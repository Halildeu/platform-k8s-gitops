# Vault config — prod (staging-sw-2 D32)
# Storage: Raft single-node MVP (HA ileri iş)
# Listener: HTTP (SSL host nginx'te termine)

ui = true

storage "raft" {
  path    = "/vault/data"
  node_id = "vault-prod-1"
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_disable   = true   # host nginx SSL termination
}

api_addr     = "http://10.9.10.53:8200"
cluster_addr = "http://10.9.10.53:8201"

# Telemetry (Prometheus scrape)
telemetry {
  prometheus_retention_time = "24h"
  disable_hostname          = true
}

# Log level
log_level = "info"
