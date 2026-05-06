#!/usr/bin/env bash
# Prometheus Adapter kurulum (Faz 23.2 PR-D.4 — custom metric → external.metrics.k8s.io API).
# notification-orchestrator HPA notify_queue_pending_intents external metric'i için zorunlu.
#
# Kullanım:
#   bash bootstrap/install-prometheus-adapter.sh           # prod default
#   bash bootstrap/install-prometheus-adapter.sh test      # k3d-test cluster
#
# Ön-koşul:
#   - kube-prometheus-stack monitoring namespace'inde aktif
#   - Prometheus svc: kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() { printf '\033[0;36m[prom-adapter]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[0;31m[prom-adapter]\033[0m %s\n' "$*" >&2; exit 1; }

command -v helm >/dev/null || err "helm yok"

cluster_arg="${1:-prod}"
case "${cluster_arg}" in
  prod|production) ctx="k3d-prod" ;;
  test|staging)    ctx="k3d-test" ;;
  *) err "geçersiz cluster: ${cluster_arg} (kabul: prod | test)" ;;
esac

kubectl --context "${ctx}" cluster-info >/dev/null 2>&1 || err "${ctx} yok"
log "cluster: ${ctx}"

# Verify kube-prometheus-stack Prometheus var
if ! kubectl --context "${ctx}" -n monitoring get svc kube-prometheus-stack-prometheus >/dev/null 2>&1; then
  err "kube-prometheus-stack Prometheus svc bulunamadı; önce install-monitoring.sh çalıştır"
fi

# prometheus-community helm repo
if ! helm repo list 2>/dev/null | grep -q "^prometheus-community"; then
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
fi
helm repo update prometheus-community >/dev/null

log "Prometheus Adapter kuruluyor"
helm --kube-context "${ctx}" upgrade --install prometheus-adapter \
  prometheus-community/prometheus-adapter \
  --namespace monitoring \
  --version "${PROMETHEUS_ADAPTER_VERSION:-4.10.0}" \
  -f "${REPO_ROOT}/helm-values/prometheus-adapter/values.yaml" \
  --wait --timeout 3m

log "kurulum tamam"

log ""
log "Verification:"
log "  APIService: kubectl --context ${ctx} get apiservice v1beta1.external.metrics.k8s.io"
log "  External metric query (test cluster):"
log "    kubectl --context ${ctx} get --raw \\"
log "      '/apis/external.metrics.k8s.io/v1beta1/namespaces/platform-${cluster_arg}/notify_queue_pending_intents'"
log ""
log "HPA custom metric kullanımı:"
log "  notification-orchestrator/hpa.yaml zaten External metric tanımlı."
log "  Adapter aktif olunca HPA scaleTarget custom metric'i okur."
