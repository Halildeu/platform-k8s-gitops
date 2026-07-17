"""Append-only SQLite observe ledger with delivery idempotency."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .canonical import sha256_digest
from .errors import reject
from .timeutil import utc_now, utc_seconds
from .webhook import DeploymentProtectionRequest


@dataclass(frozen=True)
class LedgerEvent:
    sequence: int
    event_id: str
    event_type: str
    reason_code: str
    event_hash: str


@dataclass(frozen=True)
class DecisionRecord:
    repository_id: int
    environment: str
    run_id: int
    state: str
    reason_code: str
    evidence_digest: str | None
    comment: str
    callback_status: str
    callback_http_status: int | None


class ObserveLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._connection = sqlite3.connect(
            path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA busy_timeout=5000")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    received_at TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    repository_id INTEGER NOT NULL,
                    repository TEXT NOT NULL,
                    installation_id INTEGER NOT NULL,
                    environment TEXT NOT NULL,
                    run_id INTEGER NOT NULL,
                    head_sha TEXT NOT NULL,
                    intent_ref TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    sender_id INTEGER NOT NULL
                ) STRICT;

                CREATE TABLE IF NOT EXISTS ledger_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    delivery_id TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    evidence_digest TEXT,
                    previous_hash TEXT,
                    event_hash TEXT NOT NULL UNIQUE,
                    FOREIGN KEY (delivery_id) REFERENCES deliveries(delivery_id)
                ) STRICT;

                CREATE TABLE IF NOT EXISTS decision_records (
                    repository_id INTEGER NOT NULL,
                    environment TEXT NOT NULL,
                    run_id INTEGER NOT NULL,
                    first_delivery_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('approved', 'rejected')),
                    reason_code TEXT NOT NULL,
                    evidence_digest TEXT,
                    comment TEXT NOT NULL,
                    callback_status TEXT NOT NULL CHECK (callback_status IN (
                        'Pending', 'Succeeded', 'DefinitiveFailure', 'Unknown'
                    )),
                    callback_http_status INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (repository_id, environment, run_id),
                    FOREIGN KEY (first_delivery_id) REFERENCES deliveries(delivery_id)
                ) STRICT;

                CREATE TRIGGER IF NOT EXISTS deliveries_no_update
                BEFORE UPDATE ON deliveries BEGIN
                    SELECT RAISE(ABORT, 'append-only deliveries');
                END;
                CREATE TRIGGER IF NOT EXISTS deliveries_no_delete
                BEFORE DELETE ON deliveries BEGIN
                    SELECT RAISE(ABORT, 'append-only deliveries');
                END;
                CREATE TRIGGER IF NOT EXISTS ledger_events_no_update
                BEFORE UPDATE ON ledger_events BEGIN
                    SELECT RAISE(ABORT, 'append-only ledger');
                END;
                CREATE TRIGGER IF NOT EXISTS ledger_events_no_delete
                BEFORE DELETE ON ledger_events BEGIN
                    SELECT RAISE(ABORT, 'append-only ledger');
                END;
                CREATE TRIGGER IF NOT EXISTS decision_records_no_delete
                BEFORE DELETE ON decision_records BEGIN
                    SELECT RAISE(ABORT, 'decision records cannot be deleted');
                END;
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def record_delivery(
        self,
        request: DeploymentProtectionRequest,
        *,
        received_at: datetime | None = None,
    ) -> bool:
        timestamp = utc_seconds(received_at or utc_now())
        values = (
            request.delivery_id,
            timestamp,
            request.payload_sha256,
            request.repository_id,
            request.repository,
            request.installation_id,
            request.environment,
            request.run_id,
            request.head_sha,
            request.intent_ref,
            request.request_id,
            request.sender_id,
        )
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    """
                    INSERT INTO deliveries (
                        delivery_id, received_at, payload_sha256, repository_id,
                        repository, installation_id, environment, run_id,
                        head_sha, intent_ref, request_id, sender_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                self._connection.execute("COMMIT")
                return True
            except sqlite3.IntegrityError:
                existing = self._connection.execute(
                    "SELECT payload_sha256 FROM deliveries WHERE delivery_id = ?",
                    (request.delivery_id,),
                ).fetchone()
                if existing is None:
                    self._connection.execute("ROLLBACK")
                    raise
                if existing["payload_sha256"] != request.payload_sha256:
                    self._connection.execute("ROLLBACK")
                    reject(
                        "WEBHOOK_DELIVERY_COLLISION",
                        "one delivery ID was reused with different payload bytes",
                    )
                self._connection.execute("COMMIT")
                return False
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def append_event(
        self,
        *,
        delivery_id: str,
        event_type: str,
        reason_code: str,
        evidence_digest: str | None = None,
        recorded_at: datetime | None = None,
    ) -> LedgerEvent:
        timestamp = utc_seconds(recorded_at or utc_now())
        event_id = str(uuid.uuid4())
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                delivery = self._connection.execute(
                    "SELECT delivery_id FROM deliveries WHERE delivery_id = ?",
                    (delivery_id,),
                ).fetchone()
                if delivery is None:
                    reject("LEDGER_DELIVERY_MISSING", "delivery must be recorded before event")
                previous = self._connection.execute(
                    "SELECT event_hash FROM ledger_events ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                previous_hash = previous["event_hash"] if previous else None
                event_hash = sha256_digest(
                    {
                        "domain": "acik.cross-ai-deployment-ledger-event.v1",
                        "eventId": event_id,
                        "deliveryId": delivery_id,
                        "recordedAt": timestamp,
                        "eventType": event_type,
                        "reasonCode": reason_code,
                        "evidenceDigest": evidence_digest,
                        "previousHash": previous_hash,
                    }
                )
                cursor = self._connection.execute(
                    """
                    INSERT INTO ledger_events (
                        event_id, delivery_id, recorded_at, event_type, reason_code,
                        evidence_digest, previous_hash, event_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        delivery_id,
                        timestamp,
                        event_type,
                        reason_code,
                        evidence_digest,
                        previous_hash,
                        event_hash,
                    ),
                )
                sequence = cursor.lastrowid
                if sequence is None:
                    reject("LEDGER_WRITE_FAILED", "ledger sequence was not allocated")
                self._connection.execute("COMMIT")
                return LedgerEvent(
                    sequence=sequence,
                    event_id=event_id,
                    event_type=event_type,
                    reason_code=reason_code,
                    event_hash=event_hash,
                )
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def counts(self) -> tuple[int, int]:
        with self._lock:
            deliveries = self._connection.execute(
                "SELECT COUNT(*) AS count FROM deliveries"
            ).fetchone()["count"]
            events = self._connection.execute(
                "SELECT COUNT(*) AS count FROM ledger_events"
            ).fetchone()["count"]
        return int(deliveries), int(events)

    def events_for_delivery(self, delivery_id: str) -> tuple[LedgerEvent, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT sequence, event_id, event_type, reason_code, event_hash
                FROM ledger_events WHERE delivery_id = ? ORDER BY sequence
                """,
                (delivery_id,),
            ).fetchall()
        return tuple(
            LedgerEvent(
                sequence=row["sequence"],
                event_id=row["event_id"],
                event_type=row["event_type"],
                reason_code=row["reason_code"],
                event_hash=row["event_hash"],
            )
            for row in rows
        )

    @staticmethod
    def _decision_from_row(row: sqlite3.Row) -> DecisionRecord:
        return DecisionRecord(
            repository_id=row["repository_id"],
            environment=row["environment"],
            run_id=row["run_id"],
            state=row["state"],
            reason_code=row["reason_code"],
            evidence_digest=row["evidence_digest"],
            comment=row["comment"],
            callback_status=row["callback_status"],
            callback_http_status=row["callback_http_status"],
        )

    def claim_decision(
        self,
        *,
        request: DeploymentProtectionRequest,
        state: str,
        reason_code: str,
        evidence_digest: str | None,
        comment: str,
        recorded_at: datetime | None = None,
    ) -> tuple[DecisionRecord, bool]:
        if state not in {"approved", "rejected"}:
            reject("DECISION_STATE_INVALID", "decision state is invalid")
        if not reason_code or len(reason_code) > 100 or not comment or len(comment) > 1024:
            reject("DECISION_RECORD_INVALID", "decision record fields are invalid")
        timestamp = utc_seconds(recorded_at or utc_now())
        key = (request.repository_id, request.environment, request.run_id)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    """
                    SELECT * FROM decision_records
                    WHERE repository_id = ? AND environment = ? AND run_id = ?
                    """,
                    key,
                ).fetchone()
                if row is not None:
                    if (
                        row["state"] != state
                        or row["reason_code"] != reason_code
                        or row["evidence_digest"] != evidence_digest
                        or row["comment"] != comment
                    ):
                        reject(
                            "DECISION_CONFLICT",
                            "one run cannot receive contradictory decisions",
                        )
                    self._connection.execute("COMMIT")
                    return self._decision_from_row(row), False
                self._connection.execute(
                    """
                    INSERT INTO decision_records (
                        repository_id, environment, run_id, first_delivery_id,
                        state, reason_code, evidence_digest, comment,
                        callback_status, callback_http_status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', NULL, ?, ?)
                    """,
                    (
                        *key,
                        request.delivery_id,
                        state,
                        reason_code,
                        evidence_digest,
                        comment,
                        timestamp,
                        timestamp,
                    ),
                )
                row = self._connection.execute(
                    """
                    SELECT * FROM decision_records
                    WHERE repository_id = ? AND environment = ? AND run_id = ?
                    """,
                    key,
                ).fetchone()
                self._connection.execute("COMMIT")
                return self._decision_from_row(row), True
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def complete_decision(
        self,
        *,
        request: DeploymentProtectionRequest,
        callback_status: str,
        callback_http_status: int | None,
        recorded_at: datetime | None = None,
    ) -> DecisionRecord:
        if callback_status not in {"Succeeded", "DefinitiveFailure", "Unknown"}:
            reject("DECISION_CALLBACK_STATE_INVALID", "callback result is invalid")
        timestamp = utc_seconds(recorded_at or utc_now())
        key = (request.repository_id, request.environment, request.run_id)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    """
                    SELECT * FROM decision_records
                    WHERE repository_id = ? AND environment = ? AND run_id = ?
                    """,
                    key,
                ).fetchone()
                if row is None:
                    reject("DECISION_NOT_CLAIMED", "decision must be claimed before callback")
                current = row["callback_status"]
                if current == "Succeeded":
                    if callback_status != "Succeeded":
                        reject("DECISION_CONFLICT", "successful callback cannot be contradicted")
                    self._connection.execute("COMMIT")
                    return self._decision_from_row(row)
                if current == "DefinitiveFailure" and callback_status != "DefinitiveFailure":
                    reject("DECISION_CONFLICT", "definitive callback failure cannot be changed")
                self._connection.execute(
                    """
                    UPDATE decision_records
                    SET callback_status = ?, callback_http_status = ?, updated_at = ?
                    WHERE repository_id = ? AND environment = ? AND run_id = ?
                    """,
                    (callback_status, callback_http_status, timestamp, *key),
                )
                row = self._connection.execute(
                    """
                    SELECT * FROM decision_records
                    WHERE repository_id = ? AND environment = ? AND run_id = ?
                    """,
                    key,
                ).fetchone()
                self._connection.execute("COMMIT")
                return self._decision_from_row(row)
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise


__all__ = ["DecisionRecord", "LedgerEvent", "ObserveLedger"]
