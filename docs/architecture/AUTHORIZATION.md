# Authorization Architecture

## Katman Mimarisi

```
Katman 1: KEYCLOAK (Authentication)
  → Login, SSO, MFA, JWT (identity-only: sub, email)
  → Keycloak realm: serban
  → Port: 8081

Katman 2: OpenFGA (Authorization Engine)
  → Zanzibar tuple store, ReBAC model (9 tip, deny-wins, hierarchical)
  → check(), listObjects(), expand()
  → Port: 4000 (HTTP), 4001 (gRPC), 4002 (Playground)

Katman 3: PERMISSION-SERVICE (OpenFGA Hub) — D-003/D-008 FINAL
  → TupleSyncService: role → OpenFGA tuple sync (deny-wins resolution)
  → AuthzVersionService: cache invalidation version management
  → TupleSyncOutboxPoller: durable retry (SELECT FOR UPDATE SKIP LOCKED)
  → AuthorizationControllerV1: /authz/me, /check, /batch-check, /explain, /version, /catalog
  → AccessControllerV1: role CRUD
  → Port: 8090

Katman 4: DATA ENFORCEMENT (Her servis kendi içinde)
  → Hibernate @Filter (ORM seviyesi)
  → PostgreSQL RLS (DB seviyesi)
  → ScopeContext: company/project/warehouse/branch ID'leri
  → Her servis: OpenFgaAuthzService (common-auth) → direct OpenFGA SDK
  → Servisler check/listObjects için permission-service'e HTTP çağrısı YAPMAZ (C-008)

Katman 5: FRONTEND
  → @mfe/auth package
  → PermissionProvider, useZanzibarAccess, ZanzibarGate, ProtectedRoute
  → /api/v1/authz/* → Vite proxy → permission-service:8090
```

### Erişim Pattern'leri

**Backend servis check (fast path):**
```
user-service biz logic → OpenFgaAuthzService.check(...) → OpenFGA SDK → OpenFGA:4000
```

**Frontend kullanıcı sorgu (via hub):**
```
React → /api/v1/authz/me → Vite proxy → permission-service:8090 → OpenFGA + DB
```

**Role değişikliği (tuple sync):**
```
Admin UI → /api/v1/roles/{id}/permissions → permission-service
  → DB write + Outbox entry (transactional)
  → TupleSyncOutboxPoller (30s) → TupleSyncService
  → OpenFGA tuple write + AuthzVersionService.incrementVersion()
```

## Dev Mode (permitAll)

Dev ortamda Keycloak ve OpenFGA **gerekmez**. Veri filtreleme YAML'dan calısır.

### Konfigürasyon

```properties
# application-local.properties (her servis)
erp.openfga.enabled=false
erp.openfga.dev-scope.company-ids=1
erp.openfga.dev-scope.project-ids=1,2
erp.openfga.dev-scope.warehouse-ids=1
erp.openfga.dev-scope.super-admin=true
```

### Davranış

| Özellik | Dev Mode | Prod Mode |
|---------|----------|-----------|
| JWT validation | Kapalı (SecurityConfigLocal) | Aktif (Keycloak JWKS) |
| OpenFGA | Devre dışı | Aktif |
| ScopeContext kaynağı | YAML config | OpenFGA listObjects |
| Hibernate @Filter | **AKTİF** (YAML scope) | **AKTİF** (OpenFGA scope) |
| PostgreSQL RLS | **AKTİF** (NULL = all) | **AKTİF** (SET LOCAL) |
| Frontend permissions | permitAll (tümü true) | /v1/authz/me |

### Servis Başlatma

```bash
# Backend (tek servis)
cd backend/user-service
mvn spring-boot:run -Dspring.profiles.active=local

# Tüm stack (Docker)
cd backend
docker compose up

# OpenFGA ile (opsiyonel)
docker compose up openfga
./openfga/init.sh       # Store + model + seed
```

## OpenFGA Model

```
user → organization → company → project
                             → warehouse
                             → module
```

Model dosyası: `backend/openfga/model.fga`
Seed verileri: `backend/openfga/tuples-seed.json`
Playground: http://localhost:4002

### Check Örnekleri

```bash
# Store ID'yi al
STORE_ID=$(curl -s http://localhost:4000/stores | jq -r '.stores[0].id')

# Company erişim kontrolü
curl -X POST "http://localhost:4000/stores/$STORE_ID/check" \
  -H "Content-Type: application/json" \
  -d '{"tuple_key":{"user":"user:1","relation":"viewer","object":"company:1"}}'

# Kullanıcının erişebildiği şirketler
curl -X POST "http://localhost:4000/stores/$STORE_ID/list-objects" \
  -H "Content-Type: application/json" \
  -d '{"user":"user:1","relation":"viewer","type":"company"}'
```

## Backend Entegrasyonu

### Java SDK (common-auth)

```java
@Autowired
private OpenFgaAuthzService authzService;

// Check
boolean allowed = authzService.check("userId", "viewer", "company", "5");

// List objects
Set<Long> companyIds = authzService.listObjectIds("userId", "viewer", "company");

// Write tuple
authzService.writeTuple("userId", "admin", "company", "5");
```

### ScopeContext

```java
// Her request'te otomatik populate edilir (ScopeContextFilter)
ScopeContext ctx = ScopeContext.current();
ctx.allowedCompanyIds();  // [1, 5, 10]
ctx.canAccessCompany(5L); // true
ctx.superAdmin();         // false
```

### Entity @Filter

```java
@Entity
@FilterDef(name = "companyScope",
    parameters = @ParamDef(name = "companyIds", type = Long.class))
@Filter(name = "companyScope",
    condition = "company_id IN (:companyIds)")
public class User { ... }
```

## Frontend Entegrasyonu

### @mfe/auth Package

```tsx
// App root
<PermissionProvider httpGet={api.get} permitAll={isPermitAllMode()}>
  <App />
</PermissionProvider>

// Route guard
<ProtectedRoute requiredModule="AUDIT">
  <AuditPage />
</ProtectedRoute>

// Section guard
<ProtectedSection requiredModule="THEME">
  <ThemeAdminButton />
</ProtectedSection>

// Hook
const canViewUsers = useHasModule('USER_MANAGEMENT');
```

## Troubleshooting

### "403 Forbidden" hatası
1. Dev mode'da mı? → `erp.openfga.dev-scope.super-admin=true` kontrol et
2. JWT'de email claim var mı? → Test'te `.claim("email", "test@test.com")` ekle
3. ScopeContext null mı? → ScopeContextFilter registered mı kontrol et

### findAll() boş dönüyor
1. Hibernate filter aktif mi? → Log'da "Company scope filter enabled" var mı
2. company_id NULL olan kayıtlar var mı? → NULL company global veri, her zaman görünür
3. Dev scope doğru mu? → `erp.openfga.dev-scope.company-ids` kontrol et

### OpenFGA bağlantı hatası
1. Container çalışıyor mu? → `docker compose ps openfga`
2. Health check: `curl http://localhost:4000/healthz`
3. Store oluşturuldu mu? → `./openfga/init.sh`
4. Dev mode'da OpenFGA gerekmez → `erp.openfga.enabled=false`

### RLS filtreleme çalışmıyor
1. `FORCE ROW LEVEL SECURITY` aktif mi? → `02-rls-policies.sql` kontrol et
2. DB user table owner mi? → Owner RLS bypass eder, app_user kullan
3. `SET LOCAL` çalışıyor mu? → HikariCP transaction mode kontrol et

## İlgili Dosyalar

| Dosya | Açıklama |
|-------|----------|
| `backend/openfga/model.fga` | OpenFGA authorization modeli |
| `backend/openfga/init.sh` | Store + model + seed yükleme |
| `backend/openfga/migrate-permissions.py` | DB → OpenFGA migration |
| `backend/openfga/sync-from-keycloak.sh` | Keycloak role → tuple sync |
| `backend/common-auth/.../openfga/` | Java SDK wrapper |
| `backend/common-auth/.../scope/` | ScopeContext, RLS helper |
| `backend/devops/postgres/02-rls-policies.sql` | PostgreSQL RLS policy'ler |
| `web/packages/auth/` | @mfe/auth React package |
| `docs/02-architecture/adr/` | Mimari karar kayıtları |
