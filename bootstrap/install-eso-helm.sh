#!/usr/bin/env bash
# ESO Helm install — test veya prod cluster
# Usage: bash bootstrap/install-eso-helm.sh <test|prod>
# Prereq:
#   - kubectl context aktif (k3d-test veya k3d-prod)
#   - helm CLI kurulu
#   - helm-values/external-secrets/values.yaml mevcut
#   - Vault path'leri seed edilmiş (docs/S2-B1-vault-property-matrix.md preflight)
#
# Codex iter-3 PARTIAL absorb: install-on-staging-sw-2.sh F6 artık bu script'i
# çağırıyor; base/eso YASAK, overlay apply zorunlu.

set -euo pipefail

CLUSTER="${1:-test}"

if [[ "${CLUSTER}" != "test" && "${CLUSTER}" != "prod" ]]; then
  echo "ERROR: İlk argüman 'test' veya 'prod' olmalı (verildi: '${CLUSTER}')"
  echo "Usage: $0 <test|prod>"
  exit 1
fi

CTX="k3d-${CLUSTER}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VALUES="${REPO_DIR}/helm-values/external-secrets/values.yaml"

if ! kubectl config get-contexts "${CTX}" >/dev/null 2>&1; then
  echo "ERROR: kubectl context '${CTX}' yok. k3d-${CLUSTER} cluster up mı?"
  exit 1
fi

if [[ ! -f "${VALUES}" ]]; then
  echo "ERROR: Helm values dosyası yok: ${VALUES}"
  exit 1
fi

echo "=== ESO Helm Install → ${CTX} ==="

echo "1) Helm repo external-secrets..."
helm repo add external-secrets https://charts.external-secrets.io 2>/dev/null || true
helm repo update external-secrets

echo "2) Namespace external-secrets (idempotent)..."
kubectl --context "${CTX}" create namespace external-secrets --dry-run=client -o yaml \
  | kubectl --context "${CTX}" apply -f -

echo "3) Helm install/upgrade external-secrets..."
helm --kube-context "${CTX}" upgrade --install external-secrets \
  external-secrets/external-secrets \
  --namespace external-secrets \
  --values "${VALUES}" \
  --wait --timeout 5m

echo "4) Doğrula ESO Deployments Ready..."
kubectl --context "${CTX}" -n external-secrets get deployment
kubectl --context "${CTX}" -n external-secrets wait --for=condition=Available \
  deployment/external-secrets --timeout=120s
kubectl --context "${CTX}" -n external-secrets wait --for=condition=Available \
  deployment/external-secrets-webhook --timeout=120s
kubectl --context "${CTX}" -n external-secrets wait --for=condition=Available \
  deployment/external-secrets-cert-controller --timeout=120s

cat <<EOF

=== ESO Install PASS — ${CTX} ===

NEXT STEPS (manuel ops):

5) Vault AppRole secret-id (ilk bootstrap, sonrası auto-rotate):
   kubectl --context ${CTX} -n external-secrets create secret generic vault-approle-secret \\
     --from-literal=secret-id=<VAULT_ESO_RUNTIME_SECRET_ID>

6) Overlay ESO apply (ClusterSecretStore + ghcr-pull ExternalSecret):
   kubectl --context ${CTX} apply -k kustomize/overlays/${CLUSTER}/eso

7) Doğrulama:
   kubectl --context ${CTX} get clustersecretstore vault-platform-gitops
   # Status=Ready, Message=store validated
   kubectl --context ${CTX} -n external-secrets get externalsecret ghcr-pull
   # Synced=True
   kubectl --context ${CTX} -n platform-${CLUSTER} get secret ghcr-pull
   # type=kubernetes.io/dockerconfigjson

8) Per-service ExternalSecret switch (S2-B1 Dilim 2):
   Her servis kustomization.yaml içinde secret-stub.yaml kaldır, externalsecret.yaml ekle.
   Apply: kubectl --context ${CTX} apply -k kustomize/overlays/${CLUSTER}

EOF
