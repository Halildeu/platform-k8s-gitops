"""Faz 16.3 Gün 5 — Load module (Codex iter-6 AGREE).

Pattern:
- Bulk INSERT ... ON CONFLICT (source_schema, source_year, source_table, source_pk)
  DO UPDATE WHERE content_hash IS DISTINCT FROM
- Per-batch BEGIN/COMMIT (10K row default)
- Bulk fail → per-row retry
- Reject insert ayrı transaction (Codex iter-6: rollback reject siler)
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg import sql

from etl_worker.transform import TableMeta

log = logging.getLogger(__name__)


# ============================================================================
# Quote utilities (Codex iter-6: kolon adları allowlist quote)
# ============================================================================

def quote_ident(name: str) -> sql.Identifier:
    """psycopg sql.Identifier — safe quoting."""
    return sql.Identifier(name.lower())


def quote_qualified(schema: str, table: str) -> sql.Identifier:
    return sql.Identifier(schema, table.lower())


# ============================================================================
# Upsert SQL generator (metadata-driven)
# ============================================================================

def build_upsert_sql(table_meta: TableMeta, schema: str = "workcube_mikrolink") -> sql.Composed:
    """Generate parametric upsert SQL (Codex iter-6: programatik üret, allowlist quote).

    Returns psycopg sql.Composed — caller binds parameters.
    """
    table = table_meta.name.lower()
    cols = [c.name for c in table_meta.columns]
    audit_cols = ["source_schema", "source_table", "source_pk", "content_hash"]
    if table_meta.source_year is not None:
        audit_cols.insert(1, "source_year")

    all_cols = cols + audit_cols

    # Conflict key (Codex iter-5/6: source_schema + source_year + source_table + source_pk)
    conflict_cols = ["source_schema", "source_table", "source_pk"]
    if table_meta.source_year is not None:
        conflict_cols.insert(1, "source_year")

    # Update set (skip conflict cols themselves)
    update_cols = [c for c in all_cols if c not in conflict_cols]

    insert_cols_sql = sql.SQL(", ").join(quote_ident(c) for c in all_cols)
    placeholders_sql = sql.SQL(", ").join(sql.Placeholder() for _ in all_cols)
    conflict_cols_sql = sql.SQL(", ").join(quote_ident(c) for c in conflict_cols)
    update_set_sql = sql.SQL(", ").join(
        sql.SQL("{} = EXCLUDED.{}").format(quote_ident(c), quote_ident(c)) for c in update_cols
    )

    return sql.SQL(
        "INSERT INTO {table} ({insert_cols}) VALUES ({placeholders}) "
        "ON CONFLICT ({conflict_cols}) "
        "DO UPDATE SET {update_set} "
        "WHERE {table}.content_hash IS DISTINCT FROM EXCLUDED.content_hash"
    ).format(
        table=quote_qualified(schema, table),
        insert_cols=insert_cols_sql,
        placeholders=placeholders_sql,
        conflict_cols=conflict_cols_sql,
        update_set=update_set_sql,
    )


# ============================================================================
# Bulk load
# ============================================================================

class LoadStats:
    """Per-batch load metrics."""

    def __init__(self) -> None:
        self.inserted = 0
        self.updated = 0
        self.rejected = 0
        self.bulk_fallback = False


def load_batch(
    conn: psycopg.Connection,
    rows: list[dict[str, Any]],
    table_meta: TableMeta,
    schema: str = "workcube_mikrolink",
) -> LoadStats:
    """Bulk INSERT ON CONFLICT, per-batch transaction.

    Failure → per-row retry (rejected counts).
    """
    stats = LoadStats()
    if not rows:
        return stats

    upsert_sql = build_upsert_sql(table_meta, schema)
    cols = [c.name for c in table_meta.columns]
    audit_cols = ["source_schema", "source_table", "source_pk", "content_hash"]
    if table_meta.source_year is not None:
        audit_cols.insert(1, "source_year")
    all_cols = cols + audit_cols

    def row_to_tuple(row: dict[str, Any]) -> tuple:
        return tuple(row.get(c) for c in all_cols)

    # Try bulk
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(upsert_sql, [row_to_tuple(r) for r in rows])
                # psycopg cursor.rowcount sum
                stats.inserted = cur.rowcount or 0
        return stats
    except psycopg.errors.Error as e:
        log.warning("bulk_upsert_failed", error=str(e), bulk_size=len(rows))
        stats.bulk_fallback = True
        # Per-row retry
        for row in rows:
            try:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(upsert_sql, row_to_tuple(row))
                        stats.inserted += cur.rowcount or 0
            except psycopg.errors.Error as e2:
                log.warning("row_upsert_failed", error=str(e2), source_pk=row.get("source_pk"))
                stats.rejected += 1
        return stats


# ============================================================================
# Raw staging COPY (Gün 4 PoC, Gün 5 keep)
# ============================================================================

def copy_to_raw_staging(
    conn: psycopg.Connection,
    rows: list[dict[str, Any]],
    table_name: str,
    run_id: str,
    source_schema: str,
    source_year: int | None,
    schema: str = "workcube_mssql_raw",
) -> int:
    """Bulk COPY raw_payload JSONB to workcube_mssql_raw.<table>."""
    if not rows:
        return 0

    import json
    table = table_name.lower()
    copy_sql = sql.SQL(
        "COPY {table} (run_id, source_schema, source_year, source_pk, raw_payload) FROM STDIN"
    ).format(table=quote_qualified(schema, table))

    with conn.cursor() as cur:
        with cur.copy(copy_sql) as copy:
            for row in rows:
                source_pk = str(row.get("source_pk", ""))
                raw_json = json.dumps(row, default=str, ensure_ascii=False)
                copy.write_row((run_id, source_schema, source_year, source_pk, raw_json))

    return len(rows)
