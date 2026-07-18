#!/usr/bin/env bash
# One-run VIEW_ONLY surface controller for issue #2644.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
cd "$REPO_ROOT"

K8S_CONTEXT="${K8S_CONTEXT:-k3d-test}"
K8S_NAMESPACE="${K8S_NAMESPACE:-platform-test}"
BRIDGE_DEPLOYMENT="${BRIDGE_DEPLOYMENT:-endpoint-admin-remote-bridge-device-key}"
BRIDGE_CONFIGMAP="${BRIDGE_CONFIGMAP:-endpoint-admin-remote-bridge-config-device-key}"
GATEWAY_DEPLOYMENT="${GATEWAY_DEPLOYMENT:-api-gateway}"
GATEWAY_CONFIGMAP="${GATEWAY_CONFIGMAP:-api-gateway-config}"
GATEWAY_ROUTE_INDEX="${GATEWAY_ROUTE_INDEX:-28}"
GATEWAY_ROUTE_PREFIX="SPRING_CLOUD_GATEWAY_ROUTES_${GATEWAY_ROUTE_INDEX}_"
VIEWER_OVERLAY="${VIEWER_OVERLAY:-kustomize/overlays/test/activation/endpoint-admin-remote-bridge-viewer}"
BROKER_ONLY_OVERLAY="${BROKER_ONLY_OVERLAY:-kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key-live}"
TEST_ROOT_OVERLAY="${TEST_ROOT_OVERLAY:-kustomize/overlays/test}"
WATCHDOG_TEMPLATE="${WATCHDOG_TEMPLATE:-scripts/faz22-remote-ops/view-only-viewer-pilot-watchdog.template.yaml}"
WORK_DIR="${VIEW_ONLY_TRANSACTION_WORK_DIR:-${RUNNER_TEMP:-/tmp}/faz22-view-only-transaction}"
PREFLIGHT_DIR="${VIEW_ONLY_TRANSACTION_PREFLIGHT_DIR:-$WORK_DIR/preflight}"
WATCHDOG_CLEANUP_HEADROOM_SECONDS=900
WATCHDOG_ACTIVATION_DRIFT_BUDGET_SECONDS=300
WATCHDOG_RESOURCES=(
  job/faz22-view-only-pilot-watchdog
  rolebinding/faz22-view-only-pilot-watchdog
  role/faz22-view-only-pilot-watchdog
  serviceaccount/faz22-view-only-pilot-watchdog
  networkpolicy/allow-faz22-view-only-watchdog-kubernetes-api
)
STALE_WATCHDOG_FOUND=0
STALE_WATCHDOG_OWNER=""
STALE_WATCHDOG_RECLAIMED=0

reason_error() {
  local reason="$1"
  shift
  printf '::error title=%s::%s\n' "$reason" "$*" >&2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    reason_error missing-runtime-command "required command is unavailable: $1"
    return 2
  }
}

validate_mask_rect_bps() {
  local value="${DLP_MASK_RECT_BPS:-}" x y width height
  [[ "$value" =~ ^[0-9]{1,5},[0-9]{1,5},[0-9]{1,5},[0-9]{1,5}$ ]] || {
    reason_error invalid-mask-geometry "DLP mask must be canonical x,y,width,height basis points"
    return 2
  }
  IFS=',' read -r x y width height <<<"$value"
  x=$((10#$x)); y=$((10#$y)); width=$((10#$width)); height=$((10#$height))
  (( x <= 10000 && y <= 10000 && width > 0 && height > 0 \
     && x + width <= 10000 && y + height <= 10000 )) || {
    reason_error invalid-mask-geometry "DLP mask is empty or outside the primary monitor"
    return 2
  }
}

require_hash() {
  [[ "$1" =~ ^sha256:[a-f0-9]{64}$ ]] || {
    reason_error invalid-sha256 "$2 must be canonical sha256"
    return 2
  }
}

render_static_and_guard() {
  mkdir -p "$WORK_DIR"
  kubectl kustomize "$VIEWER_OVERLAY" > "$WORK_DIR/viewer.yaml"
  kubectl kustomize "$TEST_ROOT_OVERLAY" > "$WORK_DIR/test-root.yaml"
  grep -Fq 'name: endpoint-admin-remote-bridge-viewer' "$WORK_DIR/viewer.yaml"
  grep -Fq 'type: ClusterIP' "$WORK_DIR/viewer.yaml"
  grep -Fq 'REMOTE_BRIDGE_VIEWER_ENABLED: "true"' "$WORK_DIR/viewer.yaml"
  grep -Fq 'REMOTE_BRIDGE_VIEW_ONLY_ALLOWED_FRAME_CONTENT_TYPES: image/png' "$WORK_DIR/viewer.yaml"
  grep -Fq 'REMOTE_BRIDGE_BROKER_VIEW_ONLY_PERMIT_TTL_MILLIS: "600000"' "$WORK_DIR/viewer.yaml"
  if grep -Fq 'nodePort:' "$WORK_DIR/viewer.yaml"; then
    reason_error viewer-nodeport-forbidden "viewer surface must remain ClusterIP-only"
    return 1
  fi
  if grep -Fq 'endpoint-admin-remote-bridge-viewer' "$WORK_DIR/test-root.yaml"; then
    reason_error viewer-argo-root-leak "transient viewer overlay leaked into the test Argo root"
    return 1
  fi
}

render_and_guard() {
  render_static_and_guard || return
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    apply --dry-run=server -f "$WORK_DIR/viewer.yaml" >/dev/null
}

route_keys() {
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get configmap "$GATEWAY_CONFIGMAP" -o json \
    | jq -r --arg prefix "$GATEWAY_ROUTE_PREFIX" \
      '.data | keys[] | select(startswith($prefix))'
}

verify_surface_clean() {
  local resource
  for resource in \
    service/endpoint-admin-remote-bridge-viewer \
    networkpolicy/eab-bridge-viewer-allow-ingress-8096-from-api-gateway \
    networkpolicy/eab-api-gateway-allow-egress-8096-to-bridge-viewer; do
    if kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" get "$resource" >/dev/null 2>&1; then
      reason_error rollback-resource-remains "$resource remains after rollback"
      return 1
    fi
  done
  [[ -z "$(route_keys)" ]] || {
    reason_error rollback-route-remains "gateway viewer route keys remain"
    return 1
  }
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get configmap "$BRIDGE_CONFIGMAP" -o json \
    | jq -e '
        (.data | has("REMOTE_BRIDGE_VIEWER_ENABLED") | not)
        and (.data | has("REMOTE_BRIDGE_VIEW_ONLY_ALLOWED_FRAME_CONTENT_TYPES") | not)
        and (.data | has("REMOTE_BRIDGE_BROKER_VIEW_ONLY_PERMIT_TTL_MILLIS") | not)
      ' >/dev/null
}

verify_clean() {
  verify_surface_clean
  local resource
  for resource in "${WATCHDOG_RESOURCES[@]}"; do
    if kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" get "$resource" >/dev/null 2>&1; then
      reason_error rollback-watchdog-resource-remains "$resource remains after rollback"
      return 1
    fi
  done
}

verify_watchdog_ownership() {
  local mode="${1:-require-all}" resource object observed
  for resource in "${WATCHDOG_RESOURCES[@]}"; do
    object="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
      get "$resource" --ignore-not-found -o json)"
    if [[ -z "$object" ]]; then
      if [[ "$mode" == require-all ]]; then
        reason_error watchdog-resource-missing "$resource is missing"
        return 1
      fi
      continue
    fi
    observed="$(jq -r '.metadata.annotations["faz22.6.acik.com/authorization-sha256"] // empty' <<<"$object")"
    [[ "$observed" == "$AUTHORIZATION_SHA256" ]] || {
      reason_error rollback-ownership-mismatch "$resource belongs to a different authorization"
      return 1
    }
  done
}

delete_watchdog_resources() {
  local resource
  for resource in \
    rolebinding/faz22-view-only-pilot-watchdog \
    role/faz22-view-only-pilot-watchdog \
    serviceaccount/faz22-view-only-pilot-watchdog \
    networkpolicy/allow-faz22-view-only-watchdog-kubernetes-api \
    job/faz22-view-only-pilot-watchdog; do
    kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
      delete "$resource" --ignore-not-found --wait=true
  done
}

inspect_stale_watchdog() {
  local resource object observed owner="" job="" existing=0
  for resource in "${WATCHDOG_RESOURCES[@]}"; do
    object="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
      get "$resource" --ignore-not-found -o json)"
    [[ -n "$object" ]] || continue
    existing=1
    observed="$(jq -r '.metadata.annotations["faz22.6.acik.com/authorization-sha256"] // empty' <<<"$object")"
    require_hash "$observed" stale_watchdog_authorization
    if [[ -z "$owner" ]]; then
      owner="$observed"
    elif [[ "$owner" != "$observed" ]]; then
      reason_error stale-watchdog-ownership-diverged "watchdog resources have different authorization owners"
      return 1
    fi
    [[ "$resource" != job/* ]] || job="$object"
  done
  STALE_WATCHDOG_FOUND="$existing"
  STALE_WATCHDOG_OWNER="$owner"
  (( existing == 1 )) || return 0

  # Reclaim is allowed only after the safety controller has removed the viewer
  # surface. This prevents an abandoned runner from deleting an active owner.
  verify_surface_clean
  if [[ -n "$job" ]]; then
    jq -e '
      ((.status.active // 0) == 0)
      and (
        ((.status.succeeded // 0) >= 1)
        or ((.status.failed // 0) >= 1)
        or any(.status.conditions[]?; .status == "True" and (.type == "Complete" or .type == "Failed"))
      )
    ' <<<"$job" >/dev/null || {
      reason_error prior-watchdog-active "an earlier watchdog is not terminal"
      return 1
    }
  fi

  AUTHORIZATION_SHA256="$owner" verify_watchdog_ownership allow-missing
}

reclaim_stale_watchdog() {
  inspect_stale_watchdog || return
  (( STALE_WATCHDOG_FOUND == 1 )) || return 0
  AUTHORIZATION_SHA256="$STALE_WATCHDOG_OWNER" verify_watchdog_ownership allow-missing
  verify_surface_clean
  delete_watchdog_resources
  verify_clean
  STALE_WATCHDOG_RECLAIMED=1
  printf 'stale-watchdog-reclaimed authorization=%s\n' "$STALE_WATCHDOG_OWNER"
}

cleanup_owned_watchdog() {
  : "${AUTHORIZATION_SHA256:?AUTHORIZATION_SHA256 is required}"
  require_hash "$AUTHORIZATION_SHA256" AUTHORIZATION_SHA256
  verify_surface_clean
  verify_watchdog_ownership allow-missing
  delete_watchdog_resources
  verify_clean
}

retire_watchdog_after_clean_surface() {
  local resource object observed owner="" existing=0
  verify_surface_clean
  for resource in "${WATCHDOG_RESOURCES[@]}"; do
    object="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
      get "$resource" --ignore-not-found -o json)"
    [[ -n "$object" ]] || continue
    existing=1
    observed="$(jq -r '.metadata.annotations["faz22.6.acik.com/authorization-sha256"] // empty' <<<"$object")"
    require_hash "$observed" retiring_watchdog_authorization
    if [[ -z "$owner" ]]; then
      owner="$observed"
    elif [[ "$owner" != "$observed" ]]; then
      reason_error retiring-watchdog-ownership-diverged "watchdog resources have different authorization owners"
      return 1
    fi
  done
  if (( existing == 0 )); then
    verify_clean
    return
  fi
  AUTHORIZATION_SHA256="$owner" verify_watchdog_ownership allow-missing
  delete_watchdog_resources
  verify_clean
}

verify_watchdog() {
  : "${AUTHORIZATION_SHA256:?AUTHORIZATION_SHA256 is required}"
  : "${WATCHDOG_EXPIRES_EPOCH:?WATCHDOG_EXPIRES_EPOCH is required}"
  require_hash "$AUTHORIZATION_SHA256" AUTHORIZATION_SHA256
  [[ "$WATCHDOG_EXPIRES_EPOCH" =~ ^[1-9][0-9]{9,12}$ ]] || {
    reason_error invalid-watchdog-expiry "watchdog expiry must be an epoch"
    return 2
  }
  local job
  job="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get job faz22-view-only-pilot-watchdog -o json)"
  jq -e --arg authorization "$AUTHORIZATION_SHA256" --arg expiry "$WATCHDOG_EXPIRES_EPOCH" '
    .metadata.annotations["faz22.6.acik.com/authorization-sha256"] == $authorization
    and .metadata.annotations["faz22.6.acik.com/expires-at-epoch"] == $expiry
    and ((.status.active // 0) == 1)
    and ((.status.failed // 0) == 0)
    and ((.status.succeeded // 0) == 0)
  ' <<<"$job" >/dev/null
  verify_watchdog_ownership require-all
}

preflight() {
  : "${DEVICE_ID:?DEVICE_ID is required}"
  : "${DEVICE_HOSTNAME:?DEVICE_HOSTNAME is required}"
  : "${SOURCE_REVISION:?SOURCE_REVISION is required}"
  : "${PILOT_SECONDS:?PILOT_SECONDS is required}"
  : "${DLP_MASK_RECT_BPS:?DLP_MASK_RECT_BPS is required}"
  [[ "$SOURCE_REVISION" =~ ^[a-f0-9]{40}$ ]] || return 2
  [[ "$DEVICE_ID" =~ ^[0-9a-fA-F-]{36}$ ]] || return 2
  [[ "$DEVICE_HOSTNAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{1,126}$ ]] || return 2
  case "$PILOT_SECONDS" in 300|600|900|1200|1800) ;; *) return 2 ;; esac
  validate_mask_rect_bps || return
  for command in bash date jq kubectl python3 sha256sum; do
    require_command "$command"
  done
  [[ "${KUBECONFIG:-}" == "/dev/null" ]] || {
    reason_error unprotected-preflight-kubeconfig "static preflight must not receive a kubeconfig"
    return 1
  }
  [[ -z "${SSH_AUTH_SOCK:-}" ]] || {
    reason_error unprotected-preflight-ssh-agent "static preflight must not receive an SSH agent"
    return 1
  }
  render_static_and_guard || return

  # shellcheck source=scripts/governance/lib-remote-bridge-digest.sh disable=SC1091
  source scripts/governance/lib-remote-bridge-digest.sh
  local expected_ref expected_digest
  expected_ref="$(rbd_expected_digest)" || {
    reason_error expected-digest-unavailable "remote bridge digest SSOT could not be rendered"
    return 1
  }
  expected_digest="${expected_ref##*@}"
  rm -rf -- "$PREFLIGHT_DIR"
  install -d -m 0700 "$PREFLIGHT_DIR"
  local endpoint_hash hostname_hash policy_hash mask_hash manifest
  endpoint_hash="sha256:$(printf '%s' "$DEVICE_ID" | sha256sum | awk '{print $1}')"
  hostname_hash="sha256:$(printf '%s' "${DEVICE_HOSTNAME,,}" | sha256sum | awk '{print $1}')"
  policy_hash="sha256:$(sha256sum config/faz22-6-view-only-pilot-owner-policy.v1.json | awk '{print $1}')"
  mask_hash="sha256:$(printf '%s' "$DLP_MASK_RECT_BPS" | sha256sum | awk '{print $1}')"
  manifest="$PREFLIGHT_DIR/preflight.json"
  jq -S -n \
    --arg repository "${GITHUB_REPOSITORY:-Halildeu/platform-k8s-gitops}" \
    --arg workflowRef "${GITHUB_WORKFLOW_REF:-local}" \
    --arg headSha "$SOURCE_REVISION" \
    --argjson runId "${GITHUB_RUN_ID:-1}" \
    --argjson runAttempt "${GITHUB_RUN_ATTEMPT:-1}" \
    --arg endpointIdSha256 "$endpoint_hash" \
    --arg deviceHostnameSha256 "$hostname_hash" \
    --arg policySha256 "$policy_hash" \
    --arg maskPolicySha256 "$mask_hash" \
    --arg expectedImageDigest "$expected_digest" \
    --argjson pilotSeconds "$PILOT_SECONDS" \
    --arg observedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
      {
        schemaVersion:"faz22.6.viewOnlyTransactionPreflight.v1",
        repository:$repository,
        workflowRef:$workflowRef,
        headSha:$headSha,
        runId:$runId,
        runAttempt:$runAttempt,
        endpointIdSha256:$endpointIdSha256,
        deviceHostnameSha256:$deviceHostnameSha256,
        policySha256:$policySha256,
        maskPolicySha256:$maskPolicySha256,
        expectedImageDigest:$expectedImageDigest,
        pilotSeconds:$pilotSeconds,
        observedAt:$observedAt,
        capabilityClass:"github-hosted-unprivileged-static",
        liveChecksDeferredToProtectedJob:true,
        mutationCount:0,
        attendedConsentAttempted:false,
        staleWatchdogReclaimRequired:null,
        staleWatchdogAuthorizationSha256:null,
        verdict:"PASS"
      }
    ' > "$manifest"
  (cd "$PREFLIGHT_DIR" && sha256sum preflight.json > SHA256SUMS && sha256sum -c SHA256SUMS)
  printf 'sha256:%s\n' "$(sha256sum "$manifest" | awk '{print $1}')"
}

revalidate() {
  : "${DEVICE_ID:?DEVICE_ID is required}"
  : "${DEVICE_HOSTNAME:?DEVICE_HOSTNAME is required}"
  : "${SOURCE_REVISION:?SOURCE_REVISION is required}"
  : "${PILOT_SECONDS:?PILOT_SECONDS is required}"
  : "${DLP_MASK_RECT_BPS:?DLP_MASK_RECT_BPS is required}"
  : "${EXPECTED_PREFLIGHT_SHA256:?EXPECTED_PREFLIGHT_SHA256 is required}"
  require_hash "$EXPECTED_PREFLIGHT_SHA256" EXPECTED_PREFLIGHT_SHA256
  local manifest="$PREFLIGHT_DIR/preflight.json"
  [[ -s "$manifest" && ! -L "$manifest" ]] || {
    reason_error preflight-manifest-missing "downloaded preflight manifest is unavailable"
    return 1
  }
  local actual endpoint_hash hostname_hash policy_hash mask_hash expected_ref expected_digest pods_json
  actual="sha256:$(sha256sum "$manifest" | awk '{print $1}')"
  [[ "$actual" == "$EXPECTED_PREFLIGHT_SHA256" ]] || {
    reason_error preflight-digest-mismatch "downloaded preflight digest changed before activation"
    return 1
  }
  endpoint_hash="sha256:$(printf '%s' "$DEVICE_ID" | sha256sum | awk '{print $1}')"
  hostname_hash="sha256:$(printf '%s' "${DEVICE_HOSTNAME,,}" | sha256sum | awk '{print $1}')"
  policy_hash="sha256:$(sha256sum config/faz22-6-view-only-pilot-owner-policy.v1.json | awk '{print $1}')"
  mask_hash="sha256:$(printf '%s' "$DLP_MASK_RECT_BPS" | sha256sum | awk '{print $1}')"
  jq -e \
    --arg repository "${GITHUB_REPOSITORY:-Halildeu/platform-k8s-gitops}" \
    --arg workflowRef "${GITHUB_WORKFLOW_REF:-local}" \
    --arg headSha "$SOURCE_REVISION" \
    --arg endpoint "$endpoint_hash" --arg hostname "$hostname_hash" \
    --arg policy "$policy_hash" --arg mask "$mask_hash" \
    --argjson pilotSeconds "$PILOT_SECONDS" '
      .repository == $repository and .workflowRef == $workflowRef and .headSha == $headSha
      and .endpointIdSha256 == $endpoint and .deviceHostnameSha256 == $hostname
      and .policySha256 == $policy and .maskPolicySha256 == $mask
      and .pilotSeconds == $pilotSeconds and .mutationCount == 0
      and .capabilityClass == "github-hosted-unprivileged-static"
      and .liveChecksDeferredToProtectedJob == true
      and .attendedConsentAttempted == false and .verdict == "PASS"
    ' "$manifest" >/dev/null

  reclaim_stale_watchdog || return
  verify_clean || return
  render_and_guard || return
  bash scripts/faz22-remote-ops/reconcile-viewer-audit-db-role.sh check || return
  DENETIM_SSH_TARGET=denetim-pc DENETIM_SSH_CONFIG=/home/halil/.ssh/config \
    bash scripts/faz22-remote-ops/verify-view-only-viewer-target.sh || return

  # shellcheck source=scripts/governance/lib-remote-bridge-digest.sh disable=SC1091
  source scripts/governance/lib-remote-bridge-digest.sh
  expected_ref="$(rbd_expected_digest)" || {
    reason_error expected-digest-unavailable "remote bridge digest SSOT could not be rendered"
    return 1
  }
  expected_digest="${expected_ref##*@}"
  [[ "$(jq -r .expectedImageDigest "$manifest")" == "$expected_digest" ]] || {
    reason_error preflight-image-digest-stale "rendered immutable digest changed while approval was pending"
    return 1
  }
  pods_json="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get pods -l "app.kubernetes.io/name=${BRIDGE_DEPLOYMENT}" -o json)"
  jq -e --arg digest "$expected_digest" '
    [.items[] | select(
      .metadata.deletionTimestamp == null and .status.phase == "Running"
      and any(.status.containerStatuses[]?; .ready == true and (.imageID | contains($digest)))
    )] | length >= 1
  ' <<<"$pods_json" >/dev/null || {
    reason_error live-image-digest-mismatch "broker pod imageID changed while approval was pending"
    return 1
  }
  jq -S -n --arg preflightSha256 "$EXPECTED_PREFLIGHT_SHA256" \
    --arg headSha "$SOURCE_REVISION" --arg expectedImageDigest "$expected_digest" \
    --argjson staleWatchdogReclaimed "$STALE_WATCHDOG_RECLAIMED" \
    --arg observedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
      {
        schemaVersion:"faz22.6.viewOnlyTransactionLiveRevalidation.v1",
        preflightSha256:$preflightSha256,
        headSha:$headSha,
        expectedImageDigest:$expectedImageDigest,
        observedAt:$observedAt,
        staleWatchdogReclaimed:($staleWatchdogReclaimed == 1),
        viewerSurfaceClean:true,
        endpointTrustRevalidated:true,
        auditRoleRevalidated:true,
        verdict:"PASS"
      }
    ' > "$WORK_DIR/live-revalidation.json"
}

activate() {
  : "${AUTHORIZATION_SHA256:?AUTHORIZATION_SHA256 is required}"
  : "${WATCHDOG_EXPIRES_EPOCH:?WATCHDOG_EXPIRES_EPOCH is required}"
  : "${PILOT_SECONDS:?PILOT_SECONDS is required}"
  require_hash "$AUTHORIZATION_SHA256" AUTHORIZATION_SHA256
  [[ "$WATCHDOG_EXPIRES_EPOCH" =~ ^[1-9][0-9]{9,12}$ ]] || return 2
  local now required active_deadline route_patch existing_watchdog
  now="$(date -u +%s)"
  required="$(( PILOT_SECONDS + WATCHDOG_CLEANUP_HEADROOM_SECONDS - WATCHDOG_ACTIVATION_DRIFT_BUDGET_SECONDS ))"
  (( WATCHDOG_EXPIRES_EPOCH - now >= required )) || {
    reason_error watchdog-headroom-insufficient "watchdog deadline cannot cover the pilot and cleanup budget"
    return 1
  }
  verify_clean
  render_and_guard
  existing_watchdog="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get job faz22-view-only-pilot-watchdog --ignore-not-found -o name)"
  [[ -z "$existing_watchdog" ]] || {
    reason_error prior-watchdog-active "an earlier transaction still owns rollback"
    return 1
  }
  active_deadline="$(( WATCHDOG_EXPIRES_EPOCH - now + 600 ))"
  sed \
    -e "s/__EXPIRES_EPOCH__/${WATCHDOG_EXPIRES_EPOCH}/g" \
    -e "s/__ACTIVE_DEADLINE_SECONDS__/${active_deadline}/g" \
    -e "s/__AUTHORIZATION_SHA256__/${AUTHORIZATION_SHA256}/g" \
    -e "s/__GATEWAY_ROUTE_PREFIX__/${GATEWAY_ROUTE_PREFIX}/g" \
    "$WATCHDOG_TEMPLATE" > "$WORK_DIR/watchdog.yaml"
  if grep -Eq '__[A-Z0-9_]+__' "$WORK_DIR/watchdog.yaml"; then
    reason_error watchdog-template-unresolved "watchdog template contains an unresolved placeholder"
    return 1
  fi
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    apply --dry-run=server -f "$WORK_DIR/watchdog.yaml" >/dev/null
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" apply -f "$WORK_DIR/watchdog.yaml" >/dev/null
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    wait --for=condition=Ready pod -l app.kubernetes.io/name=faz22-view-only-pilot-watchdog --timeout=120s
  verify_watchdog
  VIEWER_AUDIT_DB_ROLE_CONFIRM=RECONCILE_FAZ22_6_VIEWER_AUDIT_DB_ROLE \
    bash scripts/faz22-remote-ops/reconcile-viewer-audit-db-role.sh apply
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" apply -f "$WORK_DIR/viewer.yaml" >/dev/null
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout restart "deploy/$BRIDGE_DEPLOYMENT"
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout status "deploy/$BRIDGE_DEPLOYMENT" --timeout=300s
  route_patch="$(jq -cn --arg prefix "$GATEWAY_ROUTE_PREFIX" \
    --arg filter 'RewritePath=/api/v1/endpoint-admin/remote-access/sessions/(?<sid>[^/]+)/view, /internal/remote-bridge/operator/sessions/${sid}/view' '
      {data:{
        ($prefix+"ID"):"remote-bridge-viewer-route",
        ($prefix+"URI"):"http://endpoint-admin-remote-bridge-viewer:8096",
        ($prefix+"ORDER"):"-10",
        ($prefix+"PREDICATES_0"):"Path=/api/v1/endpoint-admin/remote-access/sessions/*/view",
        ($prefix+"PREDICATES_1"):"Method=GET,POST",
        ($prefix+"FILTERS_0"):$filter
      }}
    ')"
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" patch configmap \
    "$GATEWAY_CONFIGMAP" --type merge -p "$route_patch" >/dev/null
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout restart "deploy/$GATEWAY_DEPLOYMENT"
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout status "deploy/$GATEWAY_DEPLOYMENT" --timeout=300s
  [[ "$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get service endpoint-admin-remote-bridge-viewer -o jsonpath='{.spec.type}')" == "ClusterIP" ]]
  [[ -z "$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get service endpoint-admin-remote-bridge-viewer -o jsonpath='{.spec.ports[*].nodePort}')" ]]
  verify_watchdog
}

rollback() {
  : "${AUTHORIZATION_SHA256:?AUTHORIZATION_SHA256 is required}"
  require_hash "$AUTHORIZATION_SHA256" AUTHORIZATION_SHA256
  local live_authorization status=0
  live_authorization="$(kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    get job faz22-view-only-pilot-watchdog --ignore-not-found \
    -o jsonpath='{.metadata.annotations.faz22\.6\.acik\.com/authorization-sha256}')"
  if [[ -z "$live_authorization" ]]; then
    verify_watchdog_ownership allow-missing
    delete_watchdog_resources
    verify_clean
    return
  fi
  [[ "$live_authorization" == "$AUTHORIZATION_SHA256" ]] || {
    reason_error rollback-ownership-mismatch "watchdog belongs to a different authorization"
    return 1
  }
  verify_watchdog_ownership allow-missing
  GATEWAY_ROUTE_INDEX="$GATEWAY_ROUTE_INDEX" \
    bash scripts/faz22-remote-ops/rollback-view-only-viewer-pilot-config.sh || status=1
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" delete \
    service endpoint-admin-remote-bridge-viewer --ignore-not-found || status=1
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" delete networkpolicy \
    eab-bridge-viewer-allow-ingress-8096-from-api-gateway \
    eab-api-gateway-allow-egress-8096-to-bridge-viewer --ignore-not-found || status=1
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" apply -k "$BROKER_ONLY_OVERLAY" || status=1
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout restart \
    "deploy/$BRIDGE_DEPLOYMENT" "deploy/$GATEWAY_DEPLOYMENT" || status=1
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout status \
    "deploy/$BRIDGE_DEPLOYMENT" --timeout=300s || status=1
  kubectl --context="$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout status \
    "deploy/$GATEWAY_DEPLOYMENT" --timeout=300s || status=1
  (( status == 0 )) || return "$status"
  verify_surface_clean
  delete_watchdog_resources
  verify_clean
}

cleanup_local() {
  : "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
  : "${GITHUB_RUN_ATTEMPT:?GITHUB_RUN_ATTEMPT is required}"
  [[ "$GITHUB_RUN_ID" =~ ^[1-9][0-9]*$ ]] || return 2
  [[ "$GITHUB_RUN_ATTEMPT" =~ ^[1-9][0-9]*$ ]] || return 2
  local expected="/tmp/faz22-view-only-transaction-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
  [[ "$WORK_DIR" == "$expected" ]] || {
    reason_error cleanup-path-mismatch "refusing to clean an unexpected transaction directory"
    return 1
  }
  [[ ! -L "$WORK_DIR" ]] || {
    reason_error cleanup-symlink-forbidden "transaction directory must not be a symlink"
    return 1
  }
  [[ -e "$WORK_DIR" ]] || return 0
  find "$WORK_DIR" -xdev -type f -exec chmod u+w {} +
  if command -v shred >/dev/null 2>&1; then
    find "$WORK_DIR" -xdev -type f -exec shred -u -- {} +
  else
    find "$WORK_DIR" -xdev -type f -exec rm -f {} +
  fi
  find "$WORK_DIR" -xdev -depth -mindepth 1 -delete
  rmdir "$WORK_DIR"
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

case "${1:-}" in
  preflight) preflight ;;
  revalidate) revalidate ;;
  activate) activate ;;
  verify-watchdog) verify_watchdog ;;
  reclaim-stale) reclaim_stale_watchdog ;;
  cleanup-owned-watchdog) cleanup_owned_watchdog ;;
  retire-watchdog-after-clean-surface) retire_watchdog_after_clean_surface ;;
  rollback) rollback ;;
  verify-clean) verify_clean ;;
  cleanup-local) cleanup_local ;;
  *)
    echo "usage: $0 {preflight|revalidate|activate|verify-watchdog|reclaim-stale|cleanup-owned-watchdog|retire-watchdog-after-clean-surface|rollback|verify-clean|cleanup-local}" >&2
    exit 2
    ;;
esac
