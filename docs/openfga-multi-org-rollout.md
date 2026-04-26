# OpenFGA Multi-Org Model Rollout Runbook (Faz 21.3)

> **Status**: PROPOSED — manifest-merged, **not yet executed**.
> **Authority**: ADR-0008 (this repo) + backend repo OpenFGA model PR.
> Each step is **operator-gated**; agents do not execute these without
> explicit user approval per step.

## Pre-conditions

- [ ] Backend repo PR (platform-ssot or successor): `openfga-authorization-model.fga`
      adds `organization` + `depot` types per ADR-0008. Tuple writer +
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

```bash
# Backend ConfigMap:
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  set env deploy/permission-service MULTI_ORG_TUPLE_SYNC_ENABLED=true"
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  rollout restart deploy/permission-service"
```

Backend now writes tuples on `data_access.scope INSERT` automatically.

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
