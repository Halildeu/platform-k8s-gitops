# Runbook — Faz 16.2.A Scope Anchor Load (D35-1 Prereq)

> **DR-6 of ADR-0010** (`docs/adr/0010-vault-credential-lifecycle-and-dr.md` §2.4).
> **Codex consensus**: thread `019dd2c9` (xhigh effort architecture).
> **D35 ladder**: produces D35-1 evidence (Scope Anchor Prereq).
> **NOT**: parametric multi-tenant ETL (= Faz 16.2.P, deferred indefinitely).

## Purpose

Load **minimum 1 real Workcube OUR_COMPANY row** from MSSQL into PostgreSQL `workcube_mikrolink.our_company` on staging-sw `reports_db`. Produce D35-1 evidence file. **Unblocks D35-2** (= "D35 first evidence" per ADR-0009 §"D35 Evidence Ladder").

**Anchor table correction** (V25 / PR-2 of OUR_COMPANY drift fix sequence): The D35-1 anchor is `workcube_mikrolink.OUR_COMPANY` (42 rows in Workcube source — AÇIK tenant boundary), NOT `workcube_mikrolink.COMPANY` (80,246 rows directory of all companies). V25 migration corrects validate_scope_ref + organization_company contract; this runbook loads the matching anchor.

**This is NOT Faz 16.2.P (parametric ETL)**. It is a strict subset:
- Only canonical schema `workcube_mikrolink` (NOT `workcube_mikrolink_<year>` parametric).
- Only `OUR_COMPANY` table (3 other anchor tables — `pro_projects`, `branch`, `department` — extend in follow-up only when D35-2/3 actually need them).
- Minimum row count: 1 (any of AÇIK org's 42 OUR companies in Workcube). All-42 load also acceptable per Codex `019dd34e` recommendation (small set; cleaner contract).
- **Not** product-data-loading; this is anchor-existence-only for the V25 tenant predicate trigger guard.

## Pre-conditions

- [ ] DR-1..DR-5 merged.
- [ ] staging-sw network restored (TCP/22, testai HTTP 200).
- [ ] Workcube MSSQL bridge alive (`platform-test-net` workcube-mssql-proxy-test container, 172.19.0.8:11433 — ETL workers reach via this proxy per Faz 19.MSSQL.F).
- [ ] etl_worker built (Dockerfile + pyproject in `scripts/migration/etl_worker/`).
- [ ] reports_db has `workcube_mikrolink` schema (V16 applied; verified during 2026-04-28 outbox preflight).
- [ ] Operator has Workcube source DB read credentials (NTLM ReadOnly intent — existing operator setup per Faz 19.MSSQL).

## Step 0 — Validate manifest + dry-run inspection

```bash
ssh halil@staging-sw "cd ~/platform-k8s-gitops/scripts/migration/etl_worker && \
  source .venv/bin/activate 2>/dev/null || python3 -m venv .venv && \
  source .venv/bin/activate && pip install -e . >/dev/null 2>&1
  echo '--- validate manifest:'
  etl-worker validate-manifest
  echo '--- inspect OUR_COMPANY (NTLM ReadOnly probe, no writes):'
  etl-worker inspect-source --tables OUR_COMPANY"
```

Expected:
- Manifest validation: `OK` for OUR_COMPANY entry.
- Inspect: prints column count + row count from MSSQL source. Row count > 0 (we'll load just 1 row, but source must have data).

## Step 1 — Dry-run on a single row

```bash
ssh halil@staging-sw "cd ~/platform-k8s-gitops/scripts/migration/etl_worker && \
  source .venv/bin/activate
  RUN_ID=\$(uuidgen)
  echo \"RUN_ID=\$RUN_ID\"
  etl-worker run --mode dry-run --run-id \"\$RUN_ID\" --tables OUR_COMPANY --limit 1 \
    | tee /tmp/dr6-dry-run-\${RUN_ID}.log"
```

Expected:
- Worker reads 1 OUR_COMPANY row from MSSQL
- Audit module records `mode=dry-run, status=SUCCESS, rows_extracted=1, rows_loaded=0`
- No PG writes (`workcube_mikrolink.our_company` row count unchanged)

Verify (separate command):
```bash
ssh halil@staging-sw 'PG_PWD=$(sudo grep "^REPORT_PG_PASSWORD=" /home/halil/platform/env/backend.env | cut -d= -f2)
docker exec -e PGPASSWORD="$PG_PWD" platform-pg-test psql -U platform -d reports_db -c \
  "SELECT count(*) FROM workcube_mikrolink.our_company;"'
```

Expected: 0.

## Step 2 — Live load (the actual D35-1 evidence event)

**Operator approval gate** — this is the first canlı Workcube row movement. Per ADR-0010 §2.5: user-approval required.

```bash
ssh halil@staging-sw "cd ~/platform-k8s-gitops/scripts/migration/etl_worker && \
  source .venv/bin/activate
  RUN_ID=\$(uuidgen)
  echo \"RUN_ID=\$RUN_ID\" | tee -a /tmp/dr6-live-run.log
  etl-worker run --mode initial --run-id \"\$RUN_ID\" --tables OUR_COMPANY --limit 1 \
    | tee -a /tmp/dr6-live-run.log"
```

Expected:
- Worker reads 1 OUR_COMPANY row from MSSQL
- Worker upserts into `workcube_mikrolink.our_company` (V17 lineage columns auto-populated)
- Audit row: `mode=initial, status=SUCCESS, rows_extracted=1, rows_loaded=1, rows_rejected=0`

## Step 3 — Reconcile (mandatory per Codex `019dd2c9` §2.4 + Faz 16 reconcile contract)

```bash
ssh halil@staging-sw "cd ~/platform-k8s-gitops/scripts/migration/etl_worker && \
  source .venv/bin/activate
  RUN_ID=<from Step 2>
  etl-worker reconcile --run-id \"\$RUN_ID\" --mode limited \
    | tee /tmp/dr6-reconcile-\${RUN_ID}.log"
```

Expected:
- VERDICT: MATCH
- checksum_pg == checksum_mssql for the 1 loaded row
- 1/1 sample hash match
- `docs/migration/reconcile-<run-id>.{md,json}` artifacts produced

## Step 4 — Verify scope anchor existence

```bash
ssh halil@staging-sw 'PG_PWD=$(sudo grep "^REPORT_PG_PASSWORD=" /home/halil/platform/env/backend.env | cut -d= -f2)
docker exec -e PGPASSWORD="$PG_PWD" platform-pg-test psql -U platform -d reports_db <<EOF
SELECT count(*) AS our_company_count FROM workcube_mikrolink.our_company;
SELECT source_pk, source_schema, source_table FROM workcube_mikrolink.our_company LIMIT 3;
SELECT row_to_json(t) FROM workcube_mikrolink.our_company t LIMIT 1;
EOF'
```

Expected:
- `our_company_count >= 1`
- `source_pk` non-empty (this is the value D35-2 uses as `SCOPE_REF` JSON element)
- `source_schema = workcube_mikrolink`
- `source_table = OUR_COMPANY`

## Step 5 — Re-seed `data_access.organization_company` (auto from V19 trigger or manual)

V19 had a CROSS JOIN seed step that produced 0 rows when `workcube_mikrolink.our_company` was empty. With Step 2-4 complete, re-run the seed:

```bash
ssh halil@staging-sw 'PG_PWD=$(sudo grep "^REPORT_PG_PASSWORD=" /home/halil/platform/env/backend.env | cut -d= -f2)
docker exec -e PGPASSWORD="$PG_PWD" platform-pg-test psql -U platform -d reports_db <<EOF
INSERT INTO data_access.organization_company (
    org_id, workcube_company_source_pk, source_schema, source_table
)
SELECT o.id, c.source_pk, '\''workcube_mikrolink'\'', '\''OUR_COMPANY'\''
FROM data_access.organization o
CROSS JOIN workcube_mikrolink.our_company c
WHERE o.name = '\''AÇIK'\'' AND c.source_schema = '\''workcube_mikrolink'\''
ON CONFLICT (org_id, workcube_company_source_pk) DO NOTHING;

SELECT * FROM data_access.organization_company WHERE org_id = (
    SELECT id FROM data_access.organization WHERE name = '\''AÇIK'\''
);
EOF'
```

Expected: at least 1 row in `data_access.organization_company` for AÇIK org with the loaded source_pk.

## Step 6 — Capture D35-1 evidence file

Use the format from `docs/d35-evidence-template.md` § "D35-1 — Scope Anchor Prereq":

```bash
RUN_ID=<from Step 2>
SOURCE_PK=<from Step 4>
EVIDENCE="docs/faz-21-3-evidence/$(date -u +%Y-%m-%d)-d35-1-scope-anchor-load-${RUN_ID:0:8}.md"
```

Required captures (per template):
- Faz 16.2.A `etl_worker` runbook executed (this runbook reference)
- `workcube_mikrolink.our_company` row count >= 1 with at least 1 real source_pk shown
- `migration_audit.migration_runs` row with mode + status + counts
- Reconcile evidence (rejected_rows = 0)
- `data_access.organization_company` mapping for AÇIK org → real source_pk

Final verdict block: PASS if all 5 captures present + reconcile MATCH.

Commit + open PR with the evidence file. PR description includes the D35 ladder declaration block per `docs/d35-evidence-template.md`.

## Step 7 — Hand off to DR-7

D35-1 evidence committed → DR-7 (next PR) runs the canonical 11-step sequence (`docs/openfga-multi-org-rollout.md` Step 9.1-9.11) with the `SOURCE_PK` from Step 4 as the SCOPE_REF JSON element.

DR-7's authority: requires user-approval per ADR-0010 §2.5 (D35 semantic — first canlı evidence run).

## Rollback

If anything goes wrong in Step 2-3 (live load fails, reconcile MISMATCH):

```bash
ssh halil@staging-sw 'PG_PWD=$(sudo grep "^REPORT_PG_PASSWORD=" /home/halil/platform/env/backend.env | cut -d= -f2)
RUN_ID=<from failing step>

docker exec -e PGPASSWORD="$PG_PWD" platform-pg-test psql -U postgres -d reports_db <<EOF
-- Identify rows from this run via lineage
SELECT count(*) FROM workcube_mikrolink.our_company
  WHERE (source_schema, source_table) = ('\''workcube_mikrolink'\'', '\''COMPANY'\'')
    AND source_pk IN (
      SELECT source_pk FROM migration_audit.migration_table_state
      WHERE run_id = '\''$RUN_ID'\''
    );

-- Optional: delete via run-id reference (audit-trail-preserved)
-- (Operator decides whether to drop or keep failed-run rows.)

-- Mark migration_audit.migration_runs row failed
UPDATE migration_audit.migration_runs
   SET status = '\''ABORTED'\'',
       error_summary = '\''DR-6 reconcile MISMATCH or live load failure (operator-driven rollback)'\''
 WHERE run_id = '\''$RUN_ID'\'';
EOF'
```

## Out of scope (explicitly)

- **`pro_projects`, `branch`, `department` anchor table loads**: extend only when D35-2 or D35-3 evidence requires those scope_kinds. Do not preemptively load.
- **Faz 16.2.P parametric ETL**: defer remains in effect (PLAN.md). This is a strict subset.
- **D35-2 first canlı evidence run**: that's DR-7.
- **mfe-access UI surface update for tupleSyncStatus/outboxId/processedAt**: separate PR, downstream of DR-7.
- **Production COMPANY load**: prod has no Faz 16.2.A equivalent yet; user-approval gated separately.

## D35 ladder declaration (this runbook drives D35-1)

This runbook (when run live) **advances D35-1**.
- Evidence file path: `docs/faz-21-3-evidence/<date>-d35-1-scope-anchor-load-<run-id>.md`
- Tier marker in evidence: D35-1
- DR-7 consumes the `source_pk` produced here.

## References

- ADR-0010 §2.4 (Faz 16.2.A vs 16.2.P boundary)
- ADR-0009 § "D35 Evidence Ladder" (D35-1 capture requirements)
- `docs/d35-evidence-template.md` (per-tier capture lists, evidence format)
- Faz 16 etl_worker `scripts/migration/etl_worker/` (existing infrastructure)
- PLAN.md Faz 16.2.P deferral (preserved)
- Codex thread `019dd2c9` (this runbook's strategic foundation)
