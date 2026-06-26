#!/usr/bin/env bash
# ADR-0044: VIEW_ONLY gate SPLIT regression.
#   - check_view_only_engineering_gate: fail-closed (duplicate-marker tested here;
#     pass/legacy/missing are covered in the verifier + package tests).
#   - check_view_only_kvkk: TRACKED, NON-BLOCKING. Emits tracked_pending|cleared|
#     expired and returns 0 (never fail-closes completion) EXCEPT for an
#     allowlist_violation (a non-legal field mislabeled as legal), which returns 1.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

export F22_6_COMPLETION_AUDIT_SOURCE_ONLY=1
# shellcheck source=/dev/null
source "$ROOT/scripts/faz22-remote-ops/faz22-6-completion-audit.sh"

tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
mkdir -p "$tmp_root"
tmp_dir="$(mktemp -d "$tmp_root/view-only-split.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

future_date_utc() {
  local days="$1"
  if date -u -d "+$days days" +%F >/dev/null 2>&1; then
    date -u -d "+$days days" +%F
    return
  fi
  date -u -v+"$days"d +%F
}
past_date_utc() {
  local days="$1"
  if date -u -d "-$days days" +%F >/dev/null 2>&1; then
    date -u -d "-$days days" +%F
    return
  fi
  date -u -v-"$days"d +%F
}

approved_at="$(date -u +%F)"
expires_at="$(future_date_utc 7)"
expired_at="$(past_date_utc 1)"
expired_approved_at="$(past_date_utc 2)"

fake_bin="$tmp_dir/bin"
mkdir -p "$fake_bin"
cat >"$fake_bin/gh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -eq 7 ] \
  && [ "${1:-}" = "issue" ] \
  && [ "${2:-}" = "view" ] \
  && [ "${3:-}" = "1580" ] \
  && [ "${4:-}" = "-R" ] \
  && [ "${5:-}" = "Halildeu/platform-k8s-gitops" ] \
  && [ "${6:-}" = "--json" ] \
  && [ "${7:-}" = "state,body,title,url" ]; then
  cat "$FAKE_GH_ISSUE_JSON"
  exit 0
fi
echo "unexpected fake gh invocation: $*" >&2
exit 2
SH
chmod +x "$fake_bin/gh"

issue_json="$tmp_dir/issue.json"
write_issue() { # write_issue <state> <body>
  jq -n --arg state "$1" --arg body "$2" --arg title "fake VIEW_ONLY issue" \
    '{state:$state,body:$body,title:$title,url:"https://example.invalid/issues/1580"}' >"$issue_json"
}
run_kvkk() {
  PATH="$fake_bin:$PATH" FAKE_GH_ISSUE_JSON="$issue_json" \
    VIEW_ONLY_ACCEPTANCE_REF="Halildeu/platform-k8s-gitops#1580" \
    check_view_only_kvkk
}
run_eng() {
  PATH="$fake_bin:$PATH" FAKE_GH_ISSUE_JSON="$issue_json" \
    VIEW_ONLY_ACCEPTANCE_REF="Halildeu/platform-k8s-gitops#1580" \
    check_view_only_engineering_gate
}
expect_rc0() { # expect_rc0 <out-file> <cmd...>
  local out="$1"; shift
  set +e; "$@" >"$out" 2>&1; local rc="$?"; set -e
  [ "$rc" = "0" ] || { echo "expected rc=0 (non-blocking): $* (got $rc)"; cat "$out"; exit 1; }
}
expect_rc_nonzero() { # expect_rc_nonzero <out-file> <cmd...>
  local out="$1"; shift
  set +e; "$@" >"$out" 2>&1; local rc="$?"; set -e
  [ "$rc" != "0" ] || { echo "expected rc!=0 (blocking): $*"; cat "$out"; exit 1; }
}

# 1) No KVKK marker -> tracked_pending, non-blocking.
write_issue CLOSED "some unrelated body text"
expect_rc0 "$tmp_dir/kvkk-none.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=tracked_pending ' "$tmp_dir/kvkk-none.out"
grep -q 'reason=no-kvkk-marker' "$tmp_dir/kvkk-none.out"

# 2) KVKK marker status=pending -> tracked_pending, non-blocking.
pending_body="$(printf 'F22_6_VIEW_ONLY_KVKK: v1\nstatus: pending\nkvkk_attended_pilot_signoff: pending\n')"
write_issue CLOSED "$pending_body"
expect_rc0 "$tmp_dir/kvkk-pending.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=tracked_pending ' "$tmp_dir/kvkk-pending.out"

# 3) KVKK cleared with valid DPO owner + dates -> cleared, non-blocking.
cleared_body="$(printf 'F22_6_VIEW_ONLY_KVKK: v1\nstatus: cleared\nkvkk_attended_pilot_signoff: pass\nlegal_dpo_consent: pass\nretention_policy_approval: pass\nowner_approved_by: DPO Example\napproved_at: %s\nexpires_at: %s\n' "$approved_at" "$expires_at")"
write_issue CLOSED "$cleared_body"
expect_rc0 "$tmp_dir/kvkk-cleared.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=cleared ' "$tmp_dir/kvkk-cleared.out"
grep -q 'owner=DPO Example' "$tmp_dir/kvkk-cleared.out"

# 4) KVKK cleared but expired -> expired, still non-blocking.
expired_body="$(printf 'F22_6_VIEW_ONLY_KVKK: v1\nstatus: cleared\nkvkk_attended_pilot_signoff: pass\nlegal_dpo_consent: pass\nretention_policy_approval: pass\nowner_approved_by: DPO Example\napproved_at: %s\nexpires_at: %s\n' "$expired_approved_at" "$expired_at")"
write_issue CLOSED "$expired_body"
expect_rc0 "$tmp_dir/kvkk-expired.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=expired ' "$tmp_dir/kvkk-expired.out"

# 5) KVKK cleared with placeholder owner -> incomplete-clear -> tracked_pending (non-blocking).
incomplete_body="$(printf 'F22_6_VIEW_ONLY_KVKK: v1\nstatus: cleared\nkvkk_attended_pilot_signoff: pass\nowner_approved_by: TBD\napproved_at: %s\nexpires_at: %s\n' "$approved_at" "$expires_at")"
write_issue CLOSED "$incomplete_body"
expect_rc0 "$tmp_dir/kvkk-incomplete.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=tracked_pending ' "$tmp_dir/kvkk-incomplete.out"
grep -q 'incomplete-clear' "$tmp_dir/kvkk-incomplete.out"

# 6) ALLOWLIST VIOLATION: a security/product field mislabeled as legal -> blocks.
violation_body="$(printf 'F22_6_VIEW_ONLY_KVKK: v1\nstatus: cleared\nkvkk_attended_pilot_signoff: pass\ndlp_mask_policy: pass\nrecording_mode: disabled\nowner_approved_by: DPO Example\napproved_at: %s\nexpires_at: %s\n' "$approved_at" "$expires_at")"
write_issue CLOSED "$violation_body"
expect_rc_nonzero "$tmp_dir/kvkk-violation.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=allowlist_violation ' "$tmp_dir/kvkk-violation.out"
grep -q 'forbidden_keys=' "$tmp_dir/kvkk-violation.out"
grep -q 'dlp_mask_policy' "$tmp_dir/kvkk-violation.out"
grep -q 'recording_mode' "$tmp_dir/kvkk-violation.out"

# 7) Duplicate KVKK markers (both clean) -> tracked_pending duplicate, non-blocking.
dup_body="$(printf '%s\n\n%s\n' "$cleared_body" "$cleared_body")"
write_issue CLOSED "$dup_body"
expect_rc0 "$tmp_dir/kvkk-dup.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=tracked_pending ' "$tmp_dir/kvkk-dup.out"
grep -q 'reason=duplicate-marker' "$tmp_dir/kvkk-dup.out"

# 7b) Duplicate where a SECOND marker smuggles a forbidden key must NOT slip
#     through the duplicate short-circuit -> allowlist_violation (blocks).
dup_smuggle="$(printf '%s\n\nF22_6_VIEW_ONLY_KVKK: v1\nstatus: cleared\ndlp_mask_policy: pass\nowner_approved_by: DPO Example\n' "$cleared_body")"
write_issue CLOSED "$dup_smuggle"
expect_rc_nonzero "$tmp_dir/kvkk-dup-smuggle.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=allowlist_violation ' "$tmp_dir/kvkk-dup-smuggle.out"
grep -q 'dlp_mask_policy' "$tmp_dir/kvkk-dup-smuggle.out"

# 8) Engineering duplicate marker -> blocked.
dup_eng="$(printf 'F22_6_VIEW_ONLY_ENGINEERING: v2\nacceptance_scope: bounded-pilot-view-only\n\nF22_6_VIEW_ONLY_ENGINEERING: v2\nacceptance_scope: bounded-pilot-view-only\n')"
write_issue CLOSED "$dup_eng"
expect_rc_nonzero "$tmp_dir/eng-dup.out" run_eng
grep -q '^GATE_VIEW_ONLY_ENGINEERING=blocked ' "$tmp_dir/eng-dup.out"
grep -q 'reason=duplicate-marker' "$tmp_dir/eng-dup.out"

# 9) DUAL OUTPUT: an issue with NO engineering marker but a cleared KVKK marker
#    -> engineering blocked AND KVKK cleared (both visible, independent).
write_issue CLOSED "$cleared_body"
expect_rc_nonzero "$tmp_dir/dual-eng.out" run_eng
grep -q '^GATE_VIEW_ONLY_ENGINEERING=blocked ' "$tmp_dir/dual-eng.out"
grep -q 'reason=missing-acceptance-marker' "$tmp_dir/dual-eng.out"
expect_rc0 "$tmp_dir/dual-kvkk.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=cleared ' "$tmp_dir/dual-kvkk.out"

echo "view-only-split-gate-ok"
