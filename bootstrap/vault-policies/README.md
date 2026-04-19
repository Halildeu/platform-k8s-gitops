# Vault Policies — ADR-0002 Env-Split Yapı

> **Referans ADR:** [`docs/adr/0002-single-host-dual-cluster.md`](../../docs/adr/0002-single-host-dual-cluster.md) §3.6 Vault Design
> **Tasarım:** `common/` + `prod/` + `test/` ayrık policy; 2 ayrı Vault daemon (prod + test full isolation)
> **Apply (env-specific):** `vault policy write <name> bootstrap/vault-policies/<dir>/<file>.hcl`

---

## 1. Dizin Yapısı (ADR-0002 §3.6)

```
bootstrap/vault-policies/
├── common/
│   └── eso-runtime.hcl              # Her Vault'ta aynı shared paths (kv/data/platform/* + kv/data/gitops/*)
├── prod/
│   └── eso-runtime-extras.hcl       # Prod Vault'a özel ek path/capability
└── test/
    └── eso-runtime-extras.hcl       # Test Vault'a özel ek path/capability
```

## 2. Policy Listesi

| Policy | Dizin | Amaç | Vault (hangi daemon) |
|---|---|---|---|
| `eso-runtime` | `common/` | ESO ExternalSecret read (kv/platform/* + kv/gitops/* + smoke-client) | Hem prod hem test Vault |
| `eso-runtime-prod-extras` | `prod/` | Prod-only ek paths (sys/audit read, forward-extension) | SADECE prod Vault |
| `eso-runtime-test-extras` | `test/` | Test-only ek paths (token self-lookup debug, forward-extension) | SADECE test Vault |

## 3. Apply (Prod Vault)

```bash
# Prod Vault login
export VAULT_ADDR=http://localhost:8200
vault login <prod-root-token>

# Common + prod extras
vault policy write eso-runtime bootstrap/vault-policies/common/eso-runtime.hcl
vault policy write eso-runtime-prod-extras bootstrap/vault-policies/prod/eso-runtime-extras.hcl

# AppRole binding (multi-policy)
vault auth enable approle 2>/dev/null || true
vault write auth/approle/role/eso-runtime \
  token_policies="eso-runtime,eso-runtime-prod-extras" \
  token_ttl=1h \
  token_max_ttl=24h \
  secret_id_ttl=0

# Doğrula (prod'da üç politika bağlı)
vault read auth/approle/role/eso-runtime | grep policies
# Beklenen: token_policies=[eso-runtime eso-runtime-prod-extras]
```

## 4. Apply (Test Vault)

```bash
# Test Vault login (platform-vault-test, port 8201)
export VAULT_ADDR=http://localhost:8201
vault login <test-root-token>

vault policy write eso-runtime bootstrap/vault-policies/common/eso-runtime.hcl
vault policy write eso-runtime-test-extras bootstrap/vault-policies/test/eso-runtime-extras.hcl

vault auth enable approle 2>/dev/null || true
vault write auth/approle/role/eso-runtime \
  token_policies="eso-runtime,eso-runtime-test-extras" \
  token_ttl=1h \
  token_max_ttl=24h \
  secret_id_ttl=0
```

## 5. Apply Pattern (common policy her iki Vault'ta aynı)

Her iki Vault instance'ında `eso-runtime` policy içeriği **birebir aynı** olur. Env-specific fark sadece `extras` policy'de.

Bu yüzden:
- Common policy **her iki Vault'ta ayrı write** edilir (Vault state ayrı)
- Policy dosyası **tek git'te** (drift önleme)
- Rotation/audit **env-independent** (ortak path'ler)

## 6. Rotation + AppRole Secret ID

```bash
# Secret ID generate (her iki env'de ayrı)
vault write -f -field=secret_id auth/approle/role/eso-runtime/secret-id

# K8s Secret create (env-specific context)
kubectl --context k3d-prod -n external-secrets create secret generic \
  vault-approle-secret --from-literal=secret-id="${PROD_SECRET_ID}"

kubectl --context k3d-test -n external-secrets create secret generic \
  vault-approle-secret --from-literal=secret-id="${TEST_SECRET_ID}"
```

**Rotation takvim (day-2-governance §2.1):**
- Prod secret_id: **30 gün**
- Test secret_id: **14 gün**
- Token TTL: 1h (otomatik renew)

## 7. ClusterSecretStore Entegrasyon

`kustomize/base/eso/clustersecretstore-vault.yaml` base tanım:
- `roleId: "eso-runtime"` — literal (placeholder, fail-closed)
- `secretRef.name: vault-approle-secret`, `key: secret-id`

Overlay patch (env-specific UUID):
- `overlays/test/eso/clustersecretstore-patch.yaml` → test Vault `role_id` UUID
- `overlays/prod/eso/clustersecretstore-patch.yaml` → prod Vault `role_id` UUID (OPS-PREREQ gated)

Role ID okuma:
```bash
# Prod Vault
vault read -field=role_id auth/approle/role/eso-runtime/role-id
# → overlays/prod/eso/clustersecretstore-patch.yaml JSON6902 patch'ine commit
```

## 8. Forward-Extension Paths

ADR-0002 §6 forward-extension:
- **Vault replication** (primary-secondary): common policy her iki node'da aynı, extras farklılaşır
- **Common policy büyüdükçe**: yeni dosya ekle `common/eso-runtime-additional.hcl` + both envs write
- **Prod-only external vendor paths**: `prod/eso-runtime-extras.hcl` içine ek path tanımla
- **İkinci host**: Vault replication + common/prod/test aynı yapı kalır

## 9. Open Question (PR #12 iter deferred)

**Vault `api_addr` vs K8s Service endpoint hizalama:**
- Compose `api_addr: http://platform-vault-prod:8200` (intra-network DNS)
- K8s Service `vault.platform-prod.svc.cluster.local:8200` (K8s DNS üzerinden host bridge Endpoints)

Bugün: bilinçli diverge. Vault self-addr intra-compose, K8s tarafı host-bridge Service/Endpoints. ESO ClusterSecretStore K8s Service kullanır.

Gelecek: prod cutover sonrası net entegrasyon runbook'u (PR-next-5 ArgoCD + cutover).

## 10. Negatif Test (policy sınır doğrulama)

```bash
# AppRole login
ROLE_ID=$(vault read -field=role_id auth/approle/role/eso-runtime/role-id)
SECRET_ID=$(vault write -f -field=secret_id auth/approle/role/eso-runtime/secret-id)
APPROLE_TOKEN=$(vault write -field=token auth/approle/login \
  role_id="${ROLE_ID}" secret_id="${SECRET_ID}")

# Pozitif: ESO beklediği path'ler
VAULT_TOKEN="${APPROLE_TOKEN}" vault kv get kv/platform/auth-service     # ✓ read
VAULT_TOKEN="${APPROLE_TOKEN}" vault kv get kv/gitops/ghcr-token          # ✓ read
VAULT_TOKEN="${APPROLE_TOKEN}" vault kv get kv/platform/keycloak/smoke-client  # ✓ read

# Negatif: policy dışı path'ler
VAULT_TOKEN="${APPROLE_TOKEN}" vault kv get kv/root-secret 2>&1            # ✗ permission denied
VAULT_TOKEN="${APPROLE_TOKEN}" vault write kv/platform/auth-service foo=bar 2>&1  # ✗ permission denied (capabilities=read)

# Prod-specific (sys/audit) sadece prod'da PASS
VAULT_TOKEN="${APPROLE_TOKEN}" vault read sys/audit  # Prod: ✓, Test: ✗
```

## 11. Referanslar

- [ADR-0002 §3.6](../../docs/adr/0002-single-host-dual-cluster.md) Vault Design
- [docs/S2-B1-vault-property-matrix.md](../../docs/S2-B1-vault-property-matrix.md) — Vault path + property tablosu
- [docs/day-2-governance.md §2.1](../../docs/day-2-governance.md) — Secret rotation takvim
- [host-compose/BOOTSTRAP.md](../../host-compose/BOOTSTRAP.md) — Fresh bootstrap credential chain
- [kustomize/base/eso/clustersecretstore-vault.yaml](../../kustomize/base/eso/clustersecretstore-vault.yaml) — ClusterSecretStore base
