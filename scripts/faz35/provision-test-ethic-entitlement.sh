#!/usr/bin/env bash
# Faz 35 Etik Speak: grant the three dedicated synthetic manager personas the
# same narrow suite ETHIC module. Tenant and object authorization remain solely
# differentiated by each persona's org claim and isolated OpenFGA tuples.
#
# A2 MIGRATION NOTE (2026-07-21, Faz 22 Sec KC hardening #2476 A2b.2):
# `client_id=frontend` public ROPC + DAG=true KC client'ı A2c cutover'ında
# `directAccessGrantsEnabled=false`'a çevrilecek. Bu script `frontend`'in
# `ethics-manager-audience` optional scope'una bağımlı (smoke-client'ta ETHICS
# scope YOK). Faz35 team A2c ÖNCESİ smoke-client'ı A2b.3 ile genişletmeli veya
# bu script'i revize etmeli — aksi halde A2c ROPC'yi keser.
set -euo pipefail
# A caller may invoke bash -x; stop tracing before credentials are read.
set +x
umask 077

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/faz35/lib-vault-accessor-inventory.sh
source "$SCRIPT_DIR/lib-vault-accessor-inventory.sh"
# shellcheck source=scripts/faz35/lib-authz-projection.sh
source "$SCRIPT_DIR/lib-authz-projection.sh"
# shellcheck source=scripts/faz35/lib-test-keycloak-binding.sh
source "$SCRIPT_DIR/lib-test-keycloak-binding.sh"
# shellcheck source=scripts/faz35/lib-permission-role-catalog.sh
source "$SCRIPT_DIR/lib-permission-role-catalog.sh"

BASE_URL="${BASE_URL:-https://testai.acik.com}"
KC_BASE_URL="${KC_BASE_URL:-http://127.0.0.1:8082}"
KC_REALM="${KC_REALM:-platform-test}"
KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
readonly KC_EXPECTED_ISSUER="https://testai.acik.com/realms/platform-test"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_FILE_DEFAULT="$HOME/bootstrap-drill/vault-init-test.json"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-$VAULT_INIT_FILE_DEFAULT}"
WRITER_VAULT_PATH="${WRITER_VAULT_PATH:-kv/platform/d35-3}"
WRITER_USERNAME="${WRITER_USERNAME:-d35-admin-persona}"
WRITER_LOCAL_USER_ID="${WRITER_LOCAL_USER_ID:-12}"
WRITER_PROVISIONER_ROLE="${WRITER_PROVISIONER_ROLE:-ETIK_SPEAK_PROVISIONER}"
PERSONA_USERNAME="${PERSONA_USERNAME:-ethics-manager-test}"
PERSONA_PASSWORD_FILE="${PERSONA_PASSWORD_FILE:-/srv/platform/secrets/faz35-test/ethics-manager-test.password}"
WRONG_ORG_USERNAME="${WRONG_ORG_USERNAME:-ethics-manager-wrong-org-test}"
WRONG_ORG_PASSWORD_FILE="${WRONG_ORG_PASSWORD_FILE:-/srv/platform/secrets/faz35-test/ethics-manager-wrong-org-test.password}"
DENIED_USERNAME="${DENIED_USERNAME:-ethics-manager-denied-test}"
DENIED_PASSWORD_FILE="${DENIED_PASSWORD_FILE:-/srv/platform/secrets/faz35-test/ethics-manager-denied-test.password}"
PERMISSION_ROLE_NAME="${PERMISSION_ROLE_NAME:-ETIK_SPEAK_MANAGER}"

for binding in \
  "$BASE_URL=https://testai.acik.com" \
  "$KC_BASE_URL=http://127.0.0.1:8082" \
  "$KC_REALM=platform-test" \
  "$KC_CONTAINER=platform-kc-test" \
  "$VAULT_CONTAINER=platform-vault-test" \
  "$VAULT_INIT_FILE=$VAULT_INIT_FILE_DEFAULT" \
  "$WRITER_VAULT_PATH=kv/platform/d35-3" \
  "$WRITER_USERNAME=d35-admin-persona" \
  "$WRITER_LOCAL_USER_ID=12" \
  "$WRITER_PROVISIONER_ROLE=ETIK_SPEAK_PROVISIONER" \
  "$PERSONA_USERNAME=ethics-manager-test" \
  "$PERSONA_PASSWORD_FILE=/srv/platform/secrets/faz35-test/ethics-manager-test.password" \
  "$WRONG_ORG_USERNAME=ethics-manager-wrong-org-test" \
  "$WRONG_ORG_PASSWORD_FILE=/srv/platform/secrets/faz35-test/ethics-manager-wrong-org-test.password" \
  "$DENIED_USERNAME=ethics-manager-denied-test" \
  "$DENIED_PASSWORD_FILE=/srv/platform/secrets/faz35-test/ethics-manager-denied-test.password" \
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

faz35_assert_test_keycloak_binding \
  "$KC_CONTAINER" "$KC_BASE_URL" "$KC_REALM" "$KC_EXPECTED_ISSUER" || {
  echo "FATAL: TEST Keycloak container/loopback/issuer binding is invalid" >&2
  exit 1
}

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
[ "$writer_username" = "$WRITER_USERNAME" ] || {
  echo "FATAL: permission-writer Vault username is not the canonical synthetic writer" >&2
  exit 1
}

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

# This is the final fail-closed writer gate before the first entitlement-side
# user materialization or permission mutation. A valid password alone is not
# authority: the live projection must be the exact dedicated non-admin writer.
writer_authz_code=$(http_status GET "$BASE_URL/api/v1/authz/me" \
  "$TMP_DIR/writer-authz-preflight.json" --config "$TMP_DIR/writer-auth.curl")
[ "$writer_authz_code" = 200 ] || {
  echo "FATAL: canonical permission writer authz preflight failed" >&2
  exit 1
}
jq -e --arg id "$WRITER_LOCAL_USER_ID" --arg role "$WRITER_PROVISIONER_ROLE" '
  .userId == $id and .subscriberId == ($id | tonumber) and
  .superAdmin == false and
  ((.roles // []) | sort) == [$role] and
  (.modules // {}) == {ACCESS:"MANAGE"} and
  ((.allowedModules // []) | sort) == ["ACCESS"] and
  ((.permissions // []) | sort) == ["ACCESS"] and
  (.actions // {}) == {} and (.reports // {}) == {} and
  (.scopes // []) == [] and (.allowedScopes // []) == []
' "$TMP_DIR/writer-authz-preflight.json" >/dev/null || {
  echo "FATAL: permission writer is not the exact least-privilege provisioner" >&2
  exit 1
}

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

# Every synthetic manager must be either exact-empty on first run or carry only
# the dedicated role and ETHIC=MANAGE on a rerun. Giving all three this same
# suite-level prerequisite lets the runtime acceptance reach the intended
# tenant/OpenFGA deny layers instead of being short-circuited by a 403.
for label in target wrong-org denied; do
  code=$(http_status GET "$BASE_URL/api/v1/authz/me" "$TMP_DIR/$label-authz-before.json" \
    --config "$TMP_DIR/$label-auth.curl")
  [ "$code" = 200 ] || { echo "FATAL: $label authz identity bootstrap failed" >&2; exit 1; }
  projection_state=$(faz35_authz_projection_state "$TMP_DIR/$label-authz-before.json") || {
    echo "FATAL: $label has a non-canonical full authorization projection" >&2
    exit 1
  }
  printf '%s' "$projection_state" >"$TMP_DIR/$label-projection-before"
done
unset projection_state

# The helper validates all three authz/local bindings before its first HTTP
# activation. Any mismatch returns nonzero with zero activation requests.
target_user_id=$(faz35_activate_verified_profiles \
  "$TMP_DIR" "$BASE_URL" "$TMP_DIR/writer-auth.curl") || exit 1
wrong_org_user_id=$(<"$TMP_DIR/wrong-org-user-id")
denied_user_id=$(<"$TMP_DIR/denied-user-id")
for user_id in "$target_user_id" "$wrong_org_user_id" "$denied_user_id"; do
  [[ "$user_id" =~ ^[0-9]+$ ]] || {
    echo "FATAL: synthetic manager local user ID is not numeric" >&2
    exit 1
  }
done
expected_member_ids=$(jq -nc \
  --argjson target "$target_user_id" \
  --argjson wrong_org "$wrong_org_user_id" \
  --argjson denied "$denied_user_id" \
  '[$target,$wrong_org,$denied] | sort')
[ "$(printf '%s' "$expected_member_ids" | jq 'unique | length')" = 3 ] || {
  echo "FATAL: synthetic manager local user IDs are not unique" >&2
  exit 1
}

roles_code=$(http_status GET "$BASE_URL/api/v1/roles" "$TMP_DIR/roles.json" \
  --config "$TMP_DIR/writer-auth.curl")
[ "$roles_code" = 200 ] || { echo "FATAL: permission role list failed" >&2; exit 1; }
faz35_validate_complete_role_catalog "$TMP_DIR/roles.json" || {
  echo "FATAL: permission role catalog is incomplete or paged" >&2
  exit 1
}
role_count=$(jq --arg name "$PERMISSION_ROLE_NAME" '[.items[]? | select(.name == $name)] | length' "$TMP_DIR/roles.json")
[ "$role_count" = 0 ] || [ "$role_count" = 1 ] || {
  echo "FATAL: dedicated permission role is not unique" >&2
  exit 1
}
role_id=$(jq -r --arg name "$PERMISSION_ROLE_NAME" '[.items[]? | select(.name == $name)][0].id // empty' "$TMP_DIR/roles.json")
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
  jq -e --argjson expected "$expected_member_ids" '
    type == "array" and length <= 3 and
    all(.[]?; (.userId | type) == "number") and
    (([.[].userId] | length) == ([.[].userId] | unique | length)) and
    (([.[].userId] - $expected) | length == 0)
  ' "$TMP_DIR/members-before.json" >/dev/null || {
    echo "FATAL: dedicated permission role contains an unrelated member" >&2
    exit 1
  }

  for label in target wrong-org denied; do
    [ "$(<"$TMP_DIR/$label-projection-before")" = EXACT_MANAGE ] || continue
    user_id=$(<"$TMP_DIR/$label-user-id")
    if ! jq -e '.granules == [{type:"MODULE",key:"ETHIC",grant:"MANAGE"}]' \
        "$TMP_DIR/granules-before.json" >/dev/null ||
        ! jq -e --argjson user_id "$user_id" \
          'any(.[]; .userId == $user_id)' "$TMP_DIR/members-before.json" >/dev/null; then
      echo "FATAL: existing $label ETHIC projection is not linked to the exact dedicated role" >&2
      exit 1
    fi
  done
else
  for label in target wrong-org denied; do
    [ "$(<"$TMP_DIR/$label-projection-before")" = ABSENT ] || {
      echo "FATAL: $label has ETHIC but the dedicated permission role is missing" >&2
      exit 1
    }
  done
  jq -n --arg name "$PERMISSION_ROLE_NAME" \
    '{name:$name,description:"Etik Speak dedicated synthetic test managers"}' >"$TMP_DIR/create-role.json"
  code=$(http_status POST "$BASE_URL/api/v1/roles" "$TMP_DIR/create-role-response.json" \
    --config "$TMP_DIR/writer-auth.curl" -H 'Content-Type: application/json' \
    --data-binary "@$TMP_DIR/create-role.json")
  [ "$code" = 201 ] || { echo "FATAL: dedicated permission role create failed" >&2; exit 1; }
  role_id=$(jq -r '.id // empty' "$TMP_DIR/create-role-response.json")
  [[ "$role_id" =~ ^[0-9]+$ ]] || { echo "FATAL: dedicated permission role id missing" >&2; exit 1; }
  printf '[]' >"$TMP_DIR/members-before.json"
fi

jq -n '{permissions:[{type:"MODULE",key:"ETHIC",grant:"MANAGE"}]}' >"$TMP_DIR/granules.json"
code=$(http_status PUT "$BASE_URL/api/v1/roles/$role_id/granules" "$TMP_DIR/mutation.json" \
  --config "$TMP_DIR/writer-auth.curl" -H 'Content-Type: application/json' \
  --data-binary "@$TMP_DIR/granules.json")
[ "$code" = 200 ] || { echo "FATAL: ETHIC granule writer failed" >&2; exit 1; }

current_member_ids=$(jq -c '[.[].userId] | unique | sort' "$TMP_DIR/members-before.json")
missing_member_ids=$(jq -nc --argjson expected "$expected_member_ids" \
  --argjson current "$current_member_ids" '$expected - $current')
if [ "$(printf '%s' "$missing_member_ids" | jq 'length')" -gt 0 ]; then
  jq -n --argjson missing "$missing_member_ids" '{userIds:$missing}' >"$TMP_DIR/member.json"
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
if [ "$code" != 200 ] || ! jq -e --argjson expected "$expected_member_ids" \
  'length == 3 and ([.[].userId] | sort) == $expected' "$TMP_DIR/members-after.json" >/dev/null; then
  echo "FATAL: ETHIC membership readback mismatch" >&2
  exit 1
fi

# RoleChangeEvent/version propagation may be asynchronous. Poll only the
# non-secret authorization projection and require the exact same suite-level
# prerequisite for all three personas before runtime tenant/OpenFGA denial.
entitlement_ready=false
for _ in $(seq 1 30); do
  all_personas_ready=true
  for label in target wrong-org denied; do
    expected_user_id=$(<"$TMP_DIR/$label-user-id")
    code=$(http_status GET "$BASE_URL/api/v1/authz/me" "$TMP_DIR/$label-authz-after.json" \
      --config "$TMP_DIR/$label-auth.curl")
    if [ "$code" != 200 ] ||
        [ "$(faz35_authz_member_id "$TMP_DIR/$label-authz-after.json" "$expected_user_id" 2>/dev/null || true)" != "$expected_user_id" ] ||
        [ "$(faz35_authz_projection_state "$TMP_DIR/$label-authz-after.json" 2>/dev/null || true)" != EXACT_MANAGE ]; then
      all_personas_ready=false
    fi
  done
  if [ "$all_personas_ready" = true ]; then
    entitlement_ready=true
    break
  fi
  sleep 1
done
[ "$entitlement_ready" = true ] || {
  echo "FATAL: all synthetic manager ETHIC entitlements did not become authoritative" >&2
  exit 1
}

unset target_user_id wrong_org_user_id denied_user_id expected_user_id user_id
unset expected_member_ids current_member_ids missing_member_ids all_personas_ready
echo "Permission: canonical role/granule/member writer granted all three synthetic managers exact ETHIC=MANAGE"
echo "Permission: tenant/OpenFGA remains the sole allow, wrong-org and explicit-deny differentiator"
echo "ETHICS_PERMISSION_ROLE_ID=$role_id"
