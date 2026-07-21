# RB-faz-23-1-pr5-deploy-verify

> **Faz**: 23.1 PR5 (Authz + Preference + D29-NOTIFY deploy)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Codex thread**: `019dfaaa-a82e-77f1-8df8-b70e8ad9a9a1` (plan-time AGREE + post-impl AGREE)
> **Backend PR**: `platform-backend#65` (commit `<final-merge-sha>`)

## Bağlam

Faz 23.1 son sub-PR (5/5). PR3 channel adapters + PR4 worker pipeline +
PR5 authz/preference guard birleştirip notification-orchestrator'ü
**test cluster D29-NOTIFY** seviyesinde aktive eder.

D29 3-tier kabul kriteri (CLAUDE.md HARD RULE #5):
1. **Up**: Pod Running + TCP 8089 reachable
2. **Functional**: POST /api/v1/notify/intents → 202 ACCEPTED + intent persist
3. **Zanzibar-ready**: synthetic intent + permission-service authz tuple
   match → DELIVERED; tuple eksik → BLOCKED_BY_AUTHZ visible delivery row

## Önkoşullar

### Backend (platform-backend)
- [x] PR #65 backend code Codex AGREE iter-2
- [x] CI 8/8 GREEN (Maven reactor + Testcontainers PG dahil)
- [x] CI image-push matrix'e `notification-orchestrator` eklendi
- [ ] Main merge sonrası ilk GHCR push: `sha-<short>` + digest
- [ ] Codex deploy-dispatch payload'a digest yansır

### GitOps (platform-k8s-gitops)
- [x] `kustomize/base/apps/notification-orchestrator/` PR5 keys absorb
- [x] `kustomize/overlays/test/eso/notify/externalsecret-notify.yaml` ESO bağlandı
- [x] `kustomize/overlays/test/kustomization.yaml` aktive (replicas=1, configmap patch)
- [ ] Vault path populate (operator manuel — D29 öncesi mutlak):
  - `kv/platform/notify/db` (username, password)
  - `kv/platform/notify/smtp` (host, username, password)
  - `kv/platform/notify/redaction` (pepper)
  - `kv/platform/notify/webhook` (signing_secret)
  - `kv/platform/notify/slack` (webhook_url)
  - `kv/platform/notify/authz` (internal_api_key)

### Permission-service
- [x] PR #65 `InternalAuthorizationController` + `OpenFgaAuthzService.checkPrincipal`
- [ ] OpenFGA model: `template:can_receive` relation tanımlı
- [ ] Test tuple seed (D29 verify için):
  - Pozitif: `template:auth-password-reset#can_receive@subscriber:1204`
  - Negatif: tuple yok → subscriber:9999 BLOCKED_BY_AUTHZ

## Adımlar (operatör/agent çalıştırır)

### 1. Vault path populate (operator manuel)

```bash
# kv-v2 store
vault kv put kv/platform/notify/db \
  username="notify_test" \
  password="<random-32>"

vault kv put kv/platform/notify/smtp \
  host="mailpit.platform-test.svc.cluster.local" \
  username="" \
  password=""  # Mailpit no-auth in test

vault kv put kv/platform/notify/redaction \
  pepper="<random-32>"

vault kv put kv/platform/notify/webhook \
  signing_secret="<random-32>"

vault kv put kv/platform/notify/slack \
  webhook_url="https://hooks.slack.com/services/T.../B.../..."

vault kv put kv/platform/notify/authz \
  internal_api_key="<random-32-must-match-permission-service>"

# permission-service tarafında AYNI key set edilir
vault kv put kv/platform/permission-service \
  internal_api_key="<same-as-above>"
```

**Doğrulama**:
```bash
vault kv list kv/platform/notify
# Çıktı: db smtp redaction webhook slack authz
```

### 2. PG `notify_db` schema bootstrap (host-compose Postgres)

```bash
# host-compose postgres'te DB + user yarat (Faz 23.1 Foundation V1 migration applies)
psql -h localhost -p 5432 -U postgres -c "CREATE DATABASE notify_db;"
psql -h localhost -p 5432 -U postgres -c "CREATE USER notify_test WITH PASSWORD '<from-vault>';"
psql -h localhost -p 5432 -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE notify_db TO notify_test;"
psql -h localhost -p 5432 -U postgres -d notify_db -c "CREATE SCHEMA notify AUTHORIZATION notify_test;"
```

### 3. ESO ExternalSecret apply

```bash
kubectl --context k3d-test apply -k kustomize/overlays/test/eso/notify
kubectl --context k3d-test -n platform-test get externalsecret notification-orchestrator-secrets
# Beklenen STATUS=Synced; SecretKind populate edildi
kubectl --context k3d-test -n platform-test get secret notification-orchestrator-secrets -o jsonpath='{.data}' | jq 'keys'
# Beklenen 9+ key (PG creds + SMTP + redaction + webhook + slack + authz)
```

### 4. Selective deployment apply (D17 koruma)

D17 koruma: full `apply -k overlays/test` YASAK (tüm replicas=0 patch'lerini tekrar uygular).

```bash
# Selective: notification-orchestrator manifestleri tek tek
kubectl --context k3d-test -n platform-test apply -f kustomize/base/apps/notification-orchestrator/serviceaccount.yaml
kubectl --context k3d-test -n platform-test apply -f kustomize/base/apps/notification-orchestrator/service.yaml
kubectl --context k3d-test -n platform-test apply -f kustomize/base/apps/notification-orchestrator/configmap.yaml

# Deployment overlay-patched form için kustomize build → apply:
kubectl --context k3d-test -n platform-test \
  kustomize kustomize/overlays/test \
  | yq 'select(.kind == "Deployment" and .metadata.name == "notification-orchestrator")' \
  | kubectl apply -f -
```

### 5. Tier-1 — Up (pod Running + TCP)

```bash
kubectl --context k3d-test -n platform-test get pods -l app.kubernetes.io/name=notification-orchestrator
# Beklenen: 1 Running, READY 1/1
kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator --timeout=120s

# TCP reachability
POD=$(kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=notification-orchestrator -o name | head -1)
kubectl --context k3d-test -n platform-test exec $POD -- wget -qO- http://localhost:8081/actuator/health
# Beklenen: {"status":"UP",...}
```

### 6. Tier-2 — Functional (intent submit → 202)

```bash
INTENT_ID=$(uuidgen)
KEY=$(uuidgen)

kubectl --context k3d-test -n platform-test port-forward svc/api-gateway 18080:8080 &
PF=$!
sleep 2

# Submit synthetic intent (synthetic JWT subscriber:1204)
# A2b.2 (2026-07-21): confidential smoke-client ROPC (client_id=frontend + DAG=false, A2c cutover);
# Vault path: kv/platform/keycloak/smoke-client; scope=openid smoke-notify-v1 (org_id capability)
SMOKE_CLIENT_SECRET=$(ssh halil@staging-sw '
  VT=$(python3 -c "import json; print(json.load(open(\"/home/halil/bootstrap-drill/vault-init-test.json\"))[\"root_token\"])")
  docker exec -e VAULT_TOKEN=$VT platform-vault-test vault kv get -field=client_secret kv/platform/keycloak/smoke-client
')
TEST_PERSONA_PASSWORD=$(ssh halil@staging-sw 'kubectl --context k3d-test -n platform-test get secret test-personas-perf-auth -o jsonpath="{.data.password}" | base64 -d')
TOKEN=$(curl -s -X POST "https://testai.acik.com/realms/platform-test/protocol/openid-connect/token" \
  --data-urlencode "client_id=smoke-client" \
  --data-urlencode "client_secret=${SMOKE_CLIENT_SECRET}" \
  --data-urlencode "grant_type=password" \
  --data-urlencode "username=perf-test" \
  --data-urlencode "password=${TEST_PERSONA_PASSWORD}" \
  --data-urlencode "scope=openid smoke-notify-v1" | jq -r .access_token)

curl -X POST http://localhost:18080/api/v1/notify/intents \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Org-Id: default" \
  -H "Content-Type: application/json" \
  -d "{
    \"intentId\": \"$INTENT_ID\",
    \"idempotencyKey\": \"$KEY\",
    \"correlationId\": \"d29-verify-$INTENT_ID\",
    \"orgId\": \"default\",
    \"topicKey\": \"auth.password-reset\",
    \"severity\": \"info\",
    \"dataClassification\": \"security\",
    \"recipients\": [{
      \"type\": \"subscriber\",
      \"subscriberId\": \"1204\",
      \"locale\": \"tr-TR\"
    }],
    \"template\": {\"templateId\": \"auth-password-reset\", \"locale\": \"tr-TR\"},
    \"channels\": [\"email\"],
    \"payload\": {\"user_name\": \"D29 Verify\", \"reset_url\": \"https://x\"}
  }"

# Beklenen: HTTP 202 + {"intentId": "...", "status": "ACCEPTED"}
kill $PF

# DB verify
psql -h localhost -p 5432 -U notify_test -d notify_db -c \
  "SELECT intent_id, status, created_at FROM notify.notification_intent WHERE intent_id='$INTENT_ID';"
# Beklenen: 1 row, status=PENDING (worker tick'i öncesi) veya PROCESSING (sonrası)
```

### 7. Tier-3 — Zanzibar-ready (positive + negative authz)

```bash
# Pozitif tuple seed
kubectl --context k3d-test -n platform-test exec deploy/openfga -- \
  fga tuple write --store-id <store> \
    "subscriber:1204 can_receive template:auth-password-reset"

# OutboxPoller tick (5s default) sonrası DELIVERED görmek için
sleep 10
psql -h localhost -p 5432 -U notify_test -d notify_db -c \
  "SELECT intent_id, channel, status, recipient_hash FROM notify.notification_delivery WHERE intent_id='$INTENT_ID';"
# Beklenen: 1 row, channel=email, status=DELIVERED

# Negatif: yeni intent + subscriber:9999 (tuple yok)
INTENT_NEG=$(uuidgen)
# ... aynı POST body fakat subscriberId="9999"
# Beklenen: status=BLOCKED_BY_AUTHZ
psql -h localhost -p 5432 -U notify_test -d notify_db -c \
  "SELECT intent_id, channel, status, failure_reason FROM notify.notification_delivery WHERE intent_id='$INTENT_NEG';"
# Beklenen: status=BLOCKED_BY_AUTHZ; failure_reason='authz_deny: no_tuple'
```

### 8. Audit event verify

```bash
psql -h localhost -p 5432 -U notify_test -d notify_db -c \
  "SELECT event_type, channel, occurred_at FROM notify.audit_event WHERE intent_id='$INTENT_ID' ORDER BY occurred_at;"
# Beklenen sequence: INTENT_CREATED → DELIVERY_ATTEMPTED → DELIVERY_SUCCEEDED

psql -h localhost -p 5432 -U notify_test -d notify_db -c \
  "SELECT event_type, details FROM notify.audit_event WHERE intent_id='$INTENT_NEG';"
# Beklenen: INTENT_CREATED → DELIVERY_BLOCKED (NOT DELIVERY_ATTEMPTED — adapter çağrılmaz)
```

## Rollback

D29 fail → ESO + deployment revert:

```bash
kubectl --context k3d-test -n platform-test scale deploy/notification-orchestrator --replicas=0
kubectl --context k3d-test -n platform-test delete externalsecret notification-orchestrator-secrets
```

GitOps: PR revert → rollback overlay manifestleri.

## Devam eşiği

D29 3-tier hepsi PASS → Faz 23.1 **complete** ✓
- Up + Functional + Zanzibar-ready hep evidence'da görünür
- Faz 23.2 production MVP dar kapsamı planlanır (DKIM, ESO/Vault prod, TLS-only, multi-region)

D29 fail (herhangi bir tier) → blocker investigation + fix + retest. Codex 019dfaaa thread'de iter-N olarak izle.

## Referans

- ADR-0013: `docs/adr/0013-notification-orchestration.md`
- Charter: `docs/runbooks/RB-faz-23-charter.md`
- Backend PR: `Halildeu/platform-backend#65`
- Codex thread: `019dfaaa-a82e-77f1-8df8-b70e8ad9a9a1`
- Evidence: `docs/faz-23-evidence/2026-05-06-23-1-pr5-d29-notify.md`
