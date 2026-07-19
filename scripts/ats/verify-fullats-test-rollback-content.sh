#!/usr/bin/env bash
# Trusted-base verifier for the narrow Full ATS test rollback automation lane.
# It proves that the bot PR is the exact inverse of promotion PR #2636's
# frontend pin plus the explicit ROLLED_BACK marker before Cross-AI grants the
# machine-generated exemption. ATS and permission-service pins are deliberately
# outside the compensator and remain on the current validated baseline.
set -euo pipefail

GH_REPO="${GH_REPO:-Halildeu/platform-k8s-gitops}"
PROMOTION_PR="${PROMOTION_PR:-2636}"
PR_NUMBER="${PR_NUMBER:-}"
PR_HEAD_REF="${PR_HEAD_REF:-}"
PR_HEAD_SHA="${PR_HEAD_SHA:-}"
PR_BASE_SHA="${PR_BASE_SHA:-}"
ATTESTATION_OUTPUT="${ATTESTATION_OUTPUT:-}"
PROMOTION_BASE_SHA="aa93f4743dc8254ce8e22a0317f92db1f5819268"
SOURCE_WORKFLOW=".github/workflows/faz25-fullats-live-browser-acceptance.yml"

[[ "$GH_REPO" == "Halildeu/platform-k8s-gitops" && "$PROMOTION_PR" == "2636" ]] || exit 2
[[ "$PR_NUMBER" =~ ^[0-9]+$ ]] || exit 2
[[ "$PR_HEAD_REF" =~ ^auto-fullats-rollback/faz25-fullats-[0-9]+-[0-9]+$ ]] || exit 2
[[ "$PR_HEAD_SHA" =~ ^[0-9a-f]{40}$ && "$PR_BASE_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ -n "$ATTESTATION_OUTPUT" ]] || exit 2

# Fetch only the exact PR head object graph. The trusted verifier itself was
# already opened from the immutable base checkout before this fetch; no PR-head
# path is checked out, sourced or executed.
git fetch --no-tags origin "pull/${PR_NUMBER}/head"
[[ "$(git rev-parse FETCH_HEAD)" == "$PR_HEAD_SHA" ]] || exit 1

promotion_json="$(gh api "repos/$GH_REPO/pulls/$PROMOTION_PR")"
promotion_merge="$(jq -r '.merge_commit_sha // empty' <<<"$promotion_json")"
promotion_head="$(jq -r '.head.sha // empty' <<<"$promotion_json")"
promotion_body="$(jq -r '.body // empty' <<<"$promotion_json")"
promotion_body="${promotion_body//$'\r'/}"
[[ -n "$(jq -r '.merged_at // empty' <<<"$promotion_json")" ]] || exit 1
[[ "$promotion_merge" == "$PR_BASE_SHA" && "$promotion_head" =~ ^[0-9a-f]{40}$ ]] || exit 1

require_exact_body_line() {
  local expected="$1"
  [[ "$(grep -Fxc -- "$expected" <<<"$promotion_body" || true)" == "1" ]] || exit 1
}

require_exact_body_line "Consultation base: $PROMOTION_BASE_SHA"
require_exact_body_line "Consultation base tip: $PROMOTION_BASE_SHA"
require_exact_body_line "Consultation commit: $promotion_head"
require_exact_body_line "Consultation mode: single"
require_exact_body_line "Consultation class: high-impact"
require_exact_body_line "Verdict: AGREE"
consultation_reason="$(sed -nE 's/^Consultation reason:[[:space:]]*(.{10,})[[:space:]]*$/\1/p' <<<"$promotion_body")"
[[ -n "$consultation_reason" ]] || exit 1
promotion_scope="$(sed -nE 's/^Consultation scope:[[:space:]]*([0-9a-f]{64})[[:space:]]*$/\1/p' <<<"$promotion_body")"
[[ "$promotion_scope" =~ ^[0-9a-f]{64}$ ]] || exit 1
receipt_line="$(grep -E '^Codex receipt: ' <<<"$promotion_body" || true)"
receipt_pattern="Codex receipt: provider=openai; requested=gpt-5\\.6-sol; actual=gpt-5\\.6-sol; effort=xhigh; sandbox=read-only; ephemeral=true; base_tip=$PROMOTION_BASE_SHA; base=$PROMOTION_BASE_SHA; head=$promotion_head; scope=$promotion_scope; verdict=AGREE; ref=https://api\\.github\\.com/repos/Halildeu/platform-k8s-gitops/issues/comments/[1-9][0-9]*; sha256=[0-9a-f]{64}"
if [[ "$(grep -Ec '^Codex receipt: ' <<<"$promotion_body" || true)" != "1" ]] ||
  ! grep -Exq -- "$receipt_pattern" <<<"$receipt_line"; then
  exit 1
fi
receipt_ref="$(sed -nE 's/^.*; ref=(https:\/\/api\.github\.com\/repos\/Halildeu\/platform-k8s-gitops\/issues\/comments\/[1-9][0-9]*); sha256=[0-9a-f]{64}$/\1/p' <<<"$receipt_line")"
receipt_sha256="$(sed -nE 's/^.*; sha256=([0-9a-f]{64})$/\1/p' <<<"$receipt_line")"
evidence_comment="$(gh api "$receipt_ref")"
scope_file="${RUNNER_TEMP:-/tmp}/fullats-promotion-cross-ai-scope-$$.patch"
scope_receipt="$(python3 scripts/ai/prepare_cross_ai_scope.py \
  --derive-only \
  --base-ref "$PROMOTION_BASE_SHA" \
  --base-sha "$PROMOTION_BASE_SHA" \
  --head-sha "$promotion_head" \
  --output "$scope_file")"
[[ "$(jq -r .scope_sha256 <<<"$scope_receipt")" == "$promotion_scope" ]] || exit 1
printf '%s' "$evidence_comment" | python3 scripts/ai/verify_cross_ai_evidence_comment.py \
  --owner Halildeu \
  --body-sha256 "$receipt_sha256" \
  --base-tip-sha "$PROMOTION_BASE_SHA" \
  --base-sha "$PROMOTION_BASE_SHA" \
  --head-sha "$promotion_head" \
  --scope-sha256 "$promotion_scope" \
  --scope-file "$scope_file" \
  --repo-root "$PWD" \
  --model gpt-5.6-sol >/dev/null || exit 1
rm -f "$scope_file"
[[ "$(grep -Eic '^[[:space:]]*(claude|minimax) receipt[[:space:]]*:' <<<"$promotion_body" || true)" == "0" ]] || exit 1

[[ "$(git rev-list --parents -n 1 "$PR_HEAD_SHA" | awk '{print NF - 1}')" == "1" ]] || exit 1
[[ "$(git rev-parse "$PR_HEAD_SHA^")" == "$PR_BASE_SHA" ]] || exit 1
[[ "$(git rev-list --parents -n 1 "$PR_BASE_SHA" | awk '{print NF - 1}')" == "1" ]] || exit 1
[[ "$(git rev-parse "$PR_BASE_SHA^")" == "$PROMOTION_BASE_SHA" ]] || exit 1

promotion_head_tree="$(gh api "repos/$GH_REPO/git/commits/$promotion_head" --jq '.tree.sha')"
promotion_merge_tree="$(gh api "repos/$GH_REPO/git/commits/$promotion_merge" --jq '.tree.sha')"
[[ "$promotion_head_tree" =~ ^[0-9a-f]{40}$ && "$promotion_merge_tree" == "$promotion_head_tree" ]] || exit 1

state_marker="kustomize/overlays/test/fullats-promotion-state.txt"
test_root="kustomize/overlays/test/kustomization.yaml"
changed="$(git -c core.quotePath=true diff --name-only --no-renames "$PR_BASE_SHA...$PR_HEAD_SHA" | sort)"
expected_changed="$(printf '%s\n' "$state_marker" "$test_root" | sort)"
[[ "$changed" == "$expected_changed" ]] || exit 1

[[ "$(git rev-parse "$PROMOTION_BASE_SHA:$test_root")" == \
   "$(git rev-parse "$PR_HEAD_SHA:$test_root")" ]] || exit 1
[[ "$(git show "$PR_HEAD_SHA:$state_marker")" == "ROLLED_BACK" ]] || exit 1

changed_diff_sha256="$(git -c core.quotePath=true diff --binary --full-index --no-renames \
  "$PR_BASE_SHA...$PR_HEAD_SHA" | shasum -a 256 | awk '{print $1}')"
[[ "$changed_diff_sha256" =~ ^[0-9a-f]{64}$ ]] || exit 1

jq -n \
  --arg source "$SOURCE_WORKFLOW" \
  --arg branch "$PR_HEAD_REF" \
  --arg base "$PR_BASE_SHA" \
  --arg head "$PR_HEAD_SHA" \
  --arg promotion_merge "$promotion_merge" \
  --arg promotion_head "$promotion_head" \
  --arg promotion_base "$PROMOTION_BASE_SHA" \
  --arg promotion_scope "$promotion_scope" \
  --arg changed_diff "$changed_diff_sha256" \
  --arg marker "$state_marker" \
  --arg test_root "$test_root" \
  '{
    schema:"fullats-rollback-content-attestation/v1",
    valid:true,
    source:$source,
    branch:$branch,
    base_sha:$base,
    head_sha:$head,
    promotion_pr:2636,
    promotion_merge_sha:$promotion_merge,
    promotion_head_sha:$promotion_head,
    promotion_base_sha:$promotion_base,
    promotion_scope_sha256:$promotion_scope,
    changed_diff_sha256:$changed_diff,
    expected_paths:[$marker,$test_root]
  }' >"$ATTESTATION_OUTPUT"
