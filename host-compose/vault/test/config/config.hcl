# Vault config — test (ADR-0002 same-host isolated instance)
# Storage: Raft single-node
# Listener: HTTP (host nginx SSL termination)

ui = true

storage "raft" {
  path    = "/vault/data"
  node_id = "vault-test-1"
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_disable   = true
}

api_addr     = "http://platform-vault-test:8200"
cluster_addr = "http://platform-vault-test:8201"

telemetry {
  prometheus_retention_time = "24h"
  disable_hostname          = true
}

log_level = "info"
