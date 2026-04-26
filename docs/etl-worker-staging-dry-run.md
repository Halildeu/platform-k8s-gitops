# ETL Worker — Staging-sw K8s Dry-Run Runbook (Faz 16 Day 8 prep)

**Status**: PR-merged manifest, no auto-apply. Each step below requires
explicit operator confirmation — agents do not run these unless the user
has typed approval for that specific step.

**Authority**:
- Codex thread `019dc88c` iter-4 AGREE (Yol B + user-gated K8s prep).
- D29 discipline: Up ≠ Functional ≠ Behavior. Local Mac dev-pg smoke
  delivered the **Functional** gate (commit `b1f184d`,
  `docs/migration/reconcile-20260426-1b4f8397-smoke-dev-pg.{md,json}`,
  VERDICT MATCH). This runbook is for the **Behavior** gate on the
  staging-sw test cluster.
- Hard rule (kural #9): every step must produce a paste-able evidence
  artifact (kubectl output, audit row, reconcile artifact). No "ran it,
  trust me."

---

## 0. Pre-flight (no cluster touch)

Operator runs locally. **D30 immutable artifact rule**: the manifest
pins `image` by digest (`@sha256:...`), not by tag. Tag is convenience
for humans; digest is the runtime contract.

```bash
SHA=$(git rev-parse --short=12 HEAD)
IMAGE_TAG="ghcr.io/halildeu/platform/etl-worker:sha-${SHA}"

cd scripts/migration/etl_worker
docker build -t "${IMAGE_TAG}" .
docker push "${IMAGE_TAG}"

# Capture the canonical digest of what was just pushed.
DIGEST=$(docker buildx imagetools inspect "${IMAGE_TAG}" \
    --format '{{json .Manifest.Digest}}' | tr -d '"')

# Final pinned reference — substitute this into job.yaml in Step 4.
IMAGE_REF="ghcr.io/halildeu/platform/etl-worker@${DIGEST}"
echo "IMAGE_REF=${IMAGE_REF}"
```

Operator gate: paste `IMAGE_REF`. It must start with `ghcr.io/...@sha256:`
and the digest must be 64 hex chars.

---

## 1. PG schema apply (idempotent, additive)

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/auth-service -- bash -c 'echo HELLO from cluster shell'"
# (Sanity: cluster reachable from operator host.)

# Apply V16 + V17 to the test PG.
# Replace <PG_HOST> + <PG_PASSWORD> with operator-known values.
ssh halil@staging-sw "PGPASSWORD='<PG_PASSWORD>' psql \
  -h 172.19.0.6 -U postgres -d reports_db \
  -f /tmp/V16__reports.sql"
ssh halil@staging-sw "PGPASSWORD='<PG_PASSWORD>' psql \
  -h 172.19.0.6 -U postgres -d reports_db \
  -f /tmp/V17__etl_lineage_columns.sql"
```

Expected: `COMMIT` for both, `NOTICE: ... already exists, skipping` lines
acceptable for re-runs (V17 is fully `IF NOT EXISTS`-guarded).

Operator gate: paste the COMMIT line + verify with
`\d workcube_mikrolink.company` showing `source_table`, `source_pk`, and
`UNIQUE INDEX idx_company_lineage_unique`.

---

## 2. Secrets (Vault → ESO; no plaintext touch)

If `kv/platform/etl-worker-pg` does not exist yet, operator creates it
inside Vault UI/CLI with read-only DB user credentials. Agents do NOT
provision Vault secrets.

```bash
# Apply ExternalSecrets after Vault has the values:
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test apply \
  -k /tmp/etl-worker-ops"

# Wait for sync:
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get externalsecret etl-worker-pg-secrets etl-worker-mssql-secrets \
  -o wide"
```

Expected: STATUS `SecretSynced` for both. Operator gate: paste the
`get externalsecret` table.

---

## 3. Apply config + ServiceAccount

```bash
# These are non-destructive: ConfigMap + ServiceAccount only.
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test apply \
  -f /tmp/etl-worker/configmap.yaml \
  -f /tmp/etl-worker/serviceaccount.yaml"
```

Operator gate: confirm `kubectl get cm etl-worker-config sa etl-worker -o name`
returns both.

---

## 4. Job substitution + apply (PHASE A — boot smoke)

```bash
RUN_ID=$(uuidgen | tr 'A-Z' 'a-z')
SHORT="${RUN_ID:0:8}"
# IMAGE_REF was captured in Step 0 (must be a digest pin: repo@sha256:...).

# Substitute placeholders. The base manifest carries
# `etl-worker-PLACEHOLDER_RUN_ID` and image
# `ghcr.io/halildeu/platform/etl-worker@sha256:PLACEHOLDER_DIGEST`;
# the runbook replaces both intentionally — kustomize cannot rename a
# Job per run, and digest substitution is what enforces D30.
sed \
  -e "s/PLACEHOLDER_RUN_ID/${SHORT}/g" \
  -e "s|ghcr.io/halildeu/platform/etl-worker@sha256:PLACEHOLDER_DIGEST|${IMAGE_REF}|g" \
  /tmp/etl-worker/job.yaml > /tmp/etl-worker-job-${SHORT}.yaml

# Sanity: the substituted file must contain a digest reference.
grep -q "ghcr.io/halildeu/platform/etl-worker@sha256:[a-f0-9]\{64\}" \
  /tmp/etl-worker-job-${SHORT}.yaml || {
    echo "FAIL: digest substitution did not land; refusing to apply"; exit 2; }

ssh halil@staging-sw "kubectl --context k3d-test -n platform-test apply \
  -f /tmp/etl-worker-job-${SHORT}.yaml"

# This first run uses default args (`validate-manifest`) — no PG writes,
# proves boot + manifest load.
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  wait --for=condition=complete --timeout=120s \
  job/etl-worker-${SHORT}"

# D30 verification gate: pod's running imageID MUST equal IMAGE_REF.
POD_IMG=$(ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get pod -l job-name=etl-worker-${SHORT} \
  -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'")
echo "running imageID: ${POD_IMG}"
echo "expected ref   : ${IMAGE_REF}"
# imageID typically prefixed with "ghcr.io/.../etl-worker@sha256:..."; the
# digest portion must match the IMAGE_REF digest exactly.

ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  logs job/etl-worker-${SHORT} --tail=50"
```

Expected log line: `✓ Manifest valid (N tables, syntax OK)`.

Operator gate (D29 + D30): paste tail-50 logs + `kubectl get job` showing
`COMPLETIONS 1/1` + the imageID/IMAGE_REF digest match. If digests
differ, STOP — likely tag drift on the registry. Do not proceed to
Phase B until imageID matches.

---

## 5. PHASE B — actual dry-run with row movement

```bash
# Edit /tmp/etl-worker-job-<SHORT>.yaml (or create a new one) — replace
# the `args:` block with:
#
#   args:
#     - "run"
#     - "--mode=dry-run"
#     - "--run-id"
#     - "<RUN_ID>"
#     - "--tables"
#     - "COMPANY,BRANCH"
#     - "--limit"
#     - "1000"
#
# Bump the metadata.name to `etl-worker-${SHORT}-dryrun` so it doesn't
# collide with the Phase A Job. Then apply:

ssh halil@staging-sw "kubectl --context k3d-test -n platform-test apply \
  -f /tmp/etl-worker-job-${SHORT}-dryrun.yaml"

ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  wait --for=condition=complete --timeout=600s \
  job/etl-worker-${SHORT}-dryrun"

ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  logs job/etl-worker-${SHORT}-dryrun --tail=200" \
  | tee /tmp/etl-worker-${SHORT}-dryrun.log
```

Operator gate: log tail must include `run.outcome=SUCCESS`.

---

## 6. Audit verification (Behavior gate evidence)

```bash
# Run-row + per-table state + reject summary on the live PG.
ssh halil@staging-sw "PGPASSWORD='<PG_PASSWORD>' psql \
  -h 172.19.0.6 -U postgres -d reports_db <<EOF
SELECT run_id, mode, status, source_database, started_at, completed_at, error_summary
FROM migration_audit.migration_runs WHERE run_id = '<RUN_ID>';

SELECT table_name, status, rows_extracted, rows_loaded, rows_rejected, last_pk
FROM migration_audit.migration_table_state WHERE run_id = '<RUN_ID>'
ORDER BY started_at;

SELECT count(*) AS reject_total
FROM migration_audit.migration_rejects WHERE run_id = '<RUN_ID>';

SELECT count(*) AS canonical_company,
       count(DISTINCT source_pk) AS distinct_pks
FROM workcube_mikrolink.company
WHERE source_schema = 'workcube_mikrolink';
EOF"
```

Operator gate: paste the four query results. Acceptable for dry-run:
- `migration_runs.status = SUCCESS`
- `migration_table_state.status = VALIDATED` for both tables
- `rows_loaded > 0` for at least one table (live MSSQL non-empty)
- `reject_total = 0` (live data shape matches V16 NOT NULL contract)

---

## 7. Reconcile artifact (Behavior gate evidence #2)

```bash
# Re-apply the Job manifest with reconcile args:
#   args:
#     - "reconcile"
#     - "--run-id"
#     - "<RUN_ID>"
#     - "--scope"
#     - "limited"
#     - "--limit"
#     - "1000"
#     - "--output-dir"
#     - "/tmp/reconcile-out"
#
# Rename to etl-worker-${SHORT}-reconcile.

ssh halil@staging-sw "kubectl --context k3d-test -n platform-test cp \
  etl-worker-${SHORT}-reconcile-<podsuffix>:/tmp/reconcile-out \
  /tmp/reconcile-${SHORT}/"

# Commit artifact to repo:
mv /tmp/reconcile-${SHORT}/reconcile-*.md \
   docs/migration/
mv /tmp/reconcile-${SHORT}/reconcile-*.json \
   docs/migration/
git add docs/migration/reconcile-*.{md,json}
git commit -m "evidence(faz-16): staging-sw dry-run reconcile artifact (run ${SHORT})"
```

Operator gate: open the markdown — `overall verdict: MATCH`,
`row_count_pg == row_count_mssql`, sample diff all match.

---

## 8. Cleanup

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  delete job etl-worker-${SHORT} \
  etl-worker-${SHORT}-dryrun \
  etl-worker-${SHORT}-reconcile"
# ConfigMap + ServiceAccount + ExternalSecrets stay; reusable for next run.
```

---

## Failure recovery

| Symptom | Cause | Action |
|---|---|---|
| `LOCK_CONTENDED` exit 3 | another worker holds same run_id | Use a new UUID; check for stale Job |
| `SchemaContractError ... Apply V17` | V17 not yet applied | Step 1 |
| `BAD_GATEWAY` from PG | postgres Service down | Investigate platform `postgres` Endpoint |
| `MSSQL connection error` | Vault sync failed | Check ExternalSecret status |
| `threshold breach mode=initial` | live data has unexpected nulls | Inspect `etl-worker rejects --run-id` |
| Phase B `validate-manifest` succeeds but `run` fails immediately | image tag mismatch | confirm `kubectl get pod -o jsonpath='{...imageID}'` matches the digest |

---

## Out of scope (this runbook)

- Production cluster apply (k3d-prod). This runbook covers k3d-test only.
- Faz 16.2.P parametric tables. Deferred — see `PLAN.md`.
- Final-delta cutover. A separate runbook gates the actual MSSQL→PG
  switchover; final-delta strict mode aborts on first reject.
