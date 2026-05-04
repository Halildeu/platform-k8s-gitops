# OpenFGA Model Contract — Authorization Source-of-Truth

> **Codex AGREE Session 37** (2026-05-04, thread `019df2bf-d910-7920-b888-cb21a4f71059`):
> "OpenFGA tuple pattern'i ürün kontratı olmalı. Relation isimleri dağılırsa silent
> deny veya accidental allow oluşur."
>
> **2026-05-04 truth-correction (Codex thread `019df310` follow-up)**: PR #348 B0a
> deneyiminde `OpenFGA Model Drift Gate (Faz 19.11 Step 4)` kanıtladı ki
> bootstrap local fixture VE upstream `platform-backend/backend/openfga/model.fga`
> her ikisi de canonical inheritance içermiyor. Bu doküman target-state contract'ı
> tanımlar; "Current implementation status" bölümü bunun şu an tam olarak
> implement edilmediğini açıkça belirtir.

## Current implementation status — 2026-05-04

Empirical drift gate evidence shows that both:
- `bootstrap/local-fixtures/openfga/model.fga`
- upstream `platform-backend/backend/openfga/model.fga`

do **not** currently encode `organization:default#admin` inheritance into
`module:*`, `action:*`, or `report:*` relations.

Therefore, `organization:default#admin@user:<id>` as a single tuple is the
**target-state super-admin contract**, not the current model-enforced behavior.

Current production access for known admins may be satisfied by one or more
compatibility paths, such as explicit module/action/report tuples, backend-side
superAdmin handling, existing role/bootstrap grants, or legacy tuple patterns.
Do not claim single-tuple sufficiency until live tuple export + backend check-path
evidence proves it.

Target-state migration requires a platform-backend OpenFGA model revision,
tuple/link migration, model_id rollout, and dual-read allow/deny smoke before
this fixture can become a hard gate.

## Target-State Canonical Super-Admin Tuple

Target-state tuple:

```
organization:default#admin@user:<users_db_id>
```

This is the **desired future contract**. It is not yet guaranteed by the current
upstream OpenFGA model.

Örnek (prod, halen mevcut tuples — test smoke + live audit kanıtı):

```
organization:default | admin | user:1201    ← admin@example.com
organization:default | admin | user:1204    ← halil.kocoglu@serban.com.tr (Session 37)
organization:default | admin | user:48102a7f-5144-4e5b-8e01-4b869fd73511    ← KC sub UUID
```

Bu tuple'lar mevcut, ama **canonical inheritance ile çalışmıyor** çünkü model
inheritance içermiyor. Dolayısıyla canlı erişim başka bir mekanizma ile
sağlanıyor (yukarıda compatibility paths listesi).

### Target-state inheritance (planned, not current)

When the platform-backend OpenFGA model is migrated to the target schema, the
inheritance rule will be:

```
[Type] organization
  relations:
    define admin: [user]              ← canonical super-admin grant

[Type] module
  relations:
    define org: [organization]
    define can_view: [user] or admin from org
    define can_manage: [user] or admin from org

[Type] action
  relations:
    define org: [organization]
    define allowed: [user] or admin from org

[Type] report
  relations:
    define org: [organization]
    define can_view: [user] or admin from org
```

After model migration, every `module/action/report` instance will declare its
parent `organization` via the `org` relation, and a single
`organization:default#admin@user:<id>` tuple will resolve to all module/action/
report access via `admin from org` inheritance.

(Schema rev için `docs/authz/openfga-model-rev-history.md` referans, model
migration runbook ile. Migration runbook draft: Sprint D prep — bu repo.)

## NE DEĞİLDİR

### `user:920001` 39 module/action/report tuple = super-admin DEĞİL

Session 37 audit'inde keşfedilen önemli yanılgı: prod'da `user:920001`
adına 39 tuple vardı:

```
module:USER_MANAGEMENT | can_manage | user:920001
module:ACCESS | can_manage | user:920001
... (toplam 39 tuple — module/action/report her biri için ayrı)
```

Bu kullanıcı **super-admin DEĞİL**. Sadece her modüle/aksiyon/rapora **explicit
tuple** verilmiş bir global role. Bu pattern:

- Çok daha **kırılgan**: yeni bir module type eklendiğinde her user için tuple
  güncellenmeli
- **Bakım maliyeti yüksek**: bootstrap-admin-assigner job'ı bu 39 tuple'ı
  her user için yazmalı
- **Audit zor**: hangi user hangi modülde hangi seviyede sorusunun cevabı
  39 row tarama
- **Migration riski**: schema rev sırasında relation rename olunca bu tuple'lar
  bayat kalır

**Doğru pattern:** Tüm super-admin'ler için **TEK** `organization:default#admin@user:<id>`
tuple'ı kullan. 39 tuple pattern'i deprecation listesinde — Codex P1 schema
migration sprint'inde temizlenecek.

### KC realm role `ADMIN`/`admin` ≠ OpenFGA super-admin

Session 37'de bulunan başka bir yanılgı: Keycloak realm rollerini (`ADMIN`,
`admin`) eklemek halil için yeterli sanılmıştı. Backend authz check'leri
**OpenFGA tuple'larına** bakar, JWT realm roles'a değil. KC roles sadece
**JWT claim** olarak token'a eklenir ama backend permission gate'i OpenFGA'dadır.

KC roles şunlar için kullanılır:
- Frontend module visibility hint (`Yönetim` menü açma kararı)
- Backend `@PreAuthorize("hasRole('ADMIN')")` annotation'ı (sadece bazı
  legacy endpoint'lerde)

Backend'in çoğunluğu OpenFGA üzerinden gider:
```java
permissionService.check("module:USER_MANAGEMENT", "can_manage", "user:" + currentUserId);
// → OpenFGA query → bool
```

## Yeni admin onboarding — atomic pattern

Yeni bir kullanıcıyı **super-admin yapmak** için minimum atomic adım:

```sql
-- 1. users_db.users INSERT (KC sub'tan veya manuel)
INSERT INTO users (email, name, role, password, ...) VALUES
  ('newuser@serban.com.tr', 'New User', 'ADMIN', '<bcrypt-placeholder>', ...);
```

```bash
# 2. KC realm + frontend client roles (admin@example.com pattern ile birebir)
PASS=$(...)
TOKEN=$(...)
USER_ID=$(curl -X POST KC users RETURNING id)
curl -X POST KC role-mappings/realm  -d '[{"id":"<ADMIN-id>","name":"ADMIN"},{"id":"<admin-id>","name":"admin"},{"id":"<viewer-id>","name":"viewer"}]'
curl -X POST KC role-mappings/clients/<frontend-cid>  -d '<12 client roles json>'
```

```sql
-- 3. OpenFGA super-admin tuple (TEK!)
INSERT INTO tuple (store, object_type, object_id, relation, _user, user_type, ulid, inserted_at)
VALUES (
  '<store_id>',
  'organization', 'default', 'admin',
  'user:<users_db_id>',
  'user',
  '<ulid>',
  now()
);
```

```sql
-- 4. (Opsiyonel) permission_db.user_role_assignments — Zanzibar geçişinde
-- gerekecek; şu an OpenFGA dominant. Detail için
-- docs/adr/0010-zanzibar-cutover.md
```

**5 manuel adım** (KC user create → realm role → client role → users_db INSERT
→ OpenFGA tuple) bir gün **idempotent saga endpoint** ile tek API call
olacak (Codex P1 — `POST /api/v1/admin/users/onboard`). Şu an:

- Manual SQL = **break-glass** (Session 37'de halil/sezer için yapıldı —
  doküman: `docs/runbooks/RB-admin-onboarding-manual.md` — TODO)
- API = ileri faz (P1)

## Smoke test — super-admin allow/deny

Yeni admin grant doğrulamak için:

```bash
TOKEN=<admin-jwt>

# Allow
curl -H "Authorization: Bearer $TOKEN" https://ai.acik.com/api/v1/users
# → 200, kullanıcı listesi

curl -H "Authorization: Bearer $TOKEN" https://ai.acik.com/api/v1/authz/me
# → modules: { USER_MANAGEMENT: "MANAGE", ACCESS: "MANAGE", ... }

# Sentetic deny (super-admin değil bir kullanıcı için aynı çağrı)
TOKEN_REGULAR=<regular-user-jwt>
curl -H "Authorization: Bearer $TOKEN_REGULAR" https://ai.acik.com/api/v1/users
# → 403 user-read yetkisine sahip olmalısınız
```

Smoke fixtures: `tests/openfga/fixtures/super-admin-allow-deny.yaml` —
gelecek PR'da CI gate olarak entegre edilecek.

## Truth hierarchy

OpenFGA model ↔ permission-service kod ↔ frontend module gate ilişkisi:

```
[Source of truth: OpenFGA model (contract)]
       ↓
[permission-service Java code]
       ↓
[/api/v1/authz/me response]
       ↓
[Frontend hasModule() gate]
```

Bu yönde değişiklik **schema rev** ile yapılır (model migration runbook).
Tersine değişiklik (frontend module ekle → backend tuple ekle → model expand)
**RED** verdict: contract violation.

## Migration runbook (Codex P1)

Şema değişikliği gereken durumlarda:

```
1. Export old model + tuples (kanıtlı snapshot)
2. Write new model with relation aliases (geri uyumluluk window)
3. Vault model_id rotate (hot)
4. Dual-read smoke (old + new aynı sonucu vermelidir)
5. Backfill tuples to new relation names
6. Sunset old aliases (next sprint)
7. Prod repeat
```

Detay: `docs/runbooks/RB-openfga-schema-rev.md` (TODO — P1 sprint).

## İlişkili belgeler

- ADR-0010: Zanzibar/OpenFGA adoption decision
- `docs/authz/openfga-model-rev-history.md` (TODO — schema rev log)
- `docs/runbooks/RB-admin-onboarding-manual.md` (TODO — break-glass runbook)
- `docs/runbooks/RB-openfga-schema-rev.md` (TODO — migration runbook)
- `permission-service` Java source: `DefaultAdminRoleAssignmentInitializer`,
  `OpenFgaCheckService` (backend repo)

## Değişiklik geçmişi

| Tarih | Versiyon | Notlar |
|---|---|---|
| 2026-05-04 | 1.0 | İlk versiyon — Session 37 audit + Codex AGREE 019df2bf. Halil/Sezer manuel onboarding'in açığa çıkardığı kontrat boşluğunu kapatıyor. Schema rev + migration runbook P1 sprint'te eklenecek. |
