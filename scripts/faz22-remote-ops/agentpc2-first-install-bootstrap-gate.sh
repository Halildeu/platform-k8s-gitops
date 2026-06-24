#!/usr/bin/env bash
set -euo pipefail

# Faz 22.6.3 / platform-k8s-gitops#1768 AgentPC2 first-install bootstrap gate.
#
# This script prepares a bounded, endpoint-local bootstrap package that can move
# AgentPC2 from a non-operation-capable agent to the selected operation-capable
# release without opening inbound SSH/RDP/WinRM/SMB/RPC paths. It deliberately
# does not claim platform-agent#208 acceptance; it only produces immutable
# first-install evidence and the script required for the endpoint-local action.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
# shellcheck source=scripts/faz22-remote-ops/endpoint-agent-release-policy.sh
source "${SCRIPT_DIR}/endpoint-agent-release-policy.sh"
endpoint_agent_release_policy_load "$REPO_ROOT"

RUN_ID="${GITHUB_RUN_ID:-local-$(date -u +%Y%m%dT%H%M%SZ)}"
EVIDENCE_DIR="${EVIDENCE_DIR:-/tmp/agentpc2-first-install-bootstrap-${RUN_ID}}"
TMP_DIR="$(mktemp -d)"

TARGET_VERSION="${TARGET_VERSION:-$EXPECTED_AGENT_VERSION}"
TARGET_HOSTNAME="${TARGET_HOSTNAME:-AgentPc2}"
TARGET_PRODUCT_DEVICE_ID="${TARGET_PRODUCT_DEVICE_ID:-2f7ad30f-970a-42e7-8af8-08764ae6066f}"

RELEASE_BASE_URL="${RELEASE_BASE_URL:-$GITHUB_RELEASE_BASE_URL}"
INSTALL_URL="${INSTALL_URL:-${RELEASE_BASE_URL}/install.ps1}"
BINARY_URL="${BINARY_URL:-${RELEASE_BASE_URL}/endpoint-agent.exe}"
BOOTSTRAP_PACKAGE_URL="${BOOTSTRAP_PACKAGE_URL:-${RELEASE_BASE_URL}/bootstrap-package.ps1}"
MANIFEST_URL="${MANIFEST_URL:-${RELEASE_BASE_URL}/release-manifest.json}"
SHA256SUMS_URL="${SHA256SUMS_URL:-${RELEASE_BASE_URL}/SHA256SUMS}"

: "${EXPECTED_RELEASE_MANIFEST_SHA256:?missing expected release manifest SHA256}"
: "${EXPECTED_INSTALL_PS1_SHA256:?missing expected install.ps1 SHA256}"
: "${EXPECTED_BOOTSTRAP_PS1_SHA256:?missing expected bootstrap-package.ps1 SHA256}"
: "${EXPECTED_SIGNER_SHA256_FINGERPRINT:?missing expected signer SHA256 fingerprint}"
REQUIRE_ARTIFACT_HOST_LIVE_DIGEST="${REQUIRE_ARTIFACT_HOST_LIVE_DIGEST:-true}"

AUTO_ENROLL_API_URL="${AUTO_ENROLL_API_URL:-https://mtls.testai.acik.com/api/v1/endpoint-agent}"
AUTO_ENROLL_SAN_URI_PREFIX="${AUTO_ENROLL_SAN_URI_PREFIX:-adcomputer:}"
REMOTE_BRIDGE_HOSTNAME="${REMOTE_BRIDGE_HOSTNAME:-remote-bridge-mtls.testai.acik.com}"
REMOTE_BRIDGE_BROKER_ADDR="${REMOTE_BRIDGE_BROKER_ADDR:-${REMOTE_BRIDGE_HOSTNAME}:443}"
REMOTE_BRIDGE_MTLS_SAN_URI_PREFIX="${REMOTE_BRIDGE_MTLS_SAN_URI_PREFIX:-adcomputer:}"
REMOTE_BRIDGE_PERMIT_KID="${REMOTE_BRIDGE_PERMIT_KID:-rb-test-denetim-20260617-01}"

SELF_UPDATE_ALLOWED_HOSTS="${SELF_UPDATE_ALLOWED_HOSTS:-github.com,release-assets.githubusercontent.com,objects.githubusercontent.com,testai.acik.com}"
SELF_UPDATE_HARD_MAX_BYTES="${SELF_UPDATE_HARD_MAX_BYTES:-52428800}"
SELF_UPDATE_MAX_REDIRECTS="${SELF_UPDATE_MAX_REDIRECTS:-5}"
SELF_UPDATE_AUTO_ACTIVATE="${SELF_UPDATE_AUTO_ACTIVATE:-true}"
SELF_UPDATE_ACTIVATION_TIMEOUT="${SELF_UPDATE_ACTIVATION_TIMEOUT:-2m}"
SELF_UPDATE_COMMAND_TIMEOUT="${SELF_UPDATE_COMMAND_TIMEOUT:-30m}"

K8S_CONTEXT="${K8S_CONTEXT:-k3d-test}"
K8S_NAMESPACE="${K8S_NAMESPACE:-platform-test}"
PERMIT_SIGNER_SECRET="${PERMIT_SIGNER_SECRET:-endpoint-admin-remote-bridge-signer}"
PERMIT_SIGNER_SECRET_KEY="${PERMIT_SIGNER_SECRET_KEY:-permit-signing.key}"

BOOTSTRAP_PS1="${EVIDENCE_DIR}/agentpc2-first-install-bootstrap.ps1"
CANONICAL_ENV_PATCH_PS1="${EVIDENCE_DIR}/agentpc2-remote-bridge-canonical-env-patch-v7.ps1"
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

validate_release_inputs() {
  if [[ "${#TARGET_HOSTNAME}" -gt 253 ]] || ! printf '%s' "${TARGET_HOSTNAME}" | grep -Eq '^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)([.][A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$'; then
    echo "ERR TARGET_HOSTNAME must be a DNS-safe hostname label/FQDN" >&2
    exit 2
  fi

  if [[ "${RELEASE_ID}" != "v${TARGET_VERSION}" ]]; then
    echo "ERR RELEASE_ID must equal vTARGET_VERSION: release=${RELEASE_ID} target=${TARGET_VERSION}" >&2
    exit 2
  fi

  if ! printf '%s' "${RELEASE_ID}" | grep -Eq '^v[0-9]+[.][0-9]+[.][0-9]+(-[A-Za-z0-9._-]+)?$'; then
    echo "ERR RELEASE_ID must look like vX.Y.Z" >&2
    exit 2
  fi

  for value in \
    "${EXPECTED_RELEASE_MANIFEST_SHA256}" \
    "${EXPECTED_INSTALL_PS1_SHA256}" \
    "${EXPECTED_BOOTSTRAP_PS1_SHA256}" \
    "${EXPECTED_AGENT_SHA256}" \
    "${EXPECTED_AGENT_ZIP_SHA256}"
  do
    if ! printf '%s' "${value}" | grep -Eq '^[a-f0-9]{64}$'; then
      echo "ERR expected SHA256 values must be lowercase 64-char hex strings" >&2
      exit 2
    fi
  done

  if ! printf '%s' "${EXPECTED_ARTIFACT_HOST_DIGEST}" | grep -Eq '^sha256:[a-f0-9]{64}$'; then
    echo "ERR EXPECTED_ARTIFACT_HOST_DIGEST must match sha256:<64 hex>" >&2
    exit 2
  fi

  if ! printf '%s' "${EXPECTED_SIGNER_THUMBPRINT}" | grep -Eq '^[A-F0-9]{40}$'; then
    echo "ERR EXPECTED_SIGNER_THUMBPRINT must be uppercase SHA1 thumbprint hex" >&2
    exit 2
  fi

  if ! printf '%s' "${EXPECTED_SIGNER_SHA256_FINGERPRINT}" | grep -Eq '^[A-F0-9]{64}$'; then
    echo "ERR EXPECTED_SIGNER_SHA256_FINGERPRINT must be uppercase SHA256 certificate fingerprint hex" >&2
    exit 2
  fi

  if [[ "${REQUIRE_ARTIFACT_HOST_LIVE_DIGEST}" != "true" && "${REQUIRE_ARTIFACT_HOST_LIVE_DIGEST}" != "false" ]]; then
    echo "ERR REQUIRE_ARTIFACT_HOST_LIVE_DIGEST must be true or false" >&2
    exit 2
  fi

  if [[ "${SELF_UPDATE_AUTO_ACTIVATE}" != "true" && "${SELF_UPDATE_AUTO_ACTIVATE}" != "false" ]]; then
    echo "ERR SELF_UPDATE_AUTO_ACTIVATE must be true or false" >&2
    exit 2
  fi

  if ! printf '%s' "${SELF_UPDATE_HARD_MAX_BYTES}" | grep -Eq '^[1-9][0-9]*$'; then
    echo "ERR SELF_UPDATE_HARD_MAX_BYTES must be a positive integer" >&2
    exit 2
  fi

  if ! printf '%s' "${SELF_UPDATE_MAX_REDIRECTS}" | grep -Eq '^[0-9]+$'; then
    echo "ERR SELF_UPDATE_MAX_REDIRECTS must be a non-negative integer" >&2
    exit 2
  fi

  IFS=',' read -r -a self_update_hosts <<< "${SELF_UPDATE_ALLOWED_HOSTS}"
  if [[ "${#self_update_hosts[@]}" -eq 0 ]]; then
    echo "ERR SELF_UPDATE_ALLOWED_HOSTS must not be empty" >&2
    exit 2
  fi

  for host in "${self_update_hosts[@]}"; do
    if [[ -z "${host}" ]] || [[ "${host}" == *" "* ]] || [[ "${host}" == http* ]] || [[ "${host}" == *"/"* ]] || ! printf '%s' "${host}" | grep -Eq '^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?[.])+[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$'; then
      echo "ERR SELF_UPDATE_ALLOWED_HOSTS contains invalid host: ${host}" >&2
      exit 2
    fi
  done
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
\$SelfUpdateAllowedHosts = "${SELF_UPDATE_ALLOWED_HOSTS}"
\$SelfUpdateSignerThumbprints = "${EXPECTED_SIGNER_SHA256_FINGERPRINT}"
\$SelfUpdateHardMaxBytes = "${SELF_UPDATE_HARD_MAX_BYTES}"
\$SelfUpdateMaxRedirects = "${SELF_UPDATE_MAX_REDIRECTS}"
\$SelfUpdateAutoActivate = "${SELF_UPDATE_AUTO_ACTIVATE}"
\$SelfUpdateActivationTimeout = "${SELF_UPDATE_ACTIVATION_TIMEOUT}"
\$SelfUpdateCommandTimeout = "${SELF_UPDATE_COMMAND_TIMEOUT}"
\$SelfUpdateServiceName = "EndpointAgent"

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

function Read-ServiceEnvMap {
  param([string]\$Path)
  \$raw = (Get-ItemProperty -Path \$Path -Name Environment -ErrorAction SilentlyContinue).Environment
  \$map = [ordered]@{}
  foreach (\$entry in @(\$raw)) {
    \$parts = \$entry -split "=", 2
    if (\$parts.Count -eq 2 -and -not [string]::IsNullOrWhiteSpace(\$parts[0])) {
      \$map[\$parts[0]] = \$parts[1]
    }
  }
  return \$map
}

function Write-ServiceEnvMap {
  param([string]\$Path, \$Map)
  \$entries = @()
  foreach (\$key in \$Map.Keys) {
    \$value = [string]\$Map[\$key]
    if (-not [string]::IsNullOrWhiteSpace(\$value)) {
      \$entries += "\$key=\$value"
    }
  }
  Set-ItemProperty -Path \$Path -Name Environment -Type MultiString -Value \$entries
}

function Set-CanonicalRemoteBridgeServiceEnvironment {
  param([string]\$ServiceName)

  \$serviceKey = "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\\$ServiceName"
  if (-not (Test-Path -Path \$serviceKey)) {
    throw "Service registry key not found: \$serviceKey"
  }

  \$map = Read-ServiceEnvMap -Path \$serviceKey
  \$map["ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED"] = "true"
  \$map["ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR"] = \$RemoteBridgeBrokerAddr
  \$map["ENDPOINT_AGENT_REMOTE_BRIDGE_TLS_SERVER_NAME"] = \$RemoteBridgeTlsServerName
  \$map["ENDPOINT_AGENT_REMOTE_BRIDGE_CERT_SAN_URI_PREFIX"] = \$RemoteBridgeMTLSSanUriPrefix
  \$map["ENDPOINT_AGENT_REMOTE_BRIDGE_MTLS_CERT_SAN_URI_PREFIX"] = \$RemoteBridgeMTLSSanUriPrefix
  \$map["ENDPOINT_AGENT_REMOTE_BRIDGE_OPERATIONS_ENABLED"] = "true"
  \$map["ENDPOINT_AGENT_REMOTE_BRIDGE_PTY_ENABLED"] = "true"
  \$map["ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_PERMIT_PUBLIC_KEY_B64"] = \$RemoteBridgePermitBrokerPublicKeyB64
  \$map["ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_PERMIT_KID"] = \$RemoteBridgePermitKid
  \$map["ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64"] = \$RemoteBridgePermitBrokerPublicKeyB64
  \$map["ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_KEY_ID"] = \$RemoteBridgePermitKid
  \$map["ENDPOINT_AGENT_REMOTE_BRIDGE_PILOT_AUTO_CONSENT"] = "true"

  Write-ServiceEnvMap -Path \$serviceKey -Map \$map
}

function Set-CanonicalSelfUpdateServiceEnvironment {
  param([string]\$ServiceName)

  \$serviceKey = "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\\$ServiceName"
  if (-not (Test-Path -Path \$serviceKey)) {
    throw "Service registry key not found: \$serviceKey"
  }

  \$map = Read-ServiceEnvMap -Path \$serviceKey
  \$map["ENDPOINT_AGENT_SELF_UPDATE_ENABLED"] = "true"
  \$map["ENDPOINT_AGENT_SELF_UPDATE_ALLOWED_HOSTS"] = \$SelfUpdateAllowedHosts
  \$map["ENDPOINT_AGENT_SELF_UPDATE_SIGNER_THUMBPRINTS"] = \$SelfUpdateSignerThumbprints
  \$map["ENDPOINT_AGENT_SELF_UPDATE_HARD_MAX_BYTES"] = \$SelfUpdateHardMaxBytes
  \$map["ENDPOINT_AGENT_SELF_UPDATE_MAX_REDIRECTS"] = \$SelfUpdateMaxRedirects
  \$map["ENDPOINT_AGENT_SELF_UPDATE_AUTO_ACTIVATE"] = \$SelfUpdateAutoActivate
  \$map["ENDPOINT_AGENT_SELF_UPDATE_ACTIVATION_TIMEOUT"] = \$SelfUpdateActivationTimeout
  \$map["ENDPOINT_AGENT_SELF_UPDATE_SERVICE_NAME"] = \$SelfUpdateServiceName
  \$map["ENDPOINT_AGENT_SELF_UPDATE_COMMAND_TIMEOUT"] = \$SelfUpdateCommandTimeout

  Write-ServiceEnvMap -Path \$serviceKey -Map \$map
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
    "-RemoteBridgePilotAutoConsent",
    "-SelfUpdateEnabled",
    "-SelfUpdateAllowedHosts", \$SelfUpdateAllowedHosts,
    "-SelfUpdateSignerThumbprints", \$SelfUpdateSignerThumbprints,
    "-SelfUpdateHardMaxBytes", \$SelfUpdateHardMaxBytes,
    "-SelfUpdateMaxRedirects", \$SelfUpdateMaxRedirects,
    "-SelfUpdateAutoActivate",
    "-SelfUpdateActivationTimeout", \$SelfUpdateActivationTimeout,
    "-SelfUpdateServiceName", \$SelfUpdateServiceName,
    "-SelfUpdateCommandTimeout", \$SelfUpdateCommandTimeout,
    "-ServiceStartTimeoutSeconds", "90",
    "-Force",
    "-Start"
  )
  & powershell.exe @installArgs

  if (\$LASTEXITCODE -ne 0) {
    throw "install.ps1 exited with code \$LASTEXITCODE"
  }

  Write-Step "patch canonical remote bridge service environment"
  Set-CanonicalRemoteBridgeServiceEnvironment -ServiceName "EndpointAgent"

  Write-Step "patch signed self-update service environment"
  Set-CanonicalSelfUpdateServiceEnvironment -ServiceName "EndpointAgent"

  Write-Step "restart EndpointAgent with canonical remote bridge and self-update environment"
  Restart-Service EndpointAgent -Force

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
      ptyEnabled = \$true
      pilotAutoConsent = \$true
      permitKeyId = \$RemoteBridgePermitKid
      permitBrokerPublicKeySha256 = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::ASCII.GetBytes(\$RemoteBridgePermitBrokerPublicKeyB64))).Replace("-", "").ToLowerInvariant()
    }
    selfUpdate = @{
      enabled = \$true
      allowedHosts = \$SelfUpdateAllowedHosts
      signerThumbprintsConfigured = 1
      hardMaxBytes = \$SelfUpdateHardMaxBytes
      maxRedirects = \$SelfUpdateMaxRedirects
      autoActivate = \$SelfUpdateAutoActivate
      activationTimeout = \$SelfUpdateActivationTimeout
      serviceName = \$SelfUpdateServiceName
      commandTimeout = \$SelfUpdateCommandTimeout
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
        "EndpointAgent service install/start attempted with immutable \$ReleaseId binary hash",
        "Outbound remote bridge configuration written for 443/SNI broker",
        "Canonical constrained-PTY and owner-gated pilot auto-consent service environment written",
        "Signed self-update local trust policy written so UPDATE_AGENT can be advertised"
      )
      doesNotProve = @(
        "platform-agent#208 constrained operation acceptance",
        "UPDATE_AGENT product dispatch succeeded",
        "Agent version changed through product self-update",
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

write_canonical_env_patch_script() {
  local permit_public_key_b64="$1"

  cat > "${CANONICAL_ENV_PATCH_PS1}" <<EOF
<#
.SYNOPSIS
AgentPC2 remote-bridge canonical environment patch v7.

.DESCRIPTION
Migrates the EndpointAgent service Environment from earlier pilot alias names to
the canonical remote-bridge keys for ${RELEASE_ID}, enables bounded CONSTRAINED_PTY
operation handling, and enables owner-gated pilot auto-consent for the AgentPC2
lab acceptance lane. It contains no private key, bearer token, password,
administrator credential, or HMAC enrollment token.
#>

[CmdletBinding()]
param(
  [string]\$EvidenceRoot = "C:\\ProgramData\\EndpointAgent\\rollout-evidence",
  [int]\$PostRestartWaitSeconds = 90
)

Set-StrictMode -Version Latest
\$ErrorActionPreference = "Stop"
\$ProgressPreference = "SilentlyContinue"

\$PatchId = "agentpc2-remote-bridge-canonical-env-v7"
\$StartedAt = Get-Date
\$ServiceName = "EndpointAgent"
\$ServiceKey = "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\\$ServiceName"
\$BinaryPath = "C:\\Program Files\\EndpointAgent\\endpoint-agent.exe"
\$ExpectedAgentSha256 = "${EXPECTED_AGENT_SHA256}"
\$RemoteBridgeBrokerAddr = "${REMOTE_BRIDGE_BROKER_ADDR}"
\$RemoteBridgeTlsServerName = "${REMOTE_BRIDGE_HOSTNAME}"
\$RemoteBridgeMTLSSanUriPrefix = "${REMOTE_BRIDGE_MTLS_SAN_URI_PREFIX}"
\$RemoteBridgePermitKid = "${REMOTE_BRIDGE_PERMIT_KID}"
\$RemoteBridgePermitBrokerPublicKeyB64 = @'
${permit_public_key_b64}
'@.Trim()
\$SelfUpdateAllowedHosts = "${SELF_UPDATE_ALLOWED_HOSTS}"
\$SelfUpdateSignerThumbprints = "${EXPECTED_SIGNER_SHA256_FINGERPRINT}"
\$SelfUpdateHardMaxBytes = "${SELF_UPDATE_HARD_MAX_BYTES}"
\$SelfUpdateMaxRedirects = "${SELF_UPDATE_MAX_REDIRECTS}"
\$SelfUpdateAutoActivate = "${SELF_UPDATE_AUTO_ACTIVATE}"
\$SelfUpdateActivationTimeout = "${SELF_UPDATE_ACTIVATION_TIMEOUT}"
\$SelfUpdateCommandTimeout = "${SELF_UPDATE_COMMAND_TIMEOUT}"
\$SelfUpdateServiceName = "EndpointAgent"

function Write-Step {
  param([string]\$Message)
  Write-Host "[\$PatchId] \$Message"
}

function Assert-Administrator {
  \$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  \$principal = New-Object Security.Principal.WindowsPrincipal(\$identity)
  if (-not \$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Administrator shell required."
  }
}

function Read-ServiceEnvMap {
  param([string]\$Path)
  \$raw = (Get-ItemProperty -Path \$Path -Name Environment -ErrorAction SilentlyContinue).Environment
  \$map = [ordered]@{}
  foreach (\$entry in @(\$raw)) {
    \$parts = \$entry -split "=", 2
    if (\$parts.Count -eq 2 -and -not [string]::IsNullOrWhiteSpace(\$parts[0])) {
      \$map[\$parts[0]] = \$parts[1]
    }
  }
  return \$map
}

function Write-ServiceEnvMap {
  param([string]\$Path, \$Map)
  \$entries = @()
  foreach (\$key in \$Map.Keys) {
    \$value = [string]\$Map[\$key]
    if (-not [string]::IsNullOrWhiteSpace(\$value)) {
      \$entries += "\$key=\$value"
    }
  }
  Set-ItemProperty -Path \$Path -Name Environment -Type MultiString -Value \$entries
}

function Redact-ServiceEnvMap {
  param(\$Map)
  \$rows = @()
  foreach (\$key in (\$Map.Keys | Sort-Object)) {
    \$value = [string]\$Map[\$key]
    \$sensitive = \$key -match "TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL|KID|ATTESTATION"
    \$rows += [PSCustomObject]@{
      Key = \$key
      Present = -not [string]::IsNullOrWhiteSpace(\$value)
      Length = \$value.Length
      Value = if (\$sensitive) { "<redacted>" } else { \$value }
    }
  }
  return \$rows
}

function Get-RemoteBridgeSignals {
  Get-Content "C:\\ProgramData\\EndpointAgent\\logs\\*.log" -Tail 1200 -ErrorAction SilentlyContinue |
    Select-String -Pattern "remote-bridge|bridge|mtls|mTLS|hello|HELLO|consent|CONSENT|active|ACTIVE|permit|operation|CONSTRAINED|error|failed|denied|certificate|${REMOTE_BRIDGE_HOSTNAME}" |
    ForEach-Object { \$_.Line }
}

New-Item -ItemType Directory -Force -Path \$EvidenceRoot | Out-Null
\$SummaryPath = Join-Path \$EvidenceRoot "agentpc2-remote-bridge-canonical-env-patch-v7-summary.json"
\$SignalsPath = Join-Path \$EvidenceRoot "agentpc2-remote-bridge-canonical-env-patch-v7-signals.txt"

Assert-Administrator
if (-not (Test-Path -Path \$ServiceKey)) { throw "Service registry key not found: \$ServiceKey" }
if (-not (Test-Path -Path \$BinaryPath)) { throw "EndpointAgent binary not found: \$BinaryPath" }

\$actualAgentSha256 = (Get-FileHash -Path \$BinaryPath -Algorithm SHA256).Hash.ToLowerInvariant()
if (\$actualAgentSha256 -ne \$ExpectedAgentSha256) {
  throw "EndpointAgent binary SHA256 mismatch expected=\$ExpectedAgentSha256 actual=\$actualAgentSha256"
}

Write-Step "read service environment"
\$map = Read-ServiceEnvMap -Path \$ServiceKey

Write-Step "write canonical remote bridge keys"
\$map["ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED"] = "true"
\$map["ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR"] = \$RemoteBridgeBrokerAddr
\$map["ENDPOINT_AGENT_REMOTE_BRIDGE_TLS_SERVER_NAME"] = \$RemoteBridgeTlsServerName
\$map["ENDPOINT_AGENT_REMOTE_BRIDGE_CERT_SAN_URI_PREFIX"] = \$RemoteBridgeMTLSSanUriPrefix
\$map["ENDPOINT_AGENT_REMOTE_BRIDGE_MTLS_CERT_SAN_URI_PREFIX"] = \$RemoteBridgeMTLSSanUriPrefix
\$map["ENDPOINT_AGENT_REMOTE_BRIDGE_OPERATIONS_ENABLED"] = "true"
\$map["ENDPOINT_AGENT_REMOTE_BRIDGE_PTY_ENABLED"] = "true"
\$map["ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_PERMIT_PUBLIC_KEY_B64"] = \$RemoteBridgePermitBrokerPublicKeyB64
\$map["ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_PERMIT_KID"] = \$RemoteBridgePermitKid
\$map["ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64"] = \$RemoteBridgePermitBrokerPublicKeyB64
\$map["ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_KEY_ID"] = \$RemoteBridgePermitKid
\$map["ENDPOINT_AGENT_REMOTE_BRIDGE_PILOT_AUTO_CONSENT"] = "true"

Write-Step "write canonical signed self-update keys"
\$map["ENDPOINT_AGENT_SELF_UPDATE_ENABLED"] = "true"
\$map["ENDPOINT_AGENT_SELF_UPDATE_ALLOWED_HOSTS"] = \$SelfUpdateAllowedHosts
\$map["ENDPOINT_AGENT_SELF_UPDATE_SIGNER_THUMBPRINTS"] = \$SelfUpdateSignerThumbprints
\$map["ENDPOINT_AGENT_SELF_UPDATE_HARD_MAX_BYTES"] = \$SelfUpdateHardMaxBytes
\$map["ENDPOINT_AGENT_SELF_UPDATE_MAX_REDIRECTS"] = \$SelfUpdateMaxRedirects
\$map["ENDPOINT_AGENT_SELF_UPDATE_AUTO_ACTIVATE"] = \$SelfUpdateAutoActivate
\$map["ENDPOINT_AGENT_SELF_UPDATE_ACTIVATION_TIMEOUT"] = \$SelfUpdateActivationTimeout
\$map["ENDPOINT_AGENT_SELF_UPDATE_SERVICE_NAME"] = \$SelfUpdateServiceName
\$map["ENDPOINT_AGENT_SELF_UPDATE_COMMAND_TIMEOUT"] = \$SelfUpdateCommandTimeout

Write-ServiceEnvMap -Path \$ServiceKey -Map \$map

Write-Step "restart EndpointAgent"
Restart-Service \$ServiceName -Force
Start-Sleep -Seconds \$PostRestartWaitSeconds

\$service = Get-CimInstance Win32_Service |
  Where-Object { \$_.Name -eq \$ServiceName } |
  Select-Object Name, DisplayName, State, StartMode, StartName, PathName

\$patchedMap = Read-ServiceEnvMap -Path \$ServiceKey
\$signals = @(Get-RemoteBridgeSignals)
\$signals | Set-Content -Path \$SignalsPath -Encoding UTF8

\$requiredKeys = @(
  "ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_CERT_SAN_URI_PREFIX",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_PTY_ENABLED",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_PERMIT_PUBLIC_KEY_B64",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_PERMIT_KID",
  "ENDPOINT_AGENT_REMOTE_BRIDGE_PILOT_AUTO_CONSENT",
  "ENDPOINT_AGENT_SELF_UPDATE_ENABLED",
  "ENDPOINT_AGENT_SELF_UPDATE_ALLOWED_HOSTS",
  "ENDPOINT_AGENT_SELF_UPDATE_SIGNER_THUMBPRINTS",
  "ENDPOINT_AGENT_SELF_UPDATE_HARD_MAX_BYTES",
  "ENDPOINT_AGENT_SELF_UPDATE_MAX_REDIRECTS",
  "ENDPOINT_AGENT_SELF_UPDATE_AUTO_ACTIVATE",
  "ENDPOINT_AGENT_SELF_UPDATE_SERVICE_NAME"
)
\$missing = @(\$requiredKeys | Where-Object {
  -not \$patchedMap.Contains(\$_) -or [string]::IsNullOrWhiteSpace([string]\$patchedMap[\$_])
})

\$completedAt = Get-Date
[PSCustomObject]@{
  schema = "faz22.1768.agentpc2-remote-bridge-canonical-env-patch.v1"
  patchId = \$PatchId
  status = if (\$missing.Count -eq 0 -and \$service -and \$service.State -eq "Running") { "patched-service-running" } else { "patched-needs-attention" }
  startedAt = \$StartedAt.ToString("o")
  completedAt = \$completedAt.ToString("o")
  computerName = \$env:COMPUTERNAME
  user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
  localBinary = @{ path = \$BinaryPath; sha256 = \$actualAgentSha256 }
  service = \$service
  selfUpdate = @{
    enabled = \$patchedMap["ENDPOINT_AGENT_SELF_UPDATE_ENABLED"]
    allowedHosts = \$patchedMap["ENDPOINT_AGENT_SELF_UPDATE_ALLOWED_HOSTS"]
    signerThumbprintsConfigured = if ([string]::IsNullOrWhiteSpace([string]\$patchedMap["ENDPOINT_AGENT_SELF_UPDATE_SIGNER_THUMBPRINTS"])) { 0 } else { 1 }
    hardMaxBytes = \$patchedMap["ENDPOINT_AGENT_SELF_UPDATE_HARD_MAX_BYTES"]
    maxRedirects = \$patchedMap["ENDPOINT_AGENT_SELF_UPDATE_MAX_REDIRECTS"]
    autoActivate = \$patchedMap["ENDPOINT_AGENT_SELF_UPDATE_AUTO_ACTIVATE"]
    serviceName = \$patchedMap["ENDPOINT_AGENT_SELF_UPDATE_SERVICE_NAME"]
    commandTimeout = \$patchedMap["ENDPOINT_AGENT_SELF_UPDATE_COMMAND_TIMEOUT"]
  }
  missingCanonicalKeys = \$missing
  redactedServiceEnvironment = @(Redact-ServiceEnvMap -Map \$patchedMap)
  evidence = @{ root = \$EvidenceRoot; signals = \$SignalsPath }
  boundary = @{
    proves = @(
      "EndpointAgent ${RELEASE_ID} binary digest matches expected release digest",
      "Canonical constrained-PTY remote-bridge service environment is present",
      "Owner-gated pilot auto-consent is enabled for bounded AgentPC2 lab acceptance",
      "Signed self-update local trust policy is present so UPDATE_AGENT can be advertised",
      "EndpointAgent service restart attempted after canonical env patch"
    )
    doesNotProve = @(
      "platform-agent#208 constrained operation acceptance",
      "UPDATE_AGENT product dispatch succeeded",
      "Agent version changed through product self-update",
      "broker permit issuance",
      "typed operation execution",
      "production/domain-wide support readiness",
      "unrestricted shell/RDP/WinRM/SMB/SSH readiness"
    )
  }
} | ConvertTo-Json -Depth 8 | Set-Content -Path \$SummaryPath -Encoding UTF8

Write-Step "summary: \$SummaryPath"
Get-Content \$SummaryPath

if (\$missing.Count -gt 0) { throw "Missing canonical remote-bridge keys: \$(\$missing -join ', ')" }
if (-not \$service -or \$service.State -ne "Running") { throw "EndpointAgent is not running after patch." }

Write-Step "completed"
EOF

  chmod 0644 "${CANONICAL_ENV_PATCH_PS1}"
}

write_readme() {
  cat > "${README_PATH}" <<EOF
# AgentPC2 first-install bootstrap package

This package was generated by scripts/faz22-remote-ops/agentpc2-first-install-bootstrap-gate.sh.

Purpose:
- Move AgentPC2 to EndpointAgent ${RELEASE_ID} when the currently installed agent does not advertise \`UPDATE_AGENT\`.
- Preserve the product remote-ops acceptance boundary: this package is only a bootstrap step, not #208 acceptance.
- Use outbound-only remote bridge configuration over ${REMOTE_BRIDGE_BROKER_ADDR}.
- Enable the signed, host-bounded EndpointAgent self-update policy required for
  the product \`UPDATE_AGENT\` capability.
- Publish an endpoint-local v7 migration patch for already-installed ${RELEASE_ID}
  endpoints that still carry earlier remote-bridge env aliases or lack the
  signed self-update local policy.

Run on AgentPC2 from an elevated PowerShell session:

    \$ErrorActionPreference = "Stop"
    \$ProgressPreference = "SilentlyContinue"
    \$Base = "https://testai.acik.com/artifacts/endpoint-agent/bootstrap"
    \$WorkDir = "C:\\Temp\\AgentPC2Bootstrap"
    \$Script = Join-Path \$WorkDir "agentpc2-first-install-bootstrap.ps1"
    \$ExpectedScriptSha256 = "<see SHA256SUMS>"
    New-Item -ItemType Directory -Force \$WorkDir | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri "\$Base/agentpc2-first-install-bootstrap.ps1" -OutFile \$Script
    \$ActualScriptSha256 = (Get-FileHash \$Script -Algorithm SHA256).Hash.ToLowerInvariant()
    if (\$ActualScriptSha256 -ne \$ExpectedScriptSha256) { throw "Bootstrap script SHA256 mismatch: \$ActualScriptSha256" }
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File \$Script

If AgentPC2 already has EndpointAgent ${RELEASE_ID} installed but the product
smoke still returns \`session-not-active\` or \`UPDATE_AGENT\` is not advertised,
run the bounded canonical env patch instead:

    \$ErrorActionPreference = "Stop"
    \$ProgressPreference = "SilentlyContinue"
    \$Base = "https://testai.acik.com/artifacts/endpoint-agent/bootstrap"
    \$WorkDir = "C:\\Temp\\AgentPC2Bootstrap"
    \$Script = Join-Path \$WorkDir "agentpc2-remote-bridge-canonical-env-patch-v7.ps1"
    \$ExpectedScriptSha256 = "<see SHA256SUMS>"
    New-Item -ItemType Directory -Force \$WorkDir | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri "\$Base/agentpc2-remote-bridge-canonical-env-patch-v7.ps1" -OutFile \$Script
    \$ActualScriptSha256 = (Get-FileHash \$Script -Algorithm SHA256).Hash.ToLowerInvariant()
    if (\$ActualScriptSha256 -ne \$ExpectedScriptSha256) { throw "Patch script SHA256 mismatch: \$ActualScriptSha256" }
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File \$Script

Endpoint evidence will be written under:

    C:\\ProgramData\\EndpointAgent\\rollout-evidence

The scripts contain no HMAC enrollment token, bearer token, password, private
key, or administrator credential. They contain the broker permit public key,
which is intentionally public verifier material.

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
    --arg signerSha256Fingerprint "${EXPECTED_SIGNER_SHA256_FINGERPRINT}" \
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
    --arg selfUpdateAllowedHosts "${SELF_UPDATE_ALLOWED_HOSTS}" \
    --arg selfUpdateHardMaxBytes "${SELF_UPDATE_HARD_MAX_BYTES}" \
    --arg selfUpdateMaxRedirects "${SELF_UPDATE_MAX_REDIRECTS}" \
    --arg selfUpdateAutoActivate "${SELF_UPDATE_AUTO_ACTIVATE}" \
    --arg selfUpdateActivationTimeout "${SELF_UPDATE_ACTIVATION_TIMEOUT}" \
    --arg selfUpdateCommandTimeout "${SELF_UPDATE_COMMAND_TIMEOUT}" \
    --arg evidenceDir "${EVIDENCE_DIR}" \
    --arg bootstrapScript "${BOOTSTRAP_PS1}" \
    --arg canonicalEnvPatchScript "${CANONICAL_ENV_PATCH_PS1}" \
    --arg readme "${README_PATH}" \
    --argjson proves "$(write_json_string_array \
      "${RELEASE_ID} release manifest/install/bootstrap hashes verified" \
      "Broker permit public key derived from live signer source or explicit public-key override" \
      "Endpoint-local first-install script generated with outbound-only 443/SNI remote bridge configuration" \
      "Endpoint-local first-install and canonical env scripts generated with signed self-update local policy" \
      "No inbound endpoint management port is required by this bootstrap package")" \
    --argjson doesNotProve "$(write_json_string_array \
      "platform-agent#208 constrained executor acceptance" \
      "AgentPC2 endpoint actually executed the bootstrap script" \
      "UPDATE_AGENT product dispatch succeeded" \
      "Agent version changed through product self-update" \
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
        signer:{thumbprint:$signerThumbprint, sha256Fingerprint:$signerSha256Fingerprint, tier:$signingTier},
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
      selfUpdate:{
        enabled:true,
        allowedHosts:$selfUpdateAllowedHosts,
        signerThumbprintsConfigured:1,
        signerFingerprintAlgorithm:"sha256(cert.Raw)",
        hardMaxBytes:$selfUpdateHardMaxBytes,
        maxRedirects:$selfUpdateMaxRedirects,
        autoActivate:$selfUpdateAutoActivate,
        activationTimeout:$selfUpdateActivationTimeout,
        serviceName:"EndpointAgent",
        commandTimeout:$selfUpdateCommandTimeout
      },
      evidence:{dir:$evidenceDir, bootstrapScript:$bootstrapScript, canonicalEnvPatchScript:$canonicalEnvPatchScript, readme:$readme},
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
  validate_release_inputs

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
    echo "ERR release manifest did not match expected ${RELEASE_ID} immutable metadata" >&2
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
  if [[ "${REQUIRE_ARTIFACT_HOST_LIVE_DIGEST}" == "true" ]]; then
    need_cmd kubectl
    set +e
    kubectl --context "${K8S_CONTEXT}" -n "${K8S_NAMESPACE}" get deploy artifact-host -o json \
      > "${EVIDENCE_DIR}/artifact-host-deployment.json" 2>"${EVIDENCE_DIR}/artifact-host-deployment.err"
    local kubectl_status=$?
    set -e
    if [[ "${kubectl_status}" != "0" ]]; then
      echo "ERR could not read live artifact-host deployment for digest assertion" >&2
      cat "${EVIDENCE_DIR}/artifact-host-deployment.err" >&2 || true
      exit 3
    fi
    artifact_image="$(jq -r '.spec.template.spec.containers[0].image // ""' "${EVIDENCE_DIR}/artifact-host-deployment.json")"
    artifact_ready="$(jq -r '.status.readyReplicas // 0' "${EVIDENCE_DIR}/artifact-host-deployment.json")"
    if [[ "${artifact_image}" != *"@${EXPECTED_ARTIFACT_HOST_DIGEST}" ]]; then
      echo "ERR live artifact-host image digest mismatch: expected ${EXPECTED_ARTIFACT_HOST_DIGEST}, got ${artifact_image}" >&2
      exit 3
    fi
    if [[ "${artifact_ready}" == "0" || -z "${artifact_ready}" ]]; then
      echo "ERR live artifact-host has no ready replicas" >&2
      exit 3
    fi
  elif command -v kubectl >/dev/null 2>&1; then
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
  write_canonical_env_patch_script "${permit_public_key_b64}"
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
