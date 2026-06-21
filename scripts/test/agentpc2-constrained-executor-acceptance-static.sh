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

if ! grep -Fq 'EXPECTED_RELEASE_TAG="${EXPECTED_RELEASE_TAG:-v0.2.17}"' "${script}"; then
  echo "acceptance must default to the current AgentPC2 release tag v0.2.17" >&2
  exit 1
fi

if ! grep -Fq 'EXPECTED_AGENT_VERSION="${EXPECTED_AGENT_VERSION:-0.2.17}"' "${script}"; then
  echo "acceptance must default to the current AgentPC2 agent version 0.2.17" >&2
  exit 1
fi

if ! grep -Fq 'EXPECTED_AGENT_SHA256="${EXPECTED_AGENT_SHA256:-418160181258594ce196a734f5d570473919ee6678c255a9fb92b7da0f16a4c2}"' "${script}"; then
  echo "acceptance must default to the v0.2.17 endpoint-agent.exe SHA256" >&2
  exit 1
fi

if ! grep -Fq 'EXPECTED_AGENT_ZIP_SHA256="${EXPECTED_AGENT_ZIP_SHA256:-873a2906c85668ed92a5c656806e77ece82b9d3feabcd6f4cb6927837205cfb7}"' "${script}"; then
  echo "acceptance must default to the v0.2.17 EndpointAgent.zip SHA256" >&2
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

if ! grep -Fq 'restore_remote_bridge_runtime_env_override' "${script}"; then
  echo "acceptance must restore the remote-bridge Deployment runtime env override during cleanup" >&2
  exit 1
fi

if ! grep -Fq 'if ! restore_remote_bridge_runtime_env_override; then' "${script}"; then
  echo "acceptance cleanup must attempt to restore the Deployment env override" >&2
  exit 1
fi

if ! grep -Fq 'CLEANUP_WARN remote-bridge runtime env restore failed' "${script}"; then
  echo "acceptance cleanup must warn when Deployment env restore fails" >&2
  exit 1
fi

if ! grep -Fq 'REMOTE_BRIDGE_ORIGINAL_ENV_FILE' "${script}"; then
  echo "acceptance must back up the remote-bridge Deployment env before applying a step-up override" >&2
  exit 1
fi

if ! grep -Fq 'hadStepUpEnv' "${script}"; then
  echo "acceptance must restore only the original step-up env entry instead of replacing the whole env array blindly" >&2
  exit 1
fi

if ! grep -Fq 'hadRunScopedAnnotation' "${script}"; then
  echo "acceptance must restore or remove the run-scoped step-up Deployment annotation during cleanup" >&2
  exit 1
fi

if ! grep -Fq '(.metadata.annotations // {}) as $annotations' "${script}"; then
  echo "acceptance must capture and verify the top-level Deployment annotation written by kubectl annotate deploy" >&2
  exit 1
fi

if ! grep -Fq 'apply_run_scoped_step_up_runtime_env_override' "${script}"; then
  echo "acceptance must inject the run-scoped step-up key through a Deployment env override" >&2
  exit 1
fi

if ! grep -Fq -- '--rawfile publicKey "$public_path"' "${script}"; then
  echo "acceptance must load the run-scoped public key directly from the generated public key file" >&2
  exit 1
fi

if ! grep -Fq 'value: $publicKey' "${script}"; then
  echo "acceptance must inject the run-scoped public key as a transient Deployment env literal" >&2
  exit 1
fi

if ! grep -Fq 'map(select(.name != "REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM"))' "${script}"; then
  echo "acceptance must replace any prior explicit step-up env var instead of duplicating it" >&2
  exit 1
fi

if grep -Fq 'patch secret endpoint-admin-remote-bridge-secrets' "${script}"; then
  echo "acceptance must not write the run-scoped key into the ESO-owned steady-state Secret" >&2
  exit 1
fi

if grep -Fq 'create secret generic' "${script}"; then
  echo "acceptance must not create a run-scoped Secret because the test namespace may be at Secret quota" >&2
  exit 1
fi

if grep -Fq 'pause_step_up_external_secret_refresh' "${script}"; then
  echo "acceptance must not mutate the ExternalSecret to inject run-scoped step-up material" >&2
  exit 1
fi

if ! grep -Fq 'STEP_UP_RUNTIME_STABILIZE_SECONDS' "${script}"; then
  echo "acceptance must wait briefly after broker rollout before final step-up runtime SHA checks" >&2
  exit 1
fi

if ! grep -Fq 'runtime_step_up_public_key_matches' "${script}"; then
  echo "acceptance must verify the broker runtime step-up public key after rollout" >&2
  exit 1
fi

if ! grep -Fq 'sha256_public_key_material_file' "${script}"; then
  echo "acceptance must compare step-up public keys by canonical key material hash, not raw PEM bytes" >&2
  exit 1
fi

if ! grep -Fq "grep -v -- '-----'" "${script}"; then
  echo "acceptance must strip PEM armor before hashing step-up public key material" >&2
  exit 1
fi

if ! grep -Fq 'step-up-runtime-public-key-drift' "${script}"; then
  echo "acceptance must fail clearly when the broker runtime step-up public key does not match the run-scoped key" >&2
  exit 1
fi

if ! grep -Fq 'step-up-runtime-public-key-drift-after-env-override' "${script}"; then
  echo "acceptance must fail clearly when the Deployment env override does not reach broker runtime" >&2
  exit 1
fi

echo "agentpc2 constrained-executor acceptance static guard passed"
