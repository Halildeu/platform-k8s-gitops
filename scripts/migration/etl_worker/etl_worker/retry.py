"""Faz 16.3 Gün 6 — Retry classifier (Codex iter-7 REVISE).

Three-bucket classifier for psycopg errors:
  - TRANSIENT  → exponential backoff w/ jitter, retry up to N times
  - NO_RETRY   → row-level reject (constraint/data violation)
  - CRITICAL   → abort the entire run (disk, OOM, schema mismatch)

Threshold (mode-aware):
  - initial      → continue past per-row failures up to max_reject_ratio
  - final-delta  → strict: any TRANSIENT exhaustion or threshold breach aborts
  - dry-run      → continue + write-only-to-reject (run never aborts)
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import psycopg

log = logging.getLogger(__name__)


# ============================================================================
# Classification
# ============================================================================

class RetryClass(str, Enum):
    TRANSIENT = "TRANSIENT"
    NO_RETRY = "NO_RETRY"
    CRITICAL = "CRITICAL"


# psycopg SQLSTATE class prefixes / codes we care about.
# https://www.postgresql.org/docs/current/errcodes-appendix.html
_TRANSIENT_SQLSTATES = {
    "40001",  # serialization_failure
    "40P01",  # deadlock_detected
    "08000",  # connection_exception
    "08003",  # connection_does_not_exist
    "08006",  # connection_failure
    "08001",  # sqlclient_unable_to_establish_connection
    "08004",  # sqlserver_rejected_establishment
    "08007",  # transaction_resolution_unknown
    "57P03",  # cannot_connect_now
    "57014",  # query_canceled (timeout)
    "55006",  # object_in_use
    "55P03",  # lock_not_available
}

_NO_RETRY_SQLSTATES = {
    "23502",  # not_null_violation
    "23503",  # foreign_key_violation
    "23505",  # unique_violation
    "23514",  # check_violation
    "22001",  # string_data_right_truncation
    "22003",  # numeric_value_out_of_range
    "22007",  # invalid_datetime_format
    "22008",  # datetime_field_overflow
    "22P02",  # invalid_text_representation
    "22P03",  # invalid_binary_representation
    "22P05",  # untranslatable_character
    "22023",  # invalid_parameter_value
    "22025",  # invalid_escape_sequence
    "22026",  # string_data_length_mismatch
}

_CRITICAL_SQLSTATES = {
    "53100",  # disk_full
    "53200",  # out_of_memory
    "53300",  # too_many_connections
    "53400",  # configuration_limit_exceeded
    "42P01",  # undefined_table
    "42703",  # undefined_column
    "42P07",  # duplicate_table (schema mismatch)
    "42501",  # insufficient_privilege
    "28000",  # invalid_authorization_specification
    "28P01",  # invalid_password
    "3D000",  # invalid_catalog_name (db not found)
    "3F000",  # invalid_schema_name
    "58030",  # io_error
    "58P01",  # undefined_file
    "58P02",  # duplicate_file
    "XX000",  # internal_error
    "XX001",  # data_corrupted
    "XX002",  # index_corrupted
}


def classify_error(exc: BaseException) -> RetryClass:
    """Map psycopg exception → RetryClass.

    Falls back to TRANSIENT for raw psycopg.OperationalError (network timeouts
    occasionally surface without a SQLSTATE) and NO_RETRY for everything else
    that lacks a SQLSTATE — safest default for unknown data errors.
    """
    sqlstate = _sqlstate_of(exc)
    if sqlstate is not None:
        if sqlstate in _CRITICAL_SQLSTATES:
            return RetryClass.CRITICAL
        if sqlstate in _TRANSIENT_SQLSTATES:
            return RetryClass.TRANSIENT
        if sqlstate in _NO_RETRY_SQLSTATES:
            return RetryClass.NO_RETRY
        # Class-level fallbacks (first 2 chars of SQLSTATE)
        cls = sqlstate[:2]
        if cls in {"08", "57", "55"}:
            return RetryClass.TRANSIENT
        if cls in {"22", "23"}:
            return RetryClass.NO_RETRY
        if cls in {"53", "58", "XX", "3D", "3F", "28", "42"}:
            return RetryClass.CRITICAL
        return RetryClass.NO_RETRY

    # No SQLSTATE: typed fallbacks.
    if isinstance(exc, psycopg.OperationalError):
        return RetryClass.TRANSIENT
    if isinstance(exc, psycopg.IntegrityError):
        return RetryClass.NO_RETRY
    if isinstance(exc, psycopg.DataError):
        return RetryClass.NO_RETRY
    if isinstance(exc, psycopg.ProgrammingError):
        return RetryClass.CRITICAL
    if isinstance(exc, psycopg.InternalError):
        return RetryClass.CRITICAL

    # Generic Python errors that surface from network paths
    name = type(exc).__name__.lower()
    if "timeout" in name or "connection" in name:
        return RetryClass.TRANSIENT

    return RetryClass.NO_RETRY


def _sqlstate_of(exc: BaseException) -> str | None:
    """Pull SQLSTATE from a psycopg error (sqlstate attr or diag.sqlstate)."""
    state = getattr(exc, "sqlstate", None)
    if state:
        return state
    diag = getattr(exc, "diag", None)
    if diag is not None:
        state = getattr(diag, "sqlstate", None)
        if state:
            return state
    return None


# ============================================================================
# Backoff policy
# ============================================================================

@dataclass
class BackoffPolicy:
    """Exponential backoff with full jitter (AWS recipe)."""

    max_attempts: int = 5
    base_seconds: float = 0.5
    cap_seconds: float = 30.0

    def delay_for(self, attempt: int) -> float:
        """attempt is 1-indexed (first retry = attempt 1)."""
        if attempt <= 0:
            return 0.0
        # Full jitter: random.uniform(0, min(cap, base * 2**attempt))
        upper = min(self.cap_seconds, self.base_seconds * (2 ** attempt))
        return random.uniform(0.0, upper)

    def sleep_for(self, attempt: int) -> float:
        delay = self.delay_for(attempt)
        if delay > 0:
            time.sleep(delay)
        return delay


# ============================================================================
# Threshold (mode-aware)
# ============================================================================

@dataclass
class ThresholdPolicy:
    """Per-mode rejection tolerance.

    Codex iter-7:
      - initial:      max_reject_ratio default 0.0; runner respects override.
      - final-delta:  strict — abort on first threshold breach.
      - dry-run:      continue forever; rejects logged + written to audit.
    """

    mode: str
    max_reject_ratio: float

    def should_abort(self, rejected: int, processed: int) -> bool:
        if self.mode == "dry-run":
            return False
        if processed <= 0:
            return False
        ratio = rejected / processed
        if self.mode == "final-delta":
            return ratio > 0.0  # strict
        return ratio > self.max_reject_ratio


# ============================================================================
# Convenience helper for callers
# ============================================================================

def is_transient(exc: BaseException) -> bool:
    return classify_error(exc) == RetryClass.TRANSIENT


def is_critical(exc: BaseException) -> bool:
    return classify_error(exc) == RetryClass.CRITICAL


def describe(exc: BaseException) -> dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "sqlstate": _sqlstate_of(exc),
        "message": str(exc)[:500],
        "classification": classify_error(exc).value,
    }
