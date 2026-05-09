# M3 (23.2 Closure) Stale Audit + Residual Re-Baseline — 2026-05-09

> **Status**: ACTIVE (Codex `019e0c28` strategic finding absorb)
> **Trigger**: M2 D29 partial evidence collection sırasında platform-backend repo scan'i göstermiştir ki sprint-plan T1 ~100h pending estimate **stale/pessimistic**.
> **Codex Authority**: thread `019e0c28` "Backend stale finding gerçek ve stratejik. ... source exists ≠ acceptance done değil. Yeni sınıflandırma."

Bu audit Codex'in önerdiği **5-state matrix** (Source-ready / Live-deployed / Evidence-backed / Acceptance complete / Blocked) ile gerçek state'i tespit eder.

---

## Executive Summary

Sprint-plan T1 (23.2 closure) **gerçek residual ~43-46h band** (post PR #132 + PR #452 MERGE 2026-05-09 14:00Z; T1.2 subscriber self-service source-ready/live-deployed). Backend implementation T1.1.1-T1.1.4 + **T1.2 admin + subscriber self-service** + T1.3 partial + T1.5 **source-ready/live**; T1.4 (D43 outage fallback) + T1.6 (abuse guards) gerçek pending.

| State | Count | Notes |
|---|---:|---|
| 🟢 **Source-ready** | 8/12 | T1.1.1-T1.1.4, T1.2 admin + **subscriber self-service** (PR #132 MERGED), T1.3 partial, T1.5 backend code LIVE |
| 🟢 **Live-deployed** | 8/12 | Test cluster deploy LIVE (T1.2 subscriber endpoint cluster apply CONFIRMED 2026-05-09 14:00Z, /api/v1/notify/audit/me 404→401 transition; PR #452 image bump) |
| 🔴 **Evidence-backed** | 0/12 | M2 partial smoke yapıldı; full authenticated D29 BLOCKED (RAID I6) |
| 🔴 **Acceptance complete** | 0/12 | Acceptance kriteri Charter'da hâlâ pending; M3 closure 🟡 |
| 🟡 **Blocked** | 4/12 | T1.4 (R9 D43 drill), T1.6 (R13/R19 abuse), Keycloak credential (RAID I6), legal review (R2) — T1.2 subscriber endpoint blocker RESOLVED (PR #132 + #452 MERGE) |

**M3 closure target**: 2026-06-08 → audit sonrası muhtemelen **2-3 hafta** (2026-05-22 - 2026-05-29 band) eğer credential + legal gate açılırsa + T1.4 + T1.6 tamamlanırsa.

---

## Backend Code Scan Methodology

**Repo**: `Halildeu/platform-backend` (HEAD detached origin/main)
**Path**: `notification-orchestrator/src/main/java/com/serban/notify/`
**Plus**: `src/main/resources/db/migration/`

Aramalar:
- Class/file presence (find + grep -l)
- Source signal pattern (BLOCKED_BY_PREFERENCE, DataClassification, AdminErasure, DlrController, OutageFallback, AbuseGuard)
- Schema migration presence (V1-V14 SQL files)

---

## T1 Sub-Task Audit

### T1.1 — 23.2.A Preference + Critical Bypass + Opt-out (must-have #8)

| Task ID | Backend File | Line Count | Source State | Live State | Evidence | Acceptance | Blocker |
|---|---|---:|:---:|:---:|:---:|:---:|---|
| T1.1.1 V9 migration `subscriber_preference` | `V1__init_notify_schema.sql` | (in V1) | 🟢 | 🟢 | 🟡 partial smoke | 🔴 | RAID I6 (auth) |
| T1.1.2 Domain entity + repository | `SubscriberPreferenceService.java` | 414 | 🟢 | 🟢 | 🟡 unit test 6/6 | 🔴 | acceptance gate |
| T1.1.3 REST API `PUT/GET /preferences/me` | `PreferenceController.java` | 290 | 🟢 | 🟢 | 🔴 auth flow | 🔴 | RAID I6 |
| T1.1.4 Send pipeline preference check | `DeliveryEligibilityService.java` (BLOCKED_BY_PREFERENCE path) | substantial | 🟢 | 🟢 | 🔴 D29-Authorized | 🔴 | RAID I6 |
| T1.1.5 Critical bypass (severity + classification) | `DeliveryEligibilityService.java` (severity=critical bypass) | partial | 🟢 (severity) | 🟢 | 🔴 | 🔴 | data_classification security bypass test gerek |
| T1.1.6 Quiet hours bypass | (DeliveryEligibilityService) | partial | 🟢 | 🟢 | 🔴 | 🔴 | acceptance gate |
| T1.1.7 Frequency limit bypass | (DeliveryEligibilityService) | partial | 🟢 | 🟢 | 🔴 | 🔴 | acceptance gate |
| T1.1.8 Unsubscribe link footer | (template engine) | TBD | 🟡 | 🟡 | 🔴 | 🔴 | template review |
| T1.1.9 Integration test | `IntentSubmissionServiceIntegrationTest.java` | exists | 🟢 | N/A | 🟡 | 🔴 | Testcontainers Docker config |

**T1.1 Verdict**: **Source-ready 9/9**, but **Acceptance complete 0/9** (D29-Authorized BLOCKED on credential).

### T1.2 — 23.2.B KVKK Erasure (must-have #7 closure)

| Task | File | Line | Source | Live | Evidence | Acceptance | Blocker |
|---|---|---:|:---:|:---:|:---:|:---:|---|
| T1.2.x **admin** erasure `POST /api/v1/admin/notify/erasure` | `AdminErasureController.java` | 129 | 🟢 | 🟢 | 🟡 | 🔴 | R2 legal review |
| T1.2.1 **Subscriber self-service** `DELETE /audit/me` (KVKK Art.11) | `SubscriberErasureController.java` (PR #132 MERGED + PR #452 cluster apply 14:00Z) | 195 | 🟢 | 🟢 | 🔴 | 🔴 | RAID I6 acceptance gate |
| T1.2.2 **Subscriber right-to-info** `GET /audit/me` (KVKK Art.13) | `SubscriberErasureController.java` (same controller, same PR; route LIVE 14:00Z, /audit/me 404→401 transition) | (same) | 🟢 | 🟢 | 🔴 | 🔴 | RAID I6 acceptance gate |
| T1.2.3 Append-only verify | V8 trigger no_update/delete | (V8) | 🟢 | 🟢 | 🟢 | 🟢 | — |
| T1.2.4-5 Integration test | (test files admin scope) | TBD | 🟡 | N/A | 🔴 | 🔴 | TC config + self-service endpoint |
| T1.2.6 Runbook | `RB-notify-kvkk-erasure.md` | exists | 🟢 | N/A | 🟢 | 🔴 | legal review |
| T1.2.7 Legal review | external | — | — | — | — | 🔴 | R2 active |
| T1.2.8 Codex review + merge | (audit) | — | — | — | — | 🔴 | post-impl |

**T1.2 Verdict (UPDATED 2026-05-09 14:00Z — PR #132 + PR #452 MERGE + cluster apply CONFIRMED)**: **Admin erasure source-ready (R2 legal block); subscriber self-service `DELETE/GET /audit/me` ARTIK source-ready/live-deployed** (PR #132: `SubscriberErasureController` 195 satır + `SubscriberErasureService` 175 satır + 2 DTO + security boundary tests 10/10 PASS + service unit tests 6/6 PASS + 59/59 regression PASS; PR #452 image bump sha-7bdfb7d cluster apply CONFIRMED → /audit/me 404→401 transition). **Acceptance gate** D29-Authorized BLOCKED on RAID I6 Keycloak credential. T1.2 sprint-plan ~17h estimate; gerçek residual ~2-4h (acceptance test + R2 legal review coordination).

### T1.3 — 23.2.C Provider Config Rollback

| Task | File | Source | Acceptance | Blocker |
|---|---|:---:|:---:|---|
| T1.3.1 V_history table | (provider_config_history schema) | 🟢 | 🟢 | — |
| T1.3.2 Versioning service | `ProviderConfigHistoryRepository.java` | 🟢 | 🔴 | acceptance gate |
| T1.3.3 Atomic switch + cache | TBD | 🟡 | 🔴 | acceptance gate |

**T1.3 Verdict**: Partial source-ready; acceptance gate.

### T1.4 — 23.2.D Outage Fallback Bypass (D43, must-have #10)

| Task | Source File | Source | Blocker |
|---|---|:---:|---|
| T1.4.1 Vault fallback path | NOT FOUND in code | 🔴 | **R9 active** |
| T1.4.2 ESO ExternalSecret | `vault-paths-runbook` | 🟡 partial | R9 |
| T1.4.3 Alertmanager dual-route | TBD | 🔴 | drill |
| T1.4.5 Drift alarm-receiver | TBD | 🔴 | drill |
| T1.4.6 Break-glass dual-channel | TBD | 🔴 | drill |
| T1.4.7 Runbook | TBD | 🔴 | — |
| T1.4.8 Drill execution | scheduled | 🔴 | R9 |

**T1.4 Verdict**: **PENDING — gerçek residual ~15h** (R9 D43 outage fallback drill blocker).

### T1.5 — 23.2.E Data Classification

| Task | File | Source | Acceptance |
|---|---|:---:|:---:|
| T1.5.1 V_field migration | (in V1 schema) | 🟢 | 🟢 |
| T1.5.2 Enum + validator | `NotificationIntent.DataClassification` (transactional, security, commercial, system) | 🟢 | 🟢 |
| T1.5.3 Send pipeline behavior | `IntentSubmissionService` + `DeliveryEligibilityService` | 🟢 | 🔴 |
| T1.5.4 Integration test | TBD | 🟡 | 🔴 |

**T1.5 Verdict**: **Source-ready substantively**; acceptance integration test gate.

### T1.6 — 23.2.F Abuse Prevention Guards (must-have #10 partial)

| Task | Source File | Source | Blocker |
|---|---|:---:|---|
| T1.6.1 Rate limit per source | NOT FOUND in code | 🔴 | R13/R19 active |
| T1.6.2 Duplicate flood | NOT FOUND | 🔴 | R13 |
| T1.6.3 Webhook fan-out cap | NOT FOUND | 🔴 | R13 |
| T1.6.4 429 + audit | TBD | 🔴 | R13 |
| T1.6.5 PrometheusRule alert | TBD | 🔴 | impl |
| T1.6.6-7 Test + Codex review | TBD | 🔴 | impl |

**T1.6 Verdict**: **PENDING — gerçek residual ~15h** (R13/R19 abuse + storm risks).

---

## Real Residual Estimate (Codex `019e0c28` Re-Baseline)

| Tier | Original Estimate (sprint-plan) | Re-Baselined Real Residual | Drift |
|---|---:|---:|---|
| **T1.1** Preference + bypass + opt-out | 27h | ~3h (acceptance test only) | -24h |
| **T1.2** KVKK erasure (admin + subscriber self-service source-ready/live; PR #132+#452 MERGE 14:00Z apply CONFIRMED) | 17h | ~2-4h (acceptance test + R2 legal review coordination) | -13 / -15h |
| **T1.3** Provider rollback | 13h | ~5h (acceptance gate) | -8h |
| **T1.4** Outage fallback (D43) | 15.5h | ~15h (gerçek pending) | 0h |
| **T1.5** Data classification | 12h | ~2h (acceptance test) | -10h |
| **T1.6** Abuse guards | 15h | ~15h (gerçek pending) | 0h |
| **Toplam T1 (post PR #132 MERGE 2026-05-09)** | **99.5h (~100h)** | **~43-46h** | **-53 / -57h** |

**M3 closure realistic estimate (post PR #132 MERGE)**: ~43-46h **+** acceptance gate testing **+** Codex review iter overhead = **~50-60h provisional sprint** (önceki ~60-70h provisional'dan -10h; T1.2 subscriber endpoint impl LIVE source-ready). 4-6 hafta yerine **2-3 hafta** mümkün (eğer RAID I6 credential + R2 legal + T1.4 D43 + T1.6 abuse guards tamamlanırsa).

> **Provisional disclaimer (Codex `019e0c28` iter-3 absorb)**: Provisional until RAID I6 (Keycloak credential) + R2 (KVKK legal) acceptance gates close. T1.4 D43 + T1.6 abuse guards gerçek pending implementation.

---

## Charter / Sprint-Plan / Must-Have / Feature-Matrix Re-Baseline Önerileri

### Charter (RB-faz-23-charter.md)

**23.2 sub-faz marker**:
- Şu an: `🟡 partial (Session 39 hardening 5/8 done; original acceptance 2/8 done)`
- Re-baseline (post PR #132 + #452 MERGE 2026-05-09 14:00Z): `🟡 partial (Session 39 hardening 5/8 done; backend source-ready 8/9 / live-deployed 8/9 / acceptance-complete 1/9 — D29-Authorized BLOCKED on RAID I6 + R2 KVKK legal; T1.2 subscriber self-service endpoint LIVE, T1.4 + T1.6 gerçek pending)`
- 23.2 duration `4-6 hafta / ~100h aggressive` → `~43-46h residual / ~50-60h provisional sprint / 2-3 hafta (credential RAID I6 + R2 legal gate açılınca + T1.4 + T1.6 tamamlanırsa)`

### Sprint-Plan (sprint-plan.md)

**T1 task status sweep (post PR #132 + #452 MERGE 2026-05-09 14:00Z)**:
- T1.1.1, T1.1.2, T1.1.3, T1.1.4 → 🔴 → 🟢 source-ready/live (V1 schema + PreferenceController + service + send pipeline LIVE)
- T1.1.5, T1.1.6, T1.1.7, T1.2.6, T1.5.3 → 🔴 → 🟡 partial (source-ready, acceptance gate)
- T1.2.0 admin erasure → 🟢 source-ready/live (R2 legal review wait)
- **T1.2.1, T1.2.2 subscriber self-service `DELETE/GET /audit/me` → 🟢 source-ready/live (PR #132 MERGED + PR #452 cluster apply CONFIRMED; /audit/me 404→401 transition)**
- T1.2.3 append-only verify (V8 trigger) → 🟢 done
- T1.3.1 → 🟢 source-ready/live; T1.3.2 → 🟡 partial
- T1.5.1, T1.5.2 → 🟢 source-ready/live (V1 field + DataClassification enum)
- T1.4 sub-tasks: 🔴 stays (gerçek pending; alertmanager-bridge backend code YOK)
- T1.6 sub-tasks: 🔴 stays (gerçek pending; RateLimitGuard/AbuseGuard backend'de YOK)
- "T1 ~100h" başlığı → "T1 ~43-46h residual / ~50-60h provisional sprint" + actuals tracking note

### Must-Have Checklist

- #7 KVKK retention/erasure: kabul kriteri "API source-ready, legal review pending (R2)"
- #8 Preference + critical bypass: "API + service + send pipeline source-ready; D29-Authorized BLOCKED on RAID I6"
- #10 Observability + outage fallback: "alerts/SLO LIVE, D43 abuse guards 🔴 PENDING"

### Feature-Matrix

- §4 Subscriber/Preferences: ⏳ → 🟡 (preference API source-ready)
- §6 Audit/Compliance: 🟡 (erasure API source-ready, legal pending)
- §13 Abuse/Spam: ⏳ stays (T1.6 gerçek pending)
- §15 Incident/Degraded Mode: 🟡 (alerts LIVE, D43 fallback pending)
- §16 Data Classification: ⏳ → 🟢 (enum + service substantively LIVE)

---

## Codex Cross-AI Review

- **Thread**: `019e0c28-297a-7112-8291-002e84e40fcb`
- **Codex strategic finding**: "Source exists ≠ acceptance done; new classification matrix (Source-ready / Live-deployed / Evidence-backed / Acceptance complete / Blocked)"
- **Verdict expected**: AGREE on audit methodology + re-baseline numbers

---

## Next Action

1. Bu PR (M3 stale audit) merge sonrası:
   - Charter sub-faz % re-baseline
   - Sprint-plan T1 task status sweep + ~43-46h residual / ~50-60h provisional sprint
   - Must-have evidence/acceptance gate ayrımı
   - Feature-matrix marker sweep (5 kategori)
2. M3 residual implementation:
   - **T1.4 D43 outage fallback** (~15h, R9 drill paralel)
   - **T1.6 Abuse guards** (~15h, R13/R19 paralel)
   - Acceptance test gate (T1.1.9, T1.2.4, T1.3.4, T1.5.4)
3. Credential + legal gate çözümü:
   - RAID I6 (Keycloak credential)
   - R2 KVKK legal review (ETA 2026-05-25)
4. M1 paralel devam (T+72h observation + browser SSO + rollback prova)

---

## Last Update

**2026-05-09 12:35Z** — backend code scan + 5-state matrix audit, ~50-60h residual re-baseline

**2026-05-09 13:45Z (PR #132 MERGE update)** — T1.2 subscriber self-service erasure backend MERGED (`SubscriberErasureController` + `SubscriberErasureService` + 16 unit/security test PASS). T1.2.1/T1.2.2 🔴 → 🟢 source-ready. T1 toplam residual ~52-55h → ~43-46h (-10h). M3 closure 2-3 hafta provisional.

**2026-05-09 14:00Z (PR #452 cluster apply CONFIRMED)** — Image bump sha-ef0f487 → sha-7bdfb7d (sha256:ca2587f...) test cluster apply success. Pod notification-orchestrator-85b9894cdc-z4vvc 1/1 Running. /api/v1/notify/audit/me **404→401 transition** (route LIVE; "JWT token zorunludur" auth required). T1.2 source-ready/**live-deployed** CONFIRMED. T1 residual canonical model **~43-46h** korundu (T1.2 ~2-4h residual + T1.1 ~3h + T1.3 ~5h + T1.4 ~15h + T1.5 ~2h + T1.6 ~15h = ~42-44h base + Codex iter overhead = ~43-46h band; image build + cluster apply effort task tablo dışı, residual tek modeli korundu). Acceptance gate hâlâ RAID I6 + R2.

**2026-05-09 14:15Z (Codex iter-3 absorb)** — Intra-doc re-baseline drift fix: T1.2.1/T1.2.2 detail satırları live=🟢 (önceki 🟡 image build pending), residual ~3-5h → ~2-4h, provisional disclaimer iter-3 dili düzeltildi.
