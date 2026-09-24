#!/usr/bin/env bash
# setup-meeting-normal-persona.sh — gitops#3834. Idempotent synthetic NORMAL meeting user (TEST).
#
# Faz 24 journeys must be proven with a person who is NOT a user-management admin. The existing
# personas do not fit: d35-admin-persona is an org super-admin; faz24-smoke carries a legacy
# userId attribute (990001) that differs from its directory id and no permission-service role,
# so the web shell refuses it the Meetings module. This persona is configured the way a regular
# meeting user is:
#
#   Keycloak (platform-test): enabled, e-mail verified, first/last name (user profile), org_id and
#     tenantId = the meeting org, realm role MEETING_ADMIN, userId attribute = its directory id.
#     MEETING_ADMIN is what meeting users hold today to pass meeting-service's /api/v1/admin/**
#     role gate (ROLE_ADMIN | ROLE_MEETING_ADMIN | SCOPE_meeting); without it a user is refused
#     before any OpenFGA check (Faz 24 recorder e2e, 2026-06-25). It grants no user management.
#   users_db: auto-provisioned on first call, then ACTIVATED by the org-admin persona through the
#     product endpoint (PUT /api/v1/users/{id}/activation) — audited, never by SQL.
#   permission-service: MEETING_INTELLIGENCE_PILOT (MEETING manage + TRANSCRIPT view, nothing
#     else) through POST /api/v1/roles/{id}/members — the product path that also syncs OpenFGA.
#   Vault kv/platform/meeting-normal-persona: persona_username, persona_password,
#     keycloak_user_id, platform_user_id.
#
# Secrets never ride a process argv: the KC admin password is read inside the container into
# KC_CLI_PASSWORD, the new password travels as stdin JSON, the Vault token and password as stdin.
# Nothing secret is printed. Re-runs converge; the password is only (re)set on create or ROTATE=1.
#
# Usage (TEST host): bash scripts/keycloak/setup-meeting-normal-persona.sh
#   ROTATE=1      set a fresh password (KC + Vault together)
#   VERIFY_ONLY=1 read-back assertions only
set -euo pipefail

REALM="${REALM:-platform-test}"
BASE_URL="${BASE_URL:-https://testai.acik.com}"
KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_JSON="${VAULT_INIT_JSON:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
VAULT_PATH="${VAULT_PATH:-kv/platform/meeting-normal-persona}"
PERSONA_USERNAME="${PERSONA_USERNAME:-meeting-normal-persona}"
PERSONA_EMAIL="${PERSONA_EMAIL:-meeting-normal-persona@testai.acik.com}"
ORG_ID="${ORG_ID:-68c73eb9-c410-37dc-aff7-5ade8fbbcbb7}"
PILOT_ROLE_NAME="${PILOT_ROLE_NAME:-MEETING_INTELLIGENCE_PILOT}"
ADMIN_PERSONA_VAULT_PATH="${ADMIN_PERSONA_VAULT_PATH:-kv/platform/d35-3}"
ROTATE="${ROTATE:-0}"
VERIFY_ONLY="${VERIFY_ONLY:-0}"

case "$PERSONA_USERNAME" in
  halildeu|admin) echo "ERROR: refusing to touch an operator login" >&2; exit 1 ;;
esac

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
chmod 700 "$T"

vault_token_line() {
  python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_JSON"
}

vault_get() { # $1 path, $2 field -> stdout (empty if absent)
  vault_token_line | docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
    IFS= read -r VAULT_TOKEN; export VAULT_TOKEN
    vault kv get -field="$2" "$1" 2>/dev/null || true' sh "$1" "$2"
}

kc() { # kcadm inside the KC container; admin password never on argv
  docker exec -i "$KC_CONTAINER" sh -c '
    HOME="$(mktemp -d)"; export HOME
    KC_CLI_PASSWORD="$(cat "$KEYCLOAK_ADMIN_PASSWORD_FILE")"; export KC_CLI_PASSWORD
    K=/opt/keycloak/bin/kcadm.sh
    "$K" config credentials --config "$HOME/k.cfg" --server http://localhost:8080 --realm master --user admin </dev/null >/dev/null 2>&1 \
      || { echo "ERROR: KC admin login failed" >&2; rm -rf "$HOME"; exit 9; }
    "$K" "$@" --config "$HOME/k.cfg"; rc=$?
    rm -rf "$HOME"; exit $rc' sh "$@"
}

ropc_token() { # $1 username, $2 password file -> access token on stdout
  printf '%s' "$1" > "$T/ropc-user"
  curl -sS --fail-with-body "$BASE_URL/realms/$REALM/protocol/openid-connect/token" \
    --data-urlencode grant_type=password --data-urlencode client_id=smoke-client \
    --data-urlencode "client_secret@$T/smoke-client.secret" \
    --data-urlencode "username@$T/ropc-user" --data-urlencode "password@$2" \
    --data-urlencode "scope=openid smoke-notify-v1" \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])'
}

api() { # $1 token file, $2 method, $3 path, [$4 json] -> body in $T/body, code on stdout
  printf 'Authorization: Bearer %s' "$(cat "$1")" > "$T/h"
  if [ -n "${4:-}" ]; then
    curl -sS -o "$T/body" -w '%{http_code}' -X "$2" -H @"$T/h" -H 'Content-Type: application/json' --data "$4" "$BASE_URL$3"
  else
    curl -sS -o "$T/body" -w '%{http_code}' -X "$2" -H @"$T/h" "$BASE_URL$3"
  fi
}

jfield() { python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d.get(sys.argv[2],"") if isinstance(d,dict) else "")' "$T/body" "$1"; }

vault_get "kv/platform/keycloak/smoke-client" client_secret > "$T/smoke-client.secret"
[ -s "$T/smoke-client.secret" ] || { echo "ERROR: smoke-client secret unreadable" >&2; exit 1; }

echo "=== 1/6 Keycloak user"
KC_ID="$(kc get users -r "$REALM" -q "username=$PERSONA_USERNAME" -q exact=true --fields id \
  | python3 -c 'import json,sys;u=json.load(sys.stdin);print(u[0]["id"] if u else "")')"
NEW_USER=0
if [ -z "$KC_ID" ]; then
  [ "$VERIFY_ONLY" = 1 ] && { echo "VERIFY_FAILED: persona missing"; exit 3; }
  kc create users -r "$REALM" -s "username=$PERSONA_USERNAME" -s "email=$PERSONA_EMAIL" \
    -s firstName=Toplantı -s "lastName=Normal Persona" -s enabled=true -s emailVerified=true \
    -s "attributes.org_id=[\"$ORG_ID\"]" -s "attributes.tenantId=[\"$ORG_ID\"]" >/dev/null
  KC_ID="$(kc get users -r "$REALM" -q "username=$PERSONA_USERNAME" -q exact=true --fields id \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')"
  NEW_USER=1
  echo "  created ${KC_ID:0:8}"
else
  echo "  exists ${KC_ID:0:8}"
fi
[ "$VERIFY_ONLY" = 1 ] || kc add-roles -r "$REALM" --uid "$KC_ID" --rolename MEETING_ADMIN >/dev/null

echo "=== 2/6 password"
if [ "$VERIFY_ONLY" != 1 ] && { [ "$NEW_USER" = 1 ] || [ "$ROTATE" = 1 ] || [ -z "$(vault_get "$VAULT_PATH" persona_password)" ]; }; then
  openssl rand -base64 36 | tr -dc 'A-Za-z0-9' | head -c 32 > "$T/pw"
  [ "$(wc -c < "$T/pw")" -ge 24 ] || { echo "ERROR: password generation failed" >&2; exit 1; }
  # stdin JSON — the value never becomes an argument of any process.
  python3 -c 'import json,sys;print(json.dumps({"type":"password","temporary":False,"value":open(sys.argv[1]).read()}))' "$T/pw" \
    | kc update "users/$KC_ID/reset-password" -r "$REALM" -f - >/dev/null
  # put (not patch): creates the path on first run; step 6 patches the identity fields back.
  { vault_token_line; cat "$T/pw"; } | docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
    IFS= read -r VAULT_TOKEN; export VAULT_TOKEN
    exec vault kv put "$1" persona_password=- >/dev/null' sh "$VAULT_PATH"
  echo "  set (Keycloak + Vault)"
else
  vault_get "$VAULT_PATH" persona_password > "$T/pw"
  echo "  kept (Vault)"
fi
[ -s "$T/pw" ] || { echo "ERROR: persona password unavailable" >&2; exit 1; }

echo "=== 3/6 directory row"
ropc_token "$PERSONA_USERNAME" "$T/pw" > "$T/persona.tok"
PROFILE_CODE="$(api "$T/persona.tok" GET /api/v1/users/me/profile)"   # auto-provisions on first call
vault_get "$ADMIN_PERSONA_VAULT_PATH" admin_persona_password > "$T/admin.pw"
ADMIN_USER="$(vault_get "$ADMIN_PERSONA_VAULT_PATH" admin_persona_username)"
ropc_token "$ADMIN_USER" "$T/admin.pw" > "$T/admin.tok"
CODE="$(api "$T/admin.tok" GET "/api/v1/users/by-email?email=$PERSONA_EMAIL")"
[ "$CODE" = 200 ] || { echo "ERROR: directory lookup HTTP $CODE (profile call HTTP $PROFILE_CODE)" >&2; exit 1; }
PLATFORM_ID="$(jfield id)"
ENABLED="$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(str(d.get("enabled", d.get("active",""))).lower())' "$T/body")"
echo "  id=$PLATFORM_ID enabled=$ENABLED (profile call HTTP $PROFILE_CODE)"
if [ "$ENABLED" != true ] && [ "$VERIFY_ONLY" != 1 ]; then
  CODE="$(api "$T/admin.tok" PUT "/api/v1/users/$PLATFORM_ID/activation" '{"active":true}')"
  [ "$CODE" = 200 ] || { echo "ERROR: activation HTTP $CODE" >&2; exit 1; }
  echo "  activated by the org-admin persona (audit $(jfield auditId))"
fi

echo "=== 4/6 Keycloak userId = directory id"
[ "$VERIFY_ONLY" = 1 ] || kc update "users/$KC_ID" -r "$REALM" -s "attributes.userId=[\"$PLATFORM_ID\"]" \
  -s "attributes.org_id=[\"$ORG_ID\"]" -s "attributes.tenantId=[\"$ORG_ID\"]" >/dev/null

echo "=== 5/6 permission-service role"
CODE="$(api "$T/admin.tok" GET /api/v1/roles)"
[ "$CODE" = 200 ] || { echo "ERROR: role list HTTP $CODE" >&2; exit 1; }
ROLE_ID="$(python3 -c 'import json,sys
d=json.load(open(sys.argv[1])); rows=d if isinstance(d,list) else (d.get("items") or d.get("content") or [])
print(next((str(r["id"]) for r in rows if r.get("name")==sys.argv[2]), ""))' "$T/body" "$PILOT_ROLE_NAME")"
[ -n "$ROLE_ID" ] || { echo "ERROR: role $PILOT_ROLE_NAME not found" >&2; exit 1; }
if [ "$VERIFY_ONLY" != 1 ]; then
  CODE="$(api "$T/admin.tok" POST "/api/v1/roles/$ROLE_ID/members" "{\"userIds\":[$PLATFORM_ID]}")"
  [ "$CODE" = 200 ] || { echo "ERROR: role membership HTTP $CODE" >&2; exit 1; }
fi
echo "  $PILOT_ROLE_NAME (id $ROLE_ID) -> user $PLATFORM_ID"

echo "=== 6/6 verify as the persona (fresh token)"
{ vault_token_line; printf '%s' "$PLATFORM_ID"; } | docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
  IFS= read -r VAULT_TOKEN; export VAULT_TOKEN
  exec vault kv patch "$1" persona_username="$2" keycloak_user_id="$3" platform_user_id=- >/dev/null' sh "$VAULT_PATH" "$PERSONA_USERNAME" "$KC_ID"
ropc_token "$PERSONA_USERNAME" "$T/pw" > "$T/persona.tok"
FAIL=0
CLAIM_UID="$(python3 -c 'import sys,json,base64;p=open(sys.argv[1]).read().strip().split(".")[1];p+="="*(-len(p)%4);print(json.loads(base64.urlsafe_b64decode(p)).get("userId",""))' "$T/persona.tok")"
[ "$CLAIM_UID" = "$PLATFORM_ID" ] || { echo "  ✗ token userId=$CLAIM_UID != directory id $PLATFORM_ID"; FAIL=1; }
CODE="$(api "$T/persona.tok" GET /api/v1/authz/me)"
python3 - "$T/body" <<'PY' || FAIL=1
import json,sys
d=json.load(open(sys.argv[1])); perms=set(d.get("permissions") or []); mods=d.get("modules") or {}
ok = (not d.get("superAdmin")) and mods.get("MEETING")=="MANAGE" and not (perms & {"VIEW_USERS","MANAGE_USERS","USER_READ","USER_UPDATE"})
print(f"  authz/me superAdmin={d.get('superAdmin')} MEETING={mods.get('MEETING')} user-perms={sorted(perms & {'VIEW_USERS','MANAGE_USERS'})} -> {'ok' if ok else 'NOT a normal meeting user'}")
sys.exit(0 if ok else 1)
PY
CODE="$(api "$T/persona.tok" GET '/api/v1/users?search=zz&pageSize=1')"; echo "  admin user grid -> $CODE (expect 403)"; [ "$CODE" = 403 ] || FAIL=1
CODE="$(api "$T/persona.tok" GET '/api/v1/admin/meetings?page=0&size=1')"; echo "  meetings list -> $CODE (expect 200)"; [ "$CODE" = 200 ] || FAIL=1
if [ "$FAIL" != 0 ]; then
  echo "=== VERIFY_FAILED"
  exit 3
fi
echo "=== PASS: $PERSONA_USERNAME is a normal meeting user (directory id $PLATFORM_ID)"
