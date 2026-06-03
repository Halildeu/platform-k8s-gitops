#!/usr/bin/env bash
#
# r10-invariant-checks.sh — Faz 21.0 R10 4-invariant smoke harness
#
# Codex iter-1 REVISE absorbed (Faz 23 M8 PR-3 A, thread 019e8c24):
#   - schema discovery delegated to pre-migration-audit.sh (v2)
#   - jq // 0 null-safe guards
#   - Inv-4 MANUAL_PENDING default exit 2; --inv4-verified flag opens exit 0
#   - schema_version stable string
#
# Wraps four invariant probes from `docs/faz-21/charter.md` §4.1 + §4.3.
# Designed for repeated execution during Faz 21.0 (snapshot audit) and
# after Faz 21.1 implementation (regression smoke).
#
# Usage:
#   ./docs/scripts/faz-21/r10-invariant-checks.sh \
#       --audit-json /tmp/audit.json \
#       --inv4-evidence /tmp/inv4-checklist.md \
#       --inv4-verified \
#       --out /tmp/r10-checks.json
#
# `--inv4-verified` MUST be present to receive exit 0
# (MOSTLY_CLEAN_INV4_VERIFIED). Without it, verdict is MANUAL_PENDING
# (exit 2) even if Inv-1/2/3 are CLEAN. This prevents operators or
# automation from claiming DoD met while Inv-4 AI boundary checklist
# remains open.
#
# Exit codes:
#   0 — MOSTLY_CLEAN_INV4_VERIFIED (Inv-1/2/3 CLEAN + Inv-4 verified)
#   1 — INVARIANT_VIOLATION (predicates fail) OR ADVISORY_INVESTIGATION
#   2 — MANUAL_PENDING (Inv-4 not verified) OR OBSERVATION_INSUFFICIENT
#   3 — Usage error

set -euo pipefail

AUDIT_JSON=""
INV4_EVIDENCE=""
INV4_VERIFIED=0
OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --audit-json)     AUDIT_JSON="$2"; shift 2 ;;
    --inv4-evidence)  INV4_EVIDENCE="$2"; shift 2 ;;
    --inv4-verified)  INV4_VERIFIED=1; shift 1 ;;
    --out)            OUT="$2"; shift 2 ;;
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

# Inv-1 advisory pull (null-safe).
INV1_STATUS=$(jq -r '.predicates.inv1_request_missing_advisory_24h.status' "$AUDIT_JSON")
INV1_COUNT=$(jq -r '.predicates.inv1_request_missing_advisory_24h.count' "$AUDIT_JSON")
INV1_THRESHOLD=$(jq -r '.thresholds.inv1_advisory_max // 100' "$AUDIT_JSON")
INV1_SMOKE="ADVISORY_ABSENT"
if [[ "$INV1_STATUS" == "DISCOVERED" ]]; then
  if awk -v v="$INV1_COUNT" -v t="$INV1_THRESHOLD" 'BEGIN { exit !(v+0 > t+0) }'; then
    INV1_SMOKE="ADVISORY_OVER_THRESHOLD"
  else
    INV1_SMOKE="CLEAN"
  fi
fi

# Inv-2 summary (null-safe).
# Codex iter-2 P0/inv2StatusSuffix absorb: previous form added
# `_WITH_NO_KEY_TABLES` suffix to INV2_SMOKE which broke the exact-match
# composite verdict ladder downstream (== "VIOLATION" missed
# `VIOLATION_WITH_NO_KEY_TABLES`). Now no_key tracked as separate boolean
# (INV2_HAS_NO_KEY); core status remains exact-match-safe.
INV2_VIOLATION=$(jq -r '.predicates.inv2_summary.violation_count // 0' "$AUDIT_JSON")
INV2_DISCOVERED=$(jq -r '.predicates.inv2_summary.discovered_count // 0' "$AUDIT_JSON")
INV2_NO_KEY=$(jq -r '.predicates.inv2_summary.no_tenant_key_count // 0' "$AUDIT_JSON")
INV2_SMOKE="CLEAN"
if [[ "$INV2_VIOLATION" != "0" ]]; then INV2_SMOKE="VIOLATION"; fi
if [[ "$INV2_DISCOVERED" -lt 2 ]]; then INV2_SMOKE="OBSERVATION_INSUFFICIENT"; fi
INV2_HAS_NO_KEY="false"
if [[ "$INV2_NO_KEY" -gt 0 ]]; then INV2_HAS_NO_KEY="true"; fi

# Inv-3 (null-safe).
INV3_STATUS=$(jq -r '.predicates.inv3_callback_correlation_orphan.status' "$AUDIT_JSON")
INV3_ORPHAN=$(jq -r '.predicates.inv3_callback_correlation_orphan.orphan_count' "$AUDIT_JSON")
INV3_SMOKE="OBSERVATION_INSUFFICIENT"
if [[ "$INV3_STATUS" == "DISCOVERED" ]]; then
  if [[ "$INV3_ORPHAN" == "0" ]]; then
    INV3_SMOKE="CLEAN"
  elif [[ "$INV3_ORPHAN" != "null" ]]; then
    INV3_SMOKE="VIOLATION"
  fi
fi

# Inv-4 manual cross-check — emits checklist + observes flag.
# Codex iter-1 P0/inv4Gate absorb: exit 0 only if --inv4-verified provided.
INV4_CHECKLIST=$(cat <<'EOF'
- platform-ai vector index keys carry tenant partition prefix
- prompt context selector applies tenant filter before retrieval
- embedding cache key includes org_id
- inference audit emits tenant=<org_id> label
EOF
)
INV4_STATUS="MANUAL_PENDING"
if [[ "$INV4_VERIFIED" == "1" ]]; then
  INV4_STATUS="MANUAL_VERIFIED"
fi

# Composite verdict.
if [[ "$INV2_SMOKE" == "VIOLATION" || "$INV3_SMOKE" == "VIOLATION" ]]; then
  VERDICT="INVARIANT_VIOLATION"
elif [[ "$INV1_SMOKE" == "ADVISORY_OVER_THRESHOLD" ]]; then
  VERDICT="ADVISORY_INVESTIGATION"
elif [[ "$INV2_SMOKE" == "OBSERVATION_INSUFFICIENT" || "$INV3_SMOKE" == "OBSERVATION_INSUFFICIENT" ]]; then
  VERDICT="OBSERVATION_INSUFFICIENT"
elif [[ "$INV4_STATUS" == "MANUAL_PENDING" ]]; then
  VERDICT="MANUAL_PENDING"
elif [[ "$INV4_STATUS" == "MANUAL_VERIFIED" ]]; then
  VERDICT="MOSTLY_CLEAN_INV4_VERIFIED"
else
  VERDICT="MIXED"
fi

INV4_EVIDENCE_JSON="null"
if [[ -n "$INV4_EVIDENCE" ]]; then
  INV4_EVIDENCE_JSON=$(printf '%s' "$INV4_EVIDENCE" | jq -R -s -c .)
fi

cat >"$OUT" <<EOF
{
  "schema_version": "faz-21-r10-invariant-checks/v2",
  "generated_at": "${GENERATED_AT}",
  "audit_json_ref": "${AUDIT_JSON}",
  "invariants": {
    "inv1_tenant_context": {
      "status": "${INV1_SMOKE}",
      "audit_status": "${INV1_STATUS}",
      "request_missing_24h": ${INV1_COUNT},
      "advisory_threshold": ${INV1_THRESHOLD}
    },
    "inv2_persistence": {
      "status": "${INV2_SMOKE}",
      "has_no_key_tables": ${INV2_HAS_NO_KEY},
      "discovered_count": ${INV2_DISCOVERED},
      "violation_count": ${INV2_VIOLATION},
      "no_tenant_key_count": ${INV2_NO_KEY}
    },
    "inv3_side_effect_isolation": {
      "status": "${INV3_SMOKE}",
      "audit_status": "${INV3_STATUS}",
      "callback_correlation_orphan_count": ${INV3_ORPHAN}
    },
    "inv4_ai_boundary": {
      "status": "${INV4_STATUS}",
      "checklist": $(printf '%s' "$INV4_CHECKLIST" | jq -R -s -c .),
      "evidence_ref": ${INV4_EVIDENCE_JSON}
    }
  },
  "verdict": "${VERDICT}",
  "scope_notes": {
    "inv3_full_test_requires_backend_integration": "Snapshot orphan count is a READ-ONLY analog; charter §4.3 callback isolation test (concurrent update + provider_message_id reuse) requires backend integration test, tracked separately."
  },
  "anti_pattern_guards": {
    "depends_on_audit_json": true,
    "no_raw_tenant_pii_in_evidence": true,
    "inv4_requires_manual_cross_check": true,
    "inv4_verified_flag_required_for_exit_0": true
  }
}
EOF

echo "evidence: $OUT"
echo "verdict:  $VERDICT"

case "$VERDICT" in
  MOSTLY_CLEAN_INV4_VERIFIED) exit 0 ;;
  INVARIANT_VIOLATION) exit 1 ;;
  ADVISORY_INVESTIGATION) exit 1 ;;
  MANUAL_PENDING) exit 2 ;;
  OBSERVATION_INSUFFICIENT) exit 2 ;;
  *) exit 2 ;;
esac
