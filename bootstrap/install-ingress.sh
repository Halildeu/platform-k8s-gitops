#!/usr/bin/env bash
# ingress-nginx kurulum (her iki k3d cluster'a)
# Helm chart: kubernetes/ingress-nginx (upstream)
#
# Kullanım:
#   ./bootstrap/install-ingress.sh           # prod + test
#   ./bootstrap/install-ingress.sh prod
#   ./bootstrap/install-ingress.sh test

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() { printf '\033[0;36m[ingress]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[0;31m[ingress]\033[0m %s\n' "$*" >&2; exit 1; }

command -v helm >/dev/null || err "helm kurulu değil (brew install helm)"

HELM_REPO="ingress-nginx"
HELM_CHART="ingress-nginx/ingress-nginx"
CHART_VERSION="${CHART_VERSION:-4.11.3}"     # upstream kubernetes/ingress-nginx

add_repo() {
  if ! helm repo list 2>/dev/null | grep -q "^${HELM_REPO}"; then
    log "helm repo ekleniyor: ${HELM_REPO}"
    helm repo add "${HELM_REPO}" https://kubernetes.github.io/ingress-nginx
  fi
  helm repo update "${HELM_REPO}" >/dev/null 2>&1 || true
}

install_ingress() {
  local cluster="$1"
  local ctx="k3d-${cluster}"
  local values="${REPO_ROOT}/helm-values/ingress-nginx/values-${cluster}.yaml"

  [[ -f "${values}" ]] || err "values dosyası yok: ${values}"
  kubectl --context "${ctx}" cluster-info >/dev/null 2>&1 \
    || err "context '${ctx}' yok — önce setup-clusters.sh"

  log "[${cluster}] namespace ingress-nginx"
  kubectl --context "${ctx}" create namespace ingress-nginx --dry-run=client -o yaml \
    | kubectl --context "${ctx}" apply -f -

  log "[${cluster}] helm upgrade --install ingress-nginx (chart ${CHART_VERSION})"
  helm --kube-context "${ctx}" upgrade --install ingress-nginx "${HELM_CHART}" \
    --namespace ingress-nginx \
    --version "${CHART_VERSION}" \
    -f "${values}" \
    --wait --timeout 5m

  log "[${cluster}] kurulum tamam"
  kubectl --context "${ctx}" -n ingress-nginx get pods,svc
}

add_repo

TARGETS="${1:-both}"
case "${TARGETS}" in
  prod) install_ingress prod ;;
  test) install_ingress test ;;
  both|"") install_ingress prod; install_ingress test ;;
  *) err "bilinmeyen hedef: ${TARGETS}" ;;
esac

log "sıradaki adım: host-level nginx SNI proxy'yi ayağa kaldır"
log "  lokal: docs/main-repo-tasks.md takip et, image build sonrası deploy"
log "  canlı: host-compose/proxy/ ile staging-sw'de (disk gelince)"
