# Faz 22 Completion — Action Plan (Owner/Operator/Legal + Agent Execution)

> **Status:** ACTIVE, updated 2026-06-27. **Machine gate (canonical):** `scripts/faz22-remote-ops/faz22-6-completion-audit.sh` (run from `origin/main`) + `docs/runbooks/RB-faz22.6-autonomous-completion-contract.md`.
> This doc lists the **irreducible human (owner/operator/legal) items** plus the **agent execution plan** to reach `F22_6_COMPLETION=pass` durably. Engineering/security markers are fail-closed (named owner + dates); they cannot be auto-generated/forged (contract §4/§9).
>
> **🔑 GOVERNING RULE — [ADR-0044](adr/0044-faz22-6-kvkk-nonblocking-parametric-durations.md) (owner directive 2026-06-27, Codex `019f05cc` AGREE):** **KVKK / legal items are NEVER engineering-completion blockers** — they run as a **parallel, tracked, non-blocking** owner/DPO track (allowlist: `kvkk_attended_pilot_signoff`, `legal_dpo_consent`, `retention_policy_approval`). Engineering/security/auditability evidence stays fail-closed. Retention **durations are parametric** (config keys; owner sets the value → config flip, not a blocker). Content-recording **default = OFF** (privacy-safe MVP). `F22_6_COMPLETION` = engineering + #548 + live broker/release **only**; KVKK is emitted as `tracked_pending|cleared|expired` (visible, never fail-closes). *Audit/contract enforcement of this split lands in one atomic follow-up PR; until then the existing stricter bundled gate stays in force (no over-claim window).*

## 0. Current gate truth (audit-verified 2026-06-26)

| Gate | State |
|---|---|
| Operation catalog / approved runner / constrained executor / operator-UX / AgentPC2 bootstrap | ✅ pass |
| Release-lineage (v0.3.1 canonical bounded-pilot) | ✅ pass |
| REMOTE_BRIDGE_LIVE (digest-alignment) | ✅ pass (fixed 2026-06-26, PR #2068 + live rollout to V77 8c4209ee) |
| **#548 B1.4 hardware attestation** | ⛔ blocked — `missing-acceptance-marker` (OWNER) |
| **#1580 VIEW_ONLY — ENGINEERING** | ⛔ blocked — build + live evidence not yet produced (AGENT→OWNER marker) |
| **#1580 VIEW_ONLY — KVKK** | 🟡 `tracked_pending` — **NON-BLOCKING** parallel legal track (ADR-0044) |
| **F22_6_COMPLETION** | blocked on engineering markers (#548 hardware + #1580 engineering) — **NOT** on KVKK |

Owner decisions recorded: **#548 = STRONG path (real hardware/TPM attestation)**, not the bounded-pilot risk-acceptance. **KVKK = parallel non-blocking track + parametric durations** ([ADR-0044](adr/0044-faz22-6-kvkk-nonblocking-parametric-durations.md)).

## 1. PART A — Owner / Operator / Legal items (only you can do these)

### A1 · #548-A Vault gate-B enablement — OPERATOR
- Enable the test-Vault **HTTPS listener** (gitops PR #2054 config) — requires a **Vault restart on staging-sw** (shared blast radius → needs your go).
- Provide a **Vault privileged token** (or run the PKI setup yourself via `docs/runbooks/RB-faz22-3b-vault-pki-setup.md`) so the agent can create the `pki_int` mount + `tpm-device` role + AppRole.
- Why: device-key cert issuance fail-fasts unless Vault is HTTPS + the PKI engine is live.

### A2 · #548-A hardware-attestation marker — OWNER
- After the agent runs the live TPM session (denetim PC) + produces the evidence, provide `owner_approved_by` (your name) + `approved_at` (date) for `F22_6_B1_4_HARDWARE_ATTESTATION_ACCEPTANCE`.

### A3 · #1580 KVKK / legal — OWNER + DPO/LEGAL — **PARALLEL, NON-BLOCKING** (ADR-0044)
> These run **in parallel** and do **NOT** block engineering completion (`F22_6_VIEW_ONLY_KVKK = tracked_pending`). The MVP defaults content-recording **OFF** (no content persistence → no recording-retention dependency), so items 2 below is only required **if/when** recording is later enabled. When cleared, the owner posts the `F22_6_VIEW_ONLY_KVKK: v1` marker → `cleared`.
1. **Lawful basis + aydınlatma metni** (disclosure text) for screen observation (employee-context consent validity).
2. **Retention süresi** = **PARAMETRIC** (config key, not a fixed blocker): for the recording-OFF MVP, content retention is **N/A**; `session_metadata_retention_days` has a conservative default + owner-override. If recording is later enabled, set `recording_retention_days` (owner-decision-ref) → applied as config.
3. **VERBIS purpose registration**: "Diğer: uzaktan destek — ekran gözlemi" (separate from 13-İşitsel, which covers audio only — prior VERBIS analysis).
4. **Employee notice / workplace remote-support policy.**
5. **Pilot device + operator + window** selection + **attended-pilot signoff** (`kvkk_attended_pilot_signoff`).

### A4 · #1580 VIEW_ONLY **ENGINEERING** marker — OWNER (this is the gate; KVKK is separate)
- After the agent runs the live VIEW_ONLY smoke + produces the v2 evidence package, provide `owner_approved_by` (engineering acceptance) + `approved_at` + `expires_at` for **`F22_6_VIEW_ONLY_ENGINEERING: v2`** (NOT the legacy bundled `F22_6_VIEW_ONLY_ACCEPTANCE`). This is the fail-closed completion gate. The DPO `F22_6_VIEW_ONLY_KVKK` marker (A3) is tracked separately and non-blocking.

### A5 · Faz 22.5 operator/time gates — OPERATOR (runbooks already done)
- M5 GPO pilot 5-PC · M6 50-PC capacity baseline · M7 rollback drill (runbooks `RB-faz22*`; execution needs real devices).
- M4 signed MSI GPO domain pilot (trusted signing + AppLocker/WDAC + GPO).

## 2. PART B — Agent execution (autonomous; cross-AI reviewed)

### B1 · #2067 durable version-drift guard — ✅ DONE (Codex 019f0733 verdict C)
**Eliminated the drift sources instead of syncing copies.** The single SSOT is now the **rendered overlay**: a shared lib (`scripts/governance/lib-remote-bridge-digest.sh`) renders the overlay and extracts the endpoint-admin digest; the completion-audit **derives** `expected_digest` from it (no hardcoded `EXPECTED_REMOTE_BRIDGE_DIGEST` literal — env override only as an explicit `ALLOW_EXPECTED_DIGEST_OVERRIDE=1` diagnostic escape hatch, output marks `expected_source`); the contract §3 cell is **de-pinned**; the apply-workflow `expected_digest` default is **emptied** (derived from the render at run time, asserted equal if provided). The PR-time guard + a new `tests/governance/test_remote_bridge_digest_alignment.sh` enforce the same-image invariant fail-closed. A future endpoint-admin V-bump can no longer silently re-drift any literal — there are no literal copies left (the auto-sync keeps the 2 overlays aligned; everything else derives). Live-proven: `REMOTE_BRIDGE_LIVE=pass expected_source=rendered-overlay`.

### B2 · #1580 VIEW_ONLY build — slice-by-slice (in-house; NOT Guacamole/RDP/VNC)
First acceptance = **single-device attended bounded pilot** over the existing outbound agent + remote-bridge (low-fps PNG/JPEG over gRPC DATA). **MVP = `recording_mode=disabled`** (live VIEW_ONLY, no content persistence; metadata audit always-on — ADR-0044 D3/D5). Slices (each cross-AI reviewed + browser smoke):
1. Backend real `DataPlaneHandler` — **mode-aware** fanout: `recording_mode=disabled` MVP = live-only, **no content object/storage write path** (positive negative-proof) + metadata audit; `recording_mode=enabled` (opt-in) = record-before-fanout + recording-down→fail-closed-kill + WORM + parametric retention. Session/device/permit mapping + audit.
2. Agent — DATA frame sender + SCREEN_VIEW permit dispatch + broker-state→capture-gate binding + local-abort trigger.
3. Web — one-to-one viewer (canvas + **no-input guarantee** + session-state + authz).
4. Privacy controls live — consent screen + active indicator + local abort + DLP/mask fail-closed + `processingPurpose=REMOTE_SUPPORT_SCREEN_OBSERVATION` purpose-tag + **parametric retention config** (`recording_mode`, `recording_retention_days`, `session_metadata_retention_days` — ADR-0044 D3).
5. Negative-matrix live — no-auth, wrong-device, expired-session, recording-down (enabled-mode), dlp-deny, local-abort, **recording-disabled-no-persistence + metadata-audit-still-on** (disabled-mode proof).
6. Live smoke → v2 evidence manifest (jq -cS SHA256) → `F22_6_VIEW_ONLY_ENGINEERING: v2` marker (owner fills A4). KVKK marker (A3) is separate + non-blocking.
- Effort: ~3-5 eng-weeks. (Codex consults `019f0591` + `019f05cc`.)
- **Prerequisite (this arc):** the contract+audit schema split PR (F22_6_VIEW_ONLY_ENGINEERING v2 + F22_6_VIEW_ONLY_KVKK v1 + allowlist + mode-based recording) lands first per ADR-0044 acceptance criteria.

### B3 · #548-A hardware attestation — after A1 (Vault gate-B)
- PKI setup (RB-faz22-3b) once Vault HTTPS is live → live device-key TPM session on denetim PC (mint-and-attest chain ready) → cert issued → V74 binding row → `device=true` → hardware-attestation evidence → marker (owner fills A2).

## 3. PART C — Sequence + dependencies

- **B0 (contract+audit schema split)** — the ADR-0044 atomic PR (F22_6_VIEW_ONLY_ENGINEERING v2 + F22_6_VIEW_ONLY_KVKK v1 + allowlist + mode-based recording + legacy fail-safe + dual audit output + tests). Lands **before** B2 closes; cross-AI post-impl review.
- **B1 (#2067)** — independent, now.
- **B2 (#1580 build)** — independent of Vault **and of KVKK** (KVKK is now non-blocking, ADR-0044). Agent builds the recording-OFF MVP; owner/DPO do the A3 KVKK items in parallel with **no gate dependency**; A4 engineering marker at the end.
- **A1 (Vault gate-B, operator)** → **B3 (#548-A live TPM)** → **A2 (marker)**.
- **A5 (22.5 drills)** — operator, independent.

## 4. Acceptance boundary (no overclaim)

Even when the engineering markers land, the accepted scope is **bounded-pilot** (single device, attended) — NOT production / broad rollout / 5-50-800 device. The **engineering/security** markers are fail-closed (named owner + valid dates + forbidden-claims listed); they prevent premature-closure and cannot be forged. **KVKK is non-blocking but never lost** — the audit emits `F22_6_VIEW_ONLY_KVKK=tracked_pending|cleared|expired` every run, so the legal obligation stays visible even though it does not fail-close completion (ADR-0044 D4). Industry posture target: Microsoft Defender Live Response / Intune Remote Help / CrowdStrike RTR class controls.
