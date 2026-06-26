#!/usr/bin/env python3
"""Validate Faz 24 platform-desktop mic + loopback capture evidence.

This verifier is intentionally metadata-only. It accepts a redacted evidence
envelope from a real platform-desktop smoke run that proves both microphone and
system-loopback capture reached the public audio-gateway lifecycle. It rejects
raw audio, transcript text, tokens, destination URLs, direct-STT overclaims, and
production-readiness claims.
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


EVIDENCE_SCHEMA_VERSION = "faz24.desktopCaptureEvidence.v1"
VERIFIER_SCHEMA_VERSION = "faz24.desktopCaptureEvidenceVerifier.v1"

EXPECTED_CLIENT_KIND = "platform-desktop"
EXPECTED_SOURCES = ("microphone", "loopback")
EXPECTED_STEPS = [
    "desktop_app_started",
    "permission_check",
    "mic_capture",
    "loopback_capture",
    "record_consent",
    "start_session",
    "upload_mic_chunk",
    "upload_loopback_chunk",
    "finish_session",
    "session_status",
]

HTTP_STEP_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "record_consent": {
        "method": "POST",
        "path": "/api/v1/audio-gateway/consents",
        "statuses": {201},
    },
    "start_session": {
        "method": "POST",
        "path": "/api/v1/audio-gateway/sessions",
        "statuses": {200, 201},
    },
    "upload_mic_chunk": {
        "method": "POST",
        "source": "microphone",
        "statuses": {200},
    },
    "upload_loopback_chunk": {
        "method": "POST",
        "source": "loopback",
        "statuses": {200},
    },
    "finish_session": {
        "method": "POST",
        "statuses": {200},
    },
    "session_status": {
        "method": "GET",
        "statuses": {200},
    },
}

BOUNDARY_EXPECTATIONS = {
    "desktopMicLoopbackProven": True,
    "gatewayOnly": True,
    "rawAudioIncluded": False,
    "rawTranscriptIncluded": False,
    "directClientToStt": False,
    "directSttTranscriptProven": False,
    "computePlaneAuditProven": False,
    "productionReady": False,
}

SENSITIVE_KEY_NAMES = {
    "access_token",
    "api_key",
    "audio",
    "audio_base64",
    "audio_bytes",
    "audiobase64",
    "audiobytes",
    "authorization",
    "bearer",
    "callback_endpoint",
    "callback_url",
    "client_secret",
    "cookie",
    "destination_endpoint",
    "destination_url",
    "endpoint_url",
    "idempotency_key",
    "internal_url",
    "jwt",
    "password",
    "private_key",
    "raw_audio",
    "raw_audio_bytes",
    "raw_command_output",
    "raw_output",
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

SENSITIVE_KEY_NAME_COMPACT = {name.replace("_", "") for name in SENSITIVE_KEY_NAMES}

SECRET_VALUE_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bAuthorization\s*:", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"data:audio/[A-Za-z0-9.+-]+;base64,", re.IGNORECASE),
]

UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
SHA256_TAG_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_STRING_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,180}$")
SESSION_ID_RE = re.compile(r"^SES-[A-Za-z0-9_-]{4,120}$")
CAMEL_BOUNDARY_1_RE = re.compile(r"(.)([A-Z][a-z]+)")
CAMEL_BOUNDARY_2_RE = re.compile(r"([a-z0-9])([A-Z])")


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


def safe_string(value: Any) -> bool:
    return isinstance(value, str) and bool(SAFE_STRING_RE.match(value))


def sha256(value: Any, *, tagged: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    return bool((SHA256_TAG_RE if tagged else SHA256_HEX_RE).match(value))


def validate_no_sensitive_content(data: dict[str, Any], checks: list[Check]) -> None:
    findings: list[str] = []
    for path, key, value in iter_values(data):
        if key is not None:
            normalized = normalized_key(key)
            if normalized in SENSITIVE_KEY_NAMES or normalized.replace("_", "") in SENSITIVE_KEY_NAME_COMPACT:
                findings.append(f"{path}: forbidden key '{key}'")
                continue
        if isinstance(value, str):
            for pattern in SECRET_VALUE_PATTERNS:
                if pattern.search(value):
                    findings.append(f"{path}: secret-like or raw audio value")
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
    add(
        checks,
        "generated_at",
        isinstance(data.get("generatedAt"), str) and bool(UTC_TIMESTAMP_RE.match(data["generatedAt"])),
        "generatedAt must use UTC YYYY-MM-DDTHH:MM:SSZ",
    )
    add(checks, "token_not_included", data.get("tokenIncluded") is False, "tokenIncluded must be false")
    failures = data.get("failures")
    add(checks, "failures_empty", failures in (None, []), "failures must be absent or empty")


def validate_client(data: dict[str, Any], checks: list[Check]) -> None:
    client = data.get("client")
    if not isinstance(client, dict):
        add(checks, "client_shape", False, "client must be an object")
        return
    add(checks, "client_kind", client.get("kind") == EXPECTED_CLIENT_KIND, f"client.kind must be {EXPECTED_CLIENT_KIND}")
    add(checks, "client_os", client.get("os") in {"windows", "macos", "linux"}, "client.os must be windows, macos, or linux")
    commit = client.get("buildCommit")
    add(checks, "client_build_commit", commit == "unknown" or bool(GIT_SHA_RE.match(str(commit))), "client.buildCommit must be 40 lowercase hex chars or unknown")
    add(checks, "client_capture_mode", client.get("captureMode") == "real-device", "captureMode must be real-device")
    add(checks, "client_active_indicator", client.get("activeIndicatorVisible") is True, "active capture indicator must be visible")


def validate_session(data: dict[str, Any], checks: list[Check]) -> tuple[str, str, str, str]:
    session = data.get("session")
    if not isinstance(session, dict):
        add(checks, "session_shape", False, "session must be an object")
        return "", "", "", ""
    meeting_id = str(session.get("meetingId") or "")
    capture_id = str(session.get("captureId") or "")
    session_id = str(session.get("sessionId") or "")
    correlation_id = str(session.get("correlationId") or "")
    add(checks, "meeting_id_uuid", bool(UUID_RE.match(meeting_id)), "session.meetingId must be UUID-shaped")
    add(checks, "capture_id_uuid", bool(UUID_RE.match(capture_id)), "session.captureId must be UUID-shaped")
    add(
        checks,
        "session_id_shape",
        bool(SESSION_ID_RE.match(session_id)),
        "session.sessionId must start with SES- and contain only safe chars",
    )
    add(checks, "correlation_id_safe", safe_string(correlation_id), "session.correlationId must be bounded safe metadata")
    return meeting_id, capture_id, session_id, correlation_id


def validate_consent(data: dict[str, Any], checks: list[Check]) -> None:
    consent = data.get("consent")
    if not isinstance(consent, dict):
        add(checks, "consent_shape", False, "consent must be an object")
        return
    add(checks, "consent_captured", consent.get("recordingConsentCaptured") is True, "recording consent must be captured")
    add(checks, "consent_hash", sha256(consent.get("consentTextHash"), tagged=True), "consentTextHash must be sha256:<64 hex>")
    add(checks, "consent_text_absent", consent.get("consentTextIncluded") is False, "consent text must not be included")


def validate_source(
    name: str,
    source: Any,
    checks: list[Check],
) -> str:
    if not isinstance(source, dict):
        add(checks, f"{name}_source_shape", False, f"sources.{name} must be an object")
        return ""
    add(checks, f"{name}_proven", source.get("proven") is True, f"{name} must be proven")
    add(checks, f"{name}_kind", source.get("sourceKind") == name, f"{name}.sourceKind must be {name}")
    add(checks, f"{name}_real_device", source.get("synthetic") is False, f"{name} source must not be synthetic")
    add(checks, f"{name}_device_hash", sha256(source.get("deviceLabelHash"), tagged=True), f"{name}.deviceLabelHash must be sha256:<64 hex>")
    duration_ms = as_int(source.get("durationMs"))
    sample_rate = as_int(source.get("sampleRateHz"))
    channels = as_int(source.get("channels"))
    byte_length = as_int(source.get("byteLength"))
    add(checks, f"{name}_duration", duration_ms is not None and duration_ms >= 1000, f"{name}.durationMs must be >= 1000")
    add(checks, f"{name}_sample_rate", sample_rate in {8000, 16000, 24000, 32000, 44100, 48000}, f"{name}.sampleRateHz must be a supported audio rate")
    add(checks, f"{name}_channels", channels in {1, 2}, f"{name}.channels must be 1 or 2")
    add(checks, f"{name}_byte_length", byte_length is not None and 0 < byte_length <= 20_000_000, f"{name}.byteLength must be bounded")
    digest = str(source.get("sha256") or "")
    add(checks, f"{name}_sha256", sha256(digest), f"{name}.sha256 must be 64 lowercase hex chars")
    add(checks, f"{name}_raw_absent", source.get("rawAudioIncluded") is False, f"{name} raw audio must be absent")
    return digest


def validate_sources(data: dict[str, Any], checks: list[Check]) -> dict[str, str]:
    sources = data.get("sources")
    if not isinstance(sources, dict):
        add(checks, "sources_shape", False, "sources must be an object")
        return {}
    digests: dict[str, str] = {}
    for name in EXPECTED_SOURCES:
        digests[name] = validate_source(name, sources.get(name), checks)
    return digests


def validate_steps(
    data: dict[str, Any],
    *,
    session_id: str,
    source_digests: dict[str, str],
    checks: list[Check],
) -> None:
    steps = data.get("steps")
    if not isinstance(steps, list):
        add(checks, "steps_shape", False, "steps must be a list")
        return
    actual = [step.get("name") if isinstance(step, dict) else None for step in steps]
    add(checks, "steps_exact_order", actual == EXPECTED_STEPS, "steps must appear in exact expected order")
    by_name = {step.get("name"): step for step in steps if isinstance(step, dict)}
    for name in EXPECTED_STEPS:
        step = by_name.get(name)
        if not isinstance(step, dict):
            add(checks, f"{name}_step", False, f"{name} step is missing")
            continue
        add(checks, f"{name}_ok", step.get("ok") is True, f"{name}.ok must be true")

    for name, expectation in HTTP_STEP_EXPECTATIONS.items():
        step = by_name.get(name)
        if not isinstance(step, dict):
            continue
        add(checks, f"{name}_method", step.get("method") == expectation["method"], f"{name}.method must be {expectation['method']}")
        add(
            checks,
            f"{name}_status",
            as_int(step.get("statusCode")) in expectation["statuses"],
            f"{name}.statusCode must be one of {sorted(expectation['statuses'])}",
        )
        if name in {"upload_mic_chunk", "upload_loopback_chunk"}:
            expected_source = str(expectation["source"])
            expected_path = f"/api/v1/audio-gateway/sessions/{session_id}/chunks"
            add(checks, f"{name}_path", step.get("path") == expected_path, f"{name}.path must be session chunk route")
            add(checks, f"{name}_source", step.get("source") == expected_source, f"{name}.source must be {expected_source}")
            add(checks, f"{name}_sha256_match", step.get("sha256") == source_digests.get(expected_source), f"{name}.sha256 must match source digest")
        elif name in {"finish_session", "session_status"}:
            suffix = "finish" if name == "finish_session" else "status"
            expected_path = f"/api/v1/audio-gateway/sessions/{session_id}/{suffix}"
            add(checks, f"{name}_path", step.get("path") == expected_path, f"{name}.path must be session {suffix} route")
        else:
            add(checks, f"{name}_path", step.get("path") == expectation["path"], f"{name}.path must be {expectation['path']}")


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
    validate_client(data, checks)
    _meeting_id, _capture_id, session_id, _correlation_id = validate_session(data, checks)
    validate_consent(data, checks)
    source_digests = validate_sources(data, checks)
    validate_steps(data, session_id=session_id, source_digests=source_digests, checks=checks)
    validate_boundaries(data, checks)
    return checks


def build_summary(checks: list[Check], data: dict[str, Any] | None = None) -> dict[str, Any]:
    passed = all(check.passed for check in checks)
    failures = [check.message for check in checks if not check.passed]
    summary: dict[str, Any] = {
        "schemaVersion": VERIFIER_SCHEMA_VERSION,
        "evidenceSchemaVersion": EVIDENCE_SCHEMA_VERSION,
        "checkedAt": utc_now(),
        "status": "pass" if passed else "fail",
        "tokenIncluded": False,
        "passed": sum(1 for check in checks if check.passed),
        "total": len(checks),
        "checks": [asdict(check) for check in checks],
        "failures": failures,
    }
    if data is not None:
        session = data.get("session")
        if isinstance(session, dict):
            summary["ids"] = {
                "meetingId": session.get("meetingId"),
                "captureId": session.get("captureId"),
                "sessionId": session.get("sessionId"),
            }
        boundaries = data.get("boundaries")
        if isinstance(boundaries, dict):
            summary["boundaries"] = {
                key: boundaries.get(key)
                for key in BOUNDARY_EXPECTATIONS
            }
    return summary


def write_summary(path: Path, checks: list[Check], data: dict[str, Any] | None = None) -> None:
    summary = build_summary(checks, data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_human(checks: list[Check]) -> None:
    for check in checks:
        symbol = "OK" if check.passed else "FAIL"
        print(f"{symbol} {check.name}: {check.message}")
    passed = sum(1 for check in checks if check.passed)
    print(f"\nFaz 24 desktop capture evidence: {'PASS' if passed == len(checks) else 'FAIL'} ({passed}/{len(checks)})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", nargs="?", type=Path, help="Evidence JSON path. Reads stdin when omitted.")
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
        write_summary(args.summary_json, checks, data)
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
