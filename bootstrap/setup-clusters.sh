#!/usr/bin/env bash
# Prod + test k3d cluster'larını ayağa kaldırır.
# Idempotent: cluster zaten varsa dokunmaz.
#
# Gereksinimler:
#   - docker
#   - k3d (https://k3d.io)
#   - kubectl
#
# Kullanım:
#   ./bootstrap/setup-clusters.sh            # ikisini de kur
#   ./bootstrap/setup-clusters.sh prod       # sadece prod
#   ./bootstrap/setup-clusters.sh test       # sadece test

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log()  { printf '\033[0;36m[bootstrap]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[0;33m[bootstrap]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[0;31m[bootstrap]\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker  >/dev/null || err "docker kurulu değil"
command -v k3d     >/dev/null || err "k3d kurulu değil — https://k3d.io"
command -v kubectl >/dev/null || err "kubectl kurulu değil"

TARGETS="${1:-both}"

create_cluster() {
  local name="$1"
  local config="${SCRIPT_DIR}/k3d-${name}.yaml"
  [[ -f "${config}" ]] || err "config bulunamadı: ${config}"

  if k3d cluster list --no-headers 2>/dev/null | awk '{print $1}' | grep -qx "${name}"; then
    log "cluster '${name}' zaten var — atlanıyor"
    return 0
  fi

  log "cluster '${name}' oluşturuluyor (${config})"
  k3d cluster create --config "${config}"

  log "cluster '${name}' hazır (context: k3d-${name})"
  kubectl --context "k3d-${name}" get nodes -o wide
}

case "${TARGETS}" in
  prod) create_cluster prod ;;
  test) create_cluster test ;;
  both|"") create_cluster prod; create_cluster test ;;
  *) err "bilinmeyen hedef: ${TARGETS} (beklenen: prod|test|both)" ;;
esac

log "kubeconfig context'leri: $(kubectl config get-contexts -o name | grep '^k3d-' | tr '\n' ' ')"
log "sıradaki adım: ./bootstrap/install-calico.sh  (her iki cluster için CNI)"
