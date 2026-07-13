#!/usr/bin/env bash
set -euo pipefail

# Reconcile immutable backend image pins through ArgoCD one Deployment at a
# time. Sequential resource sync preserves test-cluster quota headroom without
# introducing an imperative kubectl workload mutation path.

APP="${APP:-platform-test}"
ARGOCD_CONTEXT="${ARGOCD_CONTEXT:-k3d-prod}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
TEST_CONTEXT="${TEST_CONTEXT:-k3d-test}"
TEST_NAMESPACE="${TEST_NAMESPACE:-platform-test}"
REVISION="${REVISION:-${GITHUB_SHA:-}}"
DIGEST_MAP="${DIGEST_MAP:-}"
PER_SERVICE_TIMEOUT="${PER_SERVICE_TIMEOUT:-300}"
FULL_SYNC_TIMEOUT="${FULL_SYNC_TIMEOUT:-900}"
REPORT_PATH="${REPORT_PATH:-}"
CURRENT_SERVICE="preflight"
VERDICT="FAIL"

SERVICE_SPECS=(
  "auth-service|auth-service|auth-service"
  "permission-service|permission-service|permission-service"
  "user-service|user-service|user-service"
  "variant-service|variant-service|variant-service"
  "core-data-service|core-data-service|core-data-service"
  "report-service|report-service|report-service"
  "schema-service|schema-service|schema-service"
  "endpoint-admin-service|endpoint-admin-service|endpoint-admin-service"
  "audio-gateway-service|audio-gateway|audio-gateway"
  "meeting-service|meeting-service|meeting-service"
  "transcript-service|transcript-service|transcript-service"
  "audit-event-consumer-service|audit-event-consumer-service|audit-event-consumer-service"
  "api-gateway|api-gateway|api-gateway"
)

write_report() {
  [[ -n "$REPORT_PATH" ]] || return 0
  set +e
  sync_status=$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" -o jsonpath='{.status.sync.status}' 2>/dev/null)
  health_status=$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" -o jsonpath='{.status.health.status}' 2>/dev/null)
  observed_revision=$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" -o jsonpath='{.status.sync.revision}' 2>/dev/null)
  jq -n \
    --arg verdict "$VERDICT" \
    --arg failed_or_last_service "$CURRENT_SERVICE" \
    --arg requested_revision "$REVISION" \
    --arg observed_revision "$observed_revision" \
    --arg sync_status "$sync_status" \
    --arg health_status "$health_status" \
    --argjson expected_digests "${NORMALIZED_DIGEST_MAP:-{}}" \
    '{
      schemaVersion: "testai-backend-sequential-argocd-v1",
      verdict: $verdict,
      failedOrLastService: $failed_or_last_service,
      requestedRevision: $requested_revision,
      observedRevision: $observed_revision,
      syncStatus: $sync_status,
      healthStatus: $health_status,
      mutationPath: "argocd-resource-sync-only",
      expectedDigests: $expected_digests
    }' > "$REPORT_PATH"
}
trap write_report EXIT

[[ "$REVISION" =~ ^[a-f0-9]{40}$ ]] || {
  echo "FAIL: REVISION must be a 40-character lowercase git SHA" >&2
  exit 1
}
[[ -n "$DIGEST_MAP" ]] || {
  echo "FAIL: DIGEST_MAP is required" >&2
  exit 1
}

for command in kubectl jq python3; do
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
if [[ "$target_revision" =~ ^[a-f0-9]{40}$ && "$target_revision" != "$REVISION" ]]; then
  echo "FAIL: ArgoCD targetRevision $target_revision differs from requested $REVISION" >&2
  exit 1
fi

core_kubeconfig="${RUNNER_TEMP:-/tmp}/argocd-core-${APP}-backend-kubeconfig"
kubectl config view --raw > "$core_kubeconfig"
kubectl --kubeconfig "$core_kubeconfig" config set-context \
  "$ARGOCD_CONTEXT" --namespace "$ARGOCD_NAMESPACE" >/dev/null
export KUBECONFIG="$core_kubeconfig"
ARGOCD=("$ARGOCD_BIN" --core --kube-context "$ARGOCD_CONTEXT")

"${ARGOCD[@]}" app get "$APP" --hard-refresh >/dev/null

for spec in "${SERVICE_SPECS[@]}"; do
  IFS='|' read -r service deployment selector <<< "$spec"
  CURRENT_SERVICE="$service"
  digest=$(jq -r --arg service "$service" '.[$service] // empty' \
    <<< "$NORMALIZED_DIGEST_MAP")
  [[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]] || {
    echo "FAIL: expected digest missing for $service" >&2
    exit 1
  }

  echo "== ArgoCD sequential sync: deployment/$deployment @ $digest =="
  "${ARGOCD[@]}" app sync "$APP" \
    --revision "$REVISION" \
    --resource "apps:Deployment:${deployment}" \
    --apply-out-of-sync-only \
    --timeout "$PER_SERVICE_TIMEOUT"

  kubectl --context "$TEST_CONTEXT" -n "$TEST_NAMESPACE" rollout status \
    "deployment/${deployment}" --timeout="${PER_SERVICE_TIMEOUT}s"
  bash scripts/deploy/verify-pod-digest.sh \
    --context "$TEST_CONTEXT" \
    --namespace "$TEST_NAMESPACE" \
    --selector "app.kubernetes.io/name=${selector}" \
    --expected-digest "$digest"
done

CURRENT_SERVICE="full-application-convergence"
echo "== ArgoCD full Application convergence @ $REVISION =="
"${ARGOCD[@]}" app sync "$APP" \
  --revision "$REVISION" \
  --apply-out-of-sync-only \
  --timeout "$FULL_SYNC_TIMEOUT"
"${ARGOCD[@]}" app wait "$APP" \
  --operation --sync --health \
  --timeout "$FULL_SYNC_TIMEOUT"

app_json=$("${ARGOCD[@]}" app get "$APP" -o json)
sync_status=$(jq -r '.status.sync.status // ""' <<< "$app_json")
health_status=$(jq -r '.status.health.status // ""' <<< "$app_json")
observed_revision=$(jq -r '.status.sync.revision // ""' <<< "$app_json")
[[ "$sync_status" == "Synced" ]] || {
  echo "FAIL: ArgoCD app is not Synced ($sync_status)" >&2
  exit 1
}
[[ "$health_status" == "Healthy" ]] || {
  echo "FAIL: ArgoCD app is not Healthy ($health_status)" >&2
  exit 1
}
[[ "$observed_revision" == "$REVISION" ]] || {
  echo "FAIL: ArgoCD revision mismatch (observed=$observed_revision expected=$REVISION)" >&2
  exit 1
}

VERDICT="PASS"
echo "PASS: 13 backend Deployments and full Application reconciled through ArgoCD at $REVISION"
