# Muavin Raporu (`fin-muhasebe-detay`) — UI Grid + EUR Fallback Spec

> **Status**: DRAFT (2026-05-05) — Codex thread `019df4ed-615c-73d1-b67a-7d0b61cc94df` REVISE absorbed
> **Owner**: report-service (ADR-0005 dual-datasource)
> **Annex entry**: `docs/migration/report-source-annex.yaml` → `fin-muhasebe-detay`
> **Lock state**: Spec yazıldı; **JSON template canlı 3 doğrulama sonrası kilitlenir** (bkz. §10).

---

## 1. Bağlam

Workcube ERP MSSQL üzerinde "Muhasebe Detay (Muavin) Raporu" üretimi. report-service Spring Boot, `@Qualifier("mssqlReadOnly")` üzerinden canlı veri çeker. Yeni rapor = yeni JSON template (migration yok). Standart ADR-0005 + Annex 2A pattern.

User'ın 4 onaylı kararı (2026-05-04→05):

| # | Karar |
|---|---|
| K1 | USD = `ACCOUNT_CARD_ROWS.AMOUNT_2` native (ayrı USD pool YOK) |
| K2 | Karşı hesap mantığı YOK (self-JOIN iptal) |
| K3 | BAKIYE sourceQuery içinde window function (`SUM() OVER ROWS UNBOUNDED PRECEDING`) |
| K4 | Açılış bakiyesi: ayrı sorgu YOK; "Açılış" fiş tipi normal data içinde |
| K5 | Üst filter: yalnız `OUR_COMPANY` dropdown. Tarih + diğerleri per-column header inline filter |
| K6 | B/A → ayrı sütun (Borç/Alacak/Net/Bakiye × 3 kur = 12 amount kolonu) |

---

## 2. Schema Adlandırma (canlı doğrulanmış)

```
workcube_mikrolink                       canonical (PRO_PROJECTS, COMPANY, MONEY_HISTORY,
                                                    SETUP_DOCUMENT_TYPE, OUR_COMPANY,
                                                    MONEY_TABLES, ACCOUNT_CARD_DOCUMENT_TYPES)

workcube_mikrolink_{COMPANY_ID}          şirket-only (SETUP_PROCESS_CAT, CREDIT_CARD_BANK_EXPENSE,
                                                      TAHAKKUK_PLAN — yıldan bağımsız)

workcube_mikrolink_{YEAR}_{COMPANY_ID}   yıl×şirket parametric (ACCOUNT_CARD, ACCOUNT_CARD_ROWS,
                                                                ACCOUNT_CARD_MONEY, ACCOUNT_PLAN,
                                                                12 *_MONEY pool tabloları)
```

Multi-tenant izolasyon kapısı: şirket dropdown seçimi → `{COMPANY_ID}` interpolation → ilgili schema'lara physical bind.

---

## 3. Kullanılan Tablolar (24 zorunlu + 3 opsiyonel)

### 3.1 Çekirdek (4)
| Tablo | Schema | Doğrulama | Kolon (script'ten) |
|---|---|---|---|
| `ACCOUNT_CARD` | yıl×şirket | ⏳ canlı | CARD_ID, ACTION_ID, ACTION_TYPE, ACTION_DATE, WRK_ID, CARD_DETAIL, PAPER_NO, CARD_CAT_ID, ACC_COMPANY_ID, ACC_PROJECT_ID |
| `ACCOUNT_CARD_ROWS` | yıl×şirket | ⏳ canlı | CARD_ROW_ID, CARD_ID, ACCOUNT_ID, AMOUNT (TL), AMOUNT_2 (USD), BA, DETAIL, OTHER_AMOUNT, OTHER_CURRENCY, ACC_PROJECT_ID |
| `ACCOUNT_CARD_MONEY` | yıl×şirket | ⏳ canlı | ACTION_ID, MONEY_TYPE, RATE2 (+ muhtemelen IS_SELECTED — canlı kontrol) |
| `ACCOUNT_PLAN` | yıl×şirket | ✅ snapshot 16 kolon | ACCOUNT_CODE, ACCOUNT_NAME, SUB_ACCOUNT (filter: SUB_ACCOUNT=0 + ACCOUNT_CODE BETWEEN '100' AND '900') |

### 3.2 EUR *_MONEY Pool (12 pair = 24 tablo)
12 modül, her biri `data + money` çifti. **`MONEY_TABLES`** dispatch tablosu (canonical, 60 satır) `ACTION_TYPE → ACTION_TABLE` mapping'i sağlar — keyfi priority değil, deterministic dispatch.

| # | Data tablo | Money tablo | Schema | Tie-break priority |
|---|---|---|---|---|
| 1 | INVOICE | INVOICE_MONEY | yıl×şirket | 10 |
| 2 | EXPENSE_ITEM_PLANS | EXPENSE_ITEM_PLANS_MONEY | yıl×şirket | 20 |
| 3 | STOCK_FIS | STOCK_FIS_MONEY | yıl×şirket | 30 |
| 4 | CARI_ACTIONS | CARI_ACTION_MONEY | yıl×şirket | 40 |
| 5 | CARI_ACTIONS_MULTI | CARI_ACTION_MULTI_MONEY | yıl×şirket | 45 |
| 6 | CREDIT_CONTRACT_PAYMENT_INCOME | CCPIM | yıl×şirket | 50 |
| 7 | PAYROLL | PAYROLL_MONEY | yıl×şirket | 60 |
| 8 | BANK_ACTIONS_MULTI | BANK_ACTION_MULTI_MONEY | yıl×şirket | 70 |
| 9 | BANK_ACTIONS | BANK_ACTION_MONEY | yıl×şirket | 80 |
| 10 | CASH_ACTIONS | CASH_ACTION_MONEY | yıl×şirket | 90 |
| 11 | CREDIT_CARD_BANK_EXPENSE | CCBE_MONEY | şirket-only | 100 |
| 12 | TAHAKKUK_PLAN | TAHAKKUK_PLAN_MONEY | şirket-only | 110 |

### 3.3 Lookup / Boyut (5)
| Tablo | Schema | Snapshot |
|---|---|---|
| `SETUP_PROCESS_CAT` | şirket-only | ⏳ canlı (PROCESS_CAT_ID → text) |
| `SETUP_DOCUMENT_TYPE` | canonical | ✅ 9 kolon (Mahsup/Tahsil/Tediye + Açılış lookup) |
| `ACCOUNT_CARD_DOCUMENT_TYPES` | canonical | ⏳ canlı (Açılış fişi şirket-bazlı custom isim için yedek lookup) |
| `PRO_PROJECTS` | canonical | ✅ 75 kolon (PROJECT_ID → PROJECT_HEAD) |
| `COMPANY` | canonical | ✅ 113 kolon (COMPANY_ID → FULLNAME, cari) |
| `MONEY_HISTORY` | canonical | ✅ 19 kolon (RATE1, RATE2, RATE3, RATEPP2/3, RATEWW2/3, EFFECTIVE_*, MONEY, VALIDATE_DATE, COMPANY_ID, PERIOD_ID, MONEY_HISTORY_ID(PK identity), RECORD_DATE) |
| `MONEY_TABLES` | canonical | ✅ 3 kolon (MT_ID, ACTION_TYPE, ACTION_TABLE) — POOL dispatch |

### 3.4 Filter (1)
| Tablo | Rol |
|---|---|
| `OUR_COMPANY` | Üst filter dropdown (COMP_ID + COMPANY_NAME + TAX_NO) |

### 3.5 Opsiyonel / V2
- `NEW_MONEY_HISTORY` — staging/delta overlay (981 row vs MONEY_HISTORY 180,995). v1'de **dahil edilmiyor**, v2 canlı owner doğrulamasında karar.
- `FOREKS_MerkezBankasiDoviz` — snapshot rowCount 0; canlıda dolu ise L7 fallback.
- `FOREKS_DovizParite` — snapshot rowCount 0; cross-rate L8 fallback (USD→EUR).

---

## 4. Grid Sütunları (26 görünür + 6 hidden audit)

### 4.1 Sabit Boyut (12)
| # | Başlık | Kaynak |
|---|---|---|
| 1 | Hesap Kodu | `ACCOUNT_PLAN.ACCOUNT_CODE` |
| 2 | Hesap Adı | `ACCOUNT_PLAN.ACCOUNT_NAME` |
| 3 | Tarih | `ACCOUNT_CARD.ACTION_DATE` (per-column date range filter) |
| 4 | Fiş No | `ACCOUNT_CARD.CARD_ID` |
| 5 | Fiş Tipi | `SETUP_DOCUMENT_TYPE.DOCUMENT_TYPE_NAME` (fallback `ACCOUNT_CARD_DOCUMENT_TYPES`) |
| 6 | Belge No | `ACCOUNT_CARD.PAPER_NO` |
| 7 | Süreç Kategorisi | `SETUP_PROCESS_CAT.PROCESS_CAT` |
| 8 | Açıklama | `ACCOUNT_CARD_ROWS.DETAIL` |
| 9 | Kart Açıklama | `ACCOUNT_CARD.CARD_DETAIL` |
| 10 | Cari | `COMPANY.FULLNAME` |
| 11 | Proje | `PRO_PROJECTS.PROJECT_HEAD` |
| 12 | WRK_ID | `ACCOUNT_CARD.WRK_ID` |

### 4.2 🟦 TL (4)
| # | Başlık | Hesap |
|---|---|---|
| 13 | Borç (TL) | `CASE WHEN BA='B' THEN AMOUNT ELSE 0 END` |
| 14 | Alacak (TL) | `CASE WHEN BA='A' THEN AMOUNT ELSE 0 END` |
| 15 | Net Tutar (TL) | `AMOUNT × (BA='B' ? +1 : -1)` |
| 16 | Bakiye (TL) | `SUM(NET_TL) OVER (PARTITION BY ACCOUNT_CODE ORDER BY ACTION_DATE, CARD_ID, CARD_ROW_ID ROWS UNBOUNDED PRECEDING)` |

### 4.3 🟩 USD (4)
| # | Başlık | Hesap |
|---|---|---|
| 17 | Borç (USD) | `CASE WHEN BA='B' THEN AMOUNT_2 ELSE 0 END` |
| 18 | Alacak (USD) | `CASE WHEN BA='A' THEN AMOUNT_2 ELSE 0 END` |
| 19 | Net Tutar (USD) | `AMOUNT_2 × signed` |
| 20 | Bakiye (USD) | window over NET_USD |

### 4.4 🟪 EUR (5)
| # | Başlık | Hesap |
|---|---|---|
| 21 | EUR Kuru | 8-katman fallback (§5) |
| 22 | Borç (EUR) | `CASE WHEN BA='B' THEN AMOUNT/EUR_KUR ELSE 0 END` |
| 23 | Alacak (EUR) | `CASE WHEN BA='A' THEN AMOUNT/EUR_KUR ELSE 0 END` |
| 24 | Net Tutar (EUR) | `(AMOUNT/EUR_KUR) × signed` |
| 25 | Bakiye (EUR) | window over NET_EUR |

### 4.5 Audit (1 görünür)
| # | Başlık | İçerik |
|---|---|---|
| 26 | Kur Kaynağı | §6 enum (ACM/POOL/MH/FOREKS/PARITY/MISSING) |

### 4.6 Hidden / Export-only Audit (6)
- `kur_tarihi` — efektif kurun valid tarihi
- `kur_kolonu` — RATE1/RATE2/RATEPP2 vs (hangi rate kolonu)
- `kur_id` — MONEY_HISTORY_ID veya equivalent
- `kur_yas_gun` — fişten ne kadar uzak (0 = same-day, N = N gün önce)
- `kur_cakisma` — birden fazla katman non-null ise true (audit warning)
- `eur_rate_layer` — L1..L8 hangi katman çalıştı

---

## 5. EUR Kuru — 8-Katman Fallback (Codex absorb)

```
L1  ACCOUNT_CARD_MONEY (fiş-level manuel override)
    JOIN: ACM.ACTION_ID = AC.CARD_ID  ⏳ canlı doğrulama gerek (alternatif: ACM.ACTION_ID = AC.ACTION_ID)
    FILTER: MONEY_TYPE='EUR'
    RATE: RATE2
    TIE-BREAK: ORDER BY (varsa IS_SELECTED DESC,) ACTION_ID
    RATIONALE: Muhasebecinin manuel override'ı en otoriter (Codex L1 swap)

L2  POOL — 12 *_MONEY UNION ALL
    JOIN: AM.ACTION_ID = AC.ACTION_ID AND AM.PROCESS_TYPE = AC.ACTION_TYPE
    FILTER: MONEY_TYPE='EUR'
    DISPATCH: MONEY_TABLES(ACTION_TYPE → ACTION_TABLE) exact match (Codex)
    RATE: RATE2
    TIE-BREAK: ACTION_TABLE exact → IS_SELECTED DESC → MONEY_ROW_ID DESC → SOURCE_PRIORITY
    RATIONALE: Kaynak modülün kayıt-anı kuru

L3  MONEY_HISTORY same-day, COMPANY_ID = :OUR_COMPANY_ID
    FILTER: MONEY='EUR' AND VALIDATE_DATE = AC.ACTION_DATE AND COMPANY_ID = :c
    RATE: RATE1 (TCMB resmi — Codex; RATEPP2 kullanma)
    ORDER: VALIDATE_DATE DESC, RECORD_DATE DESC, MONEY_HISTORY_ID DESC
    LIMIT 1

L4  MONEY_HISTORY same-day GLOBAL (COMPANY_ID null veya 0)
    FILTER: MONEY='EUR' AND VALIDATE_DATE = AC.ACTION_DATE AND COMPANY_ID IS NULL
    RATE: RATE1
    ORDER: aynı tie-break
    RATIONALE: Aynı gün global > prev-day company (Codex sıra fix)

L5  MONEY_HISTORY ≤7 gün önce, COMPANY_ID matched
    FILTER: MONEY='EUR' AND VALIDATE_DATE BETWEEN AC.ACTION_DATE - 7 AND AC.ACTION_DATE - 1
            AND COMPANY_ID = :c
    RATE: RATE1
    ORDER: VALIDATE_DATE DESC, ...
    LIMIT 1
    AUDIT: kur_yas_gun = DATEDIFF(day, MH.VALIDATE_DATE, AC.ACTION_DATE)

L6  MONEY_HISTORY ≤7 gün önce, GLOBAL
    Aynı L5, COMPANY_ID IS NULL

L7  FOREKS_MerkezBankasiDoviz (opsiyonel, canlıda dolu ise)
    FILTER: strSembol='EUR' AND dtmTarih = AC.ACTION_DATE
    RATE: dblAlis (TCMB satış? — canlı doğrulama gerek)
    NOT: snapshot rowCount 0; v1'de aktif değil

L8  Cross-rate USD→EUR (son çare)
    KOŞUL: AMOUNT_2 ≠ 0 (USD native dolu)
    SOURCE: FOREKS_DovizParite veya hesaplanmış USDTRY/EURTRY
    FORMULA: EUR = AMOUNT_2 × (USDTRY / EURTRY)
    NOT: snapshot rowCount 0; canlıda parite yönü doğrulanmadan ETKİN DEĞİL

NULL FINAL → kur_kaynak = 'MISSING|EUR_RATE_NOT_FOUND'
            UI hücre: "—"
            Footer toplamına dahil DEĞİL
            EUR_KUR / Borç_EUR / Alacak_EUR / Net_EUR / Bakiye_EUR = NULL
```

---

## 6. `Kur Kaynağı` Audit Enum (Codex önerisi)

Pipe-delimited, structured. UI'da kompakt, export'ta tam.

```text
ACM|EUR|RATE2|CARD_ID:{card_id}|MID:{money_row_id}
POOL|{source_table}|EUR|RATE2|ACTION_TYPE:{type}|ACTION_ID:{aid}|MID:{mid}
MH|COMPANY|RATE1|SAME_DAY|DATE:{rate_date}|MID:{id}
MH|GLOBAL|RATE1|SAME_DAY|DATE:{rate_date}|MID:{id}
MH|COMPANY|RATE1|PREV_DAY|DATE:{rate_date}|AGE:{n}|MID:{id}
MH|GLOBAL|RATE1|PREV_DAY|DATE:{rate_date}|AGE:{n}|MID:{id}
FOREKS|TCMB_ALIS|DATE:{rate_date}|AGE:{n}
PARITY|USD_TO_EUR|DATE:{rate_date}|FORMULA:{code}
MISSING|EUR_RATE_NOT_FOUND
```

---

## 7. Filter Şeması

| Yer | Eleman | Tip | Zorunlu |
|---|---|---|---|
| **Üst sticky** | OUR_COMPANY_ID | dropdown (OUR_COMPANY.COMP_ID + COMPANY_NAME) | ✅ Evet |
| Header inline | Tarih | date range | ⏸ |
| Header inline | Hesap Kodu | text range/like | ⏸ |
| Header inline | Fiş Tipi | dropdown (SETUP_DOCUMENT_TYPE) | ⏸ |
| Header inline | Süreç Kategorisi | dropdown | ⏸ |
| Header inline | Cari | LIKE | ⏸ |
| Header inline | Proje | LIKE | ⏸ |
| Gelişmiş panel (collapse) | Şube/Departman/Personel/Para Birimi | opsiyonel boyut | ⏸ |

---

## 8. Performans (Codex önerisi)

- Yıllar **server-side UNION ALL** per-year (Spring Boot client-side iterasyon YOK; yıl sınırında bakiye bozulur).
- Tek outer query'de `SUM() OVER ...` window function.
- Index önerisi (canlı uygulama, MSSQL admin):
  - `ACCOUNT_CARD(ACTION_DATE, CARD_ID) INCLUDE (ACTION_ID, ACTION_TYPE, PAPER_NO, CARD_CAT_ID, ACC_PROJECT_ID, CARD_DETAIL)`
  - `ACCOUNT_CARD_ROWS(CARD_ID, ACCOUNT_ID, CARD_ROW_ID) INCLUDE (AMOUNT, AMOUNT_2, BA, DETAIL, OTHER_AMOUNT, OTHER_CURRENCY)`
  - 12 *_MONEY pool: `(ACTION_ID, MONEY_TYPE) INCLUDE (RATE2, PROCESS_TYPE, IS_SELECTED?)`
  - `MONEY_HISTORY(MONEY, COMPANY_ID, VALIDATE_DATE DESC, MONEY_HISTORY_ID DESC) INCLUDE (RATE1, PERIOD_ID, RECORD_DATE)`
  - Global fallback için: `MONEY_HISTORY(MONEY, VALIDATE_DATE DESC, MONEY_HISTORY_ID DESC)`
- Decimal cast: `MONEY_HISTORY.RATE1` float → `decimal(18,6)` cast (binary float toplam artefact engellemek)
- Materialized view v1 YOK (ADR-0005 live data zorunluluğu).

---

## 9. Pre-Range Carry-Forward (açık karar)

Kullanıcı kararı K4: "Açılış bakiyesi fiş türünde var, yerleşik". Fakat:

- **Senaryo A**: Tüm geçmişi raporda göster → `ROWS UNBOUNDED PRECEDING` doğru çalışır, açılış fişi data içinde.
- **Senaryo B**: Tarih filtresi uygulanırsa (örn. sadece 2026 yılı) → filtre öncesi kayıtlar window dışında kalır, bakiye filtreden başlar (yanlış kümülatif).

**Çözüm seçenekleri:**
1. Filter SQL'e push edilmesin, UI tarafında client-side filter (büyük data riski)
2. Pre-range carry-forward subquery: `WHERE ACTION_DATE < :date_from` özet, opening balance olarak ilk satıra ekle
3. UI'da "Bu rapor kümülatif başlangıçtan gösterir; tarih filtresi sadece görünüm filtresi" uyarı

→ **Default: Seçenek 3** (en az karmaşık), Seçenek 2 v2'de değerlendirilir.

---

## 10. Live Validation Gate (`ready_for_impl: false`)

Codex önerdiği 3 canlı doğrulama yapılmadan **JSON template kilitlenmemeli**:

### 10.1 ACCOUNT_CARD_MONEY join key
```sql
-- Hangi join doğru?
SELECT 'ACTION_ID=CARD_ID' AS variant, COUNT(*) AS matched
FROM workcube_mikrolink_2026_{COMPANY_ID}.ACCOUNT_CARD AC
INNER JOIN workcube_mikrolink_2026_{COMPANY_ID}.ACCOUNT_CARD_MONEY ACM
  ON ACM.ACTION_ID = AC.CARD_ID
WHERE ACM.MONEY_TYPE='EUR'
UNION ALL
SELECT 'ACTION_ID=ACTION_ID', COUNT(*)
FROM workcube_mikrolink_2026_{COMPANY_ID}.ACCOUNT_CARD AC
INNER JOIN workcube_mikrolink_2026_{COMPANY_ID}.ACCOUNT_CARD_MONEY ACM
  ON ACM.ACTION_ID = AC.ACTION_ID
WHERE ACM.MONEY_TYPE='EUR';
```
Beklenen: birinin matched sayısı belirgin yüksek olmalı.

### 10.2 MONEY_TABLES dispatch row values
```sql
SELECT MT_ID, ACTION_TYPE, ACTION_TABLE
FROM workcube_mikrolink.MONEY_TABLES
ORDER BY ACTION_TYPE;
```
Beklenen: 60 satır, ACTION_TYPE → table name deterministic mapping.

### 10.3 RATE1 vs FOREKS sample doğrulama
```sql
SELECT TOP 30 MH.VALIDATE_DATE, MH.MONEY,
              MH.RATE1   AS MH_RATE1,
              MH.RATE2   AS MH_RATE2,
              MH.RATEPP2 AS MH_RATEPP2,
              F.dblAlis  AS FOREKS_ALIS,
              F.dblSatis AS FOREKS_SATIS
FROM workcube_mikrolink.MONEY_HISTORY MH
LEFT JOIN workcube_mikrolink.FOREKS_MerkezBankasiDoviz F
  ON F.dtmTarih = MH.VALIDATE_DATE AND F.strSembol = MH.MONEY
WHERE MH.MONEY IN ('EUR','USD') AND MH.VALIDATE_DATE >= '2026-01-01'
ORDER BY MH.VALIDATE_DATE DESC;
```
Beklenen: hangi rate kolonu FOREKS ile uyumlu?

---

## 11. Sonraki Adımlar

| # | Adım | Sahip | Durum |
|---|---|---|---|
| 1 | Spec doc yazıldı | platform-team | ✅ Bu dosya |
| 2 | 3 canlı doğrulama | user / Workcube admin | ⏸ pending |
| 3 | JSON template (`fin-muhasebe-detay.json`) | platform-backend repo | ⏸ pending (validation gate) |
| 4 | Annex update (`manually_validated: true`) | this repo | ⏸ pending (post-validation) |
| 5 | MSSQL credential rotation (Vault) | user/operator | ⏸ pending (script chat'te şifre paylaşımı) |
| 6 | Index önerileri Workcube admin'e | user | ⏸ pending |

---

## 12. Referanslar

- Codex thread: `019df4ed-615c-73d1-b67a-7d0b61cc94df` (REVISE verdict)
- ADR-0005 dual-datasource reporting
- Annex 2A: `docs/migration/report-source-annex.yaml`
- Schema snapshot: `docs/migration/workcube-schema.json` (1509 tablo, 2026-04-25)
- Data contract: `docs/migration/mssql-pg-data-contract.md`
- DDL review: `docs/migration/v16-ddl-review.md`
- User session: 2026-05-04→05 muavin grid spec konuşması
