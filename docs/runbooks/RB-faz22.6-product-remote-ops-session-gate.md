# RB — Faz 22.6 Product Remote-Ops Session Gate

> **Status**: ACTIVE acceptance contract for `platform-backend#510` and
> `platform-k8s-gitops#1601`.
> **First target**: Denetim PC / `SRB-AIDENETIMPC`.
> **Current evidence anchor**: `rb-denetim-20260617T191335Z`.
>
> This runbook defines what can be counted as product remote-ops evidence. It
> does not by itself move #510 or #1601 out of `Needs Verify`.

## 1. Gate Decision

The product remote-ops gate is accepted only through the real product channel:

- EndpointAgent initiates an outbound mTLS remote-bridge session.
- Operator opens the session through the backend product API.
- A distinct approver approves the request.
- Step-up verification succeeds before operation transport.
- The broker sends a short-lived signed permit.
- The endpoint executes only the typed read-only pilot operation:
  `PTY_COMMAND hostname` under `CONSTRAINED_PTY`.
- Product audit/recording evidence is attached to the relevant issues.

The following never count as this gate:

- RDP clipboard or manually pasted PowerShell.
- Temporary reverse SSH or direct SSH into the endpoint.
- Inbound WinRM, SMB, RPC, RDP, SSH, or any endpoint port opening.
- Raw shell, PowerShell, `cmd /c`, encoded command, arbitrary path execution,
  file browser, or path enumeration.
- Token paste or any secret-bearing command payload.

## 2. Checklist-Hardening Rule

Before a live product session is used as evidence, #510 must contain a revised
checklist that explicitly separates:

1. product-channel happy path,
2. typed read-only operation constraint,
3. approval/authz evidence,
4. audit/recording evidence,
5. negative tests,
6. explicit non-acceptance for lab bridges and inbound admin channels,
7. remaining gates that cannot be satisfied by the Denetim PC run.

If this runbook and the issue body disagree, the stricter requirement wins until
the drift is reconciled in both places.

## 3. Required Evidence Classes

| Gate | Required evidence | Denetim `20260617T191335Z` status |
|---|---|---|
| G1 target | `SRB-AIDENETIMPC` selected; device id recorded | Proven |
| G2 topology | EndpointAgent outbound mTLS product path; no reverse SSH/RDP evidence | Proven for Denetim product run |
| G3 runtime artifact | broker deployment imageID digest and live config captured | Proven via #1666 evidence |
| G4 authz/approval | operator open + distinct approval + step-up challenge/verify | Proven |
| G5 typed operation | `PTY_COMMAND hostname` / `CONSTRAINED_PTY`; no raw shell | Proven for positive operation |
| G6 transport | operation response `PERMIT` and `transportPushed=true` | Proven |
| G7 audit/recording | approval/grant plus WORM/audit rows attached | Partially proven; row type must be stated exactly per run |
| G8 negative non-pilot | non-pilot capability such as `FULL_RDP` rejected | Proven (`400`) |
| G9 negative auth | no-auth or missing-role request rejected | Proven by earlier same-day negative comments; attach when claiming |
| G10 raw-shell negative | PowerShell / `cmd /c` shaped request rejected | Proven by earlier same-day negative comments; attach when claiming |
| G11 mTLS negative | no-cert and wrong-CA fail closed on real RPC | Proven by earlier same-day gRPC negative comments; attach when claiming |
| G12 session controls | expiry/replay/wrong-device/heartbeat/revoke/audit-down/skew | Not fully live-proven |

The Denetim run can be used for a bounded MVP gate only. It must not be used to
claim AgentPC2 acceptance, signed MSI/GPO readiness, 5-PC/50-PC/800-PC rollout,
or prod remote-support readiness.

## 4. Evidence Template

Use this format when commenting on #510 and #1601:

```text
EVIDENCE product-remote-ops-session-gate <timestamp>

Target:
- device:
- deviceId:
- environment:
- topology:

Runtime:
- broker deployment:
- broker imageID:
- live config:
- endpoint log cross-check:

Product path:
- session:
- open:
- approve:
- challenge:
- verify:
- operation:
- operation response:

Approval/audit:
- requester:
- approver:
- approval decision:
- grant:
- recording/audit rows:
- evidence hashes:

Negative tests:
- non-pilot capability:
- no-auth/missing-role:
- raw-shell:
- no-client-cert:
- wrong-CA:
- remaining negatives:

Does not prove:
- AgentPC2 product-channel acceptance
- signed MSI/GPO rollout acceptance
- 5-PC/50-PC/800-PC rollout readiness
- prod remote-support readiness
- reverse SSH/RDP/manual bridge acceptance
```

## 5. Current Denetim Evidence Mapping

The current accepted Denetim product session evidence is:

- Evidence directory:
  `/home/halil/codex-rb-smoke/20260617T191335Z-product`
- Session: `rb-denetim-20260617T191335Z`
- Operation: `op-hostname-20260617T191335Z`
- Device: `423b6fc3-7497-4083-bd2f-5e2fe543bfe9`
- HTTP statuses: `open=200`, `negative-nonpilot=400`, `approve=200`,
  `challenge=200`, `verify=200`, `operation=200`
- Operation response: `PERMIT`, `transportPushed=true`
- `summary.json` SHA256:
  `433e1273e13b1dafb24160948447abb490c87fd1db1c29ef642df0f7f52320f0`
- Endpoint log cross-check: Denetim agent log at `2026-06-17 19:13:37`
  shows pilot auto-consent and constrained-PTY enabled over outbound mTLS.

Known limitation for this specific evidence bundle: the recording row observed
for the `20260617T191335Z-product` package was `POLICY_EVENT`; do not claim
`AGENT_OUTPUT` for that run unless a row for the same session is inspected and
attached.

## 6. Status Rules

- Keep #510 and #1601 in `Needs Verify` while any parent gate remains outside
  the accepted Denetim MVP evidence.
- Keep AgentPC2 in its own gate (#1643) until AgentPC2 itself has product-channel
  evidence. Lab reverse SSH/RDP or inbound admin reachability does not unblock it.
- Track backend lifecycle hardening separately in `platform-backend#690`:
  DENY/terminal outcomes should terminalize or evict live sessions and leave
  audited state.
- Desired-state cleanup such as ESO/Vault reconciliation is separate from the
  positive product session. Do not call the overlay clean while ExternalSecrets
  remain `SecretSyncedError`.

## 7. Minimal Re-Verification Before Reuse

Before reusing this gate for another device or another session:

1. Verify broker imageID and live config again.
2. Verify endpoint log proves outbound mTLS remote-bridge connection.
3. Run the product path again; do not reuse stale session IDs as fresh evidence.
4. Attach positive, negative, audit, and "does not prove" sections to both
   #510 and #1601 or the device-specific gate issue.
5. State any missing negative matrix item explicitly instead of marking it done.
