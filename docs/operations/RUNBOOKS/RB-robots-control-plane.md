# RB-robots-control-plane – Robot/Sync Control Plane (OBSERVE/PLAN/APPLY)

ID: RB-robots-control-plane
Service: ops
Status: Draft
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Dış kaynak sync “robot”larını tek SSOT altında yönetmek: mode=observe|plan|apply.
- Side-effect (dispatch/merge/rollback) işlemlerini confirm/flag ile güvenli hale getirmek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- SSOT:
  - Registry: `docs-ssot/04-operations/ROBOTS-REGISTRY.v0.1.json`
  - Policy: `docs-ssot/03-delivery/SPECS/robots-policy.v1.json`
- Checker’lar:
  - `scripts/check_robots_policy.py` (schema-lite; hard gate)
  - `scripts/check_robots_drift.py` (policy-aware; enabled=false iken non-blocking)

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Başlatma (local):
  1) Policy doğrula: `python3 scripts/check_robots_policy.py`
  2) Drift raporu üret: `python3 scripts/check_robots_drift.py`
- Durdurma (break-glass kapatma):
  - Policy’de `enabled: false` bırak (drift raporlayıcı, hard gate değil).

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Drift raporu (local-only):
  - `.autopilot-tmp/robots/robots-drift-report.md`
  - `.autopilot-tmp/robots/robots-drift-report.json`
- CI gözlemi:
  - `Doc QA` workflow (`.github/workflows/doc-qa.yml`)
  - Local kanıt: `.autopilot-tmp/execution-log/execution-log.md`

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – Registry/Policy JSON bozuk (schema FAIL):
  - Given: `scripts/check_robots_policy.py` FAIL
  - When: Doc QA / local execution-log koşuldu
  - Then:
    1) `docs-ssot/04-operations/ROBOTS-REGISTRY.v0.1.json` JSON parse/scheme hatasını düzelt.
    2) `python3 scripts/check_robots_policy.py` PASS olana kadar tekrarla.

- [ ] Arıza senaryosu 2 – Drift hard gate açıldı ve CI FAIL:
  - Given: `docs-ssot/03-delivery/SPECS/robots-policy.v1.json` içinde `enabled=true`
  - When: `scripts/check_robots_drift.py` ihlal buldu
  - Then:
    1) `.autopilot-tmp/robots/robots-drift-report.md` içinde UNREGISTERED_ROBOT listesini aç.
    2) İlgili script/workflow için registry’ye kayıt ekle veya false-positive ise drift regex’ini daralt.
    3) Gerekirse geçici rollback: `enabled=false` (policy flip).

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Robots SSOT iki dosyada yaşar: registry + policy.
- Drift check enabled=false iken raporlayıcıdır; enabled=true iken hard gate’e döner.
- Apply işlemleri confirm/flag ile guard edilir.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- SSOT: `docs-ssot/04-operations/ROBOTS-REGISTRY.v0.1.json`
- Policy: `docs-ssot/03-delivery/SPECS/robots-policy.v1.json`
- Checker: `scripts/check_robots_policy.py`
- Checker: `scripts/check_robots_drift.py`
- CI: `.github/workflows/doc-qa.yml`

