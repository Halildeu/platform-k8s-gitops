"""Faz 16.3 Gün 7 — Orchestrator tests (Codex iter-4 AGREE).

Verified contracts:
  - Lock contention → RunOutcome.LOCK_CONTENDED, audit NEVER mutated.
  - V16 SchemaContractError → RunOutcome.FAILED, audit NEVER mutated.
  - create_run UniqueViolation → RUN_EXISTS, existing audit row NOT mutated.
  - Happy path → SUCCESS, audit transitions table_state EXTRACTING→VALIDATED
    and run_status→SUCCESS exactly once.
  - Per-batch TRANSIENT exhausted → ABORTED, audit ABORTED with summary.
  - Per-batch CRITICAL → ABORTED, audit ABORTED with summary.
  - Threshold breach (final-delta first reject) → ABORTED.
  - Resume skips VALIDATED tables (extract_fn never called for them).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import psycopg
import pytest

from etl_worker.audit import AuditModule
from etl_worker.preflight_v16 import SchemaContractError
from etl_worker.retry import BackoffPolicy
from etl_worker.runner import (
    RunnerConfig,
    RunOutcome,
    run_orchestrator,
)
from etl_worker.transform import ColumnMeta, TableMeta


# ============================================================================
# Common fixtures
# ============================================================================

def _company_meta() -> TableMeta:
    return TableMeta(
        name="COMPANY",
        source_schema="workcube_mikrolink",
        source_year=None,
        columns=[
            ColumnMeta(name="company_id", pg_type="BIGINT", nullable=False),
            ColumnMeta(name="company_name", pg_type="VARCHAR(255)", nullable=False, max_length=255),
        ],
        idempotency_key=["company_id"],
    )


def _bank_meta() -> TableMeta:
    return TableMeta(
        name="BANK",
        source_schema="workcube_mikrolink",
        source_year=None,
        columns=[
            ColumnMeta(name="bank_id", pg_type="BIGINT", nullable=False),
        ],
        idempotency_key=["bank_id"],
    )


def _make_pg_conn(autocommit: bool = True, lock_acquired: bool = True) -> MagicMock:
    cur = MagicMock(name="cursor")
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    # The lock probe and any other reads default to (True,)
    cur.fetchone.return_value = (lock_acquired,)
    cur.fetchall.return_value = []
    cur.rowcount = 1

    tx = MagicMock(name="tx")
    tx.__enter__ = MagicMock(return_value=tx)
    tx.__exit__ = MagicMock(return_value=False)

    conn = MagicMock(name="pg_conn")
    conn.autocommit = autocommit
    conn.cursor.return_value = cur
    conn.transaction.return_value = tx
    conn._cur = cur
    return conn


@pytest.fixture
def lock_conn():
    return _make_pg_conn(autocommit=True, lock_acquired=True)


@pytest.fixture
def audit_conn():
    return _make_pg_conn(autocommit=True)


@pytest.fixture
def load_conn():
    return _make_pg_conn(autocommit=False)


@pytest.fixture
def mssql_conn():
    return MagicMock(name="mssql_conn")


@pytest.fixture
def cfg():
    return RunnerConfig(
        pg_dsn="postgresql://stub",
        mssql_dsn="DRIVER=stub",
        run_id="11111111-1111-1111-1111-111111111111",
        mode="initial",
        manifest=[_company_meta()],
        max_reject_ratio=0.0,
    )


@pytest.fixture
def fast_backoff():
    """Backoff with zero sleep so tests don't actually wait."""
    p = BackoffPolicy(max_attempts=2, base_seconds=0, cap_seconds=0)
    return p


def _connect_factory(*conns):
    """Return a callable that yields connections in order on successive calls."""
    queue = list(conns)

    def fn(dsn: str, autocommit: bool):
        return queue.pop(0)
    return fn


def _mssql_factory(conn):
    def fn(dsn: str):
        return conn
    return fn


def _stable_extract(batches: list[list[dict]]):
    """Return an extract_fn that yields the given batches once.

    Codex iter-5/6: extract_fn signature now (mssql_conn, table_meta, last_pk, limit)
    so tests must accept the limit arg.
    """
    def fn(mssql_conn, table_meta, last_pk, limit):
        for b in batches:
            yield b
    return fn


def _raw_row(i: int, name: str = "Acme") -> dict:
    """RAW MSSQL-shaped row (just business cols). Runner runs transform_row()
    on this before handing to load_batch. This mirrors the real path Codex
    iter-5 said was missing in iter-4."""
    return {
        "company_id": i,
        "company_name": name,
    }


# ============================================================================
# Lock contention
# ============================================================================

def test_lock_contended_no_audit_mutate(cfg, mssql_conn):
    """When advisory lock is contended, the runner must:
       - return LOCK_CONTENDED
       - NOT touch the audit module (the run belongs to another worker)
       - close conns properly"""
    contested = _make_pg_conn(autocommit=True, lock_acquired=False)

    with patch("etl_worker.runner.AuditModule") as audit_cls:
        outcome = run_orchestrator(
            cfg,
            extract_fn=_stable_extract([[_raw_row(1)]]),
            pg_connect_fn=_connect_factory(contested),
            mssql_connect_fn=_mssql_factory(mssql_conn),
        )
    assert outcome is RunOutcome.LOCK_CONTENDED
    audit_cls.assert_not_called()
    contested.close.assert_called_once()


# ============================================================================
# V16 preflight failure → FAILED, audit untouched
# ============================================================================

def test_lineage_preflight_failure_no_audit_mutate(cfg, lock_conn, mssql_conn):
    """Codex iter-8/9: when V17 has not been applied (final tables missing the
    lineage columns), the runner must fail-fast with:
       - NO AuditModule instantiation (audit_conn never opened)
       - NO MSSQL connection (mssql_connect_fn never called)
       - control_conn closed cleanly
    The lineage preflight runs on control_conn BEFORE audit/load/mssql conns
    open, so a stale schema never wastes downstream resources."""
    mssql_factory = MagicMock(return_value=mssql_conn)
    pg_factory = MagicMock(return_value=lock_conn)

    with patch("etl_worker.runner.preflight_v16_table_state_pk"), \
         patch(
            "etl_worker.runner.preflight_final_table_lineage",
            side_effect=SchemaContractError("missing source_pk"),
         ), patch("etl_worker.runner.AuditModule") as audit_cls:
        outcome = run_orchestrator(
            cfg,
            extract_fn=_stable_extract([[_raw_row(1)]]),
            pg_connect_fn=pg_factory,
            mssql_connect_fn=mssql_factory,
        )
    assert outcome is RunOutcome.FAILED
    audit_cls.assert_not_called()
    # MSSQL connection must NEVER open on a stale-schema run
    mssql_factory.assert_not_called()
    # Only the control_conn was opened (one pg_factory call)
    assert pg_factory.call_count == 1
    lock_conn.close.assert_called_once()


def test_v16_preflight_failure_no_audit_mutate(cfg, lock_conn, mssql_conn):
    """A SchemaContractError before audit_conn even opens must surface as
    FAILED with NO audit module instantiation."""
    with patch(
        "etl_worker.runner.preflight_v16_table_state_pk",
        side_effect=SchemaContractError("V16 PK contract failure"),
    ), patch("etl_worker.runner.AuditModule") as audit_cls:
        outcome = run_orchestrator(
            cfg,
            extract_fn=_stable_extract([[_raw_row(1)]]),
            pg_connect_fn=_connect_factory(lock_conn),
            mssql_connect_fn=_mssql_factory(mssql_conn),
        )
    assert outcome is RunOutcome.FAILED
    audit_cls.assert_not_called()
    lock_conn.close.assert_called_once()


# ============================================================================
# create_run UniqueViolation → RUN_EXISTS, no mutate
# ============================================================================

def test_run_exists_does_not_mutate_existing_row(cfg, lock_conn, audit_conn, load_conn, mssql_conn):
    audit = MagicMock(spec=AuditModule)
    audit.create_run.side_effect = psycopg.errors.UniqueViolation("dup run_id")

    with patch("etl_worker.runner.preflight_v16_table_state_pk"), \
         patch("etl_worker.runner.preflight_final_table_lineage"), \
         patch("etl_worker.runner.AuditModule", return_value=audit):
        outcome = run_orchestrator(
            cfg,
            extract_fn=_stable_extract([[_raw_row(1)]]),
            pg_connect_fn=_connect_factory(lock_conn, audit_conn, load_conn),
            mssql_connect_fn=_mssql_factory(mssql_conn),
        )
    assert outcome is RunOutcome.RUN_EXISTS
    # Hard contract: never mutate status of an existing run we don't own
    audit.update_run_status.assert_not_called()
    audit.upsert_table_state.assert_not_called()


# ============================================================================
# Happy path
# ============================================================================

def test_happy_path_validates_table_and_marks_run_success(
    cfg, lock_conn, audit_conn, load_conn, mssql_conn, fast_backoff,
):
    audit = MagicMock(spec=AuditModule)

    with patch("etl_worker.runner.preflight_v16_table_state_pk"), \
         patch("etl_worker.runner.preflight_final_table_lineage"), \
         patch("etl_worker.runner.AuditModule", return_value=audit), \
         patch("etl_worker.runner.load_batch") as lb:
        from etl_worker.load import LoadStats
        lb.return_value = LoadStats(inserted=2, updated=0, rejected=0)
        outcome = run_orchestrator(
            cfg,
            extract_fn=_stable_extract([[_raw_row(1), _raw_row(2)]]),
            pg_connect_fn=_connect_factory(lock_conn, audit_conn, load_conn),
            mssql_connect_fn=_mssql_factory(mssql_conn),
            backoff=fast_backoff,
        )

    assert outcome is RunOutcome.SUCCESS
    audit.create_run.assert_called_once()
    # State transitions: EXTRACTING → record_batch_success → VALIDATED
    statuses = [c.kwargs.get("status") for c in audit.upsert_table_state.call_args_list]
    assert "EXTRACTING" in statuses
    assert "VALIDATED" in statuses
    audit.record_batch_success.assert_called()
    audit.update_run_status.assert_called_with(cfg.run_id, "SUCCESS")


# ============================================================================
# CRITICAL during batch → ABORTED + audit ABORTED
# ============================================================================

def test_critical_error_aborts_with_audit_status(
    cfg, lock_conn, audit_conn, load_conn, mssql_conn, fast_backoff,
):
    audit = MagicMock(spec=AuditModule)

    def err(*args, **kwargs):
        e = psycopg.errors.UndefinedTable("missing")
        object.__setattr__(e, "sqlstate", "42P01")
        raise e

    with patch("etl_worker.runner.preflight_v16_table_state_pk"), \
         patch("etl_worker.runner.preflight_final_table_lineage"), \
         patch("etl_worker.runner.AuditModule", return_value=audit), \
         patch("etl_worker.runner.load_batch", side_effect=err):
        outcome = run_orchestrator(
            cfg,
            extract_fn=_stable_extract([[_raw_row(1)]]),
            pg_connect_fn=_connect_factory(lock_conn, audit_conn, load_conn),
            mssql_connect_fn=_mssql_factory(mssql_conn),
            backoff=fast_backoff,
        )

    assert outcome is RunOutcome.ABORTED
    # update_run_status called with ABORTED + summary string
    aborted_calls = [c for c in audit.update_run_status.call_args_list
                     if "ABORTED" in c.args]
    assert aborted_calls, "expected ABORTED status update"
    assert "CRITICAL" in aborted_calls[0].kwargs.get("error_summary", "")


# ============================================================================
# TRANSIENT exhausts retries → ABORTED
# ============================================================================

def test_transient_retry_exhausted_aborts(
    cfg, lock_conn, audit_conn, load_conn, mssql_conn, fast_backoff,
):
    audit = MagicMock(spec=AuditModule)

    def err(*args, **kwargs):
        e = psycopg.errors.SerializationFailure("conflict")
        object.__setattr__(e, "sqlstate", "40001")
        raise e

    with patch("etl_worker.runner.preflight_v16_table_state_pk"), \
         patch("etl_worker.runner.preflight_final_table_lineage"), \
         patch("etl_worker.runner.AuditModule", return_value=audit), \
         patch("etl_worker.runner.load_batch", side_effect=err):
        outcome = run_orchestrator(
            cfg,
            extract_fn=_stable_extract([[_raw_row(1)]]),
            pg_connect_fn=_connect_factory(lock_conn, audit_conn, load_conn),
            mssql_connect_fn=_mssql_factory(mssql_conn),
            backoff=fast_backoff,
        )

    assert outcome is RunOutcome.ABORTED
    aborted = [c for c in audit.update_run_status.call_args_list
               if "ABORTED" in c.args]
    assert aborted
    assert "max retries exhausted" in aborted[0].kwargs.get("error_summary", "")


# ============================================================================
# Threshold breach → ABORTED (final-delta strict)
# ============================================================================

def test_threshold_breach_final_delta_aborts(lock_conn, audit_conn, load_conn, mssql_conn, fast_backoff):
    """final-delta strict: 1 reject in a 1-row batch → abort the run."""
    cfg = RunnerConfig(
        pg_dsn="x", mssql_dsn="y",
        run_id="22222222-2222-2222-2222-222222222222",
        mode="final-delta",
        manifest=[_company_meta()],
        max_reject_ratio=0.0,
    )
    audit = MagicMock(spec=AuditModule)

    with patch("etl_worker.runner.preflight_v16_table_state_pk"), \
         patch("etl_worker.runner.preflight_final_table_lineage"), \
         patch("etl_worker.runner.AuditModule", return_value=audit), \
         patch("etl_worker.runner.load_batch") as lb:
        from etl_worker.load import LoadReject, LoadStats
        # 0 inserted, 1 rejected → threshold strict breach
        lb.return_value = LoadStats(
            inserted=0,
            rejected=1,
            rejects=[
                LoadReject(
                    table_name="COMPANY",
                    source_schema="workcube_mikrolink",
                    source_year=None,
                    source_pk='["7"]',
                    column_name=None,
                    reject_reason="LOAD_NO_RETRY",
                    severity="ERROR",
                    pg_error_code="23502",
                    pg_error_message="not null violation",
                    source_value=None,
                    raw_payload=None,
                )
            ],
        )
        outcome = run_orchestrator(
            cfg,
            extract_fn=_stable_extract([[_raw_row(7)]]),
            pg_connect_fn=_connect_factory(lock_conn, audit_conn, load_conn),
            mssql_connect_fn=_mssql_factory(mssql_conn),
            backoff=fast_backoff,
        )

    assert outcome is RunOutcome.ABORTED
    aborted = [c for c in audit.update_run_status.call_args_list
               if "ABORTED" in c.args]
    assert aborted
    assert "threshold breach" in aborted[0].kwargs.get("error_summary", "")


# ============================================================================
# Resume skips VALIDATED tables
# ============================================================================

# ============================================================================
# Transform-in-runner real path (Codex iter-5/6 fix)
# ============================================================================

def test_runner_calls_transform_row_before_load(
    cfg, lock_conn, audit_conn, load_conn, mssql_conn, fast_backoff,
):
    """The runner must run raw rows through transform_row() before passing
    to load_batch(). This guards against the "fake path" Codex iter-5 caught
    where tests injected pre-transformed rows so the missing transform call
    went unnoticed."""
    audit = MagicMock(spec=AuditModule)

    received_typed_rows: list = []
    def fake_load_batch(conn, rows, table_meta, **kw):
        from etl_worker.load import LoadStats
        received_typed_rows.extend(rows)
        return LoadStats(inserted=len(rows))

    with patch("etl_worker.runner.preflight_v16_table_state_pk"), \
         patch("etl_worker.runner.preflight_final_table_lineage"), \
         patch("etl_worker.runner.AuditModule", return_value=audit), \
         patch("etl_worker.runner.load_batch", side_effect=fake_load_batch):
        outcome = run_orchestrator(
            cfg,
            extract_fn=_stable_extract([[_raw_row(1, "Acme"), _raw_row(2, "Beta")]]),
            pg_connect_fn=_connect_factory(lock_conn, audit_conn, load_conn),
            mssql_connect_fn=_mssql_factory(mssql_conn),
            backoff=fast_backoff,
        )

    assert outcome is RunOutcome.SUCCESS
    # transform_row populated audit columns + content_hash
    assert len(received_typed_rows) == 2
    for r in received_typed_rows:
        assert r["source_schema"] == "workcube_mikrolink"
        assert r["source_table"] == "COMPANY"
        assert "source_pk" in r
        assert "content_hash" in r
        assert len(r["content_hash"]) == 64  # SHA-256 hex


def test_runner_transform_reject_persists_without_load(lock_conn, audit_conn, load_conn, mssql_conn, fast_backoff):
    """A row that fails transform (e.g. NOT_NULL_VIOLATION) must be persisted
    to migration_rejects and never reach load_batch."""
    # Permissive ratio so the single reject doesn't trip the threshold; we're
    # asserting the persistence path, not the abort path.
    cfg = RunnerConfig(
        pg_dsn="x", mssql_dsn="y",
        run_id="44444444-4444-4444-4444-444444444444",
        mode="initial",
        manifest=[_company_meta()],
        max_reject_ratio=1.0,  # allow up to 100% rejected
    )
    audit = MagicMock(spec=AuditModule)

    with patch("etl_worker.runner.preflight_v16_table_state_pk"), \
         patch("etl_worker.runner.preflight_final_table_lineage"), \
         patch("etl_worker.runner.AuditModule", return_value=audit), \
         patch("etl_worker.runner.load_batch") as lb:
        from etl_worker.load import LoadStats
        lb.return_value = LoadStats(inserted=0)
        outcome = run_orchestrator(
            cfg,
            # company_id None violates NOT NULL → transform_row rejects this row
            extract_fn=_stable_extract([[{"company_id": None, "company_name": "X"}]]),
            pg_connect_fn=_connect_factory(lock_conn, audit_conn, load_conn),
            mssql_connect_fn=_mssql_factory(mssql_conn),
            backoff=fast_backoff,
        )

    assert outcome is RunOutcome.SUCCESS
    audit.insert_rejects_batch.assert_called()
    # The rejects passed in must include reject_reason "NOT_NULL_VIOLATION"
    rejects_call = audit.insert_rejects_batch.call_args
    rejects = rejects_call.args[0]
    assert any(r.reject_reason == "NOT_NULL_VIOLATION" for r in rejects)
    # load_batch was NOT called (typed_batch was empty)
    lb.assert_not_called()


def test_resume_skips_validated_tables(lock_conn, audit_conn, load_conn, mssql_conn, fast_backoff):
    cfg = RunnerConfig(
        pg_dsn="x", mssql_dsn="y",
        run_id="33333333-3333-3333-3333-333333333333",
        mode=None,  # filled from audit row
        manifest=[_company_meta(), _bank_meta()],
        resume=True,
        max_reject_ratio=0.0,
    )
    audit = MagicMock(spec=AuditModule)
    audit.get_run.return_value = {
        "run_id": cfg.run_id, "mode": "initial", "status": "RUNNING",
        "source_database": "wm", "started_at": None, "completed_at": None,
    }
    audit.get_resume_state.return_value = {
        "COMPANY|workcube_mikrolink|": {"status": "VALIDATED", "last_pk": '["3"]', "batch_no": 5},
        "BANK|workcube_mikrolink|":    {"status": "LOADING",   "last_pk": None,    "batch_no": 0},
    }

    extract_calls: list[str] = []
    def extract_fn(mssql_conn, table_meta, last_pk, limit):
        extract_calls.append(table_meta.name)
        if table_meta.name == "BANK":
            yield [{"bank_id": 1}]
        # else: nothing yielded

    with patch("etl_worker.runner.preflight_v16_table_state_pk"), \
         patch("etl_worker.runner.preflight_final_table_lineage"), \
         patch("etl_worker.runner.AuditModule", return_value=audit), \
         patch("etl_worker.runner.load_batch") as lb:
        from etl_worker.load import LoadStats
        lb.return_value = LoadStats(inserted=1)
        outcome = run_orchestrator(
            cfg,
            extract_fn=extract_fn,
            pg_connect_fn=_connect_factory(lock_conn, audit_conn, load_conn),
            mssql_connect_fn=_mssql_factory(mssql_conn),
            backoff=fast_backoff,
        )

    assert outcome is RunOutcome.SUCCESS
    # COMPANY validated → skip; only BANK extracted
    assert extract_calls == ["BANK"]
    # No create_run on resume — we attached to an existing audit row
    audit.create_run.assert_not_called()
    audit.update_run_status.assert_called_with(cfg.run_id, "SUCCESS")
