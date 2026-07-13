#!/usr/bin/env python3
"""Validate Faz 24 #2321 Meeting-AI gateway certificate rotation fire-drill evidence.

The private Meeting-AI result gateway (staging-sw) rotates its server leaf
through a scoped Vault token, atomically swaps the ``tls/current`` pointer and
only then reloads Caddy. ``deploy/staging-sw/meeting-ai-private-gateway`` ships
the rotation script, the eight-hourly systemd timer and the node-exporter
textfile metrics; ``kustomize/base/monitoring/meeting-ai-gateway-rule.yaml``
ships the four Prometheus alerts.

The rotation *fire drill* is an open #2321 acceptance residual. A single
successful rotation is not acceptance: the drill must also prove the
fail-closed rollback and the alert fire/clear cycle. This verifier gates the
redacted, metadata-only fire-drill evidence envelope so a weak or falsely
positive run cannot be accepted. It follows the same D29-layered contract as
the other Faz 24 verifiers:

- Up:        rotation telemetry present, all four gauges exposed.
- Functional: successful rotation issued a fresh 24h leaf, atomically swapped
              the pointer, reloaded the gateway and served an uninterrupted
              client-authenticated ``/healthz`` on the new leaf.
- Secured:   an induced reload failure rolled the pointer back to the previous
             leaf without an outage, drove ``last_run_success`` to ``0`` and
             fired ``MeetingAIGatewayCertificateRotationFailed``, which then
             cleared after recovery; no key/token/PEM material leaks.

This verifier never mutates Vault, Kubernetes, Caddy, systemd or GitHub and it
does not prove private-listener activation, the mTLS negative matrix, the JWT
claim matrix, GPU outbox drain, the Electron product path or production
readiness. Those remain independent #2321 gates.
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


EVIDENCE_SCHEMA_VERSION = "faz24.meetingAiCertRotationDrillEvidence.v1"
VERIFIER_SCHEMA_VERSION = "faz24.meetingAiCertRotationDrillVerifier.v1"

EXPECTED_ISSUE = "platform-k8s-gitops#2321"
EXPECTED_SCOPE = "test"
EXPECTED_GATEWAY_SERVICE = "meeting-ai-private-gateway.service"
EXPECTED_ROTATION_TIMER = "meeting-ai-server-cert-rotation.timer"
EXPECTED_ROTATION_SCHEDULE_HOURS = 8
EXPECTED_SERVER_MOUNT = "pki_meeting_ai_server"
EXPECTED_ISSUE_ROLE = "staging-gateway"
EXPECTED_COMMON_NAME = "meeting-ai-gateway.internal"
EXPECTED_LEAF_TTL_HOURS = 24
EXPECTED_LEAF_CHECKEND_HOURS = 12
EXPECTED_ROTATION_POLICY = "meeting-ai-gateway-server"
EXPECTED_RENEW_INCREMENT_HOURS = 24
EXPECTED_PROM_RULE = "meeting-ai-gateway"
REQUIRED_FAILURE_ALERT = "MeetingAIGatewayCertificateRotationFailed"

ALLOWED_VAULT_TRANSPORT = {"container", "https"}
ALLOWED_FAILURE_CLASSES = {
    "reload_failure",
    "vault_issue_failure",
    "leaf_validation_failure",
}
ALLOWED_ALERTS = {
    "MeetingAIGatewayCertificateRotationFailed",
    "MeetingAIGatewayCertificateRotationStale",
    "MeetingAIGatewayCertificateExpiring",
    "MeetingAIGatewayTelemetryAbsent",
}
REQUIRED_METRIC_NAMES = {
    "meeting_ai_gateway_rotation_last_attempt_timestamp_seconds",
    "meeting_ai_gateway_rotation_last_success_timestamp_seconds",
    "meeting_ai_gateway_rotation_last_run_success",
    "meeting_ai_gateway_certificate_not_after_timestamp_seconds",
}

UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,160}$")
METRIC_NAME_RE = re.compile(r"^meeting_ai_gateway_[a-z0-9_]{1,80}$")
ALERT_NAME_RE = re.compile(r"^MeetingAIGateway[A-Za-z]{1,60}$")
ISSUED_VERSION_RE = re.compile(r"^issued-\d{8}T\d{6}Z-[0-9a-f]{8}$")
CAMEL_BOUNDARY_1_RE = re.compile(r"(.)([A-Z][a-z]+)")
CAMEL_BOUNDARY_2_RE = re.compile(r"([a-z0-9])([A-Z])")

FORBIDDEN_KEY_NAMES = {
    "access_token",
    "api_key",
    "auth_token",
    "authorization",
    "bearer",
    "ca_key",
    "cert_pem",
    "certificate",
    "certificate_pem",
    "client_key",
    "client_secret",
    "cookie",
    "credential",
    "command_line",
    "command_output",
    "issuing_ca",
    "jwt",
    "key_pem",
    "leaf_key",
    "packet_capture",
    "password",
    "pcap",
    "pem",
    "private_key",
    "private_key_pem",
    "raw_command_output",
    "raw_output",
    "raw_request",
    "raw_response",
    "refresh_token",
    "root_token",
    "secret",
    "secret_id",
    "server_key",
    "session_token",
    "vault_token",
}
FORBIDDEN_KEY_NAMES_COMPACT = {name.replace("_", "") for name in FORBIDDEN_KEY_NAMES}

SECRET_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"-----BEGIN CERTIFICATE-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\bAuthorization\s*:", re.IGNORECASE),
    re.compile(r"\bhvs\.[A-Za-z0-9._-]{12,}\b"),
    re.compile(r"\bs\.[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:https?|wss?)://[^\s\"']+", re.IGNORECASE),
]

BOUNDARY_EXPECTATIONS = {
    "certRotationDrillProven": True,
    "privateListenerActivationProven": False,
    "mtlsNegativeMatrixProven": False,
    "jwtClaimMatrixProven": False,
    "outboxDrainProven": False,
    "electronProductPathProven": False,
    "productionReady": False,
    "rawKeyMaterialIncluded": False,
    "rawTokenIncluded": False,
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


def utc_timestamp(value: Any) -> bool:
    return isinstance(value, str) and bool(UTC_TIMESTAMP_RE.match(value))


def issued_version(value: Any) -> bool:
    return isinstance(value, str) and bool(ISSUED_VERSION_RE.match(value))


def validate_no_sensitive_content(data: dict[str, Any], checks: list[Check]) -> None:
    findings: list[str] = []
    for path, key, value in iter_values(data):
        if key is not None:
            normalized = normalized_key(key)
            if (
                normalized in FORBIDDEN_KEY_NAMES
                or normalized.replace("_", "") in FORBIDDEN_KEY_NAMES_COMPACT
            ):
                findings.append(f"{path}: forbidden key '{key}'")
                continue
        if isinstance(value, str):
            for pattern in SECRET_VALUE_PATTERNS:
                if pattern.search(value):
                    findings.append(
                        f"{path}: secret-like, token-like, or URL-like value"
                    )
                    break

    add(
        checks,
        "no_sensitive_content",
        not findings,
        "metadata-only evidence" if not findings else "; ".join(findings[:8]),
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
        "token_not_included",
        data.get("tokenIncluded") is False,
        "tokenIncluded must be false",
    )
    add(
        checks,
        "generated_at",
        utc_timestamp(data.get("generatedAt")),
        "generatedAt must use UTC YYYY-MM-DDTHH:MM:SSZ",
    )
    failures = data.get("failures")
    add(checks, "failures_empty", failures in (None, []), "failures must be absent or empty")


def validate_environment(data: dict[str, Any], checks: list[Check]) -> None:
    env = data.get("environment")
    if not isinstance(env, dict):
        add(checks, "environment_shape", False, "environment must be an object")
        return
    add(checks, "environment_host", safe_name(env.get("host")), "host must be bounded safe metadata")
    add(
        checks,
        "environment_scope",
        env.get("scope") == EXPECTED_SCOPE,
        f"scope must be {EXPECTED_SCOPE}; the fire drill is test-only",
    )
    add(
        checks,
        "environment_vault_transport",
        env.get("vaultTransport") in ALLOWED_VAULT_TRANSPORT,
        f"vaultTransport must be one of {sorted(ALLOWED_VAULT_TRANSPORT)}",
    )
    add(
        checks,
        "environment_gateway_service",
        env.get("gatewayService") == EXPECTED_GATEWAY_SERVICE,
        f"gatewayService must be {EXPECTED_GATEWAY_SERVICE}",
    )
    add(
        checks,
        "environment_rotation_timer",
        env.get("rotationTimer") == EXPECTED_ROTATION_TIMER,
        f"rotationTimer must be {EXPECTED_ROTATION_TIMER}",
    )
    add(
        checks,
        "environment_rotation_schedule_hours",
        as_int(env.get("rotationScheduleHours")) == EXPECTED_ROTATION_SCHEDULE_HOURS,
        f"rotationScheduleHours must be {EXPECTED_ROTATION_SCHEDULE_HOURS}",
    )


def validate_pki(data: dict[str, Any], checks: list[Check]) -> None:
    pki = data.get("pki")
    if not isinstance(pki, dict):
        add(checks, "pki_shape", False, "pki must be an object")
        return

    add(checks, "pki_server_mount", pki.get("serverMount") == EXPECTED_SERVER_MOUNT, f"serverMount must be {EXPECTED_SERVER_MOUNT}")
    add(checks, "pki_issue_role", pki.get("issueRole") == EXPECTED_ISSUE_ROLE, f"issueRole must be {EXPECTED_ISSUE_ROLE}")
    add(checks, "pki_common_name", pki.get("commonName") == EXPECTED_COMMON_NAME, f"commonName must be {EXPECTED_COMMON_NAME}")
    add(checks, "pki_leaf_ttl_hours", as_int(pki.get("leafTtlHours")) == EXPECTED_LEAF_TTL_HOURS, f"leafTtlHours must be {EXPECTED_LEAF_TTL_HOURS}")
    add(checks, "pki_fullchain_served", pki.get("fullchainServed") is True, "fullchainServed must be true (leaf + issuing CA)")
    add(
        checks,
        "pki_san_dns_gateway_internal",
        pki.get("sanDnsIncludesGatewayInternal") is True,
        "sanDnsIncludesGatewayInternal must be true",
    )

    new_fp = pki.get("newLeafFingerprintSha256")
    prev_fp = pki.get("previousLeafFingerprintSha256")
    add(checks, "pki_new_leaf_fingerprint", sha256(new_fp), "newLeafFingerprintSha256 must be a sha256 hex digest")
    add(checks, "pki_previous_leaf_fingerprint", sha256(prev_fp), "previousLeafFingerprintSha256 must be a sha256 hex digest")
    add(
        checks,
        "pki_leaf_fingerprint_rotated",
        sha256(new_fp) and sha256(prev_fp) and new_fp != prev_fp,
        "new leaf fingerprint must differ from the previous leaf",
    )

    scoped = pki.get("scopedToken")
    if not isinstance(scoped, dict):
        add(checks, "pki_scoped_token_shape", False, "pki.scopedToken must be an object")
        return
    add(checks, "pki_scoped_token_root_absent", scoped.get("rootTokenUsed") is False, "scopedToken.rootTokenUsed must be false")
    add(checks, "pki_scoped_token_policy", scoped.get("policy") == EXPECTED_ROTATION_POLICY, f"scopedToken.policy must be {EXPECTED_ROTATION_POLICY}")
    add(
        checks,
        "pki_scoped_token_renew_increment",
        as_int(scoped.get("renewIncrementHours")) == EXPECTED_RENEW_INCREMENT_HOURS,
        f"scopedToken.renewIncrementHours must be {EXPECTED_RENEW_INCREMENT_HOURS}",
    )
    add(
        checks,
        "pki_scoped_token_value_absent",
        scoped.get("tokenValueIncluded") is False,
        "scopedToken.tokenValueIncluded must be false",
    )


def validate_success_rotation(data: dict[str, Any], checks: list[Check]) -> None:
    success = data.get("successRotation")
    if not isinstance(success, dict):
        add(checks, "success_rotation_shape", False, "successRotation must be an object")
        return

    add(checks, "success_attempted", success.get("attempted") is True, "attempted must be true")
    add(checks, "success_succeeded", success.get("succeeded") is True, "succeeded must be true")
    add(checks, "success_atomic_pointer_swapped", success.get("atomicPointerSwapped") is True, "atomicPointerSwapped must be true")
    add(checks, "success_gateway_reloaded", success.get("gatewayReloaded") is True, "gatewayReloaded must be true")
    add(checks, "success_not_after_advanced", success.get("notAfterAdvanced") is True, "notAfterAdvanced must be true")
    add(
        checks,
        "success_leaf_checkend_hours",
        as_int(success.get("leafCheckendHours")) == EXPECTED_LEAF_CHECKEND_HOURS,
        f"leafCheckendHours must be {EXPECTED_LEAF_CHECKEND_HOURS}",
    )

    current_target = success.get("currentTarget")
    previous_target = success.get("previousTarget")
    add(checks, "success_current_target", issued_version(current_target), "currentTarget must match issued-<UTC>-<hex8>")
    add(
        checks,
        "success_previous_target",
        previous_target == "none" or issued_version(previous_target),
        "previousTarget must be 'none' or match issued-<UTC>-<hex8>",
    )
    add(
        checks,
        "success_target_rotated",
        previous_target == "none" or (issued_version(current_target) and current_target != previous_target),
        "currentTarget must differ from previousTarget",
    )

    retained = as_int(success.get("versionsRetained"))
    add(
        checks,
        "success_versions_retained",
        retained is not None and 1 <= retained <= 3,
        "versionsRetained must be 1..3 (active plus two prior versions)",
    )

    probe = success.get("uninterruptedHealthzProbe")
    if not isinstance(probe, dict):
        add(checks, "success_healthz_probe_shape", False, "uninterruptedHealthzProbe must be an object")
        return
    add(checks, "success_healthz_client_auth", probe.get("clientCertificateUsed") is True, "healthz probe clientCertificateUsed must be true")
    add(checks, "success_healthz_status", as_int(probe.get("httpStatus")) == 200, "healthz probe httpStatus must be 200")
    add(checks, "success_healthz_observed_at", utc_timestamp(probe.get("observedAt")), "healthz probe observedAt must be UTC")


def validate_telemetry(data: dict[str, Any], checks: list[Check]) -> None:
    telemetry = data.get("telemetry")
    if not isinstance(telemetry, dict):
        add(checks, "telemetry_shape", False, "telemetry must be an object")
        return

    add(checks, "telemetry_textfile_present", telemetry.get("textfilePresent") is True, "textfilePresent must be true")

    metrics = telemetry.get("metricsPresent")
    if not isinstance(metrics, list) or not all(isinstance(m, str) for m in metrics):
        add(checks, "telemetry_metrics_shape", False, "metricsPresent must be a list of metric names")
    else:
        bad = [m for m in metrics if not METRIC_NAME_RE.match(m)]
        add(checks, "telemetry_metric_name_shape", not bad, "metricsPresent entries must be meeting_ai_gateway_* names")
        missing = sorted(REQUIRED_METRIC_NAMES - set(metrics))
        add(
            checks,
            "telemetry_required_metrics",
            not missing,
            "metricsPresent must include all four rotation gauges"
            if not missing
            else f"missing metrics: {', '.join(missing)}",
        )

    add(checks, "telemetry_last_run_success_value", as_int(telemetry.get("lastRunSuccessValue")) == 1, "lastRunSuccessValue must be 1 after a successful rotation")
    add(checks, "telemetry_last_attempt_advanced", telemetry.get("lastAttemptAdvanced") is True, "lastAttemptAdvanced must be true")
    add(checks, "telemetry_last_success_advanced", telemetry.get("lastSuccessAdvanced") is True, "lastSuccessAdvanced must be true")


def validate_failure_drill(data: dict[str, Any], checks: list[Check]) -> None:
    drill = data.get("failureDrill")
    if not isinstance(drill, dict):
        add(checks, "failure_drill_shape", False, "failureDrill must be an object")
        return

    add(checks, "failure_induced", drill.get("induced") is True, "induced must be true")
    add(
        checks,
        "failure_class",
        drill.get("inducedFailureClass") in ALLOWED_FAILURE_CLASSES,
        f"inducedFailureClass must be one of {sorted(ALLOWED_FAILURE_CLASSES)}",
    )
    add(checks, "failure_pointer_rolled_back", drill.get("pointerRolledBack") is True, "pointerRolledBack must be true")
    add(checks, "failure_rolled_back_to_previous", drill.get("rolledBackToPreviousTarget") is True, "rolledBackToPreviousTarget must be true")
    add(
        checks,
        "failure_service_kept_serving",
        drill.get("serviceStayedServingPreviousCert") is True,
        "serviceStayedServingPreviousCert must be true (no outage)",
    )
    add(
        checks,
        "failure_last_run_success_zero",
        as_int(drill.get("lastRunSuccessValueDuringFailure")) == 0,
        "lastRunSuccessValueDuringFailure must be 0",
    )
    add(checks, "failure_new_version_removed", drill.get("newVersionRemovedOnFailure") is True, "newVersionRemovedOnFailure must be true")
    add(checks, "failure_post_drill_recovered", drill.get("postDrillRecovered") is True, "postDrillRecovered must be true")


def validate_alert_drill(data: dict[str, Any], checks: list[Check]) -> None:
    alert = data.get("alertDrill")
    if not isinstance(alert, dict):
        add(checks, "alert_drill_shape", False, "alertDrill must be an object")
        return

    add(
        checks,
        "alert_prometheus_rule",
        alert.get("prometheusRuleName") == EXPECTED_PROM_RULE,
        f"prometheusRuleName must be {EXPECTED_PROM_RULE}",
    )

    fired = alert.get("alertsFiredDuringFailure")
    if not isinstance(fired, list) or not fired or not all(isinstance(a, str) for a in fired):
        add(checks, "alert_fired_shape", False, "alertsFiredDuringFailure must be a non-empty list of alert names")
    else:
        bad_shape = [a for a in fired if not ALERT_NAME_RE.match(a)]
        add(checks, "alert_fired_name_shape", not bad_shape, "alertsFiredDuringFailure entries must be MeetingAIGateway* names")
        unknown = sorted(set(fired) - ALLOWED_ALERTS)
        add(
            checks,
            "alert_fired_known",
            not unknown,
            "alertsFiredDuringFailure must be a subset of the shipped alerts"
            if not unknown
            else f"unknown alerts: {', '.join(unknown)}",
        )
        add(
            checks,
            "alert_fired_required",
            REQUIRED_FAILURE_ALERT in fired,
            f"alertsFiredDuringFailure must include {REQUIRED_FAILURE_ALERT}",
        )

    add(
        checks,
        "alert_cleared_after_recovery",
        alert.get("alertsClearedAfterRecovery") is True,
        "alertsClearedAfterRecovery must be true",
    )


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
    validate_environment(data, checks)
    validate_pki(data, checks)
    validate_success_rotation(data, checks)
    validate_telemetry(data, checks)
    validate_failure_drill(data, checks)
    validate_alert_drill(data, checks)
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
    status = "PASS" if passed == len(checks) else "FAIL"
    print(f"\nFaz 24 Meeting-AI cert rotation drill evidence: {status} ({passed}/{len(checks)})")


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
