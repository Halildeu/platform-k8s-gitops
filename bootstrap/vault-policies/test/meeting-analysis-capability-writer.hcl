# Vault Policy — meeting-analysis-capability-writer-test
#
# Faz 24 #3144. TEST-only write boundary for the shared analysis capability
# trust root. Bound only to platform-bootstrap-writer-test in the reconciler.
# The platform-ops wrapper enforces one exact hmac_secret_base64 property over
# stdin for the reviewed operational flow. Vault ACLs are path-granular, so
# this property restriction is not a hard boundary against direct API use.
# Read is required for the wrapper's KV-v2 version read and CAS merge; the
# short-lived writer credential therefore has temporary trust-root read access.

path "kv/data/platform/meeting-analysis-capability" {
  capabilities = ["create", "update", "read"]
}
