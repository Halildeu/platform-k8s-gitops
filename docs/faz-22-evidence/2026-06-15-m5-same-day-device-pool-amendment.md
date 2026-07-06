# Faz 22.5 M5 — Same-Day Device Pool Amendment

> **Date**: 2026-06-15
> **Tracked by**: platform-k8s-gitops #1377
> **Scope**: owner-approved same-day M5 pilot scope
> **Closure claim**: NO
> **Runtime mutation from Codex host**: NONE

## 1. Owner Decision

Owner approved the following device pool for the M5 first pilot and explicitly
removed the 24h wait:

| Device | Role | Counts for GPO/tokenless denominator? | Notes |
|---|---|---:|---|
| `AGENTPC1` | `domain-gpo` | Yes, if domain-joined and GPO-scoped | Preferred primary GPO pilot device |
| `AGENTPC2` | `domain-gpo` | Yes, if domain-joined and GPO-scoped | Prior 9-hour install discovery is historical; retest as same-day GPO path |
| Local Parallels Windows | `local-control` | No, unless domain-joined and GPO-scoped | Installer/agent regression control and fast rollback/reinstall smoke |
| Denetim PC | `audit` | Yes, if domain-joined and GPO-scoped | Audit/user-session evidence device |

This supersedes the earlier 2-PC/24h kickoff wording. The original 5-PC/7d and
the intermediate 2-PC/24h paths remain reference/history only.

## 2. Current Acceptance Boundary

M5 #1377 remains `Needs Verify` until all applicable same-day evidence is
attached:

- selected device matrix with role, denominator, hostname, OU/security group,
  OS/build, arch, hardware class, EDR state and network class;
- domain-gpo devices prove tokenless enroll, heartbeat, inventory and
  result-submit without manual token/ZIP;
- T0/T+15/T+60 collector JSON from
  `scripts/faz22-mass-deployment/m5-same-day-pilot-collector.ps1`;
- `wave-preflight.ps1` preinstall and enroll-health outputs for domain-gpo
  devices;
- one-device rollback + reinstall drill evidence;
- post-pilot artifact states `same_day_smoke=true`, `soak_hours=0`,
  denominator, success/failure count, rollback readiness and M6 risk note.

## 3. No-24h Risk Note

Skipping 24h soak is an owner-approved speed decision for this first pilot. It
does not prove long-running stability. M6/50-PC ramp must either:

1. carry an explicit no-24h risk acceptance note, or
2. add a later stabilization evidence gate before expansion.

## 4. Agent-Doable Support

Added read-only evidence collector:

```text
scripts/faz22-mass-deployment/m5-same-day-pilot-collector.ps1
```

The collector does not install, uninstall, enroll, mutate GPO, read secrets, or
submit backend data. It only writes local JSON evidence under:

```text
C:\ProgramData\EndpointAgent\evidence\m5-same-day\
```
