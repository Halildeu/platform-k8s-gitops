# Contributing — platform-k8s-gitops

Bu repo Kubernetes GitOps manifest tek doğruluk kaynağıdır. Değişiklikler direkt `main`'e push edilmez — PR + CI + review zorunlu.

---

## Ortam Hazırlık

### Ön Gereksinimler

- Docker 24+ + Docker Compose v2.20+
- kubectl 1.28+ + helm 3.12+ + k3d v5.6+ + kustomize 5.0+
- `yamllint` + `shellcheck` (lokal lint öncesi)
- SSH deploy key (`~/.ssh/k8s-gitops-deploy`)

### Repo Clone

```bash
git clone git@github.com:Halildeu/platform-k8s-gitops.git
cd platform-k8s-gitops
```

---

## 3-Tier Topoloji (Faz 17)

> Detay: [docs/promotion-contract.md](./docs/promotion-contract.md)

| Tier | Host | Cluster | Domain |
|---|---|---|---|
| Lokal dev | Mac | `k3d-dev` | `*.localtest.me` |
| Test | staging-sw | `k3d-test` | `testai.acik.com` |
| Prod | staging-sw | `k3d-prod` + compose | `ai.acik.com` |

**Ownership Matrix (cross-repo):**
- **Inner-loop tooling** (Tilt, code watch, image build) → `platform-ssot` **authoritative**
- **Env/smoke/scaffolding** (overlays, scripts, fixtures) → `platform-k8s-gitops` **authoritative**
- **Application code** (Java + MFE) → `platform-ssot`
- **K8s manifest** (Deployment/Service/ConfigMap) → `platform-k8s-gitops`

Ownership değişirse **her iki repo CONTRIBUTING senkron güncellenir** (Faz 17.6 cross-repo kural).

---

## Workflow

### 1. Branch

```bash
git checkout -b feat/<kısa-başlık>
# veya: fix/<...>, docs/<...>, refactor/<...>, chore/<...>
```

### 2. Lokal Dev Setup (ilk defa)

```bash
# k3d-dev cluster ayağa kaldır (Faz 17)
./bootstrap/setup-clusters.sh dev                 # veya ./scripts/dev-up.sh
./scripts/dev-seed.sh --profile authn-min         # KC realm + PG seed (fake fixtures)
./scripts/dev-smoke.sh --profile authn-min        # D29 muadili smoke
```

Profile'lar:
- `authn-min` (2 workload, Up+Functional auth-only)
- `zanzibar-min` (6 workload, D29 3-katman FULL)
- `full` (10 workload, testai desen paritesi)

### 3. Değişiklik

- **Kustomize base:** tüm overlay'lere yansır — dikkat
- **Overlay-specific:** `kustomize/overlays/{test|prod|local-*}[/eso]/`
- **App base ayrımı (Faz 17.2.5):**
  - `kustomize/base/apps/<svc>/kustomization.yaml` → runtime only (Deployment + Service + ConfigMap + PDB + ServiceAccount)
  - `kustomize/base/apps/<svc>/ops/kustomization.yaml` → CRD-gated (ExternalSecret + ServiceMonitor)
  - test/prod overlay `ops-bundle` include eder; local-* overlay **include ETMEZ** (CRD-free)
- **Runbook:** `docs/<Sx>-<topic>-runbook.md` format
- **Handoff:** büyük delta ise `docs/session-handoff-<YYYY-MM-DD>.md` güncelle

### 4. Lokal Sanity

```bash
# Lokal dev smoke (değişikliği Mac'te test)
./scripts/dev-smoke.sh --profile <profil>

# Kustomize build (tüm overlay'ler)
for o in test prod local local-authn-min local-zanzibar-min local-full; do
  kubectl kustomize kustomize/overlays/$o > /tmp/$o.yaml && echo "$o OK"
done
kubectl kustomize kustomize/overlays/test/eso > /tmp/test-eso.yaml
kubectl kustomize kustomize/overlays/prod/eso > /tmp/prod-eso.yaml
kubectl kustomize kustomize/base/monitoring > /tmp/monitoring.yaml

# YAML lint
yamllint kustomize/ argocd/ docs/ helm-values/

# Shell lint (varsa script değişim)
shellcheck bootstrap/*.sh scripts/*.sh
```

### 4. Codex Adversarial Review (büyük değişim için)

Kesin review yalnız ayrı context'te direct Codex CLI ile yapılır:

```bash
codex exec --ephemeral --sandbox read-only --model <scope-class-exact-model> \
  -c 'model_reasoning_effort="xhigh"' -C <absolute-worktree> '<bounded exact-scope review>'
```

Rutin review modeli `gpt-5.3-codex-spark`; governance/security/migration/
production modeli `gpt-5.6-sol` olur. Claude, MiniMax, Cursor, MCP/wrapper,
başka model ve AI uygulama penceresi kullanılmaz.

Provider yanıt sözleşmesi:

```
## P0
None veya somut bulgu
## P1
None veya somut bulgu
## P2
None veya somut bulgu
VERDICT: AGREE|REVISE
```

- `AGREE` → test/CI/live evidence kapılarına devam et.
- `REVISE` → geçerli bulguyu düzelt, yeni exact head/scope ile yeniden incele.

Codex receipt protected Environment reviewer, gerçek kullanıcı rızası veya
isimli insan/hukuk onayını ikame etmez.

### 5. Commit

Format:

```
<type>(<scope>): <kısa başlık <=70 char>

<body>
- Ne değişti
- Neden değişti
- Kanıt (build sanity, Codex iter, smoke)

```

Types: `feat` / `fix` / `refactor` / `docs` / `chore` / `test`

### 6. Push + PR

```bash
git push -u origin feat/<kısa-başlık>
gh pr create --fill   # veya UI
```

PR template otomatik doldurulur (`.github/pull_request_template.md`). Test planı + kontrol listesi + Codex verdict doldurulur.

### 7. CI

GitHub Actions `ci.yml` 5 job çalıştırır:
- `kustomize-build` (5 overlay + base/eso placeholder sanity)
- `yaml-lint`
- `shell-lint`
- `closure-language-check` (HARD RULE)
- `placeholder-leak-check`

Tümü PASS olmalı.

### 8. Review

En az 1 review + CI PASS zorunlu. Self-merge yasak.

### 9. Merge

- **main** → ArgoCD auto-sync (test cluster, platform-test)
- **prod cluster** → manual sync (D30 atomic cutover)

---

## HARD RULE'lar (CI ile enforce edilir)

### 1. No Closure Language

"Bugün kapandı/tamam bitti/gün sonu/pause/bekle/başarıyla tamamlandı" YASAK — PR metni, commit mesajı, runbook dahil.

**Neden:** `CLAUDE.md` + `memory/feedback_no_closure_language.md`

### 2. IP Sanitize

Dış kullanıcı-facing doc/response'ta iç ağ IP yok. `10.9.10.53`, `172.19.0.x`, `127.0.0.1` sadece repo içi teknik doküman.

### 3. D30 Immutable Artifact

Overlay image tag `sha-<short>` — `main-stable` (moving) YASAK.

### 4. D29 3-Katman

Her deploy/cutover Up + Functional + Zanzibar-ready ayrı kanıtlanır. Tek "yeşil" yetmez.

### 5. D30 Weighted YASAK

Atomic cutover + 72h warm rollback (weighted DNS %10/50/100 YASAK).

---

## Commit Type Örnekleri

```
feat(eso): ghcr-pull overlay-specific namespace fix (W1 Opsiyon B)
fix(argocd): platform-eso path overlay/<env>/eso (base/eso YASAK)
refactor(kustomize): shortname refactor intra-ns svc URLs (S2-A1)
docs(runbook): S4-rollback + D32-bootstrap runbook
chore(ci): add kustomize-build + closure-language-check workflow
test(k6): zanzibar-load profile 50 VU × 6 dk
```

---

## Dizin Kuralları

- `kustomize/base/` — ortam-bağımsız, tek kaynak
- `kustomize/overlays/<env>/` — patches + env-specific resource
- `kustomize/overlays/<env>/eso/` — ESO overlay-specific (W1 namespace fix)
- `bootstrap/*.sh` — idempotent install/apply helper (executable)
- `docs/` — runbook + handoff + plan pack
- `argocd/applications/` — tek Application CR (MVP)
- `argocd/applicationsets/` — multi-cluster ApplicationSet (draft D32 sonrası)
- `helm-values/` — 3rd party helm chart values (values-test.yaml + values-prod.yaml)

---

## Önemli Dokümanlar

- [PLAN.md](./PLAN.md) — master plan + karar logu (D1-D32)
- [CLAUDE.md](./CLAUDE.md) — agent kılavuzu (HARD RULE + pattern + pitfall)
- [README.md](./README.md) — dizin + runbook envanteri
- [docs/session-handoff-<latest>.md](./docs/) — son session durumu

## Kaynaklar

- Codex thread: `019d9a75` (ana) + `019da5f8` (delta retrospective)
- Memory: `~/.claude/projects/<slug>/memory/` (feedback kuralları)
