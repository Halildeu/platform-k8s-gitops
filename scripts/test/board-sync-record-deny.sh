#!/usr/bin/env bash
# Offline harness for board-sync.sh record-deny local audit debt queue.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BOARD_SYNC="$REPO_ROOT/scripts/board-sync.sh"
WORK="$(mktemp -d -t board-sync-record-deny.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

FAKE_BIN="$WORK/bin"
mkdir -p "$FAKE_BIN"

cat >"$FAKE_BIN/gh" <<'FAKE_GH'
#!/usr/bin/env bash
echo "fake gh: record-deny must not call gh" >&2
exit 97
FAKE_GH
chmod +x "$FAKE_BIN/gh"

PATH="$FAKE_BIN:$PATH"
export PATH

QUEUE="$WORK/audit-debt.jsonl"
INTENT_ID="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

make_intent() {
  jq -cn \
    --arg id "$INTENT_ID" \
    '{
      allowed: false,
      issue: "Halildeu/platform-k8s-gitops#1498",
      session: "session-a",
      operation: "deploy",
      permission_source: "project_issue_mirror_v1",
      deny_code: "project_truth_stale",
      deny_event_intent_id: $id,
      details: [
        {
          code: "project_truth_stale",
          message: "Project truth stale"
        }
      ]
    }'
}

run_record_queues_local_debt() {
  local out rc
  set +e
  out="$(COORDINATION_AUDIT_DEBT_QUEUE="$QUEUE" "$BOARD_SYNC" record-deny --intent "$(make_intent)")"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e --arg id "$INTENT_ID" --arg queue "$QUEUE" '
    .recorded == false
    and .queued == true
    and .duplicate == false
    and .status == "blocked_audit_debt"
    and .reason == "cas_writer_unavailable"
    and .queue_path == $queue
    and .deny_event_intent_id == $id
  ' >/dev/null
  [ "$(wc -l <"$QUEUE" | tr -d ' ')" -eq 1 ]
  jq -e --arg id "$INTENT_ID" '
    .schemaVersion == "coordination-audit-debt/v1"
    and .status == "blocked_audit_debt"
    and .reason == "cas_writer_unavailable"
    and .deny_event_intent_id == $id
    and .intent.deny_event_intent_id == $id
  ' "$QUEUE" >/dev/null
}

run_record_duplicate_is_idempotent() {
  local out rc
  set +e
  out="$(COORDINATION_AUDIT_DEBT_QUEUE="$QUEUE" "$BOARD_SYNC" record-deny --intent "$(make_intent)")"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e --arg id "$INTENT_ID" '
    .recorded == false
    and .queued == false
    and .duplicate == true
    and .reason == "duplicate_local_debt"
    and .deny_event_intent_id == $id
  ' >/dev/null
  [ "$(wc -l <"$QUEUE" | tr -d ' ')" -eq 1 ]
}

run_record_from_stdin() {
  local out rc stdin_queue
  stdin_queue="$WORK/stdin-debt.jsonl"
  set +e
  out="$(make_intent | COORDINATION_AUDIT_DEBT_QUEUE="$stdin_queue" "$BOARD_SYNC" record-deny --intent-file -)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | jq -e '.queued == true and .status == "blocked_audit_debt"' >/dev/null
  [ "$(wc -l <"$stdin_queue" | tr -d ' ')" -eq 1 ]
}

run_invalid_intent_rejected() {
  local out rc bad_queue
  bad_queue="$WORK/bad.jsonl"
  set +e
  out="$(COORDINATION_AUDIT_DEBT_QUEUE="$bad_queue" "$BOARD_SYNC" record-deny --intent '{"deny_code":"missing-id"}' 2>&1)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | grep -q 'invalid deny intent JSON'
  [ ! -e "$bad_queue" ]
}

run_allowed_intent_rejected() {
  local out rc allowed_queue
  allowed_queue="$WORK/allowed.jsonl"
  set +e
  out="$(make_intent | jq '.allowed = true' | COORDINATION_AUDIT_DEBT_QUEUE="$allowed_queue" "$BOARD_SYNC" record-deny --intent-file - 2>&1)"
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  printf '%s\n' "$out" | grep -q 'invalid deny intent JSON'
  [ ! -e "$allowed_queue" ]
}

printf 'board-sync.sh record-deny local debt harness\n'
run_record_queues_local_debt
printf '  ok denial intent queues local blocked_audit_debt\n'
run_record_duplicate_is_idempotent
printf '  ok duplicate deny_event_intent_id is idempotent\n'
run_record_from_stdin
printf '  ok --intent-file - queues stdin intent\n'
run_invalid_intent_rejected
printf '  ok invalid intent rejected without queue creation\n'
run_allowed_intent_rejected
printf '  ok allowed=true intent rejected without queue creation\n'
printf 'PASS board-sync record-deny local debt harness\n'
