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

## Workflow

### 1. Branch

```bash
git checkout -b feat/<kısa-başlık>
# veya: fix/<...>, docs/<...>, refactor/<...>, chore/<...>
```

### 2. Değişiklik

- **Kustomize base:** tüm overlay'lere yansır — dikkat
- **Overlay-specific:** `kustomize/overlays/{test|prod}[/eso]/`
- **Runbook:** `docs/<Sx>-<topic>-runbook.md` format
- **Handoff:** büyük delta ise `docs/session-handoff-<YYYY-MM-DD>.md` güncelle

### 3. Lokal Sanity

```bash
# Kustomize build
kubectl kustomize kustomize/overlays/test > /tmp/test.yaml
kubectl kustomize kustomize/overlays/prod > /tmp/prod.yaml
kubectl kustomize kustomize/overlays/test/eso > /tmp/test-eso.yaml
kubectl kustomize kustomize/overlays/prod/eso > /tmp/prod-eso.yaml
kubectl kustomize kustomize/base/monitoring > /tmp/monitoring.yaml

# YAML lint
yamllint kustomize/ argocd/ docs/ helm-values/

# Shell lint (varsa script değişim)
shellcheck bootstrap/*.sh
```

### 4. Codex Adversarial Review (büyük değişim için)

Plan-time istişare: `mcp__codex__codex` MCP ile plan önerini sun:

```
VERDICT: AGREE / PARTIAL / REVISE / RED
```

- AGREE → direkt impl
- PARTIAL/REVISE → absorb et, yeni iter
- RED → kullanıcıya rapor + yön sor

Kural: Codex AGREE sonrası kullanıcıya ara onay sorma (CLAUDE.md).

### 5. Commit

Format:

```
<type>(<scope>): <kısa başlık <=70 char>

<body>
- Ne değişti
- Neden değişti
- Kanıt (build sanity, Codex iter, smoke)

Co-Authored-By: Claude Opus 4.X <noreply@anthropic.com>
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
