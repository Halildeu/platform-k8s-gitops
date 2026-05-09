#!/usr/bin/env bash
#
# notify-audit-retention-preflight.sh — Step C.2 dry-run→non-dry-run flip
# pre-flight inventory + evidence collection.
#
# Codex `019e0b9f` strategic retrospective C.2 prep work:
#   "Backend test DETACH/DROP path exercise + 02:00 dry-run tick clean +
#    inventory expected candidate set" before flipping
#    NOTIFY_AUDIT_RETENTION_DRY_RUN=false in production.
#
# This script collects:
#   1. AuditPartitionRetentionService activation log (bean instantiated?)
#   2. Live retention metrics snapshot (Prometheus + actuator/prometheus)
#   3. PG audit_retention_log table state (any pre-existing detached partitions?)
#   4. PG partition inventory (audit_event_v2_YYYY_MM list + row counts)
#   5. Candidate DETACH set (partitions older than retentionDays=90)
#   6. DB privilege verification (DETACH/DROP capable role?)
#   7. Last-success timestamp gauge state (gauge=0 = never succeeded; gauge>0 + age < 26h = healthy)
#
# Usage:
#   bash scripts/operations/notify-audit-retention-preflight.sh <env>
#     env = test | prod (default: prod)
#
# Output:
#   /tmp/notify-audit-retention-preflight-<env>-<UTC-timestamp>.log (full text)
#   stdout: 7-section structured summary (eligible for C.2 PR evidence block)
#
# Boundary: read-only — no DETACH/DROP/INSERT/UPDATE on audit data.
# Only kubectl get / exec wget / psql SELECT.

set -euo pipefail

ENV="${1:-prod}"
if [[ "$ENV" != "test" && "$ENV" != "prod" ]]; then
  echo "ERROR: env must be 'test' or 'prod' (got: $ENV)" >&2
  exit 1
fi

CTX="k3d-${ENV}"
NS="platform-${ENV}"
TS=$(date -u +%Y%m%dT%H%M%SZ)
LOG_FILE="/tmp/notify-audit-retention-preflight-${ENV}-${TS}.log"

# Detect SSH access if running outside staging-sw (local dev convenience).
KUBECTL="kubectl --context $CTX -n $NS"
DOCKER_EXEC=""
if ! kubectl --context "$CTX" version --request-timeout=5s &>/dev/null; then
  echo "INFO: kubectl context $CTX unreachable from this host; using SSH bridge" | tee -a "$LOG_FILE"
  KUBECTL="ssh halil@staging-sw kubectl --context $CTX -n $NS"
  DOCKER_EXEC="ssh halil@staging-sw"
fi

section() {
  echo
  echo "=== $1 ==="
  echo
}

run() {
  # Mirror command + output to both stdout (concise) and log file (full).
  echo "$ $*" >> "$LOG_FILE"
  "$@" 2>&1 | tee -a "$LOG_FILE"
}

{
  echo "notify-audit-retention-preflight"
  echo "env=$ENV  context=$CTX  namespace=$NS"
  echo "timestamp=$TS"
  echo "log=$LOG_FILE"
} | tee "$LOG_FILE"

# -----------------------------------------------------------------------
# 1. Bean activation log
# -----------------------------------------------------------------------
section "1. AuditPartitionRetentionService activation log"

ACTIVATION=$($KUBECTL logs deploy/notification-orchestrator --tail=1000 2>/dev/null \
  | grep -E "AuditPartitionRetentionService activated|ConditionalOnProperty" \
  | tail -3 || true)

if [[ -z "$ACTIVATION" ]]; then
  echo "WARN: no activation log found — bean may NOT be instantiated."
  echo "      Check NOTIFY_AUDIT_RETENTION_ENABLED env var:"
  $KUBECTL exec deploy/notification-orchestrator -- env 2>/dev/null \
    | grep -E "NOTIFY_AUDIT_RETENTION_(ENABLED|DRY_RUN|DAYS)" || true
else
  echo "OK: activation log:"
  echo "$ACTIVATION"
fi

# -----------------------------------------------------------------------
# 2. Live retention metrics snapshot (actuator/prometheus)
# -----------------------------------------------------------------------
section "2. Retention metrics snapshot"

$KUBECTL exec deploy/notification-orchestrator -- wget -qO- localhost:8081/actuator/prometheus 2>/dev/null \
  | grep -E "^notify_audit_retention_" \
  | head -20 \
  | tee -a "$LOG_FILE" || echo "WARN: actuator endpoint unreachable"

echo
echo "Interpretation:"
echo "  notify_audit_retention_last_success_timestamp_seconds:"
echo "    0      = bean activated but cron never ticked (NeverSucceeded; expected pre-first-tick)"
echo "    > 0    = healthy if (time() - gauge) < 26h"
echo "  notify_audit_retention_partitions_detached_total:"
echo "    must be 0 while DRY_RUN=true (any non-zero = bug — investigate)"
echo "  notify_audit_retention_errors_total{phase=...}: any non-zero needs triage"

# -----------------------------------------------------------------------
# 3. audit_retention_log table state
# -----------------------------------------------------------------------
section "3. audit_retention_log table inventory"

# Need the SPRING_DATASOURCE_URL to know which DB. ConfigMap data:
DB_URL=$($KUBECTL exec deploy/notification-orchestrator -- env 2>/dev/null \
  | grep "^SPRING_DATASOURCE_URL=" \
  | head -1 \
  | cut -d= -f2- || true)

if [[ -z "$DB_URL" ]]; then
  echo "WARN: SPRING_DATASOURCE_URL not exposed (env var may be optional). Skipping PG queries."
  PG_AVAILABLE=0
else
  echo "Datasource: $DB_URL"
  PG_AVAILABLE=1
fi

# We use psql via the postgres docker container (staging-sw host pattern).
# Read-only queries — SELECT only.
psql_select() {
  if [[ "$PG_AVAILABLE" == "1" ]]; then
    $DOCKER_EXEC docker exec platform-postgres-${ENV} psql -U platform -d notify_db -c "$1" 2>&1 || true
  else
    echo "(psql skipped — DB_URL unavailable)"
  fi
}

psql_select "SELECT partition_name, action, executed_at, drop_after FROM notify.audit_retention_log ORDER BY executed_at DESC LIMIT 20;"

echo
echo "Interpretation:"
echo "  Empty result + bean activated = clean state, no historical retention runs"
echo "  action='detach' rows with drop_after <= now() = candidates for next cron tick to DROP"
echo "  action='drop' rows = already-dropped partition history"

# -----------------------------------------------------------------------
# 4. Partition inventory
# -----------------------------------------------------------------------
section "4. audit_event_v2 partition list + row counts"

psql_select "SELECT
  c.relname AS partition_name,
  pg_size_pretty(pg_total_relation_size(c.oid)) AS size,
  s.n_live_tup AS row_count_estimate
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
WHERE n.nspname = 'notify'
  AND c.relname ~ '^audit_event_v2_(\d{4}_\d{2}|default)$'
ORDER BY c.relname;"

# -----------------------------------------------------------------------
# 5. Candidate DETACH set (>= 90 days old)
# -----------------------------------------------------------------------
section "5. Candidates eligible for DETACH (older than retentionDays=90)"

psql_select "WITH partitions AS (
  SELECT
    c.relname AS partition_name,
    -- Extract YYYY_MM from regular partition names; default → null
    CASE
      WHEN c.relname ~ '^audit_event_v2_\d{4}_\d{2}$'
      THEN to_date(substring(c.relname FROM 'audit_event_v2_(\d{4}_\d{2})'), 'YYYY_MM')
      ELSE NULL
    END AS partition_month
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'notify'
    AND c.relname ~ '^audit_event_v2_(\d{4}_\d{2}|default)$'
)
SELECT
  partition_name,
  partition_month,
  CASE
    WHEN partition_month IS NULL THEN 'default (skip)'
    WHEN partition_month < (NOW() - INTERVAL '90 days') THEN 'CANDIDATE'
    ELSE 'retained'
  END AS retention_decision,
  AGE(NOW(), partition_month) AS partition_age
FROM partitions
ORDER BY partition_month NULLS LAST;"

echo
echo "Interpretation:"
echo "  retention_decision='CANDIDATE' = first non-dry-run cron tick will DETACH this partition"
echo "  Empty CANDIDATE list = no-op flip (zero risk)"
echo "  Default partition (audit_event_v2_default) NEVER detached (catches mis-routed inserts)"

# -----------------------------------------------------------------------
# 6. DB privilege verification
# -----------------------------------------------------------------------
section "6. DB privilege check (DETACH/DROP capability for retention role)"

# AuditPartitionRetentionService uses the connection pool (SPRING_DATASOURCE_USERNAME).
# Check if it has ALTER + DROP privileges on notify schema.

psql_select "SELECT
  has_table_privilege(current_user, 'notify.audit_event_v2', 'TRIGGER') AS can_alter_audit_root,
  has_schema_privilege(current_user, 'notify', 'CREATE') AS can_create_in_schema,
  current_user AS role_in_use,
  session_user AS session_role;"

# -----------------------------------------------------------------------
# 7. Prometheus alert state (NeverSucceeded + Stale + Errors)
# -----------------------------------------------------------------------
section "7. Prometheus alert state for notify-audit-retention group"

# Only meaningful for prod (test cluster has no Prometheus operator).
if [[ "$ENV" == "prod" ]]; then
  PROM_PORT=19090
  echo "Spawning port-forward to prometheus..."

  # Force-kill any leftover port-forward
  if [[ -n "$DOCKER_EXEC" ]]; then
    $DOCKER_EXEC "pkill -f 'port-forward prometheus' 2>/dev/null || true"
    $DOCKER_EXEC kubectl --context k3d-prod -n monitoring port-forward prometheus-kube-prometheus-stack-prometheus-0 ${PROM_PORT}:9090 >/dev/null 2>&1 &
    sleep 5
    $DOCKER_EXEC curl -fsS "http://localhost:${PROM_PORT}/prometheus/api/v1/rules?type=alert" 2>/dev/null \
      | python3 -c "import sys, json
data = json.load(sys.stdin)
for g in data['data']['groups']:
    if 'audit-retention' in g['name']:
        for r in g['rules']:
            if r['type'] == 'alerting':
                state = r.get('state', '?')
                print(f\"  {state:9s} - {r['name']}\")"
    $DOCKER_EXEC "pkill -f 'port-forward prometheus' 2>/dev/null || true"
  else
    kubectl --context k3d-prod -n monitoring port-forward prometheus-kube-prometheus-stack-prometheus-0 ${PROM_PORT}:9090 >/dev/null 2>&1 &
    PF_PID=$!
    sleep 5
    curl -fsS "http://localhost:${PROM_PORT}/prometheus/api/v1/rules?type=alert" \
      | python3 -c "import sys, json
data = json.load(sys.stdin)
for g in data['data']['groups']:
    if 'audit-retention' in g['name']:
        for r in g['rules']:
            if r['type'] == 'alerting':
                state = r.get('state', '?')
                print(f\"  {state:9s} - {r['name']}\")"
    kill $PF_PID 2>/dev/null || true
  fi
else
  echo "(test cluster has no Prometheus — skipping alert state query)"
fi

echo
echo "Interpretation:"
echo "  NotifyAuditRetentionNeverSucceeded pending = expected before first cron tick"
echo "  NotifyAuditRetentionStale firing = cron tick missed > 26h ago"
echo "  NotifyAuditRetentionErrors firing = error counter increment in last 2h"
echo "  All inactive after first successful tick = healthy state"

# -----------------------------------------------------------------------
section "DECISION GATE — C.2 dry-run=false flip readiness checklist"

cat <<'EOF'
Before opening C.2 PR (dry-run=false) verify ALL of:

[ ] §1: Bean activation log shows `AuditPartitionRetentionService activated:
        retentionDays=90 cron=0 0 2 * * * graceHours=24 dryRun=true ...`
[ ] §2: notify_audit_retention_last_success_timestamp_seconds advanced to > 0
        (post first 02:00 UTC cron tick)
[ ] §2: notify_audit_retention_partitions_detached_total = 0 in dry-run cycle
        (any non-zero value while DRY_RUN=true is a BUG)
[ ] §2: notify_audit_retention_errors_total = 0 across all phases
[ ] §3: audit_retention_log: empty OR only contains expected dry-run history
[ ] §4: Partition inventory: every row has known partition_name + non-zero row count
[ ] §5: CANDIDATE set is reviewed + acceptable (e.g., 0 candidates = no-op flip,
        or N candidates with explicit operator approval for what gets dropped)
[ ] §6: DB role has TRIGGER (ALTER) privilege on audit_event_v2 root +
        CREATE on notify schema
[ ] §7: NotifyAuditRetentionStale + Errors alerts inactive (healthy)

Backend test gap (Codex 019e090d iter-1 P3 BLOCKER):
[ ] platform-backend AuditPartitionV8IntegrationTest exercises DETACH/DROP
    code path with disposable partition (NOT retention-days=36500 sentinel)

If ANY box unchecked → DO NOT flip dry-run=false.
If all boxes checked → C.2 PR with this evidence block referenced.
EOF

echo
echo "Full log: $LOG_FILE"
