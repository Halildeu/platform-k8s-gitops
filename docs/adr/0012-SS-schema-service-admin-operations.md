# ADR-0012-SS — Schema-Service Admin Operations Alt-Spec

> **Status**: DRAFT (plan §7 Adım 9) | **Owner**: Platform-Eng | **Date**: 2026-05-14
> **Sprint**: Reporting Refactor (plan §7 Adım 9) | **Plan ref**: `docs/plan-reporting-refactor-2026-05-14.md` §7 Adım 9
> **Codex thread**: `019e258f-1d09-72f1-8385-245eedde08f6` iter-9 + iter-11 (review)
> **Parent**: ADR-0012-EA Endpoint Admin Governance Charter (admin endpoint pattern)
> **Related**: ADR-0005 Dual DataSource Reporting (Tier 1 schema-service authority) | ADR-0008 §2.4 metrics
> **Konvansiyon**: `0012-SS` (Schema Service) namespace; ADR-0012-EA gibi sub-spec pattern reuse

---

## 1. Bağlam

`schema-service` mevcut canonical authority Workcube MSSQL schema metadata için (1509 tablo, 26240 kolon, 1774 FK). Tier 1 consumer `report-service` `SchemaServiceClient` (Caffeine cache + Tier 2 committed snapshot fallback). 16 endpoint mevcut: `/snapshot`, `/tables/{name}`, `/search/columns`, `/impact/{name}`, `/domains`, `/hubs`, `/path`, `/health-score`, `/drift`, `/drift/history`, `/suggestions/{name}`, `/lookup`, `/schemas`, `/master-data/{kind}`, `/lineage/{table}/{col}`, + Ai/Annotation.

**Eksik admin operations** (Codex `019e258f` iter-7,8,9 audit):

1. **Cache invalidation event-driven değil** — Spring Cache `@Cacheable(value="snapshot", key="#schema")` 60-min TTL only; Flyway migration veya MSSQL DDL sonrası cache stale kalır; pod restart dışında refresh yok. Manuel admin trigger gerekli.

2. **Scoped snapshot endpoint yok** — `/snapshot` tüm 1509 tablo döner; reporting-relevant subset (40-table allowlist) filter yok. `report-service` Tier 1 client tüm payload alır + client-side trim — extra wire bandwidth + parse overhead.

3. **Admin endpoint authorization pattern netleşmemiş** — mevcut `X-Internal-Api-Key` header (snapshot endpoint) + Spring Security JWT (authenticated endpoint'ler) hibrit. Admin operasyonu için keskin RBAC + audit gerek.

## 2. Karar (DRAFT)

İki yeni admin endpoint + 1 query parameter:

### 2.1. `POST /internal/cache/refresh?schema=<schema>` (NEW)

**Path**: `/internal/cache/refresh` (operator-internal, NOT user-facing `/api/v1/*`)

**Auth**: `X-Internal-Api-Key` header (existing snapshot endpoint pattern reuse) + IP allowlist (`platform-test`/`platform-prod` ingress only, no external)

**Behavior**:
1. Pre-validation: target schema exists in `listSchemas()` (else 404)
2. Cache evict: `@CacheEvict(value="snapshot", key="#schema")` + `@CacheEvict(value="tables", key="#schema")` + `@CacheEvict(value="rowCounts", key="#schema")` + `@CacheEvict(value="viewDefs", key="#schema")`
3. Pre-emptive rebuild: `SchemaSnapshotService.buildSnapshot(schema)` (warm cache for next request)
4. Post-validation: snapshot row count > 0 + table count > 0 → return 200 OK; else fail → 503

**Response**:
```json
{
  "schema": "workcube_mikrolink",
  "refreshedAt": "2026-05-14T13:45:00Z",
  "tablesCount": 1509,
  "previousAge": "PT58M30S",
  "validationStatus": "ok"
}
```

**Metrics** (Prometheus):
- `schema_service_cache_refresh_total{schema,status}` Counter
- `schema_service_cache_refresh_duration_seconds{schema}` Histogram
- `schema_service_cache_age_seconds{schema}` Gauge (post-refresh = 0)

**Trigger source**:
- Manual ops (curl + admin key)
- Flyway post-migrate webhook (test/prod GitOps deploy script çağrısı)
- Polling agent (15-dk drift check; eğer MSSQL DDL change detected → trigger)

### 2.2. `GET /api/v1/schema/snapshot?scope=reporting` (PARAMETER, NEW)

Mevcut `/snapshot` endpoint'ine `scope` query param ekle.

**Auth**: existing (X-Internal-Api-Key veya JWT)

**Behavior**:
- `?scope=all` (default veya omit) → full 1509 tablo (current behavior, backward-compat)
- `?scope=reporting` → 40-table allowlist filter:
  - 23 canonical: INVOICE, INVOICE_ROW, CARI_ROWS, CARI_ACTIONS, BANK_ACTIONS, CASH_ACTIONS, CHEQUE, COMPANY_REMAINDER, ORDERS, OUR_COMPANY, BRANCH, DEPARTMENT, PRO_PROJECTS, [...]
  - 17 parametric: yearly partitions (`workcube_mikrolink_<year>_<companyId>`)
  - Source-of-truth: `docs/migration/mssql-inventory.md` (40 tablo allowlist; Faz 16.1 annex 2A SEAL)

**Implementation**: snapshot post-build filter:
```java
@Cacheable(value="snapshot", key="#schema + ':' + #scope")
public SchemaSnapshot buildSnapshot(String schema, String scope) {
    SchemaSnapshot full = buildSnapshotInternal(schema);
    if ("reporting".equals(scope)) {
        return full.filterTables(ReportingAllowlist.TABLES);
    }
    return full;
}
```

**Cache key differentiation**: `snapshot:<schema>:<scope>` (default `scope=all`).

**Metrics**:
- `schema_service_snapshot_request_total{schema,scope}` Counter

### 2.3. Authorization Matrix

| Endpoint | Auth | RBAC |
|---|---|---|
| `POST /internal/cache/refresh` | X-Internal-Api-Key only | Service-account (operator + Flyway webhook + polling agent) |
| `GET /snapshot?scope=reporting` | X-Internal-Api-Key OR JWT (existing) | No change — same as `/snapshot` |
| `GET /snapshot?scope=all` | X-Internal-Api-Key OR JWT | Same |

`X-Internal-Api-Key` source: Vault `kv/platform/schema-service/internal-api-key` → ESO `schema-service-secrets` ConfigMap mount (existing pattern).

## 3. Sonuçlar

### Pozitif

- **Cache invalidation explicit**: schema migration sonrası snapshot refresh tek HTTP call ile yapılır (manual veya Flyway hook)
- **Bandwidth optimization**: `?scope=reporting` ile report-service Tier 1 client 40-table response alır (~3% data vs full 1509); cache miss da hızlı
- **Drift detection coverage**: ADR-0011 DD-3 schema-service snapshot diff gate `/internal/cache/refresh` ile entegre — periodic cache refresh sonrası diff alarm üretebilir
- **Admin operations doc explicit**: ADR-0012-EA pattern reuse — bundan sonra `/internal/*` admin endpoint'ler için tutarlı authz + audit + metrics standardı

### Negatif

- **API surface artışı**: 1 new endpoint + 1 query param; backward-compat korunur ama implementation kompleksite +20%
- **Cache key differentiation**: `snapshot:<schema>:<scope>` — eski cache key (`snapshot:<schema>`) migration; mevcut snapshot cache 1-kez invalidate olur deploy sonrası
- **`?scope=reporting` allowlist source-of-truth tek yer**: `ReportingAllowlist` Java class (40-table SET) `mssql-inventory.md` ile manuel sync; drift riski → ADR-0011 DD-1 build-time gate ile guard

### Neutral

- ETL worker `?scope=reporting` consumer olmaya devam edebilir (allowlist 40-table); ayrı endpoint gerekmez
- Frontend mfe-reporting bu endpoint'i kullanmaz (schema-service'i bypass eder zaten)

## 4. Drift Detection (ADR-0011 DD-3 entegrasyonu)

- **Build-time gate** (`scripts/drift_detection/check_reporting_allowlist.py`): `ReportingAllowlist` Java SET ⇄ `mssql-inventory.md` 40-table list sync check; mismatch → FAIL
- **Runtime cache age alarm**: `schema_service_cache_age_seconds > 1800` (30dk) → Prometheus alert; auto-trigger `/internal/cache/refresh` via polling agent (drift snake-eating-tail önlenir 5-min cooldown ile)
- **Post-migration hook**: Flyway `flyway:migrate` success → curl `/internal/cache/refresh?schema=<schema>` (CI/CD step or Vault dynamic secret runner)

## 5. Implementation Plan

| Adım | Effort | Owner | Cross-AI gate |
|---|---:|---|---|
| `ReportingAllowlist.java` (40 tablo SET + build-time gate test) | 1 saat | Claude | spec-level (doc) |
| `SchemaSnapshotService` overload (`scope` param) + cache key | 2-3 saat | Claude | boundary-changing (Codex review zorunlu) |
| `POST /internal/cache/refresh` endpoint | 3-4 saat | Claude | boundary-changing (admin endpoint authz) |
| Prometheus metrics (3 metric) + Grafana dashboard JSON | 2 saat | Claude | metrics extension (Codex review) |
| Integration test (Testcontainers MSSQL + Caffeine + WireMock) | 4 saat | Claude | spec-level |
| Operator runbook (`RB-schema-service-cache-refresh.md`) | 1 saat | Claude | spec-level |
| Drift detection script + CI gate | 2 saat | Claude | boundary-changing |
| Cross-provider Codex post-impl review | 30-60dk | Codex | zorunlu |

**Total**: ~1 hafta (Codex tahmin 0.5-1 gün doc + 3-5 gün impl).

## 6. Open Items

- **`ReportingAllowlist` 40-table source**: Faz 16.1 annex 2A SEAL bekleniyor (44 vs ~31 reconciliation, operator action). Pre-SEAL adapter "named allowlist version" pattern: `ReportingAllowlist.V1` (initial) → `V2` (SEAL sonrası).
- **Polling agent / Flyway webhook**: ayrı PR (gitops `kustomize/base/apps/schema-service/ops/cache-refresh-cron.yaml` cron veya init-container hook)
- **ADR-0008 §2.4 metrics revision** (plan §7 Adım 10): query-shape metrics extension — bu ADR'da listelenen 4 metric (refresh_total, refresh_duration, cache_age, snapshot_request_total) ADR-0008'in 6 generic metric setine eklenecek

## 7. Bağlantılı Kontratlar

- ADR-0005 Dual DataSource Reporting (Tier 1 schema-service authority + Faz 16 scope)
- ADR-0008 §2.4 6 generic metrics + 4 yeni metric extension (plan §7 Adım 10)
- ADR-0011 DD-3 schema-service snapshot diff gate (quarterly snapshot drift)
- ADR-0012-EA Endpoint Admin Governance Charter (admin endpoint pattern reuse)
- Codex thread `019e258f` iter-7,8,9 audit identification

---

**Status**: DRAFT — Codex iter-9 spec-level AGREE bekleniyor; iter-11 review sonrası ACCEPTED.
