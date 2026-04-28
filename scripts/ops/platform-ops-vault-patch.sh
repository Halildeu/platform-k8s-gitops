#!/usr/bin/env bash
# platform-ops-vault-patch — KV v2 merge/patch via platform-bootstrap-writer
#                            AppRole. Root token NOT required.
#
# DR-3 of ADR-0010 (`docs/adr/0010-vault-credential-lifecycle-and-dr.md`).
# Codex consensus thread `019dd2c9`.
#
# Pre-conditions:
#   - DR-2 applied: `platform-bootstrap-writer` policy + AppRole exist on
#     target Vault (test or prod).
#   - role-id available (env VAULT_BOOTSTRAP_ROLE_ID or first arg).
#   - secret-id available (env VAULT_BOOTSTRAP_SECRET_ID or file path
#     via VAULT_BOOTSTRAP_SECRET_ID_FILE).
#
# Usage:
#   scripts/ops/platform-ops-vault-patch.sh \
#     --service permission-service \
#     --field reports_db_username=permission_reports_writer \
#     --field-from-stdin reports_db_password
#
# Flags:
#   --service <name>            Required. One of: auth-service, user-service,
#                               variant-service, core-data-service,
#                               report-service, schema-service,
#                               permission-service, openfga, ghcr-token
#                               (ghcr-token uses kv/data/gitops/ghcr-token).
#   --field key=value           Set a single key-value (value visible in argv;
#                               use --field-from-stdin for sensitive values).
#   --field-from-stdin <key>    Reads the key's value from stdin (one line).
#                               Repeatable.
#   --vault-addr <url>          Default: http://127.0.0.1:8301 (test).
#                               Use http://127.0.0.1:8200 for prod.
#   --dry-run                   Print the would-be PATCH body, don't write.
#   --help                      Show this message.
#
# Exit codes:
#   0   Success.
#   1   Generic error.
#   2   Missing pre-condition (role-id, secret-id, etc.).
#   3   Authentication failure.
#   4   Capability check failure (boundary violation suspected).
#   5   Vault HTTP write failure.
#
# Audit trail:
#   - Every successful invocation prints a correlation ID + timestamp + service
#     + field-name set (NOT field-values) to stderr; ops can grep ops logs.
#   - Token TTL is short-lived (per AppRole config); script also self-revokes.

set -euo pipefail

# ============================================================================
# Defaults + arg parsing
# ============================================================================

VAULT_ADDR_DEFAULT="http://127.0.0.1:8301"
VAULT_ADDR="${VAULT_ADDR:-$VAULT_ADDR_DEFAULT}"
SERVICE=""
declare -a FIELDS=()
declare -a STDIN_KEYS=()
DRY_RUN=0

usage() {
  sed -n '/^# platform-ops-vault-patch/,/^# Audit trail:/p' "$0" \
    | sed 's/^# \?//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      SERVICE="$2"; shift 2 ;;
    --field)
      FIELDS+=("$2"); shift 2 ;;
    --field-from-stdin)
      STDIN_KEYS+=("$2"); shift 2 ;;
    --vault-addr)
      VAULT_ADDR="$2"; shift 2 ;;
    --dry-run)
      DRY_RUN=1; shift ;;
    --help|-h)
      usage; exit 0 ;;
    *)
      echo "ERROR: unknown flag: $1" >&2
      usage >&2
      exit 1 ;;
  esac
done

# ============================================================================
# Pre-condition checks
# ============================================================================

if [[ -z "$SERVICE" ]]; then
  echo "ERROR: --service is required" >&2
  exit 2
fi

# Service path resolution
case "$SERVICE" in
  auth-service|user-service|variant-service|core-data-service|\
  report-service|schema-service|permission-service|openfga)
    KV_PATH="kv/data/platform/$SERVICE"
    ;;
  ghcr-token)
    KV_PATH="kv/data/gitops/ghcr-token"
    ;;
  *)
    echo "ERROR: unknown --service $SERVICE" >&2
    exit 2 ;;
esac

if [[ "${#FIELDS[@]}" -eq 0 && "${#STDIN_KEYS[@]}" -eq 0 ]]; then
  echo "ERROR: at least one --field or --field-from-stdin is required" >&2
  exit 2
fi

ROLE_ID="${VAULT_BOOTSTRAP_ROLE_ID:-${1:-}}"
if [[ -z "$ROLE_ID" ]]; then
  echo "ERROR: role-id missing (env VAULT_BOOTSTRAP_ROLE_ID or first arg)" >&2
  exit 2
fi

SECRET_ID="${VAULT_BOOTSTRAP_SECRET_ID:-}"
if [[ -z "$SECRET_ID" ]]; then
  SECRET_ID_FILE="${VAULT_BOOTSTRAP_SECRET_ID_FILE:-/tmp/bootstrap-writer-secret-id.txt}"
  if [[ ! -f "$SECRET_ID_FILE" ]]; then
    echo "ERROR: secret-id missing (env VAULT_BOOTSTRAP_SECRET_ID or file $SECRET_ID_FILE)" >&2
    exit 2
  fi
  SECRET_ID=$(cat "$SECRET_ID_FILE")
fi

# ============================================================================
# Read sensitive fields from stdin
# ============================================================================

declare -a STDIN_FIELD_PAIRS=()
for key in "${STDIN_KEYS[@]}"; do
  echo "Enter value for $key (1 line, hidden):" >&2
  IFS='' read -rs value
  echo "" >&2
  if [[ -z "$value" ]]; then
    echo "ERROR: empty value for $key" >&2
    exit 2
  fi
  STDIN_FIELD_PAIRS+=("$key=$value")
  unset value
done

# ============================================================================
# AppRole login → short-lived token
# ============================================================================

LOGIN_RESPONSE=$(curl -sf -X POST "$VAULT_ADDR/v1/auth/approle/login" \
  -d "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$SECRET_ID\"}" 2>&1) || {
  echo "ERROR: AppRole login failed (HTTP error). Output:" >&2
  echo "$LOGIN_RESPONSE" >&2
  exit 3
}

TOKEN=$(echo "$LOGIN_RESPONSE" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["auth"]["client_token"])' 2>/dev/null) || {
  echo "ERROR: AppRole login response missing client_token" >&2
  exit 3
}

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: empty token from AppRole login" >&2
  exit 3
fi

# Cleanup token + secrets on exit (defense-in-depth; TTL is short anyway)
cleanup() {
  if [[ -n "${TOKEN:-}" ]]; then
    curl -sf -X POST -H "X-Vault-Token: $TOKEN" \
      "$VAULT_ADDR/v1/auth/token/revoke-self" >/dev/null 2>&1 || true
  fi
  unset TOKEN SECRET_ID FIELDS STDIN_FIELD_PAIRS LOGIN_RESPONSE
}
trap cleanup EXIT

# ============================================================================
# capabilities-self check (fail-fast pattern)
# ============================================================================

CAPS=$(curl -sf -X POST -H "X-Vault-Token: $TOKEN" \
  "$VAULT_ADDR/v1/sys/capabilities-self" \
  -d "{\"paths\":[\"$KV_PATH\"]}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(','.join(sorted(d['capabilities'])))")

if ! echo "$CAPS" | grep -q 'create' || ! echo "$CAPS" | grep -q 'update'; then
  echo "ERROR: capabilities-self missing create/update on $KV_PATH" >&2
  echo "       got: $CAPS" >&2
  exit 4
fi

if echo "$CAPS" | grep -q 'delete'; then
  echo "WARNING: capabilities-self includes 'delete' on $KV_PATH" >&2
  echo "         (boundary violation — bootstrap-writer should NOT have delete)" >&2
  echo "         policy may be misconfigured. Aborting." >&2
  exit 4
fi

# ============================================================================
# Read existing data + merge fields (KV v2 patch semantic)
# ============================================================================

EXISTING_RESPONSE=$(curl -sf -H "X-Vault-Token: $TOKEN" \
  "$VAULT_ADDR/v1/$KV_PATH" 2>&1)

if echo "$EXISTING_RESPONSE" | grep -q '"errors"' \
   && echo "$EXISTING_RESPONSE" | grep -q '404'; then
  EXISTING_DATA="{}"
else
  EXISTING_DATA=$(echo "$EXISTING_RESPONSE" \
    | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin)["data"]["data"]))' 2>/dev/null) \
    || EXISTING_DATA="{}"
fi

# Merge new fields into existing data
PATCHED_DATA=$(python3 -c "
import json, sys
existing = json.loads('$EXISTING_DATA')
fields = '''$(IFS=$'\n'; echo "${FIELDS[*]:-}"
              IFS=$'\n'; echo "${STDIN_FIELD_PAIRS[*]:-}")'''
for line in fields.splitlines():
    line = line.strip()
    if not line:
        continue
    k, _, v = line.partition('=')
    if k:
        existing[k] = v
print(json.dumps({'data': existing}))
")

# ============================================================================
# Write (or dry-run)
# ============================================================================

CORRELATION_ID="vault-patch-$(date -u +%Y%m%dT%H%M%S)-$$"
FIELD_KEY_LIST=$(printf '%s\n' "${FIELDS[@]:-}" "${STDIN_FIELD_PAIRS[@]:-}" \
  | awk -F= '{print $1}' | sort -u | tr '\n' ',' | sed 's/,$//')

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "DRY-RUN — would PATCH $VAULT_ADDR/v1/$KV_PATH" >&2
  echo "DRY-RUN — fields: $FIELD_KEY_LIST" >&2
  echo "DRY-RUN — body (sensitive values redacted):" >&2
  python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
for k in d.get('data', {}):
    d['data'][k] = '***REDACTED***'
print(json.dumps(d, indent=2))
" <<<"$PATCHED_DATA" >&2
  exit 0
fi

WRITE_RESPONSE=$(curl -sf -X POST -H "X-Vault-Token: $TOKEN" \
  "$VAULT_ADDR/v1/$KV_PATH" \
  -d "$PATCHED_DATA" 2>&1) || {
  echo "ERROR: Vault write failed for $KV_PATH" >&2
  echo "       response: $WRITE_RESPONSE" >&2
  exit 5
}

VERSION=$(echo "$WRITE_RESPONSE" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["version"])' 2>/dev/null) \
  || VERSION="?"

# Audit line on stderr (intentionally NOT capturing values)
echo "[$CORRELATION_ID] $(date -u +%Y-%m-%dT%H:%M:%SZ) PATCH $KV_PATH fields=[$FIELD_KEY_LIST] version=$VERSION" >&2

# Stdout: just the new version (machine-readable for chained ops)
echo "$VERSION"
