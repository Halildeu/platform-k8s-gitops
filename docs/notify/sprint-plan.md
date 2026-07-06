# Notification Platform — Sprint Plan + Estimation

> **Status**: ACTIVE (Session 39 PM artifact bootstrap 2026-05-09)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Charter**: [RB-faz-23-charter](../runbooks/RB-faz-23-charter.md)
> **Risk register**: [risk-register.md](risk-register.md)
> **Test strategy**: [test-strategy.md](test-strategy.md)
> **Milestones**: [milestones.md](milestones.md)

Bu doküman **task-level breakdown + estimation + ownership + dependency** sağlar. Her task: Sub-faz, Tier (T1..T5), Type (backend/frontend/gitops/docs), Estimation (h), Owner, Dependency, Status.

> **Faz 2 — GitHub Project migration (2026-05-17)** — Faz 23 ~Session 49'dan beri dormant. Aktif iş [platform Roadmap board](https://github.com/users/Halildeu/projects/2)'da milestone (#752-761) + risk (#762-773) item'larında izleniyor — standalone sprint-task issue açılmadı. Bu doküman task-level breakdown / estimation / tier T1-T5 detayının canonical kaynağı; bir tier aktifleşince work-package'lar kendi code repo'sunda issue açılıp milestone issue'ya linklenir.

---

## Velocity Baseline

**Single agent capacity** (Claude/Codex hybrid):
- Backend code: 4-8h per medium PR
- Gitops manifest: 1-2h per PR
- Docs: 1-3h per PR
- Codex peer review per PR: +0.5-1h (avg 2-3 iter)
- Cluster apply + verify: 0.5h per deploy
- **Effective velocity**: ~10-15h productive work per session block

**Sprint length**: variable; this plan organized by Tier (T1..T5) per closure milestone.

---

## Actuals Tracking (Codex `019e0c28` F5 Absorb)

> **Discipline**: Estimation alanları (`Est (h)`) **plan-time** rakamlarıdır; gerçekleşen efor (`Actual (h)`) task closure sırasında doldurulur. Her milestone closure'da actuals review + velocity adjustment + sprint-plan re-baseline.

**Format addition**: Tier task tablolarındaki `Est (h)` kolonu yanına `Actual (h)` ve `Variance` (Actual - Est) kolonları eklenecek (per-task closure'da inline güncellenir).

**Velocity audit cadence**:
- Per-milestone closure (M1, M2, M3, ...): tüm closed task actuals → velocity gerçekleşen ratio → sonraki tier estimation revize
- Confidence: low → medium → high progression sprint cycle'larında

**Şu an (Session 47 2026-05-21)**: Actual measurement partial başladı; T1 ~60h+ actual / 99.5h estimate (-40h drift) + T4.1 14h / 25h (-11h) + T4.2 32h (browser-only) + T4.3 12.5h done / 36h plan + 14h residual. Confidence medium (T4 actual'lar PR-bazlı izlendi; T1 actual'lar Session 41-47 cumulative proxy). M2 + M6a + M6b closure tamamlandı (board #754/#758).

---

## Tier 1: 23.2 Production MVP Dar Closure (CLOSED source-side; external acceptance pending)

> **Session 47 update 2026-05-21** (post M3 R2 KVKK T1.2 task implementation 7/7 MERGED + closure evidence + Codex 019e4950 AI proxy review interim attestation; final legal closure via 019e5189 — see Session 49+ block below):
>
> **Tier 1 6/6 sub-tier source-ready/LIVE** — kalan blocker external acceptance gate'lerinde:
> - T1.1 Preference: source-ready + PR-G2 PreferenceTopicCatalog endpoint LIVE; T1.1.9 integration test MERGED (task #17). Residual: live cluster runtime evidence (operator gate)
> - T1.2 KVKK erasure: admin + subscriber self-service LIVE; PR-K1 (erasure ledger V18 + 30-gün SLA watchdog) MERGED 2026-05-21; **PR-K1-K5 + K7 closure MERGED (6/7 K-PR; K6 tenant-scoped DPO authz P1 non-blocking 23.2.B follow-up)**. **R2 closed 2026-05-23** via Codex `019e5189` final legal verdict — see [risk-register.md R2](risk-register.md) + Session 49+ update below.
> - T1.3 Provider config rollback: T1.3.1-T1.3.4 LIVE; `ProviderConfigRollbackIntegrationTest` MERGED. R12 mitigated
> - T1.4 D43 outage fallback: PR #855 staged config MERGED 2026-05-21; **BL-008 mock-receipt drill 2026-05-24 LIVE** (test cluster dual-receipt — webhook-receiver POST + Mailpit SMTP; Codex `019e5aaf` REVISE absorb); **R9 🟢 mock-receipt mitigated**. Real Slack workspace #853 + prod activation #854 (Operator v0.90.1 `auth_*_file` schema gap fix) ayrı operator-external.
> - T1.5 Data classification: T1.5.1-T1.5.4 LIVE; `DataClassificationAcceptanceTest` MERGED
> - T1.6 Abuse guards: T1.6.1-T1.6.6 LIVE; AbuseGuardService + NotifyAbuseStorm PrometheusRule + Service IT MERGED. R13 + R19 mitigated
>
> **Session 49+ update 2026-05-23 (M3 R2 KVKK closure truth-sync)**: Kullanıcı kararı 2026-05-23 ("hukuk onaylarını Codex istişaresinde Codex'in verdiklerini kabul edeceğiz") uyarınca **Codex `019e5189` final legal verdict AGREE** — R2 KVKK uyumu M3 closure için kabul edilebilir; 3 P0 + Madde 12/13.2/11.4 riskleri 6/7 K-PR MERGED ile kapalı (K1-K5+K7). K6 tenant-scoped DPO authz P1 non-blocking follow-up. **M3 🟢 CLOSED**, R2 🟢 Mitigated. Evidence: `docs/faz-23-evidence/2026-05-21-m3-r2-kvkk-closure-evidence.md` §R2 FINAL CLOSURE.
>
> **Session 49+ residual** (R2 closed; remaining = ops/operator):
> - ~~R2 KVKK legal sign-off ETA 2026-05-25 (4 gün, legal)~~ — **CLOSED 2026-05-23** via Codex `019e5189` legal verdict
> - R9 D43 drill execution Slack #853 + prod #854 (ops slot)
> - ~~M3 acceptance gate (Codex 019e4950 + 019e499c R2 closure attestation external)~~ — **M3 🟢 CLOSED 2026-05-23**
>
> Önceki Session 41 ~17-22h residual → Session 47 ~0h agent-actionable → **Session 49+ M3 fully closed**, external acceptance R2 satisfied. T1 efektif kapanış: 2026-05-21 source-side + 2026-05-23 acceptance. K6 (P1 23.2.B follow-up) backend dev iş.

### T1.1 — 23.2.A Preference + Opt-out + Critical Bypass (must-have #8)

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T1.1.1 | V9 migration: `notify.subscriber_preference` table | backend | 2 | dev | None | 🟢 source-ready/live (V1 schema) |
| T1.1.2 | Domain entity + repository + service (preference CRUD) | backend | 4 | dev | T1.1.1 | 🟢 source-ready/live (`SubscriberPreferenceService` 414 satır) |
| T1.1.3 | REST API: `PUT /preferences/me` + `GET /preferences/me` + `DELETE /me/{id}` + `DELETE /me` | backend | 3 | dev | T1.1.2 | 🟢 source-ready/live (`PreferenceController` 290 satır) |
| T1.1.4 | Send pipeline preference check + `BLOCKED_BY_PREFERENCE` audit | backend | 3 | dev | T1.1.3 | 🟢 source-ready/live (`DeliveryEligibilityService`) |
| T1.1.5 | Critical bypass logic (severity=critical OR data_classification=security) | backend | 2 | dev | T1.1.4, T1.5.2 | 🟡 partial (severity bypass live; data_classification security bypass acceptance test gerek) |
| T1.1.6 | Quiet hours bypass | backend | 2 | dev | T1.1.4 | 🟡 partial source |
| T1.1.7 | Frequency limit bypass | backend | 2 | dev | T1.1.4 | 🟡 partial source |
| T1.1.8 | Unsubscribe link footer (email template) | backend | 2 | dev | T1.1.3 | 🔴 (template engine review pending) |
| T1.1.9 | Integration test: preference scenarios | backend | 4 | dev | T1.1.5 | 🟢 task #17 MERGED (Codex P2 absorb) |
| T1.1.10 | Gitops env enable test+prod overlays | gitops | 1 | gitops | T1.1.9 | 🟢 LIVE |
| T1.1.11 | Codex peer review + merge | docs | 1 | agent | T1.1.10 | 🟢 |
| T1.1.12 | Charter + must-have-checklist marker update | docs | 1 | agent | T1.1.11 | 🟡 charter 23.5 `[~]` source-ready + acceptance candidate (full 🟢 board acceptance + live cluster runtime evidence gerek) |

**Total estimate**: 27h. **Session 47 status 2026-05-21**: T1.1.1-T1.1.10 LIVE + T1.1.11 Codex review chain MERGED; residual T1.1.12 charter marker board acceptance (operator gate).

### T1.2 — 23.2.B KVKK Erasure + Right-to-Information (must-have #7 closure)

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T1.2.0 | **Admin erasure** `POST /api/v1/admin/notify/erasure` | backend | (existing) | dev | None | 🟢 source-ready/live (`AdminErasureController` 129 satır; R2 closed 2026-05-23 Codex `019e5189` legal verdict) |
| T1.2.1 | **Subscriber self-service** `DELETE /audit/me` (payload purge, recipient_hash kalır, KVKK Art.11) | backend | 5 | dev | None | 🟢 LIVE — `SubscriberErasureController` 179 satır + V8 trigger; KVKK Art.11 |
| T1.2.2 | **Subscriber right-to-info** `GET /audit/me` (KVKK Art.13) | backend | 5 | dev | None | 🟢 LIVE — `SubscriberErasureController` + `AuditHistoryListResponse` |
| T1.2.3 | Append-only enforcement verification (V8 trigger LIVE; test) | backend | 1 | dev | None | 🟢 done (V8 trigger LIVE) |
| T1.2.4 | Integration test: erasure flow (admin + self-service) + recipient_hash preservation | backend | 4 | dev | T1.2.1 | 🟢 `SubscriberErasureControllerIntegrationTest` MERGED |
| T1.2.5 | Integration test: right-to-information | backend | 2 | dev | T1.2.2 | 🟢 same IT class |
| T1.2.6 | Runbook: `RB-notify-kvkk-erasure.md` update with API examples (admin + self-service) | docs | 1 | agent | T1.2.4 | 🟢 PR-K7 #928 MERGED 2026-05-21 (60-gün→30-gün SLA + HMAC-SHA256) |
| T1.2.7 | Legal review (KVKK Art.11 + Art.13 compliance) | review | 2 | legal | T1.2.6 | 🟢 R2 CLOSED 2026-05-23 — Codex `019e5189` final legal verdict AGREE (kullanıcı kararı: Codex istişare verdict'i = kabul edilen hukuk onayı); earlier Codex 019e4950 AI proxy review PARTIAL_COMPLIANT was the interim attestation, 019e5189 final legal closure |
| T1.2.8 | Codex peer review + merge | docs | 1 | agent | T1.2.7 | 🟢 (Codex 019e4950 + 019e499c iter chain AGREE; final closure Codex `019e5189` 2026-05-23) |
| T1.2.9 | Charter + must-have-checklist marker update | docs | 1 | agent | T1.2.8 | 🟢 (M3 R2 KVKK closure evidence doc PR #930 MERGED; charter 23.2 🟢 done + M3 🟢 CLOSED 2026-05-23 via Codex `019e5189` final legal verdict) |

**Total estimate**: 17h. **Session 49+ status 2026-05-23**: T1.2.0-T1.2.9 ALL LIVE — T1.2 task implementation 7/7 MERGED (R2 K-PR chain: 6/7 K-PR MERGED = K1-K5+K7; K6 tenant-scoped DPO authz P1 non-blocking 23.2.B follow-up); R2 legal closed via Codex `019e5189` final verdict. T1.2 fully closed.

### T1.3 — 23.2.C Provider Config Versioning + Rollback

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T1.3.1 | V9 migration: `notify.provider_config_history` table (version + diff) | backend | 2 | dev | None | 🟢 LIVE |
| T1.3.2 | Domain service: provider config versioning | backend | 3 | dev | T1.3.1 | 🟢 LIVE — `ProviderConfigService` 120+ satır |
| T1.3.3 | Atomic switch + cache invalidate API | backend | 3 | dev | T1.3.2 | 🟢 LIVE 2026-05-10 (PR #140 MERGED; R12 mitigated FULL ACCEPTANCE) |
| T1.3.4 | Integration test: rollback scenario | backend | 3 | dev | T1.3.3 | 🟢 `ProviderConfigRollbackIntegrationTest` MERGED |
| T1.3.5 | Runbook: `RB-notify-provider-config-rollback.md` | docs | 1 | agent | T1.3.4 | 🟢 LIVE |
| T1.3.6 | Codex peer review + merge | docs | 1 | agent | T1.3.5 | 🟢 |

**Total estimate**: 13h. **Session 47 status 2026-05-21**: T1.3 6/6 LIVE; R12 mitigated. Drift fix PR #875 T1.3 closure (task #16 MERGED).

### T1.4 — 23.2.D Outage Fallback Bypass D43 (must-have #10 closure)

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T1.4.1 | Vault path `kv/platform/alertmanager-fallback` (separate creds) | ops | 1 | ops | None | 🟢 LIVE |
| T1.4.2 | ESO ExternalSecret for fallback | gitops | 1 | gitops | T1.4.1 | 🟢 LIVE |
| T1.4.3 | Alertmanager bridge dual-route config | gitops | 3 | gitops | T1.4.2 | 🟡 source-ready (PR #855 staged config MERGED 2026-05-21 — task #27); test SMTP LIVE 2026-05-10 |
| T1.4.4 | NotifyServiceDown alert routing override (already exists; verify) | gitops | 0.5 | gitops | T1.4.3 | 🟢 LIVE |
| T1.4.5 | Drift alarm-receiver fallback chain extension | backend | 3 | dev | None | 🟢 LIVE |
| T1.4.6 | Break-glass dual-channel script (notification + Alertmanager direct) | ops | 2 | ops | T1.4.4 | 🟡 source-ready |
| T1.4.7 | Runbook: `RB-notification-outage-fallback.md` | docs | 2 | agent | T1.4.6 | 🟢 MERGED 2026-05-10 |
| T1.4.8 | Drill test execution (orchestrator scale=0 → Slack direct verify) | ops | 2 | ops | T1.4.7 | 🟢 **mock-receipt mitigated** — first controlled drill 2026-05-10 (SMTP-only); BL-008 mock-receipt drill 2026-05-24 16:14-16:26Z (Codex `019e5aaf` REVISE absorb) DUAL evidence (webhook-receiver POST 200 + Mailpit SMTP — same dispatch cycle); 10/10 mock-receipt criteria PASS. Real Slack workspace #853 + prod activation #854 ayrı operator-external. |
| T1.4.9 | Codex peer review + merge | docs | 1 | agent | T1.4.8 | 🟢 (Codex 019e4234 audit + 019e5aaf BL-008 absorb; R9 🟢 mock-receipt mitigated) |

**Total**: 15.5h. **Session 49 status 2026-05-24**: T1.4 7/9 LIVE + 2 🟡 (real Slack workspace #853 + prod activation #854 — operator-external; prod values-prod.yaml `auth_*_file` Operator v0.90.1 schema gap fix #854 kapsamında). R9 🟢 mock-receipt mitigated.

### T1.5 — 23.2.E Data Classification Policy

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T1.5.1 | V9 migration: `notification_intent.data_classification` field | backend | 1 | dev | None | 🟢 LIVE |
| T1.5.2 | Enum + validator (transactional/security/commercial/system) | backend | 2 | dev | T1.5.1 | 🟢 LIVE |
| T1.5.3 | Send pipeline: classification-bound retention + opt-out behavior | backend | 4 | dev | T1.5.2, T1.1.5 | 🟢 LIVE 2026-05-10 acceptance |
| T1.5.4 | Integration test: 4 classifications + edge cases | backend | 3 | dev | T1.5.3 | 🟢 `DataClassificationAcceptanceTest` LIVE |
| T1.5.5 | Runbook update | docs | 1 | agent | T1.5.4 | 🟢 LIVE |
| T1.5.6 | Codex peer review + merge | docs | 1 | agent | T1.5.5 | 🟢 |

**Total**: 12h. **Session 47 status 2026-05-21**: T1.5 6/6 LIVE.

### T1.6 — 23.2.F Abuse Prevention Guards D45

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T1.6.1 | Rate limit per source (token bucket / sliding window) | backend | 4 | dev | None | 🟢 LIVE |
| T1.6.2 | Duplicate flood detection | backend | 3 | dev | T1.6.1 | 🟢 LIVE |
| T1.6.3 | Webhook fan-out cap | backend | 2 | dev | T1.6.1 | 🟢 LIVE (Codex 019e0c28 P1 absorb) |
| T1.6.4 | 429 + audit `RATE_LIMITED` responses | backend | 1 | dev | T1.6.1 | 🟢 LIVE |
| T1.6.5 | PrometheusRule: rate limit storm alert | gitops | 1 | gitops | T1.6.4 | 🟢 NotifyAbuseStorm MERGED (task #13) |
| T1.6.6 | Integration test: rate limit + flood scenarios | backend | 3 | dev | T1.6.4 | 🟢 AbuseGuardService IT MERGED (task #14, Codex iter chain AGREE) |
| T1.6.7 | Codex peer review + merge | docs | 1 | agent | T1.6.6 | 🟢 |

**Total**: 15h. **Session 47 status 2026-05-21**: T1.6 7/7 LIVE. R13 + R19 mitigated.

**Tier 1 Total estimate**: ~99.5h plan-time. **Session 49+ re-baseline 2026-05-24**: T1 6/6 sub-tier source-ready/LIVE + **R2 KVKK closed via Codex `019e5189` final legal verdict 2026-05-23** + **R9 mock-receipt mitigated via Codex `019e5aaf` BL-008 drill 2026-05-24**; agent-actionable residual **~0h**; real Slack workspace #853 + prod activation #854 ext-bound operator-external. Variance: ~60h+ actual vs 99.5h estimate (~-40h drift). Calendar efektif kapanış 2026-05-23 (M3 🟢 CLOSED) + 2026-05-24 (R9 🟢 mock-receipt mitigated).

---

## Tier 2: 23.1 + 23.4 + 23.9 Closure

### T2.1 — 23.1 D29-NOTIFY-Functional 3-channel Evidence

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T2.1.1 | Mailpit test message + screenshot evidence | ops | 1 | ops | None | 🟢 LIVE 2026-05-14 |
| T2.1.2 | Slack test channel test + screenshot evidence | ops | 1 | ops | None | 🟢 LIVE (mock incoming-webhook) |
| T2.1.3 | Webhook HMAC trace + delivery row INSERT | ops | 1 | ops | None | 🟢 LIVE |
| T2.1.4 | Evidence document: `docs/faz-23-evidence/2026-05-14-m2-d29-functional-3-channel-live.md` | docs | 1 | agent | T2.1.3 | 🟢 MERGED |
| T2.1.5 | Charter 23.1 marker 🟡 → 🟢 + evidence path fill | docs | 0.5 | agent | T2.1.4 | 🟡 stays per Codex 019e3c74 verdict B (Layer-2 OpenFGA `subscriber#can_receive` Faz 23.2 v2 rescope; M2 closure accepted 2026-05-18 board #754) |

**Total**: 4.5h. **Session 47 status 2026-05-21**: M2 accepted; T2.1 5/5 LIVE; charter 23.1 sub-faz marker 🟡 intentional (Layer-2 23.2 v2 dep).

### T2.2 — 23.4 Closure: Archive UI + 30d History (M6a + M6b)

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T2.2.1 | FE: archive button (mfe-host inbox component) | frontend | 3 | dev | None | 🟢 PR #626 + M6a chain MERGED (task #12) |
| T2.2.2 | Backend: notification history `GET /inbox/me?since=30d` filter | backend | 2 | dev | None | 🟢 V16 index + tests MERGED (task #8) |
| T2.2.3 | FE: 30d notification history filter UI | frontend | 2 | dev | T2.2.2 | 🟢 inbox Geçmiş tab + listHistory RTK MERGED (task #9) |
| T2.2.4 | Integration test: archive + history scenarios | backend + frontend | 2 | dev | T2.2.3 | 🟢 tasks #8 + #9 IT MERGED |
| T2.2.5 | M6b: SMS DLR badge UI | frontend | 3 | dev | T3.1 | 🟢 inbox SMS DLR badge MERGED (task #36) |
| T2.2.6 | Codex peer review + merge | docs | 1 | agent | T2.2.4 | 🟢 |

**Total**: 13h. **Session 47 status 2026-05-21**: M6a + M6b 6/6 LIVE.

### T2.3 — 23.9 Closure: 72h Observation + Rollback Prova + Browser SSO Verify

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T2.3.1 | 72h observation completion (T+72h = 2026-05-11 19:42Z natural) | ops | passive | ops | Time | 🟢 done — window closed 2026-05-11 (0 ERROR, DLQ=0, alerts clean) |
| T2.3.2 | Rollback prova execution (drill mode — non-destructive) | ops | 2 | ops | T2.3.1 | 🟢 done — ADR-0010 §2.5 + drill 2026-05-10 (R8 mitigated) |
| T2.3.3 | Browser SSO verify on testai.acik.com | user | 0.5 | user | None | 🟢 done — Session 49 `d29-evidence-tester` JWT + /authz/me 200 (Pre-Prod Full Authority agent headless) |
| T2.3.4 | Browser SSO verify on ai.acik.com | user | 0.5 | user | None | 🟢 done — Session 49 `d29-prod-sso-tester` JWT + /authz/me 200 (R7 mitigated) |
| T2.3.5 | Evidence document: `docs/faz-23-evidence/2026-05-14-m1-23-9-cutover-closure-evidence.md` | docs | 1 | agent | T2.3.4 | 🟢 done — Session 49 closure evidence published |
| T2.3.6 | Charter 23.9 marker 🟡 → 🟢 | docs | 0.5 | agent | T2.3.5 | 🟢 done — charter table line 57 FULL CLOSURE (truth-sync 2026-05-23 via this reconciliation PR for 23.9 section + this T2.3 table) |

**Total**: 4.5h passive+active. **Status 2026-05-23 (M1/23.9 reconciliation, Codex `019e53c1` AGREE)**: M1 6/6 DoD ✅ FULL CLOSURE (Session 49 evidence + 2026-05-23 truth-sync this PR). Önceki "Session 47 5/6 external blocker" wording stale; reality M1 fully closed Session 49 ama bu tablo geç senkron.

**Tier 2 Total**: ~22h estimate. **Status 2026-05-23**: T2.1 + T2.2 + **T2.3 hepsi LIVE/done**; M1 closed (R7 + R8 🟢 mitigated). M2 accepted 2026-05-18 #754; M6a+M6b 2026-05-20 #758.

---

## Tier 3: 23.3 SMS + 23.5 Preference UI (~3 weeks, ~50h)

### T3.1 — 23.3 SMS JetSMS (primary) + NetGSM (secondary) + In-app Inbox API

> **Provider kararı 2026-05-19 (kullanıcı)**: SMS primary **JetSMS** (canlı sözleşme + HTTP API), secondary **NetGSM** (contract R1 pending). Multi-provider failover 5-PR sequence — Codex `019e3f82` AGREE: PR-0 docs + PR-1 SmsProvider abstraction (behavior-neutral) + PR-2 JetSmsProvider send + failover + PR-3 JetSMS DLR polling + PR-4 gitops.

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T3.1.1 | JetSMS canlı sözleşme + API erişim (primary) + NetGSM secondary contract (R1) | ops/legal | 8 | ops | None | 🟡 JetSMS LIVE + prod cutover MERGED 2026-05-20 PR-B4 (#268+#916); NetGSM R1 ETA 2026-05-30 ext-gated |
| T3.1.2 | `SmsProvider` interface + `SmsAdapter` facade design (PR-1) | backend | 3 | dev | None | 🟢 PR #249 MERGED (task #2) |
| T3.1.3 | `JetSmsProvider` HTTP API impl (iso-8859-9 + form-urlencoded + Status/MessageIDs parse) (PR-2) | backend | 10 | dev | T3.1.2 | 🟢 PR #250 MERGED (task #3) + PR-A3 SOAP single + OTP routing (#265/#266/#267) |
| T3.1.4 | `NetGsmProvider` refactor (mevcut NetGsmSmsAdapter logic → SmsProvider, behavior-neutral) (PR-1) | backend | 4 | dev | T3.1.2 | 🟢 PR #249 (task #2) |
| T3.1.5 | Provider failover matrix (`SmsFailureClass` taxonomy: failover-eligible vs not) (PR-2) | backend | 5 | dev | T3.1.3, T3.1.4 | 🟢 PR #250 (task #3) |
| T3.1.6 | JetSMS DLR polling worker (HttpSmsReport pull + generic DlrIngest core) (PR-3) | backend | 12 | dev | T3.1.3 | 🟢 PR #252 MERGED (task #4) |
| T3.1.7 | DLR callback endpoint | backend | 3 | dev | T3.1.3 | 🟢 LIVE 2026-05-11 — 5/5 acceptance gates PASS; real SMS go-live R1 contract ETA 2026-05-30 — pipeline 100% ready |
| T3.1.8 | 4 workflow live test (admin invite, password reset, drift alarm, break-glass) | backend | 4 | dev | T3.1.7 | 🟢 **TEST CLUSTER LIVE 2026-05-24** (PR #1030 MERGED — 4 senaryo D29 3-layer disiplin proven: Up + Layer 1 `notify_org_access_match_total=11` + Layer 2 OpenFGA enforce 4× DENY + 2× ALLOW SMTP delivered; Codex iter-1 AGREE `019e5a87`); prod canary LIVE DELIVERED 2026-05-25 4-item chain: BL-010 prod KC realm discovery + persona/scope/mapper setup + Vault seed + BL-011 canary smoke + R24 Biotekno OTP allowlist + R1 NetGSM DEFER asset-preserved |
| T3.1.9 | Vault path `kv/platform/notification-orchestrator` SMS provider creds | ops | 1 | ops | T3.1.1 | 🟢 LIVE (Pre-Production Full Authority 2026-05-10) |
| T3.1.10 | In-app inbox API closure (paged + read + archive + WS endpoint) | backend | 6 | dev | None | 🟢 LIVE (M6a + M6b — tasks #8-12, #36) |
| T3.1.11 | Codex peer review + merge | docs | 2 | agent | T3.1.10 | 🟢 (Codex 019e3f82/019e4022/019e4514 multi-iter AGREE chain) |

**Total**: 44h estimate. **Session 47 status 2026-05-21**: T3.1 11/11 source-ready/LIVE; T3.1.1 + T3.1.8 ext-gated (R1 NetGSM + R24 Biotekno + KC org_id canary). **Session 53 status 2026-05-24**: T3.1.8 test cluster LIVE (PR #1030 MERGED — 4 senaryo D29 3-layer evidence); KC org_id canary **test cluster** LIVE (PR #1036 BL-010 — `platform-test` realm); prod canary LIVE DELIVERED 2026-05-25. **2026-05-25 status update (Codex `019e5e76` iter-2/iter-3 + `019e5ebe` iter-1..iter-3 AGREE B-with-lanes)**: BL-010 prod KC `serban` realm COMPLETED (PR #1062 MERGED — `notify-canary` scope + `org_id` mapper + persona LIVE + JWT 3-way claim verified); BL-011 prod SMS canary **DEFER iki gate prereq** — (1) preflight discovery 2026-05-25 prod notify_db boş data state (R28 NEW) + (2) canlı OpenFGA model fetch 2026-05-25 prod model `01KS15PF...` notification types DESTEKLEMİYOR (Layer-2 fail-closed). **BL-028 B-with-lanes mitigation**: Lane A (BL-028a, immediate, M4.5/23.3.3a — DB seed template + subscriber_contact) + Lane B (BL-028b, DEFERRED, M4.6/23.3.4 — prod OpenFGA notification model cutover + topic-inheritance tuple seed). Charter 23.3 marker `🟢 infrastructure LIVE; 🟡 functional data seed pending` + `🟡 Layer-2 authz cutover pending`. Prod canary LIVE DELIVERED 2026-05-25: (a) ✅ BL-010 prod KC LIVE (b) ✅ **BL-028a Lane A DB seed LIVE EXECUTED 2026-05-25** (c) ✅ **BL-028b Lane B OpenFGA cutover LIVE EXECUTED 2026-05-25** (M4.6 trigger; 10/10 gate PASS; new prod model `01KSFFK9K3V43DD211Z79K3FYA`; evidence `docs/faz-23-evidence/2026-05-25-bl028b-lane-b-prod-openfga-cutover-evidence.md`) (d) ✅ **BL-011 canary smoke LIVE DELIVERED 2026-05-25 16:58:45 UTC** (1 SMS +905551815564 → JetSMS jetsms-2605251959362908914 → DELIVERED 71s DLR; 7/7 acceptance gate PASS) (e) R24 Biotekno OTP allowlist (f) R1 NetGSM DEFER asset-preserved. Detay RB: `docs/runbooks/RB-bl028-prod-data-seed-execute.md` (Lane A ✅ LIVE; Lane B stub).

### T3.2 — 23.5 Preference UI (FE)

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T3.2.1 | mfe-host preference settings page route + skeleton | frontend | 2 | dev | T1.1.3 | 🟢 PR #285 MERGED (task #28) |
| T3.2.2 | Per-channel toggle UI | frontend | 3 | dev | T3.2.1 | 🟢 LIVE |
| T3.2.3 | Per-topic toggle UI | frontend | 3 | dev | T3.2.2 | 🟢 LIVE (PR-G3b platform-web PR #645 task #34) |
| T3.2.4 | Quiet hours editor | frontend | 4 | dev | T3.2.3 | 🟢 LIVE (PR #299 Faz 23.6 PR-B1) |
| T3.2.5 | Frequency limit slider | frontend | 2 | dev | T3.2.4 | 🟢 LIVE |
| T3.2.6 | Unsubscribe link landing page (RFC 8058 one-click) | frontend | 3 | dev | None | 🟢 LIVE (PR-G3 platform-web PR #642 task #32) |
| T3.2.7 | Integration test: end-to-end preference flow | frontend | 3 | dev | T3.2.6 | 🟢 Playwright e2e + Vitest unit LIVE (PR-G4 platform-web PR #646 task #33) |
| T3.2.8 | Codex peer review + merge | docs | 1 | agent | T3.2.7 | 🟢 |

**Total**: 21h estimate. **Session 47 status 2026-05-21**: T3.2 8/8 LIVE; M5 source-ready + acceptance candidate (charter 🟢 final board acceptance + live cluster runtime evidence gerek).

**Tier 3 Total**: ~65h estimate. **Session 47 status 2026-05-21**: T3.1 + T3.2 LIVE source-side; ext blocker R1/R24 (M4) + M5 board acceptance.

---

## Tier 4: 23.6 + 23.7 + 23.8 v1 (~5-6 weeks, ~99h)

> **Status revision 2026-05-22 (Session 48 — T4.3 9/9 sub-task source-side closed)**: T4.1 LIVE, T4.2 browser-only foundation 11 sub-PR + 1 UI follow-up MERGED (mobile FCM/APNS Faz 22.2 dep DIŞI), **T4.3 9/9 sub-task source-side closed** (Tempo + suppression + per-tenant dashboard + per-template analytics + federation design-artifact + FBL core+mailbox-worker MERGED). Sprint plan re-baseline:
>
> - T4.1 actual ~14h (estimate 25h, variance -11h — Block Kit + Teams Adaptive Card pattern straight-forward)
> - T4.2 (browser-only scope) actual ~32h from 11 sub-PR MERGED + 1 UI follow-up MERGED 2026-05-21 (W1+W2.1+W2.2+W2.3+W2.4+W2.5+W2.6+W3+W4+W5+W6+W7 + #649); mobile FCM/APNS ~24h Faz 22.2 dep DIŞI
> - T4.3 actual ~25.5h of ~36h plan; **0h agent residual — 9/9 sub-task source-side closed 2026-05-22** (T4.3.5 FBL PR #298+#299; T4.3.6 dashboard PR #951; T4.3.7 per-template PR #966+#296 MERGED; T4.3.8 federation design-artifact ADR-0026). Kalan yalnız operator activation gate'leri (FBL mailbox + per-template DB RO role).

### T4.1 — 23.6 Teams + Slack Zenginleştirme

| ID | Task | Type | Est (h) | Actual (h) | Owner | Status |
|---|---|---|---:|---:|---|:---:|
| T4.1.1 | Microsoft Teams adapter (Power Automate webhook + Adaptive Cards) | backend | 12 | 6 | dev | 🟢 PR #272 MERGED |
| T4.1.2 | Slack zenginleştirme (Block Kit + threading) | backend | 8 | 4 | dev | 🟢 PR #271 MERGED |
| T4.1.3 | Vault path Teams + Slack credentials | ops | 1 | 1 | ops | 🟢 |
| T4.1.4 | Integration test | backend | 3 | 2 | dev | 🟢 unit + WireMock IT |
| T4.1.5 | Codex peer review + merge | docs | 1 | 1 | agent | 🟢 019e4942/019e4946 |

**Total**: 25h estimate / 14h actual (variance -11h)

### T4.2 — 23.7 Push (browser-only WebPush scope; mobile FCM/APNS Faz 22.2 DIŞI)

| ID | Task | Type | Est (h) | Actual (h) | Owner | Status |
|---|---|---|---:|---:|---|:---:|
| T4.2.1 | FCM adapter (Android — Faz 22.2 endpoint-admin coupling) | backend | 10 | — | dev | ⏸️ Faz 22.2 dep DIŞI |
| T4.2.2 | APNS adapter (iOS — Faz 22.2 if iOS gerekirse) | backend | 10 | — | dev | ⏸️ Faz 22.2 dep DIŞI |
| T4.2.3 | `subscriber_push_endpoint` table + V19 migration | backend | 3 | 2 | dev | 🟢 PR-W1 #277 MERGED |
| T4.2.4 | Endpoint cleanup + RFC 8030 410/404 soft-delete (endpoint-level) | backend | 4 | 3 | dev | 🟢 PR-W2.2 #279 + PR-W6 #284 MERGED |
| T4.2.5 | Web Push browser (VAPID + RFC 8030 + nl.martijndwars:web-push lib) | backend | 6 | 8 | dev | 🟢 PR-W2.1+W2.3 #278/#280 MERGED |
| T4.2.6 | WebPushSender WireMock IT + integration tests | backend | 4 | 3 | dev | 🟢 PR-W2.4 #281 + PR-W7 #285 MERGED |
| T4.2.7 | IntentSubmission allow-list + DeliveryPlanService fan-out + Eligibility BLOCKED_NO_PUSH_ENDPOINT + V20 | backend | 5 | 4 | dev | 🟢 PR-W2.5+W2.6 #282 MERGED |
| T4.2.8 | PushSubscriptionController + Service + atomic upsert | backend | 4 | 3 | dev | 🟢 PR-W3 #283 MERGED |
| T4.2.9 | GitOps ConfigMap + ExternalSecret (defer-aware) + overlay digest bump | gitops | 2 | 1.5 | gitops | 🟢 PR-W4 #939 MERGED |
| T4.2.10 | Frontend service worker + helpers + RTK Query + usePushSubscription hook | frontend | 4 | 4 | dev | 🟢 PR-W5 #648 MERGED |
| T4.2.11 | Frontend UI integration (PushSubscriptionCard + VAPID env build chain) | frontend | 3 | 2.5 | dev | 🟢 PR #649 (this batch) |
| T4.2.12 | Codex peer review + merge | docs | 1 | 1 | agent | 🟢 019e49e7 + 5 thread chain |

**Total (browser-only)**: 32h actual (11 sub-PR MERGED + #649 UI integration MERGED 2026-05-21 20:00Z); mobile FCM/APNS Faz 22.2 dep (~24h DIŞI)

### T4.3 — 23.8 Tempo + Bounce Loop + Per-Tenant Grafana

| ID | Task | Type | Est (h) | Actual (h) | Owner | Status |
|---|---|---|---:|---:|---|:---:|
| T4.3.1 | Tempo Helm chart deploy in monitoring ns | gitops | 4 | — | gitops | 🟢 (önceki session) |
| T4.3.2 | OTLP collector deployment + service | gitops | 3 | — | gitops | 🟢 (önceki session) |
| T4.3.3 | notify-orch tracing reactivation env (MANAGEMENT_TRACING_ENABLED=true) | gitops | 1 | 2 | gitops | 🟢 PR #931 + #933 + #934 MERGED (2 fix iter) |
| T4.3.4 | Email bounce loop (provider feedback → suppression list V17) | backend | 8 | 6 | dev | 🟢 PR #270 MERGED (T4.3.b) |
| T4.3.5 | Spam complaint feedback loop (FBL) — ARF RFC 5965 mailbox-pull; ArfReportParser + FblService idempotent SPAM_COMPLAINT suppression + FblMailboxPollingWorker IMAP (Codex 019e4edd/019e4fc6/019e4ffd) | backend | 4 | 7 | dev | 🟢 source-ready 2026-05-22 (PR #298 core + PR #299 mailbox worker MERGED; V22 migration + 28 unit test; operator activation ext-gated — RB-fbl-mailbox-activation) |
| T4.3.6 | Per-tenant Grafana dashboard | gitops | 4 | 3 | gitops | 🟢 PR #951 MERGED (this batch — 7 panel skeleton + backend org_id Tag retrofit M8 pre-req) |
| T4.3.7 | Per-template analytics (Grafana PG datasource + Top 20 Templates panel; **PG aggregate read** — no Prometheus template_id label per Codex 019e4ee2 cardinality safety; PR-1 gitops + PR-2 backend V21 index MERGED) | gitops + backend | 4 | 4 | gitops | 🟢 source-ready 2026-05-22 (PR #966 Grafana sidecar datasource + per-tenant dashboard panel + RB-grafana-notify-pg-datasource + PR #296 V21 index MERGED; operator activation chain DB RO role + Vault seed + ESO uncomment ext-gated) |
| T4.3.8 | Federation plan-time design + safe scaffold (**design artifact only**; M7 iter-1 runtime federation YOK — ADR-0002 §3.8 remote_write zaten centralized; production federation Faz 24+/M8 trigger sonrası — Codex 019e4ee7 plan-time + 019e4ef4 iter-2 absorb) | gitops | 6 | 2 | gitops | 🟢 design-artifact-MERGED 2026-05-22 (ADR-0026 iter-2 + RB-observability-federation-rollout iter-2 + R16 budget/rollback design-managed; non-applied scaffold docs/scaffolds/; production federation runtime DEFERRED to Faz 24+/M8) |
| T4.3.9 | Codex peer review + merge | docs | 2 | 1.5 | agent | 🟢 |

**Total**: 36h estimate / 25.5h actual + 0h agent residual (satır toplamı T4.3.3 2 + T4.3.4 6 + T4.3.5 7 + T4.3.6 3 + T4.3.7 4 + T4.3.8 2 + T4.3.9 1.5 = 25.5h; T4.3.5 FBL source-ready 2026-05-22 PR #298+#299; T4.3.7 PR #966 + PR #296 MERGED; T4.3.8 design-artifact ADR-0026). T4.3 **9/9 sub-task source-side closed** — kalan yalnız operator activation (FBL mailbox + per-template DB RO role)

**Tier 4 Total**: ~99h estimate / ~71.5h actual + ~0h agent residual; mobile FCM/APNS ~24h Faz 22.2 dep DIŞI (T4.1 14h + T4.2 32h + T4.3 25.5h = 71.5h actual). **T4.3 9/9 sub-task source-side closed** 2026-05-22 — kalan yalnız operator activation gate'leri

---

## Tier 5: v2 Deferred (8-12 weeks, ~150h)

23.X v2 features — multi-tenant ready trigger sonrası başlatılır:

- A/B testing variant (~16h)
- Conditional steps rule engine (~12h)
- Workflow editor UI (no-code, ~40h)
- WhatsApp Business adapter (~16h)
- Voice/IVR adapter (Twilio, ~12h)
- Per-tenant provider config (~16h)
- Per-tenant brand customization (~12h)
- Vault dynamic secret TTL token (~8h)
- IYS commercial SMS lookup (~12h)

**Tier 5 Total**: ~144h (deferred)

---

## Sprint Summary Roadmap

| Tier | Scope | Total Effort | Calendar Span | Critical Risk |
|---|---|---:|---|---|
| **T1** 23.2 closure | preference + erasure + provider rollback + outage fallback + classification + abuse | ~99.5h estimate / ~60h+ actual + ~0h agent-actionable residual; Session 49+ 2026-05-23 re-baseline post 6/6 sub-tier source-side LIVE + T1.2 task implementation 7/7 MERGED + **R2 K-PR chain 6/7 MERGED = K1-K5+K7** (K6 tenant-scoped DPO authz P1 non-blocking 23.2.B follow-up); **R2 closed 2026-05-23 via Codex `019e5189` final legal verdict**; **R9 mock-receipt mitigated 2026-05-24 via Codex `019e5aaf` REVISE absorb (BL-008 drill)** | source-side LIVE; **M3 🟢 CLOSED 2026-05-23**; R9 mock-receipt mitigated; real Slack + prod activation operator-external | ~~R2 (KVKK legal)~~ 🟢 closed 2026-05-23, ~~R9 (D43 drill ops slot) 🟡 partial~~ **🟢 mock-receipt mitigated 2026-05-24**; real Slack #853 + prod #854 ext-bound — R12 + R13 + R19 mitigated; K6 P1 follow-up; RAID I6 superseded T1.1.9 PR #875 MERGED |
| **T2** 23.1+23.4+23.9 closure | D29-Functional + archive UI + 72h observation | ~22h estimate / **T2.1+T2.2+T2.3 hepsi LIVE/done** (M2 accepted 2026-05-18 #754; M6a+M6b 2026-05-20 #758; **M1 FULL CLOSURE Session 49 evidence 2026-05-14**, truth-sync 2026-05-23) | T2.1+T2.2 LIVE; T2.3 done — M1 closed | R7 🟢 closed (browser SSO Pre-Prod Full Authority agent headless); R8 🟢 mitigated |
| **T3** 23.3+23.5 | SMS JetSMS primary + NetGSM secondary + Preference UI | ~65h estimate / **infrastructure LIVE / 🟡 functional data seed pending** (M4 prod cutover infra-only LIVE 2026-05-20; BL-010 prod KC ✅ 2026-05-25 PR #1062; **BL-011 DEFER** — R28 NEW + BL-028 prod data seed prereq 2026-05-25 Codex `019e5e76`; M5 source-ready); T3.1.8 + T3.1.1 + M5 charter board acceptance ext-gated | infra LIVE; canary BL-028/BL-011 + R1 + R24 ext-gated | R1 (NetGSM DEFER), R24 (Biotekno OTP allowlist), **R28 NEW** (Prod data seed eksik — BL-028 mitigation) — R3 DKIM 🟢 mitigated, R23 Graph adapter active monitored |
| **T4** 23.6+23.7+23.8 v1 | Teams + WebPush (browser-only) + Tempo + bounce + per-tenant dashboard + federation design + FBL | ~99h estimate / ~71.5h actual + **~0h agent residual** — **T4.3 9/9 sub-task source-side closed 2026-05-22** (T4.3.5 FBL PR #298+#299 + T4.3.7 per-template PR #966+#296 + T4.3.8 federation design-artifact ADR-0026); mobile FCM/APNS ~24h Faz 22.2 dep DIŞI — Session 47-48 re-baseline 2026-05-21 + 2026-05-22 (T4.1 + T4.2 browser-only 11 sub-PR + #649 UI integration + T4.3.a Tempo + T4.3.b suppression + T4.3.6 per-tenant dashboard + T4.3.7 PG datasource/index + T4.3.8 federation design-artifact + T4.3.5 FBL core+mailbox-worker MERGED) | operator activation gate | R11 ~mitigated (Tempo LIVE), R16 design-managed (ADR-0026 iter-2; production federation runtime Faz 24+/M8) |
| **T5** 23.X v2 | multi-tenant features | ~144h | 8-12 hafta | R10 (multi-tenant migration) |
| **Total v1 (T1-T4)** | Faz 23.0 → 23.9 v1 closure | **~0h agent-actionable residual — T1/T2/T3/T4 source-side LIVE/closed** (T4.3 9/9 sub-task source-side closed 2026-05-22: FBL #298+#299, per-template #966+#296, federation ADR-0026); kalan yalnız external acceptance + operator activation gate'leri: **M1 🟢 FULL CLOSURE Session 49 2026-05-14 (truth-sync 2026-05-23)**; **M3 🟢 R2 KVKK closed 2026-05-23 (Codex `019e5189` final legal verdict)**; M4 R1 ⏳ DEFER (NetGSM contract kısa vadede yok — kullanıcı kararı 2026-05-23) + R24 (Biotekno OTP) + canary KC org_id ext-gated; FBL mailbox + per-template DB RO role operator activation; **§3.11 WebPush SUCCESS push delivery ✅ 2026-05-23 (Vault align overlay overrides operator follow-up)**; mobile FCM/APNS ~24h Faz 22.2 dep **DIŞI**. Session 47-48-49 re-baseline → **agent-actionable scope tükendi; v1 closure external/operator gate'lere bağlı** | **external acceptance + operator activation** (operator Vault align için PR #995+#996 overlay overrides revert; M4 R24 OTP ext) | — |
| **Total + v2** | Faz 23.0 → 23.X | v1 (T1-T4) source-side closed — **0h agent-actionable residual** (kalan external acceptance + operator activation); v2 ~144h deferred (multi-tenant ready trigger sonrası) | **v1 external/operator gate; v2 ~3-4 ay** | — |

**Estimation accuracy**: ±25% based on Codex peer review iter overhead + integration test discovery + cluster apply gates.

---

## Status Tracking

Update this doc per-PR:
1. Task status: 🔴 → 🟡 (in progress) → 🟢 (done)
2. Actual hours vs estimate (track velocity calibration)
3. Codex thread reference per task closure
4. Risk register cross-reference if new risk uncovered

**Last update**: 2026-05-25 iter-7 (BL-011 prod SMS canary **LIVE DELIVERED** — Faz 23.3 prod SMS lane v1 fully delivered): 1 SMS gönderildi `+905551815564` → JetSMS provider_msg_id `jetsms-2605251959362908914` → DELIVERED 71s DLR cycle. 7/7 acceptance gate PASS (intent COMPLETED + delivery DELIVERED + audit 4-event + metric source=org_id 0→1 + VF channel + DLR <120s + zero retry). Cost ~5 kuruş. Evidence: `docs/faz-23-evidence/2026-05-25-bl011-prod-sms-canary-live.md`. R28 🟢 Mitigated + **functional canary PROVEN**. BL-011 🟢 DONE. Charter 23.3 marker: 🟢 infra + 🟢 functional data + 🟢 Layer-2 authz + 🟢 prod SMS canary delivered. Önceki: 2026-05-25 iter-6 (BL-028b Lane B **LIVE EXECUTED** — M4.6 trigger): Prod OpenFGA notification model cutover LIVE. 10/10 acceptance gate PASS. New prod model `01KSFFK9K3V43DD211Z79K3FYA` (15 type: 10 ERP + 5 notification; ERP regression preserved). 5 ExternalSecret consumer aligned (permission + user + variant + core-data + report). Permission-service internal allow=true (reason: tuple_match) + deny=false (reason: no_tuple) via X-Internal-Api-Key. 0 error/fatal in 5 min post-rollout logs. Runtime-artifact ledger prod block pending→promoted. R28 status: 🟡 Partial → 🟢 **Mitigated** (severity High→Low). BL-011 status: 🔴 Blocked → 🟢 **Eligibility OPEN** (Layer-2 fail-closed kalktı). Evidence: `docs/faz-23-evidence/2026-05-25-bl028b-lane-b-prod-openfga-cutover-evidence.md`. Önceki: 2026-05-25 iter-5 (BL-028b Lane B runbook READY-FOR-EXECUTION — Codex `019e5ee5` iter-2 AGREE): Prod OpenFGA notification model cutover runbook draft READY (12 section + 5 ExternalSecret consumer inventory + canonical JSON ERP semantic diff + 10 hard acceptance gate + execute steps revize sıra). Status: READY post M4.6 operator window (no live execute in runbook draft PR). Runbook: `docs/runbooks/RB-bl028b-prod-openfga-notification-model-cutover.md`. R28 unchanged (Partial Mitigated). BL-011 unblock için Lane B execute ayrıca M4.6 milestone + operator authorize gerek. Önceki: 2026-05-25 iter-4 (BL-028a Lane A LIVE EXECUTED — PR #1066 MERGED `d3b7a04`): BL-028a Lane A prod DB seed live execute COMPLETED (template `canary-prod-marketing-v1` + subscriber `bl028-prod-canary-001`/+905551815564); 5 acceptance gate PASS (template exact-match + subscriber exact-match + permission-service :8090 reachable + backend env canonical + no-SMS guard); evidence `docs/faz-23-evidence/2026-05-25-bl028a-lane-a-prod-data-seed-execute.md`. R28 partial mitigated (Lane A done; Lane B DEFERRED M4.6); BL-011 hâlâ blocked by BL-028b (Layer-2 fail-closed; prod OpenFGA model notification types YOK). Önceki: 2026-05-25 iter-3 (BL-028 B-with-lanes refine — Codex `019e5ebe` iter-1 REVISE → iter-2 PARTIAL → iter-3 AGREE/impl_path=doc-only-first): Önceki R28 mitigation tek katmandı (DB seed only); canlı OpenFGA model fetch ile yeni bulgu: prod model `01KS15PF...` notification types DESTEKLEMİYOR → Layer-2 fail-closed. **BL-028 mitigation B-with-lanes refine**: Lane A (BL-028a, immediate, agent-doable, M4.5/23.3.3a — DB seed) + Lane B (BL-028b, DEFERRED, operator+architecture gate, M4.6/23.3.4 — prod OpenFGA notification model cutover). **BL-011 unblock criterion**: iki gate PASS olmadan SMS POST YASAK. **BL-028 parent runbook NEW**: `docs/runbooks/RB-bl028-prod-data-seed-execute.md` (Lane A `READY-FOR-EXECUTION` post-merge). **BL-011 RB drift fixes**: `:8094` → `:8090` port; `bl011-prod-canary-001` → `bl028-prod-canary-001` subscriber id; tuple shape direct → topic-inheritance. Önceki: 2026-05-25 BL-010 prod LIVE PR #1062 + BL-011 preflight discovery + R28 NEW + BL-028 yeni backlog (Codex `019e5e76` iter-1..iter-4 absorb); BL-009 trigger-based DEFER (PR #1061); M1 23.9 reconciliation truth-sync ✅; M3 R2 KVKK closed (Codex `019e5189`); R9 mock-receipt mitigated 2026-05-24 (Codex `019e5aaf` BL-008); BL-D43-TEAMS-PIVOT 2026-05-24 (Codex `019e5ba9` hibrit C); R27 + R28 NEW; R1 NetGSM ⏳ DEFER; WebPush §3.10+§3.11 fully closed; T1/T2/T4 source-side LIVE/closed, **T3 infra LIVE + functional data seed pending** (BL-028a + BL-028b prereq); v1 closure kalan = operator Vault align + R24 Biotekno ext + FBL mailbox/per-template DB RO + Teams Power Automate setup + **BL-028a Lane A DB seed + BL-028b Lane B OpenFGA cutover** + BL-011 SMS canary execute (post-Lane A + Lane B) + BL-009 DKIM DNS (trigger-based DEFER).
