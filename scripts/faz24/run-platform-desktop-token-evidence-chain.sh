#!/usr/bin/env bash
#
# Faz 24 platform-desktop token + external recorder evidence chain.
#
# Runs on the staging-sw self-hosted runner. The script may mutate only the
# platform-test Keycloak realm: it converges the platform-desktop token mapper
# contract, temporarily enables direct access grants long enough to mint a
# bounded smoke token, creates a temporary smoke user, then restores and
# deletes all temporary state. It never prints token/password/admin material.
#
set -Eeuo pipefail
umask 077

SCHEMA_VERSION="faz24.platformDesktopTokenEvidenceChain.v1"
KC_REALM="${KC_REALM:-platform-test}"
KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
KC_ADMIN_USER="${KC_ADMIN_USER:-admin}"
KC_BASE_URL="${KC_BASE_URL:-http://127.0.0.1:8082}"
KC_INTERNAL_SERVER="${KC_INTERNAL_SERVER:-http://localhost:8080}"
KC_ADMIN_MODE_PREFERENCE="${KC_ADMIN_MODE_PREFERENCE:-rest}"
CLIENT_ID="${CLIENT_ID:-platform-desktop}"
RESOURCE_CLIENT_ID="${RESOURCE_CLIENT_ID:-audio-gateway-service}"
CAPABILITY_ROLE="${CAPABILITY_ROLE:-audio_record}"
BASE_URL="${BASE_URL:-https://testai.acik.com}"
EXPECTED_ISSUER="${EXPECTED_ISSUER:-https://testai.acik.com/realms/platform-test}"
RUN_EXTERNAL_SMOKE="${RUN_EXTERNAL_SMOKE:-1}"
RUN_MEETING_AI_ANALYZE_SMOKE="${RUN_MEETING_AI_ANALYZE_SMOKE:-0}"
SMOKE_CHUNK_FILE="${SMOKE_CHUNK_FILE:-}"
SMOKE_AUDIO_FORMAT="${SMOKE_AUDIO_FORMAT:-WAV}"
SMOKE_SAMPLE_RATE_HZ="${SMOKE_SAMPLE_RATE_HZ:-48000}"
SMOKE_CHANNELS="${SMOKE_CHANNELS:-1}"
MEETING_AI_ANALYZE_SOURCE_FILE="${MEETING_AI_ANALYZE_SOURCE_FILE:-}"
OUT_DIR="${OUT_DIR:-/tmp/faz24-platform-desktop-token-evidence}"
RUN_ID_SAFE="${GITHUB_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_ATTEMPT_SAFE="${GITHUB_RUN_ATTEMPT:-1}"
TEMP_USERNAME="${TEMP_USERNAME:-faz24-recorder-smoke-codex-${RUN_ID_SAFE}-${RUN_ATTEMPT_SAFE}}"
TEMP_EMAIL="${TEMP_EMAIL:-${TEMP_USERNAME}@testai.acik.com}"
TENANT_ID="${TENANT_ID:-1}"
COMPANY_ID="${COMPANY_ID:-1}"
PLATFORM_USER_ID="${PLATFORM_USER_ID:-990001}"
REQUIRED_ROLE="${REQUIRED_ROLE:-MEETING_ADMIN}"

if [[ "${KC_REALM}" != "platform-test" ]]; then
  echo "ERROR: KC_REALM must be platform-test for this test-only evidence chain" >&2
  exit 2
fi

mkdir -p "${OUT_DIR}"
TMP_DIR="$(mktemp -d "${OUT_DIR}/.tmp.XXXXXX")"
KCADM=(docker exec "${KC_CONTAINER}" /opt/keycloak/bin/kcadm.sh)

DIAG_JSON="${OUT_DIR}/faz24-platform-desktop-token-diagnostic.json"
TOKEN_CONTRACT_JSON="${OUT_DIR}/faz24-platform-desktop-token-contract.json"
SMOKE_JSON="${OUT_DIR}/faz24-external-recorder-smoke.json"
SMOKE_VERIFY_JSON="${OUT_DIR}/faz24-external-recorder-smoke.verify.json"
MEETING_AI_ANALYZE_JSON="${OUT_DIR}/faz24-meeting-ai-analyze-smoke.json"
MEETING_AI_ANALYZE_VERIFY_JSON="${OUT_DIR}/faz24-meeting-ai-analyze-smoke.verify.json"
CLIENT_BEFORE_JSON="${TMP_DIR}/client-before.json"
CLIENT_AFTER_JSON="${TMP_DIR}/client-after.json"
USER_DIAG_JSON="${TMP_DIR}/user-diagnostic.json"
GRANT_ATTEMPTS_JSONL="${TMP_DIR}/grant-attempts.jsonl"
KC_SOURCE_JSON="${TMP_DIR}/keycloak-source.json"
ADMIN_PASS_FILE="${TMP_DIR}/kc-admin-password"
USER_PASS_FILE="${TMP_DIR}/smoke-user-password"
TOKEN_FILE="${TMP_DIR}/platform-desktop-token.jwt"
ADMIN_TOKEN_FILE="${TMP_DIR}/kc-admin-token.jwt"

: > "${GRANT_ATTEMPTS_JSONL}"
printf '{}\n' > "${CLIENT_BEFORE_JSON}"
printf '{}\n' > "${CLIENT_AFTER_JSON}"
printf '{}\n' > "${USER_DIAG_JSON}"
printf '{}\n' > "${KC_SOURCE_JSON}"

STATUS="running"
FAILURE_REASON=""
CLIENT_UUID=""
RESOURCE_CLIENT_UUID=""
TEMP_USER_ID=""
TEMP_USER_CREATED="false"
CLIENT_ROLE_ASSIGNED="false"
DIRECT_GRANTS_ORIGINAL=""
DIRECT_GRANTS_TOGGLED="false"
DIRECT_GRANTS_RESTORED="false"
TEMP_USER_DELETED="false"
TOKEN_FILE_REMOVED="false"
TOKEN_PRESENT="false"
TOKEN_CONTRACT_EXIT="not-run"
SMOKE_EXIT="not-run"
SMOKE_VERIFY_EXIT="not-run"
MEETING_AI_ANALYZE_EXIT="not-run"
MEETING_AI_ANALYZE_VERIFY_EXIT="not-run"
DIAGNOSTIC_WRITTEN="false"
CLEANUP_DONE="false"
KC_ADMIN_MODE=""

safe_error() {
  local value="${1:-}"
  printf '%s' "${value}" \
    | tr '\r\n' ' ' \
    | sed -E 's/[^A-Za-z0-9_ .,:;@+\/=-]/?/g' \
    | cut -c1-180
}

keycloak_admin_password_candidates() {
  printf '%s\t%s\n' \
    "canonical-home-repo" "/home/halil/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "canonical-home-compose" "/home/halil/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "runner-home-compose" "${HOME}/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "checkout-absolute" "${PWD}/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "checkout-relative" "host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "github-work" "/home/runner/work/platform-k8s-gitops/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "github-work-underscore" "/home/runner/_work/platform-k8s-gitops/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "opt-repo" "/opt/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "srv-repo" "/srv/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    | awk -F '\t' 'NF >= 2 && !seen[$2]++'
}

write_kc_source_diagnostic() {
  local selected="${1:-}"
  local selected_label="${2:-}"
  local candidates="${TMP_DIR}/kc-source-candidates.jsonl"
  : > "${candidates}"

  local docker_available=false
  local container_found=false
  local run_secret_readable=false
  local env_secret_readable=false
  local docker_socket_present=false
  local docker_socket_readable=false
  local docker_socket_writable=false
  local actions_secret_present=false
  local label candidate exists readable sudo_readable
  while IFS=$'\t' read -r label candidate; do
    exists=false
    readable=false
    sudo_readable=false
    [[ -e "${candidate}" ]] && exists=true
    [[ -r "${candidate}" ]] && readable=true
    if command -v sudo >/dev/null 2>&1 \
        && sudo -n test -r "${candidate}" >/dev/null 2>&1; then
      sudo_readable=true
    fi
    jq -n \
      --arg candidateLabel "${label}" \
      --argjson exists "${exists}" \
      --argjson readable "${readable}" \
      --argjson sudoReadable "${sudo_readable}" \
      '{"label": $candidateLabel, "exists": $exists, "readable": $readable, "sudoReadable": $sudoReadable}' >> "${candidates}"
  done < <(keycloak_admin_password_candidates)

  command -v docker >/dev/null 2>&1 && docker_available=true
  [[ -e /var/run/docker.sock ]] && docker_socket_present=true
  [[ -r /var/run/docker.sock ]] && docker_socket_readable=true
  [[ -w /var/run/docker.sock ]] && docker_socket_writable=true
  [[ -n "${KC_ADMIN_PASSWORD:-}" ]] && actions_secret_present=true
  if [[ "${docker_available}" == "true" ]]; then
    docker inspect "${KC_CONTAINER}" >/dev/null 2>&1 && container_found=true
    docker exec "${KC_CONTAINER}" sh -c 'test -r /run/secrets/kc_admin_password' >/dev/null 2>&1 \
      && run_secret_readable=true
    docker exec "${KC_CONTAINER}" sh -c 'p="${KEYCLOAK_ADMIN_PASSWORD_FILE:-}"; [ -n "$p" ] && test -r "$p"' >/dev/null 2>&1 \
      && env_secret_readable=true
  fi

  jq -n \
    --arg selectedSource "${selected}" \
    --arg selectedLabel "${selected_label}" \
    --arg container "${KC_CONTAINER}" \
    --arg realm "${KC_REALM}" \
    --argjson dockerAvailable "${docker_available}" \
    --argjson containerFound "${container_found}" \
    --argjson runSecretReadable "${run_secret_readable}" \
    --argjson envSecretReadable "${env_secret_readable}" \
    --argjson dockerSocketPresent "${docker_socket_present}" \
    --argjson dockerSocketReadable "${docker_socket_readable}" \
    --argjson dockerSocketWritable "${docker_socket_writable}" \
    --argjson actionsSecretPresent "${actions_secret_present}" \
    --slurpfile hostFileCandidates "${candidates}" \
    '{
      selectedSource: $selectedSource,
      selectedLabel: $selectedLabel,
      realm: $realm,
      container: $container,
      docker: {
        available: $dockerAvailable,
        containerFound: $containerFound,
        runSecretReadable: $runSecretReadable,
        envSecretReadable: $envSecretReadable,
        socketPresent: $dockerSocketPresent,
        socketReadable: $dockerSocketReadable,
        socketWritable: $dockerSocketWritable
      },
      actionsSecretPresent: $actionsSecretPresent,
      hostFileCandidates: $hostFileCandidates
    }' > "${KC_SOURCE_JSON}"
}

read_keycloak_admin_password() {
  if [[ -n "${KC_ADMIN_PASSWORD:-}" ]]; then
    printf '%s' "${KC_ADMIN_PASSWORD}" > "${ADMIN_PASS_FILE}"
    chmod 0600 "${ADMIN_PASS_FILE}"
    write_kc_source_diagnostic "actions-secret" "KC_TEST_ADMIN_PASSWORD"
    return 0
  fi

  if command -v docker >/dev/null 2>&1; then
    if docker exec "${KC_CONTAINER}" sh -c 'cat /run/secrets/kc_admin_password' \
        > "${ADMIN_PASS_FILE}" 2>/dev/null && [[ -s "${ADMIN_PASS_FILE}" ]]; then
      chmod 0600 "${ADMIN_PASS_FILE}"
      write_kc_source_diagnostic "docker-run-secret" "run-secret"
      return 0
    fi
    if docker exec "${KC_CONTAINER}" sh -c 'p="${KEYCLOAK_ADMIN_PASSWORD_FILE:-}"; [ -n "$p" ] && cat "$p"' \
        > "${ADMIN_PASS_FILE}" 2>/dev/null && [[ -s "${ADMIN_PASS_FILE}" ]]; then
      chmod 0600 "${ADMIN_PASS_FILE}"
      write_kc_source_diagnostic "docker-env-secret" "env-secret"
      return 0
    fi
  fi

  local label candidate
  while IFS=$'\t' read -r label candidate; do
    if [[ -r "${candidate}" ]]; then
      cp "${candidate}" "${ADMIN_PASS_FILE}"
      chmod 0600 "${ADMIN_PASS_FILE}"
      write_kc_source_diagnostic "host-file" "${label}"
      return 0
    fi
    if command -v sudo >/dev/null 2>&1 \
        && { sudo -n cat "${candidate}" 2>/dev/null | tee "${ADMIN_PASS_FILE}" >/dev/null; } \
        && [[ -s "${ADMIN_PASS_FILE}" ]]; then
      chmod 0600 "${ADMIN_PASS_FILE}"
      write_kc_source_diagnostic "host-file-sudo" "${label}"
      return 0
    fi
    : > "${ADMIN_PASS_FILE}"
  done < <(keycloak_admin_password_candidates)

  write_kc_source_diagnostic "" ""
  return 1
}

kcadm_login() {
  read_keycloak_admin_password || die "keycloak-admin-password-source-missing"
  local response_file="${TMP_DIR}/admin-token-response.json"
  local http_status token
  http_status="$(curl -sS -o "${response_file}" -w '%{http_code}' -X POST \
    "${KC_BASE_URL}/realms/master/protocol/openid-connect/token" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=admin-cli" \
    --data-urlencode "username=${KC_ADMIN_USER}" \
    --data-urlencode "password@${ADMIN_PASS_FILE}" || printf '000')"
  token="$(jq -r '.access_token // empty' "${response_file}" 2>/dev/null || true)"
  if [[ "${http_status}" == "200" && -n "${token}" ]]; then
    printf '%s' "${token}" > "${ADMIN_TOKEN_FILE}"
    chmod 0600 "${ADMIN_TOKEN_FILE}"
    KC_ADMIN_MODE="rest"
    return 0
  fi

  if [[ "${KC_ADMIN_MODE_PREFERENCE}" != "rest" ]] \
      && command -v docker >/dev/null 2>&1 \
      && docker inspect "${KC_CONTAINER}" >/dev/null 2>&1; then
    if "${KCADM[@]}" config credentials \
        --server "${KC_INTERNAL_SERVER}" \
        --realm master \
        --user "${KC_ADMIN_USER}" \
        --password "$(tr -d '\n' < "${ADMIN_PASS_FILE}")" >/dev/null 2>/dev/null; then
      KC_ADMIN_MODE="kcadm"
      return 0
    fi
  fi

  die "keycloak-admin-login-failed"
}

admin_auth_header() {
  printf 'Authorization: Bearer %s' "$(tr -d '\n' < "${ADMIN_TOKEN_FILE}")"
}

kc_admin_rest() {
  local method="$1"
  local path="$2"
  local out="$3"
  local body_file="${4:-}"
  local url="${KC_BASE_URL}/admin/realms/${KC_REALM}${path}"
  if [[ -n "${body_file}" ]]; then
    curl -sS -o "${out}" -w '%{http_code}' -X "${method}" \
      "${url}" \
      -H "$(admin_auth_header)" \
      -H "Content-Type: application/json" \
      --data-binary "@${body_file}" || printf '000'
  else
    curl -sS -o "${out}" -w '%{http_code}' -X "${method}" \
      "${url}" \
      -H "$(admin_auth_header)" || printf '000'
  fi
}

read_client_list_by_client_id() {
  local client_id="$1"
  local out="$2"
  if [[ "${KC_ADMIN_MODE}" == "kcadm" ]]; then
    "${KCADM[@]}" get clients -r "${KC_REALM}" -q "clientId=${client_id}" > "${out}"
    return $?
  fi

  local code
  code="$(kc_admin_rest GET "/clients?clientId=${client_id}" "${out}")"
  [[ "${code}" == "200" ]]
}

read_client_list() {
  local out="$1"
  read_client_list_by_client_id "${CLIENT_ID}" "${out}"
}

read_user_list() {
  local username="$1"
  local out="$2"
  if [[ "${KC_ADMIN_MODE}" == "kcadm" ]]; then
    "${KCADM[@]}" get users -r "${KC_REALM}" -q "username=${username}" -q exact=true > "${out}"
    return $?
  fi

  local code
  code="$(kc_admin_rest GET "/users?username=${username}&exact=true" "${out}")"
  [[ "${code}" == "200" ]]
}

capture_client_state() {
  local out="$1"
  local fail_reason="${2-keycloak-client-read-failed}"
  local raw="${TMP_DIR}/client-raw.json"
  if ! read_client_list "${raw}"; then
    printf '{}\n' > "${out}"
    [[ -z "${fail_reason}" ]] && return 1
    die "${fail_reason}"
  fi
  if ! jq -e --arg clientId "${CLIENT_ID}" '
    .[0] as $c
    | if $c == null then error("client not found") else
      {
        clientId: $c.clientId,
        enabled: ($c.enabled // null),
        publicClient: ($c.publicClient // null),
        directAccessGrantsEnabled: ($c.directAccessGrantsEnabled // null),
        standardFlowEnabled: ($c.standardFlowEnabled // null),
        serviceAccountsEnabled: ($c.serviceAccountsEnabled // null),
        protocolMappers: [
          ($c.protocolMappers // [])[]
          | {
              name,
              protocolMapper,
              includedCustomAudience: (.config["included.custom.audience"] // null),
              userAttribute: (.config["user.attribute"] // null),
              claimName: (.config["claim.name"] // null),
              accessTokenClaim: (.config["access.token.claim"] // null)
            }
        ],
        mapperSummary: {
          audienceAudioGatewayService: any(($c.protocolMappers // [])[]; .protocolMapper == "oidc-audience-mapper" and .config["included.custom.audience"] == "audio-gateway-service" and .config["access.token.claim"] == "true"),
          audienceMeetingService: any(($c.protocolMappers // [])[]; .protocolMapper == "oidc-audience-mapper" and .config["included.custom.audience"] == "meeting-service" and .config["access.token.claim"] == "true"),
          audienceFrontend: any(($c.protocolMappers // [])[]; .protocolMapper == "oidc-audience-mapper" and .config["included.custom.audience"] == "frontend" and .config["access.token.claim"] == "true"),
          tenantIdClaim: any(($c.protocolMappers // [])[]; .protocolMapper == "oidc-usermodel-attribute-mapper" and .config["user.attribute"] == "tenantId" and .config["claim.name"] == "tenantId" and .config["access.token.claim"] == "true"),
          companyIdClaim: any(($c.protocolMappers // [])[]; .protocolMapper == "oidc-usermodel-attribute-mapper" and .config["user.attribute"] == "companyId" and .config["claim.name"] == "companyId" and .config["access.token.claim"] == "true"),
          userIdClaim: any(($c.protocolMappers // [])[]; .protocolMapper == "oidc-usermodel-attribute-mapper" and .config["user.attribute"] == "userId" and .config["claim.name"] == "userId" and .config["access.token.claim"] == "true")
        }
      }
      end' "${raw}" > "${out}"; then
    printf '{}\n' > "${out}"
    [[ -z "${fail_reason}" ]] && return 1
    die "keycloak-platform-desktop-client-missing"
  fi
}

resolve_client_uuid() {
  local raw="${TMP_DIR}/client-id-raw.json"
  read_client_list "${raw}" \
    || die "keycloak-client-id-read-failed"
  CLIENT_UUID="$(jq -r '.[0].id // empty' "${raw}")"
  [[ -n "${CLIENT_UUID}" ]] || die "keycloak-platform-desktop-client-id-missing"
}

resolve_resource_client_uuid() {
  local raw="${TMP_DIR}/resource-client-id-raw.json"
  read_client_list_by_client_id "${RESOURCE_CLIENT_ID}" "${raw}" \
    || die "resource-client-read-failed:${RESOURCE_CLIENT_ID}"
  RESOURCE_CLIENT_UUID="$(jq -r '.[0].id // empty' "${raw}")"
  [[ -n "${RESOURCE_CLIENT_UUID}" ]] || die "resource-client-missing:${RESOURCE_CLIENT_ID}"
}

upsert_mapper() {
  local name="$1"
  local mapper_file="$2"
  local existing_id
  if [[ "${KC_ADMIN_MODE}" == "kcadm" ]]; then
    existing_id="$("${KCADM[@]}" get "clients/${CLIENT_UUID}/protocol-mappers/models" -r "${KC_REALM}" \
      | jq -r --arg name "${name}" '.[]? | select(.name == $name) | .id' | head -n 1)"
    if [[ -n "${existing_id}" ]]; then
      "${KCADM[@]}" update "clients/${CLIENT_UUID}/protocol-mappers/models/${existing_id}" \
        -r "${KC_REALM}" -f "${mapper_file}" >/dev/null \
        || die "keycloak-mapper-update-failed:${name}"
    else
      "${KCADM[@]}" create "clients/${CLIENT_UUID}/protocol-mappers/models" \
        -r "${KC_REALM}" -f "${mapper_file}" >/dev/null \
        || die "keycloak-mapper-create-failed:${name}"
    fi
  else
    local list_file="${TMP_DIR}/mappers-${name}.json"
    local out_file="${TMP_DIR}/mapper-${name}-out.json"
    local update_file="${TMP_DIR}/mapper-${name}-update.json"
    local code
    code="$(kc_admin_rest GET "/clients/${CLIENT_UUID}/protocol-mappers/models" "${list_file}")"
    [[ "${code}" == "200" ]] || die "keycloak-mapper-read-failed:${name}"
    existing_id="$(jq -r --arg name "${name}" '.[]? | select(.name == $name) | .id' "${list_file}" | head -n 1)"
    if [[ -n "${existing_id}" ]]; then
      jq --arg id "${existing_id}" '.id = $id' "${mapper_file}" > "${update_file}"
      code="$(kc_admin_rest PUT "/clients/${CLIENT_UUID}/protocol-mappers/models/${existing_id}" "${out_file}" "${update_file}")"
      [[ "${code}" == "204" ]] || die "keycloak-mapper-update-failed:${name}"
    else
      code="$(kc_admin_rest POST "/clients/${CLIENT_UUID}/protocol-mappers/models" "${out_file}" "${mapper_file}")"
      [[ "${code}" == "201" || "${code}" == "204" ]] || die "keycloak-mapper-create-failed:${name}"
    fi
  fi
}

write_audience_mapper() {
  local name="$1"
  local audience="$2"
  local out="${TMP_DIR}/${name}.json"
  jq -n \
    --arg name "${name}" \
    --arg audience "${audience}" \
    '{
      name: $name,
      protocol: "openid-connect",
      protocolMapper: "oidc-audience-mapper",
      config: {
        "included.custom.audience": $audience,
        "access.token.claim": "true",
        "id.token.claim": "false"
      }
    }' > "${out}"
  printf '%s' "${out}"
}

write_user_attribute_mapper() {
  local claim="$1"
  local out="${TMP_DIR}/claim-${claim}.json"
  jq -n \
    --arg claim "${claim}" \
    '{
      name: $claim,
      protocol: "openid-connect",
      protocolMapper: "oidc-usermodel-attribute-mapper",
      config: {
        "user.attribute": $claim,
        "claim.name": $claim,
        "jsonType.label": "String",
        "access.token.claim": "true",
        "id.token.claim": "false",
        "userinfo.token.claim": "true",
        "multivalued": "false",
        "aggregate.attrs": "false"
      }
    }' > "${out}"
  printf '%s' "${out}"
}

converge_platform_desktop_mappers() {
  upsert_mapper "audience-audio-gateway-service" "$(write_audience_mapper "audience-audio-gateway-service" "audio-gateway-service")"
  upsert_mapper "audience-meeting-service" "$(write_audience_mapper "audience-meeting-service" "meeting-service")"
  upsert_mapper "audience-frontend" "$(write_audience_mapper "audience-frontend" "frontend")"
  upsert_mapper "tenantId" "$(write_user_attribute_mapper "tenantId")"
  upsert_mapper "companyId" "$(write_user_attribute_mapper "companyId")"
  upsert_mapper "userId" "$(write_user_attribute_mapper "userId")"
}

assign_capability_role() {
  resolve_resource_client_uuid
  if [[ "${KC_ADMIN_MODE}" == "kcadm" ]]; then
    "${KCADM[@]}" get "clients/${RESOURCE_CLIENT_UUID}/roles/${CAPABILITY_ROLE}" -r "${KC_REALM}" >/dev/null \
      || die "required-client-role-missing:${RESOURCE_CLIENT_ID}/${CAPABILITY_ROLE}"
    "${KCADM[@]}" add-roles -r "${KC_REALM}" --uusername "${TEMP_USERNAME}" \
      --cclientid "${RESOURCE_CLIENT_ID}" --rolename "${CAPABILITY_ROLE}" >/dev/null \
      || die "required-client-role-assign-failed:${RESOURCE_CLIENT_ID}/${CAPABILITY_ROLE}"
  else
    local role_file="${TMP_DIR}/required-client-role.json"
    local role_assign_file="${TMP_DIR}/required-client-role-assign.json"
    local role_assign_out="${TMP_DIR}/required-client-role-assign.out"
    local code
    code="$(kc_admin_rest GET "/clients/${RESOURCE_CLIENT_UUID}/roles/${CAPABILITY_ROLE}" "${role_file}")"
    [[ "${code}" == "200" ]] || die "required-client-role-missing:${RESOURCE_CLIENT_ID}/${CAPABILITY_ROLE}"
    jq '[.]' "${role_file}" > "${role_assign_file}"
    code="$(kc_admin_rest POST "/users/${TEMP_USER_ID}/role-mappings/clients/${RESOURCE_CLIENT_UUID}" "${role_assign_out}" "${role_assign_file}")"
    [[ "${code}" == "204" ]] || die "required-client-role-assign-failed:${RESOURCE_CLIENT_ID}/${CAPABILITY_ROLE}"
  fi
  CLIENT_ROLE_ASSIGNED="true"
}

create_temp_user() {
  local existing lookup_file
  lookup_file="${TMP_DIR}/temp-user-lookup.json"
  read_user_list "${TEMP_USERNAME}" "${lookup_file}" \
    || die "temp-user-lookup-failed:${TEMP_USERNAME}"
  existing="$(jq -r '.[0].id // empty' "${lookup_file}")"
  [[ -z "${existing}" ]] || die "temp-user-already-exists:${TEMP_USERNAME}"

  local create_file="${TMP_DIR}/temp-user.json"
  jq -n \
    --arg username "${TEMP_USERNAME}" \
    --arg email "${TEMP_EMAIL}" \
    --arg tenantId "${TENANT_ID}" \
    --arg companyId "${COMPANY_ID}" \
    --arg userId "${PLATFORM_USER_ID}" \
    '{
      username: $username,
      enabled: true,
      emailVerified: true,
      email: $email,
      firstName: "Faz24",
      lastName: "RecorderSmoke",
      attributes: {
        tenantId: [$tenantId],
        companyId: [$companyId],
        userId: [$userId],
        tenant_id: [$tenantId],
        company_id: [$companyId],
        org_id: [$tenantId]
      }
    }' > "${create_file}"
  if [[ "${KC_ADMIN_MODE}" == "kcadm" ]]; then
    TEMP_USER_ID="$("${KCADM[@]}" create users -r "${KC_REALM}" -f "${create_file}" -i)"
  else
    local create_out="${TMP_DIR}/temp-user-create.out"
    local code
    code="$(kc_admin_rest POST "/users" "${create_out}" "${create_file}")"
    [[ "${code}" == "201" || "${code}" == "204" ]] || die "temp-user-create-failed"
    read_user_list "${TEMP_USERNAME}" "${lookup_file}" \
      || die "temp-user-created-lookup-failed:${TEMP_USERNAME}"
    TEMP_USER_ID="$(jq -r '.[0].id // empty' "${lookup_file}")"
  fi
  [[ -n "${TEMP_USER_ID}" ]] || die "temp-user-create-id-missing"
  TEMP_USER_CREATED="true"

  openssl rand -hex 24 | tr -d '\n' > "${USER_PASS_FILE}"
  chmod 0600 "${USER_PASS_FILE}"
  if [[ "${KC_ADMIN_MODE}" == "kcadm" ]]; then
    "${KCADM[@]}" set-password -r "${KC_REALM}" --userid "${TEMP_USER_ID}" \
      --new-password "$(cat "${USER_PASS_FILE}")" >/dev/null 2>/dev/null \
      || die "temp-user-set-password-failed"

    "${KCADM[@]}" get "roles/${REQUIRED_ROLE}" -r "${KC_REALM}" >/dev/null \
      || die "required-realm-role-missing:${REQUIRED_ROLE}"
    "${KCADM[@]}" add-roles -r "${KC_REALM}" --uusername "${TEMP_USERNAME}" --rolename "${REQUIRED_ROLE}" >/dev/null \
      || die "required-realm-role-assign-failed:${REQUIRED_ROLE}"
  else
    local reset_file="${TMP_DIR}/temp-user-reset-password.json"
    local reset_out="${TMP_DIR}/temp-user-reset-password.out"
    local role_file="${TMP_DIR}/required-role.json"
    local role_assign_file="${TMP_DIR}/required-role-assign.json"
    local role_assign_out="${TMP_DIR}/required-role-assign.out"
    local code
    jq -n --rawfile value "${USER_PASS_FILE}" \
      '{type:"password", value:$value, temporary:false}' > "${reset_file}"
    code="$(kc_admin_rest PUT "/users/${TEMP_USER_ID}/reset-password" "${reset_out}" "${reset_file}")"
    [[ "${code}" == "204" ]] || die "temp-user-set-password-failed"

    code="$(kc_admin_rest GET "/roles/${REQUIRED_ROLE}" "${role_file}")"
    [[ "${code}" == "200" ]] || die "required-realm-role-missing:${REQUIRED_ROLE}"
    jq '[.]' "${role_file}" > "${role_assign_file}"
    code="$(kc_admin_rest POST "/users/${TEMP_USER_ID}/role-mappings/realm" "${role_assign_out}" "${role_assign_file}")"
    [[ "${code}" == "204" ]] || die "required-realm-role-assign-failed:${REQUIRED_ROLE}"
  fi
  assign_capability_role
}

capture_user_diagnostic() {
  if [[ -z "${TEMP_USER_ID}" ]]; then
    printf '{}\n' > "${USER_DIAG_JSON}"
    return 0
  fi
  local user_json="${TMP_DIR}/user.json"
  local creds_json="${TMP_DIR}/credentials.json"
  local roles_json="${TMP_DIR}/roles.json"
  local client_roles_json="${TMP_DIR}/client-roles.json"
  printf '[]\n' > "${client_roles_json}"
  if [[ "${KC_ADMIN_MODE}" == "kcadm" ]]; then
    "${KCADM[@]}" get "users/${TEMP_USER_ID}" -r "${KC_REALM}" > "${user_json}" || true
    "${KCADM[@]}" get "users/${TEMP_USER_ID}/credentials" -r "${KC_REALM}" > "${creds_json}" || printf '[]\n' > "${creds_json}"
    "${KCADM[@]}" get "users/${TEMP_USER_ID}/role-mappings/realm" -r "${KC_REALM}" > "${roles_json}" || printf '[]\n' > "${roles_json}"
    if [[ -n "${RESOURCE_CLIENT_UUID}" ]]; then
      "${KCADM[@]}" get "users/${TEMP_USER_ID}/role-mappings/clients/${RESOURCE_CLIENT_UUID}" -r "${KC_REALM}" > "${client_roles_json}" \
        || printf '[]\n' > "${client_roles_json}"
    fi
  else
    local code
    code="$(kc_admin_rest GET "/users/${TEMP_USER_ID}" "${user_json}")"
    [[ "${code}" == "200" ]] || printf '{}\n' > "${user_json}"
    code="$(kc_admin_rest GET "/users/${TEMP_USER_ID}/credentials" "${creds_json}")"
    [[ "${code}" == "200" ]] || printf '[]\n' > "${creds_json}"
    code="$(kc_admin_rest GET "/users/${TEMP_USER_ID}/role-mappings/realm" "${roles_json}")"
    [[ "${code}" == "200" ]] || printf '[]\n' > "${roles_json}"
    if [[ -n "${RESOURCE_CLIENT_UUID}" ]]; then
      code="$(kc_admin_rest GET "/users/${TEMP_USER_ID}/role-mappings/clients/${RESOURCE_CLIENT_UUID}" "${client_roles_json}")"
      [[ "${code}" == "200" ]] || printf '[]\n' > "${client_roles_json}"
    fi
  fi
  jq -n \
    --slurpfile user "${user_json}" \
    --slurpfile creds "${creds_json}" \
    --slurpfile roles "${roles_json}" \
    --slurpfile clientRoles "${client_roles_json}" \
    --arg requiredRole "${REQUIRED_ROLE}" \
    --arg resourceClientId "${RESOURCE_CLIENT_ID}" \
    --arg capabilityRole "${CAPABILITY_ROLE}" \
    --argjson clientRoleAssigned "${CLIENT_ROLE_ASSIGNED}" \
    '($user[0] // {}) as $u
      | {
          username: ($u.username // null),
          enabled: ($u.enabled // null),
          emailVerified: ($u.emailVerified // null),
          requiredActions: ($u.requiredActions // []),
          attributesPresent: {
            tenantId: (($u.attributes.tenantId // []) | length > 0),
            companyId: (($u.attributes.companyId // []) | length > 0),
            userId: (($u.attributes.userId // []) | length > 0)
          },
          credentialTypes: [($creds[0] // [])[]? | .type],
          realmRolePresent: any(($roles[0] // [])[]?; .name == $requiredRole),
          clientRole: {
            resourceClientId: $resourceClientId,
            capabilityRole: $capabilityRole,
            assignedByScript: $clientRoleAssigned,
            present: any(($clientRoles[0] // [])[]?; .name == $capabilityRole)
          }
        }' > "${USER_DIAG_JSON}"
}

enable_direct_grants_temporarily() {
  DIRECT_GRANTS_ORIGINAL="$(jq -r '.directAccessGrantsEnabled // false' "${CLIENT_BEFORE_JSON}")"
  if [[ "${KC_ADMIN_MODE}" == "kcadm" ]]; then
    "${KCADM[@]}" update "clients/${CLIENT_UUID}" -r "${KC_REALM}" -s directAccessGrantsEnabled=true >/dev/null \
      || die "platform-desktop-direct-grants-enable-failed"
  else
    local client_file="${TMP_DIR}/client-direct-grants.json"
    local update_file="${TMP_DIR}/client-direct-grants-update.json"
    local update_out="${TMP_DIR}/client-direct-grants-update.out"
    local code
    code="$(kc_admin_rest GET "/clients/${CLIENT_UUID}" "${client_file}")"
    [[ "${code}" == "200" ]] || die "platform-desktop-direct-grants-read-failed"
    jq '.directAccessGrantsEnabled = true' "${client_file}" > "${update_file}"
    code="$(kc_admin_rest PUT "/clients/${CLIENT_UUID}" "${update_out}" "${update_file}")"
    [[ "${code}" == "204" ]] || die "platform-desktop-direct-grants-enable-failed"
  fi
  DIRECT_GRANTS_TOGGLED="true"
}

append_grant_attempt() {
  local endpoint_kind="$1"
  local identifier_kind="$2"
  local http_status="$3"
  local token_present="$4"
  local response_file="$5"
  local error_value=""
  local error_description=""
  error_value="$(jq -r '.error // empty' "${response_file}" 2>/dev/null | safe_error)"
  error_description="$(jq -r '.error_description // empty' "${response_file}" 2>/dev/null | safe_error)"
  jq -n \
    --arg endpointKind "${endpoint_kind}" \
    --arg clientId "${CLIENT_ID}" \
    --arg loginIdentifierKind "${identifier_kind}" \
    --arg httpStatus "${http_status}" \
    --argjson tokenPresent "${token_present}" \
    --arg error "${error_value}" \
    --arg errorDescription "${error_description}" \
    '{
      endpointKind: $endpointKind,
      clientId: $clientId,
      loginIdentifierKind: $loginIdentifierKind,
      httpStatus: ($httpStatus | tonumber? // 0),
      tokenPresent: $tokenPresent,
      tokenIncluded: false,
      error: (if $error == "" then null else $error end),
      errorDescription: (if $errorDescription == "" then null else $errorDescription end)
    }' >> "${GRANT_ATTEMPTS_JSONL}"
}

try_mint_token() {
  local endpoint_kind="$1"
  local endpoint_base="$2"
  local identifier_kind="$3"
  local username_value="$4"
  local response_file="${TMP_DIR}/token-${endpoint_kind}-${identifier_kind}.json"
  local http_status
  http_status="$(curl -sS -o "${response_file}" -w '%{http_code}' -X POST \
    "${endpoint_base}/realms/${KC_REALM}/protocol/openid-connect/token" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=${CLIENT_ID}" \
    --data-urlencode "username=${username_value}" \
    --data-urlencode "password@${USER_PASS_FILE}" || printf '000')"
  local token
  token="$(jq -r '.access_token // empty' "${response_file}" 2>/dev/null || true)"
  if [[ -n "${token}" ]]; then
    printf '%s' "${token}" > "${TOKEN_FILE}"
    chmod 0600 "${TOKEN_FILE}"
    TOKEN_PRESENT="true"
    append_grant_attempt "${endpoint_kind}" "${identifier_kind}" "${http_status}" "true" "${response_file}"
    return 0
  fi
  append_grant_attempt "${endpoint_kind}" "${identifier_kind}" "${http_status}" "false" "${response_file}"
  return 1
}

mint_platform_desktop_token() {
  try_mint_token "local" "${KC_BASE_URL}" "username" "${TEMP_USERNAME}" && return 0
  try_mint_token "local" "${KC_BASE_URL}" "email" "${TEMP_EMAIL}" && return 0
  return 1
}

run_token_contract_and_smoke() {
  if [[ "${TOKEN_PRESENT}" != "true" || ! -s "${TOKEN_FILE}" ]]; then
    STATUS="fail"
    FAILURE_REASON="platform-desktop-token-mint-failed"
    return 1
  fi

  set +e
  python3 scripts/keycloak/validate_faz24_platform_desktop_token_contract.py \
    --token-file "${TOKEN_FILE}" \
    --expected-issuer "${EXPECTED_ISSUER}" \
    > "${TOKEN_CONTRACT_JSON}"
  TOKEN_CONTRACT_EXIT="$?"
  set -e

  if [[ "${TOKEN_CONTRACT_EXIT}" != "0" ]]; then
    STATUS="fail"
    FAILURE_REASON="platform-desktop-token-contract-failed"
    return 1
  fi

  if [[ "${RUN_EXTERNAL_SMOKE}" != "1" && "${RUN_MEETING_AI_ANALYZE_SMOKE}" != "1" ]]; then
    STATUS="pass"
    FAILURE_REASON=""
    return 0
  fi

  if [[ "${RUN_EXTERNAL_SMOKE}" == "1" ]]; then
    local smoke_args=(
      --token-file "${TOKEN_FILE}" \
      --base-url "${BASE_URL}" \
      --expected-issuer "${EXPECTED_ISSUER}" \
      --audio-format "${SMOKE_AUDIO_FORMAT}" \
      --sample-rate-hz "${SMOKE_SAMPLE_RATE_HZ}" \
      --channels "${SMOKE_CHANNELS}" \
      --output-file "${SMOKE_JSON}"
    )
    if [[ -n "${SMOKE_CHUNK_FILE}" ]]; then
      smoke_args+=(--chunk-file "${SMOKE_CHUNK_FILE}")
    fi

    set +e
    python3 scripts/faz24/run_external_recorder_smoke.py \
      "${smoke_args[@]}" \
      > "${TMP_DIR}/smoke.stdout" \
      2> "${TMP_DIR}/smoke.stderr"
    SMOKE_EXIT="$?"
    set -e

    if [[ "${SMOKE_EXIT}" != "0" ]]; then
      STATUS="fail"
      FAILURE_REASON="external-recorder-smoke-failed"
      return 1
    fi

    set +e
    python3 scripts/faz24/verify_external_recorder_smoke_evidence.py \
      --evidence-file "${SMOKE_JSON}" \
      --output-file "${SMOKE_VERIFY_JSON}" \
      > "${TMP_DIR}/smoke-verify.stdout" \
      2> "${TMP_DIR}/smoke-verify.stderr"
    SMOKE_VERIFY_EXIT="$?"
    set -e

    if [[ "${SMOKE_VERIFY_EXIT}" != "0" ]]; then
      STATUS="fail"
      FAILURE_REASON="external-recorder-smoke-verifier-failed"
      return 1
    fi
  fi

  if [[ "${RUN_MEETING_AI_ANALYZE_SMOKE}" == "1" ]]; then
    local analyze_args=(
      --token-file "${TOKEN_FILE}" \
      --base-url "${BASE_URL}" \
      --expected-issuer "${EXPECTED_ISSUER}" \
      --output-file "${MEETING_AI_ANALYZE_JSON}"
    )
    if [[ -n "${MEETING_AI_ANALYZE_SOURCE_FILE}" ]]; then
      analyze_args+=(--source-text-file "${MEETING_AI_ANALYZE_SOURCE_FILE}")
    fi

    set +e
    python3 scripts/faz24/run_meeting_ai_analyze_smoke.py \
      "${analyze_args[@]}" \
      > "${TMP_DIR}/meeting-ai-analyze.stdout" \
      2> "${TMP_DIR}/meeting-ai-analyze.stderr"
    MEETING_AI_ANALYZE_EXIT="$?"
    set -e

    if [[ "${MEETING_AI_ANALYZE_EXIT}" != "0" ]]; then
      STATUS="fail"
      FAILURE_REASON="meeting-ai-analyze-smoke-failed"
      return 1
    fi

    set +e
    python3 scripts/faz24/verify_meeting_ai_analyze_smoke_evidence.py \
      --evidence-file "${MEETING_AI_ANALYZE_JSON}" \
      --output-file "${MEETING_AI_ANALYZE_VERIFY_JSON}" \
      > "${TMP_DIR}/meeting-ai-analyze-verify.stdout" \
      2> "${TMP_DIR}/meeting-ai-analyze-verify.stderr"
    MEETING_AI_ANALYZE_VERIFY_EXIT="$?"
    set -e

    if [[ "${MEETING_AI_ANALYZE_VERIFY_EXIT}" != "0" ]]; then
      STATUS="fail"
      FAILURE_REASON="meeting-ai-analyze-smoke-verifier-failed"
      return 1
    fi
  fi

  STATUS="pass"
  FAILURE_REASON=""
  return 0
}

cleanup_live_state() {
  if [[ "${CLEANUP_DONE}" == "true" ]]; then
    return 0
  fi
  set +e
  if [[ -n "${CLIENT_UUID}" && "${DIRECT_GRANTS_TOGGLED}" == "true" && -n "${DIRECT_GRANTS_ORIGINAL}" ]]; then
    if [[ "${KC_ADMIN_MODE}" == "kcadm" ]]; then
      "${KCADM[@]}" update "clients/${CLIENT_UUID}" -r "${KC_REALM}" \
        -s "directAccessGrantsEnabled=${DIRECT_GRANTS_ORIGINAL}" >/dev/null 2>&1 \
        && DIRECT_GRANTS_RESTORED="true"
    elif [[ -s "${ADMIN_TOKEN_FILE}" ]]; then
      local client_file="${TMP_DIR}/client-direct-grants-restore.json"
      local update_file="${TMP_DIR}/client-direct-grants-restore-update.json"
      local update_out="${TMP_DIR}/client-direct-grants-restore.out"
      local code
      code="$(kc_admin_rest GET "/clients/${CLIENT_UUID}" "${client_file}")"
      if [[ "${code}" == "200" ]]; then
        jq --argjson enabled "${DIRECT_GRANTS_ORIGINAL}" \
          '.directAccessGrantsEnabled = $enabled' "${client_file}" > "${update_file}"
        code="$(kc_admin_rest PUT "/clients/${CLIENT_UUID}" "${update_out}" "${update_file}")"
        [[ "${code}" == "204" ]] && DIRECT_GRANTS_RESTORED="true"
      fi
    fi
  fi
  if [[ -n "${TEMP_USER_ID}" && "${TEMP_USER_CREATED}" == "true" ]]; then
    if [[ "${KC_ADMIN_MODE}" == "kcadm" ]]; then
      "${KCADM[@]}" delete "users/${TEMP_USER_ID}" -r "${KC_REALM}" >/dev/null 2>&1 \
        && TEMP_USER_DELETED="true"
    elif [[ -s "${ADMIN_TOKEN_FILE}" ]]; then
      local delete_out="${TMP_DIR}/temp-user-delete.out"
      local code
      code="$(kc_admin_rest DELETE "/users/${TEMP_USER_ID}" "${delete_out}")"
      [[ "${code}" == "204" || "${code}" == "404" ]] && TEMP_USER_DELETED="true"
    fi
  fi
  capture_client_state "${CLIENT_AFTER_JSON}" "" || true
  rm -f "${ADMIN_PASS_FILE}" "${ADMIN_TOKEN_FILE}" "${USER_PASS_FILE}" "${TOKEN_FILE}"
  [[ ! -e "${TOKEN_FILE}" ]] && TOKEN_FILE_REMOVED="true"
  CLEANUP_DONE="true"
  set -e
}

write_diagnostic() {
  local token_contract_status="not-run"
  local smoke_status="not-run"
  local smoke_verify_status="not-run"
  local meeting_ai_analyze_status="not-run"
  local meeting_ai_analyze_verify_status="not-run"
  local grant_attempts_array="${TMP_DIR}/grant-attempts-array.json"
  if [[ -s "${TOKEN_CONTRACT_JSON}" ]]; then
    token_contract_status="$(jq -r '.status // "unknown"' "${TOKEN_CONTRACT_JSON}" 2>/dev/null || printf 'unknown')"
  fi
  if [[ -s "${SMOKE_JSON}" ]]; then
    smoke_status="$(jq -r '.status // "unknown"' "${SMOKE_JSON}" 2>/dev/null || printf 'unknown')"
  fi
  if [[ -s "${SMOKE_VERIFY_JSON}" ]]; then
    smoke_verify_status="$(jq -r '.status // "unknown"' "${SMOKE_VERIFY_JSON}" 2>/dev/null || printf 'unknown')"
  fi
  if [[ -s "${MEETING_AI_ANALYZE_JSON}" ]]; then
    meeting_ai_analyze_status="$(jq -r '.status // "unknown"' "${MEETING_AI_ANALYZE_JSON}" 2>/dev/null || printf 'unknown')"
  fi
  if [[ -s "${MEETING_AI_ANALYZE_VERIFY_JSON}" ]]; then
    meeting_ai_analyze_verify_status="$(jq -r '.status // "unknown"' "${MEETING_AI_ANALYZE_VERIFY_JSON}" 2>/dev/null || printf 'unknown')"
  fi
  if [[ -s "${GRANT_ATTEMPTS_JSONL}" ]]; then
    jq -s '.' "${GRANT_ATTEMPTS_JSONL}" > "${grant_attempts_array}" \
      || printf '[]\n' > "${grant_attempts_array}"
  else
    printf '[]\n' > "${grant_attempts_array}"
  fi

  jq -n \
    --arg schemaVersion "${SCHEMA_VERSION}" \
    --arg status "${STATUS}" \
    --arg failureReason "${FAILURE_REASON}" \
    --arg realm "${KC_REALM}" \
    --arg clientId "${CLIENT_ID}" \
    --arg resourceClientId "${RESOURCE_CLIENT_ID}" \
    --arg capabilityRole "${CAPABILITY_ROLE}" \
    --arg baseUrl "${BASE_URL}" \
    --arg expectedIssuer "${EXPECTED_ISSUER}" \
    --arg tokenPresent "${TOKEN_PRESENT}" \
    --arg tokenContractExit "${TOKEN_CONTRACT_EXIT}" \
    --arg tokenContractStatus "${token_contract_status}" \
    --arg smokeExit "${SMOKE_EXIT}" \
    --arg smokeStatus "${smoke_status}" \
    --arg smokeVerifyExit "${SMOKE_VERIFY_EXIT}" \
    --arg smokeVerifyStatus "${smoke_verify_status}" \
    --arg meetingAiAnalyzeExit "${MEETING_AI_ANALYZE_EXIT}" \
    --arg meetingAiAnalyzeStatus "${meeting_ai_analyze_status}" \
    --arg meetingAiAnalyzeVerifyExit "${MEETING_AI_ANALYZE_VERIFY_EXIT}" \
    --arg meetingAiAnalyzeVerifyStatus "${meeting_ai_analyze_verify_status}" \
    --argjson directGrantsToggled "${DIRECT_GRANTS_TOGGLED}" \
    --argjson directGrantsRestored "${DIRECT_GRANTS_RESTORED}" \
    --argjson tempUserCreated "${TEMP_USER_CREATED}" \
    --argjson tempUserDeleted "${TEMP_USER_DELETED}" \
    --argjson tokenFileRemoved "${TOKEN_FILE_REMOVED}" \
    --slurpfile kcSource "${KC_SOURCE_JSON}" \
    --slurpfile clientBefore "${CLIENT_BEFORE_JSON}" \
    --slurpfile clientAfter "${CLIENT_AFTER_JSON}" \
    --slurpfile userDiag "${USER_DIAG_JSON}" \
    --slurpfile grantAttempts "${grant_attempts_array}" \
    '{
      schemaVersion: $schemaVersion,
      status: $status,
      tokenIncluded: false,
      failureReason: (if $failureReason == "" then null else $failureReason end),
      target: {
        realm: $realm,
        clientId: $clientId,
        resourceClientId: $resourceClientId,
        capabilityRole: $capabilityRole,
        baseUrl: $baseUrl,
        expectedIssuer: $expectedIssuer
      },
      boundaries: {
        platformTestOnly: true,
        productionMutation: false,
        rawTokenLogged: false,
        rawPasswordLogged: false,
        rawAdminCredentialLogged: false,
        directSttClaimed: false,
        productionReadyClaimed: false
      },
      keycloakSource: ($kcSource[0] // {}),
      clientBefore: ($clientBefore[0] // {}),
      clientAfter: ($clientAfter[0] // {}),
      user: ($userDiag[0] // {}),
      grantAttempts: ($grantAttempts[0] // []),
      results: {
        tokenPresent: ($tokenPresent == "true"),
        tokenContract: {
          exitCode: $tokenContractExit,
          status: $tokenContractStatus
        },
        externalRecorderSmoke: {
          exitCode: $smokeExit,
          status: $smokeStatus
        },
        externalRecorderVerifier: {
          exitCode: $smokeVerifyExit,
          status: $smokeVerifyStatus
        },
        meetingAiAnalyzeSmoke: {
          exitCode: $meetingAiAnalyzeExit,
          status: $meetingAiAnalyzeStatus
        },
        meetingAiAnalyzeVerifier: {
          exitCode: $meetingAiAnalyzeVerifyExit,
          status: $meetingAiAnalyzeVerifyStatus
        }
      },
      cleanup: {
        directGrantsToggled: $directGrantsToggled,
        directGrantsRestored: $directGrantsRestored,
        tempUserCreated: $tempUserCreated,
        tempUserDeleted: $tempUserDeleted,
        tokenFileRemoved: $tokenFileRemoved
      }
    }' > "${DIAG_JSON}"
  chmod 0600 "${DIAG_JSON}"
  DIAGNOSTIC_WRITTEN="true"
}

die() {
  STATUS="fail"
  FAILURE_REASON="$(safe_error "$1")"
  exit 1
}

# shellcheck disable=SC2329 # Invoked by the EXIT trap below.
on_exit() {
  local rc="$1"
  set +e
  cleanup_live_state
  if [[ "${DIAGNOSTIC_WRITTEN}" != "true" ]]; then
    if [[ "${rc}" != "0" && "${STATUS}" == "running" ]]; then
      STATUS="fail"
      FAILURE_REASON="unexpected-runner-error"
    fi
    write_diagnostic
  fi
  rm -rf "${TMP_DIR}"
}
trap 'on_exit "$?"' EXIT

echo "Faz 24 platform-desktop token evidence chain started"
echo "realm=${KC_REALM} client=${CLIENT_ID} run_external_smoke=${RUN_EXTERNAL_SMOKE} run_meeting_ai_analyze_smoke=${RUN_MEETING_AI_ANALYZE_SMOKE}"

kcadm_login
resolve_client_uuid
capture_client_state "${CLIENT_BEFORE_JSON}"
converge_platform_desktop_mappers
create_temp_user
capture_user_diagnostic
enable_direct_grants_temporarily

if mint_platform_desktop_token; then
  run_token_contract_and_smoke || true
else
  STATUS="fail"
  FAILURE_REASON="platform-desktop-token-mint-failed"
fi

cleanup_live_state
write_diagnostic

echo "diagnostic=${DIAG_JSON}"
if [[ -s "${TOKEN_CONTRACT_JSON}" ]]; then
  echo "token_contract=${TOKEN_CONTRACT_JSON}"
fi
if [[ -s "${SMOKE_JSON}" ]]; then
  echo "external_smoke=${SMOKE_JSON}"
fi
if [[ -s "${SMOKE_VERIFY_JSON}" ]]; then
  echo "external_smoke_verify=${SMOKE_VERIFY_JSON}"
fi
if [[ -s "${MEETING_AI_ANALYZE_JSON}" ]]; then
  echo "meeting_ai_analyze=${MEETING_AI_ANALYZE_JSON}"
fi
if [[ -s "${MEETING_AI_ANALYZE_VERIFY_JSON}" ]]; then
  echo "meeting_ai_analyze_verify=${MEETING_AI_ANALYZE_VERIFY_JSON}"
fi
echo "status=${STATUS}"

if [[ "${STATUS}" == "pass" ]]; then
  exit 0
fi
exit 1
