#!/usr/bin/env bash
# reconnect-compose-to-test-net.sh
#
# Compose postgres/keycloak/vault container'ları yeniden oluşturulduğunda
# (docker compose down/up, docker restart, vb.) platform-test-net Docker
# network'üne eklendiği durum KAYBOLUR. k3d-test cluster'daki pod'lar
# Endpoints IP üzerinden bu container'lara ulaşamaz olur.
#
# Bu script:
#   1. Compose container'ları çalışıyor mu kontrol eder
#   2. platform-test-net'e (k3d-test Docker network) bağlı değilse bağlar
#   3. Yeni IP'leri okur
#   4. kustomize test overlay'indeki Endpoints patch'lerini günceller
#      (ya da dinamik kubectl patch uygular)
#   5. k3d-test pod'larını restart eder
#
# Kullanım:
#   ./bootstrap/reconnect-compose-to-test-net.sh
#   DRY_RUN=true ./bootstrap/reconnect-compose-to-test-net.sh

set -euo pipefail

REMOTE="${REMOTE:-staging-sw}"
DRY_RUN="${DRY_RUN:-false}"
NETWORK="${NETWORK:-platform-test-net}"

CONTAINERS_SERVICES=(
  "platform-postgres-db-1:postgres:5432"
  "platform-keycloak-1:keycloak:8080"
  "platform-vault-1:vault:8200"
  "minio-minio-test-1:minio:9000"
)
# Faz 3 ESO: vault platform-test-net'te görünür olmalı (ClusterSecretStore → 8200)
# Faz 24 #1250 (ADR-0042): minio host-compose (audit-archive 7yr WORM) container
# NATIVE port 9000 üzerinden — host-published :9100 değil; cluster bridge IP'den
# container portuna erişir (redis-streams emsali). Drift sonrası reconnect.

log()  { printf '\033[36m[reconnect]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[33m[reconnect]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[31m[reconnect]\033[0m %s\n' "$*" >&2; exit 1; }

sshrun() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '\033[90mDRY ssh:\033[0m %s\n' "$*" >&2
  else
    ssh -o BatchMode=no "${REMOTE}" "export PATH=\$HOME/.local/bin:\$PATH; $*"
  fi
}

ssh -o ConnectTimeout=5 "${REMOTE}" 'true' >/dev/null 2>&1 \
  || err "ssh ${REMOTE} ulaşılamıyor"

declare -A IPS

for entry in "${CONTAINERS_SERVICES[@]}"; do
  container="${entry%%:*}"
  rest="${entry#*:}"
  svc="${rest%%:*}"
  port="${rest##*:}"

  log "${container} kontrol ediliyor..."
  status=$(sshrun "docker inspect -f '{{.State.Status}}' ${container} 2>/dev/null || echo missing")
  if [[ "${status}" != "running" ]]; then
    warn "   ${container} çalışmıyor (${status}) — atlanıyor"
    continue
  fi

  # Zaten bağlı mı?
  attached=$(sshrun "docker inspect -f '{{range \$k,\$v := .NetworkSettings.Networks}}{{\$k}} {{end}}' ${container}" | grep -c "${NETWORK}" || true)
  if [[ "${attached}" -eq 0 ]]; then
    log "   ${NETWORK}'a bağlanıyor"
    sshrun "docker network connect ${NETWORK} ${container}"
  else
    log "   zaten bağlı"
  fi

  # Faz 24 #1250 (ADR-0042): MinIO TEK-HOMED olmalı (return-path asymmetry —
  # runbook RB-faz24-minio-audit-archive §0.1). Dual-home (minio_default +
  # platform-test-net) k3d pod→minio:9000 timeout yaratır. Compose artık
  # minio-test'i yalnız platform-test-net'e koyuyor; ama drift olursa burada
  # FAIL-FAST + explicit consent iste (auto-disconnect YASAK — shared instance
  # #55 meeting/transcript; owner onayı gerek).
  if [[ "${container}" == minio-* ]]; then
    other=$(sshrun "docker inspect -f '{{range \$k,\$v := .NetworkSettings.Networks}}{{\$k}} {{end}}' ${container}" | tr ' ' '\n' | grep -vE "^(${NETWORK})?$" | grep -c . || true)
    if [[ "${other}" -gt 0 ]]; then
      if [[ "${MINIO_SINGLE_HOME:-false}" == "true" ]]; then
        warn "   ${container} dual-homed + MINIO_SINGLE_HOME=true → minio_default ayrılıyor"
        sshrun "docker network disconnect minio_default ${container} || true"
      else
        err "   ${container} DUAL-HOMED (return-path bozuk). Single-home gerek: compose'da yalnız ${NETWORK}, ya da owner onayıyla MINIO_SINGLE_HOME=true ./$(basename "$0"). (runbook §0.1)"
      fi
    fi
  fi

  # IP'yi oku
  ip=$(sshrun "docker inspect -f '{{(index .NetworkSettings.Networks \"${NETWORK}\").IPAddress}}' ${container}")
  IPS["${svc}"]="${ip}"
  log "   ${svc} IP: ${ip}"
done

if [[ "${#IPS[@]}" -eq 0 ]]; then
  err "Hiçbir container bağlanamadı — compose stack çalışıyor mu kontrol et"
fi

log ""
log "=== k3d-test Endpoints güncelleniyor ==="
for svc in "${!IPS[@]}"; do
  ip="${IPS[$svc]}"
  # k3d-test cluster'a doğrudan kubectl patch (YAML değişikliği yok, runtime only)
  sshrun "kubectl --context k3d-test -n platform-test patch endpoints ${svc} --type=json -p='[{\"op\":\"replace\",\"path\":\"/subsets/0/addresses/0/ip\",\"value\":\"${ip}\"}]'" 2>&1 | head -3
done

log ""
log "=== Platform pod restart (yeni IP pick-up) ==="
sshrun 'kubectl --context k3d-test -n platform-test rollout restart deployment --selector=app.kubernetes.io/part-of=platform 2>&1 | head -15'

log ""
log "✓ Bitti. Sonraki smoke:"
log "  for p in /testai-healthz /actuator/health; do curl -sk -o /dev/null -w \"\$p → %{http_code}\n\" https://testai.acik.com\$p; done"
