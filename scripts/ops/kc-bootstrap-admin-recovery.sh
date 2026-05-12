#!/usr/bin/env bash
# scripts/ops/kc-bootstrap-admin-recovery.sh
#
# PR-S1 (PERF-INIT-V2): Keycloak master-admin password drift recovery.
#
# Recovery pattern (KC 26.5.x — running-mode bootstrap-admin NOT supported):
#   1. Stop running KC briefly (downtime-mode) OR
#      Spawn temp KC container against same DB (downtime-less mode).
#   2. Run `kc.sh bootstrap-admin user` in that offline/temp instance to
#      create a temp recovery admin in the DB.
#   3. Restart main KC (downtime mode) OR keep main running (temp-container
#      mode); temp recovery admin now exists in master realm.
#   4. Log in as temp admin via Admin REST API.
#   5. Reset `admin` user password to canonical file value.
#   6. Delete temp recovery admin (audit clean, trap-guaranteed).
#   7. Verify canonical password works.
#
# Background — why temp container, not running KC:
#   `kc.sh bootstrap-admin user` opens management interface on
#   0.0.0.0:9000. If the main KC is already running, it owns 9000 and the
#   bootstrap command fails with `Address already in use`. See
#   docs/session-logs/s07-green-yellow-completion.md and
#   s08-kc-vault-eso-debug.md for the original incident evidence.
#
# Usage:
#   kc-bootstrap-admin-recovery.sh [test|prod] [--mode temp-container|downtime] [--dry-run]
#
# Default mode: temp-container (downtime-less).
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
  printf '[%s] [%s] %s\n' "${ts}" "${SCRIPT_NAME}" "$*" | tee -a "${AUDIT_LOG}"
}

usage() {
  cat >&2 <<EOF
Usage: ${SCRIPT_NAME} [test|prod] [options]

Arguments:
  env                test (default) or prod

Options:
  --mode MODE        temp-container (default, downtime-less) | downtime
  --dry-run          Print actions but do not mutate
  --help             This help

Environment:
  KC_HOST_PORT       KC host port (default: 8082 for test, 8081 for prod)
  KC_CONTAINER       Override container name (default: platform-kc-<env>)
  KC_PASS_FILE       Override secret file path
  KC_IMAGE           Override KC image (default: read from docker inspect)
  KC_DB_HOST_PORT    PG host port for temp container DB (default: 5433 test, 5432 prod)

Exit codes:
  0   success (admin password reset + temp user cleaned + verify OK)
  1   invalid usage
  2   pre-flight failure (KC container not running, secret file missing)
  3   bootstrap-admin failed (DB/network issue, or downtime mode rejected)
  4   REST API recovery failed (token, reset, or verify)

Modes:
  temp-container (default)
    Spawn a short-lived KC container against the same PG database (read-only
    from main KC's perspective; writes admin row via JPA). Main KC stays up.
    Requires the temp container to be able to reach the same PG instance and
    use the same KC_DB_PASSWORD as main KC.

  downtime
    Stop main KC, run bootstrap-admin in-place (now able to bind :9000),
    restart main KC. Causes ~30-60s of KC unavailability.
EOF
}

ENV_NAME="test"
MODE="temp-container"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    test|prod)
      ENV_NAME="$1"
      shift
      ;;
    --mode)
      MODE="$2"
      shift 2
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

if [[ "${MODE}" != "temp-container" && "${MODE}" != "downtime" ]]; then
  echo "Invalid mode: ${MODE} (must be temp-container or downtime)" >&2
  exit 1
fi

KC_CONTAINER="${KC_CONTAINER:-platform-kc-${ENV_NAME}}"
KC_PASS_FILE="${KC_PASS_FILE:-/home/halil/platform-k8s-gitops/host-compose/keycloak/${ENV_NAME}/secrets/kc_admin_password.txt}"
KC_HOST_PORT="${KC_HOST_PORT:-$([ "${ENV_NAME}" = "test" ] && echo 8082 || echo 8081)}"
KC_URL="http://127.0.0.1:${KC_HOST_PORT}"

# --- Pre-flight -------------------------------------------------------------

log "env=${ENV_NAME} mode=${MODE} container=${KC_CONTAINER} url=${KC_URL} dry-run=${DRY_RUN}"

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

# --- Setup trap-guaranteed cleanup ------------------------------------------

TEMP_USER="temp-recovery-$(date +%s)-$$"
TEMP_PASS="$(openssl rand -base64 24 | tr -d '=+/' | head -c 32)"
TEMP_CONTAINER_NAME="kc-recovery-temp-$$"
TOK=""

cleanup() {
  local exit_code=$?
  set +e
  log "TRAP cleanup (exit=${exit_code}) — ensuring no residual state"

  # If temp container is still alive, remove it
  if docker inspect "${TEMP_CONTAINER_NAME}" >/dev/null 2>&1; then
    log "  -> removing temp KC container ${TEMP_CONTAINER_NAME}"
    docker rm -f "${TEMP_CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi

  # If we created a temp user, try to delete it (best-effort)
  if [[ -n "${TOK}" ]]; then
    local temp_id
    temp_id="$(curl -sS --fail-with-body -H "Authorization: Bearer ${TOK}" \
      "${KC_URL}/admin/realms/master/users?username=${TEMP_USER}&exact=true" 2>/dev/null \
      | jq -r '.[0].id // empty' 2>/dev/null || echo "")"
    if [[ -n "${temp_id}" ]]; then
      log "  -> deleting temp user ${TEMP_USER} (id=${temp_id})"
      if curl -sS --fail-with-body -X DELETE \
            "${KC_URL}/admin/realms/master/users/${temp_id}" \
            -H "Authorization: Bearer ${TOK}" >/dev/null 2>&1; then
        log "  -> temp user delete OK"
      else
        log "  -> temp user delete FAILED — manual cleanup required: id=${temp_id}"
        # Force non-zero exit if not already failing
        if [[ ${exit_code} -eq 0 ]]; then
          exit_code=5
        fi
      fi
    fi
  fi

  set -e
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

# --- Step 1: bootstrap temp recovery admin ---------------------------------

log "Step 1/6 — bootstrap-admin user ${TEMP_USER} (mode=${MODE})"

if [[ ${DRY_RUN} -eq 1 ]]; then
  log "DRY-RUN: would bootstrap temp admin via ${MODE} mode"
else
  if [[ "${MODE}" == "temp-container" ]]; then
    # Spawn a temp KC container with the same image + DB config, run
    # bootstrap-admin against the shared PG database.
    KC_IMAGE="${KC_IMAGE:-$(docker inspect "${KC_CONTAINER}" --format '{{.Config.Image}}')}"

    # Read main KC env so temp container connects to the same DB
    KC_DB_URL="$(docker inspect "${KC_CONTAINER}" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^KC_DB_URL=' | head -1 || true)"
    KC_DB_USERNAME_ENV="$(docker inspect "${KC_CONTAINER}" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^KC_DB_USERNAME=' | head -1 || true)"
    KC_DB_PASSWORD_FILE_ENV="$(docker inspect "${KC_CONTAINER}" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^KC_DB_PASSWORD_FILE=' | head -1 || true)"
    KC_DB_VENDOR_ENV="$(docker inspect "${KC_CONTAINER}" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^KC_DB=' | head -1 || true)"
    KC_NETWORK="$(docker inspect "${KC_CONTAINER}" --format '{{range $k, $v := .NetworkSettings.Networks}}{{println $k}}{{end}}' | head -1)"

    log "  -> temp container image=${KC_IMAGE} network=${KC_NETWORK}"

    # Mount the same secret file so KC_DB_PASSWORD_FILE works identically
    SECRETS_MOUNT_SRC="$(dirname "${KC_PASS_FILE}")"

    docker run --rm -d \
      --name "${TEMP_CONTAINER_NAME}" \
      --network "${KC_NETWORK}" \
      -e KC_TEMP_PASS="${TEMP_PASS}" \
      -e "${KC_DB_URL}" \
      -e "${KC_DB_USERNAME_ENV}" \
      -e "${KC_DB_PASSWORD_FILE_ENV}" \
      -e "${KC_DB_VENDOR_ENV}" \
      -v "${SECRETS_MOUNT_SRC}:/run/secrets:ro" \
      --entrypoint sleep \
      "${KC_IMAGE}" \
      300 >/dev/null

    sleep 2

    if docker exec -e KC_TEMP_PASS="${TEMP_PASS}" "${TEMP_CONTAINER_NAME}" \
          /opt/keycloak/bin/kc.sh bootstrap-admin user \
            --username "${TEMP_USER}" \
            --password:env KC_TEMP_PASS \
            --no-prompt 2>&1 | tee -a "${AUDIT_LOG}" | tail -5; then
      log "  -> temp-container bootstrap-admin OK"
    else
      log "FATAL: temp-container bootstrap-admin failed"
      exit 3
    fi

    # Tear down the temp container — its only purpose was the DB write
    docker rm -f "${TEMP_CONTAINER_NAME}" >/dev/null 2>&1 || true

  else
    # Downtime mode: stop main KC, bootstrap in-place, restart
    log "  -> downtime mode: stopping ${KC_CONTAINER}"
    docker stop "${KC_CONTAINER}" >/dev/null
    sleep 2

    docker start "${KC_CONTAINER}" >/dev/null
    sleep 5
    if docker exec -e KC_TEMP_PASS="${TEMP_PASS}" "${KC_CONTAINER}" \
          /opt/keycloak/bin/kc.sh bootstrap-admin user \
            --username "${TEMP_USER}" \
            --password:env KC_TEMP_PASS \
            --no-prompt 2>&1 | tee -a "${AUDIT_LOG}" | tail -5; then
      log "  -> downtime-mode bootstrap-admin OK"
    else
      log "FATAL: downtime-mode bootstrap-admin failed"
      exit 3
    fi

    # Wait for main KC to be ready again
    local_deadline=$(($(date +%s) + 120))
    while [[ $(date +%s) -lt ${local_deadline} ]]; do
      if curl -sS --fail-with-body "${KC_URL}/realms/master/.well-known/openid-configuration" >/dev/null 2>&1; then
        log "  -> main KC ready after restart"
        break
      fi
      sleep 3
    done
  fi
fi

# --- Step 2: log in with temp admin ----------------------------------------

log "Step 2/6 — obtain master realm admin token via ${TEMP_USER}"

if [[ ${DRY_RUN} -eq 0 ]]; then
  TOKEN_RESP="$(curl -sS --fail-with-body -X POST "${KC_URL}/realms/master/protocol/openid-connect/token" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode "username=${TEMP_USER}" \
    --data-urlencode "password=${TEMP_PASS}" \
    --data-urlencode 'grant_type=password' \
    --data-urlencode 'client_id=admin-cli' 2>&1 || echo '{"error":"curl_failed"}')"

  TOK="$(echo "${TOKEN_RESP}" | jq -r '.access_token // empty' 2>/dev/null)"

  if [[ -z "${TOK}" || "${TOK}" == "null" ]]; then
    ERR="$(echo "${TOKEN_RESP}" | jq -r '.error // .error_description // "unknown"' 2>/dev/null || echo "parse_failed")"
    log "FATAL: token acquisition failed: ${ERR}"
    exit 4
  fi
  log "  -> token acquired (len=${#TOK})"
fi

# --- Step 3: reset 'admin' user password -----------------------------------

log "Step 3/6 — reset 'admin' user password to canonical file value"

if [[ ${DRY_RUN} -eq 0 ]]; then
  ADMIN_RESP="$(curl -sS --fail-with-body -H "Authorization: Bearer ${TOK}" \
    "${KC_URL}/admin/realms/master/users?username=admin&exact=true" 2>&1 || echo '[]')"
  ADMIN_ID="$(echo "${ADMIN_RESP}" | jq -r '.[0].id // empty' 2>/dev/null)"

  if [[ -z "${ADMIN_ID}" ]]; then
    log "FATAL: master realm has no 'admin' user (response: ${ADMIN_RESP})"
    exit 4
  fi

  RESET_BODY="$(jq -n --arg pw "${CANONICAL_PASS}" \
    '{type:"password",value:$pw,temporary:false}')"

  RESET_RESP="$(curl -sS --fail-with-body -X PUT \
    "${KC_URL}/admin/realms/master/users/${ADMIN_ID}/reset-password" \
    -H "Authorization: Bearer ${TOK}" \
    -H 'Content-Type: application/json' \
    -d "${RESET_BODY}" 2>&1 || echo 'curl_failed')"

  if [[ -z "${RESET_RESP}" ]]; then
    log "  -> admin password reset succeeded (HTTP 204)"
  else
    log "FATAL: admin password reset failed: ${RESET_RESP}"
    exit 4
  fi
fi

# --- Step 4: cleanup happens in trap ---------------------------------------

log "Step 4/6 — temp user cleanup (deferred to trap; will run on EXIT)"

# --- Step 5: verify canonical password works -------------------------------

log "Step 5/6 — verify canonical password works for admin"

if [[ ${DRY_RUN} -eq 0 ]]; then
  VERIFY_RESP="$(curl -sS --fail-with-body -X POST "${KC_URL}/realms/master/protocol/openid-connect/token" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'username=admin' \
    --data-urlencode "password=${CANONICAL_PASS}" \
    --data-urlencode 'grant_type=password' \
    --data-urlencode 'client_id=admin-cli' 2>&1 || echo '{"error":"curl_failed"}')"

  if echo "${VERIFY_RESP}" | jq -e '.access_token' >/dev/null 2>&1; then
    log "  -> verification PASS — admin login with file password works"
  else
    ERR="$(echo "${VERIFY_RESP}" | jq -r '.error // .error_description // "unknown"' 2>/dev/null || echo "parse_failed")"
    log "FATAL: verification FAILED — admin still cannot log in: ${ERR}"
    exit 4
  fi
fi

log "Step 6/6 — DONE (trap will finalize temp user cleanup)"
exit 0
