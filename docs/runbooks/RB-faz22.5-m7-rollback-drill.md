# RB Faz 22.5 M7 — Rollback Drill: MSI Uninstall + Enrollment Revoke + GPO Rollback

> **Status**: SOURCE DRAFT (DESTRUCTIVE PLAN ONLY)
> **Runtime mutation**: NONE in this PR (draft only)
> **Destructive execution**: FORBIDDEN until lab-clone operator AGREE + board/Mavis evidence
> **Codex plan-time AGREE required**: ✅ thread `019ea922` AGREE source-side draft scope (M7 destructive boundary)
> **Operator gate**: REQUIRED (lab-clone environment + domain admin + IT lab pilot environment + Mavis ops coordination + destructive action checklist)
> **Closure claim**: NO (source-side draft; M7 acceptance evidence operator collects from lab-clone drill)
> **Tracked by**: [#1379](https://github.com/Halildeu/platform-k8s-gitops/issues/1379) Faz 22.5 M7 — Rollback drill: MSI uninstall + enrollment revoke + GPO rollback
> **Evidence template**: §7 evidence pack layout
> **Prerequisite**: M5 #1377 + M6 #1378 closure + Mavis ops sign-off + IT lab-clone environment

---

## 1. Scope

**M7** = 3-layer rollback drill (post M5 + M6 closure). Hedef: lab-clone environment ile destructive rollback path validate — (a) MSI uninstall agent-side, (b) enrollment revoke backend-side, (c) GPO rollback DC-side.

**Source-side scope (this runbook)**:
- Lab-clone rollback rehearsal pattern (env setup + 5-PC clone)
- Revoke API + ledger proof contract (backend endpoint + audit row)
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
  - OpenFGA tuples cloned (50 agent: tuples)
  - Enrollment records 50 (active)
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
  5. GPO Software Installation triggers uninstall (Event 102 uninstall flag)
  6. Verify agent service stopped + binary removed
  
Expected evidence:
  - Event 102 ApplicationInstaller "Removal Successful"
  - Get-Service PlatformAgent → ServiceController doesn't exist
  - Test-Path "%ProgramFiles%\PlatformAgent\platform-agent.exe" → False
  - %ProgramData%\PlatformAgent\state.json → may persist or removed (depends on MSI cleanup config)

Acceptance:
  - Uninstall completed within 120 min
  - Agent process not running
  - No leftover scheduled tasks
  - No registry orphan keys (HKLM\SOFTWARE\PlatformAgent removed)
```

### 4.2 Layer 2 — Enrollment Revoke (backend-side)

```
Scenario: Compromised agent → revoke enrollment to prevent further data ingest

Drill steps:
  1. Identify agent_id from lab-clone PC (pre-uninstall): backend GET /endpoint-devices/{id}
  2. Operator (admin JWT) calls revoke endpoint:
     POST /api/v1/endpoint-admin/enrollments/{agent_id}/revoke
     Body: {"reason": "drill: rollback test", "revoked_by": "operator", "evidence_ref": "M7 drill scenario 4.2"}
  3. Backend transitions enrollment status: active → revoked
  4. Backend writes audit row: action="ENROLLMENT_REVOKE", agent_id, reason, evidence_ref, timestamp
  5. Backend invalidates agent token (no more API access)
  
Expected evidence:
  - Backend response 200 + revocation confirmation
  - DB query: SELECT status FROM endpoint_enrollments WHERE id=<agent_id> → "revoked"
  - DB query: SELECT * FROM endpoint_audit WHERE action='ENROLLMENT_REVOKE' ORDER BY ts DESC LIMIT 1 → drill row
  - Agent next heartbeat fails with 401 Unauthorized (or 403 Forbidden)
  - OpenFGA tuple: agent:<agent_id> → can_check_in → REVOKED (separate tuple write)

Acceptance:
  - Revoke API 200 within 5 sec
  - Audit row persisted (immutable per V8 trigger)
  - Token invalidated (subsequent agent API call rejected)
  - OpenFGA tuple updated (if multi-layer revoke design includes Layer-2)
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

Phase 3 — Drill Layer 2 (Enrollment Revoke) — 1+ lab-clone PC:
  ☐ Identify agent_id pre-uninstall (already done if Phase 2 included this PC)
  ☐ Revoke API call from operator admin JWT
  ☐ Backend audit row + token invalidation verified
  ☐ OpenFGA tuple update verified (if Layer-2 includes)
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
  - Layer 2 Enrollment Revoke: PASS (revoke API 200 + audit row + token invalidated)
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
│   ├── revoke-api-request.txt
│   ├── revoke-api-response.txt
│   ├── audit-row-evidence.sql
│   ├── enrollment-status-check.sql
│   ├── token-invalidation-test.txt    # agent next heartbeat 401/403 proof
│   ├── openfga-tuple-state.txt        # if Layer-2 multi-layer
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
- [ ] Layer 2 enrollment revoke PASS (API 200 + audit row + token invalidated)
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
