#requires -Version 5.1
#requires -RunAsAdministrator

<#
.SYNOPSIS
Activates the Denetim PC TPM device-key and attended VIEW_ONLY endpoint lane.

.DESCRIPTION
This is a bounded post-bootstrap configuration step for the canonical Faz 22.6
Denetim endpoint. It does not install a binary, enroll a certificate, or carry
credentials. The script fails closed unless the expected signed agent binary,
TPM device certificate, TPM readiness, outbound-443 configuration, permit
trust anchor, and signed self-update policy are already present.

The existing service registry key is exported locally before mutation. Output
and evidence contain only key presence and certificate metadata; service
environment values, private keys, tokens, and credentials are never emitted.
#>

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
  [string]$ExpectedHostname = "SRB-AIDENETIMPC",
  [string]$ExpectedBinarySha256 = "4421383b58d3afacf30b7f66187e52e1e248d2bb6106c32eaebfd9169a9f4f11",
  [string]$ExpectedDeviceCertIssuer = "CN=platform-test endpoint device CA",
  [string]$ExpectedPermitKeyId = "rb-test-denetim-20260617-01",
  [string]$ExpectedPermitPublicKeyB64Sha256 = "0a92abcd8f84619fb8f14f530beb94cbdc4e0981c9eb14a4756bdc85175a1110",
  [string]$ExpectedBrokerAddr = "remote-bridge-mtls.testai.acik.com:443",
  [string]$ExpectedTlsServerName = "remote-bridge-mtls.testai.acik.com",
  [string]$ServiceName = "EndpointAgent",
  [string]$BinaryPath = "C:\Program Files\EndpointAgent\endpoint-agent.exe",
  [string]$DeviceCertPath = "$env:ProgramData\EndpointAgent\tpm-client-cert.pem",
  [string]$EvidenceRoot = "$env:ProgramData\EndpointAgent\rollout-evidence",
  [int]$ServiceRestartTimeoutSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
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

function Restart-ServiceAndWait {
  param([string]$Name, [int]$TimeoutSeconds)

  Restart-Service -Name $Name -Force -ErrorAction Stop
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    $currentService = Get-Service -Name $Name -ErrorAction Stop
    if ($currentService.Status -eq "Running") {
      return $currentService
    }
    Start-Sleep -Seconds 2
  } while ((Get-Date) -lt $deadline)

  throw "$Name did not reach Running within $TimeoutSeconds seconds"
}

function Write-ServiceEnvironmentMap {
  param([string]$Path, $Map)

  $entries = @()
  foreach ($key in @($Map.Keys | Sort-Object)) {
    $entries += "$key=$([string]$Map[$key])"
  }
  Set-ItemProperty -Path $Path -Name Environment -Type MultiString -Value $entries
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
if (-not (Test-Path -LiteralPath $BinaryPath)) {
  throw "EndpointAgent binary is absent"
}
if (-not (Test-Path -LiteralPath $DeviceCertPath)) {
  throw "TPM device certificate is absent; run the approved TPM enrollment flow first"
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

$current = Read-ServiceEnvironmentMap -Path $serviceKey
Assert-MapValue -Map $current -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED" -Expected "true"
Assert-MapValue -Map $current -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR" -Expected $ExpectedBrokerAddr
Assert-MapValue -Map $current -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_TLS_SERVER_NAME" -Expected $ExpectedTlsServerName
Assert-MapValue -Map $current -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_OPERATIONS_ENABLED" -Expected "true"
Assert-MapValue -Map $current -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64"
Assert-MapValue -Map $current -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_KEY_ID" -Expected $ExpectedPermitKeyId
Assert-MapValue -Map $current -Key "ENDPOINT_AGENT_SELF_UPDATE_ENABLED" -Expected "true"
Assert-MapValue -Map $current -Key "ENDPOINT_AGENT_SELF_UPDATE_SIGNER_THUMBPRINTS"

$actualPermitPublicKeyB64Sha256 = Get-AsciiSha256 -Value ([string]$current["ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64"])
if ($actualPermitPublicKeyB64Sha256 -ne $ExpectedPermitPublicKeyB64Sha256.ToLowerInvariant()) {
  throw "Remote bridge permit public key differs from the approved test trust anchor"
}

$WhatIfPreference = $requestedWhatIf
if (-not $PSCmdlet.ShouldProcess($ExpectedHostname, "activate TPM device-key and attended VIEW_ONLY service environment")) {
  return
}
$WhatIfPreference = $false

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$uniqueSuffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$backupDir = Join-Path $EvidenceRoot "denetim-device-key-view-only-$timestamp-$uniqueSuffix"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

& icacls.exe $backupDir /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "Could not restrict the local activation evidence directory ACL"
}

$registryBackup = Join-Path $backupDir "$ServiceName-service-before.reg"
$summaryPath = Join-Path $backupDir "summary.json"

& reg.exe export "HKLM\SYSTEM\CurrentControlSet\Services\$ServiceName" $registryBackup /y | Out-Null
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $registryBackup)) {
  throw "Could not create the local service registry rollback export"
}

$patched = [ordered]@{}
foreach ($key in $current.Keys) {
  $patched[$key] = $current[$key]
}
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_INSECURE_PLAINTEXT"] = "false"
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_PILOT_AUTO_CONSENT"] = "false"
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_DEVICE_KEY_SESSION_ENABLED"] = "true"
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ENABLED"] = "true"
$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ATTENDED_CONSENT_ENABLED"] = "true"

$scriptPath = $MyInvocation.MyCommand.Path
$scriptSha256 = if (-not [string]::IsNullOrWhiteSpace($scriptPath) -and (Test-Path -LiteralPath $scriptPath)) {
  (Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant()
} else {
  $null
}

$mutationStarted = $false
$committed = $false
$rollbackPerformed = $false
try {
  $mutationStarted = $true
  Write-ServiceEnvironmentMap -Path $serviceKey -Map $patched
  $serviceAfter = Restart-ServiceAndWait -Name $ServiceName -TimeoutSeconds $ServiceRestartTimeoutSeconds

  $after = Read-ServiceEnvironmentMap -Path $serviceKey
  foreach ($required in @(
    "ENDPOINT_AGENT_REMOTE_BRIDGE_DEVICE_KEY_SESSION_ENABLED",
    "ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ENABLED",
    "ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ATTENDED_CONSENT_ENABLED"
  )) {
    Assert-MapValue -Map $after -Key $required -Expected "true"
  }
  Assert-MapValue -Map $after -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_PILOT_AUTO_CONSENT" -Expected "false"
  if ($serviceAfter.Status -ne "Running") {
    throw "EndpointAgent did not return to Running after activation"
  }

  $result = [ordered]@{
    schema = "faz22.6.denetimepc-device-key-view-only-activation.v3"
    status = "configuration-written-service-running-awaiting-broker-proof"
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
      binaryPath = $BinaryPath
      serviceImagePath = $serviceImagePath
      binarySha256 = $actualBinarySha256
      expectedBinarySha256 = $ExpectedBinarySha256.ToLowerInvariant()
    }
    tpm = [ordered]@{
      present = [bool]$tpm.TpmPresent
      ready = [bool]$tpm.TpmReady
      manufacturerId = [string]$tpm.ManufacturerIdTxt
    }
    deviceCertificate = [ordered]@{
      path = $DeviceCertPath
      fileSha256 = (Get-FileHash -LiteralPath $DeviceCertPath -Algorithm SHA256).Hash.ToLowerInvariant()
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
    }
    configuration = [ordered]@{
      brokerAddr = $ExpectedBrokerAddr
      tlsServerName = $ExpectedTlsServerName
      operationsEnabled = $true
      constrainedPtyPilotAutoConsentEnabled = $false
      deviceKeySessionEnabled = $true
      viewOnlyEnabled = $true
      attendedConsentEnabled = $true
      insecurePlaintext = $false
      permitKeyId = $ExpectedPermitKeyId
      permitPublicKeyB64Sha256 = $actualPermitPublicKeyB64Sha256
      permitTrustAnchorPinned = $true
      selfUpdatePolicyPreserved = [string]$after["ENDPOINT_AGENT_SELF_UPDATE_ENABLED"] -eq "true"
    }
    rollback = [ordered]@{
      localRegistryExport = $registryBackup
      directoryAclRestrictedToSystemAndAdministrators = $true
      automaticRollbackPerformed = $false
    }
    evidenceHygiene = [ordered]@{
      rawServiceEnvironmentIncluded = $false
      rawSecretIncluded = $false
      tokenIncluded = $false
      privateKeyIncluded = $false
    }
    boundary = [ordered]@{
      proves = @(
        "approved EndpointAgent binary digest and service executable path are installed",
        "on-disk TPM device certificate claims the expected hostname and broker client CA issuer",
        "TPM reports present and ready",
        "pinned test permit trust anchor and attended VIEW_ONLY configuration were written",
        "CONSTRAINED_PTY pilot auto-consent was disabled",
        "EndpointAgent returned to Running"
      )
      doesNotProve = @(
        "TPM private-key binding or broker device-key challenge acceptance",
        "VIEW_ONLY session delivery or rendered frames",
        "human attended consent approval",
        "KVKK or legal approval",
        "production readiness"
      )
    }
  }

  $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
  if (-not (Test-Path -LiteralPath $summaryPath)) {
    throw "Activation summary could not be written"
  }
  $committed = $true
} catch {
  $activationError = $_.Exception.Message
  if ($mutationStarted -and -not $committed) {
    try {
      & reg.exe import $registryBackup | Out-Null
      if ($LASTEXITCODE -ne 0) {
        throw "registry import returned exit code $LASTEXITCODE"
      }
      [void](Restart-ServiceAndWait -Name $ServiceName -TimeoutSeconds $ServiceRestartTimeoutSeconds)
      $restored = Read-ServiceEnvironmentMap -Path $serviceKey
      Assert-MapsEqual -Expected $current -Actual $restored
      $rollbackPerformed = $true
    } catch {
      $rollbackError = $_.Exception.Message
      throw "Activation failed and verified automatic rollback failed. Activation error: $activationError. Rollback error: $rollbackError. Use the protected local registry export: $registryBackup"
    }
  }
  throw "Activation failed; the previous service configuration was restored and verified: $activationError"
}

Write-Host "status=configuration-written-service-running-awaiting-broker-proof"
Write-Host "evidence=$summaryPath"
