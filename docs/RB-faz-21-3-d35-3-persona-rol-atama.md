# RB Faz 21.3 D35-3 Prereq — Persona realm role atama (operatör boundary)

> **Tetikleyici**: D35-3 UI persona evidence run öncesi. `d35-admin-persona` Keycloak'ta yaratıldı ama default rollerle (`offline_access, default-roles-platform-test, uma_authorization`); frontend `THEME` / `ACCESS` / `USERS` gibi module-role beklediğinden `/unauthorized`'a redirect ediliyor.
> **Authority**: **kullanıcı / operatör only**. Agent runbook yazar, fiili realm role atama operatör boundary'sinde kalır (admin token transcript'e girmesin).
> **Bağlam (2026-04-28)**: testai.acik.com → `Modül erişimi yok — Bu modül rolünüzde tanımlı değil. Gerekli modül: THEME` ekranı. d35-admin-persona UID `cbc9a869-1833-4d9c-beea-a9fa52fa851e`.

## Neden gerekli

mfe-host frontend module guard:
- Login token claim'inden `realm_access.roles` listesi okuyor
- Her modülün entry route'unda role gate (örn. `/admin/data-access` → `ACCESS` realm role gerek)
- Default roller (`offline_access`, `default-roles-platform-test`, `uma_authorization`) Keycloak built-in; module access vermez
- D35-3 evidence için persona admin UI panel'lerine girebilmeli (Veri Erişimi → "Kullanıcı Erişimleri")

## Boundary kuralları

- **Yapma**: Agent admin token al, role atama curl'ünü kendi terminalinde koş, JWT decode → log
- **Yap**: Operatör runbook'u kendi terminalinde koşar; her adımdan sonra agent'a "atama yapıldı, role list X" sinyali verir
- **Agent koşacak adımlar (read-only / sandbox-safe)**: token endpoint healthcheck, persona UID Vault read

## Prereq

- [ ] `d35-admin-persona` Keycloak'ta var (RB-faz-21-3-d35-3-keycloak-admin-jwt.md Step 2 tamamlandı)
- [ ] `d35-granted-persona` Keycloak'ta var (Step 3 tamamlandı)
- [ ] Operatör Keycloak admin token alabiliyor (Step 1)
- [ ] PERSONA_UID Vault'tan okunabiliyor: `vault kv get -field=admin_persona_uid kv/platform/d35-3`

## Step 1 — Admin token + realm role list (operatör koşar)

```bash
# Operatör kendi terminalinde — admin password agent transcript'ine girmesin
KC_BASE="https://testai.acik.com/auth"
KC_REALM="platform-test"

# Admin password lokal dosyadan oku (Vault entegre değilse host-compose secret)
KC_ADMIN_PASSWORD=$(cat ~/Documents/host-compose/keycloak/test/secrets/kc_admin_password.txt)

KC_ADMIN_TOKEN=$(curl -sk -X POST \
  "${KC_BASE}/realms/master/protocol/openid-connect/token" \
  --data-urlencode "client_id=admin-cli" \
  --data-urlencode "username=admin" \
  --data-urlencode "password=${KC_ADMIN_PASSWORD}" \
  --data-urlencode "grant_type=password" | jq -r .access_token)

# Token alındı mı kontrol
[ -n "$KC_ADMIN_TOKEN" ] && [ "$KC_ADMIN_TOKEN" != "null" ] && echo "✓ token alındı" || echo "✗ token boş — şifre/URL kontrol"

# platform-test realm'in tüm realm rollerini listele (agent'a paylaşılabilir — sadece role isimleri, sensitive değil)
curl -sk -H "Authorization: Bearer ${KC_ADMIN_TOKEN}" \
  "${KC_BASE}/admin/realms/${KC_REALM}/roles" | jq -r '.[].name' | sort
```

**Beklenen çıktı (örnek)**: `admin`, `default-roles-platform-test`, `offline_access`, `uma_authorization`, `THEME`, `ACCESS`, `USERS`, `SCHEMA`, vs. modül-spesifik roller.

**Gate**: Realm role listesi alındı. **Bu listeyi agent'a paylaş** — atanması gereken module rolleri agent'tan tespit edilsin.

## Step 2 — Atanacak rolleri tespit et (agent + operatör birlikte)

mfe-host'un module → realm role mapping'i:

| Modül entry route | Beklenen realm role | Açıklama |
|---|---|---|
| `/admin/data-access` | `ACCESS` veya `admin` | Veri erişimi yönetim paneli |
| `/admin/users` | `USERS` veya `admin` | Kullanıcı yönetimi |
| `/admin/schema-explorer` | `SCHEMA` veya `admin` | Schema gezgini |
| `/access/roles` | `ACCESS` | Rol yönetimi |
| Tema/UI | `THEME` | Tema değişim |

> **Not**: Eğer Step 1 listesinde `admin` realm role varsa **tek başına yeterli olabilir** (mfe-host muhtemelen `admin || moduleSpecific` OR mantığıyla bakar). Önce `admin` ata, re-login sonrası test et; yetmezse module-spesifik rolleri tek tek ekle.

## Step 3 — Admin persona'ya `admin` realm role ata (operatör koşar)

```bash
# Persona UID'i al
PERSONA_UID=$(vault kv get -field=admin_persona_uid kv/platform/d35-3 2>/dev/null \
  || echo "cbc9a869-1833-4d9c-beea-a9fa52fa851e")  # fallback bilinen UID

# admin role JSON object'ini al
ADMIN_ROLE_JSON=$(curl -sk -H "Authorization: Bearer ${KC_ADMIN_TOKEN}" \
  "${KC_BASE}/admin/realms/${KC_REALM}/roles/admin")

# Atama POST
curl -sk -X POST \
  "${KC_BASE}/admin/realms/${KC_REALM}/users/${PERSONA_UID}/role-mappings/realm" \
  -H "Authorization: Bearer ${KC_ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "[${ADMIN_ROLE_JSON}]"
# Beklenen: HTTP 204 No Content (boş response)

# Atama doğrula
curl -sk -H "Authorization: Bearer ${KC_ADMIN_TOKEN}" \
  "${KC_BASE}/admin/realms/${KC_REALM}/users/${PERSONA_UID}/role-mappings/realm" \
  | jq -r '.[].name' | sort
# Beklenen liste: admin + default rollerin yanında
```

**Operator gate**: `admin` role listede görünüyor.

## Step 4 — Module-spesifik roller (admin yetmezse — opsiyonel)

```bash
# admin persona için module rolleri tek seferde JSON array hazırla
ROLES_TO_ASSIGN=("THEME" "ACCESS" "USERS" "SCHEMA")  # Step 1 listesinden mevcut olanları seç

ROLES_JSON_ARRAY="["
FIRST=true
for ROLE_NAME in "${ROLES_TO_ASSIGN[@]}"; do
  ROLE_JSON=$(curl -sk -H "Authorization: Bearer ${KC_ADMIN_TOKEN}" \
    "${KC_BASE}/admin/realms/${KC_REALM}/roles/${ROLE_NAME}" 2>/dev/null)
  if [ -n "$ROLE_JSON" ] && [ "$ROLE_JSON" != "null" ] && echo "$ROLE_JSON" | jq -e .id >/dev/null 2>&1; then
    [ "$FIRST" = false ] && ROLES_JSON_ARRAY="${ROLES_JSON_ARRAY},"
    ROLES_JSON_ARRAY="${ROLES_JSON_ARRAY}${ROLE_JSON}"
    FIRST=false
    echo "✓ ${ROLE_NAME} role bulundu"
  else
    echo "✗ ${ROLE_NAME} role yok (atlanacak)"
  fi
done
ROLES_JSON_ARRAY="${ROLES_JSON_ARRAY}]"

# Bulk atama
curl -sk -X POST \
  "${KC_BASE}/admin/realms/${KC_REALM}/users/${PERSONA_UID}/role-mappings/realm" \
  -H "Authorization: Bearer ${KC_ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${ROLES_JSON_ARRAY}"

# Doğrula
curl -sk -H "Authorization: Bearer ${KC_ADMIN_TOKEN}" \
  "${KC_BASE}/admin/realms/${KC_REALM}/users/${PERSONA_UID}/role-mappings/realm" \
  | jq -r '.[].name' | sort
```

## Step 5 — Re-login + token claim doğrulama (operatör browser + curl)

```bash
# 1. Browser: testai.acik.com → logout → re-login as d35-admin-persona
# 2. Yeni token al (curl ile decode et — sadece role claim doğrulaması)
PERSONA_USERNAME="d35-admin-persona"
PERSONA_PASSWORD="<RB-keycloak-admin-jwt.md Step 2'de set edilen şifre — kendi notundan oku>"

NEW_JWT=$(curl -sk -X POST \
  "${KC_BASE}/realms/${KC_REALM}/protocol/openid-connect/token" \
  --data-urlencode "client_id=frontend" \
  --data-urlencode "username=${PERSONA_USERNAME}" \
  --data-urlencode "password=${PERSONA_PASSWORD}" \
  --data-urlencode "grant_type=password" \
  --data-urlencode "scope=openid" | jq -r .access_token)

# Role claim'leri inspect — agent transcript'ine sadece role isimleri gidebilir, JWT body komple gitmesin
echo "$NEW_JWT" | cut -d. -f2 | base64 -d 2>/dev/null | jq '.realm_access.roles'
# Beklenen array: ["admin", "default-roles-platform-test", "offline_access", "uma_authorization", ...]
```

**Operator gate**: Yeni token claim'inde `admin` (veya module rolleri) var.

## Step 6 — Browser verify (operatör — UI run)

1. Browser cache + cookie temizle (incognito en güvenli)
2. testai.acik.com → login (`d35-admin-persona` / persona şifresi)
3. URL bar: `testai.acik.com/admin/data-access` (veya home → "Veri Erişimi" panel)
4. Beklenen: panel render etti (5 sekme: Kullanıcılar / Roller / Şirket / İş Birimi / Veri Yöneticileri)
5. **D35-3 evidence run** başlat (RB-faz-21-3-d35-3-ui-persona-checklist.md)

## Step 7 — Granted persona için minimum role (opsiyonel)

`d35-granted-persona` UI'da kendi tuple'ını görmek için sınırlı role yeterli:

```bash
# UID al
GRANTED_UID=$(vault kv get -field=granted_persona_uid kv/platform/d35-3 2>/dev/null \
  || echo "05178b50-9e4d-42a9-9373-f45a04ad094e")

# Sadece "ACCESS view" benzeri role (eğer mfe-access read-only path ayrı role kullanıyorsa).
# Eğer view = role yok = panel'e girer ama write gizli kalır pattern'i ise default rollerle kalsın.
# D35-3 evidence run sırasında panel render'ı OK, write disabled gösteren ekranı evidence'a ekle.
```

## Cleanup

D35-3 evidence runları bittikten sonra rolleri geri al (test temizliği):

```bash
# admin role'ünü kaldır
curl -sk -X DELETE \
  "${KC_BASE}/admin/realms/${KC_REALM}/users/${PERSONA_UID}/role-mappings/realm" \
  -H "Authorization: Bearer ${KC_ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "[${ADMIN_ROLE_JSON}]"

# Persona delete (RB-keycloak-admin-jwt.md Cleanup section)
```

## Pratik notlar

- **Default roles atanmış pattern**: Keycloak realm config'de `default-roles-platform-test` composite role var; yeni user create ederken bu otomatik geliyor ama module access vermez.
- **Composite role olasılığı**: `admin` realm role bir composite olabilir; içinde `realm-management/manage-users` gibi client role'ler var. Bizim için önemli olan **realm role isminin** mfe-host module guard'ında match etmesi.
- **mfe-host kaynak verify**: Eğer atama sonrası hâlâ `/unauthorized` → mfe-host `permissions.ts` veya `auth-context.tsx` mantığını oku, role string'i case-sensitive mi / namespace prefix var mı kontrol et.
- **Token cache**: SPA kendi token cache'ini tutar; Browser localStorage temizle veya hard refresh (`Cmd+Shift+R`).

## Fail troubleshooting

| Symptom | Sebep | Aksiyon |
|---|---|---|
| `/unauthorized` re-login sonrası da | Role atandı ama mfe-host farklı string match ediyor | mfe-host frontend kodu oku — role-name expectations |
| HTTP 404 role atama POST | Role realm'de yok | Step 1 listesinden mevcut isim kullan; case-sensitive |
| HTTP 403 admin token | Admin user'ın realm-management yetkisi yok | Master realm admin'iyle koş, persona realm değil |
| `admin` role atandı ama claim'de yok | Token TTL eski + cache | Logout + cache clear + re-login |

## References

- RB-faz-21-3-d35-3-keycloak-admin-jwt.md (persona create + JWT)
- RB-faz-21-3-d35-3-prereq-tuple-seed.md (OpenFGA tuple seed)
- RB-faz-21-3-d35-3-ui-persona-checklist.md (UI evidence checklist)
- ADR-0010 §2.5 (operator/agent boundary matrix)
- ADR-0011 §2.3 (boundary class — credential-read for admin token, state-mutation test cluster for role assignment)
- CLAUDE.md HARD RULE #7 (SSH+sudo+kubectl yetkisi); #9 (no fake work — atama doğrulanmadan iş bitti sayılmaz)
- mfe-host module guard kaynak (Faz 21.3 evidence ladder bağlantısı)
