# RB — Faz 22.6 #548 Device-Key Session Attestation — Step-7 Live Run

> **Trigger:** the #548 backend + agent code is merged (all cross-AI Codex `019efada`/`019efd6b` AGREE) and you want to prove the **strong path** end-to-end on real hardware — a broker-nonced, live TPM device-key challenge → `deviceTrusted=true`, `Basis.HARDWARE_KEY_ATTESTATION`.
>
> **Scope:** the ONLY remaining #548 piece. Backend (steps 1-5b) + agent (6a production, 6b wire-integration, 6c EK-NV-read, 6d app-wiring) are code-complete; this runbook is the **operator-attended live validation** on a real Windows TPM. Disabled-by-default discipline (ADR-0034): every enabling flag here is opt-in.
>
> **Audience:** operator with (a) cluster authority for the endpoint-admin-service remote-bridge deploy, (b) a real Windows PC with an attestation-capable TPM, (c) owner sign-off for the live pilot (D10/§11).
>
> **Hardened (Codex `019efd6b` REVISE→AGREE):** the four gates an operator otherwise hits as `device-key-leaf-binding-mismatch` / `ek-chain-untrusted` / `no private key` are called out explicitly (§0.1 EK chain, §3.1 mTLS-leaf binding, §3.2 full env set, §1 broker runtime evidence).

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
2. **Enroll (TPM)** so the AK↔EK binding (#748 V74) persists for this device:
   ```powershell
   endpoint-agent.exe --auto-enroll --auto-enroll-api-url https://<ea-host>/... --once
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
