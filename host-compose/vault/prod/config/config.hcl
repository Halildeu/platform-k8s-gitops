# Vault config — prod (ADR-0002 same-host isolated instance)
# Storage: Raft single-node (forward-extension: replication/HA cluster)
# Listener: HTTP (SSL host nginx'te termine)
# API/cluster addr: container hostname (platform-prod-net DNS)

ui = true

storage "raft" {
  path    = "/vault/data"
  node_id = "vault-prod-1"
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_disable   = true   # host nginx SSL termination
}

api_addr     = "http://platform-vault-prod:8200"
cluster_addr = "http://platform-vault-prod:8201"

# Telemetry (Prometheus scrape)
telemetry {
  prometheus_retention_time = "24h"
  disable_hostname          = true
}

# Log level
log_level = "info"
