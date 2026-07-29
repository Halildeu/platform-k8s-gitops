#!/usr/bin/env python3
"""Reduce raw VIEW_ONLY broker logs to an identifier-free sequence summary."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


LINE = re.compile(
    r"view-only frame: session=(?P<session>\S+) stream=(?P<stream>\S+) "
    r"seq=(?P<seq>[0-9]+) bytes=(?P<bytes>[0-9]+) type=(?P<content>\S+) "
    r"disposition=(?P<disposition>[A-Z_-]+) "
    r'ts=(?P<timestamp>[0-9]+)(?=$|[\s"}])'
)
ALLOWED = {"DELIVERED", "DROPPED_NO_VIEWER"}


def build(raw_log: bytes, session_id: str, browser: dict) -> dict:
    if not session_id or len(session_id) > 160 or not re.fullmatch(r"[A-Za-z0-9._:-]+", session_id):
        raise ValueError("session id is invalid")
    sequences: dict[int, tuple[str, int]] = {}
    disposition_counts = {"DELIVERED": 0, "DROPPED_NO_VIEWER": 0}
    for line in raw_log.decode("utf-8", errors="strict").splitlines():
        match = LINE.search(line)
        if match is None or match.group("session") != session_id:
            continue
        if int(match.group("bytes")) == 0:
            continue
        if match.group("content") != "image/png" or match.group("disposition") not in ALLOWED:
            raise ValueError("broker emitted an unexpected non-empty VIEW_ONLY frame classification")
        seq = int(match.group("seq"))
        timestamp = int(match.group("timestamp"))
        if timestamp <= 0:
            raise ValueError("broker VIEW_ONLY frame timestamp is invalid")
        disposition = match.group("disposition")
        prior = sequences.setdefault(seq, (disposition, timestamp))
        if prior != (disposition, timestamp):
            raise ValueError("one frame sequence has conflicting dispositions")
    if len(sequences) < 100:
        raise ValueError("fewer than 100 distinct broker-received VIEW_ONLY frames")
    ordered = sorted(sequences.items())
    prior_timestamp = 0
    for _, (disposition, timestamp) in ordered:
        if timestamp < prior_timestamp:
            raise ValueError("broker VIEW_ONLY frame timestamps are not monotonic by sequence")
        prior_timestamp = timestamp
        disposition_counts[disposition] += 1
    first_seq, last_seq = min(sequences), max(sequences)
    if first_seq != 0:
        raise ValueError("VIEW_ONLY frame sequence did not start at zero")
    produced_sequence_count = last_seq + 1
    gap_count = produced_sequence_count - len(sequences)
    if gap_count < 0:
        raise ValueError("frame sequence summary is inconsistent")
    binding = browser.get("binding")
    observed_at = browser.get("observedAt")
    if not isinstance(binding, dict) or not isinstance(observed_at, str):
        raise ValueError("browser evidence binding or observedAt is missing")
    return {
        "schemaVersion": "faz22.6-viewer-frame-flow-raw-v1",
        "observedAt": observed_at,
        "binding": binding,
        "firstSeq": first_seq,
        "lastSeq": last_seq,
        "firstObservedAtEpochMillis": sequences[first_seq][1],
        "lastObservedAtEpochMillis": sequences[last_seq][1],
        "producedSequenceCount": produced_sequence_count,
        "brokerReceivedDistinctCount": len(sequences),
        "sequenceGapCount": gap_count,
        "dispositions": disposition_counts,
        "rawLogSha256": f"sha256:{hashlib.sha256(raw_log).hexdigest()}",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker-log", required=True, type=Path)
    parser.add_argument("--browser-evidence", required=True, type=Path)
    parser.add_argument("--session-id-env", default="SESSION_ID")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    import os
    result = build(
        args.broker_log.read_bytes(), os.environ.get(args.session_id_env, ""),
        json.loads(args.browser_evidence.read_text(encoding="utf-8")),
    )
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
