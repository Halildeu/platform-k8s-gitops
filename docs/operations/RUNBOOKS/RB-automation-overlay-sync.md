# Runbook — Test-Overlay Digest Sync Otomasyonu (#827 PR-B)

> board #827. Codex design thread `019e4034`, PR-B token-model thread `019e4048`.
>
> **Kapsam**: `deploy-backend-testai.yml` her başarılı 8-servis rollout sonrası,
> k3d-test'te **gerçekten koşan** containerd-resolved pod imageID'lerini
> `kustomize/overlays/test/kustomization.yaml`'a PR-aracılı geri yazar
> (`auto-test-overlay/backend-testai` dalı). Amaç: kayıtlı desired-state'in
> canlı cluster'dan **sessizce drift etmesini** önlemek.
>
> **Roller**: 🧑 = operator (GitHub App + secret seed) · 🤖 = agent/CI (PR aç/güncelle).
>
> **Authentication ≠ merge**: otomasyon PR'ı **açar/günceller**; merge yine
> insan/governance gate'ine bağlıdır (admin-merge YASAK, CI-red merge YASAK).
>
> **#842 Part 2**: aynı `platform-automation` App `auto-promotion/` PR'larını da
> açar (`promotion-bot-scan-candidates.yml` — scheduled prod-candidate scan).
> Bu runbook'taki App kurulumu (ADIM 1-4) her iki otomasyonu da kapsar.

## Neden GitHub App — `GITHUB_TOKEN` değil

`sync-test-overlay-pr` job'ı PR'ı default `GITHUB_TOKEN` ile açarsa, GitHub'ın
**recursion guard**'ı devreye girer: `GITHUB_TOKEN` ile açılan bir PR
`pull_request` workflow'larını **tetiklemez**. Required `cross-ai-audit` check'i
(ve diğer PR check'leri) hiç koşmaz → PR merge edilemez. Bu yüzden PR bir
**GitHub App installation token**'ı ile açılır (`actions/create-github-app-token`).
App'in bot kimliği `platform-automation[bot]`, `#827` automation-PR governance
kontratında (`scripts/ci/pr-cross-ai-audit.mjs` `AUTOMATION_PREFIX_ACTORS`)
`auto-test-overlay/` prefix'ine **bağlı** kimliktir.

## Otomasyon kontratı

| Alan | Değer |
|---|---|
| Tetik | `deploy-backend-testai.yml` → `deploy` job başarılı (8-servis rollout + Gate 1b/1c/1d) |
| Sync job | `sync-test-overlay-pr` (`needs: deploy`, `runs-on: ubuntu-latest`) |
| Dal | `auto-test-overlay/backend-testai` (stabil, her run `origin/main`'e reset) |
| Dosya | `kustomize/overlays/test/kustomization.yaml` — yalnız 8 backend `digest:` satırı |
| PR author | `platform-automation[bot]` (GitHub App) |
| Exemption | cross-AI peer-review **muaf** — `## Cross-AI` automation attestation bloğu |
| Boundary | `[x] state-mutation (test cluster)` — user-approval **değil**, label gerekmez |
| Secrets | `AUTOMATION_APP_ID`, `AUTOMATION_APP_PRIVATE_KEY` (repo Actions secrets) |

**Graceful-skip**: secret'lar yokken `sync-test-overlay-pr` job'ı `preflight`
adımında `enabled=false` üretir → sonraki adımlar atlanır → job **green skip**
(`::notice::` + step summary "operator-disabled" der). CI kırmızı olmaz.

## 🧑 ADIM 1 — GitHub App oluştur

GitHub → Settings → Developer settings → **GitHub Apps** → New GitHub App:

- **Name**: slug'ı `platform-automation`'a çözülecek şekilde (örn. literal
  `platform-automation` veya `Platform Automation`). ⚠️ Slug `pr-cross-ai-audit.mjs`'de
  **hardcoded** — farklı isim → actor check fail.
- **Homepage URL**: repo URL'si (zorunlu alan, herhangi).
- **Webhook**: `Active` işaretini **kaldır** (webhook gerekmez).
- **Repository permissions** (yalnız bunlar — least-privilege):
  - Contents: **Read and write**
  - Pull requests: **Read and write**
  - Metadata: Read-only (otomatik)
- **Where can this App be installed**: Only on this account.

## 🧑 ADIM 2 — App'i repo'ya kur + private key üret

1. App → **Install App** → `platform-k8s-gitops` repo'sunu seç (Only select repositories).
2. App → General → **Private keys** → Generate a private key → `.pem` indir.
3. App ID'yi not al (App → General → About → App ID, numerik).

## 🧑 ADIM 3 — Repo secret'larını seed et

`Halildeu/platform-k8s-gitops` → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Değer |
|---|---|
| `AUTOMATION_APP_ID` | ADIM 2'deki numerik App ID |
| `AUTOMATION_APP_PRIVATE_KEY` | İndirilen `.pem` dosyasının **tam içeriği** (BEGIN/END satırları dahil) |

`.pem` dosyasını seed sonrası **shred** et — `shred -u <file>.pem`.

## 🧑 ADIM 4 — Branch ruleset (önerilen hardening)

`auto-test-overlay/` + `auto-test-frontend/` + `auto-promotion/` branch-prefix'lerinin güçlü bir sinyal
olması için, Settings → Rules → Rulesets → New branch ruleset:

- **Target branches**: `auto-test-overlay/**` · `auto-test-frontend/**` · `auto-promotion/**`
- **Restrict creations / updates**: yalnız `platform-automation` App bypass listesinde.

Bu, bir insanın bu dallara push edip exemption'ı taşıyamamasını garanti eder.
`auto-test-frontend/**` testai frontend desired-state PR'larını
`.github/workflows/deploy-testai.yml` üzerinden açar (#2295). `auto-promotion/**`
aynı `platform-automation` App'iyle açılır (#842 Part 2 —
`promotion-bot-scan-candidates.yml`). `auto-verified/**` ayrı follow-up
(`ledger-mark-verified.sh` staging-sw host-systemd'de koşar — host-minted App
token gerektirir).

## 🤖 ADIM 5 — Verify

`deploy-backend-testai.yml` bir sonraki rollout'unda (`repository_dispatch` veya
`workflow_dispatch`):

```bash
gh workflow run deploy-backend-testai.yml -R Halildeu/platform-k8s-gitops \
  -f sha=<40-char> -f short_sha=<7-char>
```

- `deploy` job yeşil → `sync-test-overlay-pr` job koşar.
- Overlay digest'leri rollout ile **aynıysa** → PR yok (idempotent no-op).
- **Farklıysa** → `auto-test-overlay/backend-testai` PR'ı açılır/güncellenir.
- Auto-PR'da `cross-ai-audit` check'i automation-exemption path'iyle **PASS**.
- Operator PR'ı inceler → CI yeşil → normal squash merge.

Frontend için `platform-web` image build'i `testai-deploy` dispatch'i gönderir:

- `deploy-testai.yml` doğrudan workload mutasyonu yapmaz; App kimliğiyle
  `auto-test-frontend/testai` PR'ını açar/günceller.
- Secret'lar yoksa workflow fail-closed kırmızı olur; eski `kubectl set image`
  yoluna düşmez.
- PR merge edilince `verify-testai-frontend-rollout.yml` merged revision'ı
  ArgoCD üzerinden reconcile eder ve pod digest/public asset/build-info
  lineage gate'lerini çalıştırır.
- Authenticated Meeting davranış smoke'u bu artifact gate'inden ayrıdır.

## Disable / rollback

- **Geçici devre dışı**: `AUTOMATION_APP_ID` + `AUTOMATION_APP_PRIVATE_KEY`
  secret'larını sil → job tekrar graceful-skip eder (CI yeşil kalır).
- **Tam kaldırma**: App installation'ı repo'dan kaldır.
- Açık `auto-test-overlay/backend-testai` PR'ı kapatmak güvenli — bir sonraki
  rollout drift varsa yeniden açar.

## NE YAPMA

- ❌ PR'ı `GITHUB_TOKEN` ile açma — recursion guard `cross-ai-audit`'i bastırır, PR merge-bloklu kalır.
- ❌ App'i `platform-automation` slug'ı dışında bir isimle oluşturma — `pr-cross-ai-audit.mjs` actor check fail eder.
- ❌ App'e `Contents` + `Pull requests` dışında permission verme — least-privilege.
- ❌ App'i bir **insan hesabına** PAT olarak ikame etme — `#827` kontratı bot kimliği ister.
- ❌ Auto-PR'ı admin-merge etme veya CI kırmızıyken merge etme — HARD RULE.
- ❌ `auto-test-overlay/backend-testai` veya `auto-test-frontend/testai` dalını manuel düzenleme — job her run `origin/main`'e reset eder, force-push üzerine yazar.

## Referanslar

- board #827 · Codex thread `019e4034` (design) · `019e4048` (PR-B token-model)
- `.github/workflows/deploy-backend-testai.yml` — `sync-test-overlay-pr` job
- `.github/workflows/deploy-testai.yml` — frontend desired-state-first PR producer
- `.github/workflows/verify-testai-frontend-rollout.yml` — merged frontend pin runtime verifier
- `scripts/automation/sync-test-overlay.sh` — PR aç/güncelle orchestrator
- `scripts/automation/sync-test-overlay-frontend.sh` — frontend PR orchestrator
- `scripts/automation/apply-test-overlay-digests.py` — comment-preserving digest rewrite
- `scripts/ci/pr-cross-ai-audit.mjs` — `auditAutomation` + `AUTOMATION_PREFIX_ACTORS`
- `#827` PR-A (#839) — automation-PR cross-AI exemption kontratı
- ADR-0011 §2.3 — PR boundary declaration class'ları
