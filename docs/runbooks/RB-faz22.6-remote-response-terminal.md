# RB-faz22.6 — Remote Response Terminal Productization

> Status: PLANNED / BOARD-TRACKED (2026-06-18)
> Scope owner: `platform-k8s-gitops#1693`
> Related implementation issues: `platform-backend#701`, `platform-backend#702`,
> `platform-agent#208`, `platform-web#820`

This runbook defines the acceptance boundary for the Remote Response Terminal
lane. It does not reopen `platform-backend#510`: that parent is closed for the
accepted staging remote-bridge path. This runbook turns the next product ask
into a separate, auditable 22.6.x lane.

## 1. Product Name And Boundary

The product name is **Remote Response Terminal** or **Break-Glass Response
Shell**. Do not call this a "free shell" or "unrestricted terminal" in
roadmap, issue, PR, or release language.

Allowed architectural path:

```text
Operator / Admin UI
  -> endpoint-admin remote-bridge broker
    -> EndpointAgent outbound mTLS/gRPC channel
      -> target endpoint
```

Disallowed acceptance paths:

```text
Inbound RDP
Inbound SSH
Inbound WinRM
Inbound SMB/RPC
Operator-pasted endpoint PowerShell
Generic reverse tunnel
Unrestricted cmd.exe / powershell.exe shell
```

## 2. Phased Lane

| Lane | Issue | Purpose | Status rule |
|---|---|---|---|
| 22.6.1 | `platform-backend#701` | Approved Operation Catalog | Must land before script runner / terminal |
| 22.6.2 | `platform-backend#702` | Approved Script Runner | Requires signed/hash-pinned script library |
| 22.6.3 | `platform-agent#208` | Break-glass constrained executor | Requires command policy and terminal lifecycle gates |
| UX | `platform-web#820` | Operator-safe UI | UI is not the security boundary |
| Governance | `platform-k8s-gitops#1693` | No-go gates, evidence map, rollout guard | Owns this runbook and current-state truth |

## 3. No-Go Gates

No terminal or script runner production claim is allowed unless every item below
is true:

- Endpoint exposes no inbound management port for the feature.
- Agent validates broker mTLS identity and accepts only our broker path.
- Broker issues device-bound, tenant-bound, short-lived permits.
- Operator and approver are different principals.
- WebAuthn or equivalent step-up is required for script runner and terminal.
- Justification and ticket reference are stored before dispatch.
- WORM/session recording is enabled and fail-closed.
- Command policy is default-deny.
- Raw shell classes are denied before endpoint execution.
- Output is bounded and redacted before storage/display.
- Kill, revoke, heartbeat-loss, and TTL expiry terminate the session.
- Tenant/device isolation negatives are proven.

## 4. Initial Operation Catalog

Initial operations should be diagnostic and low-risk:

```text
GET_AGENT_STATUS
GET_AGENT_VERSION
GET_HOSTNAME
GET_NETWORK_SUMMARY
GET_SERVICE_STATUS
COLLECT_AGENT_LOGS
RUN_CERT_AUTOENROLL_PULSE
REFRESH_SOFTWARE_INVENTORY
```

Each operation must define:

- risk level
- required role
- approval requirement
- consent requirement
- TTL
- output retention
- redaction class
- allowed target device class
- rollback/cleanup note when applicable

## 5. Script Runner Contract

Approved Script Runner must execute only immutable library entries:

```text
scriptId
version
sha256
signer / approver
allowed args schema
timeout
risk class
redaction class
```

Arbitrary script text in the request is denied. Disabled, revoked, mutable,
wrong-tenant, wrong-hash, invalid-args, missing-approval, missing-step-up, and
audit-down cases must fail closed.

## 6. Terminal Command Policy

The first terminal pilot is allowlist-only. Candidate read-only commands:

```text
hostname
whoami /groups
ipconfig /all
route print
nslookup
sc query <approved-service>
wevtutil qe <approved-log> /c:<bounded-count>
dir <approved-log-path>
type <approved-log-file>
tasklist
netstat -ano
```

Default denied classes:

```text
cmd /c <arbitrary>
powershell -EncodedCommand
powershell unrestricted command text
Invoke-WebRequest / curl download-and-execute
certutil download/export
reg save HKLM\SAM or credential-bearing hives
net user add / privilege manipulation
schtasks create
sc create / arbitrary service manipulation
rundll32 arbitrary
wmic process call create
arbitrary file delete
arbitrary installer execution
```

## 7. Acceptance Checklist

Required evidence per lane:

- `PERMIT` path for one allowed operation/command.
- `transportPushed=true` only for permitted work.
- `AGENT_OUTPUT` or equivalent bounded result recorded.
- WORM transcript hash/evidence recorded.
- no-auth fails.
- missing role fails.
- self-approval fails.
- missing justification fails.
- missing/failed step-up fails.
- wrong tenant fails.
- wrong device fails.
- expired permit fails.
- replay fails.
- audit sink down fails closed.
- heartbeat loss terminates.
- mid-session revoke terminates.
- clock skew bounded failure is recorded.
- raw shell classes are denied and not executed.

Each evidence comment must also state what the evidence does not prove:

- signed MSI/GPO rollout
- 5-PC/50-PC/800-PC readiness
- production remote-support readiness
- unrestricted shell/RDP/WinRM/SMB/SSH
- true TPM/device-key hardware-attestation unless `platform-backend#548` has
  separate accepted evidence

## 8. B1.4 Hardware Attestation Boundary

`platform-backend#548` remains Open/Blocked for true device-key / TPM
hardware-attestation on the agent wire. Enrollment-backed trust is acceptable
for the bounded staging path already accepted under `platform-backend#510`, but
it is not broad terminal rollout evidence.

22.6.3 broad rollout requires one of:

- `platform-backend#548` accepted evidence; or
- explicit owner-approved, time-bounded risk acceptance that names the pilot
  scope, device count, duration, rollback, and compensating controls.

## 9. Evidence Storage

Evidence is stored in:

- implementation issue comments (`EVIDENCE`, `READY-FOR-VERIFY`,
  `DONE-CANDIDATE`)
- `docs/state/current-state.md` only after accepted runtime truth changes
- this runbook when acceptance mechanics change
- staging artifact directories with SHA256 manifests when live evidence is
  collected

Never store secrets, JWTs, private keys, raw certificates, passwords, cookies,
or direct personal data in issue comments or docs.
