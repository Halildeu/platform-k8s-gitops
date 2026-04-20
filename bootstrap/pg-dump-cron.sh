#!/usr/bin/env bash
# PG Backup Cron — hourly pg_dumpall for prod + test (Faz I.1.1)
# Source: ADR-0002 §0.5 backup requirement + docs/day-2-governance.md
#
# Cron install (staging-sw):
#   sudo crontab -e
#     0 * * * * /home/halil/platform-k8s-gitops/bootstrap/pg-dump-cron.sh >> /var/log/platform-backup-cron.log 2>&1
#
# Output: /home/halil/platform/backup/pg/{prod,test}/pg_dumpall_<YYYYMMDD-HHMM>.sql.gz
# Retention: 30 gün (Faz I.1 spec); older files silinir

set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/home/halil/platform/backup/pg}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TIMESTAMP=$(date +%Y%m%d-%H%M)

log() { printf '\033[0;36m[pg-dump-cron]\033[0m %s\n' "$*" >&2; }

for env in prod test; do
  container="platform-pg-${env}"
  dir="${BACKUP_ROOT}/${env}"
  mkdir -p "${dir}"

  # Container çalışıyor mu?
  state=$(docker inspect "${container}" --format "{{.State.Status}}" 2>/dev/null || echo "missing")
  if [[ "${state}" != "running" ]]; then
    log "SKIP ${env}: ${container} state=${state}"
    continue
  fi

  output="${dir}/pg_dumpall_${TIMESTAMP}.sql.gz"
  log "DUMP ${env} → ${output}"

  if docker exec "${container}" pg_dumpall -U postgres 2>/dev/null | gzip > "${output}"; then
    chmod 600 "${output}"
    size=$(du -h "${output}" | cut -f1)
    log "OK ${env} size=${size}"
  else
    log "FAIL ${env}: pg_dumpall exit non-zero"
    rm -f "${output}"
    continue
  fi

  # Retention: 30 gün eskisini sil
  find "${dir}" -name "pg_dumpall_*.sql.gz" -type f -mtime +${RETENTION_DAYS} -delete 2>/dev/null || true
done

log "DONE ${TIMESTAMP}"
