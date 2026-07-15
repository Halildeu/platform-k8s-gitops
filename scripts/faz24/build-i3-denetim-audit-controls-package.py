#!/usr/bin/env python3
"""Build the least-privilege Denetim Windows audit-controls operator package.

The package separates privileged collection from read-only evidence transport:
an idempotent elevated installer configures controls and a SYSTEM scheduled task,
while svc-denetim-agent can only read the bounded snapshot. No credential,
event message, command text, WireGuard key, or user identity is emitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PACKAGE_SCHEMA_VERSION = "faz24.i3.denetim.audit-controls-package.v1"
BASELINE_SCHEMA_VERSION = "faz24.windows-audit-baseline.v1"
SNAPSHOT_SCHEMA_VERSION = "faz24.windows-audit-snapshot.v1"
CONTROL_CONTRACT_VERSION = "faz24.windows-audit-control.v1"

DEFAULT_TARGET_USER = "svc-denetim-agent"
DEFAULT_MANAGEMENT_ADDRESS = "10.99.0.1"
DEFAULT_ROOT = r"C:\ProgramData\Acik\Faz24\I3\audit-controls"

COLLECTOR_NAME = "collect-audit-snapshot.ps1"
INSTALLER_NAME = "install-audit-controls.ps1"
ROLLBACK_NAME = "rollback-audit-controls.ps1"
BASELINE_NAME = "baseline.json"
MANIFEST_NAME = "package-manifest.json"
README_NAME = "README.md"
SHA256SUMS_NAME = "SHA256SUMS"

PRIVATE_MARKERS = (
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "BEGIN EC PRIVATE KEY",
    "PRIVATE KEY-----",
    "Bearer ",
)


SNAPSHOT_COLLECTOR = r'''#requires -Version 5.1
[CmdletBinding()]
param(
  [string]$Root = __ROOT__,
  [string]$BaselinePath = (Join-Path $Root 'config\baseline.json'),
  [string]$SnapshotPath = (Join-Path $Root 'snapshot\audit-snapshot.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SnapshotSchemaVersion = 'faz24.windows-audit-snapshot.v1'
$ControlContractVersion = 'faz24.windows-audit-control.v1'

function Get-UtcText {
  param([Parameter(Mandatory=$true)][datetime]$Value)
  return $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}

function Get-NonNegativeAgeSeconds {
  param([Parameter(Mandatory=$true)][datetime]$Value)
  $seconds = [int][Math]::Floor(((Get-Date).ToUniversalTime() - $Value.ToUniversalTime()).TotalSeconds)
  return [Math]::Max(0, $seconds)
}

function New-Control {
  param(
    [Parameter(Mandatory=$true)][System.Collections.IDictionary]$Expected,
    [Parameter(Mandatory=$true)][System.Collections.IDictionary]$Observed,
    [Parameter(Mandatory=$true)][bool]$Pass,
    [Parameter(Mandatory=$true)][string]$CollectedAt,
    [Parameter(Mandatory=$true)][int]$MaxAgeSeconds,
    [string]$ErrorClass = 'none'
  )
  return [ordered]@{
    contractVersion = $ControlContractVersion
    expected = $Expected
    observed = $Observed
    verdict = $(if ($Pass) { 'pass' } else { 'fail' })
    collectedAt = $CollectedAt
    maxAgeSeconds = $MaxAgeSeconds
    errorClass = $(if ($Pass) { 'none' } else { $ErrorClass })
  }
}

function Write-AtomicJson {
  param(
    [Parameter(Mandatory=$true)][object]$Value,
    [Parameter(Mandatory=$true)][string]$Path
  )
  $directory = Split-Path -Parent $Path
  New-Item -ItemType Directory -Path $directory -Force | Out-Null
  $temporary = Join-Path $directory ('.snapshot-' + [guid]::NewGuid().ToString('N') + '.tmp')
  $backup = Join-Path $directory ('.snapshot-' + [guid]::NewGuid().ToString('N') + '.bak')
  $json = $Value | ConvertTo-Json -Depth 12
  $encoding = New-Object System.Text.UTF8Encoding($false)
  $stream = New-Object System.IO.FileStream(
    $temporary,
    [System.IO.FileMode]::CreateNew,
    [System.IO.FileAccess]::Write,
    [System.IO.FileShare]::None
  )
  try {
    $writer = New-Object System.IO.StreamWriter($stream, $encoding)
    try {
      $writer.Write($json)
      $writer.Flush()
      $stream.Flush($true)
    } finally {
      $writer.Dispose()
    }
    if (Test-Path -LiteralPath $Path) {
      Set-Acl -LiteralPath $temporary -AclObject (Get-Acl -LiteralPath $Path)
      [System.IO.File]::Replace($temporary, $Path, $backup, $true)
    } else {
      [System.IO.File]::Move($temporary, $Path)
    }
  } finally {
    if ($null -ne $stream) { $stream.Dispose() }
    Remove-Item -LiteralPath $temporary,$backup -Force -ErrorAction SilentlyContinue
  }
}

function Get-SidValue {
  param([Parameter(Mandatory=$true)][System.Security.Principal.IdentityReference]$Identity)
  try {
    return $Identity.Translate([System.Security.Principal.SecurityIdentifier]).Value
  } catch {
    return ''
  }
}

function Test-ExactProtectedAcl {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [string]$ReadOnlySid = '',
    [switch]$Directory
  )
  $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
  $fullControlSids = @('S-1-5-18', 'S-1-5-32-544')
  $allowedSids = @($fullControlSids)
  if ($ReadOnlySid) { $allowedSids += $ReadOnlySid }
  $allows = @($acl.Access | Where-Object {
    $_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow
  })
  $denies = @($acl.Access | Where-Object {
    $_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Deny
  })
  $unexpectedAllows = @($allows | Where-Object {
    (Get-SidValue -Identity $_.IdentityReference) -notin $allowedSids
  })
  $requiredFullControl = @($fullControlSids | Where-Object {
    $requiredSid = $_
    @($allows | Where-Object {
      (Get-SidValue -Identity $_.IdentityReference) -eq $requiredSid -and
      (($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq
        [System.Security.AccessControl.FileSystemRights]::FullControl)
    }).Count -gt 0
  })
  $readOnlyOk = $true
  if ($ReadOnlySid) {
    $requiredRead = $(if ($Directory) {
      [System.Security.AccessControl.FileSystemRights]::ReadAndExecute
    } else {
      [System.Security.AccessControl.FileSystemRights]::Read
    })
    $writeMask = (
      [System.Security.AccessControl.FileSystemRights]::Write -bor
      [System.Security.AccessControl.FileSystemRights]::Modify -bor
      [System.Security.AccessControl.FileSystemRights]::FullControl -bor
      [System.Security.AccessControl.FileSystemRights]::Delete -bor
      [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
      [System.Security.AccessControl.FileSystemRights]::TakeOwnership
    )
    $targetRules = @($allows | Where-Object {
      (Get-SidValue -Identity $_.IdentityReference) -eq $ReadOnlySid
    })
    $readOnlyOk = (
      $targetRules.Count -gt 0 -and
      @($targetRules | Where-Object {
        (($_.FileSystemRights -band $requiredRead) -eq $requiredRead) -and
        (($_.FileSystemRights -band $writeMask) -eq 0)
      }).Count -eq $targetRules.Count
    )
  }
  return (
    $acl.AreAccessRulesProtected -and
    $unexpectedAllows.Count -eq 0 -and
    $denies.Count -eq 0 -and
    $requiredFullControl.Count -eq $fullControlSids.Count -and
    $readOnlyOk
  )
}

function Initialize-AuditPolicyApi {
  if ('Faz24.AuditPolicy.NativeMethods' -as [type]) { return }
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace Faz24.AuditPolicy {
  [StructLayout(LayoutKind.Sequential)]
  public struct AUDIT_POLICY_INFORMATION {
    public Guid AuditSubCategoryGuid;
    public uint AuditingInformation;
    public Guid AuditCategoryGuid;
  }
  public static class NativeMethods {
    [DllImport("advapi32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool AuditQuerySystemPolicy(
      [In] Guid[] pSubCategoryGuids,
      uint PolicyCount,
      out IntPtr ppAuditPolicy
    );
    [DllImport("advapi32.dll")]
    public static extern void AuditFree(IntPtr buffer);
  }
}
'@
}

function Test-LogonFailureAuditEnabled {
  Initialize-AuditPolicyApi
  $logonGuid = [guid]'0CCE9215-69AE-11D9-BED3-505054503030'
  $buffer = [IntPtr]::Zero
  if (-not [Faz24.AuditPolicy.NativeMethods]::AuditQuerySystemPolicy(@($logonGuid), 1, [ref]$buffer)) {
    throw ('AuditQuerySystemPolicy:' + [Runtime.InteropServices.Marshal]::GetLastWin32Error())
  }
  try {
    $info = [Runtime.InteropServices.Marshal]::PtrToStructure(
      $buffer,
      [type][Faz24.AuditPolicy.AUDIT_POLICY_INFORMATION]
    )
    return (($info.AuditingInformation -band 2) -eq 2)
  } finally {
    [Faz24.AuditPolicy.NativeMethods]::AuditFree($buffer)
  }
}

function Get-WireGuardObservation {
  $command = Get-Command 'wg.exe' -ErrorAction SilentlyContinue
  if ($null -eq $command) { $command = Get-Command 'wg' -ErrorAction Stop }
  $rows = @(& $command.Source show all dump 2>$null)
  $exitCode = $LASTEXITCODE
  $interfaceCount = 0
  $peerCount = 0
  $handshakes = New-Object System.Collections.Generic.List[long]
  foreach ($line in $rows) {
    $fields = @($line -split "`t")
    if ($fields.Count -eq 5) {
      $interfaceCount++
      continue
    }
    if ($fields.Count -ge 9) {
      $peerCount++
      $epoch = 0L
      # `wg show all dump` prefixes peer rows with the interface name.
      if ([long]::TryParse([string]$fields[5], [ref]$epoch) -and $epoch -gt 0) {
        $handshakes.Add($epoch)
      }
    }
  }
  $latestAge = $null
  if ($handshakes.Count -gt 0) {
    $nowEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $latestAge = [int][Math]::Max(0, $nowEpoch - ($handshakes | Measure-Object -Maximum).Maximum)
  }
  $runningServices = @(Get-Service -Name 'WireGuardTunnel$*' -ErrorAction SilentlyContinue |
    Where-Object { $_.Status -eq [System.ServiceProcess.ServiceControllerStatus]::Running })
  return [ordered]@{
    queryOk = ($exitCode -eq 0)
    dumpExitCode = $exitCode
    runningServiceCount = $runningServices.Count
    interfaceCount = $interfaceCount
    peerCount = $peerCount
    latestHandshakeAgeSeconds = $latestAge
  }
}

function Get-TranscriptFilesNoReparse {
  param([Parameter(Mandatory=$true)][string]$Path)

  $rootItem = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
  if (-not $rootItem.PSIsContainer) {
    throw 'transcript-root-not-directory'
  }
  if (($rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'transcript-root-reparse-point-rejected'
  }

  $pending = New-Object 'System.Collections.Generic.Stack[string]'
  $files = New-Object 'System.Collections.Generic.List[System.IO.FileInfo]'
  $pending.Push($rootItem.FullName)
  while ($pending.Count -gt 0) {
    $directory = $pending.Pop()
    foreach ($child in @(Get-ChildItem -LiteralPath $directory -Force -ErrorAction Stop)) {
      if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'transcript-descendant-reparse-point-rejected'
      }
      if ($child.PSIsContainer) {
        $pending.Push($child.FullName)
      } else {
        $files.Add($child)
      }
    }
  }
  return @($files)
}

function Invoke-TranscriptRetention {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][int]$RetentionDays,
    [Parameter(Mandatory=$true)][long]$MaximumBytes
  )
  if ($RetentionDays -lt 1 -or $MaximumBytes -lt 1048576) {
    throw 'invalid-transcript-retention-policy'
  }
  if (-not (Test-Path -LiteralPath $Path)) {
    return [ordered]@{
      retentionEnforced=$true; transcriptBytes=0; oldestTranscriptAgeSeconds=0
      retentionDeleteCount=0; capacityDeleteCount=0
    }
  }
  $now = (Get-Date).ToUniversalTime()
  $cutoff = $now.AddDays(-1 * $RetentionDays)
  $retentionDeleteCount = 0
  $capacityDeleteCount = 0
  $files = @(Get-TranscriptFilesNoReparse -Path $Path)
  foreach ($file in $files) {
    if ($file.LastWriteTimeUtc -lt $cutoff) {
      Remove-Item -LiteralPath $file.FullName -Force -ErrorAction Stop
      $retentionDeleteCount++
    }
  }

  $remaining = @(Get-TranscriptFilesNoReparse -Path $Path | Sort-Object LastWriteTimeUtc)
  [long]$totalBytes = 0
  foreach ($file in $remaining) { $totalBytes += [long]$file.Length }
  foreach ($file in $remaining) {
    if ($totalBytes -le $MaximumBytes) { break }
    $length = [long]$file.Length
    Remove-Item -LiteralPath $file.FullName -Force -ErrorAction Stop
    $totalBytes = [Math]::Max(0, $totalBytes - $length)
    $capacityDeleteCount++
  }

  $finalFiles = @(Get-TranscriptFilesNoReparse -Path $Path)
  $oldestAge = 0
  if ($finalFiles.Count -gt 0) {
    $oldest = $finalFiles | Sort-Object LastWriteTimeUtc | Select-Object -First 1
    $oldestAge = [Math]::Max(0, [int][Math]::Floor(($now - $oldest.LastWriteTimeUtc).TotalSeconds))
  }
  return [ordered]@{
    retentionEnforced=($totalBytes -le $MaximumBytes -and $oldestAge -le ($RetentionDays * 86400))
    transcriptBytes=$totalBytes
    oldestTranscriptAgeSeconds=$oldestAge
    retentionDeleteCount=$retentionDeleteCount
    capacityDeleteCount=$capacityDeleteCount
  }
}

function Invoke-TranscriptRetentionForPolicy {
  param(
    [Parameter(Mandatory=$true)][object]$Policy,
    [Parameter(Mandatory=$true)][object]$Baseline
  )
  $outputPath = [string]$Policy.OutputDirectory
  if ([string]::IsNullOrWhiteSpace($outputPath)) {
    throw 'transcript-output-directory-missing'
  }
  return [ordered]@{
    outputPath = $outputPath
    retention = Invoke-TranscriptRetention `
      -Path $outputPath `
      -RetentionDays ([int]$Baseline.transcriptRetentionDays) `
      -MaximumBytes ([long]$Baseline.maximumTranscriptBytes)
  }
}

function Test-RemoteAddressBroad {
  param([object[]]$RemoteAddresses)

  $broadAliases = @(
    'Any', '*', 'LocalSubnet', 'Internet', 'Intranet', 'RemoteIntranet',
    'DefaultGateway', 'DHCP', 'DNS', 'WINS'
  )
  foreach ($rawValue in @($RemoteAddresses)) {
    foreach ($value in @(([string]$rawValue) -split ',')) {
      $candidate = $value.Trim()
      if ([string]::IsNullOrWhiteSpace($candidate)) { return $true }
      if (@($broadAliases | Where-Object { $_ -ieq $candidate }).Count -gt 0) {
        return $true
      }
      if ($candidate -match '^(.+)/(\d{1,3})$') {
        try {
          $network = [System.Net.IPAddress]::Parse($Matches[1])
          $prefixLength = [int]$Matches[2]
          $maximumPrefix = if (
            $network.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork
          ) { 32 } elseif (
            $network.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetworkV6
          ) { 128 } else { 0 }
          if ($maximumPrefix -eq 0 -or $prefixLength -lt 0 -or $prefixLength -gt $maximumPrefix) {
            return $true
          }
          if ($prefixLength -lt $maximumPrefix) { return $true }
          continue
        } catch {
          return $true
        }
      }
      if ($candidate -match '^(.+)-(.+)$') {
        try {
          $rangeStart = [System.Net.IPAddress]::Parse($Matches[1].Trim())
          $rangeEnd = [System.Net.IPAddress]::Parse($Matches[2].Trim())
          if (-not $rangeStart.Equals($rangeEnd)) { return $true }
          continue
        } catch {
          return $true
        }
      }
      try {
        [void][System.Net.IPAddress]::Parse($candidate)
      } catch {
        # Unknown Windows firewall keywords are rejected closed.
        return $true
      }
    }
  }
  return $false
}

function Get-FirewallObservation {
  param([Parameter(Mandatory=$true)][object]$Baseline)

  function Test-ProhibitedPortCoverage {
    param([object[]]$LocalPorts, [string[]]$ProhibitedPorts)
    foreach ($rawValue in @($LocalPorts)) {
      foreach ($value in @(([string]$rawValue) -split ',')) {
        $candidate = $value.Trim()
        if ($candidate -in @('Any', '*')) { return $true }
        if ($candidate -match '^(\d+)-(\d+)$') {
          $start = [int]$Matches[1]
          $end = [int]$Matches[2]
          if (@($ProhibitedPorts | Where-Object { [int]$_ -ge $start -and [int]$_ -le $end }).Count -gt 0) {
            return $true
          }
        } elseif ($candidate -in $ProhibitedPorts) {
          return $true
        }
      }
    }
    return $false
  }

  $matched = 0
  foreach ($expectedRule in @($Baseline.expectedFirewallRules)) {
    $rule = Get-NetFirewallRule -Name ([string]$expectedRule.name) -ErrorAction SilentlyContinue
    if ($null -eq $rule) { continue }
    $portFilter = $rule | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue
    $addressFilter = $rule | Get-NetFirewallAddressFilter -ErrorAction SilentlyContinue
    $applicationFilter = $rule | Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue
    $serviceFilter = $rule | Get-NetFirewallServiceFilter -ErrorAction SilentlyContinue
    $remoteAddresses = @($addressFilter.RemoteAddress | ForEach-Object {
      @(([string]$_) -split ',') | ForEach-Object { $_.Trim() }
    } | Where-Object { $_ })
    $localPorts = @($portFilter.LocalPort | ForEach-Object {
      @(([string]$_) -split ',') | ForEach-Object { $_.Trim() }
    } | Where-Object { $_ })
    $localAddresses = @($addressFilter.LocalAddress | ForEach-Object {
      @(([string]$_) -split ',') | ForEach-Object { $_.Trim() }
    } | Where-Object { $_ })
    $programs = @($applicationFilter.Program | ForEach-Object {
      @(([string]$_) -split ',') | ForEach-Object { $_.Trim() }
    } | Where-Object { $_ })
    $services = @($serviceFilter.Service | ForEach-Object {
      @(([string]$_) -split ',') | ForEach-Object { $_.Trim() }
    } | Where-Object { $_ })
    $profiles = @(([string]$rule.Profile -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $remoteMatches = (
      $remoteAddresses.Count -eq 1 -and
      $remoteAddresses[0] -ieq ([string]$expectedRule.remoteAddress)
    )
    $portMatches = (
      $localPorts.Count -eq 1 -and
      $localPorts[0] -eq ([string]$expectedRule.localPort)
    )
    if (
      [string]$rule.Enabled -eq 'True' -and
      [string]$rule.Direction -eq 'Inbound' -and
      [string]$rule.Action -eq 'Allow' -and
      $profiles.Count -eq 1 -and
      $profiles[0] -ieq ([string]$expectedRule.profile) -and
      [string]$portFilter.Protocol -in @('TCP', '6') -and
      $portMatches -and
      $remoteMatches -and
      $localAddresses.Count -eq 1 -and
      $localAddresses[0] -ieq ([string]$expectedRule.localAddress) -and
      $programs.Count -eq 1 -and
      $programs[0] -ieq ([string]$expectedRule.program) -and
      $services.Count -eq 1 -and
      $services[0] -ieq ([string]$expectedRule.service)
    ) { $matched++ }
  }

  $conflicts = New-Object System.Collections.Generic.HashSet[string]
  $prohibitedPorts = @($Baseline.prohibitedBroadInboundPorts | ForEach-Object { [string]$_ })
  $candidateRules = @(Get-NetFirewallRule -Direction Inbound -Action Allow -Enabled True -ErrorAction Stop)
  foreach ($rule in $candidateRules) {
    $portFilter = $rule | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue
    $addressFilter = $rule | Get-NetFirewallAddressFilter -ErrorAction SilentlyContinue
    if ($null -eq $portFilter -or $null -eq $addressFilter) { continue }
    $ports = @($portFilter.LocalPort | ForEach-Object { [string]$_ })
    $remoteAddresses = @($addressFilter.RemoteAddress | ForEach-Object { [string]$_ })
    $portConflict = Test-ProhibitedPortCoverage -LocalPorts $ports -ProhibitedPorts $prohibitedPorts
    $broadRemote = Test-RemoteAddressBroad -RemoteAddresses $remoteAddresses
    if ($portConflict -and $broadRemote) { [void]$conflicts.Add([string]$rule.Name) }
  }

  $runningEset = @($Baseline.esetCoreServices | Where-Object {
    $service = Get-Service -Name ([string]$_) -ErrorAction SilentlyContinue
    $null -ne $service -and $service.Status -eq [System.ServiceProcess.ServiceControllerStatus]::Running
  }).Count
  return [ordered]@{
    queryOk = $true
    expectedRuleCount = @($Baseline.expectedFirewallRules).Count
    expectedRuleMatchCount = $matched
    broadConflictCount = $conflicts.Count
    esetCoreRunningCount = $runningEset
  }
}

$baseline = Get-Content -LiteralPath $BaselinePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($baseline.schemaVersion -ne 'faz24.windows-audit-baseline.v1') {
  throw 'baseline-schema-mismatch'
}
$targetAccount = New-Object System.Security.Principal.NTAccount($env:COMPUTERNAME, [string]$baseline.targetUser)
$targetSid = $targetAccount.Translate([System.Security.Principal.SecurityIdentifier]).Value
$snapshotDirectory = Split-Path -Parent $SnapshotPath
$now = (Get-Date).ToUniversalTime()
$collectedAt = Get-UtcText -Value $now
$controls = [ordered]@{}

try {
  $policy = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\Transcription' -ErrorAction Stop
  $retentionResult = Invoke-TranscriptRetentionForPolicy -Policy $policy -Baseline $baseline
  $outputPath = [string]$retentionResult.outputPath
  $retention = $retentionResult.retention
  $observed = [ordered]@{
    queryOk = $true
    policyEnabled = ($policy.EnableTranscripting -eq 1)
    invocationHeaderEnabled = ($policy.EnableInvocationHeader -eq 1)
    protectedOutputAcl = ($outputPath -and (Test-ExactProtectedAcl -Path $outputPath -Directory))
    protectedSnapshotDirectoryAcl = (Test-ExactProtectedAcl -Path $snapshotDirectory -ReadOnlySid $targetSid -Directory)
    protectedSnapshotFileAcl = ((Test-Path -LiteralPath $SnapshotPath) -and (Test-ExactProtectedAcl -Path $SnapshotPath -ReadOnlySid $targetSid))
    retentionEnforced = [bool]$retention.retentionEnforced
    transcriptBytes = [long]$retention.transcriptBytes
    oldestTranscriptAgeSeconds = [int]$retention.oldestTranscriptAgeSeconds
    retentionDeleteCount = [int]$retention.retentionDeleteCount
    capacityDeleteCount = [int]$retention.capacityDeleteCount
  }
  $expected = [ordered]@{ queryOk = $true; policyEnabled = $true; invocationHeaderEnabled = $true; protectedOutputAcl = $true; protectedSnapshotDirectoryAcl = $true; protectedSnapshotFileAcl = $true; retentionEnforced=$true; maximumRetentionDays=[int]$baseline.transcriptRetentionDays; maximumTranscriptBytes=[long]$baseline.maximumTranscriptBytes }
  $pass = ($observed.queryOk -and $observed.policyEnabled -and $observed.invocationHeaderEnabled -and $observed.protectedOutputAcl -and $observed.protectedSnapshotDirectoryAcl -and $observed.protectedSnapshotFileAcl -and $observed.retentionEnforced -and $observed.transcriptBytes -le $expected.maximumTranscriptBytes -and $observed.oldestTranscriptAgeSeconds -le ($expected.maximumRetentionDays * 86400))
  $controls.'powershell-transcription' = New-Control -Expected $expected -Observed $observed -Pass $pass -CollectedAt $collectedAt -MaxAgeSeconds 900 -ErrorClass 'transcription-policy-drift'
} catch {
  $controls.'powershell-transcription' = New-Control -Expected @{ queryOk=$true; policyEnabled=$true; invocationHeaderEnabled=$true; protectedOutputAcl=$true; protectedSnapshotDirectoryAcl=$true; protectedSnapshotFileAcl=$true; retentionEnforced=$true; maximumRetentionDays=[int]$baseline.transcriptRetentionDays; maximumTranscriptBytes=[long]$baseline.maximumTranscriptBytes } -Observed @{ queryOk=$false; policyEnabled=$false; invocationHeaderEnabled=$false; protectedOutputAcl=$false; protectedSnapshotDirectoryAcl=$false; protectedSnapshotFileAcl=$false; retentionEnforced=$false; transcriptBytes=0; oldestTranscriptAgeSeconds=0; retentionDeleteCount=0; capacityDeleteCount=0 } -Pass $false -CollectedAt $collectedAt -MaxAgeSeconds 900 -ErrorClass $_.Exception.GetType().Name
}

try {
  $policy = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging' -ErrorAction Stop
  [void](Get-WinEvent -ListLog 'Microsoft-Windows-PowerShell/Operational' -ErrorAction Stop)
  $since = (Get-Date).AddHours(-1 * [int]$baseline.lookbackHours)
  $events = @(Get-WinEvent -FilterHashtable @{ LogName='Microsoft-Windows-PowerShell/Operational'; Id=4104; StartTime=$since } -ErrorAction SilentlyContinue)
  $observed = [ordered]@{ queryOk=$true; policyEnabled=($policy.EnableScriptBlockLogging -eq 1); eventCount=$events.Count }
  $expected = [ordered]@{ queryOk=$true; policyEnabled=$true; minimumEventCount=1 }
  $pass = ($observed.policyEnabled -and $observed.eventCount -ge 1)
  $controls.'powershell-script-block' = New-Control -Expected $expected -Observed $observed -Pass $pass -CollectedAt $collectedAt -MaxAgeSeconds 900 -ErrorClass 'script-block-policy-or-event-drift'
} catch {
  $controls.'powershell-script-block' = New-Control -Expected @{ queryOk=$true; policyEnabled=$true; minimumEventCount=1 } -Observed @{ queryOk=$false; policyEnabled=$false; eventCount=0 } -Pass $false -CollectedAt $collectedAt -MaxAgeSeconds 900 -ErrorClass $_.Exception.GetType().Name
}

try {
  [void](Get-WinEvent -LogName Security -MaxEvents 1 -ErrorAction Stop)
  $auditFailureEnabled = Test-LogonFailureAuditEnabled
  $milliseconds = [int]$baseline.lookbackHours * 3600000
  $xpath = "*[System[(EventID=4625) and TimeCreated[timediff(@SystemTime) <= $milliseconds]]]"
  $events = @(Get-WinEvent -LogName Security -FilterXPath $xpath -ErrorAction SilentlyContinue)
  $observed = [ordered]@{ securityLogQueryable=$true; auditFailureEnabled=$auditFailureEnabled; eventCount=$events.Count }
  $expected = [ordered]@{ securityLogQueryable=$true; auditFailureEnabled=$true }
  $controls.'failed-login' = New-Control -Expected $expected -Observed $observed -Pass ($auditFailureEnabled) -CollectedAt $collectedAt -MaxAgeSeconds 900 -ErrorClass 'failed-login-audit-drift'
} catch {
  $controls.'failed-login' = New-Control -Expected @{ securityLogQueryable=$true; auditFailureEnabled=$true } -Observed @{ securityLogQueryable=$false; auditFailureEnabled=$false; eventCount=0 } -Pass $false -CollectedAt $collectedAt -MaxAgeSeconds 900 -ErrorClass $_.Exception.GetType().Name
}

try {
  $observed = Get-WireGuardObservation
  $expected = [ordered]@{ queryOk=$true; minimumRunningServiceCount=1; minimumInterfaceCount=1; minimumPeerCount=1; maximumHandshakeAgeSeconds=[int]$baseline.maximumHandshakeAgeSeconds }
  $ageOk = ($null -ne $observed.latestHandshakeAgeSeconds -and $observed.latestHandshakeAgeSeconds -le $expected.maximumHandshakeAgeSeconds)
  $pass = ($observed.queryOk -and $observed.runningServiceCount -ge 1 -and $observed.interfaceCount -ge 1 -and $observed.peerCount -ge 1 -and $ageOk)
  $controls.'wireguard-health' = New-Control -Expected $expected -Observed $observed -Pass $pass -CollectedAt $collectedAt -MaxAgeSeconds 900 -ErrorClass 'wireguard-health-drift'
} catch {
  $controls.'wireguard-health' = New-Control -Expected @{ queryOk=$true; minimumRunningServiceCount=1; minimumInterfaceCount=1; minimumPeerCount=1; maximumHandshakeAgeSeconds=[int]$baseline.maximumHandshakeAgeSeconds } -Observed @{ queryOk=$false; dumpExitCode=-1; runningServiceCount=0; interfaceCount=0; peerCount=0; latestHandshakeAgeSeconds=$null } -Pass $false -CollectedAt $collectedAt -MaxAgeSeconds 900 -ErrorClass $_.Exception.GetType().Name
}

try {
  $observed = Get-FirewallObservation -Baseline $baseline
  $expected = [ordered]@{ queryOk=$true; expectedRuleCount=@($baseline.expectedFirewallRules).Count; minimumEsetCoreRunningCount=@($baseline.esetCoreServices).Count }
  $pass = ($observed.queryOk -and $observed.expectedRuleMatchCount -eq $expected.expectedRuleCount -and $observed.broadConflictCount -eq 0 -and $observed.esetCoreRunningCount -ge $expected.minimumEsetCoreRunningCount)
  $controls.'eset-firewall-drift' = New-Control -Expected $expected -Observed $observed -Pass $pass -CollectedAt $collectedAt -MaxAgeSeconds 900 -ErrorClass 'firewall-or-eset-drift'
} catch {
  $controls.'eset-firewall-drift' = New-Control -Expected @{ queryOk=$true; expectedRuleCount=@($baseline.expectedFirewallRules).Count; minimumEsetCoreRunningCount=@($baseline.esetCoreServices).Count } -Observed @{ queryOk=$false; expectedRuleCount=@($baseline.expectedFirewallRules).Count; expectedRuleMatchCount=0; broadConflictCount=0; esetCoreRunningCount=0 } -Pass $false -CollectedAt $collectedAt -MaxAgeSeconds 900 -ErrorClass $_.Exception.GetType().Name
}

try {
  $service = Get-Service -Name 'w32time' -ErrorAction Stop
  $serviceInstance = Get-CimInstance -ClassName Win32_Service -Filter "Name='w32time'" -ErrorAction Stop
  if ([int]$serviceInstance.ProcessId -le 0) { throw 'w32time-process-not-running' }
  $serviceProcess = Get-Process -Id ([int]$serviceInstance.ProcessId) -ErrorAction Stop
  $serviceProcessStartedAt = $serviceProcess.StartTime.ToUniversalTime()
  $null = & w32tm /query /status 2>$null
  $statusExitCode = $LASTEXITCODE
  $sourceLines = @(& w32tm /query /source 2>$null)
  $sourceExitCode = $LASTEXITCODE
  $since = (Get-Date).AddSeconds(-1 * [int]$baseline.maximumSuccessEventAgeSeconds)
  $events = @(Get-WinEvent -FilterHashtable @{ LogName='System'; ProviderName='Microsoft-Windows-Time-Service'; Id=35; StartTime=$since } -ErrorAction SilentlyContinue)
  $latest = $events | Sort-Object TimeCreated -Descending | Select-Object -First 1
  $latestAge = $null
  if ($null -ne $latest) { $latestAge = Get-NonNegativeAgeSeconds -Value $latest.TimeCreated }
  $sourceValues = New-Object System.Collections.Generic.List[string]
  foreach ($line in @($sourceLines)) {
    if (-not [string]::IsNullOrWhiteSpace([string]$line)) { $sourceValues.Add(([string]$line).Trim()) }
  }
  $sourcePresent = ($sourceExitCode -eq 0 -and $sourceValues.Count -eq 1)
  $sourceFormatSafe = (
    $sourcePresent -and
    $sourceValues[0] -notmatch '\s' -and
    $sourceValues[0] -match '^[A-Za-z0-9][A-Za-z0-9._:-]*(?:,0x[0-9A-Fa-f]+)?$'
  )
  $timeParameters = Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\Parameters' -ErrorAction Stop
  $syncTypeConfigured = ([string]$timeParameters.Type -in @('NTP', 'NT5DS', 'AllSync'))
  $eventAfterServiceStart = (
    $null -ne $latest -and
    $latest.TimeCreated.ToUniversalTime() -ge $serviceProcessStartedAt
  )
  $sourceSynchronized = (
    $statusExitCode -eq 0 -and
    $sourceFormatSafe -and
    $eventAfterServiceStart -and
    $syncTypeConfigured
  )
  $observed = [ordered]@{
    queryOk = $true
    serviceState = [string]$service.Status
    statusCommandExitCode = $statusExitCode
    sourcePresent = $sourcePresent
    sourceSynchronized = $sourceSynchronized
    syncTypeConfigured = $syncTypeConfigured
    latestSuccessEventAgeSeconds = $latestAge
  }
  $expected = [ordered]@{ queryOk=$true; serviceState='Running'; statusCommandExitCode=0; sourcePresent=$true; sourceSynchronized=$true; syncTypeConfigured=$true; maximumSuccessEventAgeSeconds=[int]$baseline.maximumSuccessEventAgeSeconds }
  $eventFresh = ($null -ne $latestAge -and $latestAge -le $expected.maximumSuccessEventAgeSeconds)
  $pass = ($observed.serviceState -eq 'Running' -and $observed.statusCommandExitCode -eq 0 -and $observed.sourceSynchronized -and $eventFresh)
  $controls.'time-sync' = New-Control -Expected $expected -Observed $observed -Pass $pass -CollectedAt $collectedAt -MaxAgeSeconds 900 -ErrorClass 'time-sync-drift'
} catch {
  $controls.'time-sync' = New-Control -Expected @{ queryOk=$true; serviceState='Running'; statusCommandExitCode=0; sourcePresent=$true; sourceSynchronized=$true; syncTypeConfigured=$true; maximumSuccessEventAgeSeconds=[int]$baseline.maximumSuccessEventAgeSeconds } -Observed @{ queryOk=$false; serviceState='Unknown'; statusCommandExitCode=-1; sourcePresent=$false; sourceSynchronized=$false; syncTypeConfigured=$false; latestSuccessEventAgeSeconds=$null } -Pass $false -CollectedAt $collectedAt -MaxAgeSeconds 900 -ErrorClass $_.Exception.GetType().Name
}

$snapshot = [ordered]@{
  schemaVersion = $SnapshotSchemaVersion
  collectedAt = $collectedAt
  controls = $controls
  redaction = [ordered]@{
    eventMessagesIncluded = $false
    eventIdentitiesIncluded = $false
    commandContentIncluded = $false
    wireGuardKeysIncluded = $false
    wireGuardEndpointsIncluded = $false
  }
}
Write-AtomicJson -Value $snapshot -Path $SnapshotPath
Write-Output ('snapshot=' + $SnapshotPath + ' verdicts=' + (($controls.Values.verdict | Group-Object | ForEach-Object { $_.Name + ':' + $_.Count }) -join ','))
'''


INSTALLER = r'''#requires -Version 5.1
[CmdletBinding()]
param(
  [ValidateSet('Validate','Apply','Rollback')][string]$Mode = 'Validate',
  [string]$TargetUser = __TARGET_USER__,
  [string]$Root = __ROOT__
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$TaskName = 'Faz24-I3-Audit-Snapshot'
$StatePath = Join-Path $Root 'state\initial-rollback.json'
$AclBackupPath = Join-Path $Root 'state\initial-acl.txt'
$CollectorSource = Join-Path $PSScriptRoot 'collect-audit-snapshot.ps1'
$BaselineSource = Join-Path $PSScriptRoot 'baseline.json'
$CollectorPath = Join-Path $Root 'scripts\collect-audit-snapshot.ps1'
$BaselinePath = Join-Path $Root 'config\baseline.json'
$SnapshotPath = Join-Path $Root 'snapshot\audit-snapshot.json'
$TranscriptPath = Join-Path $Root 'transcripts'

function Test-IsAdministrator {
  $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
  return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Initialize-AuditPolicyApi {
  if ('Faz24.InstallerAuditPolicy.NativeMethods' -as [type]) { return }
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace Faz24.InstallerAuditPolicy {
  [StructLayout(LayoutKind.Sequential)]
  public struct AUDIT_POLICY_INFORMATION {
    public Guid AuditSubCategoryGuid;
    public uint AuditingInformation;
    public Guid AuditCategoryGuid;
  }
  public static class NativeMethods {
    [DllImport("advapi32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool AuditQuerySystemPolicy(
      [In] Guid[] pSubCategoryGuids,
      uint PolicyCount,
      out IntPtr ppAuditPolicy
    );
    [DllImport("advapi32.dll")]
    public static extern void AuditFree(IntPtr buffer);
  }
}
'@
}

function Get-LogonAuditPolicyState {
  Initialize-AuditPolicyApi
  $logonGuid = [guid]'0CCE9215-69AE-11D9-BED3-505054503030'
  $buffer = [IntPtr]::Zero
  if (-not [Faz24.InstallerAuditPolicy.NativeMethods]::AuditQuerySystemPolicy(@($logonGuid), 1, [ref]$buffer)) {
    throw ('AuditQuerySystemPolicy:' + [Runtime.InteropServices.Marshal]::GetLastWin32Error())
  }
  try {
    $info = [Runtime.InteropServices.Marshal]::PtrToStructure(
      $buffer,
      [type][Faz24.InstallerAuditPolicy.AUDIT_POLICY_INFORMATION]
    )
    return [ordered]@{
      successEnabled = (($info.AuditingInformation -band 1) -eq 1)
      failureEnabled = (($info.AuditingInformation -band 2) -eq 2)
    }
  } finally {
    [Faz24.InstallerAuditPolicy.NativeMethods]::AuditFree($buffer)
  }
}

function Get-PackageFingerprint {
  $collectorHash = (Get-FileHash -LiteralPath $CollectorSource -Algorithm SHA256).Hash.ToLowerInvariant()
  $baselineHash = (Get-FileHash -LiteralPath $BaselineSource -Algorithm SHA256).Hash.ToLowerInvariant()
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($collectorHash + ':' + $baselineHash)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
  } finally {
    $sha.Dispose()
  }
}

function Write-RollbackState {
  param([Parameter(Mandatory=$true)][object]$State)
  $stateDirectory = Split-Path -Parent $StatePath
  New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
  $temporary = Join-Path $stateDirectory ('.rollback-' + [guid]::NewGuid().ToString('N') + '.tmp')
  try {
    $State | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $StatePath -Force
  } finally {
    Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
  }
}

function Read-RollbackState {
  if (-not (Test-Path -LiteralPath $StatePath)) { throw 'rollback-state-missing' }
  $state = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
  if (
    $state.schemaVersion -ne 'faz24.windows-audit-rollback.v2' -or
    [string]::IsNullOrWhiteSpace([string]$state.transactionId) -or
    [string]::IsNullOrWhiteSpace([string]$state.packageFingerprint) -or
    [string]::IsNullOrWhiteSpace([string]$state.backupDirectory) -or
    -not (Test-Path -LiteralPath ([string]$state.backupDirectory)) -or
    ($state.rootExisted -and (
      [string]::IsNullOrWhiteSpace([string]$state.aclRestoreRoot) -or
      [string]$state.aclRestoreRoot -ne (Split-Path -Parent $Root) -or
      -not (Test-Path -LiteralPath $AclBackupPath)
    ))
  ) { throw 'rollback-state-incomplete' }
  return $state
}

function Get-StateFileEntries {
  param([Parameter(Mandatory=$true)][object]$Files)
  if ($Files -is [System.Collections.IDictionary]) { return @($Files.Values) }
  return @($Files.PSObject.Properties | ForEach-Object { $_.Value })
}

function Get-RegistryState {
  param([string]$Path, [string]$Name)
  try {
    $value = Get-ItemPropertyValue -Path $Path -Name $Name -ErrorAction Stop
    $kind = (Get-Item -Path $Path -ErrorAction Stop).GetValueKind($Name).ToString()
    return [ordered]@{ exists=$true; value=$value; kind=$kind }
  } catch {
    return [ordered]@{ exists=$false; value=$null; kind=$null }
  }
}

function Set-RegistryState {
  param([string]$Path, [string]$Name, [object]$State)
  if ($State.exists) {
    New-Item -Path $Path -Force | Out-Null
    $supportedKinds = @('String','ExpandString','Binary','DWord','MultiString','QWord')
    if ([string]$State.kind -notin $supportedKinds) { throw ('unsupported-registry-kind:' + [string]$State.kind) }
    New-ItemProperty -Path $Path -Name $Name -Value $State.value -PropertyType ([string]$State.kind) -Force | Out-Null
  } else {
    Remove-ItemProperty -Path $Path -Name $Name -ErrorAction SilentlyContinue
  }
}

function Get-RuleState {
  param([string]$Name)
  $rule = Get-NetFirewallRule -Name $Name -ErrorAction SilentlyContinue
  if ($null -eq $rule) { return [ordered]@{ name=$Name; exists=$false } }
  return [ordered]@{ name=[string]$rule.Name; exists=$true }
}

function Test-RemoteAddressBroad {
  param([object[]]$RemoteAddresses)

  $broadAliases = @(
    'Any', '*', 'LocalSubnet', 'Internet', 'Intranet', 'RemoteIntranet',
    'DefaultGateway', 'DHCP', 'DNS', 'WINS'
  )
  foreach ($rawValue in @($RemoteAddresses)) {
    foreach ($value in @(([string]$rawValue) -split ',')) {
      $candidate = $value.Trim()
      if ([string]::IsNullOrWhiteSpace($candidate)) { return $true }
      if (@($broadAliases | Where-Object { $_ -ieq $candidate }).Count -gt 0) {
        return $true
      }
      if ($candidate -match '^(.+)/(\d{1,3})$') {
        try {
          $network = [System.Net.IPAddress]::Parse($Matches[1])
          $prefixLength = [int]$Matches[2]
          $maximumPrefix = if (
            $network.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork
          ) { 32 } elseif (
            $network.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetworkV6
          ) { 128 } else { 0 }
          if ($maximumPrefix -eq 0 -or $prefixLength -lt 0 -or $prefixLength -gt $maximumPrefix) {
            return $true
          }
          if ($prefixLength -lt $maximumPrefix) { return $true }
          continue
        } catch {
          return $true
        }
      }
      if ($candidate -match '^(.+)-(.+)$') {
        try {
          $rangeStart = [System.Net.IPAddress]::Parse($Matches[1].Trim())
          $rangeEnd = [System.Net.IPAddress]::Parse($Matches[2].Trim())
          if (-not $rangeStart.Equals($rangeEnd)) { return $true }
          continue
        } catch {
          return $true
        }
      }
      try {
        [void][System.Net.IPAddress]::Parse($candidate)
      } catch {
        # Unknown Windows firewall keywords are rejected closed.
        return $true
      }
    }
  }
  return $false
}

function Get-BroadConflictRules {
  param([object]$Baseline)

  function Test-ProhibitedPortCoverage {
    param([object[]]$LocalPorts, [string[]]$ProhibitedPorts)
    foreach ($rawValue in @($LocalPorts)) {
      foreach ($value in @(([string]$rawValue) -split ',')) {
        $candidate = $value.Trim()
        if ($candidate -in @('Any', '*')) { return $true }
        if ($candidate -match '^(\d+)-(\d+)$') {
          $start = [int]$Matches[1]
          $end = [int]$Matches[2]
          if (@($ProhibitedPorts | Where-Object { [int]$_ -ge $start -and [int]$_ -le $end }).Count -gt 0) {
            return $true
          }
        } elseif ($candidate -in $ProhibitedPorts) {
          return $true
        }
      }
    }
    return $false
  }

  $ports = @($Baseline.prohibitedBroadInboundPorts | ForEach-Object { [string]$_ })
  $results = New-Object System.Collections.Generic.List[object]
  foreach ($rule in @(Get-NetFirewallRule -Direction Inbound -Action Allow -Enabled True -ErrorAction Stop)) {
    $port = $rule | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue
    $address = $rule | Get-NetFirewallAddressFilter -ErrorAction SilentlyContinue
    if ($null -eq $port -or $null -eq $address) { continue }
    $portConflict = Test-ProhibitedPortCoverage -LocalPorts @($port.LocalPort) -ProhibitedPorts $ports
    $broadRemote = Test-RemoteAddressBroad -RemoteAddresses @($address.RemoteAddress)
    if ($portConflict -and $broadRemote) { $results.Add($rule) }
  }
  return @($results)
}

function Save-InitialState {
  param([object]$Baseline, [bool]$RootExisted, [string]$PackageFingerprint)
  if (Test-Path -LiteralPath $StatePath) {
    $existing = Read-RollbackState
    if ([string]$existing.packageFingerprint -ne $PackageFingerprint) {
      throw 'rollback-required-before-package-change'
    }
    if ([string]$existing.applyStatus -ne 'applied') {
      throw 'rollback-required-before-retry'
    }
    return $existing
  }
  $temporaryId = [guid]::NewGuid().ToString('N')
  $temporaryState = Join-Path $env:TEMP ('faz24-i3-state-' + $temporaryId + '.json')
  $temporaryAcl = Join-Path $env:TEMP ('faz24-i3-acl-' + $temporaryId + '.txt')
  $stateDirectory = Split-Path -Parent $StatePath
  $stateDirectoryExisted = Test-Path -LiteralPath $stateDirectory
  $backupDirectory = Join-Path $stateDirectory ('backup-' + $temporaryId)
  $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  $taskXml = $null
  if ($null -ne $task) { $taskXml = Export-ScheduledTask -TaskName $TaskName }
  $transcriptionPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\Transcription'
  $scriptBlockPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging'
  $state = [ordered]@{
    schemaVersion='faz24.windows-audit-rollback.v2'; transactionId=$temporaryId
    packageFingerprint=$PackageFingerprint; applyStatus='captured'
    capturedAt=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    rootExisted=$RootExisted; stateDirectoryExisted=$stateDirectoryExisted
    aclRestoreRoot=(Split-Path -Parent $Root)
    backupDirectory=$backupDirectory; taskXml=$taskXml
    registry=[ordered]@{
      enableTranscripting=(Get-RegistryState $transcriptionPath 'EnableTranscripting')
      enableInvocationHeader=(Get-RegistryState $transcriptionPath 'EnableInvocationHeader')
      outputDirectory=(Get-RegistryState $transcriptionPath 'OutputDirectory')
      enableScriptBlockLogging=(Get-RegistryState $scriptBlockPath 'EnableScriptBlockLogging')
    }
    logonAuditPolicy=(Get-LogonAuditPolicyState)
    exactRules=@($Baseline.expectedFirewallRules | ForEach-Object { Get-RuleState -Name ([string]$_.name) })
    files=[ordered]@{
      collector=[ordered]@{ path=$CollectorPath; existed=(Test-Path -LiteralPath $CollectorPath); backupName='collector.ps1' }
      baseline=[ordered]@{ path=$BaselinePath; existed=(Test-Path -LiteralPath $BaselinePath); backupName='baseline.json' }
      snapshot=[ordered]@{ path=$SnapshotPath; existed=(Test-Path -LiteralPath $SnapshotPath); backupName='snapshot.json' }
    }
  }
  try {
    if ($RootExisted) {
      & icacls $Root /save $temporaryAcl /t /c /q | Out-Null
      if ($LASTEXITCODE -ne 0) { throw 'acl-backup-failed' }
    }
    $state | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporaryState -Encoding UTF8
    New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
    foreach ($fileState in @(Get-StateFileEntries -Files $state.files)) {
      if ($fileState.existed) {
        Copy-Item -LiteralPath ([string]$fileState.path) -Destination (Join-Path $backupDirectory ([string]$fileState.backupName)) -Force
      }
    }
    if ($RootExisted) { Move-Item -LiteralPath $temporaryAcl -Destination $AclBackupPath -Force }
    Move-Item -LiteralPath $temporaryState -Destination $StatePath -Force
    return Read-RollbackState
  } finally {
    Remove-Item -LiteralPath $temporaryState,$temporaryAcl -Force -ErrorAction SilentlyContinue
  }
}

function Restore-InitialState {
  param([Parameter(Mandatory=$true)][object]$State)

  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  if ($State.taskXml) {
    Register-ScheduledTask -TaskName $TaskName -Xml ([string]$State.taskXml) -Force | Out-Null
  }
  $transcriptionPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\Transcription'
  $scriptBlockPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging'
  Set-RegistryState $transcriptionPath 'EnableTranscripting' $State.registry.enableTranscripting
  Set-RegistryState $transcriptionPath 'EnableInvocationHeader' $State.registry.enableInvocationHeader
  Set-RegistryState $transcriptionPath 'OutputDirectory' $State.registry.outputDirectory
  Set-RegistryState $scriptBlockPath 'EnableScriptBlockLogging' $State.registry.enableScriptBlockLogging

  $successSetting = if ($State.logonAuditPolicy.successEnabled) { 'enable' } else { 'disable' }
  $failureSetting = if ($State.logonAuditPolicy.failureEnabled) { 'enable' } else { 'disable' }
  & auditpol /set /subcategory:'{0CCE9215-69AE-11D9-BED3-505054503030}' ('/success:' + $successSetting) ('/failure:' + $failureSetting) | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'logon-audit-policy-restore-failed' }

  foreach ($rule in @($State.exactRules)) {
    if (-not $rule.exists) {
      Remove-NetFirewallRule -Name ([string]$rule.name) -ErrorAction SilentlyContinue
    }
  }
  foreach ($fileState in @(Get-StateFileEntries -Files $State.files)) {
    $path = [string]$fileState.path
    if ($fileState.existed) {
      $backupPath = Join-Path ([string]$State.backupDirectory) ([string]$fileState.backupName)
      if (-not (Test-Path -LiteralPath $backupPath)) { throw 'rollback-file-backup-missing' }
      New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
      Copy-Item -LiteralPath $backupPath -Destination $path -Force
    } else {
      Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
  }

  if ($State.rootExisted -and (Test-Path -LiteralPath $AclBackupPath)) {
    $restoreRoot = [string]$State.aclRestoreRoot
    if ([string]::IsNullOrWhiteSpace($restoreRoot) -or $restoreRoot -ne (Split-Path -Parent $Root)) {
      throw 'rollback-acl-restore-root-mismatch'
    }
    & icacls $restoreRoot /restore $AclBackupPath /c /q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'acl-restore-failed' }
    Remove-Item -LiteralPath ([string]$State.backupDirectory),$StatePath,$AclBackupPath -Recurse -Force -ErrorAction SilentlyContinue
    $stateDirectory = Split-Path -Parent $StatePath
    if (-not $State.stateDirectoryExisted -and (Test-Path -LiteralPath $stateDirectory)) {
      if (@(Get-ChildItem -LiteralPath $stateDirectory -Force).Count -eq 0) {
        Remove-Item -LiteralPath $stateDirectory -Force
      }
    }
  } elseif (-not $State.rootExisted) {
    Remove-Item -LiteralPath $Root -Recurse -Force
  } else {
    throw 'rollback-acl-backup-missing'
  }
}

function Set-ProtectedAcl {
  param([string]$UserName)
  $account = New-Object System.Security.Principal.NTAccount($env:COMPUTERNAME, $UserName)
  $targetSid = $account.Translate([System.Security.Principal.SecurityIdentifier]).Value

  function New-ExactDirectorySecurity {
    param([string[]]$ReadSids)
    $security = New-Object System.Security.AccessControl.DirectorySecurity
    $security.SetAccessRuleProtection($true, $false)
    foreach ($sidValue in @('S-1-5-18','S-1-5-32-544')) {
      $sid = New-Object System.Security.Principal.SecurityIdentifier($sidValue)
      $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $sid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        ([System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit),
        [System.Security.AccessControl.PropagationFlags]::None,
        [System.Security.AccessControl.AccessControlType]::Allow
      )
      [void]$security.AddAccessRule($rule)
    }
    foreach ($sidValue in @($ReadSids)) {
      $sid = New-Object System.Security.Principal.SecurityIdentifier($sidValue)
      $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $sid,
        [System.Security.AccessControl.FileSystemRights]::ReadAndExecute,
        ([System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit),
        [System.Security.AccessControl.PropagationFlags]::None,
        [System.Security.AccessControl.AccessControlType]::Allow
      )
      [void]$security.AddAccessRule($rule)
    }
    return $security
  }

  function New-ExactFileSecurity {
    param([string[]]$ReadSids)
    $security = New-Object System.Security.AccessControl.FileSecurity
    $security.SetAccessRuleProtection($true, $false)
    foreach ($sidValue in @('S-1-5-18','S-1-5-32-544')) {
      $sid = New-Object System.Security.Principal.SecurityIdentifier($sidValue)
      $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $sid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
      )
      [void]$security.AddAccessRule($rule)
    }
    foreach ($sidValue in @($ReadSids)) {
      $sid = New-Object System.Security.Principal.SecurityIdentifier($sidValue)
      $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $sid,
        [System.Security.AccessControl.FileSystemRights]::Read,
        [System.Security.AccessControl.AccessControlType]::Allow
      )
      [void]$security.AddAccessRule($rule)
    }
    return $security
  }

  $privateDirectories = @(
    $Root,
    (Join-Path $Root 'scripts'),
    (Join-Path $Root 'config'),
    $TranscriptPath,
    (Join-Path $Root 'state')
  )
  foreach ($path in $privateDirectories) {
    Set-Acl -LiteralPath $path -AclObject (New-ExactDirectorySecurity -ReadSids @())
  }
  Set-Acl -LiteralPath (Join-Path $Root 'snapshot') -AclObject (
    New-ExactDirectorySecurity -ReadSids @($targetSid)
  )
  foreach ($file in @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force -ErrorAction Stop)) {
    $readSids = @()
    if ($file.FullName.StartsWith((Join-Path $Root 'snapshot') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
      $readSids = @($targetSid)
    }
    Set-Acl -LiteralPath $file.FullName -AclObject (New-ExactFileSecurity -ReadSids $readSids)
  }
}

function Install-ExactRules {
  param([object]$Baseline)
  foreach ($expected in @($Baseline.expectedFirewallRules)) {
    $existing = Get-NetFirewallRule -Name ([string]$expected.name) -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
      New-NetFirewallRule -Name ([string]$expected.name) -DisplayName ([string]$expected.displayName) -Direction Inbound -Action Allow -Enabled True -Profile Any -Protocol TCP -LocalPort ([int]$expected.localPort) -LocalAddress Any -RemoteAddress ([string]$expected.remoteAddress) -Program Any -Service Any | Out-Null
    }
  }
}

function Assert-ReservedRuleNamesAvailable {
  param([object]$Baseline)
  foreach ($expected in @($Baseline.expectedFirewallRules)) {
    $rule = Get-NetFirewallRule -Name ([string]$expected.name) -ErrorAction SilentlyContinue
    if ($null -eq $rule) { continue }
    $port = $rule | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue
    $address = $rule | Get-NetFirewallAddressFilter -ErrorAction SilentlyContinue
    $application = $rule | Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue
    $service = $rule | Get-NetFirewallServiceFilter -ErrorAction SilentlyContinue
    $remoteAddresses = @($address.RemoteAddress | ForEach-Object {
      @(([string]$_) -split ',') | ForEach-Object { $_.Trim() }
    } | Where-Object { $_ })
    $localPorts = @($port.LocalPort | ForEach-Object {
      @(([string]$_) -split ',') | ForEach-Object { $_.Trim() }
    } | Where-Object { $_ })
    $localAddresses = @($address.LocalAddress | ForEach-Object {
      @(([string]$_) -split ',') | ForEach-Object { $_.Trim() }
    } | Where-Object { $_ })
    $programs = @($application.Program | ForEach-Object {
      @(([string]$_) -split ',') | ForEach-Object { $_.Trim() }
    } | Where-Object { $_ })
    $services = @($service.Service | ForEach-Object {
      @(([string]$_) -split ',') | ForEach-Object { $_.Trim() }
    } | Where-Object { $_ })
    $profiles = @(([string]$rule.Profile -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $matches = (
      [string]$rule.Enabled -eq 'True' -and
      [string]$rule.Direction -eq 'Inbound' -and
      [string]$rule.Action -eq 'Allow' -and
      $profiles.Count -eq 1 -and
      $profiles[0] -ieq ([string]$expected.profile) -and
      [string]$port.Protocol -in @('TCP','6') -and
      $localPorts.Count -eq 1 -and
      $localPorts[0] -eq ([string]$expected.localPort) -and
      $remoteAddresses.Count -eq 1 -and
      $remoteAddresses[0] -ieq ([string]$expected.remoteAddress) -and
      $localAddresses.Count -eq 1 -and
      $localAddresses[0] -ieq ([string]$expected.localAddress) -and
      $programs.Count -eq 1 -and
      $programs[0] -ieq ([string]$expected.program) -and
      $services.Count -eq 1 -and
      $services[0] -ieq ([string]$expected.service)
    )
    if (-not $matches) { throw ('reserved-firewall-rule-name-conflict:' + [string]$expected.name) }
  }
}

function Register-SnapshotTask {
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $CollectorPath + '"')
  $trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 5)
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
}

function Invoke-SnapshotAndRead {
  $startedAt = (Get-Date).ToUniversalTime()
  Start-ScheduledTask -TaskName $TaskName
  $deadline = (Get-Date).AddSeconds(45)
  do {
    Start-Sleep -Seconds 1
    if (Test-Path -LiteralPath $SnapshotPath) {
      $snapshot = Get-Content -LiteralPath $SnapshotPath -Raw -Encoding UTF8 | ConvertFrom-Json
      $snapshotTime = [DateTimeOffset]::MinValue
      $timestampOk = [DateTimeOffset]::TryParse([string]$snapshot.collectedAt, [ref]$snapshotTime)
      if (
        $snapshot.schemaVersion -eq 'faz24.windows-audit-snapshot.v1' -and
        $timestampOk -and
        $snapshotTime.UtcDateTime -ge $startedAt.AddSeconds(-5)
      ) { return $snapshot }
    }
  } while ((Get-Date) -lt $deadline)
  throw 'snapshot-not-produced-within-45s'
}

if ($Mode -in @('Apply','Rollback') -and -not (Test-IsAdministrator)) { throw 'administrator-required' }
if (-not (Test-Path -LiteralPath $BaselineSource)) { throw 'baseline-source-missing' }
$baseline = Get-Content -LiteralPath $BaselineSource -Raw -Encoding UTF8 | ConvertFrom-Json
if ($baseline.schemaVersion -ne 'faz24.windows-audit-baseline.v1') { throw 'baseline-schema-mismatch' }
$packageFingerprint = Get-PackageFingerprint

if ($Mode -eq 'Apply') {
  if ($null -eq (Get-LocalUser -Name $TargetUser -ErrorAction SilentlyContinue)) { throw 'target-user-not-found' }
  Assert-ReservedRuleNamesAvailable -Baseline $baseline
  $broad = @(Get-BroadConflictRules -Baseline $baseline)
  if ($broad.Count -gt 0) {
    throw ('broad-firewall-conflicts-require-separate-reviewed-remediation:' + $broad.Count)
  }
  $rootExisted = Test-Path -LiteralPath $Root
  $state = Save-InitialState -Baseline $baseline -RootExisted $rootExisted -PackageFingerprint $packageFingerprint
  if ([string]$state.applyStatus -eq 'applied') {
    $snapshot = Invoke-SnapshotAndRead
    $failed = @($snapshot.controls.PSObject.Properties.Value | Where-Object { $_.verdict -ne 'pass' })
    if ($failed.Count -gt 0) { throw 'existing-apply-drift-detected-use-validate-or-rollback' }
    Write-Output ('mode=Apply status=already-applied snapshot=' + $SnapshotPath + ' failedControls=0')
    exit 0
  }

  $state.applyStatus = 'applying'
  Write-RollbackState -State $state
  try {
    foreach ($path in @($Root, (Join-Path $Root 'scripts'), (Join-Path $Root 'config'), (Join-Path $Root 'snapshot'), $TranscriptPath, (Join-Path $Root 'state'))) { New-Item -ItemType Directory -Path $path -Force | Out-Null }
    Set-ProtectedAcl -UserName $TargetUser
    Copy-Item -LiteralPath $CollectorSource -Destination $CollectorPath -Force
    Copy-Item -LiteralPath $BaselineSource -Destination $BaselinePath -Force
    Set-ProtectedAcl -UserName $TargetUser

    $transcriptionPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\Transcription'
    $scriptBlockPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging'
    New-Item -Path $transcriptionPath -Force | Out-Null
    New-ItemProperty -Path $transcriptionPath -Name EnableTranscripting -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $transcriptionPath -Name EnableInvocationHeader -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $transcriptionPath -Name OutputDirectory -Value $TranscriptPath -PropertyType String -Force | Out-Null
    New-Item -Path $scriptBlockPath -Force | Out-Null
    New-ItemProperty -Path $scriptBlockPath -Name EnableScriptBlockLogging -Value 1 -PropertyType DWord -Force | Out-Null
    & auditpol /set /subcategory:'{0CCE9215-69AE-11D9-BED3-505054503030}' /failure:enable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'failed-login-audit-policy-apply-failed' }

    Install-ExactRules -Baseline $baseline
    Register-SnapshotTask
    $null = Invoke-SnapshotAndRead
    Set-ProtectedAcl -UserName $TargetUser
    $snapshot = Invoke-SnapshotAndRead
    $failed = @($snapshot.controls.PSObject.Properties.Value | Where-Object { $_.verdict -ne 'pass' })
    if ($failed.Count -gt 0) { throw ('apply-validation-failed:' + $failed.Count) }
    $state.applyStatus = 'applied'
    Write-RollbackState -State $state
    Set-ProtectedAcl -UserName $TargetUser
    Write-Output ('mode=Apply snapshot=' + $SnapshotPath + ' failedControls=0 broadConflictsObserved=0')
    exit 0
  } catch {
    $applyError = $_.Exception.Message
    try {
      Restore-InitialState -State $state
    } catch {
      throw ('apply-failed-and-auto-rollback-failed:' + $applyError + ':' + $_.Exception.Message)
    }
    throw ('apply-failed-auto-rollback-completed:' + $applyError)
  }
}

if ($Mode -eq 'Rollback') {
  $state = Read-RollbackState
  Restore-InitialState -State $state
  Write-Output 'mode=Rollback status=restored-from-initial-state'
  exit 0
}

if (-not (Test-IsAdministrator)) { throw 'administrator-required-for-system-task-validation' }
$snapshot = Invoke-SnapshotAndRead
$failed = @($snapshot.controls.PSObject.Properties.Value | Where-Object { $_.verdict -ne 'pass' })
Write-Output ('mode=Validate snapshot=' + $SnapshotPath + ' failedControls=' + $failed.Count)
exit $(if ($failed.Count -eq 0) { 0 } else { 3 })
'''


ROLLBACK = r'''#requires -Version 5.1
[CmdletBinding()]
param(
  [string]$TargetUser = __TARGET_USER__,
  [string]$Root = __ROOT__
)

$installer = Join-Path $PSScriptRoot 'install-audit-controls.ps1'
& $installer -Mode Rollback -TargetUser $TargetUser -Root $Root
exit $LASTEXITCODE
'''


def die(message: str) -> None:
    print(f"ERR {message}", file=sys.stderr)
    raise SystemExit(2)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def ps_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def validate_inputs(target_user: str, management_address: str, root: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", target_user):
        die("target user contains unsupported characters")
    if not re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", management_address):
        die("management address must be an IPv4 literal")
    octets = [int(part) for part in management_address.split(".")]
    if any(part > 255 for part in octets):
        die("management address contains an invalid IPv4 octet")
    if target_user != DEFAULT_TARGET_USER:
        die(f"target user must be the canonical {DEFAULT_TARGET_USER} identity")
    if management_address != DEFAULT_MANAGEMENT_ADDRESS:
        die(f"management address must be the canonical {DEFAULT_MANAGEMENT_ADDRESS} peer")
    if not re.fullmatch(r"[A-Za-z]:\\[A-Za-z0-9 ._\\-]+", root):
        die("root path contains unsupported characters")


def baseline(target_user: str, management_address: str) -> dict[str, Any]:
    return {
        "schemaVersion": BASELINE_SCHEMA_VERSION,
        "controlContractVersion": CONTROL_CONTRACT_VERSION,
        "targetUser": target_user,
        "lookbackHours": 24,
        "maximumHandshakeAgeSeconds": 300,
        "maximumSuccessEventAgeSeconds": 86_400,
        "transcriptRetentionDays": 14,
        "maximumTranscriptBytes": 1_073_741_824,
        "expectedFirewallRules": [
            {
                "name": "FAZ24-I3-WG-SSH-22",
                "displayName": "Faz 24 I3 WireGuard SSH 22",
                "localPort": 22,
                "remoteAddress": management_address,
                "localAddress": "Any",
                "profile": "Any",
                "program": "Any",
                "service": "Any",
            },
            {
                "name": "FAZ24-I3-WG-LIVE-STT-8200",
                "displayName": "Faz 24 I3 WireGuard Live STT 8200",
                "localPort": 8200,
                "remoteAddress": management_address,
                "localAddress": "Any",
                "profile": "Any",
                "program": "Any",
                "service": "Any",
            },
            {
                "name": "FAZ24-I7-WG-MTLS-8243",
                "displayName": "Faz 24 I7 WireGuard mTLS 8243",
                "localPort": 8243,
                "remoteAddress": management_address,
                "localAddress": "Any",
                "profile": "Any",
                "program": "Any",
                "service": "Any",
            },
        ],
        "prohibitedBroadInboundPorts": [22, 8200, 8243],
        "esetCoreServices": ["ekrn", "ekrnEpfw"],
        "redaction": {
            "eventMessagesIncluded": False,
            "eventIdentitiesIncluded": False,
            "commandContentIncluded": False,
            "wireGuardKeysIncluded": False,
            "wireGuardEndpointsIncluded": False,
        },
    }


def render_template(template: str, *, target_user: str, root: str) -> str:
    return (
        template.replace("__TARGET_USER__", ps_single_quoted(target_user))
        .replace("__ROOT__", ps_single_quoted(root))
        .strip()
        + "\n"
    )


def readme(target_user: str, root: str) -> str:
    return f"""# Faz 24 I3 Denetim audit controls operator package

This package keeps `{target_user}` read-only. A SYSTEM scheduled task writes a
bounded metadata snapshot under `{root}`; event messages, identities, command
content, WireGuard keys/endpoints, credentials, audio, and transcript text are
excluded.

## Operator flow

Run from an elevated PowerShell 5.1 session:

```powershell
.\\install-audit-controls.ps1 -Mode Apply
.\\install-audit-controls.ps1 -Mode Validate
```

`Apply` is a package-fingerprint-bound transaction. Before mutation it backs
up pre-existing managed files and captures the initial registry, scoped Logon
audit bits, exact-rule existence, scheduled task and ACL state. A partial or
failed apply automatically restores that state; an incomplete transaction or
different package fingerprint requires an explicit rollback before retry.
Repeated Apply with the same package validates without mutation. The package
creates only missing exact inbound rules limited to the WireGuard management
address and never rewrites an existing reserved rule. Any broad inbound alias,
CIDR or range conflict is a fail-closed preflight error; remediation must be
reviewed and performed separately.

PowerShell transcripts are local privileged operational data. The SYSTEM
collector removes entries older than 14 days and then the oldest entries until
the directory is at most 1 GiB; reparse points fail closed. Only bounded age,
size and deletion counters enter the snapshot, never names or content.

Rollback restores the captured initial state, including pre-existing managed
files, and changes only the Windows Logon audit subcategory captured by this
package; it never performs a full-machine `auditpol /restore`:

```powershell
.\\rollback-audit-controls.ps1
```

## Control boundary

- SYSTEM: policy queries, event-log queries, WireGuard dump counters, firewall
  drift, ESET service state, synchronized time-source health, durable same-volume
  atomic snapshot replacement.
- `{target_user}`: read-only access to the snapshot directory; no policy,
  Security log, WireGuard, firewall, task, or transcript write privilege.
- Fail closed: missing, malformed, stale, semantically weak, or error-bearing
  controls cannot pass the repository verifier.
- Zero failed-login events is valid only when Security-log queryability and the
  native Windows failure-audit bit are both proven.

The package is a restricted operator artifact: `baseline.json` contains the
target account and management address needed by the installer. It contains no
credential or secret, but it is identity-bearing and must not be published as
redacted evidence. Building it does not change the host.
"""


def write_text(path: Path, value: str, *, executable: bool = False) -> None:
    path.write_text(value, encoding="utf-8", newline="\n")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def scan_for_private_material(output_dir: Path) -> None:
    for path in output_dir.iterdir():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in PRIVATE_MARKERS:
            if marker in text:
                die(f"generated package contains forbidden private/secret marker in {path.name}")


def build(args: argparse.Namespace) -> None:
    validate_inputs(args.target_user, args.management_address, args.root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        die("output directory must be empty")

    values = baseline(args.target_user, args.management_address)
    write_text(
        output_dir / COLLECTOR_NAME,
        render_template(SNAPSHOT_COLLECTOR, target_user=args.target_user, root=args.root),
    )
    write_text(
        output_dir / INSTALLER_NAME,
        render_template(INSTALLER, target_user=args.target_user, root=args.root),
    )
    write_text(
        output_dir / ROLLBACK_NAME,
        render_template(ROLLBACK, target_user=args.target_user, root=args.root),
    )
    write_text(output_dir / BASELINE_NAME, json.dumps(values, indent=2, sort_keys=True) + "\n")
    write_text(output_dir / README_NAME, readme(args.target_user, args.root))

    component_names = [COLLECTOR_NAME, INSTALLER_NAME, ROLLBACK_NAME, BASELINE_NAME, README_NAME]
    component_hashes = {
        name: sha256_bytes((output_dir / name).read_bytes()) for name in component_names
    }
    manifest = {
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "targetUser": args.target_user,
        "classification": "restricted-operator-config",
        "containsIdentityMetadata": True,
        "rootPathHash": sha256_bytes(args.root.encode("utf-8"))[:16],
        "managementAddressHash": sha256_bytes(args.management_address.encode("utf-8"))[:16],
        "privilegeModel": {
            "collectorIdentity": "windows-system",
            "transportIdentity": args.target_user,
            "transportAccess": "snapshot-read-only",
        },
        "rollback": {
            "supported": True,
            "initialStateCapturedBeforeMutation": True,
            "automaticOnPartialApplyFailure": True,
            "packageFingerprintBound": True,
            "preexistingManagedFilesRestored": True,
            "auditPolicyRestoreScope": "logon-subcategory-only",
        },
        "operatorFlow": [
            "firewall-impact-decision",
            "apply",
            "validate",
            "rollback-drill",
            "reapply",
            "revalidate",
            "fresh-evidence",
        ],
        "transcriptRetention": {
            "maximumDays": values["transcriptRetentionDays"],
            "maximumBytes": values["maximumTranscriptBytes"],
            "reparsePointsRejected": True,
        },
        "components": component_hashes,
        "secretMaterialIncluded": False,
    }
    write_text(output_dir / MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    sums_names = sorted(component_names + [MANIFEST_NAME])
    sums = "".join(
        f"{sha256_bytes((output_dir / name).read_bytes())}  {name}\n" for name in sums_names
    )
    write_text(output_dir / SHA256SUMS_NAME, sums)
    scan_for_private_material(output_dir)
    print(
        "status=pass "
        f"schema={PACKAGE_SCHEMA_VERSION} "
        f"files={len(list(output_dir.iterdir()))} "
        f"targetUserHash={sha256_bytes(args.target_user.encode('utf-8'))[:16]}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the Faz 24 I3 least-privilege Denetim audit-controls package."
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--target-user", default=DEFAULT_TARGET_USER)
    parser.add_argument("--management-address", default=DEFAULT_MANAGEMENT_ADDRESS)
    parser.add_argument("--root", default=DEFAULT_ROOT)
    return parser.parse_args()


def main() -> int:
    build(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
