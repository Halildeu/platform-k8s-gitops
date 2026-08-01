#!/usr/bin/env python3
"""Verify Faz 24 external recorder smoke evidence before issue attachment.

This verifier validates the redacted JSON envelope emitted by
run_external_recorder_smoke.py. It is intentionally stricter than a generic
JSON schema: it rejects secret-like content, false-positive direct-STT or
production claims, missing lifecycle steps, and status mismatches.
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


EVIDENCE_SCHEMA_VERSION = "faz24.externalRecorderSmoke.v1"
VERIFIER_SCHEMA_VERSION = "faz24.externalRecorderSmokeVerifier.v1"

EXPECTED_STEPS = [
    "token_contract",
    "create_meeting",
    "record_consent",
    "start_session",
    "sync_recording_lifecycle_start",
    "upload_chunk",
    "finish_session",
    "sync_recording_lifecycle_finish",
    "session_status",
]

HTTP_STEP_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "create_meeting": {
        "method": "POST",
        "path": "/api/v1/admin/meetings",
        "statuses": {201},
    },
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
    "sync_recording_lifecycle_start": {
        "method": "PUT",
        "statuses": {200},
    },
    "upload_chunk": {
        "method": "POST",
        "statuses": {200},
    },
    "finish_session": {
        "method": "POST",
        "statuses": {200},
    },
    "sync_recording_lifecycle_finish": {
        "method": "PUT",
        "statuses": {200},
    },
    "session_status": {
        "method": "GET",
        "statuses": {200},
    },
}

BOUNDARY_EXPECTATIONS = {
    "externalMeetingAdminPathExercised": True,
    "recorderLifecycleExercised": True,
    "canonicalRecordingLifecycleSynced": True,
    "directSttProven": False,
    "directSttTranscriptProven": False,
    "directClientToStt": False,
    "computePlaneAuditProven": False,
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
    "callback_endpoint",
    "callback_url",
    "destination_endpoint",
    "destination_url",
    "endpoint_url",
    "internal_url",
    "stt_endpoint",
    "stt_url",
    "transcribe_endpoint",
    "transcribe_url",
    "webhook_url",
    "whisper_url",
    "audio_base64",
    "audio_bytes",
    "audio_preview",
    "raw_audio",
    "raw_audio_bytes",
    "transcript",
    "transcript_text",
    "segments",
    "raw_request",
    "raw_response",
    "packet_capture",
    "pcap",
    "body",
    "payload",
}
SENSITIVE_KEY_NAME_COMPACT = {name.replace("_", "") for name in SENSITIVE_KEY_NAMES}
URL_VALUE_ALLOWED_KEYS = {"issuer"}

SECRET_VALUE_PATTERNS = [
    ("secret", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)),
    ("secret", re.compile(r"\bAuthorization\s*:", re.IGNORECASE)),
    ("secret", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("secret", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("url", re.compile(r"\b(?:https?|wss?)://[^\s\"']+", re.IGNORECASE)),
    ("raw_audio", re.compile(r"data:audio/[A-Za-z0-9.+-]+;base64,", re.IGNORECASE)),
]

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
SESSION_ID_RE = re.compile(r"^SES-[A-Za-z0-9_-]{4,120}$")
CAMEL_BOUNDARY_1_RE = re.compile(r"(.)([A-Z][a-z]+)")
CAMEL_BOUNDARY_2_RE = re.compile(r"([a-z0-9])([A-Z])")


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
    key = key.replace("-", "_").replace(".", "_").strip()
    key = CAMEL_BOUNDARY_1_RE.sub(r"\1_\2", key)
    key = CAMEL_BOUNDARY_2_RE.sub(r"\1_\2", key)
    return re.sub(r"_+", "_", key).lower()


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


def _add(checks: list[Check], name: str, passed: bool, message: str) -> None:
    checks.append(Check(name=name, passed=passed, message=message))


def _step_by_name(steps: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(steps, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for step in steps:
        if isinstance(step, dict) and isinstance(step.get("name"), str):
            result[step["name"]] = step
    return result


def _validate_no_sensitive_content(data: dict[str, Any], checks: list[Check]) -> None:
    findings: list[str] = []
    for path, key, value in _iter_values(data):
        if key is not None:
            normalized = _normalized_key(key)
            if normalized in SENSITIVE_KEY_NAMES or normalized.replace("_", "") in SENSITIVE_KEY_NAME_COMPACT:
                findings.append(f"{path}: forbidden key '{key}'")
                continue
        if isinstance(value, str):
            normalized = _normalized_key(key) if key is not None else ""
            for pattern_kind, pattern in SECRET_VALUE_PATTERNS:
                if pattern_kind == "url" and normalized in URL_VALUE_ALLOWED_KEYS:
                    continue
                if pattern.search(value):
                    findings.append(f"{path}: secret-like, URL-like, or raw audio value")
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
    failures_ok = failures in (None, [])
    _add(
        checks,
        "failures_empty",
        failures_ok,
        "failures must be absent or empty",
    )


def _validate_ids(data: dict[str, Any], checks: list[Check]) -> tuple[str, str, str, str]:
    ids = data.get("ids")
    if not isinstance(ids, dict):
        _add(checks, "ids_shape", False, "ids must be an object")
        return "", "", "", ""

    meeting_id = str(ids.get("meetingId") or "")
    capture_id = str(ids.get("captureId") or "")
    session_id = str(ids.get("sessionId") or "")
    canonical_session_id = str(ids.get("canonicalSessionId") or "")

    _add(checks, "meeting_id_uuid", bool(UUID_RE.match(meeting_id)), "ids.meetingId must be UUID-shaped")
    _add(checks, "capture_id_uuid", bool(UUID_RE.match(capture_id)), "ids.captureId must be UUID-shaped")
    _add(
        checks,
        "session_id_shape",
        bool(SESSION_ID_RE.match(session_id)),
        "ids.sessionId must start with SES- and contain only safe chars",
    )
    _add(
        checks,
        "canonical_session_id_uuid",
        bool(UUID_RE.match(canonical_session_id)),
        "ids.canonicalSessionId must be UUID-shaped",
    )
    return meeting_id, capture_id, session_id, canonical_session_id


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


def _validate_step_order(data: dict[str, Any], checks: list[Check]) -> list[dict[str, Any]]:
    steps = data.get("steps")
    if not isinstance(steps, list):
        _add(checks, "steps_shape", False, "steps must be a list")
        return []
    actual = [step.get("name") if isinstance(step, dict) else None for step in steps]
    _add(
        checks,
        "steps_exact_order",
        actual == EXPECTED_STEPS,
        "steps must appear in exact expected order",
    )
    return [step for step in steps if isinstance(step, dict)]


def _expected_dynamic_path(name: str, meeting_id: str, session_id: str) -> str | None:
    if name in {"sync_recording_lifecycle_start", "sync_recording_lifecycle_finish"}:
        return f"/api/v1/admin/meetings/{meeting_id}/recording-lifecycle"
    if name == "upload_chunk":
        return f"/api/v1/audio-gateway/sessions/{session_id}/chunks"
    if name == "finish_session":
        return f"/api/v1/audio-gateway/sessions/{session_id}/finish"
    if name == "session_status":
        return f"/api/v1/audio-gateway/sessions/{session_id}/status"
    return None


def _validate_token_contract_step(step: dict[str, Any] | None, checks: list[Check]) -> None:
    if step is None:
        _add(checks, "token_contract_step", False, "token_contract step is missing")
        return

    report = step.get("report")
    report_ok = isinstance(report, dict) and report.get("status") == "pass"
    token_flag_ok = not isinstance(report, dict) or report.get("tokenIncluded") is False
    _add(
        checks,
        "token_contract_step",
        step.get("ok") is True and report_ok and token_flag_ok,
        "token_contract step and nested report must pass with tokenIncluded=false",
    )


def _validate_http_steps(
    by_name: dict[str, dict[str, Any]],
    *,
    meeting_id: str,
    capture_id: str,
    session_id: str,
    canonical_session_id: str,
    checks: list[Check],
) -> None:
    for name, expectation in HTTP_STEP_EXPECTATIONS.items():
        step = by_name.get(name)
        if step is None:
            _add(checks, f"{name}_step", False, f"{name} step is missing")
            continue

        expected_path = expectation.get("path") or _expected_dynamic_path(
            name, meeting_id, session_id
        )
        status_code = step.get("statusCode")
        passed = (
            step.get("ok") is True
            and step.get("method") == expectation["method"]
            and step.get("path") == expected_path
            and status_code in expectation["statuses"]
            and step.get("tokenIncluded") is False
            and "errorClass" not in step
        )
        _add(
            checks,
            f"{name}_http_contract",
            passed,
            f"{name} must have ok=true, expected method/path/status, tokenIncluded=false, and no errorClass",
        )

    create_response = by_name.get("create_meeting", {}).get("response")
    _add(
        checks,
        "create_meeting_response_id",
        isinstance(create_response, dict) and create_response.get("id") == meeting_id,
        "create_meeting response.id must match ids.meetingId",
    )

    consent_response = by_name.get("record_consent", {}).get("response")
    consent_ok = (
        isinstance(consent_response, dict)
        and str(consent_response.get("meetingId")) == meeting_id
        and str(consent_response.get("captureId")) == capture_id
    )
    _add(
        checks,
        "record_consent_response_ids",
        consent_ok,
        "record_consent response must match meetingId and captureId",
    )

    start_response = by_name.get("start_session", {}).get("response")
    _add(
        checks,
        "start_session_response_id",
        isinstance(start_response, dict) and start_response.get("sessionId") == session_id,
        "start_session response.sessionId must match ids.sessionId",
    )

    lifecycle_start = by_name.get("sync_recording_lifecycle_start", {}).get("response")
    lifecycle_start_ok = (
        isinstance(lifecycle_start, dict)
        and str(lifecycle_start.get("meetingId")) == meeting_id
        and str(lifecycle_start.get("externalSessionId")) == session_id
        and str(lifecycle_start.get("sessionId")) == canonical_session_id
        and lifecycle_start.get("meetingStatus") == "IN_PROGRESS"
        and lifecycle_start.get("transcriptStatus") == "PENDING"
    )
    _add(
        checks,
        "recording_lifecycle_start_projection",
        lifecycle_start_ok,
        "recording lifecycle start must match meeting, external/canonical session, IN_PROGRESS, and PENDING",
    )

    finish_response = by_name.get("finish_session", {}).get("response")
    final_state = finish_response.get("finalState") if isinstance(finish_response, dict) else None
    _add(
        checks,
        "finish_session_final_state",
        final_state == "FINISHED",
        "finish_session response.finalState must be FINISHED",
    )

    lifecycle_finish = by_name.get("sync_recording_lifecycle_finish", {}).get("response")
    lifecycle_finish_ok = (
        isinstance(lifecycle_finish, dict)
        and str(lifecycle_finish.get("meetingId")) == meeting_id
        and str(lifecycle_finish.get("externalSessionId")) == session_id
        and str(lifecycle_finish.get("sessionId")) == canonical_session_id
        and lifecycle_finish.get("meetingStatus") == "COMPLETED"
        and lifecycle_finish.get("transcriptStatus") in {"PROCESSING", "COMPLETED"}
    )
    _add(
        checks,
        "recording_lifecycle_finish_projection",
        lifecycle_finish_ok,
        "recording lifecycle finish must match meeting, external/canonical session, COMPLETED, and PROCESSING/COMPLETED",
    )

    status_response = by_name.get("session_status", {}).get("response")
    status_ok = isinstance(status_response, dict) and status_response.get("state") == "FINISHED"
    _add(
        checks,
        "session_status_finished",
        status_ok,
        "session_status response.state must be FINISHED",
    )


def validate_evidence(data: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    _validate_no_sensitive_content(data, checks)
    _validate_top_level(data, checks)
    meeting_id, capture_id, session_id, canonical_session_id = _validate_ids(data, checks)
    _validate_boundaries(data, checks)
    steps = _validate_step_order(data, checks)
    by_name = _step_by_name(steps)
    _validate_token_contract_step(by_name.get("token_contract"), checks)
    _validate_http_steps(
        by_name,
        meeting_id=meeting_id,
        capture_id=capture_id,
        session_id=session_id,
        canonical_session_id=canonical_session_id,
        checks=checks,
    )
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
        ids = data.get("ids") if isinstance(data.get("ids"), dict) else {}
        summary["ids"] = {
            "meetingId": ids.get("meetingId"),
            "captureId": ids.get("captureId"),
            "sessionId": ids.get("sessionId"),
            "canonicalSessionId": ids.get("canonicalSessionId"),
        }
        boundaries = data.get("boundaries") if isinstance(data.get("boundaries"), dict) else {}
        summary["boundaries"] = {
            key: boundaries.get(key)
            for key in BOUNDARY_EXPECTATIONS
            if key in boundaries
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
        help="Path to faz24.externalRecorderSmoke.v1 JSON. If omitted, stdin is used.",
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
