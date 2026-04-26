# Workcube MSSQL → PG ETL Worker (Faz 16)

Stand-alone Python worker that copies a curated **canonical** subset of
Workcube MSSQL into PostgreSQL canonical tables (`workcube_mikrolink.*` +
`migration_audit.*`).

## Status

| Day | Scope | Evidence |
|---|---|---|
| Day 1 | Source inventory (40 tables, 23 canonical match + 17 parametric) | `docs/migration/mssql-inventory.md` |
| Day 2 | V16 DDL skeleton | merged PR #153 |
| Day 3 | V16 generator full impl (~2500 line DDL) | merged PR #154 |
| Day 4 | Worker skeleton (PoC manifest validate + MSSQL inspect) | merged PR #155 |
| Day 5 | Transform + idempotent upsert + per-table audit hooks | merged PR #156 |
| Day 6 | Audit module + retry classifier + status/resume | merged PR #157 |
| Day 7 | Orchestrator + V16 PK preflight + reconcile (limited/full/delta) | merged PR #158, hotfix #159, smoke MATCH committed |
| Day 8 | `rejects` CLI + README cleanup (this) | PR #160 |
| Faz 16.2.P | Parametric (multi-tenant + yearly schema) ETL — **DEFERRED** | see `PLAN.md` for reopen conditions |

The full canonical pipeline is wired and exercised end-to-end against a
local PostgreSQL (Mac dev-pg). Reconcile artifact:
`docs/migration/reconcile-20260426-1b4f8397-smoke-dev-pg.{md,json}`
(`VERDICT: MATCH`, checksum_pg = checksum_mssql, 3/3 sample hashes
match, idempotent re-run preserves row count).

## Commands

```bash
# Manifest validation (config/tables.yaml syntax + idempotency_key + columns)
etl-worker validate-manifest

# MSSQL probe (NTLM ReadOnly intent; no writes)
etl-worker inspect-source --tables COMPANY

# Real run (mode required; dry-run is `--mode dry-run`, NOT a separate --dry-run flag)
etl-worker run --mode initial      --run-id $(uuidgen) --tables COMPANY,BRANCH --limit 1000
etl-worker run --mode dry-run      --run-id $(uuidgen) --tables COMPANY        --limit 100
etl-worker run --mode final-delta  --run-id $(uuidgen)

# Resume an existing run (mode comes from migration_runs)
etl-worker run --resume --run-id <uuid>

# Status (zero-fill all 5 buckets in JSON + human)
etl-worker status --run-id <uuid> [--json]

# List rejects (Day 8 — SRE triage)
etl-worker rejects --run-id <uuid> [--table COMPANY] [--limit 50] [--offset 0] [--json]

# Reconcile (limited 1000 default; full / delta opt-in)
etl-worker reconcile --run-id <uuid> --scope limited --limit 1000 --output-dir docs/migration/
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | SUCCESS |
| 1 | FAILED (unexpected) or RUN_EXISTS |
| 2 | ABORTED (CRITICAL error / threshold breach / preflight failure) |
| 3 | LOCK_CONTENDED (another worker holds the run lease) |

## Manifest scope (canonical only)

`config/tables.yaml` enumerates the canonical (non-parametric) tables.
Each entry MUST declare `columns` with `pg_type` + `nullable` —
`_load_manifest` fails fast on empty `columns` (kural #9 prevents
silent `SELECT  FROM ...`). Idempotency-key columns must appear in
the column list.

Parametric tables (yearly + tenant schemas) are out of scope for now;
see `PLAN.md` Faz 16.2.P deferred section. Do not add parametric
entries to `tables.yaml`.

## Setup (local dev)

```bash
cd scripts/migration/etl_worker
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# macOS msodbcsql18 (only needed if you call inspect-source / live MSSQL)
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew install msodbcsql18

# Run unit tests (no DB needed)
pytest tests/ -v
```

### Live MSSQL probe envs

```bash
export MSSQL_HOST=10.9.193.201
export MSSQL_PORT=1433
export MSSQL_USER=AlUser_App
export MSSQL_DOMAIN=boreas
export MSSQL_PASSWORD='...'
export MSSQL_DATABASE=workcube_mikrolink
etl-worker inspect-source --tables COMPANY
```

### PG target envs

```bash
export PG_HOST=127.0.0.1     # or `postgres` Service in K8s
export PG_PORT=5432
export PG_USER=postgres
export PG_PASSWORD='...'
export PG_DATABASE=reports_db
```

V16 + V17 must be applied to `reports_db` before `run` (the runner's
`preflight_final_table_lineage` rejects stale schemas with a clear
"Apply V17..." remediation message).

```bash
psql -U postgres -d reports_db -f sql/migration/V16__reports.sql
psql -U postgres -d reports_db -f sql/migration/V17__etl_lineage_columns.sql
```

## Docker

```bash
docker build -t etl-worker:dev scripts/migration/etl_worker/
docker run --rm \
  -e MSSQL_HOST=10.9.193.201 \
  -e MSSQL_USER=AlUser_App \
  -e MSSQL_PASSWORD='...' \
  -e PG_HOST=postgres \
  -e PG_PASSWORD='...' \
  etl-worker:dev validate-manifest
```

## Architecture

```
config/tables.yaml
        │ (manifest with explicit columns + idempotency_key)
        ▼
runner.run_orchestrator(cfg)
   1. control_conn open + pg_try_advisory_lock(NS, run_id)         [contention → LOCK_CONTENDED, no audit mutate]
   2. preflight_v16_table_state_pk(control_conn)                    [SAVEPOINT probe; ROLLBACK]
   3. preflight_final_table_lineage(control_conn)                   [V17 applied? → SchemaContractError]
   4. audit_conn (autocommit), load_conn (default tx), mssql_conn
   5. AuditModule.create_run() OR get_run() (resume)
   6. for table_meta in manifest:
        upsert_table_state(EXTRACTING)
        for raw_batch in extract_fn(mssql, table_meta, last_pk, limit):
            for raw in raw_batch:
                tr = transform_row(raw, table_meta)                  [content_hash, source_pk]
                if tr.reject_reason:
                    audit.insert_rejects_batch(...)                  [autocommit; survives load rollback]
                else:
                    typed_batch.append(tr.typed_row)
            try:
                stats = load_batch(load_conn, typed_batch)          [bulk → per-row fallback, 3-bucket retry]
            except CRITICAL: ABORTED
            except TRANSIENT (over backoff cap): ABORTED
            on NO_RETRY: insert reject + continue
            audit.record_batch_success / record_batch_failure
            ThresholdPolicy(mode).should_abort? → ABORTED
        upsert_table_state(VALIDATED)
   7. update_run_status(SUCCESS)
   8. finally: pg_advisory_unlock + close all 4 conns
```

Mode-aware behaviour:
- `initial`: ratio-based threshold (default 0.0; CLI override).
- `final-delta`: strict — abort on FIRST reject (cutover discipline).
- `dry-run`: never aborts; rejects audit-only.
- `reconcile-only`: ratio-based.

## Codex thread references

| Thread | Scope | Verdict |
|---|---|---|
| `019dc6d5` | Days 1–5 (inventory → DDL → worker skeleton → upsert) | iter-5 AGREE |
| `019dc6fb` | Day 6 audit + retry → Day 7 orchestrator + reconcile | iter-10 AGREE on Day 7 |
| `019dc88c` | Faz 16.2.P parametric pivot review | iter-4 AGREE on Yol B (defer) |

## Hard rules in effect

- **No fake work** (kural #9): every commit must demonstrate verifiable
  delta. Tests run; live evidence pasted; Codex post-impl review on the
  actual code, not just the description.
- **Auto mode + Codex authority** (kural #8): Codex AGREE on a strategic
  question counts as the user's decision; the agent proceeds without
  re-asking.
- **No closure language** (kural #1): no "kapandı / bitti / tamam"
  phrases in commit messages, PRs, or chat.
