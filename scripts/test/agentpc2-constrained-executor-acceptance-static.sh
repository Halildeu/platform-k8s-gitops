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

if ! grep -Fq 'restore_step_up_external_secret_refresh_policy' "${script}"; then
  echo "acceptance must restore the step-up ExternalSecret refresh policy during cleanup" >&2
  exit 1
fi

if ! grep -Fq 'pause_step_up_external_secret_refresh' "${script}"; then
  echo "acceptance must pause the ESO-owned step-up Secret before writing a run-scoped key" >&2
  exit 1
fi

if ! grep -Fq 'STEP_UP_ESO_ORIGINAL_DATA_FILE' "${script}"; then
  echo "acceptance must back up and restore the ExternalSecret data array during run-scoped step-up key smoke" >&2
  exit 1
fi

if ! grep -Fq 'select(.secretKey != "REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM")' "${script}"; then
  echo "acceptance must temporarily remove only the ESO step-up key mapping before writing a run-scoped key" >&2
  exit 1
fi

if ! grep -Fq 'apply_run_scoped_step_up_secret_patch' "${script}"; then
  echo "acceptance must apply the run-scoped step-up Secret patch through a reusable verified helper" >&2
  exit 1
fi

if ! grep -Fq 'reapplying run-scoped key once after ESO reconcile' "${script}"; then
  echo "acceptance must re-apply the run-scoped key once if the ESO OnChange reconcile races the broker rollout" >&2
  exit 1
fi

if ! grep -Fq 'STEP_UP_SECRET_STABILIZE_SECONDS' "${script}"; then
  echo "acceptance must wait briefly after broker rollout before final step-up Secret SHA checks" >&2
  exit 1
fi

if ! grep -Fq 'runtime_step_up_public_key_matches' "${script}"; then
  echo "acceptance must verify the broker runtime step-up public key after rollout" >&2
  exit 1
fi

if ! grep -Fq 'step-up-runtime-public-key-drift' "${script}"; then
  echo "acceptance must fail clearly when the broker runtime step-up public key does not match the run-scoped key" >&2
  exit 1
fi

if ! grep -Fq 'broker runtime env check remains authoritative' "${script}"; then
  echo "acceptance must treat post-patch live Secret drift as observation while keeping broker runtime key verification authoritative" >&2
  exit 1
fi

echo "agentpc2 constrained-executor acceptance static guard passed"
