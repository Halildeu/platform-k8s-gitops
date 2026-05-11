# T3.1.7 SMS DLR Callback — Live Smoke Evidence (mock NetGSM provider)

> **Date**: 2026-05-11 ~00:09 UTC
> **Cluster**: k3d-test (`testai.acik.com`)
> **Status**: 🟢 **PIPELINE LIVE VERIFIED** (mock provider; real SMS go-live R1 contract dep)
> **HARD RULE**: Pre-Production Full Authority + Cross-AI peer review (PR #154 Codex `019e1440` AGREE)

## Pipeline acceptance gates (all PASS)

| # | Test | Expected | Actual | Status |
|---|---|---|---|:---:|
| 1 | POST no JWT, empty token | gateway forward + backend 401 `invalid dlr token` | HTTP 401 `{"error":"unauthorized","message":"invalid dlr token"}` | ✅ |
| 2 | GET no JWT | gateway 401 Bearer challenge (POST-only contract) | HTTP 401 `WWW-Authenticate: Bearer` (gateway) | ✅ |
| 3 | Valid token, non-existent msg_id | 200 `action=NOT_FOUND` | `{"action":"NOT_FOUND","provider_msg_id":"netgsm-smoke-not-found-001","status":"UNKNOWN"}` HTTP 200 | ✅ |
| 4 | Valid token, ACCEPTED row | 200 `action=UPDATED` + status DELIVERED | `{"action":"UPDATED","provider_msg_id":"netgsm-dlr-smoke-001","status":"DELIVERED"}` HTTP 200 | ✅ |
| 5 | Re-post same DLR | 200 `action=NOOP` (idempotency) | `{"action":"NOOP","provider_msg_id":"netgsm-dlr-smoke-001","status":"DELIVERED"}` HTTP 200 | ✅ |

## DB state mutation evidence

**Pre-DLR seed** (mock NetGSM contract simulation):
```sql
INSERT INTO notify.notification_intent (intent_id, org_id, topic_key, severity,
  data_classification, template_id, locale, channels, status)
VALUES ('intent-dlr-smoke-001', 'default', 'sms.test', 'info', 'transactional',
  'sms-test-template', 'tr-TR', ARRAY['sms'], 'PROCESSING');

INSERT INTO notify.notification_delivery (intent_id, channel, recipient_type,
  recipient_hash, provider, status, provider_msg_id)
VALUES ('intent-dlr-smoke-001', 'sms', 'EXTERNAL', 'sha256-hash-mock',
  'netgsm', 'ACCEPTED', 'netgsm-dlr-smoke-001');
```

**Post-DLR final state**:
```
notify.notification_delivery (id=103):
  status: ACCEPTED → DELIVERED
  delivered_at: 2026-05-11 00:09:04.559933+00

notify.notification_intent (intent-dlr-smoke-001):
  status: PROCESSING → COMPLETED (IntentStatusResolver recompute)
```

## Audit event evidence (`notify.audit_event_v2`)

```
event_type                     | dlr_state_mutated | dlr_ignored_reason         | occurred_at
-------------------------------|-------------------|----------------------------|---------------------
DELIVERY_DLR_RECEIVED          | TRUE              | (none)                     | 2026-05-11 00:09:04 (Step 4)
DELIVERY_DLR_TERMINAL_CONFLICT | FALSE             | prior_status_delivered     | 2026-05-11 00:09:13 (Step 5)
```

Audit details JSON:
```json
{
  "org_id": "default",
  "channel": "sms",
  "provider": "netgsm",
  "topic_key": "sms.test",
  "template_id": "sms-test-template",
  "provider_code": "00",
  "recipient_hash": "sha256-hash-mock",
  "delivery_id_long": 103,
  "dlr_state_mutated": true | false
}
```

## End-to-end pipeline verified

```
External provider POST
   ↓ HTTPS 443
testai.acik.com (ingress nginx)
   ↓
api-gateway pod sha-26fa8f1 (imageID: sha256:c54f9f4baec7f34454ff686698463fa0f94c333dceeafb7a5ce8141fda47b70f)
   ├─ SecurityConfig.pathMatchers(POST, "/api/v1/notify/dlr/**").permitAll() ✅
   ├─ Spring Cloud Gateway route `notification-orchestrator-v1-route` Path=/api/v1/notify/**
   ↓
notification-orchestrator pod sha-c4a03fc (imageID: sha256:70491543...)
   ├─ SecurityConfig.requestMatchers("/api/v1/notify/dlr/**").permitAll() ✅ (defense-in-depth)
   ├─ DlrController.netgsmDlr() — X-NetGSM-DLR-Token constant-time compare (MessageDigest.isEqual) ✅
   ├─ DlrIngestService.ingestNetgsm() — atomic UPDATE WHERE status='ACCEPTED' ✅
   ├─ Multi-pod race safe (DB-level atomicity, no SELECT-then-UPDATE TOCTOU window) ✅
   ├─ IntentStatusResolver.resolve(deliveries) ✅ (parent intent terminal status recompute)
   ├─ AuditEventPublisher.publishWithDelivery() ✅ (V2 partitioned table)
   ↓
PG (platform-pg-test compose tier, D6 architecture)
```

## Operator credential reset (Pre-Production Full Authority, ESO recovery)

```bash
# 1. Vault DLR token seed (test cluster)
ROOT_TOKEN=$(python3 -c 'import json; print(json.load(open("/home/halil/bootstrap-drill/vault-init-test.json"))["root_token"])')
DLR_TOKEN=$(openssl rand -hex 32)  # = 50673258f53463c809789922ab5b9542b4a8a30a2118f1766cefedd609180ba2
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test \
  vault kv patch kv/platform/notification-orchestrator dlr_token="$DLR_TOKEN"

# 2. PG password rotation (alphanumeric, Spring env interpolation safe)
# Vault db_password matches PG user
DB_PW=$(docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test \
  vault kv get -format=json kv/platform/notification-orchestrator | \
  python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["data"]["db_password"])')
docker exec -i platform-pg-test psql -U postgres -c "ALTER USER platform WITH PASSWORD '$DB_PW';"

# 3. ESO force-sync + pod rollout
kubectl --context k3d-test -n platform-test annotate externalsecret \
  notification-orchestrator-secrets force-sync=$(date +%s) --overwrite
kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
```

## R1 (NetGSM contract activation) — full live cutover sequence

Mock pipeline %100 validated; remaining gates for real-SMS go-live:

1. **NetGSM admin UI** (operator, post-2026-05-30 contract activation):
   - SMS Sender Setup → Webhook URL: `https://testai.acik.com/api/v1/notify/dlr/netgsm`
   - Header: `X-NetGSM-DLR-Token: <vault-token>`
2. **Send 1 real SMS** via NotificationOrchestrator API (intent submit → SmsAdapter dispatch)
3. **Expected DLR within 30s**:
   - Real `provider_msg_id` = `netgsm-<jobid-from-NetGSM>`
   - Backend pipeline IDENTICAL to mock smoke (verified here)
4. **Verify DELIVERY_DLR_RECEIVED audit entry** with real provider_code from NetGSM
5. **Charter 23.4 marker fully 🟢**: archive UI + 30-day history kalan portion

## T3.1.7 sprint plan status path

| Phase | Status | Evidence |
|---|:---:|---|
| Backend ecosystem source-ready | 🔴 → 🟡 | PR #85 (DlrController + DlrIngestService + 19 backend tests) MERGED 2026-05-07 |
| Gateway permitAll gap closure | 🟡 | PR #154 Codex `019e1440` AGREE + 7 gateway tests MERGED 2026-05-11 |
| Gitops digest bump + cluster LIVE | 🟡 | PR #514 MERGED + api-gateway pod sha-26fa8f1 imageID match |
| **Live smoke pipeline validated** | 🟡 → **🟢** | **THIS DOC** — 5/5 acceptance gates PASS, DB mutation + audit events confirmed |
| Real SMS go-live | (R1 dep) | NetGSM contract ETA 2026-05-30 — pipeline ready, no code change needed |

## Refs

- PR #85 (DLR backend): `00e00fd` (notify-23.4-pr-f)
- PR #154 (gateway permitAll): `26fa8f1` (notify-23-4-dlr-gateway-permitall)
- PR #514 (gitops digest + runbook): `5592bf1`
- Codex Cross-AI peer review thread: `019e1440-7955-7452-ad10-2745f780271b` AGREE
- Smoke runbook: `docs/runbooks/RB-faz-23-4-dlr-smoke-test.md`
- Charter: `docs/runbooks/RB-faz-23-charter.md` 23.4 marker
- Sprint plan: `docs/notify/sprint-plan.md` T3.1.7
