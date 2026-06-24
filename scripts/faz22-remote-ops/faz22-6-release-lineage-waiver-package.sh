#!/usr/bin/env bash
# Generate the bounded-pilot Faz 22.6 release-lineage waiver marker expected by
# faz22-6-release-lineage-audit.sh and faz22-6-completion-audit.sh.
#
# This helper does not approve #1901 and does not mutate GitHub release state.
# It only formats already-approved metadata into the fail-closed marker shape.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/faz22-remote-ops/endpoint-agent-release-policy.sh
source "$SCRIPT_DIR/endpoint-agent-release-policy.sh"
endpoint_agent_release_policy_load "$REPO_ROOT"

WAIVER_SCOPE="bounded-pilot-only"
ACCEPTED_FINDINGS="$RELEASE_LINEAGE_WAIVER_ACCEPTED_FINDINGS"
FORBIDDEN_CLAIMS="$RELEASE_LINEAGE_WAIVER_FORBIDDEN_CLAIMS"

MARKER_OUT=""
RELEASE_TAG="${EXPECTED_AGENT_TAG}"
ARTIFACT_HOST_DIGEST="${EXPECTED_ARTIFACT_HOST_DIGEST}"
OWNER_APPROVED_BY=""
APPROVED_AT=""
EXPIRES_AT=""

usage() {
  cat <<'EOF'
Usage:
  faz22-6-release-lineage-waiver-package.sh \
    --marker-out PATH \
    --release-tag RELEASE_TAG \
    --artifact-host-digest sha256:<64 hex> \
    --owner-approved-by NAMED_OWNER \
    --approved-at YYYY-MM-DD \
    --expires-at YYYY-MM-DD

This helper emits marker text only. It does not write to #1901, does not
approve a waiver, and does not permit broad rollout language.
EOF
}

die() {
  printf 'release-lineage-waiver-package: %s\n' "$*" >&2
  exit 2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --marker-out) [ "$#" -ge 2 ] || die "--marker-out needs a value"; MARKER_OUT="$2"; shift 2 ;;
    --release-tag) [ "$#" -ge 2 ] || die "--release-tag needs a value"; RELEASE_TAG="$2"; shift 2 ;;
    --artifact-host-digest) [ "$#" -ge 2 ] || die "--artifact-host-digest needs a value"; ARTIFACT_HOST_DIGEST="$2"; shift 2 ;;
    --owner-approved-by) [ "$#" -ge 2 ] || die "--owner-approved-by needs a value"; OWNER_APPROVED_BY="$2"; shift 2 ;;
    --approved-at) [ "$#" -ge 2 ] || die "--approved-at needs a value"; APPROVED_AT="$2"; shift 2 ;;
    --expires-at) [ "$#" -ge 2 ] || die "--expires-at needs a value"; EXPIRES_AT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

require_nonempty() {
  local name="$1" value="$2"
  [ -n "$value" ] || die "$name is required"
}

require_no_control_chars() {
  local name="$1" value="$2"
  if printf '%s' "$value" | LC_ALL=C grep -q '[[:cntrl:]]'; then
    die "$name must not contain control characters"
  fi
}

owner_is_invalid() {
  local owner_lc
  owner_lc="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [ -z "$owner_lc" ] && return 0
  case "$owner_lc" in
    tbd|none|n/a|na|placeholder|owner|named-owner) return 0 ;;
  esac
  return 1
}

valid_iso_date() {
  [[ "$1" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]
}

require_nonempty "marker-out" "$MARKER_OUT"
require_nonempty "release-tag" "$RELEASE_TAG"
require_nonempty "artifact-host-digest" "$ARTIFACT_HOST_DIGEST"
require_nonempty "owner-approved-by" "$OWNER_APPROVED_BY"
require_nonempty "approved-at" "$APPROVED_AT"
require_nonempty "expires-at" "$EXPIRES_AT"

for value_name in RELEASE_TAG ARTIFACT_HOST_DIGEST OWNER_APPROVED_BY; do
  require_no_control_chars "$value_name" "${!value_name}"
done

[[ "$RELEASE_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] \
  || die "release-tag must look like vMAJOR.MINOR.PATCH"
[[ "$ARTIFACT_HOST_DIGEST" =~ ^sha256:[a-f0-9]{64}$ ]] \
  || die "artifact-host-digest must be sha256:<64 lowercase hex>"
owner_is_invalid "$OWNER_APPROVED_BY" \
  && die "owner-approved-by must be a named owner, not a placeholder"
valid_iso_date "$APPROVED_AT" || die "approved-at must be YYYY-MM-DD"
valid_iso_date "$EXPIRES_AT" || die "expires-at must be YYYY-MM-DD"

today="$(date -u +%F)"
if [[ "$APPROVED_AT" > "$EXPIRES_AT" ]]; then
  die "approved-at must not be after expires-at"
fi
if [[ "$APPROVED_AT" > "$today" ]]; then
  die "approved-at must not be in the future"
fi
if [[ "$EXPIRES_AT" < "$today" ]]; then
  die "expires-at must not be expired"
fi

mkdir -p "$(dirname "$MARKER_OUT")"

cat >"$MARKER_OUT" <<EOF
F22_6_RELEASE_LINEAGE_WAIVER: v1
waiver_scope: $WAIVER_SCOPE
release_tag: $RELEASE_TAG
artifact_host_digest: $ARTIFACT_HOST_DIGEST
accepted_findings: $ACCEPTED_FINDINGS
forbidden_claims: $FORBIDDEN_CLAIMS
owner_approved_by: $OWNER_APPROVED_BY
approved_at: $APPROVED_AT
expires_at: $EXPIRES_AT
EOF

printf 'marker=%s\n' "$MARKER_OUT"
printf 'release_tag=%s\n' "$RELEASE_TAG"
printf 'artifact_host_digest=%s\n' "$ARTIFACT_HOST_DIGEST"
