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


SCHEMA_VERSION = "faz24.wg-bplus.i6.pod-cidr-wg-masq.v3"
VERIFICATION_SCHEMA_VERSION = "faz24.wg-bplus.i6.pod-cidr-wg-masq-evidence-verification.v3"
OWNED_NAT_CHAIN = "K3D_WG_MASQ_NAT"

# Canonical pinned probe artifact — MUST match the collect workflow's PROBE_IMAGE and
# the collector's EXPECTED_PROBE_IMAGE. The runtime image DIGEST is compared to the
# requested digest (D30: a moving tag / a merely-present imageID is not proof).
EXPECTED_PROBE_IMAGE = "busybox@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662"

# Extract an exact sha256:<64hex> digest (no loose substring).
IMAGE_DIGEST_RE = re.compile(r"sha256:([0-9a-f]{64})(?![0-9a-f])")

# Only an installed, root-owned script run under sudo is authoritative. The
# `sudo-canonical` (running the user-writable checkout as root) and `direct`
# (non-root) modes are NOT authoritative.
AUTHORITATIVE_EXECUTION_MODES = {"sudo-installed"}

# Versioned rollback mechanism id — must match the collector/host-rule + historical evidence.
ROLLBACK_MECHANISM_VERSION = "k3d-wg-masq.rollback.v2"

REQUIRED_CHECK_IDS = [
    "cluster-identity-bound",
    "effective-cluster-cidr-matches-config",
    "node-pod-cidrs-within-cluster-cidr",
    "host-owned-chain-authority",
    "peer-route-is-wireguard-path",
    "pod-to-wg-peer-tcp-connect",
    "snat-rule-counter-traversal",
    "reboot-persistence",
    "drift-detect",
    "rollback-defined",
    "no-broad-lan-nat",
    "daemonset-not-assumed",
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
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

# Same positive belt policy the collector enforces; re-declared here so the
# verifier is an INDEPENDENT authority (it must not trust the collector's own
# beltPolicyOk flag).
CONTEXT_CIDR_POLICY = {
    "k3d-test": "10.44.0.0/16",
    "k3d-prod": "10.42.0.0/16",
}
# I6 acceptance-grade minimum fresh TCP connects. Rejects 0/1/2 as vacuous.
MIN_PROBE_ATTEMPTS = 3


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
    require_cidr(findings, "topology.clusterCIDR", topology.get("clusterCIDR"))

    node_cidrs = topology.get("nodePodCIDRs")
    if not isinstance(node_cidrs, list) or not node_cidrs:
        findings.append(Finding("node_pod_cidrs", "topology.nodePodCIDRs must be a non-empty list"))
    else:
        for index, node_cidr in enumerate(node_cidrs):
            require_cidr(findings, f"topology.nodePodCIDRs[{index}]", node_cidr)

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
    if mechanism.get("ownedNatChain") != OWNED_NAT_CHAIN:
        findings.append(Finding("owned_nat_chain", f"mechanism.ownedNatChain must be '{OWNED_NAT_CHAIN}'"))
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


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _norm_cidr(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError:
        return None
    if network.version != 4:
        return None
    return str(network)


def _subnet_of(child: Any, parent: Any) -> bool:
    if not isinstance(child, str) or not isinstance(parent, str):
        return False
    try:
        return ipaddress.ip_network(child).subnet_of(ipaddress.ip_network(parent))
    except (ValueError, TypeError):
        return False


def _norm_ip(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _ip_in_cidr(ip: Any, cidr: Any) -> bool:
    if not isinstance(ip, str) or not isinstance(cidr, str):
        return False
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr)
    except (ValueError, TypeError):
        return False


def _image_digest(ref: Any) -> str | None:
    """Return the canonical `sha256:<64hex>` from any image ref form, else None.

    Exact 64 hex only (no loose substring: a longer hex run does not match).
    """
    if not isinstance(ref, str):
        return None
    match = IMAGE_DIGEST_RE.search(ref)
    if not match:
        return None
    return f"sha256:{match.group(1)}"


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(HASH_RE.match(value))


def _is_plain_int(value: Any) -> bool:
    """True only for real ints, never bool.

    Guards against the type-confusion bypass where ``True``/``False`` satisfy
    ``isinstance(x, int)`` and compare equal to 1/0 (so a bool counter/exit-code
    could otherwise pass an arithmetic or ``== 0`` check).
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_octal_mode(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        return int(value, 8)
    except ValueError:
        return None


def validate_v2_check_semantics(data: dict[str, Any]) -> list[Finding]:
    """Independently re-derive every v2 check from collector.* + topology metadata.

    ``status == "pass"`` on a check remains NECESSARY (enforced by validate_checks)
    but is NOT SUFFICIENT. This layer recomputes each pass predicate from the raw
    metadata and rejects evidence whose declared pass contradicts what the metadata
    actually says — closing the v1 false-positive structure. Fail-closed: any
    missing/None/wrong-typed field yields a Finding.
    """
    findings: list[Finding] = []

    def fail(check_id: str, message: str) -> None:
        findings.append(Finding("check_semantic", f"{check_id}: {message}"))

    collector = _obj(data.get("collector"))
    topology = _obj(data.get("topology"))
    mechanism = _obj(data.get("mechanism"))
    rollback = _obj(data.get("rollback"))

    cluster_cidr = topology.get("clusterCIDR")
    wg_interface = topology.get("wgInterface")
    context = topology.get("clusterName")

    # 1) cluster-identity-bound
    ci = _obj(collector.get("clusterIdentity"))
    cid = "cluster-identity-bound"
    if ci.get("bound") is not True:
        fail(cid, "collector.clusterIdentity.bound must be true")
    if ci.get("uidResolved") is not True:
        fail(cid, "uidResolved must be true")
    if not _is_hash(ci.get("clusterUidHash")):
        fail(cid, "clusterUidHash must be a sha256 hash")
    if not _is_hash(ci.get("apiServerHostHash")):
        fail(cid, "apiServerHostHash must be a sha256 hash")
    if not _nonempty_str(ci.get("nodeName")):
        fail(cid, "nodeName must be non-empty")
    if not _nonempty_str(ci.get("dockerNetwork")):
        fail(cid, "dockerNetwork must be non-empty")
    # Positive belt: the context MUST be a supported one; an unknown clusterName
    # is rejected rather than silently skipping the policy.
    if not isinstance(context, str) or context not in CONTEXT_CIDR_POLICY:
        fail(cid, "clusterName must be a supported context (k3d-test or k3d-prod)")
    elif _norm_cidr(cluster_cidr) != CONTEXT_CIDR_POLICY[context]:
        fail(cid, f"belt policy: {context} requires clusterCIDR {CONTEXT_CIDR_POLICY[context]}")

    # 2) effective-cluster-cidr-matches-config
    ec = _obj(collector.get("effectiveCidr"))
    cid = "effective-cluster-cidr-matches-config"
    eff = _norm_cidr(ec.get("effectiveClusterCidr"))
    conf = _norm_cidr(ec.get("configuredClusterCidr"))
    if eff is None or conf is None:
        fail(cid, "effective and configured cluster CIDR must both be valid CIDRs")
    elif eff != conf:
        fail(cid, "effectiveClusterCidr must equal configuredClusterCidr")
    if ec.get("sourcesConflict") is not False:
        fail(cid, "sourcesConflict must be false")
    # The "effective" CIDR must be backed by at least one VALID observed source
    # (config.yaml or /proc/1/cmdline); a self-declared effective with no valid
    # observation is rejected, and any present source must equal effective.
    cs = ec.get("configSourceCidr")
    ms = ec.get("cmdlineSourceCidr")
    ncs = _norm_cidr(cs) if cs is not None else None
    nms = _norm_cidr(ms) if ms is not None else None
    if cs is not None and ncs is None:
        fail(cid, "configSourceCidr present but invalid")
    if ms is not None and nms is None:
        fail(cid, "cmdlineSourceCidr present but invalid")
    if ncs is None and nms is None:
        fail(cid, "at least one valid observed CIDR source (config.yaml or cmdline) is required")
    if ncs is not None and eff is not None and ncs != eff:
        fail(cid, "configSourceCidr must equal effectiveClusterCidr")
    if nms is not None and eff is not None and nms != eff:
        fail(cid, "cmdlineSourceCidr must equal effectiveClusterCidr")
    if ncs is not None and nms is not None and ncs != nms:
        fail(cid, "observed CIDR sources disagree")

    # 3) node-pod-cidrs-within-cluster-cidr (recompute containment from topology)
    cid = "node-pod-cidrs-within-cluster-cidr"
    node_cidrs = topology.get("nodePodCIDRs")
    if not isinstance(node_cidrs, list) or not node_cidrs:
        fail(cid, "topology.nodePodCIDRs must be a non-empty list")
    else:
        if _norm_cidr(cluster_cidr) is None:
            fail(cid, "topology.clusterCIDR must be a valid CIDR for containment")
        for node_cidr in node_cidrs:
            if _norm_cidr(node_cidr) is None:
                fail(cid, f"node podCIDR {node_cidr!r} is not a valid CIDR")
            elif not _subnet_of(node_cidr, cluster_cidr):
                fail(cid, f"node podCIDR {node_cidr} is not contained within clusterCIDR {cluster_cidr}")

    # 4) host-owned-chain-authority
    hc = _obj(collector.get("hostOwnedChain"))
    cid = "host-owned-chain-authority"
    if hc.get("scriptFound") is not True:
        fail(cid, "scriptFound must be true")
    if not _is_plain_int(hc.get("checkExitCode")) or hc.get("checkExitCode") != 0:
        fail(cid, "checkExitCode must be integer 0")
    # Only an installed, root-owned, non-writable-by-others script run under sudo is
    # authoritative (running the checkout as root is a TOCTOU / priv-esc gap).
    if hc.get("executionMode") not in AUTHORITATIVE_EXECUTION_MODES:
        fail(cid, "executionMode must be 'sudo-installed' (installed root-owned script only)")
    if hc.get("installedProvided") is not True:
        fail(cid, "installedProvided must be true (an installed root-owned script is required)")
    if not _is_plain_int(hc.get("installedScriptOwnerUid")) or hc.get("installedScriptOwnerUid") != 0:
        fail(cid, "installedScriptOwnerUid must be integer 0 (root-owned)")
    mode_bits = _parse_octal_mode(hc.get("installedScriptMode"))
    if mode_bits is None:
        fail(cid, "installedScriptMode must be an octal permission string")
    elif (mode_bits & 0o022) != 0:
        fail(cid, "installedScriptMode must not be group- or world-writable")
    canonical_sha = hc.get("canonicalSha256")
    installed_sha = hc.get("installedSha256")
    if not (isinstance(canonical_sha, str) and HEX64_RE.match(canonical_sha)):
        fail(cid, "canonicalSha256 must be 64 lowercase hex chars")
    if not (isinstance(installed_sha, str) and HEX64_RE.match(installed_sha)):
        fail(cid, "installedSha256 must be 64 lowercase hex chars")
    if isinstance(canonical_sha, str) and isinstance(installed_sha, str) and installed_sha != canonical_sha:
        fail(cid, "installedSha256 must equal canonicalSha256")
    if hc.get("shaMatches") is not True:
        fail(cid, "shaMatches must be true")

    # 5) peer-route-is-wireguard-path
    pr = _obj(collector.get("peerRoute"))
    cid = "peer-route-is-wireguard-path"
    if pr.get("routeResolved") is not True:
        fail(cid, "routeResolved must be true")
    if not (isinstance(pr.get("routeDevice"), str) and pr.get("routeDevice") == wg_interface):
        fail(cid, "routeDevice must equal topology.wgInterface")
    if pr.get("allowedIpsCoverPeer") is not True:
        fail(cid, "allowedIpsCoverPeer must be true")
    if not _is_hash(pr.get("peerFingerprint")):
        fail(cid, "peerFingerprint must be a sha256 hash")

    # 6) pod-to-wg-peer-tcp-connect (v3: re-derive from RAW pod metadata; do NOT
    #    trust the informational podWithinClusterCidr / podOnTargetNode booleans)
    pp = _obj(collector.get("podProbe"))
    cid = "pod-to-wg-peer-tcp-connect"
    identity_node = _obj(collector.get("clusterIdentity")).get("nodeName")

    if pp.get("matchCount") != 1:
        fail(cid, "matchCount must be exactly 1 (single label-selected probe pod)")
    if pp.get("phase") != "Running":
        fail(cid, "pod phase must be Running")
    if pp.get("ready") is not True:
        fail(cid, "pod Ready condition must be true")
    if pp.get("deletionTimestampPresent") is not False:
        fail(cid, "pod must not have a deletionTimestamp")
    if pp.get("hostNetwork") is not False:
        fail(cid, "pod must not use hostNetwork")

    pod_ip = _norm_ip(pp.get("podIP"))
    if pod_ip is None:
        fail(cid, "podIP must be a valid IP address")
    elif not _ip_in_cidr(pod_ip, cluster_cidr):
        fail(cid, "podIP must be within topology.clusterCIDR")

    pod_node = pp.get("nodeName")
    if not _nonempty_str(pod_node):
        fail(cid, "pod nodeName must be non-empty")
    elif not _nonempty_str(identity_node) or pod_node != identity_node:
        fail(cid, "pod nodeName must equal clusterIdentity.nodeName")

    # Cryptographic digest binding: the pod's REQUESTED image must be exactly the
    # pinned probe artifact, and the RUNTIME image digest must equal the requested
    # digest (a moving tag / a merely-present imageID is not proof).
    image_ref = pp.get("imageRef")
    req_digest = _image_digest(image_ref)
    run_digest = _image_digest(pp.get("runtimeImageID"))
    if image_ref != EXPECTED_PROBE_IMAGE:
        fail(cid, "probe imageRef must be the canonical expected probe artifact")
    if req_digest is None:
        fail(cid, "imageRef must be digest-pinned")
    if run_digest is None:
        fail(cid, "runtimeImageID must contain a sha256 digest")
    if req_digest is not None and run_digest is not None and req_digest != run_digest:
        fail(cid, "runtime image digest must equal requested image digest")

    pp_attempts = pp.get("attempts")
    pp_success = pp.get("successCount")
    if not _is_plain_int(pp_attempts) or pp_attempts < MIN_PROBE_ATTEMPTS:
        fail(cid, f"attempts must be an int >= {MIN_PROBE_ATTEMPTS} (non-vacuous acceptance grade)")
    if not _is_plain_int(pp_success) or pp_success != pp_attempts:
        fail(cid, "successCount must equal attempts")
    if pp.get("ncMissing") is not False:
        fail(cid, "ncMissing must be false")
    # attemptExitCodes is MANDATORY: without the per-attempt evidence the verifier
    # would be trusting the self-declared successCount.
    codes = pp.get("attemptExitCodes")
    if not isinstance(codes, list):
        fail(cid, "attemptExitCodes must be a list")
    elif not _is_plain_int(pp_attempts) or len(codes) != pp_attempts:
        fail(cid, "len(attemptExitCodes) must equal attempts")
    elif not all(_is_plain_int(code) and code == 0 for code in codes):
        fail(cid, "every attempt exit code must be integer 0")
    else:
        recomputed = sum(1 for code in codes if code == 0)
        if not _is_plain_int(pp_success) or pp_success != recomputed:
            fail(cid, "successCount must equal recomputed count of zero exit codes")

    # 7) snat-rule-counter-traversal (+ cross-check with check 6)
    ct = _obj(collector.get("counterTraversal"))
    cid = "snat-rule-counter-traversal"
    if ct.get("ruleStable") is not True:
        fail(cid, "ruleStable must be true")
    if ct.get("counterNotReset") is not True:
        fail(cid, "counterNotReset must be true")
    counter_before = ct.get("counterBefore")
    counter_after = ct.get("counterAfter")
    counter_delta = ct.get("counterDelta")
    if not _is_plain_int(counter_before) or counter_before < 0:
        fail(cid, "counterBefore must be an int >= 0")
    if not _is_plain_int(counter_after):
        fail(cid, "counterAfter must be an int")
    if _is_plain_int(counter_before) and _is_plain_int(counter_after) and counter_after < counter_before:
        fail(cid, "counterAfter must be >= counterBefore")
    if not _is_plain_int(counter_delta):
        fail(cid, "counterDelta must be an int")
    elif _is_plain_int(counter_before) and _is_plain_int(counter_after) and counter_delta != counter_after - counter_before:
        fail(cid, "counterDelta must equal counterAfter - counterBefore")
    fp_before = ct.get("ruleFingerprintBeforeHash")
    fp_after = ct.get("ruleFingerprintAfterHash")
    if not _is_hash(fp_before) or not _is_hash(fp_after):
        fail(cid, "ruleFingerprintBeforeHash and ruleFingerprintAfterHash must both be hashes")
    elif fp_before != fp_after:
        fail(cid, "ruleFingerprintBeforeHash must equal ruleFingerprintAfterHash")
    ct_attempts = ct.get("attempts")
    ct_success = ct.get("successCount")
    if not _is_plain_int(ct_attempts) or ct_attempts < MIN_PROBE_ATTEMPTS:
        fail(cid, f"attempts must be an int >= {MIN_PROBE_ATTEMPTS}")
    if not _is_plain_int(ct_success) or ct_success != ct_attempts:
        fail(cid, "successCount must equal attempts")
    if _is_plain_int(counter_delta) and _is_plain_int(ct_attempts) and counter_delta < ct_attempts:
        fail(cid, "counterDelta must be >= attempts")
    # cross-check the two checks agree and the TCP gate actually passed
    if _is_plain_int(pp_attempts) and _is_plain_int(ct_attempts) and pp_attempts != ct_attempts:
        fail(cid, "podProbe.attempts must equal counterTraversal.attempts")
    if _is_plain_int(pp_success) and _is_plain_int(ct_success) and pp_success != ct_success:
        fail(cid, "podProbe.successCount must equal counterTraversal.successCount")
    if _is_plain_int(pp_success) and _is_plain_int(pp_attempts) and pp_success != pp_attempts:
        fail(cid, "TCP gate: podProbe.successCount must equal podProbe.attempts")

    # 8) reboot-persistence
    systemd = _obj(collector.get("systemd"))
    cid = "reboot-persistence"
    if not (systemd.get("enabled") is True and systemd.get("active") is True and systemd.get("hasExecStart") is True):
        fail(cid, "systemd unit must be enabled, active, and expose ExecStart")

    # 9) drift-detect
    cid = "drift-detect"
    if not (systemd.get("driftTimerActive") is True or systemd.get("driftTimerEnabled") is True):
        fail(cid, "drift timer must be active or enabled")

    # 10) rollback-defined — re-derive from raw. The scratch drill proves the chain-body
    # primitives (necessary), but is NOT sufficient: it must be bound to the SAME installed
    # root-owned script as host-owned-chain, AND a genuine historical LIVE rollback (which
    # actually exercised the built-in POSTROUTING/FORWARD jump removal) must be present.
    cid = "rollback-defined"
    if systemd.get("hasExecStop") is not True:
        fail(cid, "systemd ExecStop must be present")
    drill = _obj(collector.get("rollbackDrill"))
    hoc = _obj(collector.get("hostOwnedChain"))
    ci = _obj(collector.get("clusterIdentity"))
    # -- drill self-consistency --
    if drill.get("executionMode") != "sudo-installed":
        fail(cid, "rollbackDrill.executionMode must be 'sudo-installed'")
    if drill.get("applyOk") is not True:
        fail(cid, "rollbackDrill.applyOk must be true")
    if drill.get("rollbackOk") is not True:
        fail(cid, "rollbackDrill.rollbackOk must be true")
    if drill.get("chainsAbsentAfter") is not True:
        fail(cid, "rollbackDrill.chainsAbsentAfter must be true")
    if drill.get("scope") != "detached-scratch-chain":
        fail(cid, "rollbackDrill.scope must be 'detached-scratch-chain'")
    if drill.get("rollbackMechanismVersion") != ROLLBACK_MECHANISM_VERSION:
        fail(cid, f"rollbackDrill.rollbackMechanismVersion must be '{ROLLBACK_MECHANISM_VERSION}'")
    drill_sha = drill.get("scriptSha256")
    if not (isinstance(drill_sha, str) and HEX64_RE.match(drill_sha)):
        fail(cid, "rollbackDrill.scriptSha256 must be 64 lowercase hex chars")
    if not _is_plain_int(drill.get("installedScriptOwnerUid")) or drill.get("installedScriptOwnerUid") != 0:
        fail(cid, "rollbackDrill.installedScriptOwnerUid must be integer 0 (root-owned)")
    drill_mode = _parse_octal_mode(drill.get("installedScriptMode"))
    if drill_mode is None:
        fail(cid, "rollbackDrill.installedScriptMode must be an octal permission string")
    elif (drill_mode & 0o022) != 0:
        fail(cid, "rollbackDrill.installedScriptMode must not be group- or world-writable")
    # -- cross-check: the SAME installed script really ran both drill + host-owned check --
    hoc_installed = hoc.get("installedSha256")
    hoc_canonical = hoc.get("canonicalSha256")
    if not (isinstance(drill_sha, str) and drill_sha == hoc_installed and drill_sha == hoc_canonical):
        fail(cid, "rollbackDrill.scriptSha256 must equal hostOwnedChain installed + canonical sha256")
    if drill.get("executionMode") != hoc.get("executionMode"):
        fail(cid, "rollbackDrill.executionMode must equal hostOwnedChain.executionMode")
    if drill.get("installedScriptOwnerUid") != hoc.get("installedScriptOwnerUid"):
        fail(cid, "rollbackDrill.installedScriptOwnerUid must equal hostOwnedChain.installedScriptOwnerUid")
    if drill.get("installedScriptMode") != hoc.get("installedScriptMode"):
        fail(cid, "rollbackDrill.installedScriptMode must equal hostOwnedChain.installedScriptMode")
    # -- required historical LIVE rollback (scratch drill alone is not sufficient) --
    hist = _obj(collector.get("historicalLiveRollback"))
    if not hist:
        fail(cid, "historicalLiveRollback evidence is required (the scratch drill does not exercise the built-in jump removal)")
    else:
        if hist.get("executionVerified") is not True:
            fail(cid, "historicalLiveRollback.executionVerified must be true")
        if hist.get("liveOwnedChainsExercised") is not True:
            fail(cid, "historicalLiveRollback.liveOwnedChainsExercised must be true")
        if hist.get("builtinHooksExercised") is not True:
            fail(cid, "historicalLiveRollback.builtinHooksExercised must be true")
        if hist.get("rollbackResult") != "pass":
            fail(cid, "historicalLiveRollback.rollbackResult must be 'pass'")
        if hist.get("rollbackMechanismVersion") != drill.get("rollbackMechanismVersion"):
            fail(cid, "historicalLiveRollback.rollbackMechanismVersion must match rollbackDrill")
        if hist.get("targetClusterHash") != ci.get("clusterUidHash"):
            fail(cid, "historicalLiveRollback.targetClusterHash must match clusterIdentity.clusterUidHash")
        if hist.get("nodeName") != ci.get("nodeName"):
            fail(cid, "historicalLiveRollback.nodeName must match clusterIdentity.nodeName")
        if hist.get("wgInterface") != topology.get("wgInterface"):
            fail(cid, "historicalLiveRollback.wgInterface must match topology.wgInterface")

    # 11) no-broad-lan-nat
    broad = _obj(collector.get("broadNat"))
    cid = "no-broad-lan-nat"
    if broad.get("queryable") is not True:
        fail(cid, "nat table must be queryable")
    if broad.get("broadNatDetected") is not False:
        fail(cid, "broadNatDetected must be false")

    # 12) daemonset-not-assumed
    cid = "daemonset-not-assumed"
    if mechanism.get("daemonSetAssumed") is not False:
        fail(cid, "mechanism.daemonSetAssumed must be false")

    return findings


def validate_evidence(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(validate_no_leaks(data))
    findings.extend(validate_required_metadata(data))
    findings.extend(validate_topology(data))
    findings.extend(validate_mechanism(data))
    findings.extend(validate_drift_and_rollback(data))
    findings.extend(validate_checks(data))
    findings.extend(validate_v2_check_semantics(data))
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
        "schemaVersion": VERIFICATION_SCHEMA_VERSION,
        "status": "pass" if not findings else "fail",
        "findingCount": len(findings),
        "findings": [finding.__dict__ for finding in findings],
    }
    if data:
        topology = data.get("topology") if isinstance(data.get("topology"), dict) else {}
        mechanism = data.get("mechanism") if isinstance(data.get("mechanism"), dict) else {}
        summary["clusterName"] = topology.get("clusterName")
        summary["clusterCIDR"] = topology.get("clusterCIDR")
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
    print(f"- clusterCIDR={summary.get('clusterCIDR')}")
    print(f"- wgInterface={summary.get('wgInterface')}")
    print(f"- mechanismType={summary.get('mechanismType')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
