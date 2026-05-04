# Muavin Raporu (`fin-muhasebe-detay`) — UI Grid + EUR Fallback Spec

> **Status**: VALIDATED (2026-05-05) — Codex thread `019df4ed` iter-2 absorbed + canlı 5 doğrulama tamamlandı (workcube_mikrolink prod, COMPANY_ID=35 sample)
> **Owner**: report-service (ADR-0005 dual-datasource)
> **Annex entry**: `docs/migration/report-source-annex.yaml` → `fin-muhasebe-detay` (manually_validated → true after JSON template lock)
> **Lock state**: Spec final; **JSON template SQL skeleton hazır** (§7), 2 küçük canlı doğrulama eksik (Codex iter-2 §10.b — son `BANK_ORDER_MONEY` schema teyidi yapıldı; `ACTION_TABLE` consistency yapıldı). Implementation ready.

---

## 1. Bağlam

Workcube ERP MSSQL üzerinde "Muhasebe Detay (Muavin) Raporu" üretimi. report-service Spring Boot, `@Qualifier("mssqlReadOnly")` üzerinden canlı veri çeker. Yeni rapor = yeni JSON template (migration yok). Standart ADR-0005 + Annex 2A pattern.

User'ın 6 onaylı kararı (2026-05-04→05):

| # | Karar |
|---|---|
| K1 | USD = `ACCOUNT_CARD_ROWS` üzerinde **dinamik currency** (canlı düzeltme: AMOUNT_2 USD-native değil, AMOUNT_CURRENCY_2 ile şart) |
| K2 | Karşı hesap mantığı YOK (self-JOIN iptal) |
| K3 | BAKIYE sourceQuery içinde window function (`SUM() OVER ROWS UNBOUNDED PRECEDING`) |
| K4 | Açılış bakiyesi: ayrı sorgu YOK; "Açılış" fiş tipi normal data içinde (lookup `ACCOUNT_CARD_DOCUMENT_TYPES`) |
| K5 | Üst filter: yalnız `OUR_COMPANY` dropdown. Tarih + diğerleri per-column header inline filter |
| K6 | B/A → ayrı sütun: Borç + Alacak + Net + Bakiye × 3 kur |

---

## 2. Schema Adlandırma (canlı doğrulanmış)

```
workcube_mikrolink                        canonical (PRO_PROJECTS, COMPANY, MONEY_HISTORY,
                                                     SETUP_DOCUMENT_TYPE, OUR_COMPANY,
                                                     MONEY_TABLES, ACCOUNT_CARD_DOCUMENT_TYPES)

workcube_mikrolink_{COMPANY_ID}           şirket-only (CREDIT_CARD_BANK_EXPENSE,
                                                       TAHAKKUK_PLAN, SETUP_PROCESS_CAT)

workcube_mikrolink_{YEAR}_{COMPANY_ID}    yıl×şirket parametric (ACCOUNT_CARD, ACCOUNT_CARD_ROWS,
                                                                 ACCOUNT_CARD_MONEY, ACCOUNT_PLAN,
                                                                 13 *_MONEY pool tabloları)
```

Multi-tenant izolasyon kapısı: şirket dropdown seçimi → `{COMPANY_ID}` interpolation → ilgili schema'lara physical bind.

**Canlı doğrulama (2026-05-05, COMPANY_ID=35 = "Serban İnşaat San. ve Tic. A.Ş."):**
- `workcube_mikrolink_2026_35`, `_2025_35`, `_2024_35`, `_2023_35` mevcut ✅
- `workcube_mikrolink_35` (şirket-only) mevcut ✅
- Canonical 10 tablo `workcube_mikrolink` schema'sında doğrulandı ✅

---

## 3. Kullanılan Tablolar (26 zorunlu + opsiyonel)

### 3.1 Çekirdek (4) — `workcube_mikrolink_{Y}_{C}`

| Tablo | Doğrulama | Önemli kolonlar (canlı) |
|---|---|---|
| **ACCOUNT_CARD** (37 kolon) | ✅ canlı | CARD_ID(PK), ACTION_ID, ACTION_TYPE, **ACTION_TABLE** (nvarchar 50 — %99 NULL!), ACTION_DATE, WRK_ID, CARD_DETAIL, PAPER_NO, CARD_CAT_ID, **CARD_DOCUMENT_TYPE**, ACC_COMPANY_ID, ACC_CONSUMER_ID, ACC_EMPLOYEE_ID, **PROJECT_ID** (script `ACC_PROJECT_ID` yanlış!), IS_RATE_DIFF, IS_OTHER_CURRENCY, **IS_CANCEL** |
| **ACCOUNT_CARD_ROWS** (33 kolon) | ✅ canlı | CARD_ID, CARD_ROW_ID, **ACCOUNT_ID** (nvarchar 100 — text!), **BA** (bit 1=Borç 0=Alacak), AMOUNT (float), **AMOUNT_CURRENCY** (nvarchar 43), AMOUNT_2, **AMOUNT_CURRENCY_2** (nvarchar 43), DETAIL, OTHER_AMOUNT, OTHER_CURRENCY, IFRS_CODE, ACCOUNT_CODE2, ACC_PROJECT_ID, ACC_DEPARTMENT_ID, ACC_BRANCH_ID |
| **ACCOUNT_CARD_MONEY** (6 kolon) | ✅ canlı | MONEY_TYPE, ACTION_ID, RATE2, RATE1, **IS_SELECTED** (bit), ACTION_MONEY_ID(PK identity) |
| **ACCOUNT_PLAN** (16 kolon) | ✅ snapshot+canlı | ACCOUNT_CODE, ACCOUNT_NAME, SUB_ACCOUNT (filter: SUB_ACCOUNT=0 + ACCOUNT_CODE BETWEEN '100' AND '900') |

### 3.2 EUR *_MONEY Pool (13 tablo, +1 yeni!)

`MONEY_TABLES` (canonical, **60 satır deterministic 1:1 dispatch**) → ACTION_TYPE → ACTION_TABLE eşlemesi:

| ACTION_TYPE | ACTION_TABLE | Schema |
|---|---|---|
| 13 | ACCOUNT_CARD_MONEY (özel, muavin'in kendi) | yıl×şirket |
| 24-27 | BANK_ACTION_MONEY | yıl×şirket |
| 31-35 | CASH_ACTION_MONEY | yıl×şirket |
| 40-46, 131 | CARI_ACTION_MONEY | yıl×şirket |
| 48-68, 531-691 | INVOICE_MONEY | yıl×şirket |
| 90-108 | PAYROLL_MONEY | yıl×şirket |
| 120-121 | EXPENSE_ITEM_PLANS_MONEY | yıl×şirket |
| 241-245 | CREDIT_CONTRACT_PAYMENT_INCOME_MONEY | yıl×şirket |
| **250-251** | **BANK_ORDER_MONEY** ← script'te yoktu, canlı keşif | yıl×şirket |
| (CARI_ACTIONS_MULTI alt-tip) | CARI_ACTION_MULTI_MONEY | yıl×şirket |
| (BANK_ACTIONS_MULTI alt-tip) | BANK_ACTION_MULTI_MONEY | yıl×şirket |
| (CCBE alt-tip) | CREDIT_CARD_BANK_EXPENSE_MONEY | **şirket-only** |
| (TAHAKKUK alt-tip) | TAHAKKUK_PLAN_MONEY | **şirket-only** |

**Pool tablo schema (canlı doğrulanmış, BANK_ORDER_MONEY üzerinden):** her tablo aynı 6 kolon → MONEY_TYPE, ACTION_ID, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID.

**Out-of-pool ACTION_TYPE'lar** (örn. 130 EMPLOYEES_PUANTAJ, 161): MONEY_TABLES'da yok → MONEY_HISTORY fallback'a düşer (L4+).

### 3.3 Lookup / Boyut (6)

| Tablo | Schema | Doğrulama | Rol |
|---|---|---|---|
| **MONEY_TABLES** | canonical | ✅ 60 satır canlı | POOL deterministic dispatch (ACTION_TYPE → ACTION_TABLE) |
| **ACCOUNT_CARD_DOCUMENT_TYPES** | canonical | ✅ 13 kolon canlı | **Açılış fişi şirket-bazlı lookup** (PRIMARY) |
| **SETUP_DOCUMENT_TYPE** | canonical (9 kolon) | ✅ snapshot | Generic doc type fallback (Açılış için **PRIMARY DEĞİL** — canlıda 0 'Açılış' satırı) |
| **PRO_PROJECTS** | canonical (75 kolon) | ✅ | Proje adı lookup |
| **COMPANY** | canonical (113 kolon) | ✅ | Cari (müşteri/tedarikçi) lookup |
| **MONEY_HISTORY** | canonical (19 kolon) | ✅ canlı (181,436 satır) | EUR/USD kur tarihi (RATE2 = alış, RATE3 = satış); RATE1 dummy=1.0 (TCMB DEĞİL!) |

### 3.4 Filter (1)

| Tablo | Rol |
|---|---|
| **OUR_COMPANY** | Üst filter dropdown — **tek zorunlu** (COMP_ID + COMPANY_NAME + TAX_NO) |

### 3.5 ❌ v1'de KULLANILMIYOR

- `NEW_MONEY_HISTORY` (981 satır, %99.7 MONEY_HISTORY subset → staging/delta overlay; v2 candidate)
- `FOREKS_MerkezBankasiDoviz` (canlıda boş — sample'da NULL döndü)
- `FOREKS_DovizParite` (snapshot rowCount 0)
- `BRANCH`, `DEPARTMENT`, `EMPLOYEES`, `CONSUMER`, `SETUP_PROCESS_CAT` — opsiyonel boyut, ileride eklenebilir

---

## 4. Grid Sütunları (26 görünür + 6 hidden audit)

### 4.1 Sabit Boyut (12)

| # | Başlık | SQL kaynak |
|---|---|---|
| 1 | Hesap Kodu | `ap.ACCOUNT_CODE` (LTRIM/RTRIM `acr.ACCOUNT_ID = ap.ACCOUNT_CODE`) |
| 2 | Hesap Adı | `ap.ACCOUNT_NAME` |
| 3 | Tarih | `ac.ACTION_DATE` (per-column date range filter) |
| 4 | Fiş No | `ac.CARD_ID` |
| 5 | Fiş Tipi | `acdt.DOCUMENT_TYPE` (ACCOUNT_CARD_DOCUMENT_TYPES; SETUP_DOCUMENT_TYPE fallback) |
| 6 | Belge No | `ac.PAPER_NO` |
| 7 | Süreç Kategorisi | `spc.PROCESS_CAT` (workcube_mikrolink_{COMPANY_ID}.SETUP_PROCESS_CAT) |
| 8 | Açıklama | `acr.DETAIL` |
| 9 | Kart Açıklama | `ac.CARD_DETAIL` |
| 10 | Cari | `c.FULLNAME` (workcube_mikrolink.COMPANY) |
| 11 | Proje | `p.PROJECT_HEAD` (workcube_mikrolink.PRO_PROJECTS) |
| 12 | WRK_ID | `ac.WRK_ID` |

### 4.2 🟦 TL (4)

| # | Başlık | SQL |
|---|---|---|
| 13 | Borç (TL) | `CASE WHEN BA=1 AND tl_native_amount IS NOT NULL THEN tl_native_amount END` |
| 14 | Alacak (TL) | `CASE WHEN BA=0 AND tl_native_amount IS NOT NULL THEN tl_native_amount END` |
| 15 | Net Tutar (TL) | `tl_native_amount × (BA=1 ? +1 : -1)` |
| 16 | Bakiye (TL) | `SUM(net_tl) OVER (PARTITION BY account_code ORDER BY ACTION_DATE, CARD_ID, CARD_ROW_ID ROWS UNBOUNDED PRECEDING)` |

`tl_native_amount = CASE WHEN amount_currency IN ('TL','TRY') OR amount_currency IS NULL THEN AMOUNT END`

### 4.3 🟩 USD (4) — REVIZE: dinamik currency

| # | Başlık | SQL |
|---|---|---|
| 17 | Borç (USD) | `CASE WHEN BA=1 AND usd_native_amount IS NOT NULL THEN usd_native_amount END` |
| 18 | Alacak (USD) | `CASE WHEN BA=0 AND usd_native_amount IS NOT NULL THEN usd_native_amount END` |
| 19 | Net Tutar (USD) | `usd_native_amount × signed` |
| 20 | Bakiye (USD) | window over `net_usd` |

`usd_native_amount = CASE WHEN AMOUNT_CURRENCY='USD' THEN AMOUNT WHEN AMOUNT_CURRENCY_2='USD' THEN AMOUNT_2 ELSE NULL END`

→ User'ın "USD = AMOUNT_2 native" tezi düzeltildi: AMOUNT_2 dinamik 2. currency. Sadece explicit USD satırları doldurulur, gerisi NULL (footer toplam exclude). v1'de implicit conversion **yok**.

### 4.4 🟪 EUR (5) — 8-katman fallback

| # | Başlık | SQL |
|---|---|---|
| 21 | EUR Kuru | OUTER APPLY 8-layer waterfall (§5) |
| 22 | Borç (EUR) | `CASE WHEN BA=1 THEN eur_amount END` |
| 23 | Alacak (EUR) | `CASE WHEN BA=0 THEN eur_amount END` |
| 24 | Net Tutar (EUR) | `eur_amount × signed` |
| 25 | Bakiye (EUR) | window |

```sql
eur_amount = CASE
  WHEN AMOUNT_CURRENCY='EUR' THEN AMOUNT
  WHEN AMOUNT_CURRENCY_2='EUR' THEN AMOUNT_2
  WHEN tl_native_amount IS NOT NULL AND eur_rate IS NOT NULL THEN tl_native_amount / eur_rate
  ELSE NULL
END
```

### 4.5 Audit (1 görünür)

| # | Başlık | İçerik |
|---|---|---|
| 26 | Kur Kaynağı | §6 enum (ACM_CARD/ACM_ACTION/POOL/MH_*/MISSING) |

### 4.6 Hidden / Export-only Audit (6)

- `kur_tarihi` — efektif kur tarih
- `kur_kolonu` — RATE2 (default) veya RATE3 / RATEPP2
- `kur_id` — MONEY_HISTORY_ID veya ACTION_MONEY_ID
- `kur_yas_gun` — fiş tarihten kur tarihe gün farkı (0 = same-day)
- `kur_cakisma` — birden fazla layer non-null ise true (audit warning)
- `is_opening_document` — açılış fişi flag (ACCOUNT_CARD_DOCUMENT_TYPES.DOCUMENT_TYPE LIKE '%çılış%')

---

## 5. EUR Kuru — 8-Katman Fallback (Codex iter-2 absorb + canlı doğrulama)

```
L1  ACCOUNT_CARD_MONEY by CARD_ID (fiş-level manuel override)
    JOIN: ACM.ACTION_ID = AC.CARD_ID
    FILTER: MONEY_TYPE='EUR'
    RATE: RATE2 (RATE1 dummy 1.0 — KULLANMA!)
    TIE-BREAK: ORDER BY IS_SELECTED DESC, ACTION_MONEY_ID DESC
    CANLı KANIT: 552 satır match (V1)

L2  ACCOUNT_CARD_MONEY by source ACTION_ID
    JOIN: ACM.ACTION_ID = AC.ACTION_ID
    Aynı filter+rate+tie-break
    CANLı KANIT: 512 satır match (%92.7 overlap, gerçek fallback)

L3  POOL exact ACTION_TABLE + ACTION_ID
    PREFER: AC.ACTION_TABLE not null AND non-empty (canlıda %1 — sadece 199/20367 row)
    JOIN: pool.action_table = AC.ACTION_TABLE AND pool.ACTION_ID = AC.ACTION_ID
    FILTER: MONEY_TYPE='EUR'
    RATE: RATE2

L4  POOL fallback by MONEY_TABLES dispatch
    PRIMARY (çoğu zaman): MONEY_TABLES.ACTION_TYPE = AC.ACTION_TYPE → derive action_table
    JOIN: pool.action_table = mt.ACTION_TABLE AND pool.ACTION_ID = AC.ACTION_ID
    FILTER: MONEY_TYPE='EUR'
    RATE: RATE2
    NOT: 60-row deterministic 1:1 mapping; ACTION_TYPE listede yoksa skip

L5  MONEY_HISTORY same-day, COMPANY_ID matched
    FILTER: MONEY='EUR' AND VALIDATE_DATE = AC.ACTION_DATE AND COMPANY_ID = :c
    RATE: RATE2 (RATEPP2 same value, but RATE2 semantic-correct)
    ORDER: VALIDATE_DATE DESC, RECORD_DATE DESC, MONEY_HISTORY_ID DESC

L6  MONEY_HISTORY same-day GLOBAL (COMPANY_ID NULL)
    Codex haklı: same-day global > prev-day company

L7  MONEY_HISTORY ≤7 gün önce, COMPANY_ID matched
    LIMIT 1 ORDER BY VALIDATE_DATE DESC
    AUDIT: kur_yas_gun

L8  MONEY_HISTORY ≤7 gün önce, GLOBAL

NULL FINAL → kur_kaynak = 'MISSING|EUR_RATE_NOT_FOUND'
            UI hücre: "—"
            Footer toplamına dahil DEĞİL
```

**FOREKS layer ÇIKARILDI** — canlıda boş (V3 sample NULL), v2 candidate.

**Cross-rate (USD→EUR) layer ÇIKARILDI** — Codex tezi: muavin'de implicit conversion audit'i bulanıklaştırır. v2 candidate.

---

## 6. `Kur Kaynağı` Audit Enum (Codex absorb)

Pipe-delimited, structured. UI'da kompakt, export'ta tam.

```text
ACM|CARD_ID|RATE2|MID:{action_money_id}
ACM|ACTION_ID|RATE2|MID:{action_money_id}
POOL|{action_table}|RATE2|MID:{money_row_id}
MH|COMPANY|SAME_DAY|RATE2|DATE:{rate_date}|MID:{id}
MH|GLOBAL|SAME_DAY|RATE2|DATE:{rate_date}|MID:{id}
MH|COMPANY|PREV_DAY|RATE2|DATE:{rate_date}|AGE:{n}|MID:{id}
MH|GLOBAL|PREV_DAY|RATE2|DATE:{rate_date}|AGE:{n}|MID:{id}
MISSING|EUR_RATE_NOT_FOUND
```

---

## 7. SQL Skeleton (Codex iter-2)

`fin-muhasebe-detay.json` template `sourceQuery` field'i için tam SQL:

```sql
-- {schema} = workcube_mikrolink_{YEAR}_{COMPANY_ID}
-- :company_id = OUR_COMPANY_ID parameter
-- :date_from / :date_to = optional date range (per-column inline filter ile UI'dan gelir)
-- :account_from / :account_to = optional account code range

WITH ac AS (
  SELECT
    CARD_ID, ACTION_ID, ACTION_TYPE, ACTION_TABLE, ACTION_DATE,
    PAPER_NO, CARD_DETAIL, CARD_DOCUMENT_TYPE, CARD_CAT_ID,
    ACC_COMPANY_ID, ACC_CONSUMER_ID, ACC_EMPLOYEE_ID,
    PROJECT_ID, IS_CANCEL, IS_RATE_DIFF, WRK_ID
  FROM {schema}.ACCOUNT_CARD
  WHERE ACTION_DATE >= :date_from
    AND ACTION_DATE < DATEADD(day, 1, :date_to)
    AND ISNULL(IS_CANCEL, 0) = 0
),
rows AS (
  SELECT
    CARD_ROW_ID, CARD_ID,
    LTRIM(RTRIM(ACCOUNT_ID)) AS account_code,
    AMOUNT, AMOUNT_CURRENCY,
    AMOUNT_2, AMOUNT_CURRENCY_2,
    BA,
    CASE WHEN BA = 1 THEN 'B' ELSE 'A' END AS ba_code,
    DETAIL, OTHER_AMOUNT, OTHER_CURRENCY,
    ACC_PROJECT_ID, ACC_DEPARTMENT_ID, ACC_BRANCH_ID,
    IFRS_CODE, ACCOUNT_CODE2
  FROM {schema}.ACCOUNT_CARD_ROWS
),
pool AS (
  -- 13 *_MONEY pool (canlı 60-row MONEY_TABLES dispatch + 3 sub-type)
  SELECT 'INVOICE_MONEY' AS action_table, ACTION_ID, MONEY_TYPE, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID AS money_row_id
    FROM {schema}.INVOICE_MONEY WHERE MONEY_TYPE = 'EUR'
  UNION ALL
  SELECT 'EXPENSE_ITEM_PLANS_MONEY', ACTION_ID, MONEY_TYPE, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID
    FROM {schema}.EXPENSE_ITEM_PLANS_MONEY WHERE MONEY_TYPE = 'EUR'
  UNION ALL
  SELECT 'STOCK_FIS_MONEY', ACTION_ID, MONEY_TYPE, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID
    FROM {schema}.STOCK_FIS_MONEY WHERE MONEY_TYPE = 'EUR'
  UNION ALL
  SELECT 'CARI_ACTION_MONEY', ACTION_ID, MONEY_TYPE, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID
    FROM {schema}.CARI_ACTION_MONEY WHERE MONEY_TYPE = 'EUR'
  UNION ALL
  SELECT 'CARI_ACTION_MULTI_MONEY', ACTION_ID, MONEY_TYPE, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID
    FROM {schema}.CARI_ACTION_MULTI_MONEY WHERE MONEY_TYPE = 'EUR'
  UNION ALL
  SELECT 'CREDIT_CONTRACT_PAYMENT_INCOME_MONEY', ACTION_ID, MONEY_TYPE, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID
    FROM {schema}.CREDIT_CONTRACT_PAYMENT_INCOME_MONEY WHERE MONEY_TYPE = 'EUR'
  UNION ALL
  SELECT 'PAYROLL_MONEY', ACTION_ID, MONEY_TYPE, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID
    FROM {schema}.PAYROLL_MONEY WHERE MONEY_TYPE = 'EUR'
  UNION ALL
  SELECT 'BANK_ACTION_MULTI_MONEY', ACTION_ID, MONEY_TYPE, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID
    FROM {schema}.BANK_ACTION_MULTI_MONEY WHERE MONEY_TYPE = 'EUR'
  UNION ALL
  SELECT 'BANK_ACTION_MONEY', ACTION_ID, MONEY_TYPE, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID
    FROM {schema}.BANK_ACTION_MONEY WHERE MONEY_TYPE = 'EUR'
  UNION ALL
  SELECT 'BANK_ORDER_MONEY', ACTION_ID, MONEY_TYPE, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID
    FROM {schema}.BANK_ORDER_MONEY WHERE MONEY_TYPE = 'EUR'
  UNION ALL
  SELECT 'CASH_ACTION_MONEY', ACTION_ID, MONEY_TYPE, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID
    FROM {schema}.CASH_ACTION_MONEY WHERE MONEY_TYPE = 'EUR'
  UNION ALL
  SELECT 'CREDIT_CARD_BANK_EXPENSE_MONEY', ACTION_ID, MONEY_TYPE, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID
    FROM workcube_mikrolink_{company_id}.CREDIT_CARD_BANK_EXPENSE_MONEY WHERE MONEY_TYPE = 'EUR'
  UNION ALL
  SELECT 'TAHAKKUK_PLAN_MONEY', ACTION_ID, MONEY_TYPE, RATE1, RATE2, IS_SELECTED, ACTION_MONEY_ID
    FROM workcube_mikrolink_{company_id}.TAHAKKUK_PLAN_MONEY WHERE MONEY_TYPE = 'EUR'
),
base AS (
  SELECT
    ac.*, r.*,
    ap.ACCOUNT_NAME,
    acdt.DOCUMENT_TYPE AS card_document_type_name,
    spc.PROCESS_CAT,
    p.PROJECT_HEAD,
    co.FULLNAME AS cari_name,

    -- TL native
    CASE
      WHEN r.AMOUNT_CURRENCY IN ('TL','TRY') OR r.AMOUNT_CURRENCY IS NULL
      THEN r.AMOUNT
    END AS tl_native_amount,

    -- USD native (dinamik)
    CASE
      WHEN r.AMOUNT_CURRENCY = 'USD'   THEN r.AMOUNT
      WHEN r.AMOUNT_CURRENCY_2 = 'USD' THEN r.AMOUNT_2
    END AS usd_native_amount,

    -- EUR native (dinamik, conversion ayrı katmanda)
    CASE
      WHEN r.AMOUNT_CURRENCY = 'EUR'   THEN r.AMOUNT
      WHEN r.AMOUNT_CURRENCY_2 = 'EUR' THEN r.AMOUNT_2
    END AS eur_native_amount

  FROM ac
  JOIN rows r ON r.CARD_ID = ac.CARD_ID
  LEFT JOIN {schema}.ACCOUNT_PLAN ap
    ON LTRIM(RTRIM(ap.ACCOUNT_CODE)) = r.account_code
   AND ap.SUB_ACCOUNT = 0
  LEFT JOIN workcube_mikrolink.ACCOUNT_CARD_DOCUMENT_TYPES acdt
    ON acdt.DOCUMENT_TYPE_ID = ac.CARD_DOCUMENT_TYPE
   AND acdt.OUR_COMPANY_ID = CAST(:company_id AS nvarchar(20))
  LEFT JOIN workcube_mikrolink_{company_id}.SETUP_PROCESS_CAT spc
    ON spc.PROCESS_CAT_ID = ac.CARD_CAT_ID
  LEFT JOIN workcube_mikrolink.PRO_PROJECTS p
    ON p.PROJECT_ID = ac.PROJECT_ID
  LEFT JOIN workcube_mikrolink.COMPANY co
    ON co.COMPANY_ID = ac.ACC_COMPANY_ID
),
rated AS (
  SELECT
    b.*,
    rate_pick.eur_rate,
    rate_pick.kur_kaynagi,
    rate_pick.rate_date,
    rate_pick.rate_id
  FROM base b
  OUTER APPLY (
    SELECT TOP (1) *
    FROM (
      -- L1: ACM by CARD_ID
      SELECT acm.RATE2 AS eur_rate,
             CONCAT('ACM|CARD_ID|RATE2|MID:', acm.ACTION_MONEY_ID) AS kur_kaynagi,
             CAST(NULL AS datetime) AS rate_date,
             acm.ACTION_MONEY_ID AS rate_id,
             10 AS priority
      FROM {schema}.ACCOUNT_CARD_MONEY acm
      WHERE acm.ACTION_ID = b.CARD_ID AND acm.MONEY_TYPE = 'EUR'

      UNION ALL
      -- L2: ACM by source ACTION_ID (cascade)
      SELECT acm.RATE2,
             CONCAT('ACM|ACTION_ID|RATE2|MID:', acm.ACTION_MONEY_ID),
             NULL, acm.ACTION_MONEY_ID, 20
      FROM {schema}.ACCOUNT_CARD_MONEY acm
      WHERE acm.ACTION_ID = b.ACTION_ID AND acm.MONEY_TYPE = 'EUR'

      UNION ALL
      -- L3: POOL exact ACTION_TABLE
      SELECT p.RATE2,
             CONCAT('POOL|', p.action_table, '|RATE2|MID:', p.money_row_id),
             NULL, p.money_row_id, 30
      FROM pool p
      WHERE p.action_table = b.ACTION_TABLE AND p.ACTION_ID = b.ACTION_ID

      UNION ALL
      -- L4: POOL fallback via MONEY_TABLES dispatch
      SELECT p.RATE2,
             CONCAT('POOL|', p.action_table, '|RATE2|MID:', p.money_row_id, '|VIA:MT'),
             NULL, p.money_row_id, 40
      FROM workcube_mikrolink.MONEY_TABLES mt
      INNER JOIN pool p ON p.action_table = mt.ACTION_TABLE AND p.ACTION_ID = b.ACTION_ID
      WHERE mt.ACTION_TYPE = b.ACTION_TYPE
        AND (b.ACTION_TABLE IS NULL OR b.ACTION_TABLE = '')

      UNION ALL
      -- L5: MH same-day company
      SELECT mh.RATE2,
             CONCAT('MH|COMPANY|SAME_DAY|RATE2|DATE:', CONVERT(varchar, mh.VALIDATE_DATE, 23), '|MID:', mh.MONEY_HISTORY_ID),
             mh.VALIDATE_DATE, mh.MONEY_HISTORY_ID, 50
      FROM workcube_mikrolink.MONEY_HISTORY mh
      WHERE mh.MONEY = 'EUR' AND mh.COMPANY_ID = :company_id
        AND CAST(mh.VALIDATE_DATE AS date) = CAST(b.ACTION_DATE AS date)

      UNION ALL
      -- L6: MH same-day global
      SELECT mh.RATE2,
             CONCAT('MH|GLOBAL|SAME_DAY|RATE2|DATE:', CONVERT(varchar, mh.VALIDATE_DATE, 23), '|MID:', mh.MONEY_HISTORY_ID),
             mh.VALIDATE_DATE, mh.MONEY_HISTORY_ID, 60
      FROM workcube_mikrolink.MONEY_HISTORY mh
      WHERE mh.MONEY = 'EUR' AND mh.COMPANY_ID IS NULL
        AND CAST(mh.VALIDATE_DATE AS date) = CAST(b.ACTION_DATE AS date)

      UNION ALL
      -- L7: MH ≤7 day prev company
      SELECT mh.RATE2,
             CONCAT('MH|COMPANY|PREV_DAY|RATE2|DATE:', CONVERT(varchar, mh.VALIDATE_DATE, 23),
                    '|AGE:', DATEDIFF(day, mh.VALIDATE_DATE, b.ACTION_DATE), '|MID:', mh.MONEY_HISTORY_ID),
             mh.VALIDATE_DATE, mh.MONEY_HISTORY_ID, 70
      FROM workcube_mikrolink.MONEY_HISTORY mh
      WHERE mh.MONEY = 'EUR' AND mh.COMPANY_ID = :company_id
        AND mh.VALIDATE_DATE < b.ACTION_DATE
        AND mh.VALIDATE_DATE >= DATEADD(day, -7, b.ACTION_DATE)

      UNION ALL
      -- L8: MH ≤7 day prev global
      SELECT mh.RATE2,
             CONCAT('MH|GLOBAL|PREV_DAY|RATE2|DATE:', CONVERT(varchar, mh.VALIDATE_DATE, 23),
                    '|AGE:', DATEDIFF(day, mh.VALIDATE_DATE, b.ACTION_DATE), '|MID:', mh.MONEY_HISTORY_ID),
             mh.VALIDATE_DATE, mh.MONEY_HISTORY_ID, 80
      FROM workcube_mikrolink.MONEY_HISTORY mh
      WHERE mh.MONEY = 'EUR' AND mh.COMPANY_ID IS NULL
        AND mh.VALIDATE_DATE < b.ACTION_DATE
        AND mh.VALIDATE_DATE >= DATEADD(day, -7, b.ACTION_DATE)
    ) candidates
    WHERE eur_rate IS NOT NULL
    ORDER BY priority ASC, rate_date DESC, rate_id DESC
  ) rate_pick
)
SELECT
  account_code, ACCOUNT_NAME AS account_name, ACTION_DATE AS action_date,
  CARD_ID AS card_id, card_document_type_name AS fis_tipi, PAPER_NO AS paper_no,
  PROCESS_CAT AS process_cat, DETAIL AS aciklama, CARD_DETAIL AS kart_aciklama,
  cari_name AS cari, PROJECT_HEAD AS proje, WRK_ID AS wrk_id,
  ba_code,

  -- TL block
  CASE WHEN ba_code='B' THEN tl_native_amount END AS borc_tl,
  CASE WHEN ba_code='A' THEN tl_native_amount END AS alacak_tl,
  CASE WHEN ba_code='B' THEN tl_native_amount ELSE -tl_native_amount END AS net_tl,
  SUM(CASE WHEN ba_code='B' THEN tl_native_amount ELSE -tl_native_amount END)
    OVER (PARTITION BY account_code ORDER BY ACTION_DATE, CARD_ID, CARD_ROW_ID
          ROWS UNBOUNDED PRECEDING) AS bakiye_tl,

  -- USD block
  CASE WHEN ba_code='B' THEN usd_native_amount END AS borc_usd,
  CASE WHEN ba_code='A' THEN usd_native_amount END AS alacak_usd,
  CASE WHEN ba_code='B' THEN usd_native_amount ELSE -usd_native_amount END AS net_usd,
  SUM(CASE WHEN ba_code='B' THEN usd_native_amount ELSE -usd_native_amount END)
    OVER (PARTITION BY account_code ORDER BY ACTION_DATE, CARD_ID, CARD_ROW_ID
          ROWS UNBOUNDED PRECEDING) AS bakiye_usd,

  -- EUR block
  eur_rate AS eur_kuru,
  CASE
    WHEN ba_code='B' AND eur_native_amount IS NOT NULL THEN eur_native_amount
    WHEN ba_code='B' AND eur_rate IS NOT NULL THEN tl_native_amount / eur_rate
  END AS borc_eur,
  CASE
    WHEN ba_code='A' AND eur_native_amount IS NOT NULL THEN eur_native_amount
    WHEN ba_code='A' AND eur_rate IS NOT NULL THEN tl_native_amount / eur_rate
  END AS alacak_eur,
  CASE
    WHEN eur_native_amount IS NOT NULL
      THEN eur_native_amount * (CASE WHEN ba_code='B' THEN 1 ELSE -1 END)
    WHEN eur_rate IS NOT NULL
      THEN (tl_native_amount / eur_rate) * (CASE WHEN ba_code='B' THEN 1 ELSE -1 END)
  END AS net_eur,
  SUM(CASE
        WHEN eur_native_amount IS NOT NULL
          THEN eur_native_amount * (CASE WHEN ba_code='B' THEN 1 ELSE -1 END)
        WHEN eur_rate IS NOT NULL
          THEN (tl_native_amount / eur_rate) * (CASE WHEN ba_code='B' THEN 1 ELSE -1 END)
      END)
    OVER (PARTITION BY account_code ORDER BY ACTION_DATE, CARD_ID, CARD_ROW_ID
          ROWS UNBOUNDED PRECEDING) AS bakiye_eur,

  -- Audit
  COALESCE(kur_kaynagi, 'MISSING|EUR_RATE_NOT_FOUND') AS kur_kaynagi,
  rate_date AS kur_tarihi,
  rate_id AS kur_id,
  CASE WHEN rate_date IS NOT NULL THEN DATEDIFF(day, rate_date, ACTION_DATE) END AS kur_yas_gun,
  CASE
    WHEN card_document_type_name LIKE N'%çılış%' OR card_document_type_name LIKE N'%cilis%' THEN 1
    ELSE 0
  END AS is_opening_document
FROM rated
ORDER BY account_code, ACTION_DATE, CARD_ID, CARD_ROW_ID;
```

---

## 8. Filter Şeması

| Yer | Eleman | Tip | Zorunlu |
|---|---|---|---|
| **Üst sticky** | OUR_COMPANY_ID | dropdown (OUR_COMPANY.COMP_ID + COMPANY_NAME) | ✅ Evet |
| Header inline | Tarih | date range | ⏸ |
| Header inline | Hesap Kodu | text range/like | ⏸ |
| Header inline | Fiş Tipi | dropdown (ACCOUNT_CARD_DOCUMENT_TYPES) | ⏸ |
| Header inline | Süreç Kategorisi | dropdown | ⏸ |
| Header inline | Cari | LIKE | ⏸ |
| Header inline | Proje | LIKE | ⏸ |

---

## 9. Performans

- **Yıllar server-side `UNION ALL`**: Spring Boot client-side iterasyon YOK; yıl sınırında bakiye bozulur.
- Tek outer query window function `SUM() OVER ROWS UNBOUNDED PRECEDING`.
- **Index önerisi (canlı uygulama, MSSQL DBA tarafında)**:
  - `ACCOUNT_CARD(ACTION_DATE, CARD_ID) INCLUDE (ACTION_ID, ACTION_TYPE, ACTION_TABLE, PAPER_NO, CARD_CAT_ID, CARD_DOCUMENT_TYPE, PROJECT_ID, ACC_COMPANY_ID, IS_CANCEL)`
  - `ACCOUNT_CARD_ROWS(CARD_ID, ACCOUNT_ID, CARD_ROW_ID) INCLUDE (AMOUNT, AMOUNT_CURRENCY, AMOUNT_2, AMOUNT_CURRENCY_2, BA, DETAIL)`
  - 13 *_MONEY pool: `(ACTION_ID, MONEY_TYPE) INCLUDE (RATE2, IS_SELECTED, ACTION_MONEY_ID)`
  - `MONEY_HISTORY(MONEY, COMPANY_ID, VALIDATE_DATE DESC, MONEY_HISTORY_ID DESC) INCLUDE (RATE2, RECORD_DATE)`
  - Global fallback: `MONEY_HISTORY(MONEY, VALIDATE_DATE DESC, MONEY_HISTORY_ID DESC)` filtered (COMPANY_ID IS NULL)
- Decimal cast: `MONEY_HISTORY.RATE2` float → `decimal(18,6)` (binary float toplam artefact engelle)
- Materialized view v1 YOK (ADR-0005 live data zorunluluğu)

---

## 10. Live Validation Results (2026-05-05)

Tüm doğrulama production MSSQL `workcube_mikrolink` (ERP-DB) üzerinde, COMPANY_ID=35 sample ile koştu (`docs/reports/muavin-validation-queries.sql`):

| Soru | Beklenti | Sonuç | Karar |
|---|---|---|---|
| ACM join key | CARD_ID veya ACTION_ID | **CARD_ID 552, ACTION_ID 512** | L1=CARD_ID, L2=ACTION_ID cascade |
| MONEY_TABLES dispatch | 60 satır deterministic | ✅ 60 satır 1:1, **0 duplicate**, BANK_ORDER_MONEY yeni | UNION ALL pool yerine MONEY_TABLES + ACTION_TABLE dispatch |
| RATE column | RATE1 = TCMB? | **❌ RATE1 = 1.0 dummy**; RATE2 alış, RATE3 satış | RATE2 default |
| MONEY_HISTORY size | snapshot 180,995 | ✅ 181,436 satır canlı, 4,449 satır COMPANY_ID=35 | OK |
| NEW_MONEY_HISTORY | staging? | ✅ 981 satır, **%99.7 MONEY_HISTORY subset** | v1 ignore |
| FOREKS canlılık | RATE source? | **NULL — boş** | v1 layer çıkar |
| Açılış fişi | SETUP_DOCUMENT_TYPE? | **0 satır 'Açılış'** | ACCOUNT_CARD_DOCUMENT_TYPES primary |
| ACCOUNT_CARD.ACTION_TABLE | dispatch primary? | **%99 NULL** (sadece 199/20367) | secondary, MONEY_TABLES primary |
| ACCOUNT_ID type | int? | **nvarchar(100)** | text join LTRIM/RTRIM |
| BA semantik | 'B'/'A'? | **bit 1=B 0=A** | SQL'de CASE normalize |

---

## 11. Sonraki Adımlar

| # | Adım | Sahip | Durum |
|---|---|---|---|
| 1 | Spec doc | platform-team | ✅ Bu dosya |
| 2 | Live validation 5 kategori | platform-team | ✅ tamamlandı |
| 3 | JSON template (`fin-muhasebe-detay.json`) | platform-backend repo | ⏸ pending (cross-repo PR — SQL §7'den) |
| 4 | Annex update (`manually_validated: true`) | this repo | ⏸ pending (post JSON template merge) |
| 5 | MSSQL credential rotation (Vault path canlı) | operator | ✅ ESO secret çalışıyor (canlı doğrulandı) |
| 6 | Index önerileri Workcube DBA'ye | user | ⏸ pending |

---

## 12. Referanslar

- Codex thread: `019df4ed-615c-73d1-b67a-7d0b61cc94df` (REVISE iter-2 absorb)
- ADR-0005 dual-datasource reporting
- Annex 2A: `docs/migration/report-source-annex.yaml`
- Schema snapshot: `docs/migration/workcube-schema.json`
- Live validation queries: `docs/reports/muavin-validation-queries.sql`
- User session: 2026-05-04 → 2026-05-05 muavin grid spec konuşması
