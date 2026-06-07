#!/usr/bin/env bash
set -euo pipefail

# Faz 22 GitOps-authoritative test sync helper.
#
# This script intentionally syncs the ArgoCD Application, not Kubernetes
# workloads directly. It is the safe path for test overlay desired-state changes
# such as ConfigMap Replace=true and pod-template rollout markers.

APP="${APP:-platform-test}"
ARGOCD_CONTEXT="${ARGOCD_CONTEXT:-k3d-prod}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
REVISION="${REVISION:-${GITHUB_SHA:-}}"
TIMEOUT="${TIMEOUT:-300}"
REPORT_PATH="${REPORT_PATH:-}"
ARGOCD_VERSION="${ARGOCD_VERSION:-v2.13.1}"

fail() {
  local reason="$1"
  write_report "FAIL" "$reason"
  echo "FAIL: $reason" >&2
  exit 1
}

write_report() {
  local verdict="$1"
  local reason="${2:-}"
  if [[ -z "$REPORT_PATH" ]]; then
    return 0
  fi

  local sync_status health_status observed_revision
  sync_status="$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" -o jsonpath='{.status.sync.status}' 2>/dev/null || true)"
  health_status="$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" -o jsonpath='{.status.health.status}' 2>/dev/null || true)"
  observed_revision="$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" -o jsonpath='{.status.sync.revision}' 2>/dev/null || true)"

  jq -n \
    --arg verdict "$verdict" \
    --arg reason "$reason" \
    --arg app "$APP" \
    --arg argocd_context "$ARGOCD_CONTEXT" \
    --arg argocd_namespace "$ARGOCD_NAMESPACE" \
    --arg requested_revision "$REVISION" \
    --arg observed_revision "$observed_revision" \
    --arg sync_status "$sync_status" \
    --arg health_status "$health_status" \
    '{
      verdict: $verdict,
      reason: $reason,
      app: $app,
      argocd_context: $argocd_context,
      argocd_namespace: $argocd_namespace,
      requested_revision: $requested_revision,
      observed_revision: $observed_revision,
      sync_status: $sync_status,
      health_status: $health_status
    }' > "$REPORT_PATH"
}

ensure_argocd_cli() {
  if command -v argocd >/dev/null 2>&1; then
    return 0
  fi

  local os arch bin tmp_bin
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
    *) fail "unsupported argocd CLI architecture: $arch" ;;
  esac
  case "$os" in
    linux|darwin) ;;
    *) fail "unsupported argocd CLI OS: $os" ;;
  esac

  bin="argocd-${os}-${arch}"
  tmp_bin="${RUNNER_TEMP:-/tmp}/argocd"
  echo "argocd CLI not found; downloading ${ARGOCD_VERSION}/${bin}"
  curl -fsSL \
    "https://github.com/argoproj/argo-cd/releases/download/${ARGOCD_VERSION}/${bin}" \
    -o "$tmp_bin"
  chmod 0755 "$tmp_bin"
  local tmp_dir
  tmp_dir="$(dirname "$tmp_bin")"
  export PATH="$tmp_dir:$PATH"

  command -v argocd >/dev/null 2>&1 || fail "argocd CLI download did not produce executable"
}

if [[ -z "$REVISION" ]]; then
  fail "REVISION or GITHUB_SHA is required"
fi

if ! [[ "$REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  fail "REVISION must be a 40-character lowercase git SHA (got: $REVISION)"
fi

command -v kubectl >/dev/null 2>&1 || fail "kubectl not found"
command -v jq >/dev/null 2>&1 || fail "jq not found"
command -v curl >/dev/null 2>&1 || fail "curl not found"
ensure_argocd_cli

echo "== platform-test GitOps sync =="
echo "app=$APP argocd_context=$ARGOCD_CONTEXT namespace=$ARGOCD_NAMESPACE revision=$REVISION"

kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
  get application "$APP" >/dev/null

ARGOCD=(argocd --core --kube-context "$ARGOCD_CONTEXT" --namespace "$ARGOCD_NAMESPACE")

echo "-- before sync --"
"${ARGOCD[@]}" app get "$APP"

"${ARGOCD[@]}" app sync "$APP" --revision "$REVISION" --timeout "$TIMEOUT"
"${ARGOCD[@]}" app wait "$APP" --sync --health --timeout "$TIMEOUT"

sync_status="$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
  get application "$APP" -o jsonpath='{.status.sync.status}')"
health_status="$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
  get application "$APP" -o jsonpath='{.status.health.status}')"
observed_revision="$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
  get application "$APP" -o jsonpath='{.status.sync.revision}')"

echo "-- after sync --"
echo "sync=$sync_status health=$health_status revision=$observed_revision"

[[ "$sync_status" == "Synced" ]] || fail "ArgoCD app is not Synced ($sync_status)"
[[ "$health_status" == "Healthy" ]] || fail "ArgoCD app is not Healthy ($health_status)"
[[ "$observed_revision" == "$REVISION" ]] || fail "ArgoCD revision mismatch (observed=$observed_revision expected=$REVISION)"

write_report "PASS" ""
echo "PASS: platform-test synced to $REVISION"
