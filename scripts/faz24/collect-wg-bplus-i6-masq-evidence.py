#!/usr/bin/env python3
"""Collect metadata-only Faz 24 WG-B+ I6 MASQ evidence on staging-sw (schema v2).

This collector is intentionally fail-closed. It may read host, systemd,
iptables, WireGuard, Docker and Kubernetes metadata, but it does not change host
iptables/nftables, WireGuard, Kubernetes objects, platform-ai or production
state. Raw command output is used only in memory for parsing and is not written
to the evidence JSON.

Schema v2 hardening (2026-07-12): the v1 tools green-lit a broken pod->WireGuard
path because they never bound the evidence to the *real* cluster the counter
belongs to, never proved the pod-origin TCP path actually traversed the owned
SNAT rule, and accepted a wrong ``--pod-cidr`` default. v2 binds cluster
identity, effective cluster CIDR, node podCIDR containment, the host-owned NAT
chain authority, the WireGuard peer route, a pod-origin TCP probe, and the owned
SNAT counter that WRAPS that probe. The counter alone is not sufficient: unless
the pod TCP connects actually succeed, the check fails.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


SCHEMA_VERSION = "faz24.wg-bplus.i6.pod-cidr-wg-masq.v3"

# v3 required checks. Every one must be status "pass" for evidence.status "pass".
# Only pod-to-wg-peer-tcp-connect's metadata + semantics change from v2 (Calico-safe
# label-selected probe pod + digest-pinned image); the other 11 ids are unchanged.
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

# Positive context -> cluster-cidr belt. A wrong default (prod 10.42 on the test
# node) was the 2026-07-12 I6 root cause; this rejects the mismatch before any
# node query even runs.
CONTEXT_CIDR_POLICY = {
    "k3d-test": "10.44.0.0/16",
    "k3d-prod": "10.42.0.0/16",
}

# The host-owned NAT chain that k3d-wg-masq-host-rule.sh materializes. The owned
# SNAT MASQUERADE rule lives here; we read its exact counter, never the chain
# aggregate.
OWNED_NAT_CHAIN = "K3D_WG_MASQ_NAT"

# I6 acceptance-grade minimum number of fresh pod-origin TCP connects. Kept in
# lock-step with the verifier: fewer than this is a vacuous / non-acceptance
# probe, so the collector rejects it at parse time and never self-declares pass.
MIN_PROBE_ATTEMPTS = 3

# Repo-relative canonical host-rule script (run from the repo root on staging-sw).
DEFAULT_HOST_RULE_SCRIPT = "bootstrap/host/k3d-wg-masq/k3d-wg-masq-host-rule.sh"

# Label selector for the ephemeral, policy-approved probe pod (deployed by the
# collect workflow). Selection is by label, NOT "first Running pod", and must
# match EXACTLY ONE pod (Calico IPAM means the pod IP is not in the node /24).
DEFAULT_PROBE_POD_SELECTOR = "wg-i6-probe=true"

# Absolute host binaries used to run the host-rule check under sudo. sudo -n
# strips the caller env, so vars are set AFTER sudo via /usr/bin/env in the root
# context (no shell). These paths are the ones present on staging-sw.
SUDO_BIN = "sudo"
ENV_BIN = "/usr/bin/env"
BASH_BIN = "/bin/bash"

LOOPBACK_HOSTS = {"127.0.0.1", "0.0.0.0", "::1", "localhost", "host.docker.internal"}


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_short(value: str) -> str:
    return sha256_hex(value)[:16]


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def run_command(argv: list[str], timeout: int = 12, env: dict[str, str] | None = None) -> CommandResult:
    run_env: dict[str, str] | None = None
    if env:
        run_env = os.environ.copy()
        run_env.update(env)
    try:
        proc = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=run_env,
        )
    except FileNotFoundError:
        return CommandResult(127, "", "not-found")
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", "timeout")
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


def command_paths(name: str) -> list[str]:
    """Return PATH + common Linux admin locations for a command."""
    candidates: list[str] = []
    found = shutil.which(name)
    if found:
        candidates.append(found)
    candidates.extend(
        [
            f"/usr/sbin/{name}",
            f"/sbin/{name}",
            f"/usr/bin/{name}",
            f"/bin/{name}",
            f"/usr/local/bin/{name}",
            f"/usr/local/sbin/{name}",
            f"/snap/bin/{name}",
            f"/opt/homebrew/bin/{name}",
        ]
    )
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def command_variants(name: str, args: list[str], sudo: bool = False) -> list[list[str]]:
    variants: list[list[str]] = []
    for command in command_paths(name):
        if sudo:
            variants.append(["sudo", "-n", command, *args])
        variants.append([command, *args])
    return variants


def nsenter_variants(name: str, args: list[str], sudo: bool = False) -> list[list[str]]:
    """Return read-only host namespace variants for containerized runners."""
    variants: list[list[str]] = []
    for nsenter in command_paths("nsenter"):
        for command in command_paths(name):
            base = [nsenter, "-t", "1", "-m", "-u", "-i", "-n", "-p", "--", command, *args]
            if sudo:
                variants.append(["sudo", "-n", *base])
            variants.append(base)
    return variants


def host_command_variants(name: str, args: list[str], sudo: bool = False) -> list[list[str]]:
    return command_variants(name, args, sudo=sudo) + nsenter_variants(name, args, sudo=sudo)


def first_success(
    commands: list[list[str]], timeout: int = 12, env: dict[str, str] | None = None
) -> CommandResult:
    last = CommandResult(127, "", "not-run")
    best_failure: CommandResult | None = None
    for command in commands:
        result = run_command(command, timeout=timeout, env=env)
        last = result
        if result.exit_code == 0:
            return result
        if result.exit_code not in {126, 127}:
            best_failure = result
    return best_failure or last


def resolve_command(name: str) -> str:
    """Resolve a single argv[0] for a command, preferring one that exists on disk.

    Used for the pod TCP probe where every attempt must map to exactly one
    execution (no cross-variant retry that would double-count fresh connects).
    """
    for candidate in command_paths(name):
        if os.path.exists(candidate):
            return candidate
    return command_paths(name)[0]


def safe_name(value: str, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:@-]+", "-", value.strip())[:96].strip("-")
    return cleaned or fallback


def normalize_cidr(value: str) -> str | None:
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError:
        return None
    if network.version != 4:
        return None
    return str(network)


def cidr_subnet_of(child: str | None, parent: str | None) -> bool:
    if not child or not parent:
        return False
    try:
        return ipaddress.ip_network(child).subnet_of(ipaddress.ip_network(parent))
    except (ValueError, TypeError):
        return False


def ip_in_cidr(ip: str, cidr: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr)
    except ValueError:
        return False


def derive_wg_cidr(peer_host: str) -> str:
    try:
        return str(ipaddress.ip_network(f"{peer_host}/24", strict=False))
    except ValueError:
        return "10.99.0.0/24"


CIDR_TOKEN_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})")


def parse_wg_interface(requested: str) -> tuple[str, dict[str, Any]]:
    if requested != "auto":
        return safe_name(requested, "wg0"), {"requested": requested, "autoDetected": False}

    result = first_success(host_command_variants("wg", ["show", "interfaces"], sudo=True), timeout=8)
    interfaces = [item for item in result.stdout.split() if re.match(r"^[A-Za-z0-9_.:@-]{1,96}$", item)]
    selected = interfaces[0] if interfaces else "wg0"
    return safe_name(selected, "wg0"), {
        "requested": "auto",
        "autoDetected": bool(interfaces),
        "interfaceCount": len(interfaces),
        "probeExitCode": result.exit_code,
    }


def expected_rule_hash(cluster_cidr: str, wg_interface: str, peer_host: str, peer_port: int) -> str:
    normalized = (
        f"iptables:nat:{OWNED_NAT_CHAIN}:cluster={cluster_cidr}:wireguard={wg_interface}:"
        f"peer={peer_host}:{peer_port}:masquerade"
    )
    return sha256_hex(normalized)


def rollback_hash(unit: str, cluster_cidr: str, wg_interface: str, peer_host: str) -> str:
    normalized = f"rollback:{unit}:cluster={cluster_cidr}:wireguard={wg_interface}:peer={peer_host}"
    return sha256_hex(normalized)


def protected_evidence_path(args: argparse.Namespace) -> str:
    if args.protected_evidence_path:
        return args.protected_evidence_path
    return f"github-actions://Halildeu/platform-k8s-gitops/actions/runs/{args.github_run_id}"


def probe_attempts_type(value: str) -> int:
    """argparse type for --probe-attempts.

    Rejects anything below MIN_PROBE_ATTEMPTS so the collector can never
    self-declare pass on a probe count the verifier would reject as vacuous /
    non-acceptance-grade (collector and verifier share the same floor).
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"must be an integer, got {value!r}")
    if parsed < MIN_PROBE_ATTEMPTS:
        raise argparse.ArgumentTypeError(f"must be >= {MIN_PROBE_ATTEMPTS}, got {parsed}")
    return parsed


# ---------------------------------------------------------------------------
# Check 1: cluster-identity-bound
# ---------------------------------------------------------------------------
def collect_cluster_identity(args: argparse.Namespace, cluster_cidr: str | None) -> dict[str, Any]:
    ctx = args.kube_context

    uid_res = first_success(
        command_variants(
            "kubectl",
            ["--context", ctx, "get", "namespace", "kube-system", "-o", "jsonpath={.metadata.uid}"],
        ),
        timeout=15,
    )
    uid_value = uid_res.stdout.strip() if uid_res.exit_code == 0 else ""
    uid_resolved = bool(uid_value)

    inspect = first_success(
        host_command_variants(
            "docker", ["inspect", args.wg_node, "--format", "{{json .NetworkSettings.Networks}}"], sudo=True
        ),
        timeout=12,
    )
    node_exists = inspect.exit_code == 0 and inspect.stdout.strip() not in {"", "null"}
    node_on_network = False
    if node_exists:
        try:
            networks = json.loads(inspect.stdout)
            node_on_network = isinstance(networks, dict) and args.docker_network in networks
        except json.JSONDecodeError:
            node_on_network = False

    server_res = first_success(
        command_variants(
            "kubectl",
            ["--context", ctx, "config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"],
        ),
        timeout=12,
    )
    server_url = server_res.stdout.strip() if server_res.exit_code == 0 else ""
    api_host = urlsplit(server_url).hostname if server_url else None
    is_loopback = bool(api_host) and (api_host in LOOPBACK_HOSTS or api_host.startswith("127."))
    endpoint_ok = bool(is_loopback or ctx.startswith("k3d-"))

    policy_cidr = CONTEXT_CIDR_POLICY.get(ctx)
    belt_applied = policy_cidr is not None
    belt_ok = True
    if belt_applied:
        belt_ok = cluster_cidr is not None and cluster_cidr == policy_cidr

    bound = bool(
        uid_resolved
        and node_exists
        and node_on_network
        and bool(server_url)
        and endpoint_ok
        and belt_ok
    )

    return {
        "contextName": safe_name(ctx),
        "clusterUidHash": sha256_short(uid_value) if uid_value else None,
        "uidResolved": uid_resolved,
        "nodeName": safe_name(args.wg_node),
        "dockerNetwork": safe_name(args.docker_network),
        "nodeExists": node_exists,
        "nodeOnNetwork": node_on_network,
        "apiServerHostHash": sha256_short(api_host) if api_host else None,
        "apiServerResolved": bool(server_url),
        "endpointIsK3dLoopback": endpoint_ok,
        "beltPolicyApplied": belt_applied,
        "beltPolicyExpectedCidr": policy_cidr,
        "beltPolicyOk": belt_ok,
        "bound": bound,
    }


# ---------------------------------------------------------------------------
# Check 2: effective-cluster-cidr-matches-config
# ---------------------------------------------------------------------------
def collect_effective_cluster_cidr(args: argparse.Namespace, cluster_cidr: str | None) -> dict[str, Any]:
    node = args.wg_node

    config_res = first_success(
        host_command_variants("docker", ["exec", node, "cat", "/etc/rancher/k3s/config.yaml"], sudo=True),
        timeout=12,
    )
    config_cidr: str | None = None
    if config_res.exit_code == 0:
        for line in config_res.stdout.splitlines():
            if "cluster-cidr" in line:
                match = CIDR_TOKEN_RE.search(line)
                if match:
                    normalized = normalize_cidr(match.group(1))
                    if normalized:
                        config_cidr = normalized
                        break

    cmdline_res = first_success(
        host_command_variants("docker", ["exec", node, "cat", "/proc/1/cmdline"], sudo=True),
        timeout=12,
    )
    cmdline_cidr: str | None = None
    if cmdline_res.exit_code == 0:
        text = cmdline_res.stdout.replace("\x00", " ")
        match = re.search(r"--cluster-cidr[=\s]+([0-9./,]+)", text)
        if match:
            token = CIDR_TOKEN_RE.search(match.group(1))
            if token:
                cmdline_cidr = normalize_cidr(token.group(1))

    sources_conflict = bool(config_cidr and cmdline_cidr and config_cidr != cmdline_cidr)
    effective = config_cidr or cmdline_cidr
    matches_config = bool(effective and cluster_cidr and effective == cluster_cidr)
    passed = bool(effective) and not sources_conflict and matches_config

    return {
        "configuredClusterCidr": cluster_cidr,
        "effectiveClusterCidr": effective,
        "configSourceCidr": config_cidr,
        "cmdlineSourceCidr": cmdline_cidr,
        "sourcesConflict": sources_conflict,
        "matchesConfig": matches_config,
        "resolved": bool(effective),
        "passed": passed,
    }


# ---------------------------------------------------------------------------
# Check 3: node-pod-cidrs-within-cluster-cidr
# ---------------------------------------------------------------------------
def collect_node_pod_cidrs(args: argparse.Namespace, cluster_cidr: str | None) -> dict[str, Any]:
    res = first_success(
        command_variants("kubectl", ["--context", args.kube_context, "get", "nodes", "-o", "json"]),
        timeout=20,
    )
    cidrs: list[str] = []
    readable = False
    if res.exit_code == 0:
        try:
            data = json.loads(res.stdout)
            readable = True
            for item in data.get("items", []):
                spec = item.get("spec", {}) if isinstance(item, dict) else {}
                raw = [spec.get("podCIDR")] + list(spec.get("podCIDRs") or [])
                for cidr in raw:
                    if not cidr:
                        continue
                    normalized = normalize_cidr(cidr)
                    if normalized and normalized not in cidrs:
                        cidrs.append(normalized)
        except json.JSONDecodeError:
            readable = False

    all_within = bool(cidrs) and all(cidr_subnet_of(cidr, cluster_cidr) for cidr in cidrs)
    passed = readable and bool(cidrs) and cluster_cidr is not None and all_within

    return {
        "nodePodCIDRs": cidrs,
        "clusterCidr": cluster_cidr,
        "sourceReadable": readable,
        "allWithinClusterCidr": all_within,
        "passed": passed,
    }


# ---------------------------------------------------------------------------
# Check 4: host-owned-chain-authority
# ---------------------------------------------------------------------------
def _run_host_rule_check(
    script_path: Path, env_vars: dict[str, str], run_mode: str
) -> tuple[int | None, str]:
    """Run `<script> check` with env set AFTER sudo (sudo -n strips the caller env).

    Returns (exit_code, executionMode). If the sudo path itself is not runnable
    (sudo/env/bash missing), fall back to a NON-sudo direct run recorded as
    executionMode="direct" — which the caller must treat as non-authoritative
    (it cannot be assumed to have CAP_NET_ADMIN).
    """
    env_args = [f"{key}={value}" for key, value in env_vars.items()]
    sudo_cmd = [SUDO_BIN, "-n", ENV_BIN, *env_args, BASH_BIN, str(script_path), "check"]
    res = run_command(sudo_cmd, timeout=25)
    if res.exit_code not in {126, 127}:
        # sudo actually executed (exit 0 = check passed; non-zero = genuine failure
        # such as a denied `sudo -n`); either way this is the authoritative mode.
        return res.exit_code, run_mode
    direct_cmd = [ENV_BIN, *env_args, BASH_BIN, str(script_path), "check"]
    res_direct = run_command(direct_cmd, timeout=25)
    return res_direct.exit_code, "direct"


def collect_host_owned_chain(args: argparse.Namespace, wg_interface: str) -> dict[str, Any]:
    canonical_path = Path(args.host_rule_script)
    canonical_found = canonical_path.is_file()
    canonical_sha = sha256_file(canonical_path) if canonical_found else None

    installed_provided = bool(args.installed_host_rule_script)
    installed_path = Path(args.installed_host_rule_script) if installed_provided else None
    installed_found = bool(installed_path and installed_path.is_file())
    installed_sha = sha256_file(installed_path) if installed_found else None
    # shaMatches is vacuously true when no installed script is supplied (no drift possible),
    # otherwise it is the recomputed equality of installed vs canonical sha256.
    if not installed_provided:
        sha_matches = True
    else:
        sha_matches = bool(installed_sha and canonical_sha and installed_sha == canonical_sha)

    # Prefer the installed root-owned script when provided AND its sha matches the
    # canonical checkout (avoids the TOCTOU of running a user-writable checkout script
    # as root); else fall back to the canonical checkout script.
    if installed_provided and sha_matches and installed_found:
        run_path: Path | None = installed_path
        run_mode = "sudo-installed"
    elif canonical_found:
        run_path = canonical_path
        run_mode = "sudo-canonical"
    else:
        run_path = None
        run_mode = ""

    node = safe_name(args.wg_node)
    network = safe_name(args.docker_network)
    wg_if = safe_name(wg_interface)
    wg_cidr = normalize_cidr(derive_wg_cidr(args.peer_host))
    env_valid = bool(node and network and wg_if and wg_cidr)

    check_exit: int | None = None
    execution_mode: str | None = None
    if run_path is not None and env_valid:
        env_vars = {
            "WGMASQ_NODE": node,
            "WGMASQ_NETWORK": network,
            "WGMASQ_WG_CIDR": wg_cidr,  # validated CIDR, passed raw (never safe_name'd — '/' matters)
            "WGMASQ_WG_IF": wg_if,
        }
        check_exit, execution_mode = _run_host_rule_check(run_path, env_vars, run_mode)

    # Authoritative pass requires a sudo (root-capable) execution mode; a "direct"
    # non-root run that could hide missing privilege is NOT sufficient.
    passed = bool(
        canonical_found
        and check_exit == 0
        and execution_mode in {"sudo-installed", "sudo-canonical"}
        and (not installed_provided or sha_matches)
    )

    return {
        "hostRuleScript": str(canonical_path),
        "runScript": str(run_path) if run_path is not None else None,
        "scriptFound": canonical_found,
        "canonicalSha256": canonical_sha,
        "checkExitCode": check_exit,
        "installedProvided": installed_provided,
        "installedSha256": installed_sha,
        "shaMatches": sha_matches,
        "executionMode": execution_mode,
        "ownedNatChain": OWNED_NAT_CHAIN,
        "passed": passed,
    }


# ---------------------------------------------------------------------------
# Check 5: peer-route-is-wireguard-path
# ---------------------------------------------------------------------------
def collect_route_interface(target_host: str) -> dict[str, Any]:
    result = first_success(host_command_variants("ip", ["route", "get", target_host], sudo=True), timeout=6)
    route_interface = None
    if result.exit_code == 0:
        match = re.search(r"\bdev\s+([A-Za-z0-9_.:@-]{1,96})\b", result.stdout)
        if match:
            route_interface = match.group(1)
    return {
        "probeExitCode": result.exit_code,
        "targetRouteInterface": safe_name(route_interface or "", "") if route_interface else None,
    }


def parse_wg_peer(
    allowed_ips_stdout: str, handshakes_stdout: str, peer_host: str
) -> tuple[bool, str | None, int | None]:
    """Return (covers_peer, peer_pubkey_fingerprint, handshake_age_seconds).

    Never returns raw key material; only a sha256 fingerprint of the public key.
    """
    try:
        peer_ip = ipaddress.ip_address(peer_host)
    except ValueError:
        return False, None, None

    matched_pubkey: str | None = None
    for line in allowed_ips_stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        pubkey = parts[0]
        for token in parts[1:]:
            if token in {"(none)", ""}:
                continue
            try:
                network = ipaddress.ip_network(token, strict=False)
            except ValueError:
                continue
            if peer_ip in network:
                matched_pubkey = pubkey
                break
        if matched_pubkey:
            break

    if not matched_pubkey:
        return False, None, None

    handshake_age: int | None = None
    for line in handshakes_stdout.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] != matched_pubkey:
            continue
        try:
            ts = int(parts[1])
        except ValueError:
            continue
        if ts > 0:
            handshake_age = max(0, now_epoch() - ts)
        break

    return True, sha256_short(matched_pubkey), handshake_age


def collect_peer_route(args: argparse.Namespace, wg_interface: str) -> dict[str, Any]:
    route = collect_route_interface(args.peer_host)
    route_dev = route.get("targetRouteInterface")
    route_is_wg = route_dev == wg_interface

    allowed = first_success(
        host_command_variants("wg", ["show", wg_interface, "allowed-ips"], sudo=True), timeout=8
    )
    handshakes = first_success(
        host_command_variants("wg", ["show", wg_interface, "latest-handshakes"], sudo=True), timeout=8
    )
    covers, fingerprint, handshake_age = parse_wg_peer(
        allowed.stdout if allowed.exit_code == 0 else "",
        handshakes.stdout if handshakes.exit_code == 0 else "",
        args.peer_host,
    )

    route_resolved = route_dev is not None
    passed = bool(route_is_wg and covers and wg_interface)

    return {
        "expectedWgInterface": wg_interface,
        "routeProbeExitCode": route.get("probeExitCode"),
        "routeResolved": route_resolved,
        "routeDevice": route_dev,
        "routeDevIsWireguard": route_is_wg,
        "allowedIpsProbeExitCode": allowed.exit_code,
        "allowedIpsCoverPeer": covers,
        "peerFingerprint": fingerprint,
        "handshakeAgeSeconds": handshake_age,
        "passed": passed,
    }


# ---------------------------------------------------------------------------
# Checks 6 + 7: pod-to-wg-peer-tcp-connect + snat-rule-counter-traversal
#
# One traversal measurement wraps the N pod-origin TCP probes:
#   read owned rule fingerprint + counter (before)
#   -> run N fresh TCP connects from the selected pod
#   -> read owned rule fingerprint + counter (after)
# Both check 6 (TCP) and check 7 (counter) derive from this single measurement.
# ---------------------------------------------------------------------------
def read_owned_chain_spec(args: argparse.Namespace) -> str | None:
    commands: list[list[str]] = []
    for binary in ["iptables", "iptables-nft", "iptables-legacy"]:
        commands.extend(host_command_variants(binary, ["-w", "-t", "nat", "-S", OWNED_NAT_CHAIN], sudo=True))
    result = first_success(commands, timeout=10)
    if result.exit_code != 0:
        return None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"-A {OWNED_NAT_CHAIN}") and "-j MASQUERADE" in stripped:
            return stripped
    return None


def read_owned_chain_counter(args: argparse.Namespace) -> int | None:
    commands = host_command_variants("iptables-save", ["-c", "-t", "nat"], sudo=True)
    result = first_success(commands, timeout=10)
    if result.exit_code != 0:
        return None
    pattern = re.compile(
        rf"^\[(\d+):\d+\]\s+(-A {re.escape(OWNED_NAT_CHAIN)}\b.*-j MASQUERADE.*)$"
    )
    for line in result.stdout.splitlines():
        match = pattern.match(line.strip())
        if match:
            return int(match.group(1))
    return None


def select_probe_pod(
    args: argparse.Namespace, cluster_cidr: str | None, node_name: str | None
) -> dict[str, Any]:
    """Select the ephemeral probe pod by LABEL (not "first Running pod").

    Calico IPAM means the pod IP is NOT inside the node's `.spec.podCIDR` /24, so
    selection is by the policy-approved label and validated against the disclosed
    clusterCIDR + the bound node instead. Requires EXACTLY ONE matching pod.
    """
    res = first_success(
        command_variants(
            "kubectl",
            [
                "--context", args.kube_context, "-n", args.namespace,
                "get", "pods", "-l", args.probe_pod_selector, "-o", "json",
            ],
        ),
        timeout=20,
    )
    items: list[dict[str, Any]] = []
    if res.exit_code == 0:
        try:
            data = json.loads(res.stdout)
            items = [item for item in data.get("items", []) if isinstance(item, dict)]
        except json.JSONDecodeError:
            items = []
    match_count = len(items)

    info: dict[str, Any] = {
        "matchCount": match_count,
        "pod": None,
        "valid": False,
        "podName": None,
        "podUid": None,
        "podIP": None,
        "nodeName": None,
        "hostNetwork": None,
        "phase": None,
        "ready": None,
        "deletionTimestampPresent": None,
        "imageRef": None,
        "runtimeImageID": None,
        "podWithinClusterCidr": None,
        "podOnTargetNode": None,
    }
    if match_count != 1:
        return info

    pod = items[0]
    meta = pod.get("metadata") if isinstance(pod.get("metadata"), dict) else {}
    spec = pod.get("spec") if isinstance(pod.get("spec"), dict) else {}
    status = pod.get("status") if isinstance(pod.get("status"), dict) else {}

    phase = status.get("phase")
    pod_ip = status.get("podIP")
    host_network = bool(spec.get("hostNetwork", False))
    deletion_present = bool(meta.get("deletionTimestamp"))
    pod_node = spec.get("nodeName")
    ready = any(
        isinstance(cond, dict) and cond.get("type") == "Ready" and cond.get("status") == "True"
        for cond in (status.get("conditions") or [])
    )
    containers = spec.get("containers") or []
    image_ref = containers[0].get("image") if containers and isinstance(containers[0], dict) else None
    cstatuses = status.get("containerStatuses") or []
    runtime_image_id = (
        cstatuses[0].get("imageID") if cstatuses and isinstance(cstatuses[0], dict) else None
    )

    within = bool(pod_ip and cluster_cidr and ip_in_cidr(pod_ip, cluster_cidr))
    on_node = bool(pod_node and node_name and pod_node == node_name)
    valid = bool(
        phase == "Running"
        and ready
        and not deletion_present
        and not host_network
        and pod_ip
        and within
        and on_node
    )

    info.update(
        pod=pod,
        valid=valid,
        podName=meta.get("name"),
        podUid=meta.get("uid"),
        podIP=pod_ip,
        nodeName=pod_node,
        hostNetwork=host_network,
        phase=phase,
        ready=ready,
        deletionTimestampPresent=deletion_present,
        imageRef=image_ref,
        runtimeImageID=runtime_image_id,
        podWithinClusterCidr=within,
        podOnTargetNode=on_node,
    )
    return info


def measure_traversal(
    args: argparse.Namespace, cluster_cidr: str | None, node_name: str | None
) -> dict[str, Any]:
    selection = select_probe_pod(args, cluster_cidr, node_name)
    pod_valid = bool(selection["valid"])

    spec_before = read_owned_chain_spec(args)
    counter_before = read_owned_chain_counter(args)

    attempts = args.probe_attempts
    attempt_exit_codes: list[int] = []
    nc_missing = False

    if pod_valid and selection["pod"] is not None:
        pod_name = selection["podName"] or ""
        kubectl_bin = resolve_command("kubectl")
        exec_argv = [
            kubectl_bin,
            "--context",
            args.kube_context,
            "-n",
            args.namespace,
            "exec",
            pod_name,
            "--",
            "nc",
            "-w4",
            "-z",
            args.peer_host,
            str(args.peer_port),
        ]
        for _ in range(attempts):
            result = run_command(exec_argv, timeout=20)
            attempt_exit_codes.append(result.exit_code)
            if result.exit_code in {126, 127}:
                nc_missing = True

    success_count = sum(1 for code in attempt_exit_codes if code == 0)

    spec_after = read_owned_chain_spec(args)
    counter_after = read_owned_chain_counter(args)

    rule_stable = bool(spec_before and spec_after and spec_before == spec_after)
    counter_delta: int | None = None
    if counter_before is not None and counter_after is not None:
        counter_delta = counter_after - counter_before
    counter_not_reset = bool(
        counter_before is not None and counter_after is not None and counter_after >= counter_before
    )

    # Fail-closed against vacuous truth: with attempts==0 the probe loop never runs, so
    # success_count==attempts==0 and counter_delta>=0 would both hold trivially. Require
    # acceptance-grade attempts (>= MIN_PROBE_ATTEMPTS) AND full success from the VALID
    # label-selected pod — the same floor the verifier enforces.
    tcp_pass = bool(
        pod_valid
        and not nc_missing
        and attempts >= MIN_PROBE_ATTEMPTS
        and success_count == attempts
    )
    counter_pass = bool(
        rule_stable
        and counter_not_reset
        and counter_delta is not None
        and attempts >= MIN_PROBE_ATTEMPTS
        and counter_delta >= attempts
        and success_count == attempts
    )

    fingerprint_before_hash = sha256_short(spec_before) if spec_before else None
    fingerprint_after_hash = sha256_short(spec_after) if spec_after else None

    pod_ip = selection["podIP"]
    probe_block = {
        "namespace": safe_name(args.namespace),
        "targetHost": args.peer_host,
        "targetPort": args.peer_port,
        "attempts": attempts,
        "successCount": success_count,
        "attemptExitCodes": attempt_exit_codes,
        "ncMissing": nc_missing,
        "matchCount": selection["matchCount"],
        "podIP": pod_ip,
        "podIpHash": sha256_short(pod_ip) if pod_ip else None,
        "podNameHash": sha256_short(selection["podName"]) if selection["podName"] else None,
        "podUidHash": sha256_short(selection["podUid"]) if selection["podUid"] else None,
        "nodeName": selection["nodeName"],
        "hostNetwork": selection["hostNetwork"],
        "phase": selection["phase"],
        "ready": selection["ready"],
        "deletionTimestampPresent": selection["deletionTimestampPresent"],
        "imageRef": selection["imageRef"],
        "runtimeImageID": selection["runtimeImageID"],
        "podWithinClusterCidr": selection["podWithinClusterCidr"],
        "podOnTargetNode": selection["podOnTargetNode"],
        "passed": tcp_pass,
    }
    counter_wrap = success_count == attempts and pod_valid
    counter_block = {
        "ownedNatChain": OWNED_NAT_CHAIN,
        "attempts": attempts,
        "successCount": success_count,
        "counterBefore": counter_before,
        "counterAfter": counter_after,
        "counterDelta": counter_delta,
        "ruleFingerprintHash": fingerprint_before_hash,
        "ruleFingerprintBeforeHash": fingerprint_before_hash,
        "ruleFingerprintAfterHash": fingerprint_after_hash,
        "ruleStable": rule_stable,
        "counterNotReset": counter_not_reset,
        "tcpProbeGateSatisfied": bool(counter_wrap),
        "passed": counter_pass,
    }
    return {"probe": probe_block, "counter": counter_block}


# ---------------------------------------------------------------------------
# Checks 8/9/10: systemd persistence + drift + rollback
# ---------------------------------------------------------------------------
def collect_systemd(unit: str, drift_timer: str) -> dict[str, Any]:
    active = first_success(host_command_variants("systemctl", ["is-active", unit], sudo=True), timeout=6)
    enabled = first_success(host_command_variants("systemctl", ["is-enabled", unit], sudo=True), timeout=6)
    show = first_success(
        host_command_variants(
            "systemctl",
            ["show", unit, "-p", "ActiveState", "-p", "UnitFileState", "-p", "ExecStart", "-p", "ExecStop"],
            sudo=True,
        ),
        timeout=8,
    )
    timer_active = first_success(host_command_variants("systemctl", ["is-active", drift_timer], sudo=True), timeout=6)
    timer_enabled = first_success(host_command_variants("systemctl", ["is-enabled", drift_timer], sudo=True), timeout=6)

    show_stdout = show.stdout if show.exit_code == 0 else ""
    has_exec_start = "ExecStart=" in show_stdout and not re.search(r"^ExecStart=$", show_stdout, re.MULTILINE)
    has_exec_stop = "ExecStop=" in show_stdout and not re.search(r"^ExecStop=$", show_stdout, re.MULTILINE)

    return {
        "unit": safe_name(unit),
        "active": active.stdout.strip() == "active",
        "enabled": enabled.stdout.strip() in {"enabled", "static"},
        "showExitCode": show.exit_code,
        "hasExecStart": has_exec_start,
        "hasExecStop": has_exec_stop,
        "driftTimer": safe_name(drift_timer),
        "driftTimerActive": timer_active.stdout.strip() == "active",
        "driftTimerEnabled": timer_enabled.stdout.strip() in {"enabled", "static"},
    }


# ---------------------------------------------------------------------------
# Check 11: no-broad-lan-nat
# ---------------------------------------------------------------------------
def collect_broad_nat(args: argparse.Namespace) -> dict[str, Any]:
    commands: list[list[str]] = []
    for binary in ["iptables", "iptables-nft", "iptables-legacy"]:
        commands.extend(host_command_variants(binary, ["-w", "-t", "nat", "-S"], sudo=True))
    commands.extend(host_command_variants("iptables-save", ["-t", "nat"], sudo=True))
    result = first_success(commands, timeout=10)
    queryable = result.exit_code == 0
    broad = False
    if queryable:
        for line in result.stdout.splitlines():
            if "-j MASQUERADE" not in line:
                continue
            if re.search(r"(^|\s)-s\s+0\.0\.0\.0/0(\s|$)", line):
                broad = True
            if re.search(r"(^|\s)-s\s+10\.0\.0\.0/8(\s|$)", line):
                broad = True
    passed = queryable and not broad
    return {
        "queryable": queryable,
        "probeExitCode": result.exit_code,
        "broadNatDetected": broad,
        "passed": passed,
    }


def check(check_id: str, passed: bool, observed_at: str, summary: str) -> dict[str, str]:
    return {
        "id": check_id,
        "status": "pass" if passed else "fail",
        "observedAt": observed_at,
        "summary": summary[:220],
        "evidenceRef": f"checks/{check_id}.json",
    }


def build_evidence(args: argparse.Namespace) -> dict[str, Any]:
    collected_at = now_utc()
    cluster_cidr = normalize_cidr(args.cluster_cidr)

    wg_interface, wg_meta = parse_wg_interface(args.wg_interface)
    host = safe_name(socket.gethostname(), "staging-sw")

    identity = collect_cluster_identity(args, cluster_cidr)
    effective = collect_effective_cluster_cidr(args, cluster_cidr)
    node_cidrs = collect_node_pod_cidrs(args, cluster_cidr)
    host_chain = collect_host_owned_chain(args, wg_interface)
    peer_route = collect_peer_route(args, wg_interface)
    # v3: probe pod is selected by LABEL and validated against clusterCIDR + the bound
    # node (Calico-safe), NOT against the node .spec.podCIDR /24.
    traversal = measure_traversal(args, cluster_cidr, identity["nodeName"])
    systemd = collect_systemd(args.systemd_unit, args.drift_timer)
    broad_nat = collect_broad_nat(args)

    persistence_pass = bool(systemd["enabled"] and systemd["active"] and systemd["hasExecStart"])
    drift_pass = bool(systemd["driftTimerActive"] or systemd["driftTimerEnabled"])
    rollback_pass = bool(systemd["hasExecStop"] and args.rollback_tested_ref)

    rule_hash = expected_rule_hash(
        cluster_cidr or args.cluster_cidr, wg_interface, args.peer_host, args.peer_port
    )
    rb_hash = rollback_hash(args.systemd_unit, cluster_cidr or args.cluster_cidr, wg_interface, args.peer_host)

    checks = [
        check(
            "cluster-identity-bound",
            identity["bound"],
            collected_at,
            "Kube context, cluster uid, node and docker network are bound and belt-policy consistent"
            if identity["bound"]
            else "Cluster identity is not bound (unresolved uid/node/network/endpoint or belt-policy mismatch)",
        ),
        check(
            "effective-cluster-cidr-matches-config",
            effective["passed"],
            collected_at,
            "Effective node cluster-cidr matches the configured cluster CIDR"
            if effective["passed"]
            else "Effective node cluster-cidr is unresolved, conflicting, or does not match configured cluster CIDR",
        ),
        check(
            "node-pod-cidrs-within-cluster-cidr",
            node_cidrs["passed"],
            collected_at,
            "Every node podCIDR allocation is contained within the cluster CIDR"
            if node_cidrs["passed"]
            else "Node podCIDR allocations are unreadable, empty, or not contained within the cluster CIDR",
        ),
        check(
            "host-owned-chain-authority",
            host_chain["passed"],
            collected_at,
            "Canonical host-rule script check passed and (if provided) installed script matches canonical sha256"
            if host_chain["passed"]
            else "Host-owned chain authority not proven (missing script, non-zero check, or installed sha mismatch)",
        ),
        check(
            "peer-route-is-wireguard-path",
            peer_route["passed"],
            collected_at,
            "Peer route egresses the WireGuard interface and a peer AllowedIPs covers the target"
            if peer_route["passed"]
            else "Peer route is not proven to egress WireGuard with peer AllowedIPs covering the target",
        ),
        check(
            "pod-to-wg-peer-tcp-connect",
            traversal["probe"]["passed"],
            collected_at,
            f"Pod-origin TCP connect {traversal['probe']['successCount']}/{traversal['probe']['attempts']} to peer succeeded from in-CIDR pod"
            if traversal["probe"]["passed"]
            else "Pod-origin TCP connect to the WireGuard peer did not fully succeed from an in-CIDR pod",
        ),
        check(
            "snat-rule-counter-traversal",
            traversal["counter"]["passed"],
            collected_at,
            "Owned SNAT counter advanced by the pod probe with a stable rule fingerprint"
            if traversal["counter"]["passed"]
            else "Owned SNAT counter traversal not proven (unstable rule, reset counter, insufficient delta, or failed TCP gate)",
        ),
        check(
            "reboot-persistence",
            persistence_pass,
            collected_at,
            "Systemd unit is enabled and active in current boot"
            if persistence_pass
            else "Systemd persistence is not proven by enabled active unit metadata",
        ),
        check(
            "drift-detect",
            drift_pass,
            collected_at,
            "Systemd drift timer metadata is active or enabled"
            if drift_pass
            else "Systemd drift timer metadata is missing or inactive",
        ),
        check(
            "rollback-defined",
            rollback_pass,
            collected_at,
            "Rollback ExecStop and tested evidence reference are present"
            if rollback_pass
            else "Rollback tested evidence reference or ExecStop metadata is missing",
        ),
        check(
            "no-broad-lan-nat",
            broad_nat["passed"],
            collected_at,
            "No broad LAN NAT was detected in the nat table or owned chain"
            if broad_nat["passed"]
            else "Broad LAN NAT absence is not proven",
        ),
        check(
            "daemonset-not-assumed",
            True,
            collected_at,
            "Evidence authority is host-managed systemd iptables, not a Kubernetes DaemonSet",
        ),
    ]

    all_pass = all(item["status"] == "pass" for item in checks)
    evidence: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "collectedAt": collected_at,
        "status": "pass" if all_pass else "blocked",
        "protectedEvidencePath": protected_evidence_path(args),
        "redaction": {
            "secretMaterialIncluded": False,
            "rawCommandOutputIncluded": False,
            "rawPacketCaptureIncluded": False,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
        },
        "topology": {
            "clusterName": safe_name(args.kube_context),
            "clusterCIDR": cluster_cidr or args.cluster_cidr,
            "nodePodCIDRs": node_cidrs["nodePodCIDRs"],
            "wgInterface": wg_interface,
            "platformAiTarget": {
                "host": args.peer_host,
                "port": args.peer_port,
            },
        },
        "mechanism": {
            "type": "host-systemd-iptables",
            "managedOutsideCluster": True,
            "daemonSetAssumed": False,
            "host": host,
            "systemdUnit": safe_name(args.systemd_unit),
            "iptablesTable": "nat",
            "iptablesChain": "POSTROUTING",
            "ownedNatChain": OWNED_NAT_CHAIN,
            "expectedRuleHash": rule_hash,
        },
        "driftDetection": {
            "enabled": drift_pass,
            "mode": "systemd-timer",
            "intervalMinutes": args.drift_interval_minutes,
            "expectedRuleHash": rule_hash,
            "evidenceRef": "drift/systemd-timer.json",
        },
        "rollback": {
            "defined": bool(systemd["hasExecStop"]),
            "tested": bool(args.rollback_tested_ref),
            "commandHash": rb_hash,
            "evidenceRef": args.rollback_tested_ref or "rollback/missing-tested-evidence.json",
        },
        "checks": checks,
        "collector": {
            "runner": "self-hosted-staging-sw",
            "wg": wg_meta,
            "clusterIdentity": identity,
            "effectiveCidr": effective,
            "nodePodCidrs": node_cidrs,
            "hostOwnedChain": host_chain,
            "peerRoute": peer_route,
            "podProbe": traversal["probe"],
            "counterTraversal": traversal["counter"],
            "systemd": systemd,
            "broadNat": broad_nat,
            "blockers": [item["id"] for item in checks if item["status"] != "pass"],
        },
    }
    if args.service_cidr:
        evidence["topology"]["serviceCIDR"] = args.service_cidr
    return evidence


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kube-context", default=os.environ.get("KUBE_CONTEXT", "k3d-test"))
    parser.add_argument("--namespace", default=os.environ.get("KUBE_NAMESPACE", "platform-test"))
    parser.add_argument(
        "--cluster-cidr",
        required=True,
        help="Configured k3s cluster CIDR (e.g. 10.44.0.0/16 for k3d-test). No default on purpose.",
    )
    parser.add_argument("--service-cidr", default=os.environ.get("SERVICE_CIDR", ""))
    parser.add_argument("--wg-interface", default=os.environ.get("WG_INTERFACE", "auto"))
    parser.add_argument("--peer-host", default=os.environ.get("PEER_HOST", "10.99.0.2"))
    parser.add_argument("--peer-port", type=int, default=int(os.environ.get("PEER_PORT", "8243")))
    parser.add_argument("--wg-node", default=os.environ.get("WG_NODE", "k3d-test-server-0"))
    parser.add_argument("--docker-network", default=os.environ.get("DOCKER_NETWORK", "platform-test-net"))
    parser.add_argument(
        "--host-rule-script",
        default=os.environ.get("HOST_RULE_SCRIPT", DEFAULT_HOST_RULE_SCRIPT),
        help="Repo-relative canonical host-rule script run with action 'check'.",
    )
    parser.add_argument(
        "--installed-host-rule-script",
        default=os.environ.get("INSTALLED_HOST_RULE_SCRIPT", ""),
        help="Optional path to the installed host-rule script; its sha256 must match the canonical script.",
    )
    parser.add_argument(
        "--probe-attempts",
        type=probe_attempts_type,
        default=probe_attempts_type(os.environ.get("PROBE_ATTEMPTS", str(MIN_PROBE_ATTEMPTS))),
    )
    parser.add_argument(
        "--probe-pod-selector",
        default=os.environ.get("PROBE_POD_SELECTOR", DEFAULT_PROBE_POD_SELECTOR),
        help="Label selector for the policy-approved probe pod; must match EXACTLY ONE pod.",
    )
    parser.add_argument("--systemd-unit", default=os.environ.get("SYSTEMD_UNIT", "k3d-wg-masq.service"))
    parser.add_argument("--drift-timer", default=os.environ.get("DRIFT_TIMER", "k3d-wg-masq.timer"))
    parser.add_argument("--drift-interval-minutes", type=int, default=int(os.environ.get("DRIFT_INTERVAL_MINUTES", "5")))
    parser.add_argument("--rollback-tested-ref", default=os.environ.get("ROLLBACK_TESTED_REF", ""))
    parser.add_argument(
        "--protected-evidence-path",
        default=os.environ.get("PROTECTED_EVIDENCE_PATH", ""),
        help="Override protectedEvidencePath for operator-collected host evidence",
    )
    parser.add_argument("--github-run-id", default=os.environ.get("GITHUB_RUN_ID", "0"))
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    evidence = build_evidence(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Faz24 WG-B+ I6 collector wrote {args.output}")
    print(f"Collector status: {evidence['status']}")
    blockers = evidence.get("collector", {}).get("blockers", [])
    if blockers:
        print(f"Blocking checks: {', '.join(blockers)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
