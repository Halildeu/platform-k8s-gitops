# RB-faz24-wg-bplus-i6-pod-cidr-wg-masq

> Scope: `platform-k8s-gitops#1867` / Faz 24 WG-B+ I6. This runbook defines
> the evidence contract for pod-CIDR to WireGuard MASQUERADE. It does not
> enable direct-STT by itself and does not prove I3 management audit acceptance.

## 1. Acceptance Boundary

I6 acceptance proves **policy-approved probe pod → WireGuard peer TCP
reachability**: a single ephemeral, digest-pinned, correctly-scheduled probe pod
(reached only via a run-scoped egress NetworkPolicy) completes fresh TCP connects
to the WireGuard-side peer through a bounded, host-owned NAT rule whose exact
SNAT counter is observed to advance, and that mechanism is drift-detectable and
rollbackable.

It does **not** prove that all app workloads are reachable, nor:

- direct audio e2e,
- Denetim PC I3 audit acceptance,
- platform-ai mTLS certificate correctness,
- production cutover,
- or any broad LAN routing policy.

## 2. Mechanism Decision

For the current `k3d-test` / host-network shape, the accepted mechanism is
host-managed `iptables`/`nftables` NAT materialized by a systemd-owned unit or
equivalent host service. Do not assume a Kubernetes DaemonSet is sufficient:
k3d/k3s pod traffic exits through host namespaces and bridge chains that are
not reliably owned by a workload pod. The evidence contract therefore requires:

- `mechanism.type=host-systemd-iptables`,
- `mechanism.managedOutsideCluster=true`,
- `mechanism.daemonSetAssumed=false`,
- `mechanism.iptablesTable=nat`,
- `mechanism.iptablesChain=POSTROUTING`,
- a stable hash of the expected NAT rule,
- drift-detection evidence,
- and rollback evidence.

Production can later replace iptables with nftables, but only with an updated
evidence contract and verifier. Until then, nftables-only evidence is not
accepted by this gate.

## 3. Required Evidence Surfaces

The v3 schema (`faz24.wg-bplus.i6.pod-cidr-wg-masq.v3`) requires all twelve
checks with `status: pass`. v1 and v2 evidence are rejected by the verifier
(schema mismatch; v2 blocked evidence stays historical). v3 keeps v2's cluster
binding + SNAT-counter traversal and additionally makes the pod probe Calico-safe:
the probe pod is selected by LABEL (not "first Running pod"), validated against
the disclosed `clusterCIDR` + the bound node, and must run a digest-pinned image:

| Check id | Required proof |
|---|---|
| `cluster-identity-bound` | Kube context resolves to a captured kube-system UID; the `--wg-node` container exists and is attached to `--docker-network`; the context is a supported one (`k3d-test`/`k3d-prod`) and the belt policy (context↔cluster-cidr) is consistent. Fail-closed if anything is unresolved. |
| `effective-cluster-cidr-matches-config` | The node's EFFECTIVE k3s cluster-cidr (config.yaml, else `/proc/1/cmdline`) equals `--cluster-cidr`, backed by ≥1 valid observed source. If both sources disagree, FAIL. This is the cluster `/16`, not a node `/24`. |
| `node-pod-cidrs-within-cluster-cidr` | Every node `.spec.podCIDR[s]` allocation is a subnet of `--cluster-cidr` (topology sanity only — a node `/24` inside the `/16` is correct). This is NO LONGER used for probe selection. Empty/unreadable → FAIL. |
| `host-owned-chain-authority` | The host-rule `check` runs ONLY the INSTALLED root-owned script (`--installed-host-rule-script`) under sudo (env set AFTER sudo via `env`, since `sudo -n` strips the caller env), with `executionMode == sudo-installed`. Running the user-writable checkout as root is rejected (the `sudo-canonical` mode is removed — the checkout is only the sha256 comparison source). Pass requires: installed script owned by uid 0, not group/world writable, sha256 == canonical checkout, and `check` exit 0. No script stdout/stderr in the JSON. |
| `peer-route-is-wireguard-path` | `ip route get <peer>` dev equals the resolved wg interface AND a `wg show <wg> allowed-ips` peer covers the peer host. Only the peer key FINGERPRINT + handshake age are stored, never raw keys. |
| `pod-to-wg-peer-tcp-connect` | EXACTLY ONE pod matches `--probe-pod-selector`; it is Running + Ready, has no `deletionTimestamp`, is not `hostNetwork`, its `podIP` is a valid IP inside `topology.clusterCIDR` (Calico: NOT the node `/24`), it is scheduled on `clusterIdentity.nodeName`, its `imageRef` is exactly the pinned expected probe artifact, and its RUNTIME image digest equals the requested digest (a moving tag / merely-present `imageID` is not proof). That pod completes `--probe-attempts`/`--probe-attempts` fresh TCP connects to `<peer>:<port>` via `nc`. Missing `nc`, wrong/absent pod, wrong image/digest, or partial success → FAIL. No host fallback. |
| `snat-rule-counter-traversal` | The owned SNAT rule fingerprint is stable across the probe (before==after hash), its exact counter did not reset, `counterDelta >= probe-attempts`, AND the pod TCP probe fully succeeded (attempts/successCount cross-checked with the pod probe). The counter alone is NOT sufficient. |
| `reboot-persistence` | Systemd unit is enabled+active with a non-empty `ExecStart`. |
| `drift-detect` | Drift timer is active or enabled. |
| `rollback-defined` | `ExecStop` present AND a tested rollback evidence ref is supplied. |
| `no-broad-lan-nat` | No `-s 0.0.0.0/0` or `-s 10.0.0.0/8` MASQUERADE in the nat table or owned chain. |
| `daemonset-not-assumed` | Evidence explicitly records that a DaemonSet is not the authority. |

## 4. Evidence Contract

Write a metadata-only JSON file using schema
`faz24.wg-bplus.i6.pod-cidr-wg-masq.v3`:

```json
{
  "schemaVersion": "faz24.wg-bplus.i6.pod-cidr-wg-masq.v2",
  "collectedAt": "2026-07-12T03:20:00Z",
  "status": "pass",
  "protectedEvidencePath": "github-actions://Halildeu/platform-k8s-gitops/actions/runs/0",
  "redaction": {
    "secretMaterialIncluded": false,
    "rawCommandOutputIncluded": false,
    "rawPacketCaptureIncluded": false,
    "rawAudioIncluded": false,
    "rawTranscriptIncluded": false
  },
  "topology": {
    "clusterName": "k3d-test",
    "clusterCIDR": "10.44.0.0/16",
    "nodePodCIDRs": ["10.44.0.0/24"],
    "serviceCIDR": "10.45.0.0/16",
    "wgInterface": "wg0",
    "platformAiTarget": {
      "host": "10.99.0.2",
      "port": 8243
    }
  },
  "mechanism": {
    "type": "host-systemd-iptables",
    "managedOutsideCluster": true,
    "daemonSetAssumed": false,
    "host": "staging-sw",
    "systemdUnit": "k3d-wg-masq.service",
    "iptablesTable": "nat",
    "iptablesChain": "POSTROUTING",
    "ownedNatChain": "K3D_WG_MASQ_NAT",
    "expectedRuleHash": "0123456789abcdef"
  },
  "driftDetection": {
    "enabled": true,
    "mode": "systemd-timer",
    "intervalMinutes": 5,
    "expectedRuleHash": "0123456789abcdef",
    "evidenceRef": "drift/k3d-wg-masq-timer.json"
  },
  "rollback": {
    "defined": true,
    "tested": true,
    "commandHash": "fedcba9876543210",
    "evidenceRef": "rollback/dry-run.json"
  },
  "checks": [
    {
      "id": "cluster-identity-bound",
      "status": "pass",
      "observedAt": "2026-07-12T03:20:00Z",
      "summary": "Kube context, cluster uid, node and docker network are bound",
      "evidenceRef": "checks/cluster-identity-bound.json"
    }
  ]
}
```

The `topology.clusterCIDR` is the k3s cluster `/16` and `topology.nodePodCIDRs`
are the per-node `/24` allocations contained within it (containment, not
equality). `mechanism.ownedNatChain` is the host-owned chain
`K3D_WG_MASQ_NAT`.

The real bundle must include all required check ids. Evidence references are
relative metadata paths under the protected evidence path.

## 5. Redaction Rules

Allowed:

- hostnames, cluster names, CIDRs, interface names, ports, timestamps,
- the probe pod IP + node name and a digest-pinned image ref / runtime imageID
  (ephemeral network/scheduling metadata inside the disclosed clusterCIDR — not
  secret/PII),
- pass/fail status names,
- SHA-256 or 16-char SHA-256 prefixes of expected rules and commands,
- bounded HTTP status metadata,
- relative evidence references.

Not allowed:

- passwords, tokens, JWTs, cookies, Vault material, private keys,
- raw `iptables-save`, `nft list ruleset`, `ip route`, `wg show`, or shell
  output,
- raw packet captures,
- raw audio or transcript content.

Keep raw host evidence, if required for audit, only in the protected path. The
JSON contract carries hashes and bounded summaries.

## 6. Validate and Ingest

### 6.0 Probe pod (v3)

The collect workflow (`faz24-wg-bplus-i6-masq-evidence-collect.yml`) deploys the
probe pod itself: a single ephemeral pod labelled `wg-i6-probe=true` +
`wg-i6-probe-run=<run-id>`, pinned to the canonical `busybox@sha256:<digest>`
artifact (`PROBE_IMAGE` — must equal the verifier's `EXPECTED_PROBE_IMAGE`; fill
the `PLACEHOLDER_DIGEST_TO_FILL` before running), scheduled on `wg_node_k8s_name`,
hardened (non-root, `readOnlyRootFilesystem`, `drop: [ALL]`,
`automountServiceAccountToken: false`, bounded resources, `restartPolicy: Never`),
and reachable only via a run-scoped egress NetworkPolicy that permits egress
**only** to `<peer_host>/32` TCP `<peer_port>` (no DNS). The workflow waits for
Ready, then hard-gates that the pod's spec image is the pinned ref AND its runtime
image digest EQUALS the pinned digest, runs the collector with
`--probe-pod-selector "wg-i6-probe=true,wg-i6-probe-run=<run-id>"` +
`--installed-host-rule-script /usr/local/sbin/k3d-wg-masq-host-rule.sh` (the
root-owned installed script), and deletes the pod + NetworkPolicy afterward
(`if: always()`, run-scoped names only). The operator fallback path must deploy an
equivalent single labelled pod before running the collector.

Validate locally before attaching or ingesting:

```bash
python3 scripts/faz24/verify-wg-bplus-i6-masq-evidence.py \
  docs/faz-24-evidence/<date>-wg-bplus-i6-masq.json
```

Expected output:

```text
Faz24 WG-B+ I6 MASQ evidence: PASS
- clusterName=k3d-test
- clusterCIDR=10.44.0.0/16
- wgInterface=wg0
- mechanismType=host-systemd-iptables
```

Ingest the metadata JSON through GitHub Actions:

```bash
I6_EVIDENCE_B64="$(base64 < docs/faz-24-evidence/<date>-wg-bplus-i6-masq.json | tr -d '\n')"

gh workflow run faz24-wg-bplus-i6-masq-evidence-ingest.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f evidence_json_base64="$I6_EVIDENCE_B64"
```

The uploaded artifact is `faz24-wg-bplus-i6-masq-evidence-<run_id>`.
Boundary: a passing ingest proves only the I6 MASQ metadata contract. It does
not make direct-STT, I3, app-mTLS, or production accepted.

### 6.1 Operator-collected Host Evidence Fallback

Use this path only when the self-hosted `staging-sw` runner can reach the
cluster/WG path but cannot query host namespace NAT/systemd metadata. The
operator runs the same collector from a protected host context and keeps raw
host command output out of the JSON artifact.

If I3 #1864 and I6 #1867 are being coordinated in one operator window, generate
the handoff package first:

```bash
gh workflow run faz24-wg-bplus-operator-handoff.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main
```

The uploaded artifact is `faz24-wg-bplus-operator-handoff-<run_id>`. It keeps
the current I6 package run id, I6 ingest command, and I3 Denetim authorization
commands together with explicit `Needs Verify` boundaries. The handoff package
does not connect to `staging-sw`, collect host evidence, or make #1867
acceptable.

Build the operator package first:

```bash
gh workflow run faz24-wg-bplus-i6-host-evidence-package.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f target_host=staging-sw \
  -f cluster_cidr=10.44.0.0/16 \
  -f wg_interface=auto \
  -f peer_host=10.99.0.2 \
  -f peer_port=8243 \
  -f wg_node=k3d-test-server-0 \
  -f docker_network=platform-test-net \
  -f probe_attempts=3 \
  -f kube_context=k3d-test \
  -f namespace=platform-test \
  -f systemd_unit=k3d-wg-masq.service \
  -f drift_timer=k3d-wg-masq.timer \
  -f rollback_tested_ref=rollback/k3d-wg-masq-dry-run.json
```

> NOTE: `cluster_cidr` must match the target context (test=`10.44.0.0/16`,
> prod=`10.42.0.0/16`). The collector's belt policy rejects `k3d-test`+`10.42`
> and `k3d-prod`+`10.44` before any node query. `peer_port` is the WireGuard
> peer's TCP port used by the pod-origin connect probe.

The uploaded artifact is `faz24-i6-host-evidence-package-<run_id>`. It
contains only:

- `collect-staging-i6-host-evidence.sh`
- `expected-i6-host-evidence-metadata.json`
- `README.md`
- `SHA256SUMS`

Boundary: the package workflow does not connect to `staging-sw`, does not
collect host command output, and does not change host iptables/nftables,
WireGuard, Kubernetes objects, platform-ai, secrets, or production state.

On `staging-sw`, from a clean checkout of `platform-k8s-gitops`:

```bash
bash /path/to/collect-staging-i6-host-evidence.sh
```

If the local verifier returns `PASS`, ingest the exact JSON:

```bash
I6_EVIDENCE_B64="$(base64 < "${OUT}" | tr -d '\n')"

gh workflow run faz24-wg-bplus-i6-masq-evidence-ingest.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f evidence_json_base64="${I6_EVIDENCE_B64}"
```

Boundary:

- the collector is metadata-only and does not change host iptables/nftables,
  WireGuard, Kubernetes objects, platform-ai, or production state,
- `--protected-evidence-path` must identify the protected operator evidence
  location; it must not contain secrets or raw command output,
- a local PASS is not final until the GitHub ingest workflow also returns PASS
  and #1867 receives an evidence comment.

## 7. Drift Detection

The drift detector must compute the same expected rule hash used by the
evidence bundle and compare it with the live host namespace. A PASS requires:

- detector enabled,
- accepted mode `systemd-timer`, `systemd-service`, `cron`, or
  `manual-plus-alert`,
- bounded interval `1..1440` minutes,
- `expectedRuleHash` matching the mechanism hash,
- metadata-only evidence reference.

If drift is found, record `BLOCKED` on #1867 and do not advance to
`Needs Verify`.

## 8. Rollback

Rollback must remove only the I6-owned NAT material and must leave unrelated
cluster, host, WireGuard, Vault, and platform-ai state untouched. A PASS
requires:

- rollback path defined,
- rollback path tested,
- command hash recorded,
- metadata-only evidence reference.

Do not use a broad flush such as `iptables -t nat -F` as rollback evidence.

## 9. Follow-up Status

After verifier PASS:

1. Reference the protected evidence path in `platform-k8s-gitops#1867`.
2. Add an `EVIDENCE` comment with verifier output and no-leak boundary.
3. Move the issue to `Needs Verify` only after the contract passes and no I6
   drift remains.
4. Do not close #1867 until acceptance review confirms the evidence.
