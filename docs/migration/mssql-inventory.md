# Faz 16.1 - MSSQL Source Inventory

> **Status**: GENERATED 2026-04-25 - ETL scope baseline
> **Source**: schema-service `/api/v1/schema/snapshot` (1509 tablo + 26240 kolon)
> **Annex**: `docs/migration/report-source-annex.yaml` (31 rapor + 44 unique tablo)

## Scope decision

- Toplam Workcube tablo: **1509**
- Raporlarda kullanilan: **40** (annex 2A allowlist)
- Snapshot match: **23/40**
- ETL scope: **23 tablo** (annex + snapshot ortak)

## Per-report classification

| Report | Tablo sayisi | Kategori |
|---|---|---|
| `fin-alacak-yaslandirma` | 1 | Finans |
| `fin-banka-hareketleri` | 1 | Finans |
| `fin-borc-yaslandirma` | 1 | Finans |
| `fin-butce-gerceklesen` | 1 | Finans |
| `fin-cari-hareketler` | 1 | Finans |
| `fin-cari-islemler` | 4 | Finans |
| `fin-cari-mutabakat` | 1 | Finans |
| `fin-cek-senet` | 1 | Finans |
| `fin-cek-vade-takip` | 1 | Finans |
| `fin-fatura-satirlari` | 4 | Finans |
| `fin-faturalar` | 1 | Finans |
| `fin-gerceklesen-maliyet` | 1 | Finans |
| `fin-kasa-hareketleri` | 1 | Finans |
| `fin-kaynak-eslesme` | 4 | Finans |
| `fin-masraf-detay` | 5 | Finans |
| `fin-muhasebe-detay` | 13 | Finans |
| `fin-muhasebe-fisleri` | 1 | Finans |
| `fin-nakit-akis-ozet` | 1 | Finans |
| `fin-stok-fis-detay` | 4 | Finans |
| `fin-tutar-mutabakat` | 8 | Finans |
| `hr-bordro-detay` | 1 | İnsan Kaynakları |
| `hr-compensation-detay` | 9 | İnsan Kaynakları |
| `hr-egitim-katilim` | 1 | İnsan Kaynakları |
| `hr-giris-cikis` | 1 | İnsan Kaynakları |
| `hr-izin-raporu` | 1 | İnsan Kaynakları |
| `hr-maas-gecmisi` | 1 | İnsan Kaynakları |
| `hr-maas-raporu` | 1 | İnsan Kaynakları |
| `hr-personel-listesi` | 1 | İnsan Kaynakları |
| `hr-puantaj` | 1 | İnsan Kaynakları |
| `satis-ozet` | 1 | Satış |
| `stok-durum` | 1 | Satış |

## ETL scope tables (alphabetical)

| Table | Reports using | In snapshot |
|---|---|---|
| `ACCOUNT_CARD` | fin-kaynak-eslesme, fin-muhasebe-detay, fin-muhasebe-fisleri, fin-tutar-mutabaka | NO (parametric) |
| `ACCOUNT_CARD_MONEY` | fin-muhasebe-detay | NO (parametric) |
| `ACCOUNT_CARD_ROWS` | fin-gerceklesen-maliyet, fin-kaynak-eslesme, fin-muhasebe-detay, fin-tutar-mutab | NO (parametric) |
| `ACCOUNT_PLAN` | fin-muhasebe-detay | OK |
| `BANK_ACTIONS` | fin-banka-hareketleri, fin-nakit-akis-ozet, fin-tutar-mutabakat | NO (parametric) |
| `BRANCH` | fin-muhasebe-detay, hr-compensation-detay | OK |
| `BUDGET_PLAN_ROW` | fin-butce-gerceklesen | OK |
| `CARI_ACTIONS` | fin-cari-islemler, fin-tutar-mutabakat | NO (parametric) |
| `CARI_ROWS` | fin-cari-hareketler, fin-cari-mutabakat | NO (parametric) |
| `CASH_ACTIONS` | fin-kasa-hareketleri | NO (parametric) |
| `CHEQUE` | fin-cek-senet, fin-cek-vade-takip | NO (parametric) |
| `COMPANY` | fin-cari-islemler, fin-fatura-satirlari, fin-kaynak-eslesme, fin-masraf-detay, f | OK |
| `COMPANY_REMAINDER` | fin-alacak-yaslandirma, fin-borc-yaslandirma | NO (parametric) |
| `CONSUMER` | fin-muhasebe-detay | OK |
| `DEPARTMENT` | fin-muhasebe-detay | OK |
| `EMPLOYEES` | fin-muhasebe-detay, hr-compensation-detay | OK |
| `EMPLOYEES_DETAIL` | hr-compensation-detay | OK |
| `EMPLOYEES_IDENTY` | hr-compensation-detay | OK |
| `EMPLOYEES_IN_OUT` | hr-compensation-detay, hr-giris-cikis | OK |
| `EMPLOYEES_PUANTAJ` | hr-compensation-detay | OK |
| `EMPLOYEES_PUANTAJ_ROWS` | hr-bordro-detay, hr-compensation-detay | OK |
| `EMPLOYEES_SALARY` | hr-maas-raporu | OK |
| `EMPLOYEES_SALARY_HISTORY` | hr-maas-gecmisi | OK |
| `EMPLOYEE_DAILY_IN_OUT` | hr-puantaj | OK |
| `EMPLOYEE_POSITIONS` | hr-compensation-detay, hr-personel-listesi | OK |
| `EXPENSE_ITEMS` | fin-masraf-detay | OK |
| `EXPENSE_ITEM_PLANS` | fin-masraf-detay, fin-tutar-mutabakat | NO (parametric) |
| `INVOICE` | fin-fatura-satirlari, fin-faturalar, fin-tutar-mutabakat | NO (parametric) |
| `INVOICE_ROW` | fin-fatura-satirlari | NO (parametric) |
| `MONEY_HISTORY` | fin-muhasebe-detay | OK |
| `OFFTIME` | hr-izin-raporu | OK |
| `ORDERS` | satis-ozet | NO (parametric) |
| `ORDER_ROW` | stok-durum | NO (parametric) |
| `OUR_COMPANY` | hr-compensation-detay | OK |
| `PRO_PROJECTS` | fin-cari-islemler, fin-fatura-satirlari, fin-masraf-detay, fin-muhasebe-detay, f | OK |
| `SETUP_DOCUMENT_TYPE` | fin-muhasebe-detay | OK |
| `SETUP_PROCESS_CAT` | fin-cari-islemler, fin-kaynak-eslesme, fin-masraf-detay, fin-muhasebe-detay, fin | NO (parametric) |
| `STOCK_FIS` | fin-stok-fis-detay | NO (parametric) |
| `STOCK_FIS_ROW` | fin-stok-fis-detay | NO (parametric) |
| `TRAINING_CLASS_ATTENDER` | hr-egitim-katilim | OK |

## Unmatched tables (parametric - schema_mode=yearly)

Snapshot canonical schema=workcube_mikrolink. Parametric schemas (workcube_mikrolink_1, _2, ...) annex variations.

- `ACCOUNT_CARD` - used by: fin-kaynak-eslesme, fin-muhasebe-detay, fin-muhasebe-fisleri, fin-tutar-mutabakat
- `ACCOUNT_CARD_MONEY` - used by: fin-muhasebe-detay
- `ACCOUNT_CARD_ROWS` - used by: fin-gerceklesen-maliyet, fin-kaynak-eslesme, fin-muhasebe-detay, fin-tutar-mutabakat
- `BANK_ACTIONS` - used by: fin-banka-hareketleri, fin-nakit-akis-ozet, fin-tutar-mutabakat
- `CARI_ACTIONS` - used by: fin-cari-islemler, fin-tutar-mutabakat
- `CARI_ROWS` - used by: fin-cari-hareketler, fin-cari-mutabakat
- `CASH_ACTIONS` - used by: fin-kasa-hareketleri
- `CHEQUE` - used by: fin-cek-senet, fin-cek-vade-takip
- `COMPANY_REMAINDER` - used by: fin-alacak-yaslandirma, fin-borc-yaslandirma
- `EXPENSE_ITEM_PLANS` - used by: fin-masraf-detay, fin-tutar-mutabakat
- `INVOICE` - used by: fin-fatura-satirlari, fin-faturalar, fin-tutar-mutabakat
- `INVOICE_ROW` - used by: fin-fatura-satirlari
- `ORDERS` - used by: satis-ozet
- `ORDER_ROW` - used by: stok-durum
- `SETUP_PROCESS_CAT` - used by: fin-cari-islemler, fin-kaynak-eslesme, fin-masraf-detay, fin-muhasebe-detay, fin-stok-fis-detay, fin-tutar-mutabakat
- `STOCK_FIS` - used by: fin-stok-fis-detay
- `STOCK_FIS_ROW` - used by: fin-stok-fis-detay

---

## Parametric Schema Enumeration (Faz 16.1 Gün 1 deliverable)

Codex iter-2 verdict: PG'de Workcube yıllık sub-schema **kopyalama** — tek logical schema + `source_year SMALLINT` + declarative partition.

### 16 parametric tablo (`{schema}` runtime placeholder + actual `workcube_mikrolink_N`)

| Table | Schema patterns | Reports |
|---|---|---|
| `ACCOUNT_CARD` | `workcube_mikrolink_2026_1`, `{schema}` | fin-kaynak-eslesme, fin-muhasebe-detay, fin-muhasebe-fisleri |
| `ACCOUNT_CARD_MONEY` | `{schema}` | fin-muhasebe-detay |
| `ACCOUNT_CARD_ROWS` | `workcube_mikrolink_2026_1`, `{schema}` | fin-gerceklesen-maliyet, fin-kaynak-eslesme, fin-muhasebe-detay |
| `ACCOUNT_PLAN` | `{schema}` | fin-muhasebe-detay |
| `BANK_ACTIONS` | `workcube_mikrolink_1` | fin-banka-hareketleri, fin-nakit-akis-ozet |
| `CARI_ACTIONS` | `{schema}` | fin-cari-islemler |
| `CARI_ROWS` | `workcube_mikrolink_1` | fin-cari-hareketler, fin-cari-mutabakat |
| `CASH_ACTIONS` | `workcube_mikrolink_1` | fin-kasa-hareketleri |
| `CHEQUE` | `workcube_mikrolink_1` | fin-cek-senet, fin-cek-vade-takip |
| `COMPANY_REMAINDER` | `workcube_mikrolink_1` | fin-alacak-yaslandirma, fin-borc-yaslandirma |
| `EXPENSE_ITEMS` | `{schema}` | fin-masraf-detay |
| `EXPENSE_ITEM_PLANS` | `{schema}` | fin-masraf-detay |
| `INVOICE` | `workcube_mikrolink_1`, `{schema}` | fin-fatura-satirlari, fin-faturalar |
| `INVOICE_ROW` | `{schema}` | fin-fatura-satirlari |
| `STOCK_FIS` | `{schema}` | fin-stok-fis-detay |
| `STOCK_FIS_ROW` | `{schema}` | fin-stok-fis-detay |

### Schema → year mapping (Workcube convention — admin onayı gerek)

| Schema | Fiscal year |
|---|---|
| `workcube_mikrolink` | canonical (year-independent) |
| `workcube_mikrolink_1` | 2024 (?) |
| `workcube_mikrolink_2` | 2025 (?) |
| `workcube_mikrolink_3` | 2026 (current?) |
| `workcube_mikrolink_2026_1` | 2026 specific (suffix mantıksız) |
| `{schema}` | runtime resolved (rapor query parametre) |

**ÖNEMLI**: Workcube admin'den schema enumeration kuralı net teyit gerek. `_1`, `_2`, `_2026_1` patterns inconsistent.

### PG canonical pattern (Codex AGREE)

```sql
-- Tek logical schema
CREATE SCHEMA workcube_mikrolink;

-- Partitioned table (per year)
CREATE TABLE workcube_mikrolink.invoice (
    id BIGINT,
    source_year SMALLINT NOT NULL,
    source_schema VARCHAR(50) NOT NULL,  -- audit trail
    -- ... other columns
    PRIMARY KEY (id, source_year)
) PARTITION BY LIST (source_year);

CREATE TABLE workcube_mikrolink.invoice_2024 PARTITION OF workcube_mikrolink.invoice FOR VALUES IN (2024);
CREATE TABLE workcube_mikrolink.invoice_2025 PARTITION OF workcube_mikrolink.invoice FOR VALUES IN (2025);
CREATE TABLE workcube_mikrolink.invoice_2026 PARTITION OF workcube_mikrolink.invoice FOR VALUES IN (2026);
```

Compatibility view (eğer rapor SQL literal schema bekliyorsa):

```sql
CREATE VIEW workcube_mikrolink_1.invoice AS SELECT * FROM workcube_mikrolink.invoice WHERE source_year = 2024;
```

## Sıradaki: Faz 16.0 Data Contract REVIEWED → SEALED gate

- 16 parametric tablo schema enumeration **netleşmesi** (admin onayı)
- 17 unmatched edge case'lerin classification ✓
- Type mapping matrix per-table (40 tablo)
- ADR-0005 schema-service parity addendum

Codex thread: `019dc6d5` iter-2 AGREE.
