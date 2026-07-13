#!/usr/bin/env bash
# ADR-0044 v2: VIEW_ONLY ENGINEERING evidence verifier + engineering gate guard.
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

# ---------------------------------------------------------------------------
# recording_mode=disabled (privacy-safe MVP) — hand-built manifest + marker.
# ---------------------------------------------------------------------------
manifest="$tmp_dir/view-only-evidence.json"
cat >"$manifest" <<JSON
{
  "schema_version": "faz22.6-view-only-evidence-v2",
  "acceptance_scope": "bounded-pilot-view-only",
  "product_channel": "endpoint-agent-outbound-mtls-remote-bridge",
  "view_mode": "VIEW_ONLY",
  "pilot_device": "AgentPc2",
  "session_id": "view-only-session-123",
  "recording_mode": "disabled",
  "content_persistence": "none",
  "metadata_audit": "active",
  "d10_fail_closed": "pass",
  "dlp_mask_policy": "pass",
  "local_abort": "pass",
  "active_indicator": "pass",
  "viewer_path_decision": "fanout-proven",
  "audit_negative_matrix": [
    "no-auth",
    "wrong-device",
    "expired-session",
    "dlp-deny",
    "local-abort",
    "no-control-attempt-denied",
    "mtls-authz-enforced",
    "ttl-revoke-kill",
    "frame-flow-proven",
    "audit-metadata-recorded",
    "recording-disabled-no-persistence",
    "metadata-audit-on"
  ],
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
F22_6_VIEW_ONLY_ENGINEERING: v2
acceptance_scope: bounded-pilot-view-only
product_channel: endpoint-agent-outbound-mtls-remote-bridge
view_mode: VIEW_ONLY
pilot_device: AgentPc2
session_id: view-only-session-123
recording_mode: disabled
content_persistence: none
metadata_audit: active
evidence_package_url: $manifest_url
evidence_package_sha256: $manifest_sha
d10_fail_closed: pass
dlp_mask_policy: pass
local_abort: pass
active_indicator: pass
viewer_path_decision: fanout-proven
audit_negative_matrix: no-auth,wrong-device,expired-session,dlp-deny,local-abort,no-control-attempt-denied,mtls-authz-enforced,ttl-revoke-kill,frame-flow-proven,audit-metadata-recorded,recording-disabled-no-persistence,metadata-audit-on
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

if verify_view_only_evidence_manifest "$manifest_url" "$manifest_sha" "${marker_body/audit_negative_matrix: no-auth,wrong-device,expired-session,dlp-deny,local-abort,no-control-attempt-denied,mtls-authz-enforced,ttl-revoke-kill,frame-flow-proven,audit-metadata-recorded,recording-disabled-no-persistence,metadata-audit-on/audit_negative_matrix: no-auth,wrong-device}" >/dev/null; then
  echo "expected marker/manifest list mismatch to fail" >&2
  exit 1
fi

# A disabled-mode manifest that asserts recording_worm=pass is an untested
# privacy claim and must be rejected (ADR-0044 D5).
worm_when_disabled_manifest="$tmp_dir/view-only-worm-when-disabled.json"
jq '. + {recording_worm:"pass"}' "$manifest" >"$worm_when_disabled_manifest"
worm_when_disabled_sha="$(jq -cS . "$worm_when_disabled_manifest" | sha256_stream)"
worm_when_disabled_marker="$(printf '%s\nrecording_worm: pass\n' "$marker_body")"
if verify_view_only_evidence_manifest "file://$worm_when_disabled_manifest" "$worm_when_disabled_sha" "$worm_when_disabled_marker" >/dev/null; then
  echo "expected recording_worm=pass under recording_mode=disabled to fail" >&2
  exit 1
fi

# Any OTHER enabled-only field in a disabled manifest must also be rejected.
rbf_when_disabled_manifest="$tmp_dir/view-only-rbf-when-disabled.json"
jq '. + {record_before_fanout:"pass"}' "$manifest" >"$rbf_when_disabled_manifest"
rbf_when_disabled_sha="$(jq -cS . "$rbf_when_disabled_manifest" | sha256_stream)"
rbf_when_disabled_marker="$(printf '%s\nrecord_before_fanout: pass\n' "$marker_body")"
if verify_view_only_evidence_manifest "file://$rbf_when_disabled_manifest" "$rbf_when_disabled_sha" "$rbf_when_disabled_marker" >/dev/null; then
  echo "expected record_before_fanout under recording_mode=disabled to fail" >&2
  exit 1
fi

missing_field_manifest="$tmp_dir/view-only-evidence-missing-field.json"
jq 'del(.content_persistence)' "$manifest" >"$missing_field_manifest"
missing_field_sha="$(jq -cS . "$missing_field_manifest" | sha256_stream)"
if verify_view_only_evidence_manifest "file://$missing_field_manifest" "$missing_field_sha" "$marker_body" >/dev/null; then
  echo "expected missing manifest field to fail" >&2
  exit 1
fi

if F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=0 verify_view_only_evidence_manifest "$manifest_url" "$manifest_sha" "$marker_body" >/dev/null; then
  echo "expected non-HTTPS evidence URL to fail outside test mode" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# recording_mode=enabled — re-arms WORM + record-before-fanout + retention.
# ---------------------------------------------------------------------------
enabled_manifest="$tmp_dir/view-only-evidence-enabled.json"
cat >"$enabled_manifest" <<JSON
{
  "schema_version": "faz22.6-view-only-evidence-v2",
  "acceptance_scope": "bounded-pilot-view-only",
  "product_channel": "endpoint-agent-outbound-mtls-remote-bridge",
  "view_mode": "VIEW_ONLY",
  "pilot_device": "AgentPc2",
  "session_id": "view-only-session-enabled",
  "recording_mode": "enabled",
  "recording_worm": "pass",
  "record_before_fanout": "pass",
  "recording_retention_days": "30",
  "recording_retention_unit": "days",
  "recording_retention_owner_ref": "issue#1580-dpo",
  "d10_fail_closed": "pass",
  "dlp_mask_policy": "pass",
  "local_abort": "pass",
  "active_indicator": "pass",
  "viewer_path_decision": "owner-deferred",
  "audit_negative_matrix": [
    "no-auth",
    "wrong-device",
    "expired-session",
    "dlp-deny",
    "local-abort",
    "no-control-attempt-denied",
    "mtls-authz-enforced",
    "ttl-revoke-kill",
    "frame-flow-proven",
    "audit-metadata-recorded",
    "recording-down"
  ],
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

enabled_canonical="$(jq -cS . "$enabled_manifest")"
enabled_sha="$(printf '%s' "$enabled_canonical" | sha256_stream)"
enabled_url="file://$enabled_manifest"
enabled_marker_body="$(cat <<EOF
F22_6_VIEW_ONLY_ENGINEERING: v2
acceptance_scope: bounded-pilot-view-only
product_channel: endpoint-agent-outbound-mtls-remote-bridge
view_mode: VIEW_ONLY
pilot_device: AgentPc2
session_id: view-only-session-enabled
recording_mode: enabled
recording_worm: pass
record_before_fanout: pass
recording_retention_days: 30
recording_retention_unit: days
recording_retention_owner_ref: issue#1580-dpo
evidence_package_url: $enabled_url
evidence_package_sha256: $enabled_sha
d10_fail_closed: pass
dlp_mask_policy: pass
local_abort: pass
active_indicator: pass
viewer_path_decision: owner-deferred
audit_negative_matrix: no-auth,wrong-device,expired-session,dlp-deny,local-abort,no-control-attempt-denied,mtls-authz-enforced,ttl-revoke-kill,frame-flow-proven,audit-metadata-recorded,recording-down
forbidden_claims: rdp,credential-entry,raw-shell,port-forward,5-device,50-device,800-device,production,broad-rollout
owner_approved_by: Owner Example
approved_at: $approved_at
expires_at: $expires_at
EOF
)"
verify_view_only_evidence_manifest "$enabled_url" "$enabled_sha" "$enabled_marker_body"

# enabled mode missing record_before_fanout must fail.
enabled_missing_rbf="$tmp_dir/view-only-enabled-missing-rbf.json"
jq 'del(.record_before_fanout)' "$enabled_manifest" >"$enabled_missing_rbf"
enabled_missing_rbf_sha="$(jq -cS . "$enabled_missing_rbf" | sha256_stream)"
if verify_view_only_evidence_manifest "file://$enabled_missing_rbf" "$enabled_missing_rbf_sha" "$enabled_marker_body" >/dev/null; then
  echo "expected enabled mode missing record_before_fanout to fail" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Engineering gate (check_view_only_engineering_gate) via fake gh.
# ---------------------------------------------------------------------------
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
write_issue() { # write_issue <state> <body>
  jq -n --arg state "$1" --arg body "$2" --arg title "fake VIEW_ONLY issue" \
    '{state:$state,body:$body,title:$title,url:"https://example.invalid/issues/1580"}' >"$issue_json"
}
run_eng_gate() {
  PATH="$fake_bin:$PATH" FAKE_GH_ISSUE_JSON="$issue_json" \
    VIEW_ONLY_ACCEPTANCE_REF="Halildeu/platform-k8s-gitops#1580" \
    check_view_only_engineering_gate
}

write_issue CLOSED "$marker_body"
run_eng_gate | tee "$tmp_dir/eng-pass.out"
grep -q '^GATE_VIEW_ONLY_ENGINEERING=pass ' "$tmp_dir/eng-pass.out"
grep -q "recording_mode=disabled" "$tmp_dir/eng-pass.out"

write_issue OPEN "$marker_body"
set +e
run_eng_gate >"$tmp_dir/eng-open.out"; rc="$?"
set -e
[ "$rc" != "0" ] || { echo "expected open issue blocked" >&2; exit 1; }
grep -q '^GATE_VIEW_ONLY_ENGINEERING=blocked ' "$tmp_dir/eng-open.out"
grep -q 'reason=issue-not-closed' "$tmp_dir/eng-open.out"

missing_url_body="$(printf '%s\n' "$marker_body" | grep -v '^evidence_package_url:')"
write_issue CLOSED "$missing_url_body"
set +e
run_eng_gate >"$tmp_dir/eng-missing-url.out"; rc="$?"
set -e
[ "$rc" != "0" ] || { echo "expected missing url blocked" >&2; exit 1; }
grep -q 'reason=evidence_package_url' "$tmp_dir/eng-missing-url.out"

# Legacy fail-safe: an old bundled F22_6_VIEW_ONLY_ACCEPTANCE must NOT pass.
legacy_body="$(printf 'F22_6_VIEW_ONLY_ACCEPTANCE: v1\nacceptance_scope: bounded-pilot-view-only\nowner_approved_by: Owner Example\n')"
write_issue CLOSED "$legacy_body"
set +e
run_eng_gate >"$tmp_dir/eng-legacy.out"; rc="$?"
set -e
[ "$rc" != "0" ] || { echo "expected legacy bundled marker blocked" >&2; exit 1; }
grep -q 'reason=legacy_bundled_marker_detected' "$tmp_dir/eng-legacy.out"

echo "view-only-evidence-verifier-ok"
