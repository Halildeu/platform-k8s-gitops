#!/usr/bin/env bash
# Faz 35 ES-301b (platform-backend#1153): the SECOND-TIER escalation recipient for the TEST
# cell — the compliance/board persona that receives level-2+ escalation notifications.
#
# Organisation: the SYNTHETIC channel org (…0003), deliberately. The orchestrator inbox is
# org-scoped and the shell bell reads it with the user's own org_id claim, so a recipient
# only ever sees rows whose intent carried its org — and acceptance escalations are
# produced on synthetic (…0003) cases, never on the live channel (…0001). The recipient
# ids in ethics-service are cell-level (one per tier), not per org: the first tier
# (ethics-manager-test, …0001) therefore cannot see org-…0003 rows from the bell — a
# pre-existing limitation of the single-recipient design, tracked separately.
#
# What it is NOT: an Etik Speak manager. It holds no ethics-manager realm role, no
# ETIK_SPEAK_MANAGER membership, no product tuple; it can log into the platform shell (to
# see the bell) and nothing else. The Faz 35 least-privilege contract for managers is
# untouched.
#
# What it produces: the numeric users_db id of the persona (materialized by the first
# authenticated /authz/me call) — the subscriber id ethics-service must address and the
# shell bell reads (X-Subscriber-Id = /authz/me.subscriberId; measured 2026-09-11: the
# Keycloak subject UUID is NOT what the bell reads — 174 inbox rows under the UUID, 0 seen).
# It also reports the first tier's numeric id so both env values can be pinned together.
# Ids are not secrets and are printed; the password never is.
#
# Test-only. Idempotent: an existing user or credential is re-asserted, not recreated.
set -euo pipefail
set +x
KC_PUBLIC_BASE="${KC_PUBLIC_BASE:-https://testai.acik.com}"
KC_PUBLIC_HOST="${KC_PUBLIC_HOST:-testai.acik.com}"
KC_EDGE_ADDR="${KC_EDGE_ADDR:-127.0.0.1}"
KC_BASE_URL="${KC_BASE_URL:-http://127.0.0.1:8082}"
KC_REALM="${KC_REALM:-platform-test}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"
RECIPIENT_USERNAME=ethics-compliance-test
RECIPIENT_ORG_ID=00000000-0000-0000-0000-000000000003
RECIPIENT_PASSWORD_FILE=/srv/platform/secrets/faz35-test/ethics-compliance-test.password
FIRST_TIER_USERNAME=ethics-manager-test
LOCAL_PORT=18091
for binding in \
  "$KC_BASE_URL=http://127.0.0.1:8082" \
  "$KC_REALM=platform-test" \
  "$VAULT_CONTAINER=platform-vault-test" \
  "$KUBE_CONTEXT=k3d-test" \
  "$KUBE_NS=platform-test"; do
  [ "${binding%%=*}" = "${binding#*=}" ] || {
    echo "FATAL: test-only script; mutation target override refused: ${binding%%=*}" >&2
    exit 1
  }
done
for command_name in curl jq docker python3 kubectl sudo; do
  command -v "$command_name" >/dev/null 2>&1 || { echo "FATAL: required command missing: $command_name" >&2; exit 1; }
done

vault_root_token() {
  sudo python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE"
}
vault_field() {
  vault_root_token | docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c \
    'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; vault kv get -field="$2" "$1"' _ "$1" "$2"
}

# 1. Credential (root-only file; reused on rerun).
if ! sudo test -f "$RECIPIENT_PASSWORD_FILE"; then
  sudo mkdir -p "$(dirname "$RECIPIENT_PASSWORD_FILE")"
  drawn=""
  while [ "${#drawn}" -lt 40 ]; do
    drawn="$drawn$(LC_ALL=C head -c 256 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9')"
  done
  printf '%s' "${drawn:0:40}" | sudo tee "$RECIPIENT_PASSWORD_FILE" >/dev/null
  sudo chmod 600 "$RECIPIENT_PASSWORD_FILE"
  unset drawn
  echo "credential: generated"
else
  echo "credential: reusing the existing test-only password file"
fi

# 2. Keycloak identity — a plain platform user with the tenant claim; no ethics role.
admin_token=$(curl -sS -X POST "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" \
  -d grant_type=client_credentials \
  -d "client_id=$(vault_field kv/platform/keycloak-automation client_id)" \
  --data-urlencode "client_secret=$(vault_field kv/platform/keycloak-automation client_secret)" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')
[ -n "$admin_token" ] || { echo "FATAL: Keycloak admin token failed" >&2; exit 1; }
kc() { curl -sS -H "Authorization: Bearer $admin_token" "$@"; }
lookup() { kc "$KC_BASE_URL/admin/realms/$KC_REALM/users?username=$RECIPIENT_USERNAME&exact=true" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[0]["id"] if d else "")'; }
user_id=$(lookup)
if [ -z "$user_id" ]; then
  python3 -c '
import json, sys
print(json.dumps({
    "username": sys.argv[1], "enabled": True, "emailVerified": True,
    "email": sys.argv[1] + "@synthetic.invalid",
    "firstName": "Etik Speak", "lastName": "Compliance Recipient",
    "attributes": {"org_id": [sys.argv[2]]},
}))' "$RECIPIENT_USERNAME" "$RECIPIENT_ORG_ID" \
  | kc -o /dev/null -X POST -H 'Content-Type: application/json' --data-binary @- \
      "$KC_BASE_URL/admin/realms/$KC_REALM/users"
  user_id=$(lookup)
  [ -n "$user_id" ] || { echo "FATAL: recipient user was not created" >&2; exit 1; }
  echo "keycloak: user created"
else
  echo "keycloak: user present"
fi
current=$(kc "$KC_BASE_URL/admin/realms/$KC_REALM/users/$user_id")
printf '%s' "$current" | python3 -c '
import json, sys
u = json.load(sys.stdin)
attrs = u.get("attributes") or {}
attrs["org_id"] = [sys.argv[1]]
u["attributes"] = attrs
u["enabled"] = True
print(json.dumps(u))' "$RECIPIENT_ORG_ID" \
  | kc -o /dev/null -X PUT -H 'Content-Type: application/json' --data-binary @- \
      "$KC_BASE_URL/admin/realms/$KC_REALM/users/$user_id"
sudo cat "$RECIPIENT_PASSWORD_FILE" | python3 -c '
import json, sys
print(json.dumps({"type": "password", "value": sys.stdin.read(), "temporary": False}))' \
  | kc -o /dev/null -X PUT -H 'Content-Type: application/json' --data-binary @- \
      "$KC_BASE_URL/admin/realms/$KC_REALM/users/$user_id/reset-password"
# Least privilege, read back: the recipient must NOT carry the manager role.
kc "$KC_BASE_URL/admin/realms/$KC_REALM/users/$user_id/role-mappings/realm" \
  | python3 -c 'import sys, json
roles = {r["name"] for r in json.load(sys.stdin)}
sys.exit(1 if "ethics-manager" in roles else 0)' || {
  echo "FATAL: the second-tier recipient carries the ethics-manager role; refusing" >&2; exit 1; }
echo "keycloak: org claim + credential asserted; no ethics-manager role (read back)"

# 3. Numeric subscriber ids — materialized by /authz/me, the id the bell and the intent use.
kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NS" port-forward svc/permission-service "$LOCAL_PORT:8090" >/dev/null 2>&1 &
forward_pid=$!
trap 'kill "$forward_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  curl -sS -o /dev/null "http://127.0.0.1:$LOCAL_PORT/actuator/health" 2>/dev/null && break
  sleep 1
done
BASE="http://127.0.0.1:$LOCAL_PORT"
mint() { # username; password on stdin; plain openid scope (no manager audience)
  local username=$1 password smoke_secret
  IFS= read -r password
  smoke_secret=$(vault_field kv/platform/keycloak/smoke-client client_secret)
  curl -sS -k --resolve "$KC_PUBLIC_HOST:443:$KC_EDGE_ADDR" \
    -X POST "$KC_PUBLIC_BASE/realms/$KC_REALM/protocol/openid-connect/token" \
    -d grant_type=password -d client_id=smoke-client \
    --data-urlencode "client_secret=$smoke_secret" \
    --data-urlencode "username=$username" --data-urlencode "password=$password" \
    --data-urlencode "scope=openid" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))'
  unset password smoke_secret
}
authz_me() { # token on stdin → "userId subscriberId permissions"
  local token; IFS= read -r token
  curl -sS -H "Authorization: Bearer $token" "$BASE/api/v1/authz/me" \
    | python3 -c 'import sys,json; p=json.load(sys.stdin); print(str(p.get("userId","")), str(p.get("subscriberId","")), json.dumps(p.get("permissions")))'
}
# The numeric id lives in users_db and is created by user-service, not by permission-service:
# the first profile read materializes the local row (pending activation), the Faz 35 writer
# persona activates it, and only then does /authz/me answer with the number. Same sequence
# lib-authz-projection.sh uses for the manager personas.
WRITER_VAULT_PATH=kv/platform/d35-3
profile_via_gateway() { # token on stdin → JSON of /api/v1/users/me/profile (through the public edge)
  local token; IFS= read -r token
  curl -sS -k --resolve "$KC_PUBLIC_HOST:443:$KC_EDGE_ADDR" -H "Authorization: Bearer $token" \
    "$KC_PUBLIC_BASE/api/v1/users/me/profile"
}
recipient_token=$(sudo cat "$RECIPIENT_PASSWORD_FILE" | mint "$RECIPIENT_USERNAME")
[ -n "$recipient_token" ] || { echo "FATAL: recipient login failed" >&2; exit 1; }
# First profile read creates the local row in pending state (403 ACCOUNT_DISABLED is the
# expected answer for a brand-new identity); the writer then resolves it by e-mail and
# activates it, after which the profile answers 200 and /authz/me carries the number.
printf '%s' "$recipient_token" | profile_via_gateway >/dev/null || true
writer_token=$(vault_field "$WRITER_VAULT_PATH" admin_persona_password | mint "$(vault_field "$WRITER_VAULT_PATH" admin_persona_username)")
[ -n "$writer_token" ] || { echo "FATAL: provisioner login failed" >&2; exit 1; }
local_id=$(curl -sS -k --resolve "$KC_PUBLIC_HOST:443:$KC_EDGE_ADDR" -H "Authorization: Bearer $writer_token" \
  --get --data-urlencode "email=$RECIPIENT_USERNAME@synthetic.invalid" "$KC_PUBLIC_BASE/api/v1/users/by-email" \
  | python3 -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: print(""); raise SystemExit
print(str(d.get("id","")) if isinstance(d, dict) else "")')
[[ "$local_id" =~ ^[0-9]+$ ]] || { echo "FATAL: user-service did not materialize the local user (by-email empty)" >&2; exit 1; }
profile=$(printf '%s' "$recipient_token" | profile_via_gateway)
if [ "$(printf '%s' "$profile" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("enabled"))
except Exception: print("")')" != "True" ]; then
  code=$(printf '{"active":true}' | curl -sS -o /dev/null -w '%{http_code}' -k --resolve "$KC_PUBLIC_HOST:443:$KC_EDGE_ADDR" \
    -X PUT -H "Authorization: Bearer $writer_token" -H 'Content-Type: application/json' --data-binary @- \
    "$KC_PUBLIC_BASE/api/v1/users/$local_id/activation")
  [ "$code" = 200 ] || { echo "FATAL: local user activation failed (HTTP $code)" >&2; exit 1; }
  profile=$(printf '%s' "$recipient_token" | profile_via_gateway)
  printf '%s' "$profile" | python3 -c 'import sys,json; p=json.load(sys.stdin); sys.exit(0 if p.get("enabled") is True and str(p.get("id"))==sys.argv[1] else 1)' "$local_id" \
    || { echo "FATAL: profile did not become active after activation" >&2; exit 1; }
  echo "user-service: local profile $local_id activated"
else
  echo "user-service: local profile $local_id already active"
fi
unset writer_token
recipient_authz=$(printf '%s' "$recipient_token" | authz_me || true)
unset recipient_token
[ -n "$recipient_authz" ] || { echo "FATAL: /authz/me answered nothing usable for the recipient" >&2; exit 1; }
read -r recipient_uid recipient_sid recipient_perms <<<"$recipient_authz"
[[ "$recipient_uid" =~ ^[0-9]+$ ]] && [ "$recipient_uid" = "$recipient_sid" ] || {
  echo "FATAL: recipient numeric id not materialized (userId=$recipient_uid subscriberId=$recipient_sid)" >&2; exit 1; }
[ "$recipient_perms" = "[]" ] || { echo "FATAL: the second-tier recipient holds permissions ($recipient_perms); it must hold none" >&2; exit 1; }
# The first tier is resolved the way the entitlement script does it — by e-mail through
# user-service with the writer — so this script never needs the manager's credential.
writer_token=$(vault_field "$WRITER_VAULT_PATH" admin_persona_password | mint "$(vault_field "$WRITER_VAULT_PATH" admin_persona_username)")
first_uid=$(curl -sS -k --resolve "$KC_PUBLIC_HOST:443:$KC_EDGE_ADDR" -H "Authorization: Bearer $writer_token" \
  --get --data-urlencode "email=$FIRST_TIER_USERNAME@test.invalid" "$KC_PUBLIC_BASE/api/v1/users/by-email" \
  | python3 -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: print(""); raise SystemExit
print(str(d.get("id","")) if isinstance(d, dict) else "")')
unset writer_token
[[ "$first_uid" =~ ^[0-9]+$ ]] || { echo "FATAL: first-tier numeric id not resolved" >&2; exit 1; }
[ "$first_uid" != "$recipient_uid" ] || { echo "FATAL: the two tiers resolve to one subscriber" >&2; exit 1; }
echo "authz: first tier ($FIRST_TIER_USERNAME) subscriberId=$first_uid"
echo "authz: second tier ($RECIPIENT_USERNAME) subscriberId=$recipient_uid, permissions=[] (least privilege read back)"
echo "ETHICS_NOTIFICATION_RECIPIENT_SUBSCRIBER_ID=$first_uid"
echo "ETHICS_NOTIFICATION_ESCALATION_RECIPIENT_SUBSCRIBER_ID=$recipient_uid"
