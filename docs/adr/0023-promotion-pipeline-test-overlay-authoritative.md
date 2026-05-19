# 0023 — Promotion Pipeline: Test Overlay GitOps-Authoritative

> **Status**: Accepted
> **Tarih**: 2026-05-19
> **Karar otoritesi**: Codex thread `019e40e4` (cross-AI mimari konsensüs — Claude denetim + tasarım, Codex adversarial review)
> **Öncüller**: ADR-0002 (single-host dual-cluster), ADR-0022 (env-baked frontend variant evidence), D29 evidence pipeline (`docs/operations/promotion-ledger-design.md`)
> **Yürütür**: promotion-pipeline hardening initiative — P0 onarım + 7-PR guardrail train

## Context

`dev → test → prod` promotion zinciri 2026-05-19 denetiminde **sistemik sızdırıyor** bulundu. Tetik: bir non-superadmin kullanıcı prod'da rapor sayfalarında `403` alıyor (`admin@example.com` superadmin olduğu için almıyor) — kök neden prod OpenFGA modelinde `report_group` tipinin eksikliği; bu tip test'te var, prod'a hiç taşınmamış.

### Denetim — 4-nokta digest matrisi (Ek A)

prod overlay == prod CANLI her serviste (prod GitOps-tutarlı ✓). Fakat `overlays/test` 8/10 backend serviste test CANLI'dan **farklı** — test cluster'ı ad-hoc `kubectl set image` ile güncellenmiş, overlay YAML hiç güncellenmemiş. Test'te doğrulanan build jenerasyonu **hiçbir YAML'da kayıtlı değil** ve prod'a terfi etmemiş; prod 8 serviste eski jenerasyonu koşuyor.

### Üç boşluk sınıfı

1. **test overlay drift** — `k3d-test` ana workload'ları ad-hoc `kubectl set image` ile değişiyor; `overlays/test/kustomization.yaml` güncellenmiyor → test overlay gerçeği yansıtmıyor.
2. **test→prod terfi manuel + zorlanmıyor** — prod, test cluster'ından sessizce bir build jenerasyonu geride kalabiliyor.
3. **image-dışı artifact'ların promotion pipeline'ı yok** — OpenFGA yetkilendirme modeli, tuple'lar (muhtemelen ConfigMap, DB migration) manuel per-cluster runbook'a bağlı; prod adımı sessizce atlanabiliyor.

### Repodaki çelişki

`docs/operations/promotion-ledger-design.md` PR-first test overlay + ledger hedefini tarif ediyor; ama `deploy-backend-testai.yml` / `deploy-testai.yml` / `scripts/drift-detection/check_prod_drift.sh` test'i imperative (`kubectl set image`) kabul eden fiili yolu taşıyor. Bu ADR çelişkiyi **PR-first lehine** kapatır.

## Decision

### D1 — Ortam rolleri

| Ortam | Rol | Mutasyon disiplini |
|---|---|---|
| `dev` / k3d-dev | Hızlı inner-loop | Serbest, mutable; buradan prod'a kanıt taşınmaz |
| `test` / k3d-test | **Promotion authority** | `overlays/test` + `release-candidates` ledger + smoke = tek doğruluk zinciri |
| `prod` / k3d-prod | Canlı | ArgoCD `platform-prod`, `selfHeal=false`, manuel gated `deploy-prod-gitops.yml` |

### D2 — Test overlay authoritative; ana workload'a ad-hoc `kubectl set image` YASAK

Shared `k3d-test` `platform-test` namespace'indeki **ana workload'lar** (Deployment/StatefulSet) yalnız `kustomize/overlays/test` üzerinden GitOps-managed olarak değişir. Ana workload'a doğrudan `kubectl set image` / `kubectl patch` / `kubectl edit` **YASAK** — overlay'i fiction'a çevirir, promotable truth'u yok eder.

**Makine-okunur tanım** (guardrail PR-3/PR-4 enforcement bu ayrımı kullanır):
- *ana workload* = `kustomize/overlays/test` render'ında çıkan, `docs/operations/services.yaml`'da enabled bir servisin Deployment/StatefulSet'i.
- *transient workload* = ADR-0022 label kontratını taşıyan kaynak: `evidence.platform/transient-smoke` + `evidence.platform/smoke-run` label'ları olan, yönetilen bir servis adını taşımayan, TTL + `trap` cleanup zorunlu kaynak.

İzin verilen istisnalar:
- `k3d-dev` — serbest.
- ADR-0022 `frontend-prod-variant-transient-smoke` gibi **transient** workload'lar (per-run etiketli, `trap` cleanup; ana workload'ı mutate etmez).
- **Break-glass** — yalnız dört koşul birlikte: (a) açık gerekçe + board issue, (b) TTL, (c) drift alarmı tetiklenmiş kabul, (d) aynı incident içinde overlay reconciliation PR'ı açılır.

### D3 — prod modeli korunur, preflight güçlendirilir

prod ArgoCD `selfHeal=false` + manuel `deploy-prod-gitops.yml` + `production` environment approval **değişmez** (ADR-0002 + D30 disiplini). Eklenen tek şey: ArgoCD sync öncesi artifact-dependency preflight (guardrail PR-7).

### D4 — image-dışı artifact'lar için promotion ledger

OpenFGA yetkilendirme modeli — ve sonraki kind'lar: canonical/bootstrap tuple migration, config-contract, DB migration level — `runtime-artifacts/<kind>/<id>.json` ledger'ı kazanır; D29 image ledger'ına analog test→prod evidence zinciri. Dinamik iş yetkileri (kullanıcı-bazlı tuple'lar) app state olarak kalır, GitOps'a çekilmez (over-engineering).

### D5 — Guardrail train

Hardening yedi PR ile uygulanır: (PR-1) bu ADR + `AGENTS.md`, (PR-2) `platform-test` ArgoCD app + kısıtlı runner RBAC, (PR-3) test deploy workflow'ları → GitOps PR, (PR-4) `check_env_drift.sh` test+prod drift gate, (PR-5) promotion-lag/generation gate, (PR-6) image-dışı artifact ledger, (PR-7) prod deploy artifact-dependency preflight.

P0 onarım (mevcut bozuk durum) sırası: promotion freeze → `overlays/test` realign → OpenFGA `report_group` prod migration → 8-servis backend generation promotion → post-sync proof. P0 onarım penceresinde prod promotion yalnız bu yapılandırılmış P0 adımlarından geçer (freeze).

## Consequences

- (+) `overlays/test` güvenilir, promotable kaynak olur — prod-candidate cluster belleğinde yaşamaz; rollback/audit/D29 zinciri korunur.
- (+) drift + promotion-lag + artifact-skip CI'da otomatik yakalanır, sessiz kalmaz.
- (+) image-dışı artifact'lar (OpenFGA modeli) ilk kez evidence-tracked + test→prod gate'li.
- (−) test deploy'u PR-mediated olur → CI + ArgoCD sync kadar ek gecikme. Inner-loop hızı `k3d-dev`'de korunur, kayıp değil.
- (−) `platform-test` ArgoCD app + kısıtlı runner RBAC tek-seferlik kurulum gerektirir (guardrail PR-2).

## Alternatives

- **Test'i imperative bırak, yalnız drift gate ekle** — reddedildi (Codex `019e40e4`): drift gate kaymayı *raporlar* ama sistem yine cluster belleğinde yaşayan "kanıtlanmış" jenerasyonlar üretmeye devam eder; promotable truth hiçbir YAML'da olmaz. Kök neden kapanmaz.

## Ek A — Promotion denetim baseline (2026-05-19)

Digest'ler `sha256:` ön-ekinden sonra ilk 12 hane. **Overlay drift** = `overlays/test` render'ı ≠ test CANLI pod imageID (ad-hoc `kubectl set image` overlay'e yansımamış).

| Servis | test overlay | test CANLI | overlay drift | prod overlay | prod CANLI |
|---|---|---|---|---|---|
| api-gateway | `bb95149a3d5f` | `6175711ae208` | ⚠ drift | `bb95149a3d5f` | `bb95149a3d5f` |
| auth-service | `81499ba09e24` | `6820e91e57da` | ⚠ drift | `81499ba09e24` | `81499ba09e24` |
| core-data-service | `ec5cfd1b9ce3` | `040ddddf2163` | ⚠ drift | `ec5cfd1b9ce3` | `ec5cfd1b9ce3` |
| notification-orchestrator | `caf02c248bb6` | `caf02c248bb6` | — eşit | `70491543fdc3` | `70491543fdc3` |
| permission-service | `6cf81e19b7e3` | `a87b8c3959cd` | ⚠ drift | `6cf81e19b7e3` | `6cf81e19b7e3` |
| report-service | `5ddbc6199bf9` | `5ae0c4d6ee32` | ⚠ drift | `7f3f71d67eae` | `7f3f71d67eae` |
| schema-service | `894e492f029c` | `2f80e2a98c12` | ⚠ drift | `894e492f029c` | `894e492f029c` |
| variant-service | `70106d05b75c` | `00bcbc24f8fa` | ⚠ drift | `70106d05b75c` | `70106d05b75c` |
| user-service | `c94c057cde2b` | `fce3096eb994` | ⚠ drift | `fce3096eb994` | `fce3096eb994` |
| frontend | `16ffc7f1cc33` (testai) | `b44b551af8e4` (testai) | ⚠ drift | `7e0999d1865a` (prod) | `7e0999d1865a` (prod) |
| endpoint-admin-service | `5bb0fa2600f0` | `5bb0fa2600f0` | — eşit | — (prod'da deploy yok) | — |

Özet: `overlays/test` **8/10 backend servis + frontend**'de test CANLI'dan farklı (overlay drift); yalnız notification-orchestrator + endpoint-admin overlay==CANLI. **prod overlay == prod CANLI her serviste** (prod GitOps-tutarlı; ArgoCD `platform-prod` Synced+Healthy). user-service + frontend 2026-05-19 prod'a terfi edildi (PR #835/#837); kalan 8 backend prod'da hâlâ eski jenerasyonda.

OpenFGA yetkilendirme modeli (image-dışı): test store modeli `01KRTJVEMAW80B2D35GN8HJDPG` → `report_group` tipi **var**; prod store modeli `01KPXCVBMDKXXRPGKFGPDRVBQX` → `report_group` tipi **yok**.

## Referanslar

- Codex thread `019e40e4` — cross-AI mimari konsensüs (target model + P0 onarım + 7-PR guardrail train)
- ADR-0002 (single-host dual-cluster), ADR-0022 (env-baked frontend variant evidence)
- `docs/operations/promotion-ledger-design.md` + `docs/operations/d29-evidence-pipeline-design.md` — D29 evidence pipeline tasarımı
- `docs/RB-openfga-report-group-migration.md` — image-dışı artifact gap'in canlı örneği (test-only koşulmuş runbook)
- Mevcut guardrail'ler: `.github/workflows/gate-drift-detection.yml`, `gate-drift-pr-time.yml`, `openfga-model-drift.yml`, `gate-d29-evidence-required.yml`; `scripts/drift-detection/`
