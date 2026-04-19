# TraceQL Query Pack — Tempo Trace Analysis

> **Source:** K8s-6 S3-A monitoring stack (Tempo + OTel instrumentation)
> **Hedef ortam:** prod cluster merkezi Tempo (48h retention, D10)
> **Kullanım:** Grafana Explore → Tempo datasource → TraceQL veya `tempo-cli`

---

## 1. Spring Boot OTel Config (application-k8s.yml örnek)

Platform servislerinin Spring Boot profile'ında OTel tracing aktif:

```yaml
# backend/<svc>/src/main/resources/application-k8s.yml
management:
  tracing:
    sampling:
      probability: ${OTEL_SAMPLING_RATE:0.1}  # %10 default, S3 soak %100 (env override)
  otlp:
    tracing:
      endpoint: ${OTEL_ENDPOINT:http://tempo.monitoring.svc.cluster.local:4318/v1/traces}
```

**Env override (overlay patch):**
```yaml
# kustomize/overlays/prod/kustomization.yaml patch
- target:
    kind: ConfigMap
    name: <svc>-config
  patch: |-
    - op: add
      path: /data/OTEL_SAMPLING_RATE
      value: "0.1"    # prod default
    - op: add
      path: /data/OTEL_ENDPOINT
      value: "http://tempo.monitoring.svc.cluster.local:4318/v1/traces"
```

---

## 2. TraceQL Query Örnekleri

### 2.1 Authz plane trace (hub → OpenFGA)

```traceql
{service.name="permission-service" && span.http.target=~"/api/v1/authz/.*"}
```

### 2.2 Gateway → backend full trace

```traceql
{span.http.target=~"/variants.*" && resource.service.name="api-gateway"}
  | select(duration > 1s)
```

### 2.3 Slow request (p95 üzeri)

```traceql
{duration > 2s}
  | select(resource.service.name, name, duration, span.http.target)
```

### 2.4 Error trace (status=error)

```traceql
{status=error}
  | select(resource.service.name, name, span.http.status_code)
```

### 2.5 Authz check latency dağılımı (span bazlı)

```traceql
{span.name="authz.check" && resource.service.name="permission-service"}
  | histogram_over_time(duration)
```

### 2.6 OpenFGA call trace

```traceql
{span.name=~"openfga\\.(check|list_objects)"}
  | select(duration, span.openfga.store_id)
```

### 2.7 Hikari connection acquire span

```traceql
{span.name="hikari.connection.acquire" && duration > 500ms}
```

---

## 3. Ops Troubleshooting Pattern

### 3.1 Kullanıcı "istek yavaş" diyor — root cause

1. Gateway trace: `{resource.service.name="api-gateway" && span.http.target="/reports"}` — hangi upstream yavaş?
2. Downstream servis trace: `{resource.service.name="report-service" && duration > 1s}` — DB mi, authz mı?
3. Hikari span: DB connection acquire yavaş mı?
4. PG server trace (varsa pg_stat_activity korelasyon)

### 3.2 5xx error burst — hangi endpoint/servis?

1. Edge log 5xx (LogQL `{namespace="ingress-nginx"} | json | status=~"5.."`)
2. Upstream adresi tespit (nginx access log `upstream` field)
3. TraceQL: `{resource.service.name="<upstream>" && status=error} | select(name, span.http.target)`
4. Error span detay: exception stack trace vs HTTP 5xx

### 3.3 Authz fail analizi (permission denied)

1. Auth-service trace: JWT decode PASS?
2. Hub trace: `{resource.service.name="permission-service" && span.http.status_code=403}` — hangi subject/object?
3. OpenFGA call trace: check response false neden?

---

## 4. S3 Soak Sampling Stratejisi

### 4.1 Production default (%10)

```yaml
OTEL_SAMPLING_RATE: "0.1"
```

### 4.2 S3 Soak — sampling %100 (7 gün)

Tüm trace'leri capture et (ileri debug için):

```yaml
# overlays/prod/kustomization.yaml patch S3 soak sırasında
OTEL_SAMPLING_RATE: "1.0"
```

**Dikkat:** Tempo retention 48h (D10). 7 günlük soak'ta 3.5× fazla trace → storage baskısı. Gerekirse:
- Tempo retention geçici 7d'ye çek
- Veya sampling %50'ye düşür

### 4.3 Chaos test (Gün 4-5) — trace önem

Chaos test sırasında sampling %100 kritik — recovery pattern trace'lenmeli.

---

## 5. Tempo Tuning Önerisi

### 5.1 WAL + Local Storage Capacity

```yaml
# helm-values/tempo/values.yaml
tempo:
  storage:
    trace:
      backend: local
      local:
        path: /var/tempo/traces
  retention: 48h

  # WAL segment size
  ingester:
    max_block_duration: 30m
    max_block_bytes: 500_000_000   # 500MB segment
```

### 5.2 Query Federation (uzun vade)

`remote_write` ile S3/Azure Blob backend (uzun retention):

```yaml
storage:
  trace:
    backend: s3
    s3:
      endpoint: s3.amazonaws.com
      bucket: platform-tempo-traces
      region: us-east-1
```

Şu an MVP'de filesystem yeterli.

### 5.3 Cardinality Kontrolü

Tempo tag cardinality Loki'den daha yüksek dayanır ama:
- `user_id`, `tenant_id` gibi high-cardinality tag'leri **span attribute** olarak tut (aranabilir değil indexed değil)
- `service.name`, `span.kind`, `http.status_code` gibi düşük-cardinality tag'leri **resource** olarak tut (indexed)

---

## 6. Alert Rule Potansiyel (Metric Generator)

Tempo'nun `metrics_generator` ile trace'lerden metric üret:

```yaml
# helm-values/tempo/values.yaml
tempo:
  metricsGenerator:
    enabled: true
    processor:
      spanMetrics:
        enabled: true
      serviceGraphs:
        enabled: true
```

Üretilen metric'ler Prometheus'a gönderilir, PrometheusRule'da kullanılır:

```promql
# Örnek: servis-to-servis latency p95 (service graph metric)
histogram_quantile(0.95, sum by (le, client, server)
  (rate(traces_service_graph_request_total[5m])))
```

---

## 7. Referanslar

- `helm-values/tempo/values.yaml` — Tempo Helm values
- `docs/promql-query-pack.md` — PromQL metric query pack
- `docs/logql-query-pack.md` — LogQL log query pack
- `docs/S3-stability-soak-pack.md` — S3 soak plan
- PLAN.md D10 Tempo retention (48h)
- `kustomize/base/apps/<svc>/configmap.yaml` — OTEL_ENDPOINT + OTEL_SAMPLING_RATE env (eklenmeli)
