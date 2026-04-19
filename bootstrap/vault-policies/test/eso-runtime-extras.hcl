# Vault Policy — eso-runtime test extras
# ADR-0002 §3.6: test-specific role binding (common üzerine EK).
# Apply: vault policy write eso-runtime-test-extras bootstrap/vault-policies/test/eso-runtime-extras.hcl
# Role binding: vault write auth/approle/role/eso-runtime \
#   token_policies=eso-runtime,eso-runtime-test-extras

# --- Test-only secret paths (forward-extension, şu an boş) ---
# Test-specific debug/dev paths ileride eklenebilir:
# - kv/data/platform/test-fixtures (synthetic test data)
# - kv/data/platform/debug-tokens (ops debug)

# --- Test-specific self-inspection (debug) ---
path "auth/token/lookup-self" {
  capabilities = ["read"]
}
