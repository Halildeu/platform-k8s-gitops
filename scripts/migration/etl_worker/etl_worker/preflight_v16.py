"""Faz 16.3 Gün 7 — V16 expression-PK preflight (Codex iter-4 AGREE).

Two preflights live in this module:

  * preflight_v16_table_state_pk(control_conn) — verifies that
    migration_audit.migration_table_state.PRIMARY KEY enforces uniqueness
    for COALESCE(source_year, 0).

  * preflight_final_table_lineage(pg_conn, manifest, schema) — Codex iter-8:
    verifies that every selected canonical final table carries the ETL
    lineage columns + conflict-key unique index that load_batch() relies
    on. Catches stale schemas where V17 has not been applied.

Both raise SchemaContractError so the runner can refuse to start.
"""

from __future__ import annotations

import logging
from typing import Iterable

import psycopg
from psycopg import sql

log = logging.getLogger(__name__)

# Sentinel UUID used only by preflight; never leaks into real audit data.
SENTINEL_RUN_ID = "00000000-0000-0000-0000-000000000000"
SENTINEL_TABLE = "PREFLIGHT_V16_PK_PROBE"
SENTINEL_SCHEMA = "preflight"


class SchemaContractError(RuntimeError):
    """V16 audit DDL contract violation — runner must refuse to start."""


def preflight_v16_table_state_pk(control_conn: psycopg.Connection) -> None:
    """Probe migration_table_state PK uniqueness on (run, table, schema, COALESCE(year, 0)).

    Raises:
        SchemaContractError if duplicate insert (year=NULL) does not raise
            UniqueViolation, indicating the V16 PK expression is not enforced
            as expected.
    """
    if control_conn.autocommit is False:
        # Defensive: caller passes an autocommit conn so BEGIN/ROLLBACK are
        # explicit. If autocommit is False the conn already has a tx and our
        # rollback would discard work the caller didn't expect to lose.
        log.warning(
            "preflight.conn.not_autocommit "
            "— preflight expects control_conn.autocommit=True"
        )

    with control_conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            # Insert sentinel run row (FK requirement).
            cur.execute(
                "INSERT INTO migration_audit.migration_runs "
                "(run_id, mode, status, source_database, started_by, notes) "
                "VALUES (%s, 'initial', 'RUNNING', 'preflight_sentinel', "
                "        'preflight', '{}'::jsonb)",
                (SENTINEL_RUN_ID,),
            )

            # First table_state insert — should succeed.
            cur.execute(
                "INSERT INTO migration_audit.migration_table_state "
                "(run_id, table_name, source_schema, source_year, status) "
                "VALUES (%s, %s, %s, NULL, 'PENDING')",
                (SENTINEL_RUN_ID, SENTINEL_TABLE, SENTINEL_SCHEMA),
            )

            # Duplicate insert under savepoint — should raise UniqueViolation.
            cur.execute("SAVEPOINT duplicate_probe")
            duplicate_raised = False
            try:
                cur.execute(
                    "INSERT INTO migration_audit.migration_table_state "
                    "(run_id, table_name, source_schema, source_year, status) "
                    "VALUES (%s, %s, %s, NULL, 'PENDING')",
                    (SENTINEL_RUN_ID, SENTINEL_TABLE, SENTINEL_SCHEMA),
                )
            except psycopg.errors.UniqueViolation:
                duplicate_raised = True
                cur.execute("ROLLBACK TO SAVEPOINT duplicate_probe")
            else:
                cur.execute("RELEASE SAVEPOINT duplicate_probe")

            if not duplicate_raised:
                raise SchemaContractError(
                    "V16 PK contract failure: duplicate INSERT into "
                    "migration_table_state with (run_id, table_name, "
                    "source_schema, source_year=NULL) did not raise "
                    "UniqueViolation. PRIMARY KEY uses COALESCE(source_year, 0) "
                    "but uniqueness is not being enforced. Migrate to a STORED "
                    "generated `source_year_norm SMALLINT GENERATED ALWAYS AS "
                    "(COALESCE(source_year, 0)) STORED` column with a real "
                    "UNIQUE index, then re-run preflight."
                )

            log.info("preflight.v16_pk_probe.ok run_id=%s", SENTINEL_RUN_ID)
        finally:
            # ALWAYS rollback so the sentinel never persists.
            cur.execute("ROLLBACK")


# ============================================================================
# Final-table lineage preflight (Codex iter-8 — V17 ALTER applied?)
# ============================================================================

REQUIRED_LINEAGE_COLUMNS: tuple[str, ...] = (
    "source_schema",
    "source_table",
    "source_pk",
    "content_hash",
)


def preflight_final_table_lineage(
    pg_conn: psycopg.Connection,
    table_names: Iterable[str],
    schema: str = "workcube_mikrolink",
) -> None:
    """Verify each selected canonical table carries ETL lineage columns and
    a unique constraint or index over (source_schema, source_table, source_pk).

    Catches the stale-schema failure mode Codex iter-8 flagged: V16 was
    immutable; V17 might not yet be applied to the target DB. Without this
    preflight, the runner would push a batch with `source_table`/`source_pk`
    columns to a DB that has no such columns → `undefined_column` 42703.
    """
    missing_cols: dict[str, list[str]] = {}
    missing_unique: list[str] = []

    with pg_conn.cursor() as cur:
        for table in table_names:
            tname = table.lower()
            # Column existence check
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s",
                (schema, tname),
            )
            present = {row[0] for row in cur.fetchall()}
            if not present:
                missing_cols[table] = [
                    f"<table {schema}.{tname} not found in information_schema>"
                ]
                continue
            absent = [c for c in REQUIRED_LINEAGE_COLUMNS if c not in present]
            if absent:
                missing_cols[table] = absent

            # Conflict-key uniqueness check: a UNIQUE INDEX or CONSTRAINT
            # spanning exactly (source_schema, source_table, source_pk).
            cur.execute(
                """
                SELECT i.indexname
                FROM pg_indexes i
                JOIN pg_class c ON c.relname = i.indexname
                JOIN pg_index ix ON ix.indexrelid = c.oid
                WHERE i.schemaname = %s
                  AND i.tablename = %s
                  AND ix.indisunique = true
                  AND ix.indnatts = 3
                """,
                (schema, tname),
            )
            unique_idx_names = [row[0] for row in cur.fetchall()]
            # Cheap second pass: check that one of those unique indexes
            # actually covers the lineage triple by inspecting indexdef.
            has_lineage_unique = False
            for idx_name in unique_idx_names:
                cur.execute(
                    "SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND indexname = %s",
                    (schema, idx_name),
                )
                row = cur.fetchone()
                if not row:
                    continue
                indexdef = row[0]
                if (
                    "source_schema" in indexdef
                    and "source_table" in indexdef
                    and "source_pk" in indexdef
                ):
                    has_lineage_unique = True
                    break
            if not has_lineage_unique:
                missing_unique.append(table)

    if missing_cols or missing_unique:
        msg_parts: list[str] = []
        if missing_cols:
            msg_parts.append(
                "missing lineage columns: "
                + ", ".join(f"{k}({','.join(v)})" for k, v in missing_cols.items())
            )
        if missing_unique:
            msg_parts.append(
                "missing UNIQUE (source_schema, source_table, source_pk): "
                + ", ".join(missing_unique)
            )
        msg_parts.append(
            "Apply V17__etl_lineage_columns.sql to bring schema in line with "
            "the runner's load_batch() contract, then retry."
        )
        raise SchemaContractError("; ".join(msg_parts))

    log.info(
        "preflight.final_table_lineage.ok schema=%s tables=%s",
        schema, list(table_names),
    )
