#!/usr/bin/env bash
set -euo pipefail

# Wait for ArgoCD auto-sync to apply the merged immutable backend image pins.
# Deployment ordering is desired state in the test overlay's sync-wave
# annotations. This verifier is read-only: it never starts a sync operation or
# mutates a Kubernetes workload.

APP="${APP:-platform-test}"
ARGOCD_CONTEXT="${ARGOCD_CONTEXT:-k3d-prod}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
REVISION="${REVISION:-${GITHUB_SHA:-}}"
DIGEST_MAP="${DIGEST_MAP:-}"
FULL_SYNC_TIMEOUT="${FULL_SYNC_TIMEOUT:-900}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
EXPECTED_TARGET_REVISION="${EXPECTED_TARGET_REVISION:-main}"
REQUIRED_STABLE_POLLS="${REQUIRED_STABLE_POLLS:-2}"
SUPERSESSION_CHECK_INTERVAL="${SUPERSESSION_CHECK_INTERVAL:-60}"
REPORT_PATH="${REPORT_PATH:-}"
CURRENT_PHASE="preflight"
VERDICT="FAIL"
NORMALIZED_DIGEST_MAP='{}'

# Invoked indirectly by the EXIT trap below.
# shellcheck disable=SC2329
write_report() {
  [[ -n "$REPORT_PATH" ]] || return 0
  local sync_status=""
  local health_status=""
  local observed_revision=""
  local expected_digests='{}'
  local report_tmp="${REPORT_PATH}.tmp"

  sync_status=$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" -o jsonpath='{.status.sync.status}' 2>/dev/null) || true
  health_status=$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" -o jsonpath='{.status.health.status}' 2>/dev/null) || true
  observed_revision=$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" -o jsonpath='{.status.sync.revision}' 2>/dev/null) || true
  expected_digests=$(jq -c . <<< "$NORMALIZED_DIGEST_MAP" 2>/dev/null) || expected_digests='{}'
  mkdir -p "$(dirname "$REPORT_PATH")" || return 0

  jq -n \
    --arg verdict "$VERDICT" \
    --arg failed_or_last_phase "$CURRENT_PHASE" \
    --arg requested_revision "$REVISION" \
    --arg observed_revision "$observed_revision" \
    --arg sync_status "$sync_status" \
    --arg health_status "$health_status" \
    --argjson expected_digests "$expected_digests" \
    '{
      schemaVersion: "testai-backend-argocd-auto-sync-v2",
      verdict: $verdict,
      failedOrLastPhase: $failed_or_last_phase,
      requestedRevision: $requested_revision,
      observedRevision: $observed_revision,
      syncStatus: $sync_status,
      healthStatus: $health_status,
      reconciliationOwner: "argocd-auto-sync-waves",
      verificationMode: "read-only-exact-convergence",
      verifierMutationPerformed: false,
      expectedDigests: $expected_digests
    }' > "$report_tmp" || {
      echo "WARN: failed to render ArgoCD convergence report" >&2
      rm -f "$report_tmp"
      return 0
    }
  if ! mv "$report_tmp" "$REPORT_PATH"; then
    echo "WARN: failed to publish ArgoCD convergence report to $REPORT_PATH" >&2
    rm -f "$report_tmp"
  fi
  return 0
}
trap 'write_report || true' EXIT

[[ "$REVISION" =~ ^[a-f0-9]{40}$ ]] || {
  echo "FAIL: REVISION must be a 40-character lowercase git SHA" >&2
  exit 1
}
[[ -n "$DIGEST_MAP" ]] || {
  echo "FAIL: DIGEST_MAP is required" >&2
  exit 1
}
[[ "$FULL_SYNC_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || {
  echo "FAIL: FULL_SYNC_TIMEOUT must be a positive integer" >&2
  exit 1
}
[[ "$POLL_INTERVAL" =~ ^[1-9][0-9]*$ ]] || {
  echo "FAIL: POLL_INTERVAL must be a positive integer" >&2
  exit 1
}
[[ "$REQUIRED_STABLE_POLLS" =~ ^[2-9][0-9]*$ ]] || {
  echo "FAIL: REQUIRED_STABLE_POLLS must be an integer of at least 2" >&2
  exit 1
}
[[ "$SUPERSESSION_CHECK_INTERVAL" =~ ^[1-9][0-9]*$ ]] || {
  echo "FAIL: SUPERSESSION_CHECK_INTERVAL must be a positive integer" >&2
  exit 1
}

for command in git kubectl jq python3; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "FAIL: required command not found: $command" >&2
    exit 1
  }
done
ARGOCD_BIN=$(bash scripts/deploy/ensure-argocd-cli.sh)
[[ -x "$ARGOCD_BIN" ]] || {
  echo "FAIL: verified ArgoCD CLI is not executable: $ARGOCD_BIN" >&2
  exit 1
}

NORMALIZED_DIGEST_MAP=$(printf '%s' "$DIGEST_MAP" \
  | python3 scripts/automation/backend-testai-digest-contract.py normalize)

kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
  get application "$APP" >/dev/null

target_revision=$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
  get application "$APP" -o json \
  | jq -r '.spec.source.targetRevision // (.spec.sources[0].targetRevision // "")')
if [[ -z "$target_revision" ]]; then
  echo "FAIL: ArgoCD app targetRevision is empty" >&2
  exit 1
fi
if [[ "$target_revision" != "$EXPECTED_TARGET_REVISION" ]]; then
  echo "FAIL: ArgoCD targetRevision $target_revision differs from required GitOps authority $EXPECTED_TARGET_REVISION" >&2
  exit 1
fi

core_kubeconfig="${RUNNER_TEMP:-/tmp}/argocd-core-${APP}-backend-kubeconfig"
kubectl config view --raw > "$core_kubeconfig"
kubectl --kubeconfig "$core_kubeconfig" config set-context \
  "$ARGOCD_CONTEXT" --namespace "$ARGOCD_NAMESPACE" >/dev/null
export KUBECONFIG="$core_kubeconfig"
ARGOCD=("$ARGOCD_BIN" --core --kube-context "$ARGOCD_CONTEXT")

CURRENT_PHASE="argocd-auto-sync-convergence"
echo "== Wait for ArgoCD auto-sync waves @ $REVISION =="
deadline=$((SECONDS + FULL_SYNC_TIMEOUT))
sync_status=""
health_status=""
observed_revision=""
operation_phase=""
operation_revision=""
stable_polls=0
last_supersession_check=$SECONDS

while (( SECONDS < deadline )); do
  app_json=$("${ARGOCD[@]}" app get "$APP" --hard-refresh -o json)
  sync_status=$(jq -r '.status.sync.status // ""' <<< "$app_json")
  health_status=$(jq -r '.status.health.status // ""' <<< "$app_json")
  observed_revision=$(jq -r '.status.sync.revision // ""' <<< "$app_json")
  operation_phase=$(jq -r '.status.operationState.phase // ""' <<< "$app_json")
  operation_revision=$(jq -r '.status.operationState.syncResult.revision // ""' <<< "$app_json")

  if [[ "$operation_revision" == "$REVISION" \
    && ( "$operation_phase" == "Failed" || "$operation_phase" == "Error" ) ]]; then
    echo "FAIL: ArgoCD auto-sync operation $operation_phase at requested revision $REVISION" >&2
    exit 1
  fi

  # A manifest-neutral main commit may advance status.sync.revision without a
  # new operation, leaving operationState on the previous successful revision.
  # Therefore operationState is a current-operation failure/activity guard,
  # while exact sync revision + aggregate health remain convergence authority.
  if [[ "$observed_revision" == "$REVISION" \
    && "$sync_status" == "Synced" \
    && "$health_status" == "Healthy" \
    && "$operation_phase" != "Running" \
    && "$operation_phase" != "Terminating" ]]; then
    stable_polls=$((stable_polls + 1))
    echo "STABLE: exact healthy convergence poll ${stable_polls}/${REQUIRED_STABLE_POLLS}"
    if (( stable_polls >= REQUIRED_STABLE_POLLS )); then
      CURRENT_PHASE="main-revision-fence"
      git fetch origin main --depth=1 --quiet
      latest_main=$(git rev-parse FETCH_HEAD)
      if [[ "$latest_main" != "$REVISION" ]]; then
        echo "FAIL: requested revision $REVISION was superseded by main $latest_main" >&2
        exit 1
      fi
      VERDICT="PASS"
      echo "PASS: ArgoCD auto-sync converged at exact current main revision $REVISION"
      exit 0
    fi
  else
    stable_polls=0
  fi

  if (( SECONDS - last_supersession_check >= SUPERSESSION_CHECK_INTERVAL )); then
    CURRENT_PHASE="main-revision-fence"
    git fetch origin main --depth=1 --quiet
    latest_main=$(git rev-parse FETCH_HEAD)
    if [[ "$latest_main" != "$REVISION" ]]; then
      echo "FAIL: requested revision $REVISION was superseded by main $latest_main" >&2
      exit 1
    fi
    CURRENT_PHASE="argocd-auto-sync-convergence"
    last_supersession_check=$SECONDS
  fi

  echo "WAIT: observed=${observed_revision:-none} sync=${sync_status:-none} health=${health_status:-none} operation=${operation_phase:-none}"
  sleep "$POLL_INTERVAL"
done

echo "FAIL: ArgoCD did not reach exact Synced/Healthy revision $REVISION within ${FULL_SYNC_TIMEOUT}s (observed=${observed_revision:-none} sync=${sync_status:-none} health=${health_status:-none})" >&2
exit 1
