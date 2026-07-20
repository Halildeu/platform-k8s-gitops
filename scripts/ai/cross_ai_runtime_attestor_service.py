"""Fixed-function service for independently attested direct-Codex reviews.

The service owns the runner-management Transit capability and the verified
Codex executable. Callers can request one canonical review and later submit a
provider-review DSSE envelope, but they cannot supply an execution receipt or
runtime payload. The measured execution is retained in a create-once SQLite
session and is the only source used for the runtime signature.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import stat
import threading
from contextlib import contextmanager
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator, Protocol
from urllib.parse import quote
from uuid import UUID, uuid4

from scripts.ai.cross_ai_runtime_authorization import (
    AUTH_AUDIENCE,
    load_runtime_authorization,
)
from scripts.ai.cross_ai_runtime_workload import WorkloadMeasurement
from scripts.ai.trusted_cross_ai_evidence import (
    build_prompt,
    build_subject,
    canonical_bytes,
)
from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.contract import (
    PROVIDER_RUNTIME_ATTESTATION_PAYLOAD_TYPE,
    EvidenceVerifier,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError, reject
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import loads_json_bytes
from scripts.github_apps.cross_ai_deployment_policy.provider import (
    CODEX_MODELS,
    EnvelopeSigner,
    ProviderExecutionReceipt,
)
from scripts.github_apps.cross_ai_deployment_policy.timeutil import parse_utc, utc_now


SESSION_REQUEST_SCHEMA = "acik.cross-ai-provider-review-runtime-session-request.v1"
SESSION_RESPONSE_SCHEMA = "acik.cross-ai-provider-review-runtime-session-response.v1"
FINALIZE_REQUEST_SCHEMA = "acik.cross-ai-provider-review-runtime-finalize-request.v1"
FINALIZE_RESPONSE_SCHEMA = "acik.cross-ai-provider-review-runtime-finalize-response.v1"
GIT_SHA = re.compile(r"^[a-f0-9]{40}$")
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
SCOPE_DIGEST = re.compile(r"^[a-f0-9]{64}$")
MAX_PROMPT_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BYTES = 5 * 1024 * 1024
ATTEST_PATH = re.compile(
    r"^/api/v1/cross-ai/provider-review-runtime/sessions/"
    r"([0-9a-f-]{36})/attest$"
)


class ReviewRunner(Protocol):
    def run(
        self,
        *,
        prompt: str,
        model: str,
        workspace: Path,
        timeout_seconds: int,
    ) -> ProviderExecutionReceipt: ...


class WorkloadVerifier(Protocol):
    def measure(self) -> WorkloadMeasurement: ...


def _load_public_json(path: Path, label: str) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        reject("PROVIDER_RUNTIME_AUTHORITY_UNAVAILABLE", f"{label} cannot be opened")
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_mode & 0o022
            or not 1 <= metadata.st_size <= MAX_REQUEST_BYTES
        ):
            reject(
                "PROVIDER_RUNTIME_AUTHORITY_INVALID",
                f"{label} permissions or size are invalid",
            )
        raw = os.read(descriptor, metadata.st_size + 1)
    except OSError:
        reject("PROVIDER_RUNTIME_AUTHORITY_UNAVAILABLE", f"{label} cannot be read")
    finally:
        os.close(descriptor)
    if len(raw) != metadata.st_size:
        reject("PROVIDER_RUNTIME_AUTHORITY_INVALID", f"{label} changed while reading")
    document = loads_json_bytes(raw, max_bytes=MAX_REQUEST_BYTES, label=label)
    if not isinstance(document, dict):
        reject("PROVIDER_RUNTIME_AUTHORITY_INVALID", f"{label} is not an object")
    return document


def _canonical_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        reject("PROVIDER_RUNTIME_REQUEST_INVALID", f"{label} is invalid")
    try:
        parsed = str(UUID(value))
    except (ValueError, AttributeError):
        reject("PROVIDER_RUNTIME_REQUEST_INVALID", f"{label} is invalid")
    if parsed != value:
        reject("PROVIDER_RUNTIME_REQUEST_INVALID", f"{label} is not canonical")
    return parsed


def execution_document(receipt: ProviderExecutionReceipt) -> dict[str, Any]:
    return {
        "providerFamily": receipt.provider_family,
        "channel": receipt.channel,
        "directProviderCli": receipt.direct_provider_cli,
        "modelId": receipt.model_id,
        "modelIdentityClass": receipt.model_identity_class,
        "reasoningEffort": receipt.reasoning_effort,
        "sandbox": receipt.sandbox,
        "ephemeral": receipt.ephemeral,
        "providerSessionId": receipt.provider_session_id,
        "providerTranscriptSha256": receipt.provider_transcript_sha256,
        "capabilitySnapshot": receipt.capability_snapshot,
        "capabilitySnapshotSha256": receipt.capability_snapshot_sha256,
        "inputSha256": receipt.input_sha256,
        "outputSha256": receipt.output_sha256,
        "resultText": receipt.result_text,
    }


def _validate_session_request(document: dict[str, Any]) -> None:
    required = {
        "schemaVersion",
        "requestId",
        "authAudience",
        "baseTipSha",
        "baseSha",
        "headSha",
        "scopeSha256",
        "subjectSha256",
        "prompt",
        "promptSha256",
        "modelId",
        "reasoningEffort",
        "sandbox",
        "ephemeral",
        "toolPolicy",
        "timeoutSeconds",
    }
    prompt = document.get("prompt")
    prompt_bytes = prompt.encode("utf-8") if isinstance(prompt, str) else b""
    if (
        set(document) != required
        or document.get("schemaVersion") != SESSION_REQUEST_SCHEMA
        or document.get("authAudience") != AUTH_AUDIENCE
        or document.get("modelId") not in CODEX_MODELS
        or document.get("reasoningEffort") != "xhigh"
        or document.get("sandbox") != "read-only"
        or document.get("ephemeral") is not True
        or document.get("toolPolicy") != "none-pre-execution"
        or not isinstance(document.get("timeoutSeconds"), int)
        or not 30 <= document["timeoutSeconds"] <= 1200
        or not prompt_bytes
        or len(prompt_bytes) > MAX_PROMPT_BYTES
        or not isinstance(document.get("promptSha256"), str)
        or document["promptSha256"]
        != "sha256:" + hashlib.sha256(prompt_bytes).hexdigest()
        or not isinstance(document.get("subjectSha256"), str)
        or DIGEST.fullmatch(document["subjectSha256"]) is None
        or not isinstance(document.get("scopeSha256"), str)
        or DIGEST.fullmatch(document["scopeSha256"]) is None
        or any(
            not isinstance(document.get(field), str)
            or GIT_SHA.fullmatch(document[field]) is None
            for field in ("baseTipSha", "baseSha", "headSha")
        )
    ):
        reject(
            "PROVIDER_RUNTIME_REQUEST_INVALID",
            "runtime session request differs from the fixed review contract",
        )
    _canonical_uuid(document.get("requestId"), "requestId")
    begin = "--- BEGIN EXACT REVIEW SCOPE ---\n"
    end = "\n--- END EXACT REVIEW SCOPE ---\n"
    if begin not in prompt or not prompt.endswith(end):
        reject(
            "PROVIDER_RUNTIME_REQUEST_INVALID",
            "runtime prompt does not contain one canonical scope",
        )
    scope_text = prompt.split(begin, 1)[1].rsplit(end, 1)[0]
    scope_bytes = scope_text.encode("utf-8")
    expected_prompt = build_prompt(
        base_tip_sha=document["baseTipSha"],
        base_sha=document["baseSha"],
        head_sha=document["headSha"],
        scope_sha256=document["scopeSha256"],
        scope_bytes=scope_bytes,
    )
    expected_subject = build_subject(
        base_tip_sha=document["baseTipSha"],
        base_sha=document["baseSha"],
        head_sha=document["headSha"],
        scope_sha256=document["scopeSha256"],
        prompt=expected_prompt,
    )
    if (
        prompt != expected_prompt
        or sha256_digest(expected_subject) != document["subjectSha256"]
        or "sha256:" + hashlib.sha256(scope_bytes).hexdigest()
        != document["scopeSha256"]
    ):
        reject(
            "PROVIDER_RUNTIME_BINDING_MISMATCH",
            "runtime prompt, scope and signed subject bindings differ",
        )


class RuntimeSessionStore:
    """Create-once, idempotent storage for measured runtime sessions."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError:
            reject(
                "PROVIDER_RUNTIME_STORE_INVALID",
                "runtime session ledger cannot be opened safely",
            )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
                or metadata.st_mode & 0o077
            ):
                reject(
                    "PROVIDER_RUNTIME_STORE_INVALID",
                    "runtime session ledger must be owner-only regular storage",
                )
        finally:
            os.close(descriptor)
        database_uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=rw"
        self.connection = sqlite3.connect(
            database_uri,
            uri=True,
            check_same_thread=False,
        )
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_sessions (
              session_id TEXT PRIMARY KEY,
              request_id TEXT NOT NULL UNIQUE,
              request_sha256 TEXT NOT NULL,
              request_json BLOB NOT NULL,
              execution_json BLOB NOT NULL,
              workload_identity TEXT NOT NULL,
              image_digest TEXT NOT NULL,
              pod_uid TEXT NOT NULL,
              provider_envelope_sha256 TEXT,
              runtime_envelope_json BLOB
            )
            """
        )
        columns = {
            row[1]
            for row in self.connection.execute(
                "PRAGMA table_info(runtime_sessions)"
            ).fetchall()
        }
        expected_columns = {
            "session_id",
            "request_id",
            "request_sha256",
            "request_json",
            "execution_json",
            "workload_identity",
            "image_digest",
            "pod_uid",
            "provider_envelope_sha256",
            "runtime_envelope_json",
        }
        if columns != expected_columns:
            self.connection.close()
            reject(
                "PROVIDER_RUNTIME_STORE_INVALID",
                "runtime session ledger schema differs from the fixed contract",
            )
        self.connection.commit()
        self.lock = threading.Lock()

    def record(
        self,
        *,
        request: dict[str, Any],
        execution: dict[str, Any],
        measurement: WorkloadMeasurement,
    ) -> tuple[str, dict[str, Any]]:
        request_bytes = canonical_bytes(request)
        request_digest = sha256_digest(request)
        execution_bytes = canonical_bytes(execution)
        with self.lock:
            existing = self.connection.execute(
                """
                SELECT session_id, request_sha256, execution_json
                FROM runtime_sessions WHERE request_id = ?
                """,
                (request["requestId"],),
            ).fetchone()
            if existing is not None:
                if existing[1] != request_digest:
                    reject(
                        "PROVIDER_RUNTIME_IDEMPOTENCY_CONFLICT",
                        "requestId was already used for different bytes",
                    )
                return existing[0], json.loads(existing[2])
            session_id = str(uuid4())
            self.connection.execute(
                """
                INSERT INTO runtime_sessions
                  (session_id, request_id, request_sha256, request_json, execution_json,
                   workload_identity, image_digest, pod_uid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    request["requestId"],
                    request_digest,
                    request_bytes,
                    execution_bytes,
                    measurement.workload_identity,
                    measurement.image_digest,
                    measurement.pod_uid,
                ),
            )
            self.connection.commit()
        return session_id, execution

    def get(
        self, session_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], WorkloadMeasurement]:
        with self.lock:
            row = self.connection.execute(
                """
                SELECT request_json, execution_json, workload_identity,
                       image_digest, pod_uid
                FROM runtime_sessions WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            reject("PROVIDER_RUNTIME_SESSION_MISSING", "runtime session is unavailable")
        return (
            json.loads(row[0]),
            json.loads(row[1]),
            WorkloadMeasurement(
                workload_identity=row[2],
                image_digest=row[3],
                pod_uid=row[4],
            ),
        )

    def by_request(
        self,
        request_id: str,
        request_sha256: str,
    ) -> tuple[str, dict[str, Any]] | None:
        with self.lock:
            row = self.connection.execute(
                """
                SELECT session_id, request_sha256, execution_json
                FROM runtime_sessions WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        if row[1] != request_sha256:
            reject(
                "PROVIDER_RUNTIME_IDEMPOTENCY_CONFLICT",
                "requestId was already used for different bytes",
            )
        return row[0], json.loads(row[2])

    def finalized(
        self,
        *,
        session_id: str,
        provider_envelope_sha256: str,
    ) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                """
                SELECT provider_envelope_sha256, runtime_envelope_json
                FROM runtime_sessions WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            reject("PROVIDER_RUNTIME_SESSION_MISSING", "runtime session is unavailable")
        if row[1] is None:
            return None
        if row[0] != provider_envelope_sha256:
            reject(
                "PROVIDER_RUNTIME_IDEMPOTENCY_CONFLICT",
                "runtime session was finalized for another provider leaf",
            )
        return json.loads(row[1])

    def finalize(
        self,
        *,
        session_id: str,
        provider_envelope_sha256: str,
        runtime_envelope: dict[str, Any],
    ) -> dict[str, Any]:
        envelope_bytes = canonical_bytes(runtime_envelope)
        with self.lock:
            row = self.connection.execute(
                """
                SELECT provider_envelope_sha256, runtime_envelope_json
                FROM runtime_sessions WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                reject(
                    "PROVIDER_RUNTIME_SESSION_MISSING",
                    "runtime session is unavailable",
                )
            if row[1] is not None:
                if row[0] != provider_envelope_sha256:
                    reject(
                        "PROVIDER_RUNTIME_IDEMPOTENCY_CONFLICT",
                        "runtime session was finalized for another provider leaf",
                    )
                return json.loads(row[1])
            self.connection.execute(
                """
                UPDATE runtime_sessions
                SET provider_envelope_sha256 = ?, runtime_envelope_json = ?
                WHERE session_id = ?
                """,
                (provider_envelope_sha256, envelope_bytes, session_id),
            )
            self.connection.commit()
        return runtime_envelope

    def close(self) -> None:
        with self.lock:
            self.connection.close()


class FixedRuntimeAttestorService:
    """Execute, measure, verify and attest one immutable review session."""

    def __init__(
        self,
        *,
        runtime_policy: dict[str, Any],
        trust_root_file: Path,
        expected_trust_root_sha256: str,
        revocations_file: Path,
        authorization_token_file: Path,
        store: RuntimeSessionStore,
        signer: EnvelopeSigner,
        runner: ReviewRunner,
        workload_verifier: WorkloadVerifier,
        workspace: Path,
    ) -> None:
        if (
            runtime_policy.get("attestorKeyId") != signer.key_id
            or runtime_policy.get("authAudience") != AUTH_AUDIENCE
            or runtime_policy.get("sessionPath")
            != "/api/v1/cross-ai/provider-review-runtime/sessions"
            or runtime_policy.get("maxAttestationLifetimeSeconds") != 600
            or runtime_policy.get("maxReplicas") != 1
        ):
            reject(
                "PROVIDER_RUNTIME_POLICY_INVALID",
                "runtime service differs from the pinned public policy",
            )
        if not workspace.resolve().is_dir():
            reject("PROVIDER_WORKSPACE_INVALID", "runtime workspace is unavailable")
        self.runtime_policy = dict(runtime_policy)
        self.authorization = load_runtime_authorization(authorization_token_file)
        self.store = store
        self.signer = signer
        self.runner = runner
        self.workload_verifier = workload_verifier
        self.workspace = workspace
        self.trust_root_file = trust_root_file
        self.expected_trust_root_sha256 = expected_trust_root_sha256
        self.revocations_file = revocations_file
        self._lock_guard = threading.Lock()
        self._request_locks: dict[str, tuple[threading.Lock, int]] = {}
        self._finalize_locks: dict[str, tuple[threading.Lock, int]] = {}

    @contextmanager
    def _keyed_lock(
        self,
        locks: dict[str, tuple[threading.Lock, int]],
        key: str,
    ) -> Iterator[None]:
        with self._lock_guard:
            lock, users = locks.get(key, (threading.Lock(), 0))
            locks[key] = (lock, users + 1)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with self._lock_guard:
                current_lock, current_users = locks[key]
                if current_lock is not lock:
                    raise RuntimeError("runtime lock identity changed")
                if current_users == 1:
                    del locks[key]
                else:
                    locks[key] = (lock, current_users - 1)

    def _evidence_verifier(self) -> EvidenceVerifier:
        trust_root = _load_public_json(self.trust_root_file, "runtime trust root")
        revocations = _load_public_json(
            self.revocations_file,
            "runtime revocations",
        )
        if sha256_digest(trust_root) != self.expected_trust_root_sha256:
            reject(
                "PROVIDER_RUNTIME_AUTHORITY_INVALID",
                "runtime trust root differs from the independent pin",
            )
        return EvidenceVerifier(
            trust_root=trust_root,
            revocations_envelope=revocations,
            now=utc_now(),
            expected_trust_root_sha256=self.expected_trust_root_sha256,
        )

    def _measurement(self) -> WorkloadMeasurement:
        measurement = self.workload_verifier.measure()
        if (
            measurement.workload_identity
            != self.runtime_policy["workloadIdentity"]
            or measurement.image_digest != self.runtime_policy["issuerImageDigest"]
        ):
            reject(
                "PROVIDER_RUNTIME_WORKLOAD_MISMATCH",
                "measured workload identity or image differs from public policy",
            )
        return measurement

    def authorize(self, header: str | None) -> None:
        self.authorization.assert_active()
        expected = f"Bearer {self.authorization.token}"
        if not isinstance(header, str) or not hmac.compare_digest(header, expected):
            reject("PROVIDER_RUNTIME_AUTH_DENIED", "runtime authorization is invalid")

    def execute(self, document: dict[str, Any]) -> dict[str, Any]:
        _validate_session_request(document)
        self.authorization.assert_request(document)
        self._evidence_verifier()
        measurement = self._measurement()
        with self._keyed_lock(self._request_locks, document["requestId"]):
            existing = self.store.by_request(
                document["requestId"],
                sha256_digest(document),
            )
            if existing is not None:
                return {
                    "schemaVersion": SESSION_RESPONSE_SCHEMA,
                    "sessionId": existing[0],
                    "execution": existing[1],
                }
            receipt = self.runner.run(
                prompt=document["prompt"],
                model=document["modelId"],
                workspace=self.workspace,
                timeout_seconds=document["timeoutSeconds"],
            )
            execution = execution_document(receipt)
            if (
                execution["inputSha256"] != document["promptSha256"]
                or execution["modelId"] != document["modelId"]
                or execution["reasoningEffort"] != "xhigh"
                or execution["sandbox"] != "read-only"
                or execution["ephemeral"] is not True
            ):
                reject(
                    "PROVIDER_RUNTIME_BINDING_MISMATCH",
                    "measured execution differs from the fixed session request",
                )
            session_id, stored_execution = self.store.record(
                request=document,
                execution=execution,
                measurement=measurement,
            )
        return {
            "schemaVersion": SESSION_RESPONSE_SCHEMA,
            "sessionId": session_id,
            "execution": stored_execution,
        }

    def finalize(self, session_id: str, document: dict[str, Any]) -> dict[str, Any]:
        _canonical_uuid(session_id, "sessionId")
        required = {
            "schemaVersion",
            "sessionId",
            "executionSha256",
            "providerReviewEnvelope",
            "providerReviewEnvelopeSha256",
            "promptSha256",
            "issuedAt",
            "expiresAt",
        }
        if (
            set(document) != required
            or document.get("schemaVersion") != FINALIZE_REQUEST_SCHEMA
            or document.get("sessionId") != session_id
            or not isinstance(document.get("executionSha256"), str)
            or DIGEST.fullmatch(document["executionSha256"]) is None
            or not isinstance(document.get("providerReviewEnvelope"), dict)
            or not isinstance(document.get("providerReviewEnvelopeSha256"), str)
            or DIGEST.fullmatch(document["providerReviewEnvelopeSha256"]) is None
            or not isinstance(document.get("promptSha256"), str)
            or DIGEST.fullmatch(document["promptSha256"]) is None
        ):
            reject(
                "PROVIDER_RUNTIME_REQUEST_INVALID",
                "runtime finalization request differs from the fixed contract",
            )
        self.authorization.assert_active()
        verifier = self._evidence_verifier()
        current_measurement = self._measurement()
        request, execution, stored_measurement = self.store.get(session_id)
        if current_measurement != stored_measurement:
            reject(
                "PROVIDER_RUNTIME_WORKLOAD_MISMATCH",
                "runtime workload changed between execution and finalization",
            )
        provider_envelope = document["providerReviewEnvelope"]
        provider_digest = sha256_digest(provider_envelope)
        if (
            document["executionSha256"] != sha256_digest(execution)
            or document["providerReviewEnvelopeSha256"] != provider_digest
            or document["promptSha256"] != request["promptSha256"]
        ):
            reject(
                "PROVIDER_RUNTIME_BINDING_MISMATCH",
                "runtime finalization differs from the stored execution",
            )
        verified = verifier.verify_provider_review(
            provider_envelope,
            request["subjectSha256"],
        )
        payload = verified.payload
        expected = {
            "providerFamily": execution["providerFamily"],
            "channel": execution["channel"],
            "directProviderCli": execution["directProviderCli"],
            "modelId": execution["modelId"],
            "modelIdentityClass": execution["modelIdentityClass"],
            "reasoningEffort": execution["reasoningEffort"],
            "sandbox": execution["sandbox"],
            "ephemeral": execution["ephemeral"],
            "providerSessionId": execution["providerSessionId"],
            "providerTranscriptSha256": execution["providerTranscriptSha256"],
            "capabilitySnapshotSha256": execution["capabilitySnapshotSha256"],
            "inputSha256": execution["inputSha256"],
            "outputSha256": execution["outputSha256"],
        }
        if any(payload.get(field) != value for field, value in expected.items()):
            reject(
                "PROVIDER_RUNTIME_BINDING_MISMATCH",
                "provider leaf differs from the stored measured execution",
            )
        issued_at = parse_utc(document.get("issuedAt"), "runtime.issuedAt")
        expires_at = parse_utc(document.get("expiresAt"), "runtime.expiresAt")
        if (
            issued_at != verified.issued_at
            or expires_at <= issued_at
            or expires_at - issued_at > timedelta(seconds=600)
        ):
            reject(
                "PROVIDER_RUNTIME_LIFETIME_INVALID",
                "runtime finalization lifetime differs from the provider leaf",
            )
        with self._keyed_lock(self._finalize_locks, session_id):
            existing_runtime = self.store.finalized(
                session_id=session_id,
                provider_envelope_sha256=provider_digest,
            )
            if existing_runtime is not None:
                return {
                    "schemaVersion": FINALIZE_RESPONSE_SCHEMA,
                    "runtimeAttestationEnvelope": existing_runtime,
                }
            runtime_payload = {
                "schemaVersion": "acik.cross-ai-provider-review-runtime-attestation.v1",
                "attestationId": str(uuid4()),
                "keyId": self.signer.key_id,
                "workloadIdentity": stored_measurement.workload_identity,
                "issuerImageDigest": stored_measurement.image_digest,
                "launcherSourceSha256": self.runtime_policy["launcherSourceSha256"],
                "providerReviewEnvelopeSha256": provider_digest,
                "promptSha256": request["promptSha256"],
                "responseSha256": execution["outputSha256"],
                "capabilitySnapshotSha256": execution["capabilitySnapshotSha256"],
                "providerSessionId": execution["providerSessionId"],
                "issuedAt": document["issuedAt"],
                "expiresAt": document["expiresAt"],
            }
            runtime_envelope = self.signer.sign_json_envelope(
                payload_type=PROVIDER_RUNTIME_ATTESTATION_PAYLOAD_TYPE,
                payload=runtime_payload,
            )
            stored = self.store.finalize(
                session_id=session_id,
                provider_envelope_sha256=provider_digest,
                runtime_envelope=runtime_envelope,
            )
        return {
            "schemaVersion": FINALIZE_RESPONSE_SCHEMA,
            "runtimeAttestationEnvelope": stored,
        }


class RuntimeAttestorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        service: FixedRuntimeAttestorService,
    ) -> None:
        self.service = service
        super().__init__(address, RuntimeAttestorHandler)


class RuntimeAttestorHandler(BaseHTTPRequestHandler):
    server: RuntimeAttestorHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, document: dict[str, Any]) -> None:
        payload = canonical_bytes(document)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _request_document(self) -> dict[str, Any]:
        if (
            self.headers.get("Content-Type") != "application/json"
            or self.headers.get("Transfer-Encoding") is not None
        ):
            reject(
                "PROVIDER_RUNTIME_REQUEST_INVALID",
                "runtime request transport is invalid",
            )
        length_text = self.headers.get("Content-Length")
        if (
            not isinstance(length_text, str)
            or not length_text.isascii()
            or not length_text.isdigit()
        ):
            reject(
                "PROVIDER_RUNTIME_REQUEST_INVALID",
                "runtime request length is invalid",
            )
        length = int(length_text)
        if not 1 <= length <= MAX_REQUEST_BYTES:
            reject(
                "PROVIDER_RUNTIME_REQUEST_INVALID",
                "runtime request size is invalid",
            )
        raw = self.rfile.read(length)
        if len(raw) != length:
            reject(
                "PROVIDER_RUNTIME_REQUEST_INVALID",
                "runtime request length changed while reading",
            )
        return loads_json_bytes(
            raw,
            max_bytes=MAX_REQUEST_BYTES,
            label="runtime attestor request",
        )

    def do_POST(self) -> None:  # noqa: N802
        try:
            self.server.service.authorize(self.headers.get("Authorization"))
            document = self._request_document()
            if self.path == "/api/v1/cross-ai/provider-review-runtime/sessions":
                result = self.server.service.execute(document)
            else:
                match = ATTEST_PATH.fullmatch(self.path)
                if match is None:
                    self._send(404, {"error": "NOT_FOUND"})
                    return
                result = self.server.service.finalize(match.group(1), document)
            self._send(200, result)
        except PolicyError as exc:
            status = 400
            if exc.code == "PROVIDER_RUNTIME_AUTH_DENIED":
                status = 401
            elif exc.code == "PROVIDER_RUNTIME_SESSION_MISSING":
                status = 404
            elif exc.code == "PROVIDER_RUNTIME_IDEMPOTENCY_CONFLICT":
                status = 409
            self._send(status, {"error": exc.code})
        except Exception:
            self._send(500, {"error": "PROVIDER_RUNTIME_INTERNAL_ERROR"})


def make_runtime_server(
    listen: str,
    port: int,
    service: FixedRuntimeAttestorService,
) -> RuntimeAttestorHTTPServer:
    return RuntimeAttestorHTTPServer((listen, port), service)


__all__ = [
    "FixedRuntimeAttestorService",
    "RuntimeSessionStore",
    "execution_document",
    "make_runtime_server",
]
