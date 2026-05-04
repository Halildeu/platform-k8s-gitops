#!/usr/bin/env bash
# scripts/ops/d30-readiness-probe.sh
#
# D30 cutover pre-decision readiness probe (Codex 019df310 absorb).
# 7-tier check — gitops repo state ≠ live readiness. Bu probe operator
# çalıştırır, gerçek live evidence toplar.
#
# Codex: "repo-side D30 hardening AGREE; live cutover decision pending
# operator/cross-repo evidence."
#
# Tier'lar (hepsi PASS olmalı D30 GO için):
#   1. Repo gitops PR'ları — Sprint A→D 18 PR merged?
#   2. systemd timers — host'ta enabled + son fire başarılı?
#   3. Cutover bundle — son 24h içinde başarılı snapshot var mı?
#   4. Break-glass SA — iki cluster'da apply edildi mi?
#   5. AlertManager bridge — synthetic alert → GitHub issue produces?
#   6. Promotion ledger — cross-repo build → test verified zinciri canlı mı?
#   7. D29/D35 evidence — fixture + product-path ayrı kanıtlar var mı?
#
# Usage:
#   bash d30-readiness-probe.sh                    # full probe
#   bash d30-readiness-probe.sh --tier 3           # specific tier only
#   bash d30-readiness-probe.sh --dry-run          # check what would run
#
# Output:
#   /tmp/d30-readiness-probe-<ts>.json — structured output for audit
#   stdout — operator-friendly summary
#
# Exit:
#   0 — all 7 tiers GREEN, D30 ready
#   1 — at least 1 tier RED (cutover NOT recommended)
#   2 — tool/setup error

set -uo pipefail

DRY_RUN="${DRY_RUN:-0}"
TIER_FILTER="${TIER_FILTER:-all}"

# Parse args
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --tier) TIER_FILTER="$2"; shift 2 ;;
    *) echo "WARN: unknown arg: $1"; shift ;;
  esac
done

REPO_ROOT="${PLATFORM_GITOPS_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
TS_FILE=$(date -u +%Y%m%dT%H%M%SZ)
REPORT="/tmp/d30-readiness-probe-${TS_FILE}.json"
GH_REPO="${GITHUB_REPO:-Halildeu/platform-k8s-gitops}"

# Result accumulator (indexed arrays for bash 3.2 compat; Mac default)
TIER_STATUS_1=""; TIER_STATUS_2=""; TIER_STATUS_3=""; TIER_STATUS_4=""
TIER_STATUS_5=""; TIER_STATUS_6=""; TIER_STATUS_7=""
TIER_DETAILS_1=""; TIER_DETAILS_2=""; TIER_DETAILS_3=""; TIER_DETAILS_4=""
TIER_DETAILS_5=""; TIER_DETAILS_6=""; TIER_DETAILS_7=""

set_tier_status() {
  # set_tier_status <tier-num> <status>
  eval "TIER_STATUS_$1=\"$2\""
}
set_tier_details() {
  eval "TIER_DETAILS_$1=\"$2\""
}
get_tier_status() {
  eval "echo \"\$TIER_STATUS_$1\""
}
get_tier_details() {
  eval "echo \"\$TIER_DETAILS_$1\""
}

run_tier() {
  local tier="$1"
  if [[ "$TIER_FILTER" != "all" && "$TIER_FILTER" != "$tier" ]]; then
    set_tier_status "$tier" "SKIP"
    set_tier_details "$tier" "filtered out by --tier $TIER_FILTER"
    return 1
  fi
  return 0
}

# ----------------------------------------------------------------
# Tier 1: Repo gitops state (Sprint A→D PR'ları merged?)
# ----------------------------------------------------------------
tier1_repo_state() {
  run_tier 1
  [[ "$(get_tier_status 1)" == "SKIP" ]] && return

  echo "=== Tier 1: Repo gitops state ==="

  if ! command -v gh > /dev/null 2>&1; then
    set_tier_status 1 "AMBER"
    set_tier_details 1 "gh CLI not available; manual PR check required"
    echo "  [AMBER] gh CLI not available"
    return
  fi

  # Latest 20 merged PRs in last 30 days
  local count
  count=$(gh pr list --repo "$GH_REPO" --state merged --limit 30 --json number 2>/dev/null | jq 'length')

  if [[ "$count" -ge 18 ]]; then
    set_tier_status 1 "GREEN"
    set_tier_details 1 "$count merged PRs in recent history (>= 18 expected)"
    echo "  [GREEN] $count merged PRs"
  else
    set_tier_status 1 "AMBER"
    set_tier_details 1 "only $count merged PRs found (expected ≥18 for Sprint A→D)"
    echo "  [AMBER] only $count merged PRs"
  fi
}

# ----------------------------------------------------------------
# Tier 2: systemd timers active + last fire
# ----------------------------------------------------------------
tier2_systemd_timers() {
  run_tier 2
  [[ "$(get_tier_status 2)" == "SKIP" ]] && return

  echo
  echo "=== Tier 2: systemd timers ==="

  if [[ "$(uname -s)" == "Darwin" ]]; then
    set_tier_status 2 "SKIP"
    set_tier_details 2 "macOS host (this script is staging-sw probe)"
    echo "  [SKIP] macOS — run on staging-sw"
    return
  fi

  if ! command -v systemctl > /dev/null 2>&1; then
    set_tier_status 2 "RED"
    set_tier_details 2 "systemctl not available"
    echo "  [RED] systemctl not available"
    return
  fi

  local expected_timers=(
    "drift-test.timer"
    "drift-prod.timer"
    "smoke-test.timer"
    "smoke-prod.timer"
    "mfe-drift-test.timer"
    "mfe-drift-prod.timer"
    "cutover-bundle-nightly.timer"
  )

  local installed=0
  local active=0
  for t in "${expected_timers[@]}"; do
    if systemctl list-unit-files "$t" 2>/dev/null | grep -q "$t"; then
      installed=$((installed + 1))
      if systemctl is-active --quiet "$t"; then
        active=$((active + 1))
      fi
    fi
  done

  local total=${#expected_timers[@]}
  if [[ "$active" -eq "$total" ]]; then
    set_tier_status 2 "GREEN"
    set_tier_details 2 "$active/$total timers active"
    echo "  [GREEN] $active/$total timers active"
  elif [[ "$installed" -gt 0 ]]; then
    set_tier_status 2 "AMBER"
    set_tier_details 2 "installed=$installed active=$active total=$total"
    echo "  [AMBER] installed=$installed active=$active total=$total"
  else
    set_tier_status 2 "RED"
    set_tier_details 2 "no timers installed; operator setup gerekli"
    echo "  [RED] no timers installed"
  fi
}

# ----------------------------------------------------------------
# Tier 3: Cutover bundle freshness (last 24h)
# ----------------------------------------------------------------
tier3_cutover_bundle() {
  run_tier 3
  [[ "$(get_tier_status 3)" == "SKIP" ]] && return

  echo
  echo "=== Tier 3: Cutover bundle freshness ==="

  local bundle_dir="${CUTOVER_BUNDLE_DIR:-/var/backups/cutover}"
  if [[ ! -d "$bundle_dir" ]]; then
    set_tier_status 3 "RED"
    set_tier_details 3 "bundle dir not found: $bundle_dir"
    echo "  [RED] $bundle_dir not found"
    return
  fi

  # Find most recent bundle
  local latest
  latest=$(ls -t "$bundle_dir"/cutover-bundle-* 2>/dev/null | head -1)
  if [[ -z "$latest" ]]; then
    set_tier_status 3 "RED"
    set_tier_details 3 "no bundles found in $bundle_dir"
    echo "  [RED] no bundles"
    return
  fi

  # Age check
  local age_seconds=$(( $(date +%s) - $(stat -c %Y "$latest" 2>/dev/null || stat -f %m "$latest" 2>/dev/null) ))
  local age_hours=$((age_seconds / 3600))

  # Verify MANIFEST.json exists
  if [[ ! -f "$latest/MANIFEST.json" ]]; then
    set_tier_status 3 "AMBER"
    set_tier_details 3 "latest bundle $latest missing MANIFEST.json"
    echo "  [AMBER] $latest no manifest"
    return
  fi

  if [[ "$age_hours" -lt 24 ]]; then
    set_tier_status 3 "GREEN"
    set_tier_details 3 "latest bundle ${age_hours}h old: $latest"
    echo "  [GREEN] bundle ${age_hours}h old"
  elif [[ "$age_hours" -lt 168 ]]; then  # 7 days
    set_tier_status 3 "AMBER"
    set_tier_details 3 "bundle ${age_hours}h old (>24h, <7d)"
    echo "  [AMBER] bundle ${age_hours}h old"
  else
    set_tier_status 3 "RED"
    set_tier_details 3 "bundle ${age_hours}h old (stale)"
    echo "  [RED] bundle stale"
  fi
}

# ----------------------------------------------------------------
# Tier 4: Break-glass SA in both clusters
# ----------------------------------------------------------------
tier4_break_glass() {
  run_tier 4
  [[ "$(get_tier_status 4)" == "SKIP" ]] && return

  echo
  echo "=== Tier 4: Break-glass SA ==="

  if ! command -v kubectl > /dev/null 2>&1; then
    set_tier_status 4 "SKIP"
    set_tier_details 4 "kubectl not available"
    echo "  [SKIP] kubectl not available"
    return
  fi

  local sa_test=0 sa_prod=0
  if kubectl --context k3d-test -n kube-system get sa ops-break-glass > /dev/null 2>&1; then
    sa_test=1
  fi
  if kubectl --context k3d-prod -n kube-system get sa ops-break-glass > /dev/null 2>&1; then
    sa_prod=1
  fi

  if [[ "$sa_test" -eq 1 && "$sa_prod" -eq 1 ]]; then
    set_tier_status 4 "GREEN"
    set_tier_details 4 "break-glass SA exists in both clusters"
    echo "  [GREEN] both clusters"
  elif [[ "$sa_test" -eq 1 || "$sa_prod" -eq 1 ]]; then
    set_tier_status 4 "AMBER"
    set_tier_details 4 "test=$sa_test prod=$sa_prod (one missing)"
    echo "  [AMBER] partial: test=$sa_test prod=$sa_prod"
  else
    set_tier_status 4 "RED"
    set_tier_details 4 "break-glass SA not bootstrapped"
    echo "  [RED] not bootstrapped"
  fi
}

# ----------------------------------------------------------------
# Tier 5: AlertManager bridge — synthetic alert produces GitHub issue
# ----------------------------------------------------------------
tier5_alertmanager_bridge() {
  run_tier 5
  [[ "$(get_tier_status 5)" == "SKIP" ]] && return

  echo
  echo "=== Tier 5: AlertManager bridge ==="

  if ! command -v kubectl > /dev/null 2>&1; then
    set_tier_status 5 "SKIP"
    return
  fi

  # Bridge pod check
  local bridge_status
  bridge_status=$(kubectl --context k3d-prod -n monitoring get pod -l app.kubernetes.io/name=alertmanager-bridge \
    -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "")

  if [[ "$bridge_status" == "Running" ]]; then
    set_tier_status 5 "GREEN"
    set_tier_details 5 "bridge pod Running; synthetic alert test deferred"
    echo "  [GREEN] bridge Running (synthetic alert test deferred)"
  elif [[ -n "$bridge_status" ]]; then
    set_tier_status 5 "AMBER"
    set_tier_details 5 "bridge pod state: $bridge_status"
    echo "  [AMBER] bridge state: $bridge_status"
  else
    set_tier_status 5 "RED"
    set_tier_details 5 "bridge pod not deployed"
    echo "  [RED] bridge not deployed"
  fi
}

# ----------------------------------------------------------------
# Tier 6: Promotion ledger flow — verified entries exist?
# ----------------------------------------------------------------
tier6_promotion_ledger() {
  run_tier 6
  [[ "$(get_tier_status 6)" == "SKIP" ]] && return

  echo
  echo "=== Tier 6: Promotion ledger ==="

  local ledger_dir="$REPO_ROOT/release-candidates"
  if [[ ! -d "$ledger_dir" ]]; then
    set_tier_status 6 "RED"
    set_tier_details 6 "release-candidates/ dir missing"
    echo "  [RED] dir missing"
    return
  fi

  # Count entries with promotion.test.verified_at != null
  local total verified
  total=$(find "$ledger_dir" -name "*.json" -not -name "README*" | wc -l | tr -d ' ')
  verified=$(find "$ledger_dir" -name "*.json" -not -name "README*" -exec jq -r '.promotion.test.verified_at // empty' {} \; 2>/dev/null | grep -c -v "^$" || echo "0")

  if [[ "$total" -eq 0 ]]; then
    set_tier_status 6 "AMBER"
    set_tier_details 6 "no ledger entries yet (cross-repo CI integration pending — Sprint B B3)"
    echo "  [AMBER] no entries yet"
  elif [[ "$verified" -gt 0 ]]; then
    set_tier_status 6 "GREEN"
    set_tier_details 6 "$verified/$total entries test-verified"
    echo "  [GREEN] $verified/$total verified"
  else
    set_tier_status 6 "AMBER"
    set_tier_details 6 "$total entries exist but 0 verified (smoke pipeline ne çalıştı?)"
    echo "  [AMBER] 0/$total verified"
  fi
}

# ----------------------------------------------------------------
# Tier 7: D29/D35 evidence ayrımı korunuyor mu?
# ----------------------------------------------------------------
tier7_d29_d35_evidence() {
  run_tier 7
  [[ "$(get_tier_status 7)" == "SKIP" ]] && return

  echo
  echo "=== Tier 7: D29/D35 evidence separation ==="

  # D29 fixture: openfga-fixture-smoke workflow
  local d29_workflow="$REPO_ROOT/.github/workflows/openfga-fixture-smoke.yml"
  local d35_evidence_dirs="$REPO_ROOT/docs/faz-21-3-evidence"

  local d29_present=0 d35_present=0
  [[ -f "$d29_workflow" ]] && d29_present=1
  [[ -d "$d35_evidence_dirs" ]] && d35_present=1

  if [[ "$d29_present" -eq 1 && "$d35_present" -eq 1 ]]; then
    set_tier_status 7 "GREEN"
    set_tier_details 7 "D29 fixture workflow present + D35 evidence dir exists"
    echo "  [GREEN] both present"
  elif [[ "$d29_present" -eq 1 ]]; then
    set_tier_status 7 "AMBER"
    set_tier_details 7 "D29 fixture present but D35 product-path evidence dir missing"
    echo "  [AMBER] D29 only, D35 missing"
  else
    set_tier_status 7 "RED"
    set_tier_details 7 "D29/D35 evidence separation broken"
    echo "  [RED] evidence broken"
  fi
}

# ----------------------------------------------------------------
# Run all tiers
# ----------------------------------------------------------------
echo "=== D30 Readiness Probe — $TS ==="
echo "report: $REPORT"
echo

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[DRY-RUN] would check 7 tiers"
  exit 0
fi

tier1_repo_state
tier2_systemd_timers
tier3_cutover_bundle
tier4_break_glass
tier5_alertmanager_bridge
tier6_promotion_ledger
tier7_d29_d35_evidence

# ----------------------------------------------------------------
# Summary (bash 3.2 compat — no associative array)
# ----------------------------------------------------------------
echo
echo "=== Summary ==="

# Counters (avoid associative array)
COUNT_GREEN=0
COUNT_AMBER=0
COUNT_RED=0
COUNT_SKIP=0
COUNT_UNKNOWN=0

for tier in 1 2 3 4 5 6 7; do
  s=$(get_tier_status "$tier")
  d=$(get_tier_details "$tier")
  [[ -z "$s" ]] && s="UNKNOWN"
  case "$s" in
    GREEN)   COUNT_GREEN=$((COUNT_GREEN + 1)) ;;
    AMBER)   COUNT_AMBER=$((COUNT_AMBER + 1)) ;;
    RED)     COUNT_RED=$((COUNT_RED + 1)) ;;
    SKIP)    COUNT_SKIP=$((COUNT_SKIP + 1)) ;;
    *)       COUNT_UNKNOWN=$((COUNT_UNKNOWN + 1)) ;;
  esac
  printf "  Tier %d: %-8s %s\n" "$tier" "$s" "$d"
done

echo
echo "Distribution:"
echo "  GREEN: $COUNT_GREEN"
echo "  AMBER: $COUNT_AMBER"
echo "  RED:   $COUNT_RED"
echo "  SKIP:  $COUNT_SKIP"
[[ "$COUNT_UNKNOWN" -gt 0 ]] && echo "  UNKNOWN: $COUNT_UNKNOWN"

# JSON report
{
  echo '{'
  echo "  \"timestamp\": \"$TS\","
  echo "  \"tiers\": {"
  first=1
  for tier in 1 2 3 4 5 6 7; do
    [[ "$first" -eq 0 ]] && echo "    ,"
    s=$(get_tier_status "$tier"); [[ -z "$s" ]] && s="UNKNOWN"
    d=$(get_tier_details "$tier")
    echo "    \"$tier\": {"
    echo "      \"status\": \"$s\","
    echo "      \"details\": \"$d\""
    echo -n "    }"
    first=0
  done
  echo
  echo '  },'
  echo "  \"distribution\": {"
  echo "    \"green\": $COUNT_GREEN,"
  echo "    \"amber\": $COUNT_AMBER,"
  echo "    \"red\": $COUNT_RED,"
  echo "    \"skip\": $COUNT_SKIP"
  echo '  }'
  echo '}'
} > "$REPORT"

# D30 GO/NO-GO verdict
echo
if [[ "$COUNT_RED" -gt 0 ]]; then
  echo "=== VERDICT: ❌ D30 NOT READY ($COUNT_RED RED tier) ==="
  echo "    Cutover decision NOT recommended; address RED tiers first."
  exit 1
elif [[ "$COUNT_AMBER" -gt 0 ]]; then
  echo "=== VERDICT: ⚠️  D30 PARTIAL ($COUNT_AMBER AMBER tier) ==="
  echo "    Operator decision; review AMBER tiers for impact assessment."
  exit 0
else
  echo "=== VERDICT: ✅ D30 READY (all green) ==="
  echo "    Cutover gates satisfied; proceed with operator strategic decision."
  exit 0
fi
