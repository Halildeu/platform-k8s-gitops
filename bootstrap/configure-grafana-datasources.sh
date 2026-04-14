#!/usr/bin/env bash
# Grafana'ya Loki + Tempo datasource ekler (sidecar ConfigMap ile otomatik discovery)
# kube-prometheus-stack Grafana sidecar:
#   labels: grafana_datasource=1
# ile işaretli ConfigMap'leri otomatik çeker ve provisioning'e yazar.

set -euo pipefail

ctx="k3d-prod"
log() { printf '\033[0;36m[grafana-ds]\033[0m %s\n' "$*" >&2; }

# Loki datasource
log "Loki ConfigMap (sidecar-watched)"
kubectl --context "${ctx}" -n monitoring apply -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: loki-datasource
  labels:
    grafana_datasource: "1"
data:
  loki-datasource.yaml: |-
    apiVersion: 1
    datasources:
      - name: Loki
        type: loki
        access: proxy
        url: http://loki.monitoring.svc.cluster.local:3100
        isDefault: false
        editable: false
        jsonData:
          maxLines: 1000
          derivedFields:
            - datasourceUid: tempo
              matcherRegex: "traceID=(\\w+)"
              name: TraceID
              url: "$${__value.raw}"
EOF

# Tempo datasource
log "Tempo ConfigMap (sidecar-watched)"
kubectl --context "${ctx}" -n monitoring apply -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: tempo-datasource
  labels:
    grafana_datasource: "1"
data:
  tempo-datasource.yaml: |-
    apiVersion: 1
    datasources:
      - name: Tempo
        type: tempo
        uid: tempo
        access: proxy
        url: http://tempo.monitoring.svc.cluster.local:3200
        isDefault: false
        editable: false
        jsonData:
          tracesToLogsV2:
            datasourceUid: loki
            spanStartTimeShift: "-1m"
            spanEndTimeShift: "1m"
            tags: ['pod', 'namespace', 'container']
            filterByTraceID: true
          tracesToMetrics:
            datasourceUid: prometheus
          nodeGraph:
            enabled: true
EOF

log "Grafana sidecar otomatik reload eder (~1 dk)"
log ""
log "Doğrulama:"
log "  curl -H Host:ai.acik.com http://127.0.0.1:30080/grafana/api/datasources -u admin:admin-change-me"
