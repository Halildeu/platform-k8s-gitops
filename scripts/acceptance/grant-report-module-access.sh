#!/usr/bin/env bash
# Grant the budget smoke planner the REPORT module through role membership
# (gitops#3479). The Budget Workspace lives under /admin/reports/*, whose
# shell guard requires modules.REPORT >= VIEW from /authz/me — a product
# permission, granted the same way the access UI does it: by joining an
# existing permission-service role that already carries the REPORT module
# granule. Adapted from scripts/ats/provision-ats-recruiter-access.sh.
#
# Discovery-first: this repo pins no role name blindly. --discover lists the
# candidate roles (with their FULL granule sets) and mutates nothing; --apply
# then requires the exact role name AND the exact reviewed granule allowlist,
# so a role that widened since review is refused fail-closed.
#
# Writer identity: the d35-3 admin persona via the smoke-client ROPC lane
# (same substrate as the ATS provisioning script). All secrets stay on the
# host; nothing is printed.
set -euo pipefail

MODE=""
ROLE_NAME=""
ALLOWED_GRANULES=""
TARGET_EMAIL="${TARGET_EMAIL:-budget-smoke-planner@synthetic.test}"
OUT_PATH="${OUT_PATH:-/tmp/budget-planner-report-access.json}"

readonly BASE_URL="https://testai.acik.com"
readonly VAULT_CONTAINER="platform-vault-test"
readonly VAULT_INIT_JSON="${VAULT_INIT_JSON:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
readonly VAULT_ADMIN_PERSONA_PATH="kv/platform/d35-3"
readonly VAULT_SMOKE_CLIENT_PATH="kv/platform/keycloak/smoke-client"
readonly KC_ROPC_CLIENT_ID="smoke-client"
readonly REQUIRED_MODULE_KEY="REPORT"
readonly FORBIDDEN_GRANULE_KEYS="ATS_RETENTION_EXECUTE ERASURE_EXECUTE DSAR_WRITE EXPORT_REPAIR"

usage() {
  cat <<'EOF'
Usage:
  grant-report-module-access.sh --discover
  grant-report-module-access.sh --dry-run --role "NAME" --allowed-granules "K1 K2 ..."
  grant-report-module-access.sh --apply   --role "NAME" --allowed-granules "K1 K2 ..."

--discover lists roles carrying the REPORT module granule (full granule sets,
no mutation). --apply joins the budget smoke planner to the named role only
when the role's granules exactly stay within the reviewed allowlist.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --discover) MODE="discover"; shift ;;
    --dry-run) MODE="dry-run"; shift ;;
    --apply) MODE="apply"; shift ;;
    --role) ROLE_NAME="$2"; shift 2 ;;
    --allowed-granules) ALLOWED_GRANULES="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ -n "$MODE" ]] || { usage >&2; exit 2; }
if [[ "$MODE" != "discover" ]]; then
  [[ -n "$ROLE_NAME" && -n "$ALLOWED_GRANULES" ]] \
    || { echo "FATAL: $MODE requires --role and --allowed-granules" >&2; exit 2; }
fi

for command_name in curl jq docker python3; do
  command -v "$command_name" >/dev/null || { echo "FATAL: $command_name missing" >&2; exit 1; }
done
[[ -r "$VAULT_INIT_JSON" ]] || { echo "FATAL: vault init file unreadable" >&2; exit 1; }

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
chmod 700 "$TMP_DIR"

vault_field() {
  python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_JSON" |
    docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      exec vault kv get -field="$1" "$2"
    ' sh "$1" "$2"
}

ADMIN_USERNAME="$(vault_field admin_persona_username "$VAULT_ADMIN_PERSONA_PATH")"
vault_field admin_persona_password "$VAULT_ADMIN_PERSONA_PATH" > "$TMP_DIR/admin.password"
vault_field client_secret "$VAULT_SMOKE_CLIENT_PATH" > "$TMP_DIR/client.secret"
chmod 600 "$TMP_DIR/admin.password" "$TMP_DIR/client.secret"

TOKEN_JSON="$TMP_DIR/token.json"
curl -sS --max-time 20 -o "$TOKEN_JSON" -X POST \
  "$BASE_URL/realms/platform-test/protocol/openid-connect/token" \
  -d grant_type=password -d "client_id=$KC_ROPC_CLIENT_ID" \
  --data-urlencode "client_secret@$TMP_DIR/client.secret" \
  --data-urlencode "username=$ADMIN_USERNAME" \
  --data-urlencode "password@$TMP_DIR/admin.password"
jq -er '.access_token | strings | length > 0' "$TOKEN_JSON" >/dev/null \
  || { echo "FATAL: writer token mint failed" >&2; exit 1; }
AUTH_CONFIG="$TMP_DIR/auth.curl"
jq -r '"header \"Authorization: Bearer \(.access_token)\""' "$TOKEN_JSON" > "$AUTH_CONFIG"
printf 'header "X-Company-Id: 1"\n' >> "$AUTH_CONFIG"
chmod 600 "$AUTH_CONFIG"

api() { # method path out [curl-args...]
  local method="$1" path="$2" out="$3"; shift 3
  curl -sS --max-time 20 -o "$out" -w '%{http_code}' -X "$method" \
    "$BASE_URL$path" --config "$AUTH_CONFIG" "$@" || printf '000'
}

ROLES_JSON="$TMP_DIR/roles.json"
[[ "$(api GET /api/v1/roles "$ROLES_JSON")" == "200" ]] \
  || { echo "FATAL: role list failed" >&2; exit 1; }

if [[ "$MODE" == "discover" ]]; then
  : > "$OUT_PATH"
  while IFS=$'\t' read -r role_id role_name; do
    GR="$TMP_DIR/g-$role_id.json"
    [[ "$(api GET "/api/v1/roles/$role_id/granules" "$GR")" == "200" ]] || continue
    if jq -e --arg key "$REQUIRED_MODULE_KEY" \
        'any((.granules? // .)[]?; .type == "MODULE" and .key == $key)' "$GR" >/dev/null; then
      jq -n --arg id "$role_id" --arg name "$role_name" \
        --slurpfile g "$GR" \
        '{roleId: $id, roleName: $name,
          granules: [($g[0].granules? // $g[0])[]? | {type, key, level}]}' >> "$OUT_PATH"
    fi
  done < <(jq -r '(.items? // .)[]? | [(.id|tostring), .name] | @tsv' "$ROLES_JSON")
  echo "DISCOVER: REPORT taşıyan roller $OUT_PATH içinde"
  jq -r '.roleName' "$OUT_PATH" 2>/dev/null | sed 's/^/  - /' || true
  exit 0
fi

ROLE_MATCH_COUNT="$(jq --arg name "$ROLE_NAME" \
  '[(.items? // .)[]? | select(.name == $name)] | length' "$ROLES_JSON")"
[[ "$ROLE_MATCH_COUNT" == "1" ]] || { echo "FATAL: role not exactly one: $ROLE_NAME" >&2; exit 1; }
ROLE_ID="$(jq -r --arg name "$ROLE_NAME" \
  '[(.items? // .)[]? | select(.name == $name)][0].id // empty' "$ROLES_JSON")"
[[ "$ROLE_ID" =~ ^[0-9]+$ ]] || { echo "FATAL: role id missing" >&2; exit 1; }

GRANULES_JSON="$TMP_DIR/granules.json"
[[ "$(api GET "/api/v1/roles/$ROLE_ID/granules" "$GRANULES_JSON")" == "200" ]] \
  || { echo "FATAL: granule preflight failed" >&2; exit 1; }
jq -e --arg key "$REQUIRED_MODULE_KEY" \
  'any((.granules? // .)[]?; .type == "MODULE" and .key == $key)' \
  "$GRANULES_JSON" >/dev/null || { echo "FATAL: role lacks REPORT module granule" >&2; exit 1; }
jq -e --argjson allowed "$(printf '%s\n' $ALLOWED_GRANULES | jq -R . | jq -s .)" \
  'all((.granules? // .)[]?; .key as $k | $allowed | index($k) != null)' \
  "$GRANULES_JSON" >/dev/null || { echo "FATAL: role carries unreviewed granule" >&2; exit 1; }
jq -e --argjson forbidden "$(printf '%s\n' $FORBIDDEN_GRANULE_KEYS | jq -R . | jq -s .)" \
  'all((.granules? // .)[]?; .key as $k | $forbidden | index($k) == null)' \
  "$GRANULES_JSON" >/dev/null || { echo "FATAL: role carries destructive granule" >&2; exit 1; }

USER_JSON="$TMP_DIR/user.json"
code="$(curl -sS --max-time 20 -o "$USER_JSON" -w '%{http_code}' --get \
  "$BASE_URL/api/v1/users/by-email" --config "$AUTH_CONFIG" \
  --data-urlencode "email=$TARGET_EMAIL" || printf '000')"
[[ "$code" == "200" ]] || { echo "FATAL: user lookup failed ($code)" >&2; exit 1; }
PLATFORM_USER_ID="$(jq -r '.id // empty' "$USER_JSON")"
[[ "$PLATFORM_USER_ID" =~ ^[0-9]+$ ]] || { echo "FATAL: numeric user id missing" >&2; exit 1; }

MEMBERS_JSON="$TMP_DIR/members.json"
[[ "$(api GET "/api/v1/roles/$ROLE_ID/members" "$MEMBERS_JSON")" == "200" ]] \
  || { echo "FATAL: membership preflight failed" >&2; exit 1; }
if jq -e --argjson userId "$PLATFORM_USER_ID" \
    'any((.items? // .)[]?; (.userId // .id) == $userId)' "$MEMBERS_JSON" >/dev/null; then
  echo "OK: persona already member of '$ROLE_NAME'; no mutation"
  exit 0
fi

if [[ "$MODE" == "dry-run" ]]; then
  echo "OK: dry-run preflights passed for '$ROLE_NAME' (user $PLATFORM_USER_ID); rerun with --apply"
  exit 0
fi

MUTATION_RESPONSE="$TMP_DIR/mutation.json"
code="$(api POST "/api/v1/roles/$ROLE_ID/members" "$MUTATION_RESPONSE" \
  -H 'Content-Type: application/json' \
  --data-binary "$(jq -n --argjson userId "$PLATFORM_USER_ID" '{userIds: [$userId]}')")"
[[ "$code" == "200" || "$code" == "201" || "$code" == "204" ]] \
  || { echo "FATAL: membership write failed ($code)" >&2; exit 1; }

MEMBERS_AFTER="$TMP_DIR/members-after.json"
[[ "$(api GET "/api/v1/roles/$ROLE_ID/members" "$MEMBERS_AFTER")" == "200" ]] \
  || { echo "FATAL: membership readback failed" >&2; exit 1; }
jq -e --argjson userId "$PLATFORM_USER_ID" \
  'any((.items? // .)[]?; (.userId // .id) == $userId)' "$MEMBERS_AFTER" >/dev/null \
  || { echo "FATAL: membership readback mismatch" >&2; exit 1; }

GRANULES_AFTER="$TMP_DIR/granules-after.json"
[[ "$(api GET "/api/v1/roles/$ROLE_ID/granules" "$GRANULES_AFTER")" == "200" ]] \
  || { echo "FATAL: granule readback failed" >&2; exit 1; }
jq -e -s '.[0] == .[1]' "$GRANULES_JSON" "$GRANULES_AFTER" >/dev/null \
  || { echo "FATAL: granule surface changed unexpectedly" >&2; exit 1; }

echo "OK: '$TARGET_EMAIL' joined role '$ROLE_NAME' (readback verified, granule surface unchanged)"
