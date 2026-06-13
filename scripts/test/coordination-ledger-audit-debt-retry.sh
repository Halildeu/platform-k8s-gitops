#!/usr/bin/env bash
# Offline harness for CAS-backed Coordination Ledger audit-debt retry.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RETRY="$REPO_ROOT/scripts/coordination/retry-audit-debt.py"
MATERIALIZER="$REPO_ROOT/scripts/coordination/materialize-ledger-comment.py"
VERIFIER="$REPO_ROOT/scripts/coordination/verify-ledger-replay.py"
WORK="$(mktemp -d -t coordination-ledger-audit-debt-retry.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

LEDGER_BRANCH="coordination-ledger"
LEDGER_PATH="coordination-ledger/events.jsonl"
REPO="Halildeu/platform-k8s-gitops"
ISSUE="1526"
COMMITTED_AT="2026-06-13T15:00:00Z"
INTENT_ID="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

line_count() {
  local path="$1"
  python3 - "$path" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
print(sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()))
PY
}

bootstrap_remote() {
  local remote="$1" seed="$2"
  git init --bare --quiet "$remote"
  git init --quiet "$seed"
  git -C "$seed" config user.name "coordination-ledger-test"
  git -C "$seed" config user.email "coordination-ledger-test@acik.local"
  git -C "$seed" switch --quiet -c "$LEDGER_BRANCH"
  mkdir -p "$seed/coordination-ledger"
  : >"$seed/$LEDGER_PATH"
  git -C "$seed" add "$LEDGER_PATH"
  git -C "$seed" commit --quiet -m "bootstrap coordination ledger branch"
  git -C "$seed" push --quiet "$remote" "$LEDGER_BRANCH"
}

write_debt_queue() {
  local queue="$1" intent_id="$2"
  python3 - "$queue" "$intent_id" <<'PY'
from pathlib import Path
import json
import sys

queue = Path(sys.argv[1])
intent_id = sys.argv[2]
record = {
    "schemaVersion": "coordination-audit-debt/v1",
    "queued_at": "2026-06-13T14:55:00Z",
    "status": "blocked_audit_debt",
    "reason": "cas_writer_unavailable",
    "source": "board-sync-record-deny-v1",
    "queue_path": str(queue),
    "deny_event_intent_id": intent_id,
    "intent": {
        "allowed": False,
        "issue": "Halildeu/platform-k8s-gitops#1526",
        "session": "session-denied",
        "operation": "deploy",
        "permission_source": "project_issue_ledger_mirror_v1",
        "deny_code": "project_truth_stale",
        "deny_event_intent_id": intent_id,
        "details": [
            {
                "code": "project_truth_stale",
                "message": "Project truth stale"
            }
        ],
    },
}
queue.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
PY
}

make_comment_fixture_from_plan() {
  local plan="$1" fixtures="$2"
  python3 - "$plan" "$fixtures" "$MATERIALIZER" "$COMMITTED_AT" <<'PY'
from pathlib import Path
import json
import subprocess
import sys

plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
fixtures = Path(sys.argv[2])
materializer = sys.argv[3]
committed_at = sys.argv[4]
fixtures.mkdir(parents=True, exist_ok=True)

for index, item in enumerate(plan["to_emit"], start=1):
    body = subprocess.check_output(
        [
            "python3",
            materializer,
            "render",
            "--repo",
            item["repository"],
            "--issue",
            str(item["issue"]),
            "--event-uuid",
            item["event_uuid"],
            "--event-type",
            item["event_type"],
            "--writer-role",
            item["writer_role"],
            "--payload-hash",
            item["payload_hash"],
            "--verification-mode",
            "normal",
        ],
        text=True,
    )
    comment = {
        "id": 4698561000 + index,
        "body": body,
        "user": {
            "id": 1001,
            "login": "Halildeu",
            "type": "User",
        },
        "created_at": committed_at,
        "updated_at": committed_at,
    }
    (fixtures / f"{item['deny_event_intent_id']}.json").write_text(
        json.dumps(comment, sort_keys=True),
        encoding="utf-8",
    )
PY
}

fresh_checkout() {
  local remote="$1" checkout="$2"
  rm -rf "$checkout"
  git clone --quiet --branch "$LEDGER_BRANCH" "$remote" "$checkout"
}

printf 'coordination ledger audit-debt retry harness\n'

REMOTE="$WORK/remote.git"
SEED="$WORK/seed"
QUEUE="$WORK/audit-debt.jsonl"
FIXTURES="$WORK/comment-fixtures"
PLAN="$WORK/plan.json"
OUT="$WORK/retry-output.json"
CHECKOUT="$WORK/checkout"

bootstrap_remote "$REMOTE" "$SEED"
write_debt_queue "$QUEUE" "$INTENT_ID"
mkdir -p "$FIXTURES"

python3 "$RETRY" \
  --queue "$QUEUE" \
  --remote "$REMOTE" \
  --branch "$LEDGER_BRANCH" \
  --ledger-path "$LEDGER_PATH" \
  --comment-json-dir "$FIXTURES" \
  --committed-at "$COMMITTED_AT" \
  --limit 5 \
  --plan-only >"$PLAN"

python3 - "$PLAN" "$INTENT_ID" <<'PY'
from pathlib import Path
import json
import sys

plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert plan["pending_total"] == 1
assert len(plan["to_emit"]) == 1
item = plan["to_emit"][0]
assert item["deny_event_intent_id"] == sys.argv[2]
assert item["event_type"] == "DENY_RECORDED"
assert item["writer_role"] == "coordinator"
assert item["payload"]["deny_event_intent_id"] == sys.argv[2]
PY

make_comment_fixture_from_plan "$PLAN" "$FIXTURES"

python3 "$RETRY" \
  --queue "$QUEUE" \
  --remote "$REMOTE" \
  --branch "$LEDGER_BRANCH" \
  --ledger-path "$LEDGER_PATH" \
  --comment-json-dir "$FIXTURES" \
  --committed-at "$COMMITTED_AT" \
  --limit 5 >"$OUT"

fresh_checkout "$REMOTE" "$CHECKOUT"
python3 "$VERIFIER" "$CHECKOUT/$LEDGER_PATH" >/dev/null
[ "$(line_count "$CHECKOUT/$LEDGER_PATH")" -eq 1 ]
python3 - "$CHECKOUT/$LEDGER_PATH" "$OUT" "$QUEUE" "$INTENT_ID" <<'PY'
from pathlib import Path
import json
import sys

event = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()[0])
out = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
queue_lines = [json.loads(line) for line in Path(sys.argv[3]).read_text(encoding="utf-8").splitlines()]
intent_id = sys.argv[4]
assert event["event_type"] == "DENY_RECORDED"
assert event["writer_role"] == "coordinator"
assert event["payload"]["deny_event_intent_id"] == intent_id
assert event["comment_binding"]["payload_hash"] == event["payload_hash"]
assert out["status"] == "ok"
assert out["emitted"] == 1
assert queue_lines[-1]["status"] == "ledger_emitted"
assert queue_lines[-1]["deny_event_intent_id"] == intent_id
assert queue_lines[-1]["event_hash"] == event["event_hash"]
PY
printf '  ok local audit debt emits DENY_RECORDED through remote CAS\n'

ALREADY_QUEUE="$WORK/already-debt.jsonl"
write_debt_queue "$ALREADY_QUEUE" "$INTENT_ID"
python3 "$RETRY" \
  --queue "$ALREADY_QUEUE" \
  --remote "$REMOTE" \
  --branch "$LEDGER_BRANCH" \
  --ledger-path "$LEDGER_PATH" \
  --comment-json-dir "$FIXTURES" \
  --committed-at "$COMMITTED_AT" \
  --limit 5 >"$WORK/retry-already.json"

fresh_checkout "$REMOTE" "$CHECKOUT"
[ "$(line_count "$CHECKOUT/$LEDGER_PATH")" -eq 1 ]
python3 - "$WORK/retry-already.json" "$ALREADY_QUEUE" "$INTENT_ID" <<'PY'
from pathlib import Path
import json
import sys

out = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
queue_lines = [json.loads(line) for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()]
intent_id = sys.argv[3]
assert out["status"] == "ok"
assert out["emitted"] == 0
assert out["already_in_ledger"] == 1
assert out["failed"] == []
assert queue_lines[-1]["status"] == "already_in_ledger"
assert queue_lines[-1]["deny_event_intent_id"] == intent_id
PY
printf '  ok remote already-in-ledger state appends a local terminal marker without mutation\n'

python3 "$RETRY" \
  --queue "$QUEUE" \
  --remote "$REMOTE" \
  --branch "$LEDGER_BRANCH" \
  --ledger-path "$LEDGER_PATH" \
  --comment-json-dir "$FIXTURES" \
  --committed-at "$COMMITTED_AT" \
  --limit 5 >"$WORK/retry-again.json"

fresh_checkout "$REMOTE" "$CHECKOUT"
[ "$(line_count "$CHECKOUT/$LEDGER_PATH")" -eq 1 ]
python3 - "$WORK/retry-again.json" <<'PY'
from pathlib import Path
import json
import sys

out = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert out["status"] == "ok"
assert out["emitted"] == 0
assert out["failed"] == []
PY
printf '  ok rerun is idempotent and does not grow the ledger\n'

FAIL_REMOTE="$WORK/fail-remote.git"
FAIL_SEED="$WORK/fail-seed"
FAIL_QUEUE="$WORK/fail-debt.jsonl"
FAIL_CHECKOUT="$WORK/fail-checkout"
bootstrap_remote "$FAIL_REMOTE" "$FAIL_SEED"
write_debt_queue "$FAIL_QUEUE" "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"

set +e
python3 "$RETRY" \
  --queue "$FAIL_QUEUE" \
  --remote "$FAIL_REMOTE" \
  --branch "$LEDGER_BRANCH" \
  --ledger-path "$LEDGER_PATH" \
  --comment-json-dir "$WORK/missing-fixtures" \
  --committed-at "$COMMITTED_AT" \
  --limit 5 >"$WORK/fail-output.json" 2>"$WORK/fail-stderr.txt"
rc=$?
set -e
[ "$rc" -ne 0 ]
grep -q -- "--comment-json-dir must exist" "$WORK/fail-stderr.txt"
fresh_checkout "$FAIL_REMOTE" "$FAIL_CHECKOUT"
[ "$(line_count "$FAIL_CHECKOUT/$LEDGER_PATH")" -eq 0 ]
printf '  ok missing comment fixtures fail closed before ledger mutation\n'

printf 'PASS coordination ledger audit-debt retry harness\n'
