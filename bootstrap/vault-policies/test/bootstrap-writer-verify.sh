#!/usr/bin/env bash
# Test scaffold — verify `platform-bootstrap-writer` AppRole boundary on test vault.
#
# DR-2 of ADR-0010 (`docs/adr/0010-vault-credential-lifecycle-and-dr.md`).
# Codex consensus thread `019dd2c9`.
#
# Pre-condition:
#   - DR-2 runbook Steps 1-4 completed (`docs/RB-vault-bootstrap-writer-apply.md`)
#   - Operator has the role-id (export ROLE_ID)
#   - secret-id at /tmp/bootstrap-writer-secret-id.txt (perms 600)
#
# Usage:
#   export ROLE_ID="<from runbook step 4>"
#   bash bootstrap/vault-policies/test/bootstrap-writer-verify.sh
#
# Exit: 0 = boundary holds, 1 = capability or negative-test failure.

set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8301}"
SECRET_ID_FILE="${SECRET_ID_FILE:-/tmp/bootstrap-writer-secret-id.txt}"

if [[ -z "${ROLE_ID:-}" ]]; then
  echo "ERROR: ROLE_ID environment variable not set." >&2
  echo "       export ROLE_ID=\"<from runbook step 4>\"" >&2
  exit 1
fi

if [[ ! -f "$SECRET_ID_FILE" ]]; then
  echo "ERROR: secret-id file not found at $SECRET_ID_FILE" >&2
  echo "       Run DR-2 runbook step 4 first." >&2
  exit 1
fi

SECRET_ID=$(cat "$SECRET_ID_FILE")

# --- AppRole login ---
TOKEN=$({ printf '%s\n' "$ROLE_ID"; printf '%s\n' "$SECRET_ID"; } \
  | python3 -c 'import json,sys; print(json.dumps({"role_id": sys.stdin.readline().rstrip("\n"), "secret_id": sys.stdin.readline().rstrip("\n")}))' \
  | curl -sf -X POST "$VAULT_ADDR/v1/auth/approle/login" --data-binary @- \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["auth"]["client_token"])')

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: AppRole login failed; check role-id + secret-id." >&2
  exit 1
fi

TOKEN_HEADER_FILE=$(mktemp)
chmod 600 "$TOKEN_HEADER_FILE"
printf 'X-Vault-Token: %s' "$TOKEN" > "$TOKEN_HEADER_FILE"
cleanup() {
  if [[ -f "${TOKEN_HEADER_FILE:-}" ]]; then
    if command -v shred >/dev/null 2>&1; then
      shred -u "$TOKEN_HEADER_FILE"
    else
      : > "$TOKEN_HEADER_FILE"
      rm -f "$TOKEN_HEADER_FILE"
    fi
  fi
  unset TOKEN SECRET_ID
}
trap cleanup EXIT

PASS=0
FAIL=0

assert_pass() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "  PASS  $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $label"
    FAIL=$((FAIL + 1))
  fi
}

assert_http_403() {
  local label="$1"
  local method="$2"
  local path="$3"
  local body="${4:-}"
  local code
  if [[ -n "$body" ]]; then
    code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" \
      -H @"$TOKEN_HEADER_FILE" "$VAULT_ADDR/v1/$path" -d "$body")
  else
    code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" \
      -H @"$TOKEN_HEADER_FILE" "$VAULT_ADDR/v1/$path")
  fi
  if [[ "$code" == "403" ]]; then
    echo "  PASS  $label  (HTTP 403)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $label  (expected HTTP 403, got HTTP $code)"
    FAIL=$((FAIL + 1))
  fi
}

# ============================================================================
# Positive — capabilities-self for each platform service path
# ============================================================================

echo "=== Positive — capabilities-self ==="

services=(auth-service user-service variant-service core-data-service \
          report-service schema-service permission-service \
          cross-ai-deployment-protection-test openfga)

for svc in "${services[@]}"; do
  caps=$(curl -sf -X POST -H @"$TOKEN_HEADER_FILE" \
    "$VAULT_ADDR/v1/sys/capabilities-self" \
    -d "{\"paths\":[\"kv/data/platform/$svc\"]}" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(','.join(sorted(d['capabilities'])))")
  expected="create,read,update"
  if [[ "$caps" == "$expected" ]]; then
    echo "  PASS  $svc kv/data write capability  ($caps)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $svc kv/data write capability  (got: $caps; expected: $expected)"
    FAIL=$((FAIL + 1))
  fi
done

# ============================================================================
# Negative — boundary verification (every test must return HTTP 403)
# ============================================================================

echo ""
echo "=== Negative — boundary tests ==="

assert_http_403 "DELETE on kv/metadata" \
  DELETE "kv/metadata/platform/permission-service"

assert_http_403 "DELETE on kv/destroy" \
  POST "kv/destroy/platform/permission-service" \
  '{"versions":[1]}'

assert_http_403 "sys/policy write" \
  PUT "sys/policy/platform-bootstrap-writer" \
  '{"policy":"path \"foo\" { capabilities = [\"sudo\"] }"}'

assert_http_403 "sys/generate-root attempt" \
  POST "sys/generate-root/attempt" '{}'

assert_http_403 "auth/approle role write" \
  POST "auth/approle/role/platform-bootstrap-writer" \
  '{"token_ttl":"1h"}'

assert_http_403 "auth/token create" \
  POST "auth/token/create" \
  '{"policies":["root"]}'

assert_http_403 "auth/token revoke-accessor" \
  POST "auth/token/revoke-accessor" \
  '{"accessor":"00000000-0000-0000-0000-000000000000"}'

assert_http_403 "kv/data write on foreign path" \
  POST "kv/data/platform/non-existent-service" \
  '{"data":{"foo":"bar"}}'

assert_http_403 "sys/audit write" \
  PUT "sys/audit/file" \
  '{"type":"file","options":{"file_path":"/tmp/audit"}}'

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "=== Summary ==="
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
  echo "BOUNDARY VIOLATION DETECTED — DO NOT DEPLOY." >&2
  exit 1
fi

# Self-revoke the AppRole token (defense-in-depth; TTL would expire anyway)
curl -sf -X POST -H @"$TOKEN_HEADER_FILE" \
  "$VAULT_ADDR/v1/auth/token/revoke-self" >/dev/null

echo "OK — bootstrap-writer boundary verified."
echo "Token revoked. Proceed to DR-3 (wrapper script)."
