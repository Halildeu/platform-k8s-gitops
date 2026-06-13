#!/usr/bin/env bash
# Offline harness for PROJECT-DEFERRED drain and claim blocking.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BOARD_SYNC="$REPO_ROOT/scripts/board-sync.sh"
WORK="$(mktemp -d -t board-sync-project-queue.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

FAKE_BIN="$WORK/bin"
mkdir -p "$FAKE_BIN"

cat >"$FAKE_BIN/gh" <<'FAKE_GH'
#!/usr/bin/env bash
set -euo pipefail

{
  printf '%s\n' "$*"
} >>"${GH_LOG:-/dev/null}"

if [ "${1:-}" = "auth" ] && [ "${2:-}" = "status" ]; then
  exit 0
fi

if [ "${1:-}" = "project" ] && [ "${2:-}" = "view" ]; then
  printf '{"id":"PVT_kwHOCx7tY84BIN2d","number":2}\n'
  exit 0
fi

if [ "${1:-}" = "api" ] && [ "${2:-}" = "rate_limit" ]; then
  printf '{"limit":5000,"remaining":100,"reset":1781347433,"used":4900}\n'
  exit 0
fi

if [ "${1:-}" = "api" ] && [ "${2:-}" = "graphql" ]; then
  joined=" $* "
  if printf '%s' "$joined" | grep -q 'updateProjectV2ItemFieldValue'; then
    printf 'PVTI_test_42\n'
    exit 0
  fi
  status="${FAKE_PROJECT_STATUS:-Todo}"
  jq -n --arg status "$status" '{
    data: {
      repository: {
        issue: {
          number: 42,
          title: "test issue 42",
          url: "https://github.com/Halildeu/platform-k8s-gitops/issues/42",
          projectItems: {
            nodes: [
              {
                id: "PVTI_test_42",
                project: { id: "PVT_kwHOCx7tY84BIN2d" },
                fieldValues: {
                  nodes: [
                    { __typename: "ProjectV2ItemFieldSingleSelectValue", name: $status, optionId: "da11d7ac", field: { name: "Status", id: "PVTSSF_lAHOCx7tY84BIN2dzg4vgLw" } },
                    { __typename: "ProjectV2ItemFieldSingleSelectValue", name: "issue", optionId: "22b29779", field: { name: "Kind", id: "PVTSSF_lAHOCx7tY84BIN2dzhTGxFk" } },
                    { __typename: "ProjectV2ItemFieldSingleSelectValue", name: "Faz 23", optionId: "7ff54758", field: { name: "Faz", id: "PVTSSF_lAHOCx7tY84BIN2dzhTGqF0" } },
                    { __typename: "ProjectV2ItemFieldSingleSelectValue", name: "gitops", optionId: "4b80f631", field: { name: "Track", id: "PVTSSF_lAHOCx7tY84BIN2dzhTGqHY" } },
                    { __typename: "ProjectV2ItemFieldSingleSelectValue", name: "P0", optionId: "951c13f7", field: { name: "Priority", id: "PVTSSF_lAHOCx7tY84BIN2dzhTGqHk" } }
                  ]
                }
              }
            ]
          }
        }
      }
    }
  }'
  exit 0
fi

if [ "${1:-}" = "api" ]; then
  joined=" $* "
  if printf '%s' "$joined" | grep -q 'repos/Halildeu/platform-k8s-gitops/issues/42/comments?per_page=100'; then
    if [ "${FAKE_DEFERRED_DRAINED:-0}" = "1" ]; then
      cat <<'JSON'
[
  {
    "id": 100,
    "created_at": "2026-06-13T00:00:00Z",
    "body": "PROJECT-DEFERRED v1 key=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa mutation=status target=\"Needs Verify\" reason=graphql_exhausted source=verify issue_repo=Halildeu/platform-k8s-gitops issue=42 pr_repo=Halildeu/platform-k8s-gitops pr=1503 at=2026-06-13T00:00:00Z"
  },
  {
    "id": 101,
    "created_at": "2026-06-13T00:01:00Z",
    "body": "PROJECT-DRAINED v1 key=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa result=applied target=\"Needs Verify\" at=2026-06-13T00:01:00Z"
  }
]
JSON
    else
      cat <<'JSON'
[
  {
    "id": 100,
    "created_at": "2026-06-13T00:00:00Z",
    "body": "PROJECT-DEFERRED v1 key=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa mutation=status target=\"Needs Verify\" reason=graphql_exhausted source=verify issue_repo=Halildeu/platform-k8s-gitops issue=42 pr_repo=Halildeu/platform-k8s-gitops pr=1503 at=2026-06-13T00:00:00Z"
  }
]
JSON
    fi
    exit 0
  fi
  if printf '%s' "$joined" | grep -q ' -X POST repos/Halildeu/platform-k8s-gitops/issues/42/comments '; then
    printf '{"id":200}\n'
    exit 0
  fi
fi

if [ "${1:-}" = "issue" ] && [ "${2:-}" = "view" ]; then
  for arg in "$@"; do
    if [ "$arg" = "--jq" ]; then
      cat <<'BODY'
## Agent State

<!-- agent-state:v1
status: in-progress
claim_session: old
claim_worktree: old
claim_branch: old
claim_updated_at: 2026-06-13T00:00:00Z
expires_at: 2999-01-01T00:00:00Z
-->
BODY
      exit 0
    fi
  done
  printf '{"comments":[]}\n'
  exit 0
fi

if [ "${1:-}" = "issue" ] && [ "${2:-}" = "edit" ]; then
  exit 0
fi

if [ "${1:-}" = "issue" ] && [ "${2:-}" = "comment" ]; then
  echo "fake gh: claim path must not post issue comment while pending deferred marker exists" >&2
  exit 99
fi

echo "fake gh: unsupported call: $*" >&2
exit 92
FAKE_GH
chmod +x "$FAKE_BIN/gh"

PATH="$FAKE_BIN:$PATH"
export PATH

run_claim_blocked_by_deferred() {
  local out rc log
  log="$WORK/claim-blocked.log"
  set +e
  out="$(GH_LOG="$log" BOARD_SESSION_ID=test-session "$BOARD_SYNC" claim 42 2>&1)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | grep -q 'pending PROJECT-DEFERRED Needs Verify'
  ! grep -q '^issue comment' "$log"
}

run_drain_applies_marker() {
  local log
  log="$WORK/drain.log"
  GH_LOG="$log" "$BOARD_SYNC" drain-project-queue --issue 42
  grep -q '^api graphql' "$log"
  grep -q 'updateProjectV2ItemFieldValue' "$log"
  grep -q '^issue edit' "$log"
  grep -q 'repos/Halildeu/platform-k8s-gitops/issues/42/comments' "$log"
}

run_drain_idempotent_noop() {
  local log
  log="$WORK/drain-idempotent.log"
  GH_LOG="$log" FAKE_DEFERRED_DRAINED=1 "$BOARD_SYNC" drain-project-queue --issue 42
  if grep -q 'updateProjectV2ItemFieldValue' "$log"; then
    echo "idempotent drain unexpectedly mutated Project status" >&2
    return 1
  fi
  if grep -q '^issue edit' "$log"; then
    echo "idempotent drain unexpectedly edited issue body" >&2
    return 1
  fi
}

printf 'board-sync.sh PROJECT-DEFERRED queue harness\n'
run_claim_blocked_by_deferred
printf '  ok claim blocked by pending Needs Verify deferred marker\n'
run_drain_applies_marker
printf '  ok drain applies Project Status and reconciles body\n'
run_drain_idempotent_noop
printf '  ok already-drained marker is idempotent noop\n'
printf 'PASS board-sync PROJECT-DEFERRED queue harness\n'
