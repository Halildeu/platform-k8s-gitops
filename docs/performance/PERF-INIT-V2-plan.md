# Performance Optimization Initiative — Project Management Document v2.0

> **Belge kodu**: `PERF-INIT-V2`
> **Tarih**: 2026-05-11
> **Sahip**: Halil
> **AI Orchestration**: Claude (implementer default) + Codex (reviewer default)
> **Status**: Onay bekliyor (Halil sign-off + AI consensus ✅)
> **AI Consensus thread'leri**: `019e1dc8` (mutabakat ana) + `019e1de0` (bağlamsız adversarial AGREE)
> **Hedef commit**: `docs/performance/PERF-INIT-V2-plan.md`

---

## 1. Yönetici Özeti

**Problem** (canlı ölçümler, 2026-05-11):

- `/home` cold load **14.4 MB transfer / 50 MB decoded JS** (sektör 30× üzeri)
- `/admin/reports` warm **TBT 2937 ms** (10 long task / 3.4 s toplam main-thread blocking)
- HTTP/1.1 (h2 multiplexing yok)
- Memory 237 MB JS heap (kabul edilebilir ama mobil için yüksek)
- LCP/FCP/INP **ölçülemedi** (PerformanceObserver harness yok)

**Hedef**: 0-3 ay hard pass + 12-ay leader path. `ai.acik.com` (Faz G) prod cutover öncesi performans baseline + regression ratchet kurmak.

**Yaklaşım**:

1. **Ölçüm-driven** — önce attribution (PR-A0), sonra refactor. Kanıtsız iş yok.
2. **Route-based budget** — tek global gate değil, route × cache mode matrisi.
3. **Cross-AI peer review HARD RULE** — code yazan AI ≠ reviewer.
4. **Regression ratchet** — warn-only 2 hafta → %5 hard fail.
5. **Cluster stabilite paralel iz** — zincir-fail önleme (PR-S1 + PR-S2).

**Süre tahmini**: hard path 13 PR + paralel iz 1 PR + conditional leader 4 PR = **18 iş paketi**.

---

## 2. Hedef Matrisi (KPI)

### 2.1 Route × Cache Mode × Metrik

| Route × Mode | Transfer (hard / leader) | Decoded JS (hard / leader) | Long task (hard / leader) | Web Vitals |
|---|---|---|---|---|
| `/login` cold anonim | <800 KB / <300 KB | <3 MB / <1 MB | 0 | FCP <1.8s/<1.0s |
| `/home` cold auth | <3 MB / <1.5 MB | **<12 MB / <6 MB** | max <250ms count ≤2 / <150ms count ≤1 | LCP <2.5s/<1.5s |
| `/home` warm fresh | <1 MB / <300 KB | <4 MB / <2 MB | max <200ms / <150ms | INP <200ms/<100ms |
| `/admin/users`, `/admin/access` cold | <6 MB / <3 MB | <18 MB / <8 MB | max <300ms count ≤3 | CLS <0.1/<0.05 |
| `/admin/reports` cold | <8 MB / <4 MB | <22 MB / <12 MB | max <400ms count ≤4 total <600ms | TBT <600ms hard, <50ms advisory |
| Soft nav (`/home → /reports`) | <2 MB | <8 MB | max <300ms | — |
| SSO return (`/login → KC → /home`) | advisory | advisory | advisory | diagnostic |

### 2.2 Mevcut durum vs hedef baseline

| Metrik | ŞU AN | 0-3 ay hard | 12-ay leader |
|---|---|---|---|
| `/home` transfer cold | 14 419 KB 🔴 | <3 MB | <1.5 MB |
| `/home` decoded | 49 947 KB 🔴 | <12 MB | <6 MB |
| `/admin/reports` TBT | 2 937 ms 🔴 | <600 ms | <50 ms (adv) |
| HTTP protokol | HTTP/1.1 🟡 | h2 | h2/h3 |
| LCP/FCP/INP | ölçülemedi ⬛ | dolu metric | dolu metric |
| Cache hit warm | %82 ✅ | korunur | korunur |
| Resource count `/home` | 186 | <120 | <80 |

---

## 3. Kapsam

### 3.1 In-scope

- `platform-web` MFE refactor (shell + design-system + remotes)
- `platform-k8s-gitops` nginx config (HTTP/2, cache, brotli)
- `platform-backend` Spring config root-cause fix (PR-S2 sadece — geniş backend refactor değil)
- Measurement harness, CI gates, performance budgets, RUM extension

### 3.2 Out-of-scope (bilinçli)

- Service worker yeni implementation (Codex riski, MFE versioning karmaşık)
- Faz G prod cutover (ayrı initiative)
- Major framework migration (React 19, Vite major)
- Backend microservice business logic refactor
- AG Grid major version upgrade
- ECharts major version upgrade
- Image optimization (asset payload zaten düşük)
- CDN migration

---

## 4. Work Breakdown Structure (WBS)

> Her iş paketi: **Scope · Kabul Kriterleri · Test Stratejisi · Bağımlılık · Risk · Ownership**

### 4.1 Faz Stabilizasyon (S)

#### PR-S1 — Cluster Secret Drift Workaround

- **Repo**: `platform-k8s-gitops`
- **Scope**:
  - `scripts/ops/rotate-pg-vault-user.sh` (Vault canonical → ALTER USER → ESO sync → pod-network smoke)
  - `scripts/ops/kc-bootstrap-admin-recovery.sh` (KC password drift recovery)
  - `docs/RB-pg-vault-secret-parity.md` (runbook)
  - `kustomize/base/drift-detector/cronjob.yaml` (CronJob, her 30 dk drift check + alert)
  - Alphanumeric password policy doc
- **Kabul Kriterleri**:
  - [ ] Tüm pod 1/1 Running
  - [ ] ESO `SecretSynced=True` her servis için
  - [ ] CrashLoopBackOff yok
  - [ ] Pod-network smoke pass (NOT 127.0.0.1=trust)
  - [ ] CronJob drift detector aktif, alert kurulu
  - [ ] KC bootstrap-admin recovery test edildi (drill)
- **Test**:
  - Unit: shell script bash test (mock vault + mock pg)
  - Integration: test cluster'a uygula, manuel password drift simüle et + auto-recovery doğrula
  - Smoke: tüm 8 backend servis `/actuator/health` UP
- **Bağımlılık**: yok (paralel iz başlangıcı)
- **Risk**: R4 (cluster drift döngüsel) — script idempotent + audit log
- **Implementer**: Claude · **Reviewer**: Codex
- **Effort**: ~1 gün

#### PR-S2 — Spring Config Root-Cause Fix (paralel iz)

- **Repo**: `platform-backend`
- **Scope**:
  - Spring `application-k8s.yml` her servis: password ayrı env var (`SPRING_DATASOURCE_PASSWORD`)
  - JDBC URL'den password çıkar, URL encoding güvenli
  - ESO template escape verify (Helm/kustomize template'lerinde `${...}` placeholder çakışma)
  - Tek PR (ortak config pattern); sadece servis risk farkı varsa 2-3 dilim
- **Kabul Kriterleri**:
  - [ ] Tüm servis Spring config'inde password ayrı env
  - [ ] Özel karakter içeren passwordlerle smoke pass
  - [ ] Hibernate Dialect error regression yok
  - [ ] Endpoint-admin "Unable to determine Dialect" çözüldü
- **Test**:
  - Unit: Spring config binding test (mock special-char password)
  - Integration: Testcontainers PG ile her servis startup
  - Regression: 8 servis × 3 password format (alphanumeric + symbol + unicode)
- **Bağımlılık**: yok (S1 ile paralel)
- **Risk**: R4 (root-cause permanent fix)
- **Implementer**: Claude · **Reviewer**: Codex
- **Effort**: ~2-3 gün

### 4.2 Faz Measurement (M, A)

#### PR-M1 — PerformanceObserver Harness

- **Repo**: `platform-web`
- **Scope**:
  - `apps/mfe-shell/src/lib/perf-observer.ts` — paint, LCP, longtask, layout-shift, event(INP) observer
  - `apps/mfe-shell/src/lib/rum-sinks.ts` — Sentry transaction + OTel span event
  - Custom marks API: `auth:sso:start/end`, `shell:mounted`, `home:first-content`, `route:interactive`
  - `performance-budgets.json` (route bazlı warn/fail thresholds)
  - `scripts/ci/route-performance-budget.mjs` — Playwright multi-route runner
  - `tests/perf/route-budget.spec.ts`
  - `package.json` script: `perf:budget`, `perf:budget:testai`
  - Metodoloji: median of 5 runs, foreground only, fixed Chrome version, CPU/network profile, hidden-page invalid
- **Kabul Kriterleri**:
  - [ ] 3 ana route (`/login`, `/home`, `/admin/reports`) × cold/warm = 6 JSON artifact üretiliyor
  - [ ] Her artifact'te LCP, FCP, INP, CLS, TBT alanları dolu (veya unsupported nedeni açık)
  - [ ] Median of N runs çalışıyor
  - [ ] Sentry transaction.setMeasurement bridge aktif
- **Test**:
  - Unit: observer setup, custom marks API, sinks
  - Integration: Playwright local + testai
  - Regression: bootstrap RUM overhead < 50 ms
- **Bağımlılık**: yok (S1 ile paralel)
- **Risk**: R6 (measurement flakiness), R13 (RUM kendi overhead'i)
- **Implementer**: Claude · **Reviewer**: Codex
- **Effort**: ~1.5 gün

#### PR-A0 — Bundle Attribution

- **Repo**: `platform-web`
- **Scope**:
  - Vite/Rolldown visualizer (production build)
  - `source-map-explorer` integration
  - `scripts/ci/bundle-taxonomy.mjs` — route × chunk × encoded/decoded/initiator/dependency tree
  - Duplicate package report (React, design-system, AG Grid, ECharts, i18n, icons)
  - Chrome trace ile long task attribution (Playwright `tracing.start`)
  - `docs/performance/bundle-taxonomy.md` runbook
  - "50 MB decoded neden 3 route'ta da aynı?" kanıt raporu
- **Kabul Kriterleri**:
  - [ ] Her route için duplicate package listesi var
  - [ ] Top 10 chunk × initiator × decoded breakdown
  - [ ] Long task root cause (hangi script/eval)
  - [ ] Static vs API payload ayrımı
- **Test**:
  - Integration: PR-M1 ile aynı testai fixture
- **Bağımlılık**: PR-M1
- **Risk**: R6, R7
- **Implementer**: Codex (agent mode, eğer kullanıcı izin verirse) veya Claude · **Reviewer**: diğer
- **Effort**: ~1 gün

#### PR-G1 — Gate Bootstrap (Extended)

- **Repo**: `platform-web`
- **Scope**:
  - `size-limit` config genişletme (package/entry bazlı)
  - `lighthouserc.json` dev server → production preview switch
  - Custom Playwright budget script CI artifact
  - Baseline JSON commit (`tests/perf/baseline.json`)
  - 4 ayrı regression gate (transfer + decoded + main-thread + TBT)
  - İlk 2 hafta warn-only; baseline stabilize → %5 hard fail
  - `.github/workflows/perf-budget.yml`
- **Kabul Kriterleri**:
  - [ ] CI'da route budget artifact PR'da görünür
  - [ ] Baseline JSON commitli
  - [ ] 4 gate ayrı pass/fail
  - [ ] Warn-only flag ile başlat
- **Test**:
  - Integration: PR açıp baseline'ın %4 üstü, %6 üstü test
- **Bağımlılık**: PR-M1, PR-A0
- **Risk**: R3 (CI lab vs canlı), R14 (CI/live divergence)
- **Implementer**: Claude · **Reviewer**: Codex
- **Effort**: ~1 gün

### 4.3 Faz Optimization Wave 1 (B1)

#### PR-B1a — AG Grid Lazy Split

- **Repo**: `platform-web`
- **Scope**:
  - `apps/mfe-shell/src/app/bootstrap.tsx` içinden `@mfe/design-system/advanced/data-grid/setup` import kaldır
  - `setupAgGridLicense` idempotent helper → `apps/mfe-reporting/src/grid/setup.ts`
  - Grid route'ta lazy çağrı + license init
  - Smoke: `/admin/users`, `/admin/access`, `/admin/reports` grid render OK
- **Kabul Kriterleri**:
  - [ ] `/home` transfer ≥ −2 MB
  - [ ] `/home` decoded ≥ −10 MB
  - [ ] TBT ≥ −800 ms düşüş
  - [ ] Grid route smoke pass
- **Test**:
  - Unit: setupAgGridLicense idempotent (2× çağrılırsa hata yok)
  - Integration: Playwright grid render + sort + filter
  - Regression: PR-G1 budget delta
- **Bağımlılık**: PR-G1
- **Risk**: R1 (grid regression), R11 (AG Grid license side-effect)
- **Implementer**: Claude · **Reviewer**: Codex
- **Effort**: ~1 gün

#### PR-B1b — Design-System Light Entry

- **Repo**: `platform-web`
- **Scope**:
  - `packages/design-system/src/light.ts` — alt-entry (button, form, input, layout, theme; AG Grid/ECharts/advanced YOK)
  - `package.json exports`: `./light`
  - `apps/mfe-shell` + `apps/login-entry` + home consumer'ları → light import migration
  - `eslint-plugin-no-restricted-imports` rule: shell/login için root barrel ban
- **Kabul Kriterleri**:
  - [ ] `/login` transfer −1 MB
  - [ ] `/home` transfer −1-2 MB
  - [ ] Root barrel kırılmaz (backward-compat)
  - [ ] Lint guard aktif
- **Test**:
  - Unit: light entry export shape
  - Integration: shell + login + home render
  - Regression: budget gate
- **Bağımlılık**: PR-B1a, PR-A0 (analyzer kanıtı: light entry gerçekten kazanç sağlıyor mu)
- **Risk**: R10 (CSS side effect — light JS ama CSS hâlâ ağır?)
- **Implementer**: Codex (agent mode) veya Claude · **Reviewer**: diğer
- **Effort**: ~2 gün

### 4.4 Faz Optimization Wave 2 (B2)

#### PR-B2 prep — MF Shared Scope Analysis

- **Repo**: `platform-web`
- **Scope**:
  - `scripts/module-federation/shared-config.ts` (ortak)
  - Her MFE'nin shared key inventory
  - sharedKeys diagnostic script (`scripts/diagnostics/mf-shared-keys.mjs`)
  - Canary remote seçimi (`mfe-suggestions` veya `mfe-ethic`)
- **Kabul Kriterleri**:
  - [ ] Shared key inventory commit edildi
  - [ ] Diagnostic script çalışıyor (browser console)
  - [ ] Canary remote netleşti
- **Bağımlılık**: PR-A0 ile paralel başlayabilir
- **Implementer**: Claude · **Reviewer**: Codex
- **Effort**: ~0.5 gün

#### PR-B2 canary — Single Remote MF Parity Rollout

- **Repo**: `platform-web`
- **Scope**:
  - Canary remote (örn. `mfe-suggestions`) için `import: false` + `singleton: true` + `requiredVersion: false` + `strictVersion: false`
  - sharedKeys diagnostic verify
  - Browser smoke + budget delta
- **Kabul Kriterleri**:
  - [ ] Canary remote runtime kırılmadan yüklendi
  - [ ] sharedKeys diagnostic: design-system tek instance
  - [ ] Budget delta ölçülebilir (PR-G1 baseline'a göre)
- **Test**:
  - Integration: Playwright canary remote route render
  - Regression: budget gate + sharedKeys diagnostic
- **Bağımlılık**: PR-B2 prep + **PR-G1 baseline** (acceptance için zorunlu)
- **Risk**: R2 (`import:false` runtime kırma), R8 (version skew), R9 (semver mismatch)
- **Implementer**: Claude · **Reviewer**: Codex
- **Effort**: ~1.5 gün

#### PR-B2 rollout — All Remotes

- **Repo**: `platform-web`
- **Scope**: Canary verisi pass → tüm remotes (`ethic, access, users, reporting, audit, ...`) aynı pattern
- **Kabul Kriterleri**:
  - [ ] Duplicate `loadShare__design_system` chunks tek kopya
  - [ ] `/home` transfer < 6 MB
  - [ ] `/home` decoded < 25 MB
- **Bağımlılık**: PR-B2 canary
- **Implementer**: Claude · **Reviewer**: Codex
- **Effort**: ~1 gün

### 4.5 Faz Optimization Wave 3 (B3)

#### PR-B3a — Shell-Services Idle Wiring

- **Repo**: `platform-web`
- **Scope**:
  - `apps/mfe-shell/src/app/config/shell-services-wiring.ts` — eager remote service imports → `requestIdleCallback` + route-needed
  - Auth-bootstrap sonrası idle queue
- **Kabul**: `/home` TBT < 800 ms, resource < 120
- **Bağımlılık**: PR-B2 rollout
- **Implementer**: Codex/Claude · **Reviewer**: diğer
- **Effort**: ~1.5 gün

#### PR-B3b — nginx HTTP/2 + Brotli Verify

- **Repo**: `platform-k8s-gitops`
- **Scope**:
  - `host-compose/web-nginx/default.conf` + `host-compose/proxy/conf/nginx.conf` config drift fix
  - `listen 443 ssl; http2 on;` consistent (authoritative container tespit)
  - `brotli on; brotli_static on;` doğrulama
  - Verify: `curl --http2 -I` HTTP/2 + `openssl s_client -alpn h2` + `Content-Encoding: br` curl yanıtı
- **Kabul**: `nextHopProtocol=h2`, `Content-Encoding=br` her hashed asset için
- **Bağımlılık**: PR-S1 OK
- **Risk**: R12 (cache invalidation tradeoff)
- **Implementer**: Claude · **Reviewer**: Codex
- **Effort**: ~0.5 gün

#### PR-B3c — Cache Headers + Preload Audit

- **Repo**: `platform-k8s-gitops`
- **Scope**:
  - Hashed assets `Cache-Control: immutable, max-age=31536000`
  - `remoteEntry.js` no-store veya kısa revalidate
  - HTML `Cache-Control: no-cache, must-revalidate`
  - Blanket `modulepreload` audit; route-needed only
- **Kabul**: warm fresh fetch < 1 MB
- **Bağımlılık**: PR-B3b
- **Implementer**: Codex/Claude · **Reviewer**: diğer
- **Effort**: ~0.5 gün

#### PR-B3d — CSS Critical Path

- **Repo**: `platform-web`
- **Scope**: AG Grid theme CSS + chart CSS audit, route-needed lazy load
- **Kabul**: CSS payload `/home` < 50 KB, critical inline
- **Bağımlılık**: PR-B2 rollout
- **Risk**: R10 (CSS side effects)
- **Implementer**: Claude · **Reviewer**: Codex
- **Effort**: ~1 gün

#### PR-B3e — Third-Party RUM Audit + Conditional Defer

- **Repo**: `platform-web`
- **Scope**:
  - PR-A0 artifact'inde Sentry/OTel early-path cost ölçümü
  - Eğer >50 ms main-thread veya >100-150 KB ek decoded → route sonrası lazy init
  - Replay/session sampling oranı belgelenir (prod policy)
- **Kabul**:
  - [ ] Audit raporu var (Sentry/OTel early cost JSON)
  - [ ] Eğer materialse defer uygulandı
  - [ ] RUM extension kendisi yeni long task üretmiyor
- **Bağımlılık**: PR-A0
- **Risk**: R13 (Sentry/OTel overhead)
- **Implementer**: Claude · **Reviewer**: Codex
- **Effort**: ~1 gün

### 4.6 Faz Leader (Conditional, ölçüme bağlı)

| PR | Condition | Effort | Notlar |
|---|---|---|---|
| **PR-B4a** /login micro-entry | B3 sonrası `/login` >800 KB | ~3 gün | React'siz form + redirect-only |
| **PR-B4b** Reports deep split | B3 sonrası `/admin/reports` >5 MB | ~2 gün | AG Grid + ECharts route ownership |
| **PR-B4c** i18n tree-shake | analyzer pay >300 KB | ~1 gün | Namespace-bazlı export |
| **PR-B4d** Font optimization | analyzer kanıtı font payı >100 KB | ~0.5 gün | font-display swap + subset |

---

## 5. Test Stratejisi (genel)

| Test Türü | Kapsam | Tool | Trigger |
|---|---|---|---|
| **Unit** | Helper fonksiyonlar, observer setup, shell scripts | Vitest, bash test framework | Her PR |
| **Integration** | MFE render, MF parity, grid smoke | Playwright | Her PR |
| **Smoke** | Cluster pod health, ESO sync, KC, OpenFGA | bash + kubectl + curl | PR-S1, post-merge |
| **Performance** | Route budget, Web Vitals, Lighthouse | Playwright route-budget script + `@lhci/cli` | PR-G1 sonrası her PR |
| **Regression** | 4 ayrı gate (transfer + decoded + main-thread + TBT) | CI custom script | Her web PR |
| **Browser smoke** | testai.acik.com cross-route | claude-in-chrome MCP veya Playwright | Post-merge |
| **Stability** | Cluster drift detector (CronJob) | Prometheus + kubectl | Sürekli |

---

## 6. Risk Register (15 risk, kategorize)

| # | Risk | Kategori | Prob × Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| R1 | AG Grid lazy split regression | Technical | M × H | Idempotent helper + smoke | Claude |
| R2 | MF `import:false` runtime kırma | Technical | M × H | Canary önce, sharedKeys diagnostic | Codex (review) |
| R3 | CI lab vs canlı çelişki | Process | M × M | Ayrı raporlama, etiketleme | Claude |
| R4 | Cluster drift döngüsel | Operational | H × H | S1 workaround + S2 root-cause + drift detector | Claude |
| R5 | `/login` scope creep | Schedule | L × M | Conditional execution | Codex (review) |
| R6 | Measurement flakiness | Methodology | M × H | Median N runs + foreground + browser version | Claude |
| R7 | Static/API budget karışma | Methodology | M × M | Matrix ayrı kolonlar | Claude |
| R8 | Federation version skew | Technical | M × H | B2 canary + sharedKeys gate | Codex |
| R9 | Semver mismatch gizlenmesi | Technical | L × M | PR review explicit version contract | Codex |
| R10 | CSS side effects | Technical | M × M | PR-B3d ayrı | Claude |
| R11 | AG Grid license side-effect | Technical | L × H | PR-B1a idempotent + tree-shake guard | Claude |
| R12 | Cache invalidation tradeoff | Operational | M × M | remoteEntry short-revalidate + hashed immutable | Claude |
| R13 | Sentry/OTel overhead | Technical | L × M | B3e audit-first, conditional defer | Claude |
| R14 | CI/live divergence | Process | L × M | Tek prod preview + testai ayrı | Codex |
| R15 | Cross-AI governance kanıt | Process | L × L | PR template audit footer | Claude |

**Kategori dağılımı**: Technical 8 · Operational 2 · Process 3 · Methodology 2 · Schedule 0 (conditional ile çözüldü)

---

## 7. Stop Conditions (3 kademe)

### 7.1 Ara hedef (B1a+B1b+B2 rollout sonra)

- [ ] `/home` decoded ≥ 25 MB düşüş (50 → ≤25)
- [ ] TBT < 1500 ms
- [ ] Grid smoke pass
- [ ] Duplicate chunks %50+ azalır

### 7.2 Optimization hedefi (B3a/b/c/d/e sonra)

- [ ] `nextHopProtocol=h2`
- [ ] `Content-Encoding=br` confirmed
- [ ] CSS critical inline/preload
- [ ] Third-party scripts route sonrası
- [ ] TBT < 800 ms, resource < 120
- [ ] `/home` transfer < 6 MB

### 7.3 Final hard gate (B4 conditional sonra, 0-3 ay accepted)

- [ ] `/login` < 800 KB
- [ ] `/home` < 3 MB
- [ ] `/home` decoded < 12 MB
- [ ] `/admin/reports` < 8 MB
- [ ] TBT < 600 ms
- [ ] LCP < 2.5 s
- [ ] INP < 200 ms
- [ ] CLS < 0.1

### 7.4 Leader aspirasyon (12-ay)

- [ ] `/login` < 300 KB
- [ ] `/home` < 1.5 MB
- [ ] `/home` decoded < 6 MB
- [ ] `/admin/reports` < 4 MB
- [ ] TBT < 50 ms (advisory)
- [ ] LCP < 1.5 s
- [ ] INP < 100 ms
- [ ] CLS < 0.05

---

## 8. Dependencies & Critical Path

**Critical path (hard execution)**: `S1 → M1 → A0 → G1 → B1a → B1b → B2 canary → B2 rollout → B3a → [B3b/c/d/e parallel]`

**Paralel iz**:

- S2 (backend root-cause) — S1 ile paralel başlayabilir
- B3b/c/d/e — S1 OK olunca, B2 beklemez

**Bağımlılık zinciri uzunluğu**: ~10 sequential PR, paralel iz dahil ~13 toplam hard PR.

### 8.1 Akış diyagramı (text)

```
[STABILIZE]    [MEASURE]      [ATTRIBUTION]   [GATE]
   PR-S1 ──┬── PR-M1 ───────► PR-A0 ────────► PR-G1
           │                                     │
   PR-S2 ──┘ (paralel, S1 beklemez)              │
                                                  ▼
                            ┌────────────────────┴─────────────────┐
                            ▼                    ▼                  ▼
                       PR-B1a              PR-B2 prep          PR-B3a
                    (AG Grid lazy)       (config + canary)  (shell-services idle)
                            │                    │                  │
                            ▼                    ▼                  │
                       PR-B1b           PR-B2 canary               │
                  (design-system        (G1 baseline               │
                   light entry)          gerekli) ──► PR-B2 rollout│
                                                                    │
   [OPS PARALEL — S1 OK olunca bağımsız iz]                         │
   PR-B3b (HTTP/2 + brotli verify)                                  │
   PR-B3c (cache headers + preload audit)                           │
   PR-B3d (CSS critical path)                                       │
   PR-B3e (third-party RUM audit-first, conditional defer)          │
                                                                    │
   [LEADER — B1/B2/B3 sonrası ölçüme bağlı conditional]             ▼
   PR-B4a /login micro-entry  (if /login >800 KB)                   │
   PR-B4b reports deep split   (if /admin/reports >5 MB)            │
   PR-B4c i18n tree-shake      (analyzer pay >300 KB)               │
   PR-B4d font optimization    (analyzer kanıtı sonra)              │
                                                                    │
                                                            [HARD GATE]
                                                       /login <800 KB
                                                       /home <3 MB / <12 MB decoded
                                                       /admin/reports <8 MB
                                                       TBT <600 ms
```

---

## 9. RACI Ownership Matrix

| Rol | İmplementer | Reviewer | Approver | Operator |
|---|---|---|---|---|
| PR-S1 cluster drift workaround | Claude | Codex | Halil | Halil (CronJob deploy) |
| PR-S2 backend root-cause | Claude | Codex | Halil | — |
| PR-M1 perf harness | Claude | Codex | Halil | — |
| PR-A0 bundle attribution | Codex (agent) veya Claude | diğer | Halil | — |
| PR-G1 gate bootstrap | Claude | Codex | Halil | — |
| PR-B1a AG Grid | Claude | Codex | Halil | — |
| PR-B1b design-system light | Codex (agent) veya Claude | diğer | Halil | — |
| PR-B2 prep/canary/rollout | Claude | Codex | Halil | — |
| PR-B3a shell-services idle | Codex/Claude | diğer | Halil | — |
| PR-B3b HTTP/2 | Claude | Codex | Halil | Halil (nginx reload) |
| PR-B3c cache headers | Codex/Claude | diğer | Halil | Halil |
| PR-B3d CSS critical | Claude | Codex | Halil | — |
| PR-B3e RUM defer | Claude | Codex | Halil | — |
| PR-B4a-d conditional | varies | varies | Halil | — |

**Cross-AI peer review HARD RULE**: her PR'da code yazan AI ≠ reviewer. PR template audit footer:

```
Implementer AI: Claude/Codex (thread: ...)
Reviewer AI:    Codex/Claude (thread: ...)
```

---

## 10. Communication Plan

| Event | Cadence | Target | Format |
|---|---|---|---|
| PR merge | Her PR sonrası | Halil | Squash mesaj + audit footer |
| Faz kapanış | S/M/B1/B2/B3 sonu | Halil | Status report + sıradaki faz |
| Blocker | Anında | Halil | Spawn task chip veya direct mesaj |
| Drift detector alert | Sürekli (CronJob) | Halil + Slack/email | Alert payload + suggested action |
| Progress dashboard | Faz G yaklaşırken haftalık | Halil | Performance budget delta tablosu |
| Performance baseline update | Her hard pass | Repo + Halil | `tests/perf/baseline.json` commit |

---

## 11. Sign-off Kriterleri

### 11.1 Her PR

- [ ] CI yeşil (tüm required check)
- [ ] Codex review AGREE (cross-AI peer review)
- [ ] Smoke pass (cluster + browser)
- [ ] Budget delta ölçülmüş + dokümante

### 11.2 Her faz

- [ ] Stop conditions sayısal kanıt
- [ ] Status report committed (`docs/session-handoff-*.md`)
- [ ] Sıradaki faz prep

### 11.3 Final 0-3 ay hard pass

- [ ] Tüm 4 hard gate sürekli geçiyor (warn-only fazı bitti, %5 hard fail aktif)
- [ ] 6 ay milestone path projeksiyon hazır
- [ ] Faz G prod cutover öncesi handoff doc

---

## 12. Rollback Stratejisi

### 12.1 Per PR

- `git revert` + `ai-post-merge-cleanup.sh` archive tag
- Cluster: selective `kubectl apply -f` (D17 protected)

### 12.2 Per faz

- Archive tags (forensic recovery 1+ yıl)
- T+72h warm rollback (legacy compose backend standby — Faz G öncesi gerekirse)

### 12.3 Catastrophic (Faz G öncesi)

- Tüm PR'lar revert → main reset (owner explicit beyan + protected branch)
- D30 atomic cutover öncesi prod overlay still untouched (selfHeal=false güvenliği)

---

## 13. Out-of-Band: Cluster Drift Acil Çözüm

Eğer PMD onay süreci sırasında cluster yeniden bozulursa (KC drift veya PG `platform` user drift), **PR-S1'i acil olarak** ilk PR olarak başlatıp PMD geri kalan PR'larını paralel iz olarak kabul ederiz. Cluster stabilite olmadan browser smoke güvenilir değil.

---

## 14. AI Consensus Audit Trail

| Tur | Thread | Verdict | Önemli karar |
|---|---|---|---|
| Turn 1 — Codex bağımsız plan | `019e1dc8` | `ready_for_ping_pong: true` | İlk faz dizgisi |
| Turn 2 — İki plan karşılaştırma | `019e1dc8` | Mutabakat noktaları | 12 PR iskelet |
| Turn 3 — Son tartışma noktaları | `019e1dc8` | `mutabakat_kesin: true` | shell-local RUM, executor flexible, /login conditional |
| Turn 4 — Bağlamsız adversarial | `019e1de0` | `REVISE` | PR-A0 attribution, matrix decoded, paralelleştirme, S1→S2 split |
| Turn 5 — v2 absorb | `019e1de0` | **AGREE** | 5 küçük patch ile kesin |

---

## 15. Onay

| Rol | Ad | Tarih | İmza |
|---|---|---|---|
| Owner | Halil | 2026-05-11 | ☐ |
| AI Consensus | Claude (mutabakat) + Codex (`mutabakat_kesin: true` + adversarial AGREE) | 2026-05-11 | ✅ |

---

## 16. Onaya sunulan açık sorular

1. PMD onaylanıyor mu (PR-S1 ile başlatılsın mı)?
2. PR-S2 sahipliği: tek backend PR mı (Claude), yoksa servis dilimleri mi (canary first)?
3. Codex agent mode (workspace-write) kullanımı: PR-A0, PR-B1b gibi code-heavy işlerde Codex execute istiyor musunuz, yoksa hep Claude execute?
4. Drift detector CronJob alert hedefi: Slack, email, webhook? (PR-S1'in operator-config kısmı)
5. Faz G prod cutover tarihi belli mi? PMD takvimini buna sıkıştırmamız gerekir mi yoksa pre-prod modda relax mi?
6. Onay sonrası PR-S1 + PR-S2 + PR-M1 paralel mi başlasın, yoksa S1 önce mi?

Onay sonrası **PR-S1 + PR-M1 paralel başlatma** ile başlanır.
