#!/usr/bin/env bash
set -euo pipefail

script="scripts/faz22-remote-ops/agentpc2-first-install-bootstrap-gate.sh"

if [[ ! -f "${script}" ]]; then
  echo "missing ${script}" >&2
  exit 1
fi

if ! grep -Fq 'Invoke-DownloadVerified -Uri \$BinaryUrl -OutFile \$BinaryPath -ExpectedSha256 \$ExpectedAgentSha256' "${script}"; then
  echo "bootstrap must download and SHA256-verify endpoint-agent.exe before local install" >&2
  exit 1
fi

install_args_block="$(awk '
  /\\\$installArgs = @\(/ { in_block=1 }
  in_block { print }
  in_block && /^[[:space:]]+\)/ { exit }
' "${script}")"

if ! grep -Fq '"-BinaryPath", \$BinaryPath' <<<"${install_args_block}"; then
  echo "bootstrap install args must pass the verified local BinaryPath" >&2
  exit 1
fi

if grep -Fq '"-BinaryUrl"' <<<"${install_args_block}"; then
  echo "bootstrap install args must not pass -BinaryUrl with an empty value; Windows PowerShell drops empty native args" >&2
  exit 1
fi

echo "agentpc2 first-install bootstrap static guard passed"
