# ADR-0013 — Notification Orchestration Platform

> **Status**: DRAFT (Faz 23.0 charter — plan-time consensus 2026-05-05; user onay 2026-05-05)
> **Date**: 2026-05-05
> **Sprint**: Faz 23.0 (charter + ADR + event contract + ladder + roadmap + feature matrix + must-have checklist)
> **Codex thread**: `019df86f-89aa-7200-bb6c-b7b903860148` (REVISE-then-AGREE; 10-aday kıyas tablosu, custom Spring Boot baseline 9/10 skor; 4-tier ayrımı + 12 v1-taşıma + 5 yeni kategori + 10 must-have çizgisi mühürlendi)
> **Predecessors**: ADR-0002 (single-host dual-cluster), ADR-0010 (vault credential lifecycle), ADR-0011 (drift detection + audit cadence + boundary governance), ADR-0012-EA (endpoint-admin governance)
> **Related artifacts**:
> - `docs/notify/event-contract.md` — Notification intent contract spec
> - `docs/notify/feature-matrix.md` — 11 kategori × tier × özellik canlı tracker
> - `docs/notify/must-have-checklist.md` — 10 must-have çizgisi detay
> - `docs/runbooks/RB-faz-23-charter.md` — Sub-faz roadmap takip tablosu

## Bağlam

Platform üzerinde **çok-kanallı transactional bildirim** ihtiyacı 6+ yüzeyde birikti:

| Kaynak yüzey | İhtiyaç | Mevcut çözüm |
|---|---|---|
| Drift alarm-receiver (Sprint A P0 #6) | GitHub issue + email + Slack alert | Sadece GitHub issue + persistent log + webhook fallback (PR #347) |
| Admin onboarding saga (Sprint D prep PR #350) | Invite mail | Henüz yok — saga contract scaffold, delivery layer açık |
| Password reset 4 connector (Faz 22 ADR-0012-EA) | Email reset link (Local connector) + opsiyonel SMS OTP | Henüz yok |
| Break-glass token issuance audit (Sprint C PR #352) | Operasyon ekibine notification | Best-effort GitHub issue + audit log (`break-glass-token.sh`) |
| Endpoint-admin agent (Faz 22) | Operatör command result + heartbeat-fail alert | Henüz yok |
| Pilot/restricted device enrollment (Faz 22.2 EndpointPilot) | IT operatörüne enrollment notification | Henüz yok |

Şu an her servis kendi delivery'sini ad-hoc çağırıyor; **standart contract yok**, **audit/retry/idempotency/preference sahibi yok**, **outage fallback** tanımlı değil. Faz 23 bu gap'i kapatır.

### Codex plan-time istişare özeti (üç tur)

İlk öneri **Novu** (Apache 2.0, NestJS/TS, Mongo+Redis+RabbitMQ) idi. Codex `019df86f` üç tur REVISE verdict ile karşı çıktı:

**Tur 1 — Stack kararı**:
1. **Stateful explosion**: 3 yeni stateful sistem (Mongo+Redis+RabbitMQ) ADR-0002 §7.1 single-host 400GB disipliniyle uyumsuz; backup/restore + DR matrisi 3 kat büyür.
2. **Ekosistem yabancı**: TypeScript/NestJS, Java ekibi sürdürülebilirlik açısından düşük.
3. **Workflow editor değer üretmiyor**: ihtiyaç **programmatic transactional**, no-code yüzeyi gereksiz.
4. **TR SMS provider TS plugin yerine native Java adapter** daha doğru.
5. **Kendi outage'ında self-alerting riski**: Novu down olduğunda alarm gönderemez.

**Tur 2 — 10-aday kıyas tablosu skor**:
- **Custom Spring Boot `notification-orchestrator` — 9/10** ← seçilen
- Apache Camel + Spring Boot — 8 (içeride opsiyonel adapter/routing kütüphanesi)
- SendGrid + Twilio + Slack ayrı — 7 (orchestration yine custom)
- Novu / Knock / Courier — 6 (deferred lab/evaluation)
- AWS SNS+Pinpoint / Postal — 5 (cloud lock-in / email-only)
- Twilio Engage — 4 (yanlış ürün sınıfı)
- Cuttlefish — 3 (AGPL + email-only)

**Tur 3 — Özellik kapsamı revize**:
- "60 özellik MVP" yanlış çerçeveydi — production v1'e yakın kapsam
- Doğru ayrım: **Kernel/Closed Beta → Production MVP → v1 → v2** (4-tier)
- 12 özellik MVP'den v1'e taşındı (SMS full, in-app inbox UI, topic hierarchy, preference UI, vb.)
- 5 yeni kategori eklendi (Deliverability, Abuse/spam, Accessibility, Incident/degraded, Data classification)
- 10 must-have çizgisi mühürlendi (production MVP demek için olmazsa olmaz)

## Karar (DRAFT)

### D38 — Orchestration Baseline = Custom Spring Boot (atomik)

`notification-orchestrator` Spring Boot servisi `platform-backend` repo'sunda yeni sub-dir:

```
platform-backend/
  notification-orchestrator/
    src/main/java/com/serban/notify/
      api/                 # REST controller (POST /api/v1/notify/intents)
      domain/              # NotificationIntent, NotificationDelivery, Template, SubscriberPreference
      adapter/             # SmtpAdapter, SmsAdapter (NetGsm), SlackAdapter, InAppAdapter, WebhookAdapter, PushAdapter
      worker/              # OutboxPoller, RetryWorker, DeadLetterMover
      template/            # TemplateRenderer (Thymeleaf), version resolver
      preference/          # SubscriberPreferenceService, opt-out enforcement
      audit/               # AuditEventPublisher (PII redaction)
      config/              # ProviderConfig, ChannelConfig, RateLimiter
      classification/      # DataClassification + critical bypass policy (D45 yeni kategori)
      abuse/               # AbusePreventionGuard (D45 yeni kategori)
      incident/            # OutageFallbackBypass (D43)
```

**Stateful**: **PostgreSQL only** (yeni `notify_db` schema). Mongo / Redis / RabbitMQ **YASAK**.

**Authz**: mevcut `permission-service` Zanzibar plane'i kullanır; ayrı OpenFGA store değil.

**Provider abstraction**:
- `ChannelAdapter` interface: `send(NotificationIntent, RenderedMessage) → DeliveryAttemptResult`
- `SmsProvider` interface: `send`, `queryDelivery`, `normalizeError`, `supportsUnicode`, `senderId`
- `SmtpProvider` interface: `send`, `verifyConnection`, `getQueueDepth`

**Novu / Knock / Courier**: Faz 23 production line'ı **DEĞİL**. Lab/evaluation candidate olarak kalır.

### D39 — Stateful = Postgres-Only (atomik)

```
notify.notification_intent          # gelen intent (idempotency_key + payload)
notify.notification_delivery        # her kanal için delivery attempt
notify.notification_template        # versionable template (template_id + version + body + locale)
notify.subscriber_preference        # user/topic/channel preference (opt-in/opt-out)
notify.provider_config              # provider seçim (production/test environment ayrı)
notify.provider_config_history      # rollback için (D44 minimal)
notify.audit_event                  # PII-redacted audit trail (90/180 gün retention)
notify.dead_letter                  # max retry exceeded; manual replay
notify.outbox                       # domain-side per-service outbox veya central event store
```

Outbox pattern: domain service'ler **direct provider çağırmaz**.

### D40 — TR SMS Provider = Native Java Adapter (atomik kontrat; **tier v1**)

NetGSM / İletimerkezi / Mutlucell adapter'ları Spring Boot içinde Java client. Kararlar:
- Provider interface ortak: `SmsProvider`
- İlk implementation: **NetGSM primary**, **İletimerkezi secondary**
- Failover policy: pre-accept fail otomatik secondary; kabul belirsiz manuel
- DLR (Delivery Receipt) callback endpoint
- GSM-7/UCS-2 segment, Türkçe karakter, sender ID kayıt
- IYS (İleti Yönetim Sistemi) lookup: ticari mesaj zorunlu, OTP/transactional muaf — **sub-faz drift D40-IYS**

**Tier**: SMS **MVP-geniş (Faz 23.3)** — D44 channel coverage tier authoritative. SMS DLR callback ingestion v1 (Faz 23.4). MVP-dar (23.2)'de SMS yok. Kernel/Closed Beta (23.1)'de email + Slack + webhook + outbox + retry/DLQ + audit + OpenFGA + PII + metrics + Mailpit/WireMock.

### D41 — Multi-Tenancy Boundary = `org_id + OpenFGA` (atomik)

`subscriber:<userId>#can_receive notification_topic:<key>` OpenFGA tuple'ı kullanılır. Subscriber-tag authority **yetmez** — OpenFGA otoriter.

`notification_intent.org_id` first-class column. Cross-org notification isteği reddedilir (deny default).

### D42 — KVKK / GDPR Disiplin (atomik)

- **Açık rıza**: ticari/marketing kapsam dışı (Faz 23 sadece transactional)
- **Opt-out**: subscriber `notification_preference` üzerinden kanal başına; KVKK 11. madde "veri işlemeyi durdurma"
- **PII redaction**: log'larda mail body / SMS body **maskelenmiş**; sadece `template_id`, `recipient_hash` (sha256), `org_id`, `correlation_id`, `delivery_status`
- **Retention**: `audit_event` 90 gün default (sub-faz drift — ops/legal kararı 30/90/180/365 arasında)
- **Right to erasure (Art.11)**: subscriber silme talebinde audit'te recipient_hash kalır, payload purge edilir — **API/runbook MVP**, UI v1
- **Right to information (Art.13)**: subscriber kendi geçmişini görebilir — **API MVP**, UI v1
- **DPA**: 3rd party provider (SendGrid/Twilio/AWS) kullanılırsa veri işleyici sözleşmesi (sub-faz drift adayı)

### D43 — Outage Fallback Bypass (atomik — Codex kritik bulgu)

`notification-orchestrator` **kendi outage'ında alarm gönderemez**. Bu yüzden:

- **Drift alarm-receiver, break-glass audit, kritik ops alarmı için Alertmanager → direct SMTP/Slack fallback** ayrı katman olarak tutulur (`monitoring/alertmanager` config).
- Bu fallback notification-orchestrator'dan **bağımsız**: kendi SMTP credential'ı ESO ile sync, kendi Slack webhook'u ESO ile sync.
- Notification-orchestrator down → Alertmanager direct kanal üzerinden ops ekibe bildirir.
- "Notification-service down" alarmı kendi içinden değil, Prometheus liveness probe + Alertmanager rule'undan gelir.

### D44 — Channel Coverage Tier (atomik tier; provider sub-faz)

| Tier | Kanal | Sub-faz |
|---|---|---|
| **Kernel/Closed Beta** | Email transactional + Slack incoming webhook + Webhook egress (3 kanal) | 23.1 |
| **Production MVP dar** | + provider abstraction + preference API + erasure path + alerting | 23.2 |
| **Production MVP geniş** | + SMS (NetGSM) + In-app inbox **backend API** | 23.3 |
| **v1** | + SMS DLR + In-app inbox **full UI** + Microsoft Teams + Web Push + FCM/APNS | 23.4-23.8 |
| **v2** | + WhatsApp Business + Voice/IVR + PWA desktop + A/B testing + No-code workflow editor | future |
| **DIŞI** | Email newsletter/marketing + RCS + Apple/Google Business Chat | — |

### D45 — 5 Yeni Kategori (atomik — Codex eklemesi)

| Kategori | Tier | Açıklama |
|---|---|---|
| **Deliverability + sender reputation** | v1 (bazı email kontrolleri MVP) | "Send edildi" ≠ "ulaştı"; bounce, spam complaint, DKIM/SPF/DMARC drift, sender reputation izlenmeli |
| **Abuse / spam / recipient safety** | **MVP** | Yanlış loop, bulk flood, duplicate send, tenant abuse, webhook fan-out patlaması engellenmeli |
| **Accessibility (WCAG)** | v1 (temel template okunabilirliği MVP) | In-app inbox + preference UI + email template + unsubscribe akışları erişilebilir |
| **Incident / degraded mode** | **MVP** | Outage fallback bypass — drift/break-glass notification-service'e bağımlı kalamaz |
| **Data classification** | **MVP** | Transactional/Security/Commercial/System notification ayrımı; opt-out + retention + critical bypass policy bu ayrıma bağlı |

### D46 — 10 Must-Have Çizgisi (atomik — production MVP demek için olmazsa olmaz)

Detay: `docs/notify/must-have-checklist.md`. Özet:

| # | Must-have | Negotiable mi? |
|---|---|:---:|
| 1 | Notification intent + delivery log schema (`org_id`, `topic_key`, `recipient`, `template_version`, `status`, `correlation_id`) | ✗ |
| 2 | Idempotency + dedupe — retry/saga replay duplicate üretmemeli | ✗ |
| 3 | Domain-side outbox contract — admin invite/drift/break-glass direct provider çağırmaz | ✗ |
| 4 | Retry exponential backoff + DLQ + manual replay | ✗ |
| 5 | OpenFGA hard-deny + org boundary — cross-tenant leak kapatır | ✗ |
| 6 | Vault/ESO provider credentials + no secret logging | ✗ |
| 7 | PII redaction + retention/anonymization policy (KVKK) | ✗ |
| 8 | Preference/opt-out model + critical bypass policy (security notification quiet'i geçer) | ✗ |
| 9 | Template versioning + safe interpolation | ✗ |
| 10 | Observability + fallback (Prometheus + DLQ alert + correlation_id tracing + notification-service bypass for drift/break-glass) | ✗ |

**Negotiable**: kanal sayısı, workflow editor, brand customization, A/B testing, in-app inbox UI.

### D47 — Süre Tahmini ve Tier Sequencing (atomik)

| Tier | Kapsam | Süre (1 senior Java + 0.5 frontend + 0.5 ops) |
|---|---|---:|
| Faz 23.0 (Charter) | ADR + 5 artifact + 8 OQ resolve | **1 hafta** |
| Faz 23.1 (Kernel/Closed Beta) | Email + Slack + webhook + PG outbox + retry/DLQ + template versioning + audit + OpenFGA + PII redaction + metrics + Mailpit/WireMock | **3-4 hafta** |
| Faz 23.2 (Production MVP dar) | + preference API + erasure path + provider config versioning + Grafana/alerts + fallback bypass | **2-3 hafta** |
| Faz 23.3 (Production MVP geniş) | + SMS (NetGSM primary) + in-app inbox **backend API** | **3 hafta** |
| Faz 23.4-23.8 (v1) | + SMS DLR + in-app full UI + preference UI + Teams + push + analytics dashboard + bounce/spam loop | **+4-6 hafta** |
| Faz 23.9 (Prod cutover) | k3d-prod + 72h observation | **1 hafta** |
| Faz 23.X (v2 later) | + A/B + workflow editor + WhatsApp + voice + per-tenant provider | **+8-12 hafta** |

**Toplam**: Charter → Production MVP geniş = **9-11 hafta**; v1 stable + prod cutover = **+5-7 hafta**; total **14-18 hafta** (3.5-4.5 ay).

## Sub-faz Drift Adayları (atomik değil, Faz 23 içinde tartışılır)

| Drift adayı | Sub-faz |
|---|---|
| SMTP delivery layer (Postal vs corporate relay vs SendGrid) | 23.2 |
| SMS provider primary vs secondary order (NetGSM vs İletimerkezi) | 23.3 |
| In-app inbox UI library | 23.5 |
| Audit retention süresi (30/90/180/365) | ops + legal |
| Provider failover policy detay | implementation |
| Push provider sıralama (FCM/APNS/HMS) | 23.7 |
| IYS (TR commercial SMS) lookup | D40-IYS sub-faz |
| Vault dynamic secret TTL | v2 |

## D29-NOTIFY / D35-NOTIFY / D30-NOTIFY / BG-NOTIFY-1 Ladder

### D29-NOTIFY — Up + Functional + Authorized/Audited (kanal başına ayrı mezuniyet)

**D29-NOTIFY-Up** (orchestrator level):
- Pod Ready
- `/actuator/health/readiness` 200
- DB migration (V1+ notify schema) applied
- Vault/ESO secret sync OK (provider credentials)
- Outbox poller alive (poll cycle log < 60s gap)
- Queue depth < threshold (DLQ count = 0)

**D29-NOTIFY-Functional per channel** (her kanal **AYRI**):
- Email: template render OK + SMTP test recipient delivery (Mailpit lab; corporate relay test mailbox prod). **DKIM**: Kernel (23.1) Mailpit dev DKIM signing yeter; production DKIM/SPF/DMARC config 23.2 (MVP-dar) sub-faz runbook'unda aktive edilir. Kernel D29-Functional **DKIM live infra'ya takılmaz**.
- SMS: template render + provider sandbox/canary number → DELIVERED status
- In-app: WS connection + test subscriber inbox row INSERT + read receipt
- Slack: incoming webhook 200 + message visible in test channel
- Push: FCM dry-run / APNS sandbox token → success
- Webhook: HMAC-signed POST → 2xx response

**D29-NOTIFY-Authorized/Audited**:
- OpenFGA `subscriber:<id>#can_receive notification_topic:<key>` allow case PASS
- Same case **deny** (preference opt-out OR no tuple) → not delivered + audit row
- PII redaction kanıt: log entry'de payload yok, sadece hash
- Audit row in `notify.audit_event` for every send (success + fail)

### D35-NOTIFY — Live Scoped E2E (D29'dan ayrı kapı)

Real user action → source domain outbox → notification intent → orchestrator pickup → template render → provider accepted → delivery receipt/bounce → audit query → opt-out blocks → retry/DLQ zero-failed.

11 step canlı kanıt template:
1. User triggers domain action (örn. password reset request)
2. Domain service writes outbox row (`outbox.event_type = "PasswordResetRequested"`)
3. Outbox poller picks up (≤2s)
4. NotificationIntent INSERT (`notify.notification_intent`)
5. Template resolved by `template_id + locale`
6. Subscriber preference checked (opt-in OR no opt-out)
7. OpenFGA `can_receive` check
8. Provider selected by config (primary)
9. Delivery attempt → provider response
10. DeliveryAttempt row INSERT (status, provider_msg_id)
11. Audit row INSERT (PII-redacted)

**Negatif kanıt** (zorunlu):
- Aynı `idempotency_key` ile second intent → no duplicate delivery
- Subscriber opt-out → no delivery + audit `BLOCKED_BY_PREFERENCE`
- OpenFGA deny → no delivery + audit `BLOCKED_BY_AUTHZ`
- Provider primary fail (5xx) → secondary accepted → audit chain
- Max retry exceeded → DLQ row + alert

### D30-NOTIFY — Atomic Cutover Discipline

- Image digest pin (`@sha256:<digest>`)
- Pod imageID == GHCR digest match
- Provider config version pin (`provider_config.version` immutable per env)
- Atomic provider switch (DB row update + cache invalidate; no rolling read-write split)
- Previous provider config rollback-ready (`provider_config_history` table)
- Duplicate replay guard: idempotency_key window 24h
- 72h observation for prod channel activation (yeni kanal/provider)

### BG-NOTIFY-1 — PR Boundary Declaration

Mevcut ADR-0011 BG-1 pattern'in `user-communication` boundary class'ı eklenir:

| Boundary class | Açıklama |
|---|---|
| `user-communication` | Prod template/workflow/audience/provider değişikliği |

PR template:
- Blast radius (kaç kullanıcıya gider)
- Sample render (test recipient'a gönderilmiş kanıt)
- Recipient class (org_id, role, region)
- Opt-out effect (preference değişimi var mı)
- Approval evidence (`user-approval-required` label)
- Rollback strategy (template version revert + provider config revert)

## Source Ownership Matrix

| Component | Repo | Path |
|---|---|---|
| Backend orchestrator | `Halildeu/platform-backend` | `notification-orchestrator/` |
| GitOps manifest | `Halildeu/platform-k8s-gitops` (bu repo) | `kustomize/base/apps/notification-orchestrator/` |
| In-app inbox MFE | `Halildeu/platform-web` | `apps/mfe-notification-inbox/` (yeni MFE) |
| Templates (Thymeleaf) | `Halildeu/platform-backend` | `notification-orchestrator/src/main/resources/templates/` |
| ESO secret manifest | `Halildeu/platform-k8s-gitops` | `kustomize/overlays/{test,prod}/eso/notify/` |
| Vault path | (ops, runtime) | `kv/platform/notify/{provider}` |

## Sub-faz Roadmap (özet — detay `docs/runbooks/RB-faz-23-charter.md`)

| # | Sub-faz | Tier | Süre | Bağımlılık | Kabul kriteri (özet) |
|---|---|---|---|---|---|
| **23.0** | Charter | docs | 1 hafta | — (Faz 22 ile paralel) | ADR-0013 ACTIVE + 8 OQ resolved + 5 artifact merged |
| 23.1 | Lab/Kernel | code | 3-4 hafta | 23.0 + Faz 22.1.1b | Email + Slack + webhook canlı; D29-NOTIFY-Up + Functional (3 kanal) PASS |
| 23.2 | Production MVP dar | code | 2-3 hafta | 23.1 | Preference API + erasure path + Grafana/alerts + fallback bypass |
| 23.3 | Production MVP geniş | code | 3 hafta | 23.2 | SMS NetGSM + in-app inbox backend API |
| 23.4 | v1 — DLR + in-app UI | code | 2 hafta | 23.3 | SMS DLR + mfe-host inbox UI |
| 23.5 | v1 — preference UI | code | 1 hafta | 23.4 | mfe-host preference settings sayfası |
| 23.6 | v1 — Teams + Slack zenginleştirme | code | 1 hafta | 23.4 | Adaptive Cards + threading |
| 23.7 | v1 — push (FCM/APNS) | code | 2 hafta | 23.4 + Faz 22.2 | FCM primary + APNS Faz 22 iOS gerekirse |
| 23.8 | v1 — analytics + bounce | code | 2 hafta | 23.4 | Grafana dashboard + bounce/spam loop |
| 23.9 | Prod cutover | atomic | 1 hafta | 23.4-23.8 stable | k3d-prod + 72h observation |
| 23.X | v2 (later) | code | 8-12 hafta | v1 stable | A/B + workflow editor + WhatsApp + voice + per-tenant provider |

## Open Questions (kullanıcı clarify gerek)

- **OQ-1**: Corporate SMTP relay var mı, yoksa Postal self-host mi default? (D44 sub-faz 23.2)
- **OQ-2**: SMS primary provider tercihi NetGSM mi, yoksa İletimerkezi mi? (D40)
- **OQ-3**: IYS kaydı zaten var mı yoksa kapsama dahil mi? (D40-IYS)
- **OQ-4**: Audit retention süre tercihi? (30/90/180/365 — D42)
- **OQ-5**: Slack workspace kanal isimleri — `#alerts`, `#audit`, `#ops` veya farklı mı? (D44 sub-faz 23.6)
- **OQ-6**: Mobile push FCM project + APNS bundle id mevcut mu? (Faz 22 ile bağlantı)
- **OQ-7**: In-app inbox MFE Novu inbox component vs custom React tercihi onay? (D38 — Codex custom önerdi)
- **OQ-8**: 3rd party email service (SendGrid/Mailgun) kullanım izni var mı, yoksa fully self-host zorunlu mu? (D44 sub-faz 23.2)

## Sonuç (DRAFT)

Faz 23 Notification Orchestration Platform **custom Spring Boot baseline** ile başlar. **4-tier yapı** (Kernel/Closed Beta → Production MVP dar → Production MVP geniş → v1 → v2). 10 must-have çizgisi production MVP demek için olmazsa olmaz; kanal sayısı + UI yüzeyleri + workflow editor negotiable. Postgres-only stateful, native Java channel adapter, OpenFGA tuple authz, Vault/ESO credentials, KVKK-compliant transactional kapsam, kanal-bazlı D29 mezuniyeti, D35-NOTIFY live scoped E2E gate, BG-NOTIFY-1 boundary discipline. 5 yeni kategori (Deliverability, Abuse/spam, Accessibility, Incident/degraded, Data classification) policy axis olarak yazılı. Novu / Knock / Courier deferred lab candidate. Mongo / Redis / RabbitMQ YASAK.

**Toplam süre**: Charter → Production MVP geniş = **9-11 hafta**; v1 stable + prod cutover = **+5-7 hafta**; total **14-18 hafta** (3.5-4.5 ay).

Faz 23.0 charter + 5 artifact **paralel ilerleyebilir** (Faz 22 ile çakışma yok); 23.1+ Faz 22.1.1b III review verdict'e bağımlı.

8 OQ kullanıcı clarify ile ADR DRAFT → ACTIVE'e taşınır.
