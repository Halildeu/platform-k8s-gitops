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
#
# The `drill` action proves ONLY the chain-body apply/populate/verify/flush/delete
# PRIMITIVES + rule shapes on THROWAWAY DETACHED scratch chains
# K3D_WG_MASQ_NAT_DRILL / K3D_WG_MASQ_FWD_DRILL that are NEVER jumped from
# POSTROUTING/FORWARD — so they carry ZERO traffic and the live owned chains
# (K3D_WG_MASQ_NAT/FWD, the ATS live-STT masq path) are NEVER touched. It does NOT
# exercise the built-in POSTROUTING/FORWARD jump removal or hooked-chain deletion
# semantics — those are proven ONLY by a captured historical LIVE rollback. The drill
# is therefore necessary-but-not-sufficient for `rollback-defined`.
set -euo pipefail

WG_CIDR="${WGMASQ_WG_CIDR:-10.99.0.0/24}"
WG_IF="${WGMASQ_WG_IF:-wg0}"
NODE="${WGMASQ_NODE:?WGMASQ_NODE required (e.g. k3d-test-server-0)}"
NET="${WGMASQ_NETWORK:?WGMASQ_NETWORK required (docker network name, e.g. platform-test-net)}"
LOG="${WGMASQ_HOST_LOG:-/var/log/k3d-wg-masq-host-rule.log}"
LOCK="${WGMASQ_LOCK:-/run/lock/k3d-wg-masq.lock}"
NAT_CHAIN="K3D_WG_MASQ_NAT"
FWD_CHAIN="K3D_WG_MASQ_FWD"
# Throwaway scratch chains for the `drill` action — NEVER jumped from a base chain.
NAT_DRILL="${NAT_CHAIN}_DRILL"
FWD_DRILL="${FWD_CHAIN}_DRILL"
# Dedicated NON-BLOCKING lock so concurrent drills never adopt each other's scratch
# state on the fixed chain names. Separate from the main $LOCK.
DRILL_LOCK="${WGMASQ_DRILL_LOCK:-/run/lock/k3d-wg-masq-drill.lock}"
# Versioned mechanism id, emitted on the DRILL line + expected in historical evidence.
ROLLBACK_MECH_VERSION="k3d-wg-masq.rollback.v2"
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
  # position-1 invariant: the owned jump must be the FIRST rule in each base chain
  # (else Docker/UFW may terminal-MASQUERADE first and our owned counter loses meaning)
  [ "$(iptables -w -t nat    -S POSTROUTING 2>/dev/null | grep '^-A POSTROUTING' | head -1)" = "-A POSTROUTING -j $NAT_CHAIN" ] || { echo "nat jump not at position 1" >&2; return 1; }
  [ "$(iptables -w -t filter -S FORWARD     2>/dev/null | grep '^-A FORWARD'     | head -1)" = "-A FORWARD -j $FWD_CHAIN" ]     || { echo "fwd jump not at position 1" >&2; return 1; }
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
# --- drill (non-destructive scratch-chain apply+rollback mechanism proof) -----------
drill_cleanup() { # flush+delete both scratch chains; idempotent, tolerant
  iptables -w -t nat    -F "$NAT_DRILL" 2>/dev/null || true; iptables -w -t nat    -X "$NAT_DRILL" 2>/dev/null || true
  iptables -w -t filter -F "$FWD_DRILL" 2>/dev/null || true; iptables -w -t filter -X "$FWD_DRILL" 2>/dev/null || true
}
drill_rules() { iptables -w -t "$1" -S "$2" 2>/dev/null | grep -c '^-A' || true; }
chain_absent() { ! iptables -w -t "$1" -S "$2" >/dev/null 2>&1; }
drill_line() { # $1=apply $2=rollback $3=chainsAbsent
  printf 'DRILL applyOk=%s rollbackOk=%s chainsAbsentAfter=%s rollbackMechanismVersion=%s scope=detached-scratch-chain\n' \
    "$1" "$2" "$3" "$ROLLBACK_MECH_VERSION"
}
do_drill() {
  preflight
  # Dedicated NON-BLOCKING lock: if another drill holds it, fail-closed rather than
  # wait for / adopt its scratch-chain state on the fixed DRILL chain names.
  exec 8>"$DRILL_LOCK"
  if ! flock -n 8; then
    echo "another drill holds $DRILL_LOCK; refusing to adopt its scratch state" >&2
    drill_line 0 0 0
    return 1
  fi
  drill_cleanup   # idempotent: clear any leftover scratch chains before applying
  # Signal-safe safety net: from here until an explicit verified rollback, best-effort
  # flush+delete both scratch chains on EXIT/INT/TERM.
  trap 'drill_cleanup' EXIT INT TERM
  # Create + populate the SCRATCH chains. NO `-I POSTROUTING`/`-I FORWARD` jump is ever
  # emitted for them, so they are dead-ends carrying zero traffic. `|| true` keeps set -e
  # from skipping the rollback below; the apply is verified by rule-count, not exit code.
  iptables -w -t nat    -N "$NAT_DRILL" 2>/dev/null || true
  iptables -w -t filter -N "$FWD_DRILL" 2>/dev/null || true
  iptables -w -t nat    -A "$NAT_DRILL" -s "$NODE_IP/32" -d "$WG_CIDR" -o "$WG_IF" -j MASQUERADE 2>/dev/null || true
  iptables -w -t filter -A "$FWD_DRILL" -i "$BRIDGE" -o "$WG_IF" -s "$NODE_IP/32" -d "$WG_CIDR" -j ACCEPT 2>/dev/null || true
  iptables -w -t filter -A "$FWD_DRILL" -i "$WG_IF" -o "$BRIDGE" -s "$WG_CIDR" -d "$NODE_IP/32" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true
  local apply_ok=0 rollback_ok=0 chains_absent=0
  if iptables -w -t nat -S "$NAT_DRILL" >/dev/null 2>&1 \
     && iptables -w -t filter -S "$FWD_DRILL" >/dev/null 2>&1 \
     && [ "$(drill_rules nat "$NAT_DRILL")" = 1 ] \
     && [ "$(drill_rules filter "$FWD_DRILL")" = 2 ]; then
    apply_ok=1
  fi
  drill_cleanup   # explicit rollback: flush + delete both scratch chains
  if chain_absent nat "$NAT_DRILL" && chain_absent filter "$FWD_DRILL"; then
    chains_absent=1; rollback_ok=1
    trap - EXIT INT TERM   # explicit rollback verified — disarm the safety net
  fi
  # success (all three = 1) is emitted ONLY after explicit rollback + absence verify.
  drill_line "$apply_ok" "$rollback_ok" "$chains_absent"
  log drill "apply=${apply_ok} rollback=${rollback_ok} absent=${chains_absent}"
  [ "$apply_ok" = 1 ] && [ "$rollback_ok" = 1 ] && [ "$chains_absent" = 1 ]
}

ACTION="${1:-apply}"
case "$ACTION" in apply|check|rollback|drill) ;; *) echo "usage: $0 {apply|check|rollback|drill}" >&2; exit 2;; esac
# serialize the WHOLE operation (service ExecStartPost + drift timer + manual apply)
exec 9>"$LOCK"; flock 9
"do_${ACTION}"
