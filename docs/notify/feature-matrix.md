# Notification Platform Feature Matrix — Canlı Tracker

> **Status**: ACTIVE (charter base 2026-05-05; **truth alignment 2026-05-09 Session 39 post 11-PR cycle**)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Roadmap**: [RB-faz-23-charter](../runbooks/RB-faz-23-charter.md)

**16 kategori** × **~178 özellik** (literal row count 178; önceki "~140" rakamı semantic estimate idi — Codex iter-2 absorb 2026-05-09'da 178 olarak sabitlenmiştir). Her özellik için tier (Kernel/MVP-dar/MVP-geniş/v1/v2/scope-dışı) + sub-faz + status. Sub-faz tamamlandığında status güncellenir.

> **Not 1**: Kategori sayısı **11 → 16** artışı: ADR-0013 D45 ile 5 yeni kategori eklendi (Deliverability, Abuse/spam, Accessibility, Incident/degraded, Data classification).
> **Not 2**: SMS tier **MVP-geniş (23.3)** olarak mühürlendi. ADR D40 metnindeki "tier v1" yorumu D44 channel coverage ile çelişti; D44 + feature matrix authoritative — SMS MVP-geniş, DLR callback v1.
> **Not 3**: DKIM/SPF/DMARC config implementation tier **23.2 MVP-dar**, ancak ADR D29-NOTIFY-Functional Email "DKIM signed" gerektirir. Kernel email D29-Functional için **Mailpit dev DKIM signing** kullanılır (production DKIM 23.2'de aktivasyon).

**Status legend**: ☐ pending · 🟡 in-progress · 🟢 done · ✗ scope-dışı

## 📊 Snapshot (2026-05-09 Session 39, Codex `019e0bff` iter-1 absorb — actual category names)

**Semantic roll-up** (NOT literal table marker count — gerçek satır markerları aşağıdaki kategori tablolarında, çoğu hâlâ ☐; full marker pass deferred follow-up).

**By tier (semantic estimate)**:
- Kernel (23.1) features substantively LIVE: schema, idempotency, outbox, retry/DLQ, authz strict, templates (~18-20 of 25)
- MVP-dar (23.2) Session 39 hardening LIVE: Vault/ESO + audit retention + Grafana + alerts + SLO (5 of 8 acceptance)
- MVP-dar (23.2) original kabul kriteri: 2/8 done (Grafana + Alertmanager); 6 pending (preference, erasure, provider rollback, outage fallback, classification, abuse)
- MVP-geniş (23.3): 0 LIVE end-to-end (NetGSM contract pending R1); **infrastructure progress Session 42: 23.3.1 NetGSM Vault path canonical LIVE 2026-05-10 (PR #482 + #485 DLR follow-up) — kv/platform/notification-orchestrator + 4 NetGSM keys (username/password/msgheader/dlr_token all empty fail-closed) + ESO 9/9 Ready + 4/4 pod env vars injected**
- v1 (23.4-23.8): ~5-6 LIVE (in-app UI + identity guards + dashboard SLO panels)
- v2 (23.X): 0 LIVE (deferred)

**By actual category** (from §1..§16 below):
- §1 Channel Coverage: 5/19 LIVE (Email A1, Slack A2, Webhook A3, in-app API A5, in-app UI A6)
- §2 Workflow/Routing: 5/16 LIVE (single-channel B1, fan-out B2, retry B4, DLQ B5, code-based B6)
- §3 Template Management: substantially LIVE (Kernel)
- §4 Subscriber/Preferences: 🟡 partial (preference REST API + service + critical bypass source-ready/live-deployed; D29-Authorized BLOCKED on RAID I6; UI 23.5 pending) — M3 stale audit 2026-05-09
- §5 Tenant/Multi-tenancy/Branding: 🟡 multi-tenancy guard LIVE; per-tenant brand pending
- §6 Audit/Compliance: 🟡 audit append-only LIVE; KVKK retention LIVE; erasure/right-to-info pending
- §7 Analytics/Observability: 🟡 metrics + alerts + dashboard + SLO LIVE; tracing (Tempo) + bounce loop + per-tenant dashboard pending
- §8 Provider Management: 🟡 provider abstraction LIVE; versioning/rollback pending
- §9 Developer Experience: 🟡 partial
- §10 UI/Self-service: 🟡 in-app inbox UI LIVE; preference UI pending
- §11 Security/Trust: 🟡 strict identity guards LIVE; DKIM signing pending production
- §12 Deliverability: ⏳ pending (DKIM/SPF/DMARC config)
- §13 Abuse/Spam: ⏳ pending
- §14 Accessibility (WCAG): ⏳ pending
- §15 Incident/Degraded Mode: 🟡 alerts/SLO/dashboard LIVE; **D43 outage fallback bypass gerçek pending T1.4 ~15h (R9 drill blocker)** — M3 stale audit confirmed
- §16 Data Classification: 🟢 substantively LIVE (enum 4 değer transactional/security/commercial/system + IntentSubmissionService + DeliveryEligibilityService source-ready/live; acceptance test gate) — M3 stale audit 2026-05-09

**Overall**:
- Substantively LIVE features: ~30-35 of ~178 (excluding scope-dışı 5)
- Partial coverage: ~25-30 features
- Pending: ~115 features
- Coverage estimate: **~30% v1 scope, ~50% Kernel scope, ~25% MVP-dar scope**

> **Marker discipline (Codex `019e0bff` iter-1)**: Snapshot semantic roll-up'tır, literal matrix değil. Aşağıdaki kategori tablolarındaki literal ☐/🟡/🟢 markerları zaman içinde update edilecek (full pass deferred follow-up; ~178 row sweep). Snapshot ve literal arasındaki sayı farkı bu nedenle (10 done vs ~50 semantic) — doc-drift'in kabul edilmiş kalıntısı, planlı remediation'da.

---

## 1. Channel Coverage

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| A1 | Email transactional (SMTP) | **Kernel** | 23.1 | 🟢 |
| A2 | Slack incoming webhook | **Kernel** | 23.1 | 🟢 |
| A3 | Webhook egress (HMAC signed) | **Kernel** | 23.1 | 🟢 |
| A4 | SMS (NetGSM primary, İletimerkezi secondary) | **MVP-geniş** | 23.3 | 🟡 (23.3.1 Vault path canonical LIVE Session 42 PR #482; backend SmsAdapter LIVE platform-backend #77; **NetGSM contract activation R1 ETA 2026-05-30 pending** + DLR + IYS + secondary failover) |
| A5 | In-app inbox backend API | **MVP-geniş** | 23.3 | 🟢 (LIVE GET /inbox/me + SSE) |
| A6 | In-app inbox React UI (custom) | v1 | 23.4 | 🟢 (PR-5.x cycle LIVE) |
| A7 | Microsoft Teams (Adaptive Cards) | v1 | 23.6 | ☐ |
| A8 | Mobile push FCM (Android) | v1 | 23.7 | ☐ |
| A9 | Mobile push APNS (iOS) | v1 | 23.7 (Faz 22.2 iOS gerekirse) | ☐ |
| A10 | Web Push (browser, VAPID) | v1 | 23.7 | ☐ |
| A11 | WhatsApp Business | v2 | 23.X | ☐ |
| A12 | Voice / IVR (TTS) | v2 | 23.X | ☐ |
| A13 | PWA / desktop | v2 | 23.X | ☐ |
| A14 | Discord | opsiyonel | future | ☐ |
| A15 | Telegram | opsiyonel | future | ☐ |
| A16 | Email newsletter/marketing | ✗ scope-dışı | — | ✗ |
| A17 | RCS messaging | ✗ scope-dışı | — | ✗ |
| A18 | Apple Business Chat | ✗ scope-dışı | — | ✗ |
| A19 | Google Business Messages | ✗ scope-dışı | — | ✗ |

## 2. Workflow / Routing

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| B1 | Single-channel send | **Kernel** | 23.1 | 🟢 |
| B2 | Channel fan-out (multi-channel aynı anda) | **Kernel** | 23.1 | 🟢 |
| B3 | Throttle per provider (NetGSM 100/dk) | **Kernel** | 23.1 | 🟡 (provider stub; tuning Faz 23.3) |
| B4 | Retry exponential backoff (max 5 attempt) | **Kernel** | 23.1 | 🟢 (RetryWorker LIVE) |
| B5 | DLQ (manual replay endpoint) | **Kernel** | 23.1 | 🟢 (LIVE + 4 alerts + SLO) |
| B6 | Code-based workflow (Java DSL) | **Kernel** | 23.1 | 🟢 |
| B7 | Multi-step workflow (ardışık adım) | v1 | 23.4 | ☐ |
| B8 | Channel priority/fallback (email→SMS) | v1 | 23.4 | ☐ |
| B9 | Conditional step (rule: `if user.role == admin`) | v1 | 23.4 | ☐ |
| B10 | Delay / Schedule (`scheduled_at`) | v1 | 23.4 | ☐ |
| B11 | Digest (saatlik/günlük gruplandırma) | v1 | 23.8 | ☐ |
| B12 | Throttle per recipient (max N/saat per user) | v1 | 23.4 | ☐ |
| B13 | Recurring (CRON) | v2 | 23.X | ☐ |
| B14 | A/B testing (variant) | v2 | 23.X | ☐ |
| B15 | No-code workflow editor UI | v2 | 23.X | ☐ |
| B16 | Fallback channel canary test (gate) | **MVP-dar** | 23.2 | ☐ |

## 3. Template Management

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| C1 | Template versioning DB-backed | **Kernel** | 23.1 | ☐ |
| C2 | i18n (tr-TR + en-US baseline) | **Kernel** | 23.1 | ☐ |
| C3 | Variable interpolation (safe `${user.name}`) | **Kernel** | 23.1 | ☐ |
| C4 | Multipart (HTML + plain text) | **Kernel** | 23.1 | ☐ |
| C5 | Test send (admin endpoint) | **Kernel** | 23.1 | ☐ |
| C6 | Subject + body ayrı render | **Kernel** | 23.1 | ☐ |
| C7 | Provider config versioning + rollback | **MVP-dar** | 23.2 | ☐ |
| C8 | Template inline preview UI | v1 | 23.4 | ☐ |
| C9 | Dynamic blocks Thymeleaf (loops/conditionals) | v1 | 23.4 | ☐ |
| C10 | Attachment (PDF/PNG) | v1 | 23.4 | ☐ |
| C11 | Code editor raw HTML (admin) | v1 | 23.5 | ☐ |
| C12 | MJML support (responsive email) | v1 | 23.5 | ☐ |
| C13 | Brand template (logo/color/footer) | v1 | 23.6 | ☐ |
| C14 | Per-tenant template override | v1 | 23.6 | ☐ |
| C15 | Template editor UI (WYSIWYG) | v2 | 23.X | ☐ |
| C16 | Translation memory / auto-translate | ✗ scope-dışı | — | ✗ |

## 4. Subscriber / Preferences

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| D1 | Subscriber tablosu (id, email, phone, locale, tz) | **Kernel** | 23.1 | ☐ |
| D2 | External recipient (platform-dışı email/phone) | **Kernel** | 23.1 | ☐ |
| D3 | Recipient validation (RFC 5322 email + E.164 phone) | **Kernel** | 23.1 | ☐ |
| D4 | Per-channel preference (email/SMS/in-app/Slack ayrı toggle) | **MVP-dar** | 23.2 | ☐ |
| D5 | Per-topic preference (drift-alarm yes, system-update no) | **MVP-dar** | 23.2 | ☐ |
| D6 | Unsubscribe link (email footer) | **MVP-dar** | 23.2 | ☐ |
| D7 | Quiet override (kritik notification bypass) | **MVP-dar** | 23.2 | ☐ |
| D8 | Topic flat key + severity (D45 data classification ile birlikte) | **MVP-dar** | 23.2 | ☐ |
| D9 | Multiple addresses per subscriber | v1 | 23.5 | ☐ |
| D10 | Quiet hours (22:00-08:00 sadece kritik) | v1 | 23.5 | ☐ |
| D11 | Frequency limit (max N/gün) | v1 | 23.5 | ☐ |
| D12 | One-click unsubscribe (RFC 8058) | v1 | 23.5 | ☐ |
| D13 | Self-service preference UI (mfe-host) | v1 | 23.5 | ☐ |
| D14 | Subscriber import (CSV/API) | v1 | 23.5 | ☐ |
| D15 | Suppression list (hard-bounce / spam complaint) | v1 | 23.8 | ☐ |
| D16 | Topic hierarchy | v1 | 23.5 (flat MVP yeter) | ☐ |

## 5. Tenant / Multi-tenancy / Branding

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| E1 | Multi-tenant (org_id boundary) | **Kernel** | 23.1 | ☐ |
| E2 | Cross-tenant hard-deny (OpenFGA) | **Kernel** | 23.1 | ☐ |
| E3 | Multi-environment (test/prod) | **Kernel** | 23.1 | ☐ |
| E4 | Per-tenant brand (logo/color/footer) | v1 | 23.6 | ☐ |
| E5 | Per-tenant template override | v1 | 23.6 | ☐ |
| E6 | Tenant onboarding API | v1 | 23.5 | ☐ |
| E7 | Per-tenant provider config (org X kendi SMTP) | v2 | 23.X | ☐ |
| E8 | Per-tenant rate quota | v2 | 23.X | ☐ |

## 6. Audit / Compliance

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| F1 | Delivery log (per-message audit) | **Kernel** | 23.1 | ☐ |
| F2 | PII redaction (log + audit body yok) | **Kernel** | 23.1 | ☐ |
| F3 | Audit retention 90 gün default | **Kernel** | 23.1 | ☐ |
| F4 | Audit query API | **MVP-dar** | 23.2 | ☐ |
| F5 | KVKK Art.11 right-to-erasure (API/runbook) | **MVP-dar** | 23.2 | ☐ |
| F6 | KVKK Art.13 right-to-information (API) | **MVP-dar** | 23.2 | ☐ |
| F7 | Data classification policy enforcement | **MVP-dar** | 23.2 | ☐ |
| F8 | Audit append-only (app-level no-update/delete rule) | **MVP-dar** | 23.2 | ☐ |
| F9 | Activity feed admin (UI) | v1 | 23.5 | ☐ |
| F10 | Subscriber's own delivery history (UI) | v1 | 23.5 | ☐ |
| F11 | Export to SIEM (Splunk/ELK/syslog) | v1 | 23.8 | ☐ |
| F12 | Webhook for compliance events | v1 | 23.8 | ☐ |
| F13 | KVKK explicit consent tracking | v1 | 23.5 | ☐ |
| F14 | IYS lookup (TR commercial SMS) | sub-faz drift | D40-IYS | ☐ |
| F15 | DPA (3rd party provider) | sub-faz drift | legal | ☐ |
| F16 | Compliance certifications (SOC 2, ISO 27001) | ✗ scope-dışı | — | ✗ |

## 7. Analytics / Observability

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| G1 | Delivery metrics (Prometheus export) | **Kernel** | 23.1 | ☐ |
| G2 | Distributed tracing (correlation_id) | **Kernel** | 23.1 | ☐ |
| G3 | Real-time delivery status API | **MVP-dar** | 23.2 | ☐ |
| G4 | Alertmanager rule (DLQ > N) | **MVP-dar** | 23.2 | ☐ |
| G5 | Grafana dashboard (delivery rate, channel breakdown, DLQ) | **MVP-dar** | 23.2 | ☐ |
| G6 | Per-channel analytics | v1 | 23.8 | ☐ |
| G7 | Per-template analytics | v1 | 23.8 | ☐ |
| G8 | Per-tenant dashboard | v1 | 23.8 | ☐ |
| G9 | Open / click tracking (email — privacy concern) | v1 (opt-in) | 23.8 | ☐ |
| G10 | Real-time delivery status UI | v1 | 23.5 | ☐ |

## 8. Provider Management

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| H1 | Provider config env-specific (test/prod) | **Kernel** | 23.1 | ☐ |
| H2 | Provider rate limit (orchestrator-side) | **Kernel** | 23.1 | ☐ |
| H3 | Provider config versioning (rollback) | **MVP-dar** | 23.2 | ☐ |
| H4 | DKIM/SPF/DMARC config (sub-faz 23.2) | **MVP-dar** | 23.2 (runbook) | ☐ |
| H5 | DLR / delivery callback (SMS) | v1 | 23.4 | ☐ |
| H6 | Multi-provider per channel | v1 | 23.4 | ☐ |
| H7 | Provider failover (primary fail → secondary) | v1 | 23.4 | ☐ |
| H8 | Provider health check (sandbox cron) | v1 | 23.8 | ☐ |
| H9 | Bounce handling (email) | v1 | 23.8 | ☐ |
| H10 | Spam complaint feedback loop | v1 | 23.8 | ☐ |
| H11 | IP allowlist per provider | v1 | 23.8 | ☐ |
| H12 | Provider cost tracking | v2 | 23.X | ☐ |
| H13 | IP rotation (email reputation) | v2 | 23.X | ☐ |

## 9. Developer Experience

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| I1 | REST API | **Kernel** | 23.1 | ☐ |
| I2 | Java SDK (internal) | **Kernel** | 23.1 | ☐ |
| I3 | OpenAPI spec (Springdoc) | **Kernel** | 23.1 | ☐ |
| I4 | Idempotency key support | **Kernel** | 23.1 | ☐ |
| I5 | Sandbox mode (test profile) | **Kernel** | 23.1 | ☐ |
| I6 | Mock provider (Mailpit + WireMock) | **Kernel** | 23.1 | ☐ |
| I7 | JS / TS SDK (mfe-host için) | v1 | 23.4 | ☐ |
| I8 | Webhook ingress (event from external) | v1 | 23.6 | ☐ |
| I9 | Bulk API (1000 recipient batch) | v1 | 23.4 | ☐ |
| I10 | CLI tool | v2 | 23.X | ☐ |
| I11 | Other SDK (Python/Go/Ruby) | ✗ scope-dışı | — | ✗ |

## 10. UI / Self-service

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| J1 | Preference settings UI (mfe-host) | v1 | 23.5 | ☐ |
| J2 | In-app inbox UI (React component) | v1 | 23.4 | ☐ |
| J3 | Mark as read / unread | v1 | 23.4 | ☐ |
| J4 | Archive / delete | v1 | 23.4 | ☐ |
| J5 | Notification history (son 30 gün) | v1 | 23.4 | ☐ |
| J6 | Real-time WebSocket badge (unread count) | v1 | 23.4 | ☐ |
| J7 | Search / filter inbox | v1 | 23.5 | ☐ |
| J8 | Browser push permission banner | v1 | 23.7 | ☐ |
| J9 | Admin: template editor UI | v1 | 23.5 | ☐ |
| J10 | Admin: subscriber browser | v1 | 23.5 | ☐ |
| J11 | Admin: workflow editor UI (no-code) | v2 | 23.X | ☐ |

## 11. Security / Trust

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| K1 | TLS in-transit (provider call) | **Kernel** | 23.1 | ☐ |
| K2 | Webhook HMAC signing (egress) | **Kernel** | 23.1 | ☐ |
| K3 | Vault/ESO provider credentials | **Kernel** | 23.1 | ☐ |
| K4 | Encryption at rest (PG) | infra prereq | platform | ☐ |
| K5 | OpenFGA scope (subscriber#can_receive) | **Kernel** | 23.1 | ☐ |
| K6 | API key rotation runbook | **MVP-dar** | 23.2 | ☐ |
| K7 | Rate limit per source (DDoS protection) | **MVP-dar** | 23.2 | ☐ |
| K8 | Webhook signature verification (ingress) | **MVP-dar** | 23.2 | ☐ |
| K9 | Audit log integrity (append-only) | **MVP-dar** | 23.2 | ☐ |
| K10 | IP allowlist | v1 | 23.8 | ☐ |
| K11 | Vault dynamic secrets (TTL token) | v2 | 23.X | ☐ |

## 12. Deliverability + Sender Reputation (D45 yeni kategori)

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| L1 | DKIM signed email (sub-faz runbook) | **MVP-dar** | 23.2 | ☐ |
| L2 | SPF record (sub-faz runbook) | **MVP-dar** | 23.2 | ☐ |
| L3 | DMARC policy (sub-faz runbook) | **MVP-dar** | 23.2 | ☐ |
| L4 | Bounce categorization (hard/soft/transient) | v1 | 23.8 | ☐ |
| L5 | Spam complaint rate monitor | v1 | 23.8 | ☐ |
| L6 | Delivery reputation per IP/domain | v1 | 23.8 | ☐ |
| L7 | Sender reputation drift detection | v1 | 23.8 | ☐ |

## 13. Abuse / Spam / Recipient Safety (D45 yeni kategori)

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| M1 | Rate limit per source service | **MVP-dar** | 23.2 | ☐ |
| M2 | Duplicate flood detection (same template + same recipient + 5dk) | **MVP-dar** | 23.2 | ☐ |
| M3 | Webhook fan-out cap (max N targets) | **MVP-dar** | 23.2 | ☐ |
| M4 | Tenant abuse detection (anomalous send rate) | v1 | 23.8 | ☐ |
| M5 | Recipient block list (suppression) | v1 | 23.8 | ☐ |

## 14. Accessibility (WCAG) (D45 yeni kategori)

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| N1 | Email template plain text alternative (multipart) | **Kernel** | 23.1 | ☐ |
| N2 | Email template basic readability (heading hierarchy, alt text) | **MVP-dar** | 23.2 | ☐ |
| N3 | In-app inbox keyboard navigation | v1 | 23.4 | ☐ |
| N4 | In-app inbox screen-reader compatibility | v1 | 23.4 | ☐ |
| N5 | Preference UI ARIA labels | v1 | 23.5 | ☐ |
| N6 | Color contrast WCAG AA | v1 | 23.5 | ☐ |
| N7 | Unsubscribe link accessibility | v1 | 23.5 | ☐ |

## 15. Incident / Degraded Mode (D45 yeni kategori)

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| O1 | Outage fallback bypass (Alertmanager direct, orchestrator bypass) | **MVP-dar** | 23.2 | ☐ |
| O2 | Notification-orchestrator down → Slack #alerts direct | **MVP-dar** | 23.2 | ☐ |
| O3 | Drift alarm ↔ Alertmanager direct redundant chain | **MVP-dar** | 23.2 | ☐ |
| O4 | Break-glass audit ↔ Alertmanager direct redundant chain | **MVP-dar** | 23.2 | ☐ |
| O5 | RB-notification-outage-fallback runbook | **MVP-dar** | 23.2 | ☐ |
| O6 | Degraded mode policy (provider down → DLQ + alarm) | v1 | 23.4 | ☐ |
| O7 | Circuit breaker per provider | v1 | 23.4 | ☐ |

## 16. Data Classification (D45 yeni kategori)

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| P1 | `data_classification` field in intent (transactional/security/commercial/system) | **MVP-dar** | 23.2 | 🟢 (M3 audit: enum 4 değer + IntentSubmissionService LIVE) |
| P2 | Quiet bypass policy per classification | **MVP-dar** | 23.2 | 🟡 (severity bypass live, classification security bypass acceptance test) |
| P3 | Retention default per classification (90/180/30/30) | **MVP-dar** | 23.2 | ☐ (retention LIVE per audit 90d; per-classification differentiation pending) |
| P4 | Marketing kapsam ayrımı (commercial = açık rıza zorunlu) | **MVP-dar** | 23.2 | ☐ (transactional kapsam D42 confirmed; commercial track separation pending) |
| P5 | Classification-driven channel restriction (security → no commercial channel) | v1 | 23.4 | ☐ |

---

## Özet Sayım

| Tier | Özellik sayısı | Süre |
|---|---:|---|
| **Kernel/Closed Beta** | 33 | 3-4 hafta |
| **Production MVP dar** | 27 | ~17-22h residual / 1-1.5 hafta provisional (Session 41 re-baseline 2026-05-09 19:50Z post T1.6 LIVE + T1.4 4-PR source-ready; önceki 4-6 hafta / ~100h pessimistic; backend source-ready 12/12 + live-deployed 9/12 + acceptance 0/12; drill execution + acceptance gate operator action) |
| **Production MVP geniş** | 4 | 3 hafta |
| **v1** | ~55 | +4-6 hafta |
| **v2** | ~13 | +8-12 hafta |
| **Sub-faz drift / opsiyonel** | ~5 | — |
| **Scope-dışı** | ~7 | — |

**Toplam Faz 23 (Charter → Prod cutover) = 14-18 hafta**

---

## Update Discipline

Her sub-faz tamamlandığında:

1. İlgili özelliklerin `Status` sütunu ☐ → 🟡 → 🟢 ilerletilir
2. `git commit` mesajında bu dosyada güncellenen özellik ID'leri belirtilir (`feat(notify): A1+A2+A3 done; ref RB-faz-23-charter 23.1`)
3. Toplu sayım tablosu kontrol edilir (sub-faz tier'ında ☐ kalmamalı, hepsi 🟢 olmalı)
4. PR açılır, Codex review (D29-NOTIFY 3-katman evidence ile), merge sonrası bir sonraki sub-faz başlar
