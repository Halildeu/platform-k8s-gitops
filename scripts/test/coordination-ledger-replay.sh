#!/usr/bin/env bash
# Offline harness for Coordination Ledger v1 replay verifier.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERIFIER="$REPO_ROOT/scripts/coordination/verify-ledger-replay.py"
WORK="$(mktemp -d -t coordination-ledger-replay.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

make_ledger() {
  local path="$1"
  local mode="${2:-valid}"
  python3 - "$path" "$mode" <<'PY'
from __future__ import annotations

import copy
import hashlib
import json
import sys

path = sys.argv[1]
mode = sys.argv[2]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def event(uuid, event_type, writer_role, committed_at, payload, previous):
    item = {
        "schemaVersion": "coordination-ledger-event/v1",
        "event_uuid": uuid,
        "event_type": event_type,
        "writer_role": writer_role,
        "committed_at": committed_at,
        "previous_event_hash": None if previous is None else f"sha256:{previous}",
        "payload": payload,
    }
    item["payload_hash"] = f"sha256:{digest(payload)}"
    item["event_hash"] = f"sha256:{digest(item)}"
    return item


records = []
previous_hash = None
for item in [
    (
        "00000000-0000-4000-8000-000000000001",
        "BOOTSTRAP_KEY_REGISTRY",
        "bootstrap_path",
        "2026-06-13T10:00:00Z",
        {"key_id": "coordination-bootstrap-v1"},
    ),
    (
        "00000000-0000-4000-8000-000000000002",
        "CLAIM_REQUEST",
        "coordinator",
        "2026-06-13T10:01:00Z",
        {"issue": 1498, "session": "codex-a"},
    ),
    (
        "00000000-0000-4000-8000-000000000003",
        "CLAIM_ACCEPTED",
        "coordinator",
        "2026-06-13T10:02:00Z",
        {"issue": 1498, "session": "codex-a", "permission_state": "active_winner"},
    ),
]:
    record = event(*item, previous=previous_hash)
    records.append(record)
    previous_hash = record["event_hash"].removeprefix("sha256:")

if mode == "valid":
    records.append(copy.deepcopy(records[1]))
elif mode == "unauthorized-writer":
    bad = event(
        "00000000-0000-4000-8000-000000000004",
        "CLAIM_EXPIRED",
        "coordinator",
        "2026-06-13T10:03:00Z",
        {"issue": 1498, "session": "codex-a"},
        previous_hash,
    )
    records.append(bad)
elif mode == "duplicate-conflict":
    bad = copy.deepcopy(records[1])
    bad["payload"]["session"] = "codex-b"
    bad["payload_hash"] = f"sha256:{digest(bad['payload'])}"
    material = copy.deepcopy(bad)
    material.pop("event_hash", None)
    bad["event_hash"] = f"sha256:{digest(material)}"
    records.append(bad)
elif mode == "payload-hash-mismatch":
    bad = event(
        "00000000-0000-4000-8000-000000000004",
        "HEARTBEAT_EVIDENCE",
        "coordinator",
        "2026-06-13T10:03:00Z",
        {"issue": 1498, "session": "codex-a"},
        previous_hash,
    )
    bad["payload_hash"] = "sha256:" + "0" * 64
    records.append(bad)
elif mode == "time-regression":
    bad = event(
        "00000000-0000-4000-8000-000000000004",
        "HEARTBEAT_EVIDENCE",
        "coordinator",
        "2026-06-13T09:59:00Z",
        {"issue": 1498, "session": "codex-a"},
        previous_hash,
    )
    records.append(bad)
else:
    raise SystemExit(f"unknown mode: {mode}")

with open(path, "w", encoding="utf-8") as handle:
    for record in records:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
PY
}

expect_fail() {
  local mode="$1"
  local expected="$2"
  local ledger="$WORK/$mode.jsonl"
  local out rc
  make_ledger "$ledger" "$mode"
  set +e
  out="$(python3 "$VERIFIER" "$ledger" 2>&1)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | grep -q "$expected"
}

printf 'coordination ledger replay verifier harness\n'

valid="$WORK/valid.jsonl"
make_ledger "$valid" valid
python3 "$VERIFIER" "$valid"
python3 "$VERIFIER" --json "$valid" | python3 -c '
import json, sys
data = json.load(sys.stdin)
assert len(data) == 1
item = data[0]
assert item["valid"] is True
assert item["valid_events"] == 3
assert item["duplicate_events"] == 1
'
printf '  ok valid ledger with exact duplicate retry is accepted\n'

expect_fail unauthorized-writer "not authorized for CLAIM_EXPIRED"
printf '  ok unauthorized writer invalidates suffix\n'

expect_fail duplicate-conflict "duplicate event_uuid"
printf '  ok duplicate event_uuid with changed payload invalidates suffix\n'

expect_fail payload-hash-mismatch "payload_hash mismatch"
printf '  ok payload hash mismatch invalidates suffix\n'

expect_fail time-regression "committed_at moved backwards"
printf '  ok timestamp regression invalidates suffix\n'

printf 'PASS coordination ledger replay verifier harness\n'
