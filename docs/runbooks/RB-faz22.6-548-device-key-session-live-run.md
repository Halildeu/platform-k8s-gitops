# RB — Faz 22.6 #548 Device-Key Session Attestation — Step-7 Live Run

> **Trigger:** the #548 backend + agent code is merged (all cross-AI Codex `019efada`/`019efd6b` AGREE) and you want to prove the **strong path** end-to-end on real hardware — a broker-nonced, live TPM device-key challenge → `deviceTrusted=true`, `Basis.HARDWARE_KEY_ATTESTATION`.
>
> **Scope:** the ONLY remaining #548 piece. Backend (steps 1-5b) + agent (6a production, 6b wire-integration, 6c EK-NV-read, 6d app-wiring) are code-complete; this runbook is the **operator-attended live validation** on a real Windows TPM. Disabled-by-default discipline (ADR-0034): every enabling flag here is opt-in.
>
> **Audience:** operator with (a) cluster authority for the endpoint-admin-service remote-bridge deploy, (b) a real Windows PC with an attestation-capable TPM, (c) owner sign-off for the live pilot (D10/§11).
>
> **Hardened (Codex `019efd6b` REVISE→AGREE):** the four gates an operator otherwise hits as `device-key-leaf-binding-mismatch` / `ek-chain-untrusted` / `no private key` are called out explicitly (§0.1 EK chain, §3.1 mTLS-leaf binding, §3.2 full env set, §1 broker runtime evidence).

---

## A. Codex-consulted execution plan (test pilot — 2026-06-25, thread `019efd6b`)

Authoritative, industry-standard plan from a live recon of the real Intel fTPM PC + the deployed test cluster. **This section is the canonical execution order; §0–§7 are the detailed per-gate reference.**

**Live state established (kubectl + direct-SSH recon):** target PC has a real **Intel fTPM** (RSA-2048 EK, attestation-capable, EK cert present) — viable. The deployed broker `endpoint-admin-remote-bridge` (NodePort 9444) is the **owner-approved denetim pilot** running `REMOTE_BRIDGE_DEVICE_TRUST_VERIFIER=MACHINE_CERT_ENROLLMENT` with existing machine-cert sessions. `endpoint-admin.tpm-attest` is OFF. The signed agent **v0.3.3** (6a–6d + #238 EICA chain) is published (auto-signed, WDAC-trusted).

### A.1 — Decision 1: a SEPARATE #548 broker, NEVER flip the shared pilot
- **DO (b):** stand up a **separate device-key broker instance** (own Service/SNI or NodePort, ConfigMap, ExternalSecret/Vault path, permit KID, policy version, signer/recording keys, agent broker address) with `REMOTE_BRIDGE_DEVICE_TRUST_VERIFIER=DEVICE_KEY_ATTESTATION_REAL`. Leave the existing broker on `MACHINE_CERT_ENROLLMENT` untouched.
- **DO NOT (a):** flip the shared broker — that is a hard cutover that denies existing machine-cert-only devices by design.
- **LATER (c):** a tiered, policy-aware composite verifier (prefer-hardware, named machine-cert fallback with expiry + downgrade metrics) is the production migration — a separate feature PR, not this live run. For the pilot use `DEVICE_KEY_ATTESTATION_REAL` (basis `HARDWARE_KEY_ATTESTATION`) so the evidence is unambiguous; `REQUIRE_ENROLLMENT_AND_DEVICE_KEY_REAL` only if the owner wants the explicit `COMPOSITE` enrollment+hardware basis. The REAL verifier already re-checks active connected peer + persisted TPM binding + EK chain + AK binding + triple-SPKI equality.

### A.2 — Decision 2: tpm-attest enablement (the §0.1 enrollment prerequisite)
Enable on the service that runs `TpmEnrollmentController` (`endpoint-admin-service`, and the separate #548 broker if it selects the REAL verifier):
```
endpoint-admin.tpm-attest.enabled=true
endpoint-admin.tpm-attest.allowed-tenant-ids=00000000-0000-0000-0000-000000000001   # pilot tenant
endpoint-admin.tpm-attest.manufacturer-root-pems=<Intel ODCA Root CA PEM>            # config-pinned, NOT runtime-fetched
endpoint-admin.tpm-attest.manufacturer-root-sha256=beb40bb7507b33967226aa80e084749fbb6593893c642e818d682e9a8d07fc24
endpoint-admin.tpm-attest.vault.enabled=true
# Vault PKI (L2 cert issuance) — fails startup if non-HTTPS or missing pinned CA:
endpoint-admin.tpm-attest.vault.base-url=https://<vault>      # HTTPS
endpoint-admin.tpm-attest.vault.role-id / secret-id          # AppRole (secret-id via ESO)
endpoint-admin.tpm-attest.vault.<mount>/<role>               # PKI mount + role
endpoint-admin.tpm-attest.vault.ca-pem=<pinned Vault CA PEM>
# PCR: LEAVE UNSET on the first live run (see A.2.1)
```
- **Intel ODCA Root** (`https://tsci.intel.com/content/OnDieCA/certs/OnDie_CA_RootCA_Certificate.cer`, self-signed, sha256 `beb40bb7…`) is the correct single trust anchor. With agent **#238** the chain is `EK leaf → CSME ADL PTT EICA → Intel ODCA Root`: the agent sends the EICA in `ek_cert_chain_b64` (read from NV `0x01C00100..+3`), the backend pins the ODCA root. Do **not** pin the CSME intermediate as a normal anchor (that is the temporary "pinned intermediate" exception only).

#### A.2.1 — PCR: do NOT strict-pin on the first run (Codex critical)
`--auto-enroll-tpm` does **not** pass a `PCRSelections`, so the TPM quote has an empty PCR selection. Backend `pcr.advisory=true` is **not** "ignore PCR" — it still requires the quote's PCR selection to EQUAL `required-bitmap-hex`, then skips only the digest allow-set. So setting `required-bitmap-hex` while the agent sends no selection → enrollment **fails with PCR-selection-mismatch**. ⇒ **Leave PCR policy entirely unset** for the first #548 proof; capture the quote/PCR evidence from the run; only later (once the agent is wired to quote a known selection) set `required-bitmap-hex` + `advisory=true`, and only after stable cross-reboot observations move to `allow-set` enforcement. **Do not claim PCR posture yet.**

### A.3 — Decision 3: safe sequence (validate enrollment + #238 BEFORE any session-verifier change)
1. **Prepare enrollment trust** — enable tpm-attest (A.2) for the pilot tenant only, Intel ODCA root pin, Vault PKI, PCR off. **Enrollment-only — does not touch the existing broker's session basis.** Owner/security PR (new enrollment trust basis). **Requires Vault PKI admin setup** (mount + role + AppRole + pinned CA) — operator/credential-gated; the existing endpoint ESO carries no Vault PKI, so this is fresh Vault setup.
2. **TPM auto-enroll** the Intel PC (`endpoint-agent.exe --auto-enroll-tpm --once`, v0.3.3). Verify the strong enrollment evidence BEFORE any session change: EK cert present; **EICA sent in `ek_cert_chain_b64`**; EK chain validates to the Intel ODCA root (no `ek-chain-untrusted` — this **runtime-validates #238**); AK restricted/Name matches; Vault-issued cert returned; `endpoint_tpm_device_binding` row has non-empty `ak_name` / `ak_pub_sha256` / `ek_cert_sha256` / `device_key_spki_sha256`.
3. **Verify mTLS-leaf binding** (§3.1) — the bridge-selected client cert is the TPM-issued cert, its private key is acquirable, and leaf SPKI SHA-256 == `endpoint_tpm_device_binding.device_key_spki_sha256`. **Most likely operator trap** (a PEM exists but the bridge picks the old machine cert / a no-private-key cert).
4. **Stand up the separate #548 broker** (A.1) — `DEVICE_KEY_ATTESTATION_REAL`; it also needs `tpm-attest.enabled=true` + the root pins present in its deployment (else the factory fails fast).
5. **Point ONLY the test PC** at the #548 broker (agent remote-bridge + operations + `DEVICE_KEY_SESSION_ENABLED` for that PC). Existing machine-cert devices stay on the existing broker address.
6. **Acceptance + negative markers** (§5/§6). Codex extra step-7 evidence: the agent's `ek_cert_chain_b64` subject/issuer **order** must match the validator's `leaf + chain[]` build; the chain is validated **per-session** too (not just enrollment).

> **Owner/operator gates (not agent-doable):** Vault PKI admin setup (A.3.1), the new-enrollment-trust PR sign-off, the separate-broker deployment + its Vault secrets, and the managed-PC agent rollout to v0.3.3. The agent-doable parts (PC update + enroll + mTLS-leaf verify + session, all via SSH once the backend is ready) are driven by the assistant.

---

## 0. Hardware prerequisite — the target TPM MUST be attestation-capable

**Recon finding (2026-06-25):** the Parallels **vTPM (Manufacturer `PRLS`) is NOT viable** — it has an EK *key* but **no manufacturer EK *certificate*** (`Get-TpmEndorsementKeyInfo` → `ManufacturerCertificates=0`) and `tpmtool` → `Is Capable For Attestation: False`. The strong path **fail-closes** on it. The "denetim PC" is a Linux AI host (RTX 4070 / ollama+whisper), **not** a Windows agent target.

**⇒ Step-7 requires a real Windows PC** (e.g. a fleet machine like `HALILKOOLUB735` / `MKR-A1`) whose firmware/discrete TPM ships a manufacturer EK certificate.

**Gate 0 — verify the target TPM** (on the target PC, elevated):

```powershell
tpmtool getdeviceinformation
#   EXPECT: -Is Capable For Attestation: True   AND   -Ready For Attestation: True
#   EXPECT: a real Manufacturer ID (INTC/AMD/STM/NTC/IFX...), NOT "PRLS"
(Get-TpmEndorsementKeyInfo -Hash Sha256).ManufacturerCertificates.Count
#   EXPECT: >= 1   (this is the EK cert #236 readEKCertificate() reads from NV 0x01C00002)
```

> **FAIL signal:** `Capable For Attestation: False` or `ManufacturerCertificates=0` → this PC cannot do the strong path; pick another.

### 0.1 EK certificate chain — prove the exact payload validates to a configured trust anchor (Codex MUST-FIX #2)

`ManufacturerCertificates >= 1` is necessary but **not sufficient**. The backend (`TpmEkChainValidator`, configured by `TpmEnrollmentConfig`) validates the **exact payload `ek_cert_b64 + ek_cert_chain_b64`** against the configured **trust-anchor set** `endpoint-admin.tpm-attest.manufacturer-root-pems` / `manufacturer-root-sha256`. Those are **trust anchors, NOT a root+intermediate cache** — the backend does **not** auto-discover a missing intermediate. The agent's Windows TPM impl currently sends **`ek_cert_chain_b64 = nil`** (EK leaf only). So the acceptable cases are exactly:

1. The EK cert validates **directly** to a pinned manufacturer root/trust anchor with an **empty chain**; OR
2. the agent/backend is changed to supply the missing intermediate in **`ek_cert_chain_b64`**; OR
3. the owner explicitly pins the intermediate into `manufacturer-root-pems` as a **temporary trust anchor** — and the run labels it as a "pinned intermediate trust anchor", **NOT** as a vendor-root-chain proof.

Before the run, dump the EK cert issuer chain and decide which case applies:
```powershell
$ek = (Get-TpmEndorsementKeyInfo -Hash Sha256).ManufacturerCertificates[0]
$ek.Issuer; $ek.Subject
```

> **BLOCKER:** if the exact `ek_cert_b64 + ek_cert_chain_b64` payload cannot be validated against the configured trust anchors **before** the run, step-7 is blocked — not "try and see" (it would deny `ek-chain-untrusted`).

---

## 1. Backend — deploy the remote-bridge broker with the REAL verifier (owner-gated)

The broker must run the `DEVICE_KEY_ATTESTATION_REAL` verifier (the only `HARDWARE_KEY_ATTESTATION` basis). Owner-gated D29-EA deploy (Vault + Keycloak + overlay). **Prove ALL of the following on the live pod** (Codex MUST-FIX #4 — "Flyway + verifier" alone is not enough):

1. **Image/commit** actually contains the #752 issuance trigger (`RemoteBridgeOperatorService.openSession` → `sendDeviceKeyChallenge`, gated on a REAL verifier). Verify the deployed image digest maps to a `main` commit at/after #752.
2. **Migrations** through **V74** (the AK↔EK binding table, #748):
   ```bash
   kubectl --context <ctx> -n <ns-ea> exec deploy/endpoint-admin-service -- \
     sh -c 'psql "$DB_URL" -tAc "select max(version) from flyway_schema_history"'   # EXPECT >= 74
   ```
3. **Verifier mode** = `DEVICE_KEY_ATTESTATION_REAL` (gates `deviceKeySessionEnabled` in #752). Confirm it rendered into the pod env, not just the overlay.
4. **`endpoint-admin.tpm-attest.enabled=true`** + **pinned manufacturer root PEM bundle** configured (the EK-chain trust anchor for §0.1) + **Vault PKI** configured (issues the device mTLS cert).
5. **Challenge TTL** — confirm the property/env name and value on the live pod (the design default is 180000 ms > the consent window; `DeviceKeyChallengeStore` takes it caller-supplied, so the value comes from `RemoteBridgeServerConfig`/env, not a literal). Capture the live value as evidence.
6. **Roll + verify D29-EA** (Up / Functional / Zanzibar-ready):
   ```bash
   kubectl --context <ctx> -n <ns-ea> rollout status deploy/endpoint-admin-service --timeout=300s
   # Functional: the remote-bridge gRPC port answers; an anonymous CONNECT is rejected (auth), not 500.
   ```

> **FAIL signal:** verifier not REAL → no challenge issued (the agent sees an idle stream). Pinned roots / Vault PKI absent → enrollment or EK-chain fails. Re-check the live pod env, not the overlay.

---

## 2. Agent — build, install, enroll on the target PC

1. **Build** from `platform-agent` `main` (#234 production + #235 wire-integration + #236 EK-NV-read + #237 app-wiring). Use the signed MSI / one-command install.
2. **Enroll (TPM)** so the AK<->EK binding (#748 V74) persists for this
   device. Prefer the non-secret operator packet generated by GitOps:
   ```bash
   scripts/faz22-remote-ops/faz22-6-agentpc2-tpm-autoenroll-packet.sh \
     --api-url https://testai.acik.com/api/v1/endpoint-agent \
     --target-hostname AgentPc2 \
     --target-product-device-id 2f7ad30f-970a-42e7-8af8-08764ae6066f
   ```
   Or generate the same packet from GitHub Actions:
   ```bash
   gh workflow run faz22-6-agentpc2-tpm-autoenroll-packet.yml \
     --ref main \
     -f confirm=PREPARE_AGENTPC2_TPM_AUTOENROLL_PACKET \
     -f api_url=https://testai.acik.com/api/v1/endpoint-agent \
     -f target_hostname=AgentPc2 \
     -f target_product_device_id=2f7ad30f-970a-42e7-8af8-08764ae6066f
   ```
   The packet never embeds the enrollment token. On AgentPC2, prefer
   `agentpc2-tpm-autoenroll-runner.ps1`: it downloads and verifies
   `agentpc2-tpm-autoenroll.ps1`, prompts for the fresh test token with a fixed
   hidden prompt, injects it only into the process environment, and clears it
   after the endpoint-local run. Do not edit the `Read-Host -Prompt` text and do
   not put the raw token in chat, GitHub, Mavis, shell history, or evidence.
   The runner rejects obviously truncated prompt input locally before the
   endpoint/API call, without logging the token value; this specifically guards
   the live-found `enrollmentToken len=1` class from accidentally typing the
   masking asterisk, prompt text, or a redacted placeholder.
   If `endpoint-agent --auto-enroll-tpm` exits non-zero, the current runner
   prints redacted endpoint diagnostics from the evidence directory plus the
   local `endpoint-agent.exe` version/help output; use that first to separate
   stale endpoint binary, TPM/EK capability, bootstrap mTLS, API, and persistence
   failures. Return only the generated redacted evidence files.

   The underlying agent CLI is:
   ```powershell
   endpoint-agent.exe --auto-enroll-tpm --api-url https://testai.acik.com/api/v1/endpoint-agent
   ```
   Backend-side verify the binding row is **complete** (Codex note — not just present):
   ```bash
   kubectl --context <ctx> -n <ns-ea> exec deploy/endpoint-admin-service -- sh -c \
     'psql "$DB_URL" -tAc "select device_id, revoked_at, (ak_name is not null), (ak_pub_sha256 is not null), (ek_cert_sha256 is not null), (device_key_spki_sha256 is not null) from endpoint_tpm_device_binding where revoked_at is null order by created_at desc limit 1"'
   #   EXPECT: device_id NOT NULL, revoked_at NULL, and ak_name / ak_pub_sha256 / ek_cert_sha256 / device_key_spki_sha256 all TRUE (non-empty),
   #           bound to THIS device's tenant/device/enrollment.
   ```

> **FAIL signal:** no row, null `device_id` (audit `TPM_BINDING_SKIPPED_NO_DEVICE_ID`), or any hash empty → the strong path fails closed at the persisted-binding / SPKI checks. `ek_cert_sha256` non-empty here is the enrollment-time proof the EK cert read worked (§0.1).

---

## 3. Agent — enable the device-key session responder (6d, opt-in)

The remote-bridge harness answers a broker `DeviceKeyChallenge` only when its `DeviceKeyResponder` is wired — gated by the flag (default-off). When set, the agent opens a TPM (`NewWindowsTPMDevice` — the **same** EK/AK/device-key as enrollment, each a deterministic `CreatePrimary`; no persistent handle) and wires `devkeysession.Respond`.

### 3.1 mTLS leaf binding — the bridge's transport cert MUST be the TPM-issued one (Codex MUST-FIX #1)

The verifier requires **triple-SPKI equality**: attested device key == **live mTLS leaf SPKI** == persisted `device_key_spki_sha256`. The remote-bridge mTLS path loads its client cert from the Windows `LocalMachine\My` certstore (private-key-acquirable), while TPM auto-enroll persists the issued cert to `%ProgramData%\EndpointAgent\tpm-client-cert.pem` (certstore/CNG association is a known follow-up). So **explicitly gate before the run:**

- The cert the bridge selects (via `...MTLS_CERT_SUBJECT_SUFFIX` / `...SAN_URI_PREFIX`) is the **TPM-issued** cert from enrollment.
- Its **private key is acquirable** from `LocalMachine\My` (CNG/TPM-backed) — else the bridge fails to start ("no private key").
- Its **leaf SPKI SHA-256 == `endpoint_tpm_device_binding.device_key_spki_sha256`** — else the verifier denies `device-key-leaf-binding-mismatch`.

> If the TPM-issued cert is not in `LocalMachine\My` with an acquirable key, resolve that (import + associate, or the certstore-association follow-up) **before** step-7 — this is the single most likely operator trap.

### 3.2 Full mandatory env set (Codex MUST-FIX #3)

```
ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED=true
ENDPOINT_AGENT_REMOTE_BRIDGE_OPERATIONS_ENABLED=true          # device-key session requires operations (refuses loudly otherwise)
ENDPOINT_AGENT_REMOTE_BRIDGE_DEVICE_KEY_SESSION_ENABLED=true  # 6d flag
ENDPOINT_AGENT_REMOTE_BRIDGE_INSECURE_PLAINTEXT=false         # strong path needs mTLS; plaintext is refused
ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR=<broker host:port>
ENDPOINT_AGENT_REMOTE_BRIDGE_TLS_SERVER_NAME=<broker SNI>
ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64=<broker permit pubkey>
ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_KEY_ID=<permit kid>
# mTLS cert selector — one of (must resolve to the TPM-issued leaf, §3.1):
ENDPOINT_AGENT_REMOTE_BRIDGE_MTLS_CERT_SUBJECT_SUFFIX=<...>   # or ..._MTLS_CERT_SAN_URI_PREFIX=<...>
```

> **TPM handle budget:** enrollment's TPM device must be **closed** before the bridge opens its own (EK+AK+device = 3 transient primaries each; two live sets can exceed a TPM's transient slot limit → `CreatePrimary` out-of-memory). The agent enrolls one-shot then starts the long-lived bridge, so they don't overlap — confirm no `TPM_RC_MEMORY` at bridge start. An enabled flag with operations OFF refuses the bridge loudly (not a silent no-op).

---

## 4. Attended live run + capture

1. Start the agent (service or foreground) with §3.2; watch the log for a clean bridge start (no "no private key", no `TPM_RC_MEMORY`).
2. Open a remote session against this device (the operator flow that calls `RemoteBridgeOperatorService.openSession`). The broker issues a session-bound challenge → the agent's harness dispatches it → `devkeysession.Respond` signs the binding context with the TPM device key → the response returns on CONTROL.
3. Capture the agent log + the broker verifier decision for the session.

---

## 5. Acceptance markers (Codex `019efada`/`019efd6b`) — ALL must hold

- [ ] **EK cert read:** agent `readEKCertificate()` returns a non-empty DER (matches §0 `ManufacturerCertificates>=1`).
- [ ] **EK pub binding:** enrollment V2 `ekCert.getPublicKey() == ekPub.toPublicKey()`.
- [ ] **EK chain:** the EK cert chains to the pinned manufacturer root (§0.1 pre-proven; no `ek-chain-untrusted`).
- [ ] **mTLS leaf binding:** the bridge's live mTLS leaf SPKI == persisted `device_key_spki_sha256` (§3.1; no `device-key-leaf-binding-mismatch`).
- [ ] **Strong path clears the EK gate:** the verifier no longer denies `ek-cert-required` and proceeds through the chain.
- [ ] **Triple SPKI equality:** attested device-key SPKI == live mTLS leaf SPKI == persisted binding SPKI.
- [ ] **Incarnation:** the stored `challengeId` == the session's current `deviceKeyChallengeId` (no stale/replayed evidence).
- [ ] **Verdict:** `deviceTrusted=true`, `Basis.HARDWARE_KEY_ATTESTATION`, `hardwareKeyAttested=true`.

---

## 6. Fail-closed expectations (CORRECT, not bugs)

- No/short EK cert (e.g. the Parallels VM) → `ek-cert-required`. Expected.
- EK cert doesn't chain to a pinned root → `ek-chain-untrusted`. Expected (resolve via §0.1).
- Bridge mTLS leaf SPKI ≠ persisted binding → `device-key-leaf-binding-mismatch`. Expected (resolve via §3.1).
- AK Name / EK fingerprint / device-key SPKI mismatch vs the persisted binding → deny. Expected.
- `challengeId` mismatch (reused client sessionId) → `device-key-challenge-incarnation-mismatch`. Expected.
- Verifier mode not REAL → no challenge issued. Expected (re-check §1.3).

## 7. Rollback

- **Agent side:** unset `ENDPOINT_AGENT_REMOTE_BRIDGE_DEVICE_KEY_SESSION_ENABLED` (the agent stops answering challenges).
- **Broker side, SEPARATELY:** set the session verifier back to a non-REAL mode (the broker stops issuing challenges).
- Both are config flips; #548 is additive — **no rollback migration**. Pending challenges + evidence-store entries drain naturally on their TTL.

## References

- Canonical design: `platform-backend/endpoint-admin-service/docs/faz22.6-device-key-session-attestation-design.md` (§5 sequence, §6 reconciliation, §7 status).
- Backend PRs #741/#743/#744/#746/#747/#748/#750/#752; agent PRs platform-agent#234/#235/#236/#237.
- Cross-AI authority: Codex threads `019efada-7558-7653-b134-258c24f46831` (#548 lineage) + `019efd6b-c7e3-77c0-8764-c2201872ce22` (6d + this runbook).
- AK↔EK binding: `endpoint_tpm_device_binding` (V74); ConnectedDeviceResolver active-cert gate is the primary revocation.
