# Session Handoff — 2026-05-17 (Session 68) — Q3/Q4 prod GitOps landed; kalıcı prod-deploy mimarisi (Codex 6-PR planı) sıradaki

> Format: D28 5-alan + sıradaki agent aksiyon listesi
> Önceki handoff: `session-handoff-2026-05-17-session-67-extracttables-q3-q4-complete.md`
> Codex thread'ler: Q4 current-state delta `019e359e`, prod promotion + 6-PR mimari planı `019e35d1`

---

## 1. Bağlam

Session 67 handoff'u (#747) `schema-service` extractTables Q3+Q4'ün source +
GitOps desired-state tarafının landed olduğunu, Q4 canlı re-verify + cluster
recovery'nin kaldığını devretti.

Bu session (68) devam etti:
- **Cluster gerçeği netleşti**: lokal `k3d-test`/`k3d-prod` stale/non-canonical
  bulundu; kullanıcı `feedback_local_dev_only.md` kuralını ekledi (lokalde
  sadece `k3d-dev`; gerçek pre-prod/prod **sunucuda** — staging-sw). Lokal
  prod/test cluster'lar silindi.
- **Senkronizasyon doğrulandı**: schema-service Q4 sunucu `k3d-test`'te canlı
  (GitOps test overlay ↔ sunucu birebir); prod kasıtlı eski digest'te.
- **current-state.md Q4 delta** (#748) — canonical truth doc P0+P1+Q3+Q4 LIVE.
- **Q3/Q4 prod promotion** (#749) — prod overlay desired-state Q4'e taşındı.

#749'un canlı prod rollout adımı, prod-deploy mekanizmasının **yapısal
eksikliğini** ortaya çıkardı (§5). Kullanıcı tek-seferlik workaround değil
**uzun vadeli kalıcı çözüm** istedi → Codex `019e35d1` 6-PR prod-deploy
architecture planı verdi.

Handoff sebebi: 6-PR prod-altyapı projesi + bekleyen Q4 canlı rollout, taze
full-context session ister — prod-deploy workflow'u aceleyle/doğrulanmadan
yazılmamalı (No Fake Work). Session Otomatik Açma HARD RULE tetik #1 (context
derinliği) + #4 (pre-completion natural break). Sıradaki session §5 P0 ile
devam eder.

---

## 2. İddia — bu session (68) MERGE edilen PR'lar

Tümü CI yeşil, **normal squash** (`--admin` yok), `ai-post-merge-cleanup.sh`
archive tag'li.

| PR | Repo | Konu | Codex |
|----|------|------|-------|
| #747 | platform-k8s-gitops | Session 67 handoff doc (bu session başında merge) | `019e3524` AGREE |
| #748 | platform-k8s-gitops | `current-state.md` Q4 delta — Live Delta P0+P1+Q3+Q4 LIVE | `019e359e` AGREE (ilk tur) |
| #749 | platform-k8s-gitops | schema-service Q3/Q4 prod promotion — prod overlay digest `b660b25a`→`894e492f` + `schema-service-config` 300s timeout parity + release-candidates ledger backfill | `019e35d1` REVISE→absorb→AGREE |

---

## 3. İspatlar

**Q4 sunucu `k3d-test`'te canlı verified** (staging-sw):
- Pod `schema-service-6b474ffb6b-h24pv` imageID `sha256:894e492f...` (Q4),
  deploy generation 95 fully rolled.
- `/api/v1/schema/snapshot?schema=workcube_mikrolink` → HTTP 200, 1513 tablo /
  26333 kolon / 1787 ilişki / 16 domain; storage 1513 tablo (Q4 catalog-view);
  sunucu log `Extracted storage for 1513 tables`.
- D29 evidence: d29_up GREEN · d29_functional GREEN · d29_zanzibar GREEN
  (OpenFGA store `01KPP0CFP4G82K42Y6NYSPT4JF` allow `user:1204`→true, deny
  `user:9999999`→false).

**GitOps ↔ sunucu senkron**: test overlay `894e492f` == sunucu `k3d-test`
canlı; prod overlay artık `894e492f` desired-state (#749).

**D29 release-candidates ledger**: `release-candidates/platform-backend/58bc2c96c989d1328b21e7a38970e97c13a0a356.json`
— 3 tier GREEN gerçek kanıtla, `validate-ledger-schema.py` OK,
`gate-evidence-check.py` pass. Manuel operator backfill (CI ledger üretimi
PR-4'te — §5).

---

## 4. İspatlamaz

- 🟠 **Q4 prod CLUSTER'a rollout EDİLMEDİ.** Sadece GitOps desired-state
  (#749) merged. Sunucu `k3d-prod` schema-service hâlâ `sha256:b660b25a...`
  (eski, 13 gün). Canlı prod rollout, kalıcı mekanizma (§5 P0 / PR-1)
  üzerinden yapılacak — bu session bilinçli olarak rollout'u tek-seferlik
  workaround ile yapmadı.
- 6-PR prod-deploy-architecture projesi başlamadı.

---

## 5. Bilinen Boşluk + Sıradaki Agent P0 — Codex 6-PR Prod-Deploy Architecture Planı

**Kök sorun**: prod deploy için temiz, eksiksiz, tek mekanizma yok —
`deploy-backend-prod.yml` image-only (`kubectl set image`; ConfigMap/manifest
kapsamaz), ArgoCD `platform-prod` auto-sync KAPALI + sunucuda `argocd` CLI
yok, ad-hoc `kubectl` prod mutasyonu guardrail-blocked.

**Codex verdict (`019e35d1`)**: Prod'un tek normal deployer'ı ArgoCD; apply
tetikleyicisi `production` env-gate'li `workflow_dispatch`. Auto-sync prod'da
AÇILMAZ. `kubectl set image`/`apply -k` normal yol olmaktan çıkar.

### 🟠 P0 — PR-1: `deploy-prod-gitops.yml` kalıcı prod-deploy workflow'u
- Dosya: `.github/workflows/deploy-prod-gitops.yml` — ad `Deploy prod GitOps sync`.
- Trigger: yalnız `workflow_dispatch`; `environment: production`;
  `concurrency: prod-gitops-sync`.
- Inputs: `revision` (main HEAD SHA veya input — yalnız `main` ancestor kabul),
  `sync_mode` (resources/full), `resources` (resource filter), `allow_prune`
  (default `false`), `confirm` (`SYNC-PROD`).
- Workflow **yasak**: `kubectl apply`, `kubectl set image`, Deployment/ConfigMap
  patch. **İzinli**: `argocd app get/diff/sync/wait` + `kubectl get/logs/rollout
  status/exec` (verify/smoke okuması).
- Sync primitive:
  ```bash
  argocd app get platform-prod --hard-refresh
  argocd app diff platform-prod --revision "$TARGET_SHA" --exit-code || DIFF_RC=$?
  argocd app sync platform-prod --revision "$TARGET_SHA" [--resource ...]
  argocd app wait platform-prod --operation --sync --health --timeout 900
  ```
- ArgoCD erişimi: tercih ArgoCD API token (`applications get/sync`, yalnız
  `platform-prod`); alternatif `argocd --core` + k8s RBAC. `argocd` CLI
  runner'da yok → workflow adımı binary'yi indirir.
- Ek: runbook `docs/operations/RUNBOOKS/RB-prod-gitops-sync.md` + `argocd/applications/platform-prod.yaml`
  yorumunu güncelle ("manual sync" → "production env-gate'li ArgoCD sync workflow").

### 🟠 P0 — Q4 rollout: PR-1'in ilk kullanımı
PR-1 merge sonrası, #749 desired-state'i bu workflow ile canlıya uygula —
resource-limited ilk run:
```bash
gh workflow run deploy-prod-gitops.yml \
  -f revision=<main-head-sha> -f sync_mode=resources \
  -f resources=':ConfigMap:schema-service-config,apps:Deployment:schema-service' \
  -f allow_prune=false -f confirm=SYNC-PROD
```
`production` env gate → Halildeu onayı. ArgoCD resource syntax sürüm farkı
çıkarsa: önce `argocd app diff` — diff yalnız `schema-service-config` ConfigMap
+ `schema-service` Deployment ise full app sync kabul; başka gerçek değişiklik
varsa ABORT.

**Q4 acceptance smoke** (rollout sonrası — Codex `019e35d1`):
- ArgoCD sync scope yalnız schema-service ConfigMap + Deployment; refresh
  sonrası beklenmeyen OutOfSync yok.
- `schema-service-config.SCHEMA_MSSQL_QUERY_TIMEOUT_SECONDS == "300"`; yeni
  pod env'de `=300`.
- Deployment pod imageID `sha256:894e492f029c93277ee7d84c993bad2535d970995b0d2df08a48ebb23340ae26`;
  eski `b660b25a` pod kalmamış; restart artmamış.
- `/actuator/health/readiness` 200/UP; log'da startup error / MSSQL timeout /
  `SnapshotUnavailableException` / `503` yok.
- `/api/v1/schema/snapshot?schema=workcube_mikrolink` 200, 1513 tablo / 26333
  kolon, storage 1513; log `Extracted storage for 1513 tables`.
- report-service schema-truth consumer path smoke (≥1 gerçek call 200).
- Public no-token `https://ai.acik.com/api/v1/schema/reporting-contract` +
  `/snapshot` → 401.
- Prod OpenFGA direct allow/deny: `user:1204 admin organization:default`→
  `allowed:true`, `user:9999999`→`allowed:false`.
- Rollback hedefi: prod overlay schema-service digest geri
  `sha256:b660b25a5f6d6dc8080f11456e769f0ef54f9afe3a3e42b4b32e2f725c6c20c3`
  (ConfigMap 300s geri alınmaz — backward-compatible).

### 🟡 PR-2 — image-only prod workflow'ları emekli et
Q4 yeni workflow ile başarıyla sync olduktan sonra: `deploy-backend-prod.yml`
fail-closed/deprecated veya `workflow_dispatch` kaldır; `deploy-frontend-prod.yml`
aynı değerlendirme; `docs/operations/rbac-break-glass-design.md` güncelle.

### 🟡 PR-3 — RBAC least privilege
Normal prod deploy runner'a workload-mutate yetkisi verme — yalnız
`platform-prod` app get/sync token/role; smoke için ayrı read SA; Deployment/
ConfigMap patch / `set image` yok; break-glass SA ayrı + TTL + audit.

### 🔵 PR-4 — Promotion ledger CI automation (ayrı hat — Sprint B follow-up)
`platform-backend`/`platform-web` image build sonrası release-candidate ledger
entry'sini otomatik açsın (manuel backfill istisna kalsın); `d29-smoke-runner.sh`
store-id bug fix (`OPENFGA_STORE_ID` yoksa `ERP_OPENFGA_STORE_ID` fallback);
Tier 2 runner host network-path sorunu.

---

## Sıradaki Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git fetch origin main && git log origin/main --oneline -5
cat docs/session-handoff-2026-05-17-session-68-prod-deploy-architecture.md   # bu doc
# P0: PR-1 deploy-prod-gitops.yml — Codex thread 019e35d1 planı
```
