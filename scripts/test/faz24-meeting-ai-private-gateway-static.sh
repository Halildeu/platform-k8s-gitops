#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
GW="${ROOT}/deploy/staging-sw/meeting-ai-private-gateway"
TEST_RENDER="$(mktemp)"
PROD_RENDER="$(mktemp)"
MONITOR_RENDER="$(mktemp)"
trap 'rm -f -- "${TEST_RENDER}" "${PROD_RENDER}" "${MONITOR_RENDER}"' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

for file in Caddyfile firewall.sh install.sh rotate-server-cert.sh \
  meeting-ai-gateway-firewall.service meeting-ai-private-gateway.service \
  meeting-ai-server-cert-rotation.service meeting-ai-server-cert-rotation.timer; do
  [[ -s "${GW}/${file}" ]] || fail "missing gateway artifact: ${file}"
done

grep -Fq 'https://meeting-ai-gateway.internal:9445' "${GW}/Caddyfile" || \
  fail "Caddy private SNI listener missing"
grep -Fq $'\tbind 10.99.0.1' "${GW}/Caddyfile" || fail "Caddy exact bind missing"
grep -Fq 'mode require_and_verify' "${GW}/Caddyfile" || fail "client cert is not required"
grep -Fq 'pem_file /etc/platform/meeting-ai-gateway/tls/client-ca.crt' "${GW}/Caddyfile" || \
  fail "dedicated client CA missing"
grep -Fq 'tls/current/server.crt' "${GW}/Caddyfile" || \
  fail "atomic certificate pointer missing"
grep -Fq 'method POST' "${GW}/Caddyfile" || fail "POST method restrictions missing"
grep -Fq 'path /oauth2/token' "${GW}/Caddyfile" || fail "token path missing"
grep -Fq 'path_regexp result ^/api/v1/internal/meetings/' "${GW}/Caddyfile" || \
  fail "UUID-scoped ingestion path missing"
grep -Fq $'\t\trespond 404' "${GW}/Caddyfile" || fail "default deny response missing"
if grep -Eq '(^|[[:space:]])(0\.0\.0\.0|:80|:443)([[:space:]]|$)' "${GW}/Caddyfile"; then
  fail "Caddy contains a broad/public listener"
fi
grep -Fq 'request>headers>Authorization delete' "${GW}/Caddyfile" || \
  fail "Authorization redaction missing"

grep -Fq 'readonly WG_INTERFACE="wg0"' "${GW}/firewall.sh" || fail "wg0 firewall pin missing"
grep -Fq 'readonly CLIENT_IP="10.99.0.2/32"' "${GW}/firewall.sh" || fail "client /32 missing"
grep -Fq 'readonly SERVER_IP="10.99.0.1/32"' "${GW}/firewall.sh" || fail "server /32 missing"
grep -Fq 'readonly SERVER_PORT="9445"' "${GW}/firewall.sh" || fail "port pin missing"
grep -Fq -- '-j DROP' "${GW}/firewall.sh" || fail "firewall default drop missing"
grep -Fq "mv -Tf -- \"\${TLS_DIR}/current.new\" \"\${TLS_DIR}/current\"" \
  "${GW}/rotate-server-cert.sh" || fail "atomic cert/key activation missing"
grep -Fq 'gateway reload failed; certificate pointer rolled back' \
  "${GW}/rotate-server-cert.sh" || fail "certificate reload rollback missing"
grep -Fq 'vault token renew -format=json -increment=24h -self' \
  "${GW}/rotate-server-cert.sh" || fail "scoped Vault token renewal missing"
grep -Fq "server-leaf.crt\" \"\${tmp_dir}/server-ca.crt\" >\"\${tmp_dir}/server.crt" \
  "${GW}/rotate-server-cert.sh" || fail "server fullchain assembly missing"
grep -Fq 'meeting_ai_gateway_rotation_last_run_success' \
  "${GW}/rotate-server-cert.sh" || fail "rotation telemetry missing"

if find "${GW}" -type f \( -name '*.key' -o -name '*.crt' -o -name '*.pem' -o -name '*.p12' \) | grep -q .; then
  fail "certificate or private-key material is committed in the gateway directory"
fi

command -v kustomize >/dev/null 2>&1 || fail "kustomize is required"
kustomize build "${ROOT}/kustomize/overlays/test" >"${TEST_RENDER}"
kustomize build "${ROOT}/kustomize/overlays/prod" >"${PROD_RENDER}"
kustomize build "${ROOT}/kustomize/base/monitoring" >"${MONITOR_RENDER}"

grep -Fq 'host: meeting-ai-private.testai.internal' "${TEST_RENDER}" || fail "private ingress missing"
grep -Fq 'path: ^/oauth2/token$' "${TEST_RENDER}" || fail "exact token ingress route missing"
grep -Fq 'path: ^/api/v1/internal/meetings/' "${TEST_RENDER}" || fail "UUID ingestion ingress route missing"
grep -Fq '/analysis-results$' "${TEST_RENDER}" || fail "exact analysis-result ingress suffix missing"
grep -Fq 'SERVICE_CLIENT_MEETING_AI_SECRET' "${TEST_RENDER}" || fail "meeting-ai auth secret ESO mapping missing"
grep -Fq 'name: auth-service-meeting-ai-secret' "${TEST_RENDER}" || fail "isolated meeting-ai ExternalSecret missing"
grep -Fq 'optional: true' "${TEST_RENDER}" || fail "meeting-ai secret must not block core auth startup"
grep -Fq 'property: service_client_meeting_ai_secret' "${TEST_RENDER}" || fail "Vault property mapping missing"
if grep -A80 -F 'name: auth-service-secrets' "${TEST_RENDER}" | \
    head -80 | grep -Fq 'SERVICE_CLIENT_MEETING_AI_SECRET'; then
  fail "meeting-ai key must not share the core auth-service ExternalSecret"
fi
grep -Fq 'name: allow-meeting-ai-private-ingress-auth' "${TEST_RENDER}" || \
  fail "private auth ingress NetworkPolicy missing"
grep -Fq 'name: allow-meeting-ai-private-ingress-meeting' "${TEST_RENDER}" || \
  fail "private meeting ingress NetworkPolicy missing"
for binding in \
  'MEETING_INTERNAL_SERVICE_JWT_JWK_SET_URI: http://auth-service:8088/oauth2/jwks' \
  'MEETING_INTERNAL_SERVICE_JWT_ISSUER: auth-service' \
  'MEETING_INTERNAL_SERVICE_JWT_AUDIENCE: meeting-service' \
  'MEETING_INTERNAL_SERVICE_JWT_CLIENT_ID: meeting-ai'; do
  grep -Fq "${binding}" "${TEST_RENDER}" || fail "missing meeting verifier binding: ${binding}"
done
if grep -Fq 'meeting-ai-private.testai.internal' "${PROD_RENDER}"; then
  fail "test-only private ingress leaked into prod render"
fi
if grep -Fq 'SERVICE_CLIENT_MEETING_AI_SECRET' "${PROD_RENDER}"; then
  fail "test-only meeting-ai client secret leaked into prod render"
fi
for alert in \
  MeetingAIGatewayCertificateRotationFailed \
  MeetingAIGatewayCertificateRotationStale \
  MeetingAIGatewayCertificateExpiring \
  MeetingAIGatewayTelemetryAbsent; do
  grep -Fq "alert: ${alert}" "${MONITOR_RENDER}" || fail "missing gateway alert: ${alert}"
done

printf '%s\n' 'PASS: Faz 24 Meeting-AI private gateway static contract'
