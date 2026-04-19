# LogQL Query Pack — S3 Soak + Günlük Log Analysis

> **Source:** K8s-6 S3-A monitoring stack (Loki + Promtail)
> **Hedef ortam:** prod cluster merkezi Loki (kube-prometheus-stack paralel)
> **Kullanım:** Grafana Explore → Loki datasource → veya `logcli query '...'`

---

## 1. Authz Plane Log Analysis

### 1.1 Permission-service hub request logs

```logql
{namespace=~"platform-(test|prod)", pod=~"permission-service-.*"}
  | json
  | level="INFO"
  |= "authz"
```

### 1.2 Hub 401/403 rate (deny enforce kanıt)

```logql
sum by (status) (
  count_over_time(
    {namespace=~"platform-(test|prod)", pod=~"permission-service-.*"}
      | json
      | status=~"4.."
    [5m]
  )
)
```

### 1.3 Hub exception stack trace (error analiz)

```logql
{namespace=~"platform-(test|prod)", pod=~"permission-service-.*"}
  |= "ERROR"
  |~ "Exception|stack trace"
  | json
  | line_format "{{.timestamp}} {{.message}}"
```

---

## 2. Gateway + Edge Log Analysis

### 2.1 Gateway access log (nginx JSON)

```logql
{namespace="ingress-nginx"}
  | json
  | status >= 400
  | line_format "{{.time}} {{.status}} {{.req}} {{.upstream}} rt={{.rt}}"
```

### 2.2 Edge 5xx burst detection

```logql
sum by (status) (
  count_over_time(
    {namespace="ingress-nginx"}
      | json
      | status=~"5.."
    [5m]
  )
) > 10
# 5dk'da 10+ 5xx = burst
```

### 2.3 Slow upstream (rt > 2s)

```logql
{namespace="ingress-nginx"}
  | json
  | rt > 2
  | line_format "{{.time}} rt={{.rt}} upstream={{.upstream}} {{.req}}"
```

---

## 3. Platform Pod Crash/Restart Analysis

### 3.1 Pod OOMKilled

```logql
{namespace=~"platform-(test|prod)"}
  |~ "OOMKilled|Out of memory|java.lang.OutOfMemoryError"
  | line_format "{{.timestamp}} {{.pod}} {{.message}}"
```

### 3.2 Spring Boot startup fail

```logql
{namespace=~"platform-(test|prod)"}
  |~ "APPLICATION FAILED TO START|Startup Error|Failed to connect"
  | line_format "{{.pod}} {{.message}}"
```

### 3.3 Liveness/readiness probe fail

```logql
{namespace=~"platform-(test|prod)"}
  |~ "Liveness probe failed|Readiness probe failed|HealthCheck failed"
```

---

## 4. Security + Audit

### 4.1 Failed authentication (Spring Security)

```logql
{namespace=~"platform-(test|prod)", pod=~"(auth-service|api-gateway)-.*"}
  |~ "JWT expired|invalid_token|signature_invalid|AuthenticationException"
  | json
```

### 4.2 Suspicious path access (edge)

```logql
{namespace="ingress-nginx"}
  | json
  | req=~".*\.(env|git|config|admin).*"
  | line_format "{{.time}} {{.status}} {{.ip}} {{.req}}"
# .env, .git, /admin gibi ML/scanner pattern
```

### 4.3 Rate limiting trigger (ileride ingress rate-limit aktif olunca)

```logql
{namespace="ingress-nginx"}
  |= "limit_req_zone"
```

---

## 5. Database + Hikari Pool Logs

### 5.1 Hikari connection timeout

```logql
{namespace=~"platform-(test|prod)"}
  |~ "HikariPool.*timeout|Connection is not available"
  | line_format "{{.pod}} {{.message}}"
```

### 5.2 SQL slow query (JPA DEBUG log ile)

```logql
{namespace=~"platform-(test|prod)"}
  | json
  |~ "Hibernate:|SQL:"
  |= "took" | duration > 1s
```

### 5.3 PG connection drop

```logql
{namespace=~"platform-(test|prod)"}
  |~ "connection closed|server closed the connection|Broken pipe"
```

---

## 6. Calico CNI + Network

### 6.1 Calico BIRD state change

```logql
{namespace="calico-system", pod=~"calico-node-.*"}
  |~ "BIRD|BGP|peer"
```

### 6.2 CNI allocation fail

```logql
{namespace="calico-system"}
  |~ "unable to allocate|no IPs available"
```

### 6.3 Kube-proxy / ipvs health

```logql
{namespace="kube-system"}
  |~ "kube-proxy.*error|ipvs.*fail"
```

---

## 7. Vault + ESO Audit

### 7.1 Vault failed auth

```logql
{namespace="host-services"}   # veya Vault compose stdout Loki ingest
  |~ "invalid_request|missing_client_token|permission_denied"
```

### 7.2 ExternalSecret sync fail

```logql
{namespace="external-secrets"}
  |~ "failed to sync|SecretStore not ready|Vault error"
  | line_format "{{.time}} {{.message}}"
```

### 7.3 Cert rotation trigger (ileride cert-manager varsa)

```logql
{namespace="cert-manager"}
  |~ "renew|issuing|certificate"
```

---

## 8. S3 Stability Soak — 7 Günlük Query Rehberi

### Gün 1 — Baseline

```logql
# Hub request log hacmi baseline (günlük)
sum(count_over_time({namespace=~"platform-(test|prod)", pod=~"permission-service-.*"}[24h]))
```

### Gün 4-5 — Chaos test pencere

```logql
# Chaos sırasında pod restart log
sum by (pod) (
  count_over_time(
    {namespace=~"platform-(test|prod)"}
      |~ "Starting application|APPLICATION FAILED"
    [48h]
  )
)
```

### Gün 6 — Load test (k6)

```logql
# Load sırasında 5xx + error spike
sum by (pod) (
  count_over_time(
    {namespace=~"platform-(test|prod)"}
      | json
      | level="ERROR"
    [1h]
  )
)
```

### Gün 7 — No-Go gate review

```logql
# Son 7 günde ZanzibarEdgeSyntheticFail veya ZanzibarHubDown firing log
{namespace="monitoring", pod=~"alertmanager-.*"}
  |~ "ZanzibarEdgeSyntheticFail|ZanzibarHubDown|OpenFGADown"
  | line_format "{{.time}} {{.message}}"
```

---

## 9. Loki Operator Tuning Önerisi

### 9.1 Retention

```yaml
# helm-values/loki/values.yaml
limits_config:
  retention_period: 168h    # 7 gün (S3 soak pencere)
compactor:
  retention_enabled: true
  retention_delete_delay: 2h
```

### 9.2 Query Timeout

```yaml
limits_config:
  query_timeout: 5m
  max_query_series: 10000
```

### 9.3 Log Label Cardinality

**Anti-pattern:** Her request için unique label (user_id, tenant_id) → Loki stream cardinality patlar. JSON log'da tutulur, label'da tutulmaz.

**Doğru:** namespace, pod, container, level label (düşük cardinality).

---

## 10. Alert Rule Mapping (LokiRule — ileride)

Loki `LokiRule` CRD ile alert tanımlanabilir (PrometheusRule benzeri). Örnek:

```yaml
- alert: HighSpringErrorRate
  expr: |
    sum by (pod) (
      rate({namespace=~"platform-(test|prod)"} |= "ERROR" [5m])
    ) > 10
  for: 15m
```

Şu an MVP'de sadece PrometheusRule kullanılıyor. LokiRule S4 sonrası değerlendirilir.

---

## 11. Referanslar

- `helm-values/loki/values.yaml` — Loki retention + limits
- `helm-values/promtail/values.yaml` — Promtail scrape config
- `docs/promql-query-pack.md` — PromQL query pack (metrikler)
- `docs/S3-stability-soak-pack.md` — 7 günlük soak plan
- `docs/on-call-triage-playbook.md` — alert sonrası log kontrol referansı
