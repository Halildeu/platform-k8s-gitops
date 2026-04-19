#!/usr/bin/env bash
# Argo Rollouts — advanced deployment strategies controller install
# DRAFT: PLAN D30 prod cutover için edge servis YASAK (atomic switch only).
# İç servisler için opsiyonel (async job, background API).
# Usage: bash bootstrap/install-argo-rollouts.sh <test|prod>
set -euo pipefail

CLUSTER="${1:-}"

if [[ "${CLUSTER}" != "test" && "${CLUSTER}" != "prod" ]]; then
  echo "Usage: $0 <test|prod>"
  exit 1
fi

CTX="k3d-${CLUSTER}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VALUES="${REPO_DIR}/helm-values/argo-rollouts/values.yaml"

echo "=== Argo Rollouts Install → ${CTX} ==="

echo "1) Helm repo argo..."
helm repo add argo https://argoproj.github.io/argo-helm 2>/dev/null || true
helm repo update argo

echo "2) Namespace argo-rollouts..."
kubectl --context "${CTX}" create namespace argo-rollouts --dry-run=client -o yaml \
  | kubectl --context "${CTX}" apply -f -

echo "3) Helm install/upgrade argo-rollouts..."
helm --kube-context "${CTX}" upgrade --install argo-rollouts argo/argo-rollouts \
  --namespace argo-rollouts \
  --values "${VALUES}" \
  --wait --timeout 3m

echo "4) Doğrula controller Ready..."
kubectl --context "${CTX}" -n argo-rollouts wait --for=condition=Available \
  deployment/argo-rollouts --timeout=120s

echo "5) kubectl plugin 'argo-rollouts' install kontrolü (opsiyonel)..."
if ! command -v kubectl-argo-rollouts &>/dev/null; then
  echo "kubectl-argo-rollouts plugin kurulu değil. Kurulum:"
  echo "  curl -LO https://github.com/argoproj/argo-rollouts/releases/latest/download/kubectl-argo-rollouts-linux-amd64"
  echo "  chmod +x kubectl-argo-rollouts-linux-amd64"
  echo "  sudo mv kubectl-argo-rollouts-linux-amd64 /usr/local/bin/kubectl-argo-rollouts"
fi

cat <<EOF

=== Argo Rollouts Install PASS — ${CTX} ===

NEXT STEPS:

1. Canary sample apply (ONLY TEST CLUSTER — edge servis YASAK):
   kubectl --context ${CTX} apply -f kustomize/base/rollouts-samples/canary-sample.yaml

2. Rollout watch:
   kubectl --context ${CTX} argo rollouts get rollout permission-service-canary-sample -n platform-test --watch

3. Rollout promote (manuel ilerletme):
   kubectl --context ${CTX} argo rollouts promote permission-service-canary-sample -n platform-test

4. Abort + rollback:
   kubectl --context ${CTX} argo rollouts abort permission-service-canary-sample -n platform-test

UYARI (PLAN D30): Edge servis (api-gateway + auth-service + ai.acik.com
path'indeki servisler) için bu pattern YASAK — atomic cutover + 72h warm
rollback (docs/prod-cutover-smoke-runbook.md + docs/S4-rollback-runbook.md).

Kullanım scope: iç servis / async job / background API (edge değil).

EOF
