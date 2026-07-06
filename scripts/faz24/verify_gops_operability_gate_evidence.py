#!/usr/bin/env python3
"""Verify Faz 24 G-OPS on-prem operability gate evidence.

This verifier accepts a redacted metadata envelope for on-prem/self-host
operability. It validates install, upgrade, backup, restore, rollback,
secret-delivery, observability, and runbook evidence without accepting
credentials, raw audio, transcript text, or production-readiness overclaims.
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


EVIDENCE_SCHEMA_VERSION = "faz24.gopsOperabilityEvidence.v1"
VERIFIER_SCHEMA_VERSION = "faz24.gopsOperabilityGateVerifier.v1"

REQUIRED_CHECKS = {
    "install",
    "upgrade",
    "backup",
    "restore",
    "rollback",
    "secret_delivery",
    "observability",
    "runbook",
}

REQUIRED_METRICS = {
    "installDurationMinutes",
    "upgradeDurationMinutes",
    "backupAgeHours",
    "restoreRtoMinutes",
    "restoreRpoMinutes",
    "rollbackRtoMinutes",
    "secretRotationMinutes",
    "observabilityCoverage",
}

BOUNDARY_EXPECTATIONS = {
    "installEvidencePresent": True,
    "upgradeEvidencePresent": True,
    "backupEvidencePresent": True,
    "restoreEvidencePresent": True,
    "rollbackEvidencePresent": True,
    "secretDeliveryEvidencePresent": True,
    "observabilityEvidencePresent": True,
    "runbookEvidencePresent": True,
    "secretsIncluded": False,
    "rawAudioIncluded": False,
    "rawTranscriptIncluded": False,
    "liveProductionMutation": False,
    "productionReady": False,
}

FORBIDDEN_TRUE_BOUNDARIES = {
    "secretsIncluded",
    "rawAudioIncluded",
    "rawTranscriptIncluded",
    "liveProductionMutation",
    "productionReady",
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
    "root_token",
    "vault_token",
    "unseal_key",
    "kubeconfig",
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
    re.compile(r"\bpassword\s*[:=]", re.IGNORECASE),
]

SAFE_EVIDENCE_REF_RE = re.compile(
    r"^(github|github-actions|artifact|operator|protected|runbook)://[A-Za-z0-9_.:@/#?=&%+-]{3,240}$"
)


@dataclass
class Check:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class Thresholds:
    max_install_minutes: float
    max_upgrade_minutes: float
    max_backup_age_hours: float
    max_restore_rto_minutes: float
    max_restore_rpo_minutes: float
    max_rollback_rto_minutes: float
    max_secret_rotation_minutes: float
    min_observability_coverage: float


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


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _validate_no_sensitive_content(data: dict[str, Any], checks: list[Check]) -> bool:
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


def _validate_top_level(data: dict[str, Any], checks: list[Check]) -> bool:
    schema_ok = data.get("schemaVersion") == EVIDENCE_SCHEMA_VERSION
    _add(
        checks,
        "schema_version",
        schema_ok,
        f"schemaVersion must be {EVIDENCE_SCHEMA_VERSION}",
    )
    status_ok = data.get("status") == "pass"
    _add(checks, "status_pass", status_ok, "status must be pass")
    token_ok = data.get("tokenIncluded") is False
    _add(checks, "token_not_included", token_ok, "top-level tokenIncluded must be false")
    failures = data.get("failures")
    failures_ok = failures in (None, [])
    _add(checks, "failures_empty", failures_ok, "failures must be absent or empty")
    return schema_ok and status_ok and token_ok and failures_ok


def _validate_environment(data: dict[str, Any], checks: list[Check]) -> bool:
    environment = data.get("environment")
    if not isinstance(environment, dict):
        _add(checks, "environment_shape", False, "environment must be an object")
        return False
    env_class = environment.get("class")
    class_ok = env_class in {"lab", "staging", "pilot", "onprem-pilot", "dr-drill"}
    _add(
        checks,
        "environment_class",
        class_ok,
        "environment.class must be lab, staging, pilot, onprem-pilot, or dr-drill",
    )
    name = environment.get("name")
    name_ok = isinstance(name, str) and 3 <= len(name) <= 80 and "\n" not in name
    _add(checks, "environment_name", name_ok, "environment.name must be a bounded string")
    return class_ok and name_ok


def _validate_boundaries(data: dict[str, Any], checks: list[Check]) -> tuple[bool, bool]:
    boundaries = data.get("boundaries")
    if not isinstance(boundaries, dict):
        _add(checks, "boundaries_shape", False, "boundaries must be an object")
        return False, False

    all_required_ok = True
    fatal_ok = True
    for key, expected in BOUNDARY_EXPECTATIONS.items():
        passed = boundaries.get(key) is expected
        _add(
            checks,
            f"boundary_{key}",
            passed,
            f"boundaries.{key} must be {str(expected).lower()}",
        )
        all_required_ok = all_required_ok and passed
        if key in FORBIDDEN_TRUE_BOUNDARIES and boundaries.get(key) is True:
            fatal_ok = False
    return all_required_ok, fatal_ok


def _check_map(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_checks = data.get("checks")
    if not isinstance(raw_checks, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in raw_checks:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            result[item["name"]] = item
    return result


def _validate_checks(data: dict[str, Any], checks: list[Check]) -> tuple[bool, bool]:
    named = _check_map(data)
    _add(checks, "checks_shape", bool(named), "checks must be a non-empty list of named objects")
    missing = sorted(REQUIRED_CHECKS - set(named))
    _add(
        checks,
        "required_checks_present",
        not missing,
        "required checks must be present: " + ", ".join(sorted(REQUIRED_CHECKS)),
    )

    blocked = bool(missing) or not named
    failed = False
    for name in sorted(REQUIRED_CHECKS & set(named)):
        item = named[name]
        status = item.get("status")
        status_pass = status == "pass"
        _add(
            checks,
            f"check_{name}_status_pass",
            status_pass,
            f"check {name} status must be pass",
        )
        if status in {"blocked", "missing", "skipped", None, ""}:
            blocked = True
        elif not status_pass:
            failed = True

        ref = item.get("evidenceRef")
        ref_ok = isinstance(ref, str) and bool(SAFE_EVIDENCE_REF_RE.match(ref))
        _add(
            checks,
            f"check_{name}_evidence_ref",
            ref_ok,
            f"check {name} evidenceRef must use an allowed bounded evidence URI",
        )
        blocked = blocked or not ref_ok
    return blocked, failed


def _metric(metrics: dict[str, Any], key: str, checks: list[Check]) -> float | None:
    value = _as_number(metrics.get(key))
    value_ok = value is not None and value >= 0
    _add(checks, f"metric_{key}_present", value_ok, f"metrics.{key} must be numeric and >= 0")
    if not value_ok:
        return None
    return value


def _validate_metrics(
    data: dict[str, Any],
    checks: list[Check],
    thresholds: Thresholds,
) -> tuple[bool, bool, dict[str, float | None]]:
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        _add(checks, "metrics_shape", False, "metrics must be an object")
        return True, False, {key: None for key in REQUIRED_METRICS}

    values = {key: _metric(metrics, key, checks) for key in sorted(REQUIRED_METRICS)}
    blocked = any(value is None for value in values.values())
    failed = False

    threshold_pairs = [
        ("installDurationMinutes", values["installDurationMinutes"], thresholds.max_install_minutes, "<="),
        ("upgradeDurationMinutes", values["upgradeDurationMinutes"], thresholds.max_upgrade_minutes, "<="),
        ("backupAgeHours", values["backupAgeHours"], thresholds.max_backup_age_hours, "<="),
        ("restoreRtoMinutes", values["restoreRtoMinutes"], thresholds.max_restore_rto_minutes, "<="),
        ("restoreRpoMinutes", values["restoreRpoMinutes"], thresholds.max_restore_rpo_minutes, "<="),
        ("rollbackRtoMinutes", values["rollbackRtoMinutes"], thresholds.max_rollback_rto_minutes, "<="),
        ("secretRotationMinutes", values["secretRotationMinutes"], thresholds.max_secret_rotation_minutes, "<="),
    ]
    for key, value, threshold, operator in threshold_pairs:
        passed = value is not None and value <= threshold
        _add(checks, f"threshold_{key}", passed, f"metrics.{key} must be {operator} {threshold:g}")
        failed = failed or (not blocked and not passed)

    coverage = values["observabilityCoverage"]
    coverage_ok = coverage is not None and 0 <= coverage <= 1 and coverage >= thresholds.min_observability_coverage
    _add(
        checks,
        "threshold_observabilityCoverage",
        coverage_ok,
        f"metrics.observabilityCoverage must be between 0 and 1 and >= {thresholds.min_observability_coverage:.4f}",
    )
    failed = failed or (not blocked and not coverage_ok)
    return blocked, failed, values


def validate_evidence(
    data: dict[str, Any],
    *,
    thresholds: Thresholds,
) -> tuple[list[Check], dict[str, Any], str]:
    checks: list[Check] = []
    privacy_ok = _validate_no_sensitive_content(data, checks)
    structural_ok = _validate_top_level(data, checks)
    environment_ok = _validate_environment(data, checks)
    boundary_all_ok, boundary_fatal_ok = _validate_boundaries(data, checks)
    checks_blocked, checks_failed = _validate_checks(data, checks)
    metrics_blocked, metrics_failed, metric_values = _validate_metrics(data, checks, thresholds)

    metrics = {
        "requiredChecks": len(REQUIRED_CHECKS),
        "metricCount": len(REQUIRED_METRICS),
        "values": metric_values,
    }

    if not privacy_ok or not structural_ok or not boundary_fatal_ok or checks_failed or metrics_failed:
        status = "fail"
    elif not environment_ok or not boundary_all_ok or checks_blocked or metrics_blocked:
        status = "blocked"
    else:
        status = "pass"
    return checks, metrics, status


def _summary(
    *,
    data: dict[str, Any] | None,
    checks: list[Check],
    metrics: dict[str, Any],
    thresholds: Thresholds,
    status: str,
) -> dict[str, Any]:
    failures = [check.message for check in checks if not check.passed]
    return {
        "schemaVersion": VERIFIER_SCHEMA_VERSION,
        "status": status,
        "tokenIncluded": False,
        "checkedAt": _utc_now(),
        "evidenceSchemaVersion": data.get("schemaVersion") if data else None,
        "checks": [check.__dict__ for check in checks],
        "metrics": metrics,
        "thresholds": thresholds.__dict__,
        "boundaries": {
            "gopsOperabilityGateOnly": True,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
            "secretsIncluded": False,
            "liveProductionMutation": False,
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


def _positive_float(value: str) -> float:
    parsed = float(value)
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
        help=f"Path to {EVIDENCE_SCHEMA_VERSION} JSON. If omitted, stdin is used.",
    )
    parser.add_argument("--output-file", type=Path, help="Optional verifier JSON output path.")
    parser.add_argument("--max-install-minutes", type=_positive_float, default=120.0)
    parser.add_argument("--max-upgrade-minutes", type=_positive_float, default=90.0)
    parser.add_argument("--max-backup-age-hours", type=_positive_float, default=24.0)
    parser.add_argument("--max-restore-rto-minutes", type=_positive_float, default=240.0)
    parser.add_argument("--max-restore-rpo-minutes", type=_positive_float, default=1440.0)
    parser.add_argument("--max-rollback-rto-minutes", type=_positive_float, default=60.0)
    parser.add_argument("--max-secret-rotation-minutes", type=_positive_float, default=60.0)
    parser.add_argument("--min-observability-coverage", type=_unit_rate, default=0.90)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    thresholds = Thresholds(
        max_install_minutes=args.max_install_minutes,
        max_upgrade_minutes=args.max_upgrade_minutes,
        max_backup_age_hours=args.max_backup_age_hours,
        max_restore_rto_minutes=args.max_restore_rto_minutes,
        max_restore_rpo_minutes=args.max_restore_rpo_minutes,
        max_rollback_rto_minutes=args.max_rollback_rto_minutes,
        max_secret_rotation_minutes=args.max_secret_rotation_minutes,
        min_observability_coverage=args.min_observability_coverage,
    )

    data, error = _load_evidence(args.evidence_file)
    if error:
        checks = [Check("json_load", False, error)]
        report = _summary(
            data=None,
            checks=checks,
            metrics={},
            thresholds=thresholds,
            status="error",
        )
        exit_code = 2
    else:
        assert data is not None
        checks, metrics, status = validate_evidence(data, thresholds=thresholds)
        report = _summary(data=data, checks=checks, metrics=metrics, thresholds=thresholds, status=status)
        exit_code = {"pass": 0, "fail": 1, "error": 2, "blocked": 3}[status]

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output_file:
        _write_output_file(args.output_file, rendered)
    print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
