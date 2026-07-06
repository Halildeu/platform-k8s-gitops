# ADR-0038 — Faz 22.6 Remote Access Bridge: Transport Architecture (gRPC/mTLS, broker-authoritative)

> **Status:** PROPOSED (agent-actionable design accepted; runtime BLOCKED by #1388 owner/legal pilot sign-off, ADR-0034 §13/D10)
> **Date:** 2026-06-12
> **Deciders:** Cross-AI consensus — Codex/OpenAI (thread `019eb9fb`) + Claude/Anthropic (thread `019eb874`)
> **Board:** gitops [#1388](https://github.com/Halildeu/platform-k8s-gitops/issues/1388) (governance gate, P0) · [#1401](https://github.com/Halildeu/platform-k8s-gitops/issues/1401) (transport POC) · backend [#548](https://github.com/Halildeu/platform-backend/issues/548) (security runway) · [#510](https://github.com/Halildeu/platform-backend/issues/510)/[#524](https://github.com/Halildeu/platform-backend/issues/524) · agent [#116](https://github.com/Halildeu/platform-agent/issues/116)
> **Builds on:** [ADR-0033](./0033-faz-22-6-remote-access-bridge-broker.md) (broker state machine / token / audit) · [ADR-0034](./0034-1388-sensitive-endpoint-ops-owner-decision.md) (owner decision record). Supersedes the broker plan's transport sketch.

---

## 1. Context

The Faz 22.6 **security layer is feature-complete at the pure-policy + offline-crypto + integration level** (platform-backend `endpoint-admin-service`, board [#548](https://github.com/Halildeu/platform-backend/issues/548), ~25 merged PRs, each cross-AI reviewed):

- **B1 crypto-identity:** cert-binding, cert-trust (chain + identity-pin + CRL), real ECDSA/DSSE build-attestation, PKIX, **device-identity / TPM key-attestation verifier**.
- **C recording:** WORM hash-chain + out-of-band signed anchor + recorder + durable DB sink.
- **D capability-enforcement:** operation gate, constrained-PTY command allowlist + per-argument policy + composed gate, secret/PII redactor, VIEW_ONLY HMAC watermark, FIDO2 step-up freshness policy, coercion/duress response policy.
- **Integration:** `RemoteSessionPolicyEngine` — the decision core that composes all of the above into one priority-ordered, fail-closed verdict per operation (`evaluate(SessionContext) → ALLOW / DENY / TERMINATE_DURESS`).

What is missing is the **transport**: the part that turns these pure policies into a live, attended remote-support session — the outbound channel from the Windows agent to the broker, the wiring that produces each `SessionContext` input, and the enforcement of the engine's verdict on a live stream. This ADR decides that architecture. It is **agent-actionable design now**; the live pilot remains **owner-gated** (ADR-0034 §13/D10).

**Constraints:** Windows agent is a Go service behind NAT, **outbound-only** (no inbound port on the endpoint); **self-hosted only** (no third-party SaaS relay — KVKK data residency); must carry VIEW_ONLY screen frames + a CONSTRAINED_PTY channel; must support a mid-session **KILL** (revocation / duress) with **sub-second** latency; must reuse the existing mTLS/PKI (B1.4) + device attestation (B1.4d); pilot capability set is **{VIEW_ONLY, CONSTRAINED_PTY}** only.

---

## 2. Decision 1 — Transport = gRPC bidi-streaming over mTLS (domain-specific, policy-carrying)

**Accept gRPC bidirectional streaming over mTLS (HTTP/2)** between the Go Windows agent and the Java broker, with a typed protobuf envelope — designed as a **domain-specific remote-support protocol, NOT a generic reverse tunnel**.

**Why** (Codex `019eb9fb`): natural fit with the existing B1.4 mTLS/PKI (peer cert / chain / CRL / device-binding / attestation bind directly into the broker's session context); production-mature for Java+Go (deadlines, cancellation, keepalive, flow-control, backpressure, interceptors, status codes, observability); policy-aware framing is trivial (every frame carries `sessionId / deviceId / channelId / seq / operationId / decisionId / capability / permitExpiry / payloadHash`); k8s-native (broker is a Service; agent mTLS reaches the broker pod).

**Rejected:**
- **Generic OSS reverse-tunnel (frp / rathole / raw TCP forwarding) — NO-GO for the pilot.** Not a transport-quality issue: a port-forward model **by design** weakens the policy engine, the recording, the per-operation gate, and the constrained-PTY allowlist. If a QUIC-based transport is ever adopted, it must carry the **same protobuf/policy envelope** over QUIC streams — not run a reverse-tunnel product.
- **WebSocket** for the agent↔broker main channel (acceptable broker↔operator-console, but gRPC gives a better typed contract / cancellation / flow-control / Java-Go ergonomics on the agent hop).
- **Raw mTLS TCP + custom frame** — doable but re-implements deadlines / status / streaming / flow-control / interop that gRPC provides.
- **QUIC** — deferred to a future optimization (TCP head-of-line blocking is a theoretical risk; gRPC + a separate control connection is sufficient and far more reviewable for the pilot capability set).

---

## 3. Decision 2 — Broker-authoritative ALLOW; agent-authoritative DENY

The **broker is the single authoritative source of an ALLOW decision**; the **agent is an authoritative source of DENY + local enforcement**. Effective decision = `brokerAllow && agentLocalAllow`. The agent may **never** "the broker didn't allow it but I will". The agent IS authoritative for **negative local signals only**:

- no endpoint-user consent; the persistent indicator can't be shown; the user pressed local-abort;
- Windows session locked / secure desktop / active-user changed; agent local tamper / self-defense alarm;
- broker lease expired; permit signature/sequence invalid; the requested capability is disabled in the local binary.

The **broker is authoritative** for: cert trust / CRL / chain / identity-binding; TPM/device-attestation result; operator identity + role + WebAuthn/FIDO2 step-up freshness; duress/coercion policy; the owner-signed pilot authorization token; the granted capability set; per-operation allowlist + argument policy; recording requirement; WORM/hash-chain anchor state; command redaction + output policy; session revocation.

The agent carries a **narrow copy** of the capability policy for defense-in-depth only — e.g. even if the broker allows `ipconfig /all` inside CONSTRAINED_PTY, the agent verifies the permit's **canonical command hash** and never re-parses an arbitrary shell string.

---

## 4. Decision 3 — Two logical channels: CONTROL (never-drop) + DATA (drop-tolerant)

The agent↔broker tunnel carries at least two logical channels:
- **CONTROL** — `KILL`, `REVOKE`, `LEASE_RENEW`, `CONSENT_REVOKED`, permits. Never dropped. Ideally a **separate gRPC stream**; better, a **separate HTTP/2 connection** so a saturated VIEW_ONLY frame stream can never starve a KILL.
- **DATA** — VIEW_ONLY frames are **drop-tolerant** (latest-wins); PTY output is **ordered**.

**Sub-second KILL:** on `KILL` the broker **immediately** drops the console stream on its side and treats the session as revoked **without waiting for the agent ACK**. Independently, the agent holds a **short-lived lease** (renewed every 1–2 s); if the lease is not renewed (e.g. network partition with no push), the agent closes capture/PTY on its own. Push-KILL gives the sub-second target; the lease is the partition fail-safe. **Backpressure invariant (test):** a blocked DATA stream MUST NOT delay a CONTROL `KILL`.

---

## 5. Decision 4 — SessionContext wiring + data flow

The broker runs `RemoteSessionPolicyEngine.evaluate(SessionContext)` per session-start and per operation. Input ownership:

| `SessionContext` input | Produced by | Authoritative verifier |
|---|---|---|
| `certTrusted` | mTLS peer cert (agent) | Broker B1.2 PKIX/CRL/cert-binding |
| `attestationVerified` | Agent TPM/device evidence (`AgentHello`) | Broker B1.4d device-identity verifier |
| `deviceTrusted` | broker composition | Broker (`certTrusted && attestationVerified && enrollment/owner state && not-revoked`) |
| `StepUpState` | Operator-console WebAuthn ceremony | Broker/backend WebAuthn assertion verifier |
| `DuressSignal` | Operator duress signal + agent local-abort/duress event | Broker D-7 policy; agent local-abort = immediate local deny |
| `grantedCapabilities` | Owner-signed pilot token ∩ deviceScope ∩ operatorScope ∩ pilotAllowedSet (hard cap `{VIEW_ONLY, CONSTRAINED_PTY}`) | Broker |
| `RemoteOperation` | Operator-console action (normalized by the broker) | Broker |
| `commandLine` | Console command input → broker **canonical `commandId + argv[]`** parser | Broker; agent validates the permit's canonical hash |
| attended-consent state | Windows agent user-session UI | Agent emits, broker requires, agent can revoke locally |

**Flow:** agent boot (bridge default-disabled) → outbound mTLS gRPC `Connect()` → `AgentHello` (version, deviceId, cert fingerprint, platform facts, nonce response, TPM/device attestation evidence) → broker device verification → operator session request **to the broker** (operator never talks to the agent directly) → WebAuthn step-up → owner-pilot-token verification → endpoint consent prompt → `RemoteSessionPolicyEngine.evaluate` → short-lived signed **operation permit** (`decisionId, sessionId, operationId, capability, commandHash, expiresAt, seq, policyVersion`, mTLS-bound MAC / broker signature) → agent verifies the permit + applies (absent a local deny) → every policy decision / consent event / frame metadata / PTY command+output / kill event written to the C recording sink (agent emits local event-seq; broker folds them into the hash-chain).

---

## 6. Decision 5 — Attended-consent is a TRANSPORT PRECONDITION (state machine), not UX

The tunnel may be connected while idle, but **no VIEW_ONLY frame and no PTY channel opens before attended consent is live** (ADR-0034 D6). Session state machine:

`DISABLED → IDLE_CONNECTED → SESSION_REQUESTED → CONSENT_PENDING → CONSENT_GRANTED → ACTIVE → REVOKING/KILLED → CLOSED`

Minimum mechanism:
- The agent **Windows service** and the **user-session consent UI** are separate; a Session-0 service may not self-consent.
- The consent prompt shows: operator identity + organization, reason/ticket, requested capabilities, duration, **recording notice** (KVKK m.10), and the local-abort control.
- Consent grant is **session-bound** (`sessionId, operatorId, deviceId, capabilities, expiry, Windows interactive-session id`).
- A **persistent indicator** (topmost banner / tray) is mandatory whenever VIEW_ONLY or PTY is active; an indicator/consent **heartbeat** flows to the broker. If the indicator drops, the broker's `SessionContext` flips to deny and a KILL is sent.
- **Local abort is two-layer:** (1) the agent immediately stops capture/PTY; (2) it sends `LOCAL_ABORT` and the broker marks the session revoked.
- **Locked screen / user-switch / RDP secure desktop → default deny** (VIEW_ONLY blanks/stops, PTY stops).

---

## 7. Decision 6 — mTLS identity propagation = TLS passthrough / dedicated L4 (NOT edge-terminate-with-header)

The most critical transport risk is **mTLS termination + identity propagation**, not gRPC itself. The agent's mTLS MUST reach the broker pod (TLS passthrough / a dedicated L4 entrypoint) so the broker sees the **real peer cert**. If edge termination is unavoidable, the edge-verified peer-cert chain + fingerprint must be carried to the broker over a **cryptographically protected internal channel** — a plain trusted header is NOT sufficient (header-spoofing / identity-confusion).

---

## 8. Decision 7 — "Constrained PTY" stays a command gate, never a raw shell

The PTY pilot may feel like an interactive terminal, but for the operation gate **every executable command is normalized to `commandId + argv-schema + per-argument policy`** (the merged D-2/D-3 engine). Binding a raw keystroke stream to an arbitrary shell is **out of pilot scope**. The permit carries the canonical command hash; the agent runs the resolved command via direct process spawn (the D-2 no-shell executor invariant), never `cmd /c <string>`.

---

## 9. Decision 8 — Minimal first transport slice (disabled-by-default, no real screen/PTY)

**Safe to build now, pre-pilot-sign-off, Codex-reviewable, control-plane only:**
1. **ADR + protobuf contract** — `RemoteBridgeService.Connect`, `ControlFrame`, `DataFrame`, `ConsentPrompt`, `ConsentResult`, `PolicyDecision`, `OperationPermit`, `Kill`, `AuditEvent`; capability enum **only** `VIEW_ONLY`, `CONSTRAINED_PTY`.
2. **Broker skeleton** (Java `endpoint-admin-service`) behind `remote-bridge.enabled=false`; gRPC route unexposed in test/prod (no ingress/replica exposure); mTLS verifier integration unit-tested, no live exposure.
3. **Policy dry-run** — `RemoteSessionPolicyEngine.evaluate()` actually invoked with synthetic/mock operations; tests: no-cert→deny, no-attestation→deny, no-step-up→deny, no-owner-token→deny, no-consent→deny, unsupported-capability→deny, duress→kill, revoked-cert→deny.
4. **Go agent harness** — outbound gRPC idle connect + heartbeat + KILL-obey, **no real capture/PTY**; mock consent provider; feature-disabled ⇒ never connects; enabled-but-no-permit ⇒ no-op.
5. **Control-recording only** (consent-mock / decision / heartbeat / kill events to the hash-chain; no payload because there is no payload).
6. **Contract tests** — Java↔Go protobuf compatibility, sequence/replay protection, permit expiry, KILL-latency, the backpressure invariant.
7. **GitOps disabled shape** — manifests/env may exist but default `REMOTE_BRIDGE_ENABLED=false`, internal-only (or no) Service exposure, prod route firmly off.

**Gated behind the owner pilot sign-off (ADR-0034 §13/D10) — NOT in the first slice:** real attended-consent UI on a real endpoint; real VIEW_ONLY capture (desktop-duplication); real ConPTY/command execution; real WebAuthn operator step-up activation; real owner-signed pilot tokens; real device-TPM attestation acceptance against pilot devices; broker route test/prod ingress exposure; real recording-retention/WORM activation; any high-privilege operator session; pilot-device-list expansion.

---

## 10. Non-goals (explicit)

No arbitrary TCP reverse tunnel · no RDP/VNC passthrough · no file transfer · no clipboard sync · no unattended session · no shell without the command allowlist · no screen/control data before endpoint consent · **no production enablement by config drift — only an owner-gated change.**

---

## 11. Consequences

- **Positive:** a domain-specific gRPC/mTLS protocol keeps the policy engine, recording, and per-operation gate authoritative end-to-end; reuses B1.4 mTLS/PKI + B1.4d attestation + the merged `RemoteSessionPolicyEngine`; the first slice is fully buildable + reviewable now without any live remote-control surface.
- **Negative / cost:** the broker gRPC service + the Go agent transport are net-new; a separate control connection + lease machinery adds complexity; TLS-passthrough/L4 ingress is an infra requirement (no edge-terminate shortcut).
- **Risk if ignored:** adopting a generic reverse tunnel would re-open a privileged-ops path outside the policy engine — explicitly rejected (Decision 1).

---

## 12. Cross-AI provenance (HARD RULE — provider-distinct)

- **Architect:** Codex/OpenAI, thread `019eb9fb` (full architecture recommendation — gRPC/mTLS domain protocol, broker-authoritative-ALLOW + agent-authoritative-DENY, control/data channel split, SessionContext wiring, attended-consent precondition, mTLS-passthrough risk, minimal control-plane-only first slice).
- **Author/implementer:** Claude/Anthropic, thread `019eb874` (the merged B1+C+D security runway + `RemoteSessionPolicyEngine` this ADR's transport wires into).
- **Verdict:** ACCEPT gRPC/mTLS domain protocol; REJECT generic reverse tunnel; broker-authoritative ALLOW + agent-authoritative DENY; first slice control-plane only; no real screen/PTY until the owner pilot gate (ADR-0034 §13/D10).
