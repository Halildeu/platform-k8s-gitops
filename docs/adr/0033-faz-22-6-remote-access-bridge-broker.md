# ADR-0033 — Faz 22.6 Remote Access Bridge: Broker Architecture, Authz & Governance Gate

> **Status:** PROPOSED (agent-actionable design accepted; runtime BLOCKED by #1388 owner/legal decision)
> **Date:** 2026-06-09
> **Deciders:** 3-AI consensus — Codex/OpenAI (thread `019ea9aa`) + Mavis/MiniMax (session `mvs_c922505d66a94a45b031feb3489f9488`) + Claude/Anthropic
> **Board:** gitops [#1388](https://github.com/Halildeu/platform-k8s-gitops/issues/1388) (governance gate, P0) · [#1402](https://github.com/Halildeu/platform-k8s-gitops/issues/1402) (broker ADR) · [#1401](https://github.com/Halildeu/platform-k8s-gitops/issues/1401) (transport POC) · backend [#510](https://github.com/Halildeu/platform-backend/issues/510)/[#524](https://github.com/Halildeu/platform-backend/issues/524) · agent [#116](https://github.com/Halildeu/platform-agent/issues/116)
> **Plan:** [`docs/faz-22-remote-access-bridge-plan.md`](../faz-22-remote-access-bridge-plan.md) · supersedes its §4 "Hedef Mimari" with the detailed state machine/token/audit below.

---

## 1. Context

Faz 22.6 introduces an **agent-initiated, outbound-only persistent reverse tunnel** that lets an operator open a **bounded, interactive, high-privilege remote-support session** (constrained PTY / RDP relay) into a managed Windows endpoint. This is a fundamentally different security class from the read-only inventory/visibility surfaces (22.5 software deployment, 22.7 Compliance Gap Mart — already COMPLETED outside this gate): it is a **live interactive access channel** carrying real privacy (KVKK), abuse, and credential-exposure risk.

Because of that, 22.6 runtime is **BLOCKED by the Sensitive Endpoint Ops Governance Gate (#1388)**: no live session may open until the owner/legal decisions (legal basis, retention, attended/unattended policy, pilot scope, capability classes) are accepted. This ADR records the **design + governance decisions** that ARE settled now (so the agent-actionable work can proceed without opening any runtime), and explicitly fences the parts that remain an owner/legal decision.

This ADR is the output of a **provider-distinct 3-AI consultation** (HARD RULE Cross-AI). All three providers independently converged on the decisions below; the single divergence (KVKK recording mandatory-vs-tiered) is resolved in §8.

Reuses existing platform primitives: OpenFGA Zanzibar authz plane, Vault+ESO secrets, endpoint-admin dual-control + maintenance-token + HMAC signed agent wire-contract (BE-011/BE-013/BE-016/BE-017), and ADR-0030 (KVKK boundary for recording-as-personal-data).

---

## 2. Decision 1 — Build-vs-Buy = HYBRID (3/3 consensus)

The platform owns the **security decision surface**; OSS is used only for commodity transport/protocol/render. Adopting a full remote-access product (MeshCentral/RustDesk) as the *core* is rejected — it brings its own authz/permission model and a wrapper that, if pierced, bypasses #1388.

| Layer | Decision | Rationale |
|---|---|---|
| Broker: policy, session state machine, **OpenFGA authz**, dual-control (no self-approval), audit schema, retention, redaction, kill-switch | **BUILD** | Platform's security authority. Reuse BE-017 dual-control + OpenFGA + Vault discipline. |
| Token minting: cert-bound / device-bound short-lived single-use session credential, capability allowlist | **BUILD** | Token replay / pass-the-hash / capability false-advertising are solved here, not in OSS. |
| **Session recording core** (capture, hash-chain, retention, access) | **BUILD** | KVKK m.12 chain-of-custody + redaction; 3rd-party record SaaS unacceptable. |
| Outbound-only tunnel transport / overlay | **WRAP candidate: OpenZiti / zrok class** | Reverse multiplexed tunnel is high-risk to hand-roll; identity/policy still derives from the broker, not the OSS tool. |
| Protocol render + recording codec (RDP/VNC/SSH → HTML5) | **WRAP candidate: Apache Guacamole as a *dumb adapter behind the broker*** | RDP/VNC rendering maturity. Guacamole must NEVER be session authority and must never see a target until the broker authorizes + opens the tunnel (i.e. not the agentless gateway model the plan §2.1 rejects). |
| Full suite: MeshCentral / RustDesk | **EVAL baseline only, NOT production core** | Own agent/auth/relay/permission model; deep wrapper required; pierce = governance bypass. |

> Refinement vs plan §2.1: adds **OpenZiti/zrok** as the tunnel-overlay candidate and reframes **Guacamole** as a behind-the-broker protocol adapter (not the rejected agentless-gateway path). MeshCentral stays a transport-adapter POC (#1401), broker core stays BUILD (#1402).

`build_vs_buy: hybrid`

---

## 3. Decision 2 — Broker Session State Machine

```
REQUESTED → POLICY_EVALUATING → PENDING_TARGET_CONSENT → PENDING_DUAL_APPROVAL
  → APPROVED → TOKEN_ISSUED → AGENT_CONNECTED → OPERATOR_CONNECTED
  → RECORDING_READY → ACTIVE → ENDING → ENDED
```

Terminal / exception states: `DENIED`, `EXPIRED`, `REVOKED`, `ABORTED`, `FAILED_POLICY`, `FAILED_RECORDING`, `FAILED_AGENT_ATTESTATION`.

**ACTIVE invariant (fail-closed):** a session may enter `ACTIVE` **only if** policy=allow ∧ target-consent ∧ dual-approval ∧ token bound ∧ agent attestation ∧ recording-writer ack. If any precondition is missing the session stays `PENDING_*` or transitions to a `FAILED_*` terminal — **no interactive channel opens**. Transitions are idempotent + monotonic; terminal states irreversible; **abort beats connect**.

---

## 4. Decision 3 — OpenFGA `remote_session` Authz Model

Authz lives in the **same Zanzibar plane** as the rest of the platform (no ad-hoc authz):

```
type remote_session
  relations
    define target_device: [endpoint_device]
    define requester: [user]
    define approver: [user]            # must differ from requester (no self-approval)
    define operator: [user]            # joins the active session
    define can_request: [user]         # gated by endpoint-admin MODULE manage
    define can_approve: [user]         # distinct grant; proposer ≠ approver enforced
    define capability: [capability]    # per-session allowlist (broker-computed, agent can only downscope)
```

- Reuses BE-017 dual-control semantics: `approver != requester`, enforced as a **server-side invariant + regression test** — OpenFGA models the grants (`can_request`/`can_approve`), but the `≠` inequality between two principals is NOT expressible at the tuple level and must be a broker-side check.
- Capability set is **broker-computed**; the agent's advertised capabilities are a *signal only*, never authority (false-advertising guard).
- Runtime revoke → emits an authz event AND **kills the live session** (capability-drift guard).

---

## 5. Decision 4 — Session Token Contract

- **Single-use**, short TTL (**≤ 4h hard cap**, pilot default shorter), `jti` replay-cache enforced.
- **Bound to**: session_id + target_device_id + operator + audience; **mTLS / cert-bound**, non-exportable (TPM/HSM-backed where available) → cannot be proxied to another agent (pass-the-hash guard).
- **No reusable admin credential** ever handed to the agent.
- Revoke / abort propagates immediately → token invalid + session killed.

---

## 6. Decision 5 — Audit + Recording Schema (KVKK m.12 chain-of-custody)

Every session emits an immutable, hash-linked audit record:

`session_id, org_id/tenant_id, target_device_id, agent_id, agent_cert_thumbprint, agent_binary_digest, requester_user_id, approver_user_id, target_user_ack, capability_set_requested, capability_set_approved, legal_basis, reason/ticket, token_jti, token_kid, state_from/to, event_time, operator_ip_hash, recording_object_uri, recording_manifest_hash, chunk_hash_root, abort_reason, retention_class`

- **Recording is atomic with the session**: `RECORDING_READY` ack is a precondition of `ACTIVE`; recorder failure → `FAILED_RECORDING` (fail-closed). Clean start/stop bracketing closes the chain-of-custody gap.
- Recording stored in-house, **encrypted at rest, WORM / object-lock + hash-chained chunks + immutable manifest**; audit links to `recording_manifest_hash`.
- Disconnect handling: heartbeat TTL + clean abort metadata log (no orphaned-recording window).

---

## 7. Decision 6 — #1388 Minimum Safe Runtime Set (first 2–5 device pilot)

A FIRST pilot may open runtime **only** with ALL of:

- **Scope**: 2–5 **named IT-owned** devices, named pilot users / operators / approvers, allowlisted capability set. No BYOD / general-employee device.
- **Attended-only**: endpoint-visible consent prompt (operator identity + reason + capability + recording notice) + explicit approve; default attended.
- **Per-session dual-control**: requester ≠ approver, self-approval impossible (BE-017).
- **Mandatory fail-closed recording** (see §6+§8).
- **Token**: §5 (single-use, ≤4h, cert/device-bound).
- **Outbound-only**: endpoint opens no inbound port.
- **Exfil controls OFF for pilot**: no file transfer, clipboard sync, unattended elevation, credential entry, background persistence, generalized port-forward.
- **Narrowest-first capability** (Claude): start with view-only screen-share OR an allowlisted constrained PTY — NOT full RDP/file-transfer.

**Unattended / break-glass are DEFERRED to a later phase** (not optional — opening them in pilot would de-facto bypass #1388).

`pilot_ready_after_owner_decision: no` — runtime needs #1388 accepted + this ADR accepted + implementation negative-tests + recording fail-closed evidence.

---

## 8. Decision 7 — KVKK Recording, Retention & Consent

The 3-AI divergence (Codex/Claude "mandatory" vs Mavis "risk-tiered") **resolves as**: the first pilot is by definition high-privilege attended-admin → **recording is MANDATORY (3/3) for the pilot**. Risk-tiering applies only if a *future* separate **low-risk view-only / no-input** capability class is introduced (Mavis's tier model, recorded as future option — not pilot scope).

| Data class | Retention | Access |
|---|---|---|
| Session metadata / audit | 7y immutable | Security / legal / audit role (event record, not content) |
| Raw PTY/RDP recording | 30–90d encrypted (pilot 90d) | Incident-responder + IT-Security-lead + Data-Controller only; per-segment access audited (who/when/which segment) |
| Transcript / command timeline | ≥ raw retention (legal-decided) | ≥ raw strictness (more searchable) |
| Security-incident / legal-hold | explicit, reasoned, audited | legal hold |

- Screen content can contain **KVKK m.6 özel nitelikli veri** (sağlık vb.) plus credentials / customer PII / ticari sır → recording inherits ADR-0030's encryption + RBAC + access-audit. (m.6 applies only when special-category data is actually present.)
- **Legal basis**: KVKK m.5 işleme şartı — employee consent alone is weak (power imbalance) → owner/legal selects meşru menfaat / sözleşme / hukuki yükümlülük; İK + Hukuk signed policy + employee acknowledgment. Recording without prior notice violates the **m.10 aydınlatma yükümlülüğü** (transparency/notice duty). Cross-border transfer of recordings (if any) is a separate **m.9** decision.

---

## 9. Decision 8 — Threat Model (STRIDE) + Guards

| Threat | Guard |
|---|---|
| Token replay | jti replay-cache, mTLS binding, session/device/audience binding, one-time connect, ≤4h TTL, revoke propagation |
| Capability false-advertising | broker computes allowed set; agent can only downscope; signed agent build + cert posture + negative tests |
| Session hijack | separate operator-channel auth, ws origin/CSRF checks, per-channel nonce, re-auth for sensitive action, no bearer in URL/logs |
| Recording tamper / drop | hash-chained chunks, immutable manifest, WORM/object-lock, fail-closed if writer unavailable |
| Broker as new attack surface | no general TCP relay by default, per-session egress ACL, namespace isolation + NetworkPolicy, rate limits, no ambient admin creds |
| Confused deputy | approval binds exact target + capability + actor + TTL; not reusable for another device/session/capability |
| Pass-the-hash | token non-exportable, device-bound; no reusable admin cred to agent |

### 9b. Red-team absorb (Codex 019eb54b, 2026-06-11) — guards added vs mature PAM

The cross-AI security audit (RED-for-live-pilot) surfaced gaps under-covered above. These guards are **mandatory before the first live pilot** (folded into ADR-0034 §11/D10):

| Threat (added) | Guard |
|---|---|
| **Mid-session capability/policy drift (TOCTOU)** | the ACTIVE invariant is NOT only an activation-time check — a **continuous re-evaluation heartbeat** re-validates policy=allow ∧ token-valid ∧ consent-held ∧ dual-approval-valid ∧ recorder-healthy every ≤N s; any failure → **immediate kill** (ACTIVE→ENDING/ABORTED), fail-closed. The skeleton exposes a pure `reevaluateActive(pre)` policy hook the runtime heartbeat consumes. |
| **Audit tampering after broker compromise** | audit/recording integrity does NOT live only in the broker: events stream to an **out-of-band, broker-independent, append-only, signed sink** (separate collector + hash-chain + WORM); the broker holds no key that can rewrite history. Audit is verifiable even if the broker is owned. |
| **Real-time revocation latency** | revoke/abort propagates to a **global deny-list** consulted by the heartbeat; kill-switch latency is an SLO with a negative test (revoke → session dead within the window). |
| **Token-validation oracle / enumeration / retry-DoS** | the validator's distinct decisions are **internal/audit-only**; the wire response is a **single uniform `DENIED` with constant-time** behavior. Layered rate-limit + per-(ip,operator,session) throttle; parse-vs-validate distinction is not externally observable. |
| **VIEW_ONLY is itself an exfil/privacy channel** | read-only screen-share is NOT "safe by recording alone": endpoint-side **DLP/known-sensitive-app screen masking**, per-session **watermark**, a **visible 'remote-support active' indicator**, a **user local-abort/kill control**, and a per-session content policy. |
| **Endpoint-user coercion** | visible session indicator + always-available **local kill** + coercion-resistant consent UX (out-of-band confirm option); consent is revocable mid-session → kill. |
| **Agent supply-chain / code integrity** | "signed build" is insufficient alone → **SBOM + SLSA provenance + reproducible build + runtime binary-hash attestation + cert posture**, with auto-rollback on attestation mismatch (feeds `agentAttestation` precondition). |
| **PKI / clock dependence** | mTLS needs full **cert lifecycle** (CRL/OCSP, rotation, non-exportable TPM/HSM key) and the ≤4h TTL needs **trusted/monotonic time** (NTP integrity) — TTL must not be defeatable by clock skew. |
| **Insider operator collusion / approval fatigue** | dual-control is necessary not sufficient: **canonical IAM identity** (alias/proxy/service-account resolution before approver≠requester), approval-fatigue limits, and out-of-band incident review of approvals. |

---

## 10. Decision 9 — Unblock Sequencing

**Owner / legal (cannot proceed without owner — gates runtime):** KVKK scope — m.5 işleme şartı (legal basis) + m.10 aydınlatma + m.12 veri güvenliği (recording = personal-data processing); m.6 only if özel-nitelikli veri present; m.9 only if cross-border transfer · legal basis + aydınlatma/consent · attended vs unattended + break-glass policy · named pilot device/user/operator/approver list · capability classes (view-only / PTY / RDP / file-transfer / clipboard / elevation) · third-party OSS/relay DPA/subprocessor stance.

**Agent-actionable NOW (no runtime opened) — proceed in parallel:**
1. This ADR-0033 (broker design + governance) — DONE.
2. `#1402`/`#524` broker skeleton: state-machine + OpenFGA model + token contract + audit schema, **`ENABLE_REMOTE_SUPPORT=false` disabled-by-default**, tests only.
3. OSS evaluation matrix refinement (#1400/#1401) — add OpenZiti/zrok + Guacamole-as-adapter; bypass-risk per tool.
4. Threat model (§9) → test plan: self-approval deny, expired/replayed token deny, capability mismatch deny, recorder-unavailable deny.
5. KVKK retention policy draft (§8) + #1388 owner-decision checklist (in plan doc).
6. Synthetic loopback tunnel spike (#116) — lab/synthetic ONLY; connecting to a managed Windows endpoint counts as runtime → gated.

**Pipeline:** #1388 owner/legal accept → ADR-0033 ACCEPTED → OSS selection → broker impl + negative-test evidence → recording fail-closed evidence → first attended pilot.

---

## 11. Consequences

- **Positive:** governance-first design lets all non-runtime work proceed now; reuses OpenFGA/Vault/BE-017/ADR-0030 (no new authz/secret/recording paradigm); the security decision surface stays platform-owned even if OSS transport is wrapped.
- **Negative / cost:** broker is net-new build (state machine + token + audit + recording); recording infra (WORM storage + access-audit) has ops cost; legal/KVKK review is on the critical path (owner-bound).
- **Risk if ignored:** adopting an OSS remote-access product as core would open a second privileged-ops domain outside #1388 — explicitly rejected.

---

## 12. Cross-AI provenance (HARD RULE — provider-distinct)

- **Codex / OpenAI** — thread `019ea9aa-345e-70d1-acf9-64df48a57d5f`: hybrid, build core + wrap transport (OpenZiti/zrok) + Guacamole-as-protocol-adapter; pilot_ready=no; state machine + audit schema + pitfalls; recording mandatory for high-privilege class.
- **Mavis / MiniMax** — session `mvs_c922505d66a94a45b031feb3489f9488`: hybrid, recording core in-house (KVKK m.12); pilot_ready=no; token bound-to-session-not-agent, recording atomicity, capability-drift kill, syscall-level redaction; risk-tiered KVKK (resolved → mandatory for pilot, tier=future low-risk class).
- **Claude / Anthropic**: hybrid reusing OpenFGA `remote_session` + BE-017 + Vault; narrowest-first capability; D29-EA Secured tier; broker separate deployment + NetworkPolicy + WORM recording.

## 13. References

- Plan: [`docs/faz-22-remote-access-bridge-plan.md`](../faz-22-remote-access-bridge-plan.md)
- Governance: ADR-0012-EA (endpoint-admin charter), ADR-0030 (KVKK recording boundary), ADR-0029 (mass-deployment mTLS/AD CS)
- Gate: #1388 (sensitive endpoint ops governance gate) — 22.6 + 22.8 runtime prerequisite
