#!/usr/bin/env bash
# Faz 22.6 #1580 VIEW_ONLY attended product-channel smoke.
#
# Runs on the self-hosted staging-sw runner. It uses the real broker/operator
# REST path and produces the evidence shape consumed by
# faz22-6-view-only-smoke-finalize.sh. It never opens endpoint inbound
# management ports and never writes bearer tokens or private keys into the
# evidence bundle.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
FINALIZER="${SCRIPT_DIR}/faz22-6-view-only-smoke-finalize.sh"
BROWSER_DIAGNOSTIC_READER="${SCRIPT_DIR}/read-view-only-viewer-browser-diagnostic.sh"

RBD_PRIMARY_OVERLAY="${RBD_PRIMARY_OVERLAY:-${REPO_ROOT}/kustomize/overlays/test}"
RBD_BRIDGE_OVERLAY="${RBD_BRIDGE_OVERLAY:-${REPO_ROOT}/kustomize/overlays/test/activation/endpoint-admin-remote-bridge}"
RBD_DEVICE_KEY_BRIDGE_OVERLAY="${RBD_DEVICE_KEY_BRIDGE_OVERLAY:-${REPO_ROOT}/kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key}"
# shellcheck source=scripts/governance/lib-remote-bridge-digest.sh disable=SC1091
source "${REPO_ROOT}/scripts/governance/lib-remote-bridge-digest.sh"
# Canonical broker frame-flow parser shared with the finalizer (Codex 019f559d S2).
# shellcheck source=scripts/faz22-remote-ops/lib-view-only-frame-flow.sh disable=SC1091
source "${SCRIPT_DIR}/lib-view-only-frame-flow.sh"

K8S_CONTEXT="${K8S_CONTEXT:-k3d-test}"
K8S_NAMESPACE="${K8S_NAMESPACE:-platform-test}"
REMOTE_BRIDGE_DEPLOYMENT="${REMOTE_BRIDGE_DEPLOYMENT:-endpoint-admin-remote-bridge}"
FRONTEND_DEPLOYMENT="${FRONTEND_DEPLOYMENT:-frontend}"
FRONTEND_REPOSITORY="${FRONTEND_REPOSITORY:-ghcr.io/halildeu/platform-web-frontend-testai}"
FRONTEND_CRI_NODE_CONTAINER="${FRONTEND_CRI_NODE_CONTAINER:-k3d-test-server-0}"
REMOTE_BRIDGE_LOCAL_PORT="${REMOTE_BRIDGE_LOCAL_PORT:-18096}"
REMOTE_BRIDGE_MANAGEMENT_LOCAL_PORT="${REMOTE_BRIDGE_MANAGEMENT_LOCAL_PORT:-18097}"
EXPECTED_DIGEST="${EXPECTED_DIGEST:-}"

DEVICE_ID="${DEVICE_ID:-423b6fc3-7497-4083-bd2f-5e2fe543bfe9}"
DEVICE_HOSTNAME="${DEVICE_HOSTNAME:-SRB-AIDENETIMPC}"
SESSION_ID="${SESSION_ID:-rb-viewonly-attended-$(date -u +%Y%m%dT%H%M%SZ)}"
OPERATION_ID="${OPERATION_ID:-op-screen-view-$(date -u +%Y%m%dT%H%M%SZ)}"
NEGATIVE_SESSION_ID="${NEGATIVE_SESSION_ID:-${SESSION_ID}-full-rdp-deny}"
ISSUE_URL="${ISSUE_URL:-https://github.com/Halildeu/platform-k8s-gitops/issues/1580}"

KC_BASE_URL="${KC_BASE_URL:-http://127.0.0.1:8082}"
KC_REALM="${KC_REALM:-platform-test}"
KC_ADMIN_USER="${KC_ADMIN_USER:-admin}"
KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
OPERATOR_USERNAME="${OPERATOR_USERNAME:-rb-operator-denetim}"
APPROVER_USERNAME="${APPROVER_USERNAME:-rb-approver-denetim}"
# These fixed TEST IDs are also the approval-map keys in both activation
# overlays. Keeping the username and immutable JWT sub as separate fields
# prevents audit identity hardening from silently breaking maker-checker authz.
OPERATOR_SUBJECT_ID="${OPERATOR_SUBJECT_ID:-154fdd4f-3e9f-4dfd-9bdf-873bd3b67163}"
APPROVER_SUBJECT_ID="${APPROVER_SUBJECT_ID:-ef3cfda1-9a40-496c-b153-0326a4e44605}"
TENANT_ID="${TENANT_ID:-00000000-0000-0000-0000-000000000001}"
TOKEN_CLIENT_CANDIDATES="${TOKEN_CLIENT_CANDIDATES:-remote-bridge-operator-api frontend}"

PG_CONTAINER="${PG_CONTAINER:-platform-pg-test}"
PG_DATABASE="${PG_DATABASE:-endpoint_admin}"
PG_USER="${PG_USER:-postgres}"
PG_HOST="${PG_HOST:-127.0.0.1}"
PG_PORT="${PG_PORT:-5433}"
DB_SCHEMA="${DB_SCHEMA:-endpoint_admin_service}"
PG_SECRET_NAME="${PG_SECRET_NAME:-endpoint-admin-remote-bridge-secrets-device-key}"
PG_USER_SECRET_KEY="${PG_USER_SECRET_KEY:-SPRING_DATASOURCE_USERNAME}"
PG_PASSWORD_SECRET_KEY="${PG_PASSWORD_SECRET_KEY:-SPRING_DATASOURCE_PASSWORD}"

# Default uses the controlled runner-local Denetim identity created by
# faz24-i3-runner-ssh-identity.yml. The GitHub runner HOME can be ephemeral, so
# anchor the key relative to the checked-out workspace instead of ~/.ssh.
DEFAULT_DENETIM_SSH_IDENTITY="${REPO_ROOT}/../.faz24-i3-ssh/faz24-i3-denetim_ed25519"
DEFAULT_DENETIM_SSH_CONFIG="${DEFAULT_DENETIM_SSH_CONFIG:-/home/aiadmin/.ssh/config}"
DENETIM_SSH_TARGET="${DENETIM_SSH_TARGET:-svc-denetim-agent@10.99.0.2}"
DENETIM_SSH_OPTS="${DENETIM_SSH_OPTS:--i ${DEFAULT_DENETIM_SSH_IDENTITY} -o IdentitiesOnly=yes}"
EXPECTED_DENETIM_SSH_HOSTNAME="${EXPECTED_DENETIM_SSH_HOSTNAME:-10.9.161.202}"
if [[ "$DENETIM_SSH_OPTS" == "__SSH_CONFIG__" ]]; then
  DENETIM_SSH_OPTS="-F ${DEFAULT_DENETIM_SSH_CONFIG}"
fi
REQUIRE_ACTIVE_GUI="${REQUIRE_ACTIVE_GUI:-1}"
CONSENT_WAIT_SECONDS="${CONSENT_WAIT_SECONDS:-120}"
FRAME_WAIT_SECONDS="${FRAME_WAIT_SECONDS:-20}"
# Operator-REST readiness gate budget (Faz 22.6 #1580 device-key live-proof): retry the
# idempotent operation-catalog GET across a transient broker-rollout tunnel drop.
OPERATOR_REST_READY_ATTEMPTS="${OPERATOR_REST_READY_ATTEMPTS:-12}"
OPERATOR_REST_READY_INTERVAL_SECONDS="${OPERATOR_REST_READY_INTERVAL_SECONDS:-3}"
# The run-scoped step-up key rollout replaces the broker pod. Its REST surface
# becomes ready before the endpoint agent has necessarily re-established its
# outbound CONTROL stream. The operator API returns an opaque, side-effect-free
# 404 while that verified peer is absent; wait only for that exact state.
OPEN_SESSION_DEVICE_READY_SECONDS="${OPEN_SESSION_DEVICE_READY_SECONDS:-180}"
OPEN_SESSION_DEVICE_READY_INTERVAL_SECONDS="${OPEN_SESSION_DEVICE_READY_INTERVAL_SECONDS:-5}"
VIEWER_PROBE_SECONDS="${VIEWER_PROBE_SECONDS:-8}"
BROWSER_EVIDENCE_SCRIPT="${BROWSER_EVIDENCE_SCRIPT:-}"
AUTH_ROUTE_PREFLIGHT_ONLY="${AUTH_ROUTE_PREFLIGHT_ONLY:-0}"
VIEWER_PRODUCT_BASE_URL="${VIEWER_PRODUCT_BASE_URL:-https://testai.acik.com}"
PRODUCT_PILOT_SECONDS="${PRODUCT_PILOT_SECONDS:-300}"
SOURCE_REVISION="${SOURCE_REVISION:-}"
PLAYWRIGHT_PACKAGE_ROOT="${PLAYWRIGHT_PACKAGE_ROOT:-}"
REMOTE_BRIDGE_ROLLOUT_TIMEOUT_SECONDS="${REMOTE_BRIDGE_ROLLOUT_TIMEOUT_SECONDS:-420}"
STEP_UP_RUNTIME_STABILIZE_SECONDS="${STEP_UP_RUNTIME_STABILIZE_SECONDS:-8}"
STEP_UP_EPHEMERAL_KEY_ENABLED="${STEP_UP_EPHEMERAL_KEY_ENABLED:-1}"
STEP_UP_PRIVATE_KEY_PEM_PATH="${STEP_UP_PRIVATE_KEY_PEM_PATH:-}"
DURESS_SIGNAL_FOR_OPERATION="${DURESS_SIGNAL_FOR_OPERATION:-NONE}"
MATRIX_HOOK_SCRIPT="${MATRIX_HOOK_SCRIPT:-}"
MATRIX_AUTHORIZATION_SHA256="${MATRIX_AUTHORIZATION_SHA256:-}"
MATRIX_WRONG_TENANT_ID="${MATRIX_WRONG_TENANT_ID:-}"
MATRIX_TERMINATION_CASE="${MATRIX_TERMINATION_CASE:-}"
MATRIX_ROOT_BINDING_FILE="${MATRIX_ROOT_BINDING_FILE:-}"

EVIDENCE_DIR="${EVIDENCE_DIR:-/tmp/faz22-6-view-only-attended-${SESSION_ID}}"
AUTO_FINALIZE="${AUTO_FINALIZE:-0}"
EVIDENCE_URL="${EVIDENCE_URL:-}"
OWNER_APPROVED_BY="${OWNER_APPROVED_BY:-Halil Kocoglu}"
APPROVED_AT="${APPROVED_AT:-$(date -u +%F)}"
EXPIRES_AT="${EXPIRES_AT:-}"
VIEWER_PATH_DECISION="${VIEWER_PATH_DECISION:-owner-deferred}"

TMP_DIR="$(mktemp -d)"
# Armed here, immediately after the temp dir exists, because a trap installed
# dozens of lines later leaves the KC admin password and admin JWT on disk
# whenever the script dies in between (measured 2026-07-31: three such
# directories were still present on the test host, dated 27-30 July).
# The body dispatches at FIRE time: once the full `cleanup` is defined it
# runs; before that — an early --help or validation exit — it still removes
# the temp dir instead of dying with "cleanup: command not found".
trap 'if declare -F cleanup >/dev/null 2>&1; then cleanup; else rm -rf "${TMP_DIR:-}"; fi' EXIT
PORT_FORWARD_PID=""
MANAGEMENT_PORT_FORWARD_PID=""
SUMMARY_FILE="${EVIDENCE_DIR}/summary.json"
OPERATOR_TOKEN_FILE="${TMP_DIR}/operator.jwt"
APPROVER_TOKEN_FILE="${TMP_DIR}/approver.jwt"
KC_ADMIN_PASS_FILE="${TMP_DIR}/kc-admin-password.txt"
KC_ADMIN_TOKEN_FILE="${TMP_DIR}/kc-admin.jwt"
REMOTE_BRIDGE_ORIGINAL_ENV_FILE="${TMP_DIR}/remote-bridge-original-env.json"
MATRIX_WRONG_ROLE_TOKEN_FILE="${TMP_DIR}/matrix-wrong-role.jwt"
MATRIX_WRONG_TENANT_TOKEN_FILE="${TMP_DIR}/matrix-wrong-tenant.jwt"
MATRIX_WRONG_ROLE_CLAIMS_FILE="${TMP_DIR}/matrix-wrong-role-claims.redacted.json"
MATRIX_WRONG_TENANT_CLAIMS_FILE="${TMP_DIR}/matrix-wrong-tenant-claims.redacted.json"
TEMP_PERSONA_IDS=()

status="starting"
reason=""
open_code=""
approve_code=""
challenge_code=""
verify_code=""
duress_signal_code=""
operation_code=""
negative_nonpilot_code=""
close_code=""
viewer_code=""
transport_pushed="false"
consent_wait="missing"
session_hash=""
step_up_key_mode=""
step_up_public_key_sha256=""

usage() {
  cat <<'EOF'
Usage:
  faz22-6-view-only-attended-smoke.sh

Required environment on the self-hosted runner:
  KC_TEST_ADMIN_PASSWORD or readable Keycloak admin password source.

Important optional environment:
  EXPECTED_DIGEST=sha256:... (empty derives from the rendered overlay SSOT)
  DEVICE_ID=...
  DEVICE_HOSTNAME=...
  DENETIM_SSH_TARGET=svc-denetim-agent@10.99.0.2
  DENETIM_SSH_OPTS="-i ../.faz24-i3-ssh/faz24-i3-denetim_ed25519 -o IdentitiesOnly=yes"
  EXPECTED_DENETIM_SSH_HOSTNAME=10.9.161.202 (required resolved host for denetim-pc alias mode)
  REQUIRE_ACTIVE_GUI=1
  AUTO_FINALIZE=1
  EVIDENCE_URL=https://...
  OWNER_APPROVED_BY="Halil Kocoglu"
  APPROVED_AT=YYYY-MM-DD
  EXPIRES_AT=YYYY-MM-DD
  DURESS_SIGNAL_FOR_OPERATION=NONE

The script writes a redacted evidence bundle under EVIDENCE_DIR. It does not
write #1580 and does not assert KVKK/legal signoff.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "view-only-smoke: missing command: $1" >&2
    exit 2
  }
}

fail_smoke() {
  status="no-go"
  reason="$1"
  set +e
  if [[ "${AUTH_ROUTE_PREFLIGHT_ONLY:-0}" != "1" ]]; then
    collect_broker_logs >/dev/null 2>&1
    collect_endpoint_log >/dev/null 2>&1
    write_summary >/dev/null 2>&1
  fi
  write_sha256sums >/dev/null 2>&1
  set -e
  echo "NO_GO $reason"
  exit 1
}

cleanup() {
  set +e
  stop_port_forward
  stop_management_port_forward
  restore_remote_bridge_runtime_env_override >/dev/null 2>&1 || true
  delete_temporary_personas >/dev/null 2>&1 || true
  rm -rf "$TMP_DIR"
}

stop_management_port_forward() {
  if [[ -n "$MANAGEMENT_PORT_FORWARD_PID" ]]; then
    kill "$MANAGEMENT_PORT_FORWARD_PID" >/dev/null 2>&1 || true
    wait "$MANAGEMENT_PORT_FORWARD_PID" >/dev/null 2>&1 || true
    MANAGEMENT_PORT_FORWARD_PID=""
  fi
}

stop_port_forward() {
  if [[ -n "$PORT_FORWARD_PID" ]] && kill -0 "$PORT_FORWARD_PID" >/dev/null 2>&1; then
    kill "$PORT_FORWARD_PID" >/dev/null 2>&1
    wait "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
  fi
  PORT_FORWARD_PID=""
}

sha256_text() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | awk '{print $1}'
  else
    printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
  fi
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

sha256_public_key_material_file() {
  local file="$1" material
  material="$(grep -v -- '-----' "$file" | tr -d '\r\n[:space:]')"
  [[ -n "$material" ]] || return 1
  sha256_text "$material"
}

mask_file_value() {
  local file="$1"
  if [[ -s "$file" && -n "${GITHUB_ACTIONS:-}" && "${EMIT_GITHUB_MASK_COMMANDS:-0}" == "1" ]]; then
    printf '::add-mask::%s\n' "$(tr -d '\r\n' < "$file")"
  fi
}

future_date_utc() {
  local days="$1"
  if date -u -d "+$days days" +%F >/dev/null 2>&1; then
    date -u -d "+$days days" +%F
    return
  fi
  date -u -v+"$days"d +%F
}

validate_inputs() {
  if [[ "$AUTH_ROUTE_PREFLIGHT_ONLY" == "1" && -z "$BROWSER_EVIDENCE_SCRIPT" ]]; then
    fail_smoke "browser-auth-route-preflight-script-required"
  fi
  if [[ "$AUTH_ROUTE_PREFLIGHT_ONLY" != "1" && -z "$EXPECTED_DIGEST" ]]; then
    local expected_ref derive_rc
    derive_rc=0
    expected_ref="$(rbd_expected_digest)" || derive_rc=$?
    case "$derive_rc" in
      0) EXPECTED_DIGEST="${expected_ref##*@}" ;;
      3) fail_smoke "expected-digest-derive-missing-render-tool" ;;
      4) fail_smoke "expected-digest-derive-overlay-drift" ;;
      *) fail_smoke "expected-digest-derive-failed:${derive_rc}" ;;
    esac
  fi
  if [[ "$AUTH_ROUTE_PREFLIGHT_ONLY" != "1" ]]; then
    [[ "$EXPECTED_DIGEST" =~ ^sha256:[a-f0-9]{64}$ ]] || fail_smoke "expected-digest-invalid"
  fi
  [[ "$DEVICE_ID" =~ ^[0-9a-fA-F-]{36}$ ]] || fail_smoke "device-id-invalid"
  [[ "$SESSION_ID" =~ ^[A-Za-z0-9._:-]+$ ]] || fail_smoke "session-id-invalid"
  [[ "$OPERATION_ID" =~ ^[A-Za-z0-9._:-]+$ ]] || fail_smoke "operation-id-invalid"
  [[ "$DB_SCHEMA" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || fail_smoke "db-schema-invalid"
  [[ "$DURESS_SIGNAL_FOR_OPERATION" == "NONE" ]] || fail_smoke "duress-signal-for-operation-must-be-none"
  case "$REQUIRE_ACTIVE_GUI" in 0|1) ;; *) fail_smoke "require-active-gui-invalid" ;; esac
  case "$AUTH_ROUTE_PREFLIGHT_ONLY" in 0|1) ;; *) fail_smoke "auth-route-preflight-only-invalid" ;; esac
  case "$AUTO_FINALIZE" in 0|1) ;; *) fail_smoke "auto-finalize-invalid" ;; esac
  case "$VIEWER_PATH_DECISION" in owner-deferred|fanout-proven) ;; *) fail_smoke "viewer-path-decision-invalid" ;; esac
  [[ "$CONSENT_WAIT_SECONDS" =~ ^[0-9]+$ ]] || fail_smoke "consent-wait-seconds-invalid"
  [[ "$FRAME_WAIT_SECONDS" =~ ^[0-9]+$ ]] || fail_smoke "frame-wait-seconds-invalid"
  [[ "${OPERATOR_REST_READY_ATTEMPTS:-12}" =~ ^[1-9][0-9]*$ ]] || fail_smoke "operator-rest-ready-attempts-invalid"
  [[ "${OPERATOR_REST_READY_INTERVAL_SECONDS:-3}" =~ ^[0-9]+$ ]] || fail_smoke "operator-rest-ready-interval-invalid"
  if [[ ! "$OPEN_SESSION_DEVICE_READY_SECONDS" =~ ^[0-9]+$ ]] \
    || (( OPEN_SESSION_DEVICE_READY_SECONDS < 30 || OPEN_SESSION_DEVICE_READY_SECONDS > 300 )); then
    fail_smoke "open-session-device-ready-seconds-invalid"
  fi
  if [[ ! "$OPEN_SESSION_DEVICE_READY_INTERVAL_SECONDS" =~ ^[0-9]+$ ]] \
    || (( OPEN_SESSION_DEVICE_READY_INTERVAL_SECONDS < 1 || OPEN_SESSION_DEVICE_READY_INTERVAL_SECONDS > 10 )); then
    fail_smoke "open-session-device-ready-interval-invalid"
  fi
  [[ "$VIEWER_PROBE_SECONDS" =~ ^[0-9]+$ ]] || fail_smoke "viewer-probe-seconds-invalid"
  if [[ -n "$BROWSER_EVIDENCE_SCRIPT" ]]; then
    [[ -r "$BROWSER_EVIDENCE_SCRIPT" ]] || fail_smoke "browser-evidence-script-not-readable"
    [[ "$VIEWER_PRODUCT_BASE_URL" == "https://testai.acik.com" ]] \
      || fail_smoke "viewer-product-base-url-must-be-testai"
    if [[ ! "$PRODUCT_PILOT_SECONDS" =~ ^[0-9]+$ ]] \
      || (( PRODUCT_PILOT_SECONDS < 300 || PRODUCT_PILOT_SECONDS > 1800 )); then
      fail_smoke "product-pilot-seconds-must-be-300-1800"
    fi
    [[ "$SOURCE_REVISION" =~ ^[a-f0-9]{40}$ ]] || fail_smoke "source-revision-invalid"
    [[ -n "$PLAYWRIGHT_PACKAGE_ROOT" && -r "$PLAYWRIGHT_PACKAGE_ROOT/package.json" ]] \
      || fail_smoke "playwright-package-root-invalid"
    [[ "$OPERATION_ID" =~ ^[A-Za-z0-9_-]{1,128}$ ]] \
      || fail_smoke "browser-product-operation-id-invalid"
  fi
  if [[ -n "$MATRIX_HOOK_SCRIPT" ]]; then
    [[ -r "$MATRIX_HOOK_SCRIPT" ]] || fail_smoke "matrix-hook-script-not-readable"
    matrix_hook_real="$(realpath "$MATRIX_HOOK_SCRIPT")"
    negative_hook_real="$(realpath "${SCRIPT_DIR}/collect-view-only-viewer-negative-matrix.sh")"
    termination_hook_real="$(realpath "${SCRIPT_DIR}/collect-view-only-viewer-termination-case.sh")"
    [[ "$matrix_hook_real" == "$negative_hook_real" || "$matrix_hook_real" == "$termination_hook_real" ]] \
      || fail_smoke "matrix-hook-script-outside-canonical-repo-path"
    [[ "$SOURCE_REVISION" =~ ^[a-f0-9]{40}$ ]] || fail_smoke "matrix-source-revision-invalid"
    [[ "$MATRIX_AUTHORIZATION_SHA256" =~ ^sha256:[a-f0-9]{64}$ ]] \
      || fail_smoke "matrix-authorization-sha256-invalid"
    if [[ "$matrix_hook_real" == "$negative_hook_real" ]]; then
      [[ -r "$MATRIX_ROOT_BINDING_FILE" ]] \
        || fail_smoke "matrix-root-binding-file-not-readable"
      [[ "$MATRIX_WRONG_TENANT_ID" =~ ^[0-9a-fA-F-]{36}$ ]] \
        || fail_smoke "matrix-wrong-tenant-id-invalid"
      [[ "${MATRIX_WRONG_TENANT_ID,,}" != "${TENANT_ID,,}" ]] \
        || fail_smoke "matrix-wrong-tenant-id-equals-authorized-tenant"
    else
      case "$MATRIX_TERMINATION_CASE" in
        localAbort|killOrRevoke|ttlExpiry|heartbeatLoss|indicatorLoss) ;;
        *) fail_smoke "matrix-termination-case-invalid" ;;
      esac
    fi
  fi
  if [[ "$AUTO_FINALIZE" == "1" ]]; then
    [[ "$EVIDENCE_URL" == https://* ]] || fail_smoke "evidence-url-required-for-auto-finalize"
    [[ -n "$OWNER_APPROVED_BY" ]] || fail_smoke "owner-approved-by-required"
    [[ -n "$EXPIRES_AT" ]] || EXPIRES_AT="$(future_date_utc 30)"
  fi
}

validate_denetim_ssh_target_config() {
  [[ -n "$DENETIM_SSH_TARGET" ]] || return

  if [[ "$DENETIM_SSH_OPTS" == *"$DEFAULT_DENETIM_SSH_IDENTITY"* ]]; then
    [[ -r "$DEFAULT_DENETIM_SSH_IDENTITY" ]] || fail_smoke "denetim-ssh-key-not-readable"
  fi

  if [[ "$DENETIM_SSH_TARGET" == "denetim-pc" ]]; then
    local ssh_config resolved_host resolved_user identity_file
    # shellcheck disable=SC2206
    local opts=( $DENETIM_SSH_OPTS )
    [[ "$DENETIM_SSH_OPTS" == *"$DEFAULT_DENETIM_SSH_CONFIG"* ]] \
      || fail_smoke "denetim-ssh-alias-mode-requires-config-file"
    [[ -r "$DEFAULT_DENETIM_SSH_CONFIG" ]] || fail_smoke "denetim-ssh-config-not-readable"
    ssh_config="$(ssh "${opts[@]}" -G "$DENETIM_SSH_TARGET" 2>/dev/null)" \
      || fail_smoke "denetim-ssh-alias-config-unreadable"
    resolved_host="$(awk 'tolower($1) == "hostname" { print $2; exit }' <<<"$ssh_config")"
    resolved_user="$(awk 'tolower($1) == "user" { print $2; exit }' <<<"$ssh_config")"
    identity_file="$(awk 'tolower($1) == "identityfile" { print $2; exit }' <<<"$ssh_config")"

    [[ "$resolved_host" == "$EXPECTED_DENETIM_SSH_HOSTNAME" ]] \
      || fail_smoke "denetim-ssh-alias-missing-hostname"
    [[ "$resolved_user" == "denetimpc" ]] || fail_smoke "denetim-ssh-alias-missing-user"
    [[ "$identity_file" == *"id_denetim"* ]] || fail_smoke "denetim-ssh-alias-missing-identity"
  fi
}

curl_json() {
  local method="$1" base="$2" path="$3" token_file="$4" out="$5" body="${6:-}"
  local code_file="${out}.code" curl_rc=0
  local max_time="${CURL_JSON_MAX_TIME_SECONDS:-25}"
  [[ "$max_time" =~ ^[1-9][0-9]*$ ]] || return 2
  local args=(
    --silent
    --show-error
    --max-time "$max_time"
    --request "$method"
    --output "$out"
    --write-out '%{http_code}'
    --header 'Content-Type: application/json'
  )
  if [[ -n "$body" ]]; then
    printf '%s' "$body" > "${out}.request.json"
    args+=(--data-binary "@${out}.request.json")
  fi
  if [[ -n "$token_file" ]]; then
    printf 'header = "Authorization: Bearer %s"\n' "$(tr -d '\r\n' < "$token_file")" \
      | curl --config - "${args[@]}" "${base}${path}" > "$code_file" || curl_rc=$?
  else
    curl "${args[@]}" "${base}${path}" > "$code_file" || curl_rc=$?
  fi
  (( curl_rc == 0 )) || return "$curl_rc"
  tr -d '\r\n[:space:]' < "$code_file"
}

assert_http() {
  local actual="$1" expected="$2" label="$3" body_file="$4"
  if [[ "$actual" != "$expected" ]]; then
    [[ -f "$body_file" ]] && jq -c . "$body_file" 2>/dev/null | sed 's/^/BODY /' >&2 || true
    fail_smoke "${label// /-}-http-${actual}-expected-${expected}"
  fi
}

open_session_after_agent_reconnect() {
  local operator_base="$1" body="$2" started_at deadline curl_rc elapsed
  local remaining sleep_seconds CURL_JSON_MAX_TIME_SECONDS
  started_at="$SECONDS"
  deadline=$((started_at + OPEN_SESSION_DEVICE_READY_SECONDS))
  : > "${EVIDENCE_DIR}/open-session-readiness.log"

  while :; do
    if (( SECONDS >= deadline )); then
      fail_smoke "open-session-device-not-connected-timeout"
    fi
    remaining=$((deadline - SECONDS))
    CURL_JSON_MAX_TIME_SECONDS=25
    if (( remaining < CURL_JSON_MAX_TIME_SECONDS )); then
      CURL_JSON_MAX_TIME_SECONDS="$remaining"
    fi

    # A 404 is returned before operatorService.openSession is called when the
    # verified device has no live broker peer. Reissuing the same sessionId is
    # therefore side-effect-free for this exact response. No other response is
    # retried: a lost/ambiguous transport response must never double-apply POST.
    set +e
    open_code="$(curl_json POST "$operator_base" /sessions "$OPERATOR_TOKEN_FILE" "${EVIDENCE_DIR}/open-session.body" "$body")"
    curl_rc=$?
    set -e
    elapsed=$((SECONDS - started_at))

    if (( SECONDS >= deadline )); then
      fail_smoke "open-session-device-not-connected-timeout"
    fi
    if [[ "$curl_rc" != "0" || ! "$open_code" =~ ^[0-9]{3}$ ]]; then
      printf 'result=transport-failure elapsedSeconds=%s\n' "$elapsed" \
        >> "${EVIDENCE_DIR}/open-session-readiness.log"
      fail_smoke "open-session-transport-failure"
    fi

    printf 'result=http-%s elapsedSeconds=%s\n' "$open_code" "$elapsed" \
      >> "${EVIDENCE_DIR}/open-session-readiness.log"
    case "$open_code" in
      200)
        return
        ;;
      404)
        remaining=$((deadline - SECONDS))
        sleep_seconds="$OPEN_SESSION_DEVICE_READY_INTERVAL_SECONDS"
        if (( remaining < sleep_seconds )); then
          sleep_seconds="$remaining"
        fi
        sleep "$sleep_seconds"
        ;;
      *)
        assert_http "$open_code" 200 "open-session" "${EVIDENCE_DIR}/open-session.body"
        ;;
    esac
  done
}

keycloak_admin_password_candidates() {
  printf '%s\n' \
    "/srv/platform/gitops/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "/home/halil/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "$HOME/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "$HOME/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    | awk 'NF && !seen[$0]++'
}

keycloak_admin_password_is_valid() {
  local response token
  response="$(curl -sS -X POST \
    "$KC_BASE_URL/realms/master/protocol/openid-connect/token" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=admin-cli" \
    --data-urlencode "username=$KC_ADMIN_USER" \
    --data-urlencode "password@$KC_ADMIN_PASS_FILE" 2>/dev/null)" \
    || return 1
  token="$(jq -r '.access_token // empty' <<< "$response" 2>/dev/null)"
  [[ -n "$token" ]]
}

accept_keycloak_admin_password_candidate() {
  [[ -s "$KC_ADMIN_PASS_FILE" ]] || return 1
  chmod 0600 "$KC_ADMIN_PASS_FILE"
  keycloak_admin_password_is_valid
}

read_keycloak_admin_password() {
  local candidate
  if [[ -n "${KC_TEST_ADMIN_PASSWORD:-}" ]]; then
    printf '%s' "$KC_TEST_ADMIN_PASSWORD" > "$KC_ADMIN_PASS_FILE"
    accept_keycloak_admin_password_candidate && return
  fi
  if [[ -n "${KC_ADMIN_PASSWORD:-}" ]]; then
    printf '%s' "$KC_ADMIN_PASSWORD" > "$KC_ADMIN_PASS_FILE"
    accept_keycloak_admin_password_candidate && return
  fi
  if command -v docker >/dev/null 2>&1; then
    if docker exec "$KC_CONTAINER" sh -c 'cat /run/secrets/kc_admin_password' \
        > "$KC_ADMIN_PASS_FILE" 2>/dev/null \
        && accept_keycloak_admin_password_candidate; then
      return
    fi
    if docker exec "$KC_CONTAINER" sh -c \
        'p="${KEYCLOAK_ADMIN_PASSWORD_FILE:-}"; [ -n "$p" ] && cat "$p"' \
        > "$KC_ADMIN_PASS_FILE" 2>/dev/null \
        && accept_keycloak_admin_password_candidate; then
      return
    fi
  fi
  while IFS= read -r candidate; do
    if [[ -r "$candidate" ]]; then
      cp "$candidate" "$KC_ADMIN_PASS_FILE"
      accept_keycloak_admin_password_candidate && return
    fi
  done < <(keycloak_admin_password_candidates)
  rm -f "$KC_ADMIN_PASS_FILE"
  fail_smoke "keycloak-admin-password-source-unusable"
}

mint_admin_token() {
  local response
  response="$(curl -sS -X POST \
    "$KC_BASE_URL/realms/master/protocol/openid-connect/token" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=admin-cli" \
    --data-urlencode "username=$KC_ADMIN_USER" \
    --data-urlencode "password@$KC_ADMIN_PASS_FILE")" \
    || fail_smoke "keycloak-admin-token-request-failed"
  jq -r '.access_token // empty' <<< "$response" > "$KC_ADMIN_TOKEN_FILE"
  [[ -s "$KC_ADMIN_TOKEN_FILE" ]] || fail_smoke "keycloak-admin-token-missing"
  chmod 0600 "$KC_ADMIN_TOKEN_FILE"
  mask_file_value "$KC_ADMIN_TOKEN_FILE"
}

admin_curl() {
  local method="$1" path="$2" out="$3" body="${4:-}"
  curl_json "$method" "$KC_BASE_URL/admin/realms/$KC_REALM" "$path" "$KC_ADMIN_TOKEN_FILE" "$out" "$body"
}

ensure_persona() {
  local username="$1" user_id_file="$2" tenant="${3:-$TENANT_ID}"
  local role_mode="${4:-present}" temporary="${5:-0}" expected_uid="${6:-}"
  local lookup="${TMP_DIR}/${username}-lookup.json" code uid
  code="$(admin_curl GET "/users?username=${username}&exact=true" "$lookup")"
  assert_http "$code" 200 "keycloak lookup $username" "$lookup"

  uid="$(jq -r '.[0].id // empty' "$lookup")"
  if [[ -z "$uid" ]]; then
    local create_body create_out
    create_out="${TMP_DIR}/${username}-create.json"
    create_body="$(jq -nc \
      --arg id "$expected_uid" \
      --arg username "$username" \
      --arg email "${username}@testai.acik.com" \
      --arg tenant "$tenant" \
      '{username:$username, enabled:true, emailVerified:true, email:$email,
        firstName:"RemoteBridge", lastName:$username,
        attributes:{tenant_id:[$tenant], org_id:[$tenant], userId:[$username]}}
        + (if $id == "" then {} else {id:$id} end)')"
    code="$(admin_curl POST /users "$create_out" "$create_body")"
    [[ "$code" == "201" || "$code" == "204" ]] || fail_smoke "keycloak create $username returned $code"
    code="$(admin_curl GET "/users?username=${username}&exact=true" "$lookup")"
    assert_http "$code" 200 "keycloak lookup-created $username" "$lookup"
    uid="$(jq -r '.[0].id // empty' "$lookup")"
  fi
  [[ -n "$uid" ]] || fail_smoke "keycloak user id missing for $username"
  if [[ -n "$expected_uid" && "$uid" != "$expected_uid" ]]; then
    fail_smoke "keycloak immutable subject mismatch for $username"
  fi
  printf '%s' "$uid" > "$user_id_file"
  [[ "$temporary" == "1" ]] && TEMP_PERSONA_IDS+=("$uid")

  local update_out update_body pass_file reset_body reset_out role_file role_json role_out
  update_out="${TMP_DIR}/${username}-update.json"
  update_body="$(jq -nc \
    --arg id "$uid" \
    --arg username "$username" \
    --arg email "${username}@testai.acik.com" \
    --arg tenant "$tenant" \
    '{id:$id, username:$username, enabled:true, emailVerified:true, email:$email,
      firstName:"RemoteBridge", lastName:$username,
      attributes:{tenant_id:[$tenant], org_id:[$tenant], userId:[$username]}}')"
  code="$(admin_curl PUT "/users/${uid}" "$update_out" "$update_body")"
  [[ "$code" == "204" ]] || fail_smoke "keycloak update $username returned $code"

  pass_file="${TMP_DIR}/${username}.password"
  openssl rand -base64 32 | tr -d '\n' > "$pass_file"
  chmod 0600 "$pass_file"
  reset_body="$(jq -n --rawfile value "$pass_file" '{type:"password", value:$value, temporary:false}')"
  reset_out="${TMP_DIR}/${username}-reset.json"
  code="$(admin_curl PUT "/users/${uid}/reset-password" "$reset_out" "$reset_body")"
  [[ "$code" == "204" ]] || fail_smoke "keycloak reset $username returned $code"

  role_file="${TMP_DIR}/remote-bridge-role.json"
  code="$(admin_curl GET /roles/remote-bridge-operator "$role_file")"
  assert_http "$code" 200 "keycloak remote-bridge role lookup" "$role_file"
  role_json="$(jq -c '[.]' "$role_file")"
  role_out="${TMP_DIR}/${username}-role-map.json"
  case "$role_mode" in
    present)
      code="$(admin_curl POST "/users/${uid}/role-mappings/realm" "$role_out" "$role_json")"
      [[ "$code" == "204" || "$code" == "409" ]] \
        || fail_smoke "keycloak role-map $username returned $code"
      ;;
    absent)
      code="$(admin_curl DELETE "/users/${uid}/role-mappings/realm" "$role_out" "$role_json")"
      [[ "$code" == "204" || "$code" == "404" ]] \
        || fail_smoke "keycloak role-unmap $username returned $code"
      local effective_roles="${TMP_DIR}/${username}-effective-roles.json"
      code="$(admin_curl GET "/users/${uid}/role-mappings/realm/composite" "$effective_roles")"
      assert_http "$code" 200 "keycloak effective roles $username" "$effective_roles"
      jq -e 'all(.[]; .name != "remote-bridge-operator")' "$effective_roles" >/dev/null \
        || fail_smoke "keycloak wrong-role persona retained remote-bridge-operator"
      ;;
    *) fail_smoke "keycloak role mode invalid for $username" ;;
  esac
}

delete_temporary_personas() {
  local uid out code
  [[ -s "$KC_ADMIN_TOKEN_FILE" ]] || return 0
  for uid in "${TEMP_PERSONA_IDS[@]}"; do
    out="${TMP_DIR}/delete-${uid}.json"
    code="$(admin_curl DELETE "/users/${uid}" "$out" 2>/dev/null || true)"
    if [[ "$code" != "204" && "$code" != "404" ]]; then
      echo "WARN temporary Keycloak matrix persona cleanup failed (HTTP ${code:-transport-error})" >&2
    fi
  done
}

decode_jwt_claims() {
  local token_file="$1" out="$2"
  python3 - "$token_file" "$out" <<'PY'
import base64
import hashlib
import json
import sys

token_path, out_path = sys.argv[1:3]
token = open(token_path, encoding="utf-8").read().strip()
parts = token.split(".")
if len(parts) < 2:
    raise SystemExit("invalid JWT")
payload = parts[1] + "=" * (-len(parts[1]) % 4)
claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
aud = claims.get("aud")
aud_values = [aud] if isinstance(aud, str) else (aud if isinstance(aud, list) else [])
roles = claims.get("realm_access", {}).get("roles", [])
safe = {
    "preferred_username": claims.get("preferred_username"),
    "tenant_id_present": bool(claims.get("tenant_id")),
    "audContainsRemoteBridgeOperatorApi": "remote-bridge-operator-api" in aud_values,
    "realmRolesContainRemoteBridgeOperator": "remote-bridge-operator" in roles,
    "issuerPresent": bool(claims.get("iss")),
    "expiresAtEpoch": claims.get("exp"),
    "subjectSha256": "sha256:" + hashlib.sha256(str(claims.get("sub", "")).encode()).hexdigest(),
    "tenantSha256": "sha256:" + hashlib.sha256(str(claims.get("tenant_id", "")).encode()).hexdigest(),
}
open(out_path, "w", encoding="utf-8").write(json.dumps(safe, sort_keys=True, indent=2) + "\n")
PY
}

mint_persona_token() {
  local username="$1" user_id_file="$2" token_file="$3" claims_file="$4"
  local expected_role="${5:-true}" expected_tenant="${6:-$TENANT_ID}"
  local pass_file="${TMP_DIR}/${username}.password"
  local client response token expected_subject_sha expected_tenant_sha
  [[ -s "$user_id_file" ]] \
    || fail_smoke "keycloak-persona-id-missing:${username}"
  expected_subject_sha="sha256:$(sha256_text "$(cat "$user_id_file")")"
  expected_tenant_sha="sha256:$(sha256_text "$expected_tenant")"
  for client in $TOKEN_CLIENT_CANDIDATES; do
    response="$(curl -sS -X POST \
      "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" \
      --data-urlencode "grant_type=password" \
      --data-urlencode "client_id=$client" \
      --data-urlencode "username=$username" \
      --data-urlencode "password@$pass_file" || true)"
    token="$(jq -r '.access_token // empty' <<< "$response" 2>/dev/null || true)"
    if [[ -n "$token" ]]; then
      printf '%s' "$token" > "$token_file"
      chmod 0600 "$token_file"
      mask_file_value "$token_file"
      decode_jwt_claims "$token_file" "$claims_file"
      if jq -e --argjson expectedRole "$expected_role" \
        --arg tenant "$expected_tenant_sha" \
        --arg subject "$expected_subject_sha" '
        .realmRolesContainRemoteBridgeOperator == $expectedRole
        and .tenant_id_present == true
        and .tenantSha256 == $tenant
        and .subjectSha256 == $subject
        and .audContainsRemoteBridgeOperatorApi == true
      ' "$claims_file" >/dev/null; then
        return
      fi
    fi
  done
  fail_smoke "keycloak-persona-token-unusable:${username}:claim-contract-mismatch"
}

verify_runtime_digest() {
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout status "deploy/${REMOTE_BRIDGE_DEPLOYMENT}" --timeout="${REMOTE_BRIDGE_ROLLOUT_TIMEOUT_SECONDS}s"
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get deploy "$REMOTE_BRIDGE_DEPLOYMENT" -o json \
    > "${EVIDENCE_DIR}/deploy.json"
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get pods -l "app.kubernetes.io/name=${REMOTE_BRIDGE_DEPLOYMENT}" -o json \
    > "${EVIDENCE_DIR}/pods.json"
  jq -r '.spec.template.spec.containers[0].image' "${EVIDENCE_DIR}/deploy.json" > "${EVIDENCE_DIR}/deploy-image.txt"
  jq -r '.items[] | select(.metadata.deletionTimestamp == null) | .status.containerStatuses[0].imageID' \
    "${EVIDENCE_DIR}/pods.json" > "${EVIDENCE_DIR}/pod-imageID.txt"
  grep -F "$EXPECTED_DIGEST" "${EVIDENCE_DIR}/deploy-image.txt" >/dev/null \
    || fail_smoke "deployment-image-digest-mismatch"
  grep -F "$EXPECTED_DIGEST" "${EVIDENCE_DIR}/pod-imageID.txt" >/dev/null \
    || fail_smoke "pod-imageID-digest-mismatch"
}

start_port_forward() {
  stop_port_forward
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    port-forward "deploy/${REMOTE_BRIDGE_DEPLOYMENT}" "${REMOTE_BRIDGE_LOCAL_PORT}:8096" \
    > "${EVIDENCE_DIR}/port-forward.log" 2>&1 &
  PORT_FORWARD_PID="$!"
  for _ in $(seq 1 40); do
    if ! kill -0 "$PORT_FORWARD_PID" >/dev/null 2>&1; then
      fail_smoke "operator-rest-port-forward-exited"
    fi
    if curl -sS --max-time 2 "http://127.0.0.1:${REMOTE_BRIDGE_LOCAL_PORT}/internal/remote-bridge/operator/operation-catalog" \
        -o /dev/null -w '%{http_code}' | grep -Eq '^(200|401|403)$'; then
      return
    fi
    sleep 1
  done
  fail_smoke "operator-rest-port-forward-timeout"
}

start_management_port_forward() {
  stop_management_port_forward
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    port-forward "deploy/${REMOTE_BRIDGE_DEPLOYMENT}" "${REMOTE_BRIDGE_MANAGEMENT_LOCAL_PORT}:8081" \
    > "${EVIDENCE_DIR}/management-port-forward.log" 2>&1 &
  MANAGEMENT_PORT_FORWARD_PID="$!"
  for _ in $(seq 1 40); do
    if ! kill -0 "$MANAGEMENT_PORT_FORWARD_PID" >/dev/null 2>&1; then
      fail_smoke "management-port-forward-exited"
    fi
    if curl -fsS --max-time 2 \
        "http://127.0.0.1:${REMOTE_BRIDGE_MANAGEMENT_LOCAL_PORT}/actuator/prometheus" \
        -o /dev/null; then
      return
    fi
    sleep 1
  done
  fail_smoke "management-port-forward-timeout"
}

capture_viewer_metrics() {
  local phase="$1"
  local raw="${TMP_DIR}/metrics-${phase}.raw.prom"
  case "$phase" in before|after) ;; *) fail_smoke "metrics-phase-invalid" ;; esac
  curl -fsS --max-time 10 \
    "http://127.0.0.1:${REMOTE_BRIDGE_MANAGEMENT_LOCAL_PORT}/actuator/prometheus" \
    -o "$raw" || fail_smoke "metrics-${phase}-query-failed"
  grep -E '^(remote_access_bridge_(data_frames_total|view_only_fanout_frames_total|viewer_started_total|viewer_ended_total|viewer_frames_sent_total|viewer_rejected_total|viewer_render_ack_accepted_total|viewer_render_ack_rejected_total)|process_start_time_seconds)(\{|[[:space:]])' \
    "$raw" | LC_ALL=C sort > "${EVIDENCE_DIR}/metrics-${phase}.prom"
  [[ -s "${EVIDENCE_DIR}/metrics-${phase}.prom" ]] || fail_smoke "metrics-${phase}-empty"
}

viewer_metric_value() {
  local file="$1" metric="$2"
  awk -v metric="$metric" '$1 == metric { print $2; found=1 } END { if (!found) print "0" }' "$file"
}

wait_for_viewer_end_metric() {
  local before after
  before="$(viewer_metric_value "${EVIDENCE_DIR}/metrics-before.prom" \
    remote_access_bridge_viewer_ended_total)"
  for _ in $(seq 1 15); do
    capture_viewer_metrics after
    after="$(viewer_metric_value "${EVIDENCE_DIR}/metrics-after.prom" \
      remote_access_bridge_viewer_ended_total)"
    if awk -v before="$before" -v after="$after" 'BEGIN { exit !((after - before) >= 1) }'; then
      return
    fi
    sleep 1
  done
  fail_smoke "viewer-ended-metric-did-not-advance"
}

capture_d30_snapshot() {
  local output="${EVIDENCE_DIR}/d30-snapshot.json" component deployment desired live
  local runtime_binding="null" actual_ref expected_ref cri_images alias_result
  jq -n --arg capturedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{schemaVersion:"faz22.6-viewer-d30-raw-v2",capturedAt:$capturedAt,images:[]}' > "$output"
  for component in backend web; do
    case "$component" in
      backend) deployment="$REMOTE_BRIDGE_DEPLOYMENT" ;;
      web) deployment="$FRONTEND_DEPLOYMENT" ;;
    esac
    desired="$(kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get deploy "$deployment" \
      -o jsonpath='{.spec.template.spec.containers[0].image}')"
    live="$(kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get pods \
      -l "app.kubernetes.io/name=${deployment}" -o json \
      | jq -r '[.items[] | select(.metadata.deletionTimestamp == null)
        | .status.containerStatuses[0].imageID] | unique
        | if length == 1 then .[0] else empty end')"
    printf '%s' "$desired" | grep -Eq '@sha256:[a-f0-9]{64}$' \
      || fail_smoke "d30-${component}-desired-digest-missing"
    printf '%s' "$live" | grep -Eq '@sha256:[a-f0-9]{64}$' \
      || fail_smoke "d30-${component}-live-imageid-digest-missing-or-nonunique"

    runtime_binding="null"
    if [[ "${desired##*@}" != "${live##*@}" ]]; then
      [[ "$component" == "web" ]] || fail_smoke "d30-${component}-digest-mismatch"
      [[ "$desired" == "${FRONTEND_REPOSITORY}:"*"@${desired##*@}" ]] \
        || fail_smoke "d30-web-desired-repository-mismatch"
      command -v docker >/dev/null 2>&1 \
        || fail_smoke "d30-web-cri-alias-docker-unavailable"
      actual_ref="${live#docker-pullable://}"
      expected_ref="${FRONTEND_REPOSITORY}@${desired##*@}"
      cri_images="$(docker exec "$FRONTEND_CRI_NODE_CONTAINER" crictl images -o json)" \
        || fail_smoke "d30-web-cri-image-inventory-unavailable"
      alias_result="$(jq -c --arg actual "$actual_ref" --arg expected "$expected_ref" '
        [
          .images[]
          | select((.repoDigests // []) | type == "array")
          | select((.repoDigests // []) | index($actual) != null)
          | select((.repoDigests // []) | index($expected) != null)
        ] as $matches
        | {
            matchCount: ($matches | length),
            contentId: (if ($matches | length) == 1 then $matches[0].id else null end)
          }
      ' <<<"$cri_images")" || fail_smoke "d30-web-cri-alias-query-failed"
      [[ "$(jq -r '.matchCount' <<<"$alias_result")" == "1" ]] \
        || fail_smoke "d30-web-cri-alias-not-unique"
      jq -er '.contentId | select(test("^sha256:[a-f0-9]{64}$"))' \
        <<<"$alias_result" >/dev/null \
        || fail_smoke "d30-web-cri-alias-content-id-invalid"
      runtime_binding="$(jq -c -n \
        --arg expectedRepoDigest "$expected_ref" \
        --arg observedRepoDigest "$actual_ref" \
        --arg contentId "$(jq -r '.contentId' <<<"$alias_result")" \
        '{kind:"cri-repo-digest-alias-v1", expectedRepoDigest:$expectedRepoDigest,
          observedRepoDigest:$observedRepoDigest, contentId:$contentId}')"
    fi
    jq --arg component "$component" --arg deployment "$deployment" \
      --arg desiredImage "$desired" --arg liveImageId "$live" \
      --argjson runtimeBinding "$runtime_binding" \
      '.images += [{component:$component,deployment:$deployment,
        desiredImage:$desiredImage,liveImageId:$liveImageId,
        runtimeBinding:$runtimeBinding}]' \
      "$output" > "${output}.tmp"
    mv "${output}.tmp" "$output"
  done
}

capture_remote_bridge_runtime_env() {
  [[ -s "$REMOTE_BRIDGE_ORIGINAL_ENV_FILE" ]] && return
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get deploy "$REMOTE_BRIDGE_DEPLOYMENT" -o json \
    | jq '
      .spec.template.spec.containers[0] as $c |
      (.metadata.annotations // {}) as $annotations |
      {
        hadStepUpEnv: any($c.env[]?; .name == "REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM"),
        stepUpEnv: (first(($c.env // [])[]? | select(.name == "REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM")) // null),
        hadRunScopedAnnotation: ($annotations | has("remote-bridge.platform/run-scoped-step-up-key")),
        runScopedAnnotationValue: ($annotations["remote-bridge.platform/run-scoped-step-up-key"] // null)
      }' > "$REMOTE_BRIDGE_ORIGINAL_ENV_FILE" \
    || fail_smoke "step-up-runtime-env-backup-failed"
}

restore_remote_bridge_runtime_env_override() {
  [[ -s "$REMOTE_BRIDGE_ORIGINAL_ENV_FILE" ]] || return
  local current_json patch
  current_json="${TMP_DIR}/remote-bridge-current-env-restore.json"
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get deploy "$REMOTE_BRIDGE_DEPLOYMENT" -o json > "$current_json" \
    || return 1
  patch="$(jq -cn --slurpfile current "$current_json" --slurpfile original "$REMOTE_BRIDGE_ORIGINAL_ENV_FILE" '
    $current[0] as $deploy |
    $original[0] as $orig |
    ($deploy.spec.template.spec.containers[0].env // []) as $env |
    ($env | map(select(.name != "REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM"))) as $filtered |
    (if $orig.hadStepUpEnv then ($filtered + [$orig.stepUpEnv]) else $filtered end) as $restored |
    if ($restored | length) > 0 then
      [{op:(if ($deploy.spec.template.spec.containers[0] | has("env")) then "replace" else "add" end),
        path:"/spec/template/spec/containers/0/env", value:$restored}]
    elif ($deploy.spec.template.spec.containers[0] | has("env")) then
      [{op:"remove", path:"/spec/template/spec/containers/0/env"}]
    else [] end')"
  if [[ "$patch" != "[]" ]]; then
    kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" patch deploy "$REMOTE_BRIDGE_DEPLOYMENT" --type json -p "$patch" >/dev/null
  fi
  if jq -e '.hadRunScopedAnnotation == true' "$REMOTE_BRIDGE_ORIGINAL_ENV_FILE" >/dev/null; then
    local annotation_value
    annotation_value="$(jq -r '.runScopedAnnotationValue' "$REMOTE_BRIDGE_ORIGINAL_ENV_FILE")"
    kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" annotate deploy "$REMOTE_BRIDGE_DEPLOYMENT" \
      "remote-bridge.platform/run-scoped-step-up-key=${annotation_value}" --overwrite >/dev/null
  else
    kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" annotate deploy "$REMOTE_BRIDGE_DEPLOYMENT" \
      "remote-bridge.platform/run-scoped-step-up-key-" --overwrite >/dev/null 2>&1 || true
  fi
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout status "deploy/${REMOTE_BRIDGE_DEPLOYMENT}" \
    --timeout="${REMOTE_BRIDGE_ROLLOUT_TIMEOUT_SECONDS}s" >/dev/null
  rm -f "$REMOTE_BRIDGE_ORIGINAL_ENV_FILE"
}

apply_run_scoped_step_up_runtime_env_override() {
  local public_path="$1" run_id="$2" patch
  capture_remote_bridge_runtime_env
  patch="$(kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get deploy "$REMOTE_BRIDGE_DEPLOYMENT" -o json \
    | jq -c --rawfile publicKey "$public_path" '
      (.spec.template.spec.containers[0].env // []) as $env |
      ($env | map(select(.name != "REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM"))) as $filtered |
      [{op:(if (.spec.template.spec.containers[0] | has("env")) then "replace" else "add" end),
        path:"/spec/template/spec/containers/0/env",
        value:($filtered + [{name:"REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM", value:$publicKey}])}]')"
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" patch deploy "$REMOTE_BRIDGE_DEPLOYMENT" \
    --type json -p "$patch" >/dev/null || fail_smoke "step-up-runtime-env-override-failed"
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" annotate deploy "$REMOTE_BRIDGE_DEPLOYMENT" \
    "remote-bridge.platform/run-scoped-step-up-key=${run_id}" --overwrite >/dev/null 2>&1 || true
}

runtime_step_up_public_key_matches() {
  local expected_sha="$1" runtime_pem="$2" runtime_sha
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" exec "deploy/${REMOTE_BRIDGE_DEPLOYMENT}" \
    -- printenv REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM > "$runtime_pem" || return 1
  runtime_sha="$(sha256_public_key_material_file "$runtime_pem")"
  [[ "$runtime_sha" == "$expected_sha" ]]
}

export_step_up_public_key() {
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get secret "$PG_SECRET_NAME" \
    -o jsonpath='{.data.REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM}' | base64 -d > "${TMP_DIR}/step-up-public.pem"
  [[ -s "${TMP_DIR}/step-up-public.pem" ]] || fail_smoke "step-up-public-key-missing"
  step_up_public_key_sha256="$(sha256_public_key_material_file "${TMP_DIR}/step-up-public.pem")" \
    || fail_smoke "step-up-public-key-material-empty"
}

candidate_private_keys() {
  [[ -n "$STEP_UP_PRIVATE_KEY_PEM_PATH" ]] && printf '%s\n' "$STEP_UP_PRIVATE_KEY_PEM_PATH"
  for p in \
    /home/halil/codex-rb-smoke/keys/operator-step-up-private-key.pem \
    /home/halil/codex-rb-smoke/operator-step-up-private-key.pem \
    /home/halil/remote-bridge/keys/operator-step-up-private-key.pem \
    /home/halil/remote-bridge-step-up-private-key.pem \
    /home/runner/remote-bridge-step-up-private-key.pem \
    "$REPO_ROOT/.local/remote-bridge/operator-step-up-private-key.pem"; do
    printf '%s\n' "$p"
  done
}

find_matching_step_up_private_key_or_generate() {
  local public_norm candidate pub_tmp key_path public_path run_id
  public_norm="$(grep -v -- '-----' "${TMP_DIR}/step-up-public.pem" | tr -d '\r\n[:space:]')"
  while IFS= read -r candidate; do
    [[ -r "$candidate" ]] || continue
    pub_tmp="${TMP_DIR}/candidate.pub"
    if openssl pkey -in "$candidate" -pubout -out "$pub_tmp" >/dev/null 2>&1; then
      if [[ "$(grep -v -- '-----' "$pub_tmp" | tr -d '\r\n[:space:]')" == "$public_norm" ]]; then
        printf '%s' "$candidate" > "${TMP_DIR}/step-up-private-key.path"
        chmod 0600 "${TMP_DIR}/step-up-private-key.path"
        step_up_key_mode="preconfigured-private-key"
        return
      fi
    fi
  done < <(candidate_private_keys | awk 'NF && !seen[$0]++')

  [[ "$STEP_UP_EPHEMERAL_KEY_ENABLED" == "1" ]] || fail_smoke "step-up-private-key-unavailable-or-public-mismatch"
  key_path="${TMP_DIR}/run-scoped-step-up-private-key.pem"
  public_path="${TMP_DIR}/run-scoped-step-up-public-key.pem"
  run_id="${GITHUB_RUN_ID:-manual-$(date -u +%Y%m%dT%H%M%SZ)}"
  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$key_path" >/dev/null 2>&1 \
    || fail_smoke "step-up-ephemeral-key-generation-failed"
  chmod 0600 "$key_path"
  openssl pkey -in "$key_path" -pubout -out "$public_path" >/dev/null 2>&1 \
    || fail_smoke "step-up-ephemeral-public-key-generation-failed"
  step_up_key_mode="run-scoped-ephemeral-test-key"
  step_up_public_key_sha256="$(sha256_public_key_material_file "$public_path")" \
    || fail_smoke "step-up-ephemeral-public-key-material-empty"
  apply_run_scoped_step_up_runtime_env_override "$public_path" "$run_id"
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout restart "deploy/${REMOTE_BRIDGE_DEPLOYMENT}" >/dev/null \
    || fail_smoke "step-up-ephemeral-rollout-restart-failed"
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout status "deploy/${REMOTE_BRIDGE_DEPLOYMENT}" \
    --timeout="${REMOTE_BRIDGE_ROLLOUT_TIMEOUT_SECONDS}s" || fail_smoke "step-up-ephemeral-rollout-timeout"
  verify_runtime_digest
  sleep "$STEP_UP_RUNTIME_STABILIZE_SECONDS"
  runtime_step_up_public_key_matches "$step_up_public_key_sha256" "${TMP_DIR}/runtime-step-up-public.pem" \
    || fail_smoke "step-up-runtime-public-key-drift-after-env-override"
  cp "$public_path" "${TMP_DIR}/step-up-public.pem"
  printf '%s' "$key_path" > "${TMP_DIR}/step-up-private-key.path"
  chmod 0600 "${TMP_DIR}/step-up-private-key.path"
}

build_step_up_assertion() {
  local challenge_body="$1" assertion_out="$2" key_path
  key_path="$(cat "${TMP_DIR}/step-up-private-key.path")"
  python3 - "$challenge_body" "${TMP_DIR}/clientData.b64" "${TMP_DIR}/authenticatorData.b64" "${TMP_DIR}/signed.bin" <<'PY'
import base64
import hashlib
import json
import sys

challenge_path, client_b64_path, auth_b64_path, signed_path = sys.argv[1:5]
challenge = json.load(open(challenge_path, encoding="utf-8"))
raw = base64.b64decode(challenge["challengeB64"])
challenge_url = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
client = {
    "type": "webauthn.get",
    "challenge": challenge_url,
    "origin": challenge["expectedOrigin"],
}
client_bytes = json.dumps(client, separators=(",", ":"), sort_keys=True).encode("utf-8")
auth = hashlib.sha256(b"testai.acik.com").digest() + bytes([0x05]) + (1).to_bytes(4, "big")
open(client_b64_path, "w", encoding="ascii").write(base64.b64encode(client_bytes).decode("ascii"))
open(auth_b64_path, "w", encoding="ascii").write(base64.b64encode(auth).decode("ascii"))
open(signed_path, "wb").write(auth + hashlib.sha256(client_bytes).digest())
PY
  openssl dgst -sha256 -sign "$key_path" -out "${TMP_DIR}/signature.der" "${TMP_DIR}/signed.bin" \
    >/dev/null 2>&1 || fail_smoke "step-up-signature-generation-failed"
  jq -n \
    --rawfile client "${TMP_DIR}/clientData.b64" \
    --rawfile auth "${TMP_DIR}/authenticatorData.b64" \
    --arg sig "$(base64 < "${TMP_DIR}/signature.der" | tr -d '\r\n')" \
    '{clientDataJsonB64:($client|gsub("\\n";"")), authenticatorDataB64:($auth|gsub("\\n";"")), signatureB64:$sig}' \
    > "$assertion_out"
}

ssh_denetim() {
  # shellcheck disable=SC2206
  local opts=( $DENETIM_SSH_OPTS )
  ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "${opts[@]}" "$DENETIM_SSH_TARGET" "$@"
}

check_active_gui() {
  [[ -n "$DENETIM_SSH_TARGET" ]] || return
  {
    echo "=== query user ==="
    ssh_denetim 'query user'
    echo "=== qwinsta ==="
    ssh_denetim 'qwinsta'
  } > "${EVIDENCE_DIR}/denetim-gui-session.txt" 2>"${EVIDENCE_DIR}/denetim-gui-session.stderr" || {
    [[ "$REQUIRE_ACTIVE_GUI" == "0" ]] && return
    fail_smoke "denetim-gui-session-check-failed"
  }
  if [[ "$REQUIRE_ACTIVE_GUI" == "1" ]] && ! grep -Eiq '\bActive\b' "${EVIDENCE_DIR}/denetim-gui-session.txt"; then
    fail_smoke "denetim-gui-session-not-active"
  fi
}

collect_endpoint_log() {
  [[ -n "$DENETIM_SSH_TARGET" ]] || return 1
  # NOTE: no PowerShell `$` variables in the -Command string. The denetim SSH shell is
  # itself PowerShell, so a `\$sid` / `\$_` here is expanded (to empty) by the OUTER
  # PowerShell before the inner one runs — turning `$sid='...'` into `='...'` (a bogus
  # command) and collecting nothing, which fails the device-key live-proof at the final
  # evidence step even though the VIEW_ONLY relay succeeded. SESSION_ID is a validated
  # slug ([A-Za-z0-9._:-]+, no quotes), so embed it directly in a PS single-quoted
  # literal, and use Select-Object -ExpandProperty Line instead of ForEach-Object {$_.Line}.
  local ps
  ps="powershell -NoProfile -ExecutionPolicy Bypass -Command \"Get-Content 'C:\ProgramData\EndpointAgent\logs\endpoint-agent.log' -Tail 1200 -ErrorAction Stop | Select-String -SimpleMatch '${SESSION_ID}' | Select-Object -ExpandProperty Line\""
  ssh_denetim "$ps" \
    > "${EVIDENCE_DIR}/endpoint-agent-relevant.log" 2>"${EVIDENCE_DIR}/endpoint-agent-relevant.stderr" || return 1
  grep -F "session=\"$SESSION_ID\"" "${EVIDENCE_DIR}/endpoint-agent-relevant.log" >/dev/null
}

collect_broker_logs() {
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" logs "deploy/${REMOTE_BRIDGE_DEPLOYMENT}" --tail=12000 \
    > "${EVIDENCE_DIR}/remote-bridge-logs-tail.txt" 2>"${EVIDENCE_DIR}/remote-bridge-logs-tail.stderr" || true
  grep -F "$SESSION_ID" "${EVIDENCE_DIR}/remote-bridge-logs-tail.txt" \
    > "${EVIDENCE_DIR}/broker-relevant.log" 2>/dev/null || true
}

build_frame_flow_summary() {
  SESSION_ID="$SESSION_ID" python3 \
    "${SCRIPT_DIR}/build-view-only-viewer-frame-flow-summary.py" \
    --broker-log "${EVIDENCE_DIR}/broker-relevant.log" \
    --browser-evidence "${EVIDENCE_DIR}/browser.json" \
    --output "${EVIDENCE_DIR}/frame-flow-summary.json" \
    || fail_smoke "frame-flow-summary-invalid"
}

wait_for_consent() {
  local deadline now
  deadline=$((SECONDS + CONSENT_WAIT_SECONDS))
  consent_wait="timeout"
  while (( SECONDS < deadline )); do
    collect_broker_logs
    if grep -F "$SESSION_ID" "${EVIDENCE_DIR}/broker-relevant.log" | grep -F "CONSENT_GRANTED" >/dev/null 2>&1; then
      consent_wait="granted"
      return
    fi
    if grep -F "$SESSION_ID" "${EVIDENCE_DIR}/broker-relevant.log" | grep -F "CONSENT_DENIED" >/dev/null 2>&1; then
      consent_wait="denied"
      return
    fi
    now="$SECONDS"
    if (( now % 10 == 0 )); then
      printf 'INFO waiting_for_consent elapsed=%s timeout=%s\n' "$now" "$CONSENT_WAIT_SECONDS"
    fi
    sleep 2
  done
}

probe_viewer() {
  local operator_base="$1"
  set +e
  printf 'header = "Authorization: Bearer %s"\n' "$(tr -d '\r\n' < "$OPERATOR_TOKEN_FILE")" \
    | curl --config - \
      --silent --show-error --no-buffer --max-time "$VIEWER_PROBE_SECONDS" \
      --output "${EVIDENCE_DIR}/viewer-sse.body" \
      --write-out '%{http_code}' \
      "${operator_base}/sessions/${SESSION_ID}/view" \
      > "${EVIDENCE_DIR}/viewer-sse.body.code"
  local rc=$?
  set -e
  viewer_code="$(tr -d '\r\n[:space:]' < "${EVIDENCE_DIR}/viewer-sse.body.code" 2>/dev/null || true)"
  # curl returns 28 when the SSE stream stays open until --max-time; that is
  # acceptable if the HTTP status was 200 and frame/audit evidence is present.
  if [[ "$rc" != "0" && "$rc" != "28" ]]; then
    echo "WARN viewer probe curl exit=${rc}" > "${EVIDENCE_DIR}/viewer-sse.warn"
  fi
}

run_browser_evidence() {
  if [[ -z "$BROWSER_EVIDENCE_SCRIPT" ]]; then
    [[ "$AUTH_ROUTE_PREFLIGHT_ONLY" != "1" ]] \
      || fail_smoke "browser-auth-route-preflight-script-required"
    return 0
  fi
  local claims session_sha device_sha binding browser_failure_code
  claims="${EVIDENCE_DIR}/operator-jwt-claims.redacted.json"
  session_sha="sha256:$(sha256_text "$SESSION_ID")"
  device_sha="sha256:$(sha256_text "$DEVICE_ID")"
  binding="$(jq -nc \
    --arg sessionSha256 "$session_sha" \
    --arg tenantSha256 "$(jq -r '.tenantSha256' "$claims")" \
    --arg operatorSha256 "$(jq -r '.subjectSha256' "$claims")" \
    --arg deviceSha256 "$device_sha" \
    '{sessionSha256:$sessionSha256,tenantSha256:$tenantSha256,
      operatorSha256:$operatorSha256,deviceSha256:$deviceSha256}')"
  if [[ "$(jq -r '[.[]] | unique | length' <<< "$binding")" != "4" ]]; then
    fail_smoke "browser-evidence-binding-hashes-not-distinct"
  fi
  if ! EVIDENCE_BINDING_JSON="$binding" \
    VIEWER_URL="${VIEWER_PRODUCT_BASE_URL}/endpoint-admin/remote-access/sessions/${SESSION_ID}/view?streamId=${OPERATION_ID}" \
    BROWSER_OPERATOR_USERNAME="$OPERATOR_USERNAME" \
    BROWSER_OPERATOR_PASSWORD_FILE="${TMP_DIR}/${OPERATOR_USERNAME}.password" \
    BROWSER_DIAGNOSTIC_OUTPUT="${EVIDENCE_DIR}/browser-diagnostic.json" \
    AUTH_ROUTE_PREFLIGHT_ONLY="$AUTH_ROUTE_PREFLIGHT_ONLY" \
    EVIDENCE_OUTPUT="${EVIDENCE_DIR}/browser.json" \
    SOURCE_REVISION="$SOURCE_REVISION" \
    DLP_MASK_RECT_BPS="${DLP_MASK_RECT_BPS:-}" \
    PILOT_SECONDS="$PRODUCT_PILOT_SECONDS" \
    PLAYWRIGHT_PACKAGE_ROOT="$PLAYWRIGHT_PACKAGE_ROOT" \
      node "$BROWSER_EVIDENCE_SCRIPT" \
        > "${EVIDENCE_DIR}/browser-evidence.log" \
        2> "${EVIDENCE_DIR}/browser-evidence.stderr"; then
    browser_failure_code="$(
      "$BROWSER_DIAGNOSTIC_READER" \
        "${EVIDENCE_DIR}/browser-diagnostic.json" \
        "$SOURCE_REVISION" 2>/dev/null || true
    )"
    if [[ -n "$browser_failure_code" ]]; then
      printf 'BROWSER_NO_GO code=%s\n' "$browser_failure_code" >&2
    fi
    # The verified code is diagnostic only; every browser failure remains fatal.
    fail_smoke "browser-product-evidence-failed"
  fi
  if [[ "$AUTH_ROUTE_PREFLIGHT_ONLY" == "1" ]]; then
    jq -e '
      .schemaVersion == "faz22.6.viewOnlyViewerAuthRoutePreflight.v1"
      and .evidenceType == "browser-auth-route-preflight"
      and .status == "pass"
      and .payload.authentication == "keycloak-authorization-code-pkce"
      and .payload.productOrigin == "https://testai.acik.com"
      and .payload.routeMounted == true
      and .payload.browserAuthSessionPresent == true
      and .payload.viewerApiStatus == 404
    ' "${EVIDENCE_DIR}/browser.json" >/dev/null \
      || fail_smoke "browser-auth-route-preflight-invalid"
  else
    jq -e '.evidenceType == "browser" and .payload.renderAckAcceptedCount >= 100' \
      "${EVIDENCE_DIR}/browser.json" >/dev/null \
      || fail_smoke "browser-product-evidence-invalid"
  fi
}

read_pg_credentials() {
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get secret "$PG_SECRET_NAME" \
    -o "jsonpath={.data.${PG_USER_SECRET_KEY}}" | base64 -d > "${TMP_DIR}/pg-user.txt"
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get secret "$PG_SECRET_NAME" \
    -o "jsonpath={.data.${PG_PASSWORD_SECRET_KEY}}" | base64 -d > "${TMP_DIR}/pg-password.txt"
  [[ -s "${TMP_DIR}/pg-user.txt" && -s "${TMP_DIR}/pg-password.txt" ]] || fail_smoke "postgres-credential-read-failed"
  chmod 0600 "${TMP_DIR}/pg-user.txt" "${TMP_DIR}/pg-password.txt"
}

psql_query() {
  local sql="$1"
  shift || true
  if command -v docker >/dev/null 2>&1 && docker inspect "$PG_CONTAINER" >/dev/null 2>&1; then
    printf '%s\n' "$sql" \
      | docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DATABASE" -At -F $'\t' -v ON_ERROR_STOP=1 "$@" -f -
    return
  fi
  if command -v psql >/dev/null 2>&1; then
    read_pg_credentials
    printf '%s\n' "$sql" \
      | PGPASSWORD="$(cat "${TMP_DIR}/pg-password.txt")" \
      psql -h "$PG_HOST" -p "$PG_PORT" -U "$(cat "${TMP_DIR}/pg-user.txt")" \
      -d "$PG_DATABASE" -At -F $'\t' -v ON_ERROR_STOP=1 "$@" -f -
    return
  fi
  fail_smoke "postgres-query-runner-missing"
}

preflight_side_effect_count() {
  local sql
  sql="
SELECT
  (SELECT count(*) FROM ${DB_SCHEMA}.session_recording_entry WHERE chain_id = :'sid')
  +
  (SELECT count(*) FROM ${DB_SCHEMA}.endpoint_audit_events AS event
    WHERE to_jsonb(event)::text LIKE '%' || :'sid' || '%');"
  psql_query "$sql" -v "sid=${SESSION_ID}"
}

export_recording_tsv() {
  local raw_rows="${EVIDENCE_DIR}/recording.raw.tsv"
  local sql
  sql="
SELECT chain_id, seq, kind, jsonb_build_object(
  'content_hash', content_hash,
  'previous_hash', previous_hash,
  'entry_hash', entry_hash,
  'recorded_at', recorded_at,
  'payload_retention_boundary', 'content_hash_only_no_raw_payload'
)::text
FROM ${DB_SCHEMA}.session_recording_entry
WHERE chain_id = :'sid'
ORDER BY seq;"
  psql_query "$sql" -v "sid=${SESSION_ID}" > "$raw_rows" || fail_smoke "recording-query-failed"
  awk 'BEGIN { FS = "\t"; OFS = "\t" } NF >= 4 { print $1, $2, $3, $4 }' "$raw_rows" \
    > "${EVIDENCE_DIR}/recording.tsv"
  grep -F "$SESSION_ID" "${EVIDENCE_DIR}/recording.tsv" | grep -F "POLICY_EVENT" >/dev/null \
    || fail_smoke "recording-policy-event-missing"
}

export_viewer_audit_chain_jsonl() {
  local output="${TMP_DIR}/endpoint-audit-chain.jsonl" sql
  sql="
SELECT jsonb_build_object(
  'id', id::text,
  'tenant_id', tenant_id::text,
  'device_id', CASE WHEN device_id IS NULL THEN NULL ELSE device_id::text END,
  'command_id', CASE WHEN command_id IS NULL THEN NULL ELSE command_id::text END,
  'event_type', event_type,
  'action', action,
  'performed_by_subject', performed_by_subject,
  'correlation_id', correlation_id,
  'metadata', metadata,
  'before_state', before_state,
  'after_state', after_state,
  'occurred_at', to_char(occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),
  'prev_event_hash', prev_event_hash,
  'event_hash', event_hash,
  'event_hash_alg', event_hash_alg,
  'event_hash_version', event_hash_version
)::text
FROM ${DB_SCHEMA}.endpoint_audit_events
WHERE tenant_id = :'tenant'::uuid
  AND event_hash IS NOT NULL
ORDER BY occurred_at ASC, id ASC;"
  psql_query "$sql" -v "tenant=${TENANT_ID}" > "$output" \
    || fail_smoke "viewer-audit-chain-query-failed"
  [[ -s "$output" ]] || fail_smoke "viewer-audit-chain-empty"
}

build_viewer_audit_summary() {
  SESSION_ID="$SESSION_ID" OPERATION_ID="$OPERATION_ID" python3 \
    "${SCRIPT_DIR}/build-view-only-viewer-audit-summary.py" \
    --audit-chain-jsonl "${TMP_DIR}/endpoint-audit-chain.jsonl" \
    --recording-tsv "${EVIDENCE_DIR}/recording.tsv" \
    --browser-evidence "${EVIDENCE_DIR}/browser.json" \
    --frame-flow-summary "${EVIDENCE_DIR}/frame-flow-summary.json" \
    --output "${EVIDENCE_DIR}/audit-summary.json" \
    || fail_smoke "viewer-audit-summary-invalid"
}

broker_signals_json() {
  local signals=()
  grep -F "HELLO_VERIFIED" "${EVIDENCE_DIR}/broker-relevant.log" >/dev/null 2>&1 && signals+=("HELLO_VERIFIED")
  grep -F "CONSENT_GRANTED" "${EVIDENCE_DIR}/broker-relevant.log" >/dev/null 2>&1 && signals+=("CONSENT_GRANTED")
  grep -F "CONSENT_DENIED" "${EVIDENCE_DIR}/broker-relevant.log" >/dev/null 2>&1 && signals+=("CONSENT_DENIED")
  # SCREEN_VIEW == broker RECEIVED >=2 real, non-inert PNG VIEW_ONLY frames for this
  # session (the canonical "view-only frame: ... bytes=N type=image/png disposition=..."
  # broker log; DROPPED_NO_VIEWER counts, viewer relay is gated #2183). Shared parser
  # with the finalizer so the smoke's signal and the finalizer gate never drift.
  broker_log_has_received_frame_flow "${EVIDENCE_DIR}/broker-relevant.log" "$SESSION_ID" && signals+=("SCREEN_VIEW")
  grep -E 'DATA|DATA_FRAME' "${EVIDENCE_DIR}/broker-relevant.log" >/dev/null 2>&1 && signals+=("DATA")
  grep -E 'PERMIT|PERMIT_VIEW' "${EVIDENCE_DIR}/broker-relevant.log" >/dev/null 2>&1 && signals+=("PERMIT")
  if ((${#signals[@]} == 0)); then
    printf '[]'
    return
  fi
  printf '%s\n' "${signals[@]}" | jq -R . | jq -s 'unique'
}

write_summary() {
  local broker_signals operation_kind operation_transport operation_deny
  broker_signals="$(broker_signals_json)"
  operation_kind="$(jq -r '.kind // ""' "${EVIDENCE_DIR}/operation.body" 2>/dev/null || true)"
  operation_transport="$(jq -r '.transportPushed // false' "${EVIDENCE_DIR}/operation.body" 2>/dev/null || true)"
  operation_deny="$(jq -c '
    def bounded($pattern; $fallback):
      if type == "string" and test($pattern) then . else $fallback end;
    if .deny == null then null
    else {
      reason: ((.deny.reason // "denied") | bounded("^[A-Za-z0-9:_-]{1,64}$"; "denied")),
      policyGate: ((.deny.policyGate // null) | if . == null then null else bounded("^[A-Z_]{1,32}$"; null) end),
      policyDetail: ((.deny.policyDetail // null) | if . == null then null else bounded("^[a-z0-9-]{1,64}$"; null) end)
    }
    end
  ' "${EVIDENCE_DIR}/operation.body" 2>/dev/null || printf 'null')"
  [[ "$operation_transport" == "true" ]] && transport_pushed="true"
  jq -n \
    --arg api "http://127.0.0.1:${REMOTE_BRIDGE_LOCAL_PORT}/internal/remote-bridge" \
    --arg sessionId "$SESSION_ID" \
    --arg sessionHash "$session_hash" \
    --arg deviceId "$DEVICE_ID" \
    --arg deviceHostname "$DEVICE_HOSTNAME" \
    --arg status "$status" \
    --arg reason "$reason" \
    --arg consentWait "$consent_wait" \
    --arg operationKind "$operation_kind" \
    --argjson operationDeny "$operation_deny" \
    --arg viewerCode "$viewer_code" \
    --argjson transportPushed "$transport_pushed" \
    --argjson brokerSignals "$broker_signals" \
    --arg catalog "$([[ -f "${EVIDENCE_DIR}/catalog.body.code" ]] && cat "${EVIDENCE_DIR}/catalog.body.code" || true)" \
    --arg open "$open_code" \
    --arg approve "$approve_code" \
    --arg challenge "$challenge_code" \
    --arg verify "$verify_code" \
    --arg duressSignalCode "$duress_signal_code" \
    --arg duressSignal "$DURESS_SIGNAL_FOR_OPERATION" \
    --arg operation "$operation_code" \
    --arg close "$close_code" \
    --arg negativeNonpilot "$negative_nonpilot_code" \
    --arg stepUpKeyMode "$step_up_key_mode" \
    --arg stepUpPublicKeySha256 "$step_up_public_key_sha256" \
    '{
      api: $api,
      sessionId: $sessionId,
      sessionHash: $sessionHash,
      deviceId: $deviceId,
      deviceHostname: $deviceHostname,
      status: $status,
      reason: $reason,
      http: {
        catalog: $catalog,
        open: $open,
        approve: $approve,
        challenge: $challenge,
        verify: $verify,
        duressSignal: $duressSignalCode,
        operation: $operation,
        close: $close,
        "negative-nonpilot": $negativeNonpilot,
        "viewer-sse": $viewerCode
      },
      duressSignal: {
        source: "operator-session",
        signal: $duressSignal,
        recorded: ($duressSignalCode == "200")
      },
      consentWait: $consentWait,
      operationKind: $operationKind,
      operationDeny: $operationDeny,
      transportPushed: $transportPushed,
      brokerSignals: $brokerSignals,
      stepUp: {
        keyMode: $stepUpKeyMode,
        publicKeySha256: $stepUpPublicKeySha256
      },
      secretHygiene: {
        rawBearerTokenLogged: false,
        privateKeyLogged: false,
        curlConfigRetained: false
      },
      boundary: "VIEW_ONLY attended product-channel smoke; not KVKK signoff and not production/broad-rollout evidence"
    }' > "$SUMMARY_FILE"
}

write_sha256sums() {
  (
    cd "$EVIDENCE_DIR"
    rm -f SHA256SUMS
    local sums_file
    sums_file="$(mktemp "${TMPDIR:-/tmp}/faz226-viewonly-sha256.XXXXXX")"
    find . -type f ! -name SHA256SUMS ! -name workflow-smoke.log ! -name '*.curl.conf' -print0 \
      | sort -z \
      | xargs -0 shasum -a 256 > "$sums_file"
    mv "$sums_file" SHA256SUMS
    shasum -a 256 -c SHA256SUMS >/dev/null
  )
}

auto_finalize_if_requested() {
  # `return` with no argument would propagate the false [[ ]] status (1) under
  # set -e, failing an otherwise-successful accepted-candidate run whenever
  # auto_finalize is off (the default manual-seal path). Return 0 explicitly.
  [[ "$AUTO_FINALIZE" == "1" ]] || return 0
  local manifest marker finalizer_summary
  manifest="${EVIDENCE_DIR}/view-only-engineering-evidence-manifest.json"
  marker="${EVIDENCE_DIR}/view-only-engineering-marker.txt"
  finalizer_summary="${EVIDENCE_DIR}/finalizer-summary.json"
  "$FINALIZER" \
    --smoke-dir "$EVIDENCE_DIR" \
    --manifest-out "$manifest" \
    --marker-out "$marker" \
    --finalizer-summary-out "$finalizer_summary" \
    --evidence-url "$EVIDENCE_URL" \
    --pilot-device "$DEVICE_ID" \
    --viewer-path-decision "$VIEWER_PATH_DECISION" \
    --owner-approved-by "$OWNER_APPROVED_BY" \
    --approved-at "$APPROVED_AT" \
    --expires-at "$EXPIRES_AT"
}

main() {
  for cmd in kubectl jq curl openssl python3 base64 shasum ssh; do
    need_cmd "$cmd"
  done
  mkdir -p "$EVIDENCE_DIR"
  validate_inputs
  if [[ "$AUTH_ROUTE_PREFLIGHT_ONLY" == "1" ]]; then
    local before_side_effect_count after_side_effect_count browser_sha256
    read_keycloak_admin_password
    mint_admin_token
    ensure_persona "$OPERATOR_USERNAME" "${TMP_DIR}/operator.id" \
      "$TENANT_ID" present 0 "$OPERATOR_SUBJECT_ID"
    mint_persona_token "$OPERATOR_USERNAME" "${TMP_DIR}/operator.id" "$OPERATOR_TOKEN_FILE" \
      "${EVIDENCE_DIR}/operator-jwt-claims.redacted.json"
    before_side_effect_count="$(preflight_side_effect_count)" \
      || fail_smoke "browser-auth-route-preflight-side-effect-query-failed"
    before_side_effect_count="$(tr -d '[:space:]' <<< "$before_side_effect_count")"
    [[ "$before_side_effect_count" =~ ^[0-9]+$ ]] \
      || fail_smoke "browser-auth-route-preflight-side-effect-query-failed"
    run_browser_evidence
    [[ -s "${EVIDENCE_DIR}/browser.json" ]] \
      || fail_smoke "browser-auth-route-preflight-invalid"
    after_side_effect_count="$(preflight_side_effect_count)" \
      || fail_smoke "browser-auth-route-preflight-side-effect-query-failed"
    after_side_effect_count="$(tr -d '[:space:]' <<< "$after_side_effect_count")"
    [[ "$after_side_effect_count" =~ ^[0-9]+$ ]] \
      || fail_smoke "browser-auth-route-preflight-side-effect-query-failed"
    [[ "$before_side_effect_count" == "0" && "$after_side_effect_count" == "0" ]] \
      || fail_smoke "browser-auth-route-preflight-mutation-detected"
    browser_sha256="sha256:$(sha256_file "${EVIDENCE_DIR}/browser.json")"
    jq -n \
      --arg sourceRevision "$SOURCE_REVISION" \
      --arg observedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --arg sessionSha256 "sha256:$(sha256_text "$SESSION_ID")" \
      --arg browserSha256 "$browser_sha256" \
      --arg dbSchema "$DB_SCHEMA" \
      --argjson beforeCount "$before_side_effect_count" \
      --argjson afterCount "$after_side_effect_count" \
      '{
        schemaVersion:"faz22.6.viewOnlyViewerAuthRouteSessionSideEffect.v1",
        sourceRevision:$sourceRevision,
        observedAt:$observedAt,
        sessionSha256:$sessionSha256,
        browserEvidenceSha256:$browserSha256,
        assertedScope:{
          databaseSchema:$dbSchema,
          tables:["session_recording_entry", "endpoint_audit_events"],
          correlation:"run-scoped opaque session identifier",
          excludes:["test Keycloak persona lifecycle"]
        },
        beforeSideEffectRowCount:$beforeCount,
        afterSideEffectRowCount:$afterCount,
        viewerApiStatus:404,
        sessionOpenAttempted:false,
        consentPromptAttempted:false,
        verdict:"PASS"
      }' > "${EVIDENCE_DIR}/session-side-effect-attestation.json"
    write_sha256sums
    echo "PASS browser-auth-route-preflight"
    return 0
  fi
  validate_denetim_ssh_target_config
  session_hash="$(sha256_text "$SESSION_ID")"

  verify_runtime_digest
  check_active_gui
  start_port_forward
  read_keycloak_admin_password
  mint_admin_token
  ensure_persona "$OPERATOR_USERNAME" "${TMP_DIR}/operator.id" \
    "$TENANT_ID" present 0 "$OPERATOR_SUBJECT_ID"
  ensure_persona "$APPROVER_USERNAME" "${TMP_DIR}/approver.id" \
    "$TENANT_ID" present 0 "$APPROVER_SUBJECT_ID"
  mint_persona_token "$OPERATOR_USERNAME" "${TMP_DIR}/operator.id" \
    "$OPERATOR_TOKEN_FILE" "${EVIDENCE_DIR}/operator-jwt-claims.redacted.json"
  mint_persona_token "$APPROVER_USERNAME" "${TMP_DIR}/approver.id" \
    "$APPROVER_TOKEN_FILE" "${EVIDENCE_DIR}/approver-jwt-claims.redacted.json"
  if [[ -n "$MATRIX_HOOK_SCRIPT" ]]; then
    local matrix_suffix matrix_wrong_role_user matrix_wrong_tenant_user
    matrix_suffix="${GITHUB_RUN_ID:-manual-$(date -u +%Y%m%d%H%M%S)}"
    matrix_wrong_role_user="faz226-wrong-role-${matrix_suffix}"
    matrix_wrong_tenant_user="faz226-wrong-tenant-${matrix_suffix}"
    ensure_persona "$matrix_wrong_role_user" "${TMP_DIR}/matrix-wrong-role.id" \
      "$TENANT_ID" absent 1
    ensure_persona "$matrix_wrong_tenant_user" "${TMP_DIR}/matrix-wrong-tenant.id" \
      "$MATRIX_WRONG_TENANT_ID" present 1
    mint_persona_token "$matrix_wrong_role_user" "${TMP_DIR}/matrix-wrong-role.id" \
      "$MATRIX_WRONG_ROLE_TOKEN_FILE" \
      "$MATRIX_WRONG_ROLE_CLAIMS_FILE" false "$TENANT_ID"
    mint_persona_token "$matrix_wrong_tenant_user" "${TMP_DIR}/matrix-wrong-tenant.id" \
      "$MATRIX_WRONG_TENANT_TOKEN_FILE" \
      "$MATRIX_WRONG_TENANT_CLAIMS_FILE" true "$MATRIX_WRONG_TENANT_ID"
  fi
  export_step_up_public_key
  find_matching_step_up_private_key_or_generate
  start_port_forward
  start_management_port_forward

  local operator_base approval_base body catalog_code catalog_rc
  operator_base="http://127.0.0.1:${REMOTE_BRIDGE_LOCAL_PORT}/internal/remote-bridge/operator"
  approval_base="http://127.0.0.1:${REMOTE_BRIDGE_LOCAL_PORT}/internal/remote-bridge/approval"

  # Operator-REST readiness gate (Faz 22.6 #1580 device-key live-proof reliability).
  # The step-up run-scoped-key `rollout restart` above replaces the broker pod on a
  # quota-tight test node (strategy is maxSurge:0 / maxUnavailable:1, so there is a
  # brief no-pod window). rollout-status + the exec key-check confirm the NEW pod is
  # Ready, but Ready precedes the operator REST fully serving, and the freshly opened
  # port-forward can still be pinned to the terminating pod for a beat — so the first
  # authenticated call intermittently sees a dead tunnel (curl 000) and the whole
  # device-key live-proof fails on a transport race, not on any device-key defect.
  # This gate re-establishes the port-forward on a 000 and re-issues the IDEMPOTENT
  # catalog GET until the broker serves 200 (fully up) or the attempt budget is spent.
  # A non-000 code (e.g. a 5xx application-readiness error) is NOT a transport failure,
  # so it is only slept-and-retried — never masked by a tunnel rebuild. Only this read
  # is retried; the non-idempotent session POSTs below run once, after the broker is
  # proven stable, so there is no double-apply risk. Worst-case wall time ≈
  # OPERATOR_REST_READY_ATTEMPTS × (curl --max-time 25 + start_port_forward's own ≤40s
  # catalog wait on a 000); keep the attempt count modest — the healthy path exits on
  # the first 200.
  catalog_code=""
  for _ in $(seq 1 "${OPERATOR_REST_READY_ATTEMPTS:-12}"); do
    # curl_json can exit non-zero on a dead tunnel; under `set -e` that would abort the
    # whole gate before the retry, so capture its status explicitly and normalise any
    # failed/empty result to the 000 transport-failure code the loop keys on.
    set +e
    catalog_code="$(curl_json GET "$operator_base" /operation-catalog "$OPERATOR_TOKEN_FILE" "${EVIDENCE_DIR}/catalog.body")"
    catalog_rc=$?
    set -e
    [[ "$catalog_rc" == "0" && -n "$catalog_code" ]] || catalog_code="000"
    [[ "$catalog_code" == "200" ]] && break
    if [[ "$catalog_code" == "000" ]]; then
      # tunnel died under the broker rollout — rebuild it and retry the idempotent GET
      start_port_forward
      continue
    fi
    sleep "${OPERATOR_REST_READY_INTERVAL_SECONDS:-3}"
  done
  assert_http "$catalog_code" 200 "operation catalog" "${EVIDENCE_DIR}/catalog.body"

  body="$(jq -nc --arg session "$SESSION_ID" --arg device "$DEVICE_ID" \
    '{sessionId:$session, deviceId:$device, reason:"Faz 22.6 #1580 attended VIEW_ONLY smoke", capabilities:["VIEW_ONLY"]}')"
  open_session_after_agent_reconnect "$operator_base" "$body"
  jq -e '.consentPromptSent == true' "${EVIDENCE_DIR}/open-session.body" >/dev/null \
    || fail_smoke "open-session-consent-prompt-not-sent"

  body="$(jq -nc --arg session "$NEGATIVE_SESSION_ID" --arg device "$DEVICE_ID" \
    '{sessionId:$session, deviceId:$device, reason:"negative non-pilot capability", capabilities:["FULL_RDP"]}')"
  negative_nonpilot_code="$(curl_json POST "$operator_base" /sessions "$OPERATOR_TOKEN_FILE" "${EVIDENCE_DIR}/negative-nonpilot.body" "$body")"
  [[ "$negative_nonpilot_code" == "400" ]] || fail_smoke "negative-nonpilot expected 400 got ${negative_nonpilot_code}"

  wait_for_consent
  [[ "$consent_wait" == "granted" ]] || fail_smoke "consent-not-granted:${consent_wait}"

  body='{"capabilities":["VIEW_ONLY"]}'
  approve_code="$(curl_json POST "$approval_base" "/sessions/${SESSION_ID}/approve" "$APPROVER_TOKEN_FILE" "${EVIDENCE_DIR}/approve.body" "$body")"
  assert_http "$approve_code" 200 "approve session" "${EVIDENCE_DIR}/approve.body"

  challenge_code="$(curl_json POST "$operator_base" "/sessions/${SESSION_ID}/step-up/challenge" "$OPERATOR_TOKEN_FILE" "${EVIDENCE_DIR}/step-up-challenge.body")"
  assert_http "$challenge_code" 200 "step-up challenge" "${EVIDENCE_DIR}/step-up-challenge.body"
  build_step_up_assertion "${EVIDENCE_DIR}/step-up-challenge.body" "${TMP_DIR}/step-up-assertion.json"
  verify_code="$(curl_json POST "$operator_base" "/sessions/${SESSION_ID}/step-up/verify" "$OPERATOR_TOKEN_FILE" "${EVIDENCE_DIR}/step-up-verify.body" "$(cat "${TMP_DIR}/step-up-assertion.json")")"
  assert_http "$verify_code" 200 "step-up verify" "${EVIDENCE_DIR}/step-up-verify.body"
  jq -e '.verified == true' "${EVIDENCE_DIR}/step-up-verify.body" >/dev/null \
    || fail_smoke "step-up-verify-not-verified"

  body="$(jq -nc --arg signal "$DURESS_SIGNAL_FOR_OPERATION" '{signal:$signal}')"
  duress_signal_code="$(curl_json POST "$operator_base" "/sessions/${SESSION_ID}/duress/signal" "$OPERATOR_TOKEN_FILE" "${EVIDENCE_DIR}/duress-signal.body" "$body")"
  assert_http "$duress_signal_code" 200 "duress signal" "${EVIDENCE_DIR}/duress-signal.body"
  jq -e --arg signal "$DURESS_SIGNAL_FOR_OPERATION" '.signal == $signal and .terminal == false' "${EVIDENCE_DIR}/duress-signal.body" >/dev/null \
    || fail_smoke "duress-signal-not-recorded"

  capture_d30_snapshot
  capture_viewer_metrics before
  body="$(jq -nc --arg op "$OPERATION_ID" '{operationId:$op, operation:"SCREEN_VIEW", commandLine:null}')"
  operation_code="$(curl_json POST "$operator_base" "/sessions/${SESSION_ID}/operations" "$OPERATOR_TOKEN_FILE" "${EVIDENCE_DIR}/operation.body" "$body")"
  assert_http "$operation_code" 200 "screen-view operation" "${EVIDENCE_DIR}/operation.body"
  if ! jq -e '.kind == "PERMIT" and .transportPushed == true and .permit.capability == "VIEW_ONLY"' \
      "${EVIDENCE_DIR}/operation.body" >/dev/null; then
    # The controller already sanitizes DenyMetadata to bounded reason/gate/detail
    # tokens. Emit only those fields: never the permit (which carries raw session
    # and operation ids), request body, bearer token, device id, or screen data.
    jq -c '
      def bounded($pattern; $fallback):
        if type == "string" and test($pattern) then . else $fallback end;
      {
        kind: ((.kind // "missing") | bounded("^[A-Z_]{1,32}$"; "missing")),
        transportPushed: (if (.transportPushed | type) == "boolean" then .transportPushed else false end),
        deny: (if .deny == null then null else {
          reason: ((.deny.reason // "denied") | bounded("^[A-Za-z0-9:_-]{1,64}$"; "denied")),
          policyGate: ((.deny.policyGate // null) | if . == null then null else bounded("^[A-Z_]{1,32}$"; null) end),
          policyDetail: ((.deny.policyDetail // null) | if . == null then null else bounded("^[a-z0-9-]{1,64}$"; null) end)
        } end)
      }' \
      "${EVIDENCE_DIR}/operation.body" | sed 's/^/OPERATION_DIAGNOSTIC /'
    fail_smoke "screen-view-operation-not-permit"
  fi
  transport_pushed="true"

  if [[ -n "$MATRIX_HOOK_SCRIPT" ]]; then
    MATRIX_OPERATOR_BASE="$operator_base" \
    MATRIX_MANAGEMENT_BASE="http://127.0.0.1:${REMOTE_BRIDGE_MANAGEMENT_LOCAL_PORT}" \
    MATRIX_SESSION_ID="$SESSION_ID" \
    MATRIX_STREAM_ID="$OPERATION_ID" \
    MATRIX_DEVICE_ID="$DEVICE_ID" \
    MATRIX_OPERATOR_TOKEN_FILE="$OPERATOR_TOKEN_FILE" \
    MATRIX_OPERATOR_CLAIMS_FILE="${EVIDENCE_DIR}/operator-jwt-claims.redacted.json" \
    MATRIX_WRONG_ROLE_TOKEN_FILE="$MATRIX_WRONG_ROLE_TOKEN_FILE" \
    MATRIX_WRONG_ROLE_CLAIMS_FILE="$MATRIX_WRONG_ROLE_CLAIMS_FILE" \
    MATRIX_WRONG_TENANT_TOKEN_FILE="$MATRIX_WRONG_TENANT_TOKEN_FILE" \
    MATRIX_WRONG_TENANT_CLAIMS_FILE="$MATRIX_WRONG_TENANT_CLAIMS_FILE" \
    MATRIX_WRONG_TENANT_ID="$MATRIX_WRONG_TENANT_ID" \
    MATRIX_ROOT_BINDING_FILE="$MATRIX_ROOT_BINDING_FILE" \
    MATRIX_TERMINATION_CASE="$MATRIX_TERMINATION_CASE" \
    MATRIX_SOURCE_REVISION="$SOURCE_REVISION" \
    MATRIX_AUTHORIZATION_SHA256="$MATRIX_AUTHORIZATION_SHA256" \
    MATRIX_K8S_CONTEXT="$K8S_CONTEXT" \
    MATRIX_K8S_NAMESPACE="$K8S_NAMESPACE" \
    MATRIX_REMOTE_BRIDGE_DEPLOYMENT="$REMOTE_BRIDGE_DEPLOYMENT" \
    MATRIX_TENANT_ID="$TENANT_ID" \
    MATRIX_PG_CONTAINER="$PG_CONTAINER" \
    MATRIX_PG_DATABASE="$PG_DATABASE" \
    MATRIX_PG_USER="$PG_USER" \
    MATRIX_DB_SCHEMA="$DB_SCHEMA" \
    MATRIX_OUTPUT_DIR="${EVIDENCE_DIR}/matrix" \
      bash "$MATRIX_HOOK_SCRIPT" || fail_smoke "matrix-hook-failed"
    test -s "${EVIDENCE_DIR}/matrix/context.json" \
      || [[ -n "$MATRIX_TERMINATION_CASE" ]] \
      || fail_smoke "matrix-hook-context-missing"
    if [[ -n "$MATRIX_TERMINATION_CASE" ]]; then
      test -s "${EVIDENCE_DIR}/matrix/observations/${MATRIX_TERMINATION_CASE}.jsonl" \
        || fail_smoke "matrix-hook-termination-observation-missing"
      test -s "${EVIDENCE_DIR}/matrix/audit/${MATRIX_TERMINATION_CASE}.jsonl" \
        || fail_smoke "matrix-hook-termination-audit-missing"
    else
      test -s "${EVIDENCE_DIR}/matrix/observations/negative.jsonl" \
        || fail_smoke "matrix-hook-observations-missing"
    fi
    close_code="$(cat "${EVIDENCE_DIR}/matrix/close.code" 2>/dev/null || true)"
    status="accepted-candidate"
    reason="VIEW_ONLY protected matrix collector produced digest-bound observations"
    write_summary
    write_sha256sums
    echo "ACCEPTED_CANDIDATE matrix_dir=${EVIDENCE_DIR}/matrix"
    return 0
  fi

  run_browser_evidence
  wait_for_viewer_end_metric
  sleep "$FRAME_WAIT_SECONDS"
  probe_viewer "$operator_base"
  collect_broker_logs
  build_frame_flow_summary
  collect_endpoint_log || fail_smoke "endpoint-agent-consent-log-missing"
  grep -F "session=\"$SESSION_ID\"" "${EVIDENCE_DIR}/endpoint-agent-relevant.log" | grep -F "granted=true" >/dev/null \
    || fail_smoke "endpoint-agent-consent-not-granted"
  export_recording_tsv
  export_viewer_audit_chain_jsonl
  build_viewer_audit_summary

  close_code="$(curl_json POST "$operator_base" "/sessions/${SESSION_ID}/close" "$OPERATOR_TOKEN_FILE" "${EVIDENCE_DIR}/close.body")"
  [[ "$close_code" == "204" || "$close_code" == "200" || "$close_code" == "404" ]] \
    || fail_smoke "close-session unexpected http ${close_code}"

  status="accepted-candidate"
  reason="VIEW_ONLY attended product-channel smoke produced finalizer-compatible evidence"
  write_summary
  write_sha256sums
  auto_finalize_if_requested
  echo "ACCEPTED_CANDIDATE evidence_dir=${EVIDENCE_DIR}"
}

main "$@"
