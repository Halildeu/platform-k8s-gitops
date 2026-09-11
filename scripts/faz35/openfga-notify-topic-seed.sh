#!/usr/bin/env bash
# Faz 35 ES-301b (platform-backend#1153): seed OpenFGA receive grants for a notification
# topic from a tuples JSON, then verify allow/deny — the data-driven form of
# scripts/faz24/openfga-meeting-action-notify-seed.sh with the allowed relation–subject–object
# triples read from the JSON's own `topics` / `templates` declaration instead of a
# hard-coded meeting regex.
#
# Runs ON aiserver. OpenFGA is reached through a pod that has curl (default
# deploy/meeting-service); store and model ids come from the permission-service pod env
# (ERP_OPENFGA_STORE_ID / ERP_OPENFGA_MODEL_ID — the shared erp-stage store the
# orchestrator's eligibility check consults), never from a flag or a file.
#
# Single source of truth: the JSON given as $1.
#   - `.topics[]`, `.templates[]` → the only object ids this run may touch.
#   - `.tuples[]`       → per-tuple writes (already-exists 400/409 = idempotent OK).
#   - `.smoke_checks[]` → /check assertions {user, relation, object, expect_allowed}.
#
# Fail-closed: platform-test only; no wildcard subject; every tuple must be one of
#   subscriber:<id>              can_receive  notification_topic:<declared topic>
#   notification_topic:<topic>   topic        template:<declared template>
# and every smoke check must match. A leftover `__SECOND_TIER__` placeholder (filled in from
# the persona script's reported id) refuses the run.
#
# Usage (on aiserver):
#   ./scripts/faz35/openfga-notify-topic-seed.sh bootstrap/openfga/faz35-ethics-escalation-notify-tuples.json
set -euo pipefail
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
info() { printf '\033[1;32m[info]\033[0m %s\n'  "$*"; }

TUPLES_JSON="${1:?usage: $0 <tuples.json>}"
[ -f "$TUPLES_JSON" ] || { err "tuples JSON not found: $TUPLES_JSON"; exit 1; }
command -v jq >/dev/null 2>&1 || { err "jq not found on host"; exit 1; }
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"
POD_DEPLOY="${POD_DEPLOY:-deploy/meeting-service}"
STORE_POD="${STORE_POD:-deploy/permission-service}"
OPENFGA_BASE="${OPENFGA_BASE:-http://openfga:8080}"
KE="kubectl --context ${KUBE_CONTEXT} -n ${KUBE_NS}"

# --- INVARIANT GUARD (ADR-0041 §4 — machine-enforced, fail-closed) ---
case "$KUBE_NS" in
  platform-test) : ;;
  *) err "ADR-0041 invariant: seed is platform-test only (KUBE_NS=${KUBE_NS} refused)"; exit 1 ;;
esac
if grep -q '__SECOND_TIER__' "$TUPLES_JSON"; then
  err "placeholder __SECOND_TIER__ still present — run provision-test-ethics-escalation-recipient.sh first"; exit 1
fi
jq -e '(.topics|type)=="array" and (.topics|length)>0 and (.templates|type)=="array" and (.templates|length)>0' "$TUPLES_JSON" >/dev/null \
  || { err "JSON must declare non-empty .topics and .templates"; exit 1; }
if jq -e '[(.tuples // [])[].user, (.smoke_checks // [])[].user] | any(endswith(":*") or startswith("user:"))' "$TUPLES_JSON" >/dev/null; then
  err "invariant: wildcard or user:-typed subject forbidden"; exit 1
fi
# Every tuple must be one of the two allowed triple shapes, bound to the declared objects.
if jq -e '
  (.topics) as $t | (.templates) as $m |
  [ .tuples[] |
    (.object|ltrimstr("notification_topic:")) as $topicObj |
    (.user|ltrimstr("notification_topic:")) as $topicSubj |
    (.object|ltrimstr("template:")) as $templateObj |
    ( .relation=="can_receive"
      and (.user|test("^subscriber:[0-9]+$"))
      and (.object|startswith("notification_topic:"))
      and (($t|index($topicObj))!=null) )
    or
    ( .relation=="topic"
      and (.user|startswith("notification_topic:"))
      and (($t|index($topicSubj))!=null)
      and (.object|startswith("template:"))
      and (($m|index($templateObj))!=null) )
  ] | all | not' "$TUPLES_JSON" >/dev/null; then
  err "invariant: a tuple is outside the allowed shapes (numeric subscriber can_receive declared topic | declared topic → declared template)"; exit 1
fi
if jq -e '[.smoke_checks[] | .relation=="can_receive" and (.object|test("^template:"))] | all | not' "$TUPLES_JSON" >/dev/null; then
  err "invariant: smoke checks must ask can_receive on a template (the relation the orchestrator checks)"; exit 1
fi
info "invariant guard: PASS (platform-test, no wildcard, $(jq -r '.topics|join(",")' "$TUPLES_JSON") / $(jq -r '.templates|join(",")' "$TUPLES_JSON") only)"

# --- store/model from the permission-service pod env (fail-closed if absent) ---
SID=$($KE exec "$STORE_POD" -- env 2>/dev/null | grep '^ERP_OPENFGA_STORE_ID=' | cut -d= -f2 | tr -d '\r')
MID=$($KE exec "$STORE_POD" -- env 2>/dev/null | grep '^ERP_OPENFGA_MODEL_ID=' | cut -d= -f2 | tr -d '\r')
[ -n "$SID" ] && [ -n "$MID" ] || { err "STORE/MODEL missing from ${STORE_POD} env"; exit 1; }
info "STORE_ID=${SID:0:12}...  MODEL_ID=${MID:0:12}...  (from ${STORE_POD})"
pod_post() { # $1=endpoint (body on stdin)
  $KE exec -i "$POD_DEPLOY" -- curl -s -w '\n%{http_code}' \
    -X POST "${OPENFGA_BASE}/stores/${SID}/$1" -H "Content-Type: application/json" -d @-
}
[ "$($KE exec "$POD_DEPLOY" -- sh -c 'command -v curl >/dev/null 2>&1 && echo OK || echo NO')" = "OK" ] \
  || { err "curl not available in ${POD_DEPLOY}"; exit 1; }

# --- 1. SEED (per-tuple, idempotent) ---
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
      else err "  write FAILED (HTTP $code) ${u} ${r} ${o}: ${body}"; exit 1; fi ;;
    *) err "  write FAILED (HTTP $code) ${u} ${r} ${o}: ${body}"; exit 1 ;;
  esac
done < <(jq -r '.tuples[] | [.user, .relation, .object] | @tsv' "$TUPLES_JSON")
info "Seed done: ${written} written, ${existed} already-existed"

# --- 2. VERIFY (effective authorization after the write) ---
rc=0
while IFS=$'\t' read -r u r o e; do
  [ -n "$u" ] || continue
  payload=$(jq -nc --arg mid "$MID" --arg u "$u" --arg r "$r" --arg o "$o" \
    '{authorization_model_id: $mid, tuple_key: {user: $u, relation: $r, object: $o}}')
  out=$(printf '%s' "$payload" | pod_post check)
  code="${out##*$'\n'}"; body="${out%$'\n'*}"
  if [ "$code" != "200" ]; then err "  /check HTTP $code for ${u} ${r} ${o}: ${body}"; rc=1; continue; fi
  allowed=$(printf '%s' "$body" | jq -r '.allowed // false')
  if [ "$allowed" = "$e" ]; then info "  PASS ${u} ${r} ${o} → allowed=${allowed}"; else err "  FAIL ${u} ${r} ${o} → allowed=${allowed} (expected ${e})"; rc=1; fi
done < <(jq -r '.smoke_checks[] | [.user, .relation, .object, (.expect_allowed|tostring)] | @tsv' "$TUPLES_JSON")
[ "$rc" -eq 0 ] || { err "Smoke verification FAILED"; exit 1; }
info "All ${TUPLES_JSON##*/} smoke_checks PASS"
