#!/usr/bin/env bash
# DR Drill Quarterly Cron Wrapper — Faz 12 otomasyonu (PLAN.md D23)
# Source: Codex Session 28 paralel cleanup A (thread 019dbc98)
#
# Cron install (staging-sw crontab):
#   0 3 1 */3 * /home/halil/platform-k8s-gitops/bootstrap/dr-drill-cron.sh
#   → 1 Ocak, 1 Nisan, 1 Temmuz, 1 Ekim 03:00 UTC çalışır
#
# Wrapper sorumluluğu:
#   1. dr-drill.sh çalıştır (SKIP_KC=0 default, prod env)
#   2. Duration + exit code kaydet
#   3. Prometheus textfile metric yaz (/var/lib/node_exporter/dr_drill.prom)
#   4. Fail durumunda alert path (log + exit code non-zero)
#
# Metrics (node_exporter textfile collector):
#   - dr_drill_last_run_timestamp_seconds (Unix epoch)
#   - dr_drill_last_run_duration_seconds
#   - dr_drill_last_run_success (1=PASS, 0=FAIL)
#   - dr_drill_last_rto_seconds (drill RTO actual)
#
# PrometheusRule (ayrı PR): dr_drill_last_run_success == 0 ile firing

set -euo pipefail

DRILL_ROOT="${DRILL_ROOT:-/home/halil/drill-sandbox}"
DRILL_ENV="${DRILL_ENV:-prod}"
SKIP_KC="${SKIP_KC:-0}"
OUTPUT_METRIC="${OUTPUT_METRIC:-/var/lib/node_exporter/dr_drill.prom}"
REPO_ROOT="${REPO_ROOT:-/home/halil/platform-k8s-gitops}"

log() { printf '\033[0;36m[drill-cron]\033[0m %s %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
err() { printf '\033[0;31m[drill-cron ERR]\033[0m %s %s\n' "$(date +%H:%M:%S)" "$*" >&2; }

log "START $(date +%FT%T%z) — DRILL_ENV=${DRILL_ENV} SKIP_KC=${SKIP_KC}"

# Preflight: repo + script + metric dir
if [[ ! -d "$REPO_ROOT" ]] || [[ ! -x "$REPO_ROOT/bootstrap/dr-drill.sh" ]]; then
  err "Repo veya dr-drill.sh yok: $REPO_ROOT/bootstrap/dr-drill.sh"
  exit 3
fi

if [[ ! -d "$(dirname "$OUTPUT_METRIC")" ]]; then
  err "node_exporter textfile dir yok: $(dirname "$OUTPUT_METRIC")"
  err "Oluştur: sudo mkdir -p $(dirname "$OUTPUT_METRIC") && sudo chown nobody:nogroup $(dirname "$OUTPUT_METRIC")"
  exit 3
fi

# Drill çalıştır
START_TS=$(date +%s)
set +e
DRILL_ROOT="$DRILL_ROOT" \
DRILL_CONFIRM=yes \
SKIP_KC="$SKIP_KC" \
DRILL_ENV="$DRILL_ENV" \
bash "$REPO_ROOT/bootstrap/dr-drill.sh" 2>&1 | tee "/tmp/dr-drill-cron-$(date +%Y%m%d-%H%M%S).log"
DRILL_RC=${PIPESTATUS[0]}
set -e
END_TS=$(date +%s)
DURATION=$((END_TS - START_TS))

# RTO çıkart son log'dan (drill script RTO: PASS (Xs / Ys budget) basar)
LATEST_LOG=$(ls -t /tmp/dr-drill-*.log 2>/dev/null | head -1)
RTO_SECONDS=$(grep -oE 'elapsed=[0-9]+s' "$LATEST_LOG" 2>/dev/null | tail -1 | tr -dc '0-9' || echo "0")

# Success flag
SUCCESS=0
if [[ $DRILL_RC -eq 0 ]]; then
  SUCCESS=1
  log "DRILL PASS (duration=${DURATION}s rto=${RTO_SECONDS}s)"
else
  err "DRILL FAIL (exit=$DRILL_RC duration=${DURATION}s)"
fi

# Prometheus textfile atomik write
TEMP_METRIC=$(mktemp "${OUTPUT_METRIC}.XXXXXX")
cat > "$TEMP_METRIC" <<EOF
# HELP dr_drill_last_run_timestamp_seconds Unix timestamp of last DR drill attempt
# TYPE dr_drill_last_run_timestamp_seconds gauge
dr_drill_last_run_timestamp_seconds ${END_TS}
# HELP dr_drill_last_run_duration_seconds Duration of last DR drill run in seconds
# TYPE dr_drill_last_run_duration_seconds gauge
dr_drill_last_run_duration_seconds ${DURATION}
# HELP dr_drill_last_run_success DR drill last run result (1=PASS, 0=FAIL)
# TYPE dr_drill_last_run_success gauge
dr_drill_last_run_success{env="${DRILL_ENV}",skip_kc="${SKIP_KC}"} ${SUCCESS}
# HELP dr_drill_last_rto_seconds Last drill measured RTO in seconds (budget 14400 = 4h)
# TYPE dr_drill_last_rto_seconds gauge
dr_drill_last_rto_seconds ${RTO_SECONDS}
EOF
mv -f "$TEMP_METRIC" "$OUTPUT_METRIC"
chmod 644 "$OUTPUT_METRIC"

log "METRIC WRITTEN: $OUTPUT_METRIC (success=$SUCCESS rto=${RTO_SECONDS}s)"
log "DONE $(date +%FT%T%z) exit=$DRILL_RC"

# Exit with drill exit code (cron MAILTO fail alert için)
exit $DRILL_RC
