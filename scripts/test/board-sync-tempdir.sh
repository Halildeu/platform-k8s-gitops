#!/usr/bin/env bash
# Offline harness for board-sync cache temp directory selection.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BOARD_SYNC="$REPO_ROOT/scripts/board-sync.sh"
TMP_ROOT="${BOARD_SYNC_TEST_TMPDIR:-$REPO_ROOT/.tmp}"
mkdir -p "$TMP_ROOT"
WORK="$(mktemp -d "$TMP_ROOT/board-sync-tempdir.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

FAKE_BIN="$WORK/bin"
mkdir -p "$FAKE_BIN" "$WORK/tmpdir" "$WORK/board-sync-tmpdir"

cat >"$FAKE_BIN/gh" <<'FAKE_GH'
#!/usr/bin/env bash
set -euo pipefail

{
  printf '%s\n' "$*"
} >>"${GH_LOG:-/dev/null}"

if [ "${1:-}" = "auth" ] && [ "${2:-}" = "status" ]; then
  exit 0
fi

if [ "${1:-}" = "api" ] && [ "${2:-}" = "rate_limit" ]; then
  printf '{"remaining":100,"limit":5000,"used":0,"reset":1782663290}\n'
  exit 0
fi

if [ "${1:-}" = "project" ] && [ "${2:-}" = "view" ]; then
  printf '{"id":"PVT_kwHOCx7tY84BIN2d","number":2}\n'
  exit 0
fi

if [ "${1:-}" = "project" ] && [ "${2:-}" = "item-list" ]; then
  printf '%s\n' "${BOARD_SYNC_CACHE_LIST_MARKER:-item-list}" >>"${ITEM_LIST_LOG:?}"
  cat <<'JSON'
{
  "items": [
    {
      "id": "PVTI_todo_42",
      "content": {
        "type": "Issue",
        "number": 42,
        "url": "https://github.com/Halildeu/platform-k8s-gitops/issues/42"
      },
      "title": "Todo issue",
      "status": "Todo",
      "priority": "P0",
      "faz": "Faz 24",
      "track": "gitops",
      "kind": "issue"
    }
  ]
}
JSON
  exit 0
fi

echo "unexpected gh call: $*" >&2
exit 99
FAKE_GH
chmod +x "$FAKE_BIN/gh"

run_list() {
  local log_file="$1"
  shift
  GH_LOG="$WORK/gh.log" \
  ITEM_LIST_LOG="$log_file" \
  PATH="$FAKE_BIN:$PATH" \
  "$@" "$BOARD_SYNC" list >/dev/null
}

TMP_LIST_LOG="$WORK/tmpdir-item-list.log"
run_list "$TMP_LIST_LOG" env TMPDIR="$WORK/tmpdir"
test "$(wc -l <"$TMP_LIST_LOG" | tr -d ' ')" = "1"
test "$(find "$WORK/tmpdir" -type f -name 'board-sync.*' | wc -l | tr -d ' ')" = "0"

EXPLICIT_LIST_LOG="$WORK/explicit-item-list.log"
run_list "$EXPLICIT_LIST_LOG" env TMPDIR="/dev/null" BOARD_SYNC_TMPDIR="$WORK/board-sync-tmpdir"
test "$(wc -l <"$EXPLICIT_LIST_LOG" | tr -d ' ')" = "1"
test "$(find "$WORK/board-sync-tmpdir" -type f -name 'board-sync.*' | wc -l | tr -d ' ')" = "0"

echo "PASS board-sync tempdir fixture harness"
