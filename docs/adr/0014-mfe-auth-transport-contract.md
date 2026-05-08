# ADR-0014 — MFE Auth Transport Contract

> **Status**: ACTIVE (Phase 2 — plan-time consensus 2026-05-07; implementation 2026-05-07/08; live in platform-test cluster on sha-224728d / sha-9d06576)
> **Date**: 2026-05-08
> **Sprint**: MFE Auth Transport Contract roadmap (PR-Auth-1 → PR-ADR-8)
> **Codex threads**:
> - `019e0119` (PR-Auth-1 plan + impl iter-22/23/24 transport FSM)
> - `019e02bc` (PR-Reporting-2 metadata cache + auth.ready() gate)
> - `019e046c` (PR-HTTP-3 shared-http auth-ready gate; iter-1/2 P0/P1/P2 absorb)
> - `019e048d` (PR-Refresh-4 single-flight 401 refresh; iter-1/2/3 closure)
> - `019e04d0` (PR-Obs-5 fetch telemetry + degraded UI + structured logs; iter-0 REVISE → iter-1 AGREE → iter-2 post-impl AGREE)
> - `019e04e4` (PR-E2E-6 Playwright network contract gate; iter-0 REVISE → iter-1 PARTIAL)
> **Predecessors**: ADR-0004 (split-repo authority transfer — platform-web canonical), ADR-0011 (drift detection + boundary governance), ADR-0012-EA (endpoint-admin governance — auth integration)
> **Related artifacts**:
> - `apps/mfe-shell/src/features/auth/model/auth.slice.ts` — FSM phase reducer + selectors
> - `apps/mfe-shell/src/app/providers/AuthBootstrapper.tsx` — Keycloak PKCE + cookie + authz bootstrap
> - `apps/mfe-shell/src/app/config/shell-services-wiring.ts` — refresh closure + auth-ready resolver
> - `apps/mfe-shell/src/app/observability/{AuthFsmObserver,AuthDegradedBanner,auth-degraded-state}.ts` — telemetry + degraded UI
> - `packages/shared-http/src/index.ts` — request interceptor (auth-ready gate + 401 refresh single-flight)
> - `packages/shared-http/src/observability.ts` — PII-free fetch counters + bounded recent-failure ring

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

### Codex plan-time istişare (özet)

Plan-time + post-impl peer review’da 6 PR boyunca 22+ iter:
- iter-0/1: yön ve scope sözleşmesi (her PR’da REVISE → AGREE)
- iter-2/3: edge case absorb (single-flight semantiği, cookie wipe race, deadlock guard)
- post-impl: cross-AI peer review (HARD RULE: Reviewer ≠ Implementer)

Konsensus: **5-fazlı transport FSM + auth-ready gate + single-flight 401 refresh + PII-free observability + degraded UI banner**. Test stratejisi: unit (vitest) + integration (interceptor) + E2E (Playwright deterministic mock).

## Karar

### 1. Transport FSM (PR-Auth-1 #302 sha-7cd0fa78)

`auth.slice.ts` şu fazlara sahip 5-fazlı FSM:

```
initializing → keycloakReady → cookieReady → authzReady → transportReady
              ↓                  ↓                ↓
              unauthenticated    failed          refreshing → transportReady
```

Her faz tek bir _görev_ tamamlandığında ilerler:
- `keycloakReady`: `keycloak.init()` resolved (PKCE callback işlendi veya silent SSO bitti)
- `cookieReady`: `POST /api/auth/cookie` 2xx döndü
- `authzReady`: `GET /api/v1/authz/me` 2xx döndü, snapshot store’a yazıldı
- `transportReady`: Redux store’a token + profile + authz dispatch edildi (terminal "yeşil" state)
- `unauthenticated`: kullanıcı login değil (terminal — login sayfası göster)
- `failed`: bootstrap fail oldu (terminal — degraded UI göster)
- `refreshing`: 401 single-flight refresh sürmekte (geçici state, başarıda transportReady’ye dönüyor)

`PHASES_TREATED_AS_INITIALIZED = { transportReady, unauthenticated, failed }` — bu set legacy `initialized: boolean` flag’ini deriving ediyor. ProtectedRoute, AppRouter ve diğer legacy tüketiciler değişmeden çalışmaya devam ediyor.

`authEpoch: number` her logout/re-login’da artar. `auth.ready()` Promise bridge’i bu epoch’a bağlanıyor → eski refresh round’larından gelen retry’lar yeni epoch’ta otomatik invalid sayılıyor.

### 2. auth.ready() Promise bridge (PR-Auth-1 + PR-Reporting-2 #304)

MFE kodu protected request atmadan önce `await getShellServices().auth.ready()` çağırır. Bu Promise:
- `transportReady` faza ulaştığında `{ ok: true }` resolve eder
- `unauthenticated` faza ulaştığında `{ ok: false, reason: 'unauthenticated' }` resolve eder (login redirect tetikler)
- `failed` faza ulaştığında reject eder (degraded UI handler)
- `bumpAuthEpoch` çağrıldığında (logout/re-login) geçerli Promise reset edilir, sonraki `ready()` yeni epoch’u bekler

### 3. shared-http auth-ready gate (PR-HTTP-3 #306 sha-c5398751)

`@mfe/shared-http` request interceptor’ı tüm protected request’leri auth-ready gate’in arkasında tutar. Shell `registerAuthReadyResolver()` ile resolver’ı kayıt eder; resolver `transportReady` beklenirken Promise asılı kalır.

`AuthNotReadyError` typed error class — module federation no-share sınırları için `isAuthNotReadyError` name-based guard. Bu error caller’ın retry/refresh logic’ini atlamasına izin verir (request hiç atılmadı, 401 değil).

`__skipAuthReadyGate: true` config flag’i bootstrap chain’in auth FSM’i ileri itmek için ihtiyaç duyduğu request’leri (cookie write, authz fetch, login, register) gate’ten geçirmeden çağırır. Bu deadlock guard PR-HTTP-3 iter-1 P0 absorb’unda eklendi.

### 4. Single-flight 401 refresh (PR-Refresh-4 #307 sha-224728da)

`shared-http/index.ts` response interceptor’ı 401’de:
1. Eligibility check (refresh handler kayıtlı, `__isRefreshAttempt` değil, `__skipAuth/__skipAuthReadyGate/__skipRefreshOn401` set değil)
2. Single-flight: `refreshInFlight === null` ise OWNER (gerçek refresh handler invocation). Diğer 401 caller’lar in-flight Promise’a coalesce.
3. Refresh handler full closure çalıştırır:
   - `keycloak.updateToken(-1)` — yeni access token
   - `POST /api/auth/cookie` — yeni cookie
   - `GET /api/v1/authz/me` — yeni authz snapshot
   - `dispatch(setKeycloakSession({...}))` — Redux store update
   - `dispatch(setAuthPhase('transportReady'))` — auth.ready() gate yeniden açıldı
4. OK ise original request retry (`__isRefreshAttempt: true` flag’i ile loop guard)
5. Fail ise `app:auth:unauthorized` event dispatch + 401 propagate (legacy path)

Codex iter-2 P1 absorb (thread `019e048d`): `setKeycloakSession` tek başına `auth.ready()` gate’i yeniden açmıyordu (FSM `refreshing` faza takılı kalıyordu). Fix: `setAuthPhase('transportReady')` dispatch eklendi.

### 5. PII-free fetch telemetry (PR-Obs-5 #309 sha-9d06576f)

`@mfe/shared-http/observability` modülü:
- `requestTotal{<statusClass>xx_<METHOD>}` — URL hiç label değil (cardinality protection)
- `authNotReadyTotal{<bounded reason>}` — `failed | unauthenticated | resolver-throw | unknown | other`
- `refreshAttemptTotal{ok|fail}` — sadece single-flight OWNER sayar
- `refreshWaiterTotal` — coalesce edilen 401 caller sayısı (ayrı counter)
- `recentRefreshFailures` — bounded ring (max 20, 5min TTL, normalised reason enum)
- `transportReadyDurationMs` — gauge (per auth epoch, observer dedups)
- `subscribeMetrics` — throttled ≤ 1Hz, snapshots deeply frozen
- `__resetMetricsForTesting` — test isolation export

Shell tarafı:
- `AuthFsmObserver` — invisible React component, phase transitions + transportReady gauge + 1/min snapshot emit (mevcut `telemetryClient.emit` yeniden kullanılır, yeni endpoint yok)
- `AuthDegradedBanner` — derived state (pure `selectAuthDegradedState(phase, bootstrapStartAt, snapshot, now)`); `failed` faz banner SKIP eder (root UI handles); slow-init >30s, recent-refresh-failures >2/60s

### 6. Module Federation singleton boundary

Production MF: shell `@mfe/shared-http` singleton’ı tüm MFE’lere paylaşır. Tüm HTTP traffic shell-instance counter’larında sayılır.

Out-of-scope: dev/single-domain/fallback path’lerde remote MFE’ler kendi `@mfe/shared-http` kopyasını bundle’a koyabilir; bu durumda telemetry remote MFE’nin local instance’ında kalır, shell’e bridge edilmez. PR-Obs-5 commit message + PR description bu boundary’yi explicitly belirtir.

### 7. Cluster deployment & rollback

Frontend digest pin (gitops `kustomize/overlays/test/kustomization.yaml`):
- `images: - name: frontend - newName: ghcr.io/halildeu/platform-web-frontend-testai - digest: sha256:<hex>` (immutable, D30 contract)
- `strategy: rollingUpdate.maxSurge: 0` patch (test overlay) — ResourceQuota 8 CPU hard cap altında frontend pod’unun yeniden oluşturulmasını garanti eder; aksi halde 200m CPU yeni pod fitting fail eder, deployment hung kalır

Live test cluster sequence:
- sha-224728d: PR-Refresh-4 deployed (single-flight refresh + full closure)
- sha-9d06576: PR-Obs-5 deployed (observability + degraded banner)

Prod overlay (`kustomize/overlays/prod`) digest bump 24h+ test smoke sonrası ayrı PR’la yapılır.

## Test stratejisi

| Kapı | Tool | Coverage |
|---|---|---|
| Unit (interceptor + FSM) | vitest | 51 shared-http + 21 mfe-shell observability + 15 auth.slice phase-machine |
| Integration (in-browser shell wiring) | vitest jsdom | AuthBootstrapper skip-gate (3), shell-services-wiring auth.ready() (5) |
| E2E (planned PR-E2E-6) | Playwright chromium | 4 hard-gate transport contract + 2 UI sentinel + chromium required, firefox/webkit nightly advisory |
| Live cluster smoke | manual + telemetry | 24h post-deploy degraded banner not-firing + refreshAttemptTotal.fail trending toward 0 |

## Sonuçlar (Outcomes)

### Olumlu
- ✅ Login flicker: `ValidatingMessage` transitional fazlarda gösteriliyor (PR-Auth-1)
- ✅ 401 storm: protected request’ler `transportReady` öncesi atılmıyor (PR-HTTP-3)
- ✅ Deadlock: bootstrap chain `__skipAuthReadyGate` ile gate’i bypass ediyor (PR-HTTP-3 iter-1)
- ✅ Re-login storm: gateway `/auth/cookie/refresh` 404 fix (canonical sha-76c517b) + frontend single-flight refresh (PR-Refresh-4)
- ✅ Bundle drift muğlaklığı: maxSurge=0 strategy patch + immutable digest pin
- ✅ Observability: prod’da auth/HTTP davranışını ölçecek PII-free counter + degraded UI sinyali (PR-Obs-5)

### Açık (PR-E2E-6 + PR-BE-7 sonrası kapanır)
- 🟡 E2E network contract gate (Playwright deterministic mock): test harness + CI infra prep gerekli (Codex `019e04e4` iter-1 PARTIAL)
- 🟡 Backend gateway 401 telemetry + rate limit (PR-BE-7): refresh storm’ları gateway tarafında da görünür olsun
- 🟡 PKCE multi-tab collision (kullanıcının yaşadığı bug): user-action “close extra tabs + clear cache” geçici workaround; permanent fix için per-tab kc-callback isolation veya cross-tab refresh leader-election ayrı follow-up

### Bilinen sınırlar
- Module federation no-share fallback yollarında telemetry shell collector’a akmıyor (out-of-scope)
- `AuthDegradedBanner` thresholdları (slow-init 30s, recent-fail >2/60s) statik; load-aware tuning gelecek faz
- ADR yalnızca platform-test cluster’ında doğrulandı; prod cluster cutover ayrı 24h smoke gerektirir

## Kararın eşdeğer alternatifleri (rejected)

| Alternatif | Ret nedeni |
|---|---|
| Server-side rendering with secure cookie hand-off | MFE module federation runtime → SSR pipeline overhead + remote MFE manifest fetch hâlâ client-side |
| Service worker proxy intercepting all `/api/*` | service worker registration ile auth FSM arasında kurulum sırası problemi; PWA scope iframe’li MFE’lerde flaky |
| OAuth2 BFF pattern (Keycloak token never reaches browser) | Backend BFF her MFE için endpoint çoğaltır + cookie size limit aşar; mevcut gateway’le çakışır |
| Manual `await auth.ready()` her MFE’de | Sözleşme runtime contract olmadan opt-in hale gelir; bir MFE unutursa 401 storm geri gelir |

Seçilen contract (gate at HTTP layer + FSM Promise bridge) bu alternatiflerden 3 axis daha iyi: (a) backend değişikliği gerektirmez, (b) MFE’lere transparent (call site değişmez), (c) tek source of truth (auth.slice.ts).

## Ekler

- Roadmap: PR-Auth-1 #302 → PR-Reporting-2 #304 → PR-HTTP-3 #306 → PR-Refresh-4 #307 → **PR-Obs-5 #309** → PR-E2E-6 (planned) → PR-BE-7 (planned) → **PR-ADR-8 (this document)**
- Gitops cluster pin sequence: PR #400 (sha-224728d) → frontend bump for sha-9d06576f (next)
- Audit: cross-AI peer review (HARD RULE — Reviewer ≠ Implementer): tüm PR’lar Codex AGREE post-impl ile merge edildi
- Pre-production full authority: kullanıcıya iş bırakma yok; agent end-to-end koşar (HARD RULE 2026-04-29)

---

**Karar kuralı (tek cümle)**: MFE’ler protected HTTP request’lerini, shell’in 5-fazlı auth FSM’i `transportReady` sinyalini verene kadar bekletir; gate’i bypass eden tek sınıf request bootstrap chain’in kendisidir; 401 single-flight refresh tek bir token rotation’a koalese eder; PII-free fetch telemetry + degraded UI banner contract ihlallerini operatöre görünür kılar.
