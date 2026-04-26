"""Faz 16.3 Gün 7 — default_mssql_extract tests (Codex iter-6 absorb).

Verifies the production extract path that runner.run_orchestrator() uses
when no custom extract_fn is provided. Ensures:
  - SELECT statement enumerates manifest columns + idempotency_key cols
    (deduplicated, manifest order preserved)
  - ORDER BY uses idempotency_key cols
  - OFFSET 0 ROWS FETCH NEXT N ROWS ONLY when limit is provided
  - last_pk continuation logs a warning but doesn't break (Day 7 stub)
  - Empty manifest columns raises (defense in depth — _load_manifest also fails)
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from etl_worker.runner import default_mssql_extract
from etl_worker.transform import ColumnMeta, TableMeta


def _company_meta() -> TableMeta:
    return TableMeta(
        name="COMPANY",
        source_schema="workcube_mikrolink",
        source_year=None,
        columns=[
            ColumnMeta(name="company_id", pg_type="INTEGER", nullable=False),
            ColumnMeta(name="company_name", pg_type="VARCHAR(150)", nullable=True),
        ],
        idempotency_key=["company_id"],
    )


def _composite_meta() -> TableMeta:
    return TableMeta(
        name="EMPLOYEES_PUANTAJ_ROWS",
        source_schema="workcube_mikrolink",
        source_year=None,
        columns=[
            ColumnMeta(name="puantaj_id", pg_type="INTEGER", nullable=False),
            ColumnMeta(name="row_id", pg_type="INTEGER", nullable=False),
            ColumnMeta(name="value", pg_type="NUMERIC", nullable=True),
        ],
        idempotency_key=["puantaj_id", "row_id"],
    )


def _make_mssql(rows: list[tuple]) -> MagicMock:
    cur = MagicMock()
    cur.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn._cur = cur
    return conn


# ============================================================================
# Query shape
# ============================================================================

def test_extract_query_enumerates_columns_and_orders_by_pk():
    conn = _make_mssql([(1, "A"), (2, "B")])
    list(default_mssql_extract(conn, _company_meta(), last_pk=None, limit=10))

    sql = conn._cur.execute.call_args.args[0]
    assert "SELECT company_id, company_name FROM workcube_mikrolink.COMPANY" in sql
    assert "ORDER BY company_id" in sql
    assert "OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY" in sql


def test_extract_query_omits_fetch_when_limit_none():
    conn = _make_mssql([])
    list(default_mssql_extract(conn, _company_meta(), last_pk=None, limit=None))
    sql = conn._cur.execute.call_args.args[0]
    assert "OFFSET 0 ROWS" in sql
    assert "FETCH NEXT" not in sql


def test_extract_query_composite_pk_orders_by_all_keys():
    conn = _make_mssql([])
    list(default_mssql_extract(conn, _composite_meta(), last_pk=None, limit=5))
    sql = conn._cur.execute.call_args.args[0]
    assert "ORDER BY puantaj_id, row_id" in sql


def test_extract_dedupes_pk_cols_already_in_columns():
    """If the manifest declares company_id as a column AND idempotency_key,
    the SELECT list should not duplicate it."""
    conn = _make_mssql([])
    list(default_mssql_extract(conn, _company_meta(), last_pk=None, limit=1))
    sql = conn._cur.execute.call_args.args[0]
    # company_id appears exactly once in the SELECT clause
    select_clause = sql.split(" FROM ")[0]
    assert select_clause.count("company_id") == 1


# ============================================================================
# Row → dict mapping
# ============================================================================

def test_extract_yields_dict_batch_keyed_by_column_name():
    rows = [(1, "Acme"), (2, "Beta")]
    conn = _make_mssql(rows)
    batches = list(default_mssql_extract(conn, _company_meta(), last_pk=None, limit=10))
    assert len(batches) == 1
    batch = batches[0]
    assert batch == [
        {"company_id": 1, "company_name": "Acme"},
        {"company_id": 2, "company_name": "Beta"},
    ]


def test_extract_empty_yields_no_batch():
    conn = _make_mssql([])
    batches = list(default_mssql_extract(conn, _company_meta(), last_pk=None, limit=10))
    assert batches == []


# ============================================================================
# Edge cases
# ============================================================================

def test_extract_empty_columns_raises_runtime_error():
    """Defense in depth — _load_manifest fails first, but if a caller bypasses
    that path the extractor must refuse to send `SELECT  FROM ...`."""
    meta = TableMeta(
        name="X", source_schema="s", source_year=None,
        columns=[], idempotency_key=["id"],
    )
    with pytest.raises(RuntimeError):
        list(default_mssql_extract(_make_mssql([]), meta, last_pk=None, limit=10))


def test_extract_last_pk_warning_then_restart(caplog):
    conn = _make_mssql([])
    with caplog.at_level(logging.WARNING, logger="etl_worker.runner"):
        list(default_mssql_extract(conn, _company_meta(), last_pk='["42"]', limit=10))
    assert any("last_pk_unsupported_in_day7" in r.message for r in caplog.records)
