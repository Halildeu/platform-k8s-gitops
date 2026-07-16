#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/scripts/faz22-remote-ops/faz22-6-view-only-attended-smoke.sh"

curl_json_function="$(sed -n '/^curl_json() {$/,/^}$/p' "$SCRIPT")"
assert_http_function="$(sed -n '/^assert_http() {$/,/^}$/p' "$SCRIPT")"
retry_function="$(sed -n '/^open_session_after_agent_reconnect() {$/,/^}$/p' "$SCRIPT")"
[[ -n "$curl_json_function" && -n "$assert_http_function" && -n "$retry_function" ]]

test_curl_json_preserves_transport_failure() (
  local tmp status
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT

  # shellcheck disable=SC2329 # Called by the extracted runtime function.
  curl() {
    printf '404'
    return 7
  }

  eval "$curl_json_function"
  set +e
  curl_json GET "http://operator.invalid" /sessions "" "$tmp/body" >/dev/null
  status=$?
  set -e
  [[ "$status" == "7" ]]
)

run_case() (
  set -u
  local responses="$1" expected_status="$2" expected_failure="${3:-}"
  local tmp response_file failure_file status
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  response_file="$tmp/responses"
  failure_file="$tmp/failure"
  printf '%b' "$responses" > "$response_file"

  EVIDENCE_DIR="$tmp/evidence"
  OPERATOR_TOKEN_FILE="$tmp/operator.jwt"
  # shellcheck disable=SC2034 # Used by the extracted runtime function via eval.
  OPEN_SESSION_DEVICE_READY_SECONDS=30
  # shellcheck disable=SC2034 # Used by the extracted runtime function via eval.
  OPEN_SESSION_DEVICE_READY_INTERVAL_SECONDS=5
  # shellcheck disable=SC2034 # Written by the extracted runtime function.
  open_code=""
  mkdir -p "$EVIDENCE_DIR"
  : > "$OPERATOR_TOKEN_FILE"

  # shellcheck disable=SC2329 # Called by the extracted runtime function.
  curl_json() {
    local response next_file
    response="$(head -n 1 "$response_file")"
    next_file="${response_file}.next"
    tail -n +2 "$response_file" > "$next_file"
    mv "$next_file" "$response_file"
    [[ -n "$response" ]] || response="404"
    if [[ "$response" == "transport" ]]; then
      return 7
    fi
    printf '%s' "$response"
  }

  # shellcheck disable=SC2329 # Called by the extracted runtime function.
  fail_smoke() {
    printf '%s' "$1" > "$failure_file"
    exit 91
  }

  # shellcheck disable=SC2329 # Called by the extracted runtime function.
  sleep() {
    SECONDS=$((SECONDS + $1))
  }

  eval "$assert_http_function"
  eval "$retry_function"

  set +e
  (open_session_after_agent_reconnect "http://operator.invalid" '{}') >/dev/null 2>&1
  status=$?
  set -e

  [[ "$status" == "$expected_status" ]]
  if [[ -n "$expected_failure" ]]; then
    [[ -s "$failure_file" ]]
    [[ "$(cat "$failure_file")" == "$expected_failure" ]]
  else
    [[ ! -e "$failure_file" ]]
  fi

  if [[ "$expected_status" == "0" ]]; then
    [[ "$(wc -l < "${EVIDENCE_DIR}/open-session-readiness.log" | tr -d ' ')" == "2" ]]
    grep -Fq 'result=http-404' "${EVIDENCE_DIR}/open-session-readiness.log"
    grep -Fq 'result=http-200' "${EVIDENCE_DIR}/open-session-readiness.log"
  fi
)

test_curl_json_preserves_transport_failure
run_case '404\n200\n' 0
run_case '500\n' 91 'open-session-http-500-expected-200'
run_case 'transport\n' 91 'open-session-transport-failure'
run_case '404\n' 91 'open-session-device-not-connected-timeout'

echo "ok"
