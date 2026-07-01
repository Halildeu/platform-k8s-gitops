#!/usr/bin/env bash
# Build the non-secret AgentPC2 endpoint-local TPM auto-enroll packet for
# Faz 22.6 #548. The generated PowerShell script never embeds an enrollment
# token; it requires the operator/automation to inject the test token through
# the process environment on the endpoint.

set -euo pipefail

OUT_DIR="${OUT_DIR:-}"
API_URL="${API_URL:-https://testai.acik.com/api/v1/endpoint-agent}"
TARGET_HOSTNAME="${TARGET_HOSTNAME:-AgentPc2}"
TARGET_PRODUCT_DEVICE_ID="${TARGET_PRODUCT_DEVICE_ID:-2f7ad30f-970a-42e7-8af8-08764ae6066f}"
ENDPOINT_AGENT_EXE="${ENDPOINT_AGENT_EXE:-C:\\Program Files\\EndpointAgent\\endpoint-agent.exe}"
BROKER_HOST="${BROKER_HOST:-remote-bridge-mtls.testai.acik.com}"

usage() {
  cat <<'EOF'
Usage:
  faz22-6-agentpc2-tpm-autoenroll-packet.sh [options]

Options:
  --out-dir PATH                  Output directory. Defaults to /tmp/faz22-6-agentpc2-tpm-autoenroll-<utc>.
  --api-url URL                   TPM enroll API base URL, e.g. https://testai.acik.com/api/v1/endpoint-agent.
                                  The agent appends /enrollments/tpm/{nonce,attest}.
  --target-hostname HOSTNAME      Endpoint hostname. Default: AgentPc2.
  --target-product-device-id UUID Product device UUID. Default: current AgentPC2 UUID.
  --endpoint-agent-exe PATH       Windows endpoint-agent.exe path used by the generated script.
  --broker-host HOST              Dedicated device-key broker SNI for follow-up evidence.

The packet is non-secret. It does not include enrollment tokens, bearer tokens,
private keys, cookies, or raw credentials.
EOF
}

die() {
  printf 'agentpc2-tpm-packet: %s\n' "$*" >&2
  exit 2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --out-dir) [ "$#" -ge 2 ] || die "--out-dir needs a value"; OUT_DIR="$2"; shift 2 ;;
    --api-url) [ "$#" -ge 2 ] || die "--api-url needs a value"; API_URL="$2"; shift 2 ;;
    --target-hostname) [ "$#" -ge 2 ] || die "--target-hostname needs a value"; TARGET_HOSTNAME="$2"; shift 2 ;;
    --target-product-device-id) [ "$#" -ge 2 ] || die "--target-product-device-id needs a value"; TARGET_PRODUCT_DEVICE_ID="$2"; shift 2 ;;
    --endpoint-agent-exe) [ "$#" -ge 2 ] || die "--endpoint-agent-exe needs a value"; ENDPOINT_AGENT_EXE="$2"; shift 2 ;;
    --broker-host) [ "$#" -ge 2 ] || die "--broker-host needs a value"; BROKER_HOST="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

reject_multiline() {
  local name="$1" value="$2"
  case "$value" in
    *$'\n'*|*$'\r'*) die "$name must be a single line" ;;
  esac
}

for pair in \
  "api-url:$API_URL" \
  "target-hostname:$TARGET_HOSTNAME" \
  "target-product-device-id:$TARGET_PRODUCT_DEVICE_ID" \
  "endpoint-agent-exe:$ENDPOINT_AGENT_EXE" \
  "broker-host:$BROKER_HOST"; do
  reject_multiline "${pair%%:*}" "${pair#*:}"
done

case "$API_URL" in
  https://*) ;;
  *) die "--api-url must be https" ;;
esac
case "$API_URL" in
  *\?*|*#*) die "--api-url must not contain query or fragment" ;;
esac
if ! printf '%s' "$TARGET_PRODUCT_DEVICE_ID" | grep -Eq '^[0-9a-fA-F-]{36}$'; then
  die "--target-product-device-id must look like a UUID"
fi
if [ -z "$TARGET_HOSTNAME" ] || [ "${#TARGET_HOSTNAME}" -gt 253 ] \
  || ! printf '%s' "$TARGET_HOSTNAME" | grep -Eq '^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)([.][A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$'; then
  die "--target-hostname must be a DNS-safe hostname label/FQDN"
fi
if [ -z "$BROKER_HOST" ] || [ "${#BROKER_HOST}" -gt 253 ] \
  || ! printf '%s' "$BROKER_HOST" | grep -Eq '^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)([.][A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$'; then
  die "--broker-host must be a DNS-safe hostname/FQDN"
fi

if [ -z "$OUT_DIR" ]; then
  OUT_DIR="/tmp/faz22-6-agentpc2-tpm-autoenroll-$(date -u +%Y%m%dT%H%M%SZ)"
fi
mkdir -p "$OUT_DIR"

packet_ps1="$OUT_DIR/agentpc2-tpm-autoenroll.ps1"
runner_ps1="$OUT_DIR/agentpc2-tpm-autoenroll-runner.ps1"
readme="$OUT_DIR/README.md"
manifest="$OUT_DIR/packet-manifest.json"

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

cat >"$packet_ps1" <<'EOF_PS1'
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [ValidatePattern('^https://')]
  [string]$ApiUrl,

  [Parameter(Mandatory=$true)]
  [string]$TargetProductDeviceId,

  [string]$EndpointAgentExe = 'C:\Program Files\EndpointAgent\endpoint-agent.exe',
  [string]$EvidenceDir = "$env:ProgramData\EndpointAgent\faz22-6-tpm-autoenroll-evidence",
  [switch]$NoRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
  Write-Host "[faz22.6-tpm] $Message"
}

function Get-Sha256File([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Redact-Line([string]$Line) {
  if ($null -eq $Line) { return $Line }
  $out = $Line
  $out = $out -replace '(?i)(token|secret|password|bearer)[=: ][^ ]+', '$1=<redacted>'
  $out = $out -replace '(?i)authorization: .*$', 'authorization: <redacted>'
  return $out
}

function Write-JsonFile($Object, [string]$Path) {
  $Object | ConvertTo-Json -Depth 8 | Out-File -LiteralPath $Path -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$summaryPath = Join-Path $EvidenceDir 'agentpc2-tpm-autoenroll-summary.json'
$stdoutPath = Join-Path $EvidenceDir 'endpoint-agent-tpm-autoenroll-stdout.txt'
$stderrPath = Join-Path $EvidenceDir 'endpoint-agent-tpm-autoenroll-stderr.txt'
$tpmInfoPath = Join-Path $EvidenceDir 'tpmtool-deviceinformation.txt'
$ekInfoPath = Join-Path $EvidenceDir 'ek-certificate-summary.json'

$token = [Environment]::GetEnvironmentVariable('ENDPOINT_AGENT_ENROLLMENT_TOKEN', 'Process')
if ([string]::IsNullOrWhiteSpace($token)) {
  throw 'ENDPOINT_AGENT_ENROLLMENT_TOKEN must be present in the current process environment. Do not pass it on the command line and do not write it into this script.'
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
  throw 'Run from an elevated PowerShell session. TPM and LocalMachine certificate evidence require administrator context.'
}

if (-not (Test-Path -LiteralPath $EndpointAgentExe)) {
  throw "endpoint-agent.exe not found at $EndpointAgentExe"
}

Write-Step 'collect TPM attestation capability'
$tpmToolText = (& tpmtool getdeviceinformation 2>&1 | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
$tpmToolText | Out-File -LiteralPath $tpmInfoPath -Encoding UTF8

$ek = Get-TpmEndorsementKeyInfo -Hash Sha256
$manufacturerCertCount = 0
if ($null -ne $ek.ManufacturerCertificates) {
  $manufacturerCertCount = @($ek.ManufacturerCertificates).Count
}
$ekSubjects = @()
$ekIssuers = @()
if ($manufacturerCertCount -gt 0) {
  foreach ($cert in @($ek.ManufacturerCertificates)) {
    $ekSubjects += $cert.Subject
    $ekIssuers += $cert.Issuer
  }
}
Write-JsonFile ([ordered]@{
  manufacturerCertCount = $manufacturerCertCount
  subjects = $ekSubjects
  issuers = $ekIssuers
}) $ekInfoPath

if ($manufacturerCertCount -lt 1) {
  throw 'TPM manufacturer EK certificate is missing. This endpoint cannot produce the #548 hardware-attestation marker.'
}
if ($tpmToolText -match 'Is Capable For Attestation:\s*False') {
  throw 'TPM reports Is Capable For Attestation: False.'
}
if ($tpmToolText -match 'Ready For Attestation:\s*False') {
  throw 'TPM reports Ready For Attestation: False.'
}

$certPath = Join-Path $env:ProgramData 'EndpointAgent\tpm-client-cert.pem'
$beforeCertSha = Get-Sha256File $certPath
$exitCode = $null

if ($NoRun) {
  Write-Step 'NoRun set; skipped endpoint-agent --auto-enroll-tpm execution'
} else {
  Write-Step 'run endpoint-agent --auto-enroll-tpm with process-env token injection'
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $EndpointAgentExe
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.Arguments = '--auto-enroll-tpm --api-url ' + $ApiUrl.TrimEnd('/')
  $psi.EnvironmentVariables['ENDPOINT_AGENT_ENROLLMENT_TOKEN'] = $token

  $proc = New-Object System.Diagnostics.Process
  $proc.StartInfo = $psi
  [void]$proc.Start()
  $stdout = $proc.StandardOutput.ReadToEnd()
  $stderr = $proc.StandardError.ReadToEnd()
  $proc.WaitForExit()
  $exitCode = $proc.ExitCode

  ($stdout -split "`r?`n" | ForEach-Object { Redact-Line $_ }) |
    Out-File -LiteralPath $stdoutPath -Encoding UTF8
  ($stderr -split "`r?`n" | ForEach-Object { Redact-Line $_ }) |
    Out-File -LiteralPath $stderrPath -Encoding UTF8

  [Environment]::SetEnvironmentVariable('ENDPOINT_AGENT_ENROLLMENT_TOKEN', $null, 'Process')
  Remove-Item Env:\ENDPOINT_AGENT_ENROLLMENT_TOKEN -ErrorAction SilentlyContinue

  if ($exitCode -ne 0) {
    throw "endpoint-agent --auto-enroll-tpm exited with code $exitCode. Redacted stderr is at $stderrPath"
  }
}

$afterCertSha = Get-Sha256File $certPath
$certSummary = $null
if (Test-Path -LiteralPath $certPath) {
  $pem = Get-Content -LiteralPath $certPath -Raw
  $base64 = ($pem -replace '-----BEGIN CERTIFICATE-----','' -replace '-----END CERTIFICATE-----','' -replace '\s','')
  $cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new([Convert]::FromBase64String($base64))
  $certSummary = [ordered]@{
    subject = $cert.Subject
    issuer = $cert.Issuer
    notBeforeUtc = $cert.NotBefore.ToUniversalTime().ToString('o')
    notAfterUtc = $cert.NotAfter.ToUniversalTime().ToString('o')
    thumbprint = $cert.Thumbprint
    pemSha256 = $afterCertSha
  }
}

$summary = [ordered]@{
  schema = 'faz22.6.agentpc2.tpm-autoenroll.endpoint-evidence.v1'
  generatedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
  targetProductDeviceId = $TargetProductDeviceId
  apiUrl = $ApiUrl.TrimEnd('/')
  endpointAgentExe = $EndpointAgentExe
  noRun = [bool]$NoRun
  exitCode = $exitCode
  tpm = [ordered]@{
    tpmtoolEvidence = $tpmInfoPath
    ekSummaryEvidence = $ekInfoPath
    manufacturerCertCount = $manufacturerCertCount
  }
  certificate = $certSummary
  certificateSha256Before = $beforeCertSha
  certificateSha256After = $afterCertSha
  secretHygiene = [ordered]@{
    rawEnrollmentTokenLogged = $false
    tokenPassedOnCommandLine = $false
    tokenEmbeddedInScript = $false
    stdoutRedacted = $true
    stderrRedacted = $true
  }
  nextServerSideChecks = @(
    'endpoint_tpm_device_binding row for target device exists',
    'ak_name, ak_pub_sha256, ek_cert_sha256, device_key_spki_sha256 are non-empty',
    'bridge-selected mTLS leaf SPKI equals endpoint_tpm_device_binding.device_key_spki_sha256',
    'dedicated broker session yields deviceTrusted=true and Basis.HARDWARE_KEY_ATTESTATION'
  )
}
Write-JsonFile $summary $summaryPath
Write-Step "summary=$summaryPath"
Write-Step 'endpoint-local TPM auto-enroll evidence collection finished'
EOF_PS1

packet_ps1_sha256="$(sha256_file "$packet_ps1")"

cat >"$runner_ps1" <<EOF_RUNNER_PS1
[CmdletBinding()]
param(
  [string]\$BaseUrl = 'https://testai.acik.com/artifacts/endpoint-agent/bootstrap',
  [string]\$WorkDir = 'C:\Temp\faz22-6-agentpc2-tpm',
  [string]\$ExpectedScriptSha256 = '${packet_ps1_sha256}',
  [string]\$ApiUrl = '${API_URL%/}',
  [string]\$TargetProductDeviceId = '${TARGET_PRODUCT_DEVICE_ID}',
  [string]\$EndpointAgentExe = '${ENDPOINT_AGENT_EXE}'
)

\$ErrorActionPreference = 'Stop'
\$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

function Write-Step([string]\$Message) {
  Write-Host "[faz22.6-tpm-runner] \$Message"
}

function Assert-Administrator {
  \$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  \$principal = New-Object Security.Principal.WindowsPrincipal(\$identity)
  if (-not \$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run from an elevated PowerShell session.'
  }
}

function Clear-ProcessEnrollmentToken {
  [Environment]::SetEnvironmentVariable('ENDPOINT_AGENT_ENROLLMENT_TOKEN', \$null, 'Process')
  Remove-Item Env:\ENDPOINT_AGENT_ENROLLMENT_TOKEN -ErrorAction SilentlyContinue
}

function Write-FileSection([string]\$Title, [string]\$Path) {
  Write-Host ''
  Write-Host "=== \$Title ==="
  if (Test-Path -LiteralPath \$Path) {
    Get-Content -LiteralPath \$Path -ErrorAction SilentlyContinue
  } else {
    Write-Host "[missing] \$Path"
  }
}

function Write-CommandSection([string]\$Title, [scriptblock]\$Command) {
  Write-Host ''
  Write-Host "=== \$Title ==="
  try {
    & \$Command
  } catch {
    \$message = \$_.Exception.Message
    Write-Host "[diagnostic unavailable] \$message"
  }
}

function Write-TpmAutoEnrollDiagnostics {
  \$EvidenceDir = "\$env:ProgramData\EndpointAgent\faz22-6-tpm-autoenroll-evidence"

  Write-Host ''
  Write-Host '=== Evidence dir ==='
  if (Test-Path -LiteralPath \$EvidenceDir) {
    Get-ChildItem -LiteralPath \$EvidenceDir -ErrorAction SilentlyContinue |
      Select-Object Name,Length,LastWriteTime
  } else {
    Write-Host "[missing] \$EvidenceDir"
  }

  Write-FileSection 'endpoint-agent stderr' "\$EvidenceDir\endpoint-agent-tpm-autoenroll-stderr.txt"
  Write-FileSection 'endpoint-agent stdout' "\$EvidenceDir\endpoint-agent-tpm-autoenroll-stdout.txt"
  Write-FileSection 'EK certificate summary' "\$EvidenceDir\ek-certificate-summary.json"
  Write-FileSection 'TPM device information' "\$EvidenceDir\tpmtool-deviceinformation.txt"

  Write-Host ''
  Write-Host '=== endpoint-agent file ==='
  Get-Item -LiteralPath \$EndpointAgentExe -ErrorAction SilentlyContinue |
    Select-Object FullName,Length,LastWriteTime

  Write-CommandSection 'endpoint-agent version' { & \$EndpointAgentExe --version 2>&1 | Select-Object -First 80 }
  Write-CommandSection 'endpoint-agent help' { & \$EndpointAgentExe --help 2>&1 | Select-Object -First 120 }
  Write-CommandSection 'endpoint-agent auto-enroll-tpm help' { & \$EndpointAgentExe --auto-enroll-tpm --help 2>&1 | Select-Object -First 120 }
}

Assert-Administrator
Clear-ProcessEnrollmentToken

\$BaseUrl = \$BaseUrl.TrimEnd('/')
New-Item -ItemType Directory -Force -Path \$WorkDir | Out-Null

\$Script = Join-Path \$WorkDir 'agentpc2-tpm-autoenroll.ps1'
\$Sums = Join-Path \$WorkDir 'SHA256SUMS'

Write-Step 'download TPM auto-enroll script and checksum manifest'
Invoke-WebRequest -UseBasicParsing -Uri "\$BaseUrl/agentpc2-tpm-autoenroll.ps1?cacheBust=\$([Guid]::NewGuid().ToString('N'))" -OutFile \$Script
Invoke-WebRequest -UseBasicParsing -Uri "\$BaseUrl/SHA256SUMS?cacheBust=\$([Guid]::NewGuid().ToString('N'))" -OutFile \$Sums

\$ActualScriptSha256 = (Get-FileHash -LiteralPath \$Script -Algorithm SHA256).Hash.ToLowerInvariant()
if (\$ActualScriptSha256 -ne \$ExpectedScriptSha256) {
  throw "TPM auto-enroll script SHA256 mismatch. actual=\$ActualScriptSha256 expected=\$ExpectedScriptSha256"
}

Get-Content -LiteralPath \$Sums | Select-String 'agentpc2-tpm-autoenroll'

\$SecureToken = \$null
\$Bstr = [IntPtr]::Zero
\$EndpointPacketStarted = \$false
try {
  \$SecureToken = Read-Host -Prompt 'Paste approved FRESH TEST ENDPOINT_AGENT_ENROLLMENT_TOKEN' -AsSecureString
  if (\$SecureToken.Length -lt 20) {
    throw 'Enrollment token input is too short. Paste the full fresh test enrollment token into the hidden prompt; do not type the masking asterisk, prompt text, or a redacted placeholder.'
  }
  \$Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR(\$SecureToken)
  \$env:ENDPOINT_AGENT_ENROLLMENT_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(\$Bstr)

  \$EndpointPacketStarted = \$true
  Write-Step 'run endpoint-local TPM auto-enroll packet'
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File \$Script \`
    -ApiUrl \$ApiUrl \`
    -TargetProductDeviceId \$TargetProductDeviceId \`
    -EndpointAgentExe \$EndpointAgentExe
  if (\$LASTEXITCODE -ne 0) {
    throw "agentpc2-tpm-autoenroll.ps1 exited with code \$LASTEXITCODE"
  }
}
catch {
  Clear-ProcessEnrollmentToken
  if (\$EndpointPacketStarted) {
    Write-Step 'TPM auto-enroll failed; printing redacted endpoint diagnostics'
    Write-TpmAutoEnrollDiagnostics
  } else {
    Write-Step 'TPM auto-enroll did not start; endpoint diagnostics skipped'
  }
  throw
}
finally {
  if (\$Bstr -ne [IntPtr]::Zero) {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR(\$Bstr)
  }
  Clear-ProcessEnrollmentToken
  Remove-Variable SecureToken -ErrorAction SilentlyContinue
  Remove-Variable Bstr -ErrorAction SilentlyContinue
}

\$EvidenceDir = "\$env:ProgramData\EndpointAgent\faz22-6-tpm-autoenroll-evidence"

Write-Host ''
Write-Host '=== Evidence dir ==='
Get-ChildItem \$EvidenceDir

Write-Host ''
Write-Host '=== Summary ==='
Get-Content "\$EvidenceDir\agentpc2-tpm-autoenroll-summary.json"

Write-Host ''
Write-Host '=== EK certificate summary ==='
Get-Content "\$EvidenceDir\ek-certificate-summary.json" -ErrorAction SilentlyContinue

Write-Host ''
Write-Host '=== TPM device information ==='
Get-Content "\$EvidenceDir\tpmtool-deviceinformation.txt" -ErrorAction SilentlyContinue
EOF_RUNNER_PS1

cat >"$readme" <<EOF_README
# Faz 22.6 #548 AgentPC2 TPM Auto-Enroll Packet

This packet is non-secret. It does not contain an enrollment token, bearer token,
private key, cookie, password, or raw credential. The generated PowerShell script
requires the test enrollment token through the current PowerShell process
environment only.

Use \`agentpc2-tpm-autoenroll-runner.ps1\` for operator execution. It downloads
and verifies \`agentpc2-tpm-autoenroll.ps1\`, prompts for the fresh test token
inside a hidden secure prompt, injects it only into process environment, and
clears it after the endpoint-local run. It rejects obviously truncated token
input locally before calling the endpoint or API, without logging the token
value. If the agent exits non-zero, the runner
prints redacted endpoint diagnostics from the evidence directory plus the local
\`endpoint-agent.exe\` version/help so stale-binary and server-side failures are
visible without a second operator command. Do not edit the \`Read-Host -Prompt\`
text and do not paste the raw value into commands.

## Target

- Hostname: \`${TARGET_HOSTNAME}\`
- Product device id: \`${TARGET_PRODUCT_DEVICE_ID}\`
- TPM enroll API base: \`${API_URL%/}\`
- Dedicated device-key broker SNI for the follow-up session: \`${BROKER_HOST}\`
- Endpoint binary path: \`${ENDPOINT_AGENT_EXE}\`

The agent appends \`/enrollments/tpm/nonce\` and
\`/enrollments/tpm/attest\` to the API base. On the test edge, the
\`/api/v1/endpoint-agent/**\` gateway route rewrites to backend
\`/api/v1/agent/**\`.

## Endpoint-Local Execution

Run from an elevated PowerShell session on AgentPC2.

1. Inject the approved test enrollment token through the current process
   environment using the approved secret channel. Do not paste the raw value in
   chat, GitHub, Mavis, shell transcript, or evidence.
2. Prefer the runner:

\`\`\`powershell
.\agentpc2-tpm-autoenroll-runner.ps1
\`\`\`

3. Advanced/manual execution, if the runner cannot be used:

\`\`\`powershell
.\\agentpc2-tpm-autoenroll.ps1 \\
  -ApiUrl "${API_URL%/}" \\
  -TargetProductDeviceId "${TARGET_PRODUCT_DEVICE_ID}" \\
  -EndpointAgentExe "${ENDPOINT_AGENT_EXE}"
\`\`\`

4. Remove the process environment value immediately after the script returns.
5. Return only the generated evidence files, especially
   \`agentpc2-tpm-autoenroll-summary.json\`. Do not include the enrollment token.

## Acceptance Boundary

This packet proves only the endpoint-local TPM auto-enroll attempt and produces
redacted endpoint evidence. It does not by itself satisfy #548. Server-side
acceptance still requires:

- a complete \`endpoint_tpm_device_binding\` row for the target device;
- non-empty \`ak_name\`, \`ak_pub_sha256\`, \`ek_cert_sha256\`, and
  \`device_key_spki_sha256\`;
- bridge-selected mTLS leaf SPKI equal to the persisted device-key SPKI;
- a live dedicated-broker session with \`deviceTrusted=true\` and
  \`Basis.HARDWARE_KEY_ATTESTATION\`;
- negative matrix evidence for missing, stale, replay, wrong-device, and
  wrong-tenant cases.
EOF_README

jq -n \
  --arg schema "faz22.6.agentpc2.tpm-autoenroll.packet.v1" \
  --arg generated_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg api_url "${API_URL%/}" \
  --arg target_hostname "$TARGET_HOSTNAME" \
  --arg target_product_device_id "$TARGET_PRODUCT_DEVICE_ID" \
  --arg endpoint_agent_exe "$ENDPOINT_AGENT_EXE" \
  --arg broker_host "$BROKER_HOST" \
  '{
    schema:$schema,
    generated_at:$generated_at,
    target:{hostname:$target_hostname, product_device_id:$target_product_device_id},
    api:{base_url:$api_url, suffixes:["/enrollments/tpm/nonce","/enrollments/tpm/attest"]},
    endpoint_agent_exe:$endpoint_agent_exe,
    dedicated_broker_host:$broker_host,
    secret_hygiene:{
      enrollment_token_embedded:false,
      raw_credential_material_included:false,
      token_channel:"process environment on endpoint only"
    },
    files:["agentpc2-tpm-autoenroll.ps1","agentpc2-tpm-autoenroll-runner.ps1","README.md","packet-manifest.json","SHA256SUMS"]
  }' >"$manifest"

(
  cd "$OUT_DIR"
  rm -f SHA256SUMS
  tmp_checksums="$(mktemp)"
  if command -v sha256sum >/dev/null 2>&1; then
    find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
      | sort -z \
      | xargs -0 sha256sum > "$tmp_checksums"
    mv "$tmp_checksums" SHA256SUMS
    sha256sum -c SHA256SUMS >/dev/null
  else
    find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
      | sort -z \
      | xargs -0 shasum -a 256 > "$tmp_checksums"
    mv "$tmp_checksums" SHA256SUMS
    shasum -a 256 -c SHA256SUMS >/dev/null
  fi
)

printf 'packet_dir=%s\n' "$OUT_DIR"
printf 'packet_manifest=%s\n' "$manifest"
printf 'powershell=%s\n' "$packet_ps1"
