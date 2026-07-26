#!/usr/bin/env bash
#
# Assign a product-scoped Endpoint Admin tenant to one TEST user.
#
# This does not change the user's canonical org/company identity. It creates the
# frontend access-token mapper for `endpoint_admin_tenant_id` and stores exactly
# one UUID value on the selected Keycloak user. Only endpoint-admin-service
# consumes the claim; other products keep using their canonical tenant claims.
#
# Usage:
#   TARGET_USER_EMAIL=user@example.com \
#   ENDPOINT_ADMIN_TENANT_ID=00000000-0000-0000-0000-000000000001 \
#     scripts/keycloak/assign-endpoint-admin-tenant.sh --check
#
#   TARGET_USER_EMAIL=user@example.com \
#   ENDPOINT_ADMIN_TENANT_ID=00000000-0000-0000-0000-000000000001 \
#     scripts/keycloak/assign-endpoint-admin-tenant.sh --apply
#
# Exit codes: 0=converged/applied, 1=error, 2=drift in --check.
#
# Security boundary:
# - TEST only; realm/container/host endpoint are hard-bound.
# - Admin password, admin token and user tokens are never printed.
# - Temporary request/header files are owner-only and removed on exit.
# - Exactly one enabled target user and one `frontend` client are required.
# - Existing user attributes are preserved.

set -euo pipefail
umask 077

MODE="${1:---check}"
REALM="platform-test"
KC_CONTAINER="platform-kc-test"
KC_ADMIN_URL="http://127.0.0.1:8082"
CLIENT_ID="frontend"
MAPPER_NAME="endpoint-admin-tenant-claim"
ATTRIBUTE_NAME="endpoint_admin_tenant_id"
TARGET_USER_EMAIL="${TARGET_USER_EMAIL:-}"
ENDPOINT_ADMIN_TENANT_ID="${ENDPOINT_ADMIN_TENANT_ID:-}"
OUT_DIR="${OUT_DIR:-${TMPDIR:-/tmp}/endpoint-admin-tenant-assignment}"

die() {
  echo "[endpoint-admin-tenant] ERROR: $*" >&2
  exit 1
}

case "$MODE" in
  --check|--apply) ;;
  *) die "mode must be --check or --apply" ;;
esac

[[ "$TARGET_USER_EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+$ ]] \
  || die "TARGET_USER_EMAIL must be an exact email address"
[[ "$ENDPOINT_ADMIN_TENANT_ID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] \
  || die "ENDPOINT_ADMIN_TENANT_ID must be a UUID"

for command_name in curl docker jq python3 sha256sum; do
  command -v "$command_name" >/dev/null 2>&1 || die "missing command: $command_name"
done
docker inspect "$KC_CONTAINER" >/dev/null 2>&1 || die "TEST Keycloak container is unavailable"

tmp="$(mktemp -d "${TMPDIR:-/tmp}/endpoint-admin-tenant.XXXXXX")"
chmod 700 "$tmp"
cleanup() {
  rm -rf "$tmp"
  unset admin_password admin_token
}
trap cleanup EXIT

admin_password="$(
  docker exec "$KC_CONTAINER" sh -lc 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"' 2>/dev/null \
    | tr -d '\r\n'
)"
[[ -n "$admin_password" ]] || die "Keycloak admin password source is empty"

ADMIN_PASSWORD="$admin_password" python3 - "$tmp/token.form" <<'PY'
import os
import sys
import urllib.parse

fields = {
    "client_id": "admin-cli",
    "grant_type": "password",
    "password": os.environ["ADMIN_PASSWORD"],
    "username": "admin",
}
with open(sys.argv[1], "w", encoding="ascii") as stream:
    stream.write(urllib.parse.urlencode(fields))
PY
unset admin_password

token_code="$(
  curl -sS -o "$tmp/token.json" -w '%{http_code}' \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-binary "@$tmp/token.form" \
    "$KC_ADMIN_URL/realms/master/protocol/openid-connect/token"
)"
rm -f "$tmp/token.form"
[[ "$token_code" == "200" ]] || die "Keycloak admin authentication failed (HTTP $token_code)"
admin_token="$(jq -er '.access_token | select(type == "string" and length > 20)' "$tmp/token.json")" \
  || die "Keycloak admin token response is invalid"
rm -f "$tmp/token.json"

printf 'header = "Authorization: Bearer %s"\n' "$admin_token" >"$tmp/auth.curl"
unset admin_token

api() {
  local method="$1"
  local path="$2"
  local output="$3"
  local input="${4:-}"
  local args=(
    -sS
    --config "$tmp/auth.curl"
    -o "$output"
    -w '%{http_code}'
    -X "$method"
    -H 'Accept: application/json'
  )
  if [[ -n "$input" ]]; then
    args+=(-H 'Content-Type: application/json' --data-binary "@$input")
  fi
  curl "${args[@]}" "$KC_ADMIN_URL/admin/realms/$REALM$path"
}

email_query="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$TARGET_USER_EMAIL")"
code="$(api GET "/users?email=$email_query&exact=true" "$tmp/users.json")"
[[ "$code" == "200" ]] || die "target user lookup failed (HTTP $code)"
jq -e --arg email "$TARGET_USER_EMAIL" '
  length == 1
  and .[0].enabled == true
  and ((.[0].email // "") | ascii_downcase) == ($email | ascii_downcase)
' "$tmp/users.json" >/dev/null || die "target must resolve to exactly one enabled user"
user_id="$(jq -er '.[0].id' "$tmp/users.json")"

code="$(api GET "/clients?clientId=$CLIENT_ID" "$tmp/clients.json")"
[[ "$code" == "200" ]] || die "frontend client lookup failed (HTTP $code)"
jq -e --arg client "$CLIENT_ID" '
  length == 1 and .[0].clientId == $client
' "$tmp/clients.json" >/dev/null || die "frontend must resolve to exactly one client"
client_uuid="$(jq -er '.[0].id' "$tmp/clients.json")"

code="$(api GET "/clients/$client_uuid/protocol-mappers/models" "$tmp/mappers.json")"
[[ "$code" == "200" ]] || die "protocol mapper lookup failed (HTTP $code)"

code="$(api GET "/users/profile" "$tmp/user-profile.json")"
[[ "$code" == "200" ]] || die "user profile lookup failed (HTTP $code)"
jq -n --arg name "$ATTRIBUTE_NAME" '{
  name: $name,
  displayName: "Endpoint Admin tenant ID",
  permissions: {
    view: ["admin"],
    edit: ["admin"]
  },
  multivalued: false
}' >"$tmp/desired-profile-attribute.json"
jq --arg name "$ATTRIBUTE_NAME" '[.attributes[] | select(.name == $name)]' \
  "$tmp/user-profile.json" >"$tmp/controlled-profile-attributes.json"
profile_attribute_count="$(jq 'length' "$tmp/controlled-profile-attributes.json")"
[[ "$profile_attribute_count" -le 1 ]] || die "controlled user profile attribute is duplicated"
profile_attribute_exact=false
if [[ "$profile_attribute_count" == "1" ]]; then
  jq -e --slurpfile desired "$tmp/desired-profile-attribute.json" \
    '.[0] == $desired[0]' "$tmp/controlled-profile-attributes.json" >/dev/null \
    && profile_attribute_exact=true
fi

jq -n --arg name "$MAPPER_NAME" --arg attribute "$ATTRIBUTE_NAME" '{
  name: $name,
  protocol: "openid-connect",
  protocolMapper: "oidc-usermodel-attribute-mapper",
  config: {
    "access.token.claim": "true",
    "aggregate.attrs": "false",
    "claim.name": $attribute,
    "id.token.claim": "false",
    "introspection.token.claim": "true",
    "jsonType.label": "String",
    "multivalued": "false",
    "user.attribute": $attribute,
    "userinfo.token.claim": "false"
  }
}' >"$tmp/desired-mapper.json"

jq --arg name "$MAPPER_NAME" '[.[] | select(.name == $name)]' \
  "$tmp/mappers.json" >"$tmp/controlled-mappers.json"
mapper_count="$(jq 'length' "$tmp/controlled-mappers.json")"
[[ "$mapper_count" -le 1 ]] || die "controlled mapper name is duplicated"

mapper_exact=false
if [[ "$mapper_count" == "1" ]]; then
  jq -e --slurpfile desired "$tmp/desired-mapper.json" '
    .[0]
    | .protocol == $desired[0].protocol
    and .protocolMapper == $desired[0].protocolMapper
    and .config == $desired[0].config
  ' "$tmp/controlled-mappers.json" >/dev/null && mapper_exact=true
fi

code="$(api GET "/users/$user_id" "$tmp/user.json")"
[[ "$code" == "200" ]] || die "target user read failed (HTTP $code)"
user_attribute_exact="$(
  jq -r --arg attribute "$ATTRIBUTE_NAME" --arg tenant "$ENDPOINT_ADMIN_TENANT_ID" '
    ((.attributes // {})[$attribute] // []) == [$tenant]
  ' "$tmp/user.json"
)"

if [[ "$MODE" == "--check" ]]; then
  if [[ "$profile_attribute_exact" == "true" && "$mapper_exact" == "true" && "$user_attribute_exact" == "true" ]]; then
    result="converged"
    exit_code=0
  else
    result="drift"
    exit_code=2
  fi
else
  mutation_count=0
  if [[ "$profile_attribute_count" == "0" ]]; then
    jq --slurpfile desired "$tmp/desired-profile-attribute.json" '
      .attributes += [$desired[0]]
    ' "$tmp/user-profile.json" >"$tmp/desired-user-profile.json"
    code="$(api PUT "/users/profile" "$tmp/profile-update.json" "$tmp/desired-user-profile.json")"
    [[ "$code" == "200" ]] || die "user profile attribute creation failed (HTTP $code)"
    mutation_count=$((mutation_count + 1))
  elif [[ "$profile_attribute_exact" != "true" ]]; then
    die "controlled user profile attribute exists with an unexpected contract"
  fi

  if [[ "$mapper_count" == "0" ]]; then
    code="$(api POST "/clients/$client_uuid/protocol-mappers/models" "$tmp/mapper-create.json" "$tmp/desired-mapper.json")"
    [[ "$code" == "201" ]] || die "protocol mapper creation failed (HTTP $code)"
    mutation_count=$((mutation_count + 1))
  elif [[ "$mapper_exact" != "true" ]]; then
    mapper_id="$(jq -er '.[0].id' "$tmp/controlled-mappers.json")"
    code="$(api PUT "/clients/$client_uuid/protocol-mappers/models/$mapper_id" "$tmp/mapper-update.json" "$tmp/desired-mapper.json")"
    [[ "$code" == "204" ]] || die "controlled protocol mapper update failed (HTTP $code)"
    mutation_count=$((mutation_count + 1))
  fi

  if [[ "$user_attribute_exact" != "true" ]]; then
    jq --arg attribute "$ATTRIBUTE_NAME" --arg tenant "$ENDPOINT_ADMIN_TENANT_ID" '
      .attributes = ((.attributes // {}) + {($attribute): [$tenant]})
    ' "$tmp/user.json" >"$tmp/desired-user.json"
    code="$(api PUT "/users/$user_id" "$tmp/user-update.json" "$tmp/desired-user.json")"
    [[ "$code" == "204" ]] || die "target user attribute update failed (HTTP $code)"
    mutation_count=$((mutation_count + 1))
  fi
  if [[ "$mutation_count" -eq 0 ]]; then
    result="already-converged"
  else
    result="applied"
  fi
  exit_code=0
fi

# Authoritative read-back after every mode.
code="$(api GET "/users/profile" "$tmp/after-user-profile.json")"
[[ "$code" == "200" ]] || die "user profile read-back failed (HTTP $code)"
code="$(api GET "/clients/$client_uuid/protocol-mappers/models" "$tmp/after-mappers.json")"
[[ "$code" == "200" ]] || die "protocol mapper read-back failed (HTTP $code)"
code="$(api GET "/users/$user_id" "$tmp/after-user.json")"
[[ "$code" == "200" ]] || die "target user read-back failed (HTTP $code)"

postcondition="$(
  jq -n \
    --slurpfile profile "$tmp/after-user-profile.json" \
    --slurpfile desiredProfile "$tmp/desired-profile-attribute.json" \
    --slurpfile mappers "$tmp/after-mappers.json" \
    --slurpfile desired "$tmp/desired-mapper.json" \
    --slurpfile user "$tmp/after-user.json" \
    --arg name "$MAPPER_NAME" \
    --arg attribute "$ATTRIBUTE_NAME" \
    --arg tenant "$ENDPOINT_ADMIN_TENANT_ID" '
      ([ $profile[0].attributes[] | select(.name == $attribute) ] | length == 1)
      and ([ $profile[0].attributes[] | select(.name == $attribute) ][0] == $desiredProfile[0])
      and ([ $mappers[0][] | select(.name == $name) ] | length == 1)
      and ([ $mappers[0][] | select(.name == $name) ][0]
        | .protocol == $desired[0].protocol
        and .protocolMapper == $desired[0].protocolMapper
        and .config == $desired[0].config)
      and ((($user[0].attributes // {})[$attribute] // []) == [$tenant])
    '
)"
[[ "$postcondition" == "true" ]] || die "authoritative postcondition failed"

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"
user_id_sha256="$(printf '%s' "$user_id" | sha256sum | awk '{print $1}')"
jq -n \
  --arg schemaVersion "acik.endpoint-admin-tenant-assignment.v1" \
  --arg mode "$MODE" \
  --arg result "$result" \
  --arg realm "$REALM" \
  --arg clientId "$CLIENT_ID" \
  --arg mapperName "$MAPPER_NAME" \
  --arg targetEmail "$TARGET_USER_EMAIL" \
  --arg userIdSha256 "$user_id_sha256" \
  --arg tenantId "$ENDPOINT_ADMIN_TENANT_ID" \
  --argjson mutationCount "${mutation_count:-0}" \
  --arg createdAtUtc "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{
    schemaVersion: $schemaVersion,
    mode: $mode,
    result: $result,
    realm: $realm,
    clientId: $clientId,
    mapperName: $mapperName,
    targetEmail: $targetEmail,
    userIdSha256: $userIdSha256,
    tenantId: $tenantId,
    mutationCount: $mutationCount,
    userProfileAttributeExact: true,
    mapperExact: true,
    userAttributeExact: true,
    canonicalOrgOrCompanyChanged: false,
    secretHygiene: {
      adminPasswordIncluded: false,
      adminTokenIncluded: false,
      userTokenIncluded: false
    },
    createdAtUtc: $createdAtUtc
  }' >"$OUT_DIR/endpoint-admin-tenant-assignment-summary.json"

echo "[endpoint-admin-tenant] $result and verified"
exit "$exit_code"
