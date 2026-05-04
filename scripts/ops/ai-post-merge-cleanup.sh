#!/usr/bin/env bash
# ~/.claude/scripts/ai-post-merge-cleanup.sh
#
# AI-native forensic post-merge cleanup pattern (Opsiyon D — Codex PARTIAL absorb).
# Multi-user concurrent AI session safe with 5-layer hardening.
#
# Usage:
#   ai-post-merge-cleanup.sh <pr-number> [<expected-branch>]
#
# Designed for AI auto-merge bot integration (race-protected):
#   BRANCH=feat/X
#   gh pr merge $PR --squash --delete-branch --admin && \
#     bash ~/.claude/scripts/ai-post-merge-cleanup.sh $PR "$BRANCH"
#
# Without expected-branch arg, script proceeds with current branch (legacy).
#
# Hardening layers (Codex 019df310 absorb):
#   1. Per-worktree lock (atomic mkdir; aynı worktree race engelle)
#   2. Working tree safety (uncommitted → abort)
#   3. Remote archive tag push HARD GATE (fail → no delete unless override)
#   4. Existing tag SHA collision check (aynı SHA → idempotent OK; farklı → abort)
#   5. Local-only branch delete only with merged PR proof (gh pr view --json mergedAt)
#
# Override flags (env):
#   AI_CLEANUP_DRY_RUN=1                  → validate only, no writes
#   AI_CLEANUP_ALLOW_LOCAL_ONLY_ARCHIVE=1 → tag push fail → continue with delete (NOT recommended)
#   AI_CLEANUP_SKIP_PR_PROOF=1            → local-only branch delete without PR check (rare)
#
# Recovery:
#   git tag --list 'archive/*pr<N>*'                          # find archive
#   git checkout -b recovery/<name> archive/2026/05/<branch>  # restore
#   grep "pr=<N>" ~/.claude/logs/git-cleanup.log              # audit
#
# Exit codes:
#   0 — cleanup success
#   1 — abort (lock/working tree/fetch fail/PR proof missing)
#   2 — partial (tag created but delete blocked / push failed without override)

set -uo pipefail

# Args:
#   $1 — PR number (required)
#   $2 — expected branch name (optional; race protection)
PR_NUM="${1:-unknown}"
EXPECTED_BRANCH="${2:-}"

LOG_FILE="${AI_CLEANUP_LOG:-$HOME/.claude/logs/git-cleanup.log}"
ARCHIVE_REMOTE="${AI_CLEANUP_REMOTE:-origin}"
DRY_RUN="${AI_CLEANUP_DRY_RUN:-0}"
ALLOW_LOCAL_ONLY="${AI_CLEANUP_ALLOW_LOCAL_ONLY_ARCHIVE:-0}"
SKIP_PR_PROOF="${AI_CLEANUP_SKIP_PR_PROOF:-0}"

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERR: not in a git repo"
  exit 1
}
cd "$REPO_ROOT" || exit 1

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
YYYY=$(date -u +%Y)
MM=$(date -u +%m)
USER_ID="${USER:-unknown}"
WORKTREE_NAME=$(basename "$REPO_ROOT")
SESSION_ID="${CLAUDE_SESSION_ID:-$(printf '%08x' $RANDOM$RANDOM | head -c 8)}"
ACTOR="${AI_CLEANUP_ACTOR:-ai}"  # ai|human|ci

# Detect repo identity (origin URL → owner/name)
ORIGIN_URL=$(git config --get remote.origin.url 2>/dev/null || echo "unknown")
REPO_ID=$(echo "$ORIGIN_URL" | sed -E 's|^.*[:/]([^/]+)/([^/.]+)(\.git)?$|\1/\2|')

# ----------------------------------------------------------------
# HARDENING 1: Per-worktree lock (atomic mkdir, prevents same-worktree race)
# ----------------------------------------------------------------
LOCK_DIR="$(git rev-parse --git-dir)/ai-cleanup.lock"
if [[ "$DRY_RUN" != "1" ]]; then
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "[abort] cleanup already running in this worktree (lock: $LOCK_DIR)"
    echo "        if stale: rmdir $LOCK_DIR && retry"
    exit 1
  fi
  trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT
fi

# ----------------------------------------------------------------
# HARDENING 2a: Mid-operation guard (rebase/merge/cherry-pick in progress)
# ----------------------------------------------------------------
GIT_DIR=$(git rev-parse --git-dir)
for marker in MERGE_HEAD REBASE_HEAD CHERRY_PICK_HEAD REVERT_HEAD BISECT_LOG; do
  if [[ -e "$GIT_DIR/$marker" ]]; then
    echo "[abort] mid-operation detected: $marker exists"
    echo "         finish or abort the operation: git status; git rebase --abort/--continue"
    exit 1
  fi
done

# Mid-rebase ek kontrol (interactive rebase dirs)
if [[ -d "$GIT_DIR/rebase-merge" || -d "$GIT_DIR/rebase-apply" ]]; then
  echo "[abort] interactive rebase in progress"
  exit 1
fi

# ----------------------------------------------------------------
# HARDENING 2b: Working tree + index check (porcelain comprehensive)
# Yakaladıkları: modified, staged, deleted, renamed, copied, type-changed
# Yakalamadıkları: untracked (--ignore-standard ile gözardı edilir, ayrıca check'leniyor)
# Submodule recurse for nested dirty
# ----------------------------------------------------------------
DIRTY_LINES=$(git status --porcelain --ignore-submodules=none --untracked-files=no 2>/dev/null)
if [[ -n "$DIRTY_LINES" ]]; then
  echo "[abort] working tree / index has uncommitted changes:"
  echo "$DIRTY_LINES" | head -10
  echo "         total dirty entries: $(echo "$DIRTY_LINES" | wc -l | tr -d ' ')"
  echo "         use: git status; commit/stash and re-run"
  exit 1
fi

# ----------------------------------------------------------------
# HARDENING 2e: Race protection — expected branch verification
# Monitor wrapper PR'ın branch'ini biliyor; biz de current branch
# o branch ise işlem devam, değilse abort (operator switched away).
# ----------------------------------------------------------------
CURRENT_BRANCH_PRECHECK=$(git branch --show-current 2>/dev/null)
if [[ -n "$EXPECTED_BRANCH" ]]; then
  if [[ -z "$CURRENT_BRANCH_PRECHECK" ]]; then
    echo "[abort] race-protection: current state is detached HEAD, expected branch $EXPECTED_BRANCH"
    echo "         operator likely switched away after PR merge; cleanup skipped"
    exit 1
  fi
  if [[ "$CURRENT_BRANCH_PRECHECK" != "$EXPECTED_BRANCH" ]]; then
    echo "[abort] race-protection: current branch ($CURRENT_BRANCH_PRECHECK) != expected ($EXPECTED_BRANCH)"
    echo "         operator switched to a different branch after PR merge"
    echo "         to force cleanup, re-run without expected branch arg"
    exit 1
  fi
  echo "[verified] current branch matches expected: $EXPECTED_BRANCH"
fi

# ----------------------------------------------------------------
# HARDENING 2c: Stash awareness (informational, doesn't block)
# Stash ref'leri branch operasyonlarından etkilenmez ama operatör bilmeli
# ----------------------------------------------------------------
STASH_COUNT=$(git stash list 2>/dev/null | wc -l | tr -d ' ')
if [[ "$STASH_COUNT" -gt 0 ]]; then
  echo "[info] $STASH_COUNT stash entries exist (preserved across cleanup)"
  echo "       review later: git stash list"
fi

# ----------------------------------------------------------------
# HARDENING 2d: Untracked file inventory (warn but allow)
# git switch --detach refuse eder eğer origin/main'deki tracked dosya
# lokal'deki untracked ile çakışırsa (built-in safety)
# ----------------------------------------------------------------
UNTRACKED_COUNT=$(git ls-files --others --exclude-standard | wc -l | tr -d ' ')
if [[ "$UNTRACKED_COUNT" -gt 0 ]]; then
  if [[ "$UNTRACKED_COUNT" -gt 50 ]]; then
    echo "[warn] $UNTRACKED_COUNT untracked files (verify .gitignore)"
  else
    echo "[info] $UNTRACKED_COUNT untracked files (kept across cleanup; switch will refuse if any conflicts)"
  fi
fi

CURRENT_BRANCH=$(git branch --show-current 2>/dev/null)
CURRENT_SHA=$(git rev-parse HEAD)
SHORT_SHA="${CURRENT_SHA:0:8}"

# ----------------------------------------------------------------
# Fetch latest origin state
# ----------------------------------------------------------------
echo "[fetch] origin --prune"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "[DRY] would: git fetch --prune origin"
else
  git fetch --prune origin 2>&1 | tail -2 || {
    echo "[abort] fetch failed"
    exit 1
  }
fi

# ----------------------------------------------------------------
# Determine if we should proceed with delete
# Branch upstream gone → PR merged + remote deleted (canonical signal)
# ----------------------------------------------------------------
SHOULD_DELETE_LOCAL=0
DELETE_GATE_REASON=""

if [[ -n "$CURRENT_BRANCH" && "$CURRENT_BRANCH" != "main" && "$CURRENT_BRANCH" != "HEAD" ]]; then
  UPSTREAM_STATE=$(git for-each-ref --format='%(upstream:track)' "refs/heads/$CURRENT_BRANCH" 2>/dev/null)

  if [[ "$UPSTREAM_STATE" == "[gone]" ]]; then
    SHOULD_DELETE_LOCAL=1
    DELETE_GATE_REASON="upstream gone"
  elif [[ -z "$UPSTREAM_STATE" ]]; then
    # ----------------------------------------------------------------
    # HARDENING 3: Local-only branch — require merged PR proof
    # ----------------------------------------------------------------
    if [[ "$SKIP_PR_PROOF" == "1" ]]; then
      SHOULD_DELETE_LOCAL=1
      DELETE_GATE_REASON="local-only (PR proof skip via override)"
    elif [[ "$PR_NUM" =~ ^[0-9]+$ ]] && command -v gh > /dev/null 2>&1; then
      MERGED_AT=$(gh pr view "$PR_NUM" --json mergedAt --jq '.mergedAt' 2>/dev/null || echo "null")
      if [[ "$MERGED_AT" != "null" && -n "$MERGED_AT" ]]; then
        SHOULD_DELETE_LOCAL=1
        DELETE_GATE_REASON="local-only + PR #$PR_NUM merged at $MERGED_AT"
      else
        SHOULD_DELETE_LOCAL=0
        DELETE_GATE_REASON="local-only but PR #$PR_NUM merged proof missing → KEEPING"
      fi
    else
      SHOULD_DELETE_LOCAL=0
      DELETE_GATE_REASON="local-only branch + no numeric PR or no gh CLI → KEEPING"
    fi
  else
    SHOULD_DELETE_LOCAL=0
    DELETE_GATE_REASON="upstream still active ($UPSTREAM_STATE) → KEEPING"
  fi
fi

echo "[gate] $DELETE_GATE_REASON"

# ----------------------------------------------------------------
# Archive tag (annotated, with metadata)
# ----------------------------------------------------------------
ARCHIVE_TAG=""
TAG_PUSH_OK=0
if [[ -n "$CURRENT_BRANCH" && "$CURRENT_BRANCH" != "main" && "$CURRENT_BRANCH" != "HEAD" ]]; then
  SAFE_BRANCH=$(echo "$CURRENT_BRANCH" | tr '/' '-' | tr -cd 'a-zA-Z0-9._-')
  ARCHIVE_TAG="archive/$YYYY/$MM/${SAFE_BRANCH}-pr${PR_NUM}"

  echo "[archive] tag: $ARCHIVE_TAG → $SHORT_SHA"

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY] would: git tag -a $ARCHIVE_TAG (annotated) + push"
    TAG_PUSH_OK=1
  else
    # ----------------------------------------------------------------
    # HARDENING 4: Existing tag SHA collision check
    # ----------------------------------------------------------------
    if git rev-parse -q --verify "${ARCHIVE_TAG}^{commit}" > /dev/null 2>&1; then
      EXISTING_SHA=$(git rev-parse "${ARCHIVE_TAG}^{commit}")
      if [[ "$EXISTING_SHA" == "$CURRENT_SHA" ]]; then
        echo "[idempotent] tag $ARCHIVE_TAG already points to $SHORT_SHA — skipping create"
        TAG_PUSH_OK=1
      else
        echo "[abort] tag collision: $ARCHIVE_TAG points to ${EXISTING_SHA:0:8}, expected $SHORT_SHA"
        echo "        forensic corruption risk; manual investigation required"
        exit 1
      fi
    else
      # Annotated tag with metadata
      TAG_MSG="archive pr=$PR_NUM repo=$REPO_ID branch=$CURRENT_BRANCH session=$SESSION_ID actor=$ACTOR ts=$NOW"
      if git tag -a "$ARCHIVE_TAG" "$CURRENT_SHA" -m "$TAG_MSG" 2>&1 | tail -1; then
        :
      else
        echo "[abort] annotated tag create failed"
        exit 1
      fi

      # ----------------------------------------------------------------
      # HARDENING 5: Remote archive tag push HARD GATE
      # ----------------------------------------------------------------
      if git push "$ARCHIVE_REMOTE" "$ARCHIVE_TAG" 2>&1 | tail -2; then
        TAG_PUSH_OK=1
        echo "[push] $ARCHIVE_TAG → $ARCHIVE_REMOTE"
      else
        if [[ "$ALLOW_LOCAL_ONLY" == "1" ]]; then
          TAG_PUSH_OK=0
          echo "[warn] tag push failed; local-only archive (override active)"
        else
          echo "[abort] tag push to $ARCHIVE_REMOTE failed; cross-machine recovery NOT guaranteed"
          echo "        override: AI_CLEANUP_ALLOW_LOCAL_ONLY_ARCHIVE=1 (NOT recommended)"
          # Local tag remains as breadcrumb; branch NOT deleted
          exit 2
        fi
      fi
    fi
  fi
fi

# ----------------------------------------------------------------
# Switch to detached HEAD on origin/main + delete branch
# ----------------------------------------------------------------
DELETED=""
if [[ "$SHOULD_DELETE_LOCAL" == "1" ]]; then
  echo "[switch] detached HEAD on origin/main"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY] would: git switch --detach origin/main + git branch -D $CURRENT_BRANCH"
    DELETED="(dry-run)"
  else
    git switch --detach origin/main 2>&1 | tail -1 || {
      echo "[partial] could not switch to origin/main; branch will not be deleted"
      SHOULD_DELETE_LOCAL=0
    }

    if [[ "$SHOULD_DELETE_LOCAL" == "1" ]]; then
      if git branch -D "$CURRENT_BRANCH" > /dev/null 2>&1; then
        DELETED="$CURRENT_BRANCH"
        echo "[delete] $CURRENT_BRANCH"
      else
        echo "[partial] branch deletion failed"
      fi
    fi
  fi
fi

# ----------------------------------------------------------------
# Audit log entry (POSIX atomic append, multi-user safe)
# ----------------------------------------------------------------
mkdir -p "$(dirname "$LOG_FILE")"
LOG_ENTRY="$NOW|merged|actor=$ACTOR|user=$USER_ID|mode=ai|repo=$REPO_ID|worktree=$WORKTREE_NAME|session=$SESSION_ID|branch=$CURRENT_BRANCH|sha=$CURRENT_SHA|pr=$PR_NUM|archive_tag=$ARCHIVE_TAG|tag_pushed=$TAG_PUSH_OK|deleted=$DELETED|gate=$DELETE_GATE_REASON"
echo "$LOG_ENTRY" >> "$LOG_FILE"

# ----------------------------------------------------------------
# Summary
# ----------------------------------------------------------------
echo
echo "=== AI cleanup summary ==="
echo "  branch:       $CURRENT_BRANCH"
echo "  sha:          $SHORT_SHA"
echo "  repo:         $REPO_ID"
echo "  archive tag:  ${ARCHIVE_TAG:-<none>}"
echo "  tag pushed:   $TAG_PUSH_OK"
echo "  deleted:      ${DELETED:-<kept>}"
echo "  gate:         $DELETE_GATE_REASON"
echo "  audit log:    $LOG_FILE"
echo
if [[ -n "$ARCHIVE_TAG" && "$TAG_PUSH_OK" == "1" ]]; then
  echo "Recovery (cross-machine, 1+ year):"
  echo "  git checkout -b recovery/<name> $ARCHIVE_TAG"
fi

exit 0
