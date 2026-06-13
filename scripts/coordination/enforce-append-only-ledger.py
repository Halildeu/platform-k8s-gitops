#!/usr/bin/env python3
"""Enforce append-only Coordination Ledger JSONL changes.

Both old and new ledgers must replay as valid. The old ledger's non-empty lines
must be an exact prefix of the new ledger's non-empty lines; any rewrite,
reorder, deletion, or truncation fails closed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = Path(__file__).with_name("verify-ledger-replay.py")
DEFAULT_AUTHORITY_PATH = REPO_ROOT / "docs" / "coordination" / "ledger-event-authority-v1.json"


class AppendOnlyError(Exception):
    """User-facing append-only refusal."""


def load_verifier_module() -> Any:
    spec = importlib.util.spec_from_file_location("coordination_ledger_replay", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise AppendOnlyError(f"failed to load verifier module from {VERIFIER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VERIFIER = load_verifier_module()


def non_empty_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def replay(path: Path, authority_path: Path, label: str) -> Any:
    authority = VERIFIER.load_authority(authority_path)
    result = VERIFIER.replay(path, authority)
    if not result.valid:
        raise AppendOnlyError(
            f"{label} ledger invalid line={result.invalid_line} reason={result.reason}"
        )
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", required=True, type=Path, help="base ledger JSONL")
    parser.add_argument("--new", required=True, type=Path, help="candidate ledger JSONL")
    parser.add_argument("--authority", default=str(DEFAULT_AUTHORITY_PATH), type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        old_lines = non_empty_lines(args.old)
        new_lines = non_empty_lines(args.new)
        if len(new_lines) < len(old_lines):
            raise AppendOnlyError("new ledger is shorter than old ledger")
        for index, expected in enumerate(old_lines):
            if new_lines[index] != expected:
                raise AppendOnlyError(f"ledger prefix mismatch at non-empty line {index + 1}")
        old_replay = replay(args.old, args.authority, "old") if old_lines else None
        new_replay = replay(args.new, args.authority, "new") if new_lines else None
        print(
            json.dumps(
                {
                    "valid": True,
                    "append_only": True,
                    "old_events": 0 if old_replay is None else old_replay.valid_events,
                    "new_events": 0 if new_replay is None else new_replay.valid_events,
                    "appended_lines": len(new_lines) - len(old_lines),
                },
                sort_keys=True,
            )
        )
        return 0
    except (AppendOnlyError, OSError) as exc:
        print(
            json.dumps(
                {
                    "valid": False,
                    "append_only": False,
                    "fail_closed": True,
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
