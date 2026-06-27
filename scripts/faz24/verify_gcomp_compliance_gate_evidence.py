#!/usr/bin/env python3
"""Verify Faz 24 G-COMP engineering compliance-readiness evidence.

This verifier accepts a redacted metadata envelope for engineering-owned
compliance controls. It validates consent, parametric retention controls,
legal-hold, access-audit, deletion/export, owner legal-track notification,
redaction, and runbook evidence without accepting raw audio, transcript text,
credentials, personal data, or legal / production-readiness overclaims.

Legal/KVKK/VERBIS acceptance is a parallel owner/legal track and is not an
engineering blocker after owner notification is recorded.
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


EVIDENCE_SCHEMA_VERSION = "faz24.gcompComplianceEvidence.v1"
VERIFIER_SCHEMA_VERSION = "faz24.gcompComplianceGateVerifier.v1"

ENGINEERING_REQUIRED_CHECKS = {
    "consent",
    "retention",
    "legal_hold",
    "access_audit",
    "deletion_export",
    "redaction",
    "runbook",
}

LEGAL_TRACK_NOTIFICATION_CHECKS = {
    "legal_track_notification",
    "kvkk_verbis",
}

REQUIRED_CHECKS = ENGINEERING_REQUIRED_CHECKS | {"legal_track_notification"}

REQUIRED_METRICS = {
    "consentCoverage",
    "retentionPolicyCoverage",
    "accessAuditCoverage",
    "deletionExportCoverage",
    "redactionCoverage",
    "dataSubjectResponseDays",
    "legalHoldDrillAgeDays",
    "dbCleanupEvidenceAgeDays",
}

BOUNDARY_EXPECTATIONS = {
    "consentEvidencePresent": True,
    "retentionEvidencePresent": True,
    "legalHoldEvidencePresent": True,
    "accessAuditEvidencePresent": True,
    "deletionExportEvidencePresent": True,
    "ownerLegalTrackNotificationPresent": True,
    "retentionDurationsParametric": True,
    "retentionDefaultsFailClosed": True,
    "consentDefaultRequired": True,
    "deletionPipelineDefaultEnabled": True,
    "redactionEvidencePresent": True,
    "secretsIncluded": False,
    "rawAudioIncluded": False,
    "rawTranscriptIncluded": False,
    "rawPromptIncluded": False,
    "rawResponseIncluded": False,
    "unredactedPersonalDataIncluded": False,
    "legalAdviceClaimed": False,
    "legalAcceptanceClaimed": False,
    "productionLegalGoClaimed": False,
    "retentionDurationsHardcoded": False,
    "liveProductionMutation": False,
    "productionReady": False,
}

FORBIDDEN_TRUE_BOUNDARIES = {
    "secretsIncluded",
    "rawAudioIncluded",
    "rawTranscriptIncluded",
    "rawPromptIncluded",
    "rawResponseIncluded",
    "unredactedPersonalDataIncluded",
    "legalAdviceClaimed",
    "legalAcceptanceClaimed",
    "productionLegalGoClaimed",
    "retentionDurationsHardcoded",
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
    "raw_transcript",
    "transcript_text",
    "transcripttext",
    "segments",
    "prompt",
    "raw_prompt",
    "response",
    "raw_response_text",
    "raw_request",
    "raw_response",
    "body",
    "payload",
    "email",
    "phone",
    "telephone",
    "mobile",
    "tckn",
    "tc_kimlik",
    "national_id",
    "identity_number",
    "full_name",
    "participant_name",
    "personal_data",
    "raw_personal_data",
}

EMAIL_VALUE_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_VALUE_RE = re.compile(r"\b(?:\+?90|0)?5\d{9}\b")

SECRET_VALUE_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bAuthorization\s*:", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bpassword\s*[:=]", re.IGNORECASE),
    EMAIL_VALUE_RE,
    PHONE_VALUE_RE,
]

SAFE_EVIDENCE_REF_RE = re.compile(
    r"^(github|github-actions|artifact|operator|protected|runbook|legal|dpo)://"
    r"[A-Za-z0-9_.:@/#?=&%+-]{3,240}$"
)
OWNER_RETENTION_REF_SCHEMES = {"github", "github-actions", "artifact", "operator", "protected", "legal", "dpo"}
RETENTION_PARAMETER_DAY_FIELDS = {
    "rawAudioRetentionDays",
    "transcriptRetentionDays",
    "derivedArtifactRetentionDays",
    "auditRetentionDays",
}
MAX_RETENTION_DAYS = 36500


@dataclass
class Check:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class Thresholds:
    min_consent_coverage: float
    min_retention_policy_coverage: float
    min_access_audit_coverage: float
    min_deletion_export_coverage: float
    min_redaction_coverage: float
    max_data_subject_response_days: float
    max_legal_hold_drill_age_days: float
    max_db_cleanup_evidence_age_days: float


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
            is_evidence_ref = key is not None and _normalized_key(key) == "evidenceref"
            for pattern in SECRET_VALUE_PATTERNS:
                if is_evidence_ref and pattern in (EMAIL_VALUE_RE, PHONE_VALUE_RE):
                    continue
                if pattern.search(value):
                    findings.append(f"{path}: sensitive value")
                    break

    passed = not findings
    _add(
        checks,
        "no_sensitive_content",
        passed,
        "no sensitive keys, personal data, or token-shaped values found"
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
    class_ok = env_class in {
        "lab",
        "staging",
        "pilot",
        "onprem-pilot",
        "legal-review",
        "compliance-drill",
    }
    _add(
        checks,
        "environment_class",
        class_ok,
        (
            "environment.class must be lab, staging, pilot, onprem-pilot, "
            "legal-review, or compliance-drill"
        ),
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


def _evidence_ref_ok(item: dict[str, Any]) -> bool:
    ref = item.get("evidenceRef")
    return isinstance(ref, str) and bool(SAFE_EVIDENCE_REF_RE.match(ref))


def _ref_scheme(ref: str) -> str:
    return ref.split("://", 1)[0].lower()


def _owner_retention_ref_ok(ref: Any) -> bool:
    return (
        isinstance(ref, str)
        and bool(SAFE_EVIDENCE_REF_RE.match(ref))
        and _ref_scheme(ref) in OWNER_RETENTION_REF_SCHEMES
    )


def _retention_day_value_ok(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_RETENTION_DAYS


def _validate_retention_parameters(data: dict[str, Any], checks: list[Check]) -> tuple[bool, bool, dict[str, Any]]:
    """Validate optional owner-supplied effective retention duration metadata."""
    parameters = data.get("retentionParameters")
    if parameters is None:
        _add(
            checks,
            "retention_parameters_absent_uses_fail_closed_defaults",
            True,
            "retentionParameters absent; fail-closed default boundary is used",
        )
        return False, False, {
            "present": False,
            "effectiveValuesSupplied": False,
            "suppliedDurationFields": [],
        }

    if not isinstance(parameters, dict):
        _add(checks, "retention_parameters_shape", False, "retentionParameters must be an object")
        return True, False, {
            "present": False,
            "effectiveValuesSupplied": False,
            "suppliedDurationFields": [],
        }

    supplied_duration_fields = sorted(
        key for key in RETENTION_PARAMETER_DAY_FIELDS if parameters.get(key) is not None
    )
    effective_flag = parameters.get("effectiveValuesSupplied")
    effective_values_supplied = effective_flag is True or bool(supplied_duration_fields)
    _add(
        checks,
        "retention_parameters_effective_values_flag",
        isinstance(effective_flag, bool) or effective_flag is None,
        "retentionParameters.effectiveValuesSupplied must be boolean when present",
    )

    invalid_duration_fields = sorted(
        key
        for key in supplied_duration_fields
        if not _retention_day_value_ok(parameters.get(key))
    )
    durations_ok = not invalid_duration_fields
    _add(
        checks,
        "retention_parameters_duration_values",
        durations_ok,
        (
            "retention duration fields must be positive integer days <= "
            f"{MAX_RETENTION_DAYS}: {', '.join(invalid_duration_fields)}"
        ),
    )

    values_required_ok = not (effective_flag is True and not supplied_duration_fields)
    _add(
        checks,
        "retention_parameters_values_present_when_supplied",
        values_required_ok,
        "effectiveValuesSupplied=true requires at least one effective retention duration value",
    )

    owner_ref_ok = True
    applied_as_config_ok = True
    hardcoded_ok = True
    if effective_values_supplied:
        owner_ref_ok = _owner_retention_ref_ok(parameters.get("ownerDecisionRef"))
        applied_as_config_ok = parameters.get("appliedAsConfig") is True
        hardcoded_ok = parameters.get("hardcodedInCode") is False
    hardcoded_is_affirmed = parameters.get("hardcodedInCode") is True
    _add(
        checks,
        "retention_parameters_owner_decision_ref",
        owner_ref_ok,
        "supplied retention durations require a bounded owner/legal/operator/protected ownerDecisionRef",
    )
    _add(
        checks,
        "retention_parameters_applied_as_config",
        applied_as_config_ok,
        "supplied retention durations must be applied as config",
    )
    _add(
        checks,
        "retention_parameters_not_hardcoded",
        hardcoded_ok,
        "supplied retention durations must not be hardcoded in code, manifests, or fixtures",
    )

    blocked = (
        (not isinstance(effective_flag, bool) and effective_flag is not None)
        or not durations_ok
        or not values_required_ok
        or not owner_ref_ok
        or not applied_as_config_ok
        or not hardcoded_ok
    )
    failed = hardcoded_is_affirmed
    return blocked, failed, {
        "present": True,
        "effectiveValuesSupplied": effective_values_supplied,
        "suppliedDurationFields": supplied_duration_fields,
        "ownerDecisionRefPresent": _owner_retention_ref_ok(parameters.get("ownerDecisionRef")),
        "appliedAsConfig": parameters.get("appliedAsConfig") is True,
        "hardcodedInCode": hardcoded_is_affirmed,
    }


def _validate_checks(data: dict[str, Any], checks: list[Check]) -> tuple[bool, bool]:
    named = _check_map(data)
    _add(checks, "checks_shape", bool(named), "checks must be a non-empty list of named objects")
    missing = sorted(ENGINEERING_REQUIRED_CHECKS - set(named))
    _add(
        checks,
        "required_checks_present",
        not missing,
        "engineering checks must be present: " + ", ".join(sorted(ENGINEERING_REQUIRED_CHECKS)),
    )

    blocked = bool(missing) or not named
    failed = False
    for name in sorted(ENGINEERING_REQUIRED_CHECKS & set(named)):
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

        ref_ok = _evidence_ref_ok(item)
        _add(
            checks,
            f"check_{name}_evidence_ref",
            ref_ok,
            f"check {name} evidenceRef must use an allowed bounded evidence URI",
        )
        blocked = blocked or not ref_ok

    legal_track_candidates = [
        named[name] for name in sorted(LEGAL_TRACK_NOTIFICATION_CHECKS & set(named))
    ]
    legal_track_present = bool(legal_track_candidates)
    _add(
        checks,
        "legal_track_notification_present",
        legal_track_present,
        "one legal-track notification check must be present: "
        + ", ".join(sorted(LEGAL_TRACK_NOTIFICATION_CHECKS)),
    )
    legal_track_pass = any(item.get("status") == "pass" for item in legal_track_candidates)
    _add(
        checks,
        "legal_track_notification_status_pass",
        legal_track_pass,
        "one legal-track notification check must have status pass; legal acceptance itself is parallel",
    )
    legal_track_ref_ok = any(
        item.get("status") == "pass" and _evidence_ref_ok(item) for item in legal_track_candidates
    )
    _add(
        checks,
        "legal_track_notification_evidence_ref",
        legal_track_ref_ok,
        "legal-track notification evidenceRef must use an allowed bounded evidence URI",
    )
    blocked = blocked or not legal_track_present or not legal_track_pass or not legal_track_ref_ok
    return blocked, failed


def _metric(metrics: dict[str, Any], key: str, checks: list[Check]) -> float | None:
    value = _as_number(metrics.get(key))
    value_ok = value is not None and value >= 0
    _add(checks, f"metric_{key}_present", value_ok, f"metrics.{key} must be numeric and >= 0")
    if not value_ok:
        return None
    return value


def _rate_threshold(
    *,
    key: str,
    value: float | None,
    minimum: float,
    checks: list[Check],
) -> bool:
    passed = value is not None and 0 <= value <= 1 and value >= minimum
    _add(
        checks,
        f"threshold_{key}",
        passed,
        f"metrics.{key} must be between 0 and 1 and >= {minimum:.4f}",
    )
    return passed


def _max_threshold(
    *,
    key: str,
    value: float | None,
    maximum: float,
    checks: list[Check],
) -> bool:
    passed = value is not None and value <= maximum
    _add(checks, f"threshold_{key}", passed, f"metrics.{key} must be <= {maximum:g}")
    return passed


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

    threshold_results = [
        _rate_threshold(
            key="consentCoverage",
            value=values["consentCoverage"],
            minimum=thresholds.min_consent_coverage,
            checks=checks,
        ),
        _rate_threshold(
            key="retentionPolicyCoverage",
            value=values["retentionPolicyCoverage"],
            minimum=thresholds.min_retention_policy_coverage,
            checks=checks,
        ),
        _rate_threshold(
            key="accessAuditCoverage",
            value=values["accessAuditCoverage"],
            minimum=thresholds.min_access_audit_coverage,
            checks=checks,
        ),
        _rate_threshold(
            key="deletionExportCoverage",
            value=values["deletionExportCoverage"],
            minimum=thresholds.min_deletion_export_coverage,
            checks=checks,
        ),
        _rate_threshold(
            key="redactionCoverage",
            value=values["redactionCoverage"],
            minimum=thresholds.min_redaction_coverage,
            checks=checks,
        ),
        _max_threshold(
            key="dataSubjectResponseDays",
            value=values["dataSubjectResponseDays"],
            maximum=thresholds.max_data_subject_response_days,
            checks=checks,
        ),
        _max_threshold(
            key="legalHoldDrillAgeDays",
            value=values["legalHoldDrillAgeDays"],
            maximum=thresholds.max_legal_hold_drill_age_days,
            checks=checks,
        ),
        _max_threshold(
            key="dbCleanupEvidenceAgeDays",
            value=values["dbCleanupEvidenceAgeDays"],
            maximum=thresholds.max_db_cleanup_evidence_age_days,
            checks=checks,
        ),
    ]
    failed = not blocked and not all(threshold_results)
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
    retention_parameters_blocked, retention_parameters_failed, retention_parameter_values = (
        _validate_retention_parameters(data, checks)
    )
    metrics_blocked, metrics_failed, metric_values = _validate_metrics(data, checks, thresholds)

    metrics = {
        "requiredChecks": len(REQUIRED_CHECKS),
        "engineeringRequiredChecks": len(ENGINEERING_REQUIRED_CHECKS),
        "metricCount": len(REQUIRED_METRICS),
        "values": metric_values,
        "retentionParameters": retention_parameter_values,
    }

    if (
        not privacy_ok
        or not structural_ok
        or not boundary_fatal_ok
        or checks_failed
        or retention_parameters_failed
        or metrics_failed
    ):
        status = "fail"
    elif (
        not environment_ok
        or not boundary_all_ok
        or checks_blocked
        or retention_parameters_blocked
        or metrics_blocked
    ):
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
            "gcompComplianceGateOnly": True,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
            "rawPromptIncluded": False,
            "rawResponseIncluded": False,
            "secretsIncluded": False,
            "unredactedPersonalDataIncluded": False,
            "legalAdviceClaimed": False,
            "legalAcceptanceClaimed": False,
            "productionLegalGoClaimed": False,
            "ownerLegalTrackNotificationPresent": True,
            "retentionDurationsParametric": True,
            "retentionDefaultsFailClosed": True,
            "retentionOwnerProvenanceRequiredWhenValuesSupplied": True,
            "consentDefaultRequired": True,
            "deletionPipelineDefaultEnabled": True,
            "retentionDurationsHardcoded": False,
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
    parser.add_argument("--min-consent-coverage", type=_unit_rate, default=1.0)
    parser.add_argument("--min-retention-policy-coverage", type=_unit_rate, default=1.0)
    parser.add_argument("--min-access-audit-coverage", type=_unit_rate, default=0.95)
    parser.add_argument("--min-deletion-export-coverage", type=_unit_rate, default=1.0)
    parser.add_argument("--min-redaction-coverage", type=_unit_rate, default=1.0)
    parser.add_argument("--max-data-subject-response-days", type=_positive_float, default=30.0)
    parser.add_argument("--max-legal-hold-drill-age-days", type=_positive_float, default=90.0)
    parser.add_argument("--max-db-cleanup-evidence-age-days", type=_positive_float, default=30.0)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    thresholds = Thresholds(
        min_consent_coverage=args.min_consent_coverage,
        min_retention_policy_coverage=args.min_retention_policy_coverage,
        min_access_audit_coverage=args.min_access_audit_coverage,
        min_deletion_export_coverage=args.min_deletion_export_coverage,
        min_redaction_coverage=args.min_redaction_coverage,
        max_data_subject_response_days=args.max_data_subject_response_days,
        max_legal_hold_drill_age_days=args.max_legal_hold_drill_age_days,
        max_db_cleanup_evidence_age_days=args.max_db_cleanup_evidence_age_days,
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
