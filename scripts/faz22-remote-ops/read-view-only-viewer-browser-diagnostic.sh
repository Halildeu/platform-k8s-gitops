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
[[ "$schema_version" == "faz22.6.viewOnlyViewerBrowserDiagnostic.v3" ]] || {
  # Producer and reader come from the same github.sha checkout. Rejecting older
  # external artifacts is deliberate; an in-flight run cannot mix revisions.
  echo "browser-diagnostic-schema-mismatch" >&2
  exit 1
}

jq -er \
  --arg sourceRevision "$source_revision" \
  --slurpfile allowlist "$ALLOWLIST" '
    # The producer and reader are checked out from one exact workflow revision; mixed v2/v3 input is rejected.
    select(
      keys == ["ackTelemetry", "failureCode", "replayHttpStatus", "schemaVersion", "sourceRevision"]
      and .schemaVersion == "faz22.6.viewOnlyViewerBrowserDiagnostic.v3"
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
        .ackTelemetry == null and .replayHttpStatus != null and .replayHttpStatus != 404
      else
        .replayHttpStatus == null
      end)
      and ($allowlist | length == 1)
      and ($allowlist[0] | keys == ["failureCodes", "schemaVersion"])
      and ($allowlist[0].schemaVersion == "faz22.6.viewOnlyViewerBrowserDiagnosticCodes.v1")
      and (.failureCode as $code | $allowlist[0].failureCodes | index($code)) != null
    )
    | .failureCode
  ' "$diagnostic"
