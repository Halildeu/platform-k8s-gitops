#!/usr/bin/env bash
# k3d node -> WireGuard-overlay HOST NAT + FORWARD wrapper (flannel gap, #186 / #1867).
#
# Two-stage SNAT: the node container masquerades pod-CIDR (10.44) -> node docker IP
# (k3d-wg-masq.sh, inside the node). This host wrapper owns the SECOND stage —
# node docker IP -> wg0 SNAT + bridge<->wg0 FORWARD (UFW `-P DROP` gap) — inside
# service-OWNED iptables chains. Every apply flock-serializes the WHOLE operation,
# normalizes owned jumps to exactly one at position 1, flush+rebuilds the owned
# chains (stale-free), and removes KNOWN legacy inline signatures (old 10.42 rule
# the pre-#1867 wrapper appended directly to base chains).
#
# Config is deployment desired-state (EnvironmentFile), NOT script defaults —
# test=10.44.0.0/16 + platform-test-net; prod=10.42.0.0/16 (bootstrap/k3d-*.yaml).
set -euo pipefail

WG_CIDR="${WGMASQ_WG_CIDR:-10.99.0.0/24}"
WG_IF="${WGMASQ_WG_IF:-wg0}"
NODE="${WGMASQ_NODE:?WGMASQ_NODE required (e.g. k3d-test-server-0)}"
NET="${WGMASQ_NETWORK:?WGMASQ_NETWORK required (docker network name, e.g. platform-test-net)}"
LOG="${WGMASQ_HOST_LOG:-/var/log/k3d-wg-masq-host-rule.log}"
LOCK="${WGMASQ_LOCK:-/run/lock/k3d-wg-masq.lock}"
NAT_CHAIN="K3D_WG_MASQ_NAT"
FWD_CHAIN="K3D_WG_MASQ_FWD"
# Known legacy inline host signature (pre-#1867 wrapper wrote this into the base
# POSTROUTING chain). Shape: <table> <chain> <spec...> (matches del_all's signature).
LEGACY_NAT=(nat POSTROUTING -s 10.42.0.0/16 -d "$WG_CIDR" -o "$WG_IF" -j MASQUERADE)

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
log() { printf '%s action=%s net=%s node_ip=%s bridge=%s wg=%s status=%s\n' "$(date +%Y-%m-%dT%H:%M:%S)" "${1}" "${NET}" "${NODE_IP:-?}" "${BRIDGE:-?}" "${WG_CIDR}" "${2}" >>"${LOG}" 2>/dev/null || true; }

preflight() {
  [ "$(net_driver)" = "bridge" ] || { echo "network '$NET' is not a bridge driver" >&2; return 1; }
  BRIDGE="$(resolve_bridge)"; NODE_IP="$(resolve_node_ip)"
  ip link show "$WG_IF"  >/dev/null 2>&1 || { echo "wg iface $WG_IF missing" >&2; return 1; }
  ip link show "$BRIDGE" >/dev/null 2>&1 || { echo "bridge $BRIDGE missing (network recreated? re-derive)" >&2; return 1; }
}
del_all() { local t="$1"; shift; while iptables -w -t "$t" -C "$@" 2>/dev/null; do iptables -w -t "$t" -D "$@"; done; }
count_jump() { iptables -w -t "$1" -S "$2" 2>/dev/null | grep -c -- "-j $3" || true; }
normalize_jump() { # $1=table $2=basechain $3=ownedchain — exactly one, at position 1
  del_all "$1" "$2" -j "$3"
  iptables -w -t "$1" -I "$2" 1 -j "$3"
}

do_apply() {
  preflight
  iptables -w -t nat    -N "$NAT_CHAIN" 2>/dev/null || true
  iptables -w -t filter -N "$FWD_CHAIN" 2>/dev/null || true
  normalize_jump nat    POSTROUTING "$NAT_CHAIN"
  normalize_jump filter FORWARD     "$FWD_CHAIN"
  iptables -w -t nat -F "$NAT_CHAIN"
  iptables -w -t nat -A "$NAT_CHAIN" -s "$NODE_IP/32" -d "$WG_CIDR" -o "$WG_IF" -j MASQUERADE
  iptables -w -t filter -F "$FWD_CHAIN"
  iptables -w -t filter -A "$FWD_CHAIN" -i "$BRIDGE" -o "$WG_IF" -s "$NODE_IP/32" -d "$WG_CIDR" -j ACCEPT
  iptables -w -t filter -A "$FWD_CHAIN" -i "$WG_IF" -o "$BRIDGE" -s "$WG_CIDR" -d "$NODE_IP/32" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  del_all "${LEGACY_NAT[@]}"   # bounded migration: drop known legacy inline host rule
  log apply ensured
}
do_check() {
  preflight
  [ "$(count_jump nat    POSTROUTING "$NAT_CHAIN")" = 1 ] || { echo "nat jump cardinality != 1" >&2; return 1; }
  [ "$(count_jump filter FORWARD     "$FWD_CHAIN")" = 1 ] || { echo "fwd jump cardinality != 1" >&2; return 1; }
  [ "$(iptables -w -t nat    -S "$NAT_CHAIN" 2>/dev/null | grep -c '^-A')" = 1 ] || { echo "nat owned rules != 1" >&2; return 1; }
  [ "$(iptables -w -t filter -S "$FWD_CHAIN" 2>/dev/null | grep -c '^-A')" = 2 ] || { echo "fwd owned rules != 2" >&2; return 1; }
  iptables -w -t nat    -C "$NAT_CHAIN" -s "$NODE_IP/32" -d "$WG_CIDR" -o "$WG_IF" -j MASQUERADE
  iptables -w -t filter -C "$FWD_CHAIN" -i "$BRIDGE" -o "$WG_IF" -s "$NODE_IP/32" -d "$WG_CIDR" -j ACCEPT
  iptables -w -t filter -C "$FWD_CHAIN" -i "$WG_IF" -o "$BRIDGE" -s "$WG_CIDR" -d "$NODE_IP/32" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  ! iptables -w -t nat -C "${LEGACY_NAT[@]:1}" 2>/dev/null || { echo "legacy 10.42 rule still present" >&2; return 1; }
  log check present
}
do_rollback() {
  del_all nat    POSTROUTING -j "$NAT_CHAIN"
  del_all filter FORWARD     -j "$FWD_CHAIN"
  iptables -w -t nat    -F "$NAT_CHAIN" 2>/dev/null || true; iptables -w -t nat    -X "$NAT_CHAIN" 2>/dev/null || true
  iptables -w -t filter -F "$FWD_CHAIN" 2>/dev/null || true; iptables -w -t filter -X "$FWD_CHAIN" 2>/dev/null || true
  del_all "${LEGACY_NAT[@]}"
  log rollback removed
}

ACTION="${1:-apply}"
case "$ACTION" in apply|check|rollback) ;; *) echo "usage: $0 {apply|check|rollback}" >&2; exit 2;; esac
# serialize the WHOLE operation (service ExecStartPost + drift timer + manual apply)
exec 9>"$LOCK"; flock 9
"do_${ACTION}"
