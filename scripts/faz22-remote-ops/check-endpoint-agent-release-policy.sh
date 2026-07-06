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
	  and ($root.current_bounded_pilot.install_ps1_sha256 | test("^[a-f0-9]{64}$"))
	  and ($root.current_bounded_pilot.bootstrap_package_ps1_sha256 | test("^[a-f0-9]{64}$"))
	  and ($root.current_bounded_pilot.artifact_host_digest | test("^sha256:[a-f0-9]{64}$"))
	  and ($root.current_bounded_pilot.artifact_host_image_ref | test("^ghcr\\.io/halildeu/platform-agent-artifacts:" + $root.current_bounded_pilot.release_tag + "@sha256:[a-f0-9]{64}$"))
	  and ($root.current_bounded_pilot.artifact_host_image_ref | contains("@" + $root.current_bounded_pilot.artifact_host_digest))
	  and ($root.current_bounded_pilot.signer_thumbprint | test("^[A-F0-9]{40}$"))
	  and ($root.current_bounded_pilot.signer_sha256_fingerprint | test("^[A-F0-9]{64}$"))
  and ($root.current_bounded_pilot.signing_tier | length > 0)
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
  pinned_sha="$(jq -r '.current_bounded_pilot.release_manifest_sha256' "$POLICY_FILE")"
  manifest_url="$(jq -r '.current_bounded_pilot.github_release_base_url' "$POLICY_FILE")/release-manifest.json"
  if ! actual_sha="$(curl --max-time 20 -fsSL -H 'Cache-Control: no-cache' "$manifest_url" | sha256_stdin)"; then
    die "release-manifest.json SHA256 fetch failed: url=$manifest_url"
  fi
  if [ "$actual_sha" != "$pinned_sha" ]; then
    die "release-manifest.json SHA256 mismatch: expected=$pinned_sha actual=$actual_sha"
  fi
  printf 'release-manifest.json SHA256 verified: %s\n' "$actual_sha"
fi

printf 'ENDPOINT_AGENT_RELEASE_POLICY=pass path=%s release_tag=%s next_trusted_minor=%s\n' \
  "$POLICY_FILE" \
  "$release_tag" \
  "$(jq -r '.release_train_policy.next_trusted_minor' "$POLICY_FILE")"
