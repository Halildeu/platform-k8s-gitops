#!/usr/bin/env bash
# Provision the test-only Vault HTTPS listener material for Faz 22.6 #548 A1.
#
# This script generates non-production TLS material on staging-sw without
# printing private keys or tokens. It is idempotent by default: existing files
# are not overwritten unless FORCE=1 is set.

set -euo pipefail

SSH_TARGET="${SSH_TARGET:-staging-sw}"
VAULT_TLS_DIR="${VAULT_TLS_DIR:-/home/halil/platform-stateful/test/vault/tls}"
VAULT_COMPOSE_DIR="${VAULT_COMPOSE_DIR:-/home/halil/platform-k8s-gitops/host-compose/vault/test}"
RESTART_VAULT="${RESTART_VAULT:-0}"
FORCE="${FORCE:-0}"

if [ -z "${SSH_AUTH_SOCK:-}" ] && command -v launchctl >/dev/null 2>&1; then
  launchd_ssh_auth_sock="$(launchctl getenv SSH_AUTH_SOCK 2>/dev/null || true)"
  if [ -n "$launchd_ssh_auth_sock" ]; then
    export SSH_AUTH_SOCK="$launchd_ssh_auth_sock"
  fi
fi

ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_TARGET" \
  "VAULT_TLS_DIR='$VAULT_TLS_DIR' VAULT_COMPOSE_DIR='$VAULT_COMPOSE_DIR' RESTART_VAULT='$RESTART_VAULT' FORCE='$FORCE' bash -se" <<'REMOTE'
set -euo pipefail

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "FAIL missing command: $1" >&2
    exit 1
  }
}

need openssl
need docker
need sudo

echo "A1_VAULT_HTTPS_PROVISION_BEGIN host=$(hostname) tls_dir=$VAULT_TLS_DIR restart=$RESTART_VAULT force=$FORCE"

existing_count=0
for f in ca.crt tls.crt tls.key; do
  if [ -e "$VAULT_TLS_DIR/$f" ]; then
    existing_count=$((existing_count + 1))
  fi
done

generate_material=1
if [ "$FORCE" != "1" ] && [ "$existing_count" -eq 3 ]; then
  generate_material=0
  echo "INFO existing complete TLS material set will be reused"
elif [ "$FORCE" != "1" ] && [ "$existing_count" -gt 0 ]; then
  echo "FAIL partial TLS material set in $VAULT_TLS_DIR; set FORCE=1 to rotate test TLS material" >&2
  exit 1
fi

if [ "$generate_material" -eq 1 ]; then
  work="$(mktemp -d)"
  cleanup() {
    rm -rf "$work"
  }
  trap cleanup EXIT
  umask 077

  cat >"$work/openssl.cnf" <<'EOF'
[req]
default_bits = 3072
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = req_ext

[dn]
CN = vault.platform-test.svc.cluster.local
O = platform-test
OU = faz22.6-a1

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = vault.platform-test.svc.cluster.local
DNS.2 = vault.platform-test.svc
DNS.3 = vault
DNS.4 = platform-vault-test
DNS.5 = localhost
IP.1 = 127.0.0.1
IP.2 = 172.19.0.4
EOF

  cat >"$work/v3.ext" <<'EOF'
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=@alt_names

[alt_names]
DNS.1 = vault.platform-test.svc.cluster.local
DNS.2 = vault.platform-test.svc
DNS.3 = vault
DNS.4 = platform-vault-test
DNS.5 = localhost
IP.1 = 127.0.0.1
IP.2 = 172.19.0.4
EOF

  openssl genrsa -out "$work/ca.key" 4096 >/dev/null 2>&1
  openssl req -x509 -new -nodes -key "$work/ca.key" -sha256 -days 825 \
    -subj "/CN=platform-test-vault-a1-ca/O=platform-test/OU=faz22.6-a1" \
    -out "$work/ca.crt" >/dev/null 2>&1

  openssl genrsa -out "$work/tls.key" 3072 >/dev/null 2>&1
  openssl req -new -key "$work/tls.key" -out "$work/tls.csr" -config "$work/openssl.cnf" >/dev/null 2>&1
  openssl x509 -req -in "$work/tls.csr" -CA "$work/ca.crt" -CAkey "$work/ca.key" \
    -CAcreateserial -out "$work/tls.crt" -days 397 -sha256 -extfile "$work/v3.ext" >/dev/null 2>&1

  sudo -n install -d -m 0755 -o root -g 1000 "$VAULT_TLS_DIR"
  sudo -n install -m 0644 -o root -g 1000 "$work/ca.crt" "$VAULT_TLS_DIR/ca.crt"
  sudo -n install -m 0644 -o root -g 1000 "$work/tls.crt" "$VAULT_TLS_DIR/tls.crt"
  sudo -n install -m 0640 -o root -g 1000 "$work/tls.key" "$VAULT_TLS_DIR/tls.key"
  echo "PASS tls material written (private key not printed)"
else
  sudo -n chmod 0755 "$VAULT_TLS_DIR"
  sudo -n chmod 0644 "$VAULT_TLS_DIR/ca.crt" "$VAULT_TLS_DIR/tls.crt"
  sudo -n chmod 0640 "$VAULT_TLS_DIR/tls.key"
  echo "PASS tls material present (private key not printed)"
fi

openssl x509 -in "$VAULT_TLS_DIR/ca.crt" -noout -fingerprint -sha256 -subject -issuer
openssl x509 -in "$VAULT_TLS_DIR/tls.crt" -noout -fingerprint -sha256 -subject -issuer

if [ "$RESTART_VAULT" = "1" ]; then
  cd "$VAULT_COMPOSE_DIR"
  docker compose --profile manual up -d --force-recreate vault >/dev/null
  docker exec platform-vault-test sh -c \
    'VAULT_ADDR=https://127.0.0.1:8202 VAULT_CACERT=/vault/tls/ca.crt vault status -format=json >/dev/null'
  echo "PASS vault https 8202 CA-pinned status works"
else
  echo "INFO restart skipped; set RESTART_VAULT=1 after the compose/config change is present on staging-sw"
fi

echo "A1_VAULT_HTTPS_PROVISION_END"
REMOTE
