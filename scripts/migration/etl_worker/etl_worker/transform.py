"""Faz 16.3 Gün 5 — Transform pipeline (Codex iter-6 AGREE).

Pipeline:
- Contract-driven type cast (manifest column types)
- NULL normalization (empty string → None for nullable, fail for NOT NULL)
- Encoding/BOM strip
- Decimal canonicalization (format(v.normalize(), 'f'))
- Datetime UTC normalize (naive → UTC attach)
- UUID validate
- content_hash SHA-256(canonical JSON)
- Reject preflight (type/null/length fail → reject_reason)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass
class TransformResult:
    """Transform output."""

    typed_row: dict[str, Any] | None  # None if reject
    content_hash: str | None
    source_pk: str | None  # canonical JSON array string
    reject_reason: str | None  # None if success
    reject_column: str | None
    reject_value: str | None


# ============================================================================
# Type casting
# ============================================================================

def cast_value(raw: Any, target_type: str, column_name: str) -> tuple[Any, str | None]:
    """Cast raw value to target PG type. Returns (typed, reject_reason).

    target_type: PG type from V16 DDL (VARCHAR, NUMERIC, TIMESTAMPTZ, BOOLEAN, UUID, INTEGER, BIGINT, etc.)
    """
    if raw is None or raw == "":
        return None, None  # NULL handled by caller (NOT NULL check separate)

    target_upper = target_type.upper().split("(")[0]

    try:
        if target_upper in {"VARCHAR", "TEXT", "CHAR", "CITEXT"}:
            s = str(raw)
            # Strip BOM if present
            if s.startswith("﻿"):
                s = s[1:]
            return s, None

        if target_upper in {"INTEGER", "BIGINT", "SMALLINT"}:
            if isinstance(raw, bool):
                return int(raw), None
            return int(raw), None

        if target_upper == "NUMERIC":
            if isinstance(raw, Decimal):
                return raw, None
            return Decimal(str(raw)), None

        if target_upper in {"DOUBLE PRECISION", "REAL"}:
            return float(raw), None

        if target_upper == "BOOLEAN":
            if isinstance(raw, bool):
                return raw, None
            if isinstance(raw, int):
                return bool(raw), None
            if isinstance(raw, str):
                return raw.lower() in {"true", "1", "yes", "y"}, None
            return bool(raw), None

        if target_upper == "TIMESTAMPTZ":
            if isinstance(raw, datetime):
                # Naive datetime → UTC attach (Codex iter-6: contract assumption)
                if raw.tzinfo is None:
                    return raw.replace(tzinfo=timezone.utc), None
                return raw, None
            if isinstance(raw, str):
                # ISO 8601 parse
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt, None
            return None, "TIMESTAMPTZ_PARSE_FAIL"

        if target_upper == "DATE":
            if isinstance(raw, date) and not isinstance(raw, datetime):
                return raw, None
            if isinstance(raw, datetime):
                return raw.date(), None
            return date.fromisoformat(str(raw)), None

        if target_upper == "UUID":
            return uuid.UUID(str(raw)), None

        if target_upper == "BYTEA":
            if isinstance(raw, bytes):
                return raw, None
            if isinstance(raw, str):
                return raw.encode("utf-8"), None
            return None, "BYTEA_CAST_FAIL"

        # Unknown — fallback to string
        return str(raw), None

    except (ValueError, InvalidOperation, TypeError) as e:
        return None, f"TYPE_CAST_FAIL:{type(e).__name__}"


# ============================================================================
# Normalization for content_hash
# ============================================================================

def normalize_for_hash(v: Any) -> Any:
    """Codex iter-6: typed semantic hash with canonical representation."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        # Codex iter-6: format(v.normalize(), 'f') — trailing zero strip
        return format(v.normalize(), "f")
    if isinstance(v, datetime):
        # UTC ISO 8601 (Codex iter-6)
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, bytes):
        return v.hex()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


def content_hash(typed_row: dict[str, Any]) -> str:
    """Deterministic SHA-256 hash of typed row."""
    normalized = {k: normalize_for_hash(v) for k, v in sorted(typed_row.items())}
    payload = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ============================================================================
# source_pk canonical JSON array (Codex iter-6)
# ============================================================================

def make_source_pk(row: dict[str, Any], idempotency_key: list[str]) -> str:
    """Returns canonical JSON array string of business PK values.

    Single-column PK: '["12345"]'
    Composite PK: '["12345","678"]'

    Delimiter-based template (e.g., "12345|678") riskli (delimiter çakışması).
    JSON array tüm tipler için güvenli.
    """
    pk_values: list[str | None] = []
    for col in idempotency_key:
        v = row.get(col)
        if v is None:
            pk_values.append(None)
        else:
            pk_values.append(str(v))
    return json.dumps(pk_values, ensure_ascii=False, separators=(",", ":"))


# ============================================================================
# Main transform entrypoint
# ============================================================================

@dataclass
class ColumnMeta:
    """V16 DDL column metadata (manifest + generator output)."""

    name: str
    pg_type: str  # VARCHAR(100), NUMERIC, TIMESTAMPTZ, etc.
    nullable: bool = True
    max_length: int | None = None  # for VARCHAR


@dataclass
class TableMeta:
    """Table-level transform context."""

    name: str
    source_schema: str
    source_year: int | None
    columns: list[ColumnMeta]
    idempotency_key: list[str]


def transform_row(raw_row: dict[str, Any], table_meta: TableMeta) -> TransformResult:
    """Main transform: raw_row (pyodbc dict) → typed_row + content_hash + reject."""
    typed: dict[str, Any] = {}

    for col in table_meta.columns:
        raw = raw_row.get(col.name)

        # NULL check (NOT NULL columns)
        if raw is None or raw == "":
            if not col.nullable:
                return TransformResult(
                    typed_row=None,
                    content_hash=None,
                    source_pk=None,
                    reject_reason="NOT_NULL_VIOLATION",
                    reject_column=col.name,
                    reject_value=str(raw),
                )
            typed[col.name] = None
            continue

        # Type cast
        casted, reject = cast_value(raw, col.pg_type, col.name)
        if reject:
            return TransformResult(
                typed_row=None,
                content_hash=None,
                source_pk=None,
                reject_reason=reject,
                reject_column=col.name,
                reject_value=str(raw)[:200],
            )

        # Length check (VARCHAR(N) overflow preflight)
        if col.max_length and isinstance(casted, str) and len(casted) > col.max_length:
            return TransformResult(
                typed_row=None,
                content_hash=None,
                source_pk=None,
                reject_reason="LENGTH_OVERFLOW",
                reject_column=col.name,
                reject_value=f"len={len(casted)} > max={col.max_length}",
            )

        typed[col.name] = casted

    # Audit columns
    typed["source_schema"] = table_meta.source_schema
    if table_meta.source_year is not None:
        typed["source_year"] = table_meta.source_year
    typed["source_table"] = table_meta.name

    # Build source_pk + content_hash
    source_pk = make_source_pk(raw_row, table_meta.idempotency_key)
    chash = content_hash(typed)

    typed["source_pk"] = source_pk
    typed["content_hash"] = chash

    return TransformResult(
        typed_row=typed,
        content_hash=chash,
        source_pk=source_pk,
        reject_reason=None,
        reject_column=None,
        reject_value=None,
    )
