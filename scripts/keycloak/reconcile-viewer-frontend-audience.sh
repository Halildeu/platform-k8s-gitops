#!/usr/bin/env bash

# Reconcile the TEST-only Keycloak audience needed by the product VIEW_ONLY
# viewer. The bridge keeps its own issuer/audience/tenant/role checks; this
# script only lets the existing frontend PKCE token name that resource server.

set -euo pipefail
umask 077

ACTION="${1:-}"
KC_REALM="${KC_REALM:-platform-test}"
KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
KC_BASE_URL="${KC_BASE_URL:-http://127.0.0.1:8082}"
KC_ADMIN_USER="${KC_ADMIN_USER:-admin}"
FRONTEND_CLIENT_ID="${FRONTEND_CLIENT_ID:-frontend}"
RESOURCE_CLIENT_ID="${RESOURCE_CLIENT_ID:-remote-bridge-operator-api}"
MAPPER_NAME="${MAPPER_NAME:-remote-bridge-operator-api-audience}"
OUT_DIR="${OUT_DIR:-/tmp/faz22-viewer-frontend-audience}"

case "${ACTION}" in
  --check|--apply|--rollback) ;;
  *) echo "ERROR: action must be --check, --apply, or --rollback" >&2; exit 2 ;;
esac

if [[ "${KC_REALM}" != "platform-test" \
    || "${KC_CONTAINER}" != "platform-kc-test" \
    || "${KC_BASE_URL}" != "http://127.0.0.1:8082" \
    || "${FRONTEND_CLIENT_ID}" != "frontend" \
    || "${RESOURCE_CLIENT_ID}" != "remote-bridge-operator-api" \
    || "${MAPPER_NAME}" != "remote-bridge-operator-api-audience" ]]; then
  echo "ERROR: test-only Keycloak target allowlist mismatch" >&2
  exit 2
fi

for command_name in curl docker jq python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command missing: ${command_name}" >&2
    exit 1
  }
done

mkdir -p "${OUT_DIR}"
TMP_DIR="$(mktemp -d "${OUT_DIR}/.tmp.XXXXXX")"
ADMIN_PASS_FILE="${TMP_DIR}/kc-admin-password"
# Consumed by the sourced REST helper.
# shellcheck disable=SC2034
ADMIN_TOKEN_FILE="${TMP_DIR}/kc-admin-token.jwt"
# Consumed by the sourced REST helper.
# shellcheck disable=SC2034
ADMIN_CURL_CONFIG="${TMP_DIR}/kc-admin-curl.config"
BEFORE_FILE="${TMP_DIR}/mappers-before.json"
AFTER_FILE="${TMP_DIR}/mappers-after.json"
DESIRED_FILE="${TMP_DIR}/desired-mapper.json"
REST_OUT="${TMP_DIR}/rest.out"
SUMMARY_FILE="${OUT_DIR}/viewer-frontend-audience-summary.json"
FRONTEND_UUID=""
RESOURCE_UUID=""
RESULT="running"
CREATED_ID=""

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

# shellcheck source=scripts/faz24/lib/keycloak_admin_rest.sh disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../faz24/lib" && pwd)/keycloak_admin_rest.sh"

read_admin_password() {
  if [[ -n "${KC_ADMIN_PASSWORD:-}" ]]; then
    printf '%s' "${KC_ADMIN_PASSWORD}" > "${ADMIN_PASS_FILE}"
    chmod 0600 "${ADMIN_PASS_FILE}"
    unset KC_ADMIN_PASSWORD
    return 0
  fi
  if docker exec "${KC_CONTAINER}" sh -c 'cat /run/secrets/kc_admin_password' \
      > "${ADMIN_PASS_FILE}" 2>/dev/null && [[ -s "${ADMIN_PASS_FILE}" ]]; then
    chmod 0600 "${ADMIN_PASS_FILE}"
    return 0
  fi
  if docker exec "${KC_CONTAINER}" sh -c \
      'p="${KEYCLOAK_ADMIN_PASSWORD_FILE:-}"; [ -n "$p" ] && cat "$p"' \
      > "${ADMIN_PASS_FILE}" 2>/dev/null && [[ -s "${ADMIN_PASS_FILE}" ]]; then
    chmod 0600 "${ADMIN_PASS_FILE}"
    return 0
  fi
  return 1
}

mapper_projection() {
  local input="$1"
  jq --arg name "${MAPPER_NAME}" --arg audience "${RESOURCE_CLIENT_ID}" '
    [.[]? | select(.name == $name)] as $rows
    | {
        controlledMapperCount: ($rows | length),
        exact: (($rows | length) == 1
          and $rows[0].protocol == "openid-connect"
          and $rows[0].protocolMapper == "oidc-audience-mapper"
          and $rows[0].config["included.client.audience"] == $audience
          and (($rows[0].config["included.custom.audience"] // "") == "")
          and $rows[0].config["access.token.claim"] == "true"
          and $rows[0].config["id.token.claim"] == "false"
          and $rows[0].config["introspection.token.claim"] == "true"
          and $rows[0].config["userinfo.token.claim"] == "false"),
        rows: [$rows[] | {
          name,
          protocol,
          protocolMapper,
          config: {
            includedClientAudience: .config["included.client.audience"],
            includedCustomAudiencePresent: ((.config["included.custom.audience"] // "") != ""),
            accessTokenClaim: .config["access.token.claim"],
            idTokenClaim: .config["id.token.claim"],
            introspectionTokenClaim: .config["introspection.token.claim"],
            userinfoTokenClaim: .config["userinfo.token.claim"]
          }
        }]
      }
  ' "${input}"
}

write_summary() {
  local before='{"controlledMapperCount":0,"exact":false,"rows":[]}'
  local after='{"controlledMapperCount":0,"exact":false,"rows":[]}'
  [[ -s "${BEFORE_FILE}" ]] && before="$(mapper_projection "${BEFORE_FILE}")"
  [[ -s "${AFTER_FILE}" ]] && after="$(mapper_projection "${AFTER_FILE}")"
  jq -n \
    --arg action "${ACTION#--}" \
    --arg result "${RESULT}" \
    --arg realm "${KC_REALM}" \
    --arg frontendClient "${FRONTEND_CLIENT_ID}" \
    --arg resourceClient "${RESOURCE_CLIENT_ID}" \
    --arg mapperName "${MAPPER_NAME}" \
    --arg observedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --argjson before "${before}" \
    --argjson after "${after}" \
    '{
      schemaVersion: "faz22.6.viewerFrontendAudience.v1",
      action: $action,
      result: $result,
      observedAt: $observedAt,
      target: {
        environment: "test",
        realm: $realm,
        frontendClient: $frontendClient,
        resourceClient: $resourceClient,
        mapperName: $mapperName
      },
      before: $before,
      after: $after,
      securityBoundary: {
        accessTokenOnly: ($after.exact == true),
        bridgeCheckVerificationBasis: "design-preservation-not-runtime-measurement",
        bridgeIssuerCheckPreserved: true,
        bridgeAudienceCheckPreserved: true,
        bridgeTenantCheckPreserved: true,
        bridgeSubjectCheckPreserved: true,
        bridgeOperatorRoleCheckPreserved: true,
        productionMutation: false
      },
      secretHygiene: {
        adminPasswordIncluded: false,
        adminTokenIncluded: false,
        userTokenIncluded: false
      }
    }' > "${SUMMARY_FILE}"
}

fail() {
  RESULT="failed:$1"
  write_summary
  echo "ERROR: $1" >&2
  exit 1
}

client_uuid() {
  local client_id="$1"
  local output="$2"
  local code
  code="$(kc_admin_rest GET "/clients?clientId=${client_id}" "${output}")"
  [[ "${code}" == "200" ]] || return 1
  jq -er --arg clientId "${client_id}" '
    [ .[]? | select(.clientId == $clientId) ]
    | if length == 1 then .[0].id else empty end
  ' "${output}"
}

read_mappers() {
  local output="$1"
  local code
  code="$(kc_admin_rest GET "/clients/${FRONTEND_UUID}/protocol-mappers/models" "${output}")"
  [[ "${code}" == "200" ]] && jq -e 'type == "array"' "${output}" >/dev/null
}

exact_mapper_id() {
  local input="$1"
  jq -er --arg name "${MAPPER_NAME}" --arg audience "${RESOURCE_CLIENT_ID}" '
    [.[]? | select(.name == $name)] as $rows
    | if (($rows | length) == 1
        and $rows[0].protocol == "openid-connect"
        and $rows[0].protocolMapper == "oidc-audience-mapper"
        and $rows[0].config["included.client.audience"] == $audience
        and (($rows[0].config["included.custom.audience"] // "") == "")
        and $rows[0].config["access.token.claim"] == "true"
        and $rows[0].config["id.token.claim"] == "false"
        and $rows[0].config["introspection.token.claim"] == "true"
        and $rows[0].config["userinfo.token.claim"] == "false")
      then $rows[0].id
      else empty
      end
  ' "${input}"
}

unique_controlled_mapper_id() {
  local input="$1"
  jq -er --arg name "${MAPPER_NAME}" '
    [.[]? | select(.name == $name)]
    | if length == 1 then .[0].id else empty end
  ' "${input}"
}

read_admin_password || fail "keycloak-admin-password-source-missing"
refresh_keycloak_admin_rest_session || fail "keycloak-admin-login-failed"

FRONTEND_UUID="$(client_uuid "${FRONTEND_CLIENT_ID}" "${TMP_DIR}/frontend-client.json")" \
  || fail "frontend-client-read-failed"
[[ -n "${FRONTEND_UUID}" ]] || fail "frontend-client-not-found"
RESOURCE_UUID="$(client_uuid "${RESOURCE_CLIENT_ID}" "${TMP_DIR}/resource-client.json")" \
  || fail "resource-client-read-failed"
[[ -n "${RESOURCE_UUID}" ]] || fail "resource-client-not-found"

read_mappers "${BEFORE_FILE}" || fail "frontend-mapper-read-failed"
controlled_count="$(jq --arg name "${MAPPER_NAME}" '[.[]? | select(.name == $name)] | length' "${BEFORE_FILE}")"
before_exact_id="$(exact_mapper_id "${BEFORE_FILE}" || true)"

case "${ACTION}" in
  --check)
    cp "${BEFORE_FILE}" "${AFTER_FILE}"
    if [[ "${controlled_count}" == "1" && -n "${before_exact_id}" ]]; then
      RESULT="converged"
      write_summary
      echo "viewer-frontend-audience=converged"
      exit 0
    fi
    RESULT="drift"
    write_summary
    echo "viewer-frontend-audience=drift" >&2
    exit 2
    ;;

  --apply)
    [[ "${controlled_count}" == "0" ]] || {
      if [[ "${controlled_count}" == "1" && -n "${before_exact_id}" ]]; then
        cp "${BEFORE_FILE}" "${AFTER_FILE}"
        RESULT="already-converged"
        write_summary
        echo "viewer-frontend-audience=already-converged"
        exit 0
      fi
      fail "controlled-mapper-name-conflict"
    }

    CREATED_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
    jq -n \
      --arg id "${CREATED_ID}" \
      --arg name "${MAPPER_NAME}" \
      --arg audience "${RESOURCE_CLIENT_ID}" \
      '{
        id: $id,
        name: $name,
        protocol: "openid-connect",
        protocolMapper: "oidc-audience-mapper",
        config: {
          "included.client.audience": $audience,
          "id.token.claim": "false",
          "access.token.claim": "true",
          "introspection.token.claim": "true",
          "userinfo.token.claim": "false"
        }
      }' > "${DESIRED_FILE}"

    code="$(kc_admin_rest POST "/clients/${FRONTEND_UUID}/protocol-mappers/models" "${REST_OUT}" "${DESIRED_FILE}")"
    [[ "${code}" == "201" || "${code}" == "204" ]] || fail "mapper-create-failed-http-${code}"

    if ! read_mappers "${AFTER_FILE}" || [[ -z "$(exact_mapper_id "${AFTER_FILE}" || true)" ]]; then
      rollback_id=""
      [[ -s "${AFTER_FILE}" ]] && rollback_id="$(unique_controlled_mapper_id "${AFTER_FILE}" || true)"
      if [[ -n "${rollback_id}" ]]; then
        rollback_code="$(kc_admin_rest DELETE "/clients/${FRONTEND_UUID}/protocol-mappers/models/${rollback_id}" "${REST_OUT}")"
      else
        rollback_code="not-attempted-no-unique-managed-mapper"
      fi
      RESULT="failed:postcondition-failed-compensating-rollback-http-${rollback_code}"
      read_mappers "${AFTER_FILE}" || true
      write_summary
      echo "ERROR: mapper postcondition failed; compensating rollback attempted" >&2
      exit 1
    fi
    RESULT="created-and-verified"
    write_summary
    echo "viewer-frontend-audience=created-and-verified"
    ;;

  --rollback)
    if [[ "${controlled_count}" == "0" ]]; then
      cp "${BEFORE_FILE}" "${AFTER_FILE}"
      RESULT="already-absent"
      write_summary
      echo "viewer-frontend-audience=already-absent"
      exit 0
    fi
    [[ "${controlled_count}" == "1" && -n "${before_exact_id}" ]] \
      || fail "controlled-mapper-name-conflict"
    code="$(kc_admin_rest DELETE "/clients/${FRONTEND_UUID}/protocol-mappers/models/${before_exact_id}" "${REST_OUT}")"
    [[ "${code}" == "204" || "${code}" == "404" ]] || fail "mapper-delete-failed-http-${code}"
    read_mappers "${AFTER_FILE}" || fail "frontend-mapper-post-rollback-read-failed"
    after_count="$(jq --arg name "${MAPPER_NAME}" '[.[]? | select(.name == $name)] | length' "${AFTER_FILE}")"
    [[ "${after_count}" == "0" ]] || fail "mapper-still-present-after-rollback"
    RESULT="removed-and-verified"
    write_summary
    echo "viewer-frontend-audience=removed-and-verified"
    ;;
esac
