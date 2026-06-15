# Faz 22.5 M5 — 2-PC GPO Pilot Kickoff Boundary

> **Date**: 2026-06-15
> **Tracked by**: platform-k8s-gitops #1377
> **Scope**: historical 2-PC GPO pilot kickoff / matrix narrowing
> **Superseded by**: owner same-day no-24h selected-device direction recorded in `2026-06-15-m5-same-day-device-pool-amendment.md`
> **Closure claim**: NO
> **Runtime mutation from Codex host**: NONE

## 1. Owner Decision

Owner reaffirmed earlier on 2026-06-15 that the first M5 GPO pilot should use
**2 PCs**, not the original 5-PC design. This was later superseded the same day
by the owner-approved selected-device/no-24h scope. This file remains only as
read-only discovery evidence.

- original 2-PC candidate discovery;
- no runtime mutation from the Codex host;
- no GPO deployment claim.

## 2. Candidate Discovery From Codex Host

Read-only checks from the Codex host over the VPN/domain network:

```text
dig @10.9.10.10 ERP-MOBIL.acik.local A     -> 10.9.10.101
dig @10.9.10.10 HALILKOCOGLU.acik.local A  -> 10.9.2.151
dig @10.9.10.10 AGENTPC2.acik.local A      -> 10.9.2.228
dig @10.9.10.10 MKR-A1.acik.local A        -> 10.9.2.221
```

Port reachability:

| Host | IP | Reachable ports from Codex host | Pilot decision |
|---|---:|---|---|
| `ERP-MOBIL.acik.local` | `10.9.10.101` | 135, 139, 445, 3389, 443 | Candidate 1 |
| `HALILKOCOGLU.acik.local` | `10.9.2.151` | 135, 139, 445, 3389 | Candidate 2 |
| `AGENTPC2.acik.local` | `10.9.2.228` | DNS resolves, checked ports refused | Not selected for kickoff |
| `MKR-A1.acik.local` | `10.9.2.221` | DNS resolves, checked ports timed out/down | Not selected for kickoff |

## 3. 2-PC Matrix Draft

This is a kickoff matrix, not final acceptance. OS/build, hardware class, EDR
state and machine-cert proof must be filled from Windows/DC-side collectors.

| Field | PC-1 | PC-2 |
|---|---|---|
| Hostname | `ERP-MOBIL` | `HALILKOCOGLU` |
| FQDN | `ERP-MOBIL.acik.local` | `HALILKOCOGLU.acik.local` |
| IP | `10.9.10.101` | `10.9.2.151` |
| Network class | DC/server subnet | Corp/client subnet |
| OU / GPO target | `OU=EndpointTest,DC=acik,DC=local` observed earlier for ERP-MOBIL; final GPO OU proof pending | Pending |
| OS / build | Windows Server 2022 family observed earlier (`10.0.20348`) | Pending |
| Architecture | x64 expected; verify with collector | Pending |
| EDR | ESET services observed earlier on ERP-MOBIL | Pending |
| Enrollment state | Prior tokenless M2/service-continuity evidence exists | Pending |
| User-session smoke | Pending | Recommended here if this is a real user workstation |

High-signal diversity target:

- subnet differs (`10.9.10.x` vs `10.9.2.x`);
- device class likely differs (server/member host vs workstation);
- at least one user-session scenario should run on `HALILKOCOGLU`.

## 4. Execution Boundary

From the Codex host, RDP/SMB/RPC are visible but remote command execution is not
available:

- WinRM 5985/5986: not reachable;
- SSH 22: not reachable on `ERP-MOBIL`, not available on `HALILKOCOGLU`;
- RDP 3389: reachable, but not a programmable execution channel for this agent.
- Staging jump check from this Codex host also failed non-interactively:
  `ssh -o BatchMode=yes halil@10.9.10.53` returned
  `Permission denied (publickey,password)`, so the prior reverse-tunnel path
  was not usable by this session.

Therefore this file does not claim GPO deployment started. The live actions
must be run from a Windows/DC session with the existing domain admin access.

## 5. Next Evidence To Collect

For each selected device:

```powershell
# Before GPO/MSI push
.\wave-preflight.ps1 -Mode preinstall-readiness -Json `
  -ApiHost mtls.testai.acik.com -RequireMachineCert

# After GPO/MSI install + tokenless enroll
.\wave-preflight.ps1 -Mode enroll-health -Json `
  -ApiHost mtls.testai.acik.com `
  -RequireMachineCert -RequireSignature `
  -ExpectedSignerThumbprint D68F4F530137EB65CE44E3405E82B46205E753E5
```

M5 #1377 should remain `Needs Verify` until the current same-day selected-device
gate is evidenced:

- domain-gpo devices have GPO/MSI install evidence;
- domain-gpo devices have tokenless enrollment + heartbeat + inventory/result-submit;
- same-day T0/T+15/T+60 collector evidence is attached;
- one device completes rollback + reinstall drill.
