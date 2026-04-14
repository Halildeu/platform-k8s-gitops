#!/usr/bin/env bash
# Cluster'ları kaldırır. Kubeconfig context'i de temizler.
# DİKKAT: cluster içindeki tüm veri silinir. Host-level Compose servisleri etkilenmez.

set -euo pipefail

log() { printf '\033[0;33m[teardown]\033[0m %s\n' "$*" >&2; }

TARGETS="${1:-both}"

delete_cluster() {
  local name="$1"
  if k3d cluster list --no-headers 2>/dev/null | awk '{print $1}' | grep -qx "${name}"; then
    log "'${name}' cluster siliniyor"
    k3d cluster delete "${name}"
  else
    log "'${name}' cluster zaten yok"
  fi
}

case "${TARGETS}" in
  prod) delete_cluster prod ;;
  test) delete_cluster test ;;
  both|"") delete_cluster test; delete_cluster prod ;;
  *) log "bilinmeyen hedef: ${TARGETS}"; exit 1 ;;
esac

log "bitti."
