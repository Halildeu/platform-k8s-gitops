# RB — Faz 22.6 #548 A1 Device-Key Broker Activation

> **Scope:** operator-attended test activation for the strong hardware-attestation path. This does not close
> `platform-backend#548` by itself; it prepares the separate `DEVICE_KEY_ATTESTATION_REAL` broker and the
> Vault/TPM preconditions needed before the live acceptance marker can be signed.
>
> **Hard boundary:** never flip the shared denetim pilot broker from `MACHINE_CERT_ENROLLMENT` to
> `DEVICE_KEY_ATTESTATION_REAL`. The strong path uses the separate
> `endpoint-admin-remote-bridge-device-key` overlay only.

## 1. What Codex prepared

The non-secret GitOps activation overlay is:

```text
kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key
```

It renders a separate broker with:

- Deployment/Service/ConfigMap names suffixed as `endpoint-admin-remote-bridge-*-device-key`;
- unique pod/service selectors (`app.kubernetes.io/name=endpoint-admin-remote-bridge-device-key`);
- `REMOTE_BRIDGE_DEVICE_TRUST_VERIFIER=DEVICE_KEY_ATTESTATION_REAL`;
- fail-closed duress source `AMBIGUOUS_UNTIL_WIRED`, not `PILOT_RISK_ACCEPTED_DISABLED`;
- `ENDPOINT_ADMIN_TPM_ATTEST_ENABLED=true` and the pinned Intel ODCA manufacturer root;
- dedicated NodePort `31945` for the test pilot;
- dedicated Vault path `kv/platform/endpoint-admin-remote-bridge-device-key`;
- no production overlay changes and no Argo-root reference.

Render-only validation:

```bash
kubectl kustomize kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key
scripts/faz22-remote-ops/faz22-6-a1-preflight.sh
```

Live A1 status from 2026-06-27:

- test Vault `pki_int` exists and has role `tpm-device` with `client_flag=true`, `server_flag=false`;
- AppRole `endpoint-admin-tpm` exists with least-privilege policy `endpoint-admin-tpm-sign`;
- `kv/platform/endpoint-admin-service` has `tpm_vault_role_id` and `tpm_vault_secret_id`;
- AppRole login plus backend-contract `pki_int/sign/tpm-device` CSR signing drill passed;
- the temporary non-standard `tpm-device` AppRole/policy used during initial probing was removed;
- test GitOps ESO now maps `ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ROLE_ID` and
  `ENDPOINT_ADMIN_TPM_ATTEST_VAULT_SECRET_ID` from `kv/platform/endpoint-admin-service`.
- Denetim PC is reachable over `staging-sw -> WG -> 10.99.0.2`; Windows OpenSSH key/ACL was normalized,
  three consecutive SSH smokes passed, TPM 2.0 is present/ready/capable for attestation, EK manufacturer cert
  count is `1`, and EndpointAgent reports `v0.3.3`.

This is not enough to close #548. The backend still needs the HTTPS Vault transport/pinned CA, ESO sync in
the live cluster, the final `ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ENABLED=true` flip, and a real Denetim PC TPM
enrollment/session marker.

The dedicated strong-path broker intentionally does not use the bounded product-channel duress risk-acceptance
flag. If full session execution needs a duress-clean signal, wire a real duress source or record an explicit
owner decision outside the #548 hardware-attestation marker; do not hide that gap inside the marker.

## 2. Operator prerequisites

### 2.1 Vault PKI issuance for primary `/attest`

Run `docs/runbooks/RB-faz22-3b-vault-pki-setup.md` first. The primary `endpoint-admin-service` must be able
to sign TPM device CSRs through Vault PKI before the strong broker can produce meaningful session evidence.

Required operator actions, summarized:

1. Provision `pki_int` and role `tpm-device` in the test Vault. Done on 2026-06-27 for the current test Vault.
2. Create AppRole `endpoint-admin-tpm` with sign-only policy for `pki_int/sign/tpm-device`. Done on
   2026-06-27 for the current test Vault.
3. Seed `tpm_vault_role_id` and `tpm_vault_secret_id` into `kv/platform/endpoint-admin-service`. Done on
   2026-06-27 for the current test Vault.
4. Seed/pin the HTTPS Vault listener CA for `https://vault.platform-test.svc.cluster.local:8202`. Still open;
   live service discovery currently shows only the existing `vault:8200` service port.
5. Apply/sync the endpoint-admin ESO mapping and verify the live K8s Secret contains both Vault fields without
   printing either value.
6. Flip primary `endpoint-admin-service` Vault PKI config only after ESO Ready, synced credentials can sign
   `pki_int/sign/tpm-device`, and the backend pod can TLS-handshake the pinned HTTPS Vault listener.

Do not print role IDs, secret IDs, Vault tokens, private keys, or raw cert private material in chat, Mavis,
GitHub, shell history, or evidence. Use presence/status/hash evidence.

### 2.2 Dedicated #548 broker Vault path

Seed the separate broker path below. The values mirror the existing shared remote-bridge broker, but the path
is separate so the strong-path broker can be rotated or deleted without touching the shared pilot.

```text
kv/platform/endpoint-admin-remote-bridge-device-key
```

Required properties:

```text
broker_db_username
broker_db_password
openfga_store_id
openfga_model_id
device_ca_pem
device_crl_pem
attestation_public_key_pem
operator_step_up_public_key_pem
broker_tls_cert_chain_pem
broker_tls_private_key_pem
permit_signing_key_pem
recording_anchor_signing_key
```

The `device_ca_pem` must validate the TPM-issued client cert that the Denetim PC bridge will present. If the
agent is still selecting the old machine cert, the REAL verifier will deny with the expected mTLS leaf binding
failure.

## 3. Pre-apply gates

Run:

```bash
scripts/faz22-remote-ops/faz22-6-a1-preflight.sh
```

Required before apply:

- primary `endpoint-admin-service` has `ENDPOINT_ADMIN_TPM_ATTEST_ENABLED=true`;
- primary `endpoint-admin-service` has Intel manufacturer root pin;
- primary Vault PKI signing is configured and proven with `pki_int/sign/tpm-device`, or the next step is
  explicitly limited to broker render only;
- Vault HTTPS `:8202` transport exists and its CA is pinned before `ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ENABLED`
  is flipped;
- live `endpoint-admin-service-secrets` contains `ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ROLE_ID` and
  `ENDPOINT_ADMIN_TPM_ATTEST_VAULT_SECRET_ID`;
- shared broker remains `MACHINE_CERT_ENROLLMENT`;
- Denetim PC is reachable over `staging-sw -> WG -> 10.99.0.2`;
- Denetim PC TPM has `Ready For Attestation=True`, `Is Capable For Attestation=True`, and at least one EK manufacturer cert;
- dedicated ExternalSecrets are Ready=True after applying the overlay.

## 4. Apply

Only after the operator confirms the Vault paths are seeded:

```bash
kubectl --context k3d-test -n platform-test apply -k \
  kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key

kubectl --context k3d-test -n platform-test rollout status \
  deploy/endpoint-admin-remote-bridge-device-key --timeout=300s
```

Post-apply checks:

```bash
kubectl --context k3d-test -n platform-test get deploy endpoint-admin-remote-bridge endpoint-admin-remote-bridge-device-key
kubectl --context k3d-test -n platform-test get externalsecret \
  endpoint-admin-remote-bridge-secrets-device-key \
  endpoint-admin-remote-bridge-tls-device-key \
  endpoint-admin-remote-bridge-signer-device-key
kubectl --context k3d-test -n platform-test get cm endpoint-admin-remote-bridge-config-device-key \
  -o jsonpath='{.data.REMOTE_BRIDGE_DEVICE_TRUST_VERIFIER}{"\n"}'
```

Expected verifier output:

```text
DEVICE_KEY_ATTESTATION_REAL
```

## 5. Denetim PC next run

After the primary Vault PKI `/attest` path and the dedicated REAL broker are live:

1. Run TPM auto-enroll on Denetim PC using a fresh test enrollment token.
2. Verify `endpoint_tpm_device_binding` has non-empty `ak_name`, `ak_pub_sha256`, `ek_cert_sha256`, and
   `device_key_spki_sha256` for the Denetim PC.
3. Verify the bridge-selected Windows `LocalMachine\My` client cert is the TPM-issued cert and its SPKI matches
   `device_key_spki_sha256`.
4. Point only the Denetim PC at the dedicated broker endpoint.
5. Run a live broker session and capture `deviceTrusted=true`, `Basis.HARDWARE_KEY_ATTESTATION`.
6. Run negative matrix: missing, stale, replay, wrong-device, wrong-tenant.
7. Only then generate the `F22_6_B1_4_HARDWARE_ATTESTATION_ACCEPTANCE: v1` marker.

## 6. Rollback

The overlay is isolated. Rollback removes only the dedicated strong-path broker:

```bash
kubectl --context k3d-test -n platform-test delete -k \
  kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key
```

Do not delete or alter the shared `endpoint-admin-remote-bridge` resources during this rollback.
