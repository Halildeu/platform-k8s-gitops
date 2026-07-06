#!/usr/bin/env bash
# Offline harness for append-only Coordination Ledger enforcement.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENFORCER="$REPO_ROOT/scripts/coordination/enforce-append-only-ledger.py"
WRITER="$REPO_ROOT/scripts/coordination/append-ledger-event.py"
WORK="$(mktemp -d -t coordination-ledger-append-only.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

OLD="$WORK/old.jsonl"
NEW="$WORK/new.jsonl"
MUTATED="$WORK/mutated.jsonl"
TRUNCATED="$WORK/truncated.jsonl"
REPO="Halildeu/platform-k8s-gitops"

printf 'coordination ledger append-only harness\n'

OUT1="$(python3 "$WRITER" \
  --ledger "$OLD" \
  --expect-previous-hash GENESIS \
  --event-uuid "22222222-2222-4222-8222-222222222222" \
  --event-type CLAIM_ACCEPTED \
  --writer-role coordinator \
  --committed-at 2026-06-13T16:30:00Z \
  --payload-json "{\"repository\":\"$REPO\",\"issue\":1528,\"session\":\"session-a\",\"claim_expires_at\":\"2026-06-13T22:30:00Z\"}")"
cp "$OLD" "$NEW"
PREV="$(printf '%s' "$OUT1" | jq -r '.valid_prefix_hash')"
python3 "$WRITER" \
  --ledger "$NEW" \
  --expect-previous-hash "$PREV" \
  --event-uuid "33333333-3333-4333-8333-333333333333" \
  --event-type HEARTBEAT_EVIDENCE \
  --writer-role coordinator \
  --committed-at 2026-06-13T16:31:00Z \
  --payload-json "{\"repository\":\"$REPO\",\"issue\":1528,\"session\":\"session-a\"}" >/dev/null

python3 "$ENFORCER" --old "$OLD" --new "$NEW" >"$WORK/append-ok.json"
python3 - "$WORK/append-ok.json" <<'PY'
from pathlib import Path
import json
import sys

out = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert out["append_only"] is True
assert out["appended_lines"] == 1
PY
printf '  ok appended suffix is accepted\n'

python3 - "$NEW" "$MUTATED" <<'PY'
from pathlib import Path
import sys

lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
lines[0] = lines[0].replace("session-a", "session-b")
Path(sys.argv[2]).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
set +e
python3 "$ENFORCER" --old "$OLD" --new "$MUTATED" >"$WORK/mutated.json"
rc=$?
set -e
[ "$rc" -eq 1 ]
grep -q "prefix mismatch" "$WORK/mutated.json"
printf '  ok prefix rewrite is rejected\n'

: >"$TRUNCATED"
set +e
python3 "$ENFORCER" --old "$OLD" --new "$TRUNCATED" >"$WORK/truncated.json"
rc=$?
set -e
[ "$rc" -eq 1 ]
grep -q "shorter" "$WORK/truncated.json"
printf '  ok truncation is rejected\n'

printf 'PASS coordination ledger append-only harness\n'
