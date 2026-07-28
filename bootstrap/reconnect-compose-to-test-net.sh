#!/usr/bin/env bash
# Verify aiserver TEST compose networking against GitOps and live Endpoints.
#
# This tool is intentionally read-only. Network membership and static addresses
# are owned by host-compose, while Kubernetes Endpoints are owned by the test
# Kustomize overlay and ArgoCD. Drift must be repaired at those sources; direct
# docker network connect, kubectl patch, or rollout restart is forbidden.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${REMOTE:-aiadmin@aiserver}"
NETWORK="${NETWORK:-platform-test-net}"
OVERLAY="${OVERLAY:-${ROOT}/kustomize/overlays/test}"

CONTAINER_ENDPOINTS=(
  "platform-pg-test:postgres"
  "platform-kc-test:keycloak"
  "platform-vault-test:vault"
  "platform-redis-streams-test:redis-streams"
  "minio-minio-test-1:minio"
)

fail() {
  printf '[compose-net-verify] FAIL %s\n' "$*" >&2
  exit 1
}

for command in ssh kustomize python3; do
  command -v "${command}" >/dev/null 2>&1 || fail "missing command: ${command}"
done

remote_hostname="$(
  ssh -o BatchMode=yes -o ConnectTimeout=10 "${REMOTE}" hostname
)"
[[ "${remote_hostname}" == "aiserver" ]] || {
  fail "target must be aiserver, got ${remote_hostname}"
}

rendered="$(kustomize build "${OVERLAY}")"

endpoint_ip() {
  local endpoint_name="$1"
  ENDPOINT_NAME="${endpoint_name}" python3 -c '
import os
import sys
import yaml

name = os.environ["ENDPOINT_NAME"]
matches = [
    item
    for item in yaml.safe_load_all(sys.stdin.read())
    if isinstance(item, dict)
    and item.get("kind") == "Endpoints"
    and item.get("metadata", {}).get("name") == name
]
if len(matches) != 1:
    raise SystemExit(f"expected one Endpoints/{name}, got {len(matches)}")
print(matches[0]["subsets"][0]["addresses"][0]["ip"])
' <<<"${rendered}"
}

failures=0
for entry in "${CONTAINER_ENDPOINTS[@]}"; do
  container="${entry%%:*}"
  endpoint="${entry##*:}"
  expected="$(endpoint_ip "${endpoint}")"

  state="$(
    ssh -o BatchMode=yes "${REMOTE}" \
      "docker inspect -f '{{.State.Status}}' '${container}'" 2>/dev/null || true
  )"
  actual="$(
    ssh -o BatchMode=yes "${REMOTE}" \
      "docker inspect -f '{{(index .NetworkSettings.Networks \"${NETWORK}\").IPAddress}}' '${container}'" \
      2>/dev/null |
      cut -d/ -f1
  )"
  live="$(
    ssh -o BatchMode=yes "${REMOTE}" \
      "kubectl --context k3d-test -n platform-test get endpoints '${endpoint}' -o jsonpath='{.subsets[0].addresses[0].ip}'" \
      2>/dev/null || true
  )"

  if [[ "${state}" != "running" || -z "${actual}" ||
        "${actual}" != "${expected}" || "${live}" != "${expected}" ]]; then
    printf \
      '[compose-net-verify] MISMATCH container=%s state=%s actual=%s desired=%s live=%s\n' \
      "${container}" "${state:-missing}" "${actual:-missing}" \
      "${expected}" "${live:-missing}" >&2
    failures=$((failures + 1))
    continue
  fi

  printf \
    '[compose-net-verify] PASS container=%s endpoint=%s ip=%s\n' \
    "${container}" "${endpoint}" "${expected}"
done

[[ "${failures}" -eq 0 ]] || {
  fail "${failures} mismatch(es); repair host-compose or GitOps source, then sync"
}

printf '[compose-net-verify] PASS all TEST host-service bindings match\n'
