#!/usr/bin/env python3
"""Shared fail-closed contract for the Faz 24 transcript-ready pre-enable gate."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Iterable


POLICY_SCHEMA = "faz24.transcriptReadyPreEnablePolicy.v1"
EVIDENCE_SCHEMA = "faz24.transcriptReadyPreEnableEvidence.v1"
VERDICT_SCHEMA = "faz24.transcriptReadyPreEnableVerdict.v2"
PERMIT_TRUST_ROOT_SCHEMA = "faz24.transcriptReadyPermitTrustRoot.v1"
PERMIT_PAYLOAD_TYPE = (
    "application/vnd.acik.faz24.transcript-ready-pre-enable-verdict.v2+json"
)
ISSUE = "platform-k8s-gitops#2610"
SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,200}$")
SSH_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SQL_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
KEY_ID_RE = re.compile(
    r"^vault-transit://[a-z0-9][a-z0-9-]*/[A-Za-z0-9_.-]+#v[1-9][0-9]*$"
)
APP_ENVIRONMENTS = frozenset({"test", "stage", "prod"})
VERDICT_FIELDS = frozenset(
    {
        "schemaVersion",
        "generatedAt",
        "issue",
        "status",
        "enableAuthorized",
        "checks",
        "requiredRemediationEvidence",
        "binding",
        "boundary",
    }
)
VERDICT_CHECK_FIELDS = frozenset({"name", "passed", "message", "remediation"})
VERDICT_BINDING_FIELDS = frozenset(
    {
        "targetAppEnv",
        "expectedGitopsCommit",
        "policySha256",
        "producerCapability",
        "liveTranscriptPod",
        "hostStartupGuard",
        "evidenceAgeSeconds",
    }
)
PRODUCER_BINDING_FIELDS = frozenset({"transcriptImageDigest", "backendCommit"})
LIVE_POD_BINDING_FIELDS = frozenset(
    {"podUid", "imageDigest", "observedAt", "evidenceSha256"}
)
HOST_GUARD_BINDING_FIELDS = frozenset(
    {"platformAiCommit", "startupScriptSha256", "permitRequired"}
)
PERMIT_TRUST_ROOT_FIELDS = frozenset(
    {
        "schemaVersion",
        "keyId",
        "algorithm",
        "publicKeyBase64",
        "allowedAppEnvironments",
        "notBefore",
        "notAfter",
    }
)
MAX_DOCUMENT_BYTES = 1024 * 1024

FORBIDDEN_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "csrf_token",
    "credential",
    "id_token",
    "password",
    "payload",
    "private_key",
    "raw_output",
    "refresh_token",
    "secret",
    "session_token",
    "token",
    "transcript",
    "transcript_text",
}
FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:postgres|redis|rediss)://[^\s]+", re.IGNORECASE),
)


class ContractError(RuntimeError):
    """Evidence or policy violated the bounded gate contract."""


def _reject_float(_value: str) -> None:
    raise ContractError("JSON floating-point values are forbidden")


def _reject_constant(_value: str) -> None:
    raise ContractError("JSON non-finite constants are forbidden")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_utc(value: Any) -> dt.datetime:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise ContractError("timestamp must use UTC YYYY-MM-DDTHH:MM:SSZ")
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc
    )


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def binding_set_sha256_from_sha1s(values: Iterable[str]) -> str:
    hashes = sorted(values)
    if any(not SHA1_RE.fullmatch(value) for value in hashes):
        raise ContractError("compatible binding hashes must be lowercase SHA-1")
    return sha256_bytes(canonical_json(hashes))


def binding_set_sha256(values: Iterable[str]) -> str:
    return binding_set_sha256_from_sha1s(
        hashlib.sha1(value.encode("utf-8")).hexdigest() for value in values
    )


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{path} root must be an object")
    return value


def load_strict_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read {label}") from exc
    if (
        not raw
        or len(raw) > MAX_DOCUMENT_BYTES
        or b"\x00" in raw
        or raw.startswith(b"\xef\xbb\xbf")
    ):
        raise ContractError(f"{label} byte contract is invalid")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} root must be an object")
    return raw, value


def require_secure_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ContractError(f"{label} is unavailable") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or not 20 <= metadata.st_size <= 4096
    ):
        raise ContractError(f"{label} must be an owner-only regular file")


def load_policy(path: Path) -> dict[str, Any]:
    policy = load_json(path)
    if policy.get("schemaVersion") != POLICY_SCHEMA:
        raise ContractError(f"policy schemaVersion must be {POLICY_SCHEMA}")
    if policy.get("issue") != ISSUE:
        raise ContractError(f"policy issue must be {ISSUE}")
    if policy.get("activationMode") not in {"first-enable", "reactivation"}:
        raise ContractError(
            "policy activationMode must be first-enable or reactivation"
        )
    capabilities = policy.get("producerCapabilities")
    guards = policy.get("hostStartupGuards")
    if not isinstance(capabilities, list) or not isinstance(guards, list):
        raise ContractError("policy capability allowlists must be arrays")
    environment = policy.get("environment")
    if not isinstance(environment, dict):
        raise ContractError("policy environment must be an object")
    required_names = (
        "appEnv",
        "cluster",
        "kubectlContext",
        "namespace",
        "transcriptDeployment",
        "postgresHost",
        "postgresDatabase",
        "postgresSchema",
        "postgresSslMode",
        "redisHost",
        "redisStream",
        "redisGroup",
        "gpuHost",
        "gpuHostComputerName",
    )
    for name in required_names:
        require_safe_name(environment.get(name), f"environment.{name}")
    if environment["appEnv"] not in APP_ENVIRONMENTS:
        raise ContractError("environment.appEnv must be test, stage or prod")
    if not SQL_IDENTIFIER_RE.fullmatch(environment["postgresSchema"]):
        raise ContractError(
            "environment.postgresSchema must be a simple lowercase identifier"
        )
    if not SSH_ALIAS_RE.fullmatch(environment["gpuHost"]):
        raise ContractError("environment.gpuHost must be a simple SSH alias")
    for name in ("postgresPort", "redisPort"):
        port = environment.get(name)
        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65535
        ):
            raise ContractError(f"environment.{name} must be a TCP port")
    if not isinstance(environment.get("redisTls"), bool):
        raise ContractError("environment.redisTls must be boolean")
    freshness = policy.get("freshnessSeconds")
    if isinstance(freshness, bool) or not isinstance(freshness, int):
        raise ContractError("policy freshnessSeconds must be an integer")
    if not 60 <= freshness <= 3600:
        raise ContractError("policy freshnessSeconds must be between 60 and 3600")
    collection_window = policy.get("maxCollectionSeconds")
    if (
        isinstance(collection_window, bool)
        or not isinstance(collection_window, int)
        or not 30 <= collection_window <= freshness
    ):
        raise ContractError(
            "policy maxCollectionSeconds must be between 30 and freshnessSeconds"
        )
    max_entries = policy.get("redisScanMaxEntries")
    if (
        isinstance(max_entries, bool)
        or not isinstance(max_entries, int)
        or not 1 <= max_entries <= 1_000_000
    ):
        raise ContractError("policy redisScanMaxEntries must be between 1 and 1000000")
    require_safe_name(
        policy.get("requiredStartupGateMarker"), "requiredStartupGateMarker"
    )
    return policy


def normalized_key(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def iter_values(value: Any, path: str = "$") -> Iterable[tuple[str, str | None, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, str(key), child
            yield from iter_values(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield child_path, None, child
            yield from iter_values(child, child_path)


def sensitive_findings(value: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    for path, key, child in iter_values(value):
        if key is not None and normalized_key(key) in FORBIDDEN_KEYS:
            findings.append(f"{path}: forbidden key")
            continue
        if isinstance(child, str):
            if any(pattern.search(child) for pattern in FORBIDDEN_VALUE_PATTERNS):
                findings.append(f"{path}: secret-like value")
    return findings


def require_sha256(value: Any, label: str, *, prefix: bool = False) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ContractError(f"{label} must be a SHA-256 value")
    if prefix and not value.startswith("sha256:"):
        raise ContractError(f"{label} must use sha256: prefix")
    return value


def require_git_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not GIT_SHA_RE.fullmatch(value):
        raise ContractError(f"{label} must be a full lowercase Git commit")
    return value


def require_safe_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SAFE_NAME_RE.fullmatch(value):
        raise ContractError(f"{label} must be bounded safe metadata")
    return value
