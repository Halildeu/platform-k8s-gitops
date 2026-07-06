#!/usr/bin/env bash
# Faz 22.5 M2 — domain-FREE LIVE wire matrix for the mTLS auto-enroll endpoint.
#
# Drives POST {BASE}/auto via the gateway-forwarded-header path (X-Client-Cert =
# URL-encoded PEM) so it runs with no real TLS handshake — exercising the SAME
# MachineCertAutoEnrollService logic the passthrough path will use. Each case
# asserts BOTH the HTTP status AND the stable code/marker in the response body,
# so a "right code / wrong path" (e.g. a 409 DEVICE_RACE masquerading as the
# expected 409 FINGERPRINT_CONFLICT) is caught, not silently passed.
#
# This is a SELECTED set of wire negatives. Expired cert, ambiguous SAN URI,
# decommissioned device and insert-race negatives are covered at the L1
# unit/slice layer (MachineCertExtractorTest / MachineCertAutoEnrollServiceTest),
# not here.
#
# Re-runnable against a PERSISTENT DB in the DEFAULT path: it mints FRESH certs
# (random GUIDs) + a FRESH fingerprint/hostname each run, so no stale
# already-enrolled / fingerprint / hostname-adoption leak across runs.
#   !! If you pass CERTS=<dir> (pre-generated), those SAN GUIDs are REUSED, so
#      the matrix is then NOT re-runnable against a persistent DB (T1 flips to
#      idempotent/conflict). Use a FRESH cert dir per run, or omit CERTS.
#
# SECURITY: forward-header + permitAll on /auto is for an ISOLATED LOCAL LAB
# ONLY. Never run a bare backend in this mode on prod/staging — the gateway MUST
# strip any inbound X-Client-Cert and inject it only after a verified mTLS
# handshake (ADR-0029 #1501: passthrough is canonical; forward-header is fallback).
#
#   BASE   enroll base (default http://localhost:8096/api/v1/endpoint-agent/endpoint-enrollments)
#   CERTS  pre-generated cert dir (default: auto-mint fresh into a temp dir; see caveat above)
# Requires: curl, jq, openssl, uuidgen. Backend MUST run with
#   endpoint-admin.mtls.forward-header.enabled=true.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
BASE="${BASE:-http://localhost:8096/api/v1/endpoint-agent/endpoint-enrollments}"
URL="$BASE/auto"
TA="00000000-0000-0000-0000-000000000001"
TB="00000000-0000-0000-0000-000000000002"
CT="Content-Type: application/json"
RUN="${M2_RUN:-$(uuidgen | tr 'A-Z' 'a-z' | cut -c1-8)}"   # per-run token
FP="${M2_FP:-FP-$RUN}"                                      # fresh fingerprint per run

# Auto-mint fresh certs unless a CERTS dir was supplied.
if [ -z "${CERTS:-}" ]; then
  CERTS="$(mktemp -d)/certs"
  "$HERE/gen-test-certs.sh" "$CERTS" >/dev/null
fi

body() { printf '{"machineFingerprint":"%s","hostname":"%s","osName":"Windows 11","osVersion":"23H2","osBuild":"22631","domain":"WORKGROUP","architecture":"x64","agentVersion":"0.1.1-lab.2","schemaVersion":1}' "$1" "$2"; }
# Fresh hostnames per run so device-adoption (fingerprint-then-hostname
# fallback) never adopts a prior run's device that already holds an active cert.
BODY_A="$(body "$FP" "WIN11-$RUN")"
BODY_SAMEFP="$(body "$FP" "WIN11-OTHER-$RUN")"   # different cert (devb), SAME fingerprint -> 409

enc() { jq -sRr @uri < "$CERTS/$1"; }      # nginx-style URL-encoded PEM (base64 '+' -> %2B safe)
DEV=$(enc dev.crt); NOEKU=$(enc noeku.crt); NOSAN=$(enc nosan.crt); DEVB=$(enc devb.crt)

pass=0; fail=0
# run NAME EXPECTED_CODE BODY_NEEDLE  <curl args...>
# BODY_NEEDLE is a fixed string the response body MUST contain ('' = status-only).
run() { local name="$1" exp="$2" needle="$3"; shift 3
  local code body ok=1
  code=$(curl -s -o .resp -w '%{http_code}' "$@"); body=$(cat .resp 2>/dev/null)
  [ "$code" = "$exp" ] || ok=0
  if [ -n "$needle" ] && ! printf '%s' "$body" | grep -qF "$needle"; then ok=0; fi
  if [ "$ok" = 1 ]; then printf 'PASS  %-34s -> %s  %s\n' "$name" "$code" "$needle"; pass=$((pass+1));
  else printf 'FAIL  %-34s -> got %s want %s + "%s"\n' "$name" "$code" "$exp" "$needle"; fail=$((fail+1)); fi
  printf '      %s\n' "$(echo "$body" | head -c 200)"
}

echo "=== M2 forward-header LIVE matrix  BASE=$URL  fp=$FP ==="
run "T1 positive-enroll devA/tenantA" 201 '"status":"enrolled"'         -X POST "$URL" -H "$CT" -H "X-Tenant-Id: $TA" -H "X-Client-Cert: $DEV"   -d "$BODY_A"
run "T2 idempotent devA/tenantA"      200 '"status":"already-enrolled"' -X POST "$URL" -H "$CT" -H "X-Tenant-Id: $TA" -H "X-Client-Cert: $DEV"   -d "$BODY_A"
run "T3 tenant-boundary devA/tenantB" 403 'TENANT_BOUNDARY'             -X POST "$URL" -H "$CT" -H "X-Tenant-Id: $TB" -H "X-Client-Cert: $DEV"   -d "$BODY_A"
run "T4 no-clientAuth-EKU"            401 'CERT_EKU_MISSING_CLIENT_AUTH' -X POST "$URL" -H "$CT" -H "X-Tenant-Id: $TA" -H "X-Client-Cert: $NOEKU" -d "$BODY_A"
run "T5 no-adcomputer-SAN"            401 'CERT_SAN_URI_MISSING'        -X POST "$URL" -H "$CT" -H "X-Tenant-Id: $TA" -H "X-Client-Cert: $NOSAN" -d "$BODY_A"
run "T6 missing-cert(no header)"      401 'MTLS_CERT_MISSING'          -X POST "$URL" -H "$CT" -H "X-Tenant-Id: $TA" -d "$BODY_A"
run "T7 missing-tenant-header"        400 'TENANT_HEADER_REQUIRED'     -X POST "$URL" -H "$CT" -H "X-Client-Cert: $DEV" -d "$BODY_A"
run "T8 fingerprint-conflict devB"    409 'FINGERPRINT_CONFLICT'       -X POST "$URL" -H "$CT" -H "X-Tenant-Id: $TA" -H "X-Client-Cert: $DEVB"  -d "$BODY_SAMEFP"
echo ""; echo "TOTAL: pass=$pass fail=$fail"
rm -f .resp
[ "$fail" = 0 ]
