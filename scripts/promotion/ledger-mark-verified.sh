#!/usr/bin/env bash
# scripts/promotion/ledger-mark-verified.sh
#
# Codex Sprint A P0 — D29 evidence pipeline. Reads a smoke-evidence JSON
# from `scripts/smoke/d29-smoke-runner.sh` and updates the matching ledger
# entry's `promotion.<env>.smoke_evidence` block + verified_at field.
#
# Auto-detects the right ledger entry by:
#   1. Reading current overlay digest for each service from kustomize render
#   2. Finding the ledger entry whose image.digest matches
#   3. Updating that entry only (one entry per service per cluster state)
#
# After update, opens a PR via gh CLI (auto-promotion bot pattern) since
# release-candidates/ is treated as gitops-managed (PR-mediated changes).
#
# Designed for staging-sw systemd integration:
#
#   ExecStart=/bin/bash d29-smoke-runner.sh test
#   ExecStartPost=/bin/bash ledger-mark-verified.sh /tmp/smoke-report-test-<ts>.json
#
# Or invoked manually for ad-hoc evidence backfill.
#
# Auth: requires gh CLI logged in (or GITHUB_TOKEN env). Read+write contents
# scope on platform-k8s-gitops repo for the auto-promotion branch.

set -euo pipefail

REPORT="${1:-/tmp/smoke-report-test-latest.json}"
[[ ! -f "$REPORT" ]] && { echo "ERR: smoke report not found: $REPORT"; exit 1; }

ENV=$(jq -r '.environment' "$REPORT")
EXIT_CODE=$(jq -r '.exit_code' "$REPORT")
TS=$(jq -r '.timestamp' "$REPORT")

# Only mark verified if smoke was GREEN
if [[ "$EXIT_CODE" -ne 0 ]]; then
  echo "[ledger-mark-verified] smoke FAILED (exit_code=$EXIT_CODE) — NOT marking ledger entries verified"
  echo "                       Operator should investigate before promotion"
  # Still useful: log the failure to a separate audit trail file
  exit 0
fi

# Defense-in-depth (Codex 019e39ea — PR-4A): only mark verified if every D29
# tier is GREEN. A SKIP/AMBER tier (e.g. Zanzibar store_id unresolved) — or a
# missing tier in a malformed report — must NOT be carried into the ledger as
# D29-verified even if exit_code somehow reads 0. Explicit required-key check.
NON_GREEN=$(jq -r '
  .tiers as $t
  | ["d29_up", "d29_functional", "d29_zanzibar"]
  | map(
      . as $k
      | ($t[$k].status // "MISSING") as $s
      | select($s != "GREEN")
      | "\($k)=\($s)"
    )
  | join(", ")
' "$REPORT")
if [[ -n "$NON_GREEN" ]]; then
  echo "[ledger-mark-verified] non-GREEN D29 tier(s): $NON_GREEN — NOT marking ledger entries verified"
  echo "                       Operator should investigate before promotion"
  exit 0
fi

REPO_ROOT="${PLATFORM_GITOPS_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
OVERLAY="$REPO_ROOT/kustomize/overlays/${ENV}"
LEDGER_DIR="$REPO_ROOT/release-candidates"
GH_REPO="${GITHUB_REPO:-Halildeu/platform-k8s-gitops}"

[[ ! -d "$OVERLAY" ]] && { echo "ERR: overlay not found: $OVERLAY"; exit 1; }
[[ ! -d "$LEDGER_DIR" ]] && { echo "ERR: ledger dir not found: $LEDGER_DIR"; exit 1; }

echo "[ledger-mark-verified] env=$ENV report=$REPORT"

# Render overlay → list (service, digest) pairs
RENDERED=$(kubectl kustomize "$OVERLAY" 2>/dev/null | python3 -c "
import sys, yaml, re
docs = list(yaml.safe_load_all(sys.stdin))
seen = set()
for d in docs:
    if not isinstance(d, dict): continue
    if d.get('kind') not in ('Deployment', 'StatefulSet'): continue
    svc = d.get('metadata', {}).get('labels', {}).get('app.kubernetes.io/name')
    if not svc: continue
    for c in d.get('spec', {}).get('template', {}).get('spec', {}).get('containers', []):
        img = c.get('image', '')
        m = re.match(r'^(?P<reg>[^/]+)/(?P<path>[^@]+)@(?P<dig>sha256:[a-f0-9]+)\$', img)
        if m:
            key = (svc, m.group('dig'))
            if key not in seen:
                seen.add(key)
                print(f\"{svc} {m.group('dig')}\")
")

if [[ -z "$RENDERED" ]]; then
  echo "[ledger-mark-verified] no service+digest pairs in render; nothing to mark"
  exit 0
fi

# Auto-create branch for ledger updates
TS_FILE=$(date -u +%Y%m%dT%H%M%SZ)
BRANCH="auto-verified/${ENV}-${TS_FILE}"
UPDATED_FILES=()

cd "$REPO_ROOT" || exit 1

# Iterate (service, digest) pairs and find matching ledger entries
while IFS=' ' read -r svc digest; do
  [[ -z "$svc" || -z "$digest" ]] && continue

  # Find ledger entry for this digest (search by image.digest field)
  match=$(grep -l "\"$digest\"" "$LEDGER_DIR"/*/*.json 2>/dev/null | head -1 || true)

  if [[ -z "$match" ]]; then
    echo "  [SKIP] $svc digest=$digest — no ledger entry yet (CI hasn't generated one)"
    continue
  fi

  # Verify ledger entry has matching service name
  ledger_svc=$(jq -r '.service' "$match")
  if [[ "$ledger_svc" != "$svc" ]]; then
    echo "  [WARN] ledger $match has service='$ledger_svc' but render service='$svc' — skipping"
    continue
  fi

  # Check if already verified for this env
  already_verified=$(jq -r ".promotion.$ENV.verified_at // empty" "$match")
  if [[ -n "$already_verified" ]]; then
    echo "  [SKIP] $svc already verified for $ENV at $already_verified"
    continue
  fi

  echo "  [MARK] $svc → $match (env=$ENV)"

  # Patch the ledger entry with smoke evidence
  python3 <<PYEOF
import json
from pathlib import Path

ledger_path = Path("$match")
report_path = Path("$REPORT")

ledger = json.loads(ledger_path.read_text())
report = json.loads(report_path.read_text())

# Update promotion.<env> block
env_block = ledger['promotion']['$ENV']
env_block['smoke_evidence'] = report['tiers']
env_block['verified_at'] = report['timestamp']

# Audit
ledger['audit']['last_updated_at'] = report['timestamp']

ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
print(f"    updated {ledger_path}")
PYEOF

  UPDATED_FILES+=("$match")
done <<< "$RENDERED"

if [[ ${#UPDATED_FILES[@]} -eq 0 ]]; then
  echo "[ledger-mark-verified] no ledger entries updated (no matches or all already verified)"
  exit 0
fi

echo
echo "[ledger-mark-verified] ${#UPDATED_FILES[@]} ledger entries updated"
for f in "${UPDATED_FILES[@]}"; do
  echo "  - $f"
done

# Commit + push + open PR
if [[ "${LEDGER_DRY_RUN:-0}" == "1" ]]; then
  echo "[ledger-mark-verified] LEDGER_DRY_RUN=1 — skipping git push + PR"
  exit 0
fi

git checkout -b "$BRANCH" 2>&1 | tail -2
for f in "${UPDATED_FILES[@]}"; do
  git add "$f"
done

git commit -m "auto: mark $ENV-verified — D29 smoke GREEN at $TS

Smoke report: $REPORT
Updated ledger entries:
$(printf '  - %s\n' "${UPDATED_FILES[@]}")

🤖 Auto-generated by ledger-mark-verified.sh (Codex P0 #2 / Sprint A Item 3)
" 2>&1 | tail -3

git push origin "$BRANCH" 2>&1 | tail -3

# Open PR via gh
gh pr create --repo "$GH_REPO" \
  --base main \
  --head "$BRANCH" \
  --title "auto(ledger): $ENV-verified after D29 smoke GREEN ($TS)" \
  --body "Auto-generated by smoke gate after D29 GREEN on **$ENV** cluster at $TS.

## Smoke evidence

\`\`\`
$(jq -c '.tiers' "$REPORT")
\`\`\`

## Ledger entries updated

$(printf -- '- %s\n' "${UPDATED_FILES[@]}")

## Auto-merge

This PR is safe to auto-merge after CI ledger-validate gate passes — content
is generated, schema-validated, and represents observable cluster state.

## Boundary declaration (ADR-0011 §2.3)

- [ ] credential-read
- [ ] credential-write
- [ ] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [x] none of the above

Ledger evidence update only — patches release-candidates/<repo>/<sha>.json
with observed D29 smoke evidence; no cluster mutation, no credential I/O.

## Cross-AI

Automation source: scripts/promotion/ledger-mark-verified.sh
Cross-AI exempt reason: Machine-generated D29-evidence ledger PR; no AI peer-review claim is made (issue 827 automation-PR governance contract).
Automation evidence: D29 smoke report $REPORT (GREEN at $TS)
" \
  --label "auto-promotion,smoke-verified,env:$ENV" 2>&1 || echo "[WARN] PR creation failed (may already exist or auth missing)"

echo "[ledger-mark-verified] DONE"
