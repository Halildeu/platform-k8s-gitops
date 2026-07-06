#!/usr/bin/env bash
# Faz 22.5 Step-2 — domain-FREE LIVE PASSTHROUGH matrix (real :8443 mTLS handshake).
#
# Exercises the canonical passthrough path (ADR-0029 #1501): the backend
# terminates mTLS on :8443 (clientAuth=NEED), identity from the TLS peer cert,
# X-Tenant-Id IGNORED (fixed-tenant authority). Asserts positive enroll +
# handshake-level negatives (narrowed to genuine TLS refusals, not setup errors)
# + the bidirectional connector guard, and OPTIONALLY the fixed-tenant DB binding.
#
# Preconditions: the backend is RUNNING with passthrough enabled against the
# truststore in CERTS (see gen-server-keystore.sh for the start command). The
# client certs are minted from the SAME test CA the backend trusts — so CERTS
# is REQUIRED (do NOT regenerate the CA here, or the handshake won't trust it).
#
#   MTLS_BASE     https base (default https://localhost:8443/api/v1/endpoint-agent/endpoint-enrollments)
#   PLAIN_BASE    http base  (default http://localhost:8096/api/v1/endpoint-agent/endpoint-enrollments)
#   CERTS         dir with testca.crt/testca.key (REQUIRED; from gen-test-certs.sh)
#   FIXED_TENANT  expected fixed tenant (default 00000000-0000-0000-0000-000000000001)
#   PG_CONTAINER  docker PG for the optional DB tenant check (default m2-pg; skipped if absent)
# Requires: curl, openssl, uuidgen. NEVER uses curl -k (server hostname is verified).
set -euo pipefail
for c in curl openssl uuidgen; do command -v "$c" >/dev/null || { echo "ERROR: '$c' not found on PATH"; exit 1; }; done
CERTS="${CERTS:?set CERTS=<dir with testca.crt/key the backend trusts>}"
MTLS_BASE="${MTLS_BASE:-https://localhost:8443/api/v1/endpoint-agent/endpoint-enrollments}"
PLAIN_BASE="${PLAIN_BASE:-http://localhost:8096/api/v1/endpoint-agent/endpoint-enrollments}"
FIXED_TENANT="${FIXED_TENANT:-00000000-0000-0000-0000-000000000001}"
PG_CONTAINER="${PG_CONTAINER:-m2-pg}"
CA="$CERTS/testca.crt"
[ -f "$CA" ] && [ -f "$CERTS/testca.key" ] || { echo "ERROR: $CERTS/testca.{crt,key} missing (run gen-test-certs.sh)"; exit 1; }
FORGED='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'   # forged tenant header — must be IGNORED

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# Fresh CLIENT cert from the EXISTING test CA -> first enroll (201), re-runnable.
G=$(uuidgen | tr 'A-Z' 'a-z')
printf '[v3]\nkeyUsage=digitalSignature\nextendedKeyUsage=clientAuth\nsubjectAltName=URI:adcomputer:%s\n' "$G" > "$tmp/c.cnf"
openssl req -new -newkey rsa:2048 -nodes -keyout "$tmp/c.key" -subj "/CN=WIN11-PT-$(echo "$G"|cut -c1-8)" -out "$tmp/c.csr" 2>/dev/null
openssl x509 -req -in "$tmp/c.csr" -CA "$CA" -CAkey "$CERTS/testca.key" -CAcreateserial -days 14 \
  -extfile "$tmp/c.cnf" -extensions v3 -out "$tmp/c.crt" 2>/dev/null
# Wrong-CA client cert (separate CA) -> handshake must be refused.
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$tmp/o.key" -out "$tmp/oca.crt" -days 1 -subj "/CN=Other CA" 2>/dev/null
printf '[v3]\nextendedKeyUsage=clientAuth\nsubjectAltName=URI:adcomputer:99999999-9999-9999-9999-999999999999\n' > "$tmp/o.cnf"
openssl req -new -newkey rsa:2048 -nodes -keyout "$tmp/ok.key" -subj "/CN=OTHER" -out "$tmp/o.csr" 2>/dev/null
openssl x509 -req -in "$tmp/o.csr" -CA "$tmp/oca.crt" -CAkey "$tmp/o.key" -CAcreateserial -days 1 \
  -extfile "$tmp/o.cnf" -extensions v3 -out "$tmp/o.crt" 2>/dev/null
# Sanity: all client materials produced + non-empty (set -e + this guard catch silent mint failures).
for f in c.crt c.key o.crt ok.key; do [ -s "$tmp/$f" ] || { echo "ERROR: cert material $f not generated"; exit 1; }; done

FP="FP-PT-$(echo "$G"|cut -c1-8)"
BODY=$(printf '{"machineFingerprint":"%s","hostname":"WIN11-PT-%s","osName":"Windows 11","agentVersion":"0.1.1-lab.2","schemaVersion":1}' "$FP" "$(echo "$G"|cut -c1-8)")
pass=0; fail=0
ok()  { printf 'PASS  %s\n' "$1"; pass=$((pass+1)); }
bad() { printf 'FAIL  %s\n' "$1"; fail=$((fail+1)); }

# Negative TLS assertion: the curl MUST fail specifically at the TLS layer, not a
# setup/connect error. Reject ec 6/7/28/58 (DNS/connect/timeout/local-cert) and
# require ec != 0 with a TLS signature in stderr (Codex 019ec12d findings 1+2).
expect_handshake_refused() { local name="$1"; shift
  local out ec
  set +e; out=$(curl -sS --max-time 15 -o /dev/null "$@" 2>&1); ec=$?; set -e
  if [ "$ec" = 0 ]; then bad "$name (expected TLS refusal, request SUCCEEDED)"; return; fi
  case "$ec" in 6|7|28|58) bad "$name (non-TLS setup/connect error ec=$ec: ${out//$'\n'/ })"; return;; esac
  if printf '%s' "$out" | grep -qiE 'alert|handshake|tls|ssl|certificate|unknown ca|bad certificate|peer|routines'; then
    ok "$name (TLS handshake refused, ec=$ec)"
  else bad "$name (ec=$ec but no TLS signature: ${out//$'\n'/ })"; fi
}

# T1 positive enroll + FORGED tenant header (header must be ignored at the wire).
code=$(curl -sS --max-time 15 -o "$tmp/r" -w '%{http_code}' --cacert "$CA" --cert "$tmp/c.crt" --key "$tmp/c.key" \
  -H 'Content-Type: application/json' -H "X-Tenant-Id: $FORGED" -X POST "$MTLS_BASE/auto" -d "$BODY" || true)
{ [ "$code" = 201 ] && grep -q '"status":"enrolled"' "$tmp/r"; } \
  && ok "T1 enroll accepted despite forged X-Tenant-Id -> $code (DB tenant checked in T1b)" \
  || bad "T1 positive enroll -> $code"
# T2 NO client cert -> handshake refused (clientAuth=NEED)
expect_handshake_refused "T2 no client cert" --cacert "$CA" -X POST "$MTLS_BASE/auto" -d "$BODY"
# T3 WRONG-CA client cert -> handshake refused
expect_handshake_refused "T3 wrong-CA client cert" --cacert "$CA" --cert "$tmp/o.crt" --key "$tmp/ok.key" -X POST "$MTLS_BASE/auto" -d "$BODY"
# T4 plain :8096 endpoint-agent -> 403 guard (never reaches business path)
code=$(curl -sS --max-time 15 -o "$tmp/r" -w '%{http_code}' -H 'Content-Type: application/json' \
  -H "X-Tenant-Id: $FIXED_TENANT" -X POST "$PLAIN_BASE/auto" -d "$BODY" || true)
{ [ "$code" = 403 ] && grep -q 'MTLS_CONNECTOR_REQUIRED' "$tmp/r"; } \
  && ok "T4 plain :8096 endpoint-agent -> 403 MTLS_CONNECTOR_REQUIRED" || bad "T4 plain :8096 guard -> $code"
# T5 non-agent path on :8443 -> 404 guard (least privilege)
MTLS_ORIGIN="${MTLS_BASE%%/api/*}"
code=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' --cacert "$CA" --cert "$tmp/c.crt" --key "$tmp/c.key" "$MTLS_ORIGIN/actuator/health" || true)
[ "$code" = 404 ] && ok "T5 non-agent on :8443 -> 404 (guard least-privilege)" || bad "T5 non-agent on :8443 -> $code"

# T1b (optional) — fixed-tenant DB binding: the forged header had NO effect.
if command -v docker >/dev/null && docker exec "$PG_CONTAINER" true >/dev/null 2>&1; then
  row=$(docker exec "$PG_CONTAINER" psql -U postgres -d endpoint_admin -t -A -F'|' -c \
    "SELECT d.tenant_id,d.org_id FROM endpoint_admin_service.endpoint_devices d JOIN endpoint_admin_service.endpoint_machine_certs c ON c.device_id=d.id WHERE c.san_uri='adcomputer:$G';" 2>/dev/null | tr -d '[:space:]')
  [ "$row" = "$FIXED_TENANT|$FIXED_TENANT" ] \
    && ok "T1b DB tenant==fixed ($FIXED_TENANT), forged header ignored" \
    || bad "T1b DB tenant mismatch: got '$row' want '$FIXED_TENANT|$FIXED_TENANT'"
else
  echo "SKIP  T1b DB tenant verify (set PG_CONTAINER to a reachable docker PG; runbook step 4 verifies manually)"
fi

echo ""; echo "TOTAL: pass=$pass fail=$fail  (client SAN adcomputer:$G)"
[ "$fail" = 0 ]
