#!/usr/bin/env bash
# scripts/test/board-sync-project-item-limit.sh
#
# Regression harness for platform Roadmap boards whose item count exceeds the
# old hard-coded `gh project item-list --limit 200` ceiling (#1531).
#
# The fake board has 226 items. Issue #1531 is deliberately item #226, so a
# regression back to 200 silently hides it. The targeted sync-state path must
# also resolve bare issue numbers without a full board item-list scan.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BOARD_SYNC="$REPO_ROOT/scripts/board-sync.sh"
WORK="$(mktemp -d -t board-sync-item-limit.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/bin"
FAKE_GH="$WORK/bin/gh"
cat >"$FAKE_GH" <<'FAKE_GH_EOF'
#!/usr/bin/env bash
set -euo pipefail

{
  printf '%s' "$*"
  printf '\n'
} >>"${GH_LOG:-/dev/null}"

if [ "${1:-}" = "auth" ] && [ "${2:-}" = "status" ]; then
  exit 0
fi

if [ "${1:-}" = "api" ] && [ "${2:-}" = "rate_limit" ]; then
  printf '{"remaining":4999,"limit":5000,"used":1,"reset":1893456000}\n'
  exit 0
fi

if [ "${1:-}" = "project" ] && [ "${2:-}" = "view" ]; then
  printf '{"id":"PVT_kwHOCx7tY84BIN2d","number":2}\n'
  exit 0
fi

if [ "${1:-}" = "project" ] && [ "${2:-}" = "item-list" ]; then
  limit=30
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --limit|-L)
        limit="$2"
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done

  jq -n --argjson limit "$limit" '
    def visible_count: ([226, $limit] | min);
    {
      totalCount: 226,
      items: [
        range(1; visible_count + 1) as $i
        | if $i == 226 then
            {
              id: "PVTI_1531",
              title: "board-sync.sh limit regression sentinel",
              status: "Backlog",
              kind: "issue",
              content: {
                type: "Issue",
                number: 1531,
                url: "https://github.com/Halildeu/platform-k8s-gitops/issues/1531"
              }
            }
          else
            {
              id: ("PVTI_draft_" + ($i | tostring)),
              title: ("draft " + ($i | tostring)),
              status: "Todo",
              kind: "umbrella",
              content: {
                type: "DraftIssue",
                title: ("draft " + ($i | tostring))
              }
            }
          end
      ]
    }'
  exit 0
fi

if [ "${1:-}" = "api" ] && [ "${2:-}" = "graphql" ]; then
  cat <<'GRAPHQL_EOF'
{
  "data": {
    "repository": {
      "issue": {
        "number": 1531,
        "title": "board-sync.sh limit regression sentinel",
        "url": "https://github.com/Halildeu/platform-k8s-gitops/issues/1531",
        "projectItems": {
          "nodes": [
            {
              "id": "PVTI_1531",
              "project": {"id": "PVT_kwHOCx7tY84BIN2d"},
              "fieldValues": {
                "nodes": [
                  {
                    "__typename": "ProjectV2ItemFieldSingleSelectValue",
                    "name": "Backlog",
                    "optionId": "81ee9923",
                    "field": {"id": "PVTSSF_lAHOCx7tY84BIN2dzg4vgLw", "name": "Status"}
                  },
                  {
                    "__typename": "ProjectV2ItemFieldSingleSelectValue",
                    "name": "issue",
                    "optionId": "22b29779",
                    "field": {"id": "PVTSSF_lAHOCx7tY84BIN2dzhTGxFk", "name": "Kind"}
                  }
                ]
              }
            }
          ]
        }
      }
    }
  }
}
GRAPHQL_EOF
  exit 0
fi

if [ "${1:-}" = "issue" ] && [ "${2:-}" = "view" ]; then
  for arg in "$@"; do
    if [ "$arg" = "--jq" ]; then
      cat <<'BODY_EOF'
## Agent State

<!-- agent-state:v1
status: backlog
claim_session: none
claim_worktree: none
claim_branch: none
claim_updated_at: none
expires_at: none
-->
BODY_EOF
      exit 0
    fi
  done
  printf '{"body":"agent-state:v1"}\n'
  exit 0
fi

echo "fake gh: unexpected invocation: $*" >&2
exit 99
FAKE_GH_EOF
chmod +x "$FAKE_GH"

PATH="$WORK/bin:$PATH"
export PATH

pass=0
fail=0

assert_contains() {
  local file="$1" pattern="$2" label="$3"
  if grep -q "$pattern" "$file"; then
    pass=$((pass + 1))
    printf '  ✓ %s\n' "$label"
  else
    fail=$((fail + 1))
    printf '  ✗ %s\n' "$label"
    printf '    missing pattern: %s\n' "$pattern"
    printf '    output: %s\n' "$(tr '\n' '|' <"$file" | head -c 240)"
  fi
}

assert_not_contains() {
  local file="$1" pattern="$2" label="$3"
  if grep -q "$pattern" "$file"; then
    fail=$((fail + 1))
    printf '  ✗ %s\n' "$label"
    printf '    forbidden pattern: %s\n' "$pattern"
    printf '    log: %s\n' "$(tr '\n' '|' <"$file" | head -c 240)"
  else
    pass=$((pass + 1))
    printf '  ✓ %s\n' "$label"
  fi
}

printf 'board-sync.sh Project item limit regression harness (#1531)\n'
printf -- '----------------------------------------------------------\n'

LIST_LOG="$WORK/list-gh.log"
LIST_OUT="$WORK/list.out"
GH_LOG="$LIST_LOG" PROJECT_ITEM_LIMIT=226 bash "$BOARD_SYNC" list >"$LIST_OUT" 2>&1
assert_contains "$LIST_OUT" "Backlog (1" "list sees the 226th backlog issue when PROJECT_ITEM_LIMIT covers totalCount"
assert_contains "$LIST_LOG" "project item-list 2 --owner Halildeu --format json --limit 226" "list passes PROJECT_ITEM_LIMIT through to gh project item-list"

SYNC_LOG="$WORK/sync-gh.log"
SYNC_OUT="$WORK/sync.out"
GH_LOG="$SYNC_LOG" bash "$BOARD_SYNC" sync-state 1531 >"$SYNC_OUT" 2>&1
assert_contains "$SYNC_OUT" "board Status      : Backlog" "sync-state resolves bare #1531 via targeted Project lookup"
assert_not_contains "$SYNC_LOG" "project item-list" "sync-state does not depend on full board item-list"
assert_contains "$SYNC_LOG" "api graphql" "sync-state uses targeted GraphQL lookup"

if PROJECT_ITEM_LIMIT=199 bash "$BOARD_SYNC" list >"$WORK/bad-limit.out" 2>&1; then
  fail=$((fail + 1))
  printf '  ✗ PROJECT_ITEM_LIMIT<200 should fail preflight\n'
else
  pass=$((pass + 1))
  printf '  ✓ PROJECT_ITEM_LIMIT<200 fails closed\n'
fi

printf '\nResult: pass=%d fail=%d\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
