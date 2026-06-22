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

if ! grep -Fq 'EXPECTED_AGENT_VERSION="${EXPECTED_AGENT_VERSION:-0.2.25}"' "${script}"; then
  echo "UPDATE_AGENT script must default to the current AgentPC2 expected version 0.2.25" >&2
  exit 1
fi

if ! grep -Fq 'RELEASE_ID="${RELEASE_ID:-v0.2.25}"' "${script}"; then
  echo "UPDATE_AGENT script must default to release v0.2.25" >&2
  exit 1
fi

if ! grep -Fq 'TARGET_VERSION="${TARGET_VERSION:-0.2.25}"' "${script}"; then
  echo "UPDATE_AGENT script must default to target version 0.2.25" >&2
  exit 1
fi

if ! grep -Fq 'BINARY_URL="${BINARY_URL:-https://github.com/Halildeu/platform-agent/releases/download/v0.2.25/endpoint-agent.exe}"' "${script}"; then
  echo "UPDATE_AGENT script must default to the v0.2.25 endpoint-agent.exe URL" >&2
  exit 1
fi

if ! grep -Fq 'MANIFEST_URL="${MANIFEST_URL:-https://github.com/Halildeu/platform-agent/releases/download/v0.2.25/release-manifest.json}"' "${script}"; then
  echo "UPDATE_AGENT script must default to the v0.2.25 release manifest URL" >&2
  exit 1
fi

if ! grep -Fq 'EXPECTED_SHA256="${EXPECTED_SHA256:-0bf8aada0bf7b25f3e574e576a8401f9030168cbe60a487d6f6c5a6d4c610aec}"' "${script}"; then
  echo "UPDATE_AGENT script must default to the v0.2.25 endpoint-agent.exe SHA256" >&2
  exit 1
fi

if ! grep -Fq 'MAX_BYTES="${MAX_BYTES:-14376360}"' "${script}"; then
  echo "UPDATE_AGENT script must default to the v0.2.25 endpoint-agent.exe byte size" >&2
  exit 1
fi

if ! grep -Fq "default: 'v0.2.25'" "${workflow}"; then
  echo "UPDATE_AGENT workflow must default release_id to v0.2.25" >&2
  exit 1
fi

if ! grep -Fq "default: '0.2.25'" "${workflow}"; then
  echo "UPDATE_AGENT workflow must default target_version to 0.2.25" >&2
  exit 1
fi

if ! grep -Fq "default: '0bf8aada0bf7b25f3e574e576a8401f9030168cbe60a487d6f6c5a6d4c610aec'" "${workflow}"; then
  echo "UPDATE_AGENT workflow must default expected_sha256 to the v0.2.25 endpoint-agent.exe SHA256" >&2
  exit 1
fi

if ! grep -Fq "default: '14376360'" "${workflow}"; then
  echo "UPDATE_AGENT workflow must default max_bytes to the v0.2.25 endpoint-agent.exe byte size" >&2
  exit 1
fi

echo "agentpc2 UPDATE_AGENT static guard passed"
