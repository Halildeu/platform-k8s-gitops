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

jq -er \
  --arg sourceRevision "$source_revision" \
  --slurpfile allowlist "$ALLOWLIST" '
    select(
      keys == ["ackTelemetry", "failureCode", "schemaVersion", "sourceRevision"]
      and .schemaVersion == "faz22.6.viewOnlyViewerBrowserDiagnostic.v2"
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
      and ($allowlist | length == 1)
      and ($allowlist[0] | keys == ["failureCodes", "schemaVersion"])
      and ($allowlist[0].schemaVersion == "faz22.6.viewOnlyViewerBrowserDiagnosticCodes.v1")
      and (.failureCode as $code | $allowlist[0].failureCodes | index($code)) != null
    )
    | .failureCode
  ' "$diagnostic"
