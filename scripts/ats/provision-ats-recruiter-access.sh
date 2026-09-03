#!/usr/bin/env bash
# Idempotent least-privilege ATS recruiter access provisioning (platform-test).
#
# Grants an existing platform person access to the ATS product surface by adding
# them to the pre-existing "Full ATS Recruiter" permission-service role. The role
# already carries the correct granules; this script is deliberately
# MEMBERSHIP-ONLY.
#
# Runtime boundary:
# - platform-test only; no production mutation
# - membership-only: the role's granules are never created, widened or modified
# - exact identity triple: Keycloak email <-> user-service email <-> numeric id
# - permission-service is the persistent authorization writer (role membership
#   -> RoleChangeEvent -> outbox -> OpenFGA). Direct DB INSERT and direct
#   OpenFGA seed are refused by construction: this script only calls the
#   permission-service HTTP API.
# - fail-closed on role widening: if the target role carries any granule outside
#   the expected ATS recruiting set, the mutation is refused
# - no email, numeric id, token, password or cookie is written to the artifact
# - dry-run is the default; live mutation requires --apply
#
# Must run on the platform host: needs the Vault/Keycloak containers and the
# host-mapped Keycloak admin port.
#
# Usage: provision-ats-recruiter-access.sh [--apply] [--email ADDR] [--out PATH]

set -Eeuo pipefail
umask 077

MODE="dry-run"
TARGET_EMAIL="${TARGET_EMAIL:-zeynep.akkilic@acik.com}"
OUT_PATH="${OUT_PATH:-/tmp/faz25-ats-recruiter-access.json}"

readonly BASE_URL="https://testai.acik.com"
readonly KC_BASE_URL="http://127.0.0.1:8082"
readonly KC_REALM="platform-test"
readonly KC_ADMIN_USER="admin"
readonly KC_CONTAINER="platform-kc-test"
readonly VAULT_CONTAINER="platform-vault-test"
readonly VAULT_PERSONA_PATH="kv/platform/d35-3"
readonly VAULT_SMOKE_CLIENT_PATH="kv/platform/keycloak/smoke-client"
readonly PERMISSION_ROLE_NAME="Full ATS Recruiter"

# ROPC client for the permission-service writer token. `frontend` lost
# directAccessGrantsEnabled in the A2c cutover; smoke-client is the canonical
# ROPC substrate and its default scope already carries the permission-service
# audience. Token is minted through the public edge so the issuer claim matches
# what the backend validates.
readonly KC_ROPC_CLIENT_ID="smoke-client"
# ATS recruiter endpoints are tenant-gated on the JWT `tenant` claim, which the
# Keycloak client scope `ats-api-audience` derives from the user attribute
# `ats_tenant` (NOT the platform `tenantId` attribute). M365 auto-provisioned
# accounts carry `entra_oid/entra_tid` but no `ats_tenant`, so a correct role
# membership still yields 403 on /api/v1/recruiter/** (platform-web#1134).
readonly ATS_TENANT_ATTRIBUTE="ats_tenant"
readonly ATS_PUBLIC_TENANT_ID="${ATS_PUBLIC_TENANT_ID:-00000000-0000-0000-0000-000000000001}"

# The ATS module gate this grant must produce. permission-service performs no
# case transform (catalog key == permission_key == OpenFGA object id), so the
# key is pinned verbatim.
readonly REQUIRED_MODULE_KEY="ATS"

# Every granule the target role is allowed to carry. A role carrying anything
# else is not the role this script was reviewed against -> refuse.
readonly ALLOWED_GRANULE_KEYS="ATS INTERVIEW_EVIDENCE ATS_APPLICATION_MANAGE ATS_JOB_MANAGE"

# Destructive / privacy-sensitive granules that must never be handed out by this
# script. ATS_RETENTION_EXECUTE is never implied by ATS:MANAGE upstream; keep
# that boundary here too.
readonly FORBIDDEN_GRANULE_KEYS="ATS_RETENTION_EXECUTE ERASURE_EXECUTE DSAR_WRITE EXPORT_REPAIR"

STATUS="running"
FAILURE_REASON=""
KEYCLOAK_MATCH=false
KEYCLOAK_TENANT_CLAIM_READY=false
ATS_TENANT_ATTRIBUTE_WRITTEN=false
USER_SERVICE_MATCH=false
PERMISSION_ROLE_READY=false
GRANULE_BOUNDARY_READY=false
MEMBERSHIP_READY=false
ALREADY_MEMBER=false

usage() {
  cat <<'EOF'
Usage: provision-ats-recruiter-access.sh [--apply] [--email ADDR] [--out PATH]

Default mode is dry-run: every identity, role and granule-boundary preflight
runs, but no membership is written. --apply performs the bounded, idempotent
platform-test membership mutation and verifies readback.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) MODE="apply"; shift ;;
    --email) TARGET_EMAIL="$2"; shift 2 ;;
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

TARGET_EMAIL="$(printf '%s' "${TARGET_EMAIL}" | tr '[:upper:]' '[:lower:]')"
[[ "${TARGET_EMAIL}" == *@* ]] || { echo "ERROR: --email must be an address" >&2; exit 2; }

TMP_DIR="$(mktemp -d /tmp/faz25-ats-access.XXXXXX)"
mkdir -p "$(dirname "${OUT_PATH}")"

write_result() {
  jq -n \
    --arg mode "${MODE}" \
    --arg status "${STATUS}" \
    --arg failureReason "${FAILURE_REASON}" \
    --arg permissionRole "${PERMISSION_ROLE_NAME}" \
    --arg moduleKey "${REQUIRED_MODULE_KEY}" \
    --argjson keycloakMatch "${KEYCLOAK_MATCH}" \
    --argjson keycloakTenantClaimReady "${KEYCLOAK_TENANT_CLAIM_READY}" \
    --argjson atsTenantAttributeWritten "${ATS_TENANT_ATTRIBUTE_WRITTEN}" \
    --argjson userServiceMatch "${USER_SERVICE_MATCH}" \
    --argjson permissionRoleReady "${PERMISSION_ROLE_READY}" \
    --argjson granuleBoundaryReady "${GRANULE_BOUNDARY_READY}" \
    --argjson membershipReady "${MEMBERSHIP_READY}" \
    --argjson alreadyMember "${ALREADY_MEMBER}" \
    '{
      schemaVersion: "faz25.atsRecruiterAccess.v1",
      mode: $mode,
      status: $status,
      failureReason: (if $failureReason == "" then null else $failureReason end),
      target: {
        exactKeycloakMatch: $keycloakMatch,
        exactUserServiceMatch: $userServiceMatch,
        keycloakTenantClaimReady: $keycloakTenantClaimReady,
        atsTenantAttributeWritten: $atsTenantAttributeWritten
      },
      permissionService: {
        role: $permissionRole,
        roleReady: $permissionRoleReady,
        moduleGate: $moduleKey,
        granuleBoundaryReady: $granuleBoundaryReady,
        granulesMutated: false,
        membershipReady: $membershipReady,
        alreadyMember: $alreadyMember,
        writer: "permission-service-http-api"
      },
      boundaries: {
        productionMutation: false,
        granuleWidening: false,
        directDatabaseWrite: false,
        directOpenFgaSeed: false,
        destructiveGrant: false,
        rawIdentityIncluded: false,
        rawCredentialIncluded: false,
        rawTokenIncluded: false
      }
    }' > "${OUT_PATH}"
}

cleanup() {
  rm -rf "${TMP_DIR}"
  unset PERSONA_PASSWORD PERSONA_TOKEN KC_ADMIN_PASSWORD KC_ADMIN_TOKEN \
    VAULT_ROOT_TOKEN KC_ROPC_CLIENT_SECRET
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

# Vault unseal/root material moved when the platform host was migrated; accept
# the current location first and fall back to the legacy path. Root token is
# piped, never echoed.
read_vault_root_token() {
  local candidate
  for candidate in \
    /srv/platform/secrets/backup-auth/vault-init-test.json \
    /home/halil/bootstrap-drill/vault-init-test.json; do
    if [[ -r "${candidate}" ]]; then
      jq -r '.root_token // empty' "${candidate}" 2>/dev/null && return 0
    fi
    if sudo -n test -r "${candidate}" 2>/dev/null; then
      sudo -n cat "${candidate}" 2>/dev/null | jq -r '.root_token // empty' && return 0
    fi
  done
  return 1
}

VAULT_ROOT_TOKEN="$(read_vault_root_token || true)"
[[ -n "${VAULT_ROOT_TOKEN}" ]] || die "vault-root-token-unreadable"

PERSONA_VAULT_JSON="${TMP_DIR}/persona-vault.json"
printf '%s\n' "${VAULT_ROOT_TOKEN}" | docker exec -i "${VAULT_CONTAINER}" sh -c '
  IFS= read -r VAULT_TOKEN
  export VAULT_TOKEN VAULT_ADDR=http://127.0.0.1:8200
  vault kv get -format=json "$1"
' sh "${VAULT_PERSONA_PATH}" > "${PERSONA_VAULT_JSON}" 2>/dev/null \
  || die "persona-vault-read-failed"

PERSONA_USERNAME="$(jq -r '.data.data.admin_persona_username // empty' "${PERSONA_VAULT_JSON}")"
PERSONA_PASSWORD="$(jq -r '.data.data.admin_persona_password // empty' "${PERSONA_VAULT_JSON}")"
[[ -n "${PERSONA_USERNAME}" && -n "${PERSONA_PASSWORD}" ]] || die "persona-vault-fields-missing"

SMOKE_VAULT_JSON="${TMP_DIR}/smoke-client-vault.json"
printf '%s\n' "${VAULT_ROOT_TOKEN}" | docker exec -i "${VAULT_CONTAINER}" sh -c '
  IFS= read -r VAULT_TOKEN
  export VAULT_TOKEN VAULT_ADDR=http://127.0.0.1:8200
  vault kv get -format=json "$1"
' sh "${VAULT_SMOKE_CLIENT_PATH}" > "${SMOKE_VAULT_JSON}" 2>/dev/null \
  || die "smoke-client-vault-read-failed"
KC_ROPC_CLIENT_SECRET="$(jq -r '.data.data.client_secret // empty' "${SMOKE_VAULT_JSON}")"
[[ -n "${KC_ROPC_CLIENT_SECRET}" ]] || die "smoke-client-secret-missing"
unset VAULT_ROOT_TOKEN

KC_ADMIN_PASSWORD="$(docker exec "${KC_CONTAINER}" sh -c 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"' 2>/dev/null || true)"
[[ -n "${KC_ADMIN_PASSWORD}" ]] || die "keycloak-admin-password-unreadable"

TARGET_EMAIL_FILE="${TMP_DIR}/target-email"
PERSONA_USERNAME_FILE="${TMP_DIR}/persona-username"
PERSONA_PASSWORD_FILE="${TMP_DIR}/persona-password"
KC_ADMIN_PASSWORD_FILE="${TMP_DIR}/keycloak-admin-password"
KC_ROPC_CLIENT_SECRET_FILE="${TMP_DIR}/ropc-client-secret"
printf '%s' "${TARGET_EMAIL}" > "${TARGET_EMAIL_FILE}"
printf '%s' "${PERSONA_USERNAME}" > "${PERSONA_USERNAME_FILE}"
printf '%s' "${PERSONA_PASSWORD}" > "${PERSONA_PASSWORD_FILE}"
printf '%s' "${KC_ADMIN_PASSWORD}" > "${KC_ADMIN_PASSWORD_FILE}"
printf '%s' "${KC_ROPC_CLIENT_SECRET}" > "${KC_ROPC_CLIENT_SECRET_FILE}"

# --- 1) Keycloak identity anchor -------------------------------------------
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
[[ "$(jq -r '.[0].email // empty | ascii_downcase' "${KC_USERS_JSON}")" == "${TARGET_EMAIL}" ]] \
  || die "keycloak-user-email-mismatch"
KC_USER_ID="$(jq -r '.[0].id // empty' "${KC_USERS_JSON}")"
[[ -n "${KC_USER_ID}" ]] || die "keycloak-user-id-missing"
KEYCLOAK_MATCH=true

# The ATS recruiter endpoints are tenant-gated (tenantAuthenticated): a token
# without a `tenant` claim derives zero authority. The claim is mapped from the
# user attribute `ats_tenant`; the platform `tenantId` attribute is a different
# key and does not satisfy the ATS gate. Under --apply the attribute is written
# (idempotent, other attributes preserved) and read back; in dry-run a missing
# attribute is reported instead of being mistaken for readiness.
jq -e '(.[0].attributes.tenantId[0] // "") | length > 0' "${KC_USERS_JSON}" >/dev/null \
  || die "keycloak-tenant-attribute-missing"
KC_ATS_TENANT="$(jq -r --arg key "${ATS_TENANT_ATTRIBUTE}" \
  '.[0].attributes[$key][0] // empty' "${KC_USERS_JSON}")"
if [[ "${KC_ATS_TENANT}" == "${ATS_PUBLIC_TENANT_ID}" ]]; then
  KEYCLOAK_TENANT_CLAIM_READY=true
elif [[ -n "${KC_ATS_TENANT}" ]]; then
  die "keycloak-ats-tenant-attribute-mismatch"
elif [[ "${MODE}" == "apply" ]]; then
  KC_USER_JSON="${TMP_DIR}/kc-user.json"
  code="$(curl -sS --max-time 20 -o "${KC_USER_JSON}" -w '%{http_code}' \
    "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${KC_USER_ID}" \
    --config "${KC_AUTH_CONFIG}" || printf '000')"
  [[ "${code}" == "200" ]] || die "keycloak-user-read-failed"
  KC_USER_PUT_JSON="${TMP_DIR}/kc-user-put.json"
  # PUT replaces the whole user representation: send the full object back with
  # only the attribute map extended (an attributes-only body drops email/name).
  jq --arg key "${ATS_TENANT_ATTRIBUTE}" --arg tenant "${ATS_PUBLIC_TENANT_ID}" \
    '.attributes = ((.attributes // {}) + {($key): [$tenant]})' \
    "${KC_USER_JSON}" > "${KC_USER_PUT_JSON}"
  code="$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' -X PUT \
    "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${KC_USER_ID}" \
    --config "${KC_AUTH_CONFIG}" \
    -H 'Content-Type: application/json' --data "@${KC_USER_PUT_JSON}" || printf '000')"
  [[ "${code}" == "204" ]] || die "keycloak-ats-tenant-attribute-write-failed"
  code="$(curl -sS --max-time 20 -o "${KC_USER_JSON}" -w '%{http_code}' \
    "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${KC_USER_ID}" \
    --config "${KC_AUTH_CONFIG}" || printf '000')"
  [[ "${code}" == "200" ]] || die "keycloak-ats-tenant-attribute-readback-failed"
  [[ "$(jq -r --arg key "${ATS_TENANT_ATTRIBUTE}" '.attributes[$key][0] // empty' "${KC_USER_JSON}")" \
    == "${ATS_PUBLIC_TENANT_ID}" ]] || die "keycloak-ats-tenant-attribute-readback-mismatch"
  [[ "$(jq -r '.email // empty | ascii_downcase' "${KC_USER_JSON}")" == "${TARGET_EMAIL}" ]] \
    || die "keycloak-user-email-lost-on-write"
  ATS_TENANT_ATTRIBUTE_WRITTEN=true
  KEYCLOAK_TENANT_CLAIM_READY=true
else
  echo "WARN: ${ATS_TENANT_ATTRIBUTE} attribute missing on the Keycloak user;" \
    "recruiter endpoints will 403 until --apply writes it" >&2
fi

# --- 2) permission-service writer identity --------------------------------
PERSONA_TOKEN_JSON="${TMP_DIR}/persona-token.json"
code="$(http_status POST \
  "${BASE_URL}/realms/${KC_REALM}/protocol/openid-connect/token" \
  "${PERSONA_TOKEN_JSON}" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=password' \
  --data-urlencode "client_id=${KC_ROPC_CLIENT_ID}" \
  --data-urlencode "client_secret@${KC_ROPC_CLIENT_SECRET_FILE}" \
  --data-urlencode "username@${PERSONA_USERNAME_FILE}" \
  --data-urlencode "password@${PERSONA_PASSWORD_FILE}")"
[[ "${code}" == "200" ]] || die "permission-writer-login-failed"
PERSONA_TOKEN="$(jq -r '.access_token // empty' "${PERSONA_TOKEN_JSON}")"
[[ -n "${PERSONA_TOKEN}" ]] || die "permission-writer-token-missing"
PERSONA_AUTH_CONFIG="${TMP_DIR}/persona-auth.curl"
write_bearer_config "${PERSONA_AUTH_CONFIG}" "${PERSONA_TOKEN}"

# --- 3) exact user-service record ------------------------------------------
USER_JSON="${TMP_DIR}/user.json"
code="$(curl -sS --max-time 20 -o "${USER_JSON}" -w '%{http_code}' --get \
  "${BASE_URL}/api/v1/users/by-email" \
  --config "${PERSONA_AUTH_CONFIG}" \
  --data-urlencode "email@${TARGET_EMAIL_FILE}" || printf '000')"
[[ "${code}" == "200" ]] || die "user-service-exact-lookup-failed"
PLATFORM_USER_ID="$(jq -r '.id // empty' "${USER_JSON}")"
[[ "${PLATFORM_USER_ID}" =~ ^[0-9]+$ ]] || die "user-service-numeric-id-missing"
[[ "$(jq -r '.email // empty | ascii_downcase' "${USER_JSON}")" == "${TARGET_EMAIL}" ]] \
  || die "user-service-identity-mismatch"
USER_SERVICE_MATCH=true

# --- 4) target role + granule boundary ------------------------------------
ROLES_JSON="${TMP_DIR}/roles.json"
code="$(http_status GET "${BASE_URL}/api/v1/roles" "${ROLES_JSON}" \
  --config "${PERSONA_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "permission-role-list-failed"
ROLE_MATCH_COUNT="$(jq --arg name "${PERMISSION_ROLE_NAME}" \
  '[(.items? // .)[]? | select(.name == $name)] | length' "${ROLES_JSON}")"
[[ "${ROLE_MATCH_COUNT}" == "1" ]] || die "permission-role-not-exactly-one"
ROLE_ID="$(jq -r --arg name "${PERMISSION_ROLE_NAME}" \
  '[(.items? // .)[]? | select(.name == $name)][0].id // empty' "${ROLES_JSON}")"
[[ "${ROLE_ID}" =~ ^[0-9]+$ ]] || die "permission-role-id-missing"
PERMISSION_ROLE_READY=true

GRANULES_JSON="${TMP_DIR}/granules.json"
code="$(http_status GET "${BASE_URL}/api/v1/roles/${ROLE_ID}/granules" "${GRANULES_JSON}" \
  --config "${PERSONA_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "permission-granule-preflight-failed"

# This script never creates the grant surface; it only joins a role that
# already carries it. If the module gate is absent the caller is wrong about
# which role provides ATS access.
jq -e --arg key "${REQUIRED_MODULE_KEY}" \
  'any((.granules? // .)[]?; .type == "MODULE" and .key == $key)' \
  "${GRANULES_JSON}" >/dev/null || die "required-ats-module-granule-missing"

# Fail-closed against role widening: refuse if the role gained any granule this
# script was not reviewed against, and refuse outright on destructive keys.
jq -e --argjson allowed "$(printf '%s\n' ${ALLOWED_GRANULE_KEYS} | jq -R . | jq -s .)" \
  'all((.granules? // .)[]?; .key as $k | $allowed | index($k) != null)' \
  "${GRANULES_JSON}" >/dev/null || die "role-carries-unreviewed-granule"
jq -e --argjson forbidden "$(printf '%s\n' ${FORBIDDEN_GRANULE_KEYS} | jq -R . | jq -s .)" \
  'all((.granules? // .)[]?; .key as $k | $forbidden | index($k) == null)' \
  "${GRANULES_JSON}" >/dev/null || die "role-carries-destructive-granule"
GRANULE_BOUNDARY_READY=true

# --- 5) membership (idempotent) -------------------------------------------
MEMBERS_JSON="${TMP_DIR}/members.json"
code="$(http_status GET "${BASE_URL}/api/v1/roles/${ROLE_ID}/members" "${MEMBERS_JSON}" \
  --config "${PERSONA_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "permission-membership-preflight-failed"
if jq -e --argjson userId "${PLATFORM_USER_ID}" \
  'any((.items? // .)[]?; (.userId // .id) == $userId)' "${MEMBERS_JSON}" >/dev/null; then
  ALREADY_MEMBER=true
  MEMBERSHIP_READY=true
  if [[ "${KEYCLOAK_TENANT_CLAIM_READY}" != "true" ]]; then
    STATUS="blocked"
    FAILURE_REASON="keycloak-ats-tenant-attribute-missing"
    write_result
    echo "BLOCKED: membership exists but ${ATS_TENANT_ATTRIBUTE} is missing; rerun with --apply" >&2
    exit 1
  fi
  STATUS="already-granted"
  write_result
  echo "OK: target already holds ${PERMISSION_ROLE_NAME}; no mutation performed"
  exit 0
fi

if [[ "${MODE}" == "dry-run" ]]; then
  STATUS="ready"
  write_result
  echo "OK: dry-run preflights passed; rerun with --apply to write the membership"
  exit 0
fi

MEMBER_BODY="${TMP_DIR}/member.json"
jq -n --argjson userId "${PLATFORM_USER_ID}" '{userIds: [$userId]}' > "${MEMBER_BODY}"
MUTATION_RESPONSE="${TMP_DIR}/mutation-response.json"
code="$(http_status POST "${BASE_URL}/api/v1/roles/${ROLE_ID}/members" "${MUTATION_RESPONSE}" \
  --config "${PERSONA_AUTH_CONFIG}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${MEMBER_BODY}")"
[[ "${code}" == "200" || "${code}" == "201" || "${code}" == "204" ]] \
  || die "permission-membership-write-failed"

MEMBERS_AFTER_JSON="${TMP_DIR}/members-after.json"
code="$(http_status GET "${BASE_URL}/api/v1/roles/${ROLE_ID}/members" "${MEMBERS_AFTER_JSON}" \
  --config "${PERSONA_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "permission-membership-readback-failed"
jq -e --argjson userId "${PLATFORM_USER_ID}" \
  'any((.items? // .)[]?; (.userId // .id) == $userId)' "${MEMBERS_AFTER_JSON}" >/dev/null \
  || die "permission-membership-readback-mismatch"
MEMBERSHIP_READY=true

# Re-assert the boundary after the write: the mutation must not have altered the
# granule surface.
GRANULES_AFTER_JSON="${TMP_DIR}/granules-after.json"
code="$(http_status GET "${BASE_URL}/api/v1/roles/${ROLE_ID}/granules" "${GRANULES_AFTER_JSON}" \
  --config "${PERSONA_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "permission-granule-readback-failed"
jq -e -s '.[0] == .[1]' "${GRANULES_JSON}" "${GRANULES_AFTER_JSON}" >/dev/null \
  || die "granule-surface-changed-unexpectedly"

STATUS="applied"
write_result
echo "OK: membership applied and verified; artifact: ${OUT_PATH}"
