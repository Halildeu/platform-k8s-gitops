#!/usr/bin/env bash
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

if ! grep -Fq 'EXPECTED_ARTIFACT_HOST_DIGEST="${EXPECTED_ARTIFACT_HOST_DIGEST:-sha256:39059fb9754c31037e966c0a54456f167e572c9fe61c4a29594f521bbb394a3f}"' "${script}"; then
  echo "bootstrap gate default artifact-host digest must track the v0.2.19 immutable image digest" >&2
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

if ! grep -Fq '919f569e6c210e4a2241c7525d30430bf36d3896c11ff9d11df3d152fdd7e08c  agentpc2-remote-bridge-canonical-env-patch-v7.ps1' "${bootstrap_configmap}"; then
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

if ! grep -Fq '7bfe0c9b78bfc31f5fa44fd58abddc16727e796b050a03861c832df3ca8adf46  agentpc2-first-install-bootstrap.ps1' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the canonical-env first-install hash" >&2
  exit 1
fi

echo "agentpc2 first-install bootstrap static guard passed"
