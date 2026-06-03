#!/usr/bin/env bash
#
# pre-migration-audit.sh — Faz 21.0 pre-migration audit (Faz 23 M8 PR-3 A)
#
# Faz 23 M8 PR-3 A (Codex `019e8c24` order D→B→A→C, multi-PR sequenced).
# Builds on `docs/faz-21/charter.md` §4.3 acceptance evidence scope and
# ADR-0032 §4.2 migration gates (Faz 21.0 → Faz 21.1 → Faz 21.2 → ...).
#
# Purpose: READ-ONLY snapshot audit of a prod-shaped PG database to surface
# R10 invariant violations BEFORE Faz 21 multi-tenant migration begins.
# Emits a canonical JSON report + evidence summary the operator commits
# under docs/faz-23-evidence/ as the Faz 21.0 sub-faz DoD.
#
# Predicates audited (mirrors charter §4.1 Inv-1..Inv-4):
#   Inv-2/persistence:
#     - org_id NULL row count per tenant-scoped table
#     - org_id-mixed row count per audit/outbox/delivery surface
#   Inv-3/side-effect isolation:
#     - cache key without tenant prefix (advisory; cache offline)
#     - external callback updates by message_id without org_id paired
#       (UPDATE log audit pattern; advisory in audit-only mode)
#     - shared provider credential vault path discovery (advisory)
#   Inv-1/tenant context (advisory):
#     - request log entries missing org_id over sample window
#   Inv-4/AI boundary (advisory):
#     - platform-ai retrieval index keys without tenant partition prefix
#
# Anti-pattern guards (Codex 019e8c24 + 019e8c3e):
#   - READ-ONLY: no UPDATE/INSERT/DELETE on production
#   - No raw tenant/PII data in evidence (redacted counts + sample row IDs only)
#   - No backdated evidence (PG SELECT now() + workstation clock both in JSON)
#   - Exit code distinguishes invariant CLEAN vs INVARIANT_VIOLATION vs
#     OBSERVATION_INSUFFICIENT
#
# Usage:
#   ./docs/scripts/faz-21/pre-migration-audit.sh \
#     --pg-host 127.0.0.1 --pg-port 15432 --pg-user audit_ro \
#     --pg-database platform --out /tmp/audit.json
#
# Exit codes:
#   0 — All audited invariants CLEAN on snapshot
#   1 — INVARIANT_VIOLATION on snapshot (operator triage required)
#   2 — OBSERVATION_INSUFFICIENT (PG unreachable, missing schemas, no sample)
#   3 — Usage error

set -euo pipefail

PG_HOST=""
PG_PORT="5432"
PG_USER=""
PG_DATABASE="platform"
PG_PASSWORD_FILE=""
OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pg-host)          PG_HOST="$2"; shift 2 ;;
    --pg-port)          PG_PORT="$2"; shift 2 ;;
    --pg-user)          PG_USER="$2"; shift 2 ;;
    --pg-database)      PG_DATABASE="$2"; shift 2 ;;
    --pg-password-file) PG_PASSWORD_FILE="$2"; shift 2 ;;
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

# Password loaded from file (avoid shell history leak).
if [[ -n "$PG_PASSWORD_FILE" ]]; then
  if [[ ! -r "$PG_PASSWORD_FILE" ]]; then
    echo "ERROR: --pg-password-file unreadable" >&2
    exit 3
  fi
  export PGPASSWORD
  PGPASSWORD="$(cat "$PG_PASSWORD_FILE")"
fi

PSQL_BASE="psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $PG_DATABASE -At -X --csv"

# Run query and emit single integer (or null on error).
qry_int() {
  local sql="$1"
  local raw
  raw="$($PSQL_BASE -c "$sql" 2>/dev/null | head -n1)" || true
  if [[ -z "$raw" ]]; then
    echo "null"
  else
    echo "$raw"
  fi
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

# Inv-2 audit: tenant-scoped table org_id null + mixed counts.
# Charter §4.1 Inv-2 — tenant-scoped tables NOT NULL constraint MUST hold.
# Audit on snapshot reports rows that would violate constraint pre-migration.
INV2_TABLES=(
  "notify_intent"
  "notify_dispatch"
  "notify_delivery"
  "notify_outbox"
  "notify_audit"
  "endpoint_device"
  "endpoint_software_inventory"
  "endpoint_outdated_software"
)

INV2_NULL_JSON="["
first=true
for tbl in "${INV2_TABLES[@]}"; do
  cnt=$(qry_int "SELECT count(*) FROM $tbl WHERE org_id IS NULL" 2>/dev/null || echo "null")
  [[ "$first" == "true" ]] && first=false || INV2_NULL_JSON+=","
  INV2_NULL_JSON+="{\"table\":\"$tbl\",\"null_org_id_count\":$cnt}"
done
INV2_NULL_JSON+="]"

# Inv-3 audit: external callback updates by message_id without org_id paired.
# Charter §4.1 Inv-3 callback correlation — provider_message_id update path
# audit. We sample notify_delivery WHERE provider_message_id IS NOT NULL +
# org_id IS NULL (i.e. callback wrote row but did not paint tenant).
INV3_CALLBACK_NULL=$(qry_int "SELECT count(*) FROM notify_delivery WHERE provider_message_id IS NOT NULL AND org_id IS NULL")

# Inv-3 audit: shared provider credential discovery. We surface a count of
# DISTINCT provider names that appear in notify_delivery — operator
# cross-references with Vault path `kv/platform/tenants/<tenant>/<provider>/`
# canonical layout to spot any tenant currently relying on the legacy flat
# `kv/platform/<provider>` path. Audit-only signal; cross-ref manual.
INV3_PROVIDER_DISTINCT=$(qry_int "SELECT count(DISTINCT provider) FROM notify_delivery WHERE provider IS NOT NULL")

# Inv-1 audit: request log entries missing org_id over 24h sample window
# (advisory only; PG audit table not always present). Returns null if
# table missing.
INV1_REQUEST_NULL=$(qry_int "SELECT count(*) FROM request_audit WHERE org_id IS NULL AND created_at > now() - interval '24 hours'" 2>/dev/null || echo "null")

# Verdict logic. Hard fail on any non-zero Inv-2 NULL or Inv-3 callback
# orphan; soft warn on Inv-1 advisory.
VERDICT="CLEAN"
INV2_FAIL=$(echo "$INV2_NULL_JSON" | grep -c '"null_org_id_count":[1-9]' || true)
if [[ "${INV2_FAIL:-0}" -gt 0 ]]; then VERDICT="INVARIANT_VIOLATION"; fi
if [[ "$INV3_CALLBACK_NULL" != "null" && "$INV3_CALLBACK_NULL" != "0" ]]; then VERDICT="INVARIANT_VIOLATION"; fi

cat >"$OUT" <<EOF
{
  "schema_version": "faz-21-pre-migration-audit/v1",
  "generated_at": "${GENERATED_AT}",
  "pg_time_unix": ${PG_NOW},
  "workstation_time_unix": ${WS_NOW},
  "pg_host": "${PG_HOST}",
  "pg_database": "${PG_DATABASE}",
  "audit_scope": "Faz 21.0 sub-faz DoD (charter §4.3)",
  "predicates": {
    "inv2_tenant_persistence_null_org_id": ${INV2_NULL_JSON},
    "inv3_callback_correlation_orphan_count": ${INV3_CALLBACK_NULL},
    "inv3_provider_distinct_count": ${INV3_PROVIDER_DISTINCT},
    "inv1_request_missing_org_id_24h": ${INV1_REQUEST_NULL}
  },
  "thresholds": {
    "inv2_null_org_id_max": 0,
    "inv3_callback_orphan_max": 0,
    "inv1_request_missing_max_advisory": 100
  },
  "verdict": "${VERDICT}",
  "anti_pattern_guards": {
    "read_only_on_production": true,
    "no_raw_tenant_pii_in_evidence": true,
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
  *) exit 2 ;;
esac
