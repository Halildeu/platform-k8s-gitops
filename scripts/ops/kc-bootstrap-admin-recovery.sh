#!/usr/bin/env bash
# scripts/ops/kc-bootstrap-admin-recovery.sh
#
# PR-S1 (PERF-INIT-V2): Keycloak master-admin password drift recovery.
#
# Recovers from the case where the host-compose Keycloak secret file
# (host-compose/keycloak/<env>/secrets/kc_admin_password.txt) no longer
# matches the password stored inside the Keycloak database.
#
# Pattern (KC 26.5.x):
#   1. Bootstrap a temp admin user via `kc.sh bootstrap-admin user` (works
#      against an already-running KC; touches the DB directly).
#   2. Use temp admin to log in to the master realm Admin API.
#   3. Reset the `admin` user's password to the canonical file value.
#   4. Delete the temp recovery user (audit clean).
#   5. Verify file password works.
#
# Usage:
#   kc-bootstrap-admin-recovery.sh [test|prod]
#
# Why this exists (PMD §4.1 PR-S1):
#   2026-05-10 incident: KC test instance unhealthy for ~3 hours because the
#   `keycloak_user` PG password drifted AND the `admin` master realm password
#   was rotated via UI without updating the secret file. Operator recovery
#   required temp-admin + REST API reset.
#
# Companion: scripts/ops/rotate-pg-vault-user.sh
#            docs/RB-pg-vault-secret-parity.md

set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
readonly SCRIPT_NAME
readonly AUDIT_LOG="${HOME}/.claude/logs/kc-recovery.log"
mkdir -p "$(dirname "${AUDIT_LOG}")"

log() {
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[${ts}] [${SCRIPT_NAME}] $*" | tee -a "${AUDIT_LOG}"
}

usage() {
  cat >&2 <<EOF
Usage: ${SCRIPT_NAME} [test|prod] [--dry-run]

Arguments:
  env                test (default) or prod

Options:
  --dry-run          Print actions but do not mutate

Environment:
  KC_HOST_PORT       KC host port (default: 8082 for test, 8081 for prod)
  KC_CONTAINER       Override container name (default: platform-kc-<env>)
  KC_PASS_FILE       Override secret file path

Exit codes:
  0   success (admin password reset + temp user cleaned + verify OK)
  1   invalid usage
  2   pre-flight failure (KC container not running)
  3   bootstrap-admin failed
  4   verification failed
EOF
}

ENV_NAME="test"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    test|prod)
      ENV_NAME="$1"
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

KC_CONTAINER="${KC_CONTAINER:-platform-kc-${ENV_NAME}}"
KC_PASS_FILE="${KC_PASS_FILE:-/home/halil/platform-k8s-gitops/host-compose/keycloak/${ENV_NAME}/secrets/kc_admin_password.txt}"
KC_HOST_PORT="${KC_HOST_PORT:-$([ "${ENV_NAME}" = "test" ] && echo 8082 || echo 8081)}"
KC_URL="http://127.0.0.1:${KC_HOST_PORT}"

log "env=${ENV_NAME} container=${KC_CONTAINER} url=${KC_URL} dry-run=${DRY_RUN}"

# --- Step 0: pre-flight -----------------------------------------------------

if ! docker inspect "${KC_CONTAINER}" >/dev/null 2>&1; then
  log "FATAL: container ${KC_CONTAINER} not found"
  exit 2
fi

if [[ ! -r "${KC_PASS_FILE}" ]]; then
  log "FATAL: secret file ${KC_PASS_FILE} not readable"
  exit 2
fi

CANONICAL_PASS="$(sudo cat "${KC_PASS_FILE}" 2>/dev/null || cat "${KC_PASS_FILE}")"
if [[ -z "${CANONICAL_PASS}" ]]; then
  log "FATAL: secret file is empty"
  exit 2
fi
log "  -> canonical password file readable (len=${#CANONICAL_PASS})"

# --- Step 1: bootstrap temp recovery admin ----------------------------------

TEMP_USER="temp-recovery-$(date +%s)"
TEMP_PASS="$(openssl rand -base64 24 | tr -d '=+/' | head -c 32)"

log "Step 1/5 — bootstrap-admin user ${TEMP_USER}"

if [[ ${DRY_RUN} -eq 1 ]]; then
  log "DRY-RUN: would call kc.sh bootstrap-admin user --username ${TEMP_USER}"
else
  if docker exec -e KC_TEMP_PASS="${TEMP_PASS}" "${KC_CONTAINER}" \
        /opt/keycloak/bin/kc.sh bootstrap-admin user \
          --username "${TEMP_USER}" \
          --password:env KC_TEMP_PASS \
          --no-prompt 2>&1 | tail -5 | tee -a "${AUDIT_LOG}"; then
    log "  -> bootstrap-admin succeeded"
  else
    log "FATAL: bootstrap-admin failed (see KC container logs)"
    exit 3
  fi
fi

# --- Step 2: log in with temp admin -----------------------------------------

log "Step 2/5 — obtain master realm admin token via ${TEMP_USER}"

if [[ ${DRY_RUN} -eq 0 ]]; then
  TOK="$(curl -sf -X POST "${KC_URL}/realms/master/protocol/openid-connect/token" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode "username=${TEMP_USER}" \
    --data-urlencode "password=${TEMP_PASS}" \
    --data-urlencode 'grant_type=password' \
    --data-urlencode 'client_id=admin-cli' \
    | jq -r '.access_token' 2>/dev/null || echo "")"

  if [[ -z "${TOK}" || "${TOK}" == "null" ]]; then
    log "FATAL: could not obtain token with ${TEMP_USER}"
    exit 3
  fi
  log "  -> token acquired (len=${#TOK})"
fi

# --- Step 3: reset 'admin' user password -----------------------------------

log "Step 3/5 — reset 'admin' user password to canonical file value"

if [[ ${DRY_RUN} -eq 0 ]]; then
  ADMIN_ID="$(curl -sf -H "Authorization: Bearer ${TOK}" \
    "${KC_URL}/admin/realms/master/users?username=admin&exact=true" \
    | jq -r '.[0].id // empty')"

  if [[ -z "${ADMIN_ID}" ]]; then
    log "FATAL: master realm has no 'admin' user (recovery requires existing admin)"
    exit 3
  fi

  RESET_BODY="$(jq -n --arg pw "${CANONICAL_PASS}" \
    '{type:"password",value:$pw,temporary:false}')"

  if curl -sf -X PUT "${KC_URL}/admin/realms/master/users/${ADMIN_ID}/reset-password" \
       -H "Authorization: Bearer ${TOK}" \
       -H 'Content-Type: application/json' \
       -d "${RESET_BODY}" >/dev/null 2>&1; then
    log "  -> admin password reset succeeded"
  else
    log "FATAL: admin password reset failed"
    exit 3
  fi
fi

# --- Step 4: delete temp recovery user (audit clean) -----------------------

log "Step 4/5 — delete temp recovery user"

if [[ ${DRY_RUN} -eq 0 ]]; then
  TEMP_ID="$(curl -sf -H "Authorization: Bearer ${TOK}" \
    "${KC_URL}/admin/realms/master/users?username=${TEMP_USER}&exact=true" \
    | jq -r '.[0].id // empty')"

  if [[ -n "${TEMP_ID}" ]]; then
    if curl -sf -X DELETE "${KC_URL}/admin/realms/master/users/${TEMP_ID}" \
         -H "Authorization: Bearer ${TOK}" >/dev/null 2>&1; then
      log "  -> temp user deleted"
    else
      log "WARN: temp user delete failed (manual cleanup needed)"
    fi
  fi
fi

# --- Step 5: verify canonical password works -------------------------------

log "Step 5/5 — verify canonical password works for admin"

if [[ ${DRY_RUN} -eq 0 ]]; then
  VERIFY_RESP="$(curl -s -X POST "${KC_URL}/realms/master/protocol/openid-connect/token" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'username=admin' \
    --data-urlencode "password=${CANONICAL_PASS}" \
    --data-urlencode 'grant_type=password' \
    --data-urlencode 'client_id=admin-cli')"

  if echo "${VERIFY_RESP}" | jq -e '.access_token' >/dev/null 2>&1; then
    log "  -> verification PASS — admin login with file password works"
  else
    log "FATAL: verification FAILED — admin still cannot log in"
    log "       Response: $(echo "${VERIFY_RESP}" | jq -c '. // .')"
    exit 4
  fi
fi

log "DONE — Keycloak ${ENV_NAME} master-admin recovery completed"
exit 0
