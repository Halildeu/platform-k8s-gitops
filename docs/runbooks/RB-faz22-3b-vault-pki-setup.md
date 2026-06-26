# RB-faz22-3b-vault-pki-setup — test Vault PKI engine + tpm-device role + backend AppRole for #548 device-cert issuance

> **Tetik:** Faz 22.6 #548 `/attest` step needs the endpoint-admin-service `VaultPkiClient` to sign the
> TPM device CSR (`POST /v1/{mount}/sign/{role}`) → issued leaf cert → `endpoint_tpm_device_binding` (V74)
> row → §3.1 SPKI parity → device-key session. The live `/attest` currently denies with
> `code=FEATURE_DISABLED detail="FEATURE_DISABLED: vault issuance not configured"` (proven 2026-06-26,
> see PR #2057 evidence): the backend `endpoint-admin.tpm-attest.vault.enabled=false` because the PKI
> mount/role/AppRole do not exist yet **and** the test Vault has no HTTPS listener the backend can pin.
>
> **This runbook covers the PKI engine + `tpm-device` sign role + backend AppRole** (the issuance backend).
> It is the prerequisite that [`RB-faz22.6-548-vault-https-enablement.md`](./RB-faz22.6-548-vault-https-enablement.md)
> (PR #2054, the HTTPS **transport**) explicitly assumes "already provisioned". The two compose:
> transport (HTTPS listener the backend pins) + issuance (this PKI engine) -> the backend config flip (§5)
> -> `/attest` issues the cert.
>
> **Cross-AI note:** Codex (thread 019efd6b) directed "Vault server-cert + pinned-CA, NOT a proxy"
> (transport, RB-vault-https) and the gate-4b client contract (this runbook). Author: Claude.
>
> **Owner/operator-gated:** writes to the shared, 2-month-stable `platform-vault-test`. The PKI mount +
> role + AppRole are **additive** (new mount path `pki_int`, new auth method `approle`, new policy/role -
> they do NOT touch existing mounts, the KV store, the ESO ClusterSecretStore, or the `:8200` HTTP plane),
> so this step does **not** restart Vault and does **not** risk the parallel-session test plane. The single
> blast-radius step is the HTTPS listener restart in the companion RB (#2054), not this one.

## 1. AMAÇ

Stand up the Vault PKI issuance backend the endpoint-admin-service `VaultPkiClient` (gate-4b, ADR-0039)
expects, so `/attest` signs the TPM device CSR and writes the V74 binding row instead of denying
`FEATURE_DISABLED`. **Out of scope:** the HTTPS transport listener (RB-faz22.6-548-vault-https-enablement,
#2054) and the device-key SESSION broker flip (separate `DEVICE_KEY_ATTESTATION_REAL` broker - NEVER flip
the shared denetim-pilot broker).

## 2. KAPSAM (backend contract — code-verified, NOT invented)

The backend `VaultPkiClient` + `VaultPkiProperties` (prefix `endpoint-admin.tpm-attest.vault`) require:

| Contract element | Value (code-verified) | Source |
|---|---|---|
| Sign endpoint | `POST /v1/{mount}/sign/{role}` body `{"csr":"<PEM>","format":"pem"}` -> `data.certificate` | `VaultPkiClient.signCsr` |
| `mount` default | `pki_int` | `VaultPkiProperties` (blank -> `pki_int`) |
| `role` default | `tpm-device` | `VaultPkiProperties` (blank -> `tpm-device`) |
| Auth | AppRole - `POST /v1/auth/approle/login` `{role_id,secret_id}` -> token (lease + renew skew) | `VaultPkiClient` cachedToken |
| `baseUrl` | MUST be `https://` (fail-fast otherwise) | `VaultPkiProperties` |
| `caCertPem` | pinned Vault server CA (must contain `BEGIN CERTIFICATE`), required when enabled | `VaultPkiProperties` |
| `roleId`/`secretId` | from ESO / mounted secret, never hardcoded (redacted in toString) | `VaultPkiProperties` |

The agent submits a **CSR** (the TPM device key proves possession); Vault **signs** it (Vault does not
generate the key). So the `tpm-device` role is a **sign** role permitting the device-cert shape: an RSA-2048
key (the Intel fTPM EK/AK floor - V12 telemetry-flags 2048 as accepted), a `tpm:<deviceId>` URI SAN, and a
short leaf TTL.

## 3. ÖNKOŞULLAR (operator)

- Host shell on staging-sw (`ssh halil@staging-sw`), docker control of `platform-vault-test`.
- A privileged Vault token for `platform-vault-test` (root or a policy that can `sys/mounts`, `sys/auth`,
  `sys/policies/acl`, and write the pki role). Operator-supplied; this runbook never prints it.
- An **issuing CA** for `pki_int`: either (a) generate a self-signed root in-Vault for the test plane, or
  (b) import an intermediate signed by an offline/internal root. The test plane uses (a) for simplicity
  (the device leaf chains to this test PKI root, distinct from the EK-manufacturer Intel ODCA root, which
  is the `/nonce` EK-chain anchor - do NOT conflate the two roots).
- Companion transport runbook (#2054) ready to apply (the backend needs HTTPS to reach Vault), but the
  PKI engine below can be provisioned first (it works over the existing `:8200` plane).

## 4. ADIMLAR (additive; no Vault restart)

> Run on staging-sw with `VAULT_ADDR=http://127.0.0.1:8200` (host-published test Vault) and the operator
> token exported to the shell (`export VAULT_TOKEN=...` - keep it out of shell history / scripts).

### 4.1 Enable + configure the PKI engine at `pki_int`
```bash
vault secrets enable -path=pki_int pki                      # idempotent: ignore "path is already in use"
vault secrets tune -max-lease-ttl=8760h pki_int
# Test-plane self-signed root (Option a). For Option b, import an intermediate CSR signed offline.
vault write -field=certificate pki_int/root/generate/internal \
    common_name="platform-test endpoint device CA" issuer_name="tpm-device-ca" ttl=8760h \
    key_type=rsa key_bits=4096 > /tmp/pki_int_ca.crt   # device-cert chain root (NOT the Intel EK root)
vault write pki_int/config/urls \
    issuing_certificates="http://127.0.0.1:8200/v1/pki_int/ca" \
    crl_distribution_points="http://127.0.0.1:8200/v1/pki_int/crl"
```
> Devam eşiği: `vault read pki_int/cert/ca` returns the CA; `/tmp/pki_int_ca.crt` is a valid PEM.

### 4.2 Create the `tpm-device` sign role (URI-SAN `tpm:*`, RSA-2048, short leaf)
```bash
vault write pki_int/roles/tpm-device \
    allowed_uri_sans="tpm:*" \
    allow_any_name=true allow_ip_sans=false \
    key_type=rsa key_bits=2048 \
    max_ttl=72h ttl=24h \
    no_store=false require_cn=false \
    use_csr_common_name=true use_csr_sans=true \
    enforce_hostnames=false
```
> Rationale: the device CSR carries CN=deviceId + URI-SAN `tpm:<deviceId>`; `allowed_uri_sans=tpm:*`
> permits exactly that namespace and nothing else. `key_bits=2048` matches the Intel fTPM EK/AK floor.
> Devam eşiği: `vault read pki_int/roles/tpm-device` shows `allowed_uri_sans=[tpm:*]`.

### 4.3 Enable AppRole + bind a least-privilege policy for the backend
```bash
vault auth enable approle 2>/dev/null || true              # idempotent
cat <<'POLICY' | vault policy write endpoint-admin-tpm-sign -
# Least privilege: the backend may ONLY sign the tpm-device role on pki_int.
path "pki_int/sign/tpm-device" { capabilities = ["update"] }
path "pki_int/cert/ca"        { capabilities = ["read"] }
POLICY
vault write auth/approle/role/endpoint-admin-tpm \
    token_policies="endpoint-admin-tpm-sign" \
    token_ttl=20m token_max_ttl=1h secret_id_ttl=720h \
    secret_id_num_uses=0 token_num_uses=0
ROLE_ID=$(vault read -field=role_id auth/approle/role/endpoint-admin-tpm/role-id)
SECRET_ID=$(vault write -f -field=secret_id auth/approle/role/endpoint-admin-tpm/secret-id)
# Seed roleId/secretId into Vault KV for ESO (do NOT echo; pipe). Mirror the other endpoint secrets:
printf '%s' "$ROLE_ID"   | vault kv patch kv/platform/endpoint-admin tpm_vault_role_id=-
printf '%s' "$SECRET_ID" | vault kv patch kv/platform/endpoint-admin tpm_vault_secret_id=-
unset ROLE_ID SECRET_ID
```
> Devam eşiği: `vault read auth/approle/role/endpoint-admin-tpm` exists; KV has both keys (values redacted).
> The policy is sign-only - it cannot read the KV store, other mounts, or issue under any other role.

## 5. BACKEND CONFIG ACTIVATION (gitops — apply ONLY after #2054 HTTPS listener is live)

> WARN FAIL-FAST GUARD: `VaultPkiProperties` throws at startup if `enabled=true` but `baseUrl` is not
> `https://` or `caCertPem` is unpinned or `roleId`/`secretId` are blank. **Do NOT flip `enabled=true`
> until** (a) #2054's HTTPS listener is live (`https://vault.platform-test.svc.cluster.local:8202`
> reachable from the endpoint-admin pod), and (b) §4 PKI + AppRole exist, and (c) the ESO-synced
> `tpm_vault_role_id`/`tpm_vault_secret_id` land in the pod env. Flipping early takes endpoint-admin DOWN
> (breaks the parallel-session test plane). This is the single ordered activation point.

ConfigMap (`endpoint-admin-service-config`, test overlay) JSON6902 add, mirroring the existing tpm-attest
keys (do NOT inline the AppRole creds - those come from ESO):
```yaml
ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ENABLED: "true"
ENDPOINT_ADMIN_TPM_ATTEST_VAULT_BASE_URL: "https://vault.platform-test.svc.cluster.local:8202"
ENDPOINT_ADMIN_TPM_ATTEST_VAULT_MOUNT: "pki_int"
ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ROLE: "tpm-device"
ENDPOINT_ADMIN_TPM_ATTEST_VAULT_CA_CERT_PEM: "<the #2054 gen-vault-test-tls CA PEM, multi-line>"
# roleId/secretId via ESO -> ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ROLE_ID / _SECRET_ID
```
ExternalSecret: add `tpm_vault_role_id`->`ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ROLE_ID` and
`tpm_vault_secret_id`->`ENDPOINT_ADMIN_TPM_ATTEST_VAULT_SECRET_ID` from `kv/platform/endpoint-admin`.
Then selective `kubectl apply` + `rollout restart deploy/endpoint-admin-service` + browser/console verify
(HARD RULE - deploy sonrasi console verify).

## 6. POST-GATE CHAIN COMPLETION (re-run the proven live-/attest recipe)

Once §4 + §5 + #2054 are live, re-run the **proven** live-drive recipe (validated 2026-06-26, recorded in
agent memory `project_faz22_6_548_devkey_session_attestation.md` cont.6 + PR #2057 evidence):

1. Mint a fresh enrollment token: KC master-admin token -> reset test persona `c5persona-admin-9001` pw ->
   ROPC `frontend` client -> `POST https://testai.acik.com/api/v1/endpoint-admin/endpoint-enrollments`
   (gateway Route 23 RewritePath -> backend `/api/v1/admin/endpoint-enrollments`) -> `.token` -> rotate
   persona pw after (HARD RULE - don't touch the operator login user).
2. On the denetim PC (WG 10.99.0.2, agent v0.3.3 WDAC-trusted):
   `$env:ENDPOINT_AGENT_AUTO_ENROLL_API_URL='https://testai.acik.com/api/v1/endpoint-agent'` +
   `$env:ENDPOINT_AGENT_ENROLLMENT_TOKEN='<token>'` -> `endpoint-agent.exe --auto-enroll-tpm`
   (token via env; the `--enrollment-token` flag is mutually-exclusive with `--auto-enroll-tpm`).

**Expected (success) — distinct from the 2026-06-26 FEATURE_DISABLED run:**
- `tpm-attest-audit`: `V12 EK/AK RSA 2048 accepted` -> **Vault sign OK** (no `FEATURE_DISABLED`).
- DB `endpoint_admin_service.endpoint_enrollments` row -> `status=CONSUMED` (NOT `TPM_FAILED`).
- A new `endpoint_admin_service.endpoint_tpm_device_binding` (V74) row with the issued leaf + SPKI.
- The issued cert chains to the §4.1 `pki_int` CA, with URI-SAN `tpm:<deviceId>`.

## 7. VERIFY (D29-EA — Up != Functional != Zanzibar)

```bash
# Backend reaches Vault HTTPS + AppRole login works (no FEATURE_DISABLED in audit):
kubectl --context k3d-test -n platform-test logs deploy/endpoint-admin-service --since=5m \
  | grep -iE "FEATURE_DISABLED|vault|approle|sign" | tail
# V74 binding row written for the device:
docker exec platform-pg-test psql -U postgres -d endpoint_admin -tAc \
  "SELECT count(*) FROM endpoint_admin_service.endpoint_tpm_device_binding;"
```

## 8. ROLLBACK

PKI/AppRole are additive - to fully revert: `vault delete auth/approle/role/endpoint-admin-tpm`,
`vault policy delete endpoint-admin-tpm-sign`, `vault secrets disable pki_int` (only if no other consumer),
and flip `ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ENABLED=false` in the overlay + rollout. The `:8200` HTTP plane,
ESO ClusterSecretStore, and every other Vault consumer are untouched throughout.

## Referans

- [`RB-faz22.6-548-vault-https-enablement.md`](./RB-faz22.6-548-vault-https-enablement.md) - companion HTTPS transport (PR #2054).
- PR #2057 - V77 deploy + the live `/attest` FEATURE_DISABLED proof this runbook unblocks.
- Backend gate-4b: `endpoint-admin-service/.../tpmattest/VaultPkiClient.java` + `VaultPkiProperties.java`.
- Codex thread `019efd6b` (Vault server-cert + pinned-CA, not proxy).
