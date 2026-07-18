#!/usr/bin/env bash
# Trusted-base verifier for the narrow Full ATS test rollback automation lane.
# It proves that the bot PR is the exact inverse of promotion PR #2617's three
# runtime bindings plus the explicit ROLLED_BACK marker before Cross-AI grants
# the machine-generated exemption.
set -euo pipefail

GH_REPO="${GH_REPO:-Halildeu/platform-k8s-gitops}"
PROMOTION_PR="${PROMOTION_PR:-2617}"
PR_NUMBER="${PR_NUMBER:-}"
PR_HEAD_REF="${PR_HEAD_REF:-}"
PR_HEAD_SHA="${PR_HEAD_SHA:-}"
PR_BASE_SHA="${PR_BASE_SHA:-}"
ATTESTATION_OUTPUT="${ATTESTATION_OUTPUT:-}"
PROMOTION_BASE_SHA="5cec8606538a70388b1d02c59ce22ff9cc68ef9e"
SOURCE_WORKFLOW=".github/workflows/faz25-fullats-live-browser-acceptance.yml"

[[ "$GH_REPO" == "Halildeu/platform-k8s-gitops" && "$PROMOTION_PR" == "2617" ]] || exit 2
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
require_exact_body_line "Consultation commit: $promotion_head"
require_exact_body_line "Consultation mode: none"
consultation_reason="$(sed -nE 's/^Consultation reason:[[:space:]]*(.{10,})[[:space:]]*$/\1/p' <<<"$promotion_body")"
[[ -n "$consultation_reason" ]] || exit 1
promotion_scope="$(sed -nE 's/^Consultation scope:[[:space:]]*([0-9a-f]{64})[[:space:]]*$/\1/p' <<<"$promotion_body")"
[[ "$promotion_scope" =~ ^[0-9a-f]{64}$ ]] || exit 1
for receipt_label in "Claude receipt" "MiniMax receipt" "Codex receipt"; do
  [[ "$(grep -Fc "$receipt_label:" <<<"$promotion_body" || true)" == "0" ]] || exit 1
done

[[ "$(git rev-list --parents -n 1 "$PR_HEAD_SHA" | awk '{print NF - 1}')" == "1" ]] || exit 1
[[ "$(git rev-parse "$PR_HEAD_SHA^")" == "$PR_BASE_SHA" ]] || exit 1
[[ "$(git rev-list --parents -n 1 "$PR_BASE_SHA" | awk '{print NF - 1}')" == "1" ]] || exit 1
[[ "$(git rev-parse "$PR_BASE_SHA^")" == "$PROMOTION_BASE_SHA" ]] || exit 1

promotion_head_tree="$(gh api "repos/$GH_REPO/git/commits/$promotion_head" --jq '.tree.sha')"
promotion_merge_tree="$(gh api "repos/$GH_REPO/git/commits/$promotion_merge" --jq '.tree.sha')"
[[ "$promotion_head_tree" =~ ^[0-9a-f]{40}$ && "$promotion_merge_tree" == "$promotion_head_tree" ]] || exit 1

activation="kustomize/overlays/test/activation/ats-interview-evidence/kustomization.yaml"
state_marker="kustomize/overlays/test/fullats-promotion-state.txt"
test_root="kustomize/overlays/test/kustomization.yaml"
smoke="scripts/ats/d29-smoke.sh"
changed="$(git -c core.quotePath=true diff --name-only --no-renames "$PR_BASE_SHA...$PR_HEAD_SHA" | sort)"
expected_changed="$(printf '%s\n' "$activation" "$state_marker" "$test_root" "$smoke" | sort)"
[[ "$changed" == "$expected_changed" ]] || exit 1

for restored_path in "$activation" "$test_root" "$smoke"; do
  [[ "$(git rev-parse "$PROMOTION_BASE_SHA:$restored_path")" == \
     "$(git rev-parse "$PR_HEAD_SHA:$restored_path")" ]] || exit 1
done
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
  --arg activation "$activation" \
  --arg marker "$state_marker" \
  --arg test_root "$test_root" \
  --arg smoke "$smoke" \
  '{
    schema:"fullats-rollback-content-attestation/v1",
    valid:true,
    source:$source,
    branch:$branch,
    base_sha:$base,
    head_sha:$head,
    promotion_pr:2617,
    promotion_merge_sha:$promotion_merge,
    promotion_head_sha:$promotion_head,
    promotion_base_sha:$promotion_base,
    promotion_scope_sha256:$promotion_scope,
    changed_diff_sha256:$changed_diff,
    expected_paths:[$activation,$marker,$test_root,$smoke]
  }' >"$ATTESTATION_OUTPUT"
