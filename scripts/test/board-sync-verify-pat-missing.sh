#!/usr/bin/env bash
# scripts/test/board-sync-verify-pat-missing.sh
#
# Offline harness for `scripts/board-sync.sh verify` PAT-missing fallback
# (#1085, Codex 019e8079 must_fix #4; iter-2 P1 + iter-3 P1 follow-ups
# absorbed in 019e809d). Drives the verify subcommand under a synthetic
# `gh` shim that records every call and produces deterministic responses
# for the ten PAT-state / PR-body parsing scenarios:
#
#   1. PAT present (canonical):           Project API touched, board moves.
#   2. PAT missing, same-repo ref:        comment-only, no Project API.
#   3. PAT missing, cross-repo ref:       skipped with ::warning::.
#   4. PAT missing, repeated EVIDENCE:    idempotent (no duplicate comment).
#   5. PAT present REPAIR (iter-2 P1):    pre-existing EVIDENCE, body
#                                         rewrite + board STILL fire
#                                         (iter-3 P1 #2: body half
#                                         assertion).
#   6. PAT missing, lowercase same-repo   case-insensitive owner/repo
#      (iter-3 P1 #3):                    compare — NOT cross-repo-skipped.
#   7. PAT missing, repo-only cross-repo  platform-ai#N shorthand normalizes
#      shorthand:                         to same-owner repo and soft-skips.
#   8. PAT missing, invalid owner#N:      owner#N-shaped typo soft-skips
#                                         before any issue/project call.
#   9. Workflow Tracked-by extraction:    repo#N is extracted as a full token,
#                                         not truncated to bare #N.
#   10. Both tokens empty (workflow bug): workflow-level guard, asserted
#                                         by inspecting the workflow file.
#
# All ten scenarios run hermetically — no GitHub network access — so a
# regression that re-introduces a Project API call on the PAT-missing
# branch (or drops the body rewrite half of the repair guarantee) is
# caught locally instead of waiting for a real merge.
#
# Usage:
#   bash scripts/test/board-sync-verify-pat-missing.sh
#
# Exit 0 on success, 1 on any failure.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BOARD_SYNC="$REPO_ROOT/scripts/board-sync.sh"
WORKFLOW="$REPO_ROOT/.github/workflows/board-pr-evidence.yml"

# Each test gets its own work dir + its own GH_LOG so calls don't bleed.
WORK="$(mktemp -d -t board-sync-test.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# ---------------------------------------------------------------------------
# fake gh shim — logs every invocation; the dispatch table below decides what
# to print for each invocation. The script writes to:
#   $GH_LOG  — full argv per call (newline-separated)
#   stdout   — whatever the scenario's table says
# Project API calls must NOT happen on PAT-missing paths; the test asserts
# that by grepping the log.
# ---------------------------------------------------------------------------
FAKE_GH="$WORK/bin/gh"
mkdir -p "$WORK/bin"
cat >"$FAKE_GH" <<'FAKE_GH_EOF'
#!/usr/bin/env bash
# fake gh — driven by $GH_FAKE_MODE
set -euo pipefail

# Record the invocation (argv joined with spaces, one per line).
{
  printf '%s' "$*"
  printf '\n'
} >>"${GH_LOG:-/dev/null}"

# auth status: always pass (we treat token presence as "valid").
if [ "${1:-}" = "auth" ] && [ "${2:-}" = "status" ]; then
  exit 0
fi

if [ "${1:-}" = "api" ] && [ "${2:-}" = "rate_limit" ]; then
  printf '{"limit":5000,"remaining":100,"reset":1781347433,"used":4900}\n'
  exit 0
fi

if [ "${1:-}" = "api" ] && [ "${2:-}" = "graphql" ]; then
  case "${GH_FAKE_MODE:-}" in
    pat-present|pat-present-repair)
      joined=" $* "
      if printf '%s' "$joined" | grep -q 'updateProjectV2ItemFieldValue'; then
        printf 'PVTI_test_42\n'
      else
        jq -n '{
          data: {
            repository: {
              issue: {
                number: 42,
                title: "test issue 42",
                url: "https://github.com/Halildeu/platform-k8s-gitops/issues/42",
                projectItems: {
                  nodes: [
                    {
                      id: "PVTI_test_42",
                      project: { id: "PVT_kwHOCx7tY84BIN2d" },
                      fieldValues: {
                        nodes: [
                          { __typename: "ProjectV2ItemFieldSingleSelectValue", name: "In Progress", optionId: "6e2ec368", field: { name: "Status", id: "PVTSSF_lAHOCx7tY84BIN2dzg4vgLw" } },
                          { __typename: "ProjectV2ItemFieldSingleSelectValue", name: "issue", optionId: "22b29779", field: { name: "Kind", id: "PVTSSF_lAHOCx7tY84BIN2dzhTGxFk" } },
                          { __typename: "ProjectV2ItemFieldSingleSelectValue", name: "Faz 23", optionId: "7ff54758", field: { name: "Faz", id: "PVTSSF_lAHOCx7tY84BIN2dzhTGqF0" } },
                          { __typename: "ProjectV2ItemFieldSingleSelectValue", name: "gitops", optionId: "4b80f631", field: { name: "Track", id: "PVTSSF_lAHOCx7tY84BIN2dzhTGqHY" } },
                          { __typename: "ProjectV2ItemFieldSingleSelectValue", name: "P0", optionId: "951c13f7", field: { name: "Priority", id: "PVTSSF_lAHOCx7tY84BIN2dzhTGqHk" } }
                        ]
                      }
                    }
                  ]
                }
              }
            }
          }
        }'
      fi
      exit 0
      ;;
    *)
      echo "fake gh: GraphQL forbidden on this path" >&2
      exit 99
      ;;
  esac
fi

case "${GH_FAKE_MODE:-}" in
  pat-present)
    # Full path: project view, item-list, issue view (no comments),
    # issue comment (new), issue view (body), issue edit, item-edit.
    if [ "${1:-}" = "project" ] && [ "${2:-}" = "view" ]; then
      printf '{"id":"PVT_kwHOCx7tY84BIN2d","number":2}\n'
      exit 0
    fi
    if [ "${1:-}" = "project" ] && [ "${2:-}" = "item-list" ]; then
      cat <<'ITEMS_EOF'
{"items":[{"id":"PVTI_test_42","content":{"type":"Issue","number":42,"url":"https://github.com/Halildeu/platform-k8s-gitops/issues/42"},"status":"In Progress","kind":"","title":"test issue 42"}]}
ITEMS_EOF
      exit 0
    fi
    if [ "${1:-}" = "issue" ] && [ "${2:-}" = "view" ]; then
      # comments lookup → empty; body lookup → no agent-state
      for arg in "$@"; do
        if [ "$arg" = "comments" ]; then
          printf '{"comments":[]}\n'
          exit 0
        fi
      done
      printf '{"body":"no agent state here"}\n'
      exit 0
    fi
    if [ "${1:-}" = "issue" ] && [ "${2:-}" = "comment" ]; then exit 0; fi
    if [ "${1:-}" = "issue" ] && [ "${2:-}" = "edit" ]; then exit 0; fi
    if [ "${1:-}" = "project" ] && [ "${2:-}" = "item-edit" ]; then exit 0; fi
    ;;

  pat-present-repair)
    # Codex 019e8079 iter-2 P1 + 019e809d iter-3 P1 #2: pre-existing
    # EVIDENCE comment, PAT now present, board still In Progress, body
    # carries agent-state:v1 from the original claim. The fixed
    # cmd_verify must:
    #   - SKIP the comment (already there — idempotent),
    #   - REWRITE the body (agent-state → needs-verify),
    #   - MOVE the board (project item-edit).
    # The shim returns a body that contains agent-state:v1 so the body
    # rewrite branch fires and `gh issue edit` gets called — that's the
    # iter-3 P1 #2 hardening (earlier the body shim said "no agent
    # state here" and the body rewrite quietly never ran, so the
    # repair guarantee was only half-tested).
    if [ "${1:-}" = "project" ] && [ "${2:-}" = "view" ]; then
      printf '{"id":"PVT_kwHOCx7tY84BIN2d","number":2}\n'; exit 0
    fi
    if [ "${1:-}" = "project" ] && [ "${2:-}" = "item-list" ]; then
      cat <<'ITEMS_EOF'
{"items":[{"id":"PVTI_test_42","content":{"type":"Issue","number":42,"url":"https://github.com/Halildeu/platform-k8s-gitops/issues/42"},"status":"In Progress","kind":"","title":"test issue 42"}]}
ITEMS_EOF
      exit 0
    fi
    if [ "${1:-}" = "issue" ] && [ "${2:-}" = "view" ]; then
      for arg in "$@"; do
        if [ "$arg" = "comments" ]; then
          # canonical idempotency marker (matches the EVIDENCE shape
          # that the PAT-missing run would have posted)
          printf '{"comments":[{"body":"EVIDENCE type=pr-merged pr_repo=Halildeu/platform-k8s-gitops pr=99 issue_repo=Halildeu/platform-k8s-gitops at=2026-06-01T00:00:00Z"}]}\n'
          exit 0
        fi
      done
      # body lookup: needs to carry `agent-state:v1` so the rewrite
      # branch in cmd_verify fires.  Real gh emits the raw body when
      # called with --jq .body; we mimic that by printing the literal
      # body when --jq is in argv, and the JSON form otherwise.
      for arg in "$@"; do
        if [ "$arg" = "--jq" ]; then
          printf 'agent-state:v1 owner=ci action=in-progress\n'
          exit 0
        fi
      done
      printf '{"body":"agent-state:v1 owner=ci action=in-progress"}\n'; exit 0
    fi
    if [ "${1:-}" = "issue" ] && [ "${2:-}" = "comment" ]; then
      echo "fake gh: repair path must NOT post a comment (EVIDENCE already present)" >&2
      exit 99
    fi
    if [ "${1:-}" = "issue" ] && [ "${2:-}" = "edit" ]; then exit 0; fi
    if [ "${1:-}" = "project" ] && [ "${2:-}" = "item-edit" ]; then exit 0; fi
    ;;

  pat-missing-same-repo)
    # Comment-only path: issue view (no comments), issue view (number
    # exists), issue comment. NO project/* calls allowed.
    if [ "${1:-}" = "project" ]; then
      echo "fake gh: project API forbidden on PAT-missing path" >&2
      exit 99
    fi
    if [ "${1:-}" = "issue" ] && [ "${2:-}" = "view" ]; then
      for arg in "$@"; do
        case "$arg" in
          comments) printf '{"comments":[]}\n'; exit 0 ;;
          number)   printf '{"number":42}\n';    exit 0 ;;
        esac
      done
      printf '{}\n'; exit 0
    fi
    if [ "${1:-}" = "issue" ] && [ "${2:-}" = "comment" ]; then exit 0; fi
    ;;

  pat-missing-cross-repo)
    # Even tighter: cross-repo ref is detected pre-call. We should never
    # touch the network for a cross-repo skip. Any gh call besides
    # `auth status` is a test failure.
    if [ "${1:-}" = "issue" ] || [ "${1:-}" = "project" ]; then
      echo "fake gh: cross-repo skip must not call any gh subcommand" >&2
      exit 99
    fi
    ;;

  pat-missing-idempotent)
    # Same-repo path with a pre-existing EVIDENCE comment carrying the
    # canonical idempotency key. Should short-circuit before any comment
    # post.
    if [ "${1:-}" = "project" ]; then
      echo "fake gh: project API forbidden on PAT-missing path" >&2
      exit 99
    fi
    if [ "${1:-}" = "issue" ] && [ "${2:-}" = "view" ]; then
      for arg in "$@"; do
        case "$arg" in
          comments)
            printf '{"comments":[{"body":"EVIDENCE type=pr-merged pr_repo=Halildeu/platform-k8s-gitops pr=99 issue_repo=Halildeu/platform-k8s-gitops at=2026-06-01T00:00:00Z"}]}\n'
            exit 0
            ;;
          number) printf '{"number":42}\n'; exit 0 ;;
        esac
      done
      printf '{}\n'; exit 0
    fi
    if [ "${1:-}" = "issue" ] && [ "${2:-}" = "comment" ]; then
      echo "fake gh: idempotent path must NOT post a comment" >&2
      exit 99
    fi
    ;;

  *)
    echo "fake gh: GH_FAKE_MODE='${GH_FAKE_MODE:-}' unknown" >&2
    exit 98
    ;;
esac
FAKE_GH_EOF
chmod +x "$FAKE_GH"

# Stub jq too? Real jq is fine and present on every CI runner; keep it.
PATH="$WORK/bin:$PATH"
export PATH

# ---------------------------------------------------------------------------
# Test runner — each scenario sets up its env, runs board-sync.sh verify,
# asserts on the gh call log + the exit status.
# ---------------------------------------------------------------------------
pass=0
fail=0
run_case() {
  local name="$1" mode="$2" expected_rc="$3"
  shift 3
  local log
  log="$WORK/$name.log"

  GH_LOG="$log" \
  GH_FAKE_MODE="$mode" \
  bash "$BOARD_SYNC" "$@" 2>"$WORK/$name.stderr"
  local rc=$?

  if [ "$rc" -eq "$expected_rc" ]; then
    pass=$((pass + 1))
    printf '  ✓ %s\n' "$name"
  else
    fail=$((fail + 1))
    printf '  ✗ %s — expected rc=%d got rc=%d\n' "$name" "$expected_rc" "$rc"
    printf '    stderr: %s\n' "$(head -5 "$WORK/$name.stderr" | tr '\n' ' ')"
  fi

  # Each test owns post-conditions — record them in $LAST_LOG for the
  # caller to inspect with grep.
  LAST_LOG="$log"
}

assert_log_contains() {
  if grep -q "$1" "$LAST_LOG"; then
    printf '    ✓ log contains: %s\n' "$1"
  else
    fail=$((fail + 1))
    printf '    ✗ log MISSING: %s\n' "$1"
    printf '      log was: %s\n' "$(tr '\n' '|' <"$LAST_LOG" | head -c 200)"
  fi
}

assert_log_lacks() {
  if grep -q "$1" "$LAST_LOG"; then
    fail=$((fail + 1))
    printf '    ✗ log SHOULD NOT contain: %s\n' "$1"
  else
    printf '    ✓ log clean of: %s\n' "$1"
  fi
}

printf 'board-sync.sh verify — PAT-missing harness (Codex 019e8079 must_fix #4)\n'
printf -- '----------------------------------------------------------------------\n'

# Scenario 1: PAT present (happy path)
printf '\n[1] PAT present — full path uses Project API\n'
unset BOARD_PAT_PRESENT
export BOARD_PAT_PRESENT=1
run_case "pat-present" "pat-present" 0 \
  verify "https://github.com/Halildeu/platform-k8s-gitops/issues/42" \
  --pr 99 --pr-repo "Halildeu/platform-k8s-gitops"
assert_log_contains "project view"
assert_log_contains "issue comment"
# Codex 019e8079 iter-2 nit: also assert the full path actually moves
# the board. The implementation now uses direct updateProjectV2ItemFieldValue
# via gh api graphql instead of opaque gh project item-edit.
assert_log_contains "api graphql"
assert_log_lacks "project item-list"

# Scenario 2: PAT missing, same-repo ref
printf '\n[2] PAT missing, same-repo — comment-only, NO Project API\n'
export BOARD_PAT_PRESENT=""
run_case "pat-missing-same" "pat-missing-same-repo" 0 \
  verify "https://github.com/Halildeu/platform-k8s-gitops/issues/42" \
  --pr 99 --pr-repo "Halildeu/platform-k8s-gitops"
assert_log_contains "issue comment"
assert_log_lacks "project view"
assert_log_lacks "project item-list"
assert_log_lacks "api graphql"
assert_log_lacks "issue edit"   # body rewrite must be skipped (drift guard)

# Scenario 3: PAT missing, cross-repo ref
printf '\n[3] PAT missing, cross-repo — skip with warning, no network\n'
export BOARD_PAT_PRESENT=""
run_case "pat-missing-cross" "pat-missing-cross-repo" 0 \
  verify "https://github.com/Halildeu/platform-backend/issues/99" \
  --pr 99 --pr-repo "Halildeu/platform-k8s-gitops"
# Allow `gh auth status` (single call) but NO issue/project calls.
if grep -E "^(issue|project) " "$LAST_LOG" >/dev/null 2>&1; then
  fail=$((fail + 1))
  printf '    ✗ cross-repo skip should have made no issue/project gh calls\n'
else
  printf '    ✓ no issue/project gh calls (cross-repo skip clean)\n'
fi

# Scenario 4: PAT missing, repeated EVIDENCE (idempotent)
printf '\n[4] PAT missing, idempotent — pre-existing EVIDENCE → no new comment\n'
export BOARD_PAT_PRESENT=""
run_case "pat-missing-idem" "pat-missing-idempotent" 0 \
  verify "https://github.com/Halildeu/platform-k8s-gitops/issues/42" \
  --pr 99 --pr-repo "Halildeu/platform-k8s-gitops"
assert_log_lacks "issue comment"
assert_log_contains "issue view"

# Scenario 5: PAT-present REPAIR — comment already exists, body STILL
# gets rewritten, board STILL moves.
# Codex 019e8079 iter-2 P1: idempotency must skip the comment but still
# let body rewrite + board Status mutation run. Without this case the
# earlier implementation silently no-op'd the board move on every
# repair run.
# Codex 019e809d iter-3 P1 #2: the earlier shim returned a body that
# did NOT contain agent-state:v1, so the body rewrite branch was
# implicitly never exercised. Shim now returns a body WITH
# agent-state:v1; assertion below confirms `gh issue edit` fires.
printf '\n[5] PAT present REPAIR — comment exists → no new comment, body rewrite + board STILL fire\n'
export BOARD_PAT_PRESENT=1
run_case "pat-present-repair" "pat-present-repair" 0 \
  verify "https://github.com/Halildeu/platform-k8s-gitops/issues/42" \
  --pr 99 --pr-repo "Halildeu/platform-k8s-gitops"
assert_log_lacks "issue comment"
assert_log_contains "issue edit"      # body rewrite half (iter-3 P1 #2)
assert_log_contains "api graphql"  # board Status half

# Scenario 6: PAT missing, lowercase same-repo ref — case-insensitive
# compare must NOT trigger the cross-repo skip.
# Codex 019e809d iter-3 P1 #3: GitHub treats owner/repo identity
# case-insensitively; manual lowercase refs like
# `halildeu/platform-k8s-gitops#42` should still be recognised as
# same-repo and take the comment-only path. Pre-fix this would have
# false-cross-repo-skipped.
printf '\n[6] PAT missing, lowercase same-repo — case-insensitive compare, NOT skipped\n'
export BOARD_PAT_PRESENT=""
run_case "pat-missing-lowercase" "pat-missing-same-repo" 0 \
  verify "https://github.com/halildeu/platform-k8s-gitops/issues/42" \
  --pr 99 --pr-repo "Halildeu/platform-k8s-gitops"
assert_log_contains "issue comment"   # took the same-repo path, not the cross-repo skip
assert_log_lacks "project view"

# Scenario 7: PAT missing, repo-only cross-repo shorthand — `platform-ai#198`
# must normalize to `Halildeu/platform-ai#198`, then soft-skip on the
# PAT-missing path. Pre-fix, the workflow extracted bare `#198` and the
# script attempted to comment on Halildeu/platform-k8s-gitops#198.
printf '\n[7] PAT missing, repo-only cross-repo shorthand — normalize then skip\n'
export BOARD_PAT_PRESENT=""
run_case "pat-missing-repo-only-cross" "pat-missing-cross-repo" 0 \
  verify "platform-ai#198" \
  --pr 99 --pr-repo "Halildeu/platform-k8s-gitops"
if grep -E "^(issue|project) " "$LAST_LOG" >/dev/null 2>&1; then
  fail=$((fail + 1))
  printf '    ✗ repo-only cross-repo skip should have made no issue/project gh calls\n'
else
  printf '    ✓ no issue/project gh calls (repo-only cross-repo skip clean)\n'
fi

# Scenario 8: PAT missing, invalid owner#N-shaped typo. If someone writes
# `Tracked by Halildeu#198`, the repo-only normalizer must not construct
# `Halildeu/Halildeu#198` and then comment on a wrong issue.
printf '\n[8] PAT missing, invalid owner#N typo — skip before issue/project calls\n'
export BOARD_PAT_PRESENT=""
run_case "pat-missing-owner-typo" "pat-missing-cross-repo" 0 \
  verify "Halildeu#198" \
  --pr 99 --pr-repo "Halildeu/platform-k8s-gitops"
if grep -E "^(issue|project) " "$LAST_LOG" >/dev/null 2>&1; then
  fail=$((fail + 1))
  printf '    ✗ owner#N typo should have made no issue/project gh calls\n'
else
  printf '    ✓ no issue/project gh calls (owner#N typo skipped cleanly)\n'
fi

# Scenario 9: Workflow extraction — assert repo-only shorthand is captured as
# a full token before the bare `#N` fallback. This mirrors the regex in
# .github/workflows/board-pr-evidence.yml so the exact regression that hit
# PR #2094 is caught locally.
printf '\n[9] Workflow extraction — repo-only shorthand is not truncated\n'
tracked_refs="$(printf '%s\n' \
    'Tracked by platform-ai#198.' \
    'Tracked by #1615.' \
  | grep -iE '^[[:space:]]*tracked[ -]?by\b' \
  | grep -oE '(https://github\.com/[^ ]+/issues/[0-9]+|[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#[0-9]+|[A-Za-z0-9._-]+#[0-9]+|#[0-9]+)' \
  | paste -sd ',' -)"
if [ "$tracked_refs" = "platform-ai#198,#1615" ]; then
  pass=$((pass + 1))
  printf '  ✓ workflow regex extracts repo-only shorthand before bare issue fallback\n'
else
  fail=$((fail + 1))
  printf '  ✗ workflow regex extraction mismatch: %s\n' "$tracked_refs"
fi

# Scenario 10: Workflow guard — assert both-token-empty trips the workflow
# (file-level grep; the actual run is gated by GitHub Actions).
printf '\n[10] Workflow guard — empty-token branch fails loudly\n'
if grep -q "GH_TOKEN is empty" "$WORKFLOW"; then
  pass=$((pass + 1))
  printf '  ✓ workflow has empty-GH_TOKEN ::error:: guard\n'
else
  fail=$((fail + 1))
  printf '  ✗ workflow MISSING empty-GH_TOKEN ::error:: guard\n'
fi

printf '\n----------------------------------------------------------------------\n'
printf 'pass=%d fail=%d\n' "$pass" "$fail"
exit "$fail"
