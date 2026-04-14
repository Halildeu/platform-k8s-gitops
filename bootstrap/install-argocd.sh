#!/usr/bin/env bash
# ArgoCD kurulum (sadece prod cluster — D16: tek ArgoCD, multi-cluster yönetir)
# Helm chart: argoproj/argo-cd (upstream)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() { printf '\033[0;36m[argocd]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[0;31m[argocd]\033[0m %s\n' "$*" >&2; exit 1; }

command -v helm >/dev/null || err "helm yok (brew install helm)"

HELM_REPO="argo"
CHART="argo/argo-cd"
CHART_VERSION="${CHART_VERSION:-7.7.5}"   # ArgoCD 2.13 (stable)

ctx="k3d-prod"
kubectl --context "${ctx}" cluster-info >/dev/null 2>&1 || err "k3d-prod cluster yok"

if ! helm repo list 2>/dev/null | grep -q "^${HELM_REPO}"; then
  helm repo add argo https://argoproj.github.io/argo-helm
fi
helm repo update argo >/dev/null

log "namespace argocd"
kubectl --context "${ctx}" create namespace argocd --dry-run=client -o yaml \
  | kubectl --context "${ctx}" apply -f -

log "helm upgrade --install argocd (chart ${CHART_VERSION})"
helm --kube-context "${ctx}" upgrade --install argocd "${CHART}" \
  --namespace argocd \
  --version "${CHART_VERSION}" \
  -f "${REPO_ROOT}/helm-values/argocd/values.yaml" \
  --wait --timeout 10m

log "kurulum tamam"
kubectl --context "${ctx}" -n argocd get pods,svc

log ""
log "ArgoCD admin şifresi (stdout'a dump edilmez, D26):"
log "  kubectl --context ${ctx} -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
log "İlk girişten sonra 'argocd account update-password' ile değiştirip:"
log "  kubectl --context ${ctx} -n argocd delete secret argocd-initial-admin-secret"
log ""
log "Erişim:"
log "  Port-forward: kubectl --context ${ctx} port-forward -n argocd svc/argocd-server 8080:80"
log "  Ingress:      http://ai.acik.com/argocd/  (/etc/hosts: 127.0.0.1 ai.acik.com)"
