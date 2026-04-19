#!/usr/bin/env bash
# Backup Freshness Exporter — node_exporter textfile collector
# Source: kustomize/base/monitoring/backup-freshness-rule.yaml (Codex iter-8)
#
# Cron: 0 * * * *  (her saat başı, dosya timestamp güncel kalır)
# Install (systemd veya crontab):
#   sudo crontab -e
#     0 * * * * /home/halil/platform-k8s-gitops/bootstrap/backup-freshness-exporter.sh
#
# Output: /var/lib/node_exporter/backup_freshness.prom
# node_exporter args: --collector.textfile.directory=/var/lib/node_exporter

set -euo pipefail

PG_BACKUP_DIR="${PG_BACKUP_DIR:-/home/halil/platform/backup/pg}"
KC_BACKUP_DIR="${KC_BACKUP_DIR:-/home/halil/platform/backup/keycloak}"
VAULT_BACKUP_DIR="${VAULT_BACKUP_DIR:-/home/halil/platform/backup/vault}"
OUTPUT_FILE="${OUTPUT_FILE:-/var/lib/node_exporter/backup_freshness.prom}"

OUTPUT_DIR=$(dirname "${OUTPUT_FILE}")
if [[ ! -d "${OUTPUT_DIR}" ]]; then
  echo "ERROR: node_exporter textfile dir yok: ${OUTPUT_DIR}"
  echo "Oluştur: sudo mkdir -p ${OUTPUT_DIR} && sudo chown node_exporter ${OUTPUT_DIR}"
  exit 1
fi

# Atomik write — temp file + rename
TEMP_FILE=$(mktemp "${OUTPUT_FILE}.XXXXXX")

latest_timestamp() {
  local dir="${1}"
  local pattern="${2}"
  if [[ ! -d "${dir}" ]]; then
    echo "0"
    return
  fi
  # Son dosya mtime epoch
  find "${dir}" -name "${pattern}" -type f -printf '%T@\n' 2>/dev/null \
    | sort -n | tail -1 | cut -d. -f1 | awk 'NF {print; exit} END {if (!NR) print "0"}'
}

PG_TS=$(latest_timestamp "${PG_BACKUP_DIR}" "pg_dumpall_*.sql.gz")
KC_TS=$(latest_timestamp "${KC_BACKUP_DIR}" "serban-*.json.gz")
VAULT_TS=$(latest_timestamp "${VAULT_BACKUP_DIR}" "vault-snapshot-*.snap")

cat > "${TEMP_FILE}" <<EOF
# HELP backup_last_success_timestamp_seconds Unix timestamp of last successful backup per type
# TYPE backup_last_success_timestamp_seconds gauge
backup_last_success_timestamp_seconds{type="pg"} ${PG_TS}
backup_last_success_timestamp_seconds{type="kc"} ${KC_TS}
backup_last_success_timestamp_seconds{type="vault"} ${VAULT_TS}
EOF

mv -f "${TEMP_FILE}" "${OUTPUT_FILE}"

echo "✓ Backup freshness exported: PG=${PG_TS} KC=${KC_TS} Vault=${VAULT_TS}"
echo "  Output: ${OUTPUT_FILE}"
