#!/usr/bin/env python3
"""Validate Faz 24 WG-B+ I7 app-mTLS evidence.

The I7 gate proves that the Denetim data-plane is reachable only through
application-layer mTLS with client authentication and redacted metadata. The
verifier is intentionally profile-aware:

- live-stt-preflight proves the 8243 live-stt path needed before #188/#182.
- prod-gate proves the broader I7 production-gate surface.

It does not enable direct-STT, send raw audio, or prove transcript e2e.
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


SCHEMA_VERSION = "faz24.i7.app-mtls.evidence.v1"

PROFILE_REQUIRED_CHECKS = {
    "live-stt-preflight": [
        "wg-route-to-denetim",
        "tcp-8243-reachable",
        "tls-server-identity-verified",
        "mtls-valid-client-accepted",
        "mtls-no-client-rejected",
        "mtls-wrong-client-rejected",
        "redaction-no-audio-transcript",
    ],
    "prod-gate": [
        "wg-route-to-denetim",
        "tcp-8243-reachable",
        "tcp-8343-reachable",
        "tls-server-identity-verified",
        "mtls-valid-client-accepted",
        "mtls-no-client-rejected",
        "mtls-wrong-client-rejected",
        "meeting-ai-mtls-valid-client-accepted",
        "request-audit-emitted",
        "plaintext-bypass-closed",
        "cert-rotation-drill",
        "failure-drill-fail-fast",
        "redaction-no-audio-transcript",
    ],
}

PROFILE_REQUIRED_SERVICES = {
    "live-stt-preflight": {"live-stt"},
    "prod-gate": {"live-stt", "meeting-ai"},
}

SERVICE_PORTS = {
    "live-stt": 8243,
    "meeting-ai": 8343,
}

REDACTION_FLAGS = [
    "secretMaterialIncluded",
    "privateKeyIncluded",
    "rawCommandOutputIncluded",
    "rawPacketCaptureIncluded",
    "rawAudioIncluded",
    "rawTranscriptIncluded",
]

COMMON_BOUNDARY_FALSE = [
    "directSttEnabled",
    "computePlaneAuditProven",
    "directAudioE2eProven",
    "desktopMicLoopbackProven",
    "productionReady",
]

FORBIDDEN_KEY_NAMES = {
    "password",
    "passwd",
    "pwd",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "bearer",
    "jwt",
    "cookie",
    "client_secret",
    "secret",
    "secret_id",
    "private_key",
    "privatekey",
    "raw_key",
    "rawkey",
    "pem",
    "cert_pem",
    "certpem",
    "certificate_pem",
    "certificatepem",
    "key_pem",
    "keypem",
    "private_key_pem",
    "privatekeypem",
    "raw_output",
    "rawoutput",
    "command_output",
    "commandoutput",
    "command_line",
    "commandline",
    "packet_capture",
    "packetcapture",
    "pcap",
    "audio",
    "audio_bytes",
    "audiobytes",
    "audio_base64",
    "audiobase64",
    "raw_audio",
    "rawaudio",
    "transcript",
    "transcript_text",
    "transcripttext",
    "segments",
    "destination_url",
    "destinationurl",
    "transcribe_url",
    "transcribeurl",
    "url",
}

SECRET_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"-----BEGIN CERTIFICATE-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\bAuthorization\s*:", re.IGNORECASE),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
]

UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,128}$")
SAFE_SUMMARY_RE = re.compile(r"^[A-Za-z0-9 .,;:@/_()+=#-]{1,220}$")
HASH_RE = re.compile(r"^[0-9a-f]{16}([0-9a-f]{48})?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FAILURE_CLASS_RE = re.compile(
    r"^(tls_client_certificate_required|tls_bad_certificate|tls_unknown_ca|"
    r"tls_hostname_mismatch|connection_reset|connection_timeout|http_401_403)$"
)


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
            yield from iter_values(child, child_path)


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
            findings.append(Finding("forbidden_key", f"{path}: key '{key}' is not allowed"))
            continue
        if isinstance(value, str):
            for pattern in SECRET_VALUE_PATTERNS:
                if pattern.search(value):
                    findings.append(
                        Finding("secret_like_value", f"{path}: value matches secret/raw-cert pattern")
                    )
                    break
    return findings


def require_bool(findings: list[Finding], label: str, value: Any, expected: bool) -> None:
    if value is not expected:
        findings.append(Finding("boolean_value", f"{label}: must be {str(expected).lower()}"))


def require_safe_name(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str) or not SAFE_NAME_RE.match(value):
        findings.append(Finding("safe_name", f"{label}: must be 1-128 safe chars"))


def require_summary(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str) or not SAFE_SUMMARY_RE.match(value):
        findings.append(Finding("summary_shape", f"{label}: must be bounded metadata text"))


def require_timestamp(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.match(value):
        findings.append(Finding("timestamp_format", f"{label}: must use UTC format YYYY-MM-DDTHH:MM:SSZ"))


def require_hash(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str) or not HASH_RE.match(value):
        findings.append(Finding("hash_shape", f"{label}: must be 16 or 64 lowercase hex chars"))


def require_sha256(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str) or not SHA256_RE.match(value):
        findings.append(Finding("sha256_shape", f"{label}: must be 64 lowercase hex chars"))


def require_ip(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str):
        findings.append(Finding("ip_shape", f"{label}: must be an IP string"))
        return
    try:
        ipaddress.ip_address(value)
    except ValueError:
        findings.append(Finding("ip_shape", f"{label}: must be a valid IP address"))


def require_relative_ref(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        findings.append(Finding("evidence_ref", f"{label}: must be a non-empty relative path"))
        return
    parts = re.split(r"[\\/]+", value)
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value) or ".." in parts:
        findings.append(Finding("evidence_ref", f"{label}: must stay under protectedEvidencePath"))
    if "\n" in value or len(value) > 220:
        findings.append(Finding("evidence_ref", f"{label}: must be single-line and <= 220 chars"))


def validate_top_level(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    if data.get("schemaVersion") != SCHEMA_VERSION:
        findings.append(Finding("schema_version", f"schemaVersion must be '{SCHEMA_VERSION}'"))
    if data.get("status") != "pass":
        findings.append(Finding("status", "status must be 'pass'"))
    if data.get("tokenIncluded") is not False:
        findings.append(Finding("token_included", "tokenIncluded must be false"))
    require_timestamp(findings, "collectedAt", data.get("collectedAt"))

    profile = data.get("evidenceProfile")
    if profile not in PROFILE_REQUIRED_CHECKS:
        findings.append(
            Finding(
                "evidence_profile",
                f"evidenceProfile must be one of {', '.join(sorted(PROFILE_REQUIRED_CHECKS))}",
            )
        )

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


def validate_boundaries(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    profile = data.get("evidenceProfile")
    boundaries = data.get("boundaries")
    if not isinstance(boundaries, dict):
        return [Finding("boundaries", "boundaries must be an object")]

    for key in COMMON_BOUNDARY_FALSE:
        if boundaries.get(key) is not False:
            findings.append(Finding("boundary", f"boundaries.{key} must be false"))

    if boundaries.get("liveSttAppMtlsPreflightProven") is not True:
        findings.append(
            Finding("boundary", "boundaries.liveSttAppMtlsPreflightProven must be true")
        )

    if profile == "live-stt-preflight":
        require_bool(findings, "boundaries.meetingAiAppMtlsProven", boundaries.get("meetingAiAppMtlsProven"), False)
        require_bool(findings, "boundaries.i7ProdGateProven", boundaries.get("i7ProdGateProven"), False)
    elif profile == "prod-gate":
        require_bool(findings, "boundaries.meetingAiAppMtlsProven", boundaries.get("meetingAiAppMtlsProven"), True)
        require_bool(findings, "boundaries.i7ProdGateProven", boundaries.get("i7ProdGateProven"), True)

    return findings


def validate_topology(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    topology = data.get("topology")
    if not isinstance(topology, dict):
        return [Finding("topology", "topology must be an object")]

    require_safe_name(findings, "topology.source", topology.get("source"))
    require_safe_name(findings, "topology.wgInterface", topology.get("wgInterface"))
    require_ip(findings, "topology.sourceWgIp", topology.get("sourceWgIp"))
    require_ip(findings, "topology.denetimWgIp", topology.get("denetimWgIp"))
    if topology.get("dnsName") not in (None, ""):
        require_safe_name(findings, "topology.dnsName", topology.get("dnsName"))

    return findings


def validate_pki(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    pki = data.get("pki")
    if not isinstance(pki, dict):
        return [Finding("pki", "pki must be an object")]

    require_safe_name(findings, "pki.authority", pki.get("authority"))
    require_sha256(findings, "pki.caBundleSha256", pki.get("caBundleSha256"))
    require_sha256(findings, "pki.serverCertFingerprintSha256", pki.get("serverCertFingerprintSha256"))
    require_sha256(findings, "pki.clientCertFingerprintSha256", pki.get("clientCertFingerprintSha256"))

    server_dns = pki.get("serverCertSanDns")
    if not isinstance(server_dns, list) or not server_dns:
        findings.append(Finding("pki_san", "pki.serverCertSanDns must be a non-empty list"))
    else:
        for index, value in enumerate(server_dns):
            require_safe_name(findings, f"pki.serverCertSanDns[{index}]", value)

    server_ips = pki.get("serverCertSanIps")
    if not isinstance(server_ips, list) or not server_ips:
        findings.append(Finding("pki_san", "pki.serverCertSanIps must be a non-empty list"))
    else:
        for index, value in enumerate(server_ips):
            require_ip(findings, f"pki.serverCertSanIps[{index}]", value)

    return findings


def validate_valid_probe(findings: list[Finding], label: str, probe: Any) -> None:
    if not isinstance(probe, dict):
        findings.append(Finding("probe", f"{label}: must be an object"))
        return

    if probe.get("status") != "pass":
        findings.append(Finding("probe_status", f"{label}.status must be pass"))
    require_timestamp(findings, f"{label}.observedAt", probe.get("observedAt"))
    require_bool(findings, f"{label}.tlsVerified", probe.get("tlsVerified"), True)
    require_bool(findings, f"{label}.clientCertificatePresented", probe.get("clientCertificatePresented"), True)
    require_bool(findings, f"{label}.accepted", probe.get("accepted"), True)
    http_status = probe.get("httpStatus")
    if not isinstance(http_status, int) or not 200 <= http_status <= 399:
        findings.append(Finding("probe_http_status", f"{label}.httpStatus must be 2xx/3xx"))
    require_relative_ref(findings, f"{label}.evidenceRef", probe.get("evidenceRef"))


def validate_rejection_probe(findings: list[Finding], label: str, probe: Any) -> None:
    if not isinstance(probe, dict):
        findings.append(Finding("probe", f"{label}: must be an object"))
        return

    if probe.get("status") != "pass":
        findings.append(Finding("probe_status", f"{label}.status must be pass"))
    require_timestamp(findings, f"{label}.observedAt", probe.get("observedAt"))
    require_bool(findings, f"{label}.rejected", probe.get("rejected"), True)
    failure_class = probe.get("failureClass")
    if not isinstance(failure_class, str) or not FAILURE_CLASS_RE.match(failure_class):
        findings.append(Finding("failure_class", f"{label}.failureClass is unsupported"))
    require_relative_ref(findings, f"{label}.evidenceRef", probe.get("evidenceRef"))


def validate_services(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    profile = data.get("evidenceProfile")
    services = data.get("services")
    if not isinstance(services, list) or not services:
        return [Finding("services", "services must be a non-empty list")]

    seen: set[str] = set()
    for index, service in enumerate(services):
        label = f"services[{index}]"
        if not isinstance(service, dict):
            findings.append(Finding("service_shape", f"{label}: must be an object"))
            continue

        name = service.get("name")
        if name not in SERVICE_PORTS:
            findings.append(Finding("service_name", f"{label}.name is unsupported"))
            continue
        if name in seen:
            findings.append(Finding("service_duplicate", f"duplicate service {name}"))
        seen.add(name)

        endpoint = service.get("endpoint")
        if not isinstance(endpoint, dict):
            findings.append(Finding("endpoint", f"{label}.endpoint must be an object"))
        else:
            require_safe_name(findings, f"{label}.endpoint.host", endpoint.get("host"))
            require_ip(findings, f"{label}.endpoint.wgIp", endpoint.get("wgIp"))
            expected_port = SERVICE_PORTS[name]
            if endpoint.get("port") != expected_port:
                findings.append(
                    Finding("endpoint_port", f"{label}.endpoint.port must be {expected_port}")
                )
            if endpoint.get("path") not in ("/health", "/transcribe", "/"):
                findings.append(
                    Finding("endpoint_path", f"{label}.endpoint.path must be /health, /transcribe, or /")
                )

        validate_valid_probe(findings, f"{label}.validClientProbe", service.get("validClientProbe"))
        validate_rejection_probe(findings, f"{label}.noClientCertProbe", service.get("noClientCertProbe"))
        validate_rejection_probe(findings, f"{label}.wrongClientCertProbe", service.get("wrongClientCertProbe"))

    required = PROFILE_REQUIRED_SERVICES.get(str(profile), set())
    missing = sorted(required - seen)
    for name in missing:
        findings.append(Finding("service_missing", f"missing required service '{name}' for {profile}"))

    if profile == "live-stt-preflight" and "meeting-ai" in seen:
        findings.append(
            Finding(
                "service_scope",
                "live-stt-preflight evidence must not include meeting-ai; use prod-gate profile",
            )
        )

    return findings


def validate_checks(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    profile = data.get("evidenceProfile")
    checks = data.get("checks")
    if not isinstance(checks, list):
        return [Finding("checks", "checks must be a list")]

    seen: set[str] = set()
    for index, check in enumerate(checks):
        label = f"checks[{index}]"
        if not isinstance(check, dict):
            findings.append(Finding("check_shape", f"{label}: must be an object"))
            continue
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id:
            findings.append(Finding("check_id", f"{label}.id must be non-empty"))
            continue
        if check_id in seen:
            findings.append(Finding("check_duplicate", f"duplicate check id '{check_id}'"))
        seen.add(check_id)

        if check.get("status") != "pass":
            findings.append(Finding("check_status", f"{label}.status must be pass"))
        require_timestamp(findings, f"{label}.observedAt", check.get("observedAt"))
        require_summary(findings, f"{label}.summary", check.get("summary"))
        require_relative_ref(findings, f"{label}.evidenceRef", check.get("evidenceRef"))

        if "evidenceHash" in check:
            require_hash(findings, f"{label}.evidenceHash", check.get("evidenceHash"))

    for required_id in PROFILE_REQUIRED_CHECKS.get(str(profile), []):
        if required_id not in seen:
            findings.append(
                Finding(
                    "check_missing",
                    f"missing required check '{required_id}' for profile '{profile}'",
                )
            )

    return findings


def validate_prod_sections(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    profile = data.get("evidenceProfile")

    if profile != "prod-gate":
        for section in ("requestAudit", "rotation", "failureDrill", "plaintextBypass"):
            value = data.get(section)
            if value not in (None, {}):
                findings.append(
                    Finding("profile_scope", f"{section} belongs to prod-gate evidence only")
                )
        return findings

    request_audit = data.get("requestAudit")
    if not isinstance(request_audit, dict):
        findings.append(Finding("request_audit", "requestAudit must be an object"))
    else:
        require_bool(findings, "requestAudit.emitted", request_audit.get("emitted"), True)
        require_bool(findings, "requestAudit.correlationPropagated", request_audit.get("correlationPropagated"), True)
        require_bool(findings, "requestAudit.clientCertIdentityLogged", request_audit.get("clientCertIdentityLogged"), True)
        require_bool(findings, "requestAudit.rawAudioLogged", request_audit.get("rawAudioLogged"), False)
        require_bool(findings, "requestAudit.rawTranscriptLogged", request_audit.get("rawTranscriptLogged"), False)
        require_relative_ref(findings, "requestAudit.evidenceRef", request_audit.get("evidenceRef"))

    rotation = data.get("rotation")
    if not isinstance(rotation, dict):
        findings.append(Finding("rotation", "rotation must be an object"))
    else:
        require_bool(findings, "rotation.tested", rotation.get("tested"), True)
        require_bool(findings, "rotation.newClientCertAccepted", rotation.get("newClientCertAccepted"), True)
        require_bool(findings, "rotation.oldClientCertRejected", rotation.get("oldClientCertRejected"), True)
        require_relative_ref(findings, "rotation.evidenceRef", rotation.get("evidenceRef"))

    failure_drill = data.get("failureDrill")
    if not isinstance(failure_drill, dict):
        findings.append(Finding("failure_drill", "failureDrill must be an object"))
    else:
        require_bool(findings, "failureDrill.mtlsFailureFailFast", failure_drill.get("mtlsFailureFailFast"), True)
        require_bool(findings, "failureDrill.wgDownFailFast", failure_drill.get("wgDownFailFast"), True)
        require_relative_ref(findings, "failureDrill.evidenceRef", failure_drill.get("evidenceRef"))

    plaintext = data.get("plaintextBypass")
    if not isinstance(plaintext, dict):
        findings.append(Finding("plaintext_bypass", "plaintextBypass must be an object"))
    else:
        require_bool(findings, "plaintextBypass.closed", plaintext.get("closed"), True)
        require_bool(findings, "plaintextBypass.externalPlaintextReachable", plaintext.get("externalPlaintextReachable"), False)
        require_relative_ref(findings, "plaintextBypass.evidenceRef", plaintext.get("evidenceRef"))

    return findings


def validate_evidence(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(validate_no_leaks(data))
    findings.extend(validate_top_level(data))
    findings.extend(validate_boundaries(data))
    findings.extend(validate_topology(data))
    findings.extend(validate_pki(data))
    findings.extend(validate_services(data))
    findings.extend(validate_checks(data))
    findings.extend(validate_prod_sections(data))
    return findings


def write_summary(path: Path, data: dict[str, Any], findings: list[Finding]) -> None:
    summary = {
        "schemaVersion": "faz24.i7.app-mtls.verifier.v1",
        "status": "pass" if not findings else "fail",
        "findingCount": len(findings),
        "evidenceProfile": data.get("evidenceProfile"),
        "serviceNames": [
            service.get("name")
            for service in data.get("services", [])
            if isinstance(service, dict) and isinstance(service.get("name"), str)
        ],
        "tokenIncluded": False,
        "findings": [{"code": finding.code, "message": finding.message} for finding in findings],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_json", type=Path, help="Path to metadata-only I7 app-mTLS evidence JSON")
    parser.add_argument("--summary-json", type=Path, help="Optional path for machine-readable verification summary")
    args = parser.parse_args(argv)

    data, load_findings = load_json(args.evidence_json)
    if data is None:
        findings = load_findings
        if args.summary_json:
            write_summary(args.summary_json, {}, findings)
        for finding in findings:
            print(f"{finding.code}: {finding.message}", file=sys.stderr)
        return 2

    findings = validate_evidence(data)
    if args.summary_json:
        write_summary(args.summary_json, data, findings)

    if findings:
        print("Faz24 I7 app-mTLS evidence: FAIL", file=sys.stderr)
        for finding in findings:
            print(f"- {finding.code}: {finding.message}", file=sys.stderr)
        return 1

    services = ",".join(
        service["name"] for service in data["services"] if isinstance(service, dict)
    )
    print("Faz24 I7 app-mTLS evidence: PASS")
    print(f"- evidenceProfile={data['evidenceProfile']}")
    print(f"- services={services}")
    print(f"- denetimWgIp={data['topology']['denetimWgIp']}")
    print("- tokenIncluded=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
