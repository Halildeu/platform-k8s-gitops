#!/usr/bin/env python3
"""Verify Faz 24 rollup evidence for platform-k8s-gitops#1615.

This verifier accepts a redacted metadata envelope that summarizes the Faz 24
engineering/product gates. It is intentionally fail-closed: a single accepted
sub-gate such as G-CAP cannot make the whole rollup pass while direct-STT,
desktop capture, I3, full I7, G-OPS, G-COMP, pilot quality, or product smoke
evidence is still missing.
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


EVIDENCE_SCHEMA_VERSION = "faz24.readinessRollupEvidence.v1"
VERIFIER_SCHEMA_VERSION = "faz24.readinessRollupVerifier.v1"

REQUIRED_GATES: dict[str, str] = {
    "foundation_deploy": "meeting/transcript/audit foundation deploy",
    "recorder_edge_lifecycle": "recorder edge lifecycle",
    "gcap_aggregate": "aggregate capture reliability gate",
    "desktop_capture": "real desktop microphone plus loopback capture",
    "direct_stt_preflight": "direct-STT pre-flag mTLS preflight",
    "direct_stt_e2e": "direct-STT transcript e2e",
    "compute_plane_audit": "same-session compute-plane audit",
    "wg_bplus_i3": "WG-B+ I3 management audit and drift monitor",
    "wg_bplus_i6": "WG-B+ I6 pod-CIDR to WireGuard MASQ",
    "i7_live_stt_app_mtls": "I7 live-stt app-mTLS preflight",
    "i7_full_prod_gate": "I7 full app-mTLS product gate",
    "gops_operability": "G-OPS on-prem operability",
    "gcomp_engineering": "G-COMP engineering compliance controls",
    "retention_lifecycle": "retention and deletion lifecycle evidence",
    "gwer_der_pilot": "pilot WER/DER quality evidence",
    "gint_pilot": "pilot intelligence faithfulness evidence",
    "glat_cost_pilot": "pilot latency and cost evidence",
    "browser_smoke": "end-to-end browser or client smoke",
}

GATE_STATUS_VALUES = {"pass", "blocked", "fail", "pending", "not_applicable"}

BOUNDARY_EXPECTATIONS: dict[str, bool] = {
    "allRequiredGatesAccepted": True,
    "secretsIncluded": False,
    "rawAudioIncluded": False,
    "rawTranscriptIncluded": False,
    "rawPromptIncluded": False,
    "rawResponseIncluded": False,
    "unredactedPersonalDataIncluded": False,
    "directClientToStt": False,
    "legalAdviceClaimed": False,
    "legalAcceptanceClaimed": False,
    "productionLegalGoClaimed": False,
    "runtimeMutationPerformedByVerifier": False,
    "productionReady": False,
}

FORBIDDEN_TRUE_BOUNDARIES = {
    key for key, expected in BOUNDARY_EXPECTATIONS.items() if expected is False
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

SECRET_VALUE_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bAuthorization\s*:", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"-----BEGIN CERTIFICATE-----"),
    re.compile(r"\bpassword\s*[:=]", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b(?:\+?90|0)?5\d{9}\b"),
]

SAFE_EVIDENCE_REF_RE = re.compile(
    r"^(github|github-actions|artifact|operator|protected|runbook)://"
    r"[A-Za-z0-9_.:@/#?=&%+-]{3,240}$"
)
ISSUE_REF_RE = re.compile(
    r"^(platform-k8s-gitops|platform-ai|platform-backend|platform-desktop|platform-mobile|platform-web)#\d+$"
)
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@dataclass
class Check:
    name: str
    passed: bool
    message: str
    severity: str = "blocked"


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


def _add(
    checks: list[Check],
    name: str,
    passed: bool,
    message: str,
    severity: str = "blocked",
) -> None:
    checks.append(Check(name=name, passed=passed, message=message, severity=severity))


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


def _validate_no_sensitive_content(data: dict[str, Any], checks: list[Check]) -> None:
    findings: list[str] = []
    for path, key, value in _iter_values(data):
        if key is not None and _normalized_key(key) in SENSITIVE_KEY_NAMES:
            findings.append(f"{path}: forbidden key '{key}'")
            continue
        if isinstance(value, str):
            for pattern in SECRET_VALUE_PATTERNS:
                if pattern.search(value):
                    findings.append(f"{path}: secret-like or personal value")
                    break

    _add(
        checks,
        "no_sensitive_content",
        not findings,
        "no sensitive keys, token-shaped values, raw media, or direct personal data found"
        if not findings
        else "; ".join(findings[:8]),
        "fail",
    )


def _validate_top_level(data: dict[str, Any], checks: list[Check]) -> None:
    _add(
        checks,
        "schema_version",
        data.get("schemaVersion") == EVIDENCE_SCHEMA_VERSION,
        f"schemaVersion must be {EVIDENCE_SCHEMA_VERSION}",
        "fail",
    )
    _add(
        checks,
        "issue_ref",
        data.get("issue") == "platform-k8s-gitops#1615",
        "issue must be platform-k8s-gitops#1615",
    )
    _add(
        checks,
        "status_pass",
        data.get("status") == "pass",
        "top-level status must be pass for a rollup acceptance claim",
    )
    _add(
        checks,
        "token_not_included",
        data.get("tokenIncluded") is False,
        "top-level tokenIncluded must be false",
        "fail",
    )
    failures = data.get("failures")
    _add(
        checks,
        "failures_empty",
        failures in (None, []),
        "failures must be absent or empty for a rollup acceptance claim",
    )
    generated_at = data.get("generatedAt")
    _add(
        checks,
        "generated_at",
        isinstance(generated_at, str) and UTC_RE.match(generated_at) is not None,
        "generatedAt must use UTC YYYY-MM-DDTHH:MM:SSZ",
    )


def _gate_list(data: dict[str, Any], checks: list[Check]) -> list[dict[str, Any]]:
    gates = data.get("gates")
    if not isinstance(gates, list):
        _add(checks, "gates_shape", False, "gates must be an array")
        return []
    _add(checks, "gates_shape", True, "gates is an array")
    return [gate for gate in gates if isinstance(gate, dict)]


def _validate_gates(data: dict[str, Any], checks: list[Check]) -> tuple[list[str], list[str]]:
    gate_objects = _gate_list(data, checks)
    names = [gate.get("name") for gate in gate_objects if isinstance(gate.get("name"), str)]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    _add(
        checks,
        "gate_names_unique",
        not duplicate_names,
        "gate names must be unique"
        if not duplicate_names
        else f"duplicate gate names: {', '.join(duplicate_names)}",
    )

    present = set(names)
    required = set(REQUIRED_GATES)
    missing = sorted(required - present)
    unknown = sorted(present - required)
    _add(
        checks,
        "required_gates_present",
        not missing,
        "all required Faz 24 gates are present"
        if not missing
        else f"missing required gates: {', '.join(missing)}",
    )
    _add(
        checks,
        "unknown_gates_absent",
        not unknown,
        "no unknown gate names"
        if not unknown
        else f"unknown gate names: {', '.join(unknown)}",
    )

    failed_or_open: list[str] = []
    blocked: list[str] = []
    for gate in gate_objects:
        name = gate.get("name")
        if not isinstance(name, str) or name not in REQUIRED_GATES:
            continue

        status = gate.get("status")
        status_valid = status in GATE_STATUS_VALUES
        _add(
            checks,
            f"gate_{name}_status_valid",
            status_valid,
            f"{name} status must be one of {sorted(GATE_STATUS_VALUES)}",
        )
        status_pass = status == "pass"
        _add(
            checks,
            f"gate_{name}_status_pass",
            status_pass,
            f"{name} status must be pass",
        )
        if not status_pass:
            failed_or_open.append(name)
            blocked.append(name)

        accepted = gate.get("acceptedByVerifier") is True
        _add(
            checks,
            f"gate_{name}_accepted_by_verifier",
            accepted,
            f"{name} acceptedByVerifier must be true",
        )
        if not accepted and name not in blocked:
            blocked.append(name)

        evidence_ref = gate.get("evidenceRef")
        evidence_ref_ok = (
            isinstance(evidence_ref, str)
            and SAFE_EVIDENCE_REF_RE.match(evidence_ref) is not None
        )
        _add(
            checks,
            f"gate_{name}_evidence_ref",
            evidence_ref_ok,
            f"{name} evidenceRef must use an approved redacted evidence scheme",
        )
        if not evidence_ref_ok and name not in blocked:
            blocked.append(name)

        issue_ref = gate.get("issueRef")
        issue_ref_ok = isinstance(issue_ref, str) and ISSUE_REF_RE.match(issue_ref) is not None
        _add(
            checks,
            f"gate_{name}_issue_ref",
            issue_ref_ok,
            f"{name} issueRef must look like platform-ai#123 or platform-k8s-gitops#123",
        )
        if not issue_ref_ok and name not in blocked:
            blocked.append(name)

        observed_at = gate.get("observedAt")
        observed_at_ok = isinstance(observed_at, str) and UTC_RE.match(observed_at) is not None
        _add(
            checks,
            f"gate_{name}_observed_at",
            observed_at_ok,
            f"{name} observedAt must use UTC YYYY-MM-DDTHH:MM:SSZ",
        )
        if not observed_at_ok and name not in blocked:
            blocked.append(name)

        summary = gate.get("summary")
        summary_ok = (
            isinstance(summary, str)
            and 8 <= len(summary) <= 240
            and "\n" not in summary
            and "\r" not in summary
        )
        _add(
            checks,
            f"gate_{name}_summary",
            summary_ok,
            f"{name} summary must be a bounded single-line string",
        )
        if not summary_ok and name not in blocked:
            blocked.append(name)

    return sorted(set(failed_or_open)), sorted(set(blocked + missing))


def _validate_boundaries(data: dict[str, Any], checks: list[Check]) -> None:
    boundaries = data.get("boundaries")
    if not isinstance(boundaries, dict):
        _add(checks, "boundaries_shape", False, "boundaries must be an object", "fail")
        return
    _add(checks, "boundaries_shape", True, "boundaries is an object")

    for key, expected in BOUNDARY_EXPECTATIONS.items():
        actual = boundaries.get(key)
        severity = "fail" if key in FORBIDDEN_TRUE_BOUNDARIES else "blocked"
        _add(
            checks,
            f"boundary_{key}",
            actual is expected,
            f"boundaries.{key} must be {str(expected).lower()}",
            severity,
        )


def _derive_status(checks: list[Check]) -> str:
    if all(check.passed for check in checks):
        return "pass"
    if any(not check.passed and check.severity == "fail" for check in checks):
        return "fail"
    return "blocked"


def _report(
    *,
    status: str,
    checks: list[Check],
    evidence: dict[str, Any] | None,
    open_gates: list[str] | None = None,
    blocked_gates: list[str] | None = None,
) -> dict[str, Any]:
    failures = [check.message for check in checks if not check.passed]
    return {
        "schemaVersion": VERIFIER_SCHEMA_VERSION,
        "evidenceSchemaVersion": evidence.get("schemaVersion") if evidence else None,
        "status": status,
        "generatedAt": _utc_now(),
        "issue": "platform-k8s-gitops#1615",
        "tokenIncluded": False,
        "total": len(checks),
        "passed": sum(1 for check in checks if check.passed),
        "openGates": open_gates or [],
        "blockedGates": blocked_gates or [],
        "requiredGates": sorted(REQUIRED_GATES),
        "checks": [
            {
                "name": check.name,
                "passed": check.passed,
                "message": check.message,
                "severity": check.severity,
            }
            for check in checks
        ],
        "failures": failures,
        "boundaries": {
            "rollupVerifierOnly": True,
            "runtimeMutationPerformed": False,
            "productionReadyClaimed": False,
            "legalAcceptanceClaimed": False,
        },
    }


def verify(evidence: dict[str, Any]) -> dict[str, Any]:
    checks: list[Check] = []
    _validate_no_sensitive_content(evidence, checks)
    _validate_top_level(evidence, checks)
    open_gates, blocked_gates = _validate_gates(evidence, checks)
    _validate_boundaries(evidence, checks)
    status = _derive_status(checks)
    return _report(
        status=status,
        checks=checks,
        evidence=evidence,
        open_gates=open_gates,
        blocked_gates=blocked_gates,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-file",
        type=Path,
        default=None,
        help="Path to redacted Faz 24 rollup evidence JSON; stdin when omitted.",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="Optional path to write verifier JSON report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence, error = _load_evidence(args.evidence_file)
    if error:
        report = _report(
            status="error",
            checks=[Check(name="load_json", passed=False, message=error, severity="fail")],
            evidence=None,
        )
        text = json.dumps(report, indent=2, sort_keys=True)
        if args.output_file:
            args.output_file.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 2

    assert evidence is not None
    report = verify(evidence)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output_file:
        args.output_file.write_text(text + "\n", encoding="utf-8")
    print(text)

    if report["status"] == "pass":
        return 0
    if report["status"] == "blocked":
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
