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
| Denetim PC | `audit` / `domain-gpo` if pilot-scoped | Yes, if domain-joined and GPO-scoped | Minimum current first-run device; audit/user-session evidence and first domain-gpo denominator member if scoped |
| Local Parallels Windows | `local-control` | No, unless domain-joined and GPO-scoped | Minimum current first-run device; installer/agent regression control and rollback/reinstall smoke |
| `AGENTPC1` | `domain-gpo` | Yes, if domain-joined and GPO-scoped | Optional expansion / fallback primary GPO pilot device |
| `AGENTPC2` | `domain-gpo` | Yes, if domain-joined and GPO-scoped | Optional expansion / fallback; prior 9-hour install discovery is historical and must be retested if used |

This supersedes the earlier 2-PC/24h kickoff wording. The original 5-PC/7d and
the intermediate 2-PC/24h paths remain reference/history only.

## 1.1 Current Minimum Rule — Denetim PC + Local Parallels

Owner follow-up on 2026-06-15 sets the immediate first-run minimum to:

```text
Denetim PC + local Parallels Windows
```

This is acceptable as a two-device same-day smoke set with strict denominator
accounting:

- Denetim PC counts toward the GPO/tokenless denominator only if it is
  domain-joined and pilot GPO-scoped.
- Local Parallels Windows remains `local-control` and outside the GPO/tokenless
  denominator unless it is domain-joined and pilot GPO-scoped.
- A result with Denetim PC + local Parallels satisfies the two-device smoke
  shape, but it must not be reported as a 2/2 domain-gpo success unless both
  devices are domain-joined and pilot GPO-scoped.

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
  `selected_device_count`, `domain_gpo_denominator`, `local_control_count`,
  success/failure count, rollback readiness and M6 risk note.

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
