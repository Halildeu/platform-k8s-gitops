#!/usr/bin/env bash
# shellcheck disable=SC2016 # jq filters intentionally use jq regex quoting.
set -euo pipefail

# Faz 22.6.3 Remote Response Terminal runtime evidence verifier.
#
# This script is read-only against the platform. It consumes an already-captured
# evidence directory, classifies whether the allowed PERMIT path and core
# negative checks are present, then writes verification-summary.json. It never
# opens a remote-bridge session, dispatches commands, reads live DB state, or
# mutates Kubernetes/GitOps state.

EVIDENCE_DIR="${EVIDENCE_DIR:-${1:-.}}"
OPERATION_BODY_FILE="${OPERATION_BODY_FILE:-}"
RECORDING_ROWS_FILE="${RECORDING_ROWS_FILE:-}"
SMOKE_SUMMARY_FILE="${SMOKE_SUMMARY_FILE:-}"
SUMMARY_FILE="${SUMMARY_FILE:-${EVIDENCE_DIR}/verification-summary.json}"

EXPECTED_OPERATION_KIND="${EXPECTED_OPERATION_KIND:-PERMIT}"
EXPECTED_CAPABILITY="${EXPECTED_CAPABILITY:-CONSTRAINED_PTY}"
EXPECTED_CATALOG_OPERATION_ID="${EXPECTED_CATALOG_OPERATION_ID:-}"
EXPECTED_APPROVED_SCRIPT_ID="${EXPECTED_APPROVED_SCRIPT_ID:-}"

REQUIRE_NEGATIVES="${REQUIRE_NEGATIVES:-1}"
REQUIRE_FULL_MATRIX="${REQUIRE_FULL_MATRIX:-0}"
REQUIRE_SHA256="${REQUIRE_SHA256:-1}"
REQUIRE_ACCEPTED="${REQUIRE_ACCEPTED:-0}"

NEGATIVE_DETAILS="[]"

die() {
  printf 'ERR %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

relpath() {
  local path="$1"
  case "$path" in
    "$EVIDENCE_DIR"/*) printf '%s' "${path#"$EVIDENCE_DIR"/}" ;;
    *) printf '%s' "$path" ;;
  esac
}

resolve_input_file() {
  local path="$1"
  case "$path" in
    /*) printf '%s\n' "$path" ;;
    *) printf '%s\n' "${EVIDENCE_DIR}/${path}" ;;
  esac
}

canonical_dir() {
  local path="$1"
  (cd "$path" 2>/dev/null && pwd -P) || return 1
}

first_existing_file() {
  local candidate
  for candidate in "$@"; do
    if [[ -f "$EVIDENCE_DIR/$candidate" ]]; then
      printf '%s\n' "$EVIDENCE_DIR/$candidate"
      return 0
    fi
  done
  return 1
}

validate_file_under_evidence_dir() {
  local path="$1" label="$2"
  local evidence_abs file_dir_abs file_abs
  [[ -n "$path" ]] || return 0
  [[ -f "$path" ]] || die "$label file not found: $path"

  evidence_abs="$(canonical_dir "$EVIDENCE_DIR")" \
    || die "cannot resolve EVIDENCE_DIR: $EVIDENCE_DIR"
  file_dir_abs="$(canonical_dir "$(dirname "$path")")" \
    || die "cannot resolve $label file directory: $path"
  file_abs="${file_dir_abs}/$(basename "$path")"
  case "$file_abs" in
    "$evidence_abs"/*) ;;
    *) die "$label file must be under EVIDENCE_DIR: $path" ;;
  esac
}

json_bool() {
  if [[ "$1" == "true" ]]; then
    printf true
  else
    printf false
  fi
}

append_negative_detail() {
  local category="$1" file="$2" ok="$3" reason="$4" http_code="$5"
  NEGATIVE_DETAILS="$(jq -cn \
    --argjson arr "$NEGATIVE_DETAILS" \
    --arg category "$category" \
    --arg file "$(relpath "$file")" \
    --arg ok "$ok" \
    --arg reason "$reason" \
    --arg httpCode "$http_code" \
    '$arr + [{
      category: $category,
      file: $file,
      ok: ($ok == "true"),
      reason: $reason,
      httpCode: $httpCode
    }]')"
}

body_indicates_denial() {
  local file="$1"
  jq -e '
    (.kind? == "DENY")
    or (.transportPushed? == false)
    or ((.reason? // "") | tostring | length > 0)
    or ((.error? // "") | tostring | length > 0)
    or (((.message? // "") | tostring) | test("deny|denied|disabled|revoked|expired|replay|wrong|mismatch|unauthorized|forbidden"; "i"))
  ' "$file" >/dev/null 2>&1
}

extract_denial_reason() {
  local file="$1"
  jq -r '
    .reason? // .error? // .message? // .kind? // "denial-body"
    | tostring
  ' "$file" 2>/dev/null || printf 'unparseable-body'
}

adjacent_http_code() {
  local file="$1" code_file code
  code_file="${file%.body}.code"
  if [[ -f "$code_file" ]]; then
    code="$(tr -d '\r\n[:space:]' < "$code_file")"
    printf '%s' "$code"
  fi
}

check_negative_category() {
  local category="$1"
  shift
  local rel file reason http_code found="false" ok="false"

  for rel in "$@"; do
    file="${EVIDENCE_DIR}/${rel}"
    [[ -f "$file" ]] || continue
    found="true"
    reason="$(extract_denial_reason "$file")"
    http_code="$(adjacent_http_code "$file")"

    if body_indicates_denial "$file" || [[ "$http_code" =~ ^(400|401|403|409|422)$ ]]; then
      ok="true"
    fi
    append_negative_detail "$category" "$file" "$ok" "$reason" "$http_code"
  done

  if [[ "$found" != "true" ]]; then
    NEGATIVE_DETAILS="$(jq -cn \
      --argjson arr "$NEGATIVE_DETAILS" \
      --arg category "$category" \
      '$arr + [{
        category: $category,
        file: null,
        ok: false,
        reason: "missing-evidence-file",
        httpCode: ""
      }]')"
  fi

  [[ "$ok" == "true" ]]
}

find_operation_body_file() {
  if [[ -n "$OPERATION_BODY_FILE" ]]; then
    resolve_input_file "$OPERATION_BODY_FILE"
    return 0
  fi
  first_existing_file \
    catalog-operation.body \
    approved-script-operation.body \
    terminal-operation.body \
    response-terminal-operation.body \
    operation.body \
    permit.body
}

find_recording_rows_file() {
  if [[ -n "$RECORDING_ROWS_FILE" ]]; then
    resolve_input_file "$RECORDING_ROWS_FILE"
    return 0
  fi
  first_existing_file \
    session-recording.jsonl \
    recording.jsonl \
    remote-bridge-recording.jsonl \
    agent-output.jsonl \
    session-recording.tsv \
    recording.tsv \
    session-recording.psv \
    recording.psv \
    session-recording.csv \
    recording.csv
}

find_smoke_summary_file() {
  if [[ -n "$SMOKE_SUMMARY_FILE" ]]; then
    resolve_input_file "$SMOKE_SUMMARY_FILE"
    return 0
  fi
  first_existing_file summary.json smoke-summary.json
}

analyze_sha256_manifest() {
  local sums_file="${EVIDENCE_DIR}/SHA256SUMS"
  local status="not-present" log_excerpt="" tmp_log hasher=()

  if [[ -f "$sums_file" ]]; then
    if command -v shasum >/dev/null 2>&1; then
      hasher=(shasum -a 256 -c SHA256SUMS)
    elif command -v sha256sum >/dev/null 2>&1; then
      hasher=(sha256sum -c SHA256SUMS)
    else
      status="missing-hasher"
      log_excerpt="missing shasum or sha256sum"
    fi

    if [[ ${#hasher[@]} -gt 0 ]]; then
      tmp_log="$(mktemp "${TMPDIR:-/tmp}/rtt-sha256-check.XXXXXX")"
      if (cd "$EVIDENCE_DIR" && "${hasher[@]}" > "$tmp_log" 2>&1); then
        status="ok"
      else
        status="failed"
      fi
      log_excerpt="$(head -n 20 "$tmp_log" | tr '\n' ' ' | sed 's/[[:space:]]\{1,\}/ /g')"
      rm -f "$tmp_log"
    fi
  elif [[ "$REQUIRE_SHA256" == "1" ]]; then
    status="missing"
    log_excerpt="SHA256SUMS not present"
  fi

  jq -cn \
    --arg required "$REQUIRE_SHA256" \
    --arg status "$status" \
    --arg logExcerpt "$log_excerpt" \
    '{required: ($required == "1"), status: $status, logExcerpt: $logExcerpt}'
}

sha256_manifest_covers_relpath() {
  local rel="$1" sums_file="${EVIDENCE_DIR}/SHA256SUMS"
  rel="${rel#./}"
  [[ -f "$sums_file" ]] || return 1
  awk -v rel="$rel" '
    {
      path = $0
      sub(/^[^[:space:]]+[[:space:]]+/, "", path)
      sub(/^[* ]/, "", path)
      sub(/^\.\//, "", path)
      if (path == rel) {
        found = 1
      }
    }
    END { exit found ? 0 : 1 }
  ' "$sums_file"
}

analyze_sha256_required_files() {
  local arr="[]" path rel ok missing_count
  for path in "$@"; do
    [[ -n "$path" ]] || continue
    rel="$(relpath "$path")"
    ok="false"
    if sha256_manifest_covers_relpath "$rel"; then
      ok="true"
    fi
    arr="$(jq -cn \
      --argjson arr "$arr" \
      --arg file "$rel" \
      --arg ok "$ok" \
      '$arr + [{file: $file, covered: ($ok == "true")}]')"
  done

  while IFS= read -r rel; do
    [[ -n "$rel" ]] || continue
    ok="false"
    if sha256_manifest_covers_relpath "$rel"; then
      ok="true"
    fi
    arr="$(jq -cn \
      --argjson arr "$arr" \
      --arg file "$rel" \
      --arg ok "$ok" \
      '$arr + [{file: $file, covered: ($ok == "true")}]')"
  done < <(jq -r '.[] | select(.file != null) | .file' <<< "$NEGATIVE_DETAILS")

  missing_count="$(jq '[.[] | select(.covered != true)] | length' <<< "$arr")"
  jq -cn \
    --argjson files "$arr" \
    --arg missingCount "$missing_count" \
    '{ok: (($missingCount | tonumber) == 0), missingCount: ($missingCount | tonumber), files: $files}'
}

analyze_operation_body() {
  local file="$1"
  if [[ -z "$file" ]]; then
    jq -cn '{status:"missing", file:null, ok:false, reason:"operation body evidence not found"}'
    return 0
  fi
  if ! jq -e . "$file" >/dev/null 2>&1; then
    jq -cn --arg file "$(relpath "$file")" \
      '{status:"invalid-json", file:$file, ok:false, reason:"operation body is not valid JSON"}'
    return 0
  fi

  jq -c \
    --arg file "$(relpath "$file")" \
    --arg expectedKind "$EXPECTED_OPERATION_KIND" \
    --arg expectedCapability "$EXPECTED_CAPABILITY" \
    --arg expectedCatalog "$EXPECTED_CATALOG_OPERATION_ID" \
    --arg expectedScript "$EXPECTED_APPROVED_SCRIPT_ID" \
    '{
      status: "parsed",
      file: $file,
      observedKind: (.kind // ""),
      kindOk: ((.kind // "") == $expectedKind),
      transportPushed: (.transportPushed == true),
      denyAbsent: ((.deny // null) == null),
      signaturePresent: (.permit.signaturePresent == true),
      freshAtResponseTime: ((.permit.freshAtResponseTime // true) != false),
      observedCapability: (.permit.capability // .requiredCapability // ""),
      capabilityOk: ((.permit.capability // .requiredCapability // "") == $expectedCapability),
      catalogOperationId: (.catalogOperationId // ""),
      approvedScriptId: (.approvedScript.scriptId // ""),
      serverOwnedSource: (
        (((.catalogOperationId // "") | length) > 0)
        or (((.approvedScript.scriptId // "") | length) > 0)
        or (((.permit.commandHash // "") | length) > 0)
      ),
      expectedCatalogOk: (($expectedCatalog | length) == 0 or (.catalogOperationId // "") == $expectedCatalog),
      expectedScriptOk: (($expectedScript | length) == 0 or (.approvedScript.scriptId // "") == $expectedScript)
    }
    | .ok = (
      .kindOk
      and .transportPushed
      and .denyAbsent
      and .signaturePresent
      and .freshAtResponseTime
      and .capabilityOk
      and .serverOwnedSource
      and .expectedCatalogOk
      and .expectedScriptOk
    )
    | .reason = (
      if .ok then "permit-transport-evidence-present"
      elif .kindOk | not then "missing-permit"
      elif .transportPushed | not then "missing-transport-push"
      elif .denyAbsent | not then "deny-present"
      elif .signaturePresent | not then "missing-permit-signature"
      elif .freshAtResponseTime | not then "permit-not-fresh"
      elif .capabilityOk | not then "wrong-capability"
      elif .serverOwnedSource | not then "missing-server-owned-source-binding"
      elif .expectedCatalogOk | not then "unexpected-catalog-operation"
      elif .expectedScriptOk | not then "unexpected-approved-script"
      else "operation-evidence-incomplete"
      end
    )' "$file"
}

analyze_recording_rows() {
  local file="$1"
  if [[ -z "$file" ]]; then
    jq -cn '{status:"missing", file:null, ok:false, reason:"recording rows evidence not found"}'
    return 0
  fi

  local rel row_count has_agent_output has_data has_end_stream ok reason
  rel="$(relpath "$file")"
  row_count="$(wc -l < "$file" | tr -d ' ')"

  if [[ "$file" == *.jsonl ]] || head -n 1 "$file" | grep -q '^[[:space:]]*{'; then
    jq -Rn \
      --arg file "$rel" \
      '
      def text: [.. | scalars | tostring] | join(" ");
      [inputs | select(length > 0) | (try fromjson catch {"_raw": .})] as $rows
      | {
          status: "parsed",
          file: $file,
          rowCount: ($rows | length),
          hasAgentOutput: any($rows[]; (text | test("\\bAGENT_OUTPUT\\b"; "i"))),
          hasData: any($rows[]; (text | test("\\bDATA\\b"; "i"))),
          hasEndStream: any($rows[]; (text | test("END[_-]?STREAM|EndStream|endStream|\\bSESSION_END\\b"; "i")))
        }
      | .ok = ((.hasAgentOutput or .hasData) and .hasEndStream)
      | .reason = (
          if .ok then "output-and-end-stream-present"
          elif (.hasAgentOutput or .hasData) | not then "missing-agent-output"
          elif .hasEndStream | not then "missing-end-stream"
          else "recording-evidence-incomplete"
          end
        )' < "$file"
    return 0
  fi

  has_agent_output="false"
  has_data="false"
  has_end_stream="false"
  if LC_ALL=C grep -Eiq '(^|[^A-Z_])AGENT_OUTPUT([^A-Z_]|$)' "$file"; then
    has_agent_output="true"
  fi
  if LC_ALL=C grep -Eiq '(^|[^A-Z_])DATA([^A-Z_]|$)' "$file"; then
    has_data="true"
  fi
  if LC_ALL=C grep -Eiq 'END[_-]?STREAM|EndStream|endStream|(^|[^A-Z_])SESSION_END([^A-Z_]|$)' "$file"; then
    has_end_stream="true"
  fi
  ok="false"
  reason="recording-evidence-incomplete"
  if [[ "$has_agent_output" != "true" && "$has_data" != "true" ]]; then
    reason="missing-agent-output"
  elif [[ "$has_end_stream" != "true" ]]; then
    reason="missing-end-stream"
  else
    ok="true"
    reason="output-and-end-stream-present"
  fi

  jq -cn \
    --arg file "$rel" \
    --arg rowCount "$row_count" \
    --arg hasAgentOutput "$has_agent_output" \
    --arg hasData "$has_data" \
    --arg hasEndStream "$has_end_stream" \
    --arg ok "$ok" \
    --arg reason "$reason" \
    '{
      status: "parsed",
      file: $file,
      rowCount: ($rowCount | tonumber),
      hasAgentOutput: ($hasAgentOutput == "true"),
      hasData: ($hasData == "true"),
      hasEndStream: ($hasEndStream == "true"),
      ok: ($ok == "true"),
      reason: $reason
    }'
}

summarize_smoke_summary() {
  local file="$1"
  if [[ -z "$file" ]]; then
    jq -cn '{file:null, present:false}'
    return 0
  fi
  if ! jq -e . "$file" >/dev/null 2>&1; then
    jq -cn --arg file "$(relpath "$file")" \
      '{file:$file, present:true, validJson:false}'
    return 0
  fi
  jq -c --arg file "$(relpath "$file")" '
    {
      file: $file,
      present: true,
      validJson: true,
      status: (.status // ""),
      operationStatus: (.operationStatus // ""),
      decision: (.decision // ""),
      catalogOperationId: (.catalogOperationId // ""),
      scriptId: (.scriptId // "")
    }' "$file"
}

main() {
  need_cmd jq
  need_cmd wc
  need_cmd head
  need_cmd grep
  need_cmd sed

  [[ -d "$EVIDENCE_DIR" ]] || die "EVIDENCE_DIR is not a directory: $EVIDENCE_DIR"

  local operation_file recording_file smoke_summary_file
  operation_file="$(find_operation_body_file || true)"
  recording_file="$(find_recording_rows_file || true)"
  smoke_summary_file="$(find_smoke_summary_file || true)"

  validate_file_under_evidence_dir "$operation_file" "operation body"
  validate_file_under_evidence_dir "$recording_file" "recording rows"
  validate_file_under_evidence_dir "$smoke_summary_file" "smoke summary"

  local sha_json operation_json recording_json smoke_summary_json
  sha_json="$(analyze_sha256_manifest)"
  operation_json="$(analyze_operation_body "$operation_file")"
  recording_json="$(analyze_recording_rows "$recording_file")"
  smoke_summary_json="$(summarize_smoke_summary "$smoke_summary_file")"

  local raw_negative_ok="false" override_negative_ok="false" disabled_negative_ok="false"
  local authz_negative_ok="false" expired_negative_ok="false" wrong_device_negative_ok="false"
  local replay_negative_ok="false" termination_negative_ok="false"

  if check_negative_category raw_unrestricted_denied \
    raw-pty-deny.body \
    raw-shell-deny.body \
    raw-command-deny.body \
    raw-script-deny.body \
    unrestricted-shell-deny.body \
    powershell-deny.body \
    cmd-deny.body; then
    raw_negative_ok="true"
  fi

  if check_negative_category command_or_policy_override_denied \
    command-override-deny.body \
    wrong-hash-deny.body \
    arg-schema-deny.body \
    policy-hash-deny.body \
    policy-hash-mismatch-deny.body \
    command-policy-deny.body; then
    override_negative_ok="true"
  fi

  if check_negative_category disabled_or_revoked_denied \
    disabled-catalog-deny.body \
    disabled-script-deny.body \
    revoked-script-deny.body; then
    disabled_negative_ok="true"
  fi

  if check_negative_category authz_or_step_up_denied \
    noauth-catalog.body \
    noauth-approved-scripts.body \
    missing-role-deny.body \
    self-approval-deny.body \
    missing-justification-deny.body \
    missing-step-up-deny.body; then
    authz_negative_ok="true"
  fi

  if check_negative_category expired_permit_denied \
    expired-permit-deny.body \
    ttl-expired-deny.body; then
    expired_negative_ok="true"
  fi

  if check_negative_category wrong_device_or_tenant_denied \
    wrong-device-deny.body \
    wrong-tenant-deny.body; then
    wrong_device_negative_ok="true"
  fi

  if check_negative_category replay_denied \
    replay-deny.body \
    sequence-replay-deny.body; then
    replay_negative_ok="true"
  fi

  if check_negative_category termination_evidence \
    heartbeat-loss-evidence.json \
    heartbeat-loss-deny.body \
    kill-revoke-evidence.json \
    revoke-evidence.json \
    mid-session-revoke-evidence.json; then
    termination_negative_ok="true"
  fi

  local core_negatives_ok="false" full_matrix_ok="false"
  if [[ "$raw_negative_ok" == "true" && "$override_negative_ok" == "true" ]]; then
    core_negatives_ok="true"
  fi
  if [[ "$core_negatives_ok" == "true" \
    && "$disabled_negative_ok" == "true" \
    && "$authz_negative_ok" == "true" \
    && "$expired_negative_ok" == "true" \
    && "$wrong_device_negative_ok" == "true" \
    && "$replay_negative_ok" == "true" \
      && "$termination_negative_ok" == "true" ]]; then
    full_matrix_ok="true"
  fi

  local sha_required_json
  sha_required_json="$(analyze_sha256_required_files "$operation_file" "$recording_file")"

  local result reason
  if [[ "$(jq -r '.ok' <<< "$operation_json")" != "true" ]]; then
    result="$(jq -r '.reason' <<< "$operation_json")"
    reason="operation PERMIT/transport evidence is incomplete"
  elif [[ "$(jq -r '.status' <<< "$recording_json")" == "missing" ]]; then
    result="recording-unavailable"
    reason="recording rows file is missing"
  elif [[ "$(jq -r '.ok' <<< "$recording_json")" != "true" ]]; then
    result="$(jq -r '.reason' <<< "$recording_json")"
    reason="recording rows do not prove DATA/AGENT_OUTPUT plus EndStream"
  elif [[ "$REQUIRE_SHA256" == "1" && "$(jq -r '.status' <<< "$sha_json")" != "ok" ]]; then
    result="sha256-unverified"
    reason="SHA256SUMS is required but did not verify cleanly"
  elif [[ "$REQUIRE_SHA256" == "1" && "$(jq -r '.ok' <<< "$sha_required_json")" != "true" ]]; then
    result="sha256-unverified"
    reason="SHA256SUMS does not cover all required evidence files"
  elif [[ "$REQUIRE_NEGATIVES" == "1" && "$core_negatives_ok" != "true" ]]; then
    result="missing-negative"
    reason="core raw-shell and command/policy override deny evidence is required"
  elif [[ "$REQUIRE_FULL_MATRIX" == "1" && "$full_matrix_ok" != "true" ]]; then
    result="missing-full-negative-matrix"
    reason="full #208 lifecycle/authz/replay/termination matrix is required but incomplete"
  else
    result="accepted-candidate"
    reason="PERMIT, transport, recording, checksum, and required negative evidence are present"
  fi

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg result "$result" \
    --arg reason "$reason" \
    --arg evidenceDir "$EVIDENCE_DIR" \
    --arg expectedOperationKind "$EXPECTED_OPERATION_KIND" \
    --arg expectedCapability "$EXPECTED_CAPABILITY" \
    --arg expectedCatalogOperationId "$EXPECTED_CATALOG_OPERATION_ID" \
    --arg expectedApprovedScriptId "$EXPECTED_APPROVED_SCRIPT_ID" \
    --arg requireNegatives "$REQUIRE_NEGATIVES" \
    --arg requireFullMatrix "$REQUIRE_FULL_MATRIX" \
    --arg requireSha256 "$REQUIRE_SHA256" \
    --arg coreNegativesOk "$core_negatives_ok" \
    --arg fullMatrixOk "$full_matrix_ok" \
    --arg rawNegativeOk "$raw_negative_ok" \
    --arg overrideNegativeOk "$override_negative_ok" \
    --arg disabledNegativeOk "$disabled_negative_ok" \
    --arg authzNegativeOk "$authz_negative_ok" \
    --arg expiredNegativeOk "$expired_negative_ok" \
    --arg wrongDeviceNegativeOk "$wrong_device_negative_ok" \
    --arg replayNegativeOk "$replay_negative_ok" \
    --arg terminationNegativeOk "$termination_negative_ok" \
    --argjson operation "$operation_json" \
    --argjson recording "$recording_json" \
    --argjson smokeSummary "$smoke_summary_json" \
    --argjson sha256Manifest "$sha_json" \
    --argjson sha256RequiredFiles "$sha_required_json" \
    --argjson negativeChecks "$NEGATIVE_DETAILS" \
    '{
      generatedAt: $generatedAt,
      result: $result,
      acceptedCandidate: ($result == "accepted-candidate"),
      reason: $reason,
      evidenceDir: $evidenceDir,
      expected: {
        operationKind: $expectedOperationKind,
        capability: $expectedCapability,
        catalogOperationId: $expectedCatalogOperationId,
        approvedScriptId: $expectedApprovedScriptId
      },
      requirements: {
        requireNegatives: ($requireNegatives == "1"),
        requireFullMatrix: ($requireFullMatrix == "1"),
        requireSha256: ($requireSha256 == "1")
      },
      smokeSummary: $smokeSummary,
      operation: $operation,
      recording: $recording,
      sha256Manifest: ($sha256Manifest + {requiredFiles: $sha256RequiredFiles}),
      negatives: {
        coreOk: ($coreNegativesOk == "true"),
        fullMatrixOk: ($fullMatrixOk == "true"),
        categories: {
          rawUnrestrictedDenied: ($rawNegativeOk == "true"),
          commandOrPolicyOverrideDenied: ($overrideNegativeOk == "true"),
          disabledOrRevokedDenied: ($disabledNegativeOk == "true"),
          authzOrStepUpDenied: ($authzNegativeOk == "true"),
          expiredPermitDenied: ($expiredNegativeOk == "true"),
          wrongDeviceOrTenantDenied: ($wrongDeviceNegativeOk == "true"),
          replayDenied: ($replayNegativeOk == "true"),
          terminationEvidence: ($terminationNegativeOk == "true")
        },
        checks: $negativeChecks
      },
      doesNotProve: [
        "signed MSI/GPO rollout",
        "5-PC/50-PC/800-PC readiness",
        "production remote-support readiness",
        "unrestricted shell/RDP/WinRM/SMB/SSH",
        "true TPM/device-key hardware attestation unless platform-backend#548 is separately accepted",
        "full #208 Done state unless the full lifecycle/authz/replay/termination matrix is also attached and accepted"
      ]
    }' > "$SUMMARY_FILE"

  printf 'INFO evidence_dir=%s\n' "$EVIDENCE_DIR"
  printf 'INFO summary_file=%s\n' "$SUMMARY_FILE"
  jq -r '"DECISION " + .result + " reason=" + .reason' "$SUMMARY_FILE"

  if [[ "$REQUIRE_ACCEPTED" == "1" && "$result" != "accepted-candidate" ]]; then
    exit 2
  fi
}

main "$@"
