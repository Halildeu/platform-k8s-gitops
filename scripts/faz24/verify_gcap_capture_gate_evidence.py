#!/usr/bin/env python3
"""Verify Faz 24 G-CAP aggregate capture gate evidence.

This verifier consumes redacted verifier outputs and evaluates capture
reliability as an aggregate product gate: attempt count, distinct
meeting/session coverage, success rate, retry rate, and failure rate. It accepts
only verifier summaries, currently `faz24.externalRecorderSmokeVerifier.v1` and
`faz24.desktopCaptureEvidenceVerifier.v1`. It never accepts raw audio,
transcript text, JWTs, raw runner output, or raw desktop capture envelopes as
aggregate gate evidence.
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


EXTERNAL_INPUT_SCHEMA_VERSION = "faz24.externalRecorderSmokeVerifier.v1"
EXTERNAL_INPUT_EVIDENCE_SCHEMA_VERSION = "faz24.externalRecorderSmoke.v1"
DESKTOP_INPUT_SCHEMA_VERSION = "faz24.desktopCaptureEvidenceVerifier.v1"
DESKTOP_INPUT_EVIDENCE_SCHEMA_VERSION = "faz24.desktopCaptureEvidence.v1"
SUPPORTED_INPUT_SCHEMA_VERSIONS = {
    EXTERNAL_INPUT_SCHEMA_VERSION,
    DESKTOP_INPUT_SCHEMA_VERSION,
}
VERIFIER_SCHEMA_VERSION = "faz24.gcapCaptureGateVerifier.v1"

EXTERNAL_BOUNDARY_EXPECTATIONS = {
    "externalMeetingAdminPathExercised": True,
    "recorderLifecycleExercised": True,
    "directSttProven": False,
    "directClientToStt": False,
    "directSttTranscriptProven": False,
    "computePlaneAuditProven": False,
    "desktopMicLoopbackProven": False,
    "productionReady": False,
}

DESKTOP_BOUNDARY_EXPECTATIONS = {
    "desktopMicLoopbackProven": True,
    "gatewayOnly": True,
    "rawAudioIncluded": False,
    "rawTranscriptIncluded": False,
    "directClientToStt": False,
    "directSttTranscriptProven": False,
    "computePlaneAuditProven": False,
    "productionReady": False,
}

FORBIDDEN_TRUE_BOUNDARIES = {
    "directSttProven",
    "directClientToStt",
    "directSttTranscriptProven",
    "computePlaneAuditProven",
    "productionReady",
}

EXTERNAL_REQUIRED_SUCCESS_CHECKS = {
    "no_sensitive_content",
    "schema_version",
    "status_pass",
    "token_not_included",
    "failures_empty",
    "meeting_id_uuid",
    "capture_id_uuid",
    "session_id_shape",
    "boundary_externalMeetingAdminPathExercised",
    "boundary_recorderLifecycleExercised",
    "boundary_directSttProven",
    "boundary_directClientToStt",
    "boundary_directSttTranscriptProven",
    "boundary_computePlaneAuditProven",
    "boundary_desktopMicLoopbackProven",
    "boundary_productionReady",
    "steps_exact_order",
    "token_contract_step",
    "create_meeting_http_contract",
    "record_consent_http_contract",
    "start_session_http_contract",
    "upload_chunk_http_contract",
    "finish_session_http_contract",
    "session_status_http_contract",
    "create_meeting_response_id",
    "record_consent_response_ids",
    "start_session_response_id",
    "finish_session_final_state",
    "session_status_finished",
}

DESKTOP_REQUIRED_SUCCESS_CHECKS = {
    "no_sensitive_content",
    "schema_version",
    "status_pass",
    "generated_at",
    "token_not_included",
    "failures_empty",
    "client_kind",
    "client_os",
    "client_build_commit",
    "client_capture_mode",
    "client_active_indicator",
    "meeting_id_uuid",
    "capture_id_uuid",
    "session_id_shape",
    "correlation_id_safe",
    "consent_captured",
    "consent_hash",
    "consent_text_absent",
    "microphone_proven",
    "microphone_kind",
    "microphone_real_device",
    "microphone_device_hash",
    "microphone_duration",
    "microphone_sample_rate",
    "microphone_channels",
    "microphone_byte_length",
    "microphone_sha256",
    "microphone_raw_absent",
    "loopback_proven",
    "loopback_kind",
    "loopback_real_device",
    "loopback_device_hash",
    "loopback_duration",
    "loopback_sample_rate",
    "loopback_channels",
    "loopback_byte_length",
    "loopback_sha256",
    "loopback_raw_absent",
    "steps_exact_order",
    "desktop_app_started_ok",
    "permission_check_ok",
    "mic_capture_ok",
    "loopback_capture_ok",
    "record_consent_ok",
    "record_consent_method",
    "record_consent_status",
    "record_consent_path",
    "start_session_ok",
    "start_session_method",
    "start_session_status",
    "start_session_path",
    "upload_mic_chunk_ok",
    "upload_mic_chunk_method",
    "upload_mic_chunk_status",
    "upload_mic_chunk_path",
    "upload_mic_chunk_source",
    "upload_mic_chunk_sha256_match",
    "upload_loopback_chunk_ok",
    "upload_loopback_chunk_method",
    "upload_loopback_chunk_status",
    "upload_loopback_chunk_path",
    "upload_loopback_chunk_source",
    "upload_loopback_chunk_sha256_match",
    "finish_session_ok",
    "finish_session_method",
    "finish_session_status",
    "finish_session_path",
    "session_status_ok",
    "session_status_method",
    "session_status_status",
    "session_status_path",
    "boundary_desktopMicLoopbackProven",
    "boundary_gatewayOnly",
    "boundary_rawAudioIncluded",
    "boundary_rawTranscriptIncluded",
    "boundary_directClientToStt",
    "boundary_directSttTranscriptProven",
    "boundary_computePlaneAuditProven",
    "boundary_productionReady",
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
    "audio",
    "audio_base64",
    "audio_bytes",
    "audiobase64",
    "audiobytes",
    "callback_endpoint",
    "callback_url",
    "raw_audio",
    "raw_audio_bytes",
    "rawaudio",
    "destination_endpoint",
    "destination_url",
    "endpoint_url",
    "internal_url",
    "transcript",
    "transcript_text",
    "transcripttext",
    "transcribe_endpoint",
    "transcribe_url",
    "url",
    "webhook_url",
    "whisper_url",
    "segments",
    "prompt",
    "response",
    "raw_request",
    "raw_response",
    "body",
    "payload",
}

SECRET_VALUE_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bAuthorization\s*:", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"data:audio/[A-Za-z0-9.+-]+;base64,", re.IGNORECASE),
]

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
SESSION_ID_RE = re.compile(r"^SES-[A-Za-z0-9_-]{4,120}$")
CAMEL_BOUNDARY_1_RE = re.compile(r"(.)([A-Z][a-z]+)")
CAMEL_BOUNDARY_2_RE = re.compile(r"([a-z0-9])([A-Z])")
SENSITIVE_KEY_NAME_COMPACT = {name.replace("_", "") for name in SENSITIVE_KEY_NAMES}


@dataclass
class Check:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class Thresholds:
    min_attempts: int
    min_distinct_meetings: int
    min_distinct_sessions: int
    min_success_rate: float
    max_retry_rate: float
    max_failure_rate: float


@dataclass
class Attempt:
    index: int
    evidence_class: str
    valid: bool
    success: bool
    retry: bool
    meeting_id: str | None
    session_id: str | None


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


def _add(checks: list[Check], name: str, passed: bool, message: str) -> None:
    checks.append(Check(name=name, passed=passed, message=message))


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _parse_json_or_jsonl(raw: str, source: str) -> tuple[Any | None, str | None]:
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as json_error:
        rows: list[Any] = []
        for line_number, line in enumerate(raw.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError:
                return None, f"{source}: invalid JSON or JSONL at line {line_number}: {json_error}"
        if rows:
            return rows, None
        return None, f"{source}: invalid JSON: {json_error}"


def _flatten_payload(payload: Any, source: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    if isinstance(payload, dict):
        if payload.get("schemaVersion") in SUPPORTED_INPUT_SCHEMA_VERSIONS:
            return [payload], None
        for key in ("reports", "runs", "evidence"):
            value = payload.get(key)
            if isinstance(value, list):
                if all(isinstance(item, dict) for item in value):
                    return list(value), None
                return None, f"{source}: {key} must contain JSON objects"
        return None, (
            f"{source}: expected one of {sorted(SUPPORTED_INPUT_SCHEMA_VERSIONS)} object, JSON array, "
            "or wrapper object with reports/runs/evidence"
        )
    if isinstance(payload, list):
        if all(isinstance(item, dict) for item in payload):
            return list(payload), None
        return None, f"{source}: top-level array must contain JSON objects"
    return None, f"{source}: top-level evidence must be an object, array, or JSONL object stream"


def _load_reports(paths: list[Path]) -> tuple[list[dict[str, Any]], list[str], int]:
    sources: list[tuple[str, str]] = []
    if paths:
        for path in paths:
            try:
                sources.append((str(path), path.read_text(encoding="utf-8")))
            except OSError as exc:
                return [], [f"{path}: cannot read evidence: {exc}"], len(paths)
    else:
        sources.append(("<stdin>", sys.stdin.read()))

    reports: list[dict[str, Any]] = []
    errors: list[str] = []
    for source, raw in sources:
        payload, parse_error = _parse_json_or_jsonl(raw, source)
        if parse_error:
            errors.append(parse_error)
            continue
        flattened, flatten_error = _flatten_payload(payload, source)
        if flatten_error:
            errors.append(flatten_error)
            continue
        assert flattened is not None
        reports.extend(flattened)
    return reports, errors, len(sources)


def _validate_no_sensitive_content(data: Any, checks: list[Check]) -> bool:
    findings: list[str] = []
    for path, key, value in _iter_values(data):
        if key is not None:
            normalized = _normalized_key(key)
            if normalized in SENSITIVE_KEY_NAMES or normalized.replace("_", "") in SENSITIVE_KEY_NAME_COMPACT:
                findings.append(f"{path}: forbidden key '{key}'")
                continue
        if isinstance(value, str):
            for pattern in SECRET_VALUE_PATTERNS:
                if pattern.search(value):
                    findings.append(f"{path}: secret-like value")
                    break

    passed = not findings
    _add(
        checks,
        "no_sensitive_content",
        passed,
        "no sensitive keys or token-shaped values found"
        if passed
        else "; ".join(findings[:8]),
    )
    return passed


def _check_lookup(report: dict[str, Any]) -> dict[str, bool]:
    checks = report.get("checks")
    if not isinstance(checks, list):
        return {}
    result: dict[str, bool] = {}
    for item in checks:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            result[item["name"]] = item.get("passed") is True
    return result


def _failures_empty(report: dict[str, Any]) -> bool:
    failures = report.get("failures")
    return failures in (None, [])


def _ids(report: dict[str, Any]) -> tuple[str | None, str | None]:
    ids = report.get("ids")
    if not isinstance(ids, dict):
        return None, None
    meeting_id = ids.get("meetingId")
    session_id = ids.get("sessionId")
    return (
        meeting_id if isinstance(meeting_id, str) else None,
        session_id if isinstance(session_id, str) else None,
    )


def _input_schema_version(report: dict[str, Any]) -> str:
    schema = report.get("schemaVersion")
    return schema if isinstance(schema, str) else ""


def _evidence_class(report: dict[str, Any]) -> str:
    schema = _input_schema_version(report)
    if schema == EXTERNAL_INPUT_SCHEMA_VERSION:
        return "external_recorder"
    if schema == DESKTOP_INPUT_SCHEMA_VERSION:
        return "desktop_capture"
    return "unsupported"


def _expected_evidence_schema_version(input_schema: str) -> str | None:
    if input_schema == EXTERNAL_INPUT_SCHEMA_VERSION:
        return EXTERNAL_INPUT_EVIDENCE_SCHEMA_VERSION
    if input_schema == DESKTOP_INPUT_SCHEMA_VERSION:
        return DESKTOP_INPUT_EVIDENCE_SCHEMA_VERSION
    return None


def _required_success_checks(input_schema: str) -> set[str]:
    if input_schema == EXTERNAL_INPUT_SCHEMA_VERSION:
        return EXTERNAL_REQUIRED_SUCCESS_CHECKS
    if input_schema == DESKTOP_INPUT_SCHEMA_VERSION:
        return DESKTOP_REQUIRED_SUCCESS_CHECKS
    return set()


def _boundary_expectations(input_schema: str) -> dict[str, bool]:
    if input_schema == EXTERNAL_INPUT_SCHEMA_VERSION:
        return EXTERNAL_BOUNDARY_EXPECTATIONS
    if input_schema == DESKTOP_INPUT_SCHEMA_VERSION:
        return DESKTOP_BOUNDARY_EXPECTATIONS
    return {}


def _retry_marker(report: dict[str, Any]) -> bool:
    if report.get("retryAttempt") is True:
        return True
    if str(report.get("attemptKind") or "").strip().lower() == "retry":
        return True
    metadata = report.get("metadata")
    if isinstance(metadata, dict):
        return metadata.get("retryAttempt") is True or str(metadata.get("attemptKind") or "").lower() == "retry"
    return False


def _negative_boundary_ok(report: dict[str, Any]) -> bool:
    boundaries = report.get("boundaries")
    if not isinstance(boundaries, dict):
        return True
    forbidden = set(FORBIDDEN_TRUE_BOUNDARIES)
    if _input_schema_version(report) == EXTERNAL_INPUT_SCHEMA_VERSION:
        forbidden.add("desktopMicLoopbackProven")
    return all(boundaries.get(key) is not True for key in forbidden)


def _positive_boundary_success(report: dict[str, Any]) -> bool:
    boundaries = report.get("boundaries")
    if not isinstance(boundaries, dict):
        return False
    expectations = _boundary_expectations(_input_schema_version(report))
    return bool(expectations) and all(boundaries.get(key) is expected for key, expected in expectations.items())


def _validate_report(index: int, report: dict[str, Any], checks: list[Check]) -> Attempt:
    input_schema = _input_schema_version(report)
    evidence_class = _evidence_class(report)
    schema_ok = input_schema in SUPPORTED_INPUT_SCHEMA_VERSIONS
    _add(
        checks,
        f"row_{index}_schema_version",
        schema_ok,
        f"row {index}: schemaVersion must be one of {sorted(SUPPORTED_INPUT_SCHEMA_VERSIONS)}",
    )

    token_ok = report.get("tokenIncluded") is False
    _add(
        checks,
        f"row_{index}_token_not_included",
        token_ok,
        f"row {index}: tokenIncluded must be false",
    )

    expected_evidence_schema = _expected_evidence_schema_version(input_schema)
    evidence_schema_ok = expected_evidence_schema is not None and report.get("evidenceSchemaVersion") == expected_evidence_schema
    _add(
        checks,
        f"row_{index}_evidence_schema_version",
        evidence_schema_ok,
        f"row {index}: evidenceSchemaVersion must be {expected_evidence_schema or 'a supported evidence schema'}",
    )

    report_checks = _check_lookup(report)
    checks_shape_ok = bool(report_checks)
    _add(
        checks,
        f"row_{index}_checks_shape",
        checks_shape_ok,
        f"row {index}: checks must be a non-empty verifier check list",
    )

    unsafe_verifier_checks = [
        name for name in ("no_sensitive_content", "token_not_included") if report_checks.get(name) is False
    ]
    unsafe_verifier_checks_ok = not unsafe_verifier_checks
    _add(
        checks,
        f"row_{index}_unsafe_verifier_checks_absent",
        unsafe_verifier_checks_ok,
        f"row {index}: unsafe verifier checks must not be false: {', '.join(unsafe_verifier_checks)}",
    )

    negative_boundary_ok = _negative_boundary_ok(report)
    _add(
        checks,
        f"row_{index}_no_boundary_overclaim",
        negative_boundary_ok,
        f"row {index}: direct-STT, compute-plane audit, and production boundaries must not be true",
    )

    required_success_checks = _required_success_checks(input_schema)
    missing_success_checks = sorted(required_success_checks - report_checks.keys())
    required_success_checks_present = bool(required_success_checks) and not missing_success_checks
    _add(
        checks,
        f"row_{index}_required_success_checks_present",
        required_success_checks_present,
        f"row {index}: required verifier checks missing: {', '.join(missing_success_checks)}",
    )
    failed_success_checks = sorted(
        name for name in required_success_checks if report_checks.get(name) is False
    )
    success_checks_pass = bool(required_success_checks) and not failed_success_checks
    _add(
        checks,
        f"row_{index}_required_success_checks_pass",
        success_checks_pass,
        f"row {index}: required verifier checks failed: {', '.join(failed_success_checks)}",
    )
    positive_boundary_success = _positive_boundary_success(report)
    _add(
        checks,
        f"row_{index}_required_boundaries",
        positive_boundary_success,
        f"row {index}: verifier boundaries must match post-hardening G-CAP expectations",
    )
    meeting_id, session_id = _ids(report)
    valid = (
        schema_ok
        and token_ok
        and evidence_schema_ok
        and checks_shape_ok
        and unsafe_verifier_checks_ok
        and negative_boundary_ok
        and required_success_checks_present
        and positive_boundary_success
    )
    ids_ok = (
        isinstance(meeting_id, str)
        and bool(UUID_RE.match(meeting_id))
        and isinstance(session_id, str)
        and bool(SESSION_ID_RE.match(session_id))
    )
    success = (
        valid
        and report.get("status") == "pass"
        and _failures_empty(report)
        and required_success_checks_present
        and success_checks_pass
        and ids_ok
    )

    return Attempt(
        index=index,
        evidence_class=evidence_class,
        valid=valid,
        success=success,
        retry=_retry_marker(report),
        meeting_id=meeting_id if ids_ok else None,
        session_id=session_id if ids_ok else None,
    )


def _threshold_checks(
    checks: list[Check],
    *,
    metrics: dict[str, Any],
    thresholds: Thresholds,
) -> tuple[bool, bool]:
    blocked = False
    failed = False

    has_reports = metrics["reportCount"] > 0
    _add(checks, "has_reports", has_reports, "at least one verifier report is required")
    blocked = blocked or not has_reports

    min_attempts_ok = metrics["attempts"] >= thresholds.min_attempts
    _add(
        checks,
        "min_attempts",
        min_attempts_ok,
        f"attempts must be >= {thresholds.min_attempts}",
    )
    blocked = blocked or not min_attempts_ok

    min_meetings_ok = metrics["distinctMeetings"] >= thresholds.min_distinct_meetings
    _add(
        checks,
        "min_distinct_meetings",
        min_meetings_ok,
        f"distinct meetings must be >= {thresholds.min_distinct_meetings}",
    )
    blocked = blocked or not min_meetings_ok

    min_sessions_ok = metrics["distinctSessions"] >= thresholds.min_distinct_sessions
    _add(
        checks,
        "min_distinct_sessions",
        min_sessions_ok,
        f"distinct sessions must be >= {thresholds.min_distinct_sessions}",
    )
    blocked = blocked or not min_sessions_ok

    success_rate = metrics["successRate"]
    success_rate_ok = success_rate is not None and success_rate >= thresholds.min_success_rate
    _add(
        checks,
        "min_success_rate",
        success_rate_ok,
        f"success rate must be >= {thresholds.min_success_rate:.4f}",
    )
    failed = failed or (not blocked and not success_rate_ok)

    retry_rate = metrics["retryRate"]
    retry_rate_ok = retry_rate is not None and retry_rate <= thresholds.max_retry_rate
    _add(
        checks,
        "max_retry_rate",
        retry_rate_ok,
        f"retry rate must be <= {thresholds.max_retry_rate:.4f}",
    )
    failed = failed or (not blocked and not retry_rate_ok)

    failure_rate = metrics["failureRate"]
    failure_rate_ok = failure_rate is not None and failure_rate <= thresholds.max_failure_rate
    _add(
        checks,
        "max_failure_rate",
        failure_rate_ok,
        f"failure rate must be <= {thresholds.max_failure_rate:.4f}",
    )
    failed = failed or (not blocked and not failure_rate_ok)

    return blocked, failed


def evaluate_reports(
    reports: list[dict[str, Any]],
    *,
    thresholds: Thresholds,
    source_count: int,
) -> tuple[list[Check], dict[str, Any], str]:
    checks: list[Check] = []
    privacy_ok = _validate_no_sensitive_content({"reports": reports}, checks)

    attempts = [_validate_report(index, report, checks) for index, report in enumerate(reports)]
    fatal_row_failure = any(not attempt.valid for attempt in attempts)
    valid_attempts = [attempt for attempt in attempts if attempt.valid]
    success_attempts = [attempt for attempt in valid_attempts if attempt.success]
    failed_attempts = [attempt for attempt in valid_attempts if not attempt.success]
    retry_attempts = [attempt for attempt in valid_attempts if attempt.retry]
    distinct_meetings = {attempt.meeting_id for attempt in success_attempts if attempt.meeting_id}
    distinct_sessions = {attempt.session_id for attempt in success_attempts if attempt.session_id}
    attempt_classes = {
        "externalRecorder": sum(1 for attempt in valid_attempts if attempt.evidence_class == "external_recorder"),
        "desktopCapture": sum(1 for attempt in valid_attempts if attempt.evidence_class == "desktop_capture"),
    }
    passed_attempt_classes = {
        "externalRecorder": sum(1 for attempt in success_attempts if attempt.evidence_class == "external_recorder"),
        "desktopCapture": sum(1 for attempt in success_attempts if attempt.evidence_class == "desktop_capture"),
    }

    metrics: dict[str, Any] = {
        "sourceCount": source_count,
        "reportCount": len(reports),
        "attempts": len(valid_attempts),
        "passed": len(success_attempts),
        "failed": len(failed_attempts),
        "retryAttempts": len(retry_attempts),
        "distinctMeetings": len(distinct_meetings),
        "distinctSessions": len(distinct_sessions),
        "successRate": _rate(len(success_attempts), len(valid_attempts)),
        "failureRate": _rate(len(failed_attempts), len(valid_attempts)),
        "retryRate": _rate(len(retry_attempts), len(valid_attempts)),
        "attemptClasses": attempt_classes,
        "passedAttemptClasses": passed_attempt_classes,
    }

    blocked, threshold_failed = _threshold_checks(checks, metrics=metrics, thresholds=thresholds)

    if not privacy_ok or fatal_row_failure or threshold_failed:
        status = "fail"
    elif blocked:
        status = "blocked"
    else:
        status = "pass"
    return checks, metrics, status


def _summary(
    *,
    checks: list[Check],
    metrics: dict[str, Any],
    thresholds: Thresholds,
    status: str,
    load_errors: list[str] | None = None,
) -> dict[str, Any]:
    failures = [check.message for check in checks if not check.passed]
    if load_errors:
        failures.extend(load_errors)
    return {
        "schemaVersion": VERIFIER_SCHEMA_VERSION,
        "status": status,
        "tokenIncluded": False,
        "checkedAt": _utc_now(),
        "inputSchemaVersions": sorted(SUPPORTED_INPUT_SCHEMA_VERSIONS),
        "checks": [check.__dict__ for check in checks],
        "metrics": metrics,
        "thresholds": thresholds.__dict__,
        "boundaries": {
            "aggregateCaptureGateOnly": True,
            "inputEvidenceClasses": sorted(SUPPORTED_INPUT_SCHEMA_VERSIONS),
            "externalRecorderVerifierInputsAccepted": metrics.get("attemptClasses", {}).get("externalRecorder", 0) > 0,
            "desktopCaptureVerifierInputsAccepted": metrics.get("attemptClasses", {}).get("desktopCapture", 0) > 0,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
            "directSttProven": False,
            "directClientToStt": False,
            "directSttTranscriptProven": False,
            "computePlaneAuditProven": False,
            "desktopMicLoopbackProven": metrics.get("passedAttemptClasses", {}).get("desktopCapture", 0) > 0,
            "productionReady": False,
        },
        "failures": failures,
    }


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


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def _unit_rate(value: str) -> float:
    parsed = float(value)
    if parsed < 0 or parsed > 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return parsed


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-file",
        type=Path,
        action="append",
        default=[],
        help=(
            "Path to a JSON object, JSON array, wrapper object, or JSONL stream of "
            "supported G-CAP verifier reports. Repeatable. If omitted, stdin is used."
        ),
    )
    parser.add_argument("--output-file", type=Path, help="Optional verifier JSON output path.")
    parser.add_argument("--min-attempts", type=_non_negative_int, default=5)
    parser.add_argument("--min-distinct-meetings", type=_non_negative_int, default=5)
    parser.add_argument("--min-distinct-sessions", type=_non_negative_int, default=5)
    parser.add_argument("--min-success-rate", type=_unit_rate, default=0.95)
    parser.add_argument("--max-retry-rate", type=_unit_rate, default=0.10)
    parser.add_argument("--max-failure-rate", type=_unit_rate, default=0.05)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    thresholds = Thresholds(
        min_attempts=args.min_attempts,
        min_distinct_meetings=args.min_distinct_meetings,
        min_distinct_sessions=args.min_distinct_sessions,
        min_success_rate=args.min_success_rate,
        max_retry_rate=args.max_retry_rate,
        max_failure_rate=args.max_failure_rate,
    )

    reports, load_errors, source_count = _load_reports(args.evidence_file)
    if load_errors:
        checks = [Check("evidence_load", False, "; ".join(load_errors))]
        report = _summary(
            checks=checks,
            metrics={
                "sourceCount": source_count,
                "reportCount": 0,
                "attempts": 0,
                "passed": 0,
                "failed": 0,
                "retryAttempts": 0,
                "distinctMeetings": 0,
                "distinctSessions": 0,
                "successRate": None,
                "failureRate": None,
                "retryRate": None,
                "attemptClasses": {"externalRecorder": 0, "desktopCapture": 0},
                "passedAttemptClasses": {"externalRecorder": 0, "desktopCapture": 0},
            },
            thresholds=thresholds,
            status="error",
            load_errors=load_errors,
        )
        exit_code = 2
    else:
        checks, metrics, status = evaluate_reports(
            reports,
            thresholds=thresholds,
            source_count=source_count,
        )
        report = _summary(checks=checks, metrics=metrics, thresholds=thresholds, status=status)
        exit_code = {"pass": 0, "fail": 1, "error": 2, "blocked": 3}[status]

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output_file:
        _write_output_file(args.output_file, rendered)
    print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
