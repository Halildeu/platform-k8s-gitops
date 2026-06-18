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

### 4.1 Runtime Smoke For 22.6.1

The catalog source gate is not accepted by a source merge alone. Runtime
acceptance requires the broker image that contains `platform-backend#701` to be
running on the remote-bridge path, not only on the primary endpoint-admin
Deployment.

Use the helper below after the selected endpoint-admin digest is pinned and
deployed:

```bash
OPERATOR_BEARER_TOKEN=<redacted> \
REMOTE_BRIDGE_SESSION_ID=<fresh-owned-and-step-up-verified-session> \
CATALOG_OPERATION_ID=GET_HOSTNAME \
EVIDENCE_DIR=/home/halil/codex-rb-smoke/<timestamp>-catalog \
scripts/faz22-remote-ops/remote-ops-catalog-smoke.sh
```

The helper:

- opens only a local port-forward when `REMOTE_BRIDGE_OPERATOR_BASE_URL` is not
  supplied;
- queries `GET /internal/remote-bridge/operator/operation-catalog`;
- verifies enabled entries `GET_HOSTNAME` and `GET_NETWORK_SUMMARY`;
- verifies a disabled catalog entry remains disabled;
- verifies raw `PTY_COMMAND` without `catalogOperationId` is rejected;
- verifies command override with a catalog id is rejected;
- submits one server-owned catalog operation and requires `PERMIT` plus
  `transportPushed=true` by default;
- writes bounded evidence files and SHA256 manifest under `EVIDENCE_DIR`.

If `REMOTE_BRIDGE_SESSION_ID` is omitted, the helper performs only the
authenticated/no-auth catalog preflight and records that operation evidence is
skipped. That is useful for deploy readiness, but it is not #701 acceptance.

Do not use direct `kubectl set image`, `kubectl patch`, or `kubectl edit` for
this lane. The selected digest must be reconciled through GitOps desired-state.
If `platform-backend#706` or another endpoint-admin PR merges before the smoke,
pin the newer combined digest rather than reusing an immediately superseded
#701-only digest.

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

### 6.1 Pilot Endpoint Upgrade Precondition For 22.6.3

`platform-agent#208` runtime acceptance requires an endpoint that is actually
running the constrained-executor artifact under the product channel. A signed
artifact being served by `testai` is a prerequisite, not execution evidence.

Current pilot truth as of the 2026-06-18T23:40Z recheck:

- `testai` artifact-host serves `v0.2.10` with
  `endpoint_agent_sha256=a50344a4457959b95dfdfa22e6578e53cd6ec4b124830b506fe53503c18ba1ec`
  and trusted signer thumbprint `D68F4F530137EB65CE44E3405E82B46205E753E5`.
- Denetim PC `SRB-AIDENETIMPC`
  (`423b6fc3-7497-4083-bd2f-5e2fe543bfe9`) still reports
  `agent_version=0.1.0-dev.g636f1d4-productsession`.
- Its latest heartbeat advertises `INSTALL_SOFTWARE` and
  `UNINSTALL_SOFTWARE`, but does not advertise `UPDATE_AGENT`.
- The live software catalog query returns only 7-Zip WinGet entries for the
  agent/endpoint search surface; no EndpointAgent `v0.2.10` install catalog
  item exists.

Accepted ways to seed the 22.6.3 runtime pilot:

1. **Catalog-bound `UPDATE_AGENT` self-update**, only when the latest heartbeat
   advertises `UPDATE_AGENT`, the `v0.2.10` release exists as
   `APPROVED`+enabled release-catalog metadata, the backend dispatch uses
   `POST /api/v1/admin/endpoint-devices/{deviceId}/agent-updates`, and the
   post-update heartbeat proves the target `agent_version`. The caller supplies
   only release id, reason, schedule, idempotency, and optional ring; binary
   URL, hash, signer thumbprint, signing tier, target version, and max bytes
   must be resolved server-side from the approved catalog.
2. **Owner-approved local maintenance install** from the signed `v0.2.10`
   artifact can seed a single pilot endpoint when self-update is not available,
   but it is not terminal acceptance evidence. It must record endpoint id,
   operator, timestamp, artifact URL, SHA256, signer thumbprint, service state,
   rollback note, and the first post-install heartbeat. Acceptance starts only
   after the product-channel constrained operation records `AGENT_OUTPUT` or
   equivalent DATA/EndStream evidence.
3. **A cert-enrolled test endpoint already running `v0.2.10`** is acceptable
   for the #208 runtime smoke if it uses the same outbound mTLS remote-bridge
   path, tenant/device binding, broker permit validation, and recording/audit
   chain. The evidence must name the endpoint and must not borrow Denetim PC
   identity claims.

Rejected ways to seed or prove the 22.6.3 runtime pilot:

- Software Catalog / `INSTALL_SOFTWARE` unless EndpointAgent is first published
  as an approved WinGet package/catalog item with the normal maker-checker,
  preflight, install audit, and detection-rule contracts. The current
  WinGet-only 7-Zip catalog surface is not a general signed-binary installer.
- Approved Script Runner download-and-execute or arbitrary installer execution
  unless a separate signed install gate is explicitly designed and accepted for
  agent upgrade. The script runner can prove script policy; it must not be
  repurposed as a hidden unrestricted installer lane for #208.
- Generic `/endpoint-commands` `UPDATE_AGENT`, direct database inserts,
  caller-supplied binary URL/hash/signer fields, direct operator PowerShell,
  unrestricted terminal, RDP, SSH, WinRM, SMB/RPC, file browser, reverse tunnel,
  or any manual endpoint command as acceptance evidence.

Decision tree for the next #208 runtime pass:

1. Read the public release manifest and record release tag, SHA256, signer
   thumbprint, and artifact-host digest.
2. Read the target endpoint heartbeat. If it already reports `v0.2.10`, run the
   product-channel constrained operation smoke.
3. If it is older and advertises `UPDATE_AGENT`, use the catalog-bound
   self-update path, then wait for a fresh heartbeat proving `v0.2.10`.
4. If it is older and does not advertise `UPDATE_AGENT`, choose either an
   owner-approved local maintenance install for one pilot endpoint or wait for
   the managed rollout lane. Do not fabricate acceptance through Software
   Catalog, Approved Script Runner, or raw shell.
5. Only after the endpoint reports `v0.2.10`, run the allowed diagnostic
   command plus the negative matrix subset and attach `AGENT_OUTPUT` or
   equivalent DATA/EndStream recording evidence to `platform-agent#208`.

Read-only helper for this gate:

```bash
EVIDENCE_DIR=/tmp/remote-response-terminal-pilot-readiness-$(date -u +%Y%m%dT%H%M%SZ) \
scripts/faz22-remote-ops/remote-response-terminal-pilot-readiness.sh
```

The helper validates the public artifact manifest and, when staging DB access
is available, reads the target endpoint heartbeat, release-catalog candidates,
and software-catalog candidates. It writes `summary.json` with one of these
decision values:

- `ready-for-product-smoke`
- `use-catalog-bound-update-agent`
- `seed-or-approve-release-catalog-first`
- `owner-approved-seed-required`
- `artifact-manifest-mismatch`
- `blocked-live-db-read`
- `target-endpoint-not-found`

Set `REQUIRE_READY=1` when a CI/operator wrapper should fail unless the target
endpoint already reports the expected agent version. The helper is not an
installer and does not dispatch operations.

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
