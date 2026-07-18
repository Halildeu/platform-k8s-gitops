#!/usr/bin/env bash
# Produce a bounded diagnostic even when the collector stopped before writing
# all response bodies. Raw identity, permit, token, and screen fields are never
# copied to the output.

set -euo pipefail

SUMMARY_PATH="${1:?summary path is required}"
OPERATION_PATH="${2:?operation path is required}"
SOURCE_REVISION="${3:?source revision is required}"
OUTPUT_DIR="${4:?output directory is required}"
BROWSER_DIAGNOSTIC_PATH="${5:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
ALLOWLIST_PATH="${DIAGNOSTIC_ALLOWLIST_PATH:-${REPO_ROOT}/config/faz22-6-viewer-collector-diagnostic-allowlist.v1.json}"
BROWSER_ALLOWLIST_PATH="${BROWSER_DIAGNOSTIC_ALLOWLIST_PATH:-${REPO_ROOT}/config/faz22-6-viewer-browser-diagnostic-codes.v1.json}"

[[ "$SOURCE_REVISION" =~ ^[a-f0-9]{40}$ ]] || {
  echo "collector-diagnostic: source-revision-invalid" >&2
  exit 2
}
jq -e '
  .schemaVersion == "faz22.6.viewOnlyViewerCollectorDiagnosticAllowlist.v1"
  and ([.collectorFailureReasonCodes[], .denyReasons[], .policyGates[], .policyDetails[]]
    | all(type == "string" and length > 0))
  and (.collectorFailureReasonCodes | length == (unique | length))
  and (.denyReasons | length == (unique | length))
  and (.policyGates | length == (unique | length))
  and (.policyDetails | length == (unique | length))
' "$ALLOWLIST_PATH" >/dev/null || {
  echo "collector-diagnostic: allowlist-invalid" >&2
  exit 2
}
jq -e '
  .schemaVersion == "faz22.6.viewOnlyViewerBrowserDiagnosticCodes.v1"
  and (.failureCodes | type == "array" and length > 0)
  and (.failureCodes | all(type == "string" and test("^[a-z0-9-]{1,96}$")))
  and (.failureCodes | length == (unique | length))
  and (.failureCodes | index("browser-unclassified-failure") != null)
' "$BROWSER_ALLOWLIST_PATH" >/dev/null || {
  echo "collector-diagnostic: browser-allowlist-invalid" >&2
  exit 2
}

mkdir -p "$OUTPUT_DIR"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

safe_json_input() {
  local source="$1" fallback="$2"
  if [[ -s "$source" ]] && jq -e 'type == "object"' "$source" >/dev/null 2>&1; then
    printf '%s' "$source"
    return
  fi
  printf '%s\n' '{}' > "$fallback"
  printf '%s' "$fallback"
}

summary_safe="$(safe_json_input "$SUMMARY_PATH" "$tmp_dir/summary.json")"
operation_safe="$(safe_json_input "$OPERATION_PATH" "$tmp_dir/operation.json")"
browser_safe="$(safe_json_input "$BROWSER_DIAGNOSTIC_PATH" "$tmp_dir/browser.json")"
output="$OUTPUT_DIR/collector-diagnostic.json"

jq -cS -n \
  --arg sourceRevision "$SOURCE_REVISION" \
  --slurpfile summary "$summary_safe" \
  --slurpfile operation "$operation_safe" \
  --slurpfile browser "$browser_safe" \
  --slurpfile allowlist "$ALLOWLIST_PATH" \
  --slurpfile browserAllowlist "$BROWSER_ALLOWLIST_PATH" \
  'def bounded($pattern; $fallback):
     if type == "string" and test($pattern) then . else $fallback end;
   def http_or_null:
     if type == "number" and . >= 100 and . <= 599 then tostring
     elif type == "string" and test("^[0-9]{3}$") then .
     else null end;
   ($allowlist[0]) as $allowlist
   | ($browserAllowlist[0]) as $browserAllowlist
   | ($summary[0] // {}) as $summary
   | ($operation[0] // {}) as $operation
   | ($browser[0] // {}) as $browser
   | {
       schemaVersion:"faz22.6.viewOnlyViewerCollectorDiagnostic.v4",
       sourceRevision:$sourceRevision,
       status:(($summary.status // "collector-did-not-write-summary") as $status
         | if ["starting", "no-go", "accepted-candidate", "collector-did-not-write-summary"]
              | index($status) != null then $status else "collector-no-go" end),
       failureReasonCode:(
         if $summary.reason == null then null
         elif $summary.reason == "open session expected 200, got 404"
           then "open-session-http-404-expected-200"
         elif (($summary.reason | type) == "string")
           and (($allowlist.collectorFailureReasonCodes | index($summary.reason)) != null)
           then $summary.reason
         else "collector-no-go-unspecified"
         end
       ),
       browserFailureCode:(
         if $summary.reason != "browser-product-evidence-failed" then null
         elif $browser.schemaVersion == "faz22.6.viewOnlyViewerBrowserDiagnostic.v2"
           and $browser.sourceRevision == $sourceRevision
           and (($browser.failureCode | type) == "string")
           and (($browserAllowlist.failureCodes | index($browser.failureCode)) != null)
           then $browser.failureCode
         else "browser-unclassified-failure"
         end
       ),
       browserAckTelemetry:(
         if $summary.reason != "browser-product-evidence-failed"
           or $browser.schemaVersion != "faz22.6.viewOnlyViewerBrowserDiagnostic.v2"
           or $browser.sourceRevision != $sourceRevision
           or ($browser.ackTelemetry | type) != "object"
           or ($browser.ackTelemetry | keys) != ["accepted", "acceptedSamples", "attempted", "lastAcceptedSeq", "pending", "rejected"]
           then null
         elif ([
             $browser.ackTelemetry.attempted,
             $browser.ackTelemetry.accepted,
             $browser.ackTelemetry.acceptedSamples,
             $browser.ackTelemetry.rejected
           ] | all(type == "number" and floor == . and . >= 0 and . <= 10000000))
           and (($browser.ackTelemetry.accepted == 0 and $browser.ackTelemetry.lastAcceptedSeq == null)
             or ($browser.ackTelemetry.accepted > 0
               and ($browser.ackTelemetry.lastAcceptedSeq | type == "number"
                 and floor == . and . >= 0 and . <= 10000000)))
           and ($browser.ackTelemetry.acceptedSamples <= $browser.ackTelemetry.accepted)
           and (($browser.ackTelemetry.accepted + $browser.ackTelemetry.rejected)
             <= $browser.ackTelemetry.attempted)
           and ($browser.ackTelemetry.pending | type == "number"
             and floor == . and . >= 0 and . <= 1000)
           then $browser.ackTelemetry
         else null
         end
       ),
       consentWait:(($summary.consentWait // null)
         | if . == null then null else bounded("^[a-z-]{1,32}$"; null) end),
       openSessionHttp:(($summary.http.open // null) | http_or_null),
       operationHttp:(($summary.http.operation // null) | http_or_null),
       operationKind:(($operation.kind // null)
         | if . == null then null else bounded("^[A-Z_]{1,32}$"; null) end),
       transportPushed:(if ($operation.transportPushed | type) == "boolean"
         then $operation.transportPushed else false end),
       deny:(if ($operation.deny | type) != "object" then null else
         ($operation.deny.reason // "denied") as $denyReason
         | ($operation.deny.policyGate // null) as $policyGate
         | ($operation.deny.policyDetail // null) as $policyDetail
         | {
           reason:(if ($allowlist.denyReasons | index($denyReason)) != null
             then $denyReason else "denied" end),
           policyGate:(if ($allowlist.policyGates | index($policyGate)) != null
             then $policyGate else null end),
           policyDetail:(if ($allowlist.policyDetails | index($policyDetail)) != null
             then $policyDetail else null end)
         }
       end)
     }' > "$output"

jq -e '
  .schemaVersion == "faz22.6.viewOnlyViewerCollectorDiagnostic.v4"
  and (.sourceRevision | test("^[a-f0-9]{40}$"))
  and (.status | test("^[A-Za-z0-9:._-]{1,64}$"))
  and (.failureReasonCode == null or (.failureReasonCode | test("^[A-Za-z0-9:._-]{1,160}$")))
  and (.browserFailureCode == null or (.browserFailureCode | test("^[a-z0-9-]{1,96}$")))
  and (.browserAckTelemetry == null or (
    (.browserAckTelemetry | keys) == ["accepted", "acceptedSamples", "attempted", "lastAcceptedSeq", "pending", "rejected"]
    and ([.browserAckTelemetry.attempted, .browserAckTelemetry.accepted,
      .browserAckTelemetry.acceptedSamples, .browserAckTelemetry.rejected]
      | all(type == "number" and floor == . and . >= 0 and . <= 10000000))
    and ((.browserAckTelemetry.accepted == 0 and .browserAckTelemetry.lastAcceptedSeq == null)
      or (.browserAckTelemetry.accepted > 0
        and (.browserAckTelemetry.lastAcceptedSeq | type == "number"
          and floor == . and . >= 0 and . <= 10000000)))
    and (.browserAckTelemetry.acceptedSamples <= .browserAckTelemetry.accepted)
    and ((.browserAckTelemetry.accepted + .browserAckTelemetry.rejected)
      <= .browserAckTelemetry.attempted)
    and (.browserAckTelemetry.pending | type == "number"
      and floor == . and . >= 0 and . <= 1000)
  ))
  and (.consentWait == null or (.consentWait | test("^[a-z-]{1,32}$")))
  and (.openSessionHttp == null or (.openSessionHttp | test("^[0-9]{3}$")))
  and (.operationHttp == null or (.operationHttp | test("^[0-9]{3}$")))
  and (.operationKind == null or (.operationKind | test("^[A-Z_]{1,32}$")))
  and (.transportPushed | type == "boolean")
  and (.deny == null or (
    (.deny.reason | test("^[A-Za-z0-9:_-]{1,64}$"))
    and (.deny.policyGate == null or (.deny.policyGate | test("^[A-Z_]{1,32}$")))
    and (.deny.policyDetail == null or (.deny.policyDetail | test("^[a-z0-9-]{1,64}$")))
  ))
' "$output" >/dev/null

if grep -Eiq 'bearer|BEGIN .*PRIVATE KEY|sessionId|deviceId|operatorId|decisionId|operationId|canonicalPayload' "$output"; then
  echo "collector-diagnostic: forbidden identity or secret-bearing field" >&2
  exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$output" > "$OUTPUT_DIR/SHA256SUMS"
  (cd "$OUTPUT_DIR" && sha256sum -c SHA256SUMS)
else
  shasum -a 256 "$output" > "$OUTPUT_DIR/SHA256SUMS"
  (cd "$OUTPUT_DIR" && shasum -a 256 -c SHA256SUMS)
fi
