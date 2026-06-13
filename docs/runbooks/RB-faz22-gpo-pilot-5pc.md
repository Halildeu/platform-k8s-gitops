# RB Faz 22.5 M5 — 5-PC GPO pilot diversity matrix + soak gate

> **Status**: SOURCE DRAFT
> **Runtime mutation**: NONE
> **Operator gate**: REQUIRED (5 PC IT-owned hardware + domain admin pilot OU + EDR allowlist + WDAC/AppLocker code-signing + 7d soak monitoring)
> **Closure claim**: NO (source-side draft; M5 acceptance evidence operator collects)
> **Tracked by**: [#1377](https://github.com/Halildeu/platform-k8s-gitops/issues/1377) Faz 22.5 M5 — 5-PC GPO pilot diversity matrix + soak gate
> **Evidence template**: §6 evidence pack layout (operator + agent collectors)
> **Codex thread**: `019ea922` plan-time AGREE (pattern from RB-faz22-non-domain-windows-pilot.md + RB-faz22.3-ad-cs-setup.md)
> **Prerequisite**: M2 #1376 AD CS / edge mTLS finalization (source LIVE + operator-gate closure)
> **Companion preflight**: `scripts/faz22-mass-deployment/wave-preflight.ps1` (§4.4 — read-only device health, modes preinstall-readiness / enroll-health).

---

> ## ⚠ SCOPE AMENDMENT — owner 2026-06-10 (board [#1377](https://github.com/Halildeu/platform-k8s-gitops/issues/1377) authoritative)
>
> Owner reduced the pilot **5-PC → 2-PC** and the soak minimum **7d → 24h**. **Board #1377 acceptance is authoritative** over the 5-PC tables below (which remain the original design + the full diversity-dimension reference).
>
> **For the 2-PC run, apply the scaled gate:**
> - **2 devices** listed (hostname/OU/OS/arch/HW/EDR/network); x64 coverage.
> - **Diversity minimum (2-PC)**: the 2 devices differ on **≥1 high-signal axis** — (a) EDR-active vs Defender-only, OR (b) fresh-enroll vs prior-enrolled/reinstall, OR (c) distinct Windows build families — and **≥1 device** runs a user-session SYSTEM install/command smoke.
> - **Soak minimum 24h** (not 7d); a shorter soak needs new consensus.
> - Abort thresholds scale to the 2-device denominator (any 1/2 enroll/heartbeat fail → stop + debug M2/M3/M4).
> - **1 device** performs the rollback + reinstall drill (`RB-faz22.5-m7-rollback-drill.md` §4.1 Layer-1 + §4.2 revoke).
> - Post-pilot artifact records **denominator=2**, success rate, failures, rollback readiness, recommendation.

## 1. Scope

**M5** = İlk 5-PC domain-joined pilot (post M2 AD CS LIVE). Hedef: GPO Software Installation kanalı ile 5 fiziksel cihaza endpoint-agent MSI deploy + enrollment + 7d soak no-regress.

**Source-side scope (this runbook)**:
- Diversity matrix design (donanım + OS + subnet kombinasyon)
- Evidence pack template (operator + agent collectors)
- Wave abort formula + threshold (failure_rate, heartbeat_loss, queue_depth)
- Sanitized evidence pack format (gpresult + Event ID Application Installer + EndpointAgent heartbeat + COLLECT_INVENTORY post-install)
- Mavis ops handoff format (board issue cross-link + on-call rotation)
- 7d soak monitoring runbook (PromQL queries + Grafana dashboard pointers)

**Out-of-scope** (operator-bound):
- IT pilot PC allocation (5 PC asset tag + AD object + assigned IT contact)
- Domain admin pilot OU create + GPO link
- EDR allowlist (Defender/CrowdStrike/Sentinel whitelist)
- WDAC/AppLocker code-signing policy build
- Physical 7d soak execution + monitoring + abort decision

## 2. Hard Constraints / Non-Goals

- **No M5 closure without 5/5 PC enrollment + 5/5 GPO Software Installation LIVE + 7d soak no-regress** — partial PASS YASAK (Codex No Fake Work HARD RULE)
- **No expansion to M6 50-PC ramp without M5 PASS + Mavis ops sign-off** — gate sequencing strict (HARD RULE Tam Otonom: M6 prerequisite = M5 closure)
- **No EDR allowlist bypass** — operator-side whitelist process zorunlu; bypass attempt YASAK
- **No GPO Software Installation force-push without GPO settings backup** — pilot OU revert path zorunlu (rollback dependency)

## 3. Diversity Matrix Design

| Dimension | Variants | Min Coverage |
|---|---|---|
| **OS Version** | Windows 10 22H2, Windows 11 23H2 | ≥2 (1 W10 + 1 W11) |
| **Architecture** | x64, ARM64 | ≥1 ARM64 (Surface Pro X, Lenovo Carbon Gen 11) |
| **Subnet** | DC subnet (10.9.10.x), corp standard subnet (10.9.2.x), VLAN-segmented | ≥2 subnets |
| **PC vendor** | Dell/Lenovo/HP mix | ≥2 vendors |
| **User profile** | Standard user (non-admin), local admin disabled | All 5 standard user |
| **AD location** | Pilot OU (dedicated), production OU prep | All 5 pilot OU |
| **EDR** | Defender ATP, CrowdStrike Falcon (if deployed) | matrix entry per EDR product |

### 3.1 5-PC Allocation Template

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
   - Move 5 pilot PCs (computer objects) to this OU

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

```powershell
# BEFORE MSI push (service/exe not yet installed): reachability + machine cert + reboot.
# -RequireMachineCert makes a missing Client-Auth cert a FAIL (tokenless M2 is a hard gate).
.\wave-preflight.ps1 -Mode preinstall-readiness -Json `
  -ApiHost endpoint-agent-mtls.testai.acik.com -RequireMachineCert

# AFTER enroll: service Running + version + signature(HARD) + mode + cert.
# -RequireSignature makes a non-Valid Authenticode signature a FAIL (signed-MSI /
# Trusted Publisher gate); pin the AG-018 leaf with -ExpectedSignerThumbprint when known.
.\wave-preflight.ps1 -Mode enroll-health -Json `
  -ApiHost endpoint-agent-mtls.testai.acik.com `
  -RequireMachineCert -RequireSignature -ExpectedSignerThumbprint <AG-018-leaf-thumbprint>
```

Script: `scripts/faz22-mass-deployment/wave-preflight.ps1` (read-only; modes
`preinstall-readiness` / `enroll-health` / `rollback-clean`). `overall=FAIL` blocks the wave.

> **NOTE**: the preflight `-RequireMachineCert` check only asserts a private-key Client-Auth
> cert is present in LocalMachine\My — it does **NOT** prove the SAN `URI:adcomputer:{guid}` /
> template binding (that is `verify-machine-cert.ps1`'s job). Preflight does not replace M2;
> the **2/2 tokenless positive enroll** (D3) is the authoritative identity proof.

## 5. Wave Abort Formula + Threshold

### 5.1 Failure Modes

| Mode | Detection | Abort Threshold |
|---|---|---|
| **GPO install fail** | Event 102 Application Installer (msiexec exit code ≠ 0) | ≥2/5 (40%) → abort + investigate |
| **Heartbeat loss** | EndpointAgent ping miss > 5 min | ≥1/5 (20%) sustained > 30 min → abort |
| **Enrollment fail** | Backend /enrollments/auto rejection | ≥2/5 (40%) → abort + edge mTLS check |
| **EDR block** | Defender/CrowdStrike alert blocks agent runtime | ≥1/5 (20%) → abort + EDR allowlist re-check |
| **Cert chain fail** | Agent log "cert verify fail" or TLS handshake reject | ≥1/5 (20%) → abort + M2 cert chain re-verify |

### 5.2 Abort Decision Tree

```
For each PC at +24h, +48h, +7d:
  metrics_collect:
    install_status: Event 102 + msiexec exit code
    heartbeat_age: now - last_ping (seconds)
    enrollment_status: backend /enrollments query (active/inactive)
    edr_block: EDR console (alert list)
    cert_status: agent log "cert verify" lines (last 100)
  
  if (install_fail >= 2):
    abort + investigate GPO/MSI/code-signing
  elif (heartbeat_age > 1800 for >= 1 PC):
    abort + investigate network/agent crash
  elif (enrollment_fail >= 2):
    abort + investigate edge mTLS (M2 dependency)
  elif (edr_block >= 1):
    abort + EDR allowlist re-process
  elif (cert_status_fail >= 1):
    abort + M2 cert chain re-verify
  else:
    PASS (continue soak)
```

### 5.3 7d Soak Acceptance

```
For 7 consecutive days:
  - 5/5 PC heartbeat alive (no >1 hour gap)
  - 0 EDR alert on agent runtime
  - 0 GPO redeploy attempts (Event 108 unexpected reinstall)
  - 5/5 PC COLLECT_INVENTORY result hash chain valid (BL-016 hash-chain audit)
  - 0 unhandled agent crash (Event 1000 Application Error)
  - Optional: 1 controlled test command (e.g., COLLECT_INVENTORY trigger) success on 5/5 PC
```

## 6. Evidence Pack Template

Layout:
```
evidence/m5-5pc-pilot-YYYYMMDD/
├── README.md                     # pilot context (date, pilot OU, GPO name, 5 PC asset tags)
├── 01-pilot-ou-screenshot.png    # GPMC pilot OU + GPO link visual proof
├── 02-gpo-software-package.txt   # GPMC export: package path + deployment type + WMI filter
├── 03-code-signing-cert.txt      # Get-AuthenticodeSignature output for MSI + agent binary
├── 04-edr-allowlist-screenshot.png # Defender/CrowdStrike exception list visual
├── 05-wdac-applocker-policy.txt  # exported policy XML/json
├── per-pc/
│   ├── pilot-pc-01/
│   │   ├── 06-gpresult-html.html         # gpresult /h pilot-pc-01.html
│   │   ├── 07-event-102-installer.txt    # Get-WinEvent -ProviderName 'Microsoft-Windows-Application-Experience' Event ID 102/103
│   │   ├── 08-heartbeat-log.txt          # backend GET /endpoint-devices/{id}/heartbeats?since=...
│   │   ├── 09-collect-inventory.json     # backend GET /endpoint-devices/{id}/inventory/latest
│   │   ├── 10-agent-service-status.txt   # Get-Service EndpointAgent status
│   │   └── 11-cert-chain-verify.txt      # Get-ChildItem Cert:\LocalMachine\My + chain trust
│   ├── pilot-pc-02/ ... (same structure)
│   └── pilot-pc-05/ ... (same structure)
├── soak-day-1.md                 # 24h heartbeat + EDR + crash summary
├── soak-day-2.md
├── ...
├── soak-day-7.md                 # 7d closure summary
├── abort-decision-ledger.md      # any failure mode trigger + Mavis decision + recovery
└── mavis-signoff.txt             # Mavis ops sign-off comment text
```

## 7. Mavis Ops Coordination Format

### 7.1 Pilot Wave Announcement (kickoff)

```
mavis communication send \
  --to <ops-peer-or-channel> \
  --command prompt \
  --content "M5 2-PC GPO pilot kickoff YYYY-MM-DD HH:MMZ (board #1377, owner 2-PC/24h):
  - Pilot OU: Pilot/EndpointAgentM5 (2 PC)
  - GPO: EndpointAgentM5-Install linked
  - MSI: EndpointAgent-<version>-signed.msi
  - Soak: 24h (until YYYY-MM-DD)
  - Abort threshold (2-PC): any 1/2 install_fail OR 1/2 heartbeat_loss>30m OR 1/2 EDR block
  - Status updates: +24h
  - Tracked by: #1377"
```

### 7.2 Daily Soak Update

```
mavis communication send \
  --to <ops-peer> \
  --command prompt \
  --content "M5 soak update (24h window):
  - Heartbeat 2/2 alive ✅
  - 0 EDR alerts
  - 0 install retries
  - 0 crash events
  - Next check: +24h"
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
  - Decision: HOLD soak; investigate root cause
  - Tracked by: #1377 + new incident issue"
```

### 7.4 Closure Sign-off

```
mavis communication send \
  --to <ops-peer> \
  --command prompt \
  --content "M5 closure sign-off YYYY-MM-DD (board #1377 2-PC gate):
  - 2/2 PC tokenless enrollment + GPO install LIVE
  - 24h soak: 2/2 heartbeat alive, 0 EDR, 0 crash
  - 1/2 rollback + reinstall drill PASS (M7 §4.1/§4.2)
  - Evidence bundle: evidence/m5-2pc-pilot-YYYYMMDD/
  - Mavis ops sign-off: APPROVED for M6 50-PC ramp gate
  - Tracked by: #1377"
```

## 8. Closure Acceptance Checklist

> **AUTHORITATIVE = 2-PC board #1377 amendment (8.A)**. The 5-PC list (8.B) is the
> **original design reference only** — owner reduced scope to 2-PC / 24h (2026-06-10).
> Do NOT tick the 5/5 + 7d boxes for the live gate; use 8.A.

### 8.A 2-PC board #1377 closure gate (AUTHORITATIVE)

- [ ] Exactly 2 devices listed (hostname/OU/OS/arch/HW/EDR/network); x64 coverage
- [ ] Diversity: ≥1 high-signal axis differs (EDR-active vs Defender-only / fresh vs prior-enrolled / distinct build) + ≥1 user-session smoke
- [ ] 2/2 tokenless enroll (no manual token/ZIP) + heartbeat + inventory + result-submit 200
- [ ] preflight `wave-preflight.ps1` FAIL=0 on 2/2 (preinstall + enroll-health, -RequireMachineCert -RequireSignature)
- [ ] 24h soak no-regress (heartbeat/command stability; shorter needs new consensus)
- [ ] 1 device rollback + reinstall drill PASS (`RB-faz22.5-m7-rollback-drill.md` §4.1 + §4.2)
- [ ] Failed-device queue empty or root-cause classed
- [ ] Post-pilot artifact: denominator=2 / success / failures / rollback readiness / recommendation
- [ ] Mavis ops sign-off on #1377; M6 #1378 ramp readiness kicked off

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

**Closure ≠ runbook merge**: Bu PR runbook MERGED ≠ M5 #1377 closed. Closure operator **2-PC pilot (board #1377 authoritative) + 24h soak + §8.A checklist** + 1-device rollback drill + Mavis sign-off sonra. (5-PC/7d = §8.B original design, superseded.)
