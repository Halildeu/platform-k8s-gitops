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

if ! grep -Fq 'be30746c9d8c8ca6d439a68ecb2e75184638001935657dcc2fbf755422438f99  agentpc2-remote-bridge-canonical-env-patch-v7.ps1' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the v7 canonical env patch hash" >&2
  exit 1
fi

if ! grep -Fq '56b793f5b085abdaec49c2aa7fe5feac82d9999682d87f982a10dba0589c59f5  agentpc2-first-install-bootstrap.ps1' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the canonical-env first-install hash" >&2
  exit 1
fi

echo "agentpc2 first-install bootstrap static guard passed"
