#!/usr/bin/env bash
#
# setup-user-mfa-admin-client.sh — gitops#3211: the dedicated Keycloak
# confidential client behind the panel MFA section (user-service
# KeycloakAdminClient, platform-backend#1034).
#
# Desired state (idempotent, CONVERGED not just created — Codex 019fb687):
#   1. Confidential client `user-mfa-admin`: serviceAccountsEnabled, no
#      browser/direct-access flows, no redirect surface. An EXISTING client
#      is PUT back to this exact shape and the live shape is re-read — a
#      pre-existing loose client (say with direct-access enabled) must not
#      inherit the credential.
#   2. Its service account holds EXACTLY realm-management `view-users` +
#      `manage-users`. Missing roles are granted, EXTRA roles are REMOVED,
#      and the final set is re-read and verified before any secret leaves
#      Keycloak — a leaked secret must not be able to touch clients, realm
#      config or any other admin surface.
#   3. Client secret seeded into test Vault kv/platform/user-service
#      property `keycloak_admin_api_client_secret`. Secret AND the Vault
#      root token travel via stdin into the container — neither ever
#      appears on host argv/stdout; only sha256 prefixes are printed.
#
# All Keycloak REST calls are fail-closed (`curl -sS --fail-with-body`
# under set -e): an HTTP 4xx/5xx stops the script before the seed step.
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
# Fail-closed REST: any 4xx/5xx aborts under set -e (Codex 019fb687 P1-3).
q() { curl -sS --fail-with-body -H "$AUTH" "$@"; }

desired_shape() {
  cat <<JSON
{
  "clientId": "$CLIENT_ID",
  "protocol": "openid-connect",
  "enabled": true,
  "publicClient": false,
  "serviceAccountsEnabled": true,
  "standardFlowEnabled": false,
  "implicitFlowEnabled": false,
  "directAccessGrantsEnabled": false,
  "redirectUris": [],
  "webOrigins": [],
  "description": "gitops#3211 panel MFA proxy — realm-management view-users+manage-users ONLY"
}
JSON
}

# 1) client — create or CONVERGE to the exact desired shape (P1-1)
CID=$(q "$API/clients?clientId=$CLIENT_ID" | jq -r '.[0].id // empty')
if [ -z "$CID" ]; then
  desired_shape | q -X POST "$API/clients" -H "$CT" -d @- >/dev/null
  CID=$(q "$API/clients?clientId=$CLIENT_ID" | jq -r '.[0].id // empty')
  echo "client created: $CID"
else
  desired_shape | q -X PUT "$API/clients/$CID" -H "$CT" -d @- >/dev/null
  echo "client converged: $CID"
fi
# Post-condition on the LIVE representation; refuse to seed on deviation.
LIVE=$(q "$API/clients/$CID")
for check in \
    '.publicClient == false' \
    '.serviceAccountsEnabled == true' \
    '.standardFlowEnabled == false' \
    '.directAccessGrantsEnabled == false' \
    '(.redirectUris | length) == 0'; do
  echo "$LIVE" | jq -e "$check" >/dev/null \
    || { echo "ERROR: client shape converge FAILED ($check) — secret seed edilmedi" >&2; exit 3; }
done
echo "client shape verified"

# 2) service-account roles — EXACT set {view-users, manage-users} (P1-2)
SA_UID=$(q "$API/clients/$CID/service-account-user" | jq -r .id)
RM_CID=$(q "$API/clients?clientId=realm-management" | jq -r '.[0].id')
for role in view-users manage-users; do
  HAS=$(q "$API/users/$SA_UID/role-mappings/clients/$RM_CID" | jq -r --arg r "$role" '.[]?|select(.name==$r).name // empty')
  if [ -z "$HAS" ]; then
    ROLE_JSON=$(q "$API/clients/$RM_CID/roles/$role")
    printf '[%s]' "$ROLE_JSON" | q -X POST "$API/users/$SA_UID/role-mappings/clients/$RM_CID" -H "$CT" -d @- >/dev/null
    echo "role granted: $role"
  else
    echo "role ok: $role"
  fi
done
EXTRA_JSON=$(q "$API/users/$SA_UID/role-mappings/clients/$RM_CID" \
  | jq '[.[] | select(.name != "view-users" and .name != "manage-users")]')
if [ "$(echo "$EXTRA_JSON" | jq length)" != "0" ]; then
  echo "$EXTRA_JSON" | jq -r '.[].name' | sed 's/^/role REMOVING (least-privilege): /'
  printf '%s' "$EXTRA_JSON" | q -X DELETE "$API/users/$SA_UID/role-mappings/clients/$RM_CID" -H "$CT" -d @- >/dev/null
fi
# Re-read; the exact final set gates the seed (missing AND extra covered).
FINAL=$(q "$API/users/$SA_UID/role-mappings/clients/$RM_CID" | jq -r '[.[].name] | sort | join(",")')
[ "$FINAL" = "manage-users,view-users" ] \
  || { echo "ERROR: rol kümesi exact değil ('$FINAL') — secret seed edilmedi" >&2; exit 3; }
echo "role set exact: $FINAL"

# 3) secret -> Vault. Root token AND value go via stdin, never argv (P1-4):
#    stdin line 1 = vault token (consumed by `read`), the rest = the secret
#    value consumed by kv patch's `-`.
[ -r "$VAULT_INIT_FILE" ] || { echo "ERROR: vault init file unreadable" >&2; exit 1; }
ROOT_TOKEN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE")"
SECRET="$(q "$API/clients/$CID/client-secret" | jq -r .value)"
[ -n "$SECRET" ] && [ "$SECRET" != "null" ] || { echo "ERROR: client secret okunamadı" >&2; exit 1; }

printf '%s\n%s' "$ROOT_TOKEN" "$SECRET" | sudo docker exec -i "$VAULT_CONTAINER" \
  sh -c "IFS= read -r VAULT_TOKEN; export VAULT_TOKEN VAULT_ADDR=http://127.0.0.1:8200; exec vault kv patch -mount=kv $KV_PATH $KV_PROP=-" >/dev/null

H_KC=$(printf '%s' "$SECRET" | sha256sum | cut -c1-12)
H_VAULT=$(printf '%s' "$ROOT_TOKEN" | sudo docker exec -i "$VAULT_CONTAINER" \
  sh -c "IFS= read -r VAULT_TOKEN; export VAULT_TOKEN VAULT_ADDR=http://127.0.0.1:8200; exec vault kv get -field=$KV_PROP -mount=kv $KV_PATH" \
  | tr -d '\n' | sha256sum | cut -c1-12)
echo "SEEDED kc sha256[:12]=$H_KC vault sha256[:12]=$H_VAULT"
[ "$H_KC" = "$H_VAULT" ] && echo "CROSS-SIDE-MATCH" || { echo "MISMATCH" >&2; exit 3; }
