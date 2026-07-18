#!/usr/bin/env bash
# Faz 25 Full ATS canlı kabulü düşerse, yalnız onu taşıyan merged PR'ı
# deterministik biçimde tersine çeviren ve gerekli kontrollerden sonra otomatik
# birleşmek üzere tek bir GitOps rollback PR'ı açan test-only compensator.
set -euo pipefail

GH_REPO="${GH_REPO:-Halildeu/platform-k8s-gitops}"
PROMOTION_PR="${PROMOTION_PR:-2617}"
FAILED_SHA="${FAILED_SHA:-}"
RUN_ID="${RUN_ID:-0}"
RUN_ATTEMPT="${RUN_ATTEMPT:-1}"
SERVER_URL="${GITHUB_SERVER_URL:-https://github.com}"
BOT_NAME="platform-gitops-automation[bot]"
BOT_EMAIL="platform-gitops-automation[bot]@users.noreply.github.com"

: "${GH_TOKEN:?GH_TOKEN must be a platform-gitops-automation GitHub App token}"
[[ "$GH_REPO" == "Halildeu/platform-k8s-gitops" ]] || {
  echo "[fullats-rollback] unexpected repository" >&2
  exit 2
}
[[ "$PROMOTION_PR" == "2617" ]] || {
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

promotion_json="$(gh api "repos/$GH_REPO/pulls/$PROMOTION_PR")"
merge_sha="$(jq -r '.merge_commit_sha // empty' <<<"$promotion_json")"
merged_at="$(jq -r '.merged_at // empty' <<<"$promotion_json")"
[[ -n "$merged_at" && "$merge_sha" =~ ^[0-9a-f]{40}$ ]] || {
  echo "[fullats-rollback] promotion PR is not merged" >&2
  exit 1
}
[[ "$FAILED_SHA" == "$merge_sha" ]] || {
  echo "[fullats-rollback] refusing stale/non-promotion workflow SHA" >&2
  exit 1
}

git fetch origin main --quiet
[[ "$(git rev-parse origin/main)" == "$FAILED_SHA" ]] || {
  echo "[fullats-rollback] main advanced; automatic revert requires a new reviewed scope" >&2
  exit 1
}

branch="auto-rollback/faz25-fullats-${RUN_ID}-${RUN_ATTEMPT}"
git checkout -B "$branch" origin/main --quiet
# Reverse GitHub's PR-scoped patch, not a base..merge range that could include
# unrelated main changes. This is independent of squash/merge/rebase strategy;
# exact-main binding above prevents a stale acceptance from touching later work.
rollback_patch="$(mktemp)"
rendered="$(mktemp)"
trap 'rm -f "$rollback_patch" "$rendered"' EXIT
gh api -H 'Accept: application/vnd.github.patch' \
  "repos/$GH_REPO/pulls/$PROMOTION_PR" >"$rollback_patch"
[[ -s "$rollback_patch" ]]
git apply --check --reverse "$rollback_patch"
git apply --index --reverse "$rollback_patch"

ATS_OLD="sha256:dce33483d78ffed43e665a8a1c960e6fc3c2fc11ad3a9028a95593a9f5572515"
PERMISSION_OLD="sha256:3a202b36843676768dc74bbacc22328ecfba2de43b7383b9aa401e6e139a5256"
FRONTEND_OLD="sha256:28da39d9402a27d825d637e65e409ecf601cbfd22540add04ce5a3b9bf566b2d"
ATS_NEW="sha256:8812ab4eed4881c24e8a8cc7129648d201e064f032dced571d9a56916ad66a11"
PERMISSION_NEW="sha256:55f2f2f2d1edb3aa67c663c1411b0cc21ab1818d10b4d8d70a5beeeb32ade13d"
FRONTEND_NEW="sha256:dc4c10c76359836da06d83bca9d977433313a43ae06da1e909e28cd31ec71ead"

activation="kustomize/overlays/test/activation/ats-interview-evidence/kustomization.yaml"
test_root="kustomize/overlays/test/kustomization.yaml"
rg -Fq "$ATS_OLD" "$activation"
rg -Fq "$PERMISSION_OLD" "$test_root"
rg -Fq "$FRONTEND_OLD" "$test_root"
rg -Fq "sourceRevision: 653752b7bcfb8343b3af0845499a749c4655052c" "$test_root"
rg -Fq "newTag: sha-653752b" "$test_root"
if rg -Fq "$ATS_NEW" "$activation" || \
   rg -Fq "$PERMISSION_NEW" "$test_root" || \
   rg -Fq "$FRONTEND_NEW" "$test_root"; then
  echo "[fullats-rollback] promoted artifact survived deterministic revert" >&2
  exit 1
fi

kustomize build kustomize/overlays/test >"$rendered"
rg -Fq "ghcr.io/halildeu/ats-app-boot@$ATS_OLD" "$rendered"
rg -Fq "ghcr.io/halildeu/platform-backend-permission-service@$PERMISSION_OLD" "$rendered"
rg -Fq "ghcr.io/halildeu/platform-web-frontend-testai:sha-653752b@$FRONTEND_OLD" "$rendered"

git diff --cached --check
git config user.name "$BOT_NAME"
git config user.email "$BOT_EMAIL"
run_url="$SERVER_URL/$GH_REPO/actions/runs/$RUN_ID"
git commit --quiet -m "revert(faz25): compensate failed Full ATS test acceptance

Exact reverse of merged promotion PR #${PROMOTION_PR} after its live browser
acceptance failed on the same main SHA. Restores the prior atomic ATS,
permission-service and frontend test artifact set.

Run: ${run_url}
Tracked by #2615."
git push origin "HEAD:$branch" --quiet

body="$(cat <<'EOF'
## Test-only compensating rollback

The live Full ATS browser acceptance failed on the exact merge commit of
promotion PR #__PROMOTION_PR__. This PR is its deterministic Git revert and
restores the prior ATS + permission-service + frontend artifact set together.

- Failed acceptance run: __RUN_URL__
- Failed main SHA: `__FAILED_SHA__`
- Direct Kubernetes workload mutation: **none**
- Production or real PII mutation: **none**
- Rollback authority: GitOps desired state; ArgoCD reconciles only after merge
- Tracked by: #2615

## Cross-AI boundary

Cross-AI exempt reason: deterministic exact revert of the already reviewed
promotion scope after its fail-closed live acceptance. This PR introduces no
new feature or architecture decision. Normal required repository checks remain
mandatory before automatic merge.

## Boundary declaration

- [ ] credential-read
- [ ] credential-write
- [x] state-mutation (test cluster, through GitOps reconciliation)
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
gh pr merge "$pr_url" --repo "$GH_REPO" --squash --auto
echo "[fullats-rollback] rollback PR opened with auto-merge: $pr_url"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  printf 'rollback_pr_url=%s\n' "$pr_url" >>"$GITHUB_OUTPUT"
fi
