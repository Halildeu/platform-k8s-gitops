"""Faz 16.3 Gün 6 — AuditModule tests (Codex iter-7).

Strategy:
    Mock psycopg.Connection and Cursor to capture SQL strings + params.
    Real PG integration is exercised in Day 7 dry-run on the test cluster.

Hard rule under test (Codex iter-7):
    AuditModule MUST be given an autocommit connection. The class warns when
    autocommit=False; the *behaviour* is enforced by the caller (cli/runner).
    These tests verify (a) the warning trigger, (b) that audit writes do not
    open or commit a transaction (cursor exec only), so a load rollback on a
    sibling connection cannot wipe rejects.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from etl_worker.audit import (
    AUDIT_SCHEMA,
    DB_MODE_VALUES,
    AuditModule,
    RejectRecord,
    normalize_mode,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_conn():
    """psycopg.Connection mock with autocommit=True and a ctx-managed cursor."""
    cur = MagicMock(name="cursor")
    cur.fetchone.return_value = None
    cur.fetchall.return_value = []
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    conn = MagicMock(name="conn")
    conn.autocommit = True
    conn.cursor.return_value = cur
    conn._cur = cur  # convenience for assertions
    return conn


@pytest.fixture
def audit(mock_conn):
    return AuditModule(mock_conn)


# ============================================================================
# create_run / update_run_status
# ============================================================================

def test_create_run_inserts_running_row(audit, mock_conn):
    audit.create_run(
        run_id="11111111-1111-1111-1111-111111111111",
        mode="initial",
        source_database="workcube_mikrolink",
        worker_version="0.1.0",
        git_sha="abc123",
        contract_version="v1.0",
        annex_version="2A-2026-04-25",
        started_by="ci-bot",
        notes={"k": "v"},
    )
    cur = mock_conn._cur
    assert cur.execute.called
    sql_call = cur.execute.call_args
    rendered = _render(sql_call)
    assert "INSERT INTO" in rendered
    assert "migration_runs" in rendered
    assert "RUNNING" in rendered
    params = sql_call.args[1]
    assert params[0] == "11111111-1111-1111-1111-111111111111"
    assert params[1] == "initial"
    assert params[2] == "workcube_mikrolink"


# ============================================================================
# Mode normalization (Codex iter-8)
# ============================================================================

def test_normalize_mode_hyphen_to_underscore():
    """CLI hyphen modes must map to DB CHECK constraint underscore values."""
    assert normalize_mode("initial") == "initial"
    assert normalize_mode("final-delta") == "final_delta"
    assert normalize_mode("reconcile-only") == "reconcile_only"
    assert normalize_mode("dry-run") == "dry_run"


def test_normalize_mode_idempotent_underscore():
    """Already-canonical underscore form passes through."""
    assert normalize_mode("final_delta") == "final_delta"
    assert normalize_mode("dry_run") == "dry_run"


def test_normalize_mode_unknown_raises():
    with pytest.raises(ValueError):
        normalize_mode("BOGUS")


def test_db_mode_values_match_v16_check_constraint():
    """Sanity check that the canonical DB values match the V16 DDL CHECK
    constraint exactly. Drift here = audit insert constraint violation."""
    assert DB_MODE_VALUES == {"initial", "final_delta", "reconcile_only", "dry_run"}


def test_create_run_normalizes_mode(audit, mock_conn):
    """`final-delta` from CLI must be inserted as `final_delta` in audit."""
    audit.create_run(
        run_id="rid-fd",
        mode="final-delta",
        source_database="wm",
    )
    params = mock_conn._cur.execute.call_args.args[1]
    assert params[1] == "final_delta"  # normalized for CHECK constraint


def test_create_run_rejects_unknown_mode(audit):
    with pytest.raises(ValueError):
        audit.create_run(run_id="rid", mode="garbage", source_database="wm")


def test_update_run_status_success(audit, mock_conn):
    audit.update_run_status("rid-1", "SUCCESS")
    rendered = _render(mock_conn._cur.execute.call_args)
    assert "UPDATE" in rendered
    assert "migration_runs" in rendered
    assert "completed_at = now()" in rendered
    assert mock_conn._cur.execute.call_args.args[1][0] == "SUCCESS"


def test_update_run_status_invalid_raises(audit):
    with pytest.raises(ValueError):
        audit.update_run_status("rid-1", "BOGUS")


# ============================================================================
# upsert_table_state
# ============================================================================

def test_upsert_table_state_insert_when_missing(audit, mock_conn):
    """First call inserts a fresh row when the SELECT probe returns None."""
    cur = mock_conn._cur
    cur.fetchone.return_value = None  # no existing row

    audit.upsert_table_state(
        run_id="rid-1",
        table_name="COMPANY",
        source_schema="workcube_mikrolink",
        source_year=None,
        status="EXTRACTING",
        rows_extracted=100,
    )

    # Two execute calls: SELECT probe + INSERT
    calls = cur.execute.call_args_list
    assert len(calls) == 2
    assert "SELECT 1" in _render(calls[0])
    assert "INSERT INTO" in _render(calls[1])
    assert "migration_table_state" in _render(calls[1])


def test_upsert_table_state_update_when_exists(audit, mock_conn):
    """Existing row → UPDATE path with cumulative counters."""
    cur = mock_conn._cur
    cur.fetchone.return_value = (1,)  # row exists

    audit.upsert_table_state(
        run_id="rid-1",
        table_name="COMPANY",
        source_schema="workcube_mikrolink",
        source_year=None,
        status="LOADING",
        rows_loaded=500,
        last_pk='["999"]',
    )

    calls = cur.execute.call_args_list
    assert len(calls) == 2
    assert "UPDATE" in _render(calls[1])
    assert "rows_loaded = rows_loaded + %s" in _render(calls[1])


def test_upsert_table_state_invalid_status(audit):
    with pytest.raises(ValueError):
        audit.upsert_table_state(
            run_id="rid-1",
            table_name="X",
            source_schema="s",
            source_year=None,
            status="WAT",
        )


def test_record_batch_helpers_call_upsert(audit, mock_conn):
    cur = mock_conn._cur
    cur.fetchone.return_value = (1,)  # all updates

    audit.record_batch_start("r", "T", "s", 2024, batch_no=1)
    audit.record_batch_success("r", "T", "s", 2024, rows_loaded=10, last_pk='["1"]', batch_no=1)
    audit.record_batch_failure("r", "T", "s", 2024, batch_no=1, rows_rejected=2)

    # 3 helper calls × (probe + update) = 6 executes
    assert cur.execute.call_count == 6

    # Status is bound as a parameter — check the UPDATE params (calls 1, 3, 5).
    update_calls = [cur.execute.call_args_list[i] for i in (1, 3, 5)]
    statuses = [c.args[1][0] for c in update_calls]  # first %s in UPDATE = status
    assert statuses == ["LOADING", "LOADING", "LOADING"]

    # And the success call must have last_pk + rows_loaded set (params index 2, 4)
    success_params = update_calls[1].args[1]
    assert success_params[2] == 10  # rows_loaded
    assert success_params[4] == '["1"]'  # last_pk


# ============================================================================
# Rejects — survive load rollback (autocommit conn)
# ============================================================================

def test_insert_reject_does_not_use_transaction(audit, mock_conn):
    """AuditModule never calls conn.transaction() / conn.commit() — its
    autocommit conn must be independent of the load tx."""
    audit.insert_reject(
        RejectRecord(
            run_id="rid-1",
            table_name="COMPANY",
            source_schema="workcube_mikrolink",
            source_year=None,
            source_pk='["123"]',
            column_name="company_name",
            reject_reason="LENGTH_OVERFLOW",
            severity="ERROR",
            source_value="X" * 300,
            pg_error_code=None,
            pg_error_message=None,
            raw_payload={"company_id": 123},
        )
    )
    # No transaction / no commit calls
    assert not mock_conn.transaction.called
    assert not mock_conn.commit.called

    rendered = _render(mock_conn._cur.execute.call_args)
    assert "INSERT INTO" in rendered
    assert "migration_rejects" in rendered
    params = mock_conn._cur.execute.call_args.args[1]
    assert params[6] == "LENGTH_OVERFLOW"
    assert params[7] == "ERROR"


def test_insert_rejects_batch_uses_executemany(audit, mock_conn):
    rejects = [
        RejectRecord(
            run_id="rid-1",
            table_name="T",
            source_schema="s",
            source_year=None,
            source_pk='["1"]',
            column_name="c",
            reject_reason="TYPE_CAST_FAIL",
            severity="ERROR",
            source_value="bad",
            pg_error_code=None,
            pg_error_message=None,
            raw_payload=None,
        )
        for _ in range(5)
    ]
    n = audit.insert_rejects_batch(rejects)
    assert n == 5
    cur = mock_conn._cur
    assert cur.executemany.called
    args = cur.executemany.call_args
    rendered = _render(args)
    assert "migration_rejects" in rendered
    assert len(args.args[1]) == 5


def test_insert_rejects_batch_empty_returns_zero(audit, mock_conn):
    n = audit.insert_rejects_batch([])
    assert n == 0
    assert not mock_conn._cur.executemany.called


def test_audit_warns_on_non_autocommit(caplog):
    """Codex iter-7: passing a non-autocommit conn should produce a warning."""
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.autocommit = False
    conn.cursor.return_value = cur
    with caplog.at_level(logging.WARNING, logger="etl_worker.audit"):
        AuditModule(conn)
    assert any("not_autocommit" in r.message for r in caplog.records)


# ============================================================================
# Resume + status helpers
# ============================================================================

def test_get_resume_state_returns_keyed_dict(audit, mock_conn):
    cur = mock_conn._cur
    cur.fetchall.return_value = [
        ("COMPANY", "workcube_mikrolink", None, "VALIDATED", 100, 100, 0, '["999"]', 5),
        ("BANK_ACTIONS", "workcube_mikrolink_1", 2024, "LOADING", 500, 400, 1, '["42"]', 2),
        ("BANK_ACTIONS", "workcube_mikrolink_1", 2025, "PENDING", 0, 0, 0, None, 0),
    ]
    state = audit.get_resume_state("rid-1")
    assert len(state) == 3
    assert state["COMPANY|workcube_mikrolink|"]["status"] == "VALIDATED"
    assert state["BANK_ACTIONS|workcube_mikrolink_1|2024"]["status"] == "LOADING"
    assert state["BANK_ACTIONS|workcube_mikrolink_1|2024"]["last_pk"] == '["42"]'


def test_resume_caller_skips_validated(audit, mock_conn):
    """Codex iter-7 hard rule: resume skips VALIDATED entries.

    AuditModule exposes raw state; the orchestrator filters. Verify the
    filter pattern documented in cli.py works as advertised.
    """
    cur = mock_conn._cur
    cur.fetchall.return_value = [
        ("A", "s", None, "VALIDATED", 1, 1, 0, None, 0),
        ("B", "s", None, "LOADING", 1, 0, 0, None, 0),
        ("C", "s", None, "PENDING", 0, 0, 0, None, 0),
    ]
    state = audit.get_resume_state("rid")
    todo = [k for k, v in state.items() if v["status"] != "VALIDATED"]
    assert sorted(todo) == ["B|s|", "C|s|"]


def test_get_run_returns_none_when_missing(audit, mock_conn):
    mock_conn._cur.fetchone.return_value = None
    assert audit.get_run("missing") is None


def test_get_run_returns_dict(audit, mock_conn):
    mock_conn._cur.fetchone.return_value = (
        "11111111-1111-1111-1111-111111111111",
        "initial",
        "RUNNING",
        "workcube_mikrolink",
        "2026-04-25T10:00:00+00:00",
        None,
        None,
    )
    r = audit.get_run("rid")
    assert r["status"] == "RUNNING"
    assert r["mode"] == "initial"


def test_status_summary_aggregates_buckets(audit, mock_conn):
    cur = mock_conn._cur
    cur.fetchone.side_effect = [
        # get_run
        ("rid", "initial", "RUNNING", "wm", "ts", None, None),
        # reject_count
        (3,),
    ]
    cur.fetchall.return_value = [
        ("VALIDATED", 10, 1000, 990, 10),
        ("LOADING", 1, 500, 200, 0),
    ]
    summary = audit.status_summary("rid")
    assert summary["run"]["status"] == "RUNNING"
    assert summary["buckets"]["VALIDATED"]["tables"] == 10
    assert summary["buckets"]["LOADING"]["rows_loaded"] == 200
    assert summary["reject_total"] == 3


def test_reject_count_filters_by_table(audit, mock_conn):
    mock_conn._cur.fetchone.return_value = (5,)
    n = audit.reject_count("rid", table_name="COMPANY")
    assert n == 5
    rendered = _render(mock_conn._cur.execute.call_args)
    assert "migration_rejects" in rendered
    assert "table_name" in rendered


# ============================================================================
# Helper
# ============================================================================

def _render(call) -> str:
    """Best-effort SQL string render from psycopg sql.Composed mocks.

    The first positional arg may be a sql.Composed; we round-trip it via
    .as_string(None) when possible, otherwise repr it.
    """
    args = call.args
    if not args:
        return ""
    composed = args[0]
    if hasattr(composed, "as_string"):
        try:
            return composed.as_string(None)
        except Exception:
            pass
    return repr(composed)
