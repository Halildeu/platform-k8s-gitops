#!/usr/bin/env bash
# scripts/automation/sync-test-overlay.sh
#
# #827 / #2384 — open/update the `auto-test-overlay/backend-testai` PR that
# re-pins the test-overlay kustomization's backend `digest:` lines to the full
# immutable map published by platform-backend.
#
# Invoked by deploy-backend-testai.yml BEFORE any runtime rollout. The promotion
# workflow validates the complete 13-service map, and this script applies it to
# the overlay through a reviewable PR. After merge, the separate verifier
# reconciles the merged revision through ArgoCD and proves exact pod imageIDs.
#
# The PR is exempt from the cross-AI peer-review requirement via the #827
# automation-PR governance contract (scripts/ci/pr-cross-ai-audit.mjs
# `auditAutomation`): the `auto-test-overlay/` head-branch prefix + the
# `platform-gitops-automation[bot]` App identity + the `## Cross-AI` automation
# attestation block in the body. The PR is therefore opened with a GitHub App
# installation token, NOT GITHUB_TOKEN — a GITHUB_TOKEN-opened PR does not
# trigger the `pull_request` workflows the required `cross-ai-audit` check needs.
#
# Idempotent: the branch is reset to origin/main + the digest delta on every
# run; an already-open PR is updated by the force-push, otherwise a new PR is
# opened. If the overlay already matches the rollout, nothing is pushed.
#
# Required env:
#   DIGEST_MAP   — validated JSON {service: 'sha256:...'} from source build
#   SHORT_SHA    — 7-char platform-backend commit sha
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
# Same-image pilot topology (#2031, Codex 019f008a): the remote-bridge activation
# overlay runs the SAME endpoint-admin-service image as the primary test overlay. When
# the rollout bumps endpoint-admin-service, its digest is mirrored into this bridge
# overlay in the SAME PR so the completion-audit REMOTE_BRIDGE_LIVE gate cannot re-drift.
BRIDGE_KUSTOMIZATION="kustomize/overlays/test/activation/endpoint-admin-remote-bridge/kustomization.yaml"
# Faz 22.6 #548 uses a dedicated, owner-gated device-key broker overlay on the same
# endpoint-admin-service image line. Keep it in the same digest-sync transaction so
# strong-attestation evidence runs do not silently execute stale backend bytecode.
DEVICE_KEY_BRIDGE_KUSTOMIZATION="kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key/kustomization.yaml"
APPLY_SCRIPT="scripts/automation/apply-test-overlay-digests.py"
GH_REPO="${GITHUB_REPO:-Halildeu/platform-k8s-gitops}"
SERVER_URL="${GITHUB_SERVER_URL:-https://github.com}"
BOT_NAME="platform-gitops-automation[bot]"
BOT_EMAIL="platform-gitops-automation[bot]@users.noreply.github.com"

# ------------------------------------------------------------
# Pre-flight
# ------------------------------------------------------------
: "${DIGEST_MAP:?DIGEST_MAP env required (validated source {service: digest} JSON map)}"
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

# ------------------------------------------------------------
# Mirror endpoint-admin-service digest into the bridge activation overlays (#2031 + #548)
# ------------------------------------------------------------
# Same-image pilot topology: the remote-bridge brokers run the SAME endpoint-admin-service
# image. If the rollout bumped endpoint-admin-service, mirror that exact digest into
# the normal bridge and #548 device-key activation overlays so they never re-drift.
# Reuses the same comment-preserving writer with a single-service map; endpoint-admin-service
# is the ONLY service mirrored. The digest-alignment guard
# (scripts/governance/check-remote-bridge-digest-alignment.sh) enforces this invariant at PR time.
BRIDGE_OUT=""
DEVICE_KEY_BRIDGE_OUT=""
EA_DIGEST=$(printf '%s' "$DIGEST_MAP" | jq -r '."endpoint-admin-service" // empty')
if [[ -n "$EA_DIGEST" ]]; then
  if ! BRIDGE_OUT=$(python3 "$APPLY_SCRIPT" --digest-map "{\"endpoint-admin-service\":\"${EA_DIGEST}\"}" --kustomization "$BRIDGE_KUSTOMIZATION"); then
    echo "::error::[sync-test-overlay] bridge activation overlay mirror failed (endpoint-admin digest ${EA_DIGEST})"
    exit 1
  fi
  echo "$BRIDGE_OUT"
  if ! DEVICE_KEY_BRIDGE_OUT=$(python3 "$APPLY_SCRIPT" --digest-map "{\"endpoint-admin-service\":\"${EA_DIGEST}\"}" --kustomization "$DEVICE_KEY_BRIDGE_KUSTOMIZATION"); then
    echo "::error::[sync-test-overlay] device-key bridge activation overlay mirror failed (endpoint-admin digest ${EA_DIGEST})"
    exit 1
  fi
  echo "$DEVICE_KEY_BRIDGE_OUT"
fi

if git diff --quiet -- "$KUSTOMIZATION" "$BRIDGE_KUSTOMIZATION" "$DEVICE_KEY_BRIDGE_KUSTOMIZATION"; then
  echo "[sync-test-overlay] test overlay + bridge overlays already match the immutable source map — no PR needed"
  exit 0
fi

# ------------------------------------------------------------
# Diff guard — the PR may change ONLY the primary test overlay + bridge activation
# overlays, ONLY digest: lines, ONLY <= 15 (up to 13 backend services + 2 bridge mirrors)
# ------------------------------------------------------------
changed_files=$(git diff --name-only)
while IFS= read -r cf; do
  [[ -z "$cf" ]] && continue
  if [[ "$cf" != "$KUSTOMIZATION" && "$cf" != "$BRIDGE_KUSTOMIZATION" && "$cf" != "$DEVICE_KEY_BRIDGE_KUSTOMIZATION" ]]; then
    echo "::error::[sync-test-overlay] diff-guard: only $KUSTOMIZATION, $BRIDGE_KUSTOMIZATION and $DEVICE_KEY_BRIDGE_KUSTOMIZATION may change; got: ${changed_files//$'\n'/, }"
    exit 1
  fi
done <<< "$changed_files"

offending=$(git diff -U0 -- "$KUSTOMIZATION" "$BRIDGE_KUSTOMIZATION" "$DEVICE_KEY_BRIDGE_KUSTOMIZATION" \
  | grep -E '^[-+]' \
  | grep -vE '^(\+\+\+|---) ' \
  | grep -vE '^[-+][[:space:]]+digest: sha256:[a-f0-9]{64}$' || true)
if [[ -n "$offending" ]]; then
  echo "::error::[sync-test-overlay] diff-guard: non-digest line(s) in the diff:"
  printf '%s\n' "$offending"
  exit 1
fi

added=$(git diff -U0 -- "$KUSTOMIZATION" "$BRIDGE_KUSTOMIZATION" "$DEVICE_KEY_BRIDGE_KUSTOMIZATION" \
  | grep -cE '^\+[[:space:]]+digest: sha256:[a-f0-9]{64}$' || true)
deleted=$(git diff -U0 -- "$KUSTOMIZATION" "$BRIDGE_KUSTOMIZATION" "$DEVICE_KEY_BRIDGE_KUSTOMIZATION" \
  | grep -cE '^-[[:space:]]+digest: sha256:[a-f0-9]{64}$' || true)
# Pure-rewrite contract: each change removes one digest line and adds one, so
# added == deleted. A mismatch means a digest line was purely added or deleted
# — out of contract (Codex 019e407c P3).
if [[ "$added" -ne "$deleted" ]]; then
  echo "::error::[sync-test-overlay] diff-guard: digest add/remove mismatch (+${added} / -${deleted}) — expected a pure rewrite"
  exit 1
fi
if [[ "$added" -lt 1 || "$added" -gt 15 ]]; then
  echo "::error::[sync-test-overlay] diff-guard: ${added} digest line(s) changed (expected 1..15: up to 13 backend services + 2 endpoint-admin bridge mirrors)"
  exit 1
fi
echo "[sync-test-overlay] diff-guard OK — ${added} digest line(s) rewritten (incl. any endpoint-admin bridge mirrors)"

# ------------------------------------------------------------
# Commit + force-push the rolling automation branch
# ------------------------------------------------------------
git config user.name "$BOT_NAME"
git config user.email "$BOT_EMAIL"
git add "$KUSTOMIZATION" "$BRIDGE_KUSTOMIZATION" "$DEVICE_KEY_BRIDGE_KUSTOMIZATION"
git commit --quiet -m "auto(test-overlay): promote ${added} backend digest(s) from sha-${SHORT_SHA}

Includes endpoint-admin-service bridge activation overlay mirrors when endpoint-admin
was rolled (same-image pilot topology, #2031 + #548), so the completion-audit
REMOTE_BRIDGE_LIVE and strong device-key broker evidence path cannot re-drift.
Promotion run: ${RUN_URL}
Generated by scripts/automation/sync-test-overlay.sh (#827 + #2384 + #2031)."

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

platform-backend published the immutable sha-${SHORT_SHA} image set. This PR
re-pins ${KUSTOMIZATION} **before runtime mutation**. The dispatch workflow has
no cluster access. After normal review and merge,
verify-testai-backend-rollout.yml reconciles this exact revision through ArgoCD
and verifies every running pod imageID.

### Digest changes — primary test overlay

~~~
${APPLY_OUT}
~~~

### Bridge activation overlay (endpoint-admin same-image mirror, #2031)

~~~
${BRIDGE_OUT:-(unchanged — endpoint-admin-service not in this rollout)}
~~~

### Device-key bridge activation overlay (endpoint-admin same-image mirror, #548)

~~~
${DEVICE_KEY_BRIDGE_OUT:-(unchanged — endpoint-admin-service not in this rollout)}
~~~

- Promotion run: ${RUN_URL}
- Source commit: ${SHA}

## Boundary declaration (ADR-0011 §2.3)

- [ ] credential-read
- [ ] credential-write
- [x] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [ ] none of the above

Re-pins the **test** overlay desired-state to immutable source digests. This PR
does not directly mutate Kubernetes; merge authorizes the normal ArgoCD
reconciliation path. No production path and no credential I/O.

## Cross-AI

Automation source: .github/workflows/deploy-backend-testai.yml
Cross-AI exempt reason: Machine-generated test-overlay digest promotion; deterministic output of the validated source build map, no AI peer-review claim is made (issues 827 and 2384 automation-PR governance contract).
Automation evidence: ${RUN_URL}

🤖 Auto-opened by scripts/automation/sync-test-overlay.sh (#827 PR-B)
EOF
)

pr_url=$(gh pr create --repo "$GH_REPO" \
  --base main \
  --head "$BRANCH" \
  --title "auto(test-overlay): promote ${added} backend digest(s) — source sha-${SHORT_SHA}" \
  --body "$BODY")
echo "[sync-test-overlay] opened ${pr_url}"
