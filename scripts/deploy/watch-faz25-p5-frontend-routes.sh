#!/usr/bin/env bash
set -euo pipefail

# Run-scoped, fail-closed route monitor for the protected Faz 25 P5 browser
# journey.  The browser workflow starts this process before Playwright and
# waits for its signed-off report after the browser exits.  A Kubernetes watch
# begins at the resourceVersion of the validated baseline list.  Any Ingress
# event during the browser window fails closed; the 250 ms full-list polls are
# a second projection-integrity check, not the sole TOCTOU control.

: "${REPORT_PATH:?REPORT_PATH is required}"
: "${STOP_PATH:?STOP_PATH is required}"
: "${READY_PATH:?READY_PATH is required}"
: "${EXPECTED_INGRESS_UID:?EXPECTED_INGRESS_UID is required}"
: "${BROWSER_REPORT_PATH:?BROWSER_REPORT_PATH is required}"

EXPECTED_CONTEXT="${EXPECTED_CONTEXT:-k3d-test}"
ROUTE_VALIDATOR="${ROUTE_VALIDATOR:-scripts/deploy/verify-faz25-p5-frontend-routes.py}"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-0.25}"
INTERVAL_MILLISECONDS="${INTERVAL_MILLISECONDS:-250}"
INGRESS_LIST_PATH="/apis/networking.k8s.io/v1/ingresses"

[[ "$EXPECTED_CONTEXT" == "k3d-test" ]]
[[ "$EXPECTED_INGRESS_UID" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$ ]]
[[ "$INTERVAL_MILLISECONDS" == "250" ]]
[[ -f "$ROUTE_VALIDATOR" && ! -L "$ROUTE_VALIDATOR" ]]
[[ ! -e "$REPORT_PATH" && ! -L "$REPORT_PATH" ]]
[[ ! -e "$STOP_PATH" && ! -L "$STOP_PATH" ]]
[[ ! -e "$READY_PATH" && ! -L "$READY_PATH" ]]
[[ ! -L "$BROWSER_REPORT_PATH" ]]
[[ -d "$(dirname "$REPORT_PATH")" && ! -L "$(dirname "$REPORT_PATH")" ]]
[[ -d "$(dirname "$STOP_PATH")" && ! -L "$(dirname "$STOP_PATH")" ]]
[[ -d "$(dirname "$READY_PATH")" && ! -L "$(dirname "$READY_PATH")" ]]

umask 077
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
observed_at="$started_at"
sample_count=0
violation_count=0
projection_sha256=""
event_watch_established=false
event_watch_resource_version=""
final_resource_version=""
event_count=0
browser_asset_path_count=0
browser_asset_paths_sha256=""
event_watch_pid=""
event_watch_output=""
event_watch_error=""
event_watch_error_sha256=""
baseline_payload=""

cleanup() {
  if [[ -n "$event_watch_pid" ]] && kill -0 "$event_watch_pid" 2>/dev/null; then
    kill "$event_watch_pid" 2>/dev/null || true
    wait "$event_watch_pid" 2>/dev/null || true
  fi
  [[ -z "$event_watch_output" ]] || rm -f -- "$event_watch_output"
  [[ -z "$event_watch_error" ]] || rm -f -- "$event_watch_error"
  [[ -z "$baseline_payload" ]] || rm -f -- "$baseline_payload"
}
trap cleanup EXIT INT TERM

sha256_text() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  else
    shasum -a 256 | awk '{print $1}'
  fi
}

list_all_ingresses() {
  local payload
  if ! payload="$(
    "$KUBECTL_BIN" --context "$EXPECTED_CONTEXT" get --raw "$INGRESS_LIST_PATH"
  )"; then
    return 1
  fi
  # A route-integrity snapshot must cover the complete collection.  The raw
  # request omits limit, but still reject any server-provided continuation
  # token instead of accepting a partial list if server behavior changes.
  jq -e '(.metadata.continue // "") == ""' <<<"$payload" >/dev/null || return 1
  printf '%s\n' "$payload"
}

write_report() {
  local verdict="$1"
  local failure_reason="$2"
  local temporary_report
  temporary_report="$(mktemp "$(dirname "$REPORT_PATH")/.route-watch-XXXXXX")"
  jq -n \
    --arg verdict "$verdict" \
    --arg failure_reason "$failure_reason" \
    --arg started_at "$started_at" \
    --arg observed_at "$observed_at" \
    --arg ingress_uid "$EXPECTED_INGRESS_UID" \
    --arg projection_sha256 "$projection_sha256" \
    --arg event_watch_resource_version "$event_watch_resource_version" \
    --arg event_watch_error_sha256 "$event_watch_error_sha256" \
    --arg final_resource_version "$final_resource_version" \
    --arg browser_asset_paths_sha256 "$browser_asset_paths_sha256" \
    --argjson sample_count "$sample_count" \
    --argjson violation_count "$violation_count" \
    --argjson event_watch_established "$event_watch_established" \
    --argjson event_count "$event_count" \
    --argjson browser_asset_path_count "$browser_asset_path_count" \
    --argjson interval_milliseconds "$INTERVAL_MILLISECONDS" '
      {
        schemaVersion: "faz25-p5-continuous-route-watch-v2",
        verdict: $verdict,
        failureReason: $failure_reason,
        startedAt: $started_at,
        observedAt: $observed_at,
        target: {
          context: "k3d-test",
          host: "testai.acik.com",
          canonicalIngress: {
            namespace: "platform-test",
            name: "platform",
            uid: $ingress_uid
          }
        },
        intervalMilliseconds: $interval_milliseconds,
        sampleCount: $sample_count,
        violationCount: $violation_count,
        eventWatchMode: "KUBERNETES_RESOURCE_VERSION_STREAM",
        eventWatchEstablished: $event_watch_established,
        eventWatchResourceVersion: $event_watch_resource_version,
        eventWatchErrorSha256: $event_watch_error_sha256,
        finalResourceVersion: $final_resource_version,
        eventCount: $event_count,
        browserAssetPathCount: $browser_asset_path_count,
        browserAssetPathsSha256: $browser_asset_paths_sha256,
        routeProjectionSha256s:
          (if $projection_sha256 == "" then [] else [$projection_sha256] end)
      }
    ' > "$temporary_report"
  chmod 0600 "$temporary_report"
  mv -f -- "$temporary_report" "$REPORT_PATH"
}

record_event_count() {
  if [[ -n "$event_watch_output" && -s "$event_watch_output" ]]; then
    event_count="$(jq -s 'length' "$event_watch_output" 2>/dev/null || true)"
    if [[ ! "$event_count" =~ ^[0-9]+$ || "$event_count" -lt 1 ]]; then
      event_count=1
    fi
  else
    event_count=0
  fi
}

record_event_watch_error() {
  if [[ -n "$event_watch_error" && -s "$event_watch_error" ]]; then
    event_watch_error_sha256="$(sha256_text < "$event_watch_error")"
  else
    event_watch_error_sha256=""
  fi
}

fail_event_observed() {
  if jq -e -s 'any(.[]; .type == "ERROR")' \
      "$event_watch_output" >/dev/null 2>&1; then
    fail route-event-watch-error
  fi
  fail route-event-observed
}

fail() {
  local reason="$1"
  record_event_count
  record_event_watch_error
  violation_count=$((violation_count + 1))
  write_report FAIL "$reason"
  : > "$READY_PATH"
  chmod 0600 "$READY_PATH"
  exit 1
}

baseline_payload="$(mktemp "$(dirname "$REPORT_PATH")/.route-baseline-XXXXXX")"
validator_error="$(mktemp "$(dirname "$REPORT_PATH")/.route-validator-XXXXXX")"
if ! list_all_ingresses > "$baseline_payload" 2>"$validator_error"; then
  rm -f -- "$validator_error"
  fail route-policy-or-collection-failure
fi
projection=""
if ! projection="$(python3 "$ROUTE_VALIDATOR" --ingress-uid "$EXPECTED_INGRESS_UID" \
    < "$baseline_payload" 2>"$validator_error")"; then
  rm -f -- "$validator_error"
  fail route-policy-or-collection-failure
fi
rm -f -- "$validator_error"
event_watch_resource_version="$(jq -er '
  .metadata.resourceVersion
  | select(type == "string" and test("^[0-9]+$"))
' "$baseline_payload" 2>/dev/null || true)"
if [[ -z "$event_watch_resource_version" ]]; then
  fail missing-list-resource-version
fi

projection_sha256="$(printf '%s\n' "$projection" | sha256_text)"
sample_count=1
event_watch_output="$(mktemp "$(dirname "$REPORT_PATH")/.route-events-XXXXXX")"
event_watch_error="$(mktemp "$(dirname "$REPORT_PATH")/.route-events-error-XXXXXX")"
ingress_watch_path="${INGRESS_LIST_PATH}?watch=true&allowWatchBookmarks=false&resourceVersion=${event_watch_resource_version}"
"$KUBECTL_BIN" --context "$EXPECTED_CONTEXT" get --raw "$ingress_watch_path" \
  > "$event_watch_output" 2> "$event_watch_error" &
event_watch_pid=$!

# Give immediate auth/configuration failures time to surface before declaring
# the protected browser window ready.
sleep "$INTERVAL_SECONDS"
if ! kill -0 "$event_watch_pid" 2>/dev/null; then
  wait "$event_watch_pid" 2>/dev/null || true
  event_watch_pid=""
  fail route-event-watch-terminated
fi
record_event_count
if [[ "$event_count" -ne 0 ]]; then
  fail_event_observed
fi
if [[ -s "$event_watch_error" ]]; then
  fail route-event-watch-stderr-observed
fi
event_watch_established=true
: > "$READY_PATH"
chmod 0600 "$READY_PATH"

while [[ ! -e "$STOP_PATH" ]]; do
  if ! kill -0 "$event_watch_pid" 2>/dev/null; then
    wait "$event_watch_pid" 2>/dev/null || true
    event_watch_pid=""
    fail route-event-watch-terminated
  fi
  record_event_count
  if [[ "$event_count" -ne 0 ]]; then
    fail_event_observed
  fi
  if [[ -s "$event_watch_error" ]]; then
    fail route-event-watch-stderr-observed
  fi

  observed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  validator_error="$(mktemp "$(dirname "$REPORT_PATH")/.route-validator-XXXXXX")"
  projection=""
  if ! projection="$(list_all_ingresses | \
      python3 "$ROUTE_VALIDATOR" --ingress-uid "$EXPECTED_INGRESS_UID" \
        2>"$validator_error")"; then
    rm -f -- "$validator_error"
    fail route-policy-or-collection-failure
  fi
  rm -f -- "$validator_error"

  current_sha256="$(printf '%s\n' "$projection" | sha256_text)"
  if [[ -z "$projection_sha256" ]]; then
    projection_sha256="$current_sha256"
  elif [[ "$current_sha256" != "$projection_sha256" ]]; then
    fail route-projection-changed
  fi

  sample_count=$((sample_count + 1))
  sleep "$INTERVAL_SECONDS"
done

record_event_count
if [[ "$event_count" -ne 0 ]]; then
  fail_event_observed
fi
if [[ -s "$event_watch_error" ]]; then
  fail route-event-watch-stderr-observed
fi
if ! kill -0 "$event_watch_pid" 2>/dev/null; then
  wait "$event_watch_pid" 2>/dev/null || true
  event_watch_pid=""
  fail route-event-watch-terminated
fi
if [[ "$sample_count" -lt 2 ]]; then
  fail insufficient-continuous-samples
fi

if [[ ! -f "$BROWSER_REPORT_PATH" ]]; then
  fail browser-route-path-evidence-missing
fi
browser_path_count="$(jq -er '.runtime.frontendAssetPaths | length' \
  "$BROWSER_REPORT_PATH" 2>/dev/null || true)"
if [[ ! "$browser_path_count" =~ ^[0-9]+$ || "$browser_path_count" -lt 1 ]]; then
  fail browser-route-path-evidence-missing
fi
browser_asset_path_count="$browser_path_count"
browser_asset_paths_sha256="$(jq -cS '.runtime.frontendAssetPaths' \
  "$BROWSER_REPORT_PATH" | sha256_text)"
browser_paths=()
while IFS= read -r browser_path; do
  browser_paths+=("$browser_path")
done < <(jq -er '
  .runtime.frontendAssetPaths[]
  | select(
      type == "string" and
      test("^/(?:[A-Za-z0-9_-][A-Za-z0-9._-]*/)*[A-Za-z0-9_-][A-Za-z0-9._-]*\\.(js|mjs|css)$")
    )
' "$BROWSER_REPORT_PATH")
if [[ "${#browser_paths[@]}" -ne "$browser_path_count" ]]; then
  fail browser-route-path-evidence-missing
fi
dynamic_route_args=()
for browser_path in "${browser_paths[@]}"; do
  dynamic_route_args+=(--additional-request-path "$browser_path")
done
final_payload="$(mktemp "$(dirname "$REPORT_PATH")/.route-final-XXXXXX")"
validator_error="$(mktemp "$(dirname "$REPORT_PATH")/.route-validator-XXXXXX")"
if ! list_all_ingresses > "$final_payload" 2>"$validator_error" || \
   ! python3 "$ROUTE_VALIDATOR" --ingress-uid "$EXPECTED_INGRESS_UID" \
      "${dynamic_route_args[@]}" < "$final_payload" >/dev/null 2>"$validator_error"; then
  rm -f -- "$final_payload" "$validator_error"
  fail browser-asset-route-policy-failure
fi
final_resource_version="$(jq -er '
  .metadata.resourceVersion
  | select(type == "string" and test("^[0-9]+$"))
' "$final_payload" 2>/dev/null || true)"
if [[ -z "$final_resource_version" ]]; then
  rm -f -- "$final_payload" "$validator_error"
  fail missing-list-resource-version
fi
if [[ "$final_resource_version" != "$event_watch_resource_version" ]]; then
  rm -f -- "$final_payload" "$validator_error"
  fail route-resource-version-changed
fi
rm -f -- "$final_payload" "$validator_error"

# Keep the resourceVersion stream alive through exact browser-asset route
# validation.  The final list resourceVersion must equal the baseline, so an
# asset-specific route that existed during browsing and disappeared before
# this snapshot cannot evade the evidence window.
record_event_count
if [[ "$event_count" -ne 0 ]]; then
  fail_event_observed
fi
if [[ -s "$event_watch_error" ]]; then
  fail route-event-watch-stderr-observed
fi
if ! kill -0 "$event_watch_pid" 2>/dev/null; then
  wait "$event_watch_pid" 2>/dev/null || true
  event_watch_pid=""
  fail route-event-watch-terminated
fi
observed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
kill "$event_watch_pid" 2>/dev/null || true
wait "$event_watch_pid" 2>/dev/null || true
event_watch_pid=""
record_event_count
if [[ "$event_count" -ne 0 ]]; then
  fail_event_observed
fi
record_event_watch_error
if [[ -n "$event_watch_error_sha256" ]]; then
  fail route-event-watch-stderr-observed
fi

write_report PASS ""
