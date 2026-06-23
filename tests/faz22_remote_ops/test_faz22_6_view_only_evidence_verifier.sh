#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

export F22_6_COMPLETION_AUDIT_SOURCE_ONLY=1
export F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1
# shellcheck source=/dev/null
source "$ROOT/scripts/faz22-remote-ops/faz22-6-completion-audit.sh"

tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
mkdir -p "$tmp_root"
tmp_dir="$(mktemp -d "$tmp_root/view-only-evidence.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

future_date_utc() {
  local days="$1"
  if date -u -d "+$days days" +%F >/dev/null 2>&1; then
    date -u -d "+$days days" +%F
    return
  fi
  date -u -v+"$days"d +%F
}

approved_at="$(date -u +%F)"
expires_at="$(future_date_utc 7)"

manifest="$tmp_dir/view-only-evidence.json"
cat >"$manifest" <<JSON
{
  "schema_version": "faz22.6-view-only-evidence-v1",
  "acceptance_scope": "bounded-pilot-view-only",
  "product_channel": "endpoint-agent-outbound-mtls-remote-bridge",
  "view_mode": "VIEW_ONLY",
  "pilot_device": "AgentPc2",
  "session_id": "view-only-session-123",
  "recording_worm": "pass",
  "d10_fail_closed": "pass",
  "dlp_mask_policy": "pass",
  "local_abort": "pass",
  "active_indicator": "pass",
  "viewer_path_decision": "fanout-proven",
  "audit_negative_matrix": [
    "no-auth",
    "wrong-device",
    "expired-session",
    "recording-down",
    "dlp-deny",
    "local-abort"
  ],
  "kvkk_attended_pilot_signoff": "pass",
  "forbidden_claims": [
    "rdp",
    "credential-entry",
    "raw-shell",
    "port-forward",
    "5-device",
    "50-device",
    "800-device",
    "production",
    "broad-rollout"
  ],
  "owner_approved_by": "Owner Example",
  "approved_at": "$approved_at",
  "expires_at": "$expires_at"
}
JSON

canonical="$(jq -cS . "$manifest")"
manifest_sha="$(printf '%s' "$canonical" | sha256_stream)"
manifest_url="file://$manifest"

marker_body="$(cat <<EOF
F22_6_VIEW_ONLY_ACCEPTANCE: v1
acceptance_scope: bounded-pilot-view-only
product_channel: endpoint-agent-outbound-mtls-remote-bridge
view_mode: VIEW_ONLY
pilot_device: AgentPc2
session_id: view-only-session-123
evidence_package_url: $manifest_url
evidence_package_sha256: $manifest_sha
recording_worm: pass
d10_fail_closed: pass
dlp_mask_policy: pass
local_abort: pass
active_indicator: pass
viewer_path_decision: fanout-proven
audit_negative_matrix: no-auth,wrong-device,expired-session,recording-down,dlp-deny,local-abort
kvkk_attended_pilot_signoff: pass
forbidden_claims: rdp,credential-entry,raw-shell,port-forward,5-device,50-device,800-device,production,broad-rollout
owner_approved_by: Owner Example
approved_at: $approved_at
expires_at: $expires_at
EOF
)"

verify_view_only_evidence_manifest "$manifest_url" "$manifest_sha" "$marker_body"

bad_sha="0000000000000000000000000000000000000000000000000000000000000000"
if verify_view_only_evidence_manifest "$manifest_url" "$bad_sha" "$marker_body" >/dev/null; then
  echo "expected checksum mismatch to fail" >&2
  exit 1
fi

if verify_view_only_evidence_manifest "$manifest_url" "$manifest_sha" "${marker_body/active_indicator: pass/active_indicator: fail}" >/dev/null; then
  echo "expected marker/manifest mismatch to fail" >&2
  exit 1
fi

if verify_view_only_evidence_manifest "$manifest_url" "$manifest_sha" "${marker_body/audit_negative_matrix: no-auth,wrong-device,expired-session,recording-down,dlp-deny,local-abort/audit_negative_matrix: no-auth,wrong-device}" >/dev/null; then
  echo "expected marker/manifest list mismatch to fail" >&2
  exit 1
fi

missing_field_manifest="$tmp_dir/view-only-evidence-missing-field.json"
jq 'del(.recording_worm)' "$manifest" >"$missing_field_manifest"
missing_field_sha="$(jq -cS . "$missing_field_manifest" | sha256_stream)"
if verify_view_only_evidence_manifest "file://$missing_field_manifest" "$missing_field_sha" "$marker_body" >/dev/null; then
  echo "expected missing manifest field to fail" >&2
  exit 1
fi

if F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=0 verify_view_only_evidence_manifest "$manifest_url" "$manifest_sha" "$marker_body" >/dev/null; then
  echo "expected non-HTTPS evidence URL to fail outside test mode" >&2
  exit 1
fi

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
  | tee "$tmp_dir/check-view-only-pass.out"

grep -q '^GATE_VIEW_ONLY_SCREEN_SHARE=pass ' "$tmp_dir/check-view-only-pass.out"
grep -q "evidence_package_sha256=$manifest_sha" "$tmp_dir/check-view-only-pass.out"

jq -n \
  --arg state "OPEN" \
  --arg body "$marker_body" \
  --arg title "fake VIEW_ONLY acceptance issue still open" \
  '{state:$state,body:$body,title:$title,url:"https://example.invalid/issues/1580"}' \
  >"$issue_json"

set +e
PATH="$fake_bin:$PATH" \
  FAKE_GH_ISSUE_JSON="$issue_json" \
  VIEW_ONLY_ACCEPTANCE_REF="Halildeu/platform-k8s-gitops#1580" \
  check_view_only_gate \
  >"$tmp_dir/check-view-only-open-issue.out"
gate_rc="$?"
set -e

if [ "$gate_rc" = "0" ]; then
  echo "expected open VIEW_ONLY acceptance issue to keep gate blocked" >&2
  exit 1
fi
grep -q '^GATE_VIEW_ONLY_SCREEN_SHARE=blocked ' "$tmp_dir/check-view-only-open-issue.out"
grep -q 'reason=issue-not-closed' "$tmp_dir/check-view-only-open-issue.out"

missing_url_body="$(printf '%s\n' "$marker_body" | grep -v '^evidence_package_url:')"
jq -n \
  --arg state "CLOSED" \
  --arg body "$missing_url_body" \
  --arg title "fake VIEW_ONLY acceptance issue missing evidence URL" \
  '{state:$state,body:$body,title:$title,url:"https://example.invalid/issues/1580"}' \
  >"$issue_json"

set +e
PATH="$fake_bin:$PATH" \
  FAKE_GH_ISSUE_JSON="$issue_json" \
  VIEW_ONLY_ACCEPTANCE_REF="Halildeu/platform-k8s-gitops#1580" \
  check_view_only_gate \
  >"$tmp_dir/check-view-only-missing-url.out"
gate_rc="$?"
set -e

if [ "$gate_rc" = "0" ]; then
  echo "expected missing evidence_package_url marker to keep gate blocked" >&2
  exit 1
fi
grep -q '^GATE_VIEW_ONLY_SCREEN_SHARE=blocked ' "$tmp_dir/check-view-only-missing-url.out"
grep -q 'reason=evidence_package_url' "$tmp_dir/check-view-only-missing-url.out"

echo "view-only-evidence-verifier-ok"
