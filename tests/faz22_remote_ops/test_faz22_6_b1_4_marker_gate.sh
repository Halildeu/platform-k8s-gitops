#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GENERATOR="$ROOT/scripts/faz22-remote-ops/faz22-6-b1-4-acceptance-package.sh"

export F22_6_COMPLETION_AUDIT_SOURCE_ONLY=1
# shellcheck source=/dev/null
source "$ROOT/scripts/faz22-remote-ops/faz22-6-completion-audit.sh"

future_date_utc() {
  local days="$1"
  if date -u -d "+$days days" +%F >/dev/null 2>&1; then
    date -u -d "+$days days" +%F
    return
  fi
  case "$days" in
    -*) date -u -v"${days}"d +%F ;;
    *) date -u -v+"$days"d +%F ;;
  esac
}

tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
mkdir -p "$tmp_root"
tmp_dir="$(mktemp -d "$tmp_root/b1-4-marker.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

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
  && [ "${3:-}" = "548" ] \
  && [ "${4:-}" = "-R" ] \
  && [ "${5:-}" = "Halildeu/platform-backend" ] \
  && [ "${6:-}" = "--json" ] \
  && [ "${7:-}" = "state,body,title,url" ]; then
  cat "$FAKE_GH_ISSUE_JSON"
  exit 0
fi
echo "unexpected fake gh invocation: $*" >&2
exit 2
SH
chmod +x "$fake_bin/gh"

expect_generator_fail() {
  local label="$1"
  shift
  set +e
  "$GENERATOR" "$@" >"$tmp_dir/generator-${label}.out" 2>"$tmp_dir/generator-${label}.err"
  local rc="$?"
  set -e
  if [ "$rc" = "0" ]; then
    echo "expected B1.4 generator failure for $label" >&2
    exit 1
  fi
}

issue_json="$tmp_dir/b1-4-issue.json"
approved_at="$(date -u +%F)"
expires_at="$(future_date_utc 7)"
expired_at="$(future_date_utc -1)"

hardware_marker="$tmp_dir/b1-4-hardware-marker.txt"
hardware_generator_out="$(
  "$GENERATOR" \
    --mode hardware \
    --marker-out "$hardware_marker" \
    --owner-approved-by "Owner Example" \
    --approved-at "$approved_at"
)"
printf '%s\n' "$hardware_generator_out" | tee "$tmp_dir/hardware-generator.out"
grep -q "^marker=$hardware_marker$" "$tmp_dir/hardware-generator.out"
grep -q '^mode=hardware$' "$tmp_dir/hardware-generator.out"
grep -q "^approved_at=$approved_at$" "$tmp_dir/hardware-generator.out"
hardware_body="$(cat "$hardware_marker")"

jq -n \
  --arg state "CLOSED" \
  --arg body "$hardware_body" \
  --arg title "fake B1.4 hardware acceptance issue" \
  '{state:$state,body:$body,title:$title,url:"https://github.com/Halildeu/platform-backend/issues/548"}' \
  >"$issue_json"

output="$(
  PATH="$fake_bin:$PATH" \
    FAKE_GH_ISSUE_JSON="$issue_json" \
    B1_4_ATTESTATION_ACCEPTANCE_REF="Halildeu/platform-backend#548" \
    check_b1_4_hardware_gate
)"
printf '%s\n' "$output" | tee "$tmp_dir/hardware-pass.out"
grep -q '^GATE_B1_4_HARDWARE_ATTESTATION=pass ' "$tmp_dir/hardware-pass.out"
grep -q "approved_at=$approved_at" "$tmp_dir/hardware-pass.out"

jq -n \
  --arg state "OPEN" \
  --arg body "$hardware_body" \
  --arg title "fake B1.4 hardware acceptance issue still open" \
  '{state:$state,body:$body,title:$title,url:"https://github.com/Halildeu/platform-backend/issues/548"}' \
  >"$issue_json"
set +e
output="$(
  PATH="$fake_bin:$PATH" \
    FAKE_GH_ISSUE_JSON="$issue_json" \
    B1_4_ATTESTATION_ACCEPTANCE_REF="Halildeu/platform-backend#548" \
    check_b1_4_hardware_gate
)"
rc="$?"
set -e
if [ "$rc" = "0" ]; then
  echo "expected open hardware acceptance issue to remain blocked" >&2
  exit 1
fi
printf '%s\n' "$output" >"$tmp_dir/hardware-open.out"
grep -q '^GATE_B1_4_HARDWARE_ATTESTATION=blocked ' "$tmp_dir/hardware-open.out"
grep -q 'reason=issue-not-closed' "$tmp_dir/hardware-open.out"

hardware_missing_replay="${hardware_body/negative_matrix: missing,stale,replay,wrong-device,wrong-tenant/negative_matrix: missing,stale,wrong-device,wrong-tenant}"
jq -n \
  --arg state "CLOSED" \
  --arg body "$hardware_missing_replay" \
  --arg title "fake B1.4 hardware acceptance missing replay negative" \
  '{state:$state,body:$body,title:$title,url:"https://github.com/Halildeu/platform-backend/issues/548"}' \
  >"$issue_json"
set +e
output="$(
  PATH="$fake_bin:$PATH" \
    FAKE_GH_ISSUE_JSON="$issue_json" \
    B1_4_ATTESTATION_ACCEPTANCE_REF="Halildeu/platform-backend#548" \
    check_b1_4_hardware_gate
)"
rc="$?"
set -e
if [ "$rc" = "0" ]; then
  echo "expected missing replay negative evidence to remain blocked" >&2
  exit 1
fi
printf '%s\n' "$output" >"$tmp_dir/hardware-missing-replay.out"
grep -q '^GATE_B1_4_HARDWARE_ATTESTATION=blocked ' "$tmp_dir/hardware-missing-replay.out"
grep -q 'negative_matrix:replay' "$tmp_dir/hardware-missing-replay.out"

hardware_with_expiry="$(printf '%s\nexpires_at: %s\n' "$hardware_body" "$expires_at")"
jq -n \
  --arg state "CLOSED" \
  --arg body "$hardware_with_expiry" \
  --arg title "fake B1.4 hardware acceptance with forbidden expiry" \
  '{state:$state,body:$body,title:$title,url:"https://github.com/Halildeu/platform-backend/issues/548"}' \
  >"$issue_json"
set +e
output="$(
  PATH="$fake_bin:$PATH" \
    FAKE_GH_ISSUE_JSON="$issue_json" \
    B1_4_ATTESTATION_ACCEPTANCE_REF="Halildeu/platform-backend#548" \
    check_b1_4_hardware_gate
)"
rc="$?"
set -e
if [ "$rc" = "0" ]; then
  echo "expected hardware marker with expires_at to remain blocked" >&2
  exit 1
fi
printf '%s\n' "$output" >"$tmp_dir/hardware-expiry-forbidden.out"
grep -q '^GATE_B1_4_HARDWARE_ATTESTATION=blocked ' "$tmp_dir/hardware-expiry-forbidden.out"
grep -q 'expires_at-forbidden' "$tmp_dir/hardware-expiry-forbidden.out"

risk_marker="$tmp_dir/b1-4-risk-marker.txt"
risk_generator_out="$(
  "$GENERATOR" \
    --mode risk \
    --marker-out "$risk_marker" \
    --owner-approved-by "Owner Example" \
    --approved-at "$approved_at" \
    --expires-at "$expires_at"
)"
printf '%s\n' "$risk_generator_out" | tee "$tmp_dir/risk-generator.out"
grep -q "^marker=$risk_marker$" "$tmp_dir/risk-generator.out"
grep -q '^mode=risk$' "$tmp_dir/risk-generator.out"
grep -q "^expires_at=$expires_at$" "$tmp_dir/risk-generator.out"
risk_body="$(cat "$risk_marker")"

jq -n \
  --arg state "OPEN" \
  --arg body "$risk_body" \
  --arg title "fake B1.4 bounded risk acceptance issue" \
  '{state:$state,body:$body,title:$title,url:"https://github.com/Halildeu/platform-backend/issues/548"}' \
  >"$issue_json"
output="$(
  PATH="$fake_bin:$PATH" \
    FAKE_GH_ISSUE_JSON="$issue_json" \
    B1_4_ATTESTATION_ACCEPTANCE_REF="Halildeu/platform-backend#548" \
    check_b1_4_hardware_gate
)"
printf '%s\n' "$output" | tee "$tmp_dir/risk-pass.out"
grep -q '^GATE_B1_4_HARDWARE_ATTESTATION=bounded_pilot_risk_accepted ' "$tmp_dir/risk-pass.out"
grep -q "expires_at=$expires_at" "$tmp_dir/risk-pass.out"

multiple_marker_body="$(printf '%s\n\n%s\n' "$hardware_body" "$risk_body")"
jq -n \
  --arg state "OPEN" \
  --arg body "$multiple_marker_body" \
  --arg title "fake B1.4 issue with hardware and risk markers" \
  '{state:$state,body:$body,title:$title,url:"https://github.com/Halildeu/platform-backend/issues/548"}' \
  >"$issue_json"
set +e
output="$(
  PATH="$fake_bin:$PATH" \
    FAKE_GH_ISSUE_JSON="$issue_json" \
    B1_4_ATTESTATION_ACCEPTANCE_REF="Halildeu/platform-backend#548" \
    check_b1_4_hardware_gate
)"
rc="$?"
set -e
if [ "$rc" = "0" ]; then
  echo "expected issue with hardware and risk markers to remain blocked" >&2
  exit 1
fi
printf '%s\n' "$output" >"$tmp_dir/multiple-marker.out"
grep -q '^GATE_B1_4_HARDWARE_ATTESTATION=blocked ' "$tmp_dir/multiple-marker.out"
grep -q 'reason=multiple-markers' "$tmp_dir/multiple-marker.out"

jq -n \
  --arg state "CLOSED" \
  --arg body "$risk_body" \
  --arg title "fake B1.4 bounded risk acceptance issue closed" \
  '{state:$state,body:$body,title:$title,url:"https://github.com/Halildeu/platform-backend/issues/548"}' \
  >"$issue_json"
set +e
output="$(
  PATH="$fake_bin:$PATH" \
    FAKE_GH_ISSUE_JSON="$issue_json" \
    B1_4_ATTESTATION_ACCEPTANCE_REF="Halildeu/platform-backend#548" \
    check_b1_4_hardware_gate
)"
rc="$?"
set -e
if [ "$rc" = "0" ]; then
  echo "expected closed bounded-risk issue to remain blocked" >&2
  exit 1
fi
printf '%s\n' "$output" >"$tmp_dir/risk-closed.out"
grep -q '^GATE_B1_4_HARDWARE_ATTESTATION=blocked ' "$tmp_dir/risk-closed.out"
grep -q 'issue-not-open-for-risk-tracking' "$tmp_dir/risk-closed.out"

risk_missing_control="${risk_body/compensating_controls: cert-bound-token,mTLS,revocation-check,signed-permits,dual-control,audit-recording,kill-revoke/compensating_controls: cert-bound-token,mTLS,revocation-check,signed-permits,dual-control,kill-revoke}"
jq -n \
  --arg state "OPEN" \
  --arg body "$risk_missing_control" \
  --arg title "fake B1.4 bounded risk missing audit recording" \
  '{state:$state,body:$body,title:$title,url:"https://github.com/Halildeu/platform-backend/issues/548"}' \
  >"$issue_json"
set +e
output="$(
  PATH="$fake_bin:$PATH" \
    FAKE_GH_ISSUE_JSON="$issue_json" \
    B1_4_ATTESTATION_ACCEPTANCE_REF="Halildeu/platform-backend#548" \
    check_b1_4_hardware_gate
)"
rc="$?"
set -e
if [ "$rc" = "0" ]; then
  echo "expected missing audit-recording compensating control to remain blocked" >&2
  exit 1
fi
printf '%s\n' "$output" >"$tmp_dir/risk-missing-control.out"
grep -q '^GATE_B1_4_HARDWARE_ATTESTATION=blocked ' "$tmp_dir/risk-missing-control.out"
grep -q 'compensating_controls:audit-recording' "$tmp_dir/risk-missing-control.out"

risk_missing_forbidden="${risk_body/forbidden_claims: tpm-complete,hardware-attestation-complete,5-device,50-device,800-device,production,broad-rollout/forbidden_claims: tpm-complete,hardware-attestation-complete,5-device,50-device,800-device,production}"
jq -n \
  --arg state "OPEN" \
  --arg body "$risk_missing_forbidden" \
  --arg title "fake B1.4 bounded risk missing broad-rollout forbidden claim" \
  '{state:$state,body:$body,title:$title,url:"https://github.com/Halildeu/platform-backend/issues/548"}' \
  >"$issue_json"
set +e
output="$(
  PATH="$fake_bin:$PATH" \
    FAKE_GH_ISSUE_JSON="$issue_json" \
    B1_4_ATTESTATION_ACCEPTANCE_REF="Halildeu/platform-backend#548" \
    check_b1_4_hardware_gate
)"
rc="$?"
set -e
if [ "$rc" = "0" ]; then
  echo "expected missing broad-rollout forbidden claim to remain blocked" >&2
  exit 1
fi
printf '%s\n' "$output" >"$tmp_dir/risk-missing-forbidden.out"
grep -q '^GATE_B1_4_HARDWARE_ATTESTATION=blocked ' "$tmp_dir/risk-missing-forbidden.out"
grep -q 'forbidden_claims:broad-rollout' "$tmp_dir/risk-missing-forbidden.out"

risk_placeholder_owner="${risk_body/owner_approved_by: Owner Example/owner_approved_by: TBD}"
jq -n \
  --arg state "OPEN" \
  --arg body "$risk_placeholder_owner" \
  --arg title "fake B1.4 bounded risk placeholder owner" \
  '{state:$state,body:$body,title:$title,url:"https://github.com/Halildeu/platform-backend/issues/548"}' \
  >"$issue_json"
set +e
output="$(
  PATH="$fake_bin:$PATH" \
    FAKE_GH_ISSUE_JSON="$issue_json" \
    B1_4_ATTESTATION_ACCEPTANCE_REF="Halildeu/platform-backend#548" \
    check_b1_4_hardware_gate
)"
rc="$?"
set -e
if [ "$rc" = "0" ]; then
  echo "expected placeholder bounded-risk owner to remain blocked" >&2
  exit 1
fi
printf '%s\n' "$output" >"$tmp_dir/risk-placeholder-owner.out"
grep -q '^GATE_B1_4_HARDWARE_ATTESTATION=blocked ' "$tmp_dir/risk-placeholder-owner.out"
grep -q 'owner_approved_by' "$tmp_dir/risk-placeholder-owner.out"

risk_expired="${risk_body/expires_at: $expires_at/expires_at: $expired_at}"
jq -n \
  --arg state "OPEN" \
  --arg body "$risk_expired" \
  --arg title "fake B1.4 bounded risk expired" \
  '{state:$state,body:$body,title:$title,url:"https://github.com/Halildeu/platform-backend/issues/548"}' \
  >"$issue_json"
set +e
output="$(
  PATH="$fake_bin:$PATH" \
    FAKE_GH_ISSUE_JSON="$issue_json" \
    B1_4_ATTESTATION_ACCEPTANCE_REF="Halildeu/platform-backend#548" \
    check_b1_4_hardware_gate
)"
rc="$?"
set -e
if [ "$rc" = "0" ]; then
  echo "expected expired bounded-risk marker to remain blocked" >&2
  exit 1
fi
printf '%s\n' "$output" >"$tmp_dir/risk-expired.out"
grep -q '^GATE_B1_4_HARDWARE_ATTESTATION=blocked ' "$tmp_dir/risk-expired.out"
grep -q 'expires_at-expired' "$tmp_dir/risk-expired.out"

expect_generator_fail "bad-mode" \
  --mode unknown \
  --marker-out "$tmp_dir/bad-mode.txt" \
  --owner-approved-by "Owner Example" \
  --approved-at "$approved_at"

expect_generator_fail "placeholder-owner" \
  --mode risk \
  --marker-out "$tmp_dir/placeholder-owner.txt" \
  --owner-approved-by "TBD" \
  --approved-at "$approved_at" \
  --expires-at "$expires_at"

expect_generator_fail "risk-missing-expires" \
  --mode risk \
  --marker-out "$tmp_dir/risk-missing-expires.txt" \
  --owner-approved-by "Owner Example" \
  --approved-at "$approved_at"

expect_generator_fail "risk-expired" \
  --mode risk \
  --marker-out "$tmp_dir/risk-expired-generator.txt" \
  --owner-approved-by "Owner Example" \
  --approved-at "$approved_at" \
  --expires-at "$expired_at"

expect_generator_fail "hardware-with-expires" \
  --mode hardware \
  --marker-out "$tmp_dir/hardware-with-expires.txt" \
  --owner-approved-by "Owner Example" \
  --approved-at "$approved_at" \
  --expires-at "$expires_at"

echo "b1-4-marker-gate-ok"
