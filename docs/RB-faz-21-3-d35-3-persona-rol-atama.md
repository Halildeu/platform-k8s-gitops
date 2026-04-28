# RB Faz 21.3 D35-3 Prereq — Persona Authorization (OpenFGA superAdmin tuple, operatör boundary)

> **Tetikleyici**: D35-3 UI persona evidence run öncesi. `d35-admin-persona` Keycloak'ta yaratıldı + Keycloak realm role default'lar var, ama frontend `/v1/authz/me` `superAdmin: false` + boş `modules: {}` döndüğünden `/unauthorized`'a redirect ediliyor.
> **Authority**: agent yapabilir test cluster'da (CLAUDE.md HARD RULE #7 + ADR-0010 §2.5 + ADR-0011 §2.3 → `state-mutation (test cluster)` class, user-approval gerekmez). Operator-pending olan **sadece psql/user-service email lookup** (kullanıcı boundary'sinde lokal credential).
> **Bağlam (2026-04-28)**: testai.acik.com → `Modül erişimi yok — Bu modül rolünüzde tanımlı değil. Gerekli modül: THEME` ekranı. d35-admin-persona Keycloak UID `cbc9a869-1833-4d9c-beea-a9fa52fa851e`, email `d35-admin@example.com`.

## Kritik bulgu: Authorization yolu

**Frontend authorization yolu Keycloak realm rolleri DEĞİL.** Doğru flow:

1. Kullanıcı Keycloak'tan JWT alır (rolleriyle birlikte ama frontend ROL ÇEKMEZ)
2. Frontend `GET /api/v1/authz/me` çağırır (permission-service)
3. Permission-service JWT'den **numeric userId** çözer (sırayla: `userId` claim, `uid` claim, `sub` claim numeric mi, email fallback)
4. Permission-service OpenFGA `/check` ile `user:<numericId>` `admin` `organization:default` sorar
5. Allowed = true ise response'da `superAdmin: true` → frontend tüm modül kapılarını açar
6. Allowed = false ise her modül için `module:<NAME> can_manage|can_view` ayrı check → tek tek module access

**Sonuç**: Tek bir OpenFGA tuple (`organization:default#admin`) seed'i ile persona'ya tüm modül access verilebilir.

## Boundary

- **Yapma**: Production OpenFGA tuple seed (kullanıcı-only, dual-clearance)
- **Yap**: Test cluster'da agent SSH+kubectl+OpenFGA write yapabilir; Codex consensus (`019dd409` PARTIAL/REVISE) zaten `module:ACCESS` tuple seed için yetki vermişti — bu runbook aynı kapsamda **organization:default#admin** ekliyor.
- **Operator-only adım**: persona'nın **numeric userId**'sini bulma (psql veya user-service email lookup). Numeric ID Vault'a kaydedilir, agent transcript'ine literal değer girmesin.

## Prereq

- [ ] `d35-admin-persona` Keycloak'ta var (RB-keycloak-admin-jwt.md Step 2 tamamlandı)
- [ ] Persona email = `d35-admin@example.com`
- [ ] OpenFGA STORE_ID + MODEL_ID Vault'tan okunabilir (`vault kv get kv/platform/openfga`)
- [ ] OpenFGA endpoint reachable (test cluster in-cluster service veya port-forward)

## Step 1 — Persona'nın numeric userId'sini bul (operatör koşar)

Backend `AuthenticatedUserLookupService` JWT → numeric userId çözüm sırası:
1. JWT `userId` claim (numeric)
2. JWT `uid` claim
3. JWT `sub` claim parse-as-long (Keycloak UUID değil)
4. Email lookup → local `users` table veya user-service `/api/users/by-email/{email}`

**Yol A: psql ile reports_db / auth_db users table**

```bash
# Operatör staging-sw'de psql ile:
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/permission-service -- env | grep -E 'DB_|DATABASE_URL' | head -5"
# DB host/db/user/password bilgisini al

# permission-service hangi tabloda lookup yapıyor — 'users' tablosu (default).
# DB'ye bağlanıp email ile id çek:
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec -i deploy/permission-service -- psql \"\${DATABASE_URL}\" \
  -c \"SELECT id, email FROM users WHERE email = 'd35-admin@example.com' LIMIT 1\""
# Beklenen: id=<numeric>, email=d35-admin@example.com

# Veya direkt PG cluster'a bağlanma (eğer permission-service CLI'sı yoksa):
ssh halil@staging-sw "docker exec platform-pg-test psql -U postgres -d permission_db \
  -c \"SELECT id, email FROM users WHERE email = 'd35-admin@example.com'\""
```

**Yol B: user-service REST endpoint (varsa)**

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/user-service -- curl -sf \
  http://localhost:8080/api/users/by-email/d35-admin@example.com | jq .id"
```

**Yol C: Persona register et (eğer DB'de hiç yoksa)**

D35-2-full'ün geçtiği bağlam: persona Keycloak'tan token alabildi → `/api/v1/access/scope` POST (admin) PASS oldu. Demek ki numeric userId resolution **bir şekilde** çalıştı. Önce Yol A/B ile numeric userId'yi bul; bulunamazsa user-service / permission-service register endpoint'inden persona kaydet.

**Operator gate**: `ADMIN_NUMERIC_UID` (numeric integer) elde edildi ve Vault'a kaydedildi:

```bash
vault kv patch kv/platform/d35-3 admin_persona_numeric_uid="${ADMIN_NUMERIC_UID}"
```

## Step 2 — `organization:default#admin` tuple seed (agent veya operatör)

```bash
# Env set
ADMIN_NUMERIC_UID=$(vault kv get -field=admin_persona_numeric_uid kv/platform/d35-3)
STORE_ID=$(vault kv get -field=store_id kv/platform/openfga)
MODEL_ID=$(vault kv get -field=model_id kv/platform/openfga)

# Agent SSH üzerinden test cluster OpenFGA endpoint'e write
ssh halil@staging-sw "curl -sf -X POST \
  http://10.44.3.209:8080/stores/${STORE_ID}/write \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  \"authorization_model_id\": \"${MODEL_ID}\",
  \"writes\": {
    \"tuple_keys\": [
      {\"user\": \"user:${ADMIN_NUMERIC_UID}\", \"relation\": \"admin\", \"object\": \"organization:default\"}
    ]
  }
}
EOF
"
# Beklenen: HTTP 200 + body {} (idempotent — tuple varsa 409 sessizce yutulur)
```

**Doğrulama**:

```bash
ssh halil@staging-sw "curl -sf -X POST \
  http://10.44.3.209:8080/stores/${STORE_ID}/check \
  -H 'Content-Type: application/json' \
  -d \"{
    \\\"authorization_model_id\\\":\\\"${MODEL_ID}\\\",
    \\\"tuple_key\\\":{\\\"user\\\":\\\"user:${ADMIN_NUMERIC_UID}\\\",\\\"relation\\\":\\\"admin\\\",\\\"object\\\":\\\"organization:default\\\"}
  }\""
# Beklenen: {"allowed":true}
```

## Step 3 — `/v1/authz/me` end-to-end doğrula (agent koşar)

Persona JWT al + permission-service /authz/me çağır:

```bash
# Operatör'den JWT_ADMIN export edildi (RB-keycloak-admin-jwt.md Step 4)
[ -z "$JWT_ADMIN" ] && echo "✗ JWT_ADMIN env set değil — operatör'den iste" && exit 1

# permission-service in-cluster çağrı
ssh halil@staging-sw "curl -sf \
  -H \"Authorization: Bearer \$JWT_ADMIN\" \
  http://10.44.3.209:8095/api/v1/authz/me | jq '{superAdmin, modules, allowedModules, roles}'"
# Beklenen: {"superAdmin": true, "modules": {...}, "allowedModules": [...], "roles": [...]}
```

**Gate**: `superAdmin: true`. Frontend artık tüm modül kapılarını bypass eder.

## Step 4 — Browser re-login + UI doğrula (operatör)

1. Browser cache + cookie temizle (incognito)
2. testai.acik.com → login (`d35-admin-persona` / persona şifresi)
3. URL bar: `testai.acik.com/admin/data-access`
4. Beklenen: 5-tab "Veri Erişimi" panel render etti (Kullanıcılar / Roller / Şirket / İş Birimi / Veri Yöneticileri)
5. **D35-3 evidence run** başlat (RB-faz-21-3-d35-3-ui-persona-checklist.md)

## Step 5 — Granted persona için minimum tuple (opsiyonel)

`d35-granted-persona` UI'da kendi tuple'ını görmek için sınırlı access yeterli. **superAdmin verme**; sadece module-spesifik:

```bash
GRANTED_NUMERIC_UID=$(vault kv get -field=granted_persona_numeric_uid kv/platform/d35-3)

ssh halil@staging-sw "curl -sf -X POST \
  http://10.44.3.209:8080/stores/${STORE_ID}/write \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  \"authorization_model_id\": \"${MODEL_ID}\",
  \"writes\": {
    \"tuple_keys\": [
      {\"user\": \"user:${GRANTED_NUMERIC_UID}\", \"relation\": \"can_view\", \"object\": \"module:ACCESS\"}
    ]
  }
}
EOF
"
```

Bu tuple ile granted persona `/access/*` route'larına view-only erişebilir. write'lar gizli kalır.

## Step 6 — Cleanup (D35-3 evidence sonrası)

```bash
# Admin tuple kaldır
ssh halil@staging-sw "curl -sf -X POST \
  http://10.44.3.209:8080/stores/${STORE_ID}/write \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  \"authorization_model_id\": \"${MODEL_ID}\",
  \"deletes\": {
    \"tuple_keys\": [
      {\"user\": \"user:${ADMIN_NUMERIC_UID}\", \"relation\": \"admin\", \"object\": \"organization:default\"}
    ]
  }
}
EOF
"

# Persona delete (RB-keycloak-admin-jwt.md Cleanup section)
```

## OpenFGA model referansı

`backend/openfga/model.fga` tipleri:

```
type user

type organization
  relations
    define admin: [user]            <-- BURASI: superAdmin = organization:default#admin
    define member: [user]

type module
  relations
    define can_edit: [user] but not blocked
    define can_manage: [user] or can_edit but not blocked
    define can_view: [user] or can_manage but not blocked
    define blocked: [user]

# ... company, project, warehouse, branch, action, report types
```

Module sabitleri (`PermissionCatalogService`):
- `USER_MANAGEMENT`, `ACCESS`, `AUDIT`, `REPORT`, `WAREHOUSE`, `PURCHASE`, `THEME`

## permission-service authz/me logic referansı

`AuthorizationControllerV1.doGetMe()` (line 105+):
- Line 134-138: `isSuperAdmin = checkOrganizationAdmin(numericUserId) || permissions.contains("admin")`
- Line 494-512: modules map populate (RolePermission → effectiveGrants → MODULE filter)
- Line 534-536: per-module sequential `can_manage` then `can_view` check
- Line 705-710: `superAdmin: true` ise tüm modüller `MANAGE` level'a fallback

## Fail troubleshooting

| Symptom | Sebep | Aksiyon |
|---|---|---|
| `/v1/authz/me` `superAdmin: false` rağmen tuple yazıldı | Numeric userId yanlış | Step 1'i tekrar koş; psql → `SELECT id FROM users WHERE email = ...` |
| `/check` HTTP 400 invalid_authorization_model_id | MODEL_ID Vault'tan eski | Vault'tan tekrar oku, fresh model ID al |
| Browser hâlâ /unauthorized | Token cache eski | Logout + browser cache clear + re-login (token TTL 5dk) |
| permission-service authz/me HTTP 401 | JWT TTL geçti | RB-keycloak-admin-jwt.md Step 4'i koş, fresh JWT al |
| `users` table'da persona yok | DB lookup fail | Persona register edilmemiş; user-service register endpoint koş veya manuel INSERT |

## Boundary declaration (ADR-0011 §2.3)

This RB execution includes (operator boundary):
- [x] state-mutation (test cluster) — OpenFGA tuple write on test store
- [ ] credential-read (psql password — operatör boundary, agent transcript'inde değil)

User-approval gerekmez (Codex consensus + Kural #7 + Codex `019dd409` PARTIAL/REVISE — test cluster tuple write agent yetkisi).

## References

- [RB-faz-21-3-d35-3-keycloak-admin-jwt.md](RB-faz-21-3-d35-3-keycloak-admin-jwt.md) (persona create + JWT)
- [RB-faz-21-3-d35-3-prereq-tuple-seed.md](RB-faz-21-3-d35-3-prereq-tuple-seed.md) (`module:ACCESS` tuple seed; bu runbook organization:default#admin ile complement)
- [RB-faz-21-3-d35-3-ui-persona-checklist.md](RB-faz-21-3-d35-3-ui-persona-checklist.md) (UI evidence checklist)
- ADR-0010 §2.5 (operator/agent boundary matrix)
- ADR-0011 §2.3 (boundary class)
- CLAUDE.md HARD RULE #7 (SSH+sudo+kubectl yetkisi); #9 (no fake work — superAdmin: true doğrulanmadan iş bitti sayılmaz)
- `backend/openfga/model.fga` (organization#admin + module relations)
- `permission-service/AuthorizationControllerV1.java` (line 134-138 superAdmin determination)
- `permission-service/AuthenticatedUserLookupService.java` (JWT → numeric userId resolution)
- Codex thread `019dd409` PARTIAL/REVISE (test OpenFGA tuple write yetkisi)
