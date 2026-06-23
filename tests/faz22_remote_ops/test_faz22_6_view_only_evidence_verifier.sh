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

manifest="$tmp_dir/view-only-evidence.json"
cat >"$manifest" <<'JSON'
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
  "owner_approved_by": "named-owner",
  "approved_at": "2026-06-23",
  "expires_at": "2026-06-30"
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
owner_approved_by: named-owner
approved_at: 2026-06-23
expires_at: 2026-06-30
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

echo "view-only-evidence-verifier-ok"
