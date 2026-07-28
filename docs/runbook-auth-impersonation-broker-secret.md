# Runbook — `auth-impersonation-broker` Client Secret Provisioning

**Tetik:** User Impersonation v1 (PR-B) post-deploy — auth-service runtime
returns `502 TOKEN_EXCHANGE_FAILED` from
`POST /api/v1/impersonation/sessions` because `KeycloakBrokerClient`
cannot authenticate to the Keycloak token endpoint without
`AUTH_IMPERSONATION_BROKER_CLIENT_SECRET`.

**Pre-sync gate (HARD):** Do **not** apply the ExternalSecret manifest
in any cluster before the matching `impersonation_broker_client_secret`
field is provisioned in that cluster's Vault path. ESO will otherwise
fail to materialise the rendered Secret with `SecretSyncedError`,
which can ripple through other keys in the same `auth-service-secrets`
target (PG creds, JWT keys, KC client secret) once the existing key
revisions roll. Steps 1 → 2 → 3 must run in that order **per
environment**.

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

## Step 0.5 — Pre-merge sequencing for `platform-test` (HARD)

> Codex review iter-5 absorb: `argocd/applications/platform-test.yaml`
> has automated sync enabled, and the test overlay transitively
> includes this ExternalSecret via
> `kustomize/base/apps/ops-bundle → ../auth-service/ops`. Merging the
> PR without a Vault property in test ⇒ ArgoCD apply ⇒ ESO renders
> `SecretSyncedError` on `auth-service-secrets`, which can ripple
> through other keys in the same Secret target (PG creds, JWT keys,
> KC client secret) on the next reconcile cycle.

Before merging the PR, **one of the following must be true for
test**:

**Option A (preferred): pre-provision the test Vault property.**

Run Step 1 below against `platform-vault-test` first; the field can
hold the real KC client secret immediately, or a placeholder you
will replace via the same `vault kv patch` once the broker client
secret is verified in Step 0. Then merge the PR. Then run Steps 2–5.

**Option B: pause test ArgoCD auto-sync.**

```bash
# Pause auto-sync on the test ApplicationSet so merge does not
# auto-apply the ESO change. (Replace <argocd-ns> as appropriate.)
kubectl --context k3d-test -n <argocd-ns> patch application platform-test \
  --type merge \
  -p '{"spec":{"syncPolicy":{"automated":null}}}'
```

Merge PR → run Steps 1–4 → re-enable auto-sync:

```bash
kubectl --context k3d-test -n <argocd-ns> patch application platform-test \
  --type merge \
  -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
```

**Production (`platform-prod`) does not need this gate** — its
ArgoCD Application is manual-sync, so the prod path stays
operator-gated by default. Just be sure to run Step 1 against
`platform-vault-prod` before any prod overlay sync after this PR.

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

> Codex review iter-4 (thread `019e108a`) absorb: real PR-B contract is
> `POST /api/v1/impersonation/sessions`, body requires `targetUserId`
> (numeric, not optional), and the response shape is
> `{sessionId, exchangedToken, expiresAt, errorCode, errorMessage}` —
> there is no `status` field.

```bash
# A2b.2 (2026-07-21): confidential smoke-client ROPC (client_id=frontend + DAG=false, A2c cutover).
# Vault path: kv/platform/keycloak/smoke-client (A2a).
SMOKE_CLIENT_SECRET=$(sudo docker exec -e VAULT_TOKEN=<root> platform-vault-test \
  vault kv get -field=client_secret kv/platform/keycloak/smoke-client)

# Get a SuperAdmin admin token (real test admin, not the broker)
ADMIN_TOKEN=$(curl -sf -X POST \
  https://testai.acik.com/realms/platform-test/protocol/openid-connect/token \
  --data-urlencode 'grant_type=password' \
  --data-urlencode 'client_id=smoke-client' \
  --data-urlencode "client_secret=${SMOKE_CLIENT_SECRET}" \
  --data-urlencode 'username=<superadmin-test-persona>' \
  --data-urlencode 'password=<persona-password>' \
  | jq -r '.access_token')

# Call impersonation start (real PR-B contract)
curl -sf -X POST https://testai.acik.com/api/v1/impersonation/sessions \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "targetUserId": <platform-user-id>,
    "targetSubject": "<target-user-keycloak-sub>",
    "targetEmail": "<target-email>",
    "reason": "smoke-test"
  }' \
  | jq '{sessionId, expiresAt, hasToken: (.exchangedToken != null), errorCode, errorMessage}'
```

**Expected:** HTTP 201 Created, JSON body with non-null `sessionId`
(UUID), non-null `expiresAt` (ISO timestamp), `hasToken: true`, and
both `errorCode` and `errorMessage` null.

Auth-service log shows `IMPERSONATION_STARTED` audit event written via
`ImpersonationAuditClient` (best-effort path; absence does not fail
the request).

**Failure shape — broker secret still missing:**

```json
{ "errorCode": "TOKEN_EXCHANGE_FAILED",
  "errorMessage": "..." }
```

with HTTP 502 → re-run Step 1 (Vault path/property check) + Step 2
(ESO refresh).

**Failure shape — broker client missing token-exchange permission:**

```json
{ "errorCode": "TOKEN_EXCHANGE_FAILED",
  "errorMessage": "...access_denied..." }
```

→ Step 0.2 (Keycloak Authorization tab → token-exchange permission).

**Failure shape — gateway route missing (`/api/v1/impersonation/**`):**

```
HTTP 404 from gateway (request never reaches auth-service)
```

→ This PR also adds the route to
`kustomize/base/apps/api-gateway/configmap.yaml` (Codex iter-4
absorb). If running the runbook against a cluster where the route
is not yet applied, port-forward auth-service directly:

```bash
kubectl --context k3d-test -n platform-test port-forward deploy/auth-service 8088:8088
# then hit http://127.0.0.1:8088/api/v1/impersonation/sessions
```

---

## Step 5 — Audit verify (DoD #6)

> Codex review iter-4 absorb: the real V19 schema uses the **plural**
> table `permission_audit_events`, the discriminator column is
> `event_type` (not `status`), and the timestamp column is
> `occurred_at` (not `started_at`).

```bash
sudo docker exec platform-pg-test psql -U postgres -d permission_db \
  -c "SELECT event_type, action, target_email,
             impersonation_session_id, occurred_at
      FROM permission_audit_events
      WHERE event_type = 'IMPERSONATION_STARTED'
      ORDER BY id DESC LIMIT 5;"
```

**Expected:** an `IMPERSONATION_STARTED` row with the smoke target's
`target_email` (or null if KC sub-only), non-null
`impersonation_session_id` (matches the `sessionId` returned by Step 4),
recent `occurred_at`.

---

## Rollback

If broker secret rollout breaks auth-service:

```bash
# 1. Revert the ExternalSecret + runbook + gateway-route PR
git revert <this-PR-merge-sha>
git push origin main

# 2. Force ESO to drop the broker key from the rendered Secret
kubectl --context k3d-test -n platform-test annotate externalsecret \
  auth-service-secrets force-sync="$(date +%s)" --overwrite

# 3. Verify the key is gone from the rendered Secret
#    (jq -e returns non-zero exit code if the key still exists)
kubectl --context k3d-test -n platform-test get secret auth-service-secrets \
  -o jsonpath='{.data}' \
  | jq -e 'has("AUTH_IMPERSONATION_BROKER_CLIENT_SECRET") | not'

# 4. Rolling restart auth-service so the env drops the variable
kubectl --context k3d-test -n platform-test rollout restart deploy/auth-service
kubectl --context k3d-test -n platform-test rollout status deploy/auth-service --timeout=120s
```

**Optional cleanup (hygiene only — not required):**

```bash
# Drop the field from Vault path so it isn't materialised on a future
# accidental re-apply. Other keys at the path are preserved.
sudo docker exec -e VAULT_TOKEN=<root> -e VAULT_ADDR=http://127.0.0.1:8200 \
  platform-vault-test \
  vault kv patch -remove-data=impersonation_broker_client_secret \
    kv/platform/auth-service
```

After rollback, `POST /api/v1/impersonation/sessions` returns
502 `TOKEN_EXCHANGE_FAILED` (pre-PR state). No other auth-service
endpoint is affected.

---

## Notes / Boundary

This runbook involves **credential-read** (KC admin → Vault),
**credential-write** (Vault patch), and **state-mutation** (cluster
Secret refresh + Deployment rollout). It is intentionally
operator-domain because the in-process agent sandbox blocks credential
exploration; the agent contributed the declarative ExternalSecret
mapping (this PR) but cannot harvest the broker secret value
autonomously.

**PR boundary vs runbook boundary:** the PR diff itself is
declarative-only (`credential-write` wiring, no real secrets in repo).
The runbook execution adds `credential-read` (operator opens KC admin
console + reads existing client secret). The PR body distinguishes
these two boundary scopes.

**Refs:**

- PR-B (User Impersonation v1) — `auth-service` `KeycloakBrokerClient`
- PR #479 (auth-service ConfigMap hotfix) — placeholder error fix
- Spec: `platform-backend/docs/plans/2026-05-user-impersonation-v1-spec.md`
- Spike: `platform-backend/docs/spikes/2026-05-impersonation-token-exchange-spike.md`
