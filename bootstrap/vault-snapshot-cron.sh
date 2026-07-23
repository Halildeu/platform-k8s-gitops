#!/usr/bin/env bash
# Vault Raft Snapshot Cron — daily (Faz I.1.2 + Faz 18.4 Phase 1 hotfix)
# Source: ADR-0002 §0.5 + docs/S5-disaster-recovery-runbook.md
#
# TOPOLOJI (2026-04-24 Faz 18.4 Phase 2 kanıt):
#   Live container'lar: platform-vault-prod + platform-vault-test (iki ayrı vault, D34 per-realm).
#   compose platform-vault-snapshot-1 ZOMBIE (sleep infinity) — host cron authoritative.
#
# Faz 18.4 Phase 1 hotfix: original multi-vault loop RESTORED + defensive guardrails:
#   - flock: paralel-run koruma (aynı cron'un iki tick'i lap etmesin)
#   - unique temp file per-env (compose sidecar /tmp/snap.tmp legacy race hypothesis için)
#   - Retention 14 gün (repo canonical)
#
# Cron install (staging-sw):
#   0 2 * * * /home/halil/platform-k8s-gitops/bootstrap/vault-snapshot-cron.sh
#
# Output: /home/halil/platform/backup/vault/{prod,test}/vault-snapshot-<YYYYMMDD-HHMM>.snap
# Retention: 14 gün

set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/home/halil/platform/backup/vault}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
LOCK_FILE="${LOCK_FILE:-/tmp/vault-snapshot-cron.lock}"
TIMESTAMP=$(date +%Y%m%d-%H%M)

log() { printf '\033[0;36m[vault-snapshot]\033[0m %s\n' "$*" >&2; }

# Codex guardrail: flock paralel-run koruma
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  log "SKIP: another vault-snapshot run holds lock ${LOCK_FILE}"
  exit 0
fi

for env in prod test; do
  container="platform-vault-${env}"
  dir="${BACKUP_ROOT}/${env}"
  mkdir -p "${dir}"

  state=$(docker inspect "${container}" --format "{{.State.Status}}" 2>/dev/null || echo "missing")
  if [[ "${state}" != "running" ]]; then
    log "SKIP ${env}: ${container} state=${state}"
    continue
  fi

  # Vault token source. The per-environment override lets a production host
  # keep the init material under a root-only secret store instead of $HOME.
  token_file_var="VAULT_INIT_FILE_${env^^}"
  token_file="${!token_file_var:-${HOME}/bootstrap-drill/vault-init-${env}.json}"
  if [[ ! -f "${token_file}" ]]; then
    log "SKIP ${env}: no token file ${token_file}"
    continue
  fi
  ROOT_TOKEN=$(python3 -c "import json; print(json.load(open('${token_file}'))['root_token'])")

  # Codex guardrail: unique temp file (PID + timestamp) per-env — legacy compose sidecar race safe
  tmp_in_container="/tmp/snap-${env}-$$-${TIMESTAMP}.tmp"
  output="${dir}/vault-snapshot-${TIMESTAMP}.snap"
  log "SNAPSHOT ${env} → ${output} (tmp=${tmp_in_container})"

  if docker exec -e VAULT_TOKEN="${ROOT_TOKEN}" "${container}" vault operator raft snapshot save "${tmp_in_container}" 2>/dev/null \
    && docker cp "${container}:${tmp_in_container}" "${output}"; then
    chmod 600 "${output}"
    docker exec "${container}" rm -f "${tmp_in_container}" 2>/dev/null || true
    size=$(du -h "${output}" | cut -f1)
    log "OK ${env} size=${size}"
  else
    log "FAIL ${env}"
    rm -f "${output}"
    continue
  fi

  find "${dir}" -name "vault-snapshot-*.snap" -type f -mtime +"${RETENTION_DAYS}" -delete 2>/dev/null || true
done

log "DONE ${TIMESTAMP}"
