#!/usr/bin/env python3
"""High-confidence secret scan for Coordination Ledger surfaces.

This scanner is intentionally narrower than repository-wide gitleaks. It
covers coordination ledgers, mirror snapshots, audit debt queues, and related
docs/scripts with high-confidence token patterns and emits machine-readable
findings. It avoids broad `TOKEN=` heuristics to keep source-code constants from
becoming false positives.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATHS = [
    "coordination-ledger",
    "docs/coordination",
    "docs/coordination-ledger-v1-plan.md",
    "docs/board-protocol.md",
    "scripts/coordination",
]
MAX_FILE_BYTES = 2_000_000
SKIP_PARTS = {".git", "node_modules", ".venv", "__pycache__"}

PATTERNS = [
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("bearer_token", re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._~+/-]{40,}={0,2}\b")),
]


def iter_candidate_files(paths: Iterable[str]) -> Iterable[Path]:
    seen: set[Path] = set()
    for raw in paths:
        matches = [Path(item) for item in glob.glob(raw, recursive=True)] if any(ch in raw for ch in "*?[") else [Path(raw)]
        for path in matches:
            if not path.is_absolute():
                path = REPO_ROOT / path
            if not path.exists():
                continue
            if path.is_dir():
                for child in path.rglob("*"):
                    if child.is_file():
                        yield from iter_candidate_files([str(child)])
                continue
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if path.stat().st_size <= MAX_FILE_BYTES:
                yield path


def redacted(line: str, start: int, end: int) -> str:
    token = line[start:end]
    replacement = token[:4] + "..." + token[-4:] if len(token) > 12 else "***"
    return line[:start] + replacement + line[end:]


def scan_file(path: Path) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return findings
    for line_number, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS:
            for match in pattern.finditer(line):
                findings.append(
                    {
                        "file": str(path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path),
                        "line": line_number,
                        "column": match.start() + 1,
                        "pattern": name,
                        "snippet": redacted(line, match.start(), match.end()).strip(),
                    }
                )
    return findings


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", action="append", dest="paths", help="file, directory, or glob to scan")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    paths = args.paths or DEFAULT_PATHS
    files = sorted(iter_candidate_files(paths))
    findings: list[dict[str, object]] = []
    for path in files:
        findings.extend(scan_file(path))
    print(
        json.dumps(
            {
                "valid": not findings,
                "files_scanned": len(files),
                "findings": findings,
            },
            sort_keys=True,
        )
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
