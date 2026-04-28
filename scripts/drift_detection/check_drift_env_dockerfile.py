#!/usr/bin/env python3
"""
ADR-0011 DD-4 — env prefix + Python compat + Dockerfile keyring lint
(Codex 019dd409 PARTIAL/AGREE-with-revisions).

Session 32 drift events'tan 2'si DD-4 kapsam:
- etl-worker env prefix drift (REPORT_MSSQL_ vs MSSQL_; ayrıca SCHEMA_MSSQL_ comment mismatch)
- Dockerfile signing convention drift (msodbcsql18 keyring [signed-by=...])

5 check:

1. etl-worker env prefix consistency (config.py fallback hierarchy)
2. Python version compat consistency (pyproject + Dockerfile + workflow + ruff/mypy)
3. Dockerfile keyring signing convention (msodbcsql18 + signed-by + gpg --dearmor)
4. tables.yaml schema validity (minimum field set + validation flags)
5. README docs sync (dar marker — make_source_pk + env prefix references; warn-only)

Exit codes:
  0 = pass (or all warnings only)
  1 = drift detected (hard checks fail)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PY = "scripts/migration/etl_worker/etl_worker/config.py"
DEFAULT_DOCKERFILE = "scripts/migration/etl_worker/Dockerfile"
DEFAULT_PYPROJECT = "scripts/migration/etl_worker/pyproject.toml"
DEFAULT_TABLES_YAML = "scripts/migration/etl_worker/config/tables.yaml"
DEFAULT_README = "scripts/migration/etl_worker/README.md"
DEFAULT_WORKFLOW = ".github/workflows/etl-worker-tests.yml"

EXPECTED_ENV_PREFIXES = ["MSSQL_", "REPORT_MSSQL_", "SCHEMA_MSSQL_", "WORKCUBE_MSSQL_"]
EXPECTED_PYTHON_VERSION = "3.12"

REQUIRED_TABLES_FIELDS = {"name", "source_schema", "columns", "idempotency_key", "parametric", "reports"}
REQUIRED_COLUMN_FIELDS = {"name", "pg_type", "nullable"}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    passed: bool
    is_warning: bool = False  # warn-only check (not hard fail)
    message: str = ""
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
# Checks
# ---------------------------------------------------------------------------


def check_env_prefix_consistency(config_path: str) -> CheckResult:
    """Check 1: config.py fallback hierarchy contains all 4 expected prefixes."""
    name = "env_prefix_consistency"
    p = Path(config_path)
    if not p.exists():
        return CheckResult(name=name, passed=False, message=f"config.py not found: {config_path}")

    src = p.read_text(encoding="utf-8")
    issues: list[str] = []

    # Each prefix must appear in fallback list (host/port/user/password/db at minimum)
    for prefix in EXPECTED_ENV_PREFIXES:
        # MSSQL_ alone is the unprefixed; check it appears as standalone token
        # MSSQL_HOST, MSSQL_USER, MSSQL_PASSWORD etc.
        if prefix == "MSSQL_":
            count = len(re.findall(r'"MSSQL_[A-Z_]+"', src))
        else:
            count = len(re.findall(rf'"{re.escape(prefix)}[A-Z_]+"', src))
        if count < 3:  # at least HOST/USER/PASSWORD
            issues.append(f"prefix {prefix!r}: only {count} env var references (expected ≥3)")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message="config.py env prefix hierarchy drift",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        message=f"config.py contains all {len(EXPECTED_ENV_PREFIXES)} expected env prefixes ({', '.join(EXPECTED_ENV_PREFIXES)})",
    )


def check_python_version_compat(pyproject_path: str, dockerfile_path: str, workflow_path: str) -> CheckResult:
    """Check 2: Python 3.12 version consistency across pyproject + Dockerfile + workflow."""
    name = "python_version_compat"
    issues: list[str] = []

    # pyproject
    try:
        pyp = Path(pyproject_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return CheckResult(name=name, passed=False, message=f"pyproject.toml not found: {pyproject_path}")

    if not re.search(r'requires-python\s*=\s*"\s*>=\s*3\.12', pyp):
        issues.append("pyproject.toml: requires-python >= 3.12 not found")
    if not re.search(r'python_version\s*=\s*"3\.12', pyp):
        issues.append("pyproject.toml: mypy python_version = 3.12 not found")
    if not re.search(r'target-version\s*=\s*"py312', pyp):
        issues.append("pyproject.toml: ruff target-version = py312 not found")

    # Dockerfile
    try:
        df = Path(dockerfile_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return CheckResult(name=name, passed=False, message=f"Dockerfile not found: {dockerfile_path}")

    if not re.search(r"FROM\s+python:3\.12", df):
        issues.append("Dockerfile: FROM python:3.12-* not found")

    # Workflow
    try:
        wf = Path(workflow_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        # Workflow might be optional or named differently
        issues.append(f"workflow not found: {workflow_path} (note: ETL workflow path may differ)")
    else:
        if not re.search(r'python-version:\s*"?3\.12', wf):
            issues.append(f"{workflow_path}: python-version: 3.12 not found")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message="Python version compat drift",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        message=f"Python {EXPECTED_PYTHON_VERSION} consistent across pyproject + Dockerfile + workflow",
    )


def check_dockerfile_keyring_signing(dockerfile_path: str) -> CheckResult:
    """Check 3: msodbcsql18 install uses signed-by + gpg --dearmor pattern."""
    name = "dockerfile_keyring_signing"
    try:
        df = Path(dockerfile_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return CheckResult(name=name, passed=False, message=f"Dockerfile not found: {dockerfile_path}")

    issues: list[str] = []

    # msodbcsql18 install
    if not re.search(r"msodbcsql18", df):
        issues.append("msodbcsql18 install line not found")

    # signed-by= pointing at keyring path
    if not re.search(r"\[\s*[^\]]*signed-by=[^\]]*microsoft.gpg", df, re.IGNORECASE):
        issues.append("Microsoft repo line missing [signed-by=...microsoft.gpg]")

    # gpg --dearmor command
    if not re.search(r"gpg\s+--dearmor", df):
        issues.append("gpg --dearmor command not found (raw .asc → .gpg conversion)")

    # Avoid global trust pattern (packages-microsoft-prod.deb)
    if "packages-microsoft-prod.deb" in df:
        issues.append("packages-microsoft-prod.deb global trust pattern detected (use signed-by=)")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message="Dockerfile keyring signing convention drift",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        message="Dockerfile uses correct msodbcsql18 + signed-by + gpg --dearmor keyring pattern",
    )


def check_tables_yaml_schema_validity(tables_yaml_path: str) -> CheckResult:
    """Check 4: tables.yaml schema discipline — required fields per entry + validation flags."""
    name = "tables_yaml_schema_validity"
    p = Path(tables_yaml_path)
    if not p.exists():
        return CheckResult(name=name, passed=False, message=f"tables.yaml not found: {tables_yaml_path}")

    text = p.read_text(encoding="utf-8")

    try:
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(text)
        return _check_tables_yaml_yaml(data, text)
    except ImportError:
        return _check_tables_yaml_manual(text)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name=name,
            passed=False,
            message=f"tables.yaml parse error: {exc}",
        )


def _check_tables_yaml_yaml(data: dict, text: str) -> CheckResult:
    name = "tables_yaml_schema_validity"
    issues: list[str] = []

    if not isinstance(data, dict):
        return CheckResult(name=name, passed=False, message="tables.yaml root is not a dict")

    tables = data.get("tables", [])
    if not isinstance(tables, list) or not tables:
        return CheckResult(name=name, passed=False, message="'tables' list missing or empty")

    for i, entry in enumerate(tables):
        if not isinstance(entry, dict):
            issues.append(f"entry #{i}: not a dict")
            continue
        missing_fields = REQUIRED_TABLES_FIELDS - set(entry.keys())
        if missing_fields:
            issues.append(f"entry '{entry.get('name', f'#{i}')}' missing fields: {sorted(missing_fields)}")
        cols = entry.get("columns")
        if not isinstance(cols, list) or not cols:
            issues.append(f"entry '{entry.get('name', f'#{i}')}' columns missing/empty")
            continue
        for j, c in enumerate(cols):
            if not isinstance(c, dict):
                continue
            col_missing = REQUIRED_COLUMN_FIELDS - set(c.keys())
            if col_missing:
                issues.append(
                    f"entry '{entry.get('name', f'#{i}')}' column #{j} missing: {sorted(col_missing)}"
                )

    # validation flags
    if "fail_on_pk_mismatch" not in text:
        issues.append("validation.fail_on_pk_mismatch flag not found")
    if "fail_on_missing_table" not in text:
        issues.append("validation.fail_on_missing_table flag not found")
    if "fail_on_empty_columns" not in text:
        issues.append("validation.fail_on_empty_columns flag not found")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message=f"tables.yaml schema validity drift ({len(issues)} issues)",
            details=issues[:15],
        )
    return CheckResult(
        name=name,
        passed=True,
        message=f"tables.yaml schema valid ({len(tables)} entries, all required fields + 3 validation flags)",
    )


def _check_tables_yaml_manual(text: str) -> CheckResult:
    """Fallback when PyYAML missing — line-based validation flags only."""
    name = "tables_yaml_schema_validity"
    issues: list[str] = []
    for flag in ["fail_on_pk_mismatch", "fail_on_missing_table", "fail_on_empty_columns"]:
        if flag not in text:
            issues.append(f"validation.{flag} flag not found")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message="tables.yaml manual validation flag drift",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        is_warning=True,
        message="tables.yaml validation flags present (manual scan; install PyYAML for full schema check)",
    )


def check_readme_docs_sync(readme_path: str) -> CheckResult:
    """Check 5: README dar marker — make_source_pk canonical + env prefix references (warn-only)."""
    name = "readme_docs_sync"
    p = Path(readme_path)
    if not p.exists():
        return CheckResult(
            name=name,
            passed=True,
            is_warning=True,
            message=f"README not found: {readme_path} (warn-only check)",
        )

    text = p.read_text(encoding="utf-8")
    issues: list[str] = []

    if "make_source_pk" not in text:
        issues.append("README missing 'make_source_pk' canonical reference")
    # env prefix mention — at least one of the prefixed forms
    has_env_prefix_mention = any(p in text for p in ["REPORT_MSSQL_", "SCHEMA_MSSQL_", "WORKCUBE_MSSQL_"])
    if not has_env_prefix_mention:
        issues.append("README missing env prefix fallback hierarchy reference")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            is_warning=True,  # warn-only, doesn't fail CI
            message="README docs sync warnings",
            details=issues,
        )
    return CheckResult(
        name=name,
        passed=True,
        is_warning=True,
        message="README contains make_source_pk + env prefix markers",
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_all_checks(args: argparse.Namespace) -> DriftReport:
    checks = [
        check_env_prefix_consistency(args.config_path),
        check_python_version_compat(args.pyproject_path, args.dockerfile_path, args.workflow_path),
        check_dockerfile_keyring_signing(args.dockerfile_path),
        check_tables_yaml_schema_validity(args.tables_yaml_path),
        check_readme_docs_sync(args.readme_path),
    ]
    # Hard-fail = any non-warning check failed
    has_hard_fail = any(not c.passed and not c.is_warning for c in checks)
    overall = "FAIL" if has_hard_fail else "PASS"
    return DriftReport(overall=overall, checks=checks)


def format_human(report: DriftReport, verbose: bool) -> str:
    GREEN = "\033[1;32m" if sys.stdout.isatty() else ""
    YELLOW = "\033[1;33m" if sys.stdout.isatty() else ""
    RED = "\033[1;31m" if sys.stdout.isatty() else ""
    RESET = "\033[0m" if sys.stdout.isatty() else ""

    lines: list[str] = []
    for c in report.checks:
        if not c.passed and c.is_warning:
            sym, color = "⚠", YELLOW
        elif not c.passed:
            sym, color = "✗", RED
        else:
            sym, color = "✓", GREEN
        lines.append(f"  {color}{sym}{RESET} {c.name}: {c.message}")
        if verbose or not c.passed:
            for d in c.details:
                lines.append(f"      → {d}")

    overall_color = GREEN if report.overall == "PASS" else RED
    summary = f"{overall_color}DD-4 env+dockerfile lint: {report.overall}{RESET}"
    return "\n".join(lines) + "\n\n" + summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ADR-0011 DD-4 — env prefix + Python compat + Dockerfile keyring lint.",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--config-path", default=DEFAULT_CONFIG_PY)
    parser.add_argument("--dockerfile-path", default=DEFAULT_DOCKERFILE)
    parser.add_argument("--pyproject-path", default=DEFAULT_PYPROJECT)
    parser.add_argument("--tables-yaml-path", default=DEFAULT_TABLES_YAML)
    parser.add_argument("--readme-path", default=DEFAULT_README)
    parser.add_argument("--workflow-path", default=DEFAULT_WORKFLOW)
    args = parser.parse_args()

    report = run_all_checks(args)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_human(report, args.verbose))
    return 0 if report.overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
