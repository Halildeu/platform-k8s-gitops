# V16 DDL Manual Review (Faz 16.2 Gün 3)

> Generator: `scripts/migration/generate_v16_sql.py`
> Codex iter-4 AGREE: 23 matched + 17 parametric placeholder + blocked kolon report

## Summary

- Total tables: 40
- Matched canonical (snapshot var): **20**
- Parametric (placeholder): **17**
- No snapshot (unexpected): 3
- Blocked columns: **0**

## Per-table review checklist

| Table | Type | Columns | Reports | PK status |
|---|---|---|---|---|
| `ACCOUNT_CARD` | parametric | ? | fin-kaynak-eslesme, fin-muhasebe-detay, fin-muhasebe-fisleri | TODO Faz 16.2.P |
| `ACCOUNT_CARD_MONEY` | parametric | ? | fin-muhasebe-detay | TODO Faz 16.2.P |
| `ACCOUNT_CARD_ROWS` | parametric | ? | fin-gerceklesen-maliyet, fin-kaynak-eslesme, fin-muhasebe-de | TODO Faz 16.2.P |
| `ACCOUNT_PLAN` | parametric | ? | fin-muhasebe-detay | TODO Faz 16.2.P |
| `BANK_ACTIONS` | parametric | ? | fin-banka-hareketleri, fin-nakit-akis-ozet, fin-tutar-mutaba | TODO Faz 16.2.P |
| `BRANCH` | canonical | 107 | fin-muhasebe-detay, hr-compensation-detay | surrogate (TODO business PK) |
| `BUDGET_PLAN_ROW` | parametric | ? | fin-butce-gerceklesen | TODO Faz 16.2.P |
| `CARI_ACTIONS` | parametric | ? | fin-cari-islemler, fin-tutar-mutabakat | TODO Faz 16.2.P |
| `CARI_ROWS` | parametric | ? | fin-cari-hareketler, fin-cari-mutabakat | TODO Faz 16.2.P |
| `CASH_ACTIONS` | parametric | ? | fin-kasa-hareketleri | TODO Faz 16.2.P |
| `CHEQUE` | parametric | ? | fin-cek-senet, fin-cek-vade-takip | TODO Faz 16.2.P |
| `COMPANY` | canonical | 113 | fin-cari-islemler, fin-fatura-satirlari, fin-kaynak-eslesme | surrogate (TODO business PK) |
| `COMPANY_REMAINDER` | parametric | ? | fin-alacak-yaslandirma, fin-borc-yaslandirma | TODO Faz 16.2.P |
| `CONSUMER` | canonical | 157 | fin-muhasebe-detay | surrogate (TODO business PK) |
| `DEPARTMENT` | canonical | 43 | fin-muhasebe-detay | surrogate (TODO business PK) |
| `EMPLOYEES` | canonical | 72 | fin-muhasebe-detay, hr-compensation-detay | surrogate (TODO business PK) |
| `EMPLOYEES_DETAIL` | canonical | 151 | hr-compensation-detay | surrogate (TODO business PK) |
| `EMPLOYEES_IDENTY` | canonical | 38 | hr-compensation-detay | surrogate (TODO business PK) |
| `EMPLOYEES_IN_OUT` | canonical | 200 | hr-compensation-detay, hr-giris-cikis | surrogate (TODO business PK) |
| `EMPLOYEES_PUANTAJ` | canonical | 26 | hr-compensation-detay | surrogate (TODO business PK) |
| `EMPLOYEES_PUANTAJ_ROWS` | canonical | 283 | hr-bordro-detay, hr-compensation-detay | surrogate (TODO business PK) |
| `EMPLOYEES_SALARY` | canonical | 36 | hr-maas-raporu | surrogate (TODO business PK) |
| `EMPLOYEES_SALARY_HISTORY` | canonical | 34 | hr-maas-gecmisi | surrogate (TODO business PK) |
| `EMPLOYEE_DAILY_IN_OUT` | canonical | 37 | hr-puantaj | surrogate (TODO business PK) |
| `EMPLOYEE_POSITIONS` | canonical | 102 | hr-compensation-detay, hr-personel-listesi | surrogate (TODO business PK) |
| `EXPENSE_ITEMS` | parametric | ? | fin-masraf-detay | TODO Faz 16.2.P |
| `EXPENSE_ITEM_PLANS` | parametric | ? | fin-masraf-detay, fin-tutar-mutabakat | TODO Faz 16.2.P |
| `INVOICE` | parametric | ? | fin-fatura-satirlari, fin-faturalar, fin-tutar-mutabakat | TODO Faz 16.2.P |
| `INVOICE_ROW` | parametric | ? | fin-fatura-satirlari | TODO Faz 16.2.P |
| `MONEY_HISTORY` | canonical | 19 | fin-muhasebe-detay | surrogate (TODO business PK) |
| `OFFTIME` | canonical | 62 | hr-izin-raporu | surrogate (TODO business PK) |
| `ORDERS` | no-snapshot | 0 | satis-ozet | FAIL |
| `ORDER_ROW` | no-snapshot | 0 | stok-durum | FAIL |
| `OUR_COMPANY` | canonical | 68 | hr-compensation-detay | surrogate (TODO business PK) |
| `PRO_PROJECTS` | canonical | 75 | fin-cari-islemler, fin-fatura-satirlari, fin-masraf-detay | surrogate (TODO business PK) |
| `SETUP_DOCUMENT_TYPE` | canonical | 9 | fin-muhasebe-detay | surrogate (TODO business PK) |
| `SETUP_PROCESS_CAT` | no-snapshot | 0 | fin-cari-islemler, fin-kaynak-eslesme, fin-masraf-detay | FAIL |
| `STOCK_FIS` | parametric | ? | fin-stok-fis-detay | TODO Faz 16.2.P |
| `STOCK_FIS_ROW` | parametric | ? | fin-stok-fis-detay | TODO Faz 16.2.P |
| `TRAINING_CLASS_ATTENDER` | canonical | 12 | hr-egitim-katilim | surrogate (TODO business PK) |

## Sıradaki sprint

- **Faz 16.2.P Schema Snapshot Enrichment**: schema-service parametric crawl + PK + scale metadata (Codex iter-4 ayrı sprint)
- **Gün 4**: Worker skeleton (Python + pyodbc + COPY)
- **Gün 5-7**: Transform + retry + reconcile + dry-run
