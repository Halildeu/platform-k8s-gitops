#!/usr/bin/env bash
# shellcheck disable=SC2016
set -euo pipefail

script="scripts/faz22-remote-ops/agentpc2-first-install-bootstrap-gate.sh"
kustomization="kustomize/overlays/test/kustomization.yaml"
bootstrap_configmap="kustomize/overlays/test/agentpc2-bootstrap/configmap.yaml"

if [[ ! -f "${script}" ]]; then
  echo "missing ${script}" >&2
  exit 1
fi

# shellcheck disable=SC2016
if ! grep -Fq 'Invoke-DownloadVerified -Uri \$BinaryUrl -OutFile \$BinaryPath -ExpectedSha256 \$ExpectedAgentSha256' "${script}"; then
  echo "bootstrap must download and SHA256-verify endpoint-agent.exe before local install" >&2
  exit 1
fi

if ! grep -Fq 'EXPECTED_ARTIFACT_HOST_DIGEST="${EXPECTED_ARTIFACT_HOST_DIGEST:-sha256:36a81cb89294ef7f4d09350ab9f92a955b65b8132ba5330fcf1dcb7e365ab3e2}"' "${script}"; then
  echo "bootstrap gate default artifact-host digest must track the v0.2.28 immutable image digest" >&2
  exit 1
fi

if ! grep -Fq 'REQUIRE_ARTIFACT_HOST_LIVE_DIGEST="${REQUIRE_ARTIFACT_HOST_LIVE_DIGEST:-true}"' "${script}"; then
  echo "bootstrap gate must require live artifact-host digest assertion by default" >&2
  exit 1
fi

if ! grep -Fq 'ERR live artifact-host image digest mismatch' "${script}"; then
  echo "bootstrap gate must fail closed when the live artifact-host digest differs from the expected release digest" >&2
  exit 1
fi

install_args_block="$(awk '
  /\\\$installArgs = @\(/ { in_block=1 }
  in_block { print }
  in_block && /^[[:space:]]+\)/ { exit }
' "${script}")"

# shellcheck disable=SC2016
if ! grep -Fq '"-BinaryPath", \$BinaryPath' <<<"${install_args_block}"; then
  echo "bootstrap install args must pass the verified local BinaryPath" >&2
  exit 1
fi

if grep -Fq '"-BinaryUrl"' <<<"${install_args_block}"; then
  echo "bootstrap install args must not pass -BinaryUrl with an empty value; Windows PowerShell drops empty native args" >&2
  exit 1
fi

if ! grep -Fq 'SELF_UPDATE_ALLOWED_HOSTS="${SELF_UPDATE_ALLOWED_HOSTS:-github.com,release-assets.githubusercontent.com,objects.githubusercontent.com,testai.acik.com}"' "${script}"; then
  echo "bootstrap gate must default to the bounded signed self-update host allowlist" >&2
  exit 1
fi

if ! grep -Fq 'EXPECTED_SIGNER_SHA256_FINGERPRINT="${EXPECTED_SIGNER_SHA256_FINGERPRINT:-EB16FA8C2C2325295483ED2271D87632DA5EA631E3095039D6CFC358F16CAACD}"' "${script}"; then
  echo "bootstrap gate must pin the SHA256 Authenticode certificate fingerprint used by UPDATE_AGENT" >&2
  exit 1
fi

if ! grep -Fq 'ERR EXPECTED_SIGNER_THUMBPRINT must be uppercase SHA1 thumbprint hex' "${script}"; then
  echo "bootstrap gate must validate the SHA1 Authenticode signer thumbprint in standalone mode" >&2
  exit 1
fi

if ! grep -Fq '"-RemoteBridgePilotAutoConsent"' <<<"${install_args_block}"; then
  echo "bootstrap install args must opt into the bounded AgentPC2 pilot remote-bridge consent lane" >&2
  exit 1
fi

if ! grep -Fq '"-SelfUpdateEnabled"' <<<"${install_args_block}"; then
  echo "bootstrap install args must enable signed product self-update support" >&2
  exit 1
fi

if ! grep -Fq '"-SelfUpdateSignerThumbprints", \$SelfUpdateSignerThumbprints' <<<"${install_args_block}"; then
  echo "bootstrap install args must pass the SHA256 signer fingerprint allowlist to install.ps1" >&2
  exit 1
fi

if ! grep -Fq 'ENDPOINT_AGENT_SELF_UPDATE_ENABLED' "${script}"; then
  echo "bootstrap gate must write self-update service environment keys" >&2
  exit 1
fi

if ! grep -Fq 'Signed self-update local trust policy written so UPDATE_AGENT can be advertised' "${script}"; then
  echo "bootstrap endpoint evidence boundary must state self-update capability scope" >&2
  exit 1
fi

if [[ ! -f "${bootstrap_configmap}" ]]; then
  echo "missing ${bootstrap_configmap}" >&2
  exit 1
fi

if ! grep -Fq 'agentpc2-bootstrap/configmap.yaml' "${kustomization}"; then
  echo "test overlay must include the AgentPC2 bootstrap ConfigMap resource" >&2
  exit 1
fi

if ! grep -Fq 'mountPath: /usr/share/nginx/html/artifacts/endpoint-agent/bootstrap' "${kustomization}"; then
  echo "artifact-host must publish the AgentPC2 bootstrap ConfigMap under /artifacts/endpoint-agent/bootstrap" >&2
  exit 1
fi

if ! grep -Fq 'agentpc2-first-install-bootstrap.ps1:' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap ConfigMap must contain agentpc2-first-install-bootstrap.ps1" >&2
  exit 1
fi

if ! grep -Fq 'SHA256SUMS:' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap ConfigMap must contain SHA256SUMS" >&2
  exit 1
fi

if ! grep -Fq 'agentpc2-remote-bridge-canonical-env-patch-v7.ps1:' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap ConfigMap must contain the v7 canonical env patch" >&2
  exit 1
fi

if ! grep -Fq 'ENDPOINT_AGENT_SELF_UPDATE_ALLOWED_HOSTS' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap ConfigMap must publish self-update service environment keys" >&2
  exit 1
fi

if ! grep -Fq '9da2e0ee733173e1289d8ef7a65a0bb1eb1725d8747d553d0c25790a71450532  agentpc2-remote-bridge-canonical-env-patch-v7.ps1' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the v7 canonical env patch hash" >&2
  exit 1
fi

if ! grep -Fq 'agentpc2-remote-bridge-attestation-patch-v0217-20260621T144928Z-14741b2e.ps1:' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap ConfigMap must contain the v0.2.17 signed attestation patch" >&2
  exit 1
fi

if ! grep -Fq 'f695d8b3bf5b74ad200529bed823d1dc7228e1db9c0dac680eb1339355917c06  agentpc2-remote-bridge-attestation-patch-v0217-20260621T144928Z-14741b2e.ps1' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the v0.2.17 signed attestation patch hash" >&2
  exit 1
fi

if ! grep -Fq '1c83bc3f6c1f263b462c82ae43cefaa9e1f3019f5fbc575a047076d341ecc217  agentpc2-first-install-bootstrap.ps1' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the self-update-capable first-install hash" >&2
  exit 1
fi

if ! grep -Fq '25671f8860d95f2ebdb0990a7dd9e69a42811638a226f2b06aa640b069a69228  README.md' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the self-update-capable README hash" >&2
  exit 1
fi

echo "agentpc2 first-install bootstrap static guard passed"
