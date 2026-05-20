#!/usr/bin/env bash
# Register k3d-test cluster in prod ArgoCD (ADR-0002 §3.7 prod-hub topology)
# Test cluster credential Git'te tutulmaz — Vault/out-of-band bootstrap flow.
#
# Prereq:
#   - bootstrap/install-argocd.sh prod → ArgoCD hub prod'da çalışıyor
#   - k3d-test + k3d-prod her ikisi de çalışıyor
#   - argocd CLI kurulu
#
# Usage: bash bootstrap/register-test-cluster-argocd.sh
# Flow:
#   1. ArgoCD server'a login (prod ingress veya port-forward)
#   2. k3d-test cluster'da argocd-manager ServiceAccount yarat (dedicated)
#   3. SA token al → argocd cluster add ile kaydet
#   4. Cluster secret Vault path'e yedekle (prod Vault kv/argocd/test-cluster-bootstrap)
#   5. Doğrula: argocd cluster list → k3d-test görünür

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() { printf '\033[0;36m[argocd-register-test]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[0;31m[argocd-register-test]\033[0m %s\n' "$*" >&2; exit 1; }

command -v argocd >/dev/null || err "argocd CLI yok (brew install argocd)"
command -v kubectl >/dev/null || err "kubectl yok"

PROD_CTX="${PROD_CTX:-k3d-prod}"
TEST_CTX="${TEST_CTX:-k3d-test}"
# 2026-05-20 — ADR-0023 Guardrail PR-2 align: argocd/applications/platform-test.yaml
# spec.destination.name: test-cluster bekliyor. Default önceden k3d-test'ti
# (Codex 019e42c4 REVISE absorb — name mismatch riski). Operator override
# yaparsa string test-cluster ile uyumlu olmalı.
CLUSTER_NAME="${CLUSTER_NAME:-test-cluster}"
ARGOCD_SERVER="${ARGOCD_SERVER:-localhost:8080}"

kubectl --context "${PROD_CTX}" cluster-info >/dev/null 2>&1 || err "${PROD_CTX} yok"
kubectl --context "${TEST_CTX}" cluster-info >/dev/null 2>&1 || err "${TEST_CTX} yok"

# 1. ArgoCD server erişim
log "ArgoCD server bağlantı test (${ARGOCD_SERVER})"
if ! argocd --server "${ARGOCD_SERVER}" --insecure version --client >/dev/null 2>&1; then
  err "argocd CLI bağlantı fail. Port-forward kur: kubectl --context ${PROD_CTX} port-forward -n argocd svc/argocd-server 8080:80"
fi

# 2. Admin login (initial-admin-secret veya rotate edilmiş password)
if [[ -z "${ARGOCD_PASSWORD:-}" ]]; then
  log "Admin password okunuyor (initial-admin-secret)..."
  ARGOCD_PASSWORD=$(kubectl --context "${PROD_CTX}" -n argocd \
    get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' 2>/dev/null | base64 -d || echo "")
  if [[ -z "${ARGOCD_PASSWORD}" ]]; then
    err "Admin password alınamadı. ARGOCD_PASSWORD env ile elle ver veya rotate edilmiş secret'ı kontrol et."
  fi
fi

log "argocd login"
argocd --server "${ARGOCD_SERVER}" --insecure login \
  --username admin --password "${ARGOCD_PASSWORD}"

# 3. Test cluster'ı ArgoCD'ye ekle
log "argocd cluster add ${TEST_CTX} → ${CLUSTER_NAME}"
argocd --server "${ARGOCD_SERVER}" --insecure cluster add "${TEST_CTX}" \
  --name "${CLUSTER_NAME}" \
  --kubeconfig "${HOME}/.kube/config" \
  --yes

# 4. Doğrula
log "argocd cluster list"
argocd --server "${ARGOCD_SERVER}" --insecure cluster list

# 5. Cluster secret'ını Vault'a yedekle (out-of-band backup, ADR-0002 §3.7)
log ""
log "=== ÖNEMLİ: Cluster credential backup (ADR-0002 §3.7) ==="
log "Git'te saklama YOK. Vault prod'a yedekle:"
log ""
log "  # ArgoCD'nin yarattığı cluster secret'ı oku:"
log "  kubectl --context ${PROD_CTX} -n argocd get secret \\"
log "    -l argocd.argoproj.io/secret-type=cluster \\"
log "    -o jsonpath='{.items[?(@.data.name==\"$(printf "%s" "${CLUSTER_NAME}" | base64)\")].data}'"
log ""
log "  # Vault'a yaz (prod Vault):"
log "  vault kv put kv/argocd/test-cluster-bootstrap \\"
log "    server=\$(kubectl ... .data.server) \\"
log "    config=\$(kubectl ... .data.config) \\"
log "    ca-cert=\$(kubectl ... .data.\"tls.crt\")"
log ""
log "Restore senaryosu (prod ArgoCD reinstall sonrası):"
log "  vault kv get -format=json kv/argocd/test-cluster-bootstrap | jq ... | kubectl apply"

log ""
log "Register DONE. root.yaml Application'ları sync edebilir."
