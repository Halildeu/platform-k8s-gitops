#!/usr/bin/env bash
# Repair the stale test-only D35 permission-writer credential without exposing it.

set -Eeuo pipefail
set +x
umask 077

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/faz35/lib-test-keycloak-binding.sh
source "${SCRIPT_DIR}/../faz35/lib-test-keycloak-binding.sh"

OUT_PATH="${OUT_PATH:-/tmp/faz24-permission-writer-repair.json}"
readonly KC_CONTAINER="platform-kc-test"
readonly KC_BASE_URL="http://127.0.0.1:8082"
readonly KC_REALM="platform-test"
readonly KC_EXPECTED_ISSUER="https://testai.acik.com/realms/platform-test"
readonly KC_ADMIN_USER="admin"
readonly WRITER_USERNAME="d35-admin-persona"
readonly WRITER_USER_ID="cbc9a869-1833-4d9c-beea-a9fa52fa851e"
readonly WRITER_LOCAL_USER_ID="12"
readonly WRITER_LEGACY_LOCAL_USER_ID="1204"
# Faz 35 gives this synthetic permission writer its own active local profile;
# it must never borrow the historical user 1204 / performance persona email.
readonly WRITER_PROFILE_EMAIL="d35-admin-persona@acik.com"
readonly WRITER_PROFILE_FIRST_NAME="D35"
readonly WRITER_PROFILE_LAST_NAME="Admin Persona"
readonly WRITER_CLIENT="frontend"
readonly BASE_URL="https://testai.acik.com"
readonly VAULT_PERSONA_PATH="kv/platform/d35-3"
readonly VAULT_CONTAINER="platform-vault-test"
readonly VAULT_INIT_FILE="/home/halil/bootstrap-drill/vault-init-test.json"

STATUS="running"
KC_ADMIN_PASSWORD_STDIN=false
PRE_IDENTITY_CREDENTIAL_ONLY=false
FAILURE_REASON=""
EXACT_WRITER_MATCH=false
KEYCLOAK_RESET=false
VAULT_SYNCED=false
VAULT_ROLLBACK_ATTEMPTED=false
VAULT_ROLLBACK_SUCCEEDED=false
WRITER_LOGIN_READY=false
WRITER_ROLES_READ_READY=false
WRITER_REQUIRED_ACTIONS_READY=false
WRITER_PROFILE_READY=false
WRITER_PROFILE_REPAIRED=false
WRITER_PROFILE_EMAIL_COLLISION_FREE=false
WRITER_PROFILE_ATTRIBUTES_PRESERVED=false
WRITER_PROFILE_REQUIRED_ACTIONS_PRESERVED=false
WRITER_PROFILE_EMAIL_MUTATION_ATTEMPTED=false
WRITER_PROFILE_EMAIL_MUTATION_CONFIRMED=false

usage() {
  cat <<'EOF'
Usage: repair-d35-permission-writer-credential.sh [--out PATH]
       [--keycloak-admin-password-stdin] [--pre-identity-credential-only]

Repairs missing platform-test D35 permission-writer service-profile fields,
rotates its password, patches the matching Vault record, and verifies login plus
permission-service roles read access. No production object or target-user
authorization is modified.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT_PATH="$2"; shift 2 ;;
    --keycloak-admin-password-stdin) KC_ADMIN_PASSWORD_STDIN=true; shift ;;
    --pre-identity-credential-only) PRE_IDENTITY_CREDENTIAL_ONLY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for command_name in cmp curl jq docker openssl tr; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command missing: ${command_name}" >&2
    exit 2
  }
done

faz35_assert_test_keycloak_binding \
  "${KC_CONTAINER}" "${KC_BASE_URL}" "${KC_REALM}" "${KC_EXPECTED_ISSUER}" || {
  echo "ERROR: TEST Keycloak container/loopback/issuer binding is invalid" >&2
  exit 2
}

if [[ "${KC_ADMIN_PASSWORD_STDIN}" == "true" ]]; then
  [[ -z "${KC_ADMIN_PASSWORD:-}" ]] || {
    echo "ERROR: Keycloak admin password sources are ambiguous" >&2
    exit 2
  }
  KC_ADMIN_PASSWORD=""
  IFS= read -r KC_ADMIN_PASSWORD || [[ -n "${KC_ADMIN_PASSWORD}" ]] || {
    echo "ERROR: Keycloak admin password stdin is empty" >&2
    exit 2
  }
fi

TMP_DIR="$(mktemp -d /tmp/faz24-writer-repair.XXXXXX)"
mkdir -p "$(dirname "${OUT_PATH}")"

write_result() {
  jq -n \
    --arg status "${STATUS}" \
    --arg failureReason "${FAILURE_REASON}" \
    --argjson exactWriterMatch "${EXACT_WRITER_MATCH}" \
    --argjson keycloakReset "${KEYCLOAK_RESET}" \
    --argjson vaultSynced "${VAULT_SYNCED}" \
    --argjson vaultRollbackAttempted "${VAULT_ROLLBACK_ATTEMPTED}" \
    --argjson vaultRollbackSucceeded "${VAULT_ROLLBACK_SUCCEEDED}" \
    --argjson writerLoginReady "${WRITER_LOGIN_READY}" \
    --argjson rolesReadReady "${WRITER_ROLES_READ_READY}" \
    --argjson requiredActionsReady "${WRITER_REQUIRED_ACTIONS_READY}" \
    --argjson profileReady "${WRITER_PROFILE_READY}" \
    --argjson profileRepaired "${WRITER_PROFILE_REPAIRED}" \
    --argjson profileEmailCollisionFree "${WRITER_PROFILE_EMAIL_COLLISION_FREE}" \
    --argjson profileAttributesPreserved "${WRITER_PROFILE_ATTRIBUTES_PRESERVED}" \
    --argjson profileRequiredActionsPreserved "${WRITER_PROFILE_REQUIRED_ACTIONS_PRESERVED}" \
    --argjson permissionWriterEmailMutationAttempted "${WRITER_PROFILE_EMAIL_MUTATION_ATTEMPTED}" \
    --argjson permissionWriterEmailMutationConfirmed "${WRITER_PROFILE_EMAIL_MUTATION_CONFIRMED}" \
    '{
      schemaVersion: "faz24.permissionWriterCredentialRepair.v3",
      mode: "repair-persona",
      status: $status,
      failureReason: (if $failureReason == "" then null else $failureReason end),
      permissionWriter: {
        realm: "platform-test",
        exactIdentityMatch: $exactWriterMatch,
        identityBinding: "username+immutable-user-id",
        keycloakCredentialReset: $keycloakReset,
        vaultRecordSynced: $vaultSynced,
        vaultRollbackAttempted: $vaultRollbackAttempted,
        vaultRollbackSucceeded: $vaultRollbackSucceeded,
        requiredActionsReady: $requiredActionsReady,
        profileReady: $profileReady,
        profileRepaired: $profileRepaired,
        profileEmailCollisionFree: $profileEmailCollisionFree,
        existingAttributesPreserved: $profileAttributesPreserved,
        requiredActionsPreserved: $profileRequiredActionsPreserved,
        loginReady: $writerLoginReady,
        rolesReadReady: $rolesReadReady
      },
      boundaries: {
        productionMutation: false,
        targetUserMutation: false,
        permissionWriterEmailMutation: $permissionWriterEmailMutationAttempted,
        permissionWriterEmailMutationAttempted: $permissionWriterEmailMutationAttempted,
        permissionWriterEmailMutationConfirmed: $permissionWriterEmailMutationConfirmed,
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

KC_WRITER_FRESH_JSON="${TMP_DIR}/writer-user-fresh.json"
code="$(http_status GET \
  "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${WRITER_USER_ID}" \
  "${KC_WRITER_FRESH_JSON}" \
  --config "${KC_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "permission-writer-profile-precondition-read-failed"
jq -e \
  --arg writerId "${WRITER_USER_ID}" \
  --arg writerUsername "${WRITER_USERNAME}" \
  --arg localUserId "${WRITER_LOCAL_USER_ID}" \
  --arg legacyUserId "${WRITER_LEGACY_LOCAL_USER_ID}" \
  --argjson allowLegacy "${PRE_IDENTITY_CREDENTIAL_ONLY}" '
  .id == $writerId and
  .username == $writerUsername and
  .enabled == true and
  (
    (.attributes.userId == [$localUserId] and
     .attributes.subscriberId == [$localUserId]) or
    ($allowLegacy and
     .attributes.userId == [$legacyUserId] and
     .attributes.subscriberId == [$legacyUserId])
  )
' "${KC_WRITER_FRESH_JSON}" >/dev/null \
  || die "permission-writer-profile-precondition-local-user-mismatch"

WRITER_FRESH_REQUIRED_ACTIONS="$(jq -c '.requiredActions // []' "${KC_WRITER_FRESH_JSON}")"
[[ "${WRITER_FRESH_REQUIRED_ACTIONS}" == '[]' ]] \
  || die "permission-writer-required-actions-unsupported"
WRITER_REQUIRED_ACTIONS_READY=true

WRITER_PROFILE_ATTRIBUTES_BEFORE="${TMP_DIR}/writer-profile-attributes-before.json"
WRITER_PROFILE_REQUIRED_ACTIONS_BEFORE="${TMP_DIR}/writer-profile-required-actions-before.json"
jq -S '.attributes // {}' "${KC_WRITER_FRESH_JSON}" > "${WRITER_PROFILE_ATTRIBUTES_BEFORE}"
jq -S '.requiredActions // []' "${KC_WRITER_FRESH_JSON}" \
  > "${WRITER_PROFILE_REQUIRED_ACTIONS_BEFORE}"

WRITER_EMAIL_BEFORE="$(jq -r '.email // empty' "${KC_WRITER_FRESH_JSON}")"
WRITER_FIRST_NAME_BEFORE="$(jq -r '.firstName // empty' "${KC_WRITER_FRESH_JSON}")"
WRITER_LAST_NAME_BEFORE="$(jq -r '.lastName // empty' "${KC_WRITER_FRESH_JSON}")"
NEED_WRITER_EMAIL=false
NEED_WRITER_FIRST_NAME=false
NEED_WRITER_LAST_NAME=false
[[ "${WRITER_EMAIL_BEFORE}" == "${WRITER_PROFILE_EMAIL}" ]] || NEED_WRITER_EMAIL=true
[[ -n "${WRITER_FIRST_NAME_BEFORE}" ]] || NEED_WRITER_FIRST_NAME=true
[[ -n "${WRITER_LAST_NAME_BEFORE}" ]] || NEED_WRITER_LAST_NAME=true

if [[ "${NEED_WRITER_EMAIL}" == "true" ]]; then
  WRITER_PROFILE_EMAIL_FILE="${TMP_DIR}/writer-profile-email"
  printf '%s' "${WRITER_PROFILE_EMAIL}" > "${WRITER_PROFILE_EMAIL_FILE}"
  WRITER_PROFILE_EMAIL_OWNERS="${TMP_DIR}/writer-profile-email-owners.json"
  code="$(curl -sS --max-time 20 -o "${WRITER_PROFILE_EMAIL_OWNERS}" -w '%{http_code}' --get \
    "${KC_BASE_URL}/admin/realms/${KC_REALM}/users" \
    --config "${KC_AUTH_CONFIG}" \
    --data-urlencode "email@${WRITER_PROFILE_EMAIL_FILE}" \
    --data-urlencode 'exact=true' || printf '000')"
  [[ "${code}" == "200" ]] || die "permission-writer-profile-email-lookup-failed"
  jq -e --arg writerId "${WRITER_USER_ID}" '
    length == 0 or (length == 1 and .[0].id == $writerId)
  ' "${WRITER_PROFILE_EMAIL_OWNERS}" >/dev/null \
    || die "permission-writer-profile-email-conflict"
fi

WRITER_EMAIL_EXPECTED="${WRITER_EMAIL_BEFORE}"
WRITER_FIRST_NAME_EXPECTED="${WRITER_FIRST_NAME_BEFORE}"
WRITER_LAST_NAME_EXPECTED="${WRITER_LAST_NAME_BEFORE}"
if [[ "${NEED_WRITER_EMAIL}" == "true" ]]; then
  WRITER_EMAIL_EXPECTED="${WRITER_PROFILE_EMAIL}"
fi
[[ "${NEED_WRITER_FIRST_NAME}" == "true" ]] \
  && WRITER_FIRST_NAME_EXPECTED="${WRITER_PROFILE_FIRST_NAME}"
[[ "${NEED_WRITER_LAST_NAME}" == "true" ]] \
  && WRITER_LAST_NAME_EXPECTED="${WRITER_PROFILE_LAST_NAME}"

if [[ "${NEED_WRITER_EMAIL}" == "true" || \
      "${NEED_WRITER_FIRST_NAME}" == "true" || \
      "${NEED_WRITER_LAST_NAME}" == "true" ]]; then
  WRITER_PROFILE_UPDATE="${TMP_DIR}/writer-profile-update.json"
  jq -n \
    --arg email "${WRITER_PROFILE_EMAIL}" \
    --arg firstName "${WRITER_PROFILE_FIRST_NAME}" \
    --arg lastName "${WRITER_PROFILE_LAST_NAME}" \
    --argjson setEmail "${NEED_WRITER_EMAIL}" \
    --argjson setFirstName "${NEED_WRITER_FIRST_NAME}" \
    --argjson setLastName "${NEED_WRITER_LAST_NAME}" '
      {} +
      (if $setEmail then {email: $email} else {} end) +
      (if $setFirstName then {firstName: $firstName} else {} end) +
      (if $setLastName then {lastName: $lastName} else {} end)
    ' > "${WRITER_PROFILE_UPDATE}"
  jq -e '
    has("attributes") == false and
    has("requiredActions") == false and
    (keys | length) > 0
  ' "${WRITER_PROFILE_UPDATE}" >/dev/null \
    || die "permission-writer-profile-update-payload-invalid"

  if [[ "${NEED_WRITER_EMAIL}" == "true" ]]; then
    WRITER_PROFILE_EMAIL_MUTATION_ATTEMPTED=true
  fi

  PROFILE_UPDATE_RESPONSE="${TMP_DIR}/writer-profile-update-response.json"
  code="$(http_status PUT \
    "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${WRITER_USER_ID}" \
    "${PROFILE_UPDATE_RESPONSE}" \
    --config "${KC_AUTH_CONFIG}" \
    -H 'Content-Type: application/json' \
    --data-binary "@${WRITER_PROFILE_UPDATE}")"
  [[ ! "${code}" =~ ^4[0-9]{2}$ ]] \
    || die "permission-writer-profile-repair-rejected"

  KC_WRITER_READBACK_JSON="${TMP_DIR}/writer-user-readback.json"
  code="$(http_status GET \
    "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${WRITER_USER_ID}" \
    "${KC_WRITER_READBACK_JSON}" \
    --config "${KC_AUTH_CONFIG}")"
  [[ "${code}" == "200" ]] || die "permission-writer-profile-readback-failed"

  jq -e \
    --arg writerId "${WRITER_USER_ID}" \
    --arg writerUsername "${WRITER_USERNAME}" \
    --arg email "${WRITER_EMAIL_EXPECTED}" \
    --arg firstName "${WRITER_FIRST_NAME_EXPECTED}" \
    --arg lastName "${WRITER_LAST_NAME_EXPECTED}" '
      .id == $writerId and
      .username == $writerUsername and
      .enabled == true and
      .email == $email and
      .firstName == $firstName and
      .lastName == $lastName
    ' "${KC_WRITER_READBACK_JSON}" >/dev/null \
    || die "permission-writer-profile-readback-mismatch"
  [[ "${NEED_WRITER_EMAIL}" == "true" ]] \
    && WRITER_PROFILE_EMAIL_MUTATION_CONFIRMED=true
  jq -S '.attributes // {}' "${KC_WRITER_READBACK_JSON}" \
    | cmp -s "${WRITER_PROFILE_ATTRIBUTES_BEFORE}" - \
    || die "permission-writer-profile-attributes-changed"
  WRITER_PROFILE_ATTRIBUTES_PRESERVED=true
  jq -S '.requiredActions // []' "${KC_WRITER_READBACK_JSON}" \
    | cmp -s "${WRITER_PROFILE_REQUIRED_ACTIONS_BEFORE}" - \
    || die "permission-writer-profile-required-actions-changed"
  WRITER_PROFILE_REQUIRED_ACTIONS_PRESERVED=true
  WRITER_PROFILE_REPAIRED=true
else
  WRITER_PROFILE_ATTRIBUTES_PRESERVED=true
  WRITER_PROFILE_REQUIRED_ACTIONS_PRESERVED=true
fi

WRITER_EFFECTIVE_EMAIL_FILE="${TMP_DIR}/writer-effective-email"
printf '%s' "${WRITER_EMAIL_EXPECTED}" > "${WRITER_EFFECTIVE_EMAIL_FILE}"
WRITER_EFFECTIVE_EMAIL_OWNERS="${TMP_DIR}/writer-effective-email-owners.json"
code="$(curl -sS --max-time 20 -o "${WRITER_EFFECTIVE_EMAIL_OWNERS}" -w '%{http_code}' --get \
  "${KC_BASE_URL}/admin/realms/${KC_REALM}/users" \
  --config "${KC_AUTH_CONFIG}" \
  --data-urlencode "email@${WRITER_EFFECTIVE_EMAIL_FILE}" \
  --data-urlencode 'exact=true' || printf '000')"
[[ "${code}" == "200" ]] || die "permission-writer-profile-email-readback-failed"
jq -e --arg writerId "${WRITER_USER_ID}" '
  length == 1 and .[0].id == $writerId
' "${WRITER_EFFECTIVE_EMAIL_OWNERS}" >/dev/null \
  || die "permission-writer-profile-email-ownership-unverified"
WRITER_PROFILE_EMAIL_COLLISION_FREE=true
WRITER_PROFILE_READY=true

EXISTING_WRITER_USERNAME="$(jq -r '.admin_persona_username // empty' "${VAULT_ORIGINAL_DATA}")"
EXISTING_PASSWORD_FILE="${TMP_DIR}/existing-writer-password"
jq -j '.admin_persona_password // empty' "${VAULT_ORIGINAL_DATA}" > "${EXISTING_PASSWORD_FILE}"
chmod 600 "${EXISTING_PASSWORD_FILE}"
if [[ "${EXISTING_WRITER_USERNAME}" == "${WRITER_USERNAME}" && -s "${EXISTING_PASSWORD_FILE}" ]]; then
  EXISTING_TOKEN_JSON="${TMP_DIR}/existing-writer-token.json"
  if request_writer_token "${EXISTING_PASSWORD_FILE}" "${EXISTING_TOKEN_JSON}"; then
    VAULT_SYNCED=true
    WRITER_LOGIN_READY=true
    if [[ "${PRE_IDENTITY_CREDENTIAL_ONLY}" == "true" ]]; then
      STATUS="credential-ready"
      write_result
      exit 0
    fi
    EXISTING_AUTH_CONFIG="${TMP_DIR}/existing-writer-auth.curl"
    EXISTING_ROLES_JSON="${TMP_DIR}/existing-roles.json"
    verify_roles_read "${WRITER_TOKEN}" "${EXISTING_AUTH_CONFIG}" "${EXISTING_ROLES_JSON}" \
      || die "permission-writer-roles-readback-failed"
    WRITER_ROLES_READ_READY=true
    if [[ "${WRITER_PROFILE_REPAIRED}" == "true" ]]; then
      STATUS="profile-repaired"
    else
      STATUS="already-ready"
    fi
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

if [[ "${PRE_IDENTITY_CREDENTIAL_ONLY}" == "true" ]]; then
  STATUS="credential-repaired"
  write_result
  exit 0
fi

WRITER_AUTH_CONFIG="${TMP_DIR}/writer-auth.curl"
ROLES_JSON="${TMP_DIR}/roles.json"
verify_roles_read "${WRITER_TOKEN}" "${WRITER_AUTH_CONFIG}" "${ROLES_JSON}" \
  || die "permission-writer-roles-readback-failed"
WRITER_ROLES_READ_READY=true

STATUS="repaired"
write_result
