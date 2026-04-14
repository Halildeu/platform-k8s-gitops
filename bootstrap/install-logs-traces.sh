#!/usr/bin/env bash
# Loki + Promtail + Tempo kurulum (prod cluster, monitoring ns)
# Grafana datasource'lara Loki/Tempo eklenmesi ayrı adım (ConfigMap).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() { printf '\033[0;36m[logs-traces]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[0;31m[logs-traces]\033[0m %s\n' "$*" >&2; exit 1; }

command -v helm >/dev/null || err "helm yok"

ctx="k3d-prod"
kubectl --context "${ctx}" cluster-info >/dev/null 2>&1 || err "k3d-prod yok"

# Grafana repo (loki + promtail + tempo aynı repoda)
if ! helm repo list 2>/dev/null | grep -q "^grafana"; then
  helm repo add grafana https://grafana.github.io/helm-charts
fi
helm repo update grafana >/dev/null

log "namespace monitoring"
kubectl --context "${ctx}" create namespace monitoring --dry-run=client -o yaml \
  | kubectl --context "${ctx}" apply -f -

# ─── Loki ───
log "Loki kuruluyor (SingleBinary, 7d retention)"
helm --kube-context "${ctx}" upgrade --install loki grafana/loki \
  --namespace monitoring \
  --version "${LOKI_VERSION:-6.18.0}" \
  -f "${REPO_ROOT}/helm-values/loki/values.yaml" \
  --wait --timeout 5m

# ─── Promtail ───
log "Promtail kuruluyor (DaemonSet)"
helm --kube-context "${ctx}" upgrade --install promtail grafana/promtail \
  --namespace monitoring \
  --version "${PROMTAIL_VERSION:-6.16.6}" \
  -f "${REPO_ROOT}/helm-values/promtail/values.yaml" \
  --wait --timeout 3m

# ─── Tempo ───
log "Tempo kuruluyor (single binary, 48h retention)"
helm --kube-context "${ctx}" upgrade --install tempo grafana/tempo \
  --namespace monitoring \
  --version "${TEMPO_VERSION:-1.12.0}" \
  -f "${REPO_ROOT}/helm-values/tempo/values.yaml" \
  --wait --timeout 3m

log "kurulum tamam"
kubectl --context "${ctx}" -n monitoring get pods | grep -E "loki|promtail|tempo"

log ""
log "Grafana datasource'lara ekleme (ConfigMap sidecar ile otomatik):"
log "  bootstrap/configure-grafana-datasources.sh"
log ""
log "Hızlı test:"
log "  Loki: kubectl --context k3d-prod -n monitoring port-forward svc/loki 3100:3100"
log "  Tempo: kubectl --context k3d-prod -n monitoring port-forward svc/tempo 3200:3200"
