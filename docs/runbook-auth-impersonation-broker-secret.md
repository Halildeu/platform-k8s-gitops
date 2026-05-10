# Runbook — `auth-impersonation-broker` Client Secret Provisioning

**Tetik:** User Impersonation v1 (PR-B) post-deploy — auth-service runtime
returns `502 TOKEN_EXCHANGE_FAILED` from `POST /api/v1/auth/impersonation/start`
because `KeycloakBrokerClient` cannot authenticate to the Keycloak token
endpoint without `AUTH_IMPERSONATION_BROKER_CLIENT_SECRET`.

**Scope:** test cluster (`platform-test` realm) and prod cluster
(`serban` realm) — run once per environment.

**Why a runbook (and not full agent automation):** Reading the Keycloak
admin password and the Vault root token is a credential-exploration
boundary the in-process sandbox blocks. The agent prepared the
ExternalSecret + Deployment wiring; the operator runs the
five-step script below.

**Pre-requisites:**

- SSH access to `staging-sw` with `sudo`
- Local `vault` and `kubectl` clients (or use `docker exec` into
  `platform-vault-test` / `platform-vault-prod`)
- The `impersonation-broker` Keycloak client must already exist in
  the target realm with **service accounts enabled** and **token-exchange
  permission** (see Step 0 if it does not).

---

## Step 0 — Verify (or create) the `impersonation-broker` client

1. Open Keycloak admin console for the target realm:
   - test: `https://testai.acik.com/admin/master/console/#/platform-test/clients`
   - prod: `https://api.acik.com/admin/master/console/#/serban/clients`

2. Confirm a client named `impersonation-broker` exists with:
   - **Access Type / Client authentication:** ON (confidential)
   - **Service accounts roles:** ON
   - **Standard flow:** OFF
   - **Direct access grants:** OFF
   - **Token exchange:** enabled (Authorization tab → token exchange permission)
   - **Audience mapper:** value = `frontend`

3. If the client does not exist, create it via the admin console
   (out of scope for this runbook — see
   `platform-backend/docs/spikes/2026-05-impersonation-token-exchange-spike.md`
   §3 for the create steps).

4. Open **Credentials** tab → copy the current **Client secret** value.
   This is the value you will write into Vault.

---

## Step 1 — Write the broker secret into Vault

Path: `kv/platform/auth-service`. Existing keys at this path
(`db_username`, `db_password`, `jwt_private_key`, `jwt_public_key`,
`keycloak_client_secret`) **must be preserved** — use `vault kv patch`,
not `vault kv put` (which would replace the entire secret).

```bash
# test cluster
sudo docker exec -e VAULT_TOKEN=<root> -e VAULT_ADDR=http://127.0.0.1:8200 \
  platform-vault-test \
  vault kv patch kv/platform/auth-service \
    impersonation_broker_client_secret='<paste-from-step-0.4>'

# prod cluster (when ready)
sudo docker exec -e VAULT_TOKEN=<root> -e VAULT_ADDR=http://127.0.0.1:8200 \
  platform-vault-prod \
  vault kv patch kv/platform/auth-service \
    impersonation_broker_client_secret='<paste-from-step-0.4>'
```

**Verify:**

```bash
sudo docker exec platform-vault-test vault kv get -format=json kv/platform/auth-service \
  | jq '.data.data | keys'
# Expect: ["db_password", "db_username", "impersonation_broker_client_secret",
#         "jwt_private_key", "jwt_public_key", "keycloak_client_secret"]
```

---

## Step 2 — Force ESO refresh (so the in-cluster Secret picks up the new key)

The `auth-service-secrets` ExternalSecret's `refreshInterval` is `1h`,
so without a force-sync the new key would not appear in the K8s Secret
for up to one hour.

```bash
kubectl --context k3d-test -n platform-test annotate externalsecret \
  auth-service-secrets force-sync="$(date +%s)" --overwrite

# Wait ~5 seconds, then verify the key is materialised:
kubectl --context k3d-test -n platform-test get secret auth-service-secrets \
  -o jsonpath='{.data}' | jq 'keys' | grep AUTH_IMPERSONATION_BROKER_CLIENT_SECRET
```

If the key is missing, check the ExternalSecret status:

```bash
kubectl --context k3d-test -n platform-test describe externalsecret auth-service-secrets \
  | tail -30
```

`SecretSyncedError` here usually means the Vault path / property
mismatched (Step 1.verify) or the Vault token expired (re-auth ESO).

---

## Step 3 — Rolling restart auth-service (envFrom pickup)

```bash
kubectl --context k3d-test -n platform-test rollout restart deploy/auth-service
kubectl --context k3d-test -n platform-test rollout status deploy/auth-service --timeout=120s
```

---

## Step 4 — Smoke test (functional verify)

```bash
# Get a SuperAdmin admin token (real test admin, not the broker)
ADMIN_TOKEN=$(curl -sf -X POST \
  https://testai.acik.com/realms/platform-test/protocol/openid-connect/token \
  -d 'grant_type=password' \
  -d 'client_id=frontend' \
  -d 'username=<superadmin-test-persona>' \
  -d 'password=<persona-password>' \
  | jq -r '.access_token')

# Call impersonation/start
curl -sf -X POST https://testai.acik.com/api/v1/auth/impersonation/start \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"targetSubject":"<target-user-keycloak-sub>","reason":"smoke-test"}' \
  | jq '{status: .status, sessionId: .sessionId}'
```

**Expected:** HTTP 201 Created, JSON body with `status: "ACTIVE"` and
a UUID `sessionId`. Auth-service log shows `IMPERSONATION_STARTED`
audit event written via `ImpersonationAuditClient`.

**Failure shape — broker secret still missing:**

```
502 — TOKEN_EXCHANGE_FAILED — keycloak token endpoint returned 401
```

→ re-run Step 1 (Vault path/property check) + Step 2 (ESO refresh).

**Failure shape — broker client missing token-exchange permission:**

```
502 — TOKEN_EXCHANGE_FAILED — keycloak returned access_denied
```

→ Step 0.2 (Keycloak Authorization tab → token-exchange permission).

---

## Step 5 — Audit verify (DoD #6)

```bash
sudo docker exec platform-pg-test psql -U postgres -d permission_db \
  -c "SELECT action, status, target_email, started_at
      FROM permission_audit_event
      WHERE action LIKE 'IMPERSONATION_%'
      ORDER BY id DESC LIMIT 5;"
```

**Expected:** `IMPERSONATION_STARTED` row with the smoke target user,
non-null `impersonation_session_id`, `status='SUCCESS'`.

---

## Rollback

If broker secret rollout breaks auth-service:

```bash
# Revert the ExternalSecret to the previous version (drop the new key)
git revert <this-PR-merge-sha>
git push origin main

# ESO will rotate auth-service-secrets without the broker key
# Auth-service rolling restart removes AUTH_IMPERSONATION_BROKER_CLIENT_SECRET
# Impersonation/start endpoint returns 502 again (pre-PR state),
# but no other auth-service endpoint is affected.
```

---

## Notes / Boundary

This runbook involves **credential read** (KC admin → Vault) and
**state-mutation** (Vault patch + cluster Secret refresh + Deployment
rollout). It is intentionally operator-domain because the in-process
agent sandbox blocks credential exploration; the agent contributed the
declarative ExternalSecret mapping (this PR) but cannot harvest the
broker secret value autonomously.

**Refs:**

- PR-B (User Impersonation v1) — `auth-service` `KeycloakBrokerClient`
- PR #479 (auth-service ConfigMap hotfix) — placeholder error fix
- Spec: `platform-backend/docs/plans/2026-05-user-impersonation-v1-spec.md`
- Spike: `platform-backend/docs/spikes/2026-05-impersonation-token-exchange-spike.md`
