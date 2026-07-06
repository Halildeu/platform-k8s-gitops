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
SESSION_OWNERSHIP_FILE="${SESSION_OWNERSHIP_FILE:-}"
PILOT_READINESS_FILE="${PILOT_READINESS_FILE:-}"
GOVERNANCE_EVIDENCE_FILE="${GOVERNANCE_EVIDENCE_FILE:-}"
SUMMARY_FILE="${SUMMARY_FILE:-${EVIDENCE_DIR}/verification-summary.json}"

EXPECTED_OPERATION_KIND="${EXPECTED_OPERATION_KIND:-PERMIT}"
EXPECTED_CAPABILITY="${EXPECTED_CAPABILITY:-CONSTRAINED_PTY}"
EXPECTED_CATALOG_OPERATION_ID="${EXPECTED_CATALOG_OPERATION_ID:-}"
EXPECTED_APPROVED_SCRIPT_ID="${EXPECTED_APPROVED_SCRIPT_ID:-}"

REQUIRE_NEGATIVES="${REQUIRE_NEGATIVES:-1}"
REQUIRE_FULL_MATRIX="${REQUIRE_FULL_MATRIX:-0}"
REQUIRE_SHA256="${REQUIRE_SHA256:-1}"
REQUIRE_ACCEPTED="${REQUIRE_ACCEPTED:-0}"
REQUIRE_SESSION_OWNERSHIP="${REQUIRE_SESSION_OWNERSHIP:-1}"
REQUIRE_PILOT_READINESS="${REQUIRE_PILOT_READINESS:-1}"
REQUIRE_GOVERNANCE_EVIDENCE="${REQUIRE_GOVERNANCE_EVIDENCE:-1}"
REQUIRE_EVIDENCE_REDACTION="${REQUIRE_EVIDENCE_REDACTION:-1}"

NEGATIVE_DETAILS="[]"
REDACTION_SCAN_FILES="[]"
REDACTION_FINDINGS="[]"

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

    if body_indicates_denial "$file" || [[ "$http_code" =~ ^(400|401|403|404|409|422)$ ]]; then
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

find_session_ownership_file() {
  if [[ -n "$SESSION_OWNERSHIP_FILE" ]]; then
    resolve_input_file "$SESSION_OWNERSHIP_FILE"
    return 0
  fi
  first_existing_file \
    session-ownership-guard.out \
    session-ownership.out \
    live-session-owner.out
}

find_pilot_readiness_file() {
  if [[ -n "$PILOT_READINESS_FILE" ]]; then
    resolve_input_file "$PILOT_READINESS_FILE"
    return 0
  fi
  first_existing_file \
    pilot-readiness/summary.json \
    pilot-readiness-summary.json \
    pilot-readiness.json \
    readiness-summary.json
}

find_governance_evidence_file() {
  if [[ -n "$GOVERNANCE_EVIDENCE_FILE" ]]; then
    resolve_input_file "$GOVERNANCE_EVIDENCE_FILE"
    return 0
  fi
  first_existing_file \
    governance-evidence.json \
    governance/summary.json \
    approval-evidence.json \
    operator-governance.json
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

analyze_session_ownership() {
  local file="$1"
  if [[ -z "$file" ]]; then
    jq -cn '{status:"missing", file:null, ok:false, reason:"session ownership guard evidence not found"}'
    return 0
  fi

  local rel owned_line has_owned_line="false" session_hash_ok="false" endpoint_hash_ok="false"
  local owner_comment_ok="false" raw_marker_present="false" ok="false" reason="session-ownership-evidence-incomplete"
  rel="$(relpath "$file")"
  owned_line="$(grep -E '^REMOTE_RESPONSE_TERMINAL_SESSION_GUARD_STATUS=owned([[:space:]]|$)' "$file" | tail -n 1 || true)"

  if [[ -n "$owned_line" ]]; then
    has_owned_line="true"
  fi
  if [[ "$owned_line" =~ (^|[[:space:]])session_hash=[a-f0-9]{12}([[:space:]]|$) ]]; then
    session_hash_ok="true"
  fi
  if [[ "$owned_line" =~ (^|[[:space:]])endpoint_hash=[a-f0-9]{12}([[:space:]]|$) ]]; then
    endpoint_hash_ok="true"
  fi
  if [[ "$owned_line" =~ (^|[[:space:]])owner_comment_id=[0-9]+([[:space:]]|$) ]]; then
    owner_comment_ok="true"
  fi
  if LC_ALL=C grep -Eiq 'Bearer|Authorization|eyJ[A-Za-z0-9_-]{10,}|access_token|client_secret|privateKey|BEGIN PRIVATE|OPERATOR_BEARER_TOKEN|REMOTE_BRIDGE_SESSION_ID=' "$file"; then
    raw_marker_present="true"
  fi

  if [[ "$has_owned_line" != "true" ]]; then
    reason="missing-owned-status"
  elif [[ "$session_hash_ok" != "true" || "$endpoint_hash_ok" != "true" ]]; then
    reason="missing-redacted-session-or-endpoint-hash"
  elif [[ "$owner_comment_ok" != "true" ]]; then
    reason="missing-owner-comment-id"
  elif [[ "$raw_marker_present" == "true" ]]; then
    reason="session-ownership-evidence-leaks-sensitive-marker"
  else
    ok="true"
    reason="redacted-session-ownership-present"
  fi

  jq -cn \
    --arg file "$rel" \
    --arg hasOwnedLine "$has_owned_line" \
    --arg sessionHashOk "$session_hash_ok" \
    --arg endpointHashOk "$endpoint_hash_ok" \
    --arg ownerCommentOk "$owner_comment_ok" \
    --arg rawMarkerPresent "$raw_marker_present" \
    --arg ok "$ok" \
    --arg reason "$reason" \
    '{
      status: "parsed",
      file: $file,
      hasOwnedStatus: ($hasOwnedLine == "true"),
      sessionHashRedacted: ($sessionHashOk == "true"),
      endpointHashRedacted: ($endpointHashOk == "true"),
      ownerCommentPresent: ($ownerCommentOk == "true"),
      sensitiveMarkerPresent: ($rawMarkerPresent == "true"),
      ok: ($ok == "true"),
      reason: $reason
    }'
}

analyze_pilot_readiness() {
  local file="$1"
  if [[ -z "$file" ]]; then
    jq -cn '{status:"missing", file:null, ok:false, reason:"pilot readiness summary not found"}'
    return 0
  fi
  if ! jq -e . "$file" >/dev/null 2>&1; then
    jq -cn --arg file "$(relpath "$file")" \
      '{status:"invalid-json", file:$file, ok:false, reason:"pilot readiness summary is not valid JSON"}'
    return 0
  fi

  jq -c --arg file "$(relpath "$file")" '
    . as $root
    | ($root.manifest.expectedReleaseTag // "") as $expectedReleaseTag
    | ($root.manifest.expectedAgentVersion // "") as $expectedAgentVersion
    | ($root.targetEndpoint.observed.agent_version // "") as $observedVersion
    | {
        status: "parsed",
        file: $file,
        decision: ($root.decision // ""),
        reasonText: ($root.reason // ""),
        manifestOk: ($root.manifest.ok == true),
        expectedReleaseTag: $expectedReleaseTag,
        expectedAgentVersion: $expectedAgentVersion,
        observedAgentVersion: $observedVersion,
        targetEndpointPresent: (($root.targetEndpoint.observed // null) != null),
        decisionOk: (($root.decision // "") == "ready-for-product-smoke"),
        versionOk: (
          ($observedVersion | length) > 0
          and (
            ($expectedReleaseTag | length) > 0 and $observedVersion == $expectedReleaseTag
            or ($expectedAgentVersion | length) > 0 and $observedVersion == $expectedAgentVersion
            or ($expectedAgentVersion | length) > 0 and ($observedVersion | contains($expectedAgentVersion))
            or ($expectedReleaseTag | length) > 0 and ($observedVersion | contains($expectedReleaseTag))
          )
        )
      }
    | .ok = (.decisionOk and .manifestOk and .targetEndpointPresent and .versionOk)
    | .reason = (
        if .ok then "pilot-ready-for-product-smoke"
        elif .decisionOk | not then "pilot-not-ready"
        elif .manifestOk | not then "pilot-artifact-manifest-mismatch"
        elif .targetEndpointPresent | not then "pilot-target-endpoint-missing"
        elif .versionOk | not then "pilot-agent-version-mismatch"
        else "pilot-readiness-incomplete"
        end
      )' "$file"
}

analyze_governance_evidence() {
  local file="$1"
  if [[ -z "$file" ]]; then
    jq -cn '{status:"missing", file:null, ok:false, reason:"governance evidence not found"}'
    return 0
  fi

  local rel raw_marker_present="false"
  rel="$(relpath "$file")"
  if LC_ALL=C grep -Eiq 'Bearer|Authorization|eyJ[A-Za-z0-9_-]{10,}|access_token|refresh_token|client_secret|secret_key|api_key|privateKey|BEGIN PRIVATE|OPERATOR_BEARER_TOKEN|REMOTE_BRIDGE_SESSION_ID=|password' "$file"; then
    raw_marker_present="true"
  fi

  if ! jq -e . "$file" >/dev/null 2>&1; then
    jq -cn --arg file "$rel" \
      '{status:"invalid-json", file:$file, ok:false, reason:"governance evidence is not valid JSON"}'
    return 0
  fi

  jq -c \
    --arg file "$rel" \
    --arg rawMarkerPresent "$raw_marker_present" \
    '
    . as $root
    | (($root.operator.subject // $root.operator.id // $root.operatorSubject // "") | tostring) as $operatorSubject
    | (($root.approver.subject // $root.approver.id // $root.approverSubject // "") | tostring) as $approverSubject
    | (($root.approval.id // $root.approvalId // "") | tostring) as $approvalId
    | (
        $root.ticketRef
        // (if ($root.ticket | type) == "object" then ($root.ticket.ref // $root.ticket.id) else $root.ticket end)
        // $root.ticketId
        // ""
      | tostring) as $ticketRef
    | (
        (if ($root.justification | type) == "object" then $root.justification.text else $root.justification end)
        // $root.reason
        // ""
      | tostring) as $justification
    | (($root.stepUp.verified == true) or ($root.stepUpVerified == true)) as $stepUpVerified
    | (
        ($root.recording.worm == true)
        or ($root.recording.wormEnabled == true)
        or ($root.wormRecording.enabled == true)
        or (($root.recording.mode // "") | tostring | ascii_downcase) == "worm"
      ) as $wormRecordingEnabled
    | (
        ($root.recording.failClosed == true)
        or ($root.wormRecording.failClosed == true)
        or (($root.recording.mode // "") | tostring | ascii_downcase) == "fail-closed"
        or (($root.recording.failurePolicy // "") | tostring | ascii_downcase) == "fail-closed"
      ) as $recordingFailClosed
    | {
        status: "parsed",
        file: $file,
        operatorSubjectPresent: (($operatorSubject | length) > 0),
        approverSubjectPresent: (($approverSubject | length) > 0),
        distinctOperatorApprover: (($operatorSubject | length) > 0 and ($approverSubject | length) > 0 and $operatorSubject != $approverSubject),
        approvalIdPresent: (($approvalId | length) > 0),
        stepUpVerified: $stepUpVerified,
        ticketRefPresent: (($ticketRef | length) > 0),
        justificationPresent: (($justification | length) > 0),
        wormRecordingEnabled: $wormRecordingEnabled,
        recordingFailClosed: $recordingFailClosed,
        sensitiveMarkerPresent: ($rawMarkerPresent == "true")
      }
    | .ok = (
        .operatorSubjectPresent
        and .approverSubjectPresent
        and .distinctOperatorApprover
        and .approvalIdPresent
        and .stepUpVerified
        and .ticketRefPresent
        and .justificationPresent
        and .wormRecordingEnabled
        and .recordingFailClosed
        and (.sensitiveMarkerPresent | not)
      )
    | .reason = (
        if .ok then "governance-evidence-present"
        elif .sensitiveMarkerPresent then "governance-evidence-leaks-sensitive-marker"
        elif (.operatorSubjectPresent | not) then "governance-operator-missing"
        elif (.approverSubjectPresent | not) then "governance-approver-missing"
        elif (.distinctOperatorApprover | not) then "governance-operator-approver-not-distinct"
        elif (.approvalIdPresent | not) then "governance-approval-id-missing"
        elif (.stepUpVerified | not) then "governance-step-up-missing"
        elif (.ticketRefPresent | not) then "governance-ticket-missing"
        elif (.justificationPresent | not) then "governance-justification-missing"
        elif (.wormRecordingEnabled | not) then "governance-worm-recording-missing"
        elif (.recordingFailClosed | not) then "governance-recording-not-fail-closed"
        else "governance-evidence-incomplete"
        end
      )' "$file"
}

redaction_add_scan_file() {
  local file="$1" rel
  [[ -n "$file" && -f "$file" ]] || return 0
  rel="$(relpath "$file")"

  case "$rel" in
    SHA256SUMS|verification-summary.json|runtime-smoke-plan.json|governance-evidence-summary.json|recording-summary.json|binary-headers.txt|port-forward.log)
      return 0
      ;;
  esac

  REDACTION_SCAN_FILES="$(jq -cn \
    --argjson arr "$REDACTION_SCAN_FILES" \
    --arg file "$rel" \
    'if any($arr[]; . == $file) then $arr else $arr + [$file] end')"
}

redaction_add_discovered_files() {
  local file
  while IFS= read -r -d '' file; do
    redaction_add_scan_file "$file"
  done < <(find "$EVIDENCE_DIR" -type f \( \
      -name '*.body' \
      -o -name '*.request.json' \
      -o -name '*.request' \
      -o -name '*.jsonl' \
      -o -name '*.tsv' \
      -o -name '*.psv' \
      -o -name '*.csv' \
      -o -name 'session-ownership*.out' \
      -o -name 'live-session-owner.out' \
    \) -print0)
}

redaction_record_finding() {
  local file="$1" marker_class="$2"
  REDACTION_FINDINGS="$(jq -cn \
    --argjson arr "$REDACTION_FINDINGS" \
    --arg file "$file" \
    --arg markerClass "$marker_class" \
    '$arr + [{file: $file, markerClass: $markerClass}]')"
}

redaction_scan_marker() {
  local rel="$1" file="$2" marker_class="$3" pattern="$4"
  if LC_ALL=C grep -Eiq -- "$pattern" "$file"; then
    redaction_record_finding "$rel" "$marker_class"
  fi
}

redaction_scan_file() {
  local rel="$1"
  local file="${EVIDENCE_DIR}/${rel}"
  [[ -f "$file" ]] || return 0

  redaction_scan_marker "$rel" "$file" "bearer-token" \
    'Bearer[[:space:]]+[A-Za-z0-9._~+/=-]{10,}'
  redaction_scan_marker "$rel" "$file" "authorization-header" \
    'Authorization[[:space:]]*:[[:space:]]*Bearer[[:space:]]+[A-Za-z0-9._~+/=-]{10,}'
  redaction_scan_marker "$rel" "$file" "jwt" \
    'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'
  redaction_scan_marker "$rel" "$file" "oauth-token" \
    '(access_token|refresh_token)[[:space:]]*[:=][[:space:]]*["'\'']?[A-Za-z0-9._~+/=-]{16,}'
  redaction_scan_marker "$rel" "$file" "client-secret" \
    '(client_secret|secret_key|api_key)[[:space:]]*[:=][[:space:]]*["'\'']?[A-Za-z0-9._~+/=-]{16,}'
  redaction_scan_marker "$rel" "$file" "private-key" \
    '-----BEGIN ((RSA|EC|OPENSSH)[[:space:]])?PRIVATE KEY-----|"privateKey"[[:space:]]*:[[:space:]]*"[^"<]{20,}"'
  redaction_scan_marker "$rel" "$file" "operator-token-env" \
    'OPERATOR_BEARER_TOKEN[[:space:]]*[:=][[:space:]]*["'\'']?[A-Za-z0-9._~+/=-]{16,}'
  redaction_scan_marker "$rel" "$file" "session-secret" \
    '("?(REMOTE_BRIDGE_SESSION_ID|remoteBridgeSessionId|remote_bridge_session_id|session_token|session_secret|session_key)"?[[:space:]]*[:=][[:space:]]*["'\'']?[A-Za-z0-9._:-]{12,})'
  redaction_scan_marker "$rel" "$file" "pg-credential" \
    'PGPASSWORD[[:space:]]*=|postgresql://[^[:space:]@/]+:[^[:space:]@]+@'
}

analyze_evidence_redaction() {
  local file rel scanned_count finding_count ok="true" status="ok" reason="no-sensitive-marker-detected"
  REDACTION_SCAN_FILES="[]"
  REDACTION_FINDINGS="[]"

  for file in "$@"; do
    redaction_add_scan_file "$file"
  done

  while IFS= read -r rel; do
    [[ -n "$rel" ]] || continue
    redaction_add_scan_file "${EVIDENCE_DIR}/${rel}"
  done < <(jq -r '.[] | select(.file != null) | .file' <<< "$NEGATIVE_DETAILS")

  redaction_add_discovered_files

  while IFS= read -r rel; do
    [[ -n "$rel" ]] || continue
    redaction_scan_file "$rel"
  done < <(jq -r '.[]' <<< "$REDACTION_SCAN_FILES")

  scanned_count="$(jq 'length' <<< "$REDACTION_SCAN_FILES")"
  finding_count="$(jq 'length' <<< "$REDACTION_FINDINGS")"

  if [[ "$finding_count" != "0" ]]; then
    ok="false"
    status="finding"
    reason="evidence-bundle-contains-sensitive-marker"
  elif [[ "$scanned_count" == "0" ]]; then
    status="no-files-scanned"
    reason="no-verifier-relevant-files-found-for-redaction-scan"
  fi

  jq -cn \
    --arg required "$REQUIRE_EVIDENCE_REDACTION" \
    --arg ok "$ok" \
    --arg status "$status" \
    --arg reason "$reason" \
    --arg scannedCount "$scanned_count" \
    --arg findingCount "$finding_count" \
    --argjson scannedFiles "$REDACTION_SCAN_FILES" \
    --argjson findings "$REDACTION_FINDINGS" \
    '{
      required: ($required == "1"),
      ok: ($ok == "true"),
      status: $status,
      reason: $reason,
      scannedFilesCount: ($scannedCount | tonumber),
      findingCount: ($findingCount | tonumber),
      scannedFiles: $scannedFiles,
      findings: $findings
    }'
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
  need_cmd find

  [[ -d "$EVIDENCE_DIR" ]] || die "EVIDENCE_DIR is not a directory: $EVIDENCE_DIR"

  local operation_file recording_file smoke_summary_file
  local session_ownership_file pilot_readiness_file governance_evidence_file
  operation_file="$(find_operation_body_file || true)"
  recording_file="$(find_recording_rows_file || true)"
  smoke_summary_file="$(find_smoke_summary_file || true)"
  session_ownership_file="$(find_session_ownership_file || true)"
  pilot_readiness_file="$(find_pilot_readiness_file || true)"
  governance_evidence_file="$(find_governance_evidence_file || true)"

  validate_file_under_evidence_dir "$operation_file" "operation body"
  validate_file_under_evidence_dir "$recording_file" "recording rows"
  validate_file_under_evidence_dir "$smoke_summary_file" "smoke summary"
  validate_file_under_evidence_dir "$session_ownership_file" "session ownership"
  validate_file_under_evidence_dir "$pilot_readiness_file" "pilot readiness"
  validate_file_under_evidence_dir "$governance_evidence_file" "governance evidence"

  local sha_json operation_json recording_json smoke_summary_json session_ownership_json pilot_readiness_json governance_evidence_json evidence_redaction_json
  sha_json="$(analyze_sha256_manifest)"
  operation_json="$(analyze_operation_body "$operation_file")"
  recording_json="$(analyze_recording_rows "$recording_file")"
  smoke_summary_json="$(summarize_smoke_summary "$smoke_summary_file")"
  session_ownership_json="$(analyze_session_ownership "$session_ownership_file")"
  pilot_readiness_json="$(analyze_pilot_readiness "$pilot_readiness_file")"
  governance_evidence_json="$(analyze_governance_evidence "$governance_evidence_file")"

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
    closed-session-deny.body \
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

  evidence_redaction_json="$(analyze_evidence_redaction \
    "$operation_file" \
    "$recording_file" \
    "$smoke_summary_file" \
    "$session_ownership_file" \
    "$pilot_readiness_file" \
    "$governance_evidence_file")"

  local sha_required_json
  sha_required_json="$(analyze_sha256_required_files "$operation_file" "$recording_file" "$session_ownership_file" "$pilot_readiness_file" "$governance_evidence_file")"

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
  elif [[ "$REQUIRE_SESSION_OWNERSHIP" == "1" && "$(jq -r '.status' <<< "$session_ownership_json")" == "missing" ]]; then
    result="missing-session-ownership"
    reason="redacted live-session ownership guard evidence is required"
  elif [[ "$REQUIRE_SESSION_OWNERSHIP" == "1" && "$(jq -r '.ok' <<< "$session_ownership_json")" != "true" ]]; then
    result="invalid-session-ownership"
    reason="session ownership guard evidence is incomplete or leaks a sensitive marker"
  elif [[ "$REQUIRE_PILOT_READINESS" == "1" && "$(jq -r '.status' <<< "$pilot_readiness_json")" == "missing" ]]; then
    result="missing-pilot-readiness"
    reason="pilot readiness summary proving expected endpoint agent version is required"
  elif [[ "$REQUIRE_PILOT_READINESS" == "1" && "$(jq -r '.ok' <<< "$pilot_readiness_json")" != "true" ]]; then
    result="invalid-pilot-readiness"
    reason="pilot readiness summary does not prove ready-for-product-smoke with expected agent version"
  elif [[ "$REQUIRE_GOVERNANCE_EVIDENCE" == "1" && "$(jq -r '.status' <<< "$governance_evidence_json")" == "missing" ]]; then
    result="missing-governance-evidence"
    reason="governance evidence proving dual-control, step-up, justification, ticket, and fail-closed recording policy is required"
  elif [[ "$REQUIRE_GOVERNANCE_EVIDENCE" == "1" && "$(jq -r '.ok' <<< "$governance_evidence_json")" != "true" ]]; then
    result="invalid-governance-evidence"
    reason="governance evidence is incomplete, self-approved, lacks step-up/ticket/recording policy, or leaks a sensitive marker"
  elif [[ "$REQUIRE_EVIDENCE_REDACTION" == "1" && "$(jq -r '.ok' <<< "$evidence_redaction_json")" != "true" ]]; then
    result="sensitive-evidence-marker"
    reason="evidence bundle contains sensitive marker classes; redact before accepted candidate"
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
    reason="PERMIT, transport"
    if [[ "$REQUIRE_SESSION_OWNERSHIP" == "1" ]]; then
      reason="${reason}, redacted session ownership"
    fi
    if [[ "$REQUIRE_PILOT_READINESS" == "1" ]]; then
      reason="${reason}, pilot readiness"
    fi
    if [[ "$REQUIRE_GOVERNANCE_EVIDENCE" == "1" ]]; then
      reason="${reason}, governance evidence"
    fi
    if [[ "$REQUIRE_EVIDENCE_REDACTION" == "1" ]]; then
      reason="${reason}, redaction guard"
    fi
    reason="${reason}, recording, checksum, and required negative evidence are present"
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
    --arg requireSessionOwnership "$REQUIRE_SESSION_OWNERSHIP" \
    --arg requirePilotReadiness "$REQUIRE_PILOT_READINESS" \
    --arg requireGovernanceEvidence "$REQUIRE_GOVERNANCE_EVIDENCE" \
    --arg requireEvidenceRedaction "$REQUIRE_EVIDENCE_REDACTION" \
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
    --argjson sessionOwnership "$session_ownership_json" \
    --argjson pilotReadiness "$pilot_readiness_json" \
    --argjson governanceEvidence "$governance_evidence_json" \
    --argjson evidenceRedaction "$evidence_redaction_json" \
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
        requireSha256: ($requireSha256 == "1"),
        requireSessionOwnership: ($requireSessionOwnership == "1"),
        requirePilotReadiness: ($requirePilotReadiness == "1"),
        requireGovernanceEvidence: ($requireGovernanceEvidence == "1"),
        requireEvidenceRedaction: ($requireEvidenceRedaction == "1")
      },
      smokeSummary: $smokeSummary,
      sessionOwnership: $sessionOwnership,
      pilotReadiness: $pilotReadiness,
      governanceEvidence: $governanceEvidence,
      evidenceRedaction: $evidenceRedaction,
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
        "broker-side enforcement from the session ownership comment alone",
        "operator identity beyond the captured governance evidence",
        "absence of all possible secrets beyond the configured high-confidence evidence redaction scan",
        "fresh endpoint readiness beyond the captured pilot readiness timestamp",
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
