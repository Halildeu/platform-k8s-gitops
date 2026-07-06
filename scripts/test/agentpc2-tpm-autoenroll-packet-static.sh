#!/usr/bin/env bash
set -euo pipefail

script="scripts/faz22-remote-ops/faz22-6-agentpc2-tpm-autoenroll-packet.sh"
workflow=".github/workflows/faz22-6-agentpc2-tpm-autoenroll-packet.yml"
runbook="docs/runbooks/RB-faz22.6-548-device-key-session-live-run.md"
bootstrap_configmap="kustomize/overlays/test/agentpc2-bootstrap/configmap.yaml"

if [[ ! -x "${script}" ]]; then
  echo "missing executable ${script}" >&2
  exit 1
fi

if [[ ! -f "${workflow}" ]]; then
  echo "missing ${workflow}" >&2
  exit 1
fi

if [[ ! -f "${runbook}" ]]; then
  echo "missing ${runbook}" >&2
  exit 1
fi

bash -n "${script}"

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

"${script}" \
  --out-dir "${tmp}/packet" \
  --api-url "https://testai.acik.com/api/v1/endpoint-agent" \
  --target-hostname "AgentPc2" \
  --target-product-device-id "2f7ad30f-970a-42e7-8af8-08764ae6066f" >/dev/null

packet_ps1="${tmp}/packet/agentpc2-tpm-autoenroll.ps1"
packet_runner="${tmp}/packet/agentpc2-tpm-autoenroll-runner.ps1"
packet_readme="${tmp}/packet/README.md"
packet_manifest="${tmp}/packet/packet-manifest.json"

for required in "${packet_ps1}" "${packet_runner}" "${packet_readme}" "${packet_manifest}" "${tmp}/packet/SHA256SUMS"; do
  if [[ ! -s "${required}" ]]; then
    echo "packet missing ${required}" >&2
    exit 1
  fi
done

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

extract_configmap_block() {
  local key="$1"
  local dest="$2"
  awk -v wanted="  ${key}: |" '
    $0 == wanted { in_block = 1; next }
    in_block && $0 ~ /^  [A-Za-z0-9_.-]+: \|$/ { exit }
    in_block {
      if (substr($0, 1, 4) == "    ") {
        print substr($0, 5)
      } else {
        print
      }
    }
  ' "${bootstrap_configmap}" >"${dest}"
}

if ! grep -Fq "\$psi.Arguments = '--auto-enroll-tpm --api-url ' + \$ApiUrl.TrimEnd('/')" "${packet_ps1}"; then
  echo "endpoint packet must invoke endpoint-agent --auto-enroll-tpm" >&2
  exit 1
fi

if grep -Fq "ArgumentList.Add" "${packet_ps1}"; then
  echo "endpoint packet must be compatible with Windows PowerShell 5.1 ProcessStartInfo; do not use ArgumentList" >&2
  exit 1
fi

if grep -Fq -- "--enrollment-token" "${packet_ps1}"; then
  echo "endpoint packet must not pass enrollment token on argv" >&2
  exit 1
fi

if ! grep -Fq "EnvironmentVariables['ENDPOINT_AGENT_ENROLLMENT_TOKEN']" "${packet_ps1}"; then
  echo "endpoint packet must inject the enrollment token through child process environment only" >&2
  exit 1
fi

if ! grep -Fq "SetEnvironmentVariable('ENDPOINT_AGENT_ENROLLMENT_TOKEN', \$null, 'Process')" "${packet_ps1}"; then
  echo "endpoint packet must clear the process environment token after use" >&2
  exit 1
fi

if ! grep -Fq "Get-TpmEndorsementKeyInfo -Hash Sha256" "${packet_ps1}"; then
  echo "endpoint packet must collect EK manufacturer certificate evidence" >&2
  exit 1
fi

if ! grep -Fq "Is Capable For Attestation" "${packet_ps1}"; then
  echo "endpoint packet must gate on TPM attestation capability" >&2
  exit 1
fi

if ! grep -Fq "tokenPassedOnCommandLine = \$false" "${packet_ps1}"; then
  echo "endpoint packet summary must record tokenPassedOnCommandLine=false" >&2
  exit 1
fi

if ! grep -Fq "Read-Host -Prompt 'Paste approved FRESH TEST ENDPOINT_AGENT_ENROLLMENT_TOKEN' -AsSecureString" "${packet_runner}"; then
  echo "runner must use a fixed hidden token prompt without embedding token values" >&2
  exit 1
fi

if ! grep -Fq "Invoke-WebRequest -UseBasicParsing -Uri \"\$BaseUrl/agentpc2-tpm-autoenroll.ps1" "${packet_runner}"; then
  echo "runner must download the endpoint TPM auto-enroll script" >&2
  exit 1
fi

if ! grep -Fq "Get-FileHash -LiteralPath \$Script -Algorithm SHA256" "${packet_runner}"; then
  echo "runner must verify the downloaded endpoint TPM auto-enroll script hash" >&2
  exit 1
fi

if ! grep -Fq "\$env:ENDPOINT_AGENT_ENROLLMENT_TOKEN =" "${packet_runner}"; then
  echo "runner must inject the enrollment token only through process environment" >&2
  exit 1
fi

if ! grep -Fq "\$SecureToken.Length -lt 20" "${packet_runner}"; then
  echo "runner must reject obviously truncated enrollment-token prompt input before endpoint/API execution" >&2
  exit 1
fi

if ! grep -Fq "Enrollment token input is too short" "${packet_runner}"; then
  echo "runner must explain too-short token input without logging token material" >&2
  exit 1
fi

if ! grep -Fq "TPM auto-enroll did not start; endpoint diagnostics skipped" "${packet_runner}"; then
  echo "runner must avoid printing stale endpoint diagnostics when local token preflight fails" >&2
  exit 1
fi

if ! grep -Fq "ZeroFreeBSTR" "${packet_runner}"; then
  echo "runner must zero the SecureString BSTR after use" >&2
  exit 1
fi

if ! grep -Fq "Clear-ProcessEnrollmentToken" "${packet_runner}"; then
  echo "runner must clear process enrollment token state" >&2
  exit 1
fi

if ! grep -Fq "Write-TpmAutoEnrollDiagnostics" "${packet_runner}"; then
  echo "runner must print redacted endpoint diagnostics when TPM auto-enroll fails" >&2
  exit 1
fi

if ! grep -Fq "TPM auto-enroll failed; printing redacted endpoint diagnostics" "${packet_runner}"; then
  echo "runner failure path must make diagnostic collection explicit" >&2
  exit 1
fi

if ! grep -Fq "endpoint-agent-tpm-autoenroll-stderr.txt" "${packet_runner}"; then
  echo "runner diagnostics must print the redacted endpoint-agent stderr file" >&2
  exit 1
fi

if ! grep -Fq -- "--auto-enroll-tpm --help" "${packet_runner}"; then
  echo "runner diagnostics must print endpoint-agent TPM help for stale-binary detection" >&2
  exit 1
fi

# shellcheck disable=SC2016 # This is a literal PowerShell heredoc regression sentinel.
if grep -Fq '$(.Exception.Message)' "${packet_runner}"; then
  echo "runner diagnostics must not lose the PowerShell catch variable while generating from bash heredoc" >&2
  exit 1
fi

if grep -Fq -- "--enrollment-token" "${packet_runner}"; then
  echo "runner must not pass enrollment tokens on argv" >&2
  exit 1
fi

if ! grep -Fq "Do not paste the raw value" "${packet_readme}"; then
  echo "packet README must forbid raw token disclosure" >&2
  exit 1
fi

jq -e '
  .secret_hygiene.enrollment_token_embedded == false and
  .secret_hygiene.raw_credential_material_included == false and
  (.api.suffixes | index("/enrollments/tpm/nonce")) and
  (.api.suffixes | index("/enrollments/tpm/attest")) and
  (.files | index("agentpc2-tpm-autoenroll-runner.ps1"))
' "${packet_manifest}" >/dev/null

if grep -RIEq '(BEGIN (RSA |EC |OPENSSH |PRIVATE )?KEY|Authorization: Bearer|password=|secret=|token=[A-Za-z0-9_-]{16,})' "${tmp}/packet"; then
  echo "generated packet appears to contain secret material" >&2
  exit 1
fi

if ! grep -Fq "PREPARE_AGENTPC2_TPM_AUTOENROLL_PACKET" "${workflow}"; then
  echo "workflow must require explicit packet preparation confirmation" >&2
  exit 1
fi

if ! grep -Fq "faz22-6-agentpc2-tpm-autoenroll-packet.sh" "${workflow}"; then
  echo "workflow must call the packet generator" >&2
  exit 1
fi

if grep -Fq "secrets." "${workflow}"; then
  echo "workflow must not consume GitHub secrets; the token is endpoint-local only" >&2
  exit 1
fi

if ! grep -Fq "faz22-6-agentpc2-tpm-autoenroll-packet.sh" "${runbook}"; then
  echo "runbook must point operators to the packet generator" >&2
  exit 1
fi

if ! grep -Fq "agentpc2-tpm-autoenroll-runner.ps1" "${runbook}"; then
  echo "runbook must prefer the safe TPM auto-enroll runner" >&2
  exit 1
fi

if ! grep -Fq -- "--auto-enroll-tpm" "${runbook}"; then
  echo "runbook must use the TPM-specific auto-enroll CLI flag" >&2
  exit 1
fi

if [[ ! -f "${bootstrap_configmap}" ]]; then
  echo "missing ${bootstrap_configmap}" >&2
  exit 1
fi

for published_key in \
  "agentpc2-tpm-autoenroll.ps1:" \
  "agentpc2-tpm-autoenroll-runner.ps1:" \
  "agentpc2-tpm-autoenroll-README.md:" \
  "agentpc2-tpm-autoenroll-packet-manifest.json:"; do
  if ! grep -Fq "${published_key}" "${bootstrap_configmap}"; then
    echo "AgentPC2 bootstrap ConfigMap must publish ${published_key}" >&2
    exit 1
  fi
done

published_packet_ps1="${tmp}/published-agentpc2-tpm-autoenroll.ps1"
published_packet_runner="${tmp}/published-agentpc2-tpm-autoenroll-runner.ps1"
published_packet_readme="${tmp}/published-agentpc2-tpm-autoenroll-README.md"
published_packet_manifest="${tmp}/published-agentpc2-tpm-autoenroll-packet-manifest.json"

extract_configmap_block "agentpc2-tpm-autoenroll.ps1" "${published_packet_ps1}"
extract_configmap_block "agentpc2-tpm-autoenroll-runner.ps1" "${published_packet_runner}"
extract_configmap_block "agentpc2-tpm-autoenroll-README.md" "${published_packet_readme}"
extract_configmap_block "agentpc2-tpm-autoenroll-packet-manifest.json" "${published_packet_manifest}"

jq -e '
  (.files | index("agentpc2-tpm-autoenroll.ps1")) and
  (.files | index("agentpc2-tpm-autoenroll-runner.ps1")) and
  (.files | index("agentpc2-tpm-autoenroll-README.md")) and
  (.files | index("agentpc2-tpm-autoenroll-packet-manifest.json")) and
  (.files | index("SHA256SUMS"))
' "${published_packet_manifest}" >/dev/null

packet_ps1_sha256="$(sha256_file "${published_packet_ps1}")"
packet_runner_sha256="$(sha256_file "${published_packet_runner}")"
packet_readme_sha256="$(sha256_file "${published_packet_readme}")"
packet_manifest_sha256="$(sha256_file "${published_packet_manifest}")"

if ! grep -Fq "${packet_ps1_sha256}  agentpc2-tpm-autoenroll.ps1" "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the TPM auto-enroll script hash" >&2
  exit 1
fi

if ! grep -Fq "${packet_runner_sha256}  agentpc2-tpm-autoenroll-runner.ps1" "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the TPM auto-enroll runner hash" >&2
  exit 1
fi

if ! grep -Fq "${packet_readme_sha256}  agentpc2-tpm-autoenroll-README.md" "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the TPM auto-enroll README hash" >&2
  exit 1
fi

if ! grep -Fq "${packet_manifest_sha256}  agentpc2-tpm-autoenroll-packet-manifest.json" "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the TPM auto-enroll manifest hash" >&2
  exit 1
fi

if ! grep -Fq "Paste approved FRESH TEST ENDPOINT_AGENT_ENROLLMENT_TOKEN" "${bootstrap_configmap}"; then
  echo "published bootstrap ConfigMap must include the safe runner prompt text" >&2
  exit 1
fi

if ! grep -Fq "Write-TpmAutoEnrollDiagnostics" "${bootstrap_configmap}"; then
  echo "published bootstrap ConfigMap must include runner failure diagnostics" >&2
  exit 1
fi

if ! grep -Fq "TPM auto-enroll failed; printing redacted endpoint diagnostics" "${bootstrap_configmap}"; then
  echo "published bootstrap ConfigMap must include the runner diagnostic failure path" >&2
  exit 1
fi

if ! grep -Fq "Enrollment token input is too short" "${bootstrap_configmap}"; then
  echo "published bootstrap ConfigMap must include the runner too-short token guard" >&2
  exit 1
fi

if ! grep -Fq "schema = 'faz22.6.agentpc2.tpm-autoenroll.endpoint-evidence.v1'" "${bootstrap_configmap}"; then
  echo "published TPM auto-enroll script must emit the endpoint evidence schema" >&2
  exit 1
fi

if ! grep -Fq "tokenEmbeddedInScript = \$false" "${bootstrap_configmap}"; then
  echo "published TPM auto-enroll script must record tokenEmbeddedInScript=false" >&2
  exit 1
fi

if grep -Fq -- "--enrollment-token" "${bootstrap_configmap}"; then
  echo "published bootstrap ConfigMap must not pass enrollment tokens on argv" >&2
  exit 1
fi

echo "agentpc2 TPM auto-enroll packet static guard passed"
