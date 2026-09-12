#!/usr/bin/env bash
# Hermetic verify -> acceptance re-claim regression; no GitHub calls.
set -euo pipefail
SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/board-sync.sh"
# Load the repository functions without dispatching the CLI entry point.
eval "$(sed '$d' "$SCRIPT")"
WORK="$(mktemp -d -t board-verify-release.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

iso_now() { printf '2026-09-12T12:10:00Z'; }
project_graphql_is_exhausted() { return 1; }
pending_needs_verify_deferred_count() { printf 0; }
resolve_issue_optional() {
  REPO=Halildeu/platform-k8s-gitops NUM=42 ITEM_ID=test-item ITEM_KIND=issue
  ITEM_STATUS="$(cat "$WORK/status")"
}
resolve_issue() { resolve_issue_optional "$@"; }
issue_body() { cat "$WORK/body"; }
write_body() { cat > "$WORK/body"; }
set_board_status() { printf '%s' "$3" > "$WORK/status"; }
post_comment() {
  if [[ "$3" == HANDOFF* ]]; then
    if [ "$MODE" = fail-release ]; then return 1; fi
    if [ "$MODE" = lost-release ]; then return 0; fi
  fi
  jq --arg body "$3" '.comments += [{id:"new",createdAt:"2026-09-12T12:10:00Z",body:$body}]' \
    "$WORK/comments" > "$WORK/next"
  mv "$WORK/next" "$WORK/comments"
  if [[ "$3" == HANDOFF* ]] && [ "$MODE" = raced-owner ]; then
    sed 's/claim_session: owner/claim_session: other/' "$WORK/body" > "$WORK/next"
    mv "$WORK/next" "$WORK/body"
  fi
}
gh() {
  if [ "$1 $2" = 'issue view' ] && [[ " $* " == *' comments '* ]]; then
    cat "$WORK/comments"
  else
    printf 'Unexpected gh call: %s\n' "$*" >&2
    return 99
  fi
}

setup() {
  MODE="$1"
  BOARD_SESSION_ID=owner
  OPT_SESSION="" OPT_PR=99 OPT_PR_REPO=Halildeu/platform-k8s-gitops
  printf 'In Progress' > "$WORK/status"
  printf '%s\n' '<!-- agent-state:v1' 'status: in-progress' 'claim_session: owner' \
    'claim_worktree: /test' 'claim_branch: test' \
    'claim_updated_at: 2026-09-12T12:00:00Z' 'expires_at: 2026-09-12T14:00:00Z' '-->' > "$WORK/body"
  jq -n '{comments:[{id:"old",createdAt:"2026-09-12T12:00:00Z",body:"CLAIM session=owner at=2026-09-12T12:00:00Z expires=2026-09-12T14:00:00Z"}]}' > "$WORK/comments"
}
assert_state() {
  [ "$(cat "$WORK/status")" = "$1" ]
  [ "$(state_get claim_session < "$WORK/body")" = "$2" ]
}

setup owned
cmd_verify 42
assert_state 'Needs Verify' none
[ "$(winner_of '2026-09-12T12:11:00Z' < "$WORK/comments")" = NONE ]
# An acceptance pass deliberately returns the item to Todo before claiming.
printf Todo > "$WORK/status"
BOARD_SESSION_ID=next-owner
cmd_claim 42
assert_state 'In Progress' next-owner
printf 'PASS owned verify releases historical lease and next claim wins\n'

for mode in foreign absent; do
  setup "$mode"
  if [ "$mode" = foreign ]; then BOARD_SESSION_ID=other; else unset BOARD_SESSION_ID; fi
  cmd_verify 42
  assert_state 'In Progress' owner
  [ "$(winner_of '2026-09-12T12:11:00Z' < "$WORK/comments")" = owner ]
  printf 'PASS %s session cannot release another claim\n' "$mode"
done

for mode in fail-release lost-release raced-owner; do
  setup "$mode"
  (cmd_verify 42) && { printf 'FAIL accepted %s\n' "$mode"; exit 1; }
  [ "$(cat "$WORK/status")" = 'In Progress' ]
  [ "$(state_get claim_session < "$WORK/body")" != none ]
  printf 'PASS %s does not clear body or move board\n' "$mode"
done

setup unclaimed
sed 's/claim_session: owner/claim_session: none/' "$WORK/body" > "$WORK/next"
mv "$WORK/next" "$WORK/body"
printf '{"comments":[]}' > "$WORK/comments"
unset BOARD_SESSION_ID
cmd_verify 42
assert_state 'Needs Verify' none
[ "$(jq '[.comments[]|select(.body|startswith("HANDOFF "))]|length' "$WORK/comments")" = 0 ]
cmd_verify 42
[ "$(jq '.comments|length' "$WORK/comments")" = 1 ]
printf 'PASS unclaimed verify and repeated evidence are idempotent\n'
