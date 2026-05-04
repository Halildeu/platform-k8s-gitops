# Renovate Auto-Bump Configuration — Faz N (D36 PLAN.md karar)

> Codex 2026-04-28 D35-3 closure flow gözlemi: backend PR #18 merge → image push GHCR
> → **manuel** PR #242 digest pin → manuel rollout. Frontend de aynı pattern.
>
> **D36 karar**: Renovate ile auto-bump bot kurulur. **D27 uyumlu** (Renovate
> community-standard tool, custom kod değil; ArgoCD Image Updater'dan farklı).

## Sorun

Mevcut promotion flow:

```
[Backend kod değişim]
    ↓
[CI build + GHCR push (sha-<commit>)]
    ↓
[Manuel PR: gitops repo'da kustomization.yaml digest pin update]
    ↓
[Manuel rollout]
```

Manuel PR adımı insan-zaman-bağımlı:
- Operator/dev her image update için manuel PR açıyor
- PR sıraya giriyor, geç merge
- Bazen unutulup geride kalıyor (frontend drift gibi)
- Hata payı yüksek (yanlış digest, eksik overlay update)

## Çözüm — Renovate

`.github/renovate.json` config ile bot otomatik:

1. GHCR'ı periyodik (Pazartesi-Cuma 07:00 sonrası) tara
2. `kustomize/overlays/test/**` `kustomize/overlays/prod/**` dosyalarındaki
   `image: ghcr.io/halildeu/...@sha256:<digest>` referanslarını bul
3. Yeni digest varsa PR aç
4. PR body'de boundary declaration auto-fill (D17)
5. CI gate'leri (drift PR-time, D29 evidence required) doğal akışla geçer

## Konfigürasyon Detayları

### Schedule

```json
"schedule": ["after 7am every weekday"]
```

Pazartesi-Cuma 07:00 sonrası — Türkiye iş saati başı. Test overlay PR'ları
operator review window'una düşer.

### Path-based Rules

| Path | Behavior |
|---|---|
| `kustomize/overlays/test/**` | `auto-bump`, `automerge: false`, label `env:test`, boundary auto-fill `state-mutation (test cluster)` |
| `kustomize/overlays/prod/**` | `auto-bump`, `automerge: false`, **DRAFT PR** (`draftPR: true`), label `env:prod` + `user-approval-required`, boundary auto-fill `state-mutation (production)` + D30 cutover checklist |
| `helm-values/**` | minor/patch only (no major) |
| `.github/workflows/**` | patch + digest pin updates |

### Boundary Declaration Auto-fill

Test overlay PR template (boundary auto-checked):
```markdown
## Boundary declaration (ADR-0011 §2.3)
- [x] state-mutation (test cluster)

User-approval evidence: Renovate auto-bump, test cluster only.
```

Prod overlay PR template (boundary auto-checked + D30 cutover gate):
```markdown
## ⚠️ PROD digest update — D30 atomic cutover discipline
- [ ] D29 evidence ledger doğrulandı (release-candidates/<repo>/<sha>.json verified)
- [ ] gate-d29-evidence-required CI yeşil
- [ ] Operator manuel cutover decision
- [ ] Pre-cutover bundle snapshot (T-24h) yapıldı
- [ ] Rollback plan hazır

## Boundary declaration (ADR-0011 §2.3)
- [x] state-mutation (production)

User-approval evidence: Renovate auto-bump DRAFT, prod cluster atomic cutover discipline (D30).
```

### Digest-Only Updates

```json
{
  "matchPackageNames": ["ghcr.io/halildeu/**"],
  "matchUpdateTypes": ["digest"],
  "groupName": "platform image digest sync",
  "groupSlug": "platform-digest-sync"
}
```

Sadece digest update'leri grup PR'da; semver bumps operator decision (gerek yok auto-bump).

### Concurrency Limits

```json
"prConcurrentLimit": 5,
"prHourlyLimit": 2
```

5'ten fazla concurrent PR yok (review burnout korunur).
Saatlik 2 PR limit (rate limit + spam koruma).

## Promotion Bot ile Uyumlanma

| Pattern | Trigger | Output |
|---|---|---|
| **Renovate** | Cron + GHCR poll | digest pin update PR |
| **promotion-bot** (Sprint B B5) | Test smoke GREEN sonrası ledger update | prod-candidate DRAFT PR |

İkisi farklı katmanda çalışır:
- Renovate: **GHCR registry → gitops repo** (image pin discovery)
- Promotion bot: **gitops repo → cluster** (test→prod gate flow)

Çatışma yok — ardışık katmanlar.

Daha doğrusu:
1. Backend CI image push GHCR (yeni digest)
2. Renovate polls → test overlay PR aç (24h içinde)
3. PR merge → ArgoCD test sync → cluster digest update
4. smoke-test.timer 30min sonra D29 smoke
5. ledger-mark-verified.sh → ledger entry verified
6. promotion-bot scheduled (08:00 cron) → prod DRAFT PR
7. Operator manuel review + merge
8. ArgoCD prod sync

Renovate **adım 2**'yi otomatize eder. Promotion bot **adım 6**'yı.

## ignorePaths

```json
"ignorePaths": [
  "release-candidates/**",
  "tests/promotion/fixtures/**",
  "schema/**"
]
```

Bu yollarda image referansları bulunabilir (test fixtures, vb) ama auto-bump
yapılmamalı.

## ignoreDeps

```json
"ignoreDeps": [
  "halildeu/platform-backend-endpoint-admin-service"
]
```

endpoint-admin-service services.yaml'da `prod=deferred` olduğu için Renovate
prod overlay'inde aramamalı (zaten yok). Test overlay için manual decision
(Faz 22.1 onboard ile aktif olacak).

## Operator Setup (manuel, post-merge)

### 1. Renovate App install (GitHub Apps)

```
GitHub → Settings → Applications → Renovate
Install on: Halildeu/platform-k8s-gitops
Permissions: Read code + Write PRs + Read packages
```

### 2. Initial config validation

```bash
npx --yes renovate --platform=github --token=$GITHUB_TOKEN \
  --dry-run=full Halildeu/platform-k8s-gitops
```

### 3. First run observability

```bash
gh run list --repo Halildeu/platform-k8s-gitops --workflow renovate
gh pr list --repo Halildeu/platform-k8s-gitops --label renovate
```

## Vulnerability Alerts

```json
"vulnerabilityAlerts": {
  "labels": ["security", "renovate"],
  "automerge": false,
  "schedule": ["at any time"]
}
```

Security advisories için schedule kapatılır (immediately fire). Operator
yüksek priority review.

## Bilinen TODO (post-merge)

- [ ] GitHub App install (operator manual)
- [ ] First synthetic test (dummy digest update)
- [ ] Renovate dashboard (config:dependencyDashboard) → review burdened
- [ ] Backend CI integration sonrası (Sprint B B3) Renovate vs CI direct push
      uyumlandırma — Codex consult önerilir
- [ ] PR body template review (Codex consult, multi-language Turkish/English mix)

## Ne YAPMAZ

- Otomatik merge (security hariç) → `automerge: false` her path için
- Major version bump → `matchUpdateTypes: ["minor", "patch"]` helm/actions için
- Custom dep manager → upstream-first prensibi (D27)

## Codex Consult İhtiyacı

Bu PR içinde değil, post-merge review:
- Renovate vs promotion-bot priority (Sprint B B3 cross-repo CI integration ile)
- Test overlay auto-merge enable etme zaman (smoke gate stabilite sonrası)

## See also

- D36 karar (PLAN.md line 220+)
- ADR-0011 §2.3 (Boundary declaration spec)
- `scripts/promotion/scan-promotion-candidates.sh` (post-D29 prod-candidate)
- `.github/workflows/promotion-bot-scan-candidates.yml` (Sprint B B5)
