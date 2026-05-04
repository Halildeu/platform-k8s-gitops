#!/usr/bin/env bash
# scripts/promotion/ledger-close-prod.sh
#
# Codex Sprint B B1 — promotion ledger closer for prod-side.
# Invoked after ArgoCD prod sync completes (post-sync webhook OR scheduled
# poll). Walks release-candidates/<repo>/<sha>.json entries that have
# promotion.prod.promoted_by_pr (PR was merged) but NO promotion.prod.promoted_at
# (sync confirmation pending), and updates the ledger with prod sync evidence.
#
# Logic:
#   1. Read live prod cluster pod imageIDs
#   2. For each ledger entry with non-null promoted_by_pr:
#      - Check if image.digest matches any pod imageID in prod
#      - If match: update promoted_at + argocd_revision (best-effort) + audit
#      - If no match yet: skip (next run will catch it)
#
# Designed for staging-sw scheduled execution (every 15min, after smoke-prod):
#
#   ExecStartPost=/bin/bash -c 'bash ledger-close-prod.sh'
#
# Or manual invocation when promotion bot updates need to be flushed.
#
# Usage:
#   ledger-close-prod.sh                     # close all open candidates
#   ledger-close-prod.sh --dry-run           # validate, no writes
#
# Exit:
#   0 — completed (0+ entries closed)
#   1 — at least one entry failed to update (file or git error)
#   2 — pre-flight error (kubectl unreachable, no ledger dir)

set -uo pipefail

DRY_RUN="${1:-}"
[[ "$DRY_RUN" == "--dry-run" ]] && DRY_RUN=1 || DRY_RUN=0

REPO_ROOT="${PLATFORM_GITOPS_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
LEDGER_DIR="$REPO_ROOT/release-candidates"
GH_REPO="${GITHUB_REPO:-Halildeu/platform-k8s-gitops}"

PROD_CTX="${PROD_CTX:-k3d-prod}"
PROD_NS="${PROD_NS:-platform-prod}"

if ! kubectl --context "$PROD_CTX" cluster-info > /dev/null 2>&1; then
  echo "ERR: cannot reach prod cluster context=$PROD_CTX"
  exit 2
fi

if [[ ! -d "$LEDGER_DIR" ]]; then
  echo "[WARN] no release-candidates/ directory; nothing to close"
  exit 0
fi

# ------------------------------------------------------------
# Capture live prod pod imageIDs
# ------------------------------------------------------------
echo "=== Reading prod cluster pod imageIDs ==="
LIVE_DIGESTS=$(kubectl --context "$PROD_CTX" -n "$PROD_NS" get pods \
  -o jsonpath='{range .items[*].status.containerStatuses[*]}{.imageID}{"\n"}{end}' 2>/dev/null \
  | grep -oE 'sha256:[a-f0-9]{64}' | sort -u)

if [[ -z "$LIVE_DIGESTS" ]]; then
  echo "[WARN] no pod imageIDs found in $PROD_NS"
  exit 0
fi

live_count=$(echo "$LIVE_DIGESTS" | wc -l | tr -d ' ')
echo "[INFO] $live_count unique pod imageID digests in prod cluster"

# ------------------------------------------------------------
# Try to capture ArgoCD revision (best-effort)
# ------------------------------------------------------------
ARGOCD_REVISION=""
if kubectl --context "$PROD_CTX" -n argocd get application platform-prod > /dev/null 2>&1; then
  ARGOCD_REVISION=$(kubectl --context "$PROD_CTX" -n argocd get application platform-prod \
    -o jsonpath='{.status.sync.revision}' 2>/dev/null | head -c 12 || echo "")
fi

# ------------------------------------------------------------
# Walk ledger entries
# ------------------------------------------------------------
echo
echo "=== Scanning ledger entries for prod-pending closure ==="

total=0
to_close=0
closed=0
failed=0
not_yet_synced=0

for repo_dir in "$LEDGER_DIR"/*/; do
  [[ ! -d "$repo_dir" ]] && continue

  for ledger_file in "$repo_dir"/*.json; do
    [[ ! -f "$ledger_file" ]] && continue
    [[ "$(basename "$ledger_file")" == "README.md" ]] && continue

    total=$((total + 1))

    promoted_by_pr=$(jq -r '.promotion.prod.promoted_by_pr // empty' "$ledger_file")
    promoted_at=$(jq -r '.promotion.prod.promoted_at // empty' "$ledger_file")
    digest=$(jq -r '.image.digest // empty' "$ledger_file")
    service=$(jq -r '.service // empty' "$ledger_file")
    short_sha=$(jq -r '.git_short_sha // empty' "$ledger_file")

    # Skip: not promoted-by-PR yet (operator hasn't merged candidate PR)
    [[ -z "$promoted_by_pr" ]] && continue
    # Skip: already closed
    [[ -n "$promoted_at" ]] && continue

    to_close=$((to_close + 1))

    # Check if digest is live in prod cluster
    if ! echo "$LIVE_DIGESTS" | grep -qx "$digest"; then
      echo "[PEND] $service ($short_sha): PR #$promoted_by_pr merged but digest not yet running in prod"
      not_yet_synced=$((not_yet_synced + 1))
      continue
    fi

    # Live in prod — close ledger entry
    NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    echo "[CLOSE] $service ($short_sha): digest live in prod, closing ledger"

    if [[ "$DRY_RUN" == "1" ]]; then
      echo "  [DRY] would: update promotion.prod.promoted_at=$NOW, argocd_revision=$ARGOCD_REVISION"
      continue
    fi

    python3 <<PYEOF
import json
from pathlib import Path
ledger = Path("$ledger_file")
data = json.loads(ledger.read_text())
data['promotion']['prod']['promoted_at'] = '$NOW'
if '$ARGOCD_REVISION':
    data['promotion']['prod']['argocd_revision'] = '$ARGOCD_REVISION'
data['audit']['last_updated_at'] = '$NOW'

# Update candidate_pr_status if it was draft → merged inferred from PR being merged
if data['promotion']['prod'].get('candidate_pr'):
    data['promotion']['prod']['candidate_pr_status'] = 'merged'

ledger.write_text(json.dumps(data, indent=2) + "\n")
print(f"    updated $ledger_file")
PYEOF

    if [[ $? -eq 0 ]]; then
      closed=$((closed + 1))
    else
      failed=$((failed + 1))
    fi
  done
done

echo
echo "=== Close summary ==="
echo "total ledger entries:    $total"
echo "to-close (PR merged):    $to_close"
echo "closed (digest in prod): $closed"
echo "pending (sync lag):      $not_yet_synced"
echo "failed:                  $failed"

if [[ "$closed" -gt 0 && "$DRY_RUN" != "1" ]]; then
  echo
  echo "Note: ledger entries updated locally. Operator should:"
  echo "  - Open auto-close PR via existing ledger-mark-verified.sh pattern, OR"
  echo "  - Commit + push directly if running on staging-sw with write access"
  echo
  echo "Suggested commit:"
  echo "  git add release-candidates/"
  echo "  git commit -m 'auto(close): mark $closed prod-deployed ledger entries'"
fi

[[ "$failed" -gt 0 ]] && exit 1
exit 0
