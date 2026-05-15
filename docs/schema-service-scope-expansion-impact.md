# Schema-Service Kapsam Genişlemesi — Etki Analizi

> **Soru**: PR #693 capability gap matrix'in 30 maddesi implementasyona alınırsa **neler değişir**? Hangi servisler, tablolar, modeller, UI sekmeleri, contract'lar etkilenir?
>
> **Tarih**: 2026-05-15  
> **Bağlam**: 4 doc quadrilogy (#688 #690 #691 #693) sonrası uygulama tarafı etki haritası.

---

## 1. Etki Matrisi — Bileşen × Capability

| Bileşen | Etkilenen Alan | Effort (kümülatif) | Risk |
|---|---|---|---|
| **schema-service backend** | 8-12 yeni controller endpoint + 15+ yeni service + 8 yeni model | ~3 hafta | Düşük (read-only) |
| **mfe-schema-explorer frontend** | 5-8 yeni UI sekmesi + truth tier badge + per-capability filter | ~1-2 hafta | Düşük (UX) |
| **MSSQL kaynak** | 20+ yeni sys.* + DMV sorgusu, Query Store enable, sampling load | Periyodik | Orta (load + permission) |
| **Postgres hedef (own DB)** | 5-8 yeni tablo (drift baseline, annotation extended, workload cache, sample cache) | ~1 hafta | Düşük |
| **Annex 2A YAML** | 12-15 yeni alan (truth tier, evidence list, real FK status) | ~3-4 gün | Yüksek (canonical contract değişimi) |
| **report-service** | Schema-service'ten unique/check/real-FK consume, SourceQuery validation extension | ~1 hafta | Orta |
| **etl-worker** | Parametric ETL pipeline (Faz 16.2.P deferred) — schema discovery layer bağımlılığı | ~2-3 hafta | Orta (Faz 16.2.P scope) |
| **AI Chat backend** | Semantic dictionary + annotation injection + workload-derived examples | ~1 hafta | Düşük |
| **CLAUDE.md + PLAN.md + ADR** | Drift guard genişleme, ADR-0008 extension, truth tier kuralı | ~1-2 gün | Düşük |
| **DBA workflow** | Annotation onboarding, sampling opt-in flow, MSSQL permission review | Periyodik | Orta (org adoption) |
| **PII / security** | Sampling masking, query timeout, read-only mode enforce | Sprint 3 | Yüksek |

---

## 2. Schema-Service Backend (Java/Spring) — Detaylı

### 2.1 Yeni Controller endpoint'leri

| Endpoint | Yeni capability |
|---|---|
| `GET /api/v1/schema/foreign-keys` | Real FK (sys.foreign_keys) listesi |
| `GET /api/v1/schema/unique-constraints?schema=<>` | Unique constraint discovery |
| `GET /api/v1/schema/check-constraints?schema=<>` | Check constraint listesi |
| `GET /api/v1/schema/defaults?schema=<>` | Default value constraints |
| `GET /api/v1/schema/indexes?schema=<>` | Non-PK index inventory |
| `GET /api/v1/schema/index-health/{table}` | Index fragmentation + usage |
| `GET /api/v1/schema/storage/{table}` | Storage size + LOB + filegroup |
| `GET /api/v1/schema/partitions/{table}` | Partition scheme + boundary + row count |
| `GET /api/v1/schema/programmability/{schema}` | SP + function + trigger listesi |
| `GET /api/v1/schema/dependencies/{object}` | sys.sql_expression_dependencies graph |
| `GET /api/v1/schema/cdc-status` | CDC / Change Tracking enabled tables |
| `GET /api/v1/schema/database-options` | Recovery model + compatibility + RCSI |
| `POST /api/v1/schema/sample/{table}` | Opt-in sampling (PII masked) |
| `GET /api/v1/schema/workload/top-queries` | Query Store top expensive queries |
| `GET /api/v1/schema/workload/join-pairs` | En çok join'lenen tablo çiftleri |
| `GET /api/v1/schema/relationships/evidence/{rel}` | Detaylı evidence (multi-source breakdown) |

### 2.2 Yeni service class'ları (~15)

```
ForeignKeyDiscoveryService     — sys.foreign_keys extract
UniqueConstraintService        — is_unique=1 indexes
ConstraintExtractService       — check + default + custom
IndexInventoryService          — non-PK indexes + fill factor + filter
IndexHealthService             — dm_db_index_physical_stats + usage_stats
StorageMetricsService          — dm_db_partition_stats
PartitioningService            — sys.partitions + schemes + functions
ProgrammabilityService         — SP + func + trigger bodies
DependencyGraphService         — sys.sql_expression_dependencies
TSQLParserService              — proper parser (regex replaced)
WorkloadMiningService          — Query Store / DMV
DataSamplingService            — opt-in + PII masked
CDCStatusService               — change tracking detection
PermissionInventoryService     — GRANT / RLS extract
SemanticDictionaryService      — annotation extended
```

### 2.3 Model genişlemesi

```java
// Mevcut
public record ColumnInfo(name, dataType, maxLength, nullable, identity, pk, ordinal) {}

// Önerilen (PR #693 §4)
public record ColumnInfo(
    String name, String dataType, int maxLength,
    Integer precision, Integer scale,        // NEW
    String collation,                         // NEW
    boolean nullable, boolean identity,
    Long identitySeed, Long identityIncrement, // NEW
    boolean pk,
    boolean unique,                           // NEW
    String defaultExpression,                 // NEW
    String computedExpression,                // NEW
    boolean persisted,                        // NEW (computed)
    boolean sparse,                           // NEW
    int ordinal
) {}

public record RelationshipEvidence(           // RENAMED + EXTENDED
    String fromTable, String fromColumn,
    String toTable, String toColumn,
    double confidence,
    EvidenceTier tier,                        // NEW
    List<EvidenceSource> sources,             // NEW (multi-source list)
    RelationshipCategory category,            // NEW
    Double orphanRatio,                       // NEW (sampling)
    Double typeCompatibilityScore,            // NEW
    boolean isComposite,                      // NEW
    List<String> compositeColumns             // NEW
) {}

// Yeni model'ler
public record ConstraintInfo(...) {}
public record IndexInfo(...) {}
public record StoredProcInfo(...) {}
public record TriggerInfo(...) {}
public record PartitionInfo(...) {}
public record WorkloadQuery(...) {}
public record SampleProfile(...) {}
```

### 2.4 Backward-compatible strategy

- Yeni alanlar `Optional` veya `nullable` default
- Mevcut endpoint'ler aynı response shape döner (yeni alanlar opsiyonel)
- Yeni endpoint'ler ayrı URL'ler (eskileri kırmaz)
- API versioning: `/api/v1/schema/*` korunur, advanced `/api/v2/schema/*` düşünülebilir (gerek yok ilk planda)

---

## 3. Frontend SchemaLens (mfe-schema-explorer) — Detaylı

### 3.1 Yeni UI sekmeleri (5-8)

| Sekme | İçerik |
|---|---|
| **Constraints** | FK + Unique + Check + Default constraint listesi, trust state |
| **Indexes** | Non-PK index'ler, fragmentation, fill factor, usage stats |
| **Storage** | Tablo başına size, LOB, filegroup, compression |
| **Partitioning** | Partition scheme + boundary + row count |
| **Programmability** | SP + func + trigger listesi + body preview + dependency graph |
| **Workload** | Top expensive queries, en çok join'lenen tablo çiftleri |
| **Data Profile** | Null ratio, distinct, top values, orphan metrics (opt-in) |
| **Security** | GRANT/DENY matrix, role membership, RLS |

### 3.2 Mevcut sekmelerin genişlemesi

| Sekme | Yeni özellik |
|---|---|
| **ER Graph** | Truth tier badge (authoritative FK ≠ inferred), relationship category renkleri |
| **Columns** | Precision/scale/collation/computed/unique görünümü |
| **Health** | Truth tier breakdown ("authoritative %", "inferred %", "missing %") |
| **Drift** | Authoritative drift vs inferred confidence drift ayrımı (renk + filter) |
| **AI Chat** | Annotation + sample context (PII safe) injected |

### 3.3 Truth Tier UI patterns

- Badge renkleri: `authoritative_mssql` (yeşil) / `inferred_metadata` (sarı) / `sampled_data` (turuncu) / `workload_observed` (mavi) / `manual_domain` (mor) / `unsupported` (gri)
- Tooltip her veri noktasında tier + confidence + source breakdown
- Filter dropdown: "sadece authoritative göster", "inferred dahil", vb.

---

## 4. MSSQL Kaynak (Workcube) Etkisi

### 4.1 Yeni sorgular (~20 yeni sys.* + DMV)

| Sorgu | Yük |
|---|---|
| `sys.foreign_keys`, `sys.foreign_key_columns` | Tek seferlik (cache) — küçük |
| `sys.indexes` (PK filter kaldırıldı) | Tek seferlik — orta |
| `sys.check_constraints`, `sys.default_constraints` | Küçük |
| `sys.computed_columns` | Küçük |
| `sys.dm_db_partition_stats` | Tablo başına — orta |
| `sys.dm_db_index_physical_stats` | **Pahalı** (sampled mode kullanılmalı) |
| `sys.dm_db_index_usage_stats` | Hafif |
| `sys.partitions + sys.partition_schemes + sys.partition_functions` | Hafif |
| `sys.sql_modules + sys.triggers + sys.sql_expression_dependencies` | Orta (body parse'da yük) |
| `sys.query_store_*` | **Çok pahalı** (Query Store enable + storage) |
| `sys.dm_exec_query_stats + plan cache` | Snapshot pahalı |
| Sampling: `SELECT TOP N FROM <table>` | **PII risk + load** |

### 4.2 Workcube tarafında gerekli değişiklikler

| İhtiyaç | Workcube DBA aksiyonu |
|---|---|
| Query Store aktif | `ALTER DATABASE SET QUERY_STORE = ON` (varsa zaten OK, yoksa enable) |
| Change Tracking | İstenen tablolarda enable (otomatik delta yakalama için) |
| Sampling permission | schema-service service account'a `SELECT` permission veri tablolarına |
| Read-only intent zaten var | `applicationIntent=ReadOnly` connection string — değişiklik yok |
| dm_* DMV permission | `VIEW DATABASE STATE` permission gerekli |

### 4.3 Load profili

- **Baseline (mevcut)**: ~1-2 saniye snapshot fetch, dakikada birkaç istek
- **Genişlemiş (sprint 1 sonrası)**: Snapshot 3-5 saniye, dakikada 5-10 istek
- **Full (sprint 2 + 3)**: İstek bazında değişken; sampling/workload sorguları timeout limitli (max 30sn)

**Mitigation**:
- Cache TTL agresif (canonical: 1 saat, sampling: 24 saat)
- Sampling rate limit (saatte 10 tablo)
- Query Store query'leri offset/batch'le
- DMV sorguları off-peak (gece batch)

---

## 5. Postgres Hedef (Schema-Service Kendi DB) — Yeni Şema

### 5.1 Yeni tablolar

```sql
-- Drift baseline persist
CREATE TABLE schema_drift_baseline (
  schema_name TEXT,
  object_type TEXT,
  object_name TEXT,
  fingerprint_hash TEXT,  -- canonical hash
  captured_at TIMESTAMPTZ
);

-- Annotation extended (semantic glossary)
CREATE TABLE schema_annotation (
  schema_name TEXT,
  table_name TEXT,
  column_name TEXT,        -- nullable (table-level annotation)
  annotation_type TEXT,    -- 'description', 'business_glossary', 'semantic_class', ...
  content JSONB,
  author TEXT,
  updated_at TIMESTAMPTZ
);

-- Workload cache
CREATE TABLE schema_workload_cache (
  query_hash TEXT,
  query_text TEXT,        -- truncated + masked
  total_execution_count BIGINT,
  total_elapsed_time_ms BIGINT,
  referenced_tables JSONB,
  captured_at TIMESTAMPTZ
);

-- Sample profile cache (PII masked)
CREATE TABLE schema_sample_profile (
  schema_name TEXT,
  table_name TEXT,
  column_name TEXT,
  null_ratio NUMERIC,
  distinct_count BIGINT,
  min_value TEXT,         -- masked if PII
  max_value TEXT,         -- masked if PII
  top_values JSONB,       -- masked
  captured_at TIMESTAMPTZ
);

-- Relationship evidence history
CREATE TABLE schema_relationship_evidence (
  from_table TEXT, from_column TEXT,
  to_table TEXT, to_column TEXT,
  tier TEXT,                  -- enum
  category TEXT,
  confidence NUMERIC,
  sources JSONB,
  orphan_ratio NUMERIC,
  captured_at TIMESTAMPTZ
);
```

### 5.2 Postgres storage etkisi

| Tablo | Tahmini hacim | Notlar |
|---|---|---|
| `schema_drift_baseline` | ~10 MB / aylık snapshot | Hash bazlı |
| `schema_annotation` | ~5-50 MB (DBA notlarına göre) | JSONB |
| `schema_workload_cache` | ~100 MB / haftalık (top 100 query) | Masked text |
| `schema_sample_profile` | ~50 MB / tüm tablolar | PII masked |
| `schema_relationship_evidence` | ~10 MB | Versioned |

**Toplam**: ~200-500 MB schema-service kendi DB. PostgreSQL için küçük.

---

## 6. Annex 2A YAML — Canonical Contract Genişlemesi

### 6.1 Yeni `_meta` alanları

```yaml
_meta:
  # Mevcut
  annex: 2A_report_runtime_source_surface
  status: DRAFT | SEALED
  seal_state: DRAFT | SEALED
  
  # YENİ — truth tier disclosure
  truth_tier_breakdown:
    authoritative_mssql:
      count: <int>
      confidence: high
    inferred_metadata:
      count: <int>
      confidence: 0.80-0.92
      techniques: [name_match, alias, common_fk, view_parse]
    sampled_data:
      count: <int>
      sampling_date: <date>
      pii_masked: true
    manual_domain:
      count: <int>
      reviewer: <name>
  
  # YENİ — schema cross-check evidence
  schema_validation:
    method: schema-service-endpoint
    endpoint: /api/v1/schema/snapshot?schema=<>
    captured_at: <timestamp>
    sourcequery_count: 8
    pass_count: 8
    real_fk_count: <int>
    inferred_fk_count: <int>
    unique_constraint_count: <int>
    check_constraint_count: <int>
```

### 6.2 Yeni `reports[]` alanları (her rapor için)

```yaml
- report: fin-cari-islemler
  # Mevcut
  source: sourceQuery
  migration_action_default: migrate
  manually_validated: true
  
  # YENİ
  sourcequery_validation:
    tables_used:
      canonical: [COMPANY, EMPLOYEES, ...]
      year_tenant: [CARI_ACTIONS, ACCOUNT_CARD, ...]
    real_fk_resolved: <int>
    inferred_fk_resolved: <int>
    unique_constraints_relied_on: [COMPANY.COMPANY_CODE, ...]
    check_constraints_documented: [...]
    procedure_dependencies: [...]  # sp_dependency parse
    trigger_dependencies: [...]
```

---

## 7. Report-Service Etkisi

### 7.1 Schema-service consume

Report-service `report-service/src/main/resources/reports/*.json` validation'da:

1. `sourceQuery` SQL'i parse et (yeni T-SQL parser)
2. Her tablo referansı için schema-service'e sor:
   - Tablo var mı (snapshot)?
   - Kolonlar uyumlu mu (column metadata)?
   - Unique constraint kullanılan kolonlarda var mı?
   - Check constraint validation rule var mı (PG'ye taşı)?
3. SourceQuery contract gate (existing) → genişletilmiş validation

### 7.2 ETL worker bağımlılığı

Faz 16.2.P (parametric ETL) artık schema discovery layer mevcut olduğu için **yeniden başlayabilir**:
- Manifest `source_instances` enrichment → schema-service'ten yearly tenant listesi
- Runner parametric expansion (1 manifest → N TableMeta) → schema cross-check
- V18 DDL generator extension → column expansion (precision/scale/computed) consume

**Effort**: Faz 16.2.P sprint kuyruğa eklenir (eski tahmin: 2-3 hafta).

---

## 8. AI Chat Kalite Etkisi

### 8.1 Yeni context injection

AI Chat prompt'a şunlar eklenecek:

1. **Annotation glossary** (manual_domain tier)
2. **Sampled data profile** (top values, distinct count — PII safe)
3. **Workload-derived examples** (gerçek view + procedure body)
4. **Truth tier disclosure** (AI cevabında "bu inferred mi authoritative mi" söyle)

### 8.2 Cevap kalitesi farkı

| Soru | Şimdi | Genişlemiş |
|---|---|---|
| "Müşteri başına aylık fatura?" | Tablo + kolon önerir | Tablo + örnek değer + tipik join + workload pattern |
| "ACCOUNT_CARD nedir?" | Kolon listesi | Annotation + sample data + business glossary + benzer view'lar |
| "Bu kolon unique mi?" | "Bilmiyorum" | "Evet, unique index var (authoritative)" veya "Hayır, inferred görünmüyor" |
| "Bu tablo silinirse ne olur?" | Heuristic FK chain | Real FK + heuristic FK + workload usage (gerçek bağımlılık) |

---

## 9. CLAUDE.md + PLAN.md + ADR Etkisi

### 9.1 CLAUDE.md değişiklikler

```diff
## Hızlı Bağlam — MSSQL Şema Gezgini

+ Truth tier modeli (authoritative_mssql / inferred_metadata / sampled_data / 
+   workload_observed / manual_domain / unsupported). Agent rapor verirken hangi
+   tier'dan veri aldığını belirtir.

+ Yeni capability'ler (PR #693 capability gap matrix sonrası):
+ - Real FK extraction (sys.foreign_keys)
+ - Unique + Check + Default constraint inventory
+ - Non-PK index inventory + health/usage
+ - Storage + partitioning + LOB
+ - Stored procedure + function + trigger inventory
+ - Query workload mining
+ - Data sampling (opt-in + PII masked)
+ - Business semantic dictionary

- Faz 16.2.P (parametric ETL) defer edildi
+ Faz 16.2.P parametric ETL şimdi schema discovery layer hazır — yeniden başlatma
+   şartı kalmadı (schema-service /snapshot?schema= ve /workload mevcut)
```

### 9.2 PLAN.md değişiklikler

```diff
#### Faz 16.2.P — Parametric (multi-tenant + yearly schema) ETL — ~~DEFERRED INDEFINITELY~~ ACTIVATED

**Karar tarihi**: 2026-05-15 (schema-service capability genişlemesi sonrası)
+ Schema discovery + workload mining + sampling layer'ları artık schema-service'te
+   mevcut; parametric ETL pipeline blocker'ı kalmadı.

**Kapsam dahil edilenler**:
+ 17 parametric tablo crawl → schema-service /snapshot?schema=workcube_mikrolink_<year>_<id>
+ source_axis_key + source_year_bucket partition design
+ V18 DDL generator extension
+ Manifest source_instances enrichment
+ Runner parametric expansion
+ schema-service yearly-schema crawl tool (zaten mevcut)
```

### 9.3 Yeni / güncel ADR'ler

| ADR | Konu | Status |
|---|---|---|
| ADR-0008 `schema-truth-integration` | Schema-service ve report-service contract | **Extend** — yeni capability'ler + truth tier |
| **ADR-00XX (yeni) `truth-tier-disclosure`** | Truth tier model + UI badge + report contract | **Yeni** — capability gap matrix verdict |
| **ADR-00XX (yeni) `pii-sampling-guardrail`** | Data sampling opt-in + masking + read-only mode | **Yeni** — sprint 3 prereq |
| ADR-0005 `dual-datasource-reporting` | §6 amendment (timezone + float + migration_action) | Adım 13 SEAL flip sonrası |
| ADR-0010 `report-service-faz-16-1` | Schema crawl section update | Mini-update |

---

## 10. DBA Workflow Etkisi

### 10.1 Yeni operasyonlar

| Görev | Sıklık | Effort |
|---|---|---|
| Annotation onboarding (DBA notları) | İlk seferlik | 2-3 saat (mevcut Workcube belgesinden) |
| Sampling opt-in karar (per tablo) | İlk seferlik | 1 saat (PII tablolarını işaretle) |
| MSSQL permission review (VIEW DATABASE STATE, SELECT) | İlk seferlik | 30 dk |
| Query Store enable | İlk seferlik | 15 dk |
| Drift baseline periodic update | Haftalık | 5 dk (otomatik) |

### 10.2 Adoption riskler

- **PII**: DBA hangi tabloların PII içerdiğini işaretlemeli; agent default-deny
- **Performance**: Sampling production saatlerinde değil, off-peak
- **Permission creep**: schema-service service account'a `VIEW DATABASE STATE` veriliyor; audit edilmeli

---

## 11. PII / Security Guardrail

### 11.1 Sampling güvenliği

```yaml
sample_data_endpoint:
  default: DISABLED
  enable_per_table: explicit opt-in
  masking:
    pii_columns: [NAME, EMAIL, PHONE, TC_NO, ADDRESS, ...]
    masking_rule: SHA256 prefix + length
  rate_limit: 10 tables/hour
  query_timeout: 30 seconds
  read_only_mode: enforced
  audit_log: every sample request
```

### 11.2 Workload data güvenliği

- Query Store'daki sorgular **truncated** (max 500 char)
- Parametric değerler **masked** (literal '?'  yerine konur)
- Schema-service kendi DB'sinde sadece **hash + masked text** saklanır

---

## 12. Toplam Effort + Roadmap

### Sprint planı (PR #693'ten)

| Sprint | Süre | Capability | Bileşen etkisi |
|---|---|---|---|
| 1 | 1-2 hafta | 10 authoritative (FK + unique + check + default + indexes + SP + storage + ...) | Backend service + model + endpoint |
| 2 | 1-2 hafta | 9 inferred + sampled (T-SQL parser + SP/trigger parse + workload + sampling) | Backend + Postgres cache + PII guardrail |
| 3 | 1 hafta | UX + truth tier UI | Frontend SchemaLens + annotation system |

**Toplam**: ~5-7 hafta + Faz 16.2.P unblock (2-3 hafta) = **~7-10 hafta**.

### Cross-AI yönetimi

Her sprint sonu:
- Codex paralel review (yeni thread)
- Cross-AI peer review HARD RULE
- Truth tier dokumantasyonu güncellemesi

---

## 13. Karar Matrisi — Genişleme yapılmalı mı?

| Senaryo | Mevcut yeterli mi? | Genişleme ROI |
|---|---|---|
| **Adım 13 SEAL (sourceQuery review)** | 8/8 PASS, baseline yeterli | T-SQL parser + workload mining → SEAL daha güvenilir |
| **Faz 17 migration** | Eksik (real FK, unique, check, default, SP/trigger, CDC) | **Yüksek ROI** — migration güvenliği için kritik |
| **AI Chat kalitesi** | Generic cevap | Semantic + sample + workload → iş anlamında doğru cevap |
| **Drift detection** | Hash-less, gürültülü | Stable hash + diff → operations team faydası |
| **Reporting team yeni rapor** | Mevcut snapshot yeterli | Constraint + index → performans risk önceden görünür |

**Net**: Genişleme **Faz 17 migration + AI Chat** için **kritik ROI**. SEAL + reporting için **fayda var ama acil değil**.

---

## 14. Önerilen sıra (öncelik)

1. **Hemen** (Sprint 1): Real FK + Unique + Check + Default + Indexes + SP/trigger + Column expansion + Storage + CDC + DB options
2. **Sonra** (Sprint 2): T-SQL parser + Workload mining + Data sampling (PII guardrail)
3. **Sonra** (Sprint 3): Truth tier UI + Annotation extended + Business semantic
4. **Paralel** (Faz 16.2.P unblock): Parametric ETL pipeline (deferred sprint açılır)

---

## 15. Referans

- PR #693 Capability gap matrix (30 madde detay)
- PR #691 Detected vs inferred vs missing baseline
- PR #690 Uçtan uca capability + decision tree
- PR #688 Genel rehber
- Codex thread `019e2c59` (Adım 13 SEAL + docs)
- Codex thread `019e2cca` (capability gap paralel review)
- ADR-0008 schema-truth-integration
- PLAN.md Faz 16.2.P (deferred → unblock candidate)
