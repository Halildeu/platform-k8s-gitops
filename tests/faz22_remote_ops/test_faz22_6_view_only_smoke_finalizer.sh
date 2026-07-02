#!/usr/bin/env bash
# VIEW_ONLY attended-smoke finalizer regression.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FINALIZER="$ROOT/scripts/faz22-remote-ops/faz22-6-view-only-smoke-finalize.sh"

export F22_6_COMPLETION_AUDIT_SOURCE_ONLY=1
export F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1
# shellcheck source=/dev/null
source "$ROOT/scripts/faz22-remote-ops/faz22-6-completion-audit.sh"

tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
mkdir -p "$tmp_root"
tmp_dir="$(mktemp -d "$tmp_root/view-only-smoke-finalizer.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

future_date_utc() {
  local days="$1"
  if date -u -d "+$days days" +%F >/dev/null 2>&1; then
    date -u -d "+$days days" +%F
    return
  fi
  date -u -v+"$days"d +%F
}

checksum_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$@"
    return
  fi
  shasum -a 256 "$@"
}

write_sha256sums() {
  local dir="$1"
  (
    cd "$dir"
    rm -f SHA256SUMS
    checksum_tmp="$(mktemp "${TMPDIR:-/tmp}/view-only-sha256sums.XXXXXX")"
    while IFS= read -r file; do
      checksum_file "$file"
    done < <(find . -maxdepth 1 -type f ! -name SHA256SUMS -print | LC_ALL=C sort | sed 's#^\./##') >"$checksum_tmp"
    mv "$checksum_tmp" SHA256SUMS
  )
}

make_smoke_dir() {
  local dir="$1" session_id="$2" consent_wait="$3" transport_pushed="$4" include_frame_signal="$5"
  mkdir -p "$dir"

  jq -n \
    --arg session_id "$session_id" \
    --arg device_id "2f7ad30f-970a-42e7-8af8-08764ae6066f" \
    --arg consent_wait "$consent_wait" \
    --argjson transport_pushed "$transport_pushed" \
    --argjson frame_signals "$include_frame_signal" \
    '{
      api: "https://testai.acik.com/api/v1",
      base: "https://testai.acik.com",
      sessionId: $session_id,
      deviceId: $device_id,
      http: {
        catalog: "200",
        open: "200",
        approve: "200",
        operation: "200",
        close: "200",
        "negative-nonpilot": "400"
      },
      consentWait: $consent_wait,
      transportPushed: $transport_pushed,
      brokerSignals: (
        ["HELLO_VERIFIED"]
        + (if $consent_wait == "granted" then ["CONSENT_GRANTED"] else ["CONSENT_DENIED"] end)
        + (if $frame_signals then ["SCREEN_VIEW","DATA","PERMIT"] else [] end)
      )
    }' >"$dir/summary.json"

  printf 'remote-bridge: consent result session="%s" granted=%s interactive_session="wts-session-1-active"\n' \
    "$session_id" \
    "$([ "$consent_wait" = "granted" ] && printf true || printf false)" \
    >"$dir/endpoint-agent-relevant.log"

  if [ "$include_frame_signal" = "true" ]; then
    printf 'broker session=%s event=CONSENT_GRANTED\nbroker session=%s event=SCREEN_VIEW frame=metadata-only\n' \
      "$session_id" "$session_id" >"$dir/broker-relevant.log"
  else
    printf 'broker session=%s event=CONSENT_GRANTED\n' "$session_id" >"$dir/broker-relevant.log"
  fi

  {
    printf '%s\t0\tPOLICY_EVENT\t{"event":"view_only_session_opened"}\n' "$session_id"
    printf '%s\t1\tPOLICY_EVENT\t{"event":"view_only_metadata_audit"}\n' "$session_id"
  } >"$dir/recording.tsv"

  write_sha256sums "$dir"
}

approved_at="$(date -u +%F)"
expires_at="$(future_date_utc 7)"

smoke_dir="$tmp_dir/smoke-success"
session_id="rb-viewonly-attended-pass"
manifest="$tmp_dir/view-only-engineering-evidence-manifest.json"
marker="$tmp_dir/view-only-engineering-marker.txt"
finalizer_summary="$tmp_dir/finalizer-summary.json"

make_smoke_dir "$smoke_dir" "$session_id" "granted" "true" "true"

F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1 "$FINALIZER" \
  --smoke-dir "$smoke_dir" \
  --manifest-out "$manifest" \
  --marker-out "$marker" \
  --finalizer-summary-out "$finalizer_summary" \
  --evidence-url "file://$manifest" \
  --owner-approved-by "Owner Example" \
  --approved-at "$approved_at" \
  --expires-at "$expires_at" \
  --viewer-path-decision owner-deferred \
  | tee "$tmp_dir/finalizer.out"

grep -q "^finalized_smoke_dir=$smoke_dir$" "$tmp_dir/finalizer.out"
grep -q '^F22_6_VIEW_ONLY_ENGINEERING: v2$' "$marker"
grep -q "^session_id: $session_id$" "$marker"
grep -q '^recording_mode: disabled$' "$marker"
grep -q '^content_persistence: none$' "$marker"
grep -q '^metadata_audit: active$' "$marker"

canonical_manifest="$(jq -cS . "$manifest")"
manifest_sha="$(printf '%s' "$canonical_manifest" | sha256_stream)"
grep -q "^evidence_package_sha256: $manifest_sha$" "$marker"
verify_view_only_evidence_manifest "file://$manifest" "$manifest_sha" "$(cat "$marker")"

jq -e \
  --arg smoke_dir "$smoke_dir" \
  --arg session_id "$session_id" \
  --arg manifest_sha "$manifest_sha" \
  '.schema_version == "faz22.6-view-only-smoke-finalizer-v1"
   and .gate == "F22_6_VIEW_ONLY_ENGINEERING"
   and .source == "attended-view-only-live-smoke"
   and .smoke_dir == $smoke_dir
   and .session_id == $session_id
   and .recording_mode == "disabled"
   and .manifest_sha256 == $manifest_sha
   and .writes_github_issues == false
   and .contains_secrets == false' \
  "$finalizer_summary" >/dev/null

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

denied_dir="$tmp_dir/smoke-consent-denied"
make_smoke_dir "$denied_dir" "rb-viewonly-attended-denied" "denied" "false" "true"
expect_fail "summary.consentWait must be granted" \
  env F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1 "$FINALIZER" \
    --smoke-dir "$denied_dir" \
    --manifest-out "$tmp_dir/denied-manifest.json" \
    --marker-out "$tmp_dir/denied-marker.txt" \
    --evidence-url "file://$tmp_dir/denied-manifest.json" \
    --owner-approved-by "Owner Example" \
    --approved-at "$approved_at" \
    --expires-at "$expires_at"

no_frame_dir="$tmp_dir/smoke-no-frame-proof"
make_smoke_dir "$no_frame_dir" "rb-viewonly-attended-no-frame" "granted" "true" "false"
expect_fail "broker evidence must prove non-inert VIEW_ONLY frame flow" \
  env F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1 "$FINALIZER" \
    --smoke-dir "$no_frame_dir" \
    --manifest-out "$tmp_dir/no-frame-manifest.json" \
    --marker-out "$tmp_dir/no-frame-marker.txt" \
    --evidence-url "file://$tmp_dir/no-frame-manifest.json" \
    --owner-approved-by "Owner Example" \
    --approved-at "$approved_at" \
    --expires-at "$expires_at"

curl_conf_dir="$tmp_dir/smoke-curl-conf"
make_smoke_dir "$curl_conf_dir" "rb-viewonly-attended-curl-conf" "granted" "true" "true"
printf 'token = "redacted"\n' >"$curl_conf_dir/request.curl.conf"
write_sha256sums "$curl_conf_dir"
expect_fail "smoke-dir still contains .*curl.conf" \
  env F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1 "$FINALIZER" \
    --smoke-dir "$curl_conf_dir" \
    --manifest-out "$tmp_dir/curl-conf-manifest.json" \
    --marker-out "$tmp_dir/curl-conf-marker.txt" \
    --evidence-url "file://$tmp_dir/curl-conf-manifest.json" \
    --owner-approved-by "Owner Example" \
    --approved-at "$approved_at" \
    --expires-at "$expires_at"

bad_checksum_dir="$tmp_dir/smoke-bad-checksum"
make_smoke_dir "$bad_checksum_dir" "rb-viewonly-attended-bad-checksum" "granted" "true" "true"
printf '\ncorruption\n' >>"$bad_checksum_dir/recording.tsv"
expect_fail "SHA256SUMS" \
  env F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1 "$FINALIZER" \
    --smoke-dir "$bad_checksum_dir" \
    --manifest-out "$tmp_dir/bad-checksum-manifest.json" \
    --marker-out "$tmp_dir/bad-checksum-marker.txt" \
    --evidence-url "file://$tmp_dir/bad-checksum-manifest.json" \
    --owner-approved-by "Owner Example" \
    --approved-at "$approved_at" \
    --expires-at "$expires_at"

echo "ok"
