#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GENERATOR="$ROOT/scripts/faz22-remote-ops/faz22-6-release-lineage-waiver-package.sh"

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

run_waiver_suite() {
  local script_path="$1" source_flag="$2" suite_name="$3"

  (
    export "$source_flag=1"
    # shellcheck source=/dev/null
    source "$ROOT/$script_path"

    local tmp_root tmp_dir fake_bin issue_json required_findings approved_at expires_at expired_at
    local marker generator_out
    tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
    mkdir -p "$tmp_root"
    tmp_dir="$(mktemp -d "$tmp_root/release-lineage-waiver.XXXXXX")"
    trap 'rm -rf "$tmp_dir"' EXIT

    fake_bin="$tmp_dir/bin"
    mkdir -p "$fake_bin"
    cat >"$fake_bin/gh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "auth" ] && [ "${2:-}" = "status" ]; then
  exit 0
fi
if [ "$#" -eq 7 ] \
  && [ "${1:-}" = "issue" ] \
  && [ "${2:-}" = "view" ] \
  && [ "${3:-}" = "1901" ] \
  && [ "${4:-}" = "-R" ] \
  && [ "${5:-}" = "Halildeu/platform-k8s-gitops" ] \
  && [ "${6:-}" = "--json" ] \
  && [ "${7:-}" = "state,body,title" ]; then
  cat "$FAKE_GH_ISSUE_JSON"
  exit 0
fi
echo "unexpected fake gh invocation: $*" >&2
exit 2
SH
    chmod +x "$fake_bin/gh"

    issue_json="$tmp_dir/release-lineage-issue.json"
    required_findings="GITHUB_RELEASE_IMMUTABLE,GITHUB_RELEASE_DENSE_TRAIN"
    approved_at="$(date -u +%F)"
    expires_at="$(future_date_utc 7)"
    expired_at="$(future_date_utc -1)"

    marker="$tmp_dir/release-lineage-waiver-marker.txt"
    generator_out="$(
      "$GENERATOR" \
        --marker-out "$marker" \
        --release-tag "$EXPECTED_AGENT_TAG" \
        --artifact-host-digest "$EXPECTED_ARTIFACT_HOST_DIGEST" \
        --owner-approved-by "Owner Example" \
        --approved-at "$approved_at" \
        --expires-at "$expires_at"
    )"
    printf '%s\n' "$generator_out" | tee "$tmp_dir/${suite_name}-generator.out"
    grep -q "^marker=$marker$" "$tmp_dir/${suite_name}-generator.out"
    grep -q "^release_tag=$EXPECTED_AGENT_TAG$" "$tmp_dir/${suite_name}-generator.out"
    grep -q "^artifact_host_digest=$EXPECTED_ARTIFACT_HOST_DIGEST$" "$tmp_dir/${suite_name}-generator.out"

    valid_body="$(cat "$marker")"

    jq -n \
      --arg state "OPEN" \
      --arg body "$valid_body" \
      --arg title "fake release-lineage waiver issue" \
      '{state:$state,body:$body,title:$title}' \
      >"$issue_json"

    output="$(
      PATH="$fake_bin:$PATH" \
        FAKE_GH_ISSUE_JSON="$issue_json" \
        RELEASE_LINEAGE_WAIVER_REF="Halildeu/platform-k8s-gitops#1901" \
        check_release_lineage_waiver "$required_findings"
    )"
    printf '%s\n' "$output" | tee "$tmp_dir/${suite_name}-pass.out"
    grep -q '^RELEASE_LINEAGE_WAIVER=bounded_pilot_pass ' "$tmp_dir/${suite_name}-pass.out"
    grep -Eq "accepted_findings=.*GITHUB_RELEASE_IMMUTABLE.*GITHUB_RELEASE_DENSE_TRAIN" "$tmp_dir/${suite_name}-pass.out"

    fenced_example_body="$(cat <<EOF
\`\`\`text
F22_6_RELEASE_LINEAGE_WAIVER: v1
waiver_scope: bounded-pilot-only
release_tag: stale-example
artifact_host_digest: sha256:0000000000000000000000000000000000000000000000000000000000000000
accepted_findings: GITHUB_RELEASE_IMMUTABLE
forbidden_claims: production
owner_approved_by: TBD
approved_at: 2000-01-01
expires_at: 2000-01-02
\`\`\`

$valid_body
EOF
)"
    jq -n \
      --arg state "OPEN" \
      --arg body "$fenced_example_body" \
      --arg title "fake release-lineage waiver with fenced example" \
      '{state:$state,body:$body,title:$title}' \
      >"$issue_json"
    output="$(
      PATH="$fake_bin:$PATH" \
        FAKE_GH_ISSUE_JSON="$issue_json" \
        RELEASE_LINEAGE_WAIVER_REF="Halildeu/platform-k8s-gitops#1901" \
        check_release_lineage_waiver "$required_findings"
    )"
    printf '%s\n' "$output" >"$tmp_dir/${suite_name}-fenced-example.out"
    grep -q '^RELEASE_LINEAGE_WAIVER=bounded_pilot_pass ' "$tmp_dir/${suite_name}-fenced-example.out"

    duplicate_marker_body="$(printf '%s\n\n%s\n' "$valid_body" "$valid_body")"
    jq -n \
      --arg state "OPEN" \
      --arg body "$duplicate_marker_body" \
      --arg title "fake release-lineage waiver duplicate marker" \
      '{state:$state,body:$body,title:$title}' \
      >"$issue_json"
    set +e
    output="$(
      PATH="$fake_bin:$PATH" \
        FAKE_GH_ISSUE_JSON="$issue_json" \
        RELEASE_LINEAGE_WAIVER_REF="Halildeu/platform-k8s-gitops#1901" \
        check_release_lineage_waiver "$required_findings"
    )"
    rc="$?"
    set -e
    if [ "$rc" = "0" ]; then
      echo "expected duplicate release-lineage waiver markers to remain blocked" >&2
      exit 1
    fi
    printf '%s\n' "$output" >"$tmp_dir/${suite_name}-duplicate-marker.out"
    grep -q '^RELEASE_LINEAGE_WAIVER=blocked ' "$tmp_dir/${suite_name}-duplicate-marker.out"
    grep -q 'reason=duplicate-marker' "$tmp_dir/${suite_name}-duplicate-marker.out"

    jq -n \
      --arg state "CLOSED" \
      --arg body "$valid_body" \
      --arg title "fake release-lineage waiver issue closed" \
      '{state:$state,body:$body,title:$title}' \
      >"$issue_json"
    set +e
    output="$(
      PATH="$fake_bin:$PATH" \
        FAKE_GH_ISSUE_JSON="$issue_json" \
        RELEASE_LINEAGE_WAIVER_REF="Halildeu/platform-k8s-gitops#1901" \
        check_release_lineage_waiver "$required_findings"
    )"
    rc="$?"
    set -e
    if [ "$rc" = "0" ]; then
      echo "expected closed release-lineage waiver issue to remain blocked" >&2
      exit 1
    fi
    printf '%s\n' "$output" >"$tmp_dir/${suite_name}-closed.out"
    grep -q '^RELEASE_LINEAGE_WAIVER=blocked ' "$tmp_dir/${suite_name}-closed.out"
    grep -q 'reason=issue-not-open' "$tmp_dir/${suite_name}-closed.out"

    missing_finding_body="${valid_body/accepted_findings: GITHUB_RELEASE_IMMUTABLE,GITHUB_RELEASE_DENSE_TRAIN/accepted_findings: GITHUB_RELEASE_IMMUTABLE}"
    jq -n \
      --arg state "OPEN" \
      --arg body "$missing_finding_body" \
      --arg title "fake release-lineage waiver missing dense-train finding" \
      '{state:$state,body:$body,title:$title}' \
      >"$issue_json"
    set +e
    output="$(
      PATH="$fake_bin:$PATH" \
        FAKE_GH_ISSUE_JSON="$issue_json" \
        RELEASE_LINEAGE_WAIVER_REF="Halildeu/platform-k8s-gitops#1901" \
        check_release_lineage_waiver "$required_findings"
    )"
    rc="$?"
    set -e
    if [ "$rc" = "0" ]; then
      echo "expected missing dense-train accepted finding to remain blocked" >&2
      exit 1
    fi
    printf '%s\n' "$output" >"$tmp_dir/${suite_name}-missing-finding.out"
    grep -q '^RELEASE_LINEAGE_WAIVER=blocked ' "$tmp_dir/${suite_name}-missing-finding.out"
    grep -q 'accepted_findings:GITHUB_RELEASE_DENSE_TRAIN' "$tmp_dir/${suite_name}-missing-finding.out"

    missing_forbidden_body="${valid_body/forbidden_claims: 5-device,50-device,800-device,production,broad-rollout/forbidden_claims: 5-device,50-device,800-device,broad-rollout}"
    jq -n \
      --arg state "OPEN" \
      --arg body "$missing_forbidden_body" \
      --arg title "fake release-lineage waiver missing production forbidden claim" \
      '{state:$state,body:$body,title:$title}' \
      >"$issue_json"
    set +e
    output="$(
      PATH="$fake_bin:$PATH" \
        FAKE_GH_ISSUE_JSON="$issue_json" \
        RELEASE_LINEAGE_WAIVER_REF="Halildeu/platform-k8s-gitops#1901" \
        check_release_lineage_waiver "$required_findings"
    )"
    rc="$?"
    set -e
    if [ "$rc" = "0" ]; then
      echo "expected missing production forbidden claim to remain blocked" >&2
      exit 1
    fi
    printf '%s\n' "$output" >"$tmp_dir/${suite_name}-missing-forbidden.out"
    grep -q '^RELEASE_LINEAGE_WAIVER=blocked ' "$tmp_dir/${suite_name}-missing-forbidden.out"
    grep -q 'forbidden_claims:production' "$tmp_dir/${suite_name}-missing-forbidden.out"

    placeholder_owner_body="${valid_body/owner_approved_by: Owner Example/owner_approved_by: TBD}"
    jq -n \
      --arg state "OPEN" \
      --arg body "$placeholder_owner_body" \
      --arg title "fake release-lineage waiver placeholder owner" \
      '{state:$state,body:$body,title:$title}' \
      >"$issue_json"
    set +e
    output="$(
      PATH="$fake_bin:$PATH" \
        FAKE_GH_ISSUE_JSON="$issue_json" \
        RELEASE_LINEAGE_WAIVER_REF="Halildeu/platform-k8s-gitops#1901" \
        check_release_lineage_waiver "$required_findings"
    )"
    rc="$?"
    set -e
    if [ "$rc" = "0" ]; then
      echo "expected placeholder release-lineage waiver owner to remain blocked" >&2
      exit 1
    fi
    printf '%s\n' "$output" >"$tmp_dir/${suite_name}-placeholder-owner.out"
    grep -q '^RELEASE_LINEAGE_WAIVER=blocked ' "$tmp_dir/${suite_name}-placeholder-owner.out"
    grep -q 'owner_approved_by' "$tmp_dir/${suite_name}-placeholder-owner.out"

    named_owner_body="${valid_body/owner_approved_by: Owner Example/owner_approved_by: named-owner}"
    jq -n \
      --arg state "OPEN" \
      --arg body "$named_owner_body" \
      --arg title "fake release-lineage waiver literal named-owner placeholder" \
      '{state:$state,body:$body,title:$title}' \
      >"$issue_json"
    set +e
    output="$(
      PATH="$fake_bin:$PATH" \
        FAKE_GH_ISSUE_JSON="$issue_json" \
        RELEASE_LINEAGE_WAIVER_REF="Halildeu/platform-k8s-gitops#1901" \
        check_release_lineage_waiver "$required_findings"
    )"
    rc="$?"
    set -e
    if [ "$rc" = "0" ]; then
      echo "expected literal named-owner release-lineage waiver owner to remain blocked" >&2
      exit 1
    fi
    printf '%s\n' "$output" >"$tmp_dir/${suite_name}-named-owner.out"
    grep -q '^RELEASE_LINEAGE_WAIVER=blocked ' "$tmp_dir/${suite_name}-named-owner.out"
    grep -q 'owner_approved_by' "$tmp_dir/${suite_name}-named-owner.out"

    expired_body="${valid_body/expires_at: $expires_at/expires_at: $expired_at}"
    jq -n \
      --arg state "OPEN" \
      --arg body "$expired_body" \
      --arg title "fake release-lineage waiver expired" \
      '{state:$state,body:$body,title:$title}' \
      >"$issue_json"
    set +e
    output="$(
      PATH="$fake_bin:$PATH" \
        FAKE_GH_ISSUE_JSON="$issue_json" \
        RELEASE_LINEAGE_WAIVER_REF="Halildeu/platform-k8s-gitops#1901" \
        check_release_lineage_waiver "$required_findings"
    )"
    rc="$?"
    set -e
    if [ "$rc" = "0" ]; then
      echo "expected expired release-lineage waiver to remain blocked" >&2
      exit 1
    fi
    printf '%s\n' "$output" >"$tmp_dir/${suite_name}-expired.out"
    grep -q '^RELEASE_LINEAGE_WAIVER=blocked ' "$tmp_dir/${suite_name}-expired.out"
    grep -q 'expires_at-expired' "$tmp_dir/${suite_name}-expired.out"

    date_order_body="${valid_body/approved_at: $approved_at/approved_at: $(future_date_utc 2)}"
    date_order_body="${date_order_body/expires_at: $expires_at/expires_at: $(future_date_utc 1)}"
    jq -n \
      --arg state "OPEN" \
      --arg body "$date_order_body" \
      --arg title "fake release-lineage waiver invalid date order" \
      '{state:$state,body:$body,title:$title}' \
      >"$issue_json"
    set +e
    output="$(
      PATH="$fake_bin:$PATH" \
        FAKE_GH_ISSUE_JSON="$issue_json" \
        RELEASE_LINEAGE_WAIVER_REF="Halildeu/platform-k8s-gitops#1901" \
        check_release_lineage_waiver "$required_findings"
    )"
    rc="$?"
    set -e
    if [ "$rc" = "0" ]; then
      echo "expected release-lineage waiver with approved_at after expires_at to remain blocked" >&2
      exit 1
    fi
    printf '%s\n' "$output" >"$tmp_dir/${suite_name}-date-order.out"
    grep -q '^RELEASE_LINEAGE_WAIVER=blocked ' "$tmp_dir/${suite_name}-date-order.out"
    grep -q 'approved_at-after-expires_at' "$tmp_dir/${suite_name}-date-order.out"

    set +e
    "$GENERATOR" \
      --marker-out "$tmp_dir/bad-owner-marker.txt" \
      --release-tag "$EXPECTED_AGENT_TAG" \
      --artifact-host-digest "$EXPECTED_ARTIFACT_HOST_DIGEST" \
      --owner-approved-by "TBD" \
      --approved-at "$approved_at" \
      --expires-at "$expires_at" >"$tmp_dir/${suite_name}-generator-bad-owner.out" 2>&1
    rc="$?"
    set -e
    if [ "$rc" = "0" ]; then
      echo "expected release-lineage waiver generator to reject placeholder owner" >&2
      exit 1
    fi
    grep -q 'owner-approved-by' "$tmp_dir/${suite_name}-generator-bad-owner.out"

    set +e
    "$GENERATOR" \
      --marker-out "$tmp_dir/bad-digest-marker.txt" \
      --release-tag "$EXPECTED_AGENT_TAG" \
      --artifact-host-digest "sha256:BAD" \
      --owner-approved-by "Owner Example" \
      --approved-at "$approved_at" \
      --expires-at "$expires_at" >"$tmp_dir/${suite_name}-generator-bad-digest.out" 2>&1
    rc="$?"
    set -e
    if [ "$rc" = "0" ]; then
      echo "expected release-lineage waiver generator to reject invalid digest" >&2
      exit 1
    fi
    grep -q 'artifact-host-digest' "$tmp_dir/${suite_name}-generator-bad-digest.out"
  )
}

run_waiver_suite \
  "scripts/faz22-remote-ops/faz22-6-release-lineage-audit.sh" \
  "F22_6_RELEASE_LINEAGE_AUDIT_SOURCE_ONLY" \
  "release-lineage-audit"

run_waiver_suite \
  "scripts/faz22-remote-ops/faz22-6-completion-audit.sh" \
  "F22_6_COMPLETION_AUDIT_SOURCE_ONLY" \
  "completion-audit"

echo "release-lineage-waiver-gate-ok"
