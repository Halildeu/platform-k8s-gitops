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
readonly WRITER_USER_ID="cbc9a869-1833-4d9c-beea-a9fa52fa851e"
readonly WRITER_CLIENT="frontend"
readonly BASE_URL="https://testai.acik.com"
readonly VAULT_PERSONA_PATH="kv/platform/d35-3"
readonly VAULT_CONTAINER="platform-vault-test"
readonly VAULT_INIT_FILE="/home/halil/bootstrap-drill/vault-init-test.json"

STATUS="running"
FAILURE_REASON=""
EXACT_WRITER_MATCH=false
CANONICAL_EMAIL_READY=false
EMAIL_RECONCILIATION_ATTEMPTED=false
EMAIL_RECONCILIATION_SUCCEEDED=false
KEYCLOAK_RESET=false
VAULT_SYNCED=false
VAULT_ROLLBACK_ATTEMPTED=false
VAULT_ROLLBACK_SUCCEEDED=false
WRITER_LOGIN_READY=false
WRITER_ROLES_READ_READY=false

usage() {
  cat <<'EOF'
Usage: repair-d35-permission-writer-credential.sh [--out PATH]

Explicitly rotates the platform-test D35 permission-writer password, patches the
matching Vault record, and verifies login plus permission-service roles read access.
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

for command_name in curl jq docker openssl tr; do
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
    --argjson canonicalEmailReady "${CANONICAL_EMAIL_READY}" \
    --argjson emailReconciliationAttempted "${EMAIL_RECONCILIATION_ATTEMPTED}" \
    --argjson emailReconciliationSucceeded "${EMAIL_RECONCILIATION_SUCCEEDED}" \
    --argjson keycloakReset "${KEYCLOAK_RESET}" \
    --argjson vaultSynced "${VAULT_SYNCED}" \
    --argjson vaultRollbackAttempted "${VAULT_ROLLBACK_ATTEMPTED}" \
    --argjson vaultRollbackSucceeded "${VAULT_ROLLBACK_SUCCEEDED}" \
    --argjson writerLoginReady "${WRITER_LOGIN_READY}" \
    --argjson rolesReadReady "${WRITER_ROLES_READ_READY}" \
    '{
      schemaVersion: "faz24.permissionWriterCredentialRepair.v1",
      mode: "repair-persona",
      status: $status,
      failureReason: (if $failureReason == "" then null else $failureReason end),
      permissionWriter: {
        realm: "platform-test",
        exactIdentityMatch: $exactWriterMatch,
        canonicalEmailReady: $canonicalEmailReady,
        emailReconciliationAttempted: $emailReconciliationAttempted,
        emailReconciliationSucceeded: $emailReconciliationSucceeded,
        keycloakCredentialReset: $keycloakReset,
        vaultRecordSynced: $vaultSynced,
        vaultRollbackAttempted: $vaultRollbackAttempted,
        vaultRollbackSucceeded: $vaultRollbackSucceeded,
        loginReady: $writerLoginReady,
        rolesReadReady: $rolesReadReady
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

vault_put_data() {
  local root_token="$1"
  local cas_version="$2"
  local payload_file="$3"
  {
    printf '%s\n' "${root_token}"
    cat "${payload_file}"
  } | docker exec -i "${VAULT_CONTAINER}" sh -c '
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    vault kv put -cas="$2" "$1" - >/dev/null
  ' sh "${VAULT_PERSONA_PATH}" "${cas_version}"
}

restore_vault_snapshot() {
  local root_token="$1"
  local snapshot_file="$2"
  local expected_current_file="$3"
  local current_json="${TMP_DIR}/vault-current-before-rollback.json"
  local rollback_readback="${TMP_DIR}/vault-rollback-readback.json"
  local current_version

  VAULT_ROLLBACK_ATTEMPTED=true
  read_vault_path "${root_token}" "${current_json}" || return 1
  current_version="$(jq -r '.data.metadata.version // empty' "${current_json}")"
  [[ "${current_version}" =~ ^[0-9]+$ ]] || return 1
  jq -s -e '.[0].data.data == .[1]' "${current_json}" "${expected_current_file}" >/dev/null \
    || return 1

  vault_put_data "${root_token}" "${current_version}" "${snapshot_file}" || return 1
  read_vault_path "${root_token}" "${rollback_readback}" || return 1
  jq -s -e '.[0].data.data == .[1]' "${rollback_readback}" "${snapshot_file}" >/dev/null || return 1

  VAULT_ROLLBACK_SUCCEEDED=true
  VAULT_SYNCED=false
}

die_after_vault_write() {
  local failure_reason="$1"
  if restore_vault_snapshot "${ROOT_TOKEN}" "${VAULT_ORIGINAL_DATA}" "${VAULT_NEW_DATA}"; then
    die "${failure_reason}-vault-rolled-back"
  fi
  die "${failure_reason}-vault-rollback-failed"
}

request_writer_token() {
  local password_file="$1"
  local token_json="$2"
  local login_code
  local candidate_token

  login_code="$(http_status POST \
    "${KC_BASE_URL}/realms/${KC_REALM}/protocol/openid-connect/token" \
    "${token_json}" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'grant_type=password' \
    --data-urlencode "client_id=${WRITER_CLIENT}" \
    --data-urlencode "username@${WRITER_USERNAME_FILE}" \
    --data-urlencode "password@${password_file}")"
  [[ "${login_code}" == "200" ]] || return 1
  candidate_token="$(jq -r '.access_token // empty' "${token_json}")"
  [[ -n "${candidate_token}" ]] || return 1
  WRITER_TOKEN="${candidate_token}"
}

verify_roles_read() {
  local token="$1"
  local auth_config="$2"
  local roles_json="$3"
  local roles_code

  write_bearer_config "${auth_config}" "${token}"
  roles_code="$(http_status GET "${BASE_URL}/api/v1/roles" "${roles_json}" \
    --config "${auth_config}")"
  [[ "${roles_code}" == "200" ]] || return 1
  jq -e '.items | type == "array"' "${roles_json}" >/dev/null
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
WRITER_USER_ID_LIVE="$(jq -r '.[0].id // empty' "${KC_USERS_JSON}")"
[[ -n "${WRITER_USER_ID_LIVE}" ]] || die "permission-writer-id-missing"
[[ "${WRITER_USER_ID_LIVE}" == "${WRITER_USER_ID}" ]] \
  || die "permission-writer-id-mismatch"

if [[ "$(jq -r '.[0].email // empty | ascii_downcase' "${KC_USERS_JSON}")" != "${WRITER_EMAIL}" ]]; then
  EMAIL_RECONCILIATION_ATTEMPTED=true
  EMAIL_UPDATE_BODY="${TMP_DIR}/writer-email-update.json"
  jq --arg email "${WRITER_EMAIL}" '.[0] | .email = $email' \
    "${KC_USERS_JSON}" > "${EMAIL_UPDATE_BODY}"
  EMAIL_UPDATE_RESPONSE="${TMP_DIR}/writer-email-update-response.json"
  code="$(http_status PUT \
    "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${WRITER_USER_ID}" \
    "${EMAIL_UPDATE_RESPONSE}" \
    --config "${KC_AUTH_CONFIG}" \
    -H 'Content-Type: application/json' \
    --data-binary "@${EMAIL_UPDATE_BODY}")"
  [[ ! "${code}" =~ ^4[0-9][0-9]$ ]] \
    || die "permission-writer-email-reconcile-rejected"

  KC_USERS_READBACK_JSON="${TMP_DIR}/writer-users-readback.json"
  readback_code="$(curl -sS --max-time 20 -o "${KC_USERS_READBACK_JSON}" -w '%{http_code}' --get \
    "${KC_BASE_URL}/admin/realms/${KC_REALM}/users" \
    --config "${KC_AUTH_CONFIG}" \
    --data-urlencode "username@${WRITER_USERNAME_FILE}" \
    --data-urlencode 'exact=true' || printf '000')"
  [[ "${readback_code}" == "200" ]] \
    || die "permission-writer-email-reconcile-readback-failed"
  [[ "$(jq 'length' "${KC_USERS_READBACK_JSON}")" == "1" ]] \
    || die "permission-writer-email-reconcile-identity-drift"
  [[ "$(jq -r '.[0].id // empty' "${KC_USERS_READBACK_JSON}")" == "${WRITER_USER_ID}" &&
     "$(jq -r '.[0].username // empty' "${KC_USERS_READBACK_JSON}")" == "${WRITER_USERNAME}" &&
     "$(jq -r '.[0].enabled // false' "${KC_USERS_READBACK_JSON}")" == "true" ]] \
    || die "permission-writer-email-reconcile-identity-drift"
  if [[ "$(jq -r '.[0].email // empty | ascii_downcase' "${KC_USERS_READBACK_JSON}")" == "${WRITER_EMAIL}" ]]; then
    EMAIL_RECONCILIATION_SUCCEEDED=true
  elif [[ "${code}" == "204" ]]; then
    die "permission-writer-email-reconcile-readback-mismatch"
  else
    die "permission-writer-email-reconcile-state-unverified"
  fi
fi
CANONICAL_EMAIL_READY=true
EXACT_WRITER_MATCH=true

docker inspect "${VAULT_CONTAINER}" >/dev/null 2>&1 || die "vault-container-missing"
ROOT_TOKEN="$(vault_root_token)" || die "vault-root-token-missing"

VAULT_ORIGINAL_JSON="${TMP_DIR}/vault-original.json"
VAULT_ORIGINAL_DATA="${TMP_DIR}/vault-original-data.json"
read_vault_path "${ROOT_TOKEN}" "${VAULT_ORIGINAL_JSON}" || die "vault-persona-preflight-read-failed"
VAULT_ORIGINAL_VERSION="$(jq -r '.data.metadata.version // empty' "${VAULT_ORIGINAL_JSON}")"
[[ "${VAULT_ORIGINAL_VERSION}" =~ ^[0-9]+$ ]] || die "vault-persona-version-missing"
jq -e '.data.data | type == "object"' "${VAULT_ORIGINAL_JSON}" >/dev/null \
  || die "vault-persona-data-invalid"
jq '.data.data' "${VAULT_ORIGINAL_JSON}" > "${VAULT_ORIGINAL_DATA}"

EXISTING_WRITER_USERNAME="$(jq -r '.admin_persona_username // empty' "${VAULT_ORIGINAL_DATA}")"
EXISTING_PASSWORD_FILE="${TMP_DIR}/existing-writer-password"
jq -j '.admin_persona_password // empty' "${VAULT_ORIGINAL_DATA}" > "${EXISTING_PASSWORD_FILE}"
chmod 600 "${EXISTING_PASSWORD_FILE}"
if [[ "${EXISTING_WRITER_USERNAME}" == "${WRITER_USERNAME}" && -s "${EXISTING_PASSWORD_FILE}" ]]; then
  EXISTING_TOKEN_JSON="${TMP_DIR}/existing-writer-token.json"
  if request_writer_token "${EXISTING_PASSWORD_FILE}" "${EXISTING_TOKEN_JSON}"; then
    VAULT_SYNCED=true
    WRITER_LOGIN_READY=true
    EXISTING_AUTH_CONFIG="${TMP_DIR}/existing-writer-auth.curl"
    EXISTING_ROLES_JSON="${TMP_DIR}/existing-roles.json"
    verify_roles_read "${WRITER_TOKEN}" "${EXISTING_AUTH_CONFIG}" "${EXISTING_ROLES_JSON}" \
      || die "permission-writer-roles-readback-failed"
    WRITER_ROLES_READ_READY=true
    STATUS="already-ready"
    write_result
    exit 0
  fi
fi

NEW_PASSWORD_FILE="${TMP_DIR}/writer-password"
openssl rand -hex 32 | tr -d '\n' > "${NEW_PASSWORD_FILE}"
chmod 600 "${NEW_PASSWORD_FILE}"

VAULT_NEW_DATA="${TMP_DIR}/vault-new-data.json"
jq \
  --arg username "${WRITER_USERNAME}" \
  --rawfile password "${NEW_PASSWORD_FILE}" \
  '. + {
    admin_persona_username: $username,
    admin_persona_password: ($password | rtrimstr("\n"))
  }' "${VAULT_ORIGINAL_DATA}" > "${VAULT_NEW_DATA}"
vault_put_data "${ROOT_TOKEN}" "${VAULT_ORIGINAL_VERSION}" "${VAULT_NEW_DATA}" \
  || die "vault-persona-cas-write-failed"

VAULT_READBACK_JSON="${TMP_DIR}/vault-readback.json"
read_vault_path "${ROOT_TOKEN}" "${VAULT_READBACK_JSON}" \
  || die_after_vault_write "vault-persona-readback-failed"
jq -e --arg username "${WRITER_USERNAME}" --rawfile password "${NEW_PASSWORD_FILE}" '
  .data.data.admin_persona_username == $username and
  .data.data.admin_persona_password == ($password | rtrimstr("\n"))
' "${VAULT_READBACK_JSON}" >/dev/null \
  || die_after_vault_write "vault-persona-readback-mismatch"
VAULT_SYNCED=true

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
if [[ "${code}" == "204" ]]; then
  KEYCLOAK_RESET=true
elif [[ "${code}" =~ ^4[0-9][0-9]$ ]]; then
  die_after_vault_write "permission-writer-password-reset-rejected"
else
  AMBIGUOUS_NEW_TOKEN_JSON="${TMP_DIR}/ambiguous-new-token.json"
  if request_writer_token "${NEW_PASSWORD_FILE}" "${AMBIGUOUS_NEW_TOKEN_JSON}"; then
    KEYCLOAK_RESET=true
  else
    unset WRITER_TOKEN
    AMBIGUOUS_OLD_TOKEN_JSON="${TMP_DIR}/ambiguous-old-token.json"
    if [[ -s "${EXISTING_PASSWORD_FILE}" ]] && \
       request_writer_token "${EXISTING_PASSWORD_FILE}" "${AMBIGUOUS_OLD_TOKEN_JSON}"; then
      unset WRITER_TOKEN
      die_after_vault_write "permission-writer-password-reset-not-applied"
    fi
    die "permission-writer-password-reset-state-unverified"
  fi
fi

WRITER_TOKEN_JSON="${TMP_DIR}/writer-token.json"
request_writer_token "${NEW_PASSWORD_FILE}" "${WRITER_TOKEN_JSON}" \
  || die "permission-writer-login-readback-failed"
WRITER_LOGIN_READY=true

WRITER_AUTH_CONFIG="${TMP_DIR}/writer-auth.curl"
ROLES_JSON="${TMP_DIR}/roles.json"
verify_roles_read "${WRITER_TOKEN}" "${WRITER_AUTH_CONFIG}" "${ROLES_JSON}" \
  || die "permission-writer-roles-readback-failed"
WRITER_ROLES_READ_READY=true

STATUS="repaired"
write_result
