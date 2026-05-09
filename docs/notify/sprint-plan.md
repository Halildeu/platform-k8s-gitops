# Notification Platform — Sprint Plan + Estimation

> **Status**: ACTIVE (Session 39 PM artifact bootstrap 2026-05-09)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Charter**: [RB-faz-23-charter](../runbooks/RB-faz-23-charter.md)
> **Risk register**: [risk-register.md](risk-register.md)
> **Test strategy**: [test-strategy.md](test-strategy.md)
> **Milestones**: [milestones.md](milestones.md)

Bu doküman **task-level breakdown + estimation + ownership + dependency** sağlar. Her task: Sub-faz, Tier (T1..T5), Type (backend/frontend/gitops/docs), Estimation (h), Owner, Dependency, Status.

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

## Tier 1: 23.2 Production MVP Dar Closure (4-6 weeks, ~100h aggressive target)

> **Effort note (Codex iter-2 absorb 2026-05-09)**: T1 toplam = T1.1 27h + T1.2 17h + T1.3 13h + T1.4 15.5h + T1.5 12h + T1.6 15h ≈ **99.5h ~100h aggressive target**. Önceki "80h" başlığı R2 KVKK legal review beklemesini saymıyordu — iter-2 tek-sayı sweep ile T1 bottleneck = ~100h olarak sabitlenmiştir; M3 target 2026-06-08 "aggressive" etiketiyle.

### T1.1 — 23.2.A Preference + Opt-out + Critical Bypass (must-have #8)

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T1.1.1 | V9 migration: `notify.subscriber_preference` table | backend | 2 | dev | None | 🔴 |
| T1.1.2 | Domain entity + repository + service (preference CRUD) | backend | 4 | dev | T1.1.1 | 🔴 |
| T1.1.3 | REST API: `PUT /preferences/me` + `GET /preferences/me` | backend | 3 | dev | T1.1.2 | 🔴 |
| T1.1.4 | Send pipeline preference check + `BLOCKED_BY_PREFERENCE` audit | backend | 3 | dev | T1.1.3 | 🔴 |
| T1.1.5 | Critical bypass logic (severity=critical OR data_classification=security) | backend | 2 | dev | T1.1.4, T1.5.1 | 🔴 |
| T1.1.6 | Quiet hours bypass | backend | 2 | dev | T1.1.4 | 🔴 |
| T1.1.7 | Frequency limit bypass | backend | 2 | dev | T1.1.4 | 🔴 |
| T1.1.8 | Unsubscribe link footer (email template) | backend | 2 | dev | T1.1.3 | 🔴 |
| T1.1.9 | Integration test: preference scenarios | backend | 4 | dev | T1.1.5 | 🔴 |
| T1.1.10 | Gitops env enable test+prod overlays | gitops | 1 | gitops | T1.1.9 | 🔴 |
| T1.1.11 | Codex peer review + merge | docs | 1 | agent | T1.1.10 | 🔴 |
| T1.1.12 | Charter + must-have-checklist marker update | docs | 1 | agent | T1.1.11 | 🔴 |

**Total**: 27h

### T1.2 — 23.2.B KVKK Erasure + Right-to-Information (must-have #7 closure)

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T1.2.1 | REST API: `DELETE /audit/me` (payload purge, recipient_hash kalır) | backend | 3 | dev | None | 🔴 |
| T1.2.2 | REST API: `GET /audit/me` (subscriber's own history) | backend | 2 | dev | None | 🔴 |
| T1.2.3 | Append-only enforcement verification (V8 trigger LIVE; test) | backend | 1 | dev | None | 🔴 |
| T1.2.4 | Integration test: erasure flow + recipient_hash preservation | backend | 4 | dev | T1.2.1 | 🔴 |
| T1.2.5 | Integration test: right-to-information | backend | 2 | dev | T1.2.2 | 🔴 |
| T1.2.6 | Runbook: `RB-notify-kvkk-erasure.md` update with API examples | docs | 1 | agent | T1.2.4 | 🔴 |
| T1.2.7 | Legal review (KVKK Art.11 + Art.13 compliance) | review | 2 | legal | T1.2.6 | 🔴 |
| T1.2.8 | Codex peer review + merge | docs | 1 | agent | T1.2.7 | 🔴 |
| T1.2.9 | Charter + must-have-checklist marker update | docs | 1 | agent | T1.2.8 | 🔴 |

**Total**: 17h

### T1.3 — 23.2.C Provider Config Versioning + Rollback

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T1.3.1 | V9 migration: `notify.provider_config_history` table (version + diff) | backend | 2 | dev | None | 🔴 |
| T1.3.2 | Domain service: provider config versioning | backend | 3 | dev | T1.3.1 | 🔴 |
| T1.3.3 | Atomic switch + cache invalidate API | backend | 3 | dev | T1.3.2 | 🔴 |
| T1.3.4 | Integration test: rollback scenario | backend | 3 | dev | T1.3.3 | 🔴 |
| T1.3.5 | Runbook: `RB-notify-provider-config-rollback.md` | docs | 1 | agent | T1.3.4 | 🔴 |
| T1.3.6 | Codex peer review + merge | docs | 1 | agent | T1.3.5 | 🔴 |

**Total**: 13h

### T1.4 — 23.2.D Outage Fallback Bypass D43 (must-have #10 closure)

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T1.4.1 | Vault path `kv/platform/alertmanager-fallback` (separate creds) | ops | 1 | ops | None | 🔴 |
| T1.4.2 | ESO ExternalSecret for fallback | gitops | 1 | gitops | T1.4.1 | 🔴 |
| T1.4.3 | Alertmanager bridge dual-route config | gitops | 3 | gitops | T1.4.2 | 🔴 |
| T1.4.4 | NotifyServiceDown alert routing override (already exists; verify) | gitops | 0.5 | gitops | T1.4.3 | 🔴 |
| T1.4.5 | Drift alarm-receiver fallback chain extension | backend | 3 | dev | None | 🔴 |
| T1.4.6 | Break-glass dual-channel script (notification + Alertmanager direct) | ops | 2 | ops | T1.4.4 | 🔴 |
| T1.4.7 | Runbook: `RB-notification-outage-fallback.md` | docs | 2 | agent | T1.4.6 | 🔴 |
| T1.4.8 | Drill test execution (orchestrator scale=0 → Slack direct verify) | ops | 2 | ops | T1.4.7 | 🔴 |
| T1.4.9 | Codex peer review + merge | docs | 1 | agent | T1.4.8 | 🔴 |

**Total**: 15.5h

### T1.5 — 23.2.E Data Classification Policy

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T1.5.1 | V9 migration: `notification_intent.data_classification` field | backend | 1 | dev | None | 🔴 |
| T1.5.2 | Enum + validator (transactional/security/commercial/system) | backend | 2 | dev | T1.5.1 | 🔴 |
| T1.5.3 | Send pipeline: classification-bound retention + opt-out behavior | backend | 4 | dev | T1.5.2, T1.1.5 | 🔴 |
| T1.5.4 | Integration test: 4 classifications + edge cases | backend | 3 | dev | T1.5.3 | 🔴 |
| T1.5.5 | Runbook update | docs | 1 | agent | T1.5.4 | 🔴 |
| T1.5.6 | Codex peer review + merge | docs | 1 | agent | T1.5.5 | 🔴 |

**Total**: 12h

### T1.6 — 23.2.F Abuse Prevention Guards D45

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T1.6.1 | Rate limit per source (token bucket / sliding window) | backend | 4 | dev | None | 🔴 |
| T1.6.2 | Duplicate flood detection | backend | 3 | dev | T1.6.1 | 🔴 |
| T1.6.3 | Webhook fan-out cap | backend | 2 | dev | T1.6.1 | 🔴 |
| T1.6.4 | 429 + audit `RATE_LIMITED` responses | backend | 1 | dev | T1.6.1 | 🔴 |
| T1.6.5 | PrometheusRule: rate limit storm alert | gitops | 1 | gitops | T1.6.4 | 🔴 |
| T1.6.6 | Integration test: rate limit + flood scenarios | backend | 3 | dev | T1.6.4 | 🔴 |
| T1.6.7 | Codex peer review + merge | docs | 1 | agent | T1.6.6 | 🔴 |

**Total**: 15h

**Tier 1 Total**: ~100h productive work (~10-13 day blocks; exact sum 99.5h)

---

## Tier 2: 23.1 + 23.4 + 23.9 Closure (~1 week, ~15h)

### T2.1 — 23.1 D29-NOTIFY-Functional 3-channel Evidence

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T2.1.1 | Mailpit test message + screenshot evidence | ops | 1 | ops | None | 🔴 |
| T2.1.2 | Slack test channel test + screenshot evidence | ops | 1 | ops | None | 🔴 |
| T2.1.3 | Webhook HMAC trace + delivery row INSERT | ops | 1 | ops | None | 🔴 |
| T2.1.4 | Evidence document: `docs/faz-23-evidence/2026-XX-XX-23-1-d29-functional.md` | docs | 1 | agent | T2.1.3 | 🔴 |
| T2.1.5 | Charter 23.1 marker 🟡 → 🟢 + evidence path fill | docs | 0.5 | agent | T2.1.4 | 🔴 |

**Total**: 4.5h

### T2.2 — 23.4 Closure: Archive UI + 30d History

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T2.2.1 | FE: archive button (mfe-host inbox component) | frontend | 3 | dev | None | 🔴 |
| T2.2.2 | Backend: notification history `GET /inbox/me?since=30d` filter | backend | 2 | dev | None | 🔴 |
| T2.2.3 | FE: 30d notification history filter UI | frontend | 2 | dev | T2.2.2 | 🔴 |
| T2.2.4 | Integration test: archive + history scenarios | backend + frontend | 2 | dev | T2.2.3 | 🔴 |
| T2.2.5 | (SMS DLR deferred — Faz 23.3 prerequisite) | — | — | — | T3.1 | ⏳ |
| T2.2.6 | Codex peer review + merge | docs | 1 | agent | T2.2.4 | 🔴 |

**Total**: 10h (SMS DLR portion in 23.3)

### T2.3 — 23.9 Closure: 72h Observation + Rollback Prova + Browser SSO Verify

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T2.3.1 | 72h observation completion (T+72h = 2026-05-11 19:42Z natural) | ops | passive | ops | Time | 🟡 |
| T2.3.2 | Rollback prova execution (drill mode — non-destructive) | ops | 2 | ops | T2.3.1 | 🔴 |
| T2.3.3 | Browser SSO verify on testai.acik.com | user | 0.5 | user | None | 🔴 |
| T2.3.4 | Browser SSO verify on ai.acik.com | user | 0.5 | user | None | 🔴 |
| T2.3.5 | Evidence document: `docs/faz-23-evidence/2026-05-11-23-9-cutover-72h.md` | docs | 1 | agent | T2.3.4 | 🔴 |
| T2.3.6 | Charter 23.9 marker 🟡 → 🟢 | docs | 0.5 | agent | T2.3.5 | 🔴 |

**Total**: 4.5h (T2.3.1 passive)

**Tier 2 Total**: ~19h

---

## Tier 3: 23.3 SMS + 23.5 Preference UI (~3 weeks, ~50h)

### T3.1 — 23.3 SMS NetGSM + In-app Inbox API

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T3.1.1 | NetGSM provider contract + sandbox account (R1 mitigation) | ops/legal | 8 | ops | None | 🔴 |
| T3.1.2 | `SmsProvider` interface design | backend | 2 | dev | None | 🔴 |
| T3.1.3 | `NetGsmClient` implementation (REST/SOAP per provider docs) | backend | 8 | dev | T3.1.2 | 🔴 |
| T3.1.4 | GSM-7/UCS-2 segment + Türkçe karakter + sender ID | backend | 3 | dev | T3.1.3 | 🔴 |
| T3.1.5 | `İletimerkezi` secondary client | backend | 4 | dev | T3.1.2 | 🔴 |
| T3.1.6 | Provider failover (pre-accept fail auto) | backend | 3 | dev | T3.1.5 | 🔴 |
| T3.1.7 | DLR callback endpoint | backend | 3 | dev | T3.1.3 | 🔴 |
| T3.1.8 | 4 workflow live test (admin invite, password reset, drift alarm, break-glass) | backend | 4 | dev | T3.1.7 | 🔴 |
| T3.1.9 | Vault path `kv/platform/notification-orchestrator` SMS provider creds | ops | 1 | ops | T3.1.1 | 🔴 |
| T3.1.10 | In-app inbox API closure (paged + read + archive + WS endpoint) | backend | 6 | dev | None | 🟡 |
| T3.1.11 | Codex peer review + merge | docs | 2 | agent | T3.1.10 | 🔴 |

**Total**: 44h

### T3.2 — 23.5 Preference UI (FE)

| ID | Task | Type | Est (h) | Owner | Dep | Status |
|---|---|---|---:|---|---|:---:|
| T3.2.1 | mfe-host preference settings page route + skeleton | frontend | 2 | dev | T1.1.3 | 🔴 |
| T3.2.2 | Per-channel toggle UI | frontend | 3 | dev | T3.2.1 | 🔴 |
| T3.2.3 | Per-topic toggle UI | frontend | 3 | dev | T3.2.2 | 🔴 |
| T3.2.4 | Quiet hours editor | frontend | 4 | dev | T3.2.3 | 🔴 |
| T3.2.5 | Frequency limit slider | frontend | 2 | dev | T3.2.4 | 🔴 |
| T3.2.6 | Unsubscribe link landing page (RFC 8058 one-click) | frontend | 3 | dev | None | 🔴 |
| T3.2.7 | Integration test: end-to-end preference flow | frontend | 3 | dev | T3.2.6 | 🔴 |
| T3.2.8 | Codex peer review + merge | docs | 1 | agent | T3.2.7 | 🔴 |

**Total**: 21h

**Tier 3 Total**: ~65h

---

## Tier 4: 23.6 + 23.7 + 23.8 v1 (~6 weeks, ~80h)

### T4.1 — 23.6 Teams + Slack Zenginleştirme

| ID | Task | Type | Est (h) | Owner | Status |
|---|---|---|---:|---|:---:|
| T4.1.1 | Microsoft Teams adapter (Power Automate webhook + Adaptive Cards) | backend | 12 | dev | 🔴 |
| T4.1.2 | Slack zenginleştirme (Block Kit + threading) | backend | 8 | dev | 🔴 |
| T4.1.3 | Vault path Teams + Slack credentials | ops | 1 | ops | 🔴 |
| T4.1.4 | Integration test | backend | 3 | dev | 🔴 |
| T4.1.5 | Codex peer review + merge | docs | 1 | agent | 🔴 |

**Total**: 25h

### T4.2 — 23.7 Push (FCM/APNS)

| ID | Task | Type | Est (h) | Owner | Status |
|---|---|---|---:|---|:---:|
| T4.2.1 | FCM adapter (Android — Faz 22.2 endpoint-admin coupling) | backend | 10 | dev | 🔴 |
| T4.2.2 | APNS adapter (iOS — Faz 22.2 if iOS gerekirse) | backend | 10 | dev | 🔴 |
| T4.2.3 | `subscriber_device` token registry table + V10 migration | backend | 3 | dev | 🔴 |
| T4.2.4 | Token rotation handling | backend | 4 | dev | 🔴 |
| T4.2.5 | Web Push (browser, VAPID) | backend | 6 | dev | 🔴 |
| T4.2.6 | Integration test | backend | 4 | dev | 🔴 |
| T4.2.7 | Codex peer review + merge | docs | 1 | agent | 🔴 |

**Total**: 38h

### T4.3 — 23.8 Tempo + Bounce Loop + Per-Tenant Grafana

| ID | Task | Type | Est (h) | Owner | Status |
|---|---|---|---:|---|:---:|
| T4.3.1 | Tempo Helm chart deploy in monitoring ns | gitops | 4 | gitops | 🔴 |
| T4.3.2 | OTLP collector deployment + service | gitops | 3 | gitops | 🔴 |
| T4.3.3 | notify-orch tracing reactivation env (MANAGEMENT_TRACING_ENABLED=true) | gitops | 1 | gitops | 🔴 |
| T4.3.4 | Email bounce loop (provider feedback → suppression list) | backend | 8 | dev | 🔴 |
| T4.3.5 | Spam complaint feedback (FBL endpoint) | backend | 4 | dev | 🔴 |
| T4.3.6 | Per-tenant Grafana dashboard | gitops | 4 | gitops | 🔴 |
| T4.3.7 | Per-template analytics | backend | 4 | dev | 🔴 |
| T4.3.8 | Cross-cluster Prometheus federation (R16 mitigation) | gitops | 6 | gitops | 🔴 |
| T4.3.9 | Codex peer review + merge | docs | 2 | agent | 🔴 |

**Total**: 36h

**Tier 4 Total**: ~99h

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
| **T1** 23.2 closure | preference + erasure + provider rollback + outage fallback + classification + abuse | ~100h | 4-6 hafta | R2 (KVKK), R9 (D43), R13 (abuse) |
| **T2** 23.1+23.4+23.9 closure | D29-Functional + archive UI + 72h observation | ~19h | 1 hafta | R7 (browser verify) |
| **T3** 23.3+23.5 | SMS NetGSM + Preference UI | ~65h | 3 hafta | R1 (NetGSM contract), R3 (DKIM) |
| **T4** 23.6+23.7+23.8 v1 | Teams + Push + Tempo + bounce | ~99h | 5-6 hafta | R11 (Tempo), R16 (federation) |
| **T5** 23.X v2 | multi-tenant features | ~144h | 8-12 hafta | R10 (multi-tenant migration) |
| **Total v1 (T1-T4)** | Faz 23.0 → 23.9 v1 closure | ~280h | **3-4 ay** (with parallelization) | — |
| **Total + v2** | Faz 23.0 → 23.X | ~424h | **6-8 ay** | — |

**Estimation accuracy**: ±25% based on Codex peer review iter overhead + integration test discovery + cluster apply gates.

---

## Status Tracking

Update this doc per-PR:
1. Task status: 🔴 → 🟡 (in progress) → 🟢 (done)
2. Actual hours vs estimate (track velocity calibration)
3. Codex thread reference per task closure
4. Risk register cross-reference if new risk uncovered

**Last update**: 2026-05-09 (Session 39 PM bootstrap; all tasks 🔴 except T2.3.1 🟡 passive)
