# Runbook — Test-Overlay Digest Sync Otomasyonu (#827 PR-B)

> board #827. Codex design thread `019e4034`, PR-B token-model thread `019e4048`.
>
> **Kapsam**: `deploy-backend-testai.yml`, platform-backend'in yayımladığı tam
> 13-servis immutable digest haritasını herhangi bir cluster mutasyonundan
> **önce** `kustomize/overlays/test/kustomization.yaml` için PR'a dönüştürür
> (`auto-test-overlay/backend-testai` dalı). Merge sonrası
> ArgoCD auto-sync, test overlay'deki `sync-wave` desired-state sözleşmesiyle
> Deployment'ları sırayla reconcile eder. `verify-testai-backend-rollout.yml`
> mutasyon yapmadan exact revision convergence ve çalışan pod imageID'lerini
> doğrular.
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

Promotion job'ı PR'ı default `GITHUB_TOKEN` ile açarsa, GitHub'ın
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
| Tetik | platform-backend tam image build → `backend-testai-deploy` dispatch |
| Promotion job | `deploy-backend-testai.yml/promote` (`runs-on: ubuntu-latest`, cluster erişimi yok) |
| Dal | `auto-test-overlay/backend-testai` (stabil, her run `origin/main`'e reset) |
| Dosya | Ana test overlay'de 13 backend `digest:` satırı; endpoint-admin değişirse iki owner-gated bridge mirror satırı |
| PR author | `platform-automation[bot]` (GitHub App) |
| Exemption | cross-AI peer-review **muaf** — `## Cross-AI` automation attestation bloğu |
| Boundary | `[x] state-mutation (test cluster)` — user-approval **değil**, label gerekmez |
| Secrets | `AUTOMATION_APP_ID`, `AUTOMATION_APP_PRIVATE_KEY` (repo Actions secrets) |
| Merge sonrası | ArgoCD auto-sync waves `10..22` → read-only exact revision convergence → exact imageID/edge/readiness/stability |

**Fail-closed**: App secret'ları yoksa promotion kırmızı olur ve açıkça operator
aksiyonu ister. Eski direct rollout veya green-skip yoluna düşmez. Cluster
mutasyonu başlamaz.

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

`deploy-backend-testai.yml` bir sonraki promotion'ında (`repository_dispatch` veya
`workflow_dispatch`):

```bash
gh workflow run deploy-backend-testai.yml -R Halildeu/platform-k8s-gitops \
  -f sha=<40-char> -f short_sha=<7-char> -f digests='<13-service-json-map>'
```

- Payload eksik, kısmi, bilinmeyen servisli veya malformed digest içeriyorsa fail-closed.
- Targeted tek-servis source build build-only'dir; GitOps dispatch üretmez.
- Overlay digest'leri source map ile **aynıysa** → PR yok (idempotent no-op).
- **Farklıysa** → `auto-test-overlay/backend-testai` PR'ı açılır/güncellenir.
- Auto-PR'da `cross-ai-audit` check'i automation-exemption path'iyle **PASS**.
- Operator PR'ı inceler → CI yeşil → normal squash merge.
- Merge sonrası ArgoCD auto-sync, 13 Deployment'ı test overlay'deki benzersiz
  sync-wave'lerle bağımlılık sırasına göre uygular (`auth-service=10`,
  `api-gateway=22`). Workflow ayrıca bir sync operasyonu başlatmaz.
- Runner'da global CLI kurulumuna güvenilmez; `ensure-argocd-cli.sh` ArgoCD
  `v2.13.1` binary'sini OS/architecture allowlist'i ve repoya pinli resmi
  SHA-256 ile doğrular. Doğrulanmamış binary çalıştırılmaz.
- Read-only convergence gate Application'ın exact merge revision'ında `Synced`
  ve `Healthy` durumunu en az iki ardışık poll'da görmesini; `origin/main`
  revision fence'ini; post-gate exact pod imageID, public edge, readiness ve
  2-3 dakikalık stabilite penceresini doğrular. Yeni main gelirse eski koşu
  fail-closed superseded olur.

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
  secret'larını sil → promotion fail-closed olur; cluster mutasyonu yapmaz.
- **Tam kaldırma**: App installation'ı repo'dan kaldır.
- Açık `auto-test-overlay/backend-testai` PR'ı kapatmak güvenli — bir sonraki
  source digest farkında yeniden açar.
- **Runtime rollback**: immutable digest promotion PR'ını Git revert ile geri
  al; aynı post-merge ArgoCD verifier önceki digest setini reconcile eder.

## NE YAPMA

- ❌ PR'ı `GITHUB_TOKEN` ile açma — recursion guard `cross-ai-audit`'i bastırır, PR merge-bloklu kalır.
- ❌ App'i `platform-automation` slug'ı dışında bir isimle oluşturma — `pr-cross-ai-audit.mjs` actor check fail eder.
- ❌ App'e `Contents` + `Pull requests` dışında permission verme — least-privilege.
- ❌ App'i bir **insan hesabına** PAT olarak ikame etme — `#827` kontratı bot kimliği ister.
- ❌ Auto-PR'ı admin-merge etme veya CI kırmızıyken merge etme — HARD RULE.
- ❌ `auto-test-overlay/backend-testai` veya `auto-test-frontend/testai` dalını manuel düzenleme — job her run `origin/main`'e reset eder, force-push üzerine yazar.
- ❌ Auto-sync açıkken workflow'dan `argocd app sync --revision/--resource`
  çalıştırma — Application'ın `main` targetRevision authority'siyle yarışır.

## Referanslar

- board #827 · Codex thread `019e4034` (design) · `019e4048` (PR-B token-model)
- `.github/workflows/deploy-backend-testai.yml` — backend desired-state PR producer
- `.github/workflows/verify-testai-backend-rollout.yml` — merged backend pin runtime verifier
- `.github/workflows/deploy-testai.yml` — frontend desired-state-first PR producer
- `.github/workflows/verify-testai-frontend-rollout.yml` — merged frontend pin runtime verifier
- `scripts/automation/sync-test-overlay.sh` — PR aç/güncelle orchestrator
- `scripts/automation/sync-test-overlay-frontend.sh` — frontend PR orchestrator
- `scripts/automation/apply-test-overlay-digests.py` — comment-preserving digest rewrite
- `scripts/automation/backend-testai-digest-contract.py` — full-map normalization + overlay inspection
- `scripts/deploy/reconcile-testai-backend-sequential.sh` — read-only ArgoCD auto-sync exact-convergence verifier
- `scripts/deploy/ensure-argocd-cli.sh` — pinned + SHA-256 verified ArgoCD CLI bootstrap
- `scripts/deploy/verify-testai-backend-runtime.sh` — exact digest/edge/readiness/stability acceptance
- `scripts/ci/pr-cross-ai-audit.mjs` — `auditAutomation` + `AUTOMATION_PREFIX_ACTORS`
- `#827` PR-A (#839) — automation-PR cross-AI exemption kontratı
- ADR-0011 §2.3 — PR boundary declaration class'ları
