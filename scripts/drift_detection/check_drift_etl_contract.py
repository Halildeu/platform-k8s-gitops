#!/usr/bin/env python3
"""
ADR-0011 DD-2 — ETL canonical JSON contract drift detection (Codex 019dd409).

DD-2 odaklanır: ETL `make_source_pk()` canonical JSON üretimi + DB tarafının
(V26 final function + V16/V17 lineage TEXT contract) bu canonical p_ref'i
kabul ettiğini guard eder. DD-1'in V26 dual-format check'iyle çakışmaz —
DD-2 ETL↔DB **symmetric guard**.

6 check:

1. `make_source_pk()` static AST contract (json.dumps + separators + ensure_ascii + str(v))
2. `make_source_pk()` runtime sample outputs (single, composite, None, non-ASCII)
3. `test_transform.py` exact canonical assertions present
4. V26 final function each branch accepts canonical p_ref + raw v_pk fallback
5. V16/V17 PG lineage source_pk TEXT contract + UNIQUE (source_schema, source_table, source_pk)
6. tables.yaml anchor idempotency_key map matches expected anchor PKs + fail_on_pk_mismatch

Exit codes:
  0 = all checks pass
  1 = drift detected
  2 = invocation error

Usage:
  python3 scripts/drift_detection/check_drift_etl_contract.py [options]
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TRANSFORM_PATH = "scripts/migration/etl_worker/etl_worker/transform.py"
DEFAULT_TEST_TRANSFORM_PATH = "scripts/migration/etl_worker/tests/test_transform.py"
DEFAULT_TABLES_YAML_PATH = "scripts/migration/etl_worker/config/tables.yaml"
DEFAULT_V16_PATH = "sql/migration/V16__reports.sql"
DEFAULT_V17_PATH = "sql/migration/V17__etl_lineage_columns.sql"
DEFAULT_V26_PATH = "sql/migration/V26__source_pk_dual_format.sql"

EXPECTED_IDEMPOTENCY_KEYS = {
    "OUR_COMPANY": ["COMP_ID"],
    "COMPANY": ["COMPANY_ID"],
    "BRANCH": ["BRANCH_ID"],
    "PRO_PROJECTS": ["PROJECT_ID"],
    "DEPARTMENT": ["DEPARTMENT_ID"],
}

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
    overall: str
    checks: list[CheckResult]

    def to_dict(self) -> dict:
        return {"overall": self.overall, "checks": [c.to_dict() for c in self.checks]}


# ---------------------------------------------------------------------------
# SQL helpers (shared with anchor script — local copies for stdlib-only)
# ---------------------------------------------------------------------------


def strip_sql_comments(sql: str) -> str:
    out_lines: list[str] = []
    for line in sql.splitlines():
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
    pattern = re.compile(
        rf"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+[^$]*?{re.escape(function_name)}[^$]*?\$\$(.*?)\$\$",
        re.DOTALL | re.IGNORECASE,
    )
    matches = pattern.findall(sql_clean)
    if not matches:
        return None
    return matches[-1]


def extract_branch_body(function_body: str, kind: str, source_table: str) -> str | None:
    pattern = re.compile(
        rf"(?:IF|ELSIF)\s+p_kind\s*=\s*'{re.escape(kind)}'\s+AND\s+p_source_table\s*=\s*'{re.escape(source_table)}'\s+THEN(.*?)(?=ELSIF\s+|ELSE\s|END\s+IF)",
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(function_body)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_make_source_pk_static_contract(transform_path: str) -> CheckResult:
    """Check 1: make_source_pk() AST/source contract (json.dumps + canonical separators)."""
    name = "make_source_pk_static_contract"
    try:
        source = Path(transform_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return CheckResult(name=name, passed=False, message=f"transform.py not found: {transform_path}")

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return CheckResult(name=name, passed=False, message=f"transform.py parse error: {exc}")

    # Find make_source_pk function
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "make_source_pk":
            fn = node
            break

    if fn is None:
        return CheckResult(name=name, passed=False, message="make_source_pk function NOT FOUND in transform.py")

    # Body source code (re-render)
    body_src = ast.unparse(fn)
    issues: list[str] = []

    if "json.dumps" not in body_src:
        issues.append("missing json.dumps() call")
    if "ensure_ascii=False" not in body_src:
        issues.append("missing ensure_ascii=False (UTF-8 fidelity)")
    if "separators=(',', ':')" not in body_src and 'separators=(",", ":")' not in body_src:
        # ast.unparse may render as ', ' (single space); normalize check
        if "separators=" not in body_src or "(',', ':')" not in body_src.replace(" ", ""):
            issues.append("missing canonical separators=(',', ':') (compact JSON)")
    if "str(v)" not in body_src and "str(" not in body_src:
        issues.append("missing str(v) cast (None preservation requires explicit cast)")
    if "None" not in body_src or "is None" not in body_src:
        issues.append("missing None preservation branch")

    if issues:
        return CheckResult(name=name, passed=False, message="make_source_pk() static contract drift", details=issues)
    return CheckResult(
        name=name,
        passed=True,
        message="make_source_pk() static contract intact (json.dumps + canonical separators + ensure_ascii=False + None preservation)",
    )


def check_make_source_pk_runtime_outputs(transform_path: str) -> CheckResult:
    """Check 2: import make_source_pk + sample calls produce expected canonical outputs."""
    name = "make_source_pk_runtime_outputs"
    transform_path_obj = Path(transform_path).resolve()
    if not transform_path_obj.exists():
        return CheckResult(name=name, passed=False, message=f"transform.py not found: {transform_path}")

    try:
        spec = importlib.util.spec_from_file_location("dd2_etl_transform_runtime", transform_path_obj)
        if spec is None or spec.loader is None:
            return CheckResult(name=name, passed=False, message="failed to load transform.py spec")
        mod = importlib.util.module_from_spec(spec)
        # Register module in sys.modules BEFORE exec_module — required for some
        # exec patterns (annotations, dataclass forward refs).
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        make_source_pk = mod.make_source_pk  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name=name, passed=False, message=f"failed to import make_source_pk: {exc}")

    samples = [
        ({"COMP_ID": 1}, ["COMP_ID"], '["1"]'),
        ({"COMPANY_ID": 12345}, ["COMPANY_ID"], '["12345"]'),
        ({"COMPANY_ID": 12345, "COMPANYP_ID": 678}, ["COMPANY_ID", "COMPANYP_ID"], '["12345","678"]'),
        ({"COMPANY_ID": None}, ["COMPANY_ID"], "[null]"),
        ({"NAME": "AÇIK"}, ["NAME"], '["AÇIK"]'),  # non-ASCII fidelity
    ]

    issues: list[str] = []
    for row, key, expected in samples:
        actual = make_source_pk(row, key)
        if actual != expected:
            issues.append(f"input row={row} key={key} → expected {expected!r}, got {actual!r}")

    if issues:
        return CheckResult(name=name, passed=False, message="make_source_pk() runtime output drift", details=issues)
    return CheckResult(
        name=name,
        passed=True,
        message=f"make_source_pk() runtime outputs match canonical contract ({len(samples)} samples PASS)",
    )


def check_make_source_pk_unit_tests_present(test_path: str) -> CheckResult:
    """Check 3: test_transform.py contains exact canonical asserts."""
    name = "make_source_pk_unit_tests_present"
    try:
        source = Path(test_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return CheckResult(name=name, passed=False, message=f"test_transform.py not found: {test_path}")

    expected_asserts = [
        '\'["12345"]\'',
        '\'["12345","678"]\'',
        '\'[null]\'',
    ]

    issues: list[str] = []
    for exp in expected_asserts:
        if exp not in source:
            issues.append(f"missing canonical assert: {exp}")

    if issues:
        return CheckResult(name=name, passed=False, message="test_transform.py canonical asserts drift", details=issues)
    return CheckResult(
        name=name,
        passed=True,
        message="test_transform.py contains all 3 canonical asserts (single, composite, None)",
    )


def check_v26_accepts_etl_canonical_p_ref(v26_path: str) -> CheckResult:
    """Check 4: V26 final function each branch accepts canonical p_ref + raw v_pk fallback."""
    name = "v26_accepts_etl_canonical_p_ref"
    try:
        v26_sql = Path(v26_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return CheckResult(name=name, passed=False, message=f"V26 SQL not found: {v26_path}")

    sql_clean = strip_sql_comments(v26_sql)
    body = extract_function_body(sql_clean)
    if body is None:
        return CheckResult(name=name, passed=False, message="V26 validate_scope_ref body NOT FOUND")

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
        # canonical p_ref acceptance
        canonical_re = re.compile(rf"{re.escape(alias)}\.source_pk\s*=\s*p_ref", re.IGNORECASE)
        if not canonical_re.search(branch_body):
            issues.append(f"{kind} branch: canonical predicate ({alias}.source_pk = p_ref) missing")
        # raw fallback v_pk
        raw_re = re.compile(rf"{re.escape(alias)}\.source_pk\s*=\s*v_pk", re.IGNORECASE)
        if not raw_re.search(branch_body):
            issues.append(f"{kind} branch: raw fallback ({alias}.source_pk = v_pk) missing")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message="V26 ETL canonical p_ref acceptance drift",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        message="V26 final function accepts ETL canonical p_ref + raw v_pk fallback in all 4 branches",
    )


def check_pg_lineage_source_pk_text_contract(v16_path: str, v17_path: str) -> CheckResult:
    """Check 5: V16/V17 PG lineage source_pk TEXT contract + UNIQUE (source_schema, source_table, source_pk)."""
    name = "pg_lineage_source_pk_text_contract"
    issues: list[str] = []

    # V17 must add source_pk TEXT column dynamically
    try:
        v17_sql = Path(v17_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return CheckResult(name=name, passed=False, message=f"V17 SQL not found: {v17_path}")

    v17_clean = strip_sql_comments(v17_sql)
    if not re.search(r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+source_pk\s+TEXT", v17_clean, re.IGNORECASE):
        issues.append("V17: 'ADD COLUMN IF NOT EXISTS source_pk TEXT' not found")
    # V17 uses dynamic SQL for UNIQUE INDEX (per-table iteration with format()):
    # 'CREATE UNIQUE INDEX IF NOT EXISTS idx_%I_lineage_unique ...'.
    # Match the dynamic SQL string template OR a literal CREATE UNIQUE INDEX statement.
    has_dynamic_unique = re.search(
        r"CREATE\s+UNIQUE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+idx_.*?lineage_unique",
        v17_clean,
        re.IGNORECASE,
    )
    has_literal_unique = re.search(
        r"UNIQUE.*\(\s*source_schema\s*,\s*source_table\s*,\s*source_pk\s*\)",
        v17_clean,
        re.IGNORECASE,
    )
    if not (has_dynamic_unique or has_literal_unique):
        issues.append("V17: UNIQUE INDEX (source_schema, source_table, source_pk) — neither dynamic 'idx_<table>_lineage_unique' nor literal UNIQUE found")

    # V16 anchor tables also have source_pk TEXT
    try:
        v16_sql = Path(v16_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return CheckResult(name=name, passed=False, message=f"V16 SQL not found: {v16_path}")

    v16_clean = strip_sql_comments(v16_sql)
    text_count = len(re.findall(r"source_pk\s+TEXT", v16_clean, re.IGNORECASE))
    if text_count < 5:  # at least 5 anchor tables expected
        issues.append(f"V16: only {text_count} 'source_pk TEXT' definitions; expected ≥5 anchor tables")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message="V16/V17 PG lineage source_pk TEXT contract drift",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        message=f"V16/V17 PG lineage source_pk TEXT contract intact ({text_count} V16 + V17 dynamic ADD)",
    )


def check_anchor_idempotency_keys_documented(tables_yaml_path: str) -> CheckResult:
    """Check 6: tables.yaml anchor idempotency_key map matches expected + fail_on_pk_mismatch present."""
    name = "anchor_idempotency_keys_documented"
    try:
        text = Path(tables_yaml_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return CheckResult(name=name, passed=False, message=f"tables.yaml not found: {tables_yaml_path}")

    # Parse YAML — try standard library; fall back to manual line scan
    try:
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(text)
    except ImportError:
        # Manual line-based fallback (sufficient for our flat structure)
        return _check_anchor_idempotency_keys_manual(text)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name=name, passed=False, message=f"tables.yaml YAML parse error: {exc}")

    issues: list[str] = []
    tables = data.get("tables", []) if isinstance(data, dict) else []
    found: dict[str, list[str]] = {}
    for entry in tables:
        if not isinstance(entry, dict):
            continue
        nm = entry.get("name")
        ikey = entry.get("idempotency_key")
        if nm and ikey:
            found[nm] = ikey

    for tname, expected_keys in EXPECTED_IDEMPOTENCY_KEYS.items():
        if tname not in found:
            issues.append(f"anchor table {tname} missing in tables.yaml")
            continue
        if found[tname] != expected_keys:
            issues.append(f"{tname} idempotency_key: expected {expected_keys}, got {found[tname]}")

    # fail_on_pk_mismatch flag
    if "fail_on_pk_mismatch" not in text:
        issues.append("validation.fail_on_pk_mismatch: true not found in tables.yaml")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message="tables.yaml anchor idempotency_key map drift",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        message=f"tables.yaml anchor idempotency_key map intact ({len(EXPECTED_IDEMPOTENCY_KEYS)} anchors + fail_on_pk_mismatch)",
    )


def _check_anchor_idempotency_keys_manual(text: str) -> CheckResult:
    """Fallback when PyYAML not installed: line-based scan."""
    name = "anchor_idempotency_keys_documented"
    issues: list[str] = []
    for tname, expected_keys in EXPECTED_IDEMPOTENCY_KEYS.items():
        # Find: "- name: <tname>" then nearby "idempotency_key: [<keys>]"
        name_re = re.compile(rf"-\s*name:\s*{re.escape(tname)}\b", re.MULTILINE)
        m = name_re.search(text)
        if not m:
            issues.append(f"anchor table {tname} missing")
            continue
        # Look forward up to 30 lines for idempotency_key
        rest = text[m.end():]
        ikey_re = re.compile(r"idempotency_key:\s*\[([^\]]+)\]", re.MULTILINE)
        ikm = ikey_re.search(rest[:2000])
        if not ikm:
            issues.append(f"{tname} idempotency_key field missing")
            continue
        actual_keys = [k.strip() for k in ikm.group(1).split(",")]
        if actual_keys != expected_keys:
            issues.append(f"{tname} idempotency_key: expected {expected_keys}, got {actual_keys}")

    if "fail_on_pk_mismatch" not in text:
        issues.append("validation.fail_on_pk_mismatch: true not found")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message="tables.yaml anchor idempotency_key map drift (manual scan)",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        message="tables.yaml anchor idempotency_key map intact (manual scan, PyYAML not present)",
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_all_checks(args: argparse.Namespace) -> DriftReport:
    checks = [
        check_make_source_pk_static_contract(args.transform_path),
        check_make_source_pk_runtime_outputs(args.transform_path),
        check_make_source_pk_unit_tests_present(args.test_transform_path),
        check_v26_accepts_etl_canonical_p_ref(args.v26_path),
        check_pg_lineage_source_pk_text_contract(args.v16_path, args.v17_path),
        check_anchor_idempotency_keys_documented(args.tables_yaml_path),
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
    summary = f"{overall_color}DD-2 ETL contract drift detection: {report.overall} ({sum(1 for c in report.checks if c.passed)}/{len(report.checks)}){RESET}"
    return "\n".join(lines) + "\n\n" + summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ADR-0011 DD-2 — ETL canonical JSON contract drift detection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--transform-path", default=DEFAULT_TRANSFORM_PATH)
    parser.add_argument("--test-transform-path", default=DEFAULT_TEST_TRANSFORM_PATH)
    parser.add_argument("--tables-yaml-path", default=DEFAULT_TABLES_YAML_PATH)
    parser.add_argument("--v16-path", default=DEFAULT_V16_PATH)
    parser.add_argument("--v17-path", default=DEFAULT_V17_PATH)
    parser.add_argument("--v26-path", default=DEFAULT_V26_PATH)
    args = parser.parse_args()

    report = run_all_checks(args)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_human(report, args.verbose))
    return 0 if report.overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
