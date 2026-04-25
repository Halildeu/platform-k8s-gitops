# ADR-0013: Permission-Service Operational Scope as OpenFGA Hub

ID: ADR-0013
Status: Accepted
Date: 2026-04-14
Owner: @halil
Supersedes: (extends D-003 DCP from ADR-0010)
Related: D-001, D-002, D-003, D-008

---

## Context

ADR-0010'daki D-003 DCP kararı (2026-04-11), permission-service'in "REMOVED"
etiketinin aspirasyonel olduğunu ve gerçekte TRANSFORMED olduğunu belirledi.
Ancak bu kararın **operasyonel kapsamı** tam olarak belirlenmedi:

- Permission-service tam olarak hangi sorumlulukları üstlenir?
- Diğer servisler permission-service'e nasıl erişir?
- Hangi sorumluluklar permission-service'in DIŞINDADIR?

Canary rollout (Rev 19, CNS-20260414-001/002) sırasında şu drift'ler tespit edildi:

1. `/authz/check` ve `/batch-check` endpoint'leri core-data-service'te tanımlıydı
   ama gateway+Vite `/api/v1/authz/**` trafiğini permission-service'e yönlendiriyordu
2. `.claude/rules/backend-services.md` ve `.claude/rules/web-apps.md` hâlâ
   "permission-service is REMOVED" diyordu (D-003 ile çelişki)
3. Bazı dokümanlar hub rolünü belirtmiyordu (SYSTEM-OVERVIEW, DOMAIN-MAP, INDEX)

Bu kararın amacı permission-service'in operasyonel kapsamını **resmî olarak**
kayıt altına almak ve tüm dokümantasyonu tutarlı hale getirmektir.

---

## Decision

Permission-service, **OpenFGA Sync Hub + User-Facing Authz Query Hub** rolünü
üstlenir. Sorumlulukları 3 kategoride tanımlıdır:

### Kategori 1: WRITE/SYNC (OpenFGA Tuple Yönetimi)

- **TupleSyncService**
  - Role değişikliğinde role_permissions tablosundan OpenFGA tuple'ları üretir
  - Deny-wins resolution uygular (DENY > MANAGE > ALLOW > VIEW)
  - Permission → tuple mapping:
    - MODULE + MANAGE → `(can_manage, module)`
    - MODULE + VIEW → `(can_view, module)`
    - MODULE + DENY → `(blocked, module)`
    - ACTION + ALLOW → `(allowed, action)`
    - REPORT + MANAGE → `(can_edit, report)`
  - `propagateRoleChange(roleId)`: rolle atanmış tüm kullanıcıların tuple'larını refresh eder
  - `syncScopeTuples(userId, ...)`: scope (company/project/warehouse/branch) tuple'ları

- **TupleSyncOutboxPoller**
  - `@Scheduled` ile 30s aralıkla PENDING outbox entry'lerini işler
  - `SELECT FOR UPDATE SKIP LOCKED` ile multi-instance çakışması engellenir
  - Max 5 deneme, başarısızlık → FAILED (dead letter)
  - **Metric:** `tuple_sync_outbox_failed_total` Counter (B4, Rev 19)

- **AuthzVersionService**
  - `authz_sync_version` tablosunda monotonic version
  - Tuple değişikliğinden sonra `incrementVersion()` → cache invalidation trigger

### Kategori 2: USER-FACING QUERY (Frontend için Authz API)

- **AuthorizationControllerV1** (`/api/v1/authz/**`)
  - `GET /me` → Kullanıcının tüm yetki snapshot'ı (modules, actions, reports, scopes, roles)
  - `GET /version` → Cache invalidation version
  - `POST /check` → Tek object-level kontrol (B1, Rev 19)
  - `POST /batch-check` → Toplu object-level kontrol (max 20)
  - `POST /explain` → Rol/scope kaynaklı deny açıklaması
  - `POST /object-explain` → OpenFGA expand (object-level açıklama, B1 Rev 19)
  - `GET /catalog` → Permission kataloğu (modules + actions + reports)
  - `GET /modules` → Modül listesi
  - `POST /users/{userId}/assignments` → Kullanıcıya rol+scope ata
  - `GET /users/{userId}/roles` → Kullanıcının rolleri

### Kategori 3: ROLE/PERMISSION CRUD

- **AccessControllerV1** (`/api/v1/roles/**`)
  - Rol CRUD (create, read, update, delete, clone)
  - Rol-kullanıcı atama
  - Rol izin güncelleme (PUT `/roles/{id}/permissions`)

- **PermissionControllerV1** (`/api/v1/permissions/**`)
  - Permission katalog yönetimi
  - Permission atama sorguları

---

## Kapsam DIŞI Sorumluluklar (EXPLICIT EXCLUSIONS)

| Sorumluluk | Sahip | Gerekçe |
|-----------|-------|---------|
| Authentication (login, JWT üretimi) | **Keycloak** | D-002 FINAL |
| Check operations from backend services | **common-auth/OpenFgaAuthzService** | Her servis OpenFGA SDK'yı doğrudan kullanır (R-006, C-008) |
| Data enforcement (query filtering) | **Her servisin Hibernate @Filter + RLS** | ADR-0011 |
| Business domain data (user, company, variant) | **Domain servisleri** | Bounded context |
| ScopeContext oluşturma | **common-auth/ScopeContextFilter** | Her servis kendi filter chain'inde |

---

## Servisler Arası Erişim Pattern'leri

### ✅ Doğru Pattern (C-008 compliance)

```
user-service business logic:
  OpenFgaAuthzService.check(userId, "viewer", "company", "10")
    └─> OpenFGA SDK → OpenFGA (port 4000) direct call
```

```
Frontend:
  GET /api/v1/authz/me
    └─> Vite proxy → permission-service (port 8090)
      └─> TupleSyncService/AuthzVersionService + OpenFGA query
```

### ❌ Yanlış Pattern (C-008 violation)

```
user-service business logic:
  HTTP POST permission-service:8090/authz/check
    └─> Adds unnecessary latency + SPOF risk
```

---

## Kısıtlamalar (HARD CONSTRAINTS)

| ID | Kısıt | Kapsam |
|----|-------|--------|
| C-005 | Permission-service kaldırılamaz. TupleSyncService/AuthzVersionService başka yerde duplicate edilemez | `backend/permission-service/**` |
| C-008 | Servisler check/listObjects için OpenFgaAuthzService kullanır — permission-service'e HTTP çağrısı YAPMAZ | `backend/*-service/**` |
| C-004 | Vite proxy `/api/v1/authz|/roles|/permissions` → localhost:8090. Gateway üzerinden yönlendirme YOK | `web/apps/mfe-shell/vite.config.ts` |

---

## Consequences

### Pozitif
- Permission-service rol sorumluluğu net (hub, not proxy)
- Servisler arası latency azalır (direct OpenFGA, HTTP hop yok)
- Single source of truth: permission-service tuple yazma, OpenFGA saklama
- Canary izleme noktası tek yerde (metric/alert üretimi)

### Negatif
- Servisler common-auth'a bağımlı (OpenFgaAuthzService dependency)
- Permission-service down olursa rol değişiklikleri senkronize edilemez
  (mitigasyon: outbox pattern + dead letter)

### Nötr
- D-003'teki "TRANSFORMED" etiketi bu ADR ile formalize edildi
- Tüm ilgili dokümantasyon (backend/web rules, SYSTEM-OVERVIEW, DOMAIN-MAP, INDEX)
  bu karara uyacak şekilde güncellendi (Rev 19, 2026-04-14)

---

## Reddedilen Alternatifler

| ID | Alternatif | Reddetme Sebebi |
|----|-----------|-----------------|
| R-006 | Servisler check için permission-service'e HTTP çağrısı yapsın | Latency + SPOF; OpenFGA SDK zaten direct access sağlıyor |
| (implicit) | OpenFGA'yı frontend'den direkt sorgula | Frontend OpenFGA SDK'ya bağımlı olmamalı; permission-service abstraction katmanı gerekli |
| (implicit) | Permission-service'i "REMOVED" tut, sadece sync için kullan | Kullanıcı-facing `/authz/me`, `/explain` için yine de gerekli |

---

## Links

- **Karar:** `decisions/topics/zanzibar-openfga.v1.json` D-008
- **ADR-0010:** OpenFGA Authorization (D-003 DCP kaynağı)
- **ADR-0011:** Data Enforcement (RLS + Filter)
- **ADR-0012:** JWT Identity Only
- **Master Plan Rev 19:** `.claude/plans/zanzibar-master-plan.md`
- **İstişare:** CNS-20260414-001 (482K token), CNS-20260414-002 (212K token)
- **Doğrulama:** `backend/scripts/doctor-zanzibar.sh --quick`
