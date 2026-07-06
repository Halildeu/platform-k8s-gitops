#!/usr/bin/env bash
# Offline harness for Coordination Ledger tombstone/supersede planning.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLANNER="$REPO_ROOT/scripts/coordination/tombstone-supersede-flow.py"
WRITER="$REPO_ROOT/scripts/coordination/append-ledger-event.py"
CLAIM_STATE="$REPO_ROOT/scripts/coordination/ledger-claim-state.py"
WORK="$(mktemp -d -t coordination-ledger-tombstone.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

LEDGER="$WORK/ledger.jsonl"
INVALID="$WORK/invalid.jsonl"
MIRROR="$WORK/mirror.json"
REPO="Halildeu/platform-k8s-gitops"
ISSUE=1528
NEW_ISSUE=1529
SESSION="session-tombstone"

printf 'coordination ledger tombstone/supersede harness\n'

python3 "$WRITER" \
  --ledger "$LEDGER" \
  --expect-previous-hash GENESIS \
  --event-uuid "44444444-4444-4444-8444-444444444444" \
  --event-type CLAIM_ACCEPTED \
  --writer-role coordinator \
  --committed-at 2026-06-13T16:40:00Z \
  --payload-json "{\"repository\":\"$REPO\",\"issue\":$ISSUE,\"session\":\"$SESSION\",\"claim_expires_at\":\"2026-06-13T22:40:00Z\"}" >/dev/null

python3 "$PLANNER" \
  --ledger "$LEDGER" \
  --phase tombstone \
  --repo "$REPO" \
  --issue "$ISSUE" \
  --reason "duplicate coordination issue" \
  --now 2026-06-13T16:41:00Z >"$WORK/tombstone.json"
python3 - "$WORK/tombstone.json" <<'PY'
from pathlib import Path
import json
import sys

out = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert out["status"] == "planned"
plan = out["plans"][0]
assert plan["event_type"] == "TOMBSTONE_CHAIN"
assert plan["payload"]["permission"] is False
PY
printf '  ok tombstone plan is audit/deny only\n'

cat >"$MIRROR" <<JSON
{
  "repository": "$REPO",
  "issue": $ISSUE,
  "superseded_by_issue": $NEW_ISSUE,
  "issue_body_verified": true,
  "project_verified": true,
  "pr_mirrors_verified": true,
  "verified_at": "2026-06-13T16:42:00Z"
}
JSON
python3 "$PLANNER" \
  --ledger "$LEDGER" \
  --phase supersede \
  --repo "$REPO" \
  --issue "$ISSUE" \
  --new-issue "$NEW_ISSUE" \
  --reason "replace stale issue with final hardening issue" \
  --mirror-verification-json "$MIRROR" \
  --now 2026-06-13T16:43:00Z >"$WORK/supersede.json"
python3 - "$WORK/supersede.json" <<'PY'
from pathlib import Path
import json
import sys

out = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
plan = out["plans"][0]
assert plan["event_type"] == "SUPERSEDE_ISSUE"
assert plan["payload"]["old_permission"] is False
assert plan["payload"]["new_issue_claim_required"] is True
PY
printf '  ok supersede plan requires mirror verification and keeps old issue denied\n'

cp "$LEDGER" "$INVALID"
printf '{not-json}\n' >>"$INVALID"
set +e
python3 "$PLANNER" \
  --ledger "$INVALID" \
  --phase tombstone \
  --repo "$REPO" \
  --issue "$ISSUE" \
  --reason "invalid ledger should fail" >"$WORK/invalid.json"
rc=$?
set -e
[ "$rc" -eq 1 ]
grep -q "ledger invalid" "$WORK/invalid.json"
printf '  ok invalid ledger suffix fails closed\n'

set +e
python3 "$PLANNER" \
  --ledger "$LEDGER" \
  --phase supersede \
  --repo "$REPO" \
  --issue "$ISSUE" \
  --new-issue "$ISSUE" \
  --reason "same issue invalid" \
  --mirror-verification-json "$MIRROR" >"$WORK/same-issue.json"
rc=$?
set -e
[ "$rc" -eq 1 ]
grep -q "must differ" "$WORK/same-issue.json"
printf '  ok self-supersede is rejected\n'

printf 'PASS coordination ledger tombstone/supersede harness\n'
