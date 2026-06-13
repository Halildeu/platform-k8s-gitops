#!/usr/bin/env bash
# Offline harness for remote/branch Coordination Ledger CAS append wrapper.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BRANCH_WRITER="$REPO_ROOT/scripts/coordination/append-ledger-branch.sh"
VERIFIER="$REPO_ROOT/scripts/coordination/verify-ledger-replay.py"
WORK="$(mktemp -d -t coordination-ledger-branch-cas.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

REMOTE="$WORK/remote.git"
SEED="$WORK/seed"
CHECKOUT="$WORK/checkout"
LEDGER_BRANCH="coordination-ledger"
LEDGER_PATH="coordination-ledger/events.jsonl"

line_count() {
  local path="$1"
  python3 - "$path" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
print(sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()))
PY
}

fresh_checkout() {
  rm -rf "$CHECKOUT"
  git clone --quiet --branch "$LEDGER_BRANCH" "$REMOTE" "$CHECKOUT"
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

printf 'coordination ledger branch CAS harness\n'

git init --bare --quiet "$REMOTE"
git init --quiet "$SEED"
git -C "$SEED" config user.name "coordination-ledger-test"
git -C "$SEED" config user.email "coordination-ledger-test@acik.local"
git -C "$SEED" switch --quiet -c "$LEDGER_BRANCH"
mkdir -p "$SEED/coordination-ledger"
: >"$SEED/$LEDGER_PATH"
git -C "$SEED" add "$LEDGER_PATH"
git -C "$SEED" commit --quiet -m "bootstrap coordination ledger branch"
git -C "$SEED" push --quiet "$REMOTE" "$LEDGER_BRANCH"

bash "$BRANCH_WRITER" \
  --remote "$REMOTE" \
  --branch "$LEDGER_BRANCH" \
  --ledger-path "$LEDGER_PATH" \
  --commit-title "coordination ledger append test bootstrap" \
  --commit-message "Tracked by #1498" \
  -- \
  --expect-previous-hash GENESIS \
  --event-uuid 00000000-0000-4000-8000-000000000201 \
  --event-type BOOTSTRAP_KEY_REGISTRY \
  --writer-role bootstrap_path \
  --committed-at 2026-06-13T12:00:00Z \
  --payload-json '{"key_id":"coordination-bootstrap-v1"}' >/dev/null

fresh_checkout
python3 "$VERIFIER" "$CHECKOUT/$LEDGER_PATH" >/dev/null
[ "$(line_count "$CHECKOUT/$LEDGER_PATH")" -eq 1 ]
printf '  ok branch CAS genesis append pushed to remote ledger branch\n'

prefix="$(valid_prefix_hash "$CHECKOUT/$LEDGER_PATH")"
bash "$BRANCH_WRITER" \
  --remote "$REMOTE" \
  --branch "$LEDGER_BRANCH" \
  --ledger-path "$LEDGER_PATH" \
  --commit-title "coordination ledger append test claim request" \
  --commit-message "Tracked by #1498" \
  -- \
  --expect-previous-hash "sha256:$prefix" \
  --event-uuid 00000000-0000-4000-8000-000000000202 \
  --event-type CLAIM_REQUEST \
  --writer-role coordinator \
  --committed-at 2026-06-13T12:01:00Z \
  --payload-json '{"issue":1498,"session":"codex-branch-cas-test"}' >/dev/null

fresh_checkout
python3 "$VERIFIER" "$CHECKOUT/$LEDGER_PATH" >/dev/null
[ "$(line_count "$CHECKOUT/$LEDGER_PATH")" -eq 2 ]
printf '  ok branch CAS chained append pushed to remote ledger branch\n'

before_count="$(line_count "$CHECKOUT/$LEDGER_PATH")"
expect_fail "cas_mismatch" \
  bash "$BRANCH_WRITER" \
    --remote "$REMOTE" \
    --branch "$LEDGER_BRANCH" \
    --ledger-path "$LEDGER_PATH" \
    --commit-title "coordination ledger append test wrong hash" \
    --commit-message "Tracked by #1498" \
    -- \
    --expect-previous-hash "sha256:0000000000000000000000000000000000000000000000000000000000000000" \
    --event-uuid 00000000-0000-4000-8000-000000000203 \
    --event-type HEARTBEAT_EVIDENCE \
    --writer-role coordinator \
    --committed-at 2026-06-13T12:02:00Z \
    --payload-json '{"issue":1498,"session":"codex-branch-cas-test"}'

fresh_checkout
[ "$(line_count "$CHECKOUT/$LEDGER_PATH")" -eq "$before_count" ]
printf '  ok wrong expected hash refuses without remote ledger mutation\n'

expect_fail "bootstrap required" \
  bash "$BRANCH_WRITER" \
    --remote "$REMOTE" \
    --branch missing-ledger-branch \
    --ledger-path "$LEDGER_PATH" \
    --commit-title "coordination ledger append test missing branch" \
    -- \
    --expect-previous-hash GENESIS \
    --event-uuid 00000000-0000-4000-8000-000000000204 \
    --event-type BOOTSTRAP_KEY_REGISTRY \
    --writer-role bootstrap_path \
    --committed-at 2026-06-13T12:03:00Z \
    --payload-json '{"key_id":"coordination-bootstrap-v1"}'
printf '  ok missing ledger branch fails closed for bootstrap runbook\n'

printf 'PASS coordination ledger branch CAS harness\n'
