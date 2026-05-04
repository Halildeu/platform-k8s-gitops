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

set -euo pipefail

REPORT="${1:-/tmp/drift-report-prod-latest.json}"
[[ ! -f "$REPORT" ]] && { echo "ERR: report not found: $REPORT"; exit 1; }

REPO="${GITHUB_REPO:-Halildeu/platform-k8s-gitops}"

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

# For each P1/P2 finding, generate a stable signature and open/update issue
jq -c '.findings[] | select(.class != "OK")' "$REPORT" | while IFS= read -r finding; do
  cls=$(echo "$finding" | jq -r '.class')
  knd=$(echo "$finding" | jq -r '.kind')
  msg=$(echo "$finding" | jq -r '.message')
  details=$(echo "$finding" | jq -r '.details // empty')

  # Stable signature: env + class + kind + first 60 chars of message
  # (so digest_drift on the same service produces 1 issue, not many)
  sig_msg=$(echo "$msg" | head -c 60)
  title="[drift-${cls}] ${ENV}/${knd}: ${sig_msg}"

  # Search for existing open issue with exact title
  existing_issue=$(gh issue list --repo "$REPO" --state open --search "\"$title\" in:title" \
    --json number,title --jq '.[] | select(.title == "'"$title"'") | .number' | head -1)

  if [[ -n "$existing_issue" ]]; then
    # Append comment with timestamp + report ref
    echo "[alarm_receiver] [$cls] $knd — adding comment to existing issue #$existing_issue"
    gh issue comment "$existing_issue" --repo "$REPO" --body "Drift recurrence at $TS

Report: \`$REPORT\`
Details: $details" > /dev/null 2>&1 || echo "  (failed to add comment)"
  else
    # Open new issue
    echo "[alarm_receiver] [$cls] $knd — opening new issue: $title"
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

🤖 Auto-opened by drift-detection alarm_receiver (Codex P0 follow-up).
"
    gh issue create --repo "$REPO" \
      --title "$title" \
      --label "drift-detection,$cls" \
      --body "$body" > /dev/null 2>&1 || echo "  (failed to open issue — check gh auth + repo perms)"
  fi
done

echo "[alarm_receiver] processed $findings_count findings"
