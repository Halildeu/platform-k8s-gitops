# RB-notify-kvkk-erasure — KVKK Art.11 Right-to-Erasure Operasyon Prosedürü

> **Status**: ACTIVE — REFRESHED 2026-05-21 (Codex `019e4950` P2 absorb)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md) D42 + D46 #7
> **Sub-faz**: 23.2 (MVP-dar — KVKK erasure path)
> **SLA**: KVKK Madde 13.2 — başvuruya **en geç 30 gün** içinde cevap. Erasure request ledger (PR-K1 V18 migration) `due_at = received_at + 30d` tracking.
> **Related runbooks**: `RB-notify-kvkk-provider-propagation.md` (Madde 11.4 provider matrix), `RB-notify-kvkk-backup-tombstone.md` (backup restore re-erasure)

## Codex 019e4950 P2 absorb — drift fix (2026-05-21)

Bu runbook **AI proxy review** sonrası kod ile aligned:
- **Pseudonymization**: ~~SHA-256 anonim~~ → **HMAC-SHA256 with Vault-stored org-namespaced pepper** (`PiiRedactor.hashRecipient`). recipient_hash **pseudonymous personal data**; "anonim" terimi yanıltıcıdır.
- **Audit table**: `audit_event_v2` (Faz 23.1 PR-F partitioned 90-day retention); `audit_event` legacy.
- **Subscriber endpoint**: free-form `reason` accepted DEĞİL; sabit `self-service-kvkk-art-11`.
- **Response shape**: `intents_erased`, `deliveries_anonymized`, `inbox_rows_deleted`, `status` (`completed` / `no_op`).
- **DPO/legal final onay**: bu runbook implementation contract'ını yansıtır; hukuki uyum **DPO/legal sign-off ext** kalır.

KVKK 11. madde: "Veri sahibi, kendisine ait verilerin silinmesini veya yok edilmesini talep edebilir."

Bu runbook **subscriber'ın kendi notification verilerinin silinmesi** prosedürünü tanımlar. Audit log integrity korunur, payload purge edilir, recipient_hash pseudonymous kalır.

## Kapsam

- **Dahil**: subscriber'ın `notification_intent.payload`, `notification_delivery.recipient_id`, log MDC içeriği
- **Hariç (pseudonymous data — saklama hukuki dayanak)**: `audit_event_v2.recipient_hash` (HMAC-SHA256 with org-namespaced Vault pepper — pseudonymous, audit chain integrity + replay prevention için saklanır; KVKK Madde 7 hukuki yükümlülük gerekçesi 90-day retention'a kadar), `notification_delivery.provider_msg_id_masked` (provider DPA gereği — provider matrix runbook); aggregate metrics (kişiye özgü değil)

## Subscriber Self-Service (API yolu — MVP)

### Endpoint

```
DELETE /api/v1/notify/audit/me
```

JWT zorunlu. `subscriber_id = JWT.subject`. Cross-subscriber silme YASAK (OpenFGA enforcement).

### Behavior

1. Subscriber'ın tüm aktif `notification_intent` row'larını bul (`WHERE EXISTS (SELECT 1 FROM notification_delivery WHERE recipient_hash = sha256(<subscriber_email_or_phone>))`)
2. Her row için:
   - `payload` field NULL'lanır
   - `correlation_id` korunur (cross-trace integrity)
   - `template_id`, `template_version`, `org_id`, `topic_key` korunur (audit query için anonim)
3. `subscriber_preference` row'ları **silinmez**, ama `enabled = FALSE` (re-enrollment audit kalır)
4. Audit event INSERT: `event_type = SUBSCRIBER_ERASURE_REQUEST`, `subscriber_id = <id>`, `requested_at = NOW()`
5. Response: `200 OK + {"erased_intent_count": N, "erased_at": "<timestamp>"}`

### SQL örneği

```sql
-- Atomic transaction
BEGIN;

UPDATE notify.notification_intent ni
SET payload = NULL
WHERE EXISTS (
  SELECT 1 FROM notify.notification_delivery nd
  WHERE nd.intent_id = ni.intent_id
    AND nd.recipient_hash = encode(sha256('user@example.com'::bytea), 'hex')
);

UPDATE notify.subscriber_preference
SET enabled = FALSE, updated_at = NOW()
WHERE subscriber_id = '1204';

INSERT INTO notify.audit_event (intent_id, event_type, org_id, topic_key, recipient_hash, details, occurred_at)
VALUES (
  '<system-erasure-event>',
  'SUBSCRIBER_ERASURE_REQUEST',
  'default',
  'system.kvkk',
  encode(sha256('user@example.com'::bytea), 'hex'),
  '{"requested_via": "self-service-api", "erased_intent_count": 42}',
  NOW()
);

COMMIT;
```

## Operator-Driven (admin tarafı — KVKK request handler)

### Trigger

Subscriber legal kanaldan request gönderdi (email/posta/KVKK Bilgi Edinme): "Verilerimi silin".

### Adımlar

1. **Kimlik doğrulama** (OPS): subscriber kimliğini doğrula (KVKK'nın 13. madde gereği). E-posta + ID number cross-check.
2. **Subscriber lookup**: 
   ```sql
   SELECT subscriber_id FROM notify.subscriber_preference WHERE email_hash = encode(sha256('user@example.com'::bytea), 'hex');
   ```
3. **Erasure runbook çalıştır** (OPS, user-approval-required):
   ```bash
   ./scripts/notify/kvkk-erasure.sh --subscriber-id 1204 --reason "user-request-2026-05-05" --evidence-link "https://kvkk-tickets.example.com/12345"
   ```
4. **Audit kanıt**: erasure event log'u Slack #audit kanalına notification (BG-NOTIFY-1 boundary)
5. **Subscriber bilgilendirme**: erasure tamamlandı email (transactional kapsamda; commercial değil)

### Boundary

`scripts/notify/kvkk-erasure.sh` çalıştırma → ADR-0011 BG-1 `state-mutation (production)` + `user-communication` (KVKK confirmation email). User-approval-required label + evidence link zorunlu.

## Aggregate Audit Retention

KVKK'nın 7. madde "veri saklama süresi" ile uyumlu:

```sql
-- 90 gün retention default (ADR-0013 D42)
DELETE FROM notify.audit_event
WHERE occurred_at < NOW() - INTERVAL '90 days';
```

Bu cron job (sub-faz 23.2'de implementasyon):

```yaml
# kustomize/base/apps/notification-orchestrator/cronjob-retention.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: notify-audit-retention-purge
spec:
  schedule: "0 2 * * *"  # daily 02:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: purge
              image: ghcr.io/halildeu/platform-backend-notify-cron@sha256:<digest>
              command:
                - /bin/sh
                - -c
                - psql $NOTIFY_DB_URL -c "DELETE FROM notify.audit_event WHERE occurred_at < NOW() - INTERVAL '90 days'; DELETE FROM notify.idempotency_key WHERE expires_at < NOW() - INTERVAL '7 days';"
```

## Compliance Evidence

Her erasure operasyonu `docs/faz-23-evidence/kvkk/<date>-<subscriber-hash>-erasure.md`:

```markdown
# KVKK Art.11 Erasure — <date> — <subscriber-hash>

- **Subscriber hash**: <sha256(email)>
- **Request channel**: self-service / legal / posta / email
- **Verified by**: <ops-username>
- **Verification method**: e-posta + ID number cross-check
- **Erased intent count**: 42
- **Erased at**: 2026-05-05T14:32:00Z
- **Audit event id**: <uuid>
- **Notification sent**: ✓ (transactional confirmation)

## Files affected

- notification_intent.payload NULL'landı: 42 row
- subscriber_preference enabled=FALSE: 1 row
- audit_event INSERT: SUBSCRIBER_ERASURE_REQUEST

## Compliance check

- [x] KVKK 11. madde — silme talebi yerine getirildi
- [x] KVKK 13. madde — bilgilendirme yapıldı (transactional email)
- [x] Audit integrity — recipient_hash + correlation_id korundu
- [x] Aggregate metrics not affected
```

## Cross-Reference

- ADR-0013 D42 (KVKK disiplin) + D46 #7 (PII redaction must-have)
- ADR-0011 BG-1 (`user-communication` class — confirmation email için)
- KVKK 11. madde (right to erasure) + 13. madde (right to information)
- event-contract.md §7 PII Redaction Policy
