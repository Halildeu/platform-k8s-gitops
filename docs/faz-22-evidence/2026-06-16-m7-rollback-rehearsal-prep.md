# Faz 22.5 M7 — Same-Day Rollback Rehearsal Prep Evidence

> **Date**: 2026-06-16
> **Issue**: #1379
> **Branch/worktree**: `codex/faz225-rollback-rehearsal-1379` /
> `.worktrees/faz225-rollback-rehearsal-1379`
> **Scope**: agent-doable prep for owner-approved 2-device rollback rehearsal.
> This is **not** full M7 closure.

## 1. Durable Fix Audit

The 2026-06-15/16 Windows pilot problems are now represented in persistent
source/runbook state rather than chat-only commands:

| Problem observed | Durable state |
|---|---|
| `install.ps1` / package friction on standard Windows PowerShell 5.1 | `docs/faz-22-software-deployment-plan.md` records platform-agent PR #102 as PS5.1-safe installer packaging with UTF-8 BOM handling. |
| Wrong/short AG-038 `configHash` and silent result-submit failures | `docs/faz-22-software-deployment-plan.md` records AG-038 full `configHash` and backend result-submit 4xx/5xx visibility as M0 hardening. |
| Temporary ZIP/manual token workflow was too fragile for 800 PCs | `docs/runbooks/RB-faz22-m1-artifact-host.md` and `docs/runbooks/RB-faz22.3-edge-mtls-autoenroll.md` document canonical `current` artifact host + one-command bootstrap shape. |
| mTLS DNS/edge path drift (`endpoint-agent-mtls...` vs `mtls.*`) | ADR-0029 and M2 runbooks now use `mtls.testai.acik.com` for test/pilot and `mtls.ai.acik.com` for prod. |
| Prod `mtls.ai.acik.com` needed ssl-passthrough activation | `docs/faz-22-evidence/2026-06-15-m2-prod-mtls-ai-activation.md` and current-state record PR #1593/#1594 evidence and ingress-nginx ssl-passthrough. |
| Rollback evidence collection was manual and scattered | This branch adds `scripts/faz22-mass-deployment/m7-rollback-rehearsal-collector.ps1` and runbook §0 same-day 2-device rehearsal lane. |

## 2. New Agent-Doable Artifact

`scripts/faz22-mass-deployment/m7-rollback-rehearsal-collector.ps1`

- PS5.1-compatible.
- Read-only evidence collector.
- Phases:
  - `baseline`
  - `rollback-clean`
  - `reinstall-continuity`
- Does not install, uninstall, decommission, reactivate, mutate GPO, read
  secrets, or submit data to backend.
- Writes JSON evidence to:

```text
C:\ProgramData\EndpointAgent\evidence\m7-rollback-rehearsal\*.json
```

## 3. Validation

```text
git diff --check
PowerShell parser OK:
[System.Management.Automation.Language.Parser]::ParseFile(
  "scripts/faz22-mass-deployment/m7-rollback-rehearsal-collector.ps1"
)
```

## 4. Runtime Attempt Boundary

Codex attempted to use the previously opened reverse-SSH path for live Windows
execution:

```text
ssh staging-sw / halil@10.9.10.53 -> connection refused or key rejected
localhost:22022 -> connection refused
localhost:22024 -> connection refused
```

Therefore this session could not execute the collector on Denetim PC or
ERP-MOBIL from the Codex host. This is not treated as a runtime pass.

## 5. Local-Control Runtime Rehearsal Evidence

After the reverse-SSH route became unavailable, Codex used the local Parallels
Windows 11 VM (`HALILKOOLUB735`) as the safe local-control device. This does
not replace domain-GPO evidence, but it proves the same-day rollback collector,
preserve-config uninstall path, HMAC-preserving reinstall path, and
post-reinstall service continuity on a real Windows endpoint.

| Phase | File | Overall | Fail | Warn | SHA256 |
|---|---|---:|---:|---:|---|
| baseline | `.runtime-evidence/HALILKOOLUB735/20260616-080748Z-HALILKOOLUB735-baseline.json` | PASS-WITH-WARN | 0 | 1 | `b65967ba520a68e1b498fea5e5ae96bb81eaaca5a5450750f37234ad351912f1` |
| rollback-clean | `.runtime-evidence/HALILKOOLUB735/20260616-082315Z-HALILKOOLUB735-rollback-clean.json` | PASS | 0 | 0 | `aaea53e3e694bebe8ac75e497f01ef1d4a9105a3531d00fc184ff7d55071529f` |
| reinstall-continuity | `.runtime-evidence/HALILKOOLUB735/20260616-082338Z-HALILKOOLUB735-reinstall-continuity.json` | PASS | 0 | 0 | `92cc24b1601023ef7caebdb0b9211ee1aff5fa4b89ac7031ded7f8a96f77f06e` |

Rehearsal runner:

```text
.runtime-evidence/HALILKOOLUB735/m7-local-w11-rehearsal-runner.ps1
SHA256: 54592185df930307588a361455a15e361c45f2c80665693eb2f893ab9d4da220
```

Local Windows step log:

```text
2026-06-16T11:23:12+03:00 PRE-STATE
2026-06-16T11:23:12+03:00 BEGIN UNINSTALL-PRESERVE-CONFIG-LOGS
2026-06-16T11:23:13+03:00 END UNINSTALL-PRESERVE-CONFIG-LOGS exit=0
2026-06-16T11:23:13+03:00 BEGIN COLLECT-ROLLBACK-CLEAN
2026-06-16T11:23:15+03:00 END COLLECT-ROLLBACK-CLEAN exit=0
2026-06-16T11:23:15+03:00 BEGIN INSTALL-CURRENT-PRESERVE-HMAC
2026-06-16T11:23:16+03:00 END INSTALL-CURRENT-PRESERVE-HMAC exit=0
2026-06-16T11:23:36+03:00 BEGIN COLLECT-REINSTALL-CONTINUITY
2026-06-16T11:23:38+03:00 END COLLECT-REINSTALL-CONTINUITY exit=0
2026-06-16T11:23:38+03:00 POST-STATE
2026-06-16T11:23:38+03:00 END M7 local-control rollback rehearsal
```

Post-state:

```text
EndpointAgent service: Running / Automatic
endpoint-agent version: v0.2.5
```

Important boundary:

- This proves local-control rollback/reinstall continuity.
- This does **not** prove domain-GPO propagation or the 2-device denominator.
- Therefore #1379 remains open until domain-GPO/selected-pilot evidence is
  attached or the acceptance boundary is explicitly narrowed by the owner.

## 6. Denetim PC Domain-GPO Baseline Evidence

After the reverse-SSH route recovered, Codex ran the collector on the selected
domain-joined Denetim PC (`SRB-AIDENETIMPC`) in non-destructive baseline mode.
This proves the domain-GPO baseline is healthy, but does not execute the
rollback-clean or reinstall-continuity phases on that device.

| Phase | File | Overall | Fail | Warn | SHA256 |
|---|---|---:|---:|---:|---|
| baseline | `.runtime-evidence/SRB-AIDENETIMPC/20260616-083459Z-SRB-A_DENET_MPC-baseline.json` | PASS | 0 | 0 | `d64a3c7bdef87ec082e2ccae687b3e344b74c1b274233539bd58d924e3aa21e7` |

Runtime facts:

```text
Computer: SRB-AIDENETIMPC
Domain: acik.local
EndpointAgent service: Running / Automatic
Machine cert: CN=SRB-AIDENETIMPC.acik.local
Issuer: CN=Acik-Endpoint-CA, DC=acik, DC=local
Cert thumbprint: 1687D3C41443239A12ECA973E6EED87B0876B068
Executable signature: Valid, signer D68F4F530137EB65CE44E3405E82B46205E753E5
Backend TCP: PASS mtls.testai.acik.com:443
```

Important boundary:

- This proves a selected domain-GPO device baseline is ready.
- This does **not** prove destructive rollback-clean/reinstall-continuity on
  Denetim PC.
- This does **not** prove backend enrollment revoke/decommission/reactivate.

## 7. Status

| Gate | Status |
|---|---|
| #1379 board status | Blocked/open; local-control drill + Denetim baseline evidence attached |
| M7 full closure | Not closed |
| Local-control rollback/reinstall drill | PASS on HALILKOOLUB735 |
| Domain-GPO baseline | PASS on SRB-AIDENETIMPC |
| Domain-GPO destructive rollback drill | Runtime evidence pending |
| 50-PC/M6 dependency | Still open under #1378 |

## 8. Next Runtime Command Shape

On a selected Windows device with the repo script available:

```powershell
.\m7-rollback-rehearsal-collector.ps1 -Phase baseline -DeviceRole domain-gpo -RequireMachineCert -Json
.\m7-rollback-rehearsal-collector.ps1 -Phase rollback-clean -DeviceRole domain-gpo -Json
.\m7-rollback-rehearsal-collector.ps1 -Phase reinstall-continuity -DeviceRole domain-gpo -RequireMachineCert -Json
```

Attach the three JSON files to #1379 before any `Needs Verify` or closure move.
