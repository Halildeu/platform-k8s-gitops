#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: verify-edge-nginx-ws-contract.sh CONFIG

Verifies the Faz 24 edge contract:
  - testai.acik.com /api/ forwards WebSocket Upgrade/Connection and has 1h timeouts
  - ai.acik.com /api/ remains outside this test-only change until owner approval
  - browser TLS hosts use the shared :8444 listener behind the stream SNI router
EOF
}

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

[[ $# -eq 1 ]] || {
  usage >&2
  exit 2
}

config="$1"
[[ -s "$config" ]] || fail "config missing or empty: ${config}"

tmp_dir="$(mktemp -d)"
trap 'rm -rf -- "$tmp_dir"' EXIT

extract_servers() {
  local host="$1"
  awk -v host="$host" '
    function count_char(value, needle, copy) {
      copy = value
      return gsub(needle, "", copy)
    }
    /^[[:space:]]*server[[:space:]]*\{/ && depth == 0 {
      active = 1
      block = ""
      matched = 0
    }
    active {
      block = block $0 ORS
      if ($0 ~ "server_name[[:space:]]+" host "([[:space:];]|$)") matched = 1
      depth += count_char($0, "\\{")
      depth -= count_char($0, "\\}")
      if (depth == 0) {
        if (matched) printf "%s", block
        active = 0
      }
    }
  ' "$config"
}

extract_api_location() {
  awk '
    function count_char(value, needle, copy) {
      copy = value
      return gsub(needle, "", copy)
    }
    /^[[:space:]]*location[[:space:]]+\/api\/[[:space:]]*\{/ && depth == 0 {
      active = 1
      block = ""
    }
    active {
      block = block $0 ORS
      depth += count_char($0, "\\{")
      depth -= count_char($0, "\\}")
      if (depth == 0) {
        printf "%s", block
        exit
      }
    }
  '
}

test_servers="${tmp_dir}/test-servers.conf"
prod_servers="${tmp_dir}/prod-servers.conf"
public_servers="${tmp_dir}/public-servers.conf"
test_api="${tmp_dir}/test-api.conf"
prod_api="${tmp_dir}/prod-api.conf"

extract_servers 'testai\.acik\.com' >"$test_servers"
extract_servers 'ai\.acik\.com' >"$prod_servers"
extract_servers 'etik\.acik\.com[[:space:]]+speakup\.acik\.com' >"$public_servers"
extract_api_location <"$test_servers" >"$test_api"
extract_api_location <"$prod_servers" >"$prod_api"

[[ -s "$test_api" ]] || fail 'testai.acik.com /api/ location missing'
[[ -s "$prod_api" ]] || fail 'ai.acik.com /api/ location missing'

grep -Eq '^map[[:space:]]+\$http_upgrade[[:space:]]+\$connection_upgrade[[:space:]]*\{' "$config" || \
  fail 'global WebSocket connection map missing'
grep -Fq 'proxy_set_header Upgrade $http_upgrade;' "$test_api" || \
  fail 'test /api/ Upgrade forward missing'
grep -Fq 'proxy_set_header Connection $connection_upgrade;' "$test_api" || \
  fail 'test /api/ Connection forward missing'
grep -Fq 'proxy_read_timeout 3600s;' "$test_api" || fail 'test /api/ read timeout missing'
grep -Fq 'proxy_send_timeout 3600s;' "$test_api" || fail 'test /api/ send timeout missing'
grep -Fq 'proxy_pass http://127.0.0.1:31080;' "$test_api" || fail 'test /api/ upstream drifted'

if grep -Eq 'proxy_set_header[[:space:]]+(Upgrade|Connection)[[:space:]]' "$prod_api"; then
  fail 'prod /api/ WebSocket mutation requires a separate owner-approved change'
fi

grep -Fq 'listen 8444 ssl;' "$test_servers" || fail 'test browser TLS listener is not :8444'
grep -Fq 'listen 8444 ssl;' "$prod_servers" || fail 'prod browser TLS listener is not :8444'
grep -Fq 'listen 8444 ssl;' "$public_servers" || fail 'Faz 35 browser TLS listener is not :8444'

printf 'PASS: Faz 24 TEST edge WebSocket contract (%s)\n' "$config"
