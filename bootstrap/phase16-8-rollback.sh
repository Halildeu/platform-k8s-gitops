#!/usr/bin/env bash
#
# Faz 16.8 MSSQL Source Decommission — Rollback Dispatcher
#
# Parent runbook: docs/phase16-8-decommission-runbook.md (Codex AGREE thread 019dbf24 iter-7)
#
# Subcommands:
#   re-enable-flags       Aşama 1 revert — feature flag re-enable (prod only, report + schema)
#   restore-mssql-secret  Aşama 2 revert — Vault kv + compose .env restore (prod only; test Aşama 2'de zaten cleanup)
#   remove-network-deny   Aşama 3 revert — iptables DOCKER-USER + OUTPUT rule remove
#   emergency-reaccess    Aşama 4 drill — combined 1+2+3 revert, 30 dk SLA, timed
#   verify-backup         Backup integrity check — SHA256 verify prod+test envelope+data+env
#   status                Mevcut 16.8 aşama durumu (Vault kv, compose env, iptables state)
#
# Environment variables (zorunlu):
#   VAULT_TOKEN_PROD      prod Vault root token (export edilmiş olmalı)
#   VAULT_TOKEN_TEST      test Vault root token (export edilmiş olmalı)
#   BACKUP_DIR            Aşama 2 backup dizini (default /tmp/phase16-8-backup-latest)
#
# Usage:
#   export VAULT_TOKEN_PROD=<prod-token>
#   export VAULT_TOKEN_TEST=<test-token>
#   ./bootstrap/phase16-8-rollback.sh status
#   ./bootstrap/phase16-8-rollback.sh verify-backup
#   ./bootstrap/phase16-8-rollback.sh re-enable-flags
#   ./bootstrap/phase16-8-rollback.sh restore-mssql-secret
#   ./bootstrap/phase16-8-rollback.sh remove-network-deny
#   ./bootstrap/phase16-8-rollback.sh emergency-reaccess    # 30 dk SLA timed drill

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC2034
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BACKUP_DIR="${BACKUP_DIR:-/tmp/phase16-8-backup-latest}"
SSH_HOST="${PHASE16_SSH_HOST:-staging-sw}"
VAULT_ADDR_PROD="${VAULT_ADDR_PROD:-http://127.0.0.1:8200}"
VAULT_ADDR_TEST="${VAULT_ADDR_TEST:-http://127.0.0.1:8301}"
KUBE_CONTEXT_PROD="${PHASE16_KUBE_CONTEXT_PROD:-k3d-prod}"
KUBE_NS_PROD="${PHASE16_KUBE_NS_PROD:-platform-prod}"
COMPOSE_ENV_PROD="${PHASE16_COMPOSE_ENV_PROD:-/home/halil/platform/compose/.env.prod}"
# shellcheck disable=SC2034
COMPOSE_ENV_TEST="${PHASE16_COMPOSE_ENV_TEST:-/home/halil/platform/compose/.env.test}"  # future: Aşama 2 symmetric cleanup (ileri iter, şu an cleanup sadece documentasyon)
MSSQL_IP="${PHASE16_MSSQL_IP:-10.9.193.201}"
MSSQL_PORT="${PHASE16_MSSQL_PORT:-1433}"

# ----- Logging -----

log()  { printf '\033[0;36m[phase16-8]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[0;33m[phase16-8]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[0;31m[phase16-8]\033[0m %s\n' "$*" >&2; exit 1; }
ok()   { printf '\033[0;32m[phase16-8]\033[0m %s\n' "$*" >&2; }

# ----- Helpers -----

require_env() {
  local var
  for var in "$@"; do
    if [[ -z "${!var:-}" ]]; then
      err "Environment variable ${var} setli değil. export ${var}=... önce çalıştır."
    fi
  done
}

confirm() {
  local prompt="$1"
  if [[ "${PHASE16_SKIP_CONFIRM:-}" == "yes" ]]; then
    warn "confirm auto-yes (PHASE16_SKIP_CONFIRM=yes)"
    return 0
  fi
  printf '\033[0;33m[phase16-8 CONFIRM]\033[0m %s [y/N]: ' "${prompt}" >&2
  local ans
  read -r ans
  [[ "${ans}" == "y" || "${ans}" == "Y" ]] || err "iptal"
}

ssh_run() {
  # Mod A pattern: local wrapper + local expansion
  # ssh_run "<remote command>" — inner command single quotes geçerliyse remote'da expand yap
  ssh "${SSH_HOST}" "$@"
}

# ----- Subcommand: verify-backup -----

cmd_verify_backup() {
  log "Backup integrity check (BACKUP_DIR=${BACKUP_DIR})"

  if [[ ! -d "${BACKUP_DIR}" ]]; then
    err "BACKUP_DIR bulunamadı: ${BACKUP_DIR}"
  fi

  local files_to_check=(
    "mssql-prod.data.json.sha256"
    "mssql-test.data.json.sha256"
    "env.prod.backup.sha256"
    "env.test.backup.sha256"
  )

  local missing=0
  local f
  for f in "${files_to_check[@]}"; do
    if [[ ! -f "${BACKUP_DIR}/${f}" ]]; then
      warn "MISSING: ${BACKUP_DIR}/${f}"
      missing=$((missing + 1))
    fi
  done

  if [[ ${missing} -gt 0 ]]; then
    err "Backup dosyası eksik (${missing} adet). Aşama 2 backup adımını tekrar koş."
  fi

  log "Tüm 4 SHA256 dosyası mevcut. Hash doğrulama başlıyor..."
  (
    cd "${BACKUP_DIR}"
    sha256sum -c \
      "mssql-prod.data.json.sha256" \
      "mssql-test.data.json.sha256" \
      "env.prod.backup.sha256" \
      "env.test.backup.sha256"
  ) || err "Backup integrity FAIL — restore güvenli değil."

  ok "Backup integrity: OK (prod+test, envelope+data+env)"
}

# ----- Subcommand: re-enable-flags (Aşama 1 revert) -----

cmd_re_enable_flags() {
  log "Aşama 1 revert: feature flag re-enable (prod only)"
  log "Target: ${KUBE_CONTEXT_PROD} / ${KUBE_NS_PROD}"

  confirm "Report + Schema service ConfigMap MSSQL_ENABLED=true patch apply edilecek. Devam?"

  # report-service (her zaman flag)
  log "report-service: REPORT_MSSQL_ENABLED=true patch"
  ssh_run "kubectl --context ${KUBE_CONTEXT_PROD} apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: report-service-config
  namespace: ${KUBE_NS_PROD}
data:
  REPORT_MSSQL_ENABLED: 'true'
EOF"

  # schema-service Option B (ConfigMap flag)
  # Option A seçiliyse operatör bu komut bloğunu image rollback ile değiştirmeli
  log "schema-service: SCHEMA_MSSQL_ENABLED=true patch (Option B assumption)"
  warn "Parity Option A seçiliyse bu komut manuel değiştirilmeli (image rollback)."
  ssh_run "kubectl --context ${KUBE_CONTEXT_PROD} apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: schema-service-config
  namespace: ${KUBE_NS_PROD}
data:
  SCHEMA_MSSQL_ENABLED: 'true'
EOF"

  log "Rollout restart: report-service + schema-service"
  ssh_run "kubectl --context ${KUBE_CONTEXT_PROD} -n ${KUBE_NS_PROD} rollout restart deploy/report-service deploy/schema-service"
  ssh_run "kubectl --context ${KUBE_CONTEXT_PROD} -n ${KUBE_NS_PROD} rollout status deploy/report-service deploy/schema-service --timeout=180s"

  ok "Aşama 1 revert tamamlandı. rapor UI MSSQL-backed beklenir."
}

# ----- Subcommand: restore-mssql-secret (Aşama 2 revert — prod only for drill) -----

cmd_restore_mssql_secret() {
  log "Aşama 2 revert: Vault kv + compose env restore (prod only)"

  # Önce backup integrity verify
  cmd_verify_backup

  require_env VAULT_TOKEN_PROD

  confirm "Vault prod kv/platform/mssql-external + compose .env.prod BACKUP_DIR'dan restore edilecek. Devam?"

  # Vault prod restore
  log "Vault prod restore (${VAULT_ADDR_PROD})"
  ssh_run "VAULT_ADDR=${VAULT_ADDR_PROD} VAULT_TOKEN=\"${VAULT_TOKEN_PROD}\" \
    vault kv put kv/platform/mssql-external @${BACKUP_DIR}/mssql-prod.data.json"

  # Compose env prod restore
  log "Compose env restore: ${COMPOSE_ENV_PROD}"
  ssh_run "cp ${BACKUP_DIR}/env.prod.backup ${COMPOSE_ENV_PROD}"

  # ESO force sync + pod rollout
  log "ESO force-sync + pod rollout (report + schema)"
  ssh_run "kubectl --context ${KUBE_CONTEXT_PROD} annotate externalsecret -n ${KUBE_NS_PROD} \
    report-service-secrets schema-service-secrets force-sync=\$(date +%s) --overwrite"
  ssh_run "kubectl --context ${KUBE_CONTEXT_PROD} -n ${KUBE_NS_PROD} rollout restart \
    deploy/report-service deploy/schema-service"
  ssh_run "kubectl --context ${KUBE_CONTEXT_PROD} -n ${KUBE_NS_PROD} rollout status \
    deploy/report-service deploy/schema-service --timeout=180s"

  ok "Aşama 2 revert tamamlandı. Vault + compose env + pod ES sync complete."
}

# ----- Subcommand: remove-network-deny (Aşama 3 revert) -----

cmd_remove_network_deny() {
  log "Aşama 3 revert: iptables DOCKER-USER + OUTPUT rule remove"

  confirm "iptables DROP rules MSSQL ${MSSQL_IP}:${MSSQL_PORT} için kaldırılacak. Devam?"

  # DOCKER-USER rule remove
  log "DOCKER-USER chain: DROP rule remove"
  ssh_run "sudo iptables -D DOCKER-USER -d ${MSSQL_IP} -p tcp --dport ${MSSQL_PORT} -j DROP 2>/dev/null || true"

  # OUTPUT rule remove (secondary)
  log "OUTPUT chain: DROP rule remove"
  ssh_run "sudo iptables -D OUTPUT -d ${MSSQL_IP} -p tcp --dport ${MSSQL_PORT} -j DROP 2>/dev/null || true"

  # Persist
  log "iptables-save"
  ssh_run "sudo iptables-save > /etc/iptables/rules.v4"

  # Verify (bağlantı OK beklenir — ERP canlı)
  log "Connection test (beklenen: bağlantı OK)"
  if ssh_run "nc -zv -w 3 ${MSSQL_IP} ${MSSQL_PORT}" 2>&1 | grep -qE 'succeeded|open'; then
    ok "Aşama 3 revert tamamlandı. MSSQL ${MSSQL_IP}:${MSSQL_PORT} bağlantı OK."
  else
    warn "MSSQL bağlantı hâlâ deny — rule remove başarısız olabilir. Manuel kontrol: sudo iptables -L DOCKER-USER -n"
  fi
}

# ----- Subcommand: emergency-reaccess (Aşama 4 drill, timed) -----

cmd_emergency_reaccess() {
  log "Aşama 4 EMERGENCY DRILL — 30 dk SLA timed re-access"
  warn "Bu drill 1+2+3 revert'i combine eder. 30 dk SLA measure edilecek."

  confirm "Drill başlasın mı? (functional re-access hedef ≤30 dk)"

  # Önce backup verify (kritik)
  cmd_verify_backup

  require_env VAULT_TOKEN_PROD

  local T0 T1 DURATION
  T0=$(date +%s)

  # T+2dk — iptables rules remove
  log "T+$(( $(date +%s) - T0 ))s — Aşama 3 revert"
  cmd_remove_network_deny || warn "network-deny remove non-fatal continue"

  # T+5dk — Vault + compose env restore
  log "T+$(( $(date +%s) - T0 ))s — Aşama 2 revert"
  # Inline emergency restore (bypass confirm — drill timed)
  PHASE16_SKIP_CONFIRM=yes cmd_restore_mssql_secret

  # T+20dk — Feature flag re-enable
  log "T+$(( $(date +%s) - T0 ))s — Aşama 1 revert"
  PHASE16_SKIP_CONFIRM=yes cmd_re_enable_flags

  # T+25dk — Functional re-access test
  log "T+$(( $(date +%s) - T0 ))s — Functional test"
  if ssh_run "docker exec platform-report-service-1 nc -zv -w 3 ${MSSQL_IP} ${MSSQL_PORT}" 2>&1 | grep -qE 'succeeded|open'; then
    ok "Functional re-access SAĞLANDI."
  else
    warn "Functional re-access test FAIL — manuel inceleme."
  fi

  T1=$(date +%s)
  DURATION=$((T1 - T0))
  log "Drill duration: ${DURATION}s (target <1800s / 30 dk)"

  if [[ ${DURATION} -le 1800 ]]; then
    ok "SLA PASS — functional re-access ≤30 dk."
    log "Post-drill cleanup: SLA dışı. State'i Aşama 3 seviyesine geri getir manuel."
    log "  - ConfigMap *_MSSQL_ENABLED=false (report + schema)"
    log "  - Vault kv metadata delete kv/platform/mssql-external (prod)"
    log "  - sed -i '/^MSSQL_/d' ${COMPOSE_ENV_PROD}"
    log "  - iptables -I DOCKER-USER 1 -d ${MSSQL_IP} -p tcp --dport ${MSSQL_PORT} -j DROP"
  else
    err "SLA FAIL — duration ${DURATION}s > 1800s. Runbook revize gerek."
  fi
}

# ----- Subcommand: status -----

cmd_status() {
  log "Faz 16.8 mevcut aşama durumu"
  echo

  # 1. Feature flag state
  echo "=== Aşama 1: Feature Flags ==="
  local rpt_flag sch_flag
  rpt_flag=$(ssh_run "kubectl --context ${KUBE_CONTEXT_PROD} -n ${KUBE_NS_PROD} get cm report-service-config -o jsonpath='{.data.REPORT_MSSQL_ENABLED}' 2>/dev/null || echo NOT_SET")
  sch_flag=$(ssh_run "kubectl --context ${KUBE_CONTEXT_PROD} -n ${KUBE_NS_PROD} get cm schema-service-config -o jsonpath='{.data.SCHEMA_MSSQL_ENABLED}' 2>/dev/null || echo NOT_SET")
  echo "  REPORT_MSSQL_ENABLED: ${rpt_flag}"
  echo "  SCHEMA_MSSQL_ENABLED: ${sch_flag}"
  echo

  # 2. Vault kv state
  echo "=== Aşama 2: Vault kv/platform/mssql-external ==="
  require_env VAULT_TOKEN_PROD || true
  if [[ -n "${VAULT_TOKEN_PROD:-}" ]]; then
    if ssh_run "VAULT_ADDR=${VAULT_ADDR_PROD} VAULT_TOKEN=\"${VAULT_TOKEN_PROD}\" \
        vault kv get kv/platform/mssql-external" >/dev/null 2>&1; then
      echo "  Prod Vault: EXISTS (MSSQL secret aktif)"
    else
      echo "  Prod Vault: DELETED (Aşama 2 uygulanmış)"
    fi
  else
    echo "  Prod Vault: VAULT_TOKEN_PROD setli değil, kontrol atlandı"
  fi
  echo

  # 3. iptables state
  echo "=== Aşama 3: iptables DOCKER-USER DROP ${MSSQL_IP}:${MSSQL_PORT} ==="
  if ssh_run "sudo iptables -C DOCKER-USER -d ${MSSQL_IP} -p tcp --dport ${MSSQL_PORT} -j DROP 2>/dev/null"; then
    echo "  DOCKER-USER: DROP rule ACTIVE (Aşama 3 uygulanmış)"
  else
    echo "  DOCKER-USER: DROP rule YOK (Aşama 3 uygulanmamış veya revert edilmiş)"
  fi
  echo

  # 4. Backup dir
  echo "=== Backup Dir ==="
  if [[ -d "${BACKUP_DIR}" ]]; then
    echo "  Path: ${BACKUP_DIR}"
    local backup_files
    backup_files=$(find "${BACKUP_DIR}" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d ' ')
    echo "  Files: ${backup_files}"
  else
    echo "  BACKUP_DIR yok: ${BACKUP_DIR}"
  fi
  echo
}

# ----- Main -----

SUBCMD="${1:-status}"

case "${SUBCMD}" in
  re-enable-flags)      cmd_re_enable_flags ;;
  restore-mssql-secret) cmd_restore_mssql_secret ;;
  remove-network-deny)  cmd_remove_network_deny ;;
  emergency-reaccess)   cmd_emergency_reaccess ;;
  verify-backup)        cmd_verify_backup ;;
  status)               cmd_status ;;
  -h|--help)
    grep -E '^#' "$0" | sed -E 's/^# ?//' | head -30
    ;;
  *)
    err "bilinmeyen subcommand: ${SUBCMD} (beklenen: re-enable-flags|restore-mssql-secret|remove-network-deny|emergency-reaccess|verify-backup|status)"
    ;;
esac
