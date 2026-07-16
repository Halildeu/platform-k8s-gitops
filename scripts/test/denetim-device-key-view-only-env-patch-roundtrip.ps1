[CmdletBinding()]
param(
  [string]$ScriptPath = (Join-Path $PSScriptRoot "../faz22-remote-ops/denetim-device-key-view-only-env-patch.ps1")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$resolvedScript = (Resolve-Path -LiteralPath $ScriptPath -ErrorAction Stop).Path
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $resolvedScript,
  [ref]$tokens,
  [ref]$errors
)
if ($errors.Count -gt 0) {
  throw "EndpointAgent environment patch script did not parse"
}

foreach ($name in @(
    "Write-AtomicJsonFile",
    "Write-ServiceEnvironmentBackup",
    "Read-ServiceEnvironmentBackup",
    "Assert-MapsEqual",
    "Register-RollbackCleanupTask"
  )) {
  $functionAst = $ast.Find({
      param($node)
      $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq $name
    }, $true)
  if ($null -eq $functionAst) {
    throw "Required environment-backup function is missing: $name"
  }
  Invoke-Expression $functionAst.Extent.Text
}

$root = Join-Path ([IO.Path]::GetTempPath()) (
  "f22-env-backup-roundtrip-" + [Guid]::NewGuid().ToString("N")
)
$path = Join-Path $root "EndpointAgent-environment-before.json"
try {
  New-Item -ItemType Directory -Path $root | Out-Null
  $expected = [ordered]@{}
  for ($index = 0; $index -lt 28; $index++) {
    $key = "KEY_{0:D2}" -f $index
    if ($index -eq 0) {
      $expected[$key] = "one=two"
    } elseif ($index -eq 1) {
      $expected[$key] = "line1" + [Environment]::NewLine + "line2"
    } elseif ($index -eq 2) {
      $expected[$key] = ""
    } else {
      $expected[$key] = "synthetic-value-$index"
    }
  }

  Write-ServiceEnvironmentBackup -Map $expected -Path $path
  $actual = Read-ServiceEnvironmentBackup -Path $path
  Assert-MapsEqual -Expected $expected -Actual $actual
  if ($actual.Count -ne 28) {
    throw "Environment backup row count changed during round-trip"
  }

  function New-ScheduledTaskAction {
    param($Execute, $Argument)
    $script:cleanupArgument = $Argument
    [pscustomobject]@{ Execute = $Execute; Argument = $Argument }
  }
  function New-ScheduledTaskTrigger {
    param([switch]$Once, [switch]$Daily, $At)
    [pscustomobject]@{}
  }
  function New-ScheduledTaskPrincipal {
    param($UserId, $LogonType, $RunLevel)
    [pscustomobject]@{}
  }
  function New-ScheduledTaskSettingsSet {
    param([switch]$StartWhenAvailable, $RestartCount, $RestartInterval, $ExecutionTimeLimit)
    [pscustomobject]@{}
  }
  function Register-ScheduledTask {
    param($TaskName, $Action, $Trigger, $Principal, $Settings, [switch]$Force)
    [pscustomobject]@{ TaskName = $TaskName }
  }
  function Get-ScheduledTask {
    param($TaskName)
    [pscustomobject]@{ TaskName = $TaskName }
  }

  $transactionId = "a" * 32
  if ($env:OS -eq "Windows_NT") {
    $registrationRoot = $root
    $cleanupDirectory = Join-Path $root "denetim-device-key-view-only-$transactionId"
    $lockDirectory = Join-Path $root "migration.lock"
    $lockOwnerFile = Join-Path $lockDirectory "owner.txt"
  } else {
    # Register-RollbackCleanupTask deliberately applies Windows path rules.
    # This shape keeps its boundary check testable under PowerShell Core on CI.
    $registrationRoot = "C:\evidence"
    $cleanupDirectory = "C:\evidence\/denetim-device-key-view-only-$transactionId"
    $lockDirectory = "C:\locks\migration.lock"
    $lockOwnerFile = "C:\locks\migration.lock\owner.txt"
  }
  Register-RollbackCleanupTask `
    -BackupDirectory $cleanupDirectory `
    -EvidenceRootPath $registrationRoot `
    -TransactionLockDirectory $lockDirectory `
    -TransactionLockOwnerFile $lockOwnerFile `
    -BoundTransactionId $transactionId `
    -BoundServiceName EndpointAgent `
    -ExpectedPreMutationServiceEnvironmentSha256 ("b" * 64) `
    -ManagedEnvironmentKeys @("ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID") `
    -DeleteAfterUtc ([DateTime]::UtcNow.AddHours(1).ToString("o")) | Out-Null

  $encoded = ($script:cleanupArgument -split " ")[-1]
  $cleanupCode = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($encoded))
  $cleanupTokens = $null
  $cleanupErrors = $null
  $cleanupAst = [System.Management.Automation.Language.Parser]::ParseInput(
    $cleanupCode,
    [ref]$cleanupTokens,
    [ref]$cleanupErrors
  )
  if ($cleanupErrors.Count -gt 0) {
    throw "Generated deadline cleanup body did not parse"
  }
  $cleanupReaderAst = $cleanupAst.Find({
      param($node)
      $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Read-EnvironmentBackup"
    }, $true)
  if ($null -eq $cleanupReaderAst) {
    throw "Generated deadline cleanup backup reader is missing"
  }
  Invoke-Expression $cleanupReaderAst.Extent.Text
  $environmentBackup = $path
  $cleanupActual = Read-EnvironmentBackup
  Assert-MapsEqual -Expected $expected -Actual $cleanupActual
  if ($cleanupActual.Count -ne 28) {
    throw "Deadline cleanup backup row count changed during round-trip"
  }

  Write-Output "powershellVersion=$($PSVersionTable.PSVersion)"
  Write-Output "rowCount=$($actual.Count)"
  Write-Output "environmentBackupRoundTrip=pass"
  Write-Output "deadlineCleanupBackupRoundTrip=pass"
} finally {
  Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
