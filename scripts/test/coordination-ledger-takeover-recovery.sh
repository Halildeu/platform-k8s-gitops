#!/usr/bin/env bash
# Offline harness for Coordination Ledger takeover/recovery flow planner.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WRITER="$REPO_ROOT/scripts/coordination/append-ledger-event.py"
VERIFIER="$REPO_ROOT/scripts/coordination/verify-ledger-replay.py"
FLOW="$REPO_ROOT/scripts/coordination/takeover-recovery-flow.py"
WORK="$(mktemp -d -t coordination-ledger-takeover.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

LEDGER="$WORK/ledger.jsonl"
ACCEPT_REPORT="$WORK/accept.json"
COMMIT_REPORT="$WORK/commit.json"
RECOVERY_REPORT="$WORK/recovery.json"
MIRROR="$WORK/mirror.json"
APPROVAL="$WORK/approval.json"

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

plan_payload() {
  local report="$1"
  local index="${2:-0}"
  python3 - "$report" "$index" <<'PY'
from pathlib import Path
import json
import sys

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(json.dumps(report["plans"][int(sys.argv[2])]["payload"], sort_keys=True, separators=(",", ":")))
PY
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

printf 'coordination ledger takeover/recovery harness\n'

append_event \
  --expect-previous-hash GENESIS \
  --event-uuid 00000000-0000-4000-8000-000000000601 \
  --event-type CLAIM_ACCEPTED \
  --writer-role coordinator \
  --committed-at 2026-06-13T10:00:00Z \
  --payload-json '{"repository":"Halildeu/platform-k8s-gitops","issue":1498,"session":"old-session","claim_expires_at":"2026-06-13T13:00:00Z"}'

python3 "$FLOW" \
  --ledger "$LEDGER" \
  --phase accept \
  --repo Halildeu/platform-k8s-gitops \
  --issue 1498 \
  --old-session old-session \
  --new-session new-session \
  --reason "operator approved takeover" \
  --now 2026-06-13T10:05:00Z >"$ACCEPT_REPORT"

python3 - "$ACCEPT_REPORT" <<'PY'
from pathlib import Path
import json
import sys

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert report["mutates_github"] is False
assert report["mutates_ledger"] is False
plan = report["plans"][0]
assert plan["event_type"] == "TAKEOVER_ACCEPTED"
assert plan["payload"]["old_permission"] is False
assert plan["payload"]["new_permission"] is False
assert plan["payload"]["state"] == "takeover_pending_mirror"
PY
printf '  ok accept phase plans no-permission takeover pending event\n'

prefix="$(prefix_hash)"
append_event \
  --expect-previous-hash "sha256:$prefix" \
  --event-uuid 00000000-0000-4000-8000-000000000602 \
  --event-type TAKEOVER_ACCEPTED \
  --writer-role coordinator \
  --committed-at 2026-06-13T10:05:00Z \
  --payload-json "$(plan_payload "$ACCEPT_REPORT")"

expect_fail "mirror verification JSON is required" \
  python3 "$FLOW" \
    --ledger "$LEDGER" \
    --phase commit \
    --repo Halildeu/platform-k8s-gitops \
    --issue 1498 \
    --old-session old-session \
    --new-session new-session \
    --now 2026-06-13T10:06:00Z
printf '  ok commit phase refuses without mirror verification\n'

cat >"$MIRROR" <<'JSON'
{
  "repository": "Halildeu/platform-k8s-gitops",
  "issue": 1498,
  "old_session": "old-session",
  "new_session": "new-session",
  "issue_body_verified": true,
  "project_verified": true,
  "pr_mirrors_verified": true,
  "verified_at": "2026-06-13T10:06:00Z"
}
JSON

python3 "$FLOW" \
  --ledger "$LEDGER" \
  --phase commit \
  --repo Halildeu/platform-k8s-gitops \
  --issue 1498 \
  --old-session old-session \
  --new-session new-session \
  --mirror-verification-json "$MIRROR" \
  --now 2026-06-13T10:06:30Z >"$COMMIT_REPORT"

python3 - "$COMMIT_REPORT" <<'PY'
from pathlib import Path
import json
import sys

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
plan = report["plans"][0]
assert plan["event_type"] == "TAKEOVER_COMMITTED"
assert plan["payload"]["old_permission"] is False
assert plan["payload"]["new_permission"] is True
assert plan["payload"]["state"] == "active_winner"
assert plan["payload"]["mirror_verification"]["project_verified"] is True
PY
printf '  ok commit phase requires verified mirrors before active winner plan\n'

cat >"$APPROVAL" <<'JSON'
{
  "repository": "Halildeu/platform-k8s-gitops",
  "issue": 1498,
  "session": "new-session",
  "approval_comment_id": 4698600001,
  "approved_by_login": "Halildeu",
  "approved_by_type": "User",
  "scope": "recovery",
  "approved_until": "2026-06-13T12:00:00Z",
  "reason": "solo-owner recovery"
}
JSON

python3 "$FLOW" \
  --ledger "$LEDGER" \
  --phase recovery \
  --repo Halildeu/platform-k8s-gitops \
  --issue 1498 \
  --new-session new-session \
  --owner-approval-json "$APPROVAL" \
  --now 2026-06-13T10:07:00Z >"$RECOVERY_REPORT"

python3 - "$RECOVERY_REPORT" <<'PY'
from pathlib import Path
import json
import sys

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
types = [plan["event_type"] for plan in report["plans"]]
assert types == ["OWNER_APPROVAL_EVIDENCE", "OWNER_APPROVED"]
assert report["plans"][1]["payload"]["requires_prior_owner_approval_evidence"] is True
PY
printf '  ok recovery phase plans owner evidence before approval grant\n'

cat >"$WORK/missing-scope.json" <<'JSON'
{
  "repository": "Halildeu/platform-k8s-gitops",
  "issue": 1498,
  "session": "new-session",
  "approval_comment_id": 4698600001,
  "approved_by_login": "Halildeu",
  "approved_by_type": "User",
  "approved_until": "2026-06-13T12:00:00Z",
  "reason": "solo-owner recovery"
}
JSON

expect_fail "owner approval scope is required" \
  python3 "$FLOW" \
    --ledger "$LEDGER" \
    --phase recovery \
    --repo Halildeu/platform-k8s-gitops \
    --issue 1498 \
    --new-session new-session \
    --owner-approval-json "$WORK/missing-scope.json"
printf '  ok missing recovery approval evidence is rejected\n'

printf 'PASS coordination ledger takeover/recovery harness\n'
