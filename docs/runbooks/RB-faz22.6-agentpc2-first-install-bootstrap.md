# RB: Faz 22.6 AgentPC2 First-Install Bootstrap

Status: active bounded-pilot runbook

Scope:
- Issue: platform-k8s-gitops#1768
- Downstream acceptance: platform-agent#208
- Target: AgentPC2 / AD object GUID
  `fa2d1ad6-a0a8-4101-ab77-9f2a0b25742a` / product device
  `2f7ad30f-970a-42e7-8af8-08764ae6066f`
- Release: platform-agent `v0.2.14`

## Purpose

AgentPC2 can be online with an older agent that does not advertise `UPDATE_AGENT`.
In that state the product update operation correctly fails with HTTP 422, so
platform-agent#208 cannot be accepted through the normal product update path.

This runbook prepares a bounded first-install package that upgrades AgentPC2 to
the operation-capable release without opening broad inbound management paths.

## Non-Goals

This runbook does not prove:

- platform-agent#208 constrained executor acceptance
- broad MSI/GPO rollout
- production/domain-wide remote support readiness
- inbound SSH, RDP, WinRM, SMB, or RPC acceptance
- TPM or hardware-backed device-key attestation

## Workflow

Run the GitHub Actions workflow:

```text
Faz 22.6.3 AgentPC2 first-install bootstrap
```

Required confirmation input:

```text
PREPARE_AGENTPC2_FIRST_INSTALL_BOOTSTRAP
```

The workflow runs on the staging self-hosted runner and performs:

- immutable release metadata verification for `v0.2.14`
- live broker permit public-key derivation from the staging signer secret
- outbound-only remote bridge configuration generation for
  `remote-bridge-mtls.testai.acik.com:443`
- endpoint-local PowerShell bootstrap generation
- redacted evidence artifact upload
- boundary comments on platform-k8s-gitops#1768 and platform-agent#208

The workflow must not mark #208 as accepted.

## Latest No-Go Handoff

The 2026-06-20 v0.2.14 product-update rerun proved that the release and
artifact-host prerequisites are present, but AgentPC2 still needs the
endpoint-local bootstrap because its current heartbeat does not advertise
`UPDATE_AGENT`.

Evidence:

- product update workflow:
  `https://github.com/Halildeu/platform-k8s-gitops/actions/runs/27880118884`
- no-go reason: `update-agent-dispatch-failed`
- backend response: HTTP `422`,
  `Agent does not advertise the 'UPDATE_AGENT' capability on the most recent
  heartbeat. Upgrade/configure the agent and retry.`
- AgentPC2 observed state: `agent_version=v0.2.13`, `status=ONLINE`,
  `last_seen_at=2026-06-20 18:48:39.637374+00`
- endpoint-admin remote-bridge digest prerequisite remains:
  `sha256:7e1925ceb0312042c8712fcb423eafc5bae1a3f1e0f22c93a7d0ce3b16dccf84`
- artifact-host `v0.2.14` live digest prerequisite:
  `sha256:54ad8a712df02e4ed445e7dd3d3b3e4261764265d04259121bbb4df7056aa7b0`;
  both live pods reported matching imageID and restart count `0`
- public agent artifact SHA256:
  `624d7f4efd520de1382c7d82027a25cf2dd860bc5574eb31815eafa3c99d6618`
- generated bootstrap artifact source:
  `https://github.com/Halildeu/platform-k8s-gitops/actions/runs/27880208124`
- generated bootstrap status: `bootstrap-ready`; `install.ps1` SHA256
  `5819207b63795ca0f14c1949f2a187dd996372f066992d692672e8f0d71c79df`;
  broker `remote-bridge-mtls.testai.acik.com:443`; permit public-key SHA256
  `0a92abcd8f84619fb8f14f530beb94cbdc4e0981c9eb14a4756bdc85175a1110`

This no-go is the expected safety behavior. It must not be reclassified as a
failed product gate, and it must not be bypassed by inbound SSH/RDP/WinRM/SMB
or manual remote-shell evidence.

## Access Boundary Audit

2026-06-20 live audit:

- Staging reverse SSH listeners exist for ERP-MOBIL (`127.0.0.1:22022`) and
  Denetim PC (`127.0.0.1:22024`), but AgentPC2 has no active reverse listener
  (`127.0.0.1:22026` refused).
- Denetim PC and ERP-MOBIL both timed out when testing AgentPC2 ports
  `22/135/445/5985/3389/443/80`.
- The ERP-MOBIL tunnel authenticates as `ACIK\ca.setup` and shows local
  Administrators + Domain Admins group membership, but the OpenSSH public-key
  session holds only an S4U ticket scoped to `erp-mobil$`. ADWS, SYSVOL, and
  GPO operations fail from that token, so the ERP tunnel is not an effective
  domain-authenticated GPO mutation channel.

Consequence: the remaining bootstrap must be executed through an approved
endpoint-local/operator path, a real domain-authenticated GPO/management
channel, or a future product update capability. Current tunnels cannot be used
as #208 acceptance evidence.

## Endpoint-Local Action

After the workflow artifact is available, execute the generated
`agentpc2-first-install-bootstrap.ps1` on AgentPC2 from an elevated PowerShell
session. If the workflow artifact is not directly reachable from the endpoint,
use the same pinned release values from the latest issue comment and execute the
operator-local bootstrap block there; do not use a generic raw-shell, DB insert,
or caller-supplied binary/hash lane.

The endpoint script writes evidence under:

```text
C:\ProgramData\EndpointAgent\rollout-evidence
```

The endpoint-local script contains no HMAC enrollment token, bearer token,
password, private key, or administrator credential. It contains only the broker
permit public key, which is public verifier material.

After the script finishes, collect the evidence folder and rerun the normal
#208 acceptance workflow. Do not move #1768 or #208 forward on the board until
that rerun produces live product-channel `HELLO`, permit, constrained
operation, negative, and audit evidence.

## Evidence Ingest

After the endpoint-local script writes
`C:\ProgramData\EndpointAgent\rollout-evidence`, copy that evidence folder to
one of the approved staging-runner evidence roots, for example:

```text
/home/halil/agentpc2-bootstrap-evidence/<run-or-hostname>
```

Then run the GitHub Actions workflow:

```text
Faz 22.6.3 AgentPC2 first-install evidence ingest
```

Required confirmation input:

```text
INGEST_AGENTPC2_FIRST_INSTALL_EVIDENCE
```

The ingest workflow verifies the endpoint-local summary schema, immutable
`v0.2.14` hashes, signer thumbprint, `LocalSystem` service state, outbound
`remote-bridge-mtls.testai.acik.com:443` configuration, redacted service
environment, and private-key client-auth certificate with the expected
`adcomputer:` SAN. A passing ingest may dispatch the normal #208 acceptance
workflow automatically, but it still does not prove #208 by itself.

## Acceptance Hand-Off

Only after AgentPC2 reports an operation-capable agent version may the normal
platform-agent#208 constrained-executor acceptance workflow run.

The #208 acceptance gate still requires:

- outbound 443 mTLS HELLO evidence
- permit verification evidence
- constrained operation evidence
- negative operation evidence
- audit ledger evidence

If those pass, #208 may receive an acceptance comment and the board may advance.
The first-install bootstrap evidence alone is not sufficient.
