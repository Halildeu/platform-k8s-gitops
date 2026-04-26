"""Faz 16.3 Gün 7 — load_batch retry classification + LoadReject (iter-4 AGREE).

Tests verify:
  - bulk fail → per-row fallback
  - per-row NO_RETRY (constraint violation) → LoadReject populated, continue
  - per-row TRANSIENT → re-raised so the runner's retry loop picks it up
  - per-row CRITICAL → re-raised so the runner aborts
  - bulk-level CRITICAL → re-raised before per-row fallback runs
"""

from __future__ import annotations

from unittest.mock import MagicMock

import psycopg
import pytest

from etl_worker.load import LoadReject, LoadStats, load_batch
from etl_worker.transform import ColumnMeta, TableMeta


# ============================================================================
# Helpers — psycopg-shaped error with sqlstate
# ============================================================================

def _err(cls: type, sqlstate: str, msg: str = "boom") -> Exception:
    e = cls(msg)
    object.__setattr__(e, "sqlstate", sqlstate)
    return e


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


def _row(i: int, name: str = "Acme") -> dict:
    return {
        "company_id": i,
        "company_name": name,
        "source_schema": "workcube_mikrolink",
        "source_table": "COMPANY",
        "source_pk": f'["{i}"]',
        "content_hash": "deadbeef" * 8,
    }


def _make_conn():
    cur = MagicMock(name="cursor")
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.rowcount = 1

    tx = MagicMock(name="tx")
    tx.__enter__ = MagicMock(return_value=tx)
    tx.__exit__ = MagicMock(return_value=False)

    conn = MagicMock(name="conn")
    conn.cursor.return_value = cur
    conn.transaction.return_value = tx
    conn._cur = cur
    conn._tx = tx
    return conn


# ============================================================================
# Bulk-level paths
# ============================================================================

def test_load_batch_bulk_success(monkeypatch):
    conn = _make_conn()
    rows = [_row(1), _row(2), _row(3)]
    conn._cur.rowcount = 3

    stats = load_batch(conn, rows, _company_meta())
    assert isinstance(stats, LoadStats)
    assert stats.inserted == 3
    assert stats.rejected == 0
    assert stats.rejects == []
    assert stats.bulk_fallback is False


def test_load_batch_bulk_critical_raises_without_fallback():
    """A bulk-level CRITICAL error must NOT trigger per-row fallback —
    surface immediately so the runner can abort."""
    conn = _make_conn()
    # First execute (executemany) raises an undefined_table error.
    conn._cur.executemany.side_effect = _err(psycopg.errors.UndefinedTable, "42P01")

    with pytest.raises(psycopg.errors.UndefinedTable):
        load_batch(conn, [_row(1)], _company_meta())


# ============================================================================
# Per-row fallback paths
# ============================================================================

def test_load_batch_no_retry_per_row_produces_load_reject():
    """A per-row UniqueViolation must become a LoadReject (no run_id field)
    and the loop must continue to the next row."""
    conn = _make_conn()
    rows = [_row(1, "first"), _row(1, "duplicate"), _row(2, "third")]

    # Bulk fails with a deadlock (TRANSIENT) → per-row fallback.
    conn._cur.executemany.side_effect = _err(psycopg.errors.DeadlockDetected, "40P01")

    # Per-row execute order: row1 OK, row2 UniqueViolation, row3 OK.
    conn._cur.execute.side_effect = [
        None,
        _err(psycopg.errors.UniqueViolation, "23505", "duplicate key"),
        None,
    ]

    stats = load_batch(conn, rows, _company_meta())
    assert stats.bulk_fallback is True
    assert stats.rejected == 1
    assert len(stats.rejects) == 1
    lr = stats.rejects[0]
    assert isinstance(lr, LoadReject)
    assert lr.reject_reason == "LOAD_NO_RETRY"
    assert lr.severity == "ERROR"
    assert lr.pg_error_code == "23505"
    assert "duplicate key" in lr.pg_error_message
    assert lr.table_name == "COMPANY"
    assert lr.source_schema == "workcube_mikrolink"
    # Hard contract: no run_id on LoadReject (audit lifecycle owned by runner)
    assert not hasattr(lr, "run_id")


def test_load_batch_per_row_transient_reraises():
    """A per-row TRANSIENT must propagate so the runner's batch retry loop
    can apply backoff at the batch level. Eating the error here would mean
    the batch silently loses rows."""
    conn = _make_conn()
    conn._cur.executemany.side_effect = _err(psycopg.errors.DeadlockDetected, "40P01")
    conn._cur.execute.side_effect = _err(psycopg.errors.SerializationFailure, "40001")

    with pytest.raises(psycopg.errors.SerializationFailure):
        load_batch(conn, [_row(1)], _company_meta())


def test_load_batch_per_row_critical_reraises():
    conn = _make_conn()
    conn._cur.executemany.side_effect = _err(psycopg.errors.DeadlockDetected, "40P01")
    conn._cur.execute.side_effect = _err(psycopg.errors.DiskFull, "53100")

    with pytest.raises(psycopg.errors.DiskFull):
        load_batch(conn, [_row(1)], _company_meta())


def test_load_reject_raw_payload_default_off():
    """Raw payload must NOT be persisted by default (privacy)."""
    conn = _make_conn()
    conn._cur.executemany.side_effect = _err(psycopg.errors.DeadlockDetected, "40P01")
    conn._cur.execute.side_effect = _err(psycopg.errors.UniqueViolation, "23505")

    stats = load_batch(conn, [_row(1)], _company_meta())
    assert stats.rejects[0].raw_payload is None


def test_load_reject_raw_payload_opt_in():
    conn = _make_conn()
    conn._cur.executemany.side_effect = _err(psycopg.errors.DeadlockDetected, "40P01")
    conn._cur.execute.side_effect = _err(psycopg.errors.UniqueViolation, "23505")

    stats = load_batch(
        conn, [_row(1, "Acme")], _company_meta(),
        include_raw_payload=True,
    )
    assert stats.rejects[0].raw_payload is not None
    assert stats.rejects[0].raw_payload["company_name"] == "Acme"


def test_load_batch_empty_returns_zero_stats():
    conn = _make_conn()
    stats = load_batch(conn, [], _company_meta())
    assert stats.inserted == 0
    assert stats.rejects == []
    assert not conn._cur.executemany.called


def test_load_batch_mixed_per_row_results():
    """3 rows: row1 OK, row2 reject (NO_RETRY), row3 OK → stats.rejected=1
    and 2 successful inserts."""
    conn = _make_conn()
    conn._cur.executemany.side_effect = _err(psycopg.errors.DeadlockDetected, "40P01")
    conn._cur.execute.side_effect = [
        None,
        _err(psycopg.errors.NotNullViolation, "23502"),
        None,
    ]
    conn._cur.rowcount = 1

    stats = load_batch(conn, [_row(1), _row(2), _row(3)], _company_meta())
    assert stats.bulk_fallback is True
    assert stats.rejected == 1
    assert stats.inserted == 2  # 2 successful rows
    assert len(stats.rejects) == 1
    assert stats.rejects[0].pg_error_code == "23502"
