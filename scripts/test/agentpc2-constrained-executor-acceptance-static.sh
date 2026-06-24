#!/usr/bin/env bash
set -euo pipefail

script="scripts/faz22-remote-ops/agentpc2-constrained-executor-acceptance.sh"
policy_validator="scripts/faz22-remote-ops/check-endpoint-agent-release-policy.sh"

if [[ ! -f "${script}" ]]; then
  echo "missing ${script}" >&2
  exit 1
fi

"${policy_validator}" >/dev/null

if ! grep -Fq 'TOKEN_CLIENT_CANDIDATES="${TOKEN_CLIENT_CANDIDATES:-remote-bridge-operator-api frontend}"' "${script}"; then
  echo "acceptance must try the dedicated remote-bridge-operator-api client before frontend" >&2
  exit 1
fi

if ! grep -Fq 'source "${SCRIPT_DIR}/endpoint-agent-release-policy.sh"' "${script}"; then
  echo "acceptance must load the shared EndpointAgent release policy" >&2
  exit 1
fi

if ! grep -Fq 'endpoint_agent_release_policy_load "$REPO_ROOT"' "${script}"; then
  echo "acceptance must source release defaults from the policy SSOT" >&2
  exit 1
fi

if ! grep -Fq 'EXPECTED_RELEASE_TAG="${EXPECTED_RELEASE_TAG:-$EXPECTED_AGENT_TAG}"' "${script}"; then
  echo "acceptance release tag must default from the policy-loaded agent tag" >&2
  exit 1
fi

if grep -Eq 'EXPECTED_AGENT_(VERSION|SHA256|ZIP_SHA256)="\$\{EXPECTED_AGENT_(VERSION|SHA256|ZIP_SHA256):-[^$]' "${script}"; then
  echo "acceptance must not hard-code release metadata defaults outside the policy SSOT" >&2
  exit 1
fi

if ! grep -Fq 'REMOTE_BRIDGE_ROLLOUT_TIMEOUT_SECONDS="${REMOTE_BRIDGE_ROLLOUT_TIMEOUT_SECONDS:-420}"' "${script}"; then
  echo "acceptance must default remote-bridge rollout waits to 420s for Java cold-start tolerance" >&2
  exit 1
fi

if ! grep -Fq 'remote-bridge-rollout-timeout-seconds-invalid' "${script}"; then
  echo "acceptance must validate REMOTE_BRIDGE_ROLLOUT_TIMEOUT_SECONDS bounds" >&2
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

if ! grep -Fq 'AGENT_OPERATION_WAIT_SECONDS="${AGENT_OPERATION_WAIT_SECONDS:-45}"' "${script}"; then
  echo "acceptance must use a configurable, jitter-tolerant default wait before exporting agent output recording" >&2
  exit 1
fi

if ! grep -Fq 'REQUIRE_FULL_MATRIX="${REQUIRE_FULL_MATRIX:-0}"' "${script}"; then
  echo "acceptance must expose REQUIRE_FULL_MATRIX instead of hard-coding verifier full-matrix mode" >&2
  exit 1
fi

if ! grep -Fq 'require-full-matrix-invalid' "${script}"; then
  echo "acceptance must validate REQUIRE_FULL_MATRIX as a strict 0/1 input" >&2
  exit 1
fi

if ! grep -Fq 'agent-operation-wait-seconds-invalid' "${script}"; then
  echo "acceptance must validate the agent operation output wait window" >&2
  exit 1
fi

if ! grep -Fq 'sleep "$AGENT_OPERATION_WAIT_SECONDS"' "${script}"; then
  echo "acceptance must not use a fixed short sleep before recording export" >&2
  exit 1
fi

if ! grep -Fq 'run_product_supported_full_matrix_negatives' "${script}"; then
  echo "acceptance must capture product-supported full-matrix negative probes when full matrix mode is requested" >&2
  exit 1
fi

if ! grep -Fq 'curl_json_or_fail' "${script}"; then
  echo "acceptance must convert product-negative curl failures into explicit fail_acceptance summaries" >&2
  exit 1
fi

if grep -Fq 'local body_file="$1" stem="${body_file%.body}"' "${script}"; then
  echo "acceptance must not derive stem from body_file in the same local declaration under set -u" >&2
  exit 1
fi

if ! grep -Fq 'local stem="${body_file%.body}"' "${script}"; then
  echo "acceptance must derive named HTTP evidence stems after body_file is assigned" >&2
  exit 1
fi

if ! awk '
  /^normalize_body_named_http_evidence\(\) \{/ { in_fn=1 }
  in_fn && /return 0/ { found=1 }
  in_fn && /^\}/ { exit found ? 0 : 1 }
  END { if (!found) exit 1 }
' "${script}"; then
  echo "acceptance named HTTP evidence normalizer must return success when request.json is absent" >&2
  exit 1
fi

if grep -Fq 'curl_json_or_fail code ' "${script}"; then
  echo "acceptance must not pass result_var=code to curl_json_or_fail because the helper has a local code variable" >&2
  exit 1
fi

if ! grep -Fq 'curl_json_or_fail wrong_device_code wrong-device-deny' "${script}"; then
  echo "acceptance must store wrong-device probe HTTP status in a non-shadowing variable" >&2
  exit 1
fi

if ! grep -Fq 'curl_json_or_fail closed_session_code closed-session-deny' "${script}"; then
  echo "acceptance must store closed-session probe HTTP status in a non-shadowing variable" >&2
  exit 1
fi

if ! grep -Fq 'wrong-device-deny.body' "${script}"; then
  echo "acceptance must record a product-supported wrong-device/not-enrolled negative probe" >&2
  exit 1
fi

if ! grep -Fq 'closed-session-deny.body' "${script}"; then
  echo "acceptance must record a product-supported closed-session termination negative probe" >&2
  exit 1
fi

if ! grep -Fq 'REQUIRE_FULL_MATRIX="$REQUIRE_FULL_MATRIX"' "${script}"; then
  echo "acceptance must pass REQUIRE_FULL_MATRIX through to the evidence verifier" >&2
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

if ! grep -Fq 'capture_failpath_diagnostics "$reason"' "${script}"; then
  echo "acceptance must capture fail-path diagnostics before writing no-go summary" >&2
  exit 1
fi

if ! grep -Fq 'local verifier_exit=$?' "${script}"; then
  echo "acceptance must capture verifier exit code instead of letting set -e bypass failpath diagnostics" >&2
  exit 1
fi

if ! grep -Fq 'failpath-diagnostics' "${script}"; then
  echo "acceptance no-go evidence must include a failpath-diagnostics bundle" >&2
  exit 1
fi

if ! grep -Fq 'remote-bridge-logs-tail.txt' "${script}"; then
  echo "acceptance no-go evidence must preserve remote-bridge logs before cleanup/rollout changes" >&2
  exit 1
fi

if ! grep -Fq 'session-recording.raw.jsonl' "${script}"; then
  echo "acceptance no-go evidence must attempt to preserve current session recording rows" >&2
  exit 1
fi

if ! grep -Fq 'docker postgres container unavailable for failpath recording export' "${script}"; then
  echo "acceptance failpath recording export must degrade without recursive no-go failures" >&2
  exit 1
fi

echo "agentpc2 constrained-executor acceptance static guard passed"
