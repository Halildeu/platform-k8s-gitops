#!/usr/bin/env bash
#
# setup-user-mfa-admin-client.sh — gitops#3211: the dedicated Keycloak
# confidential client behind the panel MFA section (user-service
# KeycloakAdminClient, platform-backend#1034).
#
# Desired state (idempotent):
#   1. Confidential client `user-mfa-admin`: serviceAccountsEnabled, no
#      browser/direct-access flows, no redirect surface.
#   2. Its service account holds ONLY realm-management client roles
#      `view-users` + `manage-users` (manage-users covers credential delete
#      and attribute update — the two panel mutations). Nothing else; a
#      leaked secret cannot touch clients, realm config or other admin
#      surfaces.
#   3. Client secret seeded into test Vault kv/platform/user-service
#      property `keycloak_admin_api_client_secret` (stdin pipe; the value
#      never reaches argv/stdout — only sha256 prefixes are printed).
#
# TEST-scoped by the same realm→KC hard-bind as setup-privileged-mfa.sh;
# prod provisioning is owner-gated and NOT done here.
#
set -euo pipefail
umask 077

REALM="${REALM:-platform-test}"
case "$REALM" in
  platform-test) KC="platform-kc-test"; KC_PORT="8082" ;;
  *) echo "ERROR: bu script yalnız platform-test için (prod owner-gated)" >&2; exit 1 ;;
esac

CLIENT_ID="user-mfa-admin"
VAULT_CONTAINER="platform-vault-test"
VAULT_INIT_FILE="/srv/platform/secrets/backup-auth/vault-init-test.json"
KV_PATH="platform/user-service"
KV_PROP="keycloak_admin_api_client_secret"
API="http://127.0.0.1:${KC_PORT}/admin/realms/${REALM}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' yok" >&2; exit 1; }; }
need curl; need jq

get_token() {
  sudo docker exec "$KC" /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8080 --realm master \
    --user "$(sudo docker exec "$KC" sh -lc 'printf %s "$KEYCLOAK_ADMIN"')" \
    --password "$(sudo docker exec "$KC" sh -lc 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"')" \
    >/dev/null 2>&1
  sudo docker exec "$KC" sh -lc 'cat ~/.keycloak/kcadm.config 2>/dev/null || cat /opt/keycloak/.keycloak/kcadm.config 2>/dev/null' \
    | jq -r '.endpoints[]|.[].token // empty' | head -1
}
TOKEN="$(get_token)"; AUTH="Authorization: Bearer $TOKEN"; CT="Content-Type: application/json"
q() { curl -s -H "$AUTH" "$@"; }

# 1) client
CID=$(q "$API/clients?clientId=$CLIENT_ID" | jq -r '.[0].id // empty')
if [ -z "$CID" ]; then
  q -X POST "$API/clients" -H "$CT" -d "{
    \"clientId\": \"$CLIENT_ID\",
    \"protocol\": \"openid-connect\",
    \"publicClient\": false,
    \"serviceAccountsEnabled\": true,
    \"standardFlowEnabled\": false,
    \"directAccessGrantsEnabled\": false,
    \"redirectUris\": [],
    \"description\": \"gitops#3211 panel MFA proxy — realm-management view-users+manage-users ONLY\"
  }" >/dev/null
  CID=$(q "$API/clients?clientId=$CLIENT_ID" | jq -r '.[0].id // empty')
  echo "client created: $CID"
else
  echo "client exists: $CID"
fi

# 2) service-account roles (exact set; report any extras as drift)
SA_UID=$(q "$API/clients/$CID/service-account-user" | jq -r .id)
RM_CID=$(q "$API/clients?clientId=realm-management" | jq -r '.[0].id')
for role in view-users manage-users; do
  HAS=$(q "$API/users/$SA_UID/role-mappings/clients/$RM_CID" | jq -r --arg r "$role" '.[]?|select(.name==$r).name // empty')
  if [ -z "$HAS" ]; then
    ROLE_JSON=$(q "$API/clients/$RM_CID/roles/$role")
    q -X POST "$API/users/$SA_UID/role-mappings/clients/$RM_CID" -H "$CT" -d "[$ROLE_JSON]" >/dev/null
    echo "role granted: $role"
  else
    echo "role ok: $role"
  fi
done
EXTRA=$(q "$API/users/$SA_UID/role-mappings/clients/$RM_CID" | jq -r '[.[].name]-["view-users","manage-users"]|.[]' )
[ -z "$EXTRA" ] || echo "UYARI: fazla realm-management rolü var (least-privilege drift): $EXTRA"

# 3) secret -> Vault (stdin, value never on argv/stdout)
[ -r "$VAULT_INIT_FILE" ] || { echo "ERROR: vault init file unreadable" >&2; exit 1; }
ROOT_TOKEN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE")"
SECRET="$(q "$API/clients/$CID/client-secret" | jq -r .value)"
[ -n "$SECRET" ] && [ "$SECRET" != "null" ] || { echo "ERROR: client secret okunamadı" >&2; exit 1; }
printf '%s' "$SECRET" | sudo docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="$ROOT_TOKEN" \
  "$VAULT_CONTAINER" vault kv patch -mount=kv "$KV_PATH" "$KV_PROP=-" >/dev/null

H_KC=$(printf '%s' "$SECRET" | sha256sum | cut -c1-12)
H_VAULT=$(sudo docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="$ROOT_TOKEN" \
  "$VAULT_CONTAINER" vault kv get -field="$KV_PROP" -mount=kv "$KV_PATH" | tr -d '\n' | sha256sum | cut -c1-12)
echo "SEEDED kc sha256[:12]=$H_KC vault sha256[:12]=$H_VAULT"
[ "$H_KC" = "$H_VAULT" ] && echo "CROSS-SIDE-MATCH" || { echo "MISMATCH" >&2; exit 3; }
