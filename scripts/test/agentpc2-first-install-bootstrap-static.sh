#!/usr/bin/env bash
# shellcheck disable=SC2016
set -euo pipefail

script="scripts/faz22-remote-ops/agentpc2-first-install-bootstrap-gate.sh"
workflow=".github/workflows/faz22-agentpc2-first-install-bootstrap.yml"
policy="config/faz22-6-endpoint-agent-release-policy.v1.json"
policy_validator="scripts/faz22-remote-ops/check-endpoint-agent-release-policy.sh"
kustomization="kustomize/overlays/test/kustomization.yaml"
bootstrap_configmap="kustomize/overlays/test/agentpc2-bootstrap/configmap.yaml"

if [[ ! -f "${script}" ]]; then
  echo "missing ${script}" >&2
  exit 1
fi

if [[ ! -f "${workflow}" ]]; then
  echo "missing ${workflow}" >&2
  exit 1
fi

if [[ ! -f "${policy}" ]]; then
  echo "missing ${policy}" >&2
  exit 1
fi

if [[ ! -x "${policy_validator}" ]]; then
  echo "missing executable ${policy_validator}" >&2
  exit 1
fi

"${policy_validator}" >/dev/null

# shellcheck disable=SC2016
if ! grep -Fq 'Invoke-DownloadVerified -Uri \$BinaryUrl -OutFile \$BinaryPath -ExpectedSha256 \$ExpectedAgentSha256' "${script}"; then
  echo "bootstrap must download and SHA256-verify endpoint-agent.exe before local install" >&2
  exit 1
fi

if ! grep -Fq 'source "${SCRIPT_DIR}/endpoint-agent-release-policy.sh"' "${script}"; then
  echo "bootstrap gate must load the shared EndpointAgent release policy" >&2
  exit 1
fi

if ! grep -Fq 'endpoint_agent_release_policy_load "$REPO_ROOT"' "${script}"; then
  echo "bootstrap gate must source release defaults from the policy SSOT" >&2
  exit 1
fi

if ! grep -Fq 'TARGET_VERSION="${TARGET_VERSION:-$EXPECTED_AGENT_VERSION}"' "${script}"; then
  echo "bootstrap gate target version must default from the policy-loaded agent version" >&2
  exit 1
fi

if ! grep -Fq 'RELEASE_BASE_URL="${RELEASE_BASE_URL:-$GITHUB_RELEASE_BASE_URL}"' "${script}"; then
  echo "bootstrap gate release URLs must default from the policy-loaded release base URL" >&2
  exit 1
fi

if ! grep -Fq ': "${EXPECTED_RELEASE_MANIFEST_SHA256:?missing expected release manifest SHA256}"' "${script}"; then
  echo "bootstrap gate must fail closed when policy does not provide release-manifest SHA256" >&2
  exit 1
fi

if ! grep -Fq ': "${EXPECTED_INSTALL_PS1_SHA256:?missing expected install.ps1 SHA256}"' "${script}"; then
  echo "bootstrap gate must fail closed when policy does not provide install.ps1 SHA256" >&2
  exit 1
fi

if ! grep -Fq ': "${EXPECTED_BOOTSTRAP_PS1_SHA256:?missing expected bootstrap-package.ps1 SHA256}"' "${script}"; then
  echo "bootstrap gate must fail closed when policy does not provide bootstrap-package.ps1 SHA256" >&2
  exit 1
fi

if ! grep -Fq ': "${EXPECTED_SIGNER_SHA256_FINGERPRINT:?missing expected signer SHA256 fingerprint}"' "${script}"; then
  echo "bootstrap gate must fail closed when policy does not provide the signer SHA256 fingerprint" >&2
  exit 1
fi

if grep -Fq 'sha256:36a81cb89294ef7f4d09350ab9f92a955b65b8132ba5330fcf1dcb7e365ab3e2' "${script}"; then
  echo "bootstrap gate must not hard-code the release artifact-host digest outside the policy SSOT" >&2
  exit 1
fi

if ! grep -Fq 'scripts/faz22-remote-ops/check-endpoint-agent-release-policy.sh' "${workflow}"; then
  echo "first-install workflow must validate the checked-in release policy before running" >&2
  exit 1
fi

if grep -Eq '^[[:space:]]+(release_id|expected_release_manifest_sha256|expected_install_ps1_sha256|expected_bootstrap_ps1_sha256|expected_agent_sha256|expected_agent_zip_sha256|expected_signer_thumbprint|expected_signer_sha256_fingerprint):' "${workflow}"; then
  echo "first-install workflow must not expose release-specific override inputs; release defaults come from the policy SSOT" >&2
  exit 1
fi

if grep -Eq "default: '(v0\\.2\\.28|e99c05d0daf37b1d4e36807ab8a70194ab4be76f50a6225f1cedb82b2d31b7a4|e30ab27490dfcc565bd19f5da657739dfacb8e8d9f57770142575a03e607938a|afc86befa2db11803724e4c1bc9fc0aaf0275ff4cf31d953270d27c84d6b7f12|f257202723ac719f4170cbe2e800dc190845ff7fbd128c6ce3ddd2ac90e49e0e|83292ab3b5c27a8c27c11c7774cf4157bbb23188b81b0adf2a5a29a70279c7f8|D68F4F530137EB65CE44E3405E82B46205E753E5|EB16FA8C2C2325295483ED2271D87632DA5EA631E3095039D6CFC358F16CAACD)'" "${workflow}"; then
  echo "first-install workflow must not carry release-specific defaults outside the policy SSOT" >&2
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

if grep -Fq 'EB16FA8C2C2325295483ED2271D87632DA5EA631E3095039D6CFC358F16CAACD' "${script}"; then
  echo "bootstrap gate must not hard-code the Authenticode certificate fingerprint outside the policy SSOT" >&2
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

if ! grep -Fq '9e3a7a89f5782ea54acb93e7c4bc1bbe411e0d5f29eacabca2a3911dbd8a5196  agentpc2-remote-bridge-canonical-env-patch-v7.ps1' "${bootstrap_configmap}"; then
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

if ! grep -Fq 'c301386acbcee0297260495a1d4fc79f4e263130c39522a6137354d10f11bdbe  agentpc2-first-install-bootstrap.ps1' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the self-update-capable first-install hash" >&2
  exit 1
fi

if ! grep -Fq '91570e68f60c7b789d44d748735d696f70dddb09534e84ce6124f09966396503  README.md' "${bootstrap_configmap}"; then
  echo "AgentPC2 bootstrap SHA256SUMS must pin the self-update-capable README hash" >&2
  exit 1
fi

echo "agentpc2 first-install bootstrap static guard passed"
