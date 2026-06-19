#!/usr/bin/env bash
set -euo pipefail

# Faz 22.6.1 Remote Ops Operation Catalog smoke.
#
# This script is intentionally read-only against Kubernetes. It may open a
# local port-forward to the owner-gated remote-bridge broker, then exercises
# the operator REST catalog surface. It does not mutate Deployments, images,
# sessions, Vault, or GitOps desired-state.

CONTEXT="${KUBE_CONTEXT:-k3d-test}"
NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
REMOTE_BRIDGE_NAME="${REMOTE_BRIDGE_NAME:-endpoint-admin-remote-bridge}"
LOCAL_PORT="${REMOTE_BRIDGE_LOCAL_PORT:-18096}"
BASE_URL="${REMOTE_BRIDGE_OPERATOR_BASE_URL:-}"
SESSION_ID="${REMOTE_BRIDGE_SESSION_ID:-}"
CATALOG_OPERATION_ID="${CATALOG_OPERATION_ID:-GET_HOSTNAME}"
EXPECTED_OPERATION_KIND="${EXPECTED_OPERATION_KIND:-PERMIT}"
REQUIRE_OPERATION="${REQUIRE_OPERATION:-0}"
TOKEN="${OPERATOR_BEARER_TOKEN:-}"
CURL_TIMEOUT="${CURL_TIMEOUT_SECONDS:-15}"
EVIDENCE_DIR="${EVIDENCE_DIR:-/tmp/remote-ops-catalog-smoke-$(date -u +%Y%m%dT%H%M%SZ)}"

PORT_FORWARD_PID=""

die() {
  printf 'ERR %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

cleanup() {
  if [[ -n "$PORT_FORWARD_PID" ]] && kill -0 "$PORT_FORWARD_PID" >/dev/null 2>&1; then
    kill "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
  fi
}

safe_label() {
  printf '%s' "$1" | tr -cs 'A-Za-z0-9_.-' '-'
}

start_port_forward_if_needed() {
  if [[ -n "$BASE_URL" ]]; then
    BASE_URL="${BASE_URL%/}"
    return 0
  fi

  need_cmd kubectl
  kubectl config get-contexts -o name 2>/dev/null | grep -Fxq "$CONTEXT" \
    || die "kubectl context missing: $CONTEXT"
  kubectl --context "$CONTEXT" -n "$NAMESPACE" get deploy "$REMOTE_BRIDGE_NAME" >/dev/null \
    || die "remote bridge deployment missing: $REMOTE_BRIDGE_NAME"

  kubectl --context "$CONTEXT" -n "$NAMESPACE" \
    port-forward "deploy/${REMOTE_BRIDGE_NAME}" "${LOCAL_PORT}:8096" \
    >"${EVIDENCE_DIR}/port-forward.log" 2>&1 &
  PORT_FORWARD_PID="$!"
  trap cleanup EXIT

  BASE_URL="http://127.0.0.1:${LOCAL_PORT}/internal/remote-bridge/operator"
  local code=""
  for _ in $(seq 1 30); do
    if ! kill -0 "$PORT_FORWARD_PID" >/dev/null 2>&1; then
      sed 's/^/PORT_FORWARD /' "${EVIDENCE_DIR}/port-forward.log" >&2 || true
      die "port-forward exited before the operator REST surface responded"
    fi
    code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
      --max-time 2 "${BASE_URL}/operation-catalog" || true)"
    if [[ "$code" =~ ^(200|401|403|404)$ ]]; then
      return 0
    fi
    sleep 1
  done
  sed 's/^/PORT_FORWARD /' "${EVIDENCE_DIR}/port-forward.log" >&2 || true
  die "operator REST surface did not respond through port-forward"
}

curl_request() {
  local method="$1" path="$2" auth_mode="$3" label="$4" body="${5:-}"
  local safe out req code_file url
  safe="$(safe_label "$label")"
  out="${EVIDENCE_DIR}/${safe}.body"
  req="${EVIDENCE_DIR}/${safe}.request.json"
  code_file="${EVIDENCE_DIR}/${safe}.code"
  url="${BASE_URL}${path}"

  local args=(
    --silent
    --show-error
    --max-time "$CURL_TIMEOUT"
    --request "$method"
    --output "$out"
    --write-out '%{http_code}'
    --header 'Content-Type: application/json'
  )

  if [[ -n "$body" ]]; then
    printf '%s' "$body" > "$req"
    args+=(--data-binary "@${req}")
  fi

  if [[ "$auth_mode" == "auth" ]]; then
    [[ -n "$TOKEN" ]] || die "OPERATOR_BEARER_TOKEN is required for authenticated catalog smoke"
    # Keep the bearer token out of argv. curl reads this header from stdin.
    printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" \
      | curl --config - "${args[@]}" "$url" > "$code_file"
  else
    curl "${args[@]}" "$url" > "$code_file"
  fi
  tr -d '\n' < "$code_file"
}

expect_code() {
  local actual="$1" expected="$2" label="$3"
  if [[ "$actual" != "$expected" ]]; then
    printf 'ERR %s expected_http=%s actual_http=%s\n' "$label" "$expected" "$actual" >&2
    local body
    body="${EVIDENCE_DIR}/$(safe_label "$label").body"
    [[ -f "$body" ]] && sed 's/^/BODY /' "$body" >&2
    exit 1
  fi
}

assert_json() {
  local file="$1" filter="$2" label="$3"
  if ! jq -e "$filter" "$file" >/dev/null; then
    printf 'ERR json assertion failed: %s\n' "$label" >&2
    sed 's/^/BODY /' "$file" >&2 || true
    exit 1
  fi
}

sha256_manifest() {
  (
    cd "$EVIDENCE_DIR"
    local sums_file
    sums_file="$(mktemp "${TMPDIR:-/tmp}/remote-ops-catalog-sha256.XXXXXX")"
    find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
      | sort -z \
      | xargs -0 shasum -a 256 \
      > "$sums_file"
    mv "$sums_file" SHA256SUMS
  )
}

main() {
  need_cmd curl
  need_cmd jq
  mkdir -p "$EVIDENCE_DIR"

  start_port_forward_if_needed

  printf 'INFO base_url=%s\n' "$BASE_URL"
  printf 'INFO evidence_dir=%s\n' "$EVIDENCE_DIR"

  local code
  code="$(curl_request GET /operation-catalog noauth noauth-catalog)"
  expect_code "$code" 401 noauth-catalog

  code="$(curl_request GET /operation-catalog auth catalog)"
  expect_code "$code" 200 catalog
  assert_json "${EVIDENCE_DIR}/catalog.body" \
    'any(.[]; .id == "GET_HOSTNAME" and .enabled == true and .operation == "PTY_COMMAND" and .requiredCapability == "CONSTRAINED_PTY")' \
    "GET_HOSTNAME enabled catalog entry"
  assert_json "${EVIDENCE_DIR}/catalog.body" \
    'any(.[]; .id == "GET_NETWORK_SUMMARY" and .enabled == true and .operation == "PTY_COMMAND" and .requiredCapability == "CONSTRAINED_PTY")' \
    "GET_NETWORK_SUMMARY enabled catalog entry"
  assert_json "${EVIDENCE_DIR}/catalog.body" \
    'any(.[]; .id == "GET_SERVICE_STATUS" and .enabled == false and .disabledReason == "service-status-argument-policy-not-implemented")' \
    "GET_SERVICE_STATUS disabled fail-closed entry"

  local status="catalog-ready"
  local operation_status="skipped-session-required"
  local op_id
  op_id="op-catalog-$(date -u +%Y%m%dT%H%M%SZ)"

  if [[ -n "$SESSION_ID" ]]; then
    local raw_body disabled_body override_body allowed_body
    raw_body="$(jq -nc --arg op "${op_id}-raw" \
      '{operationId:$op, operation:"PTY_COMMAND", commandLine:"hostname"}')"
    code="$(curl_request POST "/sessions/${SESSION_ID}/operations" auth raw-pty-deny "$raw_body")"
    expect_code "$code" 400 raw-pty-deny
    assert_json "${EVIDENCE_DIR}/raw-pty-deny.body" \
      '.reason == "catalog-operation-required"' \
      "raw PTY without catalog id is denied before service"

    disabled_body="$(jq -nc --arg op "${op_id}-disabled" \
      '{operationId:$op, catalogOperationId:"GET_SERVICE_STATUS"}')"
    code="$(curl_request POST "/sessions/${SESSION_ID}/operations" auth disabled-catalog-deny "$disabled_body")"
    expect_code "$code" 422 disabled-catalog-deny
    assert_json "${EVIDENCE_DIR}/disabled-catalog-deny.body" \
      '.reason == "catalog-operation-disabled"' \
      "disabled catalog id is fail-closed"

    override_body="$(jq -nc --arg op "${op_id}-override" --arg catalog "$CATALOG_OPERATION_ID" \
      '{operationId:$op, catalogOperationId:$catalog, commandLine:"hostname"}')"
    code="$(curl_request POST "/sessions/${SESSION_ID}/operations" auth command-override-deny "$override_body")"
    expect_code "$code" 400 command-override-deny
    assert_json "${EVIDENCE_DIR}/command-override-deny.body" \
      '.reason == "catalog-command-override"' \
      "catalog command override is denied before service"

    allowed_body="$(jq -nc --arg op "$op_id" --arg catalog "$CATALOG_OPERATION_ID" \
      '{operationId:$op, catalogOperationId:$catalog}')"
    code="$(curl_request POST "/sessions/${SESSION_ID}/operations" auth catalog-operation "$allowed_body")"
    expect_code "$code" 200 catalog-operation
    if ! jq -e --arg kind "$EXPECTED_OPERATION_KIND" --arg catalog "$CATALOG_OPERATION_ID" \
      '.kind == $kind and .catalogOperationId == $catalog' \
      "${EVIDENCE_DIR}/catalog-operation.body" >/dev/null; then
      printf 'ERR json assertion failed: catalog operation returns expected broker kind\n' >&2
      sed 's/^/BODY /' "${EVIDENCE_DIR}/catalog-operation.body" >&2 || true
      exit 1
    fi
    if [[ "$EXPECTED_OPERATION_KIND" == "PERMIT" ]]; then
      assert_json "${EVIDENCE_DIR}/catalog-operation.body" \
        '.transportPushed == true and .deny == null and .permit.signaturePresent == true and .permit.freshAtResponseTime == true and .permit.capability == "CONSTRAINED_PTY"' \
        "catalog operation PERMIT carries bounded permit metadata and transport"
      operation_status="permit-transport-pushed"
      status="accepted-candidate"
    else
      operation_status="non-permit-expected-${EXPECTED_OPERATION_KIND}"
    fi
  elif [[ "$REQUIRE_OPERATION" == "1" ]]; then
    die "REMOTE_BRIDGE_SESSION_ID is required when REQUIRE_OPERATION=1"
  fi

  jq -n \
    --arg status "$status" \
    --arg operationStatus "$operation_status" \
    --arg catalogOperationId "$CATALOG_OPERATION_ID" \
    --arg expectedOperationKind "$EXPECTED_OPERATION_KIND" \
    --arg baseUrl "$BASE_URL" \
    --arg evidenceDir "$EVIDENCE_DIR" \
    --arg sessionPresent "$([[ -n "$SESSION_ID" ]] && printf true || printf false)" \
    '{
      status: $status,
      operationStatus: $operationStatus,
      catalogOperationId: $catalogOperationId,
      expectedOperationKind: $expectedOperationKind,
      baseUrl: $baseUrl,
      evidenceDir: $evidenceDir,
      sessionPresent: ($sessionPresent == "true"),
      doesNotProve: [
        "Approved Script Runner",
        "interactive terminal",
        "unrestricted shell",
        "file transfer",
        "production remote-support readiness",
        "broad rollout",
        "true TPM/device-key hardware attestation"
      ]
    }' > "${EVIDENCE_DIR}/summary.json"

  sha256_manifest
  printf 'REMOTE_OPS_CATALOG_SMOKE_STATUS=%s operation=%s evidence_dir=%s\n' \
    "$status" "$operation_status" "$EVIDENCE_DIR"
}

main "$@"
