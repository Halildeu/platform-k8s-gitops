#!/usr/bin/env bash
# Kyverno admission controller Helm install
# Prereq: kubectl context aktif + helm CLI
# Policy CR'lar: kustomize/base/policies/ (ClusterPolicy D30 HARD RULE enforce)
set -euo pipefail

CLUSTER="${1:-}"

if [[ "${CLUSTER}" != "test" && "${CLUSTER}" != "prod" ]]; then
  echo "Usage: $0 <test|prod>"
  exit 1
fi

CTX="k3d-${CLUSTER}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VALUES="${REPO_DIR}/helm-values/kyverno/values.yaml"

if ! kubectl config get-contexts "${CTX}" >/dev/null 2>&1; then
  echo "ERROR: kubectl context '${CTX}' yok"
  exit 1
fi

echo "=== Kyverno Helm Install → ${CTX} ==="

echo "1) Helm repo add kyverno..."
helm repo add kyverno https://kyverno.github.io/kyverno/ 2>/dev/null || true
helm repo update kyverno

echo "2) Namespace kyverno..."
kubectl --context "${CTX}" create namespace kyverno --dry-run=client -o yaml \
  | kubectl --context "${CTX}" apply -f -

echo "3) Helm install/upgrade kyverno..."
helm --kube-context "${CTX}" upgrade --install kyverno kyverno/kyverno \
  --namespace kyverno \
  --values "${VALUES}" \
  --wait --timeout 5m

echo "4) Doğrula admission controller Ready..."
kubectl --context "${CTX}" -n kyverno wait --for=condition=Available \
  deployment/kyverno-admission-controller --timeout=180s

echo "5) Policy CR'lar apply (audit mode başlangıç)..."
kubectl --context "${CTX}" apply -k "${REPO_DIR}/kustomize/base/policies"

echo "6) Doğrula ClusterPolicy + PolicyReport..."
kubectl --context "${CTX}" get clusterpolicy
echo
echo "PolicyReport (violations audit mode):"
kubectl --context "${CTX}" get policyreport -A 2>/dev/null || echo "(henüz yok, controller reconcile bekler)"

cat <<EOF

=== Kyverno Install PASS — ${CTX} ===

NEXT STEPS (audit → enforce geçişi):

1. Policy violations izle (5-10 dk):
   watch kubectl --context ${CTX} get policyreport -A

2. Violations 0 ise (tüm mevcut pod'lar compliant), enforce'a geç:
   kubectl --context ${CTX} apply -k kustomize/base/policies/enforce-overlay/
   # veya patch: kubectl patch clusterpolicy <name> --type=merge -p \\
   #   '{"spec":{"validationFailureAction":"enforce"}}'

3. Yeni violations → admission webhook reject (deploy fail)
   → Policy compliant değilse Pod create yapılmaz

4. Monitoring: kustomize/base/monitoring/ PrometheusRule'a Kyverno alerts ekle
   (ileride): kyverno_policy_results_total{result="fail"} > 0

EOF
