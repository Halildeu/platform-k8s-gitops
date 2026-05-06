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

Erasure çağrısı api-gateway üzerinden ROLE_PRIVACY_OFFICER role gate'i ile yapılır.

> **PR-C scope notu**: api-gateway'in `/api/v1/admin/notify/**` route + role
> allowlist konfigürasyonu PR-D scope'unda. PR-C'de api-gateway-config içinde
> notification admin route YOK. Gateway route gelene kadar erasure `kubectl
> port-forward` ile cluster içinden yapılır (DPO authorized operator):
>
> ```bash
> # Pre-PR-D fallback (operator-only, audit'li)
> kubectl --context k3d-prod -n platform-prod port-forward svc/notification-orchestrator 8089:8089 &
> ```

**Üretim ortamı** (PR-D sonrası, gateway route aktif):

```bash
# Prod: ai.acik.com (canonical prod hostname)
curl -X POST 'https://ai.acik.com/api/v1/admin/notify/erasure' \
  -H 'Authorization: Bearer <jwt-with-ROLE_PRIVACY_OFFICER>' \
  -H 'Content-Type: application/json' \
  -d '{
    "org_id": "default",
    "subscriber_id": "1204",
    "reason": "GDPR Art 17 / KVKK §11 subject request",
    "evidence_ref": "TICKET-DPO-2026-001"
  }'
```

**Test cluster smoke** (testai.acik.com):

```bash
curl -X POST 'https://testai.acik.com/api/v1/admin/notify/erasure' \
  -H 'Authorization: Bearer <test-jwt-with-ROLE_PRIVACY_OFFICER>' \
  -H 'Content-Type: application/json' \
  -d '{"org_id":"default","subscriber_id":"smoke-erasure","reason":"smoke","evidence_ref":"SMOKE-RB-23-2"}'
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

**Yeni audit event** (append-only — Codex 019dfc6a P1 absorb: field adları
ErasureService.java kodu ile birebir):
- `event_type`: `SUBSCRIBER_ERASURE_REQUEST`
- `details.subscriber_id`: <subscriber-id> (pseudonymous internal id, e-posta değil)
- `details.erasure_reason`: <reason>
- `details.evidence_ref`: <evidence-ref>
- `details.deliveries_anonymized`: <count>
- `occurred_at`: now()

> Code reference: `ErasureService.eraseSubscriber()` — `details.put("erasure_reason", ...)`,
> `details.put("subscriber_id", ...)`, `details.put("evidence_ref", ...)`,
> `details.put("deliveries_anonymized", ...)`. **NOT** `reason` veya `intents_erased`
> (önceki runbook draft hatasıydı).

### 5. Verification (zorunlu post-step)

> **Codex 019dfc6a P1 absorb**: önceki draft `recipient_hash` filter
> kullanıyordu ama `recipient_hash` HMAC-SHA256(pepper) ile hesaplanıyor
> ve operatör için praktik değil (Vault'tan pepper okumak gerekirdi).
> Yeni verification subscriber_id üzerinden audit event ve recipients_snapshot
> JSONB containment ile yapılır — pepper-free.

```sql
-- 1) Audit event SUBSCRIBER_ERASURE_REQUEST var (en güvenilir kanıt)
SELECT event_type, occurred_at, details
  FROM notify.audit_event
 WHERE event_type = 'SUBSCRIBER_ERASURE_REQUEST'
   AND details->>'subscriber_id' = '<subscriber-id>'
   AND org_id = '<org-id>'
 ORDER BY occurred_at DESC LIMIT 1;
-- Beklenti: 1 row, details = {erasure_reason, evidence_ref, subscriber_id,
--                              deliveries_anonymized}

-- 2) Subject'e ait intent payload tümü NULL olmalı (recipients_snapshot
--    pre-erasure containment match; post-erasure snapshot NULL olur)
SELECT intent_id, payload IS NULL AS payload_purged,
       recipients_snapshot IS NULL AS snapshot_purged,
       metadata IS NULL AS metadata_purged
  FROM notify.notification_intent
 WHERE org_id = '<org-id>'
   AND intent_id IN (
     -- intent_id'leri audit'ten alabiliriz, veya delivery üzerinden:
     -- (subscriber_id'ye bağlı delivery.recipient_id artık NULL ama
     -- intent_id eşleşmesi için son audit event'in correlation_id'si)
     SELECT DISTINCT i.intent_id
       FROM notify.notification_intent i
       JOIN notify.notification_delivery d ON d.intent_id = i.intent_id
      WHERE d.recipient_id IS NULL  -- post-erasure: recipient_id null
        AND i.org_id = '<org-id>'
        AND i.payload IS NULL
   );
-- Beklenti: payload_purged=t, snapshot_purged=t, metadata_purged=t (tümü TRUE)

-- 3) Subject delivery rows recipient_id NULL olmalı (recipient_hash KORUNUR)
SELECT id, intent_id, channel, recipient_id, recipient_hash
  FROM notify.notification_delivery d
 WHERE EXISTS (
   SELECT 1 FROM notify.notification_intent i
    WHERE i.intent_id = d.intent_id
      AND i.org_id = '<org-id>'
      AND i.payload IS NULL  -- post-erasure marker
 )
 AND d.recipient_id IS NULL;
-- Beklenti: rows present; recipient_id IS NULL; recipient_hash IS NOT NULL
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

Pre-prod test (ConfigMap routing PR-D sonrası):

```bash
# Test ortamı (testai.acik.com authoritative test surface)
curl -X POST 'https://testai.acik.com/api/v1/admin/notify/erasure' \
  -H 'Authorization: Bearer <test-jwt>' \
  -H 'Content-Type: application/json' \
  -d '{"org_id":"default","subscriber_id":"smoke-erasure","reason":"smoke","evidence_ref":"SMOKE-RB-23-2"}'

# Beklenen: 200 + {"intents_erased":N,"deliveries_anonymized":M,"status":"completed|no_op"}
```

PR-C scope'unda gateway route henüz yok; pre-PR-D test cluster smoke için
operatör `kubectl port-forward` kullanır:

```bash
kubectl --context k3d-test -n platform-test port-forward svc/notification-orchestrator 8089:8089
curl -X POST http://localhost:8089/api/v1/admin/notify/erasure -H 'Content-Type: application/json' \
  -d '{"org_id":"default","subscriber_id":"smoke-erasure","reason":"smoke","evidence_ref":"SMOKE-RB-23-2"}'
```

Test cluster'da real subscriber data **YOK**; smoke endpoint reachability
doğrular. Real KVKK erasure sadece prod'da operatör tarafından yapılır
(PR-D gateway route + JWT role gate aktif sonrası).

---

## Referans

- ADR-0013-notification-orchestration §6 (KVKK)
- KVKK Kanun No: 6698 §11 (Veri Sahibinin Hakları)
- GDPR Art 17 (Right to erasure / right to be forgotten)
- Codex thread `019dfae5` (PR-B partition foundation)
- Codex thread `019dfc3e` (PR-C runbook + Q6 PARTIAL absorb)
