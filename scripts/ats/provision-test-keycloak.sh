#!/usr/bin/env bash
# 39d-2c/39d-11 + Faz 25 #2526 — platform-test KC realm: ats-api client +
# 14 client-role (13 PERMS + atanmayan export.repair) +
# audience/permission client-scope'ları + persona rol atamaları.
# Model: Codex 019f50b7 verdict A — permission scope'lar DEFAULT (yetki değil);
# gerçek yetki YALNIZ ats-api client-role atamasıyla (rol-kapısı ats#96).
# İdempotent: get-check-then-create; mevcutsa dokunmaz. Cred'ler container
# env'inden (dışarı çıkmaz); bu script parola/secret BASMAZ.
set -euo pipefail

KC=platform-kc-test
REALM=platform-test
KCADM='/opt/keycloak/bin/kcadm.sh'

kc() { docker exec "$KC" "$KCADM" "$@"; }

# login: keycloak-automation service-account (Vault'tan; stdout'a düşmez).
# Bootstrap env parolası rotate edilmiş durumda (invalid_grant) — otomasyon
# client'ı kanonik yol. Önce platform-test realm'i, olmazsa master denenir.
ROOT=$(python3 -c 'import json;print(json.load(open("/home/halil/bootstrap-drill/vault-init-test.json"))["root_token"])')
AUTO_JSON=$(VAULT_TOKEN="$ROOT" docker exec -e VAULT_TOKEN \
  -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-test \
  vault kv get -format=json kv/platform/keycloak-automation)
CID=$(printf '%s' "$AUTO_JSON" | python3 -c 'import json,sys;print(json.load(sys.stdin)["data"]["data"]["client_id"])')
CSEC=$(printf '%s' "$AUTO_JSON" | python3 -c 'import json,sys;print(json.load(sys.stdin)["data"]["data"]["client_secret"])')
login_ok=""
for lr in "$REALM" master; do
  if printf '%s\n' "$CSEC" | docker exec -i -e KCID="$CID" -e KCREALM="$lr" "$KC" sh -c '
    IFS= read -r KCSEC
    /opt/keycloak/bin/kcadm.sh config credentials \
      --server http://localhost:8080 --realm "$KCREALM" \
      --client "$KCID" --secret "$KCSEC" >/dev/null 2>&1
  '; then
    login_ok="$lr"; break
  fi
done
unset CSEC AUTO_JSON
[ -n "$login_ok" ] || { echo "FATAL: keycloak-automation client login başarısız (platform-test + master)" >&2; exit 1; }
echo "KC: kcadm login OK (client=$CID realm=$login_ok)"

# --- 1) ats-api client (salt rol-taşıyıcı; hiçbir auth akışı yok) ---
ATS_CID=$(kc get clients -r $REALM -q clientId=ats-api --fields id --format csv --noquotes 2>/dev/null | head -1 || true)
if [ -z "$ATS_CID" ]; then
  kc create clients -r $REALM \
    -s clientId=ats-api \
    -s enabled=true \
    -s publicClient=false \
    -s standardFlowEnabled=false \
    -s implicitFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=false >/dev/null
  ATS_CID=$(kc get clients -r $REALM -q clientId=ats-api --fields id --format csv --noquotes | head -1)
  echo "KC: ats-api client CREATED"
else
  echo "KC: ats-api client exists"
fi

# --- 2) client-role'ler (13 PERMS + atanmayan export.repair) ---
# 39d-8..11: ats.export.read (receipt/artifact salt-okuma) PERMS'te — operator
# sınıfına atanır. ats.export.repair BİLEREK PERMS DIŞI: rol+scope oluşturulur
# ama HİÇBİR persona'ya otomatik ATANMAZ (runbook R4 onay-kapısı — Codex 39d-11).
PERMS="ats.consent.write ats.recording.write ats.transcription.write ats.transcript.read ats.citation.write ats.review.write ats.review.read ats.application.read ats.application.status.write ats.export.read ats.export.write ats.dsar.write ats.erasure.execute"
REPAIR_PERM="ats.export.repair"
for p in $PERMS $REPAIR_PERM; do
  if ! kc get "clients/$ATS_CID/roles/$p" -r $REALM >/dev/null 2>&1; then
    kc create "clients/$ATS_CID/roles" -r $REALM -s name="$p" >/dev/null
    echo "KC: role $p CREATED"
  fi
done

# --- 3) audience client-scope + mapper ---
AUD_SID=$(kc get client-scopes -r $REALM --fields id,name --format csv --noquotes 2>/dev/null | awk -F, '$2=="ats-api-audience"{print $1}' | head -1 || true)
if [ -z "$AUD_SID" ]; then
  kc create client-scopes -r $REALM \
    -s name=ats-api-audience \
    -s protocol=openid-connect \
    -s 'attributes."include.in.token.scope"=false' \
    -s 'attributes."display.on.consent.screen"=false' >/dev/null
  AUD_SID=$(kc get client-scopes -r $REALM --fields id,name --format csv --noquotes | awk -F, '$2=="ats-api-audience"{print $1}' | head -1)
  kc create "client-scopes/$AUD_SID/protocol-mappers/models" -r $REALM \
    -s name=ats-api-audience-mapper \
    -s protocol=openid-connect \
    -s protocolMapper=oidc-audience-mapper \
    -s 'config."included.client.audience"=ats-api' \
    -s 'config."access.token.claim"=true' \
    -s 'config."id.token.claim"=false' >/dev/null
  echo "KC: ats-api-audience scope+mapper CREATED"
else
  # reconcile (Codex 019f50b7 P1): scope mevcutsa mapper varligi da dogrulanir
  # `set -o pipefail` + `grep -q` upstream docker/kcadm'a SIGPIPE verip mapper
  # gerçekten var olsa bile pipeline'i 141 ile false yapabiliyor. Cevabi önce
  # tamamen materialize et; sonra lokal exact-line kontrolü yap.
  if ! MAPPER_NAMES=$(kc get "client-scopes/$AUD_SID/protocol-mappers/models" -r $REALM \
    --fields name --format csv --noquotes 2>/dev/null); then
    echo "FATAL: audience mapper listesi okunamadi; kor provisioning fail-closed" >&2
    exit 1
  fi
  if ! grep -Fqx "ats-api-audience-mapper" <<<"$MAPPER_NAMES"; then
    kc create "client-scopes/$AUD_SID/protocol-mappers/models" -r $REALM \
      -s name=ats-api-audience-mapper \
      -s protocol=openid-connect \
      -s protocolMapper=oidc-audience-mapper \
      -s 'config."included.client.audience"=ats-api' \
      -s 'config."access.token.claim"=true' \
      -s 'config."id.token.claim"=false' >/dev/null
    echo "KC: ats-api-audience mapper RECONCILED"
  else
    echo "KC: ats-api-audience scope+mapper exists"
  fi
fi

# --- 4) permission client-scope'lar (13 PERMS + repair; scope claim'ine ad girsin) ---
for p in $PERMS $REPAIR_PERM; do
  SID=$(kc get client-scopes -r $REALM --fields id,name --format csv --noquotes 2>/dev/null | awk -F, -v n="$p" '$2==n{print $1}' | head -1 || true)
  if [ -z "$SID" ]; then
    kc create client-scopes -r $REALM \
      -s name="$p" \
      -s protocol=openid-connect \
      -s 'attributes."include.in.token.scope"=true' \
      -s 'attributes."display.on.consent.screen"=false' >/dev/null
    echo "KC: scope $p CREATED"
  fi
done

# --- 5) frontend client'a default-scope bağlama ---
FE_CID=$(kc get clients -r $REALM -q clientId=frontend --fields id --format csv --noquotes 2>/dev/null | head -1 || true)
if [ -z "$FE_CID" ]; then
  echo "FATAL: 'frontend' clientId bulunamadı — realm client listesi kontrol edilmeli" >&2
  kc get clients -r $REALM --fields clientId --format csv --noquotes | head -20 >&2
  exit 1
fi
BOUND=$(kc get "clients/$FE_CID/default-client-scopes" -r $REALM --fields name --format csv --noquotes 2>/dev/null || true)
for name in ats-api-audience $PERMS $REPAIR_PERM; do
  if ! printf '%s\n' "$BOUND" | grep -qx "$name"; then
    SID=$(kc get client-scopes -r $REALM --fields id,name --format csv --noquotes | awk -F, -v n="$name" '$2==n{print $1}' | head -1)
    [ -n "$SID" ] || { echo "FATAL: client-scope bulunamadi: $name" >&2; exit 1; }
    kc update "clients/$FE_CID/default-client-scopes/$SID" -r $REALM >/dev/null
    echo "KC: frontend += default-scope $name"
  fi
done
echo "KC: frontend default-scopes bound (audience + 13 permission + repair)"

# --- 6) persona'lar + rol atamaları ---
# admin@example.com (test super-admin; yalnız ROL+tenant attr; şifreye dokunulmaz): operator (13 rol; repair HARİÇ)
# ats-reader-persona: yalnız interview read; ats-reviewer-persona: consent/ingest/review/citation
# ats-recruiter-persona: yalnız application inbox + insan kontrollü status transition
ensure_user() { # $1=username -> stdout id
  local uid
  uid=$(kc get users -r $REALM -q "username=$1" --fields id --format csv --noquotes 2>/dev/null | head -1 || true)
  if [ -z "$uid" ]; then
    kc create users -r $REALM -s "username=$1" -s enabled=true -s emailVerified=true \
      -s "email=$1@test.invalid" -s firstName=ATS -s lastName=Persona >/dev/null
    uid=$(kc get users -r $REALM -q "username=$1" --fields id --format csv --noquotes | head -1)
    echo "KC: user $1 CREATED" >&2
  fi
  printf '%s' "$uid"
}
grant() { # $1=userId $2..=roles — idempotent get-check; gercek hata YUTULMAZ
  local uid=$1; shift
  local have
  have=$(kc get "users/$uid/role-mappings/clients/$ATS_CID" -r $REALM --fields name --format csv --noquotes 2>/dev/null || true)
  for r in "$@"; do
    if ! printf '%s\n' "$have" | grep -qx "$r"; then
      kc add-roles -r $REALM --uid "$uid" --cclientid ats-api --rolename "$r" >/dev/null
    fi
  done
}
set_tenant() { # $1=userId $2=tenant — user-attribute mapper kaynagi
  kc update "users/$1" -r $REALM -s "attributes.ats_tenant=[\"$2\"]" >/dev/null
}

ADMIN_UID=$(kc get users -r $REALM -q 'username=admin@example.com' -q exact=true --fields id --format csv --noquotes 2>/dev/null | head -1 || true)
if [ -n "$ADMIN_UID" ]; then
  set_tenant "$ADMIN_UID" t-platform-test
  # shellcheck disable=SC2086
  grant "$ADMIN_UID" $PERMS
  echo "KC: admin test kullanıcısına tenant=t-platform-test + 13 ats-api rolü atandı (operator; repair HARİÇ)"
else
  echo "WARN: admin@example.com bulunamadı — operator ataması atlandı" >&2
fi

READER_UID=$(ensure_user ats-reader-persona)
set_tenant "$READER_UID" t-platform-test
grant "$READER_UID" ats.transcript.read ats.review.read
echo "KC: ats-reader-persona → read rolleri"

REVIEWER_UID=$(ensure_user ats-reviewer-persona)
set_tenant "$REVIEWER_UID" t-platform-test
grant "$REVIEWER_UID" ats.consent.write ats.recording.write ats.transcription.write ats.transcript.read ats.citation.write ats.review.write ats.review.read
echo "KC: ats-reviewer-persona → reviewer rolleri (export/dsar/erasure YOK)"

RECRUITER_UID=$(ensure_user ats-recruiter-persona)
set_tenant "$RECRUITER_UID" 00000000-0000-0000-0000-000000000001
grant "$RECRUITER_UID" ats.application.read ats.application.status.write
echo "KC: ats-recruiter-persona → public careers tenant + application read/status rolleri"

# operator persona (13 rol) — admin kullanıcısının şifresine DOKUNMADAN
# export/dsar allow kanıtı için; roleless persona (0 rol) — rol-kapısının
# canlı 403 kanıtı için (default scope'lar token'a girse bile yetki YOK).
OPERATOR_UID=$(ensure_user ats-operator-persona)
set_tenant "$OPERATOR_UID" t-platform-test
# shellcheck disable=SC2086
grant "$OPERATOR_UID" $PERMS
echo "KC: ats-operator-persona → 13 rol (operator; export.repair HARİÇ)"
echo "KC: $REPAIR_PERM rol+scope OLUŞTURULDU, kimseye ATANMADI (R4 repair onay-kapısı: runbook'la manuel atama)"
ROLELESS_UID=$(ensure_user ats-roleless-persona)
set_tenant "$ROLELESS_UID" t-platform-test
echo "KC: ats-roleless-persona → rolsüz (kasıtlı)"

# --- 6b) tenant claim mapper (ATS SecurityConfig TENANT_CLAIM="tenant" sabit,
# fail-closed: claim yoksa HICBIR authority uretilmez). Persona attribute'lari
# mapper gecisinden ONCE yazilir; mevcut mapper atomik PUT ile guncellenir.
# Delete→create penceresi YOK: create/update basarisizsa eski mapper korunur.
if ! TENANT_MAPPER_ROWS=$(kc get "client-scopes/$AUD_SID/protocol-mappers/models" -r $REALM \
  --fields id,name --format csv --noquotes 2>/dev/null); then
  echo "FATAL: tenant mapper listesi okunamadi; kor provisioning fail-closed" >&2
  exit 1
fi
TENANT_MAPPER_ID=$(awk -F, '$2=="ats-tenant-claim-mapper"{print $1; exit}' <<<"$TENANT_MAPPER_ROWS")
TENANT_MAPPER_OK="false"
if [ -n "$TENANT_MAPPER_ID" ]; then
  TENANT_MAPPER_JSON=$(kc get "client-scopes/$AUD_SID/protocol-mappers/models/$TENANT_MAPPER_ID" -r $REALM)
  TENANT_MAPPER_OK=$(printf '%s' "$TENANT_MAPPER_JSON" | python3 -c 'import json,sys
m=json.load(sys.stdin); c=m.get("config",{})
print(str(m.get("protocolMapper")=="oidc-usermodel-attribute-mapper" and c.get("user.attribute")=="ats_tenant" and c.get("claim.name")=="tenant" and c.get("access.token.claim")=="true").lower())')
fi
if [ "$TENANT_MAPPER_OK" != "true" ]; then
  MAPPER_ARGS=(
    -s name=ats-tenant-claim-mapper
    -s protocol=openid-connect
    -s protocolMapper=oidc-usermodel-attribute-mapper
    -s 'config."user.attribute"=ats_tenant'
    -s 'config."claim.name"=tenant'
    -s 'config."jsonType.label"=String'
    -s 'config."access.token.claim"=true'
    -s 'config."id.token.claim"=false'
    -s 'config."userinfo.token.claim"=false'
    -s 'config."multivalued"=false'
    -s 'config."aggregate.attrs"=false'
  )
  if [ -n "$TENANT_MAPPER_ID" ]; then
    kc update "client-scopes/$AUD_SID/protocol-mappers/models/$TENANT_MAPPER_ID" \
      -r $REALM "${MAPPER_ARGS[@]}" >/dev/null
    echo "KC: ats-tenant-claim-mapper atomik UPDATE (user.attribute=ats_tenant)"
  else
    kc create "client-scopes/$AUD_SID/protocol-mappers/models" -r $REALM "${MAPPER_ARGS[@]}" >/dev/null
    echo "KC: ats-tenant-claim-mapper CREATED (user.attribute=ats_tenant)"
  fi
else
  echo "KC: ats-tenant-claim-mapper exists (user attribute)"
fi
if ! TENANT_MAPPER_ROWS=$(kc get "client-scopes/$AUD_SID/protocol-mappers/models" -r $REALM \
  --fields id,name --format csv --noquotes 2>/dev/null); then
  echo "FATAL: tenant mapper post-update listesi okunamadi" >&2
  exit 1
fi
TENANT_MAPPER_ID=$(awk -F, '$2=="ats-tenant-claim-mapper"{print $1; exit}' <<<"$TENANT_MAPPER_ROWS")
[ -n "$TENANT_MAPPER_ID" ] || { echo "FATAL: tenant mapper bulunamadi" >&2; exit 1; }
TENANT_MAPPER_JSON=$(kc get "client-scopes/$AUD_SID/protocol-mappers/models/$TENANT_MAPPER_ID" -r $REALM)
printf '%s' "$TENANT_MAPPER_JSON" | python3 -c 'import json,sys
m=json.load(sys.stdin); c=m.get("config",{})
assert m.get("protocolMapper")=="oidc-usermodel-attribute-mapper"
assert c.get("user.attribute")=="ats_tenant"
assert c.get("claim.name")=="tenant"
assert c.get("access.token.claim")=="true"' || {
  echo "FATAL: tenant mapper post-update dogrulamasi basarisiz" >&2
  exit 1
}

# persona test-şifreleri: Vault degerleri kararlı tutulur; yalnız eksik anahtar
# uretilir. KC her kosumda Vault'taki degerle uzlastirilir; secret argv/stdout'a
# cikmaz. kv/platform/ats-smoke 39d-4 smoke tekrar-koşumlarının kaynağıdır.
ROOT2=$(python3 -c 'import json;print(json.load(open("/home/halil/bootstrap-drill/vault-init-test.json"))["root_token"])')
if ! EXISTING_SMOKE=$(VAULT_TOKEN="$ROOT2" docker exec -e VAULT_TOKEN \
  -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-test \
  vault kv get -format=json kv/platform/ats-smoke 2>/dev/null); then
  EXISTING_SMOKE='{"data":{"data":{}}}'
fi
declare -A PWMAP
declare -A PWKEY=(
  [ats-reader-persona]=READER_PW
  [ats-reviewer-persona]=REVIEWER_PW
  [ats-recruiter-persona]=RECRUITER_PW
  [ats-operator-persona]=OPERATOR_PW
  [ats-roleless-persona]=ROLELESS_PW
)
for u in ats-reader-persona ats-reviewer-persona ats-recruiter-persona ats-operator-persona ats-roleless-persona; do
  k=${PWKEY[$u]}
  PWMAP[$u]=$(printf '%s' "$EXISTING_SMOKE" | python3 -c 'import json,sys
k=sys.argv[1]; print(json.load(sys.stdin).get("data",{}).get("data",{}).get(k,""))' "$k")
  [ -n "${PWMAP[$u]}" ] || PWMAP[$u]=$(openssl rand -hex 12)
  UIDX=$(kc get users -r $REALM -q "username=$u" -q exact=true --fields id --format csv --noquotes | head -1)
  PW_JSON=$(printf '%s' "${PWMAP[$u]}" | python3 -c 'import json,sys
print(json.dumps({"type":"password","temporary":False,"value":sys.stdin.read()}))')
  printf '%s' "$PW_JSON" | docker exec -i "$KC" "$KCADM" \
    update "users/$UIDX/reset-password" -r "$REALM" -f - >/dev/null
  unset PW_JSON
done
printf '%s\0' \
  "${PWMAP[ats-reader-persona]}" \
  "${PWMAP[ats-reviewer-persona]}" \
  "${PWMAP[ats-recruiter-persona]}" \
  "${PWMAP[ats-operator-persona]}" \
  "${PWMAP[ats-roleless-persona]}" \
  | python3 -c 'import json,sys
keys=("READER_PW","REVIEWER_PW","RECRUITER_PW","OPERATOR_PW","ROLELESS_PW")
raw=sys.stdin.buffer.read().split(b"\0")
if raw and raw[-1]==b"": raw.pop()
if len(raw)!=len(keys): raise SystemExit("password serialization arity mismatch")
json.dump(dict(zip(keys,(v.decode("utf-8") for v in raw))),sys.stdout,separators=(",",":"))' \
  | VAULT_TOKEN="$ROOT2" docker exec -i -e VAULT_TOKEN \
      -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-test sh -c '
        set -eu
        f=$(mktemp); chmod 600 "$f"; trap '\''rm -f "$f"'\'' EXIT
        cat >"$f"
        vault kv put kv/platform/ats-smoke @"$f" >/dev/null
      '
unset EXISTING_SMOKE ROOT2 ROOT
echo "KC: 5 persona şifresi Vault ile kararlı uzlaştırıldı (secret argv/stdout yok)"

# --- FINAL ASSERT (Codex 019f50b7 P1: fail-open yerine dogrulanmis durum) ---
fail=0
ROLE_N=$(kc get "clients/$ATS_CID/roles" -r $REALM --fields name --format csv --noquotes | grep -c '^ats\.') || true
[ "$ROLE_N" -eq 14 ] || { echo "ASSERT FAIL: ats-api rol sayisi=$ROLE_N (14 bekleniyor: 13 PERMS + export.repair)" >&2; fail=1; }
BOUND_N=$(kc get "clients/$FE_CID/default-client-scopes" -r $REALM --fields name --format csv --noquotes | grep -cE '^(ats\.|ats-api-audience)') || true
[ "$BOUND_N" -eq 15 ] || { echo "ASSERT FAIL: frontend default ats-scope sayisi=$BOUND_N (15 bekleniyor: audience + 13 PERMS + repair)" >&2; fail=1; }
# TAM-KUME esitligi (Codex 019f50b7: '>=' least-privilege drift'ini yakalamaz —
# reader'a operator rolu eklense bile PASS olurdu; kume birebir eslesmeli)
assert_roles_exact() { # $1=uid $2=etiket $3..=beklenen roller (tam kume)
  local uid=$1 label=$2; shift 2
  local want have
  want=$(printf '%s\n' "$@" | sort)
  have=$(kc get "users/$uid/role-mappings/clients/$ATS_CID" -r $REALM --fields name --format csv --noquotes 2>/dev/null | grep '^ats\.' | sort) || true
  if [ "$want" != "$have" ]; then
    echo "ASSERT FAIL: $label rol kumesi birebir eslesmedi" >&2
    echo "  beklenen: $(printf '%s' "$want" | tr '\n' ' ')" >&2
    echo "  mevcut:   $(printf '%s' "$have" | tr '\n' ' ')" >&2
    fail=1
  fi
}
assert_tenant_exact() { # $1=uid $2=etiket $3=beklenen tenant
  local uid=$1 label=$2 want=$3 have
  have=$(kc get "users/$uid" -r $REALM | python3 -c 'import json,sys
d=json.load(sys.stdin); v=d.get("attributes",{}).get("ats_tenant",[])
print(v[0] if len(v)==1 else "")')
  [ "$have" = "$want" ] || {
    echo "ASSERT FAIL: $label ats_tenant='$have' (beklenen '$want')" >&2
    fail=1
  }
}
# shellcheck disable=SC2086
[ -n "$ADMIN_UID" ] && assert_roles_exact "$ADMIN_UID" operator-admin $PERMS
[ -n "$ADMIN_UID" ] && assert_tenant_exact "$ADMIN_UID" operator-admin t-platform-test
assert_roles_exact "$READER_UID" reader ats.transcript.read ats.review.read
assert_roles_exact "$REVIEWER_UID" reviewer ats.consent.write ats.recording.write ats.transcription.write ats.transcript.read ats.citation.write ats.review.write ats.review.read
assert_roles_exact "$RECRUITER_UID" recruiter ats.application.read ats.application.status.write
# shellcheck disable=SC2086
assert_roles_exact "$OPERATOR_UID" operator $PERMS
assert_tenant_exact "$READER_UID" reader t-platform-test
assert_tenant_exact "$REVIEWER_UID" reviewer t-platform-test
assert_tenant_exact "$RECRUITER_UID" recruiter 00000000-0000-0000-0000-000000000001
assert_tenant_exact "$OPERATOR_UID" operator t-platform-test
assert_tenant_exact "$ROLELESS_UID" roleless t-platform-test
have_roleless=$(kc get "users/$ROLELESS_UID/role-mappings/clients/$ATS_CID" -r $REALM --fields name --format csv --noquotes 2>/dev/null | grep -c '^ats\.') || true
[ "$have_roleless" -eq 0 ] || { echo "ASSERT FAIL: roleless persona rol tasiyor ($have_roleless)" >&2; fail=1; }
[ "$fail" -eq 0 ] || exit 1
echo "ASSERT OK: 14 rol + 15 default-scope + tenant-bagli persona atamalari dogrulandi (export.repair ATANMAMIS)"
echo "DONE 39d-2c"
