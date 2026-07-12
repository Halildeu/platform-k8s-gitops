# k3d pod → WireGuard-overlay MASQ + FORWARD host wrapper (#186 / #1867)

Host bootstrap desired-state for the k3d-test pod → WireGuard(denetim `10.99.0.2`)
network path. Consumed by ATS `ats-interview-evidence` (live-STT, 39d-5) and Faz24
`audio-gateway` (direct-STT). Not a Kubernetes manifest — these are host systemd
assets that were previously live-only; this directory is their source-of-truth.

## Why (2026-07-12 — I6 acceptance was a false-positive)

The pod→WG path **never actually worked end-to-end**. Two independent defects:

1. **Wrong masq CIDR.** The wrapper defaulted to prod's `10.42.0.0/16`, but the
   test cluster CIDR is `10.44.0.0/16` (`bootstrap/k3d-test.yaml`). The SNAT rule
   matched **0 packets**.
2. **No FORWARD ACCEPT.** The host FORWARD chain is `-P DROP` (+`ufw-reject-forward`).
   The wrapper set SNAT but never a FORWARD ACCEPT for `bridge ↔ wg0`, so forwarded
   pod/node traffic to the overlay was dropped before egress.

The old I6 collector checked only "a rule with the claimed CIDR is present" — not
"claimed CIDR == observed cluster CIDR" nor "a pod probe actually traversed the rule
(counter delta)". Hence the false-positive. See #1867.

## Contents

| File | Installs to | Role |
|---|---|---|
| `k3d-wg-masq.sh` | `/usr/local/sbin/` | node-container SNAT reconcile loop (`ExecStart`) |
| `k3d-wg-masq-host-rule.sh` | `/usr/local/sbin/` | host SNAT + FORWARD apply/check/rollback |
| `environment/k3d-test.conf` | `/etc/default/k3d-wg-masq` | desired-state config (CIDR, node, network) |
| `systemd/k3d-wg-masq.service` | `/etc/systemd/system/` | main service (loop + host-rule ExecStartPost/Stop) |
| `systemd/k3d-wg-masq-drift.service` | `/etc/systemd/system/` | oneshot drift reconcile |
| `systemd/k3d-wg-masq.timer` | `/etc/systemd/system/` | 5-min drift re-apply |

## Two-stage SNAT + FORWARD (test)

```
ATS/audio-gateway pod (10.44.x)
  │  node-container POSTROUTING MASQUERADE  (k3d-wg-masq.sh, inside node)
  ▼  src -> node docker IP (172.19.x)
k3d node → host docker bridge
  │  host FORWARD ACCEPT bridge↔wg0         (k3d-wg-masq-host-rule.sh)
  │  host POSTROUTING MASQUERADE -o wg0     (k3d-wg-masq-host-rule.sh)
  ▼  src -> 10.99.0.1
staging-sw wg0 → denetim 10.99.0.2:8243
```

The host stage is **owned explicitly**: `k3d-wg-masq-host-rule.sh` derives the node's
docker IP (`172.19.x`) from the network name and installs a `-s <node-ip>/32 -o wg0`
MASQUERADE + scoped bridge↔wg0 FORWARD into service-owned chains (`K3D_WG_MASQ_NAT`
/ `K3D_WG_MASQ_FWD`). The SNAT source is the real node IP (not the dead `10.44` the
old I6 wrapper matched → 0 hits), so its counter actually increments. The return rule
is `conntrack --ctstate ESTABLISHED,RELATED` only — denetim cannot open NEW inbound
connections to bridge containers (PG/Vault/KC). Each apply flushes+rebuilds the owned
chains, so stale old-bridge / wrong-CIDR rules cannot accumulate on network recreation.

## Bridge-recreation guard

The k3d docker bridge is `br-<network-id[:12]>` and **changes if the docker network
is recreated**. `k3d-wg-masq-host-rule.sh` therefore **derives** the bridge from the
stable docker network **name** (`WGMASQ_NETWORK=platform-test-net`) on every run, and
`require_iface` fails closed if the derived bridge is absent. Do **not** hard-pin
`WGMASQ_BRIDGE`.

## Install / reconcile

```bash
sudo install -m 0755 k3d-wg-masq.sh k3d-wg-masq-host-rule.sh /usr/local/sbin/
sudo install -m 0644 environment/k3d-test.conf /etc/default/k3d-wg-masq
sudo install -m 0644 systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now k3d-wg-masq.service k3d-wg-masq.timer
```

## Acceptance (not "rule present" — "pod probe traversed")

```bash
# 1. observed cluster CIDR == configured CIDR
docker exec k3d-test-server-0 cat /etc/rancher/k3s/config.yaml | grep cluster-cidr   # 10.44.0.0/16
# 2. exactly one SNAT + two FORWARD rules, no stale 10.42
sudo /usr/local/sbin/k3d-wg-masq-host-rule.sh check
# 3. pod-origin reachability + counter delta (reliable probe — /dev/tcp in distroless
#    pods is unreliable; NetworkPolicy is enforced, so the probe pod needs an egress allow)
kubectl -n platform-test debug <ats-pod> --image=busybox:1.36 --profile=restricted \
  -- nc -w6 -z 10.99.0.2 8243   # REACHABLE
```

## Rollback

`flock` prevents concurrent mutation but does NOT make the explicit rollback the
*last* writer. Quiesce every apply producer (timer, in-flight drift, main loop)
FIRST, then rollback — otherwise a pending/next drift `apply` can re-install the
rules right after rollback.

```bash
# 1. stop all apply producers (order matters — rollback must be the last writer)
sudo systemctl disable --now k3d-wg-masq.timer
sudo systemctl stop k3d-wg-masq-drift.service 2>/dev/null || true   # inactive is fine
sudo systemctl disable --now k3d-wg-masq.service                    # its ExecStop also rolls back
# 2. explicit rollback last, with the same env (WGMASQ_NODE + WGMASQ_NETWORK):
sudo bash -c 'set -a; . /etc/default/k3d-wg-masq; /usr/local/sbin/k3d-wg-masq-host-rule.sh rollback'
```

## Scope limits + follow-up (tracked, #1867)

This PR bounds its claims honestly:

- **Host stage** is a dedicated-chain, cardinality-checked, flock-serialized, exact
  owned model. **Node stage** (`k3d-wg-masq.sh`) still `-A`-appends its SNAT directly
  to the node `POSTROUTING` chain and only cleans the *known* legacy `10.42` signature
  (guarded to the non-prod leg) — it is **not** a generic future-CIDR reconciler, and
  host `rollback` does **not** remove the desired `10.44` node-namespace rule. Full
  node owned-chain + node rollback is a separate #1867 acceptance item.
- The offline `tests/test-host-rule.sh` covers fail-closed guards, the emitted owned
  command set, and a minimal **stateful** normalize/check/rollback pass; a fuller
  general iptables-emulator harness is a #1867 follow-up.
- The Faz24 I6 collector/verifier (`scripts/faz24/collect-wg-bplus-i6-masq-evidence.py`,
  workflow, tests) still default to `10.42` and check rule-presence only. They must be
  hardened to assert `observed cluster CIDR == configured CIDR` **and** a counter-delta
  pod probe, and to reject `k3d-test + 10.42` / `k3d-prod + 10.44`. Separate PR.
