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

## 5. Status

| Gate | Status |
|---|---|
| #1379 board status | In Progress for bounded rehearsal prep |
| M7 full closure | Not closed |
| Full destructive rollback drill | Runtime evidence pending |
| 50-PC/M6 dependency | Still open under #1378 |

## 6. Next Runtime Command Shape

On a selected Windows device with the repo script available:

```powershell
.\m7-rollback-rehearsal-collector.ps1 -Phase baseline -DeviceRole domain-gpo -RequireMachineCert -Json
.\m7-rollback-rehearsal-collector.ps1 -Phase rollback-clean -DeviceRole domain-gpo -Json
.\m7-rollback-rehearsal-collector.ps1 -Phase reinstall-continuity -DeviceRole domain-gpo -RequireMachineCert -Json
```

Attach the three JSON files to #1379 before any `Needs Verify` or closure move.
