#!/usr/bin/env bash
# check-tempo-canary.sh — preflight + smoke script for R11 tracing canary rollout.
#
# Risk #767 R11 (Tempo OTLP collector deploy tracing path'i bozabilir)
# safety-baseline preflight script. Run BEFORE flipping
# `MANAGEMENT_TRACING_ENABLED=true` on any service, and as the smoke
# check for the canary's first 5-10 minutes.
#
# Usage:
#   bash scripts/ops/check-tempo-canary.sh <test|prod>
#
# Exit codes:
#   0 — all preflight gates green; safe to apply canary
#   1 — at least one gate red; do NOT apply canary
#   2 — invocation error (env, kubectl context, etc.)
#
# Codex thread: 019e4448-e90a-7472-9e8c-d287c0fa7970 (R11 PR1 verdict
#   REVISE → Alt-B safety-baseline: monitoring + runbook + smoke script).
#
# Runbook: docs/runbooks/RB-tracing-canary-rollout.md

set -euo pipefail

ENV="${1:-test}"
if [[ "${ENV}" != "test" && "${ENV}" != "prod" ]]; then
  printf 'ERROR: usage: %s <test|prod>\n' "$0" >&2
  exit 2
fi

CTX="k3d-${ENV}"
NS="monitoring"
TEMPO_PORT_READY=3200   # Tempo readiness (HTTP) — chart default
TEMPO_PORT_GRPC=4317
TEMPO_PORT_HTTP=4318

log() { printf '\033[0;36m[tempo-canary-%s]\033[0m %s\n' "${ENV}" "$*" >&2; }
fail() { printf '\033[0;31m[tempo-canary-%s] FAIL: %s\033[0m\n' "${ENV}" "$*" >&2; }
ok() { printf '\033[0;32m[tempo-canary-%s] OK: %s\033[0m\n' "${ENV}" "$*" >&2; }

command -v kubectl >/dev/null || { fail "kubectl not found"; exit 2; }
kubectl --context "${CTX}" cluster-info >/dev/null 2>&1 || { fail "context ${CTX} not reachable"; exit 2; }

# --------------------------------------------------------------------
# Gate 1 — Tempo pod state
# --------------------------------------------------------------------
log "Gate 1/4 — Tempo pod state"
POD=$(kubectl --context "${CTX}" -n "${NS}" get pod -l app.kubernetes.io/name=tempo -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [[ -z "${POD}" ]]; then
  fail "Tempo pod not found (selector app.kubernetes.io/name=tempo in ns ${NS})"
  exit 1
fi
READY=$(kubectl --context "${CTX}" -n "${NS}" get pod "${POD}" -o jsonpath='{.status.containerStatuses[0].ready}')
RESTARTS=$(kubectl --context "${CTX}" -n "${NS}" get pod "${POD}" -o jsonpath='{.status.containerStatuses[0].restartCount}')
if [[ "${READY}" != "true" ]]; then
  fail "Tempo pod ${POD} not ready (ready=${READY})"
  exit 1
fi
ok "Tempo pod ${POD} ready (restarts=${RESTARTS})"

# --------------------------------------------------------------------
# Gate 2 — Tempo /ready endpoint
# --------------------------------------------------------------------
log "Gate 2/4 — Tempo /ready HTTP probe"
# Port-forward to the readiness port (3200 chart default).
kubectl --context "${CTX}" -n "${NS}" port-forward "pod/${POD}" "${TEMPO_PORT_READY}:${TEMPO_PORT_READY}" >/dev/null 2>&1 &
PF_PID=$!
trap 'kill ${PF_PID} 2>/dev/null || true' EXIT
sleep 3
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${TEMPO_PORT_READY}/ready" || echo "000")
kill ${PF_PID} 2>/dev/null || true
trap - EXIT
if [[ "${HTTP_CODE}" != "200" ]]; then
  fail "Tempo /ready returned ${HTTP_CODE} (expected 200) on :${TEMPO_PORT_READY}"
  exit 1
fi
ok "Tempo /ready returned 200"

# --------------------------------------------------------------------
# Gate 3 — OTLP receiver ports reachable (gRPC 4317 + HTTP 4318)
# --------------------------------------------------------------------
log "Gate 3/4 — OTLP receiver ports reachable"
for port in "${TEMPO_PORT_GRPC}" "${TEMPO_PORT_HTTP}"; do
  kubectl --context "${CTX}" -n "${NS}" port-forward "pod/${POD}" "${port}:${port}" >/dev/null 2>&1 &
  PF_PID=$!
  trap 'kill ${PF_PID} 2>/dev/null || true' EXIT
  sleep 2
  # We just verify the TCP socket accepts a connection; the OTLP
  # protocol semantics are beyond a shell-level probe.
  if (echo > "/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
    ok "OTLP port ${port} reachable"
  else
    fail "OTLP port ${port} NOT reachable"
    kill ${PF_PID} 2>/dev/null || true
    trap - EXIT
    exit 1
  fi
  kill ${PF_PID} 2>/dev/null || true
  trap - EXIT
done

# --------------------------------------------------------------------
# Gate 4 — Prometheus rule state: TempoDown + TempoOTLPIngestErrors
#          should be `inactive` (not firing).
# --------------------------------------------------------------------
log "Gate 4/4 — R11 alert state"
PROM_POD=$(kubectl --context "${CTX}" -n "${NS}" get pod -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [[ -z "${PROM_POD}" ]]; then
  fail "Prometheus pod not found — alert state cannot be queried"
  exit 1
fi
FIRING=$(kubectl --context "${CTX}" -n "${NS}" exec "${PROM_POD}" -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/alerts' 2>/dev/null | \
  jq -r '[.data.alerts[] | select(.labels.risk=="R11" and .state!="inactive")] | length' || echo "?")
if [[ "${FIRING}" == "?" || -z "${FIRING}" ]]; then
  fail "Could not query Prometheus alert state"
  exit 1
fi
if [[ "${FIRING}" != "0" ]]; then
  fail "R11 alerts already firing (count=${FIRING}); resolve before canary apply"
  kubectl --context "${CTX}" -n "${NS}" exec "${PROM_POD}" -c prometheus -- \
    wget -qO- 'http://localhost:9090/api/v1/alerts' 2>/dev/null | \
    jq -r '.data.alerts[] | select(.labels.risk=="R11") | "\(.state) \(.labels.alertname)"' >&2
  exit 1
fi
ok "No R11 alerts firing (0 active)"

# --------------------------------------------------------------------
# All gates green
# --------------------------------------------------------------------
log ""
log "All 4 preflight gates green — safe to apply tracing canary."
log "Next: follow docs/runbooks/RB-tracing-canary-rollout.md → 'Canary apply' section."
exit 0
