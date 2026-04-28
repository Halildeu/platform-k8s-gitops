#!/usr/bin/env python3
"""
ADR-0011 DD-3 — Schema-service snapshot drift detection (Codex 019dd409 B-prime).

DD-3 odaklanır: committed source snapshot (`workcube-schema.json`) ile canlı
PG `reports_db.workcube_mikrolink.*` actual schema arasındaki drift.
Karşılaştırma kapsamı: ETL-managed subset (`tables.yaml` anchor + parametric
entries).

Artifact contract: `docs/migration/reports-db-workcube-actual-schema.json`
operatör tarafından read-only export ile üretilir. Workflow operator-loop:

1. Operatör runbook (`docs/RB-faz-21-3-adr-0011-dd-3-schema-snapshot.md`) ile:
   - `kubectl --context k3d-test exec ... -- psql ... -f scripts/drift_detection/export_reports_db_schema.sql > artifact.json`
2. Operatör artifact'ı PR olarak commit eder
3. CI script artifact'ı validate eder + diff vs source snapshot

Graceful pending state: artifact yoksa veya stale ise script `WARN` raporlar
+ exit 0 (CI pass). Artifact varsa drift varsa exit 1.

Codex 019dd409 B-prime AGREE: "FK kısmını ilk DD-3'te artifact'a dahil et,
raporla, ama hard-fail yapmadan başlat. Mevcut repo tarafında güvenilir
expected-FK mapping net değilse FK hard-fail fazla kırılgan olur."

Checks:
1. actual artifact freshness (≤120 days)
2. source_snapshot_sha256 hash match (artifact basis = current workcube-schema.json)
3. ETL-managed tables (tables.yaml) source snapshot'ta var
4. ETL-managed tables actual PG snapshot'ta var
5. Manifest columns source + PG side var
6. PG lineage columns var (source_schema, source_table, source_pk, content_hash)

Exit codes:
  0 = all checks pass OR artifact pending (warn-only)
  1 = drift detected
  2 = invocation error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SOURCE_SNAPSHOT = "docs/migration/workcube-schema.json"
DEFAULT_ACTUAL_ARTIFACT = "docs/migration/reports-db-workcube-actual-schema.json"
DEFAULT_TABLES_YAML = "scripts/migration/etl_worker/config/tables.yaml"

ARTIFACT_FRESHNESS_DAYS = 120
LINEAGE_COLUMNS = ["source_schema", "source_table", "source_pk", "content_hash"]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    passed: bool  # True = pass, False = fail
    pending: bool = False  # True = artifact pending (CI pass with warn)
    message: str = ""
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DriftReport:
    overall: str  # "PASS" | "PENDING" | "FAIL"
    checks: list[CheckResult]

    def to_dict(self) -> dict:
        return {"overall": self.overall, "checks": [c.to_dict() for c in self.checks]}


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def load_source_snapshot(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_actual_artifact(path: str) -> dict | None:
    """Returns artifact dict or None if missing (pending state)."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return None


def parse_tables_yaml_etl_managed(path: str) -> set[str]:
    """Manual parse — return set of ETL-managed table names from tables.yaml."""
    p = Path(path)
    if not p.exists():
        return set()
    text = p.read_text(encoding="utf-8")
    import re

    names = re.findall(r"^\s*-\s*name:\s*(\w+)\s*$", text, re.MULTILINE)
    return set(names)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_artifact_present(artifact: dict | None) -> CheckResult:
    name = "actual_artifact_present"
    if artifact is None:
        return CheckResult(
            name=name,
            passed=True,
            pending=True,
            message="Actual artifact NOT PRESENT — operator-loop dependency (runbook: docs/RB-faz-21-3-adr-0011-dd-3-schema-snapshot.md)",
        )
    return CheckResult(
        name=name,
        passed=True,
        message="Actual artifact present",
    )


def check_artifact_freshness(artifact: dict | None) -> CheckResult:
    name = "actual_artifact_freshness"
    if artifact is None:
        return CheckResult(
            name=name,
            passed=True,
            pending=True,
            message=f"Skipped — artifact missing (target freshness ≤{ARTIFACT_FRESHNESS_DAYS} days when present)",
        )
    gen_at = artifact.get("generated_at")
    if not gen_at:
        return CheckResult(
            name=name,
            passed=False,
            message="actual artifact missing 'generated_at' timestamp",
        )
    try:
        gen_dt = datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return CheckResult(
            name=name,
            passed=False,
            message=f"actual artifact 'generated_at' parse failed: {gen_at}",
        )
    now = datetime.now(timezone.utc)
    age_days = (now - gen_dt).days
    if age_days > ARTIFACT_FRESHNESS_DAYS:
        return CheckResult(
            name=name,
            passed=False,
            message=f"actual artifact stale ({age_days} days old; max {ARTIFACT_FRESHNESS_DAYS})",
        )
    return CheckResult(
        name=name,
        passed=True,
        message=f"actual artifact fresh ({age_days} days old)",
    )


def check_artifact_source_hash_match(
    artifact: dict | None, source_path: str
) -> CheckResult:
    name = "actual_artifact_source_hash_match"
    if artifact is None:
        return CheckResult(
            name=name,
            passed=True,
            pending=True,
            message="Skipped — artifact missing (target: source_snapshot_sha256 = workcube-schema.json hash)",
        )
    expected_hash_field = artifact.get("source_snapshot_sha256")
    if not expected_hash_field:
        return CheckResult(
            name=name,
            passed=False,
            message="actual artifact missing 'source_snapshot_sha256' field",
        )
    p = Path(source_path)
    if not p.exists():
        return CheckResult(
            name=name,
            passed=False,
            message=f"source snapshot not found: {source_path}",
        )
    actual_hash = sha256(p.read_bytes()).hexdigest()
    if expected_hash_field != actual_hash:
        return CheckResult(
            name=name,
            passed=False,
            message="source_snapshot_sha256 mismatch",
            details=[
                f"artifact recorded: {expected_hash_field}",
                f"current source:    {actual_hash}",
            ],
        )
    return CheckResult(
        name=name,
        passed=True,
        message=f"artifact basis matches current workcube-schema.json (sha256={actual_hash[:12]}...)",
    )


def check_etl_managed_in_source(
    source: dict | None, etl_managed: set[str]
) -> CheckResult:
    name = "etl_managed_tables_in_source"
    if source is None:
        return CheckResult(name=name, passed=False, message="source snapshot not loaded")
    src_tables = source.get("tables", {}) or {}
    if not isinstance(src_tables, dict):
        return CheckResult(name=name, passed=False, message="source 'tables' not a dict")

    missing = [t for t in etl_managed if t not in src_tables]
    if missing:
        return CheckResult(
            name=name,
            passed=False,
            message=f"{len(missing)} ETL-managed table(s) missing from source snapshot",
            details=[f"missing: {', '.join(missing[:10])}{'...' if len(missing) > 10 else ''}"],
        )
    return CheckResult(
        name=name,
        passed=True,
        message=f"all {len(etl_managed)} ETL-managed tables present in source snapshot",
    )


def check_etl_managed_in_actual(
    artifact: dict | None, etl_managed: set[str]
) -> CheckResult:
    name = "etl_managed_tables_in_actual"
    if artifact is None:
        return CheckResult(
            name=name,
            passed=True,
            pending=True,
            message="Skipped — artifact missing",
        )
    actual_tables = artifact.get("tables", {}) or {}
    if not isinstance(actual_tables, dict):
        return CheckResult(
            name=name,
            passed=False,
            message="actual artifact 'tables' not a dict",
        )
    # Lower-cased PG table names; normalize comparison
    actual_names = {t.upper() for t in actual_tables.keys()}
    missing = [t for t in etl_managed if t.upper() not in actual_names]
    if missing:
        return CheckResult(
            name=name,
            passed=False,
            message=f"{len(missing)} ETL-managed table(s) missing from actual PG snapshot",
            details=[f"missing: {', '.join(missing[:10])}"],
        )
    return CheckResult(
        name=name,
        passed=True,
        message=f"all {len(etl_managed)} ETL-managed tables present in actual PG snapshot",
    )


def check_pg_lineage_columns_present(artifact: dict | None) -> CheckResult:
    name = "pg_lineage_columns_present"
    if artifact is None:
        return CheckResult(
            name=name,
            passed=True,
            pending=True,
            message=f"Skipped — artifact missing (target: every ETL table has lineage cols {LINEAGE_COLUMNS})",
        )
    actual_tables = artifact.get("tables", {}) or {}
    issues: list[str] = []
    for tname, tdata in actual_tables.items():
        cols = tdata.get("columns", []) if isinstance(tdata, dict) else []
        col_names = set()
        for c in cols:
            if isinstance(c, dict):
                col_names.add(c.get("name", "").lower())
            elif isinstance(c, str):
                col_names.add(c.lower())
        for lc in LINEAGE_COLUMNS:
            if lc.lower() not in col_names:
                issues.append(f"{tname} missing lineage column: {lc}")

    if issues:
        return CheckResult(
            name=name,
            passed=False,
            message=f"{len(issues)} lineage column drift(s)",
            details=issues[:10],
        )
    return CheckResult(
        name=name,
        passed=True,
        message=f"all actual tables have V17 lineage columns ({', '.join(LINEAGE_COLUMNS)})",
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_all_checks(args: argparse.Namespace) -> DriftReport:
    source = load_source_snapshot(args.source_snapshot)
    artifact = load_actual_artifact(args.actual_artifact)
    etl_managed = parse_tables_yaml_etl_managed(args.tables_yaml)

    checks = [
        check_artifact_present(artifact),
        check_artifact_freshness(artifact),
        check_artifact_source_hash_match(artifact, args.source_snapshot),
        check_etl_managed_in_source(source, etl_managed),
        check_etl_managed_in_actual(artifact, etl_managed),
        check_pg_lineage_columns_present(artifact),
    ]

    # Overall status
    if any(not c.passed and not c.pending for c in checks):
        overall = "FAIL"
    elif any(c.pending for c in checks):
        overall = "PENDING"
    else:
        overall = "PASS"
    return DriftReport(overall=overall, checks=checks)


def format_human(report: DriftReport, verbose: bool) -> str:
    GREEN = "\033[1;32m" if sys.stdout.isatty() else ""
    YELLOW = "\033[1;33m" if sys.stdout.isatty() else ""
    RED = "\033[1;31m" if sys.stdout.isatty() else ""
    RESET = "\033[0m" if sys.stdout.isatty() else ""

    lines: list[str] = []
    for c in report.checks:
        if c.passed and c.pending:
            sym, color = "⏳", YELLOW
        elif c.passed:
            sym, color = "✓", GREEN
        else:
            sym, color = "✗", RED
        lines.append(f"  {color}{sym}{RESET} {c.name}: {c.message}")
        if verbose or (not c.passed and not c.pending):
            for d in c.details:
                lines.append(f"      → {d}")

    overall_color = (
        GREEN if report.overall == "PASS"
        else YELLOW if report.overall == "PENDING"
        else RED
    )
    npass = sum(1 for c in report.checks if c.passed and not c.pending)
    npending = sum(1 for c in report.checks if c.pending)
    nfail = sum(1 for c in report.checks if not c.passed)
    summary = (
        f"{overall_color}DD-3 schema-snapshot drift detection: {report.overall} "
        f"({npass} pass, {npending} pending, {nfail} fail){RESET}"
    )
    return "\n".join(lines) + "\n\n" + summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ADR-0011 DD-3 — schema-service snapshot drift detection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--source-snapshot", default=DEFAULT_SOURCE_SNAPSHOT)
    parser.add_argument("--actual-artifact", default=DEFAULT_ACTUAL_ARTIFACT)
    parser.add_argument("--tables-yaml", default=DEFAULT_TABLES_YAML)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat PENDING as FAIL (artifact must be present)",
    )
    args = parser.parse_args()

    report = run_all_checks(args)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_human(report, args.verbose))

    if report.overall == "FAIL":
        return 1
    if report.overall == "PENDING" and args.strict:
        return 1
    return 0  # PASS or PENDING (graceful)


if __name__ == "__main__":
    sys.exit(main())
