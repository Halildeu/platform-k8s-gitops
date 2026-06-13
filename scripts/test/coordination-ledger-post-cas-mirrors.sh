#!/usr/bin/env bash
# Offline harness for post-CAS Coordination Ledger mirror writes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HELPER="$REPO_ROOT/scripts/coordination/apply-ledger-mirrors.py"
WORK="$(mktemp -d -t coordination-post-cas-mirrors.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

EVENT_UUID="00000000-0000-4000-8000-000000001524"
EVENT_HASH="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
PREFIX_HASH="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

cat >"$WORK/cas.json" <<JSON
{
  "status": "ledger_event_emitted_after_remote_cas",
  "branch_append": {
    "append": {
      "event_uuid": "$EVENT_UUID",
      "event_hash": "$EVENT_HASH",
      "valid_prefix_hash": "$PREFIX_HASH"
    }
  }
}
JSON

cat >"$WORK/issue-body-ok.txt" <<'BODY'
## Agent State

<!-- agent-state:v1
status: in-progress
claim_session: session-ok
claim_worktree: /tmp/worktree-ok
claim_branch: branch-ok
claim_updated_at: 2026-06-13T10:00:00Z
expires_at: 2999-01-01T00:00:00Z
-->
BODY

cat >"$WORK/pr-body-empty.txt" <<'BODY'
PR body before mirror.
BODY

write_plan() {
  local path="$1" project_status="${2:-Todo}" expected_hash="${3:-$EVENT_HASH}" pr_expected="${4:-}"
  cat >"$path" <<JSON
{
  "schemaVersion": "coordination-mirror-write-plan/v1",
  "repository": "Halildeu/platform-k8s-gitops",
  "issue": 1524,
  "expected_event_uuid": "$EVENT_UUID",
  "expected_event_hash": "$expected_hash",
  "issue_body": {
    "enabled": true,
    "expected": {
      "status": "in-progress",
      "claim_session": "session-ok"
    },
    "set": {
      "status": "needs-verify",
      "claim_session": "none",
      "claim_worktree": "none",
      "claim_branch": "none",
      "claim_updated_at": "none",
      "expires_at": "none"
    }
  },
  "project": {
    "enabled": true,
    "item_id": "PVTI_fake1524",
    "current_fields": {
      "Status": "$project_status"
    },
    "set_fields": {
      "Status": "Needs Verify",
      "Faz": "Faz 22",
      "Track": "gitops",
      "Priority": "P0",
      "Kind": "issue"
    }
  },
  "pr_body": {
    "enabled": true,
    "number": 1525,
    "expected": {$pr_expected},
    "set": {
      "coordination_state": "needs-verify",
      "event_uuid": "$EVENT_UUID",
      "event_hash": "$EVENT_HASH",
      "session": "none"
    }
  }
}
JSON
}

write_fake_gh() {
  local fake="$WORK/gh"
  cat >"$fake" <<'FAKE_GH'
#!/usr/bin/env bash
set -euo pipefail

log="${FAKE_GH_LOG:?}"

if [ "${1:-}" = "issue" ] && [ "${2:-}" = "view" ]; then
  cat "${FAKE_ISSUE_BODY:?}"
  exit 0
fi

if [ "${1:-}" = "pr" ] && [ "${2:-}" = "view" ]; then
  cat "${FAKE_PR_BODY:?}"
  exit 0
fi

body_file=""
for ((i=1; i <= $#; i++)); do
  if [ "${!i}" = "--body-file" ]; then
    j=$((i + 1))
    body_file="${!j}"
  fi
done

if [ "${1:-}" = "issue" ] && [ "${2:-}" = "edit" ]; then
  {
    printf 'ISSUE_EDIT %s\n' "$*"
    sed 's/^/ISSUE_BODY:/' "$body_file"
  } >>"$log"
  exit 0
fi

if [ "${1:-}" = "pr" ] && [ "${2:-}" = "edit" ]; then
  {
    printf 'PR_EDIT %s\n' "$*"
    sed 's/^/PR_BODY:/' "$body_file"
  } >>"$log"
  exit 0
fi

if [ "${1:-}" = "project" ] && [ "${2:-}" = "item-edit" ]; then
  if [ "${FAKE_FAIL_PROJECT:-0}" = "1" ]; then
    echo "fake project failure" >&2
    exit 42
  fi
  printf 'PROJECT_EDIT %s\n' "$*" >>"$log"
  exit 0
fi

echo "unsupported fake gh call: $*" >&2
exit 70
FAKE_GH
  chmod +x "$fake"
  printf '%s\n' "$fake"
}

run_success_apply() {
  local plan="$WORK/plan-success.json" log="$WORK/success.log" fake out
  : >"$log"
  fake="$(write_fake_gh)"
  write_plan "$plan"
  out="$(FAKE_GH_LOG="$log" FAKE_ISSUE_BODY="$WORK/issue-body-ok.txt" FAKE_PR_BODY="$WORK/pr-body-empty.txt" \
    python3 "$HELPER" --cas-result "$WORK/cas.json" --plan "$plan" --gh "$fake" --apply)"
  printf '%s\n' "$out" | jq -e '
    .status == "post_cas_mirrors_applied"
    and (.applied_surfaces | index("issue_body"))
    and (.applied_surfaces | index("project:Status"))
    and (.applied_surfaces | index("pr_body"))
    and .permission_granted == false
  ' >/dev/null
  grep -q '^ISSUE_EDIT ' "$log"
  grep -q '^PROJECT_EDIT ' "$log"
  grep -q '^PR_EDIT ' "$log"
}

run_cas_mismatch_refuses_without_mutation() {
  local plan="$WORK/plan-cas-mismatch.json" log="$WORK/cas-mismatch.log" fake out rc
  : >"$log"
  fake="$(write_fake_gh)"
  write_plan "$plan" "Todo" "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  set +e
  out="$(FAKE_GH_LOG="$log" FAKE_ISSUE_BODY="$WORK/issue-body-ok.txt" FAKE_PR_BODY="$WORK/pr-body-empty.txt" \
    python3 "$HELPER" --cas-result "$WORK/cas.json" --plan "$plan" --gh "$fake" --apply)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '.status == "post_cas_mirror_refused" and .permission_granted == false' >/dev/null
  [ ! -s "$log" ]
}

run_issue_stale_refuses_before_mutation() {
  local plan="$WORK/plan-issue-stale.json" stale="$WORK/issue-body-stale.txt" log="$WORK/issue-stale.log" fake out rc
  : >"$log"
  fake="$(write_fake_gh)"
  sed 's/status: in-progress/status: todo/' "$WORK/issue-body-ok.txt" >"$stale"
  write_plan "$plan"
  set +e
  out="$(FAKE_GH_LOG="$log" FAKE_ISSUE_BODY="$stale" FAKE_PR_BODY="$WORK/pr-body-empty.txt" \
    python3 "$HELPER" --cas-result "$WORK/cas.json" --plan "$plan" --gh "$fake" --apply)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '.status == "post_cas_mirror_refused"' >/dev/null
  [ ! -s "$log" ]
}

run_project_no_downgrade_refuses_before_mutation() {
  local plan="$WORK/plan-project-done.json" log="$WORK/project-done.log" fake out rc
  : >"$log"
  fake="$(write_fake_gh)"
  write_plan "$plan" "Done"
  set +e
  out="$(FAKE_GH_LOG="$log" FAKE_ISSUE_BODY="$WORK/issue-body-ok.txt" FAKE_PR_BODY="$WORK/pr-body-empty.txt" \
    python3 "$HELPER" --cas-result "$WORK/cas.json" --plan "$plan" --gh "$fake" --apply)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '.status == "post_cas_mirror_refused"' >/dev/null
  [ ! -s "$log" ]
}

run_pr_marker_mismatch_refuses_before_mutation() {
  local plan="$WORK/plan-pr-mismatch.json" pr="$WORK/pr-body-marker.txt" log="$WORK/pr-mismatch.log" fake out rc
  : >"$log"
  fake="$(write_fake_gh)"
  cat >"$pr" <<'BODY'
Existing PR body.

<!-- coordination-ledger-pr-mirror:v1
coordination_state: active_winner
event_uuid: old-event
event_hash: sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
session: old-session
-->
BODY
  write_plan "$plan" "Todo" "$EVENT_HASH" '"event_uuid": "expected-different-event"'
  set +e
  out="$(FAKE_GH_LOG="$log" FAKE_ISSUE_BODY="$WORK/issue-body-ok.txt" FAKE_PR_BODY="$pr" \
    python3 "$HELPER" --cas-result "$WORK/cas.json" --plan "$plan" --gh "$fake" --apply)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '.status == "post_cas_mirror_refused"' >/dev/null
  [ ! -s "$log" ]
}

run_partial_project_failure_reports_debt() {
  local plan="$WORK/plan-partial.json" log="$WORK/partial.log" fake out rc
  : >"$log"
  fake="$(write_fake_gh)"
  write_plan "$plan"
  set +e
  out="$(FAKE_FAIL_PROJECT=1 FAKE_GH_LOG="$log" FAKE_ISSUE_BODY="$WORK/issue-body-ok.txt" FAKE_PR_BODY="$WORK/pr-body-empty.txt" \
    python3 "$HELPER" --cas-result "$WORK/cas.json" --plan "$plan" --gh "$fake" --apply)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '
    .status == "mirror_write_failed_repair_required"
    and (.repair_debt | length >= 1)
    and (.applied_surfaces | index("issue_body"))
    and (.applied_surfaces | index("pr_body"))
    and .permission_granted == false
  ' >/dev/null
  grep -q '^ISSUE_EDIT ' "$log"
}

printf 'coordination ledger post-CAS mirror harness\n'
run_success_apply
printf '  ok CAS success applies issue, Project, and PR mirrors\n'
run_cas_mismatch_refuses_without_mutation
printf '  ok CAS mismatch refuses before mutation\n'
run_issue_stale_refuses_before_mutation
printf '  ok stale issue body refuses before mutation\n'
run_project_no_downgrade_refuses_before_mutation
printf '  ok Project no-downgrade refuses before mutation\n'
run_pr_marker_mismatch_refuses_before_mutation
printf '  ok PR marker mismatch refuses before mutation\n'
run_partial_project_failure_reports_debt
printf '  ok partial mirror failure reports repair debt without granting permission\n'
printf 'PASS coordination ledger post-CAS mirror harness\n'
