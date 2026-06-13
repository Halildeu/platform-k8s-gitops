#!/usr/bin/env bash
# Offline harness for Coordination Ledger materialized comment render/verify path.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MATERIALIZER="$REPO_ROOT/scripts/coordination/materialize-ledger-comment.py"
WRITER="$REPO_ROOT/scripts/coordination/append-ledger-event.py"
VERIFIER="$REPO_ROOT/scripts/coordination/verify-ledger-replay.py"
WORK="$(mktemp -d -t coordination-ledger-materialized-comment.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

REPO="Halildeu/platform-k8s-gitops"
ISSUE="1498"
EVENT_UUID="00000000-0000-4000-8000-000000000301"
EVENT_TYPE="HEARTBEAT_EVIDENCE"
WRITER_ROLE="coordinator"
PAYLOAD_JSON='{"issue":1498,"session":"codex-materialized-comment-test"}'
PAYLOAD_HASH="$(python3 - <<'PY'
import hashlib
import json

payload = {"issue": 1498, "session": "codex-materialized-comment-test"}
body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
print("sha256:" + hashlib.sha256(body).hexdigest())
PY
)"
CREATED_AT="2026-06-13T12:00:00Z"
LEDGER="$WORK/ledger.jsonl"
BODY_JSON="$WORK/body.json"
BODY_FILE="$WORK/body.md"
COMMENT_JSON="$WORK/comment.json"
BINDING_JSON="$WORK/binding.json"

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

make_comment_fixture() {
  local body_file="$1"
  local output_file="$2"
  local updated_at="${3:-$CREATED_AT}"
  python3 - "$body_file" "$output_file" "$CREATED_AT" "$updated_at" <<'PY'
from pathlib import Path
import json
import sys

body = Path(sys.argv[1]).read_text(encoding="utf-8")
payload = {
    "id": 4698560001,
    "body": body,
    "user": {
        "id": 1001,
        "login": "Halildeu",
        "type": "User",
    },
    "created_at": sys.argv[3],
    "updated_at": sys.argv[4],
}
Path(sys.argv[2]).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
PY
}

printf 'coordination ledger materialized comment harness\n'

python3 "$MATERIALIZER" render \
  --repo "$REPO" \
  --issue "$ISSUE" \
  --event-uuid "$EVENT_UUID" \
  --event-type "$EVENT_TYPE" \
  --writer-role "$WRITER_ROLE" \
  --payload-hash "$PAYLOAD_HASH" \
  --verification-mode normal \
  --json >"$BODY_JSON"

python3 - "$BODY_JSON" "$BODY_FILE" <<'PY'
from pathlib import Path
import json
import sys

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert data["raw_body_hash"].startswith("sha256:")
assert data["payload_hash"].startswith("sha256:")
Path(sys.argv[2]).write_text(data["body"], encoding="utf-8")
PY

make_comment_fixture "$BODY_FILE" "$COMMENT_JSON"

python3 "$MATERIALIZER" verify \
  --repo "$REPO" \
  --issue "$ISSUE" \
  --event-uuid "$EVENT_UUID" \
  --event-type "$EVENT_TYPE" \
  --writer-role "$WRITER_ROLE" \
  --payload-hash "$PAYLOAD_HASH" \
  --verification-mode normal \
  --committed-at "$CREATED_AT" \
  --comment-json "$COMMENT_JSON" >"$BINDING_JSON"

python3 - "$BINDING_JSON" <<'PY'
from pathlib import Path
import json
import sys

binding = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert binding["surface"] == "github_issue_comment"
assert binding["repository"] == "Halildeu/platform-k8s-gitops"
assert binding["issue"] == 1498
assert binding["raw_body_hash"].startswith("sha256:")
assert binding["payload_hash"].startswith("sha256:")
assert binding["timestamp_tolerance_minutes"] == 5
PY
printf '  ok render + verify emits comment_binding JSON\n'

python3 "$WRITER" \
  --ledger "$LEDGER" \
  --expect-previous-hash GENESIS \
  --event-uuid "$EVENT_UUID" \
  --event-type "$EVENT_TYPE" \
  --writer-role "$WRITER_ROLE" \
  --committed-at "$CREATED_AT" \
  --payload-json "$PAYLOAD_JSON" \
  --comment-binding-file "$BINDING_JSON" >/dev/null

python3 "$VERIFIER" "$LEDGER" >/dev/null
printf '  ok emitted binding is accepted by ledger replay verifier\n'

BAD_BODY="$WORK/bad-body.md"
python3 - "$BODY_FILE" "$BAD_BODY" <<'PY'
from pathlib import Path
import sys

body = Path(sys.argv[1]).read_text(encoding="utf-8")
lines = []
for line in body.splitlines():
    if line.startswith("payload_hash: sha256:"):
        lines.append("payload_hash: sha256:0000000000000000000000000000000000000000000000000000000000000000")
    else:
        lines.append(line)
body = "\n".join(lines) + "\n"
Path(sys.argv[2]).write_text(body, encoding="utf-8")
PY

BAD_COMMENT="$WORK/bad-comment.json"
make_comment_fixture "$BAD_BODY" "$BAD_COMMENT"
expect_fail "comment marker payload_hash mismatch" \
  python3 "$MATERIALIZER" verify \
    --repo "$REPO" \
    --issue "$ISSUE" \
    --event-uuid "$EVENT_UUID" \
    --event-type "$EVENT_TYPE" \
    --writer-role "$WRITER_ROLE" \
    --payload-hash "$PAYLOAD_HASH" \
    --verification-mode normal \
    --committed-at "$CREATED_AT" \
    --comment-json "$BAD_COMMENT"
printf '  ok marker payload mismatch is rejected\n'

EDITED_COMMENT="$WORK/edited-comment.json"
make_comment_fixture "$BODY_FILE" "$EDITED_COMMENT" "2026-06-13T12:01:00Z"
expect_fail "comment.updated_at must equal comment.created_at" \
  python3 "$MATERIALIZER" verify \
    --repo "$REPO" \
    --issue "$ISSUE" \
    --event-uuid "$EVENT_UUID" \
    --event-type "$EVENT_TYPE" \
    --writer-role "$WRITER_ROLE" \
    --payload-hash "$PAYLOAD_HASH" \
    --verification-mode normal \
    --committed-at "$CREATED_AT" \
    --comment-json "$EDITED_COMMENT"
printf '  ok edited comment is rejected\n'

expect_fail "comment.created_at outside tolerance" \
  python3 "$MATERIALIZER" verify \
    --repo "$REPO" \
    --issue "$ISSUE" \
    --event-uuid "$EVENT_UUID" \
    --event-type "$EVENT_TYPE" \
    --writer-role "$WRITER_ROLE" \
    --payload-hash "$PAYLOAD_HASH" \
    --verification-mode normal \
    --committed-at "2026-06-13T12:10:01Z" \
    --comment-json "$COMMENT_JSON"
printf '  ok stale comment timestamp is rejected\n'

printf 'PASS coordination ledger materialized comment harness\n'
