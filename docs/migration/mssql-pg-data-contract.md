# Data Contract — Workcube MSSQL → Platform PG

> **STATUS**: DRAFT / RFC — **Inventory Pending**
> **SEAL STATE**: DRAFT → REVIEWED → **SEALED** (bu doc `DRAFT` aşamasında; Faz 16.1 inventory sonunda `SEALED` geçer)
> **Owner**: Platform team (drafter) · Workcube admin (freeze owner) · Backend lead (schema owner)
> **Last updated**: 2026-04-24 (Session 29)
> **Codex adversarial review**: thread `019dbe92`, iter-1 REVISE → iter-2 PARTIAL → iter-3 PARTIAL → **iter-4 AGREE** (DRAFT/RFC seviyesinde)
> **Linked ADR**: `docs/adr/0002-single-host-dual-cluster.md` D31 (PG primary kontratı)

---

## 1. Purpose + Scope

Bu kontrat **Faz 16.0 deliverable**'ıdır (PLAN.md §16.0). ETL öncesi mühürlenir; 16.1 inventory + 16.2 Flyway target schema + 16.3 ETL worker bu kontrata referans verir. ADR-0002 D31 "PG primary, MSSQL secondary/opsiyonel" kontratının veri-gerçekliği zeminidir.

### İki Katmanlı Kontrat Modeli

- **Katman 1 (bu doc, "general contract")**: Type mapping genel kuralları, soft-delete semantics, freeze policy, acceptance framework — **inventory-independent**
- **Katman 2 (annex, 16.1 inventory sonrası mühürlenir)**: Actual runtime source surface + observed-type inventory + per-table classification. İki alt-annex:
  - **2A — `report-runtime-source-surface`**: platform-ssot report-service JSON registry crawler
  - **2B — `schema-introspection-surface`**: platform-ssot schema-service MSSQL meta-catalog yüzeyi

### Governs (authoritative)

1. Her runtime-consumed MSSQL tablosu için taşıma kararı (`authoritative_source_today` + `class (future)` + `operational_owner` + `migration_action`)
2. Type mapping matrisi (observed types, encounter policy)
3. Soft-delete semantics + partial index/view pattern
4. Idempotency keys (stable IDENTITY vs hybrid UUID)
5. FK load order + circular resolution (staging/raw + `NOT VALID/VALIDATE`)
6. Unicode + encoding (`driver-based streaming read primary`)
7. NULL vs empty string policy
8. Write-freeze window (pre-seed + freeze-time final delta kontratı)
9. Backup retention minimum + legal override

### Does NOT govern

- Runtime query behavior (index selection, query plan tuning)
- API contract (schema-service / report-service endpoint şemaları — platform-ssot OpenAPI)
- CDC / continuous delta sync (PLAN.md §16.4 SKIP)
- MSSQL off-switch sıralaması (PLAN.md §16.5 runbook kapsamı)
- Feature flag mechanics (`*_MSSQL_ENABLED` — runbook)

> Kontrat *karar* mühürler; runbook *eylem* sırası verir. Ayrı dosyalar.

---

## 2. Table Classification Framework

### 2.1 Sınıf tanımları

| Sınıf | Tanım | PG post-cutover | Source-of-truth (post-cutover) |
|---|---|---|---|
| `authoritative` | Canonical truth. MSSQL'e yazım durur. | Full replica; write path PG | **PG** |
| `cache-reference` | Read-only enrichment. MSSQL canlı, PG periodic snapshot. | Read replica (stale tolerable) | **MSSQL** (PG'den okunur) |
| `skip` | Taşınmaz. PG referansı yok. | Yok | N/A |

### 2.2 Karar Matrisi — yeni 4 kolon

| Table | `authoritative_source_today` | `class (future)` | `operational_owner` | `migration_action` | PG target |
|---|---|---|---|---|---|
| `custom_reports` | **PG** (V2__custom_reports.sql) | N/A | platform-team | `already_pg_owned` | — |
| `user_service.users` (platform) | **PG** (V1__create_user_schema.sql) | N/A | platform-team | `already_pg_owned` | — |
| `permission_db.permissions` (platform) | **PG + code-defined** (PermissionCatalogService, V2__authz_scopes.sql) | N/A | platform-team | `already_pg_owned` | — |
| `REPORTS` (MSSQL) | MSSQL | authoritative (post-cutover) | Workcube admin | `freeze_backup_bulk_pre_seed_final_delta` | `reports_db.reports` |
| `EMPLOYEE_POSITIONS`, `INVOICE`, `ORDER_ROW`, `ACNIELSEN_REPORTS`, ... (annex 2A kapsamı) | MSSQL | `pending_annex` | Workcube admin | `pending_annex` | — |

**Kritik**: PLAN.md'deki "kritik 6 tablo (REPORTS/SAVED_REPORTS/custom_reports/PERMISSIONS/MODULES/USERS)" pre-classification **yanlış eksende**. `custom_reports`, `users`, `permissions`, `modules` zaten PG/code-defined. Gerçek MSSQL-source yüzeyi annex 2A + 2B çıktısı olmadan mühürlenemez. **6-tablo staged contract modeli iptal**; yerine "general contract + annex" iki katmanlı model.

### 2.3 `migration_action` Enum

| Enum | Anlam | Sorumlu |
|---|---|---|
| `freeze_backup_bulk_pre_seed_final_delta` | Authoritative source (annex 2A): freeze öncesi bulk, freeze içinde final delta | Workcube admin + platform-team |
| `cache_snapshot_periodic` | Cache-reference (annex 2A): ERP canlı, periyodik PG snapshot | platform-team |
| `metadata_snapshot_refresh` | Schema-introspection (annex 2B): ETL-ed metadata kararı, periyodik refresh | platform-team |
| `live_pg_catalog` | Schema-introspection (annex 2B): Live PG catalog kararı, ETL yok | platform-team (read-only) |
| `already_pg_owned` | Zaten PG'de canonical | platform-team |
| `skip_no_migrate` | Bilinçli skip (ERP-internal, platform kullanmaz) | platform-team + Workcube admin |
| `manual_transform` | Special-case: computed column, semantic transform, complex UDF | backend lead |
| `pending_annex` | Annex 2A/2B classify bekleniyor (**sadece pre-16.1-seal geçerli; post-seal = acceptance fail**) | TBD |

`already_pg_owned` ≠ `skip_no_migrate`: paydaş için "zaten bizde" vs "taşımayacağız" farklı eylemsizlik.

---

## 3. Annex 2A — Report Runtime Source Surface

### 3.1 Scope

Platform-ssot `backend/report-service/src/main/resources/reports/*.json` 31 rapor tanımı. Runtime'da `ReportRegistry` + `SqlBuilder` tarafından execute edilen MSSQL yüzeyi annex'e girer.

### 3.2 Extraction Hierarchy

1. **Direct `source` field**: JSON `source` → `schema.table` direct
2. **`sourceQuery` AST/regex parse** (31'den 8 rapor: `fin-fatura-satirlari`, `fin-tutar-mutabakat`, `fin-muhasebe-detay`, `fin-kaynak-eslesme`, vb.):
   - `FROM <table>` extract
   - `JOIN <table>` extract (INNER/LEFT/RIGHT/CROSS/OUTER)
   - Subquery recursive parse: `FROM ( SELECT ... FROM <tables> )`
   - Cross-schema: `[db].[schema].[table]` → explicit split
   - CTE: `WITH cte AS (SELECT ... FROM <tables>)` → dependencies
3. **`{schema}` template expansion**: `{schema}.INVOICE` runtime substitution; annex'te `schema=UNKNOWN_AT_PARSE`, Workcube admin resolve
4. **Parametric schema**: `{module}_INVOICES` runtime template → annex'te parametric flag, actual instantiation 16.1'de enumerate

> **`sourceQuery` extraction is automation-assisted; every `sourceQuery` report requires manual validation before annex seal.**

Tam otomasyon için regex/parser-assisted extraction (sqlparse değil, T-SQL-aware grammar) + manuel review zorunlu. MVP: regex + 8 rapor manuel QA.

### 3.3 Annex Format

`docs/migration/report-source-annex.yaml` (16.1 deliverable):

```yaml
- report: fin-fatura-satirlari
  extraction_method: sourceQuery
  manually_validated: true
  tables:
    - schema: dbo
      name: INVOICE
      class: authoritative
      migration_action: freeze_backup_bulk_pre_seed_final_delta
    - schema: dbo
      name: ORDER_ROW
      join_type: LEFT
      class: authoritative
      migration_action: freeze_backup_bulk_pre_seed_final_delta
  parametric_schemas: []
  contains_nolock_hint: true
```

### 3.4 SEAL gate (16.1 sonunda)

- [ ] 31 rapor extracted
- [ ] 8 `sourceQuery` rapor manuel validated
- [ ] Zero `schema=UNKNOWN_AT_PARSE` (Workcube admin resolve etti)
- [ ] Zero `pending_annex` (tüm tablolar classify)
- [ ] `{module}` parametric schema'lar enumerate edildi

---

## 4. Annex 2B — Schema-Introspection Surface

### 4.1 Scope

Platform-ssot `backend/schema-service/` `SchemaExtractService.java` + `SchemaSnapshotService.java` tarafından okunan MSSQL meta-catalog yüzeyi:

- `sys.tables`
- `sys.columns`
- `sys.sql_modules` (view/procedure definition)
- `sys.partitions`
- `sys.foreign_keys`, `sys.indexes`, `sys.index_columns`

### 4.2 Schema-Service Parity Decision (16.1 gate)

**KRITIK KARAR** — 16.1 sonunda mühürlenir, 16.2 Flyway ve 16.3 ETL worker design'ını direkt etkiler:

| Seçenek | Açıklama | Trade-off |
|---|---|---|
| **A. Live PG catalog** | `pg_tables`, `pg_attribute`, `pg_views` doğrudan sorgu | Dinamik, güncel; MSSQL meta-catalog bire-bir eşlenmeyebilir |
| **B. ETL-ed metadata snapshot** | Periyodik refresh (örn. günlük) snapshot tablosu | Stale risk; annex 2B kapsamında iyi-tanımlı |

Karar `docs/migration/schema-service-parity-adr.md` (kısa ADR) içinde gerekçelendirilir. 16.5 cutover sadece **verify** kapısı — decision 16.1'de seal.

### 4.3 Annex Entry Format

`docs/migration/schema-introspection-annex.yaml`:

```yaml
- object_type: view
  schema: dbo
  name: v_active_invoices
  definition_source: sys.sql_modules
  migration_action: metadata_snapshot_refresh  # veya live_pg_catalog
  observed_types: [nvarchar, int, decimal, datetime]
```

### 4.4 2A / 2B İlişkisi

**Ortogonal** (bağımsız değil, çakışma değil): aynı obje iki annex'te görünebilir. `INVOICE` → 2A'da business-read surface + 2B'de introspected object. Key: `surface_role + schema + object_name`.

---

## 5. Observed Type Inventory

### 5.1 Snapshot Kaynak

`schema-docs-mssql-35/workcube_mikrolink*.xml` — 607 tablo MSSQL katalogu.

### 5.2 Observed (present in snapshot)

Dominant: `int`, `nvarchar(N)`, `nvarchar(MAX)`, `float`, `datetime`, `bit`, `int IDENTITY`, `nchar`, `char`, `text`, `ntext`, `varbinary`, `binary`, `decimal`, `numeric`, `smallint`, `tinyint`, `bigint`, `money`, `smallmoney`, `real`, `date`, `time`, `smalldatetime`

### 5.3 Not Observed (teorik MSSQL katalogu)

`uniqueidentifier`, `datetime2`, `datetimeoffset`, `hierarchyid`, `xml`, `sql_variant`, `geography`, `geometry`, `rowversion/timestamp`, `image` (deprecated)

### 5.4 Encounter Policy

**Primary rule (SEAL gate)**: Annex 2A + 2B scope'undaki TÜM kolonların TÜM tipleri observed-inventory'ye düşer VE encounter-policy (map veya reject) mühürlü. **Zero unclassified type before SEAL.**

**Runtime reject** (son güvenlik freni, drift catch): ETL runtime beklenmeyen tip (observed dışı) ile karşılaşırsa:
- `uniqueidentifier` → yeni tabloda görülürse kontrat güncelleme PR tetikleyici (non-blocking)
- `xml`/`sql_variant`/`geography` → ETL reject queue + alert + kontrat revizyon (blocking)

---

## 6. Type Mapping Matrix (observed-focused)

| MSSQL | PG | Not |
|---|---|---|
| `bit` | `BOOLEAN` | `0`→`false`, `1`→`true`, `NULL`→`NULL` |
| `tinyint` / `smallint` | `SMALLINT` | PG'de `TINYINT` yok; 2 byte minimum |
| `int` | `INTEGER` | — |
| `int IDENTITY(1,1)` | `INTEGER GENERATED BY DEFAULT AS IDENTITY` | Sequence `setval()` cutover sonunda |
| `bigint` | `BIGINT` | — |
| `float` / `real` | `DOUBLE PRECISION` / `REAL` | **Analitik/ölçü için; para ASLA `float` (reconciliation §11)** |
| `decimal(N,M)` / `numeric(N,M)` | `NUMERIC(N,M)` | precision + scale aynen |
| `money` | `NUMERIC(19,4)` | **Asla `float` kullanma** |
| `smallmoney` | `NUMERIC(10,4)` | — |
| `char(N)` / `nchar(N)` | `CHAR(N)` UTF-8 | trailing space aynı semantik |
| `varchar(N)` / `nvarchar(N)` | `VARCHAR(N)` UTF-8 | collation §7 |
| `varchar(MAX)` / `nvarchar(MAX)` | `TEXT` | — |
| `text` / `ntext` (deprecated) | `TEXT` | ETL aynı hedefe yazar |
| `sysname` | `VARCHAR(128)` | MSSQL `sysname` = `nvarchar(128) NOT NULL` |
| `date` | `DATE` | — |
| `time` | `TIME` | — |
| `datetime` | `TIMESTAMPTZ` | **Timezone varsayımı ERP DBA yazılı onay (hidden risk #1)** |
| `smalldatetime` | `TIMESTAMP(0)` veya `TIMESTAMPTZ` | saniye çözünürlük yok |
| `binary` / `varbinary(N)` | `BYTEA` | — |
| `varbinary(MAX)` / `image` (deprecated) | `BYTEA` (&lt;1 GB) | `image` deprecated |

### 6.1 Identity

- MSSQL `IDENTITY(1,1)` → PG `GENERATED BY DEFAULT AS IDENTITY` (SQL standard)
- ETL explicit değer yazar (identity-insert on)
- Cutover sonu: `SELECT setval(pg_get_serial_sequence('reports_db.reports', 'id'), COALESCE((SELECT MAX(id) FROM reports_db.reports), 1));`

### 6.2 rowversion Per-Use-Case

- App optimistic locking kullanıyorsa → PG `xmin` MVCC **veya** explicit `version BIGINT DEFAULT 0`
- Kullanmıyorsa → DROP OK
- Kontrat **global drop kuralı yok** (iter-1 RED düzeltmesi)

---

## 7. Collation (lower()+functional index, no CITEXT)

Repo pattern'ine göre:

| Use case | Pattern | Gerekçe |
|---|---|---|
| PK / technical code / enum string ("ACTIVE"/"INACTIVE") | `VARCHAR COLLATE "C"` | byte-compare; deterministic; hızlı |
| Email / login lookup (case-insensitive) | **`lower(email)` + functional index** `CREATE INDEX ON users ((lower(email)))` | Repo zaten `AuthenticatedUserLookupService.java:57 lower(…Locale.ROOT)` pattern'i kullanıyor; `CITEXT` eklemek drift |
| TR full-text search | `VARCHAR COLLATE "tr-TR-x-icu"` | ICU collation; sadece full-text search kolonları; glibc Türkçe olmayabilir |

**`CITEXT` kaldırıldı** — repo pattern değil.

---

## 8. Soft-Delete (partial index + view)

### 8.1 MSSQL Bayrakları

| Kolon | Tip | Anlam |
|---|---|---|
| `DELETED_FLAG` | `bit` / `char(1)` | `1`/`'Y'` silinmiş |
| `IS_ACTIVE` | `bit` | `0` askıda |
| `REVOKED_AT` | `datetime` | `NULL` değilse iptal |
| `DELETED_AT` | `datetime` | — |

### 8.2 PG Pattern

Kolonu aynı isimle taşı. Query filter iki pattern:

**Partial index**:
```sql
CREATE INDEX idx_reports_active ON reports_db.reports (id)
  WHERE deleted_flag = false;
```

**Read-only view** (tercih — repository WHERE duplicate etmesin):
```sql
CREATE VIEW reports_db.v_reports_active AS
SELECT * FROM reports_db.reports
WHERE deleted_flag = false AND (revoked_at IS NULL);
```

Spring entity `@Table(name = "v_reports_active")` veya native query.

### 8.3 FK + Soft-Delete Risk

PG FK soft-delete bayrağını **görmez**. `ON DELETE CASCADE` hard delete için; soft delete'te child orphan referans.

Kural:
- Parent soft-delete → child keep referans; query view'dan JOIN
- Parent hard-delete → `ON DELETE RESTRICT` (default) veya `SET NULL` opsiyonel FK'ler
- **RLS soft-delete için yanlış araç** (performance + security semantics karıştırır)

### 8.4 Reconciliation (16.3.5)

- Row count parity: active + soft-deleted **toplam**
- Sample semantic diff: soft-delete'li satırlar dahil (aksi halde false positive)

---

## 9. Idempotency Keys

### 9.1 Seçim Kuralı

| Durum | Tavsiye | Gerekçe |
|---|---|---|
| MSSQL PK `uniqueidentifier` | Natural UUID kullan | Zaten global unique |
| MSSQL PK stable `int IDENTITY` | **Natural PK koru** (PG `INTEGER/BIGINT`) | Sequence setval cutover sonu; surrogate gereksiz karmaşık |
| MSSQL PK int IDENTITY + re-seed riski / multi-source merge | Hybrid: `UUID DEFAULT gen_random_uuid()` + `source_mssql_id BIGINT NOT NULL UNIQUE` | Gelecek sorgu karışmasın |
| Composite natural key | Hybrid: natural unique + surrogate `id UUID PK` | ORM + FK pratik |

### 9.2 Re-Run Safety (UPSERT)

```sql
INSERT INTO reports_db.reports (id, source_mssql_id, title, ..., content_hash)
SELECT id, source_mssql_id, title, ..., md5(row_to_json(...)::text)
FROM staging.reports
ON CONFLICT (source_mssql_id) DO UPDATE SET
    title = EXCLUDED.title,
    updated_at = now()
WHERE reports_db.reports.content_hash <> EXCLUDED.content_hash;
```

`content_hash` — tracked column set md5. Her re-run sadece değişen satırı günceller. 16.6 audit raporlar.

---

## 10. FK Load Order + Circular Resolution

### 10.1 Topological Sort

Kahn's algorithm:
```
in_degree[t] = 0 for t in T
for (child, parent) in E: in_degree[child] += 1
queue = [t for t in T if in_degree[t] == 0]
L = []
while queue:
    t = queue.pop()
    L.append(t)
    for child in children_of(t):
        in_degree[child] -= 1
        if in_degree[child] == 0:
            queue.append(child)
if len(L) < len(T): raise CycleError
```

### 10.2 Circular Dependency

Strateji:

**Basit**: `DEFERRABLE INITIALLY DEFERRED` + two-pass insert (NULL FK pass-1, UPDATE pass-2, `SET CONSTRAINTS ALL IMMEDIATE` commit)

**Daha güvenli (Codex iter-3 önerisi)**: `staging/raw` schema → bulk COPY → `final` schema `INSERT SELECT` → FK `ADD CONSTRAINT ... NOT VALID` → pipeline sonu `ALTER TABLE ... VALIDATE CONSTRAINT` (MVCC-friendly, daha düşük lock)

Deliverable: `docs/migration/fk-graph.dot` (Graphviz, 16.1 inventory çıktısı)

---

## 11. Unicode + Encoding (driver-based streaming read)

### 11.1 Primary Extract Lane

**`driver-based streaming read primary`** (implementation-agnostic):

| Implementation | Driver | Target |
|---|---|---|
| Java (Spring Batch Job-mode OK) | `mssql-jdbc` | PG COPY via JDBC |
| Python (PLAN §16.3 stand-alone) | `pyodbc` / `pymssql` | `psql COPY FROM` pipe |
| Go (alternatif) | `github.com/denisenkom/go-mssqldb` | `pgx COPY` |

Her lane: cursor-based streaming read → PG COPY target. **Doğruluk > hız** (iter-2 Codex kararı).

**BCP** opt-in lane — sadece çok büyük + append-mostly tablolar için. `bcp -w -C 65001` combo **hatalı** (iter-1 Codex düzeltmesi); kullanılırsa `-N` native format + explicit validator.

### 11.2 Encoding

- MSSQL `nvarchar` = UTF-16 LE → PG UTF-8 (`SERVER_ENCODING=UTF8`, `LC_CTYPE=C.UTF-8`)
- JDBC/pyodbc driver otomatik UTF-8 stream; BCP wide mode manuel
- Edge cases:
  - Surrogate pair (emoji, nadir CJK) → UTF-8 4-byte native
  - BOM (`\uFEFF`) → ETL girişinde **strip** (ilk byte check)
  - NULL byte (`\0`) → PG `TEXT` kabul etmez → reject queue
  - `Turkish_CI_AS` code-point level; **encoding değil** comparison rule

---

## 12. NULL vs Empty String Policy

MSSQL'de `''` "unset" yaygın; PG `''` ve `NULL` farklı.

| Kolon tipi/use | Varsayılan | Gerekçe |
|---|---|---|
| Free-text (description, note, comment) | Keep `''` | App `''` bekliyor; NULL normalize → regression |
| Optional FK string (`parent_code`) | Normalize `''` → `NULL` | FK semantik bozuk |
| Enum/status (`'A'`/`'I'`/`'D'`) | Keep değer; `''` REJECT | Invalid state → reject queue |
| Email, phone | Normalize `''` → `NULL` | `UNIQUE` constraint + veri temizlik |
| `datetime` `''` (MSSQL sentinel `1900-01-01`) | **REJECT** | Bozuk veri — audit |

Per-column inventory işareti: `normalize_empty_to_null: true/false`.

---

## 13. Write-Freeze Window

### 13.1 Parametreler

| Alan | Değer |
|---|---|
| Owner | Workcube admin |
| Süre hedefi | 10-15 dk (sadece "pre-seed + final delta" modelinde) |
| Lock tercih | ERP app-level maintenance mode |
| Lock fallback | MSSQL `ALTER DATABASE workcube_mikrolink SET READ_ONLY` |
| Rollback | 15 dk aşılırsa freeze kaldır, cutover ertele |

### 13.2 "Pre-seed + Final Delta" Kontratı (Codex iter-2 kalibrasyonu)

Freeze 10-15 dk **ancak şu senaryoda gerçekçi**:

- **T-1 / T-7 günler (freeze dışı)**: 16.3 ETL worker bulk initial load (tüm 2A + 2B scope)
- **Freeze içinde** (T0):
  1. Source freeze (ERP maintenance)
  2. Final delta import (16.3 worker son re-run sadece değişenleri)
  3. 16.3.5 reconciliation PASS
  4. Feature flag flip `*_MSSQL_ENABLED=false`
  5. Read-path kanıt

**Aksi halde** (bulk initial freeze içinde): 30+ dk iyimser. Kontrat **pre-seed pattern** mühürler; yoksa freeze genişletilir + cutover ertelenir.

---

## 14. Backup Before Freeze

### 14.1 MSSQL Backup

```sql
BACKUP DATABASE workcube_mikrolink
TO DISK = 'E:\Backup\workcube_mikrolink_PRE_FAZ16_CUTOVER_YYYYMMDD.bak'
WITH FORMAT, COMPRESSION, CHECKSUM, STATS = 10;

BACKUP LOG workcube_mikrolink
TO DISK = 'E:\Backup\workcube_mikrolink_PRE_FAZ16_LOG_YYYYMMDD.trn';
```

### 14.2 Retention

- **Minimum 30 gün** (operasyonel minimum; PLAN.md §16.8 Aşama 5 gözlem penceresi)
- **Legal/compliance policy üstün** — owner override hakkı

### 14.3 Restore Prova (16.5.5 gate)

- Test sunucu `RESTORE DATABASE` provası ≤ freeze'den 48 saat önce
- Prova başarısız → cutover bekleme

---

## 15. Reconciliation Rules (Float Tolerance)

Per-column `semantic_class` inventory'de mühürlenir:

| Semantic class | Parity method | Örnek kolon |
|---|---|---|
| `analytical_float` | Relative tolerance `ε_rel=1e-6`; `to_char(val, 'FM0.000000000000000')` normalized 15-digit text hash | `CONVERSION_RATE`, `MARGIN_PCT` |
| `currency_like_float` | **NUMERIC(19,4) cast PRE-reconciliation**; sonra exact hash | ERP `AMOUNT_TRY`/`AMOUNT_USD` float depoluyorsa (kötü pattern ama gerçek) |
| `counter_integer_as_float` | Integer cast + exact hash | Sayaç kolonu float saklıyorsa |

**Default**: `unknown_float_class => SEAL BLOCKER` (analytical değil; Codex iter-4 sıkılaştırma). Workcube admin + backend lead her `float` kolon için **çifte onay** verir.

Inventory yaml örnek:
```yaml
- column: AMOUNT_TRY
  mssql_type: float
  pg_type: NUMERIC(19,4)  # cast during ETL
  semantic_class: currency_like_float
  reconciliation: exact_hash_after_cast
  epsilon_abs: 0.0001  # fallback if cast fails
```

---

## 16. Acceptance Criteria

Bu dokümanın `SEALED` statüsüne geçmesi için (16.1 inventory sonunda):

- [ ] **Runtime source-surface coverage manifest** — annex 2A seal (zero `pending_annex`, 8 sourceQuery rapor manuel validated)
- [ ] **Schema-introspection surface** — annex 2B seal
- [ ] **Schema-service parity decision** (live PG catalog vs ETL-ed metadata snapshot) — `docs/migration/schema-service-parity-adr.md` mühürlü
- [ ] **Observed-type inventory closure** — zero unclassified type; encounter policy mühürlü
- [ ] **Timezone sign-off** — ERP DBA yazılı per-`datetime`-column veya global UTC varsayımı
- [ ] **Float semantic_class mühürlü** (per-column analytical/currency/counter) — zero `unknown_float_class`
- [ ] **Extract-lane rehearsal PASS** — driver-based streaming primary pilot on small table (JDBC/pyodbc/go-mssqldb)
- [ ] **Sequence/setval plan** per-IDENTITY-table
- [ ] **Extension prereq** decision (`ltree` / `xml` PG extension — kullanılacak mı?)
- [ ] **Backup evidence** (checksum + path + date)
- [ ] **Restore prova** Faz 16.5.5 gate
- [ ] Backend engineer + ops engineer + Workcube admin sign-off
- [ ] FK dependency graph `docs/migration/fk-graph.dot` + PNG

> **`Codex AGREE` acceptance criterion değildir** (review process ≠ acceptance; iter-2 Codex düzeltmesi).

---

## 17. Open Questions

1. **Snapshot vs incremental**: Incremental CDC PLAN.md §16.4 SKIP; tek-seferlik freeze-snapshot yeterli. Teyit: freeze penceresinde 10-15 dk final delta tamamlanabilir mi? 16.1 inventory + row count × throughput.
2. **CHECK CONSTRAINTS**: MSSQL `CHECK (STATUS IN ('A','I','D'))` var mı? Taşırsak PG; app-level enforce → `NOT VALID` + data validation. Tercih: PG port.
3. **Triggers**: `SELECT * FROM sys.triggers` — boş mu? Trigger iş-mantığı = migration blocker.
4. **Computed columns**: MSSQL `AS (...) PERSISTED` → PG `GENERATED ALWAYS AS (...) STORED`. Syntax farkı.
5. **Views**: Migrate mi, PG'de yeniden yaz mı? Tercih: Flyway V16'da yeniden yaz (tip uyumu zor).
6. **`hierarchyid` / `xml`**: ERP gerçekte kullanıyor mu? Kullanmıyorsa skip; kullanıyorsa extension prereq (`ltree`, PG `xml`).
7. **`rowversion` optimistic locking**: App kullanıyor mu? Kullanıyorsa PG `xmin` veya explicit `version BIGINT`.
8. **Permission Zanzibar overlap**: cache-reference MSSQL `PERMISSIONS` vs PG permission_db vs OpenFGA — hangi katmanda authority?

---

## 18. Hidden Risks

1. **Datetime timezone varsayım drift** — kritik: yanlışsa tüm tarihsel raporlar saatlerce kayar. Mitigasyon: ERP DBA yazılı onay per-column (16.1 acceptance kapısı).
2. **Soft-delete FK orphan** — child referansları orphan; rapor sayımları patlar. Mitigasyon: view-based query (§8.2); reconciliation active+soft-deleted toplam.
3. **`uniqueidentifier` byte-order** (BCP vs JDBC/pyodbc) — aynı UUID iki farklı string encode, idempotency conflict. Mitigasyon: tek tool (driver-based primary); BCP kullanılırsa `-N` native + validator.
4. **Empty string → MSSQL `datetime` sentinel `1900-01-01`** — bozuk veri PG'ye taşınır. Mitigasyon: §12 reject policy.
5. **Turkish `I`/`ı` CITEXT edge** — login case-insensitive match eksiklik. Mitigasyon: `lower(email) + Locale.ROOT + functional index` (repo pattern); CITEXT yok.
6. **Float reconciliation drift + semantic class misclassification** — currency float "analytical" işaretlenirse milyon-birim drift görünmez. Mitigasyon: `unknown_float_class` seal blocker + double-sign-off.
7. **Runtime source-surface coverage gap** — annex eksik → 16.5 classified PASS ama runtime unclassified hit → 404/null. Mitigasyon: annex zero-unclassified SEAL gate.
8. **Schema-service parity decision gecikmesi** — 16.1 yerine 16.5'te verilirse 16.2 Flyway + 16.3 worker design yanlış olur. Mitigasyon: 16.1 gate karar mühürlenir.

---

## 19. References

- `PLAN.md` §16.0 (parent), §16.1 inventory, §16.3 ETL, §16.3.5 reconciliation, §16.5 cutover, §16.8 decommission
- `docs/adr/0002-single-host-dual-cluster.md` D31 (PG primary)
- Codex threads:
  - `019dbe1d`, `019dbe1f`, `019dbe21`, `019dbe22` (Faz 16 parent AGREE)
  - `019dbe92` (bu doc iter-1 → iter-4 AGREE DRAFT/RFC seviyesi)
- PG docs: collation, `gen_random_uuid`, `COPY`, identity, functional index
- MSSQL docs: `BACKUP DATABASE`, `BCP`, `sys.triggers`, `sys.columns`, cursor-based read
- platform-ssot sources (annex crawler girişi):
  - `backend/report-service/src/main/resources/reports/*.json` (31 rapor)
  - `backend/report-service/src/main/java/com/example/report/query/SqlBuilder.java`
  - `backend/schema-service/src/main/java/com/example/schema/service/SchemaExtractService.java`
  - `backend/schema-service/src/main/java/com/example/schema/service/SchemaSnapshotService.java`
