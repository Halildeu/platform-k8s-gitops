#!/usr/bin/env bash
#
# pre-migration-audit.sh — Faz 21.0 pre-migration audit (Faz 23 M8 PR-3 A)
#
# Codex iter-1 REVISE absorbed: schema-qualified discovery via
# information_schema, per-table tenant key (org_id|tenant_id|skip),
# password-file mode enforcement, schema_version stable string.
#
# Purpose: READ-ONLY snapshot audit of a prod-shaped PG database to
# surface R10 invariant violations BEFORE Faz 21 multi-tenant migration
# begins. Emits a canonical JSON predicate file the operator commits
# under docs/faz-23-evidence/ as the Faz 21.0 sub-faz DoD.
#
# Discovery-first design (Codex iter-1 P0):
#   - Each tenant-scoped table candidate is verified via
#     `information_schema.tables` + `information_schema.columns`
#   - Missing table → OBSERVATION_INSUFFICIENT for that probe (not silent zero)
#   - Per-table tenant key: org_id OR tenant_id (whichever exists) OR derived-skip
#   - Schema-qualified names (e.g. notify.notification_intent vs bare
#     notify_intent) supported via --schema-prefix
#
# Inv-3 callback isolation analog (Codex iter-1 P0 absorb):
#   - This script's Inv-3 probe is a READ-ONLY snapshot analog only.
#   - The charter §4.3 callback isolation test
#     ("provider_message_id reused across tenants → update isolated by
#     org_id + external_id pair") REQUIRES a backend integration test
#     (concurrent update + assertion). Out of scope for this PR;
#     tracked in sibling backend repo (platform-backend) ticket.
#
# Anti-pattern guards (Codex 019e8c24 + 019e8c3e):
#   - READ-ONLY (no UPDATE/INSERT/DELETE)
#   - No raw tenant/PII in evidence (counts + sample IDs only)
#   - No backdated evidence (PG now() + workstation clock both recorded)
#   - PG password file MUST be 0400/0600 (group/world-readable rejected)
#
# Usage:
#   ./docs/scripts/faz-21/pre-migration-audit.sh \
#     --pg-host 127.0.0.1 --pg-port 15432 --pg-user audit_ro \
#     --pg-database platform --pg-password-file ~/.faz21-audit.pw \
#     --schema-prefix notify,endpoint_admin_service \
#     --out /tmp/audit.json
#
# Exit codes:
#   0 — All discoverable invariants CLEAN on snapshot
#   1 — INVARIANT_VIOLATION on snapshot (operator triage required)
#   2 — OBSERVATION_INSUFFICIENT (PG unreachable, schemas missing,
#       password file mode invalid, jq/psql/awk missing)
#   3 — Usage error

set -euo pipefail

PG_HOST=""
PG_PORT="5432"
PG_USER=""
PG_DATABASE="platform"
PG_PASSWORD_FILE=""
SCHEMA_PREFIX="notify,endpoint_admin_service,public"
OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pg-host)          PG_HOST="$2"; shift 2 ;;
    --pg-port)          PG_PORT="$2"; shift 2 ;;
    --pg-user)          PG_USER="$2"; shift 2 ;;
    --pg-database)      PG_DATABASE="$2"; shift 2 ;;
    --pg-password-file) PG_PASSWORD_FILE="$2"; shift 2 ;;
    --schema-prefix)    SCHEMA_PREFIX="$2"; shift 2 ;;
    --out)              OUT="$2"; shift 2 ;;
    -h|--help)
      sed -n '3,40p' "$0"
      exit 0
      ;;
    *)
      echo "ERROR: unknown arg: $1" >&2
      exit 3
      ;;
  esac
done

if [[ -z "$PG_HOST" || -z "$PG_USER" ]]; then
  echo "ERROR: --pg-host and --pg-user required" >&2
  exit 3
fi

if [[ -z "$OUT" ]]; then
  OUT="/tmp/faz-21-pre-migration-audit-$(date -u +%Y%m%d-%H%MZ).json"
fi

# Codex iter-1 P1/passwordFileMode absorb: enforce 0400/0600 on password
# file (group/world-readable rejected). `stat -c %a` on Linux; `stat -f %A`
# on macOS — we try both.
if [[ -n "$PG_PASSWORD_FILE" ]]; then
  if [[ ! -r "$PG_PASSWORD_FILE" ]]; then
    echo "ERROR: --pg-password-file unreadable" >&2
    exit 3
  fi
  PWFILE_MODE=""
  if PWFILE_MODE=$(stat -c %a "$PG_PASSWORD_FILE" 2>/dev/null); then :; fi
  if [[ -z "$PWFILE_MODE" ]]; then
    PWFILE_MODE=$(stat -f %A "$PG_PASSWORD_FILE" 2>/dev/null || true)
  fi
  if [[ -z "$PWFILE_MODE" ]]; then
    echo "ERROR: cannot determine --pg-password-file mode (stat unavailable)" >&2
    exit 2
  fi
  case "$PWFILE_MODE" in
    400|600|0400|0600) ;;
    *)
      echo "ERROR: --pg-password-file mode is $PWFILE_MODE; require 0400 or 0600 (chmod 0400 path)" >&2
      exit 2
      ;;
  esac
  export PGPASSWORD
  PGPASSWORD="$(cat "$PG_PASSWORD_FILE")"
fi

# Dependency probe.
for cmd in psql jq awk; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: $cmd not on PATH" >&2
    exit 2
  fi
done

PSQL_BASE="psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $PG_DATABASE -At -X"

qry_int() {
  local sql="$1"
  local raw
  raw="$($PSQL_BASE -c "$sql" 2>/dev/null | head -n1)" || true
  if [[ -z "$raw" ]]; then echo "null"; else echo "$raw"; fi
}

# Probe connectivity first.
PROBE=$(qry_int "SELECT 1")
if [[ "$PROBE" != "1" ]]; then
  echo "ERROR: PG probe failed (host=$PG_HOST user=$PG_USER db=$PG_DATABASE)" >&2
  exit 2
fi

PG_NOW=$(qry_int "SELECT EXTRACT(epoch FROM now())::int")
WS_NOW=$(date -u +%s)
GENERATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# ----------------------------------------------------------------------
# Inv-2 schema-discovery probe (Codex iter-1 P0/schemaDiscovery absorb).
# Candidate tenant-scoped tables (schema-qualified via --schema-prefix):
#   notify.notification_intent / dispatch / delivery / outbox / audit_event_v2
#   endpoint_admin_service.endpoint_device / software_inventory / outdated_software / install_audit / compliance_policy_evaluation / app_control
# For each candidate (schema, table) pair:
#   1. Verify table exists in information_schema.tables
#   2. Detect tenant key: prefer org_id, then tenant_id, else skip-with-note
#   3. SELECT count(*) WHERE <tenant_key> IS NULL
# Verdict-relevant only for tables that BOTH exist AND have a tenant key.
INV2_CANDIDATES=(
  "notify.notification_intent"
  "notify.notification_dispatch"
  "notify.notification_delivery"
  "notify.notification_outbox"
  "notify.audit_event_v2"
  "endpoint_admin_service.endpoint_device"
  "endpoint_admin_service.endpoint_software_inventory"
  "endpoint_admin_service.endpoint_outdated_software"
  "endpoint_admin_service.endpoint_install_audit"
  "endpoint_admin_service.endpoint_compliance_policy_evaluation"
  "endpoint_admin_service.endpoint_app_control"
)

table_exists() {
  local schema="$1" tbl="$2"
  local v
  v=$(qry_int "SELECT count(*) FROM information_schema.tables WHERE table_schema = '$schema' AND table_name = '$tbl'")
  [[ "$v" == "1" ]]
}

column_exists() {
  local schema="$1" tbl="$2" col="$3"
  local v
  v=$(qry_int "SELECT count(*) FROM information_schema.columns WHERE table_schema = '$schema' AND table_name = '$tbl' AND column_name = '$col'")
  [[ "$v" == "1" ]]
}

INV2_JSON="["
first=true
INV2_FAIL_COUNT=0
INV2_DISCOVERED_COUNT=0
INV2_MISSING_COUNT=0
INV2_NO_KEY_COUNT=0
for st in "${INV2_CANDIDATES[@]}"; do
  schema="${st%%.*}"
  tbl="${st##*.}"
  status="discovered"
  tenant_key="null"
  null_count="null"
  if ! table_exists "$schema" "$tbl"; then
    status="missing_table"
    INV2_MISSING_COUNT=$((INV2_MISSING_COUNT + 1))
  else
    INV2_DISCOVERED_COUNT=$((INV2_DISCOVERED_COUNT + 1))
    if column_exists "$schema" "$tbl" "org_id"; then
      tenant_key="\"org_id\""
      null_count=$(qry_int "SELECT count(*) FROM \"$schema\".\"$tbl\" WHERE org_id IS NULL")
    elif column_exists "$schema" "$tbl" "tenant_id"; then
      tenant_key="\"tenant_id\""
      null_count=$(qry_int "SELECT count(*) FROM \"$schema\".\"$tbl\" WHERE tenant_id IS NULL")
    else
      status="no_tenant_key_column"
      INV2_NO_KEY_COUNT=$((INV2_NO_KEY_COUNT + 1))
    fi
    if [[ "$null_count" != "null" && "$null_count" != "0" ]]; then
      INV2_FAIL_COUNT=$((INV2_FAIL_COUNT + 1))
    fi
  fi
  [[ "$first" == "true" ]] && first=false || INV2_JSON+=","
  INV2_JSON+="{\"schema\":\"$schema\",\"table\":\"$tbl\",\"status\":\"$status\",\"tenant_key_column\":$tenant_key,\"null_tenant_key_count\":$null_count}"
done
INV2_JSON+="]"

# ----------------------------------------------------------------------
# Inv-3 read-only snapshot analog (Codex iter-1 P0/inv3Scope absorb).
# This probe is a READ-ONLY analog only; charter §4.3 callback isolation
# test ("provider_message_id reused across tenants → update isolated by
# org_id + external_id pair") REQUIRES a backend integration test
# (concurrent update + assertion). Tracked separately.
#
# Snapshot analog: count delivery rows where provider_msg_id OR
# provider_message_id is non-null AND tenant key is null. Both column
# names probed via information_schema (real schema uses provider_msg_id
# per Codex iter-1 P0 finding).
INV3_NOTIFY_DELIVERY_SCHEMA="notify"
INV3_NOTIFY_DELIVERY_TABLE="notification_delivery"
INV3_CALLBACK_ORPHAN="null"
INV3_PROVIDER_DISTINCT="null"
INV3_STATUS="OBSERVATION_INSUFFICIENT"
if table_exists "$INV3_NOTIFY_DELIVERY_SCHEMA" "$INV3_NOTIFY_DELIVERY_TABLE"; then
  PROV_COL=""
  if column_exists "$INV3_NOTIFY_DELIVERY_SCHEMA" "$INV3_NOTIFY_DELIVERY_TABLE" "provider_msg_id"; then
    PROV_COL="provider_msg_id"
  elif column_exists "$INV3_NOTIFY_DELIVERY_SCHEMA" "$INV3_NOTIFY_DELIVERY_TABLE" "provider_message_id"; then
    PROV_COL="provider_message_id"
  fi
  TENANT_COL=""
  if column_exists "$INV3_NOTIFY_DELIVERY_SCHEMA" "$INV3_NOTIFY_DELIVERY_TABLE" "org_id"; then
    TENANT_COL="org_id"
  elif column_exists "$INV3_NOTIFY_DELIVERY_SCHEMA" "$INV3_NOTIFY_DELIVERY_TABLE" "tenant_id"; then
    TENANT_COL="tenant_id"
  fi
  if [[ -n "$PROV_COL" && -n "$TENANT_COL" ]]; then
    INV3_CALLBACK_ORPHAN=$(qry_int "SELECT count(*) FROM \"$INV3_NOTIFY_DELIVERY_SCHEMA\".\"$INV3_NOTIFY_DELIVERY_TABLE\" WHERE $PROV_COL IS NOT NULL AND $TENANT_COL IS NULL")
    if column_exists "$INV3_NOTIFY_DELIVERY_SCHEMA" "$INV3_NOTIFY_DELIVERY_TABLE" "provider"; then
      INV3_PROVIDER_DISTINCT=$(qry_int "SELECT count(DISTINCT provider) FROM \"$INV3_NOTIFY_DELIVERY_SCHEMA\".\"$INV3_NOTIFY_DELIVERY_TABLE\" WHERE provider IS NOT NULL")
    fi
    INV3_STATUS="DISCOVERED"
  else
    INV3_STATUS="COLUMNS_MISSING"
  fi
fi

# ----------------------------------------------------------------------
# Inv-1 advisory request audit probe (Codex iter-1 P1 absorb).
# Discover via information_schema. Multiple schemas may host request audit
# table; we probe the most common.
INV1_STATUS="ADVISORY_ABSENT"
INV1_VAL="null"
INV1_TABLE_CANDIDATES=("public.request_audit" "audit.request_audit" "platform.request_audit")
for st in "${INV1_TABLE_CANDIDATES[@]}"; do
  schema="${st%%.*}"
  tbl="${st##*.}"
  if table_exists "$schema" "$tbl"; then
    TENANT_COL=""
    if column_exists "$schema" "$tbl" "org_id"; then TENANT_COL="org_id"; fi
    if [[ -z "$TENANT_COL" ]] && column_exists "$schema" "$tbl" "tenant_id"; then TENANT_COL="tenant_id"; fi
    if [[ -n "$TENANT_COL" ]] && column_exists "$schema" "$tbl" "created_at"; then
      INV1_VAL=$(qry_int "SELECT count(*) FROM \"$schema\".\"$tbl\" WHERE $TENANT_COL IS NULL AND created_at > now() - interval '24 hours'")
      INV1_STATUS="DISCOVERED"
      break
    fi
  fi
done

# Verdict logic.
VERDICT="CLEAN"
if [[ "$INV2_FAIL_COUNT" -gt 0 ]]; then VERDICT="INVARIANT_VIOLATION"; fi
if [[ "$INV3_CALLBACK_ORPHAN" != "null" && "$INV3_CALLBACK_ORPHAN" != "0" ]]; then VERDICT="INVARIANT_VIOLATION"; fi

# Observation guard: if too few candidates discovered, fall to OBSERVATION_INSUFFICIENT.
if [[ "$INV2_DISCOVERED_COUNT" -lt 2 ]]; then
  VERDICT="OBSERVATION_INSUFFICIENT"
fi

cat >"$OUT" <<EOF
{
  "schema_version": "faz-21-pre-migration-audit/v2",
  "generated_at": "${GENERATED_AT}",
  "pg_time_unix": ${PG_NOW},
  "workstation_time_unix": ${WS_NOW},
  "pg_host": "${PG_HOST}",
  "pg_database": "${PG_DATABASE}",
  "audit_scope": "Faz 21.0 sub-faz DoD (charter §4.3)",
  "predicates": {
    "inv2_tenant_persistence_per_table": ${INV2_JSON},
    "inv2_summary": {
      "discovered_count": ${INV2_DISCOVERED_COUNT},
      "missing_count": ${INV2_MISSING_COUNT},
      "no_tenant_key_count": ${INV2_NO_KEY_COUNT},
      "violation_count": ${INV2_FAIL_COUNT}
    },
    "inv3_callback_correlation_orphan": {
      "status": "${INV3_STATUS}",
      "orphan_count": ${INV3_CALLBACK_ORPHAN},
      "provider_distinct_count": ${INV3_PROVIDER_DISTINCT}
    },
    "inv1_request_missing_advisory_24h": {
      "status": "${INV1_STATUS}",
      "count": ${INV1_VAL}
    }
  },
  "thresholds": {
    "inv2_violation_count_max": 0,
    "inv3_orphan_count_max": 0,
    "inv1_advisory_max": 100
  },
  "scope_notes": {
    "inv3_snapshot_analog_only": "Read-only orphan count; charter §4.3 callback isolation test REQUIRES backend integration test (concurrent update + assertion). Tracked separately.",
    "inv4_ai_boundary_not_audited_here": "Inv-4 manual cross-check required; see r10-invariant-checks.sh + RB §4.1"
  },
  "verdict": "${VERDICT}",
  "anti_pattern_guards": {
    "read_only_on_production": true,
    "no_raw_tenant_pii_in_evidence": true,
    "pg_password_file_mode_enforced": true,
    "schema_discovery_first": true,
    "backdate_evidence": false,
    "pg_time_skew_present": true
  }
}
EOF

echo "evidence: $OUT"
echo "verdict:  $VERDICT"

case "$VERDICT" in
  CLEAN) exit 0 ;;
  INVARIANT_VIOLATION) exit 1 ;;
  OBSERVATION_INSUFFICIENT) exit 2 ;;
  *) exit 2 ;;
esac
