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
# shellcheck source=scripts/faz22-remote-ops/lib-github-read-api.sh
source "$SCRIPT_DIR/lib-github-read-api.sh"
# shellcheck source=scripts/governance/lib-remote-bridge-digest.sh
source "$REPO_ROOT/scripts/governance/lib-remote-bridge-digest.sh"
# Single SSOT for the remote-bridge expected digest: the rendered overlay
# (issue #2067 / Codex 019f0733 verdict C). Absolute overlay paths so the
# derivation works regardless of the audit's CWD.
RBD_PRIMARY_OVERLAY="$REPO_ROOT/kustomize/overlays/test"
RBD_BRIDGE_OVERLAY="$REPO_ROOT/kustomize/overlays/test/activation/endpoint-admin-remote-bridge"

SSH_TARGET="${SSH_TARGET:-aiadmin@aiserver}"
SSH_OPTS="${SSH_OPTS:-}"
REMOTE_BRIDGE_KUBECTL_MODE="${REMOTE_BRIDGE_KUBECTL_MODE:-ssh}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
# EXPECTED_REMOTE_BRIDGE_DIGEST is DERIVED at audit time (check_remote_bridge) from
# the rendered overlay — there is NO hardcoded literal (the old default was a drift
# source, #2067). Setting it in the env is honored ONLY as an explicit diagnostic
# escape hatch with ALLOW_EXPECTED_DIGEST_OVERRIDE=1 (output marks
# expected_source=env_override); it never silently overrides the rendered source.
B1_4_ATTESTATION_ACCEPTANCE_REF="${B1_4_ATTESTATION_ACCEPTANCE_REF:-Halildeu/platform-backend#548}"
B1_4_RISK_ACCEPTANCE_FORBIDDEN_CLAIMS="${B1_4_RISK_ACCEPTANCE_FORBIDDEN_CLAIMS:-tpm-complete,hardware-attestation-complete,5-device,50-device,800-device,production,broad-rollout}"
VIEW_ONLY_ACCEPTANCE_REF="${VIEW_ONLY_ACCEPTANCE_REF:-Halildeu/platform-k8s-gitops#1580}"
VIEW_ONLY_KVKK_REF="${VIEW_ONLY_KVKK_REF:-Halildeu/platform-k8s-gitops#2374}"
VIEW_ONLY_KVKK_APPROVER_POLICY_PATH="${VIEW_ONLY_KVKK_APPROVER_POLICY_PATH:-$REPO_ROOT/config/faz22-6-view-only-kvkk-approver-policy.v1.json}"
VIEW_ONLY_FORBIDDEN_CLAIMS="${VIEW_ONLY_FORBIDDEN_CLAIMS:-rdp,credential-entry,raw-shell,port-forward,5-device,50-device,800-device,production,broad-rollout}"
# ADR-0044: VIEW_ONLY marker split. Engineering gate (fail-closed) + KVKK gate
# (tracked, non-blocking). The KVKK non-blocking track is an ALLOWLIST: only the
# enumerated legal/DPO/retention keys (plus the standard marker fields) may appear
# in the F22_6_VIEW_ONLY_KVKK marker. Any other key (a security/product/audit field
# mislabeled as "legal") is an allowlist violation and DOES block completion — the
# non-blocking-ness applies to genuine legal items only, never to weakening a gate.
VIEW_ONLY_EVIDENCE_SCHEMA_VERSION="${VIEW_ONLY_EVIDENCE_SCHEMA_VERSION:-faz22.6-view-only-evidence-v2}"
VIEW_ONLY_KVKK_ALLOWED_KEYS="${VIEW_ONLY_KVKK_ALLOWED_KEYS:-kvkk_attended_pilot_signoff,legal_dpo_consent,retention_policy_approval,status,owner_approved_by,approved_at,expires_at,decision_payload_sha256,decision_record_sha256,decision_record_ref,approver_policy_sha256,approver_policy_ref,privacy_owner_key_id,privacy_owner_public_key_sha256,privacy_owner_signed_at,privacy_owner_signature,legal_dpo_key_id,legal_dpo_public_key_sha256,legal_dpo_signed_at,legal_dpo_signature}"
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

ssh_cmd() {
  # ssh_cmd <target> <remote-command>
  #
  # Allows live audits to scope OpenSSH identity selection without changing the
  # default CI behavior. Example:
  # SSH_OPTS='-o IdentitiesOnly=yes -i ~/.ssh/id_ed25519'
  local target="$1" remote_cmd="$2"
  local opts=()
  if [ -n "$SSH_OPTS" ]; then
    # shellcheck disable=SC2206 # SSH_OPTS is an operator-provided shellwords string.
    opts=($SSH_OPTS)
  fi
  # shellcheck disable=SC2029 # remote_cmd is intentionally composed client-side by the caller.
  if [ "${#opts[@]}" -gt 0 ]; then
    ssh "${opts[@]}" "$target" "$remote_cmd"
  else
    ssh "$target" "$remote_cmd"
  fi
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
  if ! issue_json="$(github_read_issue_json "$repo_ref" "$number" state,body,title,url 2>&1)"; then
    printf '{"_audit_error":%s}' "$(jq -Rn --arg error "$issue_json" '$error')"
    return 1
  fi
  printf '%s' "$issue_json"
}

marker_count() {
  # marker_count <marker-key> [version]; reads issue body from stdin and ignores
  # fenced examples. version defaults to v1 (the established marker-format token);
  # ADR-0044's F22_6_VIEW_ONLY_ENGINEERING marker is v2.
  local marker="$1" version="${2:-v1}"
  awk -v marker="$marker" -v version="$version" '
    /^```/ { fenced = !fenced; next }
    !fenced && $0 ~ "^" marker ":[[:space:]]*" version "[[:space:]]*$" { count++ }
    END { print count + 0 }
  '
}

marker_block() {
  # marker_block <marker-key> [version]; reads issue body from stdin and ignores
  # fenced examples. version defaults to v1.
  local marker="$1" version="${2:-v1}"
  awk -v marker="$marker" -v version="$version" '
    /^```/ {
      if (found) {
        exit
      }
      fenced = !fenced
      next
    }
    fenced { next }
    !found && $0 ~ "^" marker ":[[:space:]]*" version "[[:space:]]*$" {
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
  #
  # ADR-0044 v2 engineering manifest: mode-aware.
  #   recording_mode=disabled -> positive no-content-persistence proof
  #     (content_persistence=none) + metadata audit still active
  #     (metadata_audit=active); WORM/record-before-fanout are NOT required and
  #     recording_worm=pass is FORBIDDEN (avoids an untested "recording off" claim).
  #   recording_mode=enabled  -> re-arms the fail-closed recording controls:
  #     recording_worm=pass + record_before_fanout=pass + a parametric
  #     recording_retention_days (positive int) + recording_retention_owner_ref.
  # kvkk_attended_pilot_signoff is NOT part of this manifest (moved to the
  # non-blocking F22_6_VIEW_ONLY_KVKK marker per ADR-0044 D1/D2).
  local url="$1" expected_sha="$2" marker_body="$3"
  local fetched canonical actual_sha marker_value manifest_value errors=()
  local recording_mode

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

  [ "$(manifest_field "$canonical" "schema_version")" = "$VIEW_ONLY_EVIDENCE_SCHEMA_VERSION" ] || errors+=("manifest:schema_version")

  recording_mode="$(manifest_field "$canonical" "recording_mode")"

  # Base exact-match fields (manifest must equal marker, both non-empty), plus
  # mode-specific fields appended below.
  local exact_field
  local exact_fields=(
    acceptance_scope product_channel view_mode pilot_device session_id
    recording_mode d10_fail_closed dlp_mask_policy local_abort active_indicator
    viewer_path_decision owner_approved_by approved_at expires_at
  )
  case "$recording_mode" in
    disabled) exact_fields+=(content_persistence metadata_audit) ;;
    enabled) exact_fields+=(recording_worm record_before_fanout recording_retention_days recording_retention_unit recording_retention_owner_ref) ;;
    *) errors+=("manifest:recording_mode:invalid") ;;
  esac

  for exact_field in "${exact_fields[@]}"; do
    marker_value="$(printf '%s\n' "$marker_body" | waiver_field "$exact_field")"
    manifest_value="$(manifest_field "$canonical" "$exact_field")"
    if [ -z "$manifest_value" ]; then
      errors+=("manifest:$exact_field")
    elif [ "$manifest_value" != "$marker_value" ]; then
      errors+=("manifest:${exact_field}:mismatch")
    fi
  done

  # Mode-specific value constraints (if-blocks, not `&&`, to stay set -e safe).
  case "$recording_mode" in
    disabled)
      [ "$(manifest_field "$canonical" "content_persistence")" = "none" ] || errors+=("manifest:content_persistence:must-be-none")
      [ "$(manifest_field "$canonical" "metadata_audit")" = "active" ] || errors+=("manifest:metadata_audit:must-be-active")
      # No enabled-only recording field may appear in a disabled manifest.
      local disabled_forbidden
      for disabled_forbidden in recording_worm record_before_fanout recording_retention_days recording_retention_unit recording_retention_owner_ref; do
        if [ -n "$(manifest_field "$canonical" "$disabled_forbidden")" ]; then
          errors+=("manifest:${disabled_forbidden}:forbidden-when-disabled")
        fi
      done
      ;;
    enabled)
      [ "$(manifest_field "$canonical" "recording_worm")" = "pass" ] || errors+=("manifest:recording_worm:must-be-pass")
      [ "$(manifest_field "$canonical" "record_before_fanout")" = "pass" ] || errors+=("manifest:record_before_fanout:must-be-pass")
      [[ "$(manifest_field "$canonical" "recording_retention_days")" =~ ^[1-9][0-9]*$ ]] || errors+=("manifest:recording_retention_days:must-be-positive-int")
      [ "$(manifest_field "$canonical" "recording_retention_unit")" = "days" ] || errors+=("manifest:recording_retention_unit:must-be-days")
      [ -n "$(manifest_field "$canonical" "recording_retention_owner_ref")" ] || errors+=("manifest:recording_retention_owner_ref")
      ;;
  esac

  local required_value
  manifest_csv_matches_marker "$canonical" "$marker_body" "audit_negative_matrix" || errors+=("manifest:audit_negative_matrix:mismatch")
  manifest_csv_matches_marker "$canonical" "$marker_body" "forbidden_claims" || errors+=("manifest:forbidden_claims:mismatch")

  # Full engineering evidence list (ADR-0044 D2) machine-bound as required
  # adversarial negative-matrix tokens.
  local required_negatives=(
    no-auth wrong-device expired-session dlp-deny local-abort
    no-control-attempt-denied mtls-authz-enforced ttl-revoke-kill
    frame-flow-proven audit-metadata-recorded
  )
  case "$recording_mode" in
    disabled) required_negatives+=(recording-disabled-no-persistence metadata-audit-on) ;;
    enabled) required_negatives+=(recording-down) ;;
  esac
  for required_value in "${required_negatives[@]}"; do
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

  if ! issue_json="$(github_read_issue_json "$repo_ref" "$number" state,body,title 2>&1)"; then
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

pass_if_state() {
  local label="$1" repo="$2" number="$3" want="$4"
  local issue_json state title
  if ! issue_json="$(github_read_issue_json "$repo" "$number" state,body,title 2>&1)"; then
    printf '%s=blocked expected=%s issue=%s#%s reason=%q\n' "$label" "$want" "$repo" "$number" "$issue_json"
    return 1
  fi
  state="$(printf '%s\n' "$issue_json" | jq -r '.state // ""')"
  title="$(printf '%s\n' "$issue_json" | jq -r '.title // ""')"
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
    local positive_matrix negative_matrix owner approved_at expires_at date_errors
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
    expires_at="$(printf '%s\n' "$hardware_block" | waiver_field 'expires_at')"

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
    [ -z "$expires_at" ] || missing+=("expires_at-forbidden")
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

check_view_only_engineering_gate() {
  # ADR-0044 D2: the fail-closed engineering gate for #1580 VIEW_ONLY.
  # Reads F22_6_VIEW_ONLY_ENGINEERING: v2 (NOT the legacy bundled marker, which is
  # refused as legacy_bundled_marker_detected). Mode-aware on recording_mode.
  # kvkk_attended_pilot_signoff is NOT part of this gate (it is the separate,
  # non-blocking F22_6_VIEW_ONLY_KVKK gate).
  local ref="$VIEW_ONLY_ACCEPTANCE_REF" issue_json state body title marker_count_value legacy_count marker_body missing=()
  if ! issue_json="$(issue_json_for_ref "$ref")"; then
    lineage_print_check 'GATE_VIEW_ONLY_ENGINEERING' 'blocked' "ref=$ref reason=$(printf '%s' "$issue_json" | jq -r '._audit_error // "issue-fetch-failed"')"
    return 1
  fi
  state="$(printf '%s\n' "$issue_json" | jq -r '.state // ""')"
  body="$(printf '%s\n' "$issue_json" | jq -r '.body // ""')"
  title="$(printf '%s\n' "$issue_json" | jq -r '.title // ""')"

  # Legacy fail-safe (Codex 019f05cc #2): an old bundled marker must NEVER
  # auto-pass the new engineering gate.
  legacy_count="$(printf '%s\n' "$body" | marker_count 'F22_6_VIEW_ONLY_ACCEPTANCE')"
  if [ "$legacy_count" -ge 1 ]; then
    lineage_print_check 'GATE_VIEW_ONLY_ENGINEERING' 'blocked' "state=$state issue=$ref title=$(printf '%q' "$title") reason=legacy_bundled_marker_detected"
    return 1
  fi

  marker_count_value="$(printf '%s\n' "$body" | marker_count 'F22_6_VIEW_ONLY_ENGINEERING' 'v2')"

  if [ "$marker_count_value" -gt 1 ]; then
    lineage_print_check 'GATE_VIEW_ONLY_ENGINEERING' 'blocked' "state=$state issue=$ref title=$(printf '%q' "$title") reason=duplicate-marker"
    return 1
  fi

  if [ "$marker_count_value" -eq 1 ]; then
    local acceptance_scope product_channel view_mode pilot_device session_id evidence_package_sha256
    local evidence_package_url evidence_manifest_errors recording_mode
    local d10_fail_closed dlp_mask_policy local_abort active_indicator viewer_path_decision
    local audit_negative_matrix forbidden_claims owner approved_at expires_at date_errors
    marker_body="$(printf '%s\n' "$body" | marker_block 'F22_6_VIEW_ONLY_ENGINEERING' 'v2')"
    acceptance_scope="$(printf '%s\n' "$marker_body" | waiver_field 'acceptance_scope')"
    product_channel="$(printf '%s\n' "$marker_body" | waiver_field 'product_channel')"
    view_mode="$(printf '%s\n' "$marker_body" | waiver_field 'view_mode')"
    pilot_device="$(printf '%s\n' "$marker_body" | waiver_field 'pilot_device')"
    session_id="$(printf '%s\n' "$marker_body" | waiver_field 'session_id')"
    evidence_package_url="$(printf '%s\n' "$marker_body" | waiver_field 'evidence_package_url')"
    evidence_package_sha256="$(printf '%s\n' "$marker_body" | waiver_field 'evidence_package_sha256')"
    recording_mode="$(printf '%s\n' "$marker_body" | waiver_field 'recording_mode')"
    d10_fail_closed="$(printf '%s\n' "$marker_body" | waiver_field 'd10_fail_closed')"
    dlp_mask_policy="$(printf '%s\n' "$marker_body" | waiver_field 'dlp_mask_policy')"
    local_abort="$(printf '%s\n' "$marker_body" | waiver_field 'local_abort')"
    active_indicator="$(printf '%s\n' "$marker_body" | waiver_field 'active_indicator')"
    viewer_path_decision="$(printf '%s\n' "$marker_body" | waiver_field 'viewer_path_decision')"
    audit_negative_matrix="$(printf '%s\n' "$marker_body" | waiver_field 'audit_negative_matrix')"
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
    [ "$d10_fail_closed" = "pass" ] || missing+=("d10_fail_closed")
    [ "$dlp_mask_policy" = "pass" ] || missing+=("dlp_mask_policy")
    [ "$local_abort" = "pass" ] || missing+=("local_abort")
    [ "$active_indicator" = "pass" ] || missing+=("active_indicator")
    case "$viewer_path_decision" in
      fanout-proven|owner-deferred) ;;
      *) missing+=("viewer_path_decision") ;;
    esac

    # Full engineering evidence list (ADR-0044 D2): machine-bound as concrete
    # adversarial negative-matrix tokens so each promised control is required,
    # not just folded into a single flag.
    local negative required_negatives
    required_negatives=(
      no-auth wrong-device expired-session dlp-deny local-abort
      no-control-attempt-denied mtls-authz-enforced ttl-revoke-kill
      frame-flow-proven audit-metadata-recorded
    )
    # Mode-aware recording controls (ADR-0044 D3/D5).
    case "$recording_mode" in
      disabled)
        # Privacy-safe MVP: no content persistence, metadata audit still active.
        [ "$(printf '%s\n' "$marker_body" | waiver_field 'content_persistence')" = "none" ] || missing+=("content_persistence")
        [ "$(printf '%s\n' "$marker_body" | waiver_field 'metadata_audit')" = "active" ] || missing+=("metadata_audit")
        # No enabled-only recording field may be asserted while disabled — an
        # untested privacy claim (ADR-0044 D5). Reject any of them.
        local disabled_forbidden
        for disabled_forbidden in recording_worm record_before_fanout recording_retention_days recording_retention_owner_ref recording_retention_unit; do
          if [ -n "$(printf '%s\n' "$marker_body" | waiver_field "$disabled_forbidden")" ]; then
            missing+=("${disabled_forbidden}:forbidden-when-disabled")
          fi
        done
        required_negatives+=(recording-disabled-no-persistence metadata-audit-on)
        ;;
      enabled)
        # Opt-in recording re-arms the fail-closed controls + parametric retention.
        [ "$(printf '%s\n' "$marker_body" | waiver_field 'recording_worm')" = "pass" ] || missing+=("recording_worm")
        [ "$(printf '%s\n' "$marker_body" | waiver_field 'record_before_fanout')" = "pass" ] || missing+=("record_before_fanout")
        [[ "$(printf '%s\n' "$marker_body" | waiver_field 'recording_retention_days')" =~ ^[1-9][0-9]*$ ]] || missing+=("recording_retention_days")
        [ "$(printf '%s\n' "$marker_body" | waiver_field 'recording_retention_unit')" = "days" ] || missing+=("recording_retention_unit")
        [ -n "$(printf '%s\n' "$marker_body" | waiver_field 'recording_retention_owner_ref')" ] || missing+=("recording_retention_owner_ref")
        required_negatives+=(recording-down)
        ;;
      *)
        missing+=("recording_mode")
        ;;
    esac
    for negative in "${required_negatives[@]}"; do
      csv_has "$audit_negative_matrix" "$negative" || missing+=("audit_negative_matrix:$negative")
    done

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
      lineage_print_check 'GATE_VIEW_ONLY_ENGINEERING' 'blocked' "state=$state issue=$ref title=$(printf '%q' "$title") reason=$reason"
      return 1
    fi
    lineage_print_check 'GATE_VIEW_ONLY_ENGINEERING' 'pass' "state=$state issue=$ref owner=$owner session_id=$session_id recording_mode=$recording_mode evidence_package_sha256=$evidence_package_sha256 expires_at=$expires_at"
    return 0
  fi

  lineage_print_check 'GATE_VIEW_ONLY_ENGINEERING' 'blocked' "state=$state expected=CLOSED-with-view-only-engineering-acceptance issue=$ref title=$(printf '%q' "$title") reason=missing-acceptance-marker"
  return 1
}

check_view_only_kvkk() {
  # ADR-0044 D1/D4: the KVKK/legal track is TRACKED but NON-BLOCKING. This gate
  # ALWAYS emits a status line (visible, never lost) and returns 0 (does not
  # fail-close F22_6_COMPLETION) for genuine legal states (tracked_pending |
  # cleared | expired). The ONE exception is an ALLOWLIST VIOLATION: if the
  # F22_6_VIEW_ONLY_KVKK marker carries any key outside the enumerated
  # legal/DPO/retention allowlist (i.e. a security/product/audit field mislabeled
  # as "legal" to sneak it into the non-blocking track), that IS an integrity
  # violation and returns 1 (blocks). Non-blocking-ness applies to genuine legal
  # items only, never to weakening a gate (Codex 019f05cc #3).
  local ref="$VIEW_ONLY_KVKK_REF" issue_json body title marker_count_value marker_body
  if ! issue_json="$(issue_json_for_ref "$ref")"; then
    # Non-blocking gate: surface fetch failure as tracked_pending, do not block.
    lineage_print_check 'GATE_VIEW_ONLY_KVKK' 'tracked_pending' "ref=$ref reason=issue-fetch-failed"
    return 0
  fi
  body="$(printf '%s\n' "$issue_json" | jq -r '.body // ""')"
  title="$(printf '%s\n' "$issue_json" | jq -r '.title // ""')"
  marker_count_value="$(printf '%s\n' "$body" | marker_count 'F22_6_VIEW_ONLY_KVKK')"

  if [ "$marker_count_value" -eq 0 ]; then
    lineage_print_check 'GATE_VIEW_ONLY_KVKK' 'tracked_pending' "issue=$ref reason=no-kvkk-marker"
    return 0
  fi

  # Allowlist (whitelist) enforcement over ALL KVKK blocks, evaluated BEFORE the
  # duplicate short-circuit so a second marker carrying a forbidden key cannot
  # slip through (Codex 019f05cc post-impl #1). Every field key in any
  # F22_6_VIEW_ONLY_KVKK block must be in VIEW_ONLY_KVKK_ALLOWED_KEYS; any other
  # key is an attempt to reclassify a non-legal field as legal ->
  # allowlist_violation -> blocks.
  local key violations=()
  while IFS= read -r key; do
    [ -z "$key" ] && continue
    csv_has "$VIEW_ONLY_KVKK_ALLOWED_KEYS" "$key" || violations+=("$key")
  done < <(printf '%s\n' "$body" | awk '
    /^```/ { fenced = !fenced; next }
    fenced { next }
    $0 ~ /^F22_6_VIEW_ONLY_KVKK:[[:space:]]*v1[[:space:]]*$/ { inblock = 1; next }
    inblock {
      if ($0 ~ /^[A-Za-z0-9_]+:/) { k = $0; sub(/:.*/, "", k); print k; next }
      inblock = 0
    }
  ')
  if [ "${#violations[@]}" -ne 0 ]; then
    local violation_list
    violation_list="$(printf '%s\n' "${violations[@]}" | LC_ALL=C sort -u | paste -sd, -)"
    lineage_print_check 'GATE_VIEW_ONLY_KVKK' 'allowlist_violation' "issue=$ref title=$(printf '%q' "$title") forbidden_keys=$violation_list"
    return 1
  fi

  if [ "$marker_count_value" -gt 1 ]; then
    lineage_print_check 'GATE_VIEW_ONLY_KVKK' 'tracked_pending' "issue=$ref reason=duplicate-marker"
    return 0
  fi

  marker_body="$(printf '%s\n' "$body" | marker_block 'F22_6_VIEW_ONLY_KVKK')"

  local status owner approved_at expires_at
  local attended_signoff legal_consent retention_approval payload_digest decision_digest decision_ref policy_digest policy_ref
  local privacy_key_id privacy_key_fingerprint privacy_signed_at privacy_signature
  local legal_key_id legal_key_fingerprint legal_signed_at legal_signature
  status="$(printf '%s\n' "$marker_body" | waiver_field 'status')"
  attended_signoff="$(printf '%s\n' "$marker_body" | waiver_field 'kvkk_attended_pilot_signoff')"
  legal_consent="$(printf '%s\n' "$marker_body" | waiver_field 'legal_dpo_consent')"
  retention_approval="$(printf '%s\n' "$marker_body" | waiver_field 'retention_policy_approval')"
  owner="$(printf '%s\n' "$marker_body" | waiver_field 'owner_approved_by')"
  approved_at="$(printf '%s\n' "$marker_body" | waiver_field 'approved_at')"
  expires_at="$(printf '%s\n' "$marker_body" | waiver_field 'expires_at')"
  payload_digest="$(printf '%s\n' "$marker_body" | waiver_field 'decision_payload_sha256')"
  decision_digest="$(printf '%s\n' "$marker_body" | waiver_field 'decision_record_sha256')"
  decision_ref="$(printf '%s\n' "$marker_body" | waiver_field 'decision_record_ref')"
  policy_digest="$(printf '%s\n' "$marker_body" | waiver_field 'approver_policy_sha256')"
  policy_ref="$(printf '%s\n' "$marker_body" | waiver_field 'approver_policy_ref')"
  privacy_key_id="$(printf '%s\n' "$marker_body" | waiver_field 'privacy_owner_key_id')"
  privacy_key_fingerprint="$(printf '%s\n' "$marker_body" | waiver_field 'privacy_owner_public_key_sha256')"
  privacy_signed_at="$(printf '%s\n' "$marker_body" | waiver_field 'privacy_owner_signed_at')"
  privacy_signature="$(printf '%s\n' "$marker_body" | waiver_field 'privacy_owner_signature')"
  legal_key_id="$(printf '%s\n' "$marker_body" | waiver_field 'legal_dpo_key_id')"
  legal_key_fingerprint="$(printf '%s\n' "$marker_body" | waiver_field 'legal_dpo_public_key_sha256')"
  legal_signed_at="$(printf '%s\n' "$marker_body" | waiver_field 'legal_dpo_signed_at')"
  legal_signature="$(printf '%s\n' "$marker_body" | waiver_field 'legal_dpo_signature')"

  if [ "$status" = "cleared" ]; then
    # A real clear is generated from a schema-valid, dual-human-signed decision
    # record. The marker discloses only a content digest and its content-addressed
    # URN, never the protected record location or pilot identifiers.
    local incomplete=()
    [ "$attended_signoff" = "pass" ] || incomplete+=("kvkk_attended_pilot_signoff")
    [ "$legal_consent" = "pass" ] || incomplete+=("legal_dpo_consent")
    [ "$retention_approval" = "pass" ] || incomplete+=("retention_policy_approval")
    [[ "$owner" =~ ^dual-human-signature:[A-Za-z0-9._-]{3,120}$ ]] || incomplete+=("owner_approved_by")
    [[ "$payload_digest" =~ ^sha256:[a-f0-9]{64}$ ]] || incomplete+=("decision_payload_sha256")
    [[ "$decision_digest" =~ ^sha256:[a-f0-9]{64}$ ]] || incomplete+=("decision_record_sha256")
    [ "$decision_ref" = "urn:decision-record:$decision_digest" ] || incomplete+=("decision_record_ref")
    [[ "$policy_digest" =~ ^sha256:[a-f0-9]{64}$ ]] || incomplete+=("approver_policy_sha256")
    [ "$policy_ref" = "urn:approver-policy:$policy_digest" ] || incomplete+=("approver_policy_ref")
    [ -n "$approved_at" ] || incomplete+=("approved_at")
    [ -n "$expires_at" ] || incomplete+=("expires_at")
    [[ "$privacy_key_id" =~ ^kvkk-[a-z0-9][a-z0-9-]{2,62}$ ]] || incomplete+=("privacy_owner_key_id")
    [[ "$privacy_key_fingerprint" =~ ^sha256:[a-f0-9]{64}$ ]] || incomplete+=("privacy_owner_public_key_sha256")
    [ -n "$privacy_signed_at" ] || incomplete+=("privacy_owner_signed_at")
    [[ "$privacy_signature" =~ ^[A-Za-z0-9+/]{86}==$ ]] || incomplete+=("privacy_owner_signature")
    [[ "$legal_key_id" =~ ^kvkk-[a-z0-9][a-z0-9-]{2,62}$ ]] || incomplete+=("legal_dpo_key_id")
    [[ "$legal_key_fingerprint" =~ ^sha256:[a-f0-9]{64}$ ]] || incomplete+=("legal_dpo_public_key_sha256")
    [ -n "$legal_signed_at" ] || incomplete+=("legal_dpo_signed_at")
    [[ "$legal_signature" =~ ^[A-Za-z0-9+/]{86}==$ ]] || incomplete+=("legal_dpo_signature")
    [ -f "$VIEW_ONLY_KVKK_APPROVER_POLICY_PATH" ] || incomplete+=("canonical-approver-policy-missing")
    if [ "${#incomplete[@]}" -ne 0 ]; then
      local incomplete_reason
      incomplete_reason="$(IFS=,; printf '%s' "${incomplete[*]}")"
      lineage_print_check 'GATE_VIEW_ONLY_KVKK' 'tracked_pending' "issue=$ref reason=incomplete-clear:$incomplete_reason"
      return 0
    fi
    local marker_verifier_result marker_verifier_status
    if ! marker_verifier_result="$(printf '%s\n' "$marker_body" | python3 "$SCRIPT_DIR/verify-view-only-kvkk-decision.py" \
      --approver-policy "$VIEW_ONLY_KVKK_APPROVER_POLICY_PATH" --verify-marker-input - 2>/dev/null)"; then
      lineage_print_check 'GATE_VIEW_ONLY_KVKK' 'tracked_pending' "issue=$ref reason=cryptographic-marker-verification-failed"
      return 0
    fi
    marker_verifier_status="$(printf '%s\n' "$marker_verifier_result" | jq -r '.status // "fail"')"
    if [ "$marker_verifier_status" = "expired" ]; then
      lineage_print_check 'GATE_VIEW_ONLY_KVKK' 'expired' "issue=$ref owner=$owner expires_at=$expires_at decision_record_sha256=$decision_digest"
      return 0
    fi
    if [ "$marker_verifier_status" != "pass" ]; then
      lineage_print_check 'GATE_VIEW_ONLY_KVKK' 'tracked_pending' "issue=$ref reason=cryptographic-marker-verifier-status:$marker_verifier_status"
      return 0
    fi
    lineage_print_check 'GATE_VIEW_ONLY_KVKK' 'cleared' "issue=$ref owner=$owner approved_at=$approved_at expires_at=$expires_at decision_record_sha256=$decision_digest"
    return 0
  fi

  lineage_print_check 'GATE_VIEW_ONLY_KVKK' 'tracked_pending' "issue=$ref status=$(printf '%q' "${status:-unset}")"
  return 0
}

remote_bridge_query_cmd() {
  # remote_bridge_query_cmd <q_context> <q_namespace>
  # Echo a single shell command that emits four marker-delimited JSON blocks
  # (deploys, pods, ExternalSecrets). The SAME command runs locally (bash -c) and
  # remotely (ssh), so the exact-parse below is identical in both modes.
  local q_context="$1" q_namespace="$2" q_selector
  q_selector="$(shell_quote 'app.kubernetes.io/name in (endpoint-admin-service,endpoint-admin-remote-bridge,endpoint-admin-remote-bridge-device-key)')"
  printf '%s' "echo '===RB_DEPLOYS==='; kubectl --context $q_context -n $q_namespace get deploy endpoint-admin-service endpoint-admin-remote-bridge endpoint-admin-remote-bridge-device-key --ignore-not-found -o json; echo '===RB_PODS==='; kubectl --context $q_context -n $q_namespace get pod -l $q_selector -o json; echo '===RB_ES==='; kubectl --context $q_context -n $q_namespace get externalsecret endpoint-admin-remote-bridge-secrets endpoint-admin-remote-bridge-signer endpoint-admin-remote-bridge-tls endpoint-admin-remote-bridge-secrets-device-key endpoint-admin-remote-bridge-signer-device-key endpoint-admin-remote-bridge-tls-device-key --ignore-not-found -o json; echo '===RB_INGRESS==='; kubectl --context $q_context -n $q_namespace get ingress endpoint-admin-remote-bridge-mtls -o json"
}

_rb_section() {
  # _rb_section <combined-output> <marker>; print the JSON block after ===<marker>===.
  printf '%s\n' "$1" | awk -v m="===$2===" '
    $0 == m { grab = 1; next }
    /^===RB_[A-Z]+===$/ { grab = 0 }
    grab { print }
  '
}

evaluate_remote_bridge_live() {
  # evaluate_remote_bridge_live <expected-digest> <deploys-json> <pods-json> <es-json> <ingress-json>
  # Exact per-object assertions (Codex 019f0733 P1/P2 — replaces grep-count, which
  # could mask object-specific drift): endpoint-admin-service and the active SNI
  # broker deployment carry the expected image; for each app label there is >=1
  # non-deleting Running pod and ALL such pods are Ready on the expected imageID
  # (no pod on a wrong digest); the active broker's ExternalSecrets are
  # Ready=True/SecretSynced. The active broker is derived from the public SNI
  # Ingress so the #548 device-key live wrapper does not get blocked by the
  # now-inactive enrollment-backed broker deployment.
  local expected="$1" deploys="$2" pods="$3" es="$4" ingress="$5"
  local full="${RBD_IMG}@${expected}" reasons=() d lbl active_broker active_secret_suffix

  active_broker="$(printf '%s' "$ingress" | jq -r '
    [ .spec.rules[]?
      | select(.host == "remote-bridge-mtls.testai.acik.com")
      | .http.paths[]?.backend.service.name ] | first // ""' 2>/dev/null || true)"
  case "$active_broker" in
    endpoint-admin-remote-bridge)
      active_secret_suffix=""
      ;;
    endpoint-admin-remote-bridge-device-key)
      active_secret_suffix="-device-key"
      ;;
    "")
      reasons+=("ingress:endpoint-admin-remote-bridge-mtls")
      active_broker="endpoint-admin-remote-bridge"
      active_secret_suffix=""
      ;;
    *)
      reasons+=("ingress:unexpected-backend:$active_broker")
      active_secret_suffix=""
      ;;
  esac

  for d in endpoint-admin-service "$active_broker"; do
    printf '%s' "$deploys" | jq -e --arg n "$d" --arg f "$full" \
      '([.items[]|select(.metadata.name==$n)]|length==1)
       and ([.items[]|select(.metadata.name==$n)][0].spec.template.spec.containers[0].image==$f)' \
      >/dev/null 2>&1 || reasons+=("deploy:$d")
  done
  for lbl in endpoint-admin-service "$active_broker"; do
    printf '%s' "$pods" | jq -e --arg n "$lbl" --arg e "$expected" '
      [ .items[]
        | select(.metadata.deletionTimestamp == null)
        | select(.metadata.labels["app.kubernetes.io/name"] == $n)
        | select(.status.phase == "Running") ] as $p
      | ($p | length >= 1)
        and (all($p[];
              (.status.containerStatuses[0].ready == true)
              and (.status.containerStatuses[0].imageID | contains($e))))' \
    >/dev/null 2>&1 || reasons+=("pods:$lbl")
  done
  # Per-name exact-one + an explicit Ready=True/SecretSynced condition. Using
  # `any` over `(.status.conditions // [])` (not a select-stream inside all()) so an
  # ExternalSecret that EXISTS but has no Ready condition fails closed instead of
  # being silently skipped (Codex 019f0733 P1).
  printf '%s' "$es" | jq -e --arg suffix "$active_secret_suffix" '
    def es_ready($n):
      ([.items[] | select(.metadata.name == $n)] | length == 1)
      and ([.items[] | select(.metadata.name == $n)][0].status.conditions // []
            | any(.type == "Ready" and .status == "True" and .reason == "SecretSynced"));
    es_ready("endpoint-admin-remote-bridge-secrets" + $suffix)
    and es_ready("endpoint-admin-remote-bridge-signer" + $suffix)
    and es_ready("endpoint-admin-remote-bridge-tls" + $suffix)' \
    >/dev/null 2>&1 || reasons+=("externalsecrets")
  if [ "${#reasons[@]}" -ne 0 ]; then
    printf 'blocked reason=%s' "$(IFS=,; printf '%s' "${reasons[*]}")"
    return 1
  fi
  printf 'ok'
  return 0
}

check_remote_bridge() {
  local output effective_mode rb_query q_context q_namespace
  local expected_digest expected_source expected_ref derive_rc
  local deploys_json pods_json es_json ingress_json eval_out eval_rc
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

  # Derive the expected digest from the rendered overlay (single SSOT, #2067 /
  # Codex 019f0733). An env-set EXPECTED_REMOTE_BRIDGE_DIGEST is honored ONLY as an
  # explicit diagnostic escape hatch (ALLOW_EXPECTED_DIGEST_OVERRIDE=1) and is
  # marked expected_source=env_override — never a silent fallback for a canonical pass.
  expected_source="rendered-overlay"
  if [ -n "${EXPECTED_REMOTE_BRIDGE_DIGEST:-}" ]; then
    if [ "${ALLOW_EXPECTED_DIGEST_OVERRIDE:-0}" = "1" ]; then
      expected_source="env_override"
      expected_digest="$EXPECTED_REMOTE_BRIDGE_DIGEST"
    else
      printf 'REMOTE_BRIDGE_LIVE=unknown mode=%s reason=expected-digest-env-set-without-ALLOW_EXPECTED_DIGEST_OVERRIDE\n' "$effective_mode"
      return 1
    fi
  else
    derive_rc=0
    expected_ref="$(rbd_expected_digest)" || derive_rc=$?
    case "$derive_rc" in
      0) expected_digest="${expected_ref##*@}" ;;
      3) printf 'REMOTE_BRIDGE_LIVE=unknown mode=%s reason=missing-kustomize-and-kubectl-for-expected-digest\n' "$effective_mode"; return 1 ;;
      4) printf 'REMOTE_BRIDGE_LIVE=unknown mode=%s reason=overlay-digest-drift-primary-ne-bridge\n' "$effective_mode"; return 1 ;;
      *) printf 'REMOTE_BRIDGE_LIVE=unknown mode=%s reason=expected-digest-derivation-failed code=%s\n' "$effective_mode" "$derive_rc"; return 1 ;;
    esac
  fi
  if ! printf '%s' "$expected_digest" | grep -Eq '^sha256:[a-f0-9]{64}$'; then
    printf 'REMOTE_BRIDGE_LIVE=unknown mode=%s reason=expected-digest-malformed expected_source=%s\n' "$effective_mode" "$expected_source"
    return 1
  fi

  if ! command -v jq >/dev/null 2>&1; then
    printf 'REMOTE_BRIDGE_LIVE=unknown mode=%s reason=missing-jq\n' "$effective_mode"
    return 1
  fi
  q_context="$(shell_quote "$KUBE_CONTEXT")"
  q_namespace="$(shell_quote "$KUBE_NAMESPACE")"
  rb_query="$(remote_bridge_query_cmd "$q_context" "$q_namespace")"
  if [ "$effective_mode" = "local-kubectl" ]; then
    if ! command -v kubectl >/dev/null 2>&1; then
      printf 'REMOTE_BRIDGE_LIVE=unknown mode=%s reason=missing-kubectl\n' "$effective_mode"
      return 1
    fi
    if ! output="$(bash -c "$rb_query" 2>&1)"; then
      printf 'REMOTE_BRIDGE_LIVE=unknown mode=%s reason=%q\n' "$effective_mode" "$output"
      return 1
    fi
  else
    if ! command -v ssh >/dev/null 2>&1; then
      printf 'REMOTE_BRIDGE_LIVE=unknown mode=ssh reason=missing-ssh\n'
      return 1
    fi
    # shellcheck disable=SC2029 # rb_query is composed from shell_quote'd context/namespace; intentional remote expansion.
    if ! output="$(ssh_cmd "$SSH_TARGET" "$rb_query" 2>&1)"; then
      printf 'REMOTE_BRIDGE_LIVE=unknown mode=ssh reason=%q\n' "$output"
      return 1
    fi
  fi

  deploys_json="$(_rb_section "$output" RB_DEPLOYS)"
  pods_json="$(_rb_section "$output" RB_PODS)"
  es_json="$(_rb_section "$output" RB_ES)"
  ingress_json="$(_rb_section "$output" RB_INGRESS)"
  eval_rc=0
  eval_out="$(evaluate_remote_bridge_live "$expected_digest" "$deploys_json" "$pods_json" "$es_json" "$ingress_json")" || eval_rc=$?

  # Env-override is a DIAGNOSTIC escape hatch only — it can NEVER be a canonical
  # completion source (Codex 019f0733 P1). Always return non-zero in that mode so
  # main() never folds it into F22_6_COMPLETION=pass.
  if [ "$expected_source" = "env_override" ]; then
    if [ "$eval_rc" = 0 ]; then
      printf 'REMOTE_BRIDGE_LIVE=diagnostic_pass mode=%s expected_source=env_override expected_digest=%s reason=env-override-not-canonical\n' "$effective_mode" "$expected_digest"
    else
      printf 'REMOTE_BRIDGE_LIVE=diagnostic_blocked mode=%s expected_source=env_override expected_digest=%s %s\n' "$effective_mode" "$expected_digest" "$eval_out"
    fi
    return 1
  fi

  if [ "$eval_rc" = 0 ]; then
    printf 'REMOTE_BRIDGE_LIVE=pass mode=%s expected_source=%s expected_digest=%s\n' "$effective_mode" "$expected_source" "$expected_digest"
    return 0
  fi
  printf 'REMOTE_BRIDGE_LIVE=blocked mode=%s expected_source=%s expected_digest=%s %s\n' "$effective_mode" "$expected_source" "$expected_digest" "$eval_out"
  return 1
}

check_release_lineage_gate() {
  local output lineage_line lineage_status effective_mode release_mode
  release_mode="${RELEASE_LINEAGE_KUBECTL_MODE:-$REMOTE_BRIDGE_KUBECTL_MODE}"
  case "$release_mode" in
    local|local-kubectl) effective_mode="local-kubectl" ;;
    ssh) effective_mode="ssh" ;;
    *)
      lineage_print_check 'RELEASE_LINEAGE_GATE' 'blocked' "mode=$(printf '%q' "$release_mode") reason=invalid-release-lineage-kubectl-mode"
      return 1
      ;;
  esac
  if [ "$SSH_TARGET" = "local" ]; then
    effective_mode="local-kubectl"
  fi

  if output="$(
    RELEASE_LINEAGE_KUBECTL_MODE="$effective_mode" \
      SSH_TARGET="$SSH_TARGET" \
      SSH_OPTS="$SSH_OPTS" \
      KUBE_CONTEXT="$KUBE_CONTEXT" \
      KUBE_NAMESPACE="$KUBE_NAMESPACE" \
      bash "$SCRIPT_DIR/faz22-6-release-lineage-audit.sh" 2>&1
  )"; then
    :
  else
    lineage_line="$(printf '%s\n' "$output" | awk -F= '$1 == "F22_6_RELEASE_LINEAGE" { line = $0 } END { print line }')"
    if [ -z "$lineage_line" ]; then
      printf 'RELEASE_LINEAGE_AUDIT_OUTPUT_BEGIN\n%s\nRELEASE_LINEAGE_AUDIT_OUTPUT_END\n' "$output"
      lineage_print_check 'RELEASE_LINEAGE_GATE' 'blocked' "mode=$effective_mode reason=release-lineage-audit-failed-without-status"
      return 1
    fi
  fi

  printf 'RELEASE_LINEAGE_AUDIT_OUTPUT_BEGIN\n%s\nRELEASE_LINEAGE_AUDIT_OUTPUT_END\n' "$output"
  lineage_line="$(printf '%s\n' "$output" | awk -F= '$1 == "F22_6_RELEASE_LINEAGE" { line = $0 } END { print line }')"
  if [ -z "$lineage_line" ]; then
    lineage_print_check 'RELEASE_LINEAGE_GATE' 'blocked' "mode=$effective_mode reason=missing-F22_6_RELEASE_LINEAGE"
    return 1
  fi

  lineage_status="${lineage_line#F22_6_RELEASE_LINEAGE=}"
  case "$lineage_status" in
    pass)
      lineage_print_check 'RELEASE_LINEAGE_GATE' 'pass' "mode=$effective_mode status=$lineage_status"
      return 0
      ;;
    bounded_pilot_pass)
      lineage_print_check 'RELEASE_LINEAGE_GATE' 'bounded_pilot_pass' "mode=$effective_mode status=$lineage_status"
      return 0
      ;;
    blocked|needs_hygiene)
      lineage_print_check 'RELEASE_LINEAGE_GATE' 'blocked' "mode=$effective_mode status=$lineage_status"
      return 1
      ;;
    *)
      lineage_print_check 'RELEASE_LINEAGE_GATE' 'blocked' "mode=$effective_mode status=$(printf '%q' "$lineage_status") reason=unexpected-release-lineage-status"
      return 1
      ;;
  esac
}

main() {
  need grep
  need awk
  need jq
  need curl
  need python3
  local github_backend
  if ! github_read_api_preflight; then
    printf 'F22_6_AUDIT_ERROR=github-read-api-unavailable backend=%q\n' "$GITHUB_READ_API_BACKEND"
    exit 2
  fi
  github_backend="$(github_read_api_backend)"
  if [ "$REMOTE_BRIDGE_KUBECTL_MODE" = "local" ] || [ "$REMOTE_BRIDGE_KUBECTL_MODE" = "local-kubectl" ] || [ "$SSH_TARGET" = "local" ]; then
    need kubectl
  else
    need ssh
  fi

  local blocked=0
  local next_required=()

  printf 'F22_6_AUDIT_SCOPE=remote-ops-autonomous-completion\n'
  printf 'F22_6_AUDIT_CONTRACT=docs/runbooks/RB-faz22.6-autonomous-completion-contract.md\n'
  printf 'F22_6_GITHUB_READ_BACKEND=%s\n' "$github_backend"

  pass_if_state 'GATE_22_6_1_OPERATION_CATALOG' "$BACKEND_REPO" 701 CLOSED || blocked=1
  pass_if_state 'GATE_22_6_2_APPROVED_SCRIPT_RUNNER' "$BACKEND_REPO" 702 CLOSED || blocked=1
  pass_if_state 'GATE_22_6_3_CONSTRAINED_EXECUTOR' "$AGENT_REPO" 208 CLOSED || blocked=1

  if check_b1_4_hardware_gate; then
    :
  else
    blocked=1
    next_required+=('b1-4-acceptance-package-required')
  fi

  if check_view_only_engineering_gate; then
    :
  else
    blocked=1
    next_required+=('view-only-engineering-evidence-package-required')
  fi

  # ADR-0044 D1/D4: KVKK is a tracked, NON-BLOCKING legal track. This gate always
  # emits a GATE_VIEW_ONLY_KVKK status line (tracked_pending|cleared|expired) so
  # the legal obligation stays visible, but it does NOT fail-close completion. The
  # only blocking path is an allowlist violation (a security/product field
  # mislabeled as "legal" to sneak into the non-blocking track).
  if ! check_view_only_kvkk; then
    blocked=1
    next_required+=('view-only-kvkk-allowlist-violation')
  fi

  if ! check_remote_bridge; then
    blocked=1
    next_required+=('remote-bridge-live-evidence-required')
  fi
  if ! check_release_lineage_gate; then
    blocked=1
    next_required+=('release-lineage-audit-pass-required')
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
