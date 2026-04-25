#!/usr/bin/env python3
"""Faz 16.2 — V16 Flyway DDL generator.

Codex iter-3 AGREE: 40 tablo full DDL deterministic generation.

Inputs:
- docs/migration/workcube-schema.json (schema-service snapshot, 1509 tablo + 26240 kolon)
- docs/migration/report-source-annex.yaml (31 rapor + 40 unique tablo allowlist)
- docs/migration/mssql-pg-data-contract.md (type mapping rules)

Output:
- sql/migration/V16__reports.sql (full DDL — final + raw + audit + partitions + indexes)
- docs/migration/v16-ddl-review.md (manual review checklist + edge cases)

Usage:
  python3 scripts/migration/generate_v16_sql.py \\
    --snapshot docs/migration/workcube-schema.json \\
    --annex docs/migration/report-source-annex.yaml \\
    --contract docs/migration/mssql-pg-data-contract.md \\
    --out sql/migration/V16__reports.sql \\
    --review-out docs/migration/v16-ddl-review.md

Status: SKELETON (Faz 16.2 Gün 2 deliverable). Tam impl Gün 3 sprint sonunda.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any
import yaml


# ============================================================================
# Type mapping (Codex iter-1 AGREE)
# ============================================================================

MSSQL_TO_PG_TYPE = {
    # String
    "nvarchar": "VARCHAR",
    "varchar": "VARCHAR",
    "nchar": "CHAR",
    "char": "CHAR",
    "ntext": "TEXT",
    "text": "TEXT",
    # Numeric
    "int": "INTEGER",
    "bigint": "BIGINT",
    "smallint": "SMALLINT",
    "tinyint": "SMALLINT",  # PG'de TINYINT yok
    "decimal": "NUMERIC",
    "numeric": "NUMERIC",
    "money": "NUMERIC(19,4)",
    "smallmoney": "NUMERIC(10,4)",
    "float": "DOUBLE PRECISION",
    "real": "REAL",
    # Date/time
    "datetime": "TIMESTAMPTZ",
    "datetime2": "TIMESTAMPTZ",
    "smalldatetime": "TIMESTAMPTZ",
    "date": "DATE",
    "time": "TIME",
    "datetimeoffset": "TIMESTAMPTZ",
    # Boolean / GUID
    "bit": "BOOLEAN",
    "uniqueidentifier": "UUID",
    # Binary
    "binary": "BYTEA",
    "varbinary": "BYTEA",
    "image": "BYTEA",
    # JSON
    "xml": "TEXT",  # PG'de native XML var ama TEXT yeterli
    # Edge
    "sql_variant": "TEXT",  # fallback
    "hierarchyid": "TEXT",  # fallback
    "geography": "TEXT",  # fallback (PostGIS gerek)
    "geometry": "TEXT",  # fallback
    "rowversion": "BYTEA",
    "timestamp": "BYTEA",  # MSSQL timestamp ≠ PG TIMESTAMP
}

# Partition seti (Codex iter-3 AGREE)
PARTITION_YEARS = [2024, 2025, 2026, 2027, 2028]


# ============================================================================
# Schema parser
# ============================================================================

def load_inputs(snapshot_path: Path, annex_path: Path) -> tuple[dict, dict]:
    """Snapshot + annex yükle."""
    with open(snapshot_path) as f:
        snapshot = json.load(f)
    with open(annex_path) as f:
        annex = yaml.safe_load(f)
    return snapshot, annex


def get_etl_scope(annex: dict) -> tuple[set[str], dict[str, dict]]:
    """40 tablo allowlist + per-table metadata (parametric flag, reports)."""
    table_meta: dict[str, dict] = {}
    for r in annex["reports"]:
        rname = r["report"]
        for t in r.get("tables", []):
            tname = t["name"]
            if tname not in table_meta:
                table_meta[tname] = {
                    "name": tname,
                    "is_parametric": False,
                    "reports": [],
                    "schemas": set(),
                    "category": r.get("category", "?"),
                }
            table_meta[tname]["reports"].append(rname)
            if t.get("parametric_schema"):
                table_meta[tname]["is_parametric"] = True
                table_meta[tname]["schemas"].update(r.get("parametric_schemas", []))
    return set(table_meta.keys()), table_meta


def map_mssql_type(mssql_type: str, length: int | None = None, precision: int | None = None, scale: int | None = None) -> str:
    """MSSQL type → PG type."""
    base = mssql_type.lower().split("(")[0].strip()
    pg_type = MSSQL_TO_PG_TYPE.get(base, "TEXT")  # fallback TEXT

    if base in {"varchar", "nvarchar", "char", "nchar"}:
        if length and length > 0 and length < 10485760:  # MAX
            return f"{pg_type}({length})"
        return "TEXT"
    if base in {"decimal", "numeric"} and precision:
        if scale is not None:
            return f"{pg_type}({precision},{scale})"
        return f"{pg_type}({precision})"
    return pg_type


# ============================================================================
# DDL generation
# ============================================================================

def generate_audit_ddl() -> str:
    """Section 02 — migration_audit schema (sabit)."""
    return """-- 02 MIGRATION AUDIT
CREATE TABLE migration_audit.migration_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    mode VARCHAR(20) NOT NULL CHECK (mode IN ('initial','final_delta','reconcile_only','dry_run')),
    status VARCHAR(20) NOT NULL CHECK (status IN ('RUNNING','SUCCESS','FAILED','ABORTED')),
    source_database VARCHAR(128) NOT NULL,
    worker_version VARCHAR(40),
    git_sha VARCHAR(40),
    contract_version VARCHAR(40),
    annex_version VARCHAR(40),
    started_by VARCHAR(128),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    error_summary TEXT,
    notes JSONB NOT NULL DEFAULT '{}'::jsonb
);
-- ... (full audit DDL) ...
"""


def generate_table_ddl(table_meta: dict, snapshot_table: dict | None) -> tuple[str, str]:
    """Per-table: raw staging + final canonical + partitions + indexes."""
    tname_lower = table_meta["name"].lower()
    is_parametric = table_meta["is_parametric"]

    # TODO: snapshot_table'dan kolon listesi extract + type mapping
    # Şu an SKELETON — sadece tablo adı + parametric pattern

    raw_ddl = f"""-- raw staging
CREATE TABLE workcube_mssql_raw.{tname_lower} (
    run_id UUID NOT NULL,
    source_schema VARCHAR(128) NOT NULL,
    source_year SMALLINT,
    source_pk TEXT,
    raw_payload JSONB NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_raw_{tname_lower}_run ON workcube_mssql_raw.{tname_lower} (run_id);
"""

    if is_parametric:
        partition_ddl = "\n".join(
            f"CREATE TABLE workcube_mikrolink.{tname_lower}_{y} PARTITION OF workcube_mikrolink.{tname_lower} FOR VALUES IN ({y});"
            for y in PARTITION_YEARS
        )
        partition_ddl += f"\nCREATE TABLE workcube_mikrolink.{tname_lower}_default PARTITION OF workcube_mikrolink.{tname_lower} DEFAULT;"

        final_ddl = f"""-- {table_meta["name"]} (parametric, used by: {", ".join(table_meta["reports"][:3])})
CREATE TABLE workcube_mikrolink.{tname_lower} (
    source_year SMALLINT NOT NULL,
    source_schema VARCHAR(128) NOT NULL,
    -- TODO: snapshot kolonları — generator full impl
    content_hash VARCHAR(64) NOT NULL,
    migrated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_year /* + natural PK */)
) PARTITION BY LIST (source_year);

{partition_ddl}
"""
    else:
        final_ddl = f"""-- {table_meta["name"]} (canonical, used by: {", ".join(table_meta["reports"][:3])})
CREATE TABLE workcube_mikrolink.{tname_lower} (
    source_schema VARCHAR(128) NOT NULL DEFAULT 'workcube_mikrolink',
    -- TODO: snapshot kolonları — generator full impl
    content_hash VARCHAR(64) NOT NULL,
    migrated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (/* natural PK */)
);
"""

    return raw_ddl, final_ddl


def generate_review_md(table_meta_map: dict, unmatched: list) -> str:
    """Manual review checklist."""
    lines = [
        "# V16 DDL Review Checklist (Faz 16.2 Gün 2)\n\n",
        "> Generator: `scripts/migration/generate_v16_sql.py`\n",
        f"> Total tables: {len(table_meta_map)}\n",
        f"> Unmatched (parametric or unknown): {len(unmatched)}\n\n",
        "## Manual review per-table\n\n",
        "| Table | Parametric | PK | Edge cases |\n",
        "|---|---|---|---|\n",
    ]
    for tname, meta in sorted(table_meta_map.items()):
        param = "YES" if meta["is_parametric"] else "no"
        lines.append(f"| `{tname}` | {param} | TODO | TODO |\n")
    lines.append("\n## Unmatched (manuel resolution gerek)\n\n")
    for t in unmatched:
        lines.append(f"- `{t}` — schema-service snapshot'ta yok (parametric or unknown)\n")
    return "".join(lines)


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--annex", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--review-out", required=True, type=Path)
    args = parser.parse_args()

    snapshot, annex = load_inputs(args.snapshot, args.annex)
    etl_scope, table_meta_map = get_etl_scope(annex)

    snapshot_tables = snapshot.get("tables", {})
    matched = [t for t in etl_scope if t in snapshot_tables]
    unmatched = [t for t in etl_scope if t not in snapshot_tables]

    print(f"ETL scope: {len(etl_scope)} table", file=sys.stderr)
    print(f"Matched (snapshot canonical): {len(matched)}", file=sys.stderr)
    print(f"Unmatched (parametric): {len(unmatched)}", file=sys.stderr)

    # Generate DDL
    sections: list[str] = ["BEGIN;\n"]
    sections.append("-- Generated by scripts/migration/generate_v16_sql.py\n")
    sections.append(f"-- Tables: {len(etl_scope)} ({len(matched)} canonical + {len(unmatched)} parametric)\n\n")
    sections.append("CREATE EXTENSION IF NOT EXISTS citext;\n")
    sections.append("CREATE EXTENSION IF NOT EXISTS pgcrypto;\n\n")
    sections.append("CREATE SCHEMA IF NOT EXISTS workcube_mikrolink;\n")
    sections.append("CREATE SCHEMA IF NOT EXISTS workcube_mssql_raw;\n")
    sections.append("CREATE SCHEMA IF NOT EXISTS migration_audit;\n\n")
    sections.append(generate_audit_ddl())
    sections.append("\n-- =====================\n-- 03+04+05 PER-TABLE DDL\n-- =====================\n\n")

    for tname in sorted(etl_scope):
        meta = table_meta_map[tname]
        snap = snapshot_tables.get(tname)
        raw_ddl, final_ddl = generate_table_ddl(meta, snap)
        sections.append(f"-- ===== {tname} =====\n")
        sections.append(raw_ddl)
        sections.append("\n")
        sections.append(final_ddl)
        sections.append("\n")

    sections.append("\nCOMMIT;\n")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(sections))
    print(f"Wrote: {args.out}", file=sys.stderr)

    # Review markdown
    review_md = generate_review_md(table_meta_map, unmatched)
    args.review_out.parent.mkdir(parents=True, exist_ok=True)
    args.review_out.write_text(review_md)
    print(f"Wrote: {args.review_out}", file=sys.stderr)

    print("DONE", file=sys.stderr)


if __name__ == "__main__":
    main()
