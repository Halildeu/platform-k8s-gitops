#!/usr/bin/env bash
set -euo pipefail

# Additive TEST seed for Faz 24 #3240 through the dedicated, least-privilege
# audio-gateway-mtls-seeder AppRole. Secret values never enter argv or stdout.

HOST="${SPEECHMATICS_VAULT_HOST:-aiserver}"
VAULT_ADDR="${SPEECHMATICS_VAULT_ADDR:-http://127.0.0.1:8201}"
ROLE_ID_FILE="${SPEECHMATICS_ROLE_ID_FILE:-/home/aiadmin/.vault/audio-gateway-mtls-seeder-role-id}"
SECRET_ID_FILE="${SPEECHMATICS_SECRET_ID_FILE:-/home/aiadmin/.vault/audio-gateway-mtls-seeder-secret-id}"

if [[ $# -gt 0 ]]; then
  printf 'usage: [pbpaste |] %s\n' "$0" >&2
  exit 2
fi

if [[ -t 0 ]]; then
  printf 'Speechmatics TEST API key: ' >&2
  IFS= read -rs SPEECHMATICS_API_KEY
  printf '\n' >&2
else
  IFS= read -r SPEECHMATICS_API_KEY
fi

if [[ -z "${SPEECHMATICS_API_KEY:-}" ]]; then
  printf 'ERROR: empty key refused\n' >&2
  exit 2
fi

REMOTE_SCRIPT=$(cat <<'REMOTE'
set -euo pipefail

if [[ ! -r "$ROLE_ID_FILE" || ! -r "$SECRET_ID_FILE" ]]; then
  printf 'ERROR: scoped audio-gateway-mtls-seeder AppRole files are unavailable\n' >&2
  exit 3
fi
ROLE_ID=$(tr -d '\r\n' < "$ROLE_ID_FILE")
SECRET_ID=$(tr -d '\r\n' < "$SECRET_ID_FILE")
if [[ -z "$ROLE_ID" || -z "$SECRET_ID" ]]; then
  printf 'ERROR: scoped audio-gateway-mtls-seeder AppRole files are empty\n' >&2
  exit 3
fi

cleanup() {
  if [[ -n "${TOKEN_HEADER_FILE:-}" && -f "$TOKEN_HEADER_FILE" ]]; then
    curl -sf -X POST -H @"$TOKEN_HEADER_FILE" \
      "$VAULT_ADDR/v1/auth/token/revoke-self" >/dev/null 2>&1 || true
    shred -u "$TOKEN_HEADER_FILE" 2>/dev/null || true
  fi
  unset TOKEN ROLE_ID SECRET_ID API_KEY API_KEY_HASH LOGIN_RESPONSE \
    READ_RESPONSE READ_BACK_HASH VERSION PATCH_BODY
}
trap cleanup EXIT

IFS= read -r API_KEY
[[ -n "$API_KEY" ]] || { printf 'ERROR: empty key refused\n' >&2; exit 2; }

LOGIN_RESPONSE=$({ printf '%s\n' "$ROLE_ID"; printf '%s\n' "$SECRET_ID"; } \
  | python3 -c 'import json,sys; print(json.dumps({"role_id":sys.stdin.readline().strip(),"secret_id":sys.stdin.readline().strip()}))' \
  | curl -sf -X POST "$VAULT_ADDR/v1/auth/approle/login" --data-binary @-) \
  || { printf 'ERROR: scoped AppRole login failed\n' >&2; exit 3; }
TOKEN=$(printf '%s' "$LOGIN_RESPONSE" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["auth"]["client_token"])')
TOKEN_HEADER_FILE=$(mktemp)
chmod 600 "$TOKEN_HEADER_FILE"
printf 'X-Vault-Token: %s' "$TOKEN" > "$TOKEN_HEADER_FILE"

CAPS=$(curl -sf -X POST -H @"$TOKEN_HEADER_FILE" \
  "$VAULT_ADDR/v1/sys/capabilities-self" \
  -d '{"paths":["kv/data/platform/audio-gateway-service"]}' \
  | python3 -c 'import json,sys; print(",".join(sorted(json.load(sys.stdin)["capabilities"])))')
[[ ",$CAPS," == *",patch,"* && ",$CAPS," == *",read,"* ]] \
  || { printf 'ERROR: scoped AppRole lacks patch/read capability\n' >&2; exit 4; }
[[ ",$CAPS," != *",delete,"* && ",$CAPS," != *",update,"* && ",$CAPS," != *",create,"* ]] \
  || { printf 'ERROR: scoped AppRole capability boundary widened\n' >&2; exit 4; }

READ_RESPONSE=$(curl -sf -H @"$TOKEN_HEADER_FILE" \
  "$VAULT_ADDR/v1/kv/data/platform/audio-gateway-service") \
  || { printf 'ERROR: scoped Vault read failed\n' >&2; exit 5; }
VERSION=$(printf '%s' "$READ_RESPONSE" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["metadata"]["version"])')
API_KEY_HASH=$(printf '%s' "$API_KEY" | sha256sum | awk '{print $1}')
PATCH_BODY=$({ printf '%s\n' "$VERSION"; printf '%s' "$API_KEY"; } \
  | python3 -c 'import json,sys; version=int(sys.stdin.readline()); value=sys.stdin.read(); print(json.dumps({"options":{"cas":version},"data":{"speechmatics_api_key":value}}))')
unset API_KEY READ_RESPONSE

printf '%s' "$PATCH_BODY" \
  | curl -sf -X PATCH -H @"$TOKEN_HEADER_FILE" \
      -H 'Content-Type: application/merge-patch+json' \
      "$VAULT_ADDR/v1/kv/data/platform/audio-gateway-service" --data-binary @- \
      >/dev/null \
  || { printf 'ERROR: scoped additive Vault patch failed\n' >&2; exit 5; }
unset PATCH_BODY

READ_BACK_HASH=$(curl -sf -H @"$TOKEN_HEADER_FILE" \
  "$VAULT_ADDR/v1/kv/data/platform/audio-gateway-service" \
  | python3 -c 'import hashlib,json,sys; value=json.load(sys.stdin)["data"]["data"]["speechmatics_api_key"]; print(hashlib.sha256(value.encode()).hexdigest())') \
  || { printf 'ERROR: scoped Vault read-back failed\n' >&2; exit 5; }
[[ "$READ_BACK_HASH" == "$API_KEY_HASH" ]] \
  || { printf 'ERROR: scoped Vault read-back hash mismatch\n' >&2; exit 5; }

printf 'Vault read-back: speechmatics_api_key hash matched through scoped AppRole (value redacted)\n'
REMOTE
)

printf -v REMOTE_COMMAND \
  'VAULT_ADDR=%q ROLE_ID_FILE=%q SECRET_ID_FILE=%q bash -lc %q' \
  "$VAULT_ADDR" "$ROLE_ID_FILE" "$SECRET_ID_FILE" "$REMOTE_SCRIPT"
# REMOTE_COMMAND contains only static script/config paths; the key stays on stdin.
# shellcheck disable=SC2029
printf '%s\n' "$SPEECHMATICS_API_KEY" | ssh "$HOST" "$REMOTE_COMMAND"
unset SPEECHMATICS_API_KEY
