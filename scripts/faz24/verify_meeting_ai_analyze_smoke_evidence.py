#!/usr/bin/env python3
"""Verify redacted Faz 24 Meeting AI analyze smoke evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


EVIDENCE_SCHEMA_VERSION = "faz24.meetingAiAnalyzeSmoke.v1"
VERIFIER_SCHEMA_VERSION = "faz24.meetingAiAnalyzeSmokeVerifier.v1"
EXPECTED_STEPS = ["token_contract", "create_meeting", "meeting_ai_analyze"]
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
SESSION_ID_RE = re.compile(r"^SES-[A-Za-z0-9_-]{4,120}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CAMEL_BOUNDARY_1_RE = re.compile(r"(.)([A-Z][a-z]+)")
CAMEL_BOUNDARY_2_RE = re.compile(r"([a-z0-9])([A-Z])")

FORBIDDEN_KEY_NAMES = {
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
    "summary",
    "decisions",
    "action_items",
    "citations",
}
FORBIDDEN_KEY_NAME_COMPACT = {name.replace("_", "") for name in FORBIDDEN_KEY_NAMES}
ALLOWED_KEY_NAMES = {
    "rawSourceTextIncluded",
    "rawAnalyzeResponseIncluded",
    "rawRequestBodyIncluded",
    "rawResponseBodyIncluded",
    "tokenIncluded",
}
SECRET_VALUE_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bAuthorization\s*:", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:https?|wss?)://[^\s\"']+", re.IGNORECASE),
    re.compile(r"data:audio/[A-Za-z0-9.+-]+;base64,", re.IGNORECASE),
]


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


def _normalized_key(key: str) -> str:
    key = key.replace("-", "_").replace(".", "_").strip()
    key = CAMEL_BOUNDARY_1_RE.sub(r"\1_\2", key)
    key = CAMEL_BOUNDARY_2_RE.sub(r"\1_\2", key)
    return re.sub(r"_+", "_", key).lower()


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


def _steps_by_name(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    steps = data.get("steps")
    if not isinstance(steps, list):
        return {}
    return {
        item["name"]: item
        for item in steps
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def _validate_no_sensitive_content(data: dict[str, Any], checks: list[Check]) -> None:
    findings: list[str] = []
    for path, key, value in _iter_values(data):
        if key is not None and key not in ALLOWED_KEY_NAMES:
            normalized = _normalized_key(key)
            if normalized in FORBIDDEN_KEY_NAMES or normalized.replace("_", "") in FORBIDDEN_KEY_NAME_COMPACT:
                findings.append(f"{path}: forbidden key '{key}'")
                continue
        if isinstance(value, str):
            for pattern in SECRET_VALUE_PATTERNS:
                if pattern.search(value):
                    findings.append(f"{path}: secret-like, URL-like, or raw media value")
                    break

    _add(
        checks,
        "no_sensitive_content",
        not findings,
        "no raw source text, response text, token, URL, or secret-like values found"
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
    _add(
        checks,
        "failures_empty",
        failures in (None, []),
        "failures must be absent or empty",
    )


def _validate_ids(data: dict[str, Any], checks: list[Check]) -> None:
    ids = data.get("ids")
    if not isinstance(ids, dict):
        _add(checks, "ids_shape", False, "ids must be an object")
        return
    _add(
        checks,
        "meeting_id_uuid",
        isinstance(ids.get("meetingId"), str) and bool(UUID_RE.match(ids["meetingId"])),
        "ids.meetingId must be UUID-shaped",
    )
    _add(
        checks,
        "session_id_shape",
        isinstance(ids.get("sessionId"), str) and bool(SESSION_ID_RE.match(ids["sessionId"])),
        "ids.sessionId must be SES-* shaped",
    )


def _validate_sample(data: dict[str, Any], checks: list[Check]) -> None:
    sample = data.get("sample")
    if not isinstance(sample, dict):
        _add(checks, "sample_shape", False, "sample must be an object")
        return
    _add(
        checks,
        "source_text_hash",
        isinstance(sample.get("sourceTextSha256"), str)
        and bool(SHA256_RE.match(sample["sourceTextSha256"])),
        "sample.sourceTextSha256 must be a SHA-256 hex digest",
    )
    _add(
        checks,
        "source_text_not_included",
        sample.get("rawSourceTextIncluded") is False,
        "sample.rawSourceTextIncluded must be false",
    )
    _add(
        checks,
        "analyze_response_not_included",
        sample.get("rawAnalyzeResponseIncluded") is False,
        "sample.rawAnalyzeResponseIncluded must be false",
    )


def _validate_boundaries(data: dict[str, Any], checks: list[Check]) -> None:
    boundaries = data.get("boundaries")
    if not isinstance(boundaries, dict):
        _add(checks, "boundaries_shape", False, "boundaries must be an object")
        return
    expectations = {
        "externalMeetingAdminPathExercised": True,
        "meetingAiAnalyzePathExercised": True,
        "rawSourceTextIncluded": False,
        "rawAnalyzeResponseIncluded": False,
        "rawTokenLogged": False,
        "piiEvidenceIncluded": False,
        "productionReady": False,
        "erpSpecificContract": False,
    }
    for key, expected in expectations.items():
        _add(
            checks,
            f"boundary_{key}",
            boundaries.get(key) is expected,
            f"boundaries.{key} must be {str(expected).lower()}",
        )


def _validate_steps(data: dict[str, Any], checks: list[Check]) -> None:
    steps = _steps_by_name(data)
    _add(
        checks,
        "steps_present",
        all(name in steps for name in EXPECTED_STEPS),
        f"expected steps: {', '.join(EXPECTED_STEPS)}",
    )
    for name in EXPECTED_STEPS:
        step = steps.get(name) or {}
        _add(checks, f"{name}_ok", step.get("ok") is True, f"{name} must have ok=true")
        _add(
            checks,
            f"{name}_token_not_included",
            step.get("tokenIncluded") is False,
            f"{name}.tokenIncluded must be false",
        )

    create = steps.get("create_meeting") or {}
    _add(
        checks,
        "create_meeting_status",
        create.get("method") == "POST"
        and create.get("path") == "/api/v1/admin/meetings"
        and create.get("statusCode") == 201,
        "create_meeting must be POST /api/v1/admin/meetings -> 201",
    )

    analyze = steps.get("meeting_ai_analyze") or {}
    response_meta = analyze.get("responseMeta")
    _add(
        checks,
        "analyze_status",
        analyze.get("method") == "POST"
        and isinstance(analyze.get("path"), str)
        and analyze["path"].endswith("/intelligence/analyze")
        and analyze.get("statusCode") == 200,
        "meeting_ai_analyze must be POST */intelligence/analyze -> 200",
    )
    _add(
        checks,
        "analyze_raw_bodies_absent",
        analyze.get("rawRequestBodyIncluded") is False
        and analyze.get("rawResponseBodyIncluded") is False,
        "meeting_ai_analyze must not include raw request or response bodies",
    )
    _add(
        checks,
        "analyze_structured_envelope",
        isinstance(response_meta, dict) and response_meta.get("structuredEnvelope") is True,
        "responseMeta must summarize a structured analyze envelope",
    )
    if isinstance(response_meta, dict):
        _add(
            checks,
            "analyze_schema_present",
            isinstance(response_meta.get("schemaVersion"), str)
            and bool(response_meta["schemaVersion"]),
            "responseMeta.schemaVersion must be present",
        )
        _add(
            checks,
            "analyze_backend_present",
            isinstance(response_meta.get("backend"), str) and bool(response_meta["backend"]),
            "responseMeta.backend must be present",
        )


def verify(data: dict[str, Any]) -> dict[str, Any]:
    checks: list[Check] = []
    _validate_top_level(data, checks)
    _validate_no_sensitive_content(data, checks)
    _validate_ids(data, checks)
    _validate_sample(data, checks)
    _validate_boundaries(data, checks)
    _validate_steps(data, checks)
    passed = all(check.passed for check in checks)
    return {
        "schemaVersion": VERIFIER_SCHEMA_VERSION,
        "status": "pass" if passed else "fail",
        "checkedAt": _utc_now(),
        "checks": [
            {"name": check.name, "passed": check.passed, "message": check.message}
            for check in checks
        ],
        "failedChecks": [check.name for check in checks if not check.passed],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-file", type=Path)
    parser.add_argument("--output-file", type=Path)
    return parser.parse_args(argv)


def _write_output_file(path: Path, rendered: str) -> None:
    fd = path.open("w", encoding="utf-8")
    try:
        fd.write(rendered + "\n")
    finally:
        fd.close()
        try:
            path.chmod(0o600)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    evidence, error = _load_evidence(args.evidence_file)
    if error is not None or evidence is None:
        report = {
            "schemaVersion": VERIFIER_SCHEMA_VERSION,
            "status": "fail",
            "checkedAt": _utc_now(),
            "checks": [
                {
                    "name": "load_evidence",
                    "passed": False,
                    "message": error or "unknown load error",
                }
            ],
            "failedChecks": ["load_evidence"],
        }
    else:
        report = verify(evidence)

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output_file:
        _write_output_file(args.output_file, rendered)
    print(rendered)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
