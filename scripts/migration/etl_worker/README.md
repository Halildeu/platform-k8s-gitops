# Faz 16.3 — Workcube MSSQL → PG ETL Worker

> **Codex thread**: `019dc6d5` iter-5 AGREE
> **Status**: Gün 4 SKELETON (PoC inspection + manifest validation)
> **Sprint**: 7 günlük plan (Codex iter-2 + iter-5 revize)

## Komutlar

```bash
# Manifest validation (config/tables.yaml syntax + idempotency_key check)
python -m etl_worker validate-manifest

# MSSQL connection + per-table row count
python -m etl_worker inspect-source --tables COMPANY,COMPANY_PARTNER

# Initial load (Gün 5+ tam impl)
python -m etl_worker run --mode initial --run-id $(uuidgen) --tables COMPANY --dry-run

# Final delta (cutover, T-0 freeze)
python -m etl_worker run --mode final-delta --run-id $(uuidgen)

# Reconciliation (16.3.5 gate)
python -m etl_worker reconcile --run-id $(uuidgen) --output docs/migration/reconcile-$(date +%Y%m%d).md
```

## Setup (local dev)

```bash
cd scripts/migration/etl_worker
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Mac'te msodbcsql18 (Homebrew)
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew install msodbcsql18

# ODBC connection test
export MSSQL_HOST=10.9.193.201
export MSSQL_USER=AlUser_App
export MSSQL_PASSWORD="..."
export MSSQL_DOMAIN=boreas

python -m etl_worker inspect-source --tables COMPANY
```

## Docker

```bash
docker build -t etl-worker:dev scripts/migration/etl_worker/
docker run --rm \
  -e MSSQL_HOST=10.9.193.201 \
  -e MSSQL_USER=AlUser_App \
  -e MSSQL_PASSWORD=... \
  -e PG_HOST=postgres \
  -e PG_PASSWORD=... \
  etl-worker:dev validate-manifest
```

## Architecture (Codex iter-5)

```
config/tables.yaml
        │
        ▼
[manifest.py] — load + validate
        │
        ▼
[extract.py] — MSSQL pyodbc fetchmany (batch_size=10000)
        │  per-batch in-memory CSV buffer (stream, no disk)
        ▼
[load.py] — PG psycopg COPY workcube_mssql_raw.<table>
        │
        ▼
[transform.py] — type mapping (Codex iter-1) + content_hash SHA-256
        │
        ▼
[load.py] — PG INSERT ... ON CONFLICT (source_schema, source_year, source_table, source_pk)
        │  DO UPDATE WHERE excluded.content_hash <> existing.content_hash
        ▼
[audit.py] — migration_runs/state/rejects update per-batch commit
        │
        ▼
[reconcile.py] — row count parity + checksum + sample diff (16.3.5 gate)
```

## Sprint progress

| Gün | İçerik | Durum |
|---|---|---|
| 1 | Source inventory (40 tablo) | ✓ DONE PR #151 |
| 2 | V16 DDL skeleton | ✓ DONE PR #153 |
| 3 | Generator full impl (2497 line DDL) | ✓ DONE PR #154 |
| **4** | **Worker skeleton (THIS PR)** | **Sprint** |
| 5 | Transform + final load + upsert | TODO |
| 6 | Reject queue + retry/resume | TODO |
| 7 | Reconciliation + test cluster dry-run | TODO |

## Codex thread

`019dc6d5` (Faz 16 sprint, 5 iter):
- iter-1: RED Aşama 2A → Faz 16 öncelik
- iter-2: REVISE 7-günlük sprint plan AGREE
- iter-3: REVISE V16 DDL skeleton (single file + section structure)
- iter-4: REVISE generator full impl (23 matched + 17 placeholder)
- iter-5: REVISE worker skeleton (PoC scope, transform Gün 5'e)
