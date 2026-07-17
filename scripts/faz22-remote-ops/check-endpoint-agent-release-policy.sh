#!/usr/bin/env bash
# Validate the Faz 22.6 EndpointAgent release policy SSOT.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
POLICY_FILE="${ENDPOINT_AGENT_RELEASE_POLICY_FILE:-$REPO_ROOT/config/faz22-6-endpoint-agent-release-policy.v1.json}"

die() {
  printf 'endpoint-agent-release-policy: %s\n' "$*" >&2
  exit 2
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

sha256_stdin() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | awk '{print $1}'
  else
    die "missing command: sha256sum or shasum"
  fi
}

github_api_get() {
  local url="$1" output="$2"
  local -a args=(--max-time 20 -fsSL -H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28')
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    args+=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
  fi
  curl "${args[@]}" "$url" >"$output"
}

need jq
[ -f "$POLICY_FILE" ] || die "policy file not found: $POLICY_FILE"

jq -e '
  . as $root |
  $root.schema_version == "faz22.6.endpoint-agent-release-policy.v1"
  and $root.status == "active"
	  and ($root.current_bounded_pilot.release_tag | test("^v[0-9]+\\.[0-9]+\\.[0-9]+$"))
	  and ($root.current_bounded_pilot.agent_version == ($root.current_bounded_pilot.release_tag | sub("^v"; "")))
	  and (($root.release_train_policy.allowed_release_classes | index($root.current_bounded_pilot.release_class)) != null)
	  and ($root.current_bounded_pilot.source_commit | test("^[a-f0-9]{40}$"))
	  and ($root.current_bounded_pilot.endpoint_agent_sha256 | test("^[a-f0-9]{64}$"))
	  and ($root.current_bounded_pilot.endpoint_agent_zip_sha256 | test("^[a-f0-9]{64}$"))
	  and ($root.current_bounded_pilot.endpoint_agent_max_bytes > 0)
	  and ($root.current_bounded_pilot.release_manifest_sha256 | test("^[a-f0-9]{64}$"))
	  and ($root.current_bounded_pilot.remote_bridge_attestation_evidence_sha256 | test("^[a-f0-9]{64}$"))
	  and ($root.current_bounded_pilot.remote_bridge_attestation_summary_sha256 | test("^[a-f0-9]{64}$"))
	  and ($root.current_bounded_pilot.install_ps1_sha256 | test("^[a-f0-9]{64}$"))
	  and ($root.current_bounded_pilot.bootstrap_package_ps1_sha256 | test("^[a-f0-9]{64}$"))
	  and ($root.current_bounded_pilot.artifact_host_digest | test("^sha256:[a-f0-9]{64}$"))
	  and ($root.current_bounded_pilot.artifact_host_image_ref | test("^ghcr\\.io/halildeu/platform-agent-artifacts:" + $root.current_bounded_pilot.release_tag + "@sha256:[a-f0-9]{64}$"))
	  and ($root.current_bounded_pilot.artifact_host_image_ref | contains("@" + $root.current_bounded_pilot.artifact_host_digest))
	  and ($root.current_bounded_pilot.signer_thumbprint | test("^[A-F0-9]{40}$"))
	  and ($root.current_bounded_pilot.signer_sha256_fingerprint | test("^[A-F0-9]{64}$"))
  and ($root.current_bounded_pilot.signing_tier | length > 0)
  and ($root.current_bounded_pilot.artifact_base_url == "https://testai.acik.com/artifacts/endpoint-agent/current")
  and ($root.current_bounded_pilot.artifact_release_base_url == ("https://testai.acik.com/artifacts/endpoint-agent/" + $root.current_bounded_pilot.release_tag))
  and ($root.current_bounded_pilot.github_release_base_url | test("/" + $root.current_bounded_pilot.release_tag + "$"))
  and ($root.release_train_policy.frozen_minor != $root.release_train_policy.next_trusted_minor)
  and ($root.release_train_policy.recent_release_window >= $root.release_train_policy.recent_release_hygiene_threshold)
  and ($root.release_train_policy.recent_release_hygiene_threshold > 0)
  and ($root.release_train_policy.max_trusted_releases_per_day > 0)
  and ($root.release_train_policy.require_main_ancestor == true)
  and ($root.release_train_policy.require_tag_protection == true)
  and ($root.release_train_policy.require_post_publish_verifier == true)
  and ($root.release_train_policy.require_release_class == true)
  and (($root.release_train_policy.allowed_release_classes | index("bounded-pilot")) != null)
  and (($root.release_train_policy.allowed_release_classes | index("rollout-candidate")) != null)
  and ($root.release_train_policy | has("trusted_lineage_started_at"))
  and ($root.release_train_policy.trusted_lineage_started_at | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"))
  and ($root.release_train_policy | has("active_series_dense_threshold"))
  and ($root.release_train_policy.active_series_dense_threshold > 0)
  and (($root.release_train_policy | has("trusted_series_regex") | not) or ($root.release_train_policy.trusted_series_regex == $root.release_train_policy.recent_release_series_regex))
  and (($root.bounded_pilot_waiver.accepted_findings | sort) == ["GITHUB_RELEASE_ACTIVE_SERIES_DENSE","GITHUB_RELEASE_DENSE_TRAIN","GITHUB_RELEASE_FROZEN_SERIES_REGRESSION","GITHUB_RELEASE_IMMUTABLE","GITHUB_RELEASE_LATEST_POINTER"])
  and (($root.bounded_pilot_waiver.forbidden_claims | index("5-device")) != null)
  and (($root.bounded_pilot_waiver.forbidden_claims | index("50-device")) != null)
  and (($root.bounded_pilot_waiver.forbidden_claims | index("800-device")) != null)
  and (($root.bounded_pilot_waiver.forbidden_claims | index("production")) != null)
  and (($root.bounded_pilot_waiver.forbidden_claims | index("broad-rollout")) != null)
  and (($root.release_manifest_required_fields | index("source_commit")) != null)
  and (($root.release_manifest_required_fields | index("workflow_run_id")) != null)
  and (($root.release_manifest_required_fields | index("release_class")) != null)
  and (($root.release_manifest_required_fields | index("artifact_host_digest")) != null)
  and (($root.release_manifest_required_fields | index("artifact_host_image_ref")) != null)
  and (($root.release_manifest_required_fields | index("previous_release")) != null)
  and ($root.current_bounded_pilot | has("previous_release"))
  and ($root.current_bounded_pilot | has("workflow_run_id"))
  and ($root.current_bounded_pilot.previous_release | test("^v[0-9]+\\.[0-9]+\\.[0-9]+$"))
  and ($root.current_bounded_pilot.workflow_run_id | test("^[0-9]+$"))
  and ($root.broad_rollout_language.allowed_only_when == "F22_6_RELEASE_LINEAGE=pass")
' "$POLICY_FILE" >/dev/null || die "policy schema/content validation failed"

series_regex="$(jq -r '.release_train_policy.recent_release_series_regex' "$POLICY_FILE")"
release_tag="$(jq -r '.current_bounded_pilot.release_tag' "$POLICY_FILE")"
if ! [[ "$release_tag" =~ $series_regex ]]; then
  die "current release_tag does not match recent_release_series_regex"
fi

next_minor="$(jq -r '.release_train_policy.next_trusted_minor' "$POLICY_FILE")"
current_minor="$(printf '%s' "$release_tag" | sed -E 's/^(v[0-9]+\.[0-9]+)\.[0-9]+$/\1/')"
if [ "$current_minor" != "$next_minor" ]; then
  die "current release minor $current_minor does not match next_trusted_minor $next_minor"
fi

# B3 gap-fix: verify release-manifest.json SHA256 against pinned value in policy.
# Set SKIP_MANIFEST_FETCH=1 in environments without outbound HTTPS (e.g. air-gapped).
if [ "${SKIP_MANIFEST_FETCH:-0}" != "1" ]; then
  need curl
  manifest_tmp="$(mktemp)"
  trap 'rm -f "$manifest_tmp"' EXIT
  pinned_sha="$(jq -r '.current_bounded_pilot.release_manifest_sha256' "$POLICY_FILE")"
  manifest_url="$(jq -r '.current_bounded_pilot.github_release_base_url' "$POLICY_FILE")/release-manifest.json"
  if ! curl --max-time 20 -fsSL -H 'Cache-Control: no-cache' "$manifest_url" > "$manifest_tmp"; then
    die "release-manifest.json SHA256 fetch failed: url=$manifest_url"
  fi
  actual_sha="$(sha256_stdin < "$manifest_tmp")"
  if [ "$actual_sha" != "$pinned_sha" ]; then
    die "release-manifest.json SHA256 mismatch: expected=$pinned_sha actual=$actual_sha"
  fi
  jq -e --slurpfile policy "$POLICY_FILE" '
    $policy[0].current_bounded_pilot as $p |
    .release_tag == $p.release_tag
    and .source_commit == $p.source_commit
    and .workflow_run_id == $p.workflow_run_id
    and .release_class == $p.release_class
    and .previous_release == $p.previous_release
    and .endpoint_agent_sha256 == $p.endpoint_agent_sha256
    and .endpoint_agent_zip_sha256 == $p.endpoint_agent_zip_sha256
    and .signer_thumbprint == $p.signer_thumbprint
    and .signing_tier == $p.signing_tier
    and .artifact_host_digest == $p.artifact_host_digest
    and .artifact_host_image_ref == $p.artifact_host_image_ref
    and .remote_bridge_attestation.evidence_sha256 == $p.remote_bridge_attestation_evidence_sha256
    and .remote_bridge_attestation.summary_sha256 == $p.remote_bridge_attestation_summary_sha256
    and .remote_bridge_attestation.binary_digest == $p.endpoint_agent_sha256
    and .remote_bridge_attestation.private_key_included == false
  ' "$manifest_tmp" >/dev/null \
    || die "release-manifest.json content does not match pinned release policy"
  printf 'release-manifest.json SHA256 verified: %s\n' "$actual_sha"
  printf 'release-manifest.json policy content binding verified: %s\n' "$release_tag"
fi

# Bind the policy to GitHub's immutable release record and to the exact
# successful trusted release workflow run. This closes the gap where a policy
# file and overlay could agree with each other but not with the producer.
if [ "${SKIP_GITHUB_API_FETCH:-0}" != "1" ]; then
  need curl
  release_api_tmp="$(mktemp)"
  workflow_api_tmp="$(mktemp)"
  trap 'rm -f "${manifest_tmp:-}" "${release_api_tmp:-}" "${workflow_api_tmp:-}"' EXIT

  release_api_url="https://api.github.com/repos/Halildeu/platform-agent/releases/tags/${release_tag}"
  workflow_run_id="$(jq -r '.current_bounded_pilot.workflow_run_id' "$POLICY_FILE")"
  workflow_api_url="https://api.github.com/repos/Halildeu/platform-agent/actions/runs/${workflow_run_id}"
  github_api_get "$release_api_url" "$release_api_tmp" \
    || die "GitHub immutable release metadata fetch failed: tag=$release_tag"
  github_api_get "$workflow_api_url" "$workflow_api_tmp" \
    || die "GitHub trusted release workflow metadata fetch failed: run=$workflow_run_id"

  jq -e --slurpfile policy "$POLICY_FILE" '
    $policy[0].current_bounded_pilot as $p |
    def asset($name): [.assets[] | select(.name == $name)] | if length == 1 then .[0] else null end;
    .tag_name == $p.release_tag
    and .immutable == true
    and .draft == false
    and .prerelease == false
    and (asset("release-manifest.json").digest == ("sha256:" + $p.release_manifest_sha256))
    and (asset("endpoint-agent.exe").digest == ("sha256:" + $p.endpoint_agent_sha256))
    and (asset("endpoint-agent.exe").size == $p.endpoint_agent_max_bytes)
    and (asset("EndpointAgent.zip").digest == ("sha256:" + $p.endpoint_agent_zip_sha256))
    and (asset("install.ps1").digest == ("sha256:" + $p.install_ps1_sha256))
    and (asset("bootstrap-package.ps1").digest == ("sha256:" + $p.bootstrap_package_ps1_sha256))
    and (asset("remote-bridge-attestation-evidence.b64").digest == ("sha256:" + $p.remote_bridge_attestation_evidence_sha256))
    and (asset("remote-bridge-attestation-evidence-summary.json").digest == ("sha256:" + $p.remote_bridge_attestation_summary_sha256))
  ' "$release_api_tmp" >/dev/null \
    || die "GitHub immutable release assets do not match pinned release policy"

  jq -e --slurpfile policy "$POLICY_FILE" '
    $policy[0].current_bounded_pilot as $p |
    (.id | tostring) == $p.workflow_run_id
    and .status == "completed"
    and .conclusion == "success"
    and .event == "push"
    and .head_sha == $p.source_commit
    and .head_branch == $p.release_tag
    and .path == ".github/workflows/release-exe-signed.yml"
  ' "$workflow_api_tmp" >/dev/null \
    || die "GitHub trusted release workflow run does not match pinned release policy"

  printf 'GitHub immutable release assets verified: %s\n' "$release_tag"
  printf 'GitHub trusted release workflow verified: %s\n' "$workflow_run_id"
fi

printf 'ENDPOINT_AGENT_RELEASE_POLICY=pass path=%s release_tag=%s next_trusted_minor=%s\n' \
  "$POLICY_FILE" \
  "$release_tag" \
  "$(jq -r '.release_train_policy.next_trusted_minor' "$POLICY_FILE")"
