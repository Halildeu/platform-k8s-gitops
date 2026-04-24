#!/usr/bin/env bash
# Vault Raft Snapshot Cron — daily (Faz 18.4, revize)
# Source: ADR-0002 §0.5 + docs/S5-disaster-recovery-runbook.md + Codex thread 019dc04d AGREE
#
# Faz 18.4 değişiklikleri (compose vault-snapshot-1 retirement replacement):
#   - Tek vault topolojisi: `platform-vault-1` (multi-vault loop kaldırıldı)
#   - flock: paralel run engelleme (Codex guardrail: compose sidecar + host cron 48h co-exist)
#   - unique temp file: /tmp/snap-<PID>-<timestamp>.tmp (race koruma)
#   - Retention 14 gün (repo canonical; compose 7 gün override yok)
#   - Schedule offset önerisi: 02:00 (compose sidecar 24h loop'tan bağımsız)
#
# Cron install (staging-sw):
#   0 2 * * * /home/halil/platform-k8s-gitops/bootstrap/vault-snapshot-cron.sh
#
# Output: /home/halil/platform/backup/vault/vault-snapshot-<YYYYMMDD-HHMM>.snap
# Retention: 14 gün

set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/home/halil/platform/backup/vault}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
CONTAINER="${VAULT_CONTAINER:-platform-vault-1}"
TOKEN_FILE="${VAULT_TOKEN_FILE:-/home/halil/bootstrap-drill/vault-init-prod.json}"
LOCK_FILE="${LOCK_FILE:-/tmp/vault-snapshot-cron.lock}"
TIMESTAMP=$(date +%Y%m%d-%H%M)

log() { printf '\033[0;36m[vault-snapshot]\033[0m %s\n' "$*" >&2; }

# Codex guardrail: flock paralel run + Phase 2 compose co-exist race koruma
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  log "SKIP: another vault-snapshot run holds lock ${LOCK_FILE}"
  exit 0
fi

mkdir -p "${BACKUP_ROOT}"

# Vault container state
state=$(docker inspect "${CONTAINER}" --format "{{.State.Status}}" 2>/dev/null || echo "missing")
if [[ "${state}" != "running" ]]; then
  log "SKIP: ${CONTAINER} state=${state}"
  exit 0
fi

# Token
if [[ ! -f "${TOKEN_FILE}" ]]; then
  log "FAIL: no token file ${TOKEN_FILE}"
  exit 1
fi
ROOT_TOKEN=$(python3 -c "import json; print(json.load(open('${TOKEN_FILE}'))['root_token'])")

# Codex guardrail: unique temp file (PID + timestamp) — compose sidecar legacy /tmp/snap.tmp race safe
TMP_IN_CONTAINER="/tmp/snap-$$-${TIMESTAMP}.tmp"
output="${BACKUP_ROOT}/vault-snapshot-${TIMESTAMP}.snap"

log "SNAPSHOT → ${output} (tmp=${TMP_IN_CONTAINER})"

if docker exec -e VAULT_TOKEN="${ROOT_TOKEN}" "${CONTAINER}" vault operator raft snapshot save "${TMP_IN_CONTAINER}" 2>/dev/null \
  && docker cp "${CONTAINER}:${TMP_IN_CONTAINER}" "${output}"; then
  chmod 600 "${output}"
  docker exec "${CONTAINER}" rm -f "${TMP_IN_CONTAINER}" 2>/dev/null || true
  size=$(du -h "${output}" | cut -f1)
  log "OK size=${size}"
else
  log "FAIL snapshot save/cp"
  rm -f "${output}"
  exit 1
fi

# Retention: 14 gün
find "${BACKUP_ROOT}" -name "vault-snapshot-*.snap" -type f -mtime +"${RETENTION_DAYS}" -delete 2>/dev/null || true

log "DONE ${TIMESTAMP}"
