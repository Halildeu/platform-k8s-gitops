#!/usr/bin/env bash
# Append one Coordination Ledger event to a remote ledger branch with git CAS.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WRITER="$REPO_ROOT/scripts/coordination/append-ledger-event.py"

REMOTE="origin"
LEDGER_BRANCH="coordination-ledger"
LEDGER_PATH="coordination-ledger/events.jsonl"
COMMIT_TITLE="coordination ledger append"
COMMIT_MESSAGE=""
APPEND_ARGS=()

die() {
  printf 'append-ledger-branch: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat >&2 <<'USAGE'
Usage:
  scripts/coordination/append-ledger-branch.sh [options] -- <append-ledger-event args>

Options:
  --remote <name-or-url>       Git remote name or URL (default: origin)
  --branch <branch>            Ledger branch name (default: coordination-ledger)
  --ledger-path <path>         JSONL path inside ledger branch (default: coordination-ledger/events.jsonl)
  --commit-title <title>       Commit title for the ledger append
  --commit-message <message>   Optional commit body

Notes:
  - The ledger branch must already exist; bootstrap is a separate runbook.
  - All arguments after "--" are passed to append-ledger-event.py.
  - The wrapper pushes with --force-with-lease against the fetched branch OID.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --remote)
      REMOTE="${2:-}"
      shift 2
      ;;
    --branch)
      LEDGER_BRANCH="${2:-}"
      shift 2
      ;;
    --ledger-path)
      LEDGER_PATH="${2:-}"
      shift 2
      ;;
    --commit-title)
      COMMIT_TITLE="${2:-}"
      shift 2
      ;;
    --commit-message)
      COMMIT_MESSAGE="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      APPEND_ARGS=("$@")
      break
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[ -n "$REMOTE" ] || die "--remote must not be empty"
[ -n "$LEDGER_BRANCH" ] || die "--branch must not be empty"
[ -n "$LEDGER_PATH" ] || die "--ledger-path must not be empty"
[ -n "$COMMIT_TITLE" ] || die "--commit-title must not be empty"
[ "${#APPEND_ARGS[@]}" -gt 0 ] || die "append-ledger-event args required after --"

case "$LEDGER_PATH" in
  /*|*..*)
    die "--ledger-path must be a relative path without '..'"
    ;;
esac

safe_branch="$(printf '%s' "$LEDGER_BRANCH" | tr -c 'A-Za-z0-9._-' '_')"
tmp_ref="refs/coordination-ledger-cas/${safe_branch}/$$"
remote_ref="refs/heads/$LEDGER_BRANCH"
worktree=""

cleanup() {
  if [ -n "$worktree" ] && [ -d "$worktree" ]; then
    git -C "$REPO_ROOT" worktree remove --force "$worktree" >/dev/null 2>&1 || true
  fi
  git -C "$REPO_ROOT" update-ref -d "$tmp_ref" >/dev/null 2>&1 || true
}
trap cleanup EXIT

git -C "$REPO_ROOT" fetch --quiet --no-tags "$REMOTE" "$remote_ref:$tmp_ref" \
  || die "failed to fetch existing ledger branch '$LEDGER_BRANCH' from '$REMOTE' (bootstrap required)"

remote_oid="$(git -C "$REPO_ROOT" rev-parse "$tmp_ref")"
worktree="$(mktemp -d -t coordination-ledger-branch.XXXXXX)"
git -C "$REPO_ROOT" worktree add --quiet --detach "$worktree" "$tmp_ref" >/dev/null

ledger_file="$worktree/$LEDGER_PATH"
mkdir -p "$(dirname "$ledger_file")"

append_output="$(python3 "$WRITER" --ledger "$ledger_file" "${APPEND_ARGS[@]}")"
rm -f "$ledger_file.lock"

if git -C "$worktree" diff --quiet -- "$LEDGER_PATH"; then
  die "append produced no ledger diff"
fi

git -C "$worktree" add "$LEDGER_PATH"
commit_args=(-m "$COMMIT_TITLE")
if [ -n "$COMMIT_MESSAGE" ]; then
  commit_args+=(-m "$COMMIT_MESSAGE")
fi

git -C "$worktree" \
  -c user.name="${COORDINATION_LEDGER_GIT_USER_NAME:-coordination-ledger-bot}" \
  -c user.email="${COORDINATION_LEDGER_GIT_USER_EMAIL:-coordination-ledger-bot@acik.local}" \
  commit "${commit_args[@]}" >/dev/null

new_oid="$(git -C "$worktree" rev-parse HEAD)"
git -C "$worktree" push --quiet "$REMOTE" "HEAD:$remote_ref" \
  --force-with-lease="$remote_ref:$remote_oid" >/dev/null \
  || die "remote_cas_mismatch branch=$LEDGER_BRANCH expected=$remote_oid"

python3 - "$append_output" "$REMOTE" "$LEDGER_BRANCH" "$remote_oid" "$new_oid" <<'PY'
from __future__ import annotations

import json
import sys

append_result = json.loads(sys.argv[1])
print(
    json.dumps(
        {
            "remote": sys.argv[2],
            "branch": sys.argv[3],
            "previous_branch_oid": sys.argv[4],
            "new_branch_oid": sys.argv[5],
            "append": append_result,
        },
        sort_keys=True,
    )
)
PY
