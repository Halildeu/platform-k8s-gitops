#!/usr/bin/env bash
# Conservative Faz 22.6 EndpointAgent release-lineage audit.
#
# This helper is read-only. It validates the published GitHub release, the
# test artifact-host "current" surface, and the live artifact-host deployment
# before broad rollout language can be used for the rapid v0.2.x line.

set -euo pipefail

AGENT_REPO="${AGENT_REPO:-Halildeu/platform-agent}"
SSH_TARGET="${SSH_TARGET:-staging-sw}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
EXPECTED_AGENT_TAG="${EXPECTED_AGENT_TAG:-v0.2.28}"
EXPECTED_AGENT_COMMIT="${EXPECTED_AGENT_COMMIT:-10361a60ca8ca1fb4c6efe3823b433297e16ae3a}"
EXPECTED_SIGNER_THUMBPRINT="${EXPECTED_SIGNER_THUMBPRINT:-D68F4F530137EB65CE44E3405E82B46205E753E5}"
EXPECTED_SIGNING_TIER="${EXPECTED_SIGNING_TIER:-trusted-internal-ca}"
EXPECTED_ARTIFACT_HOST_DIGEST="${EXPECTED_ARTIFACT_HOST_DIGEST:-sha256:36a81cb89294ef7f4d09350ab9f92a955b65b8132ba5330fcf1dcb7e365ab3e2}"
RECENT_RELEASE_WINDOW="${RECENT_RELEASE_WINDOW:-50}"
RECENT_RELEASE_HYGIENE_THRESHOLD="${RECENT_RELEASE_HYGIENE_THRESHOLD:-5}"
MIN_ARTIFACT_HOST_DIGEST_HITS="${MIN_ARTIFACT_HOST_DIGEST_HITS:-2}"
CURL_MAX_TIME="${CURL_MAX_TIME:-20}"
ARTIFACT_BASE_URL="${ARTIFACT_BASE_URL:-https://testai.acik.com/artifacts/endpoint-agent/current}"
GITHUB_RELEASE_BASE_URL="${GITHUB_RELEASE_BASE_URL:-https://github.com/${AGENT_REPO}/releases/download/${EXPECTED_AGENT_TAG}}"
RELEASE_LINEAGE_WAIVER_REF="${RELEASE_LINEAGE_WAIVER_REF:-Halildeu/platform-k8s-gitops#1901}"
RELEASE_LINEAGE_WAIVER_FORBIDDEN_CLAIMS="${RELEASE_LINEAGE_WAIVER_FORBIDDEN_CLAIMS:-5-device,50-device,800-device,production,broad-rollout}"

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

fetch_url() {
  # fetch_url <url>
  # Keep the audit bounded and avoid stale CDN bytes after metadata-only release repairs.
  curl --max-time "$CURL_MAX_TIME" -fsSL -H 'Cache-Control: no-cache' "$1"
}

waiver_field() {
  # waiver_field <key> <issue-body>
  local key="$1"
  sed -n "s/^${key}:[[:space:]]*//p" | head -1
}

check_release_lineage_waiver() {
  # check_release_lineage_waiver <comma-separated-required-findings>
  local required_findings="$1"
  local ref="$RELEASE_LINEAGE_WAIVER_REF"
  local repo_ref number issue_json state body today
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

  marker="$(printf '%s\n' "$body" | waiver_field 'F22_6_RELEASE_LINEAGE_WAIVER')"
  scope="$(printf '%s\n' "$body" | waiver_field 'waiver_scope')"
  release_tag="$(printf '%s\n' "$body" | waiver_field 'release_tag')"
  digest="$(printf '%s\n' "$body" | waiver_field 'artifact_host_digest')"
  accepted_findings="$(printf '%s\n' "$body" | waiver_field 'accepted_findings')"
  forbidden_claims="$(printf '%s\n' "$body" | waiver_field 'forbidden_claims')"
  owner="$(printf '%s\n' "$body" | waiver_field 'owner_approved_by')"
  approved_at="$(printf '%s\n' "$body" | waiver_field 'approved_at')"
  expires_at="$(printf '%s\n' "$body" | waiver_field 'expires_at')"

  [ "$marker" = "v1" ] || missing+=("marker")
  [ "$scope" = "bounded-pilot-only" ] || missing+=("scope")
  [ "$release_tag" = "$EXPECTED_AGENT_TAG" ] || missing+=("release_tag")
  [ "$digest" = "$EXPECTED_ARTIFACT_HOST_DIGEST" ] || missing+=("artifact_host_digest")
  local owner_lc
  owner_lc="$(printf '%s' "$owner" | tr '[:upper:]' '[:lower:]')"
  if [ -z "$owner" ]; then
    missing+=("owner_approved_by")
  fi
  case "$owner_lc" in
    tbd|none|n/a) missing+=("owner_approved_by") ;;
  esac

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

  if ! [[ "$approved_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    missing+=("approved_at")
  fi
  if ! [[ "$expires_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    missing+=("expires_at")
  fi
  today="$(date -u +%Y-%m-%d 2>/dev/null || true)"
  if ! [[ "$today" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    missing+=("today-unparseable")
  else
    if [[ "$approved_at" > "$today" ]]; then
      missing+=("approved_at-in-future")
    fi
    if [[ "$expires_at" < "$today" ]]; then
      missing+=("expires_at-expired")
    fi
  fi

  if [ "${#missing[@]}" -ne 0 ]; then
    local reason
    reason="$(IFS=,; printf '%s' "${missing[*]}")"
    print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref reason=$reason"
    return 1
  fi

  print_check 'RELEASE_LINEAGE_WAIVER' 'bounded_pilot_pass' "ref=$ref owner=$owner expires_at=$expires_at accepted_findings=$(printf '%q' "$accepted_findings")"
  return 0
}

main() {
  need gh
  need jq
  need curl
  need awk
  need grep
  need ssh

  local blocked=0
  local needs_hygiene=0
  local nonwaiver_hygiene=0
  local waiver_findings=()

  printf 'F22_6_RELEASE_LINEAGE_SCOPE=endpoint-agent-release-hygiene\n'
  printf 'F22_6_RELEASE_LINEAGE_RUNBOOK=docs/runbooks/RB-faz22.6-release-lineage-audit.md\n'

  local releases latest is_latest is_draft is_prerelease is_immutable recent_count
  if ! releases="$(gh release list -R "$AGENT_REPO" --limit "$RECENT_RELEASE_WINDOW" \
      --json tagName,isLatest,isDraft,isPrerelease,isImmutable,publishedAt,name 2>&1)"; then
    print_check 'GITHUB_RELEASE_LIST' 'blocked' "reason=$(printf '%q' "$releases")"
    blocked=1
    releases='[]'
  fi

  latest="$(printf '%s\n' "$releases" | jq -r '(map(select(.isLatest))[0].tagName // .[0].tagName // "unknown")')"
  is_latest="$(printf '%s\n' "$releases" | jq -r --arg tag "$EXPECTED_AGENT_TAG" 'map(select(.tagName == $tag)) as $m | if ($m|length) > 0 then $m[0].isLatest else false end')"
  is_draft="$(printf '%s\n' "$releases" | jq -r --arg tag "$EXPECTED_AGENT_TAG" 'map(select(.tagName == $tag)) as $m | if ($m|length) > 0 then $m[0].isDraft else true end')"
  is_prerelease="$(printf '%s\n' "$releases" | jq -r --arg tag "$EXPECTED_AGENT_TAG" 'map(select(.tagName == $tag)) as $m | if ($m|length) > 0 then $m[0].isPrerelease else true end')"
  is_immutable="$(printf '%s\n' "$releases" | jq -r --arg tag "$EXPECTED_AGENT_TAG" 'map(select(.tagName == $tag)) as $m | if ($m|length) > 0 then $m[0].isImmutable else false end')"
  recent_count="$(printf '%s\n' "$releases" | jq '[.[].tagName | select(test("^v0\\.2\\."))] | length')"

  if [ "$latest" = "$EXPECTED_AGENT_TAG" ] && [ "$is_latest" = "true" ] \
    && [ "$is_draft" = "false" ] && [ "$is_prerelease" = "false" ]; then
    print_check 'GITHUB_RELEASE_LATEST' 'pass' "tag=$latest draft=$is_draft prerelease=$is_prerelease"
  else
    print_check 'GITHUB_RELEASE_LATEST' 'blocked' "latest=$latest expected=$EXPECTED_AGENT_TAG isLatest=$is_latest draft=$is_draft prerelease=$is_prerelease"
    blocked=1
  fi

  if [ "$is_immutable" = "true" ]; then
    print_check 'GITHUB_RELEASE_IMMUTABLE' 'pass' "tag=$EXPECTED_AGENT_TAG"
  else
    print_check 'GITHUB_RELEASE_IMMUTABLE' 'needs_hygiene' "tag=$EXPECTED_AGENT_TAG isImmutable=$is_immutable"
    needs_hygiene=1
    waiver_findings+=('GITHUB_RELEASE_IMMUTABLE')
  fi

  if [ "$recent_count" -gt "$RECENT_RELEASE_HYGIENE_THRESHOLD" ]; then
    print_check 'GITHUB_RELEASE_DENSE_TRAIN' 'needs_hygiene' "recent_v0_2_count=$recent_count threshold=$RECENT_RELEASE_HYGIENE_THRESHOLD"
    needs_hygiene=1
    waiver_findings+=('GITHUB_RELEASE_DENSE_TRAIN')
  else
    print_check 'GITHUB_RELEASE_DENSE_TRAIN' 'pass' "recent_v0_2_count=$recent_count"
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

  local rel_tag cur_tag rel_agent_sha cur_agent_sha rel_zip_sha cur_zip_manifest_sha rel_signer cur_signer rel_tier cur_tier rel_ah_ref cur_ah_ref
  rel_tag="$(printf '%s\n' "$release_manifest" | jq -r '.release_tag // ""')"
  cur_tag="$(printf '%s\n' "$current_manifest" | jq -r '.release_tag // ""')"
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

  local live q_context q_namespace digest_hits
  q_context="$(shell_quote "$KUBE_CONTEXT")"
  q_namespace="$(shell_quote "$KUBE_NAMESPACE")"
  # shellcheck disable=SC2029 # q_context/q_namespace are shell-escaped locally and intentionally expanded before ssh.
  if live="$(ssh "$SSH_TARGET" "kubectl --context $q_context -n $q_namespace get deploy artifact-host -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,UPDATED:.status.updatedReplicas,IMAGE:.spec.template.spec.containers[0].image && kubectl --context $q_context -n $q_namespace get pod -l app.kubernetes.io/name=artifact-host -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,IMAGEID:.status.containerStatuses[0].imageID" 2>&1)"; then
    printf 'ARTIFACT_HOST_LIVE_OUTPUT_BEGIN\n%s\nARTIFACT_HOST_LIVE_OUTPUT_END\n' "$live"
    digest_hits="$(printf '%s\n' "$live" | grep -c "$EXPECTED_ARTIFACT_HOST_DIGEST" || true)"
    if [ "$digest_hits" -ge "$MIN_ARTIFACT_HOST_DIGEST_HITS" ]; then
      print_check 'ARTIFACT_HOST_LIVE_DIGEST' 'pass' "expected_digest=$EXPECTED_ARTIFACT_HOST_DIGEST digest_hits=$digest_hits"
    else
      print_check 'ARTIFACT_HOST_LIVE_DIGEST' 'blocked' "expected_digest=$EXPECTED_ARTIFACT_HOST_DIGEST digest_hits=$digest_hits min_hits=$MIN_ARTIFACT_HOST_DIGEST_HITS"
      blocked=1
    fi
  else
    print_check 'ARTIFACT_HOST_LIVE_DIGEST' 'blocked' "reason=$(printf '%q' "$live")"
    blocked=1
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

main "$@"
