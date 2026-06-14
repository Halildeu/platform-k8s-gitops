# RB-faz22-3b-vault-pki-setup — Vault PKI engine for Faz 22.3B device certs

ID: RB-faz22-3b-vault-pki-setup
Service: HashiCorp Vault PKI secrets engine (endpoint device-cert CA)
Status: Canonical (gitops authoritative) — **operator-executed**
Owner: @team/platform
Gate: **Gate 2** of [ADR-0039](../adr/0039-faz-22-3b-tpm-attestation-vault-pki.md) (Faz 22.3B)

> **Disabled-from-live-issuance.** This runbook stands up the Vault PKI CA + the
> `tpm-device` role + the least-privilege backend AppRole. **No certificate is
> issued in production until** the backend attestation verifier (gate 4) is
> deployed AND its feature flag is flipped on per-tenant. Standing up the CA is
> inert until then. Parallel to AD CS (Faz 22.3A); does not touch it.

-------------------------------------------------------------------------------
## 1. AMAÇ
-------------------------------------------------------------------------------
Faz 22.3B'nin domain-less/BYOD/macOS-Linux cihaz mTLS yolunda, TPM attestation
doğrulandıktan sonra backend'in **kısa-ömürlü clientAuth cert** issue ettiği
**Vault PKI** CA'sını kurmak. Cert kimliği `SAN URI = tpm:{ek_pub_sha256}`;
özel anahtar cihazın TPM'inde (backend yalnız CSR public-key'ini imzalar).

-------------------------------------------------------------------------------
## 2. KAPSAM
-------------------------------------------------------------------------------
**Kurar:** offline root → intermediate PKI mount → `tpm-device` role →
OCSP/CRL → backend least-privilege AppRole+policy.
**Kurmaz / KAPSAMDIŞI:** live issuance (gate 4 + flag), agent enrollment
(gate 3), AD CS (Faz 22.3A — Codex). Root key Transit/HSM + Shamir 3-of-5.

-------------------------------------------------------------------------------
## 3. ÖNKOŞULLAR (operator / Vault-admin)
-------------------------------------------------------------------------------
- Vault unsealed; admin token; ADR-0010 credential-lifecycle disiplinine uyum.
- **Transit engine** veya **HSM/managed-keys (PKCS#11)** signing için hazır.
- Root custody: **Shamir 3-of-5** unseal/recovery key holders belirlenmiş.
- ADR-0039 + `docs/faz-22-3b-tpm-attestation-design.md` §5 okunmuş.

-------------------------------------------------------------------------------
## 4. ADIMLAR
-------------------------------------------------------------------------------

### 4.1 Root CA — offline, ayrı mount (issuance'a açık DEĞİL)
```bash
vault secrets enable -path=pki_endpoint_root pki
vault secrets tune -max-lease-ttl=87600h pki_endpoint_root          # 10y root
# Tercih: managed-key (HSM/PKCS#11) ya da Transit-backed root key.
vault write -field=certificate pki_endpoint_root/root/generate/internal \
    common_name="ACIK Endpoint Device Root CA" issuer_name="endpoint-root" \
    key_type=ec key_bits=384 ttl=87600h > endpoint_root_ca.crt
# Root key ONLINE issuance'a kapalı: yalnız intermediate'i imzalar (4.2), sonra
# root mount erişimi kısıtlanır / offline alınır (Shamir custody).
```

### 4.2 Intermediate (issuance mount)
```bash
vault secrets enable -path=pki_endpoint_device pki
vault secrets tune -max-lease-ttl=720h pki_endpoint_device          # 30d cap
vault write -field=csr pki_endpoint_device/intermediate/generate/internal \
    common_name="ACIK Endpoint Device Issuing CA" key_type=ec key_bits=384 \
    > endpoint_int.csr
vault write -field=certificate pki_endpoint_root/root/sign-intermediate \
    csr=@endpoint_int.csr format=pem_bundle ttl=43800h \
    max_path_length=0 > endpoint_int.crt                # 5y; max_path_length=0 ⇒ NO sub-CA (Codex)
vault write pki_endpoint_device/intermediate/set-signed certificate=@endpoint_int.crt
```

### 4.3 OCSP/CRL (CDP/AIA + propagation SLO)
```bash
vault write pki_endpoint_device/config/urls \
    issuing_certificates="https://vault.internal/v1/pki_endpoint_device/ca" \
    crl_distribution_points="https://vault.internal/v1/pki_endpoint_device/crl" \
    ocsp_servers="https://vault.internal/v1/pki_endpoint_device/ocsp"
vault write pki_endpoint_device/config/crl expiry=24h ocsp_disable=false \
    auto_rebuild=true auto_rebuild_grace_period=12h
# SLO: CRL/OCSP propagation < auto_rebuild_grace_period; measured at pilot.
```

### 4.4 `tpm-device` role (clientAuth-only, short-TTL, SAN/CN backend-overridden)
```bash
vault write pki_endpoint_device/roles/tpm-device \
    allow_any_name=false require_cn=false \
    use_csr_common_name=false use_csr_sans=false \
    allowed_uri_sans="tpm:*" allowed_uri_sans_template=false \
    client_flag=true server_flag=false \
    key_usage="DigitalSignature" ext_key_usage="ClientAuth" \
    ext_key_usage_oids="" \
    key_type="any" signature_bits=256 \
    ttl=168h max_ttl=168h \
    no_store=false generate_lease=false
```
- **`use_csr_sans=false` + `use_csr_common_name=false`** → agent CSR'ındaki SAN/CN
  YOK SAYILIR; backend `issue` çağrısında `uri_sans=tpm:{ek_pub_sha256}` +
  `common_name={deviceUuid}` enjekte eder (design §5/§6). Role yalnız `tpm:*`
  URI SAN'a izin verir; başka SAN tipi (DNS/IP/email) reddedilir.
- **clientAuth-only**: `server_flag=false`, EKU=ClientAuth. Başka critical
  extension yok (`ext_key_usage_oids=""`).
- **Short-TTL 168h**: renewal re-attests (design §7). `max_ttl` cap'li.
- CSR key-policy (design V9): zayıf anahtar reddi backend tarafında da
  enforce edilir (RSA-3072+/ECDSA-P256+); role `signature_bits=256`.

### 4.5 Backend least-privilege AppRole + policy
```hcl
# policy: endpoint-device-pki-issuer  (ONLY issue on the tpm-device role)
path "pki_endpoint_device/issue/tpm-device" { capabilities = ["create","update"] }
path "pki_endpoint_device/revoke"           { capabilities = ["create","update"] }
# NO access to root/intermediate keys, NO other PKI paths, NO config.
```
```bash
vault policy write endpoint-device-pki-issuer endpoint-device-pki-issuer.hcl
vault write auth/approle/role/endpoint-admin-tpm-pki \
    token_policies="endpoint-device-pki-issuer" \
    token_ttl=20m token_max_ttl=30m secret_id_ttl=0 \
    secret_id_num_uses=0 token_num_uses=0
# RoleID/SecretID → ESO/Spring-Cloud-Vault path (RB-eso-vault-approle-rotate
# disiplini). Backend yalnız issue+revoke; CA key'e erişemez.
```
ESO: backend'in mevcut Vault auth zinciri (Spring Cloud Vault / ESO AppRole)
bu policy'i alır; ayrı bir `ExternalSecret` gerekmiyorsa AppRole token-policy
yeterli. Gerekirse `kustomize/overlays/<env>/eso/endpoint-admin/` altına
`externalsecret-endpoint-tpm-pki.yaml` eklenir (gate 4 PR'ında, flag'le).

-------------------------------------------------------------------------------
## 5. DOĞRULAMA (sandbox; live issuance KAPALI kalır)
-------------------------------------------------------------------------------
```bash
# Role var + clientAuth-only + SAN override:
vault read pki_endpoint_device/roles/tpm-device | grep -E "use_csr_sans|server_flag|ext_key_usage|max_ttl"
# Sandbox test-issue (sonra revoke): backend'in yapacağı çağrı şekli
SER=$(vault write -field=serial_number pki_endpoint_device/issue/tpm-device \
    csr=@test.csr uri_sans="tpm:deadbeef..." common_name="00000000-..." ttl=1h)
vault write pki_endpoint_device/revoke serial_number="$SER"
# AppRole least-privilege negatif: issuer token CA key/config OKUYAMAZ
VAULT_TOKEN=<approle-token> vault read pki_endpoint_device/cert/ca && echo "FAIL: should be denied"
```
Beklenen: role clientAuth-only + `use_csr_sans=false`; AppRole yalnız issue/revoke,
CA key read **denied**.

**Operasyonel doğrulama checklist (Codex 019ec723 — uygulamada zorunlu):**
- [ ] **Vault-sürüm testi:** `allowed_uri_sans="tpm:*"` glob'unun bu Vault sürümünde beklendiği gibi match ettiği + `use_csr_sans=false` ile agent CSR SAN/CN'inin gerçekten yok sayıldığı sandbox'ta kanıtlanır (sürüm davranış farkı riski).
- [ ] **Sub-CA engeli:** intermediate `max_path_length=0` → issue edilen leaf'ten alt-CA türetilemediği doğrulanır.
- [ ] **V9 leaf-policy deny:** zayıf-anahtar (RSA<3072 / ECDSA<P256) + clientAuth-dışı critical-ext içeren CSR'ın backend tarafında **deny** edildiği test edilir (sadece role config değil, runtime deny).
- [ ] **OCSP/CRL propagation ÖLÇÜLÜR** (yalnız configure değil): revoke → CRL/OCSP yansıma gecikmesi `auto_rebuild_grace_period` altında, pilot'ta metrikle.
- [ ] **Disable = fail-closed + alarm:** `vault secrets disable` / seal sırasında backend issuance'ın tam fail-closed olduğu + alarm tetiklendiği test edilir (gate 5 CA-resilience).
- [ ] **AppRole per-request short token** (hardening): backend tarafı issuance token'ını mümkünse tek-talep-ömürlü döngüye taşır.

-------------------------------------------------------------------------------
## 6. ROLLBACK / DR (ADR-0039 R-3)
-------------------------------------------------------------------------------
- **Seal/unseal**: Shamir 3-of-5; unseal key holders ayrı. Seal sırasında
  issuance fail-closed (backend gate 4 fail-closed davranışı).
- **Intermediate rollover**: yeni intermediate sign + eski'yi CRL'e; grace
  period boyunca iki intermediate trusted.
- **Root-compromise recovery**: root offline olduğu için blast-radius dar;
  yeni root + yeni intermediate + tüm device re-enroll (attestation). Metrikli
  drill **gate 5** (CA-resilience) kapsamında — pilot öncesi zorunlu.
- **Disable**: `vault secrets disable pki_endpoint_device` tüm issuance'ı durdurur
  (backend flag off + bu = tam fail-closed).

-------------------------------------------------------------------------------
## 7. REFERANS
-------------------------------------------------------------------------------
- [ADR-0039](../adr/0039-faz-22-3b-tpm-attestation-vault-pki.md) §5 (Vault PKI), R-3
- `docs/faz-22-3b-tpm-attestation-design.md` §5–6 (role + identity resolver)
- [ADR-0010](../adr/0010-vault-credential-lifecycle-and-dr.md) (Vault credential lifecycle/DR)
- `docs/runbooks/RB-eso-vault-approle-rotate.md` (AppRole rotation)
- HashiCorp Vault PKI secrets engine; CA/Browser Forum + NIST SP 800-57 (key sizes), TCG TPM 2.0
