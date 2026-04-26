"""Faz 16.3 — ETL Worker CLI (Codex iter-7 REVISE).

Usage:
    etl-worker validate-manifest
    etl-worker inspect-source --tables COMPANY
    etl-worker run --mode initial --run-id <uuid> --tables COMPANY,COMPANY_PARTNER --dry-run
    etl-worker run --mode final-delta --run-id <uuid>
    etl-worker run --mode initial --run-id <uuid> --resume
    etl-worker status --run-id <uuid>
    etl-worker reconcile --run-id <uuid> --output docs/migration/reconcile-YYYYMMDD.md
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import click
import structlog

from etl_worker.config import Config

log = structlog.get_logger()


@click.group()
@click.option("--config-dir", default="config", type=click.Path(exists=True), help="Manifest dir (config/tables.yaml)")
@click.pass_context
def main(ctx: click.Context, config_dir: str) -> None:
    """Workcube MSSQL → PG ETL worker (Faz 16.3)."""
    ctx.ensure_object(dict)
    ctx.obj["config_dir"] = Path(config_dir)
    ctx.obj["config"] = Config.from_env()
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


@main.command("validate-manifest")
@click.pass_context
def validate_manifest(ctx: click.Context) -> None:
    """tables.yaml syntax + INFORMATION_SCHEMA cross-check."""
    config_dir: Path = ctx.obj["config_dir"]
    manifest_path = config_dir / "tables.yaml"

    if not manifest_path.exists():
        click.echo(f"FAIL: {manifest_path} not found", err=True)
        sys.exit(1)

    import yaml

    manifest = yaml.safe_load(manifest_path.read_text())
    tables = manifest.get("tables", [])

    log.info("manifest.loaded", path=str(manifest_path), table_count=len(tables))
    for t in tables:
        if not t.get("idempotency_key"):
            click.echo(f"FAIL: {t['name']} missing idempotency_key", err=True)
            sys.exit(1)

    # TODO Gün 5: MSSQL INFORMATION_SCHEMA cross-check
    click.echo(f"✓ Manifest valid ({len(tables)} tables, syntax OK)")


@main.command("inspect-source")
@click.option("--tables", required=False, help="CSV table list (default: all from manifest)")
@click.pass_context
def inspect_source(ctx: click.Context, tables: str | None) -> None:
    """MSSQL connection + per-table row count."""
    config: Config = ctx.obj["config"]

    log.info("inspect.start", tables=tables or "all")

    try:
        import pyodbc
    except ImportError:
        click.echo("FAIL: pyodbc not installed (pip install pyodbc)", err=True)
        sys.exit(1)

    try:
        conn = pyodbc.connect(config.mssql_dsn, timeout=10)
    except Exception as e:
        click.echo(f"FAIL: MSSQL connection error: {e}", err=True)
        sys.exit(1)

    cursor = conn.cursor()
    cursor.execute("SELECT @@VERSION")
    version = cursor.fetchone()
    log.info("mssql.connected", version=str(version[0])[:80])

    if tables:
        table_list = tables.split(",")
        for t in table_list:
            cursor.execute(f"SELECT COUNT(*) FROM workcube_mikrolink.{t.strip()}")
            count = cursor.fetchone()[0]
            click.echo(f"  {t.strip():<30} rowCount={count}")
    else:
        click.echo("(no --tables specified, manifest iterate TODO)")

    conn.close()
    click.echo("✓ Inspect complete")


@main.command("run")
@click.option(
    "--mode",
    type=click.Choice(["initial", "final-delta", "reconcile-only", "dry-run"]),
    required=False,
    default=None,
    help="Required for new runs; ignored on --resume (mode read from audit).",
)
@click.option("--run-id", default=None, help="UUID (auto-generated if omitted)")
@click.option("--tables", help="CSV (default: manifest all)")
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Per-table row cap; passed to extractor and reconcile scope.",
)
@click.option("--resume", is_flag=True, help="Resume an existing run; requires --run-id")
@click.pass_context
def run(
    ctx: click.Context,
    mode: str | None,
    run_id: str | None,
    tables: str | None,
    limit: int | None,
    resume: bool,
) -> None:
    """ETL run — MSSQL extract → transform → PG canonical load → audit.

    For dry-run mode use `--mode dry-run`; the legacy `--dry-run` flag was
    removed in Day 7 to avoid double-meaning with `--mode dry-run` (Codex
    iter-5 fix).
    """
    if resume and not run_id:
        click.echo("FAIL: --resume requires --run-id", err=True)
        sys.exit(2)
    if not resume and mode is None:
        click.echo("FAIL: --mode is required for new runs (use --resume to continue an existing run)", err=True)
        sys.exit(2)

    rid = run_id or str(uuid.uuid4())

    if resume:
        # Day 7: validate state then call orchestrator. The orchestrator
        # itself reads run/state, but we surface a friendly preview before
        # spinning up MSSQL + load conns.
        try:
            import psycopg

            from etl_worker.audit import AuditModule

            config: Config = ctx.obj["config"]
            with psycopg.connect(config.pg_dsn, autocommit=True) as audit_conn:
                audit = AuditModule(audit_conn)
                run_record = audit.get_run(rid)
                state = audit.get_resume_state(rid)
        except Exception as e:
            click.echo(f"FAIL: resume state lookup error: {e}", err=True)
            sys.exit(2)

        if run_record is None:
            click.echo(f"FAIL: run_id={rid} not found in migration_runs", err=True)
            sys.exit(2)
        if not state:
            click.echo(
                f"FAIL: no migration_table_state rows for run_id={rid} "
                "(was the run created but never started a table?)",
                err=True,
            )
            sys.exit(2)

        # Mode comes from the audit row, not the user (Codex iter-8 fix).
        log.info("run.start", run_id=rid, mode=run_record["mode"], resume=True)
        skipped = sum(1 for v in state.values() if v["status"] == "VALIDATED")
        pending = len(state) - skipped
        click.echo(f"RESUME plan — run_id={rid}")
        click.echo(f"  audit mode              : {run_record['mode']}")
        click.echo(f"  audit status            : {run_record['status']}")
        click.echo(f"  total table_state rows  : {len(state)}")
        click.echo(f"  validated (skip)        : {skipped}")
        click.echo(f"  pending / loading       : {pending}")

        # Hand off to the orchestrator.
        from etl_worker.runner import RunnerConfig, run_orchestrator
        manifest = _load_manifest(ctx.obj["config_dir"], tables)
        runner_cfg = RunnerConfig(
            pg_dsn=config.pg_dsn,
            mssql_dsn=config.mssql_dsn,
            run_id=rid,
            mode=run_record["mode"],
            manifest=manifest,
            resume=True,
            max_reject_ratio=config.max_reject_ratio,
            worker_version=config.worker_version,
            git_sha=config.git_sha,
            contract_version=config.contract_version,
            annex_version=config.annex_version,
        )
        outcome = run_orchestrator(runner_cfg)
        _exit_for_outcome(outcome, rid)
        return

    # Day 7: orchestrator wired
    log.info("run.start", run_id=rid, mode=mode, tables=tables, limit=limit, dry_run=False, resume=False)
    from etl_worker.runner import RunOutcome, RunnerConfig, run_orchestrator

    config: Config = ctx.obj["config"]
    manifest = _load_manifest(ctx.obj["config_dir"], tables)
    runner_cfg = RunnerConfig(
        pg_dsn=config.pg_dsn,
        mssql_dsn=config.mssql_dsn,
        run_id=rid,
        mode=mode,
        manifest=manifest,
        resume=False,
        max_reject_ratio=config.max_reject_ratio,
        limit=limit,
        worker_version=config.worker_version,
        git_sha=config.git_sha,
        contract_version=config.contract_version,
        annex_version=config.annex_version,
    )
    outcome = run_orchestrator(runner_cfg)
    _exit_for_outcome(outcome, rid)


@main.command("status")
@click.option("--run-id", required=True, type=str)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON")
@click.pass_context
def status(ctx: click.Context, run_id: str, as_json: bool) -> None:
    """Show audit state for a run (counts per status bucket + reject total)."""
    try:
        import psycopg

        from etl_worker.audit import AuditModule

        config: Config = ctx.obj["config"]
        with psycopg.connect(config.pg_dsn, autocommit=True) as conn:
            audit = AuditModule(conn)
            summary = audit.status_summary(run_id)
    except Exception as e:
        click.echo(f"FAIL: status query error: {e}", err=True)
        sys.exit(2)

    if summary["run"] is None:
        click.echo(f"FAIL: run_id={run_id} not found in migration_runs", err=True)
        sys.exit(2)

    # Codex iter-8: normalize buckets so all 5 statuses are present (zero-fill)
    # in both human and JSON output. Hidden zeros = SRE triage ambiguity.
    _ZERO_BUCKET = {"tables": 0, "rows_extracted": 0, "rows_loaded": 0, "rows_rejected": 0}
    raw_buckets = summary.get("buckets", {}) or {}
    buckets = {
        st: dict(raw_buckets.get(st, _ZERO_BUCKET))
        for st in ("PENDING", "EXTRACTING", "LOADING", "VALIDATED", "FAILED")
    }
    summary["buckets"] = buckets

    if as_json:
        click.echo(json.dumps(summary, default=str, indent=2))
        return

    run = summary["run"]
    click.echo(f"run_id        : {run['run_id']}")
    click.echo(f"mode          : {run['mode']}")
    click.echo(f"status        : {run['status']}")
    click.echo(f"source_db     : {run['source_database']}")
    click.echo(f"started_at    : {run['started_at']}")
    click.echo(f"completed_at  : {run['completed_at']}")
    if run.get("error_summary"):
        click.echo(f"error_summary : {run['error_summary']}")

    click.echo("")
    click.echo("table_state buckets:")
    for st in ("PENDING", "EXTRACTING", "LOADING", "VALIDATED", "FAILED"):
        b = buckets[st]
        click.echo(
            f"  {st:<12} tables={b['tables']:<5} "
            f"extracted={b['rows_extracted']} loaded={b['rows_loaded']} "
            f"rejected={b['rows_rejected']}"
        )

    click.echo("")
    click.echo(f"reject_total  : {summary.get('reject_total', 0)}")


@main.command("reconcile")
@click.option("--run-id", required=True, type=str)
@click.option(
    "--scope",
    type=click.Choice(["full", "limited", "delta"]),
    default="limited",
    help="Reconcile scope kind (Day 7 dry-run default: limited).",
)
@click.option("--limit", type=int, default=1000, help="Limited scope row cap per table.")
@click.option(
    "--output-dir",
    type=click.Path(),
    default="docs/migration",
    help="Output dir for reconcile-YYYYMMDD-<run_id_short>.{md,json}.",
)
@click.option("--tables", help="CSV (default: manifest all)")
@click.pass_context
def reconcile(
    ctx: click.Context,
    run_id: str,
    scope: str,
    limit: int,
    output_dir: str,
    tables: str | None,
) -> None:
    """16.3.5 reconciliation gate (row count + checksum + sample diff)."""
    import datetime
    import os

    import psycopg

    from etl_worker.reconcile import (
        ReconcileReport,
        ReconcileScope,
        reconcile_table,
        render_json,
        render_markdown,
    )

    log.info("reconcile.start", run_id=run_id, scope=scope, limit=limit)
    config: Config = ctx.obj["config"]
    manifest = _load_manifest(ctx.obj["config_dir"], tables)
    scope_obj = ReconcileScope(kind=scope, limit=limit if scope == "limited" else None)

    report = ReconcileReport(run_id=run_id, mode="reconcile", tables=[])

    pg_conn = psycopg.connect(config.pg_dsn)
    mssql_conn = None
    try:
        try:
            import pyodbc
            mssql_conn = pyodbc.connect(config.mssql_dsn, timeout=30)
        except Exception as e:
            click.echo(f"FAIL: MSSQL connection error: {e}", err=True)
            sys.exit(2)

        for table_meta in manifest:
            res = reconcile_table(pg_conn, mssql_conn, table_meta, scope_obj)
            report.tables.append(res)
            click.echo(
                f"  {table_meta.source_schema}.{table_meta.name} "
                f"(year={table_meta.source_year}) → {res.verdict} "
                f"pg={res.row_count_pg} mssql={res.row_count_mssql}"
            )
    finally:
        try:
            pg_conn.close()
        except Exception:
            pass
        if mssql_conn is not None:
            try:
                mssql_conn.close()
            except Exception:
                pass

    # Write artifacts
    today = datetime.date.today().strftime("%Y%m%d")
    short = run_id.split("-")[0] if "-" in run_id else run_id[:8]
    os.makedirs(output_dir, exist_ok=True)
    base = f"reconcile-{today}-{short}"
    md_path = os.path.join(output_dir, f"{base}.md")
    json_path = os.path.join(output_dir, f"{base}.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(render_json(report))
    click.echo("")
    click.echo(f"overall verdict: {report.overall_verdict()}")
    click.echo(f"markdown: {md_path}")
    click.echo(f"json:     {json_path}")


# ============================================================================
# Helpers
# ============================================================================

def _load_manifest(config_dir: Path, tables_csv: str | None) -> list[Any]:
    """Load + validate tables.yaml manifest.

    Codex iter-5 fail-fast (Day 7): empty `columns` is not silently accepted —
    extractor and reconcile both rely on column metadata, so a missing list
    means the run is unrunnable. Better to refuse at startup than to ship
    `SELECT  FROM ...` to MSSQL or load no business columns into PG.
    """
    import yaml

    from etl_worker.transform import ColumnMeta, TableMeta

    manifest_path = config_dir / "tables.yaml"
    raw = yaml.safe_load(manifest_path.read_text())
    table_filter = (
        {t.strip().upper() for t in tables_csv.split(",")} if tables_csv else None
    )
    out: list[TableMeta] = []
    missing_columns: list[str] = []
    for entry in raw.get("tables", []):
        if table_filter is not None and entry["name"].upper() not in table_filter:
            continue
        col_specs = entry.get("columns") or []
        if not col_specs:
            missing_columns.append(entry["name"])
            continue
        cols = [
            ColumnMeta(
                name=c["name"],
                pg_type=c["pg_type"],
                nullable=c.get("nullable", True),
                max_length=c.get("max_length"),
            )
            for c in col_specs
        ]
        # idempotency_key columns must be present in the column list.
        col_names = {c.name for c in cols}
        idempotency_key = entry["idempotency_key"]
        missing_pk = [k for k in idempotency_key if k not in col_names]
        if missing_pk:
            raise click.ClickException(
                f"manifest table {entry['name']!r}: idempotency_key {missing_pk} "
                f"missing from columns. fix config/tables.yaml."
            )
        out.append(
            TableMeta(
                name=entry["name"],
                source_schema=entry.get("source_schema", "workcube_mikrolink"),
                source_year=entry.get("source_year"),
                columns=cols,
                idempotency_key=idempotency_key,
            )
        )
    if missing_columns:
        raise click.ClickException(
            f"manifest tables missing `columns`: {missing_columns}. "
            "Day 7 cannot run without column metadata — populate config/tables.yaml "
            "(future: auto-resolve from V16 generator output)."
        )
    if not out:
        raise click.ClickException(
            "manifest produced 0 valid tables (filter mismatch or all entries "
            "missing columns)."
        )
    return out


def _exit_for_outcome(outcome: Any, run_id: str) -> None:
    """Map RunOutcome → CLI exit code."""
    from etl_worker.runner import RunOutcome

    if outcome is RunOutcome.SUCCESS:
        click.echo(f"✓ run {run_id} SUCCESS")
        sys.exit(0)
    if outcome is RunOutcome.LOCK_CONTENDED:
        click.echo(f"FAIL: another worker holds run lease for {run_id}", err=True)
        sys.exit(3)
    if outcome is RunOutcome.RUN_EXISTS:
        click.echo(f"FAIL: run_id={run_id} already exists in migration_runs", err=True)
        sys.exit(1)
    if outcome is RunOutcome.ABORTED:
        click.echo(f"FAIL: run {run_id} ABORTED (see migration_runs.error_summary)", err=True)
        sys.exit(2)
    click.echo(f"FAIL: run {run_id} FAILED (see logs)", err=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
