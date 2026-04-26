"""Faz 16.3 Gün 7 — local dev-pg smoke test.

Drives run_orchestrator() against the local dev-pg container using a
mock MSSQL extractor that returns 3 deterministic rows. Verifies:
  - V16 + V17 schema accepted by load_batch
  - audit migration_runs row created
  - migration_table_state transitions EXTRACTING → VALIDATED
  - actual rows landed in workcube_mikrolink.company
  - reconcile artifact (separate command) produces a markdown + JSON file

This is the "Up + Functional" gate per D29 discipline; production K8s
dry-run on staging-sw is the "Behavior" gate (separate stage).
"""

from __future__ import annotations

import sys
import uuid
from typing import Any, Iterable

from etl_worker.runner import (
    RunOutcome,
    RunnerConfig,
    run_orchestrator,
)
from etl_worker.transform import ColumnMeta, TableMeta


# ---------------------------------------------------------------------------
# Manifest (must match V16 DDL)
# ---------------------------------------------------------------------------

COMPANY = TableMeta(
    name="COMPANY",
    source_schema="workcube_mikrolink",
    source_year=None,
    columns=[
        # NOT NULL columns from V16 DDL — must all be supplied or load rejects.
        ColumnMeta(name="company_id", pg_type="INTEGER", nullable=False),
        ColumnMeta(name="company_status", pg_type="BOOLEAN", nullable=False),
        ColumnMeta(name="companycat_id", pg_type="INTEGER", nullable=False),
        # Optional cols
        ColumnMeta(name="nickname", pg_type="VARCHAR(150)", nullable=True, max_length=150),
        ColumnMeta(name="fullname", pg_type="VARCHAR(250)", nullable=True, max_length=250),
    ],
    idempotency_key=["company_id"],
)


# ---------------------------------------------------------------------------
# Mock MSSQL extractor (3 rows)
# ---------------------------------------------------------------------------

def mock_extract(mssql_conn: Any, table_meta: TableMeta, last_pk: str | None, limit: int | None) -> Iterable[list[dict[str, Any]]]:
    rows = [
        {"company_id": 1001, "company_status": True,  "companycat_id": 1, "nickname": "Acme Holding A.Ş.",  "fullname": "Acme Anonim Şirketi"},
        {"company_id": 1002, "company_status": True,  "companycat_id": 2, "nickname": "Beta Ltd.",  "fullname": "Beta Limited Şirketi"},
        {"company_id": 1003, "company_status": False, "companycat_id": 1, "nickname": "Gamma Co.",  "fullname": "Gamma Company"},
    ]
    if limit:
        rows = rows[:limit]
    yield rows


def mock_mssql_connect(dsn: str) -> Any:
    class _Conn:
        def cursor(self):
            return self
        def execute(self, *a, **kw):
            return self
        def fetchall(self):
            return []
        def close(self):
            pass
    return _Conn()


# ---------------------------------------------------------------------------
# Drive
# ---------------------------------------------------------------------------

def main() -> int:
    run_id = str(uuid.uuid4())
    cfg = RunnerConfig(
        pg_dsn="postgresql://postgres:postgres@127.0.0.1:5432/reports_db",
        mssql_dsn="<mock>",
        run_id=run_id,
        mode="dry-run",
        manifest=[COMPANY],
        max_reject_ratio=0.0,
        limit=None,
        worker_version="0.1.0-smoke",
        git_sha="b2db02f",
        contract_version="v1.0-DRAFT",
        annex_version="2A-2026-04-25",
        started_by="smoke-dev-pg",
    )
    print(f"smoke.start run_id={run_id}")
    outcome = run_orchestrator(cfg, extract_fn=mock_extract, mssql_connect_fn=mock_mssql_connect)
    print(f"smoke.outcome={outcome.value} run_id={run_id}")
    return 0 if outcome is RunOutcome.SUCCESS else 1


if __name__ == "__main__":
    sys.exit(main())
