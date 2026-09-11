#!/usr/bin/env bash
# Faz 35 ES-301b (platform-backend#1153) acceptance driver — TEST cell, synthetic channel only.
#
# Files a synthetic report on speakup.acik.com (org …0003), moves its created_at 11 days into
# the past so the acknowledgement obligation is 4 days past its legal deadline (steps PT0S,P3D →
# levels 1 and 2 on the next sweep), triggers a sweep (rollout restart: initial delay PT1M),
# then reads the evidence chain: outbox rows → orchestrator intents/deliveries → inbox rows
# per tier. Prints ids and counts, never a secret or a narrative.
#
# Fixture note: the backdate is the only non-product mutation and it touches ONE synthetic
# case's timestamps; the live channel (…0001) is never written.
set -euo pipefail
set +x
PUBLIC_BASE="${PUBLIC_BASE:-https://speakup.acik.com}"
EDGE_ADDR="${EDGE_ADDR:-127.0.0.1}"
PUBLIC_GATE_USER="${PUBLIC_GATE_USER:-etik-test}"
PUBLIC_GATE_PASSWORD_FILE="${PUBLIC_GATE_PASSWORD_FILE:-/srv/platform/secrets/faz35-test/etik-speak-public-gate.password}"
PG_CONTAINER="${PG_CONTAINER:-platform-pg-test}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"
SYNTHETIC_ORG=00000000-0000-0000-0000-000000000003
FIRST_TIER="${FIRST_TIER:-11}"
SECOND_TIER="${SECOND_TIER:-33}"
BACKDATE_DAYS="${BACKDATE_DAYS:-11}"
WAIT_SECONDS="${WAIT_SECONDS:-420}"
[ "$KUBE_NS" = platform-test ] || { echo "FATAL: test-only" >&2; exit 1; }
[ "$PG_CONTAINER" = platform-pg-test ] || { echo "FATAL: test-only" >&2; exit 1; }
psql_e() { docker exec "$PG_CONTAINER" psql -U postgres -d ethics -At -c "$1"; }
psql_n() { docker exec "$PG_CONTAINER" psql -U postgres -d notify_db -At -c "$1"; }

# 1. Intake (public API, synthetic channel). accessSecret is random and discarded — the
#    reporter mailbox is not part of this acceptance.
secret=$(LC_ALL=C head -c 64 /dev/urandom | base64 | tr -d '/+=\n' | head -c 43)
body=$(python3 -c 'import json,sys; print(json.dumps({"mode":"ANONYMOUS","category":"WORKPLACE_CONDUCT","subject":"ES-301b eskalasyon kabul (sentetik)","description":"Sentetik kabul vakasi: SLA eskalasyon bildirimi ikinci kademe yonlendirmesi (platform-backend#1153). Gercek olay degildir.","locale":"tr-TR","accessSecret":sys.argv[1],"noticeVersion":"v1"}))' "$secret")
unset secret
gate_pw=$(sudo cat "$PUBLIC_GATE_PASSWORD_FILE")
before=$(psql_e "select coalesce(max(created_at)::text,'') from ethics_service.ethics_cases where org_id='$SYNTHETIC_ORG'")
resp=$(printf '%s' "$body" | curl -sS -k --resolve "${PUBLIC_BASE#https://}:443:$EDGE_ADDR" -u "$PUBLIC_GATE_USER:$gate_pw" \
  -H 'Content-Type: application/json' -H 'X-Etik-Speak-Transport: https' -H "Idempotency-Key: es301b-$(date +%s)" \
  -X POST "$PUBLIC_BASE/api/v1/public/ethics/reports" --data-binary @-)
unset gate_pw
receipt=$(printf '%s' "$resp" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("receiptId",""))
except Exception: print("")')
[ -n "$receipt" ] || { echo "FATAL: intake failed: $(printf '%s' "$resp" | head -c 200)" >&2; exit 1; }
echo "intake: receipt=$receipt"
case_id=$(psql_e "select id from ethics_service.ethics_cases where org_id='$SYNTHETIC_ORG' and created_at > coalesce(nullif('$before','')::timestamptz, 'epoch'::timestamptz) order by created_at desc limit 1")
[ -n "$case_id" ] || { echo "FATAL: new case not found" >&2; exit 1; }
echo "case: $case_id (org $SYNTHETIC_ORG)"

# 2. Backdate the one synthetic case.
psql_e "update ethics_service.ethics_cases set created_at = now() - interval '$BACKDATE_DAYS days', updated_at = now() - interval '$BACKDATE_DAYS days' where id='$case_id' and org_id='$SYNTHETIC_ORG'" >/dev/null
echo "fixture: created_at moved $BACKDATE_DAYS days back"
mark=$(psql_e "select now()::text")

# 3. Trigger a sweep: a restart runs the escalation sweep PT1M after start.
kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NS" rollout restart deploy/ethics-service >/dev/null
kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NS" rollout status deploy/ethics-service --timeout=300s >/dev/null
echo "sweep: ethics-service restarted; waiting up to ${WAIT_SECONDS}s for levels + signals + delivery"
deadline=$(( $(date +%s) + WAIT_SECONDS ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  levels=$(psql_e "select count(*) from ethics_service.ethics_case_escalation where case_id='$case_id'")
  delivered=$(psql_e "select count(*) from ethics_service.ethics_notification_outbox where org_id='$SYNTHETIC_ORG' and created_at >= '$mark' and event_type like 'CASE_ESCALATED_L%' and status='DELIVERED'")
  inbox=$(psql_n "select count(*) from notify.notification_inbox where org_id='$SYNTHETIC_ORG' and topic_key='ethics.case.escalation' and created_at >= '$mark'")
  echo "  $(date +%T) levels=$levels outbox_delivered=$delivered inbox_rows=$inbox"
  if [ "$levels" -ge 2 ] && [ "$delivered" -ge 2 ] && [ "$inbox" -ge 2 ]; then break; fi
  sleep 20
done

# 4. Evidence chain (ids and counts only).
echo "--- ethics: escalation rows for the case"
psql_e "select obligation, level, threshold_at, escalated_at from ethics_service.ethics_case_escalation where case_id='$case_id' order by level"
echo "--- ethics: outbox signals (org, since fixture)"
psql_e "select id, event_type, status, attempt_count, created_at from ethics_service.ethics_notification_outbox where org_id='$SYNTHETIC_ORG' and created_at >= '$mark' order by created_at"
echo "--- orchestrator: intents (recipient/template/payload) for those outbox ids"
for oid in $(psql_e "select id from ethics_service.ethics_notification_outbox where org_id='$SYNTHETIC_ORG' and created_at >= '$mark' and event_type like 'CASE_ESCALATED_L%'"); do
  psql_n "select intent_id, topic_key, template_id, template_version, severity, payload::text, (recipients_snapshot::jsonb->0->>'subscriberId') as recipient, status from notify.notification_intent where intent_id='ethics-$oid'"
  psql_n "select 'delivery', d.status, d.channel from notify.notification_delivery d join notify.notification_intent i on i.id=d.intent_id where i.intent_id='ethics-$oid'" 2>/dev/null || true
  psql_n "select 'inbox', subscriber_id, subject, state from notify.notification_inbox where intent_id='ethics-$oid'"
done
echo "--- tier separation (must be: L1 only under $FIRST_TIER, L2 only under $SECOND_TIER)"
psql_n "select subscriber_id, subject, count(*) from notify.notification_inbox where org_id='$SYNTHETIC_ORG' and topic_key='ethics.case.escalation' and created_at >= '$mark' group by 1,2 order by 1,2"
echo "--- second tier effective preferences (must not block)"
psql_n "select count(*) from notify.subscriber_preference where subscriber_id='$SECOND_TIER'" 2>/dev/null || true
echo "CASE_ID=$case_id MARK=$mark"
