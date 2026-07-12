#!/usr/bin/env bash
# k3d node-container pod-CIDR -> WireGuard-overlay SNAT reconcile loop (#186/#1867).
# Runs on the host; applies the SNAT rule INSIDE the k3d node container so pod
# traffic (POD_CIDR) to the overlay is masqueraded to the node's docker IP before
# it reaches the host (where k3d-wg-masq-host-rule.sh does the wg0 stage).
#
# Config is deployment desired-state (EnvironmentFile), NOT script defaults —
# a wrong default (prod's 10.42) on the test node was the 2026-07-12 I6 root cause.
set -u
POD_CIDR="${WGMASQ_POD_CIDR:?WGMASQ_POD_CIDR required (test=10.44.0.0/16, prod=10.42.0.0/16)}"
NODE="${WGMASQ_NODE:?WGMASQ_NODE required (e.g. k3d-test-server-0)}"
WG_CIDR="${WGMASQ_WG_CIDR:-10.99.0.0/24}"
INTERVAL="${WGMASQ_INTERVAL:-20}"
LOG="${WGMASQ_LOG:-/var/log/k3d-wg-masq.log}"
log(){ printf '%s %s\n' "$(date -Is)" "$*" >>"$LOG" 2>/dev/null || true; }
log "start node=$NODE pod=$POD_CIDR wg=$WG_CIDR interval=$INTERVAL"
while true; do
  if docker ps --format '{{.Names}}' | grep -q "^${NODE}$"; then
    if ! docker exec "$NODE" iptables -w -t nat -C POSTROUTING -s "$POD_CIDR" -d "$WG_CIDR" -j MASQUERADE 2>/dev/null; then
      if docker exec "$NODE" iptables -w -t nat -A POSTROUTING -s "$POD_CIDR" -d "$WG_CIDR" -j MASQUERADE 2>/dev/null; then
        log "RE-APPLIED node masq (was missing)"
      else
        log "FAILED apply node masq"
      fi
    fi
  else log "node $NODE not running"; fi
  sleep "$INTERVAL"
done
