#!/usr/bin/env bash
# Loki + Promtail + Tempo kurulum (prod / test cluster, monitoring ns)
# Grafana datasource'lara Loki/Tempo eklenmesi ayrı adım (ConfigMap).
#
# Faz 23.2 PR-D.2 (Codex 019dfe0f Q1 absorb): cluster parametresi kabul eder.
# - Test cluster: sadece Tempo (test traces nice-to-have; Loki/Promtail prod-only).
# - Prod cluster: full stack (Loki + Promtail + Tempo).
#
# Kullanım:
#   bash bootstrap/install-logs-traces.sh           # prod default
#   bash bootstrap/install-logs-traces.sh prod      # explicit prod
#   bash bootstrap/install-logs-traces.sh test      # test cluster — sadece Tempo

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() { printf '\033[0;36m[logs-traces]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[0;31m[logs-traces]\033[0m %s\n' "$*" >&2; exit 1; }

command -v helm >/dev/null || err "helm yok"

# Cluster parameter (Codex 019dfe0f Q1 absorb)
cluster_arg="${1:-prod}"
case "${cluster_arg}" in
  prod|production)
    ctx="k3d-prod"
    install_loki_promtail=1
    tempo_values="${REPO_ROOT}/helm-values/tempo/values.yaml"
    ;;
  test|staging)
    ctx="k3d-test"
    install_loki_promtail=0
    tempo_values="${REPO_ROOT}/helm-values/tempo/values-test.yaml"
    ;;
  *)
    err "geçersiz cluster: ${cluster_arg} (kabul: prod | test)"
    ;;
esac

kubectl --context "${ctx}" cluster-info >/dev/null 2>&1 || err "${ctx} yok"
log "cluster: ${ctx}"

# Grafana repo (loki + promtail + tempo aynı repoda)
if ! helm repo list 2>/dev/null | grep -q "^grafana"; then
  helm repo add grafana https://grafana.github.io/helm-charts
fi
helm repo update grafana >/dev/null

log "namespace monitoring"
kubectl --context "${ctx}" create namespace monitoring --dry-run=client -o yaml \
  | kubectl --context "${ctx}" apply -f -

# ─── Loki + Promtail (prod only) ───
if [ "${install_loki_promtail}" -eq 1 ]; then
  log "Loki kuruluyor (SingleBinary, 7d retention)"
  helm --kube-context "${ctx}" upgrade --install loki grafana/loki \
    --namespace monitoring \
    --version "${LOKI_VERSION:-6.18.0}" \
    -f "${REPO_ROOT}/helm-values/loki/values.yaml" \
    --wait --timeout 5m

  log "Promtail kuruluyor (DaemonSet)"
  helm --kube-context "${ctx}" upgrade --install promtail grafana/promtail \
    --namespace monitoring \
    --version "${PROMTAIL_VERSION:-6.16.6}" \
    -f "${REPO_ROOT}/helm-values/promtail/values.yaml" \
    --wait --timeout 3m
fi

# ─── Tempo (her iki cluster) ───
log "Tempo kuruluyor (values: ${tempo_values})"
helm --kube-context "${ctx}" upgrade --install tempo grafana/tempo \
  --namespace monitoring \
  --version "${TEMPO_VERSION:-1.12.0}" \
  -f "${tempo_values}" \
  --wait --timeout 3m

log "kurulum tamam"
kubectl --context "${ctx}" -n monitoring get pods | grep -E "loki|promtail|tempo" || true

log ""
log "Hızlı test:"
log "  Tempo health: kubectl --context ${ctx} -n monitoring port-forward svc/tempo 3200:3200"
log "  curl -sf http://127.0.0.1:3200/ready"
log "  Search: curl -G 'http://127.0.0.1:3200/api/search' --data-urlencode 'tags=service.name=notification-orchestrator'"
if [ "${install_loki_promtail}" -eq 1 ]; then
  log "  Loki: kubectl --context ${ctx} -n monitoring port-forward svc/loki 3100:3100"
  log "  Grafana datasource'lara ekleme: bootstrap/configure-grafana-datasources.sh"
fi
