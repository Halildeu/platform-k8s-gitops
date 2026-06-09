# ADR-0034 — #1388 Sensitive Endpoint Ops Governance Gate: Owner Decision Record

> **Status:** PROPOSED — AWAITING OWNER / LEGAL SIGN-OFF (this record, once accepted, lifts the #1388 runtime gate for Faz 22.6 and is a prerequisite for 22.8)
> **Date:** 2026-06-09
> **Owner sign-off required:** Data Controller (Veri Sorumlusu) + Legal/Hukuk + İK (HR) + IT-Security lead
> **Design input:** 3-AI consensus — Codex/OpenAI `019ea9aa` + Mavis/MiniMax `mvs_c922505d66a94a45b031feb3489f9488` + Claude/Anthropic → [ADR-0033](./0033-faz-22-6-remote-access-bridge-broker.md)
> **Board:** gitops [#1388](https://github.com/Halildeu/platform-k8s-gitops/issues/1388) (sensitive endpoint ops governance gate, P0)
> **Pattern:** ADR-0030 (KVKK boundary) style decision record.

---

## 1. Context

Issue #1388 is the **Sensitive Endpoint Ops Governance Gate**: it blocks runtime for high-sensitivity endpoint capabilities — Faz **22.6** (interactive remote-access bridge) and Faz **22.8** (backup/offboarding/forensic file collection). These are not technical blockers; they are **legal/KVKK/policy decisions** that only the owner can make.

The *design* is settled (ADR-0033: broker, authz, token, audit/recording, threat model). This ADR-0034 is the **owner decision record**: the discrete legal/KVKK/policy choices that must be accepted (signed) before any live session opens. No engineering runtime work waits on this — only the live pilot does.

This record presents each decision with options + the **3-AI-recommended default**; the owner accepts, amends, or rejects each, then signs §13.

---

## 2. D1 — Legal basis (KVKK m.5)

Remote-session recording is personal-data processing requiring a lawful basis.

- **Options:** (a) açık rıza (explicit consent), (b) sözleşmenin ifası, (c) hukuki yükümlülük, (d) **meşru menfaat** (legitimate interest — corporate security/support).
- **3-AI default:** meşru menfaat (m.5/2-f) + sözleşme, **NOT consent-alone** (employee power-imbalance makes consent weak/revocable). İK + Hukuk signed policy + employee acknowledgment.
- **Owner decision:** ____________________

## 3. D2 — Notice / transparency (KVKK m.10 aydınlatma)

- **Requirement:** employees informed BEFORE processing; each session shows an endpoint-visible prompt (operator identity + reason/ticket + capability set + recording notice). Recording without prior notice violates m.10.
- **3-AI default:** standing aydınlatma metni (policy) + per-session attended prompt.
- **Owner decision:** ____________________

## 4. D3 — Recording mandate + retention (KVKK m.12 veri güvenliği)

- **3-AI default (consensus):** recording **MANDATORY + fail-closed** for the pilot (high-privilege attended-admin class). Retention: metadata/audit **7y immutable**, raw recording **30–90d** (pilot 90d) encrypted, transcript ≥ raw. WORM/object-lock + hash-chain.
- **Owner decision (retention days + storage):** ____________________

## 5. D4 — Special-category data (KVKK m.6)

- **Context:** screen content MAY contain özel-nitelikli veri (sağlık vb.) → triggers m.6 stricter regime *only if present*.
- **3-AI default:** treat recording as potentially containing m.6 data → encryption + RBAC + access-audit (ADR-0030 reuse); known-sensitive-app masking as a stretch goal.
- **Owner decision:** ____________________

## 6. D5 — Cross-border transfer (KVKK m.9)

- **Context:** m.9 applies ONLY if recordings/metadata are transferred abroad (e.g. non-TR cloud, OSS relay SaaS).
- **3-AI default:** keep all recording + relay **in-country / in-house**; no cross-border transfer → m.9 not triggered. If a foreign subprocessor is used, m.9 + DPA decision required (see D9).
- **Owner decision:** ____________________

## 7. D6 — Attended / unattended + break-glass policy

- **3-AI default (consensus):** pilot is **attended-only** (endpoint user present + consents). **Unattended + break-glass DEFERRED to a later phase** with a separate ADR — opening them in pilot de-facto bypasses this gate.
- **Owner decision:** ____________________

## 8. D7 — Pilot scope (named)

- **3-AI default:** 2–5 **IT-owned** devices; named requester(s), operator(s), approver(s). No BYOD / general-employee device.
- **Owner decision (device + people list):** ____________________

## 9. D8 — Capability classes for the pilot

- **3-AI default:** narrowest-first — **view-only screen-share OR an allowlisted constrained PTY**. File-transfer / clipboard-sync / credential-entry / elevation / generalized port-forward **OFF** for pilot.
- **Owner decision (allowed capability set):** ____________________

## 10. D9 — Third-party OSS / relay (DPA / subprocessor)

- **Context:** if a transport overlay (OpenZiti/zrok) or adapter (MeshCentral) involves a hosted/relay service, a DPA + subprocessor stance is needed.
- **3-AI default:** self-hosted OSS only (no SaaS relay) → no external subprocessor. Any SaaS path → DPA + D5 cross-border review first.
- **Owner decision:** ____________________

## 11. D10 — Acceptance gate (evidence before first live pilot)

Even after this record is signed, the **first live session** opens only after (ADR-0033 §7/§10):
- ADR-0033 ACCEPTED + broker negative-test evidence (self-approval deny / expired-replayed token deny / capability-mismatch deny / recorder-unavailable deny — all fail-closed).
- Recording fail-closed evidence (no `ACTIVE` without `RECORDING_READY`).
- D29-EA acceptance: **Up ≠ Functional ≠ Secured** proven separately.

## 12. Consequences

- **Positive:** a single signed record lifts #1388 for 22.6 (and informs 22.8); all engineering can proceed disabled-by-default in parallel meanwhile.
- **If unsigned:** 22.6/22.8 stay BLOCKED — design + skeleton + tests may land, but no live session.
- **Scope:** this record governs 22.6 remote access. 22.8 (backup/forensic file collection) reuses D1–D6/D10 but adds its own collection-scope decisions (separate addendum).

## 13. Owner sign-off

| Role | Name | Decision (accept / amend / reject) | Date |
|---|---|---|---|
| Data Controller (Veri Sorumlusu) | | | |
| Legal / Hukuk | | | |
| İK / HR | | | |
| IT-Security lead | | | |

> Until all four roles sign accept, #1388 remains OPEN and 22.6/22.8 runtime stays BLOCKED.

## 14. References

- Design: [ADR-0033](./0033-faz-22-6-remote-access-bridge-broker.md) (broker architecture/authz/token/audit/threat model)
- KVKK precedent: [ADR-0030](./0030-kvkk-meeting-intelligence-boundary.md)
- Charter: [ADR-0012-EA](./0012-EA-endpoint-admin-governance-charter.md)
- Plan: [`docs/faz-22-remote-access-bridge-plan.md`](../faz-22-remote-access-bridge-plan.md) §9.2 (owner-decision checklist)
- Gate: #1388 · downstream 22.6 (#510/#524/#1402/#116) + 22.8 (#1390/#117)
