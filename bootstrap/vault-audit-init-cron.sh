#!/usr/bin/env bash
# Vault Audit Init Ensure — idempotent (Faz 18.4 Phase 1 hotfix)
# Source: Codex thread 019dc04d AGREE + docs/S5-vault-audit-retention.md idempotent ensure pattern
#
# TOPOLOJI (2026-04-24 Faz 18.4 Phase 2 kanıt):
#   Live: platform-vault-prod + platform-vault-test (iki ayrı vault, D34 per-realm).
#   compose platform-vault-audit-init-1 ZOMBIE (sleep infinity).
#
# Logic: per-env audit device 'file/' zaten enable mi kontrol et, yoksa enable et.
# Vault storage audit config kalıcıdır (container restart audit'i sıfırlamaz) → restart detection gerek yok.
#
# Install önerilen:
#   15 2 * * * /home/halil/platform-k8s-gitops/bootstrap/vault-audit-init-cron.sh
#   (snapshot 02:00 + audit-init 02:15 offset — race koruma)

set -euo pipefail

AUDIT_PATH="${AUDIT_PATH:-file/}"
AUDIT_FILE="${AUDIT_FILE:-/vault/logs/audit.log}"

log() { printf '\033[0;36m[vault-audit-init]\033[0m %s\n' "$*" >&2; }

for env in prod test; do
  container="platform-vault-${env}"
  token_file="${HOME}/bootstrap-drill/vault-init-${env}.json"

  # Container state
  state=$(docker inspect "${container}" --format "{{.State.Status}}" 2>/dev/null || echo "missing")
  if [[ "${state}" != "running" ]]; then
    log "SKIP ${env}: ${container} state=${state}"
    continue
  fi

  # Vault unseal check (retry 120s)
  MAX_WAIT=120
  waited=0
  while [[ ${waited} -lt ${MAX_WAIT} ]]; do
    if docker exec "${container}" vault status >/dev/null 2>&1; then
      break
    fi
    sleep 2
    waited=$((waited + 2))
  done

  if [[ ${waited} -ge ${MAX_WAIT} ]]; then
    log "FAIL ${env}: timeout waiting for Vault unseal"
    continue
  fi

  # Token
  if [[ ! -f "${token_file}" ]]; then
    log "SKIP ${env}: no token file ${token_file}"
    continue
  fi
  ROOT_TOKEN=$(python3 -c "import json; print(json.load(open('${token_file}'))['root_token'])")

  # Idempotent ensure (Codex guardrail)
  if docker exec -e VAULT_TOKEN="${ROOT_TOKEN}" "${container}" vault audit list 2>/dev/null | grep -q "${AUDIT_PATH}"; then
    log "OK ${env}: audit device ${AUDIT_PATH} already enabled"
    continue
  fi

  # Enable file audit
  if docker exec -e VAULT_TOKEN="${ROOT_TOKEN}" "${container}" vault audit enable file file_path="${AUDIT_FILE}" 2>/dev/null; then
    log "OK ${env}: enabled audit file at ${AUDIT_FILE}"
  else
    log "FAIL ${env}: audit enable"
  fi
done
