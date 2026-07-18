#!/usr/bin/env bash
# Execute one fixed, signed-intent VIEW_ONLY stage. No dispatch input is read.

set -euo pipefail

STAGE="${1:-}"
case "$STAGE" in
  apply|browser-evidence|compensating-rollback) ;;
  *) echo "protected-view-only-stage: invalid stage" >&2; exit 2 ;;
esac

: "${CROSS_AI_BOOTSTRAP_FILE:?verified bootstrap file is required}"
[[ -f "$CROSS_AI_BOOTSTRAP_FILE" && ! -L "$CROSS_AI_BOOTSTRAP_FILE" ]] || {
  echo "protected-view-only-stage: bootstrap file is unavailable" >&2
  exit 2
}

K8S_CONTEXT="k3d-test"
K8S_NAMESPACE="platform-test"
BRIDGE_DEPLOYMENT="endpoint-admin-remote-bridge-device-key"
BRIDGE_CONFIGMAP="endpoint-admin-remote-bridge-config-device-key"
GATEWAY_DEPLOYMENT="api-gateway"
GATEWAY_CONFIGMAP="api-gateway-config"
VIEWER_OVERLAY="kustomize/overlays/test/activation/endpoint-admin-remote-bridge-viewer"
BROKER_ONLY_OVERLAY="kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key-live"
WATCHDOG_TEMPLATE="scripts/faz22-remote-ops/view-only-viewer-pilot-watchdog.template.yaml"
WATCHDOG_RECEIPT="${RUNNER_TEMP:?}/cross-ai-watchdog-expires-at"

for command in bash date docker jq kubectl python3 sha256sum ssh; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "protected-view-only-stage: missing runtime command $command" >&2
    exit 2
  }
done

mapfile -t BINDING < <(
  python3 - "$CROSS_AI_BOOTSTRAP_FILE" "$STAGE" <<'PY'
import base64
import json
import os
import stat
import sys

flags = os.O_RDONLY
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
descriptor = os.open(sys.argv[1], flags)
metadata = os.fstat(descriptor)
if (
    not stat.S_ISREG(metadata.st_mode)
    or metadata.st_uid != os.getuid()
    or stat.S_IMODE(metadata.st_mode) != 0o600
):
    os.close(descriptor)
    raise SystemExit("bootstrap file ownership or mode is invalid")
with os.fdopen(descriptor, encoding="utf-8") as handle:
    response = json.load(handle)
if response.get("stage") != sys.argv[2]:
    raise SystemExit("bootstrap stage mismatch")
bundle = json.loads(base64.b64decode(response["bundleEnvelope"]["payload"], validate=True))
print(response["bundleSha256"])
print(bundle["grant"]["expiresAt"])
print(bundle["subject"]["endpointIdSha256"])
PY
)
[[ "${#BINDING[@]}" -eq 3 ]] || {
  echo "protected-view-only-stage: signed bootstrap projection is invalid" >&2
  exit 2
}
BUNDLE_SHA256="${BINDING[0]}"
GRANT_EXPIRES_AT="${BINDING[1]}"
ENDPOINT_ID_SHA256="${BINDING[2]}"
[[ "$BUNDLE_SHA256" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 2
[[ "$ENDPOINT_ID_SHA256" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 2
GRANT_EXPIRES_EPOCH="$(date -u -d "$GRANT_EXPIRES_AT" +%s)" || exit 2

rollback_surface() {
  local live_bundle
  live_bundle="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get job faz22-view-only-pilot-watchdog \
    -o jsonpath='{.metadata.annotations.faz22\.6\.acik\.com/authorization-sha256}' \
    2>/dev/null)"
  if [[ "$live_bundle" != "$BUNDLE_SHA256" ]]; then
    echo "protected-view-only-stage: rollback ownership marker differs" >&2
    return 1
  fi
  set +e
  bash scripts/faz22-remote-ops/rollback-view-only-viewer-pilot-config.sh
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    delete service endpoint-admin-remote-bridge-viewer --ignore-not-found
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    delete networkpolicy eab-bridge-viewer-allow-ingress-8096-from-api-gateway \
    eab-api-gateway-allow-egress-8096-to-bridge-viewer --ignore-not-found
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" apply -k "$BROKER_ONLY_OVERLAY"
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout restart \
    "deploy/$BRIDGE_DEPLOYMENT" "deploy/$GATEWAY_DEPLOYMENT"
}

verify_rollback() {
  if kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get service endpoint-admin-remote-bridge-viewer >/dev/null 2>&1; then
    return 1
  fi
  if kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get networkpolicy eab-bridge-viewer-allow-ingress-8096-from-api-gateway \
    >/dev/null 2>&1; then
    return 1
  fi
  if kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get networkpolicy eab-api-gateway-allow-egress-8096-to-bridge-viewer \
    >/dev/null 2>&1; then
    return 1
  fi
  local route_keys
  route_keys="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get configmap "$GATEWAY_CONFIGMAP" -o json \
    | jq -r '.data | keys[] | select(startswith("SPRING_CLOUD_GATEWAY_ROUTES_28_"))')"
  [[ -z "$route_keys" ]]
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get configmap "$BRIDGE_CONFIGMAP" -o json \
    | jq -e '
        (.data | has("REMOTE_BRIDGE_VIEWER_ENABLED") | not)
        and (.data | has("REMOTE_BRIDGE_VIEW_ONLY_ALLOWED_FRAME_CONTENT_TYPES") | not)
        and (.data | has("REMOTE_BRIDGE_BROKER_VIEW_ONLY_PERMIT_TTL_MILLIS") | not)
      ' >/dev/null
}

compensate_apply_error() {
  local exit_status="$?"
  trap - ERR
  rollback_surface || true
  exit "$exit_status"
}

run_apply() {
  local work expires_epoch active_deadline
  work="$RUNNER_TEMP/cross-ai-view-only-apply"
  rm -rf -- "$work"
  mkdir -m 0700 "$work"
  expires_epoch="$GRANT_EXPIRES_EPOCH"
  (( expires_epoch - $(date -u +%s) >= 1200 )) || {
    echo "protected-view-only-stage: signed grant has insufficient apply headroom" >&2
    return 1
  }

  kubectl kustomize "$VIEWER_OVERLAY" > "$work/viewer.yaml"
  kubectl kustomize kustomize/overlays/test > "$work/test-root.yaml"
  if grep -q 'endpoint-admin-remote-bridge-viewer' "$work/test-root.yaml"; then
    echo "protected-view-only-stage: viewer leaked into the test Argo root" >&2
    return 1
  fi
  grep -q 'name: endpoint-admin-remote-bridge-viewer' "$work/viewer.yaml"
  grep -q 'type: ClusterIP' "$work/viewer.yaml"
  if grep -q 'nodePort:' "$work/viewer.yaml"; then
    echo "protected-view-only-stage: viewer rendered a nodePort" >&2
    return 1
  fi
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    apply --dry-run=server -f "$work/viewer.yaml"

  active_deadline="$(( expires_epoch - $(date -u +%s) + 600 ))"
  sed \
    -e "s/__EXPIRES_EPOCH__/${expires_epoch}/g" \
    -e "s/__ACTIVE_DEADLINE_SECONDS__/${active_deadline}/g" \
    -e "s/__AUTHORIZATION_SHA256__/${BUNDLE_SHA256}/g" \
    "$WATCHDOG_TEMPLATE" > "$work/watchdog.yaml"
  if grep -q '__[A-Z0-9_]*__' "$work/watchdog.yaml"; then
    echo "protected-view-only-stage: watchdog template is unresolved" >&2
    return 1
  fi
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    delete job faz22-view-only-pilot-watchdog --ignore-not-found --wait=true
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    apply --dry-run=server -f "$work/watchdog.yaml"
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" apply -f "$work/watchdog.yaml"
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    wait --for=condition=Ready pod \
    -l app.kubernetes.io/name=faz22-view-only-pilot-watchdog --timeout=120s
  printf '%s\n' "$GRANT_EXPIRES_AT" > "$WATCHDOG_RECEIPT"
  chmod 0600 "$WATCHDOG_RECEIPT"

  trap compensate_apply_error ERR
  VIEWER_AUDIT_DB_ROLE_CONFIRM=RECONCILE_FAZ22_6_VIEWER_AUDIT_DB_ROLE \
    bash scripts/faz22-remote-ops/reconcile-viewer-audit-db-role.sh apply
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" apply -f "$work/viewer.yaml"
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    rollout restart "deploy/$BRIDGE_DEPLOYMENT"
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    rollout status "deploy/$BRIDGE_DEPLOYMENT" --timeout=300s

  # The ${sid} token is a Spring RewritePath variable, not a shell expansion.
  local route_patch
  # shellcheck disable=SC2016
  route_patch='{"data":{"SPRING_CLOUD_GATEWAY_ROUTES_28_ID":"remote-bridge-viewer-route","SPRING_CLOUD_GATEWAY_ROUTES_28_URI":"http://endpoint-admin-remote-bridge-viewer:8096","SPRING_CLOUD_GATEWAY_ROUTES_28_ORDER":"-10","SPRING_CLOUD_GATEWAY_ROUTES_28_PREDICATES_0":"Path=/api/v1/endpoint-admin/remote-access/sessions/*/view","SPRING_CLOUD_GATEWAY_ROUTES_28_PREDICATES_1":"Method=GET,POST","SPRING_CLOUD_GATEWAY_ROUTES_28_FILTERS_0":"RewritePath=/api/v1/endpoint-admin/remote-access/sessions/(?<sid>[^/]+)/view, /internal/remote-bridge/operator/sessions/${sid}/view"}}'
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" patch configmap \
    "$GATEWAY_CONFIGMAP" --type merge -p "$route_patch"
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    rollout restart "deploy/$GATEWAY_DEPLOYMENT"
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    rollout status "deploy/$GATEWAY_DEPLOYMENT" --timeout=300s

  [[ "$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get service endpoint-admin-remote-bridge-viewer -o jsonpath='{.spec.type}')" == "ClusterIP" ]]
  [[ -z "$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get service endpoint-admin-remote-bridge-viewer -o jsonpath='{.spec.ports[*].nodePort}')" ]]
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get configmap "$BRIDGE_CONFIGMAP" -o json \
    | jq -e '.data.REMOTE_BRIDGE_VIEWER_ENABLED == "true"
        and .data.REMOTE_BRIDGE_VIEW_ONLY_ALLOWED_FRAME_CONTENT_TYPES == "image/png"
        and .data.REMOTE_BRIDGE_BROKER_VIEW_ONLY_PERMIT_TTL_MILLIS == "600000"' \
      >/dev/null
  [[ "$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get configmap "$GATEWAY_CONFIGMAP" \
    -o jsonpath='{.data.SPRING_CLOUD_GATEWAY_ROUTES_28_ID}')" == \
    "remote-bridge-viewer-route" ]]
  trap - ERR
}

run_browser() {
  local hostname device_id actual_hash expires_epoch remaining runtime evidence source
  hostname="$(ssh -n -F /home/halil/.ssh/config -o BatchMode=yes denetim-pc hostname \
    2>/dev/null | tr -d '\r\n[:space:]')"
  [[ "$hostname" =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,126}$ ]]
  device_id="$(docker exec -i platform-pg-test psql -U postgres -d endpoint_admin \
    -At -v ON_ERROR_STOP=1 -v "device_hostname=$hostname" <<'SQL'
SELECT d.id::text
FROM endpoint_admin_service.endpoint_devices d
WHERE d.tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
  AND lower(d.hostname) = lower(:'device_hostname')
  AND d.status = 'ONLINE'
  AND EXISTS (
    SELECT 1 FROM endpoint_admin_service.endpoint_machine_certs c
    WHERE c.device_id = d.id AND c.tenant_id = d.tenant_id
      AND c.revoked_at IS NULL AND c.channel = 'VAULT_TPM'
      AND c.cert_not_before <= now() AND now() < c.cert_not_after
  )
  AND EXISTS (
    SELECT 1 FROM endpoint_admin_service.endpoint_tpm_device_binding b
    WHERE b.device_id = d.id AND b.tenant_id = d.tenant_id AND b.revoked_at IS NULL
  );
SQL
)"
  [[ "$device_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]
  actual_hash="sha256:$(printf '%s' "$device_id" | sha256sum | awk '{print $1}')"
  [[ "$actual_hash" == "$ENDPOINT_ID_SHA256" ]] || {
    echo "protected-view-only-stage: live endpoint differs from signed subject" >&2
    return 1
  }
  DEVICE_ID="$device_id" DEVICE_HOSTNAME="$hostname" \
    bash scripts/faz22-remote-ops/verify-view-only-viewer-target.sh
  bash scripts/faz22-remote-ops/reconcile-viewer-audit-db-role.sh check

  [[ "$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" get job \
    faz22-view-only-pilot-watchdog \
    -o jsonpath='{.metadata.annotations.faz22\.6\.acik\.com/authorization-sha256}')" \
    == "$BUNDLE_SHA256" ]]
  expires_epoch="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" get job \
    faz22-view-only-pilot-watchdog \
    -o jsonpath='{.metadata.annotations.faz22\.6\.acik\.com/expires-at-epoch}')"
  remaining="$(( expires_epoch - $(date -u +%s) ))"
  (( remaining >= 900 )) || {
    echo "protected-view-only-stage: watchdog has insufficient browser headroom" >&2
    return 1
  }

  runtime="$RUNNER_TEMP/faz22-viewer-playwright"
  mkdir -p "$runtime"
  if [[ ! -s "$runtime/node_modules/playwright/package.json" ]]; then
    npm --prefix "$runtime" init --yes >/dev/null
    npm --prefix "$runtime" install --no-audit --no-fund --save-exact playwright@1.60.0
    npm --prefix "$runtime" exec playwright install chromium
  fi
  evidence="$RUNNER_TEMP/faz22-viewer-browser-collector"
  rm -rf -- "$evidence"
  mkdir -m 0700 "$evidence"
  export DEVICE_ID="$device_id" DEVICE_HOSTNAME="$hostname"
  export PILOT_SECONDS=300 PRODUCT_PILOT_SECONDS=300 CONSENT_WAIT_SECONDS=240
  export SOURCE_REVISION="$GITHUB_SHA"
  export BROWSER_EVIDENCE_SCRIPT="$GITHUB_WORKSPACE/scripts/faz22-remote-ops/faz22-6-viewer-browser-evidence.mjs"
  export BROWSER_DIAGNOSTIC_OUTPUT="$evidence/browser-diagnostic.json"
  export PLAYWRIGHT_PACKAGE_ROOT="$runtime" VIEWER_PRODUCT_BASE_URL=https://testai.acik.com
  export REMOTE_BRIDGE_DEPLOYMENT="$BRIDGE_DEPLOYMENT" REQUIRE_ACTIVE_GUI=1
  export DENETIM_SSH_TARGET=denetim-pc DENETIM_SSH_OPTS=__SSH_CONFIG__
  export OPEN_SESSION_DEVICE_READY_SECONDS=180 OPEN_SESSION_DEVICE_READY_INTERVAL_SECONDS=5
  export EVIDENCE_DIR="$evidence" AUTO_FINALIZE=0 DLP_MASK_RECT_BPS=7500,7500,2500,2500
  bash scripts/faz22-remote-ops/apply-denetim-attestation-migration.sh \
    bash scripts/faz22-remote-ops/faz22-6-view-only-attended-smoke.sh
  jq -e '.status == "accepted-candidate" and .consentWait == "granted"' \
    "$evidence/summary.json" >/dev/null
  jq -e '.payload.renderAckAcceptedCount >= 100
      and .payload.renderAckAcceptedCount == .payload.renderAckAttemptedCount' \
    "$evidence/browser.json" >/dev/null
  source="$RUNNER_TEMP/faz22-viewer-browser-source"
  rm -rf -- "$source"
  mkdir -m 0700 "$source"
  install -m 0600 "$evidence/browser.json" "$source/browser.json"
  install -m 0600 "$evidence/consent.json" "$source/consent.json"
  install -m 0600 "$evidence/consent-source.json" "$source/consent-source.json"
}

run_rollback() {
  rollback_surface
  set -e
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    rollout status "deploy/$BRIDGE_DEPLOYMENT" --timeout=300s
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    rollout status "deploy/$GATEWAY_DEPLOYMENT" --timeout=300s
  for resource in \
    "job/faz22-view-only-pilot-watchdog" \
    "rolebinding/faz22-view-only-pilot-watchdog" \
    "role/faz22-view-only-pilot-watchdog" \
    "serviceaccount/faz22-view-only-pilot-watchdog" \
    "networkpolicy/allow-faz22-view-only-watchdog-kubernetes-api"; do
    kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
      delete "$resource" --ignore-not-found --wait=true
  done
  verify_rollback
}

case "$STAGE" in
  apply) run_apply ;;
  browser-evidence) run_browser ;;
  compensating-rollback) run_rollback ;;
esac

echo "protected-view-only-stage: $STAGE verified"
