#!/usr/bin/env bash
# Shared EndpointAgent release policy loader for Faz 22.6 scripts.
#
# The policy file is the single source of truth for the current bounded pilot
# release, release-lineage waiver scope, train hygiene threshold, and artifact
# digest expectations. Call endpoint_agent_release_policy_load after REPO_ROOT
# is known. Existing environment variables still override policy values for
# tests and controlled break-glass rechecks.

endpoint_agent_release_policy_load() {
  local repo_root="${1:-}"
  local policy_file
  [ -n "$repo_root" ] || {
    printf 'ENDPOINT_AGENT_RELEASE_POLICY_ERROR=missing-repo-root\n' >&2
    return 2
  }
  policy_file="${ENDPOINT_AGENT_RELEASE_POLICY_FILE:-$repo_root/config/faz22-6-endpoint-agent-release-policy.v1.json}"
  [ -f "$policy_file" ] || {
    printf 'ENDPOINT_AGENT_RELEASE_POLICY_ERROR=missing-policy-file path=%s\n' "$policy_file" >&2
    return 2
  }
  command -v jq >/dev/null 2>&1 || {
    printf 'ENDPOINT_AGENT_RELEASE_POLICY_ERROR=missing-command:jq\n' >&2
    return 2
  }

  _endpoint_agent_policy_default() {
    local name="$1" value="$2"
    if [ -z "${!name:-}" ]; then
      printf -v "$name" '%s' "$value"
    fi
  }

  _endpoint_agent_policy_read() {
    local filter="$1"
    jq -er "$filter" "$policy_file"
  }

  _endpoint_agent_policy_csv() {
    local filter="$1"
    jq -er "$filter | join(\",\")" "$policy_file"
  }

  ENDPOINT_AGENT_RELEASE_POLICY_PATH="$policy_file"

  _endpoint_agent_policy_default EXPECTED_AGENT_TAG "$(_endpoint_agent_policy_read '.current_bounded_pilot.release_tag')"
  _endpoint_agent_policy_default EXPECTED_AGENT_LATEST_TAG "$EXPECTED_AGENT_TAG"
  _endpoint_agent_policy_default EXPECTED_RELEASE_TAG "$EXPECTED_AGENT_TAG"
  _endpoint_agent_policy_default RELEASE_ID "$EXPECTED_AGENT_TAG"
  _endpoint_agent_policy_default EXPECTED_RELEASE_ID "$EXPECTED_AGENT_TAG"

  _endpoint_agent_policy_default EXPECTED_AGENT_VERSION "$(_endpoint_agent_policy_read '.current_bounded_pilot.agent_version')"
  _endpoint_agent_policy_default EXPECTED_RELEASE_WORKFLOW_RUN_ID "$(_endpoint_agent_policy_read '.current_bounded_pilot.workflow_run_id')"
  _endpoint_agent_policy_default EXPECTED_PREVIOUS_RELEASE "$(_endpoint_agent_policy_read '.current_bounded_pilot.previous_release')"
  _endpoint_agent_policy_default EXPECTED_AGENT_COMMIT "$(_endpoint_agent_policy_read '.current_bounded_pilot.source_commit')"
  _endpoint_agent_policy_default EXPECTED_AGENT_SHA256 "$(_endpoint_agent_policy_read '.current_bounded_pilot.endpoint_agent_sha256')"
  _endpoint_agent_policy_default EXPECTED_AGENT_ZIP_SHA256 "$(_endpoint_agent_policy_read '.current_bounded_pilot.endpoint_agent_zip_sha256')"
  _endpoint_agent_policy_default EXPECTED_AGENT_MAX_BYTES "$(_endpoint_agent_policy_read '.current_bounded_pilot.endpoint_agent_max_bytes')"
  _endpoint_agent_policy_default EXPECTED_RELEASE_MANIFEST_SHA256 "$(_endpoint_agent_policy_read '.current_bounded_pilot.release_manifest_sha256')"
  _endpoint_agent_policy_default EXPECTED_INSTALL_PS1_SHA256 "$(_endpoint_agent_policy_read '.current_bounded_pilot.install_ps1_sha256')"
  _endpoint_agent_policy_default EXPECTED_BOOTSTRAP_PS1_SHA256 "$(_endpoint_agent_policy_read '.current_bounded_pilot.bootstrap_package_ps1_sha256')"
  _endpoint_agent_policy_default EXPECTED_SIGNER_THUMBPRINT "$(_endpoint_agent_policy_read '.current_bounded_pilot.signer_thumbprint')"
  _endpoint_agent_policy_default EXPECTED_SIGNER_SHA256_FINGERPRINT "$(_endpoint_agent_policy_read '.current_bounded_pilot.signer_sha256_fingerprint')"
  _endpoint_agent_policy_default EXPECTED_SIGNING_TIER "$(_endpoint_agent_policy_read '.current_bounded_pilot.signing_tier')"
  _endpoint_agent_policy_default EXPECTED_ARTIFACT_HOST_DIGEST "$(_endpoint_agent_policy_read '.current_bounded_pilot.artifact_host_digest')"
  _endpoint_agent_policy_default EXPECTED_ARTIFACT_HOST_IMAGE_REF "$(_endpoint_agent_policy_read '.current_bounded_pilot.artifact_host_image_ref')"
  _endpoint_agent_policy_default ARTIFACT_BASE_URL "$(_endpoint_agent_policy_read '.current_bounded_pilot.artifact_base_url')"
  _endpoint_agent_policy_default ARTIFACT_RELEASE_BASE_URL "$(_endpoint_agent_policy_read '.current_bounded_pilot.artifact_release_base_url')"
  _endpoint_agent_policy_default GITHUB_RELEASE_BASE_URL "$(_endpoint_agent_policy_read '.current_bounded_pilot.github_release_base_url')"
  _endpoint_agent_policy_default BINARY_URL "$GITHUB_RELEASE_BASE_URL/endpoint-agent.exe"
  _endpoint_agent_policy_default MANIFEST_URL "$GITHUB_RELEASE_BASE_URL/release-manifest.json"

  _endpoint_agent_policy_default RELEASE_LINEAGE_WAIVER_REF "$(_endpoint_agent_policy_read '.current_bounded_pilot.waiver_ref')"
  _endpoint_agent_policy_default RELEASE_LINEAGE_WAIVER_FORBIDDEN_CLAIMS "$(_endpoint_agent_policy_csv '.bounded_pilot_waiver.forbidden_claims')"
  _endpoint_agent_policy_default RELEASE_LINEAGE_WAIVER_ACCEPTED_FINDINGS "$(_endpoint_agent_policy_csv '.bounded_pilot_waiver.accepted_findings')"

  _endpoint_agent_policy_default RECENT_RELEASE_WINDOW "$(_endpoint_agent_policy_read '.release_train_policy.recent_release_window')"
  _endpoint_agent_policy_default RECENT_RELEASE_HYGIENE_THRESHOLD "$(_endpoint_agent_policy_read '.release_train_policy.recent_release_hygiene_threshold')"
  _endpoint_agent_policy_default RELEASE_HYGIENE_RECENT_THRESHOLD "$RECENT_RELEASE_HYGIENE_THRESHOLD"
  _endpoint_agent_policy_default AGENT_RELEASE_SERIES_REGEX "$(_endpoint_agent_policy_read '.release_train_policy.recent_release_series_regex')"
  _endpoint_agent_policy_default AGENT_RELEASE_SERIES_LABEL "$(_endpoint_agent_policy_read '.release_train_policy.recent_release_series_label')"
  _endpoint_agent_policy_default AGENT_RELEASE_NEXT_TRUSTED_MINOR "$(_endpoint_agent_policy_read '.release_train_policy.next_trusted_minor')"
  _endpoint_agent_policy_default AGENT_RELEASE_FROZEN_MINOR "$(_endpoint_agent_policy_read '.release_train_policy.frozen_minor')"

  # Release-train graduation policy (Faz 22.6 #1939). The trusted-series regex
  # decouples the live release-train check from the bounded-pilot deploy pin:
  # graduation is asserted against the latest STABLE release matching the
  # trusted series, not an exact pinned tag. trusted_series_regex falls back to
  # recent_release_series_regex when not set, and the SSOT validator fails
  # closed if both are present but unequal.
  _endpoint_agent_policy_default AGENT_RELEASE_TRUSTED_SERIES_REGEX "$(jq -er '.release_train_policy.trusted_series_regex // .release_train_policy.recent_release_series_regex' "$policy_file")"
  _endpoint_agent_policy_default AGENT_RELEASE_TRUSTED_LINEAGE_STARTED_AT "$(_endpoint_agent_policy_read '.release_train_policy.trusted_lineage_started_at')"
  _endpoint_agent_policy_default AGENT_RELEASE_ACTIVE_SERIES_DENSE_THRESHOLD "$(_endpoint_agent_policy_read '.release_train_policy.active_series_dense_threshold')"

  export ENDPOINT_AGENT_RELEASE_POLICY_PATH
}
