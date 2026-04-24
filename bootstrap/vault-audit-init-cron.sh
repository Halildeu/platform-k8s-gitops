#!/usr/bin/env bash
# Vault Audit Init Ensure — idempotent (Faz 18.4)
# Source: Codex thread 019dc04d AGREE + docs/S5-vault-audit-retention.md:21 idempotent ensure pattern
#
# Replace'lediği compose sidecar: platform-vault-audit-init-1 (one-shot)
# Logic: audit device 'file/' zaten enable mi kontrol et, yoksa enable et.
# Vault storage audit config kalıcıdır (container restart audit'i sıfırlamaz) → restart detection gerek yok.
#
# Install seçenekleri:
#   A) Cron @daily (drift koruma — audit device disable edilirse 24h içinde geri kurulur)
#   B) Systemd oneshot WantedBy=docker-compose-vault (container start'ında)
#   C) Manuel: cold-start sonrası tek kez host'ta run
#
# Önerilen: A (cron @daily) + B opsiyonel hardening.

set -euo pipefail

CONTAINER="${VAULT_CONTAINER:-platform-vault-1}"
TOKEN_FILE="${VAULT_TOKEN_FILE:-/home/halil/bootstrap-drill/vault-init-prod.json}"
AUDIT_PATH="${AUDIT_PATH:-file/}"
AUDIT_FILE="${AUDIT_FILE:-/vault/logs/audit.log}"

log() { printf '\033[0;36m[vault-audit-init]\033[0m %s\n' "$*" >&2; }

# Container state
state=$(docker inspect "${CONTAINER}" --format "{{.State.Status}}" 2>/dev/null || echo "missing")
if [[ "${state}" != "running" ]]; then
  log "SKIP: ${CONTAINER} state=${state}"
  exit 0
fi

# Vault unseal check (retry 120s)
MAX_WAIT=120
waited=0
while [[ ${waited} -lt ${MAX_WAIT} ]]; do
  if docker exec "${CONTAINER}" vault status >/dev/null 2>&1; then
    break
  fi
  sleep 2
  waited=$((waited + 2))
done

if [[ ${waited} -ge ${MAX_WAIT} ]]; then
  log "FAIL: timeout waiting for Vault unseal"
  exit 1
fi

# Token
if [[ ! -f "${TOKEN_FILE}" ]]; then
  log "FAIL: no token file ${TOKEN_FILE}"
  exit 1
fi
ROOT_TOKEN=$(python3 -c "import json; print(json.load(open('${TOKEN_FILE}'))['root_token'])")

# Idempotent ensure (Codex guardrail)
if docker exec -e VAULT_TOKEN="${ROOT_TOKEN}" "${CONTAINER}" vault audit list 2>/dev/null | grep -q "${AUDIT_PATH}"; then
  log "OK: audit device ${AUDIT_PATH} already enabled"
  exit 0
fi

# Enable file audit
if docker exec -e VAULT_TOKEN="${ROOT_TOKEN}" "${CONTAINER}" vault audit enable file file_path="${AUDIT_FILE}" 2>/dev/null; then
  log "OK: enabled audit file at ${AUDIT_FILE}"
else
  log "FAIL: audit enable"
  exit 1
fi
