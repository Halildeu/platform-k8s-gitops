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
#
# <issue>: bare number (resolved via board), owner/repo#N, or full URL.
# Session id: $BOARD_SESSION_ID if set, else generated and printed.
set -euo pipefail

# --- board reference (see docs/board-protocol.md section 13) ------------------
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
if ! [[ "$PROJECT_ITEM_LIMIT" =~ ^[0-9]+$ ]] || [ "$PROJECT_ITEM_LIMIT" -lt 200 ]; then
  echo "ERR: PROJECT_ITEM_LIMIT='$PROJECT_ITEM_LIMIT' must be an integer >= 200" >&2
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
BOARD_CACHE=""

# --- helpers ------------------------------------------------------------------
log()  { printf '%s\n' "$*" >&2; }
die()  { printf 'board-sync: %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '4,31p' "$0" | sed 's/^# \{0,1\}//'
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

preflight() {
  command -v gh >/dev/null 2>&1 || die "gh CLI not found in PATH"
  command -v jq >/dev/null 2>&1 || die "jq not found in PATH"
  gh auth status >/dev/null 2>&1 || die "gh not authenticated (gh auth status failed)"
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
  local pid
  pid="$(gh project view "$PROJECT_NUMBER" --owner "$PROJECT_OWNER" --format json 2>/dev/null \
    | jq -r '.id // empty')"
  [ "$pid" = "$PROJECT_ID" ] \
    || die "project id mismatch: expected $PROJECT_ID, got '${pid:-none}'"
}

board_json() {
  if [ -z "$BOARD_CACHE" ]; then
    BOARD_CACHE="$(mktemp -t board-sync.XXXXXX)"
    gh project item-list "$PROJECT_NUMBER" --owner "$PROJECT_OWNER" \
      --format json --limit "$PROJECT_ITEM_LIMIT" >"$BOARD_CACHE" \
      || die "failed to fetch board items"
  fi
  cat "$BOARD_CACHE"
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

# resolve_issue <number|url> -> sets REPO NUM ITEM_ID ITEM_STATUS ITEM_KIND
resolve_issue() {
  local arg="$1"
  REPO=""; NUM=""; ITEM_ID=""; ITEM_STATUS=""; ITEM_KIND=""
  if printf '%s' "$arg" | grep -q '^https://github.com/'; then
    local path
    path="${arg#https://github.com/}"
    REPO="${path%%/issues/*}"
    NUM="${path##*/}"
  else
    NUM="$arg"
  fi
  printf '%s' "$NUM" | grep -Eq '^[0-9]+$' || die "bad issue ref: '$arg'"

  local matches
  matches="$(board_matches "$NUM" "$REPO")"

  local count
  count="$(printf '%s\n' "$matches" | grep -c . || true)"
  [ "$count" -eq 0 ] && die "issue #$NUM not found on board (is it a roadmap issue?)"
  [ "$count" -gt 1 ] && die "issue #$NUM ambiguous across repos — pass the full issue URL"

  ITEM_ID="$(printf '%s' "$matches" | cut -f1)"
  ITEM_STATUS="$(printf '%s' "$matches" | cut -f2)"
  ITEM_KIND="$(printf '%s' "$matches" | cut -f5)"
  local url
  url="$(printf '%s' "$matches" | cut -f3)"
  if [ -z "$REPO" ] && [ -n "$url" ]; then
    local p
    p="${url#https://github.com/}"
    REPO="${p%%/issues/*}"
  fi
  [ -n "$REPO" ] || die "could not resolve repo for issue #$NUM"
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
  gh project item-edit --id "$1" --project-id "$PROJECT_ID" \
    --field-id "$STATUS_FIELD" --single-select-option-id "$2" >/dev/null \
    || die "failed to set board Status"
  log "board Status -> $3"
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
cmd_require_claim() {
  local issue_ref="${OPT_ISSUE:-${1:-}}"
  [ -n "$issue_ref" ] || die "require-claim needs --issue <issue>"
  [ -n "$OPT_OPERATION" ] || die "require-claim needs --operation <class>"
  valid_operation_class "$OPT_OPERATION" \
    || die "require-claim unknown --operation '$OPT_OPERATION'"

  resolve_issue "$issue_ref"

  local sid wt branch body bstatus bsess bwt bbr bexp now_iso item_json field value
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

  item_json="$(board_json | jq -c --arg id "$ITEM_ID" '.items[] | select(.id == $id)' | head -1)"
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

  local allowed deny_code details_json actor bucket minute bucket_min intent_src intent_id
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
    intent_src="$REPO#$NUM|$sid|$OPT_OPERATION|$deny_code|mirror-v1-no-ledger|$bucket|$actor"
    intent_id="$(printf '%s' "$intent_src" | shasum -a 256 | awk '{print $1}')"
  fi

  jq -n \
    --arg allowed "$allowed" \
    --arg issue "$REPO#$NUM" \
    --arg session "$sid" \
    --arg operation "$OPT_OPERATION" \
    --arg status "$ITEM_STATUS" \
    --arg source "project_issue_mirror_v1" \
    --arg deny_code "$deny_code" \
    --arg deny_event_intent_id "$intent_id" \
    --argjson details "$details_json" \
    '{
      allowed: ($allowed == "true"),
      issue: $issue,
      session: $session,
      operation: $operation,
      permission_source: $source,
      project_status: $status,
      deny_code: (if $deny_code == "" then null else $deny_code end),
      deny_event_intent_id: (if $deny_event_intent_id == "" then null else $deny_event_intent_id end),
      details: $details
    }'

  [ "$allowed" = "true" ]
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
cmd_release() {
  [ -n "${1:-}" ] || die "release needs an <issue>"
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
# PR-merge evidence: a merged PR's `Tracked by #N` -> board Status Needs Verify
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

  # graceful skip if the ref is not a single board issue (curated board —
  # not every issue is roadmap-tracked; ambiguity is not a hard error here)
  local cnt
  cnt="$(board_matches "$vnum" "$vrepo" | grep -c . || true)"
  if [ "$cnt" -eq 0 ]; then
    log "verify skip — #$vnum not on the board (curated — not a roadmap issue)"
    return 0
  fi
  if [ "$cnt" -gt 1 ]; then
    log "verify skip — #$vnum ambiguous across repos (use owner/repo#N)"
    return 0
  fi
  resolve_issue "$ref"

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
  gh project item-list "$PROJECT_NUMBER" --owner "$PROJECT_OWNER" \
    --format json --limit "$PROJECT_ITEM_LIMIT" \
    | jq -r --arg id "$1" '.items[] | select(.id == $id) | .status // ""'
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
  gh project item-edit --id "$item" --project-id "$PROJECT_ID" \
    --field-id "$KIND_FIELD" --single-select-option-id "$kopt" >/dev/null \
    || die "backlog-add — failed to set Kind"

  # set Status=Backlog, then reconcile against the native item-added->Todo
  # workflow (async — it can flip a freshly-added item back to Todo)
  local cur i
  gh project item-edit --id "$item" --project-id "$PROJECT_ID" \
    --field-id "$STATUS_FIELD" --single-select-option-id "$STATUS_BACKLOG" >/dev/null \
    || die "backlog-add — failed to set Status"
  for i in 1 2 3 4 5; do
    sleep 8
    cur="$(item_status "$item")"
    if [ "$cur" != "Backlog" ]; then
      log "backlog-add — Status drifted to '${cur:-empty}' (item-added race/lag), re-setting (round $i)"
      gh project item-edit --id "$item" --project-id "$PROJECT_ID" \
        --field-id "$STATUS_FIELD" --single-select-option-id "$STATUS_BACKLOG" >/dev/null \
        || die "backlog-add — failed to re-set Status"
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
      -h|--help)     usage 0 ;;
      *) if [ -z "$cmd" ]; then cmd="$1"; else args+=("$1"); fi; shift ;;
    esac
  done
  [ -n "$cmd" ] || usage 1

  preflight
  case "$cmd" in
    list)       cmd_list ;;
    claim)      cmd_claim "${args[@]:-}" ;;
    require-claim) cmd_require_claim "${args[@]:-}" ;;
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
