#!/usr/bin/env bash
# Vault Raft Snapshot Cron — daily (Faz I.1.2)
# Source: ADR-0002 §0.5 + docs/S5-disaster-recovery-runbook.md
#
# Cron install (staging-sw):
#   0 2 * * * /home/halil/platform-k8s-gitops/bootstrap/vault-snapshot-cron.sh
#
# Output: /home/halil/platform/backup/vault/{prod,test}/vault-snapshot-<YYYYMMDD-HHMM>.snap
# Retention: 14 gün (Vault state daha küçük + snapshot büyük)

set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/home/halil/platform/backup/vault}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TIMESTAMP=$(date +%Y%m%d-%H%M)

log() { printf '\033[0;36m[vault-snapshot]\033[0m %s\n' "$*" >&2; }

for env in prod test; do
  container="platform-vault-${env}"
  dir="${BACKUP_ROOT}/${env}"
  mkdir -p "${dir}"

  state=$(docker inspect "${container}" --format "{{.State.Status}}" 2>/dev/null || echo "missing")
  if [[ "${state}" != "running" ]]; then
    log "SKIP ${env}: ${container} state=${state}"
    continue
  fi

  # Vault token (root) bootstrap-drill'den
  token_file="${HOME}/bootstrap-drill/vault-init-${env}.json"
  if [[ ! -f "${token_file}" ]]; then
    log "SKIP ${env}: no token file ${token_file}"
    continue
  fi
  ROOT_TOKEN=$(python3 -c "import json; print(json.load(open('${token_file}'))['root_token'])")

  output="${dir}/vault-snapshot-${TIMESTAMP}.snap"
  log "SNAPSHOT ${env} → ${output}"

  if docker exec -e VAULT_TOKEN="${ROOT_TOKEN}" "${container}" vault operator raft snapshot save /tmp/snap.tmp 2>/dev/null \
    && docker cp "${container}:/tmp/snap.tmp" "${output}"; then
    chmod 600 "${output}"
    docker exec "${container}" rm -f /tmp/snap.tmp 2>/dev/null || true
    size=$(du -h "${output}" | cut -f1)
    log "OK ${env} size=${size}"
  else
    log "FAIL ${env}"
    rm -f "${output}"
    continue
  fi

  find "${dir}" -name "vault-snapshot-*.snap" -type f -mtime +${RETENTION_DAYS} -delete 2>/dev/null || true
done

log "DONE ${TIMESTAMP}"
