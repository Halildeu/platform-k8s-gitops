"""Faz 16.3 Gün 6 — Retry classifier + backoff tests (Codex iter-7).

Pure-Python tests; no live PG.
"""

from __future__ import annotations

import random
from unittest.mock import MagicMock

import psycopg
import pytest

from etl_worker.retry import (
    BackoffPolicy,
    RetryClass,
    ThresholdPolicy,
    classify_error,
    describe,
    is_critical,
    is_transient,
)


# ============================================================================
# Helpers
# ============================================================================

def _err(cls: type, sqlstate: str | None = None, msg: str = "boom") -> Exception:
    """Construct a psycopg-shaped error with a sqlstate attribute."""
    e = cls(msg) if cls is not Exception else Exception(msg)
    if sqlstate is not None:
        try:
            object.__setattr__(e, "sqlstate", sqlstate)
        except Exception:
            pass  # frozen exceptions; fall through
    return e


# ============================================================================
# classify_error — TRANSIENT bucket
# ============================================================================

def test_classify_serialization_failure_transient():
    e = _err(psycopg.errors.SerializationFailure, "40001")
    assert classify_error(e) == RetryClass.TRANSIENT


def test_classify_deadlock_transient():
    e = _err(psycopg.errors.DeadlockDetected, "40P01")
    assert classify_error(e) == RetryClass.TRANSIENT


def test_classify_connection_failure_transient():
    e = _err(psycopg.errors.ConnectionFailure, "08006")
    assert classify_error(e) == RetryClass.TRANSIENT


def test_classify_query_canceled_transient():
    e = _err(psycopg.errors.QueryCanceled, "57014")
    assert classify_error(e) == RetryClass.TRANSIENT


def test_classify_operational_error_no_sqlstate_transient():
    e = psycopg.OperationalError("network blip")
    assert is_transient(e) is True


# ============================================================================
# classify_error — NO_RETRY bucket
# ============================================================================

def test_classify_unique_violation_no_retry():
    e = _err(psycopg.errors.UniqueViolation, "23505")
    assert classify_error(e) == RetryClass.NO_RETRY


def test_classify_not_null_violation_no_retry():
    e = _err(psycopg.errors.NotNullViolation, "23502")
    assert classify_error(e) == RetryClass.NO_RETRY


def test_classify_check_violation_no_retry():
    e = _err(psycopg.errors.CheckViolation, "23514")
    assert classify_error(e) == RetryClass.NO_RETRY


def test_classify_string_truncation_no_retry():
    e = _err(psycopg.errors.StringDataRightTruncation, "22001")
    assert classify_error(e) == RetryClass.NO_RETRY


def test_classify_numeric_overflow_no_retry():
    e = _err(psycopg.errors.NumericValueOutOfRange, "22003")
    assert classify_error(e) == RetryClass.NO_RETRY


# ============================================================================
# classify_error — CRITICAL bucket
# ============================================================================

def test_classify_disk_full_critical():
    e = _err(psycopg.errors.DiskFull, "53100")
    assert classify_error(e) == RetryClass.CRITICAL
    assert is_critical(e) is True


def test_classify_oom_critical():
    e = _err(psycopg.errors.OutOfMemory, "53200")
    assert classify_error(e) == RetryClass.CRITICAL


def test_classify_undefined_table_critical():
    e = _err(psycopg.errors.UndefinedTable, "42P01")
    assert classify_error(e) == RetryClass.CRITICAL


def test_classify_undefined_column_critical():
    e = _err(psycopg.errors.UndefinedColumn, "42703")
    assert classify_error(e) == RetryClass.CRITICAL


def test_classify_insufficient_privilege_critical():
    e = _err(psycopg.errors.InsufficientPrivilege, "42501")
    assert classify_error(e) == RetryClass.CRITICAL


def test_classify_invalid_authorization_critical():
    e = psycopg.OperationalError("auth failed")
    object.__setattr__(e, "sqlstate", "28000")
    assert classify_error(e) == RetryClass.CRITICAL


# ============================================================================
# Class-level fallback (SQLSTATE class prefix)
# ============================================================================

def test_classify_unknown_22_class_no_retry():
    e = _err(psycopg.errors.Error, "22XYZ")  # unknown 22-class
    assert classify_error(e) == RetryClass.NO_RETRY


def test_classify_unknown_53_class_critical():
    e = _err(psycopg.errors.Error, "53999")
    assert classify_error(e) == RetryClass.CRITICAL


def test_classify_unknown_08_class_transient():
    e = _err(psycopg.errors.Error, "08ZZZ")
    assert classify_error(e) == RetryClass.TRANSIENT


# ============================================================================
# describe()
# ============================================================================

def test_describe_includes_classification_and_sqlstate():
    e = _err(psycopg.errors.SerializationFailure, "40001", "tx conflict")
    d = describe(e)
    assert d["sqlstate"] == "40001"
    assert d["classification"] == "TRANSIENT"
    assert "tx conflict" in d["message"]
    assert d["type"] == "SerializationFailure"


# ============================================================================
# BackoffPolicy
# ============================================================================

def test_backoff_zero_attempt_returns_zero():
    pol = BackoffPolicy(max_attempts=5, base_seconds=0.5, cap_seconds=10)
    assert pol.delay_for(0) == 0.0


def test_backoff_capped(monkeypatch):
    """Delay never exceeds cap_seconds even at high attempt counts."""
    pol = BackoffPolicy(max_attempts=10, base_seconds=1.0, cap_seconds=5.0)
    monkeypatch.setattr(random, "uniform", lambda lo, hi: hi)  # always max
    for attempt in range(1, 12):
        assert pol.delay_for(attempt) <= pol.cap_seconds + 1e-9


def test_backoff_jitter_within_window(monkeypatch):
    """Full-jitter: delay is in [0, min(cap, base*2^attempt)]."""
    pol = BackoffPolicy(base_seconds=0.5, cap_seconds=30.0)
    captured: list[tuple[float, float]] = []

    def fake_uniform(lo: float, hi: float) -> float:
        captured.append((lo, hi))
        return (lo + hi) / 2

    monkeypatch.setattr(random, "uniform", fake_uniform)
    pol.delay_for(3)  # 0.5 * 8 = 4.0 → upper=4.0
    assert captured[-1] == (0.0, 4.0)


def test_backoff_sleep_calls_time_sleep(monkeypatch):
    pol = BackoffPolicy(base_seconds=0.5, cap_seconds=30.0)
    monkeypatch.setattr(random, "uniform", lambda lo, hi: 0.123)
    sleeps: list[float] = []
    monkeypatch.setattr("etl_worker.retry.time.sleep", lambda s: sleeps.append(s))
    pol.sleep_for(2)
    assert sleeps == [0.123]


# ============================================================================
# ThresholdPolicy — mode-aware
# ============================================================================

def test_threshold_initial_within_ratio():
    p = ThresholdPolicy(mode="initial", max_reject_ratio=0.05)
    assert p.should_abort(rejected=4, processed=100) is False


def test_threshold_initial_breach():
    p = ThresholdPolicy(mode="initial", max_reject_ratio=0.05)
    assert p.should_abort(rejected=6, processed=100) is True


def test_threshold_final_delta_strict():
    """final-delta: any reject is fatal."""
    p = ThresholdPolicy(mode="final-delta", max_reject_ratio=0.0)
    assert p.should_abort(rejected=1, processed=10000) is True
    assert p.should_abort(rejected=0, processed=10000) is False


def test_threshold_dry_run_never_aborts():
    p = ThresholdPolicy(mode="dry-run", max_reject_ratio=0.0)
    assert p.should_abort(rejected=999_999, processed=1) is False


def test_threshold_zero_processed():
    """Avoid divide-by-zero when nothing has been processed yet."""
    p = ThresholdPolicy(mode="initial", max_reject_ratio=0.0)
    assert p.should_abort(rejected=0, processed=0) is False
