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
  case "$joined" in
    *" repos/Halildeu/platform-k8s-gitops/issues/42 "*) printf '42\n'; exit 0 ;;
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

printf 'board-sync.sh Project GraphQL budget harness\n'
run_budget_defer
printf '  ok low-risk Project mutation deferred when exhausted\n'
run_budget_fail_closed
printf '  ok critical operation fails closed when exhausted\n'
run_budget_continue
printf '  ok Project mutation continues when budget is available\n'
run_verify_deferred
printf '  ok verify records PROJECT-DEFERRED without Project API\n'
printf 'PASS board-sync GraphQL budget harness\n'
