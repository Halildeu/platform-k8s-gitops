# Notification Platform Feature Matrix — Canlı Tracker

> **Status**: ACTIVE (charter base 2026-05-05; **truth alignment 2026-05-09 Session 39 post 11-PR cycle**)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Roadmap**: [RB-faz-23-charter](../runbooks/RB-faz-23-charter.md)

> **Faz 2 — GitHub Project migration (2026-05-17)** — feature-matrix board'a issue olarak **taşınmadı**; 178 satır kasıtlı doc olarak kalır (Codex `019e361d` AGREE — issue listesi yapılmaz, coverage/evidence catalog'u olarak tutulur). Aktif çalışmaya alınan özellik [platform Roadmap board](https://github.com/users/Halildeu/projects/2)'da issue alır ve satırına `tracked by #N` eklenir; row marker tek başına PM progress sinyali değildir.

**16 kategori** × **~178 özellik** (literal row count 178; önceki "~140" rakamı semantic estimate idi — Codex iter-2 absorb 2026-05-09'da 178 olarak sabitlenmiştir). Her özellik için tier (Kernel/MVP-dar/MVP-geniş/v1/v2/scope-dışı) + sub-faz + status. Sub-faz tamamlandığında status güncellenir.

> **Not 1**: Kategori sayısı **11 → 16** artışı: ADR-0013 D45 ile 5 yeni kategori eklendi (Deliverability, Abuse/spam, Accessibility, Incident/degraded, Data classification).
> **Not 2**: SMS tier **MVP-geniş (23.3)** olarak mühürlendi. ADR D40 metnindeki "tier v1" yorumu D44 channel coverage ile çelişti; D44 + feature matrix authoritative — SMS MVP-geniş, DLR callback v1.
> **Not 3**: DKIM/SPF/DMARC config implementation tier **23.2 MVP-dar**, ancak ADR D29-NOTIFY-Functional Email "DKIM signed" gerektirir. Kernel email D29-Functional için **Mailpit dev DKIM signing** kullanılır (production DKIM 23.2'de aktivasyon).

**Status legend**: ☐ pending · 🟡 in-progress · 🟢 done · ✗ scope-dışı

## 📊 Snapshot (2026-05-09 Session 39, Codex `019e0bff` iter-1 absorb — historical; 2026-05-23 literal marker pass Codex `019e5958` AGREE + `019e5963` REVISE absorb)

**Status update 2026-05-24 (BL-008 mock-receipt drill, Codex `019e5aaf` REVISE absorb)**: §15 Incident O1+O2 🟡 → 🟢 **mock-receipt mitigated** (webhook-receiver POST + Mailpit SMTP dual-receipt 2026-05-24; real Slack #853 + prod #854 ext-bound), §2 B16 🟡 → 🟢 mock-receipt mitigated (paralel). O3+O4 hâlâ partial T1.4 closure scope.

**Status update 2026-05-23 (literal marker truth-sync, Codex `019e5958` AGREE + cross-AI peer review thread `019e5963-0633-7412-981d-55284b038a8f` REVISE iter-2 absorb)**: Bu snapshot Session 39'dan tarihli historical kayıt; **literal satır marker'larının full pass'i bu reconciliation PR'da yapıldı** — §1 Channels (A4 SMS 🟢, A7 Teams 🟢, A10 WebPush 🟢) + §2 Workflow (B16 outage fallback 🟡 evidence → 🟢 mock-receipt 2026-05-24) + §3 Templates (C1+C3+C4+C6 Kernel 🟢, C7 23.2.C 🟢) + §4 Subscribers (D1-D8 Kernel/MVP-dar 🟢, D10+D11+D13 23.5 🟢, D12 🟡 public landing LIVE + List-Unsubscribe-Post header TBD, D15 T4.3.b 🟢) + §5 Tenancy (E1+E3 🟢, E2 🟡) + §6 Audit/KVKK (F1-F8 Kernel/MVP-dar 🟢 — R2 KVKK CLOSED 2026-05-23 via Codex `019e5189` legal verdict; F9+F10 23.5 🟢) + §7 Observability (G1-G5 Kernel/MVP-dar 🟢, G6-G8 T4.3 🟢, G10 23.5 🟢) + §8 Provider Management (H1+H3+H5+H6 🟢, H4 🟡 DKIM relay + DNS operator-gated, H7 🟡 NetGSM DEFER, H9 🟢 bounce handling T4.3.b, H10 🟢 source-ready FBL mailbox operator) + §9 DX (I1+I3+I4+I5+I6 Kernel 🟢, I2+I7 🟡 SDK package gevşek) + §10 UI (J1-J6 + J8 23.4-23.7 🟢) + §11 Security (K1-K3 Kernel 🟢, K5 🟡 OpenFGA Layer-1 LIVE, K7 23.2 🟢, K9 🟢) + §12 Deliverability (L1 🟢 DKIM relay, L4 🟢 T4.3.b, L5 🟢 source-ready) + §13 Abuse/Spam (M1+M2 23.2 🟢, M3 🟡, M5 🟡 email-only suppression LIVE) + §14 Accessibility (N1 🟢 multipart C4 covered, N2-N7 ☐) + §15 Incident (O1+O2 🟡 partial → 🟢 mock-receipt 2026-05-24, O3+O4 🟡 partial T1.4, O5 🟢 source-ready). Updates only marked 🟢 where evidence is concrete (sprint-plan / milestones / charter / risk-register / PR # / evidence doc). Source-ready items explicitly tagged "source-ready, operator activation pending" where appropriate (T4.3.5 FBL mailbox, T4.3.7 DB RO role, L1 DKIM DNS, L2/L3 SPF/DMARC DNS).

**Semantic roll-up (historical 2026-05-09)** (NOT literal table marker count — şimdi literal markerlar updated 2026-05-23):

**By tier (semantic estimate)**:
- Kernel (23.1) features substantively LIVE: schema, idempotency, outbox, retry/DLQ, authz strict, templates (~18-20 of 25)
- MVP-dar (23.2) Session 39 hardening LIVE: Vault/ESO + audit retention + Grafana + alerts + SLO (5 of 8 acceptance)
- MVP-dar (23.2) original kabul kriteri: 2/8 done (Grafana + Alertmanager); 6 pending (preference, erasure, provider rollback, outage fallback, classification, abuse)
- MVP-geniş (23.3): 0 LIVE end-to-end; **provider kararı 2026-05-19 (kullanıcı): SMS primary JetSMS (canlı sözleşme var), secondary NetGSM (contract R1 pending)**. Infrastructure progress Session 42: NetGSM Vault path canonical LIVE 2026-05-10 (PR #482 + #485 DLR follow-up); JetSMS HTTP API adapter + failover Faz 23.3 SMS multi-provider PR sequence (PR-0..PR-4, Codex `019e3f82` AGREE)
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
- §15 Incident/Degraded Mode: 🟢 **mock-receipt mitigated** (alerts/SLO/dashboard LIVE; BL-008 D43 dual-receipt drill 2026-05-24 — Codex `019e5aaf` REVISE absorb; real Slack #853 + prod #854 operator-external residual)
- §16 Data Classification: 🟢 substantively LIVE (enum 4 değer transactional/security/commercial/system + IntentSubmissionService + DeliveryEligibilityService source-ready/live; acceptance test gate) — M3 stale audit 2026-05-09

**Overall**:
- Substantively LIVE features: ~30-35 of ~178 (excluding scope-dışı 5)
- Partial coverage: ~25-30 features
- Pending: ~115 features
- Coverage estimate: **~30% v1 scope, ~50% Kernel scope, ~25% MVP-dar scope**

> **Marker discipline (Codex `019e0bff` iter-1)**: Snapshot semantic roll-up'tır, literal matrix değil. ~~Aşağıdaki kategori tablolarındaki literal ☐/🟡/🟢 markerları zaman içinde update edilecek (full pass deferred follow-up; ~178 row sweep).~~ **Update 2026-05-23 (Codex `019e5958` AGREE + `019e5963` REVISE absorb)**: Current literal pass yukarıdaki "Status update 2026-05-23" bloğunda; historical "Semantic roll-up (historical 2026-05-09)" satırları historical kayıt olarak kalır (eski kategori/count dili tarihsel). Current literal row marker'lar ile current evidence aynı yönü gösteriyor; old "10 done vs ~50 semantic" drift kapalı.

---

## 1. Channel Coverage

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| A1 | Email transactional (SMTP canonical; Microsoft Graph API alternate path **deferred** — bkz. §8 H14 + [ADR-0024](../adr/0024-graph-mail-adapter-defer.md)) | **Kernel** | 23.1 | 🟢 |
| A2 | Slack incoming webhook | **Kernel** | 23.1 | 🟢 |
| A3 | Webhook egress (HMAC signed) | **Kernel** | 23.1 | 🟢 |
| A4 | SMS (JetSMS primary) | **MVP-geniş** | 23.3 | 🟢 **FULLY DELIVERED 2026-05-25** (B-with-lanes complete + BL-011 LIVE): M4 prod LIVE 2026-05-20 sha-6307428 + JetSMS primary `SmsAdapter activated` + `JetSmsDlrPollingWorker scheduling=true`; multipart context routing 23.3.2 LIVE; BL-010 prod KC `serban` realm + org_id mapper LIVE (PR #1062); BL-028a Lane A prod DB seed LIVE (PR #1067); BL-028b Lane B prod OpenFGA notification model cutover LIVE (PR #1069); **BL-011 prod SMS canary LIVE DELIVERED 2026-05-25 16:58:45 UTC** (PR #1071 — gerçek SMS +905551815564 → JetSMS `jetsms-2605251959362908914` → DELIVERED 71s DLR; 7/7 acceptance gate PASS). **NetGSM secondary 📦 Out of plan / demand-reactivated** (ADR-0028 2026-05-25; asset-preserved dormant; JetSMS-only kalıcı işletim durumu). |
| A5 | In-app inbox backend API | **MVP-geniş** | 23.3 | 🟢 (LIVE GET /inbox/me + SSE) |
| A6 | In-app inbox React UI (custom) | v1 | 23.4 | 🟢 (PR-5.x cycle LIVE) |
| A7 | Microsoft Teams (Adaptive Cards) | v1 | 23.6 | 🟢 (T4.1.2 LIVE — TeamsWebhookAdapter + Adaptive Card payload builder platform-backend PR #272 MERGED + deployed sha-f40aa82) |
| A8 | Mobile push FCM (Android) | v1.1 (23.7.b patch) | 23.7.b | 🔵 DEFER → [M7.b](milestones.md#m7b--237b-mobile-push-patch--defer-post-faz-222) (Faz 22.2 dep; [R25](risk-register.md) governance; Codex `019e5a59`) |
| A9 | Mobile push APNS (iOS) | v1.1 (23.7.b patch) | 23.7.b | 🔵 DEFER → [M7.b](milestones.md#m7b--237b-mobile-push-patch--defer-post-faz-222) (Faz 22.2 iOS dep; [R25](risk-register.md) governance; Codex `019e5a59`) |
| A10 | Web Push (browser, VAPID) | v1 | 23.7 | 🟢 (**WebPush browser-only LIVE end-to-end 2026-05-23** — PR-W1..W7 + #648/#649 frontend + #652 RTK + #986/#987 deploy + #990 OpenFGA model + #995 model_id cutover + #996 internal-api-key ESO; subscribe browser-proven RB-webpush §3.10 ✅; SUCCESS push delivery proven `notify_dispatch_outcome_total{channel="push",status="DELIVERED"} 1.0` + FCM 201 msg_id RB-webpush §3.11 ✅) |
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
| B3 | Throttle per provider (NetGSM 100/dk) | **Kernel** | 23.1 | 🟡 (provider stub; tuning Faz 23.3 — M3 T1.6 abuse guards LIVE for cross-cutting rate limit) |
| B4 | Retry exponential backoff (max 5 attempt) | **Kernel** | 23.1 | 🟢 (RetryWorker LIVE) |
| B5 | DLQ (manual replay endpoint) | **Kernel** | 23.1 | 🟢 (LIVE + 4 alerts + SLO) |
| B6 | Code-based workflow (Java DSL) | **Kernel** | 23.1 | 🟢 |
| B7 | Multi-step workflow (ardışık adım) | v1 | 23.4 | ☐ |
| B8 | Channel priority/fallback (email→SMS) | v1 | 23.4 | ☐ |
| B9 | Conditional step (rule: `if user.role == admin`) | v1 | 23.4 | ☐ |
| B10 | Delay / Schedule (`scheduled_at`) | v1 | 23.4 | ☐ |
| B11 | Digest (saatlik/günlük gruplandırma) | v1 | 23.8 | ☐ |
| B12 | Throttle per recipient (max N/saat per user) | v1 | 23.4 | 🟡 (M3 T1.6 AbuseGuardService rate limit per source LIVE; per-recipient discriminator scope dar — full N/saat per user pending) |
| B13 | Recurring (CRON) | v2 | 23.X | ☐ |
| B14 | A/B testing (variant) | v2 | 23.X | ☐ |
| B15 | No-code workflow editor UI | v2 | 23.X | ☐ |
| B16 | Fallback channel canary test (gate) | **MVP-dar** | 23.2 | 🟢 **mock-receipt mitigated** (M3 T1.4 23.2.D — BL-008 mock-receipt drill 2026-05-24 dual-receipt evidence (webhook-receiver POST 200 + Mailpit SMTP — same Alertmanager dispatch cycle); Codex `019e5aaf` REVISE absorb; real Slack workspace #853 + prod activation #854 ayrı operator-external) |

## 3. Template Management

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| C1 | Template versioning DB-backed | **Kernel** | 23.1 | 🟢 (V8 partition schema + NotificationTemplate entity LIVE Kernel) |
| C2 | i18n (tr-TR + en-US baseline) | **Kernel** | 23.1 | 🟡 (subscriber.locale field LIVE; template per-locale rendering source-side present, baseline tr-TR canonical kullanılıyor) |
| C3 | Variable interpolation (safe `${user.name}`) | **Kernel** | 23.1 | 🟢 (Thymeleaf template rendering LIVE all 3 Kernel adapters: Email + Slack + Webhook) |
| C4 | Multipart (HTML + plain text) | **Kernel** | 23.1 | 🟢 (Email Multipart LIVE + SMS 23.3.2 multipart context routing LIVE M4 sub-faz 23.3.2 Codex 019e4514) |
| C5 | Test send (admin endpoint) | **Kernel** | 23.1 | ☐ |
| C6 | Subject + body ayrı render | **Kernel** | 23.1 | 🟢 (Thymeleaf subject + body ayrı template LIVE Kernel) |
| C7 | Provider config versioning + rollback | **MVP-dar** | 23.2 | 🟢 (M3 T1.3 23.2.C platform-backend PR #140 MERGED 2026-05-10 — R12 mitigated FULL ACCEPTANCE evidence) |
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
| D1 | Subscriber tablosu (id, email, phone, locale, tz) | **Kernel** | 23.1 | 🟢 (V8 partition schema LIVE Kernel) |
| D2 | External recipient (platform-dışı email/phone) | **Kernel** | 23.1 | 🟢 (intent submission external recipient LIVE Kernel) |
| D3 | Recipient validation (RFC 5322 email + E.164 phone) | **Kernel** | 23.1 | 🟢 (RFC 5322 + E.164 validators LIVE Kernel) |
| D4 | Per-channel preference (email/SMS/in-app/Slack ayrı toggle) | **MVP-dar** | 23.2 | 🟢 (M3 T1.1 23.2.A trilogy MERGED — SubscriberChannelPreference entity LIVE prod; M5 23.5 UI LIVE) |
| D5 | Per-topic preference (drift-alarm yes, system-update no) | **MVP-dar** | 23.2 | 🟢 (M3 T1.1 23.2.A LIVE; M5 G2 backend PreferenceTopicCatalog endpoint PR #269 MERGED `GET /api/v1/notify/topics/me`) |
| D6 | Unsubscribe link (email footer) | **MVP-dar** | 23.2 | 🟢 (M5 G3 platform-web PR #642 public unsubscribe landing `/notifications/unsubscribe` MERGED; email footer link source-side LIVE) |
| D7 | Quiet override (kritik notification bypass) | **MVP-dar** | 23.2 | 🟢 (M3 T1.5 23.2.E data classification security severity bypass LIVE PR #149 9-test acceptance) |
| D8 | Topic flat key + severity (D45 data classification ile birlikte) | **MVP-dar** | 23.2 | 🟢 (M3 T1.5 23.2.E LIVE; M5 G2 topic catalog LIVE) |
| D9 | Multiple addresses per subscriber | v1 | 23.5 | ☐ |
| D10 | Quiet hours (22:00-08:00 sadece kritik) | v1 | 23.5 | 🟢 (M5 23.6 PR-B1 platform-web PR #299 MERGED — `quiet-hours.ts` canonical model + drawer-based rich editor LIVE) |
| D11 | Frequency limit (max N/gün) | v1 | 23.5 | 🟢 (backend `frequency_limit_per_day` + `FrequencyLimitService` LIVE — platform-backend PR #143 + PR #259 acceptance IT MERGED; per-subscriber daily limit enforce LIVE) |
| D12 | One-click unsubscribe (public landing, partial RFC 8058) | v1 | 23.5 | 🟡 (M5 G3 PR #642 public unsubscribe landing `/notifications/unsubscribe` + GET token revoke LIVE; **`List-Unsubscribe-Post` header RFC 8058 ✗ TBD** — see [must-have-checklist.md](must-have-checklist.md) line 264 pending) |
| D13 | Self-service preference UI (mfe-host) | v1 | 23.5 | 🟢 (M5 23.5 platform-web PR #285 + #286 + #288 + #299 + #301 + G2+G3+G4 gap-fill chain MERGED — `/settings/notifications` route + drawer editor + bulk mute + restore-defaults two-stage LIVE) |
| D14 | Subscriber import (CSV/API) | v1 | 23.5 | ☐ |
| D15 | Suppression list (hard-bounce / spam complaint) | v1 | 23.8 | 🟢 (T4.3.b email bounce loop MERGED platform-backend PR #270 `subscriber_email_suppression` table + audit LIVE — sha-f40aa82+; T4.3.5 FBL source-ready PR #298+#299 ArfReportParser+FblService+V22+IMAP polling worker, mailbox operator activation pending RB-fbl-mailbox-activation) |
| D16 | Topic hierarchy | v1 | 23.5 (flat MVP yeter) | ☐ |

## 5. Tenant / Multi-tenancy / Branding

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| E1 | Multi-tenant (org_id boundary) | **Kernel** | 23.1 | 🟢 (D29-Authorized Layer-1 LIVE — JWT `org_id` claim allow HTTP 202 + missing claim deny HTTP 403; Faz 24 PR-5.5 `NOTIFY_SECURITY_DEFAULT_ORG_ID=""` strict cutover LIVE prod; M2 D29-Functional evidence board #754) |
| E2 | Cross-tenant hard-deny (OpenFGA) | **Kernel** | 23.1 | 🟡 (OpenFGA notification model extension safe-phase LIVE 2026-05-22 PR #990; model_id cutover LIVE 2026-05-23 PR #995; subscriber#can_receive topic-inheritance Layer-2 enforce 23.2 v2 rescope per Codex 019e3c74 verdict B — Layer-1 strict isolation LIVE, Layer-2 channel-level subscriber#can_receive Faz 23.2 v2) |
| E3 | Multi-environment (test/prod) | **Kernel** | 23.1 | 🟢 (k3d-test + k3d-prod overlays LIVE — `kustomize/overlays/{test,prod}` env-specific configmaps + ESO ClusterSecretStore LIVE) |
| E4 | Per-tenant brand (logo/color/footer) | v1 | 23.6 | ☐ |
| E5 | Per-tenant template override | v1 | 23.6 | ☐ |
| E6 | Tenant onboarding API | v1 | 23.5 | ☐ |
| E7 | Per-tenant provider config (org X kendi SMTP) | v2 | 23.X | ☐ |
| E8 | Per-tenant rate quota | v2 | 23.X | ☐ |

## 6. Audit / Compliance

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| F1 | Delivery log (per-message audit) | **Kernel** | 23.1 | 🟢 (delivery row INSERT per dispatch LIVE Kernel — Email + Slack + Webhook + SMS + WebPush all writing delivery rows; M2 D29-Functional 3-channel evidence) |
| F2 | PII redaction (log + audit body yok) | **Kernel** | 23.1 | 🟢 (M3 R2 KVKK PR-K4+K7 log redaction MERGED 2026-05-21 — log4j2 redaction rules + audit body redaction LIVE) |
| F3 | Audit retention 90 gün default | **Kernel** | 23.1 | 🟢 (audit retention LIVE Session 39 hardening — Vault/ESO retention policy LIVE prod) |
| F4 | Audit query API | **MVP-dar** | 23.2 | 🟢 (M3 23.2.A audit query LIVE prod — actuator/audit + Grafana query LIVE) |
| F5 | KVKK Art.11 right-to-erasure (API/runbook) | **MVP-dar** | 23.2 | 🟢 (M3 R2 KVKK PR-K1 erasure request ledger + 30-gün SLA + due_at tracking LIVE; M3 23.2.B subscriber self-service + admin erasure LIVE; R2 CLOSED 2026-05-23 Codex `019e5189` final legal verdict) |
| F6 | KVKK Art.13 right-to-information (API) | **MVP-dar** | 23.2 | 🟢 (M3 R2 23.2.B subscriber self-service + GDPR/KVKK Art.13 right-to-information LIVE; R2 CLOSED 2026-05-23) |
| F7 | Data classification policy enforcement | **MVP-dar** | 23.2 | 🟢 (M3 T1.5 23.2.E platform-backend PR #149 9-test acceptance candidate LIVE 2026-05-10 — DeliveryEligibilityService classification-aware enforcement LIVE) |
| F8 | Audit append-only (app-level no-update/delete rule) | **MVP-dar** | 23.2 | 🟢 (audit append-only app-level rule LIVE Kernel) |
| F9 | Activity feed admin (UI) | v1 | 23.5 | 🟢 (M5 platform-web PR #291 mfe-audit delivery logs tab MERGED + #285 admin preferences page) |
| F10 | Subscriber's own delivery history (UI) | v1 | 23.5 | 🟢 (M6a 30-day notification history filter LIVE — Backend V16 inbox history index + FE inbox Geçmiş tab + listHistory RTK MERGED tasks #8+#9) |
| F11 | Export to SIEM (Splunk/ELK/syslog) | v1 | 23.8 | ☐ |
| F12 | Webhook for compliance events | v1 | 23.8 | ☐ |
| F13 | KVKK explicit consent tracking | v1 | 23.5 | 🟡 (M3 R2 KVKK closure provides consent mechanism via preference UI + erasure ledger; explicit consent timestamp/source tracking entity dedicated impl pending) |
| F14 | IYS lookup (TR commercial SMS) | sub-faz drift | D40-IYS | ☐ |
| F15 | DPA (3rd party provider) | sub-faz drift | legal | ☐ |
| F16 | Compliance certifications (SOC 2, ISO 27001) | ✗ scope-dışı | — | ✗ |

## 7. Analytics / Observability

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| G1 | Delivery metrics (Prometheus export) | **Kernel** | 23.1 | 🟢 (`notify_dispatch_outcome_total{channel,status,org_id}` Counter + per-tenant org_id Tag retrofit LIVE prod — B.1 PR #289 MERGED; M7 T4.2 WebPush channel=push status=DELIVERED proven 2026-05-23) |
| G2 | Distributed tracing (correlation_id) | **Kernel** | 23.1 | 🟢 (T4.3.a Tempo OTLP trace export LIVE 2026-05-21 09:17Z; 5 spans verified) |
| G3 | Real-time delivery status API | **MVP-dar** | 23.2 | 🟢 (Kernel SSE LIVE — `/api/v1/inbox/me/stream` Server-Sent Events stable testai + ai.acik.com; cross-pod broadcast PG LISTEN/NOTIFY PR-E.4) |
| G4 | Alertmanager rule (DLQ > N) | **MVP-dar** | 23.2 | 🟢 (25 PrometheusRule LIVE prod — DLQ + abuse storm + drift alarms + per-tenant rules + DLQ SLO 99.5% LIVE) |
| G5 | Grafana dashboard (delivery rate, channel breakdown, DLQ) | **MVP-dar** | 23.2 | 🟢 (Grafana 15-panel LIVE prod Session 39 hardening + per-tenant dashboard PR #951 + per-template analytics PR #966) |
| G6 | Per-channel analytics | v1 | 23.8 | 🟢 (per-channel metric breakdown LIVE via `notify_dispatch_outcome_total` channel label; M7 T4.3 dashboard 8-panel coverage) |
| G7 | Per-template analytics | v1 | 23.8 | 🟢 source-ready (T4.3.7 PR #966 Grafana PG datasource + Top 20 panel + V21 index MERGED — Codex `019e4ee2`; operator DB RO role activation pending) |
| G8 | Per-tenant dashboard | v1 | 23.8 | 🟢 (T4.3.6 PR #951 8-panel per-tenant Grafana dashboard MERGED + B.1 org_id Counter Tag retrofit PR #289 LIVE prod) |
| G9 | Open / click tracking (email — privacy concern) | v1 (opt-in) | 23.8 | ☐ |
| G10 | Real-time delivery status UI | v1 | 23.5 | 🟢 (mfe-audit delivery logs tab platform-web PR #291 MERGED — admin activity feed + per-org delivery status UI LIVE) |

## 8. Provider Management

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| H1 | Provider config env-specific (test/prod) | **Kernel** | 23.1 | 🟢 (`kustomize/overlays/{test,prod}` ConfigMap env-specific + ESO ClusterSecretStore env-specific Vault path LIVE Kernel) |
| H2 | Provider rate limit (orchestrator-side) | **Kernel** | 23.1 | 🟡 (M3 T1.6 AbuseGuardService cross-cutting rate limit LIVE; per-provider explicit rate limit knob source-side present, full per-provider tuning gevşek) |
| H3 | Provider config versioning (rollback) | **MVP-dar** | 23.2 | 🟢 (M3 T1.3 23.2.C platform-backend PR #140 MERGED 2026-05-10 — R12 mitigated FULL ACCEPTANCE) |
| H4 | DKIM/SPF/DMARC config (sub-faz 23.2) | **MVP-dar** | 23.2 (runbook) | 🟡 (DKIM relay strategy LIVE prod via Office 365 Native CNAME pattern — PR-B1 platform-backend #268 + gitops #914+#915+#916 MERGED 2026-05-20; **DNS CNAME publish + Office 365 admin tenant enable operator-gated**; SPF + DMARC operator DNS publish ext-gated) |
| H5 | DLR / delivery callback (SMS) | v1 | 23.4 | 🟢 (T3.1.7 callback endpoint test/mock live-verified Session 44 — backend PR #85 + api-gateway PR #154 + gitops PR #514 MERGED + mock provider 5/5 acceptance gates `docs/faz-23-evidence/2026-05-11-t3-1-7-dlr-live-smoke-pass.md`; JetSMS-primary prod path + `JetSmsDlrPollingWorker scheduling=true` LIVE prod sha-6307428; NetGSM webhook leg dormant per R1 ⏳ DEFER) |
| H6 | Multi-provider per channel | v1 | 23.4 | 🟢 (M4 SmsAdapter facade + JetSmsProvider + NetGsmProvider abstraction LIVE prod — `SmsAdapter activated: primary=jetsms registered=[netgsm, jetsms]`; M3 SMTP + Slack + Webhook adapters LIVE Kernel) |
| H7 | Provider failover (primary fail → secondary) | v1 | 23.4 | 🟡 (SmsAdapter failover code-path LIVE source-side; **NetGSM secondary R1 ⏳ DEFER asset-preserved** per kullanıcı kararı 2026-05-23 — sözleşme kısa vadede yok; failover acceptance test sözleşme imzalanırsa reactivation; JetSMS-only degraded mode kabul edilen kalıcı işletim durumu) |
| H8 | Provider health check (sandbox cron) | v1 | 23.8 | ☐ |
| H9 | Bounce handling (email) | v1 | 23.8 | 🟢 (T4.3.b email bounce loop platform-backend PR #270 MERGED 2026-05-21 — `subscriber_email_suppression` + audit + bounce categorization LIVE sha-f40aa82+) |
| H10 | Spam complaint feedback loop | v1 | 23.8 | 🟢 source-ready (T4.3.5 FBL platform-backend PR #298 ArfReportParser+FblService+V22 + PR #299 FblMailboxPollingWorker IMAP MERGED; mailbox operator activation pending RB-fbl-mailbox-activation) |
| H11 | IP allowlist per provider | v1 | 23.8 | ☐ |
| H12 | Provider cost tracking | v2 | 23.X | ☐ |
| H13 | IP rotation (email reputation) | v2 | 23.X | ☐ |
| H14 | Microsoft Graph mail adapter activation path (Office 365 Graph REST API, port 443; alternate to SMTP 587) | future-proofing | 23.X / v1.x | 🟡 **deferred** (SMTP canonical; Entra `acik-mail-graph-api` app reg + Mail.Send + admin consent **asset preserved**; client_secret + ApplicationAccessPolicy + Vault `graph_*` seed + ConfigMap flag flip + digest bump + smoke send 5-adım atomic reactivation chain documented in [ADR-0024](../adr/0024-graph-mail-adapter-defer.md) + [RB-graph-mail-adapter-activation.md](../runbooks/RB-graph-mail-adapter-activation.md) + board [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) P3 Backlog future-only; reactivation triggers: Microsoft App Password deprecation / SMTP AUTH tenant policy break / outbound 587 ISP block recurrence / ops-security tactical decision / provider migration; R23 active monitored) |

## 9. Developer Experience

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| I1 | REST API | **Kernel** | 23.1 | 🟢 (REST API LIVE Kernel — `/api/v1/notify/intent` + `/inbox/me` + `/preferences` + `/topics/me` + `/push-subscriptions` LIVE) |
| I2 | Java SDK (internal) | **Kernel** | 23.1 | 🟡 (internal callers use REST API directly; dedicated Java SDK package not yet extracted) |
| I3 | OpenAPI spec (Springdoc) | **Kernel** | 23.1 | 🟢 (Springdoc LIVE Kernel — `/v3/api-docs` + `/swagger-ui` endpoints LIVE) |
| I4 | Idempotency key support | **Kernel** | 23.1 | 🟢 (`Idempotency-Key` header LIVE Kernel — IntentSubmissionService idempotency-aware) |
| I5 | Sandbox mode (test profile) | **Kernel** | 23.1 | 🟢 (k3d-test cluster acts as sandbox — full pre-prod with same overlay structure + ESO ClusterSecretStore + Vault path canonical) |
| I6 | Mock provider (Mailpit + WireMock) | **Kernel** | 23.1 | 🟢 (Mailpit test/dev mock + WireMock IT tests in CI LIVE — `DefaultWebPushSenderHttpIntegrationTest` PR #281 + JetSMS IT. **Prod email relay Office 365 SMTP canonical**, Mailpit not prod-path) |
| I7 | JS / TS SDK (mfe-host için) | v1 | 23.4 | 🟡 (RTK Query client `notify-prefs.api.ts` + `notify-push.api.ts` + `notify-inbox.api.ts` LIVE for mfe-host; dedicated standalone TS SDK package not yet extracted) |
| I8 | Webhook ingress (event from external) | v1 | 23.6 | ☐ |
| I9 | Bulk API (1000 recipient batch) | v1 | 23.4 | ☐ |
| I10 | CLI tool | v2 | 23.X | ☐ |
| I11 | Other SDK (Python/Go/Ruby) | ✗ scope-dışı | — | ✗ |

## 10. UI / Self-service

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| J1 | Preference settings UI (mfe-host) | v1 | 23.5 | 🟢 (M5 23.5 LIVE — platform-web PR #285 PR3 preferences UI + RTK Query client; `/settings/notifications` route LIVE; M5 6/6 LIVE per sprint-plan T3.2) |
| J2 | In-app inbox UI (React component) | v1 | 23.4 | 🟢 (M6a + M6b 6/6 LIVE 2026-05-20 board #758 — mfe-host inbox React component LIVE testai + ai.acik.com; SSE stream stable; PR-5.x cycle) |
| J3 | Mark as read / unread | v1 | 23.4 | 🟢 (M6a inbox read/unread toggle LIVE; bulk mark-all-read platform-web PR #286 MERGED) |
| J4 | Archive / delete | v1 | 23.4 | 🟢 (M6a archive UI button platform-web PR #626 + M6a chain MERGED — sprint-plan T2.2.1 task #12) |
| J5 | Notification history (son 30 gün) | v1 | 23.4 | 🟢 (M6a notification history filter LIVE — Backend V16 inbox history index + tests task #8; FE inbox Geçmiş tab + listHistory RTK task #9 MERGED) |
| J6 | Real-time WebSocket badge (unread count) | v1 | 23.4 | 🟢 (real-time WS replaced with SSE — PR-E.4 cross-pod broadcast PG LISTEN/NOTIFY LIVE; inbox unread count LIVE) |
| J7 | Search / filter inbox | v1 | 23.5 | ☐ |
| J8 | Browser push permission banner | v1 | 23.7 | 🟢 (WebPush UI button integration LIVE — PR-W5 mfe-shell service worker + subscribe UI + PR #648/#649 frontend integration MERGED; OP.1 browser-proven subscribe akışı RB-webpush §3.10 ✅) |
| J9 | Admin: template editor UI | v1 | 23.5 | ☐ |
| J10 | Admin: subscriber browser | v1 | 23.5 | ☐ |
| J11 | Admin: workflow editor UI (no-code) | v2 | 23.X | ☐ |

## 11. Security / Trust

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| K1 | TLS in-transit (provider call) | **Kernel** | 23.1 | 🟢 (TLS-only egress LIVE Kernel — all provider calls (SMTP TLS, Slack/Webhook HTTPS, FCM HTTPS, JetSMS SOAP HTTPS) TLS-enforced) |
| K2 | Webhook HMAC signing (egress) | **Kernel** | 23.1 | 🟢 (HMAC-signed webhook egress LIVE Kernel — M2 D29-Functional 3-channel evidence Webhook HMAC delivery row INSERT) |
| K3 | Vault/ESO provider credentials | **Kernel** | 23.1 | 🟢 (Vault + ESO ClusterSecretStore `vault-platform-gitops` LIVE Kernel — all provider creds via ExternalSecret remoteRef) |
| K4 | Encryption at rest (PG) | infra prereq | platform | ☐ |
| K5 | OpenFGA scope (subscriber#can_receive) | **Kernel** | 23.1 | 🟡 (OpenFGA notification model extension safe-phase LIVE PR #990 + model_id cutover LIVE PR #995 — `subscriber#can_receive @ template` topic-inheritance resolves; Layer-2 channel-level enforce 23.2 v2 rescope per Codex 019e3c74) |
| K6 | API key rotation runbook | **MVP-dar** | 23.2 | 🟡 (Vault rotation pattern present; dedicated rotation runbook artifact pending) |
| K7 | Rate limit per source (DDoS protection) | **MVP-dar** | 23.2 | 🟢 (M3 T1.6 AbuseGuardService rate limit per source LIVE prod — RB-notify-abuse-guard runbook + NotifyAbuseStorm PrometheusRule alert; T1.6.5 + T1.6.6 MERGED Session 41) |
| K8 | Webhook signature verification (ingress) | **MVP-dar** | 23.2 | ☐ |
| K9 | Audit log integrity (append-only) | **MVP-dar** | 23.2 | 🟢 (audit append-only app-level rule LIVE Kernel; F8 LIVE) |
| K10 | IP allowlist | v1 | 23.8 | ☐ |
| K11 | Vault dynamic secrets (TTL token) | v2 | 23.X | ☐ |

## 12. Deliverability + Sender Reputation (D45 yeni kategori)

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| L1 | DKIM signed email (sub-faz runbook) | **MVP-dar** | 23.2 | 🟢 source-ready (DKIM relay strategy LIVE prod via Office 365 Native CNAME pattern — PR-B1 platform-backend #268 + gitops #914+#915+#916 MERGED 2026-05-20; DNS CNAME publish + Office 365 admin tenant enable operator-gated) |
| L2 | SPF record (sub-faz runbook) | **MVP-dar** | 23.2 | ☐ (operator DNS publish ext-gated) |
| L3 | DMARC policy (sub-faz runbook) | **MVP-dar** | 23.2 | ☐ (operator DNS publish ext-gated) |
| L4 | Bounce categorization (hard/soft/transient) | v1 | 23.8 | 🟢 (T4.3.b email bounce loop platform-backend PR #270 MERGED 2026-05-21 — `subscriber_email_suppression` table + audit + bounce category classification LIVE sha-f40aa82+) |
| L5 | Spam complaint rate monitor | v1 | 23.8 | 🟢 source-ready (T4.3.5 FBL platform-backend PR #298 ArfReportParser + FblService + V22 + PR #299 FblMailboxPollingWorker IMAP MERGED — Codex `019e4edd`/`019e4fc6`/`019e4ffd`; 28 unit test; mailbox operator activation pending RB-fbl-mailbox-activation) |
| L6 | Delivery reputation per IP/domain | v1 | 23.8 | ☐ |
| L7 | Sender reputation drift detection | v1 | 23.8 | ☐ |

## 13. Abuse / Spam / Recipient Safety (D45 yeni kategori)

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| M1 | Rate limit per source service | **MVP-dar** | 23.2 | 🟢 (M3 T1.6 AbuseGuardService rate limit per source LIVE prod — Session 41 FULL ACCEPTANCE; RB-notify-abuse-guard runbook + NotifyAbuseStorm PrometheusRule alert) |
| M2 | Duplicate flood detection (same template + same recipient + 5dk) | **MVP-dar** | 23.2 | 🟢 (M3 T1.6 AbuseGuardService duplicate flood detection LIVE — R13 + R19 mitigated; T1.6.6 AbuseGuard Service IT MERGED Session 41) |
| M3 | Webhook fan-out cap (max N targets) | **MVP-dar** | 23.2 | 🟡 (M3 T1.6 cross-cutting abuse guards present; webhook fan-out specific cap discriminator scope dar — likely needs explicit verification) |
| M4 | Tenant abuse detection (anomalous send rate) | v1 | 23.8 | ☐ |
| M5 | Recipient block list (suppression) | v1 | 23.8 | 🟡 (email-only suppression LIVE via D15 / L4 / L5 — T4.3.b PR #270 `subscriber_email_suppression` + T4.3.5 FBL source-ready; generic/manual all-channel recipient block list semantic pending) |

## 14. Accessibility (WCAG) (D45 yeni kategori)

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| N1 | Email template plain text alternative (multipart) | **Kernel** | 23.1 | 🟢 (Email Multipart HTML + plain text LIVE — see C4 §3 Templates: Email Multipart LIVE + SMS 23.3.2 multipart) |
| N2 | Email template basic readability (heading hierarchy, alt text) | **MVP-dar** | 23.2 | ☐ |
| N3 | In-app inbox keyboard navigation | v1 | 23.4 | ☐ |
| N4 | In-app inbox screen-reader compatibility | v1 | 23.4 | ☐ |
| N5 | Preference UI ARIA labels | v1 | 23.5 | ☐ |
| N6 | Color contrast WCAG AA | v1 | 23.5 | ☐ |
| N7 | Unsubscribe link accessibility | v1 | 23.5 | ☐ |

## 15. Incident / Degraded Mode (D45 yeni kategori)

| # | Özellik | Tier | Sub-faz | Status |
|---|---|---|---|:---:|
| O1 | Outage fallback bypass (Alertmanager direct, orchestrator bypass) | **MVP-dar** | 23.2 | 🟢 **mock-receipt mitigated** (M3 T1.4 23.2.D — first controlled drill 2026-05-10 Mailpit SMTP-only; BL-008 mock-receipt drill 2026-05-24 Codex `019e5aaf` REVISE absorb test cluster DUAL receipt evidence (webhook-receiver POST `/slack-mock` 200 + Mailpit SMTP — same Alertmanager dispatch cycle); 10/10 mock-receipt criteria PASS; route narrowing + permanent netpol). Real Slack workspace webhook board #853 + prod activation board #854 (prod values-prod.yaml `auth_*_file` Operator v0.90.1 schema gap fix #854 kapsamında) ayrı operator-external action. |
| O2 | Notification-orchestrator down → Slack #alerts direct | **MVP-dar** | 23.2 | 🟢 **mock-receipt mitigated** (T1.4 BL-008 mock-receipt drill 2026-05-24 dual-receipt evidence; real test workspace webhook + prod activation board issues #853 + #854 ayrı operator-external) |
| O3 | Drift alarm ↔ Alertmanager direct redundant chain | **MVP-dar** | 23.2 | 🟡 (Alertmanager rules LIVE; redundant chain partial — T1.4 closure scope) |
| O4 | Break-glass audit ↔ Alertmanager direct redundant chain | **MVP-dar** | 23.2 | 🟡 (Alertmanager rules LIVE; redundant chain partial — T1.4 closure scope) |
| O5 | RB-notification-outage-fallback runbook | **MVP-dar** | 23.2 | 🟢 (runbook source-side LIVE — `docs/runbooks/RB-notification-outage-fallback.md`; BL-008 mock-receipt drill 2026-05-24 per runbook + runbook §2.1 + §3.2 + Step 6 + §6.5.8 BL-008 absorb truth-sync update) |
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
5. **Faz 2 board linkage (2026-05-17)** — Aktif çalışmaya alınan özellik [platform Roadmap board](https://github.com/users/Halildeu/projects/2)'da issue alır; feature satırı `tracked by #N` notu taşır. Row-level `Status` marker tek başına PM progress sayılmaz — canonical aktif-iş durumu board issue'sundadır.
