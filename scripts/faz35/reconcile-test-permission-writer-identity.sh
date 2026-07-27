#!/usr/bin/env bash
# Faz 35 TEST-only repair: give the D35 permission writer its own local user
# identity and the single ACCESS=MANAGE capability needed to provision the
# Etik Speak manager role. The historical user 1204 / d35-admin performance
# persona is deliberately left untouched.
#
# A2b.2 (2026-07-21, Faz 22 Sec KC hardening #2476): `client_id=frontend`
# (public + DAG=true) yerine confidential `smoke-client` ROPC pattern
# (A2c cutover'da frontend.DAG=false olacak). Writer persona d35-admin-persona
# smoke-client + smoke-runtime-v1 default scope (audience×6, userId claim) ile
# aynı REST çağrılarını yapabilir (permission-service audience valid). Ethics
# opt-in scope YOK — bu script scope=openid + default scope kullanıyor.
# Vault: kv/platform/keycloak/smoke-client (A2a substrate).

set -Eeuo pipefail
set +x
umask 077

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/faz35/lib-test-keycloak-binding.sh
source "${SCRIPT_DIR}/lib-test-keycloak-binding.sh"
# shellcheck source=scripts/faz35/lib-permission-role-catalog.sh
source "${SCRIPT_DIR}/lib-permission-role-catalog.sh"

OUT_PATH="${OUT_PATH:-/tmp/faz35-permission-writer-identity.json}"
readonly KUBE_CONTEXT="k3d-test"
readonly KUBE_NS="platform-test"
readonly OPENFGA_POD="deploy/meeting-service"
readonly OPENFGA_BASE="http://openfga:8080"
readonly PERMISSION_POD="deploy/permission-service"
readonly PG_CONTAINER="platform-pg-test"
readonly KC_CONTAINER="platform-kc-test"
readonly KC_BASE_URL="http://127.0.0.1:8082"
readonly KC_REALM="platform-test"
readonly KC_EXPECTED_ISSUER="https://testai.acik.com/realms/platform-test"
readonly KC_ADMIN_USER="admin"
readonly VAULT_CONTAINER="platform-vault-test"
readonly VAULT_INIT_FILE="${VAULT_INIT_FILE:-$HOME/bootstrap-drill/vault-init-test.json}"
readonly WRITER_VAULT_PATH="kv/platform/d35-3"
readonly WRITER_USER_ID="cbc9a869-1833-4d9c-beea-a9fa52fa851e"
readonly WRITER_USERNAME="d35-admin-persona"
readonly WRITER_EMAIL="d35-admin-persona@acik.com"
readonly WRITER_LOCAL_USER_ID="12"
readonly LEGACY_LOCAL_USER_ID="1204"
readonly PROVISIONER_ROLE_NAME="ETIK_SPEAK_PROVISIONER"

STATUS="running"
KC_ADMIN_PASSWORD_STDIN=false
FAILURE_REASON=""
LOCAL_PROFILE_EXACT=false
LOCAL_PROFILE_ACTIVATED=false
BOOTSTRAP_TUPLE_READY=false
PROVISIONER_ROLE_READY=false
KEYCLOAK_IDENTITY_ALIGNED=false
ACCESS_MANAGE_READY=false
ROLES_READ_READY=false
CREDENTIAL_PREFLIGHT_READY=false

usage() {
  cat <<'EOF'
Usage: reconcile-test-permission-writer-identity.sh [--out PATH] [--keycloak-admin-password-stdin]

Reconciles only the synthetic platform-test permission writer. It activates
the exact pre-provisioned local profile id 12, writes the bounded ACCESS
can_manage bootstrap tuple, materializes the equivalent dedicated permission
role, aligns Keycloak userId/subscriberId to 12 and verifies a fresh token.
Production and the historical user 1204 are never mutated.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT_PATH="$2"; shift 2 ;;
    --keycloak-admin-password-stdin) KC_ADMIN_PASSWORD_STDIN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for command_name in cmp curl docker find grep jq kubectl mktemp sed stat tr wc; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command missing: ${command_name}" >&2
    exit 2
  }
done

[[ "${KUBE_CONTEXT}" == "k3d-test" && "${KUBE_NS}" == "platform-test" ]] || {
  echo "ERROR: TEST Kubernetes target invariant failed" >&2
  exit 2
}
[[ "${PG_CONTAINER}" == "platform-pg-test" && "${KC_CONTAINER}" == "platform-kc-test" ]] || {
  echo "ERROR: TEST stateful target invariant failed" >&2
  exit 2
}
[[ "${WRITER_LOCAL_USER_ID}" != "${LEGACY_LOCAL_USER_ID}" ]] || {
  echo "ERROR: dedicated and historical local identities must differ" >&2
  exit 2
}

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

TMP_DIR="$(mktemp -d /tmp/faz35-writer-identity.XXXXXX)"
mkdir -p "$(dirname "${OUT_PATH}")"

write_result() {
  jq -n \
    --arg status "${STATUS}" \
    --arg failureReason "${FAILURE_REASON}" \
    --argjson localProfileExact "${LOCAL_PROFILE_EXACT}" \
    --argjson localProfileActivated "${LOCAL_PROFILE_ACTIVATED}" \
    --argjson bootstrapTupleReady "${BOOTSTRAP_TUPLE_READY}" \
    --argjson provisionerRoleReady "${PROVISIONER_ROLE_READY}" \
    --argjson keycloakIdentityAligned "${KEYCLOAK_IDENTITY_ALIGNED}" \
    --argjson accessManageReady "${ACCESS_MANAGE_READY}" \
    --argjson rolesReadReady "${ROLES_READ_READY}" \
    --argjson credentialPreflightReady "${CREDENTIAL_PREFLIGHT_READY}" '
    {
      schemaVersion: "faz35.permissionWriterIdentityReconciliation.v1",
      mode: "test-only-reconcile",
      status: $status,
      failureReason: (if $failureReason == "" then null else $failureReason end),
      permissionWriter: {
        exactLocalProfile: $localProfileExact,
        localProfileActivated: $localProfileActivated,
        bootstrapTupleReady: $bootstrapTupleReady,
        dedicatedProvisionerRoleReady: $provisionerRoleReady,
        keycloakIdentityAligned: $keycloakIdentityAligned,
        credentialPreflightReady: $credentialPreflightReady,
        accessManageReady: $accessManageReady,
        rolesReadReady: $rolesReadReady
      },
      boundaries: {
        environment: "platform-test",
        productionMutation: false,
        historicalUser1204Mutation: false,
        rawCredentialIncluded: false,
        rawTokenIncluded: false
      }
    }' > "${OUT_PATH}"
}

cleanup() {
  find "${TMP_DIR}" -type f -delete 2>/dev/null || true
  find "${TMP_DIR}" -depth -type d -empty -delete 2>/dev/null || true
  unset KC_ADMIN_PASSWORD KC_ADMIN_TOKEN WRITER_TOKEN ROOT_TOKEN WRITER_USERNAME_LIVE WRITER_PASSWORD
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
  local method="$1" url="$2" output="$3"
  shift 3
  curl -sS --max-time 20 -o "${output}" -w '%{http_code}' -X "${method}" "${url}" "$@" || printf '000'
}

write_bearer_config() {
  local output="$1" token="$2"
  printf 'header = "Authorization: Bearer %s"\n' "${token}" > "${output}"
  chmod 600 "${output}"
}

ke() {
  kubectl --request-timeout=15s --context "${KUBE_CONTEXT}" -n "${KUBE_NS}" "$@"
}

pod_post() {
  local endpoint="$1"
  ke exec -i "${OPENFGA_POD}" -- curl -sS --max-time 15 -w '\n%{http_code}' \
    -X POST "${endpoint}" -H 'Content-Type: application/json' -d @-
}

validate_secret_file() {
  local path="$1" label="$2"
  [[ -r "${path}" && -f "${path}" && ! -L "${path}" ]] \
    || die "${label}-missing-or-unsafe"
  [[ "$(stat -c '%u' "${path}")" == "$(id -u)" && "$(stat -c '%a' "${path}")" == "600" ]] \
    || die "${label}-ownership-or-mode-invalid"
}

validate_secret_file "${VAULT_INIT_FILE}" "vault-init-file"
[[ -n "${KC_ADMIN_PASSWORD:-}" ]] || die "keycloak-admin-password-missing"

# The live TEST user-service still uses public.users. Require the exact
# auto-provisioned passive/active synthetic row and refuse every other shape.
docker exec "${PG_CONTAINER}" psql -U postgres -d users_db -v ON_ERROR_STOP=1 \
  -At -F '|' -c \
  "SELECT id,name,email,role,enabled,company_id,version
     FROM public.users
    WHERE id=${WRITER_LOCAL_USER_ID}
      AND lower(email)=lower('${WRITER_EMAIL}')" > "${TMP_DIR}/local-profile.txt" \
  || die "writer-local-profile-read-failed"
[[ "$(wc -l < "${TMP_DIR}/local-profile.txt" | tr -d ' ')" == "1" ]] \
  || die "writer-local-profile-not-exactly-one"
IFS='|' read -r local_id local_name local_email local_role local_enabled local_company local_version \
  < "${TMP_DIR}/local-profile.txt"
[[ "${local_id}" == "${WRITER_LOCAL_USER_ID}" \
   && "${local_name}" == "D35 Admin Persona" \
   && "${local_email}" == "${WRITER_EMAIL}" \
   && "${local_role}" == "USER" \
   && -z "${local_company}" \
   && "${local_version}" =~ ^[0-9]+$ \
   && ( "${local_enabled}" == "t" || "${local_enabled}" == "f" ) ]] \
  || die "writer-local-profile-shape-mismatch"
LOCAL_PROFILE_EXACT=true

legacy_collision_count="$(docker exec "${PG_CONTAINER}" psql -U postgres -d users_db \
  -v ON_ERROR_STOP=1 -At -c \
  "SELECT count(*) FROM public.users
    WHERE id=${LEGACY_LOCAL_USER_ID} AND lower(email)=lower('${WRITER_EMAIL}')")" \
  || die "historical-user-collision-check-failed"
[[ "${legacy_collision_count}" == "0" ]] || die "historical-user-email-collision"

# Validate the immutable Keycloak subject before the first mutation. The
# legacy 1204 attributes are accepted only as the known pre-reconciliation
# state; reruns accept the dedicated id 12.
KC_ADMIN_PASSWORD_FILE="${TMP_DIR}/kc-admin-password"
printf '%s' "${KC_ADMIN_PASSWORD}" > "${KC_ADMIN_PASSWORD_FILE}"
KC_ADMIN_TOKEN_JSON="${TMP_DIR}/kc-admin-token.json"
code="$(http_status POST "${KC_BASE_URL}/realms/master/protocol/openid-connect/token" \
  "${KC_ADMIN_TOKEN_JSON}" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=password' \
  --data-urlencode 'client_id=admin-cli' \
  --data-urlencode "username=${KC_ADMIN_USER}" \
  --data-urlencode "password@${KC_ADMIN_PASSWORD_FILE}")"
[[ "${code}" == "200" ]] || die "keycloak-admin-login-failed"
KC_ADMIN_TOKEN="$(jq -r '.access_token // empty' "${KC_ADMIN_TOKEN_JSON}")"
[[ -n "${KC_ADMIN_TOKEN}" ]] || die "keycloak-admin-token-missing"
KC_AUTH_CONFIG="${TMP_DIR}/kc-auth.curl"
write_bearer_config "${KC_AUTH_CONFIG}" "${KC_ADMIN_TOKEN}"

KC_WRITER_JSON="${TMP_DIR}/kc-writer.json"
code="$(http_status GET "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${WRITER_USER_ID}" \
  "${KC_WRITER_JSON}" --config "${KC_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "keycloak-writer-read-failed"
jq -e \
  --arg id "${WRITER_USER_ID}" \
  --arg username "${WRITER_USERNAME}" \
  --arg email "${WRITER_EMAIL}" \
  --arg dedicated "${WRITER_LOCAL_USER_ID}" \
  --arg legacy "${LEGACY_LOCAL_USER_ID}" '
    .id == $id and .username == $username and .email == $email and
    .enabled == true and (.requiredActions // []) == [] and
    ((.attributes.userId == [$legacy] and .attributes.subscriberId == [$legacy]) or
     (.attributes.userId == [$dedicated] and .attributes.subscriberId == [$dedicated]))
  ' "${KC_WRITER_JSON}" >/dev/null || die "keycloak-writer-precondition-mismatch"

# Prove the Vault-held credential against the immutable writer subject before
# any Keycloak, local-user, OpenFGA or permission mutation. The credential-only
# repair step is intentionally defense in depth; this script is independently
# fail closed and does not trust caller order or a caller-authored receipt.
ROOT_TOKEN="$(jq -r '.root_token // empty' "${VAULT_INIT_FILE}")"
[[ -n "${ROOT_TOKEN}" ]] || die "vault-root-token-missing"
{
  printf '%s\n' "${ROOT_TOKEN}"
} | docker exec -i "${VAULT_CONTAINER}" sh -c '
  IFS= read -r VAULT_TOKEN
  export VAULT_TOKEN
  vault kv get -format=json "$1"
' sh "${WRITER_VAULT_PATH}" > "${TMP_DIR}/writer-vault.json" 2>/dev/null \
  || die "writer-vault-read-failed"
jq -e --arg username "${WRITER_USERNAME}" '
  .data.data.admin_persona_username == $username and
  (.data.data.admin_persona_password | type == "string" and length > 0)
' "${TMP_DIR}/writer-vault.json" >/dev/null || die "writer-vault-record-mismatch"
printf '%s' "${WRITER_USERNAME}" > "${TMP_DIR}/writer.username"
jq -j '.data.data.admin_persona_password' "${TMP_DIR}/writer-vault.json" \
  > "${TMP_DIR}/writer.password"
chmod 600 "${TMP_DIR}/writer.username" "${TMP_DIR}/writer.password"
unset ROOT_TOKEN

# A2b.2 (2026-07-21) — smoke-client secret fetch (Vault kv/platform/keycloak/smoke-client)
SMOKE_CLIENT_SECRET_FILE="${TMP_DIR}/smoke-client-secret"
SMOKE_VAULT_ROOT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "${VAULT_INIT_FILE:-$HOME/bootstrap-drill/vault-init-test.json}" 2>/dev/null || true)"
[[ -n "${SMOKE_VAULT_ROOT}" ]] || die "smoke-client-vault-root-token-missing"
docker exec -e VAULT_TOKEN="${SMOKE_VAULT_ROOT}" platform-vault-test \
  vault kv get -field=client_secret kv/platform/keycloak/smoke-client > "${SMOKE_CLIENT_SECRET_FILE}" \
  || die "smoke-client-secret-fetch-failed"
chmod 0600 "${SMOKE_CLIENT_SECRET_FILE}"
SMOKE_VAULT_ROOT=""

code="$(http_status POST "${KC_BASE_URL}/realms/${KC_REALM}/protocol/openid-connect/token" \
  "${TMP_DIR}/writer-credential-preflight-token.json" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=password' \
  --data-urlencode 'client_id=smoke-client' \
  --data-urlencode "client_secret@${SMOKE_CLIENT_SECRET_FILE}" \
  --data-urlencode 'scope=openid' \
  --data-urlencode "username@${TMP_DIR}/writer.username" \
  --data-urlencode "password@${TMP_DIR}/writer.password")"
[[ "${code}" == "200" ]] || die "writer-credential-preflight-login-failed"
WRITER_TOKEN="$(jq -r '.access_token // empty' "${TMP_DIR}/writer-credential-preflight-token.json")"
[[ -n "${WRITER_TOKEN}" ]] || die "writer-credential-preflight-token-missing"
write_bearer_config "${TMP_DIR}/writer-credential-preflight-auth.curl" "${WRITER_TOKEN}"
unset WRITER_TOKEN
code="$(http_status GET \
  "${KC_BASE_URL}/realms/${KC_REALM}/protocol/openid-connect/userinfo" \
  "${TMP_DIR}/writer-credential-preflight-userinfo.json" \
  --config "${TMP_DIR}/writer-credential-preflight-auth.curl")"
[[ "${code}" == "200" ]] || die "writer-credential-preflight-userinfo-failed"
jq -e --arg subject "${WRITER_USER_ID}" '.sub == $subject' \
  "${TMP_DIR}/writer-credential-preflight-userinfo.json" >/dev/null \
  || die "writer-credential-preflight-subject-mismatch"
CREDENTIAL_PREFLIGHT_READY=true

# Keep the complete non-attribute identity profile immutable. Only the two
# numeric correlation attributes are allowed to change in this reconciliation.
jq -S '{id,username,email,firstName,lastName,emailVerified,enabled,requiredActions}' \
  "${KC_WRITER_JSON}" > "${TMP_DIR}/profile-before.json"
jq -S '.attributes // {}' "${KC_WRITER_JSON}" > "${TMP_DIR}/attributes-before.json"
jq --arg local "${WRITER_LOCAL_USER_ID}" \
  '.userId=[$local] | .subscriberId=[$local]' \
  "${TMP_DIR}/attributes-before.json" > "${TMP_DIR}/attributes-expected.json"
if ! cmp -s "${TMP_DIR}/attributes-before.json" "${TMP_DIR}/attributes-expected.json"; then
  jq --slurpfile attrs "${TMP_DIR}/attributes-expected.json" '
    {
      username,enabled,firstName,lastName,email,emailVerified,requiredActions,
      attributes:$attrs[0]
    }
  ' "${KC_WRITER_JSON}" > "${TMP_DIR}/kc-attributes-update.json"
  code="$(http_status PUT "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${WRITER_USER_ID}" \
    "${TMP_DIR}/kc-update-response.json" --config "${KC_AUTH_CONFIG}" \
    -H 'Content-Type: application/json' --data-binary "@${TMP_DIR}/kc-attributes-update.json")"
  [[ "${code}" == "204" ]] || die "keycloak-writer-identity-update-failed"
fi
code="$(http_status GET "${KC_BASE_URL}/admin/realms/${KC_REALM}/users/${WRITER_USER_ID}" \
  "${TMP_DIR}/kc-writer-after.json" --config "${KC_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "keycloak-writer-identity-readback-failed"
jq -S '.attributes // {}' "${TMP_DIR}/kc-writer-after.json" \
  | cmp -s "${TMP_DIR}/attributes-expected.json" - \
  || die "keycloak-writer-identity-readback-mismatch"
jq -S '{id,username,email,firstName,lastName,emailVerified,enabled,requiredActions}' \
  "${TMP_DIR}/kc-writer-after.json" | cmp -s "${TMP_DIR}/profile-before.json" - \
  || die "keycloak-writer-profile-changed"
KEYCLOAK_IDENTITY_ALIGNED=true

# Activate only the exact synthetic row. The transaction verifies its
# postcondition; no other user or column is changed.
if [[ "${local_enabled}" == "f" ]]; then
  activation_count="$(docker exec "${PG_CONTAINER}" psql -U postgres -d users_db \
    -v ON_ERROR_STOP=1 -At -c \
    "WITH changed AS (
       UPDATE public.users
          SET enabled=true, version=version+1
        WHERE id=${WRITER_LOCAL_USER_ID}
          AND lower(email)=lower('${WRITER_EMAIL}')
          AND role='USER' AND enabled=false
       RETURNING id
     ) SELECT count(*) FROM changed;")" || die "writer-local-profile-activation-failed"
  [[ "${activation_count}" == "1" ]] \
    || die "writer-local-profile-activation-count-mismatch"
fi
post_enabled="$(docker exec "${PG_CONTAINER}" psql -U postgres -d users_db \
  -v ON_ERROR_STOP=1 -At -c \
  "SELECT enabled FROM public.users
    WHERE id=${WRITER_LOCAL_USER_ID} AND lower(email)=lower('${WRITER_EMAIL}')")" \
  || die "writer-local-profile-activation-readback-failed"
[[ "${post_enabled}" == "t" ]] || die "writer-local-profile-not-active"
LOCAL_PROFILE_ACTIVATED=true

# Resolve the shared TEST OpenFGA binding from the running permission-service.
# IDs are non-secret runtime identifiers; secret values are never emitted.
store_id="$(ke exec "${PERMISSION_POD}" -- sh -c "printf %s \"\${ERP_OPENFGA_STORE_ID}\"")" \
  || die "shared-openfga-store-id-unresolved"
model_id="$(ke exec "${PERMISSION_POD}" -- sh -c "printf %s \"\${ERP_OPENFGA_MODEL_ID}\"")" \
  || die "shared-openfga-model-id-unresolved"
[[ "${store_id}" =~ ^[0-9A-HJKMNP-TV-Z]{26}$ && "${model_id}" =~ ^[0-9A-HJKMNP-TV-Z]{26}$ ]] \
  || die "shared-openfga-binding-invalid"

# The bootstrap tuple is already the final least-privilege capability. The
# dedicated role created below becomes its database justification and future
# reconciliation owner; no temporary ADMIN role is introduced.
jq -nc \
  --arg model "${model_id}" \
  --arg user "user:${WRITER_LOCAL_USER_ID}" '
  {authorization_model_id:$model,writes:{tuple_keys:[{
    user:$user,relation:"can_manage",object:"module:ACCESS"
  }]}}' > "${TMP_DIR}/bootstrap-write.json"
response="$(pod_post "${OPENFGA_BASE}/stores/${store_id}/write" \
  < "${TMP_DIR}/bootstrap-write.json")" || die "shared-openfga-bootstrap-write-failed"
code="${response##*$'\n'}"
body="${response%$'\n'*}"
case "${code}" in
  200|201) ;;
  400|409) printf '%s' "${body}" | grep -qi 'already exist' \
    || die "shared-openfga-bootstrap-write-rejected" ;;
  *) die "shared-openfga-bootstrap-write-http-${code}" ;;
esac
jq -nc \
  --arg model "${model_id}" \
  --arg user "user:${WRITER_LOCAL_USER_ID}" '
  {authorization_model_id:$model,tuple_key:{
    user:$user,relation:"can_manage",object:"module:ACCESS"
  }}' > "${TMP_DIR}/bootstrap-check.json"
response="$(pod_post "${OPENFGA_BASE}/stores/${store_id}/check" \
  < "${TMP_DIR}/bootstrap-check.json")" || die "shared-openfga-bootstrap-check-failed"
code="${response##*$'\n'}"
body="${response%$'\n'*}"
[[ "${code}" == "200" && "$(printf '%s' "${body}" | jq -r '.allowed // false')" == "true" ]] \
  || die "shared-openfga-bootstrap-check-denied"
BOOTSTRAP_TUPLE_READY=true

# Reuse the preflight-proven credential, then prove the bounded tuple opens
# only the canonical role API after identity alignment.
mint_writer_token() {
  local output="$1" token code
  # A2b.2 — smoke-client + smoke-runtime-v1 default scope (audience×6 valid)
  code="$(http_status POST "${KC_BASE_URL}/realms/${KC_REALM}/protocol/openid-connect/token" \
    "${output}" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'grant_type=password' \
    --data-urlencode 'client_id=smoke-client' \
    --data-urlencode "client_secret@${SMOKE_CLIENT_SECRET_FILE}" \
    --data-urlencode "username@${TMP_DIR}/writer.username" \
    --data-urlencode "password@${TMP_DIR}/writer.password")"
  [[ "${code}" == "200" ]] || return 1
  token="$(jq -r '.access_token // empty' "${output}")"
  [[ -n "${token}" ]] || return 1
  WRITER_TOKEN="${token}"
}

mint_writer_token "${TMP_DIR}/writer-token-before.json" || die "writer-token-mint-failed"
WRITER_AUTH_CONFIG="${TMP_DIR}/writer-auth-before.curl"
write_bearer_config "${WRITER_AUTH_CONFIG}" "${WRITER_TOKEN}"
unset WRITER_TOKEN
code="$(http_status GET 'https://testai.acik.com/api/v1/roles' \
  "${TMP_DIR}/roles.json" --config "${WRITER_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "writer-bootstrap-role-read-denied"
faz35_validate_complete_role_catalog "${TMP_DIR}/roles.json" \
  || die "writer-role-catalog-incomplete-or-paged"

role_count="$(jq --arg name "${PROVISIONER_ROLE_NAME}" '[.items[]? | select(.name == $name)] | length' \
  "${TMP_DIR}/roles.json")"
[[ "${role_count}" == "0" || "${role_count}" == "1" ]] \
  || die "writer-provisioner-role-not-unique"
role_id="$(jq -r --arg name "${PROVISIONER_ROLE_NAME}" \
  '[.items[]? | select(.name == $name)][0].id // empty' "${TMP_DIR}/roles.json")"
if [[ -z "${role_id}" ]]; then
  jq -n --arg name "${PROVISIONER_ROLE_NAME}" \
    '{name:$name,description:"Faz 35 TEST-only least-privilege permission writer"}' \
    > "${TMP_DIR}/create-role.json"
  code="$(http_status POST 'https://testai.acik.com/api/v1/roles' \
    "${TMP_DIR}/create-role-response.json" --config "${WRITER_AUTH_CONFIG}" \
    -H 'Content-Type: application/json' --data-binary "@${TMP_DIR}/create-role.json")"
  [[ "${code}" == "201" ]] || die "writer-provisioner-role-create-failed"
  role_id="$(jq -r '.id // empty' "${TMP_DIR}/create-role-response.json")"
fi
[[ "${role_id}" =~ ^[0-9]+$ ]] || die "writer-provisioner-role-id-invalid"

code="$(http_status GET "https://testai.acik.com/api/v1/roles/${role_id}/granules" \
  "${TMP_DIR}/granules-before.json" --config "${WRITER_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "writer-provisioner-granule-preflight-failed"
jq -e '
  (.granules | length) <= 1 and
  all(.granules[]?; .type == "MODULE" and .key == "ACCESS" and .grant == "MANAGE")
' "${TMP_DIR}/granules-before.json" >/dev/null \
  || die "writer-provisioner-granule-conflict"
code="$(http_status GET "https://testai.acik.com/api/v1/roles/${role_id}/members" \
  "${TMP_DIR}/members-before.json" --config "${WRITER_AUTH_CONFIG}")"
[[ "${code}" == "200" ]] || die "writer-provisioner-member-preflight-failed"
jq -e --argjson writer "${WRITER_LOCAL_USER_ID}" '
  length <= 1 and all(.[]?; .userId == $writer)
' "${TMP_DIR}/members-before.json" >/dev/null \
  || die "writer-provisioner-member-conflict"

jq -n '{permissions:[{type:"MODULE",key:"ACCESS",grant:"MANAGE"}]}' \
  > "${TMP_DIR}/provisioner-granules.json"
code="$(http_status PUT "https://testai.acik.com/api/v1/roles/${role_id}/granules" \
  "${TMP_DIR}/mutation.json" --config "${WRITER_AUTH_CONFIG}" \
  -H 'Content-Type: application/json' --data-binary "@${TMP_DIR}/provisioner-granules.json")"
[[ "${code}" == "200" ]] || die "writer-provisioner-granule-write-failed"
if [[ "$(jq 'length' "${TMP_DIR}/members-before.json")" == "0" ]]; then
  jq -n --argjson writer "${WRITER_LOCAL_USER_ID}" '{userIds:[$writer]}' \
    > "${TMP_DIR}/provisioner-member.json"
  code="$(http_status POST "https://testai.acik.com/api/v1/roles/${role_id}/members" \
    "${TMP_DIR}/mutation.json" --config "${WRITER_AUTH_CONFIG}" \
    -H 'Content-Type: application/json' --data-binary "@${TMP_DIR}/provisioner-member.json")"
  [[ "${code}" == "200" ]] || die "writer-provisioner-member-write-failed"
fi

code="$(http_status GET "https://testai.acik.com/api/v1/roles/${role_id}/granules" \
  "${TMP_DIR}/granules-after.json" --config "${WRITER_AUTH_CONFIG}")"
if [[ "${code}" != "200" ]] || ! jq -e \
    '.granules == [{type:"MODULE",key:"ACCESS",grant:"MANAGE"}]' \
    "${TMP_DIR}/granules-after.json" >/dev/null; then
  die "writer-provisioner-granule-readback-mismatch"
fi
code="$(http_status GET "https://testai.acik.com/api/v1/roles/${role_id}/members" \
  "${TMP_DIR}/members-after.json" --config "${WRITER_AUTH_CONFIG}")"
if [[ "${code}" != "200" ]] || ! jq -e --argjson writer "${WRITER_LOCAL_USER_ID}" \
    'length == 1 and .[0].userId == $writer' "${TMP_DIR}/members-after.json" >/dev/null; then
  die "writer-provisioner-member-readback-mismatch"
fi
PROVISIONER_ROLE_READY=true

# A fresh post-alignment token must resolve as user 12, expose only the
# dedicated ACCESS=MANAGE capability relevant here, and pass role reads.
mint_writer_token "${TMP_DIR}/writer-token-after.json" || die "writer-token-remint-failed"
WRITER_AUTH_AFTER="${TMP_DIR}/writer-auth-after.curl"
write_bearer_config "${WRITER_AUTH_AFTER}" "${WRITER_TOKEN}"
unset WRITER_TOKEN
code="$(http_status GET 'https://testai.acik.com/api/v1/authz/me' \
  "${TMP_DIR}/authz-after.json" --config "${WRITER_AUTH_AFTER}")"
[[ "${code}" == "200" ]] || die "writer-authz-readback-failed"
jq -e --arg id "${WRITER_LOCAL_USER_ID}" --arg role "${PROVISIONER_ROLE_NAME}" '
  .userId == $id and .subscriberId == ($id | tonumber) and
  .superAdmin == false and
  ((.roles // []) | sort) == [$role] and
  (.modules // {}) == {ACCESS:"MANAGE"} and
  ((.allowedModules // []) | sort) == ["ACCESS"] and
  ((.permissions // []) | sort) == ["ACCESS"] and
  (.actions // {}) == {} and (.reports // {}) == {} and
  (.scopes // []) == [] and (.allowedScopes // []) == []
' "${TMP_DIR}/authz-after.json" >/dev/null || die "writer-access-manage-not-authoritative"
ACCESS_MANAGE_READY=true
code="$(http_status GET 'https://testai.acik.com/api/v1/roles' \
  "${TMP_DIR}/roles-after.json" --config "${WRITER_AUTH_AFTER}")"
[[ "${code}" == "200" ]] || die "writer-role-readback-denied"
faz35_validate_complete_role_catalog "${TMP_DIR}/roles-after.json" \
  || die "writer-role-catalog-readback-incomplete-or-paged"
ROLES_READ_READY=true

STATUS="ready"
write_result
echo "Permission writer: dedicated TEST identity and ACCESS=MANAGE provisioner role ready"
echo "FAZ35_PERMISSION_WRITER_LOCAL_USER_ID=${WRITER_LOCAL_USER_ID}"
echo "FAZ35_PERMISSION_WRITER_ROLE_ID=${role_id}"
