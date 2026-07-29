#!/usr/bin/env python3
"""Validate Faz 24 #182 direct-STT e2e evidence.

The #182 acceptance surface is narrow but strict:

- audio-gateway direct-STT is enabled in the real test deployment.
- The pod uses the mTLS/SNI path to live-stt and receives a transcript result.
- The same session/chunk/correlation is present in the result stream and the
  durable, hash-chained compute-plane audit record.
- Evidence stays metadata-only: no PEM values, tokens, raw audio, transcript
  text, destination URLs, or raw command output.

This verifier does not mutate Kubernetes, Vault, Denetim PC, Caddy, or GitHub.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable


EVIDENCE_SCHEMA_VERSION = "faz24.directSttE2eEvidence.v1"
VERIFIER_SCHEMA_VERSION = "faz24.directSttE2eVerifier.v1"

EXPECTED_ISSUE = "platform-ai#182"
EXPECTED_CLUSTER = "k3d-test"
EXPECTED_KUBECTL_CONTEXT = "k3d-test"
EXPECTED_NAMESPACE = "platform-test"
EXPECTED_DEPLOYMENT = "audio-gateway"
EXPECTED_MTLS_SECRET = "audio-gateway-direct-stt-mtls"
EXPECTED_TRANSCRIBE_HOST = "live-stt.denetim"
EXPECTED_TRANSCRIBE_PORT = 8243
EXPECTED_HOST_ALIAS_IP = "10.99.0.2"
EXPECTED_MTLS_MOUNT = "/etc/direct-stt-mtls"
EXPECTED_RESULT_STREAM = "transcript:direct-stt-results"
EXPECTED_AUDIT_STREAM = "audit:events"
EXPECTED_AUDIT_EVENT = "CHUNK_FORWARDED_TO_COMPUTE_PLANE"
REQUIRED_SECRET_KEYS = {
    "direct-stt-ca.crt",
    "direct-stt-client.crt",
    "direct-stt-client.key",
}

UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
SESSION_ID_RE = re.compile(r"^SES-[A-Za-z0-9_-]{4,120}$")
REDIS_ID_RE = re.compile(r"^\d+-\d+$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,160}$")
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
    "credential",
    "command_line",
    "command_output",
    "cookie",
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
    "segments",
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
    "directAudioE2eProven": True,
    "directSttTranscriptProven": True,
    "computePlaneAuditProven": True,
    "directClientToStt": False,
    "rawAudioIncluded": False,
    "rawTranscriptIncluded": False,
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


def uuidish(value: Any) -> bool:
    return isinstance(value, str) and bool(UUID_RE.match(value))


def redis_id(value: Any) -> bool:
    return isinstance(value, str) and bool(REDIS_ID_RE.match(value))


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
    add(checks, "token_not_included", data.get("tokenIncluded") is False, "tokenIncluded must be false")
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
    add(
        checks,
        "source_backend_digest",
        sha256(source.get("backendImageDigest")),
        "source.backendImageDigest must be sha256 hex without raw image pull output",
    )


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
    add(checks, "environment_namespace", env.get("namespace") == EXPECTED_NAMESPACE, f"namespace must be {EXPECTED_NAMESPACE}")
    add(checks, "environment_deployment", env.get("deployment") == EXPECTED_DEPLOYMENT, f"deployment must be {EXPECTED_DEPLOYMENT}")
    add(checks, "environment_pod_name", safe_name(env.get("podName")), "podName must be bounded safe metadata")
    add(checks, "environment_pod_ready", env.get("podReady") is True, "podReady must be true")


def validate_runtime(data: dict[str, Any], checks: list[Check]) -> None:
    runtime = data.get("runtime")
    if not isinstance(runtime, dict):
        add(checks, "runtime_shape", False, "runtime must be an object")
        return

    add(checks, "runtime_direct_stt_enabled", runtime.get("directSttEnabled") is True, "directSttEnabled must be true")
    add(checks, "runtime_transcribe_host", runtime.get("transcribeHost") == EXPECTED_TRANSCRIBE_HOST, f"transcribeHost must be {EXPECTED_TRANSCRIBE_HOST}")
    add(checks, "runtime_transcribe_port", as_int(runtime.get("transcribePort")) == EXPECTED_TRANSCRIBE_PORT, f"transcribePort must be {EXPECTED_TRANSCRIBE_PORT}")
    add(checks, "runtime_host_alias_ip", runtime.get("hostAliasIp") == EXPECTED_HOST_ALIAS_IP, f"hostAliasIp must be {EXPECTED_HOST_ALIAS_IP}")
    add(checks, "runtime_mtls_mount_path", runtime.get("mtlsMountPath") == EXPECTED_MTLS_MOUNT, f"mtlsMountPath must be {EXPECTED_MTLS_MOUNT}")
    add(checks, "runtime_mtls_mount_present", runtime.get("mtlsMountPresent") is True, "mtls mount must be present")
    add(checks, "runtime_mtls_secret_name", runtime.get("mtlsSecretName") == EXPECTED_MTLS_SECRET, f"mtlsSecretName must be {EXPECTED_MTLS_SECRET}")
    add(checks, "runtime_secret_value_absent", runtime.get("secretValueIncluded") is False, "secretValueIncluded must be false")

    keys = runtime.get("mtlsSecretKeyNames")
    keys_set = set(keys) if isinstance(keys, list) and all(isinstance(k, str) for k in keys) else set()
    add(
        checks,
        "runtime_mtls_secret_keys",
        REQUIRED_SECRET_KEYS.issubset(keys_set),
        f"mtlsSecretKeyNames must include {', '.join(sorted(REQUIRED_SECRET_KEYS))}",
    )


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
    total_ms = as_int(probe.get("totalMs"))
    add(checks, "mtls_probe_total_ms", total_ms is not None and 0 < total_ms <= 30000, "totalMs must be 1..30000")


def validate_flow(data: dict[str, Any], checks: list[Check]) -> None:
    flow = data.get("flow")
    if not isinstance(flow, dict):
        add(checks, "flow_shape", False, "flow must be an object")
        return

    add(
        checks,
        "flow_session_id",
        isinstance(flow.get("sessionId"), str) and bool(SESSION_ID_RE.match(flow["sessionId"])),
        "sessionId must match the audio-gateway SES-* contract",
    )
    chunk_seq = as_int(flow.get("chunkSeq"))
    add(checks, "flow_chunk_seq", chunk_seq is not None and chunk_seq >= 0, "chunkSeq must be >= 0")
    add(checks, "flow_correlation_id", safe_name(flow.get("correlationId")), "correlationId must be bounded safe metadata")
    add(checks, "flow_sample_hash", sha256(flow.get("sampleSha256")), "sampleSha256 must be sha256 of privacy-safe sample")
    add(checks, "flow_raw_audio_absent", flow.get("rawAudioIncluded") is False, "rawAudioIncluded must be false")
    add(checks, "flow_meeting_status", as_int(flow.get("meetingCreateHttpStatus")) in {200, 201}, "meetingCreateHttpStatus must be 200 or 201")
    add(checks, "flow_chunk_status", as_int(flow.get("chunkUploadHttpStatus")) in {200, 201, 202, 204}, "chunkUploadHttpStatus must be 2xx accepted")
    add(checks, "flow_finish_status", as_int(flow.get("finishHttpStatus")) in {200, 201, 202, 204}, "finishHttpStatus must be 2xx accepted")
    add(checks, "flow_transcribe_status", as_int(flow.get("transcribeHttpStatus")) == 200, "transcribeHttpStatus must be 200")
    add(checks, "flow_result_stream_key", flow.get("resultStreamKey") == EXPECTED_RESULT_STREAM, f"resultStreamKey must be {EXPECTED_RESULT_STREAM}")
    add(checks, "flow_result_stream_entry", flow.get("resultStreamEntryFound") is True, "result stream entry must be found")
    add(checks, "flow_result_record_id", redis_id(flow.get("resultStreamRecordId")), "resultStreamRecordId must be Redis stream id shaped")
    add(checks, "flow_transcript_text_absent", flow.get("transcriptTextIncluded") is False, "transcriptTextIncluded must be false")
    add(checks, "flow_transcript_hash", sha256(flow.get("transcriptSha256")), "transcriptSha256 must be sha256 of transcript text")
    transcript_chars = as_int(flow.get("transcriptCharCount"))
    add(checks, "flow_transcript_char_count", transcript_chars is not None and transcript_chars > 0, "transcriptCharCount must be > 0")


def validate_audit(data: dict[str, Any], checks: list[Check]) -> None:
    audit = data.get("audit")
    if not isinstance(audit, dict):
        add(checks, "audit_shape", False, "audit must be an object")
        return
    add(checks, "audit_stream_key", audit.get("streamKey") == EXPECTED_AUDIT_STREAM, f"streamKey must be {EXPECTED_AUDIT_STREAM}")
    add(checks, "audit_evidence_source", audit.get("evidenceSource") == "durable-db", "evidenceSource must be durable-db")
    add(checks, "audit_event_type", audit.get("eventType") == EXPECTED_AUDIT_EVENT, f"eventType must be {EXPECTED_AUDIT_EVENT}")
    add(checks, "audit_event_found", audit.get("eventFound") is True, "audit event must be found")
    add(checks, "audit_durable_event_found", audit.get("durableEventFound") is True, "durable audit event must be found")
    add(checks, "audit_record_id", redis_id(audit.get("recordId")), "recordId must be Redis stream id shaped")
    add(checks, "audit_session_match", audit.get("sessionIdMatches") is True, "sessionIdMatches must be true")
    add(checks, "audit_chunk_match", audit.get("chunkSeqMatches") is True, "chunkSeqMatches must be true")
    add(checks, "audit_correlation_match", audit.get("correlationIdMatches") is True, "correlationIdMatches must be true")
    add(checks, "audit_timestamp_present", audit.get("eventTimestampPresent") is True, "eventTimestampPresent must be true")
    add(checks, "audit_entry_hash_present", audit.get("entryHashPresent") is True, "entryHashPresent must be true")
    add(checks, "audit_prev_hash_present", audit.get("prevHashPresent") is True, "prevHashPresent must be true")
    add(checks, "audit_hash_algorithm", audit.get("entryHashAlgorithm") == "SHA-256", "entryHashAlgorithm must be SHA-256")
    add(checks, "audit_hash_version", str(audit.get("entryHashVersion")) == "1", "entryHashVersion must be 1")


def validate_persistence(data: dict[str, Any], checks: list[Check]) -> None:
    persistence = data.get("persistence")
    if not isinstance(persistence, dict):
        add(checks, "persistence_shape", False, "persistence must be an object")
        return
    expected_false = [
        "rawAudioInRedis",
        "rawAudioInResultStream",
        "rawAudioInLogs",
        "rawTranscriptInEvidence",
        "rawTranscriptInLogs",
    ]
    add(
        checks,
        "persistence_metadata_only",
        persistence.get("redisAudioChunkMetadataOnly") is True,
        "redisAudioChunkMetadataOnly must be true",
    )
    for key in expected_false:
        add(checks, f"persistence_{key}", persistence.get(key) is False, f"{key} must be false")


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
    validate_runtime(data, checks)
    validate_mtls_probe(data, checks)
    validate_flow(data, checks)
    validate_audit(data, checks)
    validate_persistence(data, checks)
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
    print(f"\nFaz 24 direct-STT e2e evidence: {'PASS' if passed == len(checks) else 'FAIL'} ({passed}/{len(checks)})")


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
