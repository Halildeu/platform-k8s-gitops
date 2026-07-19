#!/usr/bin/env bash
# Faz 35 Etik Speak: platform-test audience/scope plus a dedicated synthetic
# manager persona. The password is stored only in a chmod-600 host file.
set -euo pipefail

KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/home/halil/bootstrap-drill/vault-init-test.json}"
REALM="${REALM:-platform-test}"
PERSONA_USERNAME="${PERSONA_USERNAME:-ethics-manager-test}"
PERSONA_PASSWORD_FILE="${PERSONA_PASSWORD_FILE:-/home/halil/bootstrap-drill/ethics-manager-test.password}"
ETHICS_ORG_ID="${ETHICS_ORG_ID:-00000000-0000-0000-0000-000000000001}"
KCADM=/opt/keycloak/bin/kcadm.sh

[ "$KC_CONTAINER" = "platform-kc-test" ] && [ "$REALM" = "platform-test" ] || {
  echo "FATAL: this script is platform-test only" >&2
  exit 1
}
[ -r "$VAULT_INIT_FILE" ] || { echo "FATAL: Vault init file unreadable" >&2; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "FATAL: openssl missing" >&2; exit 1; }

kc() { docker exec "$KC_CONTAINER" "$KCADM" "$@"; }

vault_root_token=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE")
automation_json=$(docker exec -e VAULT_TOKEN="$vault_root_token" \
  -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" \
  vault kv get -format=json kv/platform/keycloak-automation)
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

ensure_scope() {
  local name=$1 include=$2 scope_id
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
  printf '%s' "$scope_id"
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
manage_scope_id=$(ensure_scope 'ethics:case:manage' true)

frontend_id=$(kc get clients -r "$REALM" -q clientId=frontend \
  --fields id --format csv --noquotes 2>/dev/null | head -1 || true)
[ -n "$frontend_id" ] || { echo "FATAL: frontend client missing" >&2; exit 1; }
bound_scopes=$(kc get "clients/$frontend_id/default-client-scopes" -r "$REALM" \
  --fields name --format csv --noquotes 2>/dev/null || true)
if ! printf '%s\n' "$bound_scopes" | grep -Fqx ethics-manager-audience; then
  kc update "clients/$frontend_id/default-client-scopes/$audience_scope_id" -r "$REALM" >/dev/null
fi
if ! printf '%s\n' "$bound_scopes" | grep -Fqx 'ethics:case:manage'; then
  kc update "clients/$frontend_id/default-client-scopes/$manage_scope_id" -r "$REALM" >/dev/null
fi

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

org_payload=$(jq -nc --arg org "$ETHICS_ORG_ID" '{attributes:{org_id:[$org]}}')
printf '%s' "$org_payload" | docker exec -i "$KC_CONTAINER" "$KCADM" \
  update "users/$persona_id" -r "$REALM" -f - --merge >/dev/null
actual_org=$(kc get "users/$persona_id" -r "$REALM" | jq -r '.attributes.org_id[0] // empty')
[ "$actual_org" = "$ETHICS_ORG_ID" ] || {
  echo "FATAL: synthetic persona org_id was not persisted" >&2
  exit 1
}

umask 077
if [ ! -s "$PERSONA_PASSWORD_FILE" ]; then
  persona_password=$(openssl rand -base64 36 | tr -d '/+=' | cut -c1-36)
  printf '%s' "$persona_password" >"$PERSONA_PASSWORD_FILE"
  chmod 600 "$PERSONA_PASSWORD_FILE"
else
  persona_password=$(<"$PERSONA_PASSWORD_FILE")
fi
printf '%s\n' "$persona_password" | docker exec -i \
  -e KC_PERSONA_ID="$persona_id" -e KC_REALM="$REALM" "$KC_CONTAINER" sh -c '
    set -eu
    IFS= read -r KC_PERSONA_PASSWORD
    /opt/keycloak/bin/kcadm.sh set-password -r "$KC_REALM" \
      --userid "$KC_PERSONA_ID" --new-password "$KC_PERSONA_PASSWORD" \
      --temporary=false >/dev/null
    unset KC_PERSONA_PASSWORD
  '
unset persona_password org_payload

echo "KC: ethics-manager audience + ethics:case:manage scope bound to frontend"
echo "KC: synthetic persona ready; password kept at $PERSONA_PASSWORD_FILE"
echo "ETHICS_STAFF_SUBJECT=$persona_id"
