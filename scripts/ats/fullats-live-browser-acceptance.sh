#!/usr/bin/env bash
# Full ATS Faz 25 — testai.acik.com gercek aday -> IK -> aday browser kabulü.
#
# Bu hat yalniz platform-test sentetik persona/verisini kullanir. Recruiter'in
# shell module yetkisi DB/OpenFGA seed ile degil, kullanicinin kullandigi
# activation + role/granule/member API'leriyle kurulur. Raw parola/JWT stdout,
# argv, artifact veya GitHub step summary'ye yazilmaz.
#
# A2 MIGRATION NOTE (2026-07-21, Faz 22 Sec KC hardening #2476 A2b.2):
# `client_id=frontend` public + DAG=true — A2c cutover'da DAG=false. Bu accept
# smoke recruiter persona token'ının `resource_access.ats-api.roles`'e bağımlı;
# ats.* scope'lar smoke-client'ta yok. A2c ÖNCESİ Faz25 team ya (a) A2b.3 ile
# smoke-client'a ats.* scope'ları eklemeli, ya (b) dedicated `ats-recruiter-smoke`
# client kurmalı. Aksi halde A2c bu acceptance'ı break eder.
#
# PERSONA + AUDIENCE NOTE (2026-09-06, ats#240 B acceptance, run 34036592826):
# - d35 admin persona Vault `kv/platform/d35-3`'teki username+uid ile bulunur, e-posta
#   ile DEĞİL: realm'de `d35-admin@example.com` başka (attribute'suz) bir kullanıcıya
#   geçmişti; e-posta araması o kullanıcıyı seçip parolasını sıfırlıyor ve Vault'taki
#   persona parolasını BAŞKA hesabın parolasıyla eziyordu (v18). Her diğer d35-3
#   tüketicisi (provision-ats-recruiter-access, faz24/faz35 scriptleri) username ile
#   çalışır; bu hat da öyle. uid Keycloak'ta çözülmez ya da username uyuşmazsa durur.
# - Ürün API'si (permission-service/user-service) token'ı `aud` ile doğrular; d35 admin
#   token'ı `smoke-client` ile alınır (aud: permission-service + `userId` claim'i —
#   numeric kimlik yalnız oradan gelir). Recruiter token'ı `smoke-ats-v1` ile kalır;
#   o client'ın platform audience mapper'ları `scripts/keycloak/setup-smoke-ats-client.sh`
#   desired-state'indedir ve 1/6'da converge edilir.
# - Reset parolası satır sonu TAŞIMAZ: `openssl rand -hex 16` çıktısı `\n` ile
#   bitiyordu, KC'ye ve Vault'a `hex\n` yazılmıştı; `$(vault kv get -field)` ile
#   okuyan her tüketici 401 alırdı.
set -euo pipefail

# ── A2b.3 (gitops #2746): smoke ROPC client secret'i ────────────────────────
# `frontend` public + DAG=true idi; A2c'de DAG=false olacak. Ayrica `frontend`
# fullScopeAllowed=true oldugu icin kullanicinin TUM rollerini tasiyordu.
# Hedef client fullScopeAllowed=false + dar scope ile ayni claim'leri uretir
# (canli dogrulandi: tenant + rol exact-set birebir ayni, audience daraldi).
SMOKE_VAULT_PATH="kv/platform/keycloak/smoke-ats"
PRODUCT_SMOKE_VAULT_PATH="kv/platform/keycloak/smoke-client"
SMOKE_SECRET_FILE="$(mktemp)"; chmod 600 "$SMOKE_SECRET_FILE"
PRODUCT_SECRET_FILE="$(mktemp)"; chmod 600 "$PRODUCT_SECRET_FILE"
# EXIT trap'i ilk Vault okumasindan ONCE kurulur: herhangi bir erken FATAL yolunda temp
# secret dosyasi kalmaz (asagida `cleanup` bu trap'i devralir ve ikisini de siler).
trap 'rm -f "$SMOKE_SECRET_FILE" "$PRODUCT_SECRET_FILE"' EXIT
_SMOKE_INIT="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
[ -r "$_SMOKE_INIT" ] || _SMOKE_INIT="$HOME/bootstrap-drill/vault-init-test.json"
_SMOKE_ROOT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$_SMOKE_INIT" 2>/dev/null || true)"
[ -n "$_SMOKE_ROOT" ] || { echo "FATAL: vault root token okunamadi ($_SMOKE_INIT)" >&2; exit 1; }
# Faz 35 kanonik idiom: token STDIN ile container'a akitilir, iceride `IFS= read -r`
# ile okunur. Token'i `docker exec` ortam-degiskeni bayragiyla gecirmek YASAK — degerle
# gecirilirse argv'ye girer ve `ps`'te gorunur, yalniz isimle gecirilirse container
# environment'ina girer (root /proc/<pid>/environ ile gorur, `docker inspect` gosterir).
# Sozlesme iki bicimi de reddeder; guard dosyayi YORUMLAR DAHIL taradigi icin bu not
# yasakli bayragi harfiyen yazmaz. Bkz.
# tests/deploy/test_faz35_etikspeak_provisioning_contract.py
printf '%s\n' "$_SMOKE_ROOT" | docker exec -i \
    -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-test sh -c '
      set -eu
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      exec vault kv get -field=client_secret "$1"
    ' sh "$SMOKE_VAULT_PATH" > "$SMOKE_SECRET_FILE" 2>/dev/null \
  || { echo "FATAL: $SMOKE_VAULT_PATH okunamadi" >&2; exit 1; }
[ -s "$SMOKE_SECRET_FILE" ] || { echo "FATAL: smoke client secret bos" >&2; exit 1; }

# ── Ürün API'si (permission/user-service) için platform smoke ROPC client'ı ─────
# d35 admin persona'nın numeric kimliği (`userId` claim) yalnız smoke-client'ın
# `smoke-runtime-v1` scope'undan gelir; kardeş provision-ats-recruiter-access.sh ile
# aynı kanonik client. Aynı in-band idiom (token stdin, argv/env'de değer yok).
printf '%s\n' "$_SMOKE_ROOT" | docker exec -i \
    -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-test sh -c '
      set -eu
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      exec vault kv get -field=client_secret "$1"
    ' sh "$PRODUCT_SMOKE_VAULT_PATH" > "$PRODUCT_SECRET_FILE" 2>/dev/null \
  || { echo "FATAL: $PRODUCT_SMOKE_VAULT_PATH okunamadi" >&2; exit 1; }
_SMOKE_ROOT=""
[ -s "$PRODUCT_SECRET_FILE" ] || { echo "FATAL: platform smoke client secret bos" >&2; exit 1; }

BASE_URL="${BASE_URL:-https://testai.acik.com}"
REALM="${REALM:-platform-test}"
KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_JSON="${VAULT_INIT_JSON:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
KCADM="/opt/keycloak/bin/kcadm.sh"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
EXPECTED_CONFIRM="RUN_FAZ25_FULLATS_LIVE_BROWSER"
CONFIRM="${CONFIRM:-}"
EXPECTED_FRONTEND_SHA="${EXPECTED_FRONTEND_SHA:-}"
EXPECTED_ATS_DIGEST="${EXPECTED_ATS_DIGEST:-}"
EXPECTED_PERMISSION_DIGEST="${EXPECTED_PERMISSION_DIGEST:-}"
EXPECTED_FRONTEND_DIGEST="${EXPECTED_FRONTEND_DIGEST:-}"
RECRUITER_USERNAME="ats-recruiter-persona"
RECRUITER_EMAIL="ats-recruiter-persona@test.invalid"
ROLE_NAME="Full ATS Recruiter"
INTERVIEW_MODULE_KEY="INTERVIEW_EVIDENCE"
ATS_MODULE_KEY="ATS"
ATS_JOB_ACTION_KEY="ATS_JOB_MANAGE"
ATS_APPLICATION_ACTION_KEY="ATS_APPLICATION_MANAGE"
PLAYWRIGHT_VERSION="1.60.0"
AXE_VERSION="4.11.3"
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright@sha256:83192064c7510f7ee73dd63dc5f22a5e01a92c81a2e6a9c715d9e3fe55471fd9"
PLAYWRIGHT_INTEGRITY="sha512-hheHdokM8cdqCb0lcE3s+zT4t4W+vvjpGxsZlDnikarzx8tSzMebh3UiFtgqwFwnTnjYQcsyMF8ei2mCO/tpeA=="
AXE_INTEGRITY="sha512-h/kfksv4F0cVIDlKpT4700OehdRgpvuVskuQ2nb7/JmtWUXpe9ftHAPtwyXGvVSsa6SJ64A9ER7Zrzc/sIvC4w=="
CURL_CONNECT_TIMEOUT=10
CURL_MAX_TIME=45

[[ "$BASE_URL" == "https://testai.acik.com" ]] || {
  echo "FATAL: bu acceptance yalniz https://testai.acik.com icin calisir" >&2
  exit 2
}
[[ "$REALM" == "platform-test" && "$KUBE_CONTEXT" == "k3d-test" && "$KUBE_NAMESPACE" == "platform-test" ]] || {
  echo "FATAL: production veya bilinmeyen ortam reddedildi" >&2
  exit 2
}
[[ "$CONFIRM" == "$EXPECTED_CONFIRM" ]] || {
  echo "FATAL: exact test acceptance confirmation gerekli" >&2
  exit 2
}
[[ "$EXPECTED_FRONTEND_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "FATAL: exact reviewed frontend source SHA gerekli" >&2
  exit 2
}
for digest in "$EXPECTED_ATS_DIGEST" "$EXPECTED_PERMISSION_DIGEST" "$EXPECTED_FRONTEND_DIGEST"; do
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo "FATAL: exact immutable runtime digest gerekli" >&2
    exit 2
  }
done

for cmd in curl docker jq openssl python3; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "FATAL: eksik komut: $cmd" >&2
    exit 2
  }
done

if [[ ! -r "$VAULT_INIT_JSON" ]] || ! jq -e '.root_token | type == "string" and length > 0' "$VAULT_INIT_JSON" >/dev/null; then
  echo "FATAL: test Vault init credential contract hazir degil" >&2
  exit 2
fi
for container in "$KC_CONTAINER" "$VAULT_CONTAINER"; do
  docker inspect "$container" >/dev/null 2>&1 || {
    echo "FATAL: gerekli test container'i hazir degil: $container" >&2
    exit 2
  }
done

WORK_ROOT="${RUNNER_TEMP:-/tmp}/fullats-browser-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
SECRET_DIR="$WORK_ROOT/secrets"
EVIDENCE_DIR="${EVIDENCE_DIR:-$WORK_ROOT/evidence}"
mkdir -p "$SECRET_DIR" "$EVIDENCE_DIR"
chmod 700 "$WORK_ROOT" "$SECRET_DIR"

ADMIN_PASSWORD_FILE="$SECRET_DIR/d35-admin.password"
ADMIN_TOKEN_FILE="$SECRET_DIR/d35-admin.jwt"
ADMIN_HEADER_FILE="$SECRET_DIR/d35-admin.header"
RECRUITER_PASSWORD_FILE="$SECRET_DIR/recruiter.password"
RECRUITER_TOKEN_FILE="$SECRET_DIR/recruiter.jwt"
RECRUITER_HEADER_FILE="$SECRET_DIR/recruiter.header"
ADMIN_USERNAME_FILE="$SECRET_DIR/d35-admin.username"

cleanup() {
  set +e
  rm -rf "$SECRET_DIR"
  # mktemp ile acilan client secret dosyalari (ilk EXIT trap'i burada devraliniyor).
  rm -f "$SMOKE_SECRET_FILE" "$PRODUCT_SECRET_FILE"
}
trap cleanup EXIT

json_file() {
  local name="$1"
  local path="$WORK_ROOT/$name"
  umask 077
  : >"$path"
  chmod 600 "$path"
  printf '%s' "$path"
}

vault_root_token() {
  jq -er '.root_token | strings | select(length > 0)' "$VAULT_INIT_JSON"
}

vault_field_to_file() {
  # Root token STDIN ile container'a akar (ust nottaki in-band idiom): host `docker`
  # surecinin env'ine/argv'sine deger girmez. path/field secret degildir, argv ile gecer.
  # Basarisizlikta hedef dosya kalmaz.
  local path="$1" field="$2" destination="$3"
  if vault_root_token | docker exec -i \
      -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
        set -eu
        IFS= read -r VAULT_TOKEN
        export VAULT_TOKEN
        exec vault kv get -field="$2" "$1"
      ' sh "$path" "$field" >"$destination" 2>/dev/null; then
    chmod 600 "$destination"
    [[ -s "$destination" ]]
    return
  fi
  rm -f "$destination"
  return 1
}

persist_d35_password() {
  # STDIN: 1. satir root token (sh `read` yalniz o satiri tuketir), kalan byte'lar parola
  # (`admin_persona_password=-` stdin'den okur; parola dosyasi satir sonsuz). Ne token ne
  # parola argv/env'e girer. Olculdu: read sonrasi exec'e kalan byte'lar birebir gecer.
  chmod 600 "$ADMIN_PASSWORD_FILE"
  { vault_root_token; cat "$ADMIN_PASSWORD_FILE"; } | docker exec -i \
      -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
        set -eu
        IFS= read -r VAULT_TOKEN
        export VAULT_TOKEN
        exec vault kv patch kv/platform/d35-3 admin_persona_password=-
      ' >/dev/null
}

token_from_password() {
  # $4/$5: ROPC client + secret dosyasi. Varsayilan smoke-ats-v1 (recruiter: ATS API +
  # platform audience'lari); d35 admin persona icin smoke-client + PRODUCT_SECRET_FILE.
  local username_file="$1" password_file="$2" token_file="$3"
  local client_id="${4:-smoke-ats-v1}" secret_file="${5:-$SMOKE_SECRET_FILE}"
  local response_file code username
  response_file="$(json_file token-response.json)"
  username="$(tr -d '\r\n' <"$username_file")"
  code="$(curl -sS --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME" \
    -o "$response_file" -w '%{http_code}' \
    -X POST "$BASE_URL/realms/$REALM/protocol/openid-connect/token" \
    --data-urlencode 'grant_type=password' \
    --data-urlencode "client_id=$client_id" \
    --data-urlencode "client_secret@$secret_file" \
    --data-urlencode "username=$username" \
    --data-urlencode "password@$password_file" || true)"
  if [[ "$code" != "200" ]] || ! jq -e '.access_token | type == "string" and length > 100' "$response_file" >/dev/null; then
    rm -f "$response_file"
    return 1
  fi
  jq -r '.access_token' "$response_file" >"$token_file"
  chmod 600 "$token_file"
  rm -f "$response_file"
}

header_from_token() {
  local token_file="$1" header_file="$2"
  {
    printf 'Authorization: Bearer '
    tr -d '\r\n' <"$token_file"
    printf '\n'
  } >"$header_file"
  chmod 600 "$header_file"
}

api_request() {
  local method="$1" path="$2" header_file="$3" output_file="$4" body_file="${5:-}"
  local args=(-sS --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME" \
    -o "$output_file" -w '%{http_code}' -X "$method" -H "@$header_file" -H 'Accept: application/json')
  if [[ -n "$body_file" ]]; then
    args+=(-H 'Content-Type: application/json' --data-binary "@$body_file")
  fi
  curl "${args[@]}" "$BASE_URL$path" || true
}

echo "1/6 Canonical ATS Keycloak personasini uzlastir"
bash scripts/ats/provision-test-keycloak.sh >/dev/null
# smoke-ats-v1 desired-state (platform audience mapper'lari dahil): drift varsa burada
# converge edilir; postcondition basarisizsa (exit 3) acceptance fail-closed durur.
bash scripts/keycloak/setup-smoke-ats-client.sh --apply >/dev/null

RECRUITER_KC_FILE="$(json_file recruiter-kc-user.json)"
docker exec "$KC_CONTAINER" "$KCADM" get users -r "$REALM" \
  -q "email=$RECRUITER_EMAIL" --fields id,username,email,enabled >"$RECRUITER_KC_FILE" 2>/dev/null
python3 - "$RECRUITER_EMAIL" "$RECRUITER_USERNAME" "$RECRUITER_KC_FILE" <<'PY'
import json, pathlib, sys

rows = [
    row
    for row in json.loads(pathlib.Path(sys.argv[3]).read_text())
    if row.get("email") == sys.argv[1]
]
if len(rows) != 1:
    raise SystemExit(f"expected exactly one synthetic recruiter, got {len(rows)}")
row = rows[0]
if row.get("username") != sys.argv[2] or row.get("enabled") is not True:
    raise SystemExit("synthetic recruiter identity or enabled state drifted")
PY
rm -f "$RECRUITER_KC_FILE"

echo "2/6 Sentetik d35 admin credential ve product API authority hazirla"
# Persona kimligi Vault'tan (username + uid); e-posta aramasi YOK (bkz. ust not).
vault_field_to_file kv/platform/d35-3 admin_persona_username "$ADMIN_USERNAME_FILE" || {
  echo "FATAL: kv/platform/d35-3 admin_persona_username okunamadi" >&2
  exit 1
}
vault_field_to_file kv/platform/d35-3 admin_persona_uid "$SECRET_DIR/d35-admin.uid" || {
  echo "FATAL: kv/platform/d35-3 admin_persona_uid okunamadi" >&2
  exit 1
}
D35_UID="$(tr -d '\r\n' <"$SECRET_DIR/d35-admin.uid")"
[[ "$D35_UID" =~ ^[0-9a-f-]{36}$ ]] || {
  echo "FATAL: admin_persona_uid Keycloak user id biciminde degil" >&2
  exit 1
}
D35_JSON="$(docker exec "$KC_CONTAINER" "$KCADM" get "users/$D35_UID" -r "$REALM" 2>/dev/null || true)"
D35_FILE="$(json_file d35-user.json)"
printf '%s' "$D35_JSON" >"$D35_FILE"
python3 - "$D35_UID" "$ADMIN_USERNAME_FILE" "$D35_FILE" <<'PY'
import json, pathlib, sys
try:
    row = json.loads(pathlib.Path(sys.argv[3]).read_text())
except ValueError:
    row = None
if not isinstance(row, dict) or row.get("id") != sys.argv[1]:
    raise SystemExit("synthetic d35 admin uid from Vault does not resolve in Keycloak")
if row.get("username") != pathlib.Path(sys.argv[2]).read_text().strip():
    raise SystemExit("synthetic d35 admin username drifted between Vault and Keycloak")
if row.get("enabled") is not True:
    raise SystemExit("synthetic d35 admin is disabled")
PY
rm -f "$D35_FILE"
chmod 600 "$ADMIN_USERNAME_FILE" "$SECRET_DIR/d35-admin.uid"

if ! vault_field_to_file kv/platform/d35-3 admin_persona_password "$ADMIN_PASSWORD_FILE" || \
   ! token_from_password "$ADMIN_USERNAME_FILE" "$ADMIN_PASSWORD_FILE" "$ADMIN_TOKEN_FILE" smoke-client "$PRODUCT_SECRET_FILE"; then
  # Satir sonu TASIMAYAN parola: `openssl rand -hex 16` '\n' ile biter; o byte KC'ye ve
  # Vault'a girerse `$(vault kv get -field)` ile okuyan her tuketici 401 alir
  # (2026-09-06 v18 olcumu: 33 byte, son byte '\n'). Reset yalniz Vault uid'sine gider.
  openssl rand -hex 16 | tr -d '\r\n' >"$ADMIN_PASSWORD_FILE"
  chmod 600 "$ADMIN_PASSWORD_FILE"
  python3 - "$ADMIN_PASSWORD_FILE" <<'PY' | docker exec -i "$KC_CONTAINER" "$KCADM" \
      update "users/$D35_UID/reset-password" -r "$REALM" -f - >/dev/null
import json, pathlib, sys
print(json.dumps({"type":"password","temporary":False,"value":pathlib.Path(sys.argv[1]).read_text().rstrip("\r\n")}))
PY
  # Verify BEFORE persisting. Writing Vault first and checking afterwards means a
  # failed verification leaves Vault holding a password Keycloak never accepted, and
  # every later reader of kv/platform/d35-3 then authenticates with a value that
  # cannot work. Measured on 2026-07-27: kv/platform/d35-3 was at v13 while Keycloak
  # still matched v11, so `provision-test-ethic-entitlement.sh` and
  # `repair-d35-permission-writer-credential.sh` both got 401 from a live realm that
  # was otherwise healthy. `kcadm update .../reset-password` can exit 0 without the
  # intended password becoming usable, so its exit status is not sufficient proof.
  token_from_password "$ADMIN_USERNAME_FILE" "$ADMIN_PASSWORD_FILE" "$ADMIN_TOKEN_FILE" smoke-client "$PRODUCT_SECRET_FILE" || {
    echo "FATAL: sentetik d35 admin parolasi Keycloak tarafinda dogrulanamadi;" >&2
    echo "       Vault'a YAZILMADI (kv/platform/d35-3 dokunulmadan kaldi)." >&2
    exit 1
  }
  persist_d35_password
  echo "PASS sentetik d35 admin parolasi Vault ile guvenli uzlastirildi"
fi
header_from_token "$ADMIN_TOKEN_FILE" "$ADMIN_HEADER_FILE"
AUTHZ_OUT="$(json_file d35-authz.json)"
AUTHZ_CODE="$(api_request GET /api/v1/authz/me "$ADMIN_HEADER_FILE" "$AUTHZ_OUT")"
if [[ "$AUTHZ_CODE" != "200" ]] || ! jq -e '
    (.superAdmin == true) or
    (((.modules.ACCESS? // "") | tostring | ascii_upcase) == "MANAGE")
  ' "$AUTHZ_OUT" >/dev/null; then
  echo "FATAL: d35 admin product API ACCESS authority yok (authz/me HTTP $AUTHZ_CODE)" >&2
  exit 1
fi
rm -f "$AUTHZ_OUT"

echo "3/6 Recruiter'i user-service product yoluyla aktive et"
vault_field_to_file kv/platform/ats-smoke RECRUITER_PW "$RECRUITER_PASSWORD_FILE" || {
  echo "FATAL: recruiter parolasi Vault'ta yok" >&2
  exit 1
}
[[ "$(wc -c <"$RECRUITER_PASSWORD_FILE")" -ge 12 ]] || {
  echo "FATAL: recruiter parolasi test policy minimumunun altinda" >&2
  exit 1
}
printf '%s' "$RECRUITER_USERNAME" >"$SECRET_DIR/recruiter.username"
chmod 600 "$SECRET_DIR/recruiter.username"
token_from_password "$SECRET_DIR/recruiter.username" "$RECRUITER_PASSWORD_FILE" "$RECRUITER_TOKEN_FILE" || {
  echo "FATAL: recruiter token alinamadi" >&2
  exit 1
}
header_from_token "$RECRUITER_TOKEN_FILE" "$RECRUITER_HEADER_FILE"

# Ilk profil istegi, local-KC first-login provision contract'ini tetikler.
PROFILE_OUT="$(json_file recruiter-profile.json)"
PROFILE_CODE="$(api_request GET /api/v1/users/me/profile "$RECRUITER_HEADER_FILE" "$PROFILE_OUT")"
[[ "$PROFILE_CODE" == "200" || "$PROFILE_CODE" == "403" ]] || {
  echo "FATAL: recruiter first-login provision beklenmeyen HTTP $PROFILE_CODE" >&2
  exit 1
}

LOOKUP_OUT="$(json_file recruiter-user.json)"
LOOKUP_CODE="$(curl -sS --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME" \
  -o "$LOOKUP_OUT" -w '%{http_code}' -G \
  -H "@$ADMIN_HEADER_FILE" -H 'Accept: application/json' \
  --data-urlencode "email=$RECRUITER_EMAIL" \
  "$BASE_URL/api/v1/users/by-email" || true)"
[[ "$LOOKUP_CODE" == "200" ]] || {
  echo "FATAL: recruiter local user row product yolunda olusmadi (HTTP $LOOKUP_CODE)" >&2
  exit 1
}
RECRUITER_USER_ID="$(jq -r '.id // empty' "$LOOKUP_OUT")"
[[ "$RECRUITER_USER_ID" =~ ^[0-9]+$ ]] || {
  echo "FATAL: recruiter numeric user id gecersiz" >&2
  exit 1
}
ACTIVATION_BODY="$(json_file activate-recruiter.json)"
printf '%s' '{"active":true}' >"$ACTIVATION_BODY"
ACTIVATION_OUT="$(json_file activation-result.json)"
ACTIVATION_CODE="$(api_request PUT "/api/v1/users/$RECRUITER_USER_ID/activation" "$ADMIN_HEADER_FILE" "$ACTIVATION_OUT" "$ACTIVATION_BODY")"
[[ "$ACTIVATION_CODE" == "200" ]] || {
  echo "FATAL: recruiter activation product API HTTP $ACTIVATION_CODE" >&2
  exit 1
}

echo "4/6 Recruiter least-privilege ATS grant'lerini role/granule/member API'leriyle kur"
ROLES_OUT="$(json_file roles.json)"
ROLES_CODE="$(api_request GET /api/v1/roles "$ADMIN_HEADER_FILE" "$ROLES_OUT")"
[[ "$ROLES_CODE" == "200" ]] || {
  echo "FATAL: role list product API HTTP $ROLES_CODE" >&2
  exit 1
}
ROLE_COUNT="$(jq --arg name "$ROLE_NAME" '[.items[]? | select(.name == $name)] | length' "$ROLES_OUT")"
if [[ "$ROLE_COUNT" == "0" ]]; then
  CREATE_ROLE_BODY="$(json_file create-role.json)"
  jq -n --arg name "$ROLE_NAME" \
    '{name:$name,description:"Faz 25 sentetik recruiter browser acceptance — least privilege"}' >"$CREATE_ROLE_BODY"
  CREATE_ROLE_OUT="$(json_file create-role-result.json)"
  CREATE_ROLE_CODE="$(api_request POST /api/v1/roles "$ADMIN_HEADER_FILE" "$CREATE_ROLE_OUT" "$CREATE_ROLE_BODY")"
  [[ "$CREATE_ROLE_CODE" == "201" ]] || {
    echo "FATAL: role create product API HTTP $CREATE_ROLE_CODE" >&2
    exit 1
  }
  ROLE_ID="$(jq -r '.id // empty' "$CREATE_ROLE_OUT")"
elif [[ "$ROLE_COUNT" == "1" ]]; then
  ROLE_ID="$(jq -r --arg name "$ROLE_NAME" '.items[] | select(.name == $name) | .id' "$ROLES_OUT")"
else
  echo "FATAL: duplicate '$ROLE_NAME' role" >&2
  exit 1
fi
[[ "$ROLE_ID" =~ ^[0-9]+$ ]] || {
  echo "FATAL: role id gecersiz" >&2
  exit 1
}

GRANULE_BODY="$(json_file recruiter-granule.json)"
jq -n \
  --arg interview_key "$INTERVIEW_MODULE_KEY" \
  --arg ats_key "$ATS_MODULE_KEY" \
  --arg job_action "$ATS_JOB_ACTION_KEY" \
  --arg application_action "$ATS_APPLICATION_ACTION_KEY" \
  '{permissions:[
    {type:"MODULE",key:$interview_key,grant:"VIEW"},
    {type:"MODULE",key:$ats_key,grant:"VIEW"},
    {type:"ACTION",key:$job_action,grant:"ALLOW"},
    {type:"ACTION",key:$application_action,grant:"ALLOW"}
  ]}' >"$GRANULE_BODY"
GRANULE_OUT="$(json_file recruiter-granule-result.json)"
GRANULE_CODE="$(api_request PUT "/api/v1/roles/$ROLE_ID/granules" "$ADMIN_HEADER_FILE" "$GRANULE_OUT" "$GRANULE_BODY")"
[[ "$GRANULE_CODE" == "200" ]] || {
  echo "FATAL: role granule product API HTTP $GRANULE_CODE" >&2
  exit 1
}
GRANULE_SNAPSHOT_OUT="$(json_file recruiter-granule-snapshot.json)"
GRANULE_SNAPSHOT_CODE="$(api_request GET "/api/v1/roles/$ROLE_ID/granules" "$ADMIN_HEADER_FILE" "$GRANULE_SNAPSHOT_OUT")"
if [[ "$GRANULE_SNAPSHOT_CODE" != "200" ]] || ! jq -e --argjson role_id "$ROLE_ID" '
    (.roleId == $role_id) and
    ((.granules | map([.type, .key, .grant] | join(":")) | sort) == [
      "ACTION:ATS_APPLICATION_MANAGE:ALLOW",
      "ACTION:ATS_JOB_MANAGE:ALLOW",
      "MODULE:ATS:VIEW",
      "MODULE:INTERVIEW_EVIDENCE:VIEW"
    ])
  ' "$GRANULE_SNAPSHOT_OUT" >/dev/null; then
  echo "FATAL: target recruiter role exact four-granule snapshot mismatch" >&2
  exit 1
fi
ASSIGNMENT_BODY="$(json_file recruiter-assignment.json)"
jq -n --argjson role_id "$ROLE_ID" '{roleIds:[$role_id]}' >"$ASSIGNMENT_BODY"
ASSIGNMENT_OUT="$(json_file recruiter-assignment-result.json)"
ASSIGNMENT_CODE="$(api_request POST "/api/v1/authz/users/$RECRUITER_USER_ID/assignments" "$ADMIN_HEADER_FILE" "$ASSIGNMENT_OUT" "$ASSIGNMENT_BODY")"
[[ "$ASSIGNMENT_CODE" == "200" ]] || {
  echo "FATAL: exact recruiter role replacement product API HTTP $ASSIGNMENT_CODE" >&2
  exit 1
}
USER_ROLES_OUT="$(json_file recruiter-user-roles.json)"
USER_ROLES_CODE="$(api_request GET "/api/v1/authz/users/$RECRUITER_USER_ID/roles" "$ADMIN_HEADER_FILE" "$USER_ROLES_OUT")"
if [[ "$USER_ROLES_CODE" != "200" ]] || ! jq -e \
    --argjson role_id "$ROLE_ID" --arg role_name "$ROLE_NAME" '
      length == 1 and .[0].roleId == $role_id and .[0].roleName == $role_name
    ' "$USER_ROLES_OUT" >/dev/null; then
  echo "FATAL: recruiter active product role set is not exact" >&2
  exit 1
fi
ROLE_MEMBERS_OUT="$(json_file recruiter-role-members.json)"
ROLE_MEMBERS_CODE="$(api_request GET "/api/v1/roles/$ROLE_ID/members" "$ADMIN_HEADER_FILE" "$ROLE_MEMBERS_OUT")"
if [[ "$ROLE_MEMBERS_CODE" != "200" ]] || ! jq -e \
    --argjson recruiter_user_id "$RECRUITER_USER_ID" '
      (type == "array") and
      ([.[] | select(.userId == $recruiter_user_id)] | length == 1) and
      (. | all((keys | sort) == ["assignedAt", "userId"]))
    ' "$ROLE_MEMBERS_OUT" >/dev/null; then
  echo "FATAL: target recruiter exact role membership snapshot mismatch" >&2
  exit 1
fi

RECRUITER_AUTHZ_OUT="$(json_file recruiter-authz.json)"
RECRUITER_AUTHZ_CODE=""
for _ in $(seq 1 30); do
  RECRUITER_AUTHZ_CODE="$(api_request GET /api/v1/authz/me "$RECRUITER_HEADER_FILE" "$RECRUITER_AUTHZ_OUT")"
  if [[ "$RECRUITER_AUTHZ_CODE" == "200" ]] && jq -e \
      --arg interview_key "$INTERVIEW_MODULE_KEY" \
      --arg ats_key "$ATS_MODULE_KEY" \
      --arg job_action "$ATS_JOB_ACTION_KEY" \
      --arg application_action "$ATS_APPLICATION_ACTION_KEY" \
      --arg role_name "$ROLE_NAME" '
    (.superAdmin == false) and
    ((.roles // []) == [$role_name]) and
    ((.modules // {}) == {($interview_key): "VIEW", ($ats_key): "VIEW"}) and
    ((.actions // {}) == {($job_action): "ALLOW", ($application_action): "ALLOW"}) and
    ((.reports // {}) == {})
  ' "$RECRUITER_AUTHZ_OUT" >/dev/null; then
    break
  fi
  sleep 2
done
if [[ "$RECRUITER_AUTHZ_CODE" != "200" ]] || ! jq -e \
    --arg interview_key "$INTERVIEW_MODULE_KEY" \
    --arg ats_key "$ATS_MODULE_KEY" \
    --arg job_action "$ATS_JOB_ACTION_KEY" \
    --arg application_action "$ATS_APPLICATION_ACTION_KEY" \
    --arg role_name "$ROLE_NAME" '
    (.superAdmin == false) and
    ((.roles // []) == [$role_name]) and
    ((.modules // {}) == {($interview_key): "VIEW", ($ats_key): "VIEW"}) and
    ((.actions // {}) == {($job_action): "ALLOW", ($application_action): "ALLOW"}) and
    ((.reports // {}) == {})
  ' "$RECRUITER_AUTHZ_OUT" >/dev/null; then
  echo "FATAL: recruiter ATS least-privilege grant'leri /authz/me'ye 60s icinde yansimadi" >&2
  exit 1
fi
INBOX_OUT="$(json_file recruiter-inbox.json)"
INBOX_CODE="$(api_request GET '/api/ats/v1/recruiter/applications?page=0&size=1' "$RECRUITER_HEADER_FILE" "$INBOX_OUT")"
[[ "$INBOX_CODE" == "200" ]] || {
  echo "FATAL: recruiter ATS inbox preflight HTTP $INBOX_CODE" >&2
  exit 1
}
rm -f "$PROFILE_OUT" "$LOOKUP_OUT" "$ACTIVATION_BODY" "$ACTIVATION_OUT" \
  "$ROLES_OUT" "$GRANULE_BODY" "$GRANULE_OUT" "$GRANULE_SNAPSHOT_OUT" \
  "$ASSIGNMENT_BODY" "$ASSIGNMENT_OUT" "$USER_ROLES_OUT" "$ROLE_MEMBERS_OUT" \
  "$RECRUITER_AUTHZ_OUT" "$INBOX_OUT"

echo "5/6 Immutable Playwright runtime'i hazirla"
docker pull "$PLAYWRIGHT_IMAGE" >/dev/null

echo "6/6 Gercek candidate -> recruiter -> candidate browser yolculugunu calistir"
docker run --rm --ipc=host --network host \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  -e PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
  -e NPM_CONFIG_CACHE=/tmp/npm-cache \
  -e NODE_PATH=/tmp/fullats-pw/node_modules \
  -e BASE_URL="$BASE_URL" \
  -e RECRUITER_USERNAME="$RECRUITER_USERNAME" \
  -e RECRUITER_PASSWORD_FILE=/run/secrets/recruiter.password \
  -e EVIDENCE_DIR=/evidence \
  -e EXPECTED_FRONTEND_SHA="$EXPECTED_FRONTEND_SHA" \
  -e EXPECTED_ATS_DIGEST="$EXPECTED_ATS_DIGEST" \
  -e EXPECTED_PERMISSION_DIGEST="$EXPECTED_PERMISSION_DIGEST" \
  -e EXPECTED_FRONTEND_DIGEST="$EXPECTED_FRONTEND_DIGEST" \
  -e PLAYWRIGHT_VERSION="$PLAYWRIGHT_VERSION" \
  -e AXE_VERSION="$AXE_VERSION" \
  -e PLAYWRIGHT_INTEGRITY="$PLAYWRIGHT_INTEGRITY" \
  -e AXE_INTEGRITY="$AXE_INTEGRITY" \
  -v "$PWD:/work:ro" \
  -v "$SECRET_DIR:/run/secrets:ro" \
  -v "$EVIDENCE_DIR:/evidence" \
  -w /work \
  "$PLAYWRIGHT_IMAGE" bash -ceu '
    npm install --prefix /tmp/fullats-pw --ignore-scripts --no-audit --no-fund --package-lock \
      "playwright@$PLAYWRIGHT_VERSION" "@axe-core/playwright@$AXE_VERSION" >/dev/null
    node - <<'"'"'NODE'"'"'
const fs = require("fs");
const lock = JSON.parse(fs.readFileSync("/tmp/fullats-pw/package-lock.json", "utf8"));
const pw = lock.packages["node_modules/playwright"];
const axe = lock.packages["node_modules/@axe-core/playwright"];
if (pw?.version !== process.env.PLAYWRIGHT_VERSION || pw?.integrity !== process.env.PLAYWRIGHT_INTEGRITY) process.exit(31);
if (axe?.version !== process.env.AXE_VERSION || axe?.integrity !== process.env.AXE_INTEGRITY) process.exit(32);
NODE
    node scripts/ats/fullats-live-browser-acceptance.cjs
  '

echo "PASS Full ATS gercek browser yolculugu: candidate -> recruiter -> candidate"
echo "EVIDENCE_DIR=$EVIDENCE_DIR"
