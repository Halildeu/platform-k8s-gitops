#!/usr/bin/env bash

set -euo pipefail

CONTEXT="${CONTEXT:-k3d-test}"
NAMESPACE="${NAMESPACE:-platform-test}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/platform/redis-streams}"
CONTAINER="${CONTAINER:-platform-redis-streams-test}"
EXPECTED_IP="${EXPECTED_IP:-172.19.0.250}"
DEPLOYMENT="${DEPLOYMENT:-audio-gateway}"
OUT="${OUT:-/tmp/faz24-redis-streams-runtime.json}"

[[ "${CONTEXT}" == "k3d-test" ]] || { echo "unsupported-context" >&2; exit 2; }
[[ "${NAMESPACE}" == "platform-test" ]] || { echo "unsupported-namespace" >&2; exit 2; }
[[ "${COMPOSE_DIR}" == "/opt/platform/redis-streams" ]] || { echo "unsupported-compose-dir" >&2; exit 2; }
[[ "${CONTAINER}" == "platform-redis-streams-test" ]] || { echo "unsupported-container" >&2; exit 2; }
[[ "${EXPECTED_IP}" == "172.19.0.250" ]] || { echo "unsupported-expected-ip" >&2; exit 2; }
[[ "${DEPLOYMENT}" == "audio-gateway" ]] || { echo "unsupported-deployment" >&2; exit 2; }

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_source="${repo_root}/host-compose/redis-streams/docker-compose.yml"
entrypoint_source="${repo_root}/host-compose/redis-streams/gen-acl-and-run.sh"
env_file="${COMPOSE_DIR}/.env"

[[ -r "${compose_source}" && -r "${entrypoint_source}" ]] \
  || { echo "desired-compose-files-unavailable" >&2; exit 3; }
command -v docker >/dev/null 2>&1 || { echo "docker-unavailable" >&2; exit 3; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl-unavailable" >&2; exit 3; }
command -v jq >/dev/null 2>&1 || { echo "jq-unavailable" >&2; exit 3; }

privileged=()
if sudo -n true >/dev/null 2>&1; then
  privileged=(sudo -n)
fi

before_state="$(docker inspect -f '{{.State.Status}}' "${CONTAINER}" 2>/dev/null || printf 'missing')"
before_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${CONTAINER}" 2>/dev/null || printf 'missing')"

"${privileged[@]}" mkdir -p "${COMPOSE_DIR}"
"${privileged[@]}" test -f "${env_file}" \
  || { echo "redis-runtime-env-missing-secret-owner-action-required" >&2; exit 4; }
env_mode="$("${privileged[@]}" stat -c '%a' "${env_file}")"
[[ "${env_mode}" == "600" ]] || { echo "redis-runtime-env-mode-must-be-600" >&2; exit 4; }

"${privileged[@]}" install -m 0644 "${compose_source}" "${COMPOSE_DIR}/docker-compose.yml"
"${privileged[@]}" install -m 0755 "${entrypoint_source}" "${COMPOSE_DIR}/gen-acl-and-run.sh"

compose_action=(up -d)
if [[ "${before_state}" != "running" || "${before_health}" != "healthy" ]]; then
  compose_action+=(--force-recreate)
fi
"${privileged[@]}" docker compose \
  --project-directory "${COMPOSE_DIR}" \
  --env-file "${env_file}" \
  -f "${COMPOSE_DIR}/docker-compose.yml" \
  "${compose_action[@]}"

deadline=$((SECONDS + 90))
after_state=""
after_health=""
while (( SECONDS < deadline )); do
  after_state="$(docker inspect -f '{{.State.Status}}' "${CONTAINER}" 2>/dev/null || true)"
  after_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${CONTAINER}" 2>/dev/null || true)"
  if [[ "${after_state}" == "running" && "${after_health}" == "healthy" ]]; then
    break
  fi
  sleep 3
done
[[ "${after_state}" == "running" ]] || { echo "redis-runtime-not-running" >&2; exit 5; }
[[ "${after_health}" == "healthy" ]] || { echo "redis-runtime-not-healthy" >&2; exit 5; }

container_ip="$(docker inspect -f '{{(index .NetworkSettings.Networks "platform-test-net").IPAddress}}' "${CONTAINER}")"
[[ "${container_ip}" == "${EXPECTED_IP}" ]] || { echo "redis-runtime-ip-mismatch" >&2; exit 5; }

ping_result="$(docker exec "${CONTAINER}" sh -c \
  'test -n "$REDIS_PASSWORD" && redis-cli --no-auth-warning -a "$REDIS_PASSWORD" ping' 2>/dev/null)"
[[ "${ping_result}" == "PONG" ]] || { echo "redis-runtime-container-auth-ping-failed" >&2; exit 5; }

endpoint_ip="$(kubectl --context "${CONTEXT}" -n "${NAMESPACE}" \
  get endpoints redis-streams -o jsonpath='{.subsets[0].addresses[0].ip}')"
[[ "${endpoint_ip}" == "${EXPECTED_IP}" ]] || { echo "redis-runtime-endpoint-ip-mismatch" >&2; exit 5; }

pod_name="$(kubectl --context "${CONTEXT}" -n "${NAMESPACE}" \
  get pod -l app.kubernetes.io/name="${DEPLOYMENT}" \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}')"
[[ -n "${pod_name}" ]] || { echo "audio-gateway-pod-unavailable" >&2; exit 5; }

kubectl --context "${CONTEXT}" -n "${NAMESPACE}" exec "${pod_name}" -c "${DEPLOYMENT}" -- \
  bash -c '
set -euo pipefail
host="${SPRING_DATA_REDIS_HOST:-redis-streams}"
port="${SPRING_DATA_REDIS_PORT:-6379}"
password="${SPRING_DATA_REDIS_PASSWORD:-}"
test -n "${password}"
resp_bulk() {
  local value="$1"
  printf "$%s\r\n%s\r\n" "${#value}" "${value}"
}
exec 3<>"/dev/tcp/${host}/${port}"
{
  printf "*2\r\n"
  resp_bulk AUTH
  resp_bulk "${password}"
  printf "*1\r\n"
  resp_bulk PING
  printf "*1\r\n"
  resp_bulk QUIT
} >&3
response="$(timeout 10 cat <&3)"
printf "%s" "${response}" | grep -q "+PONG"
' >/dev/null

action="reconciled"
if [[ "${before_state}" != "running" || "${before_health}" != "healthy" ]]; then
  action="started"
fi

umask 077
mkdir -p "$(dirname "${OUT}")"
jq -n \
  --arg schemaVersion "faz24.redisStreamsTestRuntime.v1" \
  --arg context "${CONTEXT}" \
  --arg namespace "${NAMESPACE}" \
  --arg container "${CONTAINER}" \
  --arg beforeState "${before_state}" \
  --arg beforeHealth "${before_health}" \
  --arg action "${action}" \
  --arg afterState "${after_state}" \
  --arg afterHealth "${after_health}" \
  --arg containerIp "${container_ip}" \
  --arg endpointIp "${endpoint_ip}" \
  --arg podName "${pod_name}" \
  '{
    schemaVersion: $schemaVersion,
    status: "pass",
    environment: {cluster: $context, namespace: $namespace},
    runtime: {
      container: $container,
      beforeState: $beforeState,
      beforeHealth: $beforeHealth,
      action: $action,
      afterState: $afterState,
      afterHealth: $afterHealth,
      containerIp: $containerIp,
      endpointIp: $endpointIp
    },
    verification: {
      containerAuthPing: true,
      audioGatewayPod: $podName,
      podAuthPing: true,
      desiredFilesInstalled: true,
      secretValuesIncluded: false,
      commandOutputIncluded: false
    },
    boundaries: {
      platformTestOnly: true,
      productionMutated: false,
      redisDataPersistent: false
    }
  }' > "${OUT}"
chmod 0600 "${OUT}"

echo "redis_runtime_status=pass"
echo "redis_runtime_action=${action}"
echo "redis_runtime_evidence=${OUT}"
