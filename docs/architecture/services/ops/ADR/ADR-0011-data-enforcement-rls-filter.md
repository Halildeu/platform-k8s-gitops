# ADR-0011: Dual Data Enforcement (Hibernate @Filter + PostgreSQL RLS)

ID: ADR-0011
Status: Accepted
Date: 2026-03-29
Owner: @team/platform

## Context

ERP'de company/project/warehouse bazli veri izolasyonu gerekli.
Developer WHERE clause'u unutursa siirketler arasi veri sizintisi olusabilir.
Mevcut durum: controller seviyesinde manuel check (canAccessCompany) — unutulabilir.

## Decision

**Cift katmanli veri zorlamasi: Hibernate @Filter + PostgreSQL RLS.**

### Katman 1: Hibernate @Filter
- companyId kolonu olan entity'lere `@FilterDef` + `@Filter` annotation
- `ScopeFilterInterceptor` her request'te Session'da filter'i aktif eder
- ScopeContext'ten (OpenFGA veya YAML) izinli company ID'leri alinir
- JPQL/Criteria query'lere otomatik WHERE eklenir

### Katman 2: PostgreSQL RLS
- `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` + policy
- `SET LOCAL app.scope.company_ids = '1,5,10'` ile session-scoped
- Native query, entityManager.find, direct JDBC bile filtrelenir
- Defense-in-depth: Hibernate filter bypass edilse bile RLS yakalar

### Dev Mode
- ScopeContext YAML'dan populate edilir (erp.openfga.dev-scope.company-ids=1)
- Filtreler dev'de de AKTIF — developer hatasi dev'de bile yakalanir
- SuperAdmin: tum filtreler bypass

## Alternatives Considered

| Secenek | Karar | Neden |
|---------|-------|-------|
| Sadece Hibernate @Filter | Reddedildi | Native query'leri kapsamaz |
| Sadece RLS | Reddedildi | Connection pooling komplikasyonu, ORM integration zayif |
| AbstractRoutingDataSource (schema-per-tenant) | Ertelendi | Operasyonel karmasiklik, 100+ tenant'ta olceklenmez |
| Controller-level check (mevcut) | Reddedildi | Developer unutabilir, bypass-proof degil |

## Consequences

**Positive:**
- Developer hatasi bypass-proof (RLS DB seviyesinde zorlar)
- Dev'de bile aktif (erken bug tespiti)
- Mevcut kod degisikligi minimal (@Filter annotation + interceptor)

**Negative:**
- entityManager.find(id) Hibernate filter'i bypass eder (RLS yakalar)
- RLS performans etkisi izlenmeli (company_id index ZORUNLU)
- @BypassScopeFilter annotation disiplini gerekli (audit loglu)

## Implementation

```
ScopeContextFilter (servlet filter)
  → OpenFGA listObjects veya YAML → ScopeContext populate
  → ScopeContextHolder (ThreadLocal)

ScopeFilterInterceptor (HandlerInterceptor)
  → Hibernate Session.enableFilter("companyScope")
  → RlsScopeHelper.applyScope(connection, ctx)

Entity:
  @FilterDef + @Filter("companyScope", "company_id IN (:companyIds)")
```

## Links

- Related: ADR-001-openfga-authorization.md
- Related: ADR-003-jwt-identity-only.md
