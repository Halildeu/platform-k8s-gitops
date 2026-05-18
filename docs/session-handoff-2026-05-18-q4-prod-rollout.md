# Session Handoff — 2026-05-18 — Q4 schema-service prod rollout LIVE; prod-deploy 4-PR planının PR-2/3/4'ü sıradaki

> Format: D28 5-alan + sıradaki agent aksiyon listesi
> Önceki handoff: `session-handoff-2026-05-17-session-68-prod-deploy-architecture.md`
> Codex thread: `019e3638` (PR-1 cross-AI review + Q4 rollout VERDICT-B + acceptance YETERLİ);
> mimari plan `019e35d1` (4-PR prod-deploy architecture)

---

## 1. Bağlam

Session 68 handoff'u (#750) prod-deploy mekanizmasının yapısal eksikliğini ve
Codex `019e35d1` 4-PR planını devretti; §5 P0 = PR-1 `deploy-prod-gitops.yml`.

Bu session:
- PR-1'i `argocd --core` mimarisiyle yazdı (#781, Codex `019e3638` REVISE×2→AGREE).
- **Çakışma**: paralel bir session PR-1'i `#780` ile (ArgoCD API token +
  `kubectl port-forward` mimarisi, Codex `019e362d`) ~37 sn önce main'e merge etti.
  `#781` conflicting duplicate olarak kapatıldı (Codex `019e3638` verdict; #780 =
  main source-of-truth, ayrıca #781'in `runs-on` ölü `prod-deploy` runner label
  defekti vardı).
- #780'in operator setup'ını yürüttü ve Q4 schema-service'i prod'a rollout etti —
  `deploy-prod-gitops.yml` mekanizmasının **ilk gerçek prod kullanımı**.

Handoff sebebi: Q4 prod rollout tamam + Codex-kabul edildi; 4-PR planının kalan
PR-2/3/4'ü ayrı, taze-context bir session'da yürütülecek (Session Otomatik Açma
HARD RULE — pre-completion natural break + context derinliği).

---

## 2. İddia — bu session'da yapılanlar

### Operator setup (owner açık opt-in — credential/control-plane gated)
- ArgoCD `helm upgrade argocd argo/argo-cd --version 7.7.5` → release **rev2**.
  `helm upgrade --dry-run` ön-kontrolü (helm-diff plugin yok → dry-run manifest
  vs `helm get manifest` diff): yalnız `argocd-cm` + `argocd-rbac-cm` data + 3
  `checksum/cm` bump — drift yok.
- `argocd-cm` `accounts.prod-gitops-sync: apiKey` + `argocd-rbac-cm` policy.csv
  2 satır (`get`+`sync`, yalnız `default/platform-prod`) canlı.
- `prod-gitops-sync` API token üretildi (ArgoCD CLI v2.13.1, admin login +
  `account generate-token`) → `gh secret set ARGOCD_PROD_SYNC_TOKEN --env production`.

### Q4 prod rollout — `deploy-prod-gitops.yml` run 26003161043
- `gh workflow run` · `sync_mode=resources` · `resources=:ConfigMap:schema-service-config,apps:Deployment:schema-service,:ConfigMap:nginx-config`
  · `allow_prune=true` · `confirm=SYNC-PROD-PRUNE` (Codex `019e3638` VERDICT-B —
  3 OOS resource tek run'da scoped sync).
- İlk dispatch (run 25997960585) gece boyu `production` env-gate'inde onaysız
  kaldı, `origin/main` ilerledi → iptal + güncel revision'la yeniden dispatch.
- `production` env-gate owner onayı (CLI `pending_deployments` approve).
- `conclusion=success` — workflow diff/prune/whitelist gate'leri geçti.

### `#781` kapatıldı
Conflicting duplicate (merged #780 PR-1'i karşılıyor) + ölü `prod-deploy` runner
label defekti. Branch + worktree temizlendi. Taşınacak delta yok (cross-workflow
concurrency birleştirme PR-2 kapsamına alındı).

---

## 3. İspatlar — canlı kanıt (k3d-prod, platform-prod)

Acceptance smoke **8/8 GREEN** (Codex `019e3638` VERDICT: YETERLİ):

- schema-service deploy image + pod imageID = `sha256:894e492f029c93277ee7d84c993bad2535d970995b0d2df08a48ebb23340ae26` (Q4 digest).
- pod `schema-service-665477dd59-9nfhq` — Running · Ready · restart=0 · log
  `Started SchemaServiceApplication in 15.199 seconds`.
- `SCHEMA_MSSQL_QUERY_TIMEOUT_SECONDS=300` — `schema-service-config` ConfigMap
  (at-rest) + canlı pod runtime env (`env` ikisinde de).
- `nginx-config` orphan ConfigMap pruned — `kubectl get cm nginx-config` →
  `NotFound`.
- readiness 200 · liveness 200 (pod mgmt port 8081).
- log temiz — `error/exception/timeout/SnapshotUnavailableException/503` yok.
- public no-token `https://ai.acik.com/api/v1/schema/reporting-contract` +
  `/api/v1/schema/snapshot?schema=workcube_mikrolink` → ikisi de **401**
  (edge→gateway→service→auth-filter zinciri fail-closed, 5xx değil).
- ArgoCD `platform-prod` Application — `sync=Synced health=Healthy oos_count=0`
  (114 resource hepsi Synced; 3 OOS resource converge — 2 sync + nginx-config prune).

---

## 4. İspatlamaz

- 🟠 **Prod authenticated snapshot-data smoke** (`/api/v1/schema/snapshot` 200 +
  1513 tablo / storage 1513) prod'da DOĞRUDAN koşulmadı. schema-service auth
  JWT-only (audience `schema-service`); pod env'inde internal API key yok →
  doğrudan check Keycloak client-credentials gerektirir. Q4 image `894e492f`
  byte-identical olarak Session 67'de TEST'te bu düzeyde doğrulandı; prod o exact
  image'i healthy koşuyor. Codex: rollout kabulünün blocker'ı DEĞİL — opsiyonel/
  credential-gated follow-up.
- 4-PR prod-deploy-architecture planının PR-2/3/4'ü başlamadı.

---

## 5. Bilinen Boşluk + Sıradaki Agent P0 — prod-deploy 4-PR planı PR-2/3/4 (Codex `019e35d1`)

### 🟠 P0 — PR-2: legacy image-only prod workflow'ları emekli et
- `deploy-backend-prod.yml` + `deploy-frontend-prod.yml` image-only
  (`kubectl set image`) — artık `deploy-prod-gitops.yml` ile değiştirildi.
  Bu iki workflow şu an zaten `runs-on: [self-hosted, staging-sw, prod-deploy]`
  kullanıyor — `prod-deploy` label hiçbir runner'da yok (ölü), yani çalışamaz
  durumdalar. PR-2: fail-closed/deprecated yap veya `workflow_dispatch`'i kaldır.
- **Concurrency birleştirme bu PR'da kapanır** (Codex `019e3638` finding #4):
  PR-2 acceptance maddesi → "legacy prod deploy workflow'ları kaldırıldı/disable
  edildi; rakip prod-mutasyon workflow'u kalmadı." (#781 bu birleştirmeyi
  `prod-deploy` shared concurrency group ile yapmıştı ama kapatıldı.)
- `docs/operations/rbac-break-glass-design.md` güncelle.

### 🟡 PR-3 — RBAC least-privilege
Normal prod-deploy runner'a workload-mutate yetkisi verme; `prod-gitops-sync`
account zaten `platform-prod` app `get`+`sync`'e scoped (#780 helm-values), ama
runner kubeconfig'i hâlâ geniş kubectl yetkisinde. Smoke için ayrı read SA;
break-glass SA ayrı + TTL + audit.

### 🔵 PR-4 — Promotion ledger CI automation (ayrı hat — Sprint B follow-up)
`platform-backend`/`platform-web` image build sonrası release-candidate ledger
entry'sini otomatik üret (manuel backfill istisna kalsın); `d29-smoke-runner.sh`
store-id bug fix (`OPENFGA_STORE_ID` yoksa `ERP_OPENFGA_STORE_ID` fallback);
Tier 2 runner host network-path sorunu.

### 🔵 Opsiyonel follow-up — prod snapshot-data smoke
İstenirse: Keycloak client-credentials ile audience-`schema-service` JWT alıp
prod `/api/v1/schema/snapshot?schema=workcube_mikrolink` → 200 + 1513 tablo
doğrula. Rollout kabulü için şart değil (§4).

---

## Sıradaki Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git fetch origin main && git log origin/main --oneline -5
cat docs/session-handoff-2026-05-18-q4-prod-rollout.md   # bu doc
cat docs/state/current-state.md | head -70               # Q4 prod rollout Live Delta
# P0: PR-2 legacy prod workflow emekliliği — Codex thread 019e35d1 planı
```
