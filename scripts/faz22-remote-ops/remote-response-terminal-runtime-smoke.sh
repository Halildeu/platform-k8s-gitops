#!/usr/bin/env bash
set -euo pipefail

# Faz 22.6.3 Remote Response Terminal runtime smoke orchestrator.
#
# This is an operator wrapper over the already-reviewed product-path helpers.
# Default mode is plan-only: it does not dispatch a terminal operation, does not
# open a remote-bridge session, and does not mutate Kubernetes/GitOps/DB state.
# A live operation requires RUN_OPERATION=1, LIVE_OPERATION=1, an owned
# REMOTE_BRIDGE_SESSION_ID, and an operator token.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

EVIDENCE_DIR="${EVIDENCE_DIR:-/tmp/remote-response-terminal-runtime-smoke-$(date -u +%Y%m%dT%H%M%SZ)}"

RUN_PILOT_READINESS="${RUN_PILOT_READINESS:-0}"
RUN_GOVERNANCE_EXPORT="${RUN_GOVERNANCE_EXPORT:-0}"
RUN_OPERATION="${RUN_OPERATION:-0}"
RUN_RECORDING_EXPORT="${RUN_RECORDING_EXPORT:-0}"
RUN_VERIFY="${RUN_VERIFY:-1}"
LIVE_OPERATION="${LIVE_OPERATION:-0}"

OPERATION_SOURCE="${OPERATION_SOURCE:-catalog}"
REMOTE_BRIDGE_SESSION_ID="${REMOTE_BRIDGE_SESSION_ID:-}"
REMOTE_BRIDGE_OPERATOR_BASE_URL="${REMOTE_BRIDGE_OPERATOR_BASE_URL:-}"
SESSION_OWNER_REQUIRED="${SESSION_OWNER_REQUIRED:-1}"
SESSION_OWNER_AUTO_CLAIM="${SESSION_OWNER_AUTO_CLAIM:-0}"
SESSION_OWNER_ISSUE_URL="${SESSION_OWNER_ISSUE_URL:-${SESSION_OWNER_ISSUE:-}}"
SESSION_OWNER_ENDPOINT_ID="${SESSION_OWNER_ENDPOINT_ID:-}"
SESSION_OWNER_TTL_MINUTES="${SESSION_OWNER_TTL_MINUTES:-45}"
SESSION_OWNER_COMMENTS_FILE="${SESSION_OWNER_COMMENTS_FILE:-}"
SOURCE_GOVERNANCE_FILE="${SOURCE_GOVERNANCE_FILE:-}"
CATALOG_OPERATION_ID="${CATALOG_OPERATION_ID:-GET_HOSTNAME}"
APPROVED_SCRIPT_ID="${APPROVED_SCRIPT_ID:-DIAG_HOSTNAME}"
APPROVED_SCRIPT_VERSION="${APPROVED_SCRIPT_VERSION:-1}"
EXPECTED_OPERATION_KIND="${EXPECTED_OPERATION_KIND:-PERMIT}"
EXPECTED_CAPABILITY="${EXPECTED_CAPABILITY:-CONSTRAINED_PTY}"

PILOT_REQUIRE_READY="${PILOT_REQUIRE_READY:-0}"
VERIFY_REQUIRE_ACCEPTED="${VERIFY_REQUIRE_ACCEPTED:-0}"
VERIFY_REQUIRE_FULL_MATRIX="${VERIFY_REQUIRE_FULL_MATRIX:-0}"
VERIFY_REQUIRE_SHA256="${VERIFY_REQUIRE_SHA256:-1}"
VERIFY_REQUIRE_SESSION_OWNERSHIP="${VERIFY_REQUIRE_SESSION_OWNERSHIP:-1}"
VERIFY_REQUIRE_PILOT_READINESS="${VERIFY_REQUIRE_PILOT_READINESS:-1}"
VERIFY_REQUIRE_GOVERNANCE_EVIDENCE="${VERIFY_REQUIRE_GOVERNANCE_EVIDENCE:-1}"
VERIFY_REQUIRE_EVIDENCE_REDACTION="${VERIFY_REQUIRE_EVIDENCE_REDACTION:-1}"

TOKEN=""
ACTIONS_JSON="[]"

die() {
  printf 'ERR %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

bool_env() {
  local value="$1" label="$2"
  case "$value" in
    0|1) ;;
    *) die "$label must be 0 or 1" ;;
  esac
}

append_action() {
  local name="$1" status="$2" detail="$3"
  ACTIONS_JSON="$(jq -cn \
    --argjson arr "$ACTIONS_JSON" \
    --arg name "$name" \
    --arg status "$status" \
    --arg detail "$detail" \
    '$arr + [{name:$name,status:$status,detail:$detail}]')"
}

read_secret() {
  local value_name="$1" file_name="$2" value="" file=""
  value="${!value_name:-}"
  file="${!file_name:-}"
  if [[ -n "$value" && -n "$file" ]]; then
    die "set only one of $value_name or $file_name"
  fi
  if [[ -n "$file" ]]; then
    [[ -f "$file" ]] || die "$file_name file not found"
    value="$(tr -d '\r\n' < "$file")"
  fi
  printf '%s' "$value"
}

validate_token_for_child() {
  local token="$1"
  [[ -n "$token" ]] || die "OPERATOR_BEARER_TOKEN or OPERATOR_BEARER_TOKEN_FILE is required"
  if [[ "$token" == *$'\n'* || "$token" == *$'\r'* || "$token" == *\"* || "$token" == *\\* ]]; then
    die "operator token contains a character unsafe for child curl --config stdin"
  fi
}

sha256_manifest() {
  (
    cd "$EVIDENCE_DIR"
    local hasher=() sums_file
    if command -v shasum >/dev/null 2>&1; then
      hasher=(shasum -a 256)
    elif command -v sha256sum >/dev/null 2>&1; then
      hasher=(sha256sum)
    else
      die "missing command: shasum or sha256sum"
    fi
    sums_file="$(mktemp "${TMPDIR:-/tmp}/rtt-runtime-smoke-sha256.XXXXXX")"
    find . -type f ! -name SHA256SUMS -print0 \
      | sort -z \
      | xargs -0 "${hasher[@]}" \
      > "$sums_file"
    mv "$sums_file" SHA256SUMS
  )
}

write_plan() {
  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg operationSource "$OPERATION_SOURCE" \
    --arg catalogOperationId "$CATALOG_OPERATION_ID" \
    --arg approvedScriptId "$APPROVED_SCRIPT_ID" \
    --arg approvedScriptVersion "$APPROVED_SCRIPT_VERSION" \
    --arg runPilotReadiness "$RUN_PILOT_READINESS" \
    --arg runGovernanceExport "$RUN_GOVERNANCE_EXPORT" \
    --arg runOperation "$RUN_OPERATION" \
    --arg runRecordingExport "$RUN_RECORDING_EXPORT" \
    --arg runVerify "$RUN_VERIFY" \
    --arg liveOperation "$LIVE_OPERATION" \
    --arg sessionOwnerRequired "$SESSION_OWNER_REQUIRED" \
    --arg sessionOwnerAutoClaim "$SESSION_OWNER_AUTO_CLAIM" \
    --arg sessionOwnerIssueSet "$([[ -n "$SESSION_OWNER_ISSUE_URL" ]] && printf true || printf false)" \
    --arg sessionOwnerEndpointSet "$([[ -n "$SESSION_OWNER_ENDPOINT_ID" ]] && printf true || printf false)" \
    --arg sourceGovernanceSet "$([[ -n "$SOURCE_GOVERNANCE_FILE" ]] && printf true || printf false)" \
    --arg verifyRequireGovernance "$VERIFY_REQUIRE_GOVERNANCE_EVIDENCE" \
    --arg verifyRequireRedaction "$VERIFY_REQUIRE_EVIDENCE_REDACTION" \
    --arg sessionPresent "$([[ -n "$REMOTE_BRIDGE_SESSION_ID" ]] && printf true || printf false)" \
    '{
      generatedAt: $generatedAt,
      operationSource: $operationSource,
      liveOperation: ($liveOperation == "1"),
      sessionOwnership: {
        required: ($sessionOwnerRequired == "1"),
        autoClaim: ($sessionOwnerAutoClaim == "1"),
        ownerIssueSet: ($sessionOwnerIssueSet == "true"),
        endpointIdSet: ($sessionOwnerEndpointSet == "true"),
        storesRawSessionId: false,
        storesBearerToken: false
      },
      governanceEvidence: {
        requiredForAcceptedCandidate: ($verifyRequireGovernance == "1"),
        expectedFile: "governance-evidence.json",
        generatedByOrchestrator: ($runGovernanceExport == "1"),
        sourceGovernanceFileSet: ($sourceGovernanceSet == "true")
      },
      evidenceRedaction: {
        requiredForAcceptedCandidate: ($verifyRequireRedaction == "1"),
        reportsMatchedValues: false
      },
      requestedActions: {
        pilotReadiness: ($runPilotReadiness == "1"),
        governanceExport: ($runGovernanceExport == "1"),
        operation: ($runOperation == "1"),
        recordingExport: ($runRecordingExport == "1"),
        verify: ($runVerify == "1")
      },
      sessionPresent: ($sessionPresent == "true"),
      catalogOperationId: $catalogOperationId,
      approvedScript: {
        scriptId: $approvedScriptId,
        version: $approvedScriptVersion
      },
      liveOperationGate: [
        "RUN_OPERATION=1",
        "LIVE_OPERATION=1",
        "REMOTE_BRIDGE_SESSION_ID set to an owned, approved, step-up-verified session",
        "SESSION_OWNER_ISSUE_URL and SESSION_OWNER_ENDPOINT_ID prove a redacted active ownership claim",
        "OPERATOR_BEARER_TOKEN_FILE or OPERATOR_BEARER_TOKEN supplied by operator"
	      ],
	      acceptedRuntimeEvidence: [
	        "pilot endpoint heartbeat proves the expected EndpointAgent version",
	        "pilot-readiness/summary.json proves ready-for-product-smoke",
        "redacted live-session ownership guard output is present",
        "governance-evidence.json proves dual-control, step-up, ticket, justification, and fail-closed recording policy",
        "evidence redaction scan reports no high-confidence sensitive marker classes",
        "allowed catalog operation returns PERMIT with transportPushed=true",
        "recording/export contains AGENT_OUTPUT or DATA plus terminal EndStream",
        "core raw/unrestricted and command/policy override denies are present",
        "SHA256SUMS verifies and covers required evidence files"
      ],
      rejectedPaths: [
        "direct database insert",
        "Software Catalog abuse for EndpointAgent upgrade",
        "Approved Script Runner download-and-execute as hidden installer",
        "generic endpoint command UPDATE_AGENT",
        "caller-supplied binary/hash/signer fields",
        "raw PowerShell or unrestricted terminal",
        "RDP/SSH/WinRM/SMB/RPC/file browser/reverse tunnel"
      ]
    }' > "${EVIDENCE_DIR}/runtime-smoke-plan.json"
}

run_session_ownership_guard() {
  [[ -n "$REMOTE_BRIDGE_SESSION_ID" ]] \
    || die "REMOTE_BRIDGE_SESSION_ID is required when RUN_OPERATION=1"
  [[ -n "$SESSION_OWNER_ISSUE_URL" ]] \
    || die "SESSION_OWNER_ISSUE_URL or SESSION_OWNER_ISSUE is required when SESSION_OWNER_REQUIRED=1"
  [[ -n "$SESSION_OWNER_ENDPOINT_ID" ]] \
    || die "SESSION_OWNER_ENDPOINT_ID is required when SESSION_OWNER_REQUIRED=1"

  local action="check" guard_output
  if [[ "$SESSION_OWNER_AUTO_CLAIM" == "1" ]]; then
    action="claim"
  fi
  guard_output="${EVIDENCE_DIR}/session-ownership-guard.out"

  (
    cd "$REPO_ROOT"
    ACTION="$action" \
    REMOTE_BRIDGE_SESSION_ID="$REMOTE_BRIDGE_SESSION_ID" \
    SESSION_OWNER_ENDPOINT_ID="$SESSION_OWNER_ENDPOINT_ID" \
    SESSION_OWNER_ISSUE_URL="$SESSION_OWNER_ISSUE_URL" \
    SESSION_OWNER_TTL_MINUTES="$SESSION_OWNER_TTL_MINUTES" \
    SESSION_OWNER_OPERATION_SOURCE="$OPERATION_SOURCE" \
    SESSION_OWNER_COMMENTS_FILE="$SESSION_OWNER_COMMENTS_FILE" \
    CATALOG_OPERATION_ID="$CATALOG_OPERATION_ID" \
    APPROVED_SCRIPT_ID="$APPROVED_SCRIPT_ID" \
      scripts/faz22-remote-ops/remote-response-terminal-session-ownership-guard.sh
  ) > "$guard_output"

  append_action "session-ownership-guard" "ok" "$(tail -n 1 "$guard_output")"
}

run_pilot_readiness() {
  local dir
  dir="${EVIDENCE_DIR}/pilot-readiness"
  mkdir -p "$dir"

  (
    cd "$REPO_ROOT"
    EVIDENCE_DIR="$dir" REQUIRE_READY="$PILOT_REQUIRE_READY" \
      scripts/faz22-remote-ops/remote-response-terminal-pilot-readiness.sh
  )

  local decision
  decision="$(jq -r '.decision // .status // "unknown"' "${dir}/summary.json" 2>/dev/null || printf unknown)"
  append_action "pilot-readiness" "ok" "decision=${decision}"
}

run_governance_export() {
  (
    cd "$REPO_ROOT"
    EVIDENCE_DIR="$EVIDENCE_DIR" \
    SOURCE_GOVERNANCE_FILE="$SOURCE_GOVERNANCE_FILE" \
      scripts/faz22-remote-ops/remote-response-terminal-governance-export.sh
  )

  local reason
  reason="$(jq -r '.reason // "unknown"' "${EVIDENCE_DIR}/governance-evidence-summary.json" 2>/dev/null || printf unknown)"
  append_action "governance-export" "ok" "reason=${reason}"
}

run_operation_smoke() {
  validate_token_for_child "$TOKEN"
  [[ -n "$REMOTE_BRIDGE_SESSION_ID" ]] \
    || die "REMOTE_BRIDGE_SESSION_ID is required when RUN_OPERATION=1"

  case "$OPERATION_SOURCE" in
    catalog)
      (
        cd "$REPO_ROOT"
        OPERATOR_BEARER_TOKEN="$TOKEN" \
        EVIDENCE_DIR="$EVIDENCE_DIR" \
        REMOTE_BRIDGE_SESSION_ID="$REMOTE_BRIDGE_SESSION_ID" \
        REMOTE_BRIDGE_OPERATOR_BASE_URL="$REMOTE_BRIDGE_OPERATOR_BASE_URL" \
        CATALOG_OPERATION_ID="$CATALOG_OPERATION_ID" \
        EXPECTED_OPERATION_KIND="$EXPECTED_OPERATION_KIND" \
        REQUIRE_OPERATION=1 \
          scripts/faz22-remote-ops/remote-ops-catalog-smoke.sh
      )
      [[ -f "${EVIDENCE_DIR}/summary.json" ]] && mv "${EVIDENCE_DIR}/summary.json" "${EVIDENCE_DIR}/operation-summary.json"
      cp "${EVIDENCE_DIR}/operation-summary.json" "${EVIDENCE_DIR}/smoke-summary.json"
      append_action "operation-smoke" "ok" "catalog operation=${CATALOG_OPERATION_ID}"
      ;;
    approved-script)
      (
        cd "$REPO_ROOT"
        OPERATOR_BEARER_TOKEN="$TOKEN" \
        EVIDENCE_DIR="$EVIDENCE_DIR" \
        REMOTE_BRIDGE_SESSION_ID="$REMOTE_BRIDGE_SESSION_ID" \
        REMOTE_BRIDGE_OPERATOR_BASE_URL="$REMOTE_BRIDGE_OPERATOR_BASE_URL" \
        APPROVED_SCRIPT_ID="$APPROVED_SCRIPT_ID" \
        APPROVED_SCRIPT_VERSION="$APPROVED_SCRIPT_VERSION" \
        EXPECTED_OPERATION_KIND="$EXPECTED_OPERATION_KIND" \
        REQUIRE_OPERATION=1 \
          scripts/faz22-remote-ops/remote-ops-approved-script-smoke.sh
      )
      [[ -f "${EVIDENCE_DIR}/summary.json" ]] && mv "${EVIDENCE_DIR}/summary.json" "${EVIDENCE_DIR}/operation-summary.json"
      cp "${EVIDENCE_DIR}/operation-summary.json" "${EVIDENCE_DIR}/smoke-summary.json"
      append_action "operation-smoke" "ok" "approved script=${APPROVED_SCRIPT_ID}:${APPROVED_SCRIPT_VERSION}"
      ;;
    *)
      die "OPERATION_SOURCE must be catalog or approved-script"
      ;;
  esac
}

run_recording_export() {
  (
    cd "$REPO_ROOT"
    EVIDENCE_DIR="$EVIDENCE_DIR" \
    SESSION_ID="$REMOTE_BRIDGE_SESSION_ID" \
    SOURCE_RECORDING_ROWS_FILE="${SOURCE_RECORDING_ROWS_FILE:-}" \
    DATABASE_URL="${DATABASE_URL:-}" \
    STAGING_SSH_TARGET="${STAGING_SSH_TARGET:-}" \
    PG_CONTAINER="${PG_CONTAINER:-platform-pg-test}" \
    PG_DATABASE="${PG_DATABASE:-endpoint_admin}" \
    PG_USER="${PG_USER:-postgres}" \
      scripts/faz22-remote-ops/remote-response-terminal-recording-export.sh
  )
  append_action "recording-export" "ok" "recording export helper completed"
}

run_verifier() {
  (
    cd "$REPO_ROOT"
    export EVIDENCE_DIR
    export EXPECTED_OPERATION_KIND
    export EXPECTED_CAPABILITY
    export REQUIRE_ACCEPTED="$VERIFY_REQUIRE_ACCEPTED"
    export REQUIRE_FULL_MATRIX="$VERIFY_REQUIRE_FULL_MATRIX"
    export REQUIRE_SHA256="$VERIFY_REQUIRE_SHA256"
    export REQUIRE_SESSION_OWNERSHIP="$VERIFY_REQUIRE_SESSION_OWNERSHIP"
    export REQUIRE_PILOT_READINESS="$VERIFY_REQUIRE_PILOT_READINESS"
    export REQUIRE_GOVERNANCE_EVIDENCE="$VERIFY_REQUIRE_GOVERNANCE_EVIDENCE"
    export REQUIRE_EVIDENCE_REDACTION="$VERIFY_REQUIRE_EVIDENCE_REDACTION"
    if [[ "$OPERATION_SOURCE" == "catalog" ]]; then
      export EXPECTED_CATALOG_OPERATION_ID="$CATALOG_OPERATION_ID"
      export EXPECTED_APPROVED_SCRIPT_ID=""
    else
      export EXPECTED_CATALOG_OPERATION_ID=""
      export EXPECTED_APPROVED_SCRIPT_ID="$APPROVED_SCRIPT_ID"
    fi
    scripts/faz22-remote-ops/remote-response-terminal-evidence-verify.sh "$EVIDENCE_DIR"
  )

  local result
  result="$(jq -r '.result // "unknown"' "${EVIDENCE_DIR}/verification-summary.json" 2>/dev/null || printf unknown)"
  append_action "evidence-verify" "ok" "result=${result}"
}

write_summary() {
  local status="plan-ready-no-operation" verifier_result="" operation_status="" recording_hint="" pilot_decision="" governance_reason=""

  if [[ "$RUN_OPERATION" == "1" ]]; then
    status="operation-attempted"
  elif [[ "$RUN_RECORDING_EXPORT" == "1" ]]; then
    status="recording-exported-no-operation"
  fi
  if [[ -f "${EVIDENCE_DIR}/verification-summary.json" ]]; then
    verifier_result="$(jq -r '.result // ""' "${EVIDENCE_DIR}/verification-summary.json")"
    if [[ -n "$verifier_result" ]]; then
      status="verification-${verifier_result}"
    fi
  fi
  if [[ -f "${EVIDENCE_DIR}/operation-summary.json" ]]; then
    operation_status="$(jq -r '.operationStatus // .status // ""' "${EVIDENCE_DIR}/operation-summary.json")"
  fi
  if [[ -f "${EVIDENCE_DIR}/recording-summary.json" ]]; then
    recording_hint="$(jq -r '.acceptanceHint // ""' "${EVIDENCE_DIR}/recording-summary.json")"
  fi
  if [[ -f "${EVIDENCE_DIR}/pilot-readiness/summary.json" ]]; then
    pilot_decision="$(jq -r '.decision // .status // ""' "${EVIDENCE_DIR}/pilot-readiness/summary.json")"
  fi
  if [[ -f "${EVIDENCE_DIR}/governance-evidence-summary.json" ]]; then
    governance_reason="$(jq -r '.reason // ""' "${EVIDENCE_DIR}/governance-evidence-summary.json")"
  fi

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg status "$status" \
    --arg evidenceDir "$EVIDENCE_DIR" \
    --arg operationSource "$OPERATION_SOURCE" \
    --arg catalogOperationId "$CATALOG_OPERATION_ID" \
    --arg approvedScriptId "$APPROVED_SCRIPT_ID" \
    --arg approvedScriptVersion "$APPROVED_SCRIPT_VERSION" \
    --arg liveOperation "$LIVE_OPERATION" \
    --arg runOperation "$RUN_OPERATION" \
    --arg operationStatus "$operation_status" \
    --arg verifierResult "$verifier_result" \
    --arg recordingHint "$recording_hint" \
    --arg pilotDecision "$pilot_decision" \
    --arg governanceReason "$governance_reason" \
    --argjson actions "$ACTIONS_JSON" \
    '{
      generatedAt: $generatedAt,
      status: $status,
      evidenceDir: $evidenceDir,
      liveOperation: ($liveOperation == "1"),
      operationSource: $operationSource,
      operation: {
        requested: ($runOperation == "1"),
        status: $operationStatus,
        catalogOperationId: $catalogOperationId,
        approvedScriptId: $approvedScriptId,
        approvedScriptVersion: $approvedScriptVersion
      },
      pilotReadinessDecision: $pilotDecision,
      governanceEvidenceReason: $governanceReason,
      recordingAcceptanceHint: $recordingHint,
      verifierResult: $verifierResult,
	      actions: $actions,
	      acceptedNextEvidence: [
	        "post-update heartbeat proving the expected EndpointAgent version",
        "governance-evidence.json proving dual-control, step-up, ticket, justification, and fail-closed recording policy",
        "evidence redaction scan with no sensitive marker findings",
        "catalog operation PERMIT with transportPushed=true",
        "AGENT_OUTPUT or DATA plus EndStream in recording export",
        "raw/unrestricted and command/policy override negative evidence",
        "SHA256SUMS verification over the final bundle"
      ],
	      doesNotProve: [
	        "platform-agent#208 Done state unless verification result is accepted-candidate and owner accepts the proven boundary",
	        "current EndpointAgent deployment when pilot readiness is not ready-for-product-smoke",
        "signed MSI/GPO or broad rollout",
        "production remote-support readiness",
        "unrestricted shell/RDP/WinRM/SMB/SSH",
        "true TPM/device-key hardware attestation"
      ]
    }' > "${EVIDENCE_DIR}/summary.json"
}

main() {
  need_cmd jq
  need_cmd mktemp
  bool_env "$RUN_PILOT_READINESS" RUN_PILOT_READINESS
  bool_env "$RUN_GOVERNANCE_EXPORT" RUN_GOVERNANCE_EXPORT
  bool_env "$RUN_OPERATION" RUN_OPERATION
  bool_env "$RUN_RECORDING_EXPORT" RUN_RECORDING_EXPORT
  bool_env "$RUN_VERIFY" RUN_VERIFY
  bool_env "$LIVE_OPERATION" LIVE_OPERATION
  bool_env "$SESSION_OWNER_REQUIRED" SESSION_OWNER_REQUIRED
  bool_env "$SESSION_OWNER_AUTO_CLAIM" SESSION_OWNER_AUTO_CLAIM
  bool_env "$PILOT_REQUIRE_READY" PILOT_REQUIRE_READY
  bool_env "$VERIFY_REQUIRE_ACCEPTED" VERIFY_REQUIRE_ACCEPTED
  bool_env "$VERIFY_REQUIRE_FULL_MATRIX" VERIFY_REQUIRE_FULL_MATRIX
  bool_env "$VERIFY_REQUIRE_SHA256" VERIFY_REQUIRE_SHA256
  bool_env "$VERIFY_REQUIRE_SESSION_OWNERSHIP" VERIFY_REQUIRE_SESSION_OWNERSHIP
  bool_env "$VERIFY_REQUIRE_PILOT_READINESS" VERIFY_REQUIRE_PILOT_READINESS
  bool_env "$VERIFY_REQUIRE_GOVERNANCE_EVIDENCE" VERIFY_REQUIRE_GOVERNANCE_EVIDENCE
  bool_env "$VERIFY_REQUIRE_EVIDENCE_REDACTION" VERIFY_REQUIRE_EVIDENCE_REDACTION

  mkdir -p "$EVIDENCE_DIR"
  write_plan

  if [[ "$RUN_OPERATION" == "1" && "$LIVE_OPERATION" != "1" ]]; then
    die "RUN_OPERATION=1 requested; set LIVE_OPERATION=1 explicitly"
  fi

  TOKEN="$(read_secret OPERATOR_BEARER_TOKEN OPERATOR_BEARER_TOKEN_FILE)"

  if [[ "$RUN_PILOT_READINESS" == "1" ]]; then
    run_pilot_readiness
  else
    append_action "pilot-readiness" "skipped" "RUN_PILOT_READINESS is not 1"
  fi

  if [[ "$RUN_GOVERNANCE_EXPORT" == "1" ]]; then
    run_governance_export
  else
    append_action "governance-export" "skipped" "RUN_GOVERNANCE_EXPORT is not 1"
  fi

  if [[ "$RUN_OPERATION" == "1" ]]; then
    if [[ "$SESSION_OWNER_REQUIRED" == "1" ]]; then
      run_session_ownership_guard
    else
      append_action "session-ownership-guard" "skipped" "SESSION_OWNER_REQUIRED is not 1"
    fi
    run_operation_smoke
  else
    append_action "session-ownership-guard" "skipped" "RUN_OPERATION is not 1"
    append_action "operation-smoke" "skipped" "RUN_OPERATION is not 1; no terminal operation dispatched"
  fi

  if [[ "$RUN_RECORDING_EXPORT" == "1" ]]; then
    run_recording_export
  else
    append_action "recording-export" "skipped" "RUN_RECORDING_EXPORT is not 1"
  fi

  if [[ "$RUN_VERIFY" == "1" && "$RUN_OPERATION" == "1" ]]; then
    sha256_manifest
    run_verifier
  else
    append_action "evidence-verify" "skipped" "RUN_VERIFY is not 1 or no operation was run"
  fi

  write_summary
  sha256_manifest

  jq -r --arg evidenceDir "$EVIDENCE_DIR" \
    '"REMOTE_RESPONSE_TERMINAL_RUNTIME_SMOKE_STATUS=" + .status + " evidence_dir=" + $evidenceDir' \
    "${EVIDENCE_DIR}/summary.json"
}

main "$@"
