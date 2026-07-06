# M3 (23.2 Closure) Stale Audit + Residual Re-Baseline — 2026-05-09

> **Status**: ACTIVE (Codex `019e0c28` strategic finding absorb)
> **Trigger**: M2 D29 partial evidence collection sırasında platform-backend repo scan'i göstermiştir ki sprint-plan T1 ~100h pending estimate **stale/pessimistic**.
> **Codex Authority**: thread `019e0c28` "Backend stale finding gerçek ve stratejik. ... source exists ≠ acceptance done değil. Yeni sınıflandırma."

Bu audit Codex'in önerdiği **5-state matrix** (Source-ready / Live-deployed / Evidence-backed / Acceptance complete / Blocked) ile gerçek state'i tespit eder.

---

## Executive Summary

Sprint-plan T1 (23.2 closure) **gerçek residual ~28-32h band** (post PR #132 + #452 + #134 + #455 MERGE 2026-05-09 18:40Z; T1.2 subscriber self-service + T1.6 abuse guards source-ready/live-deployed). Backend implementation T1.1.1-T1.1.4 + **T1.2 admin + subscriber self-service** + T1.3 partial + T1.5 + **T1.6 abuse guards** **source-ready/live**; T1.4 (D43 outage fallback) gerçek pending.

| State | Count | Notes (Session 41 sonu 2026-05-09 23:45Z) |
|---|---:|---|
| 🟢 **Source-ready** | 12/12 | Tüm T1 sub-task'lar source-ready (T1.4 PR-1+2+3+4 LIVE) |
| 🟢 **Live-deployed** | 9/12 | T1.6 + T1.2 LIVE acceptance evidence kanıtlandı; T1.4 drill execution operator action |
| 🟢 **Evidence-backed** | **6/12** ⬆️ | T1.6.1 (rate limit 100×202+5×429+RATE_LIMITED audit+Prometheus counter), T1.2.1 (KVKK Art.11 DELETE 200 evidence_ref), T1.2.2 (KVKK Art.13 GET 200 paginated), **T1.1 (preference REST PUT/GET 200 + bypassForCritical)**, **T1.5 (data classification + severity=critical bypass; notify_abuse_bypassed_total counter increment)**, T1.6 critical bypass live evidence (severity=critical 202 + bypass counter 1.0) |
| 🟢 **Acceptance complete** | **6/12** ⬆️ | T1.6.1 + T1.6 critical bypass + T1.2.1 + T1.2.2 + T1.1 + T1.5 — D29-NOTIFY triple gate LIVE (Up + Functional + Authorized — Allow Mailpit + Deny 101 BLOCKED_BY_AUTHZ) |
| 🟡 **Blocked** | 1/12 | R2 KVKK legal review (admin erasure ETA 2026-05-25); T1.4 drill execution operator-bound separate; **R13 + R19 mitigated FULL acceptance**; **RAID I6 RESOLVED** (test persona pipeline LIVE Session 41) |

**M3 closure target**: 2026-06-08 → Session 41 sonu **3-7 gün** (2026-05-12 - 2026-05-16 band) — T1.4 drill execution + R2 KVKK legal review + remaining acceptance follow-up sonrası Charter 23.2 🟡 → 🟢. Acceptance evidence 6/12 LIVE Session 41 sonu (önceki 0/12).

**Session 41 acceptance summary** (2026-05-09 23:34-23:45Z):
- T1.6 abuse guards: 100×202 + 5×429 burst + RATE_LIMITED audit + Prometheus counter
- T1.6 critical bypass: severity=critical 202 + `notify_abuse_bypassed_total{reason="critical_severity"} 1.0`
- T1.2 KVKK Art.13 GET /audit/me: 200 paginated
- T1.2 KVKK Art.11 DELETE /audit/me: 200 `evidence_ref="self-service-kvkk-art-11"`
- T1.1 preference PUT/GET /preferences/me: 200 + bypassForCritical=true
- T1.5 data classification claim flow: dataClassification "transactional"/"system" RATE_LIMITED audit + critical bypass acceptance
- D29-NOTIFY triple gate: Up (pod 1/1) + Functional (3 endpoint family 200/202/429) + Authorized (Allow Mailpit + Deny 101 BLOCKED_BY_AUTHZ)

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
| T1.1.5 Critical bypass (severity-only; classification bypass removed) | `AbuseGuardService.java` + `IntentSubmissionService.java` (Codex P1 absorb): `data_classification=security` bypass KALDIRILDI — client-controlled DTO authority signal değil; sadece `severity=critical` bypass kaldı. Severity acceptance T1.6.6 `criticalSeverityBypasses` IT (PR #257 MERGED 2026-05-20 01:13:51Z `4897ce9e`) + T1.1.9 `disabledPreferenceWithCriticalBypassAllowsCriticalSeverity` (PR #258) ile kanıtlı. | source-ready | 🟢 | 🟢 | 🟢 (IT) | 🟢 | — (data_classification security bypass obsolete; client-controlled classification authority signal değil) |
| T1.1.6 Quiet hours bypass | `SubscriberPreferenceService.java:184-194` (quietHours window + severity=critical + bypassForCritical=true → `critical_bypass_quiet_hours`; non-critical inside window → deny `quiet_hours`) | substantial | 🟢 | 🟢 | 🟢 (IT) | 🟢 | — (PR #259 `quietHoursWindowDeniesNonCritical` + `quietHoursWindowBypassesForCritical` — fixed Clock injection + jsonb round-trip + Europe/Istanbul cross-day window; Codex thread `019e4469` PARTIAL→AGREE) |
| T1.1.7 Frequency limit bypass | `SubscriberPreferenceService.java:202-218` + `FrequencyLimitService` (in-memory rolling window; severity=critical + bypassForCritical=true → `critical_bypass_frequency`; over-limit non-critical → deny `frequency_limit`) | substantial | 🟢 | 🟢 | 🟢 (IT) | 🟢 | — (PR #259 `frequencyLimitDeniesNonCriticalWhenOverLimit` + `frequencyLimitBypassesForCriticalAndDoesNotConsumeWindow` — gerçek `FrequencyLimitService` bean, kritik bypass window'u tüketmiyor strong assertion; Codex thread `019e4469`) |
| T1.1.8 Unsubscribe link footer | `UnsubscribeFooterAppender.java` (per-target injection in `DeliveryDispatchService.dispatchSingleTarget` before `adapter.send`) + `UnsubscribeUrlBuilder.java` (HMAC-SHA256 signed token URL) + `UnsubscribeTokenService.java` + `UnsubscribeController.java` (verify) + `UnsubscribeRevokeService.java`; PR #260 MERGED 2026-05-20 — locale-aware footer (tr/en fallback to tr), channel filter (email + subscriber only), subject untouched, builder rejection soft fail. Codex thread `019e4476` REVISE→AGREE (4 constraint absorb: TemplateRenderer dokunma, DB template değiştirme YASAK, adapter layer append YASAK, per-target dispatch noktası). 13 unit test PASS lokal + CI Surefire. | substantial | 🟢 | 🟢 | 🟢 (unit + CI) | 🟢 | — |
| T1.1.9 Integration test | `IntentSubmissionServiceIntegrationTest.java` (existing) + `SubscriberPreferenceServiceIntegrationTest.java` (PR #258 4c5b1030 MERGED 2026-05-20 07:26:59Z): SubscriberPreferenceService exact + 3 fallback (channel-null, topic-null, both-null) JPA/Postgres IT + critical bypass exact-row IT complete (8 senaryo Testcontainers CI green). Codex thread `019e42d6` plan-time istişaresi + `019e443e` post-impl review iter-1 PARTIAL → iter-2 AGREE. | 🟢 | 🟢 | 🟢 (IT) | 🟢 | — |

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
| T1.3.2 Versioning service | `ProviderConfigHistoryRepository.java` + `ProviderConfigService.java` | 🟢 | 🟢 | — |
| T1.3.3 Atomic switch + cache | `ProviderConfigService.switchActive` (@Transactional SERIALIZABLE + TransactionSynchronization.afterCommit cache invalidate) | 🟢 | 🟢 | — |

**T1.3 Verdict (UPDATED 2026-05-10 — platform-backend PR #140 MERGED, R12 Mitigated FULL ACCEPTANCE)**: All T1.3 sub-tasks source-ready/live with Testcontainers integration test acceptance evidence (4 test methods CI GREEN: `atomic_switch` + `concurrent_switch_race` + `cache_invalidate` + `rollback_on_fail`). Atomic switch uses `@Transactional` SERIALIZABLE isolation + `TransactionSynchronization.afterCommit` cache invalidation pattern (prevents stale config served between commit and invalidate). Cross-AI peer review: Codex thread (PR #140 chain) iter-1 RED (initial design issues) → iter-2 AGREE post-impl. R12 (provider config rollback transaction race) 🟢 Mitigated per `risk-register.md`. M3 milestones canonical: `T1.3 23.2.C Provider config rollback merged` ✅.

### T1.4 — 23.2.D Outage Fallback Bypass (D43, must-have #10)

| Task | Source File | Source | Live | Blocker |
|---|---|:---:|:---:|---|
| T1.4.1 Vault path declaration | `bootstrap/vault-policies/common/eso-runtime.hcl` (PR #457 MERGED) `kv/data/platform/alertmanager-fallback` read | 🟢 | 🟡 | Vault operator init runbook + AppRole drift resolve |
| T1.4.2 ESO ExternalSecret test+prod | `kustomize/overlays/{test,prod}/eso/alertmanager/externalsecret-alertmanager-fallback.yaml` (PR #457 MERGED 5 keys) | 🟢 | 🟡 | ESO Vault AppRole "invalid role or secret ID" 2-day drift |
| T1.4.3 Alertmanager native fallback receiver | `helm-values/kube-prometheus-stack/values-test-d43-drill.yaml` (PR #457 MERGED self-contained config + secrets[] mount + with/else template) | 🟢 | 🔴 | helm upgrade drill window |
| T1.4.4 Mailpit netpol monitoring SMTP | `kustomize/overlays/test/lab-deps/mailpit-netpol-from-monitoring.yaml` (PR #457 MERGED) | 🟢 | 🟡 | cluster apply |
| T1.4.5 NotifyServiceDown stable labels | `kustomize/base/apps/notification-orchestrator/prometheusrule.yaml` (PR #457 iter-3 absorb bypass_orchestrator + outage_fallback) | 🟢 | 🟡 | cluster apply |
| T1.4.6 Drift alarm-receiver fallback hook (script-only) | `scripts/drift-detection/alarm_receiver.sh` Alertmanager direct delivery extension (PR #462 MERGED) — parallel mode default + cascade order GH→webhook→Alertmanager + stable labels (severity=critical/warning convention) + sha256sum/shasum portability | 🟢 | 🟡 | drill execution |
| T1.4.7 Break-glass dual-channel | `scripts/operations/break-glass-token.sh` extension (PR #463 MERGED) — orchestrator_reachable healthcheck (2xx/4xx/5xx ayrımı) + gh_failed flag + Alertmanager direct fallback + per-invocation dedupe (NOW+CTX+NS+SA+OPERATOR+REASON) + no-token-log HARD RULE + execution plane guard | 🟢 | 🟡 | drill execution |
| T1.4.8 Runbook + drill + R9 evidence | `docs/runbooks/RB-notification-outage-fallback.md` rewrite (T1.4 PR-4) — 10-criteria closure prosedürü + execution plane (in-cluster runner OR host port-forward) + Vault AppRole drift resolve prereq + drill window helm upgrade override + post-recovery audit best-effort | 🟢 | 🔴 | drill execute (operator action) |

**T1.4 Verdict (UPDATED 2026-05-09 19:30Z — PR #457 + #462 + #463 MERGED + PR #464 (PR-4 runbook) iter-3 review)**: **PR-1+PR-2+PR-3 source-ready/live-deployed; PR-4 source-ready candidate** (GitOps manifest + alarm-receiver fallback hook + break-glass dual-channel + runbook 10-criteria + NotifyServiceAbsent test-only overlay rule). **Live-ready** Vault AppRole drift resolve + drill execution sonrası R9 mitigated. Codex thread `019e0dea` iter chain: PR-1 4 round + PR-2 2 round + PR-3 2 round + PR-4 iter-1 PARTIAL → iter-2 absorb → iter-3 PARTIAL (3 absorb pending: NotifyServiceAbsent test-only overlay move, jq test() regex, drill side-effect explicit) — toplam ~22+ Codex iter T1.4 boyunca. Gerçek residual ~3-5h (drill execution + evidence collection — operator action gerekli; Vault drift dependency).

Implementation order (Codex iter-2 absorb):
1. PR-1 (MERGED 2026-05-09 18:56Z #457): GitOps + ESO + Alertmanager receiver + netpol — desired-state ✓
2. PR-2 (MERGED 2026-05-09 19:19Z #462): alarm-receiver fallback hook ✓
3. PR-3 (MERGED 2026-05-09 19:23Z #463): break-glass dual-channel ✓
4. PR-4 (#464 pending review): runbook rewrite + 10-criteria drill prosedürü + NotifyServiceAbsent test-only rule (Codex iter-1 P1 #2 absorb) (drill execution operator action — Vault AppRole drift resolve + helm drill upgrade + 10-criteria evidence collection)

### T1.5 — 23.2.E Data Classification

| Task | File | Source | Acceptance |
|---|---|:---:|:---:|
| T1.5.1 V_field migration | (in V1 schema) | 🟢 | 🟢 |
| T1.5.2 Enum + validator | `NotificationIntent.DataClassification` (transactional, security, commercial, system) | 🟢 | 🟢 |
| T1.5.3 Send pipeline behavior | `IntentSubmissionService` + `DeliveryEligibilityService` | 🟢 | 🔴 |
| T1.5.4 Integration test | TBD | 🟡 | 🔴 |

**T1.5 Verdict**: **Source-ready substantively**; acceptance integration test gate.

### T1.6 — 23.2.F Abuse Prevention Guards (must-have #10 partial)

| Task | Source File | Source | Live | Evidence | Acceptance | Blocker |
|---|---|:---:|:---:|:---:|:---:|---|
| T1.6.1 Rate limit per source | `AbuseGuardService.java` (240 satır; sliding window per (orgId, topicKey)) | 🟢 | 🟢 | 🟡 partial (init log + counter register; functional 429 smoke RAID I6 dep) | 🔴 | acceptance gate I6 |
| T1.6.2 Duplicate flood | NOT FOUND in code (Codex iter-1 P2 deferred follow-up) | 🔴 | 🔴 | 🔴 | 🔴 | impl follow-up |
| T1.6.3 Webhook fan-out cap | `AbuseGuardService.java` (HARD safety limit; severity=critical bile bypass etmez) | 🟢 | 🟢 | 🟡 partial (init log; functional smoke I6 dep) | 🔴 | acceptance gate I6 |
| T1.6.4 429 + audit | `AbuseGuardBlockedException` HTTP 429 + `AuditEventPublisher.publishStandaloneRequiresNew` (`Propagation.REQUIRES_NEW` audit row outer rollback'i atlatır — Codex iter-2 P1 KRITIK) | 🟢 | 🟢 | 🟡 partial (audit row evidence I6 functional smoke gerek) | 🔴 | acceptance gate I6 |
| T1.6.5 PrometheusRule alert | `NotifyAbuseStorm` alert in `kustomize/base/apps/notification-orchestrator/prometheusrule.yaml` (PR #867 MERGED 2026-05-20 00:36:22Z `1b7786a0`); dedicated runbook `RB-notify-abuse-guard.md`; Codex thread `019e42c1` REVISE×3 → AGREE iter-4. **Observability gap fix LIVE** (PR #878 MERGED 2026-05-20 07:28:49Z `6ab93b31` — PrometheusOperator selector mismatch was preventing ALL notification-orchestrator alerts from loading; release label `prometheus` → `kube-prometheus-stack`). Prometheus rule registry post-fix: NotifyAbuseStorm + 6 sibling alerts all LIVE (`wget actuator/rules` total 40 → 95). State=inactive (expected — counter zero in steady state). | 🟢 | 🟢 | 🟢 (alert load LIVE + cluster manifest synced) | 🟢 (alert registered + evaluated by Prometheus; firing functional smoke RAID I6 dep remains separate axis) | — |
| T1.6.6-7 Test + Codex review | `AbuseGuardServiceTest` 8/8 PASS unit + `IntentSubmissionAbuseGuardIntegrationTest` 5 senaryo (storm, critical bypass, fanout cap, hard limit, multi-tenant) PR #257 MERGED 2026-05-20 01:13:51Z `4897ce9e`; production code: critical bypass audit publish wiring (Decision.allowedWithAudit + IntentSubmissionService allowed-with-audit branch, Propagation.REQUIRES_NEW); Codex thread `019e42df` iter-1 REVISE → iter-2 AGREE; M3 closure katkısı | 🟢 | 🟢 | 🟢 (unit + IT) | 🟢 | — |

**T1.6 Verdict (UPDATED 2026-05-09 18:40Z — PR #134 + PR #455 MERGE + cluster apply CONFIRMED)**: **Backend abuse guards source-ready/live-deployed** (PR #134: AbuseGuardService 240 satır + AbuseGuardBlockedException + IntentSubmissionService Step 1.5 wiring + AuditEventPublisher.publishStandaloneRequiresNew + PiiRedactor whitelist extend + 8/8 unit tests PASS). Cluster pod imageID `sha256:eef18027f0d54b930e1c54c44215fe2c50e6aa752fe2dcbf93ea0eae2908d0b4` LIVE; `AbuseGuardService initialized: window=60s rateLimit=100/window webhookFanoutCap=10 (multi-pod soft enforcement)` confirmed. **Acceptance gate** functional 429 smoke (101st request expected) RAID I6 Keycloak credential blocker. T1.6 sprint-plan ~15h estimate; gerçek residual ~2-3h (functional smoke acceptance test + PrometheusRule alert + Service IT).

**Codex P1 absorb significant findings**:
- Critical bypass scope **daraltıldı**: sadece `severity=critical`; `data_classification=security` bypass kaldırıldı (DTO client-controlled, authority signal yok).
- Webhook fan-out cap **HARD safety limit** (severity=critical bile bypass etmez).
- Audit row transaction rollback **fix**: `Propagation.REQUIRES_NEW` ile 429 throw öncesi audit INSERT bağımsız transaction'da commit (outer rollback'i atlatır).
- Multi-pod soft enforcement **explicit doc**: in-process ConcurrentHashMap + AtomicLong; effective_limit = pod_count × per_pod_limit (PG/Redis follow-up out-of-scope MVP).

---

## Real Residual Estimate (Codex `019e0c28` Re-Baseline)

| Tier | Original Estimate (sprint-plan) | Re-Baselined Real Residual | Drift |
|---|---:|---:|---|
| **T1.1** Preference + bypass + opt-out | 27h | ~3h (acceptance test only) | -24h |
| **T1.2** KVKK erasure (admin + subscriber self-service source-ready/live; PR #132+#452 MERGE 14:00Z apply CONFIRMED) | 17h | ~2-4h (acceptance test + R2 legal review coordination) | -13 / -15h |
| **T1.3** Provider rollback | 13h | ~5h (acceptance gate) | -8h |
| **T1.4** Outage fallback (D43) | 15.5h | ~15h (gerçek pending) | 0h |
| **T1.5** Data classification | 12h | ~2h (acceptance test) | -10h |
| **T1.6** Abuse guards (PR #134 + #455 MERGE + cluster apply 2026-05-09 18:40Z) | 15h | ~2-3h (functional smoke + PrometheusRule alert + Service IT acceptance) | -12 / -13h |
| **Toplam T1 (post PR #134 + #455 MERGE 2026-05-09)** | **99.5h (~100h)** | **~28-32h** | **-67 / -71h** |

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
- T1.1.5, T1.1.6, T1.1.7, T1.2.6, T1.5.3 → 🔴 → 🟡 partial → **🟢 full acceptance (PR #259 MERGED 2026-05-20 — T1.1.6 + T1.1.7 4 IT senaryo Testcontainers PG; T1.1.5 row rewrite — `data_classification=security` bypass KALDIRILDI Codex P1 absorb, severity bypass T1.6.6 IT ile kapsanıyor)**
- T1.1.8 unsubscribe link footer → 🔴 → 🟡 → **🟢 full acceptance (PR #260 MERGED 2026-05-20 — `UnsubscribeFooterAppender` per-target injection in `DeliveryDispatchService.dispatchSingleTarget` before `adapter.send`; locale-aware tr/en footer; channel filter email+subscriber; 13 unit test PASS Codex thread `019e4476` REVISE→AGREE 4 constraint absorb)**
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

**2026-05-09 18:40Z (PR #134 + PR #455 MERGE + cluster apply CONFIRMED)** — T1.6 abuse guards backend MERGED + cluster apply LIVE. Pod imageID sha256:eef18027f0d54b930e1c54c44215fe2c50e6aa752fe2dcbf93ea0eae2908d0b4 (T1.6 image). Spring Boot startup `AbuseGuardService initialized: window=60s rateLimit=100/window webhookFanoutCap=10 (multi-pod soft enforcement)` confirmed. T1.6.1 + T1.6.3 + T1.6.4 🔴 → 🟢 source-ready/live-deployed; T1.6.6 unit tests 8/8 PASS 🟢. Cluster apply incident: ESO ClusterSecretStore Vault AppRole "invalid role or secret ID" (2 gündür sync error; not T1.6 backend code; PG password reset workaround applied with cached `change-me-local-only` value to unblock pod startup; ESO/Vault drift ayrı follow-up). T1 toplam residual ~43-46h → ~28-32h (-13/-14h; T1.6 ~15h → ~2-3h functional smoke + PrometheusRule + Service IT). M3 closure 1.5-2 hafta provisional (önceki 2-3 hafta).

**2026-05-09 18:50Z (Codex iter-3+post-cluster verify)** — Cross-AI peer review continues: Codex thread `019e0c28` post-merge verdict pending; PR #455 verdict AGREE / ready_to_merge=true (smoke plan: 100 default rate limit threshold → 101st request 429 expected; override `NOTIFY_ABUSE_RATE_LIMIT_MAX_PER_WINDOW=5` ile 6th); functional 429 smoke acceptance test RAID I6 Keycloak admin credential blocker'a kadar pending.

**2026-05-20 07:30Z (Major Observability Gap Discovery + Fix — Session [current])** — Following T1.6.5 NotifyAbuseStorm cluster apply, the operator-side rule reconcile check revealed a critical pre-existing bug: **the entire notification-orchestrator PrometheusRule had been silently unrendered into the operator's rulefiles ConfigMap since first deployment**. Root cause: `metadata.labels.release: prometheus` vs the kube-prometheus-stack Prometheus CR's `ruleSelector.matchLabels.release: kube-prometheus-stack` mismatch.

Live evidence (k3d-test 2026-05-20 04:18 UTC, pre-fix):
```
wget actuator/rules | grep -cE "Notify(AuthzDisabledRegression|AuthzBypassed|DlqSustained|ServiceDown|AbuseStorm|OrgAccessDeniedStorm|AuditRetentionStale)"
→ 0 (out of 40 alerts loaded from OTHER PrometheusRules)
```

Affected alerts (all critical/page or warning, all unwired):
- `NotifyAuthzDisabledRegression` (critical page — security regression)
- `NotifyAuthzBypassed` (critical page — authz bypass)
- `NotifyDlqSustained` (critical page — provider degradation)
- `NotifyServiceDown` (critical page — **T1.4 D43 outage fallback wire dependency**)
- `NotifyAbuseStorm` (warning — T1.6.5 new alert)
- `NotifyOrgAccessDeniedStorm` (critical page — strict cutover)
- `NotifyAuditRetentionStale` + companion (warning — retention monitoring)

Fix (PR #878 MERGED 2026-05-20 07:28:49Z `6ab93b31`): single-line label fix in `kustomize/base/apps/notification-orchestrator/prometheusrule.yaml` + 10-line rationale comment block. Cluster apply confirmed via `kubectl apply -f /tmp/notify-prometheus-rule-v2.yaml` on staging-sw → PrometheusRule label updated → PrometheusOperator reconciled → Prometheus rule registry post-fix: total 40 → **95 alerts** (+55), all 7 notification alerts ✅ active (state=inactive in steady state, expected).

**Significance**: this is operationally the largest single M3 closure contribution this session — NotifyServiceDown (critical/page) had been silent-green since notification-orchestrator first deployment, meaning a service outage would have surfaced only via alternative signals (HTTP probe gateway, ArgoCD app health, etc.), not via the dedicated alert. T1.4 D43 outage fallback drill design assumed this alert would fire and route to the Alertmanager direct-fallback receiver; that wiring chain only becomes functional now that the rule is loaded.

**Prod parallel verify follow-up**: kustomize/overlays/prod almost certainly carried the same `release: prometheus` label via the base manifest before the fix. Need a prod cluster `wget actuator/rules` probe to confirm scope and (if confirmed) re-apply the fix on prod. Out of scope for this M3 closure session — flagged for the next operator action window.
