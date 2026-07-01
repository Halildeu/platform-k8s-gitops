#!/usr/bin/env bash
set -euo pipefail

script="scripts/faz22-remote-ops/faz22-6-agentpc2-tpm-autoenroll-packet.sh"
workflow=".github/workflows/faz22-6-agentpc2-tpm-autoenroll-packet.yml"
runbook="docs/runbooks/RB-faz22.6-548-device-key-session-live-run.md"

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
packet_readme="${tmp}/packet/README.md"
packet_manifest="${tmp}/packet/packet-manifest.json"

for required in "${packet_ps1}" "${packet_readme}" "${packet_manifest}" "${tmp}/packet/SHA256SUMS"; do
  if [[ ! -s "${required}" ]]; then
    echo "packet missing ${required}" >&2
    exit 1
  fi
done

if ! grep -Fq "ArgumentList.Add('--auto-enroll-tpm')" "${packet_ps1}"; then
  echo "endpoint packet must invoke endpoint-agent --auto-enroll-tpm" >&2
  exit 1
fi

if grep -Fq -- "--enrollment-token" "${packet_ps1}"; then
  echo "endpoint packet must not pass enrollment token on argv" >&2
  exit 1
fi

if ! grep -Fq "Environment['ENDPOINT_AGENT_ENROLLMENT_TOKEN']" "${packet_ps1}"; then
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

if ! grep -Fq "Do not paste the raw value" "${packet_readme}"; then
  echo "packet README must forbid raw token disclosure" >&2
  exit 1
fi

jq -e '
  .secret_hygiene.enrollment_token_embedded == false and
  .secret_hygiene.raw_credential_material_included == false and
  (.api.suffixes | index("/enrollments/tpm/nonce")) and
  (.api.suffixes | index("/enrollments/tpm/attest"))
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

if ! grep -Fq -- "--auto-enroll-tpm" "${runbook}"; then
  echo "runbook must use the TPM-specific auto-enroll CLI flag" >&2
  exit 1
fi

echo "agentpc2 TPM auto-enroll packet static guard passed"
