#!/usr/bin/env bash
# Idempotent least-privilege Meeting Intelligence access provisioning.
#
# Runtime boundary:
# - platform-test only
# - exact mailbox sender -> exact Keycloak email -> exact user-service record
# - permission-service is the persistent authorization writer
# - no email, token, password, cookie, or numeric user id is written to output
# - dry-run is the default; live mutation requires --apply

set -Eeuo pipefail
umask 077

MODE="dry-run"
OUT_PATH="${OUT_PATH:-/tmp/faz24-meeting-intelligence-access.json}"
readonly MAILBOX="ai@acik.com"
readonly MAIL_PRIMARY_SUBJECT="FAZ 24"
readonly MAIL_CORROBORATING_SUBJECT="Platform Ai- Meeting Intelligence"
readonly MAIL_ANCHOR_RESOLVER="scripts/faz24/resolve-mail-anchor.jq"
readonly BASE_URL="https://testai.acik.com"
readonly KC_BASE_URL="http://127.0.0.1:8082"
readonly KC_REALM="platform-test"
readonly KC_ADMIN_USER="admin"
readonly KC_REALM_ROLE="MEETING_ADMIN"
readonly KC_RESOURCE_CLIENT="audio-gateway-service"
readonly KC_CLIENT_ROLE="audio_record"
readonly PERMISSION_ROLE_NAME="MEETING_INTELLIGENCE_MANAGER"
readonly VAULT_GRAPH_PATH="kv/platform/graph"
readonly VAULT_PERSONA_PATH="kv/platform/d35-3"

STATUS="running"
FAILURE_REASON=""
KEYCLOAK_MATCH=false
USER_SERVICE_MATCH=false
REALM_ROLE_READY=false
CLIENT_ROLE_READY=false
PERMISSION_ROLE_READY=false
GRANULES_READY=false
MEMBERSHIP_READY=false

usage() {
  cat <<'EOF'
Usage: provision-meeting-intelligence-access.sh [--apply] [--out PATH]

Default mode is dry-run. It performs every identity and authorization preflight
but does not create or modify a role assignment. --apply performs the bounded,
idempotent platform-test mutation and verifies readback.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) MODE="apply"; shift ;;
    --out) OUT_PATH="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for command_name in curl jq docker; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command missing: ${command_name}" >&2
    exit 2
  }
done

TMP_DIR="$(mktemp -d /tmp/faz24-mi-access.XXXXXX)"
mkdir -p "$(dirname "${OUT_PATH}")"

write_result() {
  jq -n \
    --arg mode "${MODE}" \
    --arg status "${STATUS}" \
    --arg failureReason "${FAILURE_REASON}" \
    --arg permissionRole "${PERMISSION_ROLE_NAME}" \
    --arg realmRole "${KC_REALM_ROLE}" \
    --arg resourceClient "${KC_RESOURCE_CLIENT}" \
    --arg clientRole "${KC_CLIENT_ROLE}" \
    --argjson keycloakMatch "${KEYCLOAK_MATCH}" \
    --argjson userServiceMatch "${USER_SERVICE_MATCH}" \
    --argjson realmRoleReady "${REALM_ROLE_READY}" \
    --argjson clientRoleReady "${CLIENT_ROLE_READY}" \
    --argjson permissionRoleReady "${PERMISSION_ROLE_READY}" \
    --argjson granulesReady "${GRANULES_READY}" \
    --argjson membershipReady "${MEMBERSHIP_READY}" \
    '{
      schemaVersion: "faz24.meetingIntelligenceAccess.v1",
      mode: $mode,
      status: $status,
      failureReason: (if $failureReason == "" then null else $failureReason end),
      target: {
        exactKeycloakMatch: $keycloakMatch,
        exactUserServiceMatch: $userServiceMatch
      },
      keycloak: {
        realm: "platform-test",
        realmRole: $realmRole,
        realmRoleReady: $realmRoleReady,
        resourceClient: $resourceClient,
        clientRole: $clientRole,
        clientRoleReady: $clientRoleReady
      },
      permissionService: {
        role: $permissionRole,
        roleReady: $permissionRoleReady,
        granules: [
          {type: "MODULE", key: "MEETING", grant: "MANAGE"},
          {type: "MODULE", key: "TRANSCRIPT", grant: "MANAGE"}
        ],
        granulesReady: $granulesReady,
        membershipReady: $membershipReady
      },
      boundaries: {
        productionMutation: false,
        broadAdminGrant: false,
        rawIdentityIncluded: false,
        rawCredentialIncluded: false,
        rawTokenIncluded: false
      }
    }' > "${OUT_PATH}"
}

cleanup() {
  rm -rf "${TMP_DIR}"
  unset GRAPH_CLIENT_SECRET GRAPH_ACCESS_TOKEN PERSONA_PASSWORD PERSONA_TOKEN KC_ADMIN_PASSWORD KC_ADMIN_TOKEN
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

read_vault_path() {
  local path="$1"
  local output="$2"
  local vault_container="$3"
  local init_file="$4"
  local root_token
  root_token="$(jq -r '.root_token // empty' "${init_file}" 2>/dev/null || true)"
  [[ -n "${root_token}" ]] || return 1
  docker inspect "${vault_container}" >/dev/null 2>&1 || return 1

  printf '%s\n' "${root_token}" | docker exec -i "${vault_container}" sh -c '
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    vault kv get -format=json "$1"
  ' sh "${path}" > "${output}" 2>/dev/null
  unset root_token
}

GRAPH_VAULT_JSON="${TMP_DIR}/graph-vault.json"
PERSONA_VAULT_JSON="${TMP_DIR}/persona-vault.json"
read_vault_path \
  "${VAULT_GRAPH_PATH}" \
  "${GRAPH_VAULT_JSON}" \
  "platform-vault-prod" \
  "/srv/platform/secrets/backup-auth/vault-init-prod.json" \
  || die "graph-prod-vault-read-failed"
read_vault_path \
  "${VAULT_PERSONA_PATH}" \
  "${PERSONA_VAULT_JSON}" \
  "platform-vault-test" \
  "/srv/platform/secrets/backup-auth/vault-init-test.json" \
  || die "persona-test-vault-read-failed"

GRAPH_CLIENT_ID="$(jq -r '.data.data.graph_client_id // .data.data.client_id // empty' "${GRAPH_VAULT_JSON}")"
GRAPH_CLIENT_SECRET="$(jq -r '.data.data.graph_client_secret // .data.data.client_secret // empty' "${GRAPH_VAULT_JSON}")"
GRAPH_TENANT_ID="$(jq -r '.data.data.graph_tenant_id // .data.data.tenant_id // empty' "${GRAPH_VAULT_JSON}")"
PERSONA_USERNAME="$(jq -r '.data.data.admin_persona_username // empty' "${PERSONA_VAULT_JSON}")"
PERSONA_PASSWORD="$(jq -r '.data.data.admin_persona_password // empty' "${PERSONA_VAULT_JSON}")"

[[ -n "${GRAPH_CLIENT_ID}" && -n "${GRAPH_CLIENT_SECRET}" && -n "${GRAPH_TENANT_ID}" ]] \
  || die "graph-vault-fields-missing"
[[ -n "${PERSONA_USERNAME}" && -n "${PERSONA_PASSWORD}" ]] \
  || die "persona-vault-fields-missing"
[[ -n "${KC_ADMIN_PASSWORD:-}" ]] || die "keycloak-admin-password-missing"

GRAPH_CLIENT_SECRET_FILE="${TMP_DIR}/graph-client-secret"
PERSONA_USERNAME_FILE="${TMP_DIR}/persona-username"
PERSONA_PASSWORD_FILE="${TMP_DIR}/persona-password"
KC_ADMIN_PASSWORD_FILE="${TMP_DIR}/keycloak-admin-password"
SMOKE_CLIENT_SECRET_FILE="${TMP_DIR}/smoke-client-secret"

# A2b.2 (2026-07-21): confidential smoke-client ROPC (client_id=frontend + DAG=false, A2c cutover).
# Vault kv/platform/keycloak/smoke-client (A2a); scope-mapping/audience A2b.1 setup-smoke-token-contract.sh.
SMOKE_VAULT_ROOT="$(python3 -c "import json; print(json.load(open('/home/halil/bootstrap-drill/vault-init-test.json'))['root_token'])" 2>/dev/null || true)"
if [[ -n "${SMOKE_VAULT_ROOT}" ]]; then
  docker exec -e VAULT_TOKEN="${SMOKE_VAULT_ROOT}" platform-vault-test \
    vault kv get -field=client_secret kv/platform/keycloak/smoke-client > "${SMOKE_CLIENT_SECRET_FILE}" \
    || die "smoke-client-secret-fetch-failed"
  chmod 0600 "${SMOKE_CLIENT_SECRET_FILE}"
  SMOKE_VAULT_ROOT=""
else
  die "smoke-client-vault-root-token-missing"
fi
printf '%s' "${GRAPH_CLIENT_SECRET}" > "${GRAPH_CLIENT_SECRET_FILE}"
printf '%s' "${PERSONA_USERNAME}" > "${PERSONA_USERNAME_FILE}"
printf '%s' "${PERSONA_PASSWORD}" > "${PERSONA_PASSWORD_FILE}"
printf '%s' "${KC_ADMIN_PASSWORD}" > "${KC_ADMIN_PASSWORD_FILE}"

GRAPH_TOKEN_JSON="${TMP_DIR}/graph-token.json"
code="$(http_status POST \
  "https://login.microsoftonline.com/${GRAPH_TENANT_ID}/oauth2/v2.0/token" \
  "${GRAPH_TOKEN_JSON}" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode "client_id=${GRAPH_CLIENT_ID}" \
  --data-urlencode "client_secret@${GRAPH_CLIENT_SECRET_FILE}" \
  --data-urlencode 'scope=https://graph.microsoft.com/.default' \
  --data-urlencode 'grant_type=client_credentials')"
[[ "${code}" == "200" ]] || die "graph-token-failed"
GRAPH_ACCESS_TOKEN="$(jq -r '.access_token // empty' "${GRAPH_TOKEN_JSON}")"
[[ -n "${GRAPH_ACCESS_TOKEN}" ]] || die "graph-token-missing"
GRAPH_AUTH_CONFIG="${TMP_DIR}/graph-auth.curl"
write_bearer_config "${GRAPH_AUTH_CONFIG}" "${GRAPH_ACCESS_TOKEN}"

[[ -f "${MAIL_ANCHOR_RESOLVER}" ]] || die "mail-anchor-resolver-missing"

read_mail_anchor() {
  local subject="$1"
  local output="$2"
  local status

  status="$(curl -sS --max-time 20 -o "${output}" -w '%{http_code}' --get \
    "https://graph.microsoft.com/v1.0/users/${MAILBOX}/mailFolders/inbox/messages" \
    --config "${GRAPH_AUTH_CONFIG}" \
    -H 'ConsistencyLevel: eventual' \
    --data-urlencode "\$top=50" \
    --data-urlencode "\$select=subject,from,receivedDateTime" \
    --data-urlencode "\$filter=subject eq '${subject}'" || printf '000')"
  [[ "${status}" == "200" ]]
}

PRIMARY_MAIL_JSON="${TMP_DIR}/primary-mail-anchor.json"
CORROBORATING_MAIL_JSON="${TMP_DIR}/corroborating-mail-anchor.json"
read_mail_anchor "${MAIL_PRIMARY_SUBJECT}" "${PRIMARY_MAIL_JSON}" \
  || die "graph-primary-mail-anchor-read-failed"
read_mail_anchor "${MAIL_CORROBORATING_SUBJECT}" "${CORROBORATING_MAIL_JSON}" \
  || die "graph-corroborating-mail-anchor-read-failed"

if ! TARGET_EMAIL="$(jq -nr \
  --arg primary_subject "${MAIL_PRIMARY_SUBJECT}" \
  --arg corroborating_subject "${MAIL_CORROBORATING_SUBJECT}" \
  --slurpfile primary "${PRIMARY_MAIL_JSON}" \
  --slurpfile corroborating "${CORROBORATING_MAIL_JSON}" \
  -f "${MAIL_ANCHOR_RESOLVER}" 2>/dev/null)"; then
  die "exact-zeynep-mail-anchor-inconsistent"
fi
[[ -n "${TARGET_EMAIL}" ]] || die "exact-zeynep-mail-anchor-inconsistent"
TARGET_EMAIL_FILE="${TMP_DIR}/target-email"
printf '%s' "${TARGET_EMAIL}" > "${TARGET_EMAIL_FILE}"

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

KC_USERS_JSON="${TMP_DIR}/kc-users.json"
code="$(curl -sS --max-time 20 -o "${KC_USERS_JSON}" -w '%{http_code}' --get \
  "${KC_BASE_URL}/admin/realms/${KC_REALM}/users" \
  --config "${KC_AUTH_CONFIG}" \
  --data-urlencode "email@${TARGET_EMAIL_FILE}" \
  --data-urlencode 'exact=true' || printf '000')"
[[ "${code}" == "200" ]] || die "keycloak-user-lookup-failed"
[[ "$(jq 'length' "${KC_USERS_JSON}")" == "1" ]] || die "keycloak-user-not-exactly-one"
[[ "$(jq -r '.[0].enabled // false' "${KC_USERS_JSON}")" == "true" ]] || die "keycloak-user-disabled"
KC_EMAIL_NORMALIZED="$(jq -r '.[0].email // empty | ascii_downcase' "${KC_USERS_JSON}")"
[[ "${KC_EMAIL_NORMALIZED}" == "${TARGET_EMAIL}" ]] || die "keycloak-user-email-mismatch"
KC_USER_ID="$(jq -r '.[0].id // empty' "${KC_USERS_JSON}")"
[[ -n "${KC_USER_ID}" ]] || die "keycloak-user-id-missing"
KEYCLOAK_MATCH=true

REALM_ROLE_JSON="${TMP_DIR}/realm-role.json"
code="$(http_status GET \
  "${KC_BASE_URL}/admin/realms/${KC_REALM}/roles/${KC_REALM_ROLE}" \
  "${REALM_ROLE_JSON}" \
  --config "${KC_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "required-realm-role-missing"

CLIENTS_JSON="${TMP_DIR}/clients.json"
code="$(curl -sS --max-time 20 -o "${CLIENTS_JSON}" -w '%{http_code}' --get \
  "${KC_BASE_URL}/admin/realms/${KC_REALM}/clients" \
  --config "${KC_AUTH_CONFIG}" \
  --data-urlencode "clientId=${KC_RESOURCE_CLIENT}" || printf '000')"
[[ "${code}" == "200" && "$(jq 'length' "${CLIENTS_JSON}")" == "1" ]] \
  || die "resource-client-not-exactly-one"
KC_CLIENT_UUID="$(jq -r '.[0].id // empty' "${CLIENTS_JSON}")"

CLIENT_ROLE_JSON="${TMP_DIR}/client-role.json"
code="$(http_status GET \
  "${KC_BASE_URL}/admin/realms/${KC_REALM}/clients/${KC_CLIENT_UUID}/roles/${KC_CLIENT_ROLE}" \
  "${CLIENT_ROLE_JSON}" \
  --config "${KC_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "required-client-role-missing"

PERSONA_TOKEN_JSON="${TMP_DIR}/persona-token.json"
code="$(http_status POST \
  "${KC_BASE_URL}/realms/${KC_REALM}/protocol/openid-connect/token" \
  "${PERSONA_TOKEN_JSON}" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=password' \
  --data-urlencode 'client_id=smoke-client' \
  --data-urlencode "client_secret@${SMOKE_CLIENT_SECRET_FILE}" \
  --data-urlencode "username@${PERSONA_USERNAME_FILE}" \
  --data-urlencode "password@${PERSONA_PASSWORD_FILE}")"
[[ "${code}" == "200" ]] || die "permission-writer-login-failed"
PERSONA_TOKEN="$(jq -r '.access_token // empty' "${PERSONA_TOKEN_JSON}")"
[[ -n "${PERSONA_TOKEN}" ]] || die "permission-writer-token-missing"
PERSONA_AUTH_CONFIG="${TMP_DIR}/persona-auth.curl"
write_bearer_config "${PERSONA_AUTH_CONFIG}" "${PERSONA_TOKEN}"

USER_JSON="${TMP_DIR}/user.json"
code="$(curl -sS --max-time 20 -o "${USER_JSON}" -w '%{http_code}' --get \
  "${BASE_URL}/api/v1/users/by-email" \
  --config "${PERSONA_AUTH_CONFIG}" \
  --data-urlencode "email@${TARGET_EMAIL_FILE}" || printf '000')"
[[ "${code}" == "200" ]] || die "user-service-exact-lookup-failed"
PLATFORM_USER_ID="$(jq -r '.id // empty' "${USER_JSON}")"
USER_EMAIL_NORMALIZED="$(jq -r '.email // empty | ascii_downcase' "${USER_JSON}")"
[[ "${PLATFORM_USER_ID}" =~ ^[0-9]+$ && "${USER_EMAIL_NORMALIZED}" == "${TARGET_EMAIL}" ]] \
  || die "user-service-identity-mismatch"
USER_SERVICE_MATCH=true

ROLES_JSON="${TMP_DIR}/roles.json"
code="$(http_status GET "${BASE_URL}/api/v1/roles" "${ROLES_JSON}" \
  --config "${PERSONA_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "permission-role-list-failed"
ROLE_MATCH_COUNT="$(jq --arg name "${PERMISSION_ROLE_NAME}" '[.items[]? | select(.name == $name)] | length' "${ROLES_JSON}")"
[[ "${ROLE_MATCH_COUNT}" == "0" || "${ROLE_MATCH_COUNT}" == "1" ]] \
  || die "permission-role-not-unique"
ROLE_ID="$(jq -r --arg name "${PERMISSION_ROLE_NAME}" '[.items[]? | select(.name == $name)][0].id // empty' "${ROLES_JSON}")"

if [[ -n "${ROLE_ID}" ]]; then
  GRANULES_BEFORE_JSON="${TMP_DIR}/granules-before.json"
  code="$(http_status GET "${BASE_URL}/api/v1/roles/${ROLE_ID}/granules" "${GRANULES_BEFORE_JSON}" \
    --config "${PERSONA_AUTH_CONFIG}")"
  [[ "${code}" == "200" ]] || die "permission-granule-preflight-failed"
  jq -e 'all(.granules[]?;
    (.type == "MODULE" and .grant == "MANAGE" and (.key == "MEETING" or .key == "TRANSCRIPT")))' \
    "${GRANULES_BEFORE_JSON}" >/dev/null || die "existing-role-has-unrelated-granules"
fi

if [[ "${MODE}" == "dry-run" ]]; then
  STATUS="ready"
  write_result
  exit 0
fi

if [[ -z "${ROLE_ID}" ]]; then
  CREATE_ROLE_BODY="${TMP_DIR}/create-role.json"
  jq -n --arg name "${PERMISSION_ROLE_NAME}" \
    '{name: $name, description: "Meeting Intelligence least-privilege access"}' > "${CREATE_ROLE_BODY}"
  CREATE_ROLE_JSON="${TMP_DIR}/create-role-response.json"
  code="$(http_status POST "${BASE_URL}/api/v1/roles" "${CREATE_ROLE_JSON}" \
    --config "${PERSONA_AUTH_CONFIG}" \
    -H 'Content-Type: application/json' \
    --data-binary "@${CREATE_ROLE_BODY}")"
  [[ "${code}" == "201" ]] || die "permission-role-create-failed"
  ROLE_ID="$(jq -r '.id // empty' "${CREATE_ROLE_JSON}")"
  [[ "${ROLE_ID}" =~ ^[0-9]+$ ]] || die "permission-role-created-id-missing"
fi

GRANULE_BODY="${TMP_DIR}/granules.json"
jq -n '{permissions: [
  {type: "MODULE", key: "MEETING", grant: "MANAGE"},
  {type: "MODULE", key: "TRANSCRIPT", grant: "MANAGE"}
]}' > "${GRANULE_BODY}"
MUTATION_RESPONSE="${TMP_DIR}/mutation-response.json"
code="$(http_status PUT "${BASE_URL}/api/v1/roles/${ROLE_ID}/granules" "${MUTATION_RESPONSE}" \
  --config "${PERSONA_AUTH_CONFIG}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${GRANULE_BODY}")"
[[ "${code}" == "200" ]] || die "permission-granule-write-failed"

MEMBER_BODY="${TMP_DIR}/member.json"
jq -n --argjson userId "${PLATFORM_USER_ID}" '{userIds: [$userId]}' > "${MEMBER_BODY}"
code="$(http_status POST "${BASE_URL}/api/v1/roles/${ROLE_ID}/members" "${MUTATION_RESPONSE}" \
  --config "${PERSONA_AUTH_CONFIG}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${MEMBER_BODY}")"
[[ "${code}" == "200" ]] || die "permission-membership-write-failed"

jq -s '.' "${REALM_ROLE_JSON}" > "${TMP_DIR}/realm-role-array.json"
code="$(http_status POST \
  "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${KC_USER_ID}/role-mappings/realm" \
  "${MUTATION_RESPONSE}" \
  --config "${KC_AUTH_CONFIG}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${TMP_DIR}/realm-role-array.json")"
[[ "${code}" == "204" ]] || die "realm-role-write-failed"

jq -s '.' "${CLIENT_ROLE_JSON}" > "${TMP_DIR}/client-role-array.json"
code="$(http_status POST \
  "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${KC_USER_ID}/role-mappings/clients/${KC_CLIENT_UUID}" \
  "${MUTATION_RESPONSE}" \
  --config "${KC_AUTH_CONFIG}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${TMP_DIR}/client-role-array.json")"
[[ "${code}" == "204" ]] || die "client-role-write-failed"

GRANULES_AFTER_JSON="${TMP_DIR}/granules-after.json"
code="$(http_status GET "${BASE_URL}/api/v1/roles/${ROLE_ID}/granules" "${GRANULES_AFTER_JSON}" \
  --config "${PERSONA_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "permission-granule-readback-failed"
jq -e '.granules == [
  {type: "MODULE", key: "MEETING", grant: "MANAGE"},
  {type: "MODULE", key: "TRANSCRIPT", grant: "MANAGE"}
]' "${GRANULES_AFTER_JSON}" >/dev/null || die "permission-granule-readback-mismatch"
GRANULES_READY=true
PERMISSION_ROLE_READY=true

MEMBERS_JSON="${TMP_DIR}/members.json"
code="$(http_status GET "${BASE_URL}/api/v1/roles/${ROLE_ID}/members" "${MEMBERS_JSON}" \
  --config "${PERSONA_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "permission-membership-readback-failed"
jq -e --argjson userId "${PLATFORM_USER_ID}" 'any(.[]?; .userId == $userId)' \
  "${MEMBERS_JSON}" >/dev/null || die "permission-membership-readback-mismatch"
MEMBERSHIP_READY=true

REALM_ROLES_AFTER="${TMP_DIR}/realm-roles-after.json"
code="$(http_status GET \
  "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${KC_USER_ID}/role-mappings/realm" \
  "${REALM_ROLES_AFTER}" \
  --config "${KC_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "realm-role-readback-failed"
jq -e --arg role "${KC_REALM_ROLE}" 'any(.[]?; .name == $role)' "${REALM_ROLES_AFTER}" >/dev/null \
  || die "realm-role-readback-mismatch"
REALM_ROLE_READY=true

CLIENT_ROLES_AFTER="${TMP_DIR}/client-roles-after.json"
code="$(http_status GET \
  "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${KC_USER_ID}/role-mappings/clients/${KC_CLIENT_UUID}" \
  "${CLIENT_ROLES_AFTER}" \
  --config "${KC_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "client-role-readback-failed"
jq -e --arg role "${KC_CLIENT_ROLE}" 'any(.[]?; .name == $role)' "${CLIENT_ROLES_AFTER}" >/dev/null \
  || die "client-role-readback-mismatch"
CLIENT_ROLE_READY=true

STATUS="applied"
write_result
