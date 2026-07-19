#!/usr/bin/env bash
# Faz 35 Etik Speak: platform-test audience/scope plus a dedicated synthetic
# manager persona. The password is stored only in a chmod-600 host file.
set -euo pipefail
# A caller may invoke bash -x; disable tracing before any credential is read.
set +x

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/faz35/lib-test-keycloak-binding.sh
source "${SCRIPT_DIR}/lib-test-keycloak-binding.sh"

KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
REALM="${REALM:-platform-test}"
KC_TOKEN_BASE_URL="${KC_TOKEN_BASE_URL:-http://127.0.0.1:8082}"
readonly KC_EXPECTED_ISSUER="https://testai.acik.com/realms/platform-test"
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
[ "$KC_TOKEN_BASE_URL" = "http://127.0.0.1:8082" ] && \
  [ "$PERSONA_USERNAME" = "ethics-manager-test" ] && \
  [ "$PERSONA_PASSWORD_FILE" = "/home/halil/bootstrap-drill/ethics-manager-test.password" ] && \
  [ "$WRONG_ORG_USERNAME" = "ethics-manager-wrong-org-test" ] && \
  [ "$WRONG_ORG_PASSWORD_FILE" = "/home/halil/bootstrap-drill/ethics-manager-wrong-org-test.password" ] && \
  [ "$DENIED_USERNAME" = "ethics-manager-denied-test" ] && \
  [ "$DENIED_PASSWORD_FILE" = "/home/halil/bootstrap-drill/ethics-manager-denied-test.password" ] && \
  [ "$WRONG_ETHICS_ORG_ID" = "00000000-0000-0000-0000-000000000002" ] && \
  [ "$ETHICS_ORG_ID" = "00000000-0000-0000-0000-000000000001" ] || {
  echo "FATAL: Keycloak/persona mutation target override refused" >&2
  exit 1
}
command -v openssl >/dev/null 2>&1 || { echo "FATAL: openssl missing" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "FATAL: host curl missing" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "FATAL: host docker missing" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "FATAL: host jq missing" >&2; exit 1; }
faz35_assert_test_keycloak_binding \
  "${KC_CONTAINER}" "${KC_TOKEN_BASE_URL}" "${REALM}" "${KC_EXPECTED_ISSUER}" || {
  echo "FATAL: TEST Keycloak container/loopback/issuer binding is invalid" >&2
  exit 1
}

prepare_synthetic_password_file() {
  local file=$1 label=$2 candidate owner mode parent
  parent=$(dirname "$file")
  [ -d "$parent" ] && [ ! -L "$parent" ] || {
    echo "FATAL: $label password parent must be a real directory" >&2
    exit 1
  }
  if [ -e "$file" ] || [ -L "$file" ]; then
    [ ! -L "$file" ] && [ -f "$file" ] || {
      echo "FATAL: $label password path must be a regular non-symlink" >&2
      exit 1
    }
    owner=$(stat -c '%u' "$file")
    mode=$(stat -c '%a' "$file")
    [ "$owner" = "$(id -u)" ] && [ "$mode" = 600 ] || {
      echo "FATAL: $label existing password must be invoking-user-owned mode 600" >&2
      exit 1
    }
  else
    candidate=$(openssl rand -base64 36 | tr -d '/+=' | cut -c1-36)
    umask 077
    (set -C; printf '%s' "$candidate" >"$file") || {
      echo "FATAL: exclusive $label password file creation failed" >&2
      exit 1
    }
    chmod 600 "$file"
    unset candidate
  fi
  [[ "$(<"$file")" =~ ^[A-Za-z0-9_-]{24,128}$ ]] || {
    echo "FATAL: $label password fails the length/format policy" >&2
    exit 1
  }
}

# All local credential targets are proven safe before the first Keycloak realm
# mutation. Creating a missing host-local synthetic password is recoverable;
# widening a realm role before discovering an unsafe path is not.
prepare_synthetic_password_file "$PERSONA_PASSWORD_FILE" persona
prepare_synthetic_password_file "$WRONG_ORG_PASSWORD_FILE" wrong-org-persona
prepare_synthetic_password_file "$DENIED_PASSWORD_FILE" denied-persona

KCADM_CONFIG=$(docker exec "$KC_CONTAINER" mktemp /tmp/kcadm-faz35.XXXXXX)
printf '%s' "$KCADM_CONFIG" | grep -Eq '^/tmp/kcadm-faz35\.[A-Za-z0-9]+$' || {
  echo "FATAL: per-run kcadm config path contract failed" >&2
  exit 1
}
docker exec "$KC_CONTAINER" chmod 600 "$KCADM_CONFIG"
trap 'unset token_json access_token claims; [ -z "${KCADM_CONFIG:-}" ] || docker exec "$KC_CONTAINER" rm -f "$KCADM_CONFIG" >/dev/null 2>&1 || true' EXIT

kc() { docker exec "$KC_CONTAINER" "$KCADM" "$@" --config "$KCADM_CONFIG"; }

# The permanent svc-kc-automation account intentionally lacks manage-realm.
# Do not widen it. Use the canonical admin password file only inside the
# Keycloak container and bind it to this per-run, mode-600 config. The password
# never crosses the container boundary or appears in argv/stdout.
if ! docker exec -e KC_CONFIG="$KCADM_CONFIG" "$KC_CONTAINER" sh -c '
  set -eu
  [ -n "${KEYCLOAK_ADMIN_PASSWORD_FILE:-}" ]
  [ -r "$KEYCLOAK_ADMIN_PASSWORD_FILE" ]
  KC_CLI_PASSWORD=$(cat "$KEYCLOAK_ADMIN_PASSWORD_FILE")
  [ -n "$KC_CLI_PASSWORD" ]
  export KC_CLI_PASSWORD
  /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8080 --realm master --user admin \
    --config "$KC_CONFIG" >/dev/null 2>&1
  unset KC_CLI_PASSWORD
'; then
  echo "FATAL: isolated Keycloak admin login failed" >&2
  exit 1
fi
kc config credentials --status >/dev/null 2>&1 || {
  echo "FATAL: isolated Keycloak admin session status failed" >&2
  exit 1
}

mint_synthetic_token() {
  local username=$1 password
  IFS= read -r password
  printf 'grant_type=password&client_id=frontend&username=%s&password=%s&scope=openid%%20ethics-manager-audience%%20ethics%%3Acase%%3Amanage' \
    "$username" "$password" \
    | curl -fsS --max-time 10 -X POST \
        -H 'Content-Type: application/x-www-form-urlencoded' \
        --data-binary @- \
        "$KC_TOKEN_BASE_URL/realms/$REALM/protocol/openid-connect/token"
  unset password
}

kc_get_scope_client_mappings() {
  local scope_id=$1 output status expected_missing
  printf '%s' "$scope_id" | grep -Eq \
    '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$' || {
    echo "FATAL: client-scope mapping lookup requires a canonical UUID" >&2
    return 1
  }
  status=0
  if output=$(kc get "client-scopes/$scope_id/scope-mappings/clients" -r "$REALM" 2>&1); then
    status=0
  else
    status=$?
  fi
  if [ "$status" -eq 0 ]; then
    printf '%s' "$output" | jq -e 'type == "array"' >/dev/null || {
      echo "FATAL: Keycloak client-scope client-mapping response is not an array" >&2
      return 1
    }
    printf '%s' "$output"
    return 0
  fi
  expected_missing="Resource not found for url: http://localhost:8080/admin/realms/$REALM/client-scopes/$scope_id/scope-mappings/clients"
  if [ "$output" = "$expected_missing" ]; then
    printf '[]'
    return 0
  fi
  echo "FATAL: Keycloak client-scope client-mapping read failed" >&2
  return "$status"
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
  local name=$1 include_value=$2 scope_id scope_json mappers bindings client_bindings
  scope_id=$(kc get client-scopes -r "$REALM" --fields id,name \
    --format csv --noquotes | awk -F, -v n="$name" '$2==n{print $1}')
  [ -n "$scope_id" ] || return 0
  scope_json=$(kc get "client-scopes/$scope_id" -r "$REALM")
  printf '%s' "$scope_json" | jq -e --arg name "$name" --arg include_value "$include_value" '
    .name == $name and .protocol == "openid-connect" and
    .attributes["include.in.token.scope"] == $include_value and
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
        .config == {"access.token.claim":"true","id.token.claim":"false","included.client.audience":"ethics-manager","introspection.token.claim":"true","userinfo.token.claim":"false"})) and
      (all(.[] | select(.name == "ethics-org-id-mapper");
        .protocol == "openid-connect" and .protocolMapper == "oidc-usermodel-attribute-mapper" and
        .config == {"access.token.claim":"true","claim.name":"org_id","id.token.claim":"false","introspection.token.claim":"true","jsonType.label":"String","multivalued":"false","user.attribute":"org_id","userinfo.token.claim":"false"}))
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
  client_bindings=$(kc_get_scope_client_mappings "$scope_id")
  printf '%s' "$client_bindings" | jq -e 'length == 0' >/dev/null || {
    echo "FATAL: pre-mutation client scope has unexpected client-role mappings: $name" >&2
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
    --fields id --format csv --noquotes | sed -n '1p')
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
  --fields id --format csv --noquotes | sed -n '1p')
if [ -z "$manager_client_id" ]; then
  kc create clients -r "$REALM" \
    -s clientId=ethics-manager -s enabled=true -s bearerOnly=true \
    -s publicClient=false -s standardFlowEnabled=false \
    -s implicitFlowEnabled=false -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=false >/dev/null
  manager_client_id=$(kc get clients -r "$REALM" -q clientId=ethics-manager \
    --fields id --format csv --noquotes | sed -n '1p')
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
  local name=$1 include_value=$2 scope_id scope_json
  scope_id=$(kc get client-scopes -r "$REALM" --fields id,name \
    --format csv --noquotes | awk -F, -v n="$name" '$2==n{print $1}')
  if [ -z "$scope_id" ]; then
    kc create client-scopes -r "$REALM" -s "name=$name" \
      -s protocol=openid-connect \
      -s "attributes.\"include.in.token.scope\"=$include_value" \
      -s 'attributes."display.on.consent.screen"=false' >/dev/null
    scope_id=$(kc get client-scopes -r "$REALM" --fields id,name \
      --format csv --noquotes | awk -F, -v n="$name" '$2==n{print $1}')
  fi
  scope_json=$(kc get "client-scopes/$scope_id" -r "$REALM")
  printf '%s' "$scope_json" | jq -e --arg name "$name" --arg include_value "$include_value" '
    .name == $name and
    .protocol == "openid-connect" and
    .attributes["include.in.token.scope"] == $include_value and
    .attributes["display.on.consent.screen"] == "false" and
    ((.attributes | keys - ["display.on.consent.screen", "gui.order", "include.in.token.scope"]) | length == 0)
  ' >/dev/null || {
    echo "FATAL: client scope $name drifted from the exact attribute allowlist" >&2
    exit 1
  }
  printf '%s' "$scope_id"
}

ensure_scope_role_binding() {
  local scope_id=$1 scope_name=$2 bindings role_payload client_bindings
  bindings=$(kc get "client-scopes/$scope_id/scope-mappings/realm" -r "$REALM")
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
      create "client-scopes/$scope_id/scope-mappings/realm" -r "$REALM" \
      -f - --config "$KCADM_CONFIG" >/dev/null
  fi
  kc get "client-scopes/$scope_id/scope-mappings/realm" -r "$REALM" \
    | jq -e '[.[].name] == ["ethics-manager"]' >/dev/null || {
      echo "FATAL: $scope_name role mapping is not the exact ethics-manager allowlist" >&2
      exit 1
    }
  client_bindings=$(kc_get_scope_client_mappings "$scope_id")
  printf '%s' "$client_bindings" | jq -e 'length == 0' >/dev/null || {
    echo "FATAL: $scope_name has unexpected client-role scope mappings" >&2
    exit 1
  }
}

audience_scope_id=$(ensure_scope ethics-manager-audience false)
mapper_rows=$(kc get "client-scopes/$audience_scope_id/protocol-mappers/models" \
  -r "$REALM" --fields id,name --format csv --noquotes)
audience_mapper_id=$(printf '%s\n' "$mapper_rows" | awk -F, \
  '$2=="ethics-manager-audience-mapper"{print $1}')
if [ -z "$audience_mapper_id" ]; then
  kc create "client-scopes/$audience_scope_id/protocol-mappers/models" -r "$REALM" \
    -s name=ethics-manager-audience-mapper -s protocol=openid-connect \
    -s protocolMapper=oidc-audience-mapper \
    -s 'config."included.client.audience"=ethics-manager' \
    -s 'config."access.token.claim"=true' \
    -s 'config."id.token.claim"=false' \
    -s 'config."introspection.token.claim"=true' \
    -s 'config."userinfo.token.claim"=false' >/dev/null
fi
org_mapper_id=$(kc get "client-scopes/$audience_scope_id/protocol-mappers/models" \
  -r "$REALM" --fields id,name --format csv --noquotes \
  | awk -F, '$2=="ethics-org-id-mapper"{print $1}')
if [ -z "$org_mapper_id" ]; then
  kc create "client-scopes/$audience_scope_id/protocol-mappers/models" -r "$REALM" \
    -s name=ethics-org-id-mapper -s protocol=openid-connect \
    -s protocolMapper=oidc-usermodel-attribute-mapper \
    -s 'config."user.attribute"=org_id' \
    -s 'config."claim.name"=org_id' \
    -s 'config."jsonType.label"=String' \
    -s 'config."access.token.claim"=true' \
    -s 'config."id.token.claim"=false' \
    -s 'config."introspection.token.claim"=true' \
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
      "included.client.audience":"ethics-manager",
      "introspection.token.claim":"true",
      "userinfo.token.claim":"false"
    }) and
  (map(select(.name == "ethics-org-id-mapper"))[0] |
    .protocol == "openid-connect" and
    .protocolMapper == "oidc-usermodel-attribute-mapper" and
    .config == {
      "access.token.claim":"true",
      "claim.name":"org_id",
      "id.token.claim":"false",
      "introspection.token.claim":"true",
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
  --fields id --format csv --noquotes | sed -n '1p')
[ -n "$frontend_id" ] || { echo "FATAL: frontend client missing" >&2; exit 1; }
bound_scopes=$(kc get "clients/$frontend_id/default-client-scopes" -r "$REALM" \
  --fields name --format csv --noquotes)
if printf '%s\n' "$bound_scopes" | grep -Fqx ethics-manager-audience; then
  kc delete "clients/$frontend_id/default-client-scopes/$audience_scope_id" -r "$REALM" >/dev/null
fi
if printf '%s\n' "$bound_scopes" | grep -Fqx 'ethics:case:manage'; then
  kc delete "clients/$frontend_id/default-client-scopes/$manage_scope_id" -r "$REALM" >/dev/null
fi
optional_scopes=$(kc get "clients/$frontend_id/optional-client-scopes" -r "$REALM" \
  --fields name --format csv --noquotes)
if ! printf '%s\n' "$optional_scopes" | grep -Fqx ethics-manager-audience; then
  kc update "clients/$frontend_id/optional-client-scopes/$audience_scope_id" -r "$REALM" >/dev/null
fi
if ! printf '%s\n' "$optional_scopes" | grep -Fqx 'ethics:case:manage'; then
  kc update "clients/$frontend_id/optional-client-scopes/$manage_scope_id" -r "$REALM" >/dev/null
fi

assert_persona_role_boundary() {
  local user_id=$1 username=$2 role_mappings groups effective_realm client_id client_name effective_client client_inventory client_rows
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
  effective_realm=$(kc get "users/$user_id/role-mappings/realm/composite" -r "$REALM")
  printf '%s' "$effective_realm" | jq -e '
    ([.[].name] | index("ethics-manager") != null) and
    (([.[].name] - ["default-roles-platform-test", "ethics-manager", "offline_access", "uma_authorization"]) | length == 0)
  ' >/dev/null || {
    echo "FATAL: $username has unexpected effective/composite realm roles" >&2
    exit 1
  }
  client_inventory=$(kc get clients -r "$REALM") || {
    echo "FATAL: $username client inventory could not be read" >&2
    exit 1
  }
  printf '%s' "$client_inventory" | jq -e '
    type == "array" and length > 0 and
    all(.[]; (.id | type == "string" and length > 0) and
             (.clientId | type == "string" and length > 0))
  ' >/dev/null || {
    echo "FATAL: $username client inventory is empty or malformed" >&2
    exit 1
  }
  client_rows=$(printf '%s' "$client_inventory" | jq -er '.[] | [.id,.clientId] | @tsv') || {
    echo "FATAL: $username client inventory projection failed" >&2
    exit 1
  }
  while IFS=$'\t' read -r client_id client_name; do
    [ -n "$client_id" ] || continue
    effective_client=$(kc get "users/$user_id/role-mappings/clients/$client_id/composite" -r "$REALM")
    case "$client_name" in
      account)
        printf '%s' "$effective_client" | jq -e '
          ([.[].name] - ["manage-account", "manage-account-links", "view-profile"]) | length == 0
        ' >/dev/null || {
          echo "FATAL: $username has unexpected effective account client roles" >&2
          exit 1
        }
        ;;
      frontend)
        printf '%s' "$effective_client" | jq -e 'length == 0' >/dev/null || {
          echo "FATAL: $username has unexpected effective frontend client roles" >&2
          exit 1
        }
        ;;
      *)
        printf '%s' "$effective_client" | jq -e 'length == 0' >/dev/null || {
          echo "FATAL: $username has unexpected effective client roles on $client_name" >&2
          exit 1
        }
        ;;
    esac
  done <<<"$client_rows"
}

assert_persona_profile_precondition() {
  local user_id=$1 username=$2 expected_email=$3 first_name=$4 last_name=$5 org_id=$6 profile
  profile=$(kc get "users/$user_id" -r "$REALM")
  printf '%s' "$profile" | jq -e \
    --arg id "$user_id" --arg username "$username" --arg email "$expected_email" \
    --arg first "$first_name" --arg last "$last_name" --arg org "$org_id" '
      .id == $id and .username == $username and .email == $email and
      .firstName == $first and .lastName == $last and
      .enabled == true and .emailVerified == true and
      (.requiredActions // []) == [] and
      (((.attributes // {}) == {}) or ((.attributes // {}) == {org_id:[$org]}))
    ' >/dev/null || {
      echo "FATAL: $username existing synthetic profile drifted from its exact contract" >&2
      exit 1
    }
}

assert_persona_profile_postcondition() {
  local user_id=$1 username=$2 expected_email=$3 first_name=$4 last_name=$5 org_id=$6 profile
  profile=$(kc get "users/$user_id" -r "$REALM")
  printf '%s' "$profile" | jq -e \
    --arg id "$user_id" --arg username "$username" --arg email "$expected_email" \
    --arg first "$first_name" --arg last "$last_name" --arg org "$org_id" '
      .id == $id and .username == $username and .email == $email and
      .firstName == $first and .lastName == $last and
      .enabled == true and .emailVerified == true and
      (.requiredActions // []) == [] and
      (.attributes // {}) == {org_id:[$org]}
    ' >/dev/null || {
      echo "FATAL: $username synthetic profile postcondition is not exact" >&2
      exit 1
    }
}

persona_matches=$(kc get users -r "$REALM" -q "username=$PERSONA_USERNAME" -q exact=true)
persona_count=$(printf '%s' "$persona_matches" | jq 'length')
[ "$persona_count" -le 1 ] || {
  echo "FATAL: canonical synthetic persona username is ambiguous" >&2
  exit 1
}
persona_id=$(printf '%s' "$persona_matches" | jq -r '.[0].id // empty')
if [ "$persona_count" -eq 0 ]; then
  kc create users -r "$REALM" -s "username=$PERSONA_USERNAME" \
    -s enabled=true -s emailVerified=true \
    -s "email=$PERSONA_USERNAME@test.invalid" \
    -s firstName=Ethics -s lastName=Manager >/dev/null
  persona_matches=$(kc get users -r "$REALM" -q "username=$PERSONA_USERNAME" -q exact=true)
  [ "$(printf '%s' "$persona_matches" | jq 'length')" -eq 1 ] || {
    echo "FATAL: canonical synthetic persona creation was not unique" >&2
    exit 1
  }
  persona_id=$(printf '%s' "$persona_matches" | jq -r '.[0].id')
fi
printf '%s' "$persona_id" | grep -Eq \
  '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$' || {
  echo "FATAL: synthetic persona canonical UUID contract failed" >&2
  exit 1
}
assert_persona_profile_precondition "$persona_id" "$PERSONA_USERNAME" \
  "$PERSONA_USERNAME@test.invalid" Ethics Manager "$ETHICS_ORG_ID"

kc add-roles -r "$REALM" --uusername "$PERSONA_USERNAME" \
  --rolename ethics-manager >/dev/null
assert_persona_role_boundary "$persona_id" "$PERSONA_USERNAME"

org_payload=$(jq -nc --arg org "$ETHICS_ORG_ID" '{attributes:{org_id:[$org]}}')
printf '%s' "$org_payload" | docker exec -i "$KC_CONTAINER" "$KCADM" \
  update "users/$persona_id" -r "$REALM" -f - --merge \
  --config "$KCADM_CONFIG" >/dev/null
actual_org=$(kc get "users/$persona_id" -r "$REALM" | jq -r '.attributes.org_id[0] // empty')
[ "$actual_org" = "$ETHICS_ORG_ID" ] || {
  echo "FATAL: synthetic persona org_id was not persisted" >&2
  exit 1
}
assert_persona_profile_postcondition "$persona_id" "$PERSONA_USERNAME" \
  "$PERSONA_USERNAME@test.invalid" Ethics Manager "$ETHICS_ORG_ID"

# The path, owner, mode and content were established before the first realm
# mutation by prepare_synthetic_password_file(). Recheck without repairing.
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
      update "users/$persona_id/reset-password" -r "$REALM" -f - \
      --config "$KCADM_CONFIG" >/dev/null

# Mint one short-lived synthetic access token and validate only its non-secret
# claims. The password is request-body stdin, never curl/docker argv. The raw
# access/refresh tokens remain in shell variables and are unset without output.
token_json=$(printf '%s\n' "$persona_password" \
  | mint_synthetic_token "$PERSONA_USERNAME") || {
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
    "resource_roles": claims.get("resource_access", {}),
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
  (((.resource_roles | keys) - ["account", "frontend"]) | length == 0) and
  (((.resource_roles.account.roles // []) - ["manage-account", "manage-account-links", "view-profile"]) | length == 0) and
  ((.resource_roles.frontend.roles // []) | length == 0) and
  (.groups | length == 0) and
  (.has_authorization == false)
' >/dev/null || {
  unset persona_password org_payload token_json access_token token_claims
  echo "FATAL: synthetic access token contains a forbidden audience, role, client role, group, or authorization claim" >&2
  exit 1
}
unset persona_password org_payload token_json access_token token_claims

ensure_negative_persona() {
  local username=$1 org_id=$2 password_file=$3 negative_id payload password token_json access_token claims matches count
  matches=$(kc get users -r "$REALM" -q "username=$username" -q exact=true)
  count=$(printf '%s' "$matches" | jq 'length')
  [ "$count" -le 1 ] || {
    echo "FATAL: $username synthetic username is ambiguous" >&2
    exit 1
  }
  negative_id=$(printf '%s' "$matches" | jq -r '.[0].id // empty')
  if [ "$count" -eq 0 ]; then
    kc create users -r "$REALM" -s "username=$username" \
      -s enabled=true -s emailVerified=true \
      -s "email=$username@test.invalid" \
      -s firstName=Ethics -s lastName=Negative >/dev/null
    matches=$(kc get users -r "$REALM" -q "username=$username" -q exact=true)
    [ "$(printf '%s' "$matches" | jq 'length')" -eq 1 ] || {
      echo "FATAL: $username synthetic persona creation was not unique" >&2
      exit 1
    }
    negative_id=$(printf '%s' "$matches" | jq -r '.[0].id')
  fi
  assert_persona_profile_precondition "$negative_id" "$username" \
    "$username@test.invalid" Ethics Negative "$org_id"
  kc add-roles -r "$REALM" --uusername "$username" --rolename ethics-manager >/dev/null
  assert_persona_role_boundary "$negative_id" "$username"
  payload=$(jq -nc --arg org "$org_id" '{attributes:{org_id:[$org]}}')
  printf '%s' "$payload" | docker exec -i "$KC_CONTAINER" "$KCADM" \
    update "users/$negative_id" -r "$REALM" -f - --merge \
    --config "$KCADM_CONFIG" >/dev/null
  assert_persona_profile_postcondition "$negative_id" "$username" \
    "$username@test.invalid" Ethics Negative "$org_id"

  # Preflight created or validated all three files before realm mutation.
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
        update "users/$negative_id/reset-password" -r "$REALM" -f - \
        --config "$KCADM_CONFIG" >/dev/null

  token_json=$(printf '%s\n' "$password" | mint_synthetic_token "$username")
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
                  "resource_roles": data.get("resource_access", {}),
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
    (((.resource_roles | keys) - ["account", "frontend"]) | length == 0) and
    (((.resource_roles.account.roles // []) - ["manage-account", "manage-account-links", "view-profile"]) | length == 0) and
    ((.resource_roles.frontend.roles // []) | length == 0) and
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
for negative_id in "$wrong_org_id" "$denied_id"; do
  printf '%s' "$negative_id" | grep -Eq \
    '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$' || {
    echo "FATAL: negative-persona canonical UUID output contract failed" >&2
    exit 1
  }
done

echo "KC: ethics-manager audience + ethics:case:manage are optional frontend scopes bound to the ethics-manager role"
echo "KC: synthetic access-token aud/scope/org_id/role contract OK"
echo "KC: synthetic persona ready; password kept at $PERSONA_PASSWORD_FILE"
echo "KC: wrong-org and OpenFGA-denied synthetic personas ready; no OpenFGA tuples granted"
echo "ETHICS_WRONG_ORG_PASSWORD_FILE=$WRONG_ORG_PASSWORD_FILE"
echo "ETHICS_DENIED_PASSWORD_FILE=$DENIED_PASSWORD_FILE"
echo "ETHICS_STAFF_SUBJECT=$persona_id"
echo "ETHICS_WRONG_ORG_SUBJECT=$wrong_org_id"
echo "ETHICS_DENIED_SUBJECT=$denied_id"
