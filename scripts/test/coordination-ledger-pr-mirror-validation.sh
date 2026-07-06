#!/usr/bin/env bash
# Offline harness for Coordination Ledger PR mirror validation.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VALIDATOR="$REPO_ROOT/scripts/coordination/validate-pr-mirrors.py"
WRITER="$REPO_ROOT/scripts/coordination/append-ledger-event.py"
WORK="$(mktemp -d -t coordination-ledger-pr-mirror.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

LEDGER="$WORK/ledger.jsonl"
SNAPSHOT="$WORK/pr-snapshot.json"
REPO="Halildeu/platform-k8s-gitops"
ISSUE=1528
SESSION="session-pr-mirror"
EVENT_UUID="11111111-1111-4111-8111-111111111111"

printf 'coordination ledger PR mirror validation harness\n'

APPEND_OUT="$(python3 "$WRITER" \
  --ledger "$LEDGER" \
  --expect-previous-hash GENESIS \
  --event-uuid "$EVENT_UUID" \
  --event-type CLAIM_ACCEPTED \
  --writer-role coordinator \
  --committed-at 2026-06-13T16:20:00Z \
  --payload-json "{\"repository\":\"$REPO\",\"issue\":$ISSUE,\"session\":\"$SESSION\",\"claim_expires_at\":\"2026-06-13T22:20:00Z\"}")"
EVENT_HASH="$(printf '%s' "$APPEND_OUT" | jq -r '.event_hash')"

python3 - "$SNAPSHOT" "$REPO" "$ISSUE" "$EVENT_UUID" "$EVENT_HASH" "$SESSION" <<'PY'
from pathlib import Path
import json
import sys

path, repo, issue, event_uuid, event_hash, session = sys.argv[1:]
body = f"""PR body

<!-- coordination-ledger-pr-mirror:v1
coordination_state: active_winner
event_uuid: {event_uuid}
event_hash: {event_hash}
session: {session}
-->
"""
Path(path).write_text(
    json.dumps(
        {
            "repository": repo,
            "pull_requests": [
                {"number": 1529, "body": body, "expected_issue": int(issue)}
            ],
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
PY

python3 "$VALIDATOR" --ledger "$LEDGER" --snapshot "$SNAPSHOT" >"$WORK/valid.json"
python3 - "$WORK/valid.json" <<'PY'
from pathlib import Path
import json
import sys

out = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert out["valid"] is True
assert out["validated_pr_mirrors"][0]["coordination_state"] == "active_winner"
PY
printf '  ok valid PR marker references a valid ledger event\n'

python3 - "$SNAPSHOT" <<'PY'
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
data["pull_requests"][0]["body"] = data["pull_requests"][0]["body"].replace(
    "session: session-pr-mirror",
    "session: wrong-session",
)
path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
PY
set +e
python3 "$VALIDATOR" --ledger "$LEDGER" --snapshot "$SNAPSHOT" >"$WORK/session-mismatch.json"
rc=$?
set -e
[ "$rc" -eq 1 ]
grep -q "session mismatch" "$WORK/session-mismatch.json"
printf '  ok session mismatch fails closed\n'

python3 - "$SNAPSHOT" "$REPO" "$ISSUE" "$EVENT_UUID" "$SESSION" <<'PY'
from pathlib import Path
import json
import sys

path, repo, issue, event_uuid, session = sys.argv[1:]
wrong_hash = "sha256:" + ("a" * 64)
body = f"""PR body

<!-- coordination-ledger-pr-mirror:v1
coordination_state: active_winner
event_uuid: {event_uuid}
event_hash: {wrong_hash}
session: {session}
-->
"""
Path(path).write_text(
    json.dumps(
        {
            "repository": repo,
            "pull_requests": [
                {"number": 1530, "body": body, "expected_issue": int(issue)}
            ],
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
PY
set +e
python3 "$VALIDATOR" --ledger "$LEDGER" --snapshot "$SNAPSHOT" >"$WORK/hash-mismatch.json"
rc=$?
set -e
[ "$rc" -eq 1 ]
grep -q "event_hash mismatch" "$WORK/hash-mismatch.json"
printf '  ok event hash mismatch fails closed\n'

python3 - "$SNAPSHOT" "$REPO" "$ISSUE" "$EVENT_UUID" "$EVENT_HASH" "$SESSION" <<'PY'
from pathlib import Path
import json
import sys

path, repo, issue, event_uuid, event_hash, session = sys.argv[1:]
body = f"""PR body

<!-- coordination-ledger-pr-mirror:v1
coordination_state: arbitrary_string
event_uuid: {event_uuid}
event_hash: {event_hash}
session: {session}
-->
"""
Path(path).write_text(
    json.dumps(
        {
            "repository": repo,
            "pull_requests": [
                {"number": 1531, "body": body, "expected_issue": int(issue)}
            ],
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
PY
set +e
python3 "$VALIDATOR" --ledger "$LEDGER" --snapshot "$SNAPSHOT" >"$WORK/unknown-state.json"
rc=$?
set -e
[ "$rc" -eq 1 ]
grep -q "unknown coordination_state" "$WORK/unknown-state.json"
printf '  ok unknown coordination_state fails closed\n'

python3 - "$SNAPSHOT" "$REPO" <<'PY'
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
repo = sys.argv[2]
path.write_text(
    json.dumps({"repository": repo, "pull_requests": [{"number": 1530, "body": "no marker"}]}, sort_keys=True),
    encoding="utf-8",
)
PY
set +e
python3 "$VALIDATOR" --ledger "$LEDGER" --snapshot "$SNAPSHOT" >"$WORK/missing-marker.json"
rc=$?
set -e
[ "$rc" -eq 1 ]
grep -q "missing coordination-ledger-pr-mirror" "$WORK/missing-marker.json"
printf '  ok missing marker fails closed\n'

printf 'PASS coordination ledger PR mirror validation harness\n'
