#!/usr/bin/env bash
# host-compose/vault/test/tls/gen-vault-test-tls.sh
#
# Faz 22.6 #548 — generate the internal-CA TLS material for the platform-vault-test HTTPS listener
# (config.hcl :8202). OPERATOR runs this HOST-SIDE on staging-sw; the private key is written 0600 and
# is NEVER committed (see .gitignore). Outputs land in ../config/tls/ which is the container's
# /vault/config/tls/ mount, so the running platform-vault-test sees them after a restart.
#
# Outputs:
#   host-compose/vault/test/tls/ca/vault-test-ca.key          host-only CA private key — NEVER mounted/committed
#   host-compose/vault/test/tls/ca/vault-test-ca.crt          CA public cert — RAW PEM copied into caCertPem (pinning)
#   host-compose/vault/test/config/tls/vault-test-server.key  Vault server key — mounted read-only (tls_key_file)
#   host-compose/vault/test/config/tls/vault-test-server.crt  Vault server cert — mounted read-only (tls_cert_file)
#
# Idempotent: re-running regenerates the SERVER cert against the EXISTING CA (so the pinned CA is stable
# across server-cert rotations). Delete vault-test-ca.* to mint a fresh CA (then re-pin in the backend).
#
# This is a lab/test-tier internal CA for the isolated test Vault only — NOT the AG-018 code-signing CA,
# NOT a production trust anchor. Scope: TLS for the in-cluster backend→test-Vault hop.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# OUT = the container's /vault/config/tls/ mount (:ro in the container). ONLY the server cert+key land
# here. The CA PRIVATE KEY must NEVER be inside the container mount (Codex 019f02db Must-Fix #1) — it
# lives in a host-only sibling dir; only the CA *public* cert is exported for backend pinning.
OUT="$HERE/../config/tls"
CA_DIR="$HERE/ca"            # host-only, NOT bind-mounted into platform-vault-test
mkdir -p "$OUT" "$CA_DIR"
chmod 0750 "$OUT"
chmod 0700 "$CA_DIR"

CA_KEY="$CA_DIR/vault-test-ca.key"   # host-only custody — never in /vault/config, never committed
CA_CRT="$CA_DIR/vault-test-ca.crt"   # CA public cert -> RAW PEM into backend caCertPem (pinning, NOT base64)
SRV_KEY="$OUT/vault-test-server.key"
SRV_CRT="$OUT/vault-test-server.crt"
SRV_CSR="$OUT/vault-test-server.csr"

DAYS_CA="${DAYS_CA:-1825}"     # CA 5y
DAYS_SRV="${DAYS_SRV:-825}"    # server cert ~27mo (CA/B-ish ceiling; rotate via re-run)

# SANs the backend may use to reach the test Vault (in-cluster Service DNS + container name + loopback).
SAN_DNS_1="vault.platform-test.svc.cluster.local"
SAN_DNS_2="platform-vault-test"
SAN_DNS_3="localhost"
SAN_IP_1="127.0.0.1"

echo "[gen-vault-test-tls] output dir: $OUT"

# --- 1. internal CA (reuse if present so the pinned CA stays stable) -------------------------------
if [[ -f "$CA_KEY" && -f "$CA_CRT" ]]; then
  echo "[gen-vault-test-tls] reusing existing CA ($CA_CRT) — server cert will chain to it"
else
  echo "[gen-vault-test-tls] minting fresh internal CA"
  openssl genrsa -out "$CA_KEY" 4096
  chmod 0600 "$CA_KEY"
  openssl req -x509 -new -nodes -key "$CA_KEY" -sha256 -days "$DAYS_CA" \
    -subj "/CN=platform-vault-test internal CA (Faz22.6 #548 lab)/O=acik/OU=endpoint-admin" \
    -out "$CA_CRT"
fi

# --- 2. server key + CSR ----------------------------------------------------------------------------
openssl genrsa -out "$SRV_KEY" 2048
chmod 0600 "$SRV_KEY"
openssl req -new -key "$SRV_KEY" \
  -subj "/CN=${SAN_DNS_1}/O=acik/OU=endpoint-admin" \
  -out "$SRV_CSR"

# --- 3. sign server cert with SANs + clientAuth-free serverAuth EKU ---------------------------------
EXT_FILE="$(mktemp)"
trap 'rm -f "$EXT_FILE"' EXIT
cat > "$EXT_FILE" <<EOF
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:${SAN_DNS_1}, DNS:${SAN_DNS_2}, DNS:${SAN_DNS_3}, IP:${SAN_IP_1}
EOF

openssl x509 -req -in "$SRV_CSR" -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
  -sha256 -days "$DAYS_SRV" -extfile "$EXT_FILE" -out "$SRV_CRT"
rm -f "$SRV_CSR"

# Server key must be READABLE BY THE VAULT CONTAINER PROCESS (Codex 019f02db Must-Fix #1): the mount is
# :ro, so the host file's ownership is what UID 100 (hashicorp/vault) sees. chown to 100 (needs root —
# operator runs this with sudo); 0640 so the chowned group can read. If chown can't run, the operator
# MUST fix readability before restart or Vault won't start (preflight in the runbook catches this).
chmod 0640 "$SRV_KEY"
# The Vault container (UID 100) must both TRAVERSE $OUT and READ the key over the :ro mount, so chown
# BOTH the dir AND the server key/cert to 100:100 (Codex 019f02db re-review #1 — owning the key but not
# the dir still blocks traversal). CA_DIR stays host-only 0700 (never chowned to the container).
if chown 100:100 "$OUT" "$SRV_KEY" "$SRV_CRT" 2>/dev/null; then
  echo "[gen-vault-test-tls] $OUT + server key/cert chowned 100:100 (hashicorp/vault container UID)"
else
  echo "[gen-vault-test-tls] WARN: chown 100:100 failed (not root?) — Vault (UID 100) may not TRAVERSE"
  echo "    $OUT or READ the key over the :ro mount. Run as root/sudo; confirm the UID via"
  echo "    'docker exec platform-vault-test id', then chown the DIR + key to it — else"
  echo "    'docker restart platform-vault-test' fails to load the TLS cert (preflight catches this)."
fi

# --- 4. report --------------------------------------------------------------------------------------
echo "[gen-vault-test-tls] done:"
openssl x509 -in "$SRV_CRT" -noout -subject -issuer -dates -ext subjectAltName | sed 's/^/    /'
echo
echo "Next (operator):"
echo "  1. restart platform-vault-test so config.hcl :8202 picks up the cert"
echo "     (verify: docker logs platform-vault-test 2>&1 | grep -i 'listener\\|tls')"
echo "  2. pin the CA in the backend — the RAW PEM of $CA_CRT (NOT base64) is the value of"
echo "     endpoint-admin.tpm-attest.vault.ca-cert-pem (backend asserts it contains BEGIN CERTIFICATE)."
echo "     e.g. Vault KV:  vault kv patch <path> tpm_vault_ca_cert_pem=\"\$(cat $CA_CRT)\""
echo "     (the K8s Secret .data layer base64s for transport; the PROPERTY value stays raw PEM)."
echo "     + set endpoint-admin.tpm-attest.vault.base-url=https://${SAN_DNS_1}:8202"
echo "  3. see docs/runbooks/RB-faz22.6-548-vault-https-enablement.md for the full sequence"
