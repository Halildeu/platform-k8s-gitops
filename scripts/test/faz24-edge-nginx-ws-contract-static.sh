#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG="${ROOT}/host-compose/web-nginx/default.conf"
VERIFY="${ROOT}/scripts/faz24/verify-edge-nginx-ws-contract.sh"
RECONCILE="${ROOT}/scripts/faz24/reconcile-edge-nginx.sh"
MISSING_TEST_UPGRADE="$(mktemp)"
PROD_MUTATION="$(mktemp)"
trap 'rm -f -- "$MISSING_TEST_UPGRADE" "$PROD_MUTATION"' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

[[ -x "$VERIFY" ]] || fail 'contract verifier missing or not executable'
[[ -x "$RECONCILE" ]] || fail 'reconcile tool missing or not executable'
"$VERIFY" "$CONFIG"

sed '/proxy_set_header Upgrade \$http_upgrade;/d' "$CONFIG" >"$MISSING_TEST_UPGRADE"
if "$VERIFY" "$MISSING_TEST_UPGRADE" >/dev/null 2>&1; then
  fail 'verifier accepted a config without the test Upgrade forward'
fi

awk '
  { print }
  /proxy_set_header X-Forwarded-Port \$server_port;/ && !inserted {
    print "    proxy_set_header Upgrade $http_upgrade;"
    print "    proxy_set_header Connection $connection_upgrade;"
    inserted = 1
  }
' "$CONFIG" >"$PROD_MUTATION"
if "$VERIFY" "$PROD_MUTATION" >/dev/null 2>&1; then
  fail 'verifier accepted an unapproved prod /api/ WebSocket mutation'
fi

grep -Fq 'mode=check' "$RECONCILE" || fail 'read-only default missing'
grep -Fq -- '--expected-live-sha' "$RECONCILE" || fail 'CAS input missing'
grep -Fq 'ROLLBACK: restored' "$RECONCILE" || fail 'automatic rollback missing'
grep -Fq 'nginx -t -c /tmp/nginx-candidate.conf' "$RECONCILE" || \
  fail 'candidate config validation missing'

printf '%s\n' 'PASS: Faz 24 edge nginx static reconciliation contract'
