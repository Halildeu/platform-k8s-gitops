# RB-doc-repair-loop – Doc-Repair Loop (Plan Only v0.1)

ID: RB-doc-repair-loop  
Service: docs-quality/doc-repair-loop  
Status: Draft  
Owner: Halil K.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `docflow_next` autopilot “dry-run” çıktısından (summary.md) deterministik bir doc-repair planı üretmek.
- Bu runbook **plan-only** kapsamdadır; otomatik patch uygulamaz.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Kapsam:
  - `scripts/docflow_next.py autopilot --dry-run` çıktısı üzerinden plan üretimi
  - Reason normalization SSOT: `docs-ssot/03-delivery/SPECS/doc-repair-reason-map.v0.1.json`
- Ortamlar:
  - Local (developer machine)
  - CI (plan üretimi opsiyonel; gate değil)

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Başlatma:
  1) Autopilot dry-run summary üret:
     - `python3 scripts/docflow_next.py autopilot --dry-run --max-run 50 --summary-path web/test-results/ops/summary.md`
  2) Plan üret:
     - `python3 scripts/doc_repair_plan.py --summary web/test-results/ops/summary.md`
- Durdurma:
  - Bu akış stateful servis içermez; koşum yapılmadığında “durdurulmuş” sayılır.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Log:
  - `docflow_next` ve `doc_repair_plan` stdout.
- Artefact’lar:
  - `web/test-results/ops/summary.md` (autopilot)
  - `artifacts/doc-repair/plan.json`
  - `artifacts/doc-repair/report.md`
- Sağlık kontrolü (best-effort):
  - `report.md` içinde “parse edilebilir Blocked Reasons bulunamadı” uyarısı varsa, summary formatı veya arama scope’u kontrol edilir.

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – Reason map dosyası yok / JSON parse edilemiyor:
  - Given: `doc_repair_plan` reason map yüklerken hata veriyor.  
    When: `docs-ssot/03-delivery/SPECS/doc-repair-reason-map.v0.1.json` yok veya JSON bozuk.  
    Then:
    - Dosya path’ini kontrol et.
    - Gerekirse `--reason-map <PATH>` ile override et.

- [ ] Arıza senaryosu 2 – Plan boş (Blocked Reasons parse edilemiyor):
  - Given: `plan.json` içindeki `items` boş.  
    When: summary.md içinde “## Blocked Reasons” bölümü yok veya format değişmiş.  
    Then:
    - `docflow_next` komutunu `--summary-path` ile belirgin bir path’e yazdır.
    - summary.md içinde “## Blocked Reasons” ve `- STORY-XXXX: ...` satırlarını doğrula.
    - Gerekirse parser/regex’i güncelle (v0.2).

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- v0.1 yalnız plan üretir; patch uygulama ayrı bir adım/epic kapsamıdır.
- Reason normalization SSOT tek kaynaktır; yeni reason’lar buraya eklenmelidir.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- ADR: `docs/02-architecture/services/backend-docs/ADR/ADR-0002-doc-repair-loop-v0-1.md`
- SPEC: `docs/03-delivery/SPECS/SPEC-0009-doc-repair-loop-v0-1.md`
- Reason map: `docs-ssot/03-delivery/SPECS/doc-repair-reason-map.v0.1.json`
- Engine: `scripts/docflow_next.py`
- Workflow: `.github/workflows/doc-qa.yml`
