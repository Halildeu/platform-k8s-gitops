#!/usr/bin/env bash
# Faz 35 Etik Speak: staff identity for the SYNTHETIC reporter channel.
#
# The two public hosts deliberately resolve to different orgs so synthetic
# verification can never be written into the live evidentiary record:
#
#   etik.acik.com     -> 00000000-0000-0000-0000-000000000001  (live)
#   speakup.acik.com  -> 00000000-0000-0000-0000-000000000003  (synthetic)
#
# Every existing manager persona lives in org 0001 or 0002, so the synthetic
# channel had no staff counterpart at all: nothing a synthetic reporter files
# could ever be opened by an authorized manager, and the positive half of the
# ES-104G acceptance ("an authorized same-org manager downloads the sanitized
# derivative") was unmeasurable. This provisions that missing counterpart.
#
# Test-only. Idempotent: an existing user, credential or role membership is
# re-asserted, not recreated. Fail-closed: the entitlement is verified against
# the live authorization projection before the script reports success. Raw
# credentials never reach stdout, this host's process list, Git or an issue.
set -euo pipefail
# A caller may invoke bash -x; disable tracing before any credential is read.
set +x

KC_BASE_URL="${KC_BASE_URL:-http://127.0.0.1:8082}"
KC_REALM="${KC_REALM:-platform-test}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"

SYNTHETIC_USERNAME=ethics-manager-synthetic-test
SYNTHETIC_ORG_ID=00000000-0000-0000-0000-000000000003
SYNTHETIC_PASSWORD_FILE=/srv/platform/secrets/faz35-test/ethics-manager-synthetic-test.password
PERMISSION_ROLE_NAME=ETIK_SPEAK_MANAGER
WRITER_VAULT_PATH=kv/platform/d35-3
LOCAL_PORT=18090

for binding in \
  "$KC_BASE_URL=http://127.0.0.1:8082" \
  "$KC_REALM=platform-test" \
  "$VAULT_CONTAINER=platform-vault-test" \
  "$KUBE_CONTEXT=k3d-test" \
  "$KUBE_NS=platform-test"; do
  [ "${binding%%=*}" = "${binding#*=}" ] || {
    echo "FATAL: this script is test-only; override refused: ${binding%%=*}" >&2
    exit 1
  }
done

vault_root_token() {
  sudo python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' \
    "$VAULT_INIT_FILE"
}
vault_field() {
  vault_root_token | docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 \
    "$VAULT_CONTAINER" sh -c \
      'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; vault kv get -field="$2" "$1"' \
      _ "$1" "$2"
}

# ---------------------------------------------------------------------------
# 1. Credential. Generated once and kept root-only on this host; a rerun reuses
#    it so an already-provisioned cell is not invalidated.
# ---------------------------------------------------------------------------
if ! sudo test -f "$SYNTHETIC_PASSWORD_FILE"; then
  sudo mkdir -p "$(dirname "$SYNTHETIC_PASSWORD_FILE")"
  # `tr </dev/urandom | head -c` dies of SIGPIPE under pipefail; draw first.
  drawn=""
  while [ "${#drawn}" -lt 40 ]; do
    drawn="$drawn$(LC_ALL=C head -c 256 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9')"
  done
  printf '%s' "${drawn:0:40}" | sudo tee "$SYNTHETIC_PASSWORD_FILE" >/dev/null
  sudo chmod 600 "$SYNTHETIC_PASSWORD_FILE"
  unset drawn
  echo "credential: generated"
else
  echo "credential: reusing the existing test-only password file"
fi

# ---------------------------------------------------------------------------
# 2. Keycloak identity.
# ---------------------------------------------------------------------------
admin_token=$(curl -sS -X POST \
  "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" \
  -d grant_type=client_credentials \
  -d "client_id=$(vault_field kv/platform/keycloak-automation client_id)" \
  --data-urlencode "client_secret=$(vault_field kv/platform/keycloak-automation client_secret)" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')
[ -n "$admin_token" ] || { echo "FATAL: Keycloak admin token failed" >&2; exit 1; }
kc() { curl -sS -H "Authorization: Bearer $admin_token" "$@"; }

user_id=$(kc "$KC_BASE_URL/admin/realms/$KC_REALM/users?username=$SYNTHETIC_USERNAME&exact=true" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[0]["id"] if d else "")')

if [ -z "$user_id" ]; then
  # A declarative user profile rejects a representation with blank managed
  # attributes and then demands VERIFY_PROFILE at first login, which no
  # non-interactive acceptance can satisfy. Send the whole profile at once.
  python3 -c '
import json, sys
print(json.dumps({
    "username": sys.argv[1],
    "enabled": True,
    "emailVerified": True,
    "email": sys.argv[1] + "@synthetic.invalid",
    "firstName": "Etik Speak",
    "lastName": "Synthetic Manager",
    "attributes": {"org_id": [sys.argv[2]]},
}))' "$SYNTHETIC_USERNAME" "$SYNTHETIC_ORG_ID" \
  | kc -o /dev/null -w '' -X POST -H 'Content-Type: application/json' \
      --data-binary @- "$KC_BASE_URL/admin/realms/$KC_REALM/users"
  user_id=$(kc "$KC_BASE_URL/admin/realms/$KC_REALM/users?username=$SYNTHETIC_USERNAME&exact=true" \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[0]["id"] if d else "")')
  [ -n "$user_id" ] || { echo "FATAL: synthetic manager was not created" >&2; exit 1; }
  echo "keycloak: user created"
else
  echo "keycloak: user present"
fi

# Re-assert the tenant claim without touching the rest of the representation.
# A full-representation PUT built from partial data silently blanks email and
# name, which then forces VERIFY_PROFILE — an outage that looks like a
# permission problem.
current=$(kc "$KC_BASE_URL/admin/realms/$KC_REALM/users/$user_id")
printf '%s' "$current" | python3 -c '
import json, sys
u = json.load(sys.stdin)
attrs = u.get("attributes") or {}
attrs["org_id"] = [sys.argv[1]]
u["attributes"] = attrs
u["enabled"] = True
print(json.dumps(u))' "$SYNTHETIC_ORG_ID" \
  | kc -o /dev/null -X PUT -H 'Content-Type: application/json' --data-binary @- \
      "$KC_BASE_URL/admin/realms/$KC_REALM/users/$user_id"

sudo cat "$SYNTHETIC_PASSWORD_FILE" | python3 -c '
import json, sys
print(json.dumps({"type": "password", "value": sys.stdin.read(), "temporary": False}))' \
  | kc -o /dev/null -X PUT -H 'Content-Type: application/json' --data-binary @- \
      "$KC_BASE_URL/admin/realms/$KC_REALM/users/$user_id/reset-password"

role_repr=$(kc "$KC_BASE_URL/admin/realms/$KC_REALM/roles/ethics-manager")
printf '[%s]' "$role_repr" | kc -o /dev/null -X POST -H 'Content-Type: application/json' \
  --data-binary @- "$KC_BASE_URL/admin/realms/$KC_REALM/users/$user_id/role-mappings/realm"
echo "keycloak: org claim, credential and ethics-manager role asserted"

# ---------------------------------------------------------------------------
# 3. Authorization plane. permission-service is not routable from this host;
#    the public ingress hostname has no hairpin route either, so reach the
#    Service through the API server.
# ---------------------------------------------------------------------------
kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NS" \
  port-forward svc/permission-service "$LOCAL_PORT:8090" >/dev/null 2>&1 &
forward_pid=$!
trap 'kill "$forward_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  curl -sS -o /dev/null "http://127.0.0.1:$LOCAL_PORT/actuator/health" 2>/dev/null && break
  sleep 1
done
BASE="http://127.0.0.1:$LOCAL_PORT"

mint() { # username, password on stdin
  local username=$1 password
  IFS= read -r password
  curl -sS -X POST "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" \
    -d grant_type=password -d client_id=frontend \
    --data-urlencode "username=$username" --data-urlencode "password=$password" \
    --data-urlencode "scope=openid ethics-manager-audience ethics:case:manage" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))'
  unset password
}

synthetic_token=$(sudo cat "$SYNTHETIC_PASSWORD_FILE" | mint "$SYNTHETIC_USERNAME")
[ -n "$synthetic_token" ] || { echo "FATAL: synthetic manager login failed" >&2; exit 1; }

# The first authenticated call lazily materializes the local user row; its
# numeric id — not the Keycloak subject — is what role membership references.
local_user_id=$(curl -sS -H "Authorization: Bearer $synthetic_token" "$BASE/api/v1/authz/me" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("userId",""))')
[[ "$local_user_id" =~ ^[0-9]+$ ]] || {
  echo "FATAL: local user id was not materialized" >&2; exit 1; }
echo "authz: local user id materialized"

writer_token=$(vault_field "$WRITER_VAULT_PATH" admin_persona_password \
  | mint "$(vault_field "$WRITER_VAULT_PATH" admin_persona_username)")
[ -n "$writer_token" ] || { echo "FATAL: provisioner login failed" >&2; exit 1; }

role_id=$(curl -sS -H "Authorization: Bearer $writer_token" "$BASE/api/v1/roles" \
  | python3 -c '
import sys, json
d = json.load(sys.stdin)
rows = d if isinstance(d, list) else d.get("content") or d.get("items") or []
print(next((str(r["id"]) for r in rows if r.get("name") == sys.argv[1]), ""))' \
      "$PERMISSION_ROLE_NAME")
[[ "$role_id" =~ ^[0-9]+$ ]] || {
  echo "FATAL: dedicated permission role $PERMISSION_ROLE_NAME not found" >&2; exit 1; }

members=$(curl -sS -H "Authorization: Bearer $writer_token" "$BASE/api/v1/roles/$role_id/members")
if printf '%s' "$members" | python3 -c '
import sys, json
ids = {str(m.get("userId")) for m in json.load(sys.stdin)}
sys.exit(0 if sys.argv[1] in ids else 1)' "$local_user_id"; then
  echo "authz: already a member of $PERMISSION_ROLE_NAME"
else
  python3 -c 'import json,sys; print(json.dumps({"userIds":[int(sys.argv[1])]}))' "$local_user_id" \
    | curl -sS -o /dev/null -X POST -H "Authorization: Bearer $writer_token" \
        -H 'Content-Type: application/json' --data-binary @- \
        "$BASE/api/v1/roles/$role_id/members"
  echo "authz: added to $PERMISSION_ROLE_NAME"
fi

# ---------------------------------------------------------------------------
# 4. Verify against the live projection, not against what we just sent.
# ---------------------------------------------------------------------------
for _ in $(seq 1 20); do
  projection=$(curl -sS -H "Authorization: Bearer $synthetic_token" "$BASE/api/v1/authz/me")
  if printf '%s' "$projection" | python3 -c '
import sys, json
p = json.load(sys.stdin)
ok = (
    p.get("userId") == p.get("subscriberId")
    and p.get("superAdmin") is False
    and "ETIK_SPEAK_MANAGER" in (p.get("roles") or [])
    and (p.get("modules") or {}).get("ETHIC") == "MANAGE"
)
sys.exit(0 if ok else 1)'; then
    echo "verify: synthetic-channel manager holds exactly ETHIC=MANAGE"
    printf '%s' "$projection" | python3 -c '
import sys, json
p = json.load(sys.stdin)
print("  roles:", p.get("roles"), "| modules:", p.get("modules"), "| superAdmin:", p.get("superAdmin"))'
    exit 0
  fi
  sleep 3
done
echo "FATAL: entitlement did not become authoritative; the cell is not provisioned" >&2
exit 1
