# Faz 22.5 Domain Ops Broker Plan

> Status: design gate plus first backend product slice accepted.
> Tracked by Project #2 issues
> [#1609](https://github.com/Halildeu/platform-k8s-gitops/issues/1609),
> [#1643](https://github.com/Halildeu/platform-k8s-gitops/issues/1643),
> and backend issue
> [platform-backend#676](https://github.com/Halildeu/platform-backend/issues/676).
> This plan does not grant permission to mutate AD/GPO outside the bounded
> scope below.

## 1. Problem

Faz 22.5 domain deployment now has working AD CS, machine certificate
AutoEnroll, signed artifact generation, and selected-device evidence. The
remaining operational gap is not basic agent execution; it is durable,
auditable, domain-authenticated mutation of AD/GPO state without relying on
ad-hoc SSH sessions, RDP clipboard steps, or Domain Admin interactive shells.

Temporary reverse SSH can support lab diagnostics, but it is not a product or
enterprise operating model. Public-key SSH into a domain member also does not
provide reusable Kerberos/DC network credentials for GroupPolicy/SYSVOL
mutation. The product needs a narrow broker that can do only approved domain
deployment operations.

## 2. Decision

Create a **Domain Ops Broker** as a delegated Windows service or scheduled
runner on a domain-authenticated host. It will receive approved requests from
the platform, validate scope, perform the specific AD/GPO operation, and return
audited results.

The broker is not a general remote shell and not a Domain Admin backdoor.

The first accepted backend slice (#676) implements the product request/audit
spine before a live domain connector is enabled: Admin API, durable request
state, credential-ref-only custody, typed connector dispatch, deterministic
`connector-unavailable` fail-closed result, and audit/result persistence. That
slice proves safe custody/durability/redaction. It does **not** prove real
AD/GPO mutation success.

## 3. Scope

Allowed object scope:

- `OU=EndpointTest,DC=acik,DC=local`
- `CN=EndpointAgentPilotComputers,...`
- Endpoint Agent GPO objects used for pilot installation, certificate
  AutoEnroll, and endpoint-agent policy.

Allowed operation classes:

- Read pilot OU/computer/group/GPO state.
- Add/remove pilot computer membership in `EndpointAgentPilotComputers`.
- Link/unlink Endpoint Agent pilot GPOs to the pilot OU.
- Set bounded GPO security filtering for Endpoint Agent pilot GPOs.
- Trigger or record operator-visible preflight output.
- Roll back the specific pilot GPO link/filtering changes performed by this
  broker.

Explicitly out of scope:

- Arbitrary PowerShell or shell execution.
- Domain Admin password collection or storage.
- Domain-wide OU moves.
- Non-Endpoint GPO changes.
- User password reset/unlock/group changes.
- SMB file exfiltration or forensic imaging.
- Any action outside the approved OU/group/GPO allowlist.

## 4. Security Model

The broker identity must be least-privilege delegated to the objects above.
Preferred identity order:

1. gMSA with constrained AD delegation to Endpoint Agent objects.
2. Dedicated domain service account with explicit ACLs and no interactive logon.
3. Operator-triggered scheduled task with audited credentials as a temporary
   bridge only.

Every mutation request requires:

- Platform RBAC authorization.
- Maker-checker approval for mutating operations.
- Request TTL.
- Idempotency key.
- Explicit target object and expected pre-state.
- Bounded rollback plan.

The broker returns:

- Request id.
- Operation name.
- Target object DN/GPO id.
- Pre-state hash/summary.
- Post-state hash/summary.
- Result status.
- Redacted stdout/stderr-style diagnostics when needed.
- Actor/request/approval metadata.

Secrets, private keys, raw bearer tokens, and admin credentials are never
returned in logs or issue comments.

## 5. Acceptance Gates

| Gate | Acceptance |
|---|---|
| DOP-0 Design | This document linked from #1609 and reviewed against the current AD/GPO boundary. |
| DOP-0A Product request spine | Admin API + durable request state + credential-ref custody + typed connector dispatch + fail-closed result/status/audit accepted in platform-backend#676. |
| DOP-1 Read-only probe | Broker reads EndpointTest OU, pilot group, and Endpoint Agent GPO state; audit row emitted. |
| DOP-2 Add/remove pilot device | Broker adds then removes a disposable test computer membership with pre/post audit and idempotency proof. |
| DOP-3 GPO link/filtering smoke | Broker links or verifies the Endpoint Agent GPO on EndpointTest OU and records exact filtering state. |
| DOP-4 Rollback proof | Broker reverts its own GPO/group mutation and proves state restored. |
| DOP-5 Product integration | Platform request/approval/audit flow can trigger DOP-1..DOP-4 without SSH/RDP clipboard operations. |

## 6. Pilot Device Policy

The accepted #1609 two-device record is limited to:

- `SRB-AIDENETIMPC`
- `ERP-MOBIL`

`AgentPC2` is now a separate third-device product-channel gate tracked in
#1643. It must not be accepted from lab reverse SSH/RDP, inbound SSH/WinRM/SMB
or operator-pasted commands. Valid evidence is GPO/signed MSI, one-command
bootstrap, existing EndpointAgent mTLS product channel, or Domain Ops Broker
typed operation evidence. `AgentPC1` remains a reserve device. Local Parallels
Windows remains the break/fix lab for installer and agent regressions.

## 7. Relationship To Remote-Ops

Domain Ops Broker handles domain-side deployment state. Endpoint remote-ops
handles endpoint-side diagnostics and bounded remediation after the agent is
installed. They are separate systems:

- Domain Ops Broker can mutate AD/GPO within a narrow allowlist.
- Endpoint remote-ops can run bounded endpoint actions over outbound mTLS.
- Neither system exposes raw shell.
- Both require TTL, audit, and rollback/fail-close behavior.
