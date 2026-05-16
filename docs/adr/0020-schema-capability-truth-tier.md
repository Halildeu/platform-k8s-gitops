# ADR-0020 — Schema Capability Truth-Tier Model

> **Status**: Accepted (2026-05-16) — Codex `019e2d7d` cross-AI AGREE; PR merge = resmi kabul
> **Owner**: Platform-Eng
> **Date**: 2026-05-16
> **Sprint**: B1 Capability Gap Sprint
> **Codex thread**: `019e2d7d-d01d-7583-94a5-26d465df6abe` (B0 planning + B1 plan + bu ADR)
> **Related**: ADR-0005 Dual DataSource Reporting (Tier 1 schema-service authority) | ADR-0012-SS Schema-Service Admin Operations
> **Kaynak**: `docs/schema-truth-contract-capability-gap-matrix.md` (PR #693, 30 gap) §0/§4 + `docs/schema-capability-gap-sprint-b0.md` (PR #714) §4

---

## 1. Bağlam

`schema-service` Workcube MSSQL şemasını çıkarır. Mevcut model iki ayrı türde bilgiyi **aynı confidence semantiğiyle** sunuyor:

- **Authoritative** — `sys.*` doğrudan extraction: PK, identity, nullable, tip, satır sayısı. Kesin truth.
- **Heuristic** — `RelationshipDiscoveryService` çıkarımı: FK ilişkileri name match / alias / common-FK / view parse'tan türetilir (`confidence` 0.80-0.92).

`Relationship` modeli `confidence` alanı taşıyor ama adı ve sunumu "FK truth" izlenimi veriyor. Oysa çıktı **heuristic evidence** — yanılabilir. Codex `019e2cca` (capability gap matrix paralel review) key finding: model "relationship evidence with confidence" olarak yeniden konumlanmalı; `authoritative_mssql` ile `inferred_metadata` SchemaLens UI'da aynı renkte gösterilmemeli.

B1 Capability Gap Sprint başlıyor (`docs/schema-capability-gap-sprint-b0.md` — 9 authoritative capability). B1-2 (R1 real FK + R2 unique constraint) `sys.foreign_keys` / `sys.indexes`'ten **gerçek authoritative** FK/unique çıkaracak — bu, heuristic `Relationship` ile authoritative FK'yi tek sistemde ayırt etme zorunluluğu doğuruyor. Codex `019e2d7d`: *"R1/R2'ye gelmeden önce truth-tier modeli resmi karara bağlanmalı — `RelationshipEvidence`, tier semantics ve UI badge artık API/mimari kararı."*

## 2. Karar

### 2.1 Altı truth tier

Her capability bilgisi şu tier'lardan birine sınıflanır:

| Tier | Tanım | Örnek |
|---|---|---|
| `authoritative_mssql` | `sys.*` doğrudan extraction | PK, identity, nullable, tip, **real FK**, **unique constraint**, index |
| `inferred_metadata` | Naming / alias / view-parse heuristic | Mevcut `Relationship` (name_match, alias, common_fk, view_parse) |
| `sampled_data` | Gerçek veri örneklemesi | Orphan ratio, null ratio, distinct count (B2 sprint) |
| `workload_observed` | Query Store / plan cache | En çok join'lenen tablo çiftleri (B2 sprint) |
| `manual_domain` | DBA / operator annotation | Business glossary, semantic class (B3 sprint) |
| `unsupported` | Sorgulanmıyor / kapsam dışı | — |

Tier'lar **farklı confidence semantiği** taşır. SchemaLens UI, drift ekranı ve AI Chat tier'a göre ayrı sunmalı — `authoritative_mssql` kesin, `inferred_metadata` olasılıksal.

### 2.2 ColumnInfo genişletme (B1-1 — uygulandı)

B1-1 (PR #224) `ColumnInfo`'yu 7→16 alana genişletti — yeni alanlar (precision, scale, collation, identity seed/increment, default/computed expression, sparse) hepsi `authoritative_mssql`. Additive + 7-arg legacy constructor ile backward-compatible. Bu ADR retroaktif onaylar: additive authoritative metadata düşük blast-radius taşıdığı için ADR-öncesi uygulanabildi (Codex `019e2d7d` M2-first verdict). Sonraki capability'ler (R1/R2/M4 — constraint/index) bu ADR'ye tabidir.

### 2.3 Authoritative inventory modelleri (B1-2+)

R1/R2/M4 (real FK, unique constraint, non-PK index) için **ayrı inventory modelleri** kullanılır: `ForeignKeyInfo`, `UniqueConstraintInfo`, `IndexInfo`. Composite key sırası, `is_disabled`, `is_not_trusted`, cascade action gibi authoritative ayrıntılar heuristic `Relationship` record'una sıkıştırılmaz — ayrı model temiz tier ayrımı sağlar.

### 2.4 RelationshipEvidence rename — ERTELENDİ

`Relationship` → `RelationshipEvidence` rename'i (model: `tier` + `sources[]` + `category` + `orphanRatio` + `typeCompatibilityScore` alanları — gap matrix §4) bu ADR'de **karar olarak kabul edilir**, ancak **implementasyonu ertelenir**. Gerekçe (Codex `019e2d7d`): rename `/snapshot` API kontratı + path-find + impact BFS + SchemaLens UI + report-service `SchemaSnapshot` mirror'ı geniş koordinasyon ister; B1'in ilk yarısında yapılması riski yükseltir.

**B1-2 yaklaşımı — iki katman:**

- **Compatibility layer**: B1-2 authoritative FK'leri mevcut `relationships` listesine `source="fk_constraint"`, `confidence=1.0` ile ekler. Path-find, impact BFS, AI description mevcut tüketicilerle kırılmadan çalışmaya devam eder.
- **Authoritative inventory layer**: ayrı `ForeignKeyInfo` / `UniqueConstraintInfo` / `IndexInfo` modelleri gerçek constraint metadata'sını (composite, trusted/disabled, cascade) taşır.

`RelationshipEvidence` rename'i B1 sprint sonrası — resmi SchemaLens frontend (truth-tier UI badge) planıyla birlikte ayrı PR + kendi API-versiyon kararı.

## 3. Sonuçlar

### Pozitif
- SchemaLens UI authoritative ↔ inferred ayrımı yapabilir; drift ekranı authoritative drift'i inferred drift'ten ayrı renkte gösterir.
- AI Chat "bu kolon unique" / "real FK var" iddialarını tier'a göre kalifiye eder — CLAUDE.md kural #9 drift guard ile uyumlu (agent authoritative ≠ inferred ayrımını korur).
- B1-2 compatibility layer sayesinde mevcut `/snapshot` tüketicileri (report-service mirror, path-find, AI) kırılmaz.

### Negatif
- `RelationshipEvidence` rename'i tier modeli tam değer üretene kadar teknik borç olarak kalır (B1 sprint sonrası kapanır).
- B1-2 compat layer geçiş dönemi tekrarı yaratır: authoritative FK iki yerde görünür — `relationships` listesi (compat) + `ForeignKeyInfo` inventory (authoritative). Rename tamamlanınca tekrar kalkar.

### Neutral
- `ColumnInfo` (B1-1) ayrı `tier` alanı taşımıyor — sütun metadata'sının authoritative olduğu zaten net. Tier ayrımı ağırlıklı olarak ilişki/evidence tarafında (heuristic vs authoritative FK) anlamlı.

## 4. İmplementasyon sırası

B0 doc §3 B1 PR-batch: **B1-1 M2 ✓ (PR #224)** → B1-2 R1+R2 → B1-3 M3 → B1-4 M4 → B1-5 M1 → B1-6 M6 → B1-7 M13 → B1-8 M15. B2 (sampled_data + workload_observed tier'ları) ve B3 (manual_domain tier + RelationshipEvidence rename + truth-tier UI badge) ayrı sprint — owner kararıyla açılır.

## 5. Açık sorular

1. **`/snapshot` API versiyonlama** — `RelationshipEvidence` rename geldiğinde API kontratı kırılır mı? → Bu ADR rename'i erteler; B1-2 compatibility layer ile kontrat korunur. Rename PR'ı kendi API-versiyon kararını (additive vs v2 path) taşıyacak.
2. **`sampled_data` PII guardrail** — orphan/null ratio sampling kullanıcı verisine dokunur. → B2 sprint kararı; opt-in + masking + read-only + query timeout zorunlu (gap matrix §3.5). B1 kapsamı dışında.
3. **Truth-tier UI badge owner** — SchemaLens'te tier badge tasarımı kim sahiplenir? → B3 (UX) sprint; SchemaLens frontend owner. B1 backend tier alanlarını üretir, UI B3'te tüketir.

## 6. Bağlantılı kontratlar

- ADR-0005 Dual DataSource Reporting — Tier 1 schema-service authority
- ADR-0012-SS Schema-Service Admin Operations — `/snapshot` scope parametresi
- `docs/schema-truth-contract-capability-gap-matrix.md` (PR #693) — 30 gap; §0 tier modelinin kaynağı
- `docs/schema-capability-gap-sprint-b0.md` (PR #714) — B1 sprint backlog + §4 ADR taslağı
- Codex thread `019e2d7d` — B0 planning + B1 plan istişaresi + bu ADR

## 7. Cross-AI Trace

```yaml
implementer_ai: Claude
reviewer_ai: Codex
codex_thread: 019e2d7d-d01d-7583-94a5-26d465df6abe
verdict: AGREE (B0 planning + B1 M2-first plan); bu ADR'nin cross-AI review'ı PR'da
key_decision: |
  Altı truth tier resmi. ColumnInfo genişletme B1-1'de (PR #224)
  uygulandı, ADR retroaktif onaylar. RelationshipEvidence rename karar
  olarak kabul ama implementasyonu B1 sprint sonrasına ertelendi;
  B1-2 compatibility layer (relationships listesine fk_constraint) +
  ayrı authoritative inventory modeli (ForeignKeyInfo / UniqueConstraintInfo
  / IndexInfo).
```

---

**Status**: Accepted — Codex `019e2d7d` cross-AI AGREE; PR merge = resmi kabul. B1-2 (R1+R2 real FK + unique constraint) bu ADR sonrası başlar.
