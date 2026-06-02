# Sprint Plan — PR-D2.5 weekly-audit-digest (5th and final remote-http pure-grid module + mart layer)

> Codex plan-time thread: `019e8708-5266-7563-bcf1-8aa1f9f1cd54` (Option A constrained — AGREE)
> Plan-time date: 2026-06-01
> Sprint scope: 4-PR cross-service (permission-service + report-service + mfe-reporting + docs)

---

## Codex consensus

**Recommendation A (constrained)**: Source-owned `/api/audit/events/digest`
endpoint + fixed `audit-weekly-digest-v1` contract. **NO generic groupBy
DSL**. Permission-service owns audit data and therefore owns digest
aggregation; report-service is allowlist'li adapter only.

### Why A wins over B/C/D

- **B/C (client-side or hybrid aggregation)** = No Fake Work risk:
  paged events under-count silently when dataset > 10K. 6 ay sonra
  adversarial review fail.
- **D (defer)** technically honest but PR-D2 chain 4/5 kalır;
  Continuous Autonomous Mode hedefiyle zayıf uyumlu.
- **A (constrained)** highest ROI: production-grade mart altyapısının
  tamamını değil, audit domain'in sahibi olan permission-service içinde
  tek sabit digest endpoint'ini ve report-service içinde allowlist'li
  aggregate response normalizer'ını üretir.

---

## 4-PR sub-chain

### PR-D2.5a — permission-service digest endpoint

**Scope**: `GET /api/audit/events/digest` source-owned aggregation.

**Request** (query params):
- `dateFrom` (ISO-8601, required)
- `dateTo` (ISO-8601, required, max range bounded)
- `action` (optional, allowlist filter)
- `service` (optional, allowlist filter)
- `level` (optional, INFO/WARN/ERROR/DEBUG)
- `user` (optional, email or userId)
- `search` (optional, free-text)
- `topK` (optional, default 5, max 20)

**Response**:
```json
{
  "weeks": [
    {
      "weekStart": "2026-05-26T00:00:00Z",
      "weekEnd": "2026-06-01T23:59:59Z",
      "isoYear": 2026,
      "isoWeek": 22,
      "totalEventCount": 1247,
      "distinctUserCount": 38,
      "actionBreakdown": {"LOGIN": 412, "LOGOUT": 388, ...},
      "serviceBreakdown": {"auth-service": 800, "permission-service": 447, ...},
      "topUsers": [
        {"userId": "user-1", "userEmail": "admin@example.com", "eventCount": 89},
        ...
      ]
    },
    ...
  ],
  "filterEcho": { /* effective filters used */ },
  "computedAt": "2026-06-01T20:38:00Z"
}
```

**Machine gates**:
- DTO/schema test
- repository/service aggregation test
- ISO week + timezone boundary test
- top-K deterministic tie-break test
- tenant/authz/header propagation test
- max range/topK validation fail-closed test

**Functional acceptance**: Seeded fixture — Week-1 + Week-2;
LOGIN/LOGOUT/IMPERSONATION; auth-service/permission-service; ≥ 3 users.
Expected aggregate JSON birebir assert edilir.

**Adversarial review focus**: Distinct user identity (userId vs userEmail),
inclusive/exclusive date boundaries, null service/action handling, top-K
tie order, permission scope bypass.

---

### PR-D2.5b — report-service aggregate adapter

**Scope**: Narrow aggregate adapter contract. **No generic `groupBy` DSL**.

Changes:
- `ExecutionKind.REMOTE_HTTP_AGGREGATE` (new enum)
- `ReportDefinition.execution.requestShape = "audit-weekly-digest-v1"`
- `ReportDefinition.execution.responseShape = "audit-weekly-digest-v1"`
- `RemoteAllowlist`: `(permission-service, /api/audit/events/digest)` tuple
- `RemoteRequestNormalizer.toAuditWeeklyDigestV1` (new)
- `RemoteResponseNormalizer.fromAuditWeeklyDigestV1` (new — flat row per week)

**Machine gates**:
- ReportDefinition schema enum update
- ExecutionKind/ExecutionConfig validation tests
- RemoteRequestNormalizer audit-weekly-digest-v1 tests
- RemoteResponseNormalizer audit-weekly-digest-v1 tests
- WireMock happy path + 401/403/5xx mapping tests
- remote aggregate grouping unsupported paths fail-closed tests

**Functional acceptance**: report-service
`/reports/weekly-audit-digest/data` permission-service digest response'unu
normalized rows olarak döndürür; frontend'e raw event sayfaları değil
aggregate rows gider.

**Adversarial review focus**: Generic aggregation surface açılmadı mı,
arbitrary service/path kaçışı yok mu, JWT ve `X-Company-Id` aynen
taşınıyor mu, response total semantics doğru mu.

---

### PR-D2.5c — ReportDefinition + frontend render

**Scope**: `weekly-audit-digest` metadata gerçek digest kontratına geçirilir.
Frontend yalnız server aggregate rows render eder.

Changes:
- `weekly-audit-digest.json` ReportDefinition:
  - `execution.kind=remote-http-aggregate`
  - `execution.service=permission-service`
  - `execution.path=/api/audit/events/digest`
  - `execution.requestShape=audit-weekly-digest-v1`
  - `execution.responseShape=audit-weekly-digest-v1`
  - columns: weekStart, weekEnd, totalEventCount, distinctUserCount,
    actionBreakdown (badge/cell-renderer), serviceBreakdown, topUsers
- ReportContractGate: reports 36 → 37
- ReportDefinitionContractTest aggregate: 36 → 37
- mfe-reporting: weekly-audit-digest route segment + dynamic factory
  weekly digest render (NO client aggregation)

**Machine gates**:
- report definition contract count/shape ratchet
- routeSegment/sharedReportId preservation test
- frontend catalog/dynamic replacement test
- AG-Grid column contract test
- no client raw-event aggregation guard test

**Functional acceptance**: UI iki haftalık digest satırlarını,
action/service breakdown hücrelerini ve top users alanını gösterir;
filter değişimi backend digest request'ine yansır.

---

### PR-D2.5d — Docs + smoke evidence

**Scope**: End-to-end acceptance + truth kayıtları.

Changes:
- `kustomize/overlays/test/kustomization.yaml`: report-service + permission-service digest pin
- `docs/state/current-state.md` LIVE delta (PR-D2.5 LIVE)
- Browser smoke evidence: weekly-audit-digest opens + aggregate rows visible
- Cluster log evidence: digest endpoint call + normalized response

**Machine gates**:
- backend CI
- frontend CI
- contract ratchet
- browser smoke
- different-provider AI review evidence
- current-state/docs drift note if live truth changed

**Functional acceptance**: Authoritative path — browser veya service edge
üzerinden `weekly-audit-digest` açılır; beklenen aggregate değerleri
fixture ile karşılaştırılır. **`raw events endpoint returned 200`
acceptance SAYILMAZ**.

---

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| A'nın kapsamı generic analytics DSL'e büyürse PR-D2.5 mart sprintine dönüşür | Sadece `audit-weekly-digest-v1` sabit kontratı; arbitrary `groupBy`, arbitrary `measure`, cross-field expression yok |
| Client-side aggregation PR'a sızarsa sonuçlar paging altında sessizce yanlış olur | Frontend aggregate hesaplamaz; sadece server digest response render eder. POC gerekiyorsa fail-closed `total <= maxFetch` guard ile ayrı spike olarak tutulur |
| Week bucket timezone drift üretir | ISO week ve timezone açıkça kontrata yazılır; boundary fixture ile pazar/pazartesi ve UTC/local geçişleri test edilir |
| Distinct user count yanlış kimlik alanına bağlanır | Canonical identity seçimi endpoint kontratında sabitlenir; null/legacy email fallback davranışı testlenir |
| Top-K determinism review'da patlar | Order: count desc, user display key asc/id asc gibi deterministic tie-break zorunlu |
| Permission/authz bypass | permission-service endpoint mevcut audit read scope'u ve tenant/company narrowing'i yeniden kullanır; report-service JWT ve company header propagation integration test ile kanıtlanır |
| Performance ve index eksikliği labda görünmez | Date range max, topK max, explain/index notu ve bounded query guard; production mart/materialized view sonraki sprint olarak açık tutulur |
| Docs/test ratchet 5/5 der ama functional digest yoktur | Ratchet sadece tuple/shape değil, digest shape ve seeded aggregate acceptance'ı da kapsamalı; filter-only weekly report acceptance sayılmamalı |

---

## Parallel safe paths

| Path | Description | Write scope | Can run parallel with | Blocked by |
|---|---|---|---|---|
| P1 | permission-service digest endpoint impl | permission-service audit controller/service/repository/dto/tests | P2, P3-docs | Canonical `audit-weekly-digest-v1` DTO field names agreed before coding |
| P2 | report-service aggregate adapter/schema/WireMock contract | report-service execution, registry schema, report contract tests | P1 after DTO skeleton | Endpoint path and response DTO skeleton |
| P3 | frontend render path and smoke harness | mfe-reporting/platform-web weekly digest dynamic render/tests | P1 fixtures, P2 metadata skeleton | Normalized row shape from report-service |
| P4 | docs/current-state/ADR amendment and review packet | docs only | P1, P2, P3 | Final acceptance evidence paths and actual live smoke outputs |

---

## Next session — first action

```bash
cd /Users/halilkocoglu/Documents/platform-backend
git checkout -b feat/pr-d2-5a-audit-weekly-digest-endpoint origin/main

# 1. Read this plan: docs/sprint-plan-pr-d2-5-weekly-audit-digest.md
# 2. Codex thread: 019e8708-5266-7563-bcf1-8aa1f9f1cd54 (plan-time AGREE)
# 3. Start P1 — permission-service digest endpoint
# 4. DTOs: AuditWeeklyDigestRequest + AuditWeeklyDigestResponse + WeeklyDigestBucket + TopUser
# 5. Service method: AuditEventService.aggregateWeeklyDigest(...)
# 6. Repository: native PG query with ISO week extraction + aggregations
# 7. Controller: GET /api/audit/events/digest @RequireModule(AUDIT, can_view)
# 8. Unit tests: DTO validation, ISO week boundary, top-K tie-break
# 9. Integration test: seeded fixture 2 weeks + assert exact aggregate JSON
# 10. Codex post-impl review (cross-AI provider isolation)
```

---

## References

- Codex plan-time thread: `019e8708-5266-7563-bcf1-8aa1f9f1cd54`
- Previous PR-D2 chain LIVE deltas: `docs/state/current-state.md`
- ADR-0015: report execution adapter
- HARD RULE Plan Consensus Autonomy: Codex AGREE → direct impl, kullanıcıya sormama
- HARD RULE No Fake Work: client-side aggregation = fake; source-owned required
- HARD RULE Continuous Autonomous Mode: sıradaki session devam eder
- HARD RULE Tarayıcıdan Sonuç Doğrulanmadan: PR-D2.5d browser smoke zorunlu
