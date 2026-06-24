#!/usr/bin/env bash
set -euo pipefail

# Faz 22.6.3 Remote Response Terminal pilot readiness preflight.
#
# This script is read-only. It validates the public EndpointAgent artifact
# manifest, optionally reads staging endpoint-admin DB truth over SSH, and
# writes a bounded JSON decision summary. It never dispatches UPDATE_AGENT,
# runs scripts, opens terminal sessions, mutates Kubernetes, edits GitOps
# desired-state, or executes endpoint commands.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
# shellcheck source=scripts/faz22-remote-ops/endpoint-agent-release-policy.sh
source "${SCRIPT_DIR}/endpoint-agent-release-policy.sh"
endpoint_agent_release_policy_load "$REPO_ROOT"

ARTIFACT_MANIFEST_URL="${ARTIFACT_MANIFEST_URL:-${ARTIFACT_BASE_URL}/release-manifest.json}"
EXPECTED_RELEASE_TAG="${EXPECTED_RELEASE_TAG:-$EXPECTED_AGENT_TAG}"
EXPECTED_AGENT_VERSION="${EXPECTED_AGENT_VERSION:-${EXPECTED_RELEASE_TAG#v}}"
: "${EXPECTED_AGENT_SHA256:?missing expected agent SHA256}"
: "${EXPECTED_AGENT_ZIP_SHA256:?missing expected EndpointAgent.zip SHA256}"
: "${EXPECTED_SIGNER_THUMBPRINT:?missing expected signer thumbprint}"

DEVICE_ID="${DEVICE_ID:-423b6fc3-7497-4083-bd2f-5e2fe543bfe9}"
DEVICE_HOSTNAME="${DEVICE_HOSTNAME:-SRB-AIDENETIMPC}"

STAGING_SSH_TARGET="${STAGING_SSH_TARGET:-halil@staging-sw}"
SSH_CONNECT_TIMEOUT_SECONDS="${SSH_CONNECT_TIMEOUT_SECONDS:-8}"
PG_CONTAINER="${PG_CONTAINER:-platform-pg-test}"
PG_DATABASE="${PG_DATABASE:-endpoint_admin}"
PG_USER="${PG_USER:-postgres}"

REQUIRE_STAGING_DB="${REQUIRE_STAGING_DB:-0}"
REQUIRE_READY="${REQUIRE_READY:-0}"
EVIDENCE_DIR="${EVIDENCE_DIR:-/tmp/remote-response-terminal-pilot-readiness-$(date -u +%Y%m%dT%H%M%SZ)}"

die() {
  printf 'ERR %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

sql_quote() {
  printf "%s" "$1" | sed "s/'/''/g"
}

run_staging_sql() {
  local sql="$1" out="$2" remote_cmd
  remote_cmd=$(printf "docker exec %q psql -U %q -d %q -At -F '|' -c %q" \
    "$PG_CONTAINER" "$PG_USER" "$PG_DATABASE" "$sql")
  ssh -o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT_SECONDS" \
    "$STAGING_SSH_TARGET" "$remote_cmd" > "$out"
}

normalize_thumbprint() {
  printf '%s' "$1" | tr '[:lower:]' '[:upper:]'
}

json_array_contains() {
  local json="$1" cap="$2"
  jq -e --arg cap "$cap" \
    'if type == "array" then index($cap) != null
     elif type == "object" then .[$cap] == true
     else false end' <<< "$json" >/dev/null
}

main() {
  need_cmd curl
  need_cmd jq
  need_cmd sed
  mkdir -p "$EVIDENCE_DIR"

  local manifest_file manifest_json manifest_ok
  manifest_file="${EVIDENCE_DIR}/artifact-manifest.json"
  curl -fsS --max-time 20 "$ARTIFACT_MANIFEST_URL" -o "$manifest_file"
  manifest_json="$(jq -c . "$manifest_file")"
  manifest_ok="false"
  if jq -e \
    --arg tag "$EXPECTED_RELEASE_TAG" \
    --arg sha "$EXPECTED_AGENT_SHA256" \
    --arg zip "$EXPECTED_AGENT_ZIP_SHA256" \
    --arg thumb "$(normalize_thumbprint "$EXPECTED_SIGNER_THUMBPRINT")" \
    '(.release_tag == $tag)
      and (.endpoint_agent_sha256 == $sha)
      and (.endpoint_agent_zip_sha256 == $zip)
      and ((.signer_thumbprint // "" | ascii_upcase) == $thumb)' \
    "$manifest_file" >/dev/null; then
    manifest_ok="true"
  fi

  local db_status="skipped" db_error="" device_json="null" release_rows_json="[]" catalog_rows_json="[]"
  local decision="manifest-only" reason="staging DB read not requested"
  local update_agent_capable="false" release_ready="false" endpoint_version=""

  if [[ -n "$STAGING_SSH_TARGET" ]]; then
    local device_file release_file catalog_file sql device_id_sql device_host_sql
    device_file="${EVIDENCE_DIR}/device-heartbeat.psv"
    release_file="${EVIDENCE_DIR}/agent-update-releases.psv"
    catalog_file="${EVIDENCE_DIR}/software-catalog-candidates.psv"
    device_id_sql="$(sql_quote "$DEVICE_ID")"
    device_host_sql="$(sql_quote "$DEVICE_HOSTNAME")"

    sql="
select d.id,d.hostname,coalesce(d.agent_version,''),coalesce(d.status,''),
       coalesce(d.last_seen_at::text,''),coalesce(h.received_at::text,''),
       coalesce((h.payload->'capabilities')::text,'[]')
from endpoint_admin_service.endpoint_devices d
left join lateral (
  select * from endpoint_admin_service.endpoint_heartbeats h
  where h.device_id=d.id
  order by h.received_at desc
  limit 1
) h on true
where d.id='${device_id_sql}'::uuid or d.hostname='${device_host_sql}'
order by case when d.id='${device_id_sql}'::uuid then 0 else 1 end,
         d.last_seen_at desc nulls last
limit 1;"

    if run_staging_sql "$sql" "$device_file" 2>"${EVIDENCE_DIR}/staging-db.stderr"; then
      db_status="ok"
      sql="
select release_id,target_version,status,enabled,signing_tier,signer_thumbprint,sha256,binary_url
from endpoint_admin_service.endpoint_agent_update_releases
where release_id in ('$(sql_quote "$EXPECTED_RELEASE_TAG")','$(sql_quote "$EXPECTED_AGENT_VERSION")')
   or target_version in ('$(sql_quote "$EXPECTED_RELEASE_TAG")','$(sql_quote "$EXPECTED_AGENT_VERSION")')
order by last_updated_at desc
limit 10;"
      run_staging_sql "$sql" "$release_file"

      sql="
select catalog_item_id,display_name,package_id,source_type,provider,installer_type,status,enabled
from endpoint_admin_service.endpoint_software_catalog_items
where lower(display_name) like '%agent%'
   or lower(display_name) like '%endpoint%'
   or lower(display_name) like '%7-zip%'
   or lower(package_id) like '%agent%'
order by last_updated_at desc
limit 30;"
      run_staging_sql "$sql" "$catalog_file"
    else
      db_status="error"
      db_error="$(tr '\n' ' ' < "${EVIDENCE_DIR}/staging-db.stderr" | sed 's/[[:space:]]\{1,\}/ /g')"
      if [[ "$REQUIRE_STAGING_DB" == "1" ]]; then
        die "staging DB read failed: ${db_error}"
      fi
    fi

    if [[ "$db_status" == "ok" ]]; then
      if [[ -s "$device_file" ]]; then
        local row id hostname status last_seen heartbeat_at caps caps_json
        row="$(head -n 1 "$device_file")"
        IFS='|' read -r id hostname endpoint_version status last_seen heartbeat_at caps <<< "$row"
        if jq -e . <<< "$caps" >/dev/null 2>&1; then
          caps_json="$(jq -c . <<< "$caps")"
        else
          caps_json="[]"
        fi
        if json_array_contains "$caps_json" "UPDATE_AGENT"; then
          update_agent_capable="true"
        fi
        device_json="$(jq -cn \
          --arg id "$id" \
          --arg hostname "$hostname" \
          --arg version "$endpoint_version" \
          --arg status "$status" \
          --arg lastSeen "$last_seen" \
          --arg heartbeatAt "$heartbeat_at" \
          --argjson capabilities "$caps_json" \
          '{id:$id,hostname:$hostname,agent_version:$version,status:$status,last_seen_at:$lastSeen,heartbeat_received_at:$heartbeatAt,capabilities:$capabilities}')"
      fi

      release_rows_json="$(jq -R -s '
        split("\n")
        | map(select(length > 0) | split("|") | {
            release_id: .[0],
            target_version: .[1],
            status: .[2],
            enabled: (.[3] == "t"),
            signing_tier: .[4],
            signer_thumbprint: .[5],
            sha256: .[6],
            binary_url: .[7]
          })' "$release_file")"
      catalog_rows_json="$(jq -R -s '
        split("\n")
        | map(select(length > 0) | split("|") | {
            catalog_item_id: .[0],
            display_name: .[1],
            package_id: .[2],
            source_type: .[3],
            provider: .[4],
            installer_type: .[5],
            status: .[6],
            enabled: (.[7] == "t")
          })' "$catalog_file")"

      if jq -e \
        --arg tag "$EXPECTED_RELEASE_TAG" \
        --arg version "$EXPECTED_AGENT_VERSION" \
        --arg sha "$EXPECTED_AGENT_SHA256" \
        --arg thumb "$(normalize_thumbprint "$EXPECTED_SIGNER_THUMBPRINT")" \
        'any(.[]; (.release_id == $tag or .release_id == $version or .target_version == $tag or .target_version == $version)
          and .status == "APPROVED"
          and .enabled == true
          and .sha256 == $sha
          and ((.signer_thumbprint // "" | ascii_upcase) == $thumb))' \
        <<< "$release_rows_json" >/dev/null; then
        release_ready="true"
      fi

      if [[ "$device_json" == "null" ]]; then
        decision="target-endpoint-not-found"
        reason="No matching endpoint device row for DEVICE_ID or DEVICE_HOSTNAME."
      # Accept local build suffixes such as vX.Y.Z-pilot.1 for readiness; the
      # artifact manifest hash/signer check above remains exact.
      elif [[ "$endpoint_version" == "$EXPECTED_RELEASE_TAG" || "$endpoint_version" == "$EXPECTED_AGENT_VERSION" || "$endpoint_version" == *"$EXPECTED_AGENT_VERSION"* ]]; then
        decision="ready-for-product-smoke"
        reason="Target endpoint already reports the expected agent version."
      elif [[ "$update_agent_capable" == "true" && "$release_ready" == "true" ]]; then
        decision="use-catalog-bound-update-agent"
        reason="Target is older, advertises UPDATE_AGENT, and an approved matching release catalog row exists."
      elif [[ "$update_agent_capable" == "true" ]]; then
        decision="seed-or-approve-release-catalog-first"
        reason="Target advertises UPDATE_AGENT, but no approved matching release catalog row was found."
      else
        decision="owner-approved-seed-required"
        reason="Target is older and does not advertise UPDATE_AGENT; do not use Software Catalog or Approved Script Runner as a hidden installer lane."
      fi
    else
      decision="blocked-live-db-read"
      reason="Staging DB truth was not available; cannot decide endpoint readiness from local context."
    fi
  fi

  local summary_file
  summary_file="${EVIDENCE_DIR}/summary.json"
  if [[ "$manifest_ok" != "true" ]]; then
    decision="artifact-manifest-mismatch"
    reason="Public artifact manifest does not match the expected release tag, hash, zip hash, and signer thumbprint."
  fi

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg decision "$decision" \
    --arg reason "$reason" \
    --arg manifestUrl "$ARTIFACT_MANIFEST_URL" \
    --arg expectedReleaseTag "$EXPECTED_RELEASE_TAG" \
    --arg expectedAgentVersion "$EXPECTED_AGENT_VERSION" \
    --arg expectedSha256 "$EXPECTED_AGENT_SHA256" \
    --arg expectedZipSha256 "$EXPECTED_AGENT_ZIP_SHA256" \
    --arg expectedSignerThumbprint "$(normalize_thumbprint "$EXPECTED_SIGNER_THUMBPRINT")" \
    --argjson manifest "$manifest_json" \
    --argjson manifestOk "$manifest_ok" \
    --arg stagingSshTarget "$STAGING_SSH_TARGET" \
    --arg dbStatus "$db_status" \
    --arg dbError "$db_error" \
    --arg deviceId "$DEVICE_ID" \
    --arg deviceHostname "$DEVICE_HOSTNAME" \
    --arg updateAgentCapable "$update_agent_capable" \
    --arg releaseReady "$release_ready" \
    --argjson device "$device_json" \
    --argjson releases "$release_rows_json" \
    --argjson catalog "$catalog_rows_json" \
    '{
      generatedAt: $generatedAt,
      decision: $decision,
      reason: $reason,
      manifest: {
        url: $manifestUrl,
        expectedReleaseTag: $expectedReleaseTag,
        expectedAgentVersion: $expectedAgentVersion,
        expectedSha256: $expectedSha256,
        expectedZipSha256: $expectedZipSha256,
        expectedSignerThumbprint: $expectedSignerThumbprint,
        ok: $manifestOk,
        observed: $manifest
      },
      stagingDb: {
        target: $stagingSshTarget,
        status: $dbStatus,
        error: $dbError
      },
      targetEndpoint: {
        requestedId: $deviceId,
        requestedHostname: $deviceHostname,
        updateAgentCapable: ($updateAgentCapable == "true"),
        releaseReady: ($releaseReady == "true"),
        observed: $device
      },
      agentUpdateReleaseCandidates: $releases,
      softwareCatalogCandidates: $catalog,
      acceptedSeedPaths: [
        "catalog-bound UPDATE_AGENT when heartbeat advertises UPDATE_AGENT and release catalog is APPROVED+enabled",
        "owner-approved local maintenance install for one pilot endpoint, then product-channel smoke",
        "cert-enrolled test endpoint already running the expected agent version"
      ],
      rejectedAcceptancePaths: [
        "Software Catalog abuse without an approved EndpointAgent WinGet catalog item",
        "Approved Script Runner download-and-execute",
        "generic endpoint-commands UPDATE_AGENT",
        "direct DB insert",
        "caller-supplied binary/hash/signer fields",
        "raw PowerShell or unrestricted terminal",
        "RDP/SSH/WinRM/SMB/RPC/file browser/reverse tunnel"
      ]
    }' > "$summary_file"

  (
    cd "$EVIDENCE_DIR"
    local sums_file
    sums_file="$(mktemp "${TMPDIR:-/tmp}/rtt-pilot-readiness-sha256.XXXXXX")"
    find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
      | sort -z \
      | xargs -0 shasum -a 256 \
      > "$sums_file"
    mv "$sums_file" SHA256SUMS
  )

  printf 'INFO evidence_dir=%s\n' "$EVIDENCE_DIR"
  jq -r '"DECISION " + .decision + " reason=" + .reason' "$summary_file"

  if [[ "$REQUIRE_READY" == "1" && "$decision" != "ready-for-product-smoke" ]]; then
    exit 2
  fi
}

main "$@"
