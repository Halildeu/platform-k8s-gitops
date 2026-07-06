#!/usr/bin/env bash
# Offline harness for high-confidence coordination secret scanning.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCANNER="$REPO_ROOT/scripts/coordination/scan-coordination-secrets.py"
WORK="$(mktemp -d -t coordination-secret-scan.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

printf 'coordination secret scan harness\n'

printf 'coordination_state: active_winner\nsession: safe-session\n' >"$WORK/clean.txt"
python3 "$SCANNER" --path "$WORK/clean.txt" >"$WORK/clean.json"
python3 - "$WORK/clean.json" <<'PY'
from pathlib import Path
import json
import sys

out = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert out["valid"] is True
assert out["findings"] == []
PY
printf '  ok clean coordination surface passes\n'

printf 'token: ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ1234567890\n' >"$WORK/leak.txt"
set +e
python3 "$SCANNER" --path "$WORK/leak.txt" >"$WORK/leak.json"
rc=$?
set -e
[ "$rc" -eq 1 ]
python3 - "$WORK/leak.json" <<'PY'
from pathlib import Path
import json
import sys

out = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert out["valid"] is False
assert out["findings"][0]["pattern"] == "github_token"
assert "..." in out["findings"][0]["snippet"]
PY
printf '  ok high-confidence token leak fails closed with redacted snippet\n'

printf 'PASS coordination secret scan harness\n'
