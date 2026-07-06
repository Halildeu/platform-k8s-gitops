# Faz 22.3B — TPM Attestation + Vault PKI: Design & Integration Contract

> **Gate 1b** of [ADR-0039](adr/0039-faz-22-3b-tpm-attestation-vault-pki.md). Detailed design + the **agent ↔ backend integration contract** that Codex review (`019ec723`) required before the sequence is more than paper. All surfaces **disabled-by-default**; live pilot **owner-gated**. This path is **parallel** to AD CS (Faz 22.3A, Codex-owned) and does **not** alter it.
>
> Status: Implemented (gate-3 agent + gate-4 backend MERGED 2026-06-15; live pilot owner-gated — see `runbooks/RB-faz22-3b-tpm-enrollment-e2e.md`). Cross-AI: Claude impl, Codex reviewer.

## 1. Goal & non-goals
- **Goal:** issue an mTLS clientAuth cert to a device whose trust is rooted in **TPM attestation** (not domain membership), from **Vault PKI**, for the **domain-less / BYOD / macOS-Linux** segment.
- **Non-goals:** does NOT replace AD CS; does NOT touch the `adcomputer:{objectGUID}` AD CS path; no live issuance until the gated rollout's CA-resilience + pilot gates pass.

## 2. Enrollment protocol (4-leg, with TPM credential-activation EK→AK binding)

> **Updated 2026-06-14 (3-AI gate-4 consult: Codex `019ec723` + MiniMax `mvs_d6ab5b4f`).** The original 3-leg shape did NOT strongly bind the AK to the EK ("is this AK really resident in that EK's TPM?"). Both reviewers, unanimously: a secure **non-interactive** binding does not exist — the standard is **TPM2_MakeCredential (server) → TPM2_ActivateCredential (device)** challenge-response (TCG TPM 2.0 / DevID v1 r12). So the protocol is now **4-leg** = 2 HTTP round-trips, with the credential-activation challenge riding in the nonce response and the activation proof riding in the attest envelope. Still over the existing bootstrap token/HMAC channel until the cert exists.

```
Agent                                            Backend (endpoint-admin)            Vault PKI
  | L1. POST /enrollments/tpm/nonce (deviceRef, ekPub, akPub, akName)                     |
  |-------------------------------------------------->| mint single-use nonce            |
  |                                                   | software TPM2_MakeCredential      |
  |                                                   |   (EK_pub, AK_name, server-secret)|
  |<--------------------------------------------------| {nonce,nonceId,exp, credBlob,     |
  |                                                   |  encSecret}  ← the challenge      |
  | L2. TPM2_ActivateCredential(EK,AK,credBlob,encSecret) → recovers server-secret        |
  |     (proves the device holds BOTH the EK and the AK inside ONE TPM)                   |
  | L3. TPM2_Quote(nonce,pcrSelect) + TPM2_Certify(deviceKey by AK)                        |
  | POST /enrollments/tpm/attest (envelope: activatedSecret + quote + certify + csr)      |
  |-------------------------------------------------->| verify §4 (V1–V12) fail-closed→deny|
  |                                                   | ok ⇒ Vault PKI issue (CSR pubkey) |
  |                                                   |--------------------------------->|
  |                                                   |<-- clientAuth cert (short TTL) --|
  |<--------------------------------------------------| {cert, caChain, notAfter, uuid}  |
  | L4. mTLS to backend :8443 with the issued cert (existing client-auth=need path)       |
```
- **EK→AK binding (the key upgrade):** L1 server runs **software** `TPM2_MakeCredential` (pure crypto — no TPM / TSS-proxy on the server) sealing a random `server-secret` to the EK-public + AK-name. Only a TPM that holds BOTH that EK and that AK can `ActivateCredential` and recover it (L2). The recovered `activatedSecret` in the attest envelope proves EK↔AK↔one-TPM — this is what satisfies the "no secure non-interactive binding" requirement.

- **Legs 1–2 are authenticated by the device's existing bootstrap channel** (the current token/HMAC enrollment). TPM attestation is the **trust upgrade**, not the only auth — the cert is issued only when BOTH the bootstrap channel AND the attestation verify. (Defence-in-depth: a stolen bootstrap token alone cannot mint a cert without a valid TPM attestation; a replayed attestation alone cannot without the channel.)
- **Framing honesty (Codex 019ec723 review-2):** this is a **"bootstrap-authorization + TPM-identity-proof" HYBRID**, NOT a zero-shared-secret model like Windows domain/Kerberos. The bootstrap channel still carries a secret; the TPM attestation raises the assurance to hardware-rooted. We do not claim "no shared secret" — we claim "shared secret alone is insufficient."
- **Nonce is token-scoped:** `nonce_scope = token_id + tenant + device_hint`. The leg-2 attestation is only accepted against a nonce minted for the SAME bootstrap token/tenant/device — a stolen token cannot be replayed against a different device's nonce (no channel confusion). **`device_hint` is NOT free agent input** (Codex review-3): it is bound to / validated against a **server-side trust-anchor claim of the bootstrap token** (the backend derives the authoritative device binding from the token claim, not from caller-supplied text).
- The CSR public key MUST equal the **TPM-resident non-exportable device key** the AK attests (binding the issued cert to that TPM).

## 3. Attestation envelope (agent → backend, leg 2 body)

```json
{
  "schema": "faz22.3b.tpm-attest.v2",
  "deviceRef": "<opaque backend device ref>",
  "nonceId": "<from leg 1>",
  "activatedSecret": "<base64 — server-secret recovered via TPM2_ActivateCredential (L2 EK↔AK binding proof; V10)>",
  "ekCert": "<base64 DER EK certificate>",
  "ekCertChain": ["<base64 DER intermediate>", "..."],
  "akPub": "<base64 TPMT_PUBLIC of the Attestation Key>",
  "akName": "<base64 TPM2B_NAME>",
  "certifyInfo": "<base64 TPMS_ATTEST from TPM2_Certify(deviceKey by AK)>",
  "certifySig": "<base64 signature over certifyInfo by AK>",
  "quote": "<base64 TPMS_ATTEST from TPM2_Quote(nonce, pcrSelect)>",
  "quoteSig": "<base64 signature over quote by AK>",
  "pcrs": { "sha256": { "0": "<hex>", "7": "<hex>", "...": "..." } },
  "csrDer": "<base64 DER PKCS#10 CSR; pubkey == the certified device key>"
}
```
Path-free: no filesystem paths, no hostnames beyond the opaque deviceRef. EK/AK public material + PCR digests are the only device-identifying data (KVKK note in ADR-0039).

## 4. Backend attestation verifier — checks (ALL must pass; any failure ⇒ fail-closed deny)

| # | Check | Deny code on failure |
|---|---|---|
| V1 | `nonceId` exists, unconsumed, unexpired; **atomically consume-once** (race-safe store); clock-skew within policy | `NONCE_INVALID` |
| V2 | `ekCert`(+chain) chains to a **trusted manufacturer EK root** in the curated bundle; not expired; **not revoked**; firmware/model not in the ROCA-class denylist | `EK_UNTRUSTED` |
| V3 | AK is bound to this EK (TPM2 credential-activation OR the established EK→AK policy) | `AK_BINDING_FAILED` |
| V4 | `certifyInfo`/`certifySig` prove the **CSR pubkey == a TPM-resident non-exportable key** certified by the AK | `KEY_NOT_TPM_BOUND` |
| V5 | `quote`/`quoteSig` valid over the **issued nonce** (anti-replay) signed by the AK | `QUOTE_INVALID` |
| V6 | **PCR policy** (risk-tiered, ADR-0039): MANDATORY for HIGH-risk class, optional LOW/MEDIUM | `PCR_POLICY_FAILED` |
| V7 | device is **registered + enabled + not decommissioned/revoked** (§7) | `DEVICE_NOT_ELIGIBLE` |
| V8 | feature flag on for tenant + `enrollment_channel=TPM-Vault` selected | `FEATURE_DISABLED` |
| V9 | CSR key algorithm/size/hash meets minimum policy; no critical extension beyond clientAuth | `CSR_POLICY_VIOLATION` |

**Rate-limit / fail-safe (Codex 019ec723 review-2):** repeated failed attest attempts per `nonce_scope`/device trigger fast-fail + temporary freeze (brute-force / noisy-replay mitigation), while preserving fail-closed semantics.

**Deny response = single external shape, no behavioral oracle (Codex review-2):** ALL denies (V1–V9 **including `FEATURE_DISABLED`**) return the **same HTTP status (`403`) + a fixed body** to the caller — the specific deny code lives **only in the append-only audit log** as metadata, never on the wire. No `503`-vs-`422` distinction (that is itself an oracle). Response timing + body size are normalized to minimize timing/size side-channels. Always path-free.

## 5. Vault PKI issuance
- Dedicated mount `pki_endpoint_device/` with an **intermediate CA** (root offline; Transit/HSM-backed signing; Shamir 3-of-5 root custody).
- Role `tpm-device`: `client_flag=true`, `server_flag=false`, `key_usage=DigitalSignature`, `ext_key_usage=ClientAuth`, **short `ttl`** (e.g. 24h–7d, renewal re-attests), `allow_any_name=false`, SAN URI **`tpm:{ek_pub_sha256}`** only, CN = backend-registered device UUID.
- Backend signs the **agent-supplied CSR** (never generates the key) → the private key never leaves the TPM. **But the backend takes ONLY the public key from the CSR** (Codex 019ec723 review-2): the **SAN and CN are backend-OVERRIDDEN** — the backend injects `SAN URI = tpm:{ek_pub_sha256}` (from the verified EK) and `CN = registered device UUID`; any agent-supplied SAN/CN/subject is ignored. **Any critical extension beyond `clientAuth` EKU is rejected** (no uncontrolled extension expansion). Vault role pins `enforce_leaf_not_after_behavior`, `key_usage`, `ext_key_usage=ClientAuth`, and `use_csr_sans=false` / `use_csr_common_name=false`.
- **CSR key policy (V9):** the CSR key algorithm/size/hash must meet a minimum policy (e.g. RSA-3072+ or ECDSA-P256+; SHA-256+); weak keys rejected.
- CRL/OCSP enabled with CDP/AIA; measured propagation SLO.

## 6. Pluggable identity provider (backend) — preserves AD CS

```
verifyClientCert(cert):
  channel = resolveChannel(cert.issuer)          # issuer-pin, NOT SAN sniffing
  switch channel:
    ADCS:      require issuer==AD-CA AND SAN URI matches adcomputer:{objectGUID}   # unchanged, strict allowlist
    TPM-Vault: require issuer==Vault-PKI-intermediate AND SAN URI matches tpm:{ek_pub_sha256}
    else:      DENY (no cross-channel fallthrough)
  return identityProvider[channel].extract(cert)
```
- `MachineCertExtractor` becomes one provider (`ADCS`) behind this resolver; the AD CS pin + behaviour is byte-for-byte preserved (regression-tested).
- A cert issued by Vault-PKI can NEVER satisfy the ADCS provider and vice-versa (issuer pin). Fail-closed on unknown issuer.

## 7. Device lifecycle
- **Register:** first successful attestation registers `{deviceUuid, ek_pub_sha256, tenant, risk_class, state=ACTIVE}`.
- **Renew:** re-attest (lightweight: nonce + quote + key-certify); same deviceUuid.
- **Decommission / revoke:** state→`REVOKED`; Vault PKI revokes outstanding certs; CRL/OCSP propagates (SLO-measured).
- **Decommission→reconnect mapping (Codex R-4):** a `REVOKED` device that re-attests with the **same EK** is **denied** (`DEVICE_NOT_ELIGIBLE`) and audited as a re-enrollment attempt; re-activation is an explicit operator action (never automatic).

## 8. Agent `--auto-enroll-tpm`
- Behind a **default-off capability** `EnableTpmAutoEnroll` (mirrors `EnableBackupDryRun` / `EnableUpdateAgent`); advertised only when policy-ready.
- Flow: generate device key in TPM (CNG/PCP, non-exportable — existing) → request nonce → build envelope (§3) → POST attest → store the issued cert in the OS cert store (TPM-bound) → use for mTLS.
- Failure handling: any deny code → ret[r]y with backoff; never falls back to a weaker path silently.

## 9. Integration contract (HTTP)
| Method | Path | Auth | Req | 2xx | Deny |
|---|---|---|---|---|---|
| POST | `/api/v1/endpoint-agent/enrollments/tpm/nonce` | bootstrap channel | `{deviceRef,ekPub,akPub,akName}` | `200 {nonce,nonceId,exp,credBlob,encSecret}` (MakeCredential challenge) | uniform `403` |
| POST | `/api/v1/endpoint-agent/enrollments/tpm/attest` | bootstrap channel | envelope (§3) | `200 {cert,caChain,notAfter,deviceUuid}` | uniform `403` |
| (mTLS) | existing `:8443` device API | issued cert | — | — | fail-closed on unknown issuer |

> **Edge vs. internal path (verified against merged code 2026-06-15):** the table shows the **gateway-public** surface `/api/v1/endpoint-agent/**`. The api-gateway `endpoint-admin-agent-route` rewrites it `RewritePath=/api/v1/endpoint-agent/(?<segment>.*) → /api/v1/agent/${segment}`, so the request reaches the controller `@RequestMapping("/api/v1/agent/enrollments/tpm")` (`TpmEnrollmentController`). The agent (`internal/tpmenroll`, `wire.go`) joins the suffix `"/enrollments/tpm/{nonce,attest}"` onto the edge base `…/api/v1/endpoint-agent`. Both legs return **`200`** (`ResponseEntity.ok()`), not `201`. There is **no** `/api/v1/agent/**` route at the gateway — point the agent at the `endpoint-agent` edge surface.

- **All deny responses are identical on the wire:** single `403` + a fixed body (no deny code, no detail). The V1–V12 reason code (incl. `FEATURE_DISABLED`) is recorded **only in the append-only audit log** — never returned — to avoid a behavioral/enumeration oracle. Response timing + size normalized.
- Generic `/commands` etc. unaffected.

## 10. Test plan (maps to gated rollout 5–6)
- **Negative (must DENY, fail-closed):** expired/forged EK; EK not in bundle; revoked EK; replayed nonce; reused nonce (consume-once); quote over a stale nonce; CSR pubkey ≠ certified key; PCR mismatch on HIGH-risk; decommissioned device reconnect; cross-channel cert (Vault cert on ADCS path & vice-versa); feature-disabled. **Every one of these denies returns the SAME uniform `403` + fixed body** (the specific reason — incl. `FEATURE_DISABLED` — is audit-log-only; **no `503`/`422` oracle**, per §9).
- **Positive:** valid TPM → cert issued → mTLS handshake succeeds → device identity = `tpm:{ek_pub_sha256}`.
- **CA-resilience (gate 5):** seal/unseal, OCSP/CRL unavailable, intermediate-expiry sim → issuance fully fail-closed; revocation-propagation latency measured.

## 10.5 Gate-4 backend implementation design (3-AI consult 2026-06-14: Codex `019ec723` + MiniMax `mvs_d6ab5b4f`, convergent)

**Library (TPM 2.0 structure parsing) — RECONCILED (gate-4a-2.1 pivot, Codex `019ec723` AGREE-LOCK; merged platform-backend #653/#654/#657):** the few fixed-offset fields the verifier needs are **hand-parsed** with **no separate attestation library** — `TpmPublicArea` (`TPMT_PUBLIC`: nameAlg / objectAttributes / params / unique → JCA public key), `TpmsAttest` (`TPMS_ATTEST`: magic / type / extraData / certified-name / PCR), `TpmtSignature` (`TPMT_SIGNATURE`). **webauthn4j was evaluated and removed**: its `tpm` attestation-statement structures are reachable only through internal Jackson-CBOR deserializers (no standalone byte→object API), so it added a dependency + attack surface without a usable parse path; Yubico `java-webauthn-server` / Microsoft TSS.Java likewise not adopted. The earlier "hand-rolling rejected — byte-order/canonical-layout surface" concern is **closed by ground-truth validation, not by a library**: the parse is minimal, **big-endian** (TCG Part 1), and **exact-consume / reject-trailing** (T-9), and is pinned to a **real swtpm golden vector** + a **real `tpm2_activatecredential` interop** (software-MakeCredential TPM-spec conformance proven on staging-sw) + per-V mutation negatives. + **BouncyCastle** for EK cert-chain validation, signature verification (certify/quote + CSR proof-of-possession), and the software `MakeCredential`. **The AK-restricted-key assertion is source-verified here** — V11 recomputes the AK Name from `akPub` (per `nameAlg`) and asserts `restricted ∧ sign ∧ ¬decrypt ∧ fixedTPM ∧ fixedParent ∧ sensitiveDataOrigin` against the golden AK (not delegated to a library).

**Server-side `TPM2_MakeCredential` is IN-PROCESS software crypto** (KDFa + seed-encrypt to EK + AK-name HMAC, per TCG TPM 2.0 Part 1; via BouncyCastle) — **no TPM and no TSS-proxy on the server**. This resolves the only flagged architecture sub-decision (tpm2_tools shell-out vs microservice → neither needed).

**Verifier extends §4 V1–V9 → V12 (3-AI additions):**
- **V10 credential-activation:** the attest envelope's `activatedSecret` equals the server's MakeCredential `server-secret` (consumed once, bound to `nonceId`). This is the EK↔AK↔one-TPM proof. Fail → `ACTIVATION_FAILED`.
- **V11 AK restricted-signing-key:** the AK's `TPMA_OBJECT` MUST have `restricted` + `sign` + `fixedTPM` + `sensitiveDataOrigin` set (only a restricted AK's Certify/Quote are trustworthy). Fail → `AK_NOT_RESTRICTED`.
- **V12 algorithm whitelist:** EK/AK/CSR keys + all signatures restricted to **RSA-3072+ / ECDSA-P256+, SHA-256+**; SHA-1/MD5 and RSA↔ECC confusion rejected; explicit per-alg dispatch. Fail → `WEAK_ALGORITHM`.

**T-1..T-10 hardening (MiniMax pitfalls, mapped):** T-1 replay → atomic single-use nonce store (≤5 min TTL) + ≤30 s timestamp window + token-scope (V1). T-2 EK privacy → persist `ek_pub_sha256` (NOT raw EK) as the identity; raw EK never echoed (Privacy-CA = a 22.3B-extension for consumer/macOS). T-3 algorithm confusion → V12. T-4 restricted key → V11. T-5 PCR-policy bypass → verify the EXACT PCR subset selected, never a superset/subset substitution. T-6 PCR drift → a per-risk-class golden PCR allow-set with bounded tolerance (HIGH = pinned). T-7 manufacturer-root chain → curated bundle + **dual-root rotation window** (overlap during rotation). T-8 cert policy/EKU → leaf EKU clientAuth-only, no critical-ext expansion (Vault role + V12). T-9 quote-struct malleability → canonical hand-parse (big-endian, explicit-length, exact-consume), reject trailing/ambiguous bytes. T-10 **backend trust bootstrap → the manufacturer EK root bundle is pinned at BUILD time by SHA-256** (not runtime-fetched), matching the AG-018 root-pin pattern.

**Test (3-layer, both reviewers):** (1) **swtpm + tpm2-tools golden reproducer** → deterministic happy-path + a per-V mutation negative (V1..V12) fixture set; (2) JUnit 5 over the fixtures (no hardware in CI); (3) **real-hardware nightly** at pilot (one good + one problematic-BIOS device). Verifier ships behind the default-off flag until layer-3 passes.

**Implementation test notes (Codex `019ec723` review-2, carried into gate-4 code):** (1) **V11 recomputes the AK name** from `akPub` per the TPM `nameAlg` and compares it to `akName` — name-hash mismatch → fail-closed + logged (don't trust a caller-supplied name); (2) the software `MakeCredential` is verified with **negative vectors** across `nameAlg` / `hashAlg` / secret-derivation; (3) the `activatedSecret`↔`nonceId` match is bound to the **token-scope** (anti device-hijack — the recovered secret only validates the device that requested that nonce).

## 11. Slice breakdown (post gate-1b)
1. **gitops:** Vault PKI mount + role + ESO wiring (no live issuance) — gate 2.
2. **platform-agent:** `EnableTpmAutoEnroll` capability + envelope builder + nonce/attest client — gate 3.
3. **platform-backend:** nonce endpoint + attestation verifier (§4) + Vault PKI issuance + pluggable identity resolver (§6) + device lifecycle (§7), all default-off fail-closed — gate 4.
4. **CA-resilience drill + pilot** — gates 5–6 (owner-gated).

## References
- [ADR-0039](adr/0039-faz-22-3b-tpm-attestation-vault-pki.md) (charter)
- 3-AI mutabakat: Codex `019ec723`, MiniMax `mvs_d6ab5b4f`
- ADR-0029 (AD CS, Faz 22.3A, Codex) — unchanged by this
- TCG TPM 2.0 (EK/AK credential activation, TPM2_Certify, TPM2_Quote); HashiCorp Vault PKI secrets engine
