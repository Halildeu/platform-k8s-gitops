#!/usr/bin/env python3
"""Validate Faz 24 direct-STT mTLS enablement preflight evidence.

This verifier covers the narrow step after Vault/ESO secret delivery and before
`AUDIO_GATEWAY_DIRECT_STT_ENABLED=true` is flipped. It proves the real
audio-gateway pod can read the mounted mTLS files and reach Denetim live-stt
over the SNI-safe 8243 path, while no audio has been sent yet.

It intentionally does not mutate Kubernetes, Vault, Denetim PC, Caddy, or
GitHub.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


EVIDENCE_SCHEMA_VERSION = "faz24.directSttMtlsEnablementPreflight.v1"
VERIFIER_SCHEMA_VERSION = "faz24.directSttMtlsEnablementPreflightVerifier.v1"

EXPECTED_ISSUE = "platform-ai#182"
EXPECTED_CLUSTER = "k3d-test"
EXPECTED_KUBECTL_CONTEXT = "k3d-test"
EXPECTED_NAMESPACE = "platform-test"
EXPECTED_DEPLOYMENT = "audio-gateway"
EXPECTED_AGGREGATE_SECRET = "audio-gateway-secrets"
EXPECTED_SECRET = "audio-gateway-direct-stt-mtls"
EXPECTED_SECRET_STORE = "vault-platform-gitops"
EXPECTED_VAULT_PATH = "kv/platform/audio-gateway-service"
EXPECTED_TRANSCRIBE_HOST = "live-stt.denetim"
EXPECTED_TRANSCRIBE_PORT = 8243
EXPECTED_HOST_ALIAS_IP = "10.99.0.2"
EXPECTED_NETPOL_CIDR = "10.99.0.2/32"
EXPECTED_MTLS_MOUNT = "/etc/direct-stt-mtls"

REQUIRED_VAULT_PROPERTIES = {
    "direct_stt_ca_crt",
    "direct_stt_client_crt",
    "direct_stt_client_key",
}
REQUIRED_SECRET_KEYS = {
    "direct-stt-ca.crt",
    "direct-stt-client.crt",
    "direct-stt-client.key",
}
AGGREGATE_SECRET_KEYS = {"SPRING_DATA_REDIS_PASSWORD"}

UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,160}$")
SAFE_CONDITION_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:/@-]{1,160}$")
SAFE_OPTIONAL_CONDITION_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:/@-]{0,160}$")
CAMEL_BOUNDARY_1_RE = re.compile(r"(.)([A-Z][a-z]+)")
CAMEL_BOUNDARY_2_RE = re.compile(r"([a-z0-9])([A-Z])")

FORBIDDEN_KEY_NAMES = {
    "access_token",
    "api_key",
    "auth_token",
    "audio",
    "audio_base64",
    "audio_bytes",
    "audiobase64",
    "audiobytes",
    "authorization",
    "bearer",
    "callback_endpoint",
    "callback_url",
    "cert_pem",
    "certificate",
    "certificate_pem",
    "client_secret",
    "command_line",
    "command_output",
    "cookie",
    "credential",
    "destination_endpoint",
    "destination_url",
    "endpoint_url",
    "idempotency_key",
    "internal_url",
    "jwt",
    "key_pem",
    "packet_capture",
    "password",
    "pcap",
    "pem",
    "private_key",
    "private_key_pem",
    "raw_audio",
    "raw_audio_bytes",
    "raw_command_output",
    "raw_output",
    "raw_request",
    "raw_response",
    "refresh_token",
    "secret",
    "secret_id",
    "session_token",
    "stt_endpoint",
    "stt_url",
    "text",
    "token",
    "transcribe_endpoint",
    "transcribe_url",
    "transcript",
    "transcript_text",
    "url",
    "webhook_url",
    "whisper_url",
}
FORBIDDEN_KEY_NAMES_COMPACT = {name.replace("_", "") for name in FORBIDDEN_KEY_NAMES}

SECRET_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"-----BEGIN CERTIFICATE-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\bAuthorization\s*:", re.IGNORECASE),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:https?|wss?)://[^\s\"']+", re.IGNORECASE),
    re.compile(r"data:audio/[A-Za-z0-9.+-]+;base64,", re.IGNORECASE),
]

BOUNDARY_EXPECTATIONS = {
    "vaultSeedAuthorityAccepted": True,
    "secretValuesIncluded": False,
    "directSttEnabled": False,
    "rawAudioSent": False,
    "transcribeCalled": False,
    "directAudioE2eProven": False,
    "i7ProdGateProven": False,
    "desktopMicLoopbackProven": False,
    "productionReady": False,
}


@dataclass
class Check:
    name: str
    passed: bool
    message: str


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalized_key(key: str) -> str:
    key = key.replace("-", "_").replace(".", "_").strip()
    key = CAMEL_BOUNDARY_1_RE.sub(r"\1_\2", key)
    key = CAMEL_BOUNDARY_2_RE.sub(r"\1_\2", key)
    return re.sub(r"_+", "_", key).lower()


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


def add(checks: list[Check], name: str, passed: bool, message: str) -> None:
    checks.append(Check(name=name, passed=passed, message=message))


def load_evidence(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = sys.stdin.read() if path is None else path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    except OSError as exc:
        return None, f"cannot read evidence: {exc}"

    if not isinstance(data, dict):
        return None, "top-level evidence must be a JSON object"
    return data, None


def as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def safe_name(value: Any) -> bool:
    return isinstance(value, str) and bool(SAFE_NAME_RE.match(value))


def sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.match(value))


def git_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(GIT_SHA_RE.match(value))


def string_set(value: Any) -> set[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return set()
    return set(value)


def safe_condition_value(value: Any, *, allow_empty: bool = False) -> bool:
    pattern = SAFE_OPTIONAL_CONDITION_VALUE_RE if allow_empty else SAFE_CONDITION_VALUE_RE
    return isinstance(value, str) and bool(pattern.match(value))


def validate_no_sensitive_content(data: dict[str, Any], checks: list[Check]) -> None:
    findings: list[str] = []
    for path, key, value in iter_values(data):
        if key is not None:
            normalized = normalized_key(key)
            if normalized in FORBIDDEN_KEY_NAMES or normalized.replace("_", "") in FORBIDDEN_KEY_NAMES_COMPACT:
                findings.append(f"{path}: forbidden key '{key}'")
                continue
        if isinstance(value, str):
            for pattern in SECRET_VALUE_PATTERNS:
                if pattern.search(value):
                    findings.append(f"{path}: secret-like, URL-like, or raw audio/certificate value")
                    break

    add(
        checks,
        "no_sensitive_content",
        not findings,
        "metadata-only evidence"
        if not findings
        else "; ".join(findings[:8]),
    )


def validate_top_level(data: dict[str, Any], checks: list[Check]) -> None:
    add(
        checks,
        "schema_version",
        data.get("schemaVersion") == EVIDENCE_SCHEMA_VERSION,
        f"schemaVersion must be {EVIDENCE_SCHEMA_VERSION}",
    )
    add(checks, "status_pass", data.get("status") == "pass", "status must be pass")
    add(checks, "issue", data.get("issue") == EXPECTED_ISSUE, f"issue must be {EXPECTED_ISSUE}")
    add(
        checks,
        "generated_at",
        isinstance(data.get("generatedAt"), str) and bool(UTC_TIMESTAMP_RE.match(data["generatedAt"])),
        "generatedAt must use UTC YYYY-MM-DDTHH:MM:SSZ",
    )
    failures = data.get("failures")
    add(checks, "failures_empty", failures in (None, []), "failures must be absent or empty")


def validate_source(data: dict[str, Any], checks: list[Check]) -> None:
    source = data.get("source")
    if not isinstance(source, dict):
        add(checks, "source_shape", False, "source must be an object")
        return
    add(checks, "source_gitops_commit", git_sha(source.get("gitopsCommit")), "source.gitopsCommit must be 40 lowercase hex chars")
    add(checks, "source_backend_digest", sha256(source.get("backendImageDigest")), "source.backendImageDigest must be sha256 hex")


def validate_environment(data: dict[str, Any], checks: list[Check]) -> None:
    env = data.get("environment")
    if not isinstance(env, dict):
        add(checks, "environment_shape", False, "environment must be an object")
        return
    add(checks, "environment_cluster", env.get("cluster") == EXPECTED_CLUSTER, f"cluster must be {EXPECTED_CLUSTER}")
    add(
        checks,
        "environment_kubectl_context",
        env.get("kubectlContext") == EXPECTED_KUBECTL_CONTEXT,
        f"kubectlContext must be {EXPECTED_KUBECTL_CONTEXT}; do not rely on kubectl's default context",
    )
    add(checks, "environment_context_available", env.get("contextAvailable") is True, "kubectl context must exist locally")
    add(checks, "environment_namespace_reachable", env.get("namespaceReachable") is True, "target namespace must be reachable through the explicit context")
    add(checks, "environment_context_failure_empty", env.get("contextFailure") == "", "contextFailure must be empty for pass evidence")
    add(checks, "environment_namespace", env.get("namespace") == EXPECTED_NAMESPACE, f"namespace must be {EXPECTED_NAMESPACE}")
    add(checks, "environment_deployment", env.get("deployment") == EXPECTED_DEPLOYMENT, f"deployment must be {EXPECTED_DEPLOYMENT}")
    add(checks, "environment_pod_name", safe_name(env.get("podName")), "podName must be bounded safe metadata")
    add(checks, "environment_pod_ready", env.get("podReady") is True, "podReady must be true")


def validate_desired_state(data: dict[str, Any], checks: list[Check]) -> None:
    desired = data.get("desiredState")
    if not isinstance(desired, dict):
        add(checks, "desired_state_shape", False, "desiredState must be an object")
        return
    add(checks, "desired_direct_stt_disabled", desired.get("directSttEnabled") is False, "directSttEnabled must still be false before flag flip")
    add(checks, "desired_transcribe_host", desired.get("transcribeHost") == EXPECTED_TRANSCRIBE_HOST, f"transcribeHost must be {EXPECTED_TRANSCRIBE_HOST}")
    add(checks, "desired_transcribe_port", as_int(desired.get("transcribePort")) == EXPECTED_TRANSCRIBE_PORT, f"transcribePort must be {EXPECTED_TRANSCRIBE_PORT}")
    add(checks, "desired_host_alias_ip", desired.get("hostAliasIp") == EXPECTED_HOST_ALIAS_IP, f"hostAliasIp must be {EXPECTED_HOST_ALIAS_IP}")
    add(checks, "desired_netpol_cidr", desired.get("networkPolicyCidr") == EXPECTED_NETPOL_CIDR, f"networkPolicyCidr must be {EXPECTED_NETPOL_CIDR}")
    add(checks, "desired_netpol_port", as_int(desired.get("networkPolicyPort")) == EXPECTED_TRANSCRIBE_PORT, f"networkPolicyPort must be {EXPECTED_TRANSCRIBE_PORT}")
    add(checks, "desired_mtls_mount_path", desired.get("mtlsMountPath") == EXPECTED_MTLS_MOUNT, f"mtlsMountPath must be {EXPECTED_MTLS_MOUNT}")
    add(checks, "desired_mtls_mount_present", desired.get("mtlsMountPresent") is True, "mtls mount must be present")
    add(checks, "desired_mtls_secret_name", desired.get("mtlsSecretName") == EXPECTED_SECRET, f"mtlsSecretName must be {EXPECTED_SECRET}")
    add(checks, "desired_mtls_secret_optional", desired.get("mtlsSecretOptional") is True, "mTLS Secret mount must stay optional while direct-STT is disabled")


def validate_external_secret(data: dict[str, Any], checks: list[Check]) -> None:
    external = data.get("externalSecret")
    if not isinstance(external, dict):
        add(checks, "external_secret_shape", False, "externalSecret must be an object")
        return
    add(checks, "external_secret_name", external.get("name") == EXPECTED_SECRET, f"name must be {EXPECTED_SECRET}")
    add(checks, "external_secret_ready", external.get("ready") is True, "ExternalSecret must be Ready=True")
    add(checks, "external_secret_store", external.get("secretStore") == EXPECTED_SECRET_STORE, f"secretStore must be {EXPECTED_SECRET_STORE}")
    add(checks, "external_secret_vault_path", external.get("vaultPath") == EXPECTED_VAULT_PATH, f"vaultPath must be {EXPECTED_VAULT_PATH}")
    add(
        checks,
        "external_secret_properties",
        REQUIRED_VAULT_PROPERTIES.issubset(string_set(external.get("mappedVaultProperties"))),
        f"mappedVaultProperties must include {', '.join(sorted(REQUIRED_VAULT_PROPERTIES))}",
    )
    add(
        checks,
        "external_secret_keys",
        REQUIRED_SECRET_KEYS.issubset(string_set(external.get("targetSecretKeys"))),
        f"targetSecretKeys must include {', '.join(sorted(REQUIRED_SECRET_KEYS))}",
    )
    add(checks, "external_secret_values_absent", external.get("secretValueIncluded") is False, "secretValueIncluded must be false")

    conditions = external.get("conditions")
    condition_findings: list[str] = []
    if not isinstance(conditions, list) or len(conditions) > 6:
        condition_findings.append("conditions must be a list of at most 6 items")
    else:
        for index, condition in enumerate(conditions):
            if not isinstance(condition, dict):
                condition_findings.append(f"conditions[{index}] must be an object")
                continue
            for key in ["type", "status", "reason"]:
                if not safe_condition_value(condition.get(key)):
                    condition_findings.append(f"conditions[{index}].{key} must be bounded metadata")
            if not safe_condition_value(condition.get("lastTransitionTime"), allow_empty=True):
                condition_findings.append(
                    f"conditions[{index}].lastTransitionTime must be bounded metadata"
                )
            if condition.get("messageIncluded") is not False or "message" in condition:
                condition_findings.append(f"conditions[{index}] must not include raw message text")
            if not isinstance(condition.get("messagePresent"), bool):
                condition_findings.append(f"conditions[{index}].messagePresent must be boolean")
            message_length = as_int(condition.get("messageLength"))
            if message_length is None or not 0 <= message_length <= 20000:
                condition_findings.append(f"conditions[{index}].messageLength must be 0..20000")

    add(
        checks,
        "external_secret_conditions_redacted",
        not condition_findings,
        "ExternalSecret condition metadata is bounded and redacted"
        if not condition_findings
        else "; ".join(condition_findings[:6]),
    )


def validate_runtime_secret(data: dict[str, Any], checks: list[Check]) -> None:
    runtime = data.get("runtimeSecret")
    if not isinstance(runtime, dict):
        add(checks, "runtime_secret_shape", False, "runtimeSecret must be an object")
        return
    add(checks, "runtime_secret_name", runtime.get("name") == EXPECTED_SECRET, f"name must be {EXPECTED_SECRET}")
    add(
        checks,
        "runtime_secret_keys",
        REQUIRED_SECRET_KEYS.issubset(string_set(runtime.get("keyNames"))),
        f"keyNames must include {', '.join(sorted(REQUIRED_SECRET_KEYS))}",
    )
    add(checks, "runtime_secret_values_absent", runtime.get("secretValueIncluded") is False, "secretValueIncluded must be false")
    add(checks, "runtime_secret_env_risk", runtime.get("fileLikeKeysNotExportedAsEnv") is True, "file-like keys must not be exported as env vars")
    add(checks, "runtime_secret_not_env_from", runtime.get("dedicatedSecretNotEnvFrom") is True, "direct-STT mTLS Secret must not be referenced by envFrom")


def validate_aggregate_secret(data: dict[str, Any], checks: list[Check]) -> None:
    aggregate = data.get("aggregateSecret")
    if not isinstance(aggregate, dict):
        add(checks, "aggregate_secret_shape", False, "aggregateSecret must be an object")
        return
    add(checks, "aggregate_secret_name", aggregate.get("name") == EXPECTED_AGGREGATE_SECRET, f"name must be {EXPECTED_AGGREGATE_SECRET}")
    add(checks, "aggregate_secret_ready", aggregate.get("ready") is True, "aggregate Secret ExternalSecret must remain Ready=True")
    add(
        checks,
        "aggregate_secret_target_redis_key",
        AGGREGATE_SECRET_KEYS.issubset(string_set(aggregate.get("targetSecretKeys"))),
        "aggregate ExternalSecret target must keep SPRING_DATA_REDIS_PASSWORD",
    )
    add(
        checks,
        "aggregate_secret_runtime_redis_key",
        AGGREGATE_SECRET_KEYS.issubset(string_set(aggregate.get("runtimeKeyNames"))),
        "aggregate runtime Secret must keep SPRING_DATA_REDIS_PASSWORD",
    )
    add(
        checks,
        "aggregate_secret_no_direct_stt_keys",
        aggregate.get("directSttKeysPresent") is False,
        "direct-STT mTLS keys must not be present in audio-gateway-secrets",
    )
    add(checks, "aggregate_secret_values_absent", aggregate.get("secretValueIncluded") is False, "secretValueIncluded must be false")


def validate_mtls_probe(data: dict[str, Any], checks: list[Check]) -> None:
    probe = data.get("mtlsProbe")
    if not isinstance(probe, dict):
        add(checks, "mtls_probe_shape", False, "mtlsProbe must be an object")
        return
    add(checks, "mtls_probe_real_pod", probe.get("fromRealPod") is True, "mtls probe must run from real audio-gateway pod")
    add(checks, "mtls_probe_host", probe.get("host") == EXPECTED_TRANSCRIBE_HOST, f"host must be {EXPECTED_TRANSCRIBE_HOST}")
    add(checks, "mtls_probe_port", as_int(probe.get("port")) == EXPECTED_TRANSCRIBE_PORT, f"port must be {EXPECTED_TRANSCRIBE_PORT}")
    add(checks, "mtls_probe_client_auth", probe.get("clientCertificateUsed") is True, "clientCertificateUsed must be true")
    add(checks, "mtls_probe_health_status", as_int(probe.get("healthHttpStatus")) == 200, "healthHttpStatus must be 200")
    add(checks, "mtls_probe_secret_values_absent", probe.get("secretValueIncluded") is False, "secretValueIncluded must be false")
    total_ms = as_int(probe.get("totalMs"))
    add(checks, "mtls_probe_total_ms", total_ms is not None and 0 < total_ms <= 30000, "totalMs must be 1..30000")


def validate_boundaries(data: dict[str, Any], checks: list[Check]) -> None:
    boundaries = data.get("boundaries")
    if not isinstance(boundaries, dict):
        add(checks, "boundaries_shape", False, "boundaries must be an object")
        return
    for key, expected in BOUNDARY_EXPECTATIONS.items():
        add(checks, f"boundary_{key}", boundaries.get(key) is expected, f"{key} must be {str(expected).lower()}")


def verify(data: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    validate_no_sensitive_content(data, checks)
    validate_top_level(data, checks)
    validate_source(data, checks)
    validate_environment(data, checks)
    validate_desired_state(data, checks)
    validate_external_secret(data, checks)
    validate_aggregate_secret(data, checks)
    validate_runtime_secret(data, checks)
    validate_mtls_probe(data, checks)
    validate_boundaries(data, checks)
    return checks


def write_summary(path: Path, checks: list[Check]) -> None:
    passed = all(check.passed for check in checks)
    summary = {
        "schemaVersion": VERIFIER_SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "status": "pass" if passed else "fail",
        "passed": sum(1 for check in checks if check.passed),
        "total": len(checks),
        "checks": [asdict(check) for check in checks],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_human(checks: list[Check]) -> None:
    for check in checks:
        symbol = "OK" if check.passed else "FAIL"
        print(f"{symbol} {check.name}: {check.message}")
    passed = sum(1 for check in checks if check.passed)
    print(f"\nFaz 24 direct-STT mTLS enablement preflight: {'PASS' if passed == len(checks) else 'FAIL'} ({passed}/{len(checks)})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "evidence",
        nargs="?",
        type=Path,
        help="Evidence JSON path. Reads stdin when omitted.",
    )
    parser.add_argument("--summary-json", type=Path, help="Write machine-readable verifier summary JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data, error = load_evidence(args.evidence)
    if error is not None:
        print(f"FAIL evidence_load: {error}", file=sys.stderr)
        if args.summary_json:
            write_summary(args.summary_json, [Check("evidence_load", False, error)])
        return 1
    assert data is not None

    checks = verify(data)
    print_human(checks)
    if args.summary_json:
        write_summary(args.summary_json, checks)
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
