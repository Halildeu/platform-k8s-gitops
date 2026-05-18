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
  # Resolve jvm_warmup_extra for the service WITHOUT a YAML library — the
  # self-hosted deploy runner has no PyYAML, and the previous `import yaml`
  # crashed this gate on every backend deploy (ModuleNotFoundError). The
  # catalog is a flat `services:` list of 2-space `- name:` blocks with
  # 4-space scalar keys, so an indentation-anchored awk scan is exact here.
  #   service found + jvm_warmup_extra: true  → 180s
  #   service found + false / key absent      → 120s (default)
  #   service not found                       → 120s (default)
  WARMUP=$(awk -v svc="$SERVICE" '
    /^[^ ]/        { in_svc = 0 }                       # new top-level key → leave the services list
    /^  - name: /  { in_svc = ($3 == svc) }
    in_svc && /^    jvm_warmup_extra:/ { print $2; exit }
  ' "$CATALOG")
  if [[ "$WARMUP" == "true" ]]; then
    WINDOW_SECONDS=180
  else
    WINDOW_SECONDS=120
  fi
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

# Codex 019e233b review #3 — restart count map keyed by "pod_uid:container_name".
# Captures every container (sidecars too); previous version only watched
# containerStatuses[0].
restart_map_csv() {
  local pods_json="$1"
  echo "$pods_json" | jq -r '
    .items
    | map(select(.metadata.deletionTimestamp == null))
    | map(
        . as $p
        | (.status.containerStatuses // [])
        | map("\($p.metadata.uid):\(.name)=\(.restartCount // 0)")
      )
    | flatten
    | sort
    | join(",")
  '
}

# Codex 019e233b review #2 — shared t=0 check; same conditions run before
# the poll loop so an instant CrashLoop/ReplicaFailure cannot be normalized
# away by the first sleep.
check_state() {
  local label="$1"
  local deploy_now="$2"
  local pods_now="$3"
  local rs_now="$4"

  # CrashLoopBackOff?
  local crash
  crash=$(echo "$pods_now" | jq -r '
    .items[]
    | .status.containerStatuses[]?
    | select(.state.waiting.reason == "CrashLoopBackOff")
    | "\(.name)@\(.image)"
  ')
  if [[ -n "$crash" ]]; then
    fail "$label: container in CrashLoopBackOff: $crash"
  fi

  # updatedReplicas / readyReplicas vs desired (null → 0).
  local desired updated ready
  desired=$(echo "$deploy_now" | jq -r '.spec.replicas // 0')
  updated=$(echo "$deploy_now" | jq -r '.status.updatedReplicas // 0')
  ready=$(echo "$deploy_now"  | jq -r '.status.readyReplicas   // 0')
  if [[ "$updated" != "$desired" ]]; then
    fail "$label: updatedReplicas=$updated != desired=$desired"
  fi
  if [[ "$ready" != "$desired" ]]; then
    fail "$label: readyReplicas=$ready != desired=$desired"
  fi

  # ReplicaSet split (label-scoped: Gate 1d is single-service so the
  # label contract is authoritative within this window).
  local rs_stall
  rs_stall=$(echo "$rs_now" | jq -r '
    .items
    | map(select((.spec.replicas // 0) > 0))
    | sort_by(.metadata.creationTimestamp)
    | if length > 1 and ((last.status.readyReplicas // 0) == 0)
      then last.metadata.name
      else "" end
  ')
  if [[ -n "$rs_stall" ]]; then
    fail "$label: ReplicaSet split stalled (newest ready=0): $rs_stall"
  fi

  # Deployment conditions.
  local prog replf
  prog=$(echo "$deploy_now" | jq -r '
    (.status.conditions // [])
    | map(select(.type == "Progressing"))
    | (.[0].status // "Unknown")
  ')
  replf=$(echo "$deploy_now" | jq -r '
    (.status.conditions // [])
    | map(select(.type == "ReplicaFailure"))
    | (.[0].status // "False")
  ')
  if [[ "$prog" == "False" ]]; then
    fail "$label: Deployment Progressing=False"
  fi
  if [[ "$replf" == "True" ]]; then
    fail "$label: Deployment ReplicaFailure=True"
  fi
}

# ---- Initial snapshot (Gate 1c just passed → take canonical state) ----

DEPLOY_INITIAL=$(deploy_json) || fail "cannot fetch initial Deployment"
PODS_INITIAL=$(pod_list_json) || fail "cannot fetch initial pod list"
RS_INITIAL=$(rs_list_json) || fail "cannot fetch initial ReplicaSets"

# Snapshot: pod UIDs + (pod_uid:container_name)=restartCount map.
INITIAL_UIDS=$(echo "$PODS_INITIAL" | jq -r '
  .items
  | map(select(.metadata.deletionTimestamp == null))
  | sort_by(.metadata.creationTimestamp)
  | map(.metadata.uid)
  | join(",")
')
INITIAL_RESTARTS=$(restart_map_csv "$PODS_INITIAL")

if [[ -z "$INITIAL_UIDS" ]]; then
  fail "no Running pods at start of window (rollout incomplete?)"
fi

echo "[gate-stability] initial snapshot: uids=$INITIAL_UIDS"
echo "[gate-stability] initial restarts: $INITIAL_RESTARTS"

# Codex 019e233b review #2 — evaluate fail conditions AT t=0 before the
# first sleep. If the deployment is already broken when we enter the
# window, the gate must fail immediately, not silently after one tick.
check_state "t=0" "$DEPLOY_INITIAL" "$PODS_INITIAL" "$RS_INITIAL"

# ---- Poll loop ----

DEADLINE=$(( $(date +%s) + WINDOW_SECONDS ))

while [[ $(date +%s) -lt $DEADLINE ]]; do
  sleep "$POLL_SECONDS"

  DEPLOY_NOW=$(deploy_json) || fail "Deployment query failed mid-window"
  PODS_NOW=$(pod_list_json) || fail "pod query failed mid-window"
  RS_NOW=$(rs_list_json) || fail "ReplicaSet query failed mid-window"

  # Pod UID churn (window-specific — initial snapshot is canonical here).
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

  # Restart growth per (pod_uid:container_name) — Codex 019e233b review #3
  # captures sidecar restarts; previous code only watched containers[0].
  NOW_RESTARTS=$(restart_map_csv "$PODS_NOW")
  IFS=',' read -ra INIT_KV <<< "$INITIAL_RESTARTS"
  declare -A INIT_R_MAP=()
  for kv in "${INIT_KV[@]}"; do
    [[ -z "$kv" ]] && continue
    INIT_R_MAP["${kv%%=*}"]="${kv##*=}"
  done
  IFS=',' read -ra NOW_KV <<< "$NOW_RESTARTS"
  for kv in "${NOW_KV[@]}"; do
    [[ -z "$kv" ]] && continue
    key="${kv%%=*}"
    now_val="${kv##*=}"
    init_val="${INIT_R_MAP[$key]:-0}"
    if (( now_val > init_val )); then
      fail "restart count increased: $key initial=$init_val now=$now_val"
    fi
  done
  unset INIT_R_MAP

  # Shared state assertions (CrashLoop / updated / ready / RS split / conds)
  check_state "tick" "$DEPLOY_NOW" "$PODS_NOW" "$RS_NOW"

  DESIRED=$(echo "$DEPLOY_NOW" | jq -r '.spec.replicas // 0')
  READY=$(echo "$DEPLOY_NOW" | jq -r '.status.readyReplicas // 0')
  REMAINING=$(( DEADLINE - $(date +%s) ))
  echo "[gate-stability] tick clean (${REMAINING}s remaining): uids match, ready=$READY/$DESIRED, restart-map unchanged"
done

echo "[gate-stability] PASS — $SERVICE stable across ${WINDOW_SECONDS}s window"
exit 0
