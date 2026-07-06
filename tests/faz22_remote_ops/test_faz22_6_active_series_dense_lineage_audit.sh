#!/usr/bin/env bash
# Offline regression test for the active trusted-series dense lineage audit.
#
# The release-train verdict intentionally flags active_count >= threshold as
# hygiene. This test proves the non-waiver resolver accepts only a contiguous,
# signed, checksummed release chain, while allowing the patch-zero seed release
# to remain immutable=false when it exactly matches the trusted-lineage
# boundary.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

export AGENT_REPO='Halildeu/platform-agent'
export AGENT_RELEASE_TRUSTED_SERIES_REGEX='^v0\.3\.'
export AGENT_RELEASE_SERIES_LABEL='v0.3'
export AGENT_RELEASE_TRUSTED_LINEAGE_STARTED_AT='2026-06-24T09:04:29Z'
export AGENT_RELEASE_ACTIVE_SERIES_DENSE_THRESHOLD='8'
export EXPECTED_SIGNER_THUMBPRINT='D68F4F530137EB65CE44E3405E82B46205E753E5'
export EXPECTED_SIGNING_TIER='trusted-internal-ca'
export ACTIVE_SERIES_DENSE_SKIP_TAG_REF=1
export F22_6_RELEASE_LINEAGE_AUDIT_SOURCE_ONLY=1
# shellcheck source=/dev/null
source "$ROOT/scripts/faz22-remote-ops/faz22-6-release-lineage-audit.sh"

tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
mkdir -p "$tmp_root"
tmp_dir="$(mktemp -d "$tmp_root/active-series-dense-lineage.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

hex64() {
  printf '%064x' "$1"
}

hex40() {
  printf '%040x' "$1"
}

write_release_evidence() {
  local dir="$1" patch="$2" previous="$3"
  local tag="v0.3.$patch"
  local release_dir="$dir/$tag"
  local source_commit agent_sha zip_sha artifact_hex artifact_digest
  mkdir -p "$release_dir"
  source_commit="$(hex40 "$((1000 + patch))")"
  agent_sha="$(hex64 "$((2000 + patch))")"
  zip_sha="$(hex64 "$((3000 + patch))")"
  artifact_hex="$(hex64 "$((4000 + patch))")"
  artifact_digest="sha256:$artifact_hex"

  jq -n \
    --arg release_tag "$tag" \
    --arg previous_release "$previous" \
    --arg source_commit "$source_commit" \
    --arg workflow_run_id "$((28000000000 + patch))" \
    --arg agent_sha "$agent_sha" \
    --arg zip_sha "$zip_sha" \
    --arg signer_thumbprint "$EXPECTED_SIGNER_THUMBPRINT" \
    --arg signing_tier "$EXPECTED_SIGNING_TIER" \
    --arg artifact_digest "$artifact_digest" \
    --arg artifact_ref "ghcr.io/halildeu/platform-agent-artifacts:$tag@$artifact_digest" \
    '{
      release_tag: $release_tag,
      previous_release: $previous_release,
      release_class: "rollout-candidate",
      source_commit: $source_commit,
      workflow_run_id: $workflow_run_id,
      endpoint_agent_sha256: $agent_sha,
      endpoint_agent_zip_sha256: $zip_sha,
      signer_thumbprint: $signer_thumbprint,
      signing_tier: $signing_tier,
      artifact_host_digest: $artifact_digest,
      artifact_host_image_ref: $artifact_ref
    }' >"$release_dir/release-manifest.json"

  cat >"$release_dir/SHA256SUMS" <<EOF
$agent_sha  endpoint-agent.exe
$(hex64 "$((5000 + patch))")  bootstrap-package.ps1
$(hex64 "$((6000 + patch))")  install.ps1
$(hex64 "$((7000 + patch))")  uninstall.ps1
$zip_sha  EndpointAgent.zip
$(hex64 "$((8000 + patch))")  EndpointAgent.zip.sha256
$(hex64 "$((9000 + patch))")  release-manifest.json
EOF
}

build_releases_json() {
  local json='[]' patch tag published immutable previous
  for patch in 0 1 2 3 4 5 6 7; do
    tag="v0.3.$patch"
    if [ "$patch" -eq 0 ]; then
      published="$AGENT_RELEASE_TRUSTED_LINEAGE_STARTED_AT"
      immutable=false
      previous='v0.2.28'
    else
      published="2026-06-24T1${patch}:00:00Z"
      immutable=true
      previous="v0.3.$((patch - 1))"
    fi
    write_release_evidence "$ACTIVE_SERIES_DENSE_EVIDENCE_DIR" "$patch" "$previous"
    json="$(printf '%s\n' "$json" | jq \
      --arg tag "$tag" \
      --arg published "$published" \
      --argjson immutable "$immutable" \
      '. + [{
        tagName: $tag,
        isLatest: false,
        isDraft: false,
        isPrerelease: false,
        isImmutable: $immutable,
        publishedAt: $published
      }]')"
  done
  printf '%s' "$json"
}

export ACTIVE_SERIES_DENSE_EVIDENCE_DIR="$tmp_dir/evidence-pass"
mkdir -p "$ACTIVE_SERIES_DENSE_EVIDENCE_DIR"
releases_json="$(build_releases_json)"

out_pass="$tmp_dir/pass.out"
active_series_dense_lineage_audit "$releases_json" >"$out_pass"
grep -q '^ACTIVE_SERIES_DENSE_LINEAGE_AUDIT=pass ' "$out_pass" \
  || fail "expected dense lineage pass; output:
$(cat "$out_pass")"
grep -q 'active_count=8 threshold=8 first=v0.3.0 latest=v0.3.7 seed_nonimmutable_allowed=1' "$out_pass" \
  || fail "expected seed immutable exception and full v0.3.0..v0.3.7 chain"

bad_immutable_json="$(printf '%s\n' "$releases_json" | jq 'map(if .tagName == "v0.3.4" then .isImmutable = false else . end)')"
set +e
active_series_dense_lineage_audit "$bad_immutable_json" >"$tmp_dir/non-seed-immutable.out"
rc="$?"
set -e
[ "$rc" != "0" ] || fail "expected non-seed immutable=false to block"
grep -q 'tag=v0.3.4 .*reason=non-seed-release-not-immutable' "$tmp_dir/non-seed-immutable.out" \
  || fail "expected non-seed immutable failure; output:
$(cat "$tmp_dir/non-seed-immutable.out")"

nonstable_json="$(printf '%s\n' "$releases_json" | jq 'map(if .tagName == "v0.3.7" then .isPrerelease = true else . end)')"
set +e
active_series_dense_lineage_audit "$nonstable_json" >"$tmp_dir/nonstable-dense.out"
rc="$?"
set -e
[ "$rc" != "0" ] || fail "expected dense train containing prerelease to block"
grep -q 'active_count=8 stable_count=7 reason=trusted-series-dense-includes-draft-or-prerelease' "$tmp_dir/nonstable-dense.out" \
  || fail "expected nonstable dense failure; output:
$(cat "$tmp_dir/nonstable-dense.out")"

export ACTIVE_SERIES_DENSE_EVIDENCE_DIR="$tmp_dir/evidence-chain-break"
mkdir -p "$ACTIVE_SERIES_DENSE_EVIDENCE_DIR"
chain_break_json="$(build_releases_json)"
jq '.previous_release = "v0.3.3"' \
  "$ACTIVE_SERIES_DENSE_EVIDENCE_DIR/v0.3.5/release-manifest.json" \
  >"$ACTIVE_SERIES_DENSE_EVIDENCE_DIR/v0.3.5/release-manifest.json.tmp"
mv "$ACTIVE_SERIES_DENSE_EVIDENCE_DIR/v0.3.5/release-manifest.json.tmp" \
  "$ACTIVE_SERIES_DENSE_EVIDENCE_DIR/v0.3.5/release-manifest.json"

set +e
active_series_dense_lineage_audit "$chain_break_json" >"$tmp_dir/chain-break.out"
rc="$?"
set -e
[ "$rc" != "0" ] || fail "expected previous_release chain break to block"
grep -q 'tag=v0.3.5 previous_release=v0.3.3 expected_previous=v0.3.4 reason=previous-release-chain-break' "$tmp_dir/chain-break.out" \
  || fail "expected previous_release chain-break failure; output:
$(cat "$tmp_dir/chain-break.out")"

echo "active-series-dense-lineage-audit-ok"
