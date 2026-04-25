"""Faz 16.3 Gün 7 — ETL orchestrator (Codex iter-4 AGREE).

Lifecycle:
  1. Open control_conn (autocommit). Acquire pair advisory lock
     (hashtext('etl-worker-run'), hashtext(run_id)).
     Lock contended → return RunOutcome.LOCK_CONTENDED. NEVER mutate audit
     for a run we don't own.
  2. V16 PK preflight on control_conn (savepoint pattern, always rollback).
  3. Open audit_conn (autocommit) + load_conn (default tx) + mssql_conn.
  4. Resume vs new run: ownership flag tells the exception path whether it's
     safe to write `update_run_status` against the audit row.
  5. For each table: extract paginated → load_batch → audit batch hooks →
     mode-aware threshold check after each batch.
  6. finally: conditional advisory_unlock + None-safe close on all conns.

Failure model:
  - LoadReject (NO_RETRY at row level) → enriched into RejectRecord +
    persisted via audit (autocommit conn, survives any load rollback).
  - TRANSIENT batch error → exponential-backoff-with-jitter retry up to
    BackoffPolicy.max_attempts.
  - CRITICAL or threshold breach → audit ABORTED (only if run_owned) +
    raise → caller maps to exit code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable

import psycopg

from etl_worker.audit import AuditModule, RejectRecord
from etl_worker.load import LoadStats, load_batch
from etl_worker.preflight_v16 import SchemaContractError, preflight_v16_table_state_pk
from etl_worker.retry import (
    BackoffPolicy,
    RetryClass,
    ThresholdPolicy,
    classify_error,
    describe,
)
from etl_worker.transform import TableMeta, make_source_pk

log = logging.getLogger(__name__)

# Advisory lock namespace shared across all etl-worker run lifecycles.
LOCK_NAMESPACE = "etl-worker-run"


class RunOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    LOCK_CONTENDED = "LOCK_CONTENDED"
    RUN_EXISTS = "RUN_EXISTS"


class CriticalError(RuntimeError):
    """Unrecoverable batch-level failure — the runner aborts the run."""


class ThresholdBreachError(RuntimeError):
    """Mode-aware threshold exceeded — the runner aborts the run."""


# ============================================================================
# Configuration / dependency injection
# ============================================================================

# Caller provides extract + connection factories. Default factories use the
# real psycopg/pyodbc adapters; tests inject in-memory mocks.

ExtractBatchFn = Callable[
    [Any, TableMeta, str | None],  # (mssql_conn, table_meta, last_pk)
    Iterable[list[dict[str, Any]]],  # yields batches
]

PgConnectFn = Callable[[str, bool], Any]  # (dsn, autocommit) → psycopg.Connection
MssqlConnectFn = Callable[[str], Any]      # (dsn) → pyodbc.Connection


def _default_pg_connect(dsn: str, autocommit: bool) -> psycopg.Connection:
    return psycopg.connect(dsn, autocommit=autocommit)


def _default_mssql_connect(dsn: str) -> Any:
    import pyodbc
    return pyodbc.connect(dsn, timeout=30)


def _default_extract(mssql_conn: Any, table_meta: TableMeta, last_pk: str | None) -> Iterable[list[dict[str, Any]]]:
    """Placeholder paginated extract.

    Day 7 dry-run uses a thin generator wrapper around pyodbc; for unit
    tests this is replaced with a fixed list. The real extract logic
    (chunking, last_pk continuation) belongs to a future PR; for Day 7
    the dry-run with limit=1000 single-batch extract is sufficient.
    """
    raise NotImplementedError(
        "default extract not implemented — pass extract_fn to run_orchestrator()"
    )


# ============================================================================
# Helpers
# ============================================================================

def _state_key(table_meta: TableMeta) -> str:
    """Match AuditModule.get_resume_state() key shape."""
    year = "" if table_meta.source_year is None else str(table_meta.source_year)
    return f"{table_meta.name}|{table_meta.source_schema}|{year}"


def _last_pk_from_batch(batch: list[dict[str, Any]], table_meta: TableMeta) -> str | None:
    if not batch:
        return None
    last = batch[-1]
    return make_source_pk(last, table_meta.idempotency_key)


def _enrich_rejects(rejects: list[Any], run_id: str) -> list[RejectRecord]:
    return [
        RejectRecord(
            run_id=run_id,
            table_name=lr.table_name,
            source_schema=lr.source_schema,
            source_year=lr.source_year,
            source_pk=lr.source_pk,
            column_name=lr.column_name,
            reject_reason=lr.reject_reason,
            severity=lr.severity,
            pg_error_code=lr.pg_error_code,
            pg_error_message=lr.pg_error_message,
            source_value=lr.source_value,
            raw_payload=lr.raw_payload,
        )
        for lr in rejects
    ]


def _acquire_lock(control_conn: psycopg.Connection, run_id: str) -> bool:
    with control_conn.cursor() as cur:
        cur.execute(
            "SELECT pg_try_advisory_lock(hashtext(%s), hashtext(%s))",
            (LOCK_NAMESPACE, run_id),
        )
        row = cur.fetchone()
    return bool(row[0]) if row else False


def _release_lock(control_conn: psycopg.Connection, run_id: str) -> None:
    with control_conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_unlock(hashtext(%s), hashtext(%s))",
            (LOCK_NAMESPACE, run_id),
        )


# ============================================================================
# Orchestrator
# ============================================================================

@dataclass
class RunnerConfig:
    pg_dsn: str
    mssql_dsn: str
    run_id: str
    mode: str | None
    manifest: list[TableMeta]
    resume: bool = False
    max_reject_ratio: float = 0.0
    source_database: str = "workcube_mikrolink"
    worker_version: str = "0.1.0"
    git_sha: str | None = None
    contract_version: str | None = None
    annex_version: str | None = None
    started_by: str | None = None
    include_raw_payload: bool = False


def run_orchestrator(
    cfg: RunnerConfig,
    extract_fn: ExtractBatchFn = _default_extract,
    pg_connect_fn: PgConnectFn = _default_pg_connect,
    mssql_connect_fn: MssqlConnectFn = _default_mssql_connect,
    backoff: BackoffPolicy | None = None,
) -> RunOutcome:
    """Drive an ETL run end-to-end. Returns RunOutcome (caller maps exit code).

    No sys.exit() inside this function. All error mutations of the audit
    `migration_runs` row are guarded by `run_owned` so a contention or a
    create_run UniqueViolation never corrupts another run's history.
    """
    backoff = backoff or BackoffPolicy()
    control_conn = None
    audit_conn = None
    load_conn = None
    mssql_conn = None
    audit: AuditModule | None = None
    lock_acquired = False
    run_owned = False

    try:
        # 1. control_conn + advisory lock
        control_conn = pg_connect_fn(cfg.pg_dsn, True)
        lock_acquired = _acquire_lock(control_conn, cfg.run_id)
        if not lock_acquired:
            log.error("advisory_lock_contended run_id=%s ns=%s", cfg.run_id, LOCK_NAMESPACE)
            return RunOutcome.LOCK_CONTENDED

        # 2. V16 PK preflight under lock (rollback-capable on control_conn)
        preflight_v16_table_state_pk(control_conn)

        # 3. Audit + load + mssql conns
        audit_conn = pg_connect_fn(cfg.pg_dsn, True)
        load_conn = pg_connect_fn(cfg.pg_dsn, False)
        mssql_conn = mssql_connect_fn(cfg.mssql_dsn)
        audit = AuditModule(audit_conn)

        # 4. Resume vs new run
        mode = cfg.mode
        state: dict[str, dict[str, Any]] = {}
        if cfg.resume:
            run_record = audit.get_run(cfg.run_id)
            if run_record is None:
                log.error("resume_run_not_found run_id=%s", cfg.run_id)
                return RunOutcome.FAILED
            mode = run_record["mode"]
            state = audit.get_resume_state(cfg.run_id)
            run_owned = True
        else:
            if mode is None:
                log.error("new_run_missing_mode run_id=%s", cfg.run_id)
                return RunOutcome.FAILED
            try:
                audit.create_run(
                    run_id=cfg.run_id,
                    mode=mode,
                    source_database=cfg.source_database,
                    worker_version=cfg.worker_version,
                    git_sha=cfg.git_sha,
                    contract_version=cfg.contract_version,
                    annex_version=cfg.annex_version,
                    started_by=cfg.started_by,
                )
                run_owned = True
            except psycopg.errors.UniqueViolation:
                log.error("run_id_already_exists run_id=%s", cfg.run_id)
                return RunOutcome.RUN_EXISTS

        # 5. Sequential table loop with retry + threshold abort
        threshold = ThresholdPolicy(mode=mode, max_reject_ratio=cfg.max_reject_ratio)
        rejected_total = 0
        processed_total = 0  # attempted rows, includes rejected (documented in CLAUDE.md)

        for table_meta in cfg.manifest:
            key = _state_key(table_meta)
            existing = state.get(key, {})
            if existing.get("status") == "VALIDATED":
                log.info("table.skip_validated table=%s", table_meta.name)
                continue

            audit.upsert_table_state(
                run_id=cfg.run_id,
                table_name=table_meta.name,
                source_schema=table_meta.source_schema,
                source_year=table_meta.source_year,
                status="EXTRACTING",
            )
            last_pk = existing.get("last_pk")
            batch_no = int(existing.get("batch_no") or 0)

            for batch in extract_fn(mssql_conn, table_meta, last_pk):
                batch_no += 1
                attempt = 0
                while True:
                    try:
                        stats = load_batch(
                            load_conn, batch, table_meta,
                            include_raw_payload=cfg.include_raw_payload,
                        )
                        # Reject persistence on the autocommit audit conn
                        # (survives any load rollback).
                        if stats.rejects:
                            audit.insert_rejects_batch(_enrich_rejects(stats.rejects, cfg.run_id))
                        audit.record_batch_success(
                            run_id=cfg.run_id,
                            table_name=table_meta.name,
                            source_schema=table_meta.source_schema,
                            source_year=table_meta.source_year,
                            rows_loaded=stats.inserted + stats.updated,
                            last_pk=_last_pk_from_batch(batch, table_meta),
                            batch_no=batch_no,
                        )
                        # Codex iter-4 implementation note: also bump rows_rejected
                        # counter when there are rejects, so audit table_state
                        # reflects truth.
                        if stats.rejected:
                            audit.record_batch_failure(
                                run_id=cfg.run_id,
                                table_name=table_meta.name,
                                source_schema=table_meta.source_schema,
                                source_year=table_meta.source_year,
                                batch_no=batch_no,
                                rows_rejected=stats.rejected,
                            )
                        rejected_total += stats.rejected
                        processed_total += len(batch)
                        break
                    except psycopg.errors.Error as e:
                        cls = classify_error(e)
                        d = describe(e)
                        log.warning(
                            "batch_error run_id=%s table=%s batch_no=%s attempt=%s class=%s sqlstate=%s msg=%s",
                            cfg.run_id, table_meta.name, batch_no, attempt,
                            cls.value, d["sqlstate"], d["message"][:120],
                        )
                        if cls == RetryClass.CRITICAL:
                            if run_owned:
                                _safe_audit_status(
                                    audit, cfg.run_id, "ABORTED",
                                    f"CRITICAL {d['sqlstate']}: {d['message'][:300]}",
                                )
                            raise CriticalError(d["message"]) from e
                        if cls == RetryClass.NO_RETRY:
                            audit.insert_reject(RejectRecord(
                                run_id=cfg.run_id,
                                table_name=table_meta.name,
                                source_schema=table_meta.source_schema,
                                source_year=table_meta.source_year,
                                source_pk=None,
                                column_name=None,
                                reject_reason="BATCH_LEVEL_NO_RETRY",
                                severity="ERROR",
                                pg_error_code=d["sqlstate"],
                                pg_error_message=d["message"][:500],
                                source_value=None,
                                raw_payload=None,
                            ))
                            audit.record_batch_failure(
                                run_id=cfg.run_id,
                                table_name=table_meta.name,
                                source_schema=table_meta.source_schema,
                                source_year=table_meta.source_year,
                                batch_no=batch_no,
                                rows_rejected=len(batch),
                            )
                            rejected_total += len(batch)
                            processed_total += len(batch)
                            break
                        # TRANSIENT
                        attempt += 1
                        if attempt > backoff.max_attempts:
                            if run_owned:
                                _safe_audit_status(
                                    audit, cfg.run_id, "ABORTED",
                                    f"max retries exhausted: {d['message'][:300]}",
                                )
                            raise CriticalError("max retries exhausted") from e
                        backoff.sleep_for(attempt)

                if threshold.should_abort(rejected_total, processed_total):
                    if run_owned:
                        _safe_audit_status(
                            audit, cfg.run_id, "ABORTED",
                            f"threshold breach mode={mode} rejected={rejected_total} processed={processed_total}",
                        )
                    raise ThresholdBreachError(
                        f"threshold breach mode={mode} rejected={rejected_total}/{processed_total}"
                    )

            audit.upsert_table_state(
                run_id=cfg.run_id,
                table_name=table_meta.name,
                source_schema=table_meta.source_schema,
                source_year=table_meta.source_year,
                status="VALIDATED",
                batch_no=batch_no,
            )

        if run_owned and audit is not None:
            audit.update_run_status(cfg.run_id, "SUCCESS")
        return RunOutcome.SUCCESS

    except (CriticalError, ThresholdBreachError):
        return RunOutcome.ABORTED
    except SchemaContractError:
        # Preflight failure — never mutate audit (sentinel-only side effects).
        log.exception("v16_preflight_failed")
        return RunOutcome.FAILED
    except Exception as e:
        # Ownership guard (Codex iter-3 fix): only mutate if WE own the run.
        if audit is not None and run_owned:
            _safe_audit_status(audit, cfg.run_id, "FAILED", str(e)[:500])
        log.exception("runner_unexpected_error run_id=%s", cfg.run_id)
        return RunOutcome.FAILED

    finally:
        if lock_acquired and control_conn is not None:
            try:
                _release_lock(control_conn, cfg.run_id)
            except Exception:
                log.exception("advisory_unlock_failed run_id=%s", cfg.run_id)
        for c in (load_conn, audit_conn, mssql_conn, control_conn):
            if c is not None:
                try:
                    c.close()
                except Exception:
                    log.exception("conn_close_failed")


def _safe_audit_status(audit: AuditModule, run_id: str, status: str, error_summary: str) -> None:
    """Wrapped update_run_status so the failure path never hides the original
    exception with a secondary audit-write failure."""
    try:
        audit.update_run_status(run_id, status, error_summary=error_summary)
    except Exception:
        log.exception("audit_status_write_failed run_id=%s status=%s", run_id, status)
