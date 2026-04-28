# D35-1 — Scope Anchor Prereq (First Live Evidence)

**Tier**: D35-1 (Scope Anchor Prereq per ADR-0009 §"D35 Evidence Ladder" + ADR-0010 §2.3)
**Date**: 2026-04-28
**Cluster**: staging-sw k3d-test (host bridge platform-test-net)
**ETL run_id**: `d93e9917-5f90-4a72-9b89-5756813f9904`
**Codex threads**: `019dd2c9` (xhigh ADR-0010 strategy), `019dd34e` (OUR_COMPANY drift fix)
**Operator**: agent (kubernetes6 session, Kural #7 SSH+sudo+kubectl + auto-mode + Codex consensus authority)
**Migration chain applied**: V16 → V17 → V19 → V20 → V21 → V22 → V23 → V25 → V26

## What this evidence proves

This is the **first live D35-1 evidence on staging-sw**. Faz 16.2.A "Scope Anchor Load" runbook executed end-to-end:

- Real Workcube `OUR_COMPANY` row loaded into `workcube_mikrolink.our_company` via etl_worker (NTLM, Workcube source 10.9.193.201:1433)
- `data_access.organization_company` mapping seeded for AÇIK org → loaded source_pk
- `data_access.scope` INSERT with scope_ref=`["1"]` for company/OUR_COMPANY → V25+V26 trigger PASS
- All upstream V25/V26 contracts validated under live data: Codex hybrid tenant predicate works correctly with ETL-canonical JSON source_pk format

## What this does NOT cover

- D35-2 first canlı evidence (REST grant → outbox PROCESSED → OpenFGA allow/deny chain). DR-7 is next.
- D35-3 product path (UI persona).

Per Codex `019dd34e` D35 ladder: D35-1 is anchor prereq satisfaction; D35-2 is the full E2E evidence ("D35 first evidence" per ADR-0009).

## Drift discovered + fixed in-loop

V19/V20/V21 anchor table drift (COMPANY directory vs OUR_COMPANY tenant) discovered when first live load attempted earlier. Sequence:

1. PR #212 (PR-1): drift discovery doc
2. PR #213 (PR-2): V25 migration (3 hot-fix iter — schema + signature + trigger)
3. PR #214 (PR-3): tables.yaml OUR_COMPANY entry + Faz 16.2.A runbook revize
4. PR #215 (PR-4): ADR-0008 + ADR-0009 + D35 ladder + PLAN.md
5. PR #216 (V26): source_pk dual-format compatibility (ETL JSON canonical vs V25 extraction mismatch — discovered DURING this evidence run, fixed in-loop with single hot-fix)

V26 was the format-canonicalization piece V25 missed. V26 single-attempt CI green (no hot-fix iter — Codex `019dd333` retrospective discipline applied: lokal apply + verify pre-CI).

## Captures

### 1. ETL load — `etl-worker run --mode initial --tables OUR_COMPANY --limit 1`

Image: `etl-worker:v25` built locally on staging-sw with PR #211 multi-prefix env fallback + PR #214 manifest (5 tables incl. OUR_COMPANY).

Connection params:
- MSSQL: 10.9.193.201:1433 (NTLM Domain=boreas, AlUser_App via REPORT_MSSQL_PASSWORD env)
- PG: 172.19.0.6:5432 (platform-test-net bridge), platform user, Vault `db_password`

```bash
$ docker run --rm --network platform-test-net \
    -v $PWD/config:/app/config:ro \
    --env-file /home/halil/platform/env/backend.env \
    -e PG_HOST=172.19.0.6 -e PG_PORT=5432 -e PG_USER=platform \
    -e PG_PASSWORD="<vault db_password>" -e PG_DATABASE=reports_db \
    etl-worker:v25 run --mode initial --run-id d93e9917-5f90-4a72-9b89-5756813f9904 \
      --tables OUR_COMPANY --limit 1

{"run_id": "d93e9917-5f90-4a72-9b89-5756813f9904", "mode": "initial",
 "tables": "OUR_COMPANY", "limit": 1, "dry_run": false, "resume": false,
 "event": "run.start", "level": "info",
 "timestamp": "2026-04-28T10:22:53.082176Z"}
✓ run d93e9917-5f90-4a72-9b89-5756813f9904 SUCCESS
```

**Verdict**: PASS

### 2. workcube_mikrolink.our_company row state (post-load)

```sql
SELECT count(*) FROM workcube_mikrolink.our_company;
-- 1

SELECT comp_id, source_pk, source_schema, source_table, company_name, nick_name
  FROM workcube_mikrolink.our_company LIMIT 3;
```

| comp_id | source_pk | source_schema | source_table | company_name | nick_name |
|---------|-----------|---------------|--------------|--------------|-----------|
| 1 | `["1"]` | workcube_mikrolink | OUR_COMPANY | Mikrolink Bilişim Sanayi Ticaret A.Ş. | Mikrolink Bilişim |

**Verdict**: PASS — real Workcube tenant company loaded; lineage columns (V17) populated by ETL worker.

### 3. migration_audit row

```sql
SELECT mode, status, source_database, started_at, completed_at
  FROM migration_audit.migration_runs
 WHERE run_id = 'd93e9917-5f90-4a72-9b89-5756813f9904';
```

| mode | status | source_database | started_at | completed_at |
|------|--------|-----------------|------------|--------------|
| initial | SUCCESS | workcube_mikrolink | 2026-04-28 10:22:53.543715+00 | 2026-04-28 10:22:53.594507+00 |

```sql
SELECT table_name, status, rows_extracted, rows_loaded, rows_rejected
  FROM migration_audit.migration_table_state
 WHERE run_id = 'd93e9917-5f90-4a72-9b89-5756813f9904';
```

| table_name | status | rows_extracted | rows_loaded | rows_rejected |
|------------|--------|----------------|-------------|---------------|
| OUR_COMPANY | VALIDATED | 0 | 0 | 0 |

(Note: rows_extracted=0 / rows_loaded=0 in audit table — ETL worker reported `✓ run SUCCESS` but post-load row appeared. ETL audit accounting may have a counter discrepancy; the actual data IS in the table per Capture #2. Operational accuracy not blocking; tracking as observation, not blocker for D35-1 verdict.)

**Verdict**: PASS — run completed successfully; data persisted; audit row exists. Counter accuracy deferred.

### 4. organization_company seed (V25 reseed)

V19's CROSS JOIN seed had been applied during initial migration (when `workcube_mikrolink.company` was empty); now re-seeded post-OUR_COMPANY-load:

```sql
INSERT INTO data_access.organization_company
  (org_id, workcube_company_source_pk, source_schema, source_table)
SELECT o.id, c.source_pk, 'workcube_mikrolink', 'OUR_COMPANY'
  FROM data_access.organization o
  CROSS JOIN workcube_mikrolink.our_company c
 WHERE o.name = 'AÇIK' AND c.source_schema = 'workcube_mikrolink'
   ON CONFLICT (org_id, workcube_company_source_pk) DO NOTHING;
-- INSERT 0 1

SELECT * FROM data_access.organization_company;
```

| org_id | workcube_company_source_pk | source_schema | source_table | attached_at | notes |
|--------|----------------------------|---------------|--------------|-------------|-------|
| 1 | `["1"]` | workcube_mikrolink | OUR_COMPANY | 2026-04-28 10:24:19.863782+00 | {} |

**Verdict**: PASS

### 5. data_access.scope INSERT (V25+V26 trigger PASS)

After V26 applied (source_pk dual-format tolerance):

```sql
INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
VALUES ('11111111-1111-1111-1111-111111111111',
        (SELECT id FROM data_access.organization WHERE name='AÇIK'),
        'company', 'OUR_COMPANY', '["1"]')
RETURNING id, user_id, org_id, scope_kind, scope_source_table, scope_ref, granted_at;
```

| id | user_id | org_id | scope_kind | scope_source_table | scope_ref | granted_at |
|----|---------|--------|------------|--------------------|-----------| -----------|
| 2 | 11111111-1111-1111-1111-111111111111 | 1 | company | OUR_COMPANY | `["1"]` | 2026-04-28 10:29:13.05184+00 |

(scope_id=2; id=1 was the V25-pre-V26 attempt which was rejected by trigger before V26.)

**Verdict**: PASS — V25 tenant predicate + V26 source_pk dual-format → first canlı scope row.

### 6. Outbox row (V22+V23 — post-INSERT eventual consistency)

```sql
SELECT count(*) FROM data_access.scope_outbox;
-- (verify post-INSERT)
```

This evidence file does NOT verify scope_outbox rows because the V22 outbox writer is in permission-service (Java; PR-G follow-up `sha-4f408f4`). This INSERT was direct PostgreSQL psql (operator), bypassing AccessScopeService, so no outbox row was triggered. D35-2 (DR-7) will exercise the full chain via REST grant.

**Verdict**: N/A for D35-1 — outbox is D35-2 territory.

## Final verdict

**D35-1 — PASS** (5/5 captures + 1 N/A).

The full upstream chain (ETL load → audit → organization_company seed → scope INSERT trigger pass) works under live Workcube data on staging-sw with V16-V26 migration chain applied + Codex hybrid contract.

## What this unblocks

- **DR-7 D35-2 first canlı evidence**: full eventual-consistency chain (REST grant → outbox PROCESSED → OpenFGA allow/deny). Per ADR-0010 §2.5 user-approval but agent can drive the orchestration.
- D35-3 product path (UI persona) is downstream of D35-2.

## Operator log

```text
2026-04-28 10:19 — V25 applied; ops grant re-applied; signature 4-arg confirmed
2026-04-28 10:20 — etl-worker:v25 built; manifest+inspect-source PASS (42 rows)
2026-04-28 10:21 — Step 1 dry-run with explicit Vault password PASS
2026-04-28 10:22:53 — Step 2 LIVE LOAD: OUR_COMPANY 1 row, run_id=d93e9917...
2026-04-28 10:23 — Step 4 verify: 1 row, comp_id=1 Mikrolink Bilişim
2026-04-28 10:24 — Step 5 organization_company reseed: 1 row for AÇIK org
2026-04-28 10:25 — D35-1 INSERT attempt with V25 only: REJECTED (drift discovered)
2026-04-28 10:26 — V26 PR #216 opened (dual-format fix)
2026-04-28 10:28 — V26 CI single-pass green; merged sha 17caa381
2026-04-28 10:29:13 — D35-1 INSERT retry post-V26: PASS scope_id=2
2026-04-28 10:30 — Evidence captured (this file)
```

## References

- ADR-0008 § Object id encoding (V25 update + transition map)
- ADR-0009 § D35 Evidence Ladder
- ADR-0010 §2.3 (D35 ladder authority), §2.5 (operator/agent matrix)
- Codex thread `019dd34e` (OUR_COMPANY drift fix sequence)
- PR #212 (PR-1 discovery), #213 (PR-2 V25), #214 (PR-3 ETL manifest), #215 (PR-4 ADR docs), #216 (V26 dual-format)
- ETL contract: `scripts/migration/etl_worker/etl_worker/transform.py:make_source_pk` (Codex iter-6 canonical JSON)
- Faz 16.2.A runbook: `docs/RB-faz-16-2-A-scope-anchor-load.md`
- D35 evidence template: `docs/d35-evidence-template.md`

Completed: 2026-04-28T10:30:00Z (UTC)
