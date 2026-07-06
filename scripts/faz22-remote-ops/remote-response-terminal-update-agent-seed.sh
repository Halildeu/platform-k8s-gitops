#!/usr/bin/env bash
set -euo pipefail

# Faz 22.6.3 EndpointAgent release-catalog seed helper.
#
# This helper prepares or executes the approved EndpointAgent release-catalog
# path that unblocks platform-agent#208 runtime smoke. It never talks directly
# to the endpoint, never inserts DB rows, never uses Software Catalog or
# Approved Script Runner as an installer, and never opens a shell/RDP/WinRM/SMB
# path. Live API mutations require LIVE_MUTATION=1 plus explicit RUN_* flags.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
# shellcheck source=scripts/faz22-remote-ops/endpoint-agent-release-policy.sh
source "${SCRIPT_DIR}/endpoint-agent-release-policy.sh"
endpoint_agent_release_policy_load "$REPO_ROOT"

API_BASE="${ENDPOINT_ADMIN_API_BASE:-https://testai.acik.com/api/v1/endpoint-admin}"
EVIDENCE_DIR="${EVIDENCE_DIR:-/tmp/remote-response-terminal-update-agent-seed-$(date -u +%Y%m%dT%H%M%SZ)}"

RELEASE_ID="${RELEASE_ID:-$EXPECTED_AGENT_TAG}"
CHANNEL="${CHANNEL:-PILOT}"
TARGET_VERSION="${TARGET_VERSION:-$EXPECTED_AGENT_VERSION}"
BINARY_URL="${BINARY_URL:-$GITHUB_RELEASE_BASE_URL/endpoint-agent.exe}"
MANIFEST_URL="${MANIFEST_URL:-$GITHUB_RELEASE_BASE_URL/release-manifest.json}"
EXPECTED_SHA256="${EXPECTED_SHA256:-$EXPECTED_AGENT_SHA256}"
: "${EXPECTED_SIGNER_THUMBPRINT:?missing expected signer thumbprint}"
SIGNING_TIER="${SIGNING_TIER:-TRUSTED_SIGNED}"
MAX_BYTES="${MAX_BYTES:-$EXPECTED_AGENT_MAX_BYTES}"
RELEASE_NOTES="${RELEASE_NOTES:-Faz 22.6.3 constrained-terminal pilot seed for platform-agent#208; source artifact ${RELEASE_ID} ${EXPECTED_SIGNING_TIER}.}"

TARGET_DEVICE_ID="${TARGET_DEVICE_ID:-d0efb00a-681a-4e32-b7de-a27ef94f2977}"
TARGET_DEVICE_HOSTNAME="${TARGET_DEVICE_HOSTNAME:-HALILKOOLUB735}"
DISPATCH_REASON="${DISPATCH_REASON:-Faz 22.6.3 constrained-terminal pilot seed for platform-agent#208 via approved release catalog}"
DISPATCH_IDEMPOTENCY_KEY="${DISPATCH_IDEMPOTENCY_KEY:-rtt-v0210-$(date -u +%Y%m%d%H%M%S)}"
REQUIRED_DEPLOYMENT_RING="${REQUIRED_DEPLOYMENT_RING:-}"
DISPATCH_NOT_BEFORE="${DISPATCH_NOT_BEFORE:-}"
DISPATCH_EXPIRES_AT="${DISPATCH_EXPIRES_AT:-}"

LIVE_MUTATION="${LIVE_MUTATION:-0}"
RUN_CREATE="${RUN_CREATE:-0}"
RUN_APPROVE="${RUN_APPROVE:-0}"
RUN_NEGATIVE_DISPATCH="${RUN_NEGATIVE_DISPATCH:-0}"
RUN_DISPATCH="${RUN_DISPATCH:-0}"
VERIFY_BINARY_SHA="${VERIFY_BINARY_SHA:-1}"
CURL_TIMEOUT="${CURL_TIMEOUT_SECONDS:-30}"

CREATOR_TOKEN=""
APPROVER_TOKEN=""
DISPATCH_TOKEN=""
ACTIONS_JSON="[]"

die() {
  printf 'ERR %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

safe_label() {
  printf '%s' "$1" | tr -cs 'A-Za-z0-9_.-' '-'
}

normalize_thumbprint() {
  printf '%s' "$1" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]:'
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

append_action() {
  local name="$1" status="$2" detail="$3"
  ACTIONS_JSON="$(jq -cn \
    --argjson arr "$ACTIONS_JSON" \
    --arg name "$name" \
    --arg status "$status" \
    --arg detail "$detail" \
    '$arr + [{name:$name,status:$status,detail:$detail}]')"
}

read_token() {
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

validate_token_for_curl_config() {
  local token="$1" label="$2"
  [[ -n "$token" ]] || die "$label token is required"
  if [[ "$token" == *$'\n'* || "$token" == *$'\r'* || "$token" == *\"* || "$token" == *\\* ]]; then
    die "$label token contains a character unsafe for curl --config stdin"
  fi
}

curl_request() {
  local method="$1" path="$2" token="$3" label="$4" body="${5:-}" mutation="${6:-0}"
  local safe out req code_file url
  safe="$(safe_label "$label")"
  out="${EVIDENCE_DIR}/${safe}.body"
  req="${EVIDENCE_DIR}/${safe}.request.json"
  code_file="${EVIDENCE_DIR}/${safe}.code"
  url="${API_BASE%/}${path}"

  if [[ "$mutation" == "1" && "$LIVE_MUTATION" != "1" ]]; then
    die "$label is a live mutation; set LIVE_MUTATION=1 explicitly"
  fi

  local args=(
    --silent
    --show-error
    --location
    --max-time "$CURL_TIMEOUT"
    --request "$method"
    --output "$out"
    --write-out '%{http_code}'
    --header 'Content-Type: application/json'
  )

  if [[ -n "$body" ]]; then
    printf '%s' "$body" > "$req"
    args+=(--data-binary "@${req}")
  fi

  if [[ -n "$token" ]]; then
    validate_token_for_curl_config "$token" "$label"
    # Keep the bearer token out of argv and evidence. curl reads the header from
    # stdin; only the redacted JSON request and response body are written.
    if ! printf 'header = "Authorization: Bearer %s"\n' "$token" \
      | curl --config - "${args[@]}" "$url" > "$code_file"; then
      die "curl request failed: ${label} ${method} ${path}"
    fi
  else
    if ! curl "${args[@]}" "$url" > "$code_file"; then
      die "curl request failed: ${label} ${method} ${path}"
    fi
  fi
  tr -d '\r\n[:space:]' < "$code_file"
}

expect_code_set() {
  local actual="$1" allowed="$2" label="$3"
  case ",$allowed," in
    *,"$actual",*) return 0 ;;
  esac
  printf 'ERR %s expected_http_one_of=%s actual_http=%s\n' "$label" "$allowed" "$actual" >&2
  local body
  body="${EVIDENCE_DIR}/$(safe_label "$label").body"
  [[ -f "$body" ]] && sed 's/^/BODY /' "$body" >&2
  exit 1
}

release_payload() {
  jq -n \
    --arg releaseId "$RELEASE_ID" \
    --arg channel "$CHANNEL" \
    --arg targetVersion "$TARGET_VERSION" \
    --arg binaryUrl "$BINARY_URL" \
    --arg manifestUrl "$MANIFEST_URL" \
    --arg sha256 "$EXPECTED_SHA256" \
    --arg signerThumbprint "$(normalize_thumbprint "$EXPECTED_SIGNER_THUMBPRINT")" \
    --arg signingTier "$SIGNING_TIER" \
    --argjson maxBytes "$MAX_BYTES" \
    --arg releaseNotes "$RELEASE_NOTES" \
    '{
      releaseId: $releaseId,
      channel: $channel,
      targetVersion: $targetVersion,
      binaryUrl: $binaryUrl,
      manifestUrl: $manifestUrl,
      sha256: $sha256,
      signerThumbprint: $signerThumbprint,
      signingTier: $signingTier,
      maxBytes: $maxBytes,
      releaseNotes: $releaseNotes
    }'
}

dispatch_payload() {
  jq -n \
    --arg releaseId "$RELEASE_ID" \
    --arg idempotencyKey "$DISPATCH_IDEMPOTENCY_KEY" \
    --arg reason "$DISPATCH_REASON" \
    --arg ring "$REQUIRED_DEPLOYMENT_RING" \
    --arg notBefore "$DISPATCH_NOT_BEFORE" \
    --arg expiresAt "$DISPATCH_EXPIRES_AT" \
    '{
      releaseId: $releaseId,
      idempotencyKey: $idempotencyKey,
      reason: $reason
    }
    + (if $ring == "" then {} else {requiredDeploymentRing:$ring} end)
    + (if $notBefore == "" then {} else {notBefore:$notBefore} end)
    + (if $expiresAt == "" then {} else {expiresAt:$expiresAt} end)'
}

negative_dispatch_payload() {
  dispatch_payload | jq \
    --arg binaryUrl "$BINARY_URL" \
    --arg sha256 "$EXPECTED_SHA256" \
    --arg signerThumbprint "$(normalize_thumbprint "$EXPECTED_SIGNER_THUMBPRINT")" \
    --arg signingTier "$SIGNING_TIER" \
    --arg targetVersion "$TARGET_VERSION" \
    --argjson maxBytes "$MAX_BYTES" \
    '. + {
      binaryUrl: $binaryUrl,
      sha256: $sha256,
      signerThumbprint: $signerThumbprint,
      signingTier: $signingTier,
      targetVersion: $targetVersion,
      maxBytes: $maxBytes
    }'
}

write_plan_files() {
  release_payload > "${EVIDENCE_DIR}/planned-release.request.json"
  dispatch_payload > "${EVIDENCE_DIR}/planned-dispatch.request.json"
  negative_dispatch_payload > "${EVIDENCE_DIR}/planned-negative-dispatch.request.json"
}

validate_release_body_matches_expected() {
  local file="$1" label="$2"
  jq -e \
    --arg releaseId "$RELEASE_ID" \
    --arg channel "$CHANNEL" \
    --arg targetVersion "$TARGET_VERSION" \
    --arg binaryUrl "$BINARY_URL" \
    --arg manifestUrl "$MANIFEST_URL" \
    --arg sha256 "$EXPECTED_SHA256" \
    --arg signerThumbprint "$(normalize_thumbprint "$EXPECTED_SIGNER_THUMBPRINT")" \
    --arg signingTier "$SIGNING_TIER" \
    --argjson maxBytes "$MAX_BYTES" \
    '.releaseId == $releaseId
      and .channel == $channel
      and .targetVersion == $targetVersion
      and .binaryUrl == $binaryUrl
      and (.manifestUrl // "") == $manifestUrl
      and .sha256 == $sha256
      and ((.signerThumbprint // "" | ascii_upcase) == $signerThumbprint)
      and .signingTier == $signingTier
      and .maxBytes == $maxBytes' \
    "$file" >/dev/null || {
      printf 'ERR %s release body does not match expected immutable metadata\n' "$label" >&2
      sed 's/^/BODY /' "$file" >&2 || true
      exit 1
    }
}

verify_artifacts() {
  local manifest_file headers_file tmp_bin actual_sha
  manifest_file="${EVIDENCE_DIR}/release-manifest.json"
  headers_file="${EVIDENCE_DIR}/binary-url.headers"

  curl -fsSL --max-time "$CURL_TIMEOUT" "$MANIFEST_URL" -o "$manifest_file"
  jq -e \
    --arg tag "$RELEASE_ID" \
    --arg sha "$EXPECTED_SHA256" \
    --arg thumb "$(normalize_thumbprint "$EXPECTED_SIGNER_THUMBPRINT")" \
    '(.release_tag == $tag or .release_tag == ($tag | ltrimstr("v")))
      and (.endpoint_agent_sha256 == $sha)
      and ((.signer_thumbprint // "" | ascii_upcase) == $thumb)
      and any(.assets[]?; .name == "endpoint-agent.exe" and .sha256 == $sha)' \
    "$manifest_file" >/dev/null || die "release manifest does not match expected EndpointAgent artifact"

  local raw_headers
  raw_headers="$(mktemp "${TMPDIR:-/tmp}/endpoint-agent-headers.XXXXXX")"
  if ! curl -fsSIL --max-time "$CURL_TIMEOUT" "$BINARY_URL" \
    -D "$raw_headers" -o /dev/null; then
    rm -f "$raw_headers"
    die "binary URL header preflight failed"
  fi
  awk 'BEGIN{IGNORECASE=1}
    /^HTTP\// || /^location:/ || /^content-type:/ || /^content-length:/ ||
    /^last-modified:/ || /^etag:/ { print }' "$raw_headers" \
    | sed -E 's/^([Ll]ocation: ).*/\1<redacted-redirect>/' \
    > "$headers_file"
  rm -f "$raw_headers"
  if [[ "$VERIFY_BINARY_SHA" == "1" ]]; then
    tmp_bin="$(mktemp "${TMPDIR:-/tmp}/endpoint-agent.XXXXXX")"
    if ! curl -fsSL --max-time 120 "$BINARY_URL" -o "$tmp_bin"; then
      rm -f "$tmp_bin"
      die "binary download failed"
    fi
    actual_sha="$(sha256_file "$tmp_bin")"
    rm -f "$tmp_bin"
    if [[ "$actual_sha" != "$EXPECTED_SHA256" ]]; then
      die "downloaded binary sha mismatch: expected=$EXPECTED_SHA256 actual=$actual_sha"
    fi
    jq -n \
      --arg binaryUrl "$BINARY_URL" \
      --arg sha256 "$actual_sha" \
      --arg expectedSha256 "$EXPECTED_SHA256" \
      --arg verifiedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      '{binaryUrl:$binaryUrl, sha256:$sha256, expectedSha256:$expectedSha256, ok:($sha256 == $expectedSha256), verifiedAt:$verifiedAt}' \
      > "${EVIDENCE_DIR}/binary-sha256.json"
  else
    jq -n \
      --arg binaryUrl "$BINARY_URL" \
      '{binaryUrl:$binaryUrl, ok:null, skipped:"VERIFY_BINARY_SHA is not 1"}' \
      > "${EVIDENCE_DIR}/binary-sha256.json"
  fi
  append_action "artifact-preflight" "ok" "release manifest and binary URL preflight complete"
}

run_release_flow() {
  local code existing_code existing_status existing_enabled payload
  payload="$(release_payload)"
  existing_status=""
  existing_enabled=""

  existing_code="$(curl_request GET "/endpoint-agent-update-releases/${RELEASE_ID}" "$CREATOR_TOKEN" release-get-before)"
  if [[ "$existing_code" == "200" ]]; then
    validate_release_body_matches_expected "${EVIDENCE_DIR}/release-get-before.body" "existing release"
    existing_status="$(jq -r '.status // ""' "${EVIDENCE_DIR}/release-get-before.body")"
    existing_enabled="$(jq -r '.enabled // false' "${EVIDENCE_DIR}/release-get-before.body")"
    append_action "release-get-before" "ok" "matching release row already exists with status=${existing_status}"
  elif [[ "$existing_code" == "404" ]]; then
    append_action "release-get-before" "missing" "release row not found"
    if [[ "$RUN_CREATE" == "1" ]]; then
      code="$(curl_request POST /endpoint-agent-update-releases "$CREATOR_TOKEN" release-create "$payload" 1)"
      expect_code_set "$code" "200,201" release-create
      validate_release_body_matches_expected "${EVIDENCE_DIR}/release-create.body" "created release"
      append_action "release-create" "ok" "release row created as DRAFT"
    fi
  elif [[ "$existing_code" == "401" || "$existing_code" == "403" ]]; then
    append_action "release-get-before" "auth-blocked" "API refused release read; provide manager token"
    if [[ "$RUN_CREATE" == "1" || "$RUN_APPROVE" == "1" ]]; then
      die "release read requires a valid manager token before mutation"
    fi
  else
    expect_code_set "$existing_code" "200,404,401,403" release-get-before
  fi

  if [[ "$RUN_APPROVE" == "1" && "$existing_status" == "APPROVED" && "$existing_enabled" == "true" ]]; then
    append_action "release-approve" "already-approved" "release was already APPROVED and enabled"
  elif [[ "$RUN_APPROVE" == "1" ]]; then
    code="$(curl_request POST "/endpoint-agent-update-releases/${RELEASE_ID}/approve" "$APPROVER_TOKEN" release-approve "" 1)"
    expect_code_set "$code" "200" release-approve
    validate_release_body_matches_expected "${EVIDENCE_DIR}/release-approve.body" "approved release"
    jq -e '.status == "APPROVED" and .enabled == true and (.createdBySubject // "") != (.approvedBySubject // "")' \
      "${EVIDENCE_DIR}/release-approve.body" >/dev/null \
      || die "approved release did not prove enabled maker-checker state"
    append_action "release-approve" "ok" "release approved and enabled with maker-checker subjects"
  fi

  code="$(curl_request GET "/endpoint-agent-update-releases/${RELEASE_ID}" "$CREATOR_TOKEN" release-get-after)"
  if [[ "$code" == "200" ]]; then
    validate_release_body_matches_expected "${EVIDENCE_DIR}/release-get-after.body" "release after flow"
    append_action "release-get-after" "ok" "release row readable after flow"
  else
    append_action "release-get-after" "skipped-or-blocked" "release after-flow read returned HTTP ${code}"
  fi
}

run_dispatch_flow() {
  local code neg_body body
  if [[ "$RUN_NEGATIVE_DISPATCH" == "1" ]]; then
    neg_body="$(negative_dispatch_payload)"
    code="$(curl_request POST "/endpoint-devices/${TARGET_DEVICE_ID}/agent-updates" "$DISPATCH_TOKEN" negative-dispatch-trust-fields "$neg_body" 1)"
    expect_code_set "$code" "400" negative-dispatch-trust-fields
    append_action "negative-dispatch-trust-fields" "ok" "caller-supplied trust fields rejected"
  fi

  if [[ "$RUN_DISPATCH" == "1" ]]; then
    body="$(dispatch_payload)"
    code="$(curl_request POST "/endpoint-devices/${TARGET_DEVICE_ID}/agent-updates" "$DISPATCH_TOKEN" update-agent-dispatch "$body" 1)"
    expect_code_set "$code" "200,201" update-agent-dispatch
    jq -e '(.type? // .commandType? // "") == "UPDATE_AGENT" or (.commandType? == "UPDATE_AGENT")' \
      "${EVIDENCE_DIR}/update-agent-dispatch.body" >/dev/null \
      || die "dispatch response does not look like an UPDATE_AGENT command"
    append_action "update-agent-dispatch" "ok" "catalog-bound UPDATE_AGENT command submitted"
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
    sums_file="$(mktemp "${TMPDIR:-/tmp}/rtt-update-agent-sha256.XXXXXX")"
    find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
      | sort -z \
      | xargs -0 "${hasher[@]}" \
      > "$sums_file"
    mv "$sums_file" SHA256SUMS
  )
}

write_summary() {
  local status="plan-ready"
  if [[ "$RUN_DISPATCH" == "1" ]]; then
    status="dispatch-attempted"
  elif [[ "$RUN_APPROVE" == "1" ]]; then
    status="release-approval-attempted"
  elif [[ "$RUN_CREATE" == "1" ]]; then
    status="release-create-attempted"
  fi
  if [[ "$LIVE_MUTATION" != "1" ]]; then
    status="plan-ready-no-mutation"
  fi

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg status "$status" \
    --arg apiBase "$API_BASE" \
    --arg releaseId "$RELEASE_ID" \
    --arg targetVersion "$TARGET_VERSION" \
    --arg binaryUrl "$BINARY_URL" \
    --arg sha256 "$EXPECTED_SHA256" \
    --arg signerThumbprint "$(normalize_thumbprint "$EXPECTED_SIGNER_THUMBPRINT")" \
    --arg signingTier "$SIGNING_TIER" \
    --argjson maxBytes "$MAX_BYTES" \
    --arg targetDeviceId "$TARGET_DEVICE_ID" \
    --arg targetDeviceHostname "$TARGET_DEVICE_HOSTNAME" \
    --arg liveMutation "$LIVE_MUTATION" \
    --arg runCreate "$RUN_CREATE" \
    --arg runApprove "$RUN_APPROVE" \
    --arg runNegativeDispatch "$RUN_NEGATIVE_DISPATCH" \
    --arg runDispatch "$RUN_DISPATCH" \
    --argjson actions "$ACTIONS_JSON" \
    '{
      generatedAt: $generatedAt,
      status: $status,
      apiBase: $apiBase,
      liveMutation: ($liveMutation == "1"),
      requestedActions: {
        create: ($runCreate == "1"),
        approve: ($runApprove == "1"),
        negativeDispatch: ($runNegativeDispatch == "1"),
        dispatch: ($runDispatch == "1")
      },
      release: {
        releaseId: $releaseId,
        targetVersion: $targetVersion,
        binaryUrl: $binaryUrl,
        sha256: $sha256,
        signerThumbprint: $signerThumbprint,
        signingTier: $signingTier,
        maxBytes: $maxBytes
      },
      targetEndpoint: {
        deviceId: $targetDeviceId,
        hostname: $targetDeviceHostname
      },
      actions: $actions,
      acceptedNextEvidence: [
        "release row APPROVED and enabled with maker-checker subjects",
        "negative dispatch rejects caller-supplied trust fields",
        "catalog-bound UPDATE_AGENT dispatch response",
        ("post-update heartbeat proving " + $targetVersion + " before platform-agent#208 terminal smoke")
      ],
      rejectedPaths: [
        "direct database insert",
        "Software Catalog abuse",
        "Approved Script Runner download-and-execute",
        "generic endpoint command UPDATE_AGENT",
        "caller-supplied binary/hash/signer fields on dispatch",
        "raw PowerShell or unrestricted terminal",
        "RDP/SSH/WinRM/SMB/RPC/file browser/reverse tunnel"
      ],
      doesNotProve: [
        "platform-agent#208 runtime AGENT_OUTPUT/DATA acceptance",
        "Remote Response Terminal PERMIT path",
        "recording export verifier acceptance",
        "signed MSI/GPO or broad rollout",
        "production remote-support readiness",
        "true TPM/device-key hardware attestation"
      ]
    }' > "${EVIDENCE_DIR}/summary.json"
}

main() {
  local normalized_thumbprint
  need_cmd curl
  need_cmd jq
  need_cmd mktemp
  mkdir -p "$EVIDENCE_DIR"
  API_BASE="${API_BASE%/}"

  if [[ "$RUN_CREATE" == "1" || "$RUN_APPROVE" == "1" || "$RUN_NEGATIVE_DISPATCH" == "1" || "$RUN_DISPATCH" == "1" ]]; then
    [[ "$LIVE_MUTATION" == "1" ]] || die "live actions requested; set LIVE_MUTATION=1 explicitly"
  fi

  CREATOR_TOKEN="$(read_token CREATOR_BEARER_TOKEN CREATOR_BEARER_TOKEN_FILE)"
  APPROVER_TOKEN="$(read_token APPROVER_BEARER_TOKEN APPROVER_BEARER_TOKEN_FILE)"
  DISPATCH_TOKEN="$(read_token DISPATCH_BEARER_TOKEN DISPATCH_BEARER_TOKEN_FILE)"
  if [[ -z "$DISPATCH_TOKEN" ]]; then
    DISPATCH_TOKEN="$APPROVER_TOKEN"
  fi

  [[ "$EXPECTED_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "EXPECTED_SHA256 must be lowercase 64-char hex"
  normalized_thumbprint="$(normalize_thumbprint "$EXPECTED_SIGNER_THUMBPRINT")"
  [[ "$normalized_thumbprint" =~ ^([0-9A-F]{40}|[0-9A-F]{64})$ ]] \
    || die "EXPECTED_SIGNER_THUMBPRINT must be SHA1 or SHA256 thumbprint hex"
  [[ "$MAX_BYTES" =~ ^[1-9][0-9]*$ ]] || die "MAX_BYTES must be a positive integer"

  write_plan_files
  verify_artifacts

  if [[ "$RUN_CREATE" == "1" || "$RUN_APPROVE" == "1" ]]; then
    [[ -n "$CREATOR_TOKEN" ]] || die "CREATOR_BEARER_TOKEN or CREATOR_BEARER_TOKEN_FILE is required"
    run_release_flow
  else
    append_action "release-flow" "skipped" "RUN_CREATE/RUN_APPROVE not requested"
  fi

  if [[ "$RUN_NEGATIVE_DISPATCH" == "1" || "$RUN_DISPATCH" == "1" ]]; then
    [[ -n "$DISPATCH_TOKEN" ]] || die "DISPATCH_BEARER_TOKEN/FILE or APPROVER_BEARER_TOKEN/FILE is required"
    run_dispatch_flow
  else
    append_action "dispatch-flow" "skipped" "RUN_NEGATIVE_DISPATCH/RUN_DISPATCH not requested"
  fi

  write_summary
  sha256_manifest

  jq -r --arg evidenceDir "$EVIDENCE_DIR" \
    '"UPDATE_AGENT_SEED_STATUS=" + .status + " evidence_dir=" + $evidenceDir' \
    "${EVIDENCE_DIR}/summary.json"
}

main "$@"
