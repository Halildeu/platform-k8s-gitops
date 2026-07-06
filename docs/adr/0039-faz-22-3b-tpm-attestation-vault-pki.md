# ADR-0039 — Faz 22.3B: TPM Attestation + Vault PKI Parallel Device-Enrollment Path

- **Status:** Proposed (charter; disabled-by-default; pilot owner-gated)
- **Date:** 2026-06-14
- **Deciders:** Owner (2026-06-14: "AD CS kalsın, onunla sistemi ayağa kaldıralım; sonra paralelde diğerini feature olarak geliştirelim") + 3-AI mutabakat (Claude / Codex thread `019ec723` / MiniMax Mavis `mvs_d6ab5b4f` — all **AGREE-locked**)
- **Owners:** Faz 22.3A (AD CS, domain-joined primary) = Codex session; **Faz 22.3B (this ADR, the parallel path) = Claude**
- **Relation:** **Amends, does not replace** [ADR-0029](0029-faz22-mass-deployment-mtls-msi-gpo.md) (AD CS mass-deployment mTLS). Parallel to it.

## Context

Faz 22.5 M2 tokenless device enrollment is built on **Windows Server AD CS** (URI-SAN `adcomputer:{objectGUID}` machine certs, GPO autoenrollment, ADR-0029). The owner asked whether the same security is achievable **without Windows Server**.

A 3-AI consensus (Claude + Codex + MiniMax, 2 rounds, AGREE-locked) concluded:

> **VERDICT: NO — Windows Server / AD CS is NOT strictly required for equal security.** TPM attestation + HashiCorp Vault PKI can match AD CS's four security pillars (enrollment-trust without a shared secret, TPM/CNG non-exportable keys, CRL/OCSP revocation, identity binding) **conditionally** — contingent on closing the **trust-bootstrap** gap. It is **not equal today**: it requires real engineering. AD CS gives GPO autoenrollment + operational maturity for free.

The owner decision: **keep AD CS for the domain-joined segment** (it works, it is mature, the URI-SAN cert is already proven), and **develop the non-Windows-Server path as a parallel feature** (this ADR) for domain-less / BYOD / macOS / Linux endpoints — consistent with the 2026-06-10 owner precedent for code-signing ("$0, no Windows Server, no AD CS, Ubuntu", AG-018).

### Why this is feasible on existing infrastructure
- **Vault is already live in prod** (secret management, ESO-synced) → a Vault PKI secrets engine can be the device CA at $0, with Transit/HSM-backed signing.
- **The agent already uses TPM/CNG non-exportable keys** (certtostore CNG, platform-agent #147/#148) → TPM-rooted device keys are in hand.
- **Domain-less / BYOD endpoints already use token/HMAC enrollment** (AD CS cannot serve them at all) → this path also hardens that segment.

## Decision

Introduce **Faz 22.3B**: a **parallel, disabled-by-default** device-enrollment path that issues mTLS client-auth certificates from **Vault PKI**, where enrollment trust is established by **TPM attestation** (not domain membership). It does **NOT** replace AD CS; domain-joined Windows endpoints stay on the AD CS path (Faz 22.3A).

### Enrollment flow (high level)
1. Agent generates a non-exportable device key in the **TPM** (CNG/PCP; existing capability).
2. Agent requests a **single-use server nonce** (anti-replay), then produces a **TPM attestation**: EK certificate (+chain), an AK bound to the device key, and a quote over the nonce (+ optional PCR policy).
3. Backend **attestation verifier** validates: EK chains to a trusted **manufacturer root bundle**; AK↔EK↔device-key binding; nonce freshness/single-use; (optional) PCR policy.
4. On success, the backend requests **Vault PKI** to issue a short-lived **clientAuth** cert whose identity encodes the **registered device identity** (see below).
5. The device uses that cert for the existing backend **mTLS** path (client-auth=need) thereafter; renewal re-runs a lightweight attestation.

### Device-identity model (alongside `adcomputer:{objectGUID}`)
The backend `MachineCertExtractor` is today hard-pinned to the AD CS `adcomputer:{objectGUID}` SAN URI. This ADR extends it to a **pluggable identity provider** that ALSO accepts a TPM-attestation identity — e.g. SAN URI `tpm:{ek_pub_sha256}` bound to a backend-registered device UUID.

**Channel selection is by trusted channel, NOT by SAN content (Codex 019ec723 review, MUST):**
- The provider is selected by a **secure channel tag** — the **issuing CA identity (issuer pin) + `enrollment_channel`** label (`source=ADCS | TPM-Vault`) returned by the verification layer — **never** by sniffing/parsing the SAN to "guess" which path a cert is on. A cert MUST NOT silently fall through from the AD CS path to the TPM path (that would weaken AD CS's domain-bound model).
- **AD CS path = strict allowlist:** a cert is valid on the AD CS path **only** when issued by the **AD CA issuer** AND carrying the `adcomputer:{objectGUID}` pin. This is enforced by a **policy engine + issuer pin**, not by a backward-compat string pattern. AD CS behaviour is therefore unchanged and uncompromised.
- The TPM-Vault provider is reachable **only** for certs issued by the Vault PKI intermediate over the TPM-attestation channel. Cross-channel acceptance is fail-closed.

### Trust-bootstrap + anti-abuse mitigations (consensus risks R-1..R-4; Codex 019ec723 review-2 absorbed)
- **R-1 Trust bootstrap (critical):** backend trusts an unseen TPM only via a curated **manufacturer EK root bundle** (Infineon/STM/Nuvoton/AMD/Intel/…) + a **rotation policy** + **revoked-EK handling** + **EK-cert freshness/validity check** + a **model/firmware risk classification** (ROCA-2017 class roots flagged/denied). Evaluate **DAA / a Privacy-CA** for EK-cert privacy + single-root-compromise blast-radius reduction. Unknown/untrusted/revoked EK root → **fail-closed deny**.
- **R-2 Replay / cloning:** single-use **nonce** with a **server-side atomic nonce store** (consume-once, race-safe) + an explicit **clock-skew policy** (TTL ≤30 s is necessary but not sufficient alone) + **policy-driven, ops-safe AK rotation** (not a flat ≤24 h that could break identity continuity) + EK-pub-derived unique device id + append-only attestation audit. Triple control to match AD CS's no-shared-secret property.
- **R-3 Vault PKI operability:** dedicated PKI mount with an **intermediate CA**, **Transit/HSM-backed** signing, **Shamir 3-of-5** root custody, defined **intermediate-rotation + offline-root** policy, OCSP/CRL with CDP/AIA fallback + a measured **CRL/OCSP propagation SLO**, a **root-compromise recovery runbook** (with metrics + a tested drill), and a seal/unseal runbook (CA-grade availability requirement).
- **R-4 Identity-lifecycle parity:** AD CS got object disable/delete/reissue + group policy + BitLocker/VPN integration for free. This path must implement an explicit **device registration / decommission / revocation** model + **incident-response path** + a defined **decommission→reconnect mapping** (what happens when a decommissioned device re-attests/reconnects must be specified, not undefined). The pilot must **measure revocation-propagation latency** and record matches/false-positives. Otherwise dropping `objectGUID` is a security regression. Estimated +2–3 sprints.

**PCR policy is risk-tiered (acceptance criterion; Codex 019ec723 review-3):** TPM quote **PCR policy is MANDATORY for HIGH-risk** device/segment classes and **optional for LOW/MEDIUM** — bound to the pilot + rollout acceptance gates, so the parallel path's assurance level cannot silently drop below the risk class it serves.

## Security parity (3-AI comparison, 1–5; 5 = strongest)

| Dimension | AD CS (Win Server) | Vault PKI + TPM attestation | Note |
|---|:---:|:---:|---|
| Enrollment trust (no shared secret) | 5 | 3 today → 5 once R-1/R-2 closed | trust-bootstrap is the gate |
| Key custody | 5 | 4–5 | TPM non-exportable + Vault Transit/HSM |
| Identity binding | 5 | 3 | `adcomputer:{objectGUID}` AD-integration is unique |
| Revocation / lifecycle | 4 | 3 | Vault OCSP/CRL needs HA + rotation maturing |
| **Domain-less / BYOD / macOS-Linux** | 1 | 5 | biggest advantage of this path |
| Zero-touch / autoenroll | 5 | 2 | GPO ready vs must-be-built |
| Infra cost + dependency | 3 | 4 | $0 + existing Vault; no Win license/AD dep |
| Maturity / operability | 5 | 2 | battle-tested vs new |
| Engineering effort (adopt) | 5 (existing) | 1 (high, +2–3 sprints) | attestation flow + identity rebuild |
| Operational reliability | 4 | 3 | seal/unseal, CA-key rollover failure modes |
| **Total** | **~38–42 / 50** | **~31–35 / 50 today, equalizable** | statistically close; **segment-dependent** |

## Gated rollout (none optional; each gate must pass before the next)
1. **Design doc + this ADR** (cross-AI iterated) — **including a written `agent --auto-enroll-tpm` ↔ backend-verifier integration contract** (request/response, attestation envelope, nonce protocol, error/deny codes), so the sequence is not paper-only. ← current slice
2. **Vault PKI engine** (mount + intermediate + Transit/HSM + HA + OCSP/CRL), disabled from any live issuance.
3. **Agent `--auto-enroll-tpm`** (TPM key + EK/AK attestation + nonce), behind a default-off capability (mirrors `EnableBackupDryRun` / `EnableUpdateAgent`).
4. **Backend attestation verifier + Vault PKI issuance + pluggable identity provider**, default-off; fail-closed.
5. **CA resilience gate (before any pilot, Codex review-2):** a **rollback drill** (CA seal/unseal failure, OCSP/CRL unavailable, intermediate-expiry simulation, offline-root repair) + an **enforcement negative test** proving that during rollback/outage **new cert issuance is fully fail-closed** (no fallback issuance, no silent AD-CS-path fallthrough).
6. **5–10 PC pilot** (owner-gated) with negative (forged / replayed / untrusted-or-revoked-EK → deny) + positive (valid TPM → cert → mTLS) smokes; **measure revocation-propagation latency**.
7. **Gradual rollout**, segment by segment.

## Scope / non-goals
- **Does NOT replace AD CS.** Domain-joined Windows endpoints stay on Faz 22.3A (AD CS, Codex-owned). This is additive.
- **Disabled-by-default** end-to-end; live pilot is **owner-gated**.
- No claim of "AD CS-equivalent security" until the R-1..R-4 gates pass measurable acceptance.
- KVKK: device-attestation metadata (EK/AK public material, device id) is processed; lawful basis + retention to be confirmed with DPO before pilot (same gate discipline as the broader Faz 22 work).

## Consequences
- **+** Removes the Windows Server / AD CS dependency for the domain-less/BYOD/macOS-Linux segment; runs on existing Vault; $0; consistent with the AG-018 precedent.
- **+** TPM-rooted identity is hardware-strong and (with R-1/R-2) matches AD CS's no-shared-secret enrollment.
- **−** Real engineering cost (+2–3 sprints) and a new operational surface (Vault PKI as a CA, attestation verification, device lifecycle) that must reach AD CS-grade maturity before carrying production trust.
- **−** Two enrollment paths to maintain during the hybrid period.

## Alternatives considered (and rejected as the *sole* path)
- **AD CS only** — rejected as universal: cannot serve domain-less/BYOD/macOS-Linux; keeps the Windows Server dependency the owner wants to bound.
- **Bootstrap-token + internal CA (no attestation)** — weaker: reintroduces a stealable shared secret, which the mTLS path exists to eliminate.
- **Replace AD CS with Vault+TPM now** — rejected: not equal today (maturity/zero-touch/identity-lifecycle gaps); hybrid is the consensus.

## References
- 3-AI mutabakat: Codex thread `019ec723`, MiniMax Mavis session `mvs_d6ab5b4f` (both AGREE-locked, 2026-06-14)
- [ADR-0029](0029-faz22-mass-deployment-mtls-msi-gpo.md) AD CS mass-deployment mTLS (Faz 22.3A, amended-by-this)
- AG-018 owner precedent (Linux internal CA, $0/no-Windows-Server) — platform-agent #133/#134
- Agent TPM/CNG keys — platform-agent #147/#148 (certtostore CNG)
- `docs/runbooks/RB-faz22-M2-edge-mtls-activation.md` (AD CS edge path, Codex)
