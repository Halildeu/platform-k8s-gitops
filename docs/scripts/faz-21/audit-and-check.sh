#!/usr/bin/env bash
#
# audit-and-check.sh — Faz 21.0 audit + R10 invariant check single-command wrapper
#
# Faz 23 M8 PR-4 C (Codex `019e8c24` order D→B→A→C, last slice).
#
# Wraps the PR-3 A scripts (`pre-migration-audit.sh` + `r10-invariant-checks.sh`)
# under a single operator entry point. Replaces a 2-step manual sequence with
# one command that:
#
#   1. Runs `pre-migration-audit.sh` against the prod-shaped snapshot
#   2. If audit exit ∈ {0,1}, runs `r10-invariant-checks.sh` against the
#      audit JSON output (without `--inv4-verified` by default — operator
#      must opt in after manual cross-check)
#   3. Emits combined verdict + paths to both evidence files
#
# Anti-pattern guards (carried from PR-3 A):
#   - READ-ONLY (delegates to underlying scripts)
#   - PG password file mode 0400/0600 enforced (audit script)
#   - Inv-4 manual cross-check gated by `--inv4-verified` flag
#   - No backdated evidence
#
# Usage:
#   # Step 1 — initial audit + checks (Inv-4 NOT verified yet)
#   ./docs/scripts/faz-21/audit-and-check.sh \
#     --pg-host 127.0.0.1 --pg-port 15432 --pg-user audit_ro \
#     --pg-database platform --pg-password-file ~/.faz21-audit.pw \
#     --schema-prefix notify,endpoint_admin_service \
#     --out-dir /tmp/faz-21
#
#   # Operator performs Inv-4 cross-check (RB §4.4)
#   # ...
#
#   # Step 2 — re-run with --inv4-verified flag
#   ./docs/scripts/faz-21/audit-and-check.sh \
#     ...same args... \
#     --inv4-verified \
#     --inv4-evidence ~/inv4-checklist.md
#
# Exit codes (composite, mirrors r10-invariant-checks.sh ladder):
#   0 — MOSTLY_CLEAN_INV4_VERIFIED (audit CLEAN + checks pass + Inv-4 verified)
#   1 — INVARIANT_VIOLATION or ADVISORY_INVESTIGATION
#   2 — MANUAL_PENDING (Inv-4 not verified) or OBSERVATION_INSUFFICIENT
#   3 — Usage error

set -euo pipefail

PG_HOST=""
PG_PORT="5432"
PG_USER=""
PG_DATABASE="platform"
PG_PASSWORD_FILE=""
SCHEMA_PREFIX="notify,endpoint_admin_service,public"
OUT_DIR=""
INV4_VERIFIED=0
INV4_EVIDENCE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pg-host)          PG_HOST="$2"; shift 2 ;;
    --pg-port)          PG_PORT="$2"; shift 2 ;;
    --pg-user)          PG_USER="$2"; shift 2 ;;
    --pg-database)      PG_DATABASE="$2"; shift 2 ;;
    --pg-password-file) PG_PASSWORD_FILE="$2"; shift 2 ;;
    --schema-prefix)    SCHEMA_PREFIX="$2"; shift 2 ;;
    --out-dir)          OUT_DIR="$2"; shift 2 ;;
    --inv4-verified)    INV4_VERIFIED=1; shift 1 ;;
    --inv4-evidence)    INV4_EVIDENCE="$2"; shift 2 ;;
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

if [[ -z "$OUT_DIR" ]]; then
  OUT_DIR="/tmp/faz-21-$(date -u +%Y%m%d-%H%MZ)"
fi
mkdir -p "$OUT_DIR"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUDIT_SH="$SCRIPT_DIR/pre-migration-audit.sh"
CHECKS_SH="$SCRIPT_DIR/r10-invariant-checks.sh"

for s in "$AUDIT_SH" "$CHECKS_SH"; do
  if [[ ! -x "$s" ]]; then
    echo "ERROR: required script not executable: $s" >&2
    exit 3
  fi
done

AUDIT_JSON="$OUT_DIR/pre-migration-audit.json"
CHECKS_JSON="$OUT_DIR/r10-invariant-checks.json"
SUMMARY_JSON="$OUT_DIR/summary.json"

echo "[1/2] Running pre-migration-audit.sh..."
AUDIT_ARGS=(
  --pg-host "$PG_HOST"
  --pg-port "$PG_PORT"
  --pg-user "$PG_USER"
  --pg-database "$PG_DATABASE"
  --schema-prefix "$SCHEMA_PREFIX"
  --out "$AUDIT_JSON"
)
if [[ -n "$PG_PASSWORD_FILE" ]]; then
  AUDIT_ARGS+=(--pg-password-file "$PG_PASSWORD_FILE")
fi

set +e
"$AUDIT_SH" "${AUDIT_ARGS[@]}"
AUDIT_EXIT=$?
set -e

echo "audit exit: $AUDIT_EXIT"

if [[ "$AUDIT_EXIT" == "2" || "$AUDIT_EXIT" == "3" ]]; then
  echo "[!] Audit returned $AUDIT_EXIT — skipping r10 checks."
  AUDIT_VERDICT=$(jq -r '.verdict // "UNKNOWN"' "$AUDIT_JSON" 2>/dev/null || echo "UNKNOWN")
  cat >"$SUMMARY_JSON" <<EOF
{
  "schema_version": "faz-21-audit-and-check/v1",
  "generated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "audit_json": "$AUDIT_JSON",
  "checks_json": null,
  "audit_exit": $AUDIT_EXIT,
  "audit_verdict": "$AUDIT_VERDICT",
  "checks_exit": null,
  "checks_verdict": null,
  "composite_verdict": "$AUDIT_VERDICT"
}
EOF
  echo "summary: $SUMMARY_JSON"
  exit "$AUDIT_EXIT"
fi

echo "[2/2] Running r10-invariant-checks.sh..."
CHECKS_ARGS=(
  --audit-json "$AUDIT_JSON"
  --out "$CHECKS_JSON"
)
if [[ "$INV4_VERIFIED" == "1" ]]; then
  CHECKS_ARGS+=(--inv4-verified)
fi
if [[ -n "$INV4_EVIDENCE" ]]; then
  CHECKS_ARGS+=(--inv4-evidence "$INV4_EVIDENCE")
fi

set +e
"$CHECKS_SH" "${CHECKS_ARGS[@]}"
CHECKS_EXIT=$?
set -e

echo "checks exit: $CHECKS_EXIT"

AUDIT_VERDICT=$(jq -r '.verdict' "$AUDIT_JSON")
CHECKS_VERDICT=$(jq -r '.verdict' "$CHECKS_JSON")

# Composite: checks_verdict carries the canonical outcome since it already
# integrates audit predicates. If audit verdict differs from checks
# verdict (rare — would mean checks downgraded the audit), report both.
COMPOSITE="$CHECKS_VERDICT"

cat >"$SUMMARY_JSON" <<EOF
{
  "schema_version": "faz-21-audit-and-check/v1",
  "generated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "audit_json": "$AUDIT_JSON",
  "checks_json": "$CHECKS_JSON",
  "audit_exit": $AUDIT_EXIT,
  "audit_verdict": "$AUDIT_VERDICT",
  "checks_exit": $CHECKS_EXIT,
  "checks_verdict": "$CHECKS_VERDICT",
  "composite_verdict": "$COMPOSITE",
  "anti_pattern_guards": {
    "delegates_to_pr3_a_scripts": true,
    "inv4_verified_explicit_flag": $([ "$INV4_VERIFIED" = "1" ] && echo true || echo false),
    "no_backdated_evidence": true
  }
}
EOF

echo ""
echo "=== Faz 21.0 audit + R10 checks summary ==="
echo "audit verdict:    $AUDIT_VERDICT (exit $AUDIT_EXIT)"
echo "checks verdict:   $CHECKS_VERDICT (exit $CHECKS_EXIT)"
echo "composite:        $COMPOSITE"
echo "audit JSON:       $AUDIT_JSON"
echo "checks JSON:      $CHECKS_JSON"
echo "summary JSON:     $SUMMARY_JSON"
echo ""

# Exit code mirrors checks.
exit "$CHECKS_EXIT"
