#!/usr/bin/env bash
# k3d pod -> WireGuard-overlay host NAT + FORWARD wrapper (flannel gap, #186 / #1867).
#
# Root cause of the 2026-07-12 I6 false-positive (pod->WG never actually worked):
#   1. masq CIDR was pinned to a WRONG value (prod's 10.42.0.0/16) while the test
#      cluster CIDR is 10.44.0.0/16 -> SNAT rule matched 0 packets.
#   2. the host FORWARD chain is `-P DROP` (+ufw-reject-forward); the wrapper set
#      SNAT but NEVER a FORWARD ACCEPT for bridge<->wg0, so forwarded pod/node
#      traffic to the overlay was dropped before egress.
#
# This wrapper idempotently reconciles THREE host rules (apply/check/rollback):
#   1. nat POSTROUTING SNAT : pod-CIDR -> wg0 -> host wg src (10.99.0.1)
#   2. filter FORWARD out   : k3d bridge -> wg0 (UFW default-DROP gap)
#   3. filter FORWARD return: wg0 -> k3d bridge
#
# Config is deployment desired-state (EnvironmentFile), NOT script defaults —
# test=10.44.0.0/16, prod=10.42.0.0/16 (bootstrap/k3d-{test,prod}.yaml). Fail-closed.
#
# BRIDGE recreation guard (Codex 019f55eb P2): the k3d docker bridge name is
# br-<network-id[:12]> and CHANGES if the docker network is recreated. So we
# derive it every run from the STABLE docker network NAME (WGMASQ_NETWORK), not a
# hard-pinned bridge id. WGMASQ_BRIDGE may override but is verified to exist.
set -euo pipefail

POD_CIDR="${WGMASQ_POD_CIDR:?WGMASQ_POD_CIDR required (test=10.44.0.0/16, prod=10.42.0.0/16)}"
WG_CIDR="${WGMASQ_WG_CIDR:-10.99.0.0/24}"
WG_IF="${WGMASQ_WG_IF:-wg0}"
LOG="${WGMASQ_HOST_LOG:-/var/log/k3d-wg-masq-host-rule.log}"

resolve_bridge() {
  if [ -n "${WGMASQ_BRIDGE:-}" ]; then
    printf '%s' "${WGMASQ_BRIDGE}"; return 0
  fi
  local net="${WGMASQ_NETWORK:?WGMASQ_NETWORK or WGMASQ_BRIDGE required}"
  local id
  id="$(docker network inspect "${net}" -f '{{.Id}}' 2>/dev/null | cut -c1-12)"
  [ -n "${id}" ] || { echo "cannot resolve docker network '${net}'" >&2; return 1; }
  printf 'br-%s' "${id}"
}
BRIDGE="$(resolve_bridge)"

log() { printf '%s action=%s pod=%s wg=%s if=%s br=%s status=%s\n' "$(date -Is)" "${1}" "${POD_CIDR}" "${WG_CIDR}" "${WG_IF}" "${BRIDGE}" "${2}" >>"${LOG}" 2>/dev/null || true; }
require_iface() {
  ip link show "${WG_IF}" >/dev/null 2>&1 || { echo "wg iface ${WG_IF} missing" >&2; return 1; }
  ip link show "${BRIDGE}" >/dev/null 2>&1 || { echo "bridge ${BRIDGE} missing (network recreated? re-derive)" >&2; return 1; }
}
ensure() { local t="$1"; shift; iptables -w -t "$t" -C "$@" 2>/dev/null || iptables -w -t "$t" -I "$@"; }
drop()   { local t="$1"; shift; local n=0; while iptables -w -t "$t" -C "$@" 2>/dev/null; do iptables -w -t "$t" -D "$@"; n=$((n+1)); done; echo "$n"; }

case "${1:-apply}" in
  apply)
    require_iface
    ensure nat    POSTROUTING -s "${POD_CIDR}" -d "${WG_CIDR}" -o "${WG_IF}" -j MASQUERADE
    ensure filter FORWARD -i "${BRIDGE}" -o "${WG_IF}" -d "${WG_CIDR}" -j ACCEPT
    ensure filter FORWARD -i "${WG_IF}" -o "${BRIDGE}" -s "${WG_CIDR}" -j ACCEPT
    log apply ensured
    ;;
  check)
    require_iface
    iptables -w -t nat    -C POSTROUTING -s "${POD_CIDR}" -d "${WG_CIDR}" -o "${WG_IF}" -j MASQUERADE
    iptables -w -t filter -C FORWARD -i "${BRIDGE}" -o "${WG_IF}" -d "${WG_CIDR}" -j ACCEPT
    iptables -w -t filter -C FORWARD -i "${WG_IF}" -o "${BRIDGE}" -s "${WG_CIDR}" -j ACCEPT
    log check present
    ;;
  rollback)
    r1="$(drop nat    POSTROUTING -s "${POD_CIDR}" -d "${WG_CIDR}" -o "${WG_IF}" -j MASQUERADE)"
    r2="$(drop filter FORWARD -i "${BRIDGE}" -o "${WG_IF}" -d "${WG_CIDR}" -j ACCEPT)"
    r3="$(drop filter FORWARD -i "${WG_IF}" -o "${BRIDGE}" -s "${WG_CIDR}" -j ACCEPT)"
    log rollback "nat=${r1} fwd_out=${r2} fwd_ret=${r3}"
    ;;
  *) echo "usage: $0 {apply|check|rollback}" >&2; exit 2 ;;
esac
