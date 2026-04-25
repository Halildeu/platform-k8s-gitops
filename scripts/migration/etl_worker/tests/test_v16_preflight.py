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
