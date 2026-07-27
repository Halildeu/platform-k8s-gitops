# RB Faz 21.3 D35-3 Prereq — Keycloak Admin User + JWT (operatör boundary)

> **Tetikleyici**: D35-2-full / D35-3 evidence runları öncesi tek seferlik prereq.
> **Authority**: **kullanıcı / operatör only**. Agent runbook yazar, fiili admin user oluşturma + password set + token alma kullanıcı boundary'sinde kalır. Codex `019dd409`: "agent runbook yazar; fiili admin user oluşturma, password set, client secret veya token alma user/operatör boundary. Mevcut test personaysa agent sadece token endpoint komutunu env placeholder ile verir. Admin credential veya yeni kullanıcı şifresi agent transcript'ine girmemeli."

## Neden gerekli

`POST /api/v1/access/scope` `Authorization: Bearer <JWT>` ister; JWT Keycloak realm'den alınır. Test cluster realm: `platform-test` veya `master` (ortam'a göre). D35-2-full Step 9.4'ün koşulması için `JWT_ADMIN` env populated olmalı.

## Boundary kuralları

- **Yapma**: agent admin password set, client secret create, JWT decode → log.
- **Yap**: kullanıcı bu runbook'u kendi terminalinde koşar; JWT'yi kendi env'ine yazar; agent'a sadece "JWT hazır" sinyalini verir.
- **Agent koşacak adımlar (sandbox-safe)**: Keycloak deployment durumu kontrolü, realm/client listesi (read-only kcadm), token endpoint healthcheck.

## Prereq

- [ ] Test cluster Keycloak Running (`kubectl get pod -l app=keycloak -n platform-test`)
- [ ] Test realm var (`platform-test` veya equivalent — D35-2 evidence'a göre teyit)
- [ ] Operatör Vault'tan `kv/platform/keycloak#admin_password` okuyabiliyor (kendi terminalinde)

## Step 1 — Realm ve client topology'si (agent koşar — read-only)

```bash
# Keycloak deployment çalışıyor mu?
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get pod -l app=keycloak -o wide" 2>&1 | head -3

# Realm endpoint reachable mi?
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/keycloak -- curl -sf -o /dev/null -w '%{http_code}\n' \
  http://localhost:8080/realms/platform-test/.well-known/openid-configuration" 2>&1
# Beklenen: 200
```

**Gate**: Keycloak Running + realm endpoint 200.

## Step 2 — Admin persona create (operatör only — kullanıcı koşar)

> **Bu adımı kullanıcı koşar** — agent transcript'inde admin password görmesin.

```bash
# Kullanıcının kendi terminalinde:
KC_ADMIN_PASSWORD=$(vault kv get -field=admin_password kv/platform/keycloak)
KC_BASE="https://acik.com/auth"   # production-like erişim — test cluster için ayrı URL olabilir
KC_REALM="platform-test"

# Admin client token al (kcadm-token endpoint)
KC_ADMIN_TOKEN=$(curl -sf -X POST \
  "${KC_BASE}/realms/master/protocol/openid-connect/token" \
  -d "client_id=admin-cli" \
  -d "username=admin" \
  -d "password=${KC_ADMIN_PASSWORD}" \
  -d "grant_type=password" | jq -r .access_token)

# Yeni admin persona create (D35-3 testleri için)
PERSONA_USERNAME="d35-admin-persona"
# Operatör güçlü bir şifre üretir ve Vault'a kaydeder (örn. `pwgen 24 1` veya
# Vault transit). Bu satıra LITERAL şifre yazılmaz; env'den alınır.
: "${PERSONA_PASSWORD:?üretip Vault'a kaydet (\`vault kv patch kv/platform/d35-3 admin_persona_password=...\`); kullanıcı/operatör adımı}"

curl -sf -X POST "${KC_BASE}/admin/realms/${KC_REALM}/users" \
  -H "Authorization: Bearer ${KC_ADMIN_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  "username": "${PERSONA_USERNAME}",
  "enabled": true,
  "emailVerified": true,
  "firstName": "D35",
  "lastName": "Admin Persona",
  "email": "d35-admin@example.com",
  "credentials": [
    {"type": "password", "value": "${PERSONA_PASSWORD}", "temporary": false}
  ]
}
EOF

# UID al
PERSONA_UID=$(curl -sf -X GET \
  "${KC_BASE}/admin/realms/${KC_REALM}/users?username=${PERSONA_USERNAME}" \
  -H "Authorization: Bearer ${KC_ADMIN_TOKEN}" | jq -r '.[0].id')

echo "PERSONA_UID=${PERSONA_UID}"
# UID'i Vault'a kaydet (tuple seed ve D35-3 evidence için kullanılacak):
vault kv patch kv/platform/d35-3 admin_persona_uid="${PERSONA_UID}" admin_persona_username="${PERSONA_USERNAME}"
```

**Operator gate**: kullanıcı kendi terminalinde koştu, `PERSONA_UID` UUID döndü, Vault'a kaydedildi.

## Step 3 — Granted persona create (operatör only — kullanıcı koşar)

> Aynı kalıp; sadece persona detayları farklı.

```bash
GRANTED_USERNAME="d35-granted-persona"
: "${GRANTED_PASSWORD:?üretip Vault'a kaydet (\`vault kv patch kv/platform/d35-3 granted_persona_password=...\`); kullanıcı/operatör adımı}"

curl -sf -X POST "${KC_BASE}/admin/realms/${KC_REALM}/users" \
  -H "Authorization: Bearer ${KC_ADMIN_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  "username": "${GRANTED_USERNAME}",
  "enabled": true,
  "emailVerified": true,
  "firstName": "D35",
  "lastName": "Granted Persona",
  "email": "d35-granted@example.com",
  "credentials": [
    {"type": "password", "value": "${GRANTED_PASSWORD}", "temporary": false}
  ]
}
EOF

GRANTED_UID=$(curl -sf -X GET \
  "${KC_BASE}/admin/realms/${KC_REALM}/users?username=${GRANTED_USERNAME}" \
  -H "Authorization: Bearer ${KC_ADMIN_TOKEN}" | jq -r '.[0].id')

vault kv patch kv/platform/d35-3 granted_persona_uid="${GRANTED_UID}" granted_persona_username="${GRANTED_USERNAME}"
```

## Step 4 — Admin persona JWT al (operatör only — kullanıcı koşar)

> Bu JWT D35-2-full Step 9.4'te `JWT_ADMIN` olarak kullanılır. **Token max 5dk yaşar** tipik test realm'de — D35-2-full'u baştan sona koşmak için zaman penceresi var.

```bash
# A2b.2 (2026-07-21): confidential smoke-client ROPC (client_id=frontend public + DAG=false, A2c cutover).
# smoke-client kv/platform/keycloak/smoke-client (A2a) + smoke-runtime-v1 default scope (userId+aud×6);
# smoke-notify-v1 opt-in scope org_id capability için (A2b.1 setup-smoke-token-contract.sh çıktısı).
PERSONA_USERNAME=$(vault kv get -field=admin_persona_username kv/platform/d35-3)
PERSONA_PASSWORD=$(vault kv get -field=admin_persona_password kv/platform/d35-3)
SMOKE_CLIENT_SECRET=$(vault kv get -field=client_secret kv/platform/keycloak/smoke-client)

JWT_ADMIN=$(curl -sf -X POST \
  "${KC_BASE}/realms/${KC_REALM}/protocol/openid-connect/token" \
  --data-urlencode "client_id=smoke-client" \
  --data-urlencode "client_secret=${SMOKE_CLIENT_SECRET}" \
  --data-urlencode "username=${PERSONA_USERNAME}" \
  --data-urlencode "password=${PERSONA_PASSWORD}" \
  --data-urlencode "grant_type=password" \
  --data-urlencode "scope=openid" | jq -r .access_token)

# Doğrula: token decode edip claim'leri kontrol et (header.payload.signature)
echo "${JWT_ADMIN}" | cut -d. -f2 | base64 -d 2>/dev/null | jq .
# Beklenen: sub=PERSONA_UID, iss=Keycloak realm URL, exp 5dk sonrası
# DİKKAT: bu JWT'i agent transcript'ine yazma; sadece export et.

# JWT'i kendi shell session'una export et (D35-2-full runner script'i için)
export JWT_ADMIN
```

**Operator gate**: JWT alındı, claim'leri doğru, agent transcript'ine yazılmadı.

## Step 5 — JWT'in `module:ACCESS#can_manage` ile uyumu

> Agent koşabilir — JWT'i kullanıcı export ettikten sonra.

```bash
# JWT'in sub claim'i admin persona UID'i ile eşleşiyor mu?
echo "$JWT_ADMIN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '.sub'
# Eşleştir: vault kv get -field=admin_persona_uid kv/platform/d35-3

# Eğer module:ACCESS#can_manage tuple'ı admin için seedlenmiş (Step 3 prereq tuple seed runbook'u koşturduktan sonra),
# /check 'allowed: true' dönmeli. Bu adım tuple seed'in admin UID ile uyumunu doğrular.
ADMIN_UID=$(vault kv get -field=admin_persona_uid kv/platform/d35-3)
# (Sonraki check komutu RB-faz-21-3-d35-3-prereq-tuple-seed.md Step 4'teki ile aynı.)
```

**Gate**: JWT.sub == ADMIN_UID == module:ACCESS#can_manage tuple user. Üçü de eşleşince D35-2-full Step 9.4 hazır.

## Step 6 — Granted persona JWT (opsiyonel, D35-3 Step 4 için)

> Sadece "granted persona kendi listesini görsün" senaryosu için. UI persona check Step 5'te aynı şekilde JWT alır.

## Cleanup

D35-3 evidence runları bittikten sonra test persona'ları silinebilir (test ortamı temizliği için):

```bash
# Operatör koşar — read kc-admin token + DELETE
curl -sf -X DELETE "${KC_BASE}/admin/realms/${KC_REALM}/users/${PERSONA_UID}" \
  -H "Authorization: Bearer ${KC_ADMIN_TOKEN}"
curl -sf -X DELETE "${KC_BASE}/admin/realms/${KC_REALM}/users/${GRANTED_UID}" \
  -H "Authorization: Bearer ${KC_ADMIN_TOKEN}"

# OpenFGA tuple cleanup (RB-prereq-tuple-seed.md Cleanup section)
```

## Pratik notlar

- **Token TTL kısa**: D35-2-full + D35-3'ü tek seansta koşmak için JWT_ADMIN'i Step 4'te alıp hemen evidence run'ları başlat.
- **Refresh token**: gerekirse `grant_type=refresh_token` ile yenile (5dk yetmezse).
- **D35-2-full ↔ D35-3 sıralama**: önce D35-2-full PASS (REST chain), sonra D35-3 (UI). UI session ayrı browser'da; UI'nin kendi token akışı var (Keycloak SSO redirect).

## References

- ADR-0010 §2.5 (operator/agent boundary matrix)
- CLAUDE.md HARD RULE #7 (SSH+sudo+kubectl yetkisi); #9 (no fake work — JWT'siz REST runner çalıştırma yasak)
- D35-2-full template Step 9.4: `docs/faz-21-3-evidence/d35-2-full-template.md`
- D35-3 template prereq listesi: `docs/faz-21-3-evidence/d35-3-product-path-template.md`
- ACCESS tuple seed runbook: `docs/RB-faz-21-3-d35-3-prereq-tuple-seed.md`
- Keycloak realm/client topology: kullanıcı dışı agent kaynak yok; live kontrol Step 1.
- Codex thread `019dd409` boundary direktifi
