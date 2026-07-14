#!/usr/bin/env bash
# Collect the #2373 negative matrix from one protected, attended VIEW_ONLY session.
# Raw SSE/frame bytes are streamed through a hasher and are never persisted.

set -euo pipefail

required=(
  MATRIX_OPERATOR_BASE MATRIX_MANAGEMENT_BASE MATRIX_SESSION_ID MATRIX_STREAM_ID
  MATRIX_DEVICE_ID MATRIX_OPERATOR_TOKEN_FILE MATRIX_OPERATOR_CLAIMS_FILE
  MATRIX_WRONG_ROLE_TOKEN_FILE MATRIX_WRONG_ROLE_CLAIMS_FILE
  MATRIX_WRONG_TENANT_TOKEN_FILE MATRIX_WRONG_TENANT_CLAIMS_FILE
  MATRIX_SOURCE_REVISION MATRIX_AUTHORIZATION_SHA256 MATRIX_OUTPUT_DIR
)
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || { echo "negative-matrix: missing $name" >&2; exit 2; }
done

[[ "$MATRIX_SOURCE_REVISION" =~ ^[a-f0-9]{40}$ ]]
[[ "$MATRIX_AUTHORIZATION_SHA256" =~ ^sha256:[a-f0-9]{64}$ ]]
[[ "$MATRIX_SESSION_ID" =~ ^[A-Za-z0-9._:-]+$ ]]
[[ "$MATRIX_STREAM_ID" =~ ^[A-Za-z0-9_-]{1,128}$ ]]

TMP_DIR="$(mktemp -d)"
SSE_CURL_PID=""
SSE_HASH_PID=""
cleanup() {
  set +e
  [[ -n "$SSE_CURL_PID" ]] && kill "$SSE_CURL_PID" >/dev/null 2>&1
  [[ -n "$SSE_HASH_PID" ]] && kill "$SSE_HASH_PID" >/dev/null 2>&1
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$MATRIX_OUTPUT_DIR/observations"
CASES_DIR="$TMP_DIR/cases"
mkdir -p "$CASES_DIR"

sha256_text() {
  printf '%s' "$1" | sha256sum | awk '{print "sha256:" $1}'
}

sha256_file() {
  sha256sum "$1" | awk '{print "sha256:" $1}'
}

metric_value() {
  local metric="$1" raw="$TMP_DIR/metrics.prom"
  curl -fsS --max-time 10 "$MATRIX_MANAGEMENT_BASE/actuator/prometheus" -o "$raw"
  python3 - "$raw" "$metric" <<'PY'
import sys

path, metric = sys.argv[1:]
total = 0.0
with open(path, encoding="utf-8") as source:
    for line in source:
        if line.startswith("#"):
            continue
        name, *rest = line.split()
        if rest and (name == metric or name.startswith(metric + "{")):
            total += float(rest[0])
print(int(total))
PY
}

wait_metric_gt() {
  local metric="$1" before="$2" current
  for _ in $(seq 1 30); do
    current="$(metric_value "$metric")"
    if (( current > before )); then
      printf '%s' "$current"
      return 0
    fi
    sleep 1
  done
  echo "negative-matrix: metric did not advance: $metric" >&2
  return 1
}

curl_probe() {
  local method="$1" url="$2" token_file="$3" output="$4" body="${5:-}"
  local args=(
    --silent --show-error --max-time 25 --request "$method"
    --header 'Content-Type: application/json' --output "$output" --write-out '%{http_code}'
  )
  if [[ -n "$body" ]]; then
    printf '%s' "$body" > "${output}.request"
    args+=(--data-binary "@${output}.request")
  fi
  if [[ -n "$token_file" ]]; then
    printf 'header = "Authorization: Bearer %s"\n' "$(tr -d '\r\n' < "$token_file")" \
      | curl --config - "${args[@]}" "$url"
  else
    curl "${args[@]}" "$url"
  fi
}

request_json() {
  local method="$1" target="$2" credential="$3" subject="$4" tenant="$5" role="$6"
  local path_template="$7" body_sha="$8"
  jq -nc \
    --arg method "$method" --arg target "$target" --arg credential "$credential" \
    --arg subject "$subject" --arg tenant "$tenant" --argjson role "$role" \
    --arg pathTemplate "$path_template" --arg bodySha256 "$body_sha" '
      {method:$method,targetClass:$target,credentialClass:$credential,
       subjectSha256:(if $subject == "null" then null else $subject end),
       tenantSha256:(if $tenant == "null" then null else $tenant end),rolePresent:$role,
       pathTemplate:$pathTemplate,
       bodySha256:(if $bodySha256 == "null" then null else $bodySha256 end)}'
}

record_case() {
  local case_name="$1" binding="$2" request="$3" status="$4" body_class="$5"
  local body_length="$6" body_sha="$7" frames_before="$8" frames_after="$9"
  shift 9
  local rejected_before="$1" rejected_after="$2" deny_required="$3"
  local deny_observed="$4" deny_code="$5" evidence_source="$6"
  local request_started="$7" request_completed="$8" metrics_before_at="$9"
  local metrics_after_at="${10}"
  local observed_at
  observed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  jq -cS -n \
    --arg schemaVersion 'faz22.6.viewOnlyViewerNegativeRuntimeSnapshot.v1' \
    --arg caseName "$case_name" --arg sourceRevision "$MATRIX_SOURCE_REVISION" \
    --arg observedAt "$observed_at" --argjson binding "$binding" \
    --argjson request "$request" --argjson httpStatus "$status" \
    --arg bodyClass "$body_class" --argjson bodyLength "$body_length" \
    --arg bodySha256 "$body_sha" --argjson framesBefore "$frames_before" \
    --argjson framesAfter "$frames_after" --argjson viewerRejectedBefore "$rejected_before" \
    --argjson viewerRejectedAfter "$rejected_after" --argjson required "$deny_required" \
    --argjson observed "$deny_observed" --arg code "$deny_code" \
    --arg evidenceSource "$evidence_source" \
    --arg requestStarted "$request_started" --arg requestCompleted "$request_completed" \
    --arg metricsBeforeAt "$metrics_before_at" --arg metricsAfterAt "$metrics_after_at" '
      {schemaVersion:$schemaVersion,caseName:$caseName,sourceRevision:$sourceRevision,
       observedAt:$observedAt,binding:$binding,
       request:($request + {startedAt:$requestStarted,completedAt:$requestCompleted}),
       response:{httpStatus:$httpStatus,bodyClass:$bodyClass,bodyLength:$bodyLength,
                 bodySha256:$bodySha256,screenContentPersisted:false,
                 artifactRepresentation:"hash-and-length-only"},
       delivery:{framesBefore:$framesBefore,framesAfter:$framesAfter,streamClosed:true,
                 viewerRejectedBefore:$viewerRejectedBefore,
                 viewerRejectedAfter:$viewerRejectedAfter,
                 metricsBeforeObservedAt:$metricsBeforeAt,
                 metricsAfterObservedAt:$metricsAfterAt},
       agentDeny:{required:$required,observed:$observed,
                  code:(if $code == "null" then null else $code end)},
       evidenceSource:$evidenceSource}' > "$CASES_DIR/$case_name.json"
}

ROOT_BINDING="$(jq -nc \
  --arg sessionSha256 "$(sha256_text "$MATRIX_SESSION_ID")" \
  --arg tenantSha256 "$(jq -r '.tenantSha256' "$MATRIX_OPERATOR_CLAIMS_FILE")" \
  --arg operatorSha256 "$(jq -r '.subjectSha256' "$MATRIX_OPERATOR_CLAIMS_FILE")" \
  --arg deviceSha256 "$(sha256_text "$MATRIX_DEVICE_ID")" \
  '{sessionSha256:$sessionSha256,tenantSha256:$tenantSha256,
    operatorSha256:$operatorSha256,deviceSha256:$deviceSha256}')"
OPERATOR_SUBJECT="$(jq -r '.subjectSha256' "$MATRIX_OPERATOR_CLAIMS_FILE")"
OPERATOR_TENANT="$(jq -r '.tenantSha256' "$MATRIX_OPERATOR_CLAIMS_FILE")"
WRONG_ROLE_SUBJECT="$(jq -r '.subjectSha256' "$MATRIX_WRONG_ROLE_CLAIMS_FILE")"
WRONG_ROLE_TENANT="$(jq -r '.tenantSha256' "$MATRIX_WRONG_ROLE_CLAIMS_FILE")"
WRONG_TENANT_SUBJECT="$(jq -r '.subjectSha256' "$MATRIX_WRONG_TENANT_CLAIMS_FILE")"
WRONG_TENANT_TENANT="$(jq -r '.tenantSha256' "$MATRIX_WRONG_TENANT_CLAIMS_FILE")"
VIEW_URL="$MATRIX_OPERATOR_BASE/sessions/$MATRIX_SESSION_ID/view?streamId=$MATRIX_STREAM_ID"
VIEW_PATH_TEMPLATE='/internal/remote-bridge/operator/sessions/{session}/view?streamId={stream}'
SESSION_OPEN_PATH_TEMPLATE='/internal/remote-bridge/operator/sessions'
FRAMES_METRIC='remote_access_bridge_viewer_frames_sent_total'
REJECTED_METRIC='remote_access_bridge_viewer_rejected_total'
STARTED_METRIC='remote_access_bridge_viewer_started_total'
ENDED_METRIC='remote_access_bridge_viewer_ended_total'

run_simple_case() {
  local case_name="$1" method="$2" url="$3" token_file="$4" expected="$5"
  local request="$6" binding="$7" source="$8" body_class="${9:-empty-or-opaque}"
  local request_body="${10:-}"
  local body="$TMP_DIR/$case_name.body" frames_before frames_after rejected_before rejected_after code
  local metrics_before_at metrics_after_at request_started request_completed
  metrics_before_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  frames_before="$(metric_value "$FRAMES_METRIC")"
  rejected_before="$(metric_value "$REJECTED_METRIC")"
  request_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  code="$(curl_probe "$method" "$url" "$token_file" "$body" "$request_body")"
  request_completed="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  [[ "$code" == "$expected" ]] || { echo "$case_name expected $expected got $code" >&2; return 1; }
  frames_after="$(metric_value "$FRAMES_METRIC")"
  rejected_after="$(metric_value "$REJECTED_METRIC")"
  metrics_after_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  record_case "$case_name" "$binding" "$request" "$code" "$body_class" \
    "$(wc -c < "$body" | tr -d ' ')" "$(sha256_file "$body")" \
    "$frames_before" "$frames_after" "$rejected_before" "$rejected_after" \
    false false null "$source" "$request_started" "$request_completed" \
    "$metrics_before_at" "$metrics_after_at"
}

run_simple_case noAuth GET "$VIEW_URL" '' 401 \
  "$(request_json GET viewer-product-channel absent null null false "$VIEW_PATH_TEMPLATE" null)" \
  "$ROOT_BINDING" viewer-http-and-metric-probe
run_simple_case wrongRole GET "$VIEW_URL" "$MATRIX_WRONG_ROLE_TOKEN_FILE" 401 \
  "$(request_json GET viewer-product-channel authenticated-wrong-role \
    "$WRONG_ROLE_SUBJECT" "$WRONG_ROLE_TENANT" false "$VIEW_PATH_TEMPLATE" null)" \
  "$ROOT_BINDING" viewer-http-and-metric-probe
run_simple_case wrongTenant GET "$VIEW_URL" "$MATRIX_WRONG_TENANT_TOKEN_FILE" 404 \
  "$(request_json GET viewer-product-channel authenticated-wrong-tenant \
    "$WRONG_TENANT_SUBJECT" "$WRONG_TENANT_TENANT" true "$VIEW_PATH_TEMPLATE" null)" \
  "$ROOT_BINDING" viewer-http-and-metric-probe

WRONG_DEVICE_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
WRONG_SESSION_ID="${MATRIX_SESSION_ID}-wrong-device"
WRONG_DEVICE_BINDING="$(jq -nc \
  --arg sessionSha256 "$(sha256_text "$WRONG_SESSION_ID")" \
  --arg tenantSha256 "$OPERATOR_TENANT" --arg operatorSha256 "$OPERATOR_SUBJECT" \
  --arg deviceSha256 "$(sha256_text "$WRONG_DEVICE_ID")" \
  '{sessionSha256:$sessionSha256,tenantSha256:$tenantSha256,
    operatorSha256:$operatorSha256,deviceSha256:$deviceSha256}')"
WRONG_DEVICE_BODY="$(jq -nc --arg session "$WRONG_SESSION_ID" --arg device "$WRONG_DEVICE_ID" \
  '{sessionId:$session,deviceId:$device,reason:"Faz 22.6 wrong-device fail-closed probe",capabilities:["VIEW_ONLY"]}')"
run_simple_case wrongDevice POST "$MATRIX_OPERATOR_BASE/sessions" "$MATRIX_OPERATOR_TOKEN_FILE" 404 \
  "$(request_json POST operator-session-open-channel authenticated-wrong-device \
    "$OPERATOR_SUBJECT" "$OPERATOR_TENANT" true "$SESSION_OPEN_PATH_TEMPLATE" \
    "$(sha256_text "$WRONG_DEVICE_BODY")")" \
  "$WRONG_DEVICE_BINDING" operator-session-open-http-probe empty-or-opaque "$WRONG_DEVICE_BODY"

run_agent_deny_case() {
  local case_name="$1" suffix="$2" expected_code="$3" outcome_credential="$4"
  local body="$TMP_DIR/$case_name.body" before_frames after_frames before_rejected after_rejected code
  local metrics_before_at metrics_after_at request_started request_completed path_template
  metrics_before_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  before_frames="$(metric_value "$FRAMES_METRIC")"
  before_rejected="$(metric_value "$REJECTED_METRIC")"
  request_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  code="$(curl_probe POST "$MATRIX_OPERATOR_BASE/sessions/$MATRIX_SESSION_ID/negative-probes/$suffix" \
    "$MATRIX_OPERATOR_TOKEN_FILE" "$body")"
  request_completed="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  [[ "$code" == 422 ]]
  [[ "$(jq -r '.kind' "$body")" == DENY ]]
  [[ "$(jq -r '.agentErrorCode' "$body")" == "$expected_code" ]]
  after_frames="$(metric_value "$FRAMES_METRIC")"
  after_rejected="$(metric_value "$REJECTED_METRIC")"
  metrics_after_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  path_template="/internal/remote-bridge/operator/sessions/{session}/negative-probes/$suffix"
  record_case "$case_name" "$ROOT_BINDING" \
    "$(request_json POST agent-permit-channel "$outcome_credential" \
      "$OPERATOR_SUBJECT" "$OPERATOR_TENANT" true "$path_template" "$(sha256_text '')")" \
    422 agent-deny-redacted "$(wc -c < "$body" | tr -d ' ')" "$(sha256_file "$body")" \
    "$before_frames" "$after_frames" "$before_rejected" "$after_rejected" \
    true true "$expected_code" agent-error-ledger-and-http-probe \
    "$request_started" "$request_completed" "$metrics_before_at" "$metrics_after_at"
}
run_agent_deny_case expired expired-permit operation-dispatch-failed:permit-invalid expired-permit
run_agent_deny_case replayed replay operation-dispatch-failed:seq-replay replayed-permit

# Hold the authorized 1:1 viewer slot. Screen bytes pass only through a FIFO to
# the streaming hasher; neither the SSE body nor base64 frame content reaches disk.
SSE_FIFO="$TMP_DIR/viewer.fifo"
SSE_SUMMARY="$TMP_DIR/viewer-stream-summary.json"
mkfifo "$SSE_FIFO"
python3 - "$SSE_FIFO" "$SSE_SUMMARY" <<'PY' &
import hashlib
import json
import sys

fifo, output = sys.argv[1:]
digest = hashlib.sha256()
length = 0
with open(fifo, "rb", buffering=0) as source:
    while True:
        chunk = source.read(65536)
        if not chunk:
            break
        length += len(chunk)
        digest.update(chunk)
with open(output, "w", encoding="utf-8") as target:
    json.dump({"bodyLength": length, "bodySha256": "sha256:" + digest.hexdigest()}, target)
    target.write("\n")
PY
SSE_HASH_PID="$!"
started_before="$(metric_value "$STARTED_METRIC")"
ended_before="$(metric_value "$ENDED_METRIC")"
frames_at_start="$(metric_value "$FRAMES_METRIC")"
stream_request_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
curl --config <(printf 'header = "Authorization: Bearer %s"\n' \
  "$(tr -d '\r\n' < "$MATRIX_OPERATOR_TOKEN_FILE")") \
  --silent --show-error --no-buffer --max-time 90 --output "$SSE_FIFO" \
  --write-out '%{http_code}' "$VIEW_URL" > "$TMP_DIR/viewer-stream.code" &
SSE_CURL_PID="$!"
wait_metric_gt "$STARTED_METRIC" "$started_before" >/dev/null
wait_metric_gt "$FRAMES_METRIC" "$frames_at_start" >/dev/null

# The second authorized viewer is rejected while the first slot is live. Its
# own response carries zero frames even if the admitted first stream advances.
over_body="$TMP_DIR/overConcurrency.body"
over_metrics_before_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
over_rejected_before="$(metric_value "$REJECTED_METRIC")"
over_request_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
over_code="$(curl_probe GET "$VIEW_URL" "$MATRIX_OPERATOR_TOKEN_FILE" "$over_body")"
over_request_completed="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
[[ "$over_code" == 409 ]]
over_rejected_after="$(metric_value "$REJECTED_METRIC")"
over_metrics_after_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
record_case overConcurrency "$ROOT_BINDING" \
  "$(request_json GET viewer-product-channel authorized-second-viewer \
    "$OPERATOR_SUBJECT" "$OPERATOR_TENANT" true "$VIEW_PATH_TEMPLATE" null)" \
  409 empty-or-opaque "$(wc -c < "$over_body" | tr -d ' ')" "$(sha256_file "$over_body")" \
  0 0 "$over_rejected_before" "$over_rejected_after" false false null \
  viewer-http-and-metric-probe "$over_request_started" "$over_request_completed" \
  "$over_metrics_before_at" "$over_metrics_after_at"

disconnect_rejected="$(metric_value "$REJECTED_METRIC")"
kill "$SSE_CURL_PID" >/dev/null 2>&1 || true
wait "$SSE_CURL_PID" >/dev/null 2>&1 || true
stream_request_completed="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
SSE_CURL_PID=""
wait "$SSE_HASH_PID"
SSE_HASH_PID=""
wait_metric_gt "$ENDED_METRIC" "$ended_before" >/dev/null
stream_metrics_before_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
disconnect_end_frames="$(metric_value "$FRAMES_METRIC")"
sleep 2
disconnect_after_frames="$(metric_value "$FRAMES_METRIC")"
disconnect_rejected_after="$(metric_value "$REJECTED_METRIC")"
stream_metrics_after_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
record_case disconnectedViewer "$ROOT_BINDING" \
  "$(request_json GET viewer-product-channel authorized-disconnected-viewer \
    "$OPERATOR_SUBJECT" "$OPERATOR_TENANT" true "$VIEW_PATH_TEMPLATE" null)" \
  null stream-content-digested-no-persistence \
  "$(jq -r '.bodyLength' "$SSE_SUMMARY")" "$(jq -r '.bodySha256' "$SSE_SUMMARY")" \
  "$disconnect_end_frames" "$disconnect_after_frames" "$disconnect_rejected" \
  "$disconnect_rejected_after" false false null viewer-http-and-metric-probe \
  "$stream_request_started" "$stream_request_completed" \
  "$stream_metrics_before_at" "$stream_metrics_after_at"

close_body="$TMP_DIR/close.body"
close_code="$(curl_probe POST "$MATRIX_OPERATOR_BASE/sessions/$MATRIX_SESSION_ID/close" \
  "$MATRIX_OPERATOR_TOKEN_FILE" "$close_body")"
[[ "$close_code" == 200 || "$close_code" == 204 ]]
printf '%s\n' "$close_code" > "$MATRIX_OUTPUT_DIR/close.code"
run_simple_case revoked GET "$VIEW_URL" "$MATRIX_OPERATOR_TOKEN_FILE" 404 \
  "$(request_json GET viewer-product-channel revoked-session \
    "$OPERATOR_SUBJECT" "$OPERATOR_TENANT" true "$VIEW_PATH_TEMPLATE" null)" \
  "$ROOT_BINDING" viewer-http-and-metric-probe

OBSERVATIONS="$MATRIX_OUTPUT_DIR/observations/negative.jsonl"
python3 - "$CASES_DIR" "$OBSERVATIONS" <<'PY'
import json
import pathlib
import sys

source, output = map(pathlib.Path, sys.argv[1:])
order = (
    "noAuth", "wrongRole", "wrongTenant", "wrongDevice", "expired",
    "revoked", "replayed", "overConcurrency", "disconnectedViewer",
)
with output.open("wb") as target:
    for name in order:
        value = json.loads((source / f"{name}.json").read_text(encoding="utf-8"))
        target.write(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
PY

jq -cS -n \
  --arg schemaVersion 'faz22.6.viewOnlyViewerMatrixCollectorContext.v1' \
  --arg evidenceType negative --arg sourceRevision "$MATRIX_SOURCE_REVISION" \
  --arg collectedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg authorizationSha256 "$MATRIX_AUTHORIZATION_SHA256" \
  --argjson rootBinding "$ROOT_BINDING" \
  --arg observationsSha256 "$(sha256_file "$OBSERVATIONS")" '
    {schemaVersion:$schemaVersion,evidenceType:$evidenceType,sourceRevision:$sourceRevision,
     collectedAt:$collectedAt,authorizationSha256:$authorizationSha256,
     rootBinding:$rootBinding,observationsSha256:$observationsSha256,auditSha256:null}' \
  > "$MATRIX_OUTPUT_DIR/context.json"

chmod 0600 "$MATRIX_OUTPUT_DIR/context.json" "$OBSERVATIONS" "$MATRIX_OUTPUT_DIR/close.code"
echo "negative_matrix=pass cases=9 raw_screen_persisted=false"
