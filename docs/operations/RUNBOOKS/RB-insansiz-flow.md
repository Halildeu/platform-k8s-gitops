# RB-insansiz-flow – İnsansız Akış (PR Bot → ci-gate → log-digest → Local Autopilot → Merge Bot → Deploy → Validate → Rollback)

ID: RB-insansiz-flow  
Service: github-actions  
Status: Draft  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- İnsan müdahalesi olmadan (insansız) PR akışını deterministik hale getirmek:
  - Push → PR oluştur/güncelle (PR Bot)
  - Tek required check: `ci-gate`
  - FAIL → otomatik failure digest (log-digest) + local autopilot (lokalde fix)
  - PASS → label gate ile otomatik squash merge (PR Merge Bot)
  - Merge → main deploy (web/backend) + post-deploy validate
  - Validate FAIL → rollback + incident kaydı
  - Sonuç: PR Conversation’da marker’lı tek comment’lerle izlenebilirlik

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Repo: `Halildeu/platform-ssot`
- Branch scope:
  - `docs/**`, `fix/**` → `merge_policy=bot_squash` (insansız merge adayı)
  - `wip/**` → draft (merge kapalı)
  - `ops/**` → default `merge_policy=none` (merge kapalı)
- SSOT kaynakları:
  - OPO authority map: `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`
  - Managed standards lock: `standards.lock`
  - Multi-repo operating contract: `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md`
  - Flow: `docs/03-delivery/PROJECT-FLOW.tsv` (+ render: `docs/03-delivery/PROJECT-FLOW.md`)
  - Doc maturity rubric: `DOC-MATURITY-RUBRIC.md` (transition-active, non-blocking rapor)
  - Semantic lint lexicon: `DOC-SEMANTIC-LINT-LEXICON.md` (transition-active, local-only, non-blocking)
  - Semantic lint script: `scripts/check_doc_semantic_lint.py` (local-only rapor)
  - ID rezervasyonu: `docs/03-delivery/ID-REGISTRY.tsv`
    - Kural: Yeni STORY başlamadan önce ilgili `STORY/AC/TP` NUM (XXXX) bu registry’de rezerve edilir.
  - Delivery zinciri: `docs/03-delivery/STORIES/`, `docs/03-delivery/ACCEPTANCE/`, `docs/03-delivery/TEST-PLANS/`
  - PR bot kuralları: `docs-ssot/04-operations/PR-BOT-RULES.json`
  - Runbook’lar: bu doküman + `RB-pr-bot` + `RB-log-digest`
- Kapsam dışı:
  - Fork repo’larda otomasyon (güvenlik nedeniyle çalışmaz).
  - Branch rules “required reviews” gibi manuel onay gerektiren policy’ler (insansız merge’i bloklar).
  - Prod deploy hedeflerinin detayları (hook/ssh/runner) secrets ile yönetilir.
    - `DEPLOY_ENABLED=true` iken gerekli deploy/validate parametreleri eksikse workflow FAIL eder (silent PASS yok).
    - `DEPLOY_ENABLED!=true` ise deploy/validate job’ları **skip** olur.

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Doğal akış (otomatik):
  1) Branch’e push yapılır.
  2) PR Bot:
     - PR yoksa `main`’e PR açar; varsa günceller.
     - `<!-- pr-bot:rules -->` marker comment’ini upsert eder (spam yok).
     - (merge adayı ise) `pr-bot/ready-to-merge` label’ını best-effort ekler.
  3) `ci-gate`:
     - PR’da always-run çalışır ve tek required check sinyali olarak kullanılır.
  4) FAIL ise:
     - log-digest workflow’u tetiklenir ve `<!-- log-digest:v1 -->` comment’ini upsert eder.
     - Local autopilot devreye alınır: `scripts/ci_pull_logs.sh` → `scripts/autopilot_local.sh`.
       - Varsayılan: sadece required check’leri izler (`ci-gate`).
       - Opsiyonel (any-fail): `AUTOPILOT_ANY_FAIL=1` ile **herhangi bir failing check** fix döngüsünü tetikler.
       - Codex dispatcher: `AUTOPILOT_FIX_CMD="bash scripts/codex_fix_runner.sh"` (allowlist + limit guardrails).
       - Opsiyonel (local-only): `AUTOPILOT_SEMANTIC_LINT=1` ile semantic lint raporu üretir (`.autopilot-tmp/doc-lint/`).
       - Opsiyonel (local-only): Queue + Orchestrator (tek worker, idle-no-query)
         - Queue: `.autopilot-tmp/queue/queue.tsv` (gitignored)
         - Lock: `.autopilot-tmp/locks/autopilot.lock`
         - Queue add/list: `python3 scripts/autopilot_queue.py add --pr 53 --reason "ci-gate fail"` / `python3 scripts/autopilot_queue.py list`
         - Orchestrator: `python3 scripts/autopilot_orchestrator.py --repo Halildeu/platform-ssot --max-attempts 5 --semantic --fix-cmd "bash scripts/codex_fix_runner.sh"`
         - Tracker Watch + Orchestrator Scan:
           - Terminal-1: `python3 scripts/pr_tracker_tsv.py sync --watch 30`
           - Terminal-2: `python3 scripts/autopilot_orchestrator.py --repo Halildeu/platform-ssot --scan-tracker --tracker-path .autopilot-tmp/pr-tracker/PR-TRACKER.tsv --scan-interval 30 --max-attempts 5 --semantic --fix-cmd "bash scripts/codex_fix_runner.sh"`
           - Not: idle-no-query korunur; GitHub sorgusu yalnız tracker watch ve autopilot_local çalışırken yapılır.
       - Local Ops Start/Stop (tek komut, UI yok):
         - Start: `bash scripts/ops/local_ops_start.sh`
         - Status: `bash scripts/ops/local_ops_status.sh`
         - Stop: `bash scripts/ops/local_ops_stop.sh`
  5) PASS ise:
     - PR Merge Bot workflow’u tetiklenir, label gate + checks yeşil ise squash merge dener.
     - `<!-- pr-merge:result -->` comment’i sonucu yazar (merged/noop + reason + run link).
     - Eğer workflow_run tetiklenmezse: local orchestrator `pr-merge.yml` için `workflow_dispatch` ile Merge Bot’u “kick” edebilir; direct merge yalnız break-glass (`--allow-direct-merge`).
  6) Merge sonrası (push main):
     - Web değiştiyse: `deploy-web` çalışır (**DEPLOY_ENABLED=true** ise; aksi halde job skip).
     - Backend değiştiyse: `deploy-backend` çalışır (**DEPLOY_ENABLED=true** ise; aksi halde job skip).
  7) Deploy sonrası:
     - `post-deploy-validate` çalışır (**DEPLOY_ENABLED=true** ise; aksi halde job skip).
     - FAIL ise `rollback` tetiklenir ve `<!-- incident:v1 -->` comment’i basar.

  - Durdurma / kill switch:
  - Workflow disable:
    - `.github/workflows/pr-bot.yml`
    - `.github/workflows/ci-gate.yml`
    - `.github/workflows/log-digest.yml`
    - `.github/workflows/auto-fix.yml` (local SSOT policy nedeniyle disabled)
    - `.github/workflows/pr-merge.yml`
    - `.github/workflows/deploy-web.yml`
    - `.github/workflows/deploy-backend.yml`
    - `.github/workflows/post-deploy-validate.yml`
    - `.github/workflows/rollback.yml`
  - Merge’i kapat (SSOT): `docs-ssot/04-operations/PR-BOT-RULES.json` içinde ilgili `match` için `merge_policy=none`.
  - Secrets kill switch (önerilen):
    - `DEPLOY_ENABLED` (true/false)
    - `ROLLBACK_ENABLED` (true/false)
    - Kaynak: Vault KV v2 (SSOT) → GitHub Secrets (Actions) sync: `.github/workflows/vault-secrets-sync.yml` (`mode=killswitch`).
    - Değer formatı: string `"true"` / `"false"` (hardening uyumu).
  - Parametre zorunluluğu (hardening):
    - `DEPLOY_ENABLED=true` iken:
      - Web deploy için `WEB_DEPLOY_HOOK_URL` zorunludur (yoksa `deploy-web` FAIL).
      - Post-deploy validate için `WEB_SMOKE_URL` ve `BACKEND_HEALTH_URLS` zorunludur (yoksa `post-deploy-validate` FAIL).
    - `ROLLBACK_ENABLED=true` iken:
      - `WEB_ROLLBACK_HOOK_URL` ve `BACKEND_ROLLBACK_HOOK_URL` zorunludur (yoksa `rollback` FAIL).

-------------------------------------------------------------------------------
3.1 LOCAL SSOT POLICY (MANDATORY)
-------------------------------------------------------------------------------

- Fix/patch yalnızca **local** ortamda üretilir (Codex).
- GitHub Actions hiçbir koşulda fix commit’i üretmez.
- CI fail durumunda kullanılacak tek mekanizma:
  - `scripts/ci_pull_logs.sh`
  - `scripts/autopilot_local.sh`
- Merge otomatik (Merge Bot) kalır.
- Local orchestrator (SSOT): `scripts/ops/local_merge_deploy_orchestrator.sh`
  - Amaç: PR/CI kanıtı toplamak, local fix-loop’u çalıştırmak ve deploy/validate/rollback zinciri loglarını localde çekmek.
  - Kural: varsayılan merge kararı bot’tur; direct merge fallback **varsayılan kapalıdır** (break-glass: `--allow-direct-merge`).
- `log-digest` sadece teşhis (digest) yazar.
- Örnek token export (değer loglanmaz):
  - `export GH_TOKEN="$(vault kv get -field=GH_SECRETS_SYNC_TOKEN 'secret/stage/ops/github')"`
  - Not: gerçek Vault path kurumunuzdaki SSOT’a göre değişebilir.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Operasyonel kanıtlar (PR Conversation):
  - `<!-- pr-bot:rules -->`: PR Bot çalıştı + rule/template uygulandı.
  - `<!-- log-digest:v1 -->`: FAIL için “ilk hata bloğu” çıkarıldı (comment upsert, spam yok).
  - `<!-- pr-merge:result -->`: Merge Bot sonucu (merged/noop + reason).
  - `<!-- incident:v1 -->`: Deploy/validate sonrası rollback/incident kaydı (best-effort).
- Ek kanıtlar:
  - PR checks: `ci-gate` (required check).
  - GitHub Actions “Step Summary” (PR Bot / PR Merge Bot).
- PR takip (TSV, local):
  - Dosya: `.autopilot-tmp/pr-tracker/PR-TRACKER.tsv` (gitignored; Local SSOT).
  - Komutlar:
    - `python3 scripts/pr_tracker_tsv.py add --pr <N>`
    - `python3 scripts/pr_tracker_tsv.py sync`
    - `python3 scripts/pr_tracker_tsv.py sync --watch 60`
    - `python3 scripts/pr_tracker_tsv.py report --out .autopilot-tmp/pr-tracker/STATUS.md`
  - Token: `GH_TOKEN` (öneri: Vault field `GH_LOCAL_AUTOPILOT_TOKEN`).
  - v0.3 teşhis kolonları (özet): `DRAFT`, `MERGEABLE_STATE`, `MERGE_POLICY`, `READY_LABEL`, `FAIL_WORKFLOWS`, `NEXT_ACTION`.
  - `NEXT_ACTION`: `DRAFT` / `RESOLVE_CONFLICTS` / `WAIT_CI_GATE` / `FIX_CI` / `POLICY_NO_MERGE` / `ADD_READY_LABEL` / `FIX_OTHER_FAIL` / `WAIT_MERGEABLE` / `READY`.
- Minimum metrikler (manuel gözlem):
  - `ci-gate` success rate
  - “time-to-merge”: `ci-gate` PASS → squash merge

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

Edge-case tablosu (v0.1):

| Durum | Belirti | Beklenen comment | Tek satır aksiyon |
|---|---|---|---|
| Missing label | `<!-- pr-merge:result -->` → `noop (missing ready label)` | pr-merge result comment | `pr-bot/ready-to-merge` label ekle → `ci-gate` rerun |
| Behind / out-of-date | `noop (mergeable_state=behind)` veya PR “Update branch” uyarısı | pr-merge result comment | PR → Update branch → `ci-gate` rerun |
| Merge bot tetiklenmedi | `ci-gate` PASS ama merge olmuyor / pr-merge sonucu yok | (comment yok) | Local orchestrator ile `pr-merge.yml` `workflow_dispatch` (inputs: `pr_number`, `confirm=MERGE`) |
| Cancelled run | log-digest comment içinde “run cancelled” notu | log-digest comment | İlgili check’i rerun et; asıl FAIL run linkinden doğrula |
| Local policy | Auto-fix workflow disabled | (comment yok) | Local autopilot kullan |
| Deploy disabled | Deploy job’ları skip | (comment yok) | `DEPLOY_ENABLED=true` ayarla |
| Validate FAIL | rollback workflow tetiklenir | `<!-- incident:v1 -->` | Hedef URL/secrets kontrol et; ardından deploy/validate rerun |

- [ ] Arıza senaryosu 1 – Ready label eksik:
  - Given: PR `merge_policy=bot_squash` kapsamında ama label yok.  
    When: PR Merge Bot `noop (missing ready label)` döner.  
    Then:
    - PR Bot’un `issues: write` permission’ını kontrol et.
    - Gerekirse label’ı manuel ekle ve `ci-gate` rerun et.

- [ ] Arıza senaryosu 2 – PR behind/out-of-date:
  - Given: PR açık ama `mergeable_state=behind`.  
    When: PR Merge Bot merge denemez (noop).  
    Then: PR’da “Update branch” yap ve `ci-gate` rerun et.

- [ ] Arıza senaryosu 3 – Cancelled run / log download yok:
  - Given: workflow_run `cancelled`.  
    When: log-digest “logs not downloaded” notu basar.  
    Then: İlgili check’i rerun et; yeni FAIL run üzerinden digest üretilecektir.

- [ ] Arıza senaryosu 4 – Checks not green:
  - Given: `ci-gate` PASS değil veya başka check-run’lar kırmızı.  
    When: PR Merge Bot `noop (checks not green)` döner.  
    Then: Kırmızı check’i düzelt; PR’da `ci-gate` rerun et.

- [ ] Arıza senaryosu 5 – Local autopilot:
  - Given: `ci-gate` FAIL var.  
    When: Local autopilot çalıştırılmadı.  
    Then:
    - `log-digest` comment’inden “ilk hata bloğu”nu al.
    - `scripts/ci_pull_logs.sh` ile `FAILURE.md` üret.
    - `scripts/autopilot_local.sh` ile fix döngüsünü sürdür.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Tek required check: `ci-gate`.
- FAIL görünürlüğü: `<!-- log-digest:v1 -->` + local autopilot (lokalde fix).
- PASS + label gate: Merge Bot squash merge; sonuç `<!-- pr-merge:result -->`.
- Merge sonrası: deploy → validate → rollback (kill-switch ile; incident marker: `<!-- incident:v1 -->`).

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- SSOT: docs-ssot/04-operations/PR-BOT-RULES.json
- Runbook: docs/04-operations/RUNBOOKS/RB-pr-bot.md
- Runbook: docs/04-operations/RUNBOOKS/RB-log-digest.md
- Workflow: .github/workflows/pr-bot.yml
- Workflow: .github/workflows/ci-gate.yml
- Workflow: .github/workflows/pr-merge.yml
- Workflow: .github/workflows/log-digest.yml
- Workflow: .github/workflows/auto-fix.yml
- Workflow: .github/workflows/deploy-web.yml
- Workflow: .github/workflows/deploy-backend.yml
- Workflow: .github/workflows/post-deploy-validate.yml
- Workflow: .github/workflows/rollback.yml
- Script: scripts/ci_pull_logs.sh
- Script: scripts/autopilot_local.sh
- Runbook: docs/04-operations/RUNBOOKS/RB-local-merge-deploy-orchestrator.md
- Script: scripts/ops/local_merge_deploy_orchestrator.sh
- Script: scripts/ops/ci_pull_deploy_chain_logs.sh
- Script: scripts/ops/gh_pull_run_logs.sh
- Script: scripts/ops/git_setup_push_auth.sh
- OPO authority map: docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md
- Handbook: DOC-MATURITY-RUBRIC.md (transition-active)
- Script: scripts/check_doc_maturity_rubric.py
- Handbook: DOC-SEMANTIC-LINT-LEXICON.md (transition-active)
- Script: scripts/check_doc_semantic_lint.py
- STORY: docs/03-delivery/STORIES/STORY-0302-release-deploy-e2e-v0-1.md
- ACCEPTANCE: docs/03-delivery/ACCEPTANCE/AC-0302-release-deploy-e2e-v0-1.md
- STORY: docs/03-delivery/STORIES/STORY-0303-autopilot-auto-fix-deploy-rollback-v0-1.md
- ACCEPTANCE: docs/03-delivery/ACCEPTANCE/AC-0303-autopilot-auto-fix-deploy-rollback-v0-1.md
- TEST-PLAN: docs/03-delivery/TEST-PLANS/TP-0303-autopilot-auto-fix-deploy-rollback-v0-1.md
- Related: docs/03-delivery/STORIES/STORY-0304-autopilot-auto-fix-deploy-rollback-v0-1.md
