#!/usr/bin/env bash
# Faz 35 Etik Speak: platform-test audience/scope plus a dedicated synthetic
# manager persona. The password is stored only in a chmod-600 host file.
set -euo pipefail
# A caller may invoke bash -x; disable tracing before any credential is read.
set +x

KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/home/halil/bootstrap-drill/vault-init-test.json}"
REALM="${REALM:-platform-test}"
PERSONA_USERNAME="${PERSONA_USERNAME:-ethics-manager-test}"
PERSONA_PASSWORD_FILE="${PERSONA_PASSWORD_FILE:-/home/halil/bootstrap-drill/ethics-manager-test.password}"
WRONG_ORG_USERNAME="${WRONG_ORG_USERNAME:-ethics-manager-wrong-org-test}"
WRONG_ORG_PASSWORD_FILE="${WRONG_ORG_PASSWORD_FILE:-/home/halil/bootstrap-drill/ethics-manager-wrong-org-test.password}"
DENIED_USERNAME="${DENIED_USERNAME:-ethics-manager-denied-test}"
DENIED_PASSWORD_FILE="${DENIED_PASSWORD_FILE:-/home/halil/bootstrap-drill/ethics-manager-denied-test.password}"
ETHICS_ORG_ID="${ETHICS_ORG_ID:-00000000-0000-0000-0000-000000000001}"
WRONG_ETHICS_ORG_ID="${WRONG_ETHICS_ORG_ID:-00000000-0000-0000-0000-000000000002}"
KCADM=/opt/keycloak/bin/kcadm.sh

[ "$KC_CONTAINER" = "platform-kc-test" ] && [ "$REALM" = "platform-test" ] || {
  echo "FATAL: this script is platform-test only" >&2
  exit 1
}
[ "$VAULT_CONTAINER" = "platform-vault-test" ] && \
  [ "$VAULT_INIT_FILE" = "/home/halil/bootstrap-drill/vault-init-test.json" ] && \
  [ "$PERSONA_USERNAME" = "ethics-manager-test" ] && \
  [ "$PERSONA_PASSWORD_FILE" = "/home/halil/bootstrap-drill/ethics-manager-test.password" ] && \
  [ "$WRONG_ORG_USERNAME" = "ethics-manager-wrong-org-test" ] && \
  [ "$WRONG_ORG_PASSWORD_FILE" = "/home/halil/bootstrap-drill/ethics-manager-wrong-org-test.password" ] && \
  [ "$DENIED_USERNAME" = "ethics-manager-denied-test" ] && \
  [ "$DENIED_PASSWORD_FILE" = "/home/halil/bootstrap-drill/ethics-manager-denied-test.password" ] && \
  [ "$WRONG_ETHICS_ORG_ID" = "00000000-0000-0000-0000-000000000002" ] && \
  [ "$ETHICS_ORG_ID" = "00000000-0000-0000-0000-000000000001" ] || {
  echo "FATAL: Keycloak/Vault/persona mutation target override refused" >&2
  exit 1
}
[ -r "$VAULT_INIT_FILE" ] && [ -f "$VAULT_INIT_FILE" ] && [ ! -L "$VAULT_INIT_FILE" ] || {
  echo "FATAL: Vault init file must be a readable regular non-symlink" >&2
  exit 1
}
[ "$(stat -c '%u' "$VAULT_INIT_FILE")" = "$(id -u)" ] && \
  [ "$(stat -c '%a' "$VAULT_INIT_FILE")" = 600 ] || {
  echo "FATAL: Vault init file must be invoking-user-owned mode 600" >&2
  exit 1
}
command -v openssl >/dev/null 2>&1 || { echo "FATAL: openssl missing" >&2; exit 1; }

kc() { docker exec "$KC_CONTAINER" "$KCADM" "$@"; }

vault_root_token=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE")
automation_json=$(printf '%s\n' "$vault_root_token" | docker exec -i \
  -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
    set -eu
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    exec vault kv get -format=json kv/platform/keycloak-automation
  ')
automation_client=$(printf '%s' "$automation_json" | jq -r '.data.data.client_id')
automation_secret=$(printf '%s' "$automation_json" | jq -r '.data.data.client_secret')
unset vault_root_token automation_json

login_realm=""
for candidate in "$REALM" master; do
  if printf '%s\n' "$automation_secret" | docker exec -i \
    -e KC_CLIENT="$automation_client" -e KC_LOGIN_REALM="$candidate" \
    "$KC_CONTAINER" sh -c '
      set -eu
      IFS= read -r KC_CLI_CLIENT_SECRET
      export KC_CLI_CLIENT_SECRET
      /opt/keycloak/bin/kcadm.sh config credentials \
        --server http://localhost:8080 --realm "$KC_LOGIN_REALM" \
        --client "$KC_CLIENT" >/dev/null 2>&1
      unset KC_CLI_CLIENT_SECRET
    '; then
    login_realm="$candidate"
    break
  fi
done
unset automation_secret
[ -n "$login_realm" ] || { echo "FATAL: Keycloak automation login failed" >&2; exit 1; }
# kcadm natively consumes KC_CLI_CLIENT_SECRET when --secret is omitted. Prove
# the resulting service-account session is usable without placing the secret in
# argv or printing the token/config.
docker exec "$KC_CONTAINER" "$KCADM" config credentials --status >/dev/null 2>&1 || {
  echo "FATAL: Keycloak automation session status failed" >&2
  exit 1
}

# Inspect every existing named object before the first mutation. Missing
# objects are allowed and created below; drifted or over-privileged objects are
# never partially reconciled in place.
existing_role=$(kc get roles/ethics-manager -r "$REALM" 2>/dev/null || true)
if [ -n "$existing_role" ]; then
  printf '%s' "$existing_role" | jq -e '
    .name == "ethics-manager" and .clientRole == false and .composite == false and
    .description == "Etik Speak sentetik test manager" and
    ((.attributes // {}) | length == 0)
  ' >/dev/null || {
    echo "FATAL: pre-mutation ethics-manager realm role drift" >&2
    exit 1
  }
fi

preflight_existing_scope() {
  local name=$1 include=$2 scope_id scope_json mappers bindings
  scope_id=$(kc get client-scopes -r "$REALM" --fields id,name \
    --format csv --noquotes 2>/dev/null | awk -F, -v n="$name" '$2==n{print $1; exit}')
  [ -n "$scope_id" ] || return 0
  scope_json=$(kc get "client-scopes/$scope_id" -r "$REALM")
  printf '%s' "$scope_json" | jq -e --arg name "$name" --arg include "$include" '
    .name == $name and .protocol == "openid-connect" and
    .attributes["include.in.token.scope"] == $include and
    .attributes["display.on.consent.screen"] == "false" and
    ((.attributes | keys - ["display.on.consent.screen", "gui.order", "include.in.token.scope"]) | length == 0)
  ' >/dev/null || {
    echo "FATAL: pre-mutation client scope attribute drift: $name" >&2
    exit 1
  }
  mappers=$(kc get "client-scopes/$scope_id/protocol-mappers/models" -r "$REALM")
  if [ "$name" = ethics-manager-audience ]; then
    printf '%s' "$mappers" | jq -e '
      ([.[].name] - ["ethics-manager-audience-mapper", "ethics-org-id-mapper"] | length == 0) and
      (all(.[] | select(.name == "ethics-manager-audience-mapper");
        .protocol == "openid-connect" and .protocolMapper == "oidc-audience-mapper" and
        .config == {"access.token.claim":"true","id.token.claim":"false","included.client.audience":"ethics-manager"})) and
      (all(.[] | select(.name == "ethics-org-id-mapper");
        .protocol == "openid-connect" and .protocolMapper == "oidc-usermodel-attribute-mapper" and
        .config == {"access.token.claim":"true","claim.name":"org_id","id.token.claim":"false","jsonType.label":"String","multivalued":"false","user.attribute":"org_id","userinfo.token.claim":"false"}))
    ' >/dev/null || {
      echo "FATAL: pre-mutation audience/org mapper drift" >&2
      exit 1
    }
  else
    printf '%s' "$mappers" | jq -e 'length == 0' >/dev/null || {
      echo "FATAL: pre-mutation ethics management scope mapper drift" >&2
      exit 1
    }
  fi
  bindings=$(kc get "client-scopes/$scope_id/scope-mappings/realm" -r "$REALM")
  printf '%s' "$bindings" | jq -e \
    '[.[].name | select(. != "ethics-manager")] | length == 0' >/dev/null || {
    echo "FATAL: pre-mutation client scope role-mapping drift: $name" >&2
    exit 1
  }
}
preflight_existing_scope ethics-manager-audience false
preflight_existing_scope 'ethics:case:manage' true

existing_manager_client=$(kc get clients -r "$REALM" -q clientId=ethics-manager 2>/dev/null \
  | jq '.[0] // empty')
if [ -n "$existing_manager_client" ]; then
  printf '%s' "$existing_manager_client" | jq -e '
    .clientId == "ethics-manager" and .enabled == true and .bearerOnly == true and
    .publicClient == false and .standardFlowEnabled == false and
    .implicitFlowEnabled == false and .directAccessGrantsEnabled == false and
    .serviceAccountsEnabled == false and
    ((.redirectUris // []) | length == 0) and ((.webOrigins // []) | length == 0)
  ' >/dev/null || {
    echo "FATAL: pre-mutation ethics-manager bearer client drift" >&2
    exit 1
  }
fi

for existing_username in "$PERSONA_USERNAME" "$WRONG_ORG_USERNAME" "$DENIED_USERNAME"; do
  existing_user_id=$(kc get users -r "$REALM" -q "username=$existing_username" -q exact=true \
    --fields id --format csv --noquotes 2>/dev/null | head -1 || true)
  [ -n "$existing_user_id" ] || continue
  existing_mappings=$(kc get "users/$existing_user_id/role-mappings" -r "$REALM")
  printf '%s' "$existing_mappings" | jq -e '
    (([((.realmMappings // [])[] | .name)] - ["default-roles-platform-test", "ethics-manager"]) | length == 0) and
    ([((.clientMappings // {}) | to_entries[]? | .value.mappings[]? | .name)] | length == 0)
  ' >/dev/null || {
    echo "FATAL: pre-mutation persona role drift: $existing_username" >&2
    exit 1
  }
  kc get "users/$existing_user_id/groups" -r "$REALM" | jq -e 'length == 0' >/dev/null || {
    echo "FATAL: pre-mutation persona group drift: $existing_username" >&2
    exit 1
  }
done

if ! kc get roles/ethics-manager -r "$REALM" >/dev/null 2>&1; then
  kc create roles -r "$REALM" -s name=ethics-manager \
    -s 'description=Etik Speak sentetik test manager' >/dev/null
fi
kc get roles/ethics-manager -r "$REALM" | jq -e '
  .name == "ethics-manager" and
  .clientRole == false and
  .composite == false and
  .description == "Etik Speak sentetik test manager" and
  ((.attributes // {}) | length == 0)
' >/dev/null || {
  echo "FATAL: ethics-manager realm role drifted from the non-composite allowlist" >&2
  exit 1
}

manager_client_id=$(kc get clients -r "$REALM" -q clientId=ethics-manager \
  --fields id --format csv --noquotes 2>/dev/null | head -1 || true)
if [ -z "$manager_client_id" ]; then
  kc create clients -r "$REALM" \
    -s clientId=ethics-manager -s enabled=true -s bearerOnly=true \
    -s publicClient=false -s standardFlowEnabled=false \
    -s implicitFlowEnabled=false -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=false >/dev/null
  manager_client_id=$(kc get clients -r "$REALM" -q clientId=ethics-manager \
    --fields id --format csv --noquotes | head -1)
  echo "KC: ethics-manager bearer client created"
fi
kc get "clients/$manager_client_id" -r "$REALM" | jq -e '
  .clientId == "ethics-manager" and .enabled == true and .bearerOnly == true and
  .publicClient == false and .standardFlowEnabled == false and
  .implicitFlowEnabled == false and .directAccessGrantsEnabled == false and
  .serviceAccountsEnabled == false and
  ((.redirectUris // []) | length == 0) and ((.webOrigins // []) | length == 0)
' >/dev/null || {
  echo "FATAL: ethics-manager bearer client drifted from the exact allowlist" >&2
  exit 1
}

ensure_scope() {
  local name=$1 include=$2 scope_id scope_json
  scope_id=$(kc get client-scopes -r "$REALM" --fields id,name \
    --format csv --noquotes 2>/dev/null | awk -F, -v n="$name" '$2==n{print $1; exit}')
  if [ -z "$scope_id" ]; then
    kc create client-scopes -r "$REALM" -s "name=$name" \
      -s protocol=openid-connect \
      -s "attributes.\"include.in.token.scope\"=$include" \
      -s 'attributes."display.on.consent.screen"=false' >/dev/null
    scope_id=$(kc get client-scopes -r "$REALM" --fields id,name \
      --format csv --noquotes | awk -F, -v n="$name" '$2==n{print $1; exit}')
  fi
  scope_json=$(kc get "client-scopes/$scope_id" -r "$REALM")
  printf '%s' "$scope_json" | jq -e --arg name "$name" --arg include "$include" '
    .name == $name and
    .protocol == "openid-connect" and
    .attributes["include.in.token.scope"] == $include and
    .attributes["display.on.consent.screen"] == "false" and
    ((.attributes | keys - ["display.on.consent.screen", "gui.order", "include.in.token.scope"]) | length == 0)
  ' >/dev/null || {
    echo "FATAL: client scope $name drifted from the exact attribute allowlist" >&2
    exit 1
  }
  printf '%s' "$scope_id"
}

ensure_scope_role_binding() {
  local scope_id=$1 scope_name=$2 bindings role_payload
  bindings=$(kc get "client-scopes/$scope_id/scope-mappings/realm" \
    -r "$REALM" 2>/dev/null || printf '[]')
  printf '%s' "$bindings" | jq -e '
    [.[].name | select(. != "ethics-manager")] | length == 0
  ' >/dev/null || {
    echo "FATAL: $scope_name has an unexpected realm-role scope mapping" >&2
    exit 1
  }
  if ! printf '%s' "$bindings" | jq -e \
      '.[]? | select(.name == "ethics-manager")' >/dev/null; then
    role_payload=$(kc get roles/ethics-manager -r "$REALM" \
      | jq '[{id:.id,name:.name,description:.description,composite:.composite,clientRole:.clientRole,containerId:.containerId}]')
    printf '%s' "$role_payload" | docker exec -i "$KC_CONTAINER" "$KCADM" \
      create "client-scopes/$scope_id/scope-mappings/realm" -r "$REALM" -f - >/dev/null
  fi
  kc get "client-scopes/$scope_id/scope-mappings/realm" -r "$REALM" \
    | jq -e '[.[].name] == ["ethics-manager"]' >/dev/null || {
      echo "FATAL: $scope_name role mapping is not the exact ethics-manager allowlist" >&2
      exit 1
    }
}

audience_scope_id=$(ensure_scope ethics-manager-audience false)
mapper_rows=$(kc get "client-scopes/$audience_scope_id/protocol-mappers/models" \
  -r "$REALM" --fields id,name --format csv --noquotes 2>/dev/null || true)
audience_mapper_id=$(printf '%s\n' "$mapper_rows" | awk -F, \
  '$2=="ethics-manager-audience-mapper"{print $1; exit}')
if [ -z "$audience_mapper_id" ]; then
  kc create "client-scopes/$audience_scope_id/protocol-mappers/models" -r "$REALM" \
    -s name=ethics-manager-audience-mapper -s protocol=openid-connect \
    -s protocolMapper=oidc-audience-mapper \
    -s 'config."included.client.audience"=ethics-manager' \
    -s 'config."access.token.claim"=true' \
    -s 'config."id.token.claim"=false' >/dev/null
fi
org_mapper_id=$(kc get "client-scopes/$audience_scope_id/protocol-mappers/models" \
  -r "$REALM" --fields id,name --format csv --noquotes 2>/dev/null \
  | awk -F, '$2=="ethics-org-id-mapper"{print $1; exit}' || true)
if [ -z "$org_mapper_id" ]; then
  kc create "client-scopes/$audience_scope_id/protocol-mappers/models" -r "$REALM" \
    -s name=ethics-org-id-mapper -s protocol=openid-connect \
    -s protocolMapper=oidc-usermodel-attribute-mapper \
    -s 'config."user.attribute"=org_id' \
    -s 'config."claim.name"=org_id' \
    -s 'config."jsonType.label"=String' \
    -s 'config."access.token.claim"=true' \
    -s 'config."id.token.claim"=false' \
    -s 'config."userinfo.token.claim"=false' \
    -s 'config."multivalued"=false' >/dev/null
fi
manage_scope_id=$(ensure_scope 'ethics:case:manage' true)
audience_mappers=$(kc get "client-scopes/$audience_scope_id/protocol-mappers/models" -r "$REALM")
printf '%s' "$audience_mappers" | jq -e '
  length == 2 and
  ([.[].name] | sort) == ["ethics-manager-audience-mapper", "ethics-org-id-mapper"] and
  (map(select(.name == "ethics-manager-audience-mapper"))[0] |
    .protocol == "openid-connect" and
    .protocolMapper == "oidc-audience-mapper" and
    .config == {
      "access.token.claim":"true",
      "id.token.claim":"false",
      "included.client.audience":"ethics-manager"
    }) and
  (map(select(.name == "ethics-org-id-mapper"))[0] |
    .protocol == "openid-connect" and
    .protocolMapper == "oidc-usermodel-attribute-mapper" and
    .config == {
      "access.token.claim":"true",
      "claim.name":"org_id",
      "id.token.claim":"false",
      "jsonType.label":"String",
      "multivalued":"false",
      "user.attribute":"org_id",
      "userinfo.token.claim":"false"
    })
' >/dev/null || {
  echo "FATAL: ethics-manager-audience mapper set drifted from the exact allowlist" >&2
  exit 1
}
kc get "client-scopes/$manage_scope_id/protocol-mappers/models" -r "$REALM" \
  | jq -e 'length == 0' >/dev/null || {
    echo "FATAL: ethics:case:manage scope must not contain protocol mappers" >&2
    exit 1
  }
ensure_scope_role_binding "$audience_scope_id" ethics-manager-audience
ensure_scope_role_binding "$manage_scope_id" 'ethics:case:manage'

frontend_id=$(kc get clients -r "$REALM" -q clientId=frontend \
  --fields id --format csv --noquotes 2>/dev/null | head -1 || true)
[ -n "$frontend_id" ] || { echo "FATAL: frontend client missing" >&2; exit 1; }
bound_scopes=$(kc get "clients/$frontend_id/default-client-scopes" -r "$REALM" \
  --fields name --format csv --noquotes 2>/dev/null || true)
if printf '%s\n' "$bound_scopes" | grep -Fqx ethics-manager-audience; then
  kc delete "clients/$frontend_id/default-client-scopes/$audience_scope_id" -r "$REALM" >/dev/null
fi
if printf '%s\n' "$bound_scopes" | grep -Fqx 'ethics:case:manage'; then
  kc delete "clients/$frontend_id/default-client-scopes/$manage_scope_id" -r "$REALM" >/dev/null
fi
optional_scopes=$(kc get "clients/$frontend_id/optional-client-scopes" -r "$REALM" \
  --fields name --format csv --noquotes 2>/dev/null || true)
if ! printf '%s\n' "$optional_scopes" | grep -Fqx ethics-manager-audience; then
  kc update "clients/$frontend_id/optional-client-scopes/$audience_scope_id" -r "$REALM" >/dev/null
fi
if ! printf '%s\n' "$optional_scopes" | grep -Fqx 'ethics:case:manage'; then
  kc update "clients/$frontend_id/optional-client-scopes/$manage_scope_id" -r "$REALM" >/dev/null
fi

assert_persona_role_boundary() {
  local user_id=$1 username=$2 role_mappings groups
  role_mappings=$(kc get "users/$user_id/role-mappings" -r "$REALM")
  printf '%s' "$role_mappings" | jq -e '
    ([((.realmMappings // [])[] | .name)] | index("ethics-manager") != null) and
    (([((.realmMappings // [])[] | .name)] - ["default-roles-platform-test", "ethics-manager"]) | length == 0) and
    ([((.clientMappings // {}) | to_entries[]? | .value.mappings[]? | .name)] | length == 0)
  ' >/dev/null || {
    echo "FATAL: $username has unexpected realm/client role mappings" >&2
    exit 1
  }
  groups=$(kc get "users/$user_id/groups" -r "$REALM")
  printf '%s' "$groups" | jq -e 'length == 0' >/dev/null || {
    echo "FATAL: $username must not inherit privileges from a group" >&2
    exit 1
  }
}

persona_id=$(kc get users -r "$REALM" -q "username=$PERSONA_USERNAME" -q exact=true \
  --fields id --format csv --noquotes 2>/dev/null | head -1 || true)
if [ -z "$persona_id" ]; then
  kc create users -r "$REALM" -s "username=$PERSONA_USERNAME" \
    -s enabled=true -s emailVerified=true \
    -s "email=$PERSONA_USERNAME@test.invalid" \
    -s firstName=Ethics -s lastName=Manager >/dev/null
  persona_id=$(kc get users -r "$REALM" -q "username=$PERSONA_USERNAME" -q exact=true \
    --fields id --format csv --noquotes | head -1)
fi

kc add-roles -r "$REALM" --uusername "$PERSONA_USERNAME" \
  --rolename ethics-manager >/dev/null
assert_persona_role_boundary "$persona_id" "$PERSONA_USERNAME"

org_payload=$(jq -nc --arg org "$ETHICS_ORG_ID" '{attributes:{org_id:[$org]}}')
printf '%s' "$org_payload" | docker exec -i "$KC_CONTAINER" "$KCADM" \
  update "users/$persona_id" -r "$REALM" -f - --merge >/dev/null
actual_org=$(kc get "users/$persona_id" -r "$REALM" | jq -r '.attributes.org_id[0] // empty')
[ "$actual_org" = "$ETHICS_ORG_ID" ] || {
  echo "FATAL: synthetic persona org_id was not persisted" >&2
  exit 1
}

umask 077
if [ -e "$PERSONA_PASSWORD_FILE" ] || [ -L "$PERSONA_PASSWORD_FILE" ]; then
  [ ! -L "$PERSONA_PASSWORD_FILE" ] && [ -f "$PERSONA_PASSWORD_FILE" ] || {
    echo "FATAL: persona password path must be a regular non-symlink" >&2
    exit 1
  }
else
  persona_password=$(openssl rand -base64 36 | tr -d '/+=' | cut -c1-36)
  (set -C; printf '%s' "$persona_password" >"$PERSONA_PASSWORD_FILE") || {
    echo "FATAL: exclusive persona password file creation failed" >&2
    exit 1
  }
fi
chmod 600 "$PERSONA_PASSWORD_FILE"
[ "$(stat -c '%u' "$PERSONA_PASSWORD_FILE")" = "$(id -u)" ] && \
  [ "$(stat -c '%a' "$PERSONA_PASSWORD_FILE")" = 600 ] || {
  echo "FATAL: persona password owner/mode assertion failed" >&2
  exit 1
}
persona_password=$(<"$PERSONA_PASSWORD_FILE")
[[ "$persona_password" =~ ^[A-Za-z0-9_-]{24,128}$ ]] || {
  echo "FATAL: persona password fails the length/format policy" >&2
  exit 1
}
# Admin REST reset-password body travels through stdin; no child process argv
# contains the cleartext password.
jq -nc --arg value "$persona_password" \
  '{type:"password",value:$value,temporary:false}' \
  | docker exec -i "$KC_CONTAINER" "$KCADM" \
      update "users/$persona_id/reset-password" -r "$REALM" -f - >/dev/null

# Mint one short-lived synthetic access token and validate only its non-secret
# claims. The password is request-body stdin, never curl/docker argv. The raw
# access/refresh tokens remain in shell variables and are unset without output.
token_json=$(printf '%s\n' "$persona_password" | docker exec -i \
  -e KC_REALM="$REALM" -e KC_PERSONA_USERNAME="$PERSONA_USERNAME" \
  "$KC_CONTAINER" sh -c '
    set -eu
    command -v curl >/dev/null 2>&1 || exit 70
    IFS= read -r KC_PERSONA_PASSWORD
    printf "grant_type=password&client_id=frontend&username=%s&password=%s&scope=openid%%20ethics-manager-audience%%20ethics%%3Acase%%3Amanage" \
      "$KC_PERSONA_USERNAME" "$KC_PERSONA_PASSWORD" \
      | curl -fsS -X POST \
          -H "Content-Type: application/x-www-form-urlencoded" \
          --data-binary @- \
          "http://localhost:8080/realms/$KC_REALM/protocol/openid-connect/token"
    unset KC_PERSONA_PASSWORD
  ') || {
  unset persona_password org_payload
  echo "FATAL: synthetic persona token mint failed" >&2
  exit 1
}
access_token=$(printf '%s' "$token_json" | jq -r '.access_token // empty')
[ -n "$access_token" ] || {
  unset persona_password org_payload token_json access_token
  echo "FATAL: synthetic persona token response had no access token" >&2
  exit 1
}
token_claims=$(printf '%s' "$access_token" | python3 -c '
import base64, json, sys
token = sys.stdin.read().strip()
parts = token.split(".")
if len(parts) != 3:
    raise SystemExit(1)
payload = parts[1] + "=" * (-len(parts[1]) % 4)
claims = json.loads(base64.urlsafe_b64decode(payload))
print(json.dumps({
    "aud": claims.get("aud"),
    "scope": claims.get("scope", ""),
    "org_id": claims.get("org_id"),
    "roles": claims.get("realm_access", {}).get("roles", []),
    "resource_clients": sorted(claims.get("resource_access", {}).keys()),
    "groups": claims.get("groups", []),
    "has_authorization": "authorization" in claims,
}, separators=(",", ":")))
') || {
  unset persona_password org_payload token_json access_token token_claims
  echo "FATAL: synthetic persona access token was not a valid JWT" >&2
  exit 1
}

printf '%s' "$token_claims" | jq -e '
  ((.aud | type == "array") and (.aud | index("ethics-manager") != null)) or
  ((.aud | type == "string") and .aud == "ethics-manager")
' >/dev/null || {
  unset persona_password org_payload token_json access_token token_claims
  echo "FATAL: synthetic access token audience lacks ethics-manager" >&2
  exit 1
}
printf '%s' "$token_claims" | jq -e '
  (.scope | split(" ") | index("ethics:case:manage") != null)
' >/dev/null || {
  unset persona_password org_payload token_json access_token token_claims
  echo "FATAL: synthetic access token scope lacks ethics:case:manage" >&2
  exit 1
}
[ "$(printf '%s' "$token_claims" | jq -r '.org_id // empty')" = "$ETHICS_ORG_ID" ] || {
  unset persona_password org_payload token_json access_token token_claims
  echo "FATAL: synthetic access token org_id is not canonical test tenant" >&2
  exit 1
}
printf '%s' "$token_claims" | jq -e \
  '.roles | index("ethics-manager") != null' >/dev/null || {
  unset persona_password org_payload token_json access_token token_claims
  echo "FATAL: synthetic access token lacks ethics-manager realm role" >&2
  exit 1
}
printf '%s' "$token_claims" | jq -e '
  ((if (.aud | type) == "array" then .aud else [.aud] end)
    | index("realm-management") == null and
      index("admin-cli") == null and
      index("security-admin-console") == null) and
  ((.roles - ["default-roles-platform-test", "ethics-manager", "offline_access", "uma_authorization"]) | length == 0) and
  ((.resource_clients - ["account", "frontend"]) | length == 0) and
  (.groups | length == 0) and
  (.has_authorization == false)
' >/dev/null || {
  unset persona_password org_payload token_json access_token token_claims
  echo "FATAL: synthetic access token contains a forbidden audience, role, client role, group, or authorization claim" >&2
  exit 1
}
unset persona_password org_payload token_json access_token token_claims

ensure_negative_persona() {
  local username=$1 org_id=$2 password_file=$3 negative_id payload password token_json access_token claims
  negative_id=$(kc get users -r "$REALM" -q "username=$username" -q exact=true \
    --fields id --format csv --noquotes 2>/dev/null | head -1 || true)
  if [ -z "$negative_id" ]; then
    kc create users -r "$REALM" -s "username=$username" \
      -s enabled=true -s emailVerified=true \
      -s "email=$username@test.invalid" \
      -s firstName=Ethics -s lastName=Negative >/dev/null
    negative_id=$(kc get users -r "$REALM" -q "username=$username" -q exact=true \
      --fields id --format csv --noquotes | head -1)
  fi
  kc add-roles -r "$REALM" --uusername "$username" --rolename ethics-manager >/dev/null
  assert_persona_role_boundary "$negative_id" "$username"
  payload=$(jq -nc --arg org "$org_id" '{attributes:{org_id:[$org]}}')
  printf '%s' "$payload" | docker exec -i "$KC_CONTAINER" "$KCADM" \
    update "users/$negative_id" -r "$REALM" -f - --merge >/dev/null

  umask 077
  if [ -e "$password_file" ] || [ -L "$password_file" ]; then
    [ ! -L "$password_file" ] && [ -f "$password_file" ] || {
      echo "FATAL: negative-persona password path must be a regular non-symlink" >&2
      exit 1
    }
  else
    password=$(openssl rand -base64 36 | tr -d '/+=' | cut -c1-36)
    (set -C; printf '%s' "$password" >"$password_file") || {
      echo "FATAL: exclusive negative-persona password creation failed" >&2
      exit 1
    }
  fi
  chmod 600 "$password_file"
  [ "$(stat -c '%u' "$password_file")" = "$(id -u)" ] && \
    [ "$(stat -c '%a' "$password_file")" = 600 ] || {
    echo "FATAL: negative-persona password owner/mode assertion failed" >&2
    exit 1
  }
  password=$(<"$password_file")
  [[ "$password" =~ ^[A-Za-z0-9_-]{24,128}$ ]] || {
    echo "FATAL: negative-persona password fails the length/format policy" >&2
    exit 1
  }
  jq -nc --arg value "$password" '{type:"password",value:$value,temporary:false}' \
    | docker exec -i "$KC_CONTAINER" "$KCADM" \
        update "users/$negative_id/reset-password" -r "$REALM" -f - >/dev/null

  token_json=$(printf '%s\n' "$password" | docker exec -i \
    -e KC_REALM="$REALM" -e KC_PERSONA_USERNAME="$username" \
    "$KC_CONTAINER" sh -c '
      set -eu
      IFS= read -r KC_PERSONA_PASSWORD
      printf "grant_type=password&client_id=frontend&username=%s&password=%s&scope=openid%%20ethics-manager-audience%%20ethics%%3Acase%%3Amanage" \
        "$KC_PERSONA_USERNAME" "$KC_PERSONA_PASSWORD" \
        | curl -fsS -X POST -H "Content-Type: application/x-www-form-urlencoded" \
            --data-binary @- "http://localhost:8080/realms/$KC_REALM/protocol/openid-connect/token"
      unset KC_PERSONA_PASSWORD
    ')
  access_token=$(printf '%s' "$token_json" | jq -r '.access_token // empty')
  claims=$(printf '%s' "$access_token" | python3 -c '
import base64, json, sys
token = sys.stdin.read().strip().split(".")
if len(token) != 3: raise SystemExit(1)
payload = token[1] + "=" * (-len(token[1]) % 4)
data = json.loads(base64.urlsafe_b64decode(payload))
print(json.dumps({"aud": data.get("aud"), "scope": data.get("scope", ""),
                  "org_id": data.get("org_id"),
                  "roles": data.get("realm_access", {}).get("roles", []),
                  "resource_clients": sorted(data.get("resource_access", {}).keys()),
                  "groups": data.get("groups", []),
                  "has_authorization": "authorization" in data}, separators=(",", ":")))
')
  printf '%s' "$claims" | jq -e --arg org "$org_id" '
    (.org_id == $org) and
    (((.aud | type == "array") and (.aud | index("ethics-manager") != null)) or
     ((.aud | type == "string") and .aud == "ethics-manager")) and
    (.scope | split(" ") | index("ethics:case:manage") != null) and
    (.roles | index("ethics-manager") != null) and
    ((if (.aud | type) == "array" then .aud else [.aud] end)
      | index("realm-management") == null and index("admin-cli") == null and
        index("security-admin-console") == null) and
    ((.roles - ["default-roles-platform-test", "ethics-manager", "offline_access", "uma_authorization"]) | length == 0) and
    ((.resource_clients - ["account", "frontend"]) | length == 0) and
    (.groups | length == 0) and
    (.has_authorization == false)
  ' >/dev/null || {
    echo "FATAL: negative-persona token contract failed" >&2
    exit 1
  }
  unset password token_json access_token claims payload
  printf '%s' "$negative_id"
}

wrong_org_id=$(ensure_negative_persona "$WRONG_ORG_USERNAME" "$WRONG_ETHICS_ORG_ID" "$WRONG_ORG_PASSWORD_FILE")
denied_id=$(ensure_negative_persona "$DENIED_USERNAME" "$ETHICS_ORG_ID" "$DENIED_PASSWORD_FILE")
printf '%s' "$wrong_org_id$denied_id" | grep -Eq '^[0-9A-Fa-f-]{72}$' || {
  echo "FATAL: negative-persona UUID output contract failed" >&2
  exit 1
}

echo "KC: ethics-manager audience + ethics:case:manage are optional frontend scopes bound to the ethics-manager role"
echo "KC: synthetic access-token aud/scope/org_id/role contract OK"
echo "KC: synthetic persona ready; password kept at $PERSONA_PASSWORD_FILE"
echo "KC: wrong-org and OpenFGA-denied synthetic personas ready; no OpenFGA tuples granted"
echo "ETHICS_WRONG_ORG_PASSWORD_FILE=$WRONG_ORG_PASSWORD_FILE"
echo "ETHICS_DENIED_PASSWORD_FILE=$DENIED_PASSWORD_FILE"
echo "ETHICS_STAFF_SUBJECT=$persona_id"
echo "ETHICS_WRONG_ORG_SUBJECT=$wrong_org_id"
echo "ETHICS_DENIED_SUBJECT=$denied_id"
