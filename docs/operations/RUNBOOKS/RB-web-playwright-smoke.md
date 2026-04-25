# RUNBOOK – Playwright Headless Smoke (Console/Network)

ID: RB-web-playwright-smoke  
Service: web-playwright-smoke  
Status: Draft  
Owner: Frontend

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Web uygulamasında kritik sayfalar için hızlı “smoke” kontrolü yapmak.
- console/pageerror/xhr‑fetch hatalarını telemetry ile toplayıp raporlamak.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Kapsam: `web/tests/playwright/pw_scenarios.yml` içindeki seviye 1/2 senaryoları.
- Ortam: Lokal dev (app çalışıyor olmalı) ve CI.
- Çıktı: Senaryo ve özet raporları `web/test-results/pw/` altında üretilir.

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Ön koşul:
  - Shell çalışıyor olmalı (`http://localhost:3000` varsayılan).
  - Playwright browser’ları yüklü olmalı (`npx playwright install`).

- Çalıştırma:
  - Seviye 1 (hızlı): `pnpm -C web run pw:ci`
  - Seviye 1+2 (geniş): `pnpm -C web run pw:nightly`

- Konfigürasyon (opsiyonel):
  - Base URL override: `PW_BASE_URL=http://localhost:3000`
  - Senaryo dosyası override: `PW_TARGETS=tests/playwright/pw_scenarios.yml`
  - Rule of thumb (mock gate):
    - Ne zaman: Backend/gateway erişimi olmadığı için auth-required smoke senaryoları flaky ise.
    - Neden: Telemetry `requestfailed/5xx` false-negative üretir ve smoke sinyalini bozar.
    - Nasıl: `PW_MOCK_API` default `0`; sadece gerekli GET endpoint’leri için `PW_MOCK_API=1` aç (mock’lar `x-pw-mocked=1`).
    - Örnek (public): `PW_MOCK_THEME_REGISTRY=1 PW_MOCK_API=0 pnpm -C web run pw:nightly --grep shell_login`
    - Örnek (auth): `PW_MOCK_THEME_REGISTRY=1 PW_MOCK_API=1 PW_AUTH_MODE=token_injection PW_TEST_TOKEN=... pnpm -C web run pw:nightly --grep story_0050_locale_switch_propagation`

- Durdurma:
  - Test süreci (`playwright test`) sonlandırılır (Ctrl+C).

-------------------------------------------------------------------------------
3.1 FAZ 3 NIGHTLY (SCHEDULE PASİF, MANUEL AKTİF)
-------------------------------------------------------------------------------

- Nightly workflow: `.github/workflows/web-playwright-nightly.yml`
  - Schedule tetikleyici varsayılan olarak PASİF:
    - `vars.ENABLE_PW_NIGHTLY=true` değilse job otomatik koşmaz (SKIP).
  - Manuel tetik (`workflow_dispatch`) her zaman aktiftir:
    - `base_url` girilirse onu kullanır, boşsa `secrets.PLAYWRIGHT_BASE_URL` kullanır.

- Hafta 1 (soft mode, auth yok):
  - `PW_SOFT_MODE=1`
  - `PW_AUTH_MODE=none`
  - `PW_READONLY_ENFORCE=0`

- Hafta 2 (soft mode, readonly + token injection başlangıcı):
  - `PW_READONLY_ENFORCE=1` (readonly ihlalleri raporlanır, gate edilmez)
  - `PW_AUTH_MODE=token_injection` (önce manuel koşumda `PW_TEST_TOKEN` ile)

-------------------------------------------------------------------------------
3.2 VAULT → GITHUB SECRETS SYNC (MANUEL)
-------------------------------------------------------------------------------

- Amaç: Vault SSOT’taki Playwright config değerlerini GitHub Actions secrets’a senkronize etmek.
- Workflow: `.github/workflows/vault-secrets-sync.yml`

- Önkoşullar (GitHub secrets):
  - `GH_SECRETS_SYNC_TOKEN` (PAT): repo secrets update izni olmalı (GITHUB_TOKEN bunu yapamaz).
  - Self-hosted runner (label: `vault-local`) Vault’a erişebilmeli.
  - Vault token (header): `VAULT_ADDR`, `VAULT_TOKEN`

- Vault KV v2 varsayılan path/key’ler (value yok):
  - `secret/<env>/web-playwright/config`:
    - `PLAYWRIGHT_BASE_URL`
    - `PW_REAL_USER_EMAIL` (opsiyonel; `authz-zanzibar` suite için önerilir)
    - `PW_REAL_USER_PASSWORD` (opsiyonel; `authz-zanzibar` suite için zorunlu)
  - `secret/<env>/web-playwright/keycloak`:
    - `KEYCLOAK_TOKEN_URL`
    - `KEYCLOAK_CLIENT_ID`
    - `KEYCLOAK_CLIENT_SECRET`
    - `KEYCLOAK_SCOPE` (opsiyonel)

- Çalıştırma:
  - Actions → “Vault → GitHub Secrets Sync (Manual)”
  - `env=stage` için default path’ler:
    - `stage/web-playwright/config`
    - `stage/web-playwright/keycloak`
  - Vault path boşsa önce aynı workflow’da `mode=seed-web-playwright` çalıştır:
    - `playwright_base_url` zorunludur.
    - `pw_real_user_email` opsiyoneldir.
    - `KEYCLOAK_*` değerleri mevcut GitHub repo secret’larından seed edilir.
  - Önce `dry_run=true` ile sadece FOUND/MISSING key listesini doğrula.
  - Sonra `dry_run=false` ile GitHub secrets’ları güncelle.

- Rotasyon sonrası önerilen sıra:
  1) `vault-secrets-sync` (dry_run=true)
  2) `vault-secrets-sync` (dry_run=false)
  3) `.github/workflows/web-playwright-nightly.yml` (workflow_dispatch) ile koşumu doğrula

- `authz-zanzibar` suite notu:
  - Restricted-user smoke çalıştırılacaksa `secret/<env>/web-playwright/config`
    altında `PW_REAL_USER_PASSWORD` tanımlı olmalıdır.
  - `PW_REAL_USER_EMAIL` boş bırakılırsa varsayılan kullanıcı
    `user3@example.com` kabul edilir.

-------------------------------------------------------------------------------
3.3 LOCAL INTEGRATION NIGHTLY (SELF-HOSTED)
-------------------------------------------------------------------------------

- Workflow: `.github/workflows/web-playwright-local-nightly.yml`
  - Amaç: “staging olmadan” localhost üzerinde nightly integration e2e çalıştırmak.
  - Self-hosted runner üzerinde çalışır (label: `vault-local`).
  - Job kendi içinde backend docker-compose + web MFE’leri ayağa kaldırır, Playwright koşar, sonra cleanup yapar.

- Planlama (cron):
  - GitHub Actions cron UTC’dir.
  - 02:30 Türkiye (UTC+3) için: `23:30 UTC` (`30 23 * * *`).

- Operasyon notları:
  - Runner’ın (Mac) uykuya geçmemesi gerekir (Energy settings).
  - Artefact’lar:
    - `web/test-results/pw/**` (pw-summary dahil)
    - `web/test-results/ops/**` (MFE log/pid dosyaları dahil)

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Raporlar:
  - Senaryo raporları: `web/test-results/pw/pw-scenario-*.md`
  - Özet raporu: `web/test-results/pw/pw-summary-*.md`

- FAIL kriterleri (default):
  - Uncaught exception (`pageerror`)
  - Allowlist hariç `console.error`
  - Allowlist hariç xhr/fetch `requestfailed`
  - Allowlist hariç xhr/fetch `5xx`
  - `auth_required: true` senaryolarda allowlist/matrix hariç `401/403`

- WARN kriterleri (default):
  - Allowlist hariç `console.warn`
  - `auth_required: false` senaryolarda allowlist/matrix hariç `401/403`

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – console.error FAIL
  - Given: `pw:ci` çalıştırıldı
  - When: raporda `console.error` görünüyor
  - Then:
    - İlgili senaryo raporunu aç: `web/test-results/pw/pw-scenario-<name>-<ts>.md`
    - Hata mesajının geçtiği sayfayı lokal aç ve reproducer çıkar.
    - Eğer hata “beklenen gürültü” ise allowlist’e ekle:
      - `web/tests/playwright/pw_scenarios.yml` → `defaults.console_error_allowlist`

- [ ] Arıza senaryosu 2 – Network 5xx FAIL
  - Given: Senaryo raporunda `xhr/fetch 5xx` var
  - When: endpoint 500 dönüyor
  - Then:
    - Backend log’larını kontrol et ve endpoint hatasını düzelt.
    - Eğer belirli bir endpoint geçici olarak hariç tutulacaksa allowlist’e ekle:
      - `web/tests/playwright/pw_scenarios.yml` → `defaults.network_allowlist`

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Senaryolar YAML’den yönetilir; hızlı smoke için seviye 1 senaryolar tercih edilir.
- Telemetry raporları hata türlerine göre “FAIL/WARN” kararını üretir.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Senaryo listesi: `web/tests/playwright/pw_scenarios.yml`
- Runner: `web/tests/playwright/scenario-runner.spec.ts`
- Telemetry: `web/tests/playwright/utils/pw_telemetry.ts`
- CI workflow: `.github/workflows/web-playwright-smoke.yml`
  - `env=stage` seçilirse smoke koşusu self-hosted `stage-backend` runner üzerinde çalışır ve `stage` environment secret'larını kullanır.
  - `env=prod` seçilirse smoke koşusu GitHub-hosted runner üzerinde çalışır ve ilgili environment secret'larını kullanır.
