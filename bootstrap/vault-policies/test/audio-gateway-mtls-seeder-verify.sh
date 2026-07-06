#!/usr/bin/env bash
# Test scaffold — verify the `audio-gateway-mtls-seeder` AppRole boundary
# (Faz 24 direct-STT app-mTLS, I7). TEST Vault only.
#
# Reviewed: Codex thread `019f1124` (separate-AppRole + negative-capability
# boundary). Mirrors bootstrap-writer-verify.sh.
#
# Pre-condition:
#   - test Vault has policies `audio-gateway-mtls-seeder` written + the dedicated
#     AppRole `audio-gateway-mtls-seeder-test` bound (README §6.5).
#   - export ROLE_ID="<role-id>"
#   - secret-id at /tmp/ag-mtls-seeder-secret-id.txt (perms 600)
#
# Usage:
#   export ROLE_ID="<role-id>"
#   bash bootstrap/vault-policies/test/audio-gateway-mtls-seeder-verify.sh
#
# Exit: 0 = boundary holds, 1 = capability or negative-test failure.

set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8201}"   # platform-vault-test
SECRET_ID_FILE="${SECRET_ID_FILE:-/tmp/ag-mtls-seeder-secret-id.txt}"

if [[ -z "${ROLE_ID:-}" ]]; then
  echo "ERROR: ROLE_ID not set (export ROLE_ID=<role-id>)." >&2
  exit 1
fi
if [[ ! -f "$SECRET_ID_FILE" ]]; then
  echo "ERROR: secret-id file not found at $SECRET_ID_FILE" >&2
  exit 1
fi
SECRET_ID=$(cat "$SECRET_ID_FILE")

TOKEN=$(curl -sf -X POST "$VAULT_ADDR/v1/auth/approle/login" \
  -d "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$SECRET_ID\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["auth"]["client_token"])')
if [[ -z "$TOKEN" ]]; then
  echo "ERROR: AppRole login failed; check role-id + secret-id." >&2
  exit 1
fi
trap 'unset TOKEN SECRET_ID' EXIT

PASS=0; FAIL=0

caps_of() {
  curl -sf -X POST -H "X-Vault-Token: $TOKEN" \
    "$VAULT_ADDR/v1/sys/capabilities-self" \
    -d "{\"paths\":[\"$1\"]}" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(','.join(sorted(d['capabilities'])))"
}

assert_caps() {
  local label="$1" path="$2" expected="$3" got
  got=$(caps_of "$path")
  if [[ "$got" == "$expected" ]]; then
    echo "  PASS  $label  ($got)"; PASS=$((PASS + 1))
  else
    echo "  FAIL  $label  (got: $got; expected: $expected)"; FAIL=$((FAIL + 1))
  fi
}

assert_http_403() {
  local label="$1" method="$2" path="$3" body="${4:-}" code
  if [[ -n "$body" ]]; then
    code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" \
      -H "X-Vault-Token: $TOKEN" "$VAULT_ADDR/v1/$path" -d "$body")
  else
    code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" \
      -H "X-Vault-Token: $TOKEN" "$VAULT_ADDR/v1/$path")
  fi
  if [[ "$code" == "403" ]]; then
    echo "  PASS  $label  (HTTP 403)"; PASS=$((PASS + 1))
  else
    echo "  FAIL  $label  (expected HTTP 403, got HTTP $code)"; FAIL=$((FAIL + 1))
  fi
}

echo "=== Positive — exact capabilities (least-privilege shape) ==="
# Additive PATCH only on the KV path — NOT create/update (no full overwrite).
assert_caps "kv audio-gateway-service = patch,read" \
  "kv/data/platform/audio-gateway-service" "patch,read"
# Issue the single client role.
assert_caps "pki issue/audio-gateway-client = update" \
  "pki-denetim-ai/issue/audio-gateway-client" "update"
assert_caps "pki roles/audio-gateway-client = read" \
  "pki-denetim-ai/roles/audio-gateway-client" "read"
assert_caps "pki cert/ca = read" \
  "pki-denetim-ai/cert/ca" "read"

echo ""
echo "=== Negative — boundary tests (must be HTTP 403) ==="
# KV: no full overwrite (POST create/update), no destroy on the seed path.
assert_http_403 "KV full-overwrite POST (create/update) denied" \
  POST "kv/data/platform/audio-gateway-service" '{"data":{"x":"y"}}'
assert_http_403 "KV destroy denied" \
  POST "kv/destroy/platform/audio-gateway-service" '{"versions":[1]}'
# KV: foreign service path denied entirely.
assert_http_403 "KV foreign-path PATCH denied" \
  PATCH "kv/data/platform/permission-service" '{"data":{"x":"y"}}'
# PKI: server cert + arbitrary sign + root + config + revoke denied.
assert_http_403 "PKI server-cert issue denied" \
  POST "pki-denetim-ai/issue/denetim-ai-server" '{"common_name":"live-stt.denetim"}'
assert_http_403 "PKI sign denied" \
  POST "pki-denetim-ai/sign/audio-gateway-client" '{"csr":"x"}'
assert_http_403 "PKI root generate denied" \
  POST "pki-denetim-ai/root/generate/internal" '{"common_name":"x"}'
assert_http_403 "PKI config/urls write denied" \
  POST "pki-denetim-ai/config/urls" '{"issuing_certificates":"x"}'
assert_http_403 "PKI revoke denied" \
  POST "pki-denetim-ai/revoke" '{"serial_number":"00"}'
# Vault admin / auth / identity denied.
assert_http_403 "sys/policy write denied" \
  PUT "sys/policy/audio-gateway-mtls-seeder" \
  '{"policy":"path \"foo\" { capabilities = [\"sudo\"] }"}'
assert_http_403 "auth/approle role write denied" \
  POST "auth/approle/role/foo" '{"token_ttl":"1h"}'
assert_http_403 "auth/token create denied" \
  POST "auth/token/create" '{"policies":["root"]}'

echo ""
echo "=== Summary ==="
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"
echo ""
if [[ "$FAIL" -gt 0 ]]; then
  echo "BOUNDARY VIOLATION DETECTED — DO NOT USE THIS APPROLE." >&2
  exit 1
fi
echo "OK — audio-gateway-mtls-seeder boundary verified (least-privilege + additive)."
