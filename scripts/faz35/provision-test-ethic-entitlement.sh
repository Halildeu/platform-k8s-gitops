#!/usr/bin/env bash
# Faz 35 Etik Speak: grant the dedicated synthetic manager the suite ETHIC
# module through permission-service's canonical role/granule/member writer.
set -euo pipefail
# A caller may invoke bash -x; stop tracing before credentials are read.
set +x
umask 077

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/faz35/lib-vault-accessor-inventory.sh
source "$SCRIPT_DIR/lib-vault-accessor-inventory.sh"
# shellcheck source=scripts/faz35/lib-authz-projection.sh
source "$SCRIPT_DIR/lib-authz-projection.sh"

BASE_URL="${BASE_URL:-https://testai.acik.com}"
KC_BASE_URL="${KC_BASE_URL:-http://127.0.0.1:8082}"
KC_REALM="${KC_REALM:-platform-test}"
KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/home/halil/bootstrap-drill/vault-init-test.json}"
WRITER_VAULT_PATH="${WRITER_VAULT_PATH:-kv/platform/d35-3}"
PERSONA_USERNAME="${PERSONA_USERNAME:-ethics-manager-test}"
PERSONA_PASSWORD_FILE="${PERSONA_PASSWORD_FILE:-/home/halil/bootstrap-drill/ethics-manager-test.password}"
WRONG_ORG_USERNAME="${WRONG_ORG_USERNAME:-ethics-manager-wrong-org-test}"
WRONG_ORG_PASSWORD_FILE="${WRONG_ORG_PASSWORD_FILE:-/home/halil/bootstrap-drill/ethics-manager-wrong-org-test.password}"
DENIED_USERNAME="${DENIED_USERNAME:-ethics-manager-denied-test}"
DENIED_PASSWORD_FILE="${DENIED_PASSWORD_FILE:-/home/halil/bootstrap-drill/ethics-manager-denied-test.password}"
PERMISSION_ROLE_NAME="${PERMISSION_ROLE_NAME:-ETIK_SPEAK_MANAGER}"

for binding in \
  "$BASE_URL=https://testai.acik.com" \
  "$KC_BASE_URL=http://127.0.0.1:8082" \
  "$KC_REALM=platform-test" \
  "$KC_CONTAINER=platform-kc-test" \
  "$VAULT_CONTAINER=platform-vault-test" \
  "$VAULT_INIT_FILE=/home/halil/bootstrap-drill/vault-init-test.json" \
  "$WRITER_VAULT_PATH=kv/platform/d35-3" \
  "$PERSONA_USERNAME=ethics-manager-test" \
  "$PERSONA_PASSWORD_FILE=/home/halil/bootstrap-drill/ethics-manager-test.password" \
  "$WRONG_ORG_USERNAME=ethics-manager-wrong-org-test" \
  "$WRONG_ORG_PASSWORD_FILE=/home/halil/bootstrap-drill/ethics-manager-wrong-org-test.password" \
  "$DENIED_USERNAME=ethics-manager-denied-test" \
  "$DENIED_PASSWORD_FILE=/home/halil/bootstrap-drill/ethics-manager-denied-test.password" \
  "$PERMISSION_ROLE_NAME=ETIK_SPEAK_MANAGER"; do
  [ "${binding%%=*}" = "${binding#*=}" ] || {
    echo "FATAL: Etik Speak entitlement mutation target override refused: ${binding%%=*}" >&2
    exit 1
  }
done

for command_name in curl jq docker stat mktemp seq; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "FATAL: required command missing: $command_name" >&2
    exit 1
  }
done

validate_secret_file() {
  local file=$1 label=$2
  [ -r "$file" ] && [ -f "$file" ] && [ ! -L "$file" ] || {
    echo "FATAL: $label must be a readable regular non-symlink" >&2
    exit 1
  }
  [ "$(stat -c '%u' "$file")" = "$(id -u)" ] && [ "$(stat -c '%a' "$file")" = 600 ] || {
    echo "FATAL: $label must be invoking-user-owned mode 600" >&2
    exit 1
  }
}

validate_secret_file "$VAULT_INIT_FILE" "Vault init file"
validate_secret_file "$PERSONA_PASSWORD_FILE" "manager password file"
validate_secret_file "$WRONG_ORG_PASSWORD_FILE" "wrong-org password file"
validate_secret_file "$DENIED_PASSWORD_FILE" "denied-persona password file"

TMP_DIR=$(mktemp -d /tmp/faz35-ethic-entitlement.XXXXXX)
vault_output_file="$TMP_DIR/vault.json"
vault_error_file="$TMP_DIR/vault.err"
trap 'unset vault_root_token writer_json writer_username writer_password target_password wrong_org_password denied_password target_token writer_token wrong_org_token denied_token; rm -rf "$TMP_DIR"' EXIT

write_bearer_config() {
  local file=$1 token=$2
  printf 'header = "Authorization: Bearer %s"\n' "$token" >"$file"
  chmod 600 "$file"
}

http_status() {
  local method=$1 url=$2 output=$3
  shift 3
  curl -sS --max-time 20 -o "$output" -w '%{http_code}' -X "$method" "$url" "$@" || printf '000'
}

vault_root_token=$(jq -er '.root_token | select(type == "string" and length > 0)' "$VAULT_INIT_FILE")
vault_status=0
if printf '%s\n' "$vault_root_token" | docker exec -i \
    -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
      set -eu
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      exec vault kv get -format=json "$1"
    ' sh "$WRITER_VAULT_PATH" >"$vault_output_file" 2>"$vault_error_file"; then
  vault_status=0
else
  vault_status=$?
fi
writer_json=$(vault_json_document_classify "$vault_status" "$vault_output_file" "$vault_error_file" \
  '(.data.data.admin_persona_username | type == "string" and length > 0) and (.data.data.admin_persona_password | type == "string" and length > 0)') || {
  echo "FATAL: permission-writer Vault response is not one exact JSON document" >&2
  exit 1
}
unset vault_root_token
writer_username=$(printf '%s' "$writer_json" | jq -r '.data.data.admin_persona_username')
writer_password=$(printf '%s' "$writer_json" | jq -r '.data.data.admin_persona_password')
unset writer_json

printf '%s' "$writer_username" >"$TMP_DIR/writer.username"
printf '%s' "$writer_password" >"$TMP_DIR/writer.password"
printf '%s' "$PERSONA_USERNAME" >"$TMP_DIR/target.username"
cp "$PERSONA_PASSWORD_FILE" "$TMP_DIR/target.password"
printf '%s' "$WRONG_ORG_USERNAME" >"$TMP_DIR/wrong-org.username"
cp "$WRONG_ORG_PASSWORD_FILE" "$TMP_DIR/wrong-org.password"
printf '%s' "$DENIED_USERNAME" >"$TMP_DIR/denied.username"
cp "$DENIED_PASSWORD_FILE" "$TMP_DIR/denied.password"
chmod 600 "$TMP_DIR"/*
unset writer_username writer_password

mint_token() {
  local username_file=$1 password_file=$2 output=$3 code
  code=$(http_status POST "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" "$output" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'grant_type=password' \
    --data-urlencode 'client_id=frontend' \
    --data-urlencode "username@$username_file" \
    --data-urlencode "password@$password_file" \
    --data-urlencode 'scope=openid ethics-manager-audience ethics:case:manage')
  if [ "$code" != 200 ] || ! jq -e '.access_token | type == "string" and length > 0' "$output" >/dev/null; then
    echo "FATAL: synthetic persona token mint failed" >&2
    exit 1
  fi
}

mint_token "$TMP_DIR/target.username" "$TMP_DIR/target.password" "$TMP_DIR/target-token.json"
mint_token "$TMP_DIR/wrong-org.username" "$TMP_DIR/wrong-org.password" "$TMP_DIR/wrong-org-token.json"
mint_token "$TMP_DIR/denied.username" "$TMP_DIR/denied.password" "$TMP_DIR/denied-token.json"

target_token=$(jq -r '.access_token' "$TMP_DIR/target-token.json")
wrong_org_token=$(jq -r '.access_token' "$TMP_DIR/wrong-org-token.json")
denied_token=$(jq -r '.access_token' "$TMP_DIR/denied-token.json")
write_bearer_config "$TMP_DIR/target-auth.curl" "$target_token"
write_bearer_config "$TMP_DIR/wrong-org-auth.curl" "$wrong_org_token"
write_bearer_config "$TMP_DIR/denied-auth.curl" "$denied_token"
unset target_token wrong_org_token denied_token

writer_code=$(http_status POST "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" \
  "$TMP_DIR/writer-token.json" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=password' \
  --data-urlencode 'client_id=frontend' \
  --data-urlencode "username@$TMP_DIR/writer.username" \
  --data-urlencode "password@$TMP_DIR/writer.password")
if [ "$writer_code" != 200 ] || ! jq -e '.access_token | type == "string" and length > 0' \
  "$TMP_DIR/writer-token.json" >/dev/null; then
  echo "FATAL: canonical permission writer token mint failed" >&2
  exit 1
fi
writer_token=$(jq -r '.access_token' "$TMP_DIR/writer-token.json")
write_bearer_config "$TMP_DIR/writer-auth.curl" "$writer_token"
unset writer_token

# /authz/me is permission-service owned and cannot materialize a new local
# user. Touch the user-service profile route first. A new least-privilege row
# intentionally answers ACCOUNT_DISABLED; the canonical test admin then uses
# the ordinary activation endpoint before any role/granule mutation.
for label in target wrong-org denied; do
  profile_code=$(http_status GET "$BASE_URL/api/v1/users/me/profile" \
    "$TMP_DIR/$label-profile-bootstrap.json" --config "$TMP_DIR/$label-auth.curl")
  if [ "$profile_code" != 200 ] && ! {
      [ "$profile_code" = 403 ] &&
      jq -e '.message == "ACCOUNT_DISABLED"' "$TMP_DIR/$label-profile-bootstrap.json" >/dev/null;
    }; then
    echo "FATAL: $label user-service identity materialization failed" >&2
    exit 1
  fi

  username=$(<"$TMP_DIR/$label.username")
  email="$username@test.invalid"
  code=$(http_status GET "$BASE_URL/api/v1/users/by-email" "$TMP_DIR/$label-user.json" \
    --config "$TMP_DIR/writer-auth.curl" --get --data-urlencode "email=$email")
  if [ "$code" != 200 ] || ! jq -e --arg email "$email" '
      (.id | type == "number") and .email == $email and (.enabled | type == "boolean")
    ' "$TMP_DIR/$label-user.json" >/dev/null; then
    echo "FATAL: $label canonical local user lookup failed" >&2
    exit 1
  fi
  user_id=$(jq -r '.id' "$TMP_DIR/$label-user.json")
  printf '%s' "$user_id" >"$TMP_DIR/$label-user-id"
  unset username email user_id
done

# Negative personas must always lack ETHIC. The target may either lack ETHIC
# on the first run or carry the exact MANAGE projection from a previously
# completed run; its dedicated role linkage is verified below before mutation.
for label in target wrong-org denied; do
  code=$(http_status GET "$BASE_URL/api/v1/authz/me" "$TMP_DIR/$label-authz-before.json" \
    --config "$TMP_DIR/$label-auth.curl")
  [ "$code" = 200 ] || { echo "FATAL: $label authz identity bootstrap failed" >&2; exit 1; }
  projection_state=$(faz35_authz_projection_state "$TMP_DIR/$label-authz-before.json") || {
    echo "FATAL: $label has a non-canonical ETHIC authorization projection" >&2
    exit 1
  }
  if [ "$label" != target ] && [ "$projection_state" != ABSENT ]; then
    echo "FATAL: $label unexpectedly has ETHIC before dedicated writer provisioning" >&2
    exit 1
  fi
  [ "$label" != target ] || target_projection_before=$projection_state
done
target_user_id=$(jq -r '.subscriberId' "$TMP_DIR/target-authz-before.json")
[ "$target_user_id" = "$(<"$TMP_DIR/target-user-id")" ] || {
  echo "FATAL: target authz subscriberId differs from the activated local profile" >&2
  exit 1
}
unset projection_state

# Activate only after all three authz projections have passed the no-ETHIC /
# exact-prior-state preflight above. This keeps a drift failure mutation-free.
for label in target wrong-org denied; do
  user_id=$(<"$TMP_DIR/$label-user-id")
  if [ "$(jq -r '.enabled' "$TMP_DIR/$label-user.json")" = false ]; then
    printf '{"active":true}' >"$TMP_DIR/$label-activation.json"
    code=$(http_status PUT "$BASE_URL/api/v1/users/$user_id/activation" \
      "$TMP_DIR/$label-activation-response.json" --config "$TMP_DIR/writer-auth.curl" \
      -H 'Content-Type: application/json' --data-binary "@$TMP_DIR/$label-activation.json")
    [ "$code" = 200 ] || { echo "FATAL: $label local user activation failed" >&2; exit 1; }
  fi
  code=$(http_status GET "$BASE_URL/api/v1/users/me/profile" \
    "$TMP_DIR/$label-profile-active.json" --config "$TMP_DIR/$label-auth.curl")
  if [ "$code" != 200 ] || ! jq -e --argjson expected "$user_id" \
      '.id == $expected and .enabled == true' "$TMP_DIR/$label-profile-active.json" >/dev/null; then
    echo "FATAL: $label active local profile postcondition failed" >&2
    exit 1
  fi
  unset user_id
done

roles_code=$(http_status GET "$BASE_URL/api/v1/roles" "$TMP_DIR/roles.json" \
  --config "$TMP_DIR/writer-auth.curl")
[ "$roles_code" = 200 ] || { echo "FATAL: permission role list failed" >&2; exit 1; }
role_count=$(jq --arg name "$PERMISSION_ROLE_NAME" '[.items[]? | select(.name == $name)] | length' "$TMP_DIR/roles.json")
[ "$role_count" = 0 ] || [ "$role_count" = 1 ] || {
  echo "FATAL: dedicated permission role is not unique" >&2
  exit 1
}
role_id=$(jq -r --arg name "$PERMISSION_ROLE_NAME" '[.items[]? | select(.name == $name)][0].id // empty' "$TMP_DIR/roles.json")
member_present=false

if [ -n "$role_id" ]; then
  code=$(http_status GET "$BASE_URL/api/v1/roles/$role_id/granules" "$TMP_DIR/granules-before.json" \
    --config "$TMP_DIR/writer-auth.curl")
  [ "$code" = 200 ] || { echo "FATAL: dedicated permission granule preflight failed" >&2; exit 1; }
  jq -e '
    (.granules | length) <= 1 and
    all(.granules[]?; .type == "MODULE" and .key == "ETHIC" and .grant == "MANAGE")
  ' "$TMP_DIR/granules-before.json" >/dev/null || {
    echo "FATAL: dedicated permission role contains unrelated granules" >&2
    exit 1
  }
  code=$(http_status GET "$BASE_URL/api/v1/roles/$role_id/members" "$TMP_DIR/members-before.json" \
    --config "$TMP_DIR/writer-auth.curl")
  [ "$code" = 200 ] || { echo "FATAL: dedicated permission membership preflight failed" >&2; exit 1; }
  jq -e --argjson target "$target_user_id" \
    'length <= 1 and all(.[]?; .userId == $target)' "$TMP_DIR/members-before.json" >/dev/null || {
    echo "FATAL: dedicated permission role contains an unrelated member" >&2
    exit 1
  }
  [ "$(jq 'length' "$TMP_DIR/members-before.json")" = 0 ] || member_present=true

  if [ "$target_projection_before" = EXACT_MANAGE ]; then
    if ! jq -e '.granules == [{type:"MODULE",key:"ETHIC",grant:"MANAGE"}]' \
        "$TMP_DIR/granules-before.json" >/dev/null ||
        ! jq -e --argjson target "$target_user_id" \
          'length == 1 and .[0].userId == $target' "$TMP_DIR/members-before.json" >/dev/null; then
      echo "FATAL: existing target ETHIC projection is not linked to the exact dedicated role" >&2
      exit 1
    fi
  fi
else
  [ "$target_projection_before" = ABSENT ] || {
    echo "FATAL: target has ETHIC but the dedicated permission role is missing" >&2
    exit 1
  }
  jq -n --arg name "$PERMISSION_ROLE_NAME" \
    '{name:$name,description:"Etik Speak dedicated synthetic test manager"}' >"$TMP_DIR/create-role.json"
  code=$(http_status POST "$BASE_URL/api/v1/roles" "$TMP_DIR/create-role-response.json" \
    --config "$TMP_DIR/writer-auth.curl" -H 'Content-Type: application/json' \
    --data-binary "@$TMP_DIR/create-role.json")
  [ "$code" = 201 ] || { echo "FATAL: dedicated permission role create failed" >&2; exit 1; }
  role_id=$(jq -r '.id // empty' "$TMP_DIR/create-role-response.json")
  [[ "$role_id" =~ ^[0-9]+$ ]] || { echo "FATAL: dedicated permission role id missing" >&2; exit 1; }
fi

jq -n '{permissions:[{type:"MODULE",key:"ETHIC",grant:"MANAGE"}]}' >"$TMP_DIR/granules.json"
code=$(http_status PUT "$BASE_URL/api/v1/roles/$role_id/granules" "$TMP_DIR/mutation.json" \
  --config "$TMP_DIR/writer-auth.curl" -H 'Content-Type: application/json' \
  --data-binary "@$TMP_DIR/granules.json")
[ "$code" = 200 ] || { echo "FATAL: ETHIC granule writer failed" >&2; exit 1; }

if [ "$member_present" = false ]; then
  jq -n --argjson target "$target_user_id" '{userIds:[$target]}' >"$TMP_DIR/member.json"
  code=$(http_status POST "$BASE_URL/api/v1/roles/$role_id/members" "$TMP_DIR/mutation.json" \
    --config "$TMP_DIR/writer-auth.curl" -H 'Content-Type: application/json' \
    --data-binary "@$TMP_DIR/member.json")
  [ "$code" = 200 ] || { echo "FATAL: ETHIC membership writer failed" >&2; exit 1; }
fi

code=$(http_status GET "$BASE_URL/api/v1/roles/$role_id/granules" "$TMP_DIR/granules-after.json" \
  --config "$TMP_DIR/writer-auth.curl")
if [ "$code" != 200 ] || ! jq -e \
  '.granules == [{type:"MODULE",key:"ETHIC",grant:"MANAGE"}]' "$TMP_DIR/granules-after.json" >/dev/null; then
  echo "FATAL: ETHIC granule readback mismatch" >&2
  exit 1
fi
code=$(http_status GET "$BASE_URL/api/v1/roles/$role_id/members" "$TMP_DIR/members-after.json" \
  --config "$TMP_DIR/writer-auth.curl")
if [ "$code" != 200 ] || ! jq -e --argjson target "$target_user_id" \
  'length == 1 and .[0].userId == $target' "$TMP_DIR/members-after.json" >/dev/null; then
  echo "FATAL: ETHIC membership readback mismatch" >&2
  exit 1
fi

# RoleChangeEvent/version propagation may be asynchronous. Poll only the
# non-secret authorization projection and require both positive and negative
# postconditions before returning success.
entitlement_ready=false
for _ in $(seq 1 30); do
  code=$(http_status GET "$BASE_URL/api/v1/authz/me" "$TMP_DIR/target-authz-after.json" \
    --config "$TMP_DIR/target-auth.curl")
  if [ "$code" = 200 ] &&
      [ "$(faz35_authz_projection_state "$TMP_DIR/target-authz-after.json" 2>/dev/null || true)" = EXACT_MANAGE ]; then
    entitlement_ready=true
    break
  fi
  sleep 1
done
[ "$entitlement_ready" = true ] || {
  echo "FATAL: target ETHIC entitlement did not become authoritative" >&2
  exit 1
}
for label in wrong-org denied; do
  code=$(http_status GET "$BASE_URL/api/v1/authz/me" "$TMP_DIR/$label-authz-after.json" \
    --config "$TMP_DIR/$label-auth.curl")
  if [ "$code" != 200 ] || ! jq -e '
    (((.modules // {}) | has("ETHIC")) | not) and
    (((.allowedModules // []) | index("ETHIC")) == null)
  ' "$TMP_DIR/$label-authz-after.json" >/dev/null; then
    echo "FATAL: $label gained the dedicated ETHIC entitlement" >&2
    exit 1
  fi
done

unset target_user_id target_projection_before member_present
echo "Permission: canonical role/granule/member writer granted only the synthetic manager ETHIC=MANAGE"
echo "Permission: target positive and wrong-org/denied negative /authz/me postconditions OK"
echo "ETHICS_PERMISSION_ROLE_ID=$role_id"
