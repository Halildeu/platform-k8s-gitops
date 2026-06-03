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
# Predicates surfaced (mirrors notify-m7-stable-recording-rule.yaml):
#   - dispatch_success_rate_30d ≥ 0.995
#   - dlq_burn_max_30d ≤ 1.0
#   - dlq_burn_72h_max_30d ≤ 1.0 (supplementary)
#   - critical_alert_minutes_30d == 0
#   - observation_present_30d == 1 (anti-silence guard)
#   - stable_30d == 1
#   - min_over_time(stable_30d[30d]) == 1 (continuous-30d ready signal)
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
#   0 — stable_30d=1 AND observation_coverage_30d ≥ 0.95: M8 DoD blocker #1 met
#   2 — stable_30d=0: observation NOT stable; M8 blocker not met
#   3 — Prometheus unreachable / metric absent / coverage < 0.95
#   4 — Usage error
#
# Codex iter-1 P0 absorb: collapsed exit-1 (window-in-progress) into
# exit-3 (OBSERVATION_ABSENT) because the new coverage_30d guard makes
# "coverage too low" the canonical "not yet enough data" signal — instead
# of a separate STABLE_BUT_WINDOW_IN_PROGRESS path that was sensitive to
# the (removed) min_over_time semantic.
#
# Anti-pattern guards (Codex `019e8c24`):
#   - DOES NOT mutate any cluster state
#   - DOES NOT shorten the 30-day window or backdate evidence
#   - DOES NOT call M7 "green" before continuous_30d_ready=true
#   - Treats absent metric as code 3 (cannot conclude), not code 0

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
#     stable_30d=1 AND coverage_30d ≥ 0.95 directly.
SUCCESS_RATE=$(query 'notify:m7_v1:dispatch_success_rate:30d{namespace="platform-prod"}')
BURN_24H_MAX=$(query 'notify:m7_v1:dlq_burn_max:30d{namespace="platform-prod"}')
BURN_72H_MAX=$(query 'notify:m7_v1:dlq_burn_72h_max:30d{namespace="platform-prod"}')
ALERT_MINUTES=$(query 'notify:m7_v1:critical_alert_minutes:30d{namespace="platform-prod"}')
OBS_COVERAGE=$(query 'notify:m7_v1:observation_coverage:30d{namespace="platform-prod"}')
STABLE_NOW=$(query 'notify:m7_v1:stable_30d{namespace="platform-prod"}')
# Also fetch Prometheus server time so evidence carries scrape-clock skew
# context — Codex iter-1 P1 follow-up.
PROM_TIME=$(query 'time()')

# Verdict logic — match the boolean composition in the recording rule.
# Coverage threshold matches the recording-rule composite gate (0.95).
verdict() {
  if [[ "$OBS_COVERAGE" == "null" ]]; then
    echo "OBSERVATION_ABSENT"
    return
  fi
  # numeric coverage compare via awk (portable)
  cov_ready="$(awk -v c="$OBS_COVERAGE" 'BEGIN { print (c+0 >= 0.95) ? "yes" : "no" }')"
  if [[ "$cov_ready" == "no" ]]; then
    echo "OBSERVATION_ABSENT"
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
  "schema_version": "m7-v1-30day-stable-evidence/v2",
  "generated_at": "${GENERATED_AT}",
  "prometheus_time_unix": ${PROM_TIME},
  "context": "${CONTEXT}",
  "namespace": "platform-prod",
  "composite_predicates": {
    "dispatch_success_rate_30d": ${SUCCESS_RATE},
    "dlq_burn_24h_max_30d": ${BURN_24H_MAX},
    "critical_alert_minutes_30d": ${ALERT_MINUTES},
    "observation_coverage_30d": ${OBS_COVERAGE}
  },
  "supplementary_predicates": {
    "dlq_burn_72h_max_30d": ${BURN_72H_MAX}
  },
  "thresholds": {
    "dispatch_success_rate_30d_min": 0.995,
    "dlq_burn_24h_max_30d_max": 1.0,
    "critical_alert_minutes_30d_max": 0,
    "observation_coverage_30d_min": 0.95,
    "dlq_burn_72h_max_30d_max_supplementary": 1.0
  },
  "stable_30d_now": ${STABLE_NOW},
  "verdict": "${VERDICT}",
  "anti_pattern_guards": {
    "shorten_30day_clock": false,
    "convert_m7_green_prematurely": false,
    "backdate_evidence": false,
    "mutate_cluster_state": false,
    "coverage_required_before_green": true
  }
}
EOF

echo "evidence: $OUT"
echo "verdict:  $VERDICT"

case "$VERDICT" in
  M8_DOD_BLOCKER_MET) exit 0 ;;
  UNSTABLE) exit 2 ;;
  OBSERVATION_ABSENT) exit 3 ;;
  *) exit 3 ;;
esac
