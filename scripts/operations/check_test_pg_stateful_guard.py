#!/usr/bin/env python3
"""
TPG-RESET-2026-05-11 guardrail.

Read-only checks for the failure mode where the test PostgreSQL data directory
is silently reinitialized and the init script only recreates roles/databases,
leaving product schemas absent.

The script intentionally does not restore data and does not mutate a live host.
It provides two independent checks:

* data-dir guard: PG_VERSION must exist unless an explicit empty-init override
  is provided by the operator.
* backup semantic guard: a pg_dumpall artifact must contain the minimal schema
  surface needed by permission-service, variant-service and OpenFGA.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, TextIO


@dataclass(frozen=True)
class RequiredMarker:
    name: str
    pattern: re.Pattern[str]
    reason: str


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    details: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


REQUIRED_DUMP_MARKERS: tuple[RequiredMarker, ...] = (
    RequiredMarker(
        "database.variants_db",
        re.compile(r"\bCREATE\s+DATABASE\s+variants_db\b", re.IGNORECASE),
        "variant-service schema restore target",
    ),
    RequiredMarker(
        "database.reports_db",
        re.compile(r"\bCREATE\s+DATABASE\s+reports_db\b", re.IGNORECASE),
        "permission-service data_access schema restore target",
    ),
    RequiredMarker(
        "database.openfga",
        re.compile(r"\bCREATE\s+DATABASE\s+openfga\b", re.IGNORECASE),
        "OpenFGA datastore restore target",
    ),
    RequiredMarker(
        "schema.variant_service",
        re.compile(r"\bCREATE\s+SCHEMA\s+variant_service\b", re.IGNORECASE),
        "variant-service schema namespace",
    ),
    RequiredMarker(
        "table.variant_service.themes",
        re.compile(
            r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?variant_service\.themes\b",
            re.IGNORECASE,
        ),
        "variant-service boot blocker seen during TPG reset",
    ),
    RequiredMarker(
        "schema.data_access",
        re.compile(r"\bCREATE\s+SCHEMA\s+data_access\b", re.IGNORECASE),
        "permission-service scoped access namespace",
    ),
    RequiredMarker(
        "table.data_access.scope",
        re.compile(
            r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?data_access\.scope\b",
            re.IGNORECASE,
        ),
        "permission-service boot blocker seen during TPG reset",
    ),
    RequiredMarker(
        "table.openfga.tuple",
        re.compile(
            r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public|openfga)\.tuple\b",
            re.IGNORECASE,
        ),
        "OpenFGA tuple store; live dumps may use public.* or openfga.* schema",
    ),
    RequiredMarker(
        "table.openfga.authorization_model",
        re.compile(
            r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public|openfga)\.authorization_model\b",
            re.IGNORECASE,
        ),
        "OpenFGA authorization model store; live dumps may use public.* or openfga.* schema",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TPG-RESET test PostgreSQL stateful guard",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="PostgreSQL data directory to guard, e.g. /srv/platform/stateful/test/postgres",
    )
    parser.add_argument(
        "--allow-empty-init",
        action="store_true",
        help="Explicitly allow a missing PG_VERSION data dir guard result",
    )
    parser.add_argument(
        "--dump",
        type=Path,
        help="pg_dumpall artifact (.sql or .sql.gz) to check semantically",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def open_text(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, mode="rt", encoding="utf-8", errors="replace")
    return path.open(mode="rt", encoding="utf-8", errors="replace")


def check_data_dir(path: Path, allow_empty_init: bool) -> CheckResult:
    if not path.exists():
        return CheckResult(
            "data_dir.exists",
            False,
            f"data dir does not exist: {path}",
            ["Refuse to treat an absent stateful directory as a healthy PG volume."],
        )
    if not path.is_dir():
        return CheckResult(
            "data_dir.isdir",
            False,
            f"data dir path is not a directory: {path}",
            [],
        )

    pg_version = path / "PG_VERSION"
    if pg_version.exists():
        version = pg_version.read_text(encoding="utf-8", errors="replace").strip()
        return CheckResult(
            "data_dir.pg_version",
            True,
            f"PG_VERSION present ({version or 'unknown'})",
            [str(pg_version)],
        )

    if allow_empty_init:
        return CheckResult(
            "data_dir.pg_version",
            True,
            "PG_VERSION missing but --allow-empty-init was explicitly provided",
            [
                "This is only acceptable for an intentional empty test PG bootstrap.",
                f"path={path}",
            ],
        )

    return CheckResult(
        "data_dir.pg_version",
        False,
        "PG_VERSION missing; silent initdb would recreate an empty test PG cluster",
        [
            "Set --allow-empty-init only for an explicit, operator-approved bootstrap.",
            f"path={path}",
        ],
    )


def scan_dump_lines(lines: Iterable[str]) -> tuple[set[str], list[str]]:
    found: set[str] = set()
    evidence: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        if len(found) == len(REQUIRED_DUMP_MARKERS):
            break
        for marker in REQUIRED_DUMP_MARKERS:
            if marker.name in found:
                continue
            if marker.pattern.search(line):
                found.add(marker.name)
                evidence.append(f"{marker.name}: line {line_number}")
    return found, evidence


def check_dump(path: Path) -> CheckResult:
    if not path.exists():
        return CheckResult(
            "dump.exists",
            False,
            f"dump does not exist: {path}",
            [],
        )
    if not path.is_file():
        return CheckResult(
            "dump.isfile",
            False,
            f"dump path is not a file: {path}",
            [],
        )

    try:
        with open_text(path) as handle:
            found, evidence = scan_dump_lines(handle)
    except OSError as exc:
        return CheckResult(
            "dump.readable",
            False,
            f"dump cannot be read: {exc}",
            [],
        )

    required = {marker.name for marker in REQUIRED_DUMP_MARKERS}
    missing = sorted(required - found)
    if missing:
        reasons = {
            marker.name: marker.reason for marker in REQUIRED_DUMP_MARKERS
            if marker.name in missing
        }
        return CheckResult(
            "dump.semantic_surface",
            False,
            f"dump is missing {len(missing)} required semantic marker(s)",
            [f"missing {name}: {reasons[name]}" for name in missing],
        )

    return CheckResult(
        "dump.semantic_surface",
        True,
        f"dump contains all {len(REQUIRED_DUMP_MARKERS)} required semantic markers",
        evidence,
    )


def main() -> int:
    args = parse_args()
    if args.data_dir is None and args.dump is None:
        print("at least one of --data-dir or --dump is required", file=sys.stderr)
        return 2

    results: list[CheckResult] = []
    if args.data_dir is not None:
        results.append(check_data_dir(args.data_dir, args.allow_empty_init))
    if args.dump is not None:
        results.append(check_dump(args.dump))

    overall_pass = all(result.passed for result in results)
    if args.json:
        print(json.dumps({
            "check": "TPG-RESET-2026-05-11",
            "overall": "PASS" if overall_pass else "FAIL",
            "results": [result.to_dict() for result in results],
        }, indent=2, ensure_ascii=False))
    else:
        print("TPG-RESET-2026-05-11 — test PostgreSQL stateful guard")
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            print(f"[{status}] {result.name}: {result.message}")
            for detail in result.details:
                print(f"  - {detail}")

    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
