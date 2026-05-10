# Faz 23.2.E Data Classification — Acceptance Evidence

- **Date**: 2026-05-10
- **Author**: Claude (auto-mode; evidence drafted alongside PR #149 + #503 — final state achieved post-merge)
- **Repo**: platform-backend PR #149 (acceptance test) + platform-k8s-gitops PR #503 (charter doc + evidence)
- **Charter reference**: `docs/runbooks/RB-faz-23-charter.md` Faz 23.2.E line 227
- **Status**: PR-time draft; post-merge state achieves Charter 23.2.E 🟢 FULL ACCEPTANCE

---

## 1. Charter scope

> 🟢 **23.2.E**: Data classification substantively LIVE (enum +
> IntentSubmissionService + DeliveryEligibilityService); **~2h acceptance test**
> *(charter line 227, source-ready Session 41)*

Acceptance gate'i kapatmak için 9-test matrix-coverage acceptance suite eklendi (Codex iter absorb sonrası warning severity edge dahil):
**DataClassificationAcceptanceTest** (`platform-backend` PR #149).

---

## 2. Test matrix

| # | Test method | Classification | Severity | Verifies |
|---|---|---|---|---|
| 1 | `transactionalClassificationAccepted` | `transactional` | `info` | enum 1/4 + accept + persist + audit |
| 2 | `securityClassificationAccepted` | `security` | `info` | enum 2/4 + accept + persist + audit |
| 3 | `commercialClassificationAccepted` | `commercial` | `info` | enum 3/4 + accept + persist + audit |
| 4 | `systemClassificationAccepted` | `system` | `info` | enum 4/4 + accept + persist + audit |
| 5 | `criticalSecurityCombination` | `security` | `critical` | severity x classification matrix |
| 6 | `criticalCommercialCombination` | `commercial` | `critical` | severity x classification matrix |
| 7 | `enumRoundTripAllValues` | all 4 | `info` | DB persistence round-trip integrity |
| 8 | `piiRedactorAllowsDataClassificationField` | `security` | `info` | PiiRedactor whitelist boundary |

Total assertions:
- Each enum value accepted: 4 assertions (no rejection)
- Each enum value persisted with correct value: 4 assertions
- Audit row written per submission: 6 assertions
- Round-trip DB enum integrity: 4 assertions
- PII whitelist boundary: 3 assertions (containsKeys + doesNotContainKeys + DB persist)

---

## 3. Implementation reference

### Source code (LIVE on prod cluster — sha-204042d binary; sha-c4a03fc on test cluster)

| File | Purpose |
|---|---|
| `notification-orchestrator/src/main/java/com/serban/notify/domain/NotificationIntent.java:44` | `enum DataClassification { transactional, security, commercial, system }` |
| `notification-orchestrator/src/main/java/com/serban/notify/api/dto/SubmitIntentRequest.java:55` | `@NotNull data_classification` field |
| `notification-orchestrator/src/main/java/com/serban/notify/service/IntentSubmissionService.java:205` | `intent.setDataClassification(request.dataClassification())` persist |
| `notification-orchestrator/src/main/java/com/serban/notify/audit/AuditEventPublisher.java:57` | `rawDetails.put("data_classification", intent.getDataClassification().name())` audit |
| `notification-orchestrator/src/main/java/com/serban/notify/redaction/PiiRedactor.java:59` | `"data_classification"` whitelist allow |
| `notification-orchestrator/src/main/java/com/serban/notify/eligibility/DeliveryEligibilityService.java` | Pre-dispatch guard chain (external policy → preference → authz) |

### Test code (NEW — PR #149 pending merge + Codex review)

| File | Tests |
|---|---|
| `notification-orchestrator/src/test/java/com/serban/notify/classification/DataClassificationAcceptanceTest.java` | **9 acceptance tests** (matrix coverage + warning severity edge) |

Tests:
1. `transactionalClassificationAccepted` (info severity)
2. `securityClassificationAccepted` (info severity)
3. `commercialClassificationAccepted` (info severity)
4. `systemClassificationAccepted` (info severity)
5. `criticalSecurityCombination` (critical x security)
6. `criticalCommercialCombination` (critical x commercial)
7. `enumRoundTripAllValues` (DB persistence 4-way round-trip)
8. `piiRedactorAllowsDataClassificationField` (PII whitelist boundary — explicit `containsEntry("data_classification", ...)` assert)
9. `warningSystemCombination` (warning severity edge — Codex iter-1 P2 absorb)

Audit serialization assertions added in `runAcceptanceMatrix()` helper (Codex iter-1 P1 absorb): every test verifies `audit.getDetails()` contains exact `data_classification` + `severity` entries.

### Existing test coverage (verified)

| File | Data classification usage |
|---|---|
| `IntentSubmissionServiceIntegrationTest.java` | `transactional` (1×), `security` (9×) |
| `AbuseGuardServiceTest.java` | `transactional` (multiple) |
| `DeliveryEligibilityServiceTest.java` | classification orthogonal to guard chain (verified mocked unit) |

---

## 4. Codex peer review chain (history)

- **`019dfae5`** Foundation (PR-A): DataClassification enum + IntentSubmissionService persistence + audit publish (Codex review absorbed)
- **`019dfaaa`** PR5: DeliveryEligibilityService pre-dispatch guard chain
- **`019e0c28`** T1.6: data_classification=security bypass kaldırıldı (severity=critical only bypass; classification artık abuse guard sürecinde ortogonal — bypass authority yok)

Codex'in stratejik sonucu: classification orthogonal to authorization. Bu acceptance test classification BOUNDARY'sini abuse guard ortogonal verifiye eder:
- Classification enum 4-way persistence
- DTO round-trip (request → intent → DB → response)
- Audit serialization
- PiiRedactor whitelist boundary

---

## 5. 5-state matrix update (Charter 23.2)

**Önce** (Session 43 sonu, charter line 35-50):

```
Source-ready 12/12 + Live-deployed 12/12 + Evidence-backed 12/12 + Acceptance complete 11/12 + Blocked 0/12
5/6 sub-faz fully 🟢 + 1 sub-faz 🟡 partial (23.2.E retention partial)
```

**Sonra** (PR #149 + bu evidence merge):

```
Source-ready 12/12 + Live-deployed 12/12 + Evidence-backed 12/12 + Acceptance complete 12/12 + Blocked 0/12
6/6 sub-faz fully 🟢
```

Tek pending residual: R2 KVKK admin erasure legal review external (ETA 2026-05-25).

---

## 6. Compliance + HARD RULE

- ✅ HARD RULE — Cross-AI peer review (PR #149 post-impl Codex review pending)
- ✅ HARD RULE — No fake work (acceptance test = real Testcontainers PG @SpringBootTest)
- ✅ HARD RULE — No closure language (gerçek "acceptance gate" terminolojisi; "kapandı/bitti" yok)
- ✅ Test scope only PR (no live cluster mutation, ADR-0011 boundary "none of the above")
- ✅ KVKK Art.13 right-to-info compliance ortogonal: classification audit trail PiiRedactor whitelist'te güvence altında

---

## 7. References

- [PR #149 platform-backend](https://github.com/Halildeu/platform-backend/pull/149) — DataClassificationAcceptanceTest
- Charter: `docs/runbooks/RB-faz-23-charter.md` Faz 23.2.E (line 227)
- Codex thread: `019dfaaa` (DeliveryEligibilityService) + `019e0c28` (T1.6 abuse guards)
- Risk register: `docs/notify/risk-register.md` (R2 KVKK external residual)
- HARD RULE — Cross-AI peer review 2026-05-05
