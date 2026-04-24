#!/usr/bin/env bash
# Faz 17.3 — Mac lokal dev cluster up + apply + optional Tilt trigger
# Idempotent: cluster varsa skip, overlay apply re-run drift-free.
#
# Kullanım:
#   ./scripts/dev-up.sh                         # default profile = authn-min
#   ./scripts/dev-up.sh --profile zanzibar-min  # 6 workload Zanzibar chain
#   ./scripts/dev-up.sh --profile full          # 10 workload testai desen
#   ./scripts/dev-up.sh --no-apply              # sadece cluster + Tilt, apply YAPMA
#   ./scripts/dev-up.sh --verbose               # detaylı log
#
# Bağımlılıklar: docker, k3d, kubectl, kustomize
# Opsiyonel: tilt (Faz 17.2 ssot Tiltfile), mkcert+caddy (Faz 17.X TLS)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PROFILE="authn-min"
NO_APPLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --no-apply) NO_APPLY=true; shift ;;
    --verbose) set -x; shift ;;
    -h|--help)
      grep -E '^#' "$0" | sed -E 's/^# ?//' | head -20
      exit 0
      ;;
    *) echo "bilinmeyen flag: $1"; exit 2 ;;
  esac
done

log()  { printf '\033[0;36m[dev-up]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[0;33m[dev-up]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[0;31m[dev-up]\033[0m %s\n' "$*" >&2; exit 1; }

case "${PROFILE}" in
  authn-min|zanzibar-min|full) ;;
  *) err "profile: authn-min | zanzibar-min | full bekleniyor, verilen: ${PROFILE}" ;;
esac

OVERLAY="kustomize/overlays/local-${PROFILE}"
[[ -d "${REPO_ROOT}/${OVERLAY}" ]] || err "overlay bulunamadı: ${OVERLAY}"

# ----- 1. Cluster hazırlığı -----
command -v docker >/dev/null || err "docker kurulu değil"
command -v k3d >/dev/null || err "k3d kurulu değil — https://k3d.io"
command -v kubectl >/dev/null || err "kubectl kurulu değil"

if k3d cluster list --no-headers 2>/dev/null | awk '{print $1}' | grep -qx "dev"; then
  log "cluster 'dev' zaten var — atlanıyor"
else
  log "k3d-dev cluster oluşturuluyor (bootstrap/k3d-dev.yaml)"
  k3d cluster create --config "${REPO_ROOT}/bootstrap/k3d-dev.yaml"
fi

kubectl --context k3d-dev get nodes -o wide >/dev/null || err "k3d-dev API erişilemiyor"
log "k3d-dev Ready"

# ----- 2. Namespace -----
kubectl --context k3d-dev get ns platform-dev >/dev/null 2>&1 || {
  log "namespace platform-dev oluşturuluyor"
  kubectl --context k3d-dev create ns platform-dev
}

# ----- 3. Apply (opsiyonel skip) -----
if [[ "${NO_APPLY}" == "false" ]]; then
  log "overlay apply: ${OVERLAY} (profile=${PROFILE})"
  kubectl --context k3d-dev apply -k "${REPO_ROOT}/${OVERLAY}" || err "kustomize apply fail"

  log "deployment readiness bekleniyor (max 180s)..."
  kubectl --context k3d-dev wait --for=condition=Available deployment --all -n platform-dev --timeout=180s || warn "bazı deployment ready değil (smoke'a devam)"
fi

# ----- 4. Tilt (opsiyonel, platform-ssot Tiltfile) -----
if command -v tilt >/dev/null 2>&1; then
  TILTFILE="${REPO_ROOT}/../platform-ssot/Tiltfile"
  if [[ -f "${TILTFILE}" ]]; then
    log "Tilt UI başlatmak için: cd ../platform-ssot && TILT_PROFILE=${PROFILE} tilt up"
  else
    warn "platform-ssot Tiltfile bulunamadı (${TILTFILE}) — manuel tilt trigger"
  fi
else
  warn "tilt kurulu değil — inner-loop UI yok (manuel rebuild için kustomize apply)"
fi

# ----- 5. Özet -----
log "=== dev-up tamamlandı ==="
log "Profile: ${PROFILE}"
log "Cluster: k3d-dev  |  Namespace: platform-dev  |  Domain: *.localtest.me"
log "Ingress: http://app.localtest.me:32080 (veya :32443 TLS 17.X sonrası)"
log "Smoke: ./scripts/dev-smoke.sh --profile ${PROFILE}"
log "Seed:  ./scripts/dev-seed.sh --profile ${PROFILE}"
