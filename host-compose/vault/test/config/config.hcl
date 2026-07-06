# Vault config — test (ADR-0002 same-host isolated instance)
# Storage: Raft single-node
# Listeners:
# - 8200 HTTP keeps the existing ESO path stable.
# - 8202 HTTPS is the Faz 22.6 A1 backend TPM-attestation sign path.

ui = true

storage "raft" {
  path    = "/vault/data"
  node_id = "vault-test-1"
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_disable   = true
}

listener "tcp" {
  address         = "0.0.0.0:8202"
  tls_cert_file   = "/vault/tls/tls.crt"
  tls_key_file    = "/vault/tls/tls.key"
  tls_client_ca_file = "/vault/tls/ca.crt"
}

api_addr     = "http://platform-vault-test:8200"
cluster_addr = "http://platform-vault-test:8201"

telemetry {
  prometheus_retention_time = "24h"
  disable_hostname          = true
}

log_level = "info"
