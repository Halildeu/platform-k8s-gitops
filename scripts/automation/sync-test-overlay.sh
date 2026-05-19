#!/usr/bin/env bash
# scripts/automation/sync-test-overlay.sh
#
# #827 PR-B — open/update the `auto-test-overlay/backend-testai` PR that re-pins
# the test-overlay kustomization's backend `digest:` lines to what the
# deploy-backend-testai.yml rollout job just put on k3d-test.
#
# Invoked by the `sync-test-overlay-pr` job AFTER a green sequential rollout.
# The rollout job emits a {service: digest} JSON map (containerd-resolved pod
# imageIDs); this script applies it to the overlay and PR-mediates the change so
# the recorded desired-state never silently drifts from the running cluster.
#
# The PR is exempt from the cross-AI peer-review requirement via the #827
# automation-PR governance contract (scripts/ci/pr-cross-ai-audit.mjs
# `auditAutomation`): the `auto-test-overlay/` head-branch prefix + the
# `platform-automation[bot]` App identity + the `## Cross-AI` automation
# attestation block in the body. The PR is therefore opened with a GitHub App
# installation token, NOT GITHUB_TOKEN — a GITHUB_TOKEN-opened PR does not
# trigger the `pull_request` workflows the required `cross-ai-audit` check needs.
#
# Idempotent: the branch is reset to origin/main + the digest delta on every
# run; an already-open PR is updated by the force-push, otherwise a new PR is
# opened. If the overlay already matches the rollout, nothing is pushed.
#
# Required env:
#   DIGEST_MAP   — JSON {service: 'sha256:...'} from the rollout job
#   SHORT_SHA    — 7-char deploy commit sha
#   GH_TOKEN     — GitHub App installation token (gh CLI auth)
# Optional env:
#   SHA          — 40-char deploy commit sha (default: SHORT_SHA)
#   RUN_ID       — deploy workflow run id (default: 0) — Automation evidence link
#   GITHUB_REPO  — owner/repo (default: Halildeu/platform-k8s-gitops)
#   GITHUB_SERVER_URL — default: https://github.com
#
# Exit:
#   0 — PR opened/updated, OR overlay already in sync (no-op)
#   1 — apply inconsistency, diff-guard violation, or git/gh failure

set -euo pipefail

BRANCH="auto-test-overlay/backend-testai"
KUSTOMIZATION="kustomize/overlays/test/kustomization.yaml"
APPLY_SCRIPT="scripts/automation/apply-test-overlay-digests.py"
GH_REPO="${GITHUB_REPO:-Halildeu/platform-k8s-gitops}"
SERVER_URL="${GITHUB_SERVER_URL:-https://github.com}"
BOT_NAME="platform-automation[bot]"
BOT_EMAIL="platform-automation[bot]@users.noreply.github.com"

# ------------------------------------------------------------
# Pre-flight
# ------------------------------------------------------------
: "${DIGEST_MAP:?DIGEST_MAP env required (rollout {service: digest} JSON map)}"
: "${SHORT_SHA:?SHORT_SHA env required}"
SHA="${SHA:-$SHORT_SHA}"
RUN_ID="${RUN_ID:-0}"
RUN_URL="${SERVER_URL}/${GH_REPO}/actions/runs/${RUN_ID}"

if [[ "$DIGEST_MAP" == "{}" || -z "$DIGEST_MAP" ]]; then
  echo "[sync-test-overlay] digest map empty — nothing to sync"
  exit 0
fi

if [[ ! -f "$APPLY_SCRIPT" ]]; then
  echo "::error::[sync-test-overlay] apply script not found: $APPLY_SCRIPT"
  exit 1
fi

# ------------------------------------------------------------
# Reset the dedicated automation branch to main
# ------------------------------------------------------------
git fetch origin main --quiet
git checkout -B "$BRANCH" origin/main --quiet

# ------------------------------------------------------------
# Apply the digest map (fail-closed — see apply-test-overlay-digests.py)
# ------------------------------------------------------------
if ! APPLY_OUT=$(python3 "$APPLY_SCRIPT" --digest-map "$DIGEST_MAP" --kustomization "$KUSTOMIZATION"); then
  echo "::error::[sync-test-overlay] apply-test-overlay-digests.py failed (digest map inconsistent with the overlay)"
  exit 1
fi
echo "$APPLY_OUT"

if git diff --quiet -- "$KUSTOMIZATION"; then
  echo "[sync-test-overlay] test overlay already in sync with the rollout — no PR needed"
  exit 0
fi

# ------------------------------------------------------------
# Diff guard — the PR may change ONLY this file, ONLY digest: lines, ONLY <= 8
# ------------------------------------------------------------
changed_files=$(git diff --name-only)
if [[ "$changed_files" != "$KUSTOMIZATION" ]]; then
  echo "::error::[sync-test-overlay] diff-guard: only $KUSTOMIZATION may change; got: ${changed_files//$'\n'/, }"
  exit 1
fi

offending=$(git diff -U0 -- "$KUSTOMIZATION" \
  | grep -E '^[-+]' \
  | grep -vE '^(\+\+\+|---) ' \
  | grep -vE '^[-+][[:space:]]+digest: sha256:[a-f0-9]{64}$' || true)
if [[ -n "$offending" ]]; then
  echo "::error::[sync-test-overlay] diff-guard: non-digest line(s) in the diff:"
  printf '%s\n' "$offending"
  exit 1
fi

added=$(git diff -U0 -- "$KUSTOMIZATION" \
  | grep -cE '^\+[[:space:]]+digest: sha256:[a-f0-9]{64}$' || true)
deleted=$(git diff -U0 -- "$KUSTOMIZATION" \
  | grep -cE '^-[[:space:]]+digest: sha256:[a-f0-9]{64}$' || true)
# Pure-rewrite contract: each change removes one digest line and adds one, so
# added == deleted. A mismatch means a digest line was purely added or deleted
# — out of contract (Codex 019e407c P3).
if [[ "$added" -ne "$deleted" ]]; then
  echo "::error::[sync-test-overlay] diff-guard: digest add/remove mismatch (+${added} / -${deleted}) — expected a pure rewrite"
  exit 1
fi
if [[ "$added" -lt 1 || "$added" -gt 8 ]]; then
  echo "::error::[sync-test-overlay] diff-guard: ${added} digest line(s) changed (expected 1..8 backend services)"
  exit 1
fi
echo "[sync-test-overlay] diff-guard OK — ${added} digest line(s) rewritten"

# ------------------------------------------------------------
# Commit + force-push the rolling automation branch
# ------------------------------------------------------------
git config user.name "$BOT_NAME"
git config user.email "$BOT_EMAIL"
git add "$KUSTOMIZATION"
git commit --quiet -m "auto(test-overlay): sync ${added} backend digest(s) to deploy sha-${SHORT_SHA}

Rollout run: ${RUN_URL}
Generated by scripts/automation/sync-test-overlay.sh (#827 PR-B)."

# Dedicated automation branch reset to origin/main each run — force-push is the
# idempotent-update mechanism. --force-with-lease still guards a surprise
# concurrent writer; the deploy workflow concurrency group already serialises
# runs, so this is belt-and-suspenders. NOT main/master — HARD RULE respected.
git push --force-with-lease origin "HEAD:${BRANCH}" --quiet

# ------------------------------------------------------------
# Open the PR (or report the already-open one the push just updated)
# ------------------------------------------------------------
existing=$(gh pr list --repo "$GH_REPO" --head "$BRANCH" --state open \
  --json number --jq '.[0].number // empty')
if [[ -n "$existing" ]]; then
  echo "[sync-test-overlay] PR #${existing} already open for ${BRANCH} — force-push updated it"
  exit 0
fi

BODY=$(cat <<EOF
## Summary

deploy-backend-testai.yml rolled out backend sha-${SHORT_SHA} to k3d-test. This
PR re-pins ${KUSTOMIZATION} so the recorded desired-state matches the
containerd-resolved pod imageIDs that are **already running** — merging it does
not itself mutate the cluster.

### Digest changes

~~~
${APPLY_OUT}
~~~

- Rollout run: ${RUN_URL}
- Deploy commit: ${SHA}

## Boundary declaration (ADR-0011 §2.3)

- [ ] credential-read
- [ ] credential-write
- [x] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [ ] none of the above

Re-pins the **test** overlay desired-state to the just-rolled digests; no
production path, no credential I/O. state-mutation (test cluster) is not a
user-approval-required class (ADR-0011 §2.3) — no label/evidence required.

## Cross-AI

Automation source: .github/workflows/deploy-backend-testai.yml
Cross-AI exempt reason: Machine-generated test-overlay digest sync; deterministic output of the deploy rollout job, no AI peer-review claim is made (issue 827 automation-PR governance contract).
Automation evidence: ${RUN_URL}

🤖 Auto-opened by scripts/automation/sync-test-overlay.sh (#827 PR-B)
EOF
)

pr_url=$(gh pr create --repo "$GH_REPO" \
  --base main \
  --head "$BRANCH" \
  --title "auto(test-overlay): sync ${added} backend digest(s) — deploy sha-${SHORT_SHA}" \
  --body "$BODY")
echo "[sync-test-overlay] opened ${pr_url}"
