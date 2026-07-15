#!/usr/bin/env bash
set -euo pipefail

K8S_CONTEXT="${K8S_CONTEXT:-k3d-test}"
K8S_NAMESPACE="${K8S_NAMESPACE:-platform-test}"
BRIDGE_CONFIGMAP="${BRIDGE_CONFIGMAP:-endpoint-admin-remote-bridge-config-device-key}"
GATEWAY_CONFIGMAP="${GATEWAY_CONFIGMAP:-api-gateway-config}"

kubectl --context="${K8S_CONTEXT}" -n "${K8S_NAMESPACE}" \
  patch configmap "${GATEWAY_CONFIGMAP}" --type merge \
  -p '{"data":{"SPRING_CLOUD_GATEWAY_ROUTES_28_ID":null,"SPRING_CLOUD_GATEWAY_ROUTES_28_URI":null,"SPRING_CLOUD_GATEWAY_ROUTES_28_ORDER":null,"SPRING_CLOUD_GATEWAY_ROUTES_28_PREDICATES_0":null,"SPRING_CLOUD_GATEWAY_ROUTES_28_PREDICATES_1":null,"SPRING_CLOUD_GATEWAY_ROUTES_28_FILTERS_0":null}}'

kubectl --context="${K8S_CONTEXT}" -n "${K8S_NAMESPACE}" \
  patch configmap "${BRIDGE_CONFIGMAP}" --type merge \
  -p '{"data":{"REMOTE_BRIDGE_VIEWER_ENABLED":null,"REMOTE_BRIDGE_VIEW_ONLY_ALLOWED_FRAME_CONTENT_TYPES":null}}'

route_keys="$(kubectl --context="${K8S_CONTEXT}" -n "${K8S_NAMESPACE}" \
  get configmap "${GATEWAY_CONFIGMAP}" -o json \
  | jq -r '.data | keys[] | select(startswith("SPRING_CLOUD_GATEWAY_ROUTES_28_"))')"
if [ -n "${route_keys}" ]; then
  echo "viewer rollback config cleanup: gateway route 28 keys remain" >&2
  printf '%s\n' "${route_keys}" >&2
  exit 1
fi

kubectl --context="${K8S_CONTEXT}" -n "${K8S_NAMESPACE}" \
  get configmap "${BRIDGE_CONFIGMAP}" -o json \
  | jq -e '
      (.data | has("REMOTE_BRIDGE_VIEWER_ENABLED") | not)
      and (.data | has("REMOTE_BRIDGE_VIEW_ONLY_ALLOWED_FRAME_CONTENT_TYPES") | not)
    ' >/dev/null

echo "viewer rollback config cleanup: route and viewer-only keys absent"
