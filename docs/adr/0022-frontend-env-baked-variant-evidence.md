# 0022 — Env-Baked Frontend Variant Promotion Evidence

> **Status**: Accepted
> **Date**: 2026-05-19
> **Decision authority**: Codex thread `019e3f7e` (cross-AI architecture consensus — kod yazan Claude, mimari onaylayan Codex; VERDICT: **A-lite**, Option C reddedildi)
> **Predecessors**: ADR-0014 (MFE Auth Transport Contract), D29 evidence pipeline (Codex Sprint A P0 — `docs/operations/d29-evidence-pipeline-design.md`)
> **Drives**: board #820 — frontend prod-variant promotion evidence path

## Bağlam

platform-web frontend, Vite ile derlenen statik bir SPA'dır. Ortam konfigürasyonu — API base URL, Keycloak realm/issuer, realm-client redirect, feature-flag'ler, bootstrap-config — **build-time'da** `VITE_*` değişkenleriyle JS bundle'ına **gömülür** (env-baked). Runtime env injection yoktur.

Sonuç: her kaynak commit'i için **iki ayrı artifact** üretilir:

| Variant | GHCR image | Env-baking |
|---|---|---|
| testai | `platform-web-frontend-testai` | `testai.acik.com` + realm `platform-test` |
| prod | `platform-web-frontend` | `ai.acik.com` + realm `serban` |

D29 evidence pipeline (`gate-evidence-check.py`) her prod-overlay digest değişimi için `release-candidates/` ledger entry'sinde `promotion.test.smoke_evidence` GREEN şartı arar. Bu pipeline **backend** servisleri için tasarlandı — orada **aynı image** önce test'te sonra prod'da koşar; test smoke'u prod'a giden artifact'ı birebir doğrular.

Env-baked frontend'de bu varsayım kırılır: test cluster'ı **testai variant**'ı koşar — prod variant'tan **farklı bir artifact**. Prod variant'ın prod API base URL'i, realm-client-redirect yüzeyi, feature-flag ve bootstrap-config gömülü hâli **hiçbir yerde** test edilmez. Bir testai-sibling smoke'u, prod artifact'ının gerçek build yüzeyine dokunmaz.

**Gap**: prod-variant frontend digest'i D29 gate'ini normal yolla geçemez — o tam artifact'ın bir test-cluster koşumu yoktur.

## Karar

### D1 — Kabul edilen evidence class: `frontend-prod-variant-transient-smoke`

Prod-variant artifact'ının **kendisi** k3d-test cluster'ında (`platform-test` namespace) **transient** olarak koşturulur ve orada smoke edilir. Bu, gerçek ledger evidence üretir: prod artifact gerçekten çalıştı, içerik sundu, env-baking'i denetlendi. Source-parity hand-wave değil — artifact'ın kendi koşum kanıtı.

### D2 — Transient izolasyon

Smoke; benzersiz etiketli (`evidence.platform/transient-smoke` sınıf etiketi + per-run id) bir Deployment + Service yaratır, `trap` ile her çıkışta temizler. Resource adları da per-run id taşır → eşzamanlı oturumlar birbirini silmez. Cluster'ın yönetilen `frontend` (testai) workload'ına **dokunmaz** — ne scale eder ne image değiştirir (TEST Cluster Scale-to-Zero HARD RULE ihlali yok; yalnız kısa ömürlü ek bir pod). Script: `scripts/smoke/d29-frontend-variant-smoke.sh`.

### D3 — Frontend profili: üç-katman evidence eşlemesi

| Tier | Verdict | Kanıt |
|---|---|---|
| `d29_up` | **GREEN** | rollout success + pod Ready + pod imageID digest == beklenen + `/build-info.json` `.sha` == kaynak commit SHA |
| `d29_functional` | **GREEN** | `/` 200 + entry + `/remoteEntry.js` asset'leri 200 + **env-baking assertion**'ları (bundle'da `testai.acik.com`/`localhost:8080` host **ve** `platform-test` realm YOK; prod-host `https://ai.acik.com` **ve** `serban` realm VAR) + canlı prod API/OIDC yüzeyinin (`ai.acik.com`) read-only public probe'u `2xx/401/403` döner (`5xx/000` değil) |
| `d29_zanzibar` | **AMBER** (`allow_deny_synthetic: SKIP`) | frontend statik SPA — kendi JWT decoder'ı yok, Zanzibar authz düzlemi yok (`jwt_validates: false`, `services.yaml`). Zanzibar tier not-applicable; **AMBER dürüst non-GREEN verdict'idir** — sahte GREEN değil, anlamsız değil. |

### D4 — Gate uyumu (kod değişimi YOK)

`gate-evidence-check.py` zaten `jwt_validates: false` servisler için `d29_zanzibar` değerini **GREEN veya AMBER** kabul eder (`services.yaml`'da `frontend` → `jwt_validates: false`). `d29_up` + `d29_functional` GREEN şartı korunur. Yani bu evidence class mevcut pipeline'ı **hiç değiştirmeden** gate-satisfying'dir.

Önemli sınır: `gate-evidence-check.py` `d29_zanzibar` için `SKIP` **status'ünü kabul etmez** — yalnız `GREEN`/`AMBER`. Bu yüzden frontend ledger'ında tier-status `AMBER`, alt-alan `allow_deny_synthetic` ise `SKIP`'tir.

Ledger **elle** doldurulur — `ledger-mark-verified.sh` kullanılmaz: o script her tier'in GREEN olmasını ister (defense-in-depth) ve frontend'in dürüst `d29_zanzibar=AMBER`'ını reddeder. Frontend profili bu otomasyonun açık istisnasıdır.

### D5 — Browser end-to-end post-cutover'dır

Prod variant `ai.acik.com` + realm `serban` için env-baked'dir; k3d-test içinde browser-login E2E'si **yapılamaz** (yanlış realm/redirect yüzeyi). Tam browser E2E prod-sync sonrası `ai.acik.com`'a karşı (operator-gated) yapılır. Transient smoke **pre-prod gate evidence**'ıdır — nihai kabul değil. Frontend "Tarayıcıdan Doğrulama" HARD RULE'u post-sync operator verify ile karşılanır.

## Sonuçlar

- (+) Prod-variant frontend digest'leri gerçek, ledger'a kayıtlı D29 evidence kazanır — sessiz drift yok, source-parity el sallaması yok.
- (+) `gate-evidence-check.py` / schema değişmez — mevcut pipeline içinde çalışır.
- (+) Tekrar kullanılabilir: gelecekteki her env-baked variant (tenant-başı build vb.) aynı transient-smoke class'ını kullanır.
- (−) Smoke cluster erişimi ister (staging-sw host execution — `d29-smoke-runner.sh` ile aynı desen); GitHub-hosted runner private cluster'a erişemez.
- (−) Transient pod k3d-test'e kısa süreli yük ekler; tek replica + `trap` cleanup + kısa ömür ile sınırlandı.
- (−) `d29_zanzibar=AMBER` ledger'ın elle doldurulmasını gerektirir (auto `ledger-mark-verified.sh` yolu dışında). Belgelendi; frontend profili açık istisnadır.

## Alternatifler

- **Option C — `source-parity-with-test-verified-sibling`**: prod variant'ı, aynı kaynak SHA'dan üretilen testai-kardeş variant test smoke'unu geçtiği için kabul et. **Reddedildi** (Codex `019e3f7e`): env-baking nedeniyle testai smoke prod artifact'ının gerçek build yüzeyini test etmez. Source parity gerekli ama yeterli değil — tek başına gate-satisfier olamaz.
- **Option B — prod variant'ın k3d-test'te tam browser E2E'si**: mümkün değil — prod variant `ai.acik.com`/`serban` için baked; k3d-test'te realm/redirect uyuşmaz.
- **Option A (full) — prod variant'ı pre-prod'da kalıcı bir ortamda koşturmak**: israf; transient A-lite aynı evidence'ı kalıcı workload olmadan üretir.

## Referanslar

- Codex thread `019e3f7e` — A-lite verdict + 7-adımlı plan
- `docs/operations/d29-evidence-pipeline-design.md` — D29 evidence pipeline (frontend profili eklendi)
- `scripts/smoke/d29-frontend-variant-smoke.sh` — transient smoke runner
- `scripts/promotion/gate-evidence-check.py` — D29 prod gate (`jwt_validates:false` → GREEN/AMBER policy)
- ADR-0014 (MFE Auth Transport Contract), ADR-0021 (M365 SSO — realm `serban` bağlamı)
- board #820
