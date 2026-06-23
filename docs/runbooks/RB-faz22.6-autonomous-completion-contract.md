# RB-faz22.6 — Autonomous Completion Contract

> Status: ACTIVE completion contract, 2026-06-23.
> Scope: Faz 22.6 remote-ops / remote-bridge productization.
> Parent milestone: Faz 22 Endpoint Administration.
> Canonical open gates at creation time: `platform-backend#548` and
> `platform-k8s-gitops#1580`.

This contract turns the broad goal "finish Faz 22.6 autonomously, aligned with
industry standards and the current system" into verifiable gates. It does not
replace the existing remote-ops runbooks. It is the closure layer that prevents
bounded pilot evidence, source-only work, RDP convenience access, or fast
release churn from being reported as full 22.6 completion.

## 1. Target Product Shape

Faz 22.6 is not an inbound remote-desktop or unrestricted shell product. The
accepted architecture is:

```text
Operator UI
  -> endpoint-admin remote-bridge broker
    -> EndpointAgent outbound mTLS/gRPC stream
      -> endpoint
```

The product can be called Remote Response Terminal, Break-Glass Response Shell,
or VIEW_ONLY screen-share depending on the capability. It must not be described
as "free shell", "raw terminal", "RDP replacement", or "direct computer
control" without the specific capability boundary.

## 2. Industry Baseline

Faz 22.6 should meet or deliberately exceed the control posture seen in mature
endpoint response products such as Microsoft Defender Live Response,
CrowdStrike Real Time Response, SentinelOne Remote Shell, Sophos Live Response,
Tanium remote operations, Intune Remote Help, and enterprise RMM backstage
tools.

The comparable controls are:

| Standard capability | Faz 22.6 required posture |
|---|---|
| Outbound-only endpoint channel | EndpointAgent initiates mTLS/gRPC; no inbound SSH/RDP/WinRM/SMB/RPC acceptance |
| Least privilege operation model | Operation catalog and signed permits; no arbitrary command text by default |
| Strong operator identity | Role check plus step-up for sensitive operations |
| Dual control | requester and approver are distinct for break-glass operations |
| Device trust | cert-bound identity for bounded pilot; hardware-backed device-key/TPM for broad rollout or explicit risk acceptance |
| Session governance | TTL, heartbeat loss, revoke, kill, and close semantics are fail-closed |
| Recording and audit | WORM/session recording before permit or operation success is claimed |
| Privacy and exfil controls | VIEW_ONLY has visible user indicator, masking/DLP policy, recording, and attended-pilot sign-off |
| Negative evidence | no-auth, wrong device, replay, expired permit, disabled operation, audit-down, raw shell, and closed-session operations fail closed |
| Release discipline | immutable digests, signed artifacts, deterministic version lineage, no moving-tag proof |

If a competitor offers a capability without one of these controls, Faz 22.6
keeps the stricter control unless the owner explicitly records a time-bounded
risk acceptance.

## 3. Completion Gates

Faz 22.6 can only be called complete when all gates below have authoritative
evidence.

| Gate | Required state | Current source of truth |
|---|---|---|
| 22.6.1 Operation Catalog | Accepted bounded evidence; raw operation classes denied | `platform-backend#701` |
| 22.6.2 Approved Script Runner | Accepted bounded evidence; immutable script library and argument schema enforced | `platform-backend#702` |
| 22.6.3 Constrained executor | Accepted AgentPC2 full matrix evidence | `platform-agent#208` |
| Broker live state | Dedicated remote-bridge deployment ready on immutable digest; ExternalSecrets Ready/SecretSynced | `docs/state/current-state.md` plus live `kubectl`; current expected digest `sha256:6b12276cea912345dcfbcf2e5e920931de813b8aa483b6b2351c75e4b5331a9c` |
| B1.4 hardware attestation | Real device-key/TPM evidence on agent wire, broker verifier pass, root policy, positive and negative field evidence | `platform-backend#548` |
| VIEW_ONLY screen-share | Product-channel live VIEW_ONLY smoke, D10 recording/fail-closed evidence, DLP/mask policy, local abort, active indicator, KVKK/attended pilot sign-off | `platform-k8s-gitops#1580` |
| Release/version hygiene | Agent release, MSI/ProductVersion/FileVersion, artifact-host current, GitOps expected version, verifier defaults, and acceptance issue evidence agree | release artifacts plus GitOps verifier output |
| Rollout boundary | 5/50/800 readiness is either explicitly out of scope or proven under separate signed MSI/GPO rollout gates | rollout issues, not `#208` |

## 4. Explicit Non-Completion Cases

The following do not complete Faz 22.6:

- `platform-agent#208` alone. It completes bounded AgentPC2 constrained
  executor scope, not broad 22.6.
- RDP from a Mac to Denetim PC or any endpoint.
- SSH/reverse tunnel access.
- Source-only parser, producer, or verifier merges for device-key attestation.
- Enrollment-backed machine certificate trust presented as TPM or secure
  element attestation.
- UI-only session state work without server-side authorization, recording, and
  negative evidence.
- A new agent release tag without artifact-host, installed endpoint, and
  verifier agreement.
- A green workflow whose artifact does not prove the named gate.

## 5. Release And Version Standard

The rapid `v0.2.x` release train is acceptable for pilot recovery only if the
lineage remains deterministic. Before any 5-device or broader rollout claim,
the release record must include:

1. Git tag and source commit.
2. Trusted release workflow run.
3. `endpoint-agent.exe` SHA256 and signer fingerprint.
4. MSI/ProductVersion/FileVersion when MSI is involved.
5. Artifact-host immutable image digest.
6. `current` manifest release tag and binary SHA256.
7. GitOps expected target version and verifier defaults.
8. Live endpoint observed version after update or install.
9. Acceptance workflow id and evidence artifact SHA256 manifest.
10. Statement of whether the release is a pilot recovery release, bounded
    acceptance release, or rollout candidate.

No gate should compare a live endpoint against stale defaults. If a verifier
default is stale, the run is a stale-gate guard, not product no-go evidence.
The audit helper treats the current rapid `v0.2.x` line as a release-hygiene
item even when the latest tag is correct, because multiple same-day pilot
recovery releases must be reconciled before any 5-device or broader rollout
claim.

## 6. Owner Decisions Needed

Two decisions unblock the remaining completion path:

1. `platform-backend#548`: Is hardware-backed device-key/TPM attestation a hard
   requirement before broad rollout, or will the owner accept a named,
   time-bounded, compensated pilot risk on enrollment-backed trust?
2. `platform-k8s-gitops#1580`: Which approved pilot device and operator window
   will produce the VIEW_ONLY live screen-share evidence package?

If either decision is not available, the autonomous path continues by hardening
source/verifier coverage and preparing evidence scripts, but completion cannot
be claimed.

## 7. Audit Command

Use the completion audit helper before reporting status:

```bash
scripts/faz22-remote-ops/faz22-6-completion-audit.sh
```

The audit is intentionally conservative. It prints `F22_6_COMPLETION=blocked`
while `#548` or `#1580` remains open, or when live broker/release evidence is
missing.

## 8. Closure Language

Allowed language:

- bounded AgentPC2 constrained executor accepted
- source-ready
- live broker healthy
- open/blocked on hardware attestation
- open/blocked on VIEW_ONLY live acceptance
- release hygiene needs audit

Disallowed language until every completion gate passes:

- Faz 22.6 complete
- production remote support ready
- broad rollout ready
- TPM attestation complete
- unrestricted terminal ready
