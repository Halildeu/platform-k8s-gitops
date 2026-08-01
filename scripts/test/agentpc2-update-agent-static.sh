#!/usr/bin/env bash
set -euo pipefail

script="scripts/faz22-remote-ops/agentpc2-update-agent-v0214.sh"
seed_script="scripts/faz22-remote-ops/remote-response-terminal-update-agent-seed.sh"
workflow=".github/workflows/faz22-agentpc2-update-agent-v0214.yml"
policy_validator="scripts/faz22-remote-ops/check-endpoint-agent-release-policy.sh"

if [[ ! -f "${script}" ]]; then
  echo "missing ${script}" >&2
  exit 1
fi

if [[ ! -f "${workflow}" ]]; then
  echo "missing ${workflow}" >&2
  exit 1
fi

if [[ ! -f "${seed_script}" ]]; then
  echo "missing ${seed_script}" >&2
  exit 1
fi

"${policy_validator}" >/dev/null

if ! grep -Fq 'source "${SCRIPT_DIR}/endpoint-agent-release-policy.sh"' "${script}"; then
  echo "UPDATE_AGENT script must load the shared EndpointAgent release policy" >&2
  exit 1
fi

if ! grep -Fq 'endpoint_agent_release_policy_load "$REPO_ROOT"' "${script}"; then
  echo "UPDATE_AGENT script must source release defaults from the policy SSOT" >&2
  exit 1
fi

if ! grep -Fq 'TARGET_VERSION="${TARGET_VERSION:-$EXPECTED_AGENT_VERSION}"' "${script}"; then
  echo "UPDATE_AGENT script target version must default from the policy-loaded agent version" >&2
  exit 1
fi

if ! grep -Fq 'EXPECTED_SHA256="${EXPECTED_SHA256:-$EXPECTED_AGENT_SHA256}"' "${script}"; then
  echo "UPDATE_AGENT script endpoint binary hash must default from the policy-loaded hash" >&2
  exit 1
fi

if ! grep -Fq 'MAX_BYTES="${MAX_BYTES:-$EXPECTED_AGENT_MAX_BYTES}"' "${script}"; then
  echo "UPDATE_AGENT script max byte guard must default from the policy-loaded size" >&2
  exit 1
fi

if ! grep -Fq -- '--data-urlencode "scope=openid smoke-notify-v1"' "${script}"; then
  echo "UPDATE_AGENT persona token must request the optional org_id scope used by endpoint-admin tenant resolution" >&2
  exit 1
fi

if grep -Eq 'https://github\.com/Halildeu/platform-agent/releases/download/v0\.2\.28|e99c05d0daf37b1d4e36807ab8a70194ab4be76f50a6225f1cedb82b2d31b7a4|MAX_BYTES="\$\{MAX_BYTES:-14377384\}"' "${script}"; then
  echo "UPDATE_AGENT script must not hard-code current release defaults outside the policy SSOT" >&2
  exit 1
fi

if ! grep -Fq 'source "${SCRIPT_DIR}/endpoint-agent-release-policy.sh"' "${seed_script}"; then
  echo "UPDATE_AGENT seed helper must load the shared EndpointAgent release policy" >&2
  exit 1
fi

if ! grep -Fq 'endpoint_agent_release_policy_load "$REPO_ROOT"' "${seed_script}"; then
  echo "UPDATE_AGENT seed helper must source release defaults from the policy SSOT" >&2
  exit 1
fi

if ! grep -Fq 'MAX_BYTES="${MAX_BYTES:-$EXPECTED_AGENT_MAX_BYTES}"' "${seed_script}"; then
  echo "UPDATE_AGENT seed helper max byte guard must default from the policy-loaded size" >&2
  exit 1
fi

if grep -Eq 'v0\.2\.10|a50344a4457959b95dfdfa22e6578e53cd6ec4b124830b506fe53503c18ba1ec|14104488' "${seed_script}"; then
  echo "UPDATE_AGENT seed helper must not carry stale release defaults outside the policy SSOT" >&2
  exit 1
fi

if ! grep -Fq 'exit 0' "${script}"; then
  echo "UPDATE_AGENT script must explicitly exit 0 after accepted update-observed/update-dispatched states" >&2
  exit 1
fi

if ! grep -Fq 'scripts/faz22-remote-ops/check-endpoint-agent-release-policy.sh' "${workflow}"; then
  echo "UPDATE_AGENT workflow must validate the checked-in release policy before running" >&2
  exit 1
fi

if ! grep -Fq 'Optional release tag override; empty uses the checked-in EndpointAgent release policy' "${workflow}"; then
  echo "UPDATE_AGENT workflow release input must be an optional override, not a hard-coded default" >&2
  exit 1
fi

if ! grep -Fq 'if [ -n "${INPUT_RELEASE_ID}" ]; then' "${workflow}"; then
  echo "UPDATE_AGENT workflow must export release URL overrides only when a release_id override is provided" >&2
  exit 1
fi

if grep -Eq "default: '(v0\\.2\\.28|0\\.2\\.28|14377384|e99c05d0daf37b1d4e36807ab8a70194ab4be76f50a6225f1cedb82b2d31b7a4)'" "${workflow}"; then
  echo "UPDATE_AGENT workflow must not carry release-specific defaults outside the policy SSOT" >&2
  exit 1
fi

echo "agentpc2 UPDATE_AGENT static guard passed"
