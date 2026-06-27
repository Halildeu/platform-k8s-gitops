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
VAULT_INIT_JSON="${VAULT_INIT_JSON:-/home/halil/bootstrap-drill/vault-init-test.json}"
RESTART_VAULT="${RESTART_VAULT:-0}"
AUTO_UNSEAL_AFTER_RESTART="${AUTO_UNSEAL_AFTER_RESTART:-1}"
FORCE="${FORCE:-0}"

if [ -z "${SSH_AUTH_SOCK:-}" ] && command -v launchctl >/dev/null 2>&1; then
  launchd_ssh_auth_sock="$(launchctl getenv SSH_AUTH_SOCK 2>/dev/null || true)"
  if [ -n "$launchd_ssh_auth_sock" ]; then
    export SSH_AUTH_SOCK="$launchd_ssh_auth_sock"
  fi
fi

remote_env="VAULT_TLS_DIR='$VAULT_TLS_DIR' VAULT_COMPOSE_DIR='$VAULT_COMPOSE_DIR' VAULT_INIT_JSON='$VAULT_INIT_JSON' RESTART_VAULT='$RESTART_VAULT' AUTO_UNSEAL_AFTER_RESTART='$AUTO_UNSEAL_AFTER_RESTART' FORCE='$FORCE'"

if [ "$SSH_TARGET" = "local" ] || [ "$SSH_TARGET" = "localhost" ] || [ "$SSH_TARGET" = "127.0.0.1" ]; then
  remote_runner=(bash -c "$remote_env bash -se")
else
  remote_runner=(ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_TARGET" "$remote_env bash -se")
fi

"${remote_runner[@]}" <<'REMOTE'
set -euo pipefail

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "FAIL missing command: $1" >&2
    exit 1
  }
}

docker_cli() {
  local docker_bin
  for docker_bin in docker /usr/bin/docker /usr/local/bin/docker /snap/bin/docker; do
    if command -v "$docker_bin" >/dev/null 2>&1 && "$docker_bin" version >/dev/null 2>&1; then
      "$docker_bin" "$@"
      return 0
    fi
    if command -v sudo >/dev/null 2>&1 && sudo -n "$docker_bin" version >/dev/null 2>&1; then
      sudo -n "$docker_bin" "$@"
      return 0
    fi
  done
  return 1
}

docker_api() {
  local method="$1"
  local path="$2"
  local sock
  command -v curl >/dev/null 2>&1 || return 1
  for sock in /var/run/docker.sock /run/docker.sock; do
    if [ -S "$sock" ] && curl -fsS -X "$method" --unix-socket "$sock" "http://localhost$path"; then
      return 0
    fi
  done
  return 1
}

docker_control_available() {
  docker_cli version >/dev/null 2>&1 || docker_api GET /_ping >/dev/null 2>&1
}

docker_inspect_vault() {
  docker_cli inspect platform-vault-test --format '{{json .}}' 2>/dev/null || \
    docker_api GET /containers/platform-vault-test/json
}

docker_vault_has_required_mounts() {
  docker_inspect_vault | jq -e \
    --arg data "/home/halil/platform-stateful/test/vault/data" \
    --arg logs "/home/halil/platform-stateful/test/vault/logs" \
    --arg tls "/home/halil/platform-stateful/test/vault/tls" '
      ([.Mounts[] | select(.Destination == "/vault/data" and (.Source | startswith($data)))] | length == 1) and
      ([.Mounts[] | select(.Destination == "/vault/logs" and (.Source | startswith($logs)))] | length == 1) and
      ([.Mounts[] | select(.Destination == "/vault/tls" and (.Source | startswith($tls)) and .RW == false)] | length == 1)
    ' >/dev/null
}

restart_vault_container() {
  cd "$VAULT_COMPOSE_DIR"
  if docker_cli compose --profile manual up -d --force-recreate vault >/dev/null 2>&1; then
    echo "PASS vault recreated with docker compose"
    return 0
  fi

  if ! docker_vault_has_required_mounts; then
    echo "FAIL Docker CLI/compose unavailable and existing platform-vault-test does not already have required data/log/tls mounts; compose recreate is required" >&2
    return 1
  fi

  if docker_cli restart platform-vault-test >/dev/null 2>&1; then
    echo "PASS vault restarted with docker CLI"
    return 0
  fi
  if docker_api POST /containers/platform-vault-test/restart?t=30 >/dev/null; then
    echo "PASS vault restarted with Docker socket API"
    return 0
  fi

  echo "FAIL Docker control unavailable: no usable CLI restart and no writable Docker socket API" >&2
  return 1
}

vault_status_json() {
  local url
  command -v curl >/dev/null 2>&1 || return 1
  while IFS= read -r url; do
    if curl -fsS --connect-timeout 3 --max-time 10 --cacert "$VAULT_TLS_DIR/ca.crt" \
      "$url/v1/sys/seal-status"; then
      return 0
    fi
  done < <(vault_api_urls)
  return 1
}

vault_api_base() {
  local url
  command -v curl >/dev/null 2>&1 || return 1
  while IFS= read -r url; do
    if curl -fsS --connect-timeout 3 --max-time 10 --cacert "$VAULT_TLS_DIR/ca.crt" \
      "$url/v1/sys/seal-status" >/dev/null; then
      printf '%s\n' "$url"
      return 0
    fi
  done < <(vault_api_urls)
  return 1
}

vault_api_urls() {
  local inspect_json
  local ip
  {
    printf '%s\n' "https://127.0.0.1:8302"
    if inspect_json="$(docker_inspect_vault 2>/dev/null)"; then
      printf '%s\n' "$inspect_json" \
        | jq -r '.NetworkSettings.Networks[]?.IPAddress // empty' 2>/dev/null \
        | while IFS= read -r ip; do
            if [ -n "$ip" ]; then
              printf 'https://%s:8202\n' "$ip"
            fi
          done
    fi
  } | awk '!seen[$0]++'
}

wait_for_vault_status_json() {
  local attempt
  for attempt in $(seq 1 30); do
    if vault_status_json; then
      return 0
    fi
    sleep 2
  done
  return 1
}

unseal_vault_with_key_index() {
  local idx="$1"
  local url
  url="$(vault_api_base)" || return 1
  sudo -n jq -er --argjson idx "$idx" '.unseal_keys_b64[$idx] | select(type == "string" and length > 0)' "$VAULT_INIT_JSON" \
    | jq -Rs 'if length > 1 then {key: rtrimstr("\n")} else halt_error(1) end' \
    | curl -fsS --connect-timeout 3 --max-time 10 --cacert "$VAULT_TLS_DIR/ca.crt" \
      -H 'Content-Type: application/json' --data @- "$url/v1/sys/unseal" >/dev/null
}

need openssl
need sudo
need jq
need curl
docker_control_available || {
  echo "FAIL Docker control unavailable: no usable Docker CLI and no Docker socket API" >&2
  exit 1
}

echo "A1_VAULT_HTTPS_PROVISION_BEGIN host=$(hostname) tls_dir=$VAULT_TLS_DIR restart=$RESTART_VAULT auto_unseal=$AUTO_UNSEAL_AFTER_RESTART force=$FORCE"

if [ "$RESTART_VAULT" = "1" ] && [ "$AUTO_UNSEAL_AFTER_RESTART" = "1" ]; then
  if ! sudo -n test -r "$VAULT_INIT_JSON"; then
    echo "FAIL restart requested but test Vault init JSON is not readable: $VAULT_INIT_JSON" >&2
    exit 1
  fi
  if ! sudo -n jq -e '.unseal_keys_b64 | length >= 2' "$VAULT_INIT_JSON" >/dev/null; then
    echo "FAIL restart requested but $VAULT_INIT_JSON does not contain at least two unseal keys" >&2
    exit 1
  fi
  echo "PASS test Vault unseal material present (values not printed)"
fi

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
  restart_vault_container

  sealed="$(
    wait_for_vault_status_json 2>/dev/null | jq -r '.sealed // "unknown"' || true
  )"
  if [ "$sealed" = "true" ] && [ "$AUTO_UNSEAL_AFTER_RESTART" = "1" ]; then
    echo "INFO Vault is sealed after restart; applying test unseal keys (values not printed)"
    for idx in 0 1; do
      unseal_vault_with_key_index "$idx"
    done
  elif [ "$sealed" = "true" ]; then
    echo "FAIL Vault is sealed after restart and AUTO_UNSEAL_AFTER_RESTART is not enabled" >&2
    exit 1
  fi

  final_status="$(wait_for_vault_status_json 2>/dev/null || true)"
  if ! printf '%s\n' "$final_status" | jq -e '.sealed == false' >/dev/null; then
    echo "FAIL vault https 8202 CA-pinned seal-status did not return sealed=false" >&2
    exit 1
  fi
  echo "PASS vault https 8202 CA-pinned status works"
else
  echo "INFO restart skipped; set RESTART_VAULT=1 after the compose/config change is present on staging-sw"
fi

echo "A1_VAULT_HTTPS_PROVISION_END"
REMOTE
