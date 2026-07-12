#!/usr/bin/env bash
# k3d node -> WireGuard-overlay HOST NAT + FORWARD wrapper (flannel gap, #186 / #1867).
#
# Two-stage SNAT: the node container masquerades pod-CIDR (10.44) -> node docker IP
# (k3d-wg-masq.sh, inside the node). This host wrapper owns the SECOND stage —
# node docker IP -> wg0 SNAT, plus the bridge<->wg0 FORWARD that UFW's `-P DROP`
# otherwise blocks. Reconciled into DEDICATED, service-OWNED iptables chains so:
#   (a) the SNAT source is the actual node IP (not the dead pod-CIDR the old I6
#       wrapper matched -> 0 hits), so the rule really carries traffic;
#   (b) each apply FLUSHES+rebuilds the owned chains -> stale bridge/CIDR rules
#       cannot accumulate on docker-network recreation;
#   (c) rollback removes only owned jumps/chains, never UFW/Docker/kube rules.
#
# Config is deployment desired-state (EnvironmentFile), NOT script defaults —
# test=10.44.0.0/16 + platform-test-net; prod=10.42.0.0/16 (bootstrap/k3d-*.yaml).
set -euo pipefail

WG_CIDR="${WGMASQ_WG_CIDR:-10.99.0.0/24}"
WG_IF="${WGMASQ_WG_IF:-wg0}"
NODE="${WGMASQ_NODE:?WGMASQ_NODE required (e.g. k3d-test-server-0)}"
NET="${WGMASQ_NETWORK:?WGMASQ_NETWORK required (docker network name, e.g. platform-test-net)}"
LOG="${WGMASQ_HOST_LOG:-/var/log/k3d-wg-masq-host-rule.log}"
NAT_CHAIN="K3D_WG_MASQ_NAT"
FWD_CHAIN="K3D_WG_MASQ_FWD"

net_driver() { docker network inspect "$NET" -f '{{.Driver}}' 2>/dev/null; }
resolve_bridge() {
  local b id
  b="$(docker network inspect "$NET" -f '{{index .Options "com.docker.network.bridge.name"}}' 2>/dev/null)"
  [ -n "$b" ] && { printf '%s' "$b"; return 0; }
  id="$(docker network inspect "$NET" -f '{{.Id}}' 2>/dev/null)"
  [[ "$id" =~ ^[0-9a-f]{12,64}$ ]] || { echo "bad/empty network id for '$NET'" >&2; return 1; }
  printf 'br-%s' "${id:0:12}"
}
resolve_node_ip() {
  local ip
  ip="$(docker inspect "$NODE" -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" 2>/dev/null)"
  [[ "$ip" =~ ^[0-9]+(\.[0-9]+){3}$ ]] || { echo "cannot resolve $NODE IP on $NET" >&2; return 1; }
  printf '%s' "$ip"
}
log() { printf '%s action=%s net=%s node_ip=%s bridge=%s wg=%s status=%s\n' "$(date -Is)" "${1}" "${NET}" "${NODE_IP:-?}" "${BRIDGE:-?}" "${WG_CIDR}" "${2}" >>"${LOG}" 2>/dev/null || true; }

preflight() {
  [ "$(net_driver)" = "bridge" ] || { echo "network '$NET' is not a bridge driver" >&2; return 1; }
  BRIDGE="$(resolve_bridge)"; NODE_IP="$(resolve_node_ip)"
  ip link show "$WG_IF"  >/dev/null 2>&1 || { echo "wg iface $WG_IF missing" >&2; return 1; }
  ip link show "$BRIDGE" >/dev/null 2>&1 || { echo "bridge $BRIDGE missing (network recreated? re-derive)" >&2; return 1; }
}

case "${1:-apply}" in
  apply)
    preflight
    iptables -w -t nat    -N "$NAT_CHAIN" 2>/dev/null || true
    iptables -w -t filter -N "$FWD_CHAIN" 2>/dev/null || true
    iptables -w -t nat    -C POSTROUTING -j "$NAT_CHAIN" 2>/dev/null || iptables -w -t nat    -I POSTROUTING 1 -j "$NAT_CHAIN"
    iptables -w -t filter -C FORWARD     -j "$FWD_CHAIN" 2>/dev/null || iptables -w -t filter -I FORWARD 1     -j "$FWD_CHAIN"
    iptables -w -t nat -F "$NAT_CHAIN"
    iptables -w -t nat -A "$NAT_CHAIN" -s "$NODE_IP/32" -d "$WG_CIDR" -o "$WG_IF" -j MASQUERADE
    iptables -w -t filter -F "$FWD_CHAIN"
    iptables -w -t filter -A "$FWD_CHAIN" -i "$BRIDGE" -o "$WG_IF" -s "$NODE_IP/32" -d "$WG_CIDR" -j ACCEPT
    iptables -w -t filter -A "$FWD_CHAIN" -i "$WG_IF" -o "$BRIDGE" -s "$WG_CIDR" -d "$NODE_IP/32" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    log apply ensured
    ;;
  check)
    preflight
    iptables -w -t nat    -C POSTROUTING -j "$NAT_CHAIN"
    iptables -w -t filter -C FORWARD     -j "$FWD_CHAIN"
    iptables -w -t nat    -C "$NAT_CHAIN" -s "$NODE_IP/32" -d "$WG_CIDR" -o "$WG_IF" -j MASQUERADE
    iptables -w -t filter -C "$FWD_CHAIN" -i "$BRIDGE" -o "$WG_IF" -s "$NODE_IP/32" -d "$WG_CIDR" -j ACCEPT
    iptables -w -t filter -C "$FWD_CHAIN" -i "$WG_IF" -o "$BRIDGE" -s "$WG_CIDR" -d "$NODE_IP/32" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    log check present
    ;;
  rollback)
    iptables -w -t nat    -D POSTROUTING -j "$NAT_CHAIN" 2>/dev/null || true
    iptables -w -t filter -D FORWARD     -j "$FWD_CHAIN" 2>/dev/null || true
    iptables -w -t nat    -F "$NAT_CHAIN" 2>/dev/null || true; iptables -w -t nat    -X "$NAT_CHAIN" 2>/dev/null || true
    iptables -w -t filter -F "$FWD_CHAIN" 2>/dev/null || true; iptables -w -t filter -X "$FWD_CHAIN" 2>/dev/null || true
    log rollback removed
    ;;
  *) echo "usage: $0 {apply|check|rollback}" >&2; exit 2 ;;
esac
