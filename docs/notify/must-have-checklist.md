# Notification Platform — 10 Must-Have Çizgisi

> **Status**: DRAFT (Faz 23.0 charter — 2026-05-05)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md) D46
> **Codex thread**: `019df86f-89aa-7200-bb6c-b7b903860148`

Bu 10 özellik **production MVP demek için olmazsa olmaz**. Negotiable değil. Bu liste eksiksiz olmadan "Faz 23 production ready" denmez.

Diğer ~130 özellik **negotiable** (kanal sayısı, UI yüzeyleri, workflow editor, A/B testing, brand customization).

---

## #1 — Notification Intent + Delivery Log Schema

**Açıklama**: Her notification akışı normalize edilmiş bir veri modeline oturmalı. `org_id`, `topic_key`, `recipient`, `template_version`, `status`, `correlation_id` — bu 6 alan **zorunlu**.

**Sub-faz**: 23.1 (Kernel)

**Kabul kriteri**:
- [ ] `notify.notification_intent` tablosu mevcut (8 zorunlu kolon)
- [ ] `notify.notification_delivery` tablosu mevcut (channel + status + recipient_hash + provider_msg_id)
- [ ] `notify.audit_event` tablosu mevcut (event_type + correlation_id + redacted details)
- [ ] V1 Flyway migration applied
- [ ] FK constraint `notification_delivery.intent_id → notification_intent.intent_id`
- [ ] Index `(status, scheduled_at)` `(org_id, topic_key)` `(correlation_id)`

**Kanıt**:
```bash
psql -c "\d notify.notification_intent"
psql -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'notify';"  # >= 8
```

**Detay**: `docs/notify/event-contract.md` §4 PostgreSQL Schema

---

## #2 — Idempotency + Dedupe

**Açıklama**: Retry, saga replay, manual replay duplicate notification üretmemeli. 24h içinde aynı `idempotency_key` ikinci kez gelirse → original intent_id döndür, no extra delivery.

**Sub-faz**: 23.1 (Kernel)

**Kabul kriteri**:
- [ ] `notification_intent.idempotency_key` UNIQUE constraint (within `org_id`)
- [ ] 24h dedupe window: aynı key 2. kez → HTTP 409 + audit `BLOCKED_BY_IDEMPOTENCY`
- [ ] Saga replay testi: aynı outbox row 2 kez işlenirse → tek delivery
- [ ] Domain service docs: `idempotency_key` convention `<topic_key>-<recipient_id>-<source_event_unique_part>`

**Kanıt**:
```bash
# Test: aynı idempotency_key 2 kez POST
curl -X POST .../intents -d '{"idempotency_key":"test-1",...}'  # 202
curl -X POST .../intents -d '{"idempotency_key":"test-1",...}'  # 409, original intent_id
psql -c "SELECT count(*) FROM notify.notification_delivery WHERE intent_id = '...'"  # 1, not 2
```

---

## #3 — Domain-Side Outbox Contract

**Açıklama**: Admin invite, drift alarm, break-glass audit, password reset — **direct provider çağırmaz**. Kendi DB'sinde transactional outbox row INSERT eder; `notification-orchestrator` outbox poll cycle ile alır.

**Sub-faz**: 23.1 (Kernel)

**Kabul kriteri**:
- [ ] Her domain service'in `notification_outbox` tablosu var (örn. `auth.notification_outbox`)
- [ ] Domain transaction: `@Transactional` ile domain INSERT + outbox INSERT atomic
- [ ] OutboxPoller PG advisory lock ile poll (5s cycle, ≤2s pickup latency)
- [ ] Outbox row PROCESSED status'e gider (orchestrator picked up)
- [ ] `docs/notify/event-contract.md` §4 outbox pattern documented

**Kanıt**:
- `docs/notify/event-contract.md` §4 ve §6 referansı
- Drift alarm receiver entegrasyonu: PR #347 alarm-receiver → outbox → orchestrator (Faz 23.1 evidence)

**Out of scope (negotiable)**:
- Central event bus (Kafka/RabbitMQ) — Codex REVISE: Mongo/Redis/RabbitMQ stateful explosion yasak. Per-domain outbox baseline.

---

## #4 — Retry Exponential Backoff + DLQ + Manual Replay

**Açıklama**: Provider call fail olduğunda retry; max attempt aşıldığında DLQ; admin manual replay edebilir. Silent drop **YASAK**.

**Sub-faz**: 23.1 (Kernel)

**Kabul kriteri**:
- [ ] Retry policy: exponential backoff (örn. 30s → 1m → 5m → 15m → 1h, max 5 attempt)
- [ ] `notification_delivery.attempt_count` increment
- [ ] `notification_delivery.next_retry_at` + RetryWorker pollar
- [ ] Max attempt aşıldığında `notify.dead_letter` tablosuna kopyala + status FAILED
- [ ] `POST /api/v1/notify/admin/dlq/{delivery_id}/replay` endpoint
- [ ] Alertmanager rule: `dlq_size > N` → ops alert
- [ ] Replay audit: `audit_event.event_type = MANUAL_DLQ_REPLAY`

**Kanıt**:
- Test: provider mock 5xx → retry chain log
- DLQ row INSERT after max attempt
- Admin replay: DLQ row → new delivery attempt

---

## #5 — OpenFGA Hard-Deny + Org Boundary

**Açıklama**: Cross-tenant notification leak **kapatılır**. `subscriber:<id>#can_receive notification_topic:<key>` tuple kontrolü yapılmadan delivery yok.

**Sub-faz**: 23.1 (Kernel)

**Kabul kriteri**:
- [ ] `notification_intent.org_id` NOT NULL
- [ ] OpenFGA tuple model: `notification_topic` type + `can_receive` relation
- [ ] Permission-service üzerinden `/check` çağrısı (mevcut Zanzibar plane reuse)
- [ ] Allow case test: tuple var → delivery PROCEEDS
- [ ] Deny case test: tuple yok → audit `BLOCKED_BY_AUTHZ`, no delivery
- [ ] Cross-org test: org_X subscriber için org_Y intent → audit `BLOCKED_BY_AUTHZ`

**Kanıt**:
```bash
# Allow case
curl -X POST .../intents -d '{"org_id":"default","recipient":"sub:1","topic":"test"}'
# OpenFGA: subscriber:1#can_receive notification_topic:test → allow
# Result: delivery succeeds

# Deny case
curl -X POST .../intents -d '{"org_id":"default","recipient":"sub:9999","topic":"test"}'
# OpenFGA: subscriber:9999#can_receive notification_topic:test → deny (no tuple)
# Result: audit BLOCKED_BY_AUTHZ, no delivery
```

---

## #6 — Vault/ESO Provider Credentials + No Secret Logging

**Açıklama**: Provider API key, SMTP password, Slack webhook token — Vault'tan ESO ile sync. Credential **log'a yazılmaz**.

**Sub-faz**: 23.1 (Kernel)

**Kabul kriteri**:
- [ ] Vault path `kv/platform/notification-orchestrator` mevcut (flat path, Faz 23.9 Step D Codex thread `019e08df` — auth-service / user-service convention; SMTP/Slack/NetGSM provider creds aynı path'e property olarak eklenir veya provider-specific path'lere ayrılır gerek olduğunda)
- [ ] ESO ExternalSecret manifest `kustomize/overlays/{test,prod}/eso/notify/`
- [ ] Vault policy `eso-runtime` `kv/data/platform/notification-orchestrator` read içerir (`bootstrap/vault-policies/common/eso-runtime.hcl`)
- [ ] Spring Boot @Value injection (env var) — kod içinde hardcoded credential yok
- [ ] Log audit: `grep -i "password\|token\|secret\|api[_-]key" stdout` → 0 match
- [ ] Provider config DB row: encrypted at rest (PG default) + credential reference (Vault path) only

**Kanıt**:
```bash
kubectl get externalsecret -n platform-test | grep notify
psql -c "SELECT credential_ref FROM notify.provider_config LIMIT 1"  # vault://kv/platform/notification-orchestrator (or provider-specific path)
kubectl logs deploy/notification-orchestrator | grep -iE "password|token|secret" | wc -l  # 0
```

---

## #7 — PII Redaction + Retention/Anonymization Policy (KVKK)

**Açıklama**: Mail body, SMS body, kişisel bilgi log'a/audit'e yazılmaz. Sadece `template_id`, `recipient_hash` (sha256), `org_id`, `correlation_id`. Retention policy var.

**Sub-faz**: 23.1 (Kernel) + 23.2 (MVP-dar erasure path)

**Kabul kriteri**:
- [ ] `audit_event.details` JSONB: payload value yok, sadece metadata
- [ ] `notification_delivery.recipient_hash` sha256(address) — orijinal address sadece intent.payload'da
- [ ] Log MDC pattern: `correlation_id`, `org_id`, `template_id`, `recipient_hash` — body yok
- [ ] Retention policy: `audit_event.occurred_at < NOW() - INTERVAL '90 days'` → cron purge job
- [ ] KVKK Art.11 erasure API: `DELETE /audit/me` → payload purge, recipient_hash kalır
- [ ] Audit append-only enforcement: `CREATE RULE no_update/delete`

**Kanıt**:
```sql
-- Audit body redaction
SELECT details FROM notify.audit_event LIMIT 1;
-- {"recipient_hash": "a3f8c...", "url_template": "/reset?token=<TOKEN>"} -- ✓ redacted

-- Erasure path
DELETE /api/v1/notify/audit/me  -- subscriber's own
SELECT details FROM notify.audit_event WHERE recipient_hash = 'a3f8c...';
-- details.payload = NULL, recipient_hash kalır

-- Retention purge
SELECT count(*) FROM notify.audit_event WHERE occurred_at < NOW() - INTERVAL '90 days';
-- 0 (cron purge çalıştı)
```

---

## #8 — Preference / Opt-out + Critical Bypass Policy

**Açıklama**: Subscriber kanal/topic bazında opt-out edebilir. Ancak `severity=critical` veya `data_classification=security` bu opt-out'u **bypass eder**. Diğerleri respect.

**Sub-faz**: 23.2 (MVP-dar)

**Kabul kriteri**:
- [ ] `notify.subscriber_preference` tablosu (subscriber_id + topic_key + channel + enabled)
- [ ] Preference API: `GET /preferences/me` + `PUT /preferences/me`
- [ ] Send pipeline'da preference check: `enabled=false` → audit `BLOCKED_BY_PREFERENCE`, no delivery
- [ ] **Critical bypass**: `severity=critical` OR `data_classification=security` → preference bypass + audit `PREFERENCE_BYPASSED_CRITICAL`
- [ ] Quiet hours opt-out: `severity=critical` quiet'i geçer
- [ ] Frequency limit opt-out: `severity=critical` frequency limit'i geçer
- [ ] Unsubscribe link footer (email): RFC 8058 List-Unsubscribe-Post header (v1)

**Kanıt**:
```bash
# Opt-out test
PUT /preferences/me {"channel":"email", "topic":"system.update", "enabled": false}
POST /intents {"topic":"system.update", "channel":"email", "recipient":"me"}
# Result: audit BLOCKED_BY_PREFERENCE, no email

# Critical bypass test
PUT /preferences/me {"channel":"email", "topic":"drift.alarm", "enabled": false}
POST /intents {"topic":"drift.alarm", "severity":"critical", "channel":"email", "recipient":"me"}
# Result: email delivered + audit PREFERENCE_BYPASSED_CRITICAL
```

---

## #9 — Template Versioning + Safe Interpolation

**Açıklama**: Geçmiş delivery hangi template ile gitti **sorgulanabilir**. Template injection (XSS, SSTI) **yok**: variable interpolation güvenli.

**Sub-faz**: 23.1 (Kernel)

**Kabul kriteri**:
- [ ] `notify.notification_template` (template_id + version + body + locale)
- [ ] Version immutable: yeni versiyon yeni row INSERT, eski row kalır
- [ ] `notification_intent.template_id + template_version` → audit'te kayıt
- [ ] Thymeleaf safe mode: `th:utext` (raw HTML) **YASAK**, sadece `th:text` (escaped)
- [ ] Test: malicious payload `<script>alert(1)</script>` → output escaped `&lt;script&gt;`
- [ ] Test: SSTI attempt `${T(java.lang.Runtime).getRuntime().exec(...)}` → reject (whitelist variable namespace)
- [ ] Locale fallback: tr-TR → tr → en-US → en → default

**Kanıt**:
```sql
-- Template versioning
SELECT version, body FROM notify.notification_template WHERE template_id = 'auth-password-reset';
-- 1, 2, 3 ... immutable history

-- Audit query
SELECT template_id, template_version FROM notify.audit_event WHERE intent_id = '...';
-- template_id=auth-password-reset, template_version=2 -- ✓ tracked

-- XSS test
POST /intents {"payload":{"user_name":"<script>alert(1)</script>",...}}
-- Email body: "Hello &lt;script&gt;alert(1)&lt;/script&gt;" -- escaped
```

---

## #10 — Observability + Outage Fallback

**Açıklama**: Prometheus metrics, DLQ alert, correlation_id tracing. Kritik yan: notification-orchestrator down olduğunda **drift/break-glass alarmı kendi içinden değil, Alertmanager direct**'tan gelir.

**Sub-faz**: 23.1 (Kernel) + 23.2 (MVP-dar fallback bypass)

**Kabul kriteri**:
- [ ] Prometheus endpoint `/actuator/prometheus` (Spring Actuator)
- [ ] Metrics: `notification_delivery_attempts_total{channel,status}`, `notification_failures_total{channel,reason}`, `notification_retry_total{channel}`, `notification_dlq_size`
- [ ] Distributed tracing: correlation_id propagation HTTP header → DB column → log MDC
- [ ] Alertmanager rule: `notification_dlq_size > 10` → ops alert
- [ ] **Outage fallback** (D43):
  - Notification-orchestrator down (`up{job="notification-orchestrator"} == 0` for 5m) → Alertmanager direct Slack/SMTP
  - Drift alarm-receiver kendi içinde fallback chain: orchestrator timeout → Alertmanager direct
  - Break-glass token script: notification + Alertmanager direct dual-channel
  - `docs/runbooks/RB-notification-outage-fallback.md` mevcut
  - Test: orchestrator scale=0 → Alertmanager #alerts kanalına direct mesaj geldi

**Kanıt**:
```bash
# Prometheus
curl http://orchestrator:8080/actuator/prometheus | grep notification_
# notification_delivery_attempts_total{channel="email",status="DELIVERED"} 1234

# Distributed tracing
curl -H "traceparent: 00-abc123-def456-01" /intents
psql -c "SELECT correlation_id FROM notify.notification_intent ORDER BY id DESC LIMIT 1"
# correlation_id = 'abc123' ✓

# Outage fallback
kubectl scale deploy/notification-orchestrator --replicas=0
# Alertmanager rule fires after 5m
# Slack #alerts'e direct message geldi (orchestrator bypass) ✓
```

---

## Özet Sayım

| # | Must-have | Sub-faz | Status |
|---|---|---|:---:|
| 1 | Intent + delivery log schema | 23.1 | ☐ |
| 2 | Idempotency + dedupe | 23.1 | ☐ |
| 3 | Domain-side outbox | 23.1 | ☐ |
| 4 | Retry + DLQ + manual replay | 23.1 | ☐ |
| 5 | OpenFGA hard-deny + org boundary | 23.1 | ☐ |
| 6 | Vault/ESO + no secret logging | 23.1 | ☐ |
| 7 | PII redaction + KVKK retention | 23.1 + 23.2 | ☐ |
| 8 | Preference + critical bypass | 23.2 | ☐ |
| 9 | Template versioning + safe interpolation | 23.1 | ☐ |
| 10 | Observability + outage fallback | 23.1 + 23.2 | ☐ |

**Production MVP demek için 10/10 ☐ → 🟢 olmalı.**

---

## Negotiable List (referans — bunlar olmadan production MVP denebilir)

- Channel sayısı (5 hedef, ama email + Slack + webhook MVP-dar yeter)
- Workflow editor UI (no-code)
- Brand customization (logo/color/footer)
- A/B testing
- In-app inbox UI (API var, UI v1)
- Per-tenant provider config
- Multi-step ardışık workflow
- Conditional rule engine
- Mobile push (FCM/APNS) — Faz 22.2 ile birlikte v1

Bu negotiable özellikler **production MVP sonrası v1+'ya alınır**.

---

## Update Discipline

Her sub-faz tamamlandığında:
1. İlgili must-have satırının `Status` ☐ → 🟡 → 🟢 ilerletilir
2. Kabul kriteri checkbox'ları tek tek işaretlenir (`docs/faz-23-evidence/...` evidence dosyası ile)
3. PR açılır, Codex review verdict (D29-NOTIFY 3-katman kanıt) AGREE → merge
4. Sub-faz geçişi (örn. 23.1 → 23.2) tüm 23.1 must-have'leri 🟢 olduğunda yapılır
