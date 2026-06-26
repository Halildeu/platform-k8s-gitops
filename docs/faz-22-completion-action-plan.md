# Faz 22 Completion — Action Plan (Owner/Operator/Legal + Agent Execution)

> **Status:** ACTIVE, 2026-06-26. **Machine gate (canonical):** `scripts/faz22-remote-ops/faz22-6-completion-audit.sh` (run from `origin/main`) + `docs/runbooks/RB-faz22.6-autonomous-completion-contract.md`.
> This doc lists the **irreducible human (owner/operator/legal) items** plus the **agent execution plan** to reach `F22_6_COMPLETION=pass` durably. Markers are fail-closed (named owner + dates); they cannot be auto-generated/forged (contract §4/§9).

## 0. Current gate truth (audit-verified 2026-06-26)

| Gate | State |
|---|---|
| Operation catalog / approved runner / constrained executor / operator-UX / AgentPC2 bootstrap | ✅ pass |
| Release-lineage (v0.3.1 canonical bounded-pilot) | ✅ pass |
| REMOTE_BRIDGE_LIVE (digest-alignment) | ✅ pass (fixed 2026-06-26, PR #2068 + live rollout to V77 8c4209ee) |
| **#548 B1.4 hardware attestation** | ⛔ blocked — `missing-acceptance-marker` (OWNER) |
| **#1580 VIEW_ONLY screen-share + KVKK** | ⛔ blocked — `missing-acceptance-marker` (OWNER/LEGAL) |
| **F22_6_COMPLETION** | blocked on the 2 owner markers |

Owner decision recorded: **#548 = STRONG path (real hardware/TPM attestation)**, not the bounded-pilot risk-acceptance.

## 1. PART A — Owner / Operator / Legal items (only you can do these)

### A1 · #548-A Vault gate-B enablement — OPERATOR
- Enable the test-Vault **HTTPS listener** (gitops PR #2054 config) — requires a **Vault restart on staging-sw** (shared blast radius → needs your go).
- Provide a **Vault privileged token** (or run the PKI setup yourself via `docs/runbooks/RB-faz22-3b-vault-pki-setup.md`) so the agent can create the `pki_int` mount + `tpm-device` role + AppRole.
- Why: device-key cert issuance fail-fasts unless Vault is HTTPS + the PKI engine is live.

### A2 · #548-A hardware-attestation marker — OWNER
- After the agent runs the live TPM session (denetim PC) + produces the evidence, provide `owner_approved_by` (your name) + `approved_at` (date) for `F22_6_B1_4_HARDWARE_ATTESTATION_ACCEPTANCE`.

### A3 · #1580 KVKK / legal — OWNER + DPO/LEGAL (5 items)
1. **Lawful basis + aydınlatma metni** (disclosure text) for screen observation (employee-context consent validity).
2. **Retention süresi** decision (how long VIEW_ONLY recordings are kept).
3. **VERBIS purpose registration**: "Diğer: uzaktan destek — ekran gözlemi" (separate from 13-İşitsel, which covers audio only — prior VERBIS analysis).
4. **Employee notice / workplace remote-support policy.**
5. **Pilot device + operator + window** selection + **attended-pilot signoff.**

### A4 · #1580 VIEW_ONLY marker — OWNER
- After the agent runs the live VIEW_ONLY smoke + produces the evidence package, provide `owner_approved_by` + `approved_at` + `expires_at` for `F22_6_VIEW_ONLY_ACCEPTANCE`.

### A5 · Faz 22.5 operator/time gates — OPERATOR (runbooks already done)
- M5 GPO pilot 5-PC · M6 50-PC capacity baseline · M7 rollback drill (runbooks `RB-faz22*`; execution needs real devices).
- M4 signed MSI GPO domain pilot (trusted signing + AppLocker/WDAC + GPO).

## 2. PART B — Agent execution (autonomous; cross-AI reviewed)

### B1 · #2067 durable version-drift guard — NOW
Extend `scripts/automation/sync-test-overlay.sh` co-bump + `scripts/governance/check-remote-bridge-digest-alignment.sh` to also cover the 3 SSOT refs (audit `EXPECTED_REMOTE_BRIDGE_DIGEST` + apply-workflow default + contract §3) so a future endpoint-admin V-bump cannot silently re-drift the bridge gate (the recurring "version mismatch" class). Interim rule until landed: every endpoint-admin V-bump co-updates overlays **and** the 3 SSOT refs.

### B2 · #1580 VIEW_ONLY build — slice-by-slice (in-house; NOT Guacamole/RDP/VNC)
First acceptance = **single-device attended bounded pilot** over the existing outbound agent + remote-bridge (low-fps PNG/JPEG over gRPC DATA). Slices (each cross-AI reviewed + browser smoke):
1. Backend real `DataPlaneHandler` — **record-before-fanout** + recording-down→fail-closed-kill + session/device/permit mapping + audit.
2. Agent — DATA frame sender + SCREEN_VIEW permit dispatch + broker-state→capture-gate binding + local-abort trigger.
3. Web — one-to-one viewer (canvas + **no-input guarantee** + session-state + authz).
4. Privacy controls live — consent screen + active indicator + local abort + DLP/mask fail-closed + `processingPurpose=REMOTE_SUPPORT_SCREEN_OBSERVATION` purpose-tag + retention-tag infra.
5. Negative-matrix live — no-auth, wrong-device, expired-session, recording-down, dlp-deny, local-abort.
6. Live smoke → evidence manifest (jq -cS SHA256) → marker (owner fills A4).
- Effort: ~3-5 eng-weeks. (Codex consult `019f0591`.)

### B3 · #548-A hardware attestation — after A1 (Vault gate-B)
- PKI setup (RB-faz22-3b) once Vault HTTPS is live → live device-key TPM session on denetim PC (mint-and-attest chain ready) → cert issued → V74 binding row → `device=true` → hardware-attestation evidence → marker (owner fills A2).

## 3. PART C — Sequence + dependencies

- **B1 (#2067)** — independent, now.
- **B2 (#1580 build)** — independent of Vault; runs **in parallel** with **A3 (KVKK)**. Agent builds while owner/DPO does the 5 KVKK items; A4 marker at the end.
- **A1 (Vault gate-B, operator)** → **B3 (#548-A live TPM)** → **A2 (marker)**.
- **A5 (22.5 drills)** — operator, independent.

## 4. Acceptance boundary (no overclaim)

Even when both markers land, the accepted scope is **bounded-pilot** (single device, attended) — NOT production / broad rollout / 5-50-800 device. The markers are fail-closed (named owner + valid dates + forbidden-claims listed); they exist to prevent premature-closure and cannot be forged. Industry posture target: Microsoft Defender Live Response / Intune Remote Help / CrowdStrike RTR class controls.
