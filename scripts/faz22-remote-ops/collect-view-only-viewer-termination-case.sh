#!/usr/bin/env bash
# Collect one real #2373 termination case from an isolated attended VIEW_ONLY session.
# Viewer bytes go directly to /dev/null. Uploaded output contains only canonical,
# identifier-hashed JSON/JSONL evidence.

set -euo pipefail

required=(
  MATRIX_OPERATOR_BASE MATRIX_MANAGEMENT_BASE MATRIX_SESSION_ID MATRIX_STREAM_ID
  MATRIX_DEVICE_ID MATRIX_OPERATOR_TOKEN_FILE MATRIX_OPERATOR_CLAIMS_FILE
  MATRIX_SOURCE_REVISION MATRIX_AUTHORIZATION_SHA256 MATRIX_OUTPUT_DIR
  MATRIX_TERMINATION_CASE MATRIX_K8S_CONTEXT MATRIX_K8S_NAMESPACE
  MATRIX_REMOTE_BRIDGE_DEPLOYMENT MATRIX_TENANT_ID MATRIX_PG_CONTAINER
  MATRIX_PG_DATABASE MATRIX_PG_USER MATRIX_DB_SCHEMA
)
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || { echo "termination-matrix: missing $name" >&2; exit 2; }
done

case "$MATRIX_TERMINATION_CASE" in
  localAbort|killOrRevoke|ttlExpiry|heartbeatLoss|indicatorLoss) ;;
  *) echo "termination-matrix: invalid case" >&2; exit 2 ;;
esac
[[ "$MATRIX_SOURCE_REVISION" =~ ^[a-f0-9]{40}$ ]]
[[ "$MATRIX_AUTHORIZATION_SHA256" =~ ^sha256:[a-f0-9]{64}$ ]]
[[ "$MATRIX_SESSION_ID" =~ ^[A-Za-z0-9._:-]{1,160}$ ]]
[[ "$MATRIX_STREAM_ID" =~ ^[A-Za-z0-9_-]{1,128}$ ]]
[[ "$MATRIX_TENANT_ID" =~ ^[0-9a-fA-F-]{36}$ ]]
[[ "$MATRIX_DB_SCHEMA" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
TMP_DIR="$(mktemp -d)"
VIEWER_PID=""
cleanup() {
  set +e
  [[ -n "$VIEWER_PID" ]] && kill "$VIEWER_PID" >/dev/null 2>&1
  [[ -n "$VIEWER_PID" ]] && wait "$VIEWER_PID" >/dev/null 2>&1
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$MATRIX_OUTPUT_DIR/observations" "$MATRIX_OUTPUT_DIR/audit"

sha256_text() {
  printf '%s' "$1" | sha256sum | awk '{print "sha256:" $1}'
}

epoch_millis() {
  python3 -c 'import time; print(time.time_ns() // 1_000_000)'
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
  local metric="$1" before="$2" timeout_seconds="$3" current
  for _ in $(seq 1 "$timeout_seconds"); do
    current="$(metric_value "$metric")"
    if (( current > before )); then
      printf '%s' "$current"
      return 0
    fi
    sleep 1
  done
  echo "termination-matrix: metric did not advance: $metric" >&2
  return 1
}

operator_post() {
  local path="$1" output="$2"
  printf 'header = "Authorization: Bearer %s"\n' \
    "$(tr -d '\r\n' < "$MATRIX_OPERATOR_TOKEN_FILE")" \
    | curl --config - --silent --show-error --max-time 190 --request POST \
        --output "$output" --write-out '%{http_code}' \
        "$MATRIX_OPERATOR_BASE$path"
}

collect_broker_log() {
  kubectl --context "$MATRIX_K8S_CONTEXT" -n "$MATRIX_K8S_NAMESPACE" \
    logs "deploy/$MATRIX_REMOTE_BRIDGE_DEPLOYMENT" --since=35m --tail=30000 --timestamps=true \
    2>"$TMP_DIR/broker.stderr" \
    | grep -F "$MATRIX_SESSION_ID" > "$TMP_DIR/broker-session.log" || true
}

broker_pattern_epoch_millis() {
  local pattern="$1"
  collect_broker_log
  python3 - "$TMP_DIR/broker-session.log" "$pattern" <<'PY'
from datetime import datetime
import sys

path, pattern = sys.argv[1:]
timestamps = []
with open(path, encoding="utf-8") as source:
    for line in source:
        if pattern not in line:
            continue
        token = line.split(maxsplit=1)[0]
        try:
            instant = datetime.fromisoformat(token.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SystemExit("termination-matrix: broker log timestamp is invalid") from exc
        timestamps.append(int(instant.timestamp() * 1000))
if len(timestamps) != 1:
    raise SystemExit("termination-matrix: exactly one timestamped broker trigger is required")
print(timestamps[0])
PY
}

wait_broker_patterns() {
  local timeout_seconds="$1"
  shift
  for _ in $(seq 1 "$timeout_seconds"); do
    collect_broker_log
    local all=true pattern
    for pattern in "$@"; do
      if ! grep -F "$pattern" "$TMP_DIR/broker-session.log" >/dev/null 2>&1; then
        all=false
        break
      fi
    done
    [[ "$all" == true ]] && return 0
    sleep 1
  done
  echo "termination-matrix: broker patterns not observed for $MATRIX_TERMINATION_CASE" >&2
  return 1
}

psql_jsonl() {
  local sql="$1" output="$2"
  command -v docker >/dev/null 2>&1
  docker inspect "$MATRIX_PG_CONTAINER" >/dev/null 2>&1
  printf '%s\n' "$sql" \
    | docker exec -i "$MATRIX_PG_CONTAINER" psql \
        -U "$MATRIX_PG_USER" -d "$MATRIX_PG_DATABASE" -At -v ON_ERROR_STOP=1 \
        -v tenant_id="$MATRIX_TENANT_ID" -v chain_id="$MATRIX_SESSION_ID" -f - \
    > "$output"
}

ROOT_BINDING="$TMP_DIR/binding.json"
jq -n \
  --arg sessionSha256 "$(sha256_text "$MATRIX_SESSION_ID")" \
  --arg tenantSha256 "$(jq -r '.tenantSha256' "$MATRIX_OPERATOR_CLAIMS_FILE")" \
  --arg operatorSha256 "$(jq -r '.subjectSha256' "$MATRIX_OPERATOR_CLAIMS_FILE")" \
  --arg deviceSha256 "$(sha256_text "$MATRIX_DEVICE_ID")" \
  '{sessionSha256:$sessionSha256,tenantSha256:$tenantSha256,
    operatorSha256:$operatorSha256,deviceSha256:$deviceSha256}' > "$ROOT_BINDING"
jq -e '[.[]] | length == 4 and (unique | length == 4)
  and all(.[]; test("^sha256:[a-f0-9]{64}$"))' "$ROOT_BINDING" >/dev/null

FRAMES_METRIC=remote_access_bridge_viewer_frames_sent_total
STARTED_METRIC=remote_access_bridge_viewer_started_total
ENDED_METRIC=remote_access_bridge_viewer_ended_total
AUDIT_FAILURE_METRIC=remote_access_bridge_operator_kill_ack_audit_failure_latched
VIEW_URL="$MATRIX_OPERATOR_BASE/sessions/$MATRIX_SESSION_ID/view?streamId=$MATRIX_STREAM_ID"

started_before="$(metric_value "$STARTED_METRIC")"
ended_before="$(metric_value "$ENDED_METRIC")"
printf 'header = "Authorization: Bearer %s"\n' \
  "$(tr -d '\r\n' < "$MATRIX_OPERATOR_TOKEN_FILE")" \
  | curl --config - --silent --show-error --no-buffer --max-time 240 \
      --output /dev/null "$VIEW_URL" &
VIEWER_PID="$!"
wait_metric_gt "$STARTED_METRIC" "$started_before" 30 >/dev/null
frames_before="$(metric_value "$FRAMES_METRIC")"
wait_metric_gt "$FRAMES_METRIC" "$frames_before" 30 >/dev/null

triggered_at=""
trigger_name=""
case "$MATRIX_TERMINATION_CASE" in
  killOrRevoke)
    trigger_name=kill-or-revoke
    [[ "$(metric_value "$AUDIT_FAILURE_METRIC")" == 0 ]]
    triggered_at="$(epoch_millis)"
    close_code="$(operator_post "/sessions/$MATRIX_SESSION_ID/close" "$TMP_DIR/close.body")"
    [[ "$close_code" == 204 ]]
    ;;
  heartbeatLoss)
    trigger_name=heartbeat-loss
    triggered_at="$(epoch_millis)"
    probe_code="$(operator_post "/sessions/$MATRIX_SESSION_ID/termination-probes/heartbeat-loss" \
      "$TMP_DIR/heartbeat-loss.body")"
    [[ "$probe_code" == 200 ]]
    jq -e '.kind == "TERMINATED" and .reason == "control-stream-loss-terminal-observed"
      and .terminalState == "KILLED" and (.probeId | type == "string" and length > 0)' \
      "$TMP_DIR/heartbeat-loss.body" >/dev/null
    wait_broker_patterns 20 'KILLED:control-stream-lost'
    ;;
  ttlExpiry)
    trigger_name=ttl-expiry
    wait_broker_patterns 180 'AGENT_ERROR:screen-view-permit-expired:retryable=false'
    triggered_at="$(broker_pattern_epoch_millis 'AGENT_ERROR:screen-view-permit-expired:retryable=false')"
    wait_broker_patterns 20 'KILLED:screen-view-permit-expired'
    ;;
  localAbort)
    trigger_name=local-abort
    echo "OPERATOR_ACTION_REQUIRED case=localAbort session=$MATRIX_SESSION_ID action=click_visible_endpoint_END_button" >&2
    wait_broker_patterns 180 'AGENT:LOCAL_ABORT'
    triggered_at="$(broker_pattern_epoch_millis 'AGENT:LOCAL_ABORT')"
    wait_broker_patterns 20 'KILLED:local-abort'
    ;;
  indicatorLoss)
    trigger_name=indicator-loss
    echo "OPERATOR_ACTION_REQUIRED case=indicatorLoss session=$MATRIX_SESSION_ID action=run_protected_indicator_loss_trigger" >&2
    wait_broker_patterns 180 'AGENT:AGENT_INDICATOR_LOST'
    triggered_at="$(broker_pattern_epoch_millis 'AGENT:AGENT_INDICATOR_LOST')"
    wait_broker_patterns 20 'KILLED:indicator-lost'
    ;;
esac
[[ "$triggered_at" =~ ^[1-9][0-9]{12}$ ]]

ended_after="$(wait_metric_gt "$ENDED_METRIC" "$ended_before" 180)"
[[ "$ended_after" == "$((ended_before + 1))" ]]
delivery_ended_at="$(epoch_millis)"
frames_at_end="$(metric_value "$FRAMES_METRIC")"
sleep 3
frames_after_end="$(metric_value "$FRAMES_METRIC")"
[[ "$frames_after_end" == "$frames_at_end" ]]
if [[ "$MATRIX_TERMINATION_CASE" == killOrRevoke ]]; then
  wait_broker_patterns 20 'AGENT:AGENT_KILL_APPLIED'
  [[ "$(metric_value "$AUDIT_FAILURE_METRIC")" == 0 ]]
fi

tenant_chain="$TMP_DIR/tenant-audit-chain.jsonl"
recording_chain="$TMP_DIR/session-recording-chain.jsonl"
tenant_sql="
SELECT jsonb_build_object(
  'id', id::text, 'tenant_id', tenant_id::text,
  'device_id', CASE WHEN device_id IS NULL THEN NULL ELSE device_id::text END,
  'command_id', CASE WHEN command_id IS NULL THEN NULL ELSE command_id::text END,
  'event_type', event_type, 'action', action,
  'performed_by_subject', performed_by_subject, 'correlation_id', correlation_id,
  'metadata', metadata, 'before_state', before_state, 'after_state', after_state,
  'occurred_at', to_char(occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),
  'prev_event_hash', prev_event_hash, 'event_hash', event_hash,
  'event_hash_alg', event_hash_alg, 'event_hash_version', event_hash_version
)::text
FROM ${MATRIX_DB_SCHEMA}.endpoint_audit_events
WHERE tenant_id = :'tenant_id'::uuid AND event_hash IS NOT NULL
ORDER BY occurred_at ASC, id ASC;"
recording_sql="
SELECT jsonb_build_object(
  'chainId', chain_id, 'seq', seq, 'timestampMillis', timestamp_millis,
  'kind', kind, 'contentHash', content_hash, 'previousHash', previous_hash,
  'entryHash', entry_hash
)::text
FROM ${MATRIX_DB_SCHEMA}.session_recording_entry
WHERE chain_id = :'chain_id'
ORDER BY seq;"

for _ in $(seq 1 30); do
  psql_jsonl "$tenant_sql" "$tenant_chain"
  psql_jsonl "$recording_sql" "$recording_chain"
  if grep -F '"action": "VIEW_STOP"' "$tenant_chain" >/dev/null 2>&1 \
      && [[ -s "$recording_chain" ]]; then
    break
  fi
  sleep 1
done
[[ -s "$tenant_chain" && -s "$recording_chain" ]]

observed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
audit_record="$MATRIX_OUTPUT_DIR/audit/${MATRIX_TERMINATION_CASE}.json"
MATRIX_SESSION_ID="$MATRIX_SESSION_ID" python3 \
  "$SCRIPT_DIR/build-view-only-viewer-termination-audit.py" \
  --tenant-audit-chain "$tenant_chain" \
  --session-recording-chain "$recording_chain" \
  --case "$MATRIX_TERMINATION_CASE" \
  --binding-json "$ROOT_BINDING" \
  --source-revision "$MATRIX_SOURCE_REVISION" \
  --observed-at "$observed_at" \
  --output "$audit_record"

collect_broker_log
broker_frames_delivered="$(python3 - "$TMP_DIR/broker-session.log" <<'PY'
import re
import sys

matches = []
for line in open(sys.argv[1], encoding="utf-8"):
    if "viewer stream END" not in line:
        continue
    match = re.search(r"framesDelivered=(\d+)", line)
    if match:
        matches.append(int(match.group(1)))
if len(matches) != 1:
    raise SystemExit("termination-matrix: exactly one session-bound viewer END count is required")
print(matches[0])
PY
)"
audit_frames_delivered="$(jq -r '.framesDelivered' "$audit_record")"
[[ "$audit_frames_delivered" =~ ^[1-9][0-9]*$ ]]
[[ "$broker_frames_delivered" == "$audit_frames_delivered" ]]

terminal='{ "viewerClosed": true, "brokerSessionTerminal": true,
  "agentEventObserved": true, "viewStopAuditVerified": true }'
if [[ "$MATRIX_TERMINATION_CASE" == localAbort ]]; then
  terminal='{ "viewerClosed": true, "brokerSessionTerminal": true,
    "agentEventObserved": true, "viewStopAuditVerified": true,
    "endpointUserInitiated": true, "consentLeaseRevoked": true }'
fi
snapshot="$MATRIX_OUTPUT_DIR/observations/${MATRIX_TERMINATION_CASE}.json"
jq -cS -n \
  --arg schemaVersion 'faz22.6.viewOnlyViewerTerminationRuntimeSnapshot.v1' \
  --arg caseName "$MATRIX_TERMINATION_CASE" \
  --arg sourceRevision "$MATRIX_SOURCE_REVISION" \
  --arg observedAt "$observed_at" \
  --argjson binding "$(cat "$ROOT_BINDING")" \
  --arg trigger "$trigger_name" \
  --argjson triggeredAtEpochMillis "$triggered_at" \
  --argjson deliveryEndedAtEpochMillis "$delivery_ended_at" \
  --argjson viewerEndedBefore "$ended_before" \
  --argjson viewerEndedAfter "$ended_after" \
  --argjson globalFramesSentAtEnd "$frames_at_end" \
  --argjson globalFramesSentAfterObservationWindow "$frames_after_end" \
  --argjson sessionFramesDeliveredAtEnd "$audit_frames_delivered" \
  --argjson terminal "$terminal" '
    {schemaVersion:$schemaVersion,caseName:$caseName,sourceRevision:$sourceRevision,
     observedAt:$observedAt,binding:$binding,trigger:$trigger,
     triggeredAtEpochMillis:$triggeredAtEpochMillis,
     deliveryEndedAtEpochMillis:$deliveryEndedAtEpochMillis,
     counters:{viewerEndedBefore:$viewerEndedBefore,viewerEndedAfter:$viewerEndedAfter,
               globalFramesSentAtEnd:$globalFramesSentAtEnd,
               globalFramesSentAfterObservationWindow:$globalFramesSentAfterObservationWindow,
               sessionFramesDeliveredAtEnd:$sessionFramesDeliveredAtEnd,
               observationWindowMillis:3000},
     terminal:$terminal}' > "$snapshot"

jq -cS . "$snapshot" > "$MATRIX_OUTPUT_DIR/observations/${MATRIX_TERMINATION_CASE}.jsonl"
jq -cS . "$audit_record" > "$MATRIX_OUTPUT_DIR/audit/${MATRIX_TERMINATION_CASE}.jsonl"
rm -f "$snapshot" "$audit_record"
echo "termination_case=$MATRIX_TERMINATION_CASE raw_screen_persisted=false"
