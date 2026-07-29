#!/usr/bin/env bash
# Emit one source-bound, allowlisted VIEW_ONLY browser failure code.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
ALLOWLIST="${REPO_ROOT}/config/faz22-6-viewer-browser-diagnostic-codes.v1.json"

[[ "$#" == "2" ]] || exit 2
diagnostic="$1"
source_revision="$2"

[[ "$source_revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ -f "$diagnostic" && ! -L "$diagnostic" ]] || exit 1
[[ -f "$ALLOWLIST" && ! -L "$ALLOWLIST" ]] || exit 1

schema_version="$(jq -r '.schemaVersion // empty' "$diagnostic" 2>/dev/null || true)"
[[ "$schema_version" == "faz22.6.viewOnlyViewerBrowserDiagnostic.v4" ]] || {
  # Producer and reader come from the same github.sha checkout. Rejecting older
  # external artifacts is deliberate; an in-flight run cannot mix revisions.
  echo "browser-diagnostic-schema-mismatch" >&2
  exit 1
}

jq -er \
  --arg sourceRevision "$source_revision" \
  --slurpfile allowlist "$ALLOWLIST" '
    def valid_console_telemetry:
      (. | keys) == ["count", "entries", "truncatedCount"]
      and (.count | type == "number" and floor == . and . >= 1 and . <= 10000000)
      and (.truncatedCount | type == "number" and floor == . and . >= 0 and . <= 10000000)
      and (.entries | type == "array" and length >= 1 and length <= 16)
      and (.count == ((.entries | length) + .truncatedCount))
      and (.entries | all(
        keys == ["category", "kind", "locationClass", "locationSha256", "messageSha256"]
        and (.category | test("^(application-error|http-[1-5]xx|network-error|page-error)$"))
        and (.kind | test("^(console-error|page-error)$"))
        and (.locationClass | test("^(authentication|endpoint-admin-api|endpoint-admin-page|external|product-api|product-page|static-asset|unknown|viewer-api)$"))
        and (.locationSha256 | test("^sha256:[a-f0-9]{64}$"))
        and (.messageSha256 | test("^sha256:[a-f0-9]{64}$"))
      ));
    # The producer and reader are checked out from one exact workflow revision; mixed v3/v4 input is rejected.
    select(
      keys == ["ackTelemetry", "consoleTelemetry", "failureCode", "replayHttpStatus", "schemaVersion", "sourceRevision"]
      and .schemaVersion == "faz22.6.viewOnlyViewerBrowserDiagnostic.v4"
      and .sourceRevision == $sourceRevision
      and (.failureCode | type == "string")
      and (.failureCode | test("^browser-[a-z0-9-]{1,80}$"))
      and (.ackTelemetry == null or (
        (.ackTelemetry | keys) == ["accepted", "acceptedSamples", "attempted", "lastAcceptedSeq", "pending", "rejected"]
        and ([.ackTelemetry.attempted, .ackTelemetry.accepted, .ackTelemetry.acceptedSamples, .ackTelemetry.rejected]
          | all(type == "number" and floor == . and . >= 0 and . <= 10000000))
        and ((.ackTelemetry.accepted == 0 and .ackTelemetry.lastAcceptedSeq == null)
          or (.ackTelemetry.accepted > 0
            and (.ackTelemetry.lastAcceptedSeq | type == "number" and floor == . and . >= 0 and . <= 10000000)))
        and (.ackTelemetry.acceptedSamples <= .ackTelemetry.accepted)
        and ((.ackTelemetry.accepted + .ackTelemetry.rejected) <= .ackTelemetry.attempted)
        and (.ackTelemetry.pending | type == "number" and floor == . and . >= 0 and . <= 1000)
      ))
      and (.replayHttpStatus == null or (
        .replayHttpStatus | type == "number" and floor == . and . >= 100 and . <= 599
      ))
      and (if .failureCode == "browser-replay-not-rejected" then
        .ackTelemetry == null and .consoleTelemetry == null
          and .replayHttpStatus != null and .replayHttpStatus != 404
      elif .failureCode == "browser-console-error" then
        .ackTelemetry == null and .replayHttpStatus == null
          and (.consoleTelemetry | valid_console_telemetry)
      else
        .consoleTelemetry == null and .replayHttpStatus == null
      end)
      and ($allowlist | length == 1)
      and ($allowlist[0] | keys == ["failureCodes", "schemaVersion"])
      and ($allowlist[0].schemaVersion == "faz22.6.viewOnlyViewerBrowserDiagnosticCodes.v1")
      and (.failureCode as $code | $allowlist[0].failureCodes | index($code)) != null
    )
    | .failureCode
  ' "$diagnostic"
