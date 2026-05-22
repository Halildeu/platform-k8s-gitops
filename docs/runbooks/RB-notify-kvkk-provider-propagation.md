# RB — KVKK Madde 11.4 Provider Erasure Propagation Matrix

> **Status**: ACTIVE (Codex `019e4950` P0 absorb 2026-05-21)
> **Tetik**: KVKK Madde 11.4 — "Veriyi işleyen tarafından işlenen kişisel verilerin silinmesi/yok edilmesi/anonim hale getirilmesi hakkındaki diğer durum"
> **Owner**: ops + legal/DPO (provider DPA koordinasyonu)
> **SLA**: 30 gün (KVKK Madde 13.2 cevap süresi sınırı; ledger `due_at` tracking)

## Bağlam

Bizim notification orchestrator, recipient verisini (`email`, `phone`, mesaj `body`) **3rd-party provider'lara aktarıyor**:
- Office 365 SMTP (mail relay)
- Microsoft Graph Mail (alternate path — currently deferred)
- JetSMS SOAP (SMS primary)
- NetGSM REST (SMS secondary — R1 ⏳ DEFER; sözleşme kısa vadede yok, NetGSM henüz aktif değil — matrix entry asset-preserved)
- SendGrid / Mailgun (future email providers)
- Slack incoming webhook (workspace receiver — channel-addressed; no recipient PII gönderiliyor)
- Microsoft Teams Power Automate flow webhook (channel-addressed)

KVKK Madde 11.4 gereği subscriber erasure request geldiğinde **bu provider'lardaki veri de silinmeli** (veya retention süresi sonunda otomatik silinmesi DPA'da garantilenmeli).

**Codex 019e4950 P0 finding**: Mevcut runbook'lar provider-side deletion akışını kapsamıyor (`RB-notify-kvkk-erasure.md` "provider_msg_id provider sorumluluğu" diye ext bırakıyor). Bu **KVKK ihlali riski**.

## Provider Matrix

### Email — Office 365 SMTP (canonical, LIVE)

| Field | Detay |
|---|---|
| **Provider** | Microsoft Office 365 (acik.com tenant) |
| **Veri aktarılan** | `from`, `to`, `subject`, `body` (HTML + text) |
| **Veri retention (provider-side)** | Microsoft 365 Exchange Online: deleted items 14-30 gün (admin policy), purged 30 gün sonra; mailbox retention policy tenant-specific |
| **Sender outbound retention** | Sent Items folder default 30 gün; admin policy üzerinden değiştirilebilir |
| **Deletion API** | `Microsoft Graph API: DELETE /me/messages/{id}` (delegated) veya `DELETE /users/{userId}/messages/{id}` (application). Tenant admin gerek. |
| **Deletion via UI** | OWA / Outlook desktop: Sent Items → Permanently Delete |
| **DPA owner** | Microsoft 365 customer agreement (CDA) — Microsoft Corporation |
| **Evidence field** | `provider_msg_id_masked` (notification_delivery), Graph API deletion timestamp |
| **Erasure propagation prosedürü** | 1. SubscriberErasureService trigger → 2. notification_delivery rows with `channel='email'` ve subscriber recipient_id → 3. Graph API DELETE çağrısı (operator gate; admin scope) → 4. Audit: `EMAIL_PROVIDER_ERASURE` event yaz |
| **Otomatik silme garantisi** | Office 365 default retention; subscriber kişisel mailbox değil — `ai@acik.com` sender outbox (kendi tenant) — DPO retention policy: 30 gün |

### Email — Microsoft Graph Mail (deferred, ADR-0024)

| Field | Detay |
|---|---|
| **Status** | Backend ready + gitops staged (PR #872); activation deferred |
| **Veri aktarılan** | SMTP ile aynı: `from`, `to`, `subject`, `body` |
| **Reactivation** | `RB-graph-mail-adapter-activation.md` chain; `kv/platform/notification-orchestrator/graph_*` Vault seed sonrası |
| **Erasure propagation** | SMTP path ile aynı (Graph API delegasyon vs application permission farkı; tenant admin gerek) |

### SMS — JetSMS SOAP (primary, LIVE)

| Field | Detay |
|---|---|
| **Provider** | JetSMS (Biotekno) |
| **Veri aktarılan** | `recipient_phone` (+90...), `message_body`, `originator`, `channel` (VFO/VF), `msg_id` |
| **Veri retention (provider-side)** | JetSMS müşteri portal: 90 gün default (SMS DLR + msg_id lookup window) |
| **Deletion API** | JetSMS API'sinde explicit deletion endpoint YOK; provider customer-side data retention policy uygulanıyor |
| **Deletion via Customer Portal** | `https://customerportal.jetsms.com.tr` → Reports → Manual deletion request (e-posta ticket) |
| **DPA owner** | Biotekno İletişim Hizmetleri A.Ş. — KVKK uyumlu sözleşme (operator track) |
| **Evidence field** | `provider_msg_id_masked` (jetsms-YYYYMMDDHHMMSSNNN), DLR `code` |
| **Erasure propagation prosedürü** | 1. SubscriberErasureService trigger → 2. notification_delivery rows with `channel='sms'` ve subscriber recipient_id → 3. **Otomatik provider deletion YOK** — DPA gereği 90 gün retention sonunda provider-side otomatik purge → 4. Audit: `SMS_PROVIDER_RETENTION_NOTED` event yaz (immediate delete YERINE retention promise documented) |
| **Otomatik silme garantisi** | Biotekno DPA: 90 gün hard limit (operator verify gerekli; tek seferlik) |

### SMS — NetGSM REST (secondary, R1 ⏳ DEFER — henüz aktif değil)

| Field | Detay |
|---|---|
| **Provider** | NetGSM A.Ş. |
| **Status** | **R1 ⏳ DEFER** — NetGSM secondary sözleşmesi kısa vadede yapılmayacak (kullanıcı kararı 2026-05-23); NetGSM henüz aktif değil → NetGSM-side subscriber datası YOK. Vault path infrastructure LIVE PR #482 (asset-preserved dormant); sözleşme imzalanırsa bu propagation matrix entry devreye girer |
| **Veri aktarılan** | JetSMS ile aynı (recipient_phone, body, msgheader, channel) |
| **Veri retention (provider-side)** | NetGSM müşteri portal: 180 gün default; contract'a bağlı |
| **Deletion API** | NetGSM API'sinde explicit deletion endpoint YOK |
| **DPA owner** | NetGSM A.Ş. — KVKK uyumlu sözleşme (R1 closure'da legal review zorunlu) |
| **Erasure propagation** | JetSMS pattern — retention promise documented; otomatik provider deletion yok |

### Slack incoming webhook (channel-addressed)

| Field | Detay |
|---|---|
| **Provider** | Slack Technologies (Salesforce) |
| **Veri aktarılan** | **Channel-addressed**: Slack workspace receiver; subscriber PII (email/phone) **YOK** — sadece intent body text + provenance (org_id + topic_key + correlation_id) |
| **Veri retention (provider-side)** | Workspace admin policy; Slack default unlimited (paid plan dependent) |
| **Deletion API** | `Slack Web API: chat.delete` (workspace owner permission) |
| **DPA owner** | Slack Technologies — workspace owner sözleşme |
| **Erasure propagation prosedürü** | PII Slack'e gitmediği için subscriber erasure propagation **gerek değil**. **AMA**: workspace-level message retention policy DPO/legal review (KVKK 7-yıl record-keeping vs Slack default unlimited tension) |

### Microsoft Teams Power Automate flow webhook

| Field | Detay |
|---|---|
| **Provider** | Microsoft Power Automate (Office 365 tenant) |
| **Veri aktarılan** | **Channel-addressed**: Teams channel receiver; subscriber PII (email/phone) **YOK** — sadece intent body text + provenance |
| **Veri retention (provider-side)** | Teams channel message retention: tenant admin policy (default unlimited) |
| **Deletion via UI** | Teams channel → message → ... → Delete |
| **DPA owner** | Microsoft 365 customer agreement (acik.com tenant) |
| **Erasure propagation** | Slack pattern — PII Teams'e gitmediği için subscriber erasure gerek değil; channel message retention DPO/legal review |

### Webhook egress (HMAC signed)

| Field | Detay |
|---|---|
| **Provider** | Müşteri-tanımlı 3rd-party endpoint (external system) |
| **Veri aktarılan** | Template-rendered body (subscriber PII içerebilir) |
| **Veri retention (3rd-party-side)** | Müşteri sorumluluk — 3rd-party kontrolünde |
| **Deletion API** | Müşteri 3rd-party DPA gereği kendi prosedürü |
| **DPA owner** | Müşteri ↔ 3rd-party (transitive sorumluluk; orchestrator processor değil controller-by-proxy) |
| **Erasure propagation prosedürü** | 1. Müşteriye notify (template rendering geçmişi 3rd-party'de var olabilir) → 2. Müşteri 3rd-party DPA gereği action alır → 3. Audit: `WEBHOOK_EGRESS_DOWNSTREAM_NOTIFIED` event |

## Erasure Propagation Flow

```
SubscriberErasureService.erase(subscriberId, orgId, reason)
  │
  ├── 1. Internal data: notification_intent + notification_delivery + audit_event
  │      → PII fields nullify (current implementation)
  │
  ├── 2. notification_delivery query: WHERE recipient_id = :subscriberId
  │      → Group by `channel` + `provider`
  │
  ├── 3. Per-provider propagation matrix lookup
  │      │
  │      ├── email/smtp-office365 → Graph API DELETE (operator gate)
  │      ├── sms/jetsms → DPA retention promise (90 gün) — NO immediate delete
  │      ├── sms/netgsm → DPA retention promise (180 gün) — NO immediate delete
  │      ├── slack/slack-default → SKIP (no PII transferred)
  │      ├── teams/teams-default → SKIP (no PII transferred)
  │      └── webhook/* → Customer notification ticket (transitive)
  │
  ├── 4. Audit event per provider:
  │      EMAIL_PROVIDER_ERASURE (success/pending/failed)
  │      SMS_PROVIDER_RETENTION_NOTED (informational; no action)
  │      WEBHOOK_EGRESS_DOWNSTREAM_NOTIFIED (customer ticket)
  │
  └── 5. Erasure request ledger update:
         status: in_progress → closed (when all providers reported)
         legal_hold_reason: NULL or "PROVIDER_RETENTION_OUT_OF_BAND"
```

## Implementation Status

| Step | Status |
|---|---|
| Internal data PII nullify | 🟢 LIVE (ErasureService) |
| Per-provider matrix lookup | 🔴 **NOT IMPLEMENTED** — bu runbook ile dokümante edildi; impl ayrı PR |
| Graph API DELETE (email) | 🔴 **NOT IMPLEMENTED** — operator gate; ayrı PR |
| Audit event per provider | 🔴 **NOT IMPLEMENTED** — ayrı PR |
| Erasure request ledger | 🔴 **NOT IMPLEMENTED** — PR-K1 scope (V18 migration) |

## Erasure Request Operator Checklist (manual provider deletion)

Otomatik provider propagation impl gelmediği sürece operator manual checklist:

### Email (Office 365)

1. Office 365 Admin Center → Compliance → eDiscovery
2. New search: `from:ai@acik.com to:<subscriber-email>`
3. Hold + Purge (admin permission gerek)
4. Audit log: `Office365EDiscoveryPurge` evidence

### SMS (JetSMS/NetGSM)

Otomatik provider deletion yok; DPA retention promise (90/180 gün) yeterli sayılır.

Eğer operator ek action gerekirse:
1. Biotekno (JetSMS) customer support → manual deletion ticket
2. NetGSM customer portal → manual deletion ticket
3. Audit log: ticket reference + provider response

## Cross-link

- Codex thread: `019e4950-d30e-7781-a50a-0ef619503e08`
- KVKK Madde 11.4 — Aktarılan verilerde silme yükümlülüğü
- Önceki runbook: `RB-notify-kvkk-erasure.md` (admin erasure prosedürü)
- Faz 23.2.B kapsamı: `RB-faz-23-2-kvkk-erasure.md`
- Sonraki PR'lar: PR-K1 (erasure ledger), PR-K3 (backup tombstone), PR-K4 (log redaction), PR-K5 (audit pseudonymize), PR-K6 (tenant DPO), PR-K7 (KVKK runbook refresh)

## DPO/Legal final onay

Bu runbook **AI proxy review (Codex)** ile hazırlandı — gerçek hukuk müşavirliği yerine geçmez. **DPO/legal final onay** gereken kalemler:
- Office 365 Graph API DELETE admin scope authorization model
- JetSMS/NetGSM DPA retention promise dokümantasyon (sözleşmede sabit mi yoksa SLA mı)
- Webhook transitive sorumluluk: orchestrator "processor" mı "controller-by-proxy" mı?
- Slack/Teams workspace retention policy DPO/legal review (record-keeping tension)
