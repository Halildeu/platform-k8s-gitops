# RB-faz-23-2-kvkk-erasure — Notification Subscriber Erasure (KVKK §11 / GDPR Art 17)

> **Status**: ACTIVE (Faz 23.2 PR-C; Codex thread `019dfc3e` Q6 PARTIAL absorb)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Related**:
> - `RB-faz-23-charter.md` (sub-faz roadmap)
> - `notification-orchestrator/src/main/java/com/serban/notify/api/AdminErasureController.java`
> - `notification-orchestrator/src/main/java/com/serban/notify/erasure/ErasureService.java`

Bu runbook **operasyonel KVKK §11 / GDPR Art 17 right-to-erasure** akışını tanımlar.
Subject (data subject) bir notification platform'unda kendisine ait kişisel verinin
silinmesini talep ettiğinde uygulanacak adımları kapsar.

---

## Tetik

| Tetikleyici | Kanal | Yanıt SLA |
|---|---|---|
| Subject formal "veri silme talebi" gönderir (e-posta, ticket, KVK Kurulu yönlendirmesi) | DPO (Data Protection Officer) | 30 takvim günü (KVKK §11 / GDPR Art 12) |
| Internal compliance audit (proaktif erasure) | Privacy ekibi | İç prosedür |
| Court order / legal mandate | Legal | Karar gereği (genelde 7-14 gün) |

**Operatör rolü**: ROLE_PRIVACY_OFFICER (api-gateway path-based allowlist üzerinden erişim).

---

## Adımlar

### 1. Talebi doğrula

Subject kimliği eşleşiyor mu?
- subscriber_id ile aktif kayıt var mı? (DB kontrol — pre-flight read-only)
- Talep "kendi verisi" mi yoksa başka subject için mi? (KVKK §11 yalnızca subject'in
  kendisinin talep edebileceğini söyler — vekil için noter onaylı yetki gerekir)
- Legal hold (icra, yargı emri, finansal denetim) var mı? Varsa erasure DURDURULUR
  ve DPO'ya escalate edilir; manuel review olmadan endpoint çağrılmaz.

### 2. Pre-flight: etkilenen kayıt sayısı

Erasure öncesi audit + DBA kontrolü:

```sql
-- Subject'e ait intent sayısı
SELECT COUNT(*) FROM notify.notification_intent
 WHERE org_id = '<org-id>'
   AND recipients_snapshot @> '[{"type":"subscriber","subscriberId":"<subscriber-id>"}]'::jsonb;

-- Subject'e ait delivery sayısı (recipient_id = subscriber_id)
SELECT COUNT(*) FROM notify.notification_delivery d
  JOIN notify.notification_intent i ON i.intent_id = d.intent_id
 WHERE i.org_id = '<org-id>' AND d.recipient_id = '<subscriber-id>';
```

Beklenen sayılar log/ticket'a kaydedilir; erasure sonrası verification için kullanılır.

### 3. Endpoint çağrı

Direct pod port veya service URL **YASAK**. Erasure mutlaka **api-gateway** üzerinden
ROLE_PRIVACY_OFFICER allowlist gate'i ile yapılır.

```bash
# Üretim çağrısı (testai üzerinden)
curl -X POST 'https://app.testai.acik.com/api/v1/admin/notify/erasure' \
  -H 'Authorization: Bearer <jwt-with-ROLE_PRIVACY_OFFICER>' \
  -H 'Content-Type: application/json' \
  -d '{
    "org_id": "default",
    "subscriber_id": "1204",
    "reason": "GDPR Art 17 / KVKK §11 subject request",
    "evidence_ref": "TICKET-DPO-2026-001"
  }'
```

**JSON wire format** (snake_case via `@JsonProperty`):
- `org_id` — required, NotBlank, max 64 chars; subscriber'ın bağlı olduğu org tenant
- `subscriber_id` — required, NotBlank, max 128 chars; pseudonymous internal id
  (e-posta/telefon **DEĞİL**; redaction allowlist boundary'sinde hâlihazır)
- `reason` — required, NotBlank, max 128 chars; kısa kategori (örn. `gdpr_art_17`,
  `kvkk_11`, `internal_audit`, `court_order`)
- `evidence_ref` — optional, max 255 chars; ticket/case id; **operasyonel disiplin
  olarak zorunludur** — DTO `@NotBlank` değil ama runbook her çağrıda evidence_ref
  girilmesini şart koşar

**Response** (200):
```json
{
  "intents_erased": 12,
  "deliveries_anonymized": 18,
  "status": "completed"
}
```

`status: "no_op"` — subscriber için erasable kayıt yok (zaten silinmiş veya hiç
kayıt yok).

### 4. Erasure davranış kontratı

`ErasureService` (sync, idempotent) şu alanları **NULL** atar:
- `notification_intent.payload`
- `notification_intent.recipients_snapshot`
- `notification_intent.metadata`
- `notification_intent.channel_routing`
- `notification_intent.preference_override`
- `notification_delivery.recipient_id`

**KORUNAN** alanlar (operational analytics + audit boundary):
- `notification_delivery.recipient_hash` — pseudonymous HMAC-SHA256, subject'i
  identifier'dan ayrıştıran irreversible hash
- `notification_intent.intent_id`, `template_id`, `topic_key`, `severity`,
  `data_classification`, status timestamps
- Audit event'ler (append-only `audit_event_no_delete` rule)

**Yeni audit event** (append-only):
- `event_type`: `SUBSCRIBER_ERASURE_REQUEST`
- `details.subscriber_id`: <subscriber-id> (pseudonymous internal id, e-posta değil)
- `details.reason`: <reason>
- `details.evidence_ref`: <evidence-ref>
- `details.intents_erased`: <count>
- `details.deliveries_anonymized`: <count>
- `occurred_at`: now()

### 5. Verification (zorunlu post-step)

```sql
-- 1) Subject'e ait intent payload tümü NULL olmalı
SELECT intent_id, payload, recipients_snapshot, metadata
  FROM notify.notification_intent
 WHERE org_id = '<org-id>'
   AND intent_id IN (
     SELECT intent_id FROM notify.notification_delivery
      WHERE recipient_hash = '<hash-of-erased-subscriber>'
   );
-- Beklenti: payload IS NULL, recipients_snapshot IS NULL, metadata IS NULL

-- 2) Subject delivery rows recipient_id NULL olmalı; recipient_hash kalmalı
SELECT id, intent_id, channel, recipient_id, recipient_hash
  FROM notify.notification_delivery
 WHERE recipient_hash = '<hash-of-erased-subscriber>';
-- Beklenti: recipient_id IS NULL; recipient_hash IS NOT NULL

-- 3) Audit event SUBSCRIBER_ERASURE_REQUEST var
SELECT event_type, occurred_at, details
  FROM notify.audit_event
 WHERE event_type = 'SUBSCRIBER_ERASURE_REQUEST'
   AND details->>'subscriber_id' = '<subscriber-id>'
 ORDER BY occurred_at DESC LIMIT 1;
-- Beklenti: 1 row (SUBSCRIBER_ERASURE_REQUEST event)
```

Verification fail olursa endpoint çağrı tekrar edilir (idempotent — ikinci çağrı
zaten silinmiş subject için `no_op` döner). Kapanmazsa DBA + dev escalate.

### 6. Subject'e bilgilendirme

KVKK §11 ve GDPR Art 19 gereği subject'e işlem tamamlandı bildirimi gönderilir.
Bildirim formal kanaldan (subject'in talep ettiği kanal — e-posta, ticket cevabı)
gönderilir; runbook bu kapsamı içermez (DPO sürecidir).

---

## Rollback

**Yok.** Erasure terminal bir karardır. Veri silindiyse:
- Backup'tan restore **standart prosedür değildir**: ayrı incident + legal review
  + DPO onayı + court order gerekir
- Bu nedenle erasure öncesi pre-flight + verification adımı atlanmaz

Yanlış subject'e erasure uygulanırsa: derhal DPO + Legal escalate; backup restore
ayrı incident workflow.

---

## Audit retention vs. erasure ilişkisi

`audit_event` append-only RULE ile silinmez. SUBSCRIBER_ERASURE_REQUEST event
`subscriber_id` (pseudonymous) içerir; e-posta/telefon raw değer **içermez**
(redaction allowlist boundary).

Audit partition retention (Faz 23.2 PR-D scope) eski partition'ları DETACH/DROP
ederek 90 gün öncesi audit row'larını kaldırır. Bu, erasure event'in 90 gün sonra
"unutulması" anlamına gelir — pseudonymous reference olduğu için KVKK §11 ile
çelişmez. Ancak external evidence_ref (ticket id) DPO tarafında ayrıca arşivlenir.

---

## Yasaklar

- Direct pod port / `kubectl port-forward` ile erasure çağrısı **YASAK**
  (ROLE_PRIVACY_OFFICER gate'i bypass)
- Boş `evidence_ref` ile erasure **operasyonel disiplin gereği YASAK**
- Subject'in dolaylı yöneticisinin (HR, manager) talebi tek başına kâfi değil;
  subject onayı veya court order gerekir
- Aynı `subscriber_id` için tekrarlı erasure (ikinci çağrı no_op döner — dürüst);
  manuel SQL UPDATE **YASAK** (audit event yazılmaz, contract bozulur)

---

## Test (smoke)

Pre-prod test:

```bash
# Test ortamında dummy subscriber id ile çağrı
curl -X POST 'https://test.testai.acik.com/api/v1/admin/notify/erasure' \
  -H 'Authorization: Bearer <test-jwt>' \
  -H 'Content-Type: application/json' \
  -d '{"org_id":"default","subscriber_id":"test-subscriber-erasure","reason":"smoke","evidence_ref":"SMOKE-RB-23-2"}'

# Beklenen: 200 + status either "completed" or "no_op"
```

Test cluster'da real subscriber data **YOK**; smoke endpoint reachability
doğrular. Real KVKK erasure sadece prod'da operatör tarafından yapılır.

---

## Referans

- ADR-0013-notification-orchestration §6 (KVKK)
- KVKK Kanun No: 6698 §11 (Veri Sahibinin Hakları)
- GDPR Art 17 (Right to erasure / right to be forgotten)
- Codex thread `019dfae5` (PR-B partition foundation)
- Codex thread `019dfc3e` (PR-C runbook + Q6 PARTIAL absorb)
