# RB-faz24-wg-bplus-i6-pod-cidr-wg-masq

> Scope: `platform-k8s-gitops#1867` / Faz 24 WG-B+ I6. This runbook defines
> the evidence contract for pod-CIDR to WireGuard MASQUERADE. It does not
> enable direct-STT by itself and does not prove I3 management audit acceptance.

## 1. Acceptance Boundary

I6 acceptance proves that pods in the selected cluster can reach the
WireGuard-side platform-ai target through a bounded, host-owned NAT rule, and
that the mechanism is drift-detectable and rollbackable.

It does not prove:

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

The metadata JSON must include all eight checks with `status: pass`:

| Check id | Required proof |
|---|---|
| `host-namespace-nat-rule-present` | Host namespace contains the expected NAT owner/rule metadata. |
| `pod-cidr-to-wg-masq-rule` | Rule source CIDR equals the selected pod CIDR and egress target is the WireGuard interface. |
| `pod-to-platform-ai-http` | A pod-origin HTTP probe to the platform-ai target returns the expected status class. |
| `reboot-persistence` | Host reboot or service restart persistence was proven or replayed with preserved rule hash. |
| `drift-detect` | Drift detector or timer compares live rule hash to expected rule hash. |
| `rollback-defined` | Rollback command/path is defined and tested without relying on raw command output. |
| `daemonset-not-assumed` | Evidence explicitly records that a DaemonSet is not the authority. |
| `no-broad-lan-nat` | NAT is scoped to the pod CIDR and WireGuard egress, not `0.0.0.0/0` or broad LAN. |

## 4. Evidence Contract

Write a metadata-only JSON file using schema
`faz24.wg-bplus.i6.pod-cidr-wg-masq.v1`:

```json
{
  "schemaVersion": "faz24.wg-bplus.i6.pod-cidr-wg-masq.v1",
  "collectedAt": "2026-06-25T03:20:00Z",
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
    "podCIDR": "10.44.0.0/16",
    "serviceCIDR": "10.45.0.0/16",
    "wgInterface": "wg0",
    "platformAiTarget": {
      "host": "10.99.0.2",
      "port": 8200
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
      "id": "host-namespace-nat-rule-present",
      "status": "pass",
      "observedAt": "2026-06-25T03:20:00Z",
      "summary": "Expected host NAT rule hash is present",
      "evidenceRef": "checks/host-namespace-nat-rule-present.json"
    }
  ]
}
```

The real bundle must include all required check ids. Evidence references are
relative metadata paths under the protected evidence path.

## 5. Redaction Rules

Allowed:

- hostnames, cluster names, CIDRs, interface names, ports, timestamps,
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

Validate locally before attaching or ingesting:

```bash
python3 scripts/faz24/verify-wg-bplus-i6-masq-evidence.py \
  docs/faz-24-evidence/<date>-wg-bplus-i6-masq.json
```

Expected output:

```text
Faz24 WG-B+ I6 MASQ evidence: PASS
- clusterName=k3d-test
- podCIDR=10.44.0.0/16
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
  -f pod_cidr=10.42.0.0/16 \
  -f wg_interface=auto \
  -f platform_ai_host=10.99.0.2 \
  -f platform_ai_port=8200 \
  -f kube_context=k3d-test \
  -f namespace=platform-test \
  -f systemd_unit=k3d-wg-masq.service \
  -f drift_timer=k3d-wg-masq.timer \
  -f rollback_tested_ref=rollback/k3d-wg-masq-dry-run.json
```

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
