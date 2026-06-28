#!/usr/bin/env bash
# Conservative Faz 22.6 EndpointAgent release-lineage audit.
#
# This helper is read-only. It validates the published GitHub release, the
# test artifact-host "current" surface, and the live artifact-host deployment
# before broad rollout language can be used for the rapid v0.2.x line.

set -euo pipefail

AGENT_REPO="${AGENT_REPO:-Halildeu/platform-agent}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/faz22-remote-ops/endpoint-agent-release-policy.sh
source "$SCRIPT_DIR/endpoint-agent-release-policy.sh"
endpoint_agent_release_policy_load "$REPO_ROOT"

SSH_TARGET="${SSH_TARGET:-staging-sw}"
SSH_OPTS="${SSH_OPTS:-}"
RELEASE_LINEAGE_KUBECTL_MODE="${RELEASE_LINEAGE_KUBECTL_MODE:-ssh}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
MIN_ARTIFACT_HOST_DIGEST_HITS="${MIN_ARTIFACT_HOST_DIGEST_HITS:-2}"
CURL_MAX_TIME="${CURL_MAX_TIME:-20}"
GITHUB_RELEASE_BASE_URL="${GITHUB_RELEASE_BASE_URL:-https://github.com/${AGENT_REPO}/releases/download/${EXPECTED_AGENT_TAG}}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'F22_6_RELEASE_LINEAGE_ERROR=missing-command:%s\n' "$1"
    exit 2
  }
}

print_check() {
  # print_check <label> <status> <details...>
  local label="$1" status="$2"
  shift 2
  printf '%s=%s' "$label" "$status"
  if [ "$#" -gt 0 ]; then
    printf ' %s' "$*"
  fi
  printf '\n'
}

sha_from_sums() {
  # sha_from_sums <file-name> <sums-text>
  local name="$1"
  local sums="$2"
  awk -v n="$name" '$2 == n {print $1; found=1} END {if (!found) exit 1}' <<<"$sums"
}

shell_quote() {
  # shell_quote <value>
  printf '%q' "$1"
}

ssh_cmd() {
  # ssh_cmd <target> <remote-command>
  #
  # Field operators often need identity-scoped SSH (for example,
  # `-o IdentitiesOnly=yes -i ~/.ssh/id_ed25519`) to avoid OpenSSH offering too
  # many local keys before the accepted key. Keep the default behavior unchanged,
  # but allow bounded options via SSH_OPTS for live audit runs.
  local target="$1" remote_cmd="$2"
  local opts=()
  if [ -n "$SSH_OPTS" ]; then
    # shellcheck disable=SC2206 # SSH_OPTS is an operator-provided shellwords string.
    opts=($SSH_OPTS)
  fi
  # shellcheck disable=SC2029 # remote_cmd is intentionally composed client-side by the caller.
  ssh "${opts[@]}" "$target" "$remote_cmd"
}

fetch_url() {
  # fetch_url <url>
  # Keep the audit bounded and avoid stale CDN bytes after metadata-only release repairs.
  curl --max-time "$CURL_MAX_TIME" -fsSL -H 'Cache-Control: no-cache' "$1"
}

artifact_host_kubectl_output() {
  kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" get deploy artifact-host \
    -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,UPDATED:.status.updatedReplicas,IMAGE:.spec.template.spec.containers[0].image
  kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" get pod \
    -l app.kubernetes.io/name=artifact-host \
    -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,IMAGEID:.status.containerStatuses[0].imageID
}

waiver_field() {
  # waiver_field <key>; reads the issue body from stdin.
  local key="$1"
  sed -n "s/^${key}:[[:space:]]*//p" | head -1
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
  # date_window_errors <approved_at> <expires_at>
  local approved_at="$1" expires_at="$2" today
  local missing=()
  if ! [[ "$approved_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    missing+=("approved_at")
  fi
  if ! [[ "$expires_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    missing+=("expires_at")
  fi
  if [[ "$approved_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] \
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
    if [[ "$expires_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && [[ "$expires_at" < "$today" ]]; then
      missing+=("expires_at-expired")
    fi
  fi
  if [ "${#missing[@]}" -ne 0 ]; then
    local reason
    reason="$(IFS=,; printf '%s' "${missing[*]}")"
    printf '%s' "$reason"
  fi
}

check_release_lineage_waiver() {
  # check_release_lineage_waiver <comma-separated-required-findings>
  local required_findings="$1"
  local ref="$RELEASE_LINEAGE_WAIVER_REF"
  local repo_ref number issue_json state body marker_count_value marker_body date_errors
  local marker scope release_tag digest accepted_findings forbidden_claims owner approved_at expires_at
  local missing=()

  if [ -z "$ref" ]; then
    print_check 'RELEASE_LINEAGE_WAIVER' 'missing' 'reason=no-waiver-ref'
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
    print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref reason=bad-ref-format"
    return 1
  fi

  if ! issue_json="$(gh issue view "$number" -R "$repo_ref" --json state,body,title 2>&1)"; then
    print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref reason=$(printf '%q' "$issue_json")"
    return 1
  fi
  state="$(printf '%s\n' "$issue_json" | jq -r '.state // ""')"
  body="$(printf '%s\n' "$issue_json" | jq -r '.body // ""')"
  if [ "$state" != "OPEN" ]; then
    print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref state=$state reason=issue-not-open"
    return 1
  fi

  marker_count_value="$(printf '%s\n' "$body" | marker_count 'F22_6_RELEASE_LINEAGE_WAIVER')"
  if [ "$marker_count_value" -gt 1 ]; then
    print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref reason=duplicate-marker"
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
  owner_is_invalid "$owner" && missing+=("owner_approved_by")

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
    print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref reason=$reason"
    return 1
  fi

  print_check 'RELEASE_LINEAGE_WAIVER' 'bounded_pilot_pass' "ref=$ref owner=$owner expires_at=$expires_at accepted_findings=$(printf '%q' "$accepted_findings")"
  return 0
}

# release_train_verdict <releases_json>
#
# Pure, network-free release-train graduation/hygiene evaluator (Faz 22.6
# #1939). It does NOT call gh/curl/ssh/kubectl, so the test harness can drive
# it directly with fixtures. It decouples the live release-train check from the
# bounded-pilot deploy pin:
#   - graduation is asserted against the latest STABLE release matching the
#     trusted series (NOT an exact pinned tag, so the train may move ahead of
#     the deployed bounded pilot);
#   - the GitHub "latest" pointer being a prerelease/draft is hygiene, not a
#     series block;
#   - a frozen-series (v0.2.x) release published at/after the trusted-lineage
#     boundary is a regression (hygiene). Historical v0.2.x before the boundary
#     are fine — never counted, never deleted;
#   - too many active trusted-series releases in the window is hygiene that
#     requires a lineage audit/waiver — it is never auto-passed and never
#     triggers a delete.
#
# Emits human-readable GITHUB_RELEASE_* check lines to stdout, then two machine
# lines the caller parses:
#   RELEASE_TRAIN_VERDICT=<pass|blocked_empty|blocked_series|needs_hygiene>
#   RELEASE_TRAIN_WAIVER_FINDINGS=<comma-separated waiver-eligible findings>
# Returns 0 for pass/needs_hygiene (caller decides waiver), 1 for blocked_*.
release_train_verdict() {
  local releases_json="$1"
  local trusted_regex="$AGENT_RELEASE_TRUSTED_SERIES_REGEX"
  local boundary="$AGENT_RELEASE_TRUSTED_LINEAGE_STARTED_AT"
  local dense_threshold="$AGENT_RELEASE_ACTIVE_SERIES_DENSE_THRESHOLD"
  local waiver_findings=()

  # Latest STABLE release = newest non-draft, non-prerelease (by publishedAt desc).
  local latest_stable
  latest_stable="$(printf '%s\n' "$releases_json" | jq -r '
    [ .[] | select((.isDraft // false | not) and (.isPrerelease // false | not)) ]
    | sort_by(.publishedAt) | reverse | (.[0].tagName // "")')"

  if [ -z "$latest_stable" ]; then
    print_check 'GITHUB_RELEASE_LATEST_STABLE' 'blocked' 'reason=no-stable-release'
    printf 'RELEASE_TRAIN_VERDICT=blocked_empty\n'
    printf 'RELEASE_TRAIN_WAIVER_FINDINGS=\n'
    return 1
  fi

  if printf '%s\n' "$latest_stable" | grep -Eq "$trusted_regex"; then
    print_check 'GITHUB_RELEASE_TRAIN_SERIES' 'pass' "latest_stable=$latest_stable trusted_series=$AGENT_RELEASE_SERIES_LABEL"
  else
    print_check 'GITHUB_RELEASE_TRAIN_SERIES' 'blocked' "latest_stable=$latest_stable trusted_series=$AGENT_RELEASE_SERIES_LABEL reason=latest-stable-not-on-trusted-series"
    printf 'RELEASE_TRAIN_VERDICT=blocked_series\n'
    printf 'RELEASE_TRAIN_WAIVER_FINDINGS=\n'
    return 1
  fi

  local needs_hygiene=0

  # GitHub "latest" pointer hygiene: the pointer being a prerelease/draft does
  # not block the series (latest STABLE already validated above) but is flagged.
  local pointer_kind
  pointer_kind="$(printf '%s\n' "$releases_json" | jq -r '
    ([ .[] | select(.isLatest // false) ] | .[0]) as $p
    | if $p == null then "none"
      elif ($p.isDraft // false) then "draft"
      elif ($p.isPrerelease // false) then "prerelease"
      else "stable" end')"
  if [ "$pointer_kind" = "draft" ] || [ "$pointer_kind" = "prerelease" ]; then
    print_check 'GITHUB_RELEASE_LATEST_POINTER' 'needs_hygiene' "pointer_kind=$pointer_kind reason=github-latest-is-prerelease-or-draft"
    needs_hygiene=1
    waiver_findings+=('GITHUB_RELEASE_LATEST_POINTER')
  else
    print_check 'GITHUB_RELEASE_LATEST_POINTER' 'pass' "pointer_kind=$pointer_kind"
  fi

  # Frozen-series regression: frozen-minor.x published at/after the trusted boundary.
  # Derive the frozen-series regex from the SSOT minor label (escape dots, anchor,
  # trailing dot) — NOT hardcoded — so a future graduation (e.g. trusted ^v0\.4\.,
  # frozen v0.3) counts post-boundary frozen releases without a code change.
  local frozen_regex
  frozen_regex="^$(printf '%s' "$AGENT_RELEASE_FROZEN_MINOR" | sed 's/\./\\./g')\\."
  local regression_count
  regression_count="$(printf '%s\n' "$releases_json" | jq --arg boundary "$boundary" --arg frozen_regex "$frozen_regex" '
    [ .[] | select((.tagName // "") | test($frozen_regex)) | select((.publishedAt // "") >= $boundary) ] | length')"
  if [ "$regression_count" -gt 0 ]; then
    print_check 'GITHUB_RELEASE_FROZEN_SERIES_REGRESSION' 'needs_hygiene' "frozen_series=$AGENT_RELEASE_FROZEN_MINOR count=$regression_count boundary=$boundary reason=frozen-series-release-after-graduation"
    needs_hygiene=1
    waiver_findings+=('GITHUB_RELEASE_FROZEN_SERIES_REGRESSION')
  else
    print_check 'GITHUB_RELEASE_FROZEN_SERIES_REGRESSION' 'pass' "frozen_series=$AGENT_RELEASE_FROZEN_MINOR count=$regression_count boundary=$boundary"
  fi

  # Active-series density: too many trusted-series releases in the window.
  local active_count
  active_count="$(printf '%s\n' "$releases_json" | jq --arg regex "$trusted_regex" '
    [ .[].tagName | select(test($regex)) ] | length')"
  if [ "$active_count" -ge "$dense_threshold" ]; then
    print_check 'GITHUB_RELEASE_ACTIVE_SERIES_DENSE' 'needs_hygiene' "trusted_series=$AGENT_RELEASE_SERIES_LABEL active_count=$active_count threshold=$dense_threshold reason=active-series-dense-requires-lineage-audit-or-waiver"
    needs_hygiene=1
    waiver_findings+=('GITHUB_RELEASE_ACTIVE_SERIES_DENSE')
  else
    print_check 'GITHUB_RELEASE_ACTIVE_SERIES_DENSE' 'pass' "trusted_series=$AGENT_RELEASE_SERIES_LABEL active_count=$active_count threshold=$dense_threshold"
  fi

  local findings_csv=""
  if [ "${#waiver_findings[@]}" -gt 0 ]; then
    findings_csv="$(IFS=,; printf '%s' "${waiver_findings[*]}")"
  fi
  if [ "$needs_hygiene" -ne 0 ]; then
    printf 'RELEASE_TRAIN_VERDICT=needs_hygiene\n'
  else
    printf 'RELEASE_TRAIN_VERDICT=pass\n'
  fi
  printf 'RELEASE_TRAIN_WAIVER_FINDINGS=%s\n' "$findings_csv"
  return 0
}

main() {
  need gh
  need jq
  need curl
  need awk
  need grep

  local blocked=0
  local needs_hygiene=0
  local nonwaiver_hygiene=0
  local waiver_findings=()

  printf 'F22_6_RELEASE_LINEAGE_SCOPE=endpoint-agent-release-hygiene\n'
  printf 'F22_6_RELEASE_LINEAGE_RUNBOOK=docs/runbooks/RB-faz22.6-release-lineage-audit.md\n'

  local releases bounded_pilot_present is_draft is_prerelease is_immutable
  # RELEASE_LIST_JSON lets the audit run offline against an injected fixture
  # (the release-train verdict is pure; the rest of the audit still needs
  # network/cluster). When unset, live GitHub truth is the gate.
  if [ -n "${RELEASE_LIST_JSON:-}" ]; then
    releases="$RELEASE_LIST_JSON"
    print_check 'GITHUB_RELEASE_LIST' 'pass' 'source=RELEASE_LIST_JSON'
  elif ! releases="$(gh release list -R "$AGENT_REPO" --limit "$RECENT_RELEASE_WINDOW" \
      --json tagName,isLatest,isDraft,isPrerelease,isImmutable,publishedAt,name 2>&1)"; then
    print_check 'GITHUB_RELEASE_LIST' 'blocked' "reason=$(printf '%q' "$releases")"
    blocked=1
    releases='[]'
  fi

  # Release-train graduation/hygiene (pure, decoupled from the deploy pin).
  local train_output train_verdict train_findings
  if train_output="$(release_train_verdict "$releases")"; then
    :
  fi
  printf '%s\n' "$train_output" | grep -E '^GITHUB_RELEASE_' || true
  train_verdict="$(printf '%s\n' "$train_output" | awk -F= '$1 == "RELEASE_TRAIN_VERDICT" { v = $2 } END { print v }')"
  train_findings="$(printf '%s\n' "$train_output" | awk -F= '$1 == "RELEASE_TRAIN_WAIVER_FINDINGS" { v = substr($0, length("RELEASE_TRAIN_WAIVER_FINDINGS=") + 1) } END { print v }')"
  case "$train_verdict" in
    pass) : ;;
    needs_hygiene)
      needs_hygiene=1
      if [ -n "$train_findings" ]; then
        local _f
        IFS=',' read -r -a _f <<<"$train_findings"
        waiver_findings+=("${_f[@]}")
      fi
      ;;
    blocked_empty|blocked_series)
      blocked=1
      ;;
    *)
      print_check 'GITHUB_RELEASE_TRAIN_VERDICT' 'blocked' "verdict=$(printf '%q' "${train_verdict:-missing}") reason=unexpected-release-train-verdict"
      blocked=1
      ;;
  esac

  # Bounded-pilot deploy evidence: the pinned pilot tag must EXIST as a
  # published stable release. It is intentionally NOT required to be GitHub's
  # "latest" (the trusted train moves ahead of the deployed pilot), but it must
  # not be a draft/prerelease.
  is_draft="$(printf '%s\n' "$releases" | jq -r --arg tag "$EXPECTED_AGENT_TAG" 'map(select(.tagName == $tag)) as $m | if ($m|length) > 0 then $m[0].isDraft else true end')"
  is_prerelease="$(printf '%s\n' "$releases" | jq -r --arg tag "$EXPECTED_AGENT_TAG" 'map(select(.tagName == $tag)) as $m | if ($m|length) > 0 then $m[0].isPrerelease else true end')"
  bounded_pilot_present="$(printf '%s\n' "$releases" | jq -r --arg tag "$EXPECTED_AGENT_TAG" 'any(.[]; .tagName == $tag)')"
  is_immutable="$(printf '%s\n' "$releases" | jq -r --arg tag "$EXPECTED_AGENT_TAG" 'map(select(.tagName == $tag)) as $m | if ($m|length) > 0 then $m[0].isImmutable else false end')"

  if [ "$bounded_pilot_present" = "true" ] && [ "$is_draft" = "false" ] && [ "$is_prerelease" = "false" ]; then
    print_check 'GITHUB_BOUNDED_PILOT_RELEASE_PRESENT' 'pass' "tag=$EXPECTED_AGENT_TAG draft=$is_draft prerelease=$is_prerelease"
  else
    print_check 'GITHUB_BOUNDED_PILOT_RELEASE_PRESENT' 'blocked' "tag=$EXPECTED_AGENT_TAG present=$bounded_pilot_present draft=$is_draft prerelease=$is_prerelease"
    blocked=1
  fi

  if [ "$is_immutable" = "true" ]; then
    print_check 'GITHUB_RELEASE_IMMUTABLE' 'pass' "tag=$EXPECTED_AGENT_TAG"
  else
    print_check 'GITHUB_RELEASE_IMMUTABLE' 'needs_hygiene' "tag=$EXPECTED_AGENT_TAG isImmutable=$is_immutable"
    needs_hygiene=1
    waiver_findings+=('GITHUB_RELEASE_IMMUTABLE')
  fi

  local tag_ref tag_object tag_commit
  if tag_ref="$(gh api "repos/${AGENT_REPO}/git/ref/tags/${EXPECTED_AGENT_TAG}" 2>&1)" \
    && tag_object="$(printf '%s\n' "$tag_ref" | jq -r '.object.sha')" \
    && tag_commit="$(gh api "repos/${AGENT_REPO}/git/tags/${tag_object}" --jq .object.sha 2>&1)"; then
    if [ "$tag_commit" = "$EXPECTED_AGENT_COMMIT" ]; then
      print_check 'GITHUB_TAG_SOURCE_COMMIT' 'pass' "tag=$EXPECTED_AGENT_TAG commit=$tag_commit"
    else
      print_check 'GITHUB_TAG_SOURCE_COMMIT' 'blocked' "tag=$EXPECTED_AGENT_TAG commit=$tag_commit expected=$EXPECTED_AGENT_COMMIT"
      blocked=1
    fi
  else
    print_check 'GITHUB_TAG_SOURCE_COMMIT' 'blocked' "reason=$(printf '%q' "${tag_ref:-tag-read-failed}")"
    blocked=1
  fi

  local release_manifest current_manifest release_sums current_sums release_zip_sha current_zip_sha
  if ! release_manifest="$(fetch_url "${GITHUB_RELEASE_BASE_URL}/release-manifest.json" 2>&1)"; then
    print_check 'RELEASE_MANIFEST_FETCH' 'blocked' "reason=$(printf '%q' "$release_manifest")"
    blocked=1
    release_manifest='{}'
  fi
  if ! current_manifest="$(fetch_url "${ARTIFACT_BASE_URL}/release-manifest.json" 2>&1)"; then
    print_check 'CURRENT_MANIFEST_FETCH' 'blocked' "reason=$(printf '%q' "$current_manifest")"
    blocked=1
    current_manifest='{}'
  fi
  if ! release_sums="$(fetch_url "${GITHUB_RELEASE_BASE_URL}/SHA256SUMS" 2>&1)"; then
    print_check 'RELEASE_SHA256SUMS_FETCH' 'blocked' "reason=$(printf '%q' "$release_sums")"
    blocked=1
    release_sums=''
  fi
  if ! current_sums="$(fetch_url "${ARTIFACT_BASE_URL}/SHA256SUMS" 2>&1)"; then
    print_check 'CURRENT_SHA256SUMS_FETCH' 'blocked' "reason=$(printf '%q' "$current_sums")"
    blocked=1
    current_sums=''
  fi

  local rel_tag cur_tag rel_workflow_run cur_workflow_run rel_previous_release cur_previous_release rel_agent_sha cur_agent_sha rel_zip_sha cur_zip_manifest_sha rel_signer cur_signer rel_tier cur_tier rel_ah_ref cur_ah_ref
  rel_tag="$(printf '%s\n' "$release_manifest" | jq -r '.release_tag // ""')"
  cur_tag="$(printf '%s\n' "$current_manifest" | jq -r '.release_tag // ""')"
  rel_workflow_run="$(printf '%s\n' "$release_manifest" | jq -r '.workflow_run_id // ""')"
  cur_workflow_run="$(printf '%s\n' "$current_manifest" | jq -r '.workflow_run_id // ""')"
  rel_previous_release="$(printf '%s\n' "$release_manifest" | jq -r '.previous_release // ""')"
  cur_previous_release="$(printf '%s\n' "$current_manifest" | jq -r '.previous_release // ""')"
  rel_agent_sha="$(printf '%s\n' "$release_manifest" | jq -r '.endpoint_agent_sha256 // ""')"
  cur_agent_sha="$(printf '%s\n' "$current_manifest" | jq -r '.endpoint_agent_sha256 // ""')"
  rel_zip_sha="$(printf '%s\n' "$release_manifest" | jq -r '.endpoint_agent_zip_sha256 // ""')"
  cur_zip_manifest_sha="$(printf '%s\n' "$current_manifest" | jq -r '.endpoint_agent_zip_sha256 // ""')"
  rel_signer="$(printf '%s\n' "$release_manifest" | jq -r '.signer_thumbprint // ""')"
  cur_signer="$(printf '%s\n' "$current_manifest" | jq -r '.signer_thumbprint // ""')"
  rel_tier="$(printf '%s\n' "$release_manifest" | jq -r '.signing_tier // ""')"
  cur_tier="$(printf '%s\n' "$current_manifest" | jq -r '.signing_tier // ""')"
  rel_ah_ref="$(printf '%s\n' "$release_manifest" | jq -r '.artifact_host_image_ref // ""')"
  cur_ah_ref="$(printf '%s\n' "$current_manifest" | jq -r '.artifact_host_image_ref // ""')"

  if [ "$rel_tag" = "$EXPECTED_AGENT_TAG" ] && [ "$cur_tag" = "$EXPECTED_AGENT_TAG" ]; then
    print_check 'MANIFEST_RELEASE_TAG_PARITY' 'pass' "release=$rel_tag current=$cur_tag"
  else
    print_check 'MANIFEST_RELEASE_TAG_PARITY' 'blocked' "release=$rel_tag current=$cur_tag expected=$EXPECTED_AGENT_TAG"
    blocked=1
  fi

  if [ "$rel_workflow_run" = "$EXPECTED_RELEASE_WORKFLOW_RUN_ID" ] \
    && [ "$cur_workflow_run" = "$EXPECTED_RELEASE_WORKFLOW_RUN_ID" ]; then
    print_check 'MANIFEST_WORKFLOW_RUN_PARITY' 'pass' "workflow_run_id=$rel_workflow_run"
  else
    print_check 'MANIFEST_WORKFLOW_RUN_PARITY' 'blocked' "release=$rel_workflow_run current=$cur_workflow_run expected=$EXPECTED_RELEASE_WORKFLOW_RUN_ID"
    blocked=1
  fi

  if [ "$rel_previous_release" = "$EXPECTED_PREVIOUS_RELEASE" ] \
    && [ "$cur_previous_release" = "$EXPECTED_PREVIOUS_RELEASE" ]; then
    print_check 'MANIFEST_PREVIOUS_RELEASE_PARITY' 'pass' "previous_release=$rel_previous_release"
  else
    print_check 'MANIFEST_PREVIOUS_RELEASE_PARITY' 'blocked' "release=$rel_previous_release current=$cur_previous_release expected=$EXPECTED_PREVIOUS_RELEASE"
    blocked=1
  fi

  if [ -n "$rel_agent_sha" ] && [ "$rel_agent_sha" = "$cur_agent_sha" ]; then
    print_check 'MANIFEST_AGENT_SHA_PARITY' 'pass' "sha256=$rel_agent_sha"
  else
    print_check 'MANIFEST_AGENT_SHA_PARITY' 'blocked' "release=$rel_agent_sha current=$cur_agent_sha"
    blocked=1
  fi

  if [ -n "$rel_zip_sha" ] && [ "$rel_zip_sha" = "$cur_zip_manifest_sha" ]; then
    print_check 'MANIFEST_ZIP_SHA_PARITY' 'pass' "sha256=$rel_zip_sha"
  else
    print_check 'MANIFEST_ZIP_SHA_PARITY' 'blocked' "release=$rel_zip_sha current=$cur_zip_manifest_sha"
    blocked=1
  fi

  if [ "$rel_signer" = "$EXPECTED_SIGNER_THUMBPRINT" ] && [ "$cur_signer" = "$EXPECTED_SIGNER_THUMBPRINT" ] \
    && [ "$rel_tier" = "$EXPECTED_SIGNING_TIER" ] && [ "$cur_tier" = "$EXPECTED_SIGNING_TIER" ]; then
    print_check 'MANIFEST_SIGNING_PARITY' 'pass' "thumbprint=$rel_signer tier=$rel_tier"
  else
    print_check 'MANIFEST_SIGNING_PARITY' 'blocked' "release_thumbprint=$rel_signer current_thumbprint=$cur_signer release_tier=$rel_tier current_tier=$cur_tier"
    blocked=1
  fi

  if printf '%s\n' "$rel_ah_ref" | grep -q "$EXPECTED_ARTIFACT_HOST_DIGEST"; then
    print_check 'RELEASE_MANIFEST_ARTIFACT_HOST_DIGEST' 'pass' "ref=$rel_ah_ref"
  else
    print_check 'RELEASE_MANIFEST_ARTIFACT_HOST_DIGEST' 'blocked' "ref=${rel_ah_ref:-missing} expected_digest=$EXPECTED_ARTIFACT_HOST_DIGEST"
    blocked=1
  fi

  if [ -z "$cur_ah_ref" ]; then
    print_check 'CURRENT_MANIFEST_ARTIFACT_HOST_DIGEST' 'not_required' "ref=missing reason=self-referential-image-digest release_manifest_ref=$rel_ah_ref"
  elif printf '%s\n' "$cur_ah_ref" | grep -q "$EXPECTED_ARTIFACT_HOST_DIGEST"; then
    print_check 'CURRENT_MANIFEST_ARTIFACT_HOST_DIGEST' 'pass' "ref=$cur_ah_ref"
  else
    print_check 'CURRENT_MANIFEST_ARTIFACT_HOST_DIGEST' 'needs_hygiene' "ref=${cur_ah_ref:-missing} expected_digest=$EXPECTED_ARTIFACT_HOST_DIGEST"
    needs_hygiene=1
    nonwaiver_hygiene=1
  fi

  local release_zip_sha_raw current_zip_sha_raw
  if ! release_zip_sha_raw="$(fetch_url "${GITHUB_RELEASE_BASE_URL}/EndpointAgent.zip.sha256" 2>&1)"; then
    print_check 'RELEASE_ZIP_SHA256_FILE_FETCH' 'blocked' "reason=$(printf '%q' "$release_zip_sha_raw")"
    blocked=1
    release_zip_sha_raw=''
  fi
  if ! current_zip_sha_raw="$(fetch_url "${ARTIFACT_BASE_URL}/EndpointAgent.zip.sha256" 2>&1)"; then
    print_check 'CURRENT_ZIP_SHA256_FILE_FETCH' 'blocked' "reason=$(printf '%q' "$current_zip_sha_raw")"
    blocked=1
    current_zip_sha_raw=''
  fi
  release_zip_sha="$(printf '%s\n' "$release_zip_sha_raw" | awk '{print $1}')"
  current_zip_sha="$(printf '%s\n' "$current_zip_sha_raw" | awk '{print $1}')"
  if [ "$release_zip_sha" = "$rel_zip_sha" ] && [ "$current_zip_sha" = "$rel_zip_sha" ]; then
    print_check 'ZIP_SHA256_FILE_PARITY' 'pass' "sha256=$rel_zip_sha"
  else
    print_check 'ZIP_SHA256_FILE_PARITY' 'blocked' "release_file=$release_zip_sha current_file=$current_zip_sha manifest=$rel_zip_sha"
    blocked=1
  fi

  local required_names=(endpoint-agent.exe bootstrap-package.ps1 install.ps1 uninstall.ps1 EndpointAgent.zip EndpointAgent.zip.sha256 release-manifest.json)
  local missing_release=() missing_current=()
  local asset
  for asset in "${required_names[@]}"; do
    if ! sha_from_sums "$asset" "$release_sums" >/dev/null 2>&1; then
      missing_release+=("$asset")
    fi
    if ! sha_from_sums "$asset" "$current_sums" >/dev/null 2>&1; then
      missing_current+=("$asset")
    fi
  done
  if [ "${#missing_current[@]}" -eq 0 ]; then
    print_check 'CURRENT_SHA256SUMS_COVERAGE' 'pass' "assets=${#required_names[@]}"
  else
    print_check 'CURRENT_SHA256SUMS_COVERAGE' 'blocked' "missing=${missing_current[*]}"
    blocked=1
  fi
  if [ "${#missing_release[@]}" -eq 0 ]; then
    print_check 'RELEASE_SHA256SUMS_COVERAGE' 'pass' "assets=${#required_names[@]}"
  else
    print_check 'RELEASE_SHA256SUMS_COVERAGE' 'needs_hygiene' "missing=${missing_release[*]}"
    needs_hygiene=1
    nonwaiver_hygiene=1
  fi

  local live q_context q_namespace digest_hits effective_mode
  case "$RELEASE_LINEAGE_KUBECTL_MODE" in
    local|local-kubectl) effective_mode="local-kubectl" ;;
    ssh) effective_mode="ssh" ;;
    *)
      print_check 'ARTIFACT_HOST_LIVE_DIGEST' 'blocked' "mode=$(printf '%q' "$RELEASE_LINEAGE_KUBECTL_MODE") reason=invalid-release-lineage-kubectl-mode"
      blocked=1
      effective_mode="$RELEASE_LINEAGE_KUBECTL_MODE"
      ;;
  esac
  if [ "$SSH_TARGET" = "local" ]; then
    effective_mode="local-kubectl"
  fi

  if [ -z "$KUBE_CONTEXT" ]; then
    print_check 'ARTIFACT_HOST_LIVE_DIGEST' 'blocked' "mode=$effective_mode reason=empty-kube-context"
    blocked=1
  elif [ -z "$KUBE_NAMESPACE" ]; then
    print_check 'ARTIFACT_HOST_LIVE_DIGEST' 'blocked' "mode=$effective_mode reason=empty-kube-namespace"
    blocked=1
  elif [ "$effective_mode" = "local-kubectl" ]; then
    if ! command -v kubectl >/dev/null 2>&1; then
      print_check 'ARTIFACT_HOST_LIVE_DIGEST' 'blocked' "mode=$effective_mode reason=missing-kubectl"
      blocked=1
    elif live="$(artifact_host_kubectl_output 2>&1)"; then
      printf 'ARTIFACT_HOST_LIVE_OUTPUT_BEGIN\n%s\nARTIFACT_HOST_LIVE_OUTPUT_END\n' "$live"
      digest_hits="$(printf '%s\n' "$live" | grep -c "$EXPECTED_ARTIFACT_HOST_DIGEST" || true)"
      if [ "$digest_hits" -ge "$MIN_ARTIFACT_HOST_DIGEST_HITS" ]; then
        print_check 'ARTIFACT_HOST_LIVE_DIGEST' 'pass' "mode=$effective_mode expected_digest=$EXPECTED_ARTIFACT_HOST_DIGEST digest_hits=$digest_hits"
      else
        print_check 'ARTIFACT_HOST_LIVE_DIGEST' 'blocked' "mode=$effective_mode expected_digest=$EXPECTED_ARTIFACT_HOST_DIGEST digest_hits=$digest_hits min_hits=$MIN_ARTIFACT_HOST_DIGEST_HITS"
        blocked=1
      fi
    else
      print_check 'ARTIFACT_HOST_LIVE_DIGEST' 'blocked' "mode=$effective_mode reason=$(printf '%q' "$live")"
      blocked=1
    fi
  else
    need ssh
    q_context="$(shell_quote "$KUBE_CONTEXT")"
    q_namespace="$(shell_quote "$KUBE_NAMESPACE")"
    # shellcheck disable=SC2029 # q_context/q_namespace are shell-escaped locally and intentionally expanded before ssh.
    if live="$(ssh_cmd "$SSH_TARGET" "kubectl --context $q_context -n $q_namespace get deploy artifact-host -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,UPDATED:.status.updatedReplicas,IMAGE:.spec.template.spec.containers[0].image && kubectl --context $q_context -n $q_namespace get pod -l app.kubernetes.io/name=artifact-host -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,IMAGEID:.status.containerStatuses[0].imageID" 2>&1)"; then
      printf 'ARTIFACT_HOST_LIVE_OUTPUT_BEGIN\n%s\nARTIFACT_HOST_LIVE_OUTPUT_END\n' "$live"
      digest_hits="$(printf '%s\n' "$live" | grep -c "$EXPECTED_ARTIFACT_HOST_DIGEST" || true)"
      if [ "$digest_hits" -ge "$MIN_ARTIFACT_HOST_DIGEST_HITS" ]; then
        print_check 'ARTIFACT_HOST_LIVE_DIGEST' 'pass' "mode=$effective_mode expected_digest=$EXPECTED_ARTIFACT_HOST_DIGEST digest_hits=$digest_hits"
      else
        print_check 'ARTIFACT_HOST_LIVE_DIGEST' 'blocked' "mode=$effective_mode expected_digest=$EXPECTED_ARTIFACT_HOST_DIGEST digest_hits=$digest_hits min_hits=$MIN_ARTIFACT_HOST_DIGEST_HITS"
        blocked=1
      fi
    else
      print_check 'ARTIFACT_HOST_LIVE_DIGEST' 'blocked' "mode=$effective_mode reason=$(printf '%q' "$live")"
      blocked=1
    fi
  fi

  if [ "$blocked" -ne 0 ]; then
    printf 'F22_6_RELEASE_LINEAGE=blocked\n'
  elif [ "$needs_hygiene" -ne 0 ]; then
    if [ "$nonwaiver_hygiene" -eq 0 ] && [ "${#waiver_findings[@]}" -gt 0 ]; then
      local required_findings
      required_findings="$(IFS=,; printf '%s' "${waiver_findings[*]}")"
      if check_release_lineage_waiver "$required_findings"; then
        printf 'F22_6_RELEASE_LINEAGE=bounded_pilot_pass\n'
      else
        printf 'F22_6_RELEASE_LINEAGE=needs_hygiene\n'
      fi
    else
      if [ "$nonwaiver_hygiene" -ne 0 ]; then
        print_check 'RELEASE_LINEAGE_WAIVER' 'not_applicable' 'reason=nonwaiver-hygiene-present'
      fi
      printf 'F22_6_RELEASE_LINEAGE=needs_hygiene\n'
    fi
  else
    print_check 'RELEASE_LINEAGE_WAIVER' 'not_required' 'reason=no-release-lineage-hygiene'
    printf 'F22_6_RELEASE_LINEAGE=pass\n'
  fi
}

if [ "${F22_6_RELEASE_LINEAGE_AUDIT_SOURCE_ONLY:-0}" != "1" ]; then
  main "$@"
fi
