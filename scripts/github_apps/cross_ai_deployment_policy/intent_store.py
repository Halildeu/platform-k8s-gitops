"""Content-addressed signed evidence and one-time deployment intent registry."""

from __future__ import annotations

import base64
import binascii
import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, sha256_digest
from .contract import VerifiedBundle
from .errors import reject
from .timeutil import parse_utc, utc_now, utc_seconds


ACTIVE_STAGE_STATES = {"Available", "Reserved", "ApprovedPendingOutcome"}
FINAL_STAGE_STATES = {
    "Succeeded",
    "Failed",
    "CallbackUnknown",
    "RolledBack",
    "Rejected",
}
DISPATCH_STATES = {"Pending", "Sending", "Accepted", "Uncertain", "Rejected"}
ALLOWED_STAGE_TRANSITIONS = {
    "Reserved": {
        "ApprovedPendingOutcome",
        "Rejected",
        "OutcomeOverdue",
    },
    "ApprovedPendingOutcome": {
        "Succeeded",
        "Failed",
        "RolledBack",
    },
    "OutcomeOverdue": {"CallbackUnknown"},
    "CallbackUnknown": {"ApprovedPendingOutcome"},
}
MAX_STAGE_OUTCOME_WAIT = timedelta(minutes=30)
ROLLBACK_DISPATCH_HEADROOM = timedelta(minutes=15)


@dataclass(frozen=True)
class IntentRecord:
    request_id: str
    bundle_digest: str
    subject_digest: str
    grant_digest: str
    repository_id: int
    repository: str
    environment: str
    head_sha: str
    intent_ref: str
    session_digest: str
    artifact_set_digest: str
    rollback_plan_digest: str
    post_deploy_verifier_digest: str
    expires_at: str
    registration_principal: str
    triggering_actor_id: int | None
    registered_at: str
    ref_object_id: str | None
    finalized_at: str | None
    state: str


@dataclass(frozen=True)
class StageReservation:
    request_id: str
    stage: str
    run_id: int
    run_attempt: int
    app_rule_id: int
    reservation_id: str
    reservation_expires_at: str
    state: str
    idempotent: bool


@dataclass(frozen=True)
class DispatchJob:
    request_id: str
    stage: str
    installation_id: int
    repository_id: int | None
    repository: str
    workflow_path: str
    intent_ref: str | None
    head_sha: str | None
    expected_actor_id: int
    correlation_key: str | None
    state: str
    queued_at: str
    claimed_at: str | None
    snapshot_at: str | None
    pre_dispatch_run_id_watermark: int | None
    resolved_at: str | None
    http_status: int | None
    reason_code: str | None
    run_id: int | None


@dataclass(frozen=True)
class BootstrapConsumption:
    request_id: str
    stage: str
    run_id: int
    run_attempt: int
    runner_id: int
    response_digest: str
    consumed_at: str


@dataclass(frozen=True)
class IdempotentEnvelope:
    operation: str
    request_id: str
    idempotency_key: str
    request_digest: str
    identity_digest: str
    response_digest: str
    envelope: dict[str, Any]
    created_at: str


class ContentAddressedStore:
    """Small durable CAS using canonical JSON bytes and SHA-256 object names."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            reject("CAS_UNAVAILABLE", "cannot secure content-addressed store")

    @staticmethod
    def _hex(digest: str) -> str:
        if (
            not isinstance(digest, str)
            or not digest.startswith("sha256:")
            or len(digest) != 71
            or any(character not in "0123456789abcdef" for character in digest[7:])
        ):
            reject("CAS_DIGEST_INVALID", "CAS digest must be lowercase SHA-256")
        return digest[7:]

    def _path(self, digest: str) -> Path:
        hex_digest = self._hex(digest)
        return self.root / hex_digest[:2] / f"{hex_digest}.json"

    def put_json(self, value: dict[str, Any], *, expected_digest: str) -> None:
        raw = canonical_bytes(value)
        actual = sha256_digest(value)
        if actual != expected_digest:
            reject("CAS_DIGEST_MISMATCH", "object digest differs from expected digest")
        target = self._path(expected_digest)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.exists():
            try:
                existing = target.read_bytes()
            except OSError:
                reject("CAS_UNAVAILABLE", "cannot read existing CAS object")
            if existing != raw:
                reject("CAS_OBJECT_COLLISION", "CAS object bytes differ for one digest")
            return
        temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                descriptor = None
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            reject("CAS_UNAVAILABLE", "cannot durably write CAS object")
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def get_json(self, digest: str) -> dict[str, Any]:
        path = self._path(digest)
        try:
            raw = path.read_bytes()
        except OSError:
            reject("CAS_OBJECT_MISSING", "CAS object is unavailable")
        if len(raw) > 4 * 1024 * 1024:
            reject("CAS_OBJECT_INVALID", "CAS object exceeds size limit")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            reject("CAS_OBJECT_INVALID", "CAS object is not JSON")
        if not isinstance(value, dict) or canonical_bytes(value) != raw:
            reject("CAS_OBJECT_INVALID", "CAS object is not canonical JSON")
        if sha256_digest(value) != digest:
            reject("CAS_OBJECT_TAMPERED", "CAS object digest verification failed")
        return value


class IntentRegistry:
    def __init__(self, path: Path, cas: ContentAddressedStore) -> None:
        self.path = path
        self.cas = cas
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._connection = sqlite3.connect(
            path, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA busy_timeout=5000")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS intents (
                    request_id TEXT PRIMARY KEY,
                    bundle_digest TEXT NOT NULL UNIQUE,
                    subject_digest TEXT NOT NULL,
                    grant_digest TEXT NOT NULL,
                    repository_id INTEGER NOT NULL,
                    repository TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    head_sha TEXT NOT NULL,
                    intent_ref TEXT NOT NULL UNIQUE,
                    session_digest TEXT NOT NULL,
                    artifact_set_digest TEXT NOT NULL,
                    rollback_plan_digest TEXT NOT NULL,
                    post_deploy_verifier_digest TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    registration_principal TEXT NOT NULL,
                    triggering_actor_id INTEGER NOT NULL,
                    registered_at TEXT NOT NULL,
                    ref_object_id TEXT,
                    finalized_at TEXT,
                    state TEXT NOT NULL CHECK (state IN ('Registered', 'Finalized', 'Quarantined'))
                ) STRICT;

                CREATE TABLE IF NOT EXISTS intent_stages (
                    request_id TEXT NOT NULL,
                    repository_id INTEGER NOT NULL,
                    environment TEXT NOT NULL,
                    stage TEXT NOT NULL CHECK (stage IN ('apply', 'browser-evidence', 'compensating-rollback', 'transaction')),
                    stage_order INTEGER NOT NULL,
                    nonce_digest TEXT NOT NULL,
                    workflow_path TEXT NOT NULL,
                    workflow_blob_digest TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN (
                        'Available', 'Reserved', 'ApprovedPendingOutcome', 'Succeeded',
                        'Failed', 'OutcomeOverdue', 'CallbackUnknown', 'RolledBack',
                        'Rejected'
                    )),
                    run_id INTEGER,
                    run_attempt INTEGER,
                    app_rule_id INTEGER,
                    reservation_id TEXT UNIQUE,
                    reservation_expires_at TEXT,
                    PRIMARY KEY (request_id, stage),
                    FOREIGN KEY (request_id) REFERENCES intents(request_id)
                ) STRICT;

                CREATE UNIQUE INDEX IF NOT EXISTS unique_run_rule
                ON intent_stages(
                    repository_id, environment, run_id, run_attempt, app_rule_id
                )
                WHERE run_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS intent_dispatches (
                    request_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    installation_id INTEGER NOT NULL,
                    repository_id INTEGER NOT NULL,
                    repository TEXT NOT NULL,
                    workflow_path TEXT NOT NULL,
                    intent_ref TEXT NOT NULL,
                    head_sha TEXT NOT NULL,
                    expected_actor_id INTEGER NOT NULL,
                    correlation_key TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN (
                        'Pending', 'Sending', 'Accepted', 'Uncertain', 'Rejected'
                    )),
                    queued_at TEXT NOT NULL,
                    claimed_at TEXT,
                    snapshot_at TEXT,
                    pre_dispatch_run_id_watermark INTEGER,
                    resolved_at TEXT,
                    http_status INTEGER,
                    reason_code TEXT,
                    run_id INTEGER,
                    PRIMARY KEY (request_id, stage),
                    FOREIGN KEY (request_id, stage)
                        REFERENCES intent_stages(request_id, stage)
                ) STRICT;

                CREATE UNIQUE INDEX IF NOT EXISTS unique_dispatch_run
                ON intent_dispatches(repository, run_id)
                WHERE run_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS intent_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    request_id TEXT NOT NULL,
                    stage TEXT,
                    recorded_at TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    previous_hash TEXT,
                    event_hash TEXT NOT NULL UNIQUE,
                    FOREIGN KEY (request_id) REFERENCES intents(request_id)
                ) STRICT;

                CREATE TABLE IF NOT EXISTS stage_outcomes (
                    request_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    run_id INTEGER NOT NULL,
                    run_attempt INTEGER NOT NULL,
                    outcome_digest TEXT NOT NULL UNIQUE,
                    source_archive_sha256 TEXT NOT NULL,
                    target_state TEXT NOT NULL CHECK (target_state IN (
                        'Succeeded', 'Failed', 'RolledBack'
                    )),
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY (request_id, stage),
                    FOREIGN KEY (request_id, stage)
                        REFERENCES intent_stages(request_id, stage)
                ) STRICT;

                CREATE TABLE IF NOT EXISTS bootstrap_consumptions (
                    request_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    run_id INTEGER NOT NULL,
                    run_attempt INTEGER NOT NULL,
                    runner_id INTEGER NOT NULL,
                    response_digest TEXT NOT NULL UNIQUE,
                    consumed_at TEXT NOT NULL,
                    PRIMARY KEY (request_id, stage),
                    FOREIGN KEY (request_id, stage)
                        REFERENCES intent_stages(request_id, stage)
                ) STRICT;

                CREATE TABLE IF NOT EXISTS stage_outcome_receipts (
                    request_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    outcome_digest TEXT NOT NULL,
                    envelope_digest TEXT NOT NULL UNIQUE,
                    signer_key_id TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY (request_id, stage),
                    FOREIGN KEY (request_id, stage)
                        REFERENCES stage_outcomes(request_id, stage)
                ) STRICT;

                CREATE TABLE IF NOT EXISTS idempotent_envelopes (
                    operation TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    identity_digest TEXT NOT NULL,
                    response_digest TEXT NOT NULL,
                    response_json BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (operation, request_id),
                    UNIQUE (operation, idempotency_key),
                    UNIQUE (response_digest)
                ) STRICT;

                CREATE TRIGGER IF NOT EXISTS intent_events_no_update
                BEFORE UPDATE ON intent_events BEGIN
                    SELECT RAISE(ABORT, 'append-only intent events');
                END;
                CREATE TRIGGER IF NOT EXISTS intent_events_no_delete
                BEFORE DELETE ON intent_events BEGIN
                    SELECT RAISE(ABORT, 'append-only intent events');
                END;
                CREATE TRIGGER IF NOT EXISTS stage_outcomes_no_update
                BEFORE UPDATE ON stage_outcomes BEGIN
                    SELECT RAISE(ABORT, 'stage outcomes are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS stage_outcomes_no_delete
                BEFORE DELETE ON stage_outcomes BEGIN
                    SELECT RAISE(ABORT, 'stage outcomes are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS bootstrap_consumptions_no_update
                BEFORE UPDATE ON bootstrap_consumptions BEGIN
                    SELECT RAISE(ABORT, 'bootstrap consumption is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS bootstrap_consumptions_no_delete
                BEFORE DELETE ON bootstrap_consumptions BEGIN
                    SELECT RAISE(ABORT, 'bootstrap consumption is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS idempotent_envelopes_no_update
                BEFORE UPDATE ON idempotent_envelopes BEGIN
                    SELECT RAISE(ABORT, 'idempotent envelopes are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS idempotent_envelopes_no_delete
                BEFORE DELETE ON idempotent_envelopes BEGIN
                    SELECT RAISE(ABORT, 'idempotent envelopes are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS stage_outcome_receipts_no_update
                BEFORE UPDATE ON stage_outcome_receipts BEGIN
                    SELECT RAISE(ABORT, 'signed outcome receipts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS stage_outcome_receipts_no_delete
                BEFORE DELETE ON stage_outcome_receipts BEGIN
                    SELECT RAISE(ABORT, 'signed outcome receipts are immutable');
                END;
                """
            )
            stage_columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(intent_stages)")
            }
            if "workflow_path" not in stage_columns:
                # Existing observe-only registries predate dispatch orchestration.
                # Their rows remain deliberately non-dispatchable because no
                # signed workflow path can be reconstructed from the SQL row.
                self._connection.execute(
                    "ALTER TABLE intent_stages ADD COLUMN workflow_path TEXT"
                )
            self._migrate_stage_contract_v3()
            intent_columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(intents)")
            }
            if "triggering_actor_id" not in intent_columns:
                self._connection.execute(
                    "ALTER TABLE intents ADD COLUMN triggering_actor_id INTEGER"
                )
            dispatch_columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(intent_dispatches)")
            }
            for column, definition in (
                ("repository_id", "INTEGER"),
                ("intent_ref", "TEXT"),
                ("head_sha", "TEXT"),
                ("correlation_key", "TEXT"),
                ("snapshot_at", "TEXT"),
                ("pre_dispatch_run_id_watermark", "INTEGER"),
            ):
                if column not in dispatch_columns:
                    self._connection.execute(
                        f"ALTER TABLE intent_dispatches ADD COLUMN {column} {definition}"
                    )
            self._connection.executescript(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS unique_dispatch_repository_run
                ON intent_dispatches(repository_id, run_id)
                WHERE repository_id IS NOT NULL AND run_id IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS unique_active_dispatch_correlation
                ON intent_dispatches(correlation_key)
                WHERE correlation_key IS NOT NULL
                  AND state IN ('Sending', 'Uncertain');
                """
            )
            self._connection.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS intent_stage_workflow_path_insert_guard
                BEFORE INSERT ON intent_stages
                WHEN NEW.workflow_path IS NULL OR NEW.workflow_path = '' BEGIN
                    SELECT RAISE(ABORT, 'signed workflow path is required');
                END;
                CREATE TRIGGER IF NOT EXISTS intent_stage_workflow_path_update_guard
                BEFORE UPDATE OF workflow_path ON intent_stages
                WHEN NEW.workflow_path IS NULL OR NEW.workflow_path = '' BEGIN
                    SELECT RAISE(ABORT, 'signed workflow path is required');
                END;
                CREATE TRIGGER IF NOT EXISTS intent_actor_insert_guard
                BEFORE INSERT ON intents
                WHEN NEW.triggering_actor_id IS NULL
                  OR typeof(NEW.triggering_actor_id) != 'integer'
                  OR NEW.triggering_actor_id < 1 BEGIN
                    SELECT RAISE(ABORT, 'signed triggering actor is required');
                END;
                CREATE TRIGGER IF NOT EXISTS intent_actor_update_guard
                BEFORE UPDATE OF triggering_actor_id ON intents
                WHEN NEW.triggering_actor_id IS NULL
                  OR typeof(NEW.triggering_actor_id) != 'integer'
                  OR NEW.triggering_actor_id < 1 BEGIN
                    SELECT RAISE(ABORT, 'signed triggering actor is required');
                END;
                """
            )

    def _migrate_stage_contract_v3(self) -> None:
        """Expand the stage enum without mutating any historical intent row."""

        row = self._connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'intent_stages'"
        ).fetchone()
        if row is None or not isinstance(row["sql"], str):
            reject("REGISTRY_SCHEMA_INVALID", "intent stage table is unavailable")
        if "'transaction'" in row["sql"]:
            return
        columns = {
            item["name"] for item in self._connection.execute("PRAGMA table_info(intent_stages)")
        }
        expected = {
            "request_id",
            "repository_id",
            "environment",
            "stage",
            "stage_order",
            "nonce_digest",
            "workflow_path",
            "workflow_blob_digest",
            "state",
            "run_id",
            "run_attempt",
            "app_rule_id",
            "reservation_id",
            "reservation_expires_at",
        }
        if columns != expected:
            reject(
                "REGISTRY_SCHEMA_MIGRATION_REQUIRED",
                "legacy intent stage columns cannot be migrated automatically",
            )
        try:
            self._connection.execute("PRAGMA foreign_keys=OFF")
            self._connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE intent_stages_v3 (
                    request_id TEXT NOT NULL,
                    repository_id INTEGER NOT NULL,
                    environment TEXT NOT NULL,
                    stage TEXT NOT NULL CHECK (stage IN (
                        'apply', 'browser-evidence', 'compensating-rollback', 'transaction'
                    )),
                    stage_order INTEGER NOT NULL,
                    nonce_digest TEXT NOT NULL,
                    workflow_path TEXT,
                    workflow_blob_digest TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN (
                        'Available', 'Reserved', 'ApprovedPendingOutcome', 'Succeeded',
                        'Failed', 'OutcomeOverdue', 'CallbackUnknown', 'RolledBack',
                        'Rejected'
                    )),
                    run_id INTEGER,
                    run_attempt INTEGER,
                    app_rule_id INTEGER,
                    reservation_id TEXT UNIQUE,
                    reservation_expires_at TEXT,
                    PRIMARY KEY (request_id, stage),
                    FOREIGN KEY (request_id) REFERENCES intents(request_id)
                ) STRICT;
                INSERT INTO intent_stages_v3 (
                    request_id, repository_id, environment, stage, stage_order,
                    nonce_digest, workflow_path, workflow_blob_digest, state,
                    run_id, run_attempt, app_rule_id, reservation_id,
                    reservation_expires_at
                )
                SELECT
                    request_id, repository_id, environment, stage, stage_order,
                    nonce_digest, workflow_path, workflow_blob_digest, state,
                    run_id, run_attempt, app_rule_id, reservation_id,
                    reservation_expires_at
                FROM intent_stages;
                DROP TABLE intent_stages;
                ALTER TABLE intent_stages_v3 RENAME TO intent_stages;
                CREATE UNIQUE INDEX unique_run_rule
                ON intent_stages(
                    repository_id, environment, run_id, run_attempt, app_rule_id
                ) WHERE run_id IS NOT NULL;
                COMMIT;
                """
            )
        except sqlite3.Error:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            reject(
                "REGISTRY_SCHEMA_MIGRATION_FAILED",
                "legacy intent stage contract could not be preserved during v3 migration",
            )
        finally:
            self._connection.execute("PRAGMA foreign_keys=ON")
        if self._connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            reject(
                "REGISTRY_SCHEMA_MIGRATION_FAILED",
                "v3 stage migration failed the foreign-key integrity check",
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _begin(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")

    def _event(
        self,
        *,
        request_id: str,
        stage: str | None,
        from_state: str | None,
        to_state: str,
        reason_code: str,
        recorded_at: str,
    ) -> None:
        previous_row = self._connection.execute(
            "SELECT event_hash FROM intent_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous_row["event_hash"] if previous_row else None
        event_id = str(uuid.uuid4())
        event_hash = sha256_digest(
            {
                "domain": "acik.cross-ai-intent-event.v1",
                "eventId": event_id,
                "requestId": request_id,
                "stage": stage,
                "recordedAt": recorded_at,
                "fromState": from_state,
                "toState": to_state,
                "reasonCode": reason_code,
                "previousHash": previous_hash,
            }
        )
        self._connection.execute(
            """
            INSERT INTO intent_events (
                event_id, request_id, stage, recorded_at, from_state, to_state,
                reason_code, previous_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                request_id,
                stage,
                recorded_at,
                from_state,
                to_state,
                reason_code,
                previous_hash,
                event_hash,
            ),
        )

    def register(
        self,
        *,
        envelope: dict[str, Any],
        verified: VerifiedBundle,
        registration_principal: str,
        registered_at: datetime | None = None,
    ) -> bool:
        if (
            not registration_principal.startswith("spiffe://")
            or len(registration_principal) > 200
        ):
            reject(
                "REGISTRATION_PRINCIPAL_INVALID",
                "registration principal must be SPIFFE",
            )
        subject = verified.payload["subject"]
        grant = verified.payload["grant"]
        if grant["registrationPrincipal"] != registration_principal:
            reject(
                "REGISTRATION_PRINCIPAL_MISMATCH", "grant principal differs from caller"
            )
        if sha256_digest(envelope) != verified.bundle_digest:
            reject("INTENT_BUNDLE_MISMATCH", "envelope differs from verified bundle")
        self.cas.put_json(envelope, expected_digest=verified.bundle_digest)
        timestamp = utc_seconds(registered_at or utc_now())
        grant_digest = sha256_digest(grant)
        row_values = (
            verified.request_id,
            verified.bundle_digest,
            verified.subject_digest,
            grant_digest,
            subject["repositoryId"],
            subject["repository"],
            subject["environment"],
            subject["headSha"],
            subject["intentRef"],
            verified.session_digest,
            subject["artifactSetSha256"],
            subject["rollbackPlanSha256"],
            subject["postDeployVerifierSha256"],
            utc_seconds(verified.expires_at),
            registration_principal,
            grant["triggeringActorId"],
            timestamp,
            "Registered",
        )
        with self._lock:
            self._begin()
            try:
                existing = self._connection.execute(
                    "SELECT * FROM intents WHERE request_id = ?",
                    (verified.request_id,),
                ).fetchone()
                if existing is not None:
                    immutable_keys = (
                        "request_id",
                        "bundle_digest",
                        "subject_digest",
                        "grant_digest",
                        "repository_id",
                        "repository",
                        "environment",
                        "head_sha",
                        "intent_ref",
                        "session_digest",
                        "artifact_set_digest",
                        "rollback_plan_digest",
                        "post_deploy_verifier_digest",
                        "expires_at",
                        "registration_principal",
                        "triggering_actor_id",
                    )
                    immutable = tuple(existing[key] for key in immutable_keys)
                    if immutable != row_values[: len(immutable_keys)]:
                        reject(
                            "INTENT_REGISTRATION_COLLISION",
                            "request ID already has another intent",
                        )
                    self._connection.execute("COMMIT")
                    return False
                self._connection.execute(
                    """
                    INSERT INTO intents (
                        request_id, bundle_digest, subject_digest, grant_digest,
                        repository_id, repository, environment, head_sha, intent_ref,
                        session_digest, artifact_set_digest, rollback_plan_digest,
                        post_deploy_verifier_digest, expires_at, registration_principal,
                        triggering_actor_id, registered_at, state
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    row_values,
                )
                for stage in verified.payload["workflowStages"]:
                    nonce_digest = (
                        grant["transactionNonceSha256"]
                        if stage["stage"] == "transaction"
                        else grant["stageNonceSha256"][stage["stage"]]
                    )
                    self._connection.execute(
                        """
                        INSERT INTO intent_stages (
                            request_id, repository_id, environment, stage,
                            stage_order, nonce_digest, workflow_path,
                            workflow_blob_digest, state
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Available')
                        """,
                        (
                            verified.request_id,
                            subject["repositoryId"],
                            subject["environment"],
                            stage["stage"],
                            stage["order"],
                            nonce_digest,
                            stage["workflowPath"],
                            stage["workflowBlobSha256"],
                        ),
                    )
                self._event(
                    request_id=verified.request_id,
                    stage=None,
                    from_state=None,
                    to_state="Registered",
                    reason_code="SIGNED_INTENT_REGISTERED",
                    recorded_at=timestamp,
                )
                self._connection.execute("COMMIT")
                return True
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _dispatch_from_row(row: sqlite3.Row) -> DispatchJob:
        return DispatchJob(
            request_id=row["request_id"],
            stage=row["stage"],
            installation_id=row["installation_id"],
            repository_id=row["repository_id"],
            repository=row["repository"],
            workflow_path=row["workflow_path"],
            intent_ref=row["intent_ref"],
            head_sha=row["head_sha"],
            expected_actor_id=row["expected_actor_id"],
            correlation_key=row["correlation_key"],
            state=row["state"],
            queued_at=row["queued_at"],
            claimed_at=row["claimed_at"],
            snapshot_at=row["snapshot_at"],
            pre_dispatch_run_id_watermark=row["pre_dispatch_run_id_watermark"],
            resolved_at=row["resolved_at"],
            http_status=row["http_status"],
            reason_code=row["reason_code"],
            run_id=row["run_id"],
        )

    def queue_dispatch(
        self,
        *,
        request_id: str,
        stage: str,
        installation_id: int,
        repository: str,
        queued_at: datetime | None = None,
    ) -> DispatchJob:
        if installation_id < 1:
            reject(
                "DISPATCH_TARGET_INVALID",
                "dispatch App installation ID must be positive",
            )
        current = queued_at or utc_now()
        timestamp = utc_seconds(current)
        with self._lock:
            self._begin()
            try:
                intent = self._connection.execute(
                    "SELECT * FROM intents WHERE request_id = ?", (request_id,)
                ).fetchone()
                if intent is None or intent["state"] != "Finalized":
                    reject("INTENT_NOT_FINALIZED", "intent is not ready for dispatch")
                if intent["repository"] != repository:
                    reject(
                        "DISPATCH_TARGET_MISMATCH",
                        "dispatch repository differs from intent",
                    )
                expected_actor_id = intent["triggering_actor_id"]
                if (
                    not isinstance(expected_actor_id, int)
                    or isinstance(expected_actor_id, bool)
                    or expected_actor_id < 1
                ):
                    reject(
                        "DISPATCH_ACTOR_UNAVAILABLE",
                        "legacy intent has no signed triggering actor and cannot be dispatched",
                    )
                expires_at = datetime.fromisoformat(
                    intent["expires_at"].replace("Z", "+00:00")
                )
                if expires_at <= current:
                    reject("INTENT_EXPIRED", "intent grant has expired")
                stage_row = self._connection.execute(
                    "SELECT * FROM intent_stages WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                if stage_row is None:
                    reject("STAGE_NOT_FOUND", "stage is not part of the intent")
                workflow_path = stage_row["workflow_path"]
                if not isinstance(workflow_path, str) or not workflow_path:
                    reject(
                        "STAGE_WORKFLOW_UNAVAILABLE",
                        "legacy stage has no signed workflow path and cannot be dispatched",
                    )
                correlation_key = sha256_digest(
                    {
                        "domain": "acik.cross-ai-dispatch-correlation.v1",
                        "installationId": installation_id,
                        "repositoryId": intent["repository_id"],
                        "workflowPath": workflow_path,
                        "intentRef": intent["intent_ref"],
                        "headSha": intent["head_sha"],
                        "expectedActorId": expected_actor_id,
                    }
                )
                existing = self._connection.execute(
                    "SELECT * FROM intent_dispatches WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                if existing is not None:
                    immutable = (
                        installation_id,
                        intent["repository_id"],
                        repository,
                        workflow_path,
                        intent["intent_ref"],
                        intent["head_sha"],
                        expected_actor_id,
                        correlation_key,
                    )
                    if immutable != tuple(
                        existing[key]
                        for key in (
                            "installation_id",
                            "repository_id",
                            "repository",
                            "workflow_path",
                            "intent_ref",
                            "head_sha",
                            "expected_actor_id",
                            "correlation_key",
                        )
                    ):
                        reject(
                            "DISPATCH_REGISTRATION_COLLISION",
                            "stage already has another dispatch target",
                        )
                    self._connection.execute("COMMIT")
                    return self._dispatch_from_row(existing)
                if stage_row["state"] != "Available":
                    reject("GRANT_REPLAY_OR_CONSUMED", "stage grant is already bound")
                if not self._prerequisite_satisfied(request_id, stage):
                    reject(
                        "PRIOR_STAGE_NOT_VERIFIED",
                        "stage prerequisite is not satisfied",
                    )
                self._connection.execute(
                    """
                    INSERT INTO intent_dispatches (
                        request_id, stage, installation_id, repository_id, repository,
                        workflow_path, intent_ref, head_sha, expected_actor_id,
                        correlation_key, state, queued_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
                    """,
                    (
                        request_id,
                        stage,
                        installation_id,
                        intent["repository_id"],
                        repository,
                        workflow_path,
                        intent["intent_ref"],
                        intent["head_sha"],
                        expected_actor_id,
                        correlation_key,
                        timestamp,
                    ),
                )
                self._event(
                    request_id=request_id,
                    stage=stage,
                    from_state=None,
                    to_state="DispatchPending",
                    reason_code="SIGNED_STAGE_DISPATCH_QUEUED",
                    recorded_at=timestamp,
                )
                row = self._connection.execute(
                    "SELECT * FROM intent_dispatches WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                self._connection.execute("COMMIT")
                assert row is not None
                return self._dispatch_from_row(row)
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def get_dispatch(self, request_id: str, stage: str) -> DispatchJob:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM intent_dispatches WHERE request_id = ? AND stage = ?",
                (request_id, stage),
            ).fetchone()
        if row is None:
            reject("DISPATCH_NOT_FOUND", "stage dispatch does not exist")
        return self._dispatch_from_row(row)

    def claim_dispatch(
        self,
        *,
        request_id: str,
        stage: str,
        claimed_at: datetime | None = None,
    ) -> DispatchJob:
        timestamp = utc_seconds(claimed_at or utc_now())
        with self._lock:
            self._begin()
            try:
                row = self._connection.execute(
                    "SELECT * FROM intent_dispatches WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                if row is None:
                    reject("DISPATCH_NOT_FOUND", "stage dispatch does not exist")
                if row["state"] != "Pending":
                    reject(
                        "DISPATCH_ALREADY_CLAIMED",
                        "automatic dispatch is limited to one durable claim",
                    )
                cursor = self._connection.execute(
                    """
                    UPDATE intent_dispatches
                    SET state = 'Sending', claimed_at = ?
                    WHERE request_id = ? AND stage = ? AND state = 'Pending'
                    """,
                    (timestamp, request_id, stage),
                )
                if cursor.rowcount != 1:
                    reject(
                        "DISPATCH_ALREADY_CLAIMED",
                        "durable dispatch claim lost its compare-and-swap",
                    )
                self._event(
                    request_id=request_id,
                    stage=stage,
                    from_state="DispatchPending",
                    to_state="DispatchSending",
                    reason_code="DISPATCH_DURABLY_CLAIMED",
                    recorded_at=timestamp,
                )
                updated = self._connection.execute(
                    "SELECT * FROM intent_dispatches WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                self._connection.execute("COMMIT")
                assert updated is not None
                return self._dispatch_from_row(updated)
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def resolve_dispatch(
        self,
        *,
        request_id: str,
        stage: str,
        state: str,
        reason_code: str,
        http_status: int | None,
        resolved_at: datetime | None = None,
    ) -> DispatchJob:
        if state not in {"Uncertain", "Rejected"}:
            reject("DISPATCH_STATE_INVALID", "dispatch result state is invalid")
        if not reason_code or len(reason_code) > 100:
            reject("DISPATCH_REASON_INVALID", "dispatch reason code is invalid")
        if http_status is not None and not 100 <= http_status <= 599:
            reject("DISPATCH_STATUS_INVALID", "dispatch HTTP status is invalid")
        timestamp = utc_seconds(resolved_at or utc_now())
        with self._lock:
            self._begin()
            try:
                row = self._connection.execute(
                    "SELECT * FROM intent_dispatches WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                if row is None:
                    reject("DISPATCH_NOT_FOUND", "stage dispatch does not exist")
                if row["state"] != "Sending":
                    identical = (
                        row["state"] == state
                        and row["reason_code"] == reason_code
                        and row["http_status"] == http_status
                    )
                    if identical:
                        self._connection.execute("COMMIT")
                        return self._dispatch_from_row(row)
                    reject(
                        "DISPATCH_STATE_INVALID", "dispatch result cannot be rewritten"
                    )
                cursor = self._connection.execute(
                    """
                    UPDATE intent_dispatches
                    SET state = ?, resolved_at = ?, http_status = ?, reason_code = ?
                    WHERE request_id = ? AND stage = ? AND state = 'Sending'
                    """,
                    (state, timestamp, http_status, reason_code, request_id, stage),
                )
                if cursor.rowcount != 1:
                    reject(
                        "DISPATCH_STATE_INVALID",
                        "dispatch result lost its compare-and-swap",
                    )
                self._event(
                    request_id=request_id,
                    stage=stage,
                    from_state="DispatchSending",
                    to_state=f"Dispatch{state}",
                    reason_code=reason_code,
                    recorded_at=timestamp,
                )
                updated = self._connection.execute(
                    "SELECT * FROM intent_dispatches WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                self._connection.execute("COMMIT")
                assert updated is not None
                return self._dispatch_from_row(updated)
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def record_dispatch_watermark(
        self,
        *,
        request_id: str,
        stage: str,
        watermark: int,
        snapshot_at: datetime | None = None,
    ) -> DispatchJob:
        if (
            not isinstance(watermark, int)
            or isinstance(watermark, bool)
            or watermark < 0
        ):
            reject("DISPATCH_WATERMARK_INVALID", "dispatch watermark cannot be negative")
        timestamp = utc_seconds(snapshot_at or utc_now())
        with self._lock:
            self._begin()
            try:
                row = self._connection.execute(
                    "SELECT * FROM intent_dispatches WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                if row is None:
                    reject("DISPATCH_NOT_FOUND", "stage dispatch does not exist")
                if row["state"] != "Sending":
                    reject("DISPATCH_STATE_INVALID", "dispatch is not in Sending state")
                existing = row["pre_dispatch_run_id_watermark"]
                if existing is not None:
                    if existing != watermark or row["snapshot_at"] != timestamp:
                        reject("DISPATCH_WATERMARK_IMMUTABLE", "dispatch watermark cannot change")
                    self._connection.execute("COMMIT")
                    return self._dispatch_from_row(row)
                cursor = self._connection.execute(
                    """
                    UPDATE intent_dispatches
                    SET snapshot_at = ?, pre_dispatch_run_id_watermark = ?
                    WHERE request_id = ? AND stage = ? AND state = 'Sending'
                      AND pre_dispatch_run_id_watermark IS NULL
                    """,
                    (timestamp, watermark, request_id, stage),
                )
                if cursor.rowcount != 1:
                    reject("DISPATCH_WATERMARK_INVALID", "dispatch watermark CAS failed")
                updated = self._connection.execute(
                    "SELECT * FROM intent_dispatches WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                self._connection.execute("COMMIT")
                assert updated is not None
                return self._dispatch_from_row(updated)
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def mark_dispatch_posted(
        self,
        *,
        request_id: str,
        stage: str,
        reason_code: str,
        http_status: int,
        recorded_at: datetime | None = None,
    ) -> DispatchJob:
        if not reason_code or len(reason_code) > 100 or not 100 <= http_status <= 599:
            reject("DISPATCH_RESULT_INVALID", "dispatch POST result is invalid")
        timestamp = utc_seconds(recorded_at or utc_now())
        with self._lock:
            self._begin()
            try:
                row = self._connection.execute(
                    "SELECT * FROM intent_dispatches WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                if row is not None and row["state"] == "Accepted":
                    self._connection.execute("COMMIT")
                    return self._dispatch_from_row(row)
                if row is None or row["state"] != "Sending":
                    reject(
                        "DISPATCH_STATE_INVALID",
                        "dispatch POST result cannot rewrite the current state",
                    )
                if (
                    row["pre_dispatch_run_id_watermark"] is None
                    or row["snapshot_at"] is None
                ):
                    reject(
                        "DISPATCH_WATERMARK_MISSING",
                        "dispatch POST requires a durable pre-dispatch watermark",
                    )
                if row["http_status"] is not None or row["reason_code"] is not None:
                    if (
                        row["http_status"] == http_status
                        and row["reason_code"] == reason_code
                    ):
                        self._connection.execute("COMMIT")
                        return self._dispatch_from_row(row)
                    reject(
                        "DISPATCH_RESULT_IMMUTABLE",
                        "dispatch POST result cannot be rewritten",
                    )
                self._connection.execute(
                    """
                    UPDATE intent_dispatches
                    SET http_status = ?, reason_code = ?, resolved_at = ?
                    WHERE request_id = ? AND stage = ? AND state = 'Sending'
                    """,
                    (http_status, reason_code, timestamp, request_id, stage),
                )
                updated = self._connection.execute(
                    "SELECT * FROM intent_dispatches WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                self._connection.execute("COMMIT")
                assert updated is not None
                return self._dispatch_from_row(updated)
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def reconcile_dispatch(
        self,
        *,
        request_id: str,
        stage: str,
        run_id: int,
        reconciled_at: datetime | None = None,
    ) -> DispatchJob:
        if run_id < 1:
            reject(
                "DISPATCH_RUN_INVALID", "reconciled workflow run ID must be positive"
            )
        timestamp = utc_seconds(reconciled_at or utc_now())
        with self._lock:
            self._begin()
            try:
                row = self._connection.execute(
                    "SELECT * FROM intent_dispatches WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                if row is None:
                    reject("DISPATCH_NOT_FOUND", "stage dispatch does not exist")
                if row["state"] == "Accepted" and row["run_id"] == run_id:
                    self._connection.execute("COMMIT")
                    return self._dispatch_from_row(row)
                if row["state"] not in {"Sending", "Uncertain"}:
                    reject(
                        "DISPATCH_STATE_INVALID", "dispatch cannot be live-reconciled"
                    )
                if (
                    row["repository_id"] is None
                    or row["intent_ref"] is None
                    or row["head_sha"] is None
                    or row["correlation_key"] is None
                    or row["snapshot_at"] is None
                    or row["pre_dispatch_run_id_watermark"] is None
                    or run_id <= row["pre_dispatch_run_id_watermark"]
                ):
                    reject(
                        "DISPATCH_CORRELATION_INVALID",
                        "dispatch lacks a valid pre-dispatch correlation snapshot",
                    )
                cursor = self._connection.execute(
                    """
                    UPDATE intent_dispatches
                    SET state = 'Accepted', resolved_at = ?,
                        reason_code = 'DISPATCH_RECONCILED_LIVE_RUN', run_id = ?
                    WHERE request_id = ? AND stage = ?
                      AND state IN ('Sending', 'Uncertain')
                    """,
                    (timestamp, run_id, request_id, stage),
                )
                if cursor.rowcount != 1:
                    reject(
                        "DISPATCH_STATE_INVALID",
                        "dispatch reconciliation lost its compare-and-swap",
                    )
                self._event(
                    request_id=request_id,
                    stage=stage,
                    from_state=f"Dispatch{row['state']}",
                    to_state="DispatchAccepted",
                    reason_code="DISPATCH_RECONCILED_LIVE_RUN",
                    recorded_at=timestamp,
                )
                updated = self._connection.execute(
                    "SELECT * FROM intent_dispatches WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                self._connection.execute("COMMIT")
                assert updated is not None
                return self._dispatch_from_row(updated)
            except sqlite3.IntegrityError:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                reject(
                    "DISPATCH_RUN_REUSED",
                    "one GitHub workflow run cannot correlate to two dispatches",
                )
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def finalize_ref(
        self,
        *,
        request_id: str,
        ref_object_id: str,
        resolved_head_sha: str,
        finalized_at: datetime | None = None,
    ) -> bool:
        if len(ref_object_id) != 40 or any(
            c not in "0123456789abcdef" for c in ref_object_id
        ):
            reject(
                "INTENT_REF_OBJECT_INVALID", "intent ref object ID must be a full SHA"
            )
        timestamp = utc_seconds(finalized_at or utc_now())
        with self._lock:
            self._begin()
            try:
                row = self._connection.execute(
                    "SELECT * FROM intents WHERE request_id = ?", (request_id,)
                ).fetchone()
                if row is None:
                    reject("INTENT_NOT_FOUND", "intent does not exist")
                if resolved_head_sha != row["head_sha"]:
                    reject(
                        "INTENT_REF_MOVED",
                        "intent ref does not resolve to reviewed head",
                    )
                if row["state"] == "Finalized":
                    if row["ref_object_id"] != ref_object_id:
                        reject(
                            "INTENT_REF_MOVED", "finalized intent ref object changed"
                        )
                    self._connection.execute("COMMIT")
                    return False
                if row["state"] != "Registered":
                    reject(
                        "INTENT_STATE_INVALID",
                        "intent cannot be finalized from current state",
                    )
                self._connection.execute(
                    """
                    UPDATE intents SET ref_object_id = ?, finalized_at = ?, state = 'Finalized'
                    WHERE request_id = ? AND state = 'Registered'
                    """,
                    (ref_object_id, timestamp, request_id),
                )
                self._event(
                    request_id=request_id,
                    stage=None,
                    from_state="Registered",
                    to_state="Finalized",
                    reason_code="IMMUTABLE_REF_VERIFIED",
                    recorded_at=timestamp,
                )
                self._connection.execute("COMMIT")
                return True
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _intent_from_row(row: sqlite3.Row) -> IntentRecord:
        return IntentRecord(
            request_id=row["request_id"],
            bundle_digest=row["bundle_digest"],
            subject_digest=row["subject_digest"],
            grant_digest=row["grant_digest"],
            repository_id=row["repository_id"],
            repository=row["repository"],
            environment=row["environment"],
            head_sha=row["head_sha"],
            intent_ref=row["intent_ref"],
            session_digest=row["session_digest"],
            artifact_set_digest=row["artifact_set_digest"],
            rollback_plan_digest=row["rollback_plan_digest"],
            post_deploy_verifier_digest=row["post_deploy_verifier_digest"],
            expires_at=row["expires_at"],
            registration_principal=row["registration_principal"],
            triggering_actor_id=row["triggering_actor_id"],
            registered_at=row["registered_at"],
            ref_object_id=row["ref_object_id"],
            finalized_at=row["finalized_at"],
            state=row["state"],
        )

    def get(self, request_id: str) -> tuple[IntentRecord, dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM intents WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            reject("INTENT_NOT_FOUND", "intent does not exist")
        record = self._intent_from_row(row)
        return record, self.cas.get_json(record.bundle_digest)

    def get_finalized(self, request_id: str) -> tuple[IntentRecord, dict[str, Any]]:
        record, envelope = self.get(request_id)
        if record.state != "Finalized":
            reject("INTENT_NOT_FINALIZED", "exactly one finalized intent is required")
        return record, envelope

    def get_stage(self, request_id: str, stage: str) -> StageReservation:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM intent_stages WHERE request_id = ? AND stage = ?",
                (request_id, stage),
            ).fetchone()
        if row is None:
            reject("STAGE_NOT_FOUND", "stage is not part of the intent")
        required = (
            row["run_id"],
            row["run_attempt"],
            row["app_rule_id"],
            row["reservation_id"],
            row["reservation_expires_at"],
        )
        if row["state"] == "Available" or not all(
            value is not None for value in required
        ):
            reject("STAGE_NOT_RESERVED", "stage has no bound run reservation")
        return StageReservation(
            request_id=request_id,
            stage=stage,
            run_id=row["run_id"],
            run_attempt=row["run_attempt"],
            app_rule_id=row["app_rule_id"],
            reservation_id=row["reservation_id"],
            reservation_expires_at=row["reservation_expires_at"],
            state=row["state"],
            idempotent=True,
        )

    def get_stage_outcome(
        self, request_id: str, stage: str
    ) -> tuple[str, dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT outcome_digest FROM stage_outcomes "
                "WHERE request_id = ? AND stage = ?",
                (request_id, stage),
            ).fetchone()
        if row is None:
            reject(
                "STAGE_OUTCOME_NOT_FOUND", "verified prior-stage outcome is unavailable"
            )
        digest = row["outcome_digest"]
        return digest, self.cas.get_json(digest)

    def get_stage_outcome_receipt(
        self, request_id: str, stage: str
    ) -> tuple[str, dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT envelope_digest FROM stage_outcome_receipts "
                "WHERE request_id = ? AND stage = ?",
                (request_id, stage),
            ).fetchone()
        if row is None:
            reject(
                "STAGE_OUTCOME_RECEIPT_NOT_FOUND",
                "signed stage outcome receipt is unavailable",
            )
        digest = row["envelope_digest"]
        return digest, self.cas.get_json(digest)

    @staticmethod
    def _idempotent_envelope_from_row(row: sqlite3.Row) -> IdempotentEnvelope:
        raw = bytes(row["response_json"])
        if not 1 <= len(raw) <= 1024 * 1024:
            reject(
                "IDEMPOTENT_RESPONSE_INVALID",
                "stored idempotent response exceeds its bounded size",
            )
        try:
            envelope = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            reject(
                "IDEMPOTENT_RESPONSE_INVALID",
                "stored idempotent response is not JSON",
            )
        if (
            not isinstance(envelope, dict)
            or canonical_bytes(envelope) != raw
            or sha256_digest(envelope) != row["response_digest"]
        ):
            reject(
                "IDEMPOTENT_RESPONSE_INVALID",
                "stored idempotent response failed integrity verification",
            )
        return IdempotentEnvelope(
            operation=row["operation"],
            request_id=row["request_id"],
            idempotency_key=row["idempotency_key"],
            request_digest=row["request_digest"],
            identity_digest=row["identity_digest"],
            response_digest=row["response_digest"],
            envelope=envelope,
            created_at=row["created_at"],
        )

    @staticmethod
    def _validate_idempotent_identity(
        *,
        operation: str,
        request_id: str,
        idempotency_key: str,
        request_digest: str,
        identity_digest: str,
    ) -> None:
        try:
            parsed_request_id = uuid.UUID(request_id)
        except (ValueError, AttributeError, TypeError):
            reject("IDEMPOTENCY_REQUEST_INVALID", "request ID must be a UUID")
        if str(parsed_request_id) != request_id:
            reject(
                "IDEMPOTENCY_REQUEST_INVALID",
                "request ID must use canonical lowercase UUID text",
            )
        if (
            not isinstance(operation, str)
            or not operation.isascii()
            or not 1 <= len(operation) <= 80
            or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in operation)
        ):
            reject(
                "IDEMPOTENCY_OPERATION_INVALID",
                "idempotency operation is invalid",
            )
        ContentAddressedStore._hex(idempotency_key)
        ContentAddressedStore._hex(request_digest)
        ContentAddressedStore._hex(identity_digest)

    def _find_idempotent_envelope(
        self,
        *,
        operation: str,
        request_id: str,
        idempotency_key: str,
        request_digest: str,
        identity_digest: str,
    ) -> IdempotentEnvelope | None:
        rows = self._connection.execute(
            """
            SELECT * FROM idempotent_envelopes
            WHERE operation = ? AND (request_id = ? OR idempotency_key = ?)
            """,
            (operation, request_id, idempotency_key),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            reject(
                "IDEMPOTENCY_CONFLICT",
                "request ID and idempotency key resolve to different operations",
            )
        row = rows[0]
        if (
            row["request_id"] != request_id
            or row["idempotency_key"] != idempotency_key
            or row["request_digest"] != request_digest
            or row["identity_digest"] != identity_digest
        ):
            reject(
                "IDEMPOTENCY_CONFLICT",
                "idempotency key was reused with a different request or identity",
            )
        return self._idempotent_envelope_from_row(row)

    def get_idempotent_envelope(
        self,
        *,
        operation: str,
        request_id: str,
        idempotency_key: str,
        request_digest: str,
        identity_digest: str,
    ) -> IdempotentEnvelope | None:
        self._validate_idempotent_identity(
            operation=operation,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            identity_digest=identity_digest,
        )
        with self._lock:
            return self._find_idempotent_envelope(
                operation=operation,
                request_id=request_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                identity_digest=identity_digest,
            )

    def record_idempotent_envelope(
        self,
        *,
        operation: str,
        request_id: str,
        idempotency_key: str,
        request_digest: str,
        identity_digest: str,
        envelope: dict[str, Any],
        max_response_bytes: int,
        created_at: datetime | None = None,
    ) -> IdempotentEnvelope:
        self._validate_idempotent_identity(
            operation=operation,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            identity_digest=identity_digest,
        )
        if not 1 <= max_response_bytes <= 1024 * 1024:
            reject(
                "IDEMPOTENT_RESPONSE_INVALID",
                "idempotent response size limit is invalid",
            )
        response_bytes = canonical_bytes(envelope)
        if not 1 <= len(response_bytes) <= max_response_bytes:
            reject(
                "IDEMPOTENT_RESPONSE_INVALID",
                "idempotent response exceeds its operation size limit",
            )
        response_digest = sha256_digest(envelope)
        timestamp = utc_seconds(created_at or utc_now())
        with self._lock:
            self._begin()
            try:
                existing = self._find_idempotent_envelope(
                    operation=operation,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    identity_digest=identity_digest,
                )
                if existing is not None:
                    self._connection.execute("COMMIT")
                    return existing
                self._connection.execute(
                    """
                    INSERT INTO idempotent_envelopes(
                        operation, request_id, idempotency_key, request_digest,
                        identity_digest, response_digest, response_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        operation,
                        request_id,
                        idempotency_key,
                        request_digest,
                        identity_digest,
                        response_digest,
                        sqlite3.Binary(response_bytes),
                        timestamp,
                    ),
                )
                row = self._connection.execute(
                    "SELECT * FROM idempotent_envelopes "
                    "WHERE operation = ? AND request_id = ?",
                    (operation, request_id),
                ).fetchone()
                self._connection.execute("COMMIT")
                assert row is not None
                return self._idempotent_envelope_from_row(row)
            except sqlite3.IntegrityError:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                existing = self._find_idempotent_envelope(
                    operation=operation,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    identity_digest=identity_digest,
                )
                if existing is None:
                    reject(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotent response lost its unique insert race",
                    )
                return existing
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def stage_approved_at(self, request_id: str, stage: str) -> str:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT recorded_at FROM intent_events
                WHERE request_id = ? AND stage = ?
                  AND to_state = 'ApprovedPendingOutcome'
                  AND reason_code != 'RUNNER_BOOTSTRAP_CONSUMED'
                ORDER BY sequence DESC LIMIT 1
                """,
                (request_id, stage),
            ).fetchone()
        if row is None:
            reject(
                "BOOTSTRAP_STAGE_NOT_APPROVED", "stage approval event is unavailable"
            )
        return row["recorded_at"]

    def consume_bootstrap(
        self,
        *,
        request_id: str,
        stage: str,
        run_id: int,
        run_attempt: int,
        runner_id: int,
        response_digest: str,
        consumed_at: datetime | None = None,
    ) -> BootstrapConsumption:
        if min(run_id, run_attempt, runner_id) < 1:
            reject(
                "BOOTSTRAP_BINDING_INVALID",
                "bootstrap run and runner IDs must be positive",
            )
        ContentAddressedStore._hex(response_digest)
        timestamp = utc_seconds(consumed_at or utc_now())
        with self._lock:
            self._begin()
            try:
                row = self._connection.execute(
                    "SELECT * FROM intent_stages WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                if row is None:
                    reject("STAGE_NOT_FOUND", "stage is not part of the intent")
                if (
                    row["state"] != "ApprovedPendingOutcome"
                    or row["run_id"] != run_id
                    or row["run_attempt"] != run_attempt
                ):
                    reject(
                        "BOOTSTRAP_STAGE_NOT_APPROVED",
                        "bootstrap is not bound to the approved run attempt",
                    )
                existing = self._connection.execute(
                    "SELECT * FROM bootstrap_consumptions "
                    "WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                if existing is not None:
                    reject(
                        "BOOTSTRAP_ALREADY_CONSUMED",
                        "bootstrap credential is single-use",
                    )
                self._connection.execute(
                    """
                    INSERT INTO bootstrap_consumptions (
                        request_id, stage, run_id, run_attempt, runner_id,
                        response_digest, consumed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request_id,
                        stage,
                        run_id,
                        run_attempt,
                        runner_id,
                        response_digest,
                        timestamp,
                    ),
                )
                self._event(
                    request_id=request_id,
                    stage=stage,
                    from_state="ApprovedPendingOutcome",
                    to_state="ApprovedPendingOutcome",
                    reason_code="RUNNER_BOOTSTRAP_CONSUMED",
                    recorded_at=timestamp,
                )
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return BootstrapConsumption(
            request_id=request_id,
            stage=stage,
            run_id=run_id,
            run_attempt=run_attempt,
            runner_id=runner_id,
            response_digest=response_digest,
            consumed_at=timestamp,
        )

    def pending_stages(self, *, limit: int = 100) -> tuple[StageReservation, ...]:
        if not 1 <= limit <= 1000:
            reject("STAGE_QUERY_INVALID", "pending-stage query limit is invalid")
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT stages.*
                FROM intent_stages AS stages
                JOIN intents ON intents.request_id = stages.request_id
                WHERE intents.state = 'Finalized'
                  AND stages.state IN (
                      'Reserved', 'ApprovedPendingOutcome', 'OutcomeOverdue',
                      'CallbackUnknown'
                  )
                  AND stages.run_id IS NOT NULL
                ORDER BY stages.request_id, stages.stage_order
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(
            StageReservation(
                request_id=row["request_id"],
                stage=row["stage"],
                run_id=row["run_id"],
                run_attempt=row["run_attempt"],
                app_rule_id=row["app_rule_id"],
                reservation_id=row["reservation_id"],
                reservation_expires_at=row["reservation_expires_at"],
                state=row["state"],
                idempotent=True,
            )
            for row in rows
        )

    def expire_pending_stages(self, *, now: datetime | None = None) -> int:
        """Quarantine overdue outcomes; live terminal proof unlocks rollback later."""

        timestamp = utc_seconds(now or utc_now())
        with self._lock:
            self._begin()
            try:
                rows = self._connection.execute(
                    """
                    SELECT request_id, stage, state
                    FROM intent_stages
                    WHERE state IN ('Reserved', 'ApprovedPendingOutcome')
                      AND reservation_expires_at IS NOT NULL
                      AND reservation_expires_at <= ?
                    ORDER BY request_id, stage_order
                    """,
                    (timestamp,),
                ).fetchall()
                for row in rows:
                    self._connection.execute(
                        """
                        UPDATE intent_stages SET state = 'OutcomeOverdue'
                        WHERE request_id = ? AND stage = ? AND state = ?
                        """,
                        (row["request_id"], row["stage"], row["state"]),
                    )
                    self._event(
                        request_id=row["request_id"],
                        stage=row["stage"],
                        from_state=row["state"],
                        to_state="OutcomeOverdue",
                        reason_code="OUTCOME_RECONCILIATION_DEADLINE_EXCEEDED",
                        recorded_at=timestamp,
                    )
                self._connection.execute("COMMIT")
                return len(rows)
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def _prerequisite_satisfied(self, request_id: str, stage: str) -> bool:
        if stage in {"apply", "transaction"}:
            return True
        apply = self._connection.execute(
            """
            SELECT stages.state, outcomes.target_state
            FROM intent_stages AS stages
            LEFT JOIN stage_outcomes AS outcomes
              ON outcomes.request_id = stages.request_id
             AND outcomes.stage = stages.stage
            WHERE stages.request_id = ? AND stages.stage = 'apply'
            """,
            (request_id,),
        ).fetchone()
        if apply is None:
            return False
        if stage == "browser-evidence":
            return (
                apply["state"] == "Succeeded" and apply["target_state"] == "Succeeded"
            )
        return apply["state"] == "CallbackUnknown" or (
            apply["state"] == "Failed" and apply["target_state"] == "Failed"
        )

    def reserve_stage(
        self,
        *,
        request_id: str,
        stage: str,
        run_id: int,
        run_attempt: int,
        app_rule_id: int,
        now: datetime | None = None,
    ) -> StageReservation:
        if min(run_id, run_attempt, app_rule_id) < 1:
            reject(
                "STAGE_RESERVATION_INVALID",
                "run, attempt and App rule IDs must be positive",
            )
        current = now or utc_now()
        timestamp = utc_seconds(current)
        with self._lock:
            self._begin()
            try:
                intent = self._connection.execute(
                    "SELECT * FROM intents WHERE request_id = ?", (request_id,)
                ).fetchone()
                if intent is None or intent["state"] != "Finalized":
                    reject(
                        "INTENT_NOT_FINALIZED", "intent is not ready for reservation"
                    )
                expires_at = datetime.fromisoformat(
                    intent["expires_at"].replace("Z", "+00:00")
                )
                if expires_at <= current:
                    reject("INTENT_EXPIRED", "intent grant has expired")
                row = self._connection.execute(
                    "SELECT * FROM intent_stages WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                if row is None:
                    reject("STAGE_NOT_FOUND", "stage is not part of the intent")
                if row["state"] != "Available":
                    identical = (
                        row["run_id"] == run_id
                        and row["run_attempt"] == run_attempt
                        and row["app_rule_id"] == app_rule_id
                    )
                    if not identical:
                        reject(
                            "GRANT_REPLAY_OR_CONSUMED", "stage grant is already bound"
                        )
                    self._connection.execute("COMMIT")
                    return StageReservation(
                        request_id=request_id,
                        stage=stage,
                        run_id=run_id,
                        run_attempt=run_attempt,
                        app_rule_id=app_rule_id,
                        reservation_id=row["reservation_id"],
                        reservation_expires_at=row["reservation_expires_at"],
                        state=row["state"],
                        idempotent=True,
                    )
                if not self._prerequisite_satisfied(request_id, stage):
                    reject(
                        "PRIOR_STAGE_NOT_VERIFIED",
                        "stage prerequisite is not satisfied",
                    )
                reservation_id = str(uuid.uuid4())
                rollback_headroom = (
                    ROLLBACK_DISPATCH_HEADROOM if stage == "apply" else timedelta(0)
                )
                reservation_deadline = min(
                    current + MAX_STAGE_OUTCOME_WAIT,
                    expires_at - rollback_headroom,
                )
                if reservation_deadline <= current:
                    reject(
                        "GRANT_ROLLBACK_HEADROOM_INVALID",
                        "grant has no bounded outcome and rollback headroom",
                    )
                reservation_expires = utc_seconds(reservation_deadline)
                try:
                    self._connection.execute(
                        """
                        UPDATE intent_stages SET
                            state = 'Reserved', run_id = ?, run_attempt = ?, app_rule_id = ?,
                            reservation_id = ?, reservation_expires_at = ?
                        WHERE request_id = ? AND stage = ? AND state = 'Available'
                        """,
                        (
                            run_id,
                            run_attempt,
                            app_rule_id,
                            reservation_id,
                            reservation_expires,
                            request_id,
                            stage,
                        ),
                    )
                except sqlite3.IntegrityError:
                    reject(
                        "GRANT_REPLAY_OR_CONSUMED",
                        "run/attempt/App rule is already reserved",
                    )
                self._event(
                    request_id=request_id,
                    stage=stage,
                    from_state="Available",
                    to_state="Reserved",
                    reason_code="STAGE_GRANT_RESERVED",
                    recorded_at=timestamp,
                )
                self._connection.execute("COMMIT")
                return StageReservation(
                    request_id=request_id,
                    stage=stage,
                    run_id=run_id,
                    run_attempt=run_attempt,
                    app_rule_id=app_rule_id,
                    reservation_id=reservation_id,
                    reservation_expires_at=reservation_expires,
                    state="Reserved",
                    idempotent=False,
                )
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def transition_stage(
        self,
        *,
        request_id: str,
        stage: str,
        to_state: str,
        reason_code: str,
        recorded_at: datetime | None = None,
    ) -> None:
        if to_state not in FINAL_STAGE_STATES | {
            "ApprovedPendingOutcome",
            "OutcomeOverdue",
        }:
            reject("STAGE_STATE_INVALID", "target stage state is invalid")
        if to_state in {"Succeeded", "Failed", "RolledBack"}:
            reject(
                "STAGE_OUTCOME_REQUIRED",
                "terminal execution state requires an atomically recorded outcome",
            )
        timestamp = utc_seconds(recorded_at or utc_now())
        with self._lock:
            self._begin()
            try:
                row = self._connection.execute(
                    "SELECT state FROM intent_stages WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                if row is None:
                    reject("STAGE_NOT_FOUND", "stage is not part of the intent")
                from_state = row["state"]
                if to_state == from_state:
                    self._connection.execute("COMMIT")
                    return
                if to_state not in ALLOWED_STAGE_TRANSITIONS.get(from_state, set()):
                    reject(
                        "STAGE_TRANSITION_INVALID", "stage transition is not allowed"
                    )
                self._connection.execute(
                    "UPDATE intent_stages SET state = ? WHERE request_id = ? AND stage = ?",
                    (to_state, request_id, stage),
                )
                self._event(
                    request_id=request_id,
                    stage=stage,
                    from_state=from_state,
                    to_state=to_state,
                    reason_code=reason_code,
                    recorded_at=timestamp,
                )
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def record_stage_outcome(
        self,
        *,
        request_id: str,
        stage: str,
        run_id: int,
        run_attempt: int,
        outcome: dict[str, Any],
        outcome_digest: str,
        target_state: str,
        outcome_envelope: dict[str, Any] | None = None,
        outcome_envelope_digest: str | None = None,
        outcome_signer_key_id: str | None = None,
        recorded_at: datetime | None = None,
    ) -> bool:
        """Atomically persist a verified outcome and advance the one bound stage."""

        allowed_targets = {
            "apply": {"Succeeded", "Failed"},
            "browser-evidence": {"Succeeded", "Failed"},
            "compensating-rollback": {"RolledBack", "Failed"},
            "transaction": {"Succeeded", "RolledBack"},
        }
        if target_state not in allowed_targets.get(stage, set()):
            reject("STAGE_OUTCOME_STATE_INVALID", "outcome target is invalid for stage")
        conclusion = outcome.get("conclusion")
        conclusion_target = (
            {
                "success": "Succeeded",
                "failure": "Failed",
                "rolled-back": "RolledBack",
            }.get(conclusion)
            if isinstance(conclusion, str)
            else None
        )
        if (
            outcome.get("schemaVersion") != "acik.cross-ai-deployment-stage-outcome.v1"
            or outcome.get("requestId") != request_id
            or outcome.get("stage") != stage
            or outcome.get("runId") != run_id
            or outcome.get("runAttempt") != run_attempt
            or outcome.get("sourceArtifactName")
            != (
                f"faz22-view-only-transaction-final-{run_id}-{run_attempt}"
                if stage == "transaction"
                else (
                    f"cross-ai-stage-outcome-{request_id}-{stage}-"
                    f"{run_id}-{run_attempt}"
                )
            )
            or conclusion_target != target_state
        ):
            reject(
                "STAGE_OUTCOME_BINDING_MISMATCH",
                "outcome identity or conclusion differs from registry transition",
            )
        source_archive_sha256 = outcome.get("sourceArchiveSha256")
        if not isinstance(source_archive_sha256, str):
            reject(
                "STAGE_OUTCOME_BINDING_MISMATCH", "outcome archive digest is missing"
            )
        ContentAddressedStore._hex(source_archive_sha256)
        signed_receipt: tuple[dict[str, Any], str, str] | None = None
        if stage == "transaction":
            if (
                not isinstance(outcome_envelope, dict)
                or not isinstance(outcome_envelope_digest, str)
                or not isinstance(outcome_signer_key_id, str)
            ):
                reject(
                    "STAGE_OUTCOME_SIGNATURE_REQUIRED",
                    "transaction outcome requires a signed coordinator receipt",
                )
            if (
                set(outcome_envelope) != {"payloadType", "payload", "signatures"}
                or outcome_envelope.get("payloadType")
                != "application/vnd.acik.cross-ai-deployment-stage-outcome.v1+json"
                or not isinstance(outcome_envelope.get("payload"), str)
                or not isinstance(outcome_envelope.get("signatures"), list)
                or len(outcome_envelope["signatures"]) != 1
                or not isinstance(outcome_envelope["signatures"][0], dict)
                or set(outcome_envelope["signatures"][0]) != {"keyid", "sig"}
                or outcome_envelope["signatures"][0].get("keyid")
                != outcome_signer_key_id
            ):
                reject(
                    "STAGE_OUTCOME_SIGNATURE_INVALID",
                    "transaction outcome receipt envelope is malformed",
                )
            try:
                payload_bytes = base64.b64decode(
                    outcome_envelope["payload"], validate=True
                )
                signature_bytes = base64.b64decode(
                    outcome_envelope["signatures"][0].get("sig"), validate=True
                )
            except (binascii.Error, ValueError, TypeError):
                reject(
                    "STAGE_OUTCOME_SIGNATURE_INVALID",
                    "transaction outcome receipt is not canonical Base64",
                )
            if (
                payload_bytes != canonical_bytes(outcome)
                or len(signature_bytes) != 64
                or sha256_digest(outcome_envelope) != outcome_envelope_digest
            ):
                reject(
                    "STAGE_OUTCOME_SIGNATURE_INVALID",
                    "transaction outcome receipt differs from the verified outcome",
                )
            ContentAddressedStore._hex(outcome_envelope_digest)
            signed_receipt = (
                outcome_envelope,
                outcome_envelope_digest,
                outcome_signer_key_id,
            )
        elif any(
            value is not None
            for value in (
                outcome_envelope,
                outcome_envelope_digest,
                outcome_signer_key_id,
            )
        ):
            reject(
                "STAGE_OUTCOME_SIGNATURE_INVALID",
                "legacy stage outcome may not assert a v3 signed receipt",
            )
        current = recorded_at or utc_now()
        timestamp = utc_seconds(current)
        with self._lock:
            self._begin()
            try:
                row = self._connection.execute(
                    """
                    SELECT stages.*, intents.repository_id, intents.repository,
                           intents.environment, intents.head_sha, intents.intent_ref,
                           intents.session_digest, intents.artifact_set_digest,
                           intents.rollback_plan_digest,
                           intents.post_deploy_verifier_digest, intents.expires_at
                    FROM intent_stages AS stages
                    JOIN intents ON intents.request_id = stages.request_id
                    WHERE stages.request_id = ? AND stages.stage = ?
                    """,
                    (request_id, stage),
                ).fetchone()
                if row is None:
                    reject("STAGE_NOT_FOUND", "stage is not part of the intent")
                if row["run_id"] != run_id or row["run_attempt"] != run_attempt:
                    reject(
                        "STAGE_OUTCOME_BINDING_MISMATCH",
                        "outcome run differs from reservation",
                    )
                durable_binding = {
                    "repositoryId": row["repository_id"],
                    "repository": row["repository"],
                    "environment": row["environment"],
                    "headSha": row["head_sha"],
                    "intentRef": row["intent_ref"],
                    "sessionSha256": row["session_digest"],
                    "workflowBlobSha256": row["workflow_blob_digest"],
                    "artifactSetSha256": row["artifact_set_digest"],
                    "rollbackPlanSha256": row["rollback_plan_digest"],
                    "postDeployVerifierSha256": row["post_deploy_verifier_digest"],
                }
                if any(
                    outcome.get(key) != value for key, value in durable_binding.items()
                ):
                    reject(
                        "STAGE_OUTCOME_BINDING_MISMATCH",
                        "outcome differs from the durable signed-intent projection",
                    )
                expires_at = datetime.fromisoformat(
                    row["expires_at"].replace("Z", "+00:00")
                )
                if current > expires_at:
                    reject(
                        "STAGE_OUTCOME_EXPIRED", "outcome arrived after intent expiry"
                    )
                existing = self._connection.execute(
                    "SELECT * FROM stage_outcomes WHERE request_id = ? AND stage = ?",
                    (request_id, stage),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["outcome_digest"] != outcome_digest
                        or existing["source_archive_sha256"] != source_archive_sha256
                        or existing["target_state"] != target_state
                    ):
                        reject(
                            "STAGE_OUTCOME_CONFLICT",
                            "stage already has another outcome",
                        )
                    if stage == "transaction":
                        receipt_row = self._connection.execute(
                            "SELECT * FROM stage_outcome_receipts "
                            "WHERE request_id = ? AND stage = ?",
                            (request_id, stage),
                        ).fetchone()
                        assert signed_receipt is not None
                        if (
                            receipt_row is None
                            or receipt_row["outcome_digest"] != outcome_digest
                            or receipt_row["envelope_digest"] != signed_receipt[1]
                            or receipt_row["signer_key_id"] != signed_receipt[2]
                        ):
                            reject(
                                "STAGE_OUTCOME_CONFLICT",
                                "transaction signed outcome receipt is missing or changed",
                            )
                    self._connection.execute("COMMIT")
                    return False
                from_state = row["state"]
                if from_state not in {
                    "Reserved",
                    "CallbackUnknown",
                    "ApprovedPendingOutcome",
                }:
                    reject(
                        "STAGE_OUTCOME_STATE_INVALID",
                        "stage is not awaiting a verified outcome",
                    )
                if stage == "apply" and target_state == "Succeeded":
                    rollback = self._connection.execute(
                        """
                        SELECT state FROM intent_stages
                        WHERE request_id = ? AND stage = 'compensating-rollback'
                        """,
                        (request_id,),
                    ).fetchone()
                    if rollback is None or rollback["state"] != "Available":
                        reject(
                            "STAGE_ROLLBACK_IN_PROGRESS",
                            "late success cannot overtake an activated rollback",
                        )
                if from_state in {"Reserved", "CallbackUnknown"}:
                    reservation_expires = row["reservation_expires_at"]
                    if not isinstance(reservation_expires, str):
                        reject(
                            "STAGE_RESERVATION_EXPIRED",
                            "stage reservation has no bounded expiry",
                        )
                    run_started_at = outcome.get("runStartedAt")
                    if not isinstance(run_started_at, str):
                        reject(
                            "STAGE_OUTCOME_BINDING_MISMATCH",
                            "outcome has no live run start binding",
                        )
                    run_started = parse_utc(run_started_at, "stageOutcome.runStartedAt")
                    reservation_end = parse_utc(
                        reservation_expires,
                        "stageReservation.expiresAt",
                    )
                    if run_started > reservation_end:
                        reject(
                            "STAGE_RESERVATION_EXPIRED",
                            "run started after the callback reservation lease expired",
                        )
                self.cas.put_json(outcome, expected_digest=outcome_digest)
                if signed_receipt is not None:
                    self.cas.put_json(
                        signed_receipt[0], expected_digest=signed_receipt[1]
                    )
                if from_state in {"Reserved", "CallbackUnknown"}:
                    self._connection.execute(
                        "UPDATE intent_stages SET state = 'ApprovedPendingOutcome' "
                        "WHERE request_id = ? AND stage = ?",
                        (request_id, stage),
                    )
                    self._event(
                        request_id=request_id,
                        stage=stage,
                        from_state=from_state,
                        to_state="ApprovedPendingOutcome",
                        reason_code="RUN_PROGRESSION_PROVED_CALLBACK_ACCEPTANCE",
                        recorded_at=timestamp,
                    )
                    from_state = "ApprovedPendingOutcome"
                self._connection.execute(
                    """
                    INSERT INTO stage_outcomes (
                        request_id, stage, run_id, run_attempt, outcome_digest,
                        source_archive_sha256, target_state, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request_id,
                        stage,
                        run_id,
                        run_attempt,
                        outcome_digest,
                        source_archive_sha256,
                        target_state,
                        timestamp,
                    ),
                )
                if signed_receipt is not None:
                    self._connection.execute(
                        """
                        INSERT INTO stage_outcome_receipts (
                            request_id, stage, outcome_digest, envelope_digest,
                            signer_key_id, recorded_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            request_id,
                            stage,
                            outcome_digest,
                            signed_receipt[1],
                            signed_receipt[2],
                            timestamp,
                        ),
                    )
                self._connection.execute(
                    "UPDATE intent_stages SET state = ? WHERE request_id = ? AND stage = ?",
                    (target_state, request_id, stage),
                )
                self._event(
                    request_id=request_id,
                    stage=stage,
                    from_state="ApprovedPendingOutcome",
                    to_state=target_state,
                    reason_code="STAGE_OUTCOME_VERIFIED",
                    recorded_at=timestamp,
                )
                self._connection.execute("COMMIT")
                return True
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def event_count(self) -> int:
        with self._lock:
            return int(
                self._connection.execute(
                    "SELECT COUNT(*) AS count FROM intent_events"
                ).fetchone()["count"]
            )


__all__ = [
    "BootstrapConsumption",
    "ContentAddressedStore",
    "DispatchJob",
    "IntentRecord",
    "IntentRegistry",
    "StageReservation",
]
