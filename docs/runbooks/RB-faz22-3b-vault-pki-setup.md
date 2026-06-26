# RB-faz22-3b-vault-pki-setup — test Vault PKI engine + tpm-device role + backend AppRole for #548 device-cert issuance

> **Tetik:** Faz 22.6 #548 `/attest` step needs the endpoint-admin-service `VaultPkiClient` to sign the
> TPM device CSR (`POST /v1/{mount}/sign/{role}`) → issued leaf cert → `endpoint_tpm_device_binding` (V74)
> row → §3.1 SPKI parity → device-key session. The live `/attest` currently denies with
> `code=FEATURE_DISABLED detail="vault issuance not configured"` (proven 2026-06-26, see PR #2057 evidence):
> the backend `endpoint-admin.tpm-attest.vault.enabled=false` because the PKI mount/role/AppRole do not
> exist yet **and** the test Vault has no HTTPS listener the backend can pin.
>
> **This runbook covers the PKI engine + `tpm-device` sign role + backend AppRole** (the issuance backend).
> It is the prerequisite that the companion HTTPS-transport runbook `RB-faz22.6-548-vault-https-enablement.md`
> (lands in PR #2054) assumes "already provisioned". The two compose: transport (HTTPS listener the backend
> pins) + issuance (this PKI engine) → the backend config flip (§5) → `/attest` signs the CSR.
>
> **Cross-AI:** Codex thread `019efd6b` directed "Vault server-cert + pinned-CA, NOT a proxy" (transport).
> Codex thread `019f0456` reviewed THIS runbook (REVISE→absorbed): SAN-injection gap, clientAuth-only role
> hardening, device-key floor RSA-3072 (not 2048), ESO KV path `kv/platform/endpoint-admin-service`, and a
> hard preflight before the activation flip. Author/implementer: Claude.
>
> **Owner/operator-gated:** writes to the shared, 2-month-stable `platform-vault-test`. The PKI mount +
> role + AppRole are **additive** (new mount path `pki_int`, new auth method `approle`, new policy/role —
> they do NOT touch existing mounts, the KV store, the ESO ClusterSecretStore, or the `:8200` HTTP plane),
> so this step does **not** restart Vault and does **not** risk the parallel-session test plane. The single
> blast-radius step is the HTTPS listener restart in the companion RB (#2054), not this one.

## 1. AMAÇ

Stand up the Vault PKI issuance backend the endpoint-admin-service `VaultPkiClient` (gate-4b, ADR-0039)
expects, so `/attest` signs the TPM device CSR and writes the V74 binding row instead of denying
`FEATURE_DISABLED`. **Out of scope:** the HTTPS transport listener (PR #2054) and the device-key SESSION
broker flip (separate `DEVICE_KEY_ATTESTATION_REAL` broker — NEVER flip the shared denetim-pilot broker).

## 2. KAPSAM (backend contract — code-verified against platform-backend, NOT invented)

The backend `VaultPkiClient` + `VaultPkiProperties` + `TpmCsrPolicy` (prefix `endpoint-admin.tpm-attest.vault`):

| Contract element | Value (code-verified) | Source |
|---|---|---|
| Sign endpoint | `POST /v1/{mount}/sign/{role}` body **exactly** `{"csr":"<PEM>","format":"pem"}` → `data.certificate` | `VaultPkiClient.signCsr` |
| `mount` default | `pki_int` | `VaultPkiProperties` (blank → `pki_int`) |
| `role` default | `tpm-device` | `VaultPkiProperties` (blank → `tpm-device`) |
| Auth | AppRole — `POST /v1/auth/approle/login` `{role_id,secret_id}` → token (lease + renew skew, 403→re-login once) | `VaultPkiClient` |
| `baseUrl` | MUST be `https://` (startup fail-fast otherwise) | `VaultPkiProperties` |
| `caCertPem` | pinned Vault server CA (must contain `BEGIN CERTIFICATE`), required when enabled | `VaultPkiProperties` |
| `roleId`/`secretId` | from ESO / mounted secret, never hardcoded (redacted in toString) | `VaultPkiProperties` |
| Device CSR key floor | **RSA-3072+ / EC-P256+** (`TpmAlgorithmPolicy.Role.DEVICE` `RSA_FLOOR_ISSUED=3072`) — enforced **in the backend**, NOT the Vault role | `TpmCsrPolicy` / `TpmAlgorithmPolicy` |
| Permitted CSR extension | **only** `extendedKeyUsage == {clientAuth}`; basicConstraints / expansive keyUsage / URI-SAN / **any** other extension → `CSR_POLICY_VIOLATION` (uniform 403) | `TpmCsrPolicy` |

**Two roots, never conflate:** the device-cert chain root (`pki_int`, below) ≠ the EK-manufacturer Intel
ODCA root (the `/nonce` EK-chain anchor, `manufacturer-root-sha256=beb40bb7…`).

**Key-floor note (Codex 019f0456 F2):** the `V12 EK/AK RSA-2048 accepted` audit line is the **EK/AK**
constrained floor (`RSA_FLOOR_CONSTRAINED=2048`, WARN-logged). The **device CSR key** floor is **3072**
and is enforced by the backend on the CSR — so the Vault role does NOT pin `key_bits` (the key comes from
the CSR; pinning 2048 here would be a wrong signal and is omitted).

**SAN-injection gap (Codex 019f0456 F1 — MUST track):** `TpmAttestVerdict.sanUri()` is defined as
`"tpm:" + ekPubSha256` and documented as "the SAN URI the backend injects into the Vault PKI issue call",
but `VaultPkiClient.signCsr` currently sends **only** `{csr,format}` — it does **not** pass `uri_sans`.
The CSR itself **cannot** carry the URI-SAN (`TpmCsrPolicy` rejects all extensions except clientAuth EKU).
⇒ **Today the issued leaf carries NO `tpm:<ekPubSha256>` URI-SAN.**

**CN is NON-AUTHORITATIVE (Codex 019f0456 iter-2).** The backend does NOT verify that the CSR CN equals the
server-derived `scope.deviceId()`: the /attest chain binds the CSR **public key** to the attested TPM device
key (`TpmEnrollmentController` + `TpmCsrPolicy`), and the authoritative device identity is the
**server-derived enrollment scope** (`DefaultTpmEnrollmentScopeResolver`) + the **V74
`endpoint_tpm_device_binding` row (SPKI of the device key)** (`TpmEnrollmentCompletionService`). The CN
string is display/debug only and MUST NOT be treated as identity. Completing a trustworthy identity is a
**backend follow-up**: wire `common_name=scope.deviceId()` **and** `uri_sans=verdict.sanUri()` into
`signCsr`'s body; then the Vault role can tighten to `allow_any_name=false`. The role below keeps
`allowed_uri_sans=tpm:*` so that follow-up needs no Vault change — but until it lands, the issued cert's
CN/SAN are NOT authoritative identity.

## 3. ÖNKOŞULLAR (operator)

- Host shell on staging-sw (`ssh halil@staging-sw`), docker control of `platform-vault-test`.
- A privileged Vault token (root or a policy that can `sys/mounts`, `sys/auth`, `sys/policies/acl`, and
  write the pki role). Operator-supplied; this runbook never prints it.
- An **issuing CA** for `pki_int`: (a) generate a self-signed root in-Vault for the test plane, or
  (b) import an intermediate signed offline. The test plane uses (a).
- Companion transport runbook (#2054) ready to apply (the backend needs HTTPS to reach Vault), but the
  PKI engine below can be provisioned first (it works over the existing `:8200` plane).

## 4. ADIMLAR (additive; no Vault restart)

> Run on staging-sw with `VAULT_ADDR=http://127.0.0.1:8200` (host-published test Vault) and the operator
> token exported to the shell (`export VAULT_TOKEN=…` — keep it out of shell history / scripts).

### 4.1 Enable + configure the PKI engine at `pki_int`
```bash
vault secrets enable -path=pki_int pki                      # idempotent: ignore "path is already in use"
vault secrets tune -max-lease-ttl=8760h pki_int
# Test-plane self-signed root (Option a). For Option b, import an intermediate CSR signed offline.
vault write -field=certificate pki_int/root/generate/internal \
    common_name="platform-test endpoint device CA" issuer_name="tpm-device-ca" ttl=8760h \
    key_type=rsa key_bits=4096 > /tmp/pki_int_ca.crt   # the CA's OWN key (4096) — NOT the leaf key floor
vault write pki_int/config/urls \
    issuing_certificates="http://127.0.0.1:8200/v1/pki_int/ca" \
    crl_distribution_points="http://127.0.0.1:8200/v1/pki_int/crl"
```
> Devam eşiği: `vault read pki_int/cert/ca` returns the CA; `/tmp/pki_int_ca.crt` is a valid PEM.

### 4.2 Create the `tpm-device` sign role (clientAuth-only; CN from CSR; key + floor enforced backend-side)
```bash
vault write pki_int/roles/tpm-device \
    allow_any_name=true require_cn=false \
    use_csr_common_name=true use_csr_sans=false \
    allow_ip_sans=false allowed_uri_sans="tpm:*" \
    client_flag=true server_flag=false \
    key_usage="DigitalSignature" ext_key_usage="ClientAuth" \
    max_ttl=72h ttl=24h no_store=false
```
> Codex 019f0456 F2 absorbed: **clientAuth-only** (`client_flag=true server_flag=false`,
> `ext_key_usage=ClientAuth`, `key_usage=DigitalSignature`) so the leaf can never be a server/CA cert;
> **no `key_type`/`key_bits`** (the key comes from the CSR; the backend `TpmCsrPolicy` enforces the
> RSA-3072+/EC-P256+ device floor — pinning here would mis-signal). `use_csr_sans=false` because the CSR
> carries no SAN (policy strips all extensions but clientAuth); `allowed_uri_sans="tpm:*"` is kept for the
> forward `sanUri()` wiring (§2 gap). `allow_any_name=true` is a deliberate **interim** choice: the CSR CN
> is **non-authoritative** (§2 — the backend does not bind it; identity = the server-derived scope + the
> V74 SPKI binding), so Vault name-policy is not the identity gate (the /nonce→/attest chain + AppRole are).
> Target hardening = the §2 backend follow-up (inject `common_name=scope.deviceId` + `uri_sans=sanUri`) →
> then flip this role to `allow_any_name=false`. Until then, treat the leaf CN/SAN as display-only.
> Devam eşiği: `vault read pki_int/roles/tpm-device` shows `client_flag true server_flag false`.

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
    token_ttl=20m token_max_ttl=1h \
    secret_id_ttl=720h secret_id_num_uses=0 token_num_uses=0
ROLE_ID=$(vault read -field=role_id auth/approle/role/endpoint-admin-tpm/role-id)
SECRET_ID=$(vault write -f -field=secret_id auth/approle/role/endpoint-admin-tpm/secret-id)
# Seed roleId/secretId into Vault KV for ESO (do NOT echo; pipe). Path = the ACTUAL ESO remoteRef:
printf '%s' "$ROLE_ID"   | vault kv patch kv/platform/endpoint-admin-service tpm_vault_role_id=-
printf '%s' "$SECRET_ID" | vault kv patch kv/platform/endpoint-admin-service tpm_vault_secret_id=-
unset ROLE_ID SECRET_ID
```
> Codex 019f0456 F3 absorbed: the path is **`kv/platform/endpoint-admin-service`** (the live
> `endpoint-admin-service-secrets` ExternalSecret remoteRef — `…/eso/endpoint-admin/externalsecret.yaml`),
> NOT `kv/platform/endpoint-admin`. A wrong path → ESO never syncs the keys → §5 fail-fast → endpoint-admin DOWN.
> **Rotation (Codex 019f0456 F3):** `secret_id_num_uses=0` (unlimited) is bounded by `secret_id_ttl=720h`;
> schedule a 30-day secret-id rotation (re-issue + ESO refresh) or move to Vault-Agent/response-wrapping
> before any prod-shaped use. The policy is sign-only — it cannot read the KV store or any other mount.

## 5. BACKEND CONFIG ACTIVATION (gitops — the LAST step; HARD preflight gate)

> ⚠️ FAIL-FAST: `VaultPkiProperties` throws at startup if `enabled=true` but `baseUrl` is not `https://`
> or `caCertPem` is unpinned or `roleId`/`secretId` are blank → endpoint-admin DOWN (breaks the
> parallel-session test plane). `enabled=true` MUST be the **last** patch, only after ALL preflight passes.

**Ordering (Codex 019f0456 iter-2):** apply the ExternalSecret mapping (§5.2) + the config keys WITHOUT
`ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ENABLED` FIRST, wait for ESO Ready + BOTH synced keys non-empty, run the
preflight below against the **ESO-synced** roleId/secretId, and only then add `…_ENABLED: "true"` in a
final patch. This proves the exact creds the pod will use — not just that the role works.
```bash
# (a) PKI role + clientAuth shape exist:
vault read pki_int/roles/tpm-device | grep -E "client_flag|server_flag"      # expect true / false
# (b) ESO is Ready AND BOTH synced keys are present (NOT just role_id — secret_id blank → fail-fast DOWN):
kubectl --context k3d-test -n platform-test get externalsecret endpoint-admin-service-secrets \
  -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'                # expect True
for k in ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ROLE_ID ENDPOINT_ADMIN_TPM_ATTEST_VAULT_SECRET_ID; do
  v=$(kubectl --context k3d-test -n platform-test get secret endpoint-admin-service-secrets -o jsonpath="{.data.$k}")
  [ -n "$v" ] && echo "$k=present" || { echo "$k=MISSING — fix ESO remoteRef before flip"; }
done
# (c) the EXACT ESO-synced creds log in AND can sign (redacted; values never printed; unset after):
RID=$(kubectl --context k3d-test -n platform-test get secret endpoint-admin-service-secrets -o jsonpath='{.data.ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ROLE_ID}' | base64 -d)
SID=$(kubectl --context k3d-test -n platform-test get secret endpoint-admin-service-secrets -o jsonpath='{.data.ENDPOINT_ADMIN_TPM_ATTEST_VAULT_SECRET_ID}' | base64 -d)
VT=$(vault write -field=token auth/approle/login role_id="$RID" secret_id="$SID")
VAULT_TOKEN="$VT" vault write pki_int/sign/tpm-device csr=@/tmp/test-device.csr format=pem >/dev/null \
  && echo "SYNCED_SIGN_OK" || echo "SYNCED_SIGN_FAIL — synced creds cannot sign; fix before flip"
unset RID SID VT
# (d) backend pod can TLS-handshake the HTTPS listener (#2054 live):
kubectl --context k3d-test -n platform-test exec deploy/endpoint-admin-service -- \
  sh -c 'echo | openssl s_client -connect vault.platform-test.svc.cluster.local:8202 2>&1 | grep -i "Verify\|CONNECTED"'
```
> Do NOT add `…_ENABLED: "true"` unless (a) clientAuth shape ✓, (b) ESO Ready=True + BOTH keys present,
> (c) `SYNCED_SIGN_OK` (the pod's actual creds sign), (d) TLS handshake succeeds. Then verify the post-flip
> rollout log shows no `VaultPkiProperties`/`FEATURE_DISABLED` startup error.

### 5.2 The flip (ConfigMap + ExternalSecret; `enabled=true` LAST)
ConfigMap (`endpoint-admin-service-config`, test overlay) JSON6902 add (do NOT inline AppRole creds):
```yaml
ENDPOINT_ADMIN_TPM_ATTEST_VAULT_BASE_URL: "https://vault.platform-test.svc.cluster.local:8202"
ENDPOINT_ADMIN_TPM_ATTEST_VAULT_MOUNT: "pki_int"
ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ROLE: "tpm-device"
ENDPOINT_ADMIN_TPM_ATTEST_VAULT_CA_CERT_PEM: "<the #2054 gen-vault-test-tls CA PEM, multi-line>"
ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ENABLED: "true"   # add THIS line in the final patch only
```
ExternalSecret (`endpoint-admin-service-secrets`): add `tpm_vault_role_id`→
`ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ROLE_ID` and `tpm_vault_secret_id`→
`ENDPOINT_ADMIN_TPM_ATTEST_VAULT_SECRET_ID` from `kv/platform/endpoint-admin-service`.
Then selective `kubectl apply` + `rollout restart deploy/endpoint-admin-service` + browser/console verify
(HARD RULE — deploy sonrası console verify).

## 6. POST-GATE CHAIN COMPLETION (re-run the proven live-/attest recipe)

Once §4 + §5 + #2054 are live, re-run the **proven** live-drive recipe (validated 2026-06-26, recorded in
agent memory `project_faz22_6_548_devkey_session_attestation.md` cont.6 + PR #2057 evidence):

1. Mint a fresh enrollment token: KC master-admin token → reset test persona `c5persona-admin-9001` pw →
   ROPC `frontend` client → `POST https://testai.acik.com/api/v1/endpoint-admin/endpoint-enrollments`
   (gateway Route 23 RewritePath → backend `/api/v1/admin/endpoint-enrollments`) → `.token` → rotate
   persona pw after (HARD RULE — don't touch the operator login user).
2. On the denetim PC (WG 10.99.0.2, agent v0.3.3 WDAC-trusted):
   `$env:ENDPOINT_AGENT_AUTO_ENROLL_API_URL='https://testai.acik.com/api/v1/endpoint-agent'` +
   `$env:ENDPOINT_AGENT_ENROLLMENT_TOKEN='<token>'` → `endpoint-agent.exe --auto-enroll-tpm`
   (token via env; the `--enrollment-token` flag is mutually-exclusive with `--auto-enroll-tpm`).

**Expected (success) — distinct from the 2026-06-26 FEATURE_DISABLED run:**
- `tpm-attest-audit`: device CSR validated (RSA-3072+/EC-P256+, clientAuth-only) → **Vault sign OK** (no `FEATURE_DISABLED`).
- DB `endpoint_admin_service.endpoint_enrollments` row → `status=CONSUMED` (NOT `TPM_FAILED`).
- A new `endpoint_admin_service.endpoint_tpm_device_binding` (V74) row with the issued leaf + SPKI.
- The issued cert chains to the §4.1 `pki_int` CA; clientAuth-only. The authoritative device identity is
  the V74 `endpoint_tpm_device_binding` row (SPKI of the device key) — NOT the leaf CN/SAN, which stay
  non-authoritative until the §2 backend injection follow-up (`common_name=scope.deviceId` + `uri_sans=sanUri`).

## 7. VERIFY (D29-EA — Up != Functional != Zanzibar)

```bash
kubectl --context k3d-test -n platform-test logs deploy/endpoint-admin-service --since=5m \
  | grep -iE "FEATURE_DISABLED|vault|approle|sign|CSR_POLICY" | tail
docker exec platform-pg-test psql -U postgres -d endpoint_admin -tAc \
  "SELECT count(*) FROM endpoint_admin_service.endpoint_tpm_device_binding;"
```

## 8. ROLLBACK

PKI/AppRole are additive — to fully revert: `vault delete auth/approle/role/endpoint-admin-tpm`,
`vault policy delete endpoint-admin-tpm-sign`, `vault secrets disable pki_int` (only if no other consumer),
and flip `ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ENABLED=false` in the overlay + rollout. The `:8200` HTTP plane,
ESO ClusterSecretStore, and every other Vault consumer are untouched throughout.

## 9. Prod-shaping notes (Codex 019f0456 — non-blocking for this test runbook)

- **secret-id handling:** §4.3 / §5.1 pass `secret_id="$SID"` on the command line (argv). It is never
  printed to the transcript, but for a prod-shaped run move to a stdin/JSON or response-wrapping pattern
  (`vault write … -<<<'{"secret_id":"…"}'` or Vault-Agent) so it never lands in argv/process list.
- **`openssl` in the pod (§5.1.d):** the endpoint-admin image is JRE/Ubuntu-based (`sh` present, `openssl`
  not guaranteed). If `openssl s_client` is absent, run the TLS handshake from a short-lived debug pod in
  the SAME namespace + NetworkPolicy egress scope (so the test reflects the real pod's reachability).

## Referans

- `RB-faz22.6-548-vault-https-enablement.md` — companion HTTPS transport (lands in PR #2054).
- PR #2057 — V77 deploy + the live `/attest` FEATURE_DISABLED proof this runbook unblocks.
- Backend gate-4b: `endpoint-admin-service/.../tpmattest/{VaultPkiClient,VaultPkiProperties,TpmCsrPolicy,TpmAlgorithmPolicy,TpmAttestVerdict}.java`.
- Codex threads `019efd6b` (transport: server-cert + pinned-CA, not proxy) + `019f0456` (this runbook REVISE→absorbed).
