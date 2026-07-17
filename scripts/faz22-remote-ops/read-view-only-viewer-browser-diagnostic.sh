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
      keys == ["failureCode", "schemaVersion", "sourceRevision"]
      and .schemaVersion == "faz22.6.viewOnlyViewerBrowserDiagnostic.v1"
      and .sourceRevision == $sourceRevision
      and (.failureCode | type == "string")
      and (.failureCode | test("^browser-[a-z0-9-]{1,80}$"))
      and ($allowlist | length == 1)
      and ($allowlist[0] | keys == ["failureCodes", "schemaVersion"])
      and ($allowlist[0].schemaVersion == "faz22.6.viewOnlyViewerBrowserDiagnosticCodes.v1")
      and (.failureCode as $code | $allowlist[0].failureCodes | index($code)) != null
    )
    | .failureCode
  ' "$diagnostic"
