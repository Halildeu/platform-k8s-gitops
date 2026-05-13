#!/usr/bin/env bash
# scripts/deploy/gate-stability-window.sh
#
# Codex 019e2319 iter-3 AGREE — PR-2 of the Deployment Contract Drift Gate
# initiative. Runs AFTER Gate 1c (immediate readiness) in deploy workflows.
# Asserts that a freshly-rolled Deployment stays stable for a catalog-driven
# window (2 min default; 3 min for services with jvm_warmup_extra=true).
#
# Closes the bug class where rollout completes, Gate 1c sees readiness=200,
# then the new pod crashes 30-60 s later because the management server
# returned to a 404 — exactly the endpoint-admin probe drift fingerprint.
#
# Fail conditions (any of):
#   - Pod UID churn within the window (new pod spawned mid-window)
#   - container `waiting.reason == CrashLoopBackOff`
#   - container.restartCount increased above the start-of-window snapshot
#   - deploy.status.updatedReplicas (treat null as 0) != spec.replicas
#   - deploy.status.readyReplicas   (treat null as 0) != spec.replicas
#   - >1 active ReplicaSet (spec.replicas > 0) with newest ready=0
#   - Deployment condition Progressing.status == False
#   - Deployment condition ReplicaFailure.status == True
#
# Usage:
#   gate-stability-window.sh \
#     --service <name> \
#     --context <kubectl-context> \
#     --namespace <namespace> \
#     [--catalog <services.yaml>] \
#     [--window-seconds <int>] \
#     [--poll-seconds <int>]
#
# Exit:
#   0 — stable across window
#   1 — instability detected
#   2 — bad invocation / exec error

set -euo pipefail

CATALOG="docs/operations/services.yaml"
WINDOW_OVERRIDE=""
POLL_SECONDS=20
SERVICE=""
CONTEXT=""
NAMESPACE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service) SERVICE="$2"; shift 2 ;;
    --context) CONTEXT="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --catalog) CATALOG="$2"; shift 2 ;;
    --window-seconds) WINDOW_OVERRIDE="$2"; shift 2 ;;
    --poll-seconds) POLL_SECONDS="$2"; shift 2 ;;
    *) echo "ERR: unknown arg: $1" >&2; exit 2 ;;
  esac
done

[[ -z "$SERVICE" || -z "$CONTEXT" || -z "$NAMESPACE" ]] && {
  echo "ERR: --service, --context, --namespace required" >&2
  exit 2
}

if [[ ! -f "$CATALOG" ]]; then
  echo "ERR: catalog not found: $CATALOG" >&2
  exit 2
fi

# Resolve window from catalog (jvm_warmup_extra → +60s) unless overridden.
if [[ -n "$WINDOW_OVERRIDE" ]]; then
  WINDOW_SECONDS="$WINDOW_OVERRIDE"
else
  WINDOW_SECONDS=$(python3 - <<PY
import sys, yaml
catalog = yaml.safe_load(open("$CATALOG"))
for svc in catalog.get("services", []):
    if svc.get("name") == "$SERVICE":
        base = 120
        if svc.get("jvm_warmup_extra"):
            base = 180
        print(base)
        sys.exit(0)
# unknown service → default 120
print(120)
PY
)
fi

echo "[gate-stability] service=$SERVICE context=$CONTEXT ns=$NAMESPACE window=${WINDOW_SECONDS}s poll=${POLL_SECONDS}s"

# ---- Helpers ----

KUBECTL=(kubectl "--context=$CONTEXT" "-n" "$NAMESPACE")

deploy_json() {
  "${KUBECTL[@]}" get deploy "$SERVICE" -o json 2>/dev/null
}

pod_list_json() {
  "${KUBECTL[@]}" get pod \
    -l "app.kubernetes.io/name=$SERVICE" \
    --field-selector=status.phase=Running \
    -o json 2>/dev/null
}

rs_list_json() {
  "${KUBECTL[@]}" get rs \
    -l "app.kubernetes.io/name=$SERVICE" \
    -o json 2>/dev/null
}

fail() {
  echo "::error::stability window FAIL: $1"
  exit 1
}

# ---- Initial snapshot (Gate 1c just passed → take canonical state) ----

DEPLOY_INITIAL=$(deploy_json) || fail "cannot fetch initial Deployment"
PODS_INITIAL=$(pod_list_json) || fail "cannot fetch initial pod list"

# Snapshot: pod UIDs + container restart counts
INITIAL_UIDS=$(echo "$PODS_INITIAL" | jq -r '
  .items
  | map(select(.metadata.deletionTimestamp == null))
  | sort_by(.metadata.creationTimestamp)
  | map(.metadata.uid)
  | join(",")
')
INITIAL_RESTARTS=$(echo "$PODS_INITIAL" | jq -r '
  .items
  | map(select(.metadata.deletionTimestamp == null))
  | sort_by(.metadata.creationTimestamp)
  | map(.status.containerStatuses[0].restartCount // 0)
  | join(",")
')

if [[ -z "$INITIAL_UIDS" ]]; then
  fail "no Running pods at start of window (rollout incomplete?)"
fi

echo "[gate-stability] initial snapshot: uids=$INITIAL_UIDS restarts=$INITIAL_RESTARTS"

# ---- Poll loop ----

DEADLINE=$(( $(date +%s) + WINDOW_SECONDS ))

while [[ $(date +%s) -lt $DEADLINE ]]; do
  sleep "$POLL_SECONDS"

  DEPLOY_NOW=$(deploy_json) || fail "Deployment query failed mid-window"
  PODS_NOW=$(pod_list_json) || fail "pod query failed mid-window"

  # 1. Pod UID churn?
  NOW_UIDS=$(echo "$PODS_NOW" | jq -r '
    .items
    | map(select(.metadata.deletionTimestamp == null))
    | sort_by(.metadata.creationTimestamp)
    | map(.metadata.uid)
    | join(",")
  ')
  if [[ "$NOW_UIDS" != "$INITIAL_UIDS" ]]; then
    fail "pod UID churn: initial=$INITIAL_UIDS now=$NOW_UIDS"
  fi

  # 2. CrashLoopBackOff?
  CRASH=$(echo "$PODS_NOW" | jq -r '
    .items[]
    | .status.containerStatuses[]?
    | select(.state.waiting.reason == "CrashLoopBackOff")
    | .name
  ')
  if [[ -n "$CRASH" ]]; then
    fail "container in CrashLoopBackOff: $CRASH"
  fi

  # 3. Restart count grew?
  NOW_RESTARTS=$(echo "$PODS_NOW" | jq -r '
    .items
    | map(select(.metadata.deletionTimestamp == null))
    | sort_by(.metadata.creationTimestamp)
    | map(.status.containerStatuses[0].restartCount // 0)
    | join(",")
  ')
  IFS=',' read -ra INIT_R <<< "$INITIAL_RESTARTS"
  IFS=',' read -ra NOW_R <<< "$NOW_RESTARTS"
  for i in "${!NOW_R[@]}"; do
    init_val="${INIT_R[$i]:-0}"
    now_val="${NOW_R[$i]:-0}"
    if (( now_val > init_val )); then
      fail "restart count increased: pod[$i] initial=$init_val now=$now_val"
    fi
  done

  # 4 + 5. updatedReplicas / readyReplicas vs spec.replicas (null → 0)
  DESIRED=$(echo "$DEPLOY_NOW" | jq -r '.spec.replicas // 0')
  UPDATED=$(echo "$DEPLOY_NOW" | jq -r '.status.updatedReplicas // 0')
  READY=$(echo "$DEPLOY_NOW" | jq -r '.status.readyReplicas // 0')
  if [[ "$UPDATED" != "$DESIRED" ]]; then
    fail "updatedReplicas=$UPDATED != desired=$DESIRED"
  fi
  if [[ "$READY" != "$DESIRED" ]]; then
    fail "readyReplicas=$READY != desired=$DESIRED"
  fi

  # 6. >1 active RS + newest ready=0
  RS_NOW=$(rs_list_json) || fail "ReplicaSet query failed mid-window"
  RS_STALL=$(echo "$RS_NOW" | jq -r '
    .items
    | map(select((.spec.replicas // 0) > 0))
    | sort_by(.metadata.creationTimestamp)
    | if length > 1 and ((last.status.readyReplicas // 0) == 0)
      then last.metadata.name
      else "" end
  ')
  if [[ -n "$RS_STALL" ]]; then
    fail "ReplicaSet split stalled (newest ready=0): $RS_STALL"
  fi

  # 7 + 8. Deployment conditions
  PROG=$(echo "$DEPLOY_NOW" | jq -r '
    (.status.conditions // [])
    | map(select(.type == "Progressing"))
    | (.[0].status // "Unknown")
  ')
  REPLF=$(echo "$DEPLOY_NOW" | jq -r '
    (.status.conditions // [])
    | map(select(.type == "ReplicaFailure"))
    | (.[0].status // "False")
  ')
  if [[ "$PROG" == "False" ]]; then
    fail "Deployment Progressing=False"
  fi
  if [[ "$REPLF" == "True" ]]; then
    fail "Deployment ReplicaFailure=True"
  fi

  REMAINING=$(( DEADLINE - $(date +%s) ))
  echo "[gate-stability] tick clean (${REMAINING}s remaining): uids match, no crash, restarts=$NOW_RESTARTS, ready=$READY/$DESIRED"
done

echo "[gate-stability] PASS — $SERVICE stable across ${WINDOW_SECONDS}s window"
exit 0
