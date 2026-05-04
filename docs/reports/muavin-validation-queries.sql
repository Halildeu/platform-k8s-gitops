-- ============================================================================
-- Muavin Raporu — Canlı Doğrulama Sorguları
-- Codex thread 019df4ed-615c-73d1-b67a-7d0b61cc94df REVISE absorb gate
-- Spec: docs/reports/muavin-grid-spec.md §10
-- ============================================================================
--
-- BAĞLAM: fin-muhasebe-detay JSON template kilitlemeden önce 3 canlı doğrulama
-- gerekli. report-service @Qualifier("mssqlReadOnly") ile aynı user (read-only)
-- kullanarak çalıştır. {COMPANY_ID} placeholder'ını gerçek şirket id'siyle değiştir.
--
-- Kullanım:
--   sqlcmd -S 10.9.193.201 -d workcube_mikrolink -U <user> -P <pass> \
--          -i docs/reports/muavin-validation-queries.sql -o muavin-validation-output.txt
--
-- Çıktı dosyasını paylaşırsan JSON template'i kilitleyeceğim.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- VALIDATION 1: ACCOUNT_CARD_MONEY join key
-- Soru: ACM.ACTION_ID = AC.CARD_ID mı, AC.ACTION_ID mı?
-- Beklenen: birinin matched count diğerinden belirgin yüksek olmalı.
-- Önemi: yanlış join = EUR kuru fiş-level override yanlış uygulanır.
-- ----------------------------------------------------------------------------
PRINT '=== VALIDATION 1: ACCOUNT_CARD_MONEY join key ===';

SELECT 'ACM.ACTION_ID = AC.CARD_ID' AS variant, COUNT(*) AS matched_rows
FROM workcube_mikrolink_2026_{COMPANY_ID}.ACCOUNT_CARD AC
INNER JOIN workcube_mikrolink_2026_{COMPANY_ID}.ACCOUNT_CARD_MONEY ACM
  ON ACM.ACTION_ID = AC.CARD_ID
WHERE ACM.MONEY_TYPE = 'EUR'
  AND AC.ACTION_DATE >= '2026-01-01'
UNION ALL
SELECT 'ACM.ACTION_ID = AC.ACTION_ID' AS variant, COUNT(*)
FROM workcube_mikrolink_2026_{COMPANY_ID}.ACCOUNT_CARD AC
INNER JOIN workcube_mikrolink_2026_{COMPANY_ID}.ACCOUNT_CARD_MONEY ACM
  ON ACM.ACTION_ID = AC.ACTION_ID
WHERE ACM.MONEY_TYPE = 'EUR'
  AND AC.ACTION_DATE >= '2026-01-01';

-- Plus: ACCOUNT_CARD_MONEY tam kolon listesi
PRINT '=== ACCOUNT_CARD_MONEY columns ===';
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE, ORDINAL_POSITION
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'workcube_mikrolink_2026_{COMPANY_ID}'
  AND TABLE_NAME   = 'ACCOUNT_CARD_MONEY'
ORDER BY ORDINAL_POSITION;


-- ----------------------------------------------------------------------------
-- VALIDATION 2: MONEY_TABLES dispatch row values
-- Soru: ACTION_TYPE → ACTION_TABLE mapping nasıl?
-- Beklenen: 60 satır (snapshot iddiası), her ACTION_TYPE bir ACTION_TABLE'a map.
-- Önemi: POOL deterministic dispatch — UNION+TOP(1) priority heuristic değil.
-- ----------------------------------------------------------------------------
PRINT '=== VALIDATION 2: MONEY_TABLES dispatch ===';

SELECT MT_ID, ACTION_TYPE, ACTION_TABLE
FROM workcube_mikrolink.MONEY_TABLES
ORDER BY ACTION_TYPE, MT_ID;

-- Aynı ACTION_TYPE birden fazla ACTION_TABLE'a map ediliyor mu?
PRINT '=== Duplicate ACTION_TYPE check ===';
SELECT ACTION_TYPE, COUNT(*) AS table_count
FROM workcube_mikrolink.MONEY_TABLES
GROUP BY ACTION_TYPE
HAVING COUNT(*) > 1
ORDER BY table_count DESC;


-- ----------------------------------------------------------------------------
-- VALIDATION 3: RATE1 vs FOREKS sample (rate kolonu seçimi)
-- Soru: MONEY_HISTORY.RATE1 ≈ FOREKS_MerkezBankasiDoviz.dblAlis mı?
-- Beklenen: aynı tarih aynı sembolde yakın değerler (RATE1 = TCMB resmi tezi).
-- Önemi: RATE1 vs RATEPP2 vs RATE2/3 — hangi muhasebe kuru standardı?
-- ----------------------------------------------------------------------------
PRINT '=== VALIDATION 3: RATE column comparison ===';

SELECT TOP 30
       MH.VALIDATE_DATE,
       MH.MONEY,
       MH.COMPANY_ID,
       MH.PERIOD_ID,
       CAST(MH.RATE1   AS decimal(18,6)) AS MH_RATE1,
       CAST(MH.RATE2   AS decimal(18,6)) AS MH_RATE2,
       CAST(MH.RATE3   AS decimal(18,6)) AS MH_RATE3,
       CAST(MH.RATEPP2 AS decimal(18,6)) AS MH_RATEPP2,
       CAST(MH.RATEPP3 AS decimal(18,6)) AS MH_RATEPP3,
       CAST(MH.RATEWW2 AS decimal(18,6)) AS MH_RATEWW2,
       CAST(MH.EFFECTIVE_SALE AS decimal(18,6)) AS MH_EFF_SALE,
       CAST(MH.EFFECTIVE_PUR  AS decimal(18,6)) AS MH_EFF_PUR,
       CAST(F.dblAlis  AS decimal(18,6)) AS FOREKS_ALIS,
       CAST(F.dblSatis AS decimal(18,6)) AS FOREKS_SATIS
FROM workcube_mikrolink.MONEY_HISTORY MH
LEFT JOIN workcube_mikrolink.FOREKS_MerkezBankasiDoviz F
  ON F.dtmTarih  = MH.VALIDATE_DATE
 AND F.strSembol = MH.MONEY
WHERE MH.MONEY IN ('EUR', 'USD')
  AND MH.VALIDATE_DATE >= '2026-01-01'
ORDER BY MH.VALIDATE_DATE DESC, MH.MONEY;

-- Plus: MONEY_HISTORY satır sayısı (snapshot iddiası 180,995)
PRINT '=== MONEY_HISTORY row counts ===';
SELECT COUNT(*) AS total_rows,
       SUM(CASE WHEN COMPANY_ID IS NULL THEN 1 ELSE 0 END) AS global_rows,
       SUM(CASE WHEN COMPANY_ID = {COMPANY_ID} THEN 1 ELSE 0 END) AS company_specific_rows,
       MIN(VALIDATE_DATE) AS earliest_date,
       MAX(VALIDATE_DATE) AS latest_date,
       COUNT(DISTINCT MONEY) AS distinct_currencies
FROM workcube_mikrolink.MONEY_HISTORY;

-- NEW_MONEY_HISTORY karşılaştırma (snapshot iddiası 981 row, staging/delta)
PRINT '=== NEW_MONEY_HISTORY comparison ===';
SELECT 'MONEY_HISTORY' AS source, COUNT(*) AS rows
FROM workcube_mikrolink.MONEY_HISTORY
UNION ALL
SELECT 'NEW_MONEY_HISTORY', COUNT(*)
FROM workcube_mikrolink.NEW_MONEY_HISTORY;

-- Aynı MONEY_HISTORY_ID iki tabloda var mı (overlay tezi)?
PRINT '=== Overlay check (NEW vs OLD ID overlap) ===';
SELECT COUNT(*) AS overlapping_ids
FROM workcube_mikrolink.NEW_MONEY_HISTORY NMH
INNER JOIN workcube_mikrolink.MONEY_HISTORY MH
  ON MH.MONEY_HISTORY_ID = NMH.MONEY_HISTORY_ID;


-- ----------------------------------------------------------------------------
-- BONUS: Açılış fişi tipi tespiti
-- Soru: SETUP_DOCUMENT_TYPE.DOCUMENT_TYPE_NAME = 'Açılış' güvenli mi?
-- Codex uyarı: ACCOUNT_CARD_DOCUMENT_TYPES da var, şirket-bazlı custom isim.
-- ----------------------------------------------------------------------------
PRINT '=== BONUS: Açılış fişi lookup ===';

SELECT DOCUMENT_TYPE_ID, DOCUMENT_TYPE_NAME, DOCUMENT_TYPE_DETAIL
FROM workcube_mikrolink.SETUP_DOCUMENT_TYPE
WHERE DOCUMENT_TYPE_NAME LIKE '%çılış%'
   OR DOCUMENT_TYPE_NAME LIKE '%Acilis%'
   OR DOCUMENT_TYPE_NAME LIKE '%Opening%';

-- ACCOUNT_CARD_DOCUMENT_TYPES ne içeriyor?
PRINT '=== ACCOUNT_CARD_DOCUMENT_TYPES schema ===';
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'workcube_mikrolink'
  AND TABLE_NAME   = 'ACCOUNT_CARD_DOCUMENT_TYPES'
ORDER BY ORDINAL_POSITION;


-- ----------------------------------------------------------------------------
-- BONUS: ACCOUNT_CARD parametric tablo kolon doğrulama (script'ten gelen iddia)
-- Iddia: CARD_ID, ACTION_ID, ACTION_TYPE, ACTION_DATE, WRK_ID, CARD_DETAIL,
--        PAPER_NO, CARD_CAT_ID, ACC_COMPANY_ID, ACC_PROJECT_ID
-- ----------------------------------------------------------------------------
PRINT '=== ACCOUNT_CARD columns ===';
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE, ORDINAL_POSITION
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'workcube_mikrolink_2026_{COMPANY_ID}'
  AND TABLE_NAME   = 'ACCOUNT_CARD'
ORDER BY ORDINAL_POSITION;

PRINT '=== ACCOUNT_CARD_ROWS columns ===';
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE, ORDINAL_POSITION
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'workcube_mikrolink_2026_{COMPANY_ID}'
  AND TABLE_NAME   = 'ACCOUNT_CARD_ROWS'
ORDER BY ORDINAL_POSITION;

-- ============================================================================
-- ÇIKTI HEDEFİ
-- ============================================================================
-- Bu sorguların çıktısı (sqlcmd > muavin-validation-output.txt) paylaşılınca:
-- 1. JSON template ACCOUNT_CARD_MONEY join key kilitlenir (#1 sonuç)
-- 2. POOL UNION ALL → MONEY_TABLES exact dispatch refactor edilir (#2 sonuç)
-- 3. RATE1 vs RATEPP2 nihai karar verilir (#3 sonuç)
-- 4. Açılış fişi DOCUMENT_TYPE_ID hardcode edilir (BONUS sonucu)
-- 5. Annex `manually_validated: true` update edilir
-- 6. platform-backend repo'ya fin-muhasebe-detay.json PR'ı açılır
-- ============================================================================
