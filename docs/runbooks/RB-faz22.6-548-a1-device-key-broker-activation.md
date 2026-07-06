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
kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key-live
```

It renders the separate broker child overlay and the public SNI route with:

- Deployment/Service/ConfigMap names suffixed as `endpoint-admin-remote-bridge-*-device-key`;
- unique pod/service selectors (`app.kubernetes.io/name=endpoint-admin-remote-bridge-device-key`);
- public mTLS SNI ingress `remote-bridge-mtls.testai.acik.com` routed to
  `endpoint-admin-remote-bridge-device-key:9444`;
- `REMOTE_BRIDGE_DEVICE_TRUST_VERIFIER=DEVICE_KEY_ATTESTATION_REAL`;
- fail-closed duress source `AMBIGUOUS_UNTIL_WIRED`, not `PILOT_RISK_ACCEPTED_DISABLED`;
- `ENDPOINT_ADMIN_TPM_ATTEST_ENABLED=true` and the pinned TPM manufacturer roots/intermediate;
- dedicated NodePort `31945` for the test pilot;
- dedicated Vault path `kv/platform/endpoint-admin-remote-bridge-device-key`;
- no production overlay changes and no Argo-root reference.

Render-only validation:

```bash
kubectl kustomize kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key-live
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
- Denetim PC historical preflight was reachable over `staging-sw -> WG -> 10.99.0.2`; Windows OpenSSH key/ACL
  was normalized, three consecutive SSH smokes passed, TPM 2.0 was present/ready/capable for attestation,
  EK manufacturer cert count was `1`, and EndpointAgent reported `v0.3.3`.
- Current 2026-07-01 target endpoint is AgentPC2. Operator precheck showed EndpointAgent `v0.3.8`, a
  `CN=AgentPc2` TPM client certificate from `CN=platform-test endpoint device CA`, service status `Running`,
  `ENDPOINT_AGENT_REMOTE_BRIDGE_DEVICE_KEY_SESSION_ENABLED=true`, and agent logs reaching
  `remote-bridge: dialing broker` for `remote-bridge-mtls.testai.acik.com:443`.
- The A1 workflow therefore defaults `denetim_check=false`. A 2026-07-01
  read-only check from `staging-sw` still proved route `10.99.0.2 dev wg0 src
  10.99.0.1` and `10.99.0.2:22` TCP reachability, but both
  `denetimpc@10.99.0.2` and `svc-denetim-agent@10.99.0.2` returned
  `Permission denied (publickey)`. Set `denetim_check=true` only if the owner
  explicitly switches the selected target back to Denetim PC and refreshes the
  SSH key/ACL path first.

This is not enough to close #548. The backend still needs the HTTPS Vault transport/pinned CA, ESO sync in
the live cluster, the final `ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ENABLED=true` flip, and a real target-endpoint TPM
enrollment/session marker.

The test Vault HTTPS transport is intentionally additive:

- existing ESO continues to use `http://vault.platform-test.svc.cluster.local:8200`;
- backend TPM-attestation signing uses `https://vault.platform-test.svc.cluster.local:8202`;
- the TLS CA/cert/key live under `/home/halil/platform-stateful/test/vault/tls` on `staging-sw` and are never
  committed to git or printed in evidence;
- the Kubernetes `vault` Service/Endpoints expose an additional `https:8202` port for the same test Vault
  container endpoint.

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
4. Seed/pin the HTTPS Vault listener CA for `https://vault.platform-test.svc.cluster.local:8202`. The
   GitOps service port is additive; the backend flag remains off until live TLS status works through the
   pinned CA.
5. Apply/sync the endpoint-admin ESO mapping and verify the live K8s Secret contains both Vault fields without
   printing either value.
6. Flip primary `endpoint-admin-service` Vault PKI config only after ESO Ready, synced credentials can sign
   `pki_int/sign/tpm-device`, and the backend pod can TLS-handshake the pinned HTTPS Vault listener.

Do not print role IDs, secret IDs, Vault tokens, private keys, or raw cert private material in chat, Mavis,
GitHub, shell history, or evidence. Use presence/status/hash evidence.

### 2.1.1 Vault HTTPS 8202 activation guard

Before restarting the test Vault container, verify the live mount source still matches the desired compose path:

```bash
ssh staging-sw "docker inspect platform-vault-test --format '{{json .Mounts}}' | jq '.[].Source'"
```

Expected data/log source prefix:

```text
/home/halil/platform-stateful/test/vault
```

If the live container reports `/srv/platform/stateful/test/vault`, stop and reconcile the mount path first. A
wrong path on recreate can boot Vault with an empty Raft directory.

Provision or reuse test-only TLS material:

```bash
RESTART_VAULT=0 scripts/faz22-remote-ops/faz22-6-a1-vault-https-provision-test.sh
```

After this PR is merged and the staging-sw checkout has the compose/config change, restart with validation:

```bash
RESTART_VAULT=1 scripts/faz22-remote-ops/faz22-6-a1-vault-https-provision-test.sh
```

If Vault returns sealed after recreate, unseal it with the test key threshold before continuing. Then verify:

```bash
ssh staging-sw "docker exec platform-vault-test sh -c \
  'VAULT_ADDR=https://127.0.0.1:8202 VAULT_CACERT=/vault/tls/ca.crt vault status'"
```

The generated certificate includes `172.19.0.4` as a convenience SAN because the current `k3d-test` host bridge
endpoint uses that container IP. The DNS SANs are the primary contract; if Docker bridge IP changes, rotate the
test TLS material or rely on DNS verification from the backend.

After Vault restart, check ESO readiness again because a single-node Vault restart can produce transient
`SecretSyncFailure` events until the next reconcile:

```bash
ssh staging-sw "kubectl --context k3d-test -n platform-test get externalsecret -o wide"
```

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

The `device_ca_pem` must validate the TPM-issued client cert that the target endpoint bridge will present.
For the current run, this is AgentPC2. If the agent is still selecting the old machine cert, the REAL verifier
will deny with the expected mTLS leaf binding failure.

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
- Vault HTTPS `:8202` transport exists, the service port is visible, and CA-pinned `vault status` works before
  `ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ENABLED` is flipped;
- live `endpoint-admin-service-secrets` contains `ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ROLE_ID` and
  `ENDPOINT_ADMIN_TPM_ATTEST_VAULT_SECRET_ID`;
- shared broker remains `MACHINE_CERT_ENROLLMENT`;
- target endpoint is explicitly selected for the run (`AgentPC2` for the 2026-07-01 run; Denetim PC only if the
  owner explicitly switches the target);
- target endpoint TPM has `Ready For Attestation=True`, `Is Capable For Attestation=True`, and at least one EK
  manufacturer cert;
- target endpoint TPM client certificate is still within `NotBefore`/`NotAfter`; AgentPC2's 2026-07-01 precheck
  certificate expired at `2026-07-01T18:18:52+03:00`, so rerun TPM enrollment if the live session is after that time;
- dedicated ExternalSecrets are Ready=True after applying the overlay.

## 4. Apply

### 4.1 Mutual-exclusion boundary

The shared product-channel activation overlay
`kustomize/overlays/test/activation/endpoint-admin-remote-bridge` and this device-key live wrapper both render
the same public SNI Ingress name:

```text
endpoint-admin-remote-bridge-mtls
```

They intentionally point that one SNI route at different Services:

- shared product-channel activation: `endpoint-admin-remote-bridge:9444`;
- #548 device-key activation: `endpoint-admin-remote-bridge-device-key:9444`.

Do not run the shared activation workflow while the device-key activation workflow is in progress, and do not
apply both activation overlays as independent live states. The workflows share the same GitHub Actions
concurrency group so owner-gated workflow applies cannot race; direct `kubectl apply` remains an operator
responsibility and must preserve this mutual-exclusion boundary.

### 4.2 Quota-safe rollout boundary

The device-key broker overlay deliberately renders:

```text
maxSurge=0
maxUnavailable=1
```

The test namespace can run close to its CPU ResourceQuota during Faz 22.6 evidence capture. A default
`maxSurge=1/maxUnavailable=0` rollout attempts to create a second broker pod before terminating the old one and can
fail with `exceeded quota` even though the steady-state single broker fits. The device-key broker is a single-device,
owner-gated evidence path, so a one-at-a-time replacement is the intended durable rollout behavior.

Only after the operator confirms the Vault paths are seeded:

```bash
kubectl --context k3d-test -n platform-test apply -k \
  kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key-live

kubectl --context k3d-test -n platform-test rollout status \
  deploy/endpoint-admin-remote-bridge-device-key --timeout=300s
```

If direct `staging-sw` SSH is unavailable, use the owner-gated self-hosted workflow after the PR is on `main`:

```bash
gh workflow run apply-device-key-remote-bridge-activation.yml \
  --ref main \
  -f confirm=APPLY_DEVICE_KEY_REMOTE_BRIDGE_ACTIVATION \
  -f expected_digest=sha256:462bd7444a03e2b3fddcb720a1b563e90fc2425c8cf200dddf635670cd05aae6 \
  -f dry_run=true

gh workflow run apply-device-key-remote-bridge-activation.yml \
  --ref main \
  -f confirm=APPLY_DEVICE_KEY_REMOTE_BRIDGE_ACTIVATION \
  -f expected_digest=sha256:462bd7444a03e2b3fddcb720a1b563e90fc2425c8cf200dddf635670cd05aae6 \
  -f dry_run=false
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

## 5. Target endpoint next run

After the primary Vault PKI `/attest` path and the dedicated REAL broker are live:

1. Run TPM auto-enroll on the selected target endpoint using a fresh test enrollment token.
   For the 2026-07-01 run, use AgentPC2 unless the owner explicitly changes the target.
2. Verify `endpoint_tpm_device_binding` has non-empty `ak_name`, `ak_pub_sha256`, `ek_cert_sha256`, and
   `device_key_spki_sha256` for the target endpoint.
3. Verify the bridge-selected Windows `LocalMachine\My` client cert is the TPM-issued cert and its SPKI matches
   `device_key_spki_sha256`.
4. Point only the selected target endpoint at the dedicated broker endpoint.
5. Run a live broker session and capture `deviceTrusted=true`, `Basis.HARDWARE_KEY_ATTESTATION`.
6. Run negative matrix: missing, stale, replay, wrong-device, wrong-tenant.
7. Only then generate the `F22_6_B1_4_HARDWARE_ATTESTATION_ACCEPTANCE: v1` marker.

## 6. Rollback

The overlay is isolated. Rollback removes only the dedicated strong-path broker:

```bash
kubectl --context k3d-test -n platform-test delete -k \
  kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key-live
```

Do not delete or alter the shared `endpoint-admin-remote-bridge` resources during this rollback.
