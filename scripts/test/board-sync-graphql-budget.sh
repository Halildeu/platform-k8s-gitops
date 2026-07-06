#!/usr/bin/env bash
# Offline harness for Project GraphQL budget guard and low-risk verify deferral.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BOARD_SYNC="$REPO_ROOT/scripts/board-sync.sh"
WORK="$(mktemp -d -t board-sync-graphql-budget.XXXXXX)"
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

if [ "${1:-}" = "project" ]; then
  echo "fake gh: Project API must not be called in this harness" >&2
  exit 90
fi

if [ "${1:-}" = "api" ] && [ "${2:-}" = "graphql" ]; then
  echo "fake gh: GraphQL endpoint must not be called when budget is exhausted" >&2
  exit 91
fi

if [ "${1:-}" = "api" ] && [ "${2:-}" = "rate_limit" ]; then
  jq -n \
    --argjson remaining "${FAKE_GRAPHQL_REMAINING:-0}" \
    --argjson reset "${FAKE_GRAPHQL_RESET:-1781347433}" \
    --argjson used "${FAKE_GRAPHQL_USED:-5000}" \
    '{limit:5000,remaining:$remaining,reset:$reset,used:$used}'
  exit 0
fi

if [ "${1:-}" = "api" ]; then
  joined=" $* "
  if printf '%s' "$joined" | grep -q ' repos/Halildeu/platform-k8s-gitops/issues/42 '; then
    if printf '%s' "$joined" | grep -q ' --jq .body'; then
      cat <<'BODY'
## Agent State

<!-- agent-state:v1
status: in-progress
claim_session: test-session
claim_worktree: /tmp/test-worktree
claim_branch: test-branch
claim_updated_at: 2026-06-13T00:00:00Z
expires_at: 2999-01-01T00:00:00Z
-->
BODY
    else
      printf '42\n'
    fi
    exit 0
  fi
  case "$joined" in
    *" repos/Halildeu/platform-k8s-gitops/issues/42/comments?per_page=100 "*)
      printf '[]\n'
      exit 0
      ;;
    *" -X POST repos/Halildeu/platform-k8s-gitops/issues/42/comments "*)
      printf '{"id":123}\n'
      exit 0
      ;;
  esac
fi

if [ "${1:-}" = "issue" ] && [ "${2:-}" = "view" ]; then
  body="$(cat <<'BODY'
## Agent State

<!-- agent-state:v1
status: in-progress
claim_session: test-session
claim_worktree: /tmp/test-worktree
claim_branch: test-branch
claim_updated_at: 2026-06-13T00:00:00Z
expires_at: 2999-01-01T00:00:00Z
-->
BODY
)"
  if printf '%s' " $* " | grep -q ' --jq '; then
    printf '%s\n' "$body"
  else
    jq -n --arg body "$body" '{body:$body}'
  fi
  exit 0
fi

if [ "${1:-}" = "issue" ] && { [ "${2:-}" = "comment" ] || [ "${2:-}" = "edit" ]; }; then
  exit 0
fi

echo "fake gh: unsupported call: $*" >&2
exit 92
FAKE_GH
chmod +x "$FAKE_BIN/gh"

PATH="$FAKE_BIN:$PATH"
export PATH

run_budget_defer() {
  local out
  out="$(GH_LOG="$WORK/defer.log" FAKE_GRAPHQL_REMAINING=0 "$BOARD_SYNC" graphql-budget --operation pr_update --mutation-risk low-risk)"
  printf '%s\n' "$out" | jq -e '
    .decision == "defer"
    and .reason == "graphql_exhausted_low_risk_project_mutation"
    and .graphql.remaining == 0
  ' >/dev/null
  ! grep -q '^project ' "$WORK/defer.log"
}

run_budget_fail_closed() {
  local out rc
  set +e
  out="$(GH_LOG="$WORK/fail.log" FAKE_GRAPHQL_REMAINING=0 "$BOARD_SYNC" graphql-budget --operation deploy --mutation-risk critical)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '
    .decision == "fail"
    and .reason == "graphql_exhausted_critical_operation_fail_closed"
  ' >/dev/null
  ! grep -q '^project ' "$WORK/fail.log"
}

run_budget_release_defer() {
  local out
  out="$(GH_LOG="$WORK/release-budget.log" FAKE_GRAPHQL_REMAINING=0 "$BOARD_SYNC" graphql-budget --operation release --mutation-risk low-risk)"
  printf '%s\n' "$out" | jq -e '
    .decision == "defer"
    and .reason == "graphql_exhausted_release_todo_reconcile"
  ' >/dev/null
  ! grep -q '^project ' "$WORK/release-budget.log"
}

run_budget_backlog_add_fail_closed() {
  local out rc
  set +e
  out="$(GH_LOG="$WORK/backlog-budget.log" FAKE_GRAPHQL_REMAINING=0 "$BOARD_SYNC" graphql-budget --operation backlog-add --mutation-risk low-risk)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '
    .decision == "fail"
    and .reason == "graphql_exhausted_fresh_project_truth_required"
  ' >/dev/null
  ! grep -q '^project ' "$WORK/backlog-budget.log"
}

run_budget_continue() {
  local out
  out="$(GH_LOG="$WORK/continue.log" FAKE_GRAPHQL_REMAINING=100 "$BOARD_SYNC" graphql-budget --operation claim --mutation-risk critical)"
  printf '%s\n' "$out" | jq -e '
    .decision == "continue"
    and .reason == "graphql_budget_available"
    and .graphql.remaining == 100
  ' >/dev/null
}

run_verify_deferred() {
  GH_LOG="$WORK/verify.log" FAKE_GRAPHQL_REMAINING=0 "$BOARD_SYNC" verify 42 \
    --repo Halildeu/platform-k8s-gitops \
    --pr 1502 \
    --pr-repo Halildeu/platform-k8s-gitops

  if grep -q '^project ' "$WORK/verify.log"; then
    echo "Project API was called on exhausted verify path" >&2
    return 1
  fi
  if grep -q '^api graphql' "$WORK/verify.log"; then
    echo "GraphQL endpoint was called on exhausted verify path" >&2
    return 1
  fi
  grep -q 'rate_limit' "$WORK/verify.log"
  grep -q 'repos/Halildeu/platform-k8s-gitops/issues/42/comments' "$WORK/verify.log"
}

run_release_deferred() {
  GH_LOG="$WORK/release.log" FAKE_GRAPHQL_REMAINING=0 BOARD_SESSION_ID=test-session \
    "$BOARD_SYNC" release 42 graphql-exhausted-test

  if grep -q '^project ' "$WORK/release.log"; then
    echo "Project API was called on exhausted release path" >&2
    return 1
  fi
  if grep -q '^api graphql' "$WORK/release.log"; then
    echo "GraphQL endpoint was called on exhausted release path" >&2
    return 1
  fi
  grep -q 'rate_limit' "$WORK/release.log"
  grep -q '^issue comment' "$WORK/release.log"
  grep -q '^issue edit' "$WORK/release.log"
  grep -q 'repos/Halildeu/platform-k8s-gitops/issues/42/comments' "$WORK/release.log"
}

run_require_claim_rest_only_low_risk() {
  local out
  out="$(GH_LOG="$WORK/require-low-risk.log" FAKE_GRAPHQL_REMAINING=0 BOARD_SESSION_ID=test-session \
    "$BOARD_SYNC" require-claim --issue 42 --session test-session --operation file_write \
      --worktree /tmp/test-worktree --branch test-branch)"
  printf '%s\n' "$out" | jq -e '
    .allowed == true
    and .permission_source == "issue_body_rest_project_graphql_exhausted_v1"
    and .project_status == null
    and .project_truth.reason == "project_graphql_exhausted_rest_only_low_risk_operation"
  ' >/dev/null
  if grep -q '^project ' "$WORK/require-low-risk.log"; then
    echo "Project API was called on REST-only require-claim file_write path" >&2
    return 1
  fi
  if grep -q '^api graphql' "$WORK/require-low-risk.log"; then
    echo "GraphQL endpoint was called on REST-only require-claim file_write path" >&2
    return 1
  fi
}

run_require_claim_rest_only_pr_update() {
  local out
  out="$(GH_LOG="$WORK/require-pr-update.log" FAKE_GRAPHQL_REMAINING=0 BOARD_SESSION_ID=test-session \
    "$BOARD_SYNC" require-claim --issue 42 --session test-session --operation pr_update \
      --worktree /tmp/test-worktree --branch test-branch)"
  printf '%s\n' "$out" | jq -e '
    .allowed == true
    and .operation == "pr_update"
    and .permission_source == "issue_body_rest_project_graphql_exhausted_v1"
  ' >/dev/null
  if grep -q '^project ' "$WORK/require-pr-update.log"; then
    echo "Project API was called on REST-only require-claim pr_update path" >&2
    return 1
  fi
  if grep -q '^api graphql' "$WORK/require-pr-update.log"; then
    echo "GraphQL endpoint was called on REST-only require-claim pr_update path" >&2
    return 1
  fi
}

run_require_claim_critical_fail_closed() {
  local out rc
  set +e
  out="$(GH_LOG="$WORK/require-critical.log" FAKE_GRAPHQL_REMAINING=0 BOARD_SESSION_ID=test-session \
    "$BOARD_SYNC" require-claim --issue 42 --session test-session --operation deploy \
      --worktree /tmp/test-worktree --branch test-branch 2>&1)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | grep -q "Project GraphQL budget exhausted — require-claim operation 'deploy' needs fresh Project truth"
  if grep -q '^project ' "$WORK/require-critical.log"; then
    echo "Project API was called before critical require-claim fail-closed" >&2
    return 1
  fi
  if grep -q '^api graphql' "$WORK/require-critical.log"; then
    echo "GraphQL endpoint was called before critical require-claim fail-closed" >&2
    return 1
  fi
}

run_backlog_add_fail_closed_before_issue_create() {
  local out rc
  set +e
  out="$(GH_LOG="$WORK/backlog-add.log" FAKE_GRAPHQL_REMAINING=0 "$BOARD_SYNC" backlog-add "captured follow-up" --note "test note" 2>&1)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | grep -q "Project GraphQL budget exhausted — 'backlog-add' needs fresh Project truth"
  if grep -q '^issue create' "$WORK/backlog-add.log"; then
    echo "backlog-add created an issue while Project GraphQL was exhausted" >&2
    return 1
  fi
  if grep -q '^project ' "$WORK/backlog-add.log"; then
    echo "Project API was called after backlog-add fail-closed decision" >&2
    return 1
  fi
  if grep -q '^api graphql' "$WORK/backlog-add.log"; then
    echo "GraphQL endpoint was called after backlog-add fail-closed decision" >&2
    return 1
  fi
}

printf 'board-sync.sh Project GraphQL budget harness\n'
run_budget_defer
printf '  ok low-risk Project mutation deferred when exhausted\n'
run_budget_fail_closed
printf '  ok critical operation fails closed when exhausted\n'
run_budget_release_defer
printf '  ok release Todo reconcile is low-risk deferred when exhausted\n'
run_budget_backlog_add_fail_closed
printf '  ok backlog-add budget decision fails closed when exhausted\n'
run_budget_continue
printf '  ok Project mutation continues when budget is available\n'
run_verify_deferred
printf '  ok verify records PROJECT-DEFERRED without Project API\n'
run_release_deferred
printf '  ok release records PROJECT-DEFERRED Todo reconcile without Project API\n'
run_require_claim_rest_only_low_risk
printf '  ok require-claim file_write uses REST-only path when GraphQL exhausted\n'
run_require_claim_rest_only_pr_update
printf '  ok require-claim pr_update uses REST-only path when GraphQL exhausted\n'
run_require_claim_critical_fail_closed
printf '  ok require-claim critical operation fails closed when GraphQL exhausted\n'
run_backlog_add_fail_closed_before_issue_create
printf '  ok backlog-add creates no issue when Project GraphQL is exhausted\n'
printf 'PASS board-sync GraphQL budget harness\n'
