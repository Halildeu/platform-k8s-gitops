#!/usr/bin/env bash
# Keycloak Realm Export Cron — weekly (Faz I.1.3)
# Source: ADR-0002 §0.5 + docs/day-2-governance.md
#
# Cron install (staging-sw):
#   0 3 * * 0 /home/halil/platform-k8s-gitops/bootstrap/kc-export-cron.sh  (Pazar 03:00)
#
# Output: /home/halil/platform/backup/keycloak/{prod,test}/serban-<YYYYMMDD>.json.gz
# Retention: 56 gün (8 hafta geriye izle)

set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/home/halil/platform/backup/keycloak}"
RETENTION_DAYS="${RETENTION_DAYS:-56}"
TIMESTAMP=$(date +%Y%m%d)

log() { printf '\033[0;36m[kc-export]\033[0m %s\n' "$*" >&2; }

declare -A REALMS=(
  ["prod"]="serban"
  ["test"]="platform-test"
)

for env in prod test; do
  container="platform-kc-${env}"
  realm="${REALMS[${env}]}"
  dir="${BACKUP_ROOT}/${env}"
  mkdir -p "${dir}"

  state=$(docker inspect "${container}" --format "{{.State.Status}}" 2>/dev/null || echo "missing")
  if [[ "${state}" != "running" ]]; then
    log "SKIP ${env}: ${container} state=${state}"
    continue
  fi

  output="${dir}/${realm}-${TIMESTAMP}.json.gz"
  log "EXPORT ${env}:${realm} → ${output}"

  # KC export (kc.sh export sırasında server çalışır, external mode ihtiyaç yok
  # realm export için admin creds gerek)
  admin_pw_file="${HOME}/bootstrap-drill/${env}-creds.env"
  if [[ -f "${admin_pw_file}" ]]; then
    source "${admin_pw_file}"
    ADMIN_PW="${KC_ADMIN_PW_PROD:-${KC_ADMIN_PW_TEST:-}}"
  fi

  if [[ -z "${ADMIN_PW:-}" ]]; then
    log "SKIP ${env}: no admin password in ${admin_pw_file}"
    continue
  fi

  # kcadm.sh ile export (realm JSON)
  if docker exec "${container}" /opt/keycloak/bin/kcadm.sh config credentials \
       --server http://localhost:8080 --realm master --user admin --password "${ADMIN_PW}" >/dev/null 2>&1 \
    && docker exec "${container}" /opt/keycloak/bin/kcadm.sh get realms/${realm} 2>/dev/null | gzip > "${output}"; then
    chmod 600 "${output}"
    size=$(du -h "${output}" | cut -f1)
    log "OK ${env}:${realm} size=${size}"
  else
    log "FAIL ${env}:${realm}"
    rm -f "${output}"
    continue
  fi

  find "${dir}" -name "*.json.gz" -type f -mtime +${RETENTION_DAYS} -delete 2>/dev/null || true
done

log "DONE ${TIMESTAMP}"
