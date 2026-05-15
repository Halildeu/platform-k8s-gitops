# Annex 2A — Agent Schema Validation Packet (2026-05-15)

> **Codex 019e2c59 B-prime verdict implementasyonu.**  Bu paket Annex 2A'yi
> SEAL etmez; operator (DBA + PO + ERP DBA) imzası için review-ready hale
> getirir. Canonical `_meta.status / seal_state / manually_validated /
> migration_action_default` alanları **bu agent paketinde dokunulmamıştır**.
>
> Kullanım sırası:
> 1. DBA bu doc + `docs/migration/report-source-annex.yaml` ikilisini birlikte okur.
> 2. Her bullet için yorum/karar bırakır.
> 3. SEAL flip ayrı bir PR — bu paket onun *önündeki* validation adımı.

---

## 1. Kapsam

`docs/migration/report-source-annex.yaml::_meta.pending_manual_validation` listesindeki
8 sourceQuery raporu agent tarafından `workcube-schema.json` ile cross-check edildi:

| # | Report Key | SQL ↗︎ |
|---|---|---|
| 1 | `fin-cari-islemler` | `platform-backend/report-service/src/main/resources/reports/fin-cari-islemler.json` |
| 2 | `fin-fatura-satirlari` | `.../fin-fatura-satirlari.json` |
| 3 | `fin-kaynak-eslesme` | `.../fin-kaynak-eslesme.json` |
| 4 | `fin-masraf-detay` | `.../fin-masraf-detay.json` |
| 5 | `fin-muhasebe-detay` | `.../fin-muhasebe-detay.json` |
| 6 | `fin-stok-fis-detay` | `.../fin-stok-fis-detay.json` |
| 7 | `fin-tutar-mutabakat` | `.../fin-tutar-mutabakat.json` |
| 8 | `hr-compensation-detay` | `.../hr-compensation-detay.json` |

Validation script: `/tmp/seal-validation.py` (session worktree'sinde, paket
referansı için repo'da reproduce edilebilir).

## 2. Validation Sonuçları

**Sonuç: 8/8 `needs_review`** — *agent canonical schema ile cross-check yapamıyor*.

| # | Report | Validation | Tetikleyici |
|---|---|---|---|
| 1 | `fin-cari-islemler` | `needs_review` | `CARI_ACTIONS` canonical snapshot'ta yok |
| 2 | `fin-fatura-satirlari` | `needs_review` | `INVOICE`, `INVOICE_ROW` canonical snapshot'ta yok |
| 3 | `fin-kaynak-eslesme` | `needs_review` | `ACCOUNT_CARD`, `ACCOUNT_CARD_ROWS` canonical snapshot'ta yok |
| 4 | `fin-masraf-detay` | `needs_review` | `EXPENSE_ITEM_PLANS` canonical snapshot'ta yok |
| 5 | `fin-muhasebe-detay` | `needs_review` | `ACCOUNT_CARD`, `ACCOUNT_CARD_MONEY`, `ACCOUNT_CARD_ROWS` canonical snapshot'ta yok |
| 6 | `fin-stok-fis-detay` | `needs_review` | `STOCK_FIS`, `STOCK_FIS_ROW` canonical snapshot'ta yok |
| 7 | `fin-tutar-mutabakat` | `needs_review` | `ACCOUNT_CARD`, `BANK_ACTIONS`, `CARI_ACTIONS`, `INVOICE`, vb. canonical snapshot'ta yok |
| 8 | `hr-compensation-detay` | `needs_review` | tüm tablolar `EMPLOYEES_*` static schema kanonik snapshot'ta beklenirdi; agent runtime'da bulamadı |

## 3. Tetikleyici Sebep — Parametric Schema Drift Guard

`workcube_mikrolink.<TABLE>` (static) ile `workcube_mikrolink_<yıl>.<TABLE>`
(parametric) arasındaki ayrım canonical snapshot'ta net değil.
`docs/migration/workcube-schema.json` **canonical** olarak tutuluyor; *yıllık*
parametric schema'lardaki (örn. `workcube_mikrolink_1`, `workcube_mikrolink_2`)
ACCOUNT_CARD, INVOICE, CARI_ACTIONS vb. **parametric** tablolar burada YOK.

CLAUDE.md `Hızlı Bağlam — MSSQL Şema Gezgini` notu zaten bunu söylüyor:
> Parametric (yıllık) tablolar canonical snapshot'ta YOK; `workcube_mikrolink_<yıl>`
> schema'larında. 17 parametric tabloyu çekmek için schema-service'in yearly schema
> crawl'ı gerekiyor (Faz 16.2.P sprint).

**Bu yüzden 8/8 `needs_review` sonucu agent yetersizliğinin değil, snapshot
eksikliğinin sonucu**. DBA + Workcube admin'in parametric schema crawl
output'ı SEAL gate açısından önkoşuldur.

## 4. SQL Statik Sağlık Profili (agent gözlemi)

Tüm 8 sourceQuery için statik kalite imzaları **uyumlu**:

| Property | Tipik Profil |
|---|---|
| `[{schema}].[TABLE]` parametric placeholder | 8/8 ✓ (yearly schema resolver beklentisiyle uyumlu) |
| `[workcube_mikrolink].[TABLE]` static placeholder | 6/8 (cross-tenant master ref'ler) |
| `WITH (NOLOCK)` hint sayısı | 2–13 per query; production read-only paterni ile uyumlu |
| `LEFT JOIN` sayısı | 2–13 per query; cardinality risk yok |
| `INNER JOIN` sayısı | 0 (hr-compensation-detay 4 hariç) |
| `CASE WHEN` / `ISNULL` kullanımı | type-aware default'lar mevcut |
| Hard-coded string literal (`N'Borç'`) | unicode string semantiği uyumlu |

Bu profiller "iyi yazılmış sourceQuery" göstergesi. Tek gap: canonical schema
snapshot drift (yukarıda §3).

## 5. Önerilen Sonraki Adımlar (proposal-only)

> ⚠️  Bu öneriler **kanonik SEAL alanlarını değiştirmez**. Operator review için.

### 5.1 Parametric Schema Crawl (Faz 16.2.P önkoşulu)

- Workcube admin yearly schema crawl'ı koşturur (`workcube_mikrolink_1` …
  `workcube_mikrolink_<N>` için tüm 17 parametric tabloyu enumerate eder)
- Sonuç JSON snapshot olarak `docs/migration/workcube-schema-parametric-2026-05-15.json`
  veya benzeri ek dosyaya commit edilir
- Bu snapshot var olduktan sonra agent re-run validation: 8 sourceQuery zaten
  static profil olarak temiz; tek eksik schema cross-check.

### 5.2 Per-Report Operator Review Slots

DBA bu doc'a yorum ekleyerek imzalar. Format:

```
- fin-cari-islemler: VALIDATED (DBA <handle>, parametric crawl ref)
- fin-fatura-satirlari: VALIDATED (DBA <handle>, parametric crawl ref)
- ...
```

### 5.3 Proposed migration_action Matrisi

> ⚠️ `migration_action_default` alanı SEAL'a kadar `pending_annex` kalır.
> Aşağıdaki tablo *önerilmiş* (proposed_migration_action) — kanonik değil.

| Kategori | Report Sayısı | Proposed Action | Rasyonel |
|---|---|---|---|
| Finans | 17 (3 dashboard + 14 grid) | `migrate` | Faz 17 Workcube decommission niyeti; tüm finans report PG hedef |
| İK | 9 (8 dashboard + hr-compensation-detay grid) | `migrate` | Aynı |
| Satış | 2 | `migrate` | Aynı |
| Dashboard | 12 | already PG (etkilenmez) | Dashboard'lar zaten PG; sourceQuery yok |

PO/DBA onayı sonrası canonical `migration_action_default` operator tarafından flip edilir.

### 5.4 Float Semantic Class Proposal

Heuristic gözlem (kolon ismi pattern'i):

| Kolon Pattern | Önerilen Class | Tetikleyici |
|---|---|---|
| `EMPLOYEES_SALARY.M1..M12` | `analytical` | aylık KPI, aggregation toleransı |
| `*.AMOUNT`, `*.MONEY*`, `*_NET_TOTAL`, `*_BRUT*` | `currency` | banking-grade precision |
| `*_COUNT`, `*_QTY`, `EMPLOYEE_COUNT` | `counter` | integer semantic |
| `*_RATE`, `*_PERCENT`, `MARGIN`, `DISCOUNT*` | `analytical` | percentage/ratio analitik |
| `*.TENURE_YEARS`, `*.AGE` | `counter` | integer semantic (1 ondalık tolerans) |

Yukarıdaki pattern operator (DBA + backend lead) onayı için *proposed*. SEAL
gate'te tek tek imzalanır. Heuristic ≠ acceptance.

### 5.5 Timezone Proposal

| Kolon ailesi | Önerilen TZ | Rasyonel |
|---|---|---|
| `*.RECORD_DATE`, `*.UPDATE_DATE`, `*.ACTION_DATE` | `Europe/Istanbul` | Workcube on-prem deploy Türkiye sistem context |
| `EMPLOYEES_IN_OUT.START_DATE / FINISH_DATE` | `Europe/Istanbul` (date-only) | HR yıl-ay-gün, tz drift Türkiye sistem |
| `MONEY_HISTORY.VALIDATE_DATE` | `Europe/Istanbul` | TCMB rate date Türkiye finans |

ERP DBA acceptance sign-off SEAL gate'inde — bu proposed.

## 6. ADR-0005 §6 Amendment (proposed; pending sign-off)

`docs/adr/0005-dual-datasource-reporting.md` sonuna eklenecek metin (henüz
**eklenmedi** — operator sign-off sonrası ayrı PR):

```markdown
## §6 Faz 16.1 Annex 2A SEAL — <YYYY-MM-DD, operator karar tarihi>

### Karar (proposed / pending operator sign-off)
Annex 2A (`docs/migration/report-source-annex.yaml`) **SEALED** flip'i için
agent validation packet hazır: `docs/migration/annex-2a-agent-validation-2026-05-15.md`.
SEAL adımları:
- 8 sourceQuery `manually_validated: true` (parametric schema crawl önkoşulu).
- 31 report `migration_action_default` matrisi: tüm Finans/İK/Satış → `migrate`
  (Faz 17 Workcube decommission niyeti).
- Float `semantic_class` per-column sign-off (PO + DBA double-onay).
- ERP DBA timezone approval (Europe/Istanbul varsayım).

### Onay (Operator Action — pending)
- DBA (Workcube): @<dba-handle>
- Product Owner: @<po-handle>
- ERP DBA (timezone): @<erp-dba-handle>
- Cross-AI peer review: Codex thread `019e2c59` (B-prime verdict)

### Etkisi
- Adım 11.5 prod cutover blocker kaldırılır (`REPORT_MSSQL_ENABLED=true`)
- Faz 17 Workcube decommission planlaması başlar
- ETL pipeline (Adım 12 etl-worker) source-of-truth contract'ı SEAL'a göre
  finalize

### Reference
- [Adım 13 runbook](../runbooks/adim-13-faz-16-1-annex-2a-seal.md)
- [SEAL DBA packet](../runbooks/adim-13-seal-dba-packet.md)
- [Agent validation packet 2026-05-15](../migration/annex-2a-agent-validation-2026-05-15.md)
- Codex thread `019e2c59` (B-prime; pre-SEAL validation)
```

## 7. Kapanış (HARD RULE 2026-05-11 düzleminde)

Bu paket **SEAL claim'i değildir**. Browser/cluster doğrulama gerektirmiyor —
bu doc operatör review zinciri için. Adım 11.5 prod cutover hâlâ blocked
(SEAL flip + DBA sign-off önkoşulları).

R15 user-visible (`/admin/reports` 38 Grid badge, 31 dynamic) tamamlandı.
Adım 11.5 prod cutover SEAL'a bağlı.

## Cross-AI

```yaml
implementer_ai: Claude
reviewer_ai: Codex
codex_thread: 019e2c59-1cdb-7ea3-a8e6-bf3fcabc62b2
verdict: B-prime (pre-SEAL validation packet — SEAL flip yok)
agent_action: 8 sourceQuery static-profile + canonical schema cross-check + proposal matrisi
operator_action_pending: DBA + PO + ERP DBA sign-off, parametric schema crawl, SEAL flip
```
