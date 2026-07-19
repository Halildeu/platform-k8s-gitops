#!/usr/bin/env python3
"""Verify provenance-bound Faz 22.6 VIEW_ONLY viewer product evidence.

The verifier accepts only a completed GitHub Actions producer run. It fetches
the run and its unique artifact from GitHub, verifies the archive digest,
validates strict root/child schemas, and correlates independent evidence
sources before emitting a bounded, content-addressed marker.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import io
import json
import math
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple, Protocol

REMOTE_OPS_DIR = Path(__file__).resolve().parent
if str(REMOTE_OPS_DIR) not in sys.path:
    sys.path.insert(0, str(REMOTE_OPS_DIR))

from view_only_pilot_authorization_common import (
    CodexEvidenceError,
    validate_codex_advisory_comment_timing,
    validate_codex_advisory_evidence,
)
from cross_ai_authority import (
    AuthorityUnavailable,
    load_authority_for_evidence,
)
from prepare_cross_ai_scope import MAX_SCOPE_BYTES, derive_scope


ROOT = Path(__file__).resolve().parents[2]
ROOT_SCHEMA = ROOT / "schema/faz22-6-view-only-viewer-product-evidence-root-v2.schema.json"
CHILD_SCHEMA = ROOT / "schema/faz22-6-view-only-viewer-product-evidence-child-v2.schema.json"
OWNER_POLICY_V2 = ROOT / "config/faz22-6-view-only-pilot-owner-policy.v2.json"
OWNER_POLICY_V1 = ROOT / "config/faz22-6-view-only-pilot-owner-policy.v1.json"
OWNER_POLICY_HISTORY = ROOT / "config/faz22-6-view-only-pilot-owner-policy-history"
REVOCATION_LEDGER = ROOT / "config/faz22-6-view-only-pilot-authorization-revocations.v1.json"

EVIDENCE_SCHEMA = "faz22.6.viewOnlyViewerProductEvidence.v2"
VERIFIER_SCHEMA = "faz22.6.viewOnlyViewerProductEvidenceVerifier.v2"
MARKER = "F22_6_VIEW_ONLY_VIEWER_PRODUCT_ACCEPTANCE: v2"
AUTHORIZATION_SCHEMA = "faz22.6-view-only-pilot-protected-authorization-v2"
OWNER_POLICY_SCHEMA_V2 = "faz22.6-view-only-pilot-owner-policy-v2"
OWNER_POLICY_SCHEMA_V1 = "faz22.6-view-only-pilot-owner-policy-v1"
LEGACY_POLICY_CANONICAL_SHA256 = "sha256:6da9283282902ba9bd35df2b730e05eeff5254734b83fb994f7e7c3908fef265"
LEGACY_V1_ISSUANCE_CUTOFF = datetime(2026, 7, 19, 0, 0, tzinfo=timezone.utc)
EXPECTED_REPOSITORY = "Halildeu/platform-k8s-gitops"
EXPECTED_WORKFLOW_PATH = ".github/workflows/faz22-6-view-only-viewer-product-evidence.yml"
EXPECTED_WORKFLOW_NAME = "Faz 22.6 VIEW_ONLY viewer product evidence"
EXPECTED_ACTIVATION_WORKFLOW_PATH = ".github/workflows/apply-view-only-viewer-pilot-enable.yml"
EXPECTED_ACTIVATION_WORKFLOW_NAME = "Apply #2373 VIEW_ONLY viewer product pilot surface"
EXPECTED_CHILD_TYPES = frozenset({"browser", "broker", "audit", "d30", "negative", "termination", "operator"})
EXPECTED_SOURCE_WORKFLOWS = {
    evidence_type: (
        f".github/workflows/faz22-6-view-only-viewer-{evidence_type}-evidence.yml",
        f"Faz 22.6 VIEW_ONLY viewer {evidence_type} evidence",
    )
    for evidence_type in EXPECTED_CHILD_TYPES
}
NEGATIVE_CASES = (
    "noAuth", "wrongRole", "wrongTenant", "wrongDevice", "expired",
    "revoked", "replayed", "overConcurrency", "disconnectedViewer",
)


class NegativeCaseContract(NamedTuple):
    outcome: str
    http_status: int | None
    method: str
    target_class: str
    credential_class: str
    path_template: str


NEGATIVE_CASE_CONTRACT = {
    # JwtBearerOperatorAuthenticator treats a missing required role as an
    # unauthenticated identity. That is deliberately a 401, not the opaque 404
    # used only after an operator identity has passed authentication.
    "noAuth": NegativeCaseContract(
        "unauthorized", 401, "GET", "viewer-product-channel", "absent",
        "/internal/remote-bridge/operator/sessions/{session}/view?streamId={stream}",
    ),
    "wrongRole": NegativeCaseContract(
        "unauthorized", 401, "GET", "viewer-product-channel", "authenticated-wrong-role",
        "/internal/remote-bridge/operator/sessions/{session}/view?streamId={stream}",
    ),
    "wrongTenant": NegativeCaseContract(
        "not-found", 404, "GET", "viewer-product-channel", "authenticated-wrong-tenant",
        "/internal/remote-bridge/operator/sessions/{session}/view?streamId={stream}",
    ),
    "wrongDevice": NegativeCaseContract(
        "not-found", 404, "POST", "operator-session-open-channel", "authenticated-wrong-device",
        "/internal/remote-bridge/operator/sessions",
    ),
    # Expiry and replay are agent-side signed-permit properties. The real
    # non-prod acceptance controller pushes the malformed permit to the agent
    # and returns 422 only after the agent's deny frame is observed.
    "expired": NegativeCaseContract(
        "expired", 422, "POST", "agent-permit-channel", "expired-permit",
        "/internal/remote-bridge/operator/sessions/{session}/negative-probes/expired-permit",
    ),
    "revoked": NegativeCaseContract(
        "revoked", 404, "GET", "viewer-product-channel", "revoked-session",
        "/internal/remote-bridge/operator/sessions/{session}/view?streamId={stream}",
    ),
    "replayed": NegativeCaseContract(
        "replay-rejected", 422, "POST", "agent-permit-channel", "replayed-permit",
        "/internal/remote-bridge/operator/sessions/{session}/negative-probes/replay",
    ),
    "overConcurrency": NegativeCaseContract(
        "capacity-rejected", 409, "GET", "viewer-product-channel", "authorized-second-viewer",
        "/internal/remote-bridge/operator/sessions/{session}/view?streamId={stream}",
    ),
    # A client disconnect ends an already-admitted SSE response; there is no
    # second HTTP response status to record, so the canonical value is null.
    "disconnectedViewer": NegativeCaseContract(
        "stream-closed", None, "GET", "viewer-product-channel", "authorized-disconnected-viewer",
        "/internal/remote-bridge/operator/sessions/{session}/view?streamId={stream}",
    ),
}
TERMINATION_CASES = (
    "localAbort", "killOrRevoke", "ttlExpiry", "heartbeatLoss",
    "indicatorLoss",
)


def expected_termination_product_signals(case_name: str) -> dict[str, bool]:
    signals = {
        "viewerClosed": True,
        "brokerSessionTerminal": True,
        "agentEventObserved": True,
        "viewStopAuditVerified": True,
    }
    if case_name == "localAbort":
        signals.update({"endpointUserInitiated": True, "consentLeaseRevoked": True})
    return signals

FIRST_FRAME_MAX_MS = 5_000
STEADY_P95_MAX_MS = 2_000
MAX_BROKER_DROP_RATE = 0.20
MAX_RENDER_LOSS_RATE = 0.05
MAX_RECONNECTS = 1
MIN_RENDERED_FRAMES = 100
MIN_PILOT_SECONDS = 300
MAX_PILOT_SECONDS = 1_800
MAX_EVIDENCE_AGE = timedelta(hours=24)
MARKER_VALIDITY = timedelta(hours=24)
RUN_CLOCK_SKEW = timedelta(minutes=5)
MAX_ACTIVATION_TO_PILOT_DELAY = timedelta(minutes=35)
# Isolated negative and termination sessions share one protected authorization.
# The cluster watchdog and signed authorization expiry remain the tighter bound.
MAX_MATRIX_WINDOW = timedelta(minutes=120)
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_FILES = 32
MAX_COMPRESSION_RATIO = 100

SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SECRET_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"data:image/[A-Za-z0-9.+-]+;base64,", re.IGNORECASE),
)
SENSITIVE_KEYS = {
    "access_token", "refresh_token", "token", "authorization", "bearer", "jwt",
    "credential", "password", "secret", "cookie", "private_key", "data_b64",
    "payload_b64", "frame_bytes", "screen_content", "raw_screen", "image_bytes",
    "session_id", "tenant_id", "operator_id", "device_id", "viewer_id",
}


class EvidenceError(Exception):
    pass


class ApiClient(Protocol):
    def get_json(self, path: str) -> dict[str, Any]: ...

    def get_bytes(self, path: str) -> bytes: ...


@dataclass(frozen=True)
class VerifiedArchive:
    artifact: dict[str, Any]
    archive_digest: str
    files: dict[str, bytes]


class GitHubClient:
    def __init__(self, token: str, api_base: str = "https://api.github.com", timeout: int = 30):
        if not token:
            raise EvidenceError("GitHub token is required through the configured environment variable")
        self.token = token
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, accept: str) -> bytes:
        if not path.startswith("/"):
            raise EvidenceError("GitHub API path must be absolute")
        request = urllib.request.Request(
            f"{self.api_base}{path}",
            headers={
                "Accept": accept,
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "faz22-6-view-only-evidence-verifier-v2",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read(MAX_ARCHIVE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise EvidenceError(f"GitHub API {path} returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EvidenceError(f"GitHub API request failed for {path}: {exc}") from exc

    def get_json(self, path: str) -> dict[str, Any]:
        raw = self._request(path, "application/vnd.github+json")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"GitHub API {path} returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise EvidenceError(f"GitHub API {path} did not return an object")
        return value

    def get_bytes(self, path: str) -> bytes:
        raw = self._request(path, "application/vnd.github+json")
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise EvidenceError("artifact archive exceeds the maximum compressed size")
        return raw


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def digest_json(value: Any) -> str:
    return digest_bytes(canonical_bytes(value))


def canonical_environment_reviewer_set(
    environment: dict[str, Any], triggering_actor: str,
) -> tuple[int, str]:
    rules = environment.get("protection_rules")
    required = [
        rule for rule in rules
        if isinstance(rule, dict) and rule.get("type") == "required_reviewers"
    ] if isinstance(rules, list) else []
    if len(required) != 1 or required[0].get("prevent_self_review") is not True:
        raise EvidenceError("protected environment self-review prevention is absent")
    reviewers = required[0].get("reviewers")
    if not isinstance(reviewers, list) or not reviewers:
        raise EvidenceError("protected environment reviewer set is absent")
    identities = []
    for reviewer in reviewers:
        if not isinstance(reviewer, dict) or reviewer.get("type") not in {"User", "Team"}:
            raise EvidenceError("protected environment reviewer entry is invalid")
        subject = reviewer.get("reviewer")
        if not isinstance(subject, dict) or not isinstance(subject.get("id"), int):
            raise EvidenceError("protected environment reviewer identity is invalid")
        name = subject.get("login") if reviewer["type"] == "User" else subject.get("slug")
        if not isinstance(name, str) or not name:
            raise EvidenceError("protected environment reviewer name is invalid")
        if reviewer["type"] == "User" and name.casefold() == triggering_actor.casefold():
            raise EvidenceError("activation actor is also a protected environment reviewer")
        identities.append({"type": reviewer["type"], "id": subject["id"], "name": name})
    identities.sort(key=lambda item: (item["type"], item["id"], item["name"]))
    return len(identities), digest_json(identities)


def load_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be a JSON object")
    return value


def load_json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        return load_json_bytes(path.read_bytes(), label)
    except OSError as exc:
        raise EvidenceError(f"{label} is unavailable") from exc


def load_schema(path: Path) -> dict[str, Any]:
    try:
        return load_json_bytes(path.read_bytes(), str(path))
    except OSError as exc:
        raise EvidenceError(f"cannot read schema {path}: {exc}") from exc


def validate_schema(instance: dict[str, Any], schema_path: Path, label: str) -> None:
    try:
        from jsonschema import Draft202012Validator  # type: ignore
    except ImportError as exc:
        raise EvidenceError("jsonschema is required: python3 -m pip install jsonschema") from exc
    schema = load_schema(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        details = []
        for error in errors[:20]:
            field = ".".join(str(part) for part in error.absolute_path) or "$"
            details.append(f"{field}: {error.message}")
        raise EvidenceError(f"{label} schema invalid: " + "; ".join(details))


def parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EvidenceError(f"{label} must be an RFC3339 UTC timestamp using Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError(f"{label} must be an RFC3339 UTC timestamp") from exc
    if parsed.utcoffset() != timedelta(0):
        raise EvidenceError(f"{label} must use UTC")
    return parsed.astimezone(timezone.utc)


def utc_seconds(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalized_key(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.replace("-", "_").replace(".", "_").lower()


def scan_hygiene(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if normalized_key(str(key)) in SENSITIVE_KEYS:
                findings.append(f"{child_path}: forbidden sensitive/raw identifier key")
            findings.extend(scan_hygiene(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(scan_hygiene(child, f"{path}[{index}]"))
    elif isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_PATTERNS):
        findings.append(f"{path}: secret or screen-content shaped value")
    return findings


def validate_repository(repository: str) -> None:
    if repository != EXPECTED_REPOSITORY or not REPOSITORY.fullmatch(repository):
        raise EvidenceError(f"repository must be exactly {EXPECTED_REPOSITORY}")


def fetch_run(
    client: ApiClient, repository: str, run_id: int, expected_name: str = EXPECTED_WORKFLOW_NAME,
    expected_path: str = EXPECTED_WORKFLOW_PATH, label: str = "producer",
) -> dict[str, Any]:
    run = client.get_json(f"/repos/{repository}/actions/runs/{run_id}")
    required = {
        "id": run_id,
        "status": "completed",
        "conclusion": "success",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "name": expected_name,
        "path": expected_path,
    }
    for key, expected in required.items():
        if run.get(key) != expected:
            raise EvidenceError(f"{label} run {key} must be {expected!r}")
    if not isinstance(run.get("run_attempt"), int) or run["run_attempt"] < 1:
        raise EvidenceError(f"{label} run_attempt is invalid")
    if not isinstance(run.get("head_sha"), str) or not re.fullmatch(r"[a-f0-9]{40}", run["head_sha"]):
        raise EvidenceError(f"{label} run head_sha is invalid")
    for field in ("run_started_at", "updated_at"):
        parse_utc(run.get(field), f"{label} run {field}")
    return run


def fetch_unique_artifact(client: ApiClient, repository: str, run_id: int) -> dict[str, Any]:
    listing = client.get_json(f"/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100")
    artifacts = listing.get("artifacts")
    if not isinstance(artifacts, list):
        raise EvidenceError("producer artifact listing is invalid")
    expected_name = f"faz22-6-view-only-viewer-product-evidence-{run_id}"
    matches = [artifact for artifact in artifacts if isinstance(artifact, dict) and artifact.get("name") == expected_name]
    if len(matches) != 1:
        raise EvidenceError("producer run must contain exactly one expected viewer product evidence artifact")
    artifact = matches[0]
    if artifact.get("expired") is not False:
        raise EvidenceError("viewer product evidence artifact is expired")
    if not isinstance(artifact.get("id"), int) or artifact["id"] < 1:
        raise EvidenceError("viewer product evidence artifact id is invalid")
    if not isinstance(artifact.get("digest"), str) or not SHA256.fullmatch(artifact["digest"]):
        raise EvidenceError("viewer product evidence artifact has no valid GitHub digest")
    workflow_run = artifact.get("workflow_run")
    if not isinstance(workflow_run, dict) or workflow_run.get("id") != run_id:
        raise EvidenceError("artifact is not bound to the requested producer run")
    for field in ("created_at", "updated_at"):
        parse_utc(artifact.get(field), f"artifact {field}")
    return artifact


def safe_archive_files(raw_archive: bytes) -> dict[str, bytes]:
    if len(raw_archive) > MAX_ARCHIVE_BYTES:
        raise EvidenceError("artifact archive exceeds the maximum compressed size")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw_archive))
    except zipfile.BadZipFile as exc:
        raise EvidenceError("artifact download is not a valid ZIP archive") from exc
    files: dict[str, bytes] = {}
    total_size = 0
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_FILES:
        raise EvidenceError("artifact archive contains too many entries")
    for info in members:
        name = info.filename
        path = PurePosixPath(name)
        mode = info.external_attr >> 16
        if (
            not name
            or "\\" in name
            or path.is_absolute()
            or ".." in path.parts
            or any(part in {"", "."} for part in path.parts)
            or stat.S_ISLNK(mode)
            or info.flag_bits & 0x1
        ):
            raise EvidenceError(f"artifact archive contains unsafe entry: {name!r}")
        if info.is_dir():
            continue
        if name in files:
            raise EvidenceError(f"artifact archive contains duplicate entry: {name}")
        if info.compress_size == 0 and info.file_size > 0:
            raise EvidenceError(f"artifact archive entry has an invalid compression ratio: {name}")
        if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            raise EvidenceError(f"artifact archive entry exceeds compression-ratio limit: {name}")
        total_size += info.file_size
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise EvidenceError("artifact archive exceeds the maximum uncompressed size")
        value = archive.read(info)
        if len(value) != info.file_size:
            raise EvidenceError(f"artifact archive entry length mismatch: {name}")
        files[name] = value
    return files


def fetch_verified_archive(client: ApiClient, repository: str, run_id: int) -> VerifiedArchive:
    artifact = fetch_unique_artifact(client, repository, run_id)
    raw_archive = client.get_bytes(f"/repos/{repository}/actions/artifacts/{artifact['id']}/zip")
    actual_digest = digest_bytes(raw_archive)
    if actual_digest != artifact["digest"]:
        raise EvidenceError("downloaded artifact digest does not match GitHub artifact metadata")
    return VerifiedArchive(artifact=artifact, archive_digest=actual_digest, files=safe_archive_files(raw_archive))


def source_artifact_files(evidence_type: str) -> set[str]:
    files = {f"evidence/{evidence_type}.json"}
    if evidence_type == "browser":
        files.add("evidence/consent.json")
        files.add("evidence/consent-source.json")
    if evidence_type in {"negative", "termination"}:
        case_names = NEGATIVE_CASES if evidence_type == "negative" else TERMINATION_CASES
        files.update(f"attestations/{evidence_type}/{name}.json" for name in case_names)
        files.add(f"observations/{evidence_type}.jsonl")
        if evidence_type == "termination":
            # The product emits a durable, hash-chained VIEW_STOP only after an
            # admitted viewer stream. Authentication/authorization rejects do
            # not invent a tenant audit identity; their protected source
            # artifact is the canonical runtime observation itself.
            files.add("audit/termination.jsonl")
    return files


def load_canonical_matrix_jsonl(
    raw: bytes, label: str, expected_cases: tuple[str, ...],
) -> dict[str, tuple[dict[str, Any], bytes]]:
    try:
        lines = raw.splitlines(keepends=True)
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EvidenceError(f"{label} is not UTF-8") from exc
    entries: dict[str, tuple[dict[str, Any], bytes]] = {}
    for line_number, line in enumerate(lines, 1):
        if not line.endswith(b"\n") or not line.strip():
            raise EvidenceError(f"{label} line {line_number} is not a canonical JSONL record")
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EvidenceError(f"{label} line {line_number} is invalid JSON") from exc
        if not isinstance(value, dict) or canonical_bytes(value) + b"\n" != line:
            raise EvidenceError(f"{label} line {line_number} is not canonical JSON")
        case_name = value.get("caseName")
        if case_name not in expected_cases or case_name in entries:
            raise EvidenceError(f"{label} case identity is missing, unknown or duplicated")
        entries[case_name] = (value, line)
    if set(entries) != set(expected_cases):
        raise EvidenceError(f"{label} case set mismatch")
    if tuple(entries) != expected_cases:
        raise EvidenceError(f"{label} case order mismatch")
    return entries


def require_archive_file(files: dict[str, bytes], path: str) -> bytes:
    try:
        return files[path]
    except KeyError as exc:
        raise EvidenceError(f"required source artifact file is missing: {path}") from exc


def validate_matrix_supporting_evidence(
    evidence_type: str, case_name: str, attestation: dict[str, Any],
    snapshot: dict[str, Any], snapshot_raw: bytes,
    audit: dict[str, Any] | None = None, audit_raw: bytes | None = None,
) -> None:
    require_equal(digest_bytes(snapshot_raw), attestation["runtimeSnapshotSha256"],
                  f"{evidence_type} {case_name} runtime snapshot digest")

    common_snapshot_keys = {
        "schemaVersion", "caseName", "sourceRevision", "observedAt", "binding",
    }
    specific_snapshot_keys = (
        {"request", "response", "delivery", "agentDeny", "evidenceSource"}
        if evidence_type == "negative"
        else {"trigger", "triggeredAtEpochMillis", "deliveryEndedAtEpochMillis", "counters", "terminal"}
    )
    if set(snapshot) != common_snapshot_keys | specific_snapshot_keys:
        raise EvidenceError(f"{evidence_type} {case_name} runtime snapshot field set mismatch")
    expected_snapshot_schema = (
        "faz22.6.viewOnlyViewerNegativeRuntimeSnapshot.v1"
        if evidence_type == "negative"
        else "faz22.6.viewOnlyViewerTerminationRuntimeSnapshot.v1"
    )
    require_equal(snapshot["schemaVersion"], expected_snapshot_schema,
                  f"{evidence_type} {case_name} runtime snapshot schema")
    for field in ("caseName", "sourceRevision", "observedAt", "binding"):
        require_equal(snapshot[field], attestation[field],
                      f"{evidence_type} {case_name} runtime snapshot {field}")

    if evidence_type == "negative":
        require_equal(snapshot["request"], attestation["request"],
                      f"negative {case_name} runtime request")
        expected_source = {
            "wrongDevice": "operator-session-open-http-probe",
            "expired": "agent-error-ledger-and-http-probe",
            "replayed": "agent-error-ledger-and-http-probe",
        }.get(case_name, "viewer-http-and-metric-probe")
        require_equal(snapshot["evidenceSource"], expected_source,
                      f"negative {case_name} evidence source")
        if set(snapshot["response"]) != {
            "httpStatus", "bodyClass", "bodyLength", "bodySha256",
            "screenContentPersisted", "artifactRepresentation",
        }:
            raise EvidenceError(f"negative {case_name} runtime response field set mismatch")
        require_equal(snapshot["response"]["httpStatus"], attestation["result"]["httpStatus"],
                      f"negative {case_name} runtime HTTP status")
        expected_body_class = (
            "agent-deny-redacted" if case_name in {"expired", "replayed"}
            else "stream-content-digested-no-persistence" if case_name == "disconnectedViewer"
            else "empty-or-opaque"
        )
        require_equal(snapshot["response"]["bodyClass"], expected_body_class,
                      f"negative {case_name} response body class")
        body_length = snapshot["response"]["bodyLength"]
        if not isinstance(body_length, int) or body_length < 0:
            raise EvidenceError(f"negative {case_name} response body length is invalid")
        if expected_body_class == "agent-deny-redacted" and body_length == 0:
            raise EvidenceError(f"negative {case_name} agent deny response body is empty")
        if not SHA256.fullmatch(str(snapshot["response"]["bodySha256"])):
            raise EvidenceError(f"negative {case_name} response body digest is invalid")
        require_equal(snapshot["response"]["screenContentPersisted"], False,
                      f"negative {case_name} screen-content persistence")
        require_equal(snapshot["response"]["artifactRepresentation"], "hash-and-length-only",
                      f"negative {case_name} artifact representation")
        if set(snapshot["delivery"]) != {
            "framesBefore", "framesAfter", "streamClosed",
            "viewerRejectedBefore", "viewerRejectedAfter",
            "metricsBeforeObservedAt", "metricsAfterObservedAt",
        }:
            raise EvidenceError(f"negative {case_name} runtime delivery field set mismatch")
        before = snapshot["delivery"]["framesBefore"]
        after = snapshot["delivery"]["framesAfter"]
        if not all(isinstance(value, int) and value >= 0 for value in (before, after)):
            raise EvidenceError(f"negative {case_name} runtime frame counters are invalid")
        require_equal(after, before, f"negative {case_name} no post-deny frame delivery")
        require_equal(snapshot["delivery"]["streamClosed"], True,
                      f"negative {case_name} stream closure")
        rejected_before = snapshot["delivery"]["viewerRejectedBefore"]
        rejected_after = snapshot["delivery"]["viewerRejectedAfter"]
        if not all(isinstance(value, int) and value >= 0
                   for value in (rejected_before, rejected_after)):
            raise EvidenceError(f"negative {case_name} viewer rejection counters are invalid")
        metrics_before = parse_utc(snapshot["delivery"]["metricsBeforeObservedAt"],
                                   f"negative {case_name} metricsBeforeObservedAt")
        metrics_after = parse_utc(snapshot["delivery"]["metricsAfterObservedAt"],
                                  f"negative {case_name} metricsAfterObservedAt")
        request_started = parse_utc(snapshot["request"]["startedAt"],
                                    f"negative {case_name} request startedAt")
        request_completed = parse_utc(snapshot["request"]["completedAt"],
                                      f"negative {case_name} request completedAt")
        observed_at = parse_utc(snapshot["observedAt"], f"negative {case_name} observedAt")
        window_ordered = (
            request_started <= request_completed <= metrics_before <= metrics_after <= observed_at
            if case_name == "disconnectedViewer"
            else metrics_before <= request_started <= request_completed <= metrics_after <= observed_at
        )
        if not window_ordered:
            raise EvidenceError(f"negative {case_name} request/metric window ordering is invalid")
        viewer_rejection_expected = case_name not in {
            "wrongDevice", "expired", "replayed", "disconnectedViewer",
        }
        if viewer_rejection_expected:
            if rejected_after <= rejected_before:
                raise EvidenceError(f"negative {case_name} viewer rejection metric did not increase")
        else:
            require_equal(rejected_after, rejected_before,
                          f"negative {case_name} unexpected viewer rejection metric delta")
        if set(snapshot["agentDeny"]) != {"required", "observed", "code"}:
            raise EvidenceError(f"negative {case_name} agent deny field set mismatch")
        agent_deny_required = case_name in {"expired", "replayed"}
        require_equal(snapshot["agentDeny"]["required"], agent_deny_required,
                      f"negative {case_name} agent deny requirement")
        require_equal(snapshot["agentDeny"]["observed"], agent_deny_required,
                      f"negative {case_name} agent deny observation")
        expected_code = {
            "expired": "operation-dispatch-failed:permit-invalid",
            "replayed": "operation-dispatch-failed:seq-replay",
        }.get(case_name)
        require_equal(snapshot["agentDeny"]["code"], expected_code,
                      f"negative {case_name} agent deny code")
        if not agent_deny_required and snapshot["agentDeny"]["code"] is not None:
            raise EvidenceError(f"negative {case_name} must not claim an agent deny code")
    else:
        for field in ("trigger", "triggeredAtEpochMillis", "deliveryEndedAtEpochMillis"):
            require_equal(snapshot[field], attestation[field],
                          f"termination {case_name} runtime {field}")
        if set(snapshot["counters"]) != {
            "viewerEndedBefore", "viewerEndedAfter", "globalFramesSentAtEnd",
            "globalFramesSentAfterObservationWindow", "sessionFramesDeliveredAtEnd",
            "observationWindowMillis",
        }:
            raise EvidenceError(f"termination {case_name} runtime counter field set mismatch")
        counters = snapshot["counters"]
        if not all(isinstance(value, int) and value >= 0 for value in counters.values()):
            raise EvidenceError(f"termination {case_name} runtime counters are invalid")
        require_equal(counters["viewerEndedAfter"], counters["viewerEndedBefore"] + 1,
                      f"termination {case_name} viewer ended delta")
        require_equal(counters["globalFramesSentAfterObservationWindow"],
                      counters["globalFramesSentAtEnd"],
                      f"termination {case_name} no post-end frames")
        require_equal(counters["observationWindowMillis"], 3_000,
                      f"termination {case_name} post-end observation window")
        if counters["sessionFramesDeliveredAtEnd"] < 1:
            raise EvidenceError(f"termination {case_name} session delivered no frames")
        required_signals = expected_termination_product_signals(case_name)
        require_equal(snapshot["terminal"], required_signals,
                      f"termination {case_name} terminal runtime signals")
        require_equal(attestation["productSignals"], required_signals,
                      f"termination {case_name} attested product signals")

    if evidence_type == "negative":
        return
    if audit is None or audit_raw is None:
        raise EvidenceError(f"termination {case_name} VIEW_STOP audit record is missing")
    require_equal(digest_bytes(audit_raw), attestation["viewStopAuditSha256"],
                  f"termination {case_name} audit record digest")
    if set(audit) != {
        "schemaVersion", "caseName", "sourceRevision", "observedAt", "binding",
        "eventType", "outcome", "chainVerified", "chainSha256", "chainCheckedCount",
        "framesDelivered", "verificationSource",
    }:
        raise EvidenceError(f"termination {case_name} audit record field set mismatch")
    require_equal(audit["schemaVersion"], "faz22.6.viewOnlyViewerMatrixAuditRecord.v1",
                  f"termination {case_name} audit record schema")
    for field in ("caseName", "sourceRevision", "observedAt", "binding"):
        require_equal(audit[field], attestation[field],
                      f"termination {case_name} audit record {field}")
    require_equal(audit["eventType"], "VIEW_STOP",
                  f"termination {case_name} audit event type")
    require_equal(audit["outcome"], attestation["result"]["deliveryTerminated"],
                  f"termination {case_name} audit outcome")
    require_equal(audit["chainVerified"], True,
                  f"termination {case_name} audit chain verification")
    require_equal(audit["verificationSource"], "tenant-audit-chain-builder",
                  f"termination {case_name} audit verification source")
    if not isinstance(audit["chainCheckedCount"], int) or audit["chainCheckedCount"] < 1:
        raise EvidenceError(f"termination {case_name} audit chain count is invalid")
    require_equal(audit["framesDelivered"], counters["sessionFramesDeliveredAtEnd"],
                  f"termination {case_name} session frame count")
    if not SHA256.fullmatch(str(audit["chainSha256"])):
        raise EvidenceError(f"termination {case_name} audit chain digest is invalid")
    require_equal(attestation["productSignals"]["viewStopAuditVerified"], audit["chainVerified"],
                  f"termination {case_name} VIEW_STOP audit verification")


def validate_matrix_source_attestations(
    evidence_type: str, files: dict[str, bytes], raw_child: bytes,
) -> None:
    if evidence_type not in {"negative", "termination"}:
        return
    child = load_json_bytes(raw_child, f"evidence/{evidence_type}.json")
    payload = child["payload"]
    case_names = NEGATIVE_CASES if evidence_type == "negative" else TERMINATION_CASES
    observations = load_canonical_matrix_jsonl(
        require_archive_file(files, f"observations/{evidence_type}.jsonl"),
        f"observations/{evidence_type}.jsonl", case_names,
    )
    audits = (
        load_canonical_matrix_jsonl(
            require_archive_file(files, "audit/termination.jsonl"),
            "audit/termination.jsonl", case_names,
        )
        if evidence_type == "termination" else {}
    )
    expected_trigger = {
        "localAbort": "local-abort", "killOrRevoke": "kill-or-revoke",
        "ttlExpiry": "ttl-expiry", "heartbeatLoss": "heartbeat-loss",
        "indicatorLoss": "indicator-loss",
    }

    for case_name in case_names:
        path = f"attestations/{evidence_type}/{case_name}.json"
        raw = require_archive_file(files, path)
        require_equal(digest_bytes(raw), payload["cases"][case_name]["evidenceSha256"],
                      f"{evidence_type} {case_name} attestation digest")
        attestation = load_json_bytes(raw, path)
        common_keys = {
            "schemaVersion", "caseName", "sourceRevision", "observedAt", "binding",
            "authorizationSha256", "runtimeSnapshotSha256",
        }
        expected_keys = common_keys | ({"request", "result"}
                                       if evidence_type == "negative" else {
                                           "trigger", "triggeredAtEpochMillis", "deliveryEndedAtEpochMillis",
                                           "result", "viewStopAuditSha256", "productSignals",
                                       })
        if set(attestation) != expected_keys:
            raise EvidenceError(f"{evidence_type} {case_name} attestation field set mismatch")
        expected_schema = (
            "faz22.6.viewOnlyViewerNegativeCaseAttestation.v1"
            if evidence_type == "negative"
            else "faz22.6.viewOnlyViewerTerminationCaseAttestation.v1"
        )
        require_equal(attestation["schemaVersion"], expected_schema,
                      f"{evidence_type} {case_name} attestation schema")
        require_equal(attestation["caseName"], case_name, f"{evidence_type} case name")
        require_equal(attestation["sourceRevision"], child["sourceRevision"],
                      f"{evidence_type} {case_name} source revision")
        require_equal(attestation["observedAt"], payload["cases"][case_name]["observedAt"],
                      f"{evidence_type} {case_name} observedAt")
        require_equal(attestation["binding"], payload["cases"][case_name]["binding"],
                      f"{evidence_type} {case_name} binding")
        require_equal(attestation["authorizationSha256"], payload["authorizationSha256"],
                      f"{evidence_type} {case_name} authorization")
        parse_utc(attestation["observedAt"], f"{evidence_type} {case_name} observedAt")
        for digest_field in ("runtimeSnapshotSha256",):
            if not isinstance(attestation[digest_field], str) or not SHA256.fullmatch(attestation[digest_field]):
                raise EvidenceError(f"{evidence_type} {case_name} {digest_field} is invalid")

        snapshot, snapshot_raw = observations[case_name]
        audit, audit_raw = audits.get(case_name, (None, None))
        validate_matrix_supporting_evidence(
            evidence_type, case_name, attestation, snapshot, snapshot_raw, audit, audit_raw,
        )

        case = payload["cases"][case_name]
        if evidence_type == "negative":
            contract = NEGATIVE_CASE_CONTRACT[case_name]
            if set(attestation["request"]) != {
                "method", "targetClass", "credentialClass", "subjectSha256",
                "tenantSha256", "rolePresent", "pathTemplate", "bodySha256",
                "startedAt", "completedAt",
            }:
                raise EvidenceError(f"negative {case_name} request field set mismatch")
            require_equal(attestation["request"]["method"], contract.method,
                          f"negative {case_name} method")
            require_equal(attestation["request"]["targetClass"], contract.target_class,
                          f"negative {case_name} target class")
            require_equal(attestation["request"]["credentialClass"], contract.credential_class,
                          f"negative {case_name} credential class")
            require_equal(attestation["request"]["pathTemplate"], contract.path_template,
                          f"negative {case_name} request path template")
            request = attestation["request"]
            body_digest = request["bodySha256"]
            if contract.method == "GET":
                require_equal(body_digest, None, f"negative {case_name} GET body digest")
            elif not isinstance(body_digest, str) or not SHA256.fullmatch(body_digest):
                raise EvidenceError(f"negative {case_name} request body digest is invalid")
            if case_name == "wrongDevice" and body_digest == digest_bytes(b""):
                raise EvidenceError("negative wrongDevice request body must be non-empty")
            subject_digest = request["subjectSha256"]
            tenant_digest = request["tenantSha256"]
            if case_name == "noAuth":
                require_equal(subject_digest, None, "negative noAuth subject identity")
                require_equal(tenant_digest, None, "negative noAuth tenant identity")
                require_equal(request["rolePresent"], False, "negative noAuth role presence")
            else:
                if not isinstance(subject_digest, str) or not SHA256.fullmatch(subject_digest):
                    raise EvidenceError(f"negative {case_name} request subject digest is invalid")
                if not isinstance(tenant_digest, str) or not SHA256.fullmatch(tenant_digest):
                    raise EvidenceError(f"negative {case_name} request tenant digest is invalid")
                if case_name in {"wrongRole", "wrongTenant"}:
                    if subject_digest == child["binding"]["operatorSha256"]:
                        raise EvidenceError(f"negative {case_name} must use a distinct request subject")
                else:
                    require_equal(subject_digest, child["binding"]["operatorSha256"],
                                  f"negative {case_name} request subject binding")
                if case_name == "wrongTenant":
                    if tenant_digest == child["binding"]["tenantSha256"]:
                        raise EvidenceError("negative wrongTenant must use a distinct request tenant")
                else:
                    require_equal(tenant_digest, child["binding"]["tenantSha256"],
                                  f"negative {case_name} request tenant binding")
                require_equal(request["rolePresent"], case_name != "wrongRole",
                              f"negative {case_name} request role presence")
            if set(attestation["result"]) != {
                "outcome", "requestAccepted", "deliveryContinued", "httpStatus",
            }:
                raise EvidenceError(f"negative {case_name} result field set mismatch")
            require_equal(attestation["result"]["outcome"], contract.outcome,
                          f"negative {case_name} contract outcome")
            require_equal(attestation["result"]["outcome"], case["outcome"],
                          f"negative {case_name} attested outcome")
            require_equal(attestation["result"]["requestAccepted"], False,
                          f"negative {case_name} request acceptance")
            require_equal(attestation["result"]["deliveryContinued"], False,
                          f"negative {case_name} delivery continuation")
            require_equal(attestation["result"]["httpStatus"], contract.http_status,
                          f"negative {case_name} HTTP status")
            require_equal(case["httpStatus"], contract.http_status,
                          f"negative {case_name} child HTTP status")
        else:
            require_equal(attestation["trigger"], expected_trigger[case_name],
                          f"termination {case_name} attested trigger")
            require_equal(attestation["trigger"], case["trigger"],
                          f"termination {case_name} child trigger")
            started = attestation["triggeredAtEpochMillis"]
            ended = attestation["deliveryEndedAtEpochMillis"]
            if not all(isinstance(value, int) and value > 0 for value in (started, ended)) or ended < started:
                raise EvidenceError(f"termination {case_name} epoch timestamps are invalid")
            require_equal(ended - started, case["terminationLatencyMillis"],
                          f"termination {case_name} measured latency")
            if set(attestation["result"]) != {"deliveryTerminated"}:
                raise EvidenceError(f"termination {case_name} result field set mismatch")
            require_equal(attestation["result"]["deliveryTerminated"], True,
                          f"termination {case_name} delivery result")
            required_signals = expected_termination_product_signals(case_name)
            require_equal(attestation["productSignals"], required_signals,
                          f"termination {case_name} product signals")
            require_equal(attestation["viewStopAuditSha256"], case["viewStopAuditSha256"],
                          f"termination {case_name} VIEW_STOP audit digest")


def fetch_verified_source_child(
    client: ApiClient, evidence_type: str, entry: dict[str, Any], expected_head_sha: str,
) -> tuple[bytes, dict[str, Any]]:
    source = entry["source"]
    expected_path, expected_name = EXPECTED_SOURCE_WORKFLOWS[evidence_type]
    expected_artifact_name = f"faz22-6-view-only-viewer-{evidence_type}-evidence-{source['runId']}"
    expected_file = f"evidence/{evidence_type}.json"
    require_equal(source["repository"], EXPECTED_REPOSITORY, f"{evidence_type} source repository")
    require_equal(source["workflowPath"], expected_path, f"{evidence_type} source workflow path")
    require_equal(source["artifactName"], expected_artifact_name, f"{evidence_type} source artifact name")
    require_equal(source["artifactFile"], expected_file, f"{evidence_type} source artifact file")
    run = fetch_run(
        client, EXPECTED_REPOSITORY, source["runId"], expected_name, expected_path,
        f"{evidence_type} source",
    )
    require_equal(source["runAttempt"], run["run_attempt"], f"{evidence_type} source run attempt")
    require_equal(source["headSha"], run["head_sha"], f"{evidence_type} source head SHA")
    require_equal(source["headSha"], expected_head_sha, f"{evidence_type} source producer revision")

    listing = client.get_json(
        f"/repos/{EXPECTED_REPOSITORY}/actions/runs/{source['runId']}/artifacts?per_page=100"
    )
    artifacts = listing.get("artifacts")
    if not isinstance(artifacts, list):
        raise EvidenceError(f"{evidence_type} source artifact listing is invalid")
    matches = [
        artifact for artifact in artifacts if isinstance(artifact, dict)
        and artifact.get("id") == source["artifactId"]
        and artifact.get("name") == expected_artifact_name
    ]
    if len(matches) != 1:
        raise EvidenceError(f"{evidence_type} source artifact identity is not unique")
    artifact = matches[0]
    require_equal(artifact.get("digest"), source["artifactDigest"], f"{evidence_type} source artifact digest")
    if artifact.get("expired") is not False:
        raise EvidenceError(f"{evidence_type} source artifact is expired")
    workflow_run = artifact.get("workflow_run")
    if not isinstance(workflow_run, dict) or workflow_run.get("id") != source["runId"]:
        raise EvidenceError(f"{evidence_type} source artifact run binding is invalid")
    for field in ("created_at", "updated_at"):
        parse_utc(artifact.get(field), f"{evidence_type} source artifact {field}")
    raw_archive = client.get_bytes(
        f"/repos/{EXPECTED_REPOSITORY}/actions/artifacts/{source['artifactId']}/zip"
    )
    actual_archive_digest = digest_bytes(raw_archive)
    require_equal(
        actual_archive_digest, source["artifactDigest"], f"{evidence_type} downloaded source artifact digest"
    )
    files = safe_archive_files(raw_archive)
    expected_files = source_artifact_files(evidence_type)
    if set(files) != expected_files:
        raise EvidenceError(f"{evidence_type} source artifact file set mismatch")
    raw_child = files[expected_file]
    require_equal(digest_bytes(raw_child), entry["sha256"], f"{evidence_type} source child digest")
    if evidence_type == "browser":
        child = load_json_bytes(raw_child, expected_file)
        consent_raw = files["evidence/consent.json"]
        require_equal(
            digest_bytes(consent_raw), child["payload"]["consentEvidenceSha256"],
            "browser consent evidence digest",
        )
        consent = load_json_bytes(consent_raw, "evidence/consent.json")
        consent_source_raw = files["evidence/consent-source.json"]
        consent_source = load_json_bytes(consent_source_raw, "evidence/consent-source.json")
        expected_consent_keys = {
            "schemaVersion", "sourceRevision", "observedAt", "binding",
            "consentPromptSent", "decision", "decisionSignal", "decisionProtocol",
            "decisionSource", "pilotAutoConsent", "recordingMode",
            "screenContentPersisted", "sourceAttestationSha256",
        }
        if set(consent) != expected_consent_keys:
            raise EvidenceError("browser consent evidence field set mismatch")
        require_equal(consent["schemaVersion"], "faz22.6.viewOnlyViewerConsentEvidence.v1", "consent schema")
        require_equal(consent["sourceRevision"], child["sourceRevision"], "consent source revision")
        require_equal(consent["observedAt"], child["observedAt"], "consent observedAt")
        require_equal(consent["binding"], child["binding"], "consent same-session binding")
        require_equal(
            consent["sourceAttestationSha256"], digest_bytes(consent_source_raw),
            "consent source attestation digest",
        )
        expected_source_keys = {
            "schemaVersion", "sourceRevision", "observedAt", "binding",
            "smokeSummarySha256", "openSessionResponseSha256",
            "endpointConsentLogLineSha256", "openSessionConsentPromptSent",
            "brokerHelloVerified", "brokerConsentGranted",
            "endpointConsentGranted", "transportPushed",
        }
        if set(consent_source) != expected_source_keys:
            raise EvidenceError("browser consent source attestation field set mismatch")
        require_equal(
            consent_source["schemaVersion"],
            "faz22.6.viewOnlyViewerConsentSourceAttestation.v1",
            "consent source schema",
        )
        require_equal(consent_source["sourceRevision"], child["sourceRevision"], "consent source revision")
        require_equal(consent_source["observedAt"], child["observedAt"], "consent source observedAt")
        require_equal(consent_source["binding"], child["binding"], "consent source same-session binding")
        for field in (
            "smokeSummarySha256", "openSessionResponseSha256",
            "endpointConsentLogLineSha256",
        ):
            if not isinstance(consent_source[field], str) or not SHA256.fullmatch(consent_source[field]):
                raise EvidenceError(f"consent source {field} digest is invalid")
        for field in (
            "openSessionConsentPromptSent", "brokerHelloVerified",
            "brokerConsentGranted", "endpointConsentGranted", "transportPushed",
        ):
            require_equal(consent_source[field], True, f"consent source {field}")
        expected_consent = {
            "consentPromptSent": True,
            "decision": "granted",
            "decisionSignal": "CONSENT_GRANTED",
            "decisionProtocol": "remote-bridge-consent-signal-v1",
            "decisionSource": "device-key-attested-endpoint-outbound-channel",
            "pilotAutoConsent": False,
            "recordingMode": "disabled",
            "screenContentPersisted": False,
        }
        for field, expected_value in expected_consent.items():
            require_equal(consent[field], expected_value, f"consent {field}")
    validate_matrix_source_attestations(evidence_type, files, raw_child)
    return raw_child, run


def percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise EvidenceError(f"{label} mismatch")


def validate_source_attestation_timing(
    observed: datetime, source_updated: datetime, producer_started: datetime, label: str,
) -> None:
    if observed > source_updated + RUN_CLOCK_SKEW:
        raise EvidenceError(f"{label} source run completed before its observation")
    if source_updated - observed > MAX_EVIDENCE_AGE:
        raise EvidenceError(f"{label} source attestation is stale")
    if source_updated > producer_started:
        raise EvidenceError(f"{label} source run did not complete before the producer")


def validate_d30(payload: dict[str, Any]) -> None:
    images = payload["images"]
    components = [image["component"] for image in images]
    if sorted(components) != ["backend", "web"]:
        raise EvidenceError("D30 evidence must contain exactly one backend and one web image")
    if any(image["desiredDigest"] != image["liveImageIdDigest"] for image in images):
        raise EvidenceError("D30 desired digest does not equal live imageID digest")


def verify_sha256sums(files: dict[str, bytes], expected_names: set[str]) -> None:
    try:
        text = files["SHA256SUMS"].decode("ascii")
    except (KeyError, UnicodeDecodeError) as exc:
        raise EvidenceError("activation SHA256SUMS is missing or invalid") from exc
    entries: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9._-]+)", line)
        if not match or match.group(2) in entries:
            raise EvidenceError("activation SHA256SUMS contains an invalid entry")
        entries[match.group(2)] = match.group(1)
    if set(entries) != expected_names:
        raise EvidenceError("activation SHA256SUMS file set mismatch")
    for name, expected in entries.items():
        if hashlib.sha256(files[name]).hexdigest() != expected:
            raise EvidenceError(f"activation receipt digest mismatch: {name}")


def load_bound_owner_policy(
    expected_digest: str, *, allow_legacy_v1: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Select exactly one content-addressed v2 or immutable legacy-v1 policy."""

    digest_hex = expected_digest.removeprefix("sha256:")
    if not re.fullmatch(r"[a-f0-9]{64}", digest_hex):
        raise EvidenceError("authorization owner policy digest is invalid")
    archived_v2 = OWNER_POLICY_HISTORY / f"{digest_hex}.json"
    candidates = [(OWNER_POLICY_V2, False), (OWNER_POLICY_V1, True)]
    if archived_v2.is_file():
        candidates.append((archived_v2, False))
    matches: list[tuple[dict[str, Any], bool]] = []
    matched_digests: set[str] = set()
    for path, legacy_v1 in candidates:
        policy = load_json_bytes(path.read_bytes(), f"canonical owner policy {path.name}")
        policy_digest = digest_json(policy)
        if policy_digest == expected_digest and policy_digest not in matched_digests:
            matches.append((policy, legacy_v1))
            matched_digests.add(policy_digest)
    if len(matches) != 1:
        raise EvidenceError("authorization owner policy digest is not a unique canonical contract")
    policy, legacy_v1 = matches[0]
    if legacy_v1 and not allow_legacy_v1:
        raise EvidenceError("legacy v1 policy is forbidden for current product activation")
    if legacy_v1 and digest_json(policy) != LEGACY_POLICY_CANONICAL_SHA256:
        raise EvidenceError("legacy v1 owner policy is not the immutable forensic contract")
    return policy, legacy_v1


def verify_activation_authorization(
    client: ApiClient, operator: dict[str, Any], expected_head_sha: str,
    binding: dict[str, str], pilot_started: datetime, pilot_ended: datetime,
    *, allow_legacy_v1: bool = False,
    advisory_scope_bytes: bytes | None = None,
    cross_ai_trust_root: dict[str, Any] | None = None,
    cross_ai_revocations: dict[str, Any] | None = None,
    expected_cross_ai_trust_root_sha256: str | None = None,
    codex_executable_policy: dict[str, Any] | None = None,
    issuer_runtime_policy: dict[str, Any] | None = None,
    authority_observed_at: datetime | None = None,
    authority_repo_root: Path | None = None,
) -> datetime:
    run_id = operator["activationRunId"]
    if operator["activationRunAttempt"] < 1:
        raise EvidenceError("activation run attempt is invalid")
    require_equal(
        operator["activationHeadSha"], expected_head_sha,
        "activation producer revision",
    )
    activation_updated = parse_utc(
        operator["activationUpdatedAt"], "activation updated_at"
    )
    if activation_updated > pilot_started + RUN_CLOCK_SKEW:
        raise EvidenceError("protected activation completed after the pilot started")
    if pilot_started - activation_updated > MAX_ACTIVATION_TO_PILOT_DELAY:
        raise EvidenceError("protected activation is too old for the pilot window")

    try:
        raw_authorization = base64.b64decode(
            operator["authorizationCarrierBase64"], validate=True
        )
        raw_advisory_comment = base64.b64decode(
            operator["advisoryCommentCarrierBase64"], validate=True
        )
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise EvidenceError("protected authorization carrier is invalid") from exc
    require_equal(
        digest_bytes(raw_authorization), operator["authorizationSha256"],
        "protected authorization receipt digest",
    )
    authorization = load_json_bytes(raw_authorization, "protected-authorization.json")
    archived_advisory_comment = load_json_bytes(
        raw_advisory_comment, "advisory-comment.json"
    )
    policy, legacy_v1 = load_bound_owner_policy(
        authorization.get("ownerPolicySha256"), allow_legacy_v1=allow_legacy_v1,
    )
    expected_keys = {
        "schemaVersion", "minimumAcceptedAuthorizationSchema", "environment",
        "onePersonRoster", "operatorSha256", "consentingPilotDevice", "deviceSha256",
        "exposureApprovedByProtectedEnvironment", "protectedEnvironmentPreventSelfReview",
        "protectedEnvironmentReviewerCount", "protectedEnvironmentReviewerSetSha256",
        "ownerPolicySha256", "ownerDirectiveRef",
        "ownerDirectiveSha256", "aiAdvisoryOnly", "aiAdvisoryRef", "aiAdvisorySha256",
        "aiAdvisoryProvenanceClass", "aiProviderCryptographicAttestation",
        "aiConsensusVerdict", "legalTrackingIssueRef", "legalTrackStatus",
        "legalClearanceClaimed", "legalDependencyAcknowledgedBy",
        "legalDependencyRationaleCode", "recordingMode", "screenContentPersisted",
        "attendedConsentRequired", "pilotAutoConsent", "visibleIndicatorRequired",
        "localAbortRequired", "killSwitchWorkflowRef", "revocationLedgerRef",
        "issuedAt", "expiresAt", "authorizationRunId",
        "authorizationHeadSha",
    }
    if not legacy_v1:
        expected_keys |= {
            "aiAdvisoryCommentId", "aiAdvisoryBaseTipSha",
            "aiAdvisoryBaseSha", "aiAdvisoryHeadSha",
            "aiAdvisoryScopeSha256",
        }
    if set(authorization) != expected_keys:
        raise EvidenceError("protected authorization receipt field set mismatch")
    require_equal(
        authorization["schemaVersion"], AUTHORIZATION_SCHEMA,
        "protected authorization schema",
    )
    require_equal(
        authorization["minimumAcceptedAuthorizationSchema"], AUTHORIZATION_SCHEMA,
        "minimum accepted authorization schema",
    )
    require_equal(authorization["environment"], "faz22-view-only-pilot", "protected environment")
    expected_advisory_provenance = (
        "owner-attested-provider-session"
        if legacy_v1 else "signed-direct-codex-launch-attested-v3"
    )
    if not (
        authorization["onePersonRoster"] is True
        and authorization["consentingPilotDevice"] is True
        and authorization["exposureApprovedByProtectedEnvironment"] is True
        and authorization["protectedEnvironmentPreventSelfReview"] is True
        and isinstance(authorization["protectedEnvironmentReviewerCount"], int)
        and authorization["protectedEnvironmentReviewerCount"] >= 1
        and authorization["aiAdvisoryOnly"] is True
        and authorization["aiAdvisoryProvenanceClass"] == expected_advisory_provenance
        and authorization["aiProviderCryptographicAttestation"] is (not legacy_v1)
        and authorization["legalTrackStatus"] == "tracked_pending"
        and authorization["legalClearanceClaimed"] is False
        and authorization["legalDependencyAcknowledgedBy"] == "owner"
        and authorization["legalDependencyRationaleCode"] == "bounded-test-owner-risk-acceptance"
        and authorization["recordingMode"] == "disabled"
        and authorization["screenContentPersisted"] is False
        and authorization["attendedConsentRequired"] is True
        and authorization["pilotAutoConsent"] is False
        and authorization["visibleIndicatorRequired"] is True
        and authorization["localAbortRequired"] is True
    ):
        raise EvidenceError("protected authorization boolean controls are not all true")
    require_equal(authorization["authorizationRunId"], run_id, "authorization receipt run id")
    require_equal(authorization["authorizationHeadSha"], expected_head_sha, "authorization head SHA")
    require_equal(authorization["operatorSha256"], binding["operatorSha256"], "authorized operator binding")
    require_equal(authorization["deviceSha256"], binding["deviceSha256"], "authorized device binding")
    for field in (
        "ownerPolicySha256", "ownerDirectiveSha256", "aiAdvisorySha256",
        "legalTrackStatus", "legalClearanceClaimed",
    ):
        require_equal(authorization[field], operator[field], f"authorization operator {field}")

    revocations = load_json_bytes(REVOCATION_LEDGER.read_bytes(), "authorization revocation ledger")
    if set(policy) != {
        "schemaVersion", "status", "ownerDirective", "aiAdvisory", "legalTracking",
        "scope", "authorization", "lifecycle",
    }:
        raise EvidenceError("canonical owner policy field set mismatch")
    require_equal(
        policy["schemaVersion"],
        OWNER_POLICY_SCHEMA_V1 if legacy_v1 else OWNER_POLICY_SCHEMA_V2,
        "canonical owner policy schema",
    )
    require_equal(
        policy["status"], "active" if legacy_v1 else "tracked_pending",
        "canonical owner policy status",
    )
    policy_digest = digest_json(policy)
    require_equal(authorization["ownerPolicySha256"], policy_digest, "canonical owner policy digest")
    if revocations.get("schemaVersion") != "faz22.6-view-only-pilot-authorization-revocations-v1":
        raise EvidenceError("authorization revocation ledger schema mismatch")
    revoked = revocations.get("revokedAuthorizationSha256")
    if not isinstance(revoked, list) or any(not isinstance(value, str) or not SHA256.fullmatch(value) for value in revoked):
        raise EvidenceError("authorization revocation ledger entries are invalid")
    if operator["authorizationSha256"] in set(revoked):
        raise EvidenceError("protected authorization has been revoked")

    owner_contract = policy.get("ownerDirective")
    advisory_contract = policy.get("aiAdvisory")
    if not isinstance(owner_contract, dict) or not isinstance(advisory_contract, dict):
        raise EvidenceError("canonical owner/advisory policy entries are missing")
    require_equal(authorization["ownerDirectiveRef"], owner_contract.get("ref"), "owner directive ref")
    require_equal(authorization["ownerDirectiveSha256"], owner_contract.get("bodySha256"), "owner directive digest")
    require_equal(
        authorization["aiAdvisoryProvenanceClass"], advisory_contract.get("provenanceClass"),
        "AI advisory provenance class",
    )
    require_equal(
        authorization["aiProviderCryptographicAttestation"],
        advisory_contract.get("providerCryptographicAttestation"),
        "AI provider cryptographic-attestation boundary",
    )
    require_equal(authorization["aiConsensusVerdict"], "AGREE", "AI advisory consensus")
    require_equal(advisory_contract.get("advisoryOnly"), True, "AI advisory-only policy")
    require_equal(
        advisory_contract.get("consensusVerdict"),
        "AGREE" if legacy_v1 else "PENDING",
        "AI advisory policy consensus",
    )
    require_equal(
        advisory_contract.get("providers"),
        (
            ["Anthropic/claude-opus-4-8", "OpenAI/gpt-5.6-sol"]
            if legacy_v1 else ["OpenAI/gpt-5.6-sol"]
        ),
        "AI advisory provider contract",
    )

    legal_contract = policy.get("legalTracking")
    if not isinstance(legal_contract, dict):
        raise EvidenceError("canonical legal tracking policy entry is missing")
    require_equal(legal_contract.get("ref"), authorization["legalTrackingIssueRef"], "legal tracking ref")
    require_equal(legal_contract.get("status"), "tracked_pending", "legal tracking policy status")
    require_equal(legal_contract.get("clearanceClaimed"), False, "legal tracking clearance claim")
    require_equal(
        authorization["killSwitchWorkflowRef"],
        ".github/workflows/apply-view-only-viewer-pilot-enable.yml?action=rollback",
        "kill-switch workflow ref",
    )
    require_equal(
        authorization["revocationLedgerRef"],
        "config/faz22-6-view-only-pilot-authorization-revocations.v1.json",
        "revocation ledger ref",
    )

    if not legacy_v1:
        expected_advisory_fields = {
            "commentId", "ref", "bodySha256", "authorLogin", "authorAssociation",
            "advisoryOnly", "consensusVerdict", "providers", "provenanceClass",
            "providerCryptographicAttestation", "evidenceBinding", "maxAgeHours",
        }
        if set(advisory_contract) != expected_advisory_fields:
            raise EvidenceError("Codex advisory policy field set mismatch")
        policy_binding = advisory_contract.get("evidenceBinding")
        if not isinstance(policy_binding, dict) or set(policy_binding) != {
            "baseTipSha", "baseSha", "headSha", "scopeSha256",
        }:
            raise EvidenceError("Codex advisory policy binding template field set mismatch")
        if (
            any(
                advisory_contract.get(field) is not None
                for field in (
                    "commentId", "ref", "bodySha256", "authorLogin",
                    "authorAssociation",
                )
            )
            or any(value is not None for value in policy_binding.values())
        ):
            raise EvidenceError("Codex advisory policy is not a stable pending template")
        expected_bindings = {
            "base_tip_sha": authorization["aiAdvisoryBaseTipSha"],
            "base_sha": authorization["aiAdvisoryBaseSha"],
            "head_sha": authorization["aiAdvisoryHeadSha"],
            "scope_sha256": authorization["aiAdvisoryScopeSha256"],
        }
        require_equal(
            authorization["aiAdvisoryHeadSha"], expected_head_sha,
            "activation/advisory head binding",
        )
        if advisory_scope_bytes is None:
            advisory_scope_bytes, _, _ = derive_scope(
                ROOT,
                base_tip_sha=expected_bindings["base_tip_sha"],
                base_sha=expected_bindings["base_sha"],
                head_sha=expected_bindings["head_sha"],
                max_scope_bytes=MAX_SCOPE_BYTES,
                scan_secrets=True,
            )
        if hashlib.sha256(advisory_scope_bytes).hexdigest() != expected_bindings[
            "scope_sha256"
        ]:
            raise EvidenceError("canonical advisory scope digest mismatch")
        explicit_authority_unavailable = any(value is None for value in (
            cross_ai_trust_root,
            cross_ai_revocations,
            expected_cross_ai_trust_root_sha256,
            codex_executable_policy,
            issuer_runtime_policy,
        ))
        if (
            advisory_scope_bytes is None
            or authority_observed_at is None
            or (authority_repo_root is None and explicit_authority_unavailable)
        ):
            raise EvidenceError("signed Codex advisory authority inputs are unavailable")
        runtime_advisory_contract = {
            "commentId": authorization["aiAdvisoryCommentId"],
            "ref": authorization["aiAdvisoryRef"],
            "bodySha256": authorization["aiAdvisorySha256"],
            "authorLogin": owner_contract.get("authorLogin"),
            "authorAssociation": "OWNER",
        }
        for label, contract in (
            ("owner directive", owner_contract),
            ("AI advisory", runtime_advisory_contract),
        ):
            comment_id = contract.get("commentId")
            if not isinstance(comment_id, int) or comment_id < 1:
                raise EvidenceError(f"{label} comment ID is invalid")
            comment = (
                archived_advisory_comment
                if label == "AI advisory"
                else client.get_json(
                    f"/repos/{EXPECTED_REPOSITORY}/issues/comments/{comment_id}",
                )
            )
            require_equal(comment.get("html_url"), contract.get("ref"), f"{label} URL")
            require_equal(
                comment.get("issue_url"),
                f"https://api.github.com/repos/{EXPECTED_REPOSITORY}/issues/2373",
                f"{label} issue binding",
            )
            require_equal(
                comment.get("author_association"), contract.get("authorAssociation"),
                f"{label} author association",
            )
            user = comment.get("user")
            require_equal(
                user.get("login") if isinstance(user, dict) else None,
                contract.get("authorLogin"), f"{label} author",
            )
            body = comment.get("body")
            if not isinstance(body, str):
                raise EvidenceError(f"{label} body is missing")
            require_equal(
                digest_bytes(body.encode()), contract.get("bodySha256"),
                f"{label} body digest",
            )
            if label == "AI advisory":
                try:
                    advisory_authority_observed_at = authority_observed_at
                    validate_codex_advisory_comment_timing(
                        comment, pilot_started, advisory_contract.get("maxAgeHours"),
                    )
                    if authority_repo_root is not None:
                        carrier = json.loads(body)
                        carrier_root = (
                            carrier.get("trust_root_sha256")
                            if isinstance(carrier, dict) else None
                        )
                        if not isinstance(carrier_root, str):
                            raise CodexEvidenceError(
                                "signed Codex carrier trust-root binding is missing"
                            )
                        resolved_authority = load_authority_for_evidence(
                            authority_repo_root,
                            expected_trust_root_sha256=carrier_root,
                            observed_at=authority_observed_at,
                            evidence_reference_time=pilot_started,
                        )
                        cross_ai_trust_root = resolved_authority.trust_root
                        cross_ai_revocations = (
                            resolved_authority.revocations_envelope
                        )
                        expected_cross_ai_trust_root_sha256 = (
                            resolved_authority.expected_trust_root_sha256
                        )
                        codex_executable_policy = (
                            resolved_authority.codex_executable_policy
                        )
                        issuer_runtime_policy = (
                            resolved_authority.issuer_runtime_policy
                        )
                        advisory_authority_observed_at = (
                            resolved_authority.observed_at
                        )
                    validate_codex_advisory_evidence(
                        body,
                        expected_bindings,
                        scope_bytes=advisory_scope_bytes,
                        trust_root=cross_ai_trust_root,
                        revocations_envelope=cross_ai_revocations,
                        expected_trust_root_sha256=(
                            expected_cross_ai_trust_root_sha256
                        ),
                        codex_executable_policy=codex_executable_policy,
                        issuer_runtime_policy=issuer_runtime_policy,
                        authority_observed_at=advisory_authority_observed_at,
                        review_reference_time=pilot_started,
                    )
                except (
                    AuthorityUnavailable,
                    CodexEvidenceError,
                    json.JSONDecodeError,
                ) as exc:
                    raise EvidenceError(
                        f"AI advisory is not strict Codex-only evidence: {exc}",
                    ) from exc

    require_equal(
        authorization["legalTrackingIssueRef"],
        "https://github.com/Halildeu/platform-k8s-gitops/issues/2374",
        "legal tracking issue ref",
    )
    legal_issue = client.get_json(f"/repos/{EXPECTED_REPOSITORY}/issues/2374")
    require_equal(legal_issue.get("state"), "open", "legal tracking state")
    require_equal(legal_issue.get("html_url"), authorization["legalTrackingIssueRef"], "legal tracking URL")

    environment = client.get_json(f"/repos/{EXPECTED_REPOSITORY}/environments/faz22-view-only-pilot")
    actor_login = operator.get("activationActorLogin")
    if not isinstance(actor_login, str) or not actor_login:
        raise EvidenceError("activation workflow actor identity is absent")
    reviewer_count, reviewer_set_sha256 = canonical_environment_reviewer_set(environment, actor_login)
    require_equal(
        reviewer_count, authorization["protectedEnvironmentReviewerCount"],
        "protected environment reviewer count",
    )
    require_equal(
        reviewer_set_sha256, authorization["protectedEnvironmentReviewerSetSha256"],
        "protected environment reviewer set digest",
    )

    issued_at = parse_utc(authorization["issuedAt"], "protected authorization issuedAt")
    if legacy_v1 and issued_at >= LEGACY_V1_ISSUANCE_CUTOFF:
        raise EvidenceError(
            "legacy v1 authorization was issued at or after the migration cutoff",
        )
    run_created = parse_utc(operator["activationCreatedAt"], "activation created_at")
    run_started = parse_utc(
        operator["activationRunStartedAt"], "activation run_started_at"
    )
    if legacy_v1 and (
        run_created >= LEGACY_V1_ISSUANCE_CUTOFF
        or run_started >= LEGACY_V1_ISSUANCE_CUTOFF
    ):
        raise EvidenceError(
            "legacy v1 activation run started at or after the migration cutoff",
        )
    if issued_at < run_created - RUN_CLOCK_SKEW or issued_at > activation_updated + RUN_CLOCK_SKEW:
        raise EvidenceError("protected authorization issuance is outside the activation run window")
    expires_at = parse_utc(authorization["expiresAt"], "protected authorization expiresAt")
    if expires_at - issued_at > timedelta(minutes=120):
        raise EvidenceError("protected authorization exceeds the 120-minute absolute TTL")
    if expires_at < pilot_ended:
        raise EvidenceError("protected authorization expired before the pilot ended")
    return expires_at


def validate_negative_and_termination(
    negative: dict[str, Any], termination: dict[str, Any], operator: dict[str, Any],
    root_binding: dict[str, Any], pilot_started: datetime, authorization_expires_at: datetime,
    child_observed_at: dict[str, datetime],
) -> None:
    """Validate source-generated fail-closed matrices and isolated termination sessions."""
    expected_termination = {
        "localAbort": ("local-abort", 5_000),
        "killOrRevoke": ("kill-or-revoke", 1_000),
        "ttlExpiry": ("ttl-expiry", 5_000),
        "heartbeatLoss": ("heartbeat-loss", 120_000),
        "indicatorLoss": ("indicator-loss", 5_000),
    }
    authorization_digest = operator["authorizationSha256"]
    matrix_deadline = min(pilot_started + MAX_MATRIX_WINDOW, authorization_expires_at)

    for label, payload in (("negative", negative), ("termination", termination)):
        require_equal(payload["authorizationSha256"], authorization_digest,
                      f"{label} protected authorization digest")
        expected_suite = digest_json({
            "authorizationSha256": payload["authorizationSha256"],
            "cases": payload["cases"],
        })
        require_equal(payload["suiteSha256"], expected_suite, f"{label} suite digest")

    negative_evidence: set[str] = set()
    negative_observations: list[datetime] = []
    negative_session: str | None = None
    for case_name in NEGATIVE_CASES:
        contract = NEGATIVE_CASE_CONTRACT[case_name]
        case = negative["cases"][case_name]
        require_equal(case["outcome"], contract.outcome, f"negative {case_name} outcome")
        require_equal(case["httpStatus"], contract.http_status, f"negative {case_name} HTTP status")
        case_binding = case["binding"]
        for key in ("tenantSha256", "operatorSha256"):
            require_equal(case_binding[key], root_binding[key], f"negative {case_name} {key}")
        if case_name == "wrongDevice":
            if case_binding["deviceSha256"] == root_binding["deviceSha256"]:
                raise EvidenceError("negative wrongDevice must use a different device binding")
            if case_binding["sessionSha256"] in {root_binding["sessionSha256"], negative_session}:
                raise EvidenceError("negative wrongDevice must use a distinct attempted session binding")
        else:
            if negative_session is None:
                negative_session = case_binding["sessionSha256"]
                if negative_session == root_binding["sessionSha256"]:
                    raise EvidenceError("negative matrix must use an isolated protected session")
            require_equal(case_binding["sessionSha256"], negative_session,
                          f"negative {case_name} isolated session binding")
            require_equal(case_binding["deviceSha256"], root_binding["deviceSha256"],
                          f"negative {case_name} deviceSha256")
        if len(set(case_binding.values())) != len(case_binding):
            raise EvidenceError(f"negative {case_name} binding hashes must be distinct")
        observed = parse_utc(case["observedAt"], f"negative {case_name} observedAt")
        negative_observations.append(observed)
        if observed < pilot_started - RUN_CLOCK_SKEW or observed > matrix_deadline:
            raise EvidenceError(f"negative {case_name} is outside the authorized matrix window")
        if case["evidenceSha256"] in negative_evidence:
            raise EvidenceError("negative cases must use distinct content evidence digests")
        negative_evidence.add(case["evidenceSha256"])
    require_equal(max(negative_observations), child_observed_at["negative"],
                  "negative child latest observation")
    if negative_session is None:
        raise EvidenceError("negative matrix isolated session binding is absent")

    termination_sessions: set[str] = set()
    termination_evidence: set[str] = set()
    termination_audits: set[str] = set()
    termination_observations: list[datetime] = []
    for case_name, (expected_trigger, max_latency) in expected_termination.items():
        case = termination["cases"][case_name]
        require_equal(case["trigger"], expected_trigger, f"termination {case_name} trigger")
        if case["terminationLatencyMillis"] > max_latency:
            raise EvidenceError(f"termination {case_name} exceeded the {max_latency}ms fail-closed SLO")
        case_binding = case["binding"]
        for key in ("tenantSha256", "operatorSha256", "deviceSha256"):
            require_equal(case_binding[key], root_binding[key], f"termination {case_name} {key}")
        if len(set(case_binding.values())) != len(case_binding):
            raise EvidenceError(f"termination {case_name} binding hashes must be distinct")
        session_digest = case_binding["sessionSha256"]
        if session_digest in {root_binding["sessionSha256"], negative_session} \
                or session_digest in termination_sessions:
            raise EvidenceError("termination cases require distinct isolated sessions")
        termination_sessions.add(session_digest)
        observed = parse_utc(case["observedAt"], f"termination {case_name} observedAt")
        termination_observations.append(observed)
        if observed < pilot_started - RUN_CLOCK_SKEW or observed > matrix_deadline:
            raise EvidenceError(f"termination {case_name} is outside the authorized matrix window")
        if case["evidenceSha256"] in termination_evidence:
            raise EvidenceError("termination cases must use distinct delivery evidence digests")
        if case["viewStopAuditSha256"] in termination_audits:
            raise EvidenceError("termination cases must use distinct VIEW_STOP audit digests")
        if case["evidenceSha256"] == case["viewStopAuditSha256"]:
            raise EvidenceError(f"termination {case_name} delivery and audit evidence must be distinct")
        termination_evidence.add(case["evidenceSha256"])
        termination_audits.add(case["viewStopAuditSha256"])
    require_equal(max(termination_observations), child_observed_at["termination"],
                  "termination child latest observation")
    all_matrix_digests = negative_evidence | termination_evidence | termination_audits
    expected_digest_count = len(negative_evidence) + len(termination_evidence) + len(termination_audits)
    if len(all_matrix_digests) != expected_digest_count:
        raise EvidenceError("negative and termination evidence digests must be globally distinct")


def validate_semantics(
    client: ApiClient, root: dict[str, Any], children: dict[str, dict[str, Any]], run: dict[str, Any],
    source_runs: dict[str, dict[str, Any]], artifact: dict[str, Any], root_digest: str,
    archive_digest: str, now: datetime,
    *,
    advisory_scope_bytes: bytes | None,
    cross_ai_trust_root: dict[str, Any] | None,
    cross_ai_revocations: dict[str, Any] | None,
    expected_cross_ai_trust_root_sha256: str | None,
    codex_executable_policy: dict[str, Any] | None,
    issuer_runtime_policy: dict[str, Any] | None,
    authority_repo_root: Path | None,
) -> dict[str, Any]:
    if scan := scan_hygiene(root):
        raise EvidenceError("root evidence hygiene failed: " + "; ".join(scan[:20]))
    for evidence_type, child in children.items():
        if scan := scan_hygiene(child):
            raise EvidenceError(f"{evidence_type} evidence hygiene failed: " + "; ".join(scan[:20]))

    producer = root["producer"]
    require_equal(producer["repository"], EXPECTED_REPOSITORY, "root producer repository")
    require_equal(producer["workflowPath"], EXPECTED_WORKFLOW_PATH, "root producer workflow path")
    require_equal(producer["runId"], run["id"], "root producer run id")
    require_equal(producer["runAttempt"], run["run_attempt"], "root producer run attempt")
    require_equal(producer["headSha"], run["head_sha"], "root producer head SHA")

    run_started = parse_utc(run["run_started_at"], "run_started_at")
    run_updated = parse_utc(run["updated_at"], "run updated_at")
    pilot_started = parse_utc(root["pilot"]["startedAt"], "pilot.startedAt")
    pilot_ended = parse_utc(root["pilot"]["endedAt"], "pilot.endedAt")
    generated_at = parse_utc(root["generatedAt"], "generatedAt")
    pilot_seconds = (pilot_ended - pilot_started).total_seconds()
    if not MIN_PILOT_SECONDS <= pilot_seconds <= MAX_PILOT_SECONDS:
        raise EvidenceError(f"pilot duration must be between {MIN_PILOT_SECONDS} and {MAX_PILOT_SECONDS} seconds")
    source_started = min(
        parse_utc(source_run["run_started_at"], f"{evidence_type} source run_started_at")
        for evidence_type, source_run in source_runs.items()
    )
    source_updated = max(
        parse_utc(source_run["updated_at"], f"{evidence_type} source updated_at")
        for evidence_type, source_run in source_runs.items()
    )
    if pilot_started < source_started - RUN_CLOCK_SKEW or pilot_ended > source_updated + RUN_CLOCK_SKEW:
        raise EvidenceError("pilot timestamps are outside the source workflow run window")
    if generated_at < pilot_ended or generated_at > run_updated + RUN_CLOCK_SKEW:
        raise EvidenceError("generatedAt must follow the pilot and remain inside the producer run window")
    if generated_at < run_started - RUN_CLOCK_SKEW:
        raise EvidenceError("generatedAt precedes the producer run")
    if now < generated_at - RUN_CLOCK_SKEW or now - pilot_ended > MAX_EVIDENCE_AGE:
        raise EvidenceError("viewer product evidence is future-dated or stale")

    binding = root["binding"]
    if len(set(binding.values())) != len(binding):
        raise EvidenceError("session, tenant, operator and device binding hashes must be distinct")
    for evidence_type, child in children.items():
        require_equal(child["evidenceType"], evidence_type, f"{evidence_type} evidence type")
        require_equal(child["sourceRevision"], run["head_sha"], f"{evidence_type} source revision")
        require_equal(child["binding"], binding, f"{evidence_type} same-session binding")
        observed = parse_utc(child["observedAt"], f"{evidence_type}.observedAt")
        source_run = source_runs[evidence_type]
        source_run_updated = parse_utc(source_run["updated_at"], f"{evidence_type} source update")
        validate_source_attestation_timing(observed, source_run_updated, run_started, evidence_type)
        latest_observed = pilot_ended + RUN_CLOCK_SKEW
        if evidence_type in {"negative", "termination"}:
            latest_observed = pilot_started + MAX_MATRIX_WINDOW
        if observed < pilot_started - RUN_CLOCK_SKEW or observed > latest_observed:
            raise EvidenceError(f"{evidence_type} observedAt is outside the authorized evidence window")

    browser = children["browser"]["payload"]
    require_equal(browser["pilotStartedAt"], root["pilot"]["startedAt"], "browser pilot start")
    require_equal(browser["pilotEndedAt"], root["pilot"]["endedAt"], "browser pilot end")
    require_equal(browser["ackDrainCutoffAt"], browser["pilotEndedAt"], "browser ACK drain cutoff")
    broker = children["broker"]["payload"]
    audit = children["audit"]["payload"]
    states = broker["states"]
    captured = states["captured"]
    received = states["brokerReceived"]
    delivered = states["viewerDelivered"]
    rendered = states["viewerRendered"]
    if not captured >= received >= delivered >= rendered >= MIN_RENDERED_FRAMES:
        raise EvidenceError("state chain or minimum rendered-frame threshold failed")
    broker_drop_rate = (received - delivered) / received
    render_loss_rate = (delivered - rendered) / delivered
    if broker_drop_rate > MAX_BROKER_DROP_RATE:
        raise EvidenceError("broker-to-viewer drop-rate SLO failed")
    if render_loss_rate > MAX_RENDER_LOSS_RATE:
        raise EvidenceError("viewer-delivered to browser-rendered loss-rate SLO failed")

    require_equal(broker["framesSentMetricDelta"], delivered, "broker frames-sent metric")
    require_equal(broker["renderAckAcceptedMetricDelta"], rendered, "broker accepted render-ACK metric")
    require_equal(browser["renderAckAcceptedCount"], rendered, "browser accepted render-ACK count")
    require_equal(browser["renderAckAttemptedCount"], rendered, "browser attempted render-ACK count")
    require_equal(browser["renderAckRejectedCount"], 0, "browser rejected render-ACK count")
    require_equal(browser["renderAckPendingCount"], 0, "browser pending render-ACK count")
    require_equal(
        browser["maskedFrameSha256"], broker["dlp"]["maskedFrameSha256"],
        "delivered-path DLP frame hash",
    )
    require_equal(audit["framesDelivered"], delivered, "audit delivered-frame count")
    require_equal(audit["framesRenderAcknowledged"], rendered, "audit rendered-frame count")
    if broker["reconnectCount"] > MAX_RECONNECTS:
        raise EvidenceError("viewer reconnect SLO failed")
    if browser["firstFrameAgeMillis"] > FIRST_FRAME_MAX_MS:
        raise EvidenceError("first-frame SLO failed")
    ages = browser["steadyFrameAgeMillis"]
    if len(ages) != rendered:
        raise EvidenceError("steady frame-age sample count must equal rendered-frame count")
    p50 = percentile(ages, 0.50)
    p95 = percentile(ages, 0.95)
    if p95 > STEADY_P95_MAX_MS:
        raise EvidenceError("steady frame-age p95 SLO failed")

    validate_d30(children["d30"]["payload"])
    operator = children["operator"]["payload"]
    authorization_expires_at = verify_activation_authorization(
        client, operator, run["head_sha"], binding, pilot_started, pilot_ended,
        advisory_scope_bytes=advisory_scope_bytes,
        cross_ai_trust_root=cross_ai_trust_root,
        cross_ai_revocations=cross_ai_revocations,
        expected_cross_ai_trust_root_sha256=expected_cross_ai_trust_root_sha256,
        codex_executable_policy=codex_executable_policy,
        issuer_runtime_policy=issuer_runtime_policy,
        authority_observed_at=now,
        authority_repo_root=authority_repo_root,
    )
    validate_negative_and_termination(
        children["negative"]["payload"], children["termination"]["payload"],
        operator, binding, pilot_started, authorization_expires_at,
        {
            "negative": parse_utc(children["negative"]["observedAt"], "negative observedAt"),
            "termination": parse_utc(children["termination"]["observedAt"], "termination observedAt"),
        },
    )

    binding_digest = digest_json(binding)
    expires_at = min(pilot_ended + MAX_EVIDENCE_AGE, now + MARKER_VALIDITY)
    return {
        "schemaVersion": VERIFIER_SCHEMA,
        "status": "pass",
        "scope": "test-only-attended-recording-off-one-viewer",
        "repository": EXPECTED_REPOSITORY,
        "runId": run["id"],
        "runAttempt": run["run_attempt"],
        "runHeadSha": run["head_sha"],
        "artifactId": artifact["id"],
        "artifactDigest": archive_digest,
        "evidenceRootSha256": root_digest,
        "sessionBindingSha256": binding_digest,
        "pilotStartedAt": utc_seconds(pilot_started),
        "pilotEndedAt": utc_seconds(pilot_ended),
        "verifiedAt": utc_seconds(now),
        "expiresAt": utc_seconds(expires_at),
        "computed": {
            "pilotSeconds": int(pilot_seconds),
            "renderedFrames": rendered,
            "brokerDropRate": round(broker_drop_rate, 6),
            "renderLossRate": round(render_loss_rate, 6),
            "steadyFrameAgeP50Millis": p50,
            "steadyFrameAgeP95Millis": p95,
        },
    }


def verify_product_evidence(
    client: ApiClient, repository: str, run_id: int, now: datetime | None = None,
    *,
    advisory_scope_bytes: bytes | None = None,
    cross_ai_trust_root: dict[str, Any] | None = None,
    cross_ai_revocations: dict[str, Any] | None = None,
    expected_cross_ai_trust_root_sha256: str | None = None,
    codex_executable_policy: dict[str, Any] | None = None,
    issuer_runtime_policy: dict[str, Any] | None = None,
    authority_repo_root: Path | None = None,
) -> dict[str, Any]:
    validate_repository(repository)
    if run_id < 1:
        raise EvidenceError("run-id must be positive")
    run = fetch_run(client, repository, run_id)
    verified = fetch_verified_archive(client, repository, run_id)
    files = verified.files
    root_name = "viewer-product-evidence.json"
    if root_name not in files:
        raise EvidenceError(f"artifact is missing {root_name}")
    root = load_json_bytes(files[root_name], root_name)
    validate_schema(root, ROOT_SCHEMA, "root evidence")

    entries = root["evidence"]
    entry_types = [entry["type"] for entry in entries]
    entry_paths = [entry["path"] for entry in entries]
    if set(entry_types) != EXPECTED_CHILD_TYPES or len(set(entry_types)) != len(entry_types):
        raise EvidenceError("root evidence must contain each required child type exactly once")
    if len(set(entry_paths)) != len(entry_paths):
        raise EvidenceError("root evidence contains duplicate child paths")
    expected_files = {root_name, *entry_paths}
    if set(files) != expected_files:
        unexpected = sorted(set(files) - expected_files)
        missing = sorted(expected_files - set(files))
        raise EvidenceError(f"artifact file set mismatch; missing={missing} unexpected={unexpected}")

    children: dict[str, dict[str, Any]] = {}
    source_runs: dict[str, dict[str, Any]] = {}
    source_run_ids = [entry["source"]["runId"] for entry in entries]
    source_artifact_ids = [entry["source"]["artifactId"] for entry in entries]
    if len(set(source_run_ids)) != len(source_run_ids):
        raise EvidenceError("each child evidence type must come from a distinct source run")
    if len(set(source_artifact_ids)) != len(source_artifact_ids):
        raise EvidenceError("each child evidence type must come from a distinct source artifact")
    for entry in entries:
        raw = files[entry["path"]]
        if digest_bytes(raw) != entry["sha256"]:
            raise EvidenceError(f"child digest mismatch: {entry['path']}")
        source_raw, source_run = fetch_verified_source_child(
            client, entry["type"], entry, run["head_sha"]
        )
        if source_raw != raw:
            raise EvidenceError(f"aggregated child differs from verified source artifact: {entry['type']}")
        child = load_json_bytes(raw, entry["path"])
        validate_schema(child, CHILD_SCHEMA, entry["path"])
        children[entry["type"]] = child
        source_runs[entry["type"]] = source_run

    result = validate_semantics(
        client, root, children, run, source_runs, verified.artifact, digest_json(root), verified.archive_digest,
        (now or datetime.now(timezone.utc)).astimezone(timezone.utc),
        advisory_scope_bytes=advisory_scope_bytes,
        cross_ai_trust_root=cross_ai_trust_root,
        cross_ai_revocations=cross_ai_revocations,
        expected_cross_ai_trust_root_sha256=expected_cross_ai_trust_root_sha256,
        codex_executable_policy=codex_executable_policy,
        issuer_runtime_policy=issuer_runtime_policy,
        authority_repo_root=authority_repo_root,
    )
    result["marker"] = marker_text(result)
    return result


def marker_text(result: dict[str, Any]) -> str:
    return "\n".join((
        MARKER,
        "status: pass",
        f"scope: {result['scope']}",
        f"repository: {result['repository']}",
        f"run_id: {result['runId']}",
        f"run_attempt: {result['runAttempt']}",
        f"run_head_sha: {result['runHeadSha']}",
        f"artifact_id: {result['artifactId']}",
        f"artifact_digest: {result['artifactDigest']}",
        f"evidence_root_sha256: {result['evidenceRootSha256']}",
        f"session_binding_sha256: {result['sessionBindingSha256']}",
        f"pilot_started_at: {result['pilotStartedAt']}",
        f"pilot_ended_at: {result['pilotEndedAt']}",
        f"verified_at: {result['verifiedAt']}",
        f"expires_at: {result['expiresAt']}",
        "production_ready: false",
        "broad_rollout_ready: false",
        "multi_viewer_fanout_proven: false",
        "legal_acceptance: false",
        "",
    ))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", EXPECTED_REPOSITORY))
    parser.add_argument("--run-id", type=int, required=True, help="completed producer workflow run ID")
    parser.add_argument("--github-api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--github-token-env", default="GITHUB_TOKEN", help="environment variable containing GitHub API token")
    parser.add_argument("--output", type=Path, help="write redacted verifier result JSON")
    parser.add_argument("--marker-out", type=Path, help="write content-addressed acceptance marker")
    return parser.parse_args()


def write_json(path: Path | None, value: dict[str, Any]) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path:
        path.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


def main() -> int:
    args = parse_args()
    try:
        token = os.environ.get(args.github_token_env, "")
        result = verify_product_evidence(
            GitHubClient(token=token, api_base=args.github_api_url),
            args.repository,
            args.run_id,
            advisory_scope_bytes=None,
            authority_repo_root=ROOT,
        )
        write_json(args.output, result)
        if args.marker_out:
            args.marker_out.write_text(result["marker"], encoding="utf-8")
        return 0
    except (AuthorityUnavailable, EvidenceError, OSError, ValueError) as exc:
        write_json(args.output, {"schemaVersion": VERIFIER_SCHEMA, "status": "fail", "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
