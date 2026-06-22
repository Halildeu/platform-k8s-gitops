#!/usr/bin/env bash
set -euo pipefail

# Redacted ownership guard for Faz 22.6.3 Remote Response Terminal live smoke.
#
# The guard uses GitHub issue comments as a lightweight coordination ledger. It
# stores hashes of session/endpoint identifiers, never raw remote-bridge session
# ids, bearer tokens, JWTs, endpoint hostnames, or user data.

ACTION="${ACTION:-check}" # claim | check | release | comment-template
SESSION_OWNER_ISSUE_URL="${SESSION_OWNER_ISSUE_URL:-${SESSION_OWNER_ISSUE:-}}"
SESSION_OWNER_ENDPOINT_ID="${SESSION_OWNER_ENDPOINT_ID:-}"
SESSION_OWNER_PURPOSE="${SESSION_OWNER_PURPOSE:-remote-response-terminal-smoke}"
SESSION_OWNER_TTL_MINUTES="${SESSION_OWNER_TTL_MINUTES:-45}"
SESSION_OWNER_OPERATION_SOURCE="${SESSION_OWNER_OPERATION_SOURCE:-${OPERATION_SOURCE:-catalog}}"
SESSION_OWNER_COMMENTS_FILE="${SESSION_OWNER_COMMENTS_FILE:-}"
SESSION_OWNER_RELEASE_REASON="${SESSION_OWNER_RELEASE_REASON:-done}"
REMOTE_BRIDGE_SESSION_ID="${REMOTE_BRIDGE_SESSION_ID:-}"
CATALOG_OPERATION_ID="${CATALOG_OPERATION_ID:-GET_HOSTNAME}"
APPROVED_SCRIPT_ID="${APPROVED_SCRIPT_ID:-DIAG_HOSTNAME}"

ISSUE_OWNER=""
ISSUE_REPO=""
ISSUE_NUMBER=""
ISSUE_API_PATH=""
ISSUE_DISPLAY="offline"

die() {
  printf 'ERR %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

safe_kv_value() {
  local label="$1" value="$2"
  [[ -n "$value" ]] || die "$label is required"
  [[ "$value" =~ ^[A-Za-z0-9._:@/#=-]+$ ]] \
    || die "$label contains characters unsafe for issue-comment key/value ledger"
}

validate_inputs() {
  case "$ACTION" in
    claim|check|release|comment-template) ;;
    *) die "ACTION must be claim, check, release, or comment-template" ;;
  esac

  [[ -n "$REMOTE_BRIDGE_SESSION_ID" ]] || die "REMOTE_BRIDGE_SESSION_ID is required"
  [[ -n "$SESSION_OWNER_ENDPOINT_ID" ]] || die "SESSION_OWNER_ENDPOINT_ID is required"
  [[ "$SESSION_OWNER_TTL_MINUTES" =~ ^[0-9]+$ ]] \
    || die "SESSION_OWNER_TTL_MINUTES must be a positive integer"
  (( SESSION_OWNER_TTL_MINUTES > 0 )) \
    || die "SESSION_OWNER_TTL_MINUTES must be greater than zero"

  safe_kv_value SESSION_OWNER_PURPOSE "$SESSION_OWNER_PURPOSE"
  safe_kv_value SESSION_OWNER_OPERATION_SOURCE "$SESSION_OWNER_OPERATION_SOURCE"
  safe_kv_value CATALOG_OPERATION_ID "$CATALOG_OPERATION_ID"
  safe_kv_value APPROVED_SCRIPT_ID "$APPROVED_SCRIPT_ID"
  safe_kv_value SESSION_OWNER_RELEASE_REASON "$SESSION_OWNER_RELEASE_REASON"
}

parse_issue_ref() {
  local ref="$1"
  if [[ -z "$ref" && -n "$SESSION_OWNER_COMMENTS_FILE" ]]; then
    ISSUE_DISPLAY="offline"
    return 0
  fi
  [[ -n "$ref" ]] || die "SESSION_OWNER_ISSUE_URL or SESSION_OWNER_ISSUE is required"
  ref="${ref%%\?*}"
  ref="${ref%%#*}"
  ref="${ref%/}"

  if [[ "$ref" =~ ^https://github.com/([^/]+)/([^/]+)/issues/([0-9]+)$ ]]; then
    ISSUE_OWNER="${BASH_REMATCH[1]}"
    ISSUE_REPO="${BASH_REMATCH[2]}"
    ISSUE_NUMBER="${BASH_REMATCH[3]}"
  elif [[ "$ref" =~ ^([^/]+)/([^#]+)#([0-9]+)$ ]]; then
    ISSUE_OWNER="${BASH_REMATCH[1]}"
    ISSUE_REPO="${BASH_REMATCH[2]}"
    ISSUE_NUMBER="${BASH_REMATCH[3]}"
  else
    die "unsupported issue ref: $ref (use https://github.com/OWNER/REPO/issues/N or OWNER/REPO#N)"
  fi

  ISSUE_API_PATH="repos/${ISSUE_OWNER}/${ISSUE_REPO}/issues/${ISSUE_NUMBER}"
  ISSUE_DISPLAY="${ISSUE_OWNER}/${ISSUE_REPO}#${ISSUE_NUMBER}"
}

sha256_value() {
  local value="$1"
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$value" | shasum -a 256 | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$value" | sha256sum | awk '{print $1}'
  else
    die "missing command: shasum or sha256sum"
  fi
}

short_hash() {
  printf '%s' "$1" | cut -c1-12
}

now_iso() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

expires_iso() {
  local minutes="$1"
  if date -u -v+"${minutes}"M +%Y-%m-%dT%H:%M:%SZ >/dev/null 2>&1; then
    date -u -v+"${minutes}"M +%Y-%m-%dT%H:%M:%SZ
  elif date -u -d "+${minutes} minutes" +%Y-%m-%dT%H:%M:%SZ >/dev/null 2>&1; then
    date -u -d "+${minutes} minutes" +%Y-%m-%dT%H:%M:%SZ
  else
    die "date implementation cannot add minutes"
  fi
}

build_owner_comment() {
  local session_hash="$1" endpoint_hash="$2" expires_at="$3"
  printf 'LIVE-SESSION-OWNER status=active session_sha256=%s endpoint_sha256=%s expires_at=%s purpose=%s operation_source=%s catalog_operation_id=%s approved_script_id=%s issue=%s\n\nBoundary: raw remote-bridge session id, bearer token, JWT, endpoint hostname, and user data intentionally omitted. Use ACTION=release after the live smoke or when the session is abandoned.\n' \
    "$session_hash" \
    "$endpoint_hash" \
    "$expires_at" \
    "$SESSION_OWNER_PURPOSE" \
    "$SESSION_OWNER_OPERATION_SOURCE" \
    "$CATALOG_OPERATION_ID" \
    "$APPROVED_SCRIPT_ID" \
    "$ISSUE_DISPLAY"
}

build_release_comment() {
  local session_hash="$1" endpoint_hash="$2" released_at="$3"
  printf 'LIVE-SESSION-RELEASE session_sha256=%s endpoint_sha256=%s released_at=%s reason=%s issue=%s\n\nBoundary: release comment invalidates the matching redacted live-session ownership claim only. Raw session id and bearer values intentionally omitted.\n' \
    "$session_hash" \
    "$endpoint_hash" \
    "$released_at" \
    "$SESSION_OWNER_RELEASE_REASON" \
    "$ISSUE_DISPLAY"
}

fetch_comments_json() {
  if [[ -n "$SESSION_OWNER_COMMENTS_FILE" ]]; then
    [[ -f "$SESSION_OWNER_COMMENTS_FILE" ]] || die "SESSION_OWNER_COMMENTS_FILE not found"
    cat "$SESSION_OWNER_COMMENTS_FILE"
    return 0
  fi
  need_cmd gh
  gh api "${ISSUE_API_PATH}/comments?per_page=100" --paginate --slurp | jq '[.[][]]'
}

post_issue_comment() {
  local body="$1"
  [[ -z "$SESSION_OWNER_COMMENTS_FILE" ]] \
    || die "cannot post comments when SESSION_OWNER_COMMENTS_FILE is set"
  need_cmd gh
  gh api "${ISSUE_API_PATH}/comments" -X POST -f body="$body" --jq '.html_url'
}

kv_from_line() {
  local line="$1" key="$2" token
  for token in $line; do
    case "$token" in
      "${key}="*)
        printf '%s' "${token#*=}"
        return 0
        ;;
    esac
  done
  printf ''
}

release_after_claim() {
  local releases="$1" claim_id="$2" claim_created="$3" session_hash="$4" endpoint_hash="$5"
  local release_id release_created release_line release_session release_endpoint
  while IFS=$'\t' read -r release_id release_created release_line; do
    [[ -n "${release_id:-}" ]] || continue
    release_session="$(kv_from_line "$release_line" session_sha256)"
    release_endpoint="$(kv_from_line "$release_line" endpoint_sha256)"
    [[ "$release_session" == "$session_hash" && "$release_endpoint" == "$endpoint_hash" ]] || continue
    if [[ "$release_created" > "$claim_created" ]]; then
      return 0
    fi
    if [[ "$release_created" == "$claim_created" && "$release_id" -gt "$claim_id" ]]; then
      return 0
    fi
  done <<< "$releases"
  return 1
}

active_owner_for_endpoint() {
  local session_hash="$1" endpoint_hash="$2" comments now owners releases
  local owner_id owner_created owner_line owner_status owner_session owner_endpoint owner_expires

  comments="$(fetch_comments_json)"
  now="$(now_iso)"
  owners="$(printf '%s' "$comments" \
    | jq -r '.[] | select((.body // "") | startswith("LIVE-SESSION-OWNER ")) | [.id, .created_at, ((.body | split("\n")[0]))] | @tsv' \
    | sort -t $'\t' -k2,2 -k1,1n)"
  releases="$(printf '%s' "$comments" \
    | jq -r '.[] | select((.body // "") | startswith("LIVE-SESSION-RELEASE ")) | [.id, .created_at, ((.body | split("\n")[0]))] | @tsv' \
    | sort -t $'\t' -k2,2 -k1,1n)"

  while IFS=$'\t' read -r owner_id owner_created owner_line; do
    [[ -n "${owner_id:-}" ]] || continue
    owner_status="$(kv_from_line "$owner_line" status)"
    owner_session="$(kv_from_line "$owner_line" session_sha256)"
    owner_endpoint="$(kv_from_line "$owner_line" endpoint_sha256)"
    owner_expires="$(kv_from_line "$owner_line" expires_at)"

    [[ "$owner_status" == "active" ]] || continue
    [[ "$owner_endpoint" == "$endpoint_hash" ]] || continue
    [[ "$owner_session" =~ ^[a-f0-9]{64}$ ]] || continue
    [[ "$owner_expires" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || continue
    [[ "$owner_expires" > "$now" ]] || continue
    if release_after_claim "$releases" "$owner_id" "$owner_created" "$owner_session" "$owner_endpoint"; then
      continue
    fi

    printf '%s\t%s\t%s\n' "$owner_id" "$owner_created" "$owner_session"
    return 0
  done <<< "$owners"

  return 1
}

evaluate_ownership() {
  local session_hash="$1" endpoint_hash="$2" comments now owners releases
  local owner_id owner_created owner_line owner_status owner_session owner_endpoint owner_expires
  local winner_id="" winner_session="" winner_created="" conflict_count=0 own_active_count=0

  comments="$(fetch_comments_json)"
  now="$(now_iso)"
  owners="$(printf '%s' "$comments" \
    | jq -r '.[] | select((.body // "") | startswith("LIVE-SESSION-OWNER ")) | [.id, .created_at, ((.body | split("\n")[0]))] | @tsv' \
    | sort -t $'\t' -k2,2 -k1,1n)"
  releases="$(printf '%s' "$comments" \
    | jq -r '.[] | select((.body // "") | startswith("LIVE-SESSION-RELEASE ")) | [.id, .created_at, ((.body | split("\n")[0]))] | @tsv' \
    | sort -t $'\t' -k2,2 -k1,1n)"

  while IFS=$'\t' read -r owner_id owner_created owner_line; do
    [[ -n "${owner_id:-}" ]] || continue
    owner_status="$(kv_from_line "$owner_line" status)"
    owner_session="$(kv_from_line "$owner_line" session_sha256)"
    owner_endpoint="$(kv_from_line "$owner_line" endpoint_sha256)"
    owner_expires="$(kv_from_line "$owner_line" expires_at)"

    [[ "$owner_status" == "active" ]] || continue
    [[ "$owner_endpoint" == "$endpoint_hash" ]] || continue
    [[ "$owner_session" =~ ^[a-f0-9]{64}$ ]] || continue
    [[ "$owner_expires" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || continue
    [[ "$owner_expires" > "$now" ]] || continue
    if release_after_claim "$releases" "$owner_id" "$owner_created" "$owner_session" "$owner_endpoint"; then
      continue
    fi

    if [[ -z "$winner_id" ]]; then
      winner_id="$owner_id"
      winner_session="$owner_session"
      winner_created="$owner_created"
    fi
    if [[ "$owner_session" == "$session_hash" ]]; then
      own_active_count=$((own_active_count + 1))
    else
      conflict_count=$((conflict_count + 1))
    fi
  done <<< "$owners"

  [[ -n "$winner_id" ]] || die "no active LIVE-SESSION-OWNER claim for endpoint_hash=$(short_hash "$endpoint_hash")"
  [[ "$winner_session" == "$session_hash" ]] \
    || die "session ownership conflict: active owner comment $winner_id wins for endpoint_hash=$(short_hash "$endpoint_hash")"
  [[ "$own_active_count" -gt 0 ]] \
    || die "no matching active owner claim for session_hash=$(short_hash "$session_hash") endpoint_hash=$(short_hash "$endpoint_hash")"
  [[ "$conflict_count" -eq 0 ]] \
    || die "active conflicting live-session claim exists for endpoint_hash=$(short_hash "$endpoint_hash"); release stale/lost claim before dispatch"

  printf 'REMOTE_RESPONSE_TERMINAL_SESSION_GUARD_STATUS=owned issue=%s owner_comment_id=%s owner_created_at=%s session_hash=%s endpoint_hash=%s\n' \
    "$ISSUE_DISPLAY" \
    "$winner_id" \
    "$winner_created" \
    "$(short_hash "$session_hash")" \
    "$(short_hash "$endpoint_hash")"
}

main() {
  need_cmd jq
  validate_inputs
  parse_issue_ref "$SESSION_OWNER_ISSUE_URL"

  local session_hash endpoint_hash expires_at comment_url
  session_hash="$(sha256_value "$REMOTE_BRIDGE_SESSION_ID")"
  endpoint_hash="$(sha256_value "$SESSION_OWNER_ENDPOINT_ID")"

  case "$ACTION" in
    comment-template)
      expires_at="$(expires_iso "$SESSION_OWNER_TTL_MINUTES")"
      build_owner_comment "$session_hash" "$endpoint_hash" "$expires_at"
      ;;
    claim)
      local active_owner active_owner_id active_owner_created active_owner_session
      active_owner="$(active_owner_for_endpoint "$session_hash" "$endpoint_hash" || true)"
      if [[ -n "$active_owner" ]]; then
        IFS=$'\t' read -r active_owner_id active_owner_created active_owner_session <<< "$active_owner"
        if [[ "$active_owner_session" != "$session_hash" ]]; then
          die "session ownership conflict: active owner comment $active_owner_id wins for endpoint_hash=$(short_hash "$endpoint_hash")"
        fi
        printf 'REMOTE_RESPONSE_TERMINAL_SESSION_GUARD_CLAIM_EXISTS issue=%s owner_comment_id=%s owner_created_at=%s session_hash=%s endpoint_hash=%s\n' \
          "$ISSUE_DISPLAY" \
          "$active_owner_id" \
          "$active_owner_created" \
          "$(short_hash "$session_hash")" \
          "$(short_hash "$endpoint_hash")"
        evaluate_ownership "$session_hash" "$endpoint_hash"
        return 0
      fi

      expires_at="$(expires_iso "$SESSION_OWNER_TTL_MINUTES")"
      comment_url="$(post_issue_comment "$(build_owner_comment "$session_hash" "$endpoint_hash" "$expires_at")")"
      printf 'REMOTE_RESPONSE_TERMINAL_SESSION_GUARD_CLAIM_COMMENT=%s session_hash=%s endpoint_hash=%s expires_at=%s\n' \
        "$comment_url" \
        "$(short_hash "$session_hash")" \
        "$(short_hash "$endpoint_hash")" \
        "$expires_at"
      evaluate_ownership "$session_hash" "$endpoint_hash"
      ;;
    check)
      evaluate_ownership "$session_hash" "$endpoint_hash"
      ;;
    release)
      comment_url="$(post_issue_comment "$(build_release_comment "$session_hash" "$endpoint_hash" "$(now_iso)")")"
      printf 'REMOTE_RESPONSE_TERMINAL_SESSION_GUARD_STATUS=released issue=%s release_comment=%s session_hash=%s endpoint_hash=%s\n' \
        "$ISSUE_DISPLAY" \
        "$comment_url" \
        "$(short_hash "$session_hash")" \
        "$(short_hash "$endpoint_hash")"
      ;;
  esac
}

main "$@"
