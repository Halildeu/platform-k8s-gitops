# ACCEPTANCE – Kabul Kriterleri Şablonu

ID: AC-XXXX  
Story: STORY-XXXX-<slug>  
Status: Planned | In Progress | Done  
Owner: <isim>

Kural:
- `AC-XXXX` numarası, `Story:` alanındaki `STORY-XXXX` ile aynı olmalıdır.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Test edilebilir kabul kriterlerini tanımlamak.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Hangi story/PRD maddeleri için geçerli?

-------------------------------------------------------------------------------
3. GIVEN / WHEN / THEN SENARYOLARI
-------------------------------------------------------------------------------

Kural:
- Bu bölüm “checklist” mantığında ilerler: `[ ]` → tamamlanınca `[x]`.
- Senaryolar kısa, test edilebilir ve net olmalı.
- İş birden fazla alanı etkiliyorsa, senaryoları modül bazlı grupla (H3).

### Ortak (varsa)

- [ ] Senaryo 1 – Given ..., When ..., Then ...

### Backend (varsa)

- [ ] Senaryo – Given ..., When ..., Then ...
  - Kanıt/Evidence (önerilen):
    - Kod: `backend/...` (örnek path)
    - Test: `scripts/run_tests_backend.sh` (örnek komut)
    - Log/Metrik: (varsa)

### Web (varsa)

- [ ] Senaryo – Given ..., When ..., Then ...
  - Kanıt/Evidence (önerilen):
    - Kod: `web/...` (örnek path)
    - Test: `scripts/run_tests_web.sh` (örnek komut)
    - UI: ekran/route adı (varsa)

### Data (varsa)

- [ ] Senaryo – Given ..., When ..., Then ...
  - Kanıt/Evidence (önerilen):
    - SQL/ETL: `data/...` (örnek path)
    - Kontrol: `scripts/check_data_all.py` (örnek komut)

### Operations (varsa)

- [ ] Senaryo – Given ..., When ..., Then ...
  - Kanıt/Evidence (önerilen):
    - Runbook: `docs/04-operations/RUNBOOKS/RB-<servis>.md`
    - Release/Smoke: `scripts/release_smoke_check.py` (örnek komut)

-------------------------------------------------------------------------------
4. NOTLAR / KISITLAR
-------------------------------------------------------------------------------

- Özellikle belirtilmesi gereken durumlar.

-------------------------------------------------------------------------------
5. ÖZET
-------------------------------------------------------------------------------

- En kritik kabul kriterlerinin özeti.

-------------------------------------------------------------------------------
6. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Story: docs/03-delivery/STORIES/STORY-XXX-*.md
- Test Plan: docs/03-delivery/TEST-PLANS/TP-XXX-*.md
