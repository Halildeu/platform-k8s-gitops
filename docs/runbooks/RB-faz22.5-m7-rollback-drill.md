# RB Faz 22.5 M7 — Rollback Drill: MSI Uninstall + Enrollment Revoke + GPO Rollback

> **Status**: SOURCE DRAFT (DESTRUCTIVE PLAN ONLY) — **HARDENED 2026-06-13**: §4.1/§4.2 verified against live backend/agent source (real `decommission`/`reactivate` + `EndpointDeviceWriteGuard` 409; correct `EndpointAgent`/`endpoint-agent.exe` names; removed the unverified `/revoke` placeholder endpoint). Companion read-only check: `scripts/faz22-mass-deployment/wave-preflight.ps1 -Mode rollback-clean`. Cross-AI: Claude (impl) ≠ Codex (review), thread `019ebf9b`.
> **Runtime mutation**: NONE in this PR (draft only)
> **Destructive execution**: FORBIDDEN until lab-clone operator AGREE + board/Mavis evidence
> **Codex plan-time AGREE required**: ✅ thread `019ea922` AGREE source-side draft scope (M7 destructive boundary)
> **Operator gate**: REQUIRED (lab-clone environment + domain admin + IT lab pilot environment + Mavis ops coordination + destructive action checklist)
> **Closure claim**: NO (source-side draft; M7 acceptance evidence operator collects from lab-clone drill)
> **Tracked by**: [#1379](https://github.com/Halildeu/platform-k8s-gitops/issues/1379) Faz 22.5 M7 — Rollback drill: MSI uninstall + enrollment revoke + GPO rollback
> **Evidence template**: §7 evidence pack layout
> **Prerequisite**: M5 #1377 + M6 #1378 closure + Mavis ops sign-off + IT lab-clone environment

---

## 0. Same-Day 2-Device Rehearsal Lane (Owner-Approved, Not Closure)

Owner may open a bounded same-day rehearsal before the full M6/M7 sequence when
the goal is to reduce rollout risk without claiming M7 closure. This lane was
added after the 2026-06-15/16 Windows pilot work showed that manual evidence
collection, remote access drift, DNS/artifact drift and reinstall continuity
must be captured as a repeatable artifact instead of chat-only commands.

**Allowed devices**: owner-selected pilot/control devices such as Denetim PC,
ERP-MOBIL, AGENTPC1/AGENTPC2, or local Parallels Windows.

**Allowed evidence phases**:

```powershell
# Before rollback/uninstall
.\m7-rollback-rehearsal-collector.ps1 -Phase baseline -DeviceRole domain-gpo -RequireMachineCert -Json

# After uninstall or GPO scope-removal
.\m7-rollback-rehearsal-collector.ps1 -Phase rollback-clean -DeviceRole domain-gpo -Json

# After reinstall / scope-restore
.\m7-rollback-rehearsal-collector.ps1 -Phase reinstall-continuity -DeviceRole domain-gpo -RequireMachineCert -Json
```

**Rules**:

- This lane may move #1379 to `In Progress` only when the owner explicitly opens
  the same-day rehearsal window in the issue/chat and the issue comment records
  the selected devices.
- This lane may attach evidence to #1379, but it **MUST NOT** close #1379 and
  **MUST NOT** move it to `Done`.
- This lane proves only selected-device rollback hygiene. It does not prove the
  50-PC capacity baseline, 800-PC rollout, full lab-clone GPO rollback, or final
  help-desk/IT sign-off.
- Destructive actions still follow the hard order below. The collector is
  read-only; it does not install, uninstall, decommission, reactivate, mutate GPO
  or read secrets.
- If remote access fails, the failure is evidence: record the SSH/tunnel/DNS
  class and keep runtime acceptance open instead of substituting source proof.

**Output location on Windows devices**:

```text
C:\ProgramData\EndpointAgent\evidence\m7-rollback-rehearsal\*.json
```

The JSON schema is `faz22.m7.rollback-rehearsal.collector.v1` and includes:
service/binary state, service environment key presence, machine ClientAuth cert,
backend TCP reachability, GPRESULT summary, recent installer/EndpointAgent
events, and redacted EndpointAgent log tail.

## 1. Scope

**M7** = 3-layer rollback drill (post M5 + M6 closure). Hedef: lab-clone environment ile destructive rollback path validate — (a) MSI uninstall agent-side, (b) enrollment revoke backend-side, (c) GPO rollback DC-side.

**Source-side scope (this runbook)**:
- Lab-clone rollback rehearsal pattern (env setup + 5-PC clone)
- Device decommission/reactivate proof contract (decommission endpoint + cascade counts + hash-chain audit row + 409-on-revoked)
- Rollback runbook (exact abort/restore checklist + chronological order)
- Mavis/board coordination format (destructive action approval chain)
- 3-layer drill scenario design

**Out-of-scope** (operator-bound):
- Lab-clone environment provision (5-PC clone of M5 pilot post-soak)
- Domain admin GPO rollback authority
- Mavis ops coordination + destructive action approval
- Physical drill execution
- Rollback decision tree owner-signed
- AG-028 testai uninstall LIVE proof (already 2026-06-04 SOURCE)

## 2. Hard Constraints / Non-Goals

- **No M7 drill execution before M5 + M6 closure** — destructive prerequisite
- **No production drill** — lab-clone ONLY (production rollback = ADR-0029 separate incident response)
- **No domain admin authority shortcut** — proper GPO change request + approval chain
- **No silent rollback** — every layer logged + audit row + Mavis notification
- **No incomplete drill** — 3 layers (uninstall + revoke + GPO) all PASS or DRILL FAIL
- **No destructive checklist bypass** — sequential layer execution (uninstall → revoke → GPO rollback)
- **Codex plan-time AGREE required per destructive scope edit** (this runbook SOURCE DRAFT scope AGREE thread `019ea922`; runtime drill execution needs separate plan-time consult per scope)

## 3. Lab-Clone Environment Setup

### 3.1 5-PC Lab Clone Pattern

```
Source: M5 5-PC pilot post-soak (#1377 closed)
Target: Lab clone environment (parallels VMs OR physical lab PCs)

Cloning steps (operator):
  1. Take VM snapshot or disk image of each M5 PC post-soak state
  2. Restore to lab-clone PC (offline from corp domain)
  3. Verify agent service status + heartbeat capability (offline)
  4. Apply lab AD (separate forest, mirror OU structure)
  5. Domain-join lab-clone PCs to lab AD
  6. Sync GPO from production OU to lab pilot OU (export/import)
  7. Verify GPO Software Installation MSI present in lab OU
  8. Verify code-signing chain intact (lab CA mirrored from prod M2 AD CS)
```

### 3.2 Lab Backend Mock

```
Lab backend endpoint-admin-service:
  - Separate cluster (k3d-lab or staging)
  - PG DB cloned from prod baseline (post-M6 50-PC enrollment)
  - 50 enrolled devices present (credentials + device rows; status ONLINE/OFFLINE)
  - Heartbeat data baseline ready
```

## 4. 3-Layer Drill Scenarios

### 4.1 Layer 1 — MSI Uninstall (agent-side)

```
Scenario: Agent self-update fails → operator manually uninstalls agent

Drill steps:
  1. Choose 1 lab-clone PC (e.g., pilot-pc-01-lab)
  2. Operator opens GPO management → Move pilot-pc-01-lab to non-pilot OU
  3. GPO refresh: gpupdate /force /target:computer
  4. Wait for next computer policy cycle (≤120 min OR force refresh)
  5. GPO Software Installation triggers uninstall ONLY IF the package option
     "Uninstall this application when it falls out of the scope of management"
     is set; otherwise the package stays and a manual uninstall (msiexec /x) is
     required -- record which path applied.
  6. Verify agent service stopped + binary removed
  
Expected evidence (verify with: wave-preflight.ps1 -Mode rollback-clean -Json):
  - Event 102 ApplicationInstaller "Removal Successful"
  - Get-Service EndpointAgent → service absent (not installed)
  - Test-Path "%ProgramFiles%\EndpointAgent\endpoint-agent.exe" → False
  - HKLM\SYSTEM\CurrentControlSet\Services\EndpointAgent\Environment regkey CLEARED (uninstall.ps1)
  - %ProgramData%\EndpointAgent\logs → PRESERVED (evidence retention)
  - %ProgramData%\EndpointAgent\config\hmac-credential.dpapi → PRESERVED unless -RemoveConfig/PURGE_CONFIG=1

Acceptance:
  - Uninstall completed within 120 min
  - Agent process not running (uninstall.ps1 Wait-AgentProcessExit; locked-binary guard)
  - No leftover scheduled tasks
  - Service Environment regkey cleared (stale-mode guard, #108/#109 class)
  - NOTE: HKLM\SOFTWARE\EndpointAgent (Mode/ApiUrl) is NOT removed by default uninstall
    (reinstall overwrites it; only -RemoveConfig purges Machine env + HMAC blob)
  - NOTE: service/binary names are EndpointAgent / endpoint-agent.exe (NOT PlatformAgent)
```

### 4.2 Layer 2 — Enrollment Revoke (backend-side)

```
Scenario: Compromised/retired agent -> revoke so it cannot receive commands until re-enrolled

Mekanizma (VERIFIED 2026-06-13 against EndpointDeviceLifecycleService + EndpointDeviceWriteGuard,
Codex 019ea789): enrollment revoke = device DECOMMISSION (KVKK reversible deactivate-not-delete).
Cascade cancels pending commands / maintenance-tokens / open uninstall-requests. The
"decommissioned device cannot act OR revive itself" invariant is enforced by the write guard.
NOTE: there is NO `POST /api/v1/endpoint-admin/enrollments/{id}/revoke` endpoint -- that was an
unverified draft placeholder. The real, verified surface is decommission/reactivate below.

Drill steps:
  1. Identify deviceId from grid:
     GET /api/v1/endpoint-admin/endpoint-devices   (public; gateway rewrites -> /api/v1/admin/...)
  2. Operator (MANAGER JWT) decommission:
     POST /api/v1/endpoint-admin/endpoint-devices/{deviceId}/decommission
     Body: {"reason": "M7 drill: rollback revoke verify"}
  3. Device status -> DECOMMISSIONED; cascade cancels pending commands/tokens/uninstalls
  4. Hash-chained audit row ENDPOINT_DEVICE_DECOMMISSIONED (lifecycle audit who/when/why + cascade counts)
  5. Verify revoked device cannot get NEW operations; then reactivate to restore.

Expected evidence:
  - decommission 200 -> status DECOMMISSIONED (409 if already decommissioned)
  - New command-create on the decommissioned device -> 409
    "Endpoint device is decommissioned; reactivate it before creating new operations."
    (EndpointDeviceWriteGuard). Body field is `type` (NOT commandType) -- a wrong field 400s
    and would FALSELY read as a revoke-rejection; require the specific 409.
  - Lifecycle audit ENDPOINT_DEVICE_DECOMMISSIONED + cascade counts
    (cancelledCommands / revokedTokens / finalizedUninstalls); secret clear is a side-effect, no separate count
  - reactivate: POST .../endpoint-devices/{deviceId}/reactivate {"reason":"..."}
    -> OFFLINE or PENDING_ENROLLMENT; ONLINE is earned by the next real heartbeat

Acceptance:
  - decommission 200; command-create on revoked device returns SPECIFIC 409 (not generic 4xx / not 400)
  - Lifecycle + hash-chain audit rows persisted
  - reactivate restores the device (HMAC/cert-bound; no manual re-enroll for the same device)
```

### 4.3 Layer 3 — GPO Rollback (DC-side)

```
Scenario: GPO Software Installation needs rollback to non-MSI state

Drill steps:
  1. Domain admin (operator) opens GPMC
  2. Edit GPO "EndpointAgentM5-Install":
     - Computer Configuration > Software Settings > Software Installation
     - Right-click MSI package > Remove
     - Choose "Immediately uninstall the software from users and computers"
  3. Apply GPO change
  4. Wait for next computer policy cycle on lab-clone PCs (≤120 min)
  5. GPO refresh: gpupdate /force on each lab-clone PC
  
Expected evidence:
  - GPO change audit log (DC Event Viewer)
  - Each lab-clone PC: Event 102 ApplicationInstaller uninstall (already covered Layer 1 if MSI removal)
  - GPRESULT shows no MSI package in Software Installation section
  - gpresult /h post-rollback.html → policy snapshot clean
  - No orphan registry keys post-uninstall

Acceptance:
  - GPO uninstall propagated to 5/5 lab-clone PCs
  - 5/5 PCs agent removed
  - 0 MSI fragments in HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall
  - GPO original state revertable (settings backup pre-drill enables restore)
```

## 5. Destructive Action Checklist (chronological order)

**HARD ORDER** — bu sıra dışı YASAK:

```
Phase 1 — Pre-Drill (operator + agent):
  ☐ Lab-clone environment 5-PC + lab AD + lab backend READY
  ☐ Pre-drill snapshot evidence bundle (baseline state captured)
  ☐ Mavis ops aware + drill window agreed (e.g., 4h window)
  ☐ Rollback rollback plan documented (revert from drill state if needed)
  ☐ Board issue #1379 cross-link to drill schedule

Phase 2 — Drill Layer 1 (MSI Uninstall) — 1+ lab-clone PC:
  ☐ Lab-clone PC moved to non-pilot OU
  ☐ GPO refresh executed (gpupdate /force)
  ☐ Wait ≤120 min for GPO Software Installation uninstall trigger
  ☐ Layer 1 evidence collected (Event 102 + Service status + binary check)
  ☐ Layer 1 acceptance: PASS/FAIL noted

Phase 3 — Drill Layer 2 (Enrollment Revoke = device decommission) — 1+ lab-clone PC:
  ☐ Identify deviceId pre-uninstall (GET /api/v1/endpoint-admin/endpoint-devices)
  ☐ decommission call (MANAGER JWT): POST .../endpoint-devices/{deviceId}/decommission
  ☐ Backend lifecycle + hash-chain audit row (ENDPOINT_DEVICE_DECOMMISSIONED + cascade counts) verified
  ☐ New command-create on decommissioned device returns specific 409 (revoked device cannot act)
  ☐ reactivate restores device (OFFLINE/PENDING_ENROLLMENT)
  ☐ Layer 2 evidence collected
  ☐ Layer 2 acceptance: PASS/FAIL noted

Phase 4 — Drill Layer 3 (GPO Rollback) — domain admin + GPO change:
  ☐ Domain admin opens GPMC; edits GPO "EndpointAgentM5-Install"
  ☐ Remove MSI package "Immediately uninstall"
  ☐ GPO change applied
  ☐ 5/5 lab-clone PCs gpupdate /force
  ☐ Wait ≤120 min for policy propagation
  ☐ Each PC: GPRESULT verify clean + agent removed verify
  ☐ Layer 3 evidence collected
  ☐ Layer 3 acceptance: PASS/FAIL noted

Phase 5 — Post-Drill (operator + agent):
  ☐ Evidence bundle archived (3-layer + Mavis log)
  ☐ Lab AD GPO restored to pre-drill state (revert for re-use)
  ☐ Lab-clone PCs re-enrolled if needed for next drill cycle
  ☐ #1379 closure comment with drill PASS or DRILL FAIL evidence
  ☐ Mavis ops sign-off
```

## 6. Mavis Ops Coordination Format

### 6.1 Drill Kickoff Approval

```
mavis communication send \
  --to <ops-peer> \
  --command prompt \
  --content "M7 rollback drill PROPOSED YYYY-MM-DD HH:MMZ:
  - Lab-clone environment: <name>
  - 5-PC lab-clone: pilot-pc-01-lab .. 05-lab
  - 3-layer scenario: §4.1 + §4.2 + §4.3 sequential
  - Estimated duration: ~4h
  - Destructive scope: lab AD GPO + lab backend revoke
  - Rollback plan: §5 Phase 5 (revert lab AD GPO + re-enroll)
  - Mavis approval requested: APPROVE or HOLD with reason
  - Tracked by: #1379"
```

### 6.2 Per-Layer Status

```
mavis communication send \
  --to <ops-peer> \
  --command prompt \
  --content "M7 Layer 1 (MSI Uninstall) status:
  - 1 lab-clone PC: pilot-pc-01-lab
  - GPO refresh executed +5 min
  - Awaiting policy cycle (ETA +120 min)
  - Action: WAIT"
```

### 6.3 Drill Closure

```
mavis communication send \
  --to <ops-peer> \
  --command prompt \
  --content "M7 drill closure YYYY-MM-DD:
  - Layer 1 MSI Uninstall: PASS (1/1 lab-clone PC; Event 102 uninstall successful)
  - Layer 2 Enrollment Revoke: PASS (decommission 200 + hash-chain audit + 409-on-revoked + reactivate)
  - Layer 3 GPO Rollback: PASS (5/5 lab-clone PC GPRESULT clean + agent removed)
  - Evidence bundle: evidence/m7-rollback-drill-YYYYMMDD/
  - Lab AD GPO restored to pre-drill state
  - Mavis ops sign-off: APPROVED M7 closure gate
  - Tracked by: #1379"
```

## 7. Evidence Pack Template

Layout:
```
evidence/m7-rollback-drill-YYYYMMDD/
├── README.md                          # drill context (date, lab-clone PCs, GPO, scenarios)
├── 00-pre-drill-snapshot/
│   ├── lab-clone-pc-states.md
│   ├── lab-backend-enrollment-state.sql
│   ├── lab-gpo-settings-backup.xml    # GPMC backup of GPO pre-drill state
│   └── lab-ad-ou-structure.md
├── 01-layer-1-msi-uninstall/
│   ├── scenario-step-log.md
│   ├── gpresult-pre-uninstall.html
│   ├── gpresult-post-uninstall.html
│   ├── event-102-uninstall.txt
│   ├── service-status-post.txt
│   ├── binary-check-post.txt
│   └── acceptance-result.md            # PASS/FAIL
├── 02-layer-2-revoke/
│   ├── scenario-step-log.md
│   ├── decommission-request.txt        # POST .../endpoint-devices/{id}/decommission
│   ├── decommission-response.txt       # status DECOMMISSIONED + cascade counts
│   ├── lifecycle-audit-evidence.sql    # ENDPOINT_DEVICE_DECOMMISSIONED + hash-chain
│   ├── device-status-check.sql         # status enum (DECOMMISSIONED)
│   ├── revoked-command-409.txt         # command-create on revoked device -> 409 proof
│   ├── reactivate-response.txt         # reactivate -> OFFLINE/PENDING_ENROLLMENT
│   └── acceptance-result.md            # PASS/FAIL
├── 03-layer-3-gpo-rollback/
│   ├── scenario-step-log.md
│   ├── gpo-pre-rollback.xml
│   ├── gpo-post-rollback.xml
│   ├── dc-event-log-gpo-change.txt
│   ├── per-pc-gpresult-post/
│   │   ├── pilot-pc-01-lab-clean.html
│   │   ├── ...
│   │   └── pilot-pc-05-lab-clean.html
│   └── acceptance-result.md            # PASS/FAIL
├── 04-mavis-coordination-log.txt
├── 05-rollback-revert-evidence.md     # §5 Phase 5 lab AD GPO restored
└── mavis-signoff.txt                  # Mavis ops M7 closure sign-off
```

## 8. Closure Acceptance Checklist (M7 #1379)

- [ ] Pre-drill snapshot evidence collected (baseline state)
- [ ] Lab-clone environment 5-PC + lab AD + lab backend READY
- [ ] Mavis ops APPROVE drill window
- [ ] Layer 1 MSI uninstall PASS (Event 102 + service stopped + binary removed)
- [ ] Layer 2 enrollment revoke PASS (decommission 200 + hash-chain audit + cascade counts + 409-on-revoked + reactivate restores)
- [ ] Layer 3 GPO rollback PASS (5/5 lab-clone PCs GPRESULT clean + agent removed)
- [ ] 3-layer drill closure: 3/3 PASS (or 1+ DRILL FAIL → re-iterate)
- [ ] Lab AD GPO restored to pre-drill state (revert path proven)
- [ ] Evidence bundle archived to `evidence/m7-rollback-drill-YYYYMMDD/`
- [ ] Mavis ops sign-off comment on #1379 with APPROVED closure
- [ ] Destructive action checklist (§5) all phases ticked

## 9. Closure Provenance

Cross-AI peer review:
- Implementer: Claude (Anthropic) — Session 51 Faz 22 otonom chain (single-PR scope; M7 destructive draft)
- Reviewer (plan-time): Codex (OpenAI GPT-5.2) thread `019ea922` AGREE source-side draft scope (M7 destructive boundary explicit)
- Verdict: AGREE source-side draft + 3-layer scenario + destructive checklist + Codex plan-time AGREE pin per scope edit

**Drill execution requires separate plan-time consult**: Bu PR runbook MERGED ≠ drill executed. Lab-clone drill execution requires:
1. Separate Codex plan-time consult (drill execution scope, lab-clone PC list, exact scenarios)
2. Mavis ops APPROVE
3. Domain admin authority confirmed
4. M5 + M6 closure precondition met
5. Drill execution sonra acceptance checklist + evidence bundle + Mavis sign-off

**Closure ≠ runbook merge**: Source draft scope AGREE; runtime acceptance ayrı kapı.
