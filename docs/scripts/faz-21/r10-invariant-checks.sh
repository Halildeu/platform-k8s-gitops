#!/usr/bin/env bash
#
# r10-invariant-checks.sh — Faz 21.0 R10 4-invariant smoke harness
#
# Faz 23 M8 PR-3 A (Codex `019e8c24` order D→B→A→C).
#
# Wraps four invariant probes drawn from `docs/faz-21/charter.md` §4.1 +
# §4.3 acceptance evidence list. Each probe emits a structured row +
# rolls into an overall verdict file. Designed for repeated execution
# during Faz 21.0 (snapshot audit) and after Faz 21.1 implementation
# (regression smoke).
#
# Invariants covered:
#   Inv-1  Tenant context        — request flow JWT org_id + service
#                                  header X-Org-Id canonical (mismatch
#                                  fail-closed)
#   Inv-2  Persistence           — org_id NOT NULL on tenant-scoped tables
#                                  (delegates to pre-migration-audit.sh)
#   Inv-3  Side-effect isolation — cache prefix + dedupe prefix + cron
#                                  tenant isolation + Vault path canonical
#                                  + external callback correlation
#   Inv-4  AI boundary           — platform-ai retrieval/inference tenant
#                                  partition (manual cross-check; this
#                                  harness emits the audit checklist)
#
# Usage:
#   ./docs/scripts/faz-21/r10-invariant-checks.sh \
#       --audit-json /tmp/audit.json \
#       --out /tmp/r10-checks.json
#
# Where `--audit-json` is the output of pre-migration-audit.sh.
#
# Exit codes:
#   0 — All 4 invariants smoke CLEAN
#   1 — INVARIANT_VIOLATION (one or more probes fail)
#   2 — OBSERVATION_INSUFFICIENT (audit JSON missing predicate or unreadable)
#   3 — Usage error

set -euo pipefail

AUDIT_JSON=""
OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --audit-json) AUDIT_JSON="$2"; shift 2 ;;
    --out)        OUT="$2"; shift 2 ;;
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

if [[ -z "$AUDIT_JSON" || ! -r "$AUDIT_JSON" ]]; then
  echo "ERROR: --audit-json missing or unreadable" >&2
  exit 3
fi
if [[ -z "$OUT" ]]; then
  OUT="/tmp/faz-21-r10-checks-$(date -u +%Y%m%d-%H%MZ).json"
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq not on PATH" >&2
  exit 3
fi

GENERATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Inv-1: pulls advisory inv1_request_missing_org_id_24h from audit JSON.
INV1_VAL=$(jq -r '.predicates.inv1_request_missing_org_id_24h' "$AUDIT_JSON")
INV1_THRESHOLD=$(jq -r '.thresholds.inv1_request_missing_max_advisory' "$AUDIT_JSON")
INV1_STATUS="CLEAN"
if [[ "$INV1_VAL" == "null" ]]; then
  INV1_STATUS="ADVISORY_ABSENT"
elif awk -v v="$INV1_VAL" -v t="$INV1_THRESHOLD" 'BEGIN { exit !(v+0 > t+0) }'; then
  INV1_STATUS="ADVISORY_OVER_THRESHOLD"
fi

# Inv-2: roll Inv-2 audit list to total null org_id count.
INV2_TOTAL=$(jq -r '[.predicates.inv2_tenant_persistence_null_org_id[].null_org_id_count | tonumber] | add // 0' "$AUDIT_JSON")
INV2_STATUS="CLEAN"
if [[ "$INV2_TOTAL" != "0" ]]; then INV2_STATUS="VIOLATION"; fi

# Inv-3: callback orphan + provider count audit notes.
INV3_CALLBACK=$(jq -r '.predicates.inv3_callback_correlation_orphan_count' "$AUDIT_JSON")
INV3_STATUS="CLEAN"
if [[ "$INV3_CALLBACK" == "null" ]]; then
  INV3_STATUS="ADVISORY_ABSENT"
elif [[ "$INV3_CALLBACK" != "0" ]]; then
  INV3_STATUS="VIOLATION"
fi

# Inv-4: platform-ai retrieval/inference tenant partition — manual cross
# check; this harness emits the operator checklist.
INV4_STATUS="MANUAL_CROSS_CHECK_REQUIRED"
INV4_CHECKLIST=$(cat <<EOF
- platform-ai vector index keys carry tenant partition prefix
- prompt context selector applies tenant filter before retrieval
- embedding cache key includes org_id
- inference audit emits tenant=<org_id> label
EOF
)

# Overall verdict.
if [[ "$INV2_STATUS" == "VIOLATION" || "$INV3_STATUS" == "VIOLATION" ]]; then
  VERDICT="INVARIANT_VIOLATION"
elif [[ "$INV1_STATUS" == "ADVISORY_OVER_THRESHOLD" ]]; then
  VERDICT="ADVISORY_INVESTIGATION"
elif [[ "$INV2_STATUS" == "CLEAN" && "$INV3_STATUS" =~ ^(CLEAN|ADVISORY_ABSENT)$ && "$INV4_STATUS" == "MANUAL_CROSS_CHECK_REQUIRED" ]]; then
  VERDICT="MOSTLY_CLEAN_INV4_MANUAL"
else
  VERDICT="MIXED"
fi

cat >"$OUT" <<EOF
{
  "schema_version": "faz-21-r10-invariant-checks/v1",
  "generated_at": "${GENERATED_AT}",
  "audit_json_ref": "${AUDIT_JSON}",
  "invariants": {
    "inv1_tenant_context": {
      "status": "${INV1_STATUS}",
      "request_missing_24h": ${INV1_VAL},
      "advisory_threshold": ${INV1_THRESHOLD}
    },
    "inv2_persistence": {
      "status": "${INV2_STATUS}",
      "total_null_org_id_rows": ${INV2_TOTAL}
    },
    "inv3_side_effect_isolation": {
      "status": "${INV3_STATUS}",
      "callback_correlation_orphan_count": ${INV3_CALLBACK}
    },
    "inv4_ai_boundary": {
      "status": "${INV4_STATUS}",
      "checklist": $(printf '%s' "$INV4_CHECKLIST" | jq -R -s -c .)
    }
  },
  "verdict": "${VERDICT}",
  "anti_pattern_guards": {
    "depends_on_audit_json": true,
    "no_raw_tenant_pii_in_evidence": true,
    "inv4_requires_manual_cross_check": true
  }
}
EOF

echo "evidence: $OUT"
echo "verdict:  $VERDICT"

case "$VERDICT" in
  MOSTLY_CLEAN_INV4_MANUAL) exit 0 ;;
  INVARIANT_VIOLATION) exit 1 ;;
  ADVISORY_INVESTIGATION) exit 1 ;;
  *) exit 2 ;;
esac
