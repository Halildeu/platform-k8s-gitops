# Vault Policy — eso-runtime
# ExternalSecrets Operator AppRole için okuma yetkisi.
# Apply: vault policy write eso-runtime bootstrap/vault-policies/eso-runtime.hcl
#
# Prereq: Vault KV v2 mount 'kv' aktif (vault secrets enable -version=2 -path=kv kv)
# AppRole: vault write auth/approle/role/eso-runtime token_policies=eso-runtime
#
# Docs: docs/S2-B1-vault-property-matrix.md (tüm path + property tablosu)

# --- Platform servis secret'ları (ESO per-service ExternalSecret'ler) ---
path "kv/data/platform/auth-service" {
  capabilities = ["read"]
}

path "kv/data/platform/user-service" {
  capabilities = ["read"]
}

path "kv/data/platform/variant-service" {
  capabilities = ["read"]
}

path "kv/data/platform/core-data-service" {
  capabilities = ["read"]
}

path "kv/data/platform/report-service" {
  capabilities = ["read"]
}

path "kv/data/platform/schema-service" {
  capabilities = ["read"]
}

path "kv/data/platform/permission-service" {
  capabilities = ["read"]
}

# --- OpenFGA Store + Model ID (D-008 runtime kontrat) ---
path "kv/data/platform/openfga" {
  capabilities = ["read"]
}

# --- D31 opsiyonel MSSQL external (report/schema yorumlu ES) ---
path "kv/data/platform/mssql-external" {
  capabilities = ["read"]
}

# --- S2-B3 smoke-client bearer token (blackbox allow probe) ---
path "kv/data/platform/keycloak/smoke-client" {
  capabilities = ["read"]
}

# --- GHCR pull token (ghcr-pull ExternalSecret) ---
path "kv/data/gitops/ghcr-token" {
  capabilities = ["read"]
}

# --- Metadata read (versioned KV v2 list/describe) ---
path "kv/metadata/platform/*" {
  capabilities = ["list"]
}

path "kv/metadata/gitops/*" {
  capabilities = ["list"]
}
