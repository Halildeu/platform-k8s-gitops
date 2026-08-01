#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
GW="${ROOT}/deploy/staging-sw/meeting-ai-private-gateway"
TEST_RENDER="$(mktemp)"
TEST_ESO_RENDER="$(mktemp)"
PROD_RENDER="$(mktemp)"
MONITOR_RENDER="$(mktemp)"
PUBLIC_GATEWAY_RENDER="$(mktemp)"
trap 'rm -f -- "${TEST_RENDER}" "${TEST_ESO_RENDER}" "${PROD_RENDER}" "${MONITOR_RENDER}" "${PUBLIC_GATEWAY_RENDER}"' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

for file in Caddyfile firewall.sh install.sh rotate-server-cert.sh \
  meeting-ai-gateway-firewall.service meeting-ai-private-gateway.service \
  meeting-ai-server-cert-rotation.service meeting-ai-server-cert-rotation.timer; do
  [[ -s "${GW}/${file}" ]] || fail "missing gateway artifact: ${file}"
done

grep -Fq 'access log must be a regular non-symlink file' \
  "${GW}/install.sh" || fail "access-log symlink/type guard missing"
# Assert the literal installer variable reference.
# shellcheck disable=SC2016
grep -Fq 'install -o caddy -g caddy -m 0640 /dev/null "${ACCESS_LOG}"' \
  "${GW}/install.sh" || fail "access-log initial ownership missing"
# Assert the literal installer variable reference.
# shellcheck disable=SC2016
grep -Fq 'chown caddy:caddy "${ACCESS_LOG}"' \
  "${GW}/install.sh" || fail "access-log ownership repair missing"

grep -Fq 'https://meeting-ai-gateway.internal:9447' "${GW}/Caddyfile" || \
  fail "Caddy private SNI listener missing"
grep -Fq $'\tbind 10.99.0.1' "${GW}/Caddyfile" || fail "Caddy exact bind missing"
grep -Fq 'mode require_and_verify' "${GW}/Caddyfile" || fail "client cert is not required"
grep -Fq 'pem_file /etc/platform/meeting-ai-gateway/tls/client-ca.crt' "${GW}/Caddyfile" || \
  fail "dedicated client CA missing"
grep -Fq 'tls/current/server.crt' "${GW}/Caddyfile" || \
  fail "atomic certificate pointer missing"
grep -Fq 'path /oauth2/token' "${GW}/Caddyfile" || fail "token path missing"
grep -Fq 'path_regexp result ^/api/v1/internal/meetings/' "${GW}/Caddyfile" || \
  fail "UUID-scoped ingestion path missing"
awk '/^[[:space:]]*@transcript_capability \{/,/^[[:space:]]*\}/' "${GW}/Caddyfile" | \
  grep -Fq 'method POST' || fail "transcript capability must be POST-only"
grep -Fq 'path_regexp transcript_capability ^/api/v1/internal/tenants/' "${GW}/Caddyfile" || \
  fail "tuple-scoped transcript capability path missing"
grep -Fq '/finalizations/[1-9][0-9]*/analysis-capability$' "${GW}/Caddyfile" || \
  fail "exact transcript capability suffix missing"
awk '/^[[:space:]]*handle @transcript_capability \{/,/^[[:space:]]*\}/' "${GW}/Caddyfile" | \
  grep -Fq 'max_size 16KiB' || fail "transcript capability body limit missing"
awk '/^[[:space:]]*@transcript_snapshot \{/,/^[[:space:]]*\}/' "${GW}/Caddyfile" | \
  grep -Fq 'method GET' || fail "canonical transcript snapshot must be GET-only"
grep -Fq 'path_regexp transcript_snapshot ^/api/v1/internal/tenants/' "${GW}/Caddyfile" || \
  fail "tuple-scoped canonical transcript path missing"
grep -Fq '/finalizations/[1-9][0-9]*$' "${GW}/Caddyfile" || \
  fail "exact canonical transcript suffix missing"
grep -Fq $'\t\trespond 404' "${GW}/Caddyfile" || fail "default deny response missing"
if grep -Eq '(^|[[:space:]])(0\.0\.0\.0|:80|:443)([[:space:]]|$)' "${GW}/Caddyfile"; then
  fail "Caddy contains a broad/public listener"
fi
grep -Fq 'request>headers>Authorization delete' "${GW}/Caddyfile" || \
  fail "Authorization redaction missing"
grep -Fq 'request>headers>X-Analysis-Job-Capability delete' "${GW}/Caddyfile" || \
  fail "request capability redaction missing"
grep -Fq 'resp_headers>X-Analysis-Job-Capability delete' "${GW}/Caddyfile" || \
  fail "response capability redaction missing"

grep -Fq 'readonly WG_INTERFACE="wg0"' "${GW}/firewall.sh" || fail "wg0 firewall pin missing"
grep -Fq 'readonly CLIENT_IP="10.99.0.2/32"' "${GW}/firewall.sh" || fail "client /32 missing"
grep -Fq 'readonly SERVER_IP="10.99.0.1/32"' "${GW}/firewall.sh" || fail "server /32 missing"
grep -Fq 'readonly SERVER_PORT="9447"' "${GW}/firewall.sh" || fail "port pin missing"
grep -Fq -- '-j DROP' "${GW}/firewall.sh" || fail "firewall default drop missing"
grep -Fq "mv -Tf -- \"\${TLS_DIR}/current.new\" \"\${TLS_DIR}/current\"" \
  "${GW}/rotate-server-cert.sh" || fail "atomic cert/key activation missing"
grep -Fq 'gateway reload failed; certificate pointer rolled back' \
  "${GW}/rotate-server-cert.sh" || fail "certificate reload rollback missing"
grep -Fq 'vault token renew -format=json -increment=24h' \
  "${GW}/rotate-server-cert.sh" || fail "scoped Vault token renewal missing"
if grep -Fq 'vault token renew -format=json -increment=24h -self' \
  "${GW}/rotate-server-cert.sh"; then
  fail "unsupported Vault CLI -self flag present"
fi
# shellcheck disable=SC2016
grep -Fq 'readonly VAULT_TRANSPORT="${VAULT_TRANSPORT:-https}"' \
  "${GW}/rotate-server-cert.sh" || fail "Vault transport selector missing"
grep -Fq "docker exec -i \"\${VAULT_DOCKER_CONTAINER}\"" \
  "${GW}/rotate-server-cert.sh" || fail "test Vault container transport missing"
grep -Fq 'Environment=VAULT_TRANSPORT=container' \
  "${GW}/meeting-ai-server-cert-rotation.service" || fail "test Vault transport is not pinned"
if grep -Eq 'docker exec[^|]*-e[[:space:]]+VAULT_TOKEN' "${GW}/rotate-server-cert.sh"; then
  fail "Vault token must not be exposed through docker exec argv"
fi
grep -Fq "server-leaf.crt\" \"\${tmp_dir}/server-ca.crt\" >\"\${tmp_dir}/server.crt" \
  "${GW}/rotate-server-cert.sh" || fail "server fullchain assembly missing"
grep -Fq 'meeting_ai_gateway_rotation_last_run_success' \
  "${GW}/rotate-server-cert.sh" || fail "rotation telemetry missing"

if find "${GW}" -type f \( -name '*.key' -o -name '*.crt' -o -name '*.pem' -o -name '*.p12' \) | grep -q .; then
  fail "certificate or private-key material is committed in the gateway directory"
fi

command -v kustomize >/dev/null 2>&1 || fail "kustomize is required"
kustomize build "${ROOT}/kustomize/overlays/test" >"${TEST_RENDER}"
kustomize build "${ROOT}/kustomize/overlays/test/eso" >"${TEST_ESO_RENDER}"
kustomize build "${ROOT}/kustomize/overlays/prod" >"${PROD_RENDER}"
kustomize build "${ROOT}/kustomize/base/monitoring" >"${MONITOR_RENDER}"

# The private ingestion path may appear in the dedicated private Ingress, but
# it must never become a Spring Cloud Gateway predicate on the public host.
# Extract only the rendered api-gateway ConfigMap so the private Ingress path
# itself does not create a false positive.
awk 'BEGIN { RS="---" }
  /kind:[[:space:]]*ConfigMap/ && /name:[[:space:]]*api-gateway-config/ { print }
' "${TEST_RENDER}" >"${PUBLIC_GATEWAY_RENDER}"
[[ -s "${PUBLIC_GATEWAY_RENDER}" ]] || fail "rendered public api-gateway ConfigMap missing"
grep -Fq 'SPRING_CLOUD_GATEWAY_ROUTES_26_ID: meeting-admin-route' \
  "${PUBLIC_GATEWAY_RENDER}" || fail "public gateway extraction is not the expected ConfigMap"
if grep -Fq '/api/v1/internal/meetings/' "${PUBLIC_GATEWAY_RENDER}"; then
  fail "private analysis-result path leaked into the public api-gateway route table"
fi
if grep -Fq '/api/v1/internal/tenants/' "${PUBLIC_GATEWAY_RENDER}"; then
  fail "private transcript path leaked into the public api-gateway route table"
fi

grep -Fq 'host: meeting-ai-private.testai.internal' "${TEST_RENDER}" || fail "private ingress missing"
grep -Fq 'path: /oauth2/token$' "${TEST_RENDER}" || fail "exact token ingress route missing"
grep -Fq 'path: /api/v1/internal/meetings/' "${TEST_RENDER}" || fail "UUID ingestion ingress route missing"
grep -Fq '/analysis-results$' "${TEST_RENDER}" || fail "exact analysis-result ingress suffix missing"
grep -Fq 'path: /api/v1/internal/tenants/' "${TEST_RENDER}" || \
  fail "tuple-scoped transcript ingress routes missing"
grep -Fq '/finalizations/[1-9][0-9]*/analysis-capability$' "${TEST_RENDER}" || \
  fail "exact transcript capability ingress suffix missing"
grep -Fq '/finalizations/[1-9][0-9]*$' "${TEST_RENDER}" || \
  fail "exact canonical transcript ingress suffix missing"
if grep -Eq '^[[:space:]]+path: \^' "${TEST_RENDER}"; then
  fail "Ingress paths must start with / for Kubernetes API validation"
fi
grep -Fq 'SERVICE_CLIENT_MEETING_AI_SECRET' "${TEST_RENDER}" || fail "meeting-ai auth secret ESO mapping missing"
grep -Fq 'name: auth-service-meeting-ai-secret' "${TEST_RENDER}" || fail "isolated meeting-ai ExternalSecret missing"
grep -Fq 'optional: true' "${TEST_RENDER}" || fail "meeting-ai secret must not block core auth startup"
grep -Fq 'property: service_client_meeting_ai_secret' "${TEST_RENDER}" || fail "Vault property mapping missing"
if grep -A80 -F 'name: auth-service-secrets' "${TEST_RENDER}" | \
    head -80 | grep -Fq 'SERVICE_CLIENT_MEETING_AI_SECRET'; then
  fail "meeting-ai key must not share the core auth-service ExternalSecret"
fi
grep -Fq 'name: auth-service-transcript-service-secret' "${TEST_RENDER}" || \
  fail "isolated transcript-service issuer secret missing"
grep -Fq 'property: service_client_transcript_service_secret' "${TEST_RENDER}" || \
  fail "transcript-service client credential Vault mapping missing"
if grep -A100 -F 'name: auth-service-secrets' "${TEST_RENDER}" | \
    head -100 | grep -Fq 'SERVICE_CLIENT_TRANSCRIPT_SERVICE_SECRET'; then
  fail "transcript-service issuer key must not share the core auth-service ExternalSecret"
fi
grep -A80 -F 'name: meeting-service-secrets' "${TEST_ESO_RENDER}" | \
  head -80 | grep -Fq 'key: kv/platform/meeting-service' || \
  fail "meeting-service Redis credential must use the meeting-service-owned Vault path"
if grep -A80 -F 'name: meeting-service-secrets' "${TEST_ESO_RENDER}" | \
    head -80 | grep -Fq 'key: kv/platform/audio-gateway-service'; then
  fail "meeting-service must not depend on the audio-gateway Vault path"
fi
grep -Fq 'name: allow-meeting-ai-private-ingress-auth' "${TEST_RENDER}" || \
  fail "private auth ingress NetworkPolicy missing"
grep -Fq 'name: allow-meeting-ai-private-ingress-meeting' "${TEST_RENDER}" || \
  fail "private meeting ingress NetworkPolicy missing"
grep -Fq 'name: allow-meeting-ai-private-ingress-transcript' "${TEST_RENDER}" || \
  fail "private transcript ingress NetworkPolicy missing"
transcript_private_policy="$(
  awk 'BEGIN { RS="---" }
    /kind:[[:space:]]*NetworkPolicy/ &&
    /name:[[:space:]]*allow-meeting-ai-private-ingress-transcript/ { print }
  ' "${TEST_RENDER}"
)"
[[ -n "${transcript_private_policy}" ]] || fail "private transcript policy render missing"
grep -Fq 'kubernetes.io/metadata.name: ingress-nginx' <<<"${transcript_private_policy}" || \
  fail "private transcript policy source is not ingress-nginx"
grep -Fq 'port: 8098' <<<"${transcript_private_policy}" || \
  fail "private transcript policy does not pin port 8098"
[[ "$(grep -c 'port:' <<<"${transcript_private_policy}")" -eq 1 ]] || \
  fail "private transcript policy exposes more than one port"
intra_namespace_policy="$(
  awk 'BEGIN { RS="---" }
    /kind:[[:space:]]*NetworkPolicy/ &&
    /name:[[:space:]]*allow-ingress-intra-ns/ { print }
  ' "${TEST_RENDER}"
)"
grep -Fq 'app.kubernetes.io/part-of: platform' <<<"${intra_namespace_policy}" || \
  fail "same-namespace platform ingress baseline missing"
for binding in \
  'TRANSCRIPT_INTERNAL_SERVICE_JWT_JWK_SET_URI: http://auth-service:8088/oauth2/jwks' \
  'TRANSCRIPT_INTERNAL_SERVICE_JWT_ISSUER: auth-service' \
  'TRANSCRIPT_INTERNAL_SERVICE_JWT_AUDIENCE: transcript-service' \
  'TRANSCRIPT_INTERNAL_SERVICE_JWT_CLIENT_IDS: meeting-ai,meeting-service'; do
  grep -Fq "${binding}" "${TEST_RENDER}" || fail "missing transcript verifier binding: ${binding}"
done
for binding in \
  'MEETING_INTERNAL_SERVICE_JWT_JWK_SET_URI: http://auth-service:8088/oauth2/jwks' \
  'MEETING_INTERNAL_SERVICE_JWT_ISSUER: auth-service' \
  'MEETING_INTERNAL_SERVICE_JWT_AUDIENCE: meeting-service' \
  'MEETING_INTERNAL_SERVICE_JWT_CLIENT_ID: meeting-ai' \
  'MEETING_INTERNAL_SERVICE_JWT_CLIENT_IDS: meeting-ai,transcript-service'; do
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
