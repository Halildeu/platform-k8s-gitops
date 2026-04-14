#!/usr/bin/env bash
# Monitoring stack kurulum (sadece prod cluster — D10, D16)
# Bileşenler: kube-prometheus-stack (Prom+Grafana+Alertmanager+node-exporter)
# Sonra ayrı script'lerle: loki, tempo

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() { printf '\033[0;36m[monitoring]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[0;31m[monitoring]\033[0m %s\n' "$*" >&2; exit 1; }

command -v helm >/dev/null || err "helm yok"

ctx="k3d-prod"
kubectl --context "${ctx}" cluster-info >/dev/null 2>&1 || err "k3d-prod yok"

# Repo ekle
if ! helm repo list 2>/dev/null | grep -q "^prometheus-community"; then
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
fi
helm repo update prometheus-community >/dev/null

log "namespace monitoring"
kubectl --context "${ctx}" create namespace monitoring --dry-run=client -o yaml \
  | kubectl --context "${ctx}" apply -f -

# D26 admin hardening: Grafana admin Secret'ını rastgele üret (ilk kurulumda).
# Halihazırda varsa dokunma (rotation bilerek manuel).
if ! kubectl --context "${ctx}" -n monitoring get secret grafana-admin-credentials >/dev/null 2>&1; then
  log "Grafana admin Secret (rastgele password) oluşturuluyor"
  ADMIN_PASS="$(openssl rand -base64 24 | tr -d '\n')"
  kubectl --context "${ctx}" -n monitoring create secret generic grafana-admin-credentials \
    --from-literal=admin-user=admin \
    --from-literal=admin-password="${ADMIN_PASS}"
  log "Admin password Secret'ta. Almak için:"
  log "  kubectl --context ${ctx} -n monitoring get secret grafana-admin-credentials -o jsonpath='{.data.admin-password}' | base64 -d"
fi

log "helm upgrade --install kube-prometheus-stack (chart 65.x)"
helm --kube-context "${ctx}" upgrade --install kube-prometheus-stack \
  prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --version "${KPS_VERSION:-65.8.0}" \
  -f "${REPO_ROOT}/helm-values/kube-prometheus-stack/values.yaml" \
  --wait --timeout 10m

log "kurulum tamam"
kubectl --context "${ctx}" -n monitoring get pods

log ""
log "Erişim:"
log "  Grafana:    http://ai.acik.com/grafana"
log "              Kullanıcı: admin · Şifre:"
log "              kubectl --context ${ctx} -n monitoring get secret grafana-admin-credentials -o jsonpath='{.data.admin-password}' | base64 -d"
log "  Prometheus: http://ai.acik.com/prometheus"
log "  Alertmanager: kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093"
