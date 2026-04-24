#!/usr/bin/env bash
# Faz 17.3 — Mac lokal dev cluster tear-down
# Reversible: sadece k3d-dev durdurur/siler, staging-sw hedeflerine dokunmaz.
#
# Kullanım:
#   ./scripts/dev-down.sh              # stop (reversible, state korunur)
#   ./scripts/dev-down.sh --delete     # fully remove (cluster + registry + network)

set -euo pipefail

ACTION="stop"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --delete) ACTION="delete"; shift ;;
    -h|--help)
      grep -E '^#' "$0" | sed -E 's/^# ?//' | head -10
      exit 0
      ;;
    *) echo "bilinmeyen flag: $1"; exit 2 ;;
  esac
done

log() { printf '\033[0;36m[dev-down]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[0;33m[dev-down]\033[0m %s\n' "$*" >&2; }

if ! k3d cluster list --no-headers 2>/dev/null | awk '{print $1}' | grep -qx "dev"; then
  warn "cluster 'dev' zaten yok"
  exit 0
fi

case "${ACTION}" in
  stop)
    log "cluster 'dev' stop (reversible) — start için 'k3d cluster start dev'"
    k3d cluster stop dev
    ;;
  delete)
    log "cluster 'dev' DELETE (tam silinir + registry + network)"
    k3d cluster delete dev
    log "Registry ve network otomatik temizlenir. Re-create için ./scripts/dev-up.sh"
    ;;
esac

log "tamam"
