#!/usr/bin/env bash
# Offline harness for Coordination Ledger v1 append writer foundation.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WRITER="$REPO_ROOT/scripts/coordination/append-ledger-event.py"
VERIFIER="$REPO_ROOT/scripts/coordination/verify-ledger-replay.py"
WORK="$(mktemp -d -t coordination-ledger-writer.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

LEDGER="$WORK/coordination-ledger.jsonl"

line_count() {
  local path="$1"
  if [ ! -f "$path" ]; then
    printf '0\n'
    return
  fi
  python3 - "$path" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
print(sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()))
PY
}

valid_prefix_hash() {
  local path="$1"
  python3 "$VERIFIER" --json "$path" | python3 -c '
import json
import sys

data = json.load(sys.stdin)[0]
assert data["valid"] is True
print(data["valid_prefix_hash"])
'
}

expect_fail() {
  local expected="$1"
  shift
  local out rc
  set +e
  out="$("$@" 2>&1)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | grep -q "$expected"
}

printf 'coordination ledger append writer harness\n'

python3 "$WRITER" \
  --ledger "$LEDGER" \
  --expect-previous-hash GENESIS \
  --event-uuid 00000000-0000-4000-8000-000000000101 \
  --event-type BOOTSTRAP_KEY_REGISTRY \
  --writer-role bootstrap_path \
  --committed-at 2026-06-13T11:00:00Z \
  --payload-json '{"key_id":"coordination-bootstrap-v1"}' >/dev/null

python3 "$VERIFIER" "$LEDGER" >/dev/null
[ "$(line_count "$LEDGER")" -eq 1 ]
printf '  ok genesis append validates and writes one event\n'

prefix="$(valid_prefix_hash "$LEDGER")"
python3 "$WRITER" \
  --ledger "$LEDGER" \
  --expect-previous-hash "sha256:$prefix" \
  --event-uuid 00000000-0000-4000-8000-000000000102 \
  --event-type CLAIM_REQUEST \
  --writer-role coordinator \
  --committed-at 2026-06-13T11:01:00Z \
  --payload-json '{"issue":1498,"session":"codex-cas-ledger-writer-1498"}' >/dev/null

python3 "$VERIFIER" "$LEDGER" >/dev/null
[ "$(line_count "$LEDGER")" -eq 2 ]
printf '  ok expected previous hash CAS append succeeds\n'

PAYLOAD_FILE="$WORK/heartbeat-payload.json"
cat >"$PAYLOAD_FILE" <<'JSON'
{"issue":1498,"session":"codex-cas-ledger-writer-1498"}
JSON

prefix="$(valid_prefix_hash "$LEDGER")"
python3 "$WRITER" \
  --ledger "$LEDGER" \
  --expect-previous-hash "sha256:$prefix" \
  --event-uuid 00000000-0000-4000-8000-000000000103 \
  --event-type HEARTBEAT_EVIDENCE \
  --writer-role coordinator \
  --committed-at 2026-06-13T11:02:00Z \
  --payload-file "$PAYLOAD_FILE" \
  --metadata-json '{"source":"coordination-ledger-writer-test"}' >/dev/null

python3 "$VERIFIER" "$LEDGER" >/dev/null
[ "$(line_count "$LEDGER")" -eq 3 ]
printf '  ok payload-file and metadata-json append validates\n'

before_count="$(line_count "$LEDGER")"
expect_fail "cas_mismatch" \
  python3 "$WRITER" \
    --ledger "$LEDGER" \
    --expect-previous-hash "sha256:0000000000000000000000000000000000000000000000000000000000000000" \
    --event-uuid 00000000-0000-4000-8000-000000000104 \
    --event-type HEARTBEAT_EVIDENCE \
    --writer-role coordinator \
    --committed-at 2026-06-13T11:03:00Z \
    --payload-json '{"issue":1498,"session":"codex-cas-ledger-writer-1498"}'
[ "$(line_count "$LEDGER")" -eq "$before_count" ]
printf '  ok CAS mismatch refuses append without mutating ledger\n'

prefix="$(valid_prefix_hash "$LEDGER")"
before_count="$(line_count "$LEDGER")"
expect_fail "not authorized for CLAIM_EXPIRED" \
  python3 "$WRITER" \
    --ledger "$LEDGER" \
    --expect-previous-hash "sha256:$prefix" \
    --event-uuid 00000000-0000-4000-8000-000000000105 \
    --event-type CLAIM_EXPIRED \
    --writer-role coordinator \
    --committed-at 2026-06-13T11:04:00Z \
    --payload-json '{"issue":1498,"session":"codex-cas-ledger-writer-1498"}'
[ "$(line_count "$LEDGER")" -eq "$before_count" ]
printf '  ok unauthorized writer refuses append without mutating ledger\n'

INVALID_LEDGER="$WORK/invalid-ledger.jsonl"
cp "$LEDGER" "$INVALID_LEDGER"
printf '%s\n' '{"schemaVersion":"coordination-ledger-event/v1"}' >>"$INVALID_LEDGER"
before_count="$(line_count "$INVALID_LEDGER")"
expect_fail "existing_ledger_invalid" \
  python3 "$WRITER" \
    --ledger "$INVALID_LEDGER" \
    --expect-previous-hash "sha256:$prefix" \
    --event-uuid 00000000-0000-4000-8000-000000000106 \
    --event-type HEARTBEAT_EVIDENCE \
    --writer-role coordinator \
    --committed-at 2026-06-13T11:05:00Z \
    --payload-json '{"issue":1498,"session":"codex-cas-ledger-writer-1498"}'
[ "$(line_count "$INVALID_LEDGER")" -eq "$before_count" ]
printf '  ok invalid existing suffix refuses append without mutating ledger\n'

printf 'PASS coordination ledger append writer harness\n'
