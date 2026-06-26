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
| Broker live state | Dedicated remote-bridge deployment ready on immutable digest; ExternalSecrets Ready/SecretSynced | `docs/state/current-state.md` plus live `kubectl`; current expected digest `sha256:8c4209ee8643ee58d0a6c2188f93ed61bff69dd32d338f3f0ecf1d63a9fb2842` |
| B1.4 hardware attestation | Real device-key/TPM evidence on agent wire, broker verifier pass, root policy, positive and negative field evidence | `platform-backend#548` |
| VIEW_ONLY screen-share | Product-channel live VIEW_ONLY smoke, D10 recording/fail-closed evidence, DLP/mask policy, local abort, active indicator, KVKK/attended pilot sign-off | `platform-k8s-gitops#1580` |
| Release/version hygiene | Agent release, MSI/ProductVersion/FileVersion, artifact-host current, GitOps expected version, verifier defaults, and acceptance issue evidence agree | release artifacts plus GitOps verifier output |
| Rollout boundary | 5/50/800 readiness is either explicitly out of scope or proven under separate signed MSI/GPO rollout gates | rollout issues, not `#208` |

Release/version hygiene uses
`config/faz22-6-endpoint-agent-release-policy.v1.json` as the SSOT for the
bounded-pilot EndpointAgent release identity. Individual audit, bootstrap,
update, evidence-verifier, or decision-package scripts and workflow dispatch
defaults must not carry their own stale `v0.2.x` release metadata for the active
closure path. The policy covers the release tag, source commit, executable/ZIP
hashes, bootstrap helper hashes, signer fingerprints, artifact-host digest, and
update byte guard. The validator is:

```bash
scripts/faz22-remote-ops/check-endpoint-agent-release-policy.sh
```

## 4. Machine-Readable Gate Acceptance

Issue state alone is not authoritative enough for the sensitive Faz 22.6 gates.
The completion audit therefore requires machine-readable acceptance markers on
the canonical gate issue before it can treat `#548` or `#1580` as passing. This
prevents accidental issue closure, informal comments, or source-only evidence
from becoming product acceptance.

Keep sample marker text in this runbook, not in the live issue body. The audit
reads the live issue body as the approval surface.

### 4.1 B1.4 Hardware Attestation

There are two accepted paths.

The strong path closes `platform-backend#548` only when real device-key / TPM
or secure-element evidence is carried on the agent wire and verified by the
broker:

```text
F22_6_B1_4_HARDWARE_ATTESTATION_ACCEPTANCE: v1
acceptance_scope: hardware-attestation
device_key_evidence: present
tpm_or_secure_element: present
agent_wire_contract: present
broker_verifier: pass
root_policy: pass
field_evidence: attached
positive_matrix: hardware-attested-device
negative_matrix: missing,stale,replay,wrong-device,wrong-tenant
owner_approved_by: <named owner>
approved_at: YYYY-MM-DD
```

The bounded pilot risk path leaves `platform-backend#548` open as a future
hardening gate, but allows the bounded Faz 22.6 pilot to proceed on
enrollment-backed trust when a named owner accepts the residual risk:

```text
F22_6_B1_4_RISK_ACCEPTANCE: v1
risk_scope: bounded-pilot-enrollment-backed-trust
accepted_gap: no-real-tpm-attestation
compensating_controls: cert-bound-token,mTLS,revocation-check,signed-permits,dual-control,audit-recording,kill-revoke
forbidden_claims: tpm-complete,hardware-attestation-complete,5-device,50-device,800-device,production,broad-rollout
owner_approved_by: <named owner>
approved_at: YYYY-MM-DD
expires_at: YYYY-MM-DD
```

Use the package helper to produce either marker from already-approved owner
metadata:

```bash
scripts/faz22-remote-ops/faz22-6-b1-4-acceptance-package.sh \
  --mode risk \
  --marker-out /path/to/b1-4-risk-marker.txt \
  --owner-approved-by "<named owner>" \
  --approved-at YYYY-MM-DD \
  --expires-at YYYY-MM-DD
```

For the strong hardware-attestation path:

```bash
scripts/faz22-remote-ops/faz22-6-b1-4-acceptance-package.sh \
  --mode hardware \
  --marker-out /path/to/b1-4-hardware-marker.txt \
  --owner-approved-by "<named owner>" \
  --approved-at YYYY-MM-DD
```

The helper does not approve `#548`, does not write to GitHub, and does not
create hardware evidence. It only prevents hand-written marker drift after a
real owner decision exists. It rejects placeholder owners, invalid dates,
expired risk windows, and `expires_at` on the hardware path.

### 4.2 VIEW_ONLY Screen-Share Acceptance

`platform-k8s-gitops#1580` can pass only through bounded VIEW_ONLY
product-channel evidence. RDP, credential entry, raw shell, port-forward,
screen-share without recording, or a UI-only session claim does not satisfy
this gate.

```text
F22_6_VIEW_ONLY_ACCEPTANCE: v1
acceptance_scope: bounded-pilot-view-only
product_channel: endpoint-agent-outbound-mtls-remote-bridge
view_mode: VIEW_ONLY
pilot_device: <device or deviceId>
session_id: <product session id>
evidence_package_url: <https URL to canonical JSON evidence manifest>
evidence_package_sha256: <64 hex SHA256 of jq -cS canonical JSON manifest>
recording_worm: pass
d10_fail_closed: pass
dlp_mask_policy: pass
local_abort: pass
active_indicator: pass
viewer_path_decision: fanout-proven
audit_negative_matrix: no-auth,wrong-device,expired-session,recording-down,dlp-deny,local-abort
kvkk_attended_pilot_signoff: pass
forbidden_claims: rdp,credential-entry,raw-shell,port-forward,5-device,50-device,800-device,production,broad-rollout
owner_approved_by: <named owner>
approved_at: YYYY-MM-DD
expires_at: YYYY-MM-DD
```

`viewer_path_decision` may be `fanout-proven` or `owner-deferred`. A defer keeps
the fan-out limitation explicit; it does not prove broad operator-viewer
readiness.

The evidence package URL must be fetchable over HTTPS by the audit runner and
must return a JSON manifest whose `jq -cS` canonical representation hashes to
`evidence_package_sha256`. The manifest must use this schema:

```json
{
  "schema_version": "faz22.6-view-only-evidence-v1",
  "acceptance_scope": "bounded-pilot-view-only",
  "product_channel": "endpoint-agent-outbound-mtls-remote-bridge",
  "view_mode": "VIEW_ONLY",
  "pilot_device": "<device or deviceId>",
  "session_id": "<product session id>",
  "recording_worm": "pass",
  "d10_fail_closed": "pass",
  "dlp_mask_policy": "pass",
  "local_abort": "pass",
  "active_indicator": "pass",
  "viewer_path_decision": "fanout-proven",
  "audit_negative_matrix": [
    "no-auth",
    "wrong-device",
    "expired-session",
    "recording-down",
    "dlp-deny",
    "local-abort"
  ],
  "kvkk_attended_pilot_signoff": "pass",
  "forbidden_claims": [
    "rdp",
    "credential-entry",
    "raw-shell",
    "port-forward",
    "5-device",
    "50-device",
    "800-device",
    "production",
    "broad-rollout"
  ],
  "owner_approved_by": "<named owner>",
  "approved_at": "YYYY-MM-DD",
  "expires_at": "YYYY-MM-DD"
}
```

`viewer_path_decision` in the manifest must match the issue marker and may be
either `fanout-proven` or `owner-deferred`; the JSON block above shows the
fan-out-proven case.

The manifest is intentionally metadata-only. Do not publish raw screen-share
frames, credentials, private endpoint identifiers, personal data, or operator
tokens in the manifest. Store sensitive recording material in the approved WORM
evidence location and expose only redacted references and hashes.

Use the package helper to produce the canonical JSON, `jq -cS` SHA256, and
issue marker from already-approved evidence metadata:

```bash
scripts/faz22-remote-ops/faz22-6-view-only-evidence-package.sh \
  --manifest-out /path/to/view-only-evidence.json \
  --marker-out /path/to/view-only-marker.txt \
  --evidence-url https://example.invalid/view-only-evidence.json \
  --pilot-device AgentPc2 \
  --session-id <product session id> \
  --recording-worm pass \
  --d10-fail-closed pass \
  --dlp-mask-policy pass \
  --local-abort pass \
  --active-indicator pass \
  --viewer-path-decision fanout-proven \
  --kvkk-attended-pilot-signoff pass \
  --owner-approved-by "<named owner>" \
  --approved-at YYYY-MM-DD \
  --expires-at YYYY-MM-DD
```

The helper does not approve #1580, does not write to GitHub, and does not prove
a live VIEW_ONLY session by itself. It only prevents hand-written marker/hash
drift once the owner/operator-gated evidence exists.

Marker parsing is fail-closed:

- named owner cannot be empty, `TBD`, `none`, `n/a`, `na`,
  `placeholder`, `owner`, or the literal example `named-owner`;
- dates must parse as UTC `YYYY-MM-DD`;
- expired acceptance/risk windows fail;
- `evidence_package_url` must be HTTPS and fetchable;
- `evidence_package_sha256` must match the canonical JSON evidence manifest;
- required manifest fields must match the issue marker;
- forbidden rollout claims must be explicitly listed;
- the marker must live on the canonical issue body, not only in a comment.

## 5. Explicit Non-Completion Cases

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

## 6. Release And Version Standard

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

## 7. Owner Decisions Needed

Two decisions unblock the remaining completion path:

1. `platform-backend#548`: Is hardware-backed device-key/TPM attestation a hard
   requirement before broad rollout, or will the owner accept a named,
   time-bounded, compensated pilot risk on enrollment-backed trust?
2. `platform-k8s-gitops#1580`: Which approved pilot device and operator window
   will produce the VIEW_ONLY live screen-share evidence package?

If either decision is not available, the autonomous path continues by hardening
source/verifier coverage and preparing evidence scripts, but completion cannot
be claimed.

After a live audit, generate a read-only owner decision package instead of
hand-interpreting the final blocker lines:

```bash
scripts/faz22-remote-ops/faz22-6-completion-decision-package.sh \
  --audit-file /path/to/faz22-6-completion-audit.txt \
  --output-dir /path/to/decision-package
```

The package writes bounded JSON/Markdown with the parsed completion status,
remaining owner inputs, and the exact helper commands for B1.4, VIEW_ONLY, and
release-lineage. It does not approve risk, write issue markers, mutate GitHub,
touch Kubernetes/endpoints/releases/secrets, or claim completion.

## 8. Audit Command

Use the completion audit helper before reporting status:

```bash
scripts/faz22-remote-ops/faz22-6-completion-audit.sh
```

Mac/operator shells use `SSH_TARGET=staging-sw` by default and collect live
broker evidence over SSH. If TCP/22 to `staging-sw` is unavailable, use the
self-hosted runner path instead of treating the Mac-side SSH failure as cluster
truth:

```bash
REMOTE_BRIDGE_KUBECTL_MODE=local SSH_TARGET=local \
  scripts/faz22-remote-ops/faz22-6-completion-audit.sh
```

The local-kubectl mode is intended for execution on `staging-sw` or the
`[self-hosted, staging-sw, testai-deploy]` runner. The canonical workflow is
`.github/workflows/faz22-6-live-audit.yml`; it is read-only, uploads the audit
output, and fails if `REMOTE_BRIDGE_LIVE=pass mode=local-kubectl` is not
present. Because the gate repositories are public, the workflow uses the
short-lived read-only `github.token` rather than a long-lived repository secret.

The audit is intentionally conservative. It prints `F22_6_COMPLETION=blocked`
while `#548` lacks hardware-attestation acceptance or bounded risk acceptance,
while `#1580` lacks VIEW_ONLY acceptance, or when live broker/release evidence
is missing.

Use the release-lineage helper before any 5-device or broader rollout claim:

```bash
scripts/faz22-remote-ops/faz22-6-release-lineage-audit.sh
```

The expected current posture is `F22_6_RELEASE_LINEAGE=pass` for the
release-lineage sub-gate. The `v0.3.1` trusted EXE workflow published an
immutable rollout-candidate release with post-publish archive verification,
`workflow_run_id=28100776164`, `previous_release=v0.3.0`,
`EndpointAgent.zip` SHA256
`6791f6af5dbe0c4f2da8d87f33e5fa4165237d8b6a7aeb8121e29a88cbc5c2b7`, and
artifact-host image
`ghcr.io/halildeu/platform-agent-artifacts:v0.3.1@sha256:b83e39a0b08b54cd9e4dc094d8d36fb857b2cd253355ce5150aa33edb502eb27`.
Self-hosted audit run `28102175711` proved release/current manifest parity,
workflow/previous-release parity, ZIP SHA parity, live artifact-host digest
parity, `RELEASE_LINEAGE_WAIVER=not_required`, and
`F22_6_RELEASE_LINEAGE=pass`.

The dense `v0.2.x` pilot-recovery train and `v0.3.0` immutable=false release
object are historical evidence, not the current policy series. Broad rollout
language still requires all other Faz 22.6 gates to pass; this release-lineage
sub-gate does not substitute for `platform-backend#548` hardware-attestation
acceptance or `platform-k8s-gitops#1580` VIEW_ONLY live acceptance.

## 9. Closure Language

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
