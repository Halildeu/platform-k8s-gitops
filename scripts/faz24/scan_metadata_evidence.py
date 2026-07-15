#!/usr/bin/env python3
"""Reject secret-like material without printing matched evidence content."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z ]+PRIVATE KEY-----", re.IGNORECASE),
    re.compile(rb"\bbearer\s+[A-Za-z0-9._~+/\-]+=*", re.IGNORECASE),
    re.compile(
        rb"\beyJ[A-Za-z0-9_-]{12,}" rb"\.[A-Za-z0-9_-]{12,}" rb"\.[A-Za-z0-9_-]{8,}\b",
        re.IGNORECASE,
    ),
)


class EvidenceScanError(ValueError):
    """Raised when the evidence directory is unsafe or contains a match."""


def scan_directory(root: Path) -> None:
    if not root.is_dir():
        raise EvidenceScanError("evidence directory is missing")

    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise EvidenceScanError(f"evidence symlink is not allowed: {path}")
        if not path.is_file():
            continue
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            raise EvidenceScanError(f"secret-like material found in: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan a metadata-only Faz 24 evidence directory.",
    )
    parser.add_argument("evidence_dir", type=Path)
    args = parser.parse_args()

    try:
        scan_directory(args.evidence_dir)
    except (EvidenceScanError, OSError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
