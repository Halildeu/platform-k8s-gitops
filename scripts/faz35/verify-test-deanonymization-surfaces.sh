#!/bin/bash
# Faz 35 ES-305 (#2664) — deanonymization surfaces the log/cookie/IP verifier does not reach.
#
# ES-106 (verify-test-public-no-correlation.sh) already proves the plumbing surfaces:
# access logs off, cookies bounded, upstream identity stripped, sentinel never lands in a
# durable log. This verifier covers what remains, and all of it is about INFERENCE rather
# than storage — the question is not "was the reporter written down" but "can an observer
# work out that a given receipt exists, or which case a metric belongs to".
#
#   1. Existence oracle — status code, error code and TIMING must be identical whether a
#      receipt exists or not. A difference lets anyone enumerate real receipts.
#   2. Metric cardinality — no identity-shaped label value on the metrics surface. A single
#      case-id label turns Prometheus into a case register.
#   3. Backup plaintext — the encrypted artifact must not carry identity-shaped strings.
#
# Read-only. Emits booleans and aggregate numbers only; no receipt, case or subject value
# ever reaches stdout, the evidence file, GitHub or chat.
set -euo pipefail
set +x
umask 077

SSH_TARGET="${SSH_TARGET:-aiserver}"
PUBLIC_HOST="${PUBLIC_HOST:-etik.acik.com}"
SAMPLES="${DEANON_TIMING_SAMPLES:-10}"
# Median difference above this is treated as a finding. 40 ms is far below the ~280 ms the
# secret verification itself costs (PBKDF2), so a short-circuit would stand out immediately,
# and far above the network jitter measured on this path (single-digit ms).
TIMING_TOLERANCE_MS="${DEANON_TIMING_TOLERANCE_MS:-40}"
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
OUT="${DEANON_EVIDENCE_OUT:-$REPO_ROOT/docs/faz-35-evidence/deanonymization-surfaces-latest.json}"

[ "$SSH_TARGET" = "aiserver" ] || { echo "FATAL: pinned to the aiserver alias" >&2; exit 1; }
case "$PUBLIC_HOST" in
  etik.acik.com|speakup.acik.com) ;;
  *) echo "FATAL: refusing a host outside the reviewed TEST reporter surface" >&2; exit 1 ;;
esac
for command_name in curl jq python3 ssh uuidgen; do
  command -v "$command_name" >/dev/null || { echo "FATAL: missing $command_name" >&2; exit 1; }
done

ssh_opts=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=5)
remote() { ssh "${ssh_opts[@]}" "$SSH_TARGET" "$@"; }

# Synthetic only, and said so in the payload itself: this verifier files real reports on
# the TEST cell, and anyone reading the case list must see immediately what they are.
new_receipt() {
  local index=$1 secret=$2
  curl -sk --max-time 20 -X POST "https://$PUBLIC_HOST/api/v1/public/ethics/reports" \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: es305-$index-$(date +%s)-$RANDOM" \
    -d "{\"mode\":\"ANONYMOUS\",\"category\":\"OTHER\",
         \"subject\":\"ES-305 sentetik olcum\",
         \"description\":\"Sentetik icerik - deanonimizasyon yuzey olcumu\",
         \"locale\":\"tr\",\"accessSecret\":\"$secret\",
         \"noticeVersion\":\"tr-test-pilot-v1\"}" \
    | jq -r '.receiptId // empty'
}

open_mailbox_timed() {
  local receipt=$1 secret=$2
  curl -sk --max-time 20 -o /tmp/es305-body.$$ -w '%{http_code} %{time_total}' \
    -X POST "https://$PUBLIC_HOST/api/v1/public/ethics/mailbox/sessions" \
    -H 'Content-Type: application/json' \
    -d "{\"receiptId\":\"$receipt\",\"accessSecret\":\"$secret\"}"
}

echo "ES-305: measuring the receipt-existence oracle (status, error code, timing)"
WRONG_SECRET="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_es305w"
present_times=(); absent_times=()
present_codes=(); absent_codes=()
present_errors=(); absent_errors=()

for index in $(seq 1 "$SAMPLES"); do
  # ONE wrong-secret attempt per FRESH receipt. This is not fussiness: the brute-force
  # lockout on a grant row short-circuits later attempts BEFORE the key derivation runs,
  # so repeated attempts against one receipt make the present case look ~220 ms faster
  # and manufacture an oracle that is not there. The first run of this measurement fell
  # into exactly that (2026-08-01) and had to be redone.
  # 43 characters minimum, enforced by the intake contract — a shorter one is refused
  # at validation and this probe would report a filing failure instead of a measurement.
  secret="0123456789ABCDEFGHIJKLMNOPQRSTUVWX_es305$(printf '%03d' "$index")"
  receipt=$(new_receipt "$index" "$secret")
  [ -n "$receipt" ] || { echo "FATAL: synthetic report could not be filed" >&2; exit 1; }

  read -r code time <<<"$(open_mailbox_timed "$receipt" "$WRONG_SECRET")"
  present_codes+=("$code"); present_times+=("$time")
  present_errors+=("$(jq -r '.error.code // "none"' /tmp/es305-body.$$)")

  read -r code time <<<"$(open_mailbox_timed "$(uuidgen | tr '[:upper:]' '[:lower:]')" "$WRONG_SECRET")"
  absent_codes+=("$code"); absent_times+=("$time")
  absent_errors+=("$(jq -r '.error.code // "none"' /tmp/es305-body.$$)")
done
rm -f /tmp/es305-body.$$

# The response must be indistinguishable on every channel an observer can read.
distinct_codes=$(printf '%s\n' "${present_codes[@]}" "${absent_codes[@]}" | sort -u | wc -l | tr -d ' ')
distinct_errors=$(printf '%s\n' "${present_errors[@]}" "${absent_errors[@]}" | sort -u | wc -l | tr -d ' ')
[ "$distinct_codes" -eq 1 ] || {
  echo "FATAL: HTTP status differs between an existing and a non-existing receipt" >&2
  exit 21
}
[ "$distinct_errors" -eq 1 ] || {
  echo "FATAL: error code differs between an existing and a non-existing receipt" >&2
  exit 22
}

timing=$(python3 - "$TIMING_TOLERANCE_MS" <<PY "${present_times[@]}" -- "${absent_times[@]}"
import json, statistics, sys
tolerance = float(sys.argv[1])
rest = sys.argv[2:]
split = rest.index('--')
present = [float(x) * 1000 for x in rest[:split]]
absent = [float(x) * 1000 for x in rest[split + 1:]]
delta = abs(statistics.median(present) - statistics.median(absent))
print(json.dumps({
    "samples_per_arm": len(present),
    "present_median_ms": round(statistics.median(present), 1),
    "absent_median_ms": round(statistics.median(absent), 1),
    "median_delta_ms": round(delta, 1),
    "tolerance_ms": tolerance,
    "within_tolerance": delta <= tolerance,
}))
PY
)
printf '%s' "$timing" | jq -e '.within_tolerance' >/dev/null || {
  echo "FATAL: timing distinguishes an existing receipt from a non-existing one" >&2
  printf '%s\n' "$timing" | jq -r '"  present=\(.present_median_ms)ms absent=\(.absent_median_ms)ms delta=\(.median_delta_ms)ms"' >&2
  exit 23
}

echo "ES-305: measuring metric label cardinality"
# A single case- or receipt-shaped label value turns the metrics surface into a register of
# who reported what and when. Read through Prometheus with promtool: the ethics-service
# container ships no shell or curl (the first attempt at this probe silently produced a
# count of 0 from a FAILED exec — a check that cannot run must never report clean), and the
# management port is closed to everything but the monitoring namespace anyway.
metrics_series=$(remote 'kubectl --request-timeout=20s --context k3d-test -n monitoring \
  exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  /bin/promtool query instant http://127.0.0.1:9090 "{__name__=~\"ethics.*\"}"') || {
  echo "FATAL: the metrics surface could not be read — coverage is unknown, not clean" >&2
  exit 24
}
series_count=$(printf '%s\n' "$metrics_series" | grep -c '^ethics' || true)
[ "${series_count:-0}" -gt 0 ] || {
  echo "FATAL: no ethics series were returned — the probe proved nothing" >&2
  exit 24
}
identity_labels=$(printf '%s\n' "$metrics_series" \
  | grep -coE '="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"' || true)
identity_labels=${identity_labels:-0}
[ "$identity_labels" -eq 0 ] || {
  echo "FATAL: $identity_labels identity-shaped metric label values are exposed" >&2
  exit 25
}

echo "ES-305: checking backup artifacts for identity-shaped plaintext"
# ES-209 proved the drill encrypts. This asks the next question: does an artifact leak
# identity SHAPE even so — a UUID in a filename, an unencrypted index beside it. Searched
# across the host rather than one guessed directory, because "the path I assumed is empty"
# is not the same finding as "no artifact carries identity", and only the second one is
# worth writing down.
backup_scan=$(remote 'set -o pipefail
  found=$(find / -xdev \( -name "*.enc" -o -name "*etik*speak*.tar*" -o -name "*ethics*.dump*" \) \
    -type f -newermt "-30 days" 2>/dev/null | head -50)
  if [ -z "$found" ]; then printf "none 0"; exit 0; fi
  count=0
  while read -r artifact; do
    [ -n "$artifact" ] || continue
    hits=$( { grep -acE "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" "$artifact" || true; } )
    count=$((count + hits))
    name_hits=$( { printf "%s" "$artifact" | grep -cE "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" || true; } )
    count=$((count + name_hits))
  done <<<"$found"
  printf "%s %s" "$(printf "%s\n" "$found" | wc -l | tr -d " ")" "$count"')
read -r backup_artifacts backup_hits <<<"$backup_scan"
if [ "$backup_artifacts" = none ]; then
  # Honest state: nothing was in scope on this host at this moment. Recorded as such —
  # never as "clean", which would claim a proof this run did not make.
  backup_state='"no_artifact_in_scope"'
else
  [ "${backup_hits:-1}" -eq 0 ] || {
    echo "FATAL: a backup artifact carries identity-shaped plaintext" >&2
    exit 26
  }
  backup_state="\"clean:${backup_artifacts}_artifacts\""
fi

mkdir -p "$(dirname "$OUT")"
jq -n --argjson timing "$timing" --argjson labels "$identity_labels" \
  --argjson backup "$backup_state" --arg host "$PUBLIC_HOST" \
  --argjson series "${series_count:-0}" \
  '{schema_version:"faz35-deanonymization-surfaces-v1",
    note:"Redacted by construction: booleans, medians and counts only. No receipt, case or subject value appears here.",
    public_host:$host,
    existence_oracle:{status_indistinguishable:true, error_code_indistinguishable:true, timing:$timing},
    metrics:{series_read:$series, identity_shaped_label_values:$labels},
    backup_identity_plaintext:$backup,
    accepted:true}' > "$OUT"

printf 'Existence oracle: closed (%s)\n' "$(printf '%s' "$timing" | jq -r '"delta \(.median_delta_ms)ms <= \(.tolerance_ms)ms over \(.samples_per_arm) fresh receipts per arm"')"
echo "Metrics: $series_count ethics series read, 0 identity-shaped label values"
echo "Backup scan: $(printf '%s' "$backup_state" | tr -d '\"')"
echo "Evidence written (redacted): $OUT"
echo "DEANONYMIZATION_SURFACES_ACCEPTED=true"
