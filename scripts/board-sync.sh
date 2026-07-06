#!/usr/bin/env bash
# scripts/board-sync.sh
#
# platform Roadmap (GitHub Project #2) agent sync tool.
# Makes the board an active, session-continuous, parallel-safe work surface.
# Protocol (canonical): docs/board-protocol.md
#
# Usage: board-sync.sh <subcommand> [<arg>] [flags]
#
# Subcommands:
#   list                  eligible Todo work + In Progress + Backlog counts
#   claim      <issue>    deterministic race-safe claim
#   heartbeat  <issue>    extend your active claim's lease
#   release    <issue>    release your claim (ownership-checked)
#   sync-state <issue>    report issue-body agent-state vs board Status
#   require-claim         read-only operation-scoped claim permission check
#   record-deny           queue DENY_RECORDED intent when CAS writer unavailable
#   graphql-budget        REST rate-limit guard for Project v2 GraphQL budget
#   drain-project-queue   apply low-risk PROJECT-DEFERRED markers
#   verify     <issue>    PR-merge evidence: Status -> Needs Verify (--pr N)
#   reap                  release every stale In Progress claim
#   backlog-add "<title>" capture discovered work as a Backlog issue
#
# Flags:
#   --dry-run             print mutations instead of executing them
#   --force-stale         (release) release another session's expired claim
#   --pr <N>              (verify) the merged PR number
#   --pr-repo <owner/rp>  (verify) the merged PR's source repo
#   --repo <owner/repo>   (verify) issue-ref disambig; (backlog-add) target repo
#   --limit <N>           (reap) max items per run (default 20)
#   --note "<text>"       (backlog-add) context for the captured item
#   --kind issue|risk     (backlog-add) board Kind (default issue)
#   --issue <N|url>       (require-claim) issue to verify
#   --session <id>        (require-claim) expected BOARD_SESSION_ID
#   --operation <class>   (require-claim) operation boundary to verify
#   --worktree <path>     (require-claim) expected worktree (default: current)
#   --branch <name>       (require-claim) expected branch (default: current)
#   --mutation-risk <r>   (graphql-budget) none|low-risk|critical
#   --intent <json>       (record-deny) deny intent JSON from require-claim
#   --intent-file <path>  (record-deny) deny intent JSON file, or '-' for stdin
#
# <issue>: bare number (resolved via board), owner/repo#N, or full URL.
# Session id: $BOARD_SESSION_ID if set, else generated and printed.
set -euo pipefail

# --- board reference (see docs/board-protocol.md section 13) ------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_OWNER="Halildeu"
PROJECT_NUMBER="2"
PROJECT_ID="PVT_kwHOCx7tY84BIN2d"
STATUS_FIELD="PVTSSF_lAHOCx7tY84BIN2dzg4vgLw"
STATUS_BACKLOG="81ee9923"
STATUS_TODO="da11d7ac"
STATUS_INPROGRESS="6e2ec368"
STATUS_NEEDSVERIFY="516d2beb"
STATUS_BACKLOG_NAME="Backlog"
STATUS_TODO_NAME="Todo"
STATUS_INPROGRESS_NAME="In Progress"
STATUS_NEEDSVERIFY_NAME="Needs Verify"
KIND_FIELD="PVTSSF_lAHOCx7tY84BIN2dzhTGxFk"
KIND_ISSUE="22b29779"
KIND_RISK="e3a49d4e"
PROJECT_ITEM_LIMIT="${PROJECT_ITEM_LIMIT:-1000}"
PROJECT_GRAPHQL_MIN_REMAINING="${PROJECT_GRAPHQL_MIN_REMAINING:-1}"
PROJECT_TRUTH_TTL_SECONDS="${PROJECT_TRUTH_TTL_SECONDS:-300}"
PROJECT_FIELD_CATALOG="${PROJECT_FIELD_CATALOG:-docs/coordination/project-field-catalog-v1.json}"
COORDINATION_AUDIT_DEBT_QUEUE="${COORDINATION_AUDIT_DEBT_QUEUE:-.local/coordination-audit-debt.jsonl}"
COORDINATION_LEDGER_PATH="${COORDINATION_LEDGER_PATH:-}"
COORDINATION_LEDGER_CLAIM_STATE="${COORDINATION_LEDGER_CLAIM_STATE:-$REPO_ROOT/scripts/coordination/ledger-claim-state.py}"
if ! [[ "$PROJECT_ITEM_LIMIT" =~ ^[0-9]+$ ]] || [ "$PROJECT_ITEM_LIMIT" -lt 200 ]; then
  echo "ERR: PROJECT_ITEM_LIMIT='$PROJECT_ITEM_LIMIT' must be an integer >= 200" >&2
  exit 2
fi
if ! [[ "$PROJECT_GRAPHQL_MIN_REMAINING" =~ ^[0-9]+$ ]]; then
  echo "ERR: PROJECT_GRAPHQL_MIN_REMAINING='$PROJECT_GRAPHQL_MIN_REMAINING' must be a non-negative integer" >&2
  exit 2
fi
if ! [[ "$PROJECT_TRUTH_TTL_SECONDS" =~ ^[0-9]+$ ]]; then
  echo "ERR: PROJECT_TRUTH_TTL_SECONDS='$PROJECT_TRUTH_TTL_SECONDS' must be a non-negative integer" >&2
  exit 2
fi
# 2026-05-20 — Guardrail PR-8 (Codex 019e444d must-fix #1 absorb): env
# override `CLAIM_TTL_HOURS=N bash scripts/board-sync.sh claim …` previously
# was overwritten by the hardcoded `="2"`. Default 2 stays for back-compat
# but the env value, if set, is honored. Numeric guard prevents silent
# claim_expiry_iso() math failure on bad input.
CLAIM_TTL_HOURS="${CLAIM_TTL_HOURS:-2}"
if ! [[ "$CLAIM_TTL_HOURS" =~ ^[0-9]+$ ]]; then
  echo "ERR: CLAIM_TTL_HOURS='$CLAIM_TTL_HOURS' must be a positive integer" >&2
  exit 2
fi

DRY_RUN=0
FORCE_STALE=0
OPT_PR=""
OPT_PR_REPO=""
OPT_REPO=""
OPT_LIMIT=""
OPT_NOTE=""
OPT_KIND=""
OPT_ISSUE=""
OPT_SESSION=""
OPT_OPERATION=""
OPT_WORKTREE=""
OPT_BRANCH=""
OPT_MUTATION_RISK=""
OPT_INTENT=""
OPT_INTENT_FILE=""
BOARD_CACHE=""
ITEM_JSON=""

# --- helpers ------------------------------------------------------------------
log()  { printf '%s\n' "$*" >&2; }
die()  { printf 'board-sync: %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '4,40p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

cleanup() { [ -n "$BOARD_CACHE" ] && rm -f "$BOARD_CACHE" || true; }
trap cleanup EXIT

iso_now()   { date -u +%Y-%m-%dT%H:%M:%SZ; }
epoch_now() { date -u +%s; }

epoch_to_iso() {
  # portable: BSD (-r) then GNU (-d @)
  date -u -r "$1" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
    || date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ
}

claim_expiry_iso() {
  epoch_to_iso "$(( $(epoch_now) + CLAIM_TTL_HOURS * 3600 ))"
}

session_id() {
  if [ -n "${BOARD_SESSION_ID:-}" ]; then
    printf '%s' "$BOARD_SESSION_ID"
  else
    printf '%s' "$(hostname -s 2>/dev/null || echo host)-$$-$(epoch_now)"
  fi
}

# read one agent-state:v1 key from an issue body (stdin)
state_get() { sed -n "s/^$1: *//p" | head -1; }

project_graphql_rate_json() {
  gh api rate_limit --jq '.resources.graphql' 2>/dev/null || true
}

project_graphql_remaining() {
  local raw
  raw="$(project_graphql_rate_json)"
  printf '%s' "$raw" | jq -er '.remaining // empty' 2>/dev/null || printf 'unknown'
}

project_graphql_is_exhausted() {
  local remaining
  remaining="$(project_graphql_remaining)"
  [ "$remaining" != "unknown" ] && [ "$remaining" -le "$PROJECT_GRAPHQL_MIN_REMAINING" ]
}

budget_operation_known() {
  case "$1" in
    local_edit|file_write|stage|commit|push|pr_create|pr_update|live_mutation|release|deploy|issue_close|recovery|key_rotation|claim|list|sync-state|backlog-add|reap|verify|drain-project-queue)
      return 0 ;;
    *) return 1 ;;
  esac
}

require_claim_rest_only_operation() {
  case "$1" in
    local_edit|file_write|stage|commit|push|pr_create|pr_update)
      return 0 ;;
    *) return 1 ;;
  esac
}

require_claim_fresh_project_truth_operation() {
  case "$1" in
    live_mutation|deploy|issue_close|recovery|key_rotation)
      return 0 ;;
    *) return 1 ;;
  esac
}

graphql_budget_decision() {
  # graphql_budget_decision <operation> <mutation-risk> <remaining-or-unknown>
  local operation="$1" risk="$2" remaining="$3"
  if [ "$remaining" = "unknown" ]; then
    printf 'continue\tgraphql_budget_unknown'
    return 0
  fi
  if [ "$remaining" -gt "$PROJECT_GRAPHQL_MIN_REMAINING" ]; then
    printf 'continue\tgraphql_budget_available'
    return 0
  fi
  case "$operation" in
    local_edit|file_write|stage)
      printf 'continue\tno_project_mutation_required'
      ;;
    commit|push|pr_create|pr_update|verify)
      if [ "$risk" = "low-risk" ]; then
        printf 'defer\tgraphql_exhausted_low_risk_project_mutation'
      elif [ "$risk" = "none" ]; then
        printf 'continue\trest_only_operation'
      else
        printf 'fail\tgraphql_exhausted_critical_or_unknown_mutation'
      fi
      ;;
    claim|list|sync-state|backlog-add|reap|drain-project-queue)
      printf 'fail\tgraphql_exhausted_fresh_project_truth_required'
      ;;
    release)
      if [ "$risk" = "low-risk" ]; then
        printf 'defer\tgraphql_exhausted_release_todo_reconcile'
      else
        printf 'fail\tgraphql_exhausted_release_requires_low_risk'
      fi
      ;;
    live_mutation|deploy|issue_close|recovery|key_rotation)
      printf 'fail\tgraphql_exhausted_critical_operation_fail_closed'
      ;;
    *)
      printf 'fail\tunknown_operation'
      ;;
  esac
}

cmd_graphql_budget() {
  [ -n "$OPT_OPERATION" ] || die "graphql-budget needs --operation <class>"
  budget_operation_known "$OPT_OPERATION" \
    || die "graphql-budget unknown --operation '$OPT_OPERATION'"
  local risk="${OPT_MUTATION_RISK:-none}"
  case "$risk" in
    none|low-risk|critical) : ;;
    *) die "graphql-budget --mutation-risk must be none|low-risk|critical" ;;
  esac

  local raw remaining reset used limit decision reason
  raw="$(project_graphql_rate_json)"
  remaining="$(printf '%s' "$raw" | jq -er '.remaining // empty' 2>/dev/null || printf 'unknown')"
  reset="$(printf '%s' "$raw" | jq -er '.reset // empty' 2>/dev/null || printf 'unknown')"
  used="$(printf '%s' "$raw" | jq -er '.used // empty' 2>/dev/null || printf 'unknown')"
  limit="$(printf '%s' "$raw" | jq -er '.limit // empty' 2>/dev/null || printf 'unknown')"
  IFS=$'\t' read -r decision reason <<<"$(graphql_budget_decision "$OPT_OPERATION" "$risk" "$remaining")"

  jq -n \
    --arg operation "$OPT_OPERATION" \
    --arg mutation_risk "$risk" \
    --arg remaining "$remaining" \
    --arg reset "$reset" \
    --arg used "$used" \
    --arg limit "$limit" \
    --arg decision "$decision" \
    --arg reason "$reason" \
    --arg min_remaining "$PROJECT_GRAPHQL_MIN_REMAINING" \
    '{
      operation: $operation,
      project_mutation_risk: $mutation_risk,
      graphql: {
        remaining: (if $remaining == "unknown" then null else ($remaining | tonumber) end),
        reset: (if $reset == "unknown" then null else ($reset | tonumber) end),
        used: (if $used == "unknown" then null else ($used | tonumber) end),
        limit: (if $limit == "unknown" then null else ($limit | tonumber) end),
        min_remaining: ($min_remaining | tonumber)
      },
      decision: $decision,
      reason: $reason
    }'

  [ "$decision" != "fail" ]
}

preflight() {
  local cmd="${1:-}"
  command -v jq >/dev/null 2>&1 || die "jq not found in PATH"
  if [ "$cmd" = "record-deny" ]; then
    return 0
  fi
  command -v gh >/dev/null 2>&1 || die "gh CLI not found in PATH"
  gh auth status >/dev/null 2>&1 || die "gh not authenticated (gh auth status failed)"
  [ "$cmd" = "graphql-budget" ] && return 0
  # #1085 Codex 019e8079 must_fix #1: skip the Project API probe when
  # BOARD_PAT_PRESENT="" (CI fell back to GITHUB_TOKEN, which has no
  # project scope). The verify subcommand routes to its own PAT-missing
  # comment-only path; other Project-mutating subcommands (claim,
  # release, reap, backlog-add, list, sync-state) will fail later at
  # the actual mutation site, which is the correct loud-fail behaviour
  # for those — they need a PAT to be meaningful at all.
  if [ "${BOARD_PAT_PRESENT-yes}" = "" ]; then
    log "preflight: PAT missing — Project API probe skipped (verify will take comment-only path)"
    return 0
  fi
  if project_graphql_is_exhausted; then
    case "$cmd" in
      verify)
        log "preflight: Project GraphQL budget exhausted — verify will use PROJECT-DEFERRED for low-risk mirror mutation"
        return 0
        ;;
      release)
        log "preflight: Project GraphQL budget exhausted — release will use REST issue update + PROJECT-DEFERRED Todo reconcile"
        return 0
        ;;
      require-claim)
        if require_claim_rest_only_operation "${OPT_OPERATION:-}"; then
          log "preflight: Project GraphQL budget exhausted — require-claim will use REST-only low-risk path for operation=${OPT_OPERATION:-unknown}"
          return 0
        fi
        die "Project GraphQL budget exhausted — require-claim operation '${OPT_OPERATION:-unknown}' needs fresh Project truth"
        ;;
      *)
        die "Project GraphQL budget exhausted — '$cmd' needs fresh Project truth; run 'board-sync.sh graphql-budget --operation $cmd'"
        ;;
    esac
  fi
  local pid
  pid="$(gh project view "$PROJECT_NUMBER" --owner "$PROJECT_OWNER" --format json 2>/dev/null \
    | jq -r '.id // empty')"
  [ "$pid" = "$PROJECT_ID" ] \
    || die "project id mismatch: expected $PROJECT_ID, got '${pid:-none}'"
}

ensure_board_cache() {
  if [ -z "$BOARD_CACHE" ]; then
    BOARD_CACHE="$(board_cache_temp)"
    gh project item-list "$PROJECT_NUMBER" --owner "$PROJECT_OWNER" \
      --format json --limit "$PROJECT_ITEM_LIMIT" >"$BOARD_CACHE" \
      || die "failed to fetch board items"
  fi
}

board_json() {
  local had_cache="${BOARD_CACHE:-}"
  ensure_board_cache
  cat "$BOARD_CACHE"
  if [ -z "$had_cache" ] && [ "${BASH_SUBSHELL:-0}" -gt 0 ]; then
    rm -f "$BOARD_CACHE"
  fi
}

board_cache_temp() {
  local roots=() root path
  [ -n "${BOARD_SYNC_TMPDIR:-}" ] && roots+=("$BOARD_SYNC_TMPDIR")
  [ -n "${TMPDIR:-}" ] && roots+=("$TMPDIR")
  roots+=("$REPO_ROOT/.tmp/board-sync")

  for root in "${roots[@]}"; do
    [ -n "$root" ] || continue
    mkdir -p "$root" 2>/dev/null || continue
    path="$(mktemp "$root/board-sync.XXXXXX" 2>/dev/null)" || continue
    printf '%s' "$path"
    return 0
  done

  die "failed to create board cache temp file; set BOARD_SYNC_TMPDIR to a writable directory"
}

# board_matches <num> <repo-or-empty> -> tab lines: id status url title kind
board_matches() {
  board_json | jq -r --arg n "$1" --arg r "$2" '
    [ .items[]
      | select(.content.type == "Issue")
      | select((.content.number | tostring) == $n)
      | select($r == "" or (.content.url // "" | contains("/" + $r + "/")))
    ]
    | .[] | "\(.id)\t\(.status // "")\t\(.content.url // "")\t\(.title // "")\t\(.kind // "")"'
}

git_remote_repo() {
  local url
  url="$(git config --get remote.origin.url 2>/dev/null || true)"
  case "$url" in
    https://github.com/*.git) printf '%s' "${url#https://github.com/}" | sed 's/\.git$//' ;;
    git@github.com:*.git) printf '%s' "${url#git@github.com:}" | sed 's/\.git$//' ;;
    https://github.com/*) printf '%s' "${url#https://github.com/}" ;;
    git@github.com:*) printf '%s' "${url#git@github.com:}" ;;
    *) printf '' ;;
  esac
}

parse_issue_ref() {
  # parse_issue_ref <number|owner/repo#N|url> -> sets REPO NUM
  local arg="$1"
  REPO=""; NUM=""
  if printf '%s' "$arg" | grep -q '^https://github.com/'; then
    local path
    path="${arg#https://github.com/}"
    REPO="${path%%/issues/*}"
    NUM="${path##*/}"
  elif printf '%s' "$arg" | grep -Eq '^[^/ ]+/[^/ #]+#[0-9]+$'; then
    REPO="${arg%#*}"
    NUM="${arg##*#}"
  else
    NUM="$arg"
    REPO="${OPT_REPO:-$(git_remote_repo)}"
  fi
  printf '%s' "$NUM" | grep -Eq '^[0-9]+$' || die "bad issue ref: '$arg'"
  printf '%s' "$REPO" | grep -Eq '^[^/ ]+/[^/ ]+$' \
    || die "could not resolve repo for issue #$NUM — pass owner/repo#N, full issue URL, or --repo owner/repo"
}

project_issue_item_json() {
  # project_issue_item_json <owner/repo> <number>
  # Targeted Project item bootstrap lookup. This avoids the old hot-path full
  # board scan and uses only the issue's projectItems connection.
  local repo="$1" num="$2" owner name query raw refreshed_epoch refreshed_at
  owner="${repo%%/*}"
  name="${repo#*/}"
  refreshed_epoch="$(epoch_now)"
  refreshed_at="$(epoch_to_iso "$refreshed_epoch")"
  query="$(cat <<'GRAPHQL'
query($owner:String!, $name:String!, $number:Int!) {
  repository(owner:$owner, name:$name) {
    issue(number:$number) {
      number
      title
      url
      projectItems(first:20) {
        nodes {
          id
          project { id }
          fieldValues(first:50) {
            nodes {
              __typename
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                optionId
                field {
                  ... on ProjectV2SingleSelectField { id name }
                }
              }
            }
          }
        }
      }
    }
  }
}
GRAPHQL
)"
  raw="$(gh api graphql \
    -F query="$query" \
    -F owner="$owner" \
    -F name="$name" \
    -F number="$num" 2>/dev/null)" || return 1
  printf '%s' "$raw" \
    | jq -c --arg project_id "$PROJECT_ID" \
        --arg refreshed_at "$refreshed_at" \
        --argjson refreshed_at_epoch "$refreshed_epoch" '
      .data.repository.issue as $issue
      | ($issue.projectItems.nodes // [] | map(select(.project.id == $project_id)) | .[0]) as $item
      | if ($issue == null or $item == null) then empty else
          def fv($n):
            (($item.fieldValues.nodes // [])
              | map(select(.__typename == "ProjectV2ItemFieldSingleSelectValue" and (.field.name // "") == $n))
              | .[0] // {});
          {
            id: $item.id,
            refreshed_at: $refreshed_at,
            refreshed_at_epoch: $refreshed_at_epoch,
            title: ($issue.title // ""),
            status: (fv("Status").name // ""),
            faz: (fv("Faz").name // ""),
            track: (fv("Track").name // ""),
            priority: (fv("Priority").name // ""),
            kind: (fv("Kind").name // ""),
            fieldOptionIds: {
              status: (fv("Status").optionId // ""),
              faz: (fv("Faz").optionId // ""),
              track: (fv("Track").optionId // ""),
              priority: (fv("Priority").optionId // ""),
              kind: (fv("Kind").optionId // "")
            },
            content: {
              type: "Issue",
              number: ($issue.number | tonumber),
              url: ($issue.url // "")
            }
          }
        end'
}

project_item_status_by_id() {
  # project_item_status_by_id <item-id>
  local item_id="$1" query
  query="$(cat <<'GRAPHQL'
query($itemId:ID!) {
  node(id:$itemId) {
    ... on ProjectV2Item {
      id
      fieldValues(first:20) {
        nodes {
          __typename
          ... on ProjectV2ItemFieldSingleSelectValue {
            name
            field {
              ... on ProjectV2SingleSelectField { id name }
            }
          }
        }
      }
    }
  }
}
GRAPHQL
)"
  gh api graphql -F query="$query" -F itemId="$item_id" 2>/dev/null \
    | jq -r '.data.node.fieldValues.nodes[]?
      | select(.__typename == "ProjectV2ItemFieldSingleSelectValue" and (.field.name // "") == "Status")
      | .name' | head -1
}

populate_item_from_json() {
  ITEM_ID="$(printf '%s' "$ITEM_JSON" | jq -r '.id // empty')"
  ITEM_STATUS="$(printf '%s' "$ITEM_JSON" | jq -r '.status // empty')"
  ITEM_KIND="$(printf '%s' "$ITEM_JSON" | jq -r '.kind // empty')"
  [ -n "$ITEM_ID" ] || return 1
}

resolve_issue_optional() {
  # resolve_issue_optional <number|owner/repo#N|url> -> sets REPO NUM ITEM_*
  REPO=""; NUM=""; ITEM_ID=""; ITEM_STATUS=""; ITEM_KIND=""; ITEM_JSON=""
  parse_issue_ref "$1"
  ITEM_JSON="$(project_issue_item_json "$REPO" "$NUM")"
  [ -n "$ITEM_JSON" ] || return 1
  populate_item_from_json
}

# resolve_issue <number|owner/repo#N|url> -> sets REPO NUM ITEM_ID ITEM_STATUS ITEM_KIND ITEM_JSON
resolve_issue() {
  if ! resolve_issue_optional "$1"; then
    die "issue ${REPO:-?}#${NUM:-?} not found on Project #2 via targeted lookup (is it a roadmap issue?)"
  fi
}

set_board_status() {
  # set_board_status <item-id> <option-id> <label>
  if [ "$DRY_RUN" -eq 1 ]; then
    log "[dry-run] board Status -> $3"
    return 0
  fi
  # #1085: graceful skip when CI runs without ADD_TO_PROJECT_PAT. The
  # workflow seeds BOARD_PAT_PRESENT="" when the PAT secret is unset;
  # in that case we cannot mutate the org-level project field
  # (GITHUB_TOKEN has no `project` scope), so log a clear notice and
  # return 0 instead of dying. Interactive use leaves BOARD_PAT_PRESENT
  # unset entirely, in which case the default "yes" still attempts the
  # mutation (the operator's gh auth is expected to carry project
  # scope).
  if [ "${BOARD_PAT_PRESENT-yes}" = "" ]; then
    log "board Status skip — ADD_TO_PROJECT_PAT missing in CI (project mutation requires PAT; issue-comment EVIDENCE half still ran)"
    return 0
  fi
  project_set_single_select "$1" "$STATUS_FIELD" "$2" "Status" "$3"
  log "board Status -> $3"
}

project_set_single_select() {
  # project_set_single_select <item-id> <field-id> <option-id> <field-name> <target-label>
  local item_id="$1" field_id="$2" option_id="$3" field_name="$4" target_label="$5"
  validate_project_option "$field_name" "$field_id" "$target_label" "$option_id"
  if project_graphql_is_exhausted; then
    die "Project GraphQL budget exhausted — cannot set $field_name -> $target_label"
  fi
  local mutation out
  # shellcheck disable=SC2016 # GraphQL variable names must remain literal.
  mutation='mutation($projectId:ID!, $itemId:ID!, $fieldId:ID!, $optionId:String!) {
    updateProjectV2ItemFieldValue(input:{
      projectId:$projectId,
      itemId:$itemId,
      fieldId:$fieldId,
      value:{singleSelectOptionId:$optionId}
    }) { projectV2Item { id } }
  }'
  out="$(gh api graphql \
    -f query="$mutation" \
    -F projectId="$PROJECT_ID" \
    -F itemId="$item_id" \
    -F fieldId="$field_id" \
    -F optionId="$option_id" \
    --jq '.data.updateProjectV2ItemFieldValue.projectV2Item.id // empty' 2>/dev/null)" \
    || die "Project mutation failed — field=$field_name target=$target_label item=$item_id"
  [ "$out" = "$item_id" ] \
    || die "Project mutation returned unexpected item id '${out:-empty}' for $item_id"
}

catalog_field_id() {
  # catalog_field_id <field-name>
  jq -er --arg field "$1" '.fields[$field].id // empty' "$PROJECT_FIELD_CATALOG" 2>/dev/null
}

catalog_option_id() {
  # catalog_option_id <field-name> <option-name>
  jq -er --arg field "$1" --arg option "$2" '.fields[$field].options[$option] // empty' "$PROJECT_FIELD_CATALOG" 2>/dev/null
}

validate_project_option() {
  # validate_project_option <field-name> <field-id> <option-name> <option-id>
  local field_name="$1" field_id="$2" option_name="$3" option_id="$4" expected_field expected_option
  expected_field="$(catalog_field_id "$field_name")" \
    || die "Project field catalog missing field '$field_name' ($PROJECT_FIELD_CATALOG)"
  expected_option="$(catalog_option_id "$field_name" "$option_name")" \
    || die "Project field catalog missing option '$field_name/$option_name'"
  [ "$expected_field" = "$field_id" ] \
    || die "Project field drift: $field_name expected field_id=$expected_field got=$field_id"
  [ "$expected_option" = "$option_id" ] \
    || die "Project option drift: $field_name/$option_name expected option_id=$expected_option got=$option_id"
}

status_option_id() {
  catalog_option_id "Status" "$1"
}

post_comment() {
  # post_comment <repo> <num> <body>
  if [ "$DRY_RUN" -eq 1 ]; then
    log "[dry-run] comment on $1#$2: $3"
    return 0
  fi
  gh issue comment "$2" --repo "$1" --body "$3" >/dev/null 2>&1 \
    || die "failed to post comment on $1#$2"
}

issue_body() { gh issue view "$2" --repo "$1" --json body --jq '.body' 2>/dev/null || echo ""; }

rest_issue_exists() {
  # rest_issue_exists <owner/repo> <num>
  gh api "repos/$1/issues/$2" --jq '.number' >/dev/null 2>&1
}

rest_issue_body() {
  # rest_issue_body <owner/repo> <num>
  gh api "repos/$1/issues/$2" --jq '.body // ""' 2>/dev/null || echo ""
}

rest_issue_comments() {
  # rest_issue_comments <owner/repo> <num>
  gh api --paginate "repos/$1/issues/$2/comments?per_page=100" 2>/dev/null \
    | jq -s '[.[][]?]'
}

rest_comment_contains() {
  # rest_comment_contains <owner/repo> <num> <needle>
  rest_issue_comments "$1" "$2" \
    | jq -e --arg needle "$3" '[.[] | select((.body // "") | contains($needle))] | length > 0' >/dev/null
}

ledger_claim_state_json() {
  # ledger_claim_state_json <repo> <num> <session>
  # Empty output means the ledger predicate is not configured. Non-empty JSON is
  # read-only evidence and may be allowed=false.
  local repo="$1" num="$2" sid="$3" out rc
  [ -n "$COORDINATION_LEDGER_PATH" ] || return 0
  set +e
  out="$(python3 "$COORDINATION_LEDGER_CLAIM_STATE" \
    --ledger "$COORDINATION_LEDGER_PATH" \
    --repo "$repo" \
    --issue "$num" \
    --session "$sid" 2>&1)"
  rc=$?
  set -e
  if ! printf '%s' "$out" | jq -e 'type == "object"' >/dev/null 2>&1; then
    jq -cn --arg ledger "$COORDINATION_LEDGER_PATH" --arg reason "$out" '{
      configured: true,
      ledger: $ledger,
      valid: false,
      allowed: false,
      deny_code: "ledger_claim_state_error",
      reason: $reason
    }'
    return 1
  fi
  printf '%s\n' "$out"
  [ "$rc" -eq 0 ]
}

rest_post_comment() {
  # rest_post_comment <owner/repo> <num> <body>
  if [ "$DRY_RUN" -eq 1 ]; then
    log "[dry-run] REST comment on $1#$2: $3"
    return 0
  fi
  gh api -X POST "repos/$1/issues/$2/comments" -f body="$3" >/dev/null \
    || die "failed to post REST comment on $1#$2"
}

project_deferred_records_json() {
  # project_deferred_records_json <owner/repo> <num>
  rest_issue_comments "$1" "$2" | jq -c '
    . as $comments
    | [ $comments[]
        | select((.body // "") | test("^PROJECT-DEFERRED v1 key=[0-9a-f]{64}\\b"))
        | .body as $body
        | ($body | capture("^PROJECT-DEFERRED v1 key=(?<key>[0-9a-f]{64})")) as $m
        | select(([ $comments[]
            | select((.body // "") | test("^PROJECT-(DRAINED|STALE-SKIP) v1 key=" + $m.key + "\\b"))
          ] | length) == 0)
        | {
            key: $m.key,
            comment_id: .id,
            created_at: .created_at,
            mutation: ((try ($body | capture(" mutation=(?<v>[^ ]+)").v) catch "")),
            target: ((try ($body | capture(" target=\"(?<v>[^\"]+)\"").v) catch "")),
            source: ((try ($body | capture(" source=(?<v>[^ ]+)").v) catch "")),
            issue_repo: ((try ($body | capture(" issue_repo=(?<v>[^ ]+)").v) catch "")),
            issue: ((try ($body | capture(" issue=(?<v>[0-9]+)").v) catch "")),
            pr_repo: ((try ($body | capture(" pr_repo=(?<v>[^ ]+)").v) catch "")),
            pr: ((try ($body | capture(" pr=(?<v>[0-9]+)").v) catch "")),
            body: $body
          }
      ]'
}

pending_needs_verify_deferred_count() {
  project_deferred_records_json "$1" "$2" \
    | jq '[.[] | select(.mutation == "status" and .target == "Needs Verify")] | length'
}

write_body() {
  # write_body <repo> <num> <new-body-on-stdin>
  if [ "$DRY_RUN" -eq 1 ]; then
    log "[dry-run] would update issue body of $1#$2"
    cat >/dev/null
    return 0
  fi
  gh issue edit "$2" --repo "$1" --body-file - >/dev/null \
    || die "failed to update issue body of $1#$2"
}

rewrite_state() {
  # rewrite_state <status> <session> <worktree> <branch> <updated_at> <expires>
  # rewrites the <!-- agent-state:v1 ... --> block read from stdin
  awk -v st="$1" -v se="$2" -v wt="$3" -v br="$4" -v up="$5" -v ex="$6" '
    /^<!-- agent-state:v1/      { inb = 1; print; next }
    inb && /^-->/              { inb = 0; print; next }
    inb && /^status:/          { print "status: " st; next }
    inb && /^claim_session:/   { print "claim_session: " se; next }
    inb && /^claim_worktree:/  { print "claim_worktree: " wt; next }
    inb && /^claim_branch:/    { print "claim_branch: " br; next }
    inb && /^claim_updated_at:/{ print "claim_updated_at: " up; next }
    inb && /^expires_at:/      { print "expires_at: " ex; next }
    { print }
  '
}

append_agent_state_block() {
  # append_agent_state_block <status> <session> <worktree> <branch> <updated_at> <expires>
  cat
  printf '\n\n## Agent State\n\n'
  printf '<!-- agent-state:v1\n'
  printf 'status: %s\n' "$1"
  printf 'claim_session: %s\n' "$2"
  printf 'claim_worktree: %s\n' "$3"
  printf 'claim_branch: %s\n' "$4"
  printf 'claim_updated_at: %s\n' "$5"
  printf 'expires_at: %s\n' "$6"
  printf '%s\n' '-->'
}

valid_operation_class() {
  case "$1" in
    local_edit|file_write|stage|commit|push|pr_create|pr_update|live_mutation|release|deploy|issue_close|recovery|key_rotation)
      return 0 ;;
    *) return 1 ;;
  esac
}

# claim winner: earliest active CLAIM. A CLAIM is active when (a) its effective
# lease — own expires extended by later same-session HEARTBEATs — is in the
# future, and (b) no later same-session HANDOFF release voids it. Reads the
# issue comments JSON on stdin; arg 1 is the current ISO time.
winner_of() {
  jq -r --arg now "$1" '
    ([ .comments[]
       | select(.body | startswith("HEARTBEAT "))
       | { created: .createdAt,
           session: (.body | capture("session=(?<s>[^ \n]+)").s // ""),
           expires: (.body | capture("expires=(?<e>[^ \n]+)").e // "") } ]) as $hb
    | ([ .comments[]
         | select((.body | startswith("HANDOFF ")) and (.body | test("released=")))
         | { created: .createdAt,
             session: (.body | capture("session=(?<s>[^ \n]+)").s // "") } ]) as $rel
    | [ .comments[]
        | select(.body | startswith("CLAIM "))
        | { created: .createdAt, id: .id,
            session: (.body | capture("session=(?<s>[^ \n]+)").s // "?"),
            cexp: (.body | capture("expires=(?<e>[^ \n]+)").e // "") }
        | . as $c
        | ( [ $hb[] | select(.session == $c.session and .created > $c.created) ]
            | sort_by(.created)
            | reduce .[] as $h ($c.cexp;
                if $h.created <= . then ([., $h.expires] | max) else . end) ) as $eff
        | select($eff > $now)
        | select(([ $rel[] | select(.session == $c.session and .created > $c.created) ] | length) == 0)
      ]
    | sort_by(.created, .id)
    | (.[0].session // "NONE")'
}

# --- subcommand: list ---------------------------------------------------------
cmd_list() {
  log "== Eligible work (Status=Todo, Kind!=umbrella, real issues) =="
  ensure_board_cache
  board_json | jq -r '
    [ .items[]
      | select(.content.type == "Issue")
      | select(.status == "Todo")
      | select((.kind // "") != "umbrella")
    ]
    | sort_by(.priority // "P9")
    | .[]
    | "  [\(.priority // "P?")] #\(.content.number) \(.title)  (\(.faz // "-")/\(.track // "-"))"
  '
  local n
  n="$(board_json | jq -r '[.items[]
        | select(.content.type=="Issue" and .status=="Todo" and (.kind//"")!="umbrella")]
        | length')"
  [ "$n" -eq 0 ] && log "  (none)"

  local bk
  bk="$(board_json | jq -r '[.items[]
        | select(.content.type=="Issue" and .status=="Backlog")] | length')"
  log ""
  log "== Backlog ($bk — triage needed; capture via backlog-add) =="

  log ""
  log "== In Progress (claim status) =="
  local now_iso inprog
  now_iso="$(iso_now)"
  inprog="$(board_json | jq -r '
    .items[]
    | select(.content.type == "Issue" and .status == "In Progress")
    | "\(.content.number)\t\(.content.url // "")\t\(.title)"')"
  if [ -z "$inprog" ]; then
    log "  (none)"
    return 0
  fi
  printf '%s\n' "$inprog" | while IFS=$'\t' read -r num url title; do
    [ -z "$num" ] && continue
    local repo path body expires sess
    path="${url#https://github.com/}"
    repo="${path%%/issues/*}"
    body="$(issue_body "$repo" "$num")"
    expires="$(printf '%s\n' "$body" | state_get expires_at)"
    sess="$(printf '%s\n' "$body" | state_get claim_session)"
    if [ -z "$expires" ] || [ "$expires" = "none" ]; then
      log "  #$num $title — IN PROGRESS, no claim recorded (sync-state to inspect)"
    elif [[ "$expires" < "$now_iso" ]]; then
      log "  #$num $title — STALE CLAIM (expired $expires, session ${sess:-?}) — reclaimable"
    else
      log "  #$num $title — active claim (session ${sess:-?}, expires $expires)"
    fi
  done
}

# --- subcommand: claim --------------------------------------------------------
cmd_claim() {
  [ -n "${1:-}" ] || die "claim needs an <issue>"
  resolve_issue "$1"

  local pending_needs_verify
  pending_needs_verify="$(pending_needs_verify_deferred_count "$REPO" "$NUM")"
  if [ "${pending_needs_verify:-0}" -gt 0 ]; then
    die "claim refused — #$NUM has pending PROJECT-DEFERRED Needs Verify marker(s); run drain-project-queue --issue $REPO#$NUM or record stale-skip first"
  fi

  # eligible-status hard gate (docs/board-protocol.md §4, §9)
  [ "$ITEM_KIND" = "umbrella" ] \
    && die "claim refused — #$NUM is Kind=umbrella (rollup, not claimable work)"
  case "$ITEM_STATUS" in
    Todo) : ;;
    "In Progress")
      local cur_exp
      cur_exp="$(issue_body "$REPO" "$NUM" | state_get expires_at)"
      if [ -n "$cur_exp" ] && [ "$cur_exp" != "none" ] && [[ "$cur_exp" > "$(iso_now)" ]]; then
        die "claim refused — #$NUM already In Progress, lease active until $cur_exp"
      fi
      log "note: #$NUM In Progress with stale/absent lease (${cur_exp:-none}) — reclaiming"
      ;;
    *)
      die "claim refused — #$NUM Status='${ITEM_STATUS:-unset}' not eligible (claim only Todo or stale In Progress)"
      ;;
  esac

  local sid wt branch now exp claim_body winner
  sid="$(session_id)"
  wt="$(git rev-parse --show-toplevel 2>/dev/null || echo unknown)"
  branch="$(git branch --show-current 2>/dev/null || echo unknown)"
  now="$(iso_now)"
  exp="$(claim_expiry_iso)"

  log "claim #$NUM ($REPO) — session=$sid branch=$branch"
  [ -n "${BOARD_SESSION_ID:-}" ] || log "note: BOARD_SESSION_ID unset — reuse: export BOARD_SESSION_ID=$sid"

  claim_body="CLAIM session=$sid worktree=$wt branch=$branch at=$now expires=$exp"
  post_comment "$REPO" "$NUM" "$claim_body"

  if [ "$DRY_RUN" -eq 1 ]; then
    log "[dry-run] would re-read comments and determine winner"
    return 0
  fi

  local comments
  comments="$(gh issue view "$NUM" --repo "$REPO" --json comments 2>/dev/null)" \
    || die "failed to re-read comments"
  winner="$(printf '%s' "$comments" | winner_of "$now")"

  log "claim race winner: session=$winner"
  if [ "$winner" != "$sid" ]; then
    post_comment "$REPO" "$NUM" \
      "HANDOFF released=lost-race session=$sid at=$(iso_now)"
    die "claim LOST to session=$winner — released; pick other work (board-sync.sh list)"
  fi

  local body
  body="$(issue_body "$REPO" "$NUM")"
  if printf '%s\n' "$body" | grep -q 'agent-state:v1'; then
    printf '%s\n' "$body" \
      | rewrite_state "in-progress" "$sid" "$wt" "$branch" "$now" "$exp" \
      | write_body "$REPO" "$NUM"
    log "issue body agent-state -> in-progress"
  else
    printf '%s\n' "$body" \
      | append_agent_state_block "in-progress" "$sid" "$wt" "$branch" "$now" "$exp" \
      | write_body "$REPO" "$NUM"
    log "issue body agent-state -> in-progress (initialized)"
  fi
  set_board_status "$ITEM_ID" "$STATUS_INPROGRESS" "$STATUS_INPROGRESS_NAME"
  log "claim WON — #$NUM is yours (lease $exp; run 'heartbeat $NUM' before it expires)"
}

# --- subcommand: require-claim ------------------------------------------------
# Read-only operation-scoped claim gate. This is the mirror-verifier slice of
# Coordination Ledger v1; ledger replay/CAS writer are separate follow-up
# slices. It intentionally performs no GitHub writes.
cmd_require_claim_rest_only() {
  local issue_ref="$1"
  local sid wt branch body bstatus bsess bwt bbr bexp now_iso
  local ledger_json ledger_allowed ledger_deny ledger_reason
  local allowed deny_code details_json actor bucket minute bucket_min intent_src intent_id source
  local -a fail_codes=()
  local -a fail_messages=()

  sid="${OPT_SESSION:-${BOARD_SESSION_ID:-}}"
  [ -n "$sid" ] || die "require-claim needs --session <id> or BOARD_SESSION_ID"
  wt="${OPT_WORKTREE:-$(git rev-parse --show-toplevel 2>/dev/null || echo unknown)}"
  branch="${OPT_BRANCH:-$(git branch --show-current 2>/dev/null || echo unknown)}"
  now_iso="$(iso_now)"

  add_fail() {
    fail_codes+=("$1")
    fail_messages+=("$2")
  }

  parse_issue_ref "$issue_ref"
  if ! rest_issue_exists "$REPO" "$NUM"; then
    add_fail "issue_missing" "issue $REPO#$NUM not found via REST"
    body=""
  else
    body="$(rest_issue_body "$REPO" "$NUM")"
  fi

  bstatus="$(printf '%s\n' "$body" | state_get status)"
  bsess="$(printf '%s\n' "$body" | state_get claim_session)"
  bwt="$(printf '%s\n' "$body" | state_get claim_worktree)"
  bbr="$(printf '%s\n' "$body" | state_get claim_branch)"
  bexp="$(printf '%s\n' "$body" | state_get expires_at)"

  [ "$bstatus" = "in-progress" ] \
    || add_fail "body_status_not_in_progress" "issue body status='${bstatus:-<none>}' is not in-progress"
  [ "$bsess" = "$sid" ] \
    || add_fail "session_mismatch" "issue body claim_session='${bsess:-<none>}' expected='$sid'"
  if [ -z "${bwt:-}" ] || [ "$bwt" = "none" ]; then
    add_fail "worktree_missing" "issue body claim_worktree is missing"
  elif [ "$bwt" != "$wt" ]; then
    add_fail "worktree_mismatch" "issue body claim_worktree='$bwt' expected='$wt'"
  fi
  if [ -z "${bbr:-}" ] || [ "$bbr" = "none" ]; then
    add_fail "branch_missing" "issue body claim_branch is missing"
  elif [ "$bbr" != "$branch" ]; then
    add_fail "branch_mismatch" "issue body claim_branch='$bbr' expected='$branch'"
  fi
  if [ -z "${bexp:-}" ] || [ "$bexp" = "none" ]; then
    add_fail "lease_missing" "issue body expires_at is missing"
  elif [[ "$bexp" < "$now_iso" ]]; then
    add_fail "lease_expired" "claim lease expired at $bexp"
  fi

  ledger_json="$(ledger_claim_state_json "$REPO" "$NUM" "$sid" || true)"
  if [ -n "$ledger_json" ]; then
    ledger_allowed="$(printf '%s' "$ledger_json" | jq -r '.allowed // false')"
    if [ "$ledger_allowed" != "true" ]; then
      ledger_deny="$(printf '%s' "$ledger_json" | jq -r '.deny_code // "ledger_permission_denied"')"
      ledger_reason="$(printf '%s' "$ledger_json" | jq -r '.reason // "ledger permission denied"')"
      add_fail "$ledger_deny" "$ledger_reason"
    fi
  else
    ledger_json="null"
  fi
  source="issue_body_rest_project_graphql_exhausted_v1"
  if [ "$ledger_json" != "null" ]; then
    source="issue_body_rest_project_graphql_exhausted_ledger_v1"
  fi

  if [ "${#fail_codes[@]}" -eq 0 ]; then
    allowed="true"
    deny_code=""
    details_json="[]"
    intent_id=""
  else
    allowed="false"
    deny_code="${fail_codes[0]}"
    details_json="$(
      for i in "${!fail_codes[@]}"; do
        jq -cn --arg code "${fail_codes[$i]}" --arg message "${fail_messages[$i]}" \
          '{code:$code,message:$message}'
      done | jq -s .
    )"
    actor="$(gh api user --jq '.login' 2>/dev/null || echo unknown)"
    minute="$(date -u +%M)"
    bucket_min="$((10#$minute / 10 * 10))"
    bucket="$(date -u +%Y%m%dT%H)$(printf '%02d' "$bucket_min")Z"
    intent_src="$REPO#$NUM|$sid|$OPT_OPERATION|$deny_code|$source|$bucket|$actor"
    intent_id="$(printf '%s' "$intent_src" | shasum -a 256 | awk '{print $1}')"
  fi

  jq -n \
    --arg allowed "$allowed" \
    --arg issue "$REPO#$NUM" \
    --arg session "$sid" \
    --arg operation "$OPT_OPERATION" \
    --arg source "$source" \
    --arg deny_code "$deny_code" \
    --arg deny_event_intent_id "$intent_id" \
    --argjson details "$details_json" \
    --argjson ledger "$ledger_json" \
    '{
      allowed: ($allowed == "true"),
      issue: $issue,
      session: $session,
      operation: $operation,
      permission_source: $source,
      project_status: null,
      project_truth: {
        fresh: false,
        reason: "project_graphql_exhausted_rest_only_low_risk_operation"
      },
      deny_code: (if $deny_code == "" then null else $deny_code end),
      deny_event_intent_id: (if $deny_event_intent_id == "" then null else $deny_event_intent_id end),
      ledger: $ledger,
      details: $details
    }'

  [ "$allowed" = "true" ]
}

cmd_require_claim() {
  local issue_ref="${OPT_ISSUE:-${1:-}}"
  [ -n "$issue_ref" ] || die "require-claim needs --issue <issue>"
  [ -n "$OPT_OPERATION" ] || die "require-claim needs --operation <class>"
  valid_operation_class "$OPT_OPERATION" \
    || die "require-claim unknown --operation '$OPT_OPERATION'"

  if project_graphql_is_exhausted && require_claim_rest_only_operation "$OPT_OPERATION"; then
    cmd_require_claim_rest_only "$issue_ref"
    return $?
  fi

  resolve_issue "$issue_ref"

  local sid wt branch body bstatus bsess bwt bbr bexp now_iso item_json field value
  local refreshed_epoch truth_age truth_fresh truth_reason
  local -a fail_codes=()
  local -a fail_messages=()

  sid="${OPT_SESSION:-${BOARD_SESSION_ID:-}}"
  [ -n "$sid" ] || die "require-claim needs --session <id> or BOARD_SESSION_ID"
  wt="${OPT_WORKTREE:-$(git rev-parse --show-toplevel 2>/dev/null || echo unknown)}"
  branch="${OPT_BRANCH:-$(git branch --show-current 2>/dev/null || echo unknown)}"
  now_iso="$(iso_now)"

  add_fail() {
    fail_codes+=("$1")
    fail_messages+=("$2")
  }

  item_json="$ITEM_JSON"
  refreshed_epoch="$(printf '%s' "$item_json" | jq -r '.refreshed_at_epoch // empty')"
  truth_age=""
  truth_fresh="false"
  truth_reason="missing_refreshed_at"
  if printf '%s' "$refreshed_epoch" | grep -Eq '^[0-9]+$'; then
    truth_age="$(( $(epoch_now) - refreshed_epoch ))"
    if [ "$truth_age" -lt 0 ]; then
      add_fail "project_truth_future_timestamp" "Project truth refreshed_at_epoch is in the future"
      truth_reason="future_timestamp"
    elif [ "$truth_age" -le "$PROJECT_TRUTH_TTL_SECONDS" ]; then
      truth_fresh="true"
      truth_reason="fresh_project_truth"
    else
      truth_reason="stale_project_truth"
    fi
  else
    add_fail "project_truth_missing_refreshed_at" "Project truth lookup has no refreshed_at_epoch"
  fi
  if require_claim_fresh_project_truth_operation "$OPT_OPERATION" \
     && [ "$truth_fresh" != "true" ]; then
    add_fail "project_truth_stale" "Project truth age ${truth_age:-unknown}s exceeds TTL ${PROJECT_TRUTH_TTL_SECONDS}s for critical operation '$OPT_OPERATION'"
  fi

  for field in status faz track priority kind; do
    value="$(printf '%s' "$item_json" | jq -r --arg f "$field" '.[$f] // ""')"
    if [ -z "$value" ] || [ "$value" = "null" ]; then
      add_fail "project_field_missing" "Project #2 field '$field' is empty"
    fi
  done
  [ "$ITEM_KIND" = "umbrella" ] \
    && add_fail "project_kind_umbrella" "Kind=umbrella is not claimable executable work"
  [ "$ITEM_STATUS" = "$STATUS_INPROGRESS_NAME" ] \
    || add_fail "project_status_not_in_progress" "Project Status='$ITEM_STATUS' is not In Progress"

  body="$(issue_body "$REPO" "$NUM")"
  bstatus="$(printf '%s\n' "$body" | state_get status)"
  bsess="$(printf '%s\n' "$body" | state_get claim_session)"
  bwt="$(printf '%s\n' "$body" | state_get claim_worktree)"
  bbr="$(printf '%s\n' "$body" | state_get claim_branch)"
  bexp="$(printf '%s\n' "$body" | state_get expires_at)"

  [ "$bstatus" = "in-progress" ] \
    || add_fail "body_status_not_in_progress" "issue body status='${bstatus:-<none>}' is not in-progress"
  [ "$bsess" = "$sid" ] \
    || add_fail "session_mismatch" "issue body claim_session='${bsess:-<none>}' expected='$sid'"
  if [ -z "${bwt:-}" ] || [ "$bwt" = "none" ]; then
    add_fail "worktree_missing" "issue body claim_worktree is missing"
  elif [ "$bwt" != "$wt" ]; then
    add_fail "worktree_mismatch" "issue body claim_worktree='$bwt' expected='$wt'"
  fi
  if [ -z "${bbr:-}" ] || [ "$bbr" = "none" ]; then
    add_fail "branch_missing" "issue body claim_branch is missing"
  elif [ "$bbr" != "$branch" ]; then
    add_fail "branch_mismatch" "issue body claim_branch='$bbr' expected='$branch'"
  fi
  if [ -z "${bexp:-}" ] || [ "$bexp" = "none" ]; then
    add_fail "lease_missing" "issue body expires_at is missing"
  elif [[ "$bexp" < "$now_iso" ]]; then
    add_fail "lease_expired" "claim lease expired at $bexp"
  fi

  local ledger_json ledger_allowed ledger_deny ledger_reason
  ledger_json="$(ledger_claim_state_json "$REPO" "$NUM" "$sid" || true)"
  if [ -n "$ledger_json" ]; then
    ledger_allowed="$(printf '%s' "$ledger_json" | jq -r '.allowed // false')"
    if [ "$ledger_allowed" != "true" ]; then
      ledger_deny="$(printf '%s' "$ledger_json" | jq -r '.deny_code // "ledger_permission_denied"')"
      ledger_reason="$(printf '%s' "$ledger_json" | jq -r '.reason // "ledger permission denied"')"
      add_fail "$ledger_deny" "$ledger_reason"
    fi
  else
    ledger_json="null"
  fi
  local allowed deny_code details_json actor bucket minute bucket_min intent_src intent_id source
  source="project_issue_mirror_v1"
  if [ "$ledger_json" != "null" ]; then
    source="project_issue_ledger_mirror_v1"
  fi

  if [ "${#fail_codes[@]}" -eq 0 ]; then
    allowed="true"
    deny_code=""
    details_json="[]"
    intent_id=""
  else
    allowed="false"
    deny_code="${fail_codes[0]}"
    details_json="$(
      for i in "${!fail_codes[@]}"; do
        jq -cn --arg code "${fail_codes[$i]}" --arg message "${fail_messages[$i]}" \
          '{code:$code,message:$message}'
      done | jq -s .
    )"
    actor="$(gh api user --jq '.login' 2>/dev/null || echo unknown)"
    minute="$(date -u +%M)"
    bucket_min="$((10#$minute / 10 * 10))"
    bucket="$(date -u +%Y%m%dT%H)$(printf '%02d' "$bucket_min")Z"
    intent_src="$REPO#$NUM|$sid|$OPT_OPERATION|$deny_code|$source|$bucket|$actor"
    intent_id="$(printf '%s' "$intent_src" | shasum -a 256 | awk '{print $1}')"
  fi

  jq -n \
    --arg allowed "$allowed" \
    --arg issue "$REPO#$NUM" \
    --arg session "$sid" \
    --arg operation "$OPT_OPERATION" \
    --arg status "$ITEM_STATUS" \
    --arg refreshed_at "$(printf '%s' "$item_json" | jq -r '.refreshed_at // empty')" \
    --arg refreshed_at_epoch "${refreshed_epoch:-}" \
    --arg truth_age "${truth_age:-}" \
    --arg truth_fresh "$truth_fresh" \
    --arg truth_reason "$truth_reason" \
    --arg ttl_seconds "$PROJECT_TRUTH_TTL_SECONDS" \
    --arg source "$source" \
    --arg deny_code "$deny_code" \
    --arg deny_event_intent_id "$intent_id" \
    --argjson details "$details_json" \
    --argjson ledger "$ledger_json" \
    '{
      allowed: ($allowed == "true"),
      issue: $issue,
      session: $session,
      operation: $operation,
      permission_source: $source,
      project_status: $status,
      project_truth: {
        fresh: ($truth_fresh == "true"),
        reason: $truth_reason,
        refreshed_at: (if $refreshed_at == "" then null else $refreshed_at end),
        refreshed_at_epoch: (if $refreshed_at_epoch == "" then null else ($refreshed_at_epoch | tonumber) end),
        age_seconds: (if $truth_age == "" then null else ($truth_age | tonumber) end),
        ttl_seconds: ($ttl_seconds | tonumber)
      },
      deny_code: (if $deny_code == "" then null else $deny_code end),
      deny_event_intent_id: (if $deny_event_intent_id == "" then null else $deny_event_intent_id end),
      ledger: $ledger,
      details: $details
    }'

  [ "$allowed" = "true" ]
}

# --- subcommand: record-deny --------------------------------------------------
# CAS ledger writer is not available in this slice. record-deny therefore
# preserves denial intents in a local append-only debt queue and returns
# nonzero so mutation wrappers stay fail-closed.
cmd_record_deny() {
  local intent queue dir id intent_operation now existing_count record rc
  if [ -n "$OPT_INTENT_FILE" ]; then
    if [ "$OPT_INTENT_FILE" = "-" ]; then
      intent="$(cat)"
    else
      intent="$(cat "$OPT_INTENT_FILE")" \
        || die "record-deny — failed to read --intent-file '$OPT_INTENT_FILE'"
    fi
  else
    intent="$OPT_INTENT"
  fi
  [ -n "$intent" ] || die "record-deny needs --intent <json> or --intent-file <path>"

  printf '%s' "$intent" | jq -e '
    type == "object"
    and (.allowed == false)
    and (.deny_event_intent_id | type == "string" and test("^[a-f0-9]{64}$"))
    and (.deny_code | type == "string" and length > 0)
    and (.issue | type == "string" and length > 0)
    and (.session | type == "string" and length > 0)
    and (.operation | type == "string" and length > 0)
  ' >/dev/null || die "record-deny — invalid deny intent JSON"

  id="$(printf '%s' "$intent" | jq -r '.deny_event_intent_id')"
  intent_operation="$(printf '%s' "$intent" | jq -r '.operation')"
  valid_operation_class "$intent_operation" \
    || die "record-deny — invalid operation '$intent_operation'"
  queue="$COORDINATION_AUDIT_DEBT_QUEUE"
  dir="$(dirname "$queue")"
  now="$(iso_now)"
  mkdir -p "$dir" || die "record-deny — failed to create queue directory '$dir'"
  touch "$queue" || die "record-deny — failed to touch queue '$queue'"

  existing_count="$(jq -s --arg id "$id" '
    [ .[]
      | select(type == "object")
      | select((.deny_event_intent_id // .intent.deny_event_intent_id // "") == $id)
    ] | length
  ' "$queue" 2>/dev/null || printf '0')"

  if [ "${existing_count:-0}" -gt 0 ]; then
    jq -n \
      --arg status "blocked_audit_debt" \
      --arg reason "duplicate_local_debt" \
      --arg queue "$queue" \
      --arg id "$id" \
      '{
        recorded: false,
        queued: false,
        duplicate: true,
        status: $status,
        reason: $reason,
        queue_path: $queue,
        deny_event_intent_id: $id
      }'
    return 1
  fi

  record="$(jq -cn \
    --arg queued_at "$now" \
    --arg status "blocked_audit_debt" \
    --arg reason "cas_writer_unavailable" \
    --arg source "board-sync-record-deny-v1" \
    --arg queue "$queue" \
    --argjson intent "$intent" \
    '{
      schemaVersion: "coordination-audit-debt/v1",
      queued_at: $queued_at,
      status: $status,
      reason: $reason,
      source: $source,
      queue_path: $queue,
      deny_event_intent_id: $intent.deny_event_intent_id,
      intent: $intent
    }')"

  rc=1
  if [ "$DRY_RUN" -eq 1 ]; then
    log "[dry-run] record-deny — would append local audit debt id=$id to $queue"
  else
    printf '%s\n' "$record" >>"$queue" \
      || die "record-deny — failed to append local audit debt to '$queue'"
  fi

  jq -n \
    --arg status "blocked_audit_debt" \
    --arg reason "cas_writer_unavailable" \
    --arg queue "$queue" \
    --arg id "$id" \
    '{
      recorded: false,
      queued: true,
      duplicate: false,
      status: $status,
      reason: $reason,
      queue_path: $queue,
      deny_event_intent_id: $id
    }'
  return "$rc"
}

# --- subcommand: heartbeat ----------------------------------------------------
cmd_heartbeat() {
  [ -n "${1:-}" ] || die "heartbeat needs an <issue>"
  resolve_issue "$1"
  local sid body bsess bexp bwt bbr now exp
  sid="$(session_id)"
  body="$(issue_body "$REPO" "$NUM")"
  bsess="$(printf '%s\n' "$body" | state_get claim_session)"
  [ "$bsess" = "$sid" ] \
    || die "heartbeat refused — #$NUM claimed by session '${bsess:-none}', not you ($sid)"
  bexp="$(printf '%s\n' "$body" | state_get expires_at)"
  if [ -z "$bexp" ] || [ "$bexp" = "none" ] || [[ "$bexp" < "$(iso_now)" ]]; then
    die "heartbeat refused — #$NUM lease expired/absent (${bexp:-none}); re-claim instead"
  fi
  bwt="$(printf '%s\n' "$body" | state_get claim_worktree)"
  bbr="$(printf '%s\n' "$body" | state_get claim_branch)"
  now="$(iso_now)"
  exp="$(claim_expiry_iso)"
  log "heartbeat #$NUM ($REPO) — session=$sid lease -> $exp"
  post_comment "$REPO" "$NUM" "HEARTBEAT session=$sid at=$now expires=$exp"
  if printf '%s\n' "$body" | grep -q 'agent-state:v1'; then
    printf '%s\n' "$body" \
      | rewrite_state "in-progress" "$sid" "$bwt" "$bbr" "$now" "$exp" \
      | write_body "$REPO" "$NUM"
    log "issue body lease -> $exp"
  fi
}

# --- subcommand: release ------------------------------------------------------
cmd_release_project_deferred() {
  local issue_ref="$1" reason="$2"
  local sid body bsess bexp now_iso rel_session note key_src key marker marker_body

  parse_issue_ref "$issue_ref"
  sid="$(session_id)"
  body="$(issue_body "$REPO" "$NUM")"
  bsess="$(printf '%s\n' "$body" | state_get claim_session)"
  bexp="$(printf '%s\n' "$body" | state_get expires_at)"
  now_iso="$(iso_now)"
  rel_session="$sid"

  if [ -n "$bsess" ] && [ "$bsess" != "none" ] && [ "$bsess" != "$sid" ]; then
    if [ "$FORCE_STALE" -eq 1 ] && [ -n "$bexp" ] && [ "$bexp" != "none" ] \
       && [[ "$bexp" < "$now_iso" ]]; then
      log "force-stale: #$NUM claimed by '$bsess' but lease expired ($bexp) — reclaiming"
      reason="stale-reclaim"
      rel_session="$bsess"
    else
      die "release refused — #$NUM claimed by session '$bsess', not you ($sid); --force-stale only if its lease ($bexp) is expired"
    fi
  fi

  log "release #$NUM ($REPO) — session=$sid reason=$reason (Project Todo reconcile deferred)"
  note=""
  [ "$rel_session" != "$sid" ] && note=" by=$sid"
  post_comment "$REPO" "$NUM" \
    "HANDOFF released=$reason session=$rel_session${note} at=$now_iso"

  if printf '%s\n' "$body" | grep -q 'agent-state:v1'; then
    printf '%s\n' "$body" \
      | rewrite_state "todo" "none" "none" "none" "none" "none" \
      | write_body "$REPO" "$NUM"
    log "issue body agent-state -> todo (unclaimed)"
  fi

  key_src="project-deferred|release|$REPO#$NUM|Status|Todo|$rel_session|v1"
  key="$(printf '%s' "$key_src" | shasum -a 256 | awk '{print $1}')"
  marker="PROJECT-DEFERRED v1 key=$key"
  if rest_comment_contains "$REPO" "$NUM" "$marker"; then
    log "release deferred note — #$NUM already has $marker"
  else
    marker_body="$marker mutation=status target=\"Todo\" reason=graphql_exhausted source=release issue_repo=$REPO issue=$NUM session=$rel_session at=$now_iso
Deferred mutation class: low-risk mirror repair only.
Authority boundary: release already updated issue-body claim state via REST; this marker is not board truth.
Drain requirement: re-read Project #2 current item state before mutation; no downgrade; skip if stale/already-drained."
    rest_post_comment "$REPO" "$NUM" "$marker_body"
    log "release deferred #$NUM ($REPO) — recorded $marker for Status -> Todo"
  fi
  log "released #$NUM (Project Todo reconcile deferred)"
}

cmd_release() {
  [ -n "${1:-}" ] || die "release needs an <issue>"
  if project_graphql_is_exhausted; then
    cmd_release_project_deferred "$1" "${2:-manual}"
    return $?
  fi

  resolve_issue "$1"
  local sid reason body bsess bexp now_iso rel_session
  sid="$(session_id)"
  reason="${2:-manual}"
  body="$(issue_body "$REPO" "$NUM")"
  bsess="$(printf '%s\n' "$body" | state_get claim_session)"
  bexp="$(printf '%s\n' "$body" | state_get expires_at)"
  now_iso="$(iso_now)"
  rel_session="$sid"

  # ownership guard — do not silently drop another live session's claim
  if [ -n "$bsess" ] && [ "$bsess" != "none" ] && [ "$bsess" != "$sid" ]; then
    if [ "$FORCE_STALE" -eq 1 ] && [ -n "$bexp" ] && [ "$bexp" != "none" ] \
       && [[ "$bexp" < "$now_iso" ]]; then
      log "force-stale: #$NUM claimed by '$bsess' but lease expired ($bexp) — reclaiming"
      reason="stale-reclaim"
      rel_session="$bsess"
    else
      die "release refused — #$NUM claimed by session '$bsess', not you ($sid); --force-stale only if its lease ($bexp) is expired"
    fi
  fi

  log "release #$NUM ($REPO) — session=$sid reason=$reason"
  local note=""
  [ "$rel_session" != "$sid" ] && note=" by=$sid"
  post_comment "$REPO" "$NUM" \
    "HANDOFF released=$reason session=$rel_session${note} at=$now_iso"

  if printf '%s\n' "$body" | grep -q 'agent-state:v1'; then
    printf '%s\n' "$body" \
      | rewrite_state "todo" "none" "none" "none" "none" "none" \
      | write_body "$REPO" "$NUM"
    log "issue body agent-state -> todo (unclaimed)"
  fi
  if [ "$ITEM_STATUS" = "In Progress" ]; then
    set_board_status "$ITEM_ID" "$STATUS_TODO" "$STATUS_TODO_NAME"
  fi
  log "released #$NUM"
}

# --- subcommand: sync-state ---------------------------------------------------
cmd_sync_state() {
  [ -n "${1:-}" ] || die "sync-state needs an <issue>"
  resolve_issue "$1"
  local body bstatus bsess bexp now_iso
  body="$(issue_body "$REPO" "$NUM")"
  bstatus="$(printf '%s\n' "$body" | state_get status)"
  bsess="$(printf '%s\n' "$body" | state_get claim_session)"
  bexp="$(printf '%s\n' "$body" | state_get expires_at)"
  now_iso="$(iso_now)"

  log "sync-state #$NUM ($REPO)"
  log "  board Status      : ${ITEM_STATUS:-<unset>}"
  log "  body agent-state  : status=${bstatus:-<none>} session=${bsess:-<none>} expires=${bexp:-<none>}"
  if [ -n "$bexp" ] && [ "$bexp" != "none" ]; then
    if [[ "$bexp" < "$now_iso" ]]; then
      log "  claim             : STALE (lease expired $bexp) — reclaimable"
    else
      log "  claim             : active until $bexp"
    fi
  else
    log "  claim             : unclaimed"
  fi
  case "$ITEM_STATUS|$bstatus" in
    "Backlog|backlog"|"In Progress|in-progress"|"Todo|todo"|"Blocked|blocked"|"Needs Verify|needs-verify"|"Done|done") : ;;
    "|"|"|none") : ;;
    *) log "  WARN: board Status and body agent-state disagree — reconcile" ;;
  esac
}

# --- subcommand: verify -------------------------------------------------------
# PR-merge evidence: a merged PR's `Tracked by <ref>` -> board Status Needs Verify
# where <ref> is #N, repo#N, owner/repo#N, or a full issue URL.
# + a machine-readable EVIDENCE comment. Idempotent; never downgrades Done /
# Blocked / Needs Verify; skips (success) non-eligible items.
cmd_verify() {
  [ -n "${1:-}" ] || die "verify needs an <issue>"
  [ -n "$OPT_PR" ] || die "verify needs --pr <N>"
  printf '%s' "$OPT_PR" | grep -Eq '^[0-9]+$' || die "verify --pr must be a number"
  [ -n "$OPT_PR_REPO" ] || die "verify needs --pr-repo <owner/repo>"
  printf '%s' "$OPT_PR_REPO" | grep -Eq '^[^/ ]+/[^/ ]+$' \
    || die "verify --pr-repo must be owner/repo"
  local ref="$1"
  if printf '%s' "$ref" | grep -Eq '^[^/ ]+/[^/ #]+#[0-9]+$'; then
    ref="https://github.com/${ref%#*}/issues/${ref##*#}"
  elif printf '%s' "$ref" | grep -Eq '^[^/ #]+#[0-9]+$'; then
    [ -n "$OPT_PR_REPO" ] || die "verify repo#N refs require --pr-repo owner/repo"
    local pr_owner repo_name pr_owner_norm repo_name_norm
    pr_owner="${OPT_PR_REPO%%/*}"
    repo_name="${ref%#*}"
    pr_owner_norm="$(printf '%s' "$pr_owner" | tr '[:upper:]' '[:lower:]')"
    repo_name_norm="$(printf '%s' "$repo_name" | tr '[:upper:]' '[:lower:]')"
    if [ "$repo_name_norm" = "$pr_owner_norm" ]; then
      log "verify skip — '$ref' looks like owner#N; use #N, repo#N, owner/repo#N, or a full issue URL"
      return 0
    fi
    ref="https://github.com/${pr_owner}/${repo_name}/issues/${ref##*#}"
  elif [ -n "$OPT_REPO" ] && printf '%s' "$ref" | grep -Eq '^[0-9]+$'; then
    ref="https://github.com/$OPT_REPO/issues/$ref"
  fi

  # parse the ref into (vnum, vrepo) BEFORE touching Project API so the
  # PAT-missing fallback below can route on the same parse (Codex
  # 019e8079 must_fix #1: PAT-missing path must not call Project API).
  local vnum vrepo
  if printf '%s' "$ref" | grep -q '^https://github.com/'; then
    local rp
    rp="${ref#https://github.com/}"
    vrepo="${rp%%/issues/*}"
    vnum="${rp##*/}"
  else
    vnum="$ref"
    vrepo=""
  fi

  # #1085 Codex 019e8079 must_fix #1+#2+#3 — PAT-missing fallback:
  # when ADD_TO_PROJECT_PAT is absent (CI signals it via BOARD_PAT_PRESENT="")
  # we cannot reach the Project API at all (preflight / board_matches /
  # resolve_issue all fail under GITHUB_TOKEN). Take a comment-only path
  # that needs only REST issue-comment perms:
  #   - same-repo refs (issue lives in PR_REPO): post EVIDENCE comment,
  #     skip body rewrite + board Status (drift-prevention: writing the
  #     body to "needs-verify" while board Status stays "Todo" produces
  #     exactly the contradictory state the protocol is supposed to
  #     prevent — Codex must_fix #3).
  #   - cross-repo refs: GITHUB_TOKEN is repo-scoped and cannot comment
  #     on a sibling repo's issue, so skip with a clear warning instead
  #     of dying mid-loop (Codex must_fix #2).
  # The full Project-API path resumes when the PAT is seeded.
  if [ "${BOARD_PAT_PRESENT-yes}" = "" ]; then
    _verify_pat_missing "$vnum" "$vrepo"
    return $?
  fi

  if project_graphql_is_exhausted; then
    _verify_project_deferred "$vnum" "$vrepo"
    return $?
  fi

  if ! resolve_issue_optional "$ref"; then
    log "verify skip — ${vrepo:-${OPT_REPO:-$(git_remote_repo)}}#$vnum not on Project #2 (targeted lookup)"
    return 0
  fi

  if [ "$ITEM_KIND" = "umbrella" ]; then
    log "verify skip — #$NUM Kind=umbrella"
    return 0
  fi
  case "$ITEM_STATUS" in
    Todo|"In Progress") : ;;
    *)
      log "verify skip — #$NUM Status='${ITEM_STATUS:-unset}' (no downgrade)"
      return 0
      ;;
  esac

  # #1085 Codex 019e8079 iter-2 P1 — separate "comment duplicate
  # prevention" from "state mutation skip". If the canonical EVIDENCE
  # marker already exists (e.g. a prior PAT-missing run posted it), do
  # NOT re-post the comment, but still proceed with body rewrite + board
  # Status mutation under the now-present PAT. This makes the doc
  # guarantee real: PAT seed after a PAT-missing run *repairs* the
  # body+board half without doubling up the comment.
  #
  # The status guard above (Todo/In Progress) already short-circuits
  # rerunning against a Done/Blocked/Needs-Verify item, so falling
  # through on seen>0 only re-runs body/board for items that still need
  # the move.
  local seen comment_needed=1
  seen="$(gh issue view "$NUM" --repo "$REPO" --json comments 2>/dev/null \
    | jq --arg pr "$OPT_PR" --arg pr_repo "$OPT_PR_REPO" '[.comments[]
        | select(.body | contains("pr_repo=" + $pr_repo + " pr=" + $pr + " "))] | length' \
    2>/dev/null || echo 0)"
  if [ "${seen:-0}" -gt 0 ]; then
    comment_needed=0
    log "verify note — #$NUM already has EVIDENCE for $OPT_PR_REPO#$OPT_PR (repairing body/board only)"
  fi

  local now ev body
  now="$(iso_now)"
  ev="EVIDENCE type=pr-merged pr_repo=$OPT_PR_REPO pr=$OPT_PR issue_repo=$REPO at=$now
Source-ready: $OPT_PR_REPO PR #$OPT_PR merged.
Runtime/acceptance evidence pending — board Status -> Needs Verify."
  log "verify #$NUM ($REPO) — $OPT_PR_REPO PR #$OPT_PR merged -> Needs Verify"
  if [ "$comment_needed" -eq 1 ]; then
    post_comment "$REPO" "$NUM" "$ev"
  fi
  body="$(issue_body "$REPO" "$NUM")"
  if printf '%s\n' "$body" | grep -q 'agent-state:v1'; then
    printf '%s\n' "$body" \
      | rewrite_state "needs-verify" "none" "none" "none" "none" "none" \
      | write_body "$REPO" "$NUM"
    log "issue body agent-state -> needs-verify (claim cleared)"
  fi
  set_board_status "$ITEM_ID" "$STATUS_NEEDSVERIFY" "$STATUS_NEEDSVERIFY_NAME"
}

# PAT-missing fallback for cmd_verify (Codex 019e8079 must_fix #1+#2+#3).
# Comment-only path that uses ONLY REST issue-comment permissions — no
# Project API, no body rewrite, no Status mutation. Drift-safe by design:
# we never write a needs-verify body without also moving the board, and
# we never claim cross-repo coverage with a repo-scoped GITHUB_TOKEN.
_verify_pat_missing() {
  local vnum="$1" vrepo="$2" issue_repo vrepo_norm pr_repo_norm
  # Codex 019e809d iter-3 P1 #3: case-insensitive repo compare so
  # mixed-case Tracked-by refs (e.g. `halildeu/platform-k8s-gitops#42`
  # vs canonical `Halildeu/...`) do not get false cross-repo skipped.
  # GitHub treats owner/repo identity case-insensitively; we do too.
  vrepo_norm="$(printf '%s' "$vrepo" | tr '[:upper:]' '[:lower:]')"
  pr_repo_norm="$(printf '%s' "$OPT_PR_REPO" | tr '[:upper:]' '[:lower:]')"
  # Cross-repo guard: a ref like owner/other-repo#42 or an issue URL
  # outside PR_REPO. GITHUB_TOKEN cannot comment on the sibling repo;
  # log + step-summary + ::warning:: annotation (P1 #4 — surface in the
  # Actions UI summary panel, not only the run log) and move on so the
  # workflow loop does not die on a multi-repo Tracked-by line.
  if [ -n "$vrepo_norm" ] && [ "$vrepo_norm" != "$pr_repo_norm" ]; then
    log "verify skip — #$vnum lives in $vrepo (cross-repo); GITHUB_TOKEN cannot comment there. Seed ADD_TO_PROJECT_PAT to enable cross-repo evidence."
    printf '::warning::cross-repo verify skipped: %s#%s (PAT-missing fallback — seed ADD_TO_PROJECT_PAT with Issues R+W on %s)\n' \
      "$vrepo" "$vnum" "$vrepo" >&2
    if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
      printf '⚠️ cross-repo verify skipped: %s#%s (PAT-missing fallback)\n' \
        "$vrepo" "$vnum" >>"$GITHUB_STEP_SUMMARY" || true
    fi
    return 0
  fi
  issue_repo="${vrepo:-$OPT_PR_REPO}"

  # Existence check via REST (no Project API). 404 means the ref points
  # at something that is not an issue in this repo — log + skip.
  if ! gh issue view "$vnum" --repo "$issue_repo" --json number >/dev/null 2>&1; then
    log "verify skip — #$vnum not found in $issue_repo (REST 404)"
    return 0
  fi

  # Idempotency: same EVIDENCE marker the full path uses.
  local seen
  seen="$(gh issue view "$vnum" --repo "$issue_repo" --json comments 2>/dev/null \
    | jq --arg pr "$OPT_PR" --arg pr_repo "$OPT_PR_REPO" '[.comments[]
        | select(.body | contains("pr_repo=" + $pr_repo + " pr=" + $pr + " "))] | length' \
    2>/dev/null || echo 0)"
  if [ "${seen:-0}" -gt 0 ]; then
    log "verify skip — #$vnum already has EVIDENCE for $OPT_PR_REPO#$OPT_PR (idempotent)"
    return 0
  fi

  local now ev
  now="$(iso_now)"
  ev="EVIDENCE type=pr-merged pr_repo=$OPT_PR_REPO pr=$OPT_PR issue_repo=$issue_repo at=$now
Source-ready: $OPT_PR_REPO PR #$OPT_PR merged.
Runtime/acceptance evidence pending — board Status mutation SKIPPED (PAT missing)."
  log "verify #$vnum ($issue_repo) — PAT-missing path: comment only (board Status untouched)"
  post_comment "$issue_repo" "$vnum" "$ev"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '✓ EVIDENCE comment posted on %s#%s (board Status still requires PAT)\n' \
      "$issue_repo" "$vnum" >>"$GITHUB_STEP_SUMMARY" || true
  fi
}

_verify_project_deferred() {
  local vnum="$1" vrepo="$2" issue_repo key_src key marker evidence body seen_marker seen_evidence
  issue_repo="${vrepo:-${OPT_REPO:-$OPT_PR_REPO}}"
  printf '%s' "$issue_repo" | grep -Eq '^[^/ ]+/[^/ ]+$' \
    || die "verify deferred — cannot resolve issue repo for #$vnum"

  if ! rest_issue_exists "$issue_repo" "$vnum"; then
    log "verify deferred skip — #$vnum not found in $issue_repo (REST 404)"
    return 0
  fi

  key_src="project-deferred|verify|$issue_repo#$vnum|$OPT_PR_REPO#$OPT_PR|Status|Needs Verify|v1"
  key="$(printf '%s' "$key_src" | shasum -a 256 | awk '{print $1}')"
  marker="PROJECT-DEFERRED v1 key=$key"

  seen_marker=0
  if rest_comment_contains "$issue_repo" "$vnum" "$marker"; then
    seen_marker=1
  fi
  seen_evidence=0
  if rest_comment_contains "$issue_repo" "$vnum" "pr_repo=$OPT_PR_REPO pr=$OPT_PR "; then
    seen_evidence=1
  fi

  if [ "$seen_marker" -eq 1 ]; then
    log "verify deferred skip — #$vnum already has $marker"
    return 0
  fi

  local now
  now="$(iso_now)"
  evidence="EVIDENCE type=pr-merged pr_repo=$OPT_PR_REPO pr=$OPT_PR issue_repo=$issue_repo at=$now
Source-ready: $OPT_PR_REPO PR #$OPT_PR merged.
Runtime/acceptance evidence pending.
Project Status mutation not executed because Project GraphQL budget is exhausted."

  body="$marker mutation=status target=\"Needs Verify\" reason=graphql_exhausted source=verify issue_repo=$issue_repo issue=$vnum pr_repo=$OPT_PR_REPO pr=$OPT_PR at=$now
Deferred mutation class: low-risk mirror repair only.
Authority boundary: this marker is not board truth and does not change agent-state.status.
Drain requirement: re-read Project #2 current item state before mutation; no downgrade; skip if stale/already-drained."

  log "verify deferred #$vnum ($issue_repo) — GraphQL exhausted; recording $marker"
  if [ "$seen_evidence" -eq 0 ]; then
    rest_post_comment "$issue_repo" "$vnum" "$evidence"
  else
    log "verify deferred note — EVIDENCE for $OPT_PR_REPO#$OPT_PR already exists"
  fi
  rest_post_comment "$issue_repo" "$vnum" "$body"
}

deferred_transition_decision() {
  # deferred_transition_decision <current-status> <target-status>
  local current="$1" target="$2"
  case "$target" in
    "Needs Verify")
      case "$current" in
        "Needs Verify") printf 'already-target' ;;
        Todo|"In Progress") printf 'apply' ;;
        *) printf 'stale-skip' ;;
      esac
      ;;
    Todo)
      case "$current" in
        Todo) printf 'already-target' ;;
        "In Progress") printf 'apply' ;;
        *) printf 'stale-skip' ;;
      esac
      ;;
    Backlog)
      case "$current" in
        Backlog) printf 'already-target' ;;
        Todo) printf 'apply' ;;
        *) printf 'stale-skip' ;;
      esac
      ;;
    *)
      printf 'forbidden-target'
      ;;
  esac
}

rewrite_body_after_deferred_status() {
  # rewrite_body_after_deferred_status <target-status>
  local target="$1" body state
  case "$target" in
    "Needs Verify") state="needs-verify" ;;
    Todo) state="todo" ;;
    Backlog) state="backlog" ;;
    *) return 0 ;;
  esac
  body="$(issue_body "$REPO" "$NUM")"
  if printf '%s\n' "$body" | grep -q 'agent-state:v1'; then
    printf '%s\n' "$body" \
      | rewrite_state "$state" "none" "none" "none" "none" "none" \
      | write_body "$REPO" "$NUM"
    log "issue body agent-state -> $state (deferred drain reconcile)"
  fi
}

post_deferred_terminal_marker() {
  # post_deferred_terminal_marker <kind> <key> <result> <extra>
  local kind="$1" key="$2" result="$3" extra="${4:-}" now
  now="$(iso_now)"
  rest_post_comment "$REPO" "$NUM" \
    "PROJECT-$kind v1 key=$key result=$result ${extra}at=$now"
}

# --- subcommand: drain-project-queue -----------------------------------------
# Apply issue-scoped low-risk PROJECT-DEFERRED markers. The queue is not
# authority; each item re-reads Project #2 with targeted lookup, then either
# applies a no-downgrade Status mutation or records a terminal stale-skip.
cmd_drain_project_queue() {
  local issue_ref="${OPT_ISSUE:-${1:-}}"
  [ -n "$issue_ref" ] || die "drain-project-queue needs --issue <issue>"
  local limit="${OPT_LIMIT:-20}"
  printf '%s' "$limit" | grep -Eq '^[0-9]+$' || die "drain-project-queue --limit must be a number"

  resolve_issue "$issue_ref"

  local records count drained=0 skipped=0 applied=0 already=0
  records="$(project_deferred_records_json "$REPO" "$NUM" | jq -c --argjson limit "$limit" '.[:$limit][]')"
  count="$(printf '%s\n' "$records" | grep -c . || true)"
  if [ "$count" -eq 0 ]; then
    log "drain-project-queue — no pending PROJECT-DEFERRED markers on $REPO#$NUM"
    return 0
  fi
  log "drain-project-queue — $REPO#$NUM pending=$count limit=$limit"

  while IFS= read -r rec; do
    [ -n "$rec" ] || continue
    local key mutation target source decision current opt extra
    key="$(printf '%s' "$rec" | jq -r '.key')"
    mutation="$(printf '%s' "$rec" | jq -r '.mutation')"
    target="$(printf '%s' "$rec" | jq -r '.target')"
    source="$(printf '%s' "$rec" | jq -r '.source')"

    resolve_issue "$REPO#$NUM"
    current="$ITEM_STATUS"

    if [ "$mutation" != "status" ]; then
      skipped=$((skipped + 1))
      log "drain-project-queue — key=$key skip unsupported mutation='$mutation'"
      [ "$DRY_RUN" -eq 1 ] || post_deferred_terminal_marker "STALE-SKIP" "$key" "unsupported-mutation" "mutation=$mutation target=\"$target\" "
      continue
    fi

    decision="$(deferred_transition_decision "$current" "$target")"
    case "$decision" in
      apply)
        opt="$(status_option_id "$target")" \
          || die "drain-project-queue — no Status option for target '$target'"
        log "drain-project-queue — key=$key apply Status '$current' -> '$target' (source=${source:-unknown})"
        if [ "$DRY_RUN" -eq 1 ]; then
          log "[dry-run] would set Project Status -> $target and reconcile body"
        else
          set_board_status "$ITEM_ID" "$opt" "$target"
          rewrite_body_after_deferred_status "$target"
          post_deferred_terminal_marker "DRAINED" "$key" "applied" "from=\"$current\" target=\"$target\" "
        fi
        applied=$((applied + 1))
        drained=$((drained + 1))
        ;;
      already-target)
        log "drain-project-queue — key=$key already target Status '$target'"
        if [ "$DRY_RUN" -eq 1 ]; then
          log "[dry-run] would record PROJECT-DRAINED already-target"
        else
          rewrite_body_after_deferred_status "$target"
          post_deferred_terminal_marker "DRAINED" "$key" "already-target" "current=\"$current\" target=\"$target\" "
        fi
        already=$((already + 1))
        drained=$((drained + 1))
        ;;
      stale-skip)
        log "drain-project-queue — key=$key stale-skip current='$current' target='$target'"
        [ "$DRY_RUN" -eq 1 ] || post_deferred_terminal_marker "STALE-SKIP" "$key" "no-downgrade" "current=\"$current\" target=\"$target\" "
        skipped=$((skipped + 1))
        ;;
      forbidden-target)
        log "drain-project-queue — key=$key forbidden target='$target'"
        [ "$DRY_RUN" -eq 1 ] || post_deferred_terminal_marker "STALE-SKIP" "$key" "forbidden-target" "current=\"$current\" target=\"$target\" "
        skipped=$((skipped + 1))
        ;;
      *)
        die "drain-project-queue — internal unknown decision '$decision'"
        ;;
    esac
  done <<< "$records"

  log "drain-project-queue — drained=$drained applied=$applied already=$already skipped=$skipped"
}

# --- subcommand: reap ---------------------------------------------------------
# Release every In Progress item whose claim lease has expired. Conservative:
# only acts on a real, recorded, parseable, past lease; never touches
# Blocked / Needs Verify / Done. Bounded by --limit (default 20).
cmd_reap() {
  local limit actor now_iso reaped=0 scanned=0
  limit="${OPT_LIMIT:-20}"
  printf '%s' "$limit" | grep -Eq '^[0-9]+$' || die "reap --limit must be a number"
  actor="$(session_id)"
  now_iso="$(iso_now)"
  log "reap — scanning In Progress claims (limit $limit)"
  local inprog
  inprog="$(board_json | jq -r '
    .items[]
    | select(.content.type == "Issue" and .status == "In Progress")
    | "\(.id)\t\(.content.number)\t\(.content.url // "")"')"
  if [ -z "$inprog" ]; then
    log "reap — no In Progress items"
    return 0
  fi
  while IFS=$'\t' read -r item num url; do
    [ -z "$num" ] && continue
    if [ "$reaped" -ge "$limit" ]; then
      log "reap — limit $limit reached"
      break
    fi
    scanned=$((scanned + 1))
    local repo path body bsess bexp
    path="${url#https://github.com/}"
    repo="${path%%/issues/*}"
    body="$(issue_body "$repo" "$num")"
    bsess="$(printf '%s\n' "$body" | state_get claim_session)"
    bexp="$(printf '%s\n' "$body" | state_get expires_at)"
    if [ -z "$bsess" ] || [ "$bsess" = "none" ]; then continue; fi
    if [ -z "$bexp" ] || [ "$bexp" = "none" ]; then continue; fi
    printf '%s' "$bexp" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T' || continue
    [[ "$bexp" < "$now_iso" ]] || continue
    reaped=$((reaped + 1))
    log "reap #$num ($repo) — stale claim session=$bsess expired=$bexp"
    post_comment "$repo" "$num" \
      "HANDOFF released=stale-reaper session=$bsess by=$actor at=$now_iso"
    if printf '%s\n' "$body" | grep -q 'agent-state:v1'; then
      printf '%s\n' "$body" \
        | rewrite_state "todo" "none" "none" "none" "none" "none" \
        | write_body "$repo" "$num"
    fi
    set_board_status "$item" "$STATUS_TODO" "$STATUS_TODO_NAME"
  done <<< "$inprog"
  log "reap — scanned=$scanned reaped=$reaped"
}

# fresh (uncached) board Status of one item
item_status() {
  project_item_status_by_id "$1"
}

# --- subcommand: backlog-add --------------------------------------------------
# Capture discovered out-of-scope work as a Backlog board issue. Backlog items
# are not eligible for claim until a human/agent triages them to Todo.
# Protocol: docs/board-protocol.md.
cmd_backlog_add() {
  [ -n "${1:-}" ] || die "backlog-add needs a \"<title>\""
  local title="$1"
  local repo="${OPT_REPO:-Halildeu/platform-k8s-gitops}"
  local kind="${OPT_KIND:-issue}"
  case "$kind" in
    issue|risk) : ;;
    *) die "backlog-add --kind must be 'issue' or 'risk'" ;;
  esac
  printf '%s' "$repo" | grep -Eq '^[^/ ]+/[^/ ]+$' \
    || die "backlog-add --repo must be owner/repo"

  # governance — the project-roadmap label must exist in the target repo
  gh api "repos/$repo/labels/project-roadmap" >/dev/null 2>&1 \
    || die "backlog-add — repo '$repo' has no 'project-roadmap' label (governance)"

  local sid wt branch now kopt body
  sid="$(session_id)"
  wt="$(git rev-parse --show-toplevel 2>/dev/null || echo unknown)"
  branch="$(git branch --show-current 2>/dev/null || echo unknown)"
  now="$(iso_now)"
  case "$kind" in issue) kopt="$KIND_ISSUE" ;; risk) kopt="$KIND_RISK" ;; esac

  body="## Agent State

<!-- agent-state:v1
status: backlog
claim_session: none
claim_worktree: none
claim_branch: none
claim_updated_at: none
expires_at: none
-->

**Kind:** $kind  ·  **Status:** Backlog (triage edilmedi)
**Discovered from:** $wt @ $branch (session $sid) at $now

### Context

${OPT_NOTE:-(baglam verilmedi — backlog-add --note ile eklenir)}

### Triage

Bu item Backlog lane'inde — claim EDILEMEZ. Triage'da Status=Todo + Faz /
Track / Priority + acceptance kriteri / Next Action doldurulur; sonra
eligible is olur. Protokol: docs/board-protocol.md."

  if [ "$DRY_RUN" -eq 1 ]; then
    log "[dry-run] backlog-add — would create a Backlog issue in $repo"
    log "  title: $title"
    log "  kind:  $kind"
    log "  note:  ${OPT_NOTE:-<none>}"
    return 0
  fi

  local url item
  url="$(printf '%s' "$body" | gh issue create --repo "$repo" --title "$title" \
    --label project-roadmap --body-file - 2>/dev/null)" \
    || die "backlog-add — failed to create issue in $repo"
  log "backlog-add — created $url"
  item="$(gh project item-add "$PROJECT_NUMBER" --owner "$PROJECT_OWNER" \
    --url "$url" --format json 2>/dev/null | jq -r '.id // empty')"
  [ -n "$item" ] || die "backlog-add — failed to add $url to the board"
  project_set_single_select "$item" "$KIND_FIELD" "$kopt" "Kind" "$kind"

  # set Status=Backlog, then reconcile against the native item-added->Todo
  # workflow (async — it can flip a freshly-added item back to Todo)
  local cur i
  project_set_single_select "$item" "$STATUS_FIELD" "$STATUS_BACKLOG" "Status" "$STATUS_BACKLOG_NAME"
  for i in 1 2 3 4 5; do
    sleep 8
    cur="$(item_status "$item")"
    if [ "$cur" != "Backlog" ]; then
      log "backlog-add — Status drifted to '${cur:-empty}' (item-added race/lag), re-setting (round $i)"
      project_set_single_select "$item" "$STATUS_FIELD" "$STATUS_BACKLOG" "Status" "$STATUS_BACKLOG_NAME"
    fi
  done
  cur="$(item_status "$item")"
  if [ "$cur" = "Backlog" ]; then
    log "backlog-add — $url on board: Kind=$kind Status=$STATUS_BACKLOG_NAME (triage needed)"
  else
    die "backlog-add — $url created + on board, but Status is '${cur:-?}', not Backlog — set it manually (capture incomplete)"
  fi
}

# --- arg parse + dispatch -----------------------------------------------------
main() {
  local cmd="" args=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run)     DRY_RUN=1; shift ;;
      --force-stale) FORCE_STALE=1; shift ;;
      --pr)          [ $# -ge 2 ] || die "--pr needs a value"; OPT_PR="$2"; shift 2 ;;
      --pr-repo)     [ $# -ge 2 ] || die "--pr-repo needs a value"; OPT_PR_REPO="$2"; shift 2 ;;
      --repo)        [ $# -ge 2 ] || die "--repo needs a value"; OPT_REPO="$2"; shift 2 ;;
      --limit)       [ $# -ge 2 ] || die "--limit needs a value"; OPT_LIMIT="$2"; shift 2 ;;
      --note)        [ $# -ge 2 ] || die "--note needs a value"; OPT_NOTE="$2"; shift 2 ;;
      --kind)        [ $# -ge 2 ] || die "--kind needs a value"; OPT_KIND="$2"; shift 2 ;;
      --issue)       [ $# -ge 2 ] || die "--issue needs a value"; OPT_ISSUE="$2"; shift 2 ;;
      --session)     [ $# -ge 2 ] || die "--session needs a value"; OPT_SESSION="$2"; shift 2 ;;
      --operation)   [ $# -ge 2 ] || die "--operation needs a value"; OPT_OPERATION="$2"; shift 2 ;;
      --worktree)    [ $# -ge 2 ] || die "--worktree needs a value"; OPT_WORKTREE="$2"; shift 2 ;;
      --branch)      [ $# -ge 2 ] || die "--branch needs a value"; OPT_BRANCH="$2"; shift 2 ;;
      --mutation-risk) [ $# -ge 2 ] || die "--mutation-risk needs a value"; OPT_MUTATION_RISK="$2"; shift 2 ;;
      --intent)      [ $# -ge 2 ] || die "--intent needs a value"; OPT_INTENT="$2"; shift 2 ;;
      --intent-file) [ $# -ge 2 ] || die "--intent-file needs a value"; OPT_INTENT_FILE="$2"; shift 2 ;;
      -h|--help)     usage 0 ;;
      *) if [ -z "$cmd" ]; then cmd="$1"; else args+=("$1"); fi; shift ;;
    esac
  done
  [ -n "$cmd" ] || usage 1

  preflight "$cmd"
  case "$cmd" in
    list)       cmd_list ;;
    claim)      cmd_claim "${args[@]:-}" ;;
    require-claim) cmd_require_claim "${args[@]:-}" ;;
    record-deny) cmd_record_deny ;;
    graphql-budget) cmd_graphql_budget ;;
    drain-project-queue) cmd_drain_project_queue "${args[@]:-}" ;;
    heartbeat)  cmd_heartbeat "${args[@]:-}" ;;
    release)    cmd_release "${args[@]:-}" ;;
    sync-state) cmd_sync_state "${args[@]:-}" ;;
    verify)     cmd_verify "${args[@]:-}" ;;
    reap)       cmd_reap ;;
    backlog-add) cmd_backlog_add "${args[@]:-}" ;;
    *)          die "unknown subcommand: $cmd (try --help)" ;;
  esac
}

main "$@"
