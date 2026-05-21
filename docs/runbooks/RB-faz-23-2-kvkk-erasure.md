# RB-faz-23-2-kvkk-erasure

> **Faz**: 23.2 (Production MVP dar)
> **Codex thread**: `019dfae5-97e6-74c0-9b13-5a15f09f507f`
> **Backend**: PR #67 (PR-B) — `ErasureService` + `AdminErasureController`

## Bağlam

KVKK §11 / GDPR Art 17 right-to-erasure — subscriber'in talebi üzerine
notification-orchestrator veritabanından PII silinir. Audit trail
append-only kalır (silinmez; sadece SUBSCRIBER_ERASURE_REQUEST event eklenir).

## Tetik (kullanıcı talebi)

Subscriber kullanıcı şunlardan biriyle erasure talep edebilir:
- Workcube hesap silme akışı
- Email/destek ticket'i (KVKK Aydınlatma Metni)
- Yasal yetkili merci yazısı

Operator (PRIVACY_OFFICER role) ticket'i kabul ettikten sonra:

## Adımlar

### 1. Erasure talebini onayla

```bash
# Talep validitesi:
# - Subscriber identity verify (email + name match)
# - Yasal süre kontrolü: KVKK Madde 13.2 — veri sorumlusu başvuruya
#   en geç **30 gün** içinde cevap verir. Erasure request ledger
#   (PR-K1 V18 migration) due_at = received_at + 30d tracking.
# - Outstanding işlem yok (active billing/legal hold)
```

### 2. Backend API çağır (synchronous)

```bash
TOKEN=$(curl -s -X POST -d "client_id=admin&grant_type=password&\
username=privacy-officer&password=<vault>" \
https://testai.acik.com/realms/platform-test/protocol/openid-connect/token \
| jq -r .access_token)

curl -X POST https://testai.acik.com/api/v1/admin/notify/erasure \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "org_id": "default",
    "subscriber_id": "1204",
    "reason": "subject_request",
    "evidence_ref": "ticket-2026-05-06-1234"
  }'

# Beklenen response:
# {
#   "intents_erased": <int>,
#   "deliveries_anonymized": <int>,
#   "status": "completed" | "no_op"
# }
```

### 3. Audit doğrula

```sql
-- Audit append (append-only)
SELECT event_type, occurred_at, details
FROM notify.audit_event
WHERE intent_id IN (SELECT intent_id FROM notify.notification_intent
                    WHERE org_id='default' AND payload IS NULL)
  AND event_type = 'SUBSCRIBER_ERASURE_REQUEST'
ORDER BY occurred_at DESC LIMIT 10;

-- Erasure sonrası state:
-- intent.payload = NULL
-- intent.recipients_snapshot = NULL
-- intent.metadata = NULL
-- intent.preference_override = NULL
-- intent.channel_routing = NULL
-- delivery.recipient_id = NULL (sadece target subscriber)
-- delivery.recipient_hash KORUNUR (operational analytics)
```

### 4. Ticket close + doc

Ticket'a 200 response screenshot + audit row count + evidence_ref attach.

## Idempotency

Aynı subscriber için ikinci çağrı → `status: "no_op"` (zaten erased).
Audit append YOK (rule: only on actual change).

## Multi-recipient intent davranışı

Intent multiple subscribers içeriyorsa:
- Sadece target subscriber'ın delivery'leri anonymize edilir
- Diğer subscriber'ların delivery'leri preserved
- Intent payload + recipients_snapshot null'lanan (intent-level PII)

## Rollback

KVKK erasure **GERİ DÖNÜŞÜ YOK** (data permanently null'lanan). Ticket
yanlışlıkla submit edildi ise:
- Intent'in audit row'ları append-only kaldı (forensic)
- recipient_hash KORUNUR (operational analytics)
- Ama PII (email, phone, name) GERİ GETİRİLEMEZ

Bu sebeple **Step 1 onay aşaması kritik**. PRIVACY_OFFICER iki-aşamalı
verify yapmalı (subscriber identity + ticket validity).

## Audit log inquiry (compliance audit)

Operator yıllık compliance audit için:

```sql
SELECT subscriber_id, occurred_at, details->>'erasure_reason' AS reason,
       details->>'evidence_ref' AS ref,
       (details->>'deliveries_anonymized')::int AS deliveries
FROM notify.audit_event
WHERE event_type = 'SUBSCRIBER_ERASURE_REQUEST'
  AND occurred_at >= NOW() - INTERVAL '1 year'
ORDER BY occurred_at DESC;
```

## Referans

- KVKK §11 (right to erasure)
- GDPR Art 17
- ADR-0013 D46 #7 (audit append-only)
- backend PR #67
- Codex thread: `019dfae5-97e6-74c0-9b13-5a15f09f507f`
