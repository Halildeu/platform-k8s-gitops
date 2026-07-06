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

Operator-safe helper for the catalog-bound `UPDATE_AGENT` seed path:

Status note (2026-06-20): `platform-backend#712` is accepted-bounded via the
`v0.2.11` catalog-bound update path on `HALILKOOLUB735`. The commands below are
kept as the repeatable helper for future pilot reruns or equivalent endpoints;
they are no longer the active #712 blocker. The current #208 blocker is
AgentPC2 endpoint-local first-install/bootstrap evidence tracked by
`platform-k8s-gitops#1768`.

```bash
EVIDENCE_DIR=/tmp/remote-response-terminal-update-agent-seed-$(date -u +%Y%m%dT%H%M%SZ) \
scripts/faz22-remote-ops/remote-response-terminal-update-agent-seed.sh
```

Default mode is plan-only and performs no live mutation. It writes the planned
release-catalog payload, planned dispatch payload, a negative-dispatch payload,
the public release manifest, redacted binary URL headers, `binary-sha256.json`,
`summary.json`, and `SHA256SUMS`. It also downloads the loose signed
`endpoint-agent.exe` to a temporary file, validates the SHA256, then removes the
temporary binary.

Create/approve the `v0.2.10` release row only after a manager JWT and a second
maker-checker subject are available:

```bash
LIVE_MUTATION=1 \
RUN_CREATE=1 \
RUN_APPROVE=1 \
CREATOR_BEARER_TOKEN_FILE=/secure/path/creator.jwt \
APPROVER_BEARER_TOKEN_FILE=/secure/path/approver.jwt \
EVIDENCE_DIR=/home/halil/codex-rb-smoke/<timestamp>-update-agent-seed \
scripts/faz22-remote-ops/remote-response-terminal-update-agent-seed.sh
```

Dispatch to a pilot endpoint only after the release row is
`APPROVED`+enabled. Keep JWTs in token files, not command-line env values:

```bash
LIVE_MUTATION=1 \
RUN_NEGATIVE_DISPATCH=1 \
RUN_DISPATCH=1 \
DISPATCH_BEARER_TOKEN_FILE=/secure/path/dispatcher.jwt \
TARGET_DEVICE_ID=d0efb00a-681a-4e32-b7de-a27ef94f2977 \
TARGET_DEVICE_HOSTNAME=HALILKOOLUB735 \
EVIDENCE_DIR=/home/halil/codex-rb-smoke/<timestamp>-update-agent-dispatch \
scripts/faz22-remote-ops/remote-response-terminal-update-agent-seed.sh
```

The helper refuses all `RUN_*` actions unless `LIVE_MUTATION=1` is set. It does
not prove `platform-agent#208` acceptance by itself. After dispatch, rerun the
pilot readiness helper with `REQUIRE_READY=1`; only a fresh post-update
heartbeat proving `v0.2.10` can unlock the constrained-terminal product smoke.

### 6.2 Runtime Evidence Verifier For 22.6.3

After the product-channel constrained operation smoke is captured, verify the
evidence bundle before posting it as `platform-agent#208` runtime evidence:

```bash
EVIDENCE_DIR=/home/halil/codex-rb-smoke/<timestamp>-remote-response-terminal \
REQUIRE_ACCEPTED=1 \
scripts/faz22-remote-ops/remote-response-terminal-evidence-verify.sh
```

The verifier is read-only against the platform. It does not open a session,
dispatch an operation, read the staging database, mutate Kubernetes, update
GitOps desired-state, or touch the endpoint. It only consumes files already
captured under `EVIDENCE_DIR` and writes `verification-summary.json`.

Accepted input names:

- allowed operation response:
  `catalog-operation.body`, `approved-script-operation.body`,
  `terminal-operation.body`, `response-terminal-operation.body`,
  `operation.body`, or `permit.body`;
- recording export:
  `session-recording.jsonl`, `recording.jsonl`,
  `remote-bridge-recording.jsonl`, `agent-output.jsonl`,
  `session-recording.tsv`, `recording.tsv`, `session-recording.psv`,
  `recording.psv`, `session-recording.csv`, or `recording.csv`;
- core negative evidence:
  `raw-pty-deny.body` or equivalent raw/unrestricted deny file, plus
  `command-override-deny.body` or equivalent command/policy override deny file;
- optional wider matrix evidence:
  disabled/revoked operation denies, no-auth/role/step-up denies, expired
  permit, wrong device/tenant, replay, heartbeat-loss, and revoke/kill
  evidence;
- governance evidence:
  `governance-evidence.json`, `governance/summary.json`,
  `approval-evidence.json`, or `operator-governance.json`;
- redaction scan surface:
  the verifier-relevant operation, recording, session ownership, pilot
  readiness, governance, negative response, request, JSONL/TSV/PSV/CSV evidence
  files. The verifier reports only file paths and marker classes; it never
  copies matched values into `verification-summary.json`;
- `SHA256SUMS` for evidence integrity. The manifest must cover the allowed
  operation response, the recording export, and the required negative evidence
  files; a stale manifest that omits required files is not accepted.

Default acceptance rules:

- the allowed response must be `PERMIT`;
- `transportPushed=true`;
- `deny` is absent/null;
- permit signature metadata is present;
- capability is `CONSTRAINED_PTY`;
- the response is bound to a server-owned source
  (`catalogOperationId`, `approvedScript.scriptId`, or `permit.commandHash`);
- pilot readiness evidence proves `decision=ready-for-product-smoke`,
  artifact manifest `ok=true`, and the target endpoint reports the expected
  agent release/version;
- the redacted session ownership guard output is present and proves
  `REMOTE_RESPONSE_TERMINAL_SESSION_GUARD_STATUS=owned`;
- the session ownership evidence contains only short SHA-derived session and
  endpoint hashes plus owner comment metadata, not raw session ids or bearer
  values;
- governance evidence proves distinct operator and approver subjects, approval
  id, step-up verification, ticket reference, justification, WORM recording,
  and fail-closed recording policy;
- governance evidence contains no raw bearer token, JWT, session id, private
  key, password, client secret, or equivalent sensitive marker;
- the verifier-relevant evidence bundle contains no high-confidence bearer,
  JWT, explicit session secret/env marker such as `REMOTE_BRIDGE_SESSION_ID`,
  private-key, client-secret/API-key, operator-token env, OAuth-token, or
  PostgreSQL credential markers;
- the recording export contains `AGENT_OUTPUT` or equivalent `DATA`;
- the recording export contains terminal `EndStream`;
- core raw-shell and command/policy override negative evidence is present;
- `SHA256SUMS` verifies cleanly and lists the required evidence files,
  including `session-ownership-guard.out`, `pilot-readiness/summary.json`, and
  `governance-evidence.json` when those requirements are enabled.

Canonical governance evidence shape:

```json
{
  "operator": {
    "subject": "rb-operator-denetim"
  },
  "approver": {
    "subject": "rb-approver-denetim"
  },
  "approval": {
    "id": "approval-123"
  },
  "stepUp": {
    "verified": true,
    "method": "webauthn"
  },
  "ticketRef": "INC-123",
  "justification": "Bounded hostname diagnostic for platform-agent#208",
  "recording": {
    "worm": true,
    "failClosed": true
  }
}
```

The file is an exported governance summary, not a credential container. Use
stable redacted subjects or product user ids; do not include bearer tokens,
raw JWTs, raw `REMOTE_BRIDGE_SESSION_ID`, cookies, private keys, passwords,
or personal contact/payment data.

Operator-safe normalization helper for this file:

```bash
SOURCE_GOVERNANCE_FILE=/path/to/product-governance.json \
EVIDENCE_DIR=/home/halil/codex-rb-smoke/<timestamp>-remote-response-terminal \
scripts/faz22-remote-ops/remote-response-terminal-governance-export.sh
```

The helper is read-only/offline. It normalizes only an already captured product
governance JSON document; it does not accept raw manual env fields as proof and
does not create an approval, step-up, ticket, or recording policy record. It
writes or refreshes:

- `governance-evidence.json` — canonical verifier input;
- `governance-evidence-summary.json` — source digest, parsed field checks,
  validation reason, and residual boundary;
- `SHA256SUMS` — refreshed over the evidence bundle.

The helper fails closed when the source is missing, invalid JSON, self-approved,
missing operator/approver/approval id/step-up/ticket/justification/WORM
recording/fail-closed recording policy, or contains sensitive markers such as
bearer/JWT/session/private-key/password material. If the source file is outside
`EVIDENCE_DIR`, the helper records only its basename plus SHA256 digest; it does
not copy the raw source into the evidence bundle.

Useful strict modes:

```bash
# Fail unless the bounded runtime evidence is an accepted candidate.
REQUIRE_ACCEPTED=1 scripts/faz22-remote-ops/remote-response-terminal-evidence-verify.sh

# Also fail unless broader lifecycle/authz/replay/termination evidence is present.
REQUIRE_ACCEPTED=1 REQUIRE_FULL_MATRIX=1 \
scripts/faz22-remote-ops/remote-response-terminal-evidence-verify.sh

# Run the AgentPC2 acceptance workflow in the same fail-closed full-matrix mode.
gh workflow run faz22-agentpc2-constrained-executor-acceptance.yml \
  --repo Halildeu/platform-k8s-gitops \
  -f confirm=RUN_AGENTPC2_CONSTRAINED_EXECUTOR_ACCEPTANCE \
  -f expected_digest=sha256:fb229ff98a1b7afb3cc31fe6de49312192686ee3ff6f80952494892d19b23b0d \
  -f device_id=2f7ad30f-970a-42e7-8af8-08764ae6066f \
  -f device_hostname=AgentPc2 \
  -f require_full_matrix=true

# Session ownership evidence is required by default for Remote Response Terminal
# accepted candidates. Use this only to inspect legacy evidence that predates
# the ownership guard; do not use it for #208 acceptance.
REQUIRE_SESSION_OWNERSHIP=0 \
scripts/faz22-remote-ops/remote-response-terminal-evidence-verify.sh

# Pilot readiness evidence is required by default for Remote Response Terminal
# accepted candidates. Use this only to inspect legacy evidence that predates
# the readiness verifier guard; do not use it for #208 acceptance.
REQUIRE_PILOT_READINESS=0 \
scripts/faz22-remote-ops/remote-response-terminal-evidence-verify.sh

# Governance evidence is required by default for Remote Response Terminal
# accepted candidates. Use this only to inspect legacy evidence that predates
# this governance verifier guard; do not use it for #208 acceptance.
REQUIRE_GOVERNANCE_EVIDENCE=0 \
scripts/faz22-remote-ops/remote-response-terminal-evidence-verify.sh

# Bundle-level redaction scanning is required by default for Remote Response
# Terminal accepted candidates. Use this only to inspect legacy evidence that
# predates the evidence redaction guard; do not use it for #208 acceptance.
REQUIRE_EVIDENCE_REDACTION=0 \
scripts/faz22-remote-ops/remote-response-terminal-evidence-verify.sh

# Pin the expected catalog operation for one smoke.
EXPECTED_CATALOG_OPERATION_ID=GET_HOSTNAME REQUIRE_ACCEPTED=1 \
scripts/faz22-remote-ops/remote-response-terminal-evidence-verify.sh
```

Verifier decision values are intentionally bounded:

- `accepted-candidate` means PERMIT, transport, pilot readiness, redacted
  session ownership, governance evidence, bounded output recording, core
  negative evidence, and checksum evidence are present.
- `missing-pilot-readiness` or `invalid-pilot-readiness` means the bundle does
  not prove an endpoint was already running the expected constrained-executor
  artifact before the terminal smoke.
- `missing-session-ownership` or `invalid-session-ownership` means the bundle
  does not prove the single-owner live-smoke coordination guard.
- `missing-governance-evidence` or `invalid-governance-evidence` means the
  bundle does not prove dual-control, step-up, ticket/justification, approval
  id, WORM recording, and fail-closed recording policy without sensitive
  marker leakage.
- `sensitive-evidence-marker` means a verifier-relevant evidence file contains
  a high-confidence sensitive marker class. Redact or replace the file before
  using the bundle for #208 accepted-candidate evidence. The summary names only
  the file and marker class, not the matched secret/session value.
- `missing-permit`, `missing-transport-push`, `missing-permit-signature`,
  `wrong-capability`, or `missing-server-owned-source-binding` mean the allowed
  operation response cannot prove the product-channel constrained path.
- `recording-unavailable`, `missing-agent-output`, or `missing-end-stream` mean
  the endpoint output path is not proven.
- `sha256-unverified` means evidence integrity was not proven.
- `missing-negative` means the core deny evidence is absent.
- `missing-full-negative-matrix` means `REQUIRE_FULL_MATRIX=1` was requested but
  lifecycle/authz/replay/termination evidence is still incomplete.

Full-matrix workflow mode is intentionally fail-closed. The AgentPC2 harness
captures only product-supported live negatives through the remote-bridge
operator REST surface. Today that includes wrong-device/not-enrolled session
open denial and closed-session operation denial. It must not synthesize expired
permits, replayed frames, or kill/revoke events through direct DB mutation or
test fixtures; those are not product-path evidence. Until a product endpoint or
real runtime path exists for those classes, `REQUIRE_FULL_MATRIX=1` is expected
to fail closed with `missing-full-negative-matrix`.

`accepted-candidate` is not `Done` for `platform-agent#208` by itself. It does
not prove signed MSI/GPO rollout, 5-PC/50-PC/800-PC readiness, production
support readiness, unrestricted shell safety, or true TPM/device-key
hardware-attestation. The #208 `Done` transition still requires the accepted
evidence comment to name the remaining acceptance items and the owner to accept
the lifecycle/authz/replay/termination boundary that was actually proven.

### 6.3 Recording Export For The Verifier

The WORM recording table stores metadata hashes, not raw endpoint output. That
is intentional: raw terminal output has a shorter retention/privacy boundary.
For #208 runtime acceptance, export the durable metadata trail and pair it with
the allowed operation response, negative response bodies, and `SHA256SUMS`.
Use the recording export helper as the final bundling step after the operation
and negative response files are already in `EVIDENCE_DIR`, so the generated
`SHA256SUMS` covers the full evidence bundle.

Read-only export from a staging SSH target:

```bash
SESSION_ID=<remote-bridge-session-id> \
STAGING_SSH_TARGET=halil@staging-sw \
EVIDENCE_DIR=/home/halil/codex-rb-smoke/<timestamp>-remote-response-terminal \
scripts/faz22-remote-ops/remote-response-terminal-recording-export.sh
```

Read-only export from a local PostgreSQL URL:

```bash
SESSION_ID=<remote-bridge-session-id> \
DATABASE_URL=postgresql://<redacted>@<host>:5432/endpoint_admin \
EVIDENCE_DIR=/home/halil/codex-rb-smoke/<timestamp>-remote-response-terminal \
scripts/faz22-remote-ops/remote-response-terminal-recording-export.sh
```

Offline normalization of a previously exported JSONL file:

```bash
SOURCE_RECORDING_ROWS_FILE=/path/to/session-recording.jsonl \
EVIDENCE_DIR=/home/halil/codex-rb-smoke/<timestamp>-remote-response-terminal \
scripts/faz22-remote-ops/remote-response-terminal-recording-export.sh
```

The helper writes or refreshes:

- `session-recording.jsonl` — one normalized JSON object per WORM row;
- `recording-summary.json` — row counts, kind counts, and an acceptance hint;
- `recording-query.sql` when the helper performs the DB export;
- `SHA256SUMS`.

Expected WORM rows for a terminal evidence candidate include `AGENT_OUTPUT` or
equivalent DATA evidence and a terminal marker such as `SESSION_END` or
`EndStream`. A recording bundle with only `POLICY_EVENT` rows is useful
control-plane evidence, but it does not prove endpoint output reached the
recording/audit path. Run the verifier against the same `EVIDENCE_DIR`:

```bash
REQUIRE_ACCEPTED=1 \
scripts/faz22-remote-ops/remote-response-terminal-evidence-verify.sh \
  /home/halil/codex-rb-smoke/<timestamp>-remote-response-terminal
```

### 6.4 Runtime Smoke Orchestrator For 22.6.3

Use the runtime smoke orchestrator when the pilot endpoint already reports
`v0.2.10` and an owned, approved, step-up-verified remote-bridge session id is
available. The orchestrator composes the existing product-path helpers; it does
not invent a new API and does not bypass the catalog/approved-script,
recording, or verifier boundaries.

Default mode is plan-only and dispatches nothing:

```bash
EVIDENCE_DIR=/tmp/remote-response-terminal-runtime-smoke-$(date -u +%Y%m%dT%H%M%SZ) \
scripts/faz22-remote-ops/remote-response-terminal-runtime-smoke.sh
```

The default output is useful for handoff/inspection, but it is not #208
runtime evidence. It writes `runtime-smoke-plan.json`, `summary.json`, and
`SHA256SUMS` with `status=plan-ready-no-operation`.

Run the allowed catalog operation path only with explicit live-operation
opt-in, a session id, and an operator token file:

```bash
LIVE_OPERATION=1 \
RUN_PILOT_READINESS=1 \
RUN_GOVERNANCE_EXPORT=1 \
PILOT_REQUIRE_READY=1 \
RUN_OPERATION=1 \
RUN_RECORDING_EXPORT=1 \
RUN_VERIFY=1 \
OPERATOR_BEARER_TOKEN_FILE=/secure/path/operator.jwt \
REMOTE_BRIDGE_SESSION_ID=<fresh-owned-step-up-verified-session> \
SOURCE_GOVERNANCE_FILE=/path/to/product-governance.json \
CATALOG_OPERATION_ID=GET_HOSTNAME \
STAGING_SSH_TARGET=halil@staging-sw \
EVIDENCE_DIR=/home/halil/codex-rb-smoke/<timestamp>-remote-response-terminal \
scripts/faz22-remote-ops/remote-response-terminal-runtime-smoke.sh
```

Before `RUN_VERIFY=1` can produce an accepted #208 candidate, place the
product-exported governance summary in the same `EVIDENCE_DIR` as
`governance-evidence.json`. The runtime smoke orchestrator does not generate
or infer governance proof. It only passes the verifier default
`VERIFY_REQUIRE_GOVERNANCE_EVIDENCE=1`, so a missing governance export fails
closed instead of silently accepting a privileged terminal action.

If the recording rows have already been exported, reuse that file instead of
querying PostgreSQL over SSH:

```bash
LIVE_OPERATION=1 \
RUN_PILOT_READINESS=1 \
RUN_GOVERNANCE_EXPORT=1 \
PILOT_REQUIRE_READY=1 \
RUN_OPERATION=1 \
RUN_RECORDING_EXPORT=1 \
RUN_VERIFY=1 \
OPERATOR_BEARER_TOKEN_FILE=/secure/path/operator.jwt \
REMOTE_BRIDGE_SESSION_ID=<fresh-owned-step-up-verified-session> \
SOURCE_GOVERNANCE_FILE=/path/to/product-governance.json \
SOURCE_RECORDING_ROWS_FILE=/path/to/session-recording.jsonl \
EVIDENCE_DIR=/home/halil/codex-rb-smoke/<timestamp>-remote-response-terminal \
scripts/faz22-remote-ops/remote-response-terminal-runtime-smoke.sh
```

Strict candidate mode should be used for a #208 evidence comment:

```bash
LIVE_OPERATION=1 \
RUN_PILOT_READINESS=1 \
RUN_GOVERNANCE_EXPORT=1 \
PILOT_REQUIRE_READY=1 \
RUN_OPERATION=1 \
RUN_RECORDING_EXPORT=1 \
RUN_VERIFY=1 \
VERIFY_REQUIRE_ACCEPTED=1 \
OPERATOR_BEARER_TOKEN_FILE=/secure/path/operator.jwt \
REMOTE_BRIDGE_SESSION_ID=<fresh-owned-step-up-verified-session> \
SOURCE_GOVERNANCE_FILE=/path/to/product-governance.json \
CATALOG_OPERATION_ID=GET_HOSTNAME \
STAGING_SSH_TARGET=halil@staging-sw \
EVIDENCE_DIR=/home/halil/codex-rb-smoke/<timestamp>-remote-response-terminal \
scripts/faz22-remote-ops/remote-response-terminal-runtime-smoke.sh
```

The orchestrator refuses `RUN_OPERATION=1` unless `LIVE_OPERATION=1` is set.
It keeps bearer values out of argv examples and evidence by using token files.
For #208 acceptance, keep `RUN_PILOT_READINESS=1 PILOT_REQUIRE_READY=1` so the
evidence bundle contains `pilot-readiness/summary.json` with
`decision=ready-for-product-smoke`; the verifier requires that file by default
for `accepted-candidate`.
When live operation is run with the default `SESSION_OWNER_REQUIRED=1`, it
writes `session-ownership-guard.out`; the verifier requires that file by
default for `accepted-candidate`.
When `VERIFY_REQUIRE_GOVERNANCE_EVIDENCE=1` remains at its default, the
verifier also requires `governance-evidence.json` to prove distinct
operator/approver subjects, step-up, ticket, justification, approval id, WORM
recording, and fail-closed recording policy. Set
`VERIFY_REQUIRE_GOVERNANCE_EVIDENCE=0` only for legacy inspection; do not use
that opt-out for `platform-agent#208` acceptance.
When `VERIFY_REQUIRE_EVIDENCE_REDACTION=1` remains at its default, the verifier
also fails closed on high-confidence sensitive marker classes in the captured
evidence bundle. Set `VERIFY_REQUIRE_EVIDENCE_REDACTION=0` only for legacy
inspection; do not use that opt-out for `platform-agent#208` acceptance.
Set `RUN_GOVERNANCE_EXPORT=1 SOURCE_GOVERNANCE_FILE=/path/to/product-governance.json`
when the bundle should normalize the product-exported governance file before
verification. If the source file is absent or incomplete, the orchestrator
fails before dispatch/verification instead of fabricating governance proof.
It does not prove that the endpoint is already on `v0.2.10`; run pilot
readiness first or set `RUN_PILOT_READINESS=1 PILOT_REQUIRE_READY=1` to fail
unless that precondition is true.

### 6.5 Live Session Ownership Guard

Before any live terminal smoke, create a redacted single-owner claim on the
implementation issue that owns the runtime evidence, normally
`platform-agent#208`. The claim is a coordination guard, not acceptance
evidence. It prevents two operator/agent sessions from dispatching against the
same endpoint at the same time.

Create the ownership claim after the operator has the approved, step-up-verified
remote-bridge session id. The helper hashes the session id and endpoint id; it
never writes the raw session id, bearer token, JWT, endpoint hostname, or user
data to GitHub:

```bash
ACTION=claim \
SESSION_OWNER_ISSUE_URL=https://github.com/Halildeu/platform-agent/issues/208 \
SESSION_OWNER_ENDPOINT_ID=<target-endpoint-device-id> \
REMOTE_BRIDGE_SESSION_ID=<fresh-owned-step-up-verified-session> \
SESSION_OWNER_TTL_MINUTES=45 \
scripts/faz22-remote-ops/remote-response-terminal-session-ownership-guard.sh
```

Run the runtime smoke with the same ownership fields. By default, live
operation dispatch requires this check and fails closed if no matching active
claim exists, if the claim expired, or if another active claim exists for the
same endpoint hash:

```bash
LIVE_OPERATION=1 \
RUN_OPERATION=1 \
RUN_RECORDING_EXPORT=1 \
RUN_VERIFY=1 \
VERIFY_REQUIRE_ACCEPTED=1 \
SESSION_OWNER_ISSUE_URL=https://github.com/Halildeu/platform-agent/issues/208 \
SESSION_OWNER_ENDPOINT_ID=<target-endpoint-device-id> \
OPERATOR_BEARER_TOKEN_FILE=/secure/path/operator.jwt \
REMOTE_BRIDGE_SESSION_ID=<fresh-owned-step-up-verified-session> \
CATALOG_OPERATION_ID=GET_HOSTNAME \
STAGING_SSH_TARGET=halil@staging-sw \
EVIDENCE_DIR=/home/halil/codex-rb-smoke/<timestamp>-remote-response-terminal \
scripts/faz22-remote-ops/remote-response-terminal-runtime-smoke.sh
```

For tightly controlled single-operator runs, the orchestrator can create and
then check the claim immediately before dispatch:

```bash
SESSION_OWNER_AUTO_CLAIM=1 \
SESSION_OWNER_ISSUE_URL=https://github.com/Halildeu/platform-agent/issues/208 \
SESSION_OWNER_ENDPOINT_ID=<target-endpoint-device-id> \
LIVE_OPERATION=1 RUN_OPERATION=1 \
OPERATOR_BEARER_TOKEN_FILE=/secure/path/operator.jwt \
REMOTE_BRIDGE_SESSION_ID=<fresh-owned-step-up-verified-session> \
scripts/faz22-remote-ops/remote-response-terminal-runtime-smoke.sh
```

Release the claim after the smoke or when the session is abandoned:

```bash
ACTION=release \
SESSION_OWNER_ISSUE_URL=https://github.com/Halildeu/platform-agent/issues/208 \
SESSION_OWNER_ENDPOINT_ID=<target-endpoint-device-id> \
REMOTE_BRIDGE_SESSION_ID=<fresh-owned-step-up-verified-session> \
SESSION_OWNER_RELEASE_REASON=done \
scripts/faz22-remote-ops/remote-response-terminal-session-ownership-guard.sh
```

This guard mirrors common remote monitoring and management practice: just-in
time operator access, explicit session ownership, short TTL, redacted audit
trail, fail-closed conflict detection, and separate acceptance evidence. It is
not a security boundary by itself; broker-side device binding, maker-checker,
step-up auth, command policy, recording, and endpoint permit validation remain
the enforcement boundaries. The live smoke evidence bundle must retain the
generated `session-ownership-guard.out` file so the verifier can prove the
single-owner coordination path was used without exposing raw session material.

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
