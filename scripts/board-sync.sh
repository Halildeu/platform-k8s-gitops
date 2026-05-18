#!/usr/bin/env bash
# scripts/board-sync.sh
#
# platform Roadmap (GitHub Project #2) agent sync tool.
# Makes the board an active, session-continuous, parallel-safe work surface.
# Protocol (canonical): docs/board-protocol.md
#
# Usage: board-sync.sh <subcommand> [<issue>] [flags]
#
# Subcommands:
#   list                  eligible Todo work + In Progress claim status
#   claim      <issue>    deterministic race-safe claim
#   heartbeat  <issue>    extend your active claim's lease
#   release    <issue>    release your claim (ownership-checked)
#   sync-state <issue>    report issue-body agent-state vs board Status
#
# Flags:
#   --dry-run             print mutations instead of executing them
#   --force-stale         (release) allow releasing another session's
#                         claim only if its lease is expired/stale
#
# <issue>: bare number (resolved via board) or full issue URL.
# Session id: $BOARD_SESSION_ID if set, else generated and printed.
set -euo pipefail

# --- board reference (see docs/board-protocol.md section 13) ------------------
PROJECT_OWNER="Halildeu"
PROJECT_NUMBER="2"
PROJECT_ID="PVT_kwHOCx7tY84BIN2d"
STATUS_FIELD="PVTSSF_lAHOCx7tY84BIN2dzg4vgLw"
STATUS_TODO="fcee11d3"
STATUS_INPROGRESS="02bba678"
STATUS_TODO_NAME="Todo"
STATUS_INPROGRESS_NAME="In Progress"
CLAIM_TTL_HOURS="2"

DRY_RUN=0
FORCE_STALE=0
BOARD_CACHE=""

# --- helpers ------------------------------------------------------------------
log()  { printf '%s\n' "$*" >&2; }
die()  { printf 'board-sync: %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '4,23p' "$0" | sed 's/^# \{0,1\}//'
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
      --format json --limit 200 >"$BOARD_CACHE" \
      || die "failed to fetch board items"
  fi
  cat "$BOARD_CACHE"
}

# resolve_issue <number|url> -> sets REPO NUM ITEM_ID ITEM_STATUS ITEM_TITLE
resolve_issue() {
  local arg="$1"
  REPO=""; NUM=""; ITEM_ID=""; ITEM_STATUS=""; ITEM_TITLE=""
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
  matches="$(board_json | jq -r --arg n "$NUM" --arg r "$REPO" '
    [ .items[]
      | select(.content.type == "Issue")
      | select((.content.number | tostring) == $n)
      | select($r == "" or (.content.url // "" | contains("/" + $r + "/")))
    ]
    | .[] | "\(.id)\t\(.status // "")\t\(.content.url // "")\t\(.title // "")"')"

  local count
  count="$(printf '%s\n' "$matches" | grep -c . || true)"
  [ "$count" -eq 0 ] && die "issue #$NUM not found on board (is it a roadmap issue?)"
  [ "$count" -gt 1 ] && die "issue #$NUM ambiguous across repos — pass the full issue URL"

  ITEM_ID="$(printf '%s' "$matches" | cut -f1)"
  ITEM_STATUS="$(printf '%s' "$matches" | cut -f2)"
  ITEM_TITLE="$(printf '%s' "$matches" | cut -f4)"
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
        | (([ $c.cexp ]
            + [ $hb[] | select(.session == $c.session and .created > $c.created) | .expires ])
           | max) as $eff
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

  local sid wt branch now exp slug claim_body winner
  sid="$(session_id)"
  wt="$(git rev-parse --show-toplevel 2>/dev/null || echo unknown)"
  branch="$(git branch --show-current 2>/dev/null || echo unknown)"
  now="$(iso_now)"
  exp="$(claim_expiry_iso)"
  slug="$(printf '%s' "$ITEM_TITLE" | tr '[:upper:]' '[:lower:]' \
    | tr -cs '[:alnum:]' '-' | sed 's/^-*//;s/-*$//' | cut -c1-32 | sed 's/-*$//')"
  [ -n "$slug" ] || slug="issue"

  log "claim #$NUM ($REPO) — session=$sid branch=$branch"
  [ -n "${BOARD_SESSION_ID:-}" ] || log "note: BOARD_SESSION_ID unset — reuse: export BOARD_SESSION_ID=$sid"

  claim_body="CLAIM session=$sid worktree=$wt branch=roadmap-$NUM-$slug at=$now expires=$exp"
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
      | rewrite_state "in-progress" "$sid" "$wt" "roadmap-$NUM-$slug" "$now" "$exp" \
      | write_body "$REPO" "$NUM"
    log "issue body agent-state -> in-progress"
  else
    log "WARN: issue #$NUM has no agent-state:v1 block — body not updated (see docs/board-protocol.md)"
  fi
  set_board_status "$ITEM_ID" "$STATUS_INPROGRESS" "$STATUS_INPROGRESS_NAME"
  log "claim WON — #$NUM is yours (lease $exp; run 'heartbeat $NUM' before it expires)"
}

# --- subcommand: heartbeat ----------------------------------------------------
cmd_heartbeat() {
  [ -n "${1:-}" ] || die "heartbeat needs an <issue>"
  resolve_issue "$1"
  local sid body bsess bwt bbr now exp
  sid="$(session_id)"
  body="$(issue_body "$REPO" "$NUM")"
  bsess="$(printf '%s\n' "$body" | state_get claim_session)"
  [ "$bsess" = "$sid" ] \
    || die "heartbeat refused — #$NUM claimed by session '${bsess:-none}', not you ($sid)"
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
    "In Progress|in-progress"|"Todo|todo"|"Blocked|blocked"|"Needs Verify|needs-verify"|"Done|done") : ;;
    "|"|"|none") : ;;
    *) log "  WARN: board Status and body agent-state disagree — reconcile" ;;
  esac
}

# --- arg parse + dispatch -----------------------------------------------------
main() {
  local cmd="" args=()
  for a in "$@"; do
    case "$a" in
      --dry-run)     DRY_RUN=1 ;;
      --force-stale) FORCE_STALE=1 ;;
      -h|--help)     usage 0 ;;
      *) if [ -z "$cmd" ]; then cmd="$a"; else args+=("$a"); fi ;;
    esac
  done
  [ -n "$cmd" ] || usage 1

  preflight
  case "$cmd" in
    list)       cmd_list ;;
    claim)      cmd_claim "${args[@]:-}" ;;
    heartbeat)  cmd_heartbeat "${args[@]:-}" ;;
    release)    cmd_release "${args[@]:-}" ;;
    sync-state) cmd_sync_state "${args[@]:-}" ;;
    *)          die "unknown subcommand: $cmd (try --help)" ;;
  esac
}

main "$@"
