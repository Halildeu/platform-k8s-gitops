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
#                               permission-service,
#                               cross-ai-deployment-protection-test, openfga,
#                               ghcr-token
#                               (ghcr-token uses kv/data/gitops/ghcr-token).
#   --field key=value           Set a single key-value (value visible in argv;
#                               use --field-from-stdin for sensitive values).
#   --field-from-stdin <key>    Reads the key's value from stdin (one line).
#                               Repeatable.
#   --cleanup-secret-id-file    Securely removes the secret-id file on exit.
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
CLEANUP_SECRET_ID_FILE=0
TOKEN_HEADER_FILE=""

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
    --cleanup-secret-id-file)
      CLEANUP_SECRET_ID_FILE=1; shift ;;
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
  report-service|schema-service|permission-service|\
  cross-ai-deployment-protection-test|openfga)
    KV_PATH="kv/data/platform/$SERVICE"
    ;;
  ghcr-token)
    KV_PATH="kv/data/gitops/ghcr-token"
    ;;
  *)
    echo "ERROR: unknown --service $SERVICE" >&2
    exit 2 ;;
esac

# This dedicated path carries exactly one GitHub-generated HMAC secret. Lock the
# wrapper contract to stdin-only and reject arbitrary fields even though Vault
# ACLs are necessarily path-granular rather than property-granular.
if [[ "$SERVICE" == "cross-ai-deployment-protection-test" ]]; then
  if [[ "${#FIELDS[@]}" -ne 0 \
        || "${#STDIN_KEYS[@]}" -ne 1 \
        || "${STDIN_KEYS[0]:-}" != "github_webhook_secret_current" ]]; then
    echo "ERROR: $SERVICE accepts only --field-from-stdin github_webhook_secret_current" >&2
    exit 2
  fi
fi

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

LOGIN_RESPONSE=$({ printf '%s\n' "$ROLE_ID"; printf '%s\n' "$SECRET_ID"; } \
  | python3 -c 'import json,sys; print(json.dumps({"role_id": sys.stdin.readline().rstrip("\n"), "secret_id": sys.stdin.readline().rstrip("\n")}))' \
  | curl -sf -X POST "$VAULT_ADDR/v1/auth/approle/login" --data-binary @- 2>/dev/null) || {
  echo "ERROR: AppRole login failed (HTTP error)" >&2
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

TOKEN_HEADER_FILE=$(mktemp)
chmod 600 "$TOKEN_HEADER_FILE"
printf 'X-Vault-Token: %s' "$TOKEN" > "$TOKEN_HEADER_FILE"

# Cleanup token + secrets on exit (defense-in-depth; TTL is short anyway)
cleanup() {
  if [[ -n "${TOKEN:-}" && -f "${TOKEN_HEADER_FILE:-}" ]]; then
    curl -sf -X POST -H @"$TOKEN_HEADER_FILE" \
      "$VAULT_ADDR/v1/auth/token/revoke-self" >/dev/null 2>&1 || true
  fi
  if [[ -f "${TOKEN_HEADER_FILE:-}" ]]; then
    if command -v shred >/dev/null 2>&1; then
      shred -u "$TOKEN_HEADER_FILE" 2>/dev/null || true
    else
      : > "$TOKEN_HEADER_FILE"
      rm -f "$TOKEN_HEADER_FILE"
    fi
  fi
  if [[ "$CLEANUP_SECRET_ID_FILE" -eq 1 \
        && -n "${SECRET_ID_FILE:-}" \
        && -f "$SECRET_ID_FILE" ]]; then
    if command -v shred >/dev/null 2>&1; then
      shred -u "$SECRET_ID_FILE" 2>/dev/null || true
    else
      : > "$SECRET_ID_FILE"
      rm -f "$SECRET_ID_FILE"
    fi
  fi
  unset TOKEN SECRET_ID FIELDS STDIN_FIELD_PAIRS LOGIN_RESPONSE \
    PATCHED_DATA EXISTING_RESPONSE EXISTING_DATA
}
trap cleanup EXIT

# ============================================================================
# capabilities-self check (fail-fast pattern)
# ============================================================================

CAPS=$(curl -sf -X POST -H @"$TOKEN_HEADER_FILE" \
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

EXISTING_RESPONSE=$(curl -sS -H @"$TOKEN_HEADER_FILE" \
  -w $'\n%{http_code}' "$VAULT_ADDR/v1/$KV_PATH" 2>/dev/null) || {
  echo "ERROR: Vault read failed for $KV_PATH" >&2
  exit 5
}
EXISTING_CODE="${EXISTING_RESPONSE##*$'\n'}"
EXISTING_BODY="${EXISTING_RESPONSE%$'\n'*}"

if [[ "$EXISTING_CODE" == "404" ]]; then
  EXISTING_DATA="{}"
  CURRENT_VERSION=0
elif [[ "$EXISTING_CODE" == "200" ]]; then
  EXISTING_DATA=$(printf '%s' "$EXISTING_BODY" \
    | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin)["data"]["data"]))')
  CURRENT_VERSION=$(printf '%s' "$EXISTING_BODY" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["metadata"]["version"])')
else
  echo "ERROR: Vault read returned HTTP $EXISTING_CODE for $KV_PATH" >&2
  exit 5
fi
unset EXISTING_BODY

# Merge new fields into existing data
PATCHED_DATA=$({
  printf '%s\n' "$EXISTING_DATA"
  printf '%s\n' "${FIELDS[@]:-}"
  printf '%s\n' "${STDIN_FIELD_PAIRS[@]:-}"
} | CURRENT_VERSION="$CURRENT_VERSION" python3 -c '
import json
import os
import sys

existing = json.loads(sys.stdin.readline())
for line in sys.stdin:
    line = line.rstrip("\n")
    if not line:
        continue
    key, separator, value = line.partition("=")
    if separator and key:
        existing[key] = value
print(json.dumps({"options": {"cas": int(os.environ["CURRENT_VERSION"])}, "data": existing}))
')

# ============================================================================
# Write (or dry-run)
# ============================================================================

CORRELATION_ID="vault-patch-$(date -u +%Y%m%dT%H%M%S)-$$"
FIELD_KEY_LIST=$({
  if [[ "${#FIELDS[@]}" -gt 0 ]]; then
    printf '%s\n' "${FIELDS[@]}"
  fi
  if [[ "${#STDIN_FIELD_PAIRS[@]}" -gt 0 ]]; then
    printf '%s\n' "${STDIN_FIELD_PAIRS[@]}"
  fi
} | awk -F= '{print $1}' | sort -u | tr '\n' ',' | sed 's/,$//')

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

WRITE_RESPONSE=$(printf '%s' "$PATCHED_DATA" \
  | curl -sf -X POST -H @"$TOKEN_HEADER_FILE" \
      "$VAULT_ADDR/v1/$KV_PATH" --data-binary @- 2>/dev/null) || {
  echo "ERROR: Vault write failed for $KV_PATH" >&2
  echo "       possible CAS conflict or HTTP error; no value was logged" >&2
  exit 5
}

VERSION=$(echo "$WRITE_RESPONSE" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["version"])' 2>/dev/null) \
  || VERSION="?"

# Audit line on stderr (intentionally NOT capturing values)
echo "[$CORRELATION_ID] $(date -u +%Y-%m-%dT%H:%M:%SZ) PATCH $KV_PATH fields=[$FIELD_KEY_LIST] version=$VERSION" >&2

# Stdout: just the new version (machine-readable for chained ops)
echo "$VERSION"
