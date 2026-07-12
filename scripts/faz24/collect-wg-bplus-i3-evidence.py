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
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = "faz24.wg-bplus.i3.audit.v1"
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
  $policy = Get-ItemProperty -Path "HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\Transcription" -ErrorAction Stop
  $enabled = ($policy.EnableTranscripting -eq 1)
  $protectedPath = [string]$policy.OutputDirectory
  $checks.powershellTranscription = [ordered]@{
    ok = ($enabled -and $protectedPath.Length -gt 0)
    queryOk = $true
    enabled = $enabled
    hasProtectedPath = ($protectedPath.Length -gt 0)
  }
} catch {
  $checks.powershellTranscription = [ordered]@{ ok = $false; queryOk = $false; enabled = $false; hasProtectedPath = $false; errorClass = $_.Exception.GetType().Name }
}

try {
  $policy = Get-ItemProperty -Path "HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging" -ErrorAction SilentlyContinue
  $enabled = ($policy.EnableScriptBlockLogging -eq 1)
  $events = @(Get-WinEvent -LogName "Microsoft-Windows-PowerShell/Operational" -ErrorAction Stop |
    Where-Object { ($_.Id -eq 4103 -or $_.Id -eq 4104) -and $_.TimeCreated.ToUniversalTime() -ge $since } |
    Select-Object TimeCreated, Id, LevelDisplayName)
  $latest = $events | Sort-Object TimeCreated -Descending | Select-Object -First 1
  $checks.powershellScriptBlock = [ordered]@{
    ok = ($enabled -and ((Count-Array $events) -gt 0))
    queryOk = $true
    enabled = $enabled
    count = Count-Array $events
    latestUtc = To-UtcText $latest.TimeCreated
  }
} catch {
  $checks.powershellScriptBlock = [ordered]@{ ok = $false; queryOk = $false; enabled = $false; count = 0; errorClass = $_.Exception.GetType().Name }
}

try {
  $events = @(Get-WinEvent -FilterHashtable @{LogName="Security"; Id=4625; StartTime=(Get-Date).AddHours(-1 * $lookbackHours)} -ErrorAction Stop |
    Select-Object TimeCreated, Id, ProviderName)
  $latest = $events | Sort-Object TimeCreated -Descending | Select-Object -First 1
  $checks.failedLogin = [ordered]@{
    ok = $true
    queryOk = $true
    count = Count-Array $events
    latestUtc = To-UtcText $latest.TimeCreated
  }
} catch {
  $checks.failedLogin = [ordered]@{ ok = $false; queryOk = $false; count = 0; errorClass = $_.Exception.GetType().Name }
}

try {
  $wgOutput = @(wg show 2>$null)
  $wgExit = $LASTEXITCODE
  $wgText = ($wgOutput -join "`n")
  $interfaceCount = ([regex]::Matches($wgText, "(?m)^interface:")).Count
  $handshakeCount = ([regex]::Matches($wgText, "latest handshake:")).Count
  $transferCount = ([regex]::Matches($wgText, "transfer:")).Count
  $checks.wireguardHealth = [ordered]@{
    ok = ($wgExit -eq 0 -and $interfaceCount -gt 0)
    queryOk = ($wgExit -eq 0)
    interfaceCount = $interfaceCount
    handshakeCount = $handshakeCount
    transferCount = $transferCount
  }
} catch {
  $checks.wireguardHealth = [ordered]@{ ok = $false; queryOk = $false; interfaceCount = 0; handshakeCount = 0; transferCount = 0; errorClass = $_.Exception.GetType().Name }
}

try {
  $rules = @(Get-NetFirewallRule -ErrorAction Stop |
    Where-Object { $_.DisplayName -match "WireGuard|OpenSSH|Caddy|8243|8200" } |
    Select-Object DisplayName, Enabled, Direction, Action, Profile)
  $checks.firewallDrift = [ordered]@{
    ok = ((Count-Array $rules) -gt 0)
    queryOk = $true
    matchingRuleCount = Count-Array $rules
  }
} catch {
  $checks.firewallDrift = [ordered]@{ ok = $false; queryOk = $false; matchingRuleCount = 0; errorClass = $_.Exception.GetType().Name }
}

try {
  $timeOutput = @(w32tm /query /status 2>$null)
  $timeExit = $LASTEXITCODE
  $checks.timeSync = [ordered]@{
    ok = ($timeExit -eq 0 -and (Count-Array $timeOutput) -gt 0)
    queryOk = ($timeExit -eq 0)
    lineCount = Count-Array $timeOutput
  }
} catch {
  $checks.timeSync = [ordered]@{ ok = $false; queryOk = $false; lineCount = 0; errorClass = $_.Exception.GetType().Name }
}

[ordered]@{
  collectedAt = $now.ToString("yyyy-MM-ddTHH:mm:ssZ")
  host = $env:COMPUTERNAME
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
) -> dict[str, Any]:
    host = parse_ssh_target_host(target)
    route = runner(["ip", "route", "get", host], None, timeout_seconds)
    tcp = tcp_probe(host, 22, timeout_seconds)
    tcp_reachable = tcp.get("tcp22Reachable") is True
    ssh_output = f"{ssh_result.stderr}\n{ssh_result.stdout}"

    return {
        "targetHostHash": sha256_short(host),
        "targetPort": 22,
        "targetHostIsIpLiteral": is_ip_literal(host),
        "routeQueryable": route.returncode == 0,
        "routeExitCode": route.returncode,
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
                "wgToolSelected": candidate,
                "wgToolProbeExitCode": result.returncode,
            }

    return "wg", {
        "wgToolFound": False,
        "wgToolSelected": "",
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
            "requested": wg_interface,
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
        "requested": "auto",
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


def build_powershell_collector(lookback_hours: int) -> str:
    return POWERSHELL_COLLECTOR.replace("__LOOKBACK_HOURS__", str(lookback_hours))


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
) -> dict[str, str]:
    return {
        "id": check_id,
        "status": status,
        "who": bounded(who, 120),
        "when": when,
        "what": bounded(what, 200),
        "evidenceRef": evidence_ref,
    }


def collect_staging_metadata(
    runner: CommandRunner,
    lookback_hours: int,
    wg_interface: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    journal_cmd = [
        "journalctl",
        "-u",
        "ssh",
        "--since",
        f"{lookback_hours} hours ago",
        "--no-pager",
        "--output=short-iso",
    ]
    journal = run_with_sudo_fallback(runner, journal_cmd, timeout_seconds)

    journal_lines = non_empty_lines(journal.stdout)
    journal_matches = [
        line
        for line in journal_lines
        if re.search(r"svc-denetim-agent|10\.99\.0\.2|Accepted|Failed", line, re.IGNORECASE)
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
    wg_probe["selectedInterface"] = selected_probe["interface"] if selected_probe else ""
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
) -> dict[str, Any]:
    now = utc_text(timestamp)
    target_hash = sha256_short(denetim_target)

    staging = collect_staging_metadata(
        runner,
        lookback_hours=lookback_hours,
        wg_interface=wg_interface,
        timeout_seconds=connect_timeout_seconds,
    )
    remote, ssh_result = collect_denetim_metadata(
        runner,
        target=denetim_target,
        lookback_hours=lookback_hours,
        connect_timeout_seconds=connect_timeout_seconds,
        ssh_identity_path=ssh_identity_path,
    )
    ssh_identity_metadata = inspect_ssh_identity(ssh_identity_path)
    denetim_ssh_preflight = collect_denetim_ssh_preflight(
        runner,
        tcp_probe,
        denetim_target,
        ssh_result,
        connect_timeout_seconds,
        ssh_identity_metadata,
    )
    remote_ok = remote is not None and ssh_result.returncode == 0
    remote_host = bounded(str(remote.get("host", "denetim-pc")) if remote else "denetim-pc", 80)

    if not remote_ok:
        ssh_failure = f"Denetim SSH metadata collector failed with exit {ssh_result.returncode}"
        remote_who = f"denetim SSH target hash {target_hash}"
        checks = [
            make_check(check_id, "fail", remote_who, now, ssh_failure, f"windows/{check_id}.metadata.json")
            for check_id in CHECK_ORDER
            if check_id != "staging-connection-log"
        ]
    else:
        openssh = remote_check(remote, "opensshEventLog")
        transcription = remote_check(remote, "powershellTranscription")
        script_block = remote_check(remote, "powershellScriptBlock")
        failed_login = remote_check(remote, "failedLogin")
        wireguard = remote_check(remote, "wireguardHealth")
        firewall = remote_check(remote, "firewallDrift")
        time_sync = remote_check(remote, "timeSync")

        checks = [
            make_check(
                "openssh-event-log",
                "pass" if bool_field(openssh, "ok") else "fail",
                f"{remote_host} OpenSSH Operational",
                now,
                f"OpenSSH metadata query count={int_field(openssh, 'count')} over {lookback_hours}h",
                "windows/openssh-event-log.metadata.json",
            ),
            make_check(
                "powershell-transcription",
                "pass" if bool_field(transcription, "ok") else "fail",
                f"{remote_host} PowerShell policy",
                now,
                "PowerShell transcription metadata is enabled with protected output path"
                if bool_field(transcription, "ok")
                else "PowerShell transcription protected-path metadata is not proven",
                "windows/powershell-transcription.metadata.json",
            ),
            make_check(
                "powershell-script-block",
                "pass" if bool_field(script_block, "ok") else "fail",
                f"{remote_host} PowerShell Operational",
                now,
                f"Script-block logging enabled; metadata count={int_field(script_block, 'count')}; command text omitted",
                "windows/powershell-script-block.metadata.json",
            ),
            make_check(
                "failed-login",
                "pass" if bool_field(failed_login, "ok") else "fail",
                f"{remote_host} Security log",
                now,
                f"Failed-logon metadata query count={int_field(failed_login, 'count')} over {lookback_hours}h",
                "windows/failed-login.metadata.json",
            ),
            make_check(
                "wireguard-health",
                "pass" if bool_field(wireguard, "ok") else "fail",
                f"{remote_host} WireGuard",
                now,
                "WireGuard metadata query succeeded with interface and peer health counters",
                "windows/wireguard-health.metadata.json",
            ),
            make_check(
                "eset-firewall-drift",
                "pass" if bool_field(firewall, "ok") else "fail",
                f"{remote_host} firewall policy",
                now,
                f"Firewall/WFP metadata query matched {int_field(firewall, 'matchingRuleCount')} expected surface rules",
                "windows/eset-firewall-drift.metadata.json",
            ),
            make_check(
                "time-sync",
                "pass" if bool_field(time_sync, "ok") else "fail",
                f"{remote_host} w32time",
                now,
                "Time-sync metadata query succeeded for audit correlation",
                "windows/time-sync.metadata.json",
            ),
        ]

    staging_ok = remote_ok and bool(staging["wgOk"]) and int(staging["wgPeerCount"]) > 0
    checks.append(
        make_check(
            "staging-connection-log",
            "pass" if staging_ok else "fail",
            "staging-sw ssh/WireGuard metadata",
            now,
            (
                "Staging metadata correlates Denetim SSH attempt with WireGuard peer state"
                if staging_ok
                else "Staging WireGuard/SSH correlation metadata is not fully proven"
            ),
            "staging/connection-log.metadata.json",
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
            "writers": ["github-actions:self-hosted-staging-sw", "svc-denetim-agent"],
        },
        "redaction": {
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
            "secretMaterialIncluded": False,
            "commandContentIncluded": False,
        },
        "collector": {
            "runner": "staging-sw",
            "denetimTargetHash": target_hash,
            "lookbackHours": lookback_hours,
            "wgInterface": wg_interface,
            "denetimSshPreflight": denetim_ssh_preflight,
            "stagingWireGuardProbe": staging["wgProbe"],
            "remoteCollectorReached": remote_ok,
            "stagingJournalQueryable": bool(staging["journalOk"]),
            "stagingJournalMatchCount": int(staging["journalMatchCount"]),
            "stagingWireGuardQueryable": bool(staging["wgOk"]),
            "stagingWireGuardPeerCount": int(staging["wgPeerCount"]),
            "stagingSshSocketQueryable": bool(staging["sshSocketOk"]),
            "stagingSshSocketCount": int(staging["sshSocketCount"]),
        },
        "checks": checks,
    }


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

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    failing = [check["id"] for check in evidence["checks"] if check.get("status") != "pass"]
    print(f"Faz24 WG-B+ I3 collector wrote {args.output}")
    if failing:
        print("Collector status: evidence-not-accepted")
        print("Failing checks: " + ", ".join(failing))
    else:
        print("Collector status: evidence-candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
