#!/usr/bin/env bash
#
# TEST-only smoke-budget-v1 lane (gitops #3466, #3454 follow-up).
#
# Unattended planner-token path for live budget acceptance. The `frontend`
# client is authorization-code-only (A2c: DAG=false) and typing a persona
# password into a login form is outside the agent credential boundary, so the
# authorized budget journey needs a dedicated confidential ROPC client —
# the smoke-ats-v1 precedent (#2746 Opsiyon B):
#
#   - client smoke-budget-v1: confidential, directAccessGrants only,
#     fullScopeAllowed=false; scope carries ONLY budget:read + budget:write
#     client scopes and the budget-planner realm role.
#   - synthetic persona budget-smoke-planner (never a human login account):
#     budget-planner realm role; company-scope grant is seeded separately in
#     the permission plane (scripts/d35-3/rest-grant-runner.sh).
#   - budget:approve / budget-approver are deliberately absent: the lane can
#     never approve what it submitted (two-person rule stays meaningful).
#
# Secrets: the KC-generated client secret and the generated persona password
# are written to TEST Vault kv/platform/smoke-budget via stdin (never argv of
# the host shell, never printed). Rotate by re-running --apply.
#
# Usage on aiserver:
#   bash scripts/keycloak/setup-smoke-budget-client.sh --check
#   bash scripts/keycloak/setup-smoke-budget-client.sh --apply
#   bash scripts/keycloak/setup-smoke-budget-client.sh --rollback
set -euo pipefail
set +x
umask 077

MODE="${1:---check}"
KC_CONTAINER="platform-kc-test"
VAULT_CONTAINER="platform-vault-test"
PG_CONTAINER="platform-pg-test"
REALM="platform-test"
CLIENT_ID="smoke-budget-v1"
PERSONA="budget-smoke-planner"
ROLE_NAME="budget-planner"
FORBIDDEN_ROLE="budget-approver"
SCOPES=("budget:read" "budget:write")
# A2b.1 shared token-contract scopes: smoke-runtime-v1 carries the aud×6 +
# userId mappers (without it the token has aud=null and every resource server
# 401s), smoke-notify-v1 projects the optional org_id claim BudgetActorResolver
# reads as tenant. Measured live 2026-08-15 (#3466).
CONTRACT_SCOPES=("smoke-runtime-v1" "smoke-notify-v1")
FORBIDDEN_SCOPE="budget:approve"
VAULT_PATH="kv/platform/smoke-budget"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"

case "$MODE" in
  --check | --apply | --rollback) ;;
  *) echo "FATAL: mode must be --check, --apply or --rollback" >&2; exit 1 ;;
esac

for command in docker jq python3 openssl; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "FATAL: missing command: $command" >&2; exit 1; }
done
docker inspect "$KC_CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -qx true || {
  echo "FATAL: TEST Keycloak container is not running" >&2; exit 1; }

KCADM_CONFIG=$(docker exec "$KC_CONTAINER" mktemp /tmp/kcadm-smoke-budget.XXXXXX)
docker exec "$KC_CONTAINER" chmod 600 "$KCADM_CONFIG"
trap 'docker exec "$KC_CONTAINER" rm -f "$KCADM_CONFIG" >/dev/null 2>&1 || true' EXIT

K() { docker exec "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh "$@" --config "$KCADM_CONFIG"; }
KI() { docker exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh "$@" --config "$KCADM_CONFIG"; }

docker exec -e KC_CONFIG="$KCADM_CONFIG" "$KC_CONTAINER" sh -c '
  set -eu
  [ -r "${KEYCLOAK_ADMIN_PASSWORD_FILE:?}" ]
  KC_CLI_PASSWORD=$(cat "$KEYCLOAK_ADMIN_PASSWORD_FILE")
  export KC_CLI_PASSWORD
  /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8080 --realm master --user admin \
    --config "$KC_CONFIG" >/dev/null 2>&1
' || { echo "FATAL: isolated TEST Keycloak admin login failed" >&2; exit 1; }

client_uuid() {
  K get clients -r "$REALM" -q "clientId=$CLIENT_ID" --fields id,clientId 2>/dev/null |
    jq -er --arg c "$CLIENT_ID" 'map(select(.clientId == $c)) | select(length == 1) | .[0].id' 2>/dev/null || true
}
persona_uuid() {
  K get users -r "$REALM" -q "username=$PERSONA" -q exact=true --fields id 2>/dev/null |
    jq -er 'select(length == 1) | .[0].id' 2>/dev/null || true
}
scope_uuid() {
  K get client-scopes -r "$REALM" --fields id,name 2>/dev/null |
    jq -er --arg n "$1" 'map(select(.name == $n)) | select(length == 1) | .[0].id' 2>/dev/null || true
}

check_state() {
  local ok=0
  local cid; cid=$(client_uuid)
  if [ -z "$cid" ]; then echo "CHECK client: ABSENT"; return 1; fi
  local shape; shape=$(K get "clients/$cid" -r "$REALM" \
    --fields publicClient,directAccessGrantsEnabled,standardFlowEnabled,serviceAccountsEnabled,fullScopeAllowed)
  echo "$shape" | jq -e '
      .publicClient == false and .directAccessGrantsEnabled == true and
      .standardFlowEnabled == false and .serviceAccountsEnabled == false and
      .fullScopeAllowed == false' >/dev/null ||
    { echo "CHECK client shape: WRONG ($shape)"; ok=1; }
  local defaults; defaults=$(K get "clients/$cid/default-client-scopes" -r "$REALM" --fields name |
    jq -r '.[].name' | sort | tr '\n' ' ')
  for s in "${SCOPES[@]}"; do
    echo "$defaults" | grep -q "$s" || { echo "CHECK default scope $s: ABSENT"; ok=1; }
  done
  echo "$defaults" | grep -q "$FORBIDDEN_SCOPE" && { echo "CHECK forbidden scope present: $FORBIDDEN_SCOPE"; ok=1; }
  local realm_mappings; realm_mappings=$(K get "clients/$cid/scope-mappings/realm" -r "$REALM" --fields name |
    jq -r '.[].name' | sort | tr '\n' ' ')
  echo "$realm_mappings" | grep -q "$ROLE_NAME" || { echo "CHECK realm-role scope $ROLE_NAME: ABSENT"; ok=1; }
  echo "$realm_mappings" | grep -q "$FORBIDDEN_ROLE" && { echo "CHECK forbidden role in scope: $FORBIDDEN_ROLE"; ok=1; }
  local uid; uid=$(persona_uuid)
  if [ -z "$uid" ]; then echo "CHECK persona: ABSENT"; ok=1; else
    local roles; roles=$(K get "users/$uid/role-mappings/realm" -r "$REALM" --fields name |
      jq -r '.[].name' | sort | tr '\n' ' ')
    echo "$roles" | grep -q "$ROLE_NAME" || { echo "CHECK persona role $ROLE_NAME: ABSENT"; ok=1; }
    echo "$roles" | grep -q "$FORBIDDEN_ROLE" && { echo "CHECK persona forbidden role: $FORBIDDEN_ROLE"; ok=1; }
    local linked; linked=$(docker exec "$PG_CONTAINER" psql -U postgres -d users_db -At -c \
      "SELECT id FROM public.users WHERE kc_subject='$uid'" 2>/dev/null || true)
    if [ -z "$linked" ]; then
      echo "CHECK identity link (users_db kc_subject): ABSENT"; ok=1
    else
      # KC26: a --fields projection HIDES user-profile-managed attributes and
      # unmanagedAttributePolicy=None discards unmanaged ones — only the full
      # user representation shows the declared attributes truthfully.
      local attr_uid; attr_uid=$(K get "users/$uid" -r "$REALM" 2>/dev/null |
        jq -r '.attributes.userId[0] // empty')
      [ "$attr_uid" = "$linked" ] ||
        { echo "CHECK KC userId attribute ($attr_uid) != users_db id ($linked)"; ok=1; }
    fi
  fi
  [ "$ok" -eq 0 ] && echo "CHECK: OK (client shape + scopes + role + persona)"
  return "$ok"
}

apply_state() {
  local cid; cid=$(client_uuid)
  if [ -z "$cid" ]; then
    K create clients -r "$REALM" \
      -s "clientId=$CLIENT_ID" -s enabled=true -s publicClient=false \
      -s directAccessGrantsEnabled=true -s standardFlowEnabled=false \
      -s implicitFlowEnabled=false -s serviceAccountsEnabled=false \
      -s fullScopeAllowed=false \
      -s "description=Unattended budget smoke ROPC lane (gitops #3466). fullScopeAllowed=false + explicit budget:read/write default scopes + budget-planner realm-role scope mapping. budget:approve deliberately absent." \
      >/dev/null
    cid=$(client_uuid)
  fi
  [ -n "$cid" ] || { echo "FATAL: client create/lookup failed" >&2; exit 1; }

  for s in "${SCOPES[@]}" "${CONTRACT_SCOPES[@]}"; do
    local sid; sid=$(scope_uuid "$s")
    [ -n "$sid" ] || { echo "FATAL: client scope $s not found in realm" >&2; exit 1; }
    K update "clients/$cid/default-client-scopes/$sid" -r "$REALM" >/dev/null 2>&1 || true
  done

  local role_json; role_json=$(K get "roles/$ROLE_NAME" -r "$REALM" --fields id,name)
  printf '[%s]' "$role_json" | KI create "clients/$cid/scope-mappings/realm" -r "$REALM" -f - >/dev/null 2>&1 || true

  local uid; uid=$(persona_uuid)
  if [ -z "$uid" ]; then
    K create users -r "$REALM" -s "username=$PERSONA" -s enabled=true >/dev/null
    uid=$(persona_uuid)
  fi
  [ -n "$uid" ] || { echo "FATAL: persona create/lookup failed" >&2; exit 1; }
  # Identity link (measured live 2026-08-15, #3466): permission-service
  # /authz/me returns EMPTY scopes for a principal without a numeric users_db
  # identity (resolveScopeSummarySafely bails on numericUserId==null), so the
  # persona needs a users_db row bound via kc_subject. Defaults are copied
  # from an existing row; the synthetic password hash is never used for login
  # (authentication is Keycloak-only).
  local numeric_uid
  docker exec "$PG_CONTAINER" psql -U postgres -d users_db -v ON_ERROR_STOP=1 -c "
    INSERT INTO public.users (name,email,enabled,role,version,date_format,locale,time_format,timezone,password,kc_subject,kc_username)
    SELECT 'Budget Smoke Planner','$PERSONA@synthetic.test',true,'USER',0,date_format,locale,time_format,timezone,password,'$uid','$PERSONA'
      FROM public.users WHERE password IS NOT NULL ORDER BY id LIMIT 1
    ON CONFLICT (email) DO UPDATE SET kc_subject=EXCLUDED.kc_subject, kc_username=EXCLUDED.kc_username" >/dev/null
  numeric_uid=$(docker exec "$PG_CONTAINER" psql -U postgres -d users_db -At -c \
    "SELECT id FROM public.users WHERE lower(email)='$PERSONA@synthetic.test'")
  [ -n "$numeric_uid" ] || { echo "FATAL: users_db identity link failed" >&2; exit 1; }

  # KC26 user-profile: ROPC fails with "Account is not fully set up" unless
  # the managed profile fields are present and no required action is pending.
  # org_id feeds the smoke-notify-v1 org claim (BudgetActorResolver tenant
  # source); userId/subscriberId carry the numeric identity into tokens (the
  # smoke-runtime-v1 mapper). The whole attributes map is replaced in one
  # write (KC26 user-profile discards unmanaged partial updates).
  K update "users/$uid" -r "$REALM" \
    -s "email=$PERSONA@synthetic.test" -s emailVerified=true \
    -s firstName=Budget -s lastName=SmokePlanner -s 'requiredActions=[]' \
    -s "attributes={\"org_id\":[\"1\"],\"userId\":[\"$numeric_uid\"],\"subscriberId\":[\"$numeric_uid\"]}" >/dev/null
  K add-roles -r "$REALM" --uusername "$PERSONA" --rolename "$ROLE_NAME" >/dev/null

  # Rotate persona password + capture client secret; both go to Vault via
  # stdin JSON — never host argv, never printed. Password stays alphanumeric
  # (Spring env interpolation trap).
  local persona_password; persona_password=$(openssl rand -hex 24)
  K set-password -r "$REALM" --userid "$uid" --new-password "$persona_password" >/dev/null
  local client_secret; client_secret=$(K get "clients/$cid/client-secret" -r "$REALM" | jq -er .value)
  [ -n "$client_secret" ] && [ "$client_secret" != "null" ] ||
    { echo "FATAL: client secret unavailable" >&2; exit 1; }

  [ -r "$VAULT_INIT_FILE" ] || { echo "FATAL: vault init file unreadable" >&2; exit 1; }
  local vault_token; vault_token=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE")
  jq -n --arg cs "$client_secret" --arg pw "$persona_password" \
      '{client_id: "'"$CLIENT_ID"'", client_secret: $cs, persona_username: "'"$PERSONA"'", persona_password: $pw}' |
    docker exec -i -e VAULT_TOKEN="$vault_token" -e VAULT_ADDR=http://127.0.0.1:8200 \
      "$VAULT_CONTAINER" vault kv put "$VAULT_PATH" - >/dev/null
  echo "APPLY: client + scopes + realm-role mapping + persona reconciled; secrets sealed to $VAULT_PATH"
}

rollback_state() {
  local uid; uid=$(persona_uuid)
  [ -n "$uid" ] && K delete "users/$uid" -r "$REALM" >/dev/null 2>&1 || true
  local cid; cid=$(client_uuid)
  [ -n "$cid" ] && K delete "clients/$cid" -r "$REALM" >/dev/null 2>&1 || true
  echo "ROLLBACK: persona and client removed (Vault entry and the users_db identity row are left for audit; the row authenticates nothing once the KC persona is gone)"
}

case "$MODE" in
  --check) check_state ;;
  --apply) apply_state; check_state ;;
  --rollback) rollback_state ;;
esac
