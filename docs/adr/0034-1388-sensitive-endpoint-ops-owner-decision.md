# ADR-0034 — #1388 Sensitive Endpoint Ops Governance Gate: Owner Decision Record

> **Status:** ACCEPTED — owner-signed 2026-06-11 (single-owner pre-prod; all four roles signed by the Data Controller per §13). This record lifts the #1388 **engineering** gate for Faz 22.6 + 22.8 (disabled-by-default build may proceed); the **first live session** still requires the §11/D10 acceptance gate. A real-counsel legal review of the KVKK basis is recommended before any production (non-pilot) rollout.
> **Date:** 2026-06-09 (proposed) → 2026-06-11 (owner-accepted)
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
- **Owner decision (2026-06-11):** ✅ ACCEPT default — **meşru menfaat (KVKK m.5/2-f) + sözleşmenin ifası**, açık-rıza-değil. Prerequisite: İK+Hukuk imzalı politika metni + çalışan bilgilendirme/acknowledgment kaydı (canlı pilottan önce).

## 3. D2 — Notice / transparency (KVKK m.10 aydınlatma)

- **Requirement:** employees informed BEFORE processing; each session shows an endpoint-visible prompt (operator identity + reason/ticket + capability set + recording notice). Recording without prior notice violates m.10.
- **3-AI default:** standing aydınlatma metni (policy) + per-session attended prompt.
- **Owner decision (2026-06-11):** ✅ ACCEPT default — standing aydınlatma metni (politika) + her oturumda endpoint'te görünür attended uyarı (operatör kimliği + sebep/ticket + yetenek seti + kayıt bildirimi).

## 4. D3 — Recording mandate + retention (KVKK m.12 veri güvenliği)

- **3-AI default (consensus):** recording **MANDATORY + fail-closed** for the pilot (high-privilege attended-admin class). Retention: metadata/audit **7y immutable**, raw recording **30–90d** (pilot 90d) encrypted, transcript ≥ raw. WORM/object-lock + hash-chain.
- **Owner decision (2026-06-11, retention days + storage):** ✅ ACCEPT default — kayıt **ZORUNLU + fail-closed** (`RECORDING_READY` olmadan oturum `ACTIVE` olmaz). Saklama: metadata/audit **7y immutable**, ham kayıt **90 gün** şifreli (pilot), transcript ≥ ham. Depolama: **WORM / object-lock + hash-chain**, in-house (bkz. D5).

## 5. D4 — Special-category data (KVKK m.6)

- **Context:** screen content MAY contain özel-nitelikli veri (sağlık vb.) → triggers m.6 stricter regime *only if present*.
- **3-AI default:** treat recording as potentially containing m.6 data → encryption + RBAC + access-audit (ADR-0030 reuse); known-sensitive-app masking as a stretch goal.
- **Owner decision (2026-06-11):** ✅ ACCEPT default — kayıt potansiyel m.6 verisi sayılır → şifreleme + RBAC + erişim-audit (ADR-0030 reuse). Bilinen-hassas-uygulama maskeleme stretch goal.

## 6. D5 — Cross-border transfer (KVKK m.9)

- **Context:** m.9 applies ONLY if recordings/metadata are transferred abroad (e.g. non-TR cloud, OSS relay SaaS).
- **3-AI default:** keep all recording + relay **in-country / in-house**; no cross-border transfer → m.9 not triggered. If a foreign subprocessor is used, m.9 + DPA decision required (see D9).
- **Owner decision (2026-06-11):** ✅ ACCEPT default — tüm kayıt + relay **yurt içi / in-house**; yurtdışı aktarım yok → m.9 tetiklenmez. Yabancı subprocessor kullanılmayacak (bkz. D9).

## 7. D6 — Attended / unattended + break-glass policy

- **3-AI default (consensus):** pilot is **attended-only** (endpoint user present + consents). **Unattended + break-glass DEFERRED to a later phase** with a separate ADR — opening them in pilot de-facto bypasses this gate.
- **Owner decision (2026-06-11):** ✅ ACCEPT default for **interactive remote-access (22.6)** — pilot **attended-only**; unattended + break-glass DEFERRED (separate ADR). Note: the automated **offboarding/audit file-copy** flow approved under D8 is a *non-interactive scheduled/triggered job* (not an unattended interactive remote session) and is governed by its own scenario-based dual-approval (see D8), not by this attended-session rule.

## 8. D7 — Pilot scope (named)

- **3-AI default:** 2–5 **IT-owned** devices; named requester(s), operator(s), approver(s). No BYOD / general-employee device.
- **Owner decision (2026-06-11, device + people list):** ✅ ACCEPT default framing — **2–5 IT-owned devices, no BYOD**. The concrete named device + requester/operator/approver roster is **operational** and will be recorded at pilot kickoff (before the first live session, as part of the §11/D10 acceptance gate). Lab candidates: the existing IT-owned Parallels/agent-managed Windows hosts (e.g. HALILKOOLUB735, MKR-A1). Maker ≠ checker enforced per ADR-0033.

## 9. D8 — Capability classes for the pilot

- **3-AI default:** narrowest-first — **view-only screen-share OR an allowlisted constrained PTY**. File-transfer / clipboard-sync / credential-entry / elevation / generalized port-forward **OFF** for pilot.
- **Owner decision (2026-06-11) — AMENDED (split into two capability planes):**
  - **22.6 interactive remote session (live operator):** ✅ keep the narrow default — **view-only screen-share + allowlisted constrained PTY only**. Free-hand in-session file-transfer / clipboard-sync / credential-entry / elevation / port-forward remain **OFF** for the pilot.
  - **22.8 file-copy (audit + offboarding / işten-çıkış):** ✅ **APPROVED as a separate, non-interactive, automated capability** — owner explicitly wants file-copy enabled for **audit and offboarding scenarios**, **fully automated and bound to a scenario-based dual-approval flow** (not free operator access). Mandatory governance for this plane (all already required by #1388 acceptance + ADR-0033):
    - **Scenario-bound:** only the named scenarios (employee offboarding copy, audit/forensic evidence collection) — no ad-hoc browse-and-pull.
    - **Dual-control:** requester ≠ approver (maker-checker); per-scenario approval before any copy job runs; abort on objection / scope-expansion / excessive-volume.
    - **Chain-of-custody:** SHA256 manifest + immutable evidence bundle (#1388 acceptance) + append-only audit (actor/approver/device/reason/scope/job-id/result/evidence-link).
    - **Retention:** offboarding/forensic artifacts per D3 (7y metadata; artifact retention set in the 22.8 addendum) + encryption + RBAC (D4) + in-house only (D5).
    - **Transparency:** offboarding copy disclosed per İK policy + D2 aydınlatma.
  - **Consequence:** this decision **activates the 22.8 collection-scope** (offboarding + audit file-copy) as owner-approved, gated behind the scenario dual-approval flow. The remaining 22.8 detail (exact path/filetype allowlist, volume caps, masking) is the **22.8 collection-scope addendum** to this record (separate, before 22.8 live). Generalized backup of arbitrary employee files outside the named scenarios is **NOT** approved here.

## 10. D9 — Third-party OSS / relay (DPA / subprocessor)

- **Context:** if a transport overlay (OpenZiti/zrok) or adapter (MeshCentral) involves a hosted/relay service, a DPA + subprocessor stance is needed.
- **3-AI default:** self-hosted OSS only (no SaaS relay) → no external subprocessor. Any SaaS path → DPA + D5 cross-border review first.
- **Owner decision (2026-06-11):** ✅ ACCEPT default — **self-hosted OSS only, no SaaS relay** → no external subprocessor. Any future SaaS path requires a DPA + D5 cross-border review first.

## 11. D10 — Acceptance gate (evidence before first live pilot)

Even after this record is signed, the **first live session** opens only after (ADR-0033 §7/§10 + §9b red-team absorb, Codex `019eb54b`):

**Original gate:**
- ADR-0033 ACCEPTED + broker negative-test evidence (self-approval deny / expired-replayed token deny / capability-mismatch deny / recorder-unavailable deny — all fail-closed).
- Recording fail-closed evidence (no `ACTIVE` without `RECORDING_READY`).
- D29-EA acceptance: **Up ≠ Functional ≠ Secured** proven separately.

**Expanded must-land (red-team absorb — pilot BLOCKED without each):**
1. **Continuous re-evaluation + real-time kill** — heartbeat re-validates policy/token/consent/dual-approval/recorder mid-session; negative test: revoke → session dead within the kill-switch SLO window.
2. **Out-of-band signed audit/recording sink** — broker-independent, append-only, hash-chained, WORM; integrity verifiable with the broker assumed compromised.
3. **mTLS + non-exportable (TPM/HSM) cert-bound token + PKI lifecycle** (CRL/OCSP/rotation) + **trusted/monotonic clock** (TTL not defeatable by skew).
4. **Atomic distributed jti store** (Redis SETNX / DB unique) proven under concurrency + **uniform `DENIED` constant-time** wire response + layered rate-limit (no oracle/enumeration/retry-DoS).
5. **Agent attestation depth** — SBOM + SLSA + reproducible build + runtime binary-hash + cert posture, auto-rollback on mismatch (feeds `agentAttestation`).
6. **VIEW_ONLY exfil controls** — endpoint-side DLP/screen-masking, watermark, visible 'remote-support active' indicator, user local-abort, per-session content policy.
7. **Endpoint-user coercion UX** — visible indicator + always-available local kill + revocable-mid-session consent.
8. **Broker hardening** — separate deployment, NetworkPolicy + per-session egress ACL + namespace isolation, no ambient admin creds, secrets separation.
9. **Operator-channel hardening** — separate auth, FIDO2/device-posture, ws origin/CSRF, per-channel nonce, no bearer in URL/logs, re-auth/per-action MFA.
10. **IAM identity canonicalization** for dual-control (alias/proxy/service-account resolved before approver≠requester) + approval-fatigue limits.
11. **Red-team drill report** — broker-compromise sim, jti replay, recorder-down→fail-closed, token theft, NTP skew, key leak/rotation — all pass.

> These were RED-flagged by an independent cross-AI audit; the disabled-by-default control-plane skeleton (platform-backend#524) is a sound start but is NOT a pilot. No live session opens until all of the above have evidence.

## 12. Consequences

- **Positive:** a single signed record lifts #1388 for 22.6 (and informs 22.8); all engineering can proceed disabled-by-default in parallel meanwhile.
- **If unsigned:** 22.6/22.8 stay BLOCKED — design + skeleton + tests may land, but no live session.
- **Scope:** this record governs 22.6 remote access. 22.8 (backup/forensic file collection) reuses D1–D6/D10 but adds its own collection-scope decisions (separate addendum).

## 13. Owner sign-off

| Role | Name | Decision (accept / amend / reject) | Date |
|---|---|---|---|
| Data Controller (Veri Sorumlusu) | Halil Koçoğlu (Halildeu, owner) | **ACCEPT** (D1–D7, D9, D10 defaults) + **AMEND** (D8: 22.6 narrow + 22.8 offboarding/audit file-copy via scenario dual-approval) | 2026-06-11 |
| Legal / Hukuk | Halil Koçoğlu (single-owner pre-prod; real-counsel review recommended pre-production) | **ACCEPT** as above | 2026-06-11 |
| İK / HR | Halil Koçoğlu (single-owner pre-prod) | **ACCEPT** as above | 2026-06-11 |
| IT-Security lead | Halil Koçoğlu (single-owner pre-prod) | **ACCEPT** as above | 2026-06-11 |

> All four roles signed ACCEPT (single-owner pre-prod) 2026-06-11 → #1388 **engineering** gate LIFTED for 22.6 + 22.8 (disabled-by-default build proceeds). The **first live session** still requires the §11/D10 acceptance gate (broker negative-tests + recording fail-closed + D29-EA). The D8 22.8 file-copy plane additionally requires the **22.8 collection-scope addendum** before its first live run. A real legal-counsel review of the KVKK basis is recommended before any production (non-pilot) rollout.

## 14. References

- Design: [ADR-0033](./0033-faz-22-6-remote-access-bridge-broker.md) (broker architecture/authz/token/audit/threat model)
- KVKK precedent: [ADR-0030](./0030-kvkk-meeting-intelligence-boundary.md)
- Charter: [ADR-0012-EA](./0012-EA-endpoint-admin-governance-charter.md)
- Plan: [`docs/faz-22-remote-access-bridge-plan.md`](../faz-22-remote-access-bridge-plan.md) §9.2 (owner-decision checklist)
- Gate: #1388 · downstream 22.6 (#510/#524/#1402/#116) + 22.8 (#1390/#117)
