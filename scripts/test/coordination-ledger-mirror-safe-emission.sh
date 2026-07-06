#!/usr/bin/env bash
# Offline harness for mirror-safe Coordination Ledger event emission.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EMITTER="$REPO_ROOT/scripts/coordination/emit-ledger-event.sh"
MATERIALIZER="$REPO_ROOT/scripts/coordination/materialize-ledger-comment.py"
VERIFIER="$REPO_ROOT/scripts/coordination/verify-ledger-replay.py"
WORK="$(mktemp -d -t coordination-ledger-mirror-safe.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

REMOTE="$WORK/remote.git"
SEED="$WORK/seed"
CHECKOUT="$WORK/checkout"
LEDGER_BRANCH="coordination-ledger"
LEDGER_PATH="coordination-ledger/events.jsonl"
REPO="Halildeu/platform-k8s-gitops"
ISSUE="1498"
EVENT_UUID="00000000-0000-4000-8000-000000000401"
EVENT_TYPE="HEARTBEAT_EVIDENCE"
WRITER_ROLE="coordinator"
PAYLOAD_JSON='{"issue":1498,"session":"codex-mirror-safe-test"}'
COMMITTED_AT="2026-06-13T12:00:00Z"
BODY_FILE="$WORK/body.md"
COMMENT_JSON="$WORK/comment.json"
OUTPUT_JSON="$WORK/output.json"

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

payload_hash() {
  python3 - "$PAYLOAD_JSON" <<'PY'
import hashlib
import json
import sys

payload = json.loads(sys.argv[1])
body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
print("sha256:" + hashlib.sha256(body).hexdigest())
PY
}

make_comment_fixture() {
  local body_file="$1"
  local output_file="$2"
  python3 - "$body_file" "$output_file" "$COMMITTED_AT" <<'PY'
from pathlib import Path
import json
import sys

body = Path(sys.argv[1]).read_text(encoding="utf-8")
payload = {
    "id": 4698560401,
    "body": body,
    "user": {
        "id": 1001,
        "login": "Halildeu",
        "type": "User",
    },
    "created_at": sys.argv[3],
    "updated_at": sys.argv[3],
}
Path(sys.argv[2]).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
PY
}

printf 'coordination ledger mirror-safe emission harness\n'

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

python3 "$MATERIALIZER" render \
  --repo "$REPO" \
  --issue "$ISSUE" \
  --event-uuid "$EVENT_UUID" \
  --event-type "$EVENT_TYPE" \
  --writer-role "$WRITER_ROLE" \
  --payload-hash "$(payload_hash)" \
  --verification-mode normal >"$BODY_FILE"

make_comment_fixture "$BODY_FILE" "$COMMENT_JSON"

bash "$EMITTER" \
  --repo "$REPO" \
  --issue "$ISSUE" \
  --remote "$REMOTE" \
  --branch "$LEDGER_BRANCH" \
  --ledger-path "$LEDGER_PATH" \
  --commit-title "coordination ledger mirror-safe emission test" \
  --commit-message "Tracked by #1498" \
  --expect-previous-hash GENESIS \
  --event-uuid "$EVENT_UUID" \
  --event-type "$EVENT_TYPE" \
  --writer-role "$WRITER_ROLE" \
  --committed-at "$COMMITTED_AT" \
  --payload-json "$PAYLOAD_JSON" \
  --comment-json "$COMMENT_JSON" >"$OUTPUT_JSON"

fresh_checkout
python3 "$VERIFIER" "$CHECKOUT/$LEDGER_PATH" >/dev/null
[ "$(line_count "$CHECKOUT/$LEDGER_PATH")" -eq 1 ]
python3 - "$CHECKOUT/$LEDGER_PATH" "$OUTPUT_JSON" <<'PY'
from pathlib import Path
import json
import sys

event = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()[0])
output = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert output["status"] == "ledger_event_emitted_after_remote_cas"
assert output["issue_project_pr_mirrors_mutated"] is False
assert event["comment_binding"]["comment_id"] == 4698560401
assert event["comment_binding"]["payload_hash"] == event["payload_hash"]
assert output["comment_binding"] == event["comment_binding"]
PY
printf '  ok verified comment binding is appended only through remote CAS\n'

expect_fail "cas_mismatch" \
  bash "$EMITTER" \
    --repo "$REPO" \
    --issue "$ISSUE" \
    --remote "$REMOTE" \
    --branch "$LEDGER_BRANCH" \
    --ledger-path "$LEDGER_PATH" \
    --commit-title "coordination ledger mirror-safe emission wrong hash" \
    --commit-message "Tracked by #1498" \
    --expect-previous-hash "sha256:0000000000000000000000000000000000000000000000000000000000000000" \
    --event-uuid "$EVENT_UUID" \
    --event-type HEARTBEAT_EVIDENCE \
    --writer-role "$WRITER_ROLE" \
    --committed-at "$COMMITTED_AT" \
    --payload-json "$PAYLOAD_JSON" \
    --comment-json "$COMMENT_JSON"

fresh_checkout
[ "$(line_count "$CHECKOUT/$LEDGER_PATH")" -eq 1 ]
printf '  ok CAS mismatch refuses without ledger growth\n'

expect_fail "pass exactly one of --post-comment or --comment-json" \
  bash "$EMITTER" \
    --repo "$REPO" \
    --issue "$ISSUE" \
    --remote "$REMOTE" \
    --branch "$LEDGER_BRANCH" \
    --ledger-path "$LEDGER_PATH" \
    --expect-previous-hash GENESIS \
    --event-uuid 00000000-0000-4000-8000-000000000403 \
    --event-type HEARTBEAT_EVIDENCE \
    --writer-role "$WRITER_ROLE" \
    --committed-at "$COMMITTED_AT" \
    --payload-json "$PAYLOAD_JSON"
printf '  ok comment materialization mode is explicit\n'

printf 'PASS coordination ledger mirror-safe emission harness\n'
