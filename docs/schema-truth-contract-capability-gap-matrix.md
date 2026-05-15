# Schema Truth Contract — Capability Gap Matrix

> **Cross-AI consensus**: Codex thread `019e2cca-e7d6-70f3-96b8-ae5fd2b21133` iter-1 paralel review + Claude analizi. Schema-service'in **detected + inferred + missing** üçlüsünü PR #691 baseline olarak vermişti; bu doküman **expanded truth contract** — Faz 17 migration, Adım 13 SEAL, AI Chat kalitesi, drift detection senaryolarına göre karar dayanağı.
>
> **Tarih**: 2026-05-15  
> **Önemli düzeltme**: Mevcut `Relationship` modeli "FK truth" gibi sunulmamalı — **"relationship evidence with confidence"** olarak değerlendirilmeli.

---

## 0. Truth Tier modeli (öneri)

Her capability bilgisi şu sınıflara ayrılır:

| Tier | Tanım | Örnek |
|---|---|---|
| `authoritative_mssql` | sys.* doğrudan extraction | PK, identity, nullable, type |
| `inferred_metadata` | Naming + alias + view parse heuristic | FK ilişkisi (current Relationship) |
| `sampled_data` | Gerçek veri örneklemesi | Orphan ratio, null ratio, distinct count |
| `workload_observed` | Query Store / plan cache | En çok join'lenen tablo çiftleri |
| `manual_domain` | DBA annotation | Business glossary, semantic class |
| `unsupported` | Sorgulanmıyor / kapsam dışı | Triggers, check constraints (şu an) |

Her tier'ın **confidence semantics** farklı. `authoritative_mssql` ile `inferred_metadata` aynı renkte gösterilmemeli.

---

## 1. İlişki Belirleme — Capability Matrix

### 1.1 Mevcut (kaynak kodda)

| # | Teknik | Tier | Confidence | Kaynak | Notlar |
|---|---|---|---|---|---|
| 1 | Name match exact | inferred_metadata | 0.85 | `*_ID → *` | `RelationshipDiscoveryService:95-112` |
| 2 | Name match plural | inferred_metadata | 0.80 | `*_ID → *S` | Aynı |
| 3 | Alias map | inferred_metadata | 0.90 | 40+ predefined (`COMP_ID/CMP_ID/MANAGER_ID/...→COMPANY|EMPLOYEES|...`) | Hard-coded |
| 4 | Common FK map | inferred_metadata | 0.92 | 25 standart (`COMPANY_ID→COMPANY`) | Hard-coded |
| 5 | View parse | inferred_metadata | 0.88 | regex `(\w+)\.(\w+) = (\w+)\.(\w+)` | View SQL'lerinden |

### 1.2 Eksik — Codex iter-1 önerileri

| # | Teknik | Tier | Etki | Öncelik | Effort |
|---|---|---|---|---|---|
| 1 | **Real FK extraction** (`sys.foreign_keys`, `sys.foreign_key_columns`, `is_disabled`, `is_not_trusted`, cascade actions, schema-qualified target) | authoritative_mssql | Workcube'da FK az veya yok; "yok" da authoritative truth | P0 | 1-2 saat |
| 2 | **Unique constraint discovery** (`sys.indexes WHERE is_unique=1`, `CODE/NO/UUID` columns) | authoritative_mssql | ERP'de ilişki sık unique key'e kuruludur, PK değil | P0 | 1 saat |
| 3 | **Composite relationship inference** | inferred_metadata | `COMPANY_ID + PERIOD_ID + RECORD_ID` çok kolonlu scope ilişkileri | P1 | 4-6 saat |
| 4 | **Type/length/collation compatibility scoring** | inferred_metadata (boost) | `fromColumn` ve `toColumn` uyumsuz tip → confidence düşür | P1 | 2-3 saat |
| 5 | **Data-overlap sampling** (candidate FK orphan ratio, distinct overlap, null ratio) | sampled_data | "Gerçek değer overlap %" en güçlü inferred evidence | P0 | 1-2 gün |
| 6 | **Cardinality/distribution match** | sampled_data (boost) | Doğrulama katmanı (status_id, type_id'de yanıltıcı) | P2 | 4-6 saat |
| 7 | **T-SQL parser** (regex yerine) | inferred_metadata | Alias, bracket identifier, schema prefix, CTE, subquery, LEFT JOIN, APPLY support | P1 | 2-3 gün |
| 8 | **Stored proc/function/trigger parse** | inferred_metadata + workload_observed | ERP business logic çoğunlukla T-SQL gövdelerinde | P0 (SEAL) | 1-2 gün |
| 9 | **Query workload mining** (`sys.dm_exec_query_stats`, Query Store, plan cache, reporting sourceQuery) | workload_observed | "Schema neye izin veriyor" değil "sistem ne kullanıyor" | P0 (SEAL+AI) | 1 gün |
| 10 | **Domain naming convention dictionary versioning** | manual_domain | Hard-coded alias map → owner + source + date + version | P1 | 4-6 saat |
| 11 | **Relationship category ayrımı** (tenant scope / audit / lookup / hierarchy / polymorphic / true FK) | manual_domain + inferred_metadata | "Her *_ID aynı tip değildir" | P1 | 1 gün |
| 12 | **Negative evidence** (orphan yüksek + type mismatch + generic name → confidence düşür) | sampled_data + inferred_metadata | False positive bastırma | P1 | 4-6 saat |

---

## 2. Metadata — Capability Matrix

### 2.1 Mevcut

| Capability | Tier | Kaynak |
|---|---|---|
| PK | authoritative_mssql | `sys.indexes WHERE is_primary_key=1` |
| Identity | authoritative_mssql | `c.is_identity` |
| Nullable | authoritative_mssql | `c.is_nullable` |
| Data type + max_length + ordinal | authoritative_mssql | `sys.columns + sys.types` |
| Row count | authoritative_mssql | `sys.partitions` (heap+clustered) |
| View definitions | authoritative_mssql | `sys.sql_modules WHERE type='V'` |
| Schema list | authoritative_mssql | `sys.schemas` |

### 2.2 Eksik — Codex iter-1 önerileri

| # | Capability | Tier | MSSQL Query/DMV | Öncelik | Risk if Missing | Effort |
|---|---|---|---|---|---|---|
| 1 | **Object inventory** (schema, object_id, type, create/modify date, owner, extended properties) | authoritative_mssql | `sys.objects`, `sys.extended_properties` | P0 | `dbo.X` vs `workcube.X` ayrımı yok | 2-3 saat |
| 2 | **Column metadata genişletme** (precision, scale, collation, default expression, computed expression, persisted, sparse, rowguid, encryption/masking) | authoritative_mssql | `sys.columns + sys.computed_columns + sys.default_constraints` | P0 (Faz 17) | DECIMAL precision/scale yok → currency drift | 4-6 saat |
| 3 | **Constraint inventory** (FK + unique + check + default + trust/disabled state) | authoritative_mssql | `sys.foreign_keys + sys.indexes (is_unique) + sys.check_constraints + sys.default_constraints` | **P0** | Check/default eksik → PG migration validation rules kayıp | 1 gün |
| 4 | **Non-PK index inventory** (key cols, included cols, filter predicate, uniqueness, sort direction, fill factor, compression, disabled/hypothetical) | authoritative_mssql | `sys.indexes + sys.index_columns + sys.partitions` | P0 (SEAL) | sourceQuery review + PG index tasarımı kör | 1 gün |
| 5 | **Index health + usage** (fragmentation %, page_count, seeks/scans/lookups/updates, last used) | sampled_data + workload_observed | `sys.dm_db_index_physical_stats + sys.dm_db_index_usage_stats` | P1 | "Index var" ≠ "kullanılıyor / taşı / sil" | 1 gün |
| 6 | **Storage size + LOB** (reserved/used/data/index/LOB size, compression, filegroup) | authoritative_mssql | `sys.dm_db_partition_stats + sp_spaceused` | P0 (Faz 17) | Cutover plan row_count değil, hacim+LOB ile zorlanır | 4-6 saat |
| 7 | **Partitioning + filegroup + compression** (partition scheme/function, boundary values, row counts per partition) | authoritative_mssql | `sys.partitions + sys.partition_schemes + sys.partition_functions` | P1 | Hot/cold ayrım göz ardı | 4-6 saat |
| 8 | **Programmability inventory** (SP + scalar/TVF/iTVF + trigger gövdeleri + `sys.sql_expression_dependencies`) | authoritative_mssql | `sys.sql_modules + sys.triggers + sys.sql_expression_dependencies` | **P0 (SEAL)** | ERP davranışı SQL objelerinde gizli | 1-2 gün |
| 9 | **Indexed/materialized view** (schema-bound, WITH SCHEMABINDING flag) | authoritative_mssql | `sys.indexes WHERE object_id = view_id` | P1 | PG'de normal view'a düşerse performans drift | 4-6 saat |
| 10 | **Synonym + linked server + cross-database reference** | authoritative_mssql | `sys.synonyms + sys.servers` | P1 | Workcube raporu başka DB/server'a bakıyorsa kayıp | 4-6 saat |
| 11 | **Statistics + histogram** (sys.stats + dm_db_stats_properties + top values) | sampled_data | `sys.stats + sys.dm_db_stats_properties + dm_db_stats_histogram` | P2 | İlişki doğrulama + skew tespiti | 1 gün |
| 12 | **Query workload metadata** (Query Store, en pahalı sorgular, en çok join'lenen tablo çiftleri) | workload_observed | `sys.query_store_*` veya `sys.dm_exec_query_stats` | **P0 (SEAL+AI)** | "Schema'da var" ≠ "sistem kullanıyor" | 1-2 gün |
| 13 | **CDC / Change Tracking / replication / temporal** | authoritative_mssql | `sys.tables.is_tracked_by_cdc + sys.change_tracking_tables + sys.system_internals_partitions` | **P0 (Faz 17)** | Delta sync + cutover window + rollback strategy | 1 gün |
| 14 | **Security + permissions** (GRANT/DENY, role membership, ownership, RLS, module signing) | authoritative_mssql | `sys.database_permissions + sys.database_role_members + sys.security_policies` | P1 | Migration sonrası least-privilege + RLS davranışı | 1 gün |
| 15 | **Database-level options** (recovery model, compatibility level, collation, isolation/RCSI, ANSI settings, backup/log size) | authoritative_mssql | `sys.databases` | P1 | Migration risk ölçümü | 2-3 saat |
| 16 | **Sequence, UDT, XML/spatial/full-text/CLR** | authoritative_mssql | `sys.sequences + sys.types + sys.fulltext_*` | P2 | "Desteklemiyor" vs "yok" ayrımı | 1 gün |
| 17 | **Sample data / data profiling** (null ratio, distinct count, min/max, top values, invalid date/currency, duplicate candidate keys, orphan metrics) | sampled_data | Direkt sorgu (PII masked, opt-in) | **P1** | AI Chat + migration validation | 2-3 gün (PII guardrail dahil) |
| 18 | **Business semantic metadata** (table/column descriptions, domain dictionary, scope kolonu, status code sözlükleri, audit kolonları) | manual_domain | Yeni table (`schema_annotations`) | P1 | SchemaLens UI > ham ERD | 1-2 gün |

---

## 3. Senaryo-bazlı Öncelik Matrisi (Codex iter-1 §C)

### 3.1 Faz 17 Migration (Workcube → Postgres cutover)

**P0**:
- Authoritative DDL truth (precision, scale, collation, default, computed)
- Constraint inventory (FK + unique + check + default)
- Index inventory (non-PK)
- Identity / sequence semantics
- Storage size + LOB
- Partitioning + filegroup
- Programmability inventory (SP + func + trigger)
- CDC / Change Tracking
- Database-level options

**P1**:
- Data quality + orphan metrics
- Indexed/materialized view
- Synonym + linked server

**Sebep**: İlişki inference faydalı ama migration'ı bozan asıl şey gizli SQL logic, veri tipi semantiği, delta yakalama, performans farkı.

### 3.2 Adım 13 SEAL (Reporting team sourceQuery review)

**P0**:
- SourceQuery lineage parser (T-SQL parser, view + procedure dependency)
- Stored proc + function + trigger parse
- Query workload mining (gerçek kullanım)
- Non-PK index inventory (performans)

**P1**:
- Workload + index usage
- Unique constraint discovery (business key)

**Sebep**: Mevcut relationship inference SEAL'i destekler ama asıl kanıt **doğrudan SQL dependency extraction**.

### 3.3 AI Chat Kalitesi

**P0**:
- Semantic dictionary
- Validated relationships (confidence + multi-source)
- Sample/profile evidence (null ratio, distinct, top values)

**P1**:
- Workload-derived examples (gerçek view + procedure örnekleri)
- AI'a "bu veri nasıl sorulur?" bağlamı

**Sebep**: AI sadece `*_ID → table` inference verirse teknik olarak akıcı ama iş anlamında hatalı cevap üretir. Semantic + örnek + workload şart.

### 3.4 Drift Detection

**P0**:
- Stable snapshot + hash + diff (columns, types, defaults, computed, constraints, indexes, views, procs, functions, triggers, permissions, dependencies)

**P1**:
- Row count + statistics + storage drift (daha gürültülü)
- Inferred relationship confidence drift (authoritative drift değil)

**Sebep**: Drift ekranı authoritative drift ile inferred drift'i **aynı renkte göstermemeli**.

### 3.5 Cross-Scenario P0

- **Truth tier modeli**: Her bilgi `authoritative_mssql | inferred_metadata | sampled_data | workload_observed | manual_domain | unsupported` sınıflanmalı
- **Cost + safety guardrail**: Sampling, histogram, Query Store ve body parse → read-only mode, sampling limit, masking, query timeout (PII risk)

---

## 4. Model değişikliği önerisi

### Mevcut

```java
public record ColumnInfo(name, dataType, maxLength, nullable, identity, pk, ordinal) {}

public record Relationship(fromTable, fromColumn, toTable, toColumn, confidence, source, multiSource) {}
```

### Önerilen (Codex iter-1 + Claude)

```java
public record ColumnInfo(
    String name,
    String dataType,
    int maxLength,
    Integer precision,         // NEW (DECIMAL/NUMERIC)
    Integer scale,             // NEW
    String collation,          // NEW
    boolean nullable,
    boolean identity,
    Long identitySeed,         // NEW
    Long identityIncrement,    // NEW
    boolean pk,
    boolean unique,            // NEW (sys.indexes is_unique=1)
    String defaultExpression,  // NEW (sys.default_constraints)
    String computedExpression, // NEW (sys.computed_columns)
    boolean persisted,         // NEW (computed column persisted?)
    boolean sparse,            // NEW
    int ordinal
) {}

public record RelationshipEvidence(
    String fromTable,
    String fromColumn,
    String toTable,
    String toColumn,
    double confidence,         // 0.0 - 1.0
    EvidenceTier tier,         // NEW: AUTHORITATIVE_FK | INFERRED_METADATA | SAMPLED_DATA | WORKLOAD_OBSERVED
    List<EvidenceSource> sources,  // NEW: multi-source list (name_match, alias, common_fk, view_parse, fk_constraint, data_overlap, ...)
    RelationshipCategory category, // NEW: TENANT_SCOPE | AUDIT_REFERENCE | LOOKUP | HIERARCHY | POLYMORPHIC | TRUE_FK | UNKNOWN
    Double orphanRatio,        // NEW (sampling sonucu, optional)
    Double typeCompatibilityScore, // NEW
    boolean isComposite,       // NEW (composite key relationship)
    List<String> compositeColumns // NEW (composite ise)
) {}

public enum EvidenceTier { AUTHORITATIVE_FK, INFERRED_METADATA, SAMPLED_DATA, WORKLOAD_OBSERVED }
public enum RelationshipCategory { TENANT_SCOPE, AUDIT_REFERENCE, LOOKUP, HIERARCHY, POLYMORPHIC, TRUE_FK, UNKNOWN }
```

**Migration**: Backward-compatible — yeni alanlar `Optional` veya `nullable` default. UI sekme zenginleşir.

---

## 5. Implementation Roadmap (Codex iter-1 §C + Claude)

### Sprint 1 (1-2 hafta) — Authoritative truth tabanı

| # | Capability | Effort | Owner |
|---|---|---|---|
| 1 | `sys.foreign_keys` extraction (real FK truth) | 1-2 saat | backend |
| 2 | `sys.indexes is_unique=1` (unique constraint) | 1 saat | backend |
| 3 | `sys.check_constraints` + `sys.default_constraints` | 1 saat | backend |
| 4 | Non-PK indexes (`sys.indexes` PK filter kaldır + IndexInfo model) | 4 saat | backend |
| 5 | Programmability inventory (SP + func + trigger) | 1-2 gün | backend |
| 6 | Column precision/scale/collation/computed/default | 4-6 saat | backend |
| 7 | Storage size + LOB (`sys.dm_db_partition_stats`) | 4 saat | backend |
| 8 | Object inventory (extended properties, owner, dates) | 2 saat | backend |
| 9 | CDC / Change Tracking detection | 1 gün | backend |
| 10 | Database-level options | 2 saat | backend |

### Sprint 2 (1-2 hafta) — Inferred + sampled

| # | Capability | Effort | Owner |
|---|---|---|---|
| 11 | T-SQL parser (regex yerine) | 2-3 gün | backend |
| 12 | Stored proc + trigger parse (dependency graph) | 1-2 gün | backend |
| 13 | Query workload mining (Query Store / DMV) | 1-2 gün | backend |
| 14 | Data-overlap sampling (PII guardrail + opt-in) | 2-3 gün | backend |
| 15 | Type/length/collation compatibility scoring | 2-3 saat | backend |
| 16 | Composite relationship inference | 4-6 saat | backend |
| 17 | Negative evidence (orphan + type mismatch) | 4-6 saat | backend |
| 18 | Relationship category ayrımı (tenant/audit/lookup/...) | 1 gün | backend |
| 19 | Domain dictionary versioning | 4-6 saat | backend |

### Sprint 3 (1 hafta) — UX + truth tier

| # | Capability | Effort | Owner |
|---|---|---|---|
| 20 | Truth tier modeli (model + UI badge) | 1 gün | full-stack |
| 21 | Drift authoritative vs inferred ayrımı (UI) | 1 gün | frontend |
| 22 | Annotation system genişletme (semantic glossary) | 1-2 gün | full-stack |
| 23 | Business semantic metadata layer | 1-2 gün | full-stack |
| 24 | Sample data masked preview (PII safe) | 1 gün | full-stack |

**Toplam**: ~5-7 hafta (3 sprint) — schema-service kapsamı **2-3 kat** genişler.

---

## 6. Hangi capability hangi senaryoda gerekli (cross-reference)

| Capability | Migration | SEAL | AI Chat | Drift |
|---|---|---|---|---|
| Real FK extraction | ✓ P0 | ✓ P0 | ✓ P1 | ✓ P0 |
| Unique constraint | ✓ P0 | ✓ P0 | ✓ P1 | ✓ P0 |
| Check + default | ✓ P0 | ✓ P1 | ✓ P1 | ✓ P0 |
| Column precision/scale | ✓ P0 | ✓ P1 | ✓ P1 | ✓ P0 |
| Computed columns | ✓ P0 | ✓ P1 | ✓ P1 | ✓ P0 |
| Non-PK indexes | ✓ P1 | ✓ P0 | ✓ P1 | ✓ P1 |
| Storage size + LOB | ✓ P0 | ✓ P1 | — | ✓ P1 |
| Programmability (SP+trigger) | ✓ P0 | ✓ P0 | ✓ P0 | ✓ P0 |
| Query workload | — | ✓ P0 | ✓ P0 | ✓ P1 |
| Data sampling | ✓ P1 | ✓ P1 | ✓ P1 | — |
| CDC / Change tracking | ✓ P0 | — | — | ✓ P0 |
| Index health/usage | ✓ P1 | ✓ P1 | — | ✓ P1 |
| T-SQL parser | ✓ P1 | ✓ P0 | ✓ P1 | ✓ P1 |
| Relationship category | — | ✓ P1 | ✓ P0 | — |
| Business semantic | — | ✓ P1 | ✓ P0 | — |
| Truth tier model | ✓ P0 | ✓ P0 | ✓ P0 | ✓ P0 |
| Cost + safety guardrail | ✓ P0 | ✓ P0 | ✓ P0 | ✓ P0 |

---

## 7. Agent için kullanım kuralları (güncellenmiş)

CLAUDE.md kural #9 drift guard + bu doc:

- ✅ Agent `snapshot.relationships[]` confidence-based güvenebilir (0.80-0.92)
- ✅ Agent canlı endpoint kullanır (`/snapshot?schema=<>`)
- ❌ Agent "bu kolon unique" iddiası **yapamaz** — schema-service vermiyor
- ❌ Agent "bu tablonun trigger'ı yok" iddiası **yapamaz** — schema-service bakmıyor
- ❌ Agent "real FK constraint var" iddiası **yapamaz** — Workcube'da yok + schema-service sorgulamıyor
- ✅ Agent eksik bilgi için **DBA için MSSQL sorgu script** tasarlar (kullanıcı koşturur)
- ✅ Agent truth tier modelini takip eder; `authoritative_mssql` ile `inferred_metadata` ayrı raporlar
- ✅ Sample data sorgusu **opt-in + masked + read-only** olmadan agent koşturmaz (PII risk)

---

## 8. Cross-AI Trace

```yaml
implementer_ai: Claude
reviewer_ai: Codex
codex_threads:
  019e2c59-1cdb-7ea3-a8e6-bf3fcabc62b2: Adim 13 SEAL packet + docs-truth + capability map zinciri
  019e2cca-e7d6-70f3-96b8-ae5fd2b21133: Bu PR'in capability gap matrix paralel review (30 madde)
verdict: AGREE — expanded truth doc lazim oldu; PR #691 baseline yeterli ama
         Faz 17 / SEAL / AI Chat / Drift kararlari icin tek basina yetersiz.
key_finding: |
  Mevcut Relationship modeli "FK truth" gibi sunulmamali; "relationship
  evidence with confidence" olarak yeniden adlandirilmali. Truth tier
  ayrimi (authoritative vs inferred vs sampled vs workload) SchemaLens UI
  ve karar veren ekip icin kritik.
```

---

## 9. Referans

| Doküman | Konu |
|---|---|
| `docs/schema-service-and-schemalens-guide.md` (PR #688) | Genel rehber |
| `docs/schema-service-capability-map.md` (PR #690) | Uçtan uca + decision tree |
| `docs/schema-service-detected-vs-inferred-truth.md` (PR #691) | Detected vs inferred vs missing (baseline) |
| Bu doc | Truth contract + capability gap matrix (expanded) |
| Codex thread `019e2cca` | Capability gap paralel review (30 madde) |
| Kaynak kod | `platform-backend/schema-service/src/main/java/com/example/schema/` |
