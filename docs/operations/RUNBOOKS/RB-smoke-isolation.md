# RB-smoke-isolation – Zanzibar Smoke Test Compose Project Isolation

ID: RB-smoke-isolation  
Service: zanzibar-smoke-test  
Status: Active  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `Zanzibar Smoke Test` workflow'unun canlı staging stack'ini yok etmesini
  önlemek; smoke script'i izole bir compose project'te çalıştırıp
  `workflow_run` auto-trigger'ı kalıcı fix yerleşene kadar geçici
  kapatmak.
- 2026-04-15 P0 incident containment'ı: smoke cleanup trap canlı
  `platform` project'inin 17 servisini ve volume'larını sildi.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- `.github/workflows/smoke-zanzibar.yml` — auto-trigger disabled, manuel
  dispatch + nightly schedule kaldı.
- `scripts/docker-smoke-test.sh` — izole `COMPOSE_PROJECT_NAME` export +
  fail-closed drift guard.
- `backend/scripts/doctor-zanzibar.sh` — A21 ve A22 drift guard check'leri.

Arka plan:

- `docker-smoke-test.sh` hem staging runner hem local dev için tasarlandı;
  ancak `COMPOSE_FILE=backend/docker-compose.yml` (name: platform) ile
  canlı staging stack'i ile aynı namespace'te çalışıyordu.
- `trap cleanup EXIT` script çıkışında her durumda
  `docker compose down --volumes --remove-orphans` yapar.
- `workflow_run` auto-trigger `deploy-backend` success olunca smoke'u
  tetikliyordu; smoke fail olduğunda trap canlı stack'i temizliyordu.

Olay zinciri (2026-04-15):

- 08:45:57Z — PR #390 `deploy-backend` success (stack healthy).
- 08:50:56Z — Zanzibar Smoke auto-trigger (run 24445359188).
- 08:51 — `openfga-migrate` exit 1 (fresh DB bekledi, mevcut DB'de çakıştı).
- trap cleanup → `docker compose down --volumes --remove-orphans`.
- `platform` project'in 17 servisi + volume'ları silindi.
- 09:17+ — canlı `/api/*` ve `/realms/*` → 502.

Fix stratejisi: 3 katman defense-in-depth (script izolasyon, workflow
auto-trigger disable, doctor drift guard).

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

3.1 Katman 1 — Script izolasyonu (`scripts/docker-smoke-test.sh`)

```bash
export COMPOSE_PROJECT_NAME="platform-smoke-${GITHUB_RUN_ID:-$$}"

if [[ ! "$COMPOSE_PROJECT_NAME" == platform-smoke-* ]]; then
  echo "::error::SMOKE ISOLATION VIOLATION: ..." >&2
  exit 1
fi
```

Docker Compose v2 priority: env > -p flag > file `name:` key. Script
içinde export edilen `COMPOSE_PROJECT_NAME` `backend/docker-compose.yml`'in
`name: platform` key'ini override eder. Smoke artık `platform-smoke-<id>`
project'inde çalışır; cleanup yalnızca kendi container + volume'larına
etki eder.

3.2 Katman 2 — Workflow auto-trigger disable (`.github/workflows/smoke-zanzibar.yml`)

```yaml
on:
  workflow_dispatch:
    inputs:
      timeout:
        description: 'Smoke test timeout (seconds)'
        default: '120'
  schedule:
    - cron: '30 2 * * *'  # Nightly @ 02:30 UTC
```

Containment phase'de `workflow_run` kaldırıldı. Manuel dispatch ve nightly
schedule ile smoke çalışır; deploy-backend completion otomatik tetiklenme
yapmaz. Katman 1 izolasyon zaten sağlandığı halde, gradual rollout için
extra güvenlik tabakası.

3.3 Katman 3 — Doctor drift guard (`backend/scripts/doctor-zanzibar.sh`)

```
A21. Smoke isolation — docker-smoke-test.sh drift guard
  - COMPOSE_PROJECT_NAME export var mı
  - SMOKE ISOLATION VIOLATION check var mı
A22. Smoke workflow auto-trigger — disabled during containment
  - workflow_run disabled mi
```

Katman 1 ve 2'nin accidentally geri alınmasını yakalar.
`doctor-zanzibar.sh --quick` her worktree'de light mode pre-commit/pre-push
hook içinde, `doctor-zanzibar.sh` (full) CI'da çalışır.

3.4 Restart / rollback

- Restart: Değişiklikler static (workflow yml + bash script + doctor).
  Workflow re-enable için bu runbook §5 kriterlerini izle.
- Rollback (acil): PR #392 revert; smoke auto-trigger geri açılır ama
  incident tekrarlar. Önerilmez. Yerine `scripts/docker-smoke-test.sh`
  izolasyon katmanını güçlendir.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

4.1 PR-ölçekli doğrulama

- [x] `bash -n` syntax PASS (docker-smoke-test.sh, doctor-zanzibar.sh).
- [x] `yaml.safe_load` PASS (smoke-zanzibar.yml).
- [x] `doctor-zanzibar.sh --quick` PASS 61 check / 0 hata / 4 uyarı
  (önceki 58/0/4'ten +3 check: A21×2 + A22×1).
- [x] Local gate chain light mode PASS.

4.2 Integration (stage-backend runner)

- Manuel dispatch: `gh workflow run smoke-zanzibar.yml`
- Run izole project'te çalışır: staging host'ta
  `docker ps --filter name=platform-smoke-*`
- Smoke fail senaryosunda bile canlı `platform` project'i intact.

4.3 Canlı doğrulama (post-merge)

- Manuel dispatch sonrası stage `platform` stack servisleri healthy
  (17 servis).
- Nightly schedule bir kez koşsun; smoke PASS veya fail — her iki
  durumda canlı stack intact.
- Full doctor run PASS (A21 + A22).

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

5.1 Smoke run'ı manuel dispatch ile başladı ama izole project'te çalışmıyor

- `docker-smoke-test.sh` dosyasında `export COMPOSE_PROJECT_NAME="platform-smoke-*"`
  satırı var mı kontrol et (doctor A21).
- Runner env'inde `COMPOSE_PROJECT_NAME="platform"` set edilmiş olabilir;
  script içindeki export unconditional olduğu için override ediyor olmalı.

5.2 Canlı stack tekrar kayboldu (containment sonrası regression)

- `git log backend/scripts/doctor-zanzibar.sh scripts/docker-smoke-test.sh`
  ile son değişiklikleri gör.
- Doctor A21 + A22 fail etti mi?
  `bash backend/scripts/doctor-zanzibar.sh --quick`
- `workflow_run:` satırı `.github/workflows/smoke-zanzibar.yml`'a geri
  eklenmiş olabilir (doctor A22 yakalamalı).

5.3 Re-enable kriterleri (workflow_run auto-trigger geri açma)

Aşağıdaki şartların HEPSİ sağlandığında `workflow_run: [deploy-backend]`
auto-trigger geri açılabilir:

- (a) 3 kez ardışık manuel dispatch smoke PASS (farklı SHA'larda).
- (b) 1 hafta nightly schedule smoke failure'ı canlı stack'i etkilememiş
  (stage host'ta `platform` stack uptime continuous).
- (c) `doctor-zanzibar.sh` full A21 + A22 PASS (regression olmamış).
- (d) Stage deploy + smoke bağımsız test (farklı deploy run'larında).
- (e) Smoke isolation stratejisine uygun idempotent run testi (aynı
  run_id ikinci çağrı namespace collision yapmamalı).

Re-enable PR'ı içerikleri:

- `smoke-zanzibar.yml` `on:` block: `workflow_run` geri eklenir.
- `if:` condition: `github.event.workflow_run.conclusion == 'success'` geri.
- `doctor-zanzibar.sh` A22 check'i soft warn'a çevrilir veya kaldırılır.
- Runbook Status `Active` → `Archived` olur, incident referansı korunur.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

Zanzibar Smoke Test workflow'unun `workflow_run` auto-trigger'ı ve aynı
`platform` compose project'inde çalıştırılması 2026-04-15'te canlı stack'i
yok etti (17 servis + volume'lar). Fix 3 katman defense-in-depth:
(1) script içinde izole `COMPOSE_PROJECT_NAME='platform-smoke-*'`,
(2) workflow auto-trigger geçici disabled (manuel dispatch + nightly
schedule kaldı), (3) doctor A21 + A22 drift guard check'leri. Containment
phase sonrası `workflow_run` geri açma kriterleri §5'te tanımlı.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Incident: 2026-04-15 canlı 502 + 17 servis kayıp.
- Consultation: CNS-20260415-002 (Claude + Codex, APPROVE_WITH_CHANGES,
  158K token).
- PR: #392 `claude/smoke-containment` → main.
- Session handoff: `.claude/plans/session-handoff-20260415-live-recovery.md`.
- Master plan: `.claude/plans/zanzibar-master-plan.md` (rev 20).
- Decision registry: `decisions/topics/zanzibar-openfga.v1.json`
  (D-003 permission-service TRANSFORMED, D-008 hub scope).
- Memory: `feedback_compose_management.md` (tek proje ismi),
  `feedback_infra_stability.md` (compose environment rules).
