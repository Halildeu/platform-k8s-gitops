# RB-local-merge-deploy-orchestrator – Local SSOT: Merge + Deploy Orchestrator

ID: RB-local-merge-deploy-orchestrator  
Service: ops-local  
Status: Draft  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

Local SSOT prensibiyle PR’ı uçtan uca sonuçlandırmak:
- PR varsa bul / yoksa aç
- CI FAIL ise log çek → local fix → push
- CI PASS ise merge’i tetikle (bot veya direct)
- Deploy/validate/rollback GitHub Actions’ta çalışsın ama local’den tetiklenebilsin
- Tüm kanıt (log/digest) localde toplansın

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Repo: `Halildeu/platform-ssot`
- Local orchestrator:
  - `scripts/ops/local_merge_deploy_orchestrator.sh`
- CI log + digest:
  - PR CI: `scripts/ci_pull_logs.sh` (autopilot içinde çağrılır)
  - Deploy chain: `scripts/ops/ci_pull_deploy_chain_logs.sh`
  - Tek run: `scripts/ops/gh_pull_run_logs.sh`
- Git push credential stabilizasyonu:
  - `scripts/ops/git_setup_push_auth.sh`
- Not: Deploy/validate/rollback workflow’ları GitHub Secrets üzerinden çalışır; Vault “login” GitHub-hosted runner’da yapılmaz.

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

### 3.1 Ön koşullar (kopyasız auth)

Canonical local gate entry points:
- Local gate adı: `local-gate-chain`
- Runner: `scripts/run_local_gate_chain.sh`
- Guard: `scripts/require_local_gate.sh`
- Hook installer: `scripts/setup_local_git_hooks.sh`
- Hook enforce: `.githooks/pre-commit`, `.githooks/pre-push`
- PASS artifact: `.cache/reports/local-gate-chain/status.json`

1) GH auth (SSOT):
- `bash scripts/ops/gh_token_preflight.sh` PASS olmalı (kopyasız; token yazdırılmaz).
- Opsiyonel (persist login): `bash scripts/ops/gh_auth_with_token.sh`

2) Git push auth (autopilot push stabil olsun):
- `bash scripts/ops/git_setup_push_auth.sh`

3) Local gate zorunlu:
- `bash scripts/setup_local_git_hooks.sh`
- `bash scripts/run_local_gate_chain.sh`
- Canonical PASS artifact:
  - `.cache/reports/local-gate-chain/status.json`
- Not:
  - `pre-commit` ve `pre-push` hook’ları stale/missing artifact halinde
    `scripts/require_local_gate.sh --auto-run` çağırır.
  - `NVD_API_KEY` shell env’de yoksa local security zinciri repo `.env/.env.local`
    dosyalarından allowlist ile yüklemeyi dener; değer loglanmaz.

### 3.2 Orchestrator (manual fix)

CI fail olursa script durur ve `FAILURE.md` üretir; fix’i sen yaparsın, sonra aynı komutu tekrar çalıştırırsın.

- `bash scripts/ops/local_merge_deploy_orchestrator.sh --fix-mode manual`

Kanıt:
- `artifacts/ci-logs/pr-<PR>/FAILURE.md`

Merge kuralı (SSOT):
- Varsayılan: merge kararı **Merge Bot** (label gate + checks) ile verilir.
- Orchestrator direct merge fallback’i **varsayılan kapalıdır**.
  - Break-glass: `--allow-direct-merge` (veya `export ALLOW_DIRECT_MERGE=1`) ile explicit açılır.

Merge Bot dispatch fallback (önerilen, varsayılan açık):
- Orchestrator `MERGE_WAIT_SEC` boyunca Merge Bot’un merge yapmasını bekler.
- PR hâlâ merged değilse ve `MERGE_BOT_DISPATCH=1` ise `pr-merge.yml` workflow’unu `workflow_dispatch` ile tetikler:
  - inputs: `pr_number=<PR>` + `confirm=MERGE`
  - `MERGE_BOT_DISPATCH_WAIT_SEC` kadar sonucu gözler.
- Bu fallback label gate / checks kurallarını bypass etmez; Merge Bot aynı gate’leri uygular.
- Disable: `export MERGE_BOT_DISPATCH=0`

### 3.3 Orchestrator (auto fix – opsiyonel)

Local autopilot fix komutu ile loop:
- `bash scripts/ops/local_merge_deploy_orchestrator.sh --fix-mode auto --fix-cmd "bash scripts/codex_fix_runner.sh"`

### 3.4 Deploy tetikleme (local → GitHub Actions)

Varsayılan: merge sonrası push-trigger deploy’ları bekler; run görünmezse `workflow_dispatch` ile tetikler.

Zorla workflow_dispatch:
- `bash scripts/ops/local_merge_deploy_orchestrator.sh --deploy dispatch`

Deploy skip:
- `bash scripts/ops/local_merge_deploy_orchestrator.sh --deploy skip`

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Local CI kanıtı:
  - `artifacts/ci-logs/pr-<PR>/FAILURE.md`
  - `artifacts/ci-logs/run-<RUN_ID>/DIGEST.md`
- Deploy chain raporu:
  - `artifacts/ci-logs/main-<SHA7>/DEPLOY-CHAIN.md`
- PR/Run URL’leri:
  - `gh pr view --repo <owner/repo> --head <branch>`
  - `gh run list --repo <owner/repo> --branch main --limit 20`

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – gh auth yok:
  - Given: `gh api rate_limit` FAIL (token yok/çalışmıyor)  
    When: orchestrator çalışır  
    Then: durur → çözüm:
    - `bash scripts/ops/gh_token_preflight.sh` (GH_TOKEN/GITHUB_TOKEN/Vault pointer) veya
    - `bash scripts/ops/gh_auth_with_token.sh` (persist login)

- [ ] Arıza senaryosu 2 – git push fail:
  - Given: `autopilot_local.sh` push aşamasında hata verir  
    When: fix commit üretildi  
    Then: PR güncellenmez → çözüm:
    - `bash scripts/ops/git_setup_push_auth.sh`
    - (SSH kullanıyorsan) ssh-agent/keychain kontrolü

- [ ] Arıza senaryosu 3 – CI FAIL (manual fix):
  - Given: `ci-gate` FAIL  
    When: `--fix-mode manual` ile orchestrator çalışır  
    Then: `artifacts/ci-logs/pr-<PR>/FAILURE.md` üretilir → fix yap → tekrar çalıştır.

- [ ] Arıza senaryosu 4 – mergeable_state=behind:
  - Given: PR behind/out-of-date  
    When: orchestrator merge dener  
    Then: merge durur → çözüm:
    - `git fetch origin && git merge origin/main && git push`

- [ ] Arıza senaryosu 5 – deploy chain görünmüyor:
  - Given: web/backend değişti ama deploy run yok  
    When: orchestrator deploy bekler  
    Then: fallback olarak `workflow_dispatch` tetikler (deploy-web/deploy-backend).

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Local SSOT: hata analizi ve fix localde; GitHub Actions sadece deterministic executor.
- Git öncesi zorunlu eşik: local gate PASS artifact’i olmadan commit/push yok.
- Merge bot GitHub’da kalabilir; local orchestrator gerektiğinde merge/deploy tetikler.
- Kanıtlar localde: `artifacts/ci-logs/**`.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Runbook template: `docs/99-templates/RUNBOOK.template.md`
- Flow SSOT: `docs/04-operations/RUNBOOKS/RB-insansiz-flow.md`
- Script: `scripts/autopilot_local.sh`
- Script: `scripts/ci_pull_logs.sh`
- Script: `scripts/ops/local_merge_deploy_orchestrator.sh`
- Script: `scripts/ops/ci_pull_deploy_chain_logs.sh`
- Script: `scripts/ops/gh_pull_run_logs.sh`
- Script: `scripts/ops/git_setup_push_auth.sh`
