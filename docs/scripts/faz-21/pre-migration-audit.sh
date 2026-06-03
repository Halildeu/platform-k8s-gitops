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
  "notify.idempotency_key"
  # Endpoint candidates — Codex iter-4 P1/endpointCoverage absorb. Repo
  # evidence uses pluralized + state-history + snapshots/packages names;
  # we list both singular and plural/canonical variants so table_exists
  # can pick the right one. Missing variants flow as `missing_table`
  # (counted) and the schema-prefix guard guarantees at least one endpoint
  # table is discovered (OBSERVATION_INSUFFICIENT otherwise).
  "endpoint_admin_service.endpoint_device"
  "endpoint_admin_service.endpoint_devices"
  "endpoint_admin_service.endpoint_software_inventory"
  "endpoint_admin_service.endpoint_software_inventory_state_history"
  "endpoint_admin_service.endpoint_outdated_software"
  "endpoint_admin_service.endpoint_outdated_software_snapshots"
  "endpoint_admin_service.endpoint_outdated_software_packages"
  "endpoint_admin_service.endpoint_install_audit"
  "endpoint_admin_service.install_audit"
  "endpoint_admin_service.endpoint_compliance_policy_evaluation"
  "endpoint_admin_service.endpoint_compliance_evaluations"
  "endpoint_admin_service.endpoint_app_control"
  "endpoint_admin_service.endpoint_app_control_snapshots"
)

# Codex iter-2 P1/derivedTenantKey absorb: some tables don't carry org_id
# or tenant_id directly; they carry a parent FK (e.g.
# notify.notification_delivery → notification_intent.org_id;
# endpoint child tables → endpoint_device.org_id). Derived check pattern
# uses LEFT JOIN to parent; orphans (FK NULL or parent NULL) count.
declare -A DERIVED_PARENT_FK=(
  ["notify.notification_delivery"]="intent_id|notify.notification_intent|intent_id"
  ["notify.notification_dispatch"]="intent_id|notify.notification_intent|intent_id"
  ["notify.notification_outbox"]="intent_id|notify.notification_intent|intent_id"
  ["notify.audit_event_v2"]="intent_id|notify.notification_intent|intent_id"
  # Endpoint child tables — both singular (endpoint_device) and plural
  # (endpoint_devices) variants point to the same parent join spec; the
  # parent table for derived join is selected by table_exists guard.
  ["endpoint_admin_service.endpoint_software_inventory"]="device_id|endpoint_admin_service.endpoint_device|id"
  ["endpoint_admin_service.endpoint_software_inventory_state_history"]="device_id|endpoint_admin_service.endpoint_devices|id"
  ["endpoint_admin_service.endpoint_outdated_software"]="device_id|endpoint_admin_service.endpoint_device|id"
  ["endpoint_admin_service.endpoint_outdated_software_snapshots"]="device_id|endpoint_admin_service.endpoint_devices|id"
  ["endpoint_admin_service.endpoint_outdated_software_packages"]="device_id|endpoint_admin_service.endpoint_devices|id"
  ["endpoint_admin_service.endpoint_install_audit"]="device_id|endpoint_admin_service.endpoint_device|id"
  ["endpoint_admin_service.install_audit"]="device_id|endpoint_admin_service.endpoint_devices|id"
  ["endpoint_admin_service.endpoint_compliance_policy_evaluation"]="device_id|endpoint_admin_service.endpoint_device|id"
  ["endpoint_admin_service.endpoint_compliance_evaluations"]="device_id|endpoint_admin_service.endpoint_devices|id"
  ["endpoint_admin_service.endpoint_app_control"]="device_id|endpoint_admin_service.endpoint_device|id"
  ["endpoint_admin_service.endpoint_app_control_snapshots"]="device_id|endpoint_admin_service.endpoint_devices|id"
)
# Codex iter-3 P0/notifyParentPK absorb: Notify parent PK is `intent_id`,
# not `id` — the notification_intent table's primary key is intent_id
# (event-contract surface). Endpoint family keeps `id` as primary key.

# Codex iter-2 P1/schemaPrefixUnused absorb: --schema-prefix actually
# filters candidate expansion now. Comma-separated allow-list of schemas.
filter_by_schema_prefix() {
  local schema="$1"
  local IFS=,
  for allowed in $SCHEMA_PREFIX; do
    if [[ "$schema" == "$allowed" ]]; then return 0; fi
  done
  return 1
}

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
INV2_SKIPPED_BY_SCHEMA_PREFIX=0
for st in "${INV2_CANDIDATES[@]}"; do
  schema="${st%%.*}"
  tbl="${st##*.}"

  # Codex iter-2 P1/schemaPrefixUnused absorb: filter candidates.
  if ! filter_by_schema_prefix "$schema"; then
    INV2_SKIPPED_BY_SCHEMA_PREFIX=$((INV2_SKIPPED_BY_SCHEMA_PREFIX + 1))
    continue
  fi

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
    elif [[ -n "${DERIVED_PARENT_FK[$st]:-}" ]]; then
      # Codex iter-2 P1/derivedTenantKey + iter-3 P1/parentTenantFallback absorb:
      # parent join check. Format: <fk_col>|<parent_schema>.<parent_tbl>|<parent_pk>
      # Parent tenant key fallback chain: org_id → tenant_id (matches child
      # table fallback chain above).
      derived_spec="${DERIVED_PARENT_FK[$st]}"
      fk_col="${derived_spec%%|*}"
      rest="${derived_spec#*|}"
      parent_st="${rest%%|*}"
      parent_pk="${rest##*|}"
      parent_schema="${parent_st%%.*}"
      parent_tbl="${parent_st##*.}"
      parent_tenant_col=""
      if column_exists "$schema" "$tbl" "$fk_col" && table_exists "$parent_schema" "$parent_tbl"; then
        if column_exists "$parent_schema" "$parent_tbl" "org_id"; then
          parent_tenant_col="org_id"
        elif column_exists "$parent_schema" "$parent_tbl" "tenant_id"; then
          parent_tenant_col="tenant_id"
        fi
      fi
      if [[ -n "$parent_tenant_col" ]]; then
        tenant_key="\"derived:$fk_col -> $parent_st.$parent_tenant_col\""
        null_count=$(qry_int "SELECT count(*) FROM \"$schema\".\"$tbl\" c LEFT JOIN \"$parent_schema\".\"$parent_tbl\" p ON c.$fk_col = p.$parent_pk WHERE p.$parent_tenant_col IS NULL")
      else
        status="no_tenant_key_column"
        INV2_NO_KEY_COUNT=$((INV2_NO_KEY_COUNT + 1))
      fi
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

# Codex iter-4 P1/endpointCoverage absorb: if endpoint_admin_service schema
# is included in --schema-prefix, at least ONE endpoint table must be
# discovered, otherwise we flag OBSERVATION_INSUFFICIENT downstream. Counts
# discovered endpoint_admin_service.* tables specifically.
INV2_ENDPOINT_DISCOVERED=0
if filter_by_schema_prefix "endpoint_admin_service"; then
  for st in "${INV2_CANDIDATES[@]}"; do
    schema="${st%%.*}"
    tbl="${st##*.}"
    if [[ "$schema" == "endpoint_admin_service" ]] && table_exists "$schema" "$tbl"; then
      INV2_ENDPOINT_DISCOVERED=$((INV2_ENDPOINT_DISCOVERED + 1))
    fi
  done
fi

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
INV3_NOTIFY_INTENT_SCHEMA="notify"
INV3_NOTIFY_INTENT_TABLE="notification_intent"
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
  # Codex iter-3 P0/inv3DerivedJoin absorb: delivery tenant column is on
  # parent (notify.notification_intent.org_id), reached via intent_id FK.
  # Fall back to direct delivery.org_id only if the parent path is unusable.
  TENANT_PATH=""
  TENANT_PROBE_SQL=""
  if column_exists "$INV3_NOTIFY_DELIVERY_SCHEMA" "$INV3_NOTIFY_DELIVERY_TABLE" "intent_id" \
     && table_exists "$INV3_NOTIFY_INTENT_SCHEMA" "$INV3_NOTIFY_INTENT_TABLE" \
     && column_exists "$INV3_NOTIFY_INTENT_SCHEMA" "$INV3_NOTIFY_INTENT_TABLE" "org_id" \
     && column_exists "$INV3_NOTIFY_INTENT_SCHEMA" "$INV3_NOTIFY_INTENT_TABLE" "intent_id"; then
    TENANT_PATH="derived: delivery.intent_id -> notification_intent.org_id"
    TENANT_PROBE_SQL="LEFT JOIN \"$INV3_NOTIFY_INTENT_SCHEMA\".\"$INV3_NOTIFY_INTENT_TABLE\" i ON d.intent_id = i.intent_id WHERE d.$PROV_COL IS NOT NULL AND i.org_id IS NULL"
  elif column_exists "$INV3_NOTIFY_DELIVERY_SCHEMA" "$INV3_NOTIFY_DELIVERY_TABLE" "org_id"; then
    TENANT_PATH="direct: delivery.org_id"
    TENANT_PROBE_SQL="WHERE d.$PROV_COL IS NOT NULL AND d.org_id IS NULL"
  elif column_exists "$INV3_NOTIFY_DELIVERY_SCHEMA" "$INV3_NOTIFY_DELIVERY_TABLE" "tenant_id"; then
    TENANT_PATH="direct: delivery.tenant_id"
    TENANT_PROBE_SQL="WHERE d.$PROV_COL IS NOT NULL AND d.tenant_id IS NULL"
  fi
  if [[ -n "$PROV_COL" && -n "$TENANT_PROBE_SQL" ]]; then
    INV3_CALLBACK_ORPHAN=$(qry_int "SELECT count(*) FROM \"$INV3_NOTIFY_DELIVERY_SCHEMA\".\"$INV3_NOTIFY_DELIVERY_TABLE\" d $TENANT_PROBE_SQL")
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
# Codex iter-4 P1/endpointCoverage absorb: if endpoint_admin_service schema
# was requested but zero endpoint tables discovered, flag insufficient.
# Notify-only audit cannot reach CLEAN if endpoint coverage demanded.
if filter_by_schema_prefix "endpoint_admin_service" && [[ "$INV2_ENDPOINT_DISCOVERED" -lt 1 ]]; then
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
      "violation_count": ${INV2_FAIL_COUNT},
      "skipped_by_schema_prefix": ${INV2_SKIPPED_BY_SCHEMA_PREFIX},
      "endpoint_discovered_count": ${INV2_ENDPOINT_DISCOVERED}
    },
    "inv3_callback_correlation_orphan": {
      "status": "${INV3_STATUS}",
      "tenant_path": "${TENANT_PATH:-}",
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
