"""Faz 16.3 Gün 7 — Reconcile gate tests (Codex iter-4 AGREE).

Tests cover:
  - ReconcileScope validation (kind, limit, checkpoint)
  - Limited path: MSSQL expected set used for both row count + checksum +
    sample diff; PG independent-LIMIT path NOT taken (Codex iter-3 fix)
  - Verdict matrix: MATCH / ROW_COUNT_MISMATCH / SAMPLE_MISMATCH /
                    CHECKSUM_MISMATCH / UNSUPPORTED_DELTA
  - Markdown + JSON renderers don't crash on real-shaped reports
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from etl_worker.reconcile import (
    ReconcileReport,
    ReconcileScope,
    TableReconcileResult,
    reconcile_table,
    render_json,
    render_markdown,
)
from etl_worker.transform import ColumnMeta, TableMeta, content_hash


# ============================================================================
# Fixtures + helpers
# ============================================================================

def _company_meta() -> TableMeta:
    return TableMeta(
        name="COMPANY",
        source_schema="workcube_mikrolink",
        source_year=None,
        columns=[
            ColumnMeta(name="company_id", pg_type="BIGINT", nullable=False),
            ColumnMeta(name="company_name", pg_type="VARCHAR(255)", nullable=False, max_length=255),
        ],
        idempotency_key=["company_id"],
    )


def _hash_for(row: dict) -> str:
    """Compute the same content_hash a real load would store."""
    from etl_worker.transform import transform_row
    tr = transform_row(row, _company_meta())
    return tr.content_hash


def _make_pg_conn(rows_pg: list[tuple], aggregate: str | None) -> MagicMock:
    """PG mock: returns the given rows on lookup, the given aggregate on
    md5(string_agg(...)) call."""
    cur = MagicMock()
    # Two distinct query types: ANY(...) lookup vs aggregate. We use call
    # order: first execute = lookup, second = aggregate.
    rounds = [
        rows_pg,            # for SELECT source_pk, content_hash WHERE ANY()
        [(aggregate,)],     # for SELECT md5(string_agg(...))
    ]

    def execute_side_effect(*args, **kwargs):
        cur._next = rounds.pop(0)

    cur.execute.side_effect = execute_side_effect
    cur.fetchall.side_effect = lambda: cur._next
    cur.fetchone.side_effect = lambda: cur._next[0] if cur._next else None

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn._cur = cur
    return conn


def _make_mssql_conn(scoped_rows: list[dict]) -> MagicMock:
    """MSSQL mock: returns scoped_rows when fetch_scoped_rows() is invoked.

    The mock implements pyodbc-like cursor.fetchall() returning tuples in
    column order, so the reconcile module's _mssql_fetch_scoped_rows()
    can convert them back to dicts.
    """
    cols = [c.name for c in _company_meta().columns]
    cur = MagicMock()
    tuples = [tuple(r[c] for c in cols) for r in scoped_rows]
    cur.execute = MagicMock()
    cur.fetchall = MagicMock(return_value=tuples)
    cur.fetchone = MagicMock(return_value=(len(scoped_rows),))

    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cur)
    return conn


# ============================================================================
# Scope validation
# ============================================================================

def test_scope_kind_invalid_raises():
    with pytest.raises(ValueError):
        ReconcileScope(kind="bogus")


def test_scope_limited_requires_limit():
    with pytest.raises(ValueError):
        ReconcileScope(kind="limited", limit=None)
    with pytest.raises(ValueError):
        ReconcileScope(kind="limited", limit=0)


def test_scope_delta_requires_checkpoint():
    with pytest.raises(ValueError):
        ReconcileScope(kind="delta")


def test_scope_full_ok():
    ReconcileScope(kind="full")


# ============================================================================
# Limited path: MATCH verdict
# ============================================================================

def test_limited_match_verdict_when_pg_and_mssql_aligned():
    """Both sides have the same scoped set + same hashes → MATCH."""
    rows = [
        {"company_id": 1, "company_name": "A"},
        {"company_id": 2, "company_name": "B"},
    ]
    h1 = _hash_for(rows[0])
    h2 = _hash_for(rows[1])
    pg_conn = _make_pg_conn(
        rows_pg=[('["1"]', h1), ('["2"]', h2)],
        aggregate=hashlib.md5((h1 + h2).encode()).hexdigest()
                  if '["1"]' < '["2"]'
                  else hashlib.md5((h2 + h1).encode()).hexdigest(),
    )
    mssql_conn = _make_mssql_conn(rows)

    res = reconcile_table(pg_conn, mssql_conn, _company_meta(), ReconcileScope(kind="limited", limit=10))
    assert res.row_count_pg == 2
    assert res.row_count_mssql == 2
    assert res.verdict == "MATCH", f"sample_diff={res.sample_diff} cs_pg={res.checksum_pg} cs_mssql={res.checksum_mssql}"
    # Sample diff hashes match
    assert all(s["match"] for s in res.sample_diff)


# ============================================================================
# Limited path: ROW_COUNT_MISMATCH
# ============================================================================

def test_limited_row_count_mismatch_when_pg_missing_rows():
    rows = [
        {"company_id": 1, "company_name": "A"},
        {"company_id": 2, "company_name": "B"},
    ]
    pg_conn = _make_pg_conn(
        rows_pg=[('["1"]', _hash_for(rows[0]))],  # only row 1 in PG
        aggregate="anything",
    )
    mssql_conn = _make_mssql_conn(rows)

    res = reconcile_table(pg_conn, mssql_conn, _company_meta(), ReconcileScope(kind="limited", limit=10))
    assert res.row_count_pg == 1
    assert res.row_count_mssql == 2
    assert res.verdict == "ROW_COUNT_MISMATCH"


# ============================================================================
# Limited path: SAMPLE_MISMATCH
# ============================================================================

def test_limited_sample_mismatch_when_hash_diverges():
    rows = [
        {"company_id": 1, "company_name": "Acme"},  # MSSQL truth
    ]
    # PG has row 1 but with a different hash (e.g. stale load)
    pg_conn = _make_pg_conn(
        rows_pg=[('["1"]', "fffffff" * 8)],  # 64-char garbage hash
        aggregate="garbage",
    )
    mssql_conn = _make_mssql_conn(rows)

    res = reconcile_table(pg_conn, mssql_conn, _company_meta(), ReconcileScope(kind="limited", limit=10))
    assert res.row_count_pg == 1
    assert res.row_count_mssql == 1
    assert res.verdict == "SAMPLE_MISMATCH"


# ============================================================================
# UNSUPPORTED_DELTA verdict
# ============================================================================

def test_delta_with_missing_checkpoint_column_unsupported():
    pg = MagicMock()
    mssql = MagicMock()
    scope = ReconcileScope(kind="delta", checkpoint_column="updated_at", checkpoint_value=datetime.now(timezone.utc))

    res = reconcile_table(pg, mssql, _company_meta(), scope)
    assert res.verdict == "UNSUPPORTED_DELTA"
    assert any("not in table_meta.columns" in n for n in res.notes)


def test_delta_for_day7_is_unsupported_even_with_column():
    """Day 7 explicitly defers full delta impl; verdict UNSUPPORTED_DELTA
    with a note pointing to Day 8."""
    meta = TableMeta(
        name="X", source_schema="s", source_year=None,
        columns=[
            ColumnMeta(name="id", pg_type="BIGINT", nullable=False),
            ColumnMeta(name="updated_at", pg_type="TIMESTAMPTZ", nullable=True),
        ],
        idempotency_key=["id"],
    )
    scope = ReconcileScope(kind="delta", checkpoint_column="updated_at", checkpoint_value=datetime.now(timezone.utc))
    res = reconcile_table(MagicMock(), MagicMock(), meta, scope)
    assert res.verdict == "UNSUPPORTED_DELTA"
    assert any("Day 8" in n for n in res.notes)


# ============================================================================
# Empty MSSQL set
# ============================================================================

def test_limited_empty_mssql_set_is_match_with_zero_rows():
    """MSSQL has no rows in the scoped window → row counts both 0, no
    sample diff, no checksum to mismatch → MATCH with notes."""
    pg_conn = _make_pg_conn(rows_pg=[], aggregate=None)
    mssql_conn = _make_mssql_conn([])

    res = reconcile_table(pg_conn, mssql_conn, _company_meta(), ReconcileScope(kind="limited", limit=10))
    assert res.row_count_pg == 0
    assert res.row_count_mssql == 0
    assert res.verdict == "MATCH"
    assert any("MSSQL scoped set is empty" in n for n in res.notes)


# ============================================================================
# Renderers
# ============================================================================

def test_render_markdown_smoke():
    res = TableReconcileResult(
        table_name="COMPANY", source_schema="wm", source_year=None,
        scope_kind="limited", scope_limit=1000,
        row_count_pg=2, row_count_mssql=2,
        checksum_pg="abc", checksum_mssql="abc",
        sample_diff=[
            {"source_pk": '["1"]', "hash_pg": "deadbeef", "hash_mssql": "deadbeef", "match": True},
            {"source_pk": '["2"]', "hash_pg": "1234", "hash_mssql": "5678", "match": False},
        ],
        verdict="SAMPLE_MISMATCH",
        notes=["one", "two"],
    )
    report = ReconcileReport(run_id="rid", mode="initial", tables=[res])
    md = render_markdown(report)
    assert "# Reconciliation report" in md
    assert "SAMPLE_MISMATCH" in md
    assert "one" in md and "two" in md
    assert "✅" in md or "❌" in md


def test_render_json_smoke():
    res = TableReconcileResult(
        table_name="COMPANY", source_schema="wm", source_year=None,
        scope_kind="limited", scope_limit=1000,
        row_count_pg=2, row_count_mssql=2,
        verdict="MATCH",
    )
    report = ReconcileReport(run_id="rid", mode="initial", tables=[res])
    payload = json.loads(render_json(report))
    assert payload["run_id"] == "rid"
    assert payload["overall_verdict"] == "MATCH"
    assert payload["tables"][0]["scope_kind"] == "limited"


def test_overall_verdict_picks_worst():
    r1 = TableReconcileResult(
        table_name="A", source_schema="s", source_year=None,
        scope_kind="limited", scope_limit=10,
        row_count_pg=0, row_count_mssql=0, verdict="MATCH",
    )
    r2 = TableReconcileResult(
        table_name="B", source_schema="s", source_year=None,
        scope_kind="limited", scope_limit=10,
        row_count_pg=10, row_count_mssql=11, verdict="ROW_COUNT_MISMATCH",
    )
    r3 = TableReconcileResult(
        table_name="C", source_schema="s", source_year=None,
        scope_kind="limited", scope_limit=10,
        row_count_pg=10, row_count_mssql=10, verdict="CHECKSUM_MISMATCH",
    )
    report = ReconcileReport(run_id="rid", mode="initial", tables=[r1, r2, r3])
    assert report.overall_verdict() == "CHECKSUM_MISMATCH"
