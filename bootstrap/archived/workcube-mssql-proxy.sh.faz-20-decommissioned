#!/usr/bin/env bash
# Faz 19.MSSQL.F — Workcube MSSQL bridge proxy bootstrap (ADR-0005)
#
# Network teşhis (2026-04-25): k3d cluster pod overlay → 10.9.193.0/24 dış subnet'e
# Calico tunneling/routing fail. PG/Vault/Keycloak çalışıyor çünkü kube-proxy DNAT
# aynı bridge'deki container'a yönlendiriyor (172.21.0.4 PG).
#
# Çözüm pattern: Per-cluster docker bridge'de socat container.
# - Pod overlay → kube-proxy DNAT → bridge proxy container IP:11433
# - socat container'dan host pattern (eski compose stack çalıştığı pattern) → 10.9.193.201:1433
# - K8s Endpoints overlay'lerde container IP pin'li
#
# Idempotent: existing container varsa kontrol eder, gerekirse recreate eder.
# Kullanım: bash bootstrap/workcube-mssql-proxy.sh

set -euo pipefail

MSSQL_HOST="${MSSQL_HOST:-10.9.193.201}"
MSSQL_PORT="${MSSQL_PORT:-1433}"
LISTEN_PORT="${LISTEN_PORT:-11433}"
IMAGE="${IMAGE:-alpine/socat:latest}"

declare -A NETWORKS=(
  [prod]="platform-prod-net"
  [test]="platform-test-net"
)

declare -A EXPECTED_IPS=(
  [prod]="172.21.0.7"      # gitops overlays/prod/endpoints-workcube-mssql.yaml ile sync
  [test]="172.19.0.8"      # gitops overlays/test/endpoints-workcube-mssql.yaml ile sync
)

log() { printf '\033[0;36m[workcube-proxy]\033[0m %s\n' "$*" >&2; }

for env in prod test; do
  CONTAINER_NAME="workcube-mssql-proxy-${env}"
  NETWORK="${NETWORKS[$env]}"
  EXPECTED_IP="${EXPECTED_IPS[$env]}"

  # Existing kontrol
  if sudo docker ps --filter "name=^${CONTAINER_NAME}$" --format '{{.Names}}' | grep -q "${CONTAINER_NAME}"; then
    CURRENT_IP=$(sudo docker inspect "${CONTAINER_NAME}" --format "{{ (index .NetworkSettings.Networks \"${NETWORK}\").IPAddress }}")
    if [[ "${CURRENT_IP}" == "${EXPECTED_IP}" ]]; then
      log "OK ${CONTAINER_NAME} running, IP=${CURRENT_IP} (expected ${EXPECTED_IP})"
      continue
    else
      log "MISMATCH ${CONTAINER_NAME} IP=${CURRENT_IP}, expected ${EXPECTED_IP} — recreate"
      sudo docker rm -f "${CONTAINER_NAME}"
    fi
  fi

  log "DEPLOY ${CONTAINER_NAME} on ${NETWORK} (target ${MSSQL_HOST}:${MSSQL_PORT})"
  sudo docker run -d \
    --name "${CONTAINER_NAME}" \
    --network "${NETWORK}" \
    --ip "${EXPECTED_IP}" \
    --restart=always \
    "${IMAGE}" \
    "tcp4-listen:${LISTEN_PORT},fork,reuseaddr" \
    "tcp4:${MSSQL_HOST}:${MSSQL_PORT}"
  sleep 2
  ACTUAL_IP=$(sudo docker inspect "${CONTAINER_NAME}" --format "{{ (index .NetworkSettings.Networks \"${NETWORK}\").IPAddress }}")
  log "OK ${CONTAINER_NAME} deployed, IP=${ACTUAL_IP}"
done

log "DONE. Verify:"
log "  kubectl --context=k3d-prod -n platform-prod get endpoints workcube-mssql"
log "  kubectl --context=k3d-test -n platform-test get endpoints workcube-mssql"
