#!/usr/bin/env python3
"""
Faz 16.1 deliverable — Annex 2A: report-runtime-source-surface crawler.

Inputs:
  platform-ssot/backend/report-service/src/main/resources/reports/*.json

Outputs:
  docs/migration/report-source-annex.yaml (Annex 2A DRAFT → manually validate sourceQuery reports → SEAL)

Reference: docs/migration/mssql-pg-data-contract.md §3 "Annex 2A extraction hierarchy"

Usage:
  extract-report-source-annex.py \\
      --reports-dir /Users/halilkocoglu/Documents/dev/backend/report-service/src/main/resources/reports \\
      --output docs/migration/report-source-annex.yaml

Notes:
- Direct `source` + `sourceSchema` field → single-table entry
- `sourceQuery` field → regex AST-assisted extraction (FROM, JOIN, subquery, cross-schema)
- `sourceQuery` reports MUST be manually validated before annex SEAL (Codex iter-4 AGREE cümlesi)
- `{schema}` template placeholder → `parametric_schemas: [{schema}]` marker
- Cross-schema literal refs (e.g. `[workcube_mikrolink].[COMPANY]`) → explicit extraction
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml

# T-SQL-aware regex patterns (not a full parser — best-effort extraction).
# sourceQuery MUST be manually validated per-report before annex SEAL.

# Table reference forms observed in platform-ssot report JSONs:
#   [workcube_mikrolink].[COMPANY]         → literal schema + table
#   [{schema}].[INVOICE_ROW]               → parametric schema
#   [{schema}].[INVOICE] I                 → with alias (ignore alias here)
#   workcube_mikrolink.COMPANY             → unbracketed (rare)
#
# We capture FROM and all JOIN types (INNER/LEFT/RIGHT/CROSS/OUTER).
_TABLE_REF_PATTERN = re.compile(
    r"""
    (?:FROM|JOIN)                 # clause
    \s+
    \[?                           # optional [
    (?P<schema>\{schema\}|\w+)    # schema: either `{schema}` template or literal
    \]?
    \.
    \[?
    (?P<table>\w+)                # table name
    \]?
    (?:\s+(?:AS\s+)?(?P<alias>\w+))?  # optional alias (not needed for extraction but consumed to avoid mis-match)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_JOIN_TYPE_PATTERN = re.compile(
    r"(?P<jtype>LEFT|RIGHT|INNER|CROSS|FULL)\s+(?:OUTER\s+)?JOIN",
    re.IGNORECASE,
)

_NOLOCK_PATTERN = re.compile(r"WITH\s*\(\s*NOLOCK\s*\)", re.IGNORECASE)
_CTE_PATTERN = re.compile(r"\bWITH\s+\w+\s+AS\s*\(", re.IGNORECASE)


@dataclass
class TableRef:
    schema: str
    name: str
    join_type: str | None = None
    is_parametric_schema: bool = False

    def to_dict(self) -> dict:
        d: dict = {"schema": self.schema, "name": self.name}
        if self.join_type and self.join_type.upper() != "FROM":
            d["join_type"] = self.join_type.upper()
        if self.is_parametric_schema:
            d["parametric_schema"] = True
        return d


@dataclass
class ReportAnnex:
    report: str
    category: str
    title: str
    extraction_method: str  # "direct_source" | "sourceQuery"
    manually_validated: bool  # false by default for sourceQuery; true if overridden
    tables: List[TableRef] = field(default_factory=list)
    parametric_schemas: List[str] = field(default_factory=list)
    schema_mode: str = "unknown"
    schema_name: str = ""
    contains_nolock_hint: bool = False
    contains_cte: bool = False
    migration_action_default: str = "pending_annex"

    def to_dict(self) -> dict:
        d: dict = {
            "report": self.report,
            "category": self.category,
            "title": self.title,
            "extraction_method": self.extraction_method,
            "manually_validated": self.manually_validated,
            "schema_mode": self.schema_mode,
            "schema_name": self.schema_name,
            "tables": [t.to_dict() for t in self.tables],
            "migration_action_default": self.migration_action_default,
        }
        if self.parametric_schemas:
            d["parametric_schemas"] = self.parametric_schemas
        if self.contains_nolock_hint:
            d["contains_nolock_hint"] = True
        if self.contains_cte:
            d["contains_cte"] = True
        return d


def _detect_join_types(sql: str) -> List[str]:
    return [m.group("jtype").upper() for m in _JOIN_TYPE_PATTERN.finditer(sql)]


def _extract_source_query_tables(sql: str) -> List[TableRef]:
    """
    Best-effort regex extraction from sourceQuery.
    Real T-SQL parser (e.g. sqlfluff, sqlglot) recommended for SEAL-grade automation.
    MVP (this script): regex + manual validation required per Codex iter-4 rule.
    """
    tables: List[TableRef] = []
    seen: set[tuple[str, str]] = set()

    # Identify FROM vs JOIN at each match by inspecting preceding clause.
    # Strategy: find all FROM/JOIN occurrences with positions, classify by type.
    for m in _TABLE_REF_PATTERN.finditer(sql):
        schema = m.group("schema")
        table = m.group("table")
        # De-dup on (schema, table)
        key = (schema, table)
        if key in seen:
            continue
        seen.add(key)

        # Look at the clause keyword preceding the match to infer FROM vs JOIN and type
        start = m.start()
        preceding = sql[:start].rstrip().split()[-3:]  # last 3 tokens approximation
        preceding_text = " ".join(preceding).upper()
        jtype: str | None = None
        if "FROM" in preceding_text.split()[-1:]:
            jtype = "FROM"
        elif "JOIN" in preceding_text:
            for jt_kw in ("LEFT", "RIGHT", "INNER", "CROSS", "FULL"):
                if jt_kw in preceding_text:
                    jtype = jt_kw
                    break
            else:
                jtype = "JOIN"  # generic join without qualifier
        is_parametric = schema == "{schema}"
        tables.append(
            TableRef(
                schema=schema,
                name=table,
                join_type=jtype,
                is_parametric_schema=is_parametric,
            )
        )

    return tables


def parse_report(json_path: Path) -> ReportAnnex:
    data = json.loads(json_path.read_text(encoding="utf-8"))

    report_key = data.get("key", json_path.stem)
    category = data.get("category", "uncategorized")
    title = data.get("title", "")
    schema_mode = data.get("schemaMode", "unknown")
    schema_name = data.get("sourceSchema", "")

    source_query = data.get("sourceQuery")
    if source_query:
        tables = _extract_source_query_tables(source_query)
        parametric_schemas = ["{schema}"] if any(t.is_parametric_schema for t in tables) else []
        return ReportAnnex(
            report=report_key,
            category=category,
            title=title,
            extraction_method="sourceQuery",
            manually_validated=False,  # MUST be manually validated before SEAL (Codex iter-4)
            tables=tables,
            parametric_schemas=parametric_schemas,
            schema_mode=schema_mode,
            schema_name=schema_name,
            contains_nolock_hint=bool(_NOLOCK_PATTERN.search(source_query)),
            contains_cte=bool(_CTE_PATTERN.search(source_query)),
            migration_action_default="pending_annex",
        )

    # Direct source path
    source_table = data.get("source", "")
    if not source_table:
        return ReportAnnex(
            report=report_key,
            category=category,
            title=title,
            extraction_method="none",
            manually_validated=False,
            tables=[],
            schema_mode=schema_mode,
            schema_name=schema_name,
        )

    is_parametric = schema_name and ("{schema}" in schema_name or schema_mode in {"yearly", "standard"})
    # Normalize parametric: yearly/standard modes use schema_name as template; treat as literal here
    # but annotate that actual runtime schema is parametric.
    tables = [
        TableRef(
            schema=schema_name or "UNKNOWN_AT_PARSE",
            name=source_table,
            join_type=None,
            is_parametric_schema=is_parametric,
        )
    ]
    return ReportAnnex(
        report=report_key,
        category=category,
        title=title,
        extraction_method="direct_source",
        manually_validated=True,  # direct source is trivially extractable; no manual review gate
        tables=tables,
        parametric_schemas=[schema_name] if is_parametric and schema_name else [],
        schema_mode=schema_mode,
        schema_name=schema_name,
        migration_action_default="pending_annex",
    )


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--reports-dir",
        required=True,
        type=Path,
        help="platform-ssot/backend/report-service/src/main/resources/reports path",
    )
    p.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output YAML annex path (e.g. docs/migration/report-source-annex.yaml)",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-report summary to stderr",
    )
    args = p.parse_args(argv)

    if not args.reports_dir.is_dir():
        print(f"ERROR: reports-dir not found: {args.reports_dir}", file=sys.stderr)
        return 2

    report_files = sorted(args.reports_dir.glob("*.json"))
    if not report_files:
        print(f"ERROR: no *.json reports found in {args.reports_dir}", file=sys.stderr)
        return 2

    annex_entries: List[dict] = []
    stats = {"total": 0, "direct": 0, "source_query": 0, "none": 0, "nolock": 0, "cte": 0}
    pending_manual_validation: List[str] = []

    for rf in report_files:
        try:
            entry = parse_report(rf)
        except json.JSONDecodeError as e:
            print(f"ERROR: {rf.name} JSON decode: {e}", file=sys.stderr)
            return 3

        stats["total"] += 1
        if entry.extraction_method == "direct_source":
            stats["direct"] += 1
        elif entry.extraction_method == "sourceQuery":
            stats["source_query"] += 1
            pending_manual_validation.append(entry.report)
        else:
            stats["none"] += 1
        if entry.contains_nolock_hint:
            stats["nolock"] += 1
        if entry.contains_cte:
            stats["cte"] += 1

        if args.verbose:
            tbls = ", ".join(f"{t.schema}.{t.name}" for t in entry.tables) or "(none)"
            print(f"[{entry.extraction_method}] {entry.report}: {tbls}", file=sys.stderr)

        annex_entries.append(entry.to_dict())

    # Unique table set (schema, name) across all reports — used for SEAL checklist.
    unique_tables: set[tuple[str, str]] = set()
    for e in annex_entries:
        for t in e.get("tables", []):
            unique_tables.add((t["schema"], t["name"]))

    output_doc = {
        "_meta": {
            "annex": "2A_report_runtime_source_surface",
            "status": "DRAFT",
            "seal_state": "DRAFT",
            "generated_by": "scripts/migration/extract-report-source-annex.py",
            "total_reports": stats["total"],
            "direct_source_reports": stats["direct"],
            "source_query_reports": stats["source_query"],
            "reports_with_nolock_hint": stats["nolock"],
            "reports_with_cte": stats["cte"],
            "pending_manual_validation": pending_manual_validation,
            "unique_table_count": len(unique_tables),
            "seal_gate": [
                "All sourceQuery reports manually validated (manually_validated: true)",
                "Zero tables with schema='UNKNOWN_AT_PARSE'",
                "Zero tables with migration_action_default='pending_annex'",
                "Workcube admin resolved all parametric_schemas",
            ],
            "references": [
                "docs/migration/mssql-pg-data-contract.md §3 Annex 2A extraction hierarchy",
                "Codex thread 019dbe92 iter-4 AGREE",
            ],
        },
        "reports": annex_entries,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        yaml.safe_dump(output_doc, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )

    print(
        f"Annex 2A DRAFT → {args.output}\n"
        f"  reports: {stats['total']} (direct={stats['direct']}, sourceQuery={stats['source_query']}, none={stats['none']})\n"
        f"  unique tables: {len(unique_tables)}\n"
        f"  pending manual validation: {len(pending_manual_validation)} reports",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
