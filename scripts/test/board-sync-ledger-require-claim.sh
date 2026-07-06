#!/usr/bin/env bash
# Offline harness for ledger-backed `scripts/board-sync.sh require-claim`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BOARD_SYNC="$REPO_ROOT/scripts/board-sync.sh"
WRITER="$REPO_ROOT/scripts/coordination/append-ledger-event.py"
WORK="$(mktemp -d -t board-sync-ledger-require.XXXXXX)"
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

if [ "${1:-}" = "project" ]; then
  echo "unexpected project write/list: $*" >&2
  exit 70
fi

if [ "${1:-}" = "api" ] && [ "${2:-}" = "rate_limit" ]; then
  jq -n \
    --argjson remaining "${FAKE_GRAPHQL_REMAINING:-100}" \
    '{limit:5000,remaining:$remaining,reset:1781347433,used:(5000 - $remaining)}'
  exit 0
fi

if [ "${1:-}" = "api" ] && [ "${2:-}" = "graphql" ]; then
  jq -n \
    --arg status "In Progress" \
    --arg faz "Faz 22" \
    --arg track "gitops" \
    --arg priority "P0" \
    --arg kind "issue" \
    '{
      data: {
        repository: {
          issue: {
            number: 1498,
            title: "Coordination Ledger fake item",
            url: "https://github.com/Halildeu/platform-k8s-gitops/issues/1498",
            projectItems: {
              nodes: [
                {
                  id: "PVTI_fake1498",
                  project: { id: "PVT_kwHOCx7tY84BIN2d" },
                  fieldValues: {
                    nodes: [
                      { __typename: "ProjectV2ItemFieldSingleSelectValue", name: $status, optionId: "6e2ec368", field: { name: "Status", id: "PVTSSF_lAHOCx7tY84BIN2dzg4vgLw" } },
                      { __typename: "ProjectV2ItemFieldSingleSelectValue", name: $faz, optionId: "6fb80ca3", field: { name: "Faz", id: "PVTSSF_lAHOCx7tY84BIN2dzhTGqF0" } },
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

if [ "${1:-}" = "api" ]; then
  if printf '%s' "$joined" | grep -q ' repos/Halildeu/platform-k8s-gitops/issues/1498 '; then
    if printf '%s' "$joined" | grep -q ' --jq .body'; then
      cat <<'BODY'
## Agent State

<!-- agent-state:v1
status: in-progress
claim_session: session-ok
claim_worktree: /tmp/worktree-ok
claim_branch: branch-ok
claim_updated_at: 2026-06-13T00:00:00Z
expires_at: 2999-01-01T00:00:00Z
-->
BODY
    else
      printf '1498\n'
    fi
    exit 0
  fi
  if [ "${2:-}" = "user" ]; then
    printf 'fake-user\n'
    exit 0
  fi
fi

if [ "${1:-}" = "issue" ] && [ "${2:-}" = "view" ]; then
  body="$(cat <<'BODY'
## Agent State

<!-- agent-state:v1
status: in-progress
claim_session: session-ok
claim_worktree: /tmp/worktree-ok
claim_branch: branch-ok
claim_updated_at: 2026-06-13T00:00:00Z
expires_at: 2999-01-01T00:00:00Z
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

if [ "${1:-}" = "issue" ] && { [ "${2:-}" = "comment" ] || [ "${2:-}" = "edit" ]; }; then
  echo "unexpected gh write: $*" >&2
  exit 70
fi

echo "fake gh: unsupported call: $*" >&2
exit 71
FAKE_GH
chmod +x "$FAKE_BIN/gh"

PATH="$FAKE_BIN:$PATH"
export PATH

append_event() {
  local ledger="$1"
  shift
  python3 "$WRITER" --ledger "$ledger" "$@" >/dev/null
}

make_active_ledger() {
  local ledger="$1" session="${2:-session-ok}"
  append_event "$ledger" \
    --expect-previous-hash GENESIS \
    --event-uuid 00000000-0000-4000-8000-000000000701 \
    --event-type CLAIM_ACCEPTED \
    --writer-role coordinator \
    --committed-at 2026-06-13T10:00:00Z \
    --payload-json "{\"repository\":\"Halildeu/platform-k8s-gitops\",\"issue\":1498,\"session\":\"$session\",\"claim_expires_at\":\"2999-01-01T00:00:00Z\",\"heartbeat_interval_minutes\":999999,\"heartbeat_grace_minutes\":45}"
}

prefix_hash() {
  local ledger="$1"
  python3 "$REPO_ROOT/scripts/coordination/verify-ledger-replay.py" --json "$ledger" | python3 -c '
import json
import sys

data = json.load(sys.stdin)[0]
assert data["valid"] is True
print(data["valid_prefix_hash"])
'
}

run_ledger_allowed() {
  local ledger="$WORK/active.jsonl" out
  make_active_ledger "$ledger"
  out="$(COORDINATION_LEDGER_PATH="$ledger" "$BOARD_SYNC" require-claim \
    --issue 1498 \
    --session session-ok \
    --operation commit \
    --worktree /tmp/worktree-ok \
    --branch branch-ok)"
  printf '%s\n' "$out" | jq -e '
    .allowed == true
    and .permission_source == "project_issue_ledger_mirror_v1"
    and .ledger.allowed == true
    and .ledger.permission_state == "active_winner"
    and .ledger.active_session == "session-ok"
  ' >/dev/null
}

run_ledger_session_mismatch_denied() {
  local ledger="$WORK/mismatch.jsonl" out rc
  make_active_ledger "$ledger" "other-session"
  set +e
  out="$(COORDINATION_LEDGER_PATH="$ledger" "$BOARD_SYNC" require-claim \
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
    and .deny_code == "ledger_session_mismatch"
    and .ledger.allowed == false
    and .ledger.deny_code == "ledger_session_mismatch"
    and (.details[] | select(.code == "ledger_session_mismatch"))
  ' >/dev/null
}

run_ledger_revoked_denied() {
  local ledger="$WORK/revoked.jsonl" prefix out rc
  make_active_ledger "$ledger"
  prefix="$(prefix_hash "$ledger")"
  append_event "$ledger" \
    --expect-previous-hash "sha256:$prefix" \
    --event-uuid 00000000-0000-4000-8000-000000000702 \
    --event-type CLAIM_EXPIRED \
    --writer-role reaper \
    --committed-at 2026-06-13T10:05:00Z \
    --payload-json '{"repository":"Halildeu/platform-k8s-gitops","issue":1498,"session":"session-ok"}'
  set +e
  out="$(COORDINATION_LEDGER_PATH="$ledger" "$BOARD_SYNC" require-claim \
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
    and .deny_code == "ledger_claim_revoked"
    and .ledger.permission_state == "claim_expired"
  ' >/dev/null
}

run_invalid_suffix_denied() {
  local ledger="$WORK/invalid.jsonl" out rc
  make_active_ledger "$ledger"
  printf '{not-json}\n' >>"$ledger"
  set +e
  out="$(COORDINATION_LEDGER_PATH="$ledger" "$BOARD_SYNC" require-claim \
    --issue 1498 \
    --session session-ok \
    --operation file_write \
    --worktree /tmp/worktree-ok \
    --branch branch-ok)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '
    .allowed == false
    and .deny_code == "invalid_ledger_suffix"
    and .ledger.valid == false
    and .ledger.deny_code == "invalid_ledger_suffix"
  ' >/dev/null
}

run_invalid_suffix_rest_only_denied() {
  local ledger="$WORK/rest-invalid.jsonl" out rc
  make_active_ledger "$ledger"
  printf '{not-json}\n' >>"$ledger"
  set +e
  out="$(FAKE_GRAPHQL_REMAINING=0 COORDINATION_LEDGER_PATH="$ledger" "$BOARD_SYNC" require-claim \
    --issue 1498 \
    --session session-ok \
    --operation file_write \
    --worktree /tmp/worktree-ok \
    --branch branch-ok)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '
    .allowed == false
    and .permission_source == "issue_body_rest_project_graphql_exhausted_ledger_v1"
    and .deny_code == "invalid_ledger_suffix"
    and .project_status == null
    and .ledger.valid == false
  ' >/dev/null
}

run_takeover_pending_denied() {
  local ledger="$WORK/takeover-pending.jsonl" prefix out rc
  make_active_ledger "$ledger"
  prefix="$(prefix_hash "$ledger")"
  append_event "$ledger" \
    --expect-previous-hash "sha256:$prefix" \
    --event-uuid 00000000-0000-4000-8000-000000000703 \
    --event-type TAKEOVER_ACCEPTED \
    --writer-role coordinator \
    --committed-at 2026-06-13T10:01:00Z \
    --payload-json '{"repository":"Halildeu/platform-k8s-gitops","issue":1498,"old_session":"session-ok","new_session":"other-session"}'
  set +e
  out="$(COORDINATION_LEDGER_PATH="$ledger" "$BOARD_SYNC" require-claim \
    --issue 1498 \
    --session session-ok \
    --operation pr_update \
    --worktree /tmp/worktree-ok \
    --branch branch-ok)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '
    .allowed == false
    and .deny_code == "ledger_takeover_pending"
    and .ledger.permission_state == "takeover_pending_mirror"
  ' >/dev/null
}

run_takeover_committed_allows_new_session() {
  local ledger="$WORK/takeover-committed.jsonl" prefix out
  make_active_ledger "$ledger" "old-session"
  prefix="$(prefix_hash "$ledger")"
  append_event "$ledger" \
    --expect-previous-hash "sha256:$prefix" \
    --event-uuid 00000000-0000-4000-8000-000000000704 \
    --event-type TAKEOVER_ACCEPTED \
    --writer-role coordinator \
    --committed-at 2026-06-13T10:01:00Z \
    --payload-json '{"repository":"Halildeu/platform-k8s-gitops","issue":1498,"old_session":"old-session","new_session":"session-ok"}'
  prefix="$(prefix_hash "$ledger")"
  append_event "$ledger" \
    --expect-previous-hash "sha256:$prefix" \
    --event-uuid 00000000-0000-4000-8000-000000000705 \
    --event-type TAKEOVER_COMMITTED \
    --writer-role coordinator \
    --committed-at 2026-06-13T10:02:00Z \
    --payload-json '{"repository":"Halildeu/platform-k8s-gitops","issue":1498,"old_session":"old-session","new_session":"session-ok","claim_expires_at":"2999-01-01T00:00:00Z","heartbeat_interval_minutes":999999,"heartbeat_grace_minutes":45}'
  out="$(COORDINATION_LEDGER_PATH="$ledger" "$BOARD_SYNC" require-claim \
    --issue 1498 \
    --session session-ok \
    --operation commit \
    --worktree /tmp/worktree-ok \
    --branch branch-ok)"
  printf '%s\n' "$out" | jq -e '
    .allowed == true
    and .ledger.permission_state == "active_winner"
    and .ledger.active_session == "session-ok"
  ' >/dev/null
}

run_tombstone_denied() {
  local ledger="$WORK/tombstone.jsonl" prefix out rc
  make_active_ledger "$ledger"
  prefix="$(prefix_hash "$ledger")"
  append_event "$ledger" \
    --expect-previous-hash "sha256:$prefix" \
    --event-uuid 00000000-0000-4000-8000-000000000706 \
    --event-type TOMBSTONE_CHAIN \
    --writer-role coordinator \
    --committed-at 2026-06-13T10:03:00Z \
    --payload-json '{"repository":"Halildeu/platform-k8s-gitops","issue":1498,"reason":"test tombstone"}'
  set +e
  out="$(COORDINATION_LEDGER_PATH="$ledger" "$BOARD_SYNC" require-claim \
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
    and .deny_code == "ledger_issue_superseded"
    and .ledger.permission_state == "tombstone_chain"
  ' >/dev/null
}

run_heartbeat_stale_denied() {
  local ledger="$WORK/stale.jsonl" out rc
  append_event "$ledger" \
    --expect-previous-hash GENESIS \
    --event-uuid 00000000-0000-4000-8000-000000000707 \
    --event-type CLAIM_ACCEPTED \
    --writer-role coordinator \
    --committed-at 2026-06-13T10:00:00Z \
    --payload-json '{"repository":"Halildeu/platform-k8s-gitops","issue":1498,"session":"session-ok","claim_expires_at":"2999-01-01T00:00:00Z","heartbeat_interval_minutes":1,"heartbeat_grace_minutes":1}'
  set +e
  out="$(COORDINATION_LEDGER_PATH="$ledger" "$BOARD_SYNC" require-claim \
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
    and .deny_code == "ledger_claim_stale"
    and .ledger.deny_code == "ledger_claim_stale"
  ' >/dev/null
}

printf 'board-sync.sh ledger-backed require-claim harness\n'
run_ledger_allowed
printf '  ok valid ledger active winner participates in allow decision\n'
run_ledger_session_mismatch_denied
printf '  ok ledger session mismatch denies despite valid mirrors\n'
run_ledger_revoked_denied
printf '  ok ledger revoke event denies despite valid mirrors\n'
run_invalid_suffix_denied
printf '  ok invalid ledger suffix denies normal path\n'
run_invalid_suffix_rest_only_denied
printf '  ok invalid ledger suffix denies GraphQL-exhausted REST-only path\n'
run_takeover_pending_denied
printf '  ok takeover pending denies old active session until commit\n'
run_takeover_committed_allows_new_session
printf '  ok takeover committed allows new active session\n'
run_tombstone_denied
printf '  ok tombstone denies superseded issue chain\n'
run_heartbeat_stale_denied
printf '  ok stale heartbeat denies otherwise valid claim\n'
printf 'PASS board-sync ledger-backed require-claim harness\n'
