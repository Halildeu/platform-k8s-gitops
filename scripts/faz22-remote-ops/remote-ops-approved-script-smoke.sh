#!/usr/bin/env bash
# shellcheck disable=SC2016 # jq filters intentionally use jq variables such as $id.
set -euo pipefail

# Faz 22.6.2 Approved Script Runner smoke.
#
# Read-only against Kubernetes except for an optional local port-forward. It
# exercises the operator REST approved-script surface and, when a session id is
# supplied, submits the server-owned DIAG_HOSTNAME approved script through the
# existing remote-bridge product path. It never sends arbitrary script bodies as
# an allowed operation; raw script text is used only as a negative test.

CONTEXT="${KUBE_CONTEXT:-k3d-test}"
NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
REMOTE_BRIDGE_NAME="${REMOTE_BRIDGE_NAME:-endpoint-admin-remote-bridge}"
LOCAL_PORT="${REMOTE_BRIDGE_LOCAL_PORT:-18096}"
BASE_URL="${REMOTE_BRIDGE_OPERATOR_BASE_URL:-}"
SESSION_ID="${REMOTE_BRIDGE_SESSION_ID:-}"
APPROVED_SCRIPT_ID="${APPROVED_SCRIPT_ID:-DIAG_HOSTNAME}"
APPROVED_SCRIPT_VERSION="${APPROVED_SCRIPT_VERSION:-1}"
EXPECTED_OPERATION_KIND="${EXPECTED_OPERATION_KIND:-PERMIT}"
REQUIRE_OPERATION="${REQUIRE_OPERATION:-0}"
REQUIRE_DISABLED_REVOKED_FIXTURES="${REQUIRE_DISABLED_REVOKED_FIXTURES:-0}"
TOKEN="${OPERATOR_BEARER_TOKEN:-}"
CURL_TIMEOUT="${CURL_TIMEOUT_SECONDS:-15}"
EVIDENCE_DIR="${EVIDENCE_DIR:-/tmp/remote-ops-approved-script-smoke-$(date -u +%Y%m%dT%H%M%SZ)}"

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

validate_token_for_curl_config() {
  [[ -n "$TOKEN" ]] || die "OPERATOR_BEARER_TOKEN is required for authenticated approved-script smoke"
  if [[ "$TOKEN" == *$'\n'* || "$TOKEN" == *$'\r'* || "$TOKEN" == *\"* || "$TOKEN" == *\\* ]]; then
    die "OPERATOR_BEARER_TOKEN contains a character unsafe for curl --config stdin"
  fi
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
      --max-time 2 "${BASE_URL}/approved-scripts" || true)"
    if [[ "$code" =~ ^(200|401|403|404)$ ]]; then
      return 0
    fi
    sleep 1
  done
  sed 's/^/PORT_FORWARD /' "${EVIDENCE_DIR}/port-forward.log" >&2 || true
  die "operator approved-script surface did not respond through port-forward"
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
    validate_token_for_curl_config
    # Keep the bearer token out of argv. curl reads this header from stdin.
    if ! printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" \
      | curl --config - "${args[@]}" "$url" > "$code_file"; then
      die "curl request failed: ${label} ${method} ${path}"
    fi
  else
    if ! curl "${args[@]}" "$url" > "$code_file"; then
      die "curl request failed: ${label} ${method} ${path}"
    fi
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

assert_jq() {
  local file="$1" label="$2"
  shift 2
  if ! jq -e "$@" "$file" >/dev/null; then
    printf 'ERR json assertion failed: %s\n' "$label" >&2
    sed 's/^/BODY /' "$file" >&2 || true
    exit 1
  fi
}

sha256_manifest() {
  (
    cd "$EVIDENCE_DIR"
    local hasher=() sums_file
    if command -v shasum >/dev/null 2>&1; then
      hasher=(shasum -a 256)
    elif command -v sha256sum >/dev/null 2>&1; then
      hasher=(sha256sum)
    else
      die "missing command: shasum or sha256sum"
    fi
    sums_file="$(mktemp "${TMPDIR:-/tmp}/remote-ops-approved-script-sha256.XXXXXX")"
    find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
      | sort -z \
      | xargs -0 "${hasher[@]}" \
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

  local code script_hash disabled_hash revoked_hash disabled_fixture_status revoked_fixture_status
  code="$(curl_request GET /approved-scripts noauth noauth-approved-scripts)"
  expect_code "$code" 401 noauth-approved-scripts

  code="$(curl_request GET /approved-scripts auth approved-scripts)"
  expect_code "$code" 200 approved-scripts
  assert_jq "${EVIDENCE_DIR}/approved-scripts.body" \
    "approved script is enabled and step-up gated" \
    --arg id "$APPROVED_SCRIPT_ID" --arg version "$APPROVED_SCRIPT_VERSION" \
    'any(.[]; .scriptId == $id and (.version | tostring) == $version and .enabled == true and .revoked == false and .requiredCapability == "CONSTRAINED_PTY" and (.approvalRequirements | index("WEBAUTHN_STEP_UP")))'
  assert_json "${EVIDENCE_DIR}/approved-scripts.body" \
    'all(.[]; has("scriptBody") | not) and all(.[]; has("commandTemplate") | not)' \
    "catalog response does not expose script body or command template"

  script_hash="$(jq -r --arg id "$APPROVED_SCRIPT_ID" --arg version "$APPROVED_SCRIPT_VERSION" \
    '.[] | select(.scriptId == $id and (.version | tostring) == $version) | .scriptHash' \
    "${EVIDENCE_DIR}/approved-scripts.body" | head -n 1)"
  [[ "$script_hash" =~ ^[0-9a-f]{64}$ ]] || die "approved script hash missing or invalid"
  disabled_hash="$(jq -r '.[] | select(.scriptId == "DIAG_IPCONFIG" and (.version | tostring) == "1" and .enabled == false) | .scriptHash' \
    "${EVIDENCE_DIR}/approved-scripts.body" | head -n 1)"
  revoked_hash="$(jq -r '.[] | select(.scriptId == "COLLECT_SUPPORT_BUNDLE" and (.version | tostring) == "1" and .revoked == true) | .scriptHash' \
    "${EVIDENCE_DIR}/approved-scripts.body" | head -n 1)"
  disabled_fixture_status="skipped-fixture-not-present"
  revoked_fixture_status="skipped-fixture-not-present"
  if [[ "$disabled_hash" =~ ^[0-9a-f]{64}$ ]]; then
    disabled_fixture_status="catalog-present"
  elif [[ "$REQUIRE_DISABLED_REVOKED_FIXTURES" == "1" ]]; then
    die "disabled DIAG_IPCONFIG fixture missing; unset REQUIRE_DISABLED_REVOKED_FIXTURES or seed the fixture"
  else
    printf 'WARN disabled DIAG_IPCONFIG fixture not present; disabled-script deny smoke will be skipped\n' >&2
  fi
  if [[ "$revoked_hash" =~ ^[0-9a-f]{64}$ ]]; then
    revoked_fixture_status="catalog-present"
  elif [[ "$REQUIRE_DISABLED_REVOKED_FIXTURES" == "1" ]]; then
    die "revoked COLLECT_SUPPORT_BUNDLE fixture missing; unset REQUIRE_DISABLED_REVOKED_FIXTURES or seed the fixture"
  else
    printf 'WARN revoked COLLECT_SUPPORT_BUNDLE fixture not present; revoked-script deny smoke will be skipped\n' >&2
  fi

  local status="approved-script-catalog-ready"
  local operation_status="skipped-session-required"
  local op_id
  op_id="op-approved-script-$(date -u +%Y%m%dT%H%M%SZ)"

  if [[ -n "$SESSION_ID" ]]; then
    local raw_body hash_body disabled_body revoked_body args_body allowed_body
    raw_body="$(jq -nc --arg op "${op_id}-raw" --arg id "$APPROVED_SCRIPT_ID" --arg version "$APPROVED_SCRIPT_VERSION" --arg hash "$script_hash" \
      '{operationId:$op, scriptId:$id, scriptVersion:$version, scriptHash:$hash, rawScriptText:"hostname"}')"
    code="$(curl_request POST "/sessions/${SESSION_ID}/approved-scripts" auth raw-script-deny "$raw_body")"
    expect_code "$code" 400 raw-script-deny
    assert_json "${EVIDENCE_DIR}/raw-script-deny.body" \
      '.reason == "approved-script-raw-text-denied"' \
      "raw script text is denied before broker dispatch"

    hash_body="$(jq -nc --arg op "${op_id}-hash" --arg id "$APPROVED_SCRIPT_ID" --arg version "$APPROVED_SCRIPT_VERSION" \
      '{operationId:$op, scriptId:$id, scriptVersion:$version, scriptHash:"0000000000000000000000000000000000000000000000000000000000000000"}')"
    code="$(curl_request POST "/sessions/${SESSION_ID}/approved-scripts" auth wrong-hash-deny "$hash_body")"
    expect_code "$code" 400 wrong-hash-deny
    assert_json "${EVIDENCE_DIR}/wrong-hash-deny.body" \
      '.reason == "approved-script-hash-mismatch"' \
      "changed script hash is denied before broker dispatch"

    if [[ "$disabled_fixture_status" == "catalog-present" ]]; then
      disabled_body="$(jq -nc --arg op "${op_id}-disabled" --arg hash "$disabled_hash" \
        '{operationId:$op, scriptId:"DIAG_IPCONFIG", scriptVersion:"1", scriptHash:$hash}')"
      code="$(curl_request POST "/sessions/${SESSION_ID}/approved-scripts" auth disabled-script-deny "$disabled_body")"
      expect_code "$code" 422 disabled-script-deny
      assert_json "${EVIDENCE_DIR}/disabled-script-deny.body" \
        '.reason == "approved-script-disabled"' \
        "disabled approved script is fail-closed"
      disabled_fixture_status="deny-verified"
    fi

    if [[ "$revoked_fixture_status" == "catalog-present" ]]; then
      revoked_body="$(jq -nc --arg op "${op_id}-revoked" --arg hash "$revoked_hash" \
        '{operationId:$op, scriptId:"COLLECT_SUPPORT_BUNDLE", scriptVersion:"1", scriptHash:$hash}')"
      code="$(curl_request POST "/sessions/${SESSION_ID}/approved-scripts" auth revoked-script-deny "$revoked_body")"
      expect_code "$code" 422 revoked-script-deny
      assert_json "${EVIDENCE_DIR}/revoked-script-deny.body" \
        '.reason == "approved-script-revoked"' \
        "revoked approved script is fail-closed"
      revoked_fixture_status="deny-verified"
    fi

    args_body="$(jq -nc --arg op "${op_id}-args" --arg id "$APPROVED_SCRIPT_ID" --arg version "$APPROVED_SCRIPT_VERSION" --arg hash "$script_hash" \
      '{operationId:$op, scriptId:$id, scriptVersion:$version, scriptHash:$hash, args:{extra:"value"}}')"
    code="$(curl_request POST "/sessions/${SESSION_ID}/approved-scripts" auth arg-schema-deny "$args_body")"
    expect_code "$code" 400 arg-schema-deny
    assert_json "${EVIDENCE_DIR}/arg-schema-deny.body" \
      '.reason == "approved-script-arg-schema-invalid"' \
      "unexpected args are denied before broker dispatch"

    allowed_body="$(jq -nc --arg op "$op_id" --arg id "$APPROVED_SCRIPT_ID" --arg version "$APPROVED_SCRIPT_VERSION" --arg hash "$script_hash" \
      '{operationId:$op, scriptId:$id, scriptVersion:$version, scriptHash:$hash}')"
    code="$(curl_request POST "/sessions/${SESSION_ID}/approved-scripts" auth approved-script-operation "$allowed_body")"
    expect_code "$code" 200 approved-script-operation
    if ! jq -e --arg kind "$EXPECTED_OPERATION_KIND" --arg id "$APPROVED_SCRIPT_ID" --arg version "$APPROVED_SCRIPT_VERSION" --arg hash "$script_hash" \
      '.kind == $kind and .approvedScript.scriptId == $id and .approvedScript.version == $version and .approvedScript.scriptHash == $hash and (.approvedScript.approvalRequirements | index("WEBAUTHN_STEP_UP"))' \
      "${EVIDENCE_DIR}/approved-script-operation.body" >/dev/null; then
      printf 'ERR json assertion failed: approved script operation returns expected broker kind and metadata\n' >&2
      sed 's/^/BODY /' "${EVIDENCE_DIR}/approved-script-operation.body" >&2 || true
      exit 1
    fi
    if [[ "$EXPECTED_OPERATION_KIND" == "PERMIT" ]]; then
      assert_json "${EVIDENCE_DIR}/approved-script-operation.body" \
        '.transportPushed == true and .deny == null and .permit.signaturePresent == true and .permit.freshAtResponseTime == true and .permit.capability == "CONSTRAINED_PTY"' \
        "approved script PERMIT carries bounded permit metadata and transport"
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
    --arg scriptId "$APPROVED_SCRIPT_ID" \
    --arg scriptVersion "$APPROVED_SCRIPT_VERSION" \
    --arg scriptHash "$script_hash" \
    --arg expectedOperationKind "$EXPECTED_OPERATION_KIND" \
    --arg baseUrl "$BASE_URL" \
    --arg evidenceDir "$EVIDENCE_DIR" \
    --arg disabledFixtureStatus "$disabled_fixture_status" \
    --arg revokedFixtureStatus "$revoked_fixture_status" \
    --arg sessionPresent "$([[ -n "$SESSION_ID" ]] && printf true || printf false)" \
    '{
      status: $status,
      operationStatus: $operationStatus,
      scriptId: $scriptId,
      scriptVersion: $scriptVersion,
      scriptHash: $scriptHash,
      expectedOperationKind: $expectedOperationKind,
      baseUrl: $baseUrl,
      evidenceDir: $evidenceDir,
      fixtureChecks: {
        disabledScriptDeny: $disabledFixtureStatus,
        revokedScriptDeny: $revokedFixtureStatus
      },
      sessionPresent: ($sessionPresent == "true"),
      doesNotProve: [
        "interactive terminal",
        "unrestricted shell",
        "file transfer",
        "production remote-support readiness",
        "broad rollout",
        "true TPM/device-key hardware attestation",
        "platform-web operator UX"
      ]
    }' > "${EVIDENCE_DIR}/summary.json"

  sha256_manifest
  printf 'REMOTE_OPS_APPROVED_SCRIPT_SMOKE_STATUS=%s operation=%s evidence_dir=%s\n' \
    "$status" "$operation_status" "$EVIDENCE_DIR"
}

main "$@"
