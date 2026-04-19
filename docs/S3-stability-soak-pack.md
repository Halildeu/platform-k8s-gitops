# S3 Stability Soak — Prometheus Query Pack + Synthetic Probe + No-Go Gate Template

> **Source:** K8s-6 S3 setup (2026-04-19)
> **Usage:** testai stability soak (3-7 gün gözlem) + No-Go gate review (cutover öncesi)
> **Codex S1-E6 kabul:** "S3 scope — apply sonraki session, bugün paket hazırlanması"

---

## 1. Prometheus Query Pack

### 1.1 Zanzibar-ready Sinyal Metrikleri

```promql
# Restart delta (son 15dk rollout penceresi dışında 0 olmalı)
sum(increase(kube_pod_container_status_restarts_total{namespace="platform-test"}[15m])) by (pod)

# Pod Ready durumu (0 değilse pod ready değil)
sum(kube_pod_status_ready{namespace="platform-test",condition="true"} == 0) by (pod)

# Edge 5xx ratio (testai gateway istekleri)
rate(nginx_ingress_controller_requests{ingress="platform",status=~"5.."}[5m]) 
  / rate(nginx_ingress_controller_requests{ingress="platform"}[5m])

# p95 latency (gateway)
histogram_quantile(0.95, 
  sum(rate(http_server_requests_seconds_bucket{application="api-gateway"}[5m])) by (le))

# Authz plane health
up{job="permission-service"}
up{job="openfga"}

# Hikari pool timeout (Loki sentinel)
# {namespace="platform-test"} |= "HikariPool" |= "timeout"

# CNI health
# calico-node Ready status
kube_pod_status_ready{namespace="calico-system", pod=~"calico-node-.*", condition="true"}

# Synthetic authz probe (blackbox-exporter, S3-A2)
probe_success{job="blackbox-testai-authz",target=~".*authz/(me|version)$"}
```

### 1.2 Önerilen Eşikler (Codex A3 uzlaşı)

| Metrik | Eşik | Alert |
|---|---|---|
| Restart delta | rollout penceresi dışında `0` | Her restart → warn |
| Unexpected 5xx ratio | sürekli `< 0.5%` | 15dk'lık pencere `> 1%` → crit |
| Hikari timeout log | `0` | 1 kayıt → warn |
| Authz synthetic pass rate | `100%` | 1 fail → warn, 3 fail peş peşe → crit |
| OpenFGA/permission-service uptime | `100%` | down → crit |
| CNI degraded event | `0` | degraded=true → warn |

### 1.3 PrometheusRule YAML Taslak

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: zanzibar-stability
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: zanzibar.stability
      interval: 30s
      rules:
        - alert: ZanzibarHubDown
          expr: up{job="permission-service"} == 0
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "Permission-service (Zanzibar hub) down"

        - alert: PodRestartSpike
          expr: sum(increase(kube_pod_container_status_restarts_total{namespace="platform-test"}[15m])) > 0
          for: 1m
          labels:
            severity: warning
          annotations:
            summary: "Unexpected pod restart in platform-test"

        - alert: CNIDegraded
          expr: sum(kube_pod_status_ready{namespace="calico-system", pod=~"calico-node-.*", condition="true"} == 0) > 0
          for: 1m
          labels:
            severity: critical
          annotations:
            summary: "Calico CNI node not ready"

        - alert: AuthzSyntheticFail
          expr: probe_success{job="blackbox-testai-authz"} == 0
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Zanzibar authz synthetic probe failing"
```

## 2. Synthetic Authz Probe (blackbox-exporter)

### 2.1 Config Taslak

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: blackbox-exporter-config
  namespace: monitoring
data:
  blackbox.yml: |
    modules:
      authz_allow:
        prober: http
        http:
          method: GET
          valid_status_codes: [200]
          bearer_token_file: /etc/blackbox/smoke-client-token  # S2-B3 smoke-client secret
          preferred_ip_protocol: ip4
      authz_deny:
        prober: http
        http:
          method: GET
          valid_status_codes: [401, 403]
          fail_if_body_matches_regexp:
            - '"error":"server_error"'  # gerçek 403/401 olmalı, 500 olmamalı
```

### 2.2 Probe Targets

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: zanzibar-authz-synthetic
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  jobName: blackbox-testai-authz
  module: authz_deny  # veya authz_allow (smoke-client token ile)
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  interval: 60s
  targets:
    staticConfig:
      static:
        # Intra-cluster Hub probe
        - http://permission-service.platform-test.svc.cluster.local:8090/api/v1/authz/version
        - http://permission-service.platform-test.svc.cluster.local:8090/api/v1/authz/me
        # Gateway enforcement probe (deny path)
        - http://api-gateway.platform-test.svc.cluster.local:8080/variants
        - http://api-gateway.platform-test.svc.cluster.local:8080/auth/login
```

**Smoke-client token** (S2-B3 handoff) secret mount + bearer_token_file ile allow tarafı.

## 3. No-Go Gate Review Template

### 3.1 Review Tablosu (her Cuma cutover milestones yaklaştığında)

| # | Mutlak Blocker | Durum | Kanıt |
|---|---|---|---|
| 1 | Edge authenticity (testai + ai) | 🟢 / 🟡 / 🔴 | (smoke body sentinel + CT) |
| 2 | CNI dependency path | 🟢 / 🟡 / 🔴 | (TigeraStatus + labeled pod TCP) |
| 3 | Runtime contract correctness | 🟢 / 🟡 / 🔴 | (K8s ConfigMap override + dev repo shortname default) |
| 4 | Authz plane active + allow/deny enforce | 🟢 / 🟡 / 🔴 | (smoke-client token allow 2xx + unauthorized 403) |
| 5 | Immutable artifact | 🟢 / 🟡 / 🔴 | (tüm servisler `sha-<short>` tag, pod imageID = CI digest) |
| 6 | report/schema PG primary veya scope-out | 🟢 / 🟡 / 🔴 | (D31 uyumu) |

### 3.2 Warning-Level (soak takibi)

- Promtail/Tempo/Grafana coverage
- ArgoCD sync health
- Unexpected restart delta rollout penceresi dışında
- Synthetic trace/dashboard completeness

### 3.3 No-Go Karar

- **6/6 mutlak blocker 🟢** + **warning'ler stabil** → cutover aç
- **1+ mutlak blocker 🔴** veya **3+ warning kritik** → cutover kapalı

## 4. Soak Gün-Gün Takibi

```
Gün 1: Deploy tamam, metrik collection başladı. İlk 24h gözlem.
Gün 2: Restart delta, 5xx ratio, Hikari timeout review. Authz synthetic ilk 48h.
Gün 3: p95 latency trend analiz. Memory/CPU baseline.
Gün 4-5: Chaos test (Calico pod delete, PG restart, ArgoCD sync pause).
Gün 6: Synthetic allow/deny regression check. Load test (k6 Zanzibar-25 pattern).
Gün 7: No-Go gate review → cutover açık/kapalı karar.
```

## 5. Apply Notu

**Bu bir doküman pack — S3 session'da apply edilir.** Gerekli dosyalar:
- `kustomize/base/monitoring/zanzibar-stability-rule.yaml` — PrometheusRule (Hub/Pod/CNI + ZanzibarEdgeSyntheticFail)
- `kustomize/base/monitoring/blackbox-exporter.yaml` — ConfigMap + Deployment + Service + 4 Probe CR (testai-deny/health + prod-deny/health, Codex iter-2 C-1 REVISE-ONAY external edge target)
- `kustomize/base/monitoring/kustomization.yaml` — base kustomization (namespace: monitoring)

Apply sırası:
1. `kubectl --context k3d-prod apply -k kustomize/base/monitoring` (prod cluster merkezi monitoring)
2. Doğrula: `kubectl -n monitoring get probes,prometheusrules`

S2-C1 ArgoCD install + S2-B3 smoke-client sonrası S3-A uygulama. Smoke-client
bearer token secret mount blackbox-exporter.yaml satır 86-90 + 99-101 yorumdan
açılır (authz_allow module bearer_token_file mount).
