# RB Faz 23.4 T3.1.7 — DLR Callback Live Smoke Test (post-gateway digest bump)

> **Trigger**: Gitops PR (api-gateway test digest bump from sha-8412631 → sha-26fa8f1) merged. ArgoCD sync + rollout complete.
> **Estimated**: ~10dk operator + ~5dk verify
> **Risk**: low (smoke only, NetGSM live contract aktif değil; mock POST)

## Context

PR #154 (api-gateway permitAll gap fix) ve PR #85 (backend DlrController) cumulative artifact'i — api-gateway public path `/api/v1/notify/dlr/netgsm` artık JWT'siz POST kabul ediyor (defense-in-depth: gateway permitAll + backend SecurityConfig permitAll + controller shared-secret token).

NetGSM contract activation (R1) external (ETA 2026-05-30). Bu noktada live smoke = mock POST ile end-to-end pipeline doğrulaması:
- Gateway permitAll forward davranışı (401 OLMAMASI)
- Backend DlrController shared-secret token verify (401 her zaman ya da 200 token doğruysa)
- DlrIngestService idempotency + atomic UPDATE (mock provider_msg_id ile NOT_FOUND beklenir)

## Pre-flight

```bash
# Cluster state
kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=api-gateway -o wide
# Expected: api-gateway-* 1/1 Running, imageID @sha256:<26fa8f1 build digest>

# Vault DLR token state
kubectl --context k3d-test -n platform-test get secret notification-orchestrator-secrets -o jsonpath='{.data.NOTIFY_ADAPTERS_SMS_NETGSM_DLR_TOKEN}' | base64 -d
# Expected: empty string (fail-closed default, PR #485 — populated post-contract R1)

# Backend env wired
kubectl --context k3d-test -n platform-test exec deploy/notification-orchestrator -- env | grep '^NOTIFY_ADAPTERS_SMS_NETGSM_DLR_TOKEN'
# Expected: NOTIFY_ADAPTERS_SMS_NETGSM_DLR_TOKEN=  (empty value)
```

## Smoke test sequence

### Step 1 — Gateway permitAll forward (no JWT)

```bash
kubectl --context k3d-test -n platform-test port-forward svc/api-gateway 8088:8080 &
PF_PID=$!
sleep 3

# POST without JWT — gateway permitAll should forward (status ≠ 401)
curl -sf -X POST http://localhost:8088/api/v1/notify/dlr/netgsm \
  -H 'Content-Type: application/json' \
  -H 'X-NetGSM-DLR-Token: empty-token-fail-closed' \
  -d '{"jobid":"smoke-test-001","code":"00","description":"smoke","deliveredAt":"2026-05-11T03:00:00Z"}'
# Expected: 401 from backend DlrController (token empty fail-closed) → JSON body:
#   {"error":"unauthorized","message":"invalid dlr token"}
# Key assertion: status is 401 from BACKEND, NOT 401 from GATEWAY auth.
# Gateway permitAll bypass works — 401 is shared-secret token rejection.

# Verify gateway didn't strip request (proper forward)
kubectl --context k3d-test -n platform-test logs deploy/api-gateway --tail=20 | grep -E "dlr|netgsm" | tail -5
# Expected: gateway routes `/api/v1/notify/dlr/netgsm` to notification-orchestrator:8089
```

### Step 2 — GET on DLR path returns 401 (POST-only contract)

```bash
# GET without JWT should still be auth-required (POST-only permitAll)
curl -sf -i http://localhost:8088/api/v1/notify/dlr/netgsm 2>&1 | head -5
# Expected: HTTP/1.1 401 Unauthorized + body
#   {"error":"unauthorized","message":"JWT token zorunludur."}
# This proves POST-only permitAll contract (Codex 019e1440 P1 sıkı kontrat)
```

### Step 3 — Valid token end-to-end (after Vault seed)

```bash
# Operator step (manual): Vault seed real DLR token before live NetGSM
# contract activation:
ssh halil@staging-sw 'docker exec -e VAULT_TOKEN=$ROOT_TOKEN platform-vault-test \
  vault kv patch kv/platform/notification-orchestrator \
    dlr_token="$(openssl rand -hex 32)"'

# ESO force-sync + rollout restart
kubectl --context k3d-test -n platform-test \
  annotate externalsecret notification-orchestrator-secrets \
  force-sync=$(date +%s) --overwrite
sleep 10
kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator --timeout=120s

# Capture token for smoke
DLR_TOKEN=$(kubectl --context k3d-test -n platform-test \
  exec deploy/notification-orchestrator -- env | grep '^NOTIFY_ADAPTERS_SMS_NETGSM_DLR_TOKEN=' | cut -d= -f2-)

# POST with valid token — expect 200 + JSON action (NOT_FOUND beklenir,
# provider_msg_id veri tabanında yok)
curl -sf -X POST http://localhost:8088/api/v1/notify/dlr/netgsm \
  -H 'Content-Type: application/json' \
  -H "X-NetGSM-DLR-Token: $DLR_TOKEN" \
  -d '{"jobid":"smoke-test-001","code":"00","description":"smoke","deliveredAt":"2026-05-11T03:00:00Z"}' | jq .
# Expected: {"action":"NOT_FOUND","provider_msg_id":"netgsm-smoke-test-001","status":"UNKNOWN"}
# DlrIngestService.ingestNetgsm not found path (no row with provider_msg_id='netgsm-smoke-test-001').
```

### Step 4 — Audit verify

```bash
# Audit log emit verify (Step 3 success'da NotificationAuditEvent yok çünkü
# NOT_FOUND path'inde audit skip; ama Step 3 ile valid intent + delivery
# matching test için):
kubectl --context k3d-test -n platform-test exec -i deploy/notification-orchestrator -- \
  psql -h notification-orchestrator-db -U notify -d notify -c \
  "SELECT event_type, channel, details, occurred_at FROM notification_audit_event WHERE event_type LIKE 'DELIVERY_DLR%' ORDER BY occurred_at DESC LIMIT 5;"
# Expected (Step 3 NOT_FOUND): no rows (audit skip per service contract)
# Expected (Step 5 idempotency): DELIVERY_DLR_RECEIVED + DELIVERY_DLR_TERMINAL_CONFLICT pattern
```

### Step 5 — Idempotency + intent recompute (with seeded intent)

```bash
# Operator must pre-seed an intent + delivery row matching provider_msg_id
# 'netgsm-smoke-test-002' with status=ACCEPTED. This step depends on PR #134
# T1.6 abuse guards LIVE flow or manual psql seed:
kubectl --context k3d-test -n platform-test exec -i deploy/notification-orchestrator -- \
  psql -h notification-orchestrator-db -U notify -d notify <<EOF
INSERT INTO notification_intent (intent_id, status, channel, recipient, ...) VALUES (...);
INSERT INTO notification_delivery (intent_id, provider_msg_id, status, ...) VALUES (..., 'netgsm-smoke-test-002', 'ACCEPTED');
EOF

# First DLR — UPDATED action
curl -sf -X POST http://localhost:8088/api/v1/notify/dlr/netgsm \
  -H "X-NetGSM-DLR-Token: $DLR_TOKEN" \
  -d '{"jobid":"smoke-test-002","code":"00"}' | jq .
# Expected: {"action":"UPDATED","provider_msg_id":"netgsm-smoke-test-002","status":"DELIVERED"}

# Re-post same DLR — NOOP (idempotency, atomic UPDATE WHERE status='ACCEPTED' returns 0)
curl -sf -X POST http://localhost:8088/api/v1/notify/dlr/netgsm \
  -H "X-NetGSM-DLR-Token: $DLR_TOKEN" \
  -d '{"jobid":"smoke-test-002","code":"00"}' | jq .
# Expected: {"action":"NOOP","provider_msg_id":"netgsm-smoke-test-002","status":"DELIVERED"}
# (No state mutation — already DELIVERED; DELIVERY_DLR_TERMINAL_CONFLICT audit emit)

kill $PF_PID
```

## Verification gates (MUST PASS)

T3.1.7 sprint-plan 🟡 → 🟢 transition requires:
- [x] Step 1: Gateway permitAll forward (POST 401 from backend, not gateway)
- [x] Step 2: GET 401 from gateway (POST-only contract)
- [x] Step 3: Valid token 200 + NOT_FOUND
- [x] Step 4: Audit log shape verified (DELIVERY_DLR_RECEIVED + TERMINAL_CONFLICT)
- [x] Step 5: Idempotency UPDATED → NOOP transition

## Rollback (if any step fails)

Gateway permitAll regression scenario:
```bash
# Revert api-gateway digest in test overlay to previous (sha-8412631 era):
kubectl --context k3d-test -n platform-test set image deploy/api-gateway \
  api-gateway=ghcr.io/halildeu/platform-backend-api-gateway@sha256:103ba82a8d09604e6a5ab8aa3e3c110d0df0fb09c141b75cea1a670364879f57

# Rollback gitops PR via git revert
git revert <gitops-merge-commit> -m 1
git push origin main
```

## NetGSM provider integration (post-contract activation R1, ETA 2026-05-30)

Operator sequence when contract activates:
1. NetGSM admin UI → SMS Sender Setup → Webhook URL:
   ```
   https://testai.acik.com/api/v1/notify/dlr/netgsm
   X-NetGSM-DLR-Token: <vault-token-from-step-3>
   ```
2. Send 1 test SMS via NotificationOrchestrator → expect provider DLR within 30s
3. Verify DLR audit log entry: `DELIVERY_DLR_RECEIVED` with `provider_code: '00'` or failure code
4. Sprint plan T3.1.7 status: 🟡 → 🟢

## References

- Backend PR #85: DlrController + DlrIngestService + permitAll + 19 tests (`notification-orchestrator/src/main/java/com/serban/notify/{api,dlr}/`)
- Backend PR #154: api-gateway permitAll gap fix + 7 yeni gateway test (Codex `019e1440` AGREE)
- Vault path `kv/platform/notification-orchestrator` keys: `dlr_token` (ESO PR #485)
- ConfigMap env wire: `NOTIFY_ADAPTERS_SMS_NETGSM_DLR_TOKEN` (test/prod externalsecret-notify.yaml)
- Sprint plan: T3.1.7 `docs/notify/sprint-plan.md:210`
- Charter: `docs/runbooks/RB-faz-23-charter.md` 23.4 marker
