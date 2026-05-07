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

### Faz 23.3 PR-E.3 SSE single-pod lock — RESOLVED in PR-E.4 (2026-05-07)

**Tarihsel bağlam (artık geçerli değil)**: Backend PR
Halildeu/platform-backend#84 SSE inbox stream eklendiğinde SseEmitter map +
ApplicationEventPublisher JVM-local olduğu için multi-pod scale SSE
delivery'i kırardı. Test overlay HPA `min=max=1` lock geçici olarak
zorunlu kılındı (gitops PR #385).

**Çözüm (Faz 23.4 PR-E.4 — Halildeu/platform-backend#89)**: PG LISTEN/NOTIFY
cross-pod broadcast pattern eklendi (ADR-0002 §7.1 PG-only;
Redis pub/sub / STOMP+broker YASAK). Her pod'un `InboxNotifyListener`'ı
NOTIFY event'lerini post-commit alır + lokal Spring event re-emit eder ⇒
hangi pod handle ederse etsin tüm SSE client'lar update alır.
@TransactionalEventListener(AFTER_COMMIT, fallbackExecution=true) ile
single-pod fallback'da phantom event önlenir (rollback durumunda listener
fire etmez).

**Gitops revert**: PR #385 patch (HPA min=max=1) **kaldırıldı**;
HPA base default (min=1, max=3) restored — CPU/memory autoscaling tekrar
aktif.

Operasyonel etki (revert sonrası):
- `kubectl get hpa notification-orchestrator -n platform-test`
  → `MIN PODS: 1, MAX PODS: 3` (base default)
- CPU > %70 veya Memory > %80 olunca scale-out aktif; SSE delivery PG
  LISTEN/NOTIFY üzerinden cross-pod sağlanır
- External metric `notify_queue_pending_intents` veri akışı + scale-out
  reaktivasyonu (alert + autoscale)

Rollout preflight (gitops revert apply sonrası):
```bash
kubectl --context k3d-test -n platform-test get deploy,hpa,pod \
  -l app.kubernetes.io/name=notification-orchestrator
# HPA MIN PODS: 1 / MAX PODS: 3 doğrula
# Backend image: notification-orchestrator pod'ları PR #89 image digest'inde mi?
kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=notification-orchestrator -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'
```

Cross-pod smoke (pod sayısı >1 olunca):
```bash
# Pod A'ya SSE bağlan; Pod B'de inbox row insert; SSE client A event almalı
kubectl --context k3d-test -n platform-test logs -l app.kubernetes.io/name=notification-orchestrator --tail=50 | grep -E "inbox NOTIFY|inbox SSE event send|InboxNotifyListener"
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
