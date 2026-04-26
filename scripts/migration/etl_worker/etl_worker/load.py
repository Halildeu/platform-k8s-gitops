"""Faz 16.3 Gün 5+7 — Load module (Codex iter-6 AGREE / iter-4 Day 7 AGREE).

Pattern:
- Bulk INSERT ... ON CONFLICT (source_schema, source_year, source_table, source_pk)
  DO UPDATE WHERE content_hash IS DISTINCT FROM
- Per-batch BEGIN/COMMIT (10K row default)
- Bulk fail → per-row retry
- Reject insert ayrı transaction (Codex iter-6: rollback reject siler)

Day 7 (Codex iter-4) extension:
- LoadReject context-free dataclass (no run_id) so load module stays
  decoupled from audit lifecycle. Runner enriches LoadReject → RejectRecord
  before insert_rejects_batch().
- Per-row except path classifies the error: NO_RETRY → LoadReject;
  TRANSIENT/CRITICAL → re-raise to the runner's batch retry loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg import sql

from etl_worker.retry import RetryClass, classify_error, describe
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
# Day 7 contracts
# ============================================================================

@dataclass
class LoadReject:
    """Context-free reject info — no run_id (audit lifecycle owned by runner).

    Runner enriches this into a RejectRecord (audit.RejectRecord) before
    calling AuditModule.insert_rejects_batch().
    """

    table_name: str
    source_schema: str
    source_year: int | None
    source_pk: str | None
    column_name: str | None
    reject_reason: str
    severity: str  # WARN / ERROR / CRITICAL
    pg_error_code: str | None
    pg_error_message: str | None
    source_value: str | None
    raw_payload: dict[str, Any] | None


@dataclass
class LoadStats:
    """Per-batch load metrics."""

    inserted: int = 0
    updated: int = 0
    rejected: int = 0
    rejects: list[LoadReject] = field(default_factory=list)
    bulk_fallback: bool = False


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
# Bulk load (Day 7 retry-aware)
# ============================================================================

def load_batch(
    conn: psycopg.Connection,
    rows: list[dict[str, Any]],
    table_meta: TableMeta,
    schema: str = "workcube_mikrolink",
    include_raw_payload: bool = False,
) -> LoadStats:
    """Bulk INSERT ON CONFLICT, per-batch transaction.

    Failure model (Codex iter-7/Day 7):
      - Bulk attempt under conn.transaction()
      - On any failure (PG error), bulk_fallback = True; iterate rows.
      - Per-row error classification:
          NO_RETRY  → append LoadReject + stats.rejected += 1, continue.
          TRANSIENT → re-raise to caller's batch retry loop.
          CRITICAL  → re-raise; caller aborts the run.

    Raw payload inclusion is opt-in (default False) so we don't accidentally
    persist large rows with sensitive content.
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

    def row_to_tuple(row: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(row.get(c) for c in all_cols)

    # Try bulk first.
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(upsert_sql, [row_to_tuple(r) for r in rows])
                stats.inserted = cur.rowcount or 0
        return stats
    except psycopg.errors.Error as e:
        cls = classify_error(e)
        d = describe(e)
        log.warning(
            "bulk_upsert_failed bulk_size=%s class=%s sqlstate=%s msg=%s",
            len(rows), cls.value, d["sqlstate"], d["message"][:120],
        )
        if cls == RetryClass.CRITICAL:
            # Don't try per-row recovery on a CRITICAL — surface immediately.
            raise
        # NO_RETRY or TRANSIENT at bulk-level → per-row fallback below.

    # Per-row fallback.
    stats.bulk_fallback = True
    for row in rows:
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(upsert_sql, row_to_tuple(row))
                    stats.inserted += cur.rowcount or 0
        except psycopg.errors.Error as e2:
            cls = classify_error(e2)
            d = describe(e2)
            if cls == RetryClass.NO_RETRY:
                stats.rejects.append(
                    LoadReject(
                        table_name=table_meta.name,
                        source_schema=table_meta.source_schema,
                        source_year=table_meta.source_year,
                        source_pk=str(row.get("source_pk")) if row.get("source_pk") is not None else None,
                        column_name=None,
                        reject_reason="LOAD_NO_RETRY",
                        severity="ERROR",
                        pg_error_code=d["sqlstate"],
                        pg_error_message=d["message"][:500],
                        source_value=None,
                        raw_payload=row if include_raw_payload else None,
                    )
                )
                stats.rejected += 1
                continue
            # TRANSIENT or CRITICAL — re-raise to the runner's retry loop.
            raise
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
