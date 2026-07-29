# Vault Policy — meeting-analysis-capability-writer-test
#
# Faz 24 #3144. TEST-only write boundary for the shared analysis capability
# trust root. Bound only to platform-bootstrap-writer-test in the reconciler.
# The platform-ops wrapper narrows this path further to one exact
# hmac_secret_base64 property supplied over stdin.

path "kv/data/platform/meeting-analysis-capability" {
  capabilities = ["create", "update", "read"]
}
