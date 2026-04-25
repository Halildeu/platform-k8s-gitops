"""Faz 16.3 — MSSQL → PG ETL Worker.

Codex thread 019dc6d5 iter-5 AGREE.

Modules:
- cli: click CLI entrypoint
- config: env config + DSN
- manifest: tables.yaml loader + validator
- extract: MSSQL fetchmany + CSV buffer
- transform: type mapping + content_hash
- load: PG COPY bulk
- audit: migration_runs/state/rejects insert/update
- reconcile: 16.3.5 gate (row count + checksum + sample diff)
"""

__version__ = "0.1.0"
