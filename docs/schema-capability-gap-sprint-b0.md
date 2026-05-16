# Schema Capability Gap — Sprint B0 (Planning Artifact)

> **Tür**: Non-code planning artifact. Kod, interface refactor veya model
> değişikliği **içermez**.
> **Cross-AI**: Codex thread `019e2d7d` verdict **C + B-plan-only** —
> "imza beklerken agent yalnızca Capability Gap sprint için B0 plan/ADR/
> backlog hazırlasın; A veya B'de kod/mimari implementasyona açık 'başla'
> kararı olmadan girme."
> **Tarih**: 2026-05-16
> **Baz**: `docs/schema-truth-contract-capability-gap-matrix.md` (PR #693,
> Codex `019e2cca` — 30 madde) + `docs/schema-service-scope-expansion-impact.md`
> (PR #698).

---

## 1. Amaç ve sınır

Phase 1 portability quick wins (1-5/5 — PR #216/#219/#221/#223) tamamlandı.
Sıradaki agent-actionable critical path **operator zinciri** (Annex 2A
SEAL imzaları + PROD cutover) ama bu operator domain'inde bloklu. Codex
`019e2d7d`: imza beklerken agent **kod yazmaz**, yalnızca capability gap
sprint'i için **karar-destekleyici, reversible** artifact hazırlar.

Bu doküman:
- 30 capability gap'i **severity / ROI / risk** ekseninde kırar (§2);
- gap'leri **B1/B2/B3 PR-batch** sırasına dizer (§3);
- truth-tier model için **ADR taslağı** verir (§4);
- B1 authoritative capability'leri için **acceptance criteria** yazar (§5);
- Phase 2 (DB adapter) için **defer notu** bırakır (§6).

**Bu doc neyi YETKİLENDİRMEZ**: hiçbir kod PR'ı, model değişikliği veya
`SchemaExtractService` refactor'u bu doc'a dayanarak başlatılamaz. Sprint 1
implementasyonu ayrı bir **owner "başla" kararı + truth-tier ADR kabulü**
gerektirir.

---

## 2. 30 Gap — Severity / ROI / Risk slicing

ROI skoru: gap-matrix §6 cross-reference tablosundan — capability'nin kaç
senaryoda (Migration / SEAL / AI Chat / Drift) P0 olduğu. **ROI = P0 sayısı**
(0-4). Impl risk: implementasyon karmaşıklığı + blast radius. Missing risk:
capability eksik kalırsa doğan hasar.

### 2.1 İlişki belirleme gap'leri (gap-matrix §1.2 — 12 madde)

| # | Gap | Tier | Severity | ROI | Impl risk | Missing risk | Slice |
|---|---|---|---|---|---|---|---|
| R1 | Real FK extraction (`sys.foreign_keys`) | authoritative | P0 | 3 | Düşük | "FK yok" da truth — inference yanıltıcı | B1 |
| R2 | Unique constraint discovery (`is_unique=1`) | authoritative | P0 | 3 | Düşük | ERP ilişkisi unique key'e kurulu, PK değil | B1 |
| R3 | Composite relationship inference | inferred | P1 | 0 | Orta | Çok-kolonlu scope ilişkisi kaçar | B2 |
| R4 | Type/length/collation compat scoring | inferred | P1 | 0 | Düşük | False positive FK | B2 |
| R5 | Data-overlap sampling (orphan ratio) | sampled | P0 | 1 | Yüksek (PII) | En güçlü inferred kanıt eksik | B2 |
| R6 | Cardinality/distribution match | sampled | P2 | 0 | Orta | Doğrulama katmanı zayıf | B3 |
| R7 | T-SQL parser (regex yerine) | inferred | P1 | 1 | Yüksek | Alias/CTE/subquery join kaçar | B2 |
| R8 | SP/func/trigger parse | inferred+workload | P0 | 2 | Yüksek | ERP business logic görünmez | B2 |
| R9 | Query workload mining (DMV/Query Store) | workload | P0 | 2 | Orta | "Şema var" ≠ "kullanılıyor" | B2 |
| R10 | Domain dictionary versioning | manual | P1 | 0 | Düşük | Alias map kaynak/sahip izsiz | B3 |
| R11 | Relationship category ayrımı | manual+inferred | P1 | 1 | Orta | "Her *_ID aynı değil" karışır | B3 |
| R12 | Negative evidence (false-positive bastırma) | sampled+inferred | P1 | 0 | Orta | Düşük-kalite ilişki şişer | B3 |

### 2.2 Metadata gap'leri (gap-matrix §2.2 — 18 madde)

| # | Gap | Tier | Severity | ROI | Impl risk | Missing risk | Slice |
|---|---|---|---|---|---|---|---|
| M1 | Object inventory (extended properties, owner) | authoritative | P0 | 1 | Düşük | `dbo.X` vs `workcube.X` ayrımı yok | B1 |
| M2 | Column metadata genişletme (precision/scale/collation/computed) | authoritative | P0 | 4 | Düşük | DECIMAL precision yok → currency drift | B1 |
| M3 | Constraint inventory (check + default + trust state) | authoritative | P0 | 3 | Düşük | PG migration validation kuralı kayıp | B1 |
| M4 | Non-PK index inventory | authoritative | P0 | 1 | Düşük | sourceQuery + PG index tasarımı kör | B1 |
| M5 | Index health + usage | sampled+workload | P1 | 0 | Orta | "Index var" ≠ "kullanılıyor" | B3 |
| M6 | Storage size + LOB | authoritative | P0 | 2 | Düşük | Cutover hacim planı zorlanır | B1 |
| M7 | Partitioning + filegroup + compression | authoritative | P1 | 0 | Orta | Hot/cold ayrımı kaçar | B3 |
| M8 | Programmability inventory (SP+func+trigger gövde) | authoritative | P0 | 4 | Orta | ERP davranışı SQL objelerinde gizli | B2 |
| M9 | Indexed/materialized view | authoritative | P1 | 0 | Düşük | PG'de performans drift | B3 |
| M10 | Synonym + linked server | authoritative | P1 | 0 | Düşük | Cross-DB referans kaçar | B3 |
| M11 | Statistics + histogram | sampled | P2 | 0 | Orta | Skew tespiti zayıf | B3 |
| M12 | Query workload metadata | workload | P0 | 2 | Orta | "Şema var" ≠ "kullanılıyor" | B2 |
| M13 | CDC / Change Tracking / temporal | authoritative | P0 | 2 | Orta | Delta sync + rollback strateji kayıp | B1 |
| M14 | Security + permissions (RLS, GRANT) | authoritative | P1 | 0 | Orta | Migration sonrası least-privilege drift | B3 |
| M15 | Database-level options | authoritative | P1 | 0 | Düşük | Migration risk ölçümü eksik | B1 |
| M16 | Sequence / UDT / XML / full-text / CLR | authoritative | P2 | 0 | Orta | "Desteklemiyor" vs "yok" karışır | B3 |
| M17 | Sample data profiling (null/distinct/min-max) | sampled | P1 | 0 | Yüksek (PII) | AI Chat + migration validation zayıf | B2 |
| M18 | Business semantic metadata | manual | P1 | 0 | Orta | SchemaLens UI ham ERD'ye düşer | B3 |

### 2.3 Slicing özet

| Slice | Gap sayısı | Karakter | Tipik impl risk |
|---|---|---|---|
| **B1** | 9 (R1, R2, M1, M2, M3, M4, M6, M13, M15) | Saf authoritative `sys.*` extraction — read-only, deterministic | Düşük |
| **B2** | 7 (R5, R7, R8, R9, M8, M12, M17) | Parser + sampling + workload — PII/cost guardrail gerekir | Orta-Yüksek |
| **B3** | 14 (R3, R4, R6, R10, R11, R12, M5, M7, M9, M10, M11, M14, M16, M18) | UX + truth tier + manual-domain + ikincil derinleştirme | Orta |

> B1 saf authoritative `sys.*` extraction (9 madde). R10 (domain
> dictionary versioning) `manual_domain` tier olduğu — `sys.*` extraction
> kategorisine girmediği — için B3'e alındı (Codex `019e2d7d` REVISE).
> Toplam 9 + 7 + 14 = 30. ✓

---

## 3. B-slice PR-batch sırası

Codex `019e2d7d` §3: "B yerine A öncelikli planlanmalı" — B (capability gap)
ROI'si yüksek + plan/backlog olarak risksiz hazırlanabilir. Aşağıdaki sıra
**implementasyon önerisidir**, ayrı owner kararı gerektirir.

### B1 — Authoritative truth tabanı (gap-matrix Sprint 1 ≈)

`sys.*` doğrudan extraction. Read-only, deterministic, PII-sız, düşük blast
radius. Mevcut `SchemaExtractService` pattern'i (gap-matrix §2.1) genişler;
yeni model alanları **backward-compatible nullable** (gap-matrix §4).

Sıra: M2 (column metadata — ROI 4, currency drift kritik) → R1+R2
(real FK + unique — ROI 3, ilişki truth) → M3 (constraint inventory) →
M4 (non-PK index) → M1 (object inventory) → M6 (storage+LOB) →
M13 (CDC) → M15 (DB options).

### B2 — Parser + sampling + workload (gap-matrix Sprint 2 ≈)

Yüksek impl risk: T-SQL parser (R7), SP/trigger parse (R8, M8), sampling
(R5, M17 — **PII guardrail + opt-in + masking + read-only zorunlu**),
workload mining (R9, M12). Bu slice ADR-level karar gerektirir (sampling
güvenlik sınırı, cost guardrail — gap-matrix §3.5).

### B3 — UX + truth tier + manual-domain + ikincil (gap-matrix Sprint 3 ≈)

Truth tier UI badge, drift authoritative/inferred ayrımı, annotation/semantic
layer, domain dictionary versioning (R10 — `manual_domain` tier: alias map'e
owner + source + date + version), ikincil metadata (partitioning, statistics,
security, synonym). B1+B2 modeline bağımlı.

---

## 4. Truth-tier model — ADR taslağı (DRAFT)

> Bu bir **taslaktır** — resmi `docs/adr/` ADR'sine, B1 implementasyonu
> "başla" kararıyla birlikte dönüşür. Şu an karar verilmedi.

### ADR-DRAFT: Schema capability truth-tier model

**Status**: DRAFT (B0 planning — kabul edilmedi)

**Context**: Mevcut `Relationship` modeli (gap-matrix §4) confidence taşıyor
ama "FK truth" gibi sunuluyor. Oysa `RelationshipDiscoveryService` çıktısı
**heuristic evidence** (name match, alias, common-FK, view parse). Codex
`019e2cca` key finding: model "relationship evidence with confidence" olarak
yeniden adlandırılmalı; `authoritative_mssql` ile `inferred_metadata` aynı
renkte gösterilmemeli.

**Decision (önerilen)**: Her capability bilgisi 6 tier'dan birine sınıflanır
(gap-matrix §0): `authoritative_mssql`, `inferred_metadata`, `sampled_data`,
`workload_observed`, `manual_domain`, `unsupported`. Model değişikliği
(gap-matrix §4):
- `ColumnInfo` → precision/scale/collation/computed/default/unique alanları
  (nullable, backward-compatible);
- `Relationship` → `RelationshipEvidence` (tier + sources[] + category +
  orphanRatio + typeCompatibilityScore + isComposite).
- Yeni enum: `EvidenceTier`, `RelationshipCategory`.

**Consequences**:
- (+) SchemaLens UI authoritative ↔ inferred ayrımı yapabilir; drift ekranı
  authoritative drift'i inferred drift'ten ayırır.
- (+) AI Chat "bu kolon unique" / "FK var" iddialarını tier'a göre kalifiye
  eder (CLAUDE.md kural #9 drift guard ile uyumlu).
- (−) Model migration: tüm `Relationship` tüketicileri (`/snapshot` endpoint,
  SchemaLens FE, AI Chat context) yeni alanları okumalı.
- (−) Backward-compat için yeni alanlar `nullable`/`Optional` — geçiş döneminde
  iki şekil bir arada.

**Alternatifler**:
- (A) Mevcut `Relationship` korunur, tier yalnız ek bir alan — reddedildi:
  model adı ("Relationship") yanlış anlamı taşımaya devam eder.
- (B) Tier yalnız UI katmanında türetilir — reddedildi: confidence semantiği
  backend'de kaynaktan gelmeli, FE türetimi kırılgan.

**Açık sorular** (ADR kabulünden önce):
1. `RelationshipEvidence` rename'i `/snapshot` API kontratını kırar mı —
   versiyonlama gerekir mi?
2. `sampled_data` tier'ı PII guardrail'i nasıl zorunlu kılar (B2 bağımlılığı)?
3. Truth tier UI badge tasarımı SchemaLens'te kim sahiplenir (frontend owner)?

---

## 5. B1 Authoritative capability — Acceptance criteria

B1 slice'ın **en yüksek ROI** üç capability'si için kabul ölçütleri. Bunlar
B1 implementasyon PR'ları açıldığında "done" tanımıdır.

### 5.1 R1 — Real FK extraction

- **Kaynak**: `sys.foreign_keys` + `sys.foreign_key_columns` JOIN.
- **Extract edilecek**: from/to table+column, `is_disabled`, `is_not_trusted`,
  cascade action (delete/update), schema-qualified target, composite FK
  kolonları (ordinal sırası korunur).
- **Çıktı**: `RelationshipEvidence` tier=`AUTHORITATIVE_FK`, source=`fk_constraint`.
- **Kabul**:
  - FK olmayan şemada (Workcube tipik) sonuç **boş liste** döner — "FK yok" da
    authoritative truth, hata değil.
  - `is_not_trusted=1` FK'lar işaretlenir (confidence'a yansır).
  - Composite FK tek `RelationshipEvidence` olarak `isComposite=true` +
    `compositeColumns` ile döner.
  - Unit test: mock `sys.foreign_keys` → 0 satır, 1 tekil FK, 1 composite FK.

### 5.2 R2 — Unique constraint discovery

- **Kaynak**: `sys.indexes WHERE is_unique=1` + `sys.index_columns`.
- **Extract edilecek**: unique index/constraint kolonları, `is_primary_key`
  ayrımı (PK zaten var — yalnız non-PK unique yeni), filtered unique predicate.
- **Çıktı**: `ColumnInfo.unique=true` (tekil kolon) + ayrı composite unique
  listesi.
- **Kabul**:
  - PK unique index'leri **tekrar raporlanmaz** (PK zaten `ColumnInfo.pk`).
  - `CODE`/`NO`/`UUID` gibi business key kolonları unique olarak işaretlenir.
  - Composite unique → kolon grubu olarak döner.
  - Unit test: PK-only tablo, tekil unique, composite unique, filtered unique.

### 5.3 M4 — Non-PK index inventory

- **Kaynak**: `sys.indexes` (PK filtresi kaldırılır) + `sys.index_columns` +
  `sys.partitions`.
- **Extract edilecek**: key columns (sıra + ASC/DESC), included columns, filter
  predicate, uniqueness, fill factor, `is_disabled`, `is_hypothetical`.
- **Çıktı**: yeni `IndexInfo` record (model — ADR kapsamında).
- **Kabul**:
  - PK ve unique-constraint index'leri R2/PK ile **çift sayılmaz** (ayrı işaret).
  - `is_hypothetical=1` (DTA artığı) index'ler ayrı işaretlenir veya elenir.
  - Disabled index'ler `is_disabled` ile döner, sessizce atlanmaz.
  - Unit test: heap tablo (0 index), clustered+nonclustered, included columns'lı,
    filtered index, disabled index.

> R1/R2/M4 ortak kabul: hepsi **read-only**, `READ UNCOMMITTED` isolation
> (mevcut `application.yml` `connection-init-sql` ile uyumlu), `sys.*` only —
> kullanıcı verisine dokunmaz, PII riski yok.

---

## 6. Phase 2 (DB adapter pattern) — defer notu

Codex `019e2d7d` §3-4: Phase 2 (A) — `SchemaExtractor` interface +
MSSQL/PG/MySQL/Oracle extractor + auth adapter + multi-tenancy DataSource —
**ADR-level mimari değişim**, yüksek blast radius.

**Karar**: **Defer until non-MSSQL engine demand.** Phase 2, somut bir
non-MSSQL ERP bağlama talebi gelene kadar başlatılmaz. Gerekçe:
- Mevcut tüm kaynak (Workcube `workcube_mikrolink`) MSSQL — adapter soyutlaması
  şu an tek implementasyonu sarar, net değer üretmez (YAGNI).
- B1 capability'leri (FK/unique/index/programmability) `sys.*`'a bağlı —
  Phase 2 adapter'ı bu B1 modelini de soyutlamak zorunda kalır; B1'i Phase 2
  ÖNCESİ tamamlamak adapter interface'ini daha olgun veriyle tasarlar.
- Sıra: **B1 → B2 → (talep gelirse) Phase 2 → B3 UX**. Phase 2 araya girerse
  B1 modeli iki kez elden geçer.

Phase 2 tetik sinyali: müşteri/owner "PG/MySQL/Oracle ERP bağlanacak" beyanı.
O noktada ayrı bir Phase 2 planning artifact (B0 muadili) açılır.

---

## 7. Sıradaki adım

Bu B0 artifact **karar bekler** — hiçbir kod PR'ı tetiklemez:

1. **Operator zinciri** (critical path) — Annex 2A 3 imza + SEAL flip + PROD
   cutover. B0 bununla paralel, onu bloklamaz.
2. **B1 "başla" kararı** — owner, B1 slice'ı (9 authoritative capability) +
   truth-tier ADR'sini onaylarsa Sprint 1 implementasyonu açılır. Cross-AI:
   her PR Codex review.
3. **Truth-tier ADR** — §4 taslağı, B1 ilk PR'ıyla birlikte resmi
   `docs/adr/` ADR'sine dönüşür (açık sorular §4 sonu cevaplanır).

---

## 8. Cross-AI Trace

```yaml
implementer_ai: Claude
reviewer_ai: Codex
codex_threads:
  019e2d7d-d01d-7583-94a5-26d465df6abe: |
    Phase 1 quick wins plan+impl+review zinciri; ardından stratejik
    yön verdict C+B-plan-only — bu B0 doc o verdict'in çıktısı.
  019e2cca-e7d6-70f3-96b8-ae5fd2b21133: |
    Capability gap matrix (30 madde) — bu B0'ın baz aldığı kaynak.
verdict: B-plan-only (Codex 019e2d7d) — non-code planning artifact,
         implementasyon ayrı owner "başla" + ADR kabulü bekler.
key_constraint: |
  Bu doc hiçbir kod/model/refactor PR'ını yetkilendirmez. A (Phase 2 DB
  adapter) defer; B (capability gap) yalnızca B1/B2/B3 backlog + ADR
  taslağı + acceptance criteria seviyesinde hazır.
```

---

## 9. Referans

| Doküman | Konu |
|---|---|
| `docs/schema-truth-contract-capability-gap-matrix.md` (PR #693) | 30 madde gap matrix — bu B0'ın bazı |
| `docs/schema-service-scope-expansion-impact.md` (PR #698) | Kapsam genişlemesi etki + 3-sprint ROI |
| `docs/schema-service-multi-source-portability.md` (PR #701/#712) | Phase 1-2-3 portability roadmap |
| `docs/schema-service-detected-vs-inferred-truth.md` (PR #691) | Detected/inferred/missing baseline |
| Codex thread `019e2d7d` | Phase 1 quick wins + stratejik yön verdict |
