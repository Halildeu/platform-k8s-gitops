#!/usr/bin/env python3
"""Collect metadata-only Faz 24 WG-B+ I6 MASQ evidence on staging-sw.

This collector is intentionally fail-closed. It may read host, systemd,
iptables, WireGuard and Kubernetes metadata, but it does not change host
iptables/nftables, WireGuard, Kubernetes objects, platform-ai or production
state. Raw command output is used only in memory for parsing and is not written
to the evidence JSON.
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


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def run_command(argv: list[str], timeout: int = 12) -> CommandResult:
    try:
        proc = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
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


def first_success(commands: list[list[str]], timeout: int = 12) -> CommandResult:
    last = CommandResult(127, "", "not-run")
    best_failure: CommandResult | None = None
    for command in commands:
        result = run_command(command, timeout=timeout)
        last = result
        if result.exit_code == 0:
            return result
        if result.exit_code not in {126, 127}:
            best_failure = result
    return best_failure or last


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


def parse_wg_interface(requested: str) -> tuple[str, dict[str, Any]]:
    if requested != "auto":
        return safe_name(requested, "wg0"), {"requested": requested, "autoDetected": False}

    result = first_success(command_variants("wg", ["show", "interfaces"], sudo=True), timeout=8)
    interfaces = [item for item in result.stdout.split() if re.match(r"^[A-Za-z0-9_.:@-]{1,96}$", item)]
    selected = interfaces[0] if interfaces else "wg0"
    return safe_name(selected, "wg0"), {
        "requested": "auto",
        "autoDetected": bool(interfaces),
        "interfaceCount": len(interfaces),
        "probeExitCode": result.exit_code,
    }


def expected_rule_hash(pod_cidr: str, wg_interface: str, target_host: str, target_port: int) -> str:
    normalized = (
        "iptables:nat:POSTROUTING:"
        f"source={pod_cidr}:wireguard={wg_interface}:target={target_host}:{target_port}:masquerade"
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def rollback_hash(unit: str, pod_cidr: str, wg_interface: str, target_host: str) -> str:
    normalized = f"rollback:{unit}:source={pod_cidr}:wireguard={wg_interface}:target={target_host}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def protected_evidence_path(args: argparse.Namespace) -> str:
    if args.protected_evidence_path:
        return args.protected_evidence_path
    return f"github-actions://Halildeu/platform-k8s-gitops/actions/runs/{args.github_run_id}"


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


def collect_iptables(pod_cidr: str, wg_interface: str, target_host: str) -> dict[str, Any]:
    commands: list[list[str]] = []
    for binary in ["iptables", "iptables-nft", "iptables-legacy"]:
        commands.extend(host_command_variants(binary, ["-t", "nat", "-S", "POSTROUTING"], sudo=True))
    commands.extend(host_command_variants("iptables-save", ["-t", "nat"], sudo=True))
    result = first_success(commands, timeout=10)
    lines = result.stdout.splitlines() if result.exit_code == 0 else []
    target_networks = {f"{target_host}/32"}
    try:
        ip = ipaddress.ip_address(target_host)
        if ip.version == 4:
            target_networks.add(str(ipaddress.ip_network(f"{target_host}/24", strict=False)))
    except ValueError:
        pass

    expected_present = False
    scoped_to_wg = False
    broad_nat = False
    matching_rule_count = 0

    for line in lines:
        if "-j MASQUERADE" not in line or "POSTROUTING" not in line:
            continue
        if re.search(r"(^|\s)-s\s+0\.0\.0\.0/0(\s|$)", line):
            broad_nat = True
        if re.search(r"(^|\s)-s\s+10\.0\.0\.0/8(\s|$)", line):
            broad_nat = True

        source_matches = re.search(rf"(^|\s)-s\s+{re.escape(pod_cidr)}(\s|$)", line) is not None
        if not source_matches:
            continue
        matching_rule_count += 1
        expected_present = True
        if re.search(rf"(^|\s)-o\s+{re.escape(wg_interface)}(\s|$)", line):
            scoped_to_wg = True
        for network in target_networks:
            if re.search(rf"(^|\s)-d\s+{re.escape(network)}(\s|$)", line):
                scoped_to_wg = True

    return {
        "probeExitCode": result.exit_code,
        "queryable": result.exit_code == 0,
        "expectedRulePresent": expected_present,
        "matchingRuleCount": matching_rule_count,
        "scopedToWireGuardPath": scoped_to_wg,
        "broadNatDetected": broad_nat,
    }


def collect_pod_http_probe(
    kube_context: str,
    namespace: str,
    target_host: str,
    target_port: int,
    path: str,
) -> dict[str, Any]:
    pods = first_success(
        command_variants("kubectl", ["--context", kube_context, "-n", namespace, "get", "pods", "-o", "json"]),
        timeout=15,
    )
    if pods.exit_code != 0:
        return {"probeExitCode": pods.exit_code, "podSelected": None, "httpStatus": None, "statusClass": None}

    try:
        payload = json.loads(pods.stdout)
    except json.JSONDecodeError:
        return {"probeExitCode": 1, "podSelected": None, "httpStatus": None, "statusClass": None}

    url = f"http://{target_host}:{target_port}{path if path.startswith('/') else '/' + path}"
    for item in payload.get("items", []):
        pod_name = item.get("metadata", {}).get("name", "")
        phase = item.get("status", {}).get("phase")
        if phase != "Running" or not pod_name:
            continue
        probe = first_success(
            command_variants(
                "kubectl",
                [
                    "--context",
                    kube_context,
                    "-n",
                    namespace,
                    "exec",
                    pod_name,
                    "--",
                    "sh",
                    "-c",
                    (
                        "if command -v curl >/dev/null 2>&1; then "
                        "curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \"$0\"; "
                        "elif command -v wget >/dev/null 2>&1; then "
                        "wget -q -T 5 -O /dev/null --server-response \"$0\" 2>&1 "
                        "| awk '/HTTP\\//{code=$2} END{print code+0}'; "
                        "else exit 127; fi"
                    ),
                    url,
                ],
            ),
            timeout=20,
        )
        code_match = re.search(r"\b([1-5][0-9][0-9])\b", probe.stdout)
        http_status = int(code_match.group(1)) if code_match else None
        if http_status is not None:
            return {
                "probeExitCode": probe.exit_code,
                "podSelectedHash": sha256_short(pod_name),
                "httpStatus": http_status,
                "statusClass": f"{http_status // 100}xx",
            }

    return {"probeExitCode": 1, "podSelected": None, "httpStatus": None, "statusClass": None}


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
    pod_cidr = normalize_cidr(args.pod_cidr)
    if pod_cidr is None:
        pod_cidr = args.pod_cidr

    wg_interface, wg_meta = parse_wg_interface(args.wg_interface)
    host = safe_name(socket.gethostname(), "staging-sw")
    route = collect_route_interface(args.platform_ai_host)
    systemd = collect_systemd(args.systemd_unit, args.drift_timer)
    iptables = collect_iptables(pod_cidr, wg_interface, args.platform_ai_host)
    pod_probe = collect_pod_http_probe(
        args.kube_context,
        args.namespace,
        args.platform_ai_host,
        args.platform_ai_port,
        args.probe_path,
    )

    rule_hash = expected_rule_hash(pod_cidr, wg_interface, args.platform_ai_host, args.platform_ai_port)
    rb_hash = rollback_hash(args.systemd_unit, pod_cidr, wg_interface, args.platform_ai_host)

    route_is_wg = route.get("targetRouteInterface") == wg_interface
    host_rule_present = bool(iptables["queryable"] and iptables["expectedRulePresent"])
    pod_rule_pass = bool(host_rule_present and (iptables["scopedToWireGuardPath"] or route_is_wg))
    http_pass = pod_probe.get("httpStatus") is not None and 200 <= int(pod_probe["httpStatus"]) < 500
    persistence_pass = bool(systemd["enabled"] and systemd["active"] and systemd["hasExecStart"])
    drift_pass = bool(systemd["driftTimerActive"] or systemd["driftTimerEnabled"])
    rollback_pass = bool(systemd["hasExecStop"] and args.rollback_tested_ref)
    no_broad_nat_pass = bool(iptables["queryable"] and not iptables["broadNatDetected"])

    checks = [
        check(
            "host-namespace-nat-rule-present",
            host_rule_present,
            collected_at,
            "Expected host NAT rule metadata is present" if host_rule_present else "Expected host NAT rule metadata is missing or not queryable",
        ),
        check(
            "pod-cidr-to-wg-masq-rule",
            pod_rule_pass,
            collected_at,
            "Pod CIDR MASQ rule is scoped to WireGuard path" if pod_rule_pass else "Pod CIDR MASQ rule is not proven scoped to WireGuard path",
        ),
        check(
            "pod-to-platform-ai-http",
            http_pass,
            collected_at,
            f"Pod-origin HTTP probe status class {pod_probe.get('statusClass')}" if http_pass else "Pod-origin HTTP probe did not return bounded HTTP status",
        ),
        check(
            "reboot-persistence",
            persistence_pass,
            collected_at,
            "Systemd unit is enabled and active in current boot" if persistence_pass else "Systemd persistence is not proven by enabled active unit metadata",
        ),
        check(
            "drift-detect",
            drift_pass,
            collected_at,
            "Systemd drift timer metadata is active or enabled" if drift_pass else "Systemd drift timer metadata is missing or inactive",
        ),
        check(
            "rollback-defined",
            rollback_pass,
            collected_at,
            "Rollback ExecStop and tested evidence reference are present" if rollback_pass else "Rollback tested evidence reference or ExecStop metadata is missing",
        ),
        check(
            "daemonset-not-assumed",
            True,
            collected_at,
            "Evidence authority is host-managed systemd iptables, not Kubernetes DaemonSet",
        ),
        check(
            "no-broad-lan-nat",
            no_broad_nat_pass,
            collected_at,
            "No broad LAN NAT was detected in POSTROUTING metadata" if no_broad_nat_pass else "Broad LAN NAT absence is not proven",
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
            "podCIDR": pod_cidr,
            "wgInterface": wg_interface,
            "platformAiTarget": {
                "host": args.platform_ai_host,
                "port": args.platform_ai_port,
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
            "route": route,
            "iptables": iptables,
            "systemd": systemd,
            "podProbe": pod_probe,
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
    parser.add_argument("--pod-cidr", default=os.environ.get("POD_CIDR", "10.42.0.0/16"))
    parser.add_argument("--service-cidr", default=os.environ.get("SERVICE_CIDR", ""))
    parser.add_argument("--wg-interface", default=os.environ.get("WG_INTERFACE", "auto"))
    parser.add_argument("--platform-ai-host", default=os.environ.get("PLATFORM_AI_HOST", "10.99.0.2"))
    parser.add_argument("--platform-ai-port", type=int, default=int(os.environ.get("PLATFORM_AI_PORT", "8200")))
    parser.add_argument("--probe-path", default=os.environ.get("PROBE_PATH", "/"))
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
