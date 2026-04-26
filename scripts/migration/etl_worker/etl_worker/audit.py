"""Faz 16.3 Gün 6 — Audit module (Codex iter-7 REVISE).

Pattern:
- migration_audit.migration_runs / migration_table_state / migration_rejects.
- AuditModule uses an autocommit connection (independent of the load tx).
  Persisting rejects survives a load rollback (Codex iter-7 hard requirement).
- Resume helpers expose VALIDATED tables to skip + last_pk for table_state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import psycopg
from psycopg import sql

log = logging.getLogger(__name__)

AUDIT_SCHEMA = "migration_audit"


# ============================================================================
# Mode canonicalization (Codex iter-8)
# ============================================================================
#
# CLI uses hyphen-spelled modes (`final-delta`, `reconcile-only`, `dry-run`)
# because Click options conventionally use hyphens. The V16 audit DDL CHECK
# constraint accepts underscore variants (`final_delta`, `reconcile_only`,
# `dry_run`). All audit writes go through this normalization to keep the
# CLI surface stable while satisfying the DB constraint.

DB_MODE_VALUES = {"initial", "final_delta", "reconcile_only", "dry_run"}

_CLI_TO_DB_MODE = {
    "initial": "initial",
    "final-delta": "final_delta",
    "final_delta": "final_delta",
    "reconcile-only": "reconcile_only",
    "reconcile_only": "reconcile_only",
    "dry-run": "dry_run",
    "dry_run": "dry_run",
}


def normalize_mode(mode: str) -> str:
    """Map CLI-facing mode string to the DB CHECK constraint value.

    Raises ValueError on unknown modes so we fail before INSERT instead of
    surfacing a constraint violation deep in the run.
    """
    if mode not in _CLI_TO_DB_MODE:
        raise ValueError(
            f"unknown mode {mode!r}; expected one of {sorted(_CLI_TO_DB_MODE)}"
        )
    return _CLI_TO_DB_MODE[mode]


# ============================================================================
# Data classes (typed payloads)
# ============================================================================

@dataclass
class RunRecord:
    run_id: str
    mode: str
    status: str
    source_database: str
    worker_version: str | None
    git_sha: str | None
    contract_version: str | None
    annex_version: str | None
    started_by: str | None
    started_at: datetime | None


@dataclass
class TableStateRecord:
    run_id: str
    table_name: str
    source_schema: str
    source_year: int | None
    status: str
    rows_extracted: int
    rows_loaded: int
    rows_rejected: int
    last_pk: str | None
    batch_no: int
    started_at: datetime | None
    completed_at: datetime | None


@dataclass
class RejectRecord:
    run_id: str
    table_name: str
    source_schema: str | None
    source_year: int | None
    source_pk: str | None
    column_name: str | None
    reject_reason: str
    severity: str  # WARN / ERROR / CRITICAL
    source_value: str | None
    pg_error_code: str | None
    pg_error_message: str | None
    raw_payload: dict[str, Any] | None


# ============================================================================
# AuditModule
# ============================================================================

class AuditModule:
    """Audit writer (autocommit conn).

    Codex iter-7 hard rule:
        Audit writes MUST happen on a connection separate from the load
        transaction so rejects survive a load rollback. Caller is responsible
        for passing an autocommit connection (set_autocommit=True).
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        if not conn.autocommit:
            log.warning(
                "audit.conn.not_autocommit "
                "— rejects may be lost on load rollback; "
                "set conn.autocommit=True before passing in"
            )
        self.conn = conn

    # ------------------------------------------------------------------ runs
    def create_run(
        self,
        run_id: str,
        mode: str,
        source_database: str,
        worker_version: str | None = None,
        git_sha: str | None = None,
        contract_version: str | None = None,
        annex_version: str | None = None,
        started_by: str | None = None,
        notes: dict[str, Any] | None = None,
    ) -> None:
        """Insert a new RUNNING migration_runs row.

        `mode` accepts CLI-spelled values (`final-delta`, `dry-run`,
        `reconcile-only`) and is normalized to the DB CHECK form
        (`final_delta`, `dry_run`, `reconcile_only`) before INSERT.
        """
        db_mode = normalize_mode(mode)
        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "INSERT INTO {schema}.migration_runs "
                    "(run_id, mode, status, source_database, worker_version, git_sha, "
                    " contract_version, annex_version, started_by, notes) "
                    "VALUES (%s, %s, 'RUNNING', %s, %s, %s, %s, %s, %s, %s::jsonb)"
                ).format(schema=sql.Identifier(AUDIT_SCHEMA)),
                (
                    run_id,
                    db_mode,
                    source_database,
                    worker_version,
                    git_sha,
                    contract_version,
                    annex_version,
                    started_by,
                    json.dumps(notes or {}),
                ),
            )
        log.info("audit.run.created run_id=%s mode=%s db_mode=%s", run_id, mode, db_mode)

    def update_run_status(
        self,
        run_id: str,
        status: str,
        error_summary: str | None = None,
    ) -> None:
        """Mark migration_runs SUCCESS / FAILED / ABORTED with completed_at."""
        if status not in {"SUCCESS", "FAILED", "ABORTED", "RUNNING"}:
            raise ValueError(f"invalid run status: {status}")
        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "UPDATE {schema}.migration_runs "
                    "SET status = %s, completed_at = now(), error_summary = %s "
                    "WHERE run_id = %s"
                ).format(schema=sql.Identifier(AUDIT_SCHEMA)),
                (status, error_summary, run_id),
            )
        log.info("audit.run.status run_id=%s status=%s", run_id, status)

    # ------------------------------------------------------------ table_state
    def upsert_table_state(
        self,
        run_id: str,
        table_name: str,
        source_schema: str,
        source_year: int | None,
        status: str,
        rows_extracted: int = 0,
        rows_loaded: int = 0,
        rows_rejected: int = 0,
        last_pk: str | None = None,
        batch_no: int = 0,
        max_updated_at: datetime | None = None,
        extract_query_hash: str | None = None,
        checksum: str | None = None,
        content_hash: str | None = None,
        default_partition_rows: int = 0,
    ) -> None:
        """Upsert table_state for (run_id, table_name, source_schema, source_year).

        PRIMARY KEY uses COALESCE(source_year, 0); we mirror that with a
        sentinel for ON CONFLICT (run_id, table_name, source_schema, source_year)
        only working when source_year IS NOT NULL — fall back to manual
        SELECT/UPDATE/INSERT for the canonical (source_year IS NULL) case.
        """
        if status not in {"PENDING", "EXTRACTING", "LOADING", "VALIDATED", "FAILED"}:
            raise ValueError(f"invalid table_state status: {status}")

        # Set started_at on first transition out of PENDING; completed_at on terminal.
        started_at = datetime.now(timezone.utc) if status in {"EXTRACTING", "LOADING"} else None
        completed_at = datetime.now(timezone.utc) if status in {"VALIDATED", "FAILED"} else None

        with self.conn.cursor() as cur:
            # Existence probe (NULL-safe predicate for source_year)
            cur.execute(
                sql.SQL(
                    "SELECT 1 FROM {schema}.migration_table_state "
                    "WHERE run_id = %s AND table_name = %s AND source_schema = %s "
                    "AND source_year IS NOT DISTINCT FROM %s"
                ).format(schema=sql.Identifier(AUDIT_SCHEMA)),
                (run_id, table_name, source_schema, source_year),
            )
            exists = cur.fetchone() is not None

            if exists:
                cur.execute(
                    sql.SQL(
                        "UPDATE {schema}.migration_table_state SET "
                        "  status = %s, "
                        "  rows_extracted = rows_extracted + %s, "
                        "  rows_loaded = rows_loaded + %s, "
                        "  rows_rejected = rows_rejected + %s, "
                        "  last_pk = COALESCE(%s, last_pk), "
                        "  batch_no = GREATEST(batch_no, %s), "
                        "  max_updated_at = COALESCE(%s, max_updated_at), "
                        "  extract_query_hash = COALESCE(%s, extract_query_hash), "
                        "  checksum = COALESCE(%s, checksum), "
                        "  content_hash = COALESCE(%s, content_hash), "
                        "  default_partition_rows = default_partition_rows + %s, "
                        "  started_at = COALESCE(started_at, %s), "
                        "  completed_at = COALESCE(%s, completed_at) "
                        "WHERE run_id = %s AND table_name = %s AND source_schema = %s "
                        "  AND source_year IS NOT DISTINCT FROM %s"
                    ).format(schema=sql.Identifier(AUDIT_SCHEMA)),
                    (
                        status,
                        rows_extracted,
                        rows_loaded,
                        rows_rejected,
                        last_pk,
                        batch_no,
                        max_updated_at,
                        extract_query_hash,
                        checksum,
                        content_hash,
                        default_partition_rows,
                        started_at,
                        completed_at,
                        run_id,
                        table_name,
                        source_schema,
                        source_year,
                    ),
                )
            else:
                cur.execute(
                    sql.SQL(
                        "INSERT INTO {schema}.migration_table_state "
                        "(run_id, table_name, source_schema, source_year, status, "
                        " rows_extracted, rows_loaded, rows_rejected, last_pk, batch_no, "
                        " max_updated_at, extract_query_hash, checksum, content_hash, "
                        " default_partition_rows, started_at, completed_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                        "        %s, %s, %s, %s, %s, %s, %s)"
                    ).format(schema=sql.Identifier(AUDIT_SCHEMA)),
                    (
                        run_id,
                        table_name,
                        source_schema,
                        source_year,
                        status,
                        rows_extracted,
                        rows_loaded,
                        rows_rejected,
                        last_pk,
                        batch_no,
                        max_updated_at,
                        extract_query_hash,
                        checksum,
                        content_hash,
                        default_partition_rows,
                        started_at,
                        completed_at,
                    ),
                )

    # ----------------------------------------------------------- batch hooks
    # Codex iter-7: explicit batch hooks for retry/observability.

    def record_batch_start(
        self,
        run_id: str,
        table_name: str,
        source_schema: str,
        source_year: int | None,
        batch_no: int,
    ) -> None:
        self.upsert_table_state(
            run_id=run_id,
            table_name=table_name,
            source_schema=source_schema,
            source_year=source_year,
            status="LOADING",
            batch_no=batch_no,
        )

    def record_batch_success(
        self,
        run_id: str,
        table_name: str,
        source_schema: str,
        source_year: int | None,
        rows_loaded: int,
        last_pk: str | None,
        batch_no: int,
    ) -> None:
        self.upsert_table_state(
            run_id=run_id,
            table_name=table_name,
            source_schema=source_schema,
            source_year=source_year,
            status="LOADING",
            rows_loaded=rows_loaded,
            last_pk=last_pk,
            batch_no=batch_no,
        )

    def record_batch_failure(
        self,
        run_id: str,
        table_name: str,
        source_schema: str,
        source_year: int | None,
        batch_no: int,
        rows_rejected: int = 0,
    ) -> None:
        # Failure does NOT auto-flip table_state to FAILED — caller decides
        # based on threshold (mode-aware). We just bump rejected counter.
        self.upsert_table_state(
            run_id=run_id,
            table_name=table_name,
            source_schema=source_schema,
            source_year=source_year,
            status="LOADING",
            rows_rejected=rows_rejected,
            batch_no=batch_no,
        )

    # --------------------------------------------------------------- rejects
    def insert_reject(self, reject: RejectRecord) -> None:
        """Persist a single reject row.

        Hard rule (Codex iter-7): runs on autocommit conn so it survives a
        load rollback.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "INSERT INTO {schema}.migration_rejects "
                    "(run_id, table_name, source_schema, source_year, source_pk, column_name, "
                    " reject_reason, severity, source_value, pg_error_code, pg_error_message, "
                    " raw_payload) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)"
                ).format(schema=sql.Identifier(AUDIT_SCHEMA)),
                (
                    reject.run_id,
                    reject.table_name,
                    reject.source_schema,
                    reject.source_year,
                    reject.source_pk,
                    reject.column_name,
                    reject.reject_reason,
                    reject.severity,
                    reject.source_value,
                    reject.pg_error_code,
                    reject.pg_error_message,
                    json.dumps(reject.raw_payload, default=str) if reject.raw_payload else None,
                ),
            )

    def insert_rejects_batch(self, rejects: Iterable[RejectRecord]) -> int:
        """Bulk reject insert. Returns count."""
        rows = list(rejects)
        if not rows:
            return 0
        with self.conn.cursor() as cur:
            cur.executemany(
                sql.SQL(
                    "INSERT INTO {schema}.migration_rejects "
                    "(run_id, table_name, source_schema, source_year, source_pk, column_name, "
                    " reject_reason, severity, source_value, pg_error_code, pg_error_message, "
                    " raw_payload) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)"
                ).format(schema=sql.Identifier(AUDIT_SCHEMA)),
                [
                    (
                        r.run_id,
                        r.table_name,
                        r.source_schema,
                        r.source_year,
                        r.source_pk,
                        r.column_name,
                        r.reject_reason,
                        r.severity,
                        r.source_value,
                        r.pg_error_code,
                        r.pg_error_message,
                        json.dumps(r.raw_payload, default=str) if r.raw_payload else None,
                    )
                    for r in rows
                ],
            )
        return len(rows)

    # ----------------------------------------------------------------- query
    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT run_id, mode, status, source_database, started_at, completed_at, "
                    "       error_summary "
                    "FROM {schema}.migration_runs WHERE run_id = %s"
                ).format(schema=sql.Identifier(AUDIT_SCHEMA)),
                (run_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "run_id": str(row[0]),
            "mode": row[1],
            "status": row[2],
            "source_database": row[3],
            "started_at": row[4],
            "completed_at": row[5],
            "error_summary": row[6],
        }

    def list_rejects(
        self,
        run_id: str,
        table_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """SRE triage helper (Day 8): list reject rows with the most useful
        diagnostic columns. Order: rejected_at DESC.

        Codex 019dc88c iter-4 AGREE: bounded operator value, doesn't depend
        on parametric scope.
        """
        if limit <= 0:
            limit = 50
        if limit > 1000:
            limit = 1000
        if offset < 0:
            offset = 0

        params: list[Any] = [run_id]
        where = "WHERE run_id = %s"
        if table_name is not None:
            where += " AND table_name = %s"
            params.append(table_name)
        params.extend([limit, offset])

        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT id, table_name, source_schema, source_year, source_pk, "
                    "       column_name, reject_reason, severity, pg_error_code, "
                    "       pg_error_message, rejected_at "
                    "FROM {schema}.migration_rejects "
                    f"{where} "
                    "ORDER BY rejected_at DESC LIMIT %s OFFSET %s"
                ).format(schema=sql.Identifier(AUDIT_SCHEMA)),
                params,
            )
            rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append({
                "id": int(r[0]),
                "table_name": r[1],
                "source_schema": r[2],
                "source_year": r[3],
                "source_pk": r[4],
                "column_name": r[5],
                "reject_reason": r[6],
                "severity": r[7],
                "pg_error_code": r[8],
                "pg_error_message": r[9],
                "rejected_at": r[10],
            })
        return out

    def get_resume_state(self, run_id: str) -> dict[str, dict[str, Any]]:
        """Return per-(table, schema, year) state for resume.

        Caller skips entries where status == 'VALIDATED'.
        last_pk lets the extractor restart mid-table for LOADING entries.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT table_name, source_schema, source_year, status, "
                    "       rows_extracted, rows_loaded, rows_rejected, last_pk, batch_no "
                    "FROM {schema}.migration_table_state "
                    "WHERE run_id = %s"
                ).format(schema=sql.Identifier(AUDIT_SCHEMA)),
                (run_id,),
            )
            rows = cur.fetchall()
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            key = f"{r[0]}|{r[1]}|{r[2] if r[2] is not None else ''}"
            out[key] = {
                "table_name": r[0],
                "source_schema": r[1],
                "source_year": r[2],
                "status": r[3],
                "rows_extracted": r[4],
                "rows_loaded": r[5],
                "rows_rejected": r[6],
                "last_pk": r[7],
                "batch_no": r[8],
            }
        return out

    def reject_count(self, run_id: str, table_name: str | None = None) -> int:
        with self.conn.cursor() as cur:
            if table_name is None:
                cur.execute(
                    sql.SQL(
                        "SELECT count(*) FROM {schema}.migration_rejects WHERE run_id = %s"
                    ).format(schema=sql.Identifier(AUDIT_SCHEMA)),
                    (run_id,),
                )
            else:
                cur.execute(
                    sql.SQL(
                        "SELECT count(*) FROM {schema}.migration_rejects "
                        "WHERE run_id = %s AND table_name = %s"
                    ).format(schema=sql.Identifier(AUDIT_SCHEMA)),
                    (run_id, table_name),
                )
            return int(cur.fetchone()[0])

    def status_summary(self, run_id: str) -> dict[str, Any]:
        """Aggregate status for CLI `status --run-id`."""
        run = self.get_run(run_id)
        if run is None:
            return {"run": None, "tables": [], "totals": {}}

        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT status, count(*), "
                    "       COALESCE(sum(rows_extracted),0), "
                    "       COALESCE(sum(rows_loaded),0), "
                    "       COALESCE(sum(rows_rejected),0) "
                    "FROM {schema}.migration_table_state "
                    "WHERE run_id = %s GROUP BY status"
                ).format(schema=sql.Identifier(AUDIT_SCHEMA)),
                (run_id,),
            )
            buckets = {
                r[0]: {
                    "tables": int(r[1]),
                    "rows_extracted": int(r[2]),
                    "rows_loaded": int(r[3]),
                    "rows_rejected": int(r[4]),
                }
                for r in cur.fetchall()
            }
        return {
            "run": run,
            "buckets": buckets,
            "reject_total": self.reject_count(run_id),
        }
