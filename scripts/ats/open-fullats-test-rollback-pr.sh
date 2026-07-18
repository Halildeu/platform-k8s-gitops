#!/usr/bin/env bash
# Faz 25 Full ATS canlı kabulü düşerse bu promotion'ın yeni ATS + frontend
# pinlerini reviewed-base artifactlerine döndüren ve state marker'ını ROLLED_BACK
# yapan test-only compensator. Permission-service mevcut doğrulanmış baseline'da
# kalır; telafi sonucu merge sonrasında canlı olarak yeniden kanıtlanır.
set -euo pipefail

GH_REPO="${GH_REPO:-Halildeu/platform-k8s-gitops}"
PROMOTION_PR="${PROMOTION_PR:-2685}"
FAILED_SHA="${FAILED_SHA:-}"
RUN_ID="${RUN_ID:-0}"
RUN_ATTEMPT="${RUN_ATTEMPT:-1}"
SERVER_URL="${GITHUB_SERVER_URL:-https://github.com}"
BOT_NAME="platform-gitops-automation[bot]"
BOT_EMAIL="platform-gitops-automation[bot]@users.noreply.github.com"
PROMOTION_BASE_SHA="6d77fbe809645cfa6e4b1c99481791070c5933d3"

: "${GH_TOKEN:?GH_TOKEN must be a platform-gitops-automation GitHub App token}"
[[ "$GH_REPO" == "Halildeu/platform-k8s-gitops" ]] || {
  echo "[fullats-rollback] unexpected repository" >&2
  exit 2
}
[[ "$PROMOTION_PR" == "2685" ]] || {
  echo "[fullats-rollback] unexpected promotion PR" >&2
  exit 2
}
[[ "$FAILED_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "[fullats-rollback] failed workflow SHA is invalid" >&2
  exit 2
}
[[ "$RUN_ID" =~ ^[0-9]+$ && "$RUN_ATTEMPT" =~ ^[0-9]+$ ]] || {
  echo "[fullats-rollback] run identity is invalid" >&2
  exit 2
}
for command in awk gh git grep jq kustomize python3; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "[fullats-rollback] missing command: $command" >&2
    exit 2
  }
done

promotion_json="$(gh api "repos/$GH_REPO/pulls/$PROMOTION_PR")"
merge_sha="$(jq -r '.merge_commit_sha // empty' <<<"$promotion_json")"
merged_at="$(jq -r '.merged_at // empty' <<<"$promotion_json")"
promotion_head="$(jq -r '.head.sha // empty' <<<"$promotion_json")"
promotion_body="$(jq -r '.body // empty' <<<"$promotion_json")"
promotion_body="${promotion_body//$'\r'/}"
[[ -n "$merged_at" && "$merge_sha" =~ ^[0-9a-f]{40}$ ]] || {
  echo "[fullats-rollback] promotion PR is not merged" >&2
  exit 1
}
[[ "$promotion_head" =~ ^[0-9a-f]{40}$ ]] || {
  echo "[fullats-rollback] promotion PR head is invalid" >&2
  exit 1
}

require_exact_body_line() {
  local expected="$1"
  local count
  count="$(grep -Fxc -- "$expected" <<<"$promotion_body" || true)"
  [[ "$count" == "1" ]] || {
    echo "[fullats-rollback] promotion review binding line is missing or duplicated" >&2
    exit 1
  }
}

require_exact_body_line "Consultation base: $PROMOTION_BASE_SHA"
require_exact_body_line "Consultation commit: $promotion_head"
require_exact_body_line "Consultation mode: dual"
require_exact_body_line "Verdict: AGREE"
consultation_reason="$(sed -nE 's/^Consultation reason:[[:space:]]*(.{10,})[[:space:]]*$/\1/p' <<<"$promotion_body")"
[[ -n "$consultation_reason" ]] || {
  echo "[fullats-rollback] promotion consultation reason is missing or too short" >&2
  exit 1
}
consultation_scope="$(sed -nE 's/^Consultation scope:[[:space:]]*([0-9a-f]{64})[[:space:]]*$/\1/p' <<<"$promotion_body")"
[[ "$consultation_scope" =~ ^[0-9a-f]{64}$ ]] || {
  echo "[fullats-rollback] promotion consultation scope is missing or duplicated" >&2
  exit 1
}
risk_trigger="$(sed -nE 's/^Risk trigger:[[:space:]]*(security-authz|production-cutover):[[:space:]]*(.{10,})[[:space:]]*$/\1: \2/p' <<<"$promotion_body")"
[[ -n "$risk_trigger" ]] || {
  echo "[fullats-rollback] dual consultation risk trigger is missing or invalid" >&2
  exit 1
}
for receipt_label in "Claude receipt" "Codex receipt"; do
  receipt_line="$(grep -E "^${receipt_label}: " <<<"$promotion_body" || true)"
  [[ "$(grep -Ec "^${receipt_label}: " <<<"$promotion_body" || true)" == "1" && \
     "$receipt_line" == *"head=$promotion_head;"* && \
     "$receipt_line" == *"scope=$consultation_scope;"* && \
     "$receipt_line" == *"verdict=AGREE;"* ]] || {
    echo "[fullats-rollback] exact $receipt_label binding is missing or invalid" >&2
    exit 1
  }
done
[[ "$(grep -Fc "MiniMax receipt:" <<<"$promotion_body" || true)" == "0" ]] || {
  echo "[fullats-rollback] MiniMax receipt is forbidden by forward policy" >&2
  exit 1
}
git fetch origin main --quiet
[[ "$(git rev-parse origin/main)" == "$FAILED_SHA" ]] || {
  echo "[fullats-rollback] main advanced; automatic revert requires a new reviewed scope" >&2
  exit 1
}
[[ "$merge_sha" == "$FAILED_SHA" ]] || {
  echo "[fullats-rollback] acceptance did not run on the exact reviewed promotion merge" >&2
  exit 1
}

branch="auto-fullats-rollback/faz25-fullats-${RUN_ID}-${RUN_ATTEMPT}"
git checkout -B "$branch" origin/main --quiet
rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT

ATS_OLD="sha256:8812ab4eed4881c24e8a8cc7129648d201e064f032dced571d9a56916ad66a11"
ATS_NEW="sha256:5b8985c1a5287588e3338bf569136c6eb6091a4475d4226a0b80c8603571b20d"
PERMISSION_CURRENT="sha256:55f2f2f2d1edb3aa67c663c1411b0cc21ab1818d10b4d8d70a5beeeb32ade13d"
FRONTEND_OLD="sha256:46a55e1664552d7f8a35c15bdd14ff4a21b9a40bc6d10324aa779e61be036402"
FRONTEND_NEW="sha256:c77d4dc57e48eed8583bf26850ac61f0ca3e44439baf64b7d2da9d3709d000f2"
FRONTEND_OLD_SHA="eee1310b33376013967482ae842bf15c797fe72c"
FRONTEND_NEW_SHA="f4a1f5822226fcb5452a7defd013933dac7fb440"
FRONTEND_OLD_TAG="sha-eee1310"
FRONTEND_NEW_TAG="sha-f4a1f58"

test_root="kustomize/overlays/test/kustomization.yaml"
ats_activation="kustomize/overlays/test/activation/ats-interview-evidence/kustomization.yaml"
state_marker="kustomize/overlays/test/fullats-promotion-state.txt"
parent_count="$(git rev-list --parents -n 1 "$merge_sha" | awk '{print NF - 1}')"
if [[ "$parent_count" != "1" || "$(git rev-parse "$merge_sha^")" != "$PROMOTION_BASE_SHA" ]]; then
  echo "[fullats-rollback] promotion must be one-parent squash directly on reviewed base" >&2
  exit 1
fi
promotion_head_commit="$(gh api "repos/$GH_REPO/git/commits/$promotion_head")"
promotion_merge_commit="$(gh api "repos/$GH_REPO/git/commits/$merge_sha")"
promotion_head_tree="$(jq -r '.tree.sha // empty' <<<"$promotion_head_commit")"
promotion_merge_tree="$(jq -r '.tree.sha // empty' <<<"$promotion_merge_commit")"
[[ "$promotion_head_tree" =~ ^[0-9a-f]{40}$ && \
   "$promotion_merge_tree" == "$promotion_head_tree" ]] || {
  echo "[fullats-rollback] squash tree differs from the exact reviewed promotion head" >&2
  exit 1
}

# Restore the two promoted runtime pins from the reviewed promotion base.
# Source scripts/workflows stay available, while the marker makes the failed
# promotion state explicit. Permission-service remains unchanged.
git show "$PROMOTION_BASE_SHA:$test_root" >"$test_root"
git show "$PROMOTION_BASE_SHA:$ats_activation" >"$ats_activation"
printf 'ROLLED_BACK\n' >"$state_marker"

changed="$(git diff --name-only | sort)"
expected_changed="$(printf '%s\n' "$ats_activation" "$state_marker" "$test_root" | sort)"
[[ "$changed" == "$expected_changed" ]] || {
  echo "[fullats-rollback] changed-file set escaped three-file runtime contract" >&2
  exit 1
}
grep -Fq -- "$PERMISSION_CURRENT" "$test_root"
grep -Fq -- "$ATS_OLD" "$ats_activation"
if grep -Fq -- "$ATS_NEW" "$ats_activation"; then
  echo "[fullats-rollback] failed ATS artifact survived deterministic revert" >&2
  exit 1
fi
grep -Fq -- "$FRONTEND_OLD" "$test_root"
grep -Fq -- "sourceRevision: $FRONTEND_OLD_SHA" "$test_root"
grep -Fq -- "newTag: $FRONTEND_OLD_TAG" "$test_root"
if grep -Fq -- "$FRONTEND_NEW" "$test_root" || \
   grep -Fq -- "sourceRevision: $FRONTEND_NEW_SHA" "$test_root" || \
   grep -Fq -- "newTag: $FRONTEND_NEW_TAG" "$test_root"; then
  echo "[fullats-rollback] failed frontend artifact survived deterministic revert" >&2
  exit 1
fi
grep -Fxq -- "ROLLED_BACK" "$state_marker"

kustomize build kustomize/overlays/test >"$rendered"
grep -Fq -- "ghcr.io/halildeu/ats-app-boot@$ATS_OLD" "$rendered"
grep -Fq -- "ghcr.io/halildeu/platform-backend-permission-service@$PERMISSION_CURRENT" "$rendered"
grep -Fq -- "ghcr.io/halildeu/platform-web-frontend-testai:$FRONTEND_OLD_TAG@$FRONTEND_OLD" "$rendered"

git add "$ats_activation" "$state_marker" "$test_root"
git diff --cached --check
git config user.name "$BOT_NAME"
git config user.email "$BOT_EMAIL"
run_url="$SERVER_URL/$GH_REPO/actions/runs/$RUN_ID"
git commit --quiet -m "revert(faz25): compensate failed Full ATS acceptance

Exact three-file runtime compensator for merged promotion PR #${PROMOTION_PR}
after its live browser acceptance failed on the same main SHA. Restores prior
ATS + frontend test artifacts and rollback marker; permission stays current.

Run: ${run_url}
Tracked by #2615."
git push origin "HEAD:$branch" --quiet

body="$(cat <<'EOF'
## Test-only compensating rollback

The live Full ATS browser acceptance failed on the exact merge of promotion PR
#__PROMOTION_PR__. This PR restores the reviewed-base ATS and frontend runtime
pins and marks the promotion ROLLED_BACK. The current permission-service pin is
preserved.

- Failed acceptance run: __RUN_URL__
- Failed main SHA: `__FAILED_SHA__`
- Direct Kubernetes workload mutation: **none**
- Production or real PII mutation: **none**
- Rollback authority: GitOps desired state; ArgoCD reconciles only after merge
- Tracked by: #2615

## Cross-AI

Automation source: .github/workflows/faz25-fullats-live-browser-acceptance.yml
Cross-AI exempt reason: Machine-generated three-file ATS and frontend test rollback; no AI peer-review claim is made.
Automation evidence: __RUN_URL__

## Boundary declaration (ADR-0011 §2.3)

- [ ] credential-read
- [ ] credential-write
- [x] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [ ] none of the above
EOF
)"
body="${body//__PROMOTION_PR__/$PROMOTION_PR}"
body="${body//__RUN_URL__/$run_url}"
body="${body//__FAILED_SHA__/$FAILED_SHA}"

pr_url="$(gh pr create --repo "$GH_REPO" --base main --head "$branch" \
  --title "revert(faz25): compensate failed Full ATS test acceptance" \
  --body "$body")"
rollback_head="$(gh pr view "$pr_url" --repo "$GH_REPO" --json headRefOid --jq '.headRefOid')"
[[ "$rollback_head" == "$(git rev-parse HEAD)" ]] || {
  echo "[fullats-rollback] opened PR head differs from generated rollback commit" >&2
  exit 1
}

# Repository auto-merge is intentionally not assumed. Wait for the protected
# branch's required checks to materialize and pass, then perform a normal merge
# bound to the exact generated head. Strict branch protection rejects the merge
# if main advanced; no --admin bypass is used.
required_checks=""
for _ in $(seq 1 60); do
  required_checks="$(gh pr checks "$pr_url" --repo "$GH_REPO" \
    --required --json name,bucket 2>/dev/null)" || true
  if jq -e 'type == "array" and length > 0' <<<"$required_checks" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
jq -e 'type == "array" and length > 0' <<<"$required_checks" >/dev/null || {
  echo "[fullats-rollback] required checks did not materialize" >&2
  exit 1
}
gh pr checks "$pr_url" --repo "$GH_REPO" --required --watch --fail-fast --interval 10
[[ "$(gh pr view "$pr_url" --repo "$GH_REPO" --json headRefOid --jq '.headRefOid')" == \
   "$rollback_head" ]] || {
  echo "[fullats-rollback] rollback PR head changed while checks were running" >&2
  exit 1
}
gh pr merge "$pr_url" --repo "$GH_REPO" --squash --match-head-commit "$rollback_head"
rollback_merge_json="$(gh pr view "$pr_url" --repo "$GH_REPO" --json mergedAt,mergeCommit)"
merged_at="$(jq -r '.mergedAt // empty' <<<"$rollback_merge_json")"
rollback_merge_sha="$(jq -r '.mergeCommit.oid // empty' <<<"$rollback_merge_json")"
[[ -n "$merged_at" && "$rollback_merge_sha" =~ ^[0-9a-f]{40}$ ]] || {
  echo "[fullats-rollback] protected rollback merge did not complete" >&2
  exit 1
}

# A merged compensator is not a successful rollback by itself. Wait for the
# GitOps controller to observe the exact rollback merge, then re-prove the
# reviewed-base frontend at the desired Deployment, Ready Pod imageID, public
# build-info and current ATS/permission D29 functional/authz layers. This verifier performs no
# direct workload mutation; a failed post-rollback check leaves this workflow
# red and the already-merged compensator visible for incident handling.
rollback_evidence_dir="${ROLLBACK_EVIDENCE_DIR:-${RUNNER_TEMP:-/tmp}/fullats-rollback-evidence-${RUN_ID}-${RUN_ATTEMPT}}"
mkdir -p "$rollback_evidence_dir"
chmod 0700 "$rollback_evidence_dir"
rollback_digest_map="$(python3 scripts/automation/backend-testai-digest-contract.py inspect \
  --kustomization "$test_root")"
REVISION="$rollback_merge_sha" \
DIGEST_MAP="$rollback_digest_map" \
FULL_SYNC_TIMEOUT=600 \
REPORT_PATH="$rollback_evidence_dir/argocd-convergence.json" \
  bash scripts/deploy/reconcile-testai-backend-sequential.sh

EXPECTED_GITOPS_SHA="$rollback_merge_sha" \
EXPECTED_FRONTEND_SHA="$FRONTEND_OLD_SHA" \
EXPECTED_ATS_DIGEST="$ATS_OLD" \
EXPECTED_PERMISSION_DIGEST="$PERMISSION_CURRENT" \
EXPECTED_FRONTEND_DIGEST="$FRONTEND_OLD" \
PHASE=post \
EVIDENCE_DIR="$rollback_evidence_dir" \
REQUIRE_HEAD_SHA=false \
  bash scripts/ats/verify-fullats-live-runtime.sh
ATS_EXPECTED_DIGEST="$ATS_OLD" bash scripts/ats/d29-smoke.sh

git fetch origin main --quiet
[[ "$(git rev-parse origin/main)" == "$rollback_merge_sha" ]] || {
  echo "[fullats-rollback] main advanced during post-rollback verification" >&2
  exit 1
}
jq -n \
  --arg rollback_pr "$pr_url" \
  --arg revision "$rollback_merge_sha" \
  --arg ats_digest "$ATS_OLD" \
  --arg permission_digest "$PERMISSION_CURRENT" \
  --arg frontend_digest "$FRONTEND_OLD" \
  --arg frontend_sha "$FRONTEND_OLD_SHA" \
  '{
    schema: "faz25-fullats-post-rollback-runtime/v1",
    verdict: "PASS",
    rollback_pr: $rollback_pr,
    revision: $revision,
    argocd: {sync: "Synced", health: "Healthy", exact_revision: true},
    runtime: {
      ats_digest: $ats_digest,
      permission_digest: $permission_digest,
      frontend_digest: $frontend_digest,
      frontend_sha: $frontend_sha,
      ready_pod_image_ids_exact: true,
      d29_passed: true
    }
  }' >"$rollback_evidence_dir/runtime-acceptance.json"

echo "[fullats-rollback] rollback PR merged and live re-verification passed: $pr_url"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  printf 'rollback_pr_url=%s\n' "$pr_url" >>"$GITHUB_OUTPUT"
  printf 'rollback_merge_sha=%s\n' "$rollback_merge_sha" >>"$GITHUB_OUTPUT"
fi
