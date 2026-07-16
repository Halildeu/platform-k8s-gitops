#!/usr/bin/env bash

# Shared, source-only helpers for bounded platform-test Keycloak automation.
# Callers provide the referenced paths and target variables; this file never
# reads or prints credential material on its own.

refresh_keycloak_admin_rest_session() {
  [[ -s "${ADMIN_PASS_FILE}" ]] || return 1
  local response_file="${TMP_DIR}/admin-token-response.json"
  local http_status
  http_status="$(curl -sS -o "${response_file}" -w '%{http_code}' -X POST \
    "${KC_BASE_URL}/realms/master/protocol/openid-connect/token" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=admin-cli" \
    --data-urlencode "username=${KC_ADMIN_USER}" \
    --data-urlencode "password@${ADMIN_PASS_FILE}" || printf '000')"
  jq -r '.access_token // empty' "${response_file}" > "${ADMIN_TOKEN_FILE}" 2>/dev/null \
    || : > "${ADMIN_TOKEN_FILE}"
  if [[ "${http_status}" == "200" && -s "${ADMIN_TOKEN_FILE}" ]] \
      && grep -Eq '^[A-Za-z0-9_.-]+$' "${ADMIN_TOKEN_FILE}"; then
    chmod 0600 "${ADMIN_TOKEN_FILE}"
    python3 - "${ADMIN_TOKEN_FILE}" "${ADMIN_CURL_CONFIG}" <<'PY'
import os
import pathlib
import sys

token = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").strip()
target = pathlib.Path(sys.argv[2])
target.write_text(f'header = "Authorization: Bearer {token}"\n', encoding="utf-8")
os.chmod(target, 0o600)
PY
    KC_ADMIN_MODE="rest"
    return 0
  fi

  : > "${ADMIN_TOKEN_FILE}"
  : > "${ADMIN_CURL_CONFIG}"
  echo "WARN: Keycloak admin session refresh failed" >&2
  return 1
}

kc_admin_rest_once() {
  local method="$1"
  local path="$2"
  local out="$3"
  local body_file="${4:-}"
  local url="${KC_BASE_URL}/admin/realms/${KC_REALM}${path}"
  if [[ -n "${body_file}" ]]; then
    curl -sS -o "${out}" -w '%{http_code}' -X "${method}" \
      --config "${ADMIN_CURL_CONFIG}" \
      "${url}" \
      -H "Content-Type: application/json" \
      --data-binary "@${body_file}" || printf '000'
  else
    curl -sS -o "${out}" -w '%{http_code}' -X "${method}" \
      --config "${ADMIN_CURL_CONFIG}" \
      "${url}" || printf '000'
  fi
}

kc_admin_rest() {
  local method="$1"
  local path="$2"
  local out="$3"
  local body_file="${4:-}"
  local code
  code="$(kc_admin_rest_once "${method}" "${path}" "${out}" "${body_file}")"
  if [[ "${code}" == "401" && "${KC_ADMIN_MODE}" == "rest" ]] \
      && refresh_keycloak_admin_rest_session; then
    code="$(kc_admin_rest_once "${method}" "${path}" "${out}" "${body_file}")"
  fi
  printf '%s' "${code}"
}

faz24_temp_user_ids() {
  local users_file="$1"
  local username_pattern="$2"
  jq -r --arg pattern "${username_pattern}" \
    '.[]? | select((.username // "") | test($pattern)) | .id // empty' \
    "${users_file}"
}

faz24_temp_user_count() {
  local users_file="$1"
  local username_pattern="$2"
  jq --arg pattern "${username_pattern}" \
    '[.[]? | select((.username // "") | test($pattern))] | length' \
    "${users_file}"
}

faz24_cleanup_state_proven() {
  local direct_grants_toggled="$1"
  local direct_grants_restored="$2"
  local temp_user_created="$3"
  local temp_user_deleted="$4"

  [[ "${direct_grants_toggled}" != "true" || "${direct_grants_restored}" == "true" ]] \
    && [[ "${temp_user_created}" != "true" || "${temp_user_deleted}" == "true" ]]
}
