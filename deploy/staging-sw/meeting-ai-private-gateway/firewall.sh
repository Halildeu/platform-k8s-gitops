#!/usr/bin/env bash
set -euo pipefail

readonly CHAIN="PLATFORM_MAI_WG_IN"
readonly WG_INTERFACE="wg0"
readonly CLIENT_IP="10.99.0.2/32"
readonly SERVER_IP="10.99.0.1/32"
readonly SERVER_PORT="9447"

die() {
  printf 'meeting-ai firewall: %s\n' "$*" >&2
  exit 1
}

require_root() {
  [[ ${EUID} -eq 0 ]] || die "root is required"
  command -v iptables >/dev/null 2>&1 || die "iptables is required"
}

remove_jump() {
  while iptables -w 5 -C INPUT -d "${SERVER_IP}" -p tcp --dport "${SERVER_PORT}" -j "${CHAIN}" 2>/dev/null; do
    iptables -w 5 -D INPUT -d "${SERVER_IP}" -p tcp --dport "${SERVER_PORT}" -j "${CHAIN}"
  done
}

apply_rules() {
  ip link show "${WG_INTERFACE}" >/dev/null 2>&1 || die "${WG_INTERFACE} does not exist"
  ip -4 address show dev "${WG_INTERFACE}" | grep -Fq "10.99.0.1/" || \
    die "${WG_INTERFACE} does not own 10.99.0.1"

  iptables -w 5 -N "${CHAIN}" 2>/dev/null || true
  iptables -w 5 -F "${CHAIN}"
  iptables -w 5 -A "${CHAIN}" -i "${WG_INTERFACE}" -s "${CLIENT_IP}" \
    -d "${SERVER_IP}" -p tcp --dport "${SERVER_PORT}" \
    -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT
  iptables -w 5 -A "${CHAIN}" -m limit --limit 6/min --limit-burst 10 \
    -j LOG --log-prefix "mai-mtls-deny " --log-level 6
  iptables -w 5 -A "${CHAIN}" -j DROP

  remove_jump
  iptables -w 5 -I INPUT 1 -d "${SERVER_IP}" -p tcp --dport "${SERVER_PORT}" -j "${CHAIN}"
}

rollback_rules() {
  remove_jump
  if iptables -w 5 -nL "${CHAIN}" >/dev/null 2>&1; then
    iptables -w 5 -F "${CHAIN}"
    iptables -w 5 -X "${CHAIN}"
  fi
}

check_rules() {
  iptables -w 5 -C INPUT -d "${SERVER_IP}" -p tcp --dport "${SERVER_PORT}" -j "${CHAIN}"
  iptables -w 5 -C "${CHAIN}" -i "${WG_INTERFACE}" -s "${CLIENT_IP}" \
    -d "${SERVER_IP}" -p tcp --dport "${SERVER_PORT}" \
    -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT
  iptables -w 5 -C "${CHAIN}" -j DROP
}

require_root
case "${1:-}" in
  apply) apply_rules ;;
  rollback) rollback_rules ;;
  check) check_rules ;;
  *) die "usage: $0 {apply|check|rollback}" ;;
esac
