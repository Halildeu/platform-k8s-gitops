#!/usr/bin/env bash
# Offline harness for `scripts/board-sync.sh require-claim`.
#
# The fake gh binary fails any write path. If this test passes, the
# require-claim subcommand stayed read-only for these scenarios.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BOARD_SYNC="$REPO_ROOT/scripts/board-sync.sh"
WORK="$(mktemp -d -t board-sync-require.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

FAKE_BIN="$WORK/bin"
mkdir -p "$FAKE_BIN"

cat >"$FAKE_BIN/gh" <<'FAKE_GH'
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="PVT_kwHOCx7tY84BIN2d"

joined=" $* "

if [ "${1:-}" = "auth" ] && [ "${2:-}" = "status" ]; then
  exit 0
fi

if [ "${1:-}" = "project" ] && [ "${2:-}" = "view" ]; then
  printf '{"id":"%s"}\n' "$PROJECT_ID"
  exit 0
fi

if [ "${1:-}" = "api" ] && [ "${2:-}" = "graphql" ]; then
  if [ -n "${FAKE_GRAPHQL_DELAY_SECONDS:-}" ]; then
    sleep "$FAKE_GRAPHQL_DELAY_SECONDS"
  fi
  jq -n \
    --arg status "${FAKE_STATUS-In Progress}" \
    --arg faz "${FAKE_FAZ-Faz 23}" \
    --arg track "${FAKE_TRACK-gitops}" \
    --arg priority "${FAKE_PRIORITY-P0}" \
    --arg kind "${FAKE_KIND-issue}" \
    '{
      data: {
        repository: {
          issue: {
            number: 1498,
            title: "Coordination Ledger v1 fake item",
            url: "https://github.com/Halildeu/platform-k8s-gitops/issues/1498",
            projectItems: {
              nodes: [
                {
                  id: "PVTI_fake1498",
                  project: { id: "PVT_kwHOCx7tY84BIN2d" },
                  fieldValues: {
                    nodes: [
                      { __typename: "ProjectV2ItemFieldSingleSelectValue", name: $status, optionId: "6e2ec368", field: { name: "Status", id: "PVTSSF_lAHOCx7tY84BIN2dzg4vgLw" } },
                      { __typename: "ProjectV2ItemFieldSingleSelectValue", name: $faz, optionId: "7ff54758", field: { name: "Faz", id: "PVTSSF_lAHOCx7tY84BIN2dzhTGqF0" } },
                      { __typename: "ProjectV2ItemFieldSingleSelectValue", name: $track, optionId: "4b80f631", field: { name: "Track", id: "PVTSSF_lAHOCx7tY84BIN2dzhTGqHY" } },
                      { __typename: "ProjectV2ItemFieldSingleSelectValue", name: $priority, optionId: "951c13f7", field: { name: "Priority", id: "PVTSSF_lAHOCx7tY84BIN2dzhTGqHk" } },
                      { __typename: "ProjectV2ItemFieldSingleSelectValue", name: $kind, optionId: "22b29779", field: { name: "Kind", id: "PVTSSF_lAHOCx7tY84BIN2dzhTGxFk" } }
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

if [ "${1:-}" = "issue" ] && [ "${2:-}" = "view" ]; then
  body="$(cat <<BODY
## Agent State

<!-- agent-state:v1
status: ${FAKE_BODY_STATUS:-in-progress}
claim_session: ${FAKE_SESSION:-session-ok}
claim_worktree: ${FAKE_WORKTREE:-/tmp/worktree-ok}
claim_branch: ${FAKE_BRANCH:-branch-ok}
claim_updated_at: 2026-06-13T00:00:00Z
expires_at: ${FAKE_EXPIRES:-2999-01-01T00:00:00Z}
-->
BODY
)"
  if printf '%s' "$joined" | grep -q -- ' --jq '; then
    printf '%s\n' "$body"
  else
    jq -n --arg body "$body" '{body:$body}'
  fi
  exit 0
fi

if [ "${1:-}" = "api" ] && [ "${2:-}" = "user" ]; then
  printf 'fake-user\n'
  exit 0
fi

if [ "${1:-}" = "issue" ] && { [ "${2:-}" = "comment" ] || [ "${2:-}" = "edit" ]; }; then
  echo "unexpected gh write: $*" >&2
  exit 70
fi

if [ "${1:-}" = "project" ] && [ "${2:-}" = "item-edit" ]; then
  echo "unexpected project write: $*" >&2
  exit 70
fi

echo "fake gh: unsupported call: $*" >&2
exit 71
FAKE_GH
chmod +x "$FAKE_BIN/gh"

PATH="$FAKE_BIN:$PATH"

run_allowed() {
  local out
  out="$("$BOARD_SYNC" require-claim \
    --issue 1498 \
    --session session-ok \
    --operation file_write \
    --worktree /tmp/worktree-ok \
    --branch branch-ok)"
  printf '%s\n' "$out" | jq -e '
    .allowed == true
    and .issue == "Halildeu/platform-k8s-gitops#1498"
    and .operation == "file_write"
    and .permission_source == "project_issue_mirror_v1"
    and .project_truth.fresh == true
    and .project_truth.ttl_seconds == 300
    and (.project_truth.age_seconds | type == "number")
    and .deny_code == null
  ' >/dev/null
}

run_critical_fresh_allowed() {
  local out
  out="$("$BOARD_SYNC" require-claim \
    --issue 1498 \
    --session session-ok \
    --operation deploy \
    --worktree /tmp/worktree-ok \
    --branch branch-ok)"
  printf '%s\n' "$out" | jq -e '
    .allowed == true
    and .operation == "deploy"
    and .project_truth.fresh == true
    and .project_truth.age_seconds <= .project_truth.ttl_seconds
  ' >/dev/null
}

run_critical_stale_denied() {
  local out rc
  set +e
  out="$(PROJECT_TRUTH_TTL_SECONDS=0 FAKE_GRAPHQL_DELAY_SECONDS=1 "$BOARD_SYNC" require-claim \
    --issue 1498 \
    --session session-ok \
    --operation deploy \
    --worktree /tmp/worktree-ok \
    --branch branch-ok)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '
    .allowed == false
    and .operation == "deploy"
    and .deny_code == "project_truth_stale"
    and .project_truth.fresh == false
    and .project_truth.reason == "stale_project_truth"
    and .project_truth.ttl_seconds == 0
    and .project_truth.age_seconds >= 1
    and (.details[] | select(.code == "project_truth_stale"))
  ' >/dev/null
}

run_missing_project_field_denied() {
  local out rc
  set +e
  out="$(FAKE_PRIORITY="" "$BOARD_SYNC" require-claim \
    --issue 1498 \
    --session session-ok \
    --operation commit \
    --worktree /tmp/worktree-ok \
    --branch branch-ok)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '
    .allowed == false
    and .deny_code == "project_field_missing"
    and (.deny_event_intent_id | type == "string")
    and (.details[] | select(.code == "project_field_missing"))
  ' >/dev/null
}

run_todo_status_denied() {
  local out rc
  set +e
  out="$(FAKE_STATUS="Todo" "$BOARD_SYNC" require-claim \
    --issue 1498 \
    --session session-ok \
    --operation push \
    --worktree /tmp/worktree-ok \
    --branch branch-ok)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '
    .allowed == false
    and .deny_code == "project_status_not_in_progress"
    and (.details[] | select(.code == "project_status_not_in_progress"))
  ' >/dev/null
}

run_invalid_operation_setup_error() {
  local out rc
  set +e
  out="$("$BOARD_SYNC" require-claim \
    --issue 1498 \
    --session session-ok \
    --operation unknown \
    --worktree /tmp/worktree-ok \
    --branch branch-ok 2>&1)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | grep -q "unknown --operation"
}

printf 'board-sync.sh require-claim harness\n'
run_allowed
printf '  ok allowed mirror verification\n'
run_critical_fresh_allowed
printf '  ok critical operation allowed with fresh Project truth\n'
run_critical_stale_denied
printf '  ok critical operation denied when Project truth exceeds TTL\n'
run_missing_project_field_denied
printf '  ok missing Project field denied\n'
run_todo_status_denied
printf '  ok non-In-Progress status denied\n'
run_invalid_operation_setup_error
printf '  ok invalid operation rejected\n'
printf 'PASS board-sync require-claim harness\n'
