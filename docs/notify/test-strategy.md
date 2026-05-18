# Notification Platform — Test Strategy

> **Status**: ACTIVE (Session 39 PM artifact bootstrap 2026-05-09)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Charter**: [RB-faz-23-charter](../runbooks/RB-faz-23-charter.md)
> **Scope**: Faz 23.0..23.X notification orchestrator test discipline

Bu doküman **per sub-faz test coverage requirements** + **regression scope** + **evidence path** mantığı tanımlar. Sub-faz `🟢 done` işaretlenmesi için bu test gates geçilmelidir.

---

## Test Pyramid

```
                       ▲
                      /│\
                     / │ \      Manual / Drill (1-3 per sub-faz)
                    /  │  \      browser SSO, rollback prova
                   /───┼───\
                  /    │    \   E2E / Acceptance (per channel)
                 /     │     \   D29-NOTIFY 3-katman
                /──────┼──────\
               /       │       \  Integration (~50 tests)
              /        │        \  Testcontainers PG + actuator
             /─────────┼─────────\
            /          │          \  Unit (~200 tests)
           /           │           \  Mocked dependencies
          /────────────┴────────────\
```

**Coverage targets per sub-faz**:
- Unit: %80 line coverage
- Integration: %70 critical path coverage
- E2E: D29-NOTIFY-Functional 3-katman per kanal (Up + Functional + Authorized)
- Manual drill: per-sub-faz acceptance criteria checklist

---

## Test Types

### 1. Unit Tests (Fast, Mocked)

**Scope**: Pure logic, no DB/network/Spring context.
**Framework**: JUnit 5 + Mockito + AssertJ
**Run**: `mvn test` (per-PR CI gate)

| Sub-faz | Test Class | Coverage Target | Status |
|---|---|---:|:---:|
| 23.1 | `NotificationIntentValidatorTest` | 90% | ✅ |
| 23.1 | `OutboxPollerTest` (mocked) | 85% | ✅ |
| 23.1 | `RetryWorkerTest` (mocked) | 85% | ✅ |
| 23.1 | `AuditPartitionRetentionServiceUnitTest` | 90% | ✅ (PR Codex 019dfdec) |
| 23.1 | `ProviderAdapterTest` (mocked SMTP/Slack/Webhook) | 85% | 🟡 |
| 23.4 | `SubscriberIdentityGuardTest` | 95% | ✅ (PR-5.5) |
| 23.4 | `NotifyOrgAccessGuardTest` | 95% | ✅ (PR-5.4) |
| 23.4 | `selectNotifyIdentity (FE)` | 90% | ✅ (PR #315) |
| 23.2.A | `PreferenceServiceTest` (mocked) | 85% | 🔴 Pending |
| 23.2.B | `AuditErasureServiceTest` (mocked) | 85% | 🔴 Pending |
| 23.2.C | `ProviderConfigRollbackServiceTest` | 85% | 🔴 Pending |
| 23.2.D | `OutageFallbackBridgeTest` (mocked) | 85% | 🔴 Pending |
| 23.2.E | `DataClassificationFilterTest` | 90% | 🔴 Pending |
| 23.2.F | `RateLimitServiceTest` + `FloodDetectorTest` | 85% | 🔴 Pending |
| 23.3 | `NetGsmClientTest` (mocked HTTP) | 85% | 🔴 Pending |
| 23.3 | `IletimerkeziClientTest` | 85% | 🔴 Pending |

### 2. Integration Tests (Testcontainers PG + actuator scrape)

**Scope**: Spring Boot @SpringBootTest with real PG via Testcontainers; HTTP client to actuator/REST.
**Framework**: JUnit 5 + Testcontainers + RestAssured
**Run**: CI workflow `notification-orchestrator Testcontainers PG test (Faz 23.1 Foundation)`

| Sub-faz | Test Class | Status | Evidence Path |
|---|---|:---:|---|
| 23.1 | `AuditPartitionV8IntegrationTest` (V8 schema + partition contract) | ✅ | CI run logs |
| 23.1 | `NotificationIntentControllerTest` (POST /intents idempotency) | ✅ | CI run logs |
| 23.1 | `OutboxIntegrationTest` (advisory lock + cycle) | ✅ | CI run logs |
| 23.1 | `OpenFgaIntegrationTest` (allow + deny case) | ✅ | CI run logs |
| 23.1 | `RetryDlqIntegrationTest` (max attempt → DLQ) | 🟡 | needs explicit assertion |
| 23.4 | `SubscriberIdentityGuardIntegrationTest` (strict mode no_auth + non_jwt) | ✅ | PR-5.5 LIVE |
| 23.4 | `NotifyOrgAccessGuardIntegrationTest` | ✅ | PR-5.4 LIVE |
| 23.7 | **`AuditPartitionRetentionDetachDropTest`** (4 methods covering DETACH/DROP/cutoff/idempotency) | ✅ | PR #130 LIVE 2026-05-09 |
| 23.2.A | `PreferenceApiIntegrationTest` (per-channel + per-topic + critical bypass) | 🔴 Pending | — |
| 23.2.B | `KvkkErasureIntegrationTest` (DELETE /audit/me + recipient_hash preservation) | 🔴 Pending | — |
| 23.2.B | `KvkkRightToInformationIntegrationTest` (GET /audit/me) | 🔴 Pending | — |
| 23.2.C | `ProviderConfigRollbackIntegrationTest` | 🔴 Pending | — |
| 23.2.D | `OutageFallbackBridgeIntegrationTest` | 🔴 Pending | — |
| 23.2.E | `DataClassificationIntegrationTest` (4 classifications + critical bypass) | 🔴 Pending | — |
| 23.2.F | `RateLimitIntegrationTest` + `FloodDetectorIntegrationTest` | 🔴 Pending | — |
| 23.3 | `SmsAdapterIntegrationTest` (NetGSM mock) | 🔴 Pending | — |
| 23.3 | `DlrCallbackIntegrationTest` | 🔴 Pending | — |
| 23.3 | `InAppInboxApiIntegrationTest` (paged + read + archive + WS) | 🔴 Pending | — |

### 3. E2E / Acceptance Tests (D29-NOTIFY 3-katman)

**Scope**: Live cluster (k3d-test) end-to-end flow per channel.
**Framework**: bash scripts + curl + psql + actuator queries
**Run**: Manual or scheduled (post-deploy)

**D29-NOTIFY** = Up + Functional + Authorized (per channel):

| Channel | D29-Up | D29-Functional | D29-Authorized | Sub-faz | Evidence Path | Status |
|---|:---:|:---:|:---:|---|---|:---:|
| **Email (Mailpit lab)** | ✅ pod ready | ✅ Mailpit message + PG delivery row (2026-05-14) | 🟡 L1 org-boundary ✅; L2 channel-level → 23.2 v2 | 23.1 | `docs/faz-23-evidence/2026-05-14-m2-d29-functional-3-channel-live.md` | 🟡 Functional+L1 accepted |
| **Slack (mock receiver)** | ✅ pod ready | ✅ mock incoming-webhook receiver 200 + PG delivery row (2026-05-14) | 🟡 L1 ✅; L2 → 23.2 v2 | 23.1 | `docs/faz-23-evidence/2026-05-14-m2-d29-functional-3-channel-live.md` | 🟡 Functional+L1 accepted |
| **Webhook (HMAC)** | ✅ pod ready | ✅ HMAC POST + webhook-receiver 200 + PG delivery row (2026-05-14) | 🟡 L1 ✅; L2 → 23.2 v2 | 23.1 | `docs/faz-23-evidence/2026-05-14-m2-d29-functional-3-channel-live.md` | 🟡 Functional+L1 accepted |
| **In-app inbox** | ✅ SSE 200 | ✅ /inbox/me 200 | ✅ subscriberId match | 23.4 | Codex `019e07d6` PR-5.5 evidence | ✅ |
| **SMS NetGSM** | — | — | — | 23.3 | — | ⏳ Faz 23.3 |
| **Teams** | — | — | — | 23.6 | — | ⏳ Faz 23.6 |
| **FCM/APNS** | — | — | — | 23.7 | — | ⏳ Faz 23.7 |

**HARD RULE (ADR D29)**: D29-NOTIFY = 3-katman per channel. Up ≠ Functional ≠ Authorized. Pod ready demek delivery işlevsel demek değil (Codex 019dcbc8 retrospective'i + 2026-04-26 Session 30 user feedback).

### 4. Manual Drill / User Action Tests

| Drill | Sub-faz | Frequency | Owner | Status |
|---|---|---|---|:---:|
| Browser SSO verify (testai + ai.acik.com /inbox/me) | 23.9 | Per-cutover | user | 🔴 Pending |
| Rollback prova (kubectl set image revert) | 23.9 | Quarterly | ops | 🔴 Pending |
| Outage fallback drill (orchestrator scale=0 → Slack direct) | 23.2.D | Quarterly | ops | 🔴 Pending |
| KVKK erasure flow (subscriber DELETE → payload purge) | 23.2.B | Per-launch | dev/legal | 🔴 Pending |
| Vault token rotation drill | — | Quarterly | ops | 🟡 Active |
| Backup restore drill (PG dump + Vault snapshot) | — | Quarterly | ops | 🟡 Active |

### 5. Regression Test Suite (Per-Merge)

**Run on every merge to main**:

- ✅ `mvn test` (full unit + integration)
- ✅ `kubectl kustomize` overlay sanity (test + prod + eso)
- ✅ Drift PR-time render gate (Codex P0)
- ✅ D29 evidence required (prod digest changes)
- ✅ ResourceQuota headroom preflight
- ✅ ADR-0011 BG-1 boundary declaration
- ✅ Drift detection PR-time gate
- 🟡 Promtool PromQL syntax validation (ad-hoc)
- 🔴 E2E suite (manual currently; future automated)

---

## Coverage Reports + Evidence

**Per-PR evidence requirement**:
1. CI run URL (Maven test report)
2. Test count delta (X tests added)
3. Coverage % change (if measurable)
4. Live cluster verification command + output
5. Cross-AI Codex peer review thread

**Per-sub-faz closure evidence**:
1. All checklist criteria 🟢
2. All test types passing
3. D29-NOTIFY 3-katman per channel evidence file
4. Risk register review (sub-faz-related risks updated)
5. Charter sub-faz section evidence path filled

---

## Test Gaps + Backlog

| Gap | Priority | Sub-faz | Plan |
|---|:---:|---|---|
| **Promtool PromQL syntax validation in CI** | High | All | Add to gitops CI workflow |
| **Mutation testing** | Medium | 23.x | Pitest config + selective coverage |
| **Load testing** (provider rate limits) | Medium | 23.3 + 23.2.F | Gatling/k6 scripts post-23.2.F |
| **Chaos testing** (pod kill, DB restart) | Low | 23.9 | Chaos Mesh post-multi-tenant |
| **E2E automation** (3-katman scripted) | High | 23.1 | bash + curl scripts in `scripts/d29/` |
| **Frontend E2E** (Playwright) | Medium | 23.4 + 23.5 | Add Chromatic/Playwright suite |
| **Security scan** (gitleaks already in CI; add OWASP ZAP for runtime) | Medium | 23.x | Post-23.2 closure |
| **Browser console JS error baseline** | High | 23.4 | Per-deploy verify (HARD RULE) |

---

## Test Execution Cadence

- **Pre-commit**: lint + unit tests (developer local)
- **Per-PR**: full Maven reactor + Testcontainers + lint gates
- **Post-merge**: regression suite + CI status webhook
- **Weekly**: drill schedule (Vault rotation, backup restore)
- **Per-sub-faz closure**: full E2E + manual drill checklist
- **Quarterly**: chaos drill + DR exercise
- **Pre-prod cutover**: 72h observation + canary smoke + browser verify
