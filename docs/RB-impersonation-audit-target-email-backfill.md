# RB — Impersonation Audit `target_email` Backfill

> Codex `019e27bf` fresh-context audit follow-up. Operator runbook.
>
> **Scope**: `permission_db.public.impersonation_audit_events` (or whichever schema the permission-service audit writer points to) rows with `event_type IN ('IMPERSONATION_BLOCKED', 'IMPERSONATION_FAILED')` and `target_email IS NULL` that pre-date the audit invariant code fixes (PR #165 / #181 / #198 chain).
>
> **Why this runbook exists**: Until PR #198 (audit invariant global fix) MERGED, 9+ audit branches in `ImpersonationController` routed `request.targetEmail()` straight to the audit row. If the operator omitted `targetEmail` from the start-session body, the row landed with `target_email = NULL`. The runtime fix prevents new NULL rows; historical rows still need a one-off backfill.

---

## Trigger

Run this runbook when:

- Compliance/audit dashboard query reports impersonation audit rows with `target_email IS NULL` after PR #198 MERGED (`2026-05-14` onwards on test cluster).
- Operator wants a clean audit history before exporting / GDPR / SOC 2 review.

**Do NOT run** until PR #198 is deployed to all clusters (test + prod). Otherwise new rows will keep landing as NULL.

---

## Pre-flight

```bash
# 1) Verify PR #198 lives in the running auth-service image digest.
kubectl --context k3d-test -n platform-test get pod -l app=auth-service \
  -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'
# Expect a digest matching the PR #198 build artifact.

# 2) Connect to permission-service PG (the schema that owns the audit table).
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test exec deploy/postgres-permission -- env | grep -E '^POSTGRES_(DB|USER)='"

# 3) Audit row count BEFORE backfill (baseline for verify step).
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test exec deploy/postgres-permission -- \
  psql -U \$POSTGRES_USER -d \$POSTGRES_DB -c \"\
    SELECT event_type, COUNT(*) FROM public.impersonation_audit_events \
    WHERE target_email IS NULL \
    GROUP BY event_type;\""
```

---

## Step 1: Identify candidate rows

```sql
-- Rows where target_email is NULL but a target_user_id exists.
-- These are recoverable via user_service.users.email lookup.
SELECT
  id,
  event_type,
  error_code,
  target_user_id,
  target_subject,
  reason,
  created_at
FROM public.impersonation_audit_events
WHERE target_email IS NULL
  AND target_user_id IS NOT NULL
  AND event_type IN ('IMPERSONATION_BLOCKED', 'IMPERSONATION_FAILED')
ORDER BY created_at DESC
LIMIT 100;
```

Take note of the date range covered and the distinct `error_code` values — this will go into the audit trail PR body.

---

## Step 2: Cross-cluster lookup (user_service.users)

The audit DB lives in permission-service PG; the source-of-truth email lives in user-service PG. The two are separate Hibernate datasources. The cleanest path is a **CSV-driven backfill** rather than a cross-DB JOIN (which would require a foreign-data-wrapper that is not configured).

```bash
# 2a) Export candidate target_user_ids to a CSV.
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test exec deploy/postgres-permission -- \
  psql -U \$POSTGRES_USER -d \$POSTGRES_DB -t -A -F ',' -c \"\
    SELECT id, target_user_id FROM public.impersonation_audit_events \
    WHERE target_email IS NULL AND target_user_id IS NOT NULL \
      AND event_type IN ('IMPERSONATION_BLOCKED', 'IMPERSONATION_FAILED');\"" \
  > /tmp/audit-rows-needing-email.csv

# 2b) Pull email per target_user_id from user-service PG.
awk -F',' '{print $2}' /tmp/audit-rows-needing-email.csv | sort -u > /tmp/target-user-ids.txt
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test exec deploy/postgres-user -- \
  psql -U \$POSTGRES_USER -d \$POSTGRES_DB -t -A -F ',' -c \"\
    SELECT id, email FROM public.users \
    WHERE id = ANY(STRING_TO_ARRAY('\$(paste -sd ',' /tmp/target-user-ids.txt)', ',')::bigint[]);\"" \
  > /tmp/user-id-to-email.csv
```

The two CSV files now hold `audit_row_id,target_user_id` (left) and `user_id,email` (right). Join them with `awk` / `python` and produce a third CSV `audit_row_id,email`:

```bash
python3 - <<'PY' > /tmp/audit-backfill-pairs.csv
import csv
audit = {}
with open('/tmp/audit-rows-needing-email.csv') as f:
    for row in csv.reader(f):
        if len(row) >= 2:
            audit[row[1]] = row[0]  # target_user_id -> audit_row_id
emails = {}
with open('/tmp/user-id-to-email.csv') as f:
    for row in csv.reader(f):
        if len(row) >= 2:
            emails[row[0]] = row[1]
for uid, audit_id in audit.items():
    if uid in emails:
        print(f"{audit_id},{emails[uid]}")
PY
wc -l /tmp/audit-backfill-pairs.csv
```

---

## Step 3: Apply backfill (transactional, dry-run first)

**Dry-run first**: never run the UPDATE without seeing the affected count.

```bash
# 3a) Dry-run: count what would change.
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test exec -i deploy/postgres-permission -- \
  psql -U \$POSTGRES_USER -d \$POSTGRES_DB" <<'SQL'
BEGIN;
CREATE TEMP TABLE audit_backfill (audit_id BIGINT, email TEXT);
\copy audit_backfill FROM '/tmp/audit-backfill-pairs.csv' WITH (FORMAT csv);
SELECT COUNT(*) AS to_update FROM public.impersonation_audit_events e
  JOIN audit_backfill b ON b.audit_id = e.id
  WHERE e.target_email IS NULL;
ROLLBACK;
SQL
```

Inspect the `to_update` count. If it matches expectations, run the real update:

```bash
# 3b) Real run.
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test exec -i deploy/postgres-permission -- \
  psql -U \$POSTGRES_USER -d \$POSTGRES_DB" <<'SQL'
BEGIN;
CREATE TEMP TABLE audit_backfill (audit_id BIGINT, email TEXT);
\copy audit_backfill FROM '/tmp/audit-backfill-pairs.csv' WITH (FORMAT csv);
UPDATE public.impersonation_audit_events e
   SET target_email = b.email,
       updated_at = NOW()
  FROM audit_backfill b
 WHERE e.id = b.audit_id
   AND e.target_email IS NULL;
SELECT COUNT(*) AS updated FROM public.impersonation_audit_events e
  JOIN audit_backfill b ON b.audit_id = e.id
  WHERE e.target_email = b.email;
COMMIT;
SQL
```

---

## Step 4: Verify

```sql
-- Count of remaining NULL rows AFTER backfill (should drop by the
-- number of rows the CSV held).
SELECT event_type, COUNT(*)
FROM public.impersonation_audit_events
WHERE target_email IS NULL
GROUP BY event_type;
```

A residual count is acceptable for:
- Rows where `target_user_id IS NULL` (pre-resolution branches: `NESTED_IMPERSONATION_FORBIDDEN`, `ADMIN_IDENTITY_MISSING`) — these have no resolvable address and PR #198 documents them as the intentional gap.
- Rows where the target user has been deleted from `user_service.users` (rare; investigate case by case).

---

## Step 5: Same for prod (when D30 cutover lands)

The same SQL sequence runs against `k3d-prod` after prod cutover, with the obvious context swap:

```bash
ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod exec deploy/postgres-permission ..."
```

**Hold the prod backfill until PR #198 image digest is pinned in prod overlay AND deployed**. Otherwise new NULL rows will keep accumulating after the backfill.

---

## Rollback

The backfill is non-destructive (`target_email` was NULL before, it becomes the resolved email). To roll back:

```sql
-- Restore NULL on the rows the CSV held. The audit_backfill temp
-- table no longer exists after COMMIT, so re-create from CSV.
BEGIN;
CREATE TEMP TABLE audit_backfill (audit_id BIGINT, email TEXT);
\copy audit_backfill FROM '/tmp/audit-backfill-pairs.csv' WITH (FORMAT csv);
UPDATE public.impersonation_audit_events e
   SET target_email = NULL,
       updated_at = NOW()
  FROM audit_backfill b
 WHERE e.id = b.audit_id
   AND e.target_email = b.email;
COMMIT;
```

Note: this restores the original NULL state for backfilled rows but does NOT touch rows that never had a NULL target_email.

---

## Referenced PRs

- `platform-backend#165` — Step 1b / 1f audit `target_email` fix (SELF pre-resolution + UNRESOLVABLE)
- `platform-backend#181` — 409 + SESSION_PERSIST_FAILED audit fix (BUG #1 catch by Codex async review)
- `platform-backend#198` — Audit invariant global fix (6 post-resolution branches + helper overload)

## Boundary classification (operator action)

- **state-mutation (test cluster)** — Step 3 UPDATE on permission_db audit table
- **state-mutation (production)** — Step 5 same on k3d-prod after D30 cutover

Operator approval required per ADR-0011 §2.5 before running Step 3 / 5 on respective clusters.
