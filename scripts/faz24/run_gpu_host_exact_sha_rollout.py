#!/usr/bin/env python3
"""Run the fixed-target Faz 24 GPU rollout and emit metadata-only evidence."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Sequence


SCHEMA_VERSION = "faz24.gpu-host-exact-sha-rollout.v1"
CANONICAL_TARGET = "denetim-pc"
CANONICAL_REPO_ROOT = r"C:\platform-ai"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
EVIDENCE_MARKER = "FAZ24_GPU_ROLLOUT_JSON:"


REMOTE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$TargetCommit = '__TARGET_COMMIT__'
$RepoRoot = 'C:\platform-ai'
$UpdateScript = Join-Path $RepoRoot 'deploy\gpu-host\update.ps1'
$MigrationScript = Join-Path $RepoRoot 'deploy\gpu-host\migrate-task-actions.ps1'
$StatePath = 'C:\ProgramData\Acik\platform-ai\deployment-state.json'

# Scope Git ownership trust to this rollout process and its updater child.
$env:GIT_CONFIG_COUNT = '1'
$env:GIT_CONFIG_KEY_0 = 'safe.directory'
$env:GIT_CONFIG_VALUE_0 = 'C:/platform-ai'

$windowsIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$windowsPrincipal = New-Object Security.Principal.WindowsPrincipal($windowsIdentity)
$principalMetadata = [ordered]@{
  expectedIdentity = $windowsIdentity.Name.EndsWith(
    '\denetimpc', [StringComparison]::OrdinalIgnoreCase
  )
  administrator = $windowsPrincipal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
  )
}

function Get-HealthMetadata {
  param([Parameter(Mandatory = $true)][string]$Url)
  try {
    $health = Invoke-RestMethod -Uri $Url -TimeoutSec 10 -ErrorAction Stop
    return [ordered]@{
      reachable = $true
      status = [string]$health.status
      model = [string]$health.model
      device = [string]$health.device
      computeType = [string]$health.compute_type
      backend = [string]$health.backend
    }
  } catch {
    return [ordered]@{
      reachable = $false
      status = ''
      model = ''
      device = ''
      computeType = ''
      backend = ''
    }
  }
}

function Get-TaskMetadata {
  param(
    [Parameter(Mandatory = $true)][object]$RootFolder,
    [Parameter(Mandatory = $true)][string]$TaskName,
    [Parameter(Mandatory = $true)][string]$ExpectedScript
  )
  $metadata = [ordered]@{
    present = $false
    state = -1
    actionCanonical = $false
    actionMigratable = $false
    actionCount = 0
    executeClass = 'missing'
    executeTrusted = $false
    scriptPathClass = 'missing'
    workingDirectoryClass = 'missing'
    actionArgumentsSha256 = ''
  }
  try {
    $task = $RootFolder.GetTask($TaskName)
    $metadata.present = $true
    $metadata.state = [int]$task.State
    $metadata.actionCount = [int]$task.Definition.Actions.Count
    $action = $task.Definition.Actions.Item(1)
    $executeName = [IO.Path]::GetFileName([string]$action.Path).ToLowerInvariant()
    $executePath = [string]$action.Path
    $arguments = [string]$action.Arguments
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
      $argumentBytes = [Text.Encoding]::UTF8.GetBytes($arguments)
      $metadata.actionArgumentsSha256 = -join (
        $sha.ComputeHash($argumentBytes) | ForEach-Object { $_.ToString('x2') }
      )
    } finally {
      $sha.Dispose()
    }

    if ($executeName -eq 'powershell.exe') {
      $metadata.executeClass = 'windows-powershell'
    } elseif ($executeName -eq 'pwsh.exe') {
      $metadata.executeClass = 'powershell-core'
    } else {
      $metadata.executeClass = 'other'
    }
    $trustedPowerShell = @('powershell.exe')
    if (-not [string]::IsNullOrWhiteSpace($env:SystemRoot)) {
      $trustedPowerShell += (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
    }
    $metadata.executeTrusted = ($trustedPowerShell -icontains $executePath)
    $metadata.workingDirectoryClass = $(
      if ([string]::IsNullOrWhiteSpace([string]$action.WorkingDirectory)) {
        'empty'
      } else {
        'set'
      }
    )

    $legacyScript = $ExpectedScript.Replace(
      'C:\platform-ai\',
      'C:\Users\denetimpc\platform-ai\'
    )
    if ($arguments.IndexOf($ExpectedScript, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
      $metadata.scriptPathClass = 'canonical-repo'
    } elseif ($arguments.IndexOf($legacyScript, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
      $metadata.scriptPathClass = 'legacy-user-repo'
    } else {
      $metadata.scriptPathClass = 'other'
    }
    $metadata.actionCanonical = (
      $metadata.actionCount -eq 1 -and
      $metadata.executeClass -eq 'windows-powershell' -and
      $metadata.executeTrusted -and
      $metadata.workingDirectoryClass -eq 'empty' -and
      $metadata.scriptPathClass -eq 'canonical-repo'
    )
    $metadata.actionMigratable = (
      $metadata.actionCount -eq 1 -and
      $metadata.executeClass -eq 'windows-powershell' -and
      $metadata.executeTrusted -and
      $metadata.workingDirectoryClass -eq 'empty' -and
      $metadata.scriptPathClass -in @('canonical-repo', 'legacy-user-repo')
    )
  } catch {
    if ($metadata.present) {
      $metadata.executeClass = 'inspection-error'
      $metadata.scriptPathClass = 'inspection-error'
    }
  }
  return $metadata
}

function Test-WebSocketReady {
  param(
    [string]$Url = 'ws://127.0.0.1:8200/ws/stream',
    [int]$TimeoutSec = 180
  )
  $client = $null
  try {
    $client = [System.Net.WebSockets.ClientWebSocket]::new()
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSec)
    $connect = $client.ConnectAsync([Uri]$Url, [Threading.CancellationToken]::None)
    if (-not $connect.Wait([Math]::Max(1, [int]($deadline - [DateTime]::UtcNow).TotalMilliseconds))) {
      return [ordered]@{ ready = $false; eventType = ''; failureClass = 'connect-timeout' }
    }
    if ($connect.Exception) {
      return [ordered]@{ ready = $false; eventType = ''; failureClass = 'connect-failed' }
    }

    $buffer = New-Object byte[] 8192
    $builder = [Text.StringBuilder]::new()
    while ([DateTime]::UtcNow -lt $deadline) {
      $remaining = [Math]::Max(1, [int]($deadline - [DateTime]::UtcNow).TotalMilliseconds)
      $segment = [ArraySegment[byte]]::new($buffer)
      $receive = $client.ReceiveAsync($segment, [Threading.CancellationToken]::None)
      if (-not $receive.Wait($remaining)) {
        return [ordered]@{ ready = $false; eventType = ''; failureClass = 'ready-timeout' }
      }
      if ($receive.Exception) {
        return [ordered]@{ ready = $false; eventType = ''; failureClass = 'receive-failed' }
      }
      $result = $receive.Result
      if ($result.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Close) {
        return [ordered]@{ ready = $false; eventType = 'close'; failureClass = 'closed-before-ready' }
      }
      if ($result.Count -gt 0) {
        [void]$builder.Append([Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count))
      }
      if (-not $result.EndOfMessage) { continue }
      $payload = $builder.ToString()
      [void]$builder.Clear()
      try {
        $event = $payload | ConvertFrom-Json -ErrorAction Stop
        $eventType = [string]$event.type
        if ($eventType -eq 'ready') {
          return [ordered]@{ ready = $true; eventType = 'ready'; failureClass = 'none' }
        }
        if ($eventType -eq 'error') {
          return [ordered]@{ ready = $false; eventType = 'error'; failureClass = 'server-error-event' }
        }
      } catch { }
    }
    return [ordered]@{ ready = $false; eventType = ''; failureClass = 'ready-timeout' }
  } catch {
    return [ordered]@{ ready = $false; eventType = ''; failureClass = $_.Exception.GetType().Name }
  } finally {
    if ($client) {
      try { $client.Dispose() } catch { }
    }
  }
}

function ConvertTo-PowerShellLiteral {
  param([Parameter(Mandatory = $true)][string]$Value)
  return "'" + $Value.Replace("'", "''") + "'"
}

function Invoke-PowerShellChild {
  param(
    [Parameter(Mandatory = $true)][string]$Command,
    [Parameter(Mandatory = $true)][string]$StdoutPath,
    [Parameter(Mandatory = $true)][string]$StderrPath
  )
  $arguments = @(
    '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-InputFormat', 'Text', '-OutputFormat', 'Text', '-Command', '-'
  )
  $oldEap = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $Command | & powershell.exe @arguments 1> $StdoutPath 2> $StderrPath
    return [int]$LASTEXITCODE
  } finally {
    $ErrorActionPreference = $oldEap
  }
}

function Invoke-UpdaterChild {
  param(
    [switch]$WhatIfOnly,
    [switch]$NoRestartOnly,
    [switch]$RollbackOnly
  )
  $stdoutPath = Join-Path $env:TEMP ('faz24-gpu-rollout-' + [Guid]::NewGuid().ToString('N') + '.out')
  $stderrPath = Join-Path $env:TEMP ('faz24-gpu-rollout-' + [Guid]::NewGuid().ToString('N') + '.err')
  try {
    $command = '$ConfirmPreference = ''None''; & ' +
      (ConvertTo-PowerShellLiteral $UpdateScript) +
      ' -RepoRoot ' + (ConvertTo-PowerShellLiteral $RepoRoot) +
      ' -Confirm:$false'
    if ($RollbackOnly) {
      $command += ' -Rollback'
    } else {
      $command += ' -TargetCommit ' + (ConvertTo-PowerShellLiteral $TargetCommit)
    }
    if ($NoRestartOnly) { $command += ' -NoRestart' }
    if ($WhatIfOnly) { $command += ' -WhatIf' }
    return Invoke-PowerShellChild -Command $command -StdoutPath $stdoutPath `
      -StderrPath $stderrPath
  } finally {
    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
  }
}

function Invoke-TaskActionMigration {
  param([switch]$WhatIfOnly)
  $stdoutPath = Join-Path $env:TEMP ('faz24-task-migration-' + [Guid]::NewGuid().ToString('N') + '.out')
  $stderrPath = Join-Path $env:TEMP ('faz24-task-migration-' + [Guid]::NewGuid().ToString('N') + '.err')
  try {
    $command = '$ConfirmPreference = ''None''; & ' +
      (ConvertTo-PowerShellLiteral $MigrationScript) +
      ' -RepoRoot ' + (ConvertTo-PowerShellLiteral $RepoRoot) +
      ' -Confirm:$false'
    if ($WhatIfOnly) { $command += ' -WhatIf' }
    return Invoke-PowerShellChild -Command $command -StdoutPath $stdoutPath `
      -StderrPath $stderrPath
  } finally {
    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
  }
}

function Get-RolloutFailureClass {
  param([Parameter(Mandatory = $true)]$ErrorRecord)
  $message = [string]$ErrorRecord.Exception.Message
  $known = @(
    'invalid-target-commit', 'unexpected-rollout-identity',
    'rollout-principal-not-admin', 'canonical-repo-missing', 'updater-missing',
    'before-commit-invalid', 'required-task-missing', 'task-action-unrecognized',
    'updater-whatif-rejected', 'updater-pin-rejected',
    'task-migration-script-missing', 'task-migration-whatif-rejected',
    'task-migration-rejected', 'task-migration-readback-rejected',
    'updater-deploy-rejected'
  )
  if ($known -contains $message) { return $message }
  $typeName = [string]$ErrorRecord.Exception.GetType().Name
  if ($typeName -notmatch '^[A-Za-z0-9]+$') { $typeName = 'error' }
  return 'rollout-unexpected-' + $typeName.ToLowerInvariant()
}

$beforeCommit = ''
$afterCommit = ''
$whatIfExitCode = -1
$pinWithoutRestartExitCode = -1
$migrationWhatIfExitCode = -1
$migrationExitCode = -1
$sourceRollbackExitCode = -1
$deployExitCode = -1
$failureClass = 'none'
$migrationRequired = $false
$sourcePinnedWithoutRestart = $false
$ledger = [ordered]@{ currentCommit = ''; previousCommit = ''; action = ''; lastResult = ''; timestampUtc = '' }
$taskService = $null
$taskRoot = $null
$liveTask = [ordered]@{
  present = $false; state = -1; actionCanonical = $false; actionMigratable = $false; actionCount = 0
  executeClass = 'missing'; executeTrusted = $false; scriptPathClass = 'missing'
  workingDirectoryClass = 'missing'; actionArgumentsSha256 = ''
}
$meetingTask = [ordered]@{
  present = $false; state = -1; actionCanonical = $false; actionMigratable = $false; actionCount = 0
  executeClass = 'missing'; executeTrusted = $false; scriptPathClass = 'missing'
  workingDirectoryClass = 'missing'; actionArgumentsSha256 = ''
}
$tasksBefore = [ordered]@{}

try {
  if ($TargetCommit -notmatch '^[0-9a-f]{40}$') { throw 'invalid-target-commit' }
  if (-not $principalMetadata.expectedIdentity) { throw 'unexpected-rollout-identity' }
  if (-not $principalMetadata.administrator) { throw 'rollout-principal-not-admin' }
  if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot '.git'))) { throw 'canonical-repo-missing' }
  if (-not (Test-Path -LiteralPath $UpdateScript -PathType Leaf)) { throw 'updater-missing' }

  Set-Location $RepoRoot
  $beforeCommit = [string](& git rev-parse HEAD 2>$null)
  $beforeCommit = $beforeCommit.Trim().ToLowerInvariant()
  if ($LASTEXITCODE -ne 0 -or $beforeCommit -notmatch '^[0-9a-f]{40}$') { throw 'before-commit-invalid' }

  $taskService = New-Object -ComObject 'Schedule.Service'
  $taskService.Connect()
  $taskRoot = $taskService.GetFolder('\')
  $liveTask = Get-TaskMetadata -RootFolder $taskRoot -TaskName 'platform-ai-live-stt' `
    -ExpectedScript 'C:\platform-ai\deploy\gpu-host\start-live-stt.ps1'
  $meetingTask = Get-TaskMetadata -RootFolder $taskRoot -TaskName 'platform-ai-meeting-ai' `
    -ExpectedScript 'C:\platform-ai\deploy\gpu-host\start-meeting-ai.ps1'
  if (-not $liveTask.present -or -not $meetingTask.present) { throw 'required-task-missing' }
  $tasksBefore = [ordered]@{ liveStt = $liveTask; meetingAi = $meetingTask }
  if (-not $liveTask.actionMigratable -or -not $meetingTask.actionMigratable) {
    throw 'task-action-unrecognized'
  }
  $migrationRequired = (-not $liveTask.actionCanonical -or -not $meetingTask.actionCanonical)

  $whatIfExitCode = Invoke-UpdaterChild -WhatIfOnly
  if ($whatIfExitCode -ne 0) { throw 'updater-whatif-rejected' }

  if ($migrationRequired) {
    $pinWithoutRestartExitCode = Invoke-UpdaterChild -NoRestartOnly
    if ($pinWithoutRestartExitCode -ne 0) { throw 'updater-pin-rejected' }
    $sourcePinnedWithoutRestart = ($beforeCommit -ne $TargetCommit)
    if (-not (Test-Path -LiteralPath $MigrationScript -PathType Leaf)) {
      throw 'task-migration-script-missing'
    }

    $migrationWhatIfExitCode = Invoke-TaskActionMigration -WhatIfOnly
    if ($migrationWhatIfExitCode -ne 0) { throw 'task-migration-whatif-rejected' }
    $migrationExitCode = Invoke-TaskActionMigration
    if ($migrationExitCode -ne 0) { throw 'task-migration-rejected' }

    $liveTask = Get-TaskMetadata -RootFolder $taskRoot -TaskName 'platform-ai-live-stt' `
      -ExpectedScript 'C:\platform-ai\deploy\gpu-host\start-live-stt.ps1'
    $meetingTask = Get-TaskMetadata -RootFolder $taskRoot -TaskName 'platform-ai-meeting-ai' `
      -ExpectedScript 'C:\platform-ai\deploy\gpu-host\start-meeting-ai.ps1'
    if (-not $liveTask.actionCanonical -or -not $meetingTask.actionCanonical) {
      throw 'task-migration-readback-rejected'
    }
    # From this point onward the final updater owns restart/recovery semantics.
    $sourcePinnedWithoutRestart = $false
  }

  $deployExitCode = Invoke-UpdaterChild
  if ($deployExitCode -ne 0) { throw 'updater-deploy-rejected' }
} catch {
  $failureClass = Get-RolloutFailureClass -ErrorRecord $_
  if ($sourcePinnedWithoutRestart) {
    $sourceRollbackExitCode = Invoke-UpdaterChild -RollbackOnly -NoRestartOnly
    if ($sourceRollbackExitCode -ne 0) {
      $failureClass = $failureClass + '-source-rollback-failed'
    }
  }
} finally {
  try {
    Set-Location $RepoRoot
    $afterCommit = [string](& git rev-parse HEAD 2>$null)
    $afterCommit = $afterCommit.Trim().ToLowerInvariant()
  } catch { $afterCommit = '' }
  try {
    $state = Get-Content -LiteralPath $StatePath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    $ledger = [ordered]@{
      currentCommit = [string]$state.currentCommit
      previousCommit = [string]$state.previousCommit
      action = [string]$state.action
      lastResult = [string]$state.lastResult
      timestampUtc = [string]$state.timestampUtc
    }
  } catch { }
  try {
    if (-not $taskRoot) {
      $taskService = New-Object -ComObject 'Schedule.Service'
      $taskService.Connect()
      $taskRoot = $taskService.GetFolder('\')
    }
    $liveTask = Get-TaskMetadata -RootFolder $taskRoot -TaskName 'platform-ai-live-stt' `
      -ExpectedScript 'C:\platform-ai\deploy\gpu-host\start-live-stt.ps1'
    $meetingTask = Get-TaskMetadata -RootFolder $taskRoot -TaskName 'platform-ai-meeting-ai' `
      -ExpectedScript 'C:\platform-ai\deploy\gpu-host\start-meeting-ai.ps1'
  } catch { }
}

$liveHealth = Get-HealthMetadata -Url 'http://127.0.0.1:8200/health'
$meetingHealth = Get-HealthMetadata -Url 'http://127.0.0.1:8300/health'
$stream = Test-WebSocketReady
$migrationAccepted = (
  (-not $migrationRequired) -or (
    $pinWithoutRestartExitCode -eq 0 -and
    $migrationWhatIfExitCode -eq 0 -and
    $migrationExitCode -eq 0 -and
    $sourceRollbackExitCode -eq -1
  )
)
$sourceCommitVerified = (
  $whatIfExitCode -eq 0 -and
  $deployExitCode -eq 0 -and
  $afterCommit -eq $TargetCommit -and
  $ledger.currentCommit -eq $TargetCommit
)
$go = (
  $failureClass -eq 'none' -and
  $migrationAccepted -and
  $whatIfExitCode -eq 0 -and
  $deployExitCode -eq 0 -and
  $afterCommit -eq $TargetCommit -and
  $ledger.currentCommit -eq $TargetCommit -and
  $ledger.lastResult -eq 'tasks-restarted' -and
  $liveTask.present -and $liveTask.state -eq 4 -and $liveTask.actionCanonical -and
  $meetingTask.present -and $meetingTask.state -eq 4 -and $meetingTask.actionCanonical -and
  $liveHealth.reachable -and $liveHealth.status -eq 'ok' -and $liveHealth.device -eq 'cuda' -and
  $meetingHealth.reachable -and $meetingHealth.status -eq 'ok' -and
  $meetingHealth.backend -eq 'ollama' -and
  $stream.ready -and $stream.eventType -eq 'ready'
)

$evidence = [ordered]@{
  schemaVersion = 'faz24.gpu-host-exact-sha-rollout.v1'
  generatedAt = [DateTime]::UtcNow.ToString('o')
  status = $(if ($go) { 'go' } else { 'no-go' })
  targetCommit = $TargetCommit
  beforeCommit = $beforeCommit
  afterCommit = $afterCommit
  sourceCommitVerified = $sourceCommitVerified
  whatIfExitCode = $whatIfExitCode
  deployExitCode = $deployExitCode
  failureClass = $failureClass
  principal = $principalMetadata
  ledger = $ledger
  taskMigration = [ordered]@{
    required = $migrationRequired
    pinWithoutRestartExitCode = $pinWithoutRestartExitCode
    whatIfExitCode = $migrationWhatIfExitCode
    migrationExitCode = $migrationExitCode
    sourceRollbackExitCode = $sourceRollbackExitCode
  }
  tasksBefore = $tasksBefore
  tasks = [ordered]@{ liveStt = $liveTask; meetingAi = $meetingTask }
  health = [ordered]@{ liveStt = $liveHealth; meetingAi = $meetingHealth }
  webSocket = $stream
  privacy = [ordered]@{
    rawAudioIncluded = $false
    transcriptTextIncluded = $false
    secretMaterialIncluded = $false
  }
}

$json = $evidence | ConvertTo-Json -Compress -Depth 8
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
[Console]::Out.WriteLine('FAZ24_GPU_ROLLOUT_JSON:' + $encoded)
if ($go) { exit 0 }
exit 1
"""


def validate_commit(value: str) -> str:
    value = value.strip()
    if not COMMIT_RE.fullmatch(value):
        raise ValueError(
            "target commit must be exactly 40 lowercase hexadecimal characters"
        )
    return value


def build_remote_script(target_commit: str) -> str:
    commit = validate_commit(target_commit)
    return REMOTE_SCRIPT.replace("__TARGET_COMMIT__", commit)


def parse_evidence(stdout: str) -> dict[str, Any]:
    markers = [line for line in stdout.splitlines() if line.startswith(EVIDENCE_MARKER)]
    if len(markers) != 1:
        raise ValueError("remote output did not contain exactly one evidence marker")
    encoded = markers[0][len(EVIDENCE_MARKER) :]
    try:
        payload = base64.b64decode(encoded, validate=True).decode("utf-8")
        evidence = json.loads(payload)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("remote evidence marker is invalid") from exc
    if not isinstance(evidence, dict):
        raise ValueError("remote evidence must be a JSON object")
    return evidence


def ssh_command(ssh_config: Path, known_hosts: Path) -> list[str]:
    return [
        "ssh",
        "-F",
        str(ssh_config),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "ServerAliveInterval=10",
        "-o",
        "ServerAliveCountMax=3",
        "-o",
        "IdentitiesOnly=yes",
        CANONICAL_TARGET,
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-InputFormat",
        "Text",
        "-OutputFormat",
        "Text",
        "-Command",
        "-",
    ]


def run_rollout(
    *,
    target_commit: str,
    ssh_config: Path,
    known_hosts: Path,
    timeout_seconds: int,
) -> tuple[int, dict[str, Any]]:
    script = build_remote_script(target_commit)
    command = ssh_command(ssh_config, known_hosts)
    try:
        process = subprocess.run(
            command,
            check=False,
            capture_output=True,
            input=script,
            text=True,
            timeout=timeout_seconds,
            env={**os.environ, "LC_ALL": "C"},
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("remote rollout timed out") from exc
    evidence = parse_evidence(process.stdout)
    return process.returncode, evidence


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def failure_evidence(target_commit: str, failure_class: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "no-go",
        "targetCommit": target_commit,
        "beforeCommit": "",
        "afterCommit": "",
        "sourceCommitVerified": False,
        "whatIfExitCode": -1,
        "deployExitCode": -1,
        "failureClass": failure_class,
        "principal": {"expectedIdentity": False, "administrator": False},
        "ledger": {},
        "taskMigration": {
            "required": False,
            "pinWithoutRestartExitCode": -1,
            "whatIfExitCode": -1,
            "migrationExitCode": -1,
            "sourceRollbackExitCode": -1,
        },
        "tasksBefore": {},
        "tasks": {},
        "health": {},
        "webSocket": {
            "ready": False,
            "eventType": "",
            "failureClass": "not-observed",
        },
        "privacy": {
            "rawAudioIncluded": False,
            "transcriptTextIncluded": False,
            "secretMaterialIncluded": False,
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--ssh-config", required=True, type=Path)
    parser.add_argument("--ssh-known-hosts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    target_commit = validate_commit(args.target_commit)
    if not args.ssh_config.is_file():
        raise SystemExit("governed SSH config is not configured")
    if not args.ssh_known_hosts.is_file():
        raise SystemExit("pinned known_hosts is not configured")
    try:
        exit_code, evidence = run_rollout(
            target_commit=target_commit,
            ssh_config=args.ssh_config,
            known_hosts=args.ssh_known_hosts,
            timeout_seconds=args.timeout_seconds,
        )
    except RuntimeError:
        exit_code = 1
        evidence = failure_evidence(target_commit, "remote-rollout-timeout")
    except (OSError, ValueError):
        exit_code = 1
        evidence = failure_evidence(target_commit, "remote-evidence-unavailable")
    write_json_atomic(args.output, evidence)
    print(
        "GPU rollout evidence: "
        f"status={evidence.get('status', 'missing')} "
        f"failureClass={evidence.get('failureClass', 'missing')}"
    )
    return 0 if exit_code == 0 and evidence.get("status") == "go" else 1


if __name__ == "__main__":
    sys.exit(main())
