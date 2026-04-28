# OpenFGA Multi-Org Model Rollout Runbook (Faz 21.3)

> **Status**: PROPOSED — manifest-merged, **not yet executed**.
> **Authority**: ADR-0008 (this repo) + backend repo OpenFGA model PR.
> Each step is **operator-gated**; agents do not execute these without
> explicit user approval per step.

## Pre-conditions

- [ ] Backend repo PR (platform-ssot or successor): `openfga-authorization-model.fga`
      semantic update per ADR-0008 explicit-scope contract:
      (a) Remove auto-grant relations (`admin from org`, `viewer: ...
      or member`, etc.) from `company`, `project`, `warehouse`, `branch`.
      (b) Add `parent_warehouse: [warehouse]` for 3-level Depo→Lokasyon
      →Raf navigation (no transitive viewer grant).
      (c) Tuple writer maps PG `scope_kind='depot'` → OpenFGA
      `warehouse` object_type.
      (Existing types — organization + company + project + warehouse +
      branch — already present in upstream model; no NEW types added.)
      REST API integrated with `data_access.scope` (V19/V20 already on
      target PG via PR #163, #165).
- [ ] V19 + V20 already applied on target PG cluster
      (`reports_db.data_access.{organization, organization_company, scope}`
      + `validate_scope_ref()` depot/DEPARTMENT branch).
- [ ] D29 Zanzibar-ready disiplini son state'i kanıtlı: existing
      synthetic allow/deny enforce baseline still passing (k6
      `tests/k6/zanzibar-load.js`).
- [ ] Operator has access to:
      - Vault `kv/platform/openfga` (`model_id` property)
      - SSH staging-sw kubectl
      - psql to host PG (lineage verification)

## Step 0 — Pre-flight inventory (no cluster touch)

```bash
# Existing model_id (so rollback target is known)
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get externalsecret -o yaml | grep -i 'model_id' | head -5"

# Existing tuple count
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/permission-service -- curl -s \
  http://openfga:8080/stores/<store_id>/read?... | jq '.tuples | length'"

# data_access.scope row count
ssh halil@staging-sw "PGPASSWORD='<...>' psql -h 172.19.0.6 -U postgres \
  -d reports_db -c 'SELECT count(*) FROM data_access.scope WHERE revoked_at IS NULL;'"
```

**Operator gate**: capture (a) old `model_id`, (b) tuple count, (c) active
scope rows. These are rollback anchors.

## Step 1 — Backend image deploy (feature flag OFF)

```bash
# Backend repo PR merged → CI builds new permission-service image with
# tuple writer, but feature flag MULTI_ORG_TUPLE_SYNC_ENABLED=false.
# Roll the new image into k3d-test:
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  set image deploy/permission-service permission-service=<new-image>"
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  rollout status deploy/permission-service --timeout=120s"
```

**Operator gate**: pod Ready 1/1 + existing `/authz/version` endpoint
returns 200 with old model_id. Behaviour unchanged at this point.

## Step 2 — Write new OpenFGA model (capture new model_id)

```bash
# From operator host, with FGA_API token sourced safely from Vault:
fga model write --store-id <store_id> \
  --file openfga-authorization-model.fga > /tmp/model_write_response.json
NEW_MODEL_ID=$(jq -r '.authorization_model_id' /tmp/model_write_response.json)
echo "NEW_MODEL_ID=${NEW_MODEL_ID}"
```

**Operator gate**: paste `NEW_MODEL_ID`. Should be a 26-char ULID.

## Step 3 — Vault model_id rotate

```bash
# Operator updates Vault — agent does not touch Vault.
vault kv patch kv/platform/openfga model_id="${NEW_MODEL_ID}"
```

ESO refresh interval (per existing ExternalSecret manifests) is 1h.
The Vault `kv/platform/openfga` `model_id` property is consumed by **4
ExternalSecrets** in this repo (each with `secretKey: ERP_OPENFGA_MODEL_ID`):

- `permission-service-secrets`
- `core-data-service-secrets`
- `variant-service-secrets`
- `user-service-secrets`

Force manual refresh on all four:

```bash
for es in permission-service-secrets core-data-service-secrets \
          variant-service-secrets user-service-secrets; do
  ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
    annotate externalsecret \"$es\" force-sync=\"$(date +%s)\" --overwrite"
done
```

**Operator gate**: confirm each ExternalSecret shows `STATUS=SecretSynced`
with refreshed `lastTransitionTime`. NOTE — the `openfga-secrets` Secret
in this repo is the OpenFGA datastore credential stub, NOT the
`model_id` carrier; do NOT annotate it for this rotate.

## Step 4 — Rollout services consuming the model

Only the 4 services with the ExternalSecret `ERP_OPENFGA_MODEL_ID` key
need to restart for the model_id rotate to take effect. Other services
(auth-service, schema-service, report-service, api-gateway) do not
consume the model_id env in this repo's manifests.

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  rollout restart deploy/permission-service deploy/core-data-service \
  deploy/variant-service deploy/user-service"

for svc in permission-service core-data-service variant-service user-service; do
  ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
    rollout status deploy/$svc --timeout=180s"
done
```

**Operator gate**: each pod Ready 1/1 with new model_id env. Confirm
the canonical env variable name (`ERP_OPENFGA_MODEL_ID`, NOT
`OPENFGA_MODEL_ID`):

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/permission-service -- env | grep ERP_OPENFGA_MODEL_ID"
# expect ERP_OPENFGA_MODEL_ID=<NEW_MODEL_ID>
```

## Step 5 — Existing-state regression check

Existing baseline behavior MUST still work (the new model is
additive — `user`, `company`, `project`, `variant` types preserved).

```bash
# Run k6 baseline:
ssh halil@staging-sw "k6 run --duration 30s tests/k6/zanzibar-load.js"
```

Plus targeted curl smoke (existing dev fixture):

```bash
# Should still allow user:dev@localtest.me viewer project:dev-local
curl -X POST http://staging-sw:30080/authz/check ... \
  -d '{"user":"user:dev@localtest.me","relation":"viewer","object":"project:dev-local"}'
# expect {"allowed": true}
```

**Operator gate**: regression k6 thresholds still passing; existing
allow/deny set unchanged.

## Step 6 — Tuple migration (data_access.scope → OpenFGA tuples)

Backend tuple writer needs to backfill existing `data_access.scope` rows.
Two paths:

### 6a) Outbox auto-drain (preferred)

```bash
# Backend exposes a backfill endpoint feature-flagged:
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/permission-service -- curl -X POST \
  http://localhost:8080/internal/access/scope/backfill \
  -H 'Authorization: Bearer <internal-token>'"
# Backend reads data_access.scope WHERE revoked_at IS NULL and
# writes tuples idempotently.
```

### 6b) Manual psql + tuple write (fallback)

```bash
# Generate tuple write commands from data_access.scope:
ssh halil@staging-sw "PGPASSWORD='<...>' psql -h 172.19.0.6 -U postgres \
  -d reports_db -c '\copy (
    SELECT user_id, scope_kind, scope_ref FROM data_access.scope
    WHERE revoked_at IS NULL
  ) TO /tmp/scope-backfill.csv WITH CSV;'"
# Operator writes the tuples via fga CLI (deterministic encoding from
# ADR-0008 § Object id encoding).
```

**Operator gate**: row count match — `data_access.scope WHERE revoked_at IS
NULL` count == OpenFGA tuple count for new types.

## Step 7 — Verification (D29 Zanzibar-ready third level)

```bash
# Allow case (positive)
curl -X POST .../authz/check \
  -d '{"user":"user:<seed-admin>","relation":"admin","object":"organization:acik"}'
# expect {"allowed": true}

# Deny case 1 — org member ≠ company viewer (explicit-only contract)
curl -X POST .../authz/check \
  -d '{"user":"user:<member-only>","relation":"viewer","object":"company:wc-company-1001"}'
# expect {"allowed": false}

# Deny case 2 — depot hierarchy auto-grant absent
# user has explicit warehouse:wc-department-3792 viewer; check sub-depot 3792-01:
curl -X POST .../authz/check \
  -d '{"user":"user:<depot-viewer>","relation":"viewer","object":"warehouse:wc-department-3792-01"}'
# expect {"allowed": false}

# Cross-kind deny — company viewer doesn't see depot
curl -X POST .../authz/check \
  -d '{"user":"user:<company-viewer>","relation":"viewer","object":"warehouse:wc-department-3792"}'
# expect {"allowed": false}
```

**Operator gate**: 1 allow + 3 deny scenarios all match. If any
mismatch, STOP — do not enable feature flag.

## Step 8 — Feature flag ON (gradual)

Faz 21.3 PR-C downstream introduces a fail-closed activation flag
`REPORTS_DB_ENABLED` (default `false`). The dual-datasource bean
graph (`ReportsDbDataSourceConfig`) only instantiates when this flag
is `"true"`. After Faz 21.3 PR-D delivery the activation gate is
property-based: `AccessScopeService` requires BOTH
`spring.datasource.reports-db.enabled=true` AND
`erp.openfga.enabled=true` (multi-name `@ConditionalOnProperty`,
AND semantic). With either flag absent or `false` the service bean
is absent and every REST endpoint returns 503 SERVICE_UNAVAILABLE.

### Pre-flip operator authz tuple seed (Faz 21.3 PR-D)

The new `/api/v1/access/scope` endpoints are gated by
`@RequireModule("ACCESS", "can_manage")` (grant + revoke) and
`@RequireModule("ACCESS", "can_view")` (list). Both relations are
`type module` in `backend/openfga/model.fga`. **Operators who will
issue scope grants in the UI/API need the tuples seeded BEFORE the
flag flip — otherwise the first POST to `/api/v1/access/scope`
returns 403.**

```bash
# For each user who will administer scope assignments (org admins),
# seed two tuples on the OpenFGA store. Operator runs once per admin uid.
ADMIN_UID="<admin-user-uuid>"
STORE_ID=$(vault kv get -field=store_id kv/platform/openfga)
MODEL_ID=$(vault kv get -field=model_id kv/platform/openfga)

curl -s -X POST "${OPENFGA_URL}/stores/${STORE_ID}/write" \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  "authorization_model_id": "${MODEL_ID}",
  "writes": {
    "tuple_keys": [
      {"user": "user:${ADMIN_UID}", "relation": "can_manage", "object": "module:ACCESS"},
      {"user": "user:${ADMIN_UID}", "relation": "can_view",   "object": "module:ACCESS"}
    ]
  }
}
EOF
```

Verify with a `/check`:

```bash
curl -s -X POST "${OPENFGA_URL}/stores/${STORE_ID}/check" \
  -H 'Content-Type: application/json' \
  -d "{\"authorization_model_id\":\"${MODEL_ID}\",\"tuple_key\":{\"user\":\"user:${ADMIN_UID}\",\"relation\":\"can_manage\",\"object\":\"module:ACCESS\"}}"
# expect {"allowed":true}
```

Seed users for scope viewers (regular users who only LIST their own
scopes) need only `can_view`. Skip if list endpoint isn't exposed
to that user persona.

### Vault credentials must be populated **before** the flip:

```bash
# 1. Populate reports_db credentials in Vault (operator)
vault kv patch kv/platform/permission-service \
  reports_db_username="<read-only-user>" \
  reports_db_password="<value>"

# 2. ESO force-refresh permission-service-secrets to pick up the new keys
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  annotate externalsecret permission-service-secrets \
  force-sync=\"$(date +%s)\" --overwrite"

# 3. Verify the secret has REPORTS_DB_USERNAME + REPORTS_DB_PASSWORD
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get secret permission-service-secrets -o jsonpath='{.data}' | \
  jq 'keys' | grep -E 'REPORTS_DB_(USERNAME|PASSWORD)'"
# expect both keys present

# 4. Flip activation flag in ConfigMap (or via env override in Deployment)
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  set env deploy/permission-service REPORTS_DB_ENABLED=true"
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  rollout restart deploy/permission-service"
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  rollout status deploy/permission-service --timeout=120s"

# 5. Verify reports_db datasource bean graph is up
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/permission-service -- env | \
  grep -E 'REPORTS_DB_(ENABLED|URL|USERNAME|PASSWORD)'"
# expect REPORTS_DB_ENABLED=true + URL/USERNAME/PASSWORD present

# 6. (Optional) actuator health check (if reports-db indicator wired)
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/permission-service -- \
  curl -s http://localhost:8081/actuator/health/reports_db 2>/dev/null || \
  echo 'health indicator not wired — tail logs for HikariCP connect line'"
```

**Operator gate**: pod Ready 1/1 + the Spring log line "HikariPool-2 - Start completed."
or equivalent appears (proves the secondary datasource initialised). Without that
the flag flip is inert; PR-D's REST `/api/v1/access/scope` endpoint will return
500 because `DataAccessScopeRepository` won't be wired.

After PR-G (V22 + V23 outbox migration + backend poller) merge: grant/revoke
no longer write to OpenFGA synchronously. Backend writes a row to
`data_access.scope_outbox` in the same transaction as the `data_access.scope`
INSERT/UPDATE; the `OutboxPoller` background service (in permission-service)
claims `PENDING` rows via `FOR UPDATE SKIP LOCKED`, calls OpenFGA, and marks
the row `PROCESSED`. **D35 evidence semantic shifts from "POST → immediate
allow" to "POST → outbox row → poller processed → eventual allow"** — see
Step 9 below.

## Step 9 — D35 first evidence (post-V22+V23+PR-G — eventual consistency)

Faz 21.3 outbox lands a transactional outbox between PG `scope` row and
OpenFGA tuple write. D35 evidence MUST validate the FULL eventual-consistency
chain rather than synchronous grant→allow. Codex `019dd0e0` iter-2 explicit
verdict: D35 evidence after V22+V23 must include `outbox row state`,
`poller evidence`, and `OpenFGA allow/deny` together.

### 11-step evidence sequence

Each step yields a captured artifact saved to
`docs/faz-21-3-evidence/2026-XX-XX-d35-first-smoke-staging-test.md`.

```bash
# Setup (operator runs once per evidence pass)
RUN_ID="d35-$(date +%Y%m%d-%H%M)"
USER_UID_GRANTED="<actual user uuid that should receive scope>"
USER_UID_DENIED="<other user uuid for negative assertion>"
ORG_ID=1  # AÇIK
SCOPE_KIND="company"
SCOPE_REF='["1001"]'  # canonical JSON form, V21 contract
EXPECTED_TUPLE_OBJECT="company:wc-company-1001"
GRANT_USER="user:${USER_UID_GRANTED}"

mkdir -p docs/faz-21-3-evidence
EVIDENCE="docs/faz-21-3-evidence/${RUN_ID}.md"
echo "# D35 first evidence — ${RUN_ID}" > ${EVIDENCE}
echo "Started: $(date -Iseconds)" >> ${EVIDENCE}
```

#### Step 9.1 — Artifact digest match

Confirm the running permission-service is the post-V22+V23 image (sha-`<merge_sha>`
or later):

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get pod -l app=permission-service \
  -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'"
# expect ghcr.io/halildeu/platform-backend-permission-service@sha256:<digest>
# Match against gitops kustomize/overlays/test/kustomization.yaml current pin.
```

Append the imageID line to ${EVIDENCE}.

**Operator gate**: digest matches the gitops overlay pin. If not, ArgoCD sync
hasn't propagated yet — wait or force `argocd app sync platform-test`.

#### Step 9.2 — REPORTS_DB_ENABLED + datasource env evidence

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/permission-service -- env | \
  grep -E 'REPORTS_DB_(ENABLED|URL|USERNAME|PASSWORD)|ERP_OPENFGA_ENABLED'"
# expect:
#   REPORTS_DB_ENABLED=true
#   REPORTS_DB_URL=jdbc:postgresql://postgres:5432/reports_db
#   REPORTS_DB_USERNAME=<populated>
#   REPORTS_DB_PASSWORD=<populated, redacted in evidence>
#   ERP_OPENFGA_ENABLED=true
```

Append to ${EVIDENCE} (redact PASSWORD value).

**Operator gate**: all 5 env vars present. Missing → re-run Step 8 ESO refresh.

#### Step 9.3 — Outbox poller enabled + config visible

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  logs deploy/permission-service --tail=200 | \
  grep -E 'OutboxPoller|app.outbox|HikariPool-(1|2) - Start completed'"
# expect at least:
#   - "HikariPool-1 - Start completed." (primary auth_db)
#   - "HikariPool-2 - Start completed." (secondary reports_db)
#   - OutboxPoller scheduler started (config: batch_size=25, poll_interval=5s, etc.)
```

Append to ${EVIDENCE}. Operator gate: secondary HikariPool started + scheduler
log line.

#### Step 9.4 — POST grant creates `data_access.scope` row

```bash
# JWT token from ${USER_UID_GRANTED} as actor (or admin-on-behalf-of pattern)
JWT_ADMIN="<admin token who has module:ACCESS#can_manage>"

GRANT_RESPONSE=$(curl -s -X POST https://testai.acik.com/api/v1/access/scope \
  -H "Authorization: Bearer ${JWT_ADMIN}" \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  "userId": "${USER_UID_GRANTED}",
  "orgId": ${ORG_ID},
  "scopeKind": "${SCOPE_KIND^^}",
  "scopeRef": "${SCOPE_REF}"
}
EOF
)
echo "${GRANT_RESPONSE}" >> ${EVIDENCE}

SCOPE_ID=$(echo "${GRANT_RESPONSE}" | jq -r .scopeId)
OUTBOX_ID=$(echo "${GRANT_RESPONSE}" | jq -r .outboxId)
TUPLE_SYNC_STATUS_INITIAL=$(echo "${GRANT_RESPONSE}" | jq -r .tupleSyncStatus)

echo "scope_id=${SCOPE_ID} outbox_id=${OUTBOX_ID} initial=${TUPLE_SYNC_STATUS_INITIAL}" >> ${EVIDENCE}
```

**Operator gate**: HTTP 201 + `scopeId` numeric + `outboxId` numeric +
`tupleSyncStatus="PENDING"` + `processedAt=null`.

#### Step 9.5 — `data_access.scope` row visible in PG

```bash
ssh halil@staging-sw "PGPASSWORD='<...>' psql -h 172.19.0.6 -U postgres \
  -d reports_db -c '
SELECT id, user_id, org_id, scope_kind, scope_ref, granted_at, revoked_at
FROM data_access.scope WHERE id = ${SCOPE_ID};
'"
# expect 1 row, revoked_at = NULL, scope_ref matches '["1001"]' (JSON canonical)
```

Append to ${EVIDENCE}. Operator gate: row exists, scope_ref is JSON form, no
revoked_at.

#### Step 9.6 — Matching `data_access.scope_outbox` PENDING row

```bash
ssh halil@staging-sw "PGPASSWORD='<...>' psql -h 172.19.0.6 -U postgres \
  -d reports_db -c '
SELECT id, scope_id, action, status, attempt_count, tuple_user, tuple_relation, tuple_object,
       next_attempt_at, locked_by, locked_until, created_at, processed_at, last_error
FROM data_access.scope_outbox WHERE id = ${OUTBOX_ID};
'"
# expect:
#   - status: PENDING (or PROCESSING/PROCESSED if poller already claimed)
#   - tuple_user: user:${USER_UID_GRANTED}
#   - tuple_relation: viewer
#   - tuple_object: company:wc-company-1001
#   - attempt_count: 0 (or 1 if PROCESSING)
#   - last_error: NULL
```

Append. Operator gate: row exists with V23 typed columns populated correctly.

#### Step 9.7 — Outbox row reaches `PROCESSED` (eventual consistency assertion)

```bash
# Poll up to 30s for status transition (poller default poll_interval=5s)
for i in $(seq 1 6); do
  STATUS=$(ssh halil@staging-sw "PGPASSWORD='<...>' psql -h 172.19.0.6 \
    -U postgres -d reports_db -t -c \
    \"SELECT status FROM data_access.scope_outbox WHERE id = ${OUTBOX_ID};\"" | xargs)
  echo "  attempt ${i}: status=${STATUS}" | tee -a ${EVIDENCE}
  if [[ "${STATUS}" == "PROCESSED" ]]; then break; fi
  sleep 5
done

# Final state assertion
ssh halil@staging-sw "PGPASSWORD='<...>' psql -h 172.19.0.6 -U postgres \
  -d reports_db -c '
SELECT id, status, processed_at, attempt_count
FROM data_access.scope_outbox WHERE id = ${OUTBOX_ID};
'" >> ${EVIDENCE}
# expect status='PROCESSED' + processed_at non-null + attempt_count >= 1
```

**Operator gate**: outbox row reaches `PROCESSED` within ~30s. If still
`PENDING` after 60s → poller not running. If `FAILED` → see Step 9.11.

#### Step 9.8 — OpenFGA `/check` allows granted user

```bash
STORE_ID=$(vault kv get -field=store_id kv/platform/openfga)
MODEL_ID=$(vault kv get -field=model_id kv/platform/openfga)

ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/openfga -- curl -s \
  http://localhost:8080/stores/${STORE_ID}/check \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  \"authorization_model_id\": \"${MODEL_ID}\",
  \"tuple_key\": {
    \"user\": \"${GRANT_USER}\",
    \"relation\": \"viewer\",
    \"object\": \"${EXPECTED_TUPLE_OBJECT}\"
  }
}
EOF
" | tee -a ${EVIDENCE}
# expect {"allowed": true}
```

Operator gate: `allowed=true` for granted user.

#### Step 9.9 — Negative user remains denied

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/openfga -- curl -s \
  http://localhost:8080/stores/${STORE_ID}/check \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  \"authorization_model_id\": \"${MODEL_ID}\",
  \"tuple_key\": {
    \"user\": \"user:${USER_UID_DENIED}\",
    \"relation\": \"viewer\",
    \"object\": \"${EXPECTED_TUPLE_OBJECT}\"
  }
}
EOF
" | tee -a ${EVIDENCE}
# expect {"allowed": false}
```

Operator gate: `allowed=false` for non-granted user. (D29 third level —
synthetic deny enforce.)

#### Step 9.10 — Revoke creates REVOKE outbox row + allow flips to deny

```bash
curl -s -X DELETE "https://testai.acik.com/api/v1/access/scope/${SCOPE_ID}" \
  -H "Authorization: Bearer ${JWT_ADMIN}" \
  -w '%{http_code}\n' | tee -a ${EVIDENCE}
# expect HTTP 204

# Verify REVOKE outbox row appears
ssh halil@staging-sw "PGPASSWORD='<...>' psql -h 172.19.0.6 -U postgres \
  -d reports_db -c '
SELECT id, scope_id, action, status, tuple_user, tuple_object
FROM data_access.scope_outbox WHERE scope_id = ${SCOPE_ID} ORDER BY id;
'" >> ${EVIDENCE}
# expect 2 rows: GRANT (PROCESSED) + REVOKE (PENDING/PROCESSING/PROCESSED)

# Wait for REVOKE PROCESSED
for i in $(seq 1 6); do
  STATUS=$(ssh halil@staging-sw "PGPASSWORD='<...>' psql -h 172.19.0.6 \
    -U postgres -d reports_db -t -c \
    \"SELECT status FROM data_access.scope_outbox \
       WHERE scope_id = ${SCOPE_ID} AND action='REVOKE' \
       ORDER BY id DESC LIMIT 1;\"" | xargs)
  echo "  revoke poll ${i}: status=${STATUS}" | tee -a ${EVIDENCE}
  if [[ "${STATUS}" == "PROCESSED" ]]; then break; fi
  sleep 5
done

# Allow flip — granted user now denied
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/openfga -- curl -s \
  http://localhost:8080/stores/${STORE_ID}/check \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  \"authorization_model_id\": \"${MODEL_ID}\",
  \"tuple_key\": {
    \"user\": \"${GRANT_USER}\",
    \"relation\": \"viewer\",
    \"object\": \"${EXPECTED_TUPLE_OBJECT}\"
  }
}
EOF
" | tee -a ${EVIDENCE}
# expect {"allowed": false} — same user as Step 9.8 now denied
```

**Operator gate**: REVOKE outbox PROCESSED + originally-granted user now
denied (allow flipped to deny). This is the eventual-consistency proof.

#### Step 9.11 — Zero terminal `FAILED` rows for this evidence run

```bash
ssh halil@staging-sw "PGPASSWORD='<...>' psql -h 172.19.0.6 -U postgres \
  -d reports_db -c '
SELECT count(*) AS failed_count
FROM data_access.scope_outbox
WHERE status = '\''FAILED'\''
  AND created_at >= now() - INTERVAL '\''10 minutes'\'';
'" | tee -a ${EVIDENCE}
# expect failed_count: 0
```

If non-zero → check `last_error` column for diagnostic; this is a real
failure signal (operator alert candidate per PR-G `OUTBOX FAILED terminal`
log line).

```bash
echo "" >> ${EVIDENCE}
echo "Completed: $(date -Iseconds)" >> ${EVIDENCE}
echo "Verdict: $(if grep -q 'allowed.: true' ${EVIDENCE} && \
                  grep -q 'allowed.: false' ${EVIDENCE} && \
                  grep -q 'PROCESSED' ${EVIDENCE} && \
                  ! grep -q 'failed_count: [1-9]' ${EVIDENCE}; \
                  then echo PASS; else echo FAIL — review steps; fi)" >> ${EVIDENCE}
```

### D35 evidence handoff

After all 11 steps captured, commit the evidence file to gitops:

```bash
cd ~/Documents/platform-k8s-gitops
git checkout -b docs/d35-evidence-${RUN_ID}
cp ${EVIDENCE} docs/faz-21-3-evidence/
git add docs/faz-21-3-evidence/${RUN_ID}.md
git commit -m "docs(d35): first evidence ${RUN_ID} — V22+V23+PR-G eventual consistency PASS"
git push -u origin docs/d35-evidence-${RUN_ID}
gh pr create --title "docs(d35): first evidence ${RUN_ID}"
```

PR review confirms evidence completeness; merge anchors D35 first evidence in
repo history (per ADR-0009 D35 ownership: operator captures, agent reviews +
merges).

## Rollback

If any step fails or post-deploy regression appears:

```bash
# 1. Vault model_id revert
vault kv patch kv/platform/openfga model_id="<old_model_id_from_step_0>"

# 2. ESO force refresh (same 4 ExternalSecrets as Step 3)
for es in permission-service-secrets core-data-service-secrets \
          variant-service-secrets user-service-secrets; do
  ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
    annotate externalsecret \"$es\" force-sync=\"$(date +%s)\" --overwrite"
done

# 3. Service rollouts (same 4 services as Step 4)
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  rollout restart deploy/permission-service deploy/core-data-service \
  deploy/variant-service deploy/user-service"

# 4. New tuples are harmless on old model (model just doesn't know
#    organization/depot types — checks against them fail closed); leave
#    them OR run a cleanup script. Document.
```

**Operator gate**: post-rollback k6 baseline still passes; existing
project/company/variant flows unchanged.

## Out of scope (this runbook)

- Production prod cluster rollout — separate runbook, dual-clearance
  approval (operator + user).
- Frontend "Veri Erişimi" UI deploy — Faz 21.4, platform-web repo.
- ETL run for canonical 4-entity (PR #162 runbook handles that
  separately).

## References

- ADR-0008 (this repo)
- Backend OpenFGA model PR (platform-ssot or successor) — [TODO link]
- Vault `kv/platform/openfga`
- ExternalSecrets carrying `ERP_OPENFGA_MODEL_ID`:
  `permission-service-secrets`, `core-data-service-secrets`,
  `variant-service-secrets`, `user-service-secrets`
  (NOTE: `openfga-secrets` is the OpenFGA datastore credential stub,
  NOT the model_id carrier)
- `kustomize/base/apps/openfga/` deployment
- `tests/k6/zanzibar-load.js` baseline
- `decisions/topics/zanzibar-openfga.v1.json` (D-001..D-008 + C-008 FINAL)
