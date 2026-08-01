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

# Faz 24 #3240: Speechmatics is selectable only in TEST. Keep this grant out
# of the common/prod policy so production ESO cannot read or materialize the
# SaaS credential without a separate owner/legal activation decision.
path "kv/data/platform/audio-gateway-speechmatics" {
  capabilities = ["read"]
}

# Additional test-specific debug/dev paths may be added later:
# - kv/data/platform/test-fixtures (synthetic test data)
# - kv/data/platform/debug-tokens (ops debug)

# --- Test-specific self-inspection (debug) ---
path "auth/token/lookup-self" {
  capabilities = ["read"]
}
