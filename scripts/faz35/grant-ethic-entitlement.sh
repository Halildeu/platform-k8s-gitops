#!/usr/bin/env bash
#
# Faz 35 ES-2 — authorize a REAL member of staff for Etik Speak (#970).
#
# Authorizing one real handler took six manual steps across three systems. Miss one and
# the only symptom is a silent 403: the entitlement check collapsed every failure into a
# single denial. `diagnose-ethic-entitlement.sh` answers "what is missing"; this closes it.
#
# The existing provisioner is pinned to three synthetic personas and refuses any other
# target. That pin is correct — synthetic acceptance must never be steerable at a real
# person — but it left no path at all for actual staff, so the six steps were done by
# hand each time.
#
# WHAT THIS DOES NOT DO, deliberately:
#
#   * It never creates a Keycloak account, and never sets or resets a password. Granting
#     authority over whistleblowing cases to an identity this script invented would be a
#     different and much worse object. The person must already exist; this only connects
#     an existing identity to an existing role.
#   * It never migrates case data between orgs. Step 6 of the manual runbook moved
#     orphaned rows; moving evidentiary records is a decision, not a provisioning step.
#   * It never runs outside the test cell.
#
# Usage:
#   scripts/faz35/grant-ethic-entitlement.sh <email>            # --check, read-only
#   scripts/faz35/grant-ethic-entitlement.sh <email> --apply
#
# Exit: 0 every link present · 1 at least one missing (or --apply could not close it)
#       2 could not determine
set -euo pipefail
set +x

EMAIL="${1:-}"
MODE="${2:---check}"
if [ -z "$EMAIL" ] || [ "${EMAIL#-}" != "$EMAIL" ]; then
  echo "kullanim: $0 <email> [--check|--apply]" >&2
  exit 64
fi
case "$MODE" in
  --check | --apply) ;;
  *) echo "kullanim: $0 <email> [--check|--apply]" >&2; exit 64 ;;
esac

KC_BASE_URL="${KC_BASE_URL:-http://127.0.0.1:8082}"
KC_REALM="${KC_REALM:-platform-test}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"
PG_CONTAINER="${PG_CONTAINER:-platform-pg-test}"
PERMISSION_ROLE_NAME="${PERMISSION_ROLE_NAME:-ETIK_SPEAK_MANAGER}"
ETHICS_ORG_ID="${ETHICS_ORG_ID:-00000000-0000-0000-0000-000000000001}"
ETHICS_FGA_STORE="${ETHICS_FGA_STORE:-01KXYKEBVTSGEDYJ5GJ0TY67JD}"
FGA_CURL_POD="${FGA_CURL_POD:-deploy/meeting-service}"
WRITER_VAULT_PATH="${WRITER_VAULT_PATH:-kv/platform/d35-3}"
# The gateway, not a port-forward: `by-email` is served by user-service and `roles` by
# permission-service, and only the edge knows that routing. Reaching permission-service
# directly answers "No static resource api/v1/users/by-email".
API_BASE="${API_BASE:-https://testai.acik.com}"
KC_PUBLIC_BASE="${KC_PUBLIC_BASE:-https://testai.acik.com}"
KC_PUBLIC_HOST="${KC_PUBLIC_HOST:-testai.acik.com}"
KC_EDGE_ADDR="${KC_EDGE_ADDR:-127.0.0.1}"

for binding in \
  "$KC_BASE_URL=http://127.0.0.1:8082" \
  "$KC_REALM=platform-test" \
  "$VAULT_CONTAINER=platform-vault-test" \
  "$KUBE_CONTEXT=k3d-test" \
  "$KUBE_NS=platform-test" \
  "$PG_CONTAINER=platform-pg-test" \
  "$ETHICS_FGA_STORE=01KXYKEBVTSGEDYJ5GJ0TY67JD"; do
  [ "${binding%%=*}" = "${binding#*=}" ] || {
    echo "FATAL: bu betik yalnizca TEST icindir; override reddedildi: ${binding%%=*}" >&2
    exit 1
  }
done
if [ "$(hostname -s)" != "aiserver" ] || ! hostname -I | grep -qw "10.9.10.15"; then
  echo "FATAL: bu TEST betigi yetkili aiserver 10.9.10.15 uzerinde kosmalidir" >&2
  exit 1
fi

missing=0
undetermined=0
ok()   { printf '  \033[32m✓\033[0m %-38s %s\n' "$1" "${2:-}"; }
gap()  { printf '  \033[31m✗\033[0m %-38s %s\n' "$1" "${2:-}"; missing=$((missing + 1)); }
huh()  { printf '  \033[33m?\033[0m %-38s %s\n' "$1" "${2:-}"; undetermined=$((undetermined + 1)); }
note() { printf '      %s\n' "$1"; }

psql_q() { docker exec "$PG_CONTAINER" psql -U postgres -d "$1" -t -A -c "$2" 2>/dev/null; }
vault_root_token() {
  sudo python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE"
}
vault_field() {
  vault_root_token | docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c \
    'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; vault kv get -field="$2" "$1"' _ "$1" "$2"
}
api() { # method path [curl args...]
  local method=$1 path=$2; shift 2
  curl -sS -k --resolve "$KC_PUBLIC_HOST:443:$KC_EDGE_ADDR" -X "$method" "$API_BASE$path" "$@"
}
fga() {
  local method=$1 path=$2 body=${3:-}
  if [ -n "$body" ]; then
    kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NS" exec "$FGA_CURL_POD" -- curl -sS --max-time 15 \
      -X "$method" "http://openfga:8080/stores/$ETHICS_FGA_STORE$path" \
      -H 'Content-Type: application/json' -d "$body"
  else
    kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NS" exec "$FGA_CURL_POD" -- curl -sS --max-time 15 \
      -X "$method" "http://openfga:8080/stores/$ETHICS_FGA_STORE$path"
  fi
}

printf '\nEtik Speak yetkilendirme — %s (%s)\n\n' "$EMAIL" "$MODE"

# ── 1. Canonical identity ────────────────────────────────────────────────────────────
# Everything downstream is keyed on this number. `permission_db` carries a table of the
# same name whose ids mean different people (#971); reading it here is the bug, not a
# fallback, so only users_db is consulted.
USER_ID=$(psql_q users_db "select id from users where lower(email)=lower('$EMAIL')")
if [ -z "$USER_ID" ]; then
  gap "kanonik kimlik (users_db)" "kayit yok"
  note "Bu kisi urun dizininde yok. Betik kimlik OLUSTURMAZ — once normal kullanici"
  note "kaydi acilmali; ihbar vakalari uzerinde yetki, bu betigin uydurdugu bir"
  note "kimlige verilemez."
  printf '\nSonuc: zincir baslamadan kesiliyor.\n\n'
  exit 1
fi
ok "kanonik kimlik (users_db)" "id=$USER_ID"

SHADOW=$(psql_q permission_db "select email from users where id=$USER_ID")
if [ -n "$SHADOW" ] && [ "$(printf '%s' "$SHADOW" | tr 'A-Z' 'a-z')" != "$(printf '%s' "$EMAIL" | tr 'A-Z' 'a-z')" ]; then
  huh "kimlik uzayi cakismasi" "permission_db.users[$USER_ID] baskasina ait"
  note "Bu id ile rol veren her arac yanlis kisiye verir (#971). Yetkilendirme"
  note "permission-service API'si uzerinden yapilir; dogrudan id ile INSERT edilmez."
fi

# ── 2. Keycloak account + org alignment ──────────────────────────────────────────────
KC_SUB=$(psql_q keycloak "select id from user_entity where lower(email)=lower('$EMAIL')")
if [ -z "$KC_SUB" ]; then
  gap "Keycloak hesabi" "yok"
  note "Betik hesap ACMAZ ve parola belirlemez. Once normal hesap acilisi."
  printf '\nSonuc: zincir kesiliyor.\n\n'
  exit 1
fi
ok "Keycloak hesabi" "sub=${KC_SUB:0:8}…"

KC_ORG=$(psql_q keycloak "select value from user_attribute where user_id='$KC_SUB' and name='org_id'")
if [ "$KC_ORG" = "$ETHICS_ORG_ID" ]; then
  ok "org_id ozniteligi" "$KC_ORG"
else
  gap "org_id ozniteligi" "${KC_ORG:-yok}"
  note "Etik urununun org'u $ETHICS_ORG_ID."
fi

KC_REALM_ROLE="${KC_REALM_ROLE:-ethics-manager}"
HAS_REALM_ROLE=$(psql_q keycloak "
  select count(*) from user_role_mapping m join keycloak_role r on r.id=m.role_id
   where m.user_id='$KC_SUB' and r.name='$KC_REALM_ROLE'")
if [ "${HAS_REALM_ROLE:-0}" -ge 1 ]; then
  ok "$KC_REALM_ROLE realm rolu" "atanmis"
else
  gap "$KC_REALM_ROLE realm rolu" "atama yok"
  note "Eksikse servis 'The realm_access claim is not valid' der — belirteci"
  note "isaret eder, eksik yetkiyi degil."
fi

# ── 3. Permission role ───────────────────────────────────────────────────────────────
ASSIGNED=$(psql_q permission_db "
  select count(*) from user_role_assignments a join roles r on r.id=a.role_id
  where a.user_id=$USER_ID and r.name='$PERMISSION_ROLE_NAME' and a.active")
if [ "${ASSIGNED:-0}" -ge 1 ]; then
  ok "$PERMISSION_ROLE_NAME rolu" "atanmis"
else
  gap "$PERMISSION_ROLE_NAME rolu" "atama yok"
fi

# ── 4. Object authorization ──────────────────────────────────────────────────────────
# The role answers "may this account use the product". It says nothing about WHICH CASES.
# ethics-service asks OpenFGA keyed by the Keycloak SUBJECT, and derives case_viewer as
# (viewer or triager or handler). Without these the staff list answers 200 with `[]` —
# indistinguishable from "this org has no cases".
CASE_VIEWER=$(fga POST /check \
  "{\"tuple_key\":{\"user\":\"user:$KC_SUB\",\"relation\":\"case_viewer\",\"object\":\"ethics_product:$ETHICS_ORG_ID\"}}" 2>/dev/null \
  | python3 -c 'import sys,json;
try: print(json.load(sys.stdin).get("allowed"))
except Exception: print("")' 2>/dev/null)
case "$CASE_VIEWER" in
  True) ok "case_viewer (turetilmis)" "izinli" ;;
  False) gap "case_viewer (turetilmis)" "izinsiz — handler/triager bagi yok" ;;
  *) huh "case_viewer (turetilmis)" "OpenFGA sorgusu okunamadi" ;;
esac

if [ "$MODE" = "--check" ]; then
  printf '\n'
  if [ "$missing" -eq 0 ] && [ "$undetermined" -eq 0 ]; then
    printf 'Sonuc: tum halkalar yerinde.\n\n'; exit 0
  fi
  [ "$missing" -eq 0 ] && { printf 'Sonuc: eksik halka yok, %d nokta belirlenemedi.\n\n' "$undetermined"; exit 2; }
  printf 'Sonuc: %d eksik halka. Kapatmak icin: %s %s --apply\n\n' "$missing" "$0" "$EMAIL"
  exit 1
fi

# ── Uygulama ─────────────────────────────────────────────────────────────────────────
[ "$missing" -eq 0 ] && { printf '\nSonuc: yapilacak degisiklik yok.\n\n'; exit 0; }
printf '\n  --- uygulaniyor ---\n'

# org_id: an attribute correction on an existing account, not a credential change.
if [ "$KC_ORG" != "$ETHICS_ORG_ID" ]; then
  admin_token=$(curl -sS -X POST "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" \
    -d grant_type=client_credentials \
    -d "client_id=$(vault_field kv/platform/keycloak-automation client_id)" \
    --data-urlencode "client_secret=$(vault_field kv/platform/keycloak-automation client_secret)" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')
  [ -n "$admin_token" ] || { echo "FATAL: Keycloak yonetici belirteci alinamadi" >&2; exit 2; }
  # Read-modify-write the whole representation: a partial update against a declarative
  # user profile drops managed attributes that were not resent.
  curl -sS -H "Authorization: Bearer $admin_token" \
    "$KC_BASE_URL/admin/realms/$KC_REALM/users/$KC_SUB" \
    | python3 -c '
import json, sys
user = json.load(sys.stdin)
user.setdefault("attributes", {})["org_id"] = [sys.argv[1]]
print(json.dumps(user))' "$ETHICS_ORG_ID" \
    | curl -sS -o /dev/null -X PUT -H "Authorization: Bearer $admin_token" \
        -H 'Content-Type: application/json' --data-binary @- \
        "$KC_BASE_URL/admin/realms/$KC_REALM/users/$KC_SUB"
  unset admin_token
  echo "  org_id hizalandi: $ETHICS_ORG_ID"
fi

# Role membership through permission-service's own API, never a direct INSERT. The API
# applies the invariants the table alone does not, and it resolves identity by email —
# which is what keeps the numeric-id collision in #971 from handing the role to someone
# else entirely.
if [ "${ASSIGNED:-0}" -lt 1 ]; then
  # The staff API validates `iss` against the PUBLIC issuer, so a token minted through
  # the loopback admin address never authenticates. Mint through the public hostname and
  # resolve it to the local edge. `frontend` has direct access grants disabled;
  # `smoke-client` is the confidential client that carries this recipe, and its secret is
  # read here rather than passed in so it never reaches a process list.
  writer_user=$(vault_field "$WRITER_VAULT_PATH" admin_persona_username)
  writer_token=$(vault_field "$WRITER_VAULT_PATH" admin_persona_password | {
    IFS= read -r writer_pass
    smoke_secret=$(vault_field kv/platform/keycloak/smoke-client client_secret)
    curl -sS -k --resolve "$KC_PUBLIC_HOST:443:$KC_EDGE_ADDR" \
      -X POST "$KC_PUBLIC_BASE/realms/$KC_REALM/protocol/openid-connect/token" \
      -d grant_type=password -d client_id=smoke-client \
      --data-urlencode "client_secret=$smoke_secret" \
      --data-urlencode "username=$writer_user" --data-urlencode "password=$writer_pass" \
      --data-urlencode "scope=openid ethics-manager-audience ethics:case:manage" \
      | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))'
    unset writer_pass smoke_secret
  })
  unset writer_user
  [ -n "$writer_token" ] || { echo "FATAL: yetkilendirme yazicisi giris yapamadi" >&2; exit 2; }

  # Role membership references permission-service's OWN user id, which is not necessarily
  # the users_db id. Resolving it through the service — which keys on email — is also what
  # keeps the numeric-id collision in #971 from handing the role to a different person.
  MEMBER_ID=$(api GET /api/v1/users/by-email -H "Authorization: Bearer $writer_token" \
    --get --data-urlencode "email=$EMAIL" \
    | python3 -c '
import sys, json
try: d = json.load(sys.stdin)
except Exception: print(""); raise SystemExit
print(str(d.get("id", "")) if isinstance(d, dict) else "")')
  [ -n "$MEMBER_ID" ] || { echo "FATAL: permission-service kimligi cozemedi" >&2; exit 2; }
  [ "$MEMBER_ID" = "$USER_ID" ] || \
    echo "  not: permission-service id=$MEMBER_ID, users_db id=$USER_ID — servisin kimligi kullanildi"

  role_id=$(api GET /api/v1/roles -H "Authorization: Bearer $writer_token" \
    | python3 -c '
import sys, json
d = json.load(sys.stdin)
# The collection is wrapped, and not always under the same key; falling through to the
# dict itself iterates its string keys and dies on .get().
rows = d if isinstance(d, list) else d.get("content") or d.get("items") or []
print(next((str(r["id"]) for r in rows if r.get("name") == sys.argv[1]), ""))' "$PERMISSION_ROLE_NAME")
  [ -n "$role_id" ] || { echo "FATAL: $PERMISSION_ROLE_NAME rolu bulunamadi" >&2; exit 2; }

  # The collection endpoint takes a LIST under `userIds`; a singular `userId` is a 400.
  code=$(printf '{"userIds":[%s]}' "$MEMBER_ID" | api POST "/api/v1/roles/$role_id/members" \
    -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $writer_token" \
    -H 'Content-Type: application/json' --data-binary @-)
  unset writer_token
  case "$code" in
    2*) echo "  $PERMISSION_ROLE_NAME atandi (HTTP $code)" ;;
    409) echo "  $PERMISSION_ROLE_NAME zaten atanmis (HTTP 409)" ;;
    *) echo "FATAL: rol atama HTTP $code" >&2; exit 1 ;;
  esac
fi

# Keycloak realm role. Read back rather than trusted: a partial representation can leave
# the account with only its default roles while the write reports success.
if [ "${HAS_REALM_ROLE:-0}" -lt 1 ]; then
  admin_token=$(curl -sS -X POST "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" \
    -d grant_type=client_credentials \
    -d "client_id=$(vault_field kv/platform/keycloak-automation client_id)" \
    --data-urlencode "client_secret=$(vault_field kv/platform/keycloak-automation client_secret)" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')
  # The representation is built from the database rather than fetched: the automation
  # service account may create users but is 403 on GET /roles/{name}, and the fetched
  # error body then posts as an invalid RoleRepresentation. Only `manage-users` is
  # needed for the assignment itself, so nothing has to be widened.
  role_uuid=$(psql_q keycloak "
    select id from keycloak_role where name='$KC_REALM_ROLE' and client_role=false")
  [ -n "$role_uuid" ] || { echo "FATAL: $KC_REALM_ROLE realm rolu realm'de yok" >&2; exit 2; }
  role_repr=$(printf '{"id":"%s","name":"%s"}' "$role_uuid" "$KC_REALM_ROLE")
  printf '[%s]' "$role_repr" | curl -sS -o /dev/null -X POST \
    -H "Authorization: Bearer $admin_token" -H 'Content-Type: application/json' \
    --data-binary @- "$KC_BASE_URL/admin/realms/$KC_REALM/users/$KC_SUB/role-mappings/realm"
  back=$(psql_q keycloak "
    select count(*) from user_role_mapping m join keycloak_role r on r.id=m.role_id
     where m.user_id='$KC_SUB' and r.name='$KC_REALM_ROLE'")
  unset admin_token role_repr role_uuid
  [ "${back:-0}" -ge 1 ] || { echo "FATAL: $KC_REALM_ROLE realm rolu tutmadi" >&2; exit 1; }
  echo "  $KC_REALM_ROLE realm rolu atandi (geri okundu)"
fi

# Product membership. Written keyed by the Keycloak subject, because that is what
# ethics-service asks about — not the numeric id the entitlement is built on.
if [ "$CASE_VIEWER" != "True" ]; then
  for relation in triager handler; do
    out=$(fga POST /write \
      "{\"writes\":{\"tuple_keys\":[{\"user\":\"user:$KC_SUB\",\"relation\":\"$relation\",\"object\":\"ethics_product:$ETHICS_ORG_ID\"}]}}" 2>&1 || true)
    case "$out" in
      *write_failed_due_to_invalid_input* | *already\ exists*) echo "  zaten var: $relation" ;;
      "{}" | "") echo "  yazildi: $relation" ;;
      *) echo "FATAL: beklenmedik OpenFGA yanit"; printf '%s\n' "$out" | head -c 300; exit 1 ;;
    esac
  done
fi

# ── Kabul ────────────────────────────────────────────────────────────────────────────
# The derived relation, not the two tuples just written: case_viewer is computed, so
# writing triager/handler is not the same fact as holding case_viewer.
printf '\n  --- kabul ---\n'
missing=0
undetermined=0

ASSIGNED=$(psql_q permission_db "
  select count(*) from user_role_assignments a join roles r on r.id=a.role_id
  where a.user_id=$USER_ID and r.name='$PERMISSION_ROLE_NAME' and a.active")
[ "${ASSIGNED:-0}" -ge 1 ] && ok "$PERMISSION_ROLE_NAME rolu" "atanmis" \
  || gap "$PERMISSION_ROLE_NAME rolu" "hala yok"

KC_ORG=$(psql_q keycloak "select value from user_attribute where user_id='$KC_SUB' and name='org_id'")
[ "$KC_ORG" = "$ETHICS_ORG_ID" ] && ok "org_id ozniteligi" "$KC_ORG" \
  || gap "org_id ozniteligi" "${KC_ORG:-yok}"

HAS_REALM_ROLE=$(psql_q keycloak "
  select count(*) from user_role_mapping m join keycloak_role r on r.id=m.role_id
   where m.user_id='$KC_SUB' and r.name='$KC_REALM_ROLE'")
[ "${HAS_REALM_ROLE:-0}" -ge 1 ] && ok "$KC_REALM_ROLE realm rolu" "atanmis" \
  || gap "$KC_REALM_ROLE realm rolu" "hala yok"

CASE_VIEWER=$(fga POST /check \
  "{\"tuple_key\":{\"user\":\"user:$KC_SUB\",\"relation\":\"case_viewer\",\"object\":\"ethics_product:$ETHICS_ORG_ID\"}}" 2>/dev/null \
  | python3 -c 'import sys,json;
try: print(json.load(sys.stdin).get("allowed"))
except Exception: print("")' 2>/dev/null)
[ "$CASE_VIEWER" = "True" ] && ok "case_viewer (turetilmis)" "izinli" \
  || gap "case_viewer (turetilmis)" "hala izinsiz"

printf '\n'
if [ "$missing" -eq 0 ]; then
  printf 'Sonuc: yetkilendirildi. Kisi yeniden oturum acmali — mevcut belirteci\n'
  printf 'eski org/rol iddiasini tasiyor ve yenilenene kadar 403 almaya devam eder.\n\n'
  exit 0
fi
printf 'Sonuc: %d halka kapanmadi.\n\n' "$missing"
exit 1
