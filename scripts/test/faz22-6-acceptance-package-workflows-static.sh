#!/usr/bin/env bash
# Static and smoke guards for the artifact-only Faz 22.6 acceptance package workflows.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
B1_WORKFLOW="$ROOT/.github/workflows/faz22-6-b1-4-acceptance-package.yml"
VIEW_ONLY_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-engineering-evidence-package.yml"
B1_HELPER="$ROOT/scripts/faz22-remote-ops/faz22-6-b1-4-acceptance-package.sh"
VIEW_ONLY_HELPER="$ROOT/scripts/faz22-remote-ops/faz22-6-view-only-evidence-package.sh"

future_date_utc() {
  local days="$1"
  if date -u -d "+$days days" +%F >/dev/null 2>&1; then
    date -u -d "+$days days" +%F
    return
  fi
  case "$days" in
    -*) date -u -v"${days}"d +%F ;;
    *) date -u -v+"$days"d +%F ;;
  esac
}

require_file() {
  local path="$1"
  [ -f "$path" ] || {
    echo "missing required file: $path" >&2
    exit 1
  }
}

require_grep() {
  local pattern="$1" path="$2"
  grep -Fq -- "$pattern" "$path" || {
    echo "missing expected pattern in $path: $pattern" >&2
    exit 1
  }
}

for path in "$B1_WORKFLOW" "$VIEW_ONLY_WORKFLOW" "$B1_HELPER" "$VIEW_ONLY_HELPER"; do
  require_file "$path"
done

bash -n "$B1_HELPER" "$VIEW_ONLY_HELPER"

require_grep "permissions:" "$B1_WORKFLOW"
require_grep "contents: read" "$B1_WORKFLOW"
require_grep "workflow_dispatch:" "$B1_WORKFLOW"
require_grep "PREPARE_FAZ22_6_B1_4_ACCEPTANCE_PACKAGE" "$B1_WORKFLOW"
require_grep "ACK_REAL_HARDWARE_ATTESTATION_EVIDENCE_EXISTS" "$B1_WORKFLOW"
require_grep "ACK_BOUNDED_RISK_OWNER_ACCEPTED" "$B1_WORKFLOW"
require_grep "scripts/faz22-remote-ops/faz22-6-b1-4-acceptance-package.sh" "$B1_WORKFLOW"
require_grep "actions/upload-artifact@v4" "$B1_WORKFLOW"
require_grep "writes_github_issues: false" "$B1_WORKFLOW"
require_grep "contains_secrets: false" "$B1_WORKFLOW"

require_grep "permissions:" "$VIEW_ONLY_WORKFLOW"
require_grep "contents: read" "$VIEW_ONLY_WORKFLOW"
require_grep "workflow_dispatch:" "$VIEW_ONLY_WORKFLOW"
require_grep "PREPARE_FAZ22_6_VIEW_ONLY_ENGINEERING_EVIDENCE_PACKAGE" "$VIEW_ONLY_WORKFLOW"
require_grep "ACK_VIEW_ONLY_ENGINEERING_CONTROLS_VERIFIED" "$VIEW_ONLY_WORKFLOW"
require_grep "scripts/faz22-remote-ops/faz22-6-view-only-evidence-package.sh" "$VIEW_ONLY_WORKFLOW"
require_grep "--recording-mode disabled" "$VIEW_ONLY_WORKFLOW"
require_grep 'canonical_manifest="$(jq -cS . "$manifest")"' "$VIEW_ONLY_WORKFLOW"
require_grep 'manifest_sha="$(printf' "$VIEW_ONLY_WORKFLOW"
require_grep "actions/upload-artifact@v4" "$VIEW_ONLY_WORKFLOW"
require_grep "writes_github_issues: false" "$VIEW_ONLY_WORKFLOW"
require_grep "contains_secrets: false" "$VIEW_ONLY_WORKFLOW"

for path in "$B1_WORKFLOW" "$VIEW_ONLY_WORKFLOW"; do
  forbidden="$(
    grep -nE 'gh issue (edit|comment)|kubectl |secrets\.|GH_TOKEN|issues: write|pull-requests: write|contents: write' "$path" || true
  )"
  if [ -n "$forbidden" ]; then
    echo "forbidden mutating or secret-bearing pattern in $path:" >&2
    printf '%s\n' "$forbidden" >&2
    exit 1
  fi
done

tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
mkdir -p "$tmp_root"
tmp_dir="$(mktemp -d "$tmp_root/faz22-6-acceptance-workflows.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

approved_at="$(date -u +%F)"
expires_at="$(future_date_utc 7)"

"$B1_HELPER" \
  --mode hardware \
  --marker-out "$tmp_dir/b1-4-hardware-marker.txt" \
  --owner-approved-by "Owner Example" \
  --approved-at "$approved_at" >/dev/null
grep -Fq "F22_6_B1_4_HARDWARE_ATTESTATION_ACCEPTANCE: v1" "$tmp_dir/b1-4-hardware-marker.txt"

"$B1_HELPER" \
  --mode risk \
  --marker-out "$tmp_dir/b1-4-risk-marker.txt" \
  --owner-approved-by "Owner Example" \
  --approved-at "$approved_at" \
  --expires-at "$expires_at" >/dev/null
grep -Fq "F22_6_B1_4_RISK_ACCEPTANCE: v1" "$tmp_dir/b1-4-risk-marker.txt"

F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1 "$VIEW_ONLY_HELPER" \
  --manifest-out "$tmp_dir/view-only-manifest.json" \
  --marker-out "$tmp_dir/view-only-marker.txt" \
  --evidence-url "file://$tmp_dir/view-only-manifest.json" \
  --pilot-device "AgentPc2" \
  --session-id "view-only-session-static-guard" \
  --recording-mode disabled \
  --d10-fail-closed pass \
  --dlp-mask-policy pass \
  --local-abort pass \
  --active-indicator pass \
  --viewer-path-decision fanout-proven \
  --owner-approved-by "Owner Example" \
  --approved-at "$approved_at" \
  --expires-at "$expires_at" >/dev/null
jq -e '.schema_version == "faz22.6-view-only-evidence-v2" and .recording_mode == "disabled"' "$tmp_dir/view-only-manifest.json" >/dev/null
grep -Fq "F22_6_VIEW_ONLY_ENGINEERING: v2" "$tmp_dir/view-only-marker.txt"

echo "faz22-6-acceptance-package-workflows-static-ok"
