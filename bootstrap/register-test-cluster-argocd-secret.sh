#!/usr/bin/env bash
# Register k3d-test in the prod ArgoCD hub without the argocd CLI.
#
# This script is intentionally fail-closed:
# - default mode is read-only preview;
# - APPLY=1 is required for Docker/Kubernetes mutations;
# - bearer token material is never printed.

set -euo pipefail

log() { printf '[argocd-test-cluster-secret] %s\n' "$*" >&2; }
die() { printf '[argocd-test-cluster-secret] ERROR: %s\n' "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

APPLY="${APPLY:-0}"
ROLLBACK="${ROLLBACK:-0}"

PROD_CTX="${PROD_CTX:-k3d-prod}"
TEST_CTX="${TEST_CTX:-k3d-test}"
ARGOCD_NS="${ARGOCD_NS:-argocd}"
CLUSTER_NAME="${CLUSTER_NAME:-test-cluster}"

PROD_NET="${PROD_NET:-platform-prod-net}"
TEST_NET="${TEST_NET:-platform-test-net}"
BRIDGE_CONTAINER="${BRIDGE_CONTAINER:-platform-argocd-test-api-bridge}"
BRIDGE_PORT="${BRIDGE_PORT:-6443}"
TARGET_HOST="${TARGET_HOST:-k3d-test-serverlb}"
TARGET_PORT="${TARGET_PORT:-6443}"
TLS_SERVER_NAME="${TLS_SERVER_NAME:-k3d-test-serverlb}"

SA_NAMESPACE="${SA_NAMESPACE:-kube-system}"
SA_NAME="${SA_NAME:-argocd-manager}"
SA_TOKEN_SECRET="${SA_TOKEN_SECRET:-argocd-manager-token}"
CRB_NAME="${CRB_NAME:-argocd-manager-role-binding}"

for cmd in docker jq kubectl openssl; do
  need "$cmd"
done

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/argocd-test-cluster.XXXXXX")"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

kubectl --context "$PROD_CTX" cluster-info >/dev/null 2>&1 || die "cannot reach prod context: $PROD_CTX"
kubectl --context "$TEST_CTX" cluster-info >/dev/null 2>&1 || die "cannot reach test context: $TEST_CTX"

secret_name="cluster-${CLUSTER_NAME}"

rollback() {
  log "rollback: deleting ArgoCD cluster secret ${ARGOCD_NS}/${secret_name}"
  kubectl --context "$PROD_CTX" -n "$ARGOCD_NS" delete secret "$secret_name" --ignore-not-found

  log "rollback: removing Docker bridge container ${BRIDGE_CONTAINER}"
  docker rm -f "$BRIDGE_CONTAINER" >/dev/null 2>&1 || true

  if [[ "${ROLLBACK_TEST_RBAC:-0}" == "1" ]]; then
    log "rollback: deleting test cluster RBAC (${CRB_NAME}, ${SA_NAMESPACE}/${SA_NAME}, ${SA_TOKEN_SECRET})"
    kubectl --context "$TEST_CTX" delete clusterrolebinding "$CRB_NAME" --ignore-not-found
    kubectl --context "$TEST_CTX" -n "$SA_NAMESPACE" delete secret "$SA_TOKEN_SECRET" --ignore-not-found
    kubectl --context "$TEST_CTX" -n "$SA_NAMESPACE" delete sa "$SA_NAME" --ignore-not-found
  fi
}

if [[ "$ROLLBACK" == "1" ]]; then
  [[ "$APPLY" == "1" ]] || die "ROLLBACK=1 requires APPLY=1"
  rollback
  exit 0
fi

log "mode: APPLY=${APPLY} (set APPLY=1 to mutate)"
log "prod context: ${PROD_CTX}; test context: ${TEST_CTX}; ArgoCD namespace: ${ARGOCD_NS}"
log "cluster name: ${CLUSTER_NAME}; bridge: ${BRIDGE_CONTAINER} (${PROD_NET}<->${TEST_NET})"

if [[ "$APPLY" != "1" ]]; then
  log "preview only. Planned actions:"
  log "1. Create/recreate Docker bridge container ${BRIDGE_CONTAINER} without published ports."
  log "2. Connect it to ${PROD_NET} and ${TEST_NET}; forward :${BRIDGE_PORT} -> ${TARGET_HOST}:${TARGET_PORT}."
  log "3. Create ${SA_NAMESPACE}/${SA_NAME} and ${CRB_NAME} in ${TEST_CTX}."
  log "4. Create ${ARGOCD_NS}/${secret_name} in ${PROD_CTX} with serverName=${TLS_SERVER_NAME}."
  log "5. Verify ArgoCD Application platform-test no longer fails with destination-not-registered."
  exit 0
fi

log "creating internal-only Docker bridge container"
docker rm -f "$BRIDGE_CONTAINER" >/dev/null 2>&1 || true
docker create \
  --name "$BRIDGE_CONTAINER" \
  --restart unless-stopped \
  --network "$PROD_NET" \
  alpine/socat:latest \
  -d -d "TCP-LISTEN:${BRIDGE_PORT},fork,reuseaddr" "TCP:${TARGET_HOST}:${TARGET_PORT}" >/dev/null
docker network connect "$TEST_NET" "$BRIDGE_CONTAINER"
docker start "$BRIDGE_CONTAINER" >/dev/null

bridge_ip="$(docker inspect "$BRIDGE_CONTAINER" \
  --format "{{with index .NetworkSettings.Networks \"${PROD_NET}\"}}{{.IPAddress}}{{end}}")"
[[ -n "$bridge_ip" ]] || die "cannot determine bridge IP on ${PROD_NET}"
log "bridge running on ${PROD_NET}: ${bridge_ip}:${BRIDGE_PORT}"

log "checking bridge TLS reachability without logging credentials"
tls_out="${tmp_dir}/s_client.out"
tls_err="${tmp_dir}/s_client.err"
cert_txt="${tmp_dir}/cert.txt"
if ! echo | openssl s_client -connect "${bridge_ip}:${BRIDGE_PORT}" -servername "$TLS_SERVER_NAME" >"$tls_out" 2>"$tls_err"; then
  tail -40 "$tls_err" >&2 || true
  die "TLS probe failed through bridge"
fi
openssl x509 -in <(awk '/BEGIN CERTIFICATE/{p=1} p{print} /END CERTIFICATE/{p=0}' "$tls_out" | head -100) \
  -noout -subject -ext subjectAltName >"$cert_txt"
if ! grep -q "DNS:${TLS_SERVER_NAME}" "$cert_txt"; then
  cat "$cert_txt" >&2
  die "target API certificate does not contain DNS:${TLS_SERVER_NAME}"
fi

log "creating test cluster ArgoCD manager service account and binding"
kubectl --context "$TEST_CTX" -n "$SA_NAMESPACE" create serviceaccount "$SA_NAME" \
  --dry-run=client -o yaml | kubectl --context "$TEST_CTX" apply -f -
kubectl --context "$TEST_CTX" create clusterrolebinding "$CRB_NAME" \
  --clusterrole=cluster-admin \
  "--serviceaccount=${SA_NAMESPACE}:${SA_NAME}" \
  --dry-run=client -o yaml | kubectl --context "$TEST_CTX" apply -f -

log "ensuring long-lived service-account token secret exists"
cat <<EOF | kubectl --context "$TEST_CTX" apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: ${SA_TOKEN_SECRET}
  namespace: ${SA_NAMESPACE}
  annotations:
    kubernetes.io/service-account.name: ${SA_NAME}
type: kubernetes.io/service-account-token
EOF

for _ in $(seq 1 30); do
  token_b64="$(kubectl --context "$TEST_CTX" -n "$SA_NAMESPACE" get secret "$SA_TOKEN_SECRET" -o jsonpath='{.data.token}' 2>/dev/null || true)"
  ca_b64="$(kubectl --context "$TEST_CTX" -n "$SA_NAMESPACE" get secret "$SA_TOKEN_SECRET" -o jsonpath='{.data.ca\.crt}' 2>/dev/null || true)"
  if [[ -n "$token_b64" && -n "$ca_b64" ]]; then
    break
  fi
  sleep 1
done
[[ -n "${token_b64:-}" ]] || die "service-account token was not populated"
[[ -n "${ca_b64:-}" ]] || die "service-account CA was not populated"

token="$(printf '%s' "$token_b64" | base64 -d)"
ca_data="$ca_b64"

config_json="$(printf '%s\n' "$token" | jq -Rcn \
  --arg ca "$ca_data" \
  --arg serverName "$TLS_SERVER_NAME" \
  'input as $token | {bearerToken:$token,tlsClientConfig:{insecure:false,caData:$ca,serverName:$serverName}}')"

log "writing ArgoCD cluster secret (token redacted)"
secret_manifest="${tmp_dir}/cluster-secret.yaml"
cat >"$secret_manifest" <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${secret_name}
  namespace: ${ARGOCD_NS}
  labels:
    argocd.argoproj.io/secret-type: cluster
type: Opaque
stringData:
  name: "${CLUSTER_NAME}"
  server: "https://${bridge_ip}:${BRIDGE_PORT}"
  config: |
    ${config_json}
EOF
chmod 600 "$secret_manifest"
kubectl --context "$PROD_CTX" apply -f "$secret_manifest"

log "cluster secret written: ${ARGOCD_NS}/${secret_name}"
log "server=https://${bridge_ip}:${BRIDGE_PORT} tlsServerName=${TLS_SERVER_NAME}"

log "waiting for platform-test Application to leave destination-not-registered"
sleep 10
kubectl --context "$PROD_CTX" -n "$ARGOCD_NS" get application platform-test \
  -o jsonpath='sync={.status.sync.status} health={.status.health.status}{"\n"}'
kubectl --context "$PROD_CTX" -n "$ARGOCD_NS" get application platform-test \
  -o jsonpath='{range .status.conditions[*]}{.type}{": "}{.message}{"\n"}{end}' || true
