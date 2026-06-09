# Faz 22.5 — 22.5.3B/C Full-Surface Browser Acceptance (A4 COMPLETE) + A2 Rollout-Controls Finding (2026-06-09)

> Follow-up to `2026-06-09-ag039-ag040-225-3c-browser-smoke-acceptance.md`.
> Closes the assessment's **A4** "22.5.3B/C authenticated full-surface acceptance
> kısmi" gap **in full**, and records a precise **A2** (rollout controls) status.
> Method: Claude-in-Chrome MCP browser smoke on `testai.acik.com`, device
> **HALILKOOLUB735** (`d0efb00a`), frontend `sha-3627195`. (HARD RULE —
> Tarayıcıdan Sonuç Doğrulanmadan İş Bitmedi.)

## A4 — 22.5.3B + 22.5.3C full authenticated surface acceptance ✅ COMPLETE

Every endpoint-admin device-drawer surface was opened and verified **authenticated,
HTTP 200, console clean** (real session, real device):

| Surface | Tab | API | Status |
|---|---|---|---|
| AG-039 critical services | Hizmetler | `GET …/services/latest` | **200** ✅ (6 services real data) |
| AG-040 startup + exposure | Başlangıç + Maruziyet | `GET …/startup-exposure/latest` | **200** ✅ |
| BE-023 compliance (22.5.3B) | Uyum | `GET …/compliance` | **200** ✅ |
| BE-024 software diff (22.5.3C) | Yazılım Değişimleri | `GET …/software-inventory/diff` | **200** ✅ |
| BE-024b outdated diff (22.5.3C) | Güncel Olmayan Değişimler | `GET …/outdated-software/diff` | **200** ✅ |
| BE-025 prohibited (22.5.3C) | Yasaklı Yazılım | `GET …/prohibited-software` | **200** ✅ |

Console clean across all surfaces. **22.5.2A (AG-039/040) + 22.5.3B + 22.5.3C
authenticated browser acceptance: CLOSED.** Also deployed + visible in the drawer:
Görüntü Politikası (#508), Uygulama Kontrolü (AG-041), Hotfix Duruşu (AG-037),
Agent Tanılaması (AG-038), Yazılım Kataloğu.

## A2 — Rollout controls (22.5.8) status finding

- **Backend: SOURCE-MERGED + DEPLOYED on testai.** BE-026 rings (#478) / BE-027
  schedule (#490) / BE-028 throttle (#491) / BE-029 bundles (#492) / BE-030/031/032
  (#494/#495) merged 2026-06-06; the live endpoint-admin pod runs
  `sha-84c927b` (a post-2026-06-06 build that carries them).
- **Drift note:** live pod digest `sha-84c927b` ≠ test-overlay pin `sha-3e1e585`
  (#1392). A parallel session `kubectl set image`'d a newer digest without a
  durable overlay PR (the known kubectl-set-image drift pattern). A reconcile
  overlay bump is owed (tracked separately; heavy parallel-session contention on
  this overlay).
- **Functional acceptance is NOT a browser smoke (genuine gap, not pseudo-saturation):**
  the device drawer exposes inventory / posture / compliance surfaces only — there
  is **no rollout-ring / schedule / throttle management UI surface deployed**.
  Exercising a rollout (create ring → assign devices → schedule/throttle → bundle →
  verify staged fan-out) therefore requires either:
  1. a **frontend rollout-management surface** (a WEB build task — not yet built), or
  2. an **authenticated backend API integration harness** (admin-JWT + the BE-026..032
     POST/GET endpoints) — a backend integration smoke, not a UI smoke.
  Both are build/harness tasks beyond a "click a deployed tab" acceptance. This is
  the residual for 22.5.8 functional acceptance.

## Net (post this session)

- **Agent-doable browser-acceptance gaps: CLOSED** — AG-039, AG-040, 22.5.3B
  compliance, 22.5.3C diff/outdated/prohibited all authenticated-200 + console clean.
- **22.5.8 rollout controls:** backend deployed; functional acceptance gated on a
  frontend rollout-management surface (WEB build) or an API integration harness.
- Remaining 22.5 otherwise operator/infra/time-gated (multi-device 24h soak #1044,
  M0-M7 productization incl. M2 edge-mTLS #1359 + M4 signed MSI, domain pilot
  #1037/#1015, prod enablement).
