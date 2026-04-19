#!/usr/bin/env bash
# cert-manager — automated TLS cert (Let's Encrypt HTTP-01)
# Usage: bash bootstrap/install-cert-manager.sh <test|prod>
# PLAN D8 Aşama 2 — Faz 12 devreye alma (şu an Sectigo manuel aktif)
set -euo pipefail

CLUSTER="${1:-}"

if [[ "${CLUSTER}" != "test" && "${CLUSTER}" != "prod" ]]; then
  echo "Usage: $0 <test|prod>"
  exit 1
fi

CTX="k3d-${CLUSTER}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VALUES="${REPO_DIR}/helm-values/cert-manager/values.yaml"

if ! kubectl config get-contexts "${CTX}" >/dev/null 2>&1; then
  echo "ERROR: kubectl context '${CTX}' yok"
  exit 1
fi

echo "=== cert-manager Helm Install → ${CTX} ==="

echo "1) Helm repo jetstack..."
helm repo add jetstack https://charts.jetstack.io 2>/dev/null || true
helm repo update jetstack

echo "2) Namespace cert-manager..."
kubectl --context "${CTX}" create namespace cert-manager --dry-run=client -o yaml \
  | kubectl --context "${CTX}" apply -f -

echo "3) Helm install/upgrade cert-manager..."
helm --kube-context "${CTX}" upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --values "${VALUES}" \
  --wait --timeout 5m

echo "4) Doğrula cert-manager Deployment Ready..."
kubectl --context "${CTX}" -n cert-manager wait --for=condition=Available \
  deployment/cert-manager --timeout=180s
kubectl --context "${CTX}" -n cert-manager wait --for=condition=Available \
  deployment/cert-manager-webhook --timeout=180s
kubectl --context "${CTX}" -n cert-manager wait --for=condition=Available \
  deployment/cert-manager-cainjector --timeout=180s

echo "5) ClusterIssuer apply (staging + prod)..."
kubectl --context "${CTX}" apply -k "${REPO_DIR}/kustomize/base/cert-manager"

echo "6) Doğrula ClusterIssuer..."
kubectl --context "${CTX}" get clusterissuer
echo "(Ready=True beklenir 30s içinde; ACME register + account key generate)"

cat <<EOF

=== cert-manager Install PASS — ${CTX} ===

NEXT STEPS (test cert + HTTP-01 challenge):

1. Test Certificate CR (staging):
   cat <<YAML | kubectl --context ${CTX} apply -f -
   apiVersion: cert-manager.io/v1
   kind: Certificate
   metadata:
     name: testai-acik-com-staging
     namespace: platform-${CLUSTER}
   spec:
     secretName: testai-acik-com-staging-tls
     dnsNames:
       - testai.acik.com
     issuerRef:
       name: letsencrypt-staging
       kind: ClusterIssuer
   YAML

2. Watch cert issuance (5-10 dk):
   watch kubectl --context ${CTX} -n platform-${CLUSTER} get certificate

3. Cert Ready=True olursa (challenge PASS):
   kubectl --context ${CTX} -n platform-${CLUSTER} get secret testai-acik-com-staging-tls
   # tls.crt + tls.key base64

4. Prod'a geçiş (staging test PASS sonrası):
   - Aynı Certificate CR ama issuerRef.name: letsencrypt-prod
   - Cert yenilemesi otomatik (cert-manager 30 gün önce renew)

5. Ingress ile entegrasyon (cert-manager.io/cluster-issuer annotation):
   # Ingress spec.tls.secretName otomatik set edilir
   metadata:
     annotations:
       cert-manager.io/cluster-issuer: letsencrypt-prod

YASAK: Prod'a direkt prod issuer ile istek — Let's Encrypt rate limit (50/week).
Her zaman önce staging test.

EOF
