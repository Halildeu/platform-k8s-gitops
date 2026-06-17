# RB — Faz 22.6 Product Remote-Ops Session Gate

> **Status**: ACTIVE gate contract, 2026-06-17.
> **Scope**: Denetim PC (`SRB-AIDENETIMPC`) first, ERP-MOBIL second evidence
> only. AgentPC2 is a separate third-device product-channel gate (#1643).
> **Board**: platform-backend#510 + platform-k8s-gitops#1601.
>
> **Non-claim**: this runbook does not prove the gate by existing. It defines
> the evidence required before #510/#1601 can move from source/productization
> readiness to live product remote-ops acceptance.

## 1. Decision

Use a **real product remote-ops session** as the acceptance gate:

- Agent initiates the session over outbound mTLS/gRPC.
- Broker issues a short-lived signed permit after operator authz and
  maker-checker/owner approval.
- The first live operation is a typed read-only operation, not a shell.
- All results and decisions are audit-recorded before the session can be
  considered accepted.

The first target is **Denetim PC / SRB-AIDENETIMPC** unless change control
blocks it. ERP-MOBIL is a higher-blast-radius AD CS/domain-adjacent server and
is only second evidence after Denetim PC passes.

## 2. Cross-AI Consultation Result

2026-06-17 consultation outcome:

| Reviewer | Verdict | Absorbed requirement |
|---|---|---|
| Claude CLI | AGREE with deltas | idle/session timeout, heartbeat-loss auto-terminate, replay test, concurrent-session limit, audit immutability, global kill-switch |
| Mavis | unavailable this run | not asserted; CLI required a session id, so no completed Mavis verdict is recorded |
| Codex CLI | REVISE | outbound-only wording must match topology; owner-gated activation semantics must be explicit; shared-image 8096/8081 reachability must be negatively proven |

Result: **REVISE -> ACCEPTABLE**. Do not start the first live session until the
acceptance matrix below is wired to evidence.

## 3. Product-Channel Rule

Accepted product-channel evidence:

- Outbound mTLS/gRPC session initiated by EndpointAgent.
- Signed permit validated by the agent and bound to device identity.
- Typed remote operation result and audit row produced by the product stack.

Not accepted as product-channel evidence:

- RDP clipboard/manual PowerShell.
- Lab reverse SSH tunnel.
- Inbound SSH, WinRM, SMB, RPC, or direct port-opening on the endpoint.
- Manual token paste or credential-bearing command payload.
- Any raw private key, bearer token, JWT, password, webhook URL, cookie, or
  device secret in logs, issue comments, PR bodies, or runbook output.

## 4. Topology Gate

Before live session execution, choose and document exactly one topology:

### Option A — preferred: true outbound-only

The agent opens a long-lived outbound mTLS/gRPC stream to the broker. The broker
does not open a direct network connection to endpoint IPs. Kubernetes
NetworkPolicy does not need broker-to-device egress for the data plane.

This is the preferred first product session topology because it matches the
field reality: endpoints may be outside VPN, behind NAT, or closed to inbound
ports.

### Option B — broker-to-device egress pilot

If the activation overlay still requires broker -> pilot-device egress, do not
call the result "outbound-only". Record it as a scoped pilot data-plane with
static 2-5 device `/32` allowlist and app-layer target/TTL enforcement.

Option B can be a limited network pilot, but it is not sufficient to claim the
VPN-free outbound agent product channel.

## 5. Preflight Evidence

Capture all items before session start:

| Gate | Required evidence |
|---|---|
| Non-prod only | Target namespace/environment is test/non-prod; prod flags stay off |
| Immutable artifact | broker pod imageID matches expected digest; no moving tag claim |
| Primary isolation | primary `endpoint-admin-service` remote bridge disabled |
| Separate broker | separate Deployment/ServiceAccount/secret path; no `part-of=platform` label |
| Secret boundary | broker secret path contains no admin JWT, enrollment pepper, broad DB credential, or command encryption key |
| SA/RBAC | broker service account has no mounted token and no RoleBinding |
| Network exposure | only the intended mTLS bridge port is published; 8096/8081 fail from same-namespace pod, ingress namespace, and host/edge path |
| Agent endpoint | endpoint has no inbound listener used for the session; RDP/SSH/WinRM/SMB not part of evidence |
| Time | broker and endpoint clocks within +/-5 minutes |
| Kill switch | a single config flag can disable new sessions fail-closed |

Read-only cluster preflight helper:

```bash
KUBE_CONTEXT=k3d-test KUBE_NAMESPACE=platform-test \
  scripts/faz22-remote-ops/remote-ops-session-preflight.sh
```

Expected before a live session: `PRECHECK_STATUS=ready`. `not-ready` is an
honest stop condition, not a failure to hide. The helper never reads secret
values; it only checks object names, renderability, exposure shape, and whether
the primary service has accidentally enabled the bridge.

## 6. Happy-Path Gate

The first operation is `GET_AGENT_STATUS` or `GET_AGENT_VERSION`. It must be a
fixed typed operation with a fixed response schema.

Required sequence:

1. Requester A creates a remote-ops session request for the selected device.
2. Approver B approves it; requester and approver are different identities.
3. Broker issues a signed permit containing at least:
   `tenantId`, `deviceId`, `sessionId`, `operatorId`, `operation`,
   `expiresAt`, `jti`, and allowed capability.
4. Agent connects outbound with mTLS and proves device identity.
5. Agent validates permit signature, expiry, `jti`, version, operation, and
   expected `deviceId`.
6. Agent executes only the typed read-only operation.
7. Broker receives typed result and writes audit/recording/hash-chain evidence.
8. Operator terminates the session.
9. Reconnect/heartbeat behavior is observed and recorded.

## 7. Negative Matrix

All negative tests must fail closed and leave audit evidence where applicable:

| Case | Expected |
|---|---|
| feature flag off | no session can be opened |
| no client certificate | rejected |
| wrong CA | rejected |
| expired certificate | rejected |
| wrong device permit | rejected by broker/agent |
| expired permit | rejected |
| replayed permit `jti` | second use rejected |
| missing operator permission | denied before device lookup leaks state |
| requester self-approves | denied |
| unapproved request | no permit |
| unknown operation | denied |
| raw shell / PowerShell / `cmd /c` / encoded command | denied |
| audit sink unavailable | permit issuance or operation execution fails closed |
| heartbeat loss beyond threshold | session auto-terminates |
| mid-session revoke | agent tears down session and audit records revoke |
| endpoint clock skew > +/-5m | rejected |
| broker clock skew > +/-5m | rejected or gate stops before live run |

## 8. Evidence Package

Attach evidence to #510 and #1601 using this structure:

```text
EVIDENCE product-remote-ops-session-gate YYYY-MM-DD

Target:
- device:
- environment:
- topology: outbound-only | broker-to-device-pilot

Preflight:
- imageID:
- primary-bridge-disabled:
- broker-isolation:
- 8096/8081-negative:
- endpoint-inbound-listener:
- time-sync:

Happy path:
- request:
- approval:
- permit:
- mTLS identity:
- typed operation:
- result/audit/hash-chain:
- terminate/reconnect:

Negative matrix:
- feature-off:
- no-cert:
- wrong-CA:
- wrong-device:
- expired-permit:
- replay-jti:
- missing-permission:
- self-approval:
- raw-shell:
- audit-sink-down:
- heartbeat-loss:
- mid-session-revoke:

Does not prove:
- AgentPC2 acceptance
- 5-PC/50-PC/800-PC rollout readiness
- prod remote support readiness
```

## 9. Status Rules

- 2026-06-17 Denetim PC session `rb-denetim-20260617145927` is valid partial
  live evidence: session open, non-pilot rejection, approval, WEBAUTHN step-up,
  consent `ACTIVE`, DB approval/grant, and WORM recording were captured.
- #510 remains open until the same product path proves full `PERMIT + dispatch
  + agent result`, not only fail-closed `DENY`.
- #1601 remains `Needs Verify` until the owner either accepts a deliberately
  split partial-live gate or the full `PERMIT + dispatch + agent result` gate
  is attached.
- #1643 remains `Blocked` until AgentPC2 itself has product-channel evidence.
- Reverse SSH, RDP, operator-pasted commands, or direct inbound ports must not
  move any of these items to `Done`.

## 10. Rollback / Stop Conditions

Stop before the first live session if any of these are true:

- 8096/8081 is reachable from a forbidden source.
- Broker starts with missing signer, TLS material, device CA, or audit sink.
- Primary endpoint-admin service has remote bridge enabled.
- Permit can be replayed.
- Raw shell or unknown operation can execute.
- Audit failure allows a permit/session to proceed.
- The endpoint requires inbound SSH/WinRM/SMB/RPC to make the operation work.

## 11. Not-Ready Unblock Order

When the helper returns `PRECHECK_STATUS=not-ready`, unblock in this order. Do
not skip ahead to a live Denetim PC session.

| Order | Item | Owner | Acceptance evidence |
|---:|---|---|---|
| 1 | Decide topology: Option A outbound-only or Option B broker-to-device pilot | owner + implementer | issue comment states exact topology; no ambiguous "outbound-only" claim |
| 2 | Replace zero digest placeholder with the owner-approved immutable broker image digest | implementer | overlay render shows no zero digest; target digest recorded |
| 3 | Replace RFC5737 placeholder CIDRs or remove broker-to-device egress if Option A is selected | implementer | overlay render has no test-net placeholder CIDR |
| 4 | Seed dedicated remote-bridge secret path with only required broker values | owner/operator | ESO creates `endpoint-admin-remote-bridge-*` Secrets; no secret values in comments/logs |
| 5 | Sync activation overlay into `k3d-test` | implementer/operator | remote-bridge Deployment/Service/NetworkPolicies live in `platform-test` |
| 6 | Run cluster preflight until `PRECHECK_STATUS=ready` | implementer | helper output attached to #510/#1601 |
| 7 | Enable Denetim PC product remote-ops config through the product channel only | implementer | EndpointAgent has remote-ops config without manual token/secret paste |
| 8 | Run typed read-only session and negative matrix | implementer | evidence package attached to #510/#1601 |

Agent-doable work can progress on steps 2, 3, 5, 6, and evidence packaging.
Secret seeding and owner approval remain explicit gates. If those gates are not
available, continue with source/runbook/test hardening and keep #510/#1601 open.
