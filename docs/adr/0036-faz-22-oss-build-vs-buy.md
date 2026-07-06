# ADR-0036 — Faz 22.6 / 22.8 / 22.9 OSS Build-vs-Buy: build Category 1+2 in-house, selective-wrap Category 3

> **Status:** ACCEPTED (owner decision, 2026-06-09) — planning/architecture only; opens NO runtime (22.6/22.8 runtime stays #1388-gated)
> **Decider:** Owner explicit decision ("Kategori 1 ve 2 tamamını biz yazalım", 2026-06-09)
> **Reviewer:** Codex (OpenAI) thread `019eac3d` (REVISE → absorbed)
> **Scope:** cross-phase OSS build-vs-buy for the endpoint sensitive-ops capabilities. Consolidates + supersedes the per-phase OSS tables in `faz-22-remote-access-bridge-plan` §2.1, `faz-22-endpoint-data-protection-plan` §3, `faz-22-security-telemetry-plan` §3 (those become pointers to this ADR).
> **Board:** closes the decision-only matrix issues #1399 / #1400 / #1401 / #1403 / #1404 (see §6).

---

## 1. Context

Faz 22.6 (remote access), 22.8 (data protection), 22.9 (security telemetry) each evaluated OSS candidates (OpenZiti/zrok, MeshCentral, RustDesk, Guacamole, Kopia, restic, Velociraptor, osquery, YARA, Sigma, Wazuh). The platform's standing principle (ADR-0002 §7.1 single-host 400 GB + PG-only discipline; ADR-0012-EA: platform owns the security decision surface) already said "build the core, wrap only commodity layers."

The owner has now decided the build-vs-buy split explicitly: **build Category 1 + Category 2 in-house** (reusing existing platform primitives), and **wrap a Category-3 OSS library only when its specific capability actually lands**. This ADR records that decision + the honest effort/risk framing (Codex `019eac3d`).

This is an architecture/planning decision. It opens **no runtime** — 22.6/22.8 live capabilities remain gated by #1388.

---

## 2. Decision

### Category 1 — Core (build in-house; was always build)
Broker / policy / **OpenFGA authz** / dual-control (no self-approval) / immutable audit / recording-policy / cert-bound single-use token. This is the platform's security authority (ADR-0033 broker, ADR-0012-EA charter). No OSS owns this.

### Category 2 — Need-scoped commodity (build in-house, reuse existing primitives)
| Need | In-house build (reuse) | OSS NOT used |
|---|---|---|
| 22.6 reverse tunnel | **New WS data-plane** that **reuses the agent's existing identity/credential roots** (enrollment cert + HMAC), NOT the existing REST poll transport (that is request/response, not streaming) | OpenZiti / zrok |
| 22.6 interactive shell | Constrained **PTY/terminal** via Windows ConPTY (NOT raw shell — explicit exception, §4) | — |
| 22.6 session recording | Terminal-I/O capture (asciicast/ttyrec) + hash-chain reusing the audit primitive; **fail-closed** | — |
| 22.8A backup | **Dry-run manifest only** — file-walk + **metadata** (path-class / size / mtime-bucket / owner-scope / count) + allow/deny report; **NO content read, NO content hash, NO copy** (content hash crosses the DC-EA-1 metadata-only boundary = reading file content → deferred to an approved bounded-content/copy capability) | Kopia (not for dry-run) |
| 22.9 posture telemetry | **Already built** via AG-035/037/038/039/040 probes | osquery |

### Category 3 — Wrap a focused OSS lib ONLY when its specific capability lands (capability-specific trigger)
| OSS | Wrap ONLY when… (crisp trigger) | Until then |
|---|---|---|
| **Apache Guacamole** | screen/RDP/VNC/clipboard/GUI session-shadowing is needed (i.e. beyond PTY) — NOT for generic "remote access" | SKIP (pilot is PTY-only) |
| **Kopia** | real backup **copy** + repository lifecycle + dedup/encryption + restore drill + retention/schedule is needed — NOT for the dry-run manifest | SKIP (dry-run is in-house) |
| **YARA** | file-content IOC / malware / signature scan is needed. NB: credential/**secret-scan** may need a *separate* scanner boundary — YARA is not automatically the answer | SKIP |
| **Velociraptor** | **re-evaluate ONLY if** DFIR artifact-collection / live-hunt lands (22.8C clean-room + legal gate #1403) — reactivation trigger, not a standing wrap | SKIP (no standing server; AGPL) |

### Skip entirely (no near-term or core role)
OpenZiti/zrok (reuse existing channel roots), MeshCentral/RustDesk (full suites with own authz/relay → wrapper pierce = #1388 bypass), osquery (we already collect posture), **Sigma** (DRL 1.1 — license-gated, not standard OSS), **Wazuh** (full SIEM/HIDS = second control plane + heavy ops, reject-as-core). Any future adoption needs a separate ADR (measured latency/recall/size + backup + DR + resource budget, per ADR-0002 §7.1).

---

## 3. Effort — honest sizing (Codex `019eac3d` correction)

Category 2 is **NOT uniformly "low".** The 22.6 tunnel/PTY/recording stack is **MEDIUM-HIGH** when production-grade (staged: a PTY-only single-session lab PoC is low-medium; production is medium-high). The other Cat-2 items (dry-run manifest, posture telemetry-already-built) are genuinely low.

**Why MEDIUM-HIGH (the agent transport is REST-poll, not a stream):** the existing agent does enroll / heartbeat / `GET /commands/next` poll / result POST — there is no stateful streaming/data-plane today. The reverse tunnel **reuses the identity/credential roots but the WS data-plane is brand new.** Hidden costs that must be designed (not hand-waved):
- **Post-upgrade auth:** HMAC covers the existing request model but NOT WS frames after upgrade → need session lease, expiry, device-binding, operator-binding, anti-replay, channel-binding.
- **Backpressure:** terminal stdout flood / slow browser / backend memory → frame-queue cap, byte cap, pause/kill semantics.
- **ConPTY edge cases:** Session-0 service context, privilege drop, process-tree kill, Ctrl-C/Break/EOF, resize, codepage/UTF-8, handle leaks, deadlocks.
- **Recording fail-closed atomicity:** recording sink + audit row must be ready BEFORE the interactive channel; sink-unavailable → session deny/pause/kill; final hash bound to audit atomically.

This does NOT flip to "buy" — OpenZiti would solve transport but NOT broker policy / OpenFGA / recording / ConPTY / audit atomicity / operator UX. But the effort label in the plan must read **MEDIUM-HIGH (staged)**, not "low".

---

## 4. 22.6 interactive terminal = explicit high-risk exception (NOT a silent guardrail extension)

The agent security model states "raw shell yok" (no raw shell). The Cat-2 PTY therefore must be encoded as a **new, owner-approved, high-risk exception with a dedicated surface — never folded into the generic command path**:
- **Dedicated capability `REMOTE_TERMINAL_SESSION` + dedicated session API** (not the generic `/commands` surface; high-risk types are already dedicated-path-only in `EndpointAdminCommandService`).
- **OpenFGA actions** separate: `remote_access:start`, `remote_access:join`, `remote_access:terminate`, `remote_access:view_recording`.
- **Dual-control + reason + max-duration + idle-timeout + one active session per device.**
- **Agent privilege boundary explicit:** LocalSystem shell default is FORBIDDEN; the ConPTY-spawning token/account must be specified.
- **Recording mandatory:** recording-unavailable = session-unavailable.
- **No arbitrary TCP forwarding, no SOCKS, no local port-forward, no file transfer.**
- **Rate-limit + output-byte-cap + input-frame-cap + terminal-dimension-cap.**
- **Full audit hash-chain reuse** (ADR-0012-EA DD-EA immutable-audit boundary).

(Runtime still #1388-gated; this defines the surface, not an activation.)

---

## 5. Consequences

- **Positive:** the security decision surface stays platform-owned; reuses existing primitives (agent identity roots, OpenFGA, audit, AG-* probes) → no new heavy stateful OSS (ADR-0002 §7.1 honored); Cat-3 wrap deferred to focused libs only when a real capability lands.
- **Cost:** 22.6 tunnel/PTY/recording is MEDIUM-HIGH (staged); must be built carefully (the §3 hidden costs).
- **Boundary:** Cat-3 wrap-triggers are capability-specific (§2) to prevent scope creep; any Cat-3 adoption = separate ADR + #1388 + DPA/license review.

## 6. Board issue closure (decision-only matrices)

These issues were "decide the matrix" tasks; the decision is now recorded here. Close each with: *"Decision recorded in ADR-0036; opens no runtime; #1388 gate remains; in-house implementation tracked by the per-phase plan slices."* If any issue also carried an execution task, link a replacement in-house board issue before closing.
- #1400 OSS-only build-vs-buy matrix → ADR-0036 (this).
- #1401 22.6 transport adapter POC (MeshCentral/RustDesk) → SKIP-as-core; Guacamole wrap-only-if-GUI.
- #1399 22.8A backup engine matrix → dry-run in-house; Kopia wrap-only-if-real-copy.
- #1403 22.8C Velociraptor clean-room/legal → reactivation-trigger only (DFIR lands).
- #1404 22.9 telemetry matrix → posture in-house (AG-*); YARA wrap-only-if-scan; osquery/Sigma/Wazuh skip.

## 7. Note — ADR-0033 number collision (separate fix in this PR)

`docs/faz-21/charter.md` + ADR-0032 reserved **ADR-0033 for "Faz 21.2 Physical Isolation Decision."** ADR-0033 was instead merged (#1407) as the 22.6 remote-access broker. To resolve: the **future Faz 21.2 physical-isolation ADR is re-pointed to ADR-0037** (reserved); the merged 22.6 broker keeps ADR-0033. (charter + ADR-0032 refs updated in this PR.)

## 8. References

- ADR-0033 (22.6 broker design) + ADR-0034 (#1388 owner-decision) + ADR-0012-EA (charter) + ADR-0002 §7.1 (single-host/PG-only) + ADR-0030 (KVKK)
- Plans: faz-22-remote-access-bridge-plan / faz-22-endpoint-data-protection-plan / faz-22-security-telemetry-plan (now point here)
- Codex `019eac3d` (encoding review)
