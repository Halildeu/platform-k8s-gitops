#!/usr/bin/env bash
#
# m7-stable-evidence.sh — Faz 23 M7 v1 30-day stable observation evidence
#
# Faz 23 M8 PR-1 D (Codex `019e8c24` AGREE order D→B→A→C).
#
# Reads the M7 stable observation recording rules + ALERTS state from the
# in-cluster Prometheus and emits a canonical JSON evidence dump that the
# operator stamps with a date and commits to docs/faz-23-evidence/.
#
# Predicates surfaced (mirrors notify-m7-stable-recording-rule.yaml v3):
#   composite:
#     - dispatch_success_rate_30d ≥ 0.995
#     - dlq_burn_max_30d ≤ 1.0
#     - critical_alert_minutes_30d == 0
#     - observation_coverage_30d ≥ 0.99 (anti-silence guard)
#     - elapsed_seconds_since_m7_live ≥ 2592000 (natural 30-day Prom-time gate)
#   supplementary:
#     - dlq_burn_72h_max_30d ≤ 1.0
#   boolean truth surface:
#     - stable_30d == 1 (AND of composite predicates)
#
# Usage:
#   ./docs/scripts/m7-stable-evidence.sh [--out PATH] [--context CTX]
#                                        [--namespace NS] [--port PORT]
#
# Defaults:
#   --out      /tmp/m7-v1-30day-stable-evidence-$(date -u +%Y%m%d-%H%MZ).json
#   --context  k3d-prod
#   --namespace monitoring
#   --port     9090 (Prometheus svc port)
#
# Exit codes:
#   0 — stable_30d=1 AND coverage ≥ 0.99 AND elapsed_s ≥ 2592000: M8 DoD blocker #1 met
#   1 — coverage ≥ 0.99 but natural 30-day mark (2026-06-22) not yet arrived
#   2 — stable_30d=0: predicate fail; observation NOT stable
#   3 — Prometheus unreachable / metric absent / coverage < 0.99
#   4 — Usage error
#
# Codex iter-1 P0 absorb: removed STABLE_BUT_WINDOW_IN_PROGRESS that
# depended on the (dropped) min_over_time semantic.
# Codex iter-2 P0/timeGate absorb: re-introduced exit-1 as
# WINDOW_PRE_NATURAL30D for the legitimate "coverage OK + natural 30d
# clock not yet expired" state. This is the canonical "wait until
# 2026-06-22" signal — distinct from OBSERVATION_ABSENT (lacking data)
# and UNSTABLE (predicate fail).
#
# Anti-pattern guards (Codex `019e8c24`):
#   - DOES NOT mutate any cluster state
#   - DOES NOT shorten the 30-day window or backdate evidence
#   - DOES NOT call M7 "green" until (stable_30d=1 AND coverage≥0.99 AND
#     natural 30-day Prom-time gate has passed)
#   - Treats absent metric as code 3 (cannot conclude), not code 0
#   - WINDOW_PRE_NATURAL30D (exit 1) is the canonical "wait until 2026-06-22"
#     verdict — distinct from OBSERVATION_ABSENT (lacking data) + UNSTABLE
#     (predicate fail)

set -euo pipefail

OUT=""
CONTEXT="k3d-prod"
NAMESPACE="monitoring"
PORT="9090"
PROM_SVC="prometheus-kube-prometheus-prometheus"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out)        OUT="$2"; shift 2 ;;
    --context)    CONTEXT="$2"; shift 2 ;;
    --namespace)  NAMESPACE="$2"; shift 2 ;;
    --port)       PORT="$2"; shift 2 ;;
    --svc)        PROM_SVC="$2"; shift 2 ;;
    -h|--help)
      sed -n '3,40p' "$0"
      exit 0
      ;;
    *)
      echo "ERROR: unknown arg: $1" >&2
      exit 4
      ;;
  esac
done

if [[ -z "$OUT" ]]; then
  OUT="/tmp/m7-v1-30day-stable-evidence-$(date -u +%Y%m%d-%H%MZ).json"
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl not on PATH" >&2
  exit 4
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq not on PATH" >&2
  exit 4
fi

# Port-forward Prometheus locally for read-only PromQL access. We pick a
# random ephemeral local port to avoid collisions with concurrent runs.
LOCAL_PORT="$(awk 'BEGIN{srand(); printf "%d", 31000 + int(rand()*1000)}')"
PF_LOG="$(mktemp -t m7-evidence-pf.XXXXXX.log)"
kubectl --context "$CONTEXT" -n "$NAMESPACE" port-forward "svc/$PROM_SVC" \
  "${LOCAL_PORT}:${PORT}" >"$PF_LOG" 2>&1 &
PF_PID=$!

cleanup() {
  if kill -0 "$PF_PID" 2>/dev/null; then
    kill "$PF_PID" 2>/dev/null || true
    wait "$PF_PID" 2>/dev/null || true
  fi
  rm -f "$PF_LOG"
}
trap cleanup EXIT

# Give port-forward a moment to bind.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf "http://127.0.0.1:${LOCAL_PORT}/-/ready" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

PROM="http://127.0.0.1:${LOCAL_PORT}"

if ! curl -sf "${PROM}/-/ready" >/dev/null 2>&1; then
  echo "ERROR: Prometheus not reachable at ${PROM}" >&2
  cat "$PF_LOG" >&2 || true
  exit 3
fi

# query — wraps Prom HTTP API instant query; emits scalar or first vector
#         value as a JSON number. Returns "null" string on absence.
query() {
  local q="$1"
  local resp
  resp="$(curl -sf --data-urlencode "query=${q}" "${PROM}/api/v1/query" || true)"
  if [[ -z "$resp" ]]; then
    echo "null"
    return
  fi
  echo "$resp" | jq -r '
    if .status != "success" then "null"
    elif (.data.resultType == "scalar") then (.data.result[1] // "null")
    elif (.data.resultType == "vector") then ((.data.result[0].value[1]) // "null")
    else "null"
    end'
}

# Read each predicate. Each query is namespace-scoped to platform-prod.
# Codex iter-1 P0/coverage absorb (thread 019e8c24):
#   - dropped `observation_present_30d` (always returned namespace-less 0)
#   - added `observation_coverage_30d` (anti-silence guard, fraction [0,1])
#   - dropped `min_over_time(stable_30d[30d])` (hidden 60d semantic +
#     partial-coverage false positive); evidence script now checks
#     stable_30d=1 AND coverage_30d ≥ 0.99 AND elapsed_seconds_since_m7_live
#     ≥ 2592000 directly (coverage tightened to 0.99 in iter-2, time-gate
#     added in iter-2 P0/timeGate).
SUCCESS_RATE=$(query 'notify:m7_v1:dispatch_success_rate:30d{namespace="platform-prod"}')
BURN_24H_MAX=$(query 'notify:m7_v1:dlq_burn_max:30d{namespace="platform-prod"}')
BURN_72H_MAX=$(query 'notify:m7_v1:dlq_burn_72h_max:30d{namespace="platform-prod"}')
ALERT_MINUTES=$(query 'notify:m7_v1:critical_alert_minutes:30d{namespace="platform-prod"}')
OBS_COVERAGE=$(query 'notify:m7_v1:observation_coverage:30d{namespace="platform-prod"}')
# Codex iter-3 P1/statusCoexist + iter-4 P1/coexistWindow absorb:
# DELIVERED ve SUCCESS aynı 30d penceresinde non-zero görünüyorsa
# success_rate numerator çift-sayım nedeniyle inflate olur. Probe window
# success_rate window ile aynı 30d (5m probe coexist'i 30d numerator
# için kaçırabiliyordu — örn. DELIVERED 10 gün önce, SUCCESS bugün).
# `increase` 30d window'da gözlenen toplam delta; > 0 filter null vs
# active ayrımını korur.
DELIVERED_RATE=$(query 'sum(increase(notify_dispatch_outcome_total{namespace="platform-prod", status="DELIVERED"}[30d])) > 0')
SUCCESS_LABEL_RATE=$(query 'sum(increase(notify_dispatch_outcome_total{namespace="platform-prod", status="SUCCESS"}[30d])) > 0')
# Codex iter-2 P0/timeGate absorb: natural 30-day Prom-time gate. The
# composite stable_30d already enforces ≥ 2592000s; we surface elapsed
# seconds + natural ready flag in evidence so the operator can see the
# clock state directly.
ELAPSED_SEC=$(query 'notify:m7_v1:elapsed_seconds_since_m7_live{namespace="platform-prod"}')
STABLE_NOW=$(query 'notify:m7_v1:stable_30d{namespace="platform-prod"}')
# Also fetch Prometheus server time so evidence carries scrape-clock skew
# context — Codex iter-1 P1 follow-up.
PROM_TIME=$(query 'time()')

# Status coexist guard (Codex iter-3 P1 absorb). Both DELIVERED and SUCCESS
# active in the same 5m window → numerator double-counts → evidence
# rejected. Each query above uses `> 0` filter so a null result means
# rate==0 (label inactive); non-null means active.
status_coexist_active() {
  if [[ "$DELIVERED_RATE" != "null" && "$SUCCESS_LABEL_RATE" != "null" ]]; then
    echo "yes"
  else
    echo "no"
  fi
}
COEXIST_ACTIVE="$(status_coexist_active)"

# Verdict logic — match the boolean composition in the recording rule.
# Coverage + time-gate + non-coexist must all pass before stable_30d=1
# can be trusted.
verdict() {
  if [[ "$OBS_COVERAGE" == "null" ]]; then
    echo "OBSERVATION_ABSENT"
    return
  fi
  # Coverage threshold matches recording-rule composite gate (0.99).
  cov_ready="$(awk -v c="$OBS_COVERAGE" 'BEGIN { print (c+0 >= 0.99) ? "yes" : "no" }')"
  if [[ "$cov_ready" == "no" ]]; then
    echo "OBSERVATION_ABSENT"
    return
  fi
  # Codex iter-3 P1/statusCoexist: terminal label coexist invalidates the
  # success_rate numerator (double-count). Reject as OBSERVATION_ABSENT
  # (canonical label PR required before evidence acceptance — RB §3.5).
  if [[ "$COEXIST_ACTIVE" == "yes" ]]; then
    echo "OBSERVATION_ABSENT"
    return
  fi
  # Codex iter-2 P0/timeGate: natural 30-day mark (2592000s) must arrive
  # before any verdict beyond OBSERVATION_ABSENT can be M8_DOD_BLOCKER_MET.
  if [[ "$ELAPSED_SEC" == "null" ]]; then
    echo "OBSERVATION_ABSENT"
    return
  fi
  natural_30d="$(awk -v e="$ELAPSED_SEC" 'BEGIN { print (e+0 >= 2592000) ? "yes" : "no" }')"
  if [[ "$natural_30d" == "no" ]]; then
    # Coverage OK but natural 30d mark not yet arrived. UNSTABLE is wrong
    # (no predicate failed); use a distinct WINDOW_PRE_NATURAL30D verdict.
    echo "WINDOW_PRE_NATURAL30D"
    return
  fi
  if [[ "$STABLE_NOW" == "1" ]]; then
    echo "M8_DOD_BLOCKER_MET"
  elif [[ "$STABLE_NOW" == "0" ]]; then
    echo "UNSTABLE"
  else
    echo "UNKNOWN"
  fi
}

VERDICT="$(verdict)"

# Anti-pattern guard (Codex `019e8c24`): generated_at uses `date -u` from
# the operator workstation clock; we DO NOT use Prometheus `time()` to
# backdate the field. Evidence is the live read at the time of execution.
GENERATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat >"$OUT" <<EOF
{
  "schema_version": "m7-v1-30day-stable-evidence/v3",
  "generated_at": "${GENERATED_AT}",
  "prometheus_time_unix": ${PROM_TIME},
  "context": "${CONTEXT}",
  "namespace": "platform-prod",
  "m7_live_unix": 1779494400,
  "natural_30day_mark_unix": 1782086400,
  "composite_predicates": {
    "dispatch_success_rate_30d": ${SUCCESS_RATE},
    "dlq_burn_24h_max_30d": ${BURN_24H_MAX},
    "critical_alert_minutes_30d": ${ALERT_MINUTES},
    "observation_coverage_30d": ${OBS_COVERAGE},
    "elapsed_seconds_since_m7_live": ${ELAPSED_SEC}
  },
  "supplementary_predicates": {
    "dlq_burn_72h_max_30d": ${BURN_72H_MAX}
  },
  "thresholds": {
    "dispatch_success_rate_30d_min": 0.995,
    "dlq_burn_24h_max_30d_max": 1.0,
    "critical_alert_minutes_30d_max": 0,
    "observation_coverage_30d_min": 0.99,
    "elapsed_seconds_since_m7_live_min": 2592000,
    "dlq_burn_72h_max_30d_max_supplementary": 1.0
  },
  "stable_30d_now": ${STABLE_NOW},
  "status_label_coexist_active": "${COEXIST_ACTIVE}",
  "verdict": "${VERDICT}",
  "anti_pattern_guards": {
    "shorten_30day_clock": false,
    "convert_m7_green_prematurely": false,
    "backdate_evidence": false,
    "mutate_cluster_state": false,
    "coverage_required_before_green": true,
    "natural_30day_mark_required_before_green": true
  }
}
EOF

echo "evidence: $OUT"
echo "verdict:  $VERDICT"

case "$VERDICT" in
  M8_DOD_BLOCKER_MET) exit 0 ;;
  WINDOW_PRE_NATURAL30D) exit 1 ;;
  UNSTABLE) exit 2 ;;
  OBSERVATION_ABSENT) exit 3 ;;
  *) exit 3 ;;
esac
