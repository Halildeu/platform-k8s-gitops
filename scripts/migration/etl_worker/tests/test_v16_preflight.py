"""Faz 16.3 Gün 7 — V16 PK preflight tests (Codex iter-4 AGREE).

Mocks psycopg.Connection + cursor; verifies the exact SQL probe sequence,
SAVEPOINT pattern, ROLLBACK in both success and failure paths, and
SchemaContractError when uniqueness is not enforced.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import psycopg
import pytest

from etl_worker.preflight_v16 import (
    SENTINEL_RUN_ID,
    SchemaContractError,
    preflight_v16_table_state_pk,
)


def _make_conn(autocommit: bool = True) -> MagicMock:
    cur = MagicMock(name="cursor")
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock(name="conn")
    conn.autocommit = autocommit
    conn.cursor.return_value = cur
    conn._cur = cur
    return conn


def _set_execute_side_effect(cur: MagicMock, *behaviors):
    """Each behavior is either None (no-op success) or an Exception class /
    instance to raise on that execute() call."""
    seq = list(behaviors)

    def side_effect(*args, **kwargs):
        if not seq:
            return None
        b = seq.pop(0)
        if isinstance(b, BaseException):
            raise b
        if isinstance(b, type) and issubclass(b, BaseException):
            raise b(*[arg for arg in args[1:]] or ["boom"])
        return None

    cur.execute.side_effect = side_effect


# ============================================================================
# Happy path: duplicate raises UniqueViolation under SAVEPOINT
# ============================================================================

def test_preflight_happy_path_duplicate_caught_under_savepoint():
    conn = _make_conn(autocommit=True)
    cur = conn._cur

    # execute order:
    #  1. BEGIN
    #  2. INSERT migration_runs (sentinel)
    #  3. INSERT migration_table_state (first)
    #  4. SAVEPOINT duplicate_probe
    #  5. INSERT migration_table_state (duplicate)  → raise UniqueViolation
    #  6. ROLLBACK TO SAVEPOINT duplicate_probe
    #  7. ROLLBACK (outer)
    _set_execute_side_effect(
        cur,
        None,  # BEGIN
        None,  # INSERT runs
        None,  # INSERT table_state #1
        None,  # SAVEPOINT
        psycopg.errors.UniqueViolation("dup"),
        None,  # ROLLBACK TO SAVEPOINT
        None,  # ROLLBACK
    )

    preflight_v16_table_state_pk(conn)

    sql_calls = [c.args[0] for c in cur.execute.call_args_list]
    assert sql_calls[0].upper() == "BEGIN"
    assert "migration_runs" in sql_calls[1]
    assert "migration_table_state" in sql_calls[2]
    assert "SAVEPOINT duplicate_probe" in sql_calls[3]
    assert "migration_table_state" in sql_calls[4]
    assert "ROLLBACK TO SAVEPOINT duplicate_probe" in sql_calls[5]
    assert sql_calls[6].upper() == "ROLLBACK"


# ============================================================================
# Schema contract failure: duplicate did NOT raise
# ============================================================================

def test_preflight_schema_contract_failure_when_duplicate_succeeds():
    conn = _make_conn(autocommit=True)
    cur = conn._cur
    # All 5 insert/savepoint calls succeed → contract broken.
    _set_execute_side_effect(
        cur,
        None,  # BEGIN
        None,  # INSERT runs
        None,  # INSERT table_state #1
        None,  # SAVEPOINT
        None,  # INSERT duplicate (no exception → BAD)
        None,  # RELEASE SAVEPOINT
        None,  # ROLLBACK (still called from finally)
    )
    with pytest.raises(SchemaContractError):
        preflight_v16_table_state_pk(conn)

    # Even on SchemaContractError the outer ROLLBACK must run.
    sql_calls = [c.args[0] for c in cur.execute.call_args_list]
    assert sql_calls[-1].upper() == "ROLLBACK"


# ============================================================================
# ROLLBACK always called — even when an unexpected exception escapes
# ============================================================================

def test_preflight_rollback_called_when_unexpected_exception_during_insert():
    conn = _make_conn(autocommit=True)
    cur = conn._cur

    class WeirdError(Exception):
        pass

    _set_execute_side_effect(
        cur,
        None,            # BEGIN
        WeirdError(),    # INSERT runs raises
        None,            # ROLLBACK in finally
    )
    with pytest.raises(WeirdError):
        preflight_v16_table_state_pk(conn)

    # finally block still ran ROLLBACK
    sql_calls = [c.args[0] for c in cur.execute.call_args_list]
    assert sql_calls[-1].upper() == "ROLLBACK"


# ============================================================================
# Sentinel UUID is the documented constant
# ============================================================================

def test_sentinel_run_id_is_zero_uuid():
    """The sentinel must be deterministic so other tooling can recognize and
    safely ignore it if it ever leaks (it shouldn't)."""
    assert SENTINEL_RUN_ID == "00000000-0000-0000-0000-000000000000"


# ============================================================================
# Non-autocommit connection: warning only, still runs
# ============================================================================

# ============================================================================
# preflight_final_table_lineage (Codex iter-8)
# ============================================================================

from etl_worker.preflight_v16 import (
    REQUIRED_LINEAGE_COLUMNS,
    preflight_final_table_lineage,
)


def _lineage_conn(
    columns_by_table: dict[str, list[str]],
    unique_indexes_by_table: dict[str, list[str]] | None = None,
) -> MagicMock:
    """Build a PG conn mock that satisfies the catalog queries used by
    preflight_final_table_lineage().

    columns_by_table: { table_name: [col_name, ...] }
    unique_indexes_by_table: { table_name: [indexdef_string, ...] }
    """
    unique_indexes_by_table = unique_indexes_by_table or {}
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    state = {"current_table": None, "phase": None, "indexes_remaining": []}

    def execute_side_effect(sql_text: str, params=None):
        sql_text = sql_text.strip()
        if "information_schema.columns" in sql_text:
            tname = params[1]
            state["current_table"] = tname
            state["phase"] = "columns"
        elif "indnatts = 3" in sql_text:
            state["phase"] = "indexes"
            tname = params[1]
            state["indexes_remaining"] = list(unique_indexes_by_table.get(tname, []))
        elif "indexdef" in sql_text:
            state["phase"] = "indexdef"

    def fetchall_side_effect():
        if state["phase"] == "columns":
            return [(c,) for c in columns_by_table.get(state["current_table"], [])]
        if state["phase"] == "indexes":
            return [(f"idx_{i}",) for i in range(len(state["indexes_remaining"]))]
        return []

    def fetchone_side_effect():
        if state["phase"] == "indexdef":
            if state["indexes_remaining"]:
                idef = state["indexes_remaining"].pop(0)
                return (idef,)
            return None
        return None

    cur.execute.side_effect = execute_side_effect
    cur.fetchall.side_effect = fetchall_side_effect
    cur.fetchone.side_effect = fetchone_side_effect

    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def test_lineage_preflight_passes_when_columns_and_unique_present():
    conn = _lineage_conn(
        columns_by_table={
            "company": ["company_id", "source_schema", "source_table", "source_pk", "content_hash"],
        },
        unique_indexes_by_table={
            "company": [
                "CREATE UNIQUE INDEX idx_company_lineage ON workcube_mikrolink.company "
                "USING btree (source_schema, source_table, source_pk)"
            ],
        },
    )
    # Should not raise.
    preflight_final_table_lineage(conn, table_names=["COMPANY"])


def test_lineage_preflight_raises_when_column_missing():
    conn = _lineage_conn(
        columns_by_table={
            # source_pk missing
            "company": ["company_id", "source_schema", "source_table", "content_hash"],
        },
    )
    with pytest.raises(SchemaContractError) as exc:
        preflight_final_table_lineage(conn, table_names=["COMPANY"])
    assert "source_pk" in str(exc.value)
    assert "V17" in str(exc.value)


def test_lineage_preflight_raises_when_table_not_found():
    conn = _lineage_conn(columns_by_table={})  # nothing in info_schema
    with pytest.raises(SchemaContractError) as exc:
        preflight_final_table_lineage(conn, table_names=["GHOST"])
    assert "not found in information_schema" in str(exc.value) or "GHOST" in str(exc.value)


def test_lineage_preflight_raises_when_unique_index_missing():
    conn = _lineage_conn(
        columns_by_table={
            "company": list(REQUIRED_LINEAGE_COLUMNS) + ["company_id"],
        },
        unique_indexes_by_table={"company": []},  # no unique indexes
    )
    with pytest.raises(SchemaContractError) as exc:
        preflight_final_table_lineage(conn, table_names=["COMPANY"])
    assert "UNIQUE" in str(exc.value)


def test_lineage_preflight_raises_when_unique_index_does_not_cover_lineage():
    """A unique 3-column index over the wrong cols must NOT pass."""
    conn = _lineage_conn(
        columns_by_table={
            "company": list(REQUIRED_LINEAGE_COLUMNS) + ["company_id"],
        },
        unique_indexes_by_table={
            # 3-col unique on unrelated columns
            "company": [
                "CREATE UNIQUE INDEX idx_other ON workcube_mikrolink.company "
                "USING btree (a, b, c)"
            ],
        },
    )
    with pytest.raises(SchemaContractError):
        preflight_final_table_lineage(conn, table_names=["COMPANY"])


# ============================================================================
# Original preflight (autocommit warning)
# ============================================================================


def test_preflight_warns_when_conn_not_autocommit(caplog):
    import logging
    conn = _make_conn(autocommit=False)
    cur = conn._cur
    _set_execute_side_effect(
        cur,
        None, None, None, None,
        psycopg.errors.UniqueViolation("dup"),
        None, None,
    )
    with caplog.at_level(logging.WARNING, logger="etl_worker.preflight_v16"):
        preflight_v16_table_state_pk(conn)
    assert any("not_autocommit" in r.message for r in caplog.records)
