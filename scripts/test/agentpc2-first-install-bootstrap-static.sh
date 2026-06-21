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

if ! grep -Fq 'EXPECTED_ARTIFACT_HOST_DIGEST="${EXPECTED_ARTIFACT_HOST_DIGEST:-sha256:e4309d08da77f9c3f5eb288805611fa2d8a97178bcd90b1a132eb30585ed3da0}"' "${script}"; then
  echo "bootstrap gate default artifact-host digest must track the v0.2.21 immutable image digest" >&2
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

if ! grep -Fq 'SELF_UPDATE_ALLOWED_HOSTS="${SELF_UPDATE_ALLOWED_HOSTS:-github.com,release-assets.githubusercontent.com,objects.githubusercontent.com}"' "${script}"; then
  echo "bootstrap gate must default to the bounded signed self-update host allowlist" >&2
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

if ! grep -Fq '4c79bd64d015189aa6cbd92b8194d3e926298921bc4579fd8c6428b76ec918fe  agentpc2-remote-bridge-canonical-env-patch-v7.ps1' "${bootstrap_configmap}"; then
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

if ! grep -Fq '00ab037fdd5d2577970359f153f77c75d51eeeb0e9da34f287d716293ed0a13c  agentpc2-first-install-bootstrap.ps1' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the self-update-capable first-install hash" >&2
  exit 1
fi

if ! grep -Fq '3ded08b9dedde27e2a7fc5ab0cfbba6fd7df25d4b107a1a1a7b287c1d95b3a7b  README.md' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the self-update-capable README hash" >&2
  exit 1
fi

echo "agentpc2 first-install bootstrap static guard passed"
