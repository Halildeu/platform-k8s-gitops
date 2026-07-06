#!/usr/bin/env bash
set -euo pipefail

CONTEXT="${KUBE_CONTEXT:-k3d-test}"
NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
REMOTE_BRIDGE_NAME="${REMOTE_BRIDGE_NAME:-endpoint-admin-remote-bridge}"
PRIMARY_NAME="${PRIMARY_NAME:-endpoint-admin-service}"
OVERLAY="${REMOTE_BRIDGE_OVERLAY:-kustomize/overlays/test/activation/endpoint-admin-remote-bridge}"
REMOTE_BRIDGE_TOPOLOGY="${REMOTE_BRIDGE_TOPOLOGY:-outbound-only}"

failures=0
not_ready=0

section() {
  printf '\n=== %s ===\n' "$1"
}

pass() {
  printf 'PASS %s\n' "$1"
}

warn() {
  not_ready=$((not_ready + 1))
  printf 'NOT_READY %s\n' "$1"
}

fail() {
  failures=$((failures + 1))
  printf 'FAIL %s\n' "$1"
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "missing command: $1"
  fi
}

kubectl_jsonpath() {
  kubectl --context "$CONTEXT" -n "$NAMESPACE" "$@" 2>/dev/null || true
}

section "tooling"
need_cmd kubectl
if command -v jq >/dev/null 2>&1; then
  pass "jq available"
else
  warn "jq missing; using jsonpath-only checks"
fi

section "context"
if kubectl config get-contexts -o name 2>/dev/null | grep -Fxq "$CONTEXT"; then
  pass "kubectl context exists: $CONTEXT"
else
  fail "kubectl context missing: $CONTEXT"
fi

if kubectl --context "$CONTEXT" get ns "$NAMESPACE" >/dev/null 2>&1; then
  pass "namespace exists: $NAMESPACE"
else
  fail "namespace missing: $NAMESPACE"
fi

section "desired-state render"
if [[ -d "$OVERLAY" ]]; then
  if kubectl kustomize "$OVERLAY" >/tmp/remote-ops-activation-render.yaml; then
    pass "activation overlay renders: $OVERLAY ($(wc -l </tmp/remote-ops-activation-render.yaml | tr -d ' ') lines)"
  else
    fail "activation overlay render failed: $OVERLAY"
  fi

  if grep -Rqs 'sha256:0000000000000000000000000000000000000000000000000000000000000000' "$OVERLAY"; then
    warn "activation overlay still has zero digest placeholder"
  else
    pass "activation overlay has no zero digest placeholder"
  fi

  if grep -RqsE '192\.0\.2\.0/24|198\.51\.100\.|203\.0\.113\.' "$OVERLAY"; then
    warn "activation overlay still has RFC5737 placeholder CIDRs"
  else
    pass "activation overlay has no RFC5737 placeholder CIDRs"
  fi

  case "$REMOTE_BRIDGE_TOPOLOGY" in
    outbound-only)
      if grep -Rqs 'eab-bridge-allow-egress-pilot-devices' "$OVERLAY"; then
        fail "outbound-only topology selected but broker-to-device pilot egress policy is present"
      else
        pass "outbound-only topology has no broker-to-device pilot egress policy"
      fi
      ;;
    broker-to-device-pilot)
      if grep -Rqs 'eab-bridge-allow-egress-pilot-devices' "$OVERLAY"; then
        pass "broker-to-device pilot topology declares pilot egress policy"
      else
        warn "broker-to-device pilot topology selected but pilot egress policy is absent"
      fi
      ;;
    *)
      fail "unknown REMOTE_BRIDGE_TOPOLOGY: $REMOTE_BRIDGE_TOPOLOGY"
      ;;
  esac

  if grep -Rqs 'kv/platform/endpoint-admin-remote-bridge' "$OVERLAY"; then
    pass "activation overlay references dedicated remote-bridge Vault path"
  else
    fail "activation overlay does not reference dedicated remote-bridge Vault path"
  fi

  for property in \
    broker_db_username \
    broker_db_password \
    openfga_store_id \
    openfga_model_id \
    recording_anchor_signing_key \
    broker_tls_cert_chain_pem \
    broker_tls_private_key_pem \
    device_ca_pem \
    device_crl_pem \
    attestation_public_key_pem \
    operator_step_up_public_key_pem \
    permit_signing_key_pem; do
    if grep -Rqs "$property" "$OVERLAY"; then
      pass "activation overlay expects Vault property: $property"
    else
      fail "activation overlay missing expected Vault property reference: $property"
    fi
  done

  if grep -Rqs 'nodePort: 31944' "$OVERLAY" && grep -Rqs 'targetPort: bridge' "$OVERLAY"; then
    pass "activation service exposes only bridge nodePort shape"
  else
    fail "activation service bridge nodePort shape missing"
  fi

  for env_name in \
    REMOTE_BRIDGE_PERMIT_KID \
    REMOTE_BRIDGE_RECORDING_ANCHOR_KEY_PATH \
    REMOTE_BRIDGE_PEER_EVIDENCE_PARSER \
    REMOTE_BRIDGE_DEVICE_TRUST_VERIFIER \
    REMOTE_BRIDGE_OWNER_GRANT_GATE_TYPE \
    REMOTE_BRIDGE_DURESS_SOURCE_TYPE \
    REMOTE_BRIDGE_DURESS_PILOT_RISK_ACCEPTED \
    REMOTE_BRIDGE_STEP_UP_VERIFIER \
    REMOTE_BRIDGE_OPERATOR_AUTH_TYPE \
    REMOTE_BRIDGE_OPERATOR_REST_ENABLED \
    REMOTE_BRIDGE_APPROVAL_REST_ENABLED \
    ENDPOINT_ADMIN_REMOTE_ACCESS_CERT_TRUST_EVALUATOR \
    ENDPOINT_ADMIN_REMOTE_ACCESS_CERT_TRUST_REVOCATION_MODE \
    ENDPOINT_ADMIN_REMOTE_ACCESS_ATTESTATION_VERIFIER; do
    if grep -Rqs "$env_name" "$OVERLAY"; then
      pass "activation overlay declares runtime env: $env_name"
    else
      fail "activation overlay missing runtime env: $env_name"
    fi
  done
else
  warn "activation overlay path not present on this host: $OVERLAY"
fi

section "primary service bridge state"
if kubectl --context "$CONTEXT" -n "$NAMESPACE" get deploy "$PRIMARY_NAME" >/dev/null 2>&1; then
  pass "primary deployment exists: $PRIMARY_NAME"
  primary_image="$(kubectl_jsonpath get deploy "$PRIMARY_NAME" -o jsonpath='{.spec.template.spec.containers[0].image}')"
  printf 'INFO primary_image=%s\n' "${primary_image:-unknown}"

  primary_bridge_env="$(kubectl_jsonpath get deploy "$PRIMARY_NAME" -o jsonpath='{range .spec.template.spec.containers[0].env[*]}{.name}={.value}{"\n"}{end}' | grep -E 'REMOTE.*BRIDGE|BRIDGE.*ENABLED' || true)"
  if printf '%s\n' "$primary_bridge_env" | grep -Eq '=true$|=TRUE$|=1$'; then
    fail "primary deployment appears to enable remote bridge: ${primary_bridge_env//$'\n'/; }"
  else
    pass "primary deployment has no enabled remote-bridge env"
    if [[ -n "$primary_bridge_env" ]]; then
      printf 'INFO primary_bridge_env=%s\n' "${primary_bridge_env//$'\n'/; }"
    fi
  fi
else
  fail "primary deployment missing: $PRIMARY_NAME"
fi

section "remote bridge live objects"
if kubectl --context "$CONTEXT" -n "$NAMESPACE" get deploy "$REMOTE_BRIDGE_NAME" >/dev/null 2>&1; then
  pass "remote bridge deployment exists: $REMOTE_BRIDGE_NAME"
  rb_image="$(kubectl_jsonpath get deploy "$REMOTE_BRIDGE_NAME" -o jsonpath='{.spec.template.spec.containers[0].image}')"
  rb_replicas="$(kubectl_jsonpath get deploy "$REMOTE_BRIDGE_NAME" -o jsonpath='{.spec.replicas}')"
  rb_ready="$(kubectl_jsonpath get deploy "$REMOTE_BRIDGE_NAME" -o jsonpath='{.status.readyReplicas}')"
  rb_available="$(kubectl_jsonpath get deploy "$REMOTE_BRIDGE_NAME" -o jsonpath='{.status.availableReplicas}')"
  printf 'INFO remote_bridge_image=%s replicas=%s ready=%s available=%s\n' \
    "${rb_image:-unknown}" "${rb_replicas:-unknown}" "${rb_ready:-0}" "${rb_available:-0}"
  if [[ "${rb_replicas:-0}" == "${rb_ready:-0}" && "${rb_replicas:-0}" == "${rb_available:-0}" ]]; then
    pass "remote bridge deployment is available"
  else
    warn "remote bridge deployment is not fully available"
  fi

  rb_pods="$(kubectl_jsonpath get pod -l "app.kubernetes.io/name=$REMOTE_BRIDGE_NAME" -o jsonpath='{range .items[*]}{.metadata.name}{"|"}{range .status.containerStatuses[*]}{.ready}{","}{.restartCount}{","}{.imageID}{";"}{end}{"\n"}{end}')"
  if [[ -n "$rb_pods" ]]; then
    while IFS='|' read -r pod_name status_line; do
      [[ -z "$pod_name" ]] && continue
      printf 'INFO remote_bridge_pod=%s status=%s\n' "$pod_name" "$status_line"
      if ! printf '%s' "$status_line" | grep -q '^true,'; then
        warn "remote bridge pod is not ready: $pod_name"
      fi
    done <<<"$rb_pods"
  else
    warn "remote bridge has no matching pods"
  fi

  if [[ "$rb_image" =~ @sha256:([0-9a-f]{64}) ]]; then
    expected_digest="${BASH_REMATCH[1]}"
    if printf '%s\n' "$rb_pods" | grep -q "$expected_digest"; then
      pass "remote bridge pod imageID matches pinned digest"
    else
      warn "remote bridge pod imageID does not show pinned digest: sha256:$expected_digest"
    fi
  else
    warn "remote bridge deployment image is not digest-pinned"
  fi
else
  warn "remote bridge deployment not live: $REMOTE_BRIDGE_NAME"
fi

if kubectl --context "$CONTEXT" -n "$NAMESPACE" get svc "$REMOTE_BRIDGE_NAME" >/dev/null 2>&1; then
  pass "remote bridge service exists: $REMOTE_BRIDGE_NAME"
  kubectl --context "$CONTEXT" -n "$NAMESPACE" get svc "$REMOTE_BRIDGE_NAME" -o jsonpath='{range .spec.ports[*]}{.name}:{.port}:{.targetPort}:{.nodePort}{"\n"}{end}' |
    sed 's/^/INFO remote_bridge_service_port=/'
else
  warn "remote bridge service not live: $REMOTE_BRIDGE_NAME"
fi

section "remote bridge secret and policy names"
for name in \
  endpoint-admin-remote-bridge-secrets \
  endpoint-admin-remote-bridge-tls \
  endpoint-admin-remote-bridge-signer; do
  if kubectl --context "$CONTEXT" -n "$NAMESPACE" get externalsecret "$name" >/dev/null 2>&1; then
    condition="$(kubectl_jsonpath get externalsecret "$name" -o jsonpath='{range .status.conditions[?(@.type=="Ready")]}{.status}:{.reason}{end}')"
    if [[ "$condition" == True:* ]]; then
      pass "ExternalSecret Ready: $name ($condition)"
    else
      warn "ExternalSecret not Ready: $name (${condition:-no Ready condition})"
    fi
  else
    warn "ExternalSecret missing by name: $name"
  fi
done

for name in \
  endpoint-admin-remote-bridge-secrets \
  endpoint-admin-remote-bridge-tls \
  endpoint-admin-remote-bridge-signer; do
  if kubectl --context "$CONTEXT" -n "$NAMESPACE" get secret "$name" >/dev/null 2>&1; then
    pass "secret exists by name: $name"
  else
    warn "secret missing by name: $name"
  fi
done

if kubectl --context "$CONTEXT" -n "$NAMESPACE" get netpol 2>/dev/null | grep -q "$REMOTE_BRIDGE_NAME"; then
  pass "remote bridge network policies exist"
  kubectl --context "$CONTEXT" -n "$NAMESPACE" get netpol | grep "$REMOTE_BRIDGE_NAME" | sed 's/^/INFO netpol=/'
else
  warn "remote bridge network policies not live"
fi

section "final"
if (( failures > 0 )); then
  printf 'PRECHECK_STATUS=fail failures=%s not_ready=%s\n' "$failures" "$not_ready"
  exit 1
fi

if (( not_ready > 0 )); then
  printf 'PRECHECK_STATUS=not-ready failures=0 not_ready=%s\n' "$not_ready"
  exit 2
fi

printf 'PRECHECK_STATUS=ready failures=0 not_ready=0\n'
