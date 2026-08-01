# Vault Policy — eso-runtime test extras
# ADR-0002 §3.6: test-specific role binding (common üzerine EK).
# Apply: vault policy write eso-runtime-test-extras bootstrap/vault-policies/test/eso-runtime-extras.hcl
# Role binding: vault write auth/approle/role/eso-runtime \
#   token_policies=eso-runtime,eso-runtime-test-extras

# --- Test-only secret paths ---
# Faz 24 #3144: transcript-service issues and meeting-service verifies the same
# short-lived HS256 analysis capability. Both ExternalSecrets read one remote
# property into separate workload-owned target Secrets.
path "kv/data/platform/meeting-analysis-capability" {
  capabilities = ["read"]
}

# Additional test-specific debug/dev paths may be added later:
# - kv/data/platform/test-fixtures (synthetic test data)
# - kv/data/platform/debug-tokens (ops debug)

# --- Test-specific self-inspection (debug) ---
path "auth/token/lookup-self" {
  capabilities = ["read"]
}
