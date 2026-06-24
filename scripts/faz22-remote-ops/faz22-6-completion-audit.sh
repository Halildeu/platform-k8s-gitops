#!/usr/bin/env bash
# Conservative Faz 22.6 completion audit.
#
# This helper does not mutate GitHub, Kubernetes, or endpoint state. It gathers
# enough public/control-plane truth to prevent bounded pilot or source-only
# evidence from being over-reported as full Faz 22.6 completion.

set -euo pipefail

GITOPS_REPO="${GITOPS_REPO:-Halildeu/platform-k8s-gitops}"
BACKEND_REPO="${BACKEND_REPO:-Halildeu/platform-backend}"
AGENT_REPO="${AGENT_REPO:-Halildeu/platform-agent}"
WEB_REPO="${WEB_REPO:-Halildeu/platform-web}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/faz22-remote-ops/endpoint-agent-release-policy.sh
source "$SCRIPT_DIR/endpoint-agent-release-policy.sh"
endpoint_agent_release_policy_load "$REPO_ROOT"

SSH_TARGET="${SSH_TARGET:-staging-sw}"
REMOTE_BRIDGE_KUBECTL_MODE="${REMOTE_BRIDGE_KUBECTL_MODE:-ssh}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
EXPECTED_REMOTE_BRIDGE_DIGEST="${EXPECTED_REMOTE_BRIDGE_DIGEST:-sha256:6b12276cea912345dcfbcf2e5e920931de813b8aa483b6b2351c75e4b5331a9c}"
B1_4_ATTESTATION_ACCEPTANCE_REF="${B1_4_ATTESTATION_ACCEPTANCE_REF:-Halildeu/platform-backend#548}"
B1_4_RISK_ACCEPTANCE_FORBIDDEN_CLAIMS="${B1_4_RISK_ACCEPTANCE_FORBIDDEN_CLAIMS:-tpm-complete,hardware-attestation-complete,5-device,50-device,800-device,production,broad-rollout}"
VIEW_ONLY_ACCEPTANCE_REF="${VIEW_ONLY_ACCEPTANCE_REF:-Halildeu/platform-k8s-gitops#1580}"
VIEW_ONLY_FORBIDDEN_CLAIMS="${VIEW_ONLY_FORBIDDEN_CLAIMS:-rdp,credential-entry,raw-shell,port-forward,5-device,50-device,800-device,production,broad-rollout}"
EXPECTED_AGENT_TAG="${EXPECTED_AGENT_TAG:-$EXPECTED_AGENT_LATEST_TAG}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'F22_6_AUDIT_ERROR=missing-command:%s\n' "$1"
    exit 2
  }
}

shell_quote() {
  local value="$1"
  printf "'%s'" "$(printf '%s' "$value" | sed "s/'/'\\\\''/g")"
}

fetch_url() {
  # fetch_url <url>
  case "$1" in
    https://*) ;;
    file://*)
      [ "${F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS:-0}" = "1" ] || return 1
      ;;
    *) return 1 ;;
  esac
  curl --max-time "${CURL_MAX_TIME:-20}" -fsSL -H 'Cache-Control: no-cache' "$1"
}

sha256_stream() {
  # Reads bytes from stdin and prints a lowercase hex SHA256.
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | awk '{print $1}'
    return 0
  fi
  return 1
}

lower_hex() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

lineage_print_check() {
  local label="$1" status="$2"
  shift 2
  printf '%s=%s' "$label" "$status"
  if [ "$#" -gt 0 ]; then
    printf ' %s' "$*"
  fi
  printf '\n'
}

waiver_field() {
  # waiver_field <key>; reads the issue body from stdin.
  local key="$1"
  sed -n "s/^${key}:[[:space:]]*//p" | head -1
}

csv_has() {
  local csv="$1" value="$2"
  csv="$(printf '%s' "$csv" | tr -d ' ')"
  case ",$csv," in
    *,"$value",*) return 0 ;;
  esac
  return 1
}

owner_is_invalid() {
  local owner="$1" owner_lc
  owner_lc="$(printf '%s' "$owner" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [ -z "$owner_lc" ] && return 0
  case "$owner_lc" in
    tbd|none|n/a|na|placeholder|owner|named-owner) return 0 ;;
  esac
  return 1
}

date_window_errors() {
  # date_window_errors <approved_at> <expires_at-or-empty>
  local approved_at="$1" expires_at="${2:-}" today
  local missing=()
  if ! [[ "$approved_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    missing+=("approved_at")
  fi
  if [ -n "$expires_at" ] && ! [[ "$expires_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    missing+=("expires_at")
  fi
  if [[ "$approved_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] \
    && [ -n "$expires_at" ] \
    && [[ "$expires_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] \
    && [[ "$approved_at" > "$expires_at" ]]; then
    missing+=("approved_at-after-expires_at")
  fi
  today="$(date -u +%Y-%m-%d 2>/dev/null || true)"
  if ! [[ "$today" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    missing+=("today-unparseable")
  else
    if [[ "$approved_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && [[ "$approved_at" > "$today" ]]; then
      missing+=("approved_at-in-future")
    fi
    if [ -n "$expires_at" ] && [[ "$expires_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && [[ "$expires_at" < "$today" ]]; then
      missing+=("expires_at-expired")
    fi
  fi
  if [ "${#missing[@]}" -ne 0 ]; then
    local reason
    reason="$(IFS=,; printf '%s' "${missing[*]}")"
    printf '%s' "$reason"
  fi
}

issue_json_for_ref() {
  local ref="$1" repo_ref number issue_json
  if printf '%s' "$ref" | grep -q '^https://github.com/'; then
    repo_ref="${ref#https://github.com/}"
    repo_ref="${repo_ref%%/issues/*}"
    number="${ref##*/}"
  elif printf '%s' "$ref" | grep -q '#'; then
    repo_ref="${ref%%#*}"
    number="${ref##*#}"
  else
    printf '{"_audit_error":"bad-ref-format"}'
    return 1
  fi
  if ! issue_json="$(gh issue view "$number" -R "$repo_ref" --json state,body,title,url 2>&1)"; then
    printf '{"_audit_error":%s}' "$(jq -Rn --arg error "$issue_json" '$error')"
    return 1
  fi
  printf '%s' "$issue_json"
}

marker_count() {
  # marker_count <marker-key>; reads issue body from stdin and ignores fenced examples.
  local marker="$1"
  awk -v marker="$marker" '
    /^```/ { fenced = !fenced; next }
    !fenced && $0 ~ "^" marker ":[[:space:]]*v1[[:space:]]*$" { count++ }
    END { print count + 0 }
  '
}

marker_block() {
  # marker_block <marker-key>; reads issue body from stdin and ignores fenced examples.
  local marker="$1"
  awk -v marker="$marker" '
    /^```/ {
      if (found) {
        exit
      }
      fenced = !fenced
      next
    }
    fenced { next }
    !found && $0 ~ "^" marker ":[[:space:]]*v1[[:space:]]*$" {
      found = 1
      print
      next
    }
    found {
      if ($0 ~ /^[[:space:]]*$/) {
        exit
      }
      if ($0 ~ /^[A-Za-z0-9_]+:[[:space:]]*/) {
        print
        next
      }
      exit
    }
  '
}

manifest_field() {
  # manifest_field <canonical-json> <key>
  local manifest="$1" key="$2"
  jq -r --arg key "$key" '.[$key] // ""' <<<"$manifest"
}

manifest_csv_has() {
  # manifest_csv_has <canonical-json> <key> <value>
  # Accept either an array field or a comma-separated string field so operators
  # can generate the manifest from simple tooling while the audit remains strict
  # about required values.
  local manifest="$1" key="$2" value="$3"
  jq -e --arg key "$key" --arg value "$value" '
    .[$key] as $field
    | if ($field | type) == "array" then
        any($field[]; . == $value)
      elif ($field | type) == "string" then
        ("," + ($field | gsub("\\s"; "")) + ",") | contains("," + $value + ",")
      else
        false
      end
  ' <<<"$manifest" >/dev/null
}

normalize_csv() {
  # normalize_csv <comma-separated-values>
  printf '%s' "$1" \
    | tr -d '[:space:]' \
    | tr ',' '\n' \
    | awk 'NF' \
    | LC_ALL=C sort -u \
    | paste -sd, -
}

manifest_csv_values() {
  # manifest_csv_values <canonical-json> <key>
  # Return a sorted comma-separated set for an array or comma-separated string.
  local manifest="$1" key="$2"
  jq -r --arg key "$key" '
    .[$key] as $field
    | if ($field | type) == "array" then
        $field[]
      elif ($field | type) == "string" then
        ($field | gsub("\\s"; "") | split(",")[])
      else
        empty
      end
  ' <<<"$manifest" \
    | awk 'NF' \
    | LC_ALL=C sort -u \
    | paste -sd, -
}

manifest_csv_matches_marker() {
  # manifest_csv_matches_marker <canonical-json> <marker-body> <key>
  local manifest="$1" marker_body="$2" key="$3"
  local marker_values manifest_values
  marker_values="$(normalize_csv "$(printf '%s\n' "$marker_body" | waiver_field "$key")")"
  manifest_values="$(manifest_csv_values "$manifest" "$key")"
  [ -n "$manifest_values" ] && [ "$manifest_values" = "$marker_values" ]
}

verify_view_only_evidence_manifest() {
  # verify_view_only_evidence_manifest <url> <expected-sha256> <marker-body>
  local url="$1" expected_sha="$2" marker_body="$3"
  local fetched canonical actual_sha marker_value manifest_value errors=()

  case "$url" in
    https://*) ;;
    file://*)
      if [ "${F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS:-0}" != "1" ]; then
        errors+=("evidence_package_url:https-required")
      fi
      ;;
    *) errors+=("evidence_package_url:https-required") ;;
  esac
  if [ "${#errors[@]}" -ne 0 ]; then
    printf '%s' "$(IFS=,; printf '%s' "${errors[*]}")"
    return 1
  fi

  if ! fetched="$(fetch_url "$url" 2>&1)"; then
    errors+=("evidence_package_fetch")
    printf '%s' "$(IFS=,; printf '%s' "${errors[*]}")"
    return 1
  fi

  if ! canonical="$(jq -cS . <<<"$fetched" 2>/dev/null)"; then
    errors+=("evidence_package_json")
    printf '%s' "$(IFS=,; printf '%s' "${errors[*]}")"
    return 1
  fi

  if ! actual_sha="$(printf '%s' "$canonical" | sha256_stream)"; then
    errors+=("evidence_package_sha256_tool")
  elif [ "$(lower_hex "$actual_sha")" != "$(lower_hex "$expected_sha")" ]; then
    errors+=("evidence_package_sha256_mismatch")
  fi

  [ "$(manifest_field "$canonical" "schema_version")" = "faz22.6-view-only-evidence-v1" ] || errors+=("manifest:schema_version")

  local exact_field
  for exact_field in acceptance_scope product_channel view_mode pilot_device session_id recording_worm d10_fail_closed dlp_mask_policy local_abort active_indicator viewer_path_decision kvkk_attended_pilot_signoff owner_approved_by approved_at expires_at; do
    marker_value="$(printf '%s\n' "$marker_body" | waiver_field "$exact_field")"
    manifest_value="$(manifest_field "$canonical" "$exact_field")"
    if [ -z "$manifest_value" ]; then
      errors+=("manifest:$exact_field")
    elif [ "$manifest_value" != "$marker_value" ]; then
      errors+=("manifest:${exact_field}:mismatch")
    fi
  done

  local required_value
  manifest_csv_matches_marker "$canonical" "$marker_body" "audit_negative_matrix" || errors+=("manifest:audit_negative_matrix:mismatch")
  manifest_csv_matches_marker "$canonical" "$marker_body" "forbidden_claims" || errors+=("manifest:forbidden_claims:mismatch")

  for required_value in no-auth wrong-device expired-session recording-down dlp-deny local-abort; do
    manifest_csv_has "$canonical" "audit_negative_matrix" "$required_value" || errors+=("manifest:audit_negative_matrix:$required_value")
  done
  IFS=',' read -r -a _view_manifest_forbidden_claims <<<"$VIEW_ONLY_FORBIDDEN_CLAIMS"
  for required_value in "${_view_manifest_forbidden_claims[@]}"; do
    [ -z "$required_value" ] && continue
    manifest_csv_has "$canonical" "forbidden_claims" "$required_value" || errors+=("manifest:forbidden_claims:$required_value")
  done

  if [ "${#errors[@]}" -ne 0 ]; then
    printf '%s' "$(IFS=,; printf '%s' "${errors[*]}")"
    return 1
  fi

  return 0
}

check_release_lineage_waiver() {
  # check_release_lineage_waiver <comma-separated-required-findings>
  local required_findings="$1"
  local ref="$RELEASE_LINEAGE_WAIVER_REF"
  local repo_ref number issue_json state body marker_count_value marker_body date_errors
  local marker scope release_tag digest accepted_findings forbidden_claims owner approved_at expires_at
  local missing=()

  if [ -z "$ref" ]; then
    lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'missing' 'reason=no-waiver-ref'
    return 1
  fi

  if printf '%s' "$ref" | grep -q '^https://github.com/'; then
    repo_ref="${ref#https://github.com/}"
    repo_ref="${repo_ref%%/issues/*}"
    number="${ref##*/}"
  elif printf '%s' "$ref" | grep -q '#'; then
    repo_ref="${ref%%#*}"
    number="${ref##*#}"
  else
    lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref reason=bad-ref-format"
    return 1
  fi

  if ! issue_json="$(gh issue view "$number" -R "$repo_ref" --json state,body,title 2>&1)"; then
    lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref reason=$(printf '%q' "$issue_json")"
    return 1
  fi
  state="$(printf '%s\n' "$issue_json" | jq -r '.state // ""')"
  body="$(printf '%s\n' "$issue_json" | jq -r '.body // ""')"
  if [ "$state" != "OPEN" ]; then
    lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref state=$state reason=issue-not-open"
    return 1
  fi

  marker_count_value="$(printf '%s\n' "$body" | marker_count 'F22_6_RELEASE_LINEAGE_WAIVER')"
  if [ "$marker_count_value" -gt 1 ]; then
    lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref reason=duplicate-marker"
    return 1
  fi
  marker_body="$body"
  if [ "$marker_count_value" -eq 1 ]; then
    marker_body="$(printf '%s\n' "$body" | marker_block 'F22_6_RELEASE_LINEAGE_WAIVER')"
  fi

  marker="$(printf '%s\n' "$marker_body" | waiver_field 'F22_6_RELEASE_LINEAGE_WAIVER')"
  scope="$(printf '%s\n' "$marker_body" | waiver_field 'waiver_scope')"
  release_tag="$(printf '%s\n' "$marker_body" | waiver_field 'release_tag')"
  digest="$(printf '%s\n' "$marker_body" | waiver_field 'artifact_host_digest')"
  accepted_findings="$(printf '%s\n' "$marker_body" | waiver_field 'accepted_findings')"
  forbidden_claims="$(printf '%s\n' "$marker_body" | waiver_field 'forbidden_claims')"
  owner="$(printf '%s\n' "$marker_body" | waiver_field 'owner_approved_by')"
  approved_at="$(printf '%s\n' "$marker_body" | waiver_field 'approved_at')"
  expires_at="$(printf '%s\n' "$marker_body" | waiver_field 'expires_at')"

  [ "$marker" = "v1" ] || missing+=("marker")
  [ "$scope" = "bounded-pilot-only" ] || missing+=("scope")
  [ "$release_tag" = "$EXPECTED_AGENT_TAG" ] || missing+=("release_tag")
  [ "$digest" = "$EXPECTED_ARTIFACT_HOST_DIGEST" ] || missing+=("artifact_host_digest")
  if owner_is_invalid "$owner"; then
    missing+=("owner_approved_by")
  else
    local owner_lc
    owner_lc="$(printf '%s' "$owner" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    case "$owner_lc" in
      na|placeholder|owner|named-owner) missing+=("owner_approved_by") ;;
    esac
  fi

  local finding
  IFS=',' read -r -a _required_findings <<<"$required_findings"
  for finding in "${_required_findings[@]}"; do
    [ -z "$finding" ] && continue
    if ! printf '%s' "$accepted_findings" | tr -d ' ' | grep -Eq "(^|,)${finding}(,|$)"; then
      missing+=("accepted_findings:$finding")
    fi
  done

  local forbidden
  IFS=',' read -r -a _forbidden_claims <<<"$RELEASE_LINEAGE_WAIVER_FORBIDDEN_CLAIMS"
  for forbidden in "${_forbidden_claims[@]}"; do
    [ -z "$forbidden" ] && continue
    if ! printf '%s' "$forbidden_claims" | tr -d ' ' | grep -Eq "(^|,)${forbidden}(,|$)"; then
      missing+=("forbidden_claims:$forbidden")
    fi
  done

  date_errors="$(date_window_errors "$approved_at" "$expires_at")"
  [ -z "$date_errors" ] || missing+=("$date_errors")

  if [ "${#missing[@]}" -ne 0 ]; then
    local reason
    reason="$(IFS=,; printf '%s' "${missing[*]}")"
    lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref reason=$reason"
    return 1
  fi

  lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'bounded_pilot_pass' "ref=$ref owner=$owner expires_at=$expires_at accepted_findings=$(printf '%q' "$accepted_findings")"
  return 0
}

issue_state() {
  local repo="$1" number="$2"
  gh issue view "$number" -R "$repo" --json state --jq .state
}

issue_title() {
  local repo="$1" number="$2"
  gh issue view "$number" -R "$repo" --json title --jq .title
}

pass_if_state() {
  local label="$1" repo="$2" number="$3" want="$4"
  local state title
  state="$(issue_state "$repo" "$number")"
  title="$(issue_title "$repo" "$number")"
  if [ "$state" = "$want" ]; then
    printf '%s=pass state=%s issue=%s#%s title=%q\n' "$label" "$state" "$repo" "$number" "$title"
    return 0
  fi
  printf '%s=blocked state=%s expected=%s issue=%s#%s title=%q\n' "$label" "$state" "$want" "$repo" "$number" "$title"
  return 1
}

check_b1_4_hardware_gate() {
  local ref="$B1_4_ATTESTATION_ACCEPTANCE_REF" issue_json state body title
  local hardware_count risk_count hardware_block risk_block missing=()
  if ! issue_json="$(issue_json_for_ref "$ref")"; then
    lineage_print_check 'GATE_B1_4_HARDWARE_ATTESTATION' 'blocked' "ref=$ref reason=$(printf '%s' "$issue_json" | jq -r '._audit_error // "issue-fetch-failed"')"
    return 1
  fi
  state="$(printf '%s\n' "$issue_json" | jq -r '.state // ""')"
  body="$(printf '%s\n' "$issue_json" | jq -r '.body // ""')"
  title="$(printf '%s\n' "$issue_json" | jq -r '.title // ""')"
  hardware_count="$(printf '%s\n' "$body" | marker_count 'F22_6_B1_4_HARDWARE_ATTESTATION_ACCEPTANCE')"
  risk_count="$(printf '%s\n' "$body" | marker_count 'F22_6_B1_4_RISK_ACCEPTANCE')"

  if [ "$hardware_count" -gt 0 ] && [ "$risk_count" -gt 0 ]; then
    lineage_print_check 'GATE_B1_4_HARDWARE_ATTESTATION' 'blocked' "state=$state issue=$ref title=$(printf '%q' "$title") reason=multiple-markers"
    return 1
  fi
  if [ "$hardware_count" -gt 1 ] || [ "$risk_count" -gt 1 ]; then
    lineage_print_check 'GATE_B1_4_HARDWARE_ATTESTATION' 'blocked' "state=$state issue=$ref title=$(printf '%q' "$title") reason=duplicate-marker"
    return 1
  fi

  if [ "$hardware_count" -eq 1 ]; then
    local acceptance_scope device_key_evidence tpm_or_secure_element agent_wire_contract broker_verifier root_policy field_evidence
    local positive_matrix negative_matrix owner approved_at date_errors
    hardware_block="$(printf '%s\n' "$body" | marker_block 'F22_6_B1_4_HARDWARE_ATTESTATION_ACCEPTANCE')"
    acceptance_scope="$(printf '%s\n' "$hardware_block" | waiver_field 'acceptance_scope')"
    device_key_evidence="$(printf '%s\n' "$hardware_block" | waiver_field 'device_key_evidence')"
    tpm_or_secure_element="$(printf '%s\n' "$hardware_block" | waiver_field 'tpm_or_secure_element')"
    agent_wire_contract="$(printf '%s\n' "$hardware_block" | waiver_field 'agent_wire_contract')"
    broker_verifier="$(printf '%s\n' "$hardware_block" | waiver_field 'broker_verifier')"
    root_policy="$(printf '%s\n' "$hardware_block" | waiver_field 'root_policy')"
    field_evidence="$(printf '%s\n' "$hardware_block" | waiver_field 'field_evidence')"
    positive_matrix="$(printf '%s\n' "$hardware_block" | waiver_field 'positive_matrix')"
    negative_matrix="$(printf '%s\n' "$hardware_block" | waiver_field 'negative_matrix')"
    owner="$(printf '%s\n' "$hardware_block" | waiver_field 'owner_approved_by')"
    approved_at="$(printf '%s\n' "$hardware_block" | waiver_field 'approved_at')"

    [ "$state" = "CLOSED" ] || missing+=("issue-not-closed")
    [ "$acceptance_scope" = "hardware-attestation" ] || missing+=("acceptance_scope")
    [ "$device_key_evidence" = "present" ] || missing+=("device_key_evidence")
    [ "$tpm_or_secure_element" = "present" ] || missing+=("tpm_or_secure_element")
    [ "$agent_wire_contract" = "present" ] || missing+=("agent_wire_contract")
    [ "$broker_verifier" = "pass" ] || missing+=("broker_verifier")
    [ "$root_policy" = "pass" ] || missing+=("root_policy")
    [ "$field_evidence" = "attached" ] || missing+=("field_evidence")
    csv_has "$positive_matrix" "hardware-attested-device" || missing+=("positive_matrix:hardware-attested-device")
    local negative
    for negative in missing stale replay wrong-device wrong-tenant; do
      csv_has "$negative_matrix" "$negative" || missing+=("negative_matrix:$negative")
    done
    owner_is_invalid "$owner" && missing+=("owner_approved_by")
    date_errors="$(date_window_errors "$approved_at")"
    [ -z "$date_errors" ] || missing+=("$date_errors")

    if [ "${#missing[@]}" -ne 0 ]; then
      local reason
      reason="$(IFS=,; printf '%s' "${missing[*]}")"
      lineage_print_check 'GATE_B1_4_HARDWARE_ATTESTATION' 'blocked' "state=$state issue=$ref title=$(printf '%q' "$title") reason=$reason"
      return 1
    fi
    lineage_print_check 'GATE_B1_4_HARDWARE_ATTESTATION' 'pass' "state=$state issue=$ref owner=$owner approved_at=$approved_at"
    return 0
  fi

  if [ "$risk_count" -eq 1 ]; then
    local risk_scope accepted_gap compensating_controls forbidden_claims owner approved_at expires_at date_errors
    risk_block="$(printf '%s\n' "$body" | marker_block 'F22_6_B1_4_RISK_ACCEPTANCE')"
    risk_scope="$(printf '%s\n' "$risk_block" | waiver_field 'risk_scope')"
    accepted_gap="$(printf '%s\n' "$risk_block" | waiver_field 'accepted_gap')"
    compensating_controls="$(printf '%s\n' "$risk_block" | waiver_field 'compensating_controls')"
    forbidden_claims="$(printf '%s\n' "$risk_block" | waiver_field 'forbidden_claims')"
    owner="$(printf '%s\n' "$risk_block" | waiver_field 'owner_approved_by')"
    approved_at="$(printf '%s\n' "$risk_block" | waiver_field 'approved_at')"
    expires_at="$(printf '%s\n' "$risk_block" | waiver_field 'expires_at')"

    [ "$state" = "OPEN" ] || missing+=("issue-not-open-for-risk-tracking")
    [ "$risk_scope" = "bounded-pilot-enrollment-backed-trust" ] || missing+=("risk_scope")
    [ "$accepted_gap" = "no-real-tpm-attestation" ] || missing+=("accepted_gap")
    local control
    for control in cert-bound-token mTLS revocation-check signed-permits dual-control audit-recording kill-revoke; do
      csv_has "$compensating_controls" "$control" || missing+=("compensating_controls:$control")
    done
    local forbidden
    IFS=',' read -r -a _b1_forbidden_claims <<<"$B1_4_RISK_ACCEPTANCE_FORBIDDEN_CLAIMS"
    for forbidden in "${_b1_forbidden_claims[@]}"; do
      [ -z "$forbidden" ] && continue
      csv_has "$forbidden_claims" "$forbidden" || missing+=("forbidden_claims:$forbidden")
    done
    owner_is_invalid "$owner" && missing+=("owner_approved_by")
    [ -n "$expires_at" ] || missing+=("expires_at")
    date_errors="$(date_window_errors "$approved_at" "$expires_at")"
    [ -z "$date_errors" ] || missing+=("$date_errors")

    if [ "${#missing[@]}" -ne 0 ]; then
      local reason
      reason="$(IFS=,; printf '%s' "${missing[*]}")"
      lineage_print_check 'GATE_B1_4_HARDWARE_ATTESTATION' 'blocked' "state=$state issue=$ref title=$(printf '%q' "$title") reason=$reason"
      return 1
    fi
    lineage_print_check 'GATE_B1_4_HARDWARE_ATTESTATION' 'bounded_pilot_risk_accepted' "state=$state issue=$ref owner=$owner expires_at=$expires_at"
    return 0
  fi

  lineage_print_check 'GATE_B1_4_HARDWARE_ATTESTATION' 'blocked' "state=$state expected=CLOSED-or-bounded-risk-accepted issue=$ref title=$(printf '%q' "$title") reason=missing-acceptance-marker"
  return 1
}

check_view_only_gate() {
  local ref="$VIEW_ONLY_ACCEPTANCE_REF" issue_json state body title marker_count_value marker_body missing=()
  if ! issue_json="$(issue_json_for_ref "$ref")"; then
    lineage_print_check 'GATE_VIEW_ONLY_SCREEN_SHARE' 'blocked' "ref=$ref reason=$(printf '%s' "$issue_json" | jq -r '._audit_error // "issue-fetch-failed"')"
    return 1
  fi
  state="$(printf '%s\n' "$issue_json" | jq -r '.state // ""')"
  body="$(printf '%s\n' "$issue_json" | jq -r '.body // ""')"
  title="$(printf '%s\n' "$issue_json" | jq -r '.title // ""')"
  marker_count_value="$(printf '%s\n' "$body" | marker_count 'F22_6_VIEW_ONLY_ACCEPTANCE')"

  if [ "$marker_count_value" -gt 1 ]; then
    lineage_print_check 'GATE_VIEW_ONLY_SCREEN_SHARE' 'blocked' "state=$state issue=$ref title=$(printf '%q' "$title") reason=duplicate-marker"
    return 1
  fi

  if [ "$marker_count_value" -eq 1 ]; then
    local acceptance_scope product_channel view_mode pilot_device session_id evidence_package_sha256
    local evidence_package_url evidence_manifest_errors
    local recording_worm d10_fail_closed dlp_mask_policy local_abort active_indicator viewer_path_decision
    local audit_negative_matrix kvkk_attended_pilot_signoff forbidden_claims owner approved_at expires_at date_errors
    marker_body="$(printf '%s\n' "$body" | marker_block 'F22_6_VIEW_ONLY_ACCEPTANCE')"
    acceptance_scope="$(printf '%s\n' "$marker_body" | waiver_field 'acceptance_scope')"
    product_channel="$(printf '%s\n' "$marker_body" | waiver_field 'product_channel')"
    view_mode="$(printf '%s\n' "$marker_body" | waiver_field 'view_mode')"
    pilot_device="$(printf '%s\n' "$marker_body" | waiver_field 'pilot_device')"
    session_id="$(printf '%s\n' "$marker_body" | waiver_field 'session_id')"
    evidence_package_url="$(printf '%s\n' "$marker_body" | waiver_field 'evidence_package_url')"
    evidence_package_sha256="$(printf '%s\n' "$marker_body" | waiver_field 'evidence_package_sha256')"
    recording_worm="$(printf '%s\n' "$marker_body" | waiver_field 'recording_worm')"
    d10_fail_closed="$(printf '%s\n' "$marker_body" | waiver_field 'd10_fail_closed')"
    dlp_mask_policy="$(printf '%s\n' "$marker_body" | waiver_field 'dlp_mask_policy')"
    local_abort="$(printf '%s\n' "$marker_body" | waiver_field 'local_abort')"
    active_indicator="$(printf '%s\n' "$marker_body" | waiver_field 'active_indicator')"
    viewer_path_decision="$(printf '%s\n' "$marker_body" | waiver_field 'viewer_path_decision')"
    audit_negative_matrix="$(printf '%s\n' "$marker_body" | waiver_field 'audit_negative_matrix')"
    kvkk_attended_pilot_signoff="$(printf '%s\n' "$marker_body" | waiver_field 'kvkk_attended_pilot_signoff')"
    forbidden_claims="$(printf '%s\n' "$marker_body" | waiver_field 'forbidden_claims')"
    owner="$(printf '%s\n' "$marker_body" | waiver_field 'owner_approved_by')"
    approved_at="$(printf '%s\n' "$marker_body" | waiver_field 'approved_at')"
    expires_at="$(printf '%s\n' "$marker_body" | waiver_field 'expires_at')"

    [ "$state" = "CLOSED" ] || missing+=("issue-not-closed")
    [ "$acceptance_scope" = "bounded-pilot-view-only" ] || missing+=("acceptance_scope")
    [ "$product_channel" = "endpoint-agent-outbound-mtls-remote-bridge" ] || missing+=("product_channel")
    [ "$view_mode" = "VIEW_ONLY" ] || missing+=("view_mode")
    [ -n "$pilot_device" ] || missing+=("pilot_device")
    [ -n "$session_id" ] || missing+=("session_id")
    [ -n "$evidence_package_url" ] || missing+=("evidence_package_url")
    [[ "$evidence_package_sha256" =~ ^[a-fA-F0-9]{64}$ ]] || missing+=("evidence_package_sha256")
    [ "$recording_worm" = "pass" ] || missing+=("recording_worm")
    [ "$d10_fail_closed" = "pass" ] || missing+=("d10_fail_closed")
    [ "$dlp_mask_policy" = "pass" ] || missing+=("dlp_mask_policy")
    [ "$local_abort" = "pass" ] || missing+=("local_abort")
    [ "$active_indicator" = "pass" ] || missing+=("active_indicator")
    case "$viewer_path_decision" in
      fanout-proven|owner-deferred) ;;
      *) missing+=("viewer_path_decision") ;;
    esac
    local negative
    for negative in no-auth wrong-device expired-session recording-down dlp-deny local-abort; do
      csv_has "$audit_negative_matrix" "$negative" || missing+=("audit_negative_matrix:$negative")
    done
    [ "$kvkk_attended_pilot_signoff" = "pass" ] || missing+=("kvkk_attended_pilot_signoff")
    local forbidden
    IFS=',' read -r -a _view_forbidden_claims <<<"$VIEW_ONLY_FORBIDDEN_CLAIMS"
    for forbidden in "${_view_forbidden_claims[@]}"; do
      [ -z "$forbidden" ] && continue
      csv_has "$forbidden_claims" "$forbidden" || missing+=("forbidden_claims:$forbidden")
    done
    owner_is_invalid "$owner" && missing+=("owner_approved_by")
    [ -n "$expires_at" ] || missing+=("expires_at")
    date_errors="$(date_window_errors "$approved_at" "$expires_at")"
    [ -z "$date_errors" ] || missing+=("$date_errors")

    if [ -n "$evidence_package_url" ] && [[ "$evidence_package_sha256" =~ ^[a-fA-F0-9]{64}$ ]]; then
      if ! evidence_manifest_errors="$(verify_view_only_evidence_manifest "$evidence_package_url" "$evidence_package_sha256" "$marker_body")"; then
        missing+=("$evidence_manifest_errors")
      fi
    fi

    if [ "${#missing[@]}" -ne 0 ]; then
      local reason
      reason="$(IFS=,; printf '%s' "${missing[*]}")"
      lineage_print_check 'GATE_VIEW_ONLY_SCREEN_SHARE' 'blocked' "state=$state issue=$ref title=$(printf '%q' "$title") reason=$reason"
      return 1
    fi
    lineage_print_check 'GATE_VIEW_ONLY_SCREEN_SHARE' 'pass' "state=$state issue=$ref owner=$owner session_id=$session_id evidence_package_sha256=$evidence_package_sha256 expires_at=$expires_at"
    return 0
  fi

  lineage_print_check 'GATE_VIEW_ONLY_SCREEN_SHARE' 'blocked' "state=$state expected=CLOSED-with-view-only-acceptance issue=$ref title=$(printf '%q' "$title") reason=missing-acceptance-marker"
  return 1
}

remote_bridge_kubectl_output() {
  kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" get deploy endpoint-admin-service endpoint-admin-remote-bridge \
    -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,UPDATED:.status.updatedReplicas,IMAGE:.spec.template.spec.containers[0].image
  kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" get pod \
    -l 'app.kubernetes.io/name in (endpoint-admin-service,endpoint-admin-remote-bridge)' \
    -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,IMAGEID:.status.containerStatuses[0].imageID
  kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" get externalsecret \
    endpoint-admin-remote-bridge-secrets endpoint-admin-remote-bridge-signer endpoint-admin-remote-bridge-tls \
    -o custom-columns=NAME:.metadata.name,READY:.status.conditions[0].status,REASON:.status.conditions[0].reason \
    --no-headers
}

check_remote_bridge() {
  local output digest_hits secret_hits
  local q_context q_namespace q_selector remote_cmd effective_mode
  case "$REMOTE_BRIDGE_KUBECTL_MODE" in
    local|local-kubectl) effective_mode="local-kubectl" ;;
    ssh) effective_mode="ssh" ;;
    *)
      printf 'REMOTE_BRIDGE_LIVE=unknown mode=%q reason=invalid-remote-bridge-kubectl-mode\n' "$REMOTE_BRIDGE_KUBECTL_MODE"
      return 1
      ;;
  esac
  if [ "$SSH_TARGET" = "local" ]; then
    effective_mode="local-kubectl"
  fi

  if [ -z "$KUBE_CONTEXT" ]; then
    printf 'REMOTE_BRIDGE_LIVE=unknown mode=%s reason=empty-kube-context\n' "$effective_mode"
    return 1
  fi
  if [ -z "$KUBE_NAMESPACE" ]; then
    printf 'REMOTE_BRIDGE_LIVE=unknown mode=%s reason=empty-kube-namespace\n' "$effective_mode"
    return 1
  fi

  if [ "$effective_mode" = "local-kubectl" ]; then
    if ! command -v kubectl >/dev/null 2>&1; then
      printf 'REMOTE_BRIDGE_LIVE=unknown mode=%s reason=missing-kubectl\n' "$effective_mode"
      return 1
    fi
    if ! output="$(remote_bridge_kubectl_output 2>&1)"; then
      printf 'REMOTE_BRIDGE_LIVE=unknown mode=%s reason=%q\n' "$effective_mode" "$output"
      return 1
    fi
  else
    if ! command -v ssh >/dev/null 2>&1; then
      printf 'REMOTE_BRIDGE_LIVE=unknown mode=ssh reason=missing-ssh\n'
      return 1
    fi
    q_context="$(shell_quote "$KUBE_CONTEXT")"
    q_namespace="$(shell_quote "$KUBE_NAMESPACE")"
    q_selector="$(shell_quote 'app.kubernetes.io/name in (endpoint-admin-service,endpoint-admin-remote-bridge)')"
    remote_cmd="kubectl --context $q_context -n $q_namespace get deploy endpoint-admin-service endpoint-admin-remote-bridge -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,UPDATED:.status.updatedReplicas,IMAGE:.spec.template.spec.containers[0].image && kubectl --context $q_context -n $q_namespace get pod -l $q_selector -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,IMAGEID:.status.containerStatuses[0].imageID && kubectl --context $q_context -n $q_namespace get externalsecret endpoint-admin-remote-bridge-secrets endpoint-admin-remote-bridge-signer endpoint-admin-remote-bridge-tls -o custom-columns=NAME:.metadata.name,READY:.status.conditions[0].status,REASON:.status.conditions[0].reason --no-headers"
    # shellcheck disable=SC2029 # q_context/q_namespace are shell-escaped locally and intentionally expanded before ssh.
    if ! output="$(ssh "$SSH_TARGET" "$remote_cmd" 2>&1)"; then
      printf 'REMOTE_BRIDGE_LIVE=unknown mode=ssh reason=%q\n' "$output"
      return 1
    fi
  fi

  printf 'REMOTE_BRIDGE_LIVE_OUTPUT_BEGIN\n%s\nREMOTE_BRIDGE_LIVE_OUTPUT_END\n' "$output"
  # Pilot topology intentionally runs the primary endpoint-admin deployment and
  # the separate remote-bridge broker deployment from the same endpoint-admin
  # image. If remote-bridge becomes a separate image, split this into two
  # explicit digest expectations instead of weakening the check.
  digest_hits="$(printf '%s\n' "$output" | grep -c "@${EXPECTED_REMOTE_BRIDGE_DIGEST}" || true)"
  secret_hits="$(printf '%s\n' "$output" | grep -cE 'True.*SecretSynced' || true)"
  if [ "$digest_hits" -ge 4 ] && [ "$secret_hits" -ge 3 ]; then
    printf 'REMOTE_BRIDGE_LIVE=pass mode=%s expected_digest=%s\n' "$effective_mode" "$EXPECTED_REMOTE_BRIDGE_DIGEST"
    return 0
  fi
  printf 'REMOTE_BRIDGE_LIVE=blocked mode=%s expected_digest=%s digest_hits=%s secret_synced_hits=%s\n' "$effective_mode" "$EXPECTED_REMOTE_BRIDGE_DIGEST" "$digest_hits" "$secret_hits"
  return 1
}

check_release_train() {
  local releases latest count tags is_immutable
  local needs_hygiene=0
  local waiver_findings=()
  if ! releases="$(gh release list -R "$AGENT_REPO" --limit 20 \
      --json tagName,isLatest,isDraft,isPrerelease,isImmutable,publishedAt,name 2>&1)"; then
    printf 'AGENT_RELEASE_TRAIN=unknown reason=%q\n' "$releases"
    return 1
  fi
  latest="$(printf '%s\n' "$releases" \
    | jq -r '(map(select(.isLatest))[0].tagName // .[0].tagName // "unknown")')"
  count="$(printf '%s\n' "$releases" \
    | jq --arg regex "$AGENT_RELEASE_SERIES_REGEX" '[.[].tagName | select(test($regex))] | length')"
  tags="$(printf '%s\n' "$releases" | jq -r '[.[].tagName] | join(",")')"
  is_immutable="$(printf '%s\n' "$releases" | jq -r --arg tag "$EXPECTED_AGENT_LATEST_TAG" 'map(select(.tagName == $tag)) as $m | if ($m|length) > 0 then $m[0].isImmutable else false end')"
  printf 'AGENT_RELEASE_TRAIN_LATEST=%s\n' "${latest:-unknown}"
  printf 'AGENT_RELEASE_TRAIN_RECENT_SERIES=%s\n' "$AGENT_RELEASE_SERIES_LABEL"
  printf 'AGENT_RELEASE_TRAIN_RECENT_SERIES_COUNT=%s\n' "$count"
  printf 'AGENT_RELEASE_TRAIN_RECENT_TAGS=%s\n' "$tags"
  if [ "${latest:-}" != "$EXPECTED_AGENT_LATEST_TAG" ]; then
    printf 'AGENT_RELEASE_TRAIN=blocked latest=%s expected_latest=%s\n' "${latest:-unknown}" "$EXPECTED_AGENT_LATEST_TAG"
    return 1
  fi

  if [ "$is_immutable" != "true" ]; then
    needs_hygiene=1
    waiver_findings+=('GITHUB_RELEASE_IMMUTABLE')
  fi

  if [ "$count" -ge "$RELEASE_HYGIENE_RECENT_THRESHOLD" ]; then
    needs_hygiene=1
    waiver_findings+=('GITHUB_RELEASE_DENSE_TRAIN')
  fi

  if [ "$needs_hygiene" -ne 0 ]; then
    local required_findings
    required_findings="$(IFS=,; printf '%s' "${waiver_findings[*]}")"
    if check_release_lineage_waiver "$required_findings"; then
      printf 'AGENT_RELEASE_TRAIN=bounded_pilot_pass latest=%s recent_series=%s recent_series_count=%s isImmutable=%s waiver_ref=%s\n' "$latest" "$AGENT_RELEASE_SERIES_LABEL" "$count" "$is_immutable" "$RELEASE_LINEAGE_WAIVER_REF"
      return 0
    fi
    printf 'AGENT_RELEASE_TRAIN=needs_hygiene latest=%s recent_series=%s recent_series_count=%s isImmutable=%s reason=rapid-release-train-or-mutable-release-requires-lineage-waiver\n' "$latest" "$AGENT_RELEASE_SERIES_LABEL" "$count" "$is_immutable"
    return 1
  fi

  lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'not_required' 'reason=no-release-lineage-hygiene'
  printf 'AGENT_RELEASE_TRAIN=pass latest=%s recent_series=%s recent_series_count=%s isImmutable=%s\n' "$latest" "$AGENT_RELEASE_SERIES_LABEL" "$count" "$is_immutable"
  return 0
}

main() {
  need gh
  need grep
  need awk
  need jq
  if [ "$REMOTE_BRIDGE_KUBECTL_MODE" = "local" ] || [ "$REMOTE_BRIDGE_KUBECTL_MODE" = "local-kubectl" ] || [ "$SSH_TARGET" = "local" ]; then
    need kubectl
  else
    need ssh
  fi

  local blocked=0
  local next_required=()

  printf 'F22_6_AUDIT_SCOPE=remote-ops-autonomous-completion\n'
  printf 'F22_6_AUDIT_CONTRACT=docs/runbooks/RB-faz22.6-autonomous-completion-contract.md\n'

  pass_if_state 'GATE_22_6_1_OPERATION_CATALOG' "$BACKEND_REPO" 701 CLOSED || blocked=1
  pass_if_state 'GATE_22_6_2_APPROVED_SCRIPT_RUNNER' "$BACKEND_REPO" 702 CLOSED || blocked=1
  pass_if_state 'GATE_22_6_3_CONSTRAINED_EXECUTOR' "$AGENT_REPO" 208 CLOSED || blocked=1
  pass_if_state 'GATE_AGENTPC2_BOOTSTRAP' "$GITOPS_REPO" 1768 CLOSED || blocked=1
  pass_if_state 'GATE_OPERATOR_UX_TERMINAL' "$WEB_REPO" 820 CLOSED || blocked=1
  pass_if_state 'GATE_OPERATOR_UX_SESSION_STATE' "$WEB_REPO" 822 CLOSED || blocked=1

  if check_b1_4_hardware_gate; then
    :
  else
    blocked=1
    next_required+=('close-or-risk-accept-548-with-marker')
  fi

  if check_view_only_gate; then
    :
  else
    blocked=1
    next_required+=('close-1580-with-view-only-marker')
  fi

  if ! check_remote_bridge; then
    blocked=1
    next_required+=('fix-remote-bridge-live')
  fi
  if ! check_release_train; then
    blocked=1
    next_required+=('fix-release-lineage-hygiene')
  fi

  if [ "$blocked" -eq 0 ]; then
    printf 'F22_6_COMPLETION=pass\n'
  else
    printf 'F22_6_COMPLETION=blocked\n'
    if [ "${#next_required[@]}" -gt 0 ]; then
      local next_joined
      next_joined="$(IFS=,; printf '%s' "${next_required[*]}")"
      printf 'F22_6_NEXT_REQUIRED=%s\n' "$next_joined"
    else
      printf 'F22_6_NEXT_REQUIRED=inspect-blocked-gates\n'
    fi
  fi
}

if [ "${F22_6_COMPLETION_AUDIT_SOURCE_ONLY:-0}" != "1" ]; then
  main "$@"
fi
