#!/usr/bin/env bash
# 39d-2c — platform-test KC realm: ats-api client + 10 client-role +
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
AUTO_JSON=$(docker exec -e VAULT_TOKEN="$ROOT" -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-test \
  vault kv get -format=json kv/platform/keycloak-automation)
CID=$(printf '%s' "$AUTO_JSON" | python3 -c 'import json,sys;print(json.load(sys.stdin)["data"]["data"]["client_id"])')
CSEC=$(printf '%s' "$AUTO_JSON" | python3 -c 'import json,sys;print(json.load(sys.stdin)["data"]["data"]["client_secret"])')
login_ok=""
for lr in "$REALM" master; do
  if docker exec -e KCID="$CID" -e KCSEC="$CSEC" "$KC" sh -c \
    "$KCADM config credentials --server http://localhost:8080 --realm $lr --client \"\$KCID\" --secret \"\$KCSEC\" >/dev/null 2>&1"; then
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

# --- 2) 10 client-role ---
PERMS="ats.consent.write ats.recording.write ats.transcription.write ats.transcript.read ats.citation.write ats.review.write ats.review.read ats.export.write ats.dsar.write ats.erasure.execute"
for p in $PERMS; do
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
  if ! kc get "client-scopes/$AUD_SID/protocol-mappers/models" -r $REALM --fields name --format csv --noquotes 2>/dev/null | grep -qx "ats-api-audience-mapper"; then
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

# --- 3b) tenant claim mapper (ATS SecurityConfig TENANT_CLAIM="tenant" sabit,
# fail-closed: claim yoksa HICBIR authority uretilmez). Platform token'inda
# tenant claim'i yok — test realm'inde sentetik sabit deger: t-platform-test.
if ! kc get "client-scopes/$AUD_SID/protocol-mappers/models" -r $REALM --fields name --format csv --noquotes 2>/dev/null | grep -qx "ats-tenant-claim-mapper"; then
  kc create "client-scopes/$AUD_SID/protocol-mappers/models" -r $REALM \
    -s name=ats-tenant-claim-mapper \
    -s protocol=openid-connect \
    -s protocolMapper=oidc-hardcoded-claim-mapper \
    -s 'config."claim.name"=tenant' \
    -s 'config."claim.value"=t-platform-test' \
    -s 'config."jsonType.label"=String' \
    -s 'config."access.token.claim"=true' \
    -s 'config."id.token.claim"=false' >/dev/null
  echo "KC: ats-tenant-claim-mapper CREATED (tenant=t-platform-test)"
else
  echo "KC: ats-tenant-claim-mapper exists"
fi

# --- 4) 10 permission client-scope (scope claim'ine ad girsin) ---
for p in $PERMS; do
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
for name in ats-api-audience $PERMS; do
  if ! printf '%s\n' "$BOUND" | grep -qx "$name"; then
    SID=$(kc get client-scopes -r $REALM --fields id,name --format csv --noquotes | awk -F, -v n="$name" '$2==n{print $1}' | head -1)
    [ -n "$SID" ] || { echo "FATAL: client-scope bulunamadi: $name" >&2; exit 1; }
    kc update "clients/$FE_CID/default-client-scopes/$SID" -r $REALM >/dev/null
    echo "KC: frontend += default-scope $name"
  fi
done
echo "KC: frontend default-scopes bound (audience + 10 permission)"

# --- 6) persona'lar + rol atamaları ---
# admin@example.com (test super-admin; yalnız ROL eklenir — şifreye dokunulmaz): operator (10 rol)
# ats-reader-persona: yalnız read; ats-reviewer-persona: consent/ingest/review/citation
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

ADMIN_UID=$(kc get users -r $REALM -q 'username=admin@example.com' -q exact=true --fields id --format csv --noquotes 2>/dev/null | head -1 || true)
if [ -n "$ADMIN_UID" ]; then
  grant "$ADMIN_UID" $PERMS
  echo "KC: admin test kullanıcısına 10 ats-api rolü atandı (operator sınıfı)"
else
  echo "WARN: admin@example.com bulunamadı — operator ataması atlandı" >&2
fi

READER_UID=$(ensure_user ats-reader-persona)
grant "$READER_UID" ats.transcript.read ats.review.read
echo "KC: ats-reader-persona → read rolleri"

REVIEWER_UID=$(ensure_user ats-reviewer-persona)
grant "$REVIEWER_UID" ats.consent.write ats.recording.write ats.transcription.write ats.transcript.read ats.citation.write ats.review.write ats.review.read
echo "KC: ats-reviewer-persona → reviewer rolleri (export/dsar/erasure YOK)"

# operator persona (10 rol) — admin kullanıcısının şifresine DOKUNMADAN
# export/dsar allow kanıtı için; roleless persona (0 rol) — rol-kapısının
# canlı 403 kanıtı için (default scope'lar token'a girse bile yetki YOK).
OPERATOR_UID=$(ensure_user ats-operator-persona)
grant "$OPERATOR_UID" $PERMS
echo "KC: ats-operator-persona → 10 rol (operator)"
ROLELESS_UID=$(ensure_user ats-roleless-persona)
echo "KC: ats-roleless-persona → rolsüz (kasıtlı)"

# persona test-şifreleri: bu hostta üretilir → KC set-password + Vault
# kv/platform/ats-smoke (39d-4 smoke tekrar-koşumları buradan okur; stdout'a düşmez)
ROOT2=$(python3 -c 'import json;print(json.load(open("/home/halil/bootstrap-drill/vault-init-test.json"))["root_token"])')
VKV="docker exec -e VAULT_TOKEN=$ROOT2 -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-test vault kv"
declare -A PWMAP
for u in ats-reader-persona ats-reviewer-persona ats-operator-persona ats-roleless-persona; do
  PWMAP[$u]=$(openssl rand -hex 12)
  UIDX=$(kc get users -r $REALM -q "username=$u" -q exact=true --fields id --format csv --noquotes | head -1)
  docker exec -e P="${PWMAP[$u]}" platform-kc-test sh -c "/opt/keycloak/bin/kcadm.sh set-password -r $REALM --userid $UIDX --new-password \"\$P\"" >/dev/null
done
$VKV put kv/platform/ats-smoke \
  READER_PW="${PWMAP[ats-reader-persona]}" \
  REVIEWER_PW="${PWMAP[ats-reviewer-persona]}" \
  OPERATOR_PW="${PWMAP[ats-operator-persona]}" \
  ROLELESS_PW="${PWMAP[ats-roleless-persona]}" >/dev/null
echo "KC: 4 persona şifresi set + Vault kv/platform/ats-smoke seed"

# --- FINAL ASSERT (Codex 019f50b7 P1: fail-open yerine dogrulanmis durum) ---
fail=0
ROLE_N=$(kc get "clients/$ATS_CID/roles" -r $REALM --fields name --format csv --noquotes | grep -c '^ats\.') || true
[ "$ROLE_N" -eq 10 ] || { echo "ASSERT FAIL: ats-api rol sayisi=$ROLE_N (10 bekleniyor)" >&2; fail=1; }
BOUND_N=$(kc get "clients/$FE_CID/default-client-scopes" -r $REALM --fields name --format csv --noquotes | grep -cE '^(ats\.|ats-api-audience)') || true
[ "$BOUND_N" -eq 11 ] || { echo "ASSERT FAIL: frontend default ats-scope sayisi=$BOUND_N (11 bekleniyor)" >&2; fail=1; }
# TAM-KUME esitligi (Codex 019f50b7: '>=' least-privilege drift'ini yakalamaz —
# reader'a operator rolu eklense bile PASS olurdu; kume birebir eslesmeli)
assert_roles_exact() { # $1=uid $2=etiket $3..=beklenen roller (tam kume)
  local uid=$1 label=$2; shift 2
  local want have
  want=$(printf '%s\n' "$@" | sort)
  have=$(kc get "users/$uid/role-mappings/clients/$ATS_CID" -r $REALM --fields name --format csv --noquotes 2>/dev/null | grep '^ats\.' | sort) || true
  if [ "$want" != "$have" ]; then
    echo "ASSERT FAIL: $label rol kumesi birebir eslesmedi" >&2
    echo "  beklenen: $(printf '%s ' $want)" >&2
    echo "  mevcut:   $(printf '%s ' $have)" >&2
    fail=1
  fi
}
# shellcheck disable=SC2086
[ -n "$ADMIN_UID" ] && assert_roles_exact "$ADMIN_UID" operator-admin $PERMS
assert_roles_exact "$READER_UID" reader ats.transcript.read ats.review.read
assert_roles_exact "$REVIEWER_UID" reviewer ats.consent.write ats.recording.write ats.transcription.write ats.transcript.read ats.citation.write ats.review.write ats.review.read
# shellcheck disable=SC2086
assert_roles_exact "$OPERATOR_UID" operator $PERMS
have_roleless=$(kc get "users/$ROLELESS_UID/role-mappings/clients/$ATS_CID" -r $REALM --fields name --format csv --noquotes 2>/dev/null | grep -c '^ats\.') || true
[ "$have_roleless" -eq 0 ] || { echo "ASSERT FAIL: roleless persona rol tasiyor ($have_roleless)" >&2; fail=1; }
[ "$fail" -eq 0 ] || exit 1
echo "ASSERT OK: 10 rol + 11 default-scope + persona atamalari dogrulandi"
echo "DONE 39d-2c"
