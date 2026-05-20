#!/usr/bin/env bash
# Monitoring stack kurulum — ADR-0002 §3.8:
#   prod: full kube-prometheus-stack (Prom + Grafana + Alertmanager + node-exporter)
#   test: lightweight Prom + node-exporter + kube-state-metrics + remote_write prod
# Usage: bash bootstrap/install-monitoring.sh <prod|test>

set -euo pipefail

ENV="${1:-prod}"
if [[ "${ENV}" != "prod" && "${ENV}" != "test" ]]; then
  printf 'ERROR: Usage: %s <prod|test>\n' "$0" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() { printf '\033[0;36m[monitoring-%s]\033[0m %s\n' "${ENV}" "$*" >&2; }
err() { printf '\033[0;31m[monitoring-%s]\033[0m %s\n' "${ENV}" "$*" >&2; exit 1; }

command -v helm >/dev/null || err "helm yok"

ctx="k3d-${ENV}"
kubectl --context "${ctx}" cluster-info >/dev/null 2>&1 || err "${ctx} yok"

# Repo ekle
if ! helm repo list 2>/dev/null | grep -q "^prometheus-community"; then
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
fi
helm repo update prometheus-community >/dev/null

log "namespace monitoring"
kubectl --context "${ctx}" create namespace monitoring --dry-run=client -o yaml \
  | kubectl --context "${ctx}" apply -f -

# D26 admin hardening (SADECE prod — test'te Grafana yok)
if [[ "${ENV}" == "prod" ]]; then
  if ! kubectl --context "${ctx}" -n monitoring get secret grafana-admin-credentials >/dev/null 2>&1; then
    log "Grafana admin Secret (rastgele password) oluşturuluyor"
    ADMIN_PASS="$(openssl rand -base64 24 | tr -d '\n')"
    kubectl --context "${ctx}" -n monitoring create secret generic grafana-admin-credentials \
      --from-literal=admin-user=admin \
      --from-literal=admin-password="${ADMIN_PASS}"
    log "Admin password Secret'ta. Almak için:"
    log "  kubectl --context ${ctx} -n monitoring get secret grafana-admin-credentials -o jsonpath='{.data.admin-password}' | base64 -d"
  fi
fi

values_file="${REPO_ROOT}/helm-values/kube-prometheus-stack/values-${ENV}.yaml"
if [[ ! -f "${values_file}" ]]; then
  err "values dosyası yok: ${values_file}"
fi

# R16 PR1 kill-switch (Codex 019e4448) — KPS_REMOTE_WRITE_DISABLED=1 layers
# a second -f values override that empties prometheus.prometheusSpec.remoteWrite.
# Only `test` ships an outbound remoteWrite stream today, so the override is
# only meaningful (and only ships a file) on the test side.
killswitch_args=()
if [[ "${KPS_REMOTE_WRITE_DISABLED:-0}" == "1" ]]; then
  killswitch_file="${REPO_ROOT}/helm-values/kube-prometheus-stack/values-${ENV}-no-remote-write.yaml"
  if [[ -f "${killswitch_file}" ]]; then
    log "R16 KILL-SWITCH ACTIVE — layering ${killswitch_file##*/}"
    killswitch_args=(-f "${killswitch_file}")
  else
    log "R16 KILL-SWITCH requested but ${killswitch_file##*/} not present — skipping (${ENV} has no outbound remote_write to disable)"
  fi
fi

log "helm upgrade --install kube-prometheus-stack (${ENV}, chart 65.x)"
helm --kube-context "${ctx}" upgrade --install kube-prometheus-stack \
  prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --version "${KPS_VERSION:-65.8.0}" \
  -f "${values_file}" \
  "${killswitch_args[@]}" \
  --wait --timeout 10m

log "kurulum tamam"
kubectl --context "${ctx}" -n monitoring get pods

log ""
log "Erişim:"
if [[ "${ENV}" == "prod" ]]; then
  log "  Grafana:    http://ai.acik.com/grafana"
  log "              Kullanıcı: admin · Şifre:"
  log "              kubectl --context ${ctx} -n monitoring get secret grafana-admin-credentials -o jsonpath='{.data.admin-password}' | base64 -d"
  log "  Prometheus: http://ai.acik.com/prometheus"
  log "  Alertmanager: kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093"
else
  log "  Test cluster minimal stack (ADR-0002 §3.8):"
  log "  - Grafana/Alertmanager: YOK (prod-hub centralize)"
  log "  - Prometheus (lokal buffer): kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090"
  log "  - Remote write target: prod Prometheus (values-test.yaml remoteWrite.url)"
  log ""
  log "  Metric flow: test-prom scrape → remote_write → prod-prom (cluster=test label)"
fi
