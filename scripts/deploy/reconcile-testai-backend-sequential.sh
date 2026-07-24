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
REQUESTED_REVISION="$REVISION"
DIGEST_MAP="${DIGEST_MAP:-}"
FULL_SYNC_TIMEOUT="${FULL_SYNC_TIMEOUT:-900}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
EXPECTED_TARGET_REVISION="${EXPECTED_TARGET_REVISION:-main}"
REQUIRED_STABLE_POLLS="${REQUIRED_STABLE_POLLS:-2}"
SUPERSESSION_CHECK_INTERVAL="${SUPERSESSION_CHECK_INTERVAL:-60}"
OUT_OF_SYNC_GRACE="${OUT_OF_SYNC_GRACE:-60}"
REQUIRED_DRIFT_POLLS="${REQUIRED_DRIFT_POLLS:-3}"
HARD_REFRESH_INTERVAL="${HARD_REFRESH_INTERVAL:-60}"
REPORT_PATH="${REPORT_PATH:-}"
CURRENT_PHASE="preflight"
VERDICT="FAIL"
NORMALIZED_DIGEST_MAP='{}'
LAST_OUT_OF_SYNC_RESOURCES='[]'
LAST_OPERATION_PHASE=""
LAST_OPERATION_REVISION=""
CORE_KUBECONFIG=""

# Invoked through finalize_report from the EXIT trap.
# shellcheck disable=SC2329
write_report() {
  [[ -n "$REPORT_PATH" ]] || return 1
  local sync_status=""
  local health_status=""
  local observed_revision=""
  local expected_digests='{}'
  local out_of_sync_resources='[]'
  local report_tmp="${REPORT_PATH}.tmp"

  sync_status=$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" -o jsonpath='{.status.sync.status}' 2>/dev/null) || true
  health_status=$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" -o jsonpath='{.status.health.status}' 2>/dev/null) || true
  observed_revision=$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" -o jsonpath='{.status.sync.revision}' 2>/dev/null) || true
  if ! expected_digests=$(jq -ce 'select(type == "object")' \
    <<< "$NORMALIZED_DIGEST_MAP" 2>/dev/null) || [[ -z "$expected_digests" ]]; then
    expected_digests='{}'
  fi
  if ! out_of_sync_resources=$(jq -ce 'select(type == "array")' \
    <<< "$LAST_OUT_OF_SYNC_RESOURCES" 2>/dev/null) || [[ -z "$out_of_sync_resources" ]]; then
    out_of_sync_resources='[]'
  fi
  mkdir -p "$(dirname "$REPORT_PATH")" || return 1
  umask 077
  rm -f "$report_tmp"

  jq -n \
    --arg verdict "$VERDICT" \
    --arg failed_or_last_phase "$CURRENT_PHASE" \
    --arg requested_revision "$REQUESTED_REVISION" \
    --arg effective_revision "$REVISION" \
    --arg observed_revision "$observed_revision" \
    --arg sync_status "$sync_status" \
    --arg health_status "$health_status" \
    --arg operation_phase "$LAST_OPERATION_PHASE" \
    --arg operation_revision "$LAST_OPERATION_REVISION" \
    --argjson expected_digests "$expected_digests" \
    --argjson out_of_sync_resources "$out_of_sync_resources" \
    '{
      schemaVersion: "testai-backend-argocd-auto-sync-v4",
      verdict: $verdict,
      failedOrLastPhase: $failed_or_last_phase,
      requestedRevision: $requested_revision,
      effectiveRevision: $effective_revision,
      observedRevision: $observed_revision,
      syncStatus: $sync_status,
      healthStatus: $health_status,
      operationPhase: $operation_phase,
      operationRevision: $operation_revision,
      reconciliationOwner: "argocd-auto-sync-waves",
      verificationMode: "read-only-exact-convergence",
      verifierMutationPerformed: false,
      diagnosticDataClassification: "resource-identifiers-only-no-manifest-diff",
      outOfSyncResources: $out_of_sync_resources,
      expectedDigests: $expected_digests
    }' > "$report_tmp" || {
      rm -f "$report_tmp"
      return 1
    }
  chmod 0600 "$report_tmp" || {
    rm -f "$report_tmp"
    return 1
  }
  mv "$report_tmp" "$REPORT_PATH" || {
    rm -f "$report_tmp"
    return 1
  }
  [[ -s "$REPORT_PATH" ]]
}

# shellcheck disable=SC2329
finalize_report() {
  local original_status=$?
  trap - EXIT
  if ! write_report; then
    echo "FAIL: ArgoCD convergence evidence report could not be published" >&2
    if (( original_status == 0 )); then
      original_status=1
    fi
  fi
  if [[ -n "$CORE_KUBECONFIG" && -e "$CORE_KUBECONFIG" ]]; then
    if ! rm -f -- "$CORE_KUBECONFIG" || [[ -e "$CORE_KUBECONFIG" ]]; then
      echo "FAIL: credential-bearing ArgoCD core kubeconfig could not be removed" >&2
      original_status=1
    fi
  fi
  exit "$original_status"
}
trap finalize_report EXIT

REVISION_ADVANCED=false
refresh_semantic_main_fence() {
  local latest_main latest_file latest_map

  REVISION_ADVANCED=false
  git fetch origin main --depth=1 --quiet
  latest_main=$(git rev-parse FETCH_HEAD)
  [[ "$latest_main" != "$REVISION" ]] || return 0

  latest_file=$(mktemp "${TMPDIR:-/tmp}/testai-reconcile-overlay-latest.XXXXXX")
  if ! git show "${latest_main}:kustomize/overlays/test/kustomization.yaml" > "$latest_file"; then
    rm -f "$latest_file"
    echo "FAIL: unable to inspect newer main backend map" >&2
    return 1
  fi
  if ! latest_map=$(python3 scripts/automation/backend-testai-digest-contract.py inspect \
    --kustomization "$latest_file"); then
    rm -f "$latest_file"
    echo "FAIL: newer main backend map is invalid" >&2
    return 1
  fi
  rm -f "$latest_file"
  [[ "$latest_map" == "$NORMALIZED_DIGEST_MAP" ]] || {
    echo "FAIL: requested backend map was superseded on main" >&2
    return 1
  }
  git diff --quiet "$REVISION" "$latest_main" -- \
    kustomize/overlays/test/kustomization.yaml \
    docs/operations/services.yaml \
    .github/workflows/deploy-backend-testai.yml \
    .github/workflows/verify-testai-backend-rollout.yml \
    argocd/applications/platform-test.yaml \
    scripts/automation/backend-testai-digest-contract.py \
    scripts/automation/sync-test-overlay.sh \
    scripts/automation/apply-test-overlay-digests.py \
    scripts/deploy/reconcile-testai-backend-sequential.sh \
    scripts/deploy/ensure-argocd-cli.sh \
    scripts/deploy/verify-testai-backend-runtime.sh \
    scripts/deploy/verify-pod-digest.sh \
    scripts/deploy/gate-stability-window.sh \
    .github/workflows/faz25-fullats-live-browser-acceptance.yml \
    scripts/ats/verify-fullats-live-runtime.sh \
    scripts/ats/fullats-live-browser-acceptance.sh \
    scripts/ats/fullats-live-browser-acceptance.cjs \
    scripts/ats/d29-smoke.sh || {
      echo "FAIL: backend verifier contract was superseded on main" >&2
      return 1
    }

  echo "NOTICE: adopting newer main revision with the same immutable backend map and verifier contract"
  REVISION="$latest_main"
  REVISION_ADVANCED=true
}

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
[[ "$OUT_OF_SYNC_GRACE" =~ ^[1-9][0-9]*$ ]] || {
  echo "FAIL: OUT_OF_SYNC_GRACE must be a positive integer" >&2
  exit 1
}
(( OUT_OF_SYNC_GRACE >= 30 && OUT_OF_SYNC_GRACE <= 300 )) || {
  echo "FAIL: OUT_OF_SYNC_GRACE must be between 30 and 300 seconds" >&2
  exit 1
}
[[ "$REQUIRED_DRIFT_POLLS" =~ ^[2-9][0-9]*$ ]] || {
  echo "FAIL: REQUIRED_DRIFT_POLLS must be an integer of at least 2" >&2
  exit 1
}
[[ "$HARD_REFRESH_INTERVAL" =~ ^[1-9][0-9]*$ ]] || {
  echo "FAIL: HARD_REFRESH_INTERVAL must be a positive integer" >&2
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

umask 077
CORE_KUBECONFIG=$(mktemp \
  "${RUNNER_TEMP:-/tmp}/argocd-core-${APP}-${GITHUB_RUN_ID:-local}.XXXXXX")
[[ -f "$CORE_KUBECONFIG" && ! -L "$CORE_KUBECONFIG" ]] || {
  echo "FAIL: ArgoCD core kubeconfig is not a regular file" >&2
  exit 1
}
kubectl config view --raw --minify --context "$ARGOCD_CONTEXT" \
  > "$CORE_KUBECONFIG"
chmod 0600 "$CORE_KUBECONFIG"
if stat -c '%a' "$CORE_KUBECONFIG" >/dev/null 2>&1; then
  [[ "$(stat -c '%a' "$CORE_KUBECONFIG")" == "600" ]]
else
  [[ "$(stat -f '%Lp' "$CORE_KUBECONFIG")" == "600" ]]
fi
kubectl --kubeconfig "$CORE_KUBECONFIG" config set-context \
  "$ARGOCD_CONTEXT" --namespace "$ARGOCD_NAMESPACE" >/dev/null
export KUBECONFIG="$CORE_KUBECONFIG"
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
out_of_sync_since=-1
drift_polls=0
last_hard_refresh=$((SECONDS - HARD_REFRESH_INTERVAL))

while (( SECONDS < deadline )); do
  hard_refresh=false
  if (( SECONDS - last_hard_refresh >= HARD_REFRESH_INTERVAL )); then
    hard_refresh=true
    if ! app_json=$("${ARGOCD[@]}" app get "$APP" --hard-refresh -o json); then
      LAST_OUT_OF_SYNC_RESOURCES='[]'
      LAST_OPERATION_PHASE=""
      LAST_OPERATION_REVISION=""
      CURRENT_PHASE="argocd-status-read"
      echo "FAIL: unable to read refreshed ArgoCD Application status" >&2
      exit 1
    fi
    last_hard_refresh=$SECONDS
  elif ! app_json=$("${ARGOCD[@]}" app get "$APP" -o json); then
    LAST_OUT_OF_SYNC_RESOURCES='[]'
    LAST_OPERATION_PHASE=""
    LAST_OPERATION_REVISION=""
    CURRENT_PHASE="argocd-status-read"
    echo "FAIL: unable to read ArgoCD Application status" >&2
    exit 1
  fi
  if ! jq -e 'type == "object" and (.status | type == "object")' \
    >/dev/null <<< "$app_json"; then
    LAST_OUT_OF_SYNC_RESOURCES='[]'
    LAST_OPERATION_PHASE=""
    LAST_OPERATION_REVISION=""
    CURRENT_PHASE="argocd-status-read"
    echo "FAIL: ArgoCD Application status response is not valid JSON status" >&2
    exit 1
  fi
  sync_status=$(jq -r '.status.sync.status // ""' <<< "$app_json")
  health_status=$(jq -r '.status.health.status // ""' <<< "$app_json")
  observed_revision=$(jq -r '.status.sync.revision // ""' <<< "$app_json")
  operation_phase=$(jq -r '.status.operationState.phase // ""' <<< "$app_json")
  operation_revision=$(jq -r '.status.operationState.syncResult.revision // ""' <<< "$app_json")
  LAST_OPERATION_PHASE="$operation_phase"
  LAST_OPERATION_REVISION="$operation_revision"
  LAST_OUT_OF_SYNC_RESOURCES=$(jq -c '[
    .status.resources[]?
    | select(.status == "OutOfSync")
    | (.kind == "Secret" or .kind == "ConfigMap") as $sensitive
    | {
        group: (.group // ""),
        kind: (.kind // ""),
        namespace: (.namespace // ""),
        name: (if $sensitive then "[redacted-sensitive-resource-name]" else (.name // "") end),
        sensitiveIdentifierRedacted: $sensitive,
        status: (.status // ""),
        health: (.health.status // "")
      }
  ]' <<< "$app_json")

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
      if ! refresh_semantic_main_fence; then
        exit 1
      fi
      if [[ "$REVISION_ADVANCED" == "true" ]]; then
        stable_polls=0
        CURRENT_PHASE="argocd-auto-sync-convergence"
        continue
      fi
      VERDICT="PASS"
      echo "PASS: ArgoCD auto-sync converged at exact current main revision $REVISION"
      exit 0
    fi
  else
    stable_polls=0
  fi

  # Once ArgoCD is idle at the exact healthy revision, persistent aggregate
  # drift is not rollout latency. Fail with resource identifiers after a short
  # grace window so desired-state drift can be repaired without exposing
  # manifest values or secret-bearing diffs in CI artifacts.
  # operationRevision is intentionally diagnostic only: manifest-neutral main
  # commits can advance status.sync.revision while operationState remains on the
  # previous successful revision.
  if [[ "$observed_revision" == "$REVISION" \
    && "$sync_status" == "OutOfSync" \
    && "$health_status" == "Healthy" \
    && "$operation_phase" != "Running" \
    && "$operation_phase" != "Terminating" ]]; then
    drift_polls=$((drift_polls + 1))
    if (( out_of_sync_since < 0 )); then
      out_of_sync_since=$SECONDS
      echo "DRIFT: exact healthy revision remains OutOfSync; starting ${OUT_OF_SYNC_GRACE}s/${REQUIRED_DRIFT_POLLS}-poll diagnostic grace"
    elif (( SECONDS - out_of_sync_since >= OUT_OF_SYNC_GRACE \
      && drift_polls >= REQUIRED_DRIFT_POLLS )); then
      CURRENT_PHASE="argocd-resource-drift"
      echo "FAIL: ArgoCD remains OutOfSync at exact healthy revision $REVISION after ${OUT_OF_SYNC_GRACE}s" >&2
      if [[ "$LAST_OUT_OF_SYNC_RESOURCES" == "[]" ]]; then
        echo "DRIFT_RESOURCE: Application reported OutOfSync without resource-level status entries" >&2
      else
        jq -r '.[] | "DRIFT_RESOURCE: \(.group)/\(.kind) \(.namespace)/\(.name) status=\(.status) health=\(.health)"' \
          <<< "$LAST_OUT_OF_SYNC_RESOURCES" >&2
      fi
      exit 1
    fi
  else
    out_of_sync_since=-1
    drift_polls=0
  fi

  if (( SECONDS - last_supersession_check >= SUPERSESSION_CHECK_INTERVAL )); then
    CURRENT_PHASE="main-revision-fence"
    if ! refresh_semantic_main_fence; then
      exit 1
    fi
    if [[ "$REVISION_ADVANCED" == "true" ]]; then
      stable_polls=0
      out_of_sync_since=-1
      drift_polls=0
    fi
    CURRENT_PHASE="argocd-auto-sync-convergence"
    last_supersession_check=$SECONDS
  fi

  echo "WAIT: observed=${observed_revision:-none} sync=${sync_status:-none} health=${health_status:-none} operation=${operation_phase:-none} hardRefresh=${hard_refresh}"
  sleep "$POLL_INTERVAL"
done

echo "FAIL: ArgoCD did not reach exact Synced/Healthy revision $REVISION within ${FULL_SYNC_TIMEOUT}s (observed=${observed_revision:-none} sync=${sync_status:-none} health=${health_status:-none})" >&2
exit 1
