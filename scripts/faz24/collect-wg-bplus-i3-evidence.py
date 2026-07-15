#!/usr/bin/env python3
"""Collect metadata-only Faz 24 WG-B+ I3 management audit evidence.

This collector is designed for the self-hosted staging-sw runner. It creates a
bounded JSON bundle for the existing I3 verifier without exporting command
contents, transcript text, raw audio, token material, or private keys.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = "faz24.wg-bplus.i3.audit.v2"
CONTROL_CONTRACT_VERSION = "faz24.windows-audit-control.v1"
SNAPSHOT_SCHEMA_VERSION = "faz24.windows-audit-snapshot.v1"
DEFAULT_REMOTE_SNAPSHOT_PATH = (
    r"C:\ProgramData\Acik\Faz24\I3\audit-controls\snapshot\audit-snapshot.json"
)
DEFAULT_DENETIM_TARGET = "svc-denetim-agent@10.99.0.2"
DEFAULT_WG_INTERFACE = "auto"
DEFAULT_RETENTION_DAYS = 14
DEFAULT_SSH_IDENTITY_PATH = "~/.ssh/faz24-i3-denetim_ed25519"
WG_BINARY_CANDIDATES = [
    "wg",
    "/usr/bin/wg",
    "/usr/sbin/wg",
    "/usr/local/bin/wg",
    "/snap/bin/wg",
    "/opt/homebrew/bin/wg",
]

CHECK_ORDER = [
    "openssh-event-log",
    "powershell-transcription",
    "powershell-script-block",
    "failed-login",
    "wireguard-health",
    "eset-firewall-drift",
    "time-sync",
    "staging-connection-log",
]

POWERSHELL_COLLECTOR = r'''
$ErrorActionPreference = "SilentlyContinue"
$lookbackHours = __LOOKBACK_HOURS__
$snapshotPath = "__SNAPSHOT_PATH__"
$now = (Get-Date).ToUniversalTime()
$since = $now.AddHours(-1 * $lookbackHours)

function To-UtcText($value) {
  if ($null -eq $value) { return $null }
  return $value.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function Count-Array($value) {
  if ($null -eq $value) { return 0 }
  return @($value).Count
}

$checks = [ordered]@{}

try {
  $events = @(Get-WinEvent -LogName "OpenSSH/Operational" -ErrorAction Stop |
    Where-Object { $_.TimeCreated.ToUniversalTime() -ge $since } |
    Select-Object TimeCreated, Id, LevelDisplayName)
  $latest = $events | Sort-Object TimeCreated -Descending | Select-Object -First 1
  $checks.opensshEventLog = [ordered]@{
    ok = ((Count-Array $events) -gt 0)
    queryOk = $true
    count = Count-Array $events
    latestUtc = To-UtcText $latest.TimeCreated
  }
} catch {
  $checks.opensshEventLog = [ordered]@{ ok = $false; queryOk = $false; count = 0; errorClass = $_.Exception.GetType().Name }
}

try {
  $rawSnapshot = Get-Content -LiteralPath $snapshotPath -Raw -Encoding UTF8 -ErrorAction Stop
  $snapshot = $rawSnapshot | ConvertFrom-Json -ErrorAction Stop
  $schemaOk = ($snapshot.schemaVersion -eq "faz24.windows-audit-snapshot.v1")
  $controlsPresent = ($null -ne $snapshot.controls)
  $checks.auditSnapshot = [ordered]@{
    ok = ($schemaOk -and $controlsPresent)
    queryOk = $true
    schemaVersion = [string]$snapshot.schemaVersion
    collectedAt = [string]$snapshot.collectedAt
    controls = $snapshot.controls
  }
} catch {
  $checks.auditSnapshot = [ordered]@{
    ok = $false
    queryOk = $false
    schemaVersion = ""
    collectedAt = ""
    controls = $null
    errorClass = $_.Exception.GetType().Name
  }
}

[ordered]@{
  collectedAt = $now.ToString("yyyy-MM-ddTHH:mm:ssZ")
  checks = $checks
} | ConvertTo-Json -Depth 8 -Compress
'''


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], str | None, int], CommandResult]
TcpProbeRunner = Callable[[str, int, int], dict[str, Any]]


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def bounded(value: str, max_len: int = 180) -> str:
    clean = re.sub(r"\s+", " ", value).strip()
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 3].rstrip() + "..."


def run_command(argv: list[str], stdin: str | None = None, timeout: int = 30) -> CommandResult:
    try:
        proc = subprocess.run(
            argv,
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return CommandResult(127, "", "command-not-found")
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", "timeout")
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


def non_empty_lines(value: str) -> list[str]:
    return [line for line in value.splitlines() if line.strip()]


def safe_interface_name(value: str) -> str | None:
    clean = value.strip()
    if clean and re.match(r"^[A-Za-z0-9_.:-]+$", clean):
        return clean
    return None


def parse_ssh_target_host(target: str) -> str:
    if "@" not in target:
        return target
    return target.rsplit("@", 1)[1]


def is_ip_literal(value: str) -> bool:
    return bool(re.match(r"^[0-9.]+$", value) or ":" in value)


def inspect_ssh_identity(identity_path: str | None) -> dict[str, Any]:
    if identity_path is None or not identity_path.strip():
        return {
            "sshIdentityConfigured": False,
            "sshIdentityPathHash": "",
            "sshIdentityPublicKeyPresent": False,
            "sshIdentityPublicKeyFingerprint": "",
        }

    path = Path(identity_path).expanduser()
    public_path = path.with_name(path.name + ".pub")
    public_key = ""
    if public_path.exists():
        try:
            public_key = public_path.read_text(encoding="utf-8").strip()
        except OSError:
            public_key = ""

    return {
        "sshIdentityConfigured": path.exists(),
        "sshIdentityPathHash": sha256_short(str(path)),
        "sshIdentityPublicKeyPresent": bool(public_key),
        "sshIdentityPublicKeyFingerprint": sha256_short(public_key) if public_key else "",
    }


def classify_socket_error(exc: OSError) -> str:
    text = str(exc).lower()
    errno_value = getattr(exc, "errno", None)
    if isinstance(exc, socket.timeout) or "timed out" in text:
        return "tcp-timeout"
    if errno_value in {61, 111} or "connection refused" in text:
        return "tcp-port-refused"
    if errno_value in {51, 101} or "network is unreachable" in text:
        return "tcp-network-unreachable"
    if errno_value in {64, 113, 65} or "no route to host" in text:
        return "tcp-host-unreachable"
    if "name or service not known" in text or "nodename nor servname" in text:
        return "tcp-dns-resolution"
    return "tcp-error"


def probe_tcp_connect(host: str, port: int, timeout_seconds: int) -> dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return {
                "tcp22Reachable": True,
                "tcp22ErrorClass": "",
                "tcp22Errno": None,
            }
    except OSError as exc:
        return {
            "tcp22Reachable": False,
            "tcp22ErrorClass": classify_socket_error(exc),
            "tcp22Errno": getattr(exc, "errno", None),
        }


def classify_ssh_failure(result: CommandResult, tcp_reachable: bool) -> str:
    if result.returncode == 0:
        return "none"

    text = f"{result.stderr}\n{result.stdout}".lower()
    if result.returncode == 124 or "timed out" in text or "operation timed out" in text:
        return "ssh-timeout"
    if "could not resolve hostname" in text or "name or service not known" in text:
        return "ssh-dns-resolution"
    if "no route to host" in text or "network is unreachable" in text:
        return "ssh-network-route"
    if "connection refused" in text:
        return "ssh-port-refused"
    if "host key verification failed" in text or "remote host identification has changed" in text:
        return "ssh-hostkey"
    if "permission denied" in text and "publickey" in text:
        return "ssh-auth-publickey"
    if "permission denied" in text:
        return "ssh-auth-denied"
    if "kex_exchange_identification" in text or "connection reset" in text:
        return "ssh-handshake-reset"
    if "connection closed" in text or "closed by remote host" in text:
        return "ssh-handshake-closed"
    if result.returncode == 255 and not tcp_reachable:
        return "ssh-exit-255-after-tcp-failure"
    if result.returncode == 255:
        return "ssh-exit-255-unclassified"
    return f"ssh-exit-{result.returncode}"


def collect_denetim_ssh_preflight(
    runner: CommandRunner,
    tcp_probe: TcpProbeRunner,
    target: str,
    ssh_result: CommandResult,
    timeout_seconds: int,
    ssh_identity_metadata: dict[str, Any],
    selected_wireguard_interface_hash: str,
) -> dict[str, Any]:
    host = parse_ssh_target_host(target)
    route = runner(["ip", "route", "get", host], None, timeout_seconds)
    tcp = tcp_probe(host, 22, timeout_seconds)
    tcp_reachable = tcp.get("tcp22Reachable") is True
    ssh_output = f"{ssh_result.stderr}\n{ssh_result.stdout}"
    route_device_match = re.search(r"(?:^|\s)dev\s+(\S+)", route.stdout)
    route_device_hash = (
        sha256_short(route_device_match.group(1)) if route_device_match else ""
    )
    route_uses_selected_wireguard_interface = bool(
        route.returncode == 0
        and route_device_hash
        and selected_wireguard_interface_hash
        and route_device_hash == selected_wireguard_interface_hash
    )

    return {
        "targetHostHash": sha256_short(host),
        "targetPort": 22,
        "targetHostIsIpLiteral": is_ip_literal(host),
        "routeQueryable": route.returncode == 0,
        "routeExitCode": route.returncode,
        "routeDeviceHash": route_device_hash,
        "routeUsesSelectedWireGuardInterface": route_uses_selected_wireguard_interface,
        "tcp22Reachable": tcp_reachable,
        "tcp22ErrorClass": bounded(str(tcp.get("tcp22ErrorClass", "")), 80),
        "tcp22Errno": tcp.get("tcp22Errno"),
        "sshExitCode": ssh_result.returncode,
        "sshFailureClass": classify_ssh_failure(ssh_result, tcp_reachable),
        "sshStdoutPresent": bool(ssh_result.stdout.strip()),
        "sshStderrPresent": bool(ssh_result.stderr.strip()),
        "sshErrorFingerprint": sha256_short(ssh_output) if ssh_output.strip() else "",
        "sshIdentityConfigured": bool(ssh_identity_metadata["sshIdentityConfigured"]),
        "sshIdentityPathHash": str(ssh_identity_metadata["sshIdentityPathHash"]),
        "sshIdentityPublicKeyPresent": bool(
            ssh_identity_metadata["sshIdentityPublicKeyPresent"]
        ),
        "sshIdentityPublicKeyFingerprint": str(
            ssh_identity_metadata["sshIdentityPublicKeyFingerprint"]
        ),
    }


def run_with_sudo_fallback(
    runner: CommandRunner,
    argv: list[str],
    timeout_seconds: int,
) -> CommandResult:
    result = runner(argv, None, timeout_seconds)
    if result.returncode == 0 or not shutil.which("sudo"):
        return result
    sudo_result = runner(["sudo", "-n", *argv], None, timeout_seconds)
    return sudo_result if sudo_result.returncode == 0 else result


def resolve_wg_binary(
    runner: CommandRunner,
    timeout_seconds: int,
) -> tuple[str, dict[str, Any]]:
    first_exit_code: int | None = None
    for candidate in WG_BINARY_CANDIDATES:
        result = run_with_sudo_fallback(runner, [candidate, "--version"], timeout_seconds)
        if first_exit_code is None:
            first_exit_code = result.returncode
        if result.returncode == 0:
            return candidate, {
                "wgToolFound": True,
                "wgToolKind": "path-search" if candidate == "wg" else "absolute-path",
                "wgToolProbeExitCode": result.returncode,
            }

    return "wg", {
        "wgToolFound": False,
        "wgToolKind": "unavailable",
        "wgToolProbeExitCode": first_exit_code if first_exit_code is not None else 127,
    }


def discover_wg_interfaces(
    runner: CommandRunner,
    wg_binary: str,
    wg_interface: str,
    timeout_seconds: int,
) -> tuple[list[str], dict[str, Any]]:
    if wg_interface != "auto":
        return [wg_interface], {
            "requestedMode": "explicit",
            "requestedInterfaceHash": sha256_short(wg_interface),
            "interfacesQueryable": False,
            "detectedCount": 0,
        }

    result = run_with_sudo_fallback(runner, [wg_binary, "show", "interfaces"], timeout_seconds)
    interfaces = [
        clean
        for token in result.stdout.split()
        if (clean := safe_interface_name(token)) is not None
    ]
    return interfaces, {
        "requestedMode": "auto",
        "requestedInterfaceHash": "",
        "interfacesQueryable": result.returncode == 0,
        "interfacesExitCode": result.returncode,
        "detectedCount": len(interfaces),
    }


def collect_wg_interface_metadata(
    runner: CommandRunner,
    wg_binary: str,
    interface_name: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    wg_latest = run_with_sudo_fallback(
        runner,
        [wg_binary, "show", interface_name, "latest-handshakes"],
        timeout_seconds,
    )
    wg_transfer = run_with_sudo_fallback(
        runner,
        [wg_binary, "show", interface_name, "transfer"],
        timeout_seconds,
    )
    wg_endpoints = run_with_sudo_fallback(
        runner,
        [wg_binary, "show", interface_name, "endpoints"],
        timeout_seconds,
    )
    peer_count = max(
        len(non_empty_lines(wg_latest.stdout)),
        len(non_empty_lines(wg_transfer.stdout)),
        len(non_empty_lines(wg_endpoints.stdout)),
    )
    ok = all(result.returncode == 0 for result in [wg_latest, wg_transfer, wg_endpoints])
    return {
        "interface": interface_name,
        "ok": ok,
        "peerCount": peer_count,
        "latestExitCode": wg_latest.returncode,
        "transferExitCode": wg_transfer.returncode,
        "endpointsExitCode": wg_endpoints.returncode,
    }


def json_from_stdout(stdout: str) -> dict[str, Any] | None:
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(stdout[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def build_powershell_collector(
    lookback_hours: int,
    snapshot_path: str = DEFAULT_REMOTE_SNAPSHOT_PATH,
) -> str:
    if not re.match(r"^[A-Za-z]:\\[A-Za-z0-9 ._\\-]+$", snapshot_path):
        raise ValueError("remote snapshot path contains unsupported characters")
    return (
        POWERSHELL_COLLECTOR.replace("__LOOKBACK_HOURS__", str(lookback_hours))
        .replace("__SNAPSHOT_PATH__", snapshot_path)
    )


def default_protected_path(timestamp: str) -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "Halildeu/platform-k8s-gitops")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if run_id:
        return (
            f"github-actions://{repository}/actions/runs/{run_id}/"
            "artifacts/faz24-wg-bplus-i3-evidence"
        )
    return f"local://faz24-wg-bplus-i3-evidence/{timestamp}"


def make_check(
    check_id: str,
    status: str,
    who: str,
    when: str,
    what: str,
    evidence_ref: str,
    control: dict[str, Any],
) -> dict[str, Any]:
    check: dict[str, Any] = {
        "id": check_id,
        "status": status,
        "who": bounded(who, 120),
        "when": when,
        "what": bounded(what, 200),
        "evidenceRef": evidence_ref,
        "control": control,
    }
    return check


def control_contract(
    *,
    expected: dict[str, Any],
    observed: dict[str, Any],
    verdict: str,
    source_kind: str,
    source_locator: str,
    collected_at: str,
    bundle_collected_at: str,
    max_age_seconds: int,
    error_class: str = "none",
) -> dict[str, Any]:
    fresh = False
    try:
        observed_time = datetime.strptime(collected_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        bundle_time = datetime.strptime(
            bundle_collected_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        age_seconds = int((bundle_time - observed_time).total_seconds())
        fresh = -300 <= age_seconds <= max_age_seconds
    except (TypeError, ValueError):
        age_seconds = None

    effective_verdict = verdict if fresh else "fail"
    effective_error = error_class
    if not fresh and effective_error == "none":
        effective_error = "stale-or-invalid-snapshot"

    return {
        "contractVersion": CONTROL_CONTRACT_VERSION,
        "expected": expected,
        "observed": observed,
        "verdict": effective_verdict,
        "source": {
            "kind": source_kind,
            "locator": source_locator,
        },
        "collectedAt": collected_at,
        "maxAgeSeconds": max_age_seconds,
        "ageSeconds": age_seconds,
        "fresh": fresh,
        "errorClass": bounded(effective_error or "none", 80),
    }


def snapshot_controls(remote: dict[str, Any] | None) -> tuple[dict[str, Any], str, str]:
    snapshot = remote_check(remote, "auditSnapshot")
    if not bool_field(snapshot, "ok"):
        return {}, "", bounded(str(snapshot.get("errorClass", "snapshot-unavailable")), 80)
    if snapshot.get("schemaVersion") != SNAPSHOT_SCHEMA_VERSION:
        return {}, str(snapshot.get("collectedAt", "")), "snapshot-schema-mismatch"
    controls = snapshot.get("controls")
    if not isinstance(controls, dict):
        return {}, str(snapshot.get("collectedAt", "")), "snapshot-controls-missing"
    return controls, str(snapshot.get("collectedAt", "")), "none"


def snapshot_control(
    controls: dict[str, Any],
    check_id: str,
) -> dict[str, Any]:
    value = controls.get(check_id)
    return value if isinstance(value, dict) else {}


def normalized_snapshot_contract(
    *,
    record: dict[str, Any],
    snapshot_collected_at: str,
    bundle_collected_at: str,
    snapshot_error_class: str,
) -> dict[str, Any]:
    if not record:
        return control_contract(
            expected={},
            observed={},
            verdict="fail",
            source_kind="windows-system-snapshot",
            source_locator="faz24-i3-audit-snapshot",
            collected_at=snapshot_collected_at,
            bundle_collected_at=bundle_collected_at,
            max_age_seconds=900,
            error_class=(
                snapshot_error_class
                if snapshot_error_class != "none"
                else "snapshot-control-missing"
            ),
        )

    expected = record.get("expected")
    observed = record.get("observed")
    max_age = record.get("maxAgeSeconds", 900)
    if not isinstance(expected, dict):
        expected = {}
    if not isinstance(observed, dict):
        observed = {}
    if not isinstance(max_age, int) or not 60 <= max_age <= 86_400:
        max_age = 900

    record_error = str(record.get("errorClass", "none"))
    error_class = snapshot_error_class if snapshot_error_class != "none" else record_error
    verdict = str(record.get("verdict", "fail"))
    if record.get("contractVersion") != CONTROL_CONTRACT_VERSION:
        verdict = "fail"
        error_class = "snapshot-control-contract-mismatch"
    if verdict not in {"pass", "fail"}:
        verdict = "fail"
        error_class = "invalid-control-verdict"

    return control_contract(
        expected=expected,
        observed=observed,
        verdict=verdict,
        source_kind="windows-system-snapshot",
        source_locator="faz24-i3-audit-snapshot",
        collected_at=str(record.get("collectedAt", snapshot_collected_at)),
        bundle_collected_at=bundle_collected_at,
        max_age_seconds=max_age,
        error_class=error_class,
    )


def control_summary(check_id: str, contract: dict[str, Any]) -> str:
    observed = contract.get("observed")
    if not isinstance(observed, dict):
        observed = {}

    if check_id == "powershell-transcription":
        return "PowerShell transcription policy and protected output ACL metadata evaluated"
    if check_id == "powershell-script-block":
        return f"Script-block logging metadata eventCount={int_field(observed, 'eventCount')}; content omitted"
    if check_id == "failed-login":
        return f"Security log query succeeded with failedLogonCount={int_field(observed, 'eventCount')}; identities omitted"
    if check_id == "wireguard-health":
        return (
            "WireGuard metadata "
            f"interfaces={int_field(observed, 'interfaceCount')} "
            f"peers={int_field(observed, 'peerCount')} "
            f"latestHandshakeAgeSeconds={observed.get('latestHandshakeAgeSeconds')}"
        )
    if check_id == "eset-firewall-drift":
        return (
            "Firewall/ESET metadata "
            f"expectedRules={int_field(observed, 'expectedRuleMatchCount')}/"
            f"{int_field(observed, 'expectedRuleCount')} "
            f"broadConflicts={int_field(observed, 'broadConflictCount')}"
        )
    if check_id == "time-sync":
        return (
            "Time-sync metadata "
            f"serviceState={bounded(str(observed.get('serviceState', 'unknown')), 24)} "
            f"latestSuccessEventAgeSeconds={observed.get('latestSuccessEventAgeSeconds')}"
        )
    return "Bounded metadata control evaluated"


def collect_staging_metadata(
    runner: CommandRunner,
    wg_interface: str,
    timeout_seconds: int,
    *,
    attempt_started_at: datetime,
    remote_collector_succeeded: bool,
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    correlation_id = uuid.uuid4().hex
    outcome = "success" if remote_collector_succeeded else "failure"
    audit_write = runner(
        [
            "logger",
            "--tag",
            "faz24-i3-audit",
            "--",
            f"correlation={correlation_id} outcome={outcome}",
        ],
        None,
        timeout_seconds,
    )
    query_finished_at = clock().astimezone(timezone.utc).replace(microsecond=0)
    since_epoch = int(attempt_started_at.astimezone(timezone.utc).timestamp()) - 5
    until_epoch = int(query_finished_at.timestamp()) + 5
    journal_cmd = [
        "journalctl",
        "-t",
        "faz24-i3-audit",
        "--since",
        f"@{since_epoch}",
        "--until",
        f"@{until_epoch}",
        "--no-pager",
        "--output=cat",
    ]
    journal = run_with_sudo_fallback(runner, journal_cmd, timeout_seconds)

    journal_lines = non_empty_lines(journal.stdout)
    journal_matches = [
        line
        for line in journal_lines
        if f"correlation={correlation_id}" in line and f"outcome={outcome}" in line
    ]

    wg_binary, wg_tool_probe = resolve_wg_binary(runner, timeout_seconds)
    candidate_interfaces, wg_probe = discover_wg_interfaces(
        runner,
        wg_binary,
        wg_interface,
        timeout_seconds,
    )
    wg_probe.update(wg_tool_probe)
    interface_probes = [
        collect_wg_interface_metadata(runner, wg_binary, interface_name, timeout_seconds)
        for interface_name in candidate_interfaces
    ]
    selected_probe = next((probe for probe in interface_probes if probe["ok"]), None)
    if selected_probe is None and interface_probes:
        selected_probe = interface_probes[0]

    ss_result = runner(
        ["ss", "-Htn", "state", "established", "( sport = :22 or dport = :22 )"],
        None,
        timeout_seconds,
    )

    wg_ok = bool(selected_probe and selected_probe["ok"])
    wg_peer_count = int(selected_probe["peerCount"]) if selected_probe else 0
    wg_probe["selectedInterfaceHash"] = (
        sha256_short(str(selected_probe["interface"])) if selected_probe else ""
    )
    wg_probe["probeCount"] = len(interface_probes)
    wg_probe["selectedLatestExitCode"] = (
        selected_probe["latestExitCode"] if selected_probe else None
    )
    wg_probe["selectedTransferExitCode"] = (
        selected_probe["transferExitCode"] if selected_probe else None
    )
    wg_probe["selectedEndpointsExitCode"] = (
        selected_probe["endpointsExitCode"] if selected_probe else None
    )

    return {
        "journalOk": journal.returncode == 0,
        "journalMatchCount": len(journal_matches),
        "auditRecordWritten": audit_write.returncode == 0,
        "journalSinceAttemptStart": True,
        "correlationWindowSeconds": max(
            0,
            int(
                (
                    query_finished_at
                    - attempt_started_at.astimezone(timezone.utc).replace(microsecond=0)
                ).total_seconds()
            ),
        ),
        "wgOk": wg_ok,
        "wgPeerCount": wg_peer_count,
        "wgProbe": wg_probe,
        "sshSocketOk": ss_result.returncode == 0,
        "sshSocketCount": len(non_empty_lines(ss_result.stdout)),
    }


def collect_denetim_metadata(
    runner: CommandRunner,
    target: str,
    lookback_hours: int,
    connect_timeout_seconds: int,
    ssh_identity_path: str | None,
) -> tuple[dict[str, Any] | None, CommandResult]:
    script = build_powershell_collector(lookback_hours)
    encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    identity_metadata = inspect_ssh_identity(ssh_identity_path)
    identity_args: list[str] = []
    if identity_metadata["sshIdentityConfigured"] and ssh_identity_path is not None:
        identity_args = [
            "-i",
            str(Path(ssh_identity_path).expanduser()),
            "-o",
            "IdentitiesOnly=yes",
        ]
    ssh = runner(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"ConnectTimeout={connect_timeout_seconds}",
            "-o",
            "ServerAliveInterval=5",
            "-o",
            "ServerAliveCountMax=2",
            *identity_args,
            target,
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded_script,
        ],
        None,
        max(60, connect_timeout_seconds + 45),
    )
    if ssh.returncode != 0:
        return None, ssh
    return json_from_stdout(ssh.stdout), ssh


def remote_check(remote: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if remote is None:
        return {}
    checks = remote.get("checks")
    if not isinstance(checks, dict):
        return {}
    value = checks.get(key)
    return value if isinstance(value, dict) else {}


def bool_field(data: dict[str, Any], key: str) -> bool:
    return data.get(key) is True


def int_field(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    return value if isinstance(value, int) else 0


def build_evidence(
    *,
    timestamp: datetime,
    protected_path: str,
    retention_days: int,
    denetim_target: str,
    lookback_hours: int,
    wg_interface: str,
    connect_timeout_seconds: int,
    runner: CommandRunner,
    tcp_probe: TcpProbeRunner = probe_tcp_connect,
    ssh_identity_path: str | None = DEFAULT_SSH_IDENTITY_PATH,
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    now = utc_text(timestamp)
    target_hash = sha256_short(denetim_target)

    attempt_started_at = clock().astimezone(timezone.utc).replace(microsecond=0)
    remote, ssh_result = collect_denetim_metadata(
        runner,
        target=denetim_target,
        lookback_hours=lookback_hours,
        connect_timeout_seconds=connect_timeout_seconds,
        ssh_identity_path=ssh_identity_path,
    )
    remote_ok = remote is not None and ssh_result.returncode == 0
    staging = collect_staging_metadata(
        runner,
        wg_interface=wg_interface,
        timeout_seconds=connect_timeout_seconds,
        attempt_started_at=attempt_started_at,
        remote_collector_succeeded=remote_ok,
        clock=clock,
    )
    ssh_identity_metadata = inspect_ssh_identity(ssh_identity_path)
    denetim_ssh_preflight = collect_denetim_ssh_preflight(
        runner,
        tcp_probe,
        denetim_target,
        ssh_result,
        connect_timeout_seconds,
        ssh_identity_metadata,
        str(staging["wgProbe"]["selectedInterfaceHash"]),
    )
    if not remote_ok:
        ssh_failure = f"Denetim SSH metadata collector failed with exit {ssh_result.returncode}"
        remote_who = f"windows-transport-target:{target_hash}"
        remote_failure_class = bounded(
            str(denetim_ssh_preflight.get("sshFailureClass", "ssh-collector-failed")),
            80,
        )
        checks = []
        for check_id in CHECK_ORDER:
            if check_id == "staging-connection-log":
                continue
            contract = control_contract(
                expected={"remoteCollectorReached": True},
                observed={
                    "remoteCollectorReached": False,
                    "sshExitCode": ssh_result.returncode,
                },
                verdict="fail",
                source_kind="windows-ssh-metadata",
                source_locator="denetim-remote-collector",
                collected_at=now,
                bundle_collected_at=now,
                max_age_seconds=900,
                error_class=remote_failure_class,
            )
            checks.append(
                make_check(
                    check_id,
                    "fail",
                    remote_who,
                    now,
                    ssh_failure,
                    f"windows/{check_id}.metadata.json",
                    contract,
                )
            )
    else:
        openssh = remote_check(remote, "opensshEventLog")
        openssh_status = "pass" if bool_field(openssh, "ok") else "fail"
        openssh_contract = control_contract(
            expected={"queryOk": True, "minimumEventCount": 1},
            observed={
                "queryOk": bool_field(openssh, "queryOk"),
                "eventCount": int_field(openssh, "count"),
            },
            verdict=openssh_status,
            source_kind="windows-event-log",
            source_locator="OpenSSH/Operational",
            collected_at=now,
            bundle_collected_at=now,
            max_age_seconds=900,
            error_class=bounded(str(openssh.get("errorClass", "none")), 80),
        )

        checks = [
            make_check(
                "openssh-event-log",
                openssh_contract["verdict"],
                f"windows-transport-target:{target_hash}",
                now,
                f"OpenSSH metadata query count={int_field(openssh, 'count')} over {lookback_hours}h",
                "windows/openssh-event-log.metadata.json",
                openssh_contract,
            ),
        ]

        controls, snapshot_collected_at, snapshot_error_class = snapshot_controls(remote)
        snapshot_who = {
            "powershell-transcription": "windows-system:audit-snapshot/powershell-policy",
            "powershell-script-block": "windows-system:audit-snapshot/powershell-events",
            "failed-login": "windows-system:audit-snapshot/security-audit",
            "wireguard-health": "windows-system:audit-snapshot/wireguard",
            "eset-firewall-drift": "windows-system:audit-snapshot/firewall-eset",
            "time-sync": "windows-system:audit-snapshot/time-service",
        }
        for check_id in CHECK_ORDER[1:7]:
            contract = normalized_snapshot_contract(
                record=snapshot_control(controls, check_id),
                snapshot_collected_at=snapshot_collected_at,
                bundle_collected_at=now,
                snapshot_error_class=snapshot_error_class,
            )
            checks.append(
                make_check(
                    check_id,
                    str(contract["verdict"]),
                    snapshot_who[check_id],
                    str(contract["collectedAt"]),
                    control_summary(check_id, contract),
                    f"windows/{check_id}.metadata.json",
                    contract,
                )
            )

    staging_ok = (
        remote_ok
        and bool(staging["wgOk"])
        and int(staging["wgPeerCount"]) > 0
        and bool(staging["auditRecordWritten"])
        and bool(staging["journalOk"])
        and int(staging["journalMatchCount"]) > 0
        and bool(staging["journalSinceAttemptStart"])
        and int(staging["correlationWindowSeconds"]) <= 180
        and bool(staging["sshSocketOk"])
        and bool(denetim_ssh_preflight["routeUsesSelectedWireGuardInterface"])
    )
    staging_contract = control_contract(
        expected={
            "remoteCollectorReached": True,
            "wireGuardQueryable": True,
            "minimumPeerCount": 1,
            "journalQueryable": True,
            "minimumJournalMatchCount": 1,
            "auditRecordWritten": True,
            "journalSinceAttemptStart": True,
            "maximumCorrelationWindowSeconds": 180,
            "sshSocketQueryable": True,
            "routeUsesSelectedWireGuardInterface": True,
        },
        observed={
            "remoteCollectorReached": remote_ok,
            "wireGuardQueryable": bool(staging["wgOk"]),
            "peerCount": int(staging["wgPeerCount"]),
            "journalQueryable": bool(staging["journalOk"]),
            "journalMatchCount": int(staging["journalMatchCount"]),
            "auditRecordWritten": bool(staging["auditRecordWritten"]),
            "journalSinceAttemptStart": bool(staging["journalSinceAttemptStart"]),
            "correlationWindowSeconds": int(staging["correlationWindowSeconds"]),
            "sshSocketQueryable": bool(staging["sshSocketOk"]),
            "sshSocketCount": int(staging["sshSocketCount"]),
            "routeUsesSelectedWireGuardInterface": bool(
                denetim_ssh_preflight["routeUsesSelectedWireGuardInterface"]
            ),
        },
        verdict="pass" if staging_ok else "fail",
        source_kind="linux-management-metadata",
            source_locator="staging-management-plane",
        collected_at=now,
        bundle_collected_at=now,
        max_age_seconds=900,
        error_class="none" if staging_ok else "staging-correlation-unproven",
    )
    checks.append(
        make_check(
            "staging-connection-log",
            str(staging_contract["verdict"]),
            "linux-management-plane:ssh-wireguard-correlation",
            now,
            (
                "Staging metadata correlates Denetim SSH attempt with WireGuard peer state"
                if staging_ok
                else "Staging WireGuard/SSH correlation metadata is not fully proven"
            ),
            "staging/connection-log.metadata.json",
            staging_contract,
        )
    )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "collectedAt": now,
        "protectedEvidencePath": protected_path,
        "retentionDays": retention_days,
        "acl": {
            "mode": "protected",
            "readers": ["platform-ops-audit"],
            "writers": [
                "github-actions:self-hosted-staging-sw",
                "windows-system:audit-snapshot",
            ],
        },
        "redaction": {
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
            "secretMaterialIncluded": False,
            "commandContentIncluded": False,
        },
        "collector": {
            "runner": "self-hosted-management-runner",
            "denetimTargetHash": target_hash,
            "lookbackHours": lookback_hours,
            "wgInterfaceSelection": (
                "auto" if wg_interface == "auto" else f"explicit-hash:{sha256_short(wg_interface)}"
            ),
            "remoteSnapshotPathHash": sha256_short(DEFAULT_REMOTE_SNAPSHOT_PATH),
            "remoteSnapshotSchemaVersion": SNAPSHOT_SCHEMA_VERSION,
            "denetimSshPreflight": denetim_ssh_preflight,
            "stagingWireGuardProbe": staging["wgProbe"],
            "remoteCollectorReached": remote_ok,
            "stagingJournalQueryable": bool(staging["journalOk"]),
            "stagingJournalMatchCount": int(staging["journalMatchCount"]),
            "stagingAuditRecordWritten": bool(staging["auditRecordWritten"]),
            "stagingJournalSinceAttemptStart": bool(staging["journalSinceAttemptStart"]),
            "stagingCorrelationWindowSeconds": int(staging["correlationWindowSeconds"]),
            "stagingWireGuardQueryable": bool(staging["wgOk"]),
            "stagingWireGuardPeerCount": int(staging["wgPeerCount"]),
            "stagingSshSocketQueryable": bool(staging["sshSocketOk"]),
            "stagingSshSocketCount": int(staging["sshSocketCount"]),
            "localEvidenceWriteContract": {
                "atomic": True,
                "fileMode": "0600",
                "directoryMode": "0700",
                "symlinkRejected": True,
            },
        },
        "checks": checks,
    }


def write_evidence_atomically(path: Path, evidence: dict[str, Any]) -> None:
    parent = path.parent
    if parent.exists() and parent.is_symlink():
        raise OSError("evidence output directory must not be a symbolic link")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(parent, 0o700)
    if path.exists() and path.is_symlink():
        raise OSError("evidence output file must not be a symbolic link")

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(evidence, stream, indent=2, sort_keys=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise OSError("evidence output mode verification failed")
    finally:
        temporary_path.unlink(missing_ok=True)


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect metadata-only Faz 24 WG-B+ I3 evidence."
    )
    parser.add_argument("--output", required=True, type=Path, help="Evidence JSON output path")
    parser.add_argument(
        "--denetim-target",
        default=os.environ.get("DENETIM_SSH_TARGET", DEFAULT_DENETIM_TARGET),
        help="SSH target for Denetim metadata collection",
    )
    parser.add_argument(
        "--lookback-hours",
        type=positive_int,
        default=int(os.environ.get("FAZ24_I3_LOOKBACK_HOURS", "2")),
        help="Evidence lookback window in hours",
    )
    parser.add_argument(
        "--retention-days",
        type=positive_int,
        default=DEFAULT_RETENTION_DAYS,
        help="Artifact retention declaration for the evidence bundle",
    )
    parser.add_argument(
        "--wg-interface",
        default=os.environ.get("FAZ24_I3_WG_INTERFACE", DEFAULT_WG_INTERFACE),
        help="WireGuard interface name on staging-sw",
    )
    parser.add_argument(
        "--connect-timeout-seconds",
        type=positive_int,
        default=int(os.environ.get("FAZ24_I3_CONNECT_TIMEOUT_SECONDS", "10")),
        help="SSH/connect timeout for metadata commands",
    )
    parser.add_argument(
        "--ssh-identity-path",
        default=os.environ.get("FAZ24_I3_SSH_IDENTITY_PATH", DEFAULT_SSH_IDENTITY_PATH),
        help="Optional runner-local SSH identity path for Denetim metadata SSH",
    )
    parser.add_argument(
        "--protected-evidence-path",
        default=None,
        help="Override protectedEvidencePath; defaults to current GitHub Actions run artifact path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.denetim_target != DEFAULT_DENETIM_TARGET:
        print(
            "Faz24 WG-B+ I3 collector requires the canonical Denetim target",
            file=sys.stderr,
        )
        return 2
    timestamp = utc_now()
    protected_path = args.protected_evidence_path or default_protected_path(utc_text(timestamp))

    evidence = build_evidence(
        timestamp=timestamp,
        protected_path=protected_path,
        retention_days=args.retention_days,
        denetim_target=args.denetim_target,
        lookback_hours=args.lookback_hours,
        wg_interface=args.wg_interface,
        connect_timeout_seconds=args.connect_timeout_seconds,
        runner=run_command,
        ssh_identity_path=args.ssh_identity_path,
    )

    try:
        write_evidence_atomically(args.output, evidence)
    except OSError as exc:
        print(f"Faz24 WG-B+ I3 collector could not securely write evidence: {exc}", file=sys.stderr)
        return 2

    failing = [check["id"] for check in evidence["checks"] if check.get("status") != "pass"]
    print(f"Faz24 WG-B+ I3 collector wrote {args.output}")
    if failing:
        print("Collector status: evidence-not-accepted")
        print("Failing checks: " + ", ".join(failing))
        return 1
    else:
        print("Collector status: evidence-candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
