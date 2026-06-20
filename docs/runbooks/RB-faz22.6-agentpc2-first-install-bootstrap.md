# RB: Faz 22.6 AgentPC2 First-Install Bootstrap

Status: active bounded-pilot runbook

Scope:
- Issue: platform-k8s-gitops#1768
- Downstream acceptance: platform-agent#208
- Target: AgentPC2 / AD object GUID
  `fa2d1ad6-a0a8-4101-ab77-9f2a0b25742a` / product device
  `2f7ad30f-970a-42e7-8af8-08764ae6066f`
- Release: platform-agent `v0.2.13`

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

- immutable release metadata verification for `v0.2.13`
- live broker permit public-key derivation from the staging signer secret
- outbound-only remote bridge configuration generation for
  `remote-bridge-mtls.testai.acik.com:443`
- endpoint-local PowerShell bootstrap generation
- redacted evidence artifact upload
- boundary comments on platform-k8s-gitops#1768 and platform-agent#208

The workflow must not mark #208 as accepted.

## Latest No-Go Handoff

The 2026-06-20 constrained-executor acceptance rerun proved that the staging
prerequisites are present, but AgentPC2 still needs the endpoint-local
bootstrap.

Evidence:

- acceptance rerun:
  `https://github.com/Halildeu/platform-k8s-gitops/actions/runs/27868590359`
  (supersedes earlier same-day rerun `27867580698`)
- no-go reason: `pilot-readiness-agent-version-mismatch`
- AgentPC2 observed state: `agent_version=v0.2.12`, `status=ONLINE`,
  `capabilities=[]`, `last_seen_at=2026-06-20 10:37:49.030519+00`
- endpoint-admin remote-bridge digest prerequisite:
  `sha256:7e1925ceb0312042c8712fcb423eafc5bae1a3f1e0f22c93a7d0ce3b16dccf84`
- artifact-host `v0.2.13` digest prerequisite:
  `sha256:6d19a740c5ba4b1a555d3398f5b80387b98b769c1ada2814954d3d914c975454`
- generated bootstrap artifact source:
  `https://github.com/Halildeu/platform-k8s-gitops/actions/runs/27867360595`

This no-go is the expected safety behavior. It must not be reclassified as a
failed product gate, and it must not be bypassed by inbound SSH/RDP/WinRM/SMB
or manual remote-shell evidence.

## Endpoint-Local Action

After the workflow artifact is available, execute the generated
`agentpc2-first-install-bootstrap.ps1` on AgentPC2 from an elevated PowerShell
session.

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
