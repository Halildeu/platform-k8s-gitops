#!/usr/bin/env bash
set -euo pipefail

script="scripts/faz22-remote-ops/agentpc2-constrained-executor-acceptance.sh"

if [[ ! -f "${script}" ]]; then
  echo "missing ${script}" >&2
  exit 1
fi

if ! grep -Fq 'TOKEN_CLIENT_CANDIDATES="${TOKEN_CLIENT_CANDIDATES:-remote-bridge-operator-api frontend}"' "${script}"; then
  echo "acceptance must try the dedicated remote-bridge-operator-api client before frontend" >&2
  exit 1
fi

if ! grep -Fq '.audContainsRemoteBridgeOperatorApi == true' "${script}"; then
  echo "acceptance must reject persona tokens without the remote-bridge-operator-api audience" >&2
  exit 1
fi

if ! grep -Fq 'missing-required-role-tenant-or-audience' "${script}"; then
  echo "acceptance no-go reason must distinguish missing role, tenant, or audience" >&2
  exit 1
fi

if grep -Fq '.realmRolesContainRemoteBridgeOperator == true and .tenant_id_present == true'\'' "$claims_file" >/dev/null' "${script}"; then
  echo "acceptance must not allow the old role+tenant-only token gate" >&2
  exit 1
fi

echo "agentpc2 constrained-executor acceptance static guard passed"
