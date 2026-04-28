#!/usr/bin/env python3
"""
ADR-0011 DD-1 — Plan-time Drift Detection (anchor table + V25/V26 contract guards).

Codex thread `019dd409` PARTIAL/AGREE-with-revisions spec:
6 check fonksiyonu, V25/V26 contract drift'ini live-load test'e bırakmadan
plan-time + CI-time'da yakalar.

Checks:
1. V25 CHECK constraint scope_kind_source_table_consistent (4 pair contract)
2. V25+V26 validate_scope_ref() final-function company branch anchor
   (workcube_mikrolink.our_company, NOT .company)
3. V25 organization_company source_table default + CHECK = 'OUR_COMPANY'
4. V26 dual-format predicate (4 kind branch'inde OR predicate)
5. workcube-schema.json anchor tables + minimum kolonlar
6. ADR-0008 § Object id encoding tablosu V25 transition map

Exit codes:
  0 = all checks pass
  1 = drift detected (one or more checks failed)
  2 = invocation error (file missing, parse error)

Usage:
  python3 scripts/drift_detection/check_drift_anchor_table.py [options]

Options:
  --verbose               Detailed per-check log
  --json                  Structured JSON output (CI artifact friendly)
  --v25-path PATH         Override V25 SQL path (default: sql/migration/V25__tenant_anchor_fix.sql)
  --v26-path PATH         Override V26 SQL path (default: sql/migration/V26__source_pk_dual_format.sql)
  --schema-path PATH      Override workcube-schema.json path (default: docs/migration/workcube-schema.json)
  --adr-0008-path PATH    Override ADR-0008 markdown path (default: docs/adr/0008-multi-org-explicit-scope-zanzibar.md)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants — Codex 019dd34e hybrid contract (ADR-0008 § Object id encoding)
# ---------------------------------------------------------------------------

EXPECTED_CHECK_PAIRS = [
    ("company", "OUR_COMPANY"),
    ("project", "PRO_PROJECTS"),
    ("branch", "BRANCH"),
    ("depot", "DEPARTMENT"),
]

# Anchor tables + minimum required columns (Codex 019dd409 check 5 expansion)
EXPECTED_ANCHOR_TABLES = {
    "OUR_COMPANY": ["COMP_ID"],
    "COMPANY": ["COMPANY_ID", "OUR_COMPANY_ID"],
    "BRANCH": ["COMPANY_ID"],
    "DEPARTMENT": ["OUR_COMPANY_ID"],
    "PRO_PROJECTS": ["COMPANY_ID"],
}

# Default file paths (relative to repo root)
DEFAULT_V25_PATH = "sql/migration/V25__tenant_anchor_fix.sql"
DEFAULT_V26_PATH = "sql/migration/V26__source_pk_dual_format.sql"
DEFAULT_SCHEMA_PATH = "docs/migration/workcube-schema.json"
DEFAULT_ADR_0008_PATH = "docs/adr/0008-multi-org-explicit-scope-zanzibar.md"

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DriftReport:
    overall: str  # "PASS" | "FAIL"
    checks: list[CheckResult]

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "checks": [c.to_dict() for c in self.checks],
        }


# ---------------------------------------------------------------------------
# SQL parser helpers
# ---------------------------------------------------------------------------


def strip_sql_comments(sql: str) -> str:
    """Remove SQL line comments (-- ...) but preserve string literals."""
    out_lines: list[str] = []
    for line in sql.splitlines():
        # Find comment start outside quoted strings (basic heuristic — doesn't
        # handle deeply nested or escaped quotes; sufficient for our migration files).
        in_single = False
        idx = 0
        while idx < len(line):
            ch = line[idx]
            if ch == "'":
                in_single = not in_single
            if not in_single and ch == "-" and idx + 1 < len(line) and line[idx + 1] == "-":
                line = line[:idx]
                break
            idx += 1
        out_lines.append(line)
    return "\n".join(out_lines)


def extract_function_body(sql_clean: str, function_name: str = "validate_scope_ref") -> str | None:
    """Extract the latest CREATE OR REPLACE FUNCTION body for `function_name`.

    Returns the content between the first $$ and matching $$ (or None if not found).
    If multiple definitions exist, returns the LAST one (mimics PG behavior).
    """
    # Find all CREATE OR REPLACE FUNCTION ... $$ ... $$ blocks
    pattern = re.compile(
        rf"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+[^$]*?{re.escape(function_name)}[^$]*?\$\$(.*?)\$\$",
        re.DOTALL | re.IGNORECASE,
    )
    matches = pattern.findall(sql_clean)
    if not matches:
        return None
    return matches[-1]  # last definition wins (V26 supersedes V25)


def extract_branch_body(function_body: str, kind: str, source_table: str) -> str | None:
    """Extract the body of a single IF/ELSIF branch in validate_scope_ref().

    Looks for `IF/ELSIF p_kind = '<kind>' AND p_source_table = '<source>' THEN ... (ELSIF|ELSE|END IF)`.
    """
    pattern = re.compile(
        rf"(?:IF|ELSIF)\s+p_kind\s*=\s*'{re.escape(kind)}'\s+AND\s+p_source_table\s*=\s*'{re.escape(source_table)}'\s+THEN(.*?)(?=ELSIF\s+|ELSE\s|END\s+IF)",
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(function_body)
    if not match:
        return None
    return match.group(1)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_v25_check_constraint(v25_sql: str) -> CheckResult:
    """Check 1: V25 scope_kind_source_table_consistent CHECK constraint pairs."""
    name = "v25_check_constraint_pairs"
    sql_clean = strip_sql_comments(v25_sql)

    # Find ADD CONSTRAINT scope_kind_source_table_consistent CHECK (...)
    # Match the closing paren of the CHECK by counting balanced parens.
    constraint_start = re.search(
        r"ADD\s+CONSTRAINT\s+scope_kind_source_table_consistent\s+CHECK\s*\(",
        sql_clean,
        re.IGNORECASE,
    )
    if not constraint_start:
        return CheckResult(
            name=name,
            passed=False,
            message="V25 CHECK constraint scope_kind_source_table_consistent NOT FOUND",
        )

    # Walk balanced parens
    start_idx = constraint_start.end()
    depth = 1
    idx = start_idx
    while idx < len(sql_clean) and depth > 0:
        if sql_clean[idx] == "(":
            depth += 1
        elif sql_clean[idx] == ")":
            depth -= 1
        idx += 1
    constraint_body = sql_clean[start_idx : idx - 1]

    missing: list[str] = []
    for kind, source_table in EXPECTED_CHECK_PAIRS:
        # Match: (scope_kind = 'X' AND scope_source_table = 'Y')
        pair_re = re.compile(
            rf"scope_kind\s*=\s*'{re.escape(kind)}'\s+AND\s+scope_source_table\s*=\s*'{re.escape(source_table)}'",
            re.IGNORECASE,
        )
        if not pair_re.search(constraint_body):
            missing.append(f"({kind} → {source_table})")

    if missing:
        return CheckResult(
            name=name,
            passed=False,
            message="V25 CHECK constraint missing expected pair(s)",
            details=[f"missing: {', '.join(missing)}"],
        )
    return CheckResult(
        name=name,
        passed=True,
        message=f"V25 CHECK constraint has all 4 expected pairs: {', '.join(f'{k}→{t}' for k, t in EXPECTED_CHECK_PAIRS)}",
    )


def check_v25_v26_validate_scope_ref_anchor(v25_sql: str, v26_sql: str) -> CheckResult:
    """Check 2: V25 + V26 validate_scope_ref() company branch anchor (workcube_mikrolink.our_company).

    Codex 019dd409 expansion: V26 is final function (CREATE OR REPLACE wins);
    V25 doğru kalıp V26 regresse ederse de DD-1 yakalamalı.
    """
    name = "v25_v26_validate_scope_ref_anchor"
    issues: list[str] = []

    for label, sql in (("V25", v25_sql), ("V26", v26_sql)):
        sql_clean = strip_sql_comments(sql)
        body = extract_function_body(sql_clean)
        if body is None:
            issues.append(f"{label}: validate_scope_ref function body NOT FOUND")
            continue

        # Company branch must reference workcube_mikrolink.our_company
        company_branch = extract_branch_body(body, "company", "OUR_COMPANY")
        if company_branch is None:
            issues.append(f"{label}: company branch (p_kind='company' AND p_source_table='OUR_COMPANY') NOT FOUND")
            continue

        if not re.search(r"workcube_mikrolink\.our_company", company_branch, re.IGNORECASE):
            issues.append(
                f"{label}: company branch does NOT reference workcube_mikrolink.our_company"
            )

        # Negative: company branch should NOT directly anchor to .company table
        # (project/branch use .company as parent join — but those are different branches)
        # Match FROM workcube_mikrolink.company (without _id suffix in column name)
        if re.search(r"FROM\s+workcube_mikrolink\.company\b", company_branch, re.IGNORECASE):
            issues.append(
                f"{label}: company branch FROM workcube_mikrolink.company — V25 anchor regression!"
            )

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message="validate_scope_ref() anchor drift",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        message="V25 + V26 validate_scope_ref() company branch anchors workcube_mikrolink.our_company",
    )


def check_v25_organization_company_default(v25_sql: str) -> CheckResult:
    """Check 3: V25 organization_company source_table default + CHECK = 'OUR_COMPANY'."""
    name = "v25_organization_company_default"
    sql_clean = strip_sql_comments(v25_sql)
    issues: list[str] = []

    # Default
    default_re = re.compile(
        r"ALTER\s+COLUMN\s+source_table\s+SET\s+DEFAULT\s+'OUR_COMPANY'",
        re.IGNORECASE,
    )
    if not default_re.search(sql_clean):
        issues.append("ALTER COLUMN source_table SET DEFAULT 'OUR_COMPANY' NOT FOUND")

    # CHECK
    check_re = re.compile(
        r"ADD\s+CONSTRAINT\s+organization_company_source_table_check\s+CHECK\s*\(\s*source_table\s*=\s*'OUR_COMPANY'\s*\)",
        re.IGNORECASE,
    )
    if not check_re.search(sql_clean):
        issues.append("ADD CONSTRAINT organization_company_source_table_check ... CHECK (source_table = 'OUR_COMPANY') NOT FOUND")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message="V25 organization_company default/CHECK drift",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        message="V25 organization_company source_table default + CHECK = 'OUR_COMPANY'",
    )


def check_v26_dual_format_predicate(v26_sql: str) -> CheckResult:
    """Check 4: V26 validate_scope_ref final function dual-format OR predicate (4 branches)."""
    name = "v26_dual_format_predicate"
    sql_clean = strip_sql_comments(v26_sql)
    body = extract_function_body(sql_clean)
    if body is None:
        return CheckResult(
            name=name,
            passed=False,
            message="V26 validate_scope_ref function body NOT FOUND",
        )

    # Each kind/table branch must contain "X.source_pk = v_pk OR X.source_pk = p_ref"
    branch_specs = [
        ("company", "OUR_COMPANY", "oc"),
        ("project", "PRO_PROJECTS", "p"),
        ("branch", "BRANCH", "b"),
        ("depot", "DEPARTMENT", "d"),
    ]

    issues: list[str] = []
    for kind, source_table, alias in branch_specs:
        branch_body = extract_branch_body(body, kind, source_table)
        if branch_body is None:
            issues.append(f"{kind} branch NOT FOUND")
            continue
        # Match: alias.source_pk = v_pk OR alias.source_pk = p_ref
        pred_re = re.compile(
            rf"{re.escape(alias)}\.source_pk\s*=\s*v_pk\s+OR\s+{re.escape(alias)}\.source_pk\s*=\s*p_ref",
            re.IGNORECASE,
        )
        if not pred_re.search(branch_body):
            issues.append(
                f"{kind} branch: dual-format OR predicate ({alias}.source_pk = v_pk OR ... = p_ref) NOT FOUND"
            )

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message="V26 dual-format OR predicate drift",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        message="V26 validate_scope_ref final function has dual-format OR predicate in all 4 branches",
    )


def check_workcube_schema_anchor_tables(schema_path: str) -> CheckResult:
    """Check 5: workcube-schema.json includes 5 anchor tables + minimum columns."""
    name = "workcube_schema_anchor_tables"
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
    except FileNotFoundError:
        return CheckResult(name=name, passed=False, message=f"Schema file not found: {schema_path}")
    except json.JSONDecodeError as exc:
        return CheckResult(name=name, passed=False, message=f"Schema JSON parse error: {exc}")

    tables = schema.get("tables", {})
    if not isinstance(tables, dict):
        return CheckResult(
            name=name,
            passed=False,
            message="schema.json 'tables' field missing or not a dict",
        )

    issues: list[str] = []
    for tname, required_cols in EXPECTED_ANCHOR_TABLES.items():
        if tname not in tables:
            issues.append(f"missing anchor table: {tname}")
            continue
        table_cols_raw = tables[tname].get("columns", []) or tables[tname].get("Columns", [])
        # Columns may be dicts {name: ...} or strings; normalize
        col_names: set[str] = set()
        for c in table_cols_raw:
            if isinstance(c, dict):
                col_names.add(c.get("name", c.get("Name", "")).upper())
            elif isinstance(c, str):
                col_names.add(c.upper())
        for req in required_cols:
            if req.upper() not in col_names:
                issues.append(f"{tname} missing column: {req}")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message="workcube-schema.json anchor table drift",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        message=f"workcube-schema.json includes all {len(EXPECTED_ANCHOR_TABLES)} anchor tables with minimum columns",
    )


def check_adr_0008_object_id_encoding(adr_path: str) -> CheckResult:
    """Check 6: ADR-0008 § Object id encoding has V25 transition map."""
    name = "adr_0008_object_id_encoding"
    try:
        with open(adr_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return CheckResult(name=name, passed=False, message=f"ADR file not found: {adr_path}")

    issues: list[str] = []

    # Required V25 namespace mention
    if "wc-our-company-" not in content:
        issues.append("ADR-0008 missing V25 namespace 'wc-our-company-' literal")
    # OUR_COMPANY anchor mention
    if "OUR_COMPANY" not in content:
        issues.append("ADR-0008 missing OUR_COMPANY anchor mention")
    # workcube_mikrolink.our_company reference
    if "workcube_mikrolink.our_company" not in content.lower():
        issues.append("ADR-0008 missing 'workcube_mikrolink.our_company' table reference")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message="ADR-0008 § Object id encoding V25 transition map drift",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        message="ADR-0008 § Object id encoding has V25 transition map (wc-our-company- + OUR_COMPANY + .our_company)",
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_all_checks(args: argparse.Namespace) -> DriftReport:
    """Run all 6 checks; return DriftReport."""
    # Read input files
    try:
        v25_sql = Path(args.v25_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return DriftReport(
            overall="FAIL",
            checks=[CheckResult(name="invocation", passed=False, message=f"V25 SQL not found: {args.v25_path}")],
        )
    try:
        v26_sql = Path(args.v26_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return DriftReport(
            overall="FAIL",
            checks=[CheckResult(name="invocation", passed=False, message=f"V26 SQL not found: {args.v26_path}")],
        )

    checks = [
        check_v25_check_constraint(v25_sql),
        check_v25_v26_validate_scope_ref_anchor(v25_sql, v26_sql),
        check_v25_organization_company_default(v25_sql),
        check_v26_dual_format_predicate(v26_sql),
        check_workcube_schema_anchor_tables(args.schema_path),
        check_adr_0008_object_id_encoding(args.adr_0008_path),
    ]

    overall = "PASS" if all(c.passed for c in checks) else "FAIL"
    return DriftReport(overall=overall, checks=checks)


def format_human(report: DriftReport, verbose: bool) -> str:
    GREEN = "\033[1;32m" if sys.stdout.isatty() else ""
    RED = "\033[1;31m" if sys.stdout.isatty() else ""
    RESET = "\033[0m" if sys.stdout.isatty() else ""

    lines: list[str] = []
    for c in report.checks:
        sym = f"{GREEN}✓{RESET}" if c.passed else f"{RED}✗{RESET}"
        lines.append(f"  {sym} {c.name}: {c.message}")
        if verbose or not c.passed:
            for d in c.details:
                lines.append(f"      → {d}")

    overall_color = GREEN if report.overall == "PASS" else RED
    summary = f"{overall_color}DD-1 drift detection: {report.overall} ({sum(1 for c in report.checks if c.passed)}/{len(report.checks)}){RESET}"
    return "\n".join(lines) + "\n\n" + summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ADR-0011 DD-1 — anchor table + V25/V26 contract drift detection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--verbose", action="store_true", help="Detailed per-check log")
    parser.add_argument("--json", action="store_true", help="Structured JSON output")
    parser.add_argument("--v25-path", default=DEFAULT_V25_PATH)
    parser.add_argument("--v26-path", default=DEFAULT_V26_PATH)
    parser.add_argument("--schema-path", default=DEFAULT_SCHEMA_PATH)
    parser.add_argument("--adr-0008-path", default=DEFAULT_ADR_0008_PATH)
    args = parser.parse_args()

    # Resolve paths relative to CWD (CI runs from repo root by convention)
    report = run_all_checks(args)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_human(report, args.verbose))

    return 0 if report.overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
