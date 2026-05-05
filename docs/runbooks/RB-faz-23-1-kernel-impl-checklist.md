# RB-faz-23-1-kernel-impl-checklist — Notification Orchestrator Kernel Implementation

> **Status**: DRAFT (Faz 23.0 charter — 2026-05-05)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Sub-faz**: 23.1 (Kernel/Closed Beta — 3-4 hafta)
> **Bağımlılık**: 🔴 Faz 22.1.1b III review verdict (`I-staged-pending-schema-rev`) — schema fix-forward sonrası unblock

Faz 23.1 implementation başlangıcı için somut implementasyon checklist'i. Spring Boot module skeleton + DB migration + 3 kanal (email + Slack + webhook) + outbox + retry/DLQ + audit + OpenFGA + PII redaction + metrics + Mailpit/WireMock.

## Önkoşul Kontrolleri

- [ ] Faz 22.1.1b III review verdict `I-staged-pending-schema-rev` → schema fix-forward (1-2 saat)
- [ ] platform-backend sub-branch'inde 22 dosya commit + image rebuild + cluster deploy
- [ ] D29-EA-Functional live smoke PASS (allow/deny/unauth/fail-closed)
- [ ] OpenFGA model alignment kanıtı (uppercase ENDPOINT_ADMIN_MODULE → lowercase endpoint_admin)
- [ ] Bu PR (`feat/faz-23-0-notify-charter`) merge edildi (8 OQ resolution charter close için)

## Boundary

**Cross-repo write** (`platform-backend/notification-orchestrator/`) → ADR-0011 BG-1 `boundary-cross + user-approval-required`. Auto mode'da yapılamaz; explicit kullanıcı onayı + PR boundary declaration ile.

## Skeleton Yapısı

### 1. platform-backend repo (Java/Spring Boot — cross-repo)

```
platform-backend/notification-orchestrator/
├── pom.xml                                    # Spring Boot 3.x parent
├── src/main/
│   ├── java/com/serban/notify/
│   │   ├── NotificationOrchestratorApplication.java
│   │   ├── api/
│   │   │   ├── NotificationIntentController.java
│   │   │   ├── PreferenceController.java
│   │   │   ├── AuditController.java
│   │   │   └── AdminDlqController.java
│   │   ├── domain/
│   │   │   ├── NotificationIntent.java        # JPA entity
│   │   │   ├── NotificationDelivery.java
│   │   │   ├── NotificationTemplate.java
│   │   │   ├── SubscriberPreference.java
│   │   │   ├── ProviderConfig.java
│   │   │   ├── ProviderConfigHistory.java
│   │   │   ├── AuditEvent.java
│   │   │   ├── DeadLetter.java
│   │   │   └── IdempotencyKey.java            # 24h TTL window (Codex post-impl fix)
│   │   ├── adapter/
│   │   │   ├── ChannelAdapter.java            # interface
│   │   │   ├── SmtpAdapter.java
│   │   │   ├── SlackAdapter.java
│   │   │   ├── WebhookAdapter.java            # generic + HMAC
│   │   │   └── (sms/in-app/teams/push 23.3+)
│   │   ├── worker/
│   │   │   ├── OutboxPoller.java              # PG advisory lock
│   │   │   ├── RetryWorker.java               # exponential backoff
│   │   │   └── DeadLetterMover.java
│   │   ├── template/
│   │   │   ├── TemplateRenderer.java          # Thymeleaf safe-mode
│   │   │   └── VersionResolver.java           # locale fallback chain
│   │   ├── preference/
│   │   │   ├── SubscriberPreferenceService.java
│   │   │   └── CriticalBypassPolicy.java      # severity=critical override
│   │   ├── audit/
│   │   │   ├── AuditEventPublisher.java       # PII redaction
│   │   │   └── PiiRedactor.java
│   │   ├── classification/
│   │   │   └── DataClassificationPolicy.java  # transactional/security/commercial/system
│   │   ├── abuse/
│   │   │   └── AbusePreventionGuard.java      # rate limit + duplicate flood + webhook fan-out cap
│   │   ├── incident/
│   │   │   └── (Faz 23.2 — outage fallback bypass coordination)
│   │   ├── authz/
│   │   │   └── OpenFgaScopeChecker.java       # subscriber#can_receive notification_topic
│   │   └── config/
│   │       ├── ProviderConfigLoader.java
│   │       ├── ChannelConfigRegistry.java
│   │       └── RateLimiter.java
│   └── resources/
│       ├── application.yml
│       ├── application-test.yml
│       ├── application-prod.yml
│       ├── db/migration/
│       │   └── V1__init_notify_schema.sql      # 9 tablo (event-contract §4)
│       └── templates/                          # Thymeleaf templates
│           └── (sub-faz 23.4 ile populate)
└── src/test/
    ├── java/com/serban/notify/
    │   ├── api/...                             # MockMvc REST tests
    │   ├── adapter/...                         # WireMock provider tests
    │   ├── worker/...                          # @Testcontainers PG tests
    │   ├── e2e/
    │   │   └── DriftAlarmFlowIntegrationTest.java  # outbox → orchestrator → Mailpit
    │   └── ...
    └── resources/
        ├── application-test.yml                 # Mailpit + WireMock
        └── fixtures/
            └── (intent payload örnekleri)
```

### 2. gitops repo (kustomize manifest — bu repo, in-scope auto mode)

```
kustomize/base/apps/notification-orchestrator/
├── kustomization.yaml
├── deployment.yaml
├── service.yaml
├── configmap.yaml
├── servicemonitor.yaml                         # Prometheus
└── networkpolicy.yaml

kustomize/overlays/test/notification-orchestrator/
├── kustomization.yaml                          # replicas:0 default (D17)
├── deployment-patch.yaml                       # image digest pin
└── eso/
    ├── kustomization.yaml
    └── externalsecret-notify.yaml              # vault://kv/platform/notify/*

kustomize/overlays/prod/notification-orchestrator/
├── kustomization.yaml                          # replicas:2 (D21)
├── deployment-patch.yaml                       # image digest pin (sha-<short>)
└── eso/
    ├── kustomization.yaml
    └── externalsecret-notify.yaml
```

## Implementation Sırası (haftalık)

### Hafta 1 — Foundation

- [ ] Spring Boot module skeleton (`pom.xml` + Application class + application.yml)
- [ ] Flyway V1 migration (9 tablo: notification_intent + notification_delivery + notification_template + subscriber_preference + provider_config + provider_config_history + audit_event + dead_letter + idempotency_key + per-domain outbox)
- [ ] Domain entity'ler (JPA @Entity)
- [ ] Repository'ler (JpaRepository)
- [ ] application-test.yml (Mailpit + WireMock + Testcontainers PG)
- [ ] Smoke test (Spring Boot starts, DB migration applies, /actuator/health 200)

### Hafta 2 — Channel Adapters + Outbox

- [ ] `ChannelAdapter` interface
- [ ] SmtpAdapter (Spring Boot Starter Mail, JavaMailSender)
- [ ] SlackAdapter (slack-api-java-sdk + Vault webhook URL)
- [ ] WebhookAdapter (HMAC SHA256 signed POST + HttpClient)
- [ ] OutboxPoller (PG advisory lock + 5s poll cycle)
- [ ] AbusePreventionGuard (rate limit Caffeine cache)

### Hafta 3 — Authz + Preference + Audit

- [ ] OpenFgaScopeChecker (permission-service /check API)
- [ ] SubscriberPreferenceService (CRUD + critical bypass)
- [ ] AuditEventPublisher (transactional INSERT + PII redaction)
- [ ] PiiRedactor (recipient hash sha256 + pattern match for body/url)
- [ ] DataClassificationPolicy (4 sınıf — quiet bypass + retention)

### Hafta 4 — Workers + Tests + Integration

- [ ] RetryWorker (exponential backoff: 30s/1m/5m/15m/1h, max 5 attempt)
- [ ] DeadLetterMover (max retry → DLQ INSERT + audit)
- [ ] Admin DLQ replay endpoint
- [ ] DriftAlarmFlowIntegrationTest (outbox → orchestrator → Mailpit end-to-end)
- [ ] Prometheus metrics export (`/actuator/prometheus`)
- [ ] OpenAPI spec (Springdoc)

## Kabul Kriteri (Faz 23.1 Kernel D29-NOTIFY)

### D29-NOTIFY-Up

- [ ] Pod Ready (`kubectl get pod -n platform-test`)
- [ ] `/actuator/health/readiness` → 200
- [ ] V1 migration applied (`psql -c "\dt notify.*"` → 9 tablo)
- [ ] Vault/ESO secret sync (`kubectl get externalsecret`)
- [ ] OutboxPoller alive (log "outbox poll cycle" < 60s gap)
- [ ] DLQ size = 0

### D29-NOTIFY-Functional (3 kanal)

- [ ] **Email**: Mailpit'te test mesajı görünür (template render + multipart HTML+text + dev DKIM signed)
- [ ] **Slack**: Test channel'a mesaj geldi (incoming webhook 200 OK)
- [ ] **Webhook**: HMAC-signed POST → 2xx response + signature verify on receiver

### D29-NOTIFY-Authorized

- [ ] OpenFGA allow case: `subscriber:1#can_receive notification_topic:test` → delivery succeeds
- [ ] OpenFGA deny case: tuple yok → audit `BLOCKED_BY_AUTHZ`, no delivery
- [ ] Preference deny case: `enabled=false` → audit `BLOCKED_BY_PREFERENCE`, no delivery
- [ ] Critical bypass: `severity=critical` opt-out'u geçer + audit `PREFERENCE_BYPASSED_CRITICAL`
- [ ] Cross-org test: org_X subscriber için org_Y intent → audit `BLOCKED_BY_AUTHZ`

### Idempotency + DLQ

- [ ] Same `idempotency_key` 24h içinde 2. POST → 409 + original intent_id
- [ ] 24h+1s sonra same key → yeni intent kabul (TTL fix)
- [ ] Provider mock 5xx → 5 retry chain → DLQ INSERT + Alertmanager fired
- [ ] Admin replay: DLQ row → new delivery attempt success

### Drift Alarm Integration

- [ ] PR #347 alarm-receiver intent submit → orchestrator processes → Slack #alerts geldi
- [ ] End-to-end correlation_id tracing (drift-alarm event → outbox → intent → delivery → audit)

## Evidence

Her sub-task tamamlandığında `docs/faz-23-evidence/<date>-23-1-<task>-canli.md` ile kanıt yazılır.

Faz 23.1 close: tüm checklist 🟢 → `docs/faz-23-evidence/<date>-23-1-kernel-canli.md` ile özet evidence + Codex review AGREE.

## Cross-Reference

- ADR-0013 (atomik kararlar D38-D47)
- event-contract (intent JSON schema + PG schema)
- feature-matrix (Kernel tier ☐ → 🟢 ilerleme)
- must-have-checklist (10 must-have her biri D29-NOTIFY-Up + Functional + Authorized'a düşer)
- RB-notification-outage-fallback (sub-faz 23.2)
