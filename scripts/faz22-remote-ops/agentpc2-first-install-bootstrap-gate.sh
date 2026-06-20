#!/usr/bin/env bash
set -euo pipefail

# Faz 22.6.3 / platform-k8s-gitops#1768 AgentPC2 first-install bootstrap gate.
#
# This script prepares a bounded, endpoint-local bootstrap package that can move
# AgentPC2 from a non-operation-capable agent to the v0.2.13 operation-capable
# release without opening inbound SSH/RDP/WinRM/SMB/RPC paths. It deliberately
# does not claim platform-agent#208 acceptance; it only produces immutable
# first-install evidence and the script required for the endpoint-local action.

RUN_ID="${GITHUB_RUN_ID:-local-$(date -u +%Y%m%dT%H%M%SZ)}"
EVIDENCE_DIR="${EVIDENCE_DIR:-/tmp/agentpc2-first-install-bootstrap-${RUN_ID}}"
TMP_DIR="$(mktemp -d)"

RELEASE_ID="${RELEASE_ID:-v0.2.13}"
TARGET_VERSION="${TARGET_VERSION:-0.2.13}"
TARGET_HOSTNAME="${TARGET_HOSTNAME:-AgentPc2}"
TARGET_PRODUCT_DEVICE_ID="${TARGET_PRODUCT_DEVICE_ID:-2f7ad30f-970a-42e7-8af8-08764ae6066f}"

RELEASE_BASE_URL="${RELEASE_BASE_URL:-https://github.com/Halildeu/platform-agent/releases/download/${RELEASE_ID}}"
INSTALL_URL="${INSTALL_URL:-${RELEASE_BASE_URL}/install.ps1}"
BINARY_URL="${BINARY_URL:-${RELEASE_BASE_URL}/endpoint-agent.exe}"
BOOTSTRAP_PACKAGE_URL="${BOOTSTRAP_PACKAGE_URL:-${RELEASE_BASE_URL}/bootstrap-package.ps1}"
MANIFEST_URL="${MANIFEST_URL:-${RELEASE_BASE_URL}/release-manifest.json}"
SHA256SUMS_URL="${SHA256SUMS_URL:-${RELEASE_BASE_URL}/SHA256SUMS}"

EXPECTED_RELEASE_MANIFEST_SHA256="${EXPECTED_RELEASE_MANIFEST_SHA256:-1cafb7bad5e6dabe8e1f10ae39ac2c91553ed923ee069776e7cb330a0e2fe08f}"
EXPECTED_INSTALL_PS1_SHA256="${EXPECTED_INSTALL_PS1_SHA256:-cb5b82f2d2dbbc0411e7f14ec0f9b68a35a900d851f86b14af93273fa72f23ec}"
EXPECTED_BOOTSTRAP_PS1_SHA256="${EXPECTED_BOOTSTRAP_PS1_SHA256:-83292ab3b5c27a8c27c11c7774cf4157bbb23188b81b0adf2a5a29a70279c7f8}"
EXPECTED_AGENT_SHA256="${EXPECTED_AGENT_SHA256:-6e3a79b8ea076d08e2288be98359d3db6049b6179e655ceaff924f792736cd0c}"
EXPECTED_AGENT_ZIP_SHA256="${EXPECTED_AGENT_ZIP_SHA256:-9afe07b6eb1fa2c8b94b50181ec5265681e77a28ec3368bdd8d1a25fd59acec0}"
EXPECTED_SIGNER_THUMBPRINT="${EXPECTED_SIGNER_THUMBPRINT:-D68F4F530137EB65CE44E3405E82B46205E753E5}"
EXPECTED_SIGNING_TIER="${EXPECTED_SIGNING_TIER:-trusted-internal-ca}"
EXPECTED_ARTIFACT_HOST_DIGEST="${EXPECTED_ARTIFACT_HOST_DIGEST:-sha256:6d19a740c5ba4b1a555d3398f5b80387b98b769c1ada2814954d3d914c975454}"

AUTO_ENROLL_API_URL="${AUTO_ENROLL_API_URL:-https://mtls.testai.acik.com/api/v1/endpoint-agent}"
AUTO_ENROLL_SAN_URI_PREFIX="${AUTO_ENROLL_SAN_URI_PREFIX:-adcomputer:}"
REMOTE_BRIDGE_HOSTNAME="${REMOTE_BRIDGE_HOSTNAME:-remote-bridge-mtls.testai.acik.com}"
REMOTE_BRIDGE_BROKER_ADDR="${REMOTE_BRIDGE_BROKER_ADDR:-${REMOTE_BRIDGE_HOSTNAME}:443}"
REMOTE_BRIDGE_MTLS_SAN_URI_PREFIX="${REMOTE_BRIDGE_MTLS_SAN_URI_PREFIX:-adcomputer:}"
REMOTE_BRIDGE_PERMIT_KID="${REMOTE_BRIDGE_PERMIT_KID:-rb-test-denetim-20260617-01}"

K8S_CONTEXT="${K8S_CONTEXT:-k3d-test}"
K8S_NAMESPACE="${K8S_NAMESPACE:-platform-test}"
PERMIT_SIGNER_SECRET="${PERMIT_SIGNER_SECRET:-endpoint-admin-remote-bridge-signer}"
PERMIT_SIGNER_SECRET_KEY="${PERMIT_SIGNER_SECRET_KEY:-permit-signing.key}"

BOOTSTRAP_PS1="${EVIDENCE_DIR}/agentpc2-first-install-bootstrap.ps1"
README_PATH="${EVIDENCE_DIR}/README.md"
SUMMARY_PATH="${EVIDENCE_DIR}/summary.json"
PUBLIC_KEY_JSON="${EVIDENCE_DIR}/permit-public-key.json"
RELEASE_SHA256SUMS_PATH="${EVIDENCE_DIR}/release-SHA256SUMS"
EVIDENCE_SHA256SUMS_PATH="${EVIDENCE_DIR}/SHA256SUMS"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERR missing command: $1" >&2
    exit 2
  }
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print tolower($1)}'
  else
    shasum -a 256 "$1" | awk '{print tolower($1)}'
  fi
}

sha256_string() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | awk '{print tolower($1)}'
  else
    printf '%s' "$1" | shasum -a 256 | awk '{print tolower($1)}'
  fi
}

lower_string() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

write_json_string_array() {
  jq -n '$ARGS.positional' --args "$@"
}

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

download_verified() {
  local url="$1"
  local out="$2"
  local expected_sha="$3"
  local actual_sha

  curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 180 \
    -o "$out" "$url"

  actual_sha="$(sha256_file "$out")"
  local expected_lower
  expected_lower="$(lower_string "${expected_sha}")"
  if [[ "${actual_sha}" != "${expected_lower}" ]]; then
    echo "ERR SHA256 mismatch for ${url}: expected ${expected_lower}, got ${actual_sha}" >&2
    exit 3
  fi
}

derive_permit_public_key_b64() {
  local public_key_b64

  if [[ -n "${REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64:-}" ]]; then
    printf '%s' "${REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64}" | tr -d '\r\n'
    return 0
  fi

  need_cmd kubectl
  local secret_json private_pem public_pem
  secret_json="${TMP_DIR}/permit-signer-secret.json"
  private_pem="${TMP_DIR}/permit-signing.key"
  public_pem="${TMP_DIR}/permit-signing.pub"

  kubectl --context "${K8S_CONTEXT}" -n "${K8S_NAMESPACE}" \
    get secret "${PERMIT_SIGNER_SECRET}" -o json > "${secret_json}"

  jq -r --arg key "${PERMIT_SIGNER_SECRET_KEY}" '.data[$key] // empty' "${secret_json}" \
    | base64 -d > "${private_pem}"

  if [[ ! -s "${private_pem}" ]]; then
    echo "ERR permit signer secret key ${PERMIT_SIGNER_SECRET_KEY} is empty" >&2
    exit 3
  fi
  chmod 0600 "${private_pem}"

  openssl pkey -in "${private_pem}" -pubout -out "${public_pem}" >/dev/null 2>&1
  public_key_b64="$(openssl pkey -pubin -in "${public_pem}" -outform DER \
    | base64 | tr -d '\r\n')"

  if [[ -z "${public_key_b64}" ]]; then
    echo "ERR derived permit public key is empty" >&2
    exit 3
  fi

  printf '%s' "${public_key_b64}"
}

write_bootstrap_script() {
  local permit_public_key_b64="$1"

  cat > "${BOOTSTRAP_PS1}" <<EOF
<#
.SYNOPSIS
AgentPC2 bounded first-install bootstrap for EndpointAgent ${RELEASE_ID}.

.DESCRIPTION
Installs the operation-capable Endpoint Agent release using immutable release
metadata, enables outbound-only remote bridge over 443/SNI, and collects
redacted endpoint-local evidence. This script contains no enrollment token,
bearer token, private key, password, or administrator credential.
#>

[CmdletBinding()]
param(
  [string]\$EvidenceRoot = "C:\\ProgramData\\EndpointAgent\\rollout-evidence",
  [string]\$WorkDir = "C:\\ProgramData\\EndpointAgent\\bootstrap\\${RELEASE_ID}",
  [int]\$PostInstallWaitSeconds = 90
)

Set-StrictMode -Version Latest
\$ErrorActionPreference = "Stop"
\$ProgressPreference = "SilentlyContinue"

\$ReleaseId = "${RELEASE_ID}"
\$TargetVersion = "${TARGET_VERSION}"
\$TargetHostname = "${TARGET_HOSTNAME}"
\$TargetProductDeviceId = "${TARGET_PRODUCT_DEVICE_ID}"

\$InstallUrl = "${INSTALL_URL}"
\$BinaryUrl = "${BINARY_URL}"
\$ExpectedInstallPs1Sha256 = "${EXPECTED_INSTALL_PS1_SHA256}"
\$ExpectedAgentSha256 = "${EXPECTED_AGENT_SHA256}"
\$ExpectedSignerThumbprint = "${EXPECTED_SIGNER_THUMBPRINT}"
\$ExpectedSigningTier = "${EXPECTED_SIGNING_TIER}"

\$AutoEnrollApiUrl = "${AUTO_ENROLL_API_URL}"
\$AutoEnrollSanUriPrefix = "${AUTO_ENROLL_SAN_URI_PREFIX}"
\$RemoteBridgeBrokerAddr = "${REMOTE_BRIDGE_BROKER_ADDR}"
\$RemoteBridgeTlsServerName = "${REMOTE_BRIDGE_HOSTNAME}"
\$RemoteBridgeMTLSSanUriPrefix = "${REMOTE_BRIDGE_MTLS_SAN_URI_PREFIX}"
\$RemoteBridgePermitKid = "${REMOTE_BRIDGE_PERMIT_KID}"
\$RemoteBridgePermitBrokerPublicKeyB64 = @'
${permit_public_key_b64}
'@.Trim()

function Write-Step {
  param([string]\$Message)
  Write-Host "[agentpc2-bootstrap] \$Message"
}

function Get-Sha256 {
  param([string]\$Path)
  return (Get-FileHash -Path \$Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-Sha256 {
  param(
    [string]\$Path,
    [string]\$Expected
  )
  \$actual = Get-Sha256 -Path \$Path
  if (\$actual -ne \$Expected.ToLowerInvariant()) {
    throw "SHA256 mismatch for \$Path expected=\$Expected actual=\$actual"
  }
}

function Invoke-DownloadVerified {
  param(
    [string]\$Uri,
    [string]\$OutFile,
    [string]\$ExpectedSha256
  )

  Invoke-WebRequest -UseBasicParsing -Uri \$Uri -OutFile \$OutFile -MaximumRedirection 5
  Assert-Sha256 -Path \$OutFile -Expected \$ExpectedSha256
}

function Get-RedactedServiceEnvironment {
  \$serviceKey = "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\EndpointAgent"
  \$raw = (Get-ItemProperty -Path \$serviceKey -Name Environment -ErrorAction SilentlyContinue).Environment
  if (\$null -eq \$raw) {
    return @()
  }

  \$rows = @()
  foreach (\$entry in \$raw) {
    \$parts = \$entry -split "=", 2
    \$key = \$parts[0]
    \$value = if (\$parts.Count -gt 1) { \$parts[1] } else { "" }
    \$isSensitive = \$key -match "TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL"
    \$rows += [PSCustomObject]@{
      Key = \$key
      Present = -not [string]::IsNullOrWhiteSpace(\$value)
      Length = \$value.Length
      Value = if (\$isSensitive) { "<redacted>" } else { \$value }
    }
  }
  return \$rows
}

function Get-ClientAuthCertRows {
  \$rows = @()
  \$certs = Get-ChildItem Cert:\\LocalMachine\\My -ErrorAction SilentlyContinue |
    Where-Object {
      \$_.HasPrivateKey -and
      \$_.EnhancedKeyUsageList.ObjectId -contains "1.3.6.1.5.5.7.3.2"
    } |
    Sort-Object NotBefore -Descending

  foreach (\$cert in \$certs) {
    \$san = \$cert.Extensions |
      Where-Object { \$_.Oid.Value -eq "2.5.29.17" } |
      Select-Object -First 1
    \$sanText = if (\$san) { \$san.Format(\$false) } else { "" }
    \$rows += [PSCustomObject]@{
      Subject = \$cert.Subject
      Issuer = \$cert.Issuer
      Thumbprint = \$cert.Thumbprint
      NotBefore = \$cert.NotBefore.ToString("o")
      NotAfter = \$cert.NotAfter.ToString("o")
      HasPrivateKey = \$cert.HasPrivateKey
      SAN = \$sanText
    }
  }
  return \$rows
}

\$startedAt = Get-Date
New-Item -ItemType Directory -Force -Path \$EvidenceRoot,\$WorkDir | Out-Null
\$TranscriptPath = Join-Path \$EvidenceRoot "agentpc2-first-install-bootstrap-transcript.log"
\$SummaryPath = Join-Path \$EvidenceRoot "agentpc2-first-install-bootstrap-summary.json"
\$InstallPath = Join-Path \$WorkDir "install.ps1"
\$BinaryPath = Join-Path \$WorkDir "endpoint-agent.exe"

try {
  Start-Transcript -Path \$TranscriptPath -Force | Out-Null

  \$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  \$principal = New-Object Security.Principal.WindowsPrincipal(\$identity)
  if (-not \$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Administrator shell required."
  }

  Write-Step "download immutable install.ps1"
  Invoke-DownloadVerified -Uri \$InstallUrl -OutFile \$InstallPath -ExpectedSha256 \$ExpectedInstallPs1Sha256

  Write-Step "download immutable endpoint-agent.exe"
  Invoke-DownloadVerified -Uri \$BinaryUrl -OutFile \$BinaryPath -ExpectedSha256 \$ExpectedAgentSha256

  Write-Step "verify endpoint-agent.exe signer thumbprint"
  \$signature = Get-AuthenticodeSignature -FilePath \$BinaryPath
  \$signerThumbprint = if (\$signature.SignerCertificate) { \$signature.SignerCertificate.Thumbprint } else { "" }
  if (\$signerThumbprint -ne \$ExpectedSignerThumbprint) {
    throw "Signer thumbprint mismatch expected=\$ExpectedSignerThumbprint actual=\$signerThumbprint"
  }

  Write-Step "install EndpointAgent \$ReleaseId with outbound remote bridge"
  \$installArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", \$InstallPath,
    "-BinaryPath", \$BinaryPath,
    "-ExpectedSha256", \$ExpectedAgentSha256,
    "-ExpectedSignerThumbprint", \$ExpectedSignerThumbprint,
    "-SigningTier", \$ExpectedSigningTier,
    "-ReleaseTag", \$ReleaseId,
    "-AutoEnroll",
    "-AutoEnrollApiUrl", \$AutoEnrollApiUrl,
    "-AutoEnrollCertSANURIPrefix", \$AutoEnrollSanUriPrefix,
    "-RemoteBridgeEnabled",
    "-RemoteBridgeBrokerAddr", \$RemoteBridgeBrokerAddr,
    "-RemoteBridgeMTLSCertSANURIPrefix", \$RemoteBridgeMTLSSanUriPrefix,
    "-RemoteBridgeOperationsEnabled",
    "-RemoteBridgePermitBrokerPublicKeyB64", \$RemoteBridgePermitBrokerPublicKeyB64,
    "-RemoteBridgePermitKeyID", \$RemoteBridgePermitKid,
    "-RemoteBridgeTLSServerName", \$RemoteBridgeTlsServerName,
    "-ServiceStartTimeoutSeconds", "90",
    "-Force",
    "-Start"
  )
  & powershell.exe @installArgs

  if (\$LASTEXITCODE -ne 0) {
    throw "install.ps1 exited with code \$LASTEXITCODE"
  }

  Start-Sleep -Seconds \$PostInstallWaitSeconds

  \$service = Get-CimInstance Win32_Service |
    Where-Object { \$_.Name -eq "EndpointAgent" } |
    Select-Object Name,DisplayName,State,StartMode,StartName,PathName

  \$serviceEnv = Get-RedactedServiceEnvironment
  \$certRows = Get-ClientAuthCertRows
  \$logTailPath = Join-Path \$EvidenceRoot "endpoint-agent-log-tail.txt"
  Get-Content "C:\\ProgramData\\EndpointAgent\\logs\\*.log" -Tail 800 -ErrorAction SilentlyContinue |
    Set-Content -Path \$logTailPath -Encoding UTF8

  \$signalsPath = Join-Path \$EvidenceRoot "endpoint-agent-remote-bridge-signals.txt"
  Get-Content \$logTailPath -ErrorAction SilentlyContinue |
    Select-String -Pattern "remote-bridge|bridge|mtls|mTLS|hello|HELLO|permit|operation|CONSTRAINED|error|failed|denied|certificate|attestation|${REMOTE_BRIDGE_HOSTNAME}" |
    ForEach-Object { \$_.Line } |
    Set-Content -Path \$signalsPath -Encoding UTF8

  \$completedAt = Get-Date
  [PSCustomObject]@{
    schema = "faz22.1768.agentpc2-first-install-bootstrap.endpoint.v1"
    status = if (\$service -and \$service.State -eq "Running") { "installed-service-running" } else { "installed-service-not-running" }
    startedAt = \$startedAt.ToString("o")
    completedAt = \$completedAt.ToString("o")
    computerName = \$env:COMPUTERNAME
    user = \$identity.Name
    release = @{
      id = \$ReleaseId
      targetVersion = \$TargetVersion
      binaryUrl = \$BinaryUrl
      binarySha256 = \$ExpectedAgentSha256
      installPs1Sha256 = \$ExpectedInstallPs1Sha256
      signerThumbprint = \$ExpectedSignerThumbprint
      signingTier = \$ExpectedSigningTier
      authenticodeStatus = [string]\$signature.Status
      authenticodeStatusMessage = [string]\$signature.StatusMessage
    }
    remoteBridge = @{
      enabled = \$true
      brokerAddr = \$RemoteBridgeBrokerAddr
      tlsServerName = \$RemoteBridgeTlsServerName
      operationsEnabled = \$true
      permitKeyId = \$RemoteBridgePermitKid
      permitBrokerPublicKeySha256 = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::ASCII.GetBytes(\$RemoteBridgePermitBrokerPublicKeyB64))).Replace("-", "").ToLowerInvariant()
    }
    autoEnroll = @{
      apiUrl = \$AutoEnrollApiUrl
      certSANURIPrefix = \$AutoEnrollSanUriPrefix
    }
    service = \$service
    redactedServiceEnvironment = \$serviceEnv
    clientAuthCerts = \$certRows
    evidence = @{
      root = \$EvidenceRoot
      transcript = \$TranscriptPath
      logTail = \$logTailPath
      remoteBridgeSignals = \$signalsPath
    }
    boundary = @{
      proves = @(
        "Endpoint-local install script executed",
        "EndpointAgent service install/start attempted with immutable v0.2.13 binary hash",
        "Outbound remote bridge configuration written for 443/SNI broker"
      )
      doesNotProve = @(
        "platform-agent#208 constrained operation acceptance",
        "broad GPO/MSI rollout",
        "inbound SSH/RDP/WinRM/SMB/RPC support",
        "production/domain-wide support readiness",
        "TPM/device-key hardware attestation"
      )
    }
  } | ConvertTo-Json -Depth 8 | Set-Content -Path \$SummaryPath -Encoding UTF8

  Write-Step "summary: \$SummaryPath"
  Get-Content \$SummaryPath
} catch {
  \$completedAt = Get-Date
  [PSCustomObject]@{
    schema = "faz22.1768.agentpc2-first-install-bootstrap.endpoint.v1"
    status = "failed"
    startedAt = \$startedAt.ToString("o")
    completedAt = \$completedAt.ToString("o")
    computerName = \$env:COMPUTERNAME
    user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    error = \$_.Exception.Message
    evidence = @{ root = \$EvidenceRoot; transcript = \$TranscriptPath }
  } | ConvertTo-Json -Depth 6 | Set-Content -Path \$SummaryPath -Encoding UTF8
  Write-Error \$_.Exception.Message
  exit 1
} finally {
  try { Stop-Transcript | Out-Null } catch {}
}
EOF

  chmod 0644 "${BOOTSTRAP_PS1}"
}

write_readme() {
  cat > "${README_PATH}" <<EOF
# AgentPC2 first-install bootstrap package

This package was generated by scripts/faz22-remote-ops/agentpc2-first-install-bootstrap-gate.sh.

Purpose:
- Move AgentPC2 to EndpointAgent ${RELEASE_ID} when the currently installed agent does not advertise \`UPDATE_AGENT\`.
- Preserve the product remote-ops acceptance boundary: this package is only a bootstrap step, not #208 acceptance.
- Use outbound-only remote bridge configuration over ${REMOTE_BRIDGE_BROKER_ADDR}.

Run on AgentPC2 from an elevated PowerShell session:

    Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\agentpc2-first-install-bootstrap.ps1

Endpoint evidence will be written under:

    C:\\ProgramData\\EndpointAgent\\rollout-evidence

The script contains no HMAC enrollment token, bearer token, password, private key, or administrator credential. It contains the broker permit public key, which is intentionally public verifier material.

The artifact bundle contains a top-level SHA256SUMS file with relative paths. Verify it from this directory before endpoint-local execution.

After endpoint-local execution, rerun the #208 constrained-executor acceptance workflow. Do not close #208 from this bootstrap evidence alone.
EOF
}

write_summary() {
  local permit_public_key_b64="$1"
  local permit_public_key_sha="$2"
  local manifest_sha="$3"
  local install_sha="$4"
  local bootstrap_sha="$5"
  local artifact_image="${6:-}"
  local artifact_ready="${7:-}"
  local generated_at
  generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  jq -n \
    --arg schema "faz22.1768.agentpc2-first-install-bootstrap.gate.v1" \
    --arg generatedAt "${generated_at}" \
    --arg status "bootstrap-ready" \
    --arg releaseId "${RELEASE_ID}" \
    --arg targetVersion "${TARGET_VERSION}" \
    --arg targetHostname "${TARGET_HOSTNAME}" \
    --arg targetProductDeviceId "${TARGET_PRODUCT_DEVICE_ID}" \
    --arg manifestUrl "${MANIFEST_URL}" \
    --arg manifestSha256 "${manifest_sha}" \
    --arg expectedManifestSha256 "$(lower_string "${EXPECTED_RELEASE_MANIFEST_SHA256}")" \
    --arg installUrl "${INSTALL_URL}" \
    --arg installPs1Sha256 "${install_sha}" \
    --arg expectedInstallPs1Sha256 "$(lower_string "${EXPECTED_INSTALL_PS1_SHA256}")" \
    --arg bootstrapPackageUrl "${BOOTSTRAP_PACKAGE_URL}" \
    --arg bootstrapPs1Sha256 "${bootstrap_sha}" \
    --arg expectedBootstrapPs1Sha256 "$(lower_string "${EXPECTED_BOOTSTRAP_PS1_SHA256}")" \
    --arg binaryUrl "${BINARY_URL}" \
    --arg binarySha256 "$(lower_string "${EXPECTED_AGENT_SHA256}")" \
    --arg zipSha256 "$(lower_string "${EXPECTED_AGENT_ZIP_SHA256}")" \
    --arg signerThumbprint "${EXPECTED_SIGNER_THUMBPRINT}" \
    --arg signingTier "${EXPECTED_SIGNING_TIER}" \
    --arg artifactHostDigest "${EXPECTED_ARTIFACT_HOST_DIGEST}" \
    --arg artifactImage "${artifact_image}" \
    --arg artifactReady "${artifact_ready}" \
    --arg autoEnrollApiUrl "${AUTO_ENROLL_API_URL}" \
    --arg autoEnrollSanUriPrefix "${AUTO_ENROLL_SAN_URI_PREFIX}" \
    --arg brokerAddr "${REMOTE_BRIDGE_BROKER_ADDR}" \
    --arg tlsServerName "${REMOTE_BRIDGE_HOSTNAME}" \
    --arg permitKeyId "${REMOTE_BRIDGE_PERMIT_KID}" \
    --arg permitPublicKeySha256 "${permit_public_key_sha}" \
    --arg evidenceDir "${EVIDENCE_DIR}" \
    --arg bootstrapScript "${BOOTSTRAP_PS1}" \
    --arg readme "${README_PATH}" \
    --argjson proves "$(write_json_string_array \
      "v0.2.13 release manifest/install/bootstrap hashes verified" \
      "Broker permit public key derived from live signer source or explicit public-key override" \
      "Endpoint-local first-install script generated with outbound-only 443/SNI remote bridge configuration" \
      "No inbound endpoint management port is required by this bootstrap package")" \
    --argjson doesNotProve "$(write_json_string_array \
      "platform-agent#208 constrained executor acceptance" \
      "AgentPC2 endpoint actually executed the bootstrap script" \
      "broad GPO/MSI rollout" \
      "production/domain-wide support readiness" \
      "TPM/device-key hardware attestation")" \
    --argjson secretHygiene '{"rawBearerTokenLogged":false,"rawPasswordLogged":false,"rawPrivateKeyLogged":false,"hmacEnrollmentTokenIncluded":false}' \
    '{
      schema:$schema,
      generatedAt:$generatedAt,
      status:$status,
      target:{hostname:$targetHostname, productDeviceId:$targetProductDeviceId},
      release:{
        id:$releaseId,
        targetVersion:$targetVersion,
        manifest:{url:$manifestUrl, sha256:$manifestSha256, expectedSha256:$expectedManifestSha256},
        installPs1:{url:$installUrl, sha256:$installPs1Sha256, expectedSha256:$expectedInstallPs1Sha256},
        bootstrapPackagePs1:{url:$bootstrapPackageUrl, sha256:$bootstrapPs1Sha256, expectedSha256:$expectedBootstrapPs1Sha256},
        binary:{url:$binaryUrl, sha256:$binarySha256},
        zip:{sha256:$zipSha256},
        signer:{thumbprint:$signerThumbprint, tier:$signingTier},
        artifactHostDigest:$artifactHostDigest
      },
      artifactHost:{image:$artifactImage, readyReplicas:$artifactReady},
      autoEnroll:{apiUrl:$autoEnrollApiUrl, certSANURIPrefix:$autoEnrollSanUriPrefix},
      remoteBridge:{
        brokerAddr:$brokerAddr,
        tlsServerName:$tlsServerName,
        operationsEnabled:true,
        permitKeyId:$permitKeyId,
        permitBrokerPublicKeySha256:$permitPublicKeySha256
      },
      evidence:{dir:$evidenceDir, bootstrapScript:$bootstrapScript, readme:$readme},
      boundary:{proves:$proves, doesNotProve:$doesNotProve},
      secretHygiene:$secretHygiene
    }' > "${SUMMARY_PATH}"
}

scan_for_secret_leaks() {
  local hits
  set +e
  hits="$(grep -RInE 'BEGIN [A-Z ]*PRIVATE KEY|Authorization: Bearer|access_token|refresh_token|client_secret|password=|PASSWORD=|KC_ADMIN|permit-signing\\.key' "${EVIDENCE_DIR}" 2>/dev/null)"
  set -e
  if [[ -n "${hits}" ]]; then
    echo "ERR potential secret material found in evidence:" >&2
    printf '%s\n' "${hits}" >&2
    exit 4
  fi
}

write_evidence_sha256sums() {
  local sums_tmp
  sums_tmp="${TMP_DIR}/agentpc2-first-install-evidence-SHA256SUMS"

  (
    cd "${EVIDENCE_DIR}"
    if command -v shasum >/dev/null 2>&1; then
      find . -maxdepth 1 -type f ! -name "SHA256SUMS" -print0 \
        | sort -z \
        | xargs -0 shasum -a 256
    else
      find . -maxdepth 1 -type f ! -name "SHA256SUMS" -print0 \
        | sort -z \
        | xargs -0 sha256sum
    fi
  ) > "${sums_tmp}"

  mv "${sums_tmp}" "${EVIDENCE_SHA256SUMS_PATH}"

  (
    cd "${EVIDENCE_DIR}"
    if command -v shasum >/dev/null 2>&1; then
      shasum -a 256 -c "SHA256SUMS" >/dev/null
    else
      sha256sum -c "SHA256SUMS" >/dev/null
    fi
  )
}

main() {
  need_cmd curl
  need_cmd jq
  need_cmd openssl
  need_cmd base64

  mkdir -p "${EVIDENCE_DIR}"
  chmod 0700 "${EVIDENCE_DIR}"

  local manifest_path install_path bootstrap_path sha_manifest sha_install sha_bootstrap
  manifest_path="${EVIDENCE_DIR}/release-manifest.json"
  install_path="${EVIDENCE_DIR}/install.ps1"
  bootstrap_path="${EVIDENCE_DIR}/bootstrap-package.ps1"

  echo "=== DOWNLOAD AND VERIFY RELEASE METADATA ==="
  download_verified "${MANIFEST_URL}" "${manifest_path}" "${EXPECTED_RELEASE_MANIFEST_SHA256}"
  download_verified "${INSTALL_URL}" "${install_path}" "${EXPECTED_INSTALL_PS1_SHA256}"
  download_verified "${BOOTSTRAP_PACKAGE_URL}" "${bootstrap_path}" "${EXPECTED_BOOTSTRAP_PS1_SHA256}"
  curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 60 \
    -o "${RELEASE_SHA256SUMS_PATH}" "${SHA256SUMS_URL}"

  sha_manifest="$(sha256_file "${manifest_path}")"
  sha_install="$(sha256_file "${install_path}")"
  sha_bootstrap="$(sha256_file "${bootstrap_path}")"

  if ! jq -e \
    --arg release_id "${RELEASE_ID}" \
    --arg target_version "${TARGET_VERSION}" \
    --arg agent_sha "${EXPECTED_AGENT_SHA256}" \
    --arg zip_sha "${EXPECTED_AGENT_ZIP_SHA256}" \
    --arg signer "${EXPECTED_SIGNER_THUMBPRINT}" \
    --arg tier "${EXPECTED_SIGNING_TIER}" \
    --arg digest "${EXPECTED_ARTIFACT_HOST_DIGEST}" \
    '
      (.release_tag == $release_id) and
      (($release_id | sub("^v"; "")) == $target_version) and
      ((.endpoint_agent_sha256 | ascii_downcase) == ($agent_sha | ascii_downcase)) and
      ((.endpoint_agent_zip_sha256 | ascii_downcase) == ($zip_sha | ascii_downcase)) and
      ((.signer_thumbprint | ascii_upcase) == ($signer | ascii_upcase)) and
      (.signing_tier == $tier) and
      (.artifact_host_digest == $digest)
    ' "${manifest_path}" >/dev/null; then
    echo "ERR release manifest did not match expected v0.2.13 immutable metadata" >&2
    exit 3
  fi

  echo "=== DERIVE BROKER PERMIT PUBLIC KEY ==="
  local permit_public_key_b64 permit_public_key_sha
  permit_public_key_b64="$(derive_permit_public_key_b64)"
  permit_public_key_sha="$(sha256_string "${permit_public_key_b64}")"

  jq -n \
    --arg keyId "${REMOTE_BRIDGE_PERMIT_KID}" \
    --arg publicKeyB64 "${permit_public_key_b64}" \
    --arg publicKeySha256 "${permit_public_key_sha}" \
    --arg source "$(if [[ -n "${REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64:-}" ]]; then printf 'env-override'; else printf '%s/%s/%s' "${K8S_CONTEXT}" "${K8S_NAMESPACE}" "${PERMIT_SIGNER_SECRET}"; fi)" \
    '{
      keyId:$keyId,
      brokerPublicKeyB64:$publicKeyB64,
      brokerPublicKeySha256:$publicKeySha256,
      source:$source,
      note:"Public verifier material only; no private key is included."
    }' > "${PUBLIC_KEY_JSON}"

  echo "=== BROKER DNS PREFLIGHT ==="
  if command -v getent >/dev/null 2>&1; then
    getent hosts "${REMOTE_BRIDGE_HOSTNAME}" > "${EVIDENCE_DIR}/remote-bridge-dns.txt"
  else
    nslookup "${REMOTE_BRIDGE_HOSTNAME}" > "${EVIDENCE_DIR}/remote-bridge-dns.txt" 2>&1 || true
  fi
  if [[ ! -s "${EVIDENCE_DIR}/remote-bridge-dns.txt" ]]; then
    echo "ERR remote bridge hostname did not resolve: ${REMOTE_BRIDGE_HOSTNAME}" >&2
    exit 3
  fi

  echo "=== ARTIFACT HOST LIVE SNAPSHOT ==="
  local artifact_image="" artifact_ready=""
  if command -v kubectl >/dev/null 2>&1; then
    set +e
    kubectl --context "${K8S_CONTEXT}" -n "${K8S_NAMESPACE}" get deploy artifact-host -o json \
      > "${EVIDENCE_DIR}/artifact-host-deployment.json" 2>"${EVIDENCE_DIR}/artifact-host-deployment.err"
    local kubectl_status=$?
    set -e
    if [[ "${kubectl_status}" == "0" ]]; then
      artifact_image="$(jq -r '.spec.template.spec.containers[0].image // ""' "${EVIDENCE_DIR}/artifact-host-deployment.json")"
      artifact_ready="$(jq -r '.status.readyReplicas // 0' "${EVIDENCE_DIR}/artifact-host-deployment.json")"
    fi
  fi

  echo "=== WRITE ENDPOINT BOOTSTRAP PACKAGE ==="
  write_bootstrap_script "${permit_public_key_b64}"
  write_readme
  write_summary "${permit_public_key_b64}" "${permit_public_key_sha}" \
    "${sha_manifest}" "${sha_install}" "${sha_bootstrap}" \
    "${artifact_image}" "${artifact_ready}"

  scan_for_secret_leaks
  write_evidence_sha256sums

  echo "=== SUMMARY ==="
  jq . "${SUMMARY_PATH}"
  echo "AGENTPC2_FIRST_INSTALL_BOOTSTRAP_READY evidence=${EVIDENCE_DIR}"
}

main "$@"
