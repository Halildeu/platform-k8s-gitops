# RB-guides-tbd-burn-down – GUIDE TBD Burn-down Plan

ID: RB-guides-tbd-burn-down
Service: docs
Status: Draft
Owner: @team/platform

Not: GUIDE migration sonrası eklenen NUM başlık scaffold’larında kalan `TBD` placeholder’larını
kontrollü şekilde doldurmak için hazırlanmıştır.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- GUIDE migration sonrası oluşan `TBD` placeholder’larını sprint bazlı burn-down ile azaltmak.
- İçerik doldurmayı “kritik bölümler önce” yaklaşımı ile yönetmek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Guides: `docs/03-delivery/guides/**/GUIDE-*.md`
- Template: `docs/99-templates/GUIDE.template.md`
- Gate (format): `scripts/check_doc_heading_contract.py` (NUM başlık sözleşmesi)
- Local ranking artefact (gitignored):
  - `.autopilot-tmp/flow-mining/guides-tbd-ranking.json`

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

Başlat (haftalık/sprint başı):
1) TBD yoğunluğu raporu üret:
   - `python3 - <<'PY' ...` (veya ilgili helper) → `.autopilot-tmp/flow-mining/guides-tbd-ranking.json`
2) Sprint hedefi seç:
   - 5 guide / sprint (öneri)
3) Her seçilen guide için minimum doldurma:
   - `1. AMAÇ`
   - `2. KAPSAM`
   - `5. ADIM ADIM (KULLANIM)`

Durdur (pausa/rollback):
- Değişiklikleri geri almak için PR revert edilir (policy flip yok; içerik değişikliği).

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Local ölçüm:
  - Toplam `TBD` sayısı (haftalık trend)
  - “kritik 3 bölüm dolu” oranı (manuel kontrol veya basit parser ile)
- CI sinyali:
  - doc-qa PASS (format/konum/ID/link zinciri)
- Kanıt:
  - `.autopilot-tmp/execution-log/execution-log.md` (local)

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – TBD doldurma PR’ı doc-qa FAIL
  - Given: Bir guide dolduruldu ama format/konum/link kuralı bozuldu.
  - When: PR açıldı ve doc-qa koştu.
  - Then: FAIL beklenir.
  - Adımlar:
    1) Lokal: `python3 scripts/run_doc_qa_execution_log_local.py --out-dir .autopilot-tmp/execution-log`
    2) İlk failing check’in raw log’una bak: `.autopilot-tmp/execution-log/raw/*`
    3) Tipik fix:
       - NUM başlık sözleşmesi → eksik/yanlış başlıkları düzelt
       - Konum kuralı → dosya path’ini düzelt
       - Link zinciri → STORY LİNKLER’deki path’leri güncelle

- [ ] Arıza senaryosu 2 – İçerik kaybı riski (migration sonrası)
  - Given: Legacy içerik “TBD” blokları arasına yanlışlıkla silindi/taşındı.
  - When: Review sırasında kritik bilgi kaybı fark edildi.
  - Then: PR merge edilmeden geri alınır.
  - Adımlar:
    1) `git diff` ile kayıp alanları tespit et.
    2) İçeriği geri getir; sadece “scaffold TBD” satırlarını değiştir.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Format (NUM başlıklar) gate ile sabit; içerik kalitesi burn-down ile iteratif artırılır.
- Öncelik: kritik kullanım rehberleri ve operasyonel akışları etkileyen guide’lar.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Template: `docs/99-templates/GUIDE.template.md`
- Mapping SSOT: `docs-ssot/00-handbook/DOC-TEMPLATE-MAP-SSOT.json`
- Guides policy: `docs-ssot/03-delivery/SPECS/guides-policy.v1.json`
- Checker: `scripts/check_doc_heading_contract.py`
- Local ranking: `.autopilot-tmp/flow-mining/guides-tbd-ranking.json`
