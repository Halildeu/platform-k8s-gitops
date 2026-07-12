#!/usr/bin/env bash
# Offline test for k3d-wg-masq-host-rule.sh — mocks iptables/docker/ip via PATH shims,
# runs apply/check/rollback, asserts the owned-chain rule model + fail-closed guards.
# No root, no real cluster. Run: bash tests/test-host-rule.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SUT="$HERE/../k3d-wg-masq-host-rule.sh"
PASS=0; FAIL=0
ok(){ echo "PASS: $1"; PASS=$((PASS+1)); }
bad(){ echo "FAIL: $1"; FAIL=$((FAIL+1)); }

setup_mocks() { # $1=mode: normal | badnet
  MOCK="$(mktemp -d)"; CALLS="$MOCK/iptables.calls"; : >"$CALLS"
  cat >"$MOCK/docker" <<EOF
#!/usr/bin/env bash
# network inspect / container inspect mocks
if [ "\$1" = "network" ] && [ "\$2" = "inspect" ]; then
  net="\$3"
  if [ "${1:-}" = "badnet" ] || [ "\$net" = "no-such-net" ]; then exit 1; fi
  case "\$*" in
    *Driver*) echo "bridge";;
    *bridge.name*) echo "";;               # no explicit bridge name option
    *.Id*) echo "b863e3369c00deadbeef0123";;
  esac
  exit 0
fi
if [ "\$1" = "inspect" ]; then echo "172.19.0.3"; exit 0; fi
exit 0
EOF
  # badnet variant: docker network inspect fails
  if [ "$1" = "badnet" ]; then
    cat >"$MOCK/docker" <<EOF
#!/usr/bin/env bash
[ "\$1" = "network" ] && exit 1
[ "\$1" = "inspect" ] && { echo "172.19.0.3"; exit 0; }
exit 0
EOF
  fi
  cat >"$MOCK/ip" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  cat >"$MOCK/iptables" <<EOF
#!/usr/bin/env bash
echo "\$*" >>"$CALLS"
# -C (check) returns 1 (absent) so apply proceeds to -N/-I/-A
for a in "\$@"; do [ "\$a" = "-C" ] && exit 1; done
exit 0
EOF
  chmod +x "$MOCK/docker" "$MOCK/ip" "$MOCK/iptables"
  export PATH="$MOCK:$PATH"
}
env_ok() { export WGMASQ_NODE=k3d-test-server-0 WGMASQ_NETWORK=platform-test-net WGMASQ_WG_CIDR=10.99.0.0/24 WGMASQ_WG_IF=wg0 WGMASQ_HOST_LOG=/dev/null; }

# 1. fail-closed: WGMASQ_NODE missing
( setup_mocks normal; unset WGMASQ_NODE; export WGMASQ_NETWORK=platform-test-net WGMASQ_HOST_LOG=/dev/null
  bash "$SUT" apply >/dev/null 2>&1 ) && bad "missing WGMASQ_NODE should fail" || ok "fail-closed: WGMASQ_NODE required"

# 2. fail-closed: WGMASQ_NETWORK missing
( setup_mocks normal; env_ok; unset WGMASQ_NETWORK
  bash "$SUT" apply >/dev/null 2>&1 ) && bad "missing WGMASQ_NETWORK should fail" || ok "fail-closed: WGMASQ_NETWORK required"

# 3. fail-closed: docker network unresolvable
( setup_mocks badnet; env_ok
  bash "$SUT" apply >/dev/null 2>&1 ) && bad "bad network should fail" || ok "fail-closed: unresolvable network"

# 4. apply builds owned chains with NODE_IP/32 SNAT + conntrack return
setup_mocks normal; env_ok
if bash "$SUT" apply >/dev/null 2>&1; then
  grep -q -- "-t nat -N K3D_WG_MASQ_NAT" "$CALLS" && ok "apply creates owned nat chain" || bad "no owned nat chain"
  grep -q -- "-t nat -A K3D_WG_MASQ_NAT -s 172.19.0.3/32 -d 10.99.0.0/24 -o wg0 -j MASQUERADE" "$CALLS" && ok "apply: NODE_IP/32 SNAT (not dead pod-CIDR)" || bad "SNAT source not NODE_IP/32"
  grep -q -- "-t nat -F K3D_WG_MASQ_NAT" "$CALLS" && ok "apply flushes nat chain (stale-free)" || bad "no flush"
  grep -q -- "conntrack --ctstate ESTABLISHED,RELATED" "$CALLS" && ok "apply: return rule is conntrack-stateful (no NEW inbound)" || bad "return not stateful"
  grep -q -- "-i br-b863e3369c00 -o wg0 -s 172.19.0.3/32 -d 10.99.0.0/24 -j ACCEPT" "$CALLS" && ok "apply: forward-out scoped to NODE_IP" || bad "forward-out not scoped"
else bad "apply failed under normal mocks"; fi

# 5. rollback flushes + deletes owned chains + jumps
setup_mocks normal; env_ok; : >"$CALLS"
if bash "$SUT" rollback >/dev/null 2>&1; then
  grep -q -- "-t nat -D POSTROUTING -j K3D_WG_MASQ_NAT" "$CALLS" && ok "rollback removes nat jump" || bad "no nat jump removal"
  grep -q -- "-t filter -X K3D_WG_MASQ_FWD" "$CALLS" && ok "rollback deletes fwd chain" || bad "no fwd chain delete"
else bad "rollback failed"; fi

echo "SONUC: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = 0 ]
