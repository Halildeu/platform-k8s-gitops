#!/usr/bin/env bash
# Faz 24 Görevler dilim-4b: seed OpenFGA receive grants for the meeting action assignment
# notifications (template→topic binding + subscriber can_receive) + verify allow/deny.
# UPPERCASE object ids (ADR-0041 §5 Option A, Codex 019ed603): the OpenFGA module
# object id == permission-service catalog key == role_permissions.permission_key ==
# services' @RequireModule literal (MeetingAuthz/TranscriptAuthz.MODULE). The MODULE
# write path applies no case transform; staged re-seed runbook (additive, NOT
# delete-first): docs/runbooks/RB-faz24-mt-uppercase-reseed.md.
#
# Runs ON staging-sw. OpenFGA reached via meeting-service pod (has curl); JSON
# payloads piped via stdin (-d @-) to avoid quote-nesting. jq runs on the HOST
# (host has jq; OpenFGA/meeting pods do not).
#
# Single source of truth: bootstrap/openfga/meeting-action-notify-tuples.json.
#   - `.tuples[]`       → write payload (no hardcoded tuple list in this script).
#   - `.smoke_checks[]` → allow/deny assertions {user,relation,object,expect_allowed}.
#
# Fail-closed (Codex cross-AI REVISE Must-Fix 2; emsal scripts/d35-3/openfga-
# access-tuple-seed.sh): per-tuple write asserts HTTP 200/201 (already-exists
# 400/409 with "already exist" body = idempotent OK), every /check asserts the
# expected allowed value; any other mismatch → exit non-zero. Idempotent + re-runnable.
#
# Usage (on staging-sw, from a repo checkout OR with TUPLES_JSON pointing at the file):
#   ./scripts/faz24/openfga-meeting-action-notify-seed.sh
#   TUPLES_JSON=/tmp/meeting-action-notify-tuples.json ./...-seed.sh
#
# Env contract:
#   TUPLES_JSON   — optional; path to the tuples JSON. Default: resolved relative
#                   to this script (../../bootstrap/openfga/meeting-action-notify-tuples.json).
#   KUBE_CONTEXT  — optional; default k3d-test.
#   KUBE_NS       — optional; default platform-test.
#   POD_DEPLOY    — optional; default deploy/meeting-service (pod with curl + OpenFGA reach).
#   OPENFGA_BASE  — optional; default http://openfga:8080 (in-cluster service DNS).
set -euo pipefail

err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n'  "$*" >&2; }
info() { printf '\033[1;32m[info]\033[0m %s\n'  "$*"; }

# --- resolve tuples JSON path (single source of truth) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUPLES_JSON="${TUPLES_JSON:-${SCRIPT_DIR}/../../bootstrap/openfga/meeting-action-notify-tuples.json}"
[ -f "$TUPLES_JSON" ] || { err "tuples JSON not found: $TUPLES_JSON (set TUPLES_JSON env)"; exit 1; }
command -v jq >/dev/null 2>&1 || { err "jq not found on host (required to read $TUPLES_JSON)"; exit 1; }

KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"
POD_DEPLOY="${POD_DEPLOY:-deploy/meeting-service}"
OPENFGA_BASE="${OPENFGA_BASE:-http://openfga:8080}"
KE="kubectl --context ${KUBE_CONTEXT} -n ${KUBE_NS}"

# --- INVARIANT GUARD (ADR-0041 §4 — machine-enforced, fail-closed) ---
# Test-only bootstrap exception (DD-EA-2): this script NEVER seeds a prod realm,
# never writes a wildcard subject, and only touches the Faz 24 module objects.
# Prod tuple-writing is permission-service's job (role/granule + assignment →
# TupleSyncService → OpenFGA). Refuse loudly if any invariant is violated.
case "$KUBE_NS" in
  platform-test) : ;;
  *) err "ADR-0041 invariant: seed is platform-test only (KUBE_NS=${KUBE_NS} refused — prod/other realm seed forbidden)"; exit 1 ;;
esac
if jq -e '[(.tuples // [])[].user, (.smoke_checks // [])[].user] | any(endswith(":*"))' "$TUPLES_JSON" >/dev/null 2>&1; then
  err "ADR-0041 invariant: wildcard subject forbidden in ${TUPLES_JSON##*/}"; exit 1
fi
if jq -e '[(.tuples // [])[].user, (.smoke_checks // [])[].user] | any(test("^(subscriber:[0-9]+|notification_topic:meeting\\.action\\.(assigned|reassigned))$") | not)' "$TUPLES_JSON" >/dev/null 2>&1; then
  err "invariant: subjects must be numeric subscriber ids or the two meeting.action topics in ${TUPLES_JSON##*/}"; exit 1
fi
if jq -e '[(.tuples // [])[].object] | any(test("^(template|notification_topic):meeting\\.action\\.(assigned|reassigned)$") | not)' "$TUPLES_JSON" >/dev/null 2>&1; then
  err "invariant: only the two meeting.action templates/topics may be written from ${TUPLES_JSON##*/}"; exit 1
fi
info "invariant guard: PASS (platform-test, no wildcard subject, meeting.action templates/topics only)"

# --- store/model from the running pod env (fail-closed if absent) ---
SID=$($KE exec "$POD_DEPLOY" -- env 2>/dev/null | grep '^ERP_OPENFGA_STORE_ID=' | cut -d= -f2 | tr -d '\r')
MID=$($KE exec "$POD_DEPLOY" -- env 2>/dev/null | grep '^ERP_OPENFGA_MODEL_ID=' | cut -d= -f2 | tr -d '\r')
info "STORE_ID=${SID:0:12}...  MODEL_ID=${MID:0:12}..."
[ -n "$SID" ] && [ -n "$MID" ] || { err "STORE/MODEL missing from ${POD_DEPLOY} env"; exit 1; }

# --- curl helper: POST <endpoint> with body on stdin; prints "<body>\n<http_code>" ---
pod_post() { # $1=endpoint  (body on stdin)
  $KE exec -i "$POD_DEPLOY" -- curl -s -w '\n%{http_code}' \
    -X POST "${OPENFGA_BASE}/stores/${SID}/$1" \
    -H "Content-Type: application/json" -d @-
}

# --- curl pre-flight ---
if [ "$($KE exec "$POD_DEPLOY" -- sh -c 'command -v curl >/dev/null 2>&1 && echo OK || echo NO')" != "OK" ]; then
  err "curl not available in ${POD_DEPLOY}"; exit 1
fi

# ============================================================================
# 1. SEED — write each .tuples[] INDIVIDUALLY (idempotent against live OpenFGA).
#    LIVE behaviour (verified 2026-06-17): OpenFGA returns HTTP 400
#    "cannot write a tuple which already exists" for a duplicate (NOT 409), and a
#    BATCH write fails atomically on ANY duplicate (leaving missing tuples
#    unwritten). So we write per-tuple and treat an already-exists 400/409 as
#    idempotent success; any OTHER non-2xx is fail-closed (exit 1).
# ============================================================================
NTUP=$(jq '.tuples | length' "$TUPLES_JSON")
info "Seeding ${NTUP} tuples individually from ${TUPLES_JSON##*/} (idempotent; already-exists = OK)"
written=0; existed=0
while IFS=$'\t' read -r u r o; do
  [ -n "$u" ] || continue
  payload=$(jq -nc --arg mid "$MID" --arg u "$u" --arg r "$r" --arg o "$o" \
    '{authorization_model_id: $mid, writes: {tuple_keys: [{user:$u, relation:$r, object:$o}]}}')
  out=$(printf '%s' "$payload" | pod_post write)
  code="${out##*$'\n'}"; body="${out%$'\n'*}"
  case "$code" in
    200|201) info "  wrote  ${u} ${r} ${o}"; written=$((written+1)) ;;
    400|409)
      if printf '%s' "$body" | grep -qi 'already exist'; then
        info "  exists ${u} ${r} ${o} (idempotent)"; existed=$((existed+1))
      else
        err "  write FAILED (HTTP $code) ${u} ${r} ${o}: ${body}"; exit 1
      fi ;;
    *) err "  write FAILED (HTTP $code) ${u} ${r} ${o}: ${body}"; exit 1 ;;
  esac
done < <(jq -r '.tuples[] | [.user, .relation, .object] | @tsv' "$TUPLES_JSON")
info "Seed done: ${written} written, ${existed} already-existed (idempotent)"

# ============================================================================
# 2. VERIFY — assert each .smoke_checks[] against /check (fail-closed)
# ============================================================================
check_one() { # user relation object expect_allowed
  local user="$1" relation="$2" object="$3" expect="$4"
  local payload out code body allowed
  payload=$(jq -nc \
    --arg mid "$MID" --arg u "$user" --arg r "$relation" --arg o "$object" \
    '{authorization_model_id: $mid, tuple_key: {user: $u, relation: $r, object: $o}}')
  out=$(printf '%s' "$payload" | pod_post check)
  code="${out##*$'\n'}"
  body="${out%$'\n'*}"
  if [ "$code" != "200" ]; then
    err "  /check HTTP $code for ${user} ${relation} ${object}: ${body}"
    return 1
  fi
  allowed=$(printf '%s' "$body" | jq -r '.allowed // false')
  if [ "$allowed" = "$expect" ]; then
    info "  PASS ${user} ${relation} ${object} → allowed=${allowed} (expect ${expect})"
    return 0
  fi
  err "  FAIL ${user} ${relation} ${object} → allowed=${allowed} (expected ${expect})"
  return 1
}

info "VERIFY $(jq '.smoke_checks | length' "$TUPLES_JSON") smoke_checks (authoritative synthetic allow/deny)"
rc=0
# read smoke_checks as tab-separated rows (stable; no subshell rc loss via process-sub)
while IFS=$'\t' read -r u r o e; do
  [ -n "$u" ] || continue
  check_one "$u" "$r" "$o" "$e" || rc=1
done < <(jq -r '.smoke_checks[] | [.user, .relation, .object, (.expect_allowed|tostring)] | @tsv' "$TUPLES_JSON")

if [ "$rc" -ne 0 ]; then
  err "Smoke verification FAILED — one or more allow/deny assertions did not match."
  exit 1
fi
info "All ${TUPLES_JSON##*/} smoke_checks PASS — meeting action assignment notifications can reach the seeded subscribers."
