# Reporting Refactor Plan — 2026-05-14

> **Status**: ACTIVE | **Owner**: Platform-Eng (Claude + Codex cross-AI) | **Started**: 2026-05-14 | **Session**: 49
>
> **Canlı doküman**: Her adım tamamlandıkça bu plan güncellenir. Adım statüsü, kanıt, sapma, yeni risk plana yazılır.
>
> **Codex thread (ana)**: `019e258f-1d09-72f1-8385-245eedde08f6`
>
> **İlgili kontratlar**: ADR-0005 / ADR-0006 / ADR-0008 / ADR-0009 / ADR-0011 / Program 1 / Program 2 / Program 8 / mssql-pg-data-contract.md

---

## 1. Hedef

Reporting yüzeyini (frontend MFE + backend report-service + schema-service + etl-worker) standartlaştır, governance risk gate'lerini kapat, mevcut kontratları (Faz 16.0 + Program 2/8 + ADR-0005/8) implement et, **Workcube canlı production'a güvenli + audit'lenebilir + composite-tenant-safe** hale getir.

Hedef olmayan: yeni reporting feature ekleme, performance optimization (P3 backlog), MFE component library full refactor.

---

## 2. Scope

### In Scope (bu plan)

- Hafta 1 risk gate'leri: Workcube exposure, Alert/Schedule authz, HR mock fallback, FE Excel export
- Program 2 TenantBoundaryGuard implement (PR #102+)
- Program 8 SchemaTruthService implement (PR #95-#100)
- ADR-0012 alt-spec: schema-service `/internal/cache/refresh` + `?scope=reporting`
- ADR-0008 §2.4 revision: query-shape metrics extension
- WorkcubeQueryAdapter composition (named allowlist + Tier policy + composite tenant + IT)
- etl-worker → schema-service contract consumer
- FE kozmetik küçük dalga (paralel)

### Out of Scope (ayrı backlog)

- Faz 21 multi-tenant runtime (DEFER, pre-prod tek-user)
- Tempo / federation / KVKK API (ayrı sub-faz cycles)
- mfe-reporting tüm sayfaları SmartDashboard'a migrate (Quick Win P3)
- Yeni rapor ekleme (feature scope)
- Workcube DBA tarafında AlUser_App rotation (operator-external)

### Bağımlılıklar (Out of Scope ama Bağlantılı)

- Faz 16.1 annex 2A SEAL (operator action; "44 vs ~31" reconciliation)
- AlUser_App credentials rotation (spawn chip — Vault root token + DBA coordination)
- Faz 19.MSSQL.B Workcube authz layer (Hafta 2-3 adapter scope ile çakışıyor — koordinat)

---

## 3. Mimari Prensipleri (Codex consensus, 2026-05-14 thread `019e258f`)

1. **schema-service = metadata source of truth**: tüm 1509 tablo + yearly schema discovery + canonical type mapper (yeni) + lineage/drift/health
2. **report-service = query execution + governance boundary**: allowlist hard gate + tenant resolution + authz mapping + RLS injection + error DTO + metrics
3. **Tier 1/2/3 fallback policy split** (per-report contract):
   - `BUILD_VALIDATION`: Tier 2 committed snapshot OK
   - `RUNTIME_STRICT_EXISTENCE`: Tier 1 sadece; fail-closed 503/400/403
   - `RUNTIME_DEGRADED_TYPE`: explicit opt-in; Tier 2 sadece type/display metadata
4. **Composite multi-table tenant**: table-local filter injection + report-side schema contract; "en kısıtlayıcı union" YASAK (leak riski); Program 7 gelene kadar explicit composite contract veya reddet
5. **Named allowlist version contract**: adapter `40` sayısına değil `workcube-allowlist-v1` named version'a bağımlı; SEAL sonrası version bump → adapter rebuild
6. **Cross-AI peer review** (boundary-changing PR'larda zorunlu): authz/RLS/fallback policy/allowlist enforcement/type mapper/query metrics/tenant boundary değişiklikleri Codex (non-Anthropic) review zorunlu

---

## 4. Mevcut Kontratlar (referans, değiştirilmeyecek)

| Kontrat | Status | Authoritative Doc | Rol |
|---|---|---|---|
| ADR-0005 Dual DataSource Reporting | Accepted 2026-04-24 | [docs/adr/0005-...md](adr/0005-dual-datasource-reporting.md) | Tier fallback + 44-tablo + D19 bridge |
| ADR-0006 Report Contract Gate | Accepted | platform-backend/docs/adr/0006-... | 11 RC rules + tenantBoundary enum + schemaMode enum |
| ADR-0008 Multi-Org Zanzibar | Accepted 2026-04-26 | [docs/adr/0008-...md](adr/0008-multi-org-explicit-scope-zanzibar.md) | OpenFGA viewer explicit + V25 OUR_COMPANY + 6 metrics |
| ADR-0009 Canlı Scoped E2E Gate | Accepted | [docs/adr/0009-...md](adr/0009-canli-scoped-e2e-gate.md) | D35 11-step proof chain |
| ADR-0011 Drift + Boundary Governance | Accepted 2026-04-28 | [docs/adr/0011-...md](adr/0011-drift-detection-audit-cadence-boundary-governance.md) | DD-1..DD-4 + boundary §2.3 |
| mssql-pg-data-contract.md | SEALED DRAFT/RFC | [docs/migration/mssql-pg-data-contract.md](migration/mssql-pg-data-contract.md) | §6 type matrix + §10 FK load + §15 reconciliation |
| Program 8 SchemaTruthService spec | DRAFT (PR #95-#100) | platform-backend/docs/plans/2026-05-...-program-8-... | Tier 1/2/3 facade + 6 metrics + frontend header |
| Program 2 TenantBoundaryGuard spec | DRAFT (PR #102+) | platform-backend/docs/plans/2026-05-...-program-2-... | TenantBoundaryGuard + fail-closed + 9 IT |
| Program 1 ContractValidator | Build-time mevcut | platform-backend | tenant-column-allowlist.json + ExceptionsRegistry 90d |

---

## 5. Genel Başarı Kriterleri (Acceptance)

- ✅ 13 sprint adımı + 2 arka plan adımı tamamlandı
- ✅ Boundary-changing PR'lar cross-provider peer review (Codex AGREE) ile merged; admin bypass kullanılmadı
- ✅ Faz 16.1 annex 2A SEAL (operator)
- ✅ Adapter live test cluster smoke geçti (REPORT_MSSQL_ENABLED=true ile authz + tenant + allowlist + RLS + metrics test)
- ✅ Per-report query-shape metrics Grafana dashboard yayında
- ✅ 0 governance violation: Workcube exposure / Alert+Schedule authz / etl drift / mock prod data
- ✅ D29 disiplini: Up + Functional + Zanzibar-ready 3 katman kanıt her adımda
- ✅ HARD RULE — Tarayıcıdan Sonuç Doğrulanmadan İş Bitmedi: FE/UI etkileyen tüm adımlar browser smoke ile

---

## 6. Risk Register

| ID | Risk | Olasılık | Etki | Mitigation | Sahibi | Statü |
|---|---|---|---|---|---|---|
| R1 | Faz 16.1 SEAL gecikir, adapter pre-seal kod yazılır, contract drift | M | H | Named allowlist version (sayıya değil version'a bağla); SEAL sonrası version bump | Operator+Claude | Open |
| R2 | Codex MCP downtime → cross-provider review beklemesi | L | M | Backup: Gemini fallback; veya commit-and-wait; boundary-changing PR'lar her zaman cross-provider beklesin | Claude | Open |
| R3 | Test cluster Workcube kapatma → development blocker | L | L | Pre-prod canlı user yok; Workcube hâlâ implementation; rollback rollout undo | Operator | Open |
| R4 | Program 2 + Program 8 PR'ları henüz platform-backend'de merge olmadıysa adapter implement bekler | M | H | Önce status check (Adım 5/6 başında); PR durumuna göre paralel veya sequence | Operator+Claude | Open |
| R5 | AlUser_App credentials prod'da reused → coordinated rotation gerek | M | H | Spawn chip aktif; Vault check + DBA coordination; prod cutover öncesi tamamlanmalı | Operator+DBA | Open (spawn chip) |
| R6 | Composite multi-table tenant scope Program 7 pending; adapter reject pattern üretebilir | M | M | Program 7 gelene kadar adapter explicit composite contract; multi-table reports için DRY-RUN flag | Claude | Open |
| R7 | Cache invalidation event-driven değil (TTL only) — schema migration sonrası cache stale | M | M | ADR-0012 alt-spec `/internal/cache/refresh` admin endpoint + Flyway hook; pre-prod scale için yeterli | Claude | Open |
| R8 | Workcube MSSQL connectivity / network partition runtime drift | L | H | RUNTIME_STRICT_EXISTENCE policy fail-closed 503; alerting Prometheus rule | Claude+Ops | Open |
| R9 | HR demographic mock fallback'ı kapatma → kullanıcıya empty state, "sistem boş" hissi | L | L | Empty state UX copy + retry button + ops alert | FE+Ops | Open |
| R10 | Cross-AI peer review HARD RULE non-boundary PR'larda overhead → velocity düşer | L | L | Codex sadece boundary-changing PR'lar zorunlu; diğerleri spec-level AGREE final | Claude | Open |
| R11 | Test cluster Workcube kapatma = Adım 5/11 dev blocker (yearly path IT + adapter test) | M | H | **A-prime** ile çözüldü 2026-05-14 (interim admin-only gate; test'te `REPORT_MSSQL_ENABLED=true` kalır); §7 Adım 1.5 revize | Claude+Codex | ✅ Resolved 2026-05-14 |
| R12 | Interim admin-only gate `@PreAuthorize` role mapping uyumsuzluğu (always-allow / always-deny no-op riski) | M | M | Custom guard fonksiyonu (`@workcubeAccessGuard.isInterimAdmin`) + 3-persona smoke matrix kanıtı zorunlu; `hasRole('SUPER_ADMIN')` direkt kullanılmaz, claim format auth-service üzerinden doğrulanır | Claude | Open |

---

## 7. Sprint Planı (15 adım)

### Hafta 1 — Risk Gate'leri (P0)

---

#### Adım 1 — REPORT_MSSQL_ENABLED canlı doğrulama
- **Status**: ✅ **COMPLETED** (2026-05-14 ~10:30 UTC+3)
- **Owner**: Claude
- **Reviewer**: Codex (`019e258f` iter-1+iter-2 REVISE → AGREE)
- **Bağımlılık**: yok
- **DoD**:
  - ✅ 6-kolon matrix (static / live ConfigMap / Deployment envFrom / pod env / endpoint / verdict)
  - ✅ Test + prod cluster pod env raporu
  - ✅ Secret presence (no value) doğrulaması
  - ✅ Codex AGREE
- **Test**: kustomize build rendered + kubectl get configmap + deployment envFrom grep + pod printenv (all running) + curl HTTP status
- **Çıktı**:
  - TEST: `REPORT_MSSQL_ENABLED=true` → **POLICY DRIFT / RISKY ENV OVERRIDE** (Workcube AKTIF, authz YOK)
  - PROD: `REPORT_MSSQL_ENABLED=false` → MATCH / DISABLED
  - Extra bulgu: AlUser_App credentials test pod env'inde plaintext → **spawn chip aktif**
- **Codex thread ref**: `019e258f` iter-1 REVISE → iter-2 (post-impl) REVISE-AGREE
- **Effort**: 15dk (gerçek)

---

#### Adım 1.5 — Test cluster Workcube interim admin-only gate (Codex A-prime, revize 2026-05-14)
- **Status**: ⏳ **PENDING** (Codex A-prime AGREE; kullanıcı onayı bekleniyor)
- **Owner**: Claude (implement) + Codex (cross-provider review — boundary-changing security gate)
- **Bağımlılık**: Adım 1
- **Revize gerekçe**: Önceki "test cluster kapat" planı dev blocker oluştururdu — Hafta 2-3 Adım 11 (WorkcubeQueryAdapter) test için Workcube AÇIK olmak zorunda. Plus Adım 5 (Program 2) `schemaMode=yearly` + `tenantBoundary=row` kombinasyon IT için Workcube path gerek. Codex A-prime kararı: test'te açık kalsın + interim admin-only gate ile governance boşluğu kapat; prod kapalı kalır.
- **DoD**:
  - Test cluster `REPORT_MSSQL_ENABLED=true` **KALSIN** (dev velocity korunur)
  - Prod overlay/base `false` korunur (governance gate; §5 explicit acceptance: "prod true yapılmadan önce Adım 11 tam adapter zorunlu")
  - `WorkcubeReportController` her endpoint'e **interim admin-only guard**:
    - **Tercih**: `@PreAuthorize("@workcubeAccessGuard.isInterimAdmin(authentication)")` (custom guard bean — claim/role mapping explicit + testlenebilir)
    - Alternatif: `@PreAuthorize("hasRole('SUPER_ADMIN')")` (sadece role mapping authority formatı `ROLE_SUPER_ADMIN` olarak doğrulandıktan sonra)
  - Method security ön-doğrulama:
    - `@EnableMethodSecurity` aktif mi (mevcut config)
    - Token claim/authority formatı (`ROLE_SUPER_ADMIN` vs `SUPER_ADMIN` vs Keycloak realm role vs custom claim) auth-service üzerinden netleştirilir
    - Mapping uyumsuzsa custom guard fonksiyonu **zorunlu** (always-allow / always-deny riski engellenir)
  - Interim guard kod-içi etiket: `// TODO(Adım-11): WorkcubeQueryAdapter lands → remove interim guard + tam authz/RLS/allowlist devreye`
  - **3-persona Workcube smoke matrix (live testai)**:
    - `admin@example.com` (SUPER_ADMIN) → `200` veya datasource-level `503` (Workcube MSSQL reachability) — ikisi de PASS
    - `testuser@testai.acik.com` (non-admin) → `403 FORBIDDEN`
    - no-auth (no Authorization header) → `401 unauthorized`
  - PR boundary declaration: state-mutation (test cluster) + boundary-cross (security gate)
  - **Cross-provider Codex review AGREE** (boundary-changing kategori — auth semantic)
- **Test**:
  - Unit: `WorkcubeAccessGuard.isInterimAdmin` 3 senaryo (admin true / non-admin false / chain edge case)
  - Integration: @SpringBootTest + WireMock KC token + 3 persona × 4 endpoint (`/views`, `/views/{key}`, vb.) matrix
  - Live smoke testai 3-persona above; her sonuç audit DB row + screenshot kanıt (HARD RULE — Tarayıcıdan Doğrulanmadan İş Bitmedi)
- **Risk**: 
  - **R12 (yeni)**: `@PreAuthorize` role mapping uyumsuzluğu → no-op (always allow) veya always-deny — **Mitigation**: custom guard fonksiyonu (`@workcubeAccessGuard.isInterimAdmin`) + 3-persona smoke matrix kanıtı zorunlu
  - Low: pre-prod canlı user yok; test personas ile kontrollü; rollback PR revert
- **Effort**: 1-2 saat (mini PR backend + IT + smoke)
- **Compensating control**: governance hafifletme **pre-prod sadece**; **prod-ready için Adım 11 tam adapter zorunlu** (interim guard kaldırılır + tam authz/RLS/allowlist devreye girer); pre-prod sandbox etiketi PR description'da explicit
- **Codex thread ref**: `019e258f` iter-3 (kapat önerisi REVISE) → iter-4 (A-prime AGREE)
- **Replacement planı (Adım 11)**: interim admin-only guard `// TODO(Adım-11)` ile işaretli; Adım 11 implementasyonunda kaldırılır + tam authz adapter devreye girer; Adım 11 acceptance'ında "interim guard kaldırıldı + tam authz aktif" gate'i

---

#### Adım 2 — Alert/Schedule endpoint report-level authz
- **Status**: ⏳ Pending
- **Owner**: Claude (implement) + Codex (cross-provider review — boundary-changing)
- **Bağımlılık**: Adım 1.5 + Program 2 spec hazır (statü kontrol Adım 5 ile)
- **DoD**:
  - `AlertController` + `ScheduleController` her CRUD method'unda `AccessEvaluator.evaluate(reportKey, authzMe)` çağrısı
  - 4-scenario integration test (Testcontainers PG + WireMock KC):
    - User no `REPORT_VIEW` perm → 403
    - User `REPORT_VIEW` ama farklı scope → 403
    - User `REPORT_VIEW` + matching scope → 200
    - Cross-report tenant boundary leak → 403
  - PR boundary declaration: state-mutation (test cluster) + boundary-cross
  - Codex AGREE
- **Test**:
  - Unit (3): `AlertController.create` permission check; `ScheduleController.update` scope check; `delete` ownership
  - IT (4 above): @SpringBootTest + Testcontainers
  - Live smoke (post-merge): testai admin user 200, non-perm user 403, audit DB row
- **Risk**: medium (canlı schedule/alert kıracak için pre-prod test gerek; rollback: feature flag)
- **Effort**: 4-6 saat
- **Codex thread ref**: TBD (yeni iter veya `019e258f` devam)

---

#### Adım 3 — HR demographic mock fallback prod-kapat
- **Status**: ⏳ Pending
- **Owner**: FE Claude session veya subagent + Codex review
- **Bağımlılık**: Adım 1.5
- **DoD**:
  - `apps/mfe-reporting/src/modules/hr-demographic-report/` kaynak audit (mock fallback yeri)
  - Mock data fallback path KALDIRILDI veya `process.env.NODE_ENV !== 'production'` guard
  - Empty state UX component (icon + i18n message + retry button)
  - Live fetch FAIL durumunda hard error + telemetry event (no mock data)
  - Cypress/Playwright smoke (mock vs live)
- **Test**:
  - FE unit: mock data path artık unreachable in prod
  - Integration: live API down → empty state render; live API up → real data
  - Browser smoke: testai HR dashboard → live data; staging-sw report-service down → empty state
- **Risk**: low (UX değişimi, kullanıcı boş ekran görür ama mock data yanıltıcı değil)
- **Effort**: 2-3 saat
- **Codex thread ref**: TBD

---

#### Adım 4 — FE Excel format mismatch fix
- **Status**: ⏳ Pending
- **Owner**: FE Claude session + Codex review
- **Bağımlılık**: yok (FE-only, paralel ilerletilebilir)
- **DoD**:
  - `ReportPage.tsx:110` veya `module.exportRows()` içinde `format='excel'` parametresi gerçekten `excel` gönderiyor (`csv` değil)
  - Backend `/api/v1/reports/{key}/export?format=excel` Apache POI XLSX streaming response döner
  - FE blob handling content-type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
  - Browser smoke: 3 rapor (1 küçük + 1 büyük + 1 wide-column) Excel indirme + Excel'de açma
- **Test**:
  - Unit FE: `exportRows(filters, 'excel')` mock fetch → `?format=excel` param
  - Integration BE: ExcelStreamingExporter content-type response header
  - Browser smoke (3 senaryo)
- **Risk**: low (export feature, ana akış etkilenmez)
- **Effort**: 2-3 saat
- **Codex thread ref**: TBD

---

### Hafta 1-2 — Implementation Paralel

---

#### Adım 5 — Program 2 TenantBoundaryGuard implement (PR #102+)
- **Status**: ⏳ Pending (statü kontrol gerek: platform-backend'de PR #102+ mevcut mu, draft mı, merge mi?)
- **Owner**: Claude (implement) + Codex (cross-provider review — boundary-changing)
- **Bağımlılık**: ADR-0008 + Program 2 spec
- **DoD**:
  - `TenantBoundaryGuard` filter chain entry
  - `TenantScopeResolver.resolveAllowed()` (super-admin override, single-company auto-pick)
  - `CurrentTenantSchemaResolver` (`workcube_mikrolink_{companyId}` regex)
  - Fail-closed semantics: 400 (bad request), 403 (no scope), 503 (schema not exist)
  - 9 integration tests (Program 2 spec'te listeli)
  - Rolling deploy test cluster smoke
- **Test**:
  - Unit (9 above)
  - IT @SpringBootTest + Testcontainers PG + WireMock KC + OpenFGA test container
  - Live smoke: testai 5 user × 5 report matrix (admin/testuser/d35-admin/d35-granted/mcp-tester)
- **Risk**: high (filter chain değişimi tüm report endpoint'leri etkiler; rollback feature flag veya revert PR)
- **Effort**: 1-1.5 hafta
- **Codex thread ref**: TBD (yeni thread veya `019e258f`)

---

#### Adım 6 — Program 8 SchemaTruthService implement (PR #95-#100)
- **Status**: ⏳ Pending (statü kontrol gerek)
- **Owner**: Claude + Codex review
- **Bağımlılık**: ADR-0008 + Program 8 spec + schema-service Tier 1 mevcut
- **DoD**:
  - `SchemaTruthService` facade class (Tier 1/2/3 dispatch)
  - Capability matrix (`lookupColumnType`, `tableExists`, `listColumns`, `getTenantColumn`)
  - 6 metrics: `lookup_total`, `fallback_total`, `cache_hit_total`, `snapshot_age_days`, `snapshot_age_warn`, `cache_miss_burst`
  - Frontend `X-Schema-Truth-Tier` response header
  - `useReportSchemaContext` hook (FE)
  - Tier policy enum (`BUILD_VALIDATION` / `RUNTIME_STRICT_EXISTENCE` / `RUNTIME_DEGRADED_TYPE`)
- **Test**:
  - Unit: 4 capability × 3 tier × hit/miss
  - IT: facade with real schema-service (test cluster) + committed snapshot Tier 2
  - FE: `useReportSchemaContext` mock + integration
- **Risk**: high (tüm reportlar schema info bu facade'den alır; cache miss spike riski)
- **Effort**: 1-1.5 hafta
- **Codex thread ref**: TBD

---

#### Adım 7 — OUR_COMPANY anchor + V25 transition post-fact ADR
- **Status**: ⏳ Pending
- **Owner**: Claude + Codex review (governance)
- **Bağımlılık**: ADR-0008 + Codex thread `019dd34e` history
- **DoD**:
  - Yeni ADR (örn. `docs/adr/0015-our-company-v25-transition.md`) yazılı
  - V25 öncesi `COMPANY` → V25 sonrası `OUR_COMPANY` anchor mapping documented
  - Transition mapping table (pre/post)
  - Acceptance: ADR-0008 sectionı update edilir; future drift detection için baseline
- **Test**: ADR review checklist; cross-link existing migration evidence
- **Risk**: low (post-fact ADR, kod değişimi yok)
- **Effort**: 1-2 saat
- **Codex thread ref**: `019dd34e` referans + yeni iter

---

#### Adım 8 — JwtClaimExtractor utility
- **Status**: ⏳ Pending
- **Owner**: Claude + Codex review (boundary-changing — auth)
- **Bağımlılık**: yok
- **DoD**:
  - `JwtClaimExtractor` utility class (precedence: `email` → `preferred_username` → `subject`)
  - Null-safe + fallback chain unit tested
  - Mevcut 4+ controller method'unda inject (`ReportController.java:122`, `:137`, `:776-780`, `ReportExportController.java:98-99`)
  - 0 behavior regression (mevcut JWT'lerle aynı user identity)
- **Test**:
  - Unit: 5 senaryo (only email / only preferred_username / only subject / all / none)
  - IT: 3 controller via WireMock KC
- **Risk**: low (utility refactor, behavior preserve)
- **Effort**: 30dk-1 saat
- **Codex thread ref**: TBD

---

### Hafta 2 — Governance Alt-Spec'ler

---

#### Adım 9 — ADR-0012 alt-spec: schema-service `/internal/cache/refresh` + `?scope=reporting`
- **Status**: ⏳ Pending
- **Owner**: Claude + Codex review (governance — admin endpoint)
- **Bağımlılık**: ADR-0012 EA Endpoint Admin Charter + schema-service mevcut
- **DoD**:
  - Alt-spec doc: `docs/adr/0012a-schema-service-admin-operations.md` veya `adr/0012-EA-endpoint-admin/01-schema-service.md`
  - `/internal/cache/refresh?schema=...` endpoint design: auth (X-Internal-Api-Key), pre/post snapshot validation, metrics, RBAC, runbook
  - `?scope=reporting` filtered snapshot: filter contract (reporting-relevant tables), cache key differentiation (scope=all vs scope=reporting)
  - Flyway migration hook: post-migrate webhook → /cache/refresh
  - Implementation PR (schema-service)
- **Test**:
  - Unit: cache refresh endpoint auth + pre/post validation
  - IT: schema-service @SpringBootTest with Caffeine
  - Live smoke: migration → cache invalidate → fresh snapshot
- **Risk**: medium (admin endpoint, auth bypass kötü; RBAC test gerek)
- **Effort**: 1 hafta
- **Codex thread ref**: TBD

---

#### Adım 10 — ADR-0008 §2.4 revision: query-shape metrics extension
- **Status**: ⏳ Pending
- **Owner**: Claude + Codex review (governance — metrics extension)
- **Bağımlılık**: ADR-0008 + Program 8 metrics base
- **DoD**:
  - ADR-0008 §2.4 revision PR: 6 generic metrics → +4 query-shape metrics
    - `report_filter_count` (per-request filter cardinality)
    - `report_join_count` (per-report static)
    - `report_exec_plan_hash` (postgres query plan fingerprint)
    - `report_tenant_cardinality` (per-tenant row count distribution)
  - Prometheus exporter implementation
  - Grafana dashboard JSON committed
  - Alert rules: high cardinality (>10k filter values), unusual plan (new hash)
- **Test**:
  - Unit: metric labels + buckets
  - IT: real query → metric scrape → expected counters
  - Live: testai dashboard render
- **Risk**: low (additive metrics, mevcut akış etkilenmez)
- **Effort**: 3-5 gün
- **Codex thread ref**: TBD

---

### Hafta 2-3 — Adapter + Contract Consumer

---

#### Adım 11 — WorkcubeQueryAdapter composition
- **Status**: ⏳ Pending
- **Owner**: Claude (implement) + Codex (cross-provider review — boundary-changing)
- **Bağımlılık**: Adım 5 (Program 2) + Adım 6 (Program 8) + Adım 9 (alt-spec) + Adım 10 (metrics)
- **DoD**:
  - `WorkcubeQueryAdapter` class — composition of:
    - `TenantBoundaryGuard` (Program 2)
    - `SchemaTruthService` (Program 8)
    - `RowFilterInjector` (existing)
    - `OpenFgaAuthzService` (ADR-0008)
    - `ContractValidator` (Program 1) runtime extension
  - Named allowlist version consumer (`workcube-allowlist-v1` initial)
  - Tier policy enum selector (per-report contract field)
  - Composite multi-table: table-local filter injection + report-side schema contract (Program 7 gelene kadar explicit or reject)
  - Error DTO standardization (`WorkcubeQueryErrorDto` aligns with `ReportQueryErrorDto`)
  - Audit trail: query execution + tenant boundary + RLS clause logged
  - Multi-table integration test (3 senaryo: single + composite explicit + composite unsafe-reject)
- **Test**:
  - Unit: 8 (policy enum × tier × allowlist hit/miss × composite hit/reject)
  - IT: Testcontainers PG + WireMock MSSQL + OpenFGA test container
  - Live smoke: test cluster `REPORT_MSSQL_ENABLED=true` → adapter live test (5 user × 3 report × 3 policy)
  - Browser smoke: testai admin user Workcube view → 200 + tenant-correct data + audit log row
- **Risk**: high (Workcube canlı kullanım, multi-table composite scope eksik = leak riski)
- **Effort**: 1.5-2 hafta
- **Codex thread ref**: TBD

---

#### Adım 12 — etl-worker → schema-service contract consumer
- **Status**: 🟡 PR-1 + PR-2a + PR-2b1 + PR-2b2a + PR-2b2b/2b3 + PR-3a + PR-3b MERGED; PR-3c gitops manifest this PR; PR-4 live smoke pending (operator gate)
- **Provisional location**: `platform-backend/etl-worker/` top-level (Codex `019e2a5c` Opt-B; future `git filter-repo` split to `Halildeu/etl-worker` keeps history clean if/when user authorizes a new repo)
- **Owner**: Claude (Python implement) + Codex review
- **Bağımlılık**: Adım 6 (Program 8 facade hazır) + Adım 11 (named allowlist)
- **PR slicing** (Codex `019e2a5c` AGREE):
  - **PR-1**: `SchemaServiceClient` + typed exceptions + contract models + pytest/ruff/mypy CI gate — [platform-backend#205](https://github.com/Halildeu/platform-backend/pull/205) ✅ MERGED
  - **PR-2a**: config / CLI / client wiring (`SCHEMA_SERVICE_URL`, internal key env, schema/timeout args, sysexits exit-code matrix `0`/`64`/`70`/`75`/`76`, `etl-worker` console script) — [platform-backend#206](https://github.com/Halildeu/platform-backend/pull/206) ✅ MERGED (74 tests total)
  - **PR-2b1**: runner **retry foundation** (`run` subcommand, bounded backoff, injectable sleeper, only `SchemaServiceUnavailable` retried; malformed + mismatch terminal; NaN/Inf guards) — [platform-backend#208](https://github.com/Halildeu/platform-backend/pull/208) ✅ MERGED (130 tests total)
  - **PR-2b2a**: **audit trail foundation** (JSON Lines writer, AuditEvent schema, 6-event vocabulary, atomic single-`write(2)` `O_APPEND`, CLI `--audit-path` / `--run-id` flags, OSError → EX_SOFTWARE typed exit) — [platform-backend#210](https://github.com/Halildeu/platform-backend/pull/210) ✅ MERGED (157 tests total)
  - **PR-2b2b/2b3**: **checkpoint + reports_db writer interface** (Checkpoint atomic write-then-rename + content-only SHA-256 signature, ReportsDbWriter Protocol + NoopReportsDbWriter, runner transaction boundary: fetch → DB upsert → checkpoint, CLI `--checkpoint-path` / `--resume` flags + EX_USAGE fail-closed, ReportsDbWriteError → EX_TEMPFAIL, CheckpointError → EX_SOFTWARE) — [platform-backend#211](https://github.com/Halildeu/platform-backend/pull/211) ✅ MERGED (186 tests total)
  - **PR-3a**: `PgReportsDbWriter` (psycopg adapter, idempotent UPSERT on `(snapshot_signature, contract_version)`, typed `ReportsDbSchemaError` → `EX_SOFTWARE`, `ReportsDbWriteError` → `EX_TEMPFAIL`) + `REPORTS_DB_*` `ReportsDbConfig` (all-or-nothing 5-field env profile + optional sslmode/connect_timeout) + CLI `--reports-db {none,postgres}` fail-closed switch + password-scrub `_safe_message` covering all common driver leak shapes — [platform-backend#212](https://github.com/Halildeu/platform-backend/pull/212) ✅ MERGED (254 tests total)
  - **PR-3b**: multi-stage `python:3.12-slim` Dockerfile (builder `pip install --prefix=/install .`, runtime non-root `etl:etl` UID/GID 1000 matching gitops Job manifest, `psycopg[binary]` wheel bundles libpq, `ENTRYPOINT ["etl-worker"]`) + GHCR image build/push workflow path-filtered to `etl-worker/**` + 4 hermetic container smoke gates (`--help`, missing `SCHEMA_SERVICE_URL`, missing `REPORTS_DB_*`, real `psycopg+libpq` import) + post-push pinned-digest re-smoke binding the `@sha256:<digest>` PR-3c pins to the same artifact this CI run smoke-tested + main-ref-only push gate (preventing `workflow_dispatch` non-main pushes) — [platform-backend#217](https://github.com/Halildeu/platform-backend/pull/217) ✅ MERGED (Codex `019e2d27` 3 P1 + 1 P2 REVISE absorb)
  - **PR-3c**: platform-k8s-gitops `kustomize/base/apps/etl-worker/` manifest update — ConfigMap drops `MSSQL_*` / `ETL_BATCH_SIZE` / `CONTRACT_VERSION` / `ANNEX_VERSION`, adds `SCHEMA_SERVICE_URL` + `SCHEMA_SERVICE_TIMEOUT_SECONDS` + `SCHEMA_SERVICE_CONTRACT_VERSIONS` + `REPORTS_DB_HOST/PORT/DATABASE/CONNECT_TIMEOUT_SECONDS` (PR-3a `Config.from_env` contract); two ExternalSecrets (`etl-worker-reports-db-secrets` ← `kv/platform/etl-worker-reports-db` + `etl-worker-schema-service-secrets` ← `kv/platform/schema-service-internal`); Job manifest `args: ["run", "--reports-db", "postgres", "--audit-path", "/var/lib/etl-worker/audit.jsonl", "--checkpoint-path", "/var/lib/etl-worker/checkpoint.json", "--run-id", "PLACEHOLDER_RUN_ID"]`; `readOnlyRootFilesystem: true` + `emptyDir` mount at `/var/lib/etl-worker` (Codex `019e2d27` AGREE on emptyDir for single-run; PVC deferred); image pinned to `ghcr.io/halildeu/platform-backend-etl-worker@sha256:<DIGEST_FROM_PR3B_MAIN_RUN>` — this PR
  - **PR-4**: live smoke against testai schema-service + reports DB writes — pending (operator gate: DBA `etl_snapshot_runs` table migration + runbook)
- **DoD** (Adım 12 overall):
  - `etl-worker/runner.py` → `SchemaServiceClient` (HTTP) integration
  - Allowlist consumer (named version)
  - Type mapping consumer (schema-service canonical type → pyodbc reader type hint)
  - Fallback: schema-service down → committed snapshot Tier 2 (read-only)
  - Live smoke: test cluster ETL run → schema-service hit → allowlist tables → reports_db insert
- **Target contract — NOT current schema-service shape**: Adım 12 PR-1 hardens the consumer side against a **target** contract (`contract_version`, `allowlist_name`, `allowlist_version`, `tables` list with column `type`) that schema-service does not emit today (today: `version`, `metadata`, `tables` Map, column `dataType`). PR-2+ must coordinate the schema-service emission change. README of `etl-worker/` documents the side-by-side delta.
- **Test**:
  - Unit: SchemaServiceClient mock (200 / 503 / version mismatch + 4xx + parse failures + auth header + `?schema=` selector) — **31 cases PR-1**
  - IT: docker-compose schema-service + etl-worker + PG + MSSQL — PR-3 scope
  - Live smoke: testai ETL run (operator action) — PR-4 scope
- **Risk**: medium (ETL pipeline değişimi; rollback eski hardcoded allowlist)
- **Effort**: 3-5 gün overall; PR-1 ~3-4 saat actual
- **Codex thread ref**: `019e2a5c` (Opt-B AGREE + REVISE absorb + AGREE post-impl)

---

### Arka Plan (Paralel)

---

#### Adım 13 — Faz 16.1 annex 2A SEAL (44 vs ~31 reconciliation)
- **Status**: ⏳ Pending (operator action — Workcube DBA + product owner)
- **Owner**: Operator + Codex review (governance)
- **Bağımlılık**: yok
- **DoD**:
  - Annex 2A YAML: 40 (veya gerçek N) tablo authority mapping (kaynak: OUR_COMPANY, BRANCH, DEPARTMENT, PRO_PROJECTS, vb.)
  - Pre-SEAL acceptance gate: zero `pending_annex`, all tables classify
  - Float semantic_class double-sign-off (analytical/currency/counter)
  - Timezone ERP DBA approval
  - SEAL ADR amendment (ADR-0005 §6 update)
- **Test**: Codex review + DBA sign-off
- **Risk**: high blocker (adapter pre-SEAL pre-prod OK ama prod-ready için SEAL gerek)
- **Effort**: 1-2 hafta operator
- **Codex thread ref**: `019dbe92` thread devam

---

#### Adım 14 — FE kozmetik küçük dalga (paralel)
- **Status**: ⏳ Pending
- **Owner**: FE Claude session + Codex spec review (kozmetik için spec-level AGREE final)
- **Bağımlılık**: yok
- **DoD**:
  - `useReportFormatter()` hook (`@mfe/shared-formatters` veya `@mfe/x-charts` içine)
  - `FilterFormStyle` preset (`apps/mfe-reporting/src/components/`)
  - `useReportData<T>()` hook (React Query unified wrapper)
  - Canonical grid karar dokümante (`@mfe/x-data-grid` vs `EntityGridTemplate` choose one + migration doc)
  - 4 modül adoption sample (audit-report + users-report + hr-compensation + dashboard)
- **Test**:
  - Unit: hook tests
  - Storybook: FilterFormStyle visual
  - Browser smoke: 4 modül render
- **Risk**: low (kozmetik, behavior preserve)
- **Effort**: 1-2 saat (hook'lar) + 1 gün (adoption)
- **Codex thread ref**: spec-level only

---

## 8. Cross-AI Peer Review Tetikleyicileri

Aşağıdaki kategorilerde her PR Codex (non-Anthropic) review zorunlu:

- ✅ Authz / RLS semantics değişimi (Adım 2, 5, 11)
- ✅ Fallback policy enum değişimi (Adım 6, 11)
- ✅ Allowlist enforcement (Adım 11)
- ✅ Canonical type mapper (Adım 6)
- ✅ Query metrics / audit shape (Adım 10)
- ✅ Tenant boundary behavior (Adım 5, 11)
- ✅ Admin endpoint (Adım 9)

Diğer adımlar (kozmetik refactor, test, doc) spec-level AGREE final sayılır.

---

## 9. MSSQL Read-Only Erişim (2026-05-14 kullanıcı bildirimi)

**Yetki**: Kullanıcı (operator) Workcube MSSQL `workcube_mikrolink` veritabanına **read-only** erişime sahip.

**Kullanım alanları (sentetik şema YASAK — kural #9)**:

1. **Schema introspection ground truth** — `sys.tables`, `sys.columns`, `sys.foreign_keys` query'leriyle 1509 tablo doğrulaması (schema-service snapshot ile paralel kanıt)
2. **Type mapping kaynak veri** — gerçek `nvarchar`, `decimal(p,s)`, `datetime2`, `bit` örnek değerleri (canonical mapper test data)
3. **40-tablo allowlist gerçek isim eşleştirme** — INVOICE, INVOICE_ROW, CARI_ROWS, vb. (canonical adların gerçek tablo varlığı doğrulaması)
4. **Adapter test fixture** — sample row (PII-free, anonymized) → Testcontainers MSSQL veya WireMock fixture data
5. **Live drift detection** — schema-service Tier 1 ↔ MSSQL gerçek state diff (ADR-0011 DD-3 quarterly snapshot diff gate)

**Erişim parametreleri** (TBD operator):
- Tool: TBD (sqlcmd / mssql-cli / DBeaver / VS Code SQL Server extension)
- Connection: TBD (host, port, credentials — büyük olasılıkla AlUser_App veya farklı user)
- Schema scope: `workcube_mikrolink` + yearly partitions (`workcube_mikrolink_<year>_<companyId>`)

**Boundary (HARD RULE — ADR-0011 §2.3 + kullanıcı)**:
- ✅ READ-ONLY query (SELECT, sys.* introspection)
- ❌ INSERT / UPDATE / DELETE / DDL (yasak; agent yapmaz)
- ❌ Production credentials write (rotation operator action)
- ❌ PII data export (anonymize zorunlu fixture için)

**Adım eşleştirmesi**:
- Adım 6 (Program 8): live MSSQL ↔ schema-service Tier 1 parity verification
- Adım 7 (V25 ADR): OUR_COMPANY anchor table real row count (42 rows) doğrulama
- Adım 11 (WorkcubeQueryAdapter): test fixture data oluşturma; composite multi-table query test
- Adım 13 (Faz 16.1 SEAL): annex 2A authority mapping kaynak veri

---

## 10. Tracking Log

| Tarih | Saat (TR) | Adım | Aksiyon | Sonuç | Codex thread |
|---|---|---|---|---|---|
| 2026-05-14 | ~10:30 | Adım 1 | REPORT_MSSQL_ENABLED canlı doğrulama | ✅ Done — 6-kolon matrix: test=true (POLICY DRIFT), prod=false (MATCH); spawn chip (AlUser_App) | `019e258f` iter-1,2 REVISE-AGREE |
| 2026-05-14 | ~11:00 | Adım 1.5 | Plan-time review | ✅ Done — Codex AGREE + 9-madde checklist | `019e258f` iter-3 (post-impl pong) |
| 2026-05-14 | ~11:15 | Plan doc | Bu plan dosyası oluşturuldu | ✅ Done — `docs/plan-reporting-refactor-2026-05-14.md` | n/a |
| 2026-05-14 | ~11:30 | Adım 1.5 | Kullanıcı concern: "kapatırsam nasıl test ederim" + Codex A-prime AGREE (kapat değil → interim admin-only gate; test'te `REPORT_MSSQL_ENABLED=true` kalır) | ✅ Plan revize | `019e258f` iter-4 |
| 2026-05-14 | ~12:00 | Adım 1.5 | Worktree `feat/workcube-interim-admin-gate` + `WorkcubeAccessGuard.java` (88 satır) + `WorkcubeReportController` class-level `@PreAuthorize` + `WorkcubeAccessGuardTest.java` (7 test) | ✅ 7/7 unit PASS | n/a |
| 2026-05-14 | ~12:15 | Adım 1.5 | PR [platform-backend#167](https://github.com/Halildeu/platform-backend/pull/167) açıldı; Codex post-impl review submit | ⏳ Codex review + CI bekleniyor | `019e258f` iter-5 submit |
| 2026-05-14 | ~12:25 | Adım 1.5 | Codex iter-5 **REVISE-1**: method-security/controller-level test eksik (`@PreAuthorize` SpEL bean reference pre-merge kanıt) | ✅ Absorb | `019e258f` iter-5 verdict |
| 2026-05-14 | ~12:35 | Adım 1.5 | `WorkcubeMethodSecurityTest.java` (3 test) eklendi: Spring AOP slice + `@EnableMethodSecurity` + non-admin deny → `AccessDeniedException` + anonymous deny + superAdmin allow | ✅ **10/10 PASS** (3 method-security + 7 unit) | n/a |
| 2026-05-14 | ~12:40 | Adım 1.5 | Commit + push (PR #167 güncellendi); Codex iter-6 ready_to_merge re-review submit | ⏳ Codex AGREE bekleniyor | `019e258f` iter-6 submit |
| 2026-05-14 | ~12:50 | Adım 1.5 | Codex iter-6 **AGREE** / `ready_to_merge: true`; başka REVISE yok; CI yeşil bekle → normal squash merge (admin bypass YASAK) | ✅ Cross-AI consensus | `019e258f` iter-6 verdict |
| 2026-05-14 | ~13:00 | Adım 1.5 | CI **10/10 PASS** → `gh pr merge --squash --delete-branch` PR #167 + ai-post-merge-cleanup.sh (archive tag `archive/2026/05/feat-workcube-interim-admin-gate-pr167` 1+ yıl recovery) | ✅ **MERGED** `cb87f5d` | n/a |
| 2026-05-14 | ~13:01 | Adım 1.5 | Post-merge workflows tetiklendi: OSV, gate-secrets, ADR-0011 DD-5, Maven Build, **Image Build + GHCR Push** | ⏳ Image build in_progress (~5-10 dk) | n/a |
| 2026-05-14 | ~13:02 | Adım 8 | JwtClaimExtractor utility paralel başlatıldı (CI beklerken) — worktree `feat/jwt-claim-extractor` + JwtClaimExtractor.java (2 method: `extractAuditUsername` chain + `extractPreferredUsername` strict) + 10 unit test PASS | ⏳ Adoption refactor 11 site bekliyor | n/a |
| 2026-05-14 | ~13:10 | Adım 1.5 | Image build COMPLETED — digest `sha256:d3e870ae2996b24153b4579a5906ca76b39a01ce8395d46cdb323d71d412a766` (tag `sha-cb87f5d`) | ⏳ gitops digest bump PR | n/a |
| 2026-05-14 | ~13:15 | Adım 8 | Adoption refactor tamamlandı (10 site + extractEmail method silindi); full test suite çalıştı, 1 pre-existing fail (`ContractValidatorTest.RC003`) origin/main'de de aynı → unrelated; PR [platform-backend#168](https://github.com/Halildeu/platform-backend/pull/168) açıldı | ⏳ Codex review + CI bekleniyor | n/a |
| 2026-05-14 | ~13:25 | Adım 8 | Codex iter-7 **REVISE-2**: (1) `ReportSchemaContextController:222 extractEmail()` residual + (2) RC-003 pre-existing fail CI'da merge blocker (admin bypass YASAK) → ayrı fix PR | ✅ Absorb + spawn chip (RC-003) | `019e258f` iter-7 verdict |
| 2026-05-14 | ~13:30 | Adım 8 | ReportSchemaContextController :215 + :222-226 refactor → JwtClaimExtractor.extractAuditUsername(jwt); JwtClaimExtractor import eklendi | ✅ Code change ready, mvn test bekleniyor | n/a |
| 2026-05-14 | ~13:32 | Adım 1.5 | gitops test overlay digest bump: `sha-9beed5f` → `sha-cb87f5d` (`sha256:d3e870ae2996b...`) — line 391 `kustomize/overlays/test/kustomization.yaml` Edit done | ⏳ PR + Codex review + merge + cluster apply | n/a |
| 2026-05-14 | ~13:35 | Adım 1.5 | PR [platform-k8s-gitops#576](https://github.com/Halildeu/platform-k8s-gitops/pull/576) açıldı (branch `feat/report-service-sha-cb87f5d-workcube-interim-gate`) | ⏳ CI bekleniyor (12/13 pass, BG-1 fail 2x boundary fix) | n/a |
| 2026-05-14 | ~13:40 | Adım 1.5 | Codex iter-8 **AGREE / ready_to_merge: true** (PR #576); typo correction comment + cross-AI consensus + rollout strategy ArgoCD auto-first → manual fallback | ✅ Cross-AI consensus | `019e258f` iter-8 |
| 2026-05-14 | ~13:45 | Adım 1.5 | PR #576 BG-1 fail fix: `state-mutation (test cluster — image rollout)` → exact `state-mutation (test cluster)` + label `user-approval-required` eklendi; failed run re-triggered | ⏳ BG-1 re-check pending | n/a |
| 2026-05-14 | ~13:42 | Adım 8 | Codex iter-8 PART A: AGREE / ready_to_merge: **false** (RC-003 blocker; admin bypass YASAK); Sıralama (a) RC-003 fix önce → main yeşil → PR #168 rebase + merge | ⏳ RC-003 fix spawn task bekleniyor | `019e258f` iter-8 |
| 2026-05-14 | ~13:48 | Adım 1.5 | **KRİTİK BULGU**: SSH staging-sw cluster pre-deploy baseline → pod `report-service-79cfcf5ccc-p2xhz` 13dk Running, imageID **`sha256:d3e870ae...`** (yeni digest); Deployment spec image aynı yeni digest. Deploy workflow image build sonrası test cluster'a otomatik push etmiş (deploy-backend-test). **Adım 1.5 cluster CLUSTER LIVE** zaten (gitops PR audit trail için) | ✅ **LIVE on test cluster** | n/a |
| 2026-05-14 | ~13:49 | Adım 1.5 | No-auth `/api/v1/workcube/views` → `401 unauthorized` (Spring Security chain JWT zorunlu; interim guard'ı bypass etmez ama 401 expected baseline); Adım 1.5 acceptance 3-persona smoke ayrı ping-pong | ✅ Baseline 401 confirm | n/a |
| 2026-05-14 | ~13:50 | Adım 1.5 | PR #576 BG-1 fail → empty commit `f413c89` push (yeni CI event); poll bekleniyor | ⏳ CI re-run | n/a |
| 2026-05-14 | ~17:00 | Adım 10 | ADR-0008 §2.4 Observability — Metrics section eklendi (6 generic + 4 query-shape; label cardinality budget); PR [#598](https://github.com/Halildeu/platform-k8s-gitops/pull/598) MERGED | ✅ **MERGED** | `019e258f` iter-13 AGREE |
| 2026-05-14 | ~17:30 | Adım 5 | Program 2 gap audit revize: infrastructure ~%90 mevcut (`ScopeContext`+`Filter`+`Holder` commonauth; `CompanyHeaderScopeNarrower`+`TenantBoundary`+`CurrentTenantSchemaResolver`+`TenantGuardExceptionHandler` mevcut; PR #109 MERGED 2026-05-07); gerçek delta: `TenantBoundaryGuard` HandlerInterceptor + `ReportServiceWebMvcConfig` + path matrix | ✅ Audit done | n/a |
| 2026-05-14 | ~17:35 | Adım 5 | PR-1 plan-time submit (Codex iter-14): scope revize + 5 soru | ✅ Done | `019e258f` iter-14 submit |
| 2026-05-14 | ~17:40 | Adım 5 | Codex iter-14 **PARTIAL** / `ready_for_impl: true`: 3 revizyon (Workcube OUT, report-aware enforcement, narrow çağrıları korunur) absorb | ✅ Absorb | `019e258f` iter-14 verdict |
| 2026-05-14 | ~17:45 | Adım 5 | PR-1 impl: TenantBoundaryGuard.java + ReportServiceWebMvcConfig.java + 11 unit + 3 web config test; 560/560 PASS başlangıç | ✅ Initial impl | n/a |
| 2026-05-14 | ~17:55 | Adım 5 | PR [platform-backend#179](https://github.com/Halildeu/platform-backend/pull/179) açıldı; Codex iter-15 post-impl review submit | ⏳ Codex review | `019e258f` iter-15 submit |
| 2026-05-14 | ~17:58 | Adım 5 | Codex iter-15 **REVISE-1** / `ready_to_merge: false`: blocker — `@ConditionalOnBean(PermissionResolver.class)` `@Component` üzerinde silent security bypass riski → kaldır + production-like wiring test ekle | ✅ Absorb | `019e258f` iter-15 verdict |
| 2026-05-14 | ~18:05 | Adım 5 | Fix commit: `@Component` kaldırıldı; ayrı `TenantBoundaryGuardBeanConfig.java` (manual @Bean); ApplicationContextRunner pattern ile 2 wiring test; **562/562 PASS** + ContextHealthControllerTest regression resolved | ✅ Fix MERGED candidate | n/a |
| 2026-05-14 | ~18:10 | Adım 5 | Codex iter-16 **AGREE** / `ready_to_merge: true` 2 normal kapanış şartıyla (CI yeşil + PR description scope notu) | ✅ Cross-AI consensus | `019e258f` iter-16 verdict |
| 2026-05-14 | ~18:15 | Adım 5 | PR #179 description scope notu eklendi ("PR-1 scope: schema-bound yearly/current only; Workcube direct endpoints deferred to Adım 11") | ⏳ CI yeşil bekleniyor (Maven full reactor PASS + 3 Testcontainers IT pending) | n/a |
| 2026-05-14 | ~18:20 | Plan doc | Handoff doc Session 50 PR [platform-k8s-gitops#608](https://github.com/Halildeu/platform-k8s-gitops/pull/608) açıldı (branch `docs/session-50-reporting-refactor-handoff`); BG-1 + cross-AI body format düzeltildi | ⏳ CI re-check pending | n/a |
| 2026-05-14 | ~18:25 | Adım 5 PR-1 | PR [platform-backend#179](https://github.com/Halildeu/platform-backend/pull/179) **MERGED** (Codex iter-16 AGREE + CI yeşil + normal squash; admin bypass yok); cleanup tag `archive/2026/05/feat-program-2-tenant-boundary-guard-pr179` | ✅ **MERGED** | `019e258f` iter-16 AGREE |
| 2026-05-14 | ~18:30 | Adım 10 | PR [platform-k8s-gitops#598](https://github.com/Halildeu/platform-k8s-gitops/pull/598) **MERGED** (ADR-0008 Observability — Metrics 6 generic + 4 query-shape; Codex iter-13 AGREE) | ✅ **MERGED** | `019e258f` iter-13 AGREE |
| 2026-05-14 | ~18:32 | Handoff doc | PR [platform-k8s-gitops#608](https://github.com/Halildeu/platform-k8s-gitops/pull/608) **MERGED** (Session 50 progress doc + plan §10 tracking; doc-only) | ✅ **MERGED** | n/a |
| 2026-05-14 | ~18:35 | Adım 11 | Codex iter-17 PARTIAL: 5-PR breakdown (11.1 RC-011 + 11.2 adapter core + 11.3 controller adoption + 11.4 interim gate removal + 11.5 prod cutover); BUILD_VALIDATION enum YOK (mevcut BUILD_DETERMINISTIC + ayrı ContractRule); ReportingAllowlist hardcoded Java Set (no sibling-repo CI dep) | ✅ Plan-time consensus | `019e258f` iter-17 |
| 2026-05-14 | ~18:40 | Adım 11.1 | RC-011 + ReportingAllowlist V1 (30 tables: 23 ADR-0012-SS + 7 regression) + ContractValidator chain 11 → 12 + 8 unit test; 585/585 PASS | ✅ Impl done | n/a |
| 2026-05-14 | ~18:50 | Adım 11.1 | PR [platform-backend#182](https://github.com/Halildeu/platform-backend/pull/182) açıldı; Codex iter-18 PARTIAL clarity (2 Javadoc/PR-body revision, code-behavior change YOK); iter-19 **AGREE** `ready_to_merge: true` | ✅ **MERGED** via REST API (GraphQL rate limit bypass) | `019e258f` iter-18 PARTIAL + iter-19 AGREE |
| 2026-05-14 | ~19:00 | Adım 11.2a | TableRef record + WorkcubeSqlTableRefScanner (lightweight T-SQL parser: literal/comment masking, bracketed+unbracketed two-part, unqualified, fail-closed on OPENQUERY/temp/var) + RC-011 sourceQuery branch + ReportingAllowlist.V1 expand 30→40 (Codex iter-20 sourceQuery inventory sweep: ACCOUNT_PLAN, COMPANY, CONSUMER, EMPLOYEES, EMPLOYEES_DETAIL, EMPLOYEES_IDENTY, EMPLOYEES_PUANTAJ, EXPENSE_ITEMS, MONEY_HISTORY, SETUP_DOCUMENT_TYPE) + 18 scanner tests + 12 RC-011 tests + 8 dynamic registry sweep tests; 630/630 PASS | ✅ Impl done | `019e258f` iter-20 PARTIAL |
| 2026-05-14 | ~19:10 | Adım 11.2a | PR [platform-backend#183](https://github.com/Halildeu/platform-backend/pull/183) açıldı; Codex iter-21 **REVISE-1** 2 blocking (sourceQuery-only coverage + UNQUALIFIED fail-closed) + 3 clarity absorb → iter-22 **AGREE** `ready_to_merge: true` | ✅ **MERGED** via REST API (close+reopen+retry; merge poller short SHA bug fix) | `019e258f` iter-21 REVISE-1 + iter-22 AGREE |
| 2026-05-14 | ~19:25 | Adım 11.2b-1 | WorkcubeQueryAdapter @Service + rendered SQL second-line scanner enforce + WorkcubeQuerySecurityException + 403 handler + 10 unit test; 640/640 PASS | ✅ Impl done | n/a |
| 2026-05-14 | ~19:35 | Adım 11.2b-1 | PR [platform-backend#184](https://github.com/Halildeu/platform-backend/pull/184) açıldı; Codex iter-22 acceptance scope (mock-only, Testcontainers 11.2b-2'ye defer); iter-23 **PARTIAL** 2 blocking (no-ref fail-closed + wiring proof) absorb → iter-24 **AGREE** `ready_to_merge: true` (644/644 PASS) | ✅ **MERGED** via REST | `019e258f` iter-22 + iter-23 PARTIAL + iter-24 AGREE |
| 2026-05-14 | ~19:50 | Adım 11.2b-2 | WorkcubeQueryAdapterIT (Testcontainers MSSQL 2022 + canonical fixture + 6 test case: allowed canonical + count + unknown/unqualified/no-ref fail before JDBC + rogue filter upstream drop) + CI workflow `-Dtest` include WorkcubeQueryAdapterIT | ✅ Impl done | n/a |
| 2026-05-14 | ~20:00 | Adım 11.2b-2 | PR [platform-backend#185](https://github.com/Halildeu/platform-backend/pull/185) açıldı; Codex iter-25 **PARTIAL** (CI workflow blocker: `-Dtest='SqlBuilderMssqlIntegrationTest'` only ran one IT, WorkcubeQueryAdapterIT not picked up) absorb → iter-26 **AGREE** `ready_to_merge: true` (canonical-only scope; yearly+composite+`{tenantSetupProcessCatRelation}` 11.2c'ye defer) | ✅ **MERGED** via REST | `019e258f` iter-25 PARTIAL + iter-26 AGREE |
| 2026-05-14 | ~20:30 | Adım 11.2c | CompositeTenantBoundaryEnforcer @Service (tenantId equality, NOT schema-string; SETUP_PROCESS_CAT CURRENT_TENANT; canonical bypass) + WorkcubeQueryAdapter pipeline order (UNKNOWN/UNQUALIFIED → V1 → composite last) + 12 unit test + 4 IT case (yearly partition + cross-tenant defensive fail + tenantSetupProcessCatRelation visibility); 656/656 PASS | ✅ Impl done | `019e258f` iter-27 PARTIAL |
| 2026-05-14 | ~20:45 | Adım 11.2c | PR [platform-backend#187](https://github.com/Halildeu/platform-backend/pull/187) açıldı; Codex iter-28 **AGREE** `ready_to_merge: true` (CI yeşil şart); composite tenant boundary defense-in-depth final layer | ✅ **MERGED** via REST | `019e258f` iter-28 AGREE |
| 2026-05-14 | ~21:00 | Adım 11.3 | WorkcubeReportExecutionService orchestration (ReportRegistry + PermissionResolver + Narrower + YearlySchemaResolver + CurrentTenantSchemaResolver + Adapter) + 2 yeni endpoint `/reports/{key}/data|count` + legacy `/views/*` deprecation header + 7 unit + 5 method-security + 2 exception mapping test; 673/673 PASS | ✅ Impl done | `019e258f` iter-29 PARTIAL |
| 2026-05-14 | ~21:30 | Adım 11.3 | PR [platform-backend#188](https://github.com/Halildeu/platform-backend/pull/188) açıldı; Codex iter-30 **REVISE-1** 2 blocker (schema resolution defer YASAK — header bypass riski + controller integration test eksik) + iter-30 PagedResultDto.total real count + iter-31 **PARTIAL** 2 mapping (WorkcubeQuerySecurityException propagation + DataAccessResourceFailureException 503) absorb → iter-32 **AGREE** `ready_to_merge: true` | ✅ **MERGED** via REST | `019e258f` iter-29/30/31/32 |

---

## 11. Bağlantılı Dosyalar / Referanslar

- **Kontratlar**: bkz §4 tablosu
- **Önceki audit raporları**:
  - Frontend audit (Explore subagent, 2026-05-14)
  - Backend audit (Explore subagent, 2026-05-14)
  - schema-service rol audit (Explore subagent, 2026-05-14)
  - Kontrat universe audit (Explore subagent, 2026-05-14)
- **HARD RULE'lar (global CLAUDE.md)**:
  - Cross-AI Peer Review (2026-05-05, 2026-05-14 clarified)
  - Admin Merge YASAK (2026-05-05)
  - Governance / Sistemik Bug (2026-05-05)
  - Pre-Production Full Authority (2026-04-29)
  - No Fake Work (2026-04-25)
  - Tarayıcıdan Sonuç Doğrulanmadan İş Bitmedi (2026-05-11)
- **Codex thread'leri**:
  - `019e258f` — Reporting Refactor ana thread (bu plan)
  - `019dbe92` — Faz 16.0 contract iter-4 AGREE (referans)
  - `019dd34e` — V25 OUR_COMPANY transition (referans, Adım 7)
- **Spawn chip'ler**: AlUser_App credentials rotation + redaction standard

---

## 12. Plan Update Protokolü

Her adım statüsü değişiminde:

1. `§7 Sprint Planı` ilgili adım `Status` field güncellenir
2. `§10 Tracking Log` yeni satır eklenir (tarih + aksiyon + sonuç + Codex thread)
3. Yeni risk varsa `§6 Risk Register` satır eklenir
4. Çıktı (artifact) varsa adım `Çıktı` field güncellenir
5. Codex post-impl review AGREE alındığında `Status: COMPLETED` işaretlenir
6. Sapma varsa `Notlar` field eklenir + plan delta açıklanır

Plan dosyası canlı; her commit'te diff plan delta gösterir; PR description'da güncelleme özeti.
