#!/usr/bin/env bash
# Faz 35 Etik Speak: notification recipient authorization for the TEST cell.
#
# The orchestrator asks OpenFGA before it delivers anything:
#
#   subscriber:<recipientId>  --can_receive-->  template:<templateId>
#
# and the model resolves that indirectly:
#
#   template.can_receive  =  template.topic → notification_topic.can_receive
#
# so two tuples are required, not one. Neither existed: the store held no
# topic or template tuples at all, so every intent — Faz 35's and every other
# producer's — was answered `authz_deny: no_tuple` after being accepted. The
# producer saw a delivered signal, the recipient saw nothing, and no component
# reported an error.
#
# Test-only. Idempotent: OpenFGA rejects a duplicate write, so an existing
# tuple is left alone rather than re-written. Fail-closed: the grant is proven
# with a live Check before this script reports success.
set -euo pipefail
set +x

KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"
STORE_ID="${STORE_ID:-01KPP0CFP4G82K42Y6NYSPT4JF}"
# A pod that is allowed to reach OpenFGA; the store is not routable from here.
CURL_POD="${CURL_POD:-deploy/meeting-service}"

TOPIC_KEY=ethics.case.activity
TEMPLATE_ID=ethics.case.activity
SUBSCRIBER_ID="${SUBSCRIBER_ID:-f8a3b6f6-a984-49d1-b666-c535b11c742f}"

for binding in \
  "$KUBE_CONTEXT=k3d-test" \
  "$KUBE_NS=platform-test" \
  "$STORE_ID=01KPP0CFP4G82K42Y6NYSPT4JF"; do
  [ "${binding%%=*}" = "${binding#*=}" ] || {
    echo "FATAL: this script is test-only; override refused: ${binding%%=*}" >&2
    exit 1
  }
done

fga() { # method path [body]
  local method=$1 path=$2 body=${3:-}
  if [ -n "$body" ]; then
    kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NS" exec "$CURL_POD" -- \
      curl -sS --max-time 15 -X "$method" \
      "http://openfga:8080/stores/$STORE_ID$path" \
      -H 'Content-Type: application/json' -d "$body"
  else
    kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NS" exec "$CURL_POD" -- \
      curl -sS --max-time 15 -X "$method" \
      "http://openfga:8080/stores/$STORE_ID$path"
  fi
}

write_tuple() { # user relation object
  local user=$1 relation=$2 object=$3 out
  out=$(fga POST /write "{\"writes\":{\"tuple_keys\":[{\"user\":\"$user\",\"relation\":\"$relation\",\"object\":\"$object\"}]}}" || true)
  case "$out" in
    *write_failed_due_to_invalid_input*|*already\ exists*)
      echo "  present: $user -- $relation --> $object" ;;
    "{}"|"")
      echo "  written: $user -- $relation --> $object" ;;
    *)
      echo "  FATAL: unexpected write result for $object" >&2
      printf '%s\n' "$out" | head -c 300 >&2; echo >&2
      return 1 ;;
  esac
}

echo "== recipient authorization =="
# 1. The subscriber may receive this topic.
write_tuple "subscriber:$SUBSCRIBER_ID" can_receive "notification_topic:$TOPIC_KEY"
# 2. The template belongs to that topic, which is how can_receive resolves.
write_tuple "notification_topic:$TOPIC_KEY" topic "template:$TEMPLATE_ID"

echo "== verify against the live store, not against what was just sent =="
decision=$(fga POST /check \
  "{\"tuple_key\":{\"user\":\"subscriber:$SUBSCRIBER_ID\",\"relation\":\"can_receive\",\"object\":\"template:$TEMPLATE_ID\"}}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("allowed"))')
echo "  subscriber can_receive template -> $decision"
[ "$decision" = "True" ] || { echo "FATAL: recipient grant is not authoritative" >&2; exit 1; }

# The grant must not widen: an unrelated subscriber stays denied.
other=$(fga POST /check \
  "{\"tuple_key\":{\"user\":\"subscriber:00000000-0000-4000-8000-000000000000\",\"relation\":\"can_receive\",\"object\":\"template:$TEMPLATE_ID\"}}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("allowed"))')
echo "  unrelated subscriber       -> $other"
[ "$other" = "False" ] || { echo "FATAL: the grant leaked to an unrelated subscriber" >&2; exit 1; }

echo "verify: recipient authorization is in place and does not widen"
