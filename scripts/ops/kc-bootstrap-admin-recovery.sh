#!/usr/bin/env bash
# scripts/ops/kc-bootstrap-admin-recovery.sh
#
# PR-S1 (PERF-INIT-V2): Keycloak master-admin password drift recovery.
#
# Recovery pattern (KC 26.5.x — running-mode bootstrap-admin NOT supported
# because :9000 management port collides):
#   1. Spawn temp KC container against the same PG database, but with
#      :9000 NOT published to host (so no port conflict with main KC).
#   2. Inside temp container, `sh -lc` literal export KC_DB_PASSWORD from
#      mounted secret file (wrapper entrypoint does not run when we use
#      `--entrypoint sleep`), then run `kc.sh bootstrap-admin user`.
#   3. Temp container has now written the temp recovery admin row into
#      the shared PG; main KC sees it immediately on next request.
#   4. Tear down temp container.
#   5. Log in as temp admin via main KC's Admin REST API.
#   6. Reset `admin` user password to canonical file value.
#   7. Delete temp recovery admin (trap-guaranteed cleanup).
#   8. Verify canonical password works.
#
# Repo evidence:
#   - docs/session-logs/s07-green-yellow-completion.md — running KC
#     bootstrap-admin fails with port 9000 Address already in use
#   - docs/session-logs/s08-kc-vault-eso-debug.md — temp container with
#     literal KC_DB_PASSWORD + KC_DB_URL_HOST was the working pattern
#
# Compose env (host-compose/keycloak/<env>/docker-compose.yml) uses
# split KC_DB_URL_HOST/PORT/DATABASE (NOT a single KC_DB_URL); the
# wrapper entrypoint exports KC_DB_PASSWORD from the secret file. The
# temp container we spawn does not run that wrapper (we use `sleep` as
# entrypoint), so we explicitly export KC_DB_PASSWORD inside the bootstrap
# invocation.
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
Usage: ${SCRIPT_NAME} [test|prod] [--dry-run]

Arguments:
  env                test (default) or prod

Options:
  --dry-run          Print actions but do not mutate

Environment:
  KC_HOST_PORT       KC host port (default: 8082 for test, 8081 for prod)
  KC_CONTAINER       Override container name (default: platform-kc-<env>)
  KC_PASS_FILE       Override admin secret file path
  KC_IMAGE           Override KC image (default: read from docker inspect)

Exit codes:
  0   success
  1   invalid usage
  2   pre-flight failure (KC container not running, secret file missing,
      cannot read required DB env from main KC)
  3   temp-container bootstrap-admin failed
  4   REST API recovery failed
  5   trap cleanup encountered orphan resources
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
KC_PASS_FILE="${KC_PASS_FILE:-/srv/platform/gitops/platform-k8s-gitops/host-compose/keycloak/${ENV_NAME}/secrets/kc_admin_password.txt}"
KC_HOST_PORT="${KC_HOST_PORT:-$([ "${ENV_NAME}" = "test" ] && echo 8082 || echo 8081)}"
KC_URL="http://127.0.0.1:${KC_HOST_PORT}"

# --- Pre-flight -------------------------------------------------------------

log "env=${ENV_NAME} container=${KC_CONTAINER} url=${KC_URL} dry-run=${DRY_RUN}"

if ! docker inspect "${KC_CONTAINER}" >/dev/null 2>&1; then
  log "FATAL: container ${KC_CONTAINER} not found"
  exit 2
fi

if [[ ! -r "${KC_PASS_FILE}" ]]; then
  log "FATAL: admin secret file ${KC_PASS_FILE} not readable"
  exit 2
fi

CANONICAL_PASS="$(sudo cat "${KC_PASS_FILE}" 2>/dev/null || cat "${KC_PASS_FILE}")"
if [[ -z "${CANONICAL_PASS}" ]]; then
  log "FATAL: admin secret file is empty"
  exit 2
fi
log "  -> admin password file readable (len=${#CANONICAL_PASS})"

# Extract DB env from main KC (we MUST reuse these exactly)
extract_env() {
  local key="$1"
  docker inspect "${KC_CONTAINER}" --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | awk -F= -v k="${key}" '$1==k{for(i=2;i<=NF;i++) printf "%s%s", (i==2?"":"="), $i}'
}

KC_DB_VENDOR="$(extract_env KC_DB)"
KC_DB_URL_HOST="$(extract_env KC_DB_URL_HOST)"
KC_DB_URL_PORT="$(extract_env KC_DB_URL_PORT)"
KC_DB_URL_DATABASE="$(extract_env KC_DB_URL_DATABASE)"
KC_DB_USERNAME_VAL="$(extract_env KC_DB_USERNAME)"
KC_DB_PASSWORD_FILE_VAL="$(extract_env KC_DB_PASSWORD_FILE)"

for var in KC_DB_VENDOR KC_DB_URL_HOST KC_DB_URL_PORT KC_DB_URL_DATABASE \
           KC_DB_USERNAME_VAL KC_DB_PASSWORD_FILE_VAL; do
  if [[ -z "${!var}" ]]; then
    log "FATAL: required main KC env '${var}' is empty (cannot replicate DB config)"
    log "       Compose file: host-compose/keycloak/${ENV_NAME}/docker-compose.yml"
    exit 2
  fi
done
log "  -> DB env: vendor=${KC_DB_VENDOR} host=${KC_DB_URL_HOST}:${KC_DB_URL_PORT}/${KC_DB_URL_DATABASE} user=${KC_DB_USERNAME_VAL}"

KC_IMAGE="${KC_IMAGE:-$(docker inspect "${KC_CONTAINER}" --format '{{.Config.Image}}')}"
KC_NETWORK="$(docker inspect "${KC_CONTAINER}" --format '{{range $k, $v := .NetworkSettings.Networks}}{{println $k}}{{end}}' | head -1)"
SECRETS_MOUNT_SRC="$(dirname "${KC_PASS_FILE}")"

# Compose `secrets:` directive maps host file `./secrets/kc_db_password.txt`
# to in-container path `/run/secrets/kc_db_password` (NO `.txt` suffix —
# secret name in compose is `kc_db_password`). Our temp container does NOT
# use compose; we must explicitly bind-mount the host file to the exact
# in-container target path so `cat $KC_DB_PASSWORD_FILE` (= /run/secrets/
# kc_db_password) finds it.
KC_DB_PASSWORD_HOST_FILE="${SECRETS_MOUNT_SRC}/kc_db_password.txt"
if [[ ! -r "${KC_DB_PASSWORD_HOST_FILE}" ]]; then
  log "FATAL: KC DB password host file not readable: ${KC_DB_PASSWORD_HOST_FILE}"
  log "       Compose maps this file to ${KC_DB_PASSWORD_FILE_VAL} inside the container."
  exit 2
fi

log "  -> image=${KC_IMAGE} network=${KC_NETWORK}"
log "  -> secrets host file: ${KC_DB_PASSWORD_HOST_FILE}"
log "  -> secrets target path: ${KC_DB_PASSWORD_FILE_VAL}"

# --- Setup trap-guaranteed cleanup ------------------------------------------

TEMP_USER="temp-recovery-$(date +%s)-$$"
TEMP_PASS="$(openssl rand -base64 24 | tr -d '=+/' | head -c 32)"
TEMP_CONTAINER_NAME="kc-recovery-temp-$$"
TOK=""
ORPHAN_TEMP_USER=0

cleanup() {
  local exit_code=$?
  set +e
  log "TRAP cleanup (exit=${exit_code}) — ensuring no residual state"

  # If temp container is still alive, remove it
  if docker inspect "${TEMP_CONTAINER_NAME}" >/dev/null 2>&1; then
    log "  -> removing temp KC container ${TEMP_CONTAINER_NAME}"
    docker rm -f "${TEMP_CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi

  # If we have a valid token, delete the temp user
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
        ORPHAN_TEMP_USER=1
      fi
    fi
  fi

  # If we created temp_user but never got a token (bootstrap succeeded
  # but token step failed), the temp user is orphan AND we cannot delete
  # it via REST. Surface this explicitly.
  if [[ -z "${TOK}" && ${exit_code} -ne 0 ]]; then
    log "WARN: bootstrap may have succeeded but token step failed"
    log "      Manual cleanup: log in to KC master realm as 'admin' and"
    log "      delete user '${TEMP_USER}' if present."
    ORPHAN_TEMP_USER=1
  fi

  # If orphan detected and original exit was success, force non-zero
  if [[ ${ORPHAN_TEMP_USER} -eq 1 && ${exit_code} -eq 0 ]]; then
    log "FATAL: orphan temp recovery user; manual cleanup required"
    exit_code=5
  fi

  set -e
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

# --- Step 1: spawn temp container + bootstrap-admin user --------------------

log "Step 1/5 — spawn temp KC container + bootstrap-admin user ${TEMP_USER}"

if [[ ${DRY_RUN} -eq 1 ]]; then
  log "DRY-RUN: would spawn temp container ${TEMP_CONTAINER_NAME} and bootstrap admin"
else
  # Spawn temp container with split DB env vars (matching main compose),
  # explicit file-to-file secret mount (compose-secret semantic preserved),
  # and sleep as entrypoint so :9000 is NOT bound.
  if ! docker run --rm -d \
        --name "${TEMP_CONTAINER_NAME}" \
        --network "${KC_NETWORK}" \
        -e KC_DB="${KC_DB_VENDOR}" \
        -e KC_DB_URL_HOST="${KC_DB_URL_HOST}" \
        -e KC_DB_URL_PORT="${KC_DB_URL_PORT}" \
        -e KC_DB_URL_DATABASE="${KC_DB_URL_DATABASE}" \
        -e KC_DB_USERNAME="${KC_DB_USERNAME_VAL}" \
        -e KC_DB_PASSWORD_FILE="${KC_DB_PASSWORD_FILE_VAL}" \
        -e KC_TEMP_PASS="${TEMP_PASS}" \
        -v "${KC_DB_PASSWORD_HOST_FILE}:${KC_DB_PASSWORD_FILE_VAL}:ro" \
        --entrypoint sleep \
        "${KC_IMAGE}" \
        300 >/dev/null; then
    log "FATAL: failed to spawn temp KC container"
    exit 3
  fi
  sleep 2

  # Run bootstrap-admin inside the temp container, with KC_DB_PASSWORD
  # explicitly exported from the mounted secret file (wrapper entrypoint
  # does NOT run because we used `--entrypoint sleep`).
  BOOTSTRAP_CMD='export KC_DB_PASSWORD="$(cat ${KC_DB_PASSWORD_FILE})" && \
    /opt/keycloak/bin/kc.sh bootstrap-admin user \
      --username "${TEMP_USER_INNER}" \
      --password:env KC_TEMP_PASS \
      --no-prompt'

  if docker exec \
        -e TEMP_USER_INNER="${TEMP_USER}" \
        "${TEMP_CONTAINER_NAME}" \
        sh -lc "${BOOTSTRAP_CMD}" 2>&1 | tee -a "${AUDIT_LOG}" | tail -10; then
    log "  -> temp-container bootstrap-admin OK"
  else
    log "FATAL: bootstrap-admin failed (see audit log for KC error detail)"
    exit 3
  fi

  # Tear down temp container — its only purpose was the DB write
  docker rm -f "${TEMP_CONTAINER_NAME}" >/dev/null 2>&1 || true
fi

# --- Step 2: log in with temp admin via main KC -----------------------------

log "Step 2/5 — obtain master realm admin token via ${TEMP_USER}"

if [[ ${DRY_RUN} -eq 0 ]]; then
  TOKEN_RESP="$(curl -sS --fail-with-body -X POST \
    "${KC_URL}/realms/master/protocol/openid-connect/token" \
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

log "Step 3/5 — reset 'admin' user password to canonical file value"

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

  if curl -sS --fail-with-body -X PUT \
        "${KC_URL}/admin/realms/master/users/${ADMIN_ID}/reset-password" \
        -H "Authorization: Bearer ${TOK}" \
        -H 'Content-Type: application/json' \
        -d "${RESET_BODY}" >/dev/null 2>&1; then
    log "  -> admin password reset succeeded (HTTP 204)"
  else
    log "FATAL: admin password reset failed"
    exit 4
  fi
fi

# --- Step 4: temp user cleanup happens in trap -----------------------------

log "Step 4/5 — temp user cleanup deferred to trap (will run on EXIT)"

# --- Step 5: verify canonical password works -------------------------------

log "Step 5/5 — verify canonical password works for admin"

if [[ ${DRY_RUN} -eq 0 ]]; then
  VERIFY_RESP="$(curl -sS --fail-with-body -X POST \
    "${KC_URL}/realms/master/protocol/openid-connect/token" \
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

log "DONE — Keycloak ${ENV_NAME} master-admin recovery completed"
# Trap cleanup will run on exit and verify temp user was deleted
exit 0
