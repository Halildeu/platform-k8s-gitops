# RB-doc-repair-apply-v0-2 – Doc-Repair Apply (v0.2)

ID: RB-doc-repair-apply-v0-2  
Service: docs-quality/doc-repair-apply  
Status: Draft  
Owner: Halil K.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `artifacts/doc-repair/plan.json` üzerinden deterministik ve güvenli (allowlist) doküman patch’lerini üretmek.
- Varsayılan davranış: **dry-run** (apply kapalı).

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Allowlist: `docs/**` (çıktı artefact’ları: `artifacts/doc-repair/**`).
- v0.2 kapsam reason’lar:
  - `STORY_LINKS_SECTION_MISSING`
  - `AC_MISSING` / `AC_FILE_MISSING`
  - `TP_MISSING` / `TP_FILE_MISSING`
- Not: Version Gate / env bloklarında apply yapılmaz (needs-human).

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Ön koşul: plan üret (plan-only):
  - `python3 scripts/docflow_next.py autopilot --dry-run --max-run 100 --summary-path artifacts/doc-repair/summary.md`
  - `python3 scripts/doc_repair_plan.py --summary artifacts/doc-repair/summary.md --out-dir artifacts/doc-repair`

- Dry-run (working tree değişmez):
  - `python3 scripts/doc_repair_apply.py --plan artifacts/doc-repair/plan.json --out-dir artifacts/doc-repair`

- Apply (lokal, working tree değişir):
  - `python3 scripts/doc_repair_apply.py --plan artifacts/doc-repair/plan.json --out-dir artifacts/doc-repair --apply`

- Durdurma:
  - Bu akış stateful servis içermez; komut koşmadığında “durdurulmuş” sayılır.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Log:
  - `docflow_next`, `doc_repair_plan`, `doc_repair_apply` stdout.
- Artefact’lar:
  - `artifacts/doc-repair/summary.md`
  - `artifacts/doc-repair/plan.json`
  - `artifacts/doc-repair/patch.diff`
  - `artifacts/doc-repair/apply-report.md`

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – Plan yok / parse edilemiyor:
  - Given: `plan.json` yok veya invalid JSON.  
    When: plan üretim adımı atlanmış ya da summary parse edilememiş.  
    Then:
    - `scripts/doc_repair_plan.py` ile planı yeniden üret.
    - `scripts/check_doc_repair_reason_map.py` ile reason map’i doğrula.

- [ ] Arıza senaryosu 2 – Apply sonrası doc-qa FAIL:
  - Given: Apply çalıştı ama doc-qa scriptleri FAIL.  
    When: Patch yanlış yerde, link zinciri kırık veya template/ID kuralı ihlali var.  
    Then:
    - `artifacts/doc-repair/patch.diff` ve `artifacts/doc-repair/apply-report.md` incele.
    - Gate setini koş:
      - `python3 scripts/check_doc_templates.py`
      - `python3 scripts/check_doc_ids.py`
      - `python3 scripts/check_doc_locations.py`
      - `python3 scripts/check_story_links.py`
      - `python3 scripts/check_doc_chain.py`
    - Gerekirse `git checkout -- docs/...` ile geri al (lokal).

- [ ] Arıza senaryosu 3 – Unsupported reason:
  - Given: Plan item `reason_code` v0.2’de desteklenmiyor.  
    When: reason-map genişledi ama apply motoru güncellenmedi.  
    Then:
    - `SPEC-0010` kapsamını güncelle ve `doc_repair_apply.py` v0.3’e taşı.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- v0.2 apply motoru yalnız belirli reason’larda `docs/**` altında küçük/deterministik patch uygular.
- “Tamamlandı” sayılması için doc-qa PASS gerekir.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- ADR: `docs/02-architecture/services/backend-docs/ADR/ADR-0002-doc-repair-loop-v0-1.md`
- SPEC (Plan): `docs/03-delivery/SPECS/SPEC-0009-doc-repair-loop-v0-1.md`
- SPEC (Apply): `docs/03-delivery/SPECS/SPEC-0010-doc-repair-apply-v0-2.md`
- Runbook (Plan): `docs/04-operations/RUNBOOKS/RB-doc-repair-loop.md`
