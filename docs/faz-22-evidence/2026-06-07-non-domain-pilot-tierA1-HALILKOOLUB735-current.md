# Faz 22.2.A non-domain pilot — Tier A1, Device HALILKOOLUB735

> **Status**: PARTIAL
> **Tracked by**: #1044
> **Tier**: A1
> **Operator**: local-operator
> **DPO sign-off** (A2 only): N/A for A1
> **Codex thread**: PENDING
> **Generated at**: 2026-06-07T06:06:32Z
> **Source diagnostics**: `/tmp/faz22-a1-local-vm-diagnostics-20260607T060330Z/Windows_11/read-only-diagnostics.txt`

## 1. Identity classification

| Field | Value | Source | Redaction |
|---|---|---|---|
| Hostname | HALILKOOLUB735 | `diagnose identity` / Win32_ComputerSystem | none |
| PartOfDomain | false | `diagnose identity` / Win32_ComputerSystem | none |
| Domain/Workgroup | WORKGROUP / WORKGROUP | `diagnose identity` | none |
| AzureAdJoined | NO | `diagnose identity` / dsregcmd | none |
| WorkplaceJoined | NO | `diagnose identity` / dsregcmd | none |
| Tenant ID | N/A | A1 local/workgroup device | not captured |
| Logged-in identity | hash/mask only | `diagnose identity` | UPN/full SID not captured |
| Agent identity class | LOCAL | agent identity classifier | none |
| Detected tier | A1 | runbook taxonomy mapping | none |

## 2. Build provenance

- platform-agent commit: PENDING
- endpoint-agent.exe SHA256: PENDING
- Agent version: endpoint-agent 0.1.3-lab.1
- EndpointAgent service: Running / Automatic
- Authenticode signed?: no — A1 lab exception unless signed evidence is provided
- install method: A1 lab install

## 3. Install / Enroll / Heartbeat

- install timestamp: PENDING
- enrollment token mint timestamp: PENDING
- device ID (backend): d0efb00a-681a-4e32-b7de-a27ef94f2977
- enroll timestamp: PENDING
- heartbeat interval (configured): 30s unless device config evidence says otherwise
- heartbeat 24h count: PENDING — fill from `a1-soak-rollup.sh` after the soak window
- heartbeat 24h max gap: PENDING — fill from `a1-soak-rollup.sh` after the soak window

## 4. Read-only local diagnostics

| Check | Value | Evidence |
|---|---|---|
| Backend reachability | true | `testai.acik.com:443` |
| WinGet ready | yes | version `1.28.240` |
| WinGet egress package | yes | package `7zip.7zip`; `PENDING` means probe skipped |
| Software inventory app count | 17 | `diagnose software` |
| Hardware OS | Microsoft Windows 11 Pro for Workstations / ARM 64-bit Processor | `diagnose hardware` |
| EndpointAgent service probe | RUNNING / AUTO_DELAYED | `diagnose services` |
| Local users observed | 5 | usernames redacted/hash-only evidence |

## 5. Smoke (non-destructive)

| Command | ID | Status | Duration | Audit row |
|---|---|---|---|---|
| COLLECT_INVENTORY | PENDING | PENDING | PENDING | PENDING |
| inventory_refresh (optional) | N/A | N/A | N/A | N/A |

This generator does not dispatch commands. Fill this section from the planned non-destructive backend command smoke.

## 6. Soak observation (24-72h)

| Metric | Value | Acceptance |
|---|---|---|
| Heartbeat success rate | PENDING | per-device explicit count §11.2 |
| Unexplained offline > 30m | PENDING | 0 required |
| Command timeout | PENDING | 0 unhandled |
| Service crash/uninstall/tamper | PENDING | 0 unexplained |

Fill this section from `scripts/faz22-non-domain/a1-soak-rollup.sh` after the evidence window. Do not infer PASS from local diagnostics alone.

## 7. KVKK / consent (A2 BYOD only)

- Consent ID: N/A for A1
- Consent timestamp: N/A for A1
- Data inventory ref: N/A for A1
- Retention policy enforced (BE-019): N/A for A1
- Uninstall self-service tested: N/A for A1

## 8. EDR allowlist (A2/A3/A4 only)

- SOC ticket: N/A for A1
- Agent SHA256 allowlisted: N/A for A1 lab exception unless operator policy requires it
- Service display name allowlisted: EndpointAgent
- Install path allowlisted: `C:\Program Files\EndpointAgent`

## 9. Cleanup / rollback

- Uninstall timestamp: PENDING / N/A during soak
- Install dir removed: PENDING / N/A during soak
- Log dir removed: PENDING / N/A during soak
- Backend device disabled: PENDING / N/A during soak

## 10. Boundary

- This evidence draft is per-device only.
- It does **not** complete #1044 by itself.
- #1044 still requires the remaining devices, planned non-destructive command facts, 24h soak facts, and pilot-wide rollup evidence.
- No destructive command, password reset, local password change, domain join, SMB/file action, or account mutation is represented by this draft.
