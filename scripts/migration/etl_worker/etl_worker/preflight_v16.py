"""Faz 16.3 Gün 7 — V16 expression-PK preflight (Codex iter-4 AGREE).

Runs under the runner's advisory lock on the rollback-capable control_conn.
Probes whether `migration_audit.migration_table_state.PRIMARY KEY` enforces
uniqueness for COALESCE(source_year, 0) — i.e. two inserts with
`source_year IS NULL` and the same other PK columns must produce a
UniqueViolation.

If the contract holds: rollback the sentinel transaction, return cleanly.
If it does NOT hold: raise SchemaContractError so the runner can refuse to
start (better hard-fail at startup than silent data corruption later).

All work happens inside a sentinel run_id (00000000-...) inside an explicit
BEGIN ... ROLLBACK so audit DB stays clean. UniqueViolation is caught under
a SAVEPOINT so the outer transaction never enters the InFailedSqlTransaction
state.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager

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
