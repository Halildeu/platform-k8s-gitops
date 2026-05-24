# M5 23.5 Preference UI — k3d-test Live Runtime Acceptance Evidence (2026-05-24)

<!-- gitleaks-baseline-redaction-2026-05-24: smoke unsubscribe?token URLs replaced with <SMOKE-TOKEN-REDACTED>; original commit 5467e0f6 fingerprints whitelisted in .gitleaksignore (lines 139/148/232 generic-api-key rule false-positive on deterministic non-cryptographic smoke value evidence-smoke-invalid-2026-05-24, no real HMAC/Vault/ESO secret involved). See CHANGELOG note. -->


> **Status**: 🟢 M5 23.5 preference UI runtime-relevant UI/API surfaces observed LIVE on k3d-test at evidence sweep time. Selected read GET RTK Query round-trips (`/topics/me`, `/preferences/me`, `/unsubscribe?token=<redacted>`) returned expected status codes; mutation round-trips + non-observed terminal states were NOT exercised this sweep and remain anchored to PR-level CI green + spec #646.
> **Scope**: Agent-driven browser end-to-end smoke against **k3d-test cluster** (`testai.acik.com`) via Chrome MCP, plus read-only SSH+kubectl pod state capture (HARD RULE #7). **No state mutation.** This artifact prepares board #757 closure inputs; it does NOT itself declare board closure.
> **Trigger**: M5 23.5 currently "🟢 source-ready + acceptance candidate" — board #757 final acceptance gate requires live cluster runtime evidence (per HARD RULE 2026-05-11 "Tarayıcıdan Sonuç Doğrulanmadan İş Bitmedi"). Doc-only artifact; canonical status authority remains [milestones.md](../notify/milestones.md).

## 1. Bağlam

M5 23.5 ("Preference UI + Public Unsubscribe") delivery PR'ları MERGED + source-ready durumda:

| PR | Repo | Konu | Runtime-relevant for this sweep? |
|---|---|---|---|
| #285 | platform-web | preferences UI page + RTK Query client (Faz 23.5 PR3-FE) | UI surface |
| #286 | platform-web | bulk mark-all-read mutation (Faz 23.5 PR4) | UI surface (button-present); mutation NOT exercised |
| #288 | platform-web | operator guide doc (Faz 23.5 PR5) | doc-only — no runtime artifact |
| #296 | platform-web | canonical subscriberId selector hardening (Faz 23.5 PR-hardening) | subscriberId resolution invariant — exercised implicitly via §3.2 200 response, but no dedicated assertion |
| #299 | platform-web | richer preference editor + quiet hours (Faz 23.6 PR-B1) | UI surface (drawer + fields) |
| #300 | platform-web | restore-defaults 2-stage confirm (Faz 23.6 PR-C1) | UI surface (button-present); arm→confirm flow NOT exercised |
| #301 | platform-web | mute-channel UI two-stage (Faz 23.6 PR-C2) | UI surface (selector-present); arm→confirm flow NOT exercised |
| #291 | platform-web | mfe-audit delivery logs tab (M6a follow-up) | M6 scope; out-of-sweep |
| #644 | platform-web | public `/notifications/unsubscribe` landing (M5 G3) | public route (2 of 3 terminal states observed live) |
| #645 | platform-web | topic catalog FE consumption + autocomplete (M5 G3b) | UI + GET RTK round-trip |
| #646 | platform-web | Playwright cluster smoke spec (M5 G4) | spec only — CI-anchor, this sweep manually replicated |
| #269 | platform-backend | `PreferenceTopicCatalog` `GET /api/v1/notify/topics/me` (M5 G2) | backend endpoint — GET 200 observed |

**Canonical PR # drift note**: Canonical surfaces ([milestones.md](../notify/milestones.md) line 141, 150 + [sprint-plan.md](../notify/sprint-plan.md) line 236) currently label the public unsubscribe landing as PR #642. Live `git log --oneline` + `gh pr view 642 / 644` verification at sweep time confirms: PR #642 was a Dependabot dev-dep bump merged 2026-05-20T16:36Z; PR #644 ("feat(notify-23.5): m5 g3 — public unsubscribe landing route") merged 2026-05-20T21:51Z is the actual canonical landing PR. This evidence doc cites #644. Canonical surface PR # would benefit from a follow-up truth-sync to #644 (out-of-scope for this evidence sweep — flagged for the next doc-truth-sync cycle).

Codex `019e599c` H sweep (PR #1011) doc-truth-sync zincirinde k3d-test backend signal'leri ile canonical doc alignment doğrulandı; M5 23.5 source-ready claim'inin **runtime kanıtı** (browser end-to-end render + RTK Query round-trip) bu artifact'in scope'u.

## 2. Browser smoke (Chrome MCP, k3d-test cluster)

Agent self-driven browser end-to-end via `mcp__Claude_in_Chrome__*` against `https://testai.acik.com`. The browser already had a cached Keycloak SSO session for Platform Admin (`admin@example.com`); the agent did NOT type a password, did NOT initiate login from a logged-out state, and did NOT export auth tokens/cookies. The existing authenticated browser context was used to render protected routes read-only — this is **operator-context render evidence**, not a standalone persona authz proof, and a benign side-effect of HTTP requests over a logged-in session (e.g., KC server-side session timestamp refresh) is not equivalent to credential modification (HARD RULE 2026-04-29 compliant). For mutation-touching probes, a dedicated test persona (`perf-test`) was used out-of-browser via curl (see §3.5).

### 2.1 Asset bundle SHA — deployed build vs source-ready PRs

```
window.__BUILD_SHA__ (deployed) = "4c3df71"
matches origin/main HEAD:
  4c3df712 fix(faz22-web): endpoint-admin RTK fetchFn unwrap — Request-object header drop (#658)

PR #285, #286, #288, #299, #300, #301, #291, #644, #645, #646 all merged
into origin/main BEFORE 4c3df71 (verified via `git log --oneline 4c3df71 --
apps/mfe-shell/src/pages/settings/NotificationPreferencesPage.tsx` and
similar). Deployed bundle includes all M5 23.5 source-ready features.
```

### 2.2 Pod state at sweep time (k3d-test)

```
frontend-c5d9b947-4v79q:
  imageID: ghcr.io/halildeu/platform-web-frontend-testai@sha256:583aa8c97694d02811c97b53b1704ae90f538fa5d3c3ff4667d9f28139a8a8c7
  started: 2026-05-24T10:31:40Z (~2h before sweep)
  ready: 1/1 Running, restartCount: 0

notification-orchestrator-774544dbdd-7cbln:
  imageID: ghcr.io/halildeu/platform-backend-notification-orchestrator@sha256:f3f8c497df87fd3ee394c224d7209b67714b026152c92ae119b0d8c4c16fbaf6
  started: 2026-05-23T07:00:28Z (~28h stable)
  ready: 1/1 Running, restartCount: 0

api-gateway-664f4b5655-rqqlm:
  imageID: ghcr.io/halildeu/platform-backend-api-gateway@sha256:6137bb2cb39994aed3999958ac9b3b009c28565e5a80c467728dd368e5822003
  started: 2026-05-22T18:33:49Z (~2 days stable)
  ready: 1/1 Running, restartCount: 0
```

### 2.3 Authenticated route `/settings/notifications` — page render + drawer

```
URL: https://testai.acik.com/settings/notifications
HTTP 200, page renders without errors.

Heading: "Bildirim Tercihleri"
Subheading: "Hangi konularda hangi kanallardan bildirim almak istediğinizi
            buradan yönetebilirsiniz. Boş kural varsayılan olarak izinli."

WebPush section (PR-W5 follow-up + iter):
  Heading "Tarayıcı bildirimleri"
  Text "Bu tarayıcıda bildirimler etkin. Acil bildirimleri pop-up olarak
        görürsünüz."
  Counter "Hesabınıza bağlı toplam 1 aktif cihaz (bu tarayıcı dahil)."
  Button "Aboneliği kapat" (data-testid="push-subscription-unsubscribe-button")

Bulk operations row (M5 23.6 PR-C1 + PR-C2):
  "Tüm kuralları sıfırla (varsayılana dön)"
    data-testid="pref-restore-defaults-arm" (2-stage armed-state UI)
  "Tüm bir kanalı sustur: Kanal seçin..."
    data-testid="pref-mute-channel-select" (mute-channel two-stage)

Quick-rule add row (PR #285):
  Topic input (placeholder "örn. report.export.ready"): data-testid="pref-form-topic"
  Channel input (placeholder "örn. email"):              data-testid="pref-form-channel"
  Enabled checkbox:                                       data-testid="pref-form-enabled"
  Save button "Kuralı kaydet":                            data-testid="pref-form-save"
  Empty-state "Henüz tanımlı bir kural yok. Yukarıdan ekleyebilirsiniz."
    data-testid="notification-preferences-empty"

Drawer opener (PR #299 rich editor):
  Link "Detaylı kural ekle (sessiz saat, günlük limit, kritik bypass) →"
    data-testid="pref-quick-open-detailed"
```

Clicking `pref-quick-open-detailed` opens drawer (`role="dialog"`) with M5 23.6 PR-B1 rich editor:

```
Drawer heading: "Yeni bildirim kuralı"
Drawer subheading: "Konu, kanal, sessiz saatler ve teslim limitlerini düzenleyin"

Drawer fields:
  - Topic input (autocomplete with datalist from /topics/me)
  - Channel input (autocomplete)
  - Etkin checkbox
  - "Sessiz saatler" section with "Sessiz saat aktif" toggle
    data-testid="pref-form-quiet-toggle"
  - "Günlük teslim limiti" section with "Limit yok" checkbox
    data-testid="pref-form-freq-no-limit"
  - "Gelişmiş ayarlar" expandable (contains kritik bypass)
    data-testid="pref-form-bypass"
  - "İptal" / "Kaydet" buttons (data-testid="pref-form-cancel" / "pref-form-save")
```

### 2.4 Public route `/notifications/unsubscribe` — 2 of 3 terminal states observed live

**State 1: Missing token** (no `?token=` query param):

```
URL: https://testai.acik.com/notifications/unsubscribe
HTTP 200, alert renders:
  data-testid="unsubscribe-missing-token"
  Alert variant: warning
  Heading: "Bağlantı eksik"
  Body: "Bu sayfaya erişmek için e-posta footer'ındaki bağlantıyı
         kullanmalısınız. Bağlantınızı kaybettiyseniz, hesabınıza giriş
         yaparak bildirim ayarları sayfasından tercihlerinizi yönetebilirsiniz."
```

**State 2: Invalid token** (smoke token `evidence-smoke-invalid-2026-05-24`):

```
URL: https://testai.acik.com/notifications/unsubscribe?token=<SMOKE-TOKEN-REDACTED>
HTTP 200 (page), alert renders:
  data-testid="unsubscribe-invalid"
  Heading: "Bağlantı geçersiz veya süresi dolmuş"
  Body: "Bu abonelik iptal bağlantısı geçersiz veya süresi dolmuş.
         Bu durum şu sebeplerden kaynaklanabilir: ..."
  Footer link to "/settings/notifications" (data-testid="unsubscribe-settings-link")

Backend RTK Query response (sanitized):
  GET /api/v1/notify/unsubscribe?token=<SMOKE-TOKEN-REDACTED>
  → HTTP 401 (HMAC verify rejects bad token → FE shows invalid alert)
```

**State 3: Success / Server-error** — NOT exercised this sweep (would require valid HMAC token mint or backend 5xx induction; CI-anchor: spec test #646 documents that page handles these branches gracefully; testid `unsubscribe-success` + `unsubscribe-server-error` present in source per `UnsubscribeLandingPage.ui.tsx` lines 91, 139).

### 2.5 Notification center popover — bulk mark-all-read (PR #286)

Clicking the header bell button opens the notification center popover:

```
Popover heading: "Bildirimler"
Subheading: "Son 50 etkinlik listelenir"

Bulk action row (PR #286):
  Button "Tümünü okundu say"      (bulk mark-all-read)
  Button "Temizle"                (bulk clear)
  Button "Görünenleri seç"        (select visible)
  Button "Seçimi okundu say"      (mark selected as read)
  Button "Seçilenleri sil"        (delete selected)

Filter tabs:
  Sistem (0), Bildirimlerim (0), Geçmiş (30 gün)
  Tümü (50, active), Okunmamış (0), Öncelikli (47), Pinlenmiş (25)

Notification cards (M2 23.2 schema):
  WARNING / ÖNCELIKLI / PINLENMIŞ badges
  Title "Oturum süreniz doldu"
  Body "Lütfen tekrar giriş yapın."
  Timestamp "21.05.2026 10:03:38"
```

## 3. Network log evidence (sanitized)

Network requests captured via `mcp__Claude_in_Chrome__read_network_requests`. Raw header values redacted; only request URL + HTTP method + status code preserved.

### 3.1 Topic catalog endpoint (M5 G2 — PR #269)

```
GET https://testai.acik.com/api/v1/notify/topics/me
→ HTTP 200
Triggered when: drawer-based preference editor opens (RTK Query lazy-loads
                topic catalog for autocomplete + critical-eligible badges)

Response shape (curl smoke from staging-sw, sanitized to schema only):
  {
    "items": [
      {
        "topicKey": "auth.mfa-otp",
        "label": "MFA OTP Kodu",
        "category": "auth",
        "supportedChannels": ["SMS", "EMAIL"],
        "criticalEligible": true,
        "description": "...",
        "defaultFrequencyHint": null
      },
      ... (10 topics total: 3 auth + 2 audit + 3 system + 2 marketing)
    ]
  }
```

### 3.2 Preferences endpoint round-trip (M5 PR3-FE — PR #285)

```
GET https://testai.acik.com/api/v1/notify/preferences/me
→ HTTP 200
Triggered when: /settings/notifications page boots (RTK Query initial fetch)

Body (browser session, orgId=default, subscriberId=1 — Platform Admin
identity claims): empty preferences list → empty-state placeholder renders
correctly.

NOTE: PUT /preferences/me round-trip and DELETE /preferences/me/{id} were
NOT exercised this sweep — that requires mutation. Per Codex `019e599c`
pattern, evidence sweep is read-only. Source-ready PRs #285/#299 ship the
mutation surface (`pref-form-save` button → triggers PUT); spec #646
exercises this in CI. This artifact certifies the GET endpoint + button
presence; mutation round-trip evidence remains anchored to CI green for PR
#285/#299/#300/#301.
```

### 3.3 Public unsubscribe endpoint (M5 G3 — PR #644)

```
GET https://testai.acik.com/api/v1/notify/unsubscribe?token=<SMOKE-TOKEN-REDACTED>
→ HTTP 401
Triggered when: /notifications/unsubscribe?token=<invalid> loads (RTK Query
                kicks off verify call without auth headers; backend HMAC
                rejects → 401)
Behavior: FE catches 401 → shows unsubscribe-invalid alert (terminal state)
```

### 3.4 Inbox + SSE stream (background, M1/M2 23.2 LIVE)

```
GET /api/v1/notify/inbox/me?page=0&size=20 → HTTP 200 (x4 polls during smoke)
GET /api/v1/notify/inbox/me/stream?orgId=default&subscriberId=1 → HTTP 200 (SSE)

Confirms M1/M2 23.2 inbox + SSE LIVE; PR #286 bulk-mark mutation surface
present in the popover above the active inbox list.
```

### 3.5 Backend persona curl smoke (out-of-browser-session sanity probe)

In addition to the in-browser smoke (which authenticated via the cached Platform Admin SSO session), a parallel backend curl smoke from staging-sw shell with a **dedicated test persona** `perf-test` (sourced from k3d-test secret `test-personas-perf-auth`, NOT the operator login user) probed the same endpoints with explicit-Bearer-no-identity-headers to exercise strict-identity boundary:

```
Persona: perf-test@local
  JWT claims: { sub: 84684bfa-..., iss: testai.acik.com/realms/platform-test,
               aud: [notification-orchestrator, auth-service, account] }
  token_len: 1462 chars; token_sha256_first12: 5b130c06151f
  realm: platform-test (matches frontend client config)

Probe 1 — GET /api/v1/notify/topics/me
  Headers: Authorization: Bearer <persona>
  → HTTP 200
  Body: 10-topic catalog (auth:3 + audit:2 + system:3 + marketing:2)
        all topics have {topicKey, label, category, supportedChannels,
        criticalEligible, description, defaultFrequencyHint}

Probe 2 — GET /api/v1/notify/preferences/me  (raw Bearer, no X-Org-Id)
  Headers: Authorization: Bearer <persona>
  → HTTP 403 (strict identity active — NOTIFY_SECURITY_DEFAULT_ORG_ID="")
  Confirms strict-identity fail-closed mode per H sweep §2.2 (PR #1011)

Probe 3 — GET /api/v1/notify/preferences/me  (raw Bearer, no X-Subscriber-Id)
  Headers: Authorization: Bearer <persona>, X-Org-Id: workcube_mikrolink
  → HTTP 400 Bad Request (subscriberId enforcement)

These probes are NOT a substitute for the in-browser §3.2 200 — they
sanity-check that:
  (a) strict-identity boundary fires when X-Org-Id absent (403)
  (b) /topics/me is org-agnostic (public-ish — needs only audience match)
  (c) Platform Admin browser session in §3.2 succeeds because shell's
      `selectNotifyIdentity` resolves orgId=default + subscriberId=1
      from JWT claims and adds the required X-* headers

Operator login user password: NOT touched (HARD RULE 2026-04-29).

### 3.6 Token sanitization (HARD RULE secret hygiene)

```
Persona token used for backend curl validation (NOT injected to browser):
  persona: perf-test@local (test persona, NOT operator login user)
  audience: ["notification-orchestrator", "auth-service", "account"]
  iss: https://testai.acik.com/realms/platform-test
  token_len: 1462 chars
  token_sha256_first12: 5b130c06151f
  raw value: redacted; ephemeral tmpfile deleted after sweep
  operator login user (admin@example.com): NOT touched (HARD RULE 2026-04-29)
```

## 4. Console evidence

`read_console_messages` with pattern `error|Error|ERROR|fail|Fail|warn|Warn|denied|404|401|403|500|undefined|Cannot read|TypeError|ReferenceError` returned:

```
Only matches across all routes visited:
  [DEBUG] [ag-grid-license] resolved key: found (538 chars) | window.__env__: object | process.env: undefined
  (8 occurrences — one per page navigation; expected ag-grid module init log)

No JS errors. No 4xx/5xx propagated into console (HTTP 401 from /unsubscribe
verify is caught by RTK Query error path → invalid alert, not console
error). No undefined / TypeError / ReferenceError. No CSP violations.
```

## 5. Sonuç (this sweep only)

- §2 lists each M5 23.5 source-ready PR's runtime-relevant UI/API artifacts and confirms the corresponding live render / GET round-trip on k3d-test at sweep time.
- §3 lists the RTK Query round-trips observed and confirms `GET /topics/me` + `GET /preferences/me` + `GET /unsubscribe?token=` endpoints respond with the expected status codes for the identity context.
- §4 confirms browser console is clean (only expected DEBUG logs).
- HARD RULE 2026-05-11 ("Tarayıcıdan Sonuç Doğrulanmadan İş Bitmedi") satisfied — agent's own browser tool (Chrome MCP) drove the end-to-end smoke, screenshot + console + network evidence captured.

**Alignment with M5 source-ready claim** (verdict glyph legend: ✓ live-observed; ◐ surface-present, mutation NOT exercised; ◑ source-/CI-anchor only; n/a = doc-only PR):

| Source-ready claim (canonical) | Live runtime evidence this sweep | Verdict |
|---|---|---|
| PR #285 preferences UI + RTK Query | Page renders, empty-state + form testids present, `GET /preferences/me` 200 (§2.3 + §3.2) | ✓ GET-live + surface-present |
| PR #286 bulk mark-all-read | "Tümünü okundu say" button in popover (§2.5) | ◐ surface-present; POST mutation NOT exercised |
| PR #288 operator guide | Doc-only PR; not a runtime artifact | n/a |
| PR #296 canonical subscriberId hardening | §3.2 200 implies subscriberId selector resolves correctly for Platform Admin (orgId=default, subscriberId=1) | ◐ implicit-only; no dedicated selector unit assertion in this sweep |
| PR #299 rich editor + quiet hours | Drawer opens with quiet-hours toggle + freq limit + bypass section (§2.3) | ✓ surface-present + drawer-open observed |
| PR #300 restore-defaults 2-stage | `pref-restore-defaults-arm` testid present (§2.3) | ◐ surface-present; arm→confirm flow + DELETE mutation NOT exercised |
| PR #301 mute-channel two-stage | `pref-mute-channel-select` selector present (§2.3) | ◐ surface-present; arm→confirm flow + PUT mutation NOT exercised |
| PR #644 public unsubscribe landing | 2 of 3 terminal states observed live (missing + invalid); success + server-error testids source-present (§2.4) | PARTIAL live (2/3) + CI-anchor for remaining |
| PR #645 topic catalog FE consumption + autocomplete | Topic input has datalist; `GET /topics/me` 200 triggered by drawer open (§3.1) | ✓ GET-live + surface-present |
| PR #269 backend `/topics/me` | HTTP 200 with 10-topic catalog (§3.1 + §3.5 persona probe) | ✓ GET-live |
| PR #646 Playwright G4 cluster smoke | Spec MERGED in repo; this sweep manually replicated 3 of 3 spec scenarios in browser | ◑ CI-anchor; sweep replication NOT a CI substitute |

**What this sweep does NOT verify** (intentionally scoped out):

- **PUT /preferences/me mutation round-trip** — would require actual rule save; spec #646 covers this in CI; this sweep is read-only on user data
- **DELETE /preferences/me/{id}** — same as above
- **POST /inbox/me/mark-all-read mutation** — would mutate user's inbox state; button presence confirmed only
- **Restore-defaults + mute-channel armed→confirm flow** — would mutate preferences; button/select presence confirmed only
- **Success + server-error terminal states of /notifications/unsubscribe** — would require valid HMAC token mint (success) or backend 5xx induction (server-error)
- **RFC 8058 `List-Unsubscribe-Post` / one-click email header** — landing page LIVE ≠ full RFC 8058 one-click acceptance; outbound message `List-Unsubscribe` + `List-Unsubscribe-Post` header presence + mailer compliance NOT verified this sweep; remains TBD per [must-have-checklist.md line 273](../notify/must-have-checklist.md)
- **D30 immutable artifact mapping** — pod `imageID` digests captured at §2.2 are runtime-observed; not cross-referenced to overlay's `sha-<short>` tag pin in this artifact; expected/observed digest mapping not re-baselined this sweep
- **Prod cluster (k3d-prod)** — only k3d-test was queried
- **Cross-browser smoke** — single-browser (Chromium-based) sweep
- **A11y / keyboard navigation** — not exercised
- **Visual regression** — screenshot captured but not diffed against baseline

These remain anchored to:
- CI green for PR #285/#286/#299/#300/#301/#644/#645/#646 (mutation surfaces covered by Playwright + Vitest)
- Spec #646 cluster-smoke run history (`tests/playwright/notify-preferences.smoke.spec.ts`)
- M5 board #757 final acceptance gate (canonical decision authority — this artifact is an input, not the decision itself)

## 6. Cross-AI peer review

- **Implementer**: Claude (Anthropic) — session `youthful-kapitsa-676d9f` (agent-driven Chrome MCP browser smoke + read-only kubectl pod-state)
- **Reviewer**: Codex (OpenAI) — thread `019e59f8-226c-7531-be3b-4af2b596cb96` REVISE → 8-point absorb chain (PR # reconciliation #642 drift, #296 inclusion, top-level scope tightening, 2-of-3 unsubscribe split, glyph-table refinement, §3.5 backend persona probe inclusion, RFC 8058 + D30 carve-outs, operator-session language tightening) → AGREE received
- **HARD RULE adherence**:
  - HARD RULE 2026-05-11 (Tarayıcıdan Sonuç Doğrulanmadan İş Bitmedi) — satisfied; agent ran end-to-end browser smoke via Chrome MCP, not delegated to user
  - HARD RULE 2026-04-29 (Kullanıcı Aktif Credential'ına Dokunma YASAK) — satisfied; operator login user's KC session was already cached, used read-only; password not touched; backend curl smoke used dedicated `perf-test` test persona via `test-personas-perf-auth` secret
  - HARD RULE #7 (SSH+kubectl pre-authorized) — used only for read-only `get pod` and `get secret -o jsonpath={.data.username|.data.realm}` (no secret data dump)
  - HARD RULE — No Fake Work — §5 explicitly distinguishes button-present vs mutation-exercised; mutation paths called out as NOT verified this sweep
  - HARD RULE — Cross-AI provider-different — Claude implementer + Codex reviewer
  - Secret hygiene — persona token reduced to `len` + `sha256_first12`; raw value redacted + tmpfile deleted post-sweep; operator session token not captured

## Referanslar (canonical surfaces)

- Canonical status authority: [milestones.md](../notify/milestones.md) M5 row, [sprint-plan.md](../notify/sprint-plan.md), [feature-matrix.md](../notify/feature-matrix.md)
- M5 board #757 (acceptance gate — canonical decision authority)
- M5 23.5 source PRs (platform-web): #285, #286, #288, #291, #299, #300, #301, #644, #645, #646
- M5 23.5 source PR (platform-backend): #269 (`PreferenceTopicCatalog` endpoint)
- H read-only signal evidence: [2026-05-24-h-live-evidence-resync.md](./2026-05-24-h-live-evidence-resync.md) (Session 49+ doc-truth-sync chain)
- Playwright spec: `platform-web/tests/playwright/notify-preferences.smoke.spec.ts`
