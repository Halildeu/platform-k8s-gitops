#!/usr/bin/env python3
"""Verify Faz 24 #188 compute-plane audit smoke evidence.

This verifier accepts a bounded JSON envelope built from the Redis
`audit:events` stream after a direct-STT smoke. It proves only that the
metadata-only `CHUNK_FORWARDED_TO_COMPUTE_PLANE` audit event was present for
the expected session/chunk/correlation. It does not prove transcript quality,
desktop capture, or production readiness.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


EVIDENCE_SCHEMA_VERSION = "faz24.computePlaneAuditEvidence.v1"
VERIFIER_SCHEMA_VERSION = "faz24.computePlaneAuditVerifier.v1"
EVENT_TYPE = "CHUNK_FORWARDED_TO_COMPUTE_PLANE"

BOUNDARY_EXPECTATIONS = {
    "chunkForwardedToComputePlaneProven": True,
    "rawAudioIncluded": False,
    "rawTranscriptIncluded": False,
    "destinationUrlIncluded": False,
    "directSttTranscriptProven": False,
    "desktopMicLoopbackProven": False,
    "productionReady": False,
}

SENSITIVE_KEY_NAMES = {
    "access_token",
    "refresh_token",
    "token",
    "authorization",
    "bearer",
    "jwt",
    "credential",
    "session_token",
    "auth_token",
    "api_key",
    "private_key",
    "cookie",
    "client_secret",
    "password",
    "secret",
    "idempotency_key",
    "idempotency-key",
    "audio",
    "audio_bytes",
    "audiobytes",
    "raw_audio",
    "rawaudio",
    "transcript",
    "transcript_text",
    "transcripttext",
    "segments",
    "text",
    "transcribe_url",
    "transcribeurl",
    "destination_url",
    "destinationurl",
    "url",
}

SECRET_VALUE_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bAuthorization\s*:", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,180}$")
REDIS_ID_RE = re.compile(r"^\d+-\d+$")


@dataclass
class Check:
    name: str
    passed: bool
    message: str


def _utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _iter_values(value: Any, path: str = "$") -> Iterable[tuple[str, str | None, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, str(key), child
            yield from _iter_values(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield child_path, None, child
            yield from _iter_values(child, child_path)


def _normalized_key(key: str) -> str:
    return key.replace("-", "_").replace(".", "_").strip().lower()


def _add(checks: list[Check], name: str, passed: bool, message: str) -> None:
    checks.append(Check(name=name, passed=passed, message=message))


def _load_evidence(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
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


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _validate_no_sensitive_content(data: dict[str, Any], checks: list[Check]) -> None:
    findings: list[str] = []
    for path, key, value in _iter_values(data):
        if key is not None and _normalized_key(key) in SENSITIVE_KEY_NAMES:
            findings.append(f"{path}: forbidden key '{key}'")
            continue
        if isinstance(value, str):
            for pattern in SECRET_VALUE_PATTERNS:
                if pattern.search(value):
                    findings.append(f"{path}: secret-like value")
                    break

    _add(
        checks,
        "no_sensitive_content",
        not findings,
        "no sensitive keys or token-shaped values found"
        if not findings
        else "; ".join(findings[:6]),
    )


def _validate_top_level(data: dict[str, Any], checks: list[Check]) -> None:
    _add(
        checks,
        "schema_version",
        data.get("schemaVersion") == EVIDENCE_SCHEMA_VERSION,
        f"schemaVersion must be {EVIDENCE_SCHEMA_VERSION}",
    )
    _add(checks, "status_pass", data.get("status") == "pass", "status must be pass")
    _add(
        checks,
        "token_not_included",
        data.get("tokenIncluded") is False,
        "top-level tokenIncluded must be false",
    )
    failures = data.get("failures")
    _add(checks, "failures_empty", failures in (None, []), "failures must be absent or empty")


def _validate_source(data: dict[str, Any], checks: list[Check]) -> None:
    source = data.get("source")
    if not isinstance(source, dict):
        _add(checks, "source_shape", False, "source must be an object")
        return
    _add(
        checks,
        "source_stream_key",
        source.get("streamKey") == "audit:events",
        "source.streamKey must be audit:events",
    )
    record_id = source.get("redisStreamRecordId")
    _add(
        checks,
        "source_record_id",
        isinstance(record_id, str) and bool(REDIS_ID_RE.match(record_id)),
        "source.redisStreamRecordId must be Redis stream id shaped",
    )


def _validate_boundaries(data: dict[str, Any], checks: list[Check]) -> None:
    boundaries = data.get("boundaries")
    if not isinstance(boundaries, dict):
        _add(checks, "boundaries_shape", False, "boundaries must be an object")
        return

    for key, expected in BOUNDARY_EXPECTATIONS.items():
        _add(
            checks,
            f"boundary_{key}",
            boundaries.get(key) is expected,
            f"boundaries.{key} must be {str(expected).lower()}",
        )


def _validate_expected(data: dict[str, Any], checks: list[Check]) -> dict[str, Any]:
    expected = data.get("expected")
    if not isinstance(expected, dict):
        _add(checks, "expected_shape", False, "expected must be an object")
        return {}
    required = ["sessionId", "meetingId", "chunkSeq", "correlationId", "sha256", "byteLength", "computePlane"]
    missing = [field for field in required if expected.get(field) in (None, "")]
    _add(
        checks,
        "expected_required",
        not missing,
        "expected must include sessionId, meetingId, chunkSeq, correlationId, sha256, byteLength, computePlane",
    )
    return expected


def _validate_event_shape(event: dict[str, Any], checks: list[Check]) -> None:
    _add(checks, "event_type", event.get("eventType") == EVENT_TYPE, f"event.eventType must be {EVENT_TYPE}")

    session_id = str(event.get("sessionId") or "")
    _add(
        checks,
        "event_session_id",
        session_id.startswith("SES-") and len(session_id) > 4 and "\n" not in session_id,
        "event.sessionId must be non-empty and start with SES-",
    )
    _add(
        checks,
        "event_meeting_id",
        isinstance(event.get("meetingId"), str) and bool(UUID_RE.match(event["meetingId"])),
        "event.meetingId must be UUID-shaped",
    )
    for field in ["tenantId", "userId", "chunkSeq", "sampleRateHz", "channels", "byteLength", "forwardedAtMs"]:
        value = _as_int(event.get(field))
        if field in {"tenantId", "userId", "sampleRateHz", "byteLength", "forwardedAtMs"}:
            passed = value is not None and value > 0
        elif field == "channels":
            passed = value is not None and 1 <= value <= 16
        else:
            passed = value is not None and value >= 0
        _add(checks, f"event_{field}", passed, f"event.{field} must be a bounded integer")

    for field in ["deviceId", "language", "audioFormat", "correlationId"]:
        value = event.get(field)
        _add(
            checks,
            f"event_{field}",
            isinstance(value, str) and bool(SAFE_VALUE_RE.match(value)),
            f"event.{field} must be a bounded safe string",
        )

    _add(
        checks,
        "event_sha256",
        isinstance(event.get("sha256"), str) and bool(SHA256_RE.match(event["sha256"])),
        "event.sha256 must be 64 lowercase hex chars",
    )
    _add(
        checks,
        "event_compute_plane",
        event.get("computePlane") == "live-stt",
        "event.computePlane must be live-stt",
    )


def _validate_event_expected_match(event: dict[str, Any], expected: dict[str, Any], checks: list[Check]) -> None:
    for field in ["sessionId", "meetingId", "chunkSeq", "correlationId", "sha256", "byteLength", "computePlane"]:
        if field not in expected:
            continue
        _add(
            checks,
            f"match_{field}",
            str(event.get(field)) == str(expected.get(field)),
            f"event.{field} must match expected.{field}",
        )


def _validate_event(data: dict[str, Any], expected: dict[str, Any], checks: list[Check]) -> None:
    event = data.get("event")
    if not isinstance(event, dict):
        _add(checks, "event_shape", False, "event must be an object")
        return
    _validate_event_shape(event, checks)
    _validate_event_expected_match(event, expected, checks)


def validate_evidence(data: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    _validate_no_sensitive_content(data, checks)
    _validate_top_level(data, checks)
    _validate_source(data, checks)
    _validate_boundaries(data, checks)
    expected = _validate_expected(data, checks)
    _validate_event(data, expected, checks)
    return checks


def _summary(data: dict[str, Any] | None, checks: list[Check], status: str) -> dict[str, Any]:
    failures = [check.message for check in checks if not check.passed]
    summary: dict[str, Any] = {
        "schemaVersion": VERIFIER_SCHEMA_VERSION,
        "status": status,
        "tokenIncluded": False,
        "checkedAt": _utc_now(),
        "evidenceSchemaVersion": data.get("schemaVersion") if data else None,
        "checks": [check.__dict__ for check in checks],
        "failures": failures,
    }
    if data:
        event = data.get("event") if isinstance(data.get("event"), dict) else {}
        summary["event"] = {
            "eventType": event.get("eventType"),
            "sessionId": event.get("sessionId"),
            "meetingId": event.get("meetingId"),
            "chunkSeq": event.get("chunkSeq"),
            "correlationId": event.get("correlationId"),
            "computePlane": event.get("computePlane"),
        }
    return summary


def _write_output_file(path: Path, rendered: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    finally:
        try:
            os.chmod(path, 0o600)
        except FileNotFoundError:
            pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-file",
        type=Path,
        help="Path to faz24.computePlaneAuditEvidence.v1 JSON. If omitted, stdin is used.",
    )
    parser.add_argument("--output-file", type=Path, help="Optional verifier JSON output path.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    data, error = _load_evidence(args.evidence_file)
    if error:
        checks = [Check("json_load", False, error)]
        report = _summary(None, checks, "error")
        exit_code = 2
    else:
        assert data is not None
        checks = validate_evidence(data)
        status = "pass" if all(check.passed for check in checks) else "fail"
        report = _summary(data, checks, status)
        exit_code = 0 if status == "pass" else 1

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output_file:
        _write_output_file(args.output_file, rendered)
    print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
