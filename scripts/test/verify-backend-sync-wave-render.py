#!/usr/bin/env python3
"""Verify backend sync waves on the rendered test overlay."""

from __future__ import annotations

import re
import sys
from pathlib import Path


EXPECTED = {
    "auth-service": "10",
    "permission-service": "11",
    "user-service": "12",
    "variant-service": "13",
    "core-data-service": "14",
    "report-service": "15",
    "schema-service": "16",
    "endpoint-admin-service": "17",
    "audio-gateway": "18",
    "meeting-service": "19",
    "transcript-service": "20",
    "audit-event-consumer-service": "21",
    "api-gateway": "22",
    # Faz 25 ATS: deliberately isolated AFTER the core authz chain (board #2549). A wave-0
    # boot failure here used to gate every backend wave, so the fix that unblocks delivery
    # cannot itself live inside that chain.
    "ats-interview-evidence": "30",
}


def rendered_waves(rendered: str) -> dict[str, str]:
    waves: dict[str, str] = {}
    for document in re.split(r"(?m)^---\s*$", rendered):
        if not re.search(r"(?m)^kind:\s+Deployment\s*$", document):
            continue
        metadata_match = re.search(
            r"(?m)^metadata:\s*\n(?P<body>(?:^[ \t].*(?:\n|$))*)",
            document,
        )
        if not metadata_match:
            continue
        metadata = metadata_match.group("body")
        name_match = re.search(r"(?m)^  name:\s+([^\s]+)\s*$", metadata)
        wave_match = re.search(
            r'(?m)^    argocd\.argoproj\.io/sync-wave:\s+"?([0-9]+)"?\s*$',
            metadata,
        )
        if name_match and wave_match:
            name = name_match.group(1)
            if name in waves:
                raise ValueError(f"duplicate rendered sync-wave Deployment: {name}")
            waves[name] = wave_match.group(1)
    return waves


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} <rendered-test-overlay.yaml>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    actual = rendered_waves(path.read_text(encoding="utf-8"))
    if actual != EXPECTED:
        print("FAIL: rendered backend sync-wave contract differs", file=sys.stderr)
        print(f"expected={EXPECTED}", file=sys.stderr)
        print(f"actual={actual}", file=sys.stderr)
        return 1
    if len(set(actual.values())) != len(actual):
        print("FAIL: rendered backend sync-wave values are not unique", file=sys.stderr)
        return 1

    print("PASS: rendered test overlay has 14 unique dependency-ordered backend sync waves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
