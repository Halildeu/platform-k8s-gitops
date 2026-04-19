# Vault Policies — versioned HCL şablonları

> **Source:** K8s-6 S2-B1 ESO apply preflight (Codex yedek iş potansiyeli)
> **Apply:** `vault policy write <name> bootstrap/vault-policies/<name>.hcl`

---

## 1. Policy Listesi

| Policy | Amaç | AppRole | Kullanıcı |
|---|---|---|---|
| `eso-runtime` | ESO ExternalSecret read (kv/platform/* + kv/gitops/* + smoke-client) | `eso-runtime` | ESO Operator (K8s ExternalSecret CR) |

## 2. Apply Komutları

### 2.1 Policy yaz

```bash
# Vault login (ops)
export VAULT_ADDR=http://<vault-host>:8200
vault login <root-or-admin-token>

# Policy apply (idempotent, versioned)
vault policy write eso-runtime bootstrap/vault-policies/eso-runtime.hcl

# Doğrula
vault policy read eso-runtime
vault policy list | grep eso-runtime
```

### 2.2 AppRole bağla

```bash
# AppRole engine aktif (idempotent)
vault auth enable approle 2>/dev/null || true

# Role create (token TTL 1h, renewable 24h)
vault write auth/approle/role/eso-runtime \
  token_policies="eso-runtime" \
  token_ttl=1h \
  token_max_ttl=24h \
  secret_id_ttl=0         # non-expiring (rotate manually)

# Role ID al (ESO ClusterSecretStore'da roleId olarak kullanılacak)
vault read -field=role_id auth/approle/role/eso-runtime/role-id

# Secret ID generate (ESO vault-approle-secret K8s secret'ına)
vault write -f -field=secret_id auth/approle/role/eso-runtime/secret-id
```

### 2.3 Test (policy doğrulama)

```bash
# AppRole ile login test
ROLE_ID=$(vault read -field=role_id auth/approle/role/eso-runtime/role-id)
SECRET_ID=$(vault write -f -field=secret_id auth/approle/role/eso-runtime/secret-id)
APPROLE_TOKEN=$(vault write -field=token auth/approle/login \
  role_id="${ROLE_ID}" secret_id="${SECRET_ID}")

# Yeni token ile KV read test
VAULT_TOKEN="${APPROLE_TOKEN}" vault kv get kv/gitops/ghcr-token
# Beklenen: Success (data: username + password)

VAULT_TOKEN="${APPROLE_TOKEN}" vault kv get kv/platform/permission-service
# Beklenen: Success

# Negatif test (policy dışı path)
VAULT_TOKEN="${APPROLE_TOKEN}" vault kv get kv/root-secret 2>&1
# Beklenen: permission denied
```

## 3. K8s Secret ile Entegrasyon

ESO ClusterSecretStore `vault-approle-secret` K8s Secret'ini referans eder:

```bash
# Secret ID'yi K8s Secret'e koy (external-secrets ns)
kubectl --context k3d-<test|prod> -n external-secrets create secret generic \
  vault-approle-secret --from-literal=secret-id="${SECRET_ID}"

# ClusterSecretStore zaten repo'da (overlays/<env>/eso):
#   roleId: eso-runtime (HCL role adı)
#   secretRef.name: vault-approle-secret (bu Secret)
#   secretRef.key: secret-id (Secret data anahtarı)
```

## 4. Rotation Stratejisi

- **Secret ID:** manuel rotate (secret_id_ttl=0). Yeni ID generate + K8s Secret update + ESO rollout restart.
- **Token:** otomatik renew (token_ttl=1h, max 24h). ESO her 1h'de yenisini ister.
- **Policy:** repo'da versioned, Git'te değişiklik → `vault policy write` ile apply.
- **Audit:** `vault audit enable file file_path=/var/log/vault/audit.log` (ops iş).

## 5. Referanslar

- `docs/S2-B1-vault-property-matrix.md` — Vault path + property tablosu
- `docs/handoff-S2-B-artifact-hardening.md` — ESO W1 ghcr-pull
- `kustomize/base/eso/clustersecretstore-vault.yaml` — roleId + secretRef
- `kustomize/overlays/<env>/eso/` — overlay-specific FQDN + ExternalSecret
