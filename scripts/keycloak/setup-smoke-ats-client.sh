#!/usr/bin/env bash
# setup-smoke-ats-client.sh — Faz 22 Sec A2b.3: `smoke-ats-v1` desired-state (gitops #2746).
#
# ── NEDEN AYRI CLIENT (Opsiyon B), ölçümle ────────────────────────────────────
# #2746 "smoke-client'a ATS scope'larını optional olarak ekle" (Opsiyon A) diyordu.
# 2026-07-27 ölçümü bunun YAPISAL OLARAK ÇALIŞMADIĞINI gösterdi:
#
#   ats.* client-scope'ları : protocolMappers=0, scope-mappings={} → token'ın `scope`
#                             claim'ine yalnız bir STRING ekler, rol projeksiyonu YOK.
#   resource_access[ats-api].roles : built-in `roles` mapper'ından, kullanıcının
#                             ats-api CLIENT ROLLERİNDEN gelir ve client scope'uyla filtrelenir.
#   frontend  : fullScopeAllowed=TRUE  → tüm rolleri filtresiz geçirir (bu yüzden çalışıyor)
#   smoke-client : fullScopeAllowed=FALSE + 0 ats-api eşlemesi → roller ELENİR
#
# Yani Opsiyon A uygulanırsa token 200 döner, `scope` doğru görünür, `resource_access`
# BOŞ gelir ve ATS scriptleri A2c cutover'ında authz'de düşer.
#
# Opsiyon B canlı token ile KANITLANDI (throwaway client+user sondası, sonra silindi):
#   fullScopeAllowed=false + ats-api rollerine AÇIK scope-mapping
#   → aud=["ats-api"] · resource_access={"ats-api":{"roles":[16/16]}}
#
# ── NEDEN `fullScopeAllowed=false` ZORUNLU ───────────────────────────────────
# `true` yapmak tek test credential'ını realm'deki HER rolü taşıyabilir hale getirir —
# `frontend`'in bugün yaptığı ve A2c'nin emekli ettiği şeyin aynısı. Açık rol eşlemesi
# yeterli olduğu ölçüldü, o yüzden bu script `false`'u DESIRED kabul eder ve `true`
# bulursa DRIFT sayıp geri çeker.
#
# ── Roller neden HARDCODE DEĞİL ──────────────────────────────────────────────
# Eşlenecek roller `ats-api` client'ından ÇALIŞMA ANINDA okunur. Sabit liste yeni bir
# `ats.*` rolü eklendiği gün kapsamı sessizce daraltır; dinamik keşif o rolü indiği gün
# kapsar. Liste boş çıkarsa fail-closed (sessiz "0 rol eşlendi" başarı sayılmaz).
#
# ── Modlar ───────────────────────────────────────────────────────────────────
#   --check   read-only: client var mı + shape converged mi + rol eşlemesi tam mı.
#             MUTASYON YOK. exit 0=converged, 2=drift.
#   --apply   create/converge + postcondition read-back assert.
#
# Secret: stdout/log'a ASLA yazılmaz; yalnız sha256'nın ilk 12 hanesi (parity kanıtı).
# Vault seed AYRI adım — bkz. aşağıdaki VAULT notu (fail-closed, sessiz atlama YOK).
#
# Exit: 0 OK · 1 ERROR(input/login/guard) · 2 DRIFT(--check) · 3 POSTCONDITION
#
# ── PLATFORM AUDIENCE MAPPER'LARI (2026-09-06 ölçümü, ats#240 B acceptance) ──
# ATS kendi yetki kararını platforma delege eder (ATS_AUTHORIZATION_PLATFORM_BASE_URL
# → api-gateway → permission-service) ve permission-service/user-service token'ı `aud`
# ile doğrular (SECURITY_JWT_AUDIENCE = account,frontend,<service>). Yalnız
# `aud=["ats-api"]` taşıyan smoke-ats-v1 token'ı bu yüzden HİÇBİR yerde geçmiyordu
# (canlı ölçüm: /api/v1/users/me/profile 401, /api/v1/authz/me 401,
# /api/ats/v1/recruiter/jobs 401 "platform kimliği reddetti"). Çözüm rol/scope
# GENİŞLETMEZ: client-level `oidc-audience-mapper` ile yalnız iki servisin audience'ı
# eklenir (permission-service, user-service). `account`/`frontend` audience'ı KASITLI
# eklenmez — onları kabul eden her platform servisine kapı açardı. Aynı token ile
# ölçüldü: profile 200, authz/me 200 (superAdmin=false, least-privilege modül seti),
# recruiter/applications 200. Eksik/yanlış mapper --check'te DRIFT, --apply'da
# converge + postcondition'dır.
set -euo pipefail

MODE="${1:---check}"
REALM="${REALM:-platform-test}"
CLIENT_ID="smoke-ats-v1"
ATS_CLIENT="ats-api"
VAULT_PATH="kv/platform/keycloak/smoke-ats"

case "$MODE" in
  --check|--apply) ;;
  *) echo "kullanım: $0 [--check|--apply]   (env: REALM, CONFIRM_PROD_SMOKE_ATS)" >&2; exit 1 ;;
esac

case "$REALM" in
  platform-test) KC_CONTAINER="platform-kc-test" ;;
  serban)
    KC_CONTAINER="platform-kc-prod"
    if [ "${CONFIRM_PROD_SMOKE_ATS:-}" != "serban" ]; then
      echo "ERROR: prod realm için CONFIRM_PROD_SMOKE_ATS=serban gerekli (intent-gate)" >&2
      exit 1
    fi ;;
  *) echo "ERROR: desteklenmeyen REALM '$REALM' (platform-test | serban)" >&2; exit 1 ;;
esac

K() { docker exec "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh "$@"; }
KI() { docker exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh "$@"; }

echo "== A2b.3 smoke-ats-v1 ($MODE) — realm=$REALM kc=$KC_CONTAINER =="

kc_login() {
  local p
  p="$(docker exec "$KC_CONTAINER" sh -lc 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"' | tr -d '\n')"
  [ -n "$p" ] || { echo "ERROR: admin password okunamadı" >&2; return 1; }
  K config credentials --server http://localhost:8080 --realm master --user admin --password "$p" >/dev/null 2>&1 \
    || { echo "ERROR: master realm login başarısız" >&2; unset p; return 1; }
  unset p
}

guard_realm() {
  local got
  got=$(K get "realms/$REALM" --fields realm 2>/dev/null | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("realm",""))
except Exception: print("")' 2>/dev/null || echo "")
  [ "$got" = "$REALM" ] || { echo "ERROR: realm guard fail (beklenen '$REALM', bulunan '$got')" >&2; exit 1; }
}

# ─── DESIRED shape (açık, review-able) ───────────────────────────────────────
# fullScopeAllowed=false KASITLI ve invariant — yukarıdaki gerekçeye bakın.
desired_shape_args() {
  printf '%s\0' \
    "-s" "clientId=$CLIENT_ID" \
    "-s" "enabled=true" \
    "-s" "publicClient=false" \
    "-s" "serviceAccountsEnabled=false" \
    "-s" "directAccessGrantsEnabled=true" \
    "-s" "standardFlowEnabled=false" \
    "-s" "implicitFlowEnabled=false" \
    "-s" "fullScopeAllowed=false" \
    "-s" "description=A2b.3 ATS smoke ROPC client (gitops #2746). fullScopeAllowed=false + explicit ats-api role scope-mappings; Opsiyon A (optional client-scope) resource_access URETMIYOR."
}

# ── DESIRED default client-scope'lar ────────────────────────────────────────
# `ats-api-audience` ZORUNLU: icinde `ats-tenant-claim-mapper` var
# (claim.name=tenant, user.attribute=ats_tenant). Bu scope olmadan token rolleri
# dogru tasir ama `tenant` claim'i BOS gelir — ATS smoke'lari `tenant|rol-exact-set`
# assert ettigi icin sessizce degil, GURULTULU sekilde duser. 2026-07-27'de once
# eksik birakildi, canli token karsilastirmasi (frontend vs smoke-ats-v1) yakaladi.
# `frontend`'de bu scope default; burada da default olmalı.
# `ats.*` client-scope'ları da ZORUNLU (2026-07-30 ölçümü):
# SecurityConfig authority'leri "İSTENEN scope ∩ ATANMIŞ resource_access rolleri"
# kesişiminden türetir (39d-2b: scope istemek != permission). Bu client'ta roller
# explicit scope-mapping ile DOĞRU geliyordu (ölçüldü: reader 3, reviewer 9,
# operator 15 rol) ama token'ın `scope` claim'inde ats.* SIFIR olduğu için
# kesişim BOŞ kalıyor ve her yetkili çağrı 403 dönüyordu.
# #2746'nın "Opsiyon A tek başına resource_access ÜRETMEZ" tespiti doğruydu;
# eksik olan şey Opsiyon A'nın kesişimin DİĞER yarısını sağladığını görmekti.
# Scope adları ÇALIŞMA ANINDA keşfedilir — rol keşfiyle aynı disiplin, hardcode yok.
ats_scope_names() {
  K get client-scopes -r "$REALM" --fields name --format csv --noquotes 2>/dev/null \
    | tr -d '\r' | grep -E '^ats\.' | sort
}
DESIRED_DEFAULT_SCOPES="ats-api-audience"

# ── DESIRED client-level audience mapper'lar (name|audience) — bkz. üst not ──
# Tam olarak bu ikisi; tests/operations/test_smoke_ats_client_scope_invariant.py
# `account`/`frontend` gibi genişletici audience'ları reddeder.
desired_audience_mappers() {
  printf '%s\n' \
    "smoke-ats-audience-permission-service|permission-service" \
    "smoke-ats-audience-user-service|user-service"
}

# Mapper listesi TEK kcadm çağrısıyla okunur (her çağrı bir JVM açar); stdout'a yalnız
# eksik/yanlış olan "name|audience" satırları, stderr'e satır raporu yazılır.
audience_report() {  # $1=client uuid
  # shellcheck disable=SC2046  # satırlar boşluk içermez; word-split kasıtlı
  K get "clients/$1/protocol-mappers/models" -r "$REALM" 2>/dev/null | python3 -c '
import json,sys
try: rows=json.load(sys.stdin)
except Exception: rows=[]
have={m.get("name"):m for m in rows if isinstance(m,dict)}
for line in sys.argv[1:]:
    name,aud=line.split("|",1)
    m=have.get(name); c=(m or {}).get("config",{})
    ok=(bool(m) and m.get("protocolMapper")=="oidc-audience-mapper"
        and c.get("included.client.audience")==aud and c.get("access.token.claim")=="true")
    print(("  audience %s: var (%s)" % (aud,name)) if ok
          else ("  audience %s: EKSIK (%s) -> platform authz / user-service 401" % (aud,name)),
          file=sys.stderr)
    if not ok: print(line)
' $(desired_audience_mappers)
}

audience_missing_count() {  # $1=client uuid ; stdout: eksik/yanlış sayısı
  audience_report "$1" | grep -c . || true
}

ats_client_uuid() {
  local id
  id=$(K get clients -r "$REALM" -q "clientId=$ATS_CLIENT" --fields id --format csv --noquotes 2>/dev/null | tr -d '\r' | head -1)
  [ -n "$id" ] || { echo "ERROR: '$ATS_CLIENT' client'ı realm '$REALM'de YOK — script client YARATMAZ" >&2; exit 1; }
  printf '%s' "$id"
}

ats_role_names() {  # $1 = ats-api uuid ; ÇALIŞMA ANINDA keşif (hardcode YOK)
  K get "clients/$1/roles" -r "$REALM" --fields name --format csv --noquotes 2>/dev/null | tr -d '\r' | grep -v '^$' | sort
}

client_uuid() {
  K get clients -r "$REALM" -q "clientId=$CLIENT_ID" --fields id --format csv --noquotes 2>/dev/null | tr -d '\r' | head -1
}

report_shape() {  # $1 = client uuid ; DRIFT sayısını global SHAPE_DRIFT'e yazar
  local cur; cur=$(K get "clients/$1" -r "$REALM" 2>/dev/null)
  SHAPE_DRIFT=$(printf '%s' "$cur" | python3 -c '
import json,sys
d=json.load(sys.stdin)
want={"enabled":True,"publicClient":False,"serviceAccountsEnabled":False,
      "directAccessGrantsEnabled":True,"standardFlowEnabled":False,
      "implicitFlowEnabled":False,"fullScopeAllowed":False}
n=0
for k,v in want.items():
    got=d.get(k)
    ok = got == v
    print("  %-28s current=%-6s desired=%-6s %s" % (k, got, v, "MATCH" if ok else "DRIFT"))
    if not ok: n+=1
print("SHAPE_DRIFT=%d" % n)
' | tee /dev/stderr | sed -n 's/^SHAPE_DRIFT=//p')
}

secret_fp() {  # $1 = client uuid ; secret'ı ASLA yazdırmaz
  K get "clients/$1/client-secret" -r "$REALM" 2>/dev/null \
    | python3 -c 'import hashlib,json,sys
try: v=json.load(sys.stdin).get("value") or ""
except Exception: v=""
print(hashlib.sha256(v.encode()).hexdigest()[:12] if v else "YOK")'
}

kc_login; guard_realm
AID="$(ats_client_uuid)"
mapfile -t WANT_ROLES < <(ats_role_names "$AID")
[ "${#WANT_ROLES[@]}" -gt 0 ] || { echo "ERROR: '$ATS_CLIENT' client rolü YOK — eşlenecek rol bulunamadı (fail-closed)" >&2; exit 1; }
echo "  $ATS_CLIENT rolleri (çalışma anında keşif): ${#WANT_ROLES[@]}"

# Keşfedilen ats.* scope'ları desired listeye eklenir (login sonrası; K hazır).
DESIRED_DEFAULT_SCOPES="$DESIRED_DEFAULT_SCOPES $(ats_scope_names | tr '\n' ' ')"
CID="$(client_uuid)"

case "$MODE" in
  --check)
    if [ -z "$CID" ]; then
      echo "  client '$CLIENT_ID': YOK"
      echo ""
      echo "=== DRIFT: client yok (--apply ile oluştur) ==="
      exit 2
    fi
    echo "  client '$CLIENT_ID': var ($CID)"
    echo "--- shape ---"
    report_shape "$CID" >/dev/null
    echo "--- rol scope-mapping ---"
    mapfile -t HAVE < <(K get "clients/$CID/scope-mappings/clients/$AID" -r "$REALM" --fields name --format csv --noquotes 2>/dev/null | tr -d '\r' | grep -v '^$' | sort)
    MISSING=$(comm -23 <(printf '%s\n' "${WANT_ROLES[@]}") <(printf '%s\n' "${HAVE[@]:-}") | grep -cv '^$' || true)
    echo "  eşlenmiş: ${#HAVE[@]}/${#WANT_ROLES[@]}  eksik: $MISSING"
    [ "$MISSING" -gt 0 ] && comm -23 <(printf '%s\n' "${WANT_ROLES[@]}") <(printf '%s\n' "${HAVE[@]:-}") | sed 's/^/    eksik: /'
    echo "--- default client-scope ---"
    SCOPE_MISSING=0
    for want in $DESIRED_DEFAULT_SCOPES; do
      if K get "clients/$CID/default-client-scopes" -r "$REALM" --fields name --format csv --noquotes 2>/dev/null \
           | tr -d '\r' | grep -qx "$want"; then
        echo "  $want: var"
      else
        case "$want" in
          ats-api-audience) echo "  $want: EKSIK (tenant claim'i bos gelir)";;
          *) echo "  $want: EKSIK (scope claim'inde yok -> authority kesisimi BOS -> 403)";;
        esac
        SCOPE_MISSING=$((SCOPE_MISSING+1))
      fi
    done
    echo "--- platform audience mapper ---"
    AUD_MISSING=$(audience_missing_count "$CID")
    echo "  secret fingerprint (sha256[0:12]): $(secret_fp "$CID")"
    echo ""
    if [ "${SHAPE_DRIFT:-1}" = "0" ] && [ "$MISSING" = "0" ] && [ "$SCOPE_MISSING" = "0" ] && [ "$AUD_MISSING" = "0" ]; then
      echo "=== CONVERGED ==="; exit 0
    else
      echo "=== DRIFT: shape=$SHAPE_DRIFT rol-eksik=$MISSING scope-eksik=$SCOPE_MISSING audience-eksik=$AUD_MISSING ==="; exit 2
    fi
    ;;

  --apply)
    if [ -z "$CID" ]; then
      echo "  client yok → create"
      mapfile -d '' -t ARGS < <(desired_shape_args)
      K create clients -r "$REALM" "${ARGS[@]}" >/dev/null 2>&1 \
        || { echo "ERROR: client create başarısız" >&2; exit 1; }
      CID="$(client_uuid)"
      [ -n "$CID" ] || { echo "ERROR: create sonrası client bulunamadı" >&2; exit 1; }
      echo "  ✓ create: $CID"
    else
      echo "  client var → shape converge"
      mapfile -d '' -t ARGS < <(desired_shape_args)
      # clientId create-only; update'te gönderilmez
      UPD=(); skip=0
      for a in "${ARGS[@]}"; do
        if [ "$skip" = "1" ]; then skip=0; continue; fi
        if [ "$a" = "-s" ]; then UPD+=("$a"); continue; fi
        case "$a" in clientId=*) unset 'UPD[${#UPD[@]}-1]'; continue ;; esac
        UPD+=("$a")
      done
      K update "clients/$CID" -r "$REALM" "${UPD[@]}" >/dev/null 2>&1 \
        || { echo "ERROR: shape update başarısız" >&2; exit 1; }
      echo "  ✓ shape converge"
    fi

    # rol scope-mapping'lerini converge et (eksikleri ekle; fazlayı BIRAKMA)
    PAYLOAD=$(K get "clients/$AID/roles" -r "$REALM" 2>/dev/null \
      | python3 -c 'import json,sys; print(json.dumps([{"id":r["id"],"name":r["name"]} for r in json.load(sys.stdin)]))')
    printf '%s' "$PAYLOAD" | KI create "clients/$CID/scope-mappings/clients/$AID" -r "$REALM" -f - >/dev/null 2>&1 || true
    echo "  ✓ rol scope-mapping gönderildi"

    # default client-scope'lar (tenant claim kaynagi)
    for want in $DESIRED_DEFAULT_SCOPES; do
      SID="$(K get client-scopes -r "$REALM" --fields id,name --format csv --noquotes 2>/dev/null \
             | tr -d '\r' | awk -F, -v s="$want" '$2==s{print $1}' | head -1)"
      [ -n "$SID" ] || { echo "ERROR: client-scope '$want' realm'de YOK (script scope YARATMAZ)" >&2; exit 1; }
      K update "clients/$CID/default-client-scopes/$SID" -r "$REALM" >/dev/null 2>&1 || true
      echo "  ✓ default scope: $want"
    done

    # platform audience mapper'ları (eksikleri ekle; fazlayı BIRAKMA). Aynı adda ama
    # yanlış içerikli bir mapper varsa create 409 verir ve script GURULTULU durur —
    # sessiz "ekledim" yok, postcondition da aynı kontrolü tekrar yapar.
    mapfile -t AUD_TODO < <(audience_report "$CID" 2>/dev/null)
    [ "${#AUD_TODO[@]}" -eq 0 ] && echo "  ✓ audience mapper'lar zaten var"
    for line in "${AUD_TODO[@]}"; do
      name="${line%%|*}"; aud="${line#*|}"
      printf '{"name":"%s","protocol":"openid-connect","protocolMapper":"oidc-audience-mapper","consentRequired":false,"config":{"included.client.audience":"%s","id.token.claim":"false","access.token.claim":"true","introspection.token.claim":"true","lightweight.claim":"false"}}' "$name" "$aud" \
        | KI create "clients/$CID/protocol-mappers/models" -r "$REALM" -f - >/dev/null 2>&1 \
        || { echo "ERROR: audience mapper create başarısız: $name ($aud)" >&2; exit 1; }
      echo "  ✓ audience mapper eklendi: $aud"
    done

    # postcondition: read-back assert
    echo "--- postcondition (read-back) ---"
    report_shape "$CID" >/dev/null
    mapfile -t HAVE < <(K get "clients/$CID/scope-mappings/clients/$AID" -r "$REALM" --fields name --format csv --noquotes 2>/dev/null | tr -d '\r' | grep -v '^$' | sort)
    MISSING=$(comm -23 <(printf '%s\n' "${WANT_ROLES[@]}") <(printf '%s\n' "${HAVE[@]:-}") | grep -cv '^$' || true)
    echo "  eşlenmiş: ${#HAVE[@]}/${#WANT_ROLES[@]}  eksik: $MISSING"
    echo "  secret fingerprint (sha256[0:12]): $(secret_fp "$CID")"
    SCOPE_MISSING=0
    for want in $DESIRED_DEFAULT_SCOPES; do
      K get "clients/$CID/default-client-scopes" -r "$REALM" --fields name --format csv --noquotes 2>/dev/null \
        | tr -d '\r' | grep -qx "$want" || SCOPE_MISSING=$((SCOPE_MISSING+1))
    done
    echo "  default scope eksik: $SCOPE_MISSING"
    AUD_MISSING=$(audience_missing_count "$CID" 2>/dev/null)
    echo "  platform audience mapper eksik: $AUD_MISSING"
    if [ "${SHAPE_DRIFT:-1}" != "0" ] || [ "$MISSING" != "0" ] || [ "$SCOPE_MISSING" != "0" ] || [ "$AUD_MISSING" != "0" ]; then
      echo "POSTCONDITION FAIL: shape=$SHAPE_DRIFT rol-eksik=$MISSING scope-eksik=$SCOPE_MISSING audience-eksik=$AUD_MISSING" >&2; exit 3
    fi
    echo ""
    echo "=== APPLIED + POSTCONDITION OK ==="
    cat <<'VAULTNOTE'

── VAULT SEED (AYRI ADIM — sessizce atlanmıyor) ──────────────────────────────
Bu script Vault'a YAZMAZ; seed ayrı adım. Kardeş `setup-smoke-client.sh` bunu root
token ile yapıyor ve o token `.15`'te MEVCUT — sadece yolu değişmiş:

  /srv/platform/secrets/backup-auth/vault-init-test.json   (ACL: script kullanıcısına r--)

DÜZELTME: bu notun ilk hali "dosya .15'e taşınmadı" diyordu. YANLIŞTI — dosya taşındı,
yalnız konumu değişti. İlk arama `~/bootstrap-drill` ve `find -maxdepth 4` ile yapılmıştı;
gerçek yol 5. seviyede olduğu için kaçtı. Token doğrulandı: policies=[root], ttl=0,
`kv/platform/keycloak/smoke-client` okunabiliyor.

Secret'ı Vault'a koymak için, secret'ı argv'ye/geçmişe DÜŞÜRMEDEN:

  kv/platform/keycloak/smoke-ats  ←  CLIENT_SECRET

Yukarıdaki fingerprint (sha256[0:12]) parity kanıtı: Vault'a yazılan değerin aynı
fingerprint'i vermesi beklenir. Fingerprint uyuşmazsa secret rotate edilmiş demektir.
VAULTNOTE
    ;;
esac
