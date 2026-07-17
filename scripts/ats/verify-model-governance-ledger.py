#!/usr/bin/env python3
"""Verify the exact two-row Faz 25 model-governance hash chain.

Input is the PostgreSQL pipe-delimited projection ordered by sequence. The
validator is intentionally independent of database credentials and image
execution so both first append and idempotent replay states are executable CI
fixtures. It prints only public refs and content hashes.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass


LEGACY_TRANSITION_ID = "mgt_25260000-0000-4000-8000-000000000001"
LEGACY_APPROVAL_REF = (
    "mapr_549a8e22a2c6f3c445be3e2405262bba5b80a78d72047fd95fa03deaa66a732d"
)
ARTIFACT_TRANSITION_ID = "mgt_25260000-0000-4000-8000-000000000002"
ARTIFACT_APPROVAL_REF = (
    "mapr_04cabd439b5b51992e86e215b9796f64d27b91dd951acdf542ab6635d517fc43"
)
ACTOR_REF = "cross-ai/faz25/2526"
GENESIS_HASH = "0" * 64
HASH_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Row:
    sequence: int
    transition_id: str
    approval_ref: str
    capability: str
    from_status: str
    to_status: str
    actor_ref: str
    reason_code: str
    entry_hash: str
    previous_hash: str

    @classmethod
    def parse(cls, line: str) -> Row:
        fields = line.split("|")
        if len(fields) != 10:
            raise ValueError("ledger row must contain exactly 10 fields")
        try:
            sequence = int(fields[0])
        except ValueError as exc:
            raise ValueError("ledger sequence must be an integer") from exc
        return cls(sequence, *fields[1:])


def require_transition(
    row: Row,
    *,
    sequence: int,
    transition_id: str,
    approval_ref: str,
    previous_hash: str,
) -> None:
    expected = (
        sequence,
        transition_id,
        approval_ref,
        "TRANSCRIBE",
        "UNINITIALIZED",
        "APPROVED",
        ACTOR_REF,
        "INITIAL_APPROVAL",
        previous_hash,
    )
    actual = (
        row.sequence,
        row.transition_id,
        row.approval_ref,
        row.capability,
        row.from_status,
        row.to_status,
        row.actor_ref,
        row.reason_code,
        row.previous_hash,
    )
    if actual != expected or HASH_RE.fullmatch(row.entry_hash) is None:
        raise ValueError(f"sequence {sequence} does not match the fixed transition")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--append-sequence", type=int)
    parser.add_argument("--append-hash")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (args.append_sequence is None) != (args.append_hash is None):
        raise ValueError("append sequence and hash must be supplied together")

    lines = [line for line in sys.stdin.read().splitlines() if line]
    rows = [Row.parse(line) for line in lines]
    allowed_lengths = {1, 2} if args.phase == "before" else {2}
    if len(rows) not in allowed_lengths:
        raise ValueError(f"phase {args.phase} requires exact retained ledger rows")

    legacy = rows[0]
    require_transition(
        legacy,
        sequence=0,
        transition_id=LEGACY_TRANSITION_ID,
        approval_ref=LEGACY_APPROVAL_REF,
        previous_hash=GENESIS_HASH,
    )

    state = "legacy-only"
    artifact_hash = "none"
    if len(rows) == 2:
        artifact = rows[1]
        require_transition(
            artifact,
            sequence=1,
            transition_id=ARTIFACT_TRANSITION_ID,
            approval_ref=ARTIFACT_APPROVAL_REF,
            previous_hash=legacy.entry_hash,
        )
        state = "artifact-approved"
        artifact_hash = artifact.entry_hash
        if args.append_sequence is not None and (
            args.append_sequence != 1 or args.append_hash != artifact.entry_hash
        ):
            raise ValueError("CLI append evidence does not match artifact ledger row")
    elif args.append_sequence is not None:
        raise ValueError("CLI append evidence supplied without artifact ledger row")

    print(
        "MODEL_GOVERNANCE_LEDGER_CONTRACT:v1 "
        f"outcome=OK phase={args.phase} state={state} "
        f"legacyEntryHash={legacy.entry_hash} artifactEntryHash={artifact_hash}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
