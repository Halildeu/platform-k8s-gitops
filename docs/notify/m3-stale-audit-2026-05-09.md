# M3 (23.2 Closure) Stale Audit + Residual Re-Baseline — 2026-05-09

> **Status**: ACTIVE (Codex `019e0c28` strategic finding absorb)
> **Trigger**: M2 D29 partial evidence collection sırasında platform-backend repo scan'i göstermiştir ki sprint-plan T1 ~100h pending estimate **stale/pessimistic**.
> **Codex Authority**: thread `019e0c28` "Backend stale finding gerçek ve stratejik. ... source exists ≠ acceptance done değil. Yeni sınıflandırma."

Bu audit Codex'in önerdiği **5-state matrix** (Source-ready / Live-deployed / Evidence-backed / Acceptance complete / Blocked) ile gerçek state'i tespit eder.

---

## Executive Summary

Sprint-plan T1 (23.2 closure) **gerçek residual ~52-55h band** (iter-2 absorb sonrası iter-1'in ~42h iddiası düzeltildi), önceki ~100h estimate'in altında ama iyimser olmayan. Backend implementation T1.1.1-T1.1.4 + T1.2 admin scope + T1.3 partial + T1.5 **source-ready/live**; T1.2 subscriber self-service (`DELETE/GET /audit/me`) gerçek pending; T1.4 (D43 outage fallback) + T1.6 (abuse guards) gerçek pending.

| State | Count | Notes |
|---|---:|---|
| 🟢 **Source-ready** | 7/12 | T1.1.1-T1.1.4, T1.2 admin, T1.3 partial, T1.5 backend code LIVE; T1.2 subscriber self-service backend'de YOK |
| 🟡 **Live-deployed** | 7/12 | Test cluster deploy tested; pod LIVE (subscriber self-service hariç) |
| 🔴 **Evidence-backed** | 0/12 | M2 partial smoke yapıldı; full authenticated D29 BLOCKED (RAID I6) |
| 🔴 **Acceptance complete** | 0/12 | Acceptance kriteri Charter'da hâlâ pending; M3 closure 🟡 |
| 🟡 **Blocked** | 5/12 | T1.2 subscriber endpoint (yeni impl), T1.4 (R9 D43 drill), T1.6 (R13/R19 abuse), Keycloak credential (RAID I6), legal review (R2) |

**M3 closure target**: 2026-06-08 → audit sonrası muhtemelen **2.5-3.5 hafta** (2026-05-25 - 2026-06-01 band) eğer credential + legal gate açılırsa + T1.2 subscriber endpoint impl + T1.4 + T1.6 tamamlanırsa.

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
| T1.2.1 **Subscriber self-service** `DELETE /audit/me` (KVKK Art.11) | NOT FOUND in code (admin scope only) | — | 🔴 | 🔴 | 🔴 | 🔴 | gerçek pending implementation |
| T1.2.2 **Subscriber right-to-info** `GET /audit/me` (KVKK Art.13) | NOT FOUND in code | — | 🔴 | 🔴 | 🔴 | 🔴 | gerçek pending implementation |
| T1.2.3 Append-only verify | V8 trigger no_update/delete | (V8) | 🟢 | 🟢 | 🟢 | 🟢 | — |
| T1.2.4-5 Integration test | (test files admin scope) | TBD | 🟡 | N/A | 🔴 | 🔴 | TC config + self-service endpoint |
| T1.2.6 Runbook | `RB-notify-kvkk-erasure.md` | exists | 🟢 | N/A | 🟢 | 🔴 | legal review |
| T1.2.7 Legal review | external | — | — | — | — | 🔴 | R2 active |
| T1.2.8 Codex review + merge | (audit) | — | — | — | — | 🔴 | post-impl |

**T1.2 Verdict**: **Admin erasure source-ready (R2 legal block)**; **subscriber self-service `DELETE /audit/me` + right-to-info `GET /audit/me` GERÇEK PENDING** — endpoint'ler backend'de YOK; sprint-plan T1.2 ~17h estimate, gerçek residual ~10-12h (sadece subscriber self-service implementation + integration test) + R2 legal review (2-3h). **Önceki iddia "source-ready" KISMEN YANLIŞTI** — admin scope source-ready, subscriber scope pending.

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
| **T1.2** KVKK erasure (admin source-ready, subscriber self-service + right-to-info pending) | 17h | ~12-15h (subscriber endpoint impl + integration test + R2 legal) | -2-5h |
| **T1.3** Provider rollback | 13h | ~5h (acceptance gate) | -8h |
| **T1.4** Outage fallback (D43) | 15.5h | ~15h (gerçek pending) | 0h |
| **T1.5** Data classification | 12h | ~2h (acceptance test) | -10h |
| **T1.6** Abuse guards | 15h | ~15h (gerçek pending) | 0h |
| **Toplam T1** | **99.5h (~100h)** | **~52-55h** | **-44 / -47h** |

**M3 closure realistic estimate**: ~52-55h **+** acceptance gate testing **+** Codex review iter overhead = **~60-70h provisional sprint** (4-6 hafta yerine **2.5-3.5 hafta** mümkün eğer RAID I6 credential + R2 legal + T1.2 subscriber endpoint impl + T1.4/T1.6 gerçek pending tamamlanırsa).

> **Provisional iddia disclaimer (Codex `019e0c28` iter-2)**: Bu rakam canonical değil; T1.2 endpoint truth düzeltmesi sonrası iter-2 sonrası iter-3 audit ile sabitlenir. "credential + legal + acceptance gates open" şartıyla.

---

## Charter / Sprint-Plan / Must-Have / Feature-Matrix Re-Baseline Önerileri

### Charter (RB-faz-23-charter.md)

**23.2 sub-faz marker**:
- Şu an: `🟡 partial (Session 39 hardening 5/8 done; original acceptance 2/8 done)`
- Re-baseline: `🟡 partial (Session 39 hardening 5/8 done; backend source-ready 7/9 / live-deployed 7/9 / acceptance-complete 1/9 — D29-Authorized BLOCKED on RAID I6 + R2 KVKK legal + T1.2 subscriber endpoint gerçek pending)`
- 23.2 duration `4-6 hafta / ~100h aggressive` → `~52-55h residual / ~60-70h provisional sprint / 2.5-3.5 hafta (credential RAID I6 + R2 legal gate açılınca + T1.2 subscriber endpoint impl + T1.4 + T1.6 tamamlanırsa)`

### Sprint-Plan (sprint-plan.md)

**T1 task status sweep**:
- T1.1.1, T1.1.2, T1.1.3, T1.1.4 → 🔴 → 🟢 source-ready/live (V1 schema + PreferenceController + service + send pipeline LIVE)
- T1.1.5, T1.1.6, T1.1.7, T1.2.6, T1.5.3 → 🔴 → 🟡 partial (source-ready, acceptance gate)
- T1.2.0 admin erasure → 🟢 source-ready/live (R2 legal review wait)
- **T1.2.1, T1.2.2 subscriber self-service `DELETE/GET /audit/me` → 🔴 stays (gerçek pending — backend'de YOK; ~10h yeni impl)**
- T1.2.3 append-only verify (V8 trigger) → 🟢 done
- T1.3.1 → 🟢 source-ready/live; T1.3.2 → 🟡 partial
- T1.5.1, T1.5.2 → 🟢 source-ready/live (V1 field + DataClassification enum)
- T1.4 sub-tasks: 🔴 stays (gerçek pending; alertmanager-bridge backend code YOK)
- T1.6 sub-tasks: 🔴 stays (gerçek pending; RateLimitGuard/AbuseGuard backend'de YOK)
- "T1 ~100h" başlığı → "T1 ~52-55h residual / ~60-70h provisional sprint" + actuals tracking note

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
   - Sprint-plan T1 task status sweep + ~50-60h residual
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
