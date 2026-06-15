# ADR-0040 — Faz 22.6 Break-glass offline domain-auth recovery (agent-mediated Kerberos-AS relay): Owner Decision Record

> **Status:** PROPOSED — awaiting owner sign-off (§9). This record does NOT lift any gate; it presents the owner the discrete legal/KVKK/policy + design choices for a **break-glass** capability that ADR-0034 D7 explicitly deferred to "a separate ADR". No engineering runtime work proceeds until the owner signs. A real-counsel KVKK review is recommended before any production (non-pilot) use.
>
> **Date:** 2026-06-15 (proposed)
> **Relationship:** extends [ADR-0033](0033-remote-access-bridge.md) (bridge design) + [ADR-0034](0034-1388-sensitive-endpoint-ops-owner-decision.md) (D7 unattended/break-glass DEFERRED; D8 pilot capability = VIEW_ONLY + constrained PTY). This is a **different capability plane** from D8 — D8 (interactive VIEW_ONLY pilot) is unchanged.
> **Cross-AI:** Claude (impl/draft) + Codex thread `019ecbc4` (design AGREE after REVISE). MiniMax/Mavis channel **unreachable at draft time** (consensus session not discoverable) — 2-AI, declared (not substituted).

## 1. Context — the problem this solves

A remote employee **not on the corporate/domain LAN** forgets their password:
1. Offline Windows logon validates against **cached domain credentials** (a one-way DCC2/MSCache-v2 hash of the LAST-known password).
2. The admin resets the password on the DC — but the **offline laptop never contacts a DC**, so the new password is never cached. The old (forgotten) password still gates the cache.
3. The user is locked out of **their own domain profile + files**. A **local account does NOT solve it**: different SID → no profile; NTFS ACLs bound to the domain SID; **EFS-encrypted files are unreadable by a local admin** (admin rights do not break EFS).

The only clean fix is the user logging into **their own domain account** while the machine can reach a DC **pre-logon** (so the new password authenticates + caches). The bridge agent is a SYSTEM service that runs before interactive logon, so it is positioned to carry that connectivity — but the *shape* of what it carries is a security + governance decision.

## 2. Why this is break-glass, not a D8 amendment

The trigger is a **locked-out user at the Windows logon screen** → no in-session consent is possible → this is **unattended / break-glass**, the exact class ADR-0034 **D7 deferred to a separate ADR**. D8 (interactive VIEW_ONLY pilot) governs a different, attended plane and stays as-is. Folding this into D8 would smuggle an unattended capability into an attended-only decision. Hence: a **new** owner-decision record.

## 3. BG-D1 — Capability mechanism (narrowest-first)

- **Options:** (a) generalized port-forward to DC ports; (b) DC-ports-only constrained port-forward (88/389/636/445/464/3268); (c) **agent-mediated, operation-specific Kerberos AS-REQ/AS-REP relay only**; (d) post-local-login cached-cred refresh.
- **3-AI recommendation (Codex `019ecbc4` AGREE):** **(c)** — relay ONLY the Kerberos `AS-REQ/AS-REP` exchange between the local LSA and **one allowlisted DC**. **NO SMB (445)** (Codex: materially raises relay/lateral-movement surface, zero value for password recovery), **NO generic TCP tunnel, NO PTY/shell, NO file-transfer.** `kpasswd (464)` is a **separate sub-capability behind its own policy + its own approval**, OFF by default (not part of the base recovery flow). Option (d) is rejected — it cannot help a user who cannot log in at all.
- **Target-user binding (BG-D1.1 — Codex review #2, critical):** the relay is bound to the **affected user's OWN locked domain principal** — the backend validates a required `target_user_context` + `principal` and an open relay servicing **any other account is denied + alarmed**. The capability recovers the locked user's own logon; it is never a lateral operation against a different account. (Closes wrong-account-targeting.)
- **Owner decision (pending):** ☐ accept (c) + BG-D1.1 / ☐ amend / ☐ reject.

## 4. BG-D2 — Legal basis (KVKK)

- m.5/2-f **meşru menfaat** (uzaktan çalışanın kendi verisine erişiminin sürekliliği + BT güvenliği) + **sözleşmenin ifası**; açık-rıza-değil. m.10 **aydınlatma:** the affected user gets **out-of-band notification** (the trigger is a locked screen, so an on-screen prompt is not reliably seen) + a ticket reference. m.12 **veri güvenliği:** §5 controls. No special-category data (m.6) is processed by an AS-REQ relay.
- **Owner decision (pending):** ☐ accept / ☐ amend / ☐ reject. **Prerequisite:** İK+Hukuk-signed break-glass policy text + employee acknowledgment (before first live use).

## 5. BG-D3 — Governance controls (all mandatory, fail-closed)

- **Default-closed + JIT** (the capability is dormant; opened only per-incident, time-boxed).
- **Dual-approval, maker≠checker:** `approval_id` + **incident ticket** + **operator identity** required; the requester cannot self-approve.
- **Single-DC target:** allowlisted DC **FQDN + certificate pin**; no wildcard, no DNS fallback, no arbitrary host.
- **Transport:** mTLS + **device attestation** + short-lived device cert (the Faz 22.3B / AD CS device identity is the anchor) + service-identity verification.
- **Bounds (measurable, Codex review #2):** session time-box (default ≤ 10 min) + idle-timeout (≤ 60 s) + **max-attempts** (default ≤ 5 AS-REQ per open) + per-open + per-device rate-limit + exponential backoff + cooldown after a failed open + consecutive-fail lockout; **any threshold breach → fail-closed + alarm** (escape-from-closed-mode is itself an alarmable event).
- **Kill-switch (full behavior, Codex review #2):** central instant-off ⇒ (1) active relaying **stops** mid-flight, (2) **no new** sessions open, (3) active binding/approval tokens **revoked**, (4) in-flight buffers/queues **dropped** (no egress), (5) a mandatory ops-audit entry is produced. Instant-off is itself audited.
- **Attack-surface limit:** AS-REQ exchange only; **anti-replay (nonce + bounded window) + operation-signing/verification + network-identity binding** (Codex: AS-REQ is narrower than SMB but not zero-risk — a restricted auth endpoint reachable remotely invites brute-force/replay; these controls + the BG-D3 thresholds close it).
- **Owner decision (pending):** ☐ accept / ☐ amend / ☐ reject.

## 6. BG-D4 — Audit (non-screen equivalent of the recording mandate)

A Kerberos/LDAP relay carries encrypted auth — it cannot be "screen-recorded". The audit equivalent (ADR-0034 D3 spirit):
- **Lifecycle log per open:** who opened, duration, which DC (FQDN), protocol, target user-context, `approval_id`, incident ticket, **outcome** (success/fail), and the **policy hash / evidence** under which it was authorized.
- → **immutable SIEM + tamper-proof (WORM/object-lock + hash-chain) archive**, metadata/audit **7y** (matching ADR-0034 D3).
- **Audit-data privacy (BG-D4.1 — Codex review #2):** the audit log is itself KVKK-scoped → **field minimization** (operational metadata only — IDs, FQDN, timings, outcome; **NO raw Kerberos payload** retained, except a time-boxed red-team sample under separate authorization), **least-privilege log access** (named SIEM/audit roles only), and **periodic log-access review**. The relay processes auth in transit but **persists no credential material**.
- **Owner decision (pending):** ☐ accept + BG-D4.1 / ☐ amend / ☐ reject.

## 7. BG-D5 — Acceptance gate (evidence before first live use)

Mirrors ADR-0034 D10. The capability stays disabled until ALL land with evidence:
1. Negative tests, all fail-closed: self-approval deny / expired-or-replayed approval-token deny / non-allowlisted-DC deny / wrong-DC-cert-pin deny / AS-REQ-replay deny / time-box + max-attempts cutoff / kill-switch instant-off.
2. mTLS + device-attestation enforced (untrusted/unattested device → deny).
3. Out-of-band user notification path proven.
4. Immutable audit chain proven (lifecycle log → WORM, tamper-evident).
5. İK+Hukuk break-glass policy text + employee acknowledgment in place.
6. Independent cross-AI red-team absorb (relay/replay/brute-force surface).

**Acceptance sign-off rollup (single-page, BG-D5.1 — Codex review #2/#3):** before first live use, record in one place — **who approved** (all 4 §9 roles), **which negative-test scenarios passed**, **which incident/ticket traced** the enablement, **effective date**, the **rollback plan + rollback success measure** (capability re-disabled → relays stop → tokens revoked → verified no residual egress), plus two fixed auditable fields: (a) **evidence-artifact format** — each evidence/test link carries its **SHA-256**; (b) **authoritative DC-target list** — a **single signed source** (referenced by hash), never an ad-hoc inline list. First live use is invalid without this rollup complete.
- **Owner decision (pending):** ☐ accept + BG-D5.1 / ☐ amend / ☐ reject.

## 8. Consequences

- **If accepted:** unblocks a disabled-by-default, break-glass, agent-mediated AS-REQ-relay capability whose engineering may then proceed (gate-by-gate, cross-AI, CI-green) on top of the existing 22.6 bridge transport. First live use still requires §7. D8 (VIEW_ONLY pilot) is untouched.
- **If rejected/deferred:** the offline-domain-recovery use-case remains unsolved by the platform; the operational fallback stays a pre-logon VPN device-tunnel to a DC (separate infra) or a cloud-trust identity migration (larger architectural change). Local-account break-glass remains for machine-admin tasks only (not user-file access — SID/EFS).
- **Scope discipline:** this record authorizes ONLY the AS-REQ-relay recovery capability. Generalized port-forward, RDP, file-transfer, credential-entry, and elevation remain OFF (ADR-0034 D8) and out of scope here.

## 9. Owner sign-off

| Role | Name | Decision (accept / amend / reject) | Date |
|---|---|---|---|
| Data Controller (Veri Sorumlusu) | Halil Koçoğlu (Halildeu, owner) | ☐ PENDING | — |
| Legal / Hukuk | Halil Koçoğlu (single-owner pre-prod; real-counsel review recommended) | ☐ PENDING | — |
| İK / HR | Halil Koçoğlu (single-owner pre-prod) | ☐ PENDING | — |
| IT-Security lead | Halil Koçoğlu (single-owner pre-prod) | ☐ PENDING | — |

> Until all four roles sign, this capability has NO engineering runtime authorization. (ADR-0034 §13 pattern.)

## 10. References

- [ADR-0033](0033-remote-access-bridge.md) (bridge design) · [ADR-0034](0034-1388-sensitive-endpoint-ops-owner-decision.md) (D7 deferred break-glass; D8 VIEW_ONLY pilot) · [ADR-0039](0039-faz-22-3b-tpm-attestation-vault-pki.md) (device identity anchor).
- Backlog issue [#1576](https://github.com/Halildeu/platform-k8s-gitops/issues/1576) (offline-DC origin).
- Cross-AI: Codex thread `019ecbc4` (REVISE → AGREE: drop raw port-forward + SMB; AS-REQ-relay-only; break-glass not D8-amendment).
- EFS note: deploy a **DRA (Data Recovery Agent)** key as insurance for EFS-encrypted files independent of this capability.
