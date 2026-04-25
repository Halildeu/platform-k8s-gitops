"""Faz 16.3 — ETL Worker CLI (Codex iter-5 AGREE).

Usage:
    etl-worker validate-manifest
    etl-worker inspect-source --tables COMPANY
    etl-worker run --mode initial --run-id <uuid> --tables COMPANY,COMPANY_PARTNER --dry-run
    etl-worker run --mode final-delta --run-id <uuid>
    etl-worker reconcile --run-id <uuid> --output docs/migration/reconcile-YYYYMMDD.md
"""

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
@click.option("--mode", type=click.Choice(["initial", "final-delta", "reconcile-only"]), required=True)
@click.option("--run-id", default=None, help="UUID (auto-generated if omitted)")
@click.option("--tables", help="CSV (default: manifest all)")
@click.option("--limit", type=int, default=None, help="Per-table row limit (dry-run helper)")
@click.option("--dry-run", is_flag=True, help="Read-only, no write to PG")
@click.pass_context
def run(ctx: click.Context, mode: str, run_id: str | None, tables: str | None, limit: int | None, dry_run: bool) -> None:
    """ETL run — MSSQL extract → PG raw staging → transform → final."""
    rid = run_id or str(uuid.uuid4())
    log.info("run.start", run_id=rid, mode=mode, tables=tables, limit=limit, dry_run=dry_run)

    if dry_run:
        click.echo(f"DRY RUN — would extract {tables or 'all'} (limit={limit})")
        click.echo("Gün 4 PoC: MSSQL extract + PG raw staging COPY only.")
        click.echo("Gün 5+: transform + final load + idempotent upsert.")
        return

    click.echo("FULL RUN — Gün 5+ implementation gerek (TODO)")
    sys.exit(2)


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
