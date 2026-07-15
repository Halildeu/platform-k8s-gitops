[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$PackageDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-True {
  param([bool]$Condition, [string]$Message)
  if (-not $Condition) { throw ('assertion-failed:' + $Message) }
}

function Get-GeneratedFunctionText {
  param([string]$Path, [string]$Name)
  $tokens = $null
  $errors = $null
  $ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $Path,
    [ref]$tokens,
    [ref]$errors
  )
  if ($errors.Count -gt 0) { throw ('generated-powershell-parse-failed:' + $Path) }
  $matches = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq $Name
  }, $true))
  if ($matches.Count -ne 1) { throw ('generated-function-count:' + $Name + ':' + $matches.Count) }
  return $matches[0].Extent.Text
}

$collectorPath = Join-Path $PackageDirectory 'collect-audit-snapshot.ps1'
$installerPath = Join-Path $PackageDirectory 'install-audit-controls.ps1'
Invoke-Expression (Get-GeneratedFunctionText -Path $collectorPath -Name 'Test-RemoteAddressBroad')
Invoke-Expression (Get-GeneratedFunctionText -Path $collectorPath -Name 'Get-TranscriptFilesNoReparse')
Invoke-Expression (Get-GeneratedFunctionText -Path $collectorPath -Name 'Invoke-TranscriptRetention')
Invoke-Expression (Get-GeneratedFunctionText -Path $collectorPath -Name 'Invoke-TranscriptRetentionForPolicy')

Assert-True (Test-RemoteAddressBroad -RemoteAddresses @('Any')) 'Any must be broad'
Assert-True (Test-RemoteAddressBroad -RemoteAddresses @('LocalSubnet')) 'LocalSubnet must be broad'
Assert-True (Test-RemoteAddressBroad -RemoteAddresses @('Internet')) 'Internet must be broad'
Assert-True (Test-RemoteAddressBroad -RemoteAddresses @('10.0.0.0/8')) '10/8 must be broad'
Assert-True (Test-RemoteAddressBroad -RemoteAddresses @('0.0.0.0/1')) 'split /1 must be broad'
Assert-True (Test-RemoteAddressBroad -RemoteAddresses @('10.99.0.1-10.99.0.9')) 'range must be broad'
Assert-True (-not (Test-RemoteAddressBroad -RemoteAddresses @('10.99.0.1'))) 'single IPv4 must not be broad'
Assert-True (-not (Test-RemoteAddressBroad -RemoteAddresses @('10.99.0.1/32'))) '/32 must not be broad'

$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('faz24-i3-behavior-' + [guid]::NewGuid().ToString('N'))
try {
  $transcriptRoot = Join-Path $testRoot 'transcripts'
  New-Item -ItemType Directory -Path $transcriptRoot -Force | Out-Null
  $oldPath = Join-Path $transcriptRoot 'old.txt'
  $firstPath = Join-Path $transcriptRoot 'first.txt'
  $secondPath = Join-Path $transcriptRoot 'second.txt'
  [System.IO.File]::WriteAllBytes($oldPath, (New-Object byte[] 128))
  [System.IO.File]::WriteAllBytes($firstPath, (New-Object byte[] 716800))
  [System.IO.File]::WriteAllBytes($secondPath, (New-Object byte[] 716800))
  [System.IO.File]::SetLastWriteTimeUtc($oldPath, [datetime]::UtcNow.AddDays(-30))
  [System.IO.File]::SetLastWriteTimeUtc($firstPath, [datetime]::UtcNow.AddMinutes(-2))
  [System.IO.File]::SetLastWriteTimeUtc($secondPath, [datetime]::UtcNow.AddMinutes(-1))

  $retention = Invoke-TranscriptRetention -Path $transcriptRoot -RetentionDays 14 -MaximumBytes 1048576
  Assert-True $retention.retentionEnforced 'retention must be enforced'
  Assert-True ($retention.retentionDeleteCount -eq 1) 'one expired file must be removed'
  Assert-True ($retention.capacityDeleteCount -eq 1) 'one oldest capacity file must be removed'
  Assert-True ($retention.transcriptBytes -le 1048576) 'transcript bytes must be bounded'
  Assert-True (-not (Test-Path -LiteralPath $oldPath)) 'expired file must be absent'
  Assert-True (-not (Test-Path -LiteralPath $firstPath)) 'oldest capacity file must be absent'
  Assert-True (Test-Path -LiteralPath $secondPath) 'newest file must remain'

  $policyRoot = Join-Path $testRoot 'policy-transcripts'
  New-Item -ItemType Directory -Path $policyRoot -Force | Out-Null
  Set-Content -LiteralPath (Join-Path $policyRoot 'policy.txt') -Value 'policy-path-binding'
  $policyResult = Invoke-TranscriptRetentionForPolicy `
    -Policy ([pscustomobject]@{ OutputDirectory=$policyRoot }) `
    -Baseline ([pscustomobject]@{ transcriptRetentionDays=14; maximumTranscriptBytes=1048576 })
  Assert-True ($policyResult.outputPath -eq $policyRoot) 'policy output directory must bind retention path'
  Assert-True $policyResult.retention.retentionEnforced 'policy-bound retention must pass'

  if ([System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT) {
    $junctionTarget = Join-Path $testRoot 'junction-target'
    $junctionPath = Join-Path $policyRoot 'junction'
    New-Item -ItemType Directory -Path $junctionTarget -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $junctionTarget 'outside.txt') -Value 'must-not-be-traversed'
    New-Item -ItemType Junction -Path $junctionPath -Target $junctionTarget | Out-Null
    $junctionRejected = $false
    try {
      Invoke-TranscriptRetention -Path $policyRoot -RetentionDays 14 -MaximumBytes 1048576 | Out-Null
    } catch {
      $junctionRejected = $_.Exception.Message -match 'transcript-descendant-reparse-point-rejected'
    }
    Assert-True $junctionRejected 'descendant junction must be rejected before retention traversal'
    Assert-True (Test-Path -LiteralPath (Join-Path $junctionTarget 'outside.txt')) 'junction target file must remain'
    Remove-Item -LiteralPath $junctionPath -Force
  }

  Invoke-Expression (Get-GeneratedFunctionText -Path $installerPath -Name 'Get-StateFileEntries')
  Invoke-Expression (Get-GeneratedFunctionText -Path $installerPath -Name 'Restore-InitialState')

  $global:Faz24AuditArguments = @()
  $global:Faz24IcaclsArguments = @()
  function global:auditpol {
    $global:Faz24AuditArguments = @($args)
    $global:LASTEXITCODE = 0
  }
  function global:icacls {
    $global:Faz24IcaclsArguments = @($args)
    $global:LASTEXITCODE = 0
  }
  function global:Unregister-ScheduledTask { param($TaskName, [switch]$Confirm, $ErrorAction) }
  function global:Register-ScheduledTask { param($TaskName, $Xml, [switch]$Force) }
  function global:Set-RegistryState { param($Path, $Name, $State) }
  function global:Remove-NetFirewallRule { param($Name, $ErrorAction) }

  $Root = Join-Path $testRoot 'rollback-root'
  $TaskName = 'Faz24-I3-Audit-Snapshot'
  $StatePath = Join-Path $Root 'state\initial-rollback.json'
  $AclBackupPath = Join-Path $Root 'state\initial-acl.txt'
  $backupDirectory = Join-Path $Root 'state\backup-test'
  $collectorTarget = Join-Path $Root 'scripts\collect-audit-snapshot.ps1'
  $baselineTarget = Join-Path $Root 'config\baseline.json'
  $snapshotTarget = Join-Path $Root 'snapshot\audit-snapshot.json'
  New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
  New-Item -ItemType Directory -Path (Split-Path -Parent $collectorTarget) -Force | Out-Null
  New-Item -ItemType Directory -Path (Split-Path -Parent $baselineTarget) -Force | Out-Null
  New-Item -ItemType Directory -Path (Split-Path -Parent $snapshotTarget) -Force | Out-Null
  Set-Content -LiteralPath (Join-Path $backupDirectory 'collector.ps1') -Value 'original-collector'
  Set-Content -LiteralPath (Join-Path $backupDirectory 'snapshot.json') -Value 'original-snapshot'
  Set-Content -LiteralPath $collectorTarget -Value 'mutated-collector'
  Set-Content -LiteralPath $baselineTarget -Value 'created-baseline'
  Set-Content -LiteralPath $snapshotTarget -Value 'mutated-snapshot'
  Set-Content -LiteralPath $StatePath -Value '{}'
  Set-Content -LiteralPath $AclBackupPath -Value 'mock-acl'
  $emptyRegistryState = [pscustomobject]@{ exists=$false; value=$null; kind=$null }
  $state = [pscustomobject]@{
    rootExisted=$true
    stateDirectoryExisted=$true
    aclRestoreRoot=(Split-Path -Parent $Root)
    backupDirectory=$backupDirectory
    taskXml=$null
    registry=[pscustomobject]@{
      enableTranscripting=$emptyRegistryState
      enableInvocationHeader=$emptyRegistryState
      outputDirectory=$emptyRegistryState
      enableScriptBlockLogging=$emptyRegistryState
    }
    logonAuditPolicy=[pscustomobject]@{ successEnabled=$false; failureEnabled=$false }
    exactRules=@([pscustomobject]@{ name='FAZ24-I3-WG-SSH-22'; exists=$false })
    files=[pscustomobject]@{
      collector=[pscustomobject]@{ path=$collectorTarget; existed=$true; backupName='collector.ps1' }
      baseline=[pscustomobject]@{ path=$baselineTarget; existed=$false; backupName='baseline.json' }
      snapshot=[pscustomobject]@{ path=$snapshotTarget; existed=$true; backupName='snapshot.json' }
    }
  }

  Restore-InitialState -State $state
  Assert-True ((Get-Content -LiteralPath $collectorTarget -Raw).Trim() -eq 'original-collector') 'collector must be restored'
  Assert-True ((Get-Content -LiteralPath $snapshotTarget -Raw).Trim() -eq 'original-snapshot') 'snapshot must be restored'
  Assert-True (-not (Test-Path -LiteralPath $baselineTarget)) 'new baseline must be removed'
  $auditText = $global:Faz24AuditArguments -join ' '
  Assert-True ($auditText -match '/set') 'audit policy restore must be scoped set'
  Assert-True ($auditText -match '0CCE9215-69AE-11D9-BED3-505054503030') 'logon subcategory must be targeted'
  Assert-True ($auditText -match '/success:disable') 'success bit must be restored'
  Assert-True ($auditText -match '/failure:disable') 'failure bit must be restored'
  Assert-True ($auditText -notmatch '/restore') 'full audit policy restore must not be used'
  Assert-True ($global:Faz24IcaclsArguments[0] -eq (Split-Path -Parent $Root)) 'ACL restore must target root parent'
  Assert-True ($global:Faz24IcaclsArguments[1] -eq '/restore') 'ACL restore must use saved ACL file'
} finally {
  Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item function:\auditpol,function:\icacls,function:\Unregister-ScheduledTask,function:\Register-ScheduledTask,function:\Set-RegistryState,function:\Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

Write-Output 'Faz24 I3 Windows behavior tests: PASS'
