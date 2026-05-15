# Float / Numeric Semantic Class — Agent Proposal (2026-05-15)

> **Proposal-only.** Sign-off için **DBA + backend lead çift onay**. Imzalar gelene kadar `mssql-pg-data-contract.md §471 unknown_float_class` SEAL BLOCKER kalır.

> **Kapsam**: 31 report'un column metadata'sından çıkarılan 206 unique numeric kolon. Heuristic agent confidence (high/medium/low) sınıflandırma. DBA gerçek SQL DECIMAL/MONEY/FLOAT tipini doğrulamalı (schema-service `/snapshot?schema=` ile verify edilebilir).

## Özet

- Toplam unique numeric kolon: **206**
- Heuristic high/medium confidence: **58**
- needs_review (DBA manuel kategori): **148**
- Class dağılımı: {'needs_review': 148, 'currency': 34, 'counter': 6, 'rate': 6, 'analytical': 12}

## 1. High/Medium Confidence Proposal (58 kolon)

DBA + backend lead **çift onay** ile her satıra `approve` veya `change <new_class>` yazar.

| # | Column | UI Type | Agent Class | Subclass | Conf | Reports | DBA Approve | Backend Lead Approve |
|---|---|---|---|---|---|---|---|---|
| 1 | `OTHER_MONEY` | text | **currency** | currency_like | high | 6 (örn: fin-banka-hareketleri, fin-cari-hareketler, fin-cari-islemler) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 2 | `MONEY` | text | **currency** | currency_like | high | 4 (örn: hr-bordro-detay, hr-giris-cikis, hr-maas-gecmisi) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 3 | `NETTOTAL` | number | **currency** | currency_like | high | 3 (örn: fin-faturalar, satis-ozet, stok-durum) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 4 | `AMOUNT` | number | **currency** | currency_like | high | 2 (örn: fin-gerceklesen-maliyet, fin-muhasebe-detay) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 5 | `AMOUNT_CURRENCY` | text | **currency** | currency_like | high | 2 (örn: fin-gerceklesen-maliyet, fin-muhasebe-detay) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 6 | `BAKIYE` | number | **currency** | currency_like | high | 2 (örn: fin-alacak-yaslandirma, fin-borc-yaslandirma) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 7 | `BIRIM_FIYAT` | number | **currency** | currency_like | high | 2 (örn: fin-fatura-satirlari, fin-stok-fis-detay) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 8 | `GROSS_NET` | number | **currency** | currency_like | high | 2 (örn: hr-bordro-detay, hr-giris-cikis) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 9 | `IHBAR_AMOUNT` | number | **currency** | currency_like | high | 2 (örn: hr-bordro-detay, hr-giris-cikis) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 10 | `KDV_ORAN` | number | **rate** | rate_like | high | 2 (örn: fin-fatura-satirlari, fin-stok-fis-detay) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 11 | `KDV_TUTAR` | number | **currency** | currency_like | high | 2 (örn: fin-fatura-satirlari, fin-stok-fis-detay) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 12 | `KIDEM_AMOUNT` | number | **currency** | currency_like | high | 2 (örn: hr-bordro-detay, hr-giris-cikis) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 13 | `M1` | number | **analytical** | analytical_aggregate | high | 2 (örn: hr-maas-gecmisi, hr-maas-raporu) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 14 | `M10` | number | **analytical** | analytical_aggregate | high | 2 (örn: hr-maas-gecmisi, hr-maas-raporu) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 15 | `M11` | number | **analytical** | analytical_aggregate | high | 2 (örn: hr-maas-gecmisi, hr-maas-raporu) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 16 | `M12` | number | **analytical** | analytical_aggregate | high | 2 (örn: hr-maas-gecmisi, hr-maas-raporu) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 17 | `M2` | number | **analytical** | analytical_aggregate | high | 2 (örn: hr-maas-gecmisi, hr-maas-raporu) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 18 | `M3` | number | **analytical** | analytical_aggregate | high | 2 (örn: hr-maas-gecmisi, hr-maas-raporu) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 19 | `M4` | number | **analytical** | analytical_aggregate | high | 2 (örn: hr-maas-gecmisi, hr-maas-raporu) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 20 | `M5` | number | **analytical** | analytical_aggregate | high | 2 (örn: hr-maas-gecmisi, hr-maas-raporu) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 21 | `M6` | number | **analytical** | analytical_aggregate | high | 2 (örn: hr-maas-gecmisi, hr-maas-raporu) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 22 | `M7` | number | **analytical** | analytical_aggregate | high | 2 (örn: hr-maas-gecmisi, hr-maas-raporu) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 23 | `M8` | number | **analytical** | analytical_aggregate | high | 2 (örn: hr-maas-gecmisi, hr-maas-raporu) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 24 | `M9` | number | **analytical** | analytical_aggregate | high | 2 (örn: hr-maas-gecmisi, hr-maas-raporu) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 25 | `MIKTAR` | number | **counter** | counter_like | medium | 2 (örn: fin-fatura-satirlari, fin-stok-fis-detay) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 26 | `NET_TUTAR` | number | **currency** | currency_like | high | 2 (örn: fin-fatura-satirlari, fin-stok-fis-detay) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 27 | `PERIOD_YEAR` | number | **counter** | counter_like | high | 2 (örn: hr-maas-gecmisi, hr-maas-raporu) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 28 | `AGE` | number | **counter** | counter_like | high | 1 (örn: hr-compensation-detay) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 29 | `ALACAKLI_CARI` | text | **currency** | currency_like | high | 1 (örn: fin-cari-islemler) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 30 | `ALACAK_TOPLAM` | number | **currency** | currency_like | high | 1 (örn: fin-tutar-mutabakat) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 31 | `AMOUNT_2` | number | **currency** | currency_like | high | 1 (örn: fin-muhasebe-detay) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 32 | `AMOUNT_CURRENCY_2` | text | **currency** | currency_like | high | 1 (örn: fin-muhasebe-detay) | ☐ approve · ☐ change | ☐ approve · ☐ change |
| 33 | `BANKA_TUTAR` | number | **currency** | currency_like | high | 1 (örn: fin-tutar-mutabakat) | ☐ approve · ☐ change | ☐ approve · ☐ change |

## 2. Needs Review — Manuel Sınıflandırma (148 kolon)

Heuristic eşleşmedi. DBA bu kolonları manuel olarak `currency / analytical / rate / counter / identifier / boolean / other` enum'una dahil eder.

| # | Column | UI Type | Reports | Agent Note | DBA Class | DBA Sub-class |
|---|---|---|---|---|---|---|
| 1 | `EMPLOYEE_ID` | number | 8 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 2 | `COMPANY_ID` | number | 7 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 3 | `ACTION_ID` | number | 6 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 4 | `ACC_COMPANY_ID` | number | 5 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 5 | `ACTION_VALUE` | number | 5 | — | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 6 | `CARD_ID` | number | 5 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 7 | `BRANCH_ID` | number | 4 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 8 | `DEPARTMENT_ID` | number | 4 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 9 | `ACTION_TYPE` | number | 3 | Lookup/enum? Categorical olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 10 | `CARD_TYPE` | number | 3 | Lookup/enum? Categorical olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 11 | `FROM_CMP_ID` | number | 3 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 12 | `INVOICE_ID` | number | 3 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 13 | `IN_OUT_ID` | number | 3 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 14 | `IS_CANCEL` | number | 3 | Boolean? IS_ prefix. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 15 | `TO_CMP_ID` | number | 3 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 16 | `ACTION_FROM_ACCOUNT_ID` | number | 2 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 17 | `ACTION_TO_ACCOUNT_ID` | number | 2 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 18 | `BILL_NO` | number | 2 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 19 | `CARD_ROW_ID` | number | 2 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 20 | `CARI_ACTION_ID` | number | 2 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 21 | `CHEQUE_ID` | number | 2 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 22 | `CHEQUE_STATUS_ID` | number | 2 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 23 | `CHEQUE_VALUE` | number | 2 | — | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 24 | `COLLAR_TYPE` | number | 2 | Lookup/enum? Categorical olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 25 | `COST_PROFIT_CENTER` | number | 2 | — | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 26 | `GROSSTOTAL` | number | 2 | — | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 27 | `IS_CRITICAL` | number | 2 | Boolean? IS_ prefix. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 28 | `IS_PROCESSED` | number | 2 | Boolean? IS_ prefix. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 29 | `ORDER_ID` | number | 2 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 30 | `PROCESS_CAT` | number | 2 | Lookup/enum? Categorical olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 31 | `PROJECT_ID` | number | 2 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 32 | `PURCHASE_SALES` | number | 2 | — | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 33 | `SALARY` | number | 2 | — | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 34 | `SALARY_TYPE` | number | 2 | Lookup/enum? Categorical olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 35 | `SELF_CHEQUE` | number | 2 | — | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 36 | `SSK_STATUTE` | number | 2 | — | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 37 | `TAXTOTAL` | number | 2 | — | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 38 | `TOTAL_HOURS` | number | 2 | — | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 39 | `VALID` | number | 2 | — | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 40 | `ACC_BRANCH_ID` | number | 1 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 41 | `ACC_DEPARTMENT_ID` | number | 1 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 42 | `ACC_PROJECT_ID` | number | 1 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 43 | `ACTION_FROM_COMPANY_ID` | number | 1 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 44 | `ACTION_TO_COMPANY_ID` | number | 1 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 45 | `ACTIVITY_TYPE_ID` | number | 1 | ID kolonu? Identifier sınıfı olabilir. | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 46 | `AVANS` | number | 1 | — | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |
| 47 | `BA` | number | 1 | — | ☐ currency · ☐ analytical · ☐ rate · ☐ counter · ☐ identifier · ☐ boolean · ☐ other | __________ |

## Acceptance kriterleri

- 206/206 kolonda **bir** sınıf belirlenmiş
- Heuristic high-confidence (58) için DBA + backend lead **iki imza** gerekli (`approve` veya `change`)
- needs_review (148) için DBA tek imza (manuel sınıflandırma)
- `unknown_float_class` sayısı = 0 olduğunda SEAL BLOCKER kapanır

## Sign-off

```
DBA              : __________________________________________  Tarih: __________
Backend lead     : __________________________________________  Tarih: __________
```

Imzalar geldikten sonra agent SEAL flip PR'ında `_meta.float_semantic_class_signoff: true` alanını ekler.
