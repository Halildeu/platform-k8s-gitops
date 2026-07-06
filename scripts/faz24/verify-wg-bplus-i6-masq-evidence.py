#!/usr/bin/env python3
"""Validate Faz 24 WG-B+ I6 pod-CIDR to WireGuard MASQ evidence.

The I6 gate proves the pod-CIDR to WireGuard NAT path is host-managed,
drift-detectable, rollbackable, and not based on an assumed Kubernetes
DaemonSet. Evidence is metadata-only and must not carry command output,
secrets, packet captures, audio, or transcript content.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "faz24.wg-bplus.i6.pod-cidr-wg-masq.v1"

REQUIRED_CHECK_IDS = [
    "host-namespace-nat-rule-present",
    "pod-cidr-to-wg-masq-rule",
    "pod-to-platform-ai-http",
    "reboot-persistence",
    "drift-detect",
    "rollback-defined",
    "daemonset-not-assumed",
    "no-broad-lan-nat",
]

REDACTION_FLAGS = [
    "secretMaterialIncluded",
    "rawCommandOutputIncluded",
    "rawPacketCaptureIncluded",
    "rawAudioIncluded",
    "rawTranscriptIncluded",
]

FORBIDDEN_KEY_NAMES = {
    "password",
    "passwd",
    "pwd",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
    "secret_id",
    "private_key",
    "privatekey",
    "bearer",
    "jwt",
    "cookie",
    "raw_output",
    "rawoutput",
    "command_output",
    "commandoutput",
    "command_line",
    "commandline",
    "raw_command",
    "rawcommand",
    "packet_capture",
    "packetcapture",
    "pcap",
    "audio_bytes",
    "audiobytes",
    "audio_base64",
    "audiobase64",
    "transcript_text",
    "transcripttext",
}

SECRET_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
]

UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,96}$")
HASH_RE = re.compile(r"^[0-9a-f]{16}([0-9a-f]{48})?$")


@dataclass
class Finding:
    code: str
    message: str


def normalized_key(key: str) -> str:
    return key.replace("-", "_").replace(".", "_").strip().lower()


def iter_values(value: Any, path: str = "$") -> Iterable[tuple[str, str | None, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, key, child
            yield from iter_values(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield child_path, None, child


def load_json(path: Path) -> tuple[dict[str, Any] | None, list[Finding]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [Finding("json_parse", f"{path}: invalid JSON: {exc}")]
    except OSError as exc:
        return None, [Finding("json_read", f"{path}: cannot read file: {exc}")]

    if not isinstance(data, dict):
        return None, [Finding("json_shape", "top-level evidence must be a JSON object")]
    return data, []


def validate_no_leaks(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for path, key, value in iter_values(data):
        if key is not None and normalized_key(key) in FORBIDDEN_KEY_NAMES:
            findings.append(
                Finding(
                    "forbidden_key",
                    f"{path}: key '{key}' is not allowed in metadata-only evidence",
                )
            )
            continue

        if isinstance(value, str):
            for pattern in SECRET_VALUE_PATTERNS:
                if pattern.search(value):
                    findings.append(
                        Finding(
                            "secret_like_value",
                            f"{path}: value matches secret/token/private-key pattern",
                        )
                    )
                    break
    return findings


def require_bool(findings: list[Finding], label: str, value: Any, expected: bool) -> None:
    if value is not expected:
        findings.append(Finding("boolean_value", f"{label}: must be {str(expected).lower()}"))


def require_name(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str) or not NAME_RE.match(value):
        findings.append(Finding("name_shape", f"{label}: must be 1-96 safe name chars"))


def require_hash(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str) or not HASH_RE.match(value):
        findings.append(Finding("hash_shape", f"{label}: must be 16 or 64 lowercase hex chars"))


def require_timestamp(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.match(value):
        findings.append(Finding("timestamp_format", f"{label}: must use UTC format YYYY-MM-DDTHH:MM:SSZ"))


def require_relative_ref(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        findings.append(Finding("evidence_ref", f"{label}: must be a non-empty relative path"))
        return
    parts = re.split(r"[\\/]+", value)
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value) or ".." in parts:
        findings.append(Finding("evidence_ref", f"{label}: must stay under protectedEvidencePath"))
    if "\n" in value or len(value) > 220:
        findings.append(Finding("evidence_ref", f"{label}: must be single-line and <= 220 chars"))


def require_cidr(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str):
        findings.append(Finding("cidr_shape", f"{label}: must be a CIDR string"))
        return
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError:
        findings.append(Finding("cidr_shape", f"{label}: must be a valid CIDR"))
        return
    if network.version != 4:
        findings.append(Finding("cidr_shape", f"{label}: must be IPv4 CIDR"))
    if network.prefixlen < 12:
        findings.append(Finding("cidr_scope", f"{label}: prefix is too broad for this gate"))


def validate_required_metadata(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []

    if data.get("schemaVersion") != SCHEMA_VERSION:
        findings.append(Finding("schema_version", f"schemaVersion must be '{SCHEMA_VERSION}'"))

    require_timestamp(findings, "collectedAt", data.get("collectedAt"))

    if data.get("status") != "pass":
        findings.append(Finding("status", "status must be 'pass'"))

    protected_path = data.get("protectedEvidencePath")
    if not isinstance(protected_path, str) or not protected_path.strip():
        findings.append(Finding("required_field", "protectedEvidencePath must be a non-empty string"))

    redaction = data.get("redaction")
    if not isinstance(redaction, dict):
        findings.append(Finding("redaction", "redaction must be an object"))
    else:
        for flag in REDACTION_FLAGS:
            if redaction.get(flag) is not False:
                findings.append(Finding("redaction_flag", f"redaction.{flag} must be false"))

    return findings


def validate_topology(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    topology = data.get("topology")
    if not isinstance(topology, dict):
        return [Finding("topology", "topology must be an object")]

    require_name(findings, "topology.clusterName", topology.get("clusterName"))
    require_cidr(findings, "topology.podCIDR", topology.get("podCIDR"))
    if "serviceCIDR" in topology and topology.get("serviceCIDR") not in ("", None):
        require_cidr(findings, "topology.serviceCIDR", topology.get("serviceCIDR"))
    require_name(findings, "topology.wgInterface", topology.get("wgInterface"))

    target = topology.get("platformAiTarget")
    if not isinstance(target, dict):
        findings.append(Finding("platform_ai_target", "topology.platformAiTarget must be an object"))
    else:
        host = target.get("host")
        port = target.get("port")
        if not isinstance(host, str) or not host.strip() or len(host) > 128 or "\n" in host:
            findings.append(Finding("platform_ai_target", "platformAiTarget.host must be bounded"))
        if not isinstance(port, int) or not 1 <= port <= 65535:
            findings.append(Finding("platform_ai_target", "platformAiTarget.port must be 1-65535"))

    return findings


def validate_mechanism(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    mechanism = data.get("mechanism")
    if not isinstance(mechanism, dict):
        return [Finding("mechanism", "mechanism must be an object")]

    if mechanism.get("type") != "host-systemd-iptables":
        findings.append(Finding("mechanism_type", "mechanism.type must be 'host-systemd-iptables'"))
    require_bool(findings, "mechanism.managedOutsideCluster", mechanism.get("managedOutsideCluster"), True)
    require_bool(findings, "mechanism.daemonSetAssumed", mechanism.get("daemonSetAssumed"), False)
    require_name(findings, "mechanism.host", mechanism.get("host"))
    require_name(findings, "mechanism.systemdUnit", mechanism.get("systemdUnit"))
    if mechanism.get("iptablesTable") != "nat":
        findings.append(Finding("iptables_table", "mechanism.iptablesTable must be 'nat'"))
    if mechanism.get("iptablesChain") != "POSTROUTING":
        findings.append(Finding("iptables_chain", "mechanism.iptablesChain must be 'POSTROUTING'"))
    require_hash(findings, "mechanism.expectedRuleHash", mechanism.get("expectedRuleHash"))

    return findings


def validate_drift_and_rollback(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    mechanism = data.get("mechanism") if isinstance(data.get("mechanism"), dict) else {}
    mechanism_hash = mechanism.get("expectedRuleHash")
    drift = data.get("driftDetection")
    if not isinstance(drift, dict):
        findings.append(Finding("drift_detection", "driftDetection must be an object"))
    else:
        require_bool(findings, "driftDetection.enabled", drift.get("enabled"), True)
        if drift.get("mode") not in {"systemd-timer", "systemd-service", "cron", "manual-plus-alert"}:
            findings.append(Finding("drift_detection", "driftDetection.mode is not an accepted mode"))
        interval = drift.get("intervalMinutes")
        if not isinstance(interval, int) or not 1 <= interval <= 1440:
            findings.append(Finding("drift_detection", "driftDetection.intervalMinutes must be 1-1440"))
        require_hash(findings, "driftDetection.expectedRuleHash", drift.get("expectedRuleHash"))
        if mechanism_hash != drift.get("expectedRuleHash"):
            findings.append(
                Finding(
                    "drift_hash_mismatch",
                    "driftDetection.expectedRuleHash must match mechanism.expectedRuleHash",
                )
            )
        require_relative_ref(findings, "driftDetection.evidenceRef", drift.get("evidenceRef"))

    rollback = data.get("rollback")
    if not isinstance(rollback, dict):
        findings.append(Finding("rollback", "rollback must be an object"))
    else:
        require_bool(findings, "rollback.defined", rollback.get("defined"), True)
        require_bool(findings, "rollback.tested", rollback.get("tested"), True)
        require_hash(findings, "rollback.commandHash", rollback.get("commandHash"))
        require_relative_ref(findings, "rollback.evidenceRef", rollback.get("evidenceRef"))

    return findings


def validate_checks(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    checks = data.get("checks")
    if not isinstance(checks, list):
        return [Finding("checks", "checks must be a list")]

    by_id: dict[str, dict[str, Any]] = {}
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            findings.append(Finding("check_shape", f"checks[{index}] must be an object"))
            continue
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id.strip():
            findings.append(Finding("check_id", f"checks[{index}].id must be non-empty"))
            continue
        if check_id in by_id:
            findings.append(Finding("duplicate_check", f"duplicate check id '{check_id}'"))
        by_id[check_id] = check

    for required_id in REQUIRED_CHECK_IDS:
        check = by_id.get(required_id)
        if check is None:
            findings.append(Finding("missing_check", f"missing required check '{required_id}'"))
            continue

        if check.get("status") != "pass":
            findings.append(Finding("check_status", f"{required_id}: status must be 'pass'"))

        for field in ["observedAt", "summary", "evidenceRef"]:
            value = check.get(field)
            if not isinstance(value, str) or not value.strip():
                findings.append(Finding("check_required_field", f"{required_id}: {field} must be non-empty"))
            elif "\n" in value or len(value) > 220:
                findings.append(Finding("check_field_bounds", f"{required_id}: {field} must be single-line and <= 220 chars"))

        require_timestamp(findings, f"{required_id}.observedAt", check.get("observedAt"))
        require_relative_ref(findings, f"{required_id}.evidenceRef", check.get("evidenceRef"))

    return findings


def validate_evidence(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(validate_no_leaks(data))
    findings.extend(validate_required_metadata(data))
    findings.extend(validate_topology(data))
    findings.extend(validate_mechanism(data))
    findings.extend(validate_drift_and_rollback(data))
    findings.extend(validate_checks(data))
    return findings


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_json", type=Path)
    parser.add_argument("--summary-json", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    data, findings = load_json(args.evidence_json)
    if data is not None:
        findings.extend(validate_evidence(data))

    summary = {
        "schemaVersion": "faz24.wg-bplus.i6.masq-evidence-verification.v1",
        "status": "pass" if not findings else "fail",
        "findingCount": len(findings),
        "findings": [finding.__dict__ for finding in findings],
    }
    if data:
        topology = data.get("topology") if isinstance(data.get("topology"), dict) else {}
        mechanism = data.get("mechanism") if isinstance(data.get("mechanism"), dict) else {}
        summary["clusterName"] = topology.get("clusterName")
        summary["podCIDR"] = topology.get("podCIDR")
        summary["wgInterface"] = topology.get("wgInterface")
        summary["mechanismType"] = mechanism.get("type")

    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if findings:
        print("Faz24 WG-B+ I6 MASQ evidence: FAIL", file=sys.stderr)
        for finding in findings:
            print(f"- {finding.code}: {finding.message}", file=sys.stderr)
        return 1

    print("Faz24 WG-B+ I6 MASQ evidence: PASS")
    print(f"- clusterName={summary.get('clusterName')}")
    print(f"- podCIDR={summary.get('podCIDR')}")
    print(f"- wgInterface={summary.get('wgInterface')}")
    print(f"- mechanismType={summary.get('mechanismType')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
