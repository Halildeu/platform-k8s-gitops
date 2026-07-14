#!/usr/bin/env bash
# Repair the stale test-only D35 permission-writer credential without exposing it.

set -Eeuo pipefail
umask 077

OUT_PATH="${OUT_PATH:-/tmp/faz24-permission-writer-repair.json}"
readonly KC_BASE_URL="http://127.0.0.1:8082"
readonly KC_REALM="platform-test"
readonly KC_ADMIN_USER="admin"
readonly WRITER_USERNAME="d35-admin-persona"
readonly WRITER_EMAIL="d35-admin@example.com"
readonly WRITER_CLIENT="frontend"
readonly BASE_URL="https://testai.acik.com"
readonly VAULT_PERSONA_PATH="kv/platform/d35-3"
readonly VAULT_CONTAINER="platform-vault-test"
readonly VAULT_INIT_FILE="/home/halil/bootstrap-drill/vault-init-test.json"

STATUS="running"
FAILURE_REASON=""
EXACT_WRITER_MATCH=false
KEYCLOAK_RESET=false
VAULT_SYNCED=false
WRITER_LOGIN_READY=false
WRITER_AUTHORIZED=false
VAULT_CONTAINER_PATCH_FILE=""

usage() {
  cat <<'EOF'
Usage: repair-d35-permission-writer-credential.sh [--out PATH]

Explicitly rotates the platform-test D35 permission-writer password, patches the
matching Vault record, and verifies login plus permission-service writer access.
No production object or target-user authorization is modified.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT_PATH="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for command_name in curl jq docker openssl; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command missing: ${command_name}" >&2
    exit 2
  }
done

TMP_DIR="$(mktemp -d /tmp/faz24-writer-repair.XXXXXX)"
mkdir -p "$(dirname "${OUT_PATH}")"

write_result() {
  jq -n \
    --arg status "${STATUS}" \
    --arg failureReason "${FAILURE_REASON}" \
    --argjson exactWriterMatch "${EXACT_WRITER_MATCH}" \
    --argjson keycloakReset "${KEYCLOAK_RESET}" \
    --argjson vaultSynced "${VAULT_SYNCED}" \
    --argjson writerLoginReady "${WRITER_LOGIN_READY}" \
    --argjson writerAuthorized "${WRITER_AUTHORIZED}" \
    '{
      schemaVersion: "faz24.permissionWriterCredentialRepair.v1",
      mode: "repair-persona",
      status: $status,
      failureReason: (if $failureReason == "" then null else $failureReason end),
      permissionWriter: {
        realm: "platform-test",
        exactIdentityMatch: $exactWriterMatch,
        keycloakCredentialReset: $keycloakReset,
        vaultRecordSynced: $vaultSynced,
        loginReady: $writerLoginReady,
        permissionServiceWriterReady: $writerAuthorized
      },
      boundaries: {
        productionMutation: false,
        targetUserMutation: false,
        rawIdentityIncluded: false,
        rawCredentialIncluded: false,
        rawTokenIncluded: false
      }
    }' > "${OUT_PATH}"
}

cleanup() {
  if [[ -n "${VAULT_CONTAINER_PATCH_FILE}" ]]; then
    docker exec "${VAULT_CONTAINER}" rm -f "${VAULT_CONTAINER_PATCH_FILE}" >/dev/null 2>&1 || true
  fi
  rm -rf "${TMP_DIR}"
  unset KC_ADMIN_PASSWORD KC_ADMIN_TOKEN WRITER_TOKEN
}
trap cleanup EXIT

die() {
  FAILURE_REASON="$1"
  STATUS="blocked"
  write_result
  echo "ERROR: ${FAILURE_REASON}" >&2
  exit 1
}

http_status() {
  local method="$1"
  local url="$2"
  local output="$3"
  shift 3
  curl -sS --max-time 20 -o "${output}" -w '%{http_code}' -X "${method}" "${url}" "$@" || printf '000'
}

write_bearer_config() {
  local output="$1"
  local token="$2"
  printf 'header = "Authorization: Bearer %s"\n' "${token}" > "${output}"
  chmod 600 "${output}"
}

vault_root_token() {
  local token
  token="$(jq -r '.root_token // empty' "${VAULT_INIT_FILE}" 2>/dev/null || true)"
  [[ -n "${token}" ]] || return 1
  printf '%s' "${token}"
}

read_vault_path() {
  local root_token="$1"
  local output="$2"
  printf '%s\n' "${root_token}" | docker exec -i "${VAULT_CONTAINER}" sh -c '
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    vault kv get -format=json "$1"
  ' sh "${VAULT_PERSONA_PATH}" > "${output}" 2>/dev/null
}

[[ -n "${KC_ADMIN_PASSWORD:-}" ]] || die "keycloak-admin-password-missing"

KC_ADMIN_PASSWORD_FILE="${TMP_DIR}/keycloak-admin-password"
printf '%s' "${KC_ADMIN_PASSWORD}" > "${KC_ADMIN_PASSWORD_FILE}"

KC_ADMIN_TOKEN_JSON="${TMP_DIR}/kc-admin-token.json"
code="$(http_status POST \
  "${KC_BASE_URL}/realms/master/protocol/openid-connect/token" \
  "${KC_ADMIN_TOKEN_JSON}" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=password' \
  --data-urlencode 'client_id=admin-cli' \
  --data-urlencode "username=${KC_ADMIN_USER}" \
  --data-urlencode "password@${KC_ADMIN_PASSWORD_FILE}")"
[[ "${code}" == "200" ]] || die "keycloak-admin-login-failed"
KC_ADMIN_TOKEN="$(jq -r '.access_token // empty' "${KC_ADMIN_TOKEN_JSON}")"
[[ -n "${KC_ADMIN_TOKEN}" ]] || die "keycloak-admin-token-missing"
KC_AUTH_CONFIG="${TMP_DIR}/keycloak-auth.curl"
write_bearer_config "${KC_AUTH_CONFIG}" "${KC_ADMIN_TOKEN}"

WRITER_USERNAME_FILE="${TMP_DIR}/writer-username"
printf '%s' "${WRITER_USERNAME}" > "${WRITER_USERNAME_FILE}"
KC_USERS_JSON="${TMP_DIR}/writer-users.json"
code="$(curl -sS --max-time 20 -o "${KC_USERS_JSON}" -w '%{http_code}' --get \
  "${KC_BASE_URL}/admin/realms/${KC_REALM}/users" \
  --config "${KC_AUTH_CONFIG}" \
  --data-urlencode "username@${WRITER_USERNAME_FILE}" \
  --data-urlencode 'exact=true' || printf '000')"
[[ "${code}" == "200" ]] || die "permission-writer-lookup-failed"
[[ "$(jq 'length' "${KC_USERS_JSON}")" == "1" ]] || die "permission-writer-not-exactly-one"
[[ "$(jq -r '.[0].enabled // false' "${KC_USERS_JSON}")" == "true" ]] \
  || die "permission-writer-disabled"
[[ "$(jq -r '.[0].username // empty' "${KC_USERS_JSON}")" == "${WRITER_USERNAME}" ]] \
  || die "permission-writer-username-mismatch"
[[ "$(jq -r '.[0].email // empty | ascii_downcase' "${KC_USERS_JSON}")" == "${WRITER_EMAIL}" ]] \
  || die "permission-writer-email-mismatch"
WRITER_USER_ID="$(jq -r '.[0].id // empty' "${KC_USERS_JSON}")"
[[ -n "${WRITER_USER_ID}" ]] || die "permission-writer-id-missing"
EXACT_WRITER_MATCH=true

docker inspect "${VAULT_CONTAINER}" >/dev/null 2>&1 || die "vault-container-missing"
ROOT_TOKEN="$(vault_root_token)" || die "vault-root-token-missing"

NEW_PASSWORD_FILE="${TMP_DIR}/writer-password"
openssl rand -hex 32 > "${NEW_PASSWORD_FILE}"
chmod 600 "${NEW_PASSWORD_FILE}"

RESET_BODY="${TMP_DIR}/reset-password.json"
jq -n --rawfile value "${NEW_PASSWORD_FILE}" \
  '{type: "password", temporary: false, value: ($value | rtrimstr("\n"))}' > "${RESET_BODY}"
RESET_RESPONSE="${TMP_DIR}/reset-response.json"
code="$(http_status PUT \
  "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${WRITER_USER_ID}/reset-password" \
  "${RESET_RESPONSE}" \
  --config "${KC_AUTH_CONFIG}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${RESET_BODY}")"
[[ "${code}" == "204" ]] || die "permission-writer-password-reset-failed"
KEYCLOAK_RESET=true

VAULT_PATCH_BODY="${TMP_DIR}/vault-patch.json"
jq -n \
  --arg username "${WRITER_USERNAME}" \
  --rawfile password "${NEW_PASSWORD_FILE}" \
  '{admin_persona_username: $username, admin_persona_password: ($password | rtrimstr("\n"))}' \
  > "${VAULT_PATCH_BODY}"
VAULT_CONTAINER_PATCH_FILE="/tmp/faz24-writer-repair-${RANDOM}-${RANDOM}.json"
docker cp "${VAULT_PATCH_BODY}" "${VAULT_CONTAINER}:${VAULT_CONTAINER_PATCH_FILE}" >/dev/null \
  || die "vault-patch-file-copy-failed"
docker exec "${VAULT_CONTAINER}" chmod 600 "${VAULT_CONTAINER_PATCH_FILE}" >/dev/null \
  || die "vault-patch-file-permission-failed"
printf '%s\n' "${ROOT_TOKEN}" | docker exec -i "${VAULT_CONTAINER}" sh -c '
  IFS= read -r VAULT_TOKEN
  export VAULT_TOKEN
  vault kv patch "$1" "@$2" >/dev/null
' sh "${VAULT_PERSONA_PATH}" "${VAULT_CONTAINER_PATCH_FILE}" \
  || die "vault-persona-patch-failed"

VAULT_READBACK_JSON="${TMP_DIR}/vault-readback.json"
read_vault_path "${ROOT_TOKEN}" "${VAULT_READBACK_JSON}" || die "vault-persona-readback-failed"
jq -e --arg username "${WRITER_USERNAME}" '
  .data.data.admin_persona_username == $username and
  ((.data.data.admin_persona_password // "") | length >= 32)
' "${VAULT_READBACK_JSON}" >/dev/null || die "vault-persona-readback-mismatch"
VAULT_SYNCED=true

WRITER_TOKEN_JSON="${TMP_DIR}/writer-token.json"
code="$(http_status POST \
  "${KC_BASE_URL}/realms/${KC_REALM}/protocol/openid-connect/token" \
  "${WRITER_TOKEN_JSON}" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=password' \
  --data-urlencode "client_id=${WRITER_CLIENT}" \
  --data-urlencode "username@${WRITER_USERNAME_FILE}" \
  --data-urlencode "password@${NEW_PASSWORD_FILE}")"
[[ "${code}" == "200" ]] || die "permission-writer-login-readback-failed"
WRITER_TOKEN="$(jq -r '.access_token // empty' "${WRITER_TOKEN_JSON}")"
[[ -n "${WRITER_TOKEN}" ]] || die "permission-writer-token-readback-missing"
WRITER_LOGIN_READY=true

WRITER_AUTH_CONFIG="${TMP_DIR}/writer-auth.curl"
write_bearer_config "${WRITER_AUTH_CONFIG}" "${WRITER_TOKEN}"
ROLES_JSON="${TMP_DIR}/roles.json"
code="$(http_status GET "${BASE_URL}/api/v1/roles" "${ROLES_JSON}" \
  --config "${WRITER_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "permission-writer-authorization-readback-failed"
WRITER_AUTHORIZED=true

STATUS="repaired"
write_result
