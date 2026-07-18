#!/usr/bin/env bash
# Execute one fixed, signed-intent VIEW_ONLY stage. No dispatch input is read.

set -euo pipefail

: "${CROSS_AI_SOURCE_ROOT:?Pinned Cross-AI source root is required}"
cd -- "$CROSS_AI_SOURCE_ROOT"
[[ -f scripts/github_apps/cross_ai_deployment_policy/canonical.py \
  && -f scripts/faz22-remote-ops/run-cross-ai-protected-view-only-stage.sh ]] || {
  echo "protected-view-only-stage: checked-out repository root is unavailable" >&2
  exit 2
}

STAGE="${1:-}"
case "$STAGE" in
  apply)
    EXPECTED_WORKFLOW_PATH=".github/workflows/apply-view-only-viewer-pilot-protected.yml"
    ;;
  browser-evidence)
    EXPECTED_WORKFLOW_PATH=".github/workflows/faz22-6-view-only-viewer-browser-evidence-protected.yml"
    ;;
  compensating-rollback)
    EXPECTED_WORKFLOW_PATH=".github/workflows/rollback-view-only-viewer-pilot-protected.yml"
    ;;
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
GATEWAY_ROUTE_INDEX="28"
GATEWAY_ROUTE_PREFIX="SPRING_CLOUD_GATEWAY_ROUTES_${GATEWAY_ROUTE_INDEX}_"
VIEWER_OVERLAY="kustomize/overlays/test/activation/endpoint-admin-remote-bridge-viewer"
BROKER_ONLY_OVERLAY="kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key-live"
WATCHDOG_TEMPLATE="scripts/faz22-remote-ops/view-only-viewer-pilot-watchdog.template.yaml"
WATCHDOG_RECEIPT="${RUNNER_TEMP:?}/cross-ai-watchdog-expires-at"
WATCHDOG_NETWORK_POLICY_FILTER="scripts/faz22-remote-ops/verify-watchdog-network-policy.jq"
BROWSER_RUNTIME_ARCHIVE="/opt/acik/cross-ai/browser-runtime/playwright-1.60.0-linux-x64.tar"

for command in bash date docker jq kubectl python3 sha256sum ssh; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "protected-view-only-stage: missing runtime command $command" >&2
    exit 2
  }
done

mapfile -t BINDING < <(
  python3 - "$CROSS_AI_BOOTSTRAP_FILE" "$STAGE" "$EXPECTED_WORKFLOW_PATH" <<'PY'
import base64
import binascii
import json
import os
import stat
import sys

from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest

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
unsigned_response = dict(response)
response_digest = unsigned_response.pop("responseSha256", None)
if response_digest != sha256_digest(unsigned_response):
    raise SystemExit("bootstrap response digest mismatch")
envelope = response.get("bundleEnvelope")
if not isinstance(envelope, dict) or response.get("bundleSha256") != sha256_digest(envelope):
    raise SystemExit("bootstrap bundle digest mismatch")
try:
    bundle = json.loads(base64.b64decode(envelope["payload"], validate=True))
except (KeyError, TypeError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
    raise SystemExit("bootstrap bundle payload is invalid") from None
stages = [item for item in bundle["workflowStages"] if item["stage"] == sys.argv[2]]
if len(stages) != 1:
    raise SystemExit("signed workflow stage is ambiguous")
subject = bundle.get("subject")
if not isinstance(subject, dict):
    raise SystemExit("signed subject is unavailable")
expected_runtime = {
    "runId": int(os.environ["GITHUB_RUN_ID"]),
    "runAttempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
    "headSha": os.environ["GITHUB_SHA"],
    "intentRef": os.environ["GITHUB_REF"],
    "workflowPath": sys.argv[3],
}
if any(response.get(field) != value for field, value in expected_runtime.items()):
    raise SystemExit("bootstrap response differs from the current workflow run")
if (
    subject.get("headSha") != expected_runtime["headSha"]
    or subject.get("intentRef") != expected_runtime["intentRef"]
    or subject.get("repository") != os.environ["GITHUB_REPOSITORY"]
    or str(subject.get("repositoryId")) != os.environ["GITHUB_REPOSITORY_ID"]
    or stages[0].get("workflowPath") != expected_runtime["workflowPath"]
):
    raise SystemExit("signed subject differs from the current workflow run")
print(response["bundleSha256"])
print(bundle["grant"]["expiresAt"])
print(subject["endpointIdSha256"])
print(stages[0]["runtimeBundleSha256"] or "")
PY
)
[[ "${#BINDING[@]}" -eq 4 ]] || {
  echo "protected-view-only-stage: signed bootstrap projection is invalid" >&2
  exit 2
}
BUNDLE_SHA256="${BINDING[0]}"
GRANT_EXPIRES_AT="${BINDING[1]}"
ENDPOINT_ID_SHA256="${BINDING[2]}"
RUNTIME_BUNDLE_SHA256="${BINDING[3]}"
[[ "$BUNDLE_SHA256" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 2
[[ "$ENDPOINT_ID_SHA256" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 2
if [[ "$STAGE" == "browser-evidence" ]]; then
  [[ "$RUNTIME_BUNDLE_SHA256" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 2
else
  [[ -z "$RUNTIME_BUNDLE_SHA256" ]] || exit 2
fi
GRANT_EXPIRES_EPOCH="$(date -u -d "$GRANT_EXPIRES_AT" +%s)" || exit 2

verify_watchdog_active() {
  local job_json pod_json service_account role role_binding network_policy permission
  job_json="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get job faz22-view-only-pilot-watchdog -o json)"
  jq -e \
    --arg bundle "$BUNDLE_SHA256" \
    --arg expiry "$GRANT_EXPIRES_EPOCH" '
      .metadata.annotations["faz22.6.acik.com/authorization-sha256"] == $bundle
      and .metadata.annotations["faz22.6.acik.com/expires-at-epoch"] == $expiry
      and ((.status.active // 0) == 1)
      and ((.status.failed // 0) == 0)
      and ((.status.succeeded // 0) == 0)
    ' <<<"$job_json" >/dev/null

  service_account="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get serviceaccount faz22-view-only-pilot-watchdog -o json)"
  jq -e '
    .metadata.deletionTimestamp == null
    and .automountServiceAccountToken == false
  ' <<<"$service_account" >/dev/null

  role="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get role faz22-view-only-pilot-watchdog -o json)"
  jq -e '
    def normalized:
      map({
        apiGroups: (.apiGroups | sort),
        resources: (.resources | sort),
        resourceNames: (.resourceNames | sort),
        verbs: (.verbs | sort)
      }) | sort_by([(.apiGroups | join(",")), (.resources | join(","))]);
    .metadata.deletionTimestamp == null
    and (.rules | normalized) == ([
      {apiGroups: [""], resources: ["configmaps"], resourceNames: ["endpoint-admin-remote-bridge-config-device-key", "api-gateway-config"], verbs: ["get", "patch"]},
      {apiGroups: [""], resources: ["services"], resourceNames: ["endpoint-admin-remote-bridge-viewer"], verbs: ["delete", "get"]},
      {apiGroups: ["apps"], resources: ["deployments"], resourceNames: ["api-gateway", "endpoint-admin-remote-bridge-device-key"], verbs: ["get", "patch"]},
      {apiGroups: ["networking.k8s.io"], resources: ["networkpolicies"], resourceNames: ["eab-api-gateway-allow-egress-8096-to-bridge-viewer", "eab-bridge-viewer-allow-ingress-8096-from-api-gateway"], verbs: ["delete", "get"]}
    ] | normalized)
  ' <<<"$role" >/dev/null

  role_binding="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get rolebinding faz22-view-only-pilot-watchdog -o json)"
  jq -e --arg namespace "$K8S_NAMESPACE" '
    .metadata.deletionTimestamp == null
    and .roleRef == {apiGroup: "rbac.authorization.k8s.io", kind: "Role", name: "faz22-view-only-pilot-watchdog"}
    and .subjects == [{kind: "ServiceAccount", name: "faz22-view-only-pilot-watchdog", namespace: $namespace}]
  ' <<<"$role_binding" >/dev/null

  network_policy="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get networkpolicy allow-faz22-view-only-watchdog-kubernetes-api -o json)"
  jq -e -f "$WATCHDOG_NETWORK_POLICY_FILTER" <<<"$network_policy" >/dev/null

  for permission in \
    "get configmap/endpoint-admin-remote-bridge-config-device-key" \
    "patch configmap/endpoint-admin-remote-bridge-config-device-key" \
    "get configmap/api-gateway-config" \
    "patch configmap/api-gateway-config" \
    "get service/endpoint-admin-remote-bridge-viewer" \
    "delete service/endpoint-admin-remote-bridge-viewer" \
    "get deployment/endpoint-admin-remote-bridge-device-key" \
    "patch deployment/endpoint-admin-remote-bridge-device-key" \
    "get deployment/api-gateway" \
    "patch deployment/api-gateway" \
    "get networkpolicy/eab-bridge-viewer-allow-ingress-8096-from-api-gateway" \
    "delete networkpolicy/eab-bridge-viewer-allow-ingress-8096-from-api-gateway" \
    "get networkpolicy/eab-api-gateway-allow-egress-8096-to-bridge-viewer" \
    "delete networkpolicy/eab-api-gateway-allow-egress-8096-to-bridge-viewer"; do
    # Deliberate word splitting turns each fixed pair into verb + resource/name.
    # shellcheck disable=SC2086
    [[ "$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" auth can-i $permission \
      --as="system:serviceaccount:${K8S_NAMESPACE}:faz22-view-only-pilot-watchdog")" == "yes" ]]
  done

  pod_json="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get pods -l batch.kubernetes.io/job-name=faz22-view-only-pilot-watchdog -o json)"
  jq -e --arg job_uid "$(jq -r '.metadata.uid' <<<"$job_json")" '
    [.items[] | select(
      .metadata.deletionTimestamp == null
      and any(.metadata.ownerReferences[]?; .uid == $job_uid and .kind == "Job" and .name == "faz22-view-only-pilot-watchdog" and .controller == true)
      and .spec.serviceAccountName == "faz22-view-only-pilot-watchdog"
      and .spec.automountServiceAccountToken == true
      and .status.phase == "Running"
      and any(.status.conditions[]?; .type == "Ready" and .status == "True")
      and any(.status.containerStatuses[]?; .name == "watchdog" and .ready == true and (.state.running.startedAt | type == "string"))
    )] | length == 1
  ' <<<"$pod_json" >/dev/null
}

rollback_surface() {
  local live_bundle status
  live_bundle="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get job faz22-view-only-pilot-watchdog \
    -o jsonpath='{.metadata.annotations.faz22\.6\.acik\.com/authorization-sha256}' \
    2>/dev/null)"
  if [[ "$live_bundle" != "$BUNDLE_SHA256" ]]; then
    echo "protected-view-only-stage: rollback ownership marker differs" >&2
    return 1
  fi
  status=0
  GATEWAY_ROUTE_INDEX="$GATEWAY_ROUTE_INDEX" \
    bash scripts/faz22-remote-ops/rollback-view-only-viewer-pilot-config.sh || status=1
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    delete service endpoint-admin-remote-bridge-viewer --ignore-not-found || status=1
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    delete networkpolicy eab-bridge-viewer-allow-ingress-8096-from-api-gateway \
    eab-api-gateway-allow-egress-8096-to-bridge-viewer --ignore-not-found || status=1
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    apply -k "$BROKER_ONLY_OVERLAY" || status=1
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout restart \
    "deploy/$BRIDGE_DEPLOYMENT" "deploy/$GATEWAY_DEPLOYMENT" || status=1
  return "$status"
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
    | jq -r --arg prefix "$GATEWAY_ROUTE_PREFIX" \
      '.data | keys[] | select(startswith($prefix))')"
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
  if rollback_surface && verify_rollback; then
    echo "protected-view-only-stage: apply failure compensation verified" >&2
  else
    echo "protected-view-only-stage: apply failure compensation incomplete; watchdog remains authoritative" >&2
  fi
  exit "$exit_status"
}

run_apply() {
  local work expires_epoch now_epoch active_deadline existing_route_keys
  work="$RUNNER_TEMP/cross-ai-view-only-apply"
  rm -rf -- "$work"
  mkdir -m 0700 "$work"
  expires_epoch="$GRANT_EXPIRES_EPOCH"
  now_epoch="$(date -u +%s)"
  (( expires_epoch - now_epoch >= 1200 )) || {
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

  existing_route_keys="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get configmap "$GATEWAY_CONFIGMAP" -o json \
    | jq -r --arg prefix "$GATEWAY_ROUTE_PREFIX" \
      '.data | keys[] | select(startswith($prefix))')"
  [[ -z "$existing_route_keys" ]] || {
    echo "protected-view-only-stage: gateway route index $GATEWAY_ROUTE_INDEX is not clean" >&2
    return 1
  }

  # The watchdog receives exactly ten minutes beyond grant expiry to execute
  # the pre-signed compensating rollback. Use the same captured clock sample as
  # the headroom check so the relative deadline cannot drift between reads.
  active_deadline="$(( expires_epoch - now_epoch + 600 ))"
  sed \
    -e "s/__EXPIRES_EPOCH__/${expires_epoch}/g" \
    -e "s/__ACTIVE_DEADLINE_SECONDS__/${active_deadline}/g" \
    -e "s/__AUTHORIZATION_SHA256__/${BUNDLE_SHA256}/g" \
    -e "s/__GATEWAY_ROUTE_PREFIX__/${GATEWAY_ROUTE_PREFIX}/g" \
    "$WATCHDOG_TEMPLATE" > "$work/watchdog.yaml"
  if grep -q '__[A-Z0-9_]*__' "$work/watchdog.yaml"; then
    echo "protected-view-only-stage: watchdog template is unresolved" >&2
    return 1
  fi
  # An existing Job is the rollback-ownership marker for an earlier apply.
  # Never replace it from a new authorization: doing so could strand the
  # earlier mutation without its compensating controller. The signed rollback
  # lane removes the marker only after it proves the full surface clean.
  local existing_watchdog
  existing_watchdog="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get job faz22-view-only-pilot-watchdog --ignore-not-found -o name)"
  [[ -z "$existing_watchdog" ]] || {
    echo "protected-view-only-stage: an earlier watchdog still owns rollback" >&2
    return 1
  }
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    apply --dry-run=server -f "$work/watchdog.yaml"
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" apply -f "$work/watchdog.yaml"
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    wait --for=condition=Ready pod \
    -l app.kubernetes.io/name=faz22-view-only-pilot-watchdog --timeout=120s
  verify_watchdog_active
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
  local route_patch route_filter_key
  route_filter_key="${GATEWAY_ROUTE_PREFIX}FILTERS_0"
  route_patch="$(jq -cn \
    --arg prefix "$GATEWAY_ROUTE_PREFIX" \
    --arg filter 'RewritePath=/api/v1/endpoint-admin/remote-access/sessions/(?<sid>[^/]+)/view, /internal/remote-bridge/operator/sessions/${sid}/view' '
      {data: {
        ($prefix + "ID"): "remote-bridge-viewer-route",
        ($prefix + "URI"): "http://endpoint-admin-remote-bridge-viewer:8096",
        ($prefix + "ORDER"): "-10",
        ($prefix + "PREDICATES_0"): "Path=/api/v1/endpoint-admin/remote-access/sessions/*/view",
        ($prefix + "PREDICATES_1"): "Method=GET,POST",
        ($prefix + "FILTERS_0"): $filter
      }}
    ')"
  jq -e --arg key "$route_filter_key" --arg token '${sid}' \
    '.data[$key] | contains($token)' <<<"$route_patch" >/dev/null
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
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get configmap "$GATEWAY_CONFIGMAP" -o json \
    | jq -e --arg key "${GATEWAY_ROUTE_PREFIX}ID" \
      '.data[$key] == "remote-bridge-viewer-route"' >/dev/null
  verify_watchdog_active
  trap - ERR
}

run_browser() {
  local hostname device_id actual_hash expires_epoch remaining runtime evidence source
  hostname="$(ssh -n -F /home/halil/.ssh/config -o BatchMode=yes \
    -o StrictHostKeyChecking=yes denetim-pc hostname \
    2>/dev/null)" || {
    echo "protected-view-only-stage: endpoint hostname query failed" >&2
    return 1
  }
  if [[ "$hostname" == *$'\n'* || "$hostname" == *$'\r'* \
    || ! "$hostname" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]{0,124}[A-Za-z0-9])?$ \
    || "$hostname" == *..* || "$hostname" == *.-* || "$hostname" == *-.* ]]; then
    echo "protected-view-only-stage: endpoint hostname is not one bounded DNS line" >&2
    return 1
  fi
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

  verify_watchdog_active
  expires_epoch="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" get job \
    faz22-view-only-pilot-watchdog \
    -o jsonpath='{.metadata.annotations.faz22\.6\.acik\.com/expires-at-epoch}')"
  [[ "$expires_epoch" =~ ^[1-9][0-9]{9}$ ]] || {
    echo "protected-view-only-stage: watchdog expiry annotation is invalid" >&2
    return 1
  }
  [[ "$expires_epoch" == "$GRANT_EXPIRES_EPOCH" ]] || {
    echo "protected-view-only-stage: watchdog expiry differs from signed grant" >&2
    return 1
  }
  remaining="$(( expires_epoch - $(date -u +%s) ))"
  (( remaining >= 900 )) || {
    echo "protected-view-only-stage: watchdog has insufficient browser headroom" >&2
    return 1
  }

  runtime="$RUNNER_TEMP/faz22-viewer-playwright"
  rm -rf -- "$runtime"
  python3 scripts/faz22-remote-ops/extract-cross-ai-browser-runtime.py \
    --archive "$BROWSER_RUNTIME_ARCHIVE" \
    --expected-sha256 "$RUNTIME_BUNDLE_SHA256" \
    --output-dir "$runtime"
  evidence="$RUNNER_TEMP/faz22-viewer-browser-collector"
  rm -rf -- "$evidence"
  mkdir -m 0700 "$evidence"
  export DEVICE_ID="$device_id" DEVICE_HOSTNAME="$hostname"
  export PILOT_SECONDS=300 PRODUCT_PILOT_SECONDS=300 CONSENT_WAIT_SECONDS=240
  export SOURCE_REVISION="$GITHUB_SHA"
  export BROWSER_EVIDENCE_SCRIPT="$CROSS_AI_SOURCE_ROOT/scripts/faz22-remote-ops/faz22-6-viewer-browser-evidence.mjs"
  export BROWSER_DIAGNOSTIC_OUTPUT="$evidence/browser-diagnostic.json"
  export PLAYWRIGHT_PACKAGE_ROOT="$runtime/browser-runtime"
  export PLAYWRIGHT_BROWSERS_PATH="$runtime/browser-runtime/ms-playwright"
  export VIEWER_PRODUCT_BASE_URL=https://testai.acik.com
  export REMOTE_BRIDGE_DEPLOYMENT="$BRIDGE_DEPLOYMENT" REQUIRE_ACTIVE_GUI=1
  # Keep the exact runner-owned SSH config path visible in this governed stage;
  # OpenSSH host-key checking remains enforced by that fixed config.
  export DENETIM_SSH_TARGET=denetim-pc
  export DENETIM_SSH_OPTS="-F /home/halil/.ssh/config -o StrictHostKeyChecking=yes"
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
  verify_watchdog_active
}

run_rollback() {
  rollback_surface
  set -e
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    rollout status "deploy/$BRIDGE_DEPLOYMENT" --timeout=300s
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    rollout status "deploy/$GATEWAY_DEPLOYMENT" --timeout=300s
  verify_rollback
  for resource in \
    "rolebinding/faz22-view-only-pilot-watchdog" \
    "role/faz22-view-only-pilot-watchdog" \
    "serviceaccount/faz22-view-only-pilot-watchdog" \
    "networkpolicy/allow-faz22-view-only-watchdog-kubernetes-api"; do
    kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
      delete "$resource" --ignore-not-found --wait=true
  done
  verify_rollback
  # The authorization-bearing Job is the retry ownership marker. Delete it
  # only after the full rollback surface and every other watchdog resource
  # have been removed and re-verified. A pre-delete crash remains retriable;
  # a post-delete crash can only occur after the surface is proven clean.
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    delete job/faz22-view-only-pilot-watchdog --ignore-not-found --wait=true
}

case "$STAGE" in
  apply) run_apply ;;
  browser-evidence) run_browser ;;
  compensating-rollback) run_rollback ;;
esac

echo "protected-view-only-stage: $STAGE verified"
