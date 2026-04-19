# Vault Policy — eso-runtime prod extras
# ADR-0002 §3.6: prod-specific role binding için env-specific policy.
# Bu dosya common/eso-runtime.hcl üzerine EK paths + capabilities tanımlar.
# Apply: vault policy write eso-runtime-prod-extras bootstrap/vault-policies/prod/eso-runtime-extras.hcl
# Role binding: vault write auth/approle/role/eso-runtime \
#   token_policies=eso-runtime,eso-runtime-prod-extras

# --- Prod-only secret paths (forward-extension, şu an boş) ---
# İleride prod-only secret'lar için path eklenir:
# - kv/data/platform-prod/* (prod-only env-prefix path varyantı)
# - kv/data/platform/external-vendor (prod-only API key)
# Boş policy merge-time geçerli, apply edilebilir (Vault boş policy kabul eder).

# --- Read-only ack for audit path (prod audit log meta) ---
path "sys/audit" {
  capabilities = ["read"]
}
