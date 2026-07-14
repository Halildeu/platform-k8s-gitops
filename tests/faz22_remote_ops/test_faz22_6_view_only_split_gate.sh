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

fake_bin="$tmp_dir/bin"
mkdir -p "$fake_bin"
cat >"$fake_bin/gh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "auth" ] && [ "${2:-}" = "status" ]; then
  exit 0
fi
if [ "$#" -eq 7 ] \
  && [ "${1:-}" = "issue" ] \
  && [ "${2:-}" = "view" ] \
  && { [ "${3:-}" = "1580" ] || [ "${3:-}" = "2374" ]; } \
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
    VIEW_ONLY_KVKK_REF="Halildeu/platform-k8s-gitops#2374" \
    VIEW_ONLY_KVKK_APPROVER_POLICY_PATH="$tmp_dir/approver-policy.json" \
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

# Build real dual-human-signed current and expired markers. The shell gate must
# cryptographically verify these against the same canonical public-key policy.
python3 - "$tmp_dir" <<'PY'
import base64
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests.faz22_remote_ops.test_faz22_6_view_only_kvkk_decision import (
    VERIFIER, policy, utc, valid_unsigned_record,
)

out = Path(sys.argv[1])
now = datetime.now(timezone.utc).replace(microsecond=0)
owner_key = Ed25519PrivateKey.generate()
legal_key = Ed25519PrivateKey.generate()
approver_policy = policy(now, owner_key, legal_key)

def sign(record):
    record["approvals"]["privacyOwner"]["signatureBase64"] = base64.b64encode(
        owner_key.sign(VERIFIER.approval_message(record, record["approvals"]["privacyOwner"], approver_policy))
    ).decode("ascii")
    record["approvals"]["legalOrDpo"]["signatureBase64"] = base64.b64encode(
        legal_key.sign(VERIFIER.approval_message(record, record["approvals"]["legalOrDpo"], approver_policy))
    ).decode("ascii")
    return record

current = sign(valid_unsigned_record(now))
current_result = VERIFIER.validate_semantics(current, approver_policy, now, True)

expired = valid_unsigned_record(now)
expired_approved = now - timedelta(days=2)
expired["approvals"]["privacyOwner"]["signedAt"] = utc(expired_approved - timedelta(hours=1))
expired["approvals"]["legalOrDpo"]["signedAt"] = utc(expired_approved)
expired["lifecycle"]["approvedAt"] = utc(expired_approved)
expired["lifecycle"]["reviewExpiresAt"] = utc(now - timedelta(days=1))
expired["uxVerification"]["verifiedAt"] = utc(expired_approved - timedelta(hours=2))
for name in ("sessionMetadata", "auditRecords"):
    expired["retention"][name]["effectiveFrom"] = utc(expired_approved - timedelta(days=1))
expired["governance"]["decisionRecordStorage"]["recordRetention"]["effectiveFrom"] = utc(expired_approved - timedelta(days=1))
expired = sign(expired)
expired_result = VERIFIER.validate_semantics(
    expired, approver_policy, expired_approved + timedelta(hours=1), True
)

(out / "approver-policy.json").write_text(json.dumps(approver_policy), encoding="utf-8")
(out / "cleared-marker.txt").write_text(VERIFIER.marker_text(current_result), encoding="utf-8")
(out / "expired-marker.txt").write_text(VERIFIER.marker_text(expired_result), encoding="utf-8")
PY

cleared_body="$(cat "$tmp_dir/cleared-marker.txt")"
expired_body="$(cat "$tmp_dir/expired-marker.txt")"
decision_digest="$(printf '%s\n' "$cleared_body" | sed -n 's/^decision_record_sha256:[[:space:]]*//p')"
decision_ref="$(printf '%s\n' "$cleared_body" | sed -n 's/^decision_record_ref:[[:space:]]*//p')"

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
write_issue CLOSED "$cleared_body"
expect_rc0 "$tmp_dir/kvkk-cleared.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=cleared ' "$tmp_dir/kvkk-cleared.out"
grep -q 'owner=dual-human-signature:privacy-approvers-2026-v1' "$tmp_dir/kvkk-cleared.out"
grep -q "decision_record_sha256=$decision_digest" "$tmp_dir/kvkk-cleared.out"

# 4) KVKK cleared but expired -> expired, still non-blocking.
write_issue CLOSED "$expired_body"
expect_rc0 "$tmp_dir/kvkk-expired.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=expired ' "$tmp_dir/kvkk-expired.out"

# 5) KVKK cleared with placeholder owner -> incomplete-clear -> tracked_pending (non-blocking).
incomplete_body="$(printf 'F22_6_VIEW_ONLY_KVKK: v1\nstatus: cleared\nkvkk_attended_pilot_signoff: pass\nowner_approved_by: TBD\napproved_at: %s\nexpires_at: %s\n' "$approved_at" "$expires_at")"
write_issue CLOSED "$incomplete_body"
expect_rc0 "$tmp_dir/kvkk-incomplete.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=tracked_pending ' "$tmp_dir/kvkk-incomplete.out"
grep -q 'incomplete-clear' "$tmp_dir/kvkk-incomplete.out"

# 5b) A digest without the exact content-addressed URN cannot clear.
bad_ref_body="${cleared_body//$decision_ref/https:\/\/storage.example\/records\/decision.json}"
write_issue CLOSED "$bad_ref_body"
expect_rc0 "$tmp_dir/kvkk-bad-ref.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=tracked_pending ' "$tmp_dir/kvkk-bad-ref.out"
grep -q 'decision_record_ref' "$tmp_dir/kvkk-bad-ref.out"

# 5c) A cleared marker without both derived key fingerprints is incomplete.
missing_fingerprint_body="$(printf '%s\n' "$cleared_body" | grep -v '^privacy_owner_public_key_sha256:')"
write_issue CLOSED "$missing_fingerprint_body"
expect_rc0 "$tmp_dir/kvkk-missing-fingerprint.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=tracked_pending ' "$tmp_dir/kvkk-missing-fingerprint.out"
grep -q 'privacy_owner_public_key_sha256' "$tmp_dir/kvkk-missing-fingerprint.out"

# 5d) A syntactically valid fingerprint must still resolve to the policy key.
privacy_fingerprint="$(printf '%s\n' "$cleared_body" | sed -n 's/^privacy_owner_public_key_sha256:[[:space:]]*//p')"
bad_fingerprint_body="${cleared_body//$privacy_fingerprint/sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd}"
write_issue CLOSED "$bad_fingerprint_body"
expect_rc0 "$tmp_dir/kvkk-bad-fingerprint.out" run_kvkk
grep -q '^GATE_VIEW_ONLY_KVKK=tracked_pending ' "$tmp_dir/kvkk-bad-fingerprint.out"
grep -q 'reason=cryptographic-marker-verification-failed' "$tmp_dir/kvkk-bad-fingerprint.out"

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
