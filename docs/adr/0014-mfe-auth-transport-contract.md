# ADR-0014 — MFE Auth Transport Contract

> **Status**: Accepted
> **Implementation State**: source-implemented through PR-Obs-5; test-overlay GitOps bump in flight (PR #401 sha-9d06576); prod cutover deferred
> **Date**: 2026-05-08
> **Sprint**: MFE Auth Transport Contract roadmap (PR-Auth-1 → PR-Obs-5 done; PR-E2E-6 + PR-BE-7 pending)
> **Predecessors**: ADR-0004 (split-repo authority transfer — `platform-web` canonical), ADR-0011 (drift detection + boundary governance), ADR-0012-EA (endpoint-admin governance — auth integration)
> **PLAN reference**: tracked under MFE Auth Transport Contract roadmap (PR-Auth-1 #302 → PR-Obs-5 #309); see § Implementation Map for Codex thread + sha provenance

## Bağlam

Faz 19 split-repo authority transfer sonrası (ADR-0004) frontend kodu `platform-web`’de canonical hale geldi. `mfe-shell` Keycloak PKCE üzerinden token alıyor, `httpOnly` cookie üzerinden gateway’e session aktarıyordu — ama auth bootstrap’ın tüm aşamaları (Keycloak init, cookie write, authz fetch, transport ready) yarış halindeydi. Production’da gözlemlenen 5 kritik sorun:

| Semptom | Nedeni |
|---|---|
| Login flicker | `AuthBootstrapper` Keycloak init bitmeden `LoginPage` render ediliyordu; `initialized` boolean transitional state ayırt etmiyordu |
| 401 storm | MFE kodu `auth.token` Redux state’i true olduğunda istek atıyordu; ama gateway cookie henüz yazılmamıştı → her request 401 |
| Auth FSM deadlock | `setTokenCookie` request’i auth-ready gate’e takılıyordu; gate `transportReady` bekliyordu; `transportReady` ise `setTokenCookie` çıktısını bekliyordu |
| 5-dakika tekrarlı re-login | gateway `/auth/cookie/refresh` 404 (single-handler henüz iki yola da hizmet etmiyordu); silent token refresh sonunda cookie wipe + re-login storm |
| Bundle drift kaynaklı kafa karışıklığı | gitops digest pin’i ile cluster pod imageID arasında 200m CPU ResourceQuota + maxSurge=1 kombinasyonundan dolayı drift; kullanıcıya "bunu deploy ettim mi acaba?" muğlaklığı |

Her semptom ayrı bir incident değil; aslında **tek bir contract eksikliği**: shell ve MFE’ler arasında "ne zaman bir HTTP request güvenle atılabilir" sözleşmesi yoktu.

## Karar — Decision Invariants

Aşağıdaki 7 invariant contract'ı tanımlar. Her satır **MUST**: contract ihlali bug. Implementation detayları (faz isimleri, file path'leri, sha'lar, Codex thread ID'leri) Implementation Map appendix'inde.

### I1 — 5-fazlı transport FSM
Shell tek bir `auth.slice` reducer'ında 5-fazlı FSM tutar:
- `initializing` → `keycloakReady` → `cookieReady` → `authzReady` → `transportReady` (terminal yeşil)
- `unauthenticated` (terminal — login sayfası göster)
- `failed` (terminal — degraded UI göster)
- `refreshing` (geçici — 401 single-flight refresh sürmekte; başarıda transportReady'ye döner)

Faz geçişleri reducer'da merkezdir; ad-hoc state mutation yasak.

### I2 — auth.ready() Promise bridge with epoch invalidation
MFE kodu protected request atmadan önce `await getShellServices().auth.ready()` çağırır. Bu Promise:
- `transportReady` → `{ ok: true }` resolve
- `unauthenticated` → `{ ok: false, reason: 'unauthenticated' }` resolve (login redirect)
- `failed` → reject (degraded handler)
- `bumpAuthEpoch` çağrıldığında (logout/re-login) Promise reset; sonraki `ready()` yeni epoch'u bekler

### I3 — shared-http auth-ready gate
`@mfe/shared-http` request interceptor tüm protected request'leri auth-ready gate'in arkasında tutar. Shell `registerAuthReadyResolver()` ile resolver'ı kayıt eder. `AuthNotReadyError` typed throw — module federation no-share için `isAuthNotReadyError` name-based guard.

### I4 — Bootstrap chain bypass (sole exception)
Auth FSM'i ileri iten request'ler (`POST /auth/cookie`, `DELETE /auth/cookie`, `GET /v1/authz/me` post-login, `POST /v1/auth/sessions`, `GET /users/by-email/...`, `POST /users/public/register`) `__skipAuthReadyGate: true` config flag'i ile gate'i bypass eder. Bu sınıf dışındaki hiçbir request gate'i bypass etmez. Deadlock guard.

### I5 — Single-flight 401 refresh with full closure
401 response'unda response interceptor:
1. Eligibility check (refresh handler kayıtlı, `__isRefreshAttempt` değil, `__skipAuth/__skipAuthReadyGate/__skipRefreshOn401` set değil)
2. Single-flight: `refreshInFlight === null` → OWNER (gerçek handler invocation); diğer 401'ler in-flight Promise'a coalesce
3. OWNER full closure: `keycloak.updateToken(-1)` + `POST /api/auth/cookie` + `GET /api/v1/authz/me` + Redux store dispatch + `setAuthPhase('transportReady')`
4. OK ise original retry (`__isRefreshAttempt: true` flag loop guard)
5. Fail ise `app:auth:unauthorized` event + 401 propagate (legacy path)

`setAuthPhase('transportReady')` zorunlu: aksi halde FSM `refreshing` faza takılı kalır, `auth.ready()` gate yeniden açılmaz, retry hang olur.

### I6 — PII-free observability
Fetch telemetry counter'ları:
- `requestTotal{<statusClass>xx_<METHOD>}` — URL hiç label DEĞİL; cardinality protection
- `authNotReadyTotal{<bounded reason>}` — bounded enum (`failed | unauthenticated | resolver-throw | unknown | other`)
- `refreshAttemptTotal{ok|fail}` — sadece single-flight OWNER sayar
- `refreshWaiterTotal` — coalesce edilen 401 caller sayısı (ayrı counter)
- `recentRefreshFailures` — bounded ring (max 20, 5min TTL, normalised reason enum)
- `transportReadyDurationMs` — gauge (per auth epoch, observer dedups)

URL/header/body/token telemetry'de YASAK. Module federation singleton path'inde tüm MFE'ler shell-instance counter'larında sayılır; dev/single-domain fallback path'lerde out-of-scope.

### I7 — Degraded UI banner via derived state
Banner pure `selectAuthDegradedState(phase, bootstrapStartAt, snapshot, now)` fonksiyonundan render edilir:
- `failed` faz → SKIP (root failed UI handles; banner duplicate etmez)
- Slow init → bootstrap >30s elapsed AND phase pre-terminal
- Recent refresh failures → `recentRefreshFailures` ring'de >2 entry son 60s'de

Banner aksiyonları: "Sayfayı yenile" (`window.location.reload()`) + "Yeniden giriş yap" (`/login?redirect=<encoded current>`; `/login` üzerindeyken plain `/login`).

## Sonuçlar

### Verified outcomes (unit / integration / live)
| Outcome | State | Evidence |
|---|---|---|
| Login flicker eliminated | verified by integration | `ValidatingMessage` transitional fazlarda gösteriliyor; AppRouter test pinned |
| 401 storm eliminated | verified by integration | protected request'ler `transportReady` öncesi atılmıyor; `AuthNotReadyError` interceptor pinned |
| Bootstrap deadlock eliminated | verified by integration | `__skipAuthReadyGate` 6 endpoint için pinned (cookie/authz/login/profile/register) |
| Re-login storm eliminated | verified by live cluster | gateway `/auth/cookie/refresh` 404 fix (canonical sha-76c517b) + frontend single-flight refresh |
| Bundle drift muğlaklığı çözüldü | verified by GitOps PR | maxSurge=0 strategy patch + immutable digest pin (PR #400 + PR #401) |
| PII-free fetch telemetry | verified by unit | 51 shared-http + 21 mfe-shell observability tests; URL hiç label değil |
| Degraded UI banner derived state | verified by unit | 10-case selector test + StrictMode dedup test |

### Planned (PR-E2E-6 + PR-BE-7 sonrası eklenecek)
| Outcome | State | Notes |
|---|---|---|
| End-to-end Playwright network contract gate | planned/draft | Codex thread `019e04e4` iter-1 PARTIAL: 6 P0 harness/CI prep blocker (test-only Keycloak bootstrap mock, `VITE_AUTH_CONTRACT_E2E=1` probe, deterministic refresh mock, server-start workflow) |
| Backend gateway 401 telemetry + rate limit | planned | PR-BE-7: refresh storm'ları gateway tarafında da görünür olsun + abuse rate limit |
| 24h prod smoke verification | deferred | testai.acik.com 24h post-deploy degraded banner not-firing + refreshAttemptTotal.fail trending toward 0 |
| Prod overlay digest bump | deferred | 24h test smoke + cross-AI peer review sonrası ayrı PR |

### Tradeoffs
- **MF singleton boundary out-of-scope**: dev/single-domain/fallback path'lerde remote MFE'ler kendi `@mfe/shared-http` kopyasını bundle'a koyabilir; telemetry remote MFE'nin local instance'ında kalır, shell'e bridge edilmez. Production MF runtime'da bu yol kullanılmaz.
- **Banner threshold'ları statik**: slow-init 30s, recent-fail >2/60s — load-aware tuning gelecek faz
- **PKCE multi-tab collision**: kullanıcı user-action (close extra tabs + clear cache) ile mitigate ediyor; permanent fix (per-tab kc-callback isolation veya cross-tab refresh leader-election) ayrı follow-up. Risk listesinde takip ediliyor — kendi başına ADR-yapacak boyutta değil; yapılırsa `Per-tab callback isolation strategy` adıyla mevcut ADR'ye amendment veya ayrı küçük ADR.

### Risks (known)
- **Module Federation singleton garantisi prod'da kritik**: shell `@mfe/shared-http` paylaşılmazsa I6 (PII-free observability) kısmen kaybolur (counter cross-MFE aggregate edilemez). Vite remoteEntry config drift'leri PR-E2E-6 contract testinde yakalanmalı.
- **Refresh closure full sync**: closure'ın 4 step'i (token + cookie + authz + dispatch) atomic değil; herhangi biri fail ederse FSM `refreshing` faza takılı kalır, `setAuthPhase('failed')` triggerlanır. Test cluster'da yapay 503 ile test edildi; prod'da gateway/keycloak outage senaryosunda bu path stress test gerek.

## Kararın eşdeğer alternatifleri (rejected)

| Alternatif | Ret nedeni |
|---|---|
| Server-side rendering with secure cookie hand-off | MFE module federation runtime → SSR pipeline overhead + remote MFE manifest fetch hâlâ client-side |
| Service worker proxy intercepting all `/api/*` | service worker registration ile auth FSM arasında kurulum sırası problemi; PWA scope iframe'li MFE'lerde flaky |
| OAuth2 BFF pattern (Keycloak token never reaches browser) | Backend BFF her MFE için endpoint çoğaltır + cookie size limit aşar; mevcut gateway'le çakışır |
| JWT-only / no httpOnly cookie | Browser'da token exposure (XSS risk) + gateway session contract bozulur (gateway cookie tabanlı session yönetiyor) |
| Gateway-side refresh only (frontend single-flight olmadan) | Keycloak token + cookie + authz snapshot + Redux epoch closure'ını gateway tek başına kapatamaz; SPA state sync için ayrı bridge gerek |
| Optimistic request + retry/backoff (per-MFE axios interceptor) | 401 storm'u bastırır ama readiness contract üretmez; her MFE bağımsız retry → thundering herd; auth.ready() Promise yok → MFE'ler arası timing sözleşmesi belirsiz |
| Manual `await auth.ready()` her MFE'de (gate olmadan) | Sözleşme runtime contract olmadan opt-in hale gelir; bir MFE unutursa 401 storm geri gelir |

Seçilen contract (gate at HTTP layer + FSM Promise bridge) bu alternatiflerden 3 axis daha iyi: (a) backend değişikliği gerektirmez, (b) MFE'lere transparent (call site değişmez), (c) tek source of truth (`auth.slice.ts` reducer + `shared-http` interceptor).

---

## Implementation Map (evidence appendix)

Bu bölüm karar mantığı değil; karar invariant'larının kodda nereye landed olduğunu tracking eden audit log.

### PR roadmap
| PR | Repo | Sha | Codex thread | Cross-AI review |
|---|---|---|---|---|
| #302 PR-Auth-1 | platform-web | 7cd0fa78 | `019e0119` (iter-22/24) | post-impl AGREE |
| #304 PR-Reporting-2 | platform-web | c9fd9319 | `019e02bc` | post-impl AGREE |
| #306 PR-HTTP-3 | platform-web | c5398751 | `019e046c` (iter-1/2 P0/P1/P2 absorb) | post-impl AGREE |
| #307 PR-Refresh-4 | platform-web | 224728da | `019e048d` (iter-1/2/3 closure) | post-impl AGREE |
| #309 PR-Obs-5 | platform-web | 9d06576f | `019e04d0` (iter-0 REVISE → iter-1 AGREE → iter-2 post-impl AGREE) | post-impl AGREE |
| PR-E2E-6 | platform-web | (planned) | `019e04e4` (iter-1 PARTIAL) | — |
| PR-BE-7 | platform-backend | (planned) | (yet to assign) | — |
| #401 frontend-bump-9d06576 | platform-k8s-gitops | (in flight) | (chore — no Codex iter) | — |

### Gitops digest history (test overlay)
- sha-c539875 (PR #400 — preceded current bundle, never reached cluster due to ResourceQuota+maxSurge race)
- sha-224728d (auto-deploy kubectl-set-image after PR-Refresh-4; gitops did not get a canonical bump for this digest before PR-Obs-5 landed)
- sha-9d06576 (PR-Obs-5; auto-deploy kubectl-set-image immediately post-merge; canonical via PR #401)

### File map (canonical source paths in `platform-web` HEAD `9d06576f`)
- `apps/mfe-shell/src/features/auth/model/auth.slice.ts` — I1 + I2 (FSM phase reducer + selectors + epoch)
- `apps/mfe-shell/src/app/providers/AuthBootstrapper.tsx` — Keycloak PKCE + cookie + authz bootstrap
- `apps/mfe-shell/src/app/config/shell-services-wiring.ts` — refresh closure + auth-ready resolver
- `apps/mfe-shell/src/app/observability/AuthFsmObserver.tsx` — I6 telemetry observer
- `apps/mfe-shell/src/app/observability/AuthDegradedBanner.tsx` — I7 banner UI
- `apps/mfe-shell/src/app/observability/auth-degraded-state.ts` — I7 derived state pure selector
- `packages/shared-http/src/index.ts` — I3 + I4 + I5 (request/response interceptor)
- `packages/shared-http/src/observability.ts` — I6 PII-free counters

### Test pinning
- `packages/shared-http/src/observability.test.ts` — 26 tests: counter increments, ring TTL, throttle, immutability, reset
- `packages/shared-http/src/index.test.ts` — 6 wire-up tests added (real status, status-bearing errors, auth-not-ready, resolver-throw, single-flight owner-only attempt vs waiter, recent failure ring)
- `apps/mfe-shell/src/app/observability/auth-degraded-state.test.ts` — 10 cases (failed-phase precedence, threshold edges, window pruning)
- `apps/mfe-shell/src/app/observability/AuthFsmObserver.test.tsx` — 4 tests (phase-change, dedup, post-bump re-record, periodic snapshot)
- `apps/mfe-shell/src/app/observability/AuthDegradedBanner.test.tsx` — 7 tests (render gates, button actions, login redirect)

---

**Karar kuralı (tek cümle)**: Protected MFE HTTP **MUST** wait for shell auth `transportReady`; only bootstrap-chain requests **MAY** bypass the gate; 401 refresh **MUST** be single-flight and restore token + cookie + authz + Redux + phase state; observability **MUST** be URL/PII-free.
