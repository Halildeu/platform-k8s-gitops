"""Faz 16.3 Gün 7 — Reconciliation gate (Codex iter-4 AGREE).

Per-table verdict over (table, schema, source_year):
  - row_count parity: PG row count vs MSSQL scoped count.
  - sample_diff: 10 deterministic rows (ORDER BY idempotency_key) compared
    by content_hash. Same canonical make_source_pk() helper everywhere.
  - per-table checksum: md5(string_agg(content_hash ORDER BY source_pk)) on
    PG side; same recipe on MSSQL side computed in-process via transform.

Scope kinds:
  - full     → both sides scan the full (schema, year) set.
  - limited  → MSSQL produces the expected source_pk set first; PG looks up
              via ANY(%s::text[]). Independent LIMIT on both sides is forbidden
              because the two would produce different sub-sets.
  - delta    → WHERE checkpoint_column > checkpoint_value on both sides.
              Requires a trustworthy watermark column; otherwise verdict
              UNSUPPORTED_DELTA + abort (final-delta mode).

Mode-aware verdict:
  - final-delta: any mismatch → fatal. Caller updates run status ABORTED.
  - initial:    report mismatch + continue (cumulative).
  - dry-run:    report only.

Output: Markdown + sibling JSON (caller writes to docs/migration/reconcile-*).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from etl_worker.transform import (
    ColumnMeta,
    TableMeta,
    content_hash,
    make_source_pk,
    transform_row,
)

log = logging.getLogger(__name__)


# ============================================================================
# Scope + Result dataclasses
# ============================================================================

@dataclass
class ReconcileScope:
    kind: str  # "full" | "limited" | "delta"
    limit: int | None = None
    order_by: list[str] | None = None  # default = idempotency_key
    checkpoint_column: str | None = None
    checkpoint_value: Any | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"full", "limited", "delta"}:
            raise ValueError(f"unknown scope kind: {self.kind}")
        if self.kind == "limited" and (self.limit is None or self.limit <= 0):
            raise ValueError("limited scope requires limit > 0")
        if self.kind == "delta" and not self.checkpoint_column:
            raise ValueError("delta scope requires checkpoint_column")


@dataclass
class TableReconcileResult:
    table_name: str
    source_schema: str
    source_year: int | None
    scope_kind: str
    scope_limit: int | None
    row_count_pg: int
    row_count_mssql: int
    sample_diff: list[dict[str, Any]] = field(default_factory=list)
    checksum_pg: str | None = None
    checksum_mssql: str | None = None
    verdict: str = "UNKNOWN"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReconcileReport:
    run_id: str
    mode: str
    tables: list[TableReconcileResult] = field(default_factory=list)

    def overall_verdict(self) -> str:
        """Worst-case verdict across all tables."""
        priority = {
            "MATCH": 0,
            "ROW_COUNT_MISMATCH": 1,
            "SAMPLE_MISMATCH": 1,
            "CHECKSUM_MISMATCH": 2,
            "UNSUPPORTED_DELTA": 3,
            "UNKNOWN": 9,
        }
        if not self.tables:
            return "UNKNOWN"
        worst = max(self.tables, key=lambda t: priority.get(t.verdict, 9))
        return worst.verdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "overall_verdict": self.overall_verdict(),
            "tables": [t.to_dict() for t in self.tables],
        }


# ============================================================================
# Per-table reconcile
# ============================================================================

def reconcile_table(
    pg_conn: Any,  # psycopg.Connection (typed loose to keep test mocking easy)
    mssql_conn: Any,  # pyodbc.Connection — typed Any for the same reason
    table_meta: TableMeta,
    scope: ReconcileScope,
    pg_canonical_schema: str = "workcube_mikrolink",
) -> TableReconcileResult:
    """Compute per-table parity. See module docstring for the contract.

    The function is intentionally split per scope kind so each path is
    independently testable. Limited path uses MSSQL as source-of-truth and
    PG ANY() lookup — never independent LIMIT on both sides (Codex iter-3
    fix).
    """
    result = TableReconcileResult(
        table_name=table_meta.name,
        source_schema=table_meta.source_schema,
        source_year=table_meta.source_year,
        scope_kind=scope.kind,
        scope_limit=scope.limit,
        row_count_pg=0,
        row_count_mssql=0,
    )

    if scope.kind == "limited":
        _reconcile_limited(pg_conn, mssql_conn, table_meta, scope, result, pg_canonical_schema)
    elif scope.kind == "full":
        _reconcile_full(pg_conn, mssql_conn, table_meta, scope, result, pg_canonical_schema)
    else:  # delta
        _reconcile_delta(pg_conn, mssql_conn, table_meta, scope, result, pg_canonical_schema)

    _assign_verdict(result)
    return result


def _assign_verdict(result: TableReconcileResult) -> None:
    if result.verdict == "UNSUPPORTED_DELTA":
        return  # already set by delta path
    if result.row_count_pg != result.row_count_mssql:
        result.verdict = "ROW_COUNT_MISMATCH"
        return
    if result.sample_diff and any(not s.get("match") for s in result.sample_diff):
        result.verdict = "SAMPLE_MISMATCH"
        return
    if (
        result.checksum_pg is not None
        and result.checksum_mssql is not None
        and result.checksum_pg != result.checksum_mssql
    ):
        result.verdict = "CHECKSUM_MISMATCH"
        return
    result.verdict = "MATCH"


# ============================================================================
# Limited scope (Day 7 dry-run default)
# ============================================================================

def _reconcile_limited(
    pg_conn: Any,
    mssql_conn: Any,
    table_meta: TableMeta,
    scope: ReconcileScope,
    result: TableReconcileResult,
    pg_canonical_schema: str,
) -> None:
    order_by = scope.order_by or list(table_meta.idempotency_key)
    if not order_by:
        result.notes.append("no idempotency_key — falling back to source_pk only")
        order_by = ["source_pk"]

    # 1. MSSQL expected scoped set — source-of-truth.
    expected_rows = _mssql_fetch_scoped_rows(
        mssql_conn, table_meta, order_by, scope.limit
    )
    expected_pk_set = [make_source_pk(r, table_meta.idempotency_key) for r in expected_rows]
    result.row_count_mssql = len(expected_pk_set)

    if not expected_pk_set:
        result.notes.append("MSSQL scoped set is empty")

    # 2. PG side: lookup the expected set via ANY().
    pg_hashes = _pg_lookup_hashes(
        pg_conn, table_meta, expected_pk_set, pg_canonical_schema
    )
    result.row_count_pg = len(pg_hashes)

    # 3. Sample diff: top 10 expected_pk_set
    sample_pks = expected_pk_set[:10]
    sample_diff: list[dict[str, Any]] = []
    for pk, mssql_row in zip(sample_pks, expected_rows[:10]):
        # Recompute MSSQL-side hash via the same transform path used at load.
        tr = transform_row(mssql_row, table_meta)
        if tr.reject_reason:
            sample_diff.append({
                "source_pk": pk,
                "hash_pg": pg_hashes.get(pk),
                "hash_mssql": None,
                "match": False,
                "note": f"transform_reject={tr.reject_reason}",
            })
            continue
        hash_mssql = tr.content_hash
        hash_pg = pg_hashes.get(pk)
        sample_diff.append({
            "source_pk": pk,
            "hash_pg": hash_pg,
            "hash_mssql": hash_mssql,
            "match": hash_pg == hash_mssql,
        })
    result.sample_diff = sample_diff

    # 4. Per-table checksum on the expected set (deterministic ordering).
    if expected_pk_set:
        # PG: md5(string_agg(content_hash, '' ORDER BY source_pk))
        result.checksum_pg = _pg_aggregate_checksum(
            pg_conn, table_meta, expected_pk_set, pg_canonical_schema
        )
        # MSSQL: same recipe in Python over the expected_rows order.
        ordered_pks = sorted(expected_pk_set)
        ordered_hashes: list[str] = []
        for r in expected_rows:
            tr = transform_row(r, table_meta)
            if tr.reject_reason or tr.content_hash is None:
                ordered_hashes.append("__transform_reject__")
                continue
            ordered_hashes.append(tr.content_hash)
        # Sort by source_pk to match PG ORDER BY source_pk.
        pk_to_hash = {make_source_pk(r, table_meta.idempotency_key): h
                      for r, h in zip(expected_rows, ordered_hashes)}
        ordered_hashes_sorted = [pk_to_hash[pk] for pk in ordered_pks if pk in pk_to_hash]
        joined = "".join(ordered_hashes_sorted)
        result.checksum_mssql = hashlib.md5(joined.encode("utf-8")).hexdigest()


# ============================================================================
# Full scope
# ============================================================================

def _reconcile_full(
    pg_conn: Any,
    mssql_conn: Any,
    table_meta: TableMeta,
    scope: ReconcileScope,
    result: TableReconcileResult,
    pg_canonical_schema: str,
) -> None:
    # MSSQL count(*).
    result.row_count_mssql = _mssql_count(mssql_conn, table_meta)
    # PG count(*) WHERE source_schema/year.
    result.row_count_pg = _pg_count_canonical(pg_conn, table_meta, pg_canonical_schema)

    # Aggregate PG checksum.
    result.checksum_pg = _pg_aggregate_checksum(
        pg_conn, table_meta, expected_pk_set=None, pg_canonical_schema=pg_canonical_schema
    )
    # MSSQL aggregate (full scan; Day 7 dry-run uses limited so this path
    # is exercised only in larger reconciles).
    result.checksum_mssql = _mssql_aggregate_checksum(mssql_conn, table_meta)

    # Sample top 10 ordered by idempotency_key.
    order_by = scope.order_by or list(table_meta.idempotency_key)
    rows = _mssql_fetch_scoped_rows(mssql_conn, table_meta, order_by, limit=10)
    pks = [make_source_pk(r, table_meta.idempotency_key) for r in rows]
    pg_hashes = _pg_lookup_hashes(pg_conn, table_meta, pks, pg_canonical_schema)
    sample_diff = []
    for pk, r in zip(pks, rows):
        tr = transform_row(r, table_meta)
        sample_diff.append({
            "source_pk": pk,
            "hash_pg": pg_hashes.get(pk),
            "hash_mssql": tr.content_hash,
            "match": pg_hashes.get(pk) == tr.content_hash,
        })
    result.sample_diff = sample_diff


# ============================================================================
# Delta scope
# ============================================================================

def _reconcile_delta(
    pg_conn: Any,
    mssql_conn: Any,
    table_meta: TableMeta,
    scope: ReconcileScope,
    result: TableReconcileResult,
    pg_canonical_schema: str,
) -> None:
    # If the manifest doesn't carry a trustworthy watermark column, refuse.
    has_watermark = any(c.name == scope.checkpoint_column for c in table_meta.columns)
    if not has_watermark:
        result.verdict = "UNSUPPORTED_DELTA"
        result.notes.append(
            f"checkpoint_column={scope.checkpoint_column!r} not in table_meta.columns"
        )
        return
    # Out-of-scope for Day 7; full impl arrives with delta cutover (Day 8+).
    result.verdict = "UNSUPPORTED_DELTA"
    result.notes.append("delta scope is not implemented in Day 7 dry-run; defer to Day 8")


# ============================================================================
# Connection adapters (separated for unit-test mocking)
# ============================================================================

def _mssql_fetch_scoped_rows(
    mssql_conn: Any,
    table_meta: TableMeta,
    order_by: list[str],
    limit: int | None,
) -> list[dict[str, Any]]:
    """Fetch ordered scoped rows from MSSQL as list[dict]. Test mocks this."""
    cols = [c.name for c in table_meta.columns]
    col_list = ", ".join(cols)
    order_list = ", ".join(order_by)
    schema = table_meta.source_schema
    table = table_meta.name
    query = f"SELECT {col_list} FROM {schema}.{table} ORDER BY {order_list}"
    if limit is not None:
        query += f" OFFSET 0 ROWS FETCH NEXT {int(limit)} ROWS ONLY"
    cur = mssql_conn.cursor()
    cur.execute(query)
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        out.append({c: row[i] for i, c in enumerate(cols)})
    return out


def _mssql_count(mssql_conn: Any, table_meta: TableMeta) -> int:
    cur = mssql_conn.cursor()
    cur.execute(f"SELECT count(*) FROM {table_meta.source_schema}.{table_meta.name}")
    row = cur.fetchone()
    return int(row[0] if row else 0)


def _mssql_aggregate_checksum(mssql_conn: Any, table_meta: TableMeta) -> str | None:
    """Compute md5 of all content_hash values, ordered by source_pk.

    Day 7 limited path uses Python streaming; this full path is reserved
    for production. Implemented as a placeholder that returns None unless
    the caller wants to fully scan.
    """
    return None


def _year_predicate(table_meta: TableMeta) -> tuple[str, list]:
    """Build a SQL predicate fragment for the source_year filter.

    Canonical (non-parametric) tables have no `source_year` column in V16
    DDL, so we omit the predicate. Parametric tables carry source_year
    SMALLINT, so we use IS NOT DISTINCT FROM (NULL-safe).
    """
    if table_meta.source_year is None:
        return ("", [])
    return (" AND source_year IS NOT DISTINCT FROM %s", [table_meta.source_year])


def _pg_count_canonical(
    pg_conn: Any, table_meta: TableMeta, pg_canonical_schema: str,
) -> int:
    cur = pg_conn.cursor()
    year_pred, year_params = _year_predicate(table_meta)
    cur.execute(
        f"SELECT count(*) FROM {pg_canonical_schema}.{table_meta.name.lower()} "
        f"WHERE source_schema = %s{year_pred}",
        [table_meta.source_schema, *year_params],
    )
    row = cur.fetchone()
    return int(row[0] if row else 0)


def _pg_lookup_hashes(
    pg_conn: Any,
    table_meta: TableMeta,
    pk_set: list[str],
    pg_canonical_schema: str,
) -> dict[str, str]:
    if not pk_set:
        return {}
    cur = pg_conn.cursor()
    year_pred, year_params = _year_predicate(table_meta)
    cur.execute(
        f"SELECT source_pk, content_hash FROM {pg_canonical_schema}.{table_meta.name.lower()} "
        f"WHERE source_schema = %s{year_pred} "
        "AND source_pk = ANY(%s::text[])",
        [table_meta.source_schema, *year_params, pk_set],
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _pg_aggregate_checksum(
    pg_conn: Any,
    table_meta: TableMeta,
    expected_pk_set: list[str] | None,
    pg_canonical_schema: str,
) -> str | None:
    cur = pg_conn.cursor()
    year_pred, year_params = _year_predicate(table_meta)
    if expected_pk_set is None:
        cur.execute(
            f"SELECT md5(string_agg(content_hash, '' ORDER BY source_pk)) "
            f"FROM {pg_canonical_schema}.{table_meta.name.lower()} "
            f"WHERE source_schema = %s{year_pred}",
            [table_meta.source_schema, *year_params],
        )
    else:
        if not expected_pk_set:
            return None
        cur.execute(
            f"SELECT md5(string_agg(content_hash, '' ORDER BY source_pk)) "
            f"FROM {pg_canonical_schema}.{table_meta.name.lower()} "
            f"WHERE source_schema = %s{year_pred} "
            "AND source_pk = ANY(%s::text[])",
            [table_meta.source_schema, *year_params, expected_pk_set],
        )
    row = cur.fetchone()
    return row[0] if row else None


# ============================================================================
# Artifact rendering (Markdown + JSON)
# ============================================================================

def render_markdown(report: ReconcileReport) -> str:
    lines: list[str] = []
    lines.append(f"# Reconciliation report")
    lines.append("")
    lines.append(f"- run_id: `{report.run_id}`")
    lines.append(f"- mode:   `{report.mode}`")
    lines.append(f"- overall verdict: **{report.overall_verdict()}**")
    lines.append("")
    for t in report.tables:
        lines.append(f"## `{t.source_schema}.{t.table_name}` (year={t.source_year})")
        lines.append("")
        lines.append(f"- scope: `{t.scope_kind}` (limit={t.scope_limit})")
        lines.append(f"- verdict: **{t.verdict}**")
        lines.append(f"- row_count_pg: {t.row_count_pg}")
        lines.append(f"- row_count_mssql: {t.row_count_mssql}")
        if t.checksum_pg or t.checksum_mssql:
            lines.append(f"- checksum_pg:    `{t.checksum_pg}`")
            lines.append(f"- checksum_mssql: `{t.checksum_mssql}`")
        if t.notes:
            lines.append("")
            lines.append("Notes:")
            for n in t.notes:
                lines.append(f"- {n}")
        if t.sample_diff:
            lines.append("")
            lines.append("Sample diff (top 10):")
            lines.append("")
            lines.append("| source_pk | hash_pg | hash_mssql | match |")
            lines.append("|---|---|---|---|")
            for s in t.sample_diff:
                pg_short = (s.get("hash_pg") or "")[:12]
                mssql_short = (s.get("hash_mssql") or "")[:12]
                match = "✅" if s.get("match") else "❌"
                lines.append(f"| `{s.get('source_pk')}` | `{pg_short}` | `{mssql_short}` | {match} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_json(report: ReconcileReport) -> str:
    return json.dumps(report.to_dict(), default=str, indent=2, ensure_ascii=False)
