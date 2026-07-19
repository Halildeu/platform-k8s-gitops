#!/usr/bin/env bash
# scripts/promotion/scan-promotion-candidates.sh
#
# Codex Sprint B B1 — promotion candidate scanner.
# Invoked by daily scheduled GitHub Actions workflow (Pazartesi-Cuma 08:00).
# Finds release-candidates/<repo>/<sha>.json ledger entries that are
# verified-in-test but NOT yet promoted-to-prod, and opens DRAFT PRs
# for operator review (each PR bumps prod overlay digest to the verified one).
#
# Skip conditions (don't open new PR):
#   - promotion.test.verified_at is null (not test-verified yet)
#   - promotion.prod.candidate_pr already exists and is open/draft
#   - promotion.prod.promoted_at is non-null (already deployed to prod)
#
# Usage:
#   scan-promotion-candidates.sh                    # scan all repos
#   scan-promotion-candidates.sh platform-backend   # single repo
#   PROMOTION_DRY_RUN=1 scan-promotion-candidates.sh # validate, no PR creation
#
# Exit:
#   0 — scan complete (0+ candidates found, PRs opened or skipped per logic)
#   1 — at least one candidate failed to open PR (gh CLI error)
#   2 — pre-flight error (gh auth, repo access)

set -uo pipefail

REPO_FILTER="${1:-}"
PROMOTION_DRY_RUN="${PROMOTION_DRY_RUN:-0}"

REPO_ROOT="${PLATFORM_GITOPS_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
LEDGER_DIR="$REPO_ROOT/release-candidates"
GH_REPO="${GITHUB_REPO:-Halildeu/platform-k8s-gitops}"

# ------------------------------------------------------------
# Pre-flight
# ------------------------------------------------------------
if ! command -v gh > /dev/null 2>&1; then
  echo "ERR: gh CLI not installed"
  exit 2
fi

if [[ "$PROMOTION_DRY_RUN" != "1" ]]; then
  if ! gh auth status > /dev/null 2>&1; then
    echo "ERR: gh CLI not authenticated"
    exit 2
  fi

  # Label precondition (live 2026-07-16, #2295 aktivasyonu): `gh pr create --label`
  # bilinmeyen bir label'da TÜM create'i FAIL eder — "could not add label:
  # 'auto-promotion' not found" → 5/5 aday açılamadı, branch'ler orphan kaldı.
  # Label'lar REPOSITORY state'idir, kodla gelmez → idempotent ensure + fail-closed.
  #
  # Codex 019f6af2: enumeration hatası ASLA "label yok" sayılamaz (API/auth/rate-limit
  # → yanlış create → "already exists" → yanlış exit). Bounded `--limit` de eksik
  # sonuç verebilir → tam pagination.
  if ! _existing_labels=$(gh api --paginate "repos/$GH_REPO/labels?per_page=100" --jq '.[].name'); then
    echo "ERR: repository label state okunamadı (API/auth/rate-limit) — fail-closed."
    echo "     Setup: docs/operations/RUNBOOKS/RB-automation-overlay-sync.md"
    exit 2
  fi
  for _l in "auto-promotion" "env:prod" "user-approval-required"; do
    if ! printf '%s\n' "$_existing_labels" | grep -qxF "$_l"; then
      echo "[WARN] label '$_l' repo'da yok — oluşturuluyor (promotion-bot precondition)"
      if ! gh label create "$_l" --repo "$GH_REPO" --color "1D76DB" \
        --description "promotion-bot precondition — RB-automation-overlay-sync.md" > /dev/null 2>&1; then
        echo "ERR: label '$_l' yok ve oluşturulamadı; 'gh pr create --label' tüm adayları FAIL eder."
        echo "     Setup: docs/operations/RUNBOOKS/RB-automation-overlay-sync.md (ADIM 5)"
        exit 2
      fi
      # Create sonrası görünürlük doğrulaması (fail-closed).
      if ! gh api --paginate "repos/$GH_REPO/labels?per_page=100" --jq '.[].name' 2>/dev/null \
        | grep -qxF "$_l"; then
        echo "ERR: label '$_l' create sonrası doğrulanamadı — fail-closed."
        exit 2
      fi
    fi
  done
fi

if [[ ! -d "$LEDGER_DIR" ]]; then
  echo "[WARN] no release-candidates/ directory; nothing to scan"
  exit 0
fi

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

is_pr_open() {
  local pr_num="$1"
  local state
  state=$(gh pr view "$pr_num" --repo "$GH_REPO" --json state --jq .state 2>/dev/null || echo "UNKNOWN")
  [[ "$state" == "OPEN" ]]
}

# ------------------------------------------------------------
# Scan loop
# ------------------------------------------------------------
echo "=== Scanning $LEDGER_DIR for promotion candidates ==="

total=0
verified_in_test=0
already_in_prod=0
candidate_pr_exists=0
opened=0
failed=0

for repo_dir in "$LEDGER_DIR"/*/; do
  [[ ! -d "$repo_dir" ]] && continue
  repo=$(basename "$repo_dir")

  # Filter by argument if provided
  if [[ -n "$REPO_FILTER" && "$repo" != "$REPO_FILTER" ]]; then
    continue
  fi

  for ledger_file in "$repo_dir"/*.json; do
    [[ ! -f "$ledger_file" ]] && continue
    [[ "$(basename "$ledger_file")" == "README.md" ]] && continue

    total=$((total + 1))

    # Parse ledger entry
    service=$(jq -r '.service // empty' "$ledger_file")
    git_sha=$(jq -r '.git_sha // empty' "$ledger_file")
    short_sha=$(jq -r '.git_short_sha // empty' "$ledger_file")
    digest=$(jq -r '.image.digest // empty' "$ledger_file")
    test_verified=$(jq -r '.promotion.test.verified_at // empty' "$ledger_file")
    prod_promoted=$(jq -r '.promotion.prod.promoted_at // empty' "$ledger_file")
    candidate_pr=$(jq -r '.promotion.prod.candidate_pr // empty' "$ledger_file")

    # Skip: not test-verified yet
    if [[ -z "$test_verified" ]]; then
      continue
    fi
    verified_in_test=$((verified_in_test + 1))

    # Skip: already deployed to prod
    if [[ -n "$prod_promoted" ]]; then
      already_in_prod=$((already_in_prod + 1))
      continue
    fi

    # Skip: candidate PR already open
    if [[ -n "$candidate_pr" ]] && is_pr_open "$candidate_pr"; then
      candidate_pr_exists=$((candidate_pr_exists + 1))
      echo "[SKIP] $service ($short_sha): candidate PR #$candidate_pr already open"
      continue
    fi

    # Open new candidate PR
    echo "[NEW]  $service ($short_sha) test-verified at $test_verified — opening prod-candidate PR"

    if [[ "$PROMOTION_DRY_RUN" == "1" ]]; then
      echo "  [DRY] would open DRAFT PR for prod overlay digest update to $digest"
      continue
    fi

    branch="auto-promotion/prod-${repo}-${short_sha}"
    title="auto: promote ${repo}/${service} sha-${short_sha} to prod"

    cd "$REPO_ROOT" || continue

    # Branch from main
    if ! git checkout -b "$branch" main 2>/dev/null; then
      git checkout "$branch" 2>/dev/null || {
        echo "  [FAIL] cannot create/switch to branch $branch"
        failed=$((failed + 1))
        continue
      }
    fi

    # Update prod overlay kustomization.yaml — find current digest line for service
    prod_kust="$REPO_ROOT/kustomize/overlays/prod/kustomization.yaml"

    if ! grep -q "$service" "$prod_kust" 2>/dev/null; then
      echo "  [FAIL] $service not found in prod overlay (manual prod include needed first)"
      failed=$((failed + 1))
      continue
    fi

    # Use sed to swap digest. This is a heuristic — finds the line with service name
    # and replaces the digest. Needs review before merge anyway (DRAFT PR).
    sed -i.bak "s|halildeu/${repo}-${service}@sha256:[a-f0-9]\{64\}|halildeu/${repo}-${service}@${digest}|g" "$prod_kust"
    rm -f "${prod_kust}.bak"

    if git diff --quiet "$prod_kust"; then
      echo "  [WARN] no diff after digest swap — may be already current or service name mismatch"
      git checkout main 2>/dev/null
      continue
    fi

    git add "$prod_kust"

    # Build PR body with ledger evidence
    body=$(cat <<EOM
## Auto-promotion candidate

Auto-generated by \`scripts/promotion/scan-promotion-candidates.sh\` based on test-verified ledger entry:

\`\`\`
release-candidates/${repo}/${git_sha}.json
\`\`\`

## Test-verified evidence

- **Service**: \`${service}\`
- **Repo**: \`${repo}\`
- **Git SHA**: \`${short_sha}\` (full: \`${git_sha}\`)
- **Image digest**: \`${digest}\`
- **Verified at**: \`${test_verified}\`

## D29 smoke evidence

\`\`\`json
$(jq -c '.promotion.test.smoke_evidence' "$ledger_file")
\`\`\`

## Operator review checklist

- [ ] Verify test-verified ledger entry is from a recent green smoke run
- [ ] Verify no breaking schema/contract changes since the digest was built
- [ ] Verify rollback target (\`metadata.rollback_to_digest\`) is sane
- [ ] Mark PR ready for review when satisfied

## Boundary declaration (ADR-0011 §2.3)

- [ ] credential-read
- [ ] credential-write
- [ ] state-mutation (test cluster)
- [x] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [ ] none of the above

User-approval evidence: scan-promotion-candidates.sh DRAFT pattern — operator manual review + merge required (this PR mutates the prod overlay desired-state).

## Cross-AI

Implementer AI: Codex
Consultation mode: single
Consultation reason: Production desired-state promotion requires exact-head high-impact Codex review
Consultation class: high-impact
Consultation base tip: pending-exact-final-head
Consultation base: pending-exact-final-head
Consultation commit: pending-exact-final-head
Consultation scope: pending-exact-final-head
Codex receipt: pending-exact-final-head
Verdict: tracked_pending

Production desired-state promotion is not automation-exempt. The draft remains
fail-closed until a direct Codex gpt-5.6-sol xhigh, read-only, ephemeral receipt
for the exact final head replaces these placeholders.

🤖 Auto-opened by scan-promotion-candidates.sh (Codex Sprint B B1)
EOM
)

    git commit -m "auto(promote): ${repo}/${service} sha-${short_sha} to prod (test-verified ${test_verified})" 2>&1 | tail -1

    # ── PR lifecycle + branch state (Codex 019f6af2 must-fix 1/2/3) ────────────
    # Sıra: lifecycle sorgula → OPEN/CLOSED/MERGED skip → yalnız "hiç PR kaydı yok"
    # gerçek orphan → explicit expected-SHA lease ile ATOMİK replace.
    #
    # Live 2026-07-16: PR'ı açılamayan run (label precondition eksik) branch'i
    # remote'ta bıraktı; sonraki run aynı isme push edince non-fast-forward
    # reddedildi → aday KALICI açılamaz hâle geldi. Fakat naif "açık PR yoksa sil"
    # iki hata yapar: (a) API hatası "PR yok" sayılır → destructive delete;
    # (b) operator'ın KAPATTIĞI stale candidate orphan sanılıp yeniden açılır
    # (terminal karar kaybolur). Bu yüzden: fail-closed + CLOSED/MERGED terminal
    # + delete YOK, compare-and-swap lease VAR.
    if ! pr_json=$(gh pr list --repo "$GH_REPO" --head "$branch" --state all --limit 20 \
      --json number,state 2>&1); then
      echo "  [FAIL] $branch PR lifecycle sorgulanamadı — fail-closed (ref'e dokunulmadı)"
      failed=$((failed + 1))
      git checkout main 2>/dev/null
      continue
    fi
    pr_state=$(printf '%s' "$pr_json" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("ERR"); raise SystemExit(0)
if not d:
    print("NONE"); raise SystemExit(0)
states = [p.get("state", "") for p in d]
if "OPEN" in states:
    print("OPEN")
elif "MERGED" in states:
    print("MERGED")
else:
    print("CLOSED")
' 2>/dev/null || echo "ERR")

    case "$pr_state" in
      ERR)
        echo "  [FAIL] $branch PR lifecycle parse edilemedi — fail-closed"
        failed=$((failed + 1)); git checkout main 2>/dev/null; continue ;;
      OPEN)
        echo "  [SKIP] $branch için AÇIK PR var — operator review'daki branch'e dokunulmuyor"
        git checkout main 2>/dev/null; continue ;;
      MERGED)
        echo "  [SKIP] $branch MERGED PR'a sahip — ledger reconciliation gerekir, sessiz yeniden açma YOK"
        git checkout main 2>/dev/null; continue ;;
      CLOSED)
        # Codex 019f6af2: "ledger'da rearm" DEMİYORUZ — scanner ledger'da rearm
        # alanı OKUMUYOR; aynı deterministic branch için CLOSED history durdukça
        # her run SKIP eder. Capability iddiası gerçekle sınırlı tutulur.
        echo "  [SKIP] $branch PR'ı operator tarafından KAPATILMIŞ (terminal: rejected/superseded)"
        echo "         Bu scanner otomatik rearm DESTEKLEMEZ; yeniden adaylık ayrı governed"
        echo "         lifecycle + yeni branch identity gerektirir (ayrı slice)."
        git checkout main 2>/dev/null; continue ;;
    esac

    # pr_state == NONE → bu head için hiç PR kaydı yok: yeni branch veya gerçek orphan.
    ref="refs/heads/$branch"
    if ! remote_sha=$(git ls-remote --refs origin "$ref" 2>/dev/null | awk 'NR == 1 { print $1 }'); then
      echo "  [FAIL] $branch remote ref state okunamadı — fail-closed"
      failed=$((failed + 1)); git checkout main 2>/dev/null; continue
    fi
    push_ok=0
    if [[ -n "$remote_sha" ]]; then
      echo "  [WARN] orphan branch $branch (hiç PR kaydı yok) — expected-SHA lease ile tazeleniyor"
      if git push --force-with-lease="${ref}:${remote_sha}" origin "HEAD:${ref}" > /dev/null 2>&1; then
        push_ok=1
      fi
    else
      if git push --force-with-lease="${ref}:" origin "HEAD:${ref}" > /dev/null 2>&1; then
        push_ok=1
      fi
    fi
    if [[ "$push_ok" != "1" ]]; then
      echo "  [FAIL] push failed for $branch (lease reddi ya da remote hata — ref'e ZORLA yazılmadı)"
      failed=$((failed + 1))
      git checkout main 2>/dev/null
      continue
    fi

    pr_url=$(gh pr create --repo "$GH_REPO" \
      --base main \
      --head "$branch" \
      --title "$title" \
      --body "$body" \
      --draft \
      --label "auto-promotion,env:prod,user-approval-required" 2>&1 | tail -1)

    if [[ "$pr_url" =~ pull/[0-9]+ ]]; then
      pr_num=$(echo "$pr_url" | grep -oE '[0-9]+$')
      echo "  [OPEN] $pr_url"

      # Update ledger entry with candidate_pr ref
      python3 <<PYEOF
import json
from pathlib import Path
ledger = Path("$ledger_file")
data = json.loads(ledger.read_text())
data['promotion']['prod']['candidate_pr'] = $pr_num
data['promotion']['prod']['candidate_pr_status'] = 'draft'
data['audit']['last_updated_at'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
ledger.write_text(json.dumps(data, indent=2) + "\n")
PYEOF

      opened=$((opened + 1))
    else
      echo "  [FAIL] gh pr create error: $pr_url"
      failed=$((failed + 1))
    fi

    git checkout main 2>/dev/null
  done
done

echo
echo "=== Scan complete ==="
echo "total ledger entries: $total"
echo "verified-in-test:     $verified_in_test"
echo "already-in-prod:      $already_in_prod"
echo "candidate PR exists:  $candidate_pr_exists"
echo "opened new PRs:       $opened"
echo "failed:               $failed"

[[ "$failed" -gt 0 ]] && exit 1
exit 0
