#!/usr/bin/env bash
# Faz 35 ES-308 (#2667) — isolation chaos: what survives when a neighbour fails.
#
# The claim under test is the one a whistleblower depends on: a report must be
# accepted and kept even while the rest of the platform is having a bad day, and
# staff access must fail CLOSED rather than fall open when the thing that decides
# "may this person read cases" cannot be reached.
#
# Runs on aiserver (needs kubectl, the node container, and the persona files).
# Read-mostly: the only mutation is a temporary Calico Deny that is removed by an
# EXIT trap, plus synthetic reports it files against the TEST cell and labels as
# such. No token, password, receipt or case value is ever printed.
#
#   HOW THE OUTAGE IS INJECTED, AND WHY IT IS NOT JUST A NETWORK POLICY
#   A Calico Deny alone does NOT simulate an outage. Measured on 2026-08-02: with
#   the policy in force the staff path kept answering 200 for over 20 seconds,
#   because the JDK HTTP client held a warm keep-alive connection and conntrack
#   lets an established flow continue. The cut only became real once the
#   established flows were flushed as well — and the flush must be keyed on the
#   SERVICE ClusterIP, since the conntrack original tuple is recorded pre-DNAT
#   (deleting by pod IP matches nothing and silently removes zero flows, which
#   looks exactly like a working cut that found nothing to break).
#   So: Deny + flush. That reproduces "the dependency went away" rather than
#   "new connections to the dependency are refused while old ones sail on".
set -euo pipefail
set +x
umask 077

CTX="${CHAOS_CONTEXT:-k3d-test}"
NS="${CHAOS_NAMESPACE:-platform-test}"
NODE="${CHAOS_NODE_CONTAINER:-k3d-test-server-0}"
EDGE_IP="${CHAOS_EDGE_IP:-10.9.10.15}"
KC_BASE_URL="${CHAOS_KC_BASE_URL:-http://127.0.0.1:8082}"
KC_REALM="${CHAOS_KC_REALM:-platform-test}"
STAFF_HOST="${CHAOS_STAFF_HOST:-testai.acik.com}"
PUBLIC_HOST="${CHAOS_PUBLIC_HOST:-etik.acik.com}"
SECRET_DIR="${CHAOS_SECRET_DIR:-/srv/platform/secrets/faz35-test}"
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
OUT="${CHAOS_EVIDENCE_OUT:-$REPO_ROOT/docs/faz-35-evidence/isolation-chaos-latest.json}"
POLICY_PREFIX=es308-chaos-deny

[ "$CTX" = k3d-test ] || { echo "FATAL: this drill is pinned to the TEST cell" >&2; exit 1; }
for command_name in kubectl curl jq python3 docker; do
  command -v "$command_name" >/dev/null || { echo "FATAL: missing $command_name" >&2; exit 1; }
done

TMP=$(mktemp -d /tmp/es308-chaos.XXXXXX)
heal_all() {
  # Runs on every exit path including Ctrl-C. Leaving a Deny behind would take the
  # cell down for the next person, so this deletes by prefix rather than by the one
  # name the script happens to be holding when it dies.
  local left
  left=$(kubectl --context "$CTX" -n "$NS" get networkpolicies.projectcalico.org \
    -o name 2>/dev/null | grep "$POLICY_PREFIX" || true)
  if [ -n "$left" ]; then
    printf '%s\n' "$left" | while read -r policy; do
      [ -n "$policy" ] && kubectl --context "$CTX" -n "$NS" delete "$policy" >/dev/null 2>&1 || true
    done
  fi
  find "$TMP" -type f -delete 2>/dev/null || true
  rmdir "$TMP" 2>/dev/null || true
}
trap heal_all EXIT INT TERM

FINDINGS="[]"
record() {
  FINDINGS=$(jq -nc --argjson acc "$FINDINGS" --arg s "$1" --arg k "$2" --arg v "$3" \
    '$acc + [{scenario:$s, probe:$k, observed:$v}]')
}
fail() { echo "FATAL: $1" >&2; exit "${2:-30}"; }

# ---------------------------------------------------------------- identity ----
mint_token() {
  local outfile=$1 username=$2 code
  code=$(curl -sS --max-time 15 -o "$TMP/token.json" -w '%{http_code}' \
    -X POST "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'grant_type=password' \
    --data-urlencode 'client_id=smoke-client' \
    --data-urlencode "client_secret@$SECRET_DIR/smoke-client.secret" \
    --data-urlencode "username=$username" \
    --data-urlencode "password@$SECRET_DIR/$username.password" \
    --data-urlencode 'scope=openid ethics-manager-audience ethics:case:manage' || printf '000')
  [ "$code" = 200 ] || fail "staff token mint failed (http=$code) — the drill cannot run blind" 10
  # The token goes into a mode-600 curl config file, never into `-H` on a command line.
  # An argument list is world-readable through /proc, so a staff bearer passed as -H is
  # visible to every other account on this shared host for the life of the request.
  printf 'header = "Authorization: Bearer %s"\n' "$(jq -j '.access_token' "$TMP/token.json")" > "$outfile"
  chmod 600 "$outfile"
  grep -q 'Bearer .' "$outfile" || fail "minted token was empty" 10
}

# Returns "<http_code>/<case_count>". The count matters as much as the code: when the
# policy engine is unreachable the Etik gate denies by returning an EMPTY LIST with 200,
# not by returning 403 (EthicsAuthorization.gateFor -> CaseGate.DENY_ALL). A probe that
# only read the status code would see 200 and call that "access stayed open", which is
# the opposite of what happened. `unreadable` rather than 0 when the body is not JSON:
# a zero here must mean "the gate denied", never "we could not tell".
staff_probe() {
  local code count
  code=$(curl -sk --max-time "${STAFF_TIMEOUT:-25}" -o "$TMP/staff.out" -w '%{http_code}' \
    --resolve "$STAFF_HOST:443:$EDGE_IP" -K "$TMP/staff.token" \
    "https://$STAFF_HOST/api/v1/ethics/cases" || printf '000')
  count=$(jq -r 'if type == "array" then length else "unreadable" end' "$TMP/staff.out" 2>/dev/null || printf 'unreadable')
  printf '%s/%s' "$code" "${count:-unreadable}"
}
staff_status() { staff_probe | cut -d/ -f1; }
forged_status() {
  # Same config-file route as the real token — not because this one is sensitive (it is
  # deliberately nonsense), but so the two paths are byte-for-byte the same shape and the
  # comparison measures the token, not the way it was delivered.
  printf 'header = "Authorization: Bearer not-a-real-token"\n' > "$TMP/forged.token"
  chmod 600 "$TMP/forged.token"
  curl -sk --max-time 25 -o /dev/null -w '%{http_code}' --resolve "$STAFF_HOST:443:$EDGE_IP" \
    -K "$TMP/forged.token" \
    "https://$STAFF_HOST/api/v1/ethics/cases" || printf '000'
}

# Files a synthetic report and keeps the receipt in a file. The receipt is the
# reporter's only key to their own case, so it is written to $TMP and never echoed.
file_report() {
  local tag=$1 secret_file=$2 receipt_file=$3 code
  # Exactly 43 characters, built without `cut`: the intake contract refuses anything
  # shorter, and `cut` would append a newline that then lands inside the JSON body.
  # A too-short secret surfaces as VALIDATION_FAILED, which reads like "intake is
  # down" in the middle of a chaos window — a measurement failure disguised as a finding.
  printf '0123456789ABCDEFGHIJKLMNOPQRSTUVWX_es3%05d' "$RANDOM" > "$secret_file"
  [ "$(wc -c < "$secret_file" | tr -d ' ')" = 43 ] || fail "synthetic access secret is not 43 chars" 14
  code=$(curl -sk --max-time 25 -o "$TMP/intake.json" -w '%{http_code}' \
    --resolve "$PUBLIC_HOST:443:$EDGE_IP" \
    -X POST "https://$PUBLIC_HOST/api/v1/public/ethics/reports" \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: es308-$tag-$(date +%s)-$RANDOM" \
    -d "{\"mode\":\"ANONYMOUS\",\"category\":\"OTHER\",
         \"subject\":\"ES-308 sentetik izolasyon olcumu\",
         \"description\":\"Sentetik icerik - izolasyon kaos testi ($tag)\",
         \"locale\":\"tr\",\"accessSecret\":\"$(cat "$secret_file")\",
         \"noticeVersion\":\"tr-test-pilot-v1\"}" || printf '000')
  jq -j '.receiptId // empty' "$TMP/intake.json" > "$receipt_file" 2>/dev/null || true
  printf '%s' "$code"
}

# Durability, not just a 201: can the reporter still open the case afterwards?
mailbox_status() {
  local receipt_file=$1 secret_file=$2
  [ -s "$receipt_file" ] || { printf 'no-receipt'; return; }
  curl -sk --max-time 25 -o /dev/null -w '%{http_code}' --resolve "$PUBLIC_HOST:443:$EDGE_IP" \
    -X POST "https://$PUBLIC_HOST/api/v1/public/ethics/mailbox/sessions" \
    -H 'Content-Type: application/json' \
    -d "{\"receiptId\":\"$(cat "$receipt_file")\",\"accessSecret\":\"$(cat "$secret_file")\"}" \
    || printf '000'
}

# ------------------------------------------------------------ fault injection --
cut_dependency() {
  # $2 is the Calico destination body (a pod selector, or nets for a host-bridged
  # dependency). $3 is the Service whose ClusterIP the conntrack flush is keyed on —
  # ALWAYS a Service, even when the deny itself is written as a CIDR: Keycloak lives
  # on the host bridge but ethics-service still reaches it through a ClusterIP, so the
  # conntrack original tuple holds the ClusterIP and a flush keyed on the host IP
  # deletes nothing. That failure mode is silent, and it looks like a clean cut.
  local label=$1 destination=$2 service=$3
  kubectl --context "$CTX" apply -f - >/dev/null <<YAML
apiVersion: projectcalico.org/v3
kind: NetworkPolicy
metadata:
  name: $POLICY_PREFIX-$label
  namespace: $NS
spec:
  order: 10
  selector: "app.kubernetes.io/name == 'ethics-service'"
  types: [Egress]
  egress:
    - action: Deny
      destination:
        $destination
YAML
  sleep 3
  local ethics_ip target_ip deleted
  ethics_ip=$(kubectl --context "$CTX" -n "$NS" get pod -l app.kubernetes.io/name=ethics-service \
    -o jsonpath='{.items[0].status.podIP}')
  [ -n "$ethics_ip" ] || fail "could not resolve the ethics-service pod IP" 11
  target_ip=$(kubectl --context "$CTX" -n "$NS" get svc "$service" -o jsonpath='{.spec.clusterIP}')
  [ -n "$target_ip" ] || fail "could not resolve ClusterIP for $service" 11
  deleted=$(docker exec "$NODE" conntrack -D -s "$ethics_ip" -d "$target_ip" 2>&1 \
    | sed -n 's/.*\([0-9][0-9]*\) flow entries have been deleted.*/\1/p' | tail -1 || true)
  record "$label" conntrack_flows_flushed "${deleted:-0}"
  sleep 3
}
heal() {
  kubectl --context "$CTX" -n "$NS" delete networkpolicies.projectcalico.org \
    "$POLICY_PREFIX-$1" --ignore-not-found=true >/dev/null 2>&1 || true
  sleep 4
}

# "name=generation" for every non-Etik workload. The generation is the discriminator
# for the blast-radius check: this drill never edits another Deployment's spec, so if a
# neighbour is unhealthy AND its generation moved during the run, somebody else rolled it
# out — on a shared TEST cell with parallel sessions that happens often, and a check that
# blames the drill for it is a check nobody will trust the next time it fires for real.
neighbour_generations() {
  kubectl --context "$CTX" -n "$NS" get deploy -o json | python3 -c '
import sys, json
docs = json.load(sys.stdin)
out = {}
for d in docs["items"]:
    if d["metadata"].get("labels", {}).get("app.kubernetes.io/part-of") == "etik-speak":
        continue
    out[d["metadata"]["name"]] = d["metadata"].get("generation", 0)
print(json.dumps(out))
'
}
neighbours_ready() {
  kubectl --context "$CTX" -n "$NS" get deploy -o json | python3 -c '
import sys, json
docs = json.load(sys.stdin)
bad = []
for d in docs["items"]:
    labels = d["metadata"].get("labels", {})
    if labels.get("app.kubernetes.io/part-of") == "etik-speak":
        continue
    desired = d["spec"].get("replicas", 0)
    if desired == 0:
        continue
    ready = d.get("status", {}).get("readyReplicas", 0)
    if ready < desired:
        bad.append(d["metadata"]["name"])
print(",".join(sorted(bad)) if bad else "all-ready")
'
}

metric() {
  # `|| true` on the whole pipeline: under `set -o pipefail` a failed exec would abort
  # the drill mid-flight and leave a Deny in place. An unreadable metric is reported
  # as "unreadable" and never silently as 0 — a zero would read as "nothing queued",
  # which is the opposite of what an unreadable counter means.
  local name=$1 value
  value=$(kubectl --context "$CTX" -n monitoring exec \
    prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
    /bin/promtool query instant http://127.0.0.1:9090 \
    "$name{namespace=\"$NS\"}" 2>/dev/null | sed -n 's/.*=> \([0-9.e+-]*\) @.*/\1/p' | tail -1 || true)
  [ -n "$value" ] || { printf 'unreadable'; return; }
  printf '%s' "$value"
}

echo "ES-308 — Etik Speak izolasyon kaos testi (TEST hucresi)"
echo

# ---------------------------------------------------------- 0. blast radius ---
BASE_NEIGHBOURS=$(neighbours_ready)
BASE_GENERATIONS=$(neighbour_generations)
[ "$BASE_NEIGHBOURS" = all-ready ] || \
  fail "neighbouring products are not healthy BEFORE the drill ($BASE_NEIGHBOURS) — a chaos result measured on a broken baseline proves nothing" 12
echo "0. Komsu urunler tabanda saglikli: $BASE_NEIGHBOURS"

# ------------------------------------------- 1. structural independence proof --
# The strongest independence evidence is not "we broke it and nothing happened" but
# "it cannot be reached at all". ethics-service egress is a closed allowlist under a
# namespace default-deny, so anything absent from it is unreachable by construction.
STRUCTURAL=$(kubectl --context "$CTX" -n "$NS" get networkpolicy ethics-service -o json \
  | python3 -c '
import sys, json
policy = json.load(sys.stdin)
allowed = set()
for rule in policy["spec"].get("egress", []):
    for target in rule.get("to", []):
        selector = target.get("podSelector", {}).get("matchLabels", {})
        name = selector.get("app.kubernetes.io/name")
        if name:
            allowed.add(name)
print(json.dumps(sorted(allowed)))
')
UNREACHABLE_OTHERS=$(kubectl --context "$CTX" -n "$NS" get deploy -o json \
  | ALLOWED="$STRUCTURAL" python3 -c '
import sys, json, os
allowed = set(json.loads(os.environ["ALLOWED"]))
docs = json.load(sys.stdin)
unreachable = []
for d in docs["items"]:
    labels = d["metadata"].get("labels", {})
    if labels.get("app.kubernetes.io/part-of") == "etik-speak":
        continue
    name = labels.get("app.kubernetes.io/name") or d["metadata"]["name"]
    if name not in allowed:
        unreachable.append(name)
print(json.dumps(sorted(set(unreachable))))
')
UNREACHABLE_COUNT=$(printf '%s' "$UNREACHABLE_OTHERS" | jq 'length')
[ "$UNREACHABLE_COUNT" -gt 0 ] || \
  fail "no unreachable neighbour was found — either the namespace holds nothing else, or the allowlist has grown to cover everything; either way the independence claim is unproven" 15
echo "1. Yapisal bagimsizlik: ethics-service egress izin listesi = $STRUCTURAL"
echo "   Ayni namespace'teki diger $UNREACHABLE_COUNT urun (Meeting/Endpoint/ATS/denetim vb.)"
echo "   ethics-service icin ULASILAMAZ — namespace default-deny + kapali izin listesi."
record structural egress_allowlist "$STRUCTURAL"
record structural neighbours_unreachable_by_construction "$UNREACHABLE_COUNT"

# --------------------------------------------------------------- 2. baseline --
mint_token "$TMP/staff.token" ethics-manager-test
BASE_PROBE=$(staff_probe)
BASE_STAFF=${BASE_PROBE%%/*}
BASE_COUNT=${BASE_PROBE##*/}
BASE_FORGED=$(forged_status)
BASE_INTAKE=$(file_report baseline "$TMP/base.secret" "$TMP/base.receipt")
[ "$BASE_STAFF" = 200 ] || fail "staff baseline is $BASE_STAFF, not 200 — nothing measured after this would mean anything" 13
# Without a non-empty baseline, "the outage returned zero cases" would prove nothing:
# zero would be the same answer the healthy system gives.
case "$BASE_COUNT" in
  ''|unreadable|0) fail "staff baseline returned $BASE_COUNT cases; a later empty list could not be read as a denial" 13 ;;
esac
[ "$BASE_INTAKE" = 201 ] || fail "public intake baseline is $BASE_INTAKE, not 201" 13
[ "$BASE_FORGED" = 401 ] || fail "a forged token returned $BASE_FORGED at baseline, expected 401" 13
echo "2. Taban: personel=$BASE_STAFF ($BASE_COUNT dava)  sahte-token=$BASE_FORGED  ihbar-alimi=$BASE_INTAKE"
record baseline staff "$BASE_PROBE"; record baseline forged_token "$BASE_FORGED"
record baseline public_intake "$BASE_INTAKE"

# ------------------------------------------- 3. entitlement (permission) cut ---
echo "3. Yetki servisi kesintisi (permission-service)"
cut_dependency permission-service \
  "selector: \"app.kubernetes.io/name == 'permission-service'\"" permission-service
CUT_PROBE=$(staff_probe)
CUT_INTAKE=$(file_report perm-cut "$TMP/perm.secret" "$TMP/perm.receipt")
CUT_FORGED=$(forged_status)
heal permission-service
HEAL_PROBE=$(staff_probe)
# Denied means "no cases came back", whether that is expressed as 403 or as 200 with an
# empty list. Only a 2xx carrying actual cases is a fail-open.
case "$CUT_PROBE" in
  2*/0|2*/unreadable) : ;;
  2*) fail "staff access stayed OPEN ($CUT_PROBE) while the entitlement service was unreachable — this is a fail-open authorization bug" 20 ;;
esac
[ "$CUT_INTAKE" = 201 ] || fail "public intake returned $CUT_INTAKE during the entitlement outage; the reporter path must not depend on staff authorization" 21
[ "${HEAL_PROBE%%/*}" = 200 ] || fail "staff access did not recover after the cut was removed (got $HEAL_PROBE)" 22
echo "   personel=$CUT_PROBE (fail-closed)  ihbar-alimi=$CUT_INTAKE  iyilesme=$HEAL_PROBE"
record permission_outage staff "$CUT_PROBE"; record permission_outage public_intake "$CUT_INTAKE"
record permission_outage forged_token "$CUT_FORGED"; record permission_outage recovery_staff "$HEAL_PROBE"

# ------------------------------------------------------------ 4. identity cut --
echo "4. Kimlik saglayici kesintisi (Keycloak)"
cut_dependency keycloak 'nets: ["172.19.0.7/32"]' keycloak
KC_STAFF=$(staff_probe)
KC_FORGED=$(forged_status)
KC_INTAKE=$(file_report kc-cut "$TMP/kc.secret" "$TMP/kc.receipt")
heal keycloak
KC_HEAL=$(staff_probe)
# A valid token MAY still be honoured here: the JWK set is cached in-process, and
# continuing to serve a already-issued token during a brief identity outage is
# resilience, not a hole. What must NOT happen is a forged token being accepted.
case "$KC_FORGED" in
  2*) fail "a forged token was ACCEPTED ($KC_FORGED) while the identity provider was unreachable — signature verification fell open" 23 ;;
esac
[ "$KC_INTAKE" = 201 ] || fail "public intake returned $KC_INTAKE during the identity outage; anonymous reporting must not need Keycloak" 24
echo "   gecerli-token=$KC_STAFF  sahte-token=$KC_FORGED (reddedildi)  ihbar-alimi=$KC_INTAKE  iyilesme=$KC_HEAL"
record identity_outage staff_valid_token "$KC_STAFF"; record identity_outage forged_token "$KC_FORGED"
record identity_outage public_intake "$KC_INTAKE"; record identity_outage recovery_staff "$KC_HEAL"

# ------------------------------------------------------------- 5. authz plane --
echo "5. Yetki duzlemi kesintisi (OpenFGA)"
cut_dependency openfga "selector: \"app.kubernetes.io/name == 'openfga'\"" openfga
# 150s, not the usual 25s: with no read timeout on the OpenFGA client this call is slow
# by construction (measured 2026-08-02: ~43s when the connection has to be re-established,
# and it never returns at all on an already-established socket — the edge 504s at 90s).
# A 25s ceiling would record a client-side give-up and hide what the service decided.
FGA_PROBE=$(STAFF_TIMEOUT=150 staff_probe)
FGA_STAFF=${FGA_PROBE%%/*}
FGA_COUNT=${FGA_PROBE##*/}
FGA_INTAKE=$(file_report fga-cut "$TMP/fga.secret" "$TMP/fga.receipt")
heal openfga
FGA_HEAL=$(staff_probe)
[ "$FGA_INTAKE" = 201 ] || fail "public intake returned $FGA_INTAKE during the authz-plane outage" 25
[ "${FGA_HEAL%%/*}" = 200 ] || fail "staff access did not recover after the authz-plane cut (got $FGA_HEAL)" 25
# The denial here is the EMPTY LIST, not the status code. Anything other than an empty
# list means the gate handed out cases while it could not verify conflict or recusal —
# and withholding those is precisely what recusal exists for.
case "$FGA_STAFF/$FGA_COUNT" in
  200/0) : ;;
  200/*) fail "the case list returned $FGA_COUNT cases while the policy engine was unreachable — conflict/recusal could not be checked and cases were served anyway" 25 ;;
  *) : ;;  # a non-200 (timeout, 504) is also not a disclosure; recorded as-is below
esac
echo "   personel=$FGA_PROBE (bos liste = reddedildi)  ihbar-alimi=$FGA_INTAKE  iyilesme=$FGA_HEAL"
record authz_plane_outage staff "$FGA_PROBE"; record authz_plane_outage public_intake "$FGA_INTAKE"
record authz_plane_outage recovery_staff "$FGA_HEAL"

# ---------------------------------------------------- 6. notification outage ---
# The one that actually risks losing a report: if the intake transaction depended on
# a downstream notification, a notifier outage would reject the reporter outright.
echo "6. Bildirim kesintisi (notification-orchestrator) — dayaniklilik olcumu"
NOTIF_PENDING_BEFORE=$(metric ethics_notification_outbox_pending_entries)
NOTIF_DELIVERED_BEFORE=$(metric ethics_notification_outbox_delivered_total)
cut_dependency notification-orchestrator \
  "selector: \"app.kubernetes.io/name == 'notification-orchestrator'\"" notification-orchestrator
NOTIF_INTAKE=$(file_report notif-cut "$TMP/notif.secret" "$TMP/notif.receipt")
[ "$NOTIF_INTAKE" = 201 ] || \
  fail "public intake returned $NOTIF_INTAKE while the notifier was down — a reporter would have lost their report because an unrelated service failed" 26
# One scrape interval is 30s; a shorter wait would read a pre-cut sample and call it
# a post-cut result.
sleep 40
NOTIF_PENDING_CUT=$(metric ethics_notification_outbox_pending_entries)
NOTIF_RETRY_CUT=$(metric ethics_notification_outbox_retry_total)
MAILBOX_DURING=$(mailbox_status "$TMP/notif.receipt" "$TMP/notif.secret")
heal notification-orchestrator
# Poll rather than sleep a fixed window: delivery is retried with a backoff, so a fixed
# 45s answered "still 1 pending" on one run and "drained" on the next — same system, two
# different stories, decided by where the retry clock happened to be.
NOTIF_PENDING_AFTER=unreadable
for _ in $(seq 1 12); do
  sleep 20
  NOTIF_PENDING_AFTER=$(metric ethics_notification_outbox_pending_entries)
  [ "$NOTIF_PENDING_AFTER" = 0 ] && break
done
NOTIF_DELIVERED_AFTER=$(metric ethics_notification_outbox_delivered_total)
NOTIF_DEADLETTER=$(metric ethics_notification_outbox_dead_letter_entries)
MAILBOX_AFTER=$(mailbox_status "$TMP/notif.receipt" "$TMP/notif.secret")
[ "$NOTIF_PENDING_AFTER" = 0 ] || \
  fail "the notification outbox still holds $NOTIF_PENDING_AFTER entries four minutes after the notifier came back — queued is only acceptable if it drains" 27
[ "$NOTIF_DEADLETTER" = 0 ] || \
  fail "$NOTIF_DEADLETTER notification(s) went to the dead-letter table — the signal was accepted and then abandoned" 27
[ "$MAILBOX_AFTER" = 201 ] || [ "$MAILBOX_AFTER" = 200 ] || \
  fail "the report filed during the notifier outage could not be opened afterwards (mailbox=$MAILBOX_AFTER) — it was accepted but not durable" 27
echo "   ihbar-alimi=$NOTIF_INTAKE  posta-kutusu(kesinti sirasinda)=$MAILBOX_DURING  posta-kutusu(sonra)=$MAILBOX_AFTER"
echo "   outbox pending: $NOTIF_PENDING_BEFORE -> $NOTIF_PENDING_CUT -> $NOTIF_PENDING_AFTER (bosaldi)"
echo "   outbox delivered: $NOTIF_DELIVERED_BEFORE -> $NOTIF_DELIVERED_AFTER (retry=$NOTIF_RETRY_CUT, olu-mektup=$NOTIF_DEADLETTER)"
record notification_outage public_intake "$NOTIF_INTAKE"
record notification_outage mailbox_after_recovery "$MAILBOX_AFTER"
record notification_outage outbox_pending_before "$NOTIF_PENDING_BEFORE"
record notification_outage outbox_pending_during "$NOTIF_PENDING_CUT"
record notification_outage outbox_pending_after "$NOTIF_PENDING_AFTER"
record notification_outage outbox_delivered_before "$NOTIF_DELIVERED_BEFORE"
record notification_outage outbox_delivered_after "$NOTIF_DELIVERED_AFTER"

# ------------------------------------------------------ 7. blast radius after --
FINAL_NEIGHBOURS=$(neighbours_ready)
if [ "$FINAL_NEIGHBOURS" != all-ready ]; then
  # Split the unhealthy set into "somebody else redeployed it mid-drill" (generation
  # moved — this drill never touches another Deployment's spec) and "it was steady and
  # went unhealthy while we were cutting", which is the only one that indicts the drill.
  ATTRIBUTABLE=$(BEFORE="$BASE_GENERATIONS" AFTER="$(neighbour_generations)" \
    UNHEALTHY="$FINAL_NEIGHBOURS" python3 -c '
import json, os
before = json.loads(os.environ["BEFORE"])
after = json.loads(os.environ["AFTER"])
blamed, concurrent = [], []
for name in os.environ["UNHEALTHY"].split(","):
    name = name.strip()
    if not name:
        continue
    if name not in before or before.get(name) != after.get(name):
        concurrent.append(name)
    else:
        blamed.append(name)
print(json.dumps({"blamed": sorted(blamed), "concurrent": sorted(concurrent)}))
')
  CONCURRENT=$(printf '%s' "$ATTRIBUTABLE" | jq -r '.concurrent | join(",")')
  BLAMED=$(printf '%s' "$ATTRIBUTABLE" | jq -r '.blamed | join(",")')
  [ -z "$BLAMED" ] || \
    fail "neighbouring products degraded during the drill without being redeployed ($BLAMED) — the blast radius escaped the Etik cell" 28
  echo "   NOT: tatbikat sirasinda baska bir oturum su is yuklerini yeniden dagitti: $CONCURRENT"
  echo "        (generation degisti — bu tatbikat baska hicbir Deployment'in spec'ine dokunmaz)"
  record blast_radius concurrent_redeploys_not_attributable "$CONCURRENT"
  FINAL_NEIGHBOURS="all-ready-except-concurrent-redeploys"
fi
LEFTOVER=$(kubectl --context "$CTX" -n "$NS" get networkpolicies.projectcalico.org \
  -o name 2>/dev/null | grep -c "$POLICY_PREFIX" || true)
[ "${LEFTOVER:-0}" -eq 0 ] || fail "chaos policies were left behind ($LEFTOVER)" 29
echo "7. Komsu urunler tatbikat sonrasi: $FINAL_NEIGHBOURS; artik kaos politikasi yok"

mkdir -p "$(dirname "$OUT")"
jq -n --argjson findings "$FINDINGS" --arg neighbours "$FINAL_NEIGHBOURS" \
  --argjson structural "$STRUCTURAL" --argjson unreachable "$UNREACHABLE_OTHERS" \
  '{schema_version:"faz35-isolation-chaos-v1",
    note:"Redacted by construction: HTTP status codes and aggregate counters only. No token, receipt, case id or reporter value appears here.",
    injection:"calico Deny (order 10) + conntrack flush keyed on the SERVICE ClusterIP; a Deny alone does not break a warm keep-alive connection, and a flush keyed on the pod IP deletes nothing",
    denial_shape:"on the case-list path a denial is an EMPTY LIST with 200, not a 403 — the probe reads the body, not only the status",
    egress_allowlist:$structural,
    neighbour_products_unreachable_by_construction:$unreachable,
    neighbours_after:$neighbours,
    probes:$findings,
    accepted:true}' > "$OUT"

echo
echo "Kanit yazildi (redakte): $OUT"
echo "ISOLATION_CHAOS_ACCEPTED=true"
