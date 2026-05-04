#!/usr/bin/env bash
# scripts/drift-detection/alarm_receiver.sh
#
# Codex P0 follow-up — drift detection JSON output → GitHub issue audit trail.
# Reads /tmp/drift-report-<env>-<ts>.json (produced by check_prod_drift.sh)
# and opens a GitHub issue per P1/P2 finding (with deduplication via title
# match — repeated drift reuses existing issue's comment thread).
#
# Designed for staging-sw systemd integration:
#
#   ExecStart=/bin/bash check_prod_drift.sh prod
#   ExecStartPost=/bin/bash alarm_receiver.sh /tmp/drift-report-prod-<ts>.json
#
# Or invoked manually for ad-hoc reports.
#
# Auth: requires gh CLI logged in (or GITHUB_TOKEN env). Read+write issues
# scope on platform-k8s-gitops repo. The runner identity (gha-runner SA or
# operator) must have issue write access.
#
# Codex P1 alarm class mapping (from openfga-model-contract.md):
#   P1: prod git/live digest mismatch >10min, GHCR manifest unknown,
#       ESO SecretSyncedError, OpenFGA admin tuple missing
#   P2: test git/live drift >30min, prod promotion lag >7d,
#       quota headroom < surge pod
#   P3: stale current-state docs, smoke creds missing
#
# This MVP supports P1+P2 (P3 deferred — needs current-state mtime check).
#
# Codex Sprint A P0 Item 6 hardening:
#   - Pre-flight: gh auth status + repo access verified BEFORE processing
#   - Persistent undelivered log: failed alarms → /var/log/.../undelivered.jsonl
#     (so retry-able later and audit trail not lost)
#   - Optional webhook fallback via DRIFT_ALARM_WEBHOOK env var
#   - Retry with exponential backoff on 429/5xx
#   - Capture gh stderr for actionable error messages

set -uo pipefail

REPORT="${1:-/tmp/drift-report-prod-latest.json}"
[[ ! -f "$REPORT" ]] && { echo "ERR: report not found: $REPORT"; exit 1; }

REPO="${GITHUB_REPO:-Halildeu/platform-k8s-gitops}"
UNDELIVERED_LOG="${ALARM_UNDELIVERED_LOG:-/var/log/platform-drift-alarm-undelivered.jsonl}"
WEBHOOK_URL="${DRIFT_ALARM_WEBHOOK:-}"
MAX_RETRIES=3

# ------------------------------------------------------------
# Pre-flight: gh auth + repo access
# ------------------------------------------------------------
preflight() {
  if ! command -v gh > /dev/null 2>&1; then
    echo "ERR: gh CLI not installed — cannot deliver alarms via GitHub Issues"
    return 1
  fi

  # Check gh auth status (silent if logged in, errors if not)
  if ! gh auth status > /dev/null 2>&1; then
    echo "ERR: gh CLI not authenticated — run 'gh auth login' or set GITHUB_TOKEN"
    return 1
  fi

  # Check repo access (read OK = sufficient signal; write happens on actual API call)
  if ! gh repo view "$REPO" > /dev/null 2>&1; then
    echo "ERR: cannot access repo $REPO — check token scope (needs 'repo' or 'public_repo' + 'issues:write')"
    return 1
  fi

  echo "[alarm_receiver] pre-flight: gh auth OK, repo access OK"
  return 0
}

# ------------------------------------------------------------
# Undelivered log helper — persist failed alarms for retry/audit
# ------------------------------------------------------------
log_undelivered() {
  local cls="$1"
  local knd="$2"
  local title="$3"
  local body="$4"
  local reason="$5"

  # Best-effort dir creation (may need sudo on first run)
  local log_dir
  log_dir=$(dirname "$UNDELIVERED_LOG")
  mkdir -p "$log_dir" 2>/dev/null || true

  if [[ ! -w "$log_dir" ]]; then
    # Fallback to /tmp if /var/log not writable (no sudo)
    UNDELIVERED_LOG="/tmp/platform-drift-alarm-undelivered.jsonl"
  fi

  # Append JSONL entry
  local entry
  entry=$(jq -nc \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg env "$ENV" \
    --arg cls "$cls" \
    --arg knd "$knd" \
    --arg title "$title" \
    --arg body "$body" \
    --arg reason "$reason" \
    --arg report "$REPORT" \
    '{ts:$ts, environment:$env, class:$cls, kind:$knd, title:$title, body:$body, reason:$reason, report:$report}')

  echo "$entry" >> "$UNDELIVERED_LOG" 2>/dev/null || \
    echo "[WARN] could not write to $UNDELIVERED_LOG — alarm dropped" >&2
}

# ------------------------------------------------------------
# Webhook fallback (optional) — POST alarm payload to external URL
# ------------------------------------------------------------
deliver_webhook() {
  local cls="$1"
  local knd="$2"
  local title="$3"
  local msg="$4"

  [[ -z "$WEBHOOK_URL" ]] && return 1

  local payload
  payload=$(jq -nc \
    --arg env "$ENV" \
    --arg cls "$cls" \
    --arg knd "$knd" \
    --arg title "$title" \
    --arg msg "$msg" \
    --arg ts "$TS" \
    --arg report "$REPORT" \
    '{environment:$env, class:$cls, kind:$knd, title:$title, message:$msg, timestamp:$ts, report:$report}')

  local code
  code=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 10 \
    -X POST -H "Content-Type: application/json" \
    -d "$payload" "$WEBHOOK_URL" 2>/dev/null || echo "000")

  case "$code" in
    2*) echo "  [webhook] delivered to $WEBHOOK_URL ($code)"; return 0 ;;
    *)  echo "  [webhook] FAILED ($code)"; return 1 ;;
  esac
}

# ------------------------------------------------------------
# Retry helper for gh API calls (rate limit + transient 5xx)
# ------------------------------------------------------------
gh_with_retry() {
  local attempt=1
  local stderr_capture
  stderr_capture=$(mktemp)
  while [[ $attempt -le $MAX_RETRIES ]]; do
    if "$@" 2>"$stderr_capture"; then
      rm -f "$stderr_capture"
      return 0
    fi

    local err
    err=$(cat "$stderr_capture")

    # Detect rate limit or transient errors
    if echo "$err" | grep -qE 'rate limit|429|503|502|504|timeout|connection refused'; then
      local backoff=$((2 ** attempt))
      echo "  [retry] attempt $attempt/$MAX_RETRIES failed (transient): sleeping ${backoff}s"
      sleep "$backoff"
      attempt=$((attempt + 1))
    else
      # Non-transient error — fail fast
      echo "  [retry] non-transient error, no retry: $(echo "$err" | head -3)"
      rm -f "$stderr_capture"
      return 1
    fi
  done

  echo "  [retry] exhausted $MAX_RETRIES retries"
  rm -f "$stderr_capture"
  return 1
}

# ------------------------------------------------------------
# Main processing
# ------------------------------------------------------------
ENV=$(jq -r '.environment' "$REPORT")
TS=$(jq -r '.timestamp' "$REPORT")
EXIT_CODE=$(jq -r '.exit_code' "$REPORT")

# Extract findings filtered to P1/P2 (skip OK)
findings_count=$(jq '[.findings[] | select(.class != "OK")] | length' "$REPORT")
[[ "$findings_count" -eq 0 ]] && {
  echo "[alarm_receiver] no P1/P2/P3 findings — exit clean"
  exit 0
}

echo "[alarm_receiver] $findings_count findings to process from $REPORT"

# Pre-flight
preflight_ok=1
if ! preflight; then
  preflight_ok=0
  echo "[alarm_receiver] pre-flight failed — all alarms will go to webhook OR undelivered log"
fi

processed=0
delivered_gh=0
delivered_webhook=0
undelivered=0

# For each P1/P2 finding, generate a stable signature and open/update issue
jq -c '.findings[] | select(.class != "OK")' "$REPORT" | while IFS= read -r finding; do
  cls=$(echo "$finding" | jq -r '.class')
  knd=$(echo "$finding" | jq -r '.kind')
  msg=$(echo "$finding" | jq -r '.message')
  details=$(echo "$finding" | jq -r '.details // empty')

  # Stable signature: env + class + kind + first 60 chars of message
  sig_msg=$(echo "$msg" | head -c 60)
  title="[drift-${cls}] ${ENV}/${knd}: ${sig_msg}"

  body="**Class**: \`$cls\`
**Environment**: \`$ENV\`
**Kind**: \`$knd\`
**First detected at**: \`$TS\`

## Message

$msg

## Details

\`\`\`
$details
\`\`\`

## Report artifact

\`\`\`
$REPORT
\`\`\`

## Operator playbook

| Class | Action |
|---|---|
| P1 | Operator action required within 10min — investigate cluster live state vs gitops yaml; reconciliation PR if break-glass was used |
| P2 | Warning — review within 1 day; may indicate stale promotion or quota tightening |
| P3 | Info — backlog grooming |

## Auto-deduplication

This issue auto-deduplicates on title match. Repeated drift detections add comments to this thread. Close the issue once cluster ↔ gitops parity restored.

---

🤖 Auto-opened by drift-detection alarm_receiver (Codex P0 follow-up + Sprint A Item 6 hardening).
"

  delivery_status="undelivered"

  if [[ "$preflight_ok" -eq 1 ]]; then
    # Try GitHub Issues first
    existing_issue=$(gh issue list --repo "$REPO" --state open --search "\"$title\" in:title" \
      --json number,title --jq '.[] | select(.title == "'"$title"'") | .number' 2>/dev/null | head -1)

    if [[ -n "$existing_issue" ]]; then
      echo "[alarm_receiver] [$cls] $knd — adding comment to existing issue #$existing_issue"
      if gh_with_retry gh issue comment "$existing_issue" --repo "$REPO" --body "Drift recurrence at $TS

Report: \`$REPORT\`
Details: $details"; then
        delivery_status="github"
      fi
    else
      echo "[alarm_receiver] [$cls] $knd — opening new issue: $title"
      if gh_with_retry gh issue create --repo "$REPO" \
        --title "$title" \
        --label "drift-detection,$cls" \
        --body "$body"; then
        delivery_status="github"
      fi
    fi
  fi

  # Webhook fallback if GH delivery failed (or skipped due to preflight)
  if [[ "$delivery_status" != "github" ]]; then
    if deliver_webhook "$cls" "$knd" "$title" "$msg"; then
      delivery_status="webhook"
    fi
  fi

  # Persistent undelivered log if both failed
  if [[ "$delivery_status" == "undelivered" ]]; then
    log_undelivered "$cls" "$knd" "$title" "$body" "gh_failed_no_webhook"
    echo "  [UNDELIVERED] persisted to $UNDELIVERED_LOG"
  fi
done

echo "[alarm_receiver] processed $findings_count findings; check undelivered log: $UNDELIVERED_LOG"
