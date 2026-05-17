# Session Handoff — 2026-05-18 — prod-deploy PR-2 + PR-3A MERGED; PR-3B/C/D operator-gated, PR-3E + PR-4 sıradaki

> Format: D28 5-alan + sıradaki agent aksiyon listesi
> Önceki handoff: `session-handoff-2026-05-18-q4-prod-rollout.md`
> Codex thread'leri: `019e37fa` (PR-2 cross-AI review) · `019e380b` (PR-3 scope
> kararı + PR-3A cross-AI review) · mimari plan `019e35d1` (4-PR prod-deploy)

---

## 1. Bağlam

Q4 prod rollout handoff'u (`session-handoff-2026-05-18-q4-prod-rollout.md` §5)
4-PR prod-deploy-architecture planının (Codex `019e35d1`) PR-2/3/4'ünü devretti.
Bu session PR-2 + PR-3'ün repo-only kısmını (PR-3A) yürüttü.

Handoff sebebi: prod-deploy mimari track'inin **otonom-merge edilebilir** kısmı
tamam (PR-2 + PR-3A). Kalan iş ya **operator-gated** (PR-3B/C/D — canlı prod
RBAC apply / runner kubeconfig cutover / operatör kimlik göçü) ya da **ayrı
hat** (PR-4 promotion ledger). Operator-gated iş için runbook shipped
(`RB-prod-rbac-least-privilege.md`); post-action verify taze-context session
ister (Session Otomatik Açma HARD RULE — pre-completion natural break +
long-running operator action).

---

## 2. İddia — bu session'da yapılanlar

### PR-2 (#789 MERGED, `88ed56b`) — legacy image-only prod workflow emekliliği
- `.github/workflows/deploy-backend-prod.yml` + `deploy-frontend-prod.yml`
  **silindi** — `kubectl set image` image-only; ölü `prod-deploy` runner label
  + rakip `prod-backend-deploy`/`prod-frontend-deploy` concurrency group'ları
  elimine. Prod'un tek normal GitHub Actions prod deploy workflow'u
  `deploy-prod-gitops.yml` (PR-1, #780).
- `docs/RB-prod-deploy-rollback.md` — image-only rollback → **GitOps revision
  rollback** yeniden yazımı (Yol A `sync_mode=full` + `SYNC-PROD-ROLLBACK` /
  Yol B revert-forward); "Yol A sınırı" — prune gate revision-aware değil.
- `rbac-break-glass-design.md` + `RB-prod-gitops-sync.md` + testai runbook +
  `deploy-prod-gitops.yml` header — stale referans güncellemeleri.
- Codex `019e37fa` REVISE×1→AGREE (blocking: rollback runbook prune sınırı).

### PR-3 scope kararı (Codex `019e380b`) — PR-3 → PR-3A..E
PR-3 "RBAC least-privilege" tek geniş PR değil; Codex `019e380b` alt-adımlara
böldü: **PR-3A repo-only contract** (merge anında canlı state değişmez), canlı
enforcement PR-3B/C/D/E operator-gated.

### PR-3A (#790 MERGED, `2127827`) — staged RBAC least-privilege contract
- **YENİ** `kustomize/base/rbac/prod-deploy-smoke/` — `prod-deploy-smoke` SA
  (`argocd` ns) + 2 Role + 2 RoleBinding. argocd ns: argocd-server
  port-forward + read; platform-prod ns: deployment/pod read+watch.
  Workload-mutate (patch/set image/scale/exec/delete) YOK. Standalone
  kustomize entrypoint — hiçbir overlay/base consume etmez.
- **YENİ** `docs/operations/RUNBOOKS/RB-prod-rbac-least-privilege.md` —
  PR-3B/C operator runbook'u (apply + `auth can-i` acceptance matrisi +
  runner kubeconfig cutover + rollback) + PR-3D/E forward.
- `rbac-break-glass-design.md` — PR-3A truth-refresh (Faz 2 orphan/NotFound,
  Faz 3 additive-RBAC düzeltmesi, PR-3A..E sıralama).
- `ci.yml` — `base/rbac` + `base/rbac/prod-deploy-smoke` render-sanity.
- Codex `019e380b` AGREE (4 non-blocking polish aynı PR'da absorbe).

İki PR de: cross-AI Codex review + CI yeşil + normal squash (admin yok) +
forensic archive-tag.

---

## 3. İspatlar

- **PR-2 #789**: CI 8/8 GREEN, `mergeState=CLEAN`, mergedAt
  2026-05-17T22:20:45Z. Archive tag
  `archive/2026/05/chore-pr2-retire-legacy-prod-workflows-pr789`.
- **PR-3A #790**: CI 12/12 GREEN (kustomize-build + base/rbac render-sanity
  dahil), `mergeState=CLEAN`, mergedAt 2026-05-17T22:46:44Z. Archive tag
  `archive/2026/05/feat-pr3a-rbac-least-privilege-contract-pr790`.
- **No live mutation kanıtı**: PR-2 workflow-file silme (silinen 2 workflow
  zaten ölü `prod-deploy` label ile non-functional'dı). PR-3A staged manifest
  — `kustomize build kustomize/overlays/prod` çıktısında `prod-deploy-smoke`
  geçiş sayısı **0** (overlay sızıntısı yok). Hiçbir cluster/credential state
  merge anında değişmedi.
- Codex cross-AI review zinciri: `019e37fa` (PR-2 REVISE→AGREE) + `019e380b`
  (PR-3 scope + PR-3A AGREE).

---

## 4. İspatlamaz

- **PR-3B/C/D canlıya alınmadı** — canlı doğrulama: `kubectl --context
  k3d-prod -n kube-system get sa ops-break-glass` → NotFound + `kubectl
  --context k3d-prod -n argocd get sa prod-deploy-smoke` → NotFound. Her iki
  manifest repo'da staged; hiçbir overlay/base consume etmiyor → ArgoCD prod
  sync path'inde değil; PR-3B/C apply bu session'da yapılmadı. Runner
  kubeconfig hâlâ `admin@k3d-prod` cluster-admin. Bunlar `state-mutation
  (production)` → operator-gated.
- PR-3E (audit/alarm) başlamadı — PR-3B (break-glass live) bağımlısı.
- PR-4 (promotion ledger CI automation) başlamadı — ayrı hat.

---

## 5. Bilinen Boşluk + Sıradaki Agent P0

### 🟢 Otonom — agent-yapılabilir (taze-context session)
- **PR-4 — promotion ledger CI automation** (4-PR planının ayrı hattı):
  `platform-backend`/`platform-web` image build sonrası release-candidate
  ledger entry'sini otomatik üret + `d29-smoke-runner.sh` store-id bug fix
  (`OPENFGA_STORE_ID` yoksa `ERP_OPENFGA_STORE_ID` fallback). Repo-PR,
  otonom merge edilebilir. **Sıradaki agent P0.**

### 🟠 Operator-gated — runbook `RB-prod-rbac-least-privilege.md` shipped
- **PR-3B — break-glass SA live activation**: `kubectl apply -k
  kustomize/base/rbac` + `break-glass-token.sh` token issuance smoke.
  `state-mutation (production)` — owner/operator onayı.
- **PR-3C — prod-deploy-smoke runner cutover**: `kubectl apply -k
  kustomize/base/rbac/prod-deploy-smoke` + `auth can-i` acceptance matrisi +
  uzun-ömürlü SA token Secret + runner kubeconfig cutover + eski admin
  kubeconfig'i runner host'tan kaldırma. `state-mutation (production)`.
- **PR-3D — operator readonly identity migration**: `rbac-break-glass-design.md`
  Faz 3 (PR-3A'da düzeltilmiş — additive-RBAC). Yeni readonly identity üret;
  eski `admin@k3d-prod`'u break-glass/offline'a taşı. Owner koordinasyonu +
  PR-3B doğrulanmadan yapılmaz.

### 🔵 Sonraki — PR-3E
- **PR-3E — audit/alarm (Faz 5)**: break-glass kullanım alert'i +
  RBAC-violation telemetrisi. PR-3B (break-glass live) sonrası anlamlı.

### Bağımsız izlenen
- `deploy-backend-testai.yml` (test cluster) image-only `kubectl set image`
  yolu — PR-3 kapsamı dışı.
- Q4 prod authenticated snapshot-data smoke (önceki handoff §4 residual).

---

## Sıradaki Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git fetch origin main && git log origin/main --oneline -5
cat docs/session-handoff-2026-05-18-prod-deploy-pr2-pr3a.md     # bu doc
cat docs/operations/RUNBOOKS/RB-prod-rbac-least-privilege.md    # PR-3B/C operator runbook
# P0 (otonom): PR-4 promotion ledger CI automation — Codex thread 019e35d1
# Operator-gated: PR-3B/C/D — RB-prod-rbac-least-privilege.md
```
