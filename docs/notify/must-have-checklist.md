# Notification Platform — 10 Must-Have Çizgisi

> **Status**: ACTIVE (charter base 2026-05-05; **truth alignment 2026-05-09 Session 39 post 11-PR cycle**)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md) D46
> **Codex thread**: `019df86f` (charter) + `019e0892` (Session 39 retrospective) + `019e0bb6` (PR review chain)

Bu 10 özellik **production MVP demek için olmazsa olmaz**. Negotiable değil. Bu liste eksiksiz olmadan "Faz 23 production ready" denmez.

Diğer ~130 özellik **negotiable** (kanal sayısı, UI yüzeyleri, workflow editor, A/B testing, brand customization).

> **Faz 2 — GitHub Project migration (2026-05-17)** — Production MVP gate takibi [platform Roadmap board](https://github.com/users/Halildeu/projects/2) #778 (`Kind=gate`). Bu doküman 10 must-have'in **kabul kriteri + evidence path**'inin canonical kaynağı kalır.
>
> **⚠️ Status marker'ları STALE — historical (2026-05-09 Session 39).** Bu dokümandaki tüm status ifadeleri (aşağıdaki "Status" tablosu, "#7/#8/#10 partial" bölüm başlıkları, "Özet Sayım", "~%85 coverage") 2026-05-09 dondurulmuş snapshot'tır; **canonical değildir**. Canonical live status: board #778 + `docs/state/current-state.md` + canonical status authority surfaces — [milestones.md](milestones.md) + [sprint-plan.md](sprint-plan.md) + [risk-register.md](risk-register.md) + [feature-matrix.md](feature-matrix.md) + [RB-faz-23-charter.md](../runbooks/RB-faz-23-charter.md).
>
> **Session 49+ truth-sync attestation 2026-05-23/24** (PR #1002 + #1003 + #1005 + #1006 + #1009 + #1011 doc-truth-sync chain + Codex `019e599c` H read-only live evidence re-sync):
> - **R2 KVKK CLOSED 2026-05-23** via Codex `019e5189` final legal verdict (kullanıcı kararı: Codex istişare verdict'i = kabul edilen hukuk onayı) — earlier "#7 external legal review ETA 2026-05-25" residual is resolved.
> - **#7 KVKK** canonical state: 🟢 (R2 closed; admin + subscriber self-service `DELETE/GET /audit/me` LIVE via M3 PR-K1 erasure ledger + 6/7 K-PR chain MERGED; K6 tenant-scoped DPO authz P1 non-blocking 23.2.B follow-up).
> - **#8 Preference** canonical state: 🟢 source-ready/live — M3 T1.1 23.2.A trilogy MERGED + sprint-plan T3.2 8/8 LIVE; M5 23.5 charter satır 53 + milestones.md M5 line 137 "🟢 source-ready + acceptance candidate" (full 🟢 closure board #757 final acceptance + live cluster runtime evidence gate ayrı); canonical surface (milestones.md M5) board acceptance kararına gider.
> - **#10 Observability**: observability 🟢 LIVE (Tempo OTLP + 25 PrometheusRule + Grafana 15-panel); **D43 outage fallback 🟢 SMTP-only v1 accepted** (per user decision 2026-05-24; Codex strategic thread `019e5b9c` REVISE absorb). D43 v1 acceptance = Alertmanager direct-fallback SMTP receiver (notification-orchestrator-independent credentials). Historical drill evidence retained as drill audit only: first controlled drill 2026-05-10 SMTP receipt Mailpit `[FIRING:1] NotifyServiceAbsent` 00:22:33Z + BL-008 mock-receipt drill 2026-05-24 (webhook-receiver + Mailpit dual). **Slack adoption DEFER future trigger**. **Production-ready claim requires prod cluster SMTP direct receipt + recovery proof** (board #854 rescope SMTP-only prod activation + Operator v0.90.1 `auth_*_file` schema fix). Original board #853 + #1012 (Slack-dependent) → DEFER. Evidence: `docs/faz-23-evidence/2026-05-24-d43-slack-defer-smtp-only-acceptance.md`.
> - **Aggregate**: must-have #1-#7 + #9 🟢 + #8 🟢 source-ready/live + #10 🟢 **SMTP-only D43 v1 accepted** (per user decision 2026-05-24; Slack DEFER); prod activation operator-external residual (board #854 SMTP-only rescope); production-ready claim DEĞİL (canonical status authority decides).
>
> Bu attestation block status marker'ları DEĞİŞTİRMEZ — aşağıdaki Session 39 snapshot historical olarak korunur; current-state için canonical surface'lere git.

## 🟢 Status (2026-05-09 Session 39, Codex `019e0bff` iter-1 absorb)

| # | Must-have | Status | Sub-faz |
|---|---|:---:|---|
| 1 | Notification Intent + Delivery Log Schema | 🟢 done | 23.1 |
| 2 | Idempotency + Dedupe | 🟢 done | 23.1 |
| 3 | Domain-Side Outbox Contract | 🟢 done | 23.1 |
| 4 | Retry Exponential Backoff + DLQ + Manual Replay | 🟢 done | 23.1 |
| 5 | OpenFGA Hard-Deny + Org Boundary | 🟢 done | 23.1 + 23.4 PR-5.x strict cutover |
| 6 | Vault/ESO Provider Credentials + No Secret Logging | 🟢 done | 23.2 (PR #424) |
| 7 | PII Redaction + Retention/Anonymization Policy (KVKK) | 🟡 partial (retention LIVE; admin erasure source-ready/R2 legal; **subscriber self-service `DELETE/GET /audit/me` GERÇEK PENDING** — M3 stale audit 2026-05-09) | 23.1 (PII) + 23.2 (retention LIVE PR #427/#437; admin erasure `AdminErasureController` source-ready; subscriber self-service endpoint backend'de YOK) |
| 8 | Preference / Opt-out + Critical Bypass Policy | 🟡 partial (source-ready; D29-Authorized acceptance gate BLOCKED on RAID I6) | 23.2.A (API source-ready/live) + 23.5 (UI pending) — M3 stale audit 2026-05-09 |
| 9 | Template Versioning + Safe Interpolation | 🟢 done | 23.1 |
| 10 | Observability + Outage Fallback | 🟡 partial (observability LIVE; **T1.4 D43 outage fallback 4-PR source-ready** Session 41 2026-05-09 — drill execution operator-bound) | 23.2 (PR #425/#428/#430/#431/#433/#435/#436 + #457/#462/#463/#464) |

**Sayım** (Codex `019e0bff` iter-1 self-consistency fix):
- 🟢 fully done: **7** (#1, #2, #3, #4, #5, #6, #9)
- 🟡 partial: **3** (#7 retention LIVE + erasure source-ready/legal review pending; #8 preference source-ready + acceptance/auth gate; #10 observability LIVE + D43 pending) — M3 stale audit 2026-05-09 #8 status update
- ⏳ pending: **0** (#8 source-ready demoted to partial)

**Net must-have coverage estimate** (NOT a "production ready" guarantee — kabul kriteri evidence path tek tek doğrulanmadan production claim yapılmaz; M3 stale audit 2026-05-09 5-state matrix re-baseline):
- 7 done × 1.0 + 3 partial (source-ready/acceptance gate) × 0.5 = **8.5/10 = ~85% must-have coverage**
- **Disclaimer**: "partial" weight 0.5 semantik — gerçek source-ready bias var; #7 erasure/legal review (R2), #8 preference acceptance gate (RAID I6), #10 D43 outage fallback gerçek implementation pending
- Önceki "8/10 = ~80%" formülü 7+2+1 modeline aitti; #8 demote sonrası 7+3+0 modelinde formül 8.5/10

---

## #1 — Notification Intent + Delivery Log Schema 🟢 done

**Açıklama**: Her notification akışı normalize edilmiş bir veri modeline oturmalı. `org_id`, `topic_key`, `recipient`, `template_version`, `status`, `correlation_id` — bu 6 alan **zorunlu**.

**Sub-faz**: 23.1 (Kernel) — LIVE 2026-05-08

**Kabul kriteri**:
- [x] `notify.notification_intent` tablosu mevcut (8 zorunlu kolon)
- [x] `notify.notification_delivery` tablosu mevcut (channel + status + recipient_hash + provider_msg_id)
- [x] `notify.audit_event` tablosu mevcut (event_type + correlation_id + redacted details) — V8 migration audit_event_v2 partitioned
- [x] V1+V8 Flyway migration applied (V1 base schema, V8 partition cutover)
- [x] FK constraint `notification_delivery.intent_id → notification_intent.intent_id`
- [x] Index `(status, scheduled_at)` `(org_id, topic_key)` `(correlation_id)`

**Evidence**: `docker exec platform-pg-prod psql -U platform -d notify_db -c "\dt notify.*"` → 8+ tables; V8 migration LIVE; partition list `audit_event_v2_2026_02..08`

**Kanıt**:
```bash
psql -c "\d notify.notification_intent"
psql -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'notify';"  # >= 8
```

**Detay**: `docs/notify/event-contract.md` §4 PostgreSQL Schema

---

## #2 — Idempotency + Dedupe 🟢 done

**Açıklama**: Retry, saga replay, manual replay duplicate notification üretmemeli. 24h içinde aynı `idempotency_key` ikinci kez gelirse → original intent_id döndür, no extra delivery.

**Sub-faz**: 23.1 (Kernel) — LIVE 2026-05-08

**Kabul kriteri**:
- [x] `notification_intent.idempotency_key` UNIQUE constraint (within `org_id`)
- [x] 24h dedupe window: `NOTIFY_IDEMPOTENCY_WINDOW_HOURS=24` env active
- [x] Saga replay testi: OutboxPoller advisory lock prevents double-process
- [x] Domain service docs: `idempotency_key` convention documented in event-contract.md

**Evidence**: pod env shows `NOTIFY_IDEMPOTENCY_WINDOW_HOURS=24`; OutboxPoller logs show `pg_try_advisory_xact_lock` used; backend integration test `NotificationIntentControllerTest.idempotencyDedupe`

**Kanıt**:
```bash
# Test: aynı idempotency_key 2 kez POST
curl -X POST .../intents -d '{"idempotency_key":"test-1",...}'  # 202
curl -X POST .../intents -d '{"idempotency_key":"test-1",...}'  # 409, original intent_id
psql -c "SELECT count(*) FROM notify.notification_delivery WHERE intent_id = '...'"  # 1, not 2
```

---

## #3 — Domain-Side Outbox Contract 🟢 done

**Açıklama**: Admin invite, drift alarm, break-glass audit, password reset — **direct provider çağırmaz**. Kendi DB'sinde transactional outbox row INSERT eder; `notification-orchestrator` outbox poll cycle ile alır.

**Sub-faz**: 23.1 (Kernel) — LIVE 2026-05-08

**Kabul kriteri**:
- [x] Her domain service'in `notification_outbox` tablosu var (örn. `auth.notification_outbox`)
- [x] Domain transaction: `@Transactional` ile domain INSERT + outbox INSERT atomic
- [x] OutboxPoller PG advisory lock ile poll (5s cycle, ≤2s pickup latency)
- [x] Outbox row PROCESSED status'e gider (orchestrator picked up)
- [x] `docs/notify/event-contract.md` §4 outbox pattern documented

**Evidence**: prod logs `OutboxPoller activated: owner=notification-orchestrator-... pollDelay=5000ms`; cycle counter ~442 on prod; PR #347 alarm-receiver integration LIVE.

**Kanıt**:
- `docs/notify/event-contract.md` §4 ve §6 referansı
- Drift alarm receiver entegrasyonu: PR #347 alarm-receiver → outbox → orchestrator (Faz 23.1 evidence)

**Out of scope (negotiable)**:
- Central event bus (Kafka/RabbitMQ) — Codex REVISE: Mongo/Redis/RabbitMQ stateful explosion yasak. Per-domain outbox baseline.

---

## #4 — Retry Exponential Backoff + DLQ + Manual Replay 🟢 done

**Açıklama**: Provider call fail olduğunda retry; max attempt aşıldığında DLQ; admin manual replay edebilir. Silent drop **YASAK**.

**Sub-faz**: 23.1 (Kernel) — LIVE 2026-05-08

**Kabul kriteri**:
- [x] Retry policy: exponential backoff (`maxAttempts=5`, `backoffInitialMs=30000`, `backoffMultiplier=2.5`, `maxBackoffMs=3600000`, `jitterRatio=0.25`)
- [x] `notification_delivery.attempt_count` increment
- [x] `notification_delivery.next_retry_at` + RetryWorker pollar (`batchSize=50 maxAttempts=5 pollDelay=5000ms`)
- [x] Max attempt aşıldığında `notify.dead_letter` tablosuna kopyala + status FAILED
- [x] `POST /api/v1/notify/admin/dlq/{delivery_id}/replay` endpoint
- [x] **Alertmanager rule**: `NotifyDlqSustained` (PR #425, rate>5/sec) + `NotifyDlqUnreplayed` (>100) + `NotifyDlqSloBurnRateFast/Slow/Medium` (PR #433 SLO 99.5% with multi-window burn rate)
- [x] Replay audit: `audit_event.event_type = MANUAL_DLQ_REPLAY`

**Evidence**: prod log `RetryWorker activated: batchSize=50 maxAttempts=5 pollDelay=5000ms scheduling=true`; 25 PrometheusRule alerts LIVE; AdminDeliveryController.replayDlq endpoint exists.

**Kanıt**:
- Test: provider mock 5xx → retry chain log
- DLQ row INSERT after max attempt
- Admin replay: DLQ row → new delivery attempt

---

## #5 — OpenFGA Hard-Deny + Org Boundary 🟢 done (with strict cutover Faz 23.4)

**Açıklama**: Cross-tenant notification leak **kapatılır**. `subscriber:<id>#can_receive notification_topic:<key>` tuple kontrolü yapılmadan delivery yok. **Faz 23.4 strict cutover** (PR-5.x): `NotifyOrgAccessGuard` + `SubscriberIdentityGuard` strict mode prod LIVE.

**Sub-faz**: 23.1 (Kernel) + 23.4 (strict cutover) — LIVE 2026-05-08

**Kabul kriteri**:
- [x] `notification_intent.org_id` NOT NULL
- [x] OpenFGA tuple model: `notification_topic` type + `can_receive` relation
- [x] Permission-service üzerinden `/check` çağrısı (mevcut Zanzibar plane reuse) — DeliveryEligibilityService activated `authz=true`
- [x] Allow case test: tuple var → delivery PROCEEDS
- [x] Deny case test: tuple yok → audit `BLOCKED_BY_AUTHZ`, no delivery
- [x] Cross-org test: org_X subscriber için org_Y intent → audit `BLOCKED_BY_AUTHZ`
- [x] **NotifyOrgAccessGuard strict** (PR-5.4): `NOTIFY_SECURITY_DEFAULT_ORG_ID=""` → silent-pass closed; F3 cutover gate sustained 0-emit on source="default" + source="none"
- [x] **SubscriberIdentityGuard strict** (PR-5.5): `NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_STRICT="true"` → no_auth + non_jwt fail-close; denied counter active
- [x] **5 strict cutover alerts LIVE**: NotifyOrgAccessDeniedStorm (critical+page), NotifySubscriberIdentityDeniedStorm (warning+security_impact=critical), source default/none regression sentinels, telemetry absent guard

**Evidence**: env shows both strict env vars; PrometheusRule prometheus query confirms 5 strict-cutover alerts inactive (correctly-pending where applicable); 4h+ sustained F3 gate observation evidence in handoff doc.

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

## #6 — Vault/ESO Provider Credentials + No Secret Logging 🟢 done

**Açıklama**: Provider API key, SMTP password, Slack webhook token — Vault'tan ESO ile sync. Credential **log'a yazılmaz**.

**Sub-faz**: 23.2 (Production MVP dar) — LIVE 2026-05-08 (PR #424)

**Kabul kriteri**:
- [x] Vault path `kv/platform/notification-orchestrator` mevcut (flat path, Codex thread `019e08df` REVISE absorb — auth-service / user-service convention; SMTP/Slack/NetGSM provider creds aynı path'e property olarak eklenir veya provider-specific path'lere ayrılır gerek olduğunda)
- [x] ESO ExternalSecret manifest `kustomize/overlays/{test,prod}/eso/notify/externalsecret-notify.yaml` LIVE
- [x] Vault policy `eso-runtime` `kv/data/platform/notification-orchestrator` read içerir (`bootstrap/vault-policies/common/eso-runtime.hcl`)
- [x] Spring Boot @Value injection (env var) — kod içinde hardcoded credential yok
- [x] Log audit: redaction MDC pattern + ProductionConfigValidator fail-close on dev sentinel values
- [x] Provider config DB row: encrypted at rest (PG default) + credential reference (Vault path) only

**Evidence (PR #424 LIVE)**:
- ExternalSecret SecretSynced=True 12s, ownerReferences=ExternalSecret
- Secret 5 keys: SPRING_DATASOURCE_USERNAME/PASSWORD, NOTIFY_ADAPTERS_WEBHOOK_SIGNING_SECRET, NOTIFY_AUTHZ_INTERNAL_API_KEY, NOTIFY_REDACTION_PEPPER
- Pod 0 ERROR post-swap, byte-identical content takeover
- Codex thread `019e08df` iter-3 AGREE (cross-AI peer review HARD RULE)

**Kanıt**:
```bash
kubectl get externalsecret -n platform-test | grep notify
psql -c "SELECT credential_ref FROM notify.provider_config LIMIT 1"  # vault://kv/platform/notification-orchestrator (or provider-specific path)
kubectl logs deploy/notification-orchestrator | grep -iE "password|token|secret" | wc -l  # 0
```

---

## #7 — PII Redaction + Retention/Anonymization Policy (KVKK) 🟡 partial (retention LIVE; erasure API pending)

**Açıklama**: Mail body, SMS body, kişisel bilgi log'a/audit'e yazılmaz. Sadece `template_id`, `recipient_hash` (sha256), `org_id`, `correlation_id`. Retention policy var.

**Sub-faz**: 23.1 (Kernel — PII redaction LIVE) + 23.2 (MVP-dar retention LIVE PR #427/#437) + **23.2.B (erasure API + right-to-information — Faz 23.2 closure)**

> **Sub-faz authority note (2026-05-09 truth alignment iter-2)**: Erasure API (KVKK Art.11) sub-faz authority = **23.2.B** per Charter [`RB-faz-23-charter.md`](../runbooks/RB-faz-23-charter.md) + sprint-plan T1.2 + milestones M3 DoD. Faz 23.7 yalnız Push (FCM/APNS/Web Push) hattıdır; KVKK erasure 23.7'ye dahil değildir.

**Kabul kriteri**:
- [x] `audit_event.details` JSONB: payload value yok, sadece metadata
- [x] `notification_delivery.recipient_hash` sha256(address) — HMAC pepper from Vault `kv/platform/notification-orchestrator.redaction_pepper`
- [x] Log MDC pattern: `correlation_id`, `org_id`, `template_id`, `recipient_hash` — body yok
- [x] **Retention policy**: AuditPartitionRetentionService activated `dryRun=false` LIVE both clusters (PR #427 + #437); `retentionDays=90 cron=0 0 2 * * * graceHours=24 futureMonths=3`; first real cycle 2026-05-09 `Created future partition: audit_event_v2_2026_08`
- [ ] **KVKK Art.11 erasure API**: `DELETE /audit/me` → payload purge, recipient_hash kalır — ⏳ pending Faz **23.2.B** backend (sprint-plan T1.2)
- [x] Audit append-only enforcement: `CREATE RULE no_update/delete` (V8 migration trigger)
- [x] **Backend test coverage** (Session 39 PR #130): `AuditPartitionRetentionDetachDropTest` 4 methods covering DETACH/DROP/cutoff/idempotency code paths

**Evidence**:
- Prod activation log: `AuditPartitionRetentionService activated: retentionDays=90 cron=0 0 2 * * * graceHours=24 dryRun=false futureMonths=3 schedulingEnabled=true`
- First real cycle (2026-05-09 manual trigger via cron override): `cycle: future_created=1 detached=0 dropped=0 dry_run=false`; `audit_event_v2_2026_08` partition created in prod DB
- Codex thread `019e090d` C.2 prep + `019e0bb6` peer review chain
- `bootstrap/vault-policies/common/eso-runtime.hcl` extended with `kv/data/platform/notification-orchestrator` read

**Pending sub-tasks (23.2.B KVKK erasure)**:
- ⏳ `DELETE /api/v1/audit/me` endpoint (subscriber's own audit history erasure)
- ⏳ `GET /api/v1/audit/me` endpoint (KVKK Art.13 right-to-information)
- ⏳ Erasure runbook: payload purge SQL pattern + recipient_hash preservation

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

## #8 — Preference / Opt-out + Critical Bypass Policy 🟡 partial (source-ready / acceptance pending)

> **M3 Stale Audit 2026-05-09 update** (Codex `019e0c28` strategic finding): Backend code source-ready (V1 schema `subscriber_preference` table + `PreferenceController` 290 satır + `SubscriberPreferenceService` 414 satır + `DeliveryEligibilityService` BLOCKED_BY_PREFERENCE + critical bypass severity logic). Acceptance gate D29-Authorized BLOCKED on RAID I6 Keycloak credential. Detay: [m3-stale-audit-2026-05-09.md](m3-stale-audit-2026-05-09.md).

**Açıklama**: Subscriber kanal/topic bazında opt-out edebilir. Ancak `severity=critical` veya `data_classification=security` bu opt-out'u **bypass eder**. Diğerleri respect.

**Sub-faz**: 23.2 (MVP-dar API) + 23.5 (UI)

**Kabul kriteri** (5-state matrix per Codex `019e0c28` strategic finding):
- [x] `notify.subscriber_preference` tablosu (subscriber_id + topic_key + channel + enabled) — V1 schema source-ready/live-deployed ✅
- [x] Preference API: `GET /preferences/me` + `PUT /preferences/me` + `DELETE /me/{id}` + `DELETE /me` — `PreferenceController` 290 satır source-ready/live-deployed ✅
- [🟡] Send pipeline'da preference check: `enabled=false` → audit `BLOCKED_BY_PREFERENCE`, no delivery — `DeliveryEligibilityService` source-ready/live-deployed; **D29-Authorized acceptance test BLOCKED on RAID I6**
- [🟡] **Critical bypass**: `severity=critical` OR `data_classification=security` → preference bypass + audit `PREFERENCE_BYPASSED_CRITICAL` — severity bypass source-ready; data_classification security bypass acceptance test gerek
- [🟡] Quiet hours opt-out: `severity=critical` quiet'i geçer — partial source; acceptance gate
- [🟡] Frequency limit opt-out: `severity=critical` frequency limit'i geçer — partial source; acceptance gate
- [ ] Unsubscribe link footer (email): RFC 8058 List-Unsubscribe-Post header — TBD template engine review

**Status**: 🟡 partial — **2/7 source-ready/live-deployed/acceptance complete (V1 + REST API)**, 4/7 source-ready/live-deployed (acceptance gate D29-Authorized BLOCKED on RAID I6), 1/7 TBD. Gerçek residual ~3h acceptance test + auth flow setup.

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

## #9 — Template Versioning + Safe Interpolation 🟢 done

**Açıklama**: Geçmiş delivery hangi template ile gitti **sorgulanabilir**. Template injection (XSS, SSTI) **yok**: variable interpolation güvenli.

**Sub-faz**: 23.1 (Kernel) — LIVE

**Kabul kriteri**:
- [x] `notify.notification_template` (template_id + version + body + locale)
- [x] Version immutable: yeni versiyon yeni row INSERT, eski row kalır
- [x] `notification_intent.template_id + template_version` → audit'te kayıt
- [x] Thymeleaf safe mode: `th:utext` (raw HTML) **YASAK**, sadece `th:text` (escaped)
- [x] Test: malicious payload `<script>alert(1)</script>` → output escaped
- [x] Test: SSTI attempt rejected (whitelist variable namespace)
- [x] Locale fallback: tr-TR → tr → en-US → en → default

**Evidence**: V1 migration table mevcut; backend `TemplateService` + Thymeleaf TemplateEngine safe mode; integration test `NotificationTemplateServiceTest`

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

## #10 — Observability + Outage Fallback 🟡 partial (observability LIVE; D43 outage fallback pending)

**Açıklama**: Prometheus metrics, DLQ alert, correlation_id tracing. Kritik yan: notification-orchestrator down olduğunda **drift/break-glass alarmı kendi içinden değil, Alertmanager direct**'tan gelir.

**Sub-faz**: 23.1 (Kernel — observability) + 23.2 (MVP-dar fallback bypass — pending)

**Kabul kriteri**:
- [x] Prometheus endpoint `/actuator/prometheus` (Spring Actuator) LIVE
- [x] **Metrics**: notify_dispatch_outcome_total, notify_dlq_terminated_total, notify_queue_pending_intents, notify_queue_retry_due, notify_dlq_unreplayed, notify_audit_retention_*, notify_org_access_match_total, notify_subscriber_identity_match_total, notify_worker_cycles_total
- [x] Distributed tracing infrastructure ready (MANAGEMENT_TRACING_ENABLED gate; OTLP to Tempo deferred to Faz 23.8)
- [x] **Alertmanager rules**: 25 PrometheusRule alerts LIVE prod (4 critical/page + 21 warning); NotifyDlqSustained rate>5/sec, NotifyDlqUnreplayed >100, NotifyDlqSloBurnRateFast/Slow/Medium/ErrorBudgetBurning (PR #433 SLO 99.5% multi-window)
- [x] **Grafana dashboard**: 15 panel (sidecar imported) including burn rate overlay + budget remaining + 28d compliance
- [ ] **Outage fallback** (D43): ⏳ pending
  - ⏳ Notification-orchestrator down → Alertmanager direct Slack/SMTP separate credentials
  - 🟡 Drift alarm-receiver kendi içinde fallback chain (PR #347 partial)
  - ⏳ Break-glass token script: dual-channel
  - ⏳ `docs/runbooks/RB-notification-outage-fallback.md` to be written
  - ⏳ Test: orchestrator scale=0 → Alertmanager #alerts direct mesaj

**Evidence (LIVE 2026-05-09)**:
- 25 PrometheusRule alerts via `wget -qO- prometheus:9090/prometheus/api/v1/rules?type=alert` (22 inactive + 1 pending + 0 firing in last check)
- 18 SLO recording rules: notify:dispatch:terminal_total:rate{5m,30m,1h,6h,24h,72h}, notify:dlq:terminated_total:rate{5m,30m,1h,6h,24h,72h}, notify:dlq:burn_rate:{5m,30m,1h,6h,24h,72h}
- Grafana ConfigMap notification-orchestrator-dashboard 15 panel — sidecar imported `Writing /tmp/dashboards/notification-orchestrator.json`
- Codex thread chain: `019e0892` strategic + `019e0935` dashboard iter + `019e094a` SLO iter + `019e0921` retention alerts iter + `019e0ba9` lock alert + `019e0bb6` final review

**Pending sub-tasks (D43 outage fallback — Faz 23.2.D)**:
- ⏳ Alertmanager bridge dual-route config (orchestrator down → SMTP direct)
- ⏳ Separate credential set in Vault for outage path
- ⏳ Drift alarm-receiver fallback chain extension
- ⏳ Break-glass dual-channel script
- ⏳ Outage fallback runbook
- ⏳ Drill test execution + evidence

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

## Özet Sayım (truth alignment 2026-05-09)

| # | Must-have | Sub-faz | Status |
|---|---|---|:---:|
| 1 | Intent + delivery log schema | 23.1 | 🟢 |
| 2 | Idempotency + dedupe | 23.1 | 🟢 |
| 3 | Domain-side outbox | 23.1 | 🟢 |
| 4 | Retry + DLQ + manual replay | 23.1 | 🟢 |
| 5 | OpenFGA hard-deny + org boundary | 23.1 + 23.4 | 🟢 (strict cutover LIVE) |
| 6 | Vault/ESO + no secret logging | 23.2 | 🟢 (PR #424) |
| 7 | PII redaction + KVKK retention | 23.1 + 23.2 (retention LIVE) + 23.2.B (erasure pending) | 🟡 (retention LIVE; erasure API pending) |
| 8 | Preference + critical bypass | 23.2 | ⏳ |
| 9 | Template versioning + safe interpolation | 23.1 | 🟢 |
| 10 | Observability + outage fallback | 23.1 + 23.2 | 🟡 (observability LIVE; D43 outage fallback pending) |

**Production MVP demek için 10/10 ☐ → 🟢 olmalı.**

**Snapshot (2026-05-09 Session 39 truth alignment, Codex `019e0bff` self-consistency)**:
- 🟢 fully done: 7 (#1, #2, #3, #4, #5, #6, #9)
- 🟡 partial: 3 (#7 retention LIVE + erasure source-ready/legal review pending; #8 preference source-ready + acceptance/auth gate; #10 observability LIVE + D43 pending) — M3 stale audit 2026-05-09 #8 demoted to partial source-ready bias
- ⏳ pending: 0
- **Net must-have coverage**: ~85% (8.5/10 — M3 stale audit 2026-05-09 5-state matrix; 7 done × 1.0 + 3 partial × 0.5; partial weight 0.5 semantik, source-ready bias var); **NOT production-ready guarantee** — #7 erasure subscriber self-service + R2 legal, #8 RAID I6 acceptance gate, #10 D43 gerçek pending
- **Production MVP gates beyond must-have**: 23.1 D29-NOTIFY-Functional 3-channel evidence, 23.2 erasure/preference/outage fallback closure, 23.9 72h observation + rollback prova execution

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
