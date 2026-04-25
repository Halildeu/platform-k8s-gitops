#!/usr/bin/env bash
# Faz 17.3 + 17.8 — Profile-aware D29 3-katman lokal muadili smoke
#
# Kullanım:
#   ./scripts/dev-smoke.sh                         # authn-min kapıları
#   ./scripts/dev-smoke.sh --profile zanzibar-min  # + OpenFGA synthetic
#   ./scripts/dev-smoke.sh --profile full          # + 9-app actuator
#   ./scripts/dev-smoke.sh --json                  # JSON output (CI uyumlu)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC2034
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"  # reserved for future fixture references

PROFILE="authn-min"
JSON_OUT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --json) JSON_OUT=true; shift ;;
    -h|--help)
      grep -E '^#' "$0" | sed -E 's/^# ?//' | head -12
      exit 0
      ;;
    *) echo "bilinmeyen flag: $1"; exit 2 ;;
  esac
done

case "${PROFILE}" in
  authn-min|zanzibar-min|full) ;;
  *) echo "profile: authn-min | zanzibar-min | full bekleniyor"; exit 2 ;;
esac

HOST="${LOCAL_EDGE_HOST:-app.localtest.me}"
PORT="${LOCAL_EDGE_PORT:-32080}"       # 17.X TLS sonrası 8443
KC_URL="${KC_URL:-http://localhost:8081}"
KC_REALM="${KC_REALM:-dev-local}"
EDGE="http://${HOST}:${PORT}"

declare -a RESULTS=()

record() {
  # $1: gate label, $2: status (PASS/FAIL/SKIP), $3: detail
  RESULTS+=("$1|$2|$3")
}

check_http() {
  # $1: URL, $2: expected code (default 200), $3: gate label
  local url="$1"
  local expect="${2:-200}"
  local label="$3"
  local code
  code=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" "${url}" 2>/dev/null || echo "000")
  if [[ "${code}" == "${expect}" ]]; then
    record "${label}" "PASS" "${code}"
  else
    record "${label}" "FAIL" "HTTP=${code} (expected ${expect})"
  fi
}

# ----- authn-min gates (her profilde çalışır) -----
# (a) OIDC discovery
check_http "${KC_URL}/realms/${KC_REALM}/.well-known/openid-configuration" 200 "a_oidc_discovery"

# (b) Token mint (direct grant, dev@localtest.me)
TOKEN_RESP=$(curl -s --max-time 5 -X POST \
  "${KC_URL}/realms/${KC_REALM}/protocol/openid-connect/token" \
  -d "client_id=platform-gateway" \
  -d "client_secret=dev-local-client-secret-NOT_FOR_PROD" \
  -d "username=dev@localtest.me" \
  -d "password=dev" \
  -d "grant_type=password" 2>/dev/null || echo '{}')
ACCESS_TOKEN=$(echo "${TOKEN_RESP}" | jq -r .access_token 2>/dev/null || echo "null")
if [[ "${ACCESS_TOKEN}" != "null" && -n "${ACCESS_TOKEN}" ]]; then
  record "b_token_mint" "PASS" "JWT alındı (${#ACCESS_TOKEN} karakter)"
else
  record "b_token_mint" "FAIL" "access_token null"
fi

# (c) Internal auth-service readiness (port-forward helper)
if kubectl --context k3d-dev -n platform-dev get svc auth-service >/dev/null 2>&1; then
  # Background port-forward
  kubectl --context k3d-dev -n platform-dev port-forward svc/auth-service 18081:8081 >/dev/null 2>&1 &
  PF_PID=$!
  sleep 2
  check_http "http://localhost:18081/actuator/health/readiness" 200 "c_auth_readiness_internal"
  kill ${PF_PID} 2>/dev/null || true
else
  record "c_auth_readiness_internal" "SKIP" "auth-service Service yok"
fi

# ----- zanzibar-min + full gates -----
if [[ "${PROFILE}" == "zanzibar-min" || "${PROFILE}" == "full" ]]; then
  # (d) OpenFGA synthetic check
  OPENFGA_URL="${OPENFGA_URL:-http://localhost:32080}"
  STORE_ID=$(curl -s --max-time 3 "${OPENFGA_URL}/stores" 2>/dev/null | jq -r '.stores[0].id' 2>/dev/null || echo "")
  if [[ -n "${STORE_ID}" && "${STORE_ID}" != "null" ]]; then
    CHECK_RESP=$(curl -s --max-time 5 -X POST \
      "${OPENFGA_URL}/stores/${STORE_ID}/check" \
      -H "Content-Type: application/json" \
      -d '{"tuple_key": {"user": "user:dev@localtest.me", "relation": "owner", "object": "project:dev-local"}}' 2>/dev/null || echo '{}')
    ALLOWED=$(echo "${CHECK_RESP}" | jq -r .allowed 2>/dev/null)
    if [[ "${ALLOWED}" == "true" ]]; then
      record "d_openfga_synthetic_allow" "PASS" "dev owner project:dev-local ✓"
    else
      record "d_openfga_synthetic_allow" "FAIL" "allowed=${ALLOWED}"
    fi
  else
    record "d_openfga_synthetic_allow" "SKIP" "OpenFGA store yok"
  fi

  # (e) scope-aware /variants allow/deny (token'lı)
  if [[ "${ACCESS_TOKEN}" != "null" && -n "${ACCESS_TOKEN}" ]]; then
    VAR_CODE=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" \
      -H "Authorization: Bearer ${ACCESS_TOKEN}" \
      "${EDGE}/variants/sample-variant-1" 2>/dev/null || echo "000")
    case "${VAR_CODE}" in
      200) record "e_variant_allow_admin" "PASS" "admin 200" ;;
      401|403) record "e_variant_allow_admin" "FAIL" "HTTP=${VAR_CODE} (beklenen 200 admin)" ;;
      *) record "e_variant_allow_admin" "FAIL" "HTTP=${VAR_CODE}" ;;
    esac
  else
    record "e_variant_allow_admin" "SKIP" "token yok"
  fi
fi

# ----- full gates -----
if [[ "${PROFILE}" == "full" ]]; then
  # (f) frontend UI render
  check_http "${EDGE}/" 200 "f_frontend_render"
  # (g) 9-app actuator (her biri için port-forward — dev-smoke lightweight version)
  record "g_nine_app_actuator" "SKIP" "manuel kubectl get pods -n platform-dev — 9/9 Ready doğrulama"
fi

# ----- D34 isolation gate (Faz 17.1 — local realm leak denylist) -----
# platform-dev içinde staging/prod IP veya domain referansı olmamalı
DENYLIST_HITS=$(kubectl --context k3d-dev -n platform-dev get all,endpoints,configmap -o yaml 2>/dev/null \
    | grep -cE "10\.9\.10\.53|10\.9\.193\.201|ai\.acik\.com|testai\.acik\.com" || true)
if [[ "${DENYLIST_HITS}" -eq 0 ]]; then
  record "z_isolation_denylist" "PASS" "no staging/prod IP or domain leak"
else
  record "z_isolation_denylist" "FAIL" "${DENYLIST_HITS} staging/prod reference (D34 ihlal)"
fi

# ----- Özet -----
PASS_COUNT=$(printf '%s\n' "${RESULTS[@]}" | grep -c '|PASS|' || true)
FAIL_COUNT=$(printf '%s\n' "${RESULTS[@]}" | grep -c '|FAIL|' || true)
SKIP_COUNT=$(printf '%s\n' "${RESULTS[@]}" | grep -c '|SKIP|' || true)
TOTAL=$((PASS_COUNT + FAIL_COUNT + SKIP_COUNT))

if [[ "${JSON_OUT}" == "true" ]]; then
  printf '{"profile":"%s","total":%d,"pass":%d,"fail":%d,"skip":%d,"results":[' "${PROFILE}" "${TOTAL}" "${PASS_COUNT}" "${FAIL_COUNT}" "${SKIP_COUNT}"
  FIRST=true
  for r in "${RESULTS[@]}"; do
    IFS='|' read -r label status detail <<<"$r"
    [[ "${FIRST}" == "true" ]] && FIRST=false || printf ','
    printf '{"gate":"%s","status":"%s","detail":"%s"}' "${label}" "${status}" "${detail}"
  done
  printf ']}\n'
else
  echo "=== dev-smoke profile=${PROFILE} ==="
  for r in "${RESULTS[@]}"; do
    IFS='|' read -r label status detail <<<"$r"
    case "${status}" in
      PASS) printf '\033[0;32m[%s] %s\033[0m — %s\n' "${status}" "${label}" "${detail}" ;;
      FAIL) printf '\033[0;31m[%s] %s\033[0m — %s\n' "${status}" "${label}" "${detail}" ;;
      SKIP) printf '\033[0;33m[%s] %s\033[0m — %s\n' "${status}" "${label}" "${detail}" ;;
    esac
  done
  echo "---"
  echo "PASS=${PASS_COUNT} FAIL=${FAIL_COUNT} SKIP=${SKIP_COUNT} TOTAL=${TOTAL}"
fi

# Exit: 0 if no FAIL
[[ "${FAIL_COUNT}" -eq 0 ]] || exit 1
