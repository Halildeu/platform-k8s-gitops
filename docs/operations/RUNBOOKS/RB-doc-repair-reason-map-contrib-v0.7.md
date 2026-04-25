# RB-doc-repair-reason-map-contrib-v0.7 – Doc-Repair Reason Map Katkı Rehberi (v0.7)

ID: RB-doc-repair-reason-map-contrib-v0.7  
Service: docs-quality/doc-repair-reason-map  
Status: Draft  
Owner: Halil K.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `artifacts/doc-repair/unknowns.md` içindeki `blockedReason` metinlerini, kanonik `reason_code`’lara deterministik şekilde map etmek.
- Hedef: `unknown_reason_ratio` oranını düşürmek (yeni reason_code eklemek değil).

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- SSOT:
  - `docs-ssot/03-delivery/SPECS/doc-repair-reason-map.v0.1.json`
- Kaynak artefact’lar:
  - `artifacts/doc-repair/unknowns.md`
  - `artifacts/doc-repair/metrics.json`
- Kurallar:
  - Pattern “substring” bazlıdır: `blockedReason` içinde geçmesi yeterli olmalı.
  - Çok genel pattern yazma (false positive üretir).
  - Önce en spesifik pattern (tam cümle), sonra varyantlar.
  - Yeni `reason_code` ekleme; önce mevcut `reason_codes` içinde map et.

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Başlatma:
  1) `unknowns.md` üret:
     - CI: `doc-repair-apply (dry-run)` workflow artifact’ından `artifacts/doc-repair/unknowns.md` dosyasını al.
     - Lokal:
       - `python3 scripts/docflow_next.py autopilot --dry-run --max-run 100 --summary-path artifacts/doc-repair/summary.md`
       - `python3 scripts/doc_repair_plan.py --summary artifacts/doc-repair/summary.md --out-dir artifacts/doc-repair`
       - `python3 scripts/doc_repair_unknowns.py --out artifacts/doc-repair/unknowns.md`
  2) Reason map’e pattern ekle:
     - `docs-ssot/03-delivery/SPECS/doc-repair-reason-map.v0.1.json` → `blockedReason_patterns[]`
  3) Gate:
     - `python3 scripts/check_doc_repair_reason_map.py`
- Durdurma:
  - Bu akış stateful servis içermez; komut koşmadığında “durdurulmuş” sayılır.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Artefact’lar:
  - `artifacts/doc-repair/unknowns.md` (Top blockedReason strings)
  - `artifacts/doc-repair/metrics.json` (`unknown_reason_ratio`)
- Metrik hedefi:
  - `unknown_reason_ratio` trendinin düşmesi (policy default: `max_unknown_reason_ratio=0.05`).

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – False positive artışı (yanlış map):
  - Given: `UNKNOWN` azalıyor ama yanlış `reason_code` artıyor.  
    When: Çok genel pattern eklendi.  
    Then:
    - Pattern’i daha spesifik yap (benzersiz substring/tam cümle).
    - Spesifik pattern’leri üst sıraya taşı (v0.1 normalize ilk eşleşmeyi alır).

- [ ] Arıza senaryosu 2 – Gate FAIL (schema-lite):
  - Given: `check_doc_repair_reason_map.py` FAIL.  
    When: duplicate pattern veya `reason_code` listede değil.  
    Then:
    - Duplicate pattern’i kaldır/düzelt.
    - `reason_code`’u mevcut `reason_codes` listesine göre düzelt.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Pattern’ler substring; regex yok.
- Yeni reason_code eklemek v0.7 kapsamı değil; önce mevcut listede map et.
- Değişiklik sonrası minimum doğrulama: `python3 scripts/check_doc_repair_reason_map.py` PASS.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Reason map (SSOT): `docs-ssot/03-delivery/SPECS/doc-repair-reason-map.v0.1.json`
- Checker: `scripts/check_doc_repair_reason_map.py`
- Unknowns: `scripts/doc_repair_unknowns.py`
- Metrics: `scripts/doc_repair_metrics.py`
- Workflow (dry-run): `.github/workflows/doc-repair-apply.yml`
- SPEC: `docs/03-delivery/SPECS/SPEC-0009-doc-repair-loop-v0-1.md`
- ADR: `docs/02-architecture/services/backend-docs/ADR/ADR-0002-doc-repair-loop-v0-1.md`

Kabul kriteri: Reason-map değişikliği sonrası `doc-repair-apply (dry-run)` çıktısında `unknown_reason_ratio` artmamalıdır; artıyorsa PR açıklamasında neden (false positive / yeni format / yeni reason) belirtilmelidir.
