#!/usr/bin/env python3
"""Verify Faz 24 audio-gateway JWT audience/capability enforcement evidence.

This verifier consumes only redacted metadata from the #716 enforce-flip smoke.
It rejects token-shaped content, raw audio/transcript fields, production
overclaims, and incomplete fail-closed matrices before evidence is attached to
GitHub issues.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


EVIDENCE_SCHEMA_VERSION = "faz24.audioGatewayAuthzEnforceEvidence.v1"
VERIFIER_SCHEMA_VERSION = "faz24.audioGatewayAuthzEnforceVerifier.v1"
RESOURCE_CLIENT_ID = "audio-gateway-service"
CAPABILITY_ROLE = "audio_record"

EXPECTED_CHECKS = [
    "no_token",
    "wrong_audience",
    "missing_audio_record_role",
    "valid_recorder",
]

EXPECTED_HTTP_STATUS = {
    "no_token": {401},
    "wrong_audience": {401},
    "missing_audio_record_role": {403},
    # A 404 for a synthetic/nonexistent session still proves security passed
    # when the failure class is business object absence, not authn/authz.
    "valid_recorder": {200, 201, 202, 204, 404},
}

BOUNDARY_EXPECTATIONS = {
    "testClusterOnly": True,
    "directSttProven": False,
    "rawAudioSent": False,
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
    "audio",
    "audio_bytes",
    "audiobytes",
    "raw_audio",
    "rawaudio",
    "transcript",
    "transcript_text",
    "transcripttext",
    "segments",
    "prompt",
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


def _validate_no_sensitive_content(data: dict[str, Any], checks: list[Check]) -> None:
    findings: list[str] = []
    for path, key, value in _iter_values(data):
        if key is not None and key.lower() in SENSITIVE_KEY_NAMES:
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
        "no sensitive keys or token/audio-shaped values found"
        if not findings
        else "; ".join(findings[:8]),
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
    _add(
        checks,
        "failures_empty",
        data.get("failures") in (None, []),
        "failures must be absent or empty",
    )


def _validate_environment(data: dict[str, Any], checks: list[Check]) -> None:
    env = data.get("environment")
    if not isinstance(env, dict):
        _add(checks, "environment_shape", False, "environment must be an object")
        return
    _add(
        checks,
        "resource_client_id",
        env.get("resourceClientId") == RESOURCE_CLIENT_ID,
        f"environment.resourceClientId must be {RESOURCE_CLIENT_ID}",
    )
    _add(
        checks,
        "enforce_audience_enabled",
        env.get("enforceAudience") is True,
        "environment.enforceAudience must be true",
    )
    _add(
        checks,
        "require_role_enabled",
        env.get("requireAudioRecordRole") is True,
        "environment.requireAudioRecordRole must be true",
    )
    _add(
        checks,
        "jwks_internal",
        env.get("jwksInternal") is True,
        "environment.jwksInternal must be true",
    )


def _validate_recorder_token_summary(data: dict[str, Any], checks: list[Check]) -> None:
    summary = data.get("recorderToken")
    if not isinstance(summary, dict):
        _add(checks, "recorder_token_shape", False, "recorderToken must be an object")
        return
    _add(
        checks,
        "recorder_token_redacted",
        summary.get("tokenIncluded") is False,
        "recorderToken.tokenIncluded must be false",
    )
    _add(
        checks,
        "recorder_audience_present",
        summary.get("audiencePresent") is True,
        f"recorder token summary must prove aud={RESOURCE_CLIENT_ID}",
    )
    _add(
        checks,
        "recorder_role_present",
        summary.get("audioRecordRolePresent") is True,
        f"recorder token summary must prove role={CAPABILITY_ROLE}",
    )
    _add(
        checks,
        "new_login_verified",
        summary.get("newLoginVerified") is True,
        "new-login token must be verified",
    )
    _add(
        checks,
        "refresh_grant_verified",
        summary.get("refreshGrantVerified") is True,
        "refresh-grant token must be verified",
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


def _validate_live_checks(data: dict[str, Any], checks: list[Check]) -> None:
    live_checks = data.get("checks")
    if not isinstance(live_checks, list):
        _add(checks, "checks_shape", False, "checks must be a list")
        return

    actual = [item.get("name") if isinstance(item, dict) else None for item in live_checks]
    _add(
        checks,
        "checks_exact_order",
        actual == EXPECTED_CHECKS,
        "checks must appear in exact expected order",
    )

    by_name = {
        item["name"]: item
        for item in live_checks
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    for name in EXPECTED_CHECKS:
        item = by_name.get(name)
        if not item:
            _add(checks, f"{name}_present", False, f"missing check {name}")
            continue
        status_code = item.get("statusCode")
        status_ok = status_code in EXPECTED_HTTP_STATUS[name]
        _add(
            checks,
            f"{name}_status",
            status_ok,
            f"{name}.statusCode must be one of {sorted(EXPECTED_HTTP_STATUS[name])}",
        )
        _add(checks, f"{name}_ok", item.get("ok") is True, f"{name}.ok must be true")
        _add(
            checks,
            f"{name}_token_not_included",
            item.get("tokenIncluded") is False,
            f"{name}.tokenIncluded must be false",
        )
        path = item.get("path")
        _add(
            checks,
            f"{name}_path",
            isinstance(path, str) and path.startswith("/api/v1/audio-gateway"),
            f"{name}.path must target /api/v1/audio-gateway",
        )

    valid = by_name.get("valid_recorder")
    if valid:
        _add(
            checks,
            "valid_recorder_security_passed",
            valid.get("securityPassed") is True,
            "valid_recorder.securityPassed must be true",
        )
        if valid.get("statusCode") == 404:
            _add(
                checks,
                "valid_recorder_404_business_boundary",
                valid.get("businessStatus") == "session-not-found",
                "valid_recorder 404 must be businessStatus=session-not-found",
            )


def verify(data: dict[str, Any]) -> dict[str, Any]:
    checks: list[Check] = []
    _validate_no_sensitive_content(data, checks)
    _validate_top_level(data, checks)
    _validate_environment(data, checks)
    _validate_recorder_token_summary(data, checks)
    _validate_boundaries(data, checks)
    _validate_live_checks(data, checks)

    failures = [check.message for check in checks if not check.passed]
    return {
        "schemaVersion": VERIFIER_SCHEMA_VERSION,
        "verifiedAt": _utc_now(),
        "status": "pass" if not failures else "fail",
        "tokenIncluded": False,
        "evidenceSchemaVersion": data.get("schemaVersion"),
        "resourceClientId": RESOURCE_CLIENT_ID,
        "capabilityRole": CAPABILITY_ROLE,
        "checks": [check.__dict__ for check in checks],
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify redacted Faz 24 audio-gateway authz enforce evidence."
    )
    parser.add_argument(
        "--evidence-file",
        type=Path,
        help="Path to redacted evidence JSON. If omitted, stdin is used.",
    )
    parser.add_argument("--output-file", type=Path, help="Optional path for verifier JSON.")
    args = parser.parse_args(argv)

    data, error = _load_evidence(args.evidence_file)
    if error:
        report = {
            "schemaVersion": VERIFIER_SCHEMA_VERSION,
            "verifiedAt": _utc_now(),
            "status": "error",
            "tokenIncluded": False,
            "error": error,
        }
        rc = 2
    else:
        assert data is not None
        report = verify(data)
        rc = 0 if report["status"] == "pass" else 1

    output = json.dumps(report, indent=2, sort_keys=True)
    if args.output_file:
        args.output_file.write_text(output + "\n", encoding="utf-8")
    print(output)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
