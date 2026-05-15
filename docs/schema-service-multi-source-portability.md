# Schema-Service Çoklu-Kaynak Taşınabilirliği

> **Soru**: Schema-service şu an sadece Workcube `mikrolink` schema'sına mı özgü, yoksa başka bağlanan schema (farklı ERP, farklı müşteri, farklı DB engine) ile de çalışır mı?
>
> **Kısa cevap**: **Çoğunlukla Workcube'a özgü.** Aynı Workcube vendor'lı başka müşteride %95 çalışır; başka MSSQL ERP'de %50; PG/MySQL/Oracle'da %0.
>
> **Tarih**: 2026-05-15  
> **Kaynak**: `platform-backend/schema-service/` (commit kanıtlı)

---

## 1. 3 Katmanlı Bağımlılık Modeli

### 1.1 ✅ Generic (her MSSQL schema'da çalışır)

| Capability | Kaynak | Generic mi? |
|---|---|---|
| PK + identity + nullable + data_type | `SchemaExtractService.java:33-50` (`sys.columns + sys.indexes`) | ✅ DB-engine generic (MSSQL) |
| Row count | `sys.partitions` | ✅ Generic |
| View definitions | `sys.sql_modules WHERE type='V'` | ✅ Generic |
| Schema list (template) | `sys.schemas` | ⚠️ Generic ama LIKE filter hardcoded |
| Domain clustering | `DomainClusteringService` — Label Propagation algorithm | ✅ Tablo isimlerinden bağımsız |
| Name match heuristic | `*_ID → *` pattern | ✅ Generic |
| View parse heuristic | regex `(\w+)\.(\w+)=(\w+)\.(\w+)` | ✅ Generic |

### 1.2 ⚠️ MSSQL'e özgü (PG/MySQL/Oracle için çalışmaz)

| Bağımlılık | Kaynak | Alternatif (PG için) |
|---|---|---|
| `sys.*` system catalog sorguları | Tüm extractor service'ler | `pg_catalog.*` veya `information_schema.*` |
| JDBC sürücü | `jdbc:sqlserver://` | `jdbc:postgresql://` |
| NTLM authentication | `authenticationScheme=NTLM;domain=boreas` | PG: md5/scram-sha-256/cert |
| ReadOnly hint | `applicationIntent=ReadOnly` | PG: `default_transaction_read_only=on` |

### 1.3 ❌ Workcube'a özgü (başka MSSQL ERP'de çalışmaz veya yanlış sonuç)

| Hardcoded | Kaynak | Etki başka ERP'de |
|---|---|---|
| `LIKE 'workcube_mikrolink%'` filter | `SchemaExtractService.java:130` | Başka schema listede **gözükmez** |
| Yearly schema pattern `workcube_mikrolink_<year>_<id>` | `YearlySchemaDiscoveryService.java:35` | Tetiklenmez, pattern eşleşmez |
| Yearly coverage pattern | `YearlySchemaCoverageExporter.SCHEMA_PATTERN` | Aynı |
| 40+ alias map (`COMP_ID, EMP_ID, MANAGER_ID, FIRST_BOSS_ID, ACC_COMPANY_ID, ...`) | `RelationshipDiscoveryService.java:22-46` | Boş — FK discovery sadece name_match (confidence 0.80) |
| 25 common FK map (`COMPANY_ID→COMPANY, PROJECT_ID→PRO_PROJECTS`) | `RelationshipDiscoveryService.java:49-63` | Boş — başka ERP'de bu tablolar yok |
| Master data graph (1774 FK) | `MasterDataReadService.java:78` | **Broken** — referans verisi yok |
| Master data table list (departments, branches) | `MasterDataReadService` | Aynı |
| AI Chat Workcube examples | `AiChatService` | Generic cevap kalitesi düşer |

---

## 2. Kapsama matrisi

| Veri kaynağı | Çalışma yüzdesi | Neler çalışır | Neler çalışmaz |
|---|---|---|---|
| **Aynı Workcube** (farklı müşteri/tenant — örn. başka şirket Workcube'u) | **~95%** | Tüm capability'ler | LIKE pattern + yearly pattern aynı kalır; sadece bağlantı string değişir |
| **Başka MSSQL ERP** (ETA, Logo, Mikro değil, vb.) | **~50%** | Generic kısım (PK + columns + views + name_match FK) | Alias/common_fk boş → FK confidence ~0.80; master data **broken**; yearly pattern boş |
| **Genel MSSQL DB** (DWH, custom ERP) | **~40%** | Generic | Aynı + business semantic yok |
| **PostgreSQL ERP** | **0%** | — | `sys.*` SQL syntax + JDBC driver |
| **MySQL ERP** | **0%** | — | Aynı |
| **Oracle ERP** | **0%** | — | Aynı |
| **Snowflake / BigQuery DWH** | **0%** | — | Connectivity + SQL dialect tamamen farklı |

---

## 3. Hangi Capability Hangi Bağımlılığa Sahip?

| Capability | DB Engine | Schema Filter | Naming Convention | Real FK | Master Data |
|---|---|---|---|---|---|
| Column metadata (PK, type, nullable) | MSSQL only | LIKE filter etkili | — | — | — |
| Row count | MSSQL only | LIKE filter etkili | — | — | — |
| View definitions | MSSQL only | LIKE filter etkili | — | — | — |
| Domain clustering | MSSQL only | LIKE filter etkili | ✅ Bağımsız | — | — |
| FK heuristic — name match | MSSQL only | LIKE filter etkili | ✅ Generic | — | — |
| FK heuristic — alias map | MSSQL only | LIKE filter etkili | ❌ Workcube-spesifik | — | — |
| FK heuristic — common FK | MSSQL only | LIKE filter etkili | ❌ Workcube-spesifik | — | — |
| FK heuristic — view parse | MSSQL only | LIKE filter etkili | ✅ Generic | — | — |
| Yearly schema discovery | MSSQL only | ❌ Workcube pattern | ❌ Workcube-spesifik | — | — |
| Master data read | MSSQL only | Schema-aware | ❌ Workcube table names | — | ❌ Workcube graph |
| Master data diagnostic | MSSQL only | Schema-aware | ❌ Workcube-spesifik | — | ❌ Workcube graph |
| AI Chat (local logic) | MSSQL only | Schema-aware | ❌ Workcube examples | — | — |

---

## 4. Generic Yapma Roadmap

### 4.1 Yüzey değişiklikler (Quick wins) — 1-2 gün

| # | Değişiklik | Effort | Etki | Durum |
|---|---|---|---|---|
| 1 | Schema discovery LIKE → config (`schema.discovery.patterns`) | 30 dk | Çoklu pattern desteği | ✅ PR #216 |
| 2 | Yearly pattern → config (`schema.yearly.like-pattern` + `regex`) | 30 dk | Başka pattern (örn. ETA `eta_<year>_<branch>`) | ✅ PR #219 |
| 3 | Alias map → JSON import (`schema.fk-heuristics.alias-path`) | 2-3 saat | Per-ERP alias dictionary | ✅ PR #221 |
| 4 | Common FK map → JSON import (`schema.fk-heuristics.common-fk-path`) | 1 saat | Per-ERP common FK | ✅ PR #221 |
| 5 | Master data **kind enablement** → config (`schema.master-data.enabled-kinds`) — subset gating | 1 saat | Per-ERP master data kind subset | ✅ PR #223 |
| 6 | Default schema name → config (zaten parametrik) | — | OK | ✅ Mevcut |

**Çıktı**: Aynı Workcube vendor'lı başka müşteri **out-of-the-box** çalışır; başka MSSQL ERP'lerde **per-ERP profile** ile çalışır.

> **Phase 1 quick wins durumu (2026-05-16)**: 1-5/5 maddelerin tümü merge edildi (PR #216/#219/#221/#223; #6 zaten parametrikti). Kalan portability Phase 2 (adapter pattern) ve Phase 3 (ERP profile pack) ile gelir.
>
> **#5 kapsam düzeltmesi**: Bu madde başlangıçta "master data table list → config" diye planlanmıştı. Ancak `MasterDataReadService.KIND_MAP` salt tablo listesi değil, kind başına tam SQL-template allowlist'idir (SQL injection guard'ın temeli). SQL template'lerini config'e taşımak quick-win değildir — DTO projection contract + identifier validation + integration smoke gerektirir. Bu nedenle #5 **kind enablement** (subset gating; `KIND_MAP` kapalı allowlist aynen korunur) olarak daraltıldı; ERP table-mapping portability'si **Phase 3 ERP profile pack**'e (§4.3) ertelendi. Codex `019e2d7d` §5-6.

### 4.2 Adapter pattern — DB engine abstraction (2-3 hafta)

| # | Değişiklik | Effort |
|---|---|---|
| 7 | `SchemaExtractor` interface (abstract method) | 2-3 saat |
| 8 | `MssqlSchemaExtractor` (mevcut kod refactor) | 1 gün |
| 9 | `PostgresSchemaExtractor` (information_schema / pg_catalog) | 2-3 gün |
| 10 | `MySQLSchemaExtractor` | 2 gün |
| 11 | `OracleSchemaExtractor` | 2-3 gün |
| 12 | Authentication adapter (NTLM/PG-md5/MySQL-native/Oracle-wallet) | 2-3 gün |
| 13 | Multi-tenancy: `DataSource` per source registered runtime | 1 gün |

**Çıktı**: PG, MySQL, Oracle ERP'lerde de çalışır.

### 4.3 ERP profile packs (Enterprise feature) — 1-2 ay

| # | Pack | Capability |
|---|---|---|
| 14 | Workcube profile | Mevcut (40+ alias, 25 common FK, master data graph) |
| 15 | ETA profile | Alias + common FK + master data (manual onboarding) |
| 16 | Logo profile | Aynı |
| 17 | Mikro profile | Aynı |
| 18 | SAP profile | Çok büyük, AI-assisted bootstrap |
| 19 | Auto-detect | Schema pattern'lerden ERP tipi tespit |
| 20 | Migration impact per ERP | Source-target mapping (Workcube→PG vs SAP→PG farklı) |
| 21 | AI Chat ERP-aware prompts | "Bu Workcube ERP'sinde 'FATURA' tablosu..." |
| 22 | Multi-ERP unified domain map | Cross-ERP semantic glossary |

---

## 5. Mevcut config'le ne yapılabilir? (acil kullanım)

### 5.1 Aynı Workcube vendor'lı başka müşteri için

`application.yml`:
```yaml
schema:
  default-schema: workcube_mikrolink  # aynı
  master-data:
    schema: workcube_mikrolink         # aynı

# Connection bilgisi env var:
SCHEMA_MSSQL_HOST: <yeni-müşteri-mssql>
SCHEMA_MSSQL_PORT: 1433
SCHEMA_MSSQL_DB: workcube_mikrolink     # aynı
```

**Sonuç**: %95 çalışır. Sadece sourceQuery'lerde özelleştirme varsa per-report ayar gerek.

### 5.2 Başka MSSQL ERP için (kod değişikliği olmadan)

`application.yml`:
```yaml
schema:
  default-schema: eta_main              # ERP-spesifik
  master-data:
    schema: eta_main
```

**Sonuç**: %50 çalışır. Generic kısım OK ama:
- LIKE filter `workcube_mikrolink%` yüzünden başka schema'lar listede gözükmez → bu satır kod değişikliği gerektirir
- Alias/common FK map Workcube-spesifik → FK confidence düşük
- Master data **broken**

**Mitigation**: LIKE filter'ı hızlı patch'le config'e taşı (1 saat); kalan alias/common_fk Phase 1 (1-2 gün).

### 5.3 PG/MySQL/Oracle için

**Şu an**: Çalışmaz. Adapter pattern (Phase 2, 2-3 hafta) gerekli.

---

## 6. Karar Matrisi

| Senaryo | Mevcut yeterli? | Çözüm |
|---|---|---|
| Aynı Workcube + farklı müşteri | ✅ Out-of-the-box | Connection string değiştir |
| Başka MSSQL ERP (kısa vadeli) | ⚠️ Kısmen | Phase 1 — config değişikliği + per-ERP profile |
| Başka MSSQL ERP (uzun vadeli) | ❌ Eksik | Phase 1 + Phase 3 (ERP profile pack) |
| PG / MySQL / Oracle | ❌ Çalışmaz | Phase 2 — DB engine adapter |
| Multi-tenant SaaS (her müşteri kendi DB'si) | ❌ Eksik | Phase 2 — DataSource per source |

---

## 7. Pratik öneriler

### 7.1 Şimdilik
- Workcube odaklı kalsın (mevcut ROI yüksek)
- Multi-tenant Workcube için **Phase 1 quick wins** (1-2 gün effort)
- Documentation: README'de "Workcube-first, generic kısım MSSQL portable" disclaimer

### 7.2 Yakın gelecek (3-6 ay)
- Adım 13 SEAL + Faz 17 migration tamamlandıktan sonra
- Phase 1 quick wins implement
- Yeni müşteri sinyali varsa Phase 3 ERP profile pack başlat

### 7.3 Uzun vade (6-12 ay)
- Phase 2 DB engine adapter (PG ön plan — yeni müşteri PG ERP kullanıyorsa)
- Multi-tenant SaaS olarak schema-service paketle
- Public API + auth/billing
- AI Chat per-ERP optimize

---

## 8. Hard-Coded Locations Audit

```bash
# Tüm Workcube referansları (kod tarafında)
grep -rn "workcube" platform-backend/schema-service/src/main/java/ | wc -l
# → 23 satır, 9 dosyada

# Dağılım:
# - SchemaExtractService.java (3 satır): default + LIKE filter
# - YearlySchemaDiscoveryService.java (3 satır): regex pattern
# - YearlySchemaCoverageExporter.java (1 satır): SCHEMA_PATTERN const
# - 6 controller @Value annotations
# - 2 DTO comment'ları
# - RelationshipDiscoveryService.java (40+ alias + 25 common FK)
# - MasterDataReadService.java (Workcube graph dependency)
```

---

## 9. Cross-AI Notu

Schema-service şu an "Workcube reference implementation" pozisyonunda. Generic platform haline gelmesi için Phase 1-3 roadmap'i var (3-6 ay incremental). Pre-prod sürecinde **Workcube-first** kalır; multi-tenant gelecek karar.

Bu doc Codex thread `019e2cca` capability gap matrix'le tutarlı — generic'leştirme **yeni capability** değil, **mevcut capability'lerin portability** boyutu.

---

## 10. Referans

| Doküman | Konu |
|---|---|
| `docs/schema-service-and-schemalens-guide.md` | Genel rehber |
| `docs/schema-service-capability-map.md` | Capability + decision tree |
| `docs/schema-service-detected-vs-inferred-truth.md` | Detected vs inferred vs missing |
| `docs/schema-truth-contract-capability-gap-matrix.md` | Truth contract + 30 madde gap |
| `docs/schema-service-scope-expansion-impact.md` | Kapsam genişlemesi etki |
| Bu doc | Çoklu-kaynak taşınabilirliği |
| Kaynak kod referansları | Yukarıda satır numarası ile |
