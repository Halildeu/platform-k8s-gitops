#!/usr/bin/env bash
set -euo pipefail

script="scripts/faz22-remote-ops/agentpc2-update-agent-v0214.sh"
workflow=".github/workflows/faz22-agentpc2-update-agent-v0214.yml"

if [[ ! -f "${script}" ]]; then
  echo "missing ${script}" >&2
  exit 1
fi

if [[ ! -f "${workflow}" ]]; then
  echo "missing ${workflow}" >&2
  exit 1
fi

if ! grep -Fq 'EXPECTED_AGENT_VERSION="${EXPECTED_AGENT_VERSION:-0.2.28}"' "${script}"; then
  echo "UPDATE_AGENT script must default to the current AgentPC2 expected version 0.2.28" >&2
  exit 1
fi

if ! grep -Fq 'RELEASE_ID="${RELEASE_ID:-v0.2.28}"' "${script}"; then
  echo "UPDATE_AGENT script must default to release v0.2.28" >&2
  exit 1
fi

if ! grep -Fq 'TARGET_VERSION="${TARGET_VERSION:-0.2.28}"' "${script}"; then
  echo "UPDATE_AGENT script must default to target version 0.2.28" >&2
  exit 1
fi

if ! grep -Fq 'BINARY_URL="${BINARY_URL:-https://github.com/Halildeu/platform-agent/releases/download/v0.2.28/endpoint-agent.exe}"' "${script}"; then
  echo "UPDATE_AGENT script must default to the v0.2.28 endpoint-agent.exe URL" >&2
  exit 1
fi

if ! grep -Fq 'MANIFEST_URL="${MANIFEST_URL:-https://github.com/Halildeu/platform-agent/releases/download/v0.2.28/release-manifest.json}"' "${script}"; then
  echo "UPDATE_AGENT script must default to the v0.2.28 release manifest URL" >&2
  exit 1
fi

if ! grep -Fq 'EXPECTED_SHA256="${EXPECTED_SHA256:-e99c05d0daf37b1d4e36807ab8a70194ab4be76f50a6225f1cedb82b2d31b7a4}"' "${script}"; then
  echo "UPDATE_AGENT script must default to the v0.2.28 endpoint-agent.exe SHA256" >&2
  exit 1
fi

if ! grep -Fq 'MAX_BYTES="${MAX_BYTES:-14377384}"' "${script}"; then
  echo "UPDATE_AGENT script must default to the v0.2.28 endpoint-agent.exe byte size" >&2
  exit 1
fi

if ! grep -Fq 'exit 0' "${script}"; then
  echo "UPDATE_AGENT script must explicitly exit 0 after accepted update-observed/update-dispatched states" >&2
  exit 1
fi

if ! grep -Fq "default: 'v0.2.28'" "${workflow}"; then
  echo "UPDATE_AGENT workflow must default release_id to v0.2.28" >&2
  exit 1
fi

if ! grep -Fq "default: '0.2.28'" "${workflow}"; then
  echo "UPDATE_AGENT workflow must default target_version to 0.2.28" >&2
  exit 1
fi

if ! grep -Fq "default: 'e99c05d0daf37b1d4e36807ab8a70194ab4be76f50a6225f1cedb82b2d31b7a4'" "${workflow}"; then
  echo "UPDATE_AGENT workflow must default expected_sha256 to the v0.2.28 endpoint-agent.exe SHA256" >&2
  exit 1
fi

if ! grep -Fq "default: '14377384'" "${workflow}"; then
  echo "UPDATE_AGENT workflow must default max_bytes to the v0.2.28 endpoint-agent.exe byte size" >&2
  exit 1
fi

echo "agentpc2 UPDATE_AGENT static guard passed"
