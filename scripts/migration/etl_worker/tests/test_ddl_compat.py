"""Faz 16.3 Gün 7 iter-7 — DDL compatibility test (Codex iter-7 ek test).

Asserts that every column build_upsert_sql() emits is present in the V16
canonical table DDL, and that the conflict key has a matching UNIQUE
constraint. Without this gate, the runner ships SQL that hits PG with
`undefined_column` (42703) at the first batch — exactly the crash Codex
iter-7 caught before merge.

The test parses sql/migration/V16__reports.sql with a thin regex-based
DDL reader (no live PG required), so it runs in any unit test
environment.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from etl_worker.load import build_upsert_sql
from etl_worker.transform import ColumnMeta, TableMeta


REPO_ROOT = Path(__file__).resolve().parents[4]
V16_PATH = REPO_ROOT / "sql" / "migration" / "V16__reports.sql"


# ============================================================================
# Light DDL parser (regex-based, sufficient for canonical CREATE TABLE blocks)
# ============================================================================

_TABLE_HDR_RE = re.compile(
    r"CREATE TABLE workcube_mikrolink\.(\w+) \(",
)


def _read_v16() -> str:
    if not V16_PATH.exists():
        pytest.skip(f"V16 DDL not found at {V16_PATH}; run from repo root")
    return V16_PATH.read_text(encoding="utf-8")


def _table_columns(ddl_text: str, table_name: str) -> set[str]:
    """Return the set of column names declared in `workcube_mikrolink.<table>`.

    Stops at the first ');' line. Comments and PRIMARY KEY / UNIQUE clauses
    are skipped.
    """
    needle = f"CREATE TABLE workcube_mikrolink.{table_name.lower()} ("
    start = ddl_text.find(needle)
    if start < 0:
        raise AssertionError(f"V16 DDL has no CREATE TABLE for {table_name!r}")
    end = ddl_text.find("\n);", start)
    if end < 0:
        raise AssertionError(f"V16 DDL CREATE TABLE for {table_name!r} not closed")
    block = ddl_text[start:end]
    cols: set[str] = set()
    for raw_line in block.splitlines()[1:]:  # skip header
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        if line.startswith(("PRIMARY KEY", "UNIQUE", "CONSTRAINT", "CHECK")):
            continue
        # column definition: `name TYPE ...`
        token = line.split()[0].strip(",").strip('"')
        if token:
            cols.add(token.lower())
    return cols


def _has_unique_lineage_constraint(ddl_text: str, table_name: str) -> bool:
    """Either an inline `UNIQUE (source_schema, source_table, source_pk)` or
    a separate `CREATE UNIQUE INDEX ...` would satisfy the conflict key."""
    needle = f"CREATE TABLE workcube_mikrolink.{table_name.lower()} ("
    start = ddl_text.find(needle)
    if start < 0:
        return False
    end = ddl_text.find("\n);", start)
    if end < 0:
        return False
    block = ddl_text[start:end]
    if re.search(
        r"UNIQUE\s*\(\s*source_schema\s*,\s*source_table\s*,\s*source_pk",
        block,
    ):
        return True
    # Fallback: a CREATE UNIQUE INDEX over the same columns.
    pattern = (
        rf"CREATE UNIQUE INDEX[^;]*ON workcube_mikrolink\.{table_name.lower()} "
        r"\(\s*source_schema\s*,\s*source_table\s*,\s*source_pk"
    )
    return bool(re.search(pattern, ddl_text))


# ============================================================================
# Helpers
# ============================================================================

def _company_meta() -> TableMeta:
    """Mirrors the column names actually in V16 DDL for `company`. Test
    intentionally exercises the real ETL columns (not synthetic ones) so
    DDL compat asserts the live load path."""
    return TableMeta(
        name="COMPANY",
        source_schema="workcube_mikrolink",
        source_year=None,
        columns=[
            ColumnMeta(name="company_id", pg_type="INTEGER", nullable=False),
            ColumnMeta(name="nickname", pg_type="VARCHAR(150)", nullable=True, max_length=150),
            ColumnMeta(name="fullname", pg_type="VARCHAR(250)", nullable=True, max_length=250),
        ],
        idempotency_key=["company_id"],
    )


def _branch_meta() -> TableMeta:
    """Mirrors the column names actually in V16 DDL for `branch`."""
    return TableMeta(
        name="BRANCH",
        source_schema="workcube_mikrolink",
        source_year=None,
        columns=[
            ColumnMeta(name="branch_id", pg_type="INTEGER", nullable=False),
            ColumnMeta(name="branch_name", pg_type="VARCHAR(50)", nullable=False, max_length=50),
        ],
        idempotency_key=["branch_id"],
    )


def _extract_insert_cols(sql_obj) -> list[str]:
    """Extract column names from `INSERT INTO ... (col, col, col) VALUES (...)` ."""
    rendered = sql_obj.as_string(None)
    m = re.search(r"INSERT INTO[^()]*\(([^)]+)\) VALUES", rendered)
    assert m, f"could not find INSERT column list in: {rendered[:200]}"
    return [c.strip().strip('"').lower() for c in m.group(1).split(",")]


# ============================================================================
# Tests
# ============================================================================

@pytest.mark.parametrize("meta_factory", [_company_meta, _branch_meta])
def test_upsert_sql_columns_exist_in_v16_ddl(meta_factory):
    """Every column build_upsert_sql() inserts must be a real column in V16
    DDL. Otherwise the first load_batch hits `undefined_column` 42703."""
    meta = meta_factory()
    ddl = _read_v16()
    table_cols = _table_columns(ddl, meta.name)

    sql = build_upsert_sql(meta)
    insert_cols = _extract_insert_cols(sql)

    missing = [c for c in insert_cols if c not in table_cols]
    assert not missing, (
        f"build_upsert_sql({meta.name}) inserts columns NOT in V16 DDL: "
        f"{missing}\nDDL columns: {sorted(table_cols)}"
    )


@pytest.mark.parametrize("table_name", ["COMPANY", "BRANCH"])
def test_v16_ddl_has_audit_lineage_columns(table_name):
    ddl = _read_v16()
    cols = _table_columns(ddl, table_name)
    for required in ("source_schema", "source_table", "source_pk", "content_hash"):
        assert required in cols, (
            f"V16 DDL for {table_name} missing audit lineage column "
            f"`{required}`. ETL load_batch will fail with undefined_column."
        )


def test_v17_canonical_tables_match_v16_ddl():
    """Codex iter-9 PR-blocker: V17 DO LOOP iterates a hard-coded
    `canonical_tables` array. If that list drifts from the actual V16 DDL,
    V17 will ALTER TABLE on a missing relation and abort. This test parses
    both files and asserts the sets match exactly.
    """
    v16 = _read_v16()
    # Canonical = anything declared as `CREATE TABLE workcube_mikrolink.<name>`.
    v16_tables = set(re.findall(r"CREATE TABLE workcube_mikrolink\.(\w+) \(", v16))

    v17_path = REPO_ROOT / "sql" / "migration" / "V17__etl_lineage_columns.sql"
    if not v17_path.exists():
        pytest.skip(f"V17 not found at {v17_path}; run from repo root")
    v17 = v17_path.read_text(encoding="utf-8")

    # Extract array contents — single quoted entries inside ARRAY[...]
    m = re.search(r"canonical_tables\s+TEXT\[\]\s*:=\s*ARRAY\[(.*?)\];", v17, re.DOTALL)
    assert m, "V17 canonical_tables array not found"
    v17_tables = set(re.findall(r"'([^']+)'", m.group(1)))

    missing_in_v16 = v17_tables - v16_tables
    missing_in_v17 = v16_tables - v17_tables
    assert not missing_in_v16, (
        f"V17 lists tables not in V16 DDL: {sorted(missing_in_v16)}. "
        "ALTER TABLE will fail with relation_undefined."
    )
    assert not missing_in_v17, (
        f"V16 has canonical tables NOT covered by V17: {sorted(missing_in_v17)}. "
        "These tables will not get the ETL lineage columns."
    )


@pytest.mark.parametrize("table_name", ["COMPANY", "BRANCH"])
def test_v16_ddl_has_unique_lineage_constraint(table_name):
    """The conflict key (source_schema, source_table, source_pk) must have a
    matching UNIQUE constraint or unique index. Without it, ON CONFLICT
    raises 42P10 / 42704."""
    ddl = _read_v16()
    assert _has_unique_lineage_constraint(ddl, table_name), (
        f"V16 DDL for {table_name} has no UNIQUE / CREATE UNIQUE INDEX over "
        "(source_schema, source_table, source_pk). ETL ON CONFLICT will fail."
    )
