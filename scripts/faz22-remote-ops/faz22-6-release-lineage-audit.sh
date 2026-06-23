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
ARTIFACT_BASE_URL="${ARTIFACT_BASE_URL:-https://testai.acik.com/artifacts/endpoint-agent/current}"
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

main() {
  need gh
  need jq
  need curl
  need awk
  need grep
  need ssh

  local blocked=0
  local needs_hygiene=0

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
  fi

  if [ "$recent_count" -gt "$RECENT_RELEASE_HYGIENE_THRESHOLD" ]; then
    print_check 'GITHUB_RELEASE_DENSE_TRAIN' 'needs_hygiene' "recent_v0_2_count=$recent_count threshold=$RECENT_RELEASE_HYGIENE_THRESHOLD"
    needs_hygiene=1
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
  if ! release_manifest="$(curl -fsSL "${GITHUB_RELEASE_BASE_URL}/release-manifest.json" 2>&1)"; then
    print_check 'RELEASE_MANIFEST_FETCH' 'blocked' "reason=$(printf '%q' "$release_manifest")"
    blocked=1
    release_manifest='{}'
  fi
  if ! current_manifest="$(curl -fsSL "${ARTIFACT_BASE_URL}/release-manifest.json" 2>&1)"; then
    print_check 'CURRENT_MANIFEST_FETCH' 'blocked' "reason=$(printf '%q' "$current_manifest")"
    blocked=1
    current_manifest='{}'
  fi
  if ! release_sums="$(curl -fsSL "${GITHUB_RELEASE_BASE_URL}/SHA256SUMS" 2>&1)"; then
    print_check 'RELEASE_SHA256SUMS_FETCH' 'blocked' "reason=$(printf '%q' "$release_sums")"
    blocked=1
    release_sums=''
  fi
  if ! current_sums="$(curl -fsSL "${ARTIFACT_BASE_URL}/SHA256SUMS" 2>&1)"; then
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
  fi

  local release_zip_sha_raw current_zip_sha_raw
  if ! release_zip_sha_raw="$(curl -fsSL "${GITHUB_RELEASE_BASE_URL}/EndpointAgent.zip.sha256" 2>&1)"; then
    print_check 'RELEASE_ZIP_SHA256_FILE_FETCH' 'blocked' "reason=$(printf '%q' "$release_zip_sha_raw")"
    blocked=1
    release_zip_sha_raw=''
  fi
  if ! current_zip_sha_raw="$(curl -fsSL "${ARTIFACT_BASE_URL}/EndpointAgent.zip.sha256" 2>&1)"; then
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
    printf 'F22_6_RELEASE_LINEAGE=needs_hygiene\n'
  else
    printf 'F22_6_RELEASE_LINEAGE=pass\n'
  fi
}

main "$@"
