# Session Handoff — 2026-05-18 — prod-deploy PR-4A MERGED; repo-only agent-actionable kapsam kayda geçti

> Format: D28 5-alan + sıradaki agent aksiyon listesi
> Önceki handoff: `session-handoff-2026-05-18-prod-deploy-pr2-pr3a.md`
> Codex thread'leri: `019e39ea` (PR-4 scope kararı + PR-4A cross-AI review);
> mimari plan `019e35d1` (4-PR prod-deploy)

---

## 1. Bağlam

`session-handoff-2026-05-18-prod-deploy-pr2-pr3a.md` §5 PR-4'ü "otonom" devretti.
Bu session PR-4'ü yürüttü; Codex `019e39ea` scope kararıyla PR-4 → **PR-4A**
(repo-only d29-smoke fix) + devredilen kalanlar.

prod-deploy 4-PR mimari planının (Codex `019e35d1`) **repo-only agent-actionable
platform-k8s-gitops kapsamı bu session'da PR-1/2/3A/4A olarak kayda geçti**;
kalan iş operator-gated, cross-repo veya spec-bekleyen:
- PR-1 (#780) — `deploy-prod-gitops.yml` GitOps deploy mekanizması.
- PR-2 (#789) — legacy image-only prod workflow emekliliği.
- PR-3A (#790) — staged RBAC least-privilege contract.
- PR-4A (#792) — d29-smoke Zanzibar store-id resolver + non-GREEN ledger guard.

Kalan iş ya **operator-gated** (PR-3B/C/D canlı RBAC) ya **cross-repo**
(PR-4 ledger CI automation = `platform-backend`/`platform-web` B3 + operator
B2) ya **spec-bekleyen** (Tier-2 runner network-path). Handoff sebebi: otonom
repo-içi iş doygunluğa ulaştı (Session Otomatik Açma HARD RULE).

---

## 2. İddia — bu session'da yapılanlar

### PR-4A (#792 MERGED, `18b3f46`) — d29-smoke Zanzibar store-id resolver

**Bug**: `scripts/smoke/d29-smoke-runner.sh` `tier_zanzibar()` store_id'yi
`permission-service-config` ConfigMap `OPENFGA_STORE_ID` key'inden okuyordu —
key yanlış (canonical `ERP_OPENFGA_STORE_ID`) + o key bile ConfigMap'te boş
stub; gerçek değer `permission-service-secrets` Secret'ında (ESO/Vault
`kv/platform/openfga`). Sonuç: Zanzibar (authz enforcement) tier her D29
smoke'da SKIP'liyor + SKIP exit 0 üretip ledger'a D29-verified taşınabiliyordu.

**Fix**:
- `resolve_store_id()` — resolver chain: `D29_OPENFGA_STORE_ID` env override →
  Secret/ConfigMap `ERP_OPENFGA_STORE_ID` (canonical, across-sources) → legacy
  `OPENFGA_STORE_ID` → opt-in pod-env `kubectl exec` (`D29_STORE_ID_SOURCE=pod-env`).
  `store_id_source` evidence `details` alanına gömülür.
- Exit-code: `0`=tüm GREEN, `1`=≥1 RED, `3`=incomplete (SKIP/AMBER, RED yok) —
  non-GREEN tier ledger'a D29-verified taşınamaz.
- `scripts/promotion/ledger-mark-verified.sh` defense-in-depth — `exit_code` 0
  olsa bile 3 D29 tier'ın hepsi GREEN değilse (veya eksikse) ledger verified
  işaretlenmez.
- Codex `019e39ea` REVISE×1→AGREE (resolver precedence + missing-tier guard).

---

## 3. İspatlar

- **PR-4A #792**: CI 8/8 GREEN (shell-lint/shellcheck dahil), `mergeState=CLEAN`,
  mergedAt 2026-05-18T07:34:11Z. Archive tag
  `archive/2026/05/fix-pr4a-d29-smoke-zanzibar-storeid-pr792`.
- **Fonksiyonel kanıt**: değiştirilmiş `d29-smoke-runner.sh test` `k3d-test`'te
  koştu — Tier 4 Zanzibar `store_id resolved via
  secret/permission-service-secrets:ERP_OPENFGA_STORE_ID` → `status=GREEN
  synthetic=PASS` (eskiden her zaman SKIP). `bash -n` + `shellcheck -S warning`
  + jq guard 3-senaryo testi temiz.
- Codex cross-AI review zinciri: `019e39ea` (PR-4 scope + PR-4A REVISE→AGREE).

---

## 4. İspatlamaz

- **PR-3B/C/D canlıya alınmadı** — `ops-break-glass` + `prod-deploy-smoke` SA
  canlıda yok (önceki handoff §4 — `kubectl get sa` NotFound kanıtlı). Runner
  kubeconfig hâlâ `admin@k3d-prod`. `state-mutation (production)` →
  operator-gated; runbook `RB-prod-rbac-least-privilege.md` shipped.
- **PR-4 ledger CI automation yapılmadı** — `scripts/promotion/*` script'leri
  hazır; eksik olan `platform-backend`/`platform-web` CI'ının `generate-ledger.sh`
  çağırması (B3, cross-repo) + B2 GitHub App registration (operator-manual).
- **Tier-2 runner network-path** — bu session d29-smoke test run'ında **yeniden
  gözlemlendi**: Tier 2 Functional 6 servisin hepsi için `000000` (port-forward
  unreachable) → RED. Root cause spec'i yok (hangi host/kubeconfig/hop) → defer;
  ayrı mini-design gerekiyor.
- PR-3E (audit/alarm) başlamadı — PR-3B bağımlısı.

---

## 5. Bilinen Boşluk + Sıradaki Agent Aksiyonları

### 🟠 Operator-gated — runbook `RB-prod-rbac-least-privilege.md` shipped
- **PR-3B** — break-glass SA live activation (`kubectl apply -k
  kustomize/base/rbac` + `break-glass-token.sh` smoke).
- **PR-3C** — `prod-deploy-smoke` apply + runner kubeconfig least-privilege
  cutover + `auth can-i` acceptance matrisi.
- **PR-3D** — operator readonly identity migration (owner koordinasyonu).

### 🔵 Cross-repo / operator — PR-4 ledger CI automation
- **B2** (operator-manual): GitHub App registration — gitops repo'ya ledger
  entry commit yetkisi.
- **B3** (cross-repo): `platform-backend` + `platform-web` CI workflow'larına
  image build + GHCR push sonrası `generate-ledger.sh` çağrısı (promotion
  design'a göre). B3 PR'ları `platform-backend`/`platform-web` CI'larında
  açılır; `platform-ssot` hedef repo olarak kullanılmaz.

### 🔵 Sonraki — PR-3E + Tier-2
- **PR-3E** — audit/alarm (Faz 5); PR-3B sonrası.
- **Tier-2 runner network-path** — `d29-smoke-runner.sh` `tier_functional`
  port-forward `svc/<name>:80` → `000000`. Ayrı mini-design: hangi host /
  kubeconfig / svc-port (80 vs 8080) / failure classification.

### Bağımsız izlenen
- Q4 prod authenticated snapshot-data smoke (önceki handoff residual).

---

## Sıradaki Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git fetch origin main && git log origin/main --oneline -6
cat docs/session-handoff-2026-05-18-prod-deploy-pr4a.md           # bu doc
cat docs/operations/RUNBOOKS/RB-prod-rbac-least-privilege.md      # PR-3B/C operator
# Operator-gated: PR-3B/C/D — RB-prod-rbac-least-privilege.md
# Cross-repo: PR-4 B3 — platform-backend/web CI generate-ledger.sh çağrısı
```
