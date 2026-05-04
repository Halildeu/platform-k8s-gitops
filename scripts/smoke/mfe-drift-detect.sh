#!/usr/bin/env bash
# scripts/smoke/mfe-drift-detect.sh
#
# MFE Remote Drift Detector — wrapper around mfe-remote-smoke.sh that produces
# JSON drift-report compatible with alarm_receiver.sh pipeline.
#
# Codex Sprint A follow-up — frontend regression için drift detection eklendi.
# Mevcut ci-live-smoke.yml workflow GitHub-hosted runner network limitation
# nedeniyle çalışmaz; bu wrapper systemd timer ile staging-sw'de host
# execution yapar (drift-detection pattern ile aynı).
#
# Output:
#   /tmp/drift-report-mfe-<env>-<ts>.json — alarm_receiver.sh pattern
#
# Usage:
#   bash mfe-drift-detect.sh test    # → smoke testai.acik.com + JSON report
#   bash mfe-drift-detect.sh prod    # → smoke ai.acik.com + JSON report
#   bash mfe-drift-detect.sh both
#
# systemd integration:
#   ExecStart=/bin/bash mfe-drift-detect.sh test
#   ExecStartPost=/bin/bash -c 'latest=$(ls -t /tmp/drift-report-mfe-test-*.json | head -1); \
#                                bash alarm_receiver.sh "$latest"'
#
# Exit:
#   0 — clean (all MFE remotes 200)
#   1 — drift detected (at least 1 endpoint not 200) → P2 alarm

set -uo pipefail

ENV="${1:-test}"
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SMOKE_SCRIPT="$SCRIPT_DIR/mfe-remote-smoke.sh"

[[ ! -x "$SMOKE_SCRIPT" ]] && { echo "ERR: $SMOKE_SCRIPT not executable"; exit 1; }

# Map env to smoke target
case "$ENV" in
  test) TARGET="test"; HOST="testai.acik.com" ;;
  prod) TARGET="prod"; HOST="ai.acik.com" ;;
  both) TARGET="both"; HOST="testai.acik.com,ai.acik.com" ;;
  *) echo "ERR: unknown env: $ENV"; exit 1 ;;
esac

TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
TS_FILE=$(date -u +%Y%m%dT%H%M%SZ)
REPORT="/tmp/drift-report-mfe-${ENV}-${TS_FILE}.json"

echo "=== MFE Drift Detector — env=$ENV host=$HOST ==="

# Run smoke + capture output + exit code
SMOKE_OUTPUT=$(bash "$SMOKE_SCRIPT" "$TARGET" 2>&1)
SMOKE_RC=$?

# Parse smoke output for findings (failed endpoints)
# Format: "  /admin/users          → 404" lines are failures
FAILED_ENDPOINTS=$(echo "$SMOKE_OUTPUT" | grep -E '→ [^2]00$|→ 0$|FAIL' | head -20)
TOTAL_FAIL=$(echo "$SMOKE_OUTPUT" | grep -oE 'FAIL \([0-9]+ endpoint\)' | grep -oE '[0-9]+' | head -1)
[[ -z "$TOTAL_FAIL" ]] && TOTAL_FAIL=0

# Build findings JSON array
FINDINGS_JSON=""
if [[ "$SMOKE_RC" -eq 0 ]]; then
  FINDINGS_JSON='[{"class":"OK","kind":"mfe_remote","message":"All 7 MFE remotes + shell reachable"}]'
  EXIT_CLASS=0
else
  # P2: deploy regression, frontend module federation kırık
  CLASS="P2"

  # Build per-endpoint finding
  FINDINGS=$(echo "$FAILED_ENDPOINTS" | head -10 | while IFS= read -r line; do
    # Skip empty / non-data lines
    [[ -z "$line" ]] && continue
    [[ "$line" =~ "FAIL " ]] && continue

    # Extract endpoint + status
    EP=$(echo "$line" | awk '{print $1}')
    STATUS=$(echo "$line" | grep -oE '[0-9]+$' | head -1)
    [[ -z "$EP" || -z "$STATUS" ]] && continue

    msg="MFE endpoint $EP returned HTTP $STATUS (expected 200) on $HOST"
    detail="Module Federation regression — possible new frontend deploy missing remote OR remoteEntry.js path drift"

    jq -nc --arg cls "$CLASS" --arg knd "mfe_remote" --arg msg "$msg" --arg det "$detail" \
      '{class:$cls, kind:$knd, message:$msg, details:$det}'
  done | jq -s '.')

  # Wrap in array; if empty (failed but no parseable lines), single fallback finding
  if [[ -z "$FINDINGS" || "$FINDINGS" == "[]" ]]; then
    FINDINGS_JSON=$(jq -nc \
      --arg cls "$CLASS" --arg knd "mfe_remote" \
      --arg msg "MFE smoke FAIL — $TOTAL_FAIL endpoint failed on $HOST" \
      '[{class:$cls, kind:$knd, message:$msg, details:"see /var/log/platform-mfe-drift.log"}]')
  else
    FINDINGS_JSON="$FINDINGS"
  fi
  EXIT_CLASS=1
fi

# Emit JSON report
cat > "$REPORT" <<EOF
{
  "schema_version": "drift-report-v1",
  "environment": "$ENV",
  "host": "$HOST",
  "timestamp": "$TS",
  "exit_code": $EXIT_CLASS,
  "kind_focus": "mfe_remote",
  "smoke_summary": {
    "total_failures": $TOTAL_FAIL,
    "smoke_exit_code": $SMOKE_RC
  },
  "findings": $FINDINGS_JSON
}
EOF

echo
echo "=== Summary ==="
echo "exit_code=$EXIT_CLASS"
echo "total_failures=$TOTAL_FAIL"
echo "report=$REPORT"

exit $EXIT_CLASS
