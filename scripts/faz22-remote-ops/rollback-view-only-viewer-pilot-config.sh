#!/usr/bin/env bash
set -euo pipefail

K8S_CONTEXT="${K8S_CONTEXT:-k3d-test}"
K8S_NAMESPACE="${K8S_NAMESPACE:-platform-test}"
BRIDGE_CONFIGMAP="${BRIDGE_CONFIGMAP:-endpoint-admin-remote-bridge-config-device-key}"
GATEWAY_CONFIGMAP="${GATEWAY_CONFIGMAP:-api-gateway-config}"
GATEWAY_ROUTE_INDEX="${GATEWAY_ROUTE_INDEX:-29}"
[[ "$GATEWAY_ROUTE_INDEX" =~ ^[1-9][0-9]{0,2}$ ]] || {
  echo "viewer rollback config cleanup: invalid route index" >&2
  exit 2
}
GATEWAY_ROUTE_PREFIX="SPRING_CLOUD_GATEWAY_ROUTES_${GATEWAY_ROUTE_INDEX}_"
route_patch="$(jq -cn --arg prefix "$GATEWAY_ROUTE_PREFIX" '
  {data: {
    ($prefix + "ID"): null,
    ($prefix + "URI"): null,
    ($prefix + "ORDER"): null,
    ($prefix + "PREDICATES_0"): null,
    ($prefix + "PREDICATES_1"): null,
    ($prefix + "FILTERS_0"): null
  }}
')"

kubectl --context="${K8S_CONTEXT}" -n "${K8S_NAMESPACE}" \
  patch configmap "${GATEWAY_CONFIGMAP}" --type merge \
  -p "$route_patch"

kubectl --context="${K8S_CONTEXT}" -n "${K8S_NAMESPACE}" \
  patch configmap "${BRIDGE_CONFIGMAP}" --type merge \
  -p '{"data":{"REMOTE_BRIDGE_VIEWER_ENABLED":null,"REMOTE_BRIDGE_VIEW_ONLY_ALLOWED_FRAME_CONTENT_TYPES":null,"REMOTE_BRIDGE_BROKER_VIEW_ONLY_PERMIT_TTL_MILLIS":null}}'

route_keys="$(kubectl --context="${K8S_CONTEXT}" -n "${K8S_NAMESPACE}" \
  get configmap "${GATEWAY_CONFIGMAP}" -o json \
  | jq -r --arg prefix "$GATEWAY_ROUTE_PREFIX" \
    '.data | keys[] | select(startswith($prefix))')"
if [ -n "${route_keys}" ]; then
  echo "viewer rollback config cleanup: gateway route ${GATEWAY_ROUTE_INDEX} keys remain" >&2
  printf '%s\n' "${route_keys}" >&2
  exit 1
fi

kubectl --context="${K8S_CONTEXT}" -n "${K8S_NAMESPACE}" \
  get configmap "${BRIDGE_CONFIGMAP}" -o json \
  | jq -e '
      (.data | has("REMOTE_BRIDGE_VIEWER_ENABLED") | not)
      and (.data | has("REMOTE_BRIDGE_VIEW_ONLY_ALLOWED_FRAME_CONTENT_TYPES") | not)
      and (.data | has("REMOTE_BRIDGE_BROKER_VIEW_ONLY_PERMIT_TTL_MILLIS") | not)
    ' >/dev/null

echo "viewer rollback config cleanup: route and viewer-only keys absent"
