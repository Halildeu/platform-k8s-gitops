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

**Şu an**: Faz 23.0..23.9 done iddiası ~270h baseline; **actual measurement başlamadı** (Codex iter-2 verdict "historical investment proxy, low confidence"). M1+M2 closure ile actual tracking başlar; M3 closure'da T1 99.5h estimate vs gerçekleşen ratio belirlenir.

---

## Tier 1: 23.2 Production MVP Dar Closure (CLOSED source-side; external acceptance pending)

> **Session 47 update 2026-05-21** (post M3 R2 KVKK 7/7 implementation MERGED + closure evidence + Codex 019e4950 AI proxy review):
>
> **Tier 1 6/6 sub-tier source-ready/LIVE** — kalan blocker external acceptance gate'lerinde:
> - T1.1 Preference: source-ready + PR-G2 PreferenceTopicCatalog endpoint LIVE; T1.1.9 integration test MERGED (task #17). Residual: live cluster runtime evidence (operator gate)
> - T1.2 KVKK erasure: admin + subscriber self-service LIVE; PR-K1 (erasure ledger V18 + 30-gün SLA watchdog) MERGED 2026-05-21; PR-K4/K5/K6/K7 closure MERGED. External blocker: R2 legal sign-off 2026-05-25 SLA
> - T1.3 Provider config rollback: T1.3.1-T1.3.4 LIVE; `ProviderConfigRollbackIntegrationTest` MERGED. R12 mitigated
> - T1.4 D43 outage fallback: PR #855 staged config MERGED 2026-05-21 (agent-actionable bölüm); drill execution + Slack #853 + prod #854 ops-gated (R9 🟡 partial)
> - T1.5 Data classification: T1.5.1-T1.5.4 LIVE; `DataClassificationAcceptanceTest` MERGED
> - T1.6 Abuse guards: T1.6.1-T1.6.6 LIVE; AbuseGuardService + NotifyAbuseStorm PrometheusRule + Service IT MERGED. R13 + R19 mitigated
>
> **Session 47 residual** (agent-actionable ~0h kaldı; external acceptance only):
> - R2 KVKK legal sign-off ETA 2026-05-25 (4 gün, legal)
> - R9 D43 drill execution Slack #853 + prod #854 (ops)
> - M3 acceptance gate (Codex 019e4950 + 019e499c R2 closure attestation external)
>
> Önceki Session 41 ~17-22h residual → **Session 47 ~0h agent-actionable** (external acceptance only). T1 efektif kapanış: 2026-05-21 (60h+ actual vs 99.5h estimate — variance -39h).

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
| T1.2.0 | **Admin erasure** `POST /api/v1/admin/notify/erasure` | backend | (existing) | dev | None | 🟢 source-ready/live (`AdminErasureController` 129 satır; R2 legal review wait) |
| T1.2.1 | **Subscriber self-service** `DELETE /audit/me` (payload purge, recipient_hash kalır, KVKK Art.11) | backend | 5 | dev | None | 🟢 LIVE — `SubscriberErasureController` 179 satır + V8 trigger; KVKK Art.11 |
| T1.2.2 | **Subscriber right-to-info** `GET /audit/me` (KVKK Art.13) | backend | 5 | dev | None | 🟢 LIVE — `SubscriberErasureController` + `AuditHistoryListResponse` |
| T1.2.3 | Append-only enforcement verification (V8 trigger LIVE; test) | backend | 1 | dev | None | 🟢 done (V8 trigger LIVE) |
| T1.2.4 | Integration test: erasure flow (admin + self-service) + recipient_hash preservation | backend | 4 | dev | T1.2.1 | 🟢 `SubscriberErasureControllerIntegrationTest` MERGED |
| T1.2.5 | Integration test: right-to-information | backend | 2 | dev | T1.2.2 | 🟢 same IT class |
| T1.2.6 | Runbook: `RB-notify-kvkk-erasure.md` update with API examples (admin + self-service) | docs | 1 | agent | T1.2.4 | 🟢 PR-K7 #928 MERGED 2026-05-21 (60-gün→30-gün SLA + HMAC-SHA256) |
| T1.2.7 | Legal review (KVKK Art.11 + Art.13 compliance) | review | 2 | legal | T1.2.6 | 🟡 R2 active, ETA 2026-05-25 (DPO/legal external); Codex 019e4950 AI proxy review PARTIAL_COMPLIANT verdict |
| T1.2.8 | Codex peer review + merge | docs | 1 | agent | T1.2.7 | 🟢 (Codex 019e4950 + 019e499c iter chain AGREE) |
| T1.2.9 | Charter + must-have-checklist marker update | docs | 1 | agent | T1.2.8 | 🟡 partial (M3 R2 KVKK closure evidence doc PR #930 MERGED; full 🟢 marker R2 legal sign-off sonrası) |

**Total estimate**: 17h. **Session 47 status 2026-05-21**: T1.2.0-T1.2.6 + T1.2.8 LIVE (KVKK 7/7 implementation MERGED); T1.2.7 external blocker R2 legal 2026-05-25; T1.2.9 charter marker R2 sign-off sonrası. Agent-actionable residual ~0h.

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
| T1.4.8 | Drill test execution (orchestrator scale=0 → Slack direct verify) | ops | 2 | ops | T1.4.7 | 🟡 partial — test SMTP drill LIVE 2026-05-10; Slack #853 sentinel-only NXDOMAIN; prod activation #854 owner-gated |
| T1.4.9 | Codex peer review + merge | docs | 1 | agent | T1.4.8 | 🟢 (Codex 019e4234 audit; R9 🟡 partial) |

**Total**: 15.5h. **Session 47 status 2026-05-21**: T1.4 6/9 LIVE + 3 🟡 partial (Slack real webhook + prod activation operator-gated). R9 🟡 partial. Issues #853 + #854 ops slot.

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

**Tier 1 Total estimate**: ~99.5h plan-time. **Session 47 re-baseline 2026-05-21**: T1 6/6 sub-tier source-ready/LIVE; agent-actionable residual **~0h**; external blocker R2 KVKK legal 2026-05-25 (4 gün) + R9 D43 drill ops slot. Variance: ~60h+ actual vs 99.5h estimate (~-40h drift). Calendar efektif kapanış 2026-05-21 (acceptance R2 sonrası).

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
| T2.3.1 | 72h observation completion (T+72h = 2026-05-11 19:42Z natural) | ops | passive | ops | Time | 🟡 passive expired (operator evidence doc pending) |
| T2.3.2 | Rollback prova execution (drill mode — non-destructive) | ops | 2 | ops | T2.3.1 | 🔴 operator slot |
| T2.3.3 | Browser SSO verify on testai.acik.com | user | 0.5 | user | None | 🔴 user slot |
| T2.3.4 | Browser SSO verify on ai.acik.com | user | 0.5 | user | None | 🔴 user slot |
| T2.3.5 | Evidence document: `docs/faz-23-evidence/2026-05-11-23-9-cutover-72h.md` | docs | 1 | agent | T2.3.4 | 🔴 (T2.3.3+T2.3.4 dep) |
| T2.3.6 | Charter 23.9 marker 🟡 → 🟢 | docs | 0.5 | agent | T2.3.5 | 🔴 (T2.3.5 dep) |

**Total**: 4.5h (T2.3.1 passive). **Session 47 status 2026-05-21**: M1 0/5 DoD external (operator + user gates); critical path blocker for v1 charter 23.9 closure. R7 active.

**Tier 2 Total**: ~22h estimate. **Session 47 status 2026-05-21**: T2.1 + T2.2 LIVE; T2.3 5/6 external blocker (operator + user slot — R7 active).

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
| T3.1.8 | 4 workflow live test (admin invite, password reset, drift alarm, break-glass) | backend | 4 | dev | T3.1.7 | 🟡 ext-gated (canary smoke KC org_id claim setup + R1 + R24 Biotekno OTP allowlist) |
| T3.1.9 | Vault path `kv/platform/notification-orchestrator` SMS provider creds | ops | 1 | ops | T3.1.1 | 🟢 LIVE (Pre-Production Full Authority 2026-05-10) |
| T3.1.10 | In-app inbox API closure (paged + read + archive + WS endpoint) | backend | 6 | dev | None | 🟢 LIVE (M6a + M6b — tasks #8-12, #36) |
| T3.1.11 | Codex peer review + merge | docs | 2 | agent | T3.1.10 | 🟢 (Codex 019e3f82/019e4022/019e4514 multi-iter AGREE chain) |

**Total**: 44h estimate. **Session 47 status 2026-05-21**: T3.1 11/11 source-ready/LIVE; T3.1.1 + T3.1.8 ext-gated (R1 NetGSM + R24 Biotekno + KC org_id canary).

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

> **Status revision 2026-05-21 (Session 47 — post WebPush 11 sub-PR + T4.1 MERGED + T4.3.a Tempo LIVE + T4.3.b suppression LIVE + T4.3.6 per-tenant dashboard MERGED)**: T4.1 LIVE, T4.2 browser-only foundation 11 sub-PR MERGED + 1 UI integration follow-up CI pending (mobile FCM/APNS Faz 22.2 dep DIŞI), T4.3 3/9 sub-task LIVE (Tempo + suppression + per-tenant dashboard MERGED; FBL + per-template analytics + federation residual). Sprint plan re-baseline:
>
> - T4.1 actual ~14h (estimate 25h, variance -11h — Block Kit + Teams Adaptive Card pattern straight-forward)
> - T4.2 (browser-only scope) actual ~32h from 11 sub-PR MERGED + 1 UI follow-up CI pending (W1+W2.1+W2.2+W2.3+W2.4+W2.5+W2.6+W3+W4+W5+W6+W7 + #649); mobile FCM/APNS ~24h Faz 22.2 dep DIŞI
> - T4.3 actual ~12.5h done of ~36h plan; ~14h kalır (T4.3.5 FBL + T4.3.7 per-template + T4.3.8 federation)

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

**Total (browser-only)**: 32h actual (11 sub-PR MERGED + #649 UI integration CI pending); mobile FCM/APNS Faz 22.2 dep (~24h DIŞI)

### T4.3 — 23.8 Tempo + Bounce Loop + Per-Tenant Grafana

| ID | Task | Type | Est (h) | Actual (h) | Owner | Status |
|---|---|---|---:|---:|---|:---:|
| T4.3.1 | Tempo Helm chart deploy in monitoring ns | gitops | 4 | — | gitops | 🟢 (önceki session) |
| T4.3.2 | OTLP collector deployment + service | gitops | 3 | — | gitops | 🟢 (önceki session) |
| T4.3.3 | notify-orch tracing reactivation env (MANAGEMENT_TRACING_ENABLED=true) | gitops | 1 | 2 | gitops | 🟢 PR #931 + #933 + #934 MERGED (2 fix iter) |
| T4.3.4 | Email bounce loop (provider feedback → suppression list V17) | backend | 8 | 6 | dev | 🟢 PR #270 MERGED (T4.3.b) |
| T4.3.5 | Spam complaint feedback (FBL endpoint) | backend | 4 | — | dev | 🔴 sub-task pending |
| T4.3.6 | Per-tenant Grafana dashboard | gitops | 4 | 3 | gitops | 🟢 PR #951 MERGED (this batch — 7 panel skeleton + backend org_id Tag retrofit M8 pre-req) |
| T4.3.7 | Per-template analytics | backend | 4 | — | dev | 🔴 sub-task pending |
| T4.3.8 | Cross-cluster Prometheus federation (R16 mitigation) | gitops | 6 | — | gitops | 🔴 (R16 active monitored) |
| T4.3.9 | Codex peer review + merge | docs | 2 | 1.5 | agent | 🟢 |

**Total**: 36h estimate / 12.5h actual + 14h residual (T4.3.5 FBL + T4.3.7 per-template + T4.3.8 federation)

**Tier 4 Total**: ~99h estimate / ~58.5h actual + ~14h residual; mobile FCM/APNS ~24h Faz 22.2 dep DIŞI (T4.1 14h + T4.2 32h + T4.3 12.5h = 58.5h actual)

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
| **T1** 23.2 closure | preference + erasure + provider rollback + outage fallback + classification + abuse | ~17-22h residual (~100h original; Session 41 re-baseline post T1.6 LIVE + T1.4 4-PR source-ready -77/-82h) | 1-1.5 hafta provisional | R2 (KVKK legal), R9 (D43 drill operator-bound), RAID I6 (Keycloak credential) — R13 + R19 mitigated (T1.6 abuse guards LIVE) |
| **T2** 23.1+23.4+23.9 closure | D29-Functional + archive UI + 72h observation | ~19h | 1 hafta | R7 (browser verify) |
| **T3** 23.3+23.5 | SMS JetSMS primary + NetGSM secondary + Preference UI | ~65h | 3 hafta | R1 (NetGSM secondary contract — failover acceptance blocker), R3 (DKIM) |
| **T4** 23.6+23.7+23.8 v1 | Teams + WebPush (browser-only) + Tempo + bounce + per-tenant dashboard | ~99h estimate / ~58.5h actual + ~14h residual (T4.3.5 FBL + T4.3.7 per-template + T4.3.8 federation); mobile FCM/APNS ~24h Faz 22.2 dep DIŞI — Session 47 re-baseline 2026-05-21 (T4.1 + T4.2 browser-only 11 sub-PR + #649 UI integration MERGED + T4.3.a Tempo + T4.3.b suppression + T4.3.6 per-tenant dashboard MERGED) | ~2 hafta residual | R11 ~mitigated (Tempo LIVE), R16 (federation pending) |
| **T5** 23.X v2 | multi-tenant features | ~144h | 8-12 hafta | R10 (multi-tenant migration) |
| **Total v1 (T1-T4)** | Faz 23.0 → 23.9 v1 closure | **~14h agent-actionable residual** (T4.3.5 + T4.3.7 + T4.3.8 backend + gitops); T1/T2/T3 source-side LIVE; M1 T2.3 5/6 operator+user external (R7); M3 R2 KVKK legal 2026-05-25; M4 R1/R24 + canary KC org_id ext-gated; mobile FCM/APNS ~24h Faz 22.2 dep **DIŞI**. Session 47 re-baseline 2026-05-21 — önceki Session 41 ~17-22h Tier 1 residual + Tier 2/3/4 dahil 100-130h → ~14h agent + external acceptance gates | **~1-2 hafta agent + 4 gün external** (R2 KVKK 2026-05-25) | — |
| **Total + v2** | Faz 23.0 → 23.X | ~158-160h (~14h v1 + ~144h v2) | **~3-4 ay** v2 inclusive | — |

**Estimation accuracy**: ±25% based on Codex peer review iter overhead + integration test discovery + cluster apply gates.

---

## Status Tracking

Update this doc per-PR:
1. Task status: 🔴 → 🟡 (in progress) → 🟢 (done)
2. Actual hours vs estimate (track velocity calibration)
3. Codex thread reference per task closure
4. Risk register cross-reference if new risk uncovered

**Last update**: 2026-05-21 (Session 47 full re-baseline; T1 LIVE + T2 T2.1/T2.2 LIVE + T3 LIVE + T4.1/T4.2-browser/T4.3.a/T4.3.b/T4.3.6 LIVE; agent-actionable residual ~14h T4.3 tail; external acceptance gates R2/R7/R9/R1/R24)
