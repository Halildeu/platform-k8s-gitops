# RB-faz-23-2-hpa-prometheus-adapter — HPA + Prometheus Adapter setup

> **Status**: ACTIVE (Faz 23.2 PR-D.4)
> **Scope**: notification-orchestrator HPA custom metric scaling

## Bağlam

PR-D.4 öncesi notification-orchestrator HPA CPU + Memory base'liydi. Custom
metric `notify_queue_pending_intents` (OutboxPoller backlog) ile scale on
intent intake backpressure mümkün — CPU/Memory bu sinyali doğrudan
yansıtmaz (pod disk/network bound olabilir).

Prometheus Adapter Kubernetes external metrics API (`external.metrics.k8s.io`)
sağlar; HPA `External` metric type bu API'yi okur.

---

## Adımlar (operatör kurulumu)

### 1. Prerequisite — kube-prometheus-stack aktif

```bash
kubectl --context k3d-test -n monitoring get svc kube-prometheus-stack-prometheus
# Beklenen: 1 svc, port 9090
```

Yoksa: `bash bootstrap/install-monitoring.sh test`

### 2. Prometheus Adapter install

```bash
# test cluster
bash bootstrap/install-prometheus-adapter.sh test

# prod cluster (D29 evidence sonrası)
bash bootstrap/install-prometheus-adapter.sh prod
```

### 3. Verification

**APIService**:
```bash
kubectl --context k3d-test get apiservice v1beta1.external.metrics.k8s.io
# Beklenen: AVAILABLE=True
```

**Custom metric query** (notification-orchestrator pod scale-up sonrası):
```bash
kubectl --context k3d-test get --raw \
  '/apis/external.metrics.k8s.io/v1beta1/namespaces/platform-test/notify_queue_pending_intents'
# Beklenen: { "items": [{...}], "kind": "ExternalMetricValueList", ... }
```

**HPA status**:
```bash
kubectl --context k3d-test -n platform-test get hpa notification-orchestrator
# Beklenen: TARGETS sütunu CPU + Memory + External metric değerleri
```

### 4. Operasyonel test

Backlog yaratmak için intent submit batch (test cluster):
```bash
# 1000 intent submit (e.g. via curl loop or load test tool)
for i in {1..1000}; do
  curl -X POST http://localhost:8089/api/v1/notify/submit \
    -H 'Content-Type: application/json' \
    -d '{"intent_id":"load-test-'$i'", ...}'
done

# notification-orchestrator pod scale durumu
watch -n 5 'kubectl --context k3d-test -n platform-test get hpa,pod -l app.kubernetes.io/name=notification-orchestrator'
```

`notify_queue_pending_intents > 200 avg per-pod` olunca HPA pod artırır
(base manifest maxReplicas=3 sınırı).

### Faz 23.3 PR-E.3 SSE single-pod lock (2026-05-06)

Backend PR Halildeu/platform-backend#84 SSE inbox stream eklendi.
SseEmitter map + ApplicationEventPublisher JVM-local; multi-pod scale SSE
delivery'i kırar. Test overlay HPA `min=max=1` lock zorunlu kılındı
(gitops PR #385).

Operasyonel etki:
- Test cluster'da `kubectl get hpa notification-orchestrator -n platform-test`
  artık `MIN PODS: 1, MAX PODS: 1` gösterir
- External metric `notify_queue_pending_intents` veri akışı korunur (gözlem +
  alert için), ama scale-out Faz 23.3 PR-E.3 boyunca beklenmez
- PR-E.4 cross-pod broadcast (Redis pub/sub / STOMP+broker) merge edilince
  HPA `maxReplicas=3` geri açılabilir; o iter'da bu runbook + overlay patch
  birlikte revert edilmeli

Rollout preflight:
```bash
kubectl --context k3d-test -n platform-test get deploy,hpa,pod \
  -l app.kubernetes.io/name=notification-orchestrator
# Live current replicas >1 ise apply sonrası downscale + SSE client reconnect bekle
```

---

## Rollback

Adapter kaldırıldığında HPA External metric "no data" döner; CPU/Memory
graceful fallback yapar (mevcut behavior preserved).

```bash
helm --kube-context k3d-test -n monitoring uninstall prometheus-adapter
kubectl --context k3d-test -n platform-test get hpa notification-orchestrator
# External metric "<unknown>" → CPU/Memory primary
```

---

## Yasaklar

- Adapter rule değişikliği canlı pod restart gerektirir; test cluster'da
  smoke gözlemlemeden prod'a apply etme **YASAK**
- HPA maxReplicas=3 üst sınır; quota aşımı için manuel artırma D17 quota
  preflight gerektirir
- DLQ accumulation (`notify_dlq_unreplayed`) HPA scaleTarget DEĞİL — DLQ
  problemi sinyalize eder, kapasite değil. Adapter rule'da yer alır
  (operasyonel görünürlük) ama HPA reference etmez

---

## Referans

- `helm-values/prometheus-adapter/values.yaml`
- `bootstrap/install-prometheus-adapter.sh`
- `kustomize/base/apps/notification-orchestrator/hpa.yaml`
- WorkerMetrics gauge: `notification-orchestrator/src/main/java/com/serban/notify/worker/WorkerMetrics.java`
