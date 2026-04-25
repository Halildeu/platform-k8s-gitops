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
@click.option("--limit", type=int, default=None, help="Per-table row limit (dry-run helper)")
@click.option("--dry-run", is_flag=True, help="Read-only, no write to PG")
@click.option("--resume", is_flag=True, help="Resume an existing run; requires --run-id")
@click.pass_context
def run(
    ctx: click.Context,
    mode: str | None,
    run_id: str | None,
    tables: str | None,
    limit: int | None,
    dry_run: bool,
    resume: bool,
) -> None:
    """ETL run — MSSQL extract → PG raw staging → transform → final."""
    if resume and not run_id:
        click.echo("FAIL: --resume requires --run-id", err=True)
        sys.exit(2)
    if not resume and mode is None:
        click.echo("FAIL: --mode is required for new runs (use --resume to continue an existing run)", err=True)
        sys.exit(2)

    rid = run_id or str(uuid.uuid4())

    if dry_run:
        log.info("run.start", run_id=rid, mode=mode, tables=tables, limit=limit, dry_run=True, resume=False)
        click.echo(f"DRY RUN — would extract {tables or 'all'} (limit={limit})")
        click.echo("Gün 4 PoC: MSSQL extract + PG raw staging COPY only.")
        click.echo("Gün 5+: transform + final load + idempotent upsert.")
        return

    if resume:
        # Read-only resume preview — actual orchestrator wires audit module.
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
        click.echo("Orchestrator wiring is implemented in Day 7 dry-run.")
        return

    log.info("run.start", run_id=rid, mode=mode, tables=tables, limit=limit, dry_run=False, resume=False)
    click.echo("FULL RUN — Gün 7 orchestrator gerek (TODO)")
    sys.exit(2)


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
@click.option("--output", type=click.Path(), default=None, help="Markdown output path")
@click.pass_context
def reconcile(ctx: click.Context, run_id: str, output: str | None) -> None:
    """16.3.5 reconciliation gate (row count + checksum + sample diff)."""
    log.info("reconcile.start", run_id=run_id)
    click.echo(f"TODO Gün 7: reconcile run-id={run_id}")
    click.echo("Output: row_count parity + checksum + sample diff (markdown + JSON)")


if __name__ == "__main__":
    main()
