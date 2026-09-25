#!/usr/bin/env bash
# setup-ats-tenant-b-recruiter.sh — ats#226 item 4. Idempotent AUTHORIZED recruiter in a second
# ATS tenant (TEST only), so tenant isolation is proven by the tenant boundary, not by a 403.
#
# The ATS API gates every recruiter route on the platform ATS module (permission-service role
# membership of the person's user-service record) in addition to the JWT `tenant` claim.
# Measured 2026-09-25: `ats-recruiter-persona` (tenant 000...001) has users_db id 9 and the
# "Full ATS Recruiter" membership; `ats-operator-persona` (tenant `t-platform-test`, the
# cross-tenant persona of fullats-application-smoke.sh) had no users_db record and no membership,
# so every recruiter call answered 403 "ATS yetkisi yok". A cross-tenant check with it proved
# missing permission, not isolation. This script gives that persona the same shape as the
# recruiter persona and leaves its tenant unchanged:
#
#   users_db: auto-provisioned on the persona's first user-service call, then ACTIVATED by the
#     org-admin persona through the product endpoint (PUT /api/v1/users/{id}/activation).
#   Keycloak: `ats_tenant` must already equal ATS_TENANT; the script never moves a persona
#     between tenants and writes nothing to Keycloak.
#   permission-service: "Full ATS Recruiter" membership through POST /api/v1/roles/{id}/members
#     (the product path that also syncs OpenFGA), after the same granule boundary as
#     provision-ats-recruiter-access.sh: the ATS module present, nothing unreviewed, nothing
#     destructive. (That script also requires a platform `tenantId` attribute, which neither ATS
#     smoke persona carries.)
#
# Secrets never ride a process argv: the KC admin password is read inside the container, the
# Vault token and passwords travel on stdin or 0600 files. Nothing secret or personal is printed.
#
# Usage (TEST host): bash scripts/ats/setup-ats-tenant-b-recruiter.sh [--apply]
#   default is a read-only check; --apply performs the missing steps.
set -Eeuo pipefail
umask 077

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

REALM="${REALM:-platform-test}"
BASE_URL="${BASE_URL:-https://testai.acik.com}"
KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_JSON="${VAULT_INIT_JSON:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
PERSONA_USERNAME="${PERSONA_USERNAME:-ats-operator-persona}"
ATS_TENANT="${ATS_TENANT:-t-platform-test}"
ATS_PUBLIC_TENANT="00000000-0000-0000-0000-000000000001"
ADMIN_PERSONA_VAULT_PATH="kv/platform/d35-3"
ROLE_NAME="Full ATS Recruiter"
ALLOWED_GRANULES='["ATS","INTERVIEW_EVIDENCE","ATS_APPLICATION_MANAGE","ATS_JOB_MANAGE"]'
FORBIDDEN_GRANULES='["ATS_RETENTION_EXECUTE","ERASURE_EXECUTE","DSAR_WRITE","EXPORT_REPAIR"]'

case "$PERSONA_USERNAME" in
  halildeu|admin) echo "ERROR: refusing to touch an operator login" >&2; exit 1 ;;
esac
[ "$ATS_TENANT" != "$ATS_PUBLIC_TENANT" ] || { echo "ERROR: tenant B must differ from the public tenant" >&2; exit 1; }

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
chmod 700 "$T"

vault_get() { # $1 path, $2 field -> stdout
  python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_JSON" |
    docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
      IFS= read -r VAULT_TOKEN; export VAULT_TOKEN
      vault kv get -field="$2" "$1"' sh "$1" "$2"
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

ropc() { # $1 client_id, $2 client secret file, $3 username, $4 password file -> token on stdout
  printf '%s' "$3" > "$T/ropc-user"
  curl -sS --fail-with-body "$BASE_URL/realms/$REALM/protocol/openid-connect/token" \
    --data-urlencode grant_type=password --data-urlencode "client_id=$1" \
    --data-urlencode "client_secret@$2" --data-urlencode "username@$T/ropc-user" \
    --data-urlencode "password@$4" \
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

claim() { # $1 token file, $2 claim -> value
  python3 -c 'import sys,json,base64;p=open(sys.argv[1]).read().strip().split(".")[1];p+="="*(-len(p)%4);v=json.loads(base64.urlsafe_b64decode(p)).get(sys.argv[2],"");print(v if isinstance(v,str) else json.dumps(v))' "$1" "$2"
}

echo "=== 1/5 Keycloak persona and tenant"
# Full representation: `--fields` would strip the nested attribute map.
kc get users -r "$REALM" -q "username=$PERSONA_USERNAME" -q exact=true -q briefRepresentation=false > "$T/kc-user.json"
python3 - "$T/kc-user.json" "$T/persona.email" "$ATS_TENANT" <<'PY'
import json, sys
users = json.load(open(sys.argv[1]))
if len(users) != 1:
    sys.exit("ERROR: persona not found (exactly one expected)")
user = users[0]
email = (user.get("email") or "").strip().lower()
if not email or not user.get("enabled"):
    sys.exit("ERROR: persona has no e-mail or is disabled")
tenant = ((user.get("attributes") or {}).get("ats_tenant") or [""])[0]
if tenant != sys.argv[3]:
    sys.exit("ERROR: persona ats_tenant is not the expected tenant; refusing to move it")
open(sys.argv[2], "w").write(email)
PY
echo "  ✓ persona exists, enabled, ats_tenant = $ATS_TENANT"

vault_get kv/platform/ats-smoke OPERATOR_PW > "$T/persona.pw"
vault_get kv/platform/keycloak/smoke-ats client_secret > "$T/smoke-ats.secret"
vault_get kv/platform/keycloak/smoke-client client_secret > "$T/smoke-client.secret"
vault_get "$ADMIN_PERSONA_VAULT_PATH" admin_persona_password > "$T/admin.pw"
ADMIN_USER="$(vault_get "$ADMIN_PERSONA_VAULT_PATH" admin_persona_username)"
ropc smoke-ats-v1 "$T/smoke-ats.secret" "$PERSONA_USERNAME" "$T/persona.pw" > "$T/persona.tok"
ropc smoke-client "$T/smoke-client.secret" "$ADMIN_USER" "$T/admin.pw" > "$T/admin.tok"

echo "=== 2/5 users_db record (auto-provision on first call)"
python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(open(sys.argv[1]).read()))' "$T/persona.email" > "$T/email.q"
CODE="$(api "$T/admin.tok" GET "/api/v1/users/by-email?email=$(cat "$T/email.q")")"
if [ "$CODE" = 404 ]; then
  if [ "$APPLY" = 1 ]; then
    echo "  first user-service call -> HTTP $(api "$T/persona.tok" GET /api/v1/users/me/profile)"
    CODE="$(api "$T/admin.tok" GET "/api/v1/users/by-email?email=$(cat "$T/email.q")")"
  else
    echo "  ✗ no users_db record yet (run with --apply)"; exit 1
  fi
fi
[ "$CODE" = 200 ] || { echo "ERROR: directory lookup HTTP $CODE" >&2; exit 1; }
PLATFORM_ID="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["id"])' "$T/body")"
ENABLED="$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(str(d.get("enabled", d.get("active", False))).lower())' "$T/body")"
echo "  ✓ users_db record present"

echo "=== 3/5 activation through the product endpoint"
if [ "$ENABLED" = true ]; then
  echo "  ✓ already active"
elif [ "$APPLY" = 1 ]; then
  CODE="$(api "$T/admin.tok" PUT "/api/v1/users/$PLATFORM_ID/activation" '{"active":true}')"
  [ "$CODE" = 200 ] || { echo "ERROR: activation HTTP $CODE" >&2; exit 1; }
  echo "  ✓ activated"
else
  echo "  ✗ not active (run with --apply)"; exit 1
fi

echo "=== 4/5 $ROLE_NAME membership (granule boundary first)"
CODE="$(api "$T/admin.tok" GET /api/v1/roles)"
[ "$CODE" = 200 ] || { echo "ERROR: role list HTTP $CODE" >&2; exit 1; }
ROLE_ID="$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));it=d.get("items",d) if isinstance(d,dict) else d;m=[r["id"] for r in it if r.get("name")==sys.argv[2]];print(m[0] if len(m)==1 else "")' "$T/body" "$ROLE_NAME")"
[ -n "$ROLE_ID" ] || { echo "ERROR: role not found exactly once" >&2; exit 1; }
CODE="$(api "$T/admin.tok" GET "/api/v1/roles/$ROLE_ID/granules")"
[ "$CODE" = 200 ] || { echo "ERROR: granule preflight HTTP $CODE" >&2; exit 1; }
python3 - "$T/body" "$ALLOWED_GRANULES" "$FORBIDDEN_GRANULES" <<'PY'
import json, sys
body = json.load(open(sys.argv[1]))
granules = body.get("granules", body) if isinstance(body, dict) else body
keys = {g.get("key") for g in granules}
allowed, forbidden = set(json.loads(sys.argv[2])), set(json.loads(sys.argv[3]))
if not any(g.get("type") == "MODULE" and g.get("key") == "ATS" for g in granules):
    sys.exit("ERROR: role lacks the ATS module granule")
if keys - allowed:
    sys.exit("ERROR: role carries unreviewed granules")
if keys & forbidden:
    sys.exit("ERROR: role carries destructive granules")
PY
echo "  ✓ granule boundary holds"
CODE="$(api "$T/admin.tok" GET "/api/v1/roles/$ROLE_ID/members")"
[ "$CODE" = 200 ] || { echo "ERROR: membership preflight HTTP $CODE" >&2; exit 1; }
MEMBER="$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));it=d.get("items",d) if isinstance(d,dict) else d;print(any(str(m.get("userId",m.get("id")))==sys.argv[2] for m in it))' "$T/body" "$PLATFORM_ID")"
if [ "$MEMBER" = True ]; then
  echo "  ✓ already a member"
elif [ "$APPLY" = 1 ]; then
  CODE="$(api "$T/admin.tok" POST "/api/v1/roles/$ROLE_ID/members" "{\"userIds\":[$PLATFORM_ID]}")"
  [ "$CODE" = 200 ] || { echo "ERROR: membership HTTP $CODE" >&2; exit 1; }
  echo "  ✓ membership added"
else
  echo "  ✗ not a member (run with --apply)"; exit 1
fi

echo "=== 5/5 read-back with a fresh token"
ropc smoke-ats-v1 "$T/smoke-ats.secret" "$PERSONA_USERNAME" "$T/persona.pw" > "$T/persona.tok"
FAIL=0
if [ "$(claim "$T/persona.tok" tenant)" = "$ATS_TENANT" ]; then
  echo "  ✓ token tenant = $ATS_TENANT"
else
  echo "  ✗ token tenant"; FAIL=1
fi
CODE="$(api "$T/persona.tok" GET "/api/ats/v1/recruiter/applications?page=0&size=1")"
if [ "$CODE" = 200 ]; then
  echo "  ✓ recruiter inbox of its own tenant -> 200"
else
  echo "  ✗ recruiter inbox -> HTTP $CODE"; FAIL=1
fi
exit "$FAIL"
