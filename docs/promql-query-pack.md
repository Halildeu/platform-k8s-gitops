# PromQL Query Pack — S3 Stability Soak & Ops Daily

> **Source:** K8s-6 S3-A monitoring stack + günlük ops troubleshoot
> **Kullanım:** Grafana Explore, Prometheus UI, ya da `curl -G <prom-url>/api/v1/query --data-urlencode 'query=...'`
> **Hedef ortam:** prod cluster merkezi Prometheus (kube-prometheus-stack)

---

## 1. Authz Plane (Zanzibar Hub + OpenFGA)

### 1.1 Hub availability (sustained)

```promql
# Son 1h'de Hub up yüzde
avg_over_time(up{job="permission-service"}[1h]) * 100
# Beklenen: 100% (SLO 99.9%+)
```

### 1.2 Hub request rate by endpoint

```promql
sum(rate(http_server_requests_seconds_count{application="permission-service"}[5m]))
  by (uri)
# Günlük bazda /authz/* endpoint'leri RPS dağılımı
```

### 1.3 Hub p95 latency by endpoint

```promql
histogram_quantile(0.95,
  sum by (le, uri)
    (rate(http_server_requests_seconds_bucket{application="permission-service"}[5m]))
)
# Beklenen: /authz/check < 100ms, /authz/list < 500ms (SLO)
```

### 1.4 Hub error rate (5xx)

```promql
sum(rate(http_server_requests_seconds_count{application="permission-service",status=~"5.."}[5m]))
  / sum(rate(http_server_requests_seconds_count{application="permission-service"}[5m]))
# Beklenen: < 0.1% sustained
```

### 1.5 OpenFGA engine check latency

```promql
histogram_quantile(0.95,
  sum by (le) (rate(openfga_check_duration_seconds_bucket[5m]))
)
# Beklenen: p95 < 50ms (cache hit)
```

---

## 2. Platform Pods (8 backend + OpenFGA + frontend)

### 2.1 Pod restart rate (15m)

```promql
sum by (pod, namespace) (
  increase(kube_pod_container_status_restarts_total{namespace=~"platform-(test|prod)"}[15m])
)
# Beklenen: 0 unexpected restarts
```

### 2.2 Pod Not Ready duration

```promql
max by (pod, namespace) (
  (time() - kube_pod_status_ready_time{condition="true", namespace=~"platform-(test|prod)"})
)
# Beklenen: sürekli 0 veya Ready=true timestamp güncel
```

### 2.3 Memory pressure by pod (RSS / limit)

```promql
sum by (pod, namespace) (container_memory_working_set_bytes{namespace=~"platform-(test|prod)",container!="POD"})
  / sum by (pod, namespace) (container_spec_memory_limit_bytes{namespace=~"platform-(test|prod)",container!="POD"})
# Beklenen: < 0.8 (80%) — threshold 90% warn
```

### 2.4 CPU throttling

```promql
sum by (pod, namespace) (rate(container_cpu_cfs_throttled_periods_total{namespace=~"platform-(test|prod)"}[5m]))
  / sum by (pod, namespace) (rate(container_cpu_cfs_periods_total{namespace=~"platform-(test|prod)"}[5m]))
# Beklenen: < 0.05 (5%) — yüksek ise CPU limit arttır (D22)
```

### 2.5 JVM heap usage (Spring Boot)

```promql
sum by (pod, area) (jvm_memory_used_bytes{area="heap"})
  / sum by (pod, area) (jvm_memory_max_bytes{area="heap"})
# Beklenen: < 0.75 (75%) steady state
```

### 2.6 JVM GC pause p95

```promql
histogram_quantile(0.95,
  sum by (le, pod) (rate(jvm_gc_pause_seconds_bucket[5m]))
)
# Beklenen: < 100ms (G1GC MaxGCPauseMillis target)
```

---

## 3. Edge + Gateway (authoritative entrypoint)

### 3.1 Edge 5xx ratio (prod ingress-nginx)

```promql
sum(rate(nginx_ingress_controller_requests{ingress="platform",status=~"5.."}[5m]))
  / sum(rate(nginx_ingress_controller_requests{ingress="platform"}[5m]))
# Beklenen: < 0.5% (1% → rollback trigger D30)
```

### 3.2 Gateway p95 latency (prod)

```promql
histogram_quantile(0.95,
  sum by (le) (rate(http_server_requests_seconds_bucket{application="api-gateway"}[5m]))
)
# Beklenen: < 1s (2s → warn trigger)
```

### 3.3 Gateway request rate by route

```promql
sum by (uri) (rate(http_server_requests_seconds_count{application="api-gateway"}[5m]))
# Route dağılımı — /variants + /users + /auth/* top 5
```

### 3.4 External edge synthetic probe success

```promql
# 4 probe (testai-deny/health + prod-deny/health) son 5dk başarı oranı
avg_over_time(probe_success{job=~"blackbox-(testai|prod)-(deny|health)"}[5m]) * 100
# Beklenen: 100% (3× peş peşe fail → ZanzibarEdgeSyntheticFail alert)
```

### 3.5 Probe duration trend

```promql
histogram_quantile(0.95,
  sum by (le, job) (rate(probe_duration_seconds_bucket[5m]))
)
# Beklenen: < 2s (timeout 10s)
```

---

## 4. Database + Infrastructure

### 4.1 PG connection pool utilization (Hikari)

```promql
hikaricp_connections_active{job=~"permission-service|auth-service|user-service|variant-service|core-data-service|report-service|schema-service"}
  / hikaricp_connections_max{job=~"permission-service|auth-service|user-service|variant-service|core-data-service|report-service|schema-service"}
# Beklenen: < 0.7 (70%) — bağlantı havuzu doluyorsa scale
```

### 4.2 Hikari connection timeout (spike detection)

```promql
rate(hikaricp_connections_timeout_total[5m])
# Beklenen: 0/s sustained (timeout spike → pool exhaustion veya DB slow)
```

### 4.3 PG slow query (host postgres exporter varsa)

```promql
pg_stat_activity_max_tx_duration{state="active"}
# Beklenen: < 30s long-running tx (> 1m → alert)
```

### 4.4 Calico CNI health

```promql
# Pod ready state (calico-system ns)
sum(kube_pod_status_ready{namespace="calico-system",condition="true"})
  / sum(kube_pod_status_phase{namespace="calico-system",phase="Running"})
# Beklenen: 1.0 (100% Ready)
```

### 4.5 Node disk IO saturation

```promql
rate(node_disk_io_time_seconds_total{device=~"sda|sdb|nvme.*"}[5m])
# Beklenen: < 0.8 (80%) — 1.0'a yakın = disk darboğaz (D11 200GB disk)
```

---

## 5. S3 Stability Soak — 7 Günlük Query Rehberi

### Gün 1 — Baseline tespit

```promql
# CPU + memory 24h trend (tüm platform pod'lar)
avg_over_time((sum by (pod) (rate(container_cpu_usage_seconds_total{namespace=~"platform-(test|prod)"}[5m])))[24h:5m])
avg_over_time((sum by (pod) (container_memory_working_set_bytes{namespace=~"platform-(test|prod)"}))[24h:5m]) / 1024 / 1024
```

### Gün 4-5 — Chaos test window

```promql
# Pod restart son 48h (chaos başından beri) — Calico delete + PG restart + ArgoCD pause
sum by (pod, namespace) (
  increase(kube_pod_container_status_restarts_total{namespace=~"platform-(test|prod)"}[48h])
)
# Ek: probe_success continuity (chaos sırasında edge down mu?)
min_over_time(probe_success{job=~"blackbox-testai-.*"}[48h])
```

### Gün 6 — Load test (k6 tests/k6/zanzibar-load.js)

```promql
# Load sırasında Hub p95 + 5xx ratio spike
histogram_quantile(0.95,
  sum by (le) (rate(http_server_requests_seconds_bucket{application="permission-service"}[1m]))
)
# VE
sum(rate(http_server_requests_seconds_count{application="permission-service",status=~"5.."}[1m]))
```

### Gün 7 — No-Go gate 6/6 blocker

Her blocker için ilgili query (Bölüm 1-4'ten):
1. Up: §2.1 restart rate + §4.4 Calico
2. Functional: §1.2 Hub request rate (active)
3. Zanzibar-ready: §3.4 synthetic probe
4. D30 immutable: `kube_pod_container_info{image=~".*sha-.*"}` filter
5. Observability: §1.4 Hub 5xx + §3.1 edge 5xx
6. Rollback drill: manuel (dış proxy switch prova)

---

## 6. Alert Rule Backing (PrometheusRule mapping)

| Alert | PromQL | Kaynak |
|---|---|---|
| `ZanzibarHubDown` | `up{job="permission-service"} == 0` | §1.1 altı |
| `OpenFGADown` | `up{job="openfga"} == 0` | §1.5 eşdeğeri |
| `ZanzibarEdgeSyntheticFail` | `probe_success{job=~"blackbox-(testai\|prod)-(deny\|health)"} == 0` | §3.4 |
| `PlatformPodRestartSpike` | `increase(kube_pod_container_status_restarts_total{...}[15m]) > 0` | §2.1 |
| `PlatformPodNotReady` | `kube_pod_status_ready{...,condition="true"} == 0` | §2.2 tersini |
| `EdgeHigh5xxRatio` | §3.1 > 0.01 | §3.1 |
| `EdgeHighLatency` | §3.2 > 2s | §3.2 |
| `CNINodeNotReady` | §4.4 < 1.0 | §4.4 |

Tümü `kustomize/base/monitoring/zanzibar-stability-rule.yaml` içinde tanımlı.

---

## 7. Recording Rules (pre-compute, `kustomize/base/monitoring/recording-rules.yaml`)

Expensive PromQL query'ler recording rule olarak pre-compute edildi. Dashboard ve alert'ler bu metric'leri kullanır → render hızlı + tek yerde tanım.

| Recording rule | Kapsam |
|---|---|
| `platform:hub:requests:rate5m` | Hub request rate by URI |
| `platform:hub:requests:p95` | Hub p95 latency by URI |
| `platform:hub:errors:ratio` | Hub 5xx error ratio |
| `platform:gateway:p95` | Gateway p95 latency |
| `platform:gateway:requests:rate5m` | Gateway request rate by URI |
| `platform:edge:5xx_ratio` | Ingress-nginx 5xx ratio (EdgeHigh5xxRatio alert) |
| `platform:edge:requests:rate5m` | Ingress-nginx request rate |
| `platform:pods:not_ready` | Platform ns Not Ready pod count |
| `platform:pods:restart:rate15m` | 15dk restart rate per pod |
| `platform:pods:memory:usage_ratio` | Pod memory / limit |
| `platform:pods:cpu:throttle_ratio` | Pod CPU throttle ratio |
| `platform:jvm:heap:ratio` | JVM heap % |
| `platform:jvm:gc:p95_ms` | JVM GC pause p95 ms |
| `platform:hikari:pool:active_ratio` | Hikari pool utilization |
| `platform:hikari:timeout:rate5m` | Hikari timeout rate |
| `platform:probe:success_ratio_5m` | Blackbox probe 5dk avg success |
| `platform:probe:duration:p95` | Probe duration p95 |

**Kullanım:** Dashboard panellerinde doğrudan recording rule adı query olarak kullanılır (örn. `platform:hub:p95{uri="/api/v1/authz/check"}` ham histogram_quantile yerine).

## 8. Referanslar

- `kustomize/base/monitoring/zanzibar-stability-rule.yaml` — Alert PrometheusRule
- `kustomize/base/monitoring/recording-rules.yaml` — Pre-compute recording rules
- `kustomize/base/monitoring/blackbox-exporter.yaml` — 4 Probe CR
- `kustomize/base/monitoring/backup-freshness-rule.yaml` — Backup alert + exporter
- `kustomize/base/monitoring/grafana-dashboards/` — 4 dashboard (authz plane + platform pods + edge synthetic + JVM/DB/Hikari)
- `docs/S3-stability-soak-pack.md` — S3 soak 7 günlük plan
- `docs/S1-S2-acceptance-smoke-runbook.md` — D29 3-katman acceptance smoke
- `tests/k6/zanzibar-load.js` — Load test profile (Gün 6)
