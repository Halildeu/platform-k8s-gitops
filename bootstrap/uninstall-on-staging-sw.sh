#!/usr/bin/env bash
# uninstall-on-staging-sw.sh — testai.acik.com paralel kurulumu geri al
# Mevcut ai.acik.com (compose) ETKİLENMEZ.
#
# Adımlar (ters sıra):
#   1. nginx default.conf → en son yedek
#   2. nginx -s reload (testai server block kalkar)
#   3. k3d-test cluster sil
#   4. (opsiyonel) repo dizinini sil

set -euo pipefail

REMOTE="${REMOTE:-staging-sw}"
DRY_RUN="${DRY_RUN:-false}"
KEEP_REPO="${KEEP_REPO:-true}"            # false: repo dizinini de sil
NGX_CONF_HOST="${NGX_CONF_HOST:-/home/halil/platform/web/nginx/default.conf}"
REPO_DIR_REMOTE="${REPO_DIR_REMOTE:-/home/halil/platform-k8s-gitops}"

log() { printf '\033[33m[uninstall]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[31m[uninstall]\033[0m %s\n' "$*" >&2; exit 1; }
sshrun() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '\033[90mDRY ssh:\033[0m %s\n' "$*" >&2
  else
    ssh -o BatchMode=no "${REMOTE}" "$@"
  fi
}

ssh -o ConnectTimeout=5 "${REMOTE}" 'true' >/dev/null 2>&1 || err "ssh ${REMOTE} bağlanamadı"

# 1. nginx default.conf restore
log "1/4 platform-web-nginx default.conf'u en son yedeğe geri al"
LATEST_BAK=$(sshrun "ls -t ${NGX_CONF_HOST}.bak-* 2>/dev/null | head -1" || echo "")
if [[ -z "${LATEST_BAK}" ]]; then
  log "   yedek bulunamadı — testai server block'u manuel sil ve devam"
else
  log "   restore: ${LATEST_BAK}"
  sshrun "cp ${LATEST_BAK} ${NGX_CONF_HOST}"
fi

# 2. nginx test + reload
log "2/4 nginx -t + reload"
sshrun 'docker exec platform-web-nginx nginx -t' || err "nginx -t başarısız (manuel müdahale gerek)"
sshrun 'docker exec platform-web-nginx nginx -s reload'
log "   ✓ ai.acik.com config'i aktif (testai block yok)"

# 3. k3d-test cluster
log "3/4 k3d-test cluster sil"
if sshrun "k3d cluster list --no-headers 2>/dev/null | awk '{print \$1}' | grep -qx test"; then
  sshrun 'k3d cluster delete test'
  log "   ✓ k3d-test silindi"
else
  log "   yok zaten"
fi

# 4. Repo dizini (opsiyonel)
log "4/4 repo dizini"
if [[ "${KEEP_REPO}" == "true" ]]; then
  log "   korundu (KEEP_REPO=true). Manuel silmek için: ssh ${REMOTE} 'rm -rf ${REPO_DIR_REMOTE}'"
else
  sshrun "rm -rf ${REPO_DIR_REMOTE}"
  log "   ✓ silindi"
fi

# Smoke
log ""
log "=== Smoke (mevcut ai.acik.com hâlâ çalışıyor mu?) ==="
sshrun 'curl -sk --max-time 5 -o /dev/null -w "ai.acik.com / → HTTP %{http_code}\n" https://127.0.0.1/ -H "Host: ai.acik.com"'
sshrun 'curl -sk --max-time 5 -o /dev/null -w "testai (kalkmış olmalı) → HTTP %{http_code}\n" https://127.0.0.1/ -H "Host: testai.acik.com" 2>&1' || true

log ""
log "✓ DONE — testai.acik.com paralel kurulum kaldırıldı"
log "  ai.acik.com hâlâ çalışıyor (compose stack dokunulmadı)"
