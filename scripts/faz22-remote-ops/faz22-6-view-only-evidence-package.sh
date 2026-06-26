#!/usr/bin/env bash
# Generate the metadata-only Faz 22.6 VIEW_ONLY ENGINEERING evidence manifest and
# matching issue marker (F22_6_VIEW_ONLY_ENGINEERING: v2) expected by
# faz22-6-completion-audit.sh.
#
# ADR-0044: this is the fail-closed ENGINEERING evidence only. It does NOT carry
# the KVKK/legal signoff (that is the separate, non-blocking
# F22_6_VIEW_ONLY_KVKK marker the DPO/owner authors). It is mode-aware:
#   --recording-mode disabled : privacy-safe MVP — no content persistence
#       (content_persistence=none) + metadata audit still active. WORM /
#       record-before-fanout / retention are NOT part of the gate in this mode.
#   --recording-mode enabled  : opt-in recording re-arms the fail-closed controls
#       (recording_worm + record_before_fanout + a parametric retention).
#
# This helper does not approve #1580 and does not publish live screen-share
# content. It only canonicalizes already-approved metadata into the fail-closed
# manifest/marker shape consumed by the audit.

set -euo pipefail

SCHEMA_VERSION="faz22.6-view-only-evidence-v2"
ACCEPTANCE_SCOPE="bounded-pilot-view-only"
PRODUCT_CHANNEL="endpoint-agent-outbound-mtls-remote-bridge"
VIEW_MODE="VIEW_ONLY"
FORBIDDEN_CLAIMS="rdp,credential-entry,raw-shell,port-forward,5-device,50-device,800-device,production,broad-rollout"
# Mode-specific negative-matrix coverage (matches the audit's required set).
# The base set machine-binds the ADR-0044 D2 engineering evidence list as
# concrete adversarial tokens (no-control invariant, mTLS+authz, TTL/revoke/kill,
# non-inert frame flow, audit metadata) in addition to the auth/device/session
# /DLP/local-abort denials.
NEGATIVE_MATRIX_BASE="no-auth,wrong-device,expired-session,dlp-deny,local-abort,no-control-attempt-denied,mtls-authz-enforced,ttl-revoke-kill,frame-flow-proven,audit-metadata-recorded"
NEGATIVE_MATRIX_DISABLED="recording-disabled-no-persistence,metadata-audit-on"
NEGATIVE_MATRIX_ENABLED="recording-down"

MANIFEST_OUT=""
MARKER_OUT=""
EVIDENCE_URL=""
PILOT_DEVICE=""
SESSION_ID=""
RECORDING_MODE=""
D10_FAIL_CLOSED=""
DLP_MASK_POLICY=""
LOCAL_ABORT=""
ACTIVE_INDICATOR=""
VIEWER_PATH_DECISION=""
RECORDING_WORM=""
RECORD_BEFORE_FANOUT=""
RECORDING_RETENTION_DAYS=""
RECORDING_RETENTION_OWNER_REF=""
OWNER_APPROVED_BY=""
APPROVED_AT=""
EXPIRES_AT=""

usage() {
  cat <<'EOF'
Usage (recording disabled — privacy-safe MVP):
  faz22-6-view-only-evidence-package.sh \
    --manifest-out PATH --marker-out PATH --evidence-url HTTPS_URL \
    --pilot-device DEVICE_OR_ID --session-id PRODUCT_SESSION_ID \
    --recording-mode disabled \
    --d10-fail-closed pass --dlp-mask-policy pass --local-abort pass \
    --active-indicator pass \
    --viewer-path-decision fanout-proven|owner-deferred \
    --owner-approved-by NAMED_OWNER --approved-at YYYY-MM-DD --expires-at YYYY-MM-DD

Usage (recording enabled — opt-in, re-arms fail-closed controls):
  faz22-6-view-only-evidence-package.sh \
    ... (all of the above with) --recording-mode enabled \
    --recording-worm pass --record-before-fanout pass \
    --recording-retention-days N --recording-retention-owner-ref REF

The manifest is metadata-only. Do not pass raw screen frames, credentials,
private endpoint identifiers, tokens, cookies, bearer strings, or private keys.
The KVKK/legal signoff is NOT generated here — it is the separate, non-blocking
F22_6_VIEW_ONLY_KVKK marker (ADR-0044).

For tests only, file:// evidence URLs are accepted when
F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1.
EOF
}

die() {
  printf 'view-only-evidence-package: %s\n' "$*" >&2
  exit 2
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

sha256_stream() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | awk '{print $1}'
    return 0
  fi
  return 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --manifest-out) [ "$#" -ge 2 ] || die "--manifest-out needs a value"; MANIFEST_OUT="$2"; shift 2 ;;
    --marker-out) [ "$#" -ge 2 ] || die "--marker-out needs a value"; MARKER_OUT="$2"; shift 2 ;;
    --evidence-url) [ "$#" -ge 2 ] || die "--evidence-url needs a value"; EVIDENCE_URL="$2"; shift 2 ;;
    --pilot-device) [ "$#" -ge 2 ] || die "--pilot-device needs a value"; PILOT_DEVICE="$2"; shift 2 ;;
    --session-id) [ "$#" -ge 2 ] || die "--session-id needs a value"; SESSION_ID="$2"; shift 2 ;;
    --recording-mode) [ "$#" -ge 2 ] || die "--recording-mode needs a value"; RECORDING_MODE="$2"; shift 2 ;;
    --d10-fail-closed) [ "$#" -ge 2 ] || die "--d10-fail-closed needs a value"; D10_FAIL_CLOSED="$2"; shift 2 ;;
    --dlp-mask-policy) [ "$#" -ge 2 ] || die "--dlp-mask-policy needs a value"; DLP_MASK_POLICY="$2"; shift 2 ;;
    --local-abort) [ "$#" -ge 2 ] || die "--local-abort needs a value"; LOCAL_ABORT="$2"; shift 2 ;;
    --active-indicator) [ "$#" -ge 2 ] || die "--active-indicator needs a value"; ACTIVE_INDICATOR="$2"; shift 2 ;;
    --viewer-path-decision) [ "$#" -ge 2 ] || die "--viewer-path-decision needs a value"; VIEWER_PATH_DECISION="$2"; shift 2 ;;
    --recording-worm) [ "$#" -ge 2 ] || die "--recording-worm needs a value"; RECORDING_WORM="$2"; shift 2 ;;
    --record-before-fanout) [ "$#" -ge 2 ] || die "--record-before-fanout needs a value"; RECORD_BEFORE_FANOUT="$2"; shift 2 ;;
    --recording-retention-days) [ "$#" -ge 2 ] || die "--recording-retention-days needs a value"; RECORDING_RETENTION_DAYS="$2"; shift 2 ;;
    --recording-retention-owner-ref) [ "$#" -ge 2 ] || die "--recording-retention-owner-ref needs a value"; RECORDING_RETENTION_OWNER_REF="$2"; shift 2 ;;
    --owner-approved-by) [ "$#" -ge 2 ] || die "--owner-approved-by needs a value"; OWNER_APPROVED_BY="$2"; shift 2 ;;
    --approved-at) [ "$#" -ge 2 ] || die "--approved-at needs a value"; APPROVED_AT="$2"; shift 2 ;;
    --expires-at) [ "$#" -ge 2 ] || die "--expires-at needs a value"; EXPIRES_AT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

need jq

require_nonempty() {
  local name="$1" value="$2"
  [ -n "$value" ] || die "$name is required"
}

require_no_control_chars() {
  local name="$1" value="$2"
  if printf '%s' "$value" | LC_ALL=C grep -q '[[:cntrl:]]'; then
    die "$name must not contain control characters"
  fi
}

require_pass() {
  local name="$1" value="$2"
  [ "$value" = "pass" ] || die "$name must be exactly 'pass'"
}

owner_is_invalid() {
  local owner_lc
  owner_lc="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [ -z "$owner_lc" ] && return 0
  case "$owner_lc" in
    tbd|none|n/a|na|placeholder|owner|named-owner) return 0 ;;
  esac
  return 1
}

valid_iso_date() {
  [[ "$1" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]
}

require_nonempty "manifest-out" "$MANIFEST_OUT"
require_nonempty "marker-out" "$MARKER_OUT"
require_nonempty "evidence-url" "$EVIDENCE_URL"
require_nonempty "pilot-device" "$PILOT_DEVICE"
require_nonempty "session-id" "$SESSION_ID"
require_nonempty "recording-mode" "$RECORDING_MODE"
require_nonempty "owner-approved-by" "$OWNER_APPROVED_BY"
require_nonempty "approved-at" "$APPROVED_AT"
require_nonempty "expires-at" "$EXPIRES_AT"

for value_name in \
  PILOT_DEVICE \
  SESSION_ID \
  OWNER_APPROVED_BY \
  EVIDENCE_URL \
  VIEWER_PATH_DECISION; do
  require_no_control_chars "$value_name" "${!value_name}"
done

case "$EVIDENCE_URL" in
  https://*) ;;
  file://*)
    [ "${F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS:-0}" = "1" ] \
      || die "evidence-url must be https://"
    ;;
  *) die "evidence-url must be https://" ;;
esac

case "$EVIDENCE_URL" in
  *\?*|*\#*) die "evidence-url must not contain query strings or fragments" ;;
  *://*@*) die "evidence-url must not contain embedded credentials" ;;
esac

require_pass "d10-fail-closed" "$D10_FAIL_CLOSED"
require_pass "dlp-mask-policy" "$DLP_MASK_POLICY"
require_pass "local-abort" "$LOCAL_ABORT"
require_pass "active-indicator" "$ACTIVE_INDICATOR"

case "$VIEWER_PATH_DECISION" in
  fanout-proven|owner-deferred) ;;
  *) die "viewer-path-decision must be fanout-proven or owner-deferred" ;;
esac

# Mode-aware required fields + negative matrix (ADR-0044 D3/D5).
case "$RECORDING_MODE" in
  disabled)
    [ -z "$RECORDING_WORM" ] || die "--recording-worm is only valid with --recording-mode enabled"
    [ -z "$RECORD_BEFORE_FANOUT" ] || die "--record-before-fanout is only valid with --recording-mode enabled"
    [ -z "$RECORDING_RETENTION_DAYS" ] || die "--recording-retention-days is only valid with --recording-mode enabled"
    [ -z "$RECORDING_RETENTION_OWNER_REF" ] || die "--recording-retention-owner-ref is only valid with --recording-mode enabled"
    AUDIT_NEGATIVE_MATRIX="$NEGATIVE_MATRIX_BASE,$NEGATIVE_MATRIX_DISABLED"
    ;;
  enabled)
    require_pass "recording-worm" "$RECORDING_WORM"
    require_pass "record-before-fanout" "$RECORD_BEFORE_FANOUT"
    [[ "$RECORDING_RETENTION_DAYS" =~ ^[1-9][0-9]*$ ]] || die "recording-retention-days must be a positive integer"
    require_nonempty "recording-retention-owner-ref" "$RECORDING_RETENTION_OWNER_REF"
    require_no_control_chars "RECORDING_RETENTION_OWNER_REF" "$RECORDING_RETENTION_OWNER_REF"
    AUDIT_NEGATIVE_MATRIX="$NEGATIVE_MATRIX_BASE,$NEGATIVE_MATRIX_ENABLED"
    ;;
  *)
    die "recording-mode must be 'disabled' or 'enabled'"
    ;;
esac

owner_is_invalid "$OWNER_APPROVED_BY" && die "owner-approved-by must be a named owner, not a placeholder"
valid_iso_date "$APPROVED_AT" || die "approved-at must be YYYY-MM-DD"
valid_iso_date "$EXPIRES_AT" || die "expires-at must be YYYY-MM-DD"

today="$(date -u +%F)"
if [[ "$APPROVED_AT" > "$EXPIRES_AT" ]]; then
  die "approved-at must not be after expires-at"
fi
if [[ "$APPROVED_AT" > "$today" ]]; then
  die "approved-at must not be in the future"
fi
if [[ "$EXPIRES_AT" < "$today" ]]; then
  die "expires-at must not be expired"
fi

manifest_parent="$(dirname "$MANIFEST_OUT")"
marker_parent="$(dirname "$MARKER_OUT")"
mkdir -p "$manifest_parent" "$marker_parent"

# Build the mode-specific JSON object fragment + marker fragment so the manifest
# and marker carry exactly the fields the audit verifier reads for that mode.
if [ "$RECORDING_MODE" = "disabled" ]; then
  mode_manifest_fragment='content_persistence: "none", metadata_audit: "active"'
  mode_marker_fragment="$(printf 'content_persistence: none\nmetadata_audit: active')"
else
  # recording_retention_unit is fixed to days; min/max bounds live in runtime
  # config (Helm values, ADR-0044 D3), not in the acceptance marker, which
  # carries only the effective value + owner decision reference.
  # shellcheck disable=SC2016 # $recording_worm etc. are jq variables (--arg), intentionally literal for the jq program built below.
  mode_manifest_fragment='recording_worm: $recording_worm, record_before_fanout: $record_before_fanout, recording_retention_days: $recording_retention_days, recording_retention_unit: "days", recording_retention_owner_ref: $recording_retention_owner_ref'
  mode_marker_fragment="$(printf 'recording_worm: %s\nrecord_before_fanout: %s\nrecording_retention_days: %s\nrecording_retention_unit: days\nrecording_retention_owner_ref: %s' \
    "$RECORDING_WORM" "$RECORD_BEFORE_FANOUT" "$RECORDING_RETENTION_DAYS" "$RECORDING_RETENTION_OWNER_REF")"
fi

canonical_manifest="$(
  jq -cnS \
    --arg schema_version "$SCHEMA_VERSION" \
    --arg acceptance_scope "$ACCEPTANCE_SCOPE" \
    --arg product_channel "$PRODUCT_CHANNEL" \
    --arg view_mode "$VIEW_MODE" \
    --arg pilot_device "$PILOT_DEVICE" \
    --arg session_id "$SESSION_ID" \
    --arg recording_mode "$RECORDING_MODE" \
    --arg d10_fail_closed "$D10_FAIL_CLOSED" \
    --arg dlp_mask_policy "$DLP_MASK_POLICY" \
    --arg local_abort "$LOCAL_ABORT" \
    --arg active_indicator "$ACTIVE_INDICATOR" \
    --arg viewer_path_decision "$VIEWER_PATH_DECISION" \
    --arg audit_negative_matrix "$AUDIT_NEGATIVE_MATRIX" \
    --arg forbidden_claims "$FORBIDDEN_CLAIMS" \
    --arg recording_worm "$RECORDING_WORM" \
    --arg record_before_fanout "$RECORD_BEFORE_FANOUT" \
    --arg recording_retention_days "$RECORDING_RETENTION_DAYS" \
    --arg recording_retention_owner_ref "$RECORDING_RETENTION_OWNER_REF" \
    --arg owner_approved_by "$OWNER_APPROVED_BY" \
    --arg approved_at "$APPROVED_AT" \
    --arg expires_at "$EXPIRES_AT" \
    "{
      schema_version: \$schema_version,
      acceptance_scope: \$acceptance_scope,
      product_channel: \$product_channel,
      view_mode: \$view_mode,
      pilot_device: \$pilot_device,
      session_id: \$session_id,
      recording_mode: \$recording_mode,
      $mode_manifest_fragment,
      d10_fail_closed: \$d10_fail_closed,
      dlp_mask_policy: \$dlp_mask_policy,
      local_abort: \$local_abort,
      active_indicator: \$active_indicator,
      viewer_path_decision: \$viewer_path_decision,
      audit_negative_matrix: (\$audit_negative_matrix | split(\",\")),
      forbidden_claims: (\$forbidden_claims | split(\",\")),
      owner_approved_by: \$owner_approved_by,
      approved_at: \$approved_at,
      expires_at: \$expires_at
    }"
)"

manifest_sha="$(printf '%s' "$canonical_manifest" | sha256_stream)" \
  || die "could not calculate manifest sha256"

printf '%s\n' "$canonical_manifest" >"$MANIFEST_OUT"

cat >"$MARKER_OUT" <<EOF
F22_6_VIEW_ONLY_ENGINEERING: v2
acceptance_scope: $ACCEPTANCE_SCOPE
product_channel: $PRODUCT_CHANNEL
view_mode: $VIEW_MODE
pilot_device: $PILOT_DEVICE
session_id: $SESSION_ID
recording_mode: $RECORDING_MODE
$mode_marker_fragment
evidence_package_url: $EVIDENCE_URL
evidence_package_sha256: $manifest_sha
d10_fail_closed: $D10_FAIL_CLOSED
dlp_mask_policy: $DLP_MASK_POLICY
local_abort: $LOCAL_ABORT
active_indicator: $ACTIVE_INDICATOR
viewer_path_decision: $VIEWER_PATH_DECISION
audit_negative_matrix: $AUDIT_NEGATIVE_MATRIX
forbidden_claims: $FORBIDDEN_CLAIMS
owner_approved_by: $OWNER_APPROVED_BY
approved_at: $APPROVED_AT
expires_at: $EXPIRES_AT
EOF

printf 'manifest=%s\n' "$MANIFEST_OUT"
printf 'marker=%s\n' "$MARKER_OUT"
printf 'recording_mode=%s\n' "$RECORDING_MODE"
printf 'evidence_package_sha256=%s\n' "$manifest_sha"
