# Vault config — test (ADR-0002 same-host isolated instance)
# Storage: Raft single-node
# Listeners:
#   - HTTP  :8200  host nginx SSL termination + ESO ClusterSecretStore + all existing consumers (UNCHANGED)
#   - HTTPS :8202  Faz 22.6 #548 — endpoint-admin-service VaultPkiClient fail-fasts unless
#                  endpoint-admin.tpm-attest.vault.base-url is https:// with a pinned CA. ADDITIVE so the
#                  :8200 HTTP plane (nginx/ESO) is untouched; the backend reaches :8202 in-cluster and pins
#                  the internal CA. Server cert/key are operator-generated host-side and NEVER committed
#                  (host-compose/vault/test/tls/gen-vault-test-tls.sh → /vault/config/tls/). Vault REFUSES to
#                  start if tls_cert_file is absent, so apply this listener ONLY after the cert files exist.
#                  Full procedure: docs/runbooks/RB-faz22.6-548-vault-https-enablement.md

ui = true

storage "raft" {
  path    = "/vault/data"
  node_id = "vault-test-1"
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_disable   = true
}

# Faz 22.6 #548 — additive TLS listener for the endpoint-admin VaultPkiClient (TPM device-cert issuance).
# Does NOT alter the :8200 HTTP listener above. Operator prerequisites BEFORE container restart:
#   (1) place vault-test-server.{crt,key} in /vault/config/tls/ (gen-vault-test-tls.sh),
#   (2) expose :8202 on the platform-vault-test container + the in-cluster `vault` Service,
#   (3) point the backend at https://vault.platform-test.svc.cluster.local:8202 with the pinned CA PEM.
listener "tcp" {
  address         = "0.0.0.0:8202"
  tls_cert_file   = "/vault/config/tls/vault-test-server.crt"
  tls_key_file    = "/vault/config/tls/vault-test-server.key"
  tls_min_version = "tls12"
}

api_addr     = "http://platform-vault-test:8200"
cluster_addr = "http://platform-vault-test:8201"

telemetry {
  prometheus_retention_time = "24h"
  disable_hostname          = true
}

log_level = "info"
