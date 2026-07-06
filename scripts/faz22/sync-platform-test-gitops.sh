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
TEST_CONTEXT="${TEST_CONTEXT:-k3d-test}"
TEST_NAMESPACE="${TEST_NAMESPACE:-platform-test}"
OVERLAY_PATH="${OVERLAY_PATH:-kustomize/overlays/test}"
ESO_OVERLAY_PATH="${ESO_OVERLAY_PATH:-kustomize/overlays/test/eso}"
ALLOW_KUBECTL_SELECTED_RESOURCE_FALLBACK="${ALLOW_KUBECTL_SELECTED_RESOURCE_FALLBACK:-false}"
SYNC_MODE="argocd"

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
    --arg sync_mode "$SYNC_MODE" \
    '{
      verdict: $verdict,
      reason: $reason,
      app: $app,
      argocd_context: $argocd_context,
      argocd_namespace: $argocd_namespace,
      sync_mode: $sync_mode,
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

prepare_argocd_core_kubeconfig() {
  local core_kubeconfig
  core_kubeconfig="${RUNNER_TEMP:-/tmp}/argocd-core-${APP}-kubeconfig"
  kubectl config view --raw > "$core_kubeconfig"
  kubectl --kubeconfig "$core_kubeconfig" config set-context \
    "$ARGOCD_CONTEXT" \
    --namespace "$ARGOCD_NAMESPACE" >/dev/null
  export KUBECONFIG="$core_kubeconfig"
}

ensure_argocd_application() {
  if kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" >/dev/null 2>&1; then
    return 0
  fi

  local app_manifest="argocd/applications/${APP}.yaml"
  if [[ ! -f "$app_manifest" ]]; then
    fail "ArgoCD Application $APP missing and manifest not found at $app_manifest"
  fi

  echo "ArgoCD Application $APP missing; applying desired Application manifest $app_manifest"
  # This bootstraps the ArgoCD control-plane object only. Workloads are still
  # reconciled by ArgoCD from kustomize/overlays/test; the script does not
  # patch/edit/set-image any platform-test workload directly.
  kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" apply -f "$app_manifest"

  kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" >/dev/null || fail "ArgoCD Application $APP still missing after bootstrap apply"
}

render_resource() {
  local render_file="$1"
  local kind="$2"
  local name="$3"
  local output_file="$4"

  python3 - "$render_file" "$kind" "$name" "$output_file" <<'PY'
from pathlib import Path
import sys

render_file, want_kind, want_name, output_file = sys.argv[1:5]
text = Path(render_file).read_text()

def top_level_value(lines, key):
    prefix = f"{key}:"
    for line in lines:
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None

def metadata_name(lines):
    in_meta = False
    for line in lines:
        if line == "metadata:":
            in_meta = True
            continue
        if in_meta and line and not line.startswith(" "):
            return None
        if in_meta and line.startswith("  name:"):
            return line.split(":", 1)[1].strip()
    return None

for raw in text.split("\n---"):
    doc = raw.strip()
    if not doc:
        continue
    lines = doc.splitlines()
    if top_level_value(lines, "kind") == want_kind and metadata_name(lines) == want_name:
        Path(output_file).write_text(doc + "\n")
        sys.exit(0)

print(f"resource not found in render: {want_kind}/{want_name}", file=sys.stderr)
sys.exit(1)
PY
}

resolve_app_target_revision() {
  kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
    get application "$APP" -o json \
    | jq -r '.spec.source.targetRevision // (.spec.sources[0].targetRevision // "")'
}

sync_argocd_application() {
  local app_target_revision
  app_target_revision="$(resolve_app_target_revision)"
  if [[ -z "$app_target_revision" ]]; then
    fail "ArgoCD app targetRevision is empty"
  fi

  if [[ "$app_target_revision" == "$REVISION" ]]; then
    "${ARGOCD[@]}" app sync "$APP" --revision "$REVISION" --timeout "$TIMEOUT"
    return 0
  fi

  if [[ ! "$app_target_revision" =~ ^[0-9a-f]{40}$ ]]; then
    echo "ArgoCD app targetRevision is $app_target_revision; syncing configured target and enforcing observed revision $REVISION"
    "${ARGOCD[@]}" app sync "$APP" --timeout "$TIMEOUT"
    return 0
  fi

  fail "ArgoCD app targetRevision $app_target_revision does not match requested revision $REVISION"
}

sync_with_kubectl_overlay_fallback() {
  if [[ "$ALLOW_KUBECTL_SELECTED_RESOURCE_FALLBACK" != "true" ]]; then
    fail "ArgoCD core sync unavailable and kubectl selected-resource fallback is disabled"
  fi

  SYNC_MODE="kubectl-overlay-selected-resources"
  command -v python3 >/dev/null 2>&1 || fail "python3 not found"

  local render_file eso_render_file tmp_dir external_secret_file configmap_file deployment_file
  tmp_dir="$(mktemp -d)"
  render_file="${tmp_dir}/test-render.yaml"
  eso_render_file="${tmp_dir}/test-eso-render.yaml"
  external_secret_file="${tmp_dir}/endpoint-admin-externalsecret.yaml"
  configmap_file="${tmp_dir}/endpoint-admin-configmap.yaml"
  deployment_file="${tmp_dir}/endpoint-admin-deployment.yaml"

  echo "ArgoCD core unavailable; falling back to selected resources from ${OVERLAY_PATH}"
  kubectl kustomize "$OVERLAY_PATH" > "$render_file"

  if ! render_resource "$render_file" "ExternalSecret" "endpoint-admin-service-secrets" "$external_secret_file"; then
    echo "ExternalSecret not found in ${OVERLAY_PATH}; rendering ${ESO_OVERLAY_PATH}"
    kubectl kustomize "$ESO_OVERLAY_PATH" > "$eso_render_file"
    render_resource "$eso_render_file" "ExternalSecret" "endpoint-admin-service-secrets" "$external_secret_file"
  fi
  render_resource "$render_file" "ConfigMap" "endpoint-admin-service-config" "$configmap_file"
  render_resource "$render_file" "Deployment" "endpoint-admin-service" "$deployment_file"

  kubectl --context "$TEST_CONTEXT" -n "$TEST_NAMESPACE" apply -f "$external_secret_file"
  kubectl --context "$TEST_CONTEXT" -n "$TEST_NAMESPACE" wait \
    externalsecret/endpoint-admin-service-secrets \
    --for=condition=Ready \
    --timeout="${TIMEOUT}s"

  # Exact ConfigMap reconciliation is required for #1267 because the live
  # object can retain stale SSA/field-manager data keys after desired-state key
  # removal. This replace uses the rendered overlay ConfigMap, not an ad-hoc
  # patch, and does not touch any workload image.
  kubectl --context "$TEST_CONTEXT" -n "$TEST_NAMESPACE" replace --force -f "$configmap_file"

  kubectl --context "$TEST_CONTEXT" -n "$TEST_NAMESPACE" apply -f "$deployment_file"
  kubectl --context "$TEST_CONTEXT" -n "$TEST_NAMESPACE" rollout status \
    deployment/endpoint-admin-service \
    --timeout="${TIMEOUT}s"

  write_report "PASS" "ArgoCD core unavailable; selected endpoint-admin resources reconciled from ${OVERLAY_PATH}"
  echo "PASS: selected endpoint-admin resources reconciled from ${OVERLAY_PATH}"
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

ensure_argocd_application

prepare_argocd_core_kubeconfig
ARGOCD=(argocd --core --kube-context "$ARGOCD_CONTEXT")

echo "-- before sync --"
if ! "${ARGOCD[@]}" app get "$APP"; then
  sync_with_kubectl_overlay_fallback
  exit 0
fi

if ! sync_argocd_application; then
  sync_with_kubectl_overlay_fallback
  exit 0
fi
if ! "${ARGOCD[@]}" app wait "$APP" --sync --health --timeout "$TIMEOUT"; then
  sync_with_kubectl_overlay_fallback
  exit 0
fi

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
