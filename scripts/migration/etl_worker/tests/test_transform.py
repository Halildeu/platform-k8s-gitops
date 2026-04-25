"""Faz 16.3 Gün 5 — Transform unit tests (Codex iter-6 AGREE).

Coverage:
- content_hash deterministic
- Decimal canonicalization (trailing zero strip)
- Datetime UTC normalize
- UUID validate
- NULL/length/type reject preflight
- source_pk canonical JSON array
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import uuid

import pytest

from etl_worker.transform import (
    ColumnMeta,
    TableMeta,
    cast_value,
    content_hash,
    make_source_pk,
    normalize_for_hash,
    transform_row,
)


# ============================================================================
# normalize_for_hash + content_hash
# ============================================================================

def test_content_hash_deterministic():
    """Same input → same hash (sorted keys, normalized values)."""
    row1 = {"a": 1, "b": "hello", "c": Decimal("12.34")}
    row2 = {"c": Decimal("12.34"), "b": "hello", "a": 1}
    assert content_hash(row1) == content_hash(row2)


def test_content_hash_decimal_normalization():
    """Decimal trailing zero stripped (Codex iter-6: format(v.normalize(), 'f'))."""
    h1 = content_hash({"price": Decimal("12.340")})
    h2 = content_hash({"price": Decimal("12.34")})
    assert h1 == h2  # 12.340 normalize to 12.34


def test_content_hash_datetime_utc():
    """Naive datetime → UTC ISO 8601."""
    naive = datetime(2026, 4, 25, 12, 0, 0)
    aware_utc = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
    assert content_hash({"created": naive}) == content_hash({"created": aware_utc})


def test_normalize_for_hash_uuid():
    u = uuid.uuid4()
    assert normalize_for_hash(u) == str(u)


def test_normalize_for_hash_bytes():
    b = b"\x00\x01\x02"
    assert normalize_for_hash(b) == "000102"


# ============================================================================
# source_pk canonical JSON
# ============================================================================

def test_source_pk_single_column():
    row = {"COMPANY_ID": 12345}
    pk = make_source_pk(row, ["COMPANY_ID"])
    assert pk == '["12345"]'


def test_source_pk_composite():
    row = {"COMPANY_ID": 12345, "COMPANYP_ID": 678}
    pk = make_source_pk(row, ["COMPANY_ID", "COMPANYP_ID"])
    assert pk == '["12345","678"]'


def test_source_pk_handles_none():
    row = {"COMPANY_ID": None}
    pk = make_source_pk(row, ["COMPANY_ID"])
    assert pk == '[null]'


# ============================================================================
# cast_value
# ============================================================================

def test_cast_int():
    assert cast_value("42", "INTEGER", "id") == (42, None)
    assert cast_value(42, "BIGINT", "id") == (42, None)


def test_cast_decimal():
    v, r = cast_value("12.345", "NUMERIC", "amount")
    assert v == Decimal("12.345")
    assert r is None


def test_cast_decimal_invalid():
    v, r = cast_value("not-a-number", "NUMERIC", "amount")
    assert v is None
    assert r and r.startswith("TYPE_CAST_FAIL")


def test_cast_datetime_naive_utc_attach():
    naive = datetime(2026, 4, 25, 12, 0, 0)
    v, r = cast_value(naive, "TIMESTAMPTZ", "created")
    assert v.tzinfo == timezone.utc


def test_cast_uuid():
    s = "12345678-1234-5678-1234-567812345678"
    v, r = cast_value(s, "UUID", "guid")
    assert v == uuid.UUID(s)
    assert r is None


def test_cast_uuid_invalid():
    v, r = cast_value("not-a-uuid", "UUID", "guid")
    assert v is None
    assert r and r.startswith("TYPE_CAST_FAIL")


def test_cast_boolean():
    assert cast_value(True, "BOOLEAN", "flag") == (True, None)
    assert cast_value(1, "BOOLEAN", "flag") == (True, None)
    assert cast_value("true", "BOOLEAN", "flag") == (True, None)
    assert cast_value("false", "BOOLEAN", "flag") == (False, None)


def test_cast_null_passthrough():
    assert cast_value(None, "INTEGER", "x") == (None, None)
    assert cast_value("", "VARCHAR(100)", "x") == (None, None)


# ============================================================================
# transform_row (end-to-end)
# ============================================================================

def _company_meta() -> TableMeta:
    return TableMeta(
        name="COMPANY",
        source_schema="workcube_mikrolink",
        source_year=None,
        columns=[
            ColumnMeta(name="company_id", pg_type="BIGINT", nullable=False),
            ColumnMeta(name="company_name", pg_type="VARCHAR(255)", nullable=False, max_length=255),
            ColumnMeta(name="created_at", pg_type="TIMESTAMPTZ", nullable=True),
        ],
        idempotency_key=["company_id"],
    )


def test_transform_row_success():
    raw = {
        "company_id": 12345,
        "company_name": "Acme Corp",
        "created_at": datetime(2026, 4, 25, 12, 0, 0),
    }
    result = transform_row(raw, _company_meta())
    assert result.reject_reason is None
    assert result.typed_row["company_id"] == 12345
    assert result.typed_row["company_name"] == "Acme Corp"
    assert result.typed_row["source_schema"] == "workcube_mikrolink"
    assert result.typed_row["source_table"] == "COMPANY"
    assert result.source_pk == '["12345"]'
    assert len(result.content_hash) == 64  # SHA-256 hex


def test_transform_row_not_null_violation():
    raw = {"company_id": None, "company_name": "Acme"}
    result = transform_row(raw, _company_meta())
    assert result.reject_reason == "NOT_NULL_VIOLATION"
    assert result.reject_column == "company_id"


def test_transform_row_length_overflow():
    long_name = "X" * 300
    raw = {"company_id": 1, "company_name": long_name}
    result = transform_row(raw, _company_meta())
    assert result.reject_reason == "LENGTH_OVERFLOW"
    assert result.reject_column == "company_name"


def test_transform_row_idempotency_same_data_same_hash():
    raw = {"company_id": 1, "company_name": "Acme", "created_at": datetime(2026, 4, 25)}
    r1 = transform_row(raw, _company_meta())
    r2 = transform_row(raw, _company_meta())
    assert r1.content_hash == r2.content_hash


def test_transform_row_idempotency_different_data_different_hash():
    raw1 = {"company_id": 1, "company_name": "Acme", "created_at": datetime(2026, 4, 25)}
    raw2 = {"company_id": 1, "company_name": "Beta", "created_at": datetime(2026, 4, 25)}
    r1 = transform_row(raw1, _company_meta())
    r2 = transform_row(raw2, _company_meta())
    assert r1.content_hash != r2.content_hash
