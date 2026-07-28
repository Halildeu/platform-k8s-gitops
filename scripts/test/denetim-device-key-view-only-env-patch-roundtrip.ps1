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
    "Assert-ViewOnlyMaskRectBps",
    "Assert-MapValueOrAbsent",
    "New-ManagedEnvironmentRestorationMap",
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

$preMutation = [ordered]@{
  ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_MASK_RECT_BPS = "5000,5000,5000,5000"
  UNRELATED_PRODUCT_SETTING = "pre-mutation"
}
$transactionOwned = [ordered]@{
  ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_MASK_RECT_BPS = "7500,7500,2500,2500"
  UNRELATED_PRODUCT_SETTING = "concurrent-update"
}
$restored = New-ManagedEnvironmentRestorationMap `
  -CurrentMap $transactionOwned `
  -BackupMap $preMutation `
  -ManagedKeys @("ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_MASK_RECT_BPS")
if ($restored["ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_MASK_RECT_BPS"] -ne "5000,5000,5000,5000" -or
    $restored["UNRELATED_PRODUCT_SETTING"] -ne "concurrent-update") {
  throw "Managed VIEW_ONLY mask rollback did not restore the prior value while preserving unrelated updates"
}

$temporaryBridgeKeys = @(
  "ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_TLS_SERVER_NAME",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_OPERATIONS_ENABLED",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64"
)
$bridgePreMutation = [ordered]@{
  ENDPOINT_AGENT_SELF_UPDATE_ENABLED = "true"
  UNRELATED_PRODUCT_SETTING = "before"
}
$bridgeTransactionOwned = [ordered]@{
  ENDPOINT_AGENT_SELF_UPDATE_ENABLED = "true"
  ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED = "true"
  ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR = "remote-bridge-mtls.testai.acik.com:443"
  ENDPOINT_AGENT_REMOTE_BRIDGE_TLS_SERVER_NAME = "remote-bridge-mtls.testai.acik.com"
  ENDPOINT_AGENT_REMOTE_BRIDGE_OPERATIONS_ENABLED = "true"
  ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64 = "public-key"
  UNRELATED_PRODUCT_SETTING = "concurrent-update"
}
$bridgeRestored = New-ManagedEnvironmentRestorationMap `
  -CurrentMap $bridgeTransactionOwned `
  -BackupMap $bridgePreMutation `
  -ManagedKeys $temporaryBridgeKeys
foreach ($temporaryBridgeKey in $temporaryBridgeKeys) {
  if ($bridgeRestored.Contains($temporaryBridgeKey)) {
    throw "Rollback retained a transaction-created bridge key: $temporaryBridgeKey"
  }
}
if ($bridgeRestored["UNRELATED_PRODUCT_SETTING"] -ne "concurrent-update") {
  throw "Bridge rollback did not preserve an unrelated concurrent update"
}

$canonicalExisting = [ordered]@{
  ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED = "true"
}
Assert-MapValueOrAbsent `
  -Map $canonicalExisting `
  -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED" `
  -Expected "true"
Assert-MapValueOrAbsent `
  -Map ([ordered]@{}) `
  -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED" `
  -Expected "true"
foreach ($invalidExisting in @("false", "")) {
  $rejectedExisting = $false
  try {
    Assert-MapValueOrAbsent `
      -Map ([ordered]@{ ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED = $invalidExisting }) `
      -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED" `
      -Expected "true"
  } catch {
    $rejectedExisting = $true
  }
  if (-not $rejectedExisting) {
    throw "Non-canonical existing bridge value was accepted"
  }
}

Assert-ViewOnlyMaskRectBps -Value "7500,7500,2500,2500"
Assert-ViewOnlyMaskRectBps -Value "0,0,10000,10000"
foreach ($invalidMask in @(
    "",
    "0,0,0,1",
    "7500,7500,2500,0",
    "7500,7500,2501,2500",
    "10000,0,1,1",
    "99999,0,1,1",
    "7500,7500,2500",
    "a,7500,2500,2500"
  )) {
  $rejected = $false
  try {
    Assert-ViewOnlyMaskRectBps -Value $invalidMask
  } catch {
    $rejected = $true
  }
  if (-not $rejected) {
    throw "Invalid VIEW_ONLY mask policy was accepted: $invalidMask"
  }
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
