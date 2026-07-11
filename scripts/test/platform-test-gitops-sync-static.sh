#!/usr/bin/env bash
# shellcheck disable=SC2016
set -euo pipefail

sync_script="scripts/faz22/sync-platform-test-gitops.sh"
verify_script="scripts/faz22/verify-endpoint-admin-openfga-runtime.sh"
sync_workflow=".github/workflows/faz22-platform-test-sync-openfga-verify.yml"
verify_workflow=".github/workflows/faz22-endpoint-admin-openfga-runtime-verify.yml"

for file in "$sync_script" "$verify_script" "$sync_workflow" "$verify_workflow"; do
  if [[ ! -f "$file" ]]; then
    echo "missing $file" >&2
    exit 1
  fi
done

bash -n "$sync_script"
bash -n "$verify_script"

if ! grep -Fq 'prepare_argocd_core_kubeconfig' "$sync_script"; then
  echo "sync helper must prepare a namespace-scoped kubeconfig for ArgoCD core mode" >&2
  exit 1
fi

if ! grep -Fq 'config set-context' "$sync_script" \
  || ! grep -Fq -- '--namespace "$ARGOCD_NAMESPACE"' "$sync_script"; then
  echo "sync helper must set the ArgoCD kube context namespace before invoking argocd --core" >&2
  exit 1
fi

if ! grep -Fq 'ARGOCD=(argocd --core --kube-context "$ARGOCD_CONTEXT")' "$sync_script"; then
  echo "sync helper must run argocd --core against the prepared kube context" >&2
  exit 1
fi

if grep -Fq 'app get "$APP" -N "$ARGOCD_NAMESPACE"' "$sync_script" \
  || grep -Fq 'app sync "$APP" -N "$ARGOCD_NAMESPACE"' "$sync_script" \
  || grep -Fq 'app wait "$APP" -N "$ARGOCD_NAMESPACE"' "$sync_script" \
  || grep -Fq 'argocd --core --kube-context "$ARGOCD_CONTEXT" --namespace' "$sync_script"; then
  echo "sync helper must not use unsupported argocd namespace flags for the control-plane namespace" >&2
  exit 1
fi

if ! grep -Fq 'ALLOW_KUBECTL_SELECTED_RESOURCE_FALLBACK="${ALLOW_KUBECTL_SELECTED_RESOURCE_FALLBACK:-false}"' "$sync_script"; then
  echo "kubectl selected-resource fallback must default to disabled" >&2
  exit 1
fi

if ! grep -Fq 'ArgoCD core sync unavailable and kubectl selected-resource fallback is disabled' "$sync_script"; then
  echo "sync helper must fail closed when ArgoCD core is unavailable and fallback is not explicitly enabled" >&2
  exit 1
fi

if ! grep -Fq 'resolve_app_target_revision' "$sync_script" \
  || ! grep -Fq 'sync_argocd_application' "$sync_script"; then
  echo "sync helper must resolve the live ArgoCD app targetRevision before syncing" >&2
  exit 1
fi

if ! grep -Fq 'ArgoCD app targetRevision is $app_target_revision; syncing configured target and enforcing observed revision $REVISION' "$sync_script"; then
  echo "sync helper must handle branch targetRevision by syncing the configured target and retaining the observed SHA guard" >&2
  exit 1
fi

if ! grep -Fq 'app sync "$APP" --timeout "$TIMEOUT"' "$sync_script"; then
  echo "sync helper must avoid --revision <sha> when ArgoCD app targetRevision is a branch such as main" >&2
  exit 1
fi

if ! grep -Fq 'ArgoCD sync completed but application did not reach Synced/Healthy within ${TIMEOUT}s' "$sync_script"; then
  echo "post-sync health timeout must be classified explicitly" >&2
  exit 1
fi

if ! grep -Fq 'ArgoCD sync command failed; kubectl fallback was not attempted because the sync may have partially applied desired state' "$sync_script"; then
  echo "failed ArgoCD sync must not fall through to a possibly conflicting kubectl mutation" >&2
  exit 1
fi

python3 - "$sync_script" <<'PY'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
block = re.search(
    r'if ! "\$\{ARGOCD\[@\]\}" app wait .*?\nfi\n',
    text,
    re.DOTALL,
)
if block is None:
    raise SystemExit("post-sync app wait guard not found")
if "sync_with_kubectl_overlay_fallback" in block.group(0):
    raise SystemExit("post-sync health timeout must never enter kubectl fallback")
PY

if ! grep -Fq 'EXPECTED_MODEL_ID="${EXPECTED_MODEL_ID:-}"' "$verify_script"; then
  echo "OpenFGA verifier must not hard-code a stale default model id" >&2
  exit 1
fi

if ! grep -Fq 'EXPECTED_STORE_ID="${EXPECTED_STORE_ID:-}"' "$verify_script"; then
  echo "OpenFGA verifier must not hard-code a stale default store id" >&2
  exit 1
fi

if ! grep -Fq 'Expected MODEL_ID not provided; using live Secret value for pod-consistency verification' "$verify_script"; then
  echo "OpenFGA verifier must support live Secret-to-pod consistency mode" >&2
  exit 1
fi

for file in "$sync_script" "$verify_script" "$sync_workflow" "$verify_workflow"; do
  if grep -Fq '01KS8QE8T1EJ2DF5CRS4VV9YX1' "$file"; then
    echo "stale OpenFGA model id must not remain in active sync/verifier code: $file" >&2
    exit 1
  fi
done

if ! grep -Fq 'default: ""' "$sync_workflow"; then
  echo "sync workflow must leave expected OpenFGA ids empty by default" >&2
  exit 1
fi

if ! grep -Fq 'default: ""' "$verify_workflow"; then
  echo "runtime verify workflow must leave expected OpenFGA ids empty by default" >&2
  exit 1
fi

echo "platform-test GitOps sync static guard passed"
