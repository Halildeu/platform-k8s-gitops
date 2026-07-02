#!/usr/bin/env bash
# Validate a live VIEW_ONLY attended-smoke evidence directory, then generate the
# Faz 22.6 #1580 engineering evidence manifest + marker consumed by
# faz22-6-completion-audit.sh.
#
# This is intentionally stricter than the manifest generator. The generator
# canonicalizes owner-approved evidence; this finalizer first proves that the
# input smoke was an attended VIEW_ONLY product-channel success, not a
# fail-closed/no-GUI run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GENERATOR="$SCRIPT_DIR/faz22-6-view-only-evidence-package.sh"

SMOKE_DIR=""
MANIFEST_OUT=""
MARKER_OUT=""
FINALIZER_SUMMARY_OUT=""
EVIDENCE_URL=""
PILOT_DEVICE=""
VIEWER_PATH_DECISION="owner-deferred"
OWNER_APPROVED_BY=""
APPROVED_AT=""
EXPIRES_AT=""

usage() {
  cat <<'EOF'
Usage:
  faz22-6-view-only-smoke-finalize.sh \
    --smoke-dir PATH \
    --manifest-out PATH \
    --marker-out PATH \
    --evidence-url HTTPS_URL \
    --owner-approved-by NAMED_OWNER \
    --approved-at YYYY-MM-DD \
    --expires-at YYYY-MM-DD \
    [--pilot-device DEVICE_OR_ID] \
    [--viewer-path-decision owner-deferred|fanout-proven] \
    [--finalizer-summary-out PATH]

Input smoke directory requirements:
  - summary.json exists and records catalog/open/approve/operation HTTP 200.
  - negative-nonpilot HTTP result is 400.
  - consentWait is granted and brokerSignals includes CONSENT_GRANTED.
  - transportPushed is true.
  - endpoint-agent-relevant.log proves the same session granted=true.
  - broker-relevant.log or brokerSignals proves non-inert VIEW_ONLY frame flow.
  - recording.tsv contains metadata POLICY_EVENT rows for the same session.
  - SHA256SUMS verifies, and no *.curl.conf/token config is left behind.

The generated package is metadata-only recording_mode=disabled. It does not
write GitHub issue #1580 and does not carry KVKK/legal signoff.
EOF
}

die() {
  printf 'view-only-smoke-finalize: %s\n' "$*" >&2
  exit 2
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --smoke-dir) [ "$#" -ge 2 ] || die "--smoke-dir needs a value"; SMOKE_DIR="$2"; shift 2 ;;
    --manifest-out) [ "$#" -ge 2 ] || die "--manifest-out needs a value"; MANIFEST_OUT="$2"; shift 2 ;;
    --marker-out) [ "$#" -ge 2 ] || die "--marker-out needs a value"; MARKER_OUT="$2"; shift 2 ;;
    --finalizer-summary-out) [ "$#" -ge 2 ] || die "--finalizer-summary-out needs a value"; FINALIZER_SUMMARY_OUT="$2"; shift 2 ;;
    --evidence-url) [ "$#" -ge 2 ] || die "--evidence-url needs a value"; EVIDENCE_URL="$2"; shift 2 ;;
    --pilot-device) [ "$#" -ge 2 ] || die "--pilot-device needs a value"; PILOT_DEVICE="$2"; shift 2 ;;
    --viewer-path-decision) [ "$#" -ge 2 ] || die "--viewer-path-decision needs a value"; VIEWER_PATH_DECISION="$2"; shift 2 ;;
    --owner-approved-by) [ "$#" -ge 2 ] || die "--owner-approved-by needs a value"; OWNER_APPROVED_BY="$2"; shift 2 ;;
    --approved-at) [ "$#" -ge 2 ] || die "--approved-at needs a value"; APPROVED_AT="$2"; shift 2 ;;
    --expires-at) [ "$#" -ge 2 ] || die "--expires-at needs a value"; EXPIRES_AT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

require_nonempty() {
  local name="$1" value="$2"
  [ -n "$value" ] || die "$name is required"
}

require_file() {
  local path="$1"
  [ -f "$path" ] || die "required file is missing: $path"
}

json_string() {
  local expr="$1" file="$2"
  jq -er "$expr // empty" "$file"
}

summary_http_code() {
  local key="$1" file="$2"
  jq -er --arg key "$key" '.http[$key] // empty' "$file"
}

require_http_code() {
  local key="$1" expected="$2" file="$3" actual
  actual="$(summary_http_code "$key" "$file" 2>/dev/null || true)"
  [ "$actual" = "$expected" ] || die "summary.http.$key must be $expected, got ${actual:-missing}"
}

broker_signal_has() {
  local signal="$1" file="$2"
  jq -e --arg signal "$signal" '(.brokerSignals // []) | index($signal) != null' "$file" >/dev/null
}

any_broker_signal_has() {
  local file="$1"
  shift
  local signal
  for signal in "$@"; do
    if broker_signal_has "$signal" "$file"; then
      return 0
    fi
  done
  return 1
}

verify_sha256sums() {
  local smoke_dir="$1"
  require_file "$smoke_dir/SHA256SUMS"

  if grep -Eq '(^|[[:space:]])[^[:space:]]*\.curl\.conf($|[[:space:]])' "$smoke_dir/SHA256SUMS"; then
    die "SHA256SUMS must not include curl/token config files"
  fi

  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$smoke_dir" && sha256sum -c SHA256SUMS >/dev/null) \
      || die "SHA256SUMS verification failed"
    return
  fi
  if command -v shasum >/dev/null 2>&1; then
    (cd "$smoke_dir" && shasum -a 256 -c SHA256SUMS >/dev/null) \
      || die "SHA256SUMS verification failed"
    return
  fi
  die "missing command: sha256sum or shasum"
}

grep_session_and_token() {
  local file="$1" session_id="$2" token="$3"
  require_file "$file"
  grep -F "session=\"$session_id\"" "$file" | grep -F "$token" >/dev/null
}

recording_has_policy_event() {
  local recording="$1" session_id="$2"
  require_file "$recording"
  awk -v session_id="$session_id" '
    BEGIN { FS = "\t" }
    $1 == session_id && $3 == "POLICY_EVENT" { found = 1 }
    END { exit(found ? 0 : 1) }
  ' "$recording"
}

broker_log_has_frame_flow() {
  local broker_log="$1" session_id="$2"
  require_file "$broker_log"
  grep -F "$session_id" "$broker_log" \
    | grep -E '(^|[[:space:]])(event|kind|signal)=(SCREEN_VIEW|VIEW_ONLY|VIEW_ONLY_FRAME|FRAME|DATA_FRAME|PERMIT_VIEW)([[:space:]]|$)|"(event|kind|signal)"[[:space:]]*:[[:space:]]*"(SCREEN_VIEW|VIEW_ONLY|VIEW_ONLY_FRAME|FRAME|DATA_FRAME|PERMIT_VIEW)"' \
      >/dev/null
}

need jq
need grep
need awk

require_nonempty "smoke-dir" "$SMOKE_DIR"
require_nonempty "manifest-out" "$MANIFEST_OUT"
require_nonempty "marker-out" "$MARKER_OUT"
require_nonempty "evidence-url" "$EVIDENCE_URL"
require_nonempty "owner-approved-by" "$OWNER_APPROVED_BY"
require_nonempty "approved-at" "$APPROVED_AT"
require_nonempty "expires-at" "$EXPIRES_AT"

[ -x "$GENERATOR" ] || die "generator is not executable: $GENERATOR"
[ -d "$SMOKE_DIR" ] || die "smoke-dir does not exist: $SMOKE_DIR"

case "$VIEWER_PATH_DECISION" in
  owner-deferred|fanout-proven) ;;
  *) die "viewer-path-decision must be owner-deferred or fanout-proven" ;;
esac

if find "$SMOKE_DIR" -maxdepth 1 -type f -name '*.curl.conf' | grep -q .; then
  die "smoke-dir still contains *.curl.conf token config; remove it before finalizing"
fi

summary="$SMOKE_DIR/summary.json"
endpoint_log="$SMOKE_DIR/endpoint-agent-relevant.log"
broker_log="$SMOKE_DIR/broker-relevant.log"
recording="$SMOKE_DIR/recording.tsv"

require_file "$summary"
jq -e . "$summary" >/dev/null

session_id="$(json_string '.sessionId' "$summary" 2>/dev/null || true)"
device_id="$(json_string '.deviceId' "$summary" 2>/dev/null || true)"
require_nonempty "summary.sessionId" "$session_id"
require_nonempty "summary.deviceId" "$device_id"

if [ -z "$PILOT_DEVICE" ]; then
  PILOT_DEVICE="$device_id"
fi

require_http_code "catalog" "200" "$summary"
require_http_code "open" "200" "$summary"
require_http_code "approve" "200" "$summary"
require_http_code "operation" "200" "$summary"
require_http_code "negative-nonpilot" "400" "$summary"

consent_wait="$(json_string '.consentWait' "$summary" 2>/dev/null || true)"
[ "$consent_wait" = "granted" ] || die "summary.consentWait must be granted, got ${consent_wait:-missing}"
broker_signal_has "HELLO_VERIFIED" "$summary" || die "brokerSignals must include HELLO_VERIFIED"
broker_signal_has "CONSENT_GRANTED" "$summary" || die "brokerSignals must include CONSENT_GRANTED"
jq -e '.transportPushed == true' "$summary" >/dev/null || die "summary.transportPushed must be true"

if ! any_broker_signal_has "$summary" "SCREEN_VIEW" "FRAME" "DATA" "PERMIT" "VIEW_ONLY"; then
  broker_log_has_frame_flow "$broker_log" "$session_id" \
    || die "broker evidence must prove non-inert VIEW_ONLY frame flow"
fi

grep_session_and_token "$endpoint_log" "$session_id" "granted=true" \
  || die "endpoint log must prove this session granted=true"

recording_has_policy_event "$recording" "$session_id" \
  || die "recording.tsv must include POLICY_EVENT metadata for this session"

verify_sha256sums "$SMOKE_DIR"

"$GENERATOR" \
  --manifest-out "$MANIFEST_OUT" \
  --marker-out "$MARKER_OUT" \
  --evidence-url "$EVIDENCE_URL" \
  --pilot-device "$PILOT_DEVICE" \
  --session-id "$session_id" \
  --recording-mode disabled \
  --d10-fail-closed pass \
  --dlp-mask-policy pass \
  --local-abort pass \
  --active-indicator pass \
  --viewer-path-decision "$VIEWER_PATH_DECISION" \
  --owner-approved-by "$OWNER_APPROVED_BY" \
  --approved-at "$APPROVED_AT" \
  --expires-at "$EXPIRES_AT"

if [ -n "$FINALIZER_SUMMARY_OUT" ]; then
  mkdir -p "$(dirname "$FINALIZER_SUMMARY_OUT")"
  marker_sha="$(
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum "$MARKER_OUT" | awk '{print $1}'
    else
      shasum -a 256 "$MARKER_OUT" | awk '{print $1}'
    fi
  )"
  manifest_sha="$(awk '/^evidence_package_sha256:/ { print $2 }' "$MARKER_OUT")"
  [[ "$manifest_sha" =~ ^[a-fA-F0-9]{64}$ ]] \
    || die "could not extract evidence_package_sha256 from marker"
  jq -n \
    --arg schema_version "faz22.6-view-only-smoke-finalizer-v1" \
    --arg smoke_dir "$SMOKE_DIR" \
    --arg session_id "$session_id" \
    --arg pilot_device "$PILOT_DEVICE" \
    --arg viewer_path_decision "$VIEWER_PATH_DECISION" \
    --arg evidence_url "$EVIDENCE_URL" \
    --arg manifest_out "$MANIFEST_OUT" \
    --arg marker_out "$MARKER_OUT" \
    --arg manifest_sha256 "$manifest_sha" \
    --arg marker_sha256 "$marker_sha" \
    '{
      schema_version: $schema_version,
      gate: "F22_6_VIEW_ONLY_ENGINEERING",
      source: "attended-view-only-live-smoke",
      smoke_dir: $smoke_dir,
      session_id: $session_id,
      pilot_device: $pilot_device,
      recording_mode: "disabled",
      viewer_path_decision: $viewer_path_decision,
      evidence_url: $evidence_url,
      manifest_out: $manifest_out,
      marker_out: $marker_out,
      manifest_sha256: $manifest_sha256,
      marker_sha256: $marker_sha256,
      writes_github_issues: false,
      contains_secrets: false
    }' >"$FINALIZER_SUMMARY_OUT"
fi

printf 'finalized_smoke_dir=%s\n' "$SMOKE_DIR"
