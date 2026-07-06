#!/usr/bin/env bash
# Offline harness for Coordination Ledger read-only reaper detector.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WRITER="$REPO_ROOT/scripts/coordination/append-ledger-event.py"
VERIFIER="$REPO_ROOT/scripts/coordination/verify-ledger-replay.py"
REAPER="$REPO_ROOT/scripts/coordination/reap-ledger-state.py"
WORK="$(mktemp -d -t coordination-ledger-reaper.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

LEDGER="$WORK/ledger.jsonl"
INVALID_LEDGER="$WORK/invalid-ledger.jsonl"
MIRROR="$WORK/mirror.json"
DEBT="$WORK/debt.jsonl"
REPORT="$WORK/report.json"
INVALID_REPORT="$WORK/invalid-report.json"

prefix_hash() {
  python3 "$VERIFIER" --json "$LEDGER" | python3 -c '
import json
import sys

data = json.load(sys.stdin)[0]
assert data["valid"] is True
print(data["valid_prefix_hash"])
'
}

append_event() {
  python3 "$WRITER" --ledger "$LEDGER" "$@" >/dev/null
}

expect_fail() {
  local expected="$1"
  shift
  local out rc
  set +e
  out="$("$@" 2>&1)"
  rc=$?
  set -e
  [ "$rc" -ne 0 ]
  printf '%s\n' "$out" | grep -q "$expected"
}

printf 'coordination ledger reaper harness\n'

append_event \
  --expect-previous-hash GENESIS \
  --event-uuid 00000000-0000-4000-8000-000000000501 \
  --event-type CLAIM_ACCEPTED \
  --writer-role coordinator \
  --committed-at 2026-06-13T10:00:00Z \
  --payload-json '{"repository":"Halildeu/platform-k8s-gitops","issue":1498,"session":"stale-session","claim_expires_at":"2026-06-13T13:00:00Z","heartbeat_interval_minutes":30,"heartbeat_grace_minutes":45}'

prefix="$(prefix_hash)"
append_event \
  --expect-previous-hash "sha256:$prefix" \
  --event-uuid 00000000-0000-4000-8000-000000000502 \
  --event-type HEARTBEAT_EVIDENCE \
  --writer-role coordinator \
  --committed-at 2026-06-13T10:10:00Z \
  --payload-json '{"repository":"Halildeu/platform-k8s-gitops","issue":1498,"session":"stale-session"}'

prefix="$(prefix_hash)"
append_event \
  --expect-previous-hash "sha256:$prefix" \
  --event-uuid 00000000-0000-4000-8000-000000000503 \
  --event-type CLAIM_ACCEPTED \
  --writer-role coordinator \
  --committed-at 2026-06-13T11:50:00Z \
  --payload-json '{"repository":"Halildeu/platform-k8s-gitops","issue":1501,"session":"active-session","claim_expires_at":"2026-06-13T14:00:00Z","heartbeat_interval_minutes":30,"heartbeat_grace_minutes":45}'

cat >"$MIRROR" <<'JSON'
{
  "issues": [
    {
      "repository": "Halildeu/platform-k8s-gitops",
      "issue": 1498,
      "status": "In Progress",
      "claim_session": "stale-session",
      "expires_at": "2026-06-13T13:00:00Z"
    },
    {
      "repository": "Halildeu/platform-k8s-gitops",
      "issue": 1500,
      "status": "In Progress",
      "claim_session": "ghost-session",
      "expires_at": "2026-06-13T14:00:00Z"
    },
    {
      "repository": "Halildeu/platform-k8s-gitops",
      "issue": 1501,
      "status": "Todo",
      "claim_session": "active-session",
      "expires_at": "2026-06-13T14:00:00Z"
    }
  ],
  "comments": [
    {
      "repository": "Halildeu/platform-k8s-gitops",
      "issue": 1498,
      "comment_id": 4698569999,
      "created_at": "2026-06-13T12:00:00Z"
    }
  ]
}
JSON

cat >"$DEBT" <<'JSONL'
{"deny_event_intent_id":"deny-1","issue":"Halildeu/platform-k8s-gitops#1498"}
{"deny_event_intent_id":"deny-1","issue":"Halildeu/platform-k8s-gitops#1498"}
{"deny_event_intent_id":"deny-2","issue":"Halildeu/platform-k8s-gitops#1500"}
JSONL

python3 "$REAPER" \
  --ledger "$LEDGER" \
  --mirror-json "$MIRROR" \
  --audit-debt-jsonl "$DEBT" \
  --now 2026-06-13T11:30:01Z >"$REPORT"

python3 - "$REPORT" <<'PY'
from pathlib import Path
import json
import sys

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert report["valid"] is True
assert report["fail_closed"] is False
types = {item["event_type"] for item in report["findings"]}
assert "CLAIM_STALE" in types
assert "MIRROR_ORPHAN_DETECTED" in types
assert "MIRROR_DRIFT_DETECTED" in types
assert "ORPHAN_COMMENT_DETECTED" in types
assert report["audit_debt"]["total"] == 3
assert report["audit_debt"]["unique"] == 2
assert report["audit_debt"]["duplicates"] == 1
assert report["audit_debt"]["retry_supported"] is True
assert report["audit_debt"]["retry_command"] == "python3 scripts/coordination/retry-audit-debt.py"
PY
printf '  ok stale claim, mirror drift/orphan, orphan comment, and debt dedupe are reported\n'

cp "$LEDGER" "$INVALID_LEDGER"
printf '{not-json}\n' >>"$INVALID_LEDGER"
set +e
python3 "$REAPER" --ledger "$INVALID_LEDGER" --now 2026-06-13T11:30:01Z >"$INVALID_REPORT"
rc=$?
set -e
[ "$rc" -eq 2 ]
python3 - "$INVALID_REPORT" <<'PY'
from pathlib import Path
import json
import sys

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert report["valid"] is False
assert report["fail_closed"] is True
assert report["findings"][0]["event_type"] == "LEDGER_INVALID_SUFFIX"
assert report["findings"][0]["writer_role"] == "reaper"
PY
printf '  ok invalid suffix produces fail-closed LEDGER_INVALID_SUFFIX finding\n'

expect_fail "mirror file not found" \
  python3 "$REAPER" --ledger "$LEDGER" --mirror-json "$WORK/missing.json"
printf '  ok missing mirror fixture is rejected when explicitly requested\n'

printf 'PASS coordination ledger reaper harness\n'
