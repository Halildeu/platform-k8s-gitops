#!/usr/bin/env bash
# Offline test for k3d-wg-masq-host-rule.sh. Mocks iptables/docker/ip/flock via PATH
# shims; the iptables mock LOGS every invocation (and returns 1 for -C so apply always
# reconciles). Asserts fail-closed guards + the exact NAT/FORWARD command set apply and
# rollback emit into the owned chains. (Stateful idempotence/dedup is enforced live by
# the systemd `check` action on the running host; a fuller stateful harness is #1867.)
# No root, no cluster. Run: bash tests/test-host-rule.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SUT="$HERE/../k3d-wg-masq-host-rule.sh"
PASS=0; FAIL=0
ok(){ echo "PASS: $1"; PASS=$((PASS+1)); }
bad(){ echo "FAIL: $1"; FAIL=$((FAIL+1)); }

setup(){ # $1 = net override (optional)
  MOCK="$(mktemp -d)"; CALLS="$MOCK/calls"; : >"$CALLS"
  local net="${1:-platform-test-net}"
  cat >"$MOCK/iptables" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >>"$CALLS"
# -C: report the legacy 10.42 rule as PRESENT (so del_all emits its -D once) and
# everything else ABSENT (so apply reconciles owned rules). Guard \$1 avoids an
# infinite del_all loop by only reporting present on the first probe per run.
case " \$* " in
  *" -C "*)
    if [[ "\$*" == *"10.42.0.0/16"* ]] && [ ! -f "$MOCK/legacy_gone" ]; then touch "$MOCK/legacy_gone"; exit 0; fi
    exit 1;;
esac
exit 0
EOF
  cat >"$MOCK/docker" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = network ]; then
  [ "$3" = no-such-net ] && exit 1
  case "$*" in *Driver*) echo bridge;; *bridge.name*) echo "";; *.Id*) echo b863e3369c00deadbeef;; esac
  exit 0
fi
[ "$1" = inspect ] && { echo 172.19.0.3; exit 0; }; exit 0
EOF
  printf '#!/usr/bin/env bash\nexit 0\n' >"$MOCK/ip"
  # flock shim: skip flag options (-n/-x/-s) + the fd/lockfile; if a command follows,
  # exec it, else no-op success. Handles `flock 9`, `flock -n 8`, `flock <lock> <cmd>`.
  cat >"$MOCK/flock" <<'EOF'
#!/usr/bin/env bash
a=("$@"); i=0
while [ $i -lt ${#a[@]} ]; do case "${a[i]}" in -*) i=$((i+1));; *) break;; esac; done
cmd=("${a[@]:$((i+1))}")
[ ${#cmd[@]} -gt 0 ] && exec "${cmd[@]}"
exit 0
EOF
  chmod +x "$MOCK"/iptables "$MOCK"/docker "$MOCK"/ip "$MOCK"/flock
  export PATH="$MOCK:$PATH"
  export WGMASQ_NODE=k3d-test-server-0 WGMASQ_NETWORK="$net" WGMASQ_WG_CIDR=10.99.0.0/24 WGMASQ_WG_IF=wg0 WGMASQ_HOST_LOG=/dev/null WGMASQ_LOCK="$MOCK/lock" WGMASQ_DRILL_LOCK="$MOCK/drill-lock"
}
has(){ grep -qF -- "$1" "$CALLS"; }

# 1-3 fail-closed
setup; ( unset WGMASQ_NODE;    bash "$SUT" apply >/dev/null 2>&1 ) && bad "missing NODE" || ok "fail-closed: WGMASQ_NODE required"
setup; ( unset WGMASQ_NETWORK; bash "$SUT" apply >/dev/null 2>&1 ) && bad "missing NET" || ok "fail-closed: WGMASQ_NETWORK required"
setup no-such-net; ( bash "$SUT" apply >/dev/null 2>&1 ) && bad "bad net" || ok "fail-closed: unresolvable network"

# 4 apply emits the owned-chain command set (dedicated chains, NODE_IP/32 SNAT, conntrack)
setup; bash "$SUT" apply >/dev/null 2>&1
has "-t nat -N K3D_WG_MASQ_NAT"   && ok "apply: creates owned nat chain"    || bad "no owned nat chain"
has "-t filter -N K3D_WG_MASQ_FWD" && ok "apply: creates owned filter chain" || bad "no owned filter chain"
has "-t nat -F K3D_WG_MASQ_NAT"   && ok "apply: flushes nat chain (stale-free)" || bad "no nat flush"
has "-t nat -A K3D_WG_MASQ_NAT -s 172.19.0.3/32 -d 10.99.0.0/24 -o wg0 -j MASQUERADE" && ok "apply: SNAT source = derived NODE_IP/32" || bad "SNAT not NODE_IP/32"
has "-t filter -A K3D_WG_MASQ_FWD -i br-b863e3369c00 -o wg0 -s 172.19.0.3/32 -d 10.99.0.0/24 -j ACCEPT" && ok "apply: forward-out scoped to NODE_IP" || bad "forward-out not scoped"
has "conntrack --ctstate ESTABLISHED,RELATED" && ok "apply: return rule conntrack-stateful (no NEW inbound)" || bad "return not stateful"
has "-t nat -D POSTROUTING -s 10.42.0.0/16 -d 10.99.0.0/24 -o wg0 -j MASQUERADE" && ok "apply: removes known legacy 10.42 inline rule" || bad "legacy not removed"
has "-I POSTROUTING 1 -j K3D_WG_MASQ_NAT" && ok "apply: inserts nat jump at position 1" || bad "jump not at pos 1"

# 5 rollback deletes owned chains (jump -D is emitted via del_all; chain -X is unconditional)
setup; bash "$SUT" rollback >/dev/null 2>&1
has "-t nat -X K3D_WG_MASQ_NAT"    && ok "rollback: deletes owned nat chain"    || bad "no nat chain delete"
has "-t filter -X K3D_WG_MASQ_FWD" && ok "rollback: deletes owned filter chain" || bad "no filter chain delete"
has "-t nat -D POSTROUTING -s 10.42.0.0/16 -d 10.99.0.0/24 -o wg0 -j MASQUERADE" && ok "rollback: also clears legacy 10.42" || bad "rollback skips legacy"

# 6 drill: apply+rollback on THROWAWAY scratch chains, ZERO base-chain mutation
setup; bash "$SUT" drill >/dev/null 2>&1
has "-t nat -N K3D_WG_MASQ_NAT_DRILL"    && ok "drill: creates scratch nat chain"    || bad "no scratch nat chain"
has "-t filter -N K3D_WG_MASQ_FWD_DRILL" && ok "drill: creates scratch filter chain" || bad "no scratch filter chain"
has "-t nat -A K3D_WG_MASQ_NAT_DRILL -s 172.19.0.3/32 -d 10.99.0.0/24 -o wg0 -j MASQUERADE" && ok "drill: populates scratch SNAT (same shape as live)" || bad "scratch SNAT missing"
has "-t filter -A K3D_WG_MASQ_FWD_DRILL -i br-b863e3369c00 -o wg0 -s 172.19.0.3/32 -d 10.99.0.0/24 -j ACCEPT" && ok "drill: populates scratch forward-out" || bad "scratch forward-out missing"
has "-t filter -A K3D_WG_MASQ_FWD_DRILL -i wg0 -o br-b863e3369c00 -s 10.99.0.0/24 -d 172.19.0.3/32 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT" && ok "drill: populates scratch conntrack return" || bad "scratch return missing"
has "-t nat -F K3D_WG_MASQ_NAT_DRILL"    && ok "drill: flushes scratch nat chain"    || bad "no scratch nat flush"
has "-t nat -X K3D_WG_MASQ_NAT_DRILL"    && ok "drill: deletes scratch nat chain"    || bad "no scratch nat delete"
has "-t filter -F K3D_WG_MASQ_FWD_DRILL" && ok "drill: flushes scratch filter chain" || bad "no scratch filter flush"
has "-t filter -X K3D_WG_MASQ_FWD_DRILL" && ok "drill: deletes scratch filter chain" || bad "no scratch filter delete"
# ZERO live-path impact: the drill must NEVER reference the base POSTROUTING/FORWARD chains.
grep -Eq -- '(POSTROUTING|FORWARD)' "$CALLS" && bad "drill mutates/reads a base chain (live-path impact)" || ok "drill: never touches POSTROUTING/FORWARD (zero live-path impact)"
# DRILL line carries the versioned mechanism id + honest scope label (capture first;
# the mock has no real chain state so drill exits non-zero, which pipefail would surface)
DRILL_OUT="$(bash "$SUT" drill 2>/dev/null || true)"
printf '%s' "$DRILL_OUT" | grep -Eq 'DRILL .*rollbackMechanismVersion=k3d-wg-masq\.rollback\.v2 scope=detached-scratch-chain' && ok "drill: DRILL line carries rollbackMechanismVersion + scope=detached-scratch-chain" || bad "DRILL line missing version/scope"
# concurrency guard + signal-safe cleanup are present in the script source
grep -Eq 'flock -n 8' "$SUT" && ok "drill: dedicated non-blocking flock guard present" || bad "no non-blocking flock guard"
grep -Eq "trap 'drill_cleanup' EXIT INT TERM" "$SUT" && ok "drill: signal-safe cleanup trap present" || bad "no cleanup trap"

echo "SONUC: PASS=$PASS FAIL=$FAIL"
rm -rf "$MOCK"
[ "$FAIL" = 0 ]
