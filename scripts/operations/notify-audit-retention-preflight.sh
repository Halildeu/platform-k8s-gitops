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
  KUBECTL="ssh aiadmin@aiserver kubectl --context $CTX -n $NS"
  DOCKER_EXEC="ssh aiadmin@aiserver"
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
# 2. Live retention metrics snapshot (per-pod aware)
# -----------------------------------------------------------------------
section "2. Retention metrics snapshot (per-pod — leader/follower disambiguation)"

# Codex 019e0ba9 iter-1 P1 absorb: `kubectl exec deploy/...` round-robins
# across pods and produces non-deterministic leader vs follower. We need to
# scrape EACH pod individually so the C.2 evidence block can prove which
# pod was the leader (gauge>0, skip=0) and which was the follower (gauge=0,
# skip=1) at first cron tick.

PODS=$($KUBECTL get pods -l app.kubernetes.io/name=notification-orchestrator -o name 2>/dev/null \
  | sed 's|pod/||' \
  | head -10)

if [[ -z "$PODS" ]]; then
  echo "WARN: no pods found with selector app.kubernetes.io/name=notification-orchestrator"
fi

for POD in $PODS; do
  echo "--- pod: $POD ---"
  $KUBECTL exec "$POD" -- wget -qO- localhost:8081/actuator/prometheus 2>/dev/null \
    | grep -E "^notify_audit_retention_" \
    | tee -a "$LOG_FILE" || echo "WARN: actuator unreachable on $POD"
  echo
done

echo "Interpretation:"
echo "  notify_audit_retention_last_success_timestamp_seconds:"
echo "    0      = bean activated but this pod never won the advisory lock"
echo "    > 0    = leader pod; healthy if (time() - gauge) < 26h"
echo "  notify_audit_retention_lock_skipped_total:"
echo "    0      = leader pod (won the lock that cron tick)"
echo "    > 0    = follower pod, expected baseline = 1 per cron tick per non-leader pod"
echo "  notify_audit_retention_partitions_detached_total:"
echo "    must be 0 while DRY_RUN=true (any non-zero = bug — investigate)"
echo "  notify_audit_retention_errors_total{phase=...}: any non-zero needs triage"
echo
echo "Multi-pod expected pattern (2 replicas + daily cron):"
echo "  Exactly 1 pod has gauge>0 + skip=0 (leader)"
echo "  Other(s) have gauge=0 + skip=1 (follower) — does NOT indicate failure"

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
  # Codex 019e0ba9 iter-1 P2 absorb: container name is `platform-pg-${ENV}`,
  # NOT `platform-postgres-${ENV}` (verified via `docker ps --format
  # '{{.Names}}\t{{.Image}}' | grep -i postgres` on staging-sw).
  if [[ "$PG_AVAILABLE" == "1" ]]; then
    $DOCKER_EXEC docker exec platform-pg-${ENV} psql -U platform -d notify_db -c "$1" 2>&1 || true
  else
    echo "(psql skipped — DB_URL unavailable)"
  fi
}

psql_select "SELECT partition_name, status, dry_run, detached_at, drop_after, dropped_at, error_message, created_at FROM notify.audit_retention_log ORDER BY created_at DESC LIMIT 20;"

echo
echo "Interpretation (Codex 019e0bb6 iter-2 P3 absorb — actual schema):"
echo "  Empty result + bean activated = clean state, no historical retention runs"
echo "  status='detached' rows with drop_after <= now() AND dropped_at IS NULL ="
echo "    candidates for next cron tick to DROP"
echo "  status='dropped' rows = already-dropped partition history"
echo "  status='failed' rows = DROP failed (error_message has detail; manual triage)"
echo "  dry_run=true rows = recorded during dry-run mode (no actual DETACH/DROP executed)"

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
echo "  Empty CANDIDATE list = no DETACH/DROP candidate for first flip"
echo "    (NOT 'zero risk' — destructive DB operation discipline still applies"
echo "     per Codex 019e0b9f; cf. backend test gap fix prerequisite)"
echo "  Default partition (audit_event_v2_default) NEVER detached (catches mis-routed inserts)"

# -----------------------------------------------------------------------
# 6. DB privilege verification (Codex 019e0ba9 iter-1 P2 absorb)
# -----------------------------------------------------------------------
section "6. DB privilege check (DETACH/DROP capability)"

# AuditPartitionRetentionService runs ALTER TABLE ... DETACH PARTITION
# and DROP TABLE on partition children. PostgreSQL's authoritative signal
# for these operations is OWNERSHIP — not has_table_privilege() flags.
# Codex iter-1 P2 absorb: `TRIGGER` privilege is misleading; check ownership
# of the audit_event_v2 root table + child partitions, plus schema CREATE.

psql_select "SELECT
  current_user AS role_in_use,
  session_user AS session_role,
  has_schema_privilege(current_user, 'notify', 'CREATE') AS can_create_in_schema,
  pg_get_userbyid(c.relowner) AS audit_root_owner,
  current_user = pg_get_userbyid(c.relowner) AS user_owns_audit_root,
  has_table_privilege(current_user, 'notify.audit_event_v2', 'TRIGGER') AS legacy_trigger_check
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'notify' AND c.relname = 'audit_event_v2';"

echo
psql_select "SELECT
  c.relname AS partition_name,
  pg_get_userbyid(c.relowner) AS partition_owner,
  current_user = pg_get_userbyid(c.relowner) AS user_owns_partition
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'notify'
  AND c.relname ~ '^audit_event_v2_(\d{4}_\d{2}|default)$'
ORDER BY c.relname;"

echo
echo "Interpretation:"
echo "  user_owns_audit_root=t = current_user can ALTER ... DETACH on root table"
echo "  user_owns_partition=t = current_user can DROP child partition table"
echo "  Both must be true for non-dry-run retention to succeed."
echo "  legacy_trigger_check is shown for backward compatibility comparison;"
echo "  it does NOT prove DETACH/DROP capability."

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
        on the LEADER pod (post first 02:00 UTC cron tick); per-pod
        disambiguation in §2 above
[ ] §2: notify_audit_retention_partitions_detached_total = 0 in dry-run cycle
        (note: dry-run intentionally short-circuits before incrementing,
         so this is non-authoritative — see §5 for real candidate proof)
[ ] §2: notify_audit_retention_errors_total = 0 across all phases
[ ] §3: audit_retention_log: empty OR only contains expected dry-run history
[ ] §4: Partition inventory: every row has known partition_name + non-zero row count
[ ] §5: CANDIDATE set (partitions older than retentionDays=90) is reviewed +
        acceptable (e.g., 0 candidates = no DETACH/DROP candidate for first
        flip; OR N candidates with explicit operator approval for what gets
        dropped). Authoritative source for "0 candidates" — log absence of
        `[dry-run] would DETACH ...` lines + partition inventory query.
[ ] §6: DB role OWNS audit_event_v2 root table + child partitions
        (Codex 019e0ba9 iter-1 P2 absorb: ownership is authoritative,
         not the legacy TRIGGER privilege check). user_owns_audit_root=t
         AND user_owns_partition=t for every candidate partition.
[ ] §6: schema CREATE privilege for new monthly partition creation
[ ] §7: NotifyAuditRetentionStale + Errors + LockSkippedSustained alerts
        inactive (healthy); LockSkippedSustained iter-2 form distinguishes
        expected multi-pod skip from stuck-leader

Backend test gap (Codex 019e090d iter-1 P3 → 019e0ba9 P3 BLOCKER):
[ ] platform-backend has dedicated `AuditPartitionRetentionDetachDropTest`
    class (separate from AuditPartitionV8IntegrationTest) with 4 methods
    covering DETACH/DROP/cutoff/idempotency on disposable partition,
    Testcontainers PG run 4/4 PASS in CI

If ANY box unchecked → DO NOT flip dry-run=false.
If all boxes checked → C.2 PR with this evidence block referenced.
Reminder: pre-prod tek-user context reduces blast radius but does NOT
remove destructive-DB-operation discipline (Codex 019e0b9f).
EOF

echo
echo "Full log: $LOG_FILE"
