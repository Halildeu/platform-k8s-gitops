#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GENERATOR="$ROOT/scripts/faz22-remote-ops/faz22-6-view-only-evidence-package.sh"

export F22_6_COMPLETION_AUDIT_SOURCE_ONLY=1
export F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1
# shellcheck source=/dev/null
source "$ROOT/scripts/faz22-remote-ops/faz22-6-completion-audit.sh"

tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
mkdir -p "$tmp_root"
tmp_dir="$(mktemp -d "$tmp_root/view-only-package.XXXXXX")"
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
manifest="$tmp_dir/view-only-evidence.json"
marker="$tmp_dir/view-only-marker.txt"
manifest_url="file://$manifest"

run_generator() {
  F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1 "$GENERATOR" \
    --manifest-out "$manifest" \
    --marker-out "$marker" \
    --evidence-url "$manifest_url" \
    --pilot-device "AgentPc2" \
    --session-id "view-only-session-123" \
    --recording-worm pass \
    --d10-fail-closed pass \
    --dlp-mask-policy pass \
    --local-abort pass \
    --active-indicator pass \
    --viewer-path-decision "${1:-fanout-proven}" \
    --kvkk-attended-pilot-signoff pass \
    --owner-approved-by "${2:-Owner Example}" \
    --approved-at "${3:-$approved_at}" \
    --expires-at "${4:-$expires_at}"
}

run_generator | tee "$tmp_dir/generator.out"

grep -q "^manifest=$manifest$" "$tmp_dir/generator.out"
grep -q "^marker=$marker$" "$tmp_dir/generator.out"
grep -Eq '^evidence_package_sha256=[a-f0-9]{64}$' "$tmp_dir/generator.out"

canonical_manifest="$(jq -cS . "$manifest")"
# Use the audit helper's sha256_stream here because the acceptance verifier
# defines the canonical hash contract this package must satisfy.
manifest_sha="$(printf '%s' "$canonical_manifest" | sha256_stream)"
cmp -s "$manifest" <(printf '%s\n' "$canonical_manifest")
grep -q "^evidence_package_sha256: $manifest_sha$" "$marker"

jq -e \
  --arg approved_at "$approved_at" \
  --arg expires_at "$expires_at" \
  '.schema_version == "faz22.6-view-only-evidence-v1"
   and .acceptance_scope == "bounded-pilot-view-only"
   and .product_channel == "endpoint-agent-outbound-mtls-remote-bridge"
   and .view_mode == "VIEW_ONLY"
   and .pilot_device == "AgentPc2"
   and .session_id == "view-only-session-123"
   and .recording_worm == "pass"
   and .d10_fail_closed == "pass"
   and .dlp_mask_policy == "pass"
   and .local_abort == "pass"
   and .active_indicator == "pass"
   and .viewer_path_decision == "fanout-proven"
   and .audit_negative_matrix == ["no-auth","wrong-device","expired-session","recording-down","dlp-deny","local-abort"]
   and .kvkk_attended_pilot_signoff == "pass"
   and .forbidden_claims == ["rdp","credential-entry","raw-shell","port-forward","5-device","50-device","800-device","production","broad-rollout"]
   and .owner_approved_by == "Owner Example"
   and .approved_at == $approved_at
   and .expires_at == $expires_at' \
  "$manifest" >/dev/null

marker_body="$(cat "$marker")"
verify_view_only_evidence_manifest "$manifest_url" "$manifest_sha" "$marker_body"

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

issue_json="$tmp_dir/view-only-issue.json"
jq -n \
  --arg state "CLOSED" \
  --arg body "$marker_body" \
  --arg title "fake VIEW_ONLY acceptance issue" \
  '{state:$state,body:$body,title:$title,url:"https://example.invalid/issues/1580"}' \
  >"$issue_json"

PATH="$fake_bin:$PATH" \
  FAKE_GH_ISSUE_JSON="$issue_json" \
  VIEW_ONLY_ACCEPTANCE_REF="Halildeu/platform-k8s-gitops#1580" \
  check_view_only_gate \
  | tee "$tmp_dir/check-view-only-generated-pass.out"

grep -q '^GATE_VIEW_ONLY_SCREEN_SHARE=pass ' "$tmp_dir/check-view-only-generated-pass.out"
grep -q "evidence_package_sha256=$manifest_sha" "$tmp_dir/check-view-only-generated-pass.out"

owner_deferred_manifest="$tmp_dir/view-only-owner-deferred.json"
owner_deferred_marker="$tmp_dir/view-only-owner-deferred-marker.txt"
F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1 "$GENERATOR" \
  --manifest-out "$owner_deferred_manifest" \
  --marker-out "$owner_deferred_marker" \
  --evidence-url "file://$owner_deferred_manifest" \
  --pilot-device "AgentPc2" \
  --session-id "view-only-session-456" \
  --recording-worm pass \
  --d10-fail-closed pass \
  --dlp-mask-policy pass \
  --local-abort pass \
  --active-indicator pass \
  --viewer-path-decision owner-deferred \
  --kvkk-attended-pilot-signoff pass \
  --owner-approved-by "Owner Example" \
  --approved-at "$approved_at" \
  --expires-at "$expires_at" >/dev/null

jq -e '.viewer_path_decision == "owner-deferred"' "$owner_deferred_manifest" >/dev/null

expect_fail() {
  local expected="$1"
  shift
  set +e
  "$@" >"$tmp_dir/fail.out" 2>&1
  local rc="$?"
  set -e
  if [ "$rc" = "0" ]; then
    echo "expected command to fail: $*" >&2
    exit 1
  fi
  grep -q "$expected" "$tmp_dir/fail.out"
}

expect_fail "viewer-path-decision" run_generator raw-rdp "Owner Example" "$approved_at" "$expires_at"
expect_fail "owner-approved-by" run_generator fanout-proven "TBD" "$approved_at" "$expires_at"
expect_fail "expires-at must not be expired" run_generator fanout-proven "Owner Example" "$expired_approved_at" "$expired_at"
expect_fail "approved-at must not be after expires-at" run_generator fanout-proven "Owner Example" "$(future_date_utc 2)" "$(future_date_utc 1)"

expect_fail "recording-worm" \
  env F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1 "$GENERATOR" \
    --manifest-out "$tmp_dir/bad-recording.json" \
    --marker-out "$tmp_dir/bad-recording-marker.txt" \
    --evidence-url "file://$tmp_dir/bad-recording.json" \
    --pilot-device "AgentPc2" \
    --session-id "view-only-session-789" \
    --recording-worm fail \
    --d10-fail-closed pass \
    --dlp-mask-policy pass \
    --local-abort pass \
    --active-indicator pass \
    --viewer-path-decision fanout-proven \
    --kvkk-attended-pilot-signoff pass \
    --owner-approved-by "Owner Example" \
    --approved-at "$approved_at" \
    --expires-at "$expires_at"

expect_fail "evidence-url must be https://" \
  env F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=0 "$GENERATOR" \
    --manifest-out "$tmp_dir/non-https.json" \
    --marker-out "$tmp_dir/non-https-marker.txt" \
    --evidence-url "file://$tmp_dir/non-https.json" \
    --pilot-device "AgentPc2" \
    --session-id "view-only-session-999" \
    --recording-worm pass \
    --d10-fail-closed pass \
    --dlp-mask-policy pass \
    --local-abort pass \
    --active-indicator pass \
    --viewer-path-decision fanout-proven \
    --kvkk-attended-pilot-signoff pass \
    --owner-approved-by "Owner Example" \
    --approved-at "$approved_at" \
    --expires-at "$expires_at"

expect_fail "query strings" \
  "$GENERATOR" \
    --manifest-out "$tmp_dir/query-url.json" \
    --marker-out "$tmp_dir/query-url-marker.txt" \
    --evidence-url "https://example.invalid/view-only.json?token=bad" \
    --pilot-device "AgentPc2" \
    --session-id "view-only-session-query" \
    --recording-worm pass \
    --d10-fail-closed pass \
    --dlp-mask-policy pass \
    --local-abort pass \
    --active-indicator pass \
    --viewer-path-decision fanout-proven \
    --kvkk-attended-pilot-signoff pass \
    --owner-approved-by "Owner Example" \
    --approved-at "$approved_at" \
    --expires-at "$expires_at"

expect_fail "embedded credentials" \
  env F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1 "$GENERATOR" \
    --manifest-out "$tmp_dir/credential-url.json" \
    --marker-out "$tmp_dir/credential-url-marker.txt" \
    --evidence-url "file://user:pass@localhost/tmp/view-only.json" \
    --pilot-device "AgentPc2" \
    --session-id "view-only-session-credential-url" \
    --recording-worm pass \
    --d10-fail-closed pass \
    --dlp-mask-policy pass \
    --local-abort pass \
    --active-indicator pass \
    --viewer-path-decision fanout-proven \
    --kvkk-attended-pilot-signoff pass \
    --owner-approved-by "Owner Example" \
    --approved-at "$approved_at" \
    --expires-at "$expires_at"

tampered_marker="${marker_body/active_indicator: pass/active_indicator: fail}"
if verify_view_only_evidence_manifest "$manifest_url" "$manifest_sha" "$tampered_marker" >/dev/null; then
  echo "expected tampered generated marker to fail verifier" >&2
  exit 1
fi

echo "view-only-evidence-package-ok"
