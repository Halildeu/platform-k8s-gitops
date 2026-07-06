# RB Faz 22.5 M5 — selected-device same-day GPO pilot smoke gate

> **Status**: SOURCE DRAFT
> **Runtime mutation**: NONE
> **Operator gate**: REQUIRED (selected devices + domain admin pilot OU/GPO for domain PCs + EDR allowlist + WDAC/AppLocker code-signing + same-day T0/T+15/T+60 monitoring)
> **Closure claim**: NO (source-side draft; M5 acceptance evidence operator collects)
> **Tracked by**: [#1377](https://github.com/Halildeu/platform-k8s-gitops/issues/1377) Faz 22.5 M5 — selected-device same-day GPO pilot smoke gate
> **Evidence template**: §6 evidence pack layout (operator + agent collectors)
> **Codex thread**: `019ea922` plan-time AGREE (pattern from RB-faz22-non-domain-windows-pilot.md + RB-faz22.3-ad-cs-setup.md)
> **Prerequisite**: M2 #1376 AD CS / edge mTLS finalization (source LIVE + operator-gate closure)
> **Companion collectors**: `scripts/faz22-mass-deployment/wave-preflight.ps1` (§4.4) and `scripts/faz22-mass-deployment/m5-same-day-pilot-collector.ps1` (§4.5).

---

> ## HISTORICAL SCOPE AMENDMENT — owner 2026-06-10, superseded 2026-06-15
>
> Owner reduced the pilot **5-PC -> 2-PC** and the soak minimum **7d -> 24h**. This is retained as history only; the later same-day no-24h amendment below is authoritative for the current run.
>
> **Historical 2-PC/24h gate (not current):**
> - **2 devices** listed (hostname/OU/OS/arch/HW/EDR/network); x64 coverage.
> - **Diversity minimum (2-PC)**: the 2 devices differ on **≥1 high-signal axis** — (a) EDR-active vs Defender-only, OR (b) fresh-enroll vs prior-enrolled/reinstall, OR (c) distinct Windows build families — and **≥1 device** runs a user-session SYSTEM install/command smoke.
> - **Soak minimum 24h** (not 7d); a shorter soak needs new consensus.
> - Abort thresholds scale to the 2-device denominator (any 1/2 enroll/heartbeat fail → stop + debug M2/M3/M4).
> - **1 device** performs the rollback + reinstall drill (`RB-faz22.5-m7-rollback-drill.md` §4.1 Layer-1 + §4.2 revoke).
> - Post-pilot artifact records **denominator=2**, success rate, failures, rollback readiness, recommendation.

> ## SCOPE AMENDMENT — owner 2026-06-15 (supersedes the 2-PC/24h gate for this first run)
>
> Owner approved this same-day device pool: **AGENTPC1, AGENTPC2, local Parallels Windows, denetim PC**. Owner also removed the 24h wait for this run.
>
> **For this no-24h run, apply the scaled gate:**
> - Selected device matrix lists all available devices and their role: `domain-gpo`, `audit`, or `local-control`.
> - GPO/tokenless denominator counts only domain-joined GPO-capable devices. Local Parallels may be used as a control/installer/agent smoke, but it does **not** prove domain GPO deployment unless domain-joined.
> - Required same-day checkpoints: **T0**, **T+15m**, **T+60m** using `m5-same-day-pilot-collector.ps1` plus `wave-preflight.ps1`.
> - No 24h closure claim is made. The post-pilot artifact must explicitly state `soak_hours=0` / `same_day_smoke=true`.
> - M6/50-PC expansion may proceed only with an explicit no-24h risk acceptance note, or with a later stabilization evidence gate.

## 1. Scope

**M5** = Same-day selected-device pilot (post M2 AD CS bounded-live evidence). Hedef: domain-joined cihazlarda GPO Software Installation kanalı ile endpoint-agent MSI deploy + tokenless enrollment; local Parallels/control cihazlarında installer/agent smoke. 24h soak bu owner-approved ilk run'da acceptance değildir.

**Source-side scope (this runbook)**:
- Diversity matrix design (donanım + OS + subnet kombinasyon)
- Evidence pack template (operator + agent collectors)
- Wave abort formula + threshold (failure_rate, heartbeat_loss, queue_depth)
- Sanitized evidence pack format (gpresult + Event ID Application Installer + EndpointAgent heartbeat + COLLECT_INVENTORY post-install)
- Mavis ops handoff format (board issue cross-link + on-call rotation)
- same-day T0/T+15/T+60 monitoring runbook (collector JSON + backend heartbeat/result checks)

**Out-of-scope** (operator-bound):
- IT selected-device access/allocation (asset tag + AD object + assigned IT contact)
- Domain admin pilot OU create + GPO link
- EDR allowlist (Defender/CrowdStrike/Sentinel whitelist)
- WDAC/AppLocker code-signing policy build
- Physical device access + same-day monitoring + abort decision

## 2. Hard Constraints / Non-Goals

- **No M5 closure without selected-device matrix + domain-device GPO/tokenless evidence + T0/T+15/T+60 same-day checks + 1-device rollback/reinstall drill** — partial PASS YASAK (Codex No Fake Work HARD RULE)
- **No expansion to M6 50-PC ramp without M5 same-day PASS + explicit no-24h risk note or later stabilization gate + Mavis ops sign-off** — gate sequencing strict (HARD RULE Tam Otonom: M6 prerequisite = M5 closure)
- **No EDR allowlist bypass** — operator-side whitelist process zorunlu; bypass attempt YASAK
- **No GPO Software Installation force-push without GPO settings backup** — pilot OU revert path zorunlu (rollback dependency)

## 3. Diversity Matrix Design

| Dimension | Variants | Min Coverage |
|---|---|---|
| **OS Version** | Windows Server / Windows 10 / Windows 11 | Record every selected device; ≥1 build-family difference preferred |
| **Architecture** | x64, ARM64 | x64 coverage required; ARM64 is optional for this same-day first gate |
| **Subnet** | DC subnet (10.9.10.x), corp standard subnet (10.9.2.x), VLAN-segmented | Record every selected device; subnet diversity is a valid high-signal axis |
| **PC vendor / class** | Server VM / laptop / desktop vendor mix | Record every selected device; class/vendor diversity preferred |
| **User profile** | Standard user (non-admin), local admin disabled | Every selected endpoint documented |
| **AD location** | Pilot OU (dedicated), production OU prep | Domain-gpo endpoints in the pilot OU / pilot security scope |
| **EDR** | Defender ATP, ESET, CrowdStrike Falcon (if deployed) | Record per device; EDR-active vs Defender-only is a valid high-signal axis |

### 3.0 Owner-approved same-day device pool

| Device | Role | Counts for GPO/tokenless denominator? | Notes |
|---|---|---:|---|
| `AGENTPC1` | `domain-gpo` | Yes, if domain-joined and GPO-scoped | Preferred primary GPO pilot device |
| `AGENTPC2` | `domain-gpo` | Yes, if domain-joined and GPO-scoped | Prior 9-hour install discovery exists; retest as fresh same-day GPO path |
| Local Parallels Windows | `local-control` | No, unless joined to `acik.local` and GPO-scoped | Use for installer/agent regression control and fast rollback/reinstall smoke |
| Denetim PC | `audit` | Yes, if domain-joined and GPO-scoped | Use as audit/user-session evidence device |

### 3.1 5-PC Allocation Template (REFERENCE ONLY — superseded by §8.A)

This table is the original diversity design. It is retained as the expansion
reference for later 5-PC/50-PC planning. It is **not** the live M5 closure gate.
Use §8.A for board #1377.

| PC ID | OS | Arch | Subnet | Vendor | EDR | IT Contact |
|---|---|---|---|---|---|---|
| `<pilot-pc-01>` | W10 22H2 | x64 | 10.9.10.x (DC) | Dell OptiPlex | Defender | `<contact>` |
| `<pilot-pc-02>` | W10 22H2 | x64 | 10.9.2.x (corp) | Lenovo ThinkPad | Defender | `<contact>` |
| `<pilot-pc-03>` | W11 23H2 | x64 | 10.9.2.x | HP EliteDesk | Defender | `<contact>` |
| `<pilot-pc-04>` | W11 23H2 | ARM64 | 10.9.2.x | Surface Pro X | Defender | `<contact>` |
| `<pilot-pc-05>` | W11 23H2 | x64 | VLAN-segmented | Dell Latitude | CrowdStrike | `<contact>` |

## 4. GPO Software Installation Setup (operator)

### 4.1 Pilot OU + GPO Link (domain admin)

```
1. AD Users and Computers (DSA.MSC):
   - Create OU "Pilot/EndpointAgentM5" under acik.local
   - Move 2 pilot PCs (computer objects) to this OU

2. Group Policy Management (GPMC.MSC):
   - Create GPO "EndpointAgentM5-Install" linked to OU
   - Edit: Computer Configuration > Policies > Software Settings > Software Installation
   - Right-click > New > Package
   - Path: \\<corp-share>\platform-agent\endpoint-agent-<version>-signed.msi
   - Deployment type: Assigned (not Published)
   - Advanced: Uninstall when removed; UPGRADE (replace existing)
   - WMI filter (optional): only-pilot computers
```

### 4.2 EDR Allowlist + WDAC/AppLocker

```
Defender ATP:
  - Add publisher signature to allowed list (code-signing cert from AD CS)
  - Or add SHA256 hash of MSI installer + agent binary

CrowdStrike Falcon (if used):
  - Falcon Console > Detection > Exceptions
  - Add path exception: %ProgramFiles%\EndpointAgent\
  - Add publisher: <code-signing CN>

WDAC (Application Control for Windows):
  - Policy: AllowSigners <code-signing-cert>
  - Path: %ProgramFiles%\EndpointAgent\*

AppLocker:
  - Path rule: %ProgramFiles%\EndpointAgent\*
  - Publisher rule: <code-signing CN>
```

### 4.3 Code-Signing Cert Chain (AD CS prerequisite M2)

```powershell
# Test signature on agent binary (name is endpoint-agent.exe, NOT platform-agent.exe):
Get-AuthenticodeSignature "$env:ProgramFiles\EndpointAgent\endpoint-agent.exe"
# Expected: Status=Valid; signer = internal CA leaf (AG-018 trusted-internal-ca)

Get-AuthenticodeSignature "EndpointAgent-<version>-signed.msi"
# Expected: Status=Valid; same chain
```

### 4.4 Per-device preflight (read-only, before + after enroll)

Use `mtls.testai.acik.com` for the M5 pilot. `mtls.ai.acik.com` is the prod
counterpart and must not be used until the test M2/M5 acceptance gates pass.

```powershell
# BEFORE MSI push (service/exe not yet installed): reachability + machine cert + reboot.
# -RequireMachineCert makes a missing Client-Auth cert a FAIL (tokenless M2 is a hard gate).
.\wave-preflight.ps1 -Mode preinstall-readiness -Json `
  -ApiHost mtls.testai.acik.com -RequireMachineCert

# AFTER enroll: service Running + version + signature(HARD) + mode + cert.
# -RequireSignature makes a non-Valid Authenticode signature a FAIL (signed-MSI /
# Trusted Publisher gate); pin the AG-018 leaf with -ExpectedSignerThumbprint when known.
.\wave-preflight.ps1 -Mode enroll-health -Json `
  -ApiHost mtls.testai.acik.com `
  -RequireMachineCert -RequireSignature -ExpectedSignerThumbprint <AG-018-leaf-thumbprint>
```

Script: `scripts/faz22-mass-deployment/wave-preflight.ps1` (read-only; modes
`preinstall-readiness` / `enroll-health` / `rollback-clean`). `overall=FAIL` blocks the wave.

> **NOTE**: the preflight `-RequireMachineCert` check only asserts a private-key Client-Auth
> cert is present in LocalMachine\My — it does **NOT** prove the SAN `URI:adcomputer:{guid}` /
> template binding (that is `verify-machine-cert.ps1`'s job). Preflight does not replace M2;
> the **2/2 tokenless positive enroll** (D3) is the authoritative identity proof.

### 4.5 Same-day evidence collector

Run this collector on every selected device at T0, T+15m and T+60m. It is
read-only and writes JSON evidence locally.

```powershell
# Before GPO/MSI push
.\m5-same-day-pilot-collector.ps1 -Phase preinstall -Role domain-gpo -Json

# After GPO/MSI install + tokenless enroll
.\m5-same-day-pilot-collector.ps1 -Phase postinstall -Role domain-gpo `
  -RequireSignature -Json

# Local Parallels/control lane
.\m5-same-day-pilot-collector.ps1 -Phase postinstall -Role local-control -Json

# Rollback/reinstall drill evidence
.\m5-same-day-pilot-collector.ps1 -Phase rollback-clean -Role domain-gpo -Json
```

Evidence path: `C:\ProgramData\EndpointAgent\evidence\m5-same-day\*.json`.

## 5. Wave Abort Formula + Threshold

### 5.1 Failure Modes

| Mode | Detection | Abort Threshold |
|---|---|---|
| **GPO install fail** | Event 102 Application Installer (msiexec exit code ≠ 0) | ≥1/2 (50%) → abort + investigate |
| **Heartbeat loss** | EndpointAgent ping miss > 5 min | ≥1/2 (50%) sustained > 30 min → abort |
| **Enrollment fail** | Backend /enrollments/auto rejection | ≥1/2 (50%) → abort + edge mTLS check |
| **EDR block** | Defender/ESET/CrowdStrike alert blocks agent runtime | ≥1/2 (50%) → abort + EDR allowlist re-check |
| **Cert chain fail** | Agent log "cert verify fail" or TLS handshake reject | ≥1/2 (50%) → abort + M2 cert chain re-verify |

### 5.2 Abort Decision Tree

```
For each selected device at T0/T+15m/T+60m:
  metrics_collect:
    install_status: Event 102 + msiexec exit code
    heartbeat_age: now - last_ping (seconds)
    device_status: GET /api/v1/endpoint-admin/endpoint-devices -> DeviceStatus
                   (PENDING_ENROLLMENT|ONLINE|STALE|OFFLINE|DECOMMISSIONED;
                   tokenless device truth is here, NOT enrollment-token status)
    edr_block: EDR console (alert list)
    cert_status: agent log "cert verify" lines (last 100)
  
  if (install_fail >= 1):
    abort + investigate GPO/MSI/code-signing
  elif (heartbeat_age > 1800 for >= 1 PC):
    abort + investigate network/agent crash
  elif (device_status not in {ONLINE,OFFLINE} for >= 1 PC):  # stuck PENDING_ENROLLMENT
    abort + investigate edge mTLS (M2 dependency)
  elif (edr_block >= 1):
    abort + EDR allowlist re-process
  elif (cert_status_fail >= 1):
    abort + M2 cert chain re-verify
  else:
    PASS (continue same-day monitoring)
```

### 5.3 Same-day smoke acceptance (AUTHORITATIVE for board #1377 no-24h run)

```
At T0, T+15m and T+60m:
  - selected device matrix frozen with role and denominator
  - domain-gpo devices heartbeat alive
  - 0 EDR alert on agent runtime
  - 0 GPO redeploy attempts (Event 108 unexpected reinstall)
  - domain-gpo devices COLLECT_INVENTORY result hash chain valid (BL-016 hash-chain audit)
  - 0 unhandled agent crash (Event 1000 Application Error)
  - at least 1 controlled test command (e.g., COLLECT_INVENTORY trigger) success
  - post-pilot artifact explicitly records same_day_smoke=true and soak_hours=0
```

## 6. Evidence Pack Template

Layout:
```
evidence/m5-same-day-pilot-YYYYMMDD/
├── README.md                     # pilot context (date, pilot OU, GPO name, selected devices, denominator)
├── 01-pilot-ou-screenshot.png    # GPMC pilot OU + GPO link visual proof
├── 02-gpo-software-package.txt   # GPMC export: package path + deployment type + WMI filter
├── 03-code-signing-cert.txt      # Get-AuthenticodeSignature output for MSI + agent binary
├── 04-edr-allowlist-screenshot.png # Defender/CrowdStrike exception list visual
├── 05-wdac-applocker-policy.txt  # exported policy XML/json
├── per-pc/
│   ├── pilot-pc-01/
│   │   ├── 00-m5-collector-t0.json
│   │   ├── 00-m5-collector-t15.json
│   │   ├── 00-m5-collector-t60.json
│   │   ├── 06-gpresult-html.html         # gpresult /h pilot-pc-01.html
│   │   ├── 07-event-102-installer.txt    # Get-WinEvent -ProviderName 'Microsoft-Windows-Application-Experience' Event ID 102/103
│   │   ├── 08-heartbeat-log.txt          # backend GET /endpoint-devices/{id}/heartbeats?since=...
│   │   ├── 09-collect-inventory.json     # backend GET /endpoint-devices/{id}/inventory/latest
│   │   ├── 10-agent-service-status.txt   # Get-Service EndpointAgent status
│   │   └── 11-cert-chain-verify.txt      # Get-ChildItem Cert:\LocalMachine\My + chain trust
│   └── pilot-pc-02/ ... (same structure)
├── same-day-summary.md           # T0/T+15/T+60 heartbeat + EDR + crash summary
├── abort-decision-ledger.md      # any failure mode trigger + Mavis decision + recovery
└── mavis-signoff.txt             # Mavis ops sign-off comment text
```

## 7. Mavis Ops Coordination Format

### 7.1 Pilot Wave Announcement (kickoff)

```
mavis communication send \
  --to <ops-peer-or-channel> \
  --command prompt \
  --content "M5 same-day selected-device pilot kickoff YYYY-MM-DD HH:MMZ (board #1377, owner no-24h):
  - Pilot OU: Pilot/EndpointAgentM5 (domain-gpo devices)
  - GPO: EndpointAgentM5-Install linked
  - MSI: EndpointAgent-<version>-signed.msi
  - Device pool: AGENTPC1, AGENTPC2, local Parallels Windows, denetim PC
  - Soak: no 24h; same-day checkpoints T0/T+15/T+60
  - Abort threshold: any domain-gpo install_fail OR heartbeat_loss>30m OR EDR block
  - Status updates: T0/T+15/T+60
  - Tracked by: #1377"
```

### 7.2 Same-day Update

```
mavis communication send \
  --to <ops-peer> \
  --command prompt \
  --content "M5 same-day update:
  - checkpoint: T+<N>m
  - Heartbeat <n>/<denominator> alive
  - 0 EDR alerts
  - 0 install retries
  - 0 crash events
  - Next check: T+15/T+60 or final"
```

### 7.3 Abort Trigger

```
mavis communication send \
  --to <ops-peer> \
  --command prompt \
  --content "M5 ABORT trigger YYYY-MM-DD HH:MMZ:
  - PC: <pilot-pc-id>
  - Failure mode: <install_fail | heartbeat_loss | enrollment_fail | edr_block | cert_status_fail>
  - Detection: <evidence excerpt>
  - Decision: HOLD same-day pilot; investigate root cause
  - Tracked by: #1377 + new incident issue"
```

### 7.4 Closure Sign-off

```
mavis communication send \
  --to <ops-peer> \
  --command prompt \
  --content "M5 closure sign-off YYYY-MM-DD (board #1377 same-day gate):
  - domain-gpo denominator frozen and documented
  - domain-gpo tokenless enrollment + GPO install LIVE
  - same-day checkpoints: T0/T+15/T+60 heartbeat alive, 0 EDR, 0 crash
  - 1/2 rollback + reinstall drill PASS (M7 §4.1/§4.2)
  - Evidence bundle: evidence/m5-same-day-pilot-YYYYMMDD/
  - No-24h note: same_day_smoke=true, soak_hours=0
  - Mavis ops sign-off: APPROVED for M6 50-PC ramp gate
  - Tracked by: #1377"
```

## 8. Closure Acceptance Checklist

> **AUTHORITATIVE = same-day selected-device owner amendment (8.A)**. The 5-PC
> list (8.B) is the original design reference only. The previous 2-PC/24h gate
> is superseded for this first run by owner no-24h direction on 2026-06-15.

### 8.A Same-day board #1377 closure gate (AUTHORITATIVE)

- [ ] Selected device pool listed: `AGENTPC1`, `AGENTPC2`, local Parallels Windows, denetim PC; each has role/hostname/OU/OS/arch/HW/EDR/network
- [ ] Domain-gpo denominator frozen; local Parallels clearly excluded from GPO proof unless domain-joined and GPO-scoped
- [ ] Domain-gpo devices tokenless enroll (no manual token/ZIP) + heartbeat + inventory + result-submit 200
- [ ] preflight `wave-preflight.ps1` FAIL=0 on domain-gpo devices (preinstall + enroll-health, -RequireMachineCert -RequireSignature)
- [ ] same-day collector JSON attached for each selected device at T0/T+15/T+60
- [ ] same-day no-regress: heartbeat/command stable through T+60; `same_day_smoke=true`, `soak_hours=0`
- [ ] 1 device rollback + reinstall drill PASS (`RB-faz22.5-m7-rollback-drill.md` §4.1 + §4.2)
- [ ] Failed-device queue empty or root-cause classed
- [ ] Post-pilot artifact: denominator / success / failures / rollback readiness / no-24h risk note / recommendation
- [ ] Mavis ops sign-off on #1377; M6 #1378 ramp readiness kicked off only with explicit no-24h risk acceptance or later stabilization gate

### 8.B 5-PC original design (REFERENCE ONLY — superseded by 8.A)

- [ ] (ref) 5/5 PC pilot OU member + GPO linked + WMI filter applied (if used)
- [ ] (ref) 5/5 PC GPO Software Installation Event 102 success (msiexec exit 0)
- [ ] (ref) 5/5 PC endpoint-agent service Running state
- [ ] (ref) 5/5 PC backend enrollment record + cert subject SAN URI valid (M2 chain)
- [ ] (ref) 5/5 PC heartbeat alive at +24h, +48h, +7d
- [ ] (ref) 0 EDR alerts + 0 unhandled crashes (7d window)
- [ ] (ref) 5/5 PC COLLECT_INVENTORY hash chain valid (BL-016 audit)
- [ ] (ref) Diversity matrix covered (≥2 OS, ≥1 ARM64, ≥2 subnet, ≥2 vendor, ≥2 EDR)

## 9. Closure Provenance

Cross-AI peer review:
- Implementer: Claude (Anthropic) — Session 51 Faz 22 otonom chain (single-PR scope)
- Reviewer (plan-time): Codex (OpenAI GPT-5.2) thread `019ea922` AGREE pattern (RB-faz22-non-domain-windows-pilot.md + RB-faz22.3-ad-cs-setup.md inspiration)
- Verdict: AGREE source-side draft + diversity matrix + evidence pack + abort formula + Mavis coordination

**Closure ≠ runbook merge**: Bu PR runbook MERGED ≠ M5 #1377 closed. Closure operator **same-day selected-device pilot (board #1377 authoritative) + §8.A checklist** + 1-device rollback drill + Mavis sign-off sonra. (5-PC/7d = §8.B original design, previous 2-PC/24h = superseded by owner no-24h direction.)
