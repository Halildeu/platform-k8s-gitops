# ADR-0003: Inner-Loop Tooling Ownership Between platform-ssot and platform-k8s-gitops

**Status**: Accepted (2026-04-24, Faz 17.6)
**Superseded by**: —
**Date**: 2026-04-24
**Context owner**: Faz 17 Local Dev Environment Parity
**Codex review**: thread `019dbe80` iter-4 AGREE

---

## Context

`autonomous-orchestrator` platformu iki repo arasında bölünmüştür:

- **platform-ssot** (`/Users/halilkocoglu/Documents/dev/`): Java backend + MFE frontend application code, Dockerfile, Maven/Gradle build config, Flyway DB migration SQL
- **platform-k8s-gitops** (bu repo): Kubernetes manifest (Kustomize overlay), ArgoCD Application, CI/CD workflow, runbook, operational scaffolding

Faz 17 Local Dev Environment Parity implementasyonu sırasında Codex adversarial review (thread `019dbe80`) sırasında **cross-repo ownership drift riski** tespit edildi:

> "Tiltfile iki repoda birden tutmak repo sınırını bulanıklaştırır. Bu repo desired-state/ops repo; source/build/artifact otoritesi platform-ssot."

Codex iter-4 cümle:

> "ADR yazmayacaksan bunu yalnız `promotion-contract.md` içine gömme; en azından `CONTRIBUTING.md` ve local-dev dokümanında authoritative ownership cümlesi net dursun."

Bu ADR, opsiyonel (Codex iter-4 "ADR opsiyonel kalabilir ama ownership kalıcıysa yaz") olarak yazılır ve inner-loop tooling (Tilt, code watch, image build, dev-script orchestration) için **authoritative ownership** kuralını repo sınırı bozulmayacak şekilde mühürler.

---

## Decision

**Inner-loop tooling ownership matrix**:

| Sorumluluk | platform-ssot | platform-k8s-gitops |
|---|---|---|
| Application code (Java backend + MFE frontend) | **Authoritative** | — |
| Dockerfile | **Authoritative** | — |
| Maven/Gradle build config | **Authoritative** | — |
| Flyway DB migration SQL (`V<N>__*.sql`) | **Authoritative** | — |
| **Tiltfile** (code watch + image build + live_update) | **Authoritative** | — |
| Code watch patterns (dev-loop inner iteration) | **Authoritative** | — |
| Image build logic (`docker_build`, `custom_build`) | **Authoritative** | — |
| K8s manifest (Deployment, Service, ConfigMap, PDB, ServiceAccount) | — | **Authoritative** |
| Kustomize overlay (test/prod/local-*) | — | **Authoritative** |
| ArgoCD Application CR | — | **Authoritative** |
| CI/CD workflow (manifest lint, render sanity) | — | **Authoritative** |
| **Dev scripts** (`dev-up/down/seed/smoke`) | — | **Authoritative** |
| Fixture scaffolding (`bootstrap/local-fixtures/`) | — | **Authoritative** |
| Local edge TLS (`bootstrap/local-edge/`) | — | **Authoritative** |
| Runbook, promotion-contract, operational docs | — | **Authoritative** |
| CI build (image → GHCR) | **Authoritative** | — |
| CI manifest render + lint | — | **Authoritative** |

**Kural**: Tiltfile **sadece** platform-ssot'ta kalır. Bu repo'da (`platform-k8s-gitops`) Tiltfile **yoktur**. Dev-loop geliştirici akışı ssot Tiltfile `k8s_yaml(kustomize('../platform-k8s-gitops/kustomize/overlays/local-$profile'))` ile bu repo'nun overlay'lerini tüketir.

### Cross-Repo Değişim Protokolü

Ownership matrix değişirse **her iki repo CONTRIBUTING.md senkron güncellenir**. Unilateral yazım (tek repoda değişim) ownership drift üretir ve Codex iter-4 bulgusudur. Önlemler:
- Bu repo CONTRIBUTING.md'de 3-tier + ownership matrix var (Faz 17.5)
- platform-ssot CONTRIBUTING.md'de **aynı cümle** bekleniyor (Faz 17.6 cross-repo PR)
- Değişim PR'ları her iki repo'da **aynı gün** merge edilir (drift penceresi kapalı)

---

## Consequences

### Pozitif

1. **Tek authoritative source per boundary**: Tiltfile'ın platform-ssot'ta kalması, code watch ve image build hızlı iterasyonunu merkezleştirir (Maven/Gradle proximity).
2. **Manifest drift önleme**: Bu repo'nun tek sorumluluğu desired-state manifest; çoklu dev tool dağıtımı yok.
3. **Cross-repo senkron**: Ownership matrix iki repo'da aynı görünür; geliştirici hangi repo'ya PR açacağını anlık bilir.
4. **Promotion contract desteği**: Faz 17.4 `docs/promotion-contract.md` 3-tier akışı bu ownership matrix'e referans verir.

### Negatif

1. **Cross-repo PR orchestration**: Ownership değişim (nadir) her iki repo'da **aynı zamanda** PR gerektirir. Geliştirici koordinasyonu gerekir.
2. **Tiltfile referans path**: `k8s_yaml(kustomize('../platform-k8s-gitops/kustomize/overlays/local-$profile'))` göreli path — iki repo'nun **aynı parent dizinde checkout** edilmesi gerekli (`~/Documents/dev/` + `~/Documents/platform-k8s-gitops/`).
3. **Overlay değişim etkisi**: Bu repo'da yeni profile overlay (`local-Z`) eklenirse Tiltfile profile-switch logic güncellenebilir (ama backward-compatible default var).

### Nötr

1. **Mevcut GitOps workflow değişmez**: ArgoCD `platform-test` + `platform-prod` Application CR bu repo'yu source tutmaya devam eder.
2. **CI boundary değişmez**: ssot CI image push (GHCR); bu repo CI kustomize lint (Faz 17.Z).

---

## Alternatives Considered

### Alternative 1: Hem-iki-repo'da thin Tiltfile

**Reddedildi** (Codex iter-1 bulgu): Tiltfile'ı her iki repo'da ince tutarak "source-mirror" pattern'i deneme. Sorun: Değişim sinkronizasyon riski (iki Tiltfile drift edince hangisi canonical?), geliştirici hangi repo'ya PR açacağını her seferinde düşünmek zorunda.

### Alternative 2: Tiltfile ayrı dedicated repo

**Reddedildi** (overhead): Tek fayda izolasyon; ama 3-repo sinkronizasyon ≥ 2-repo sinkronizasyon. Bir örnek daha eklemek işletme değeri düşük.

### Alternative 3: Devcontainer (VS Code)

**Ertelendi** (Faz 17 scope dışı): Devcontainer yardımcı olabilir (yerel hızlı onboarding), ancak ana dev-loop pattern değil. Gelecek Faz 18+ değerlendirilebilir.

### Alternative 4: Telepresence (remote dev)

**Reddedildi** (Codex iter-1): Telepresence ana pattern olmamalı — k3d-dev lokal cluster MVP için yeterli, remote dev (staging-sw'ye kod push) dev-loop yavaş (15-30s).

---

## Implementation Status

- [x] `platform-k8s-gitops/CONTRIBUTING.md` 3-Tier Topoloji + Ownership Matrix (Faz 17.5, PR #91)
- [x] `platform-k8s-gitops/docs/promotion-contract.md` §6 Ownership Matrix (Faz 17.4, PR #91)
- [x] `platform-k8s-gitops/PLAN.md` §17.6 cross-repo ownership cümle (Faz 17 iter-4 AGREE)
- [ ] `platform-ssot/CONTRIBUTING.md` aynı cümle + Tiltfile ownership (cross-repo PR — Faz 17 devam)
- [ ] `platform-ssot/Tiltfile` authoritative implementasyon (Faz 17 devam)
- [ ] `platform-ssot/README.md` inner-loop tooling referansı (Faz 17 devam)

---

## Reversal Conditions

Bu ADR reverse edilebilir (ownership matrix değişimi) eğer:

1. **Tiltfile dışında başka inner-loop tool** (örn. Skaffold, DevSpace) seçilir ve iki repo'da distribute edilirse
2. **Platform-ssot deprecate edilir** — ancak bu senaryoda bu ADR zaten geçersiz
3. **Mono-repo birleşme** (iki repo tek repo olur) — bu durum ADR-0002 ile de çelişir

Reversal için: Yeni ADR (ADR-0004+) yazılır, bu ADR status "Superseded by ADR-0N" olur. Cross-repo senkron update zorunlu.

---

## References

- [Codex thread `019dbe80`](https://platform-gitops-codex.acik.com/threads/019dbe80) iter-4 AGREE (Faz 17 tamamı)
- [PLAN.md §17.6](../../PLAN.md) — Repo Split Decision
- [docs/promotion-contract.md](../promotion-contract.md) — §6 Ownership Matrix
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — 3-Tier Topoloji + Ownership Matrix
- [ADR-0002](./0002-single-host-dual-cluster.md) — D31 PG primary, ADR ile çelişmez
