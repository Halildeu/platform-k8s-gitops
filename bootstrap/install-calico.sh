#!/usr/bin/env bash
# Her iki cluster'a Calico CNI kurar (tigera-operator).
# Flannel kapalı olduğu için k3s'te CNI yok — bu script olmadan pod'lar Pending kalır.
#
# Kullanım:
#   ./bootstrap/install-calico.sh           # her iki cluster
#   ./bootstrap/install-calico.sh prod
#   ./bootstrap/install-calico.sh test

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '\033[0;36m[calico]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[0;31m[calico]\033[0m %s\n' "$*" >&2; exit 1; }

# Calico sürümü — k3s v1.31 ile uyumlu
CALICO_VERSION="${CALICO_VERSION:-v3.29.1}"
OPERATOR_URL="https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/tigera-operator.yaml"

install_calico() {
  local cluster="$1"
  local ctx="k3d-${cluster}"
  local pod_cidr

  case "${cluster}" in
    prod) pod_cidr="10.42.0.0/16" ;;
    test) pod_cidr="10.44.0.0/16" ;;
    *) err "bilinmeyen cluster: ${cluster}" ;;
  esac

  kubectl --context "${ctx}" cluster-info >/dev/null 2>&1 \
    || err "context '${ctx}' bulunamadı — önce setup-clusters.sh çalıştır"

  log "[${cluster}] tigera-operator uygulanıyor (${CALICO_VERSION})"
  kubectl --context "${ctx}" apply --server-side -f "${OPERATOR_URL}"

  log "[${cluster}] tigera-operator hazırlanıyor..."
  kubectl --context "${ctx}" -n tigera-operator wait --for=condition=available \
    --timeout=120s deployment/tigera-operator

  log "[${cluster}] Installation CR apply — podCIDR=${pod_cidr}"
  # Typha test cluster'da kapalı (tek node için gereksiz ~150 MB tasarruf)
  local typha_replicas=1
  [[ "${cluster}" == "test" ]] && typha_replicas=0

  cat <<EOF | kubectl --context "${ctx}" apply -f -
apiVersion: operator.tigera.io/v1
kind: Installation
metadata:
  name: default
spec:
  calicoNetwork:
    ipPools:
      - blockSize: 26
        cidr: ${pod_cidr}
        encapsulation: VXLAN
        natOutgoing: Enabled
        nodeSelector: all()
  typhaDeployment:
    spec:
      template:
        spec:
          containers:
            - name: calico-typha
              resources:
                requests: { cpu: 50m, memory: 50Mi }
                limits:   { memory: 150Mi }
---
apiVersion: operator.tigera.io/v1
kind: APIServer
metadata:
  name: default
spec: {}
EOF

  # Test cluster'da Typha'yı 0'a çek (tasarruf)
  if [[ "${cluster}" == "test" ]]; then
    log "[${cluster}] Typha replica=0 (test için)"
    kubectl --context "${ctx}" -n calico-system scale deployment calico-typha --replicas=0 \
      2>/dev/null || true
  fi

  log "[${cluster}] Calico pod'ları bekleniyor (max 3 dk)..."
  kubectl --context "${ctx}" -n calico-system wait --for=condition=ready pod \
    -l k8s-app=calico-node --timeout=180s || {
    log "[${cluster}] uyarı: Calico node'ları hazır olmadı; kubectl ile incele"
  }

  log "[${cluster}] CNI hazır ✓"
}

TARGETS="${1:-both}"
case "${TARGETS}" in
  prod) install_calico prod ;;
  test) install_calico test ;;
  both|"") install_calico prod; install_calico test ;;
  *) err "bilinmeyen hedef: ${TARGETS}" ;;
esac

log "sıradaki adım: bootstrap/install-ingress.sh  (ingress-nginx her iki cluster'a)"
