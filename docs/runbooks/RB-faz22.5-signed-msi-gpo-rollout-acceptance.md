# RB Faz 22.5 — Signed MSI / GPO Rollout Acceptance Gate

> **Status:** #1680 acceptance prep. This runbook is the canonical execution
> checklist for the managed-PC rollout gate. It does not satisfy #1680 by
> itself; #1680 reaches Done only after live managed Windows endpoint evidence
> is attached.
>
> **Tracked by:** platform-k8s-gitops#1680

## 1. Purpose

Faz 22.5 has proven the bounded product-channel path for #1601 and the
AgentPC2 tokenless mTLS path under #1643. The next rollout gate is different:
prove that managed Windows PCs can receive EndpointAgent through a controlled,
repeatable product deployment method without manual token paste, manual ZIP
copy, or ad-hoc reverse SSH/RDP evidence.

This runbook defines the acceptance contract for:

- signed MSI or explicitly approved bootstrap artifact selection;
- a single deployment method per acceptance run;
- constrained pilot targeting;
- per-device service, certificate, enrollment, restart, and rollback evidence;
- failed-device triage without silent success states.

## 2. Current Artifact Reality

As of 2026-06-19:

| Artifact lane | Current truth | Acceptance impact |
|---|---|---|
| Public current ZIP/bootstrap | `v0.2.10`, EXE SHA256 `a50344a4457959b95dfdfa22e6578e53cd6ec4b124830b506fe53503c18ba1ec`, ZIP SHA256 `fa72f278b81497bf2480ea312c7d13cff410372bfcef6ddca23dc3e50a1f292e`, public `testai.acik.com/artifacts/endpoint-agent/current/release-manifest.json` | Current runtime floor for endpoint-side acceptance. A pilot endpoint running below `0.2.10` cannot close the current rollout/runtime gate. |
| GitHub release `v0.2.10` | release has `EndpointAgent.zip`, `bootstrap-package.ps1`, `install.ps1`, `uninstall.ps1`, manifest, sums, and EXE. It does **not** currently contain a signed MSI asset. | Acceptable for owner-approved bootstrap/current-artifact pilot evidence only; not sufficient for signed MSI/GPO Software Installation proof. |
| Trusted MSI workflow / durable signed MSI | `EndpointAgent-0.2.9-signed.msi` remains the latest durable signed MSI asset: SHA256 `5cab18d460720e5bf89ddf0038f5b1c4d5ae04afc031dda0dc15d9810c969571`; `msi-build-manifest.json` SHA256 `a5949a093ce234eafdb88c759fd884bf32324c9a8172b455c0daa78c9dfe72d0`; `production=true`; `signing_tier=trusted-internal-ca`; `timestamped=true`; signer thumbprint `D68F4F530137EB65CE44E3405E82B46205E753E5`; root cert SHA256 `078494D03E2FB51EA35DB71FFC04B5C5230EE9F52E0D5A057B6F35B8F7E0B59E` | This proves the signed-MSI lane exists, but it is now below the current `v0.2.10` artifact floor. It must not be used to claim current #1680 acceptance unless the issue records an explicit temporary version-floor exception; that exception still does not close #208 terminal/runtime acceptance. |

**Version-floor rule:** every post-install / enroll-health evidence run must
include `-ExpectedMinimumAgentVersion "0.2.10"` while `current/` serves
`v0.2.10`. If a signed MSI lower than that is deployed, the collector must
return `FAIL` and the rollout is a downgrade/regression lab, not #1680
acceptance.

**Deployment method for the next live pilot:** use `gpo-msi` unless the owner
explicitly chooses the bootstrap fallback in the issue comment. Record exactly
one deployment method in the evidence packet:

1. `gpo-msi`: GPO Software Installation or startup-script `msiexec` using a
   durable signed MSI URL/share path and SHA256. The installed endpoint must
   still satisfy the current version floor.
2. `one-command-bootstrap`: current ZIP/bootstrap URL and SHA256, executed by
   GPO startup script or an operator-approved command channel.

Do not mix methods in the same acceptance run.

## 3. Hard Boundaries

- No raw enrollment token, JWT, private key, password, or bearer value is pasted
  into issue comments, PRs, logs, or evidence artifacts.
- Reverse SSH, RDP clipboard output, inbound SSH/WinRM/SMB/RPC, and manually
  copied ZIP/MSI files are lab transport only. They can help collect evidence,
  but they do not prove rollout acceptance.
- A single PC smoke does not prove #1680. Minimum acceptance is two managed
  pilot PCs through the same selected deployment method.
- `source-ready != deployed != accepted`: release, workflow, or PR evidence
  cannot replace endpoint-side install, service, mTLS, and rollback evidence.
- `signed != current`: a valid older signed MSI does not satisfy the gate when
  the public current artifact has advanced. The evidence collector must fail
  versions below the current floor.
- The 5-PC/50-PC/800-PC gates stay closed until #1680 is accepted.

## 4. Pilot Targeting

The pilot scope must be recorded before execution:

| Field | Required value |
|---|---|
| Pilot OU | Example: `OU=EndpointTest,DC=acik,DC=local` |
| Security group | Example: `EndpointAgentPilotComputers` |
| Target computers | Two named computers; no wildcard domain targeting |
| GPO name | Dedicated EndpointAgent pilot GPO; no reuse of broad production GPO |
| GPO link | Pilot OU only |
| Security filtering | Pilot computer group only |
| WMI filter | Optional; if used, record filter text |
| Rollback mechanism | GPO unlink/security-filter removal and MSI uninstall/repair path |

## 5. Acceptance Checklist

For #1680 to move out of `Blocked` and toward `Done`, all items below need
evidence.

### M1 Artifact Selection

- Record method: `gpo-msi` or `one-command-bootstrap`.
- Record version, URL/share path, SHA256, source run/release, and signer/trust
  facts if MSI.
- Verify artifact hash before install on each pilot PC.
- Record the current version floor from `current/release-manifest.json`. The
  installed version on each device must be greater than or equal to that floor,
  unless #1680 explicitly records a temporary downgrade exception.

### M2 Deployment Method

- Use one method for both devices.
- If `gpo-msi`, record exact `msiexec` command or GPO Software Installation
  configuration.
- If `one-command-bootstrap`, record exact PowerShell command and expected
  ZIP/bootstrap SHA256.

### M3 Targeting Guard

- Record OU, group, GPO link, security filtering, and expected member list.
- Prove no domain-wide link or broad `Authenticated Users` apply path is used
  for install rollout.

### M4 Two-Device Install / Upgrade

On each selected PC:

- install or upgrade happens through the selected deployment method;
- no manual token/ZIP step is used;
- `EndpointAgent` service exists after policy/application;
- binary hash and version are recorded;
- installed version satisfies `-ExpectedMinimumAgentVersion` for the current
  artifact floor.

### M5 Service Continuity

On each PC:

- service state `Running`;
- start mode `Auto`;
- start account `LocalSystem`;
- forced restart returns `Running`;
- only expected service process remains.

### M6 mTLS / Tokenless Enrollment

On each PC:

- AD CS client-auth cert or auto-enroll identity is present;
- cert has private key and expected Client Authentication EKU;
- agent logs show auto-enroll/credential/heartbeat/poll without raw secrets;
- backend side shows heartbeat/poll or an accepted product-channel equivalent.

### M7 Rollback Drill

On at least one PC:

- remove GPO link/filter or run approved MSI uninstall/repair/reinstall path;
- verify service/env/log cleanup behavior;
- reinstall or reapply policy returns to healthy state.

### M8 Failed-Device Triage

- Define where failed installs appear: issue comment, dashboard, backend status,
  or help-desk queue.
- A device that fails install/enrollment must not remain silent or appear as
  delivered/successful.

## 6. Evidence Collection

Use:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\collect-endpoint-agent-rollout-evidence.ps1 `
  -ExpectedApiHost "mtls.testai.acik.com" `
  -ExpectedZipSha256 "fa72f278b81497bf2480ea312c7d13cff410372bfcef6ddca23dc3e50a1f292e" `
  -ExpectedMinimumAgentVersion "0.2.10" `
  -RestartService `
  -IncludeGpResultHtml
```

For GPO/MSI health checks, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\wave-preflight.ps1 `
  -Mode enroll-health `
  -ApiHost "mtls.testai.acik.com" `
  -RequireMachineCert `
  -RequireSignature `
  -ExpectedSignerThumbprint "D68F4F530137EB65CE44E3405E82B46205E753E5" `
  -ExpectedMinimumAgentVersion "0.2.10" `
  -ExitCodeOnFail `
  -Json
```

The script writes redacted JSON/text artifacts under:

```text
C:\ProgramData\EndpointAgent\rollout-evidence
```

Attach only redacted summaries or file hashes to GitHub. Do not paste secret
values or raw private material.

## 7. Issue Evidence Template

```markdown
EVIDENCE #1680 rollout acceptance <timestamp>

Method: gpo-msi | one-command-bootstrap
Artifact:
- version:
- current version floor:
- URL/share path:
- SHA256:
- signer/trust facts:

Targeting:
- OU:
- security group:
- GPO:
- WMI filter:
- expected computers:

Devices:
| Device | Method applied | Service | Restart | Cert/mTLS | Backend poll/heartbeat | Rollback |
|---|---|---|---|---|---|---|
| <PC1> | PASS/FAIL | PASS/FAIL | PASS/FAIL | PASS/FAIL | PASS/FAIL | N/A/PASS |
| <PC2> | PASS/FAIL | PASS/FAIL | PASS/FAIL | PASS/FAIL | PASS/FAIL | PASS/FAIL |

Failures:
- <none or failed-device queue link>

Non-claims:
- Does not prove 50-PC/800-PC rollout.
- Does not prove production remote support.
- Does not expose raw secrets.
```

## 8. Rollback Commands

MSI uninstall example, if `gpo-msi` selected and ProductCode is known:

```powershell
msiexec.exe /x "{PRODUCT-CODE-GUID}" /qn /norestart /l*v C:\ProgramData\EndpointAgent\rollout-evidence\msi-uninstall.log
```

Service cleanup verification:

```powershell
Get-CimInstance Win32_Service |
  Where-Object { $_.Name -eq "EndpointAgent" } |
  Select-Object Name, State, StartMode, StartName, PathName |
  Format-List
```

GPO rollback:

- unlink or disable the pilot GPO;
- remove pilot computer from the pilot security group, if security filtering is
  used;
- run `gpupdate /force`;
- verify service uninstall/disable behavior according to the selected method.

## 9. Current Blocker Statement

#1680 remains blocked until a live acceptance run supplies:

- durable selected artifact evidence;
- two managed endpoint install/upgrade artifacts;
- restart + mTLS/tokenless evidence per device;
- rollback drill evidence on one device;
- failed-device triage proof.

Agent-side preparation can continue without moving the Project status out of
`Blocked`; live pilot execution changes status only when the required managed
PC evidence exists.
