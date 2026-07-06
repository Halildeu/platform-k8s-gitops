#!/usr/bin/env bash
# shellcheck disable=SC2016 # jq filters intentionally use jq regex quoting.
set -euo pipefail

# Faz 22.6.3 Remote Response Terminal governance evidence export helper.
#
# This script is read-only/offline. It normalizes an already captured product
# governance JSON document into the verifier's canonical governance-evidence
# shape. It never opens a remote-bridge session, dispatches operations, reads or
# writes credentials, mutates Kubernetes/GitOps/DB state, or fabricates missing
# operator/approval fields from env vars.

EVIDENCE_DIR="${EVIDENCE_DIR:-/tmp/remote-response-terminal-governance-$(date -u +%Y%m%dT%H%M%SZ)}"
SOURCE_GOVERNANCE_FILE="${SOURCE_GOVERNANCE_FILE:-}"
GOVERNANCE_EVIDENCE_FILE="${GOVERNANCE_EVIDENCE_FILE:-${EVIDENCE_DIR}/governance-evidence.json}"
GOVERNANCE_SUMMARY_FILE="${GOVERNANCE_SUMMARY_FILE:-${EVIDENCE_DIR}/governance-evidence-summary.json}"
REQUIRE_VALID="${REQUIRE_VALID:-1}"

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

canonical_dir() {
  local path="$1"
  (cd "$path" 2>/dev/null && pwd -P) || return 1
}

resolve_input_file() {
  local path="$1"
  case "$path" in
    /*) printf '%s\n' "$path" ;;
    *) printf '%s\n' "${EVIDENCE_DIR}/${path}" ;;
  esac
}

first_existing_source_file() {
  local candidate
  if [[ -n "$SOURCE_GOVERNANCE_FILE" ]]; then
    resolve_input_file "$SOURCE_GOVERNANCE_FILE"
    return 0
  fi
  for candidate in \
    product-governance.json \
    governance-source.json \
    operation-governance-source.json \
    approval-evidence.raw.json \
    operator-governance.raw.json \
    remote-response-governance.raw.json \
    approval-evidence.json \
    operator-governance.json \
    governance/summary.json; do
    if [[ -f "${EVIDENCE_DIR}/${candidate}" ]]; then
      printf '%s\n' "${EVIDENCE_DIR}/${candidate}"
      return 0
    fi
  done
  return 1
}

sha256_file() {
  local file="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  else
    die "missing command: shasum or sha256sum"
  fi
}

source_file_label() {
  local file="$1"
  local evidence_abs file_dir_abs file_abs
  evidence_abs="$(canonical_dir "$EVIDENCE_DIR")" || return 1
  file_dir_abs="$(canonical_dir "$(dirname "$file")")" || return 1
  file_abs="${file_dir_abs}/$(basename "$file")"
  case "$file_abs" in
    "$evidence_abs"/*) printf '%s' "${file_abs#"$evidence_abs"/}" ;;
    *) printf 'external:%s' "$(basename "$file")" ;;
  esac
}

missing_source_label() {
  local file="$1"
  [[ -n "$file" ]] || return 0
  case "$file" in
    /*) printf 'external:%s' "$(basename "$file")" ;;
    *) printf '%s' "$file" ;;
  esac
}

analyze_source() {
  local file="$1"
  if [[ -z "$file" ]]; then
    jq -n \
      --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      '{
        generatedAt: $generatedAt,
        status: "missing",
        ok: false,
        reason: "source-governance-evidence-not-found",
        sourceFile: null,
        canonicalFile: null
      }'
    return 0
  fi

  if [[ ! -f "$file" ]]; then
    local missing_label
    missing_label="$(missing_source_label "$file")"
    jq -n \
      --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --arg sourceFile "$missing_label" \
      '{
        generatedAt: $generatedAt,
        status: "missing",
        ok: false,
        reason: "source-governance-evidence-not-found",
        sourceFile: $sourceFile,
        canonicalFile: null
      }'
    return 0
  fi

  local source_label source_sha raw_marker_present="false"
  source_label="$(source_file_label "$file")"
  source_sha="$(sha256_file "$file")"

  if LC_ALL=C grep -Eiq 'Bearer|Authorization|eyJ[A-Za-z0-9_-]{10,}|access_token|refresh_token|client_secret|secret_key|api_key|privateKey|BEGIN PRIVATE|OPERATOR_BEARER_TOKEN|REMOTE_BRIDGE_SESSION_ID=|password' "$file"; then
    raw_marker_present="true"
  fi

  if ! jq -e . "$file" >/dev/null 2>&1; then
    jq -n \
      --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --arg sourceFile "$source_label" \
      --arg sourceSha256 "$source_sha" \
      '{
        generatedAt: $generatedAt,
        status: "invalid-json",
        ok: false,
        reason: "source-governance-evidence-invalid-json",
        sourceFile: $sourceFile,
        sourceSha256: $sourceSha256,
        canonicalFile: null
      }'
    return 0
  fi

  jq -c \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg sourceFile "$source_label" \
    --arg sourceSha256 "$source_sha" \
    --arg canonicalFile "$(basename "$GOVERNANCE_EVIDENCE_FILE")" \
    --arg rawMarkerPresent "$raw_marker_present" \
    '
    . as $root
    | (($root.operator.subject // $root.operator.id // $root.operatorSubject // $root.session.operator.subject // $root.actor.operator.subject // "") | tostring) as $operatorSubject
    | (($root.approver.subject // $root.approver.id // $root.approverSubject // $root.approval.approver.subject // $root.session.approver.subject // "") | tostring) as $approverSubject
    | (($root.approval.id // $root.approvalId // $root.approval.approvalId // $root.session.approvalId // "") | tostring) as $approvalId
    | (
        $root.ticketRef
        // (if ($root.ticket | type) == "object" then ($root.ticket.ref // $root.ticket.id) else $root.ticket end)
        // $root.ticketId
        // $root.changeRequest
        // ""
      | tostring) as $ticketRef
    | (
        (if ($root.justification | type) == "object" then $root.justification.text else $root.justification end)
        // $root.reason
        // $root.operatorJustification
        // ""
      | tostring) as $justification
    | (($root.stepUp.verified == true) or ($root.stepUpVerified == true) or ($root.authentication.stepUpVerified == true)) as $stepUpVerified
    | (($root.stepUp.method // $root.stepUpMethod // $root.authentication.method // "") | tostring) as $stepUpMethod
    | (
        ($root.recording.worm == true)
        or ($root.recording.wormEnabled == true)
        or ($root.wormRecording.enabled == true)
        or (($root.recording.mode // "") | tostring | ascii_downcase) == "worm"
        or (($root.recording.retention // "") | tostring | ascii_downcase) == "worm"
      ) as $wormRecordingEnabled
    | (
        ($root.recording.failClosed == true)
        or ($root.wormRecording.failClosed == true)
        or (($root.recording.mode // "") | tostring | ascii_downcase) == "fail-closed"
        or (($root.recording.failurePolicy // "") | tostring | ascii_downcase) == "fail-closed"
        or (($root.audit.failurePolicy // "") | tostring | ascii_downcase) == "fail-closed"
      ) as $recordingFailClosed
    | {
        generatedAt: $generatedAt,
        status: "parsed",
        sourceFile: $sourceFile,
        sourceSha256: $sourceSha256,
        canonicalFile: $canonicalFile,
        operatorSubjectPresent: (($operatorSubject | length) > 0),
        approverSubjectPresent: (($approverSubject | length) > 0),
        distinctOperatorApprover: (($operatorSubject | length) > 0 and ($approverSubject | length) > 0 and $operatorSubject != $approverSubject),
        approvalIdPresent: (($approvalId | length) > 0),
        stepUpVerified: $stepUpVerified,
        stepUpMethodPresent: (($stepUpMethod | length) > 0),
        ticketRefPresent: (($ticketRef | length) > 0),
        justificationPresent: (($justification | length) > 0),
        wormRecordingEnabled: $wormRecordingEnabled,
        recordingFailClosed: $recordingFailClosed,
        sensitiveMarkerPresent: ($rawMarkerPresent == "true"),
        canonical: {
          operator: {subject: $operatorSubject},
          approver: {subject: $approverSubject},
          approval: {id: $approvalId},
          stepUp: {verified: $stepUpVerified, method: $stepUpMethod},
          ticketRef: $ticketRef,
          justification: $justification,
          recording: {worm: $wormRecordingEnabled, failClosed: $recordingFailClosed},
          source: {
            normalizedBy: "remote-response-terminal-governance-export.sh",
            sourceFile: $sourceFile,
            sourceSha256: $sourceSha256
          }
        },
	        doesNotProve: [
	          "live terminal dispatch",
	          "EndpointAgent expected-version heartbeat",
	          "PERMIT transport result",
          "AGENT_OUTPUT/DATA recording",
          "negative deny matrix",
          "platform-agent#208 Done state"
        ]
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
        if .ok then "governance-evidence-export-ready"
        elif .sensitiveMarkerPresent then "source-governance-evidence-leaks-sensitive-marker"
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

write_canonical() {
  local summary="$1" tmp
  if [[ "$(jq -r '.ok' <<< "$summary")" != "true" ]]; then
    rm -f "$GOVERNANCE_EVIDENCE_FILE"
    return 0
  fi
  tmp="$(mktemp "${TMPDIR:-/tmp}/rtt-governance-evidence.XXXXXX")"
  jq '.canonical' <<< "$summary" > "$tmp"
  mv "$tmp" "$GOVERNANCE_EVIDENCE_FILE"
}

write_summary() {
  local summary="$1" tmp
  tmp="$(mktemp "${TMPDIR:-/tmp}/rtt-governance-summary.XXXXXX")"
  jq 'del(.canonical)' <<< "$summary" > "$tmp"
  mv "$tmp" "$GOVERNANCE_SUMMARY_FILE"
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
    sums_file="$(mktemp "${TMPDIR:-/tmp}/rtt-governance-sha256.XXXXXX")"
    find . -type f ! -name SHA256SUMS -print0 \
      | sort -z \
      | xargs -0 "${hasher[@]}" \
      > "$sums_file"
    mv "$sums_file" SHA256SUMS
  )
}

main() {
  need_cmd jq
  need_cmd mktemp
  need_cmd grep
  bool_env "$REQUIRE_VALID" REQUIRE_VALID

  mkdir -p "$EVIDENCE_DIR"

  local source_file="" summary
  source_file="$(first_existing_source_file || true)"
  summary="$(analyze_source "$source_file")"
  write_canonical "$summary"
  write_summary "$summary"
  sha256_manifest

  printf 'INFO evidence_dir=%s\n' "$EVIDENCE_DIR"
  jq -r '"GOVERNANCE_EXPORT result=" + .reason + " ok=" + (.ok|tostring)' \
    "$GOVERNANCE_SUMMARY_FILE"

  if [[ "$REQUIRE_VALID" == "1" && "$(jq -r '.ok' "$GOVERNANCE_SUMMARY_FILE")" != "true" ]]; then
    exit 2
  fi
}

main "$@"
