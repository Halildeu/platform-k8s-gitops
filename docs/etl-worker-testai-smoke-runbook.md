# etl-worker testai live smoke runbook — Adım 12 PR-4

> **Status**: skeleton. Filled in as the PR-4 live-smoke gate is
> executed. PR-3c (kustomize/base/apps/etl-worker manifest migration)
> ships this skeleton so the Job annotation
> `platform.acik.com/runbook` resolves to a real document; the
> live-smoke procedure proper lands as PR-4 source + post-impl
> evidence capture.

Operator-gated end-to-end smoke against the `testai` cluster
(`k3d-test`, namespace `platform-test`). Prereq chain:

1. **PR-3a / PR-3b / PR-3c merged**. Digest pinned in
   `kustomize/base/apps/etl-worker/job.yaml`:
   `ghcr.io/halildeu/platform-backend-etl-worker@sha256:1f9c93da74354f92c4358914994066efd363ba97ef1a0e1ef39aabca3a9c858f`.
2. **`ghcr-pull` Secret present** in `platform-test` (Codex
   `019e2d27` PR-3c REVISE P1 #1). Verify:
   `kubectl --context k3d-test -n platform-test get secret ghcr-pull`.
3. **DBA migration applied**: `etl_snapshot_runs` table created
   in `reports_db` per the DDL in
   `platform-backend/etl-worker/etl_worker/pg_writer.py` docstring.
4. **Vault keys seeded**:
   - `kv/platform/etl-worker-reports-db.{username,password}`
   - `kv/platform/schema-service-internal.api_key`
5. **schema-service emits the Adım 12 target contract** —
   `contract_version`, `allowlist_name`, `allowlist_version`,
   `tables` LIST (not map), column `type` (not `dataType`). If the
   contract is still the legacy shape the run is expected to fail
   closed with `SchemaServiceMalformedResponse` →
   `EX_SOFTWARE=70`.

## Apply sequence

```bash
# 1. SA + ConfigMap + ExternalSecrets (these are safe to ArgoCD-
#    reconcile; Job is operator-applied only).
kubectl --context k3d-test -n platform-test apply -f kustomize/base/apps/etl-worker/serviceaccount.yaml
kubectl --context k3d-test -n platform-test apply -f kustomize/base/apps/etl-worker/configmap.yaml
kubectl --context k3d-test -n platform-test apply -f kustomize/base/apps/etl-worker/ops/externalsecret.yaml

# 2. Wait for ESO to sync the two new secrets (~refreshInterval).
kubectl --context k3d-test -n platform-test wait \
  externalsecret/etl-worker-reports-db-secrets \
  externalsecret/etl-worker-schema-service-secrets \
  --for=condition=Ready --timeout=120s

# 3. Verify the synced Secret key names (do NOT print values).
kubectl --context k3d-test -n platform-test get secret etl-worker-reports-db-secrets -o jsonpath='{.data}' | jq 'keys'
kubectl --context k3d-test -n platform-test get secret etl-worker-schema-service-secrets -o jsonpath='{.data}' | jq 'keys'

# 4. Substitute a fresh UUID for PLACEHOLDER_RUN_ID, then apply.
RUN_ID=$(uuidgen | tr 'A-Z' 'a-z')
sed "s/PLACEHOLDER_RUN_ID/$RUN_ID/g" kustomize/base/apps/etl-worker/job.yaml | \
  kubectl --context k3d-test -n platform-test apply -f -

# 5. Wait for Job completion (activeDeadlineSeconds=3600).
kubectl --context k3d-test -n platform-test wait \
  job/etl-worker-$RUN_ID --for=condition=Complete --timeout=3700s

# 6. Capture evidence.
kubectl --context k3d-test -n platform-test logs job/etl-worker-$RUN_ID > /tmp/etl-worker-$RUN_ID.log
kubectl --context k3d-test -n platform-test get job etl-worker-$RUN_ID -o jsonpath='{.spec.template.spec.containers[0].image}' # must equal the digest above
```

## Acceptance gates

- Job `Complete` condition `True`
- Logs contain no `Traceback`
- Stdout summary JSON includes `run_id`, `snapshot_signature`,
  `attempts`, `contract_version`, `table_count`, `column_count`
- Pod `imageID` digest equals the pinned digest in `job.yaml`
- `reports_db` query confirms a row in `etl_snapshot_runs` with
  the same `(snapshot_signature, contract_version)` upserted
- Old `etl-worker-pg-secrets` / `etl-worker-mssql-secrets` (from
  Faz 16) cleaned up: `kubectl ... delete secret ... --ignore-not-found`

## Failure rollback

- `kubectl --context k3d-test -n platform-test delete job/etl-worker-$RUN_ID`
- Inspect logs at `/tmp/etl-worker-$RUN_ID.log` (saved above)
- Map exit codes (sysexits-style, PR-3a contract):
  - `64` — config/CLI usage error (fix invocation, do NOT retry)
  - `70` — malformed response / DB schema mismatch / checkpoint
    corruption (DBA / contract owner action)
  - `75` — transient infra (re-queue allowed once root cause is
    triaged)
  - `76` — `contract_version` mismatch (operator reconcile with
    `SCHEMA_SERVICE_CONTRACT_VERSIONS`)

## Old-state cleanup (post-acceptance)

After a green run + evidence captured:

```bash
kubectl --context k3d-test -n platform-test delete \
  secret/etl-worker-pg-secrets \
  secret/etl-worker-mssql-secrets \
  --ignore-not-found
kubectl --context k3d-test -n platform-test delete \
  externalsecret.external-secrets.io/etl-worker-pg-secrets \
  externalsecret.external-secrets.io/etl-worker-mssql-secrets \
  --ignore-not-found
```

> **Source-of-truth note**: the Faz 16
> `docs/etl-worker-staging-dry-run.md` runbook is **deprecated**
> after PR-3c — it still describes the MSSQL→PG direct ETL model
> that the schema-service contract consumer replaced. Do not
> follow it after PR-3c merges.
