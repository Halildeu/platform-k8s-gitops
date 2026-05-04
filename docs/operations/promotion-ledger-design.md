# Promotion Ledger + PR-First Promotion Bot — Codex P0 #2

> **Codex AGREE Session 37** (thread `019df2bf`, item #1+#2+#7):
> "Test promotion: platform-backend/platform-web CI image build sonrası
> cluster'a dispatch etmesin. GitOps repo'da bot PR açsın: test overlay
> digestleri + `release-candidates/<repo>/<sha>.json` ledger dosyası
> güncellensin. PR merge → ArgoCD sync → D29/D35 smoke."
>
> "Prod promotion: testte çalışan canlı `pod imageID` digestleri ledger'a
> 'verified in test' olarak yazılsın. Prod PR, GHCR latest'ten değil bu
> ledger snapshot'ından üretılsün. Merge/sync manuel approval gate ile."

Bu doc, manuel `kubectl set image` müdahalesini ortadan kaldıran ve
`origin/main` GitOps yaml'ı **single source of truth** haline getiren
otomasyon mimarisini belirler. Implementation ayrı PR'lara bölünmüş;
burada **schema + workflow + secret/permission spec + migration** var.

## Sorun: Mevcut promotion akışı

```
[Backend kod değişim]
        ↓
   CI build + GHCR push (sha-<commit>)
        ↓
   ┌──────────────────┐
   │ TESTAI deploy    │ ← deploy-backend-testai.yml
   │  kubectl set image  CURRENT: cluster'a doğrudan mutate
   │  on cluster      │
   └──────────────────┘
        ↓
   (test smoke verify — manuel veya gate)
        ↓
   ┌──────────────────┐
   │ PROD deploy      │ ← deploy-backend-prod.yml
   │  kubectl set image  CURRENT: cluster'a doğrudan mutate
   │  on cluster      │  Yaml drift hemen başlar
   └──────────────────┘
```

**Sorunlar** (Session 37 audit):
- Test cluster'a CI dispatch overlay yaml'ı update etmiyor → drift
- Prod'a CI dispatch yapsa da yaml drift kapanmıyor → ArgoCD OutOfSync
- Manuel müdahale (kubectl set image) ile recovery genelde gitops PR atlıyor
- "Test'te verify ettim, prod'a geçtim" pattern'i unutuluyor → 3 servis bayat

## Hedef akış (PR-first)

```
[Backend kod değişim]
        ↓
   CI build + GHCR push (sha-<commit>)
        ↓
   ┌────────────────────────────────────────────────┐
   │ Promotion bot: gitops PR aç                    │
   │ - test overlay yaml digest update             │
   │ - release-candidates/<repo>/<sha>.json yarat  │
   │ - PR labels: auto-promotion, env:test         │
   └────────────────────────────────────────────────┘
        ↓
   PR auto-merge (smoke sonrası gate)
        ↓
   ArgoCD test sync → cluster'a yeni digest
        ↓
   ┌────────────────────────────────────────────────┐
   │ Test smoke verify (D29/D35 evidence)           │
   │ - readiness/liveness 200                       │
   │ - functional smoke (auth/JWT)                  │
   │ - synthetic authz allow/deny                   │
   └────────────────────────────────────────────────┘
        ↓ (smoke GREEN)
   ┌────────────────────────────────────────────────┐
   │ Promotion bot: ledger update                   │
   │ - <sha>.json: status=verified_in_test          │
   │ - test_smoke_evidence: { ... }                 │
   └────────────────────────────────────────────────┘
        ↓
   ┌────────────────────────────────────────────────┐
   │ Promotion bot: prod-candidate PR aç            │
   │ - prod overlay yaml digest update              │
   │ - PR title: feat(promotion): <repo> sha-<X>    │
   │ - PR body: ledger snapshot + smoke evidence    │
   │ - PR label: auto-promotion, env:prod           │
   │ - DRAFT (manuel review + "merge et" gate)      │
   └────────────────────────────────────────────────┘
        ↓ (operator review + merge)
   ArgoCD prod sync → strict rollout (maxSurge=1)
        ↓
   ┌────────────────────────────────────────────────┐
   │ Promotion bot: ledger close                    │
   │ - <sha>.json: status=deployed_to_prod          │
   │ - prod_deploy_evidence: { ... }                │
   └────────────────────────────────────────────────┘
```

## Ledger schema

`release-candidates/<repo>/<sha>.json`:

```json
{
  "schema_version": "1.0",
  "repo": "platform-backend",
  "service": "user-service",
  "git_sha": "548c1831719298ce1b0c8a52b2e37c9bdba3ed4ab8cd939cfad54087774b390b",
  "git_short_sha": "548c1831",
  "image": {
    "registry": "ghcr.io",
    "path": "halildeu/platform-backend-user-service",
    "digest": "sha256:548c1831719298ce1b0c8a52b2e37c9bdba3ed4ab8cd939cfad54087774b390b",
    "tag": "sha-548c183",
    "push_run_id": 25292510483,
    "pushed_at": "2026-05-04T08:50:36Z"
  },
  "promotion": {
    "test": {
      "promoted_at": "2026-05-04T09:00:00Z",
      "promoted_by_pr": 195,
      "argocd_revision": "548c1831...",
      "smoke_evidence": {
        "d29_up": { "status": "GREEN", "checked_at": "2026-05-04T09:01:00Z" },
        "d29_functional": { "status": "GREEN", "endpoints": ["/api/v1/users"] },
        "d29_zanzibar": { "status": "GREEN", "allow_deny_synthetic": "PASS" }
      },
      "verified_at": "2026-05-04T09:05:00Z"
    },
    "prod": {
      "candidate_pr": 196,
      "candidate_pr_status": "draft",
      "promoted_at": null,
      "promoted_by_pr": null,
      "argocd_revision": null,
      "smoke_evidence": null
    }
  },
  "metadata": {
    "required_migrations": [],
    "backward_compatible_until": null,
    "rollback_safe": true,
    "rollback_to_digest": "df8b84d0cd02d064cf455f40017bd5cb4ca1be271e5e7068afeb36fc4526a7f1"
  },
  "audit": {
    "created_at": "2026-05-04T08:55:00Z",
    "last_updated_at": "2026-05-04T09:05:00Z",
    "ci_run_url": "https://github.com/Halildeu/platform-backend/actions/runs/..."
  }
}
```

## Workflow architecture

### 1. CI build trigger (platform-backend/platform-web repo)

```yaml
# .github/workflows/ci-build-promote.yml (her servis repo'sunda)
name: CI build + promote

on:
  push:
    branches: [main]

jobs:
  build:
    # ... mevcut build adımları (Docker build + GHCR push)

  promote-to-test:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Generate ledger entry
        run: scripts/generate-ledger.sh ${{ github.sha }}
      - name: Open gitops PR (test overlay update)
        uses: peter-evans/create-pull-request@v6
        with:
          token: ${{ secrets.GITOPS_BOT_PAT }}
          path: <gitops-repo-clone>
          branch: auto-promotion/${{ env.REPO }}-${{ github.sha }}
          title: "auto: promote ${{ env.REPO }} sha-${{ env.SHORT_SHA }} to test"
          body: |
            Auto-generated from CI run #${{ github.run_id }}.
            Ledger: release-candidates/${{ env.REPO }}/${{ github.sha }}.json
            Test smoke gate: pending (after merge)
          labels: auto-promotion, env:test
```

### 2. Test smoke gate (gitops repo)

```yaml
# .github/workflows/test-smoke-after-deploy.yml
on:
  workflow_dispatch:    # ArgoCD sync hook tetikler
  schedule:
    - cron: '*/15 * * * *'  # backup poll

jobs:
  smoke-test:
    steps:
      - name: D29 Up — readiness/liveness
      - name: D29 Functional — endpoint smoke
      - name: D29 Zanzibar — allow/deny synthetic
      - name: Update ledger (verified_in_test or smoke_failed)
        if: success()
        run: scripts/ledger-mark-verified.sh ${{ env.SHA }} test
```

### 3. Prod-candidate PR generator (gitops repo, scheduled)

```yaml
# .github/workflows/prod-candidate-promotion.yml
on:
  schedule:
    - cron: '0 8 * * 1-5'   # Pazartesi-Cuma 08:00 daily candidate scan
  workflow_dispatch:

jobs:
  scan-and-propose:
    steps:
      - name: Find verified-in-test ledger entries without prod PR
        run: scripts/scan-promotion-candidates.sh
      - name: Open prod-candidate PR (DRAFT)
        # ... peter-evans/create-pull-request
        # PR body: ledger snapshot + test smoke evidence + diff
        # Manual review + "merge et" gate
```

### 4. Audit + close-out

ArgoCD prod sync sonrası bir GitHub webhook (veya scheduled job) ledger'ı
"deployed_to_prod" olarak kapatır.

## GitHub permissions

- **GITOPS_BOT_PAT** (GitHub App veya fine-grained PAT)
  - `gitops` repo: contents:write, pull-requests:write, workflows:read
  - Rotation: 90 gün, Vault'tan rotate
- **Branch protection**:
  - `main`: require PR review, require CI green, restrict force-push
  - `auto-promotion/*`: bot otomatik push, normal user push reject
- **Branch namespace**: `auto-promotion/<repo>/<sha>` — auto-cleanup after merge

## Migration playbook

### Faz 1 — Bu PR (design + skeleton script)

- Ledger JSON schema dökümante
- Workflow YAML iskeletleri yazıldı
- `scripts/promotion/` klasörü oluştu (placeholder)

### Faz 2 — CI build update (platform-backend, platform-web — backend repo PR'ları)

- `kubectl set image` step kaldırılır
- `scripts/generate-ledger.sh` çağrısı eklenir
- `peter-evans/create-pull-request` ile gitops repo'ya PR

### Faz 3 — Smoke gate workflow (gitops repo)

- D29 Up/Functional/Zanzibar smoke test workflow
- Ledger marker `verified_in_test`

### Faz 4 — Prod-candidate generator (gitops repo)

- Scheduled scan (daily)
- Manual approval gate (DRAFT PR)

### Faz 5 — kubectl set image deprecation

- CI workflow'lardan tamamen kaldır
- Operator runbook update: artık tek yol PR

## Bağımlılıklar

- **Drift detection MVP** (PR #334) — ledger ↔ cluster live drift kapatma referansı
- **PR-time gate** (PR #335) — promotion PR'larına aynı gate uygulanmalı
- **Quota preflight** (PR #337) — promotion PR'larına aynı gate
- **OpenFGA contract** (PR #336) — backend smoke test referansı
- **RBAC break-glass** (PR #338) — implementation P0d ile bot SA permissions

## Risk + mitigation

| Risk | Mitigation |
|---|---|
| GitHub PAT compromise | Fine-grained scope (gitops only) + 90 gün rotation + audit log |
| Bot PR storm (CI build her commit'te PR) | Filter: only main branch, only diff in image digest |
| Ledger corruption | Schema validation in CI gate; revert PR replays |
| Smoke gate flake → false-positive verified | 3-way confirmation (Up + Functional + Zanzibar each independent) |
| Prod-candidate PR auto-merge | DRAFT default, manual `gh pr ready` + `gh pr merge` |

## Codex P0 sequence

| Sıra | İş | Bağımlılık |
|---|---|---|
| **P0a (bu PR)** | Design doc + ledger schema + workflow iskeleti | — |
| **P0b** | `scripts/promotion/` implementation (generate-ledger, ledger-mark-verified, scan-candidates) | — |
| **P0c** | GitHub App registration + GITOPS_BOT_PAT secret rotation | Operator manual step |
| **P0d** | platform-backend/platform-web CI workflow update | P0b + P0c |
| **P0e** | gitops smoke gate workflow + prod-candidate generator | P0b + P0d |
| **P0f** | kubectl set image deprecation (P0 #5d) | P0e (tüm akış çalışır olduktan sonra) |

## Boundary

Bu PR:
- [x] none of the above (sadece doküman)

Implementation PR'ları (P0b-f):
- [x] state-mutation (test cluster) — gitops repo değişiklikleri test cluster'a deploy yolunu kuracak

## İlişkili belgeler

- ADR-0011 §2.3 boundary declaration
- `docs/operations/rbac-break-glass-design.md` (PR #338) — RBAC complement
- `scripts/drift-detection/` — drift gate complement
- `docs/authz/openfga-model-contract.md` — backend smoke test contract
