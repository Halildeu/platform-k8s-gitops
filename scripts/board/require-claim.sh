#!/usr/bin/env bash
# scripts/board/require-claim.sh
# ADR-0023 Guardrail PR-8 — fail-closed live-mutation guard.
#
# Verifies that the CALLING session holds an UNEXPIRED CLAIM on the given
# GitHub issue before allowing a live-mutation script (kubectl/argocd/vault/
# ssh wrapper) to proceed.
#
# Codex thread `019e444d` Opsiyon A — focused scope. Worktree-level mkdir
# lock is OUT OF SCOPE (separate follow-up). This script does NOT prevent a
# parallel session from running raw `git checkout`/`rebase` in the same
# worktree; it only closes the live-mutation blast-radius when the claim
# has expired or session/worktree/branch identity drifts.
#
# Usage:
#   bash scripts/board/require-claim.sh <issue>
#     [--worktree <path>]      # default: current git toplevel
#     [--branch <name>]        # default: current branch
#     [--grace-minutes N]      # default: 0 (no grace past expiry)
#     [--quiet]                # suppress success diagnostic
#
# <issue> may be: bare number (resolved via origin/origin remote),
#                 owner/repo#N, or full https URL.
#
# Behavior:
#   - Reads $BOARD_SESSION_ID (REQUIRED). If unset → exit 2 (setup-error).
#   - gh issue view body → parse <!-- agent-state:v1 --> block.
#   - Verifies ALL of (fail-closed):
#       claim_session   == BOARD_SESSION_ID
#       claim_worktree  == passed --worktree (or current toplevel)
#       claim_branch    == passed --branch (or current branch)
#       expires_at      > now  (+ grace-minutes if given)
#   - Exit 0 on full pass; exit 1 on any mismatch with diagnostics +
#     suggested unblock (heartbeat / fresh claim).
#
# Recommended integration in live-mutation runbook/script entrypoints:
#
#   bash scripts/board/require-claim.sh "$ISSUE" \
#     || { echo "Claim invalid — aborting mutation"; exit 1; }
#
# Override `CLAIM_TTL_HOURS` env (consumed by scripts/board-sync.sh) for
# long-running P0 work: e.g. `CLAIM_TTL_HOURS=6 bash scripts/board-sync.sh
# claim 847`. Default lease (2h) is short for multi-step prod migrations.

set -euo pipefail

iso_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Reuses board-sync.sh's parser semantics (sed for "key: value" lines).
state_get() { sed -n "s/^$1: *//p" | head -1; }

usage() {
  sed -n '2,45p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

ISSUE=""
WORKTREE=""
BRANCH=""
GRACE_MIN=0
QUIET=0

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)         usage 0 ;;
    --worktree)        WORKTREE="${2:-}"; shift 2 ;;
    --branch)          BRANCH="${2:-}";   shift 2 ;;
    --grace-minutes)   GRACE_MIN="${2:-0}"; shift 2 ;;
    --quiet)           QUIET=1; shift ;;
    --)                shift; break ;;
    -*)                echo "unknown flag: $1" >&2; exit 2 ;;
    *)                 if [ -z "$ISSUE" ]; then ISSUE="$1"; shift;
                       else echo "extra positional arg: $1" >&2; exit 2; fi ;;
  esac
done

[ -n "$ISSUE" ] || { echo "ERR: issue arg required" >&2; usage 2; }

if [ -z "${BOARD_SESSION_ID:-}" ]; then
  echo "ERR: BOARD_SESSION_ID unset — cannot verify claim ownership" >&2
  echo "     Set BOARD_SESSION_ID to the session that holds the claim." >&2
  echo "     See: bash scripts/board-sync.sh list   # prints suggested ID" >&2
  exit 2
fi

# Resolve issue → REPO + NUM
REPO=""
NUM=""
if [[ "$ISSUE" =~ ^[0-9]+$ ]]; then
  REPO="$(git config --get remote.origin.url 2>/dev/null \
    | sed -E 's|.*github.com[:/]([^/]+/[^/]+)\.git$|\1|; s|\.git$||')"
  NUM="$ISSUE"
elif [[ "$ISSUE" =~ ^([^/]+/[^#]+)#([0-9]+)$ ]]; then
  REPO="${BASH_REMATCH[1]}"; NUM="${BASH_REMATCH[2]}"
elif [[ "$ISSUE" =~ ^https://github.com/([^/]+/[^/]+)/issues/([0-9]+)$ ]]; then
  REPO="${BASH_REMATCH[1]}"; NUM="${BASH_REMATCH[2]}"
else
  echo "ERR: cannot parse issue ref '$ISSUE' (expected bare-N, owner/repo#N, or full URL)" >&2
  exit 2
fi

[ -n "$REPO" ] || { echo "ERR: could not resolve REPO from issue or remote" >&2; exit 2; }

if [ -z "$WORKTREE" ]; then
  WORKTREE="$(git rev-parse --show-toplevel 2>/dev/null || echo unknown)"
fi
if [ -z "$BRANCH" ]; then
  BRANCH="$(git branch --show-current 2>/dev/null || echo unknown)"
fi

# Fetch issue body
BODY="$(gh issue view "$NUM" --repo "$REPO" --json body --jq .body 2>/dev/null || true)"
if [ -z "$BODY" ]; then
  echo "ERR: empty body for $REPO#$NUM (issue not found, no access, or gh CLI not logged in?)" >&2
  exit 1
fi

bsess="$(printf '%s\n' "$BODY" | state_get claim_session)"
bwt="$(printf   '%s\n' "$BODY" | state_get claim_worktree)"
bbr="$(printf   '%s\n' "$BODY" | state_get claim_branch)"
bexp="$(printf  '%s\n' "$BODY" | state_get expires_at)"

FAILS=()
# Codex 019e444d must-fix #2 absorb: identity fields are FAIL-CLOSED — an empty
# claim_worktree / claim_branch in the issue body means identity is NOT
# verifiable; the guard MUST fail rather than silently accept. Previously
# the empty-skip allowed stale/incomplete issue bodies to satisfy the gate
# with only session+expiry matching.
if [ "${bsess:-}" != "$BOARD_SESSION_ID" ]; then
  FAILS+=("session mismatch: body='${bsess:-}' expected='$BOARD_SESSION_ID'")
fi
if [ -z "${bwt:-}" ]; then
  FAILS+=("claim_worktree missing from issue body — identity not verifiable")
elif [ "$bwt" != "$WORKTREE" ]; then
  FAILS+=("worktree mismatch: body='$bwt' expected='$WORKTREE'")
fi
if [ -z "${bbr:-}" ]; then
  FAILS+=("claim_branch missing from issue body — identity not verifiable")
elif [ "$bbr" != "$BRANCH" ]; then
  FAILS+=("branch mismatch: body='$bbr' expected='$BRANCH'")
fi

# `expired` is a distinct fail-class — board-sync.sh heartbeat refuses to
# extend an already-expired lease (must re-claim instead). The unblock
# advice below branches on this flag.
LEASE_EXPIRED=0
if [ -z "${bexp:-}" ] || [ "$bexp" = "none" ]; then
  FAILS+=("expires_at not set (no active claim recorded on issue body)")
  LEASE_EXPIRED=1
else
  NOW_ISO="$(iso_now)"
  if [ "$GRACE_MIN" -gt 0 ] 2>/dev/null; then
    # bexp + grace > now?
    bepoch="$(date -u -d "$bexp" +%s 2>/dev/null \
      || date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$bexp" +%s 2>/dev/null \
      || echo 0)"
    nepoch="$(date -u +%s)"
    threshold=$(( bepoch + GRACE_MIN * 60 ))
    if [ "$threshold" -lt "$nepoch" ]; then
      FAILS+=("lease expired: $bexp + ${GRACE_MIN}m grace < now=$NOW_ISO")
      LEASE_EXPIRED=1
    fi
  else
    if [[ "$bexp" < "$NOW_ISO" ]]; then
      FAILS+=("lease expired: $bexp < now=$NOW_ISO")
      LEASE_EXPIRED=1
    fi
  fi
fi

if [ ${#FAILS[@]} -gt 0 ]; then
  echo "ERR: require-claim FAIL for $REPO#$NUM" >&2
  for f in "${FAILS[@]}"; do
    echo "  - $f" >&2
  done
  echo >&2
  # Codex 019e444d must-fix #3 absorb: heartbeat REFUSES to extend an
  # already-expired lease (board-sync.sh validates this) → operator must
  # re-claim. Pre-expiry the heartbeat path keeps the lease alive.
  echo "To proceed:" >&2
  echo "  1. Inspect current state: bash scripts/board-sync.sh sync-state $NUM" >&2
  echo "  2. Confirm BOARD_SESSION_ID matches the session that opened the claim." >&2
  if [ "$LEASE_EXPIRED" -eq 1 ]; then
    echo "  3. Lease expired — board-sync.sh heartbeat will REFUSE to extend." >&2
    echo "     Re-claim instead (fresh session_id ownership):" >&2
    echo "       bash scripts/board-sync.sh claim $NUM" >&2
  else
    echo "  3. Lease still valid but identity mismatch — heartbeat extends" >&2
    echo "     it but does NOT correct session/worktree/branch fields." >&2
    echo "     Re-claim from the correct worktree/branch:" >&2
    echo "       bash scripts/board-sync.sh claim $NUM" >&2
  fi
  echo "  4. For long-running P0 work, prefer a longer TTL on next claim:" >&2
  echo "       CLAIM_TTL_HOURS=6 bash scripts/board-sync.sh claim $NUM" >&2
  exit 1
fi

if [ "$QUIET" -eq 0 ]; then
  echo "[require-claim] OK $REPO#$NUM session=$BOARD_SESSION_ID worktree=$WORKTREE branch=$BRANCH expires=$bexp"
fi
exit 0
