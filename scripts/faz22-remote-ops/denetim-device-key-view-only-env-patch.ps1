#requires -Version 5.1
#requires -RunAsAdministrator

<#
.SYNOPSIS
Activates the Denetim PC TPM device-key and attended VIEW_ONLY endpoint lane.

.DESCRIPTION
This is a bounded post-bootstrap configuration step for the canonical Faz 22.6
Denetim endpoint. It does not install a binary, enroll a certificate, or carry
credentials. The script fails closed unless the expected signed agent binary,
TPM device certificate, TPM readiness, signed self-update policy, and pinned
public permit trust anchor are available. Canonical bridge values absent from a
normal browser-managed install are introduced only as transaction-managed
values and are removed by rollback when they were absent before activation.

The immutable release manifest and public signed provenance evidence are fetched
over HTTPS, hash-pinned, bound to the installed binary, and checked against the
broker verifier public-key digest before mutation. The existing service environment
map is serialized locally before mutation. That protected local backup can contain
raw service environment values and is non-shareable rollback material with bounded
retention. The published summary and stdout contain only key presence, digests,
and certificate metadata; they never emit service environment values, private
keys, tokens, or credentials.
#>

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
  [ValidateSet("Apply", "Rollback", "ReleaseLock", "Inspect")]
  [string]$Action = "Apply",
  [string]$RollbackEnvironmentBackup = "",
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[a-f0-9]{32}$')]
  [string]$TransactionId,
  [string]$ExpectedHostname = "SRB-AIDENETIMPC",
  [string]$ExpectedReleaseTag = "",
  [string]$ReleaseManifestBaseUrl = "",
  [string]$ReleaseAssetBaseUrl = "",
  [string]$ExpectedReleaseManifestSha256 = "",
  [string]$ExpectedBinarySha256 = "",
  [string]$ExpectedArtifactHostDigest = "",
  [string]$ExpectedArtifactHostImageRef = "",
  [string]$ExpectedAttestationPublicKeySha256 = "7149268fca56d9adb1097a8148b620d99949f5fa440f31406804112ace04d467",
  [string]$ExpectedDeviceCertIssuer = "CN=platform-test endpoint device CA",
  [string]$ExpectedPermitKeyId = "rb-test-denetim-device-key-20260627-01",
  [string]$ExpectedPermitPublicKeyB64 = "",
  [string]$ExpectedPermitPublicKeyB64Sha256 = "0a92abcd8f84619fb8f14f530beb94cbdc4e0981c9eb14a4756bdc85175a1110",
  [string]$ExpectedBrokerAddr = "remote-bridge-mtls.testai.acik.com:443",
  [string]$ExpectedTlsServerName = "remote-bridge-mtls.testai.acik.com",
  [string]$ExpectedViewOnlyMaskRectBps = "",
  [ValidatePattern('^[A-Za-z0-9._-]+$')]
  [string]$ServiceName = "EndpointAgent",
  [string]$BinaryPath = "C:\Program Files\EndpointAgent\endpoint-agent.exe",
  [string]$DeviceCertPath = "$env:ProgramData\EndpointAgent\tpm-client-cert.pem",
  [string]$EvidenceRoot = "$env:ProgramData\EndpointAgent\rollout-evidence",
  [string]$TransactionLockRoot = "$env:ProgramData\EndpointAgent\locks",
  [ValidateRange(1, 168)]
  [int]$RollbackRetentionHours = 24,
  [ValidateRange(5, 120)]
  [int]$DownloadTimeoutSeconds = 30,
  [int]$ServiceRestartTimeoutSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$requestedWhatIf = [bool]$WhatIfPreference
$WhatIfPreference = $false

function Read-ServiceEnvironmentMap {
  param([string]$Path)

  $map = [ordered]@{}
  $raw = @((Get-ItemProperty -Path $Path -Name Environment -ErrorAction Stop).Environment)
  foreach ($entry in $raw) {
    if ([string]::IsNullOrWhiteSpace([string]$entry)) {
      continue
    }
    $parts = $entry -split "=", 2
    if ($parts.Count -eq 2 -and -not [string]::IsNullOrWhiteSpace($parts[0])) {
      $map[$parts[0]] = $parts[1]
    }
  }
  return $map
}

function Assert-MapsEqual {
  param($Expected, $Actual)

  if ($Expected.Count -ne $Actual.Count) {
    throw "Restored service environment entry count differs from the pre-activation configuration"
  }
  foreach ($key in $Expected.Keys) {
    if (-not $Actual.Contains($key) -or [string]$Expected[$key] -cne [string]$Actual[$key]) {
      throw "Restored service environment differs from the pre-activation configuration at key: $key"
    }
  }
}

function Get-AsciiSha256 {
  param([string]$Value)

  $sha256 = [Security.Cryptography.SHA256]::Create()
  try {
    return [BitConverter]::ToString(
      $sha256.ComputeHash([Text.Encoding]::ASCII.GetBytes($Value))
    ).Replace("-", "").ToLowerInvariant()
  } finally {
    $sha256.Dispose()
  }
}

function Get-Utf8Sha256 {
  param([string]$Value)

  $sha256 = [Security.Cryptography.SHA256]::Create()
  try {
    return [BitConverter]::ToString(
      $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))
    ).Replace("-", "").ToLowerInvariant()
  } finally {
    $sha256.Dispose()
  }
}

function Assert-ViewOnlyMaskRectBps {
  param([string]$Value)

  if ([string]::IsNullOrWhiteSpace($Value) -or
      $Value -cnotmatch '^[0-9]{1,5},[0-9]{1,5},[0-9]{1,5},[0-9]{1,5}$') {
    throw "VIEW_ONLY mask policy must be canonical x,y,width,height basis points"
  }
  $parts = @($Value -split ',')
  $numbers = @(
    foreach ($part in $parts) {
      [int]::Parse($part, [Globalization.NumberStyles]::None, [Globalization.CultureInfo]::InvariantCulture)
    }
  )
  if (@($numbers | Where-Object { $_ -lt 0 -or $_ -gt 10000 }).Count -gt 0 -or
      $numbers[2] -le 0 -or $numbers[3] -le 0 -or
      ($numbers[0] + $numbers[2]) -gt 10000 -or
      ($numbers[1] + $numbers[3]) -gt 10000) {
    throw "VIEW_ONLY mask policy is empty or outside the primary monitor"
  }
}

function Get-ManifestAsset {
  param($Manifest, [string]$Name)

  # Do not use $matches here: PowerShell variables are case-insensitive, so it
  # aliases the automatic $Matches regex hashtable and is overwritten by
  # the SHA256 -cnotmatch check below on Windows PowerShell 5.1.
  $assetsFound = @($Manifest.assets | Where-Object { [string]$_.name -eq $Name })
  if ($assetsFound.Count -ne 1) {
    throw "Release manifest must contain exactly one $Name asset"
  }
  $sha256 = ([string]$assetsFound[0].sha256).ToLowerInvariant()
  if ($sha256 -cnotmatch '^[a-f0-9]{64}$') {
    throw "Release manifest asset $Name has an invalid SHA256"
  }
  return $assetsFound[0]
}

function Get-HttpsReleaseAsset {
  param([string]$BaseUrl, [string]$Name, [string]$Destination, [int]$TimeoutSeconds)

  if ($BaseUrl -notmatch '^https://[A-Za-z0-9.-]+(?::443)?(?:/|$)') {
    throw "Release asset base URL must use HTTPS"
  }
  $uri = $BaseUrl.TrimEnd('/') + '/' + $Name
  Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $Destination -TimeoutSec $TimeoutSeconds
  if (-not (Test-Path -LiteralPath $Destination)) {
    throw "Release asset download did not produce $Name"
  }
}

function Assert-JsonBooleanProperty {
  param($Object, [string]$Name, [bool]$Expected)

  if ($null -eq $Object) {
    throw "JSON object is absent while validating boolean property $Name"
  }
  $property = $Object.PSObject.Properties[$Name]
  if ($null -eq $property -or $property.Value -isnot [bool] -or $property.Value -ne $Expected) {
    throw "JSON boolean property $Name is missing, has the wrong type, or differs from the expected value"
  }
}

function Get-ServiceEnvironmentMapSha256 {
  param($Map)

  $rows = @(
    foreach ($key in @($Map.Keys | Sort-Object)) {
      [ordered]@{ key = [string]$key; value = [string]$Map[$key] }
    }
  )
  $canonicalJson = ConvertTo-Json -InputObject $rows -Compress
  return Get-Utf8Sha256 -Value $canonicalJson
}

function Get-ServiceEnvironmentSubsetSha256 {
  param($Map, [string[]]$Keys)

  $rows = @(
    foreach ($key in @($Keys | Sort-Object -Unique)) {
      $present = $Map.Contains($key)
      [ordered]@{
        key = [string]$key
        present = [bool]$present
        value = if ($present) { [string]$Map[$key] } else { "" }
      }
    }
  )
  return Get-Utf8Sha256 -Value (ConvertTo-Json -InputObject $rows -Compress)
}

function New-ManagedEnvironmentRestorationMap {
  param($CurrentMap, $BackupMap, [string[]]$ManagedKeys)

  $result = [ordered]@{}
  foreach ($key in $CurrentMap.Keys) {
    $result[$key] = $CurrentMap[$key]
  }
  foreach ($key in @($ManagedKeys | Sort-Object -Unique)) {
    if ($BackupMap.Contains($key)) {
      $result[$key] = $BackupMap[$key]
    } else {
      [void]$result.Remove($key)
    }
  }
  return $result
}

function Write-AtomicJsonFile {
  param($Value, [string]$Path, [int]$Depth)

  $tempPath = "$Path.$([Guid]::NewGuid().ToString('N')).tmp"
  $replaceBackupPath = "$Path.$([Guid]::NewGuid().ToString('N')).replace-backup.tmp"
  try {
    ConvertTo-Json -InputObject $Value -Depth $Depth | Set-Content -LiteralPath $tempPath -Encoding UTF8
    if (-not (Test-Path -LiteralPath $tempPath -PathType Leaf)) {
      throw "Atomic JSON temporary file was not created"
    }
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
      [IO.File]::Replace($tempPath, $Path, $replaceBackupPath, $true)
    } else {
      [IO.File]::Move($tempPath, $Path)
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
      throw "Atomic JSON destination could not be verified"
    }
  } finally {
    Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $replaceBackupPath -Force -ErrorAction SilentlyContinue
  }
}

function Write-ServiceEnvironmentBackup {
  param($Map, [string]$Path)

  $rows = @(
    foreach ($key in @($Map.Keys | Sort-Object)) {
      [ordered]@{ key = [string]$key; value = [string]$Map[$key] }
    }
  )
  Write-AtomicJsonFile -Value $rows -Path $Path -Depth 3
}

function Read-ServiceEnvironmentBackup {
  param([string]$Path)

  # Windows PowerShell 5.1 can preserve ConvertFrom-Json's top-level array as
  # one nested pipeline object when the conversion runs directly inside @().
  # Assign first so @($parsed) consistently enumerates the backup rows.
  $parsed = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json
  $rows = @($parsed)
  $map = [ordered]@{}
  foreach ($row in $rows) {
    # PSMemberInfoCollection's string indexer is not reliable on Windows
    # PowerShell 5.1; inspect the property-name collection instead.
    if ($null -eq $row -or -not ($row.PSObject.Properties.Name -contains "key") -or
        -not ($row.PSObject.Properties.Name -contains "value")) {
      throw "Service environment backup contains an invalid row"
    }
    $key = [string]$row.key
    if ([string]::IsNullOrWhiteSpace($key) -or $key.Contains("=") -or $map.Contains($key)) {
      throw "Service environment backup contains an invalid or duplicate key"
    }
    $map[$key] = [string]$row.value
  }
  return $map
}

function Remove-TransactionLock {
  param([string]$LockDirectory, [string]$OwnerFile, [string]$BoundTransactionId)

  if (-not (Test-Path -LiteralPath $LockDirectory)) {
    return
  }
  if (-not (Test-Path -LiteralPath $OwnerFile -PathType Leaf)) {
    throw "Transaction lock owner file is absent"
  }
  $owner = (Get-Content -LiteralPath $OwnerFile -Raw).Trim()
  if ($owner -ne $BoundTransactionId) {
    throw "Transaction lock is owned by another migration"
  }
  Remove-Item -LiteralPath $LockDirectory -Recurse -Force
  if (Test-Path -LiteralPath $LockDirectory) {
    throw "Transaction lock removal could not be verified"
  }
}

function Enter-MigrationOperationMutex {
  $mutex = [Threading.Mutex]::new($false, "Global\EndpointAgent-F22-ViewOnly-Migration")
  try {
    if (-not $mutex.WaitOne([TimeSpan]::FromSeconds(30))) {
      $mutex.Dispose()
      throw "Timed out waiting for the endpoint migration operation mutex"
    }
  } catch [Threading.AbandonedMutexException] {
    # The previous process terminated while holding the mutex; this process now owns it.
  }
  return $mutex
}

function Exit-MigrationOperationMutex {
  param([Threading.Mutex]$Mutex)

  if ($null -eq $Mutex) {
    return
  }
  try {
    $Mutex.ReleaseMutex()
  } finally {
    $Mutex.Dispose()
  }
}

function Resolve-TransactionBoundRollback {
  param(
    [string]$EvidenceRootPath,
    [string]$EnvironmentBackupPath,
    [string]$BoundServiceName,
    [string]$BoundTransactionId
  )

  $evidenceRootFull = [IO.Path]::GetFullPath($EvidenceRootPath).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
  $environmentBackupFull = [IO.Path]::GetFullPath($EnvironmentBackupPath)
  $expectedRollbackDirectory = [IO.Path]::GetFullPath(
    (Join-Path $EvidenceRootPath "denetim-device-key-view-only-$BoundTransactionId")
  )
  if (-not $environmentBackupFull.StartsWith($evidenceRootFull, [StringComparison]::OrdinalIgnoreCase) -or
      -not [string]::Equals([IO.Path]::GetDirectoryName($environmentBackupFull), $expectedRollbackDirectory, [StringComparison]::OrdinalIgnoreCase) -or
      [IO.Path]::GetFileName($environmentBackupFull) -ne "$BoundServiceName-environment-before.json") {
    throw "Rollback environment backup must match the requested transaction under EvidenceRoot"
  }
  if (-not (Test-Path -LiteralPath $environmentBackupFull -PathType Leaf)) {
    throw "Rollback environment backup is absent"
  }

  $rollbackSummaryPath = Join-Path $expectedRollbackDirectory "summary.json"
  if (-not (Test-Path -LiteralPath $rollbackSummaryPath -PathType Leaf)) {
    throw "Rollback summary is absent"
  }
  $rollbackSummary = Get-Content -LiteralPath $rollbackSummaryPath -Raw | ConvertFrom-Json
  if ([string]$rollbackSummary.schema -ne "faz22.6.denetimepc-device-key-view-only-activation.v4") {
    throw "Rollback summary schema is not accepted"
  }
  if ([string]$rollbackSummary.transactionId -ne $BoundTransactionId) {
    throw "Rollback summary transaction ID does not match the requested transaction"
  }
  $expectedEnvironmentSha256 = [string]$rollbackSummary.rollback.preMutationServiceEnvironmentSha256
  if ($expectedEnvironmentSha256 -cnotmatch '^[a-f0-9]{64}$') {
    throw "Rollback summary does not contain a canonical pre-mutation service environment SHA256"
  }
  $expectedEnvironmentSha256 = $expectedEnvironmentSha256.ToLowerInvariant()
  $expectedEnvironmentBackupSha256 = [string]$rollbackSummary.rollback.environmentBackupSha256
  if ($expectedEnvironmentBackupSha256 -cnotmatch '^[a-f0-9]{64}$') {
    throw "Rollback summary does not contain a canonical environment backup SHA256"
  }
  $expectedEnvironmentBackupSha256 = $expectedEnvironmentBackupSha256.ToLowerInvariant()
  $actualEnvironmentBackupSha256 = (Get-FileHash -LiteralPath $environmentBackupFull -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actualEnvironmentBackupSha256 -ne $expectedEnvironmentBackupSha256) {
    throw "Rollback environment backup SHA256 differs from the protected pre-mutation summary"
  }
  $expectedManagedPostMutationSha256 = [string]$rollbackSummary.rollback.managedPostMutationSha256
  if ($expectedManagedPostMutationSha256 -cnotmatch '^[a-f0-9]{64}$') {
    throw "Rollback summary does not contain a canonical managed post-mutation SHA256"
  }
  $expectedManagedPostMutationSha256 = $expectedManagedPostMutationSha256.ToLowerInvariant()
  $expectedManagedPreMutationSha256 = [string]$rollbackSummary.rollback.managedPreMutationSha256
  if ($expectedManagedPreMutationSha256 -cnotmatch '^[a-f0-9]{64}$') {
    throw "Rollback summary does not contain a canonical managed pre-mutation SHA256"
  }
  $expectedManagedPreMutationSha256 = $expectedManagedPreMutationSha256.ToLowerInvariant()

  return [pscustomobject]@{
    environmentBackup = $environmentBackupFull
    summary = $rollbackSummaryPath
    environmentBackupSha256 = $actualEnvironmentBackupSha256
    expectedServiceEnvironmentSha256 = $expectedEnvironmentSha256
    expectedManagedPreMutationSha256 = $expectedManagedPreMutationSha256
    expectedManagedPostMutationSha256 = $expectedManagedPostMutationSha256
  }
}

function Wait-ServiceStatus {
  param([string]$Name, [string]$ExpectedStatus, [int]$TimeoutSeconds)

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    $currentService = Get-Service -Name $Name -ErrorAction Stop
    if ($currentService.Status.ToString() -eq $ExpectedStatus) {
      return $currentService
    }
    Start-Sleep -Seconds 2
  } while ((Get-Date) -lt $deadline)

  throw "$Name did not reach $ExpectedStatus within $TimeoutSeconds seconds"
}

function Stop-ServiceAndWait {
  param([string]$Name, [int]$TimeoutSeconds)

  $currentService = Get-Service -Name $Name -ErrorAction Stop
  if ($currentService.Status -ne "Stopped") {
    Stop-Service -Name $Name -Force -ErrorAction Stop
  }
  return Wait-ServiceStatus -Name $Name -ExpectedStatus "Stopped" -TimeoutSeconds $TimeoutSeconds
}

function Start-ServiceAndWait {
  param([string]$Name, [int]$TimeoutSeconds)

  $currentService = Get-Service -Name $Name -ErrorAction Stop
  if ($currentService.Status -ne "Running") {
    Start-Service -Name $Name -ErrorAction Stop
  }
  return Wait-ServiceStatus -Name $Name -ExpectedStatus "Running" -TimeoutSeconds $TimeoutSeconds
}

function Write-ServiceEnvironmentMap {
  param([string]$Path, $Map)

  $entries = @()
  foreach ($key in @($Map.Keys | Sort-Object)) {
    $entries += "$key=$([string]$Map[$key])"
  }
  Set-ItemProperty -Path $Path -Name Environment -Type MultiString -Value $entries
}

function Register-RollbackCleanupTask {
  param(
    [string]$BackupDirectory,
    [string]$EvidenceRootPath,
    [string]$TransactionLockDirectory,
    [string]$TransactionLockOwnerFile,
    [string]$BoundTransactionId,
    [string]$BoundServiceName,
    [string]$ExpectedPreMutationServiceEnvironmentSha256,
    [string[]]$ManagedEnvironmentKeys,
    [string]$DeleteAfterUtc
  )

  $rootFull = [IO.Path]::GetFullPath($EvidenceRootPath).TrimEnd('\') + '\'
  $targetFull = [IO.Path]::GetFullPath($BackupDirectory)
  $expectedLeaf = "denetim-device-key-view-only-$BoundTransactionId"
  if (-not $targetFull.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase) -or
      [IO.Path]::GetFileName($targetFull) -ne $expectedLeaf) {
    throw "Rollback cleanup target is outside the transaction-bound evidence root"
  }

  $taskName = "EndpointAgent-F22-RollbackCleanup-$BoundTransactionId"
  $escapedRoot = $rootFull.Replace("'", "''")
  $escapedTarget = $targetFull.Replace("'", "''")
  $escapedTaskName = $taskName.Replace("'", "''")
  $escapedLockDirectory = ([IO.Path]::GetFullPath($TransactionLockDirectory)).Replace("'", "''")
  $escapedLockOwnerFile = ([IO.Path]::GetFullPath($TransactionLockOwnerFile)).Replace("'", "''")
  $escapedServiceName = $BoundServiceName.Replace("'", "''")
  $escapedServiceKey = "HKLM:\SYSTEM\CurrentControlSet\Services\$BoundServiceName".Replace("'", "''")
  $escapedSummaryPath = (Join-Path $targetFull "summary.json").Replace("'", "''")
  if ($ExpectedPreMutationServiceEnvironmentSha256 -cnotmatch '^[a-f0-9]{64}$') {
    throw "Pre-mutation environment SHA256 is invalid for cleanup registration"
  }
  if ($ManagedEnvironmentKeys.Count -eq 0 -or @($ManagedEnvironmentKeys | Where-Object { $_ -cnotmatch '^[A-Z0-9_]+$' }).Count -gt 0) {
    throw "Managed environment key set is invalid for cleanup registration"
  }
  $managedKeyLiterals = @($ManagedEnvironmentKeys | Sort-Object -Unique | ForEach-Object { "'$_'" }) -join ', '
  $escapedEnvironmentBackup = (Join-Path $targetFull "$BoundServiceName-environment-before.json").Replace("'", "''")
  $cleanupCode = @"
`$ErrorActionPreference = 'Stop'
`$root = '$escapedRoot'
`$target = '$escapedTarget'
`$serviceKey = '$escapedServiceKey'
`$summaryPath = '$escapedSummaryPath'
`$environmentBackup = '$escapedEnvironmentBackup'
`$expectedPreMutationEnvironmentSha256 = '$ExpectedPreMutationServiceEnvironmentSha256'
`$markerKey = 'ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID'
`$managedEnvironmentKeys = @($managedKeyLiterals)
function Read-EnvironmentMap {
  `$map = [ordered]@{}
  foreach (`$entry in @((Get-ItemProperty -Path `$serviceKey -Name Environment -ErrorAction Stop).Environment)) {
    if ([string]::IsNullOrWhiteSpace([string]`$entry)) { continue }
    `$parts = `$entry -split '=', 2
    if (`$parts.Count -eq 2 -and -not [string]::IsNullOrWhiteSpace(`$parts[0])) { `$map[`$parts[0]] = `$parts[1] }
  }
  return `$map
}
function Get-EnvironmentSha256([object]`$map) {
  `$rows = @(foreach (`$key in @(`$map.Keys | Sort-Object)) { [ordered]@{ key = [string]`$key; value = [string]`$map[`$key] } })
  `$json = ConvertTo-Json -InputObject `$rows -Compress
  `$sha = [Security.Cryptography.SHA256]::Create()
  try { return [BitConverter]::ToString(`$sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(`$json))).Replace('-', '').ToLowerInvariant() } finally { `$sha.Dispose() }
}
function Get-EnvironmentSubsetSha256([object]`$map, [string[]]`$keys) {
  `$rows = @(foreach (`$key in @(`$keys | Sort-Object -Unique)) { `$present = `$map.Contains(`$key); [ordered]@{ key = [string]`$key; present = [bool]`$present; value = if (`$present) { [string]`$map[`$key] } else { '' } } })
  `$json = ConvertTo-Json -InputObject `$rows -Compress
  `$sha = [Security.Cryptography.SHA256]::Create()
  try { return [BitConverter]::ToString(`$sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(`$json))).Replace('-', '').ToLowerInvariant() } finally { `$sha.Dispose() }
}
function New-ScopedRestorationMap([object]`$currentMap, [object]`$backupMap, [string[]]`$keys) {
  `$result = [ordered]@{}
  foreach (`$key in `$currentMap.Keys) { `$result[`$key] = `$currentMap[`$key] }
  foreach (`$key in @(`$keys | Sort-Object -Unique)) { if (`$backupMap.Contains(`$key)) { `$result[`$key] = `$backupMap[`$key] } else { [void]`$result.Remove(`$key) } }
  return `$result
}
function Read-EnvironmentBackup {
  `$parsed = Get-Content -LiteralPath `$environmentBackup -Raw -ErrorAction Stop | ConvertFrom-Json
  `$rows = @(`$parsed)
  `$map = [ordered]@{}
  foreach (`$row in `$rows) {
    if (`$null -eq `$row -or -not (`$row.PSObject.Properties.Name -contains 'key') -or -not (`$row.PSObject.Properties.Name -contains 'value')) { throw 'environment backup row is invalid' }
    `$key = [string]`$row.key
    if ([string]::IsNullOrWhiteSpace(`$key) -or `$key.Contains('=') -or `$map.Contains(`$key)) { throw 'environment backup key is invalid or duplicated' }
    `$map[`$key] = [string]`$row.value
  }
  return `$map
}
function Write-EnvironmentMap([object]`$map) {
  `$entries = @(foreach (`$key in @(`$map.Keys | Sort-Object)) { "`$key=`$([string]`$map[`$key])" })
  Set-ItemProperty -Path `$serviceKey -Name Environment -Type MultiString -Value `$entries
}
`$operationMutex = [Threading.Mutex]::new(`$false, 'Global\EndpointAgent-F22-ViewOnly-Migration')
`$operationMutexHeld = `$false
`$serviceQuiesced = `$false
try {
  try {
    `$operationMutexHeld = `$operationMutex.WaitOne([TimeSpan]::FromSeconds(30))
  } catch [Threading.AbandonedMutexException] {
    `$operationMutexHeld = `$true
  }
  if (-not `$operationMutexHeld) { throw 'timed out waiting for the deadline rollback operation mutex' }
if (-not `$target.StartsWith(`$root, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName(`$target) -ne '$expectedLeaf') { throw 'cleanup target validation failed' }
`$current = Read-EnvironmentMap
`$currentSha256 = Get-EnvironmentSha256 `$current
`$markerPresent = `$current.Contains(`$markerKey)
`$marker = if (`$markerPresent) { [string]`$current[`$markerKey] } else { '' }
`$lockExists = Test-Path -LiteralPath '$escapedLockDirectory'
`$lockOwner = if (Test-Path -LiteralPath '$escapedLockOwnerFile' -PathType Leaf) { (Get-Content -LiteralPath '$escapedLockOwnerFile' -Raw).Trim() } else { '' }
`$ownsLock = `$lockExists -and `$lockOwner -eq '$BoundTransactionId'
if (`$lockExists -and [string]::IsNullOrWhiteSpace(`$lockOwner)) {
  if (`$currentSha256 -ne `$expectedPreMutationEnvironmentSha256 -or (Test-Path -LiteralPath `$summaryPath -PathType Leaf)) { throw 'ownerless transaction lock has active migration state' }
  Remove-Item -LiteralPath '$escapedLockDirectory' -Recurse -Force
  if (Test-Path -LiteralPath '$escapedLockDirectory') { throw 'ownerless transaction lock deletion could not be verified' }
  if (Test-Path -LiteralPath `$target) { Remove-Item -LiteralPath `$target -Recurse -Force }
  if (Test-Path -LiteralPath `$target) { throw 'incomplete transaction evidence deletion could not be verified' }
  Unregister-ScheduledTask -TaskName '$escapedTaskName' -Confirm:`$false -ErrorAction SilentlyContinue
  return
}
if (`$ownsLock) {
  if (-not (Test-Path -LiteralPath `$summaryPath -PathType Leaf)) {
    if (`$currentSha256 -ne `$expectedPreMutationEnvironmentSha256) { throw 'service environment changed without its rollback summary' }
    if (-not (Test-Path -LiteralPath '$escapedLockOwnerFile' -PathType Leaf) -or ((Get-Content -LiteralPath '$escapedLockOwnerFile' -Raw).Trim() -ne '$BoundTransactionId')) { throw 'transaction lock ownership changed before incomplete-transaction cleanup' }
    Remove-Item -LiteralPath '$escapedLockDirectory' -Recurse -Force
    if (Test-Path -LiteralPath '$escapedLockDirectory') { throw 'incomplete transaction lock deletion could not be verified' }
    if (Test-Path -LiteralPath `$target) { Remove-Item -LiteralPath `$target -Recurse -Force }
    if (Test-Path -LiteralPath `$target) { throw 'incomplete transaction evidence deletion could not be verified' }
    Unregister-ScheduledTask -TaskName '$escapedTaskName' -Confirm:`$false -ErrorAction SilentlyContinue
    return
  }
  `$summary = Get-Content -LiteralPath `$summaryPath -Raw | ConvertFrom-Json
  if ([string]`$summary.schema -ne 'faz22.6.denetimepc-device-key-view-only-activation.v4' -or [string]`$summary.transactionId -ne '$BoundTransactionId') { throw 'rollback summary transaction binding is invalid at cleanup deadline' }
  `$expectedEnvironmentSha256 = [string]`$summary.rollback.preMutationServiceEnvironmentSha256
  if (`$expectedEnvironmentSha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'pre-mutation environment digest is invalid at cleanup deadline' }
  `$expectedEnvironmentSha256 = `$expectedEnvironmentSha256.ToLowerInvariant()
  `$expectedManagedPreMutationSha256 = [string]`$summary.rollback.managedPreMutationSha256
  if (`$expectedManagedPreMutationSha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'managed pre-mutation environment digest is invalid at cleanup deadline' }
  `$expectedManagedPreMutationSha256 = `$expectedManagedPreMutationSha256.ToLowerInvariant()
  Stop-Service -Name '$escapedServiceName' -Force -ErrorAction Stop
  `$stopDeadline = (Get-Date).AddSeconds(60)
  do {
    `$service = Get-Service -Name '$escapedServiceName' -ErrorAction Stop
    if (`$service.Status -eq 'Stopped') { break }
    Start-Sleep -Seconds 2
  } while ((Get-Date) -lt `$stopDeadline)
  if (`$service.Status -ne 'Stopped') { throw 'service did not quiesce before automatic deadline rollback' }
  `$serviceQuiesced = `$true
  `$current = Read-EnvironmentMap
  `$currentSha256 = Get-EnvironmentSha256 `$current
  `$markerPresent = `$current.Contains(`$markerKey)
  `$marker = if (`$markerPresent) { [string]`$current[`$markerKey] } else { '' }
  `$expectedResultMap = `$current
  if (`$currentSha256 -ne `$expectedEnvironmentSha256) {
    `$currentManagedSha256 = Get-EnvironmentSubsetSha256 `$current `$managedEnvironmentKeys
    `$alreadyRestored = `$currentManagedSha256 -eq `$expectedManagedPreMutationSha256 -and `$marker -ne '$BoundTransactionId'
    if (`$marker -ne '$BoundTransactionId' -and -not `$alreadyRestored) { throw 'service environment is neither transaction-owned nor idempotently restored at cleanup deadline' }
    if (-not `$alreadyRestored) {
      `$expectedManagedPostMutationSha256 = [string]`$summary.rollback.managedPostMutationSha256
      if (`$expectedManagedPostMutationSha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'managed post-mutation environment digest is invalid at cleanup deadline' }
      `$expectedManagedPostMutationSha256 = `$expectedManagedPostMutationSha256.ToLowerInvariant()
      if (`$currentManagedSha256 -ne `$expectedManagedPostMutationSha256) { throw 'managed service environment changed before deadline rollback' }
      `$expectedEnvironmentBackupSha256 = [string]`$summary.rollback.environmentBackupSha256
      if (`$expectedEnvironmentBackupSha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'environment backup digest is invalid at cleanup deadline' }
      `$expectedEnvironmentBackupSha256 = `$expectedEnvironmentBackupSha256.ToLowerInvariant()
      if (-not (Test-Path -LiteralPath `$environmentBackup -PathType Leaf)) { throw 'environment backup is unavailable at cleanup deadline' }
      `$actualEnvironmentBackupSha256 = (Get-FileHash -LiteralPath `$environmentBackup -Algorithm SHA256).Hash.ToLowerInvariant()
      if (`$actualEnvironmentBackupSha256 -ne `$expectedEnvironmentBackupSha256) { throw 'environment backup digest mismatch at cleanup deadline' }
      `$backupMap = Read-EnvironmentBackup
      if ((Get-EnvironmentSha256 `$backupMap) -ne `$expectedEnvironmentSha256) { throw 'environment backup content differs from the pre-mutation digest' }
      `$pointOfUseCurrent = Read-EnvironmentMap
      if ((Get-EnvironmentSha256 `$pointOfUseCurrent) -ne `$currentSha256) { throw 'service environment changed at deadline rollback point of use' }
      `$scopedRestorationMap = New-ScopedRestorationMap `$pointOfUseCurrent `$backupMap `$managedEnvironmentKeys
      Write-EnvironmentMap `$scopedRestorationMap
      `$expectedResultMap = `$scopedRestorationMap
    }
  }
  Start-Service -Name '$escapedServiceName' -ErrorAction Stop
  `$deadline = (Get-Date).AddSeconds(60)
  do {
    `$service = Get-Service -Name '$escapedServiceName' -ErrorAction Stop
    if (`$service.Status -eq 'Running') { break }
    Start-Sleep -Seconds 2
  } while ((Get-Date) -lt `$deadline)
  if (`$service.Status -ne 'Running') { throw 'service did not recover after automatic deadline rollback' }
  `$serviceQuiesced = `$false
  `$restored = Read-EnvironmentMap
  if ((Get-EnvironmentSha256 `$restored) -ne (Get-EnvironmentSha256 `$expectedResultMap)) { throw 'automatic deadline rollback environment digest mismatch' }
  if (-not (Test-Path -LiteralPath '$escapedLockOwnerFile' -PathType Leaf) -or ((Get-Content -LiteralPath '$escapedLockOwnerFile' -Raw).Trim() -ne '$BoundTransactionId')) { throw 'transaction lock ownership changed during deadline rollback' }
  Remove-Item -LiteralPath '$escapedLockDirectory' -Recurse -Force
  if (Test-Path -LiteralPath '$escapedLockDirectory') { throw 'deadline transaction lock deletion could not be verified' }
}
if (Test-Path -LiteralPath `$target) { Remove-Item -LiteralPath `$target -Recurse -Force }
if (Test-Path -LiteralPath `$target) { throw 'sensitive rollback evidence deletion could not be verified' }
Unregister-ScheduledTask -TaskName '$escapedTaskName' -Confirm:`$false -ErrorAction SilentlyContinue
} finally {
  if (`$serviceQuiesced) {
    Start-Service -Name '$escapedServiceName' -ErrorAction SilentlyContinue
  }
  if (`$operationMutexHeld) { `$operationMutex.ReleaseMutex() }
  `$operationMutex.Dispose()
}
"@
  $encodedCleanup = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cleanupCode))
  $powershellExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
  $action = New-ScheduledTaskAction -Execute $powershellExe -Argument "-NoLogo -NoProfile -NonInteractive -EncodedCommand $encodedCleanup"
  $deleteAtLocal = ([DateTimeOffset]::Parse($DeleteAfterUtc)).LocalDateTime
  $trigger = New-ScheduledTaskTrigger -Once -At $deleteAtLocal
  # The task unregisters itself after verified success. A daily trigger keeps
  # retrying after transient or prolonged failures instead of silently leaving
  # sensitive rollback material after the finite RestartCount window.
  $retryAtLocal = $deleteAtLocal.AddDays(1)
  $retryTrigger = New-ScheduledTaskTrigger -Daily -At $retryAtLocal
  $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 15) -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($trigger, $retryTrigger) `
    -Principal $principal -Settings $settings -Force | Out-Null
  $registered = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
  if ($registered.TaskName -ne $taskName) {
    throw "Rollback cleanup task registration could not be verified"
  }

  return [ordered]@{
    taskName = $taskName
    deleteAfterUtc = $DeleteAfterUtc
    registered = $true
    runAs = "SYSTEM"
    startWhenAvailable = $true
    restartCount = 3
    retryDailyUntilVerifiedSuccess = $true
  }
}

function Assert-MapValue {
  param($Map, [string]$Key, [string]$Expected = "")

  if (-not $Map.Contains($Key) -or [string]::IsNullOrWhiteSpace([string]$Map[$Key])) {
    throw "Required service environment key is absent: $Key"
  }
  if (-not [string]::IsNullOrWhiteSpace($Expected) -and [string]$Map[$Key] -ne $Expected) {
    throw "Service environment key $Key differs from the canonical value"
  }
}

function Assert-MapValueOrAbsent {
  param($Map, [string]$Key, [string]$Expected)

  if (-not $Map.Contains($Key)) {
    return
  }
  if ([string]::IsNullOrWhiteSpace([string]$Map[$Key]) -or
      [string]$Map[$Key] -cne $Expected) {
    throw "Existing service environment key $Key differs from the canonical transaction value"
  }
}

function Read-PemLeafCertificate {
  param([string]$Path)

  $pem = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop
  $encoded = $pem `
    -replace "-----BEGIN CERTIFICATE-----", "" `
    -replace "-----END CERTIFICATE-----", "" `
    -replace "\s", ""
  if ([string]::IsNullOrWhiteSpace($encoded)) {
    throw "TPM device certificate PEM is empty"
  }
  return [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
    [Convert]::FromBase64String($encoded)
  )
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw "Administrator shell required"
}

if (-not [string]::Equals($env:COMPUTERNAME, $ExpectedHostname, [StringComparison]::OrdinalIgnoreCase)) {
  throw "Target hostname mismatch"
}

$serviceKey = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName"
if (-not (Test-Path -LiteralPath $serviceKey)) {
  throw "EndpointAgent service registry key is absent"
}
$transactionLockDirectory = Join-Path $TransactionLockRoot "faz22-view-only-migration.lock"
$transactionLockOwnerFile = Join-Path $transactionLockDirectory "owner.txt"
$managedEnvironmentKeys = @(
  "ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_TLS_SERVER_NAME",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_OPERATIONS_ENABLED",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_INSECURE_PLAINTEXT",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_PILOT_AUTO_CONSENT",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_DEVICE_KEY_SESSION_ENABLED",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ENABLED",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ATTENDED_CONSENT_ENABLED",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_MASK_RECT_BPS",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_KEY_ID",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_ATTESTATION_EVIDENCE_B64",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID"
)

if ($Action -eq "Inspect") {
  if (-not [string]::IsNullOrWhiteSpace($RollbackEnvironmentBackup)) {
    throw "RollbackEnvironmentBackup is not accepted with Action=Inspect"
  }
  $operationMutex = Enter-MigrationOperationMutex
  try {
    $inspectMap = Read-ServiceEnvironmentMap -Path $serviceKey
    $inspectMarkerState = if (-not $inspectMap.Contains("ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID")) {
      "absent"
    } elseif ([string]$inspectMap["ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID"] -eq $TransactionId) {
      "owned"
    } else {
      "foreign"
    }
    $inspectLockState = if (-not (Test-Path -LiteralPath $transactionLockDirectory)) {
      "absent"
    } elseif ((Test-Path -LiteralPath $transactionLockOwnerFile -PathType Leaf) -and
        ((Get-Content -LiteralPath $transactionLockOwnerFile -Raw).Trim() -eq $TransactionId)) {
      "owned"
    } else {
      "foreign"
    }
    $inspectDirectory = Join-Path $EvidenceRoot "denetim-device-key-view-only-$TransactionId"
    $inspectBackup = Join-Path $inspectDirectory "$ServiceName-environment-before.json"
    $inspectSummary = Join-Path $inspectDirectory "summary.json"
    $inspectBackupPresent = Test-Path -LiteralPath $inspectBackup -PathType Leaf
    $inspectSummaryState = "absent"
    if (Test-Path -LiteralPath $inspectSummary -PathType Leaf) {
      try {
        $inspectSummaryObject = Get-Content -LiteralPath $inspectSummary -Raw | ConvertFrom-Json
        if ([string]$inspectSummaryObject.schema -ne "faz22.6.denetimepc-device-key-view-only-activation.v4" -or
            [string]$inspectSummaryObject.transactionId -ne $TransactionId) {
          $inspectSummaryState = "invalid"
        } else {
          $inspectSummaryState = [string]$inspectSummaryObject.status
        }
      } catch {
        $inspectSummaryState = "invalid"
      }
    }
    Write-Host "status=transaction-state-observed"
    Write-Host "lockState=$inspectLockState"
    Write-Host "markerState=$inspectMarkerState"
    Write-Host "backupPresent=$($inspectBackupPresent.ToString().ToLowerInvariant())"
    Write-Host "summaryState=$inspectSummaryState"
  } finally {
    Exit-MigrationOperationMutex -Mutex $operationMutex
  }
  return
}

if ($Action -eq "ReleaseLock") {
  if (-not [string]::IsNullOrWhiteSpace($RollbackEnvironmentBackup)) {
    throw "RollbackEnvironmentBackup is not accepted with Action=ReleaseLock"
  }
  $WhatIfPreference = $requestedWhatIf
  if (-not $PSCmdlet.ShouldProcess($ExpectedHostname, "release the transaction-bound VIEW_ONLY migration lock")) {
    return
  }
  $WhatIfPreference = $false
  $operationMutex = Enter-MigrationOperationMutex
  try {
    $lockExists = Test-Path -LiteralPath $transactionLockDirectory
    if ($lockExists -and
        (-not (Test-Path -LiteralPath $transactionLockOwnerFile -PathType Leaf) -or
        ((Get-Content -LiteralPath $transactionLockOwnerFile -Raw).Trim() -ne $TransactionId))) {
      throw "Transaction lock is not owned by the requested migration"
    }
    $releaseMap = Read-ServiceEnvironmentMap -Path $serviceKey
    if ($releaseMap.Contains("ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID")) {
      Assert-MapValue -Map $releaseMap `
        -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID" `
        -Expected $TransactionId
      $releaseSummaryPath = Join-Path $EvidenceRoot "denetim-device-key-view-only-$TransactionId\summary.json"
      if (-not (Test-Path -LiteralPath $releaseSummaryPath -PathType Leaf)) {
        throw "Committed activation summary is absent before lock release"
      }
      $releaseSummary = Get-Content -LiteralPath $releaseSummaryPath -Raw | ConvertFrom-Json
      if ([string]$releaseSummary.schema -ne "faz22.6.denetimepc-device-key-view-only-activation.v4" -or
          [string]$releaseSummary.status -ne "configuration-written-service-running-awaiting-broker-proof" -or
          [string]$releaseSummary.transactionId -ne $TransactionId) {
        throw "Activation summary is not a committed transaction-bound configuration result"
      }
      $expectedReleaseManagedSha256 = [string]$releaseSummary.rollback.managedPostMutationSha256
      if ($expectedReleaseManagedSha256 -cnotmatch '^[a-f0-9]{64}$' -or
          (Get-ServiceEnvironmentSubsetSha256 -Map $releaseMap -Keys $managedEnvironmentKeys) -ne $expectedReleaseManagedSha256) {
        throw "Current managed service environment differs from the committed activation summary"
      }
      $releaseService = Get-Service -Name $ServiceName -ErrorAction Stop
      if ($releaseService.Status -ne "Running") {
        throw "EndpointAgent is not Running at accepted lock release"
      }
      if ($lockExists) {
        Remove-TransactionLock `
          -LockDirectory $transactionLockDirectory `
          -OwnerFile $transactionLockOwnerFile `
          -BoundTransactionId $TransactionId
        $releaseStatus = "transaction-lock-released"
      } else {
        $releaseStatus = "transaction-lock-already-released"
      }
    } else {
      if ($lockExists) {
        throw "Transaction lock exists without its migration marker"
      }
      $releaseStatus = "transaction-lock-absent-no-active-marker"
    }
    Write-Host "status=$releaseStatus"
  } finally {
    Exit-MigrationOperationMutex -Mutex $operationMutex
  }
  return
}

if ($Action -eq "Rollback") {
  if ([string]::IsNullOrWhiteSpace($RollbackEnvironmentBackup)) {
    throw "RollbackEnvironmentBackup is required for Rollback"
  }

  $rollbackBinding = Resolve-TransactionBoundRollback `
    -EvidenceRootPath $EvidenceRoot `
    -EnvironmentBackupPath $RollbackEnvironmentBackup `
    -BoundServiceName $ServiceName `
    -BoundTransactionId $TransactionId
  $environmentBackupFull = $rollbackBinding.environmentBackup
  $expectedRestoredEnvironmentSha256 = $rollbackBinding.expectedServiceEnvironmentSha256
  $expectedManagedPreMutationSha256 = $rollbackBinding.expectedManagedPreMutationSha256
  $expectedManagedPostMutationSha256 = $rollbackBinding.expectedManagedPostMutationSha256

  $WhatIfPreference = $requestedWhatIf
  if (-not $PSCmdlet.ShouldProcess($ExpectedHostname, "restore the protected pre-activation EndpointAgent service environment")) {
    return
  }
  $WhatIfPreference = $false

  $operationMutex = Enter-MigrationOperationMutex
  $rollbackServiceQuiesced = $false
  try {
    $rollbackLockExists = Test-Path -LiteralPath $transactionLockDirectory
    $rollbackOwnsLock = $rollbackLockExists -and
      (Test-Path -LiteralPath $transactionLockOwnerFile -PathType Leaf) -and
      ((Get-Content -LiteralPath $transactionLockOwnerFile -Raw).Trim() -eq $TransactionId)
    if ($rollbackLockExists -and -not $rollbackOwnsLock) {
      throw "Transaction lock is owned by another migration before rollback"
    }
    $environmentBackupSha256ImmediatelyBeforeRestore = (Get-FileHash -LiteralPath $environmentBackupFull -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($environmentBackupSha256ImmediatelyBeforeRestore -ne $rollbackBinding.environmentBackupSha256) {
      throw "Rollback environment backup changed after validation and before restore"
    }
    $backupMap = Read-ServiceEnvironmentBackup -Path $environmentBackupFull
    if ((Get-ServiceEnvironmentMapSha256 -Map $backupMap) -ne $expectedRestoredEnvironmentSha256) {
      throw "Rollback environment backup content differs from the protected pre-mutation digest"
    }
    [void](Stop-ServiceAndWait -Name $ServiceName -TimeoutSeconds $ServiceRestartTimeoutSeconds)
    $rollbackServiceQuiesced = $true
    $beforeRollbackMap = Read-ServiceEnvironmentMap -Path $serviceKey
    $beforeRollbackEnvironmentSha256 = Get-ServiceEnvironmentMapSha256 -Map $beforeRollbackMap
    $beforeRollbackManagedSha256 = Get-ServiceEnvironmentSubsetSha256 -Map $beforeRollbackMap -Keys $managedEnvironmentKeys
    $expectedResultMap = $beforeRollbackMap
    if ($beforeRollbackEnvironmentSha256 -ne $expectedRestoredEnvironmentSha256) {
      $hasOwnedMarker = $beforeRollbackMap.Contains("ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID") -and
        [string]$beforeRollbackMap["ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID"] -eq $TransactionId
      $alreadyRestored = $beforeRollbackManagedSha256 -eq $expectedManagedPreMutationSha256 -and
        (-not $beforeRollbackMap.Contains("ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID") -or
        [string]$beforeRollbackMap["ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID"] -ne $TransactionId)
      if (-not $hasOwnedMarker -and -not $alreadyRestored) {
        throw "Managed service environment is neither transaction-owned nor an idempotently restored state"
      }
      if ($hasOwnedMarker -and -not $rollbackOwnsLock) {
        throw "Active transaction marker is not protected by its owned rollback lock"
      }
      if ($hasOwnedMarker -and $beforeRollbackManagedSha256 -ne $expectedManagedPostMutationSha256) {
        throw "Managed service environment changed after activation; refusing to overwrite concurrent updates"
      }
      $pointOfUseRollbackMap = Read-ServiceEnvironmentMap -Path $serviceKey
      Assert-MapsEqual -Expected $beforeRollbackMap -Actual $pointOfUseRollbackMap
      if (-not $alreadyRestored) {
        $restorationMap = New-ManagedEnvironmentRestorationMap `
          -CurrentMap $pointOfUseRollbackMap `
          -BackupMap $backupMap `
          -ManagedKeys $managedEnvironmentKeys
        Write-ServiceEnvironmentMap -Path $serviceKey -Map $restorationMap
        $expectedResultMap = $restorationMap
      }
    }
  $rollbackService = Start-ServiceAndWait -Name $ServiceName -TimeoutSeconds $ServiceRestartTimeoutSeconds
  $rollbackServiceQuiesced = $false
  $restoredMap = Read-ServiceEnvironmentMap -Path $serviceKey
  $actualRestoredEnvironmentSha256 = Get-ServiceEnvironmentMapSha256 -Map $restoredMap
  Assert-MapsEqual -Expected $expectedResultMap -Actual $restoredMap
  if ($rollbackService.Status -ne "Running") {
    throw "EndpointAgent did not return to Running after rollback"
  }
  Remove-TransactionLock `
    -LockDirectory $transactionLockDirectory `
    -OwnerFile $transactionLockOwnerFile `
    -BoundTransactionId $TransactionId

    Write-Host "status=rollback-restored-service-running"
    Write-Host "restoredServiceEnvironmentSha256=$actualRestoredEnvironmentSha256"
  } finally {
    if ($rollbackServiceQuiesced) {
      [void](Start-ServiceAndWait -Name $ServiceName -TimeoutSeconds $ServiceRestartTimeoutSeconds)
    }
    Exit-MigrationOperationMutex -Mutex $operationMutex
  }
  return
}

if (-not [string]::IsNullOrWhiteSpace($RollbackEnvironmentBackup)) {
  throw "RollbackEnvironmentBackup is accepted only with Action=Rollback"
}
if ($Action -ne "Apply") {
  throw "Unsupported migration action reached the Apply-only release policy boundary"
}
$requiredReleasePolicy = [ordered]@{
  ExpectedReleaseTag = $ExpectedReleaseTag
  ReleaseManifestBaseUrl = $ReleaseManifestBaseUrl
  ReleaseAssetBaseUrl = $ReleaseAssetBaseUrl
  ExpectedReleaseManifestSha256 = $ExpectedReleaseManifestSha256
  ExpectedBinarySha256 = $ExpectedBinarySha256
  ExpectedArtifactHostDigest = $ExpectedArtifactHostDigest
  ExpectedArtifactHostImageRef = $ExpectedArtifactHostImageRef
}
foreach ($releasePolicyName in $requiredReleasePolicy.Keys) {
  if ([string]::IsNullOrWhiteSpace([string]$requiredReleasePolicy[$releasePolicyName])) {
    throw "Canonical release policy parameter is required for Action=Apply: $releasePolicyName"
  }
}
Assert-ViewOnlyMaskRectBps -Value $ExpectedViewOnlyMaskRectBps
if ([string]::IsNullOrWhiteSpace($ExpectedPermitPublicKeyB64) -or
    $ExpectedPermitPublicKeyB64 -cnotmatch '^[A-Za-z0-9+/]+={0,2}$') {
  throw "Canonical broker permit public key is required for Action=Apply"
}
$actualPermitPublicKeyB64Sha256 = Get-AsciiSha256 -Value $ExpectedPermitPublicKeyB64
if ($actualPermitPublicKeyB64Sha256 -ne $ExpectedPermitPublicKeyB64Sha256.ToLowerInvariant()) {
  throw "Injected broker permit public key differs from the pinned test trust anchor"
}
if (-not (Test-Path -LiteralPath $BinaryPath)) {
  throw "EndpointAgent binary is absent"
}
if (-not (Test-Path -LiteralPath $DeviceCertPath)) {
  throw "TPM device certificate is absent; run the approved TPM enrollment flow first"
}

$downloadRoot = Join-Path $env:TEMP ("endpoint-agent-attestation-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $downloadRoot | Out-Null
$manifestPath = Join-Path $downloadRoot "release-manifest.json"
$attestationPath = Join-Path $downloadRoot "remote-bridge-attestation-evidence.b64"
$attestationSummaryPath = Join-Path $downloadRoot "remote-bridge-attestation-evidence-summary.json"

try {
  Get-HttpsReleaseAsset -BaseUrl $ReleaseManifestBaseUrl -Name "release-manifest.json" -Destination $manifestPath -TimeoutSeconds $DownloadTimeoutSeconds
  $actualManifestSha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actualManifestSha256 -ne $ExpectedReleaseManifestSha256.ToLowerInvariant()) {
    throw "Release manifest SHA256 differs from the pinned immutable release"
  }

  $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
  if ([int]$manifest.schema_version -ne 1 -or [string]$manifest.release_tag -ne $ExpectedReleaseTag) {
    throw "Release manifest schema or tag differs from the pinned immutable release"
  }
  Assert-JsonBooleanProperty -Object $manifest -Name "publicly_trusted" -Expected $false
  Assert-JsonBooleanProperty -Object $manifest.remote_bridge_attestation -Name "private_key_included" -Expected $false
  if ([string]$manifest.release_class -ne "rollout-candidate") {
    throw "Release manifest is outside the approved internal rollout-candidate trust class"
  }
  if ([string]$manifest.artifact_host_digest -ne $ExpectedArtifactHostDigest -or
      [string]$manifest.artifact_host_image_ref -ne $ExpectedArtifactHostImageRef) {
    throw "Release manifest artifact-host provenance differs from the canonical policy"
  }

  $binaryAsset = Get-ManifestAsset -Manifest $manifest -Name "endpoint-agent.exe"
  $attestationAsset = Get-ManifestAsset -Manifest $manifest -Name "remote-bridge-attestation-evidence.b64"
  $attestationSummaryAsset = Get-ManifestAsset -Manifest $manifest -Name "remote-bridge-attestation-evidence-summary.json"
  if ([string]$binaryAsset.sha256 -ne $ExpectedBinarySha256.ToLowerInvariant() -or
      [string]$manifest.endpoint_agent_sha256 -ne $ExpectedBinarySha256.ToLowerInvariant()) {
    throw "Pinned EndpointAgent binary SHA256 is inconsistent with the release manifest"
  }

  Get-HttpsReleaseAsset -BaseUrl $ReleaseAssetBaseUrl -Name $attestationAsset.name -Destination $attestationPath -TimeoutSeconds $DownloadTimeoutSeconds
  Get-HttpsReleaseAsset -BaseUrl $ReleaseAssetBaseUrl -Name $attestationSummaryAsset.name -Destination $attestationSummaryPath -TimeoutSeconds $DownloadTimeoutSeconds
  $actualAttestationFileSha256 = (Get-FileHash -LiteralPath $attestationPath -Algorithm SHA256).Hash.ToLowerInvariant()
  $actualAttestationSummarySha256 = (Get-FileHash -LiteralPath $attestationSummaryPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actualAttestationFileSha256 -ne ([string]$attestationAsset.sha256).ToLowerInvariant() -or
      $actualAttestationFileSha256 -ne ([string]$manifest.remote_bridge_attestation.evidence_sha256).ToLowerInvariant()) {
    throw "Signed attestation evidence SHA256 differs from the release manifest"
  }
  if ($actualAttestationSummarySha256 -ne ([string]$attestationSummaryAsset.sha256).ToLowerInvariant() -or
      $actualAttestationSummarySha256 -ne ([string]$manifest.remote_bridge_attestation.summary_sha256).ToLowerInvariant()) {
    throw "Attestation summary SHA256 differs from the release manifest"
  }

  $attestationSummary = Get-Content -LiteralPath $attestationSummaryPath -Raw | ConvertFrom-Json
  Assert-JsonBooleanProperty -Object $attestationSummary -Name "signature_present" -Expected $true
  Assert-JsonBooleanProperty -Object $attestationSummary -Name "private_key_included" -Expected $false
  Assert-JsonBooleanProperty -Object $attestationSummary -Name "raw_private_key_logged" -Expected $false
  if ([int]$attestationSummary.schema_version -ne 1 -or
      [string]$attestationSummary.public_key_verification -ne "verified") {
    throw "Attestation summary does not satisfy the public signed-evidence contract"
  }
  if ([string]$attestationSummary.public_key_sha256 -ne $ExpectedAttestationPublicKeySha256.ToLowerInvariant()) {
    throw "Attestation summary public key differs from the pinned broker verifier key"
  }

  $attestationEvidenceB64 = (Get-Content -LiteralPath $attestationPath -Raw).Trim()
  $attestationEvidenceValueSha256 = Get-Utf8Sha256 -Value $attestationEvidenceB64
  try {
    $decodedAttestation = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($attestationEvidenceB64))
  } catch {
    throw "Signed attestation evidence is not canonical Base64"
  }
  $attestationFields = @($decodedAttestation -split '\|', 4)
  if ($attestationFields.Count -ne 4 -or [string]::IsNullOrWhiteSpace($attestationFields[3])) {
    throw "Signed attestation evidence does not contain the four-field provenance tuple"
  }
  if ($attestationFields[0] -ne $ExpectedBinarySha256.ToLowerInvariant() -or
      $attestationFields[0] -ne [string]$attestationSummary.binary_digest -or
      $attestationFields[1] -ne [string]$manifest.remote_bridge_attestation.builder_id -or
      $attestationFields[1] -ne [string]$attestationSummary.builder_id -or
      $attestationFields[2] -ne [string]$manifest.remote_bridge_attestation.policy_hash -or
      $attestationFields[2] -ne [string]$attestationSummary.policy_hash) {
    throw "Signed attestation provenance fields are inconsistent with the release manifest"
  }
} finally {
  Remove-Item -LiteralPath $downloadRoot -Recurse -Force -ErrorAction SilentlyContinue
}

$actualBinarySha256 = (Get-FileHash -LiteralPath $BinaryPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualBinarySha256 -ne $ExpectedBinarySha256.ToLowerInvariant()) {
  throw "EndpointAgent binary SHA256 differs from the approved release"
}

$escapedServiceName = $ServiceName.Replace("'", "''")
$serviceConfig = Get-CimInstance -ClassName Win32_Service -Filter "Name='$escapedServiceName'" -ErrorAction Stop
$serviceImagePath = [Environment]::ExpandEnvironmentVariables([string]$serviceConfig.PathName).Trim()
$quotedBinaryPath = '"' + $BinaryPath + '"'
$servicePathMatches = [string]::Equals($serviceImagePath, $BinaryPath, [StringComparison]::OrdinalIgnoreCase) -or
  [string]::Equals($serviceImagePath, $quotedBinaryPath, [StringComparison]::OrdinalIgnoreCase) -or
  $serviceImagePath.StartsWith("$quotedBinaryPath ", [StringComparison]::OrdinalIgnoreCase)
if (-not $servicePathMatches) {
  throw "EndpointAgent service ImagePath is not bound to the approved binary path"
}

$deviceCertFileSha256 = (Get-FileHash -LiteralPath $DeviceCertPath -Algorithm SHA256).Hash.ToLowerInvariant()
$deviceCert = Read-PemLeafCertificate -Path $DeviceCertPath
$nowUtc = (Get-Date).ToUniversalTime()
if ($deviceCert.Issuer -ne $ExpectedDeviceCertIssuer) {
  throw "TPM device certificate issuer differs from the broker client CA"
}
if (-not [string]::Equals($deviceCert.Subject, "CN=$ExpectedHostname", [StringComparison]::OrdinalIgnoreCase)) {
  throw "TPM device certificate subject is not bound to the expected hostname"
}
if ($deviceCert.NotBefore.ToUniversalTime() -gt $nowUtc -or $deviceCert.NotAfter.ToUniversalTime() -le $nowUtc) {
  throw "TPM device certificate is outside its validity window; re-enroll before activation"
}
if ($deviceCert.PublicKey.Oid.Value -ne "1.2.840.10045.2.1") {
  throw "TPM device certificate public key is not ECC"
}

$tpm = Get-Tpm -ErrorAction Stop
if (-not $tpm.TpmPresent -or -not $tpm.TpmReady) {
  throw "TPM is not present and ready"
}

$service = Get-Service -Name $ServiceName -ErrorAction Stop
if ($service.StartType -eq "Disabled") {
  throw "EndpointAgent service is disabled"
}
if ($service.Status -ne "Running") {
  throw "EndpointAgent service must be Running before the bounded migration"
}

$current = Read-ServiceEnvironmentMap -Path $serviceKey
$preMutationServiceEnvironmentSha256 = Get-ServiceEnvironmentMapSha256 -Map $current
$managedPreMutationSha256 = Get-ServiceEnvironmentSubsetSha256 -Map $current -Keys $managedEnvironmentKeys
Assert-MapValueOrAbsent -Map $current -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED" -Expected "true"
Assert-MapValueOrAbsent -Map $current -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR" -Expected $ExpectedBrokerAddr
Assert-MapValueOrAbsent -Map $current -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_TLS_SERVER_NAME" -Expected $ExpectedTlsServerName
Assert-MapValueOrAbsent -Map $current -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_OPERATIONS_ENABLED" -Expected "true"
Assert-MapValueOrAbsent `
  -Map $current `
  -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64" `
  -Expected $ExpectedPermitPublicKeyB64
Assert-MapValue -Map $current -Key "ENDPOINT_AGENT_SELF_UPDATE_ENABLED" -Expected "true"
Assert-MapValue -Map $current -Key "ENDPOINT_AGENT_SELF_UPDATE_SIGNER_THUMBPRINTS"

if ($current.Contains("ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID") -and
    [string]$current["ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID"] -eq $TransactionId) {
  throw "Transaction ID has already been applied to this endpoint"
}

$patched = [ordered]@{}
foreach ($key in $current.Keys) {
  $patched[$key] = $current[$key]
}
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED"] = "true"
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR"] = $ExpectedBrokerAddr
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_TLS_SERVER_NAME"] = $ExpectedTlsServerName
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_OPERATIONS_ENABLED"] = "true"
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64"] = $ExpectedPermitPublicKeyB64
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_INSECURE_PLAINTEXT"] = "false"
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_PILOT_AUTO_CONSENT"] = "false"
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_DEVICE_KEY_SESSION_ENABLED"] = "true"
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ENABLED"] = "true"
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ATTENDED_CONSENT_ENABLED"] = "true"
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_MASK_RECT_BPS"] = $ExpectedViewOnlyMaskRectBps
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_KEY_ID"] = $ExpectedPermitKeyId
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_ATTESTATION_EVIDENCE_B64"] = $attestationEvidenceB64
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID"] = $TransactionId
$managedPostMutationSha256 = Get-ServiceEnvironmentSubsetSha256 -Map $patched -Keys $managedEnvironmentKeys

$WhatIfPreference = $requestedWhatIf
if (-not $PSCmdlet.ShouldProcess($ExpectedHostname, "activate TPM device-key and attended VIEW_ONLY service environment")) {
  return
}
$WhatIfPreference = $false

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$rollbackDeleteAfterUtc = (Get-Date).ToUniversalTime().AddHours($RollbackRetentionHours).ToString("o")
$backupDir = Join-Path $EvidenceRoot "denetim-device-key-view-only-$TransactionId"
$environmentBackup = Join-Path $backupDir "$ServiceName-environment-before.json"
$summaryPath = Join-Path $backupDir "summary.json"

$operationMutex = Enter-MigrationOperationMutex
try {
$cleanupTaskName = "EndpointAgent-F22-RollbackCleanup-$TransactionId"
if ($null -ne (Get-ScheduledTask -TaskName $cleanupTaskName -ErrorAction SilentlyContinue)) {
  throw "Transaction cleanup task already exists; refusing transaction replay"
}
$cleanupTaskInfo = Register-RollbackCleanupTask `
  -BackupDirectory $backupDir `
  -EvidenceRootPath $EvidenceRoot `
  -TransactionLockDirectory $transactionLockDirectory `
  -TransactionLockOwnerFile $transactionLockOwnerFile `
  -BoundTransactionId $TransactionId `
  -BoundServiceName $ServiceName `
  -ExpectedPreMutationServiceEnvironmentSha256 $preMutationServiceEnvironmentSha256 `
  -ManagedEnvironmentKeys $managedEnvironmentKeys `
  -DeleteAfterUtc $rollbackDeleteAfterUtc

New-Item -ItemType Directory -Force -Path $TransactionLockRoot | Out-Null
$transactionLockAcquiredByThisProcess = $false
try {
  New-Item -ItemType Directory -Path $transactionLockDirectory -ErrorAction Stop | Out-Null
  $transactionLockAcquiredByThisProcess = $true
  Set-Content -LiteralPath $transactionLockOwnerFile -Value $TransactionId -Encoding ASCII
  & icacls.exe $transactionLockDirectory /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "Could not restrict the transaction lock ACL"
  }
} catch {
  $lockError = $_.Exception.Message
  if ($transactionLockAcquiredByThisProcess) {
    Remove-Item -LiteralPath $transactionLockDirectory -Recurse -Force -ErrorAction SilentlyContinue
  }
  if ($transactionLockAcquiredByThisProcess -and (Test-Path -LiteralPath $transactionLockDirectory)) {
    throw "Could not remove the incomplete transaction lock; recovery task remains registered"
  }
  Unregister-ScheduledTask -TaskName $cleanupTaskName -Confirm:$false -ErrorAction SilentlyContinue
  throw "Could not acquire the exclusive endpoint migration lock: $lockError"
}

$backupDirectoryCreatedByThisProcess = $false
try {
  $lockedCurrent = Read-ServiceEnvironmentMap -Path $serviceKey
  $lockedCurrentSha256 = Get-ServiceEnvironmentMapSha256 -Map $lockedCurrent
  if ($lockedCurrentSha256 -ne $preMutationServiceEnvironmentSha256) {
    throw "Service environment changed between preflight and exclusive lock acquisition"
  }
  Assert-MapsEqual -Expected $current -Actual $lockedCurrent

  if (Test-Path -LiteralPath $backupDir) {
    throw "Transaction evidence directory already exists; refusing transaction replay"
  }
  New-Item -ItemType Directory -Path $backupDir -ErrorAction Stop | Out-Null
  $backupDirectoryCreatedByThisProcess = $true

  & icacls.exe $backupDir /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "Could not restrict the local activation evidence directory ACL"
  }

  $rollbackPreparation = [ordered]@{
    schema = "faz22.6.denetimepc-device-key-view-only-activation.v4"
    status = "rollback-prepared-before-mutation"
    transactionId = $TransactionId
    generatedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
    rollback = [ordered]@{
      localEnvironmentBackup = $environmentBackup
      preMutationServiceEnvironmentSha256 = $preMutationServiceEnvironmentSha256
      managedPreMutationSha256 = $managedPreMutationSha256
      managedPostMutationSha256 = $managedPostMutationSha256
      directoryAclRestrictedToSystemAndAdministrators = $true
      containsSensitiveServiceEnvironment = $true
      shareable = $false
      retentionHours = $RollbackRetentionHours
      deleteAfterUtc = $rollbackDeleteAfterUtc
      cleanupTask = $cleanupTaskInfo
      automaticRollbackPerformed = $false
    }
    boundary = "Pre-mutation rollback metadata only; not broker proof, VIEW_ONLY evidence, human consent, legal approval, or production readiness."
  }
  Write-AtomicJsonFile -Value $rollbackPreparation -Path $summaryPath -Depth 5
  if (-not (Test-Path -LiteralPath $summaryPath -PathType Leaf)) {
    throw "Could not create the pre-mutation rollback summary"
  }

  Write-ServiceEnvironmentBackup -Map $current -Path $environmentBackup
  $environmentBackupSha256 = (Get-FileHash -LiteralPath $environmentBackup -Algorithm SHA256).Hash.ToLowerInvariant()
  $rollbackPreparation.rollback["environmentBackupSha256"] = $environmentBackupSha256
  Write-AtomicJsonFile -Value $rollbackPreparation -Path $summaryPath -Depth 6
  $immediatePreMutationMap = Read-ServiceEnvironmentMap -Path $serviceKey
  $immediatePreMutationSha256 = Get-ServiceEnvironmentMapSha256 -Map $immediatePreMutationMap
  if ($immediatePreMutationSha256 -ne $preMutationServiceEnvironmentSha256) {
    throw "Service environment changed after rollback backup and before mutation"
  }
  Assert-MapsEqual -Expected $current -Actual $immediatePreMutationMap
  if ((Get-FileHash -LiteralPath $BinaryPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedBinarySha256.ToLowerInvariant()) {
    throw "EndpointAgent binary changed after preflight and before mutation"
  }
  $serviceConfigImmediatelyBeforeMutation = Get-CimInstance -ClassName Win32_Service -Filter "Name='$escapedServiceName'" -ErrorAction Stop
  $serviceImagePathImmediatelyBeforeMutation = [Environment]::ExpandEnvironmentVariables([string]$serviceConfigImmediatelyBeforeMutation.PathName).Trim()
  $servicePathMatchesImmediatelyBeforeMutation = [string]::Equals($serviceImagePathImmediatelyBeforeMutation, $BinaryPath, [StringComparison]::OrdinalIgnoreCase) -or
    [string]::Equals($serviceImagePathImmediatelyBeforeMutation, $quotedBinaryPath, [StringComparison]::OrdinalIgnoreCase) -or
    $serviceImagePathImmediatelyBeforeMutation.StartsWith("$quotedBinaryPath ", [StringComparison]::OrdinalIgnoreCase)
  if (-not $servicePathMatchesImmediatelyBeforeMutation) {
    throw "EndpointAgent service ImagePath changed after preflight and before mutation"
  }
  if ((Get-FileHash -LiteralPath $DeviceCertPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $deviceCertFileSha256) {
    throw "TPM device certificate changed after preflight and before mutation"
  }
} catch {
  $preMutationPreparationError = $_.Exception.Message
  if ($backupDirectoryCreatedByThisProcess) {
    Remove-Item -LiteralPath $backupDir -Recurse -Force -ErrorAction SilentlyContinue
  }
  Remove-TransactionLock `
    -LockDirectory $transactionLockDirectory `
    -OwnerFile $transactionLockOwnerFile `
    -BoundTransactionId $TransactionId
  if (($backupDirectoryCreatedByThisProcess -and (Test-Path -LiteralPath $backupDir)) -or
      (Test-Path -LiteralPath $transactionLockDirectory)) {
    throw "Pre-mutation preparation failed and sensitive rollback material cleanup could not be verified: $preMutationPreparationError"
  }
  Unregister-ScheduledTask -TaskName $cleanupTaskName -Confirm:$false -ErrorAction SilentlyContinue
  throw "Could not prepare hash-bound rollback material and enforced retention before mutation: $preMutationPreparationError"
}

$scriptPath = $MyInvocation.MyCommand.Path
$scriptSha256 = if (-not [string]::IsNullOrWhiteSpace($scriptPath) -and (Test-Path -LiteralPath $scriptPath)) {
  (Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant()
} else {
  $null
}

$mutationStarted = $false
$committed = $false
$rollbackPerformed = $false
$serviceQuiesced = $false
try {
  # The service is the only supported product writer for its Environment map.
  # Quiescing it closes that writer race; the global mutex coordinates every
  # migration/rollback path. A separate elevated administrator remains an OS
  # trust-boundary actor and is detected by the point-of-use equality checks.
  [void](Stop-ServiceAndWait -Name $ServiceName -TimeoutSeconds $ServiceRestartTimeoutSeconds)
  $serviceQuiesced = $true
  $pointOfUsePreMutationMap = Read-ServiceEnvironmentMap -Path $serviceKey
  Assert-MapsEqual -Expected $immediatePreMutationMap -Actual $pointOfUsePreMutationMap
  $mutationStarted = $true
  Write-ServiceEnvironmentMap -Path $serviceKey -Map $patched
  $serviceAfter = Start-ServiceAndWait -Name $ServiceName -TimeoutSeconds $ServiceRestartTimeoutSeconds
  $serviceQuiesced = $false
  if ((Get-FileHash -LiteralPath $BinaryPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedBinarySha256.ToLowerInvariant()) {
    throw "EndpointAgent binary changed across the activation restart"
  }
  $serviceConfigAfterRestart = Get-CimInstance -ClassName Win32_Service -Filter "Name='$escapedServiceName'" -ErrorAction Stop
  $serviceImagePathAfterRestart = [Environment]::ExpandEnvironmentVariables([string]$serviceConfigAfterRestart.PathName).Trim()
  $servicePathMatchesAfterRestart = [string]::Equals($serviceImagePathAfterRestart, $BinaryPath, [StringComparison]::OrdinalIgnoreCase) -or
    [string]::Equals($serviceImagePathAfterRestart, $quotedBinaryPath, [StringComparison]::OrdinalIgnoreCase) -or
    $serviceImagePathAfterRestart.StartsWith("$quotedBinaryPath ", [StringComparison]::OrdinalIgnoreCase)
  if (-not $servicePathMatchesAfterRestart) {
    throw "EndpointAgent service ImagePath changed across the activation restart"
  }
  if ((Get-FileHash -LiteralPath $DeviceCertPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $deviceCertFileSha256) {
    throw "TPM device certificate changed across the activation restart"
  }

  $after = Read-ServiceEnvironmentMap -Path $serviceKey
  foreach ($required in @(
    "ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED",
    "ENDPOINT_AGENT_REMOTE_BRIDGE_OPERATIONS_ENABLED",
    "ENDPOINT_AGENT_REMOTE_BRIDGE_DEVICE_KEY_SESSION_ENABLED",
    "ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ENABLED",
    "ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ATTENDED_CONSENT_ENABLED"
  )) {
    Assert-MapValue -Map $after -Key $required -Expected "true"
  }
  Assert-MapValue -Map $after -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR" -Expected $ExpectedBrokerAddr
  Assert-MapValue -Map $after -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_TLS_SERVER_NAME" -Expected $ExpectedTlsServerName
  Assert-MapValue `
    -Map $after `
    -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64" `
    -Expected $ExpectedPermitPublicKeyB64
  Assert-MapValue -Map $after -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_PILOT_AUTO_CONSENT" -Expected "false"
  Assert-MapValue -Map $after `
    -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_MASK_RECT_BPS" `
    -Expected $ExpectedViewOnlyMaskRectBps
  Assert-MapValue -Map $after -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_KEY_ID" -Expected $ExpectedPermitKeyId
  Assert-MapValue -Map $after -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_ATTESTATION_EVIDENCE_B64"
  Assert-MapValue -Map $after `
    -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID" `
    -Expected $TransactionId
  if ((Get-ServiceEnvironmentSubsetSha256 -Map $after -Keys $managedEnvironmentKeys) -ne $managedPostMutationSha256) {
    throw "Managed service environment differs from the transaction-bound activation patch after restart"
  }
  $actualServiceAttestationSha256 = Get-Utf8Sha256 -Value ([string]$after["ENDPOINT_AGENT_REMOTE_BRIDGE_ATTESTATION_EVIDENCE_B64"])
  if ($actualServiceAttestationSha256 -ne $attestationEvidenceValueSha256) {
    throw "EndpointAgent service attestation evidence differs from the verified release asset"
  }
  if ($serviceAfter.Status -ne "Running") {
    throw "EndpointAgent did not return to Running after activation"
  }
  $postMutationServiceEnvironmentSha256 = Get-ServiceEnvironmentMapSha256 -Map $after

  $result = [ordered]@{
    schema = "faz22.6.denetimepc-device-key-view-only-activation.v4"
    status = "configuration-written-service-running-awaiting-broker-proof"
    transactionId = $TransactionId
    generatedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
    hostname = $env:COMPUTERNAME
    operator = [ordered]@{
      name = $identity.Name
      sid = $identity.User.Value
    }
    activationScript = [ordered]@{
      path = $scriptPath
      sha256 = $scriptSha256
    }
    release = [ordered]@{
      tag = $ExpectedReleaseTag
      manifestSha256 = $actualManifestSha256
      manifestSourceCommit = [string]$manifest.source_commit
      binaryPath = $BinaryPath
      serviceImagePath = $serviceImagePath
      binarySha256 = $actualBinarySha256
      expectedBinarySha256 = $ExpectedBinarySha256.ToLowerInvariant()
    }
    attestation = [ordered]@{
      evidenceFileSha256 = $actualAttestationFileSha256
      evidenceValueSha256 = $attestationEvidenceValueSha256
      summarySha256 = $actualAttestationSummarySha256
      binaryDigest = $attestationFields[0]
      builderId = $attestationFields[1]
      policyHash = $attestationFields[2]
      producerSignatureFieldPresent = $true
      signatureCryptographicallyVerifiedByThisScript = $false
      signatureVerificationAuthority = "broker"
      expectedBrokerVerifierPublicKeySha256 = $ExpectedAttestationPublicKeySha256.ToLowerInvariant()
      releaseProducerReportedPublicKeyVerification = [string]$attestationSummary.public_key_verification
      rawEvidenceIncluded = $false
      privateKeyIncluded = $false
    }
    tpm = [ordered]@{
      present = [bool]$tpm.TpmPresent
      ready = [bool]$tpm.TpmReady
      manufacturerId = [string]$tpm.ManufacturerIdTxt
    }
    deviceCertificate = [ordered]@{
      path = $DeviceCertPath
      fileSha256 = $deviceCertFileSha256
      subject = $deviceCert.Subject
      issuer = $deviceCert.Issuer
      thumbprint = $deviceCert.Thumbprint
      notBeforeUtc = $deviceCert.NotBefore.ToUniversalTime().ToString("o")
      notAfterUtc = $deviceCert.NotAfter.ToUniversalTime().ToString("o")
      publicKeyAlgorithm = $deviceCert.PublicKey.Oid.FriendlyName
      privateKeyIncluded = $false
      privateKeyBindingVerifiedByThisScript = $false
    }
    service = [ordered]@{
      name = $ServiceName
      status = $serviceAfter.Status.ToString()
      startType = $serviceAfter.StartType.ToString()
      environmentSha256 = $postMutationServiceEnvironmentSha256
    }
    configuration = [ordered]@{
      brokerAddr = $ExpectedBrokerAddr
      tlsServerName = $ExpectedTlsServerName
      operationsEnabled = $true
      constrainedPtyPilotAutoConsentEnabled = $false
      deviceKeySessionEnabled = $true
      viewOnlyEnabled = $true
      attendedConsentEnabled = $true
      viewOnlyMaskRectBps = $ExpectedViewOnlyMaskRectBps
      viewOnlyMaskEnabled = [bool](-not [string]::IsNullOrWhiteSpace($ExpectedViewOnlyMaskRectBps))
      insecurePlaintext = $false
      permitKeyId = $ExpectedPermitKeyId
      permitPublicKeyB64Sha256 = $actualPermitPublicKeyB64Sha256
      permitTrustAnchorPinned = $true
      provenanceWithProducerSignatureFieldPresent = $true
      provenanceEvidenceSha256 = $attestationEvidenceValueSha256
      selfUpdatePolicyPreserved = [string]$after["ENDPOINT_AGENT_SELF_UPDATE_ENABLED"] -eq "true"
      migrationTransactionId = $TransactionId
    }
    rollback = [ordered]@{
      localEnvironmentBackup = $environmentBackup
      environmentBackupSha256 = $environmentBackupSha256
      preMutationServiceEnvironmentSha256 = $preMutationServiceEnvironmentSha256
      managedPreMutationSha256 = $managedPreMutationSha256
      managedPostMutationSha256 = $managedPostMutationSha256
      directoryAclRestrictedToSystemAndAdministrators = $true
      containsSensitiveServiceEnvironment = $true
      shareable = $false
      retentionHours = $RollbackRetentionHours
      deleteAfterUtc = $rollbackDeleteAfterUtc
      cleanupTask = $cleanupTaskInfo
      automaticRollbackPerformed = $false
    }
    evidenceHygiene = [ordered]@{
      publishedSummaryContainsRawServiceEnvironment = $false
      protectedLocalEnvironmentBackupMayContainRawServiceEnvironment = $true
      protectedLocalEnvironmentBackupShareable = $false
      publishedSummaryRawSecretIncluded = $false
      publishedSummaryTokenIncluded = $false
      publishedSummaryPrivateKeyIncluded = $false
    }
    boundary = [ordered]@{
      proves = @(
        "approved EndpointAgent binary digest and service executable path are installed",
        "on-disk TPM device certificate claims the expected hostname and broker client CA issuer",
        "TPM reports present and ready",
        "release-bound provenance with a non-empty producer signature field was written; broker verification is pending",
        "pinned test permit trust anchor and attended VIEW_ONLY configuration were written",
        "CONSTRAINED_PTY pilot auto-consent was disabled",
        "EndpointAgent returned to Running"
      )
      doesNotProve = @(
        "cryptographic signature verification by this script; the broker-side verifier remains authoritative",
        "broker acceptance of the signed provenance evidence until a fresh HELLO is observed",
        "TPM private-key binding or broker device-key challenge acceptance",
        "VIEW_ONLY session delivery or rendered frames",
        "human attended consent approval",
        "KVKK or legal approval",
        "production readiness",
        "permanent AnyDesk-like product runtime integration; this script is a bounded rollout and acceptance adapter only"
      )
      localSensitiveEvidence = "The environment backup may contain raw service environment values; it is ACL-restricted, non-shareable, and must be deleted after the recorded retention deadline."
    }
  }

  Write-AtomicJsonFile -Value $result -Path $summaryPath -Depth 8
  if (-not (Test-Path -LiteralPath $summaryPath)) {
    throw "Activation summary could not be written"
  }
  $committed = $true
} catch {
  $activationError = $_.Exception.Message
  if (-not $mutationStarted -and $serviceQuiesced) {
    try {
      [void](Start-ServiceAndWait -Name $ServiceName -TimeoutSeconds $ServiceRestartTimeoutSeconds)
      $serviceQuiesced = $false
    } catch {
      throw "Activation was not mutated, but EndpointAgent could not be restarted after quiescing: $activationError. Restart error: $($_.Exception.Message)"
    }
  }
  if ($mutationStarted -and -not $committed) {
    try {
      if (-not (Test-Path -LiteralPath $transactionLockOwnerFile -PathType Leaf) -or
          ((Get-Content -LiteralPath $transactionLockOwnerFile -Raw).Trim() -ne $TransactionId)) {
        throw "transaction lock ownership changed before automatic rollback"
      }
      $environmentBackupSha256ImmediatelyBeforeRestore = (Get-FileHash -LiteralPath $environmentBackup -Algorithm SHA256).Hash.ToLowerInvariant()
      if ($environmentBackupSha256ImmediatelyBeforeRestore -ne $environmentBackupSha256) {
        throw "environment backup changed after preparation and before automatic rollback restore"
      }
      $automaticRestorationMap = Read-ServiceEnvironmentBackup -Path $environmentBackup
      Assert-MapsEqual -Expected $current -Actual $automaticRestorationMap
      [void](Stop-ServiceAndWait -Name $ServiceName -TimeoutSeconds $ServiceRestartTimeoutSeconds)
      $serviceQuiesced = $true
      $beforeAutomaticRollback = Read-ServiceEnvironmentMap -Path $serviceKey
      $beforeAutomaticRollbackSha256 = Get-ServiceEnvironmentMapSha256 -Map $beforeAutomaticRollback
      $expectedAutomaticRollbackResult = $beforeAutomaticRollback
      if ($beforeAutomaticRollbackSha256 -ne $preMutationServiceEnvironmentSha256) {
        Assert-MapValue -Map $beforeAutomaticRollback `
          -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID" `
          -Expected $TransactionId
        if ((Get-ServiceEnvironmentSubsetSha256 -Map $beforeAutomaticRollback -Keys $managedEnvironmentKeys) -ne $managedPostMutationSha256) {
          throw "managed service environment changed before automatic rollback"
        }
        $pointOfUseAutomaticRollbackMap = Read-ServiceEnvironmentMap -Path $serviceKey
        Assert-MapsEqual -Expected $beforeAutomaticRollback -Actual $pointOfUseAutomaticRollbackMap
        $scopedAutomaticRestorationMap = New-ManagedEnvironmentRestorationMap `
          -CurrentMap $pointOfUseAutomaticRollbackMap `
          -BackupMap $automaticRestorationMap `
          -ManagedKeys $managedEnvironmentKeys
        Write-ServiceEnvironmentMap -Path $serviceKey -Map $scopedAutomaticRestorationMap
        $expectedAutomaticRollbackResult = $scopedAutomaticRestorationMap
      }
      [void](Start-ServiceAndWait -Name $ServiceName -TimeoutSeconds $ServiceRestartTimeoutSeconds)
      $serviceQuiesced = $false
      $restored = Read-ServiceEnvironmentMap -Path $serviceKey
      Assert-MapsEqual -Expected $expectedAutomaticRollbackResult -Actual $restored
      $restoredEnvironmentSha256 = Get-ServiceEnvironmentMapSha256 -Map $restored
      Remove-TransactionLock `
        -LockDirectory $transactionLockDirectory `
        -OwnerFile $transactionLockOwnerFile `
        -BoundTransactionId $TransactionId
      $rollbackPerformed = $true
    } catch {
      $rollbackError = $_.Exception.Message
      throw "Activation failed and verified automatic rollback failed. Activation error: $activationError. Rollback error: $rollbackError. Use the protected local environment backup: $environmentBackup"
    }
  }
  throw "Activation failed; the previous service configuration was restored and verified: $activationError"
}

Write-Host "status=configuration-written-service-running-awaiting-broker-proof"
Write-Host "evidence=$summaryPath"
} finally {
  Exit-MigrationOperationMutex -Mutex $operationMutex
}
