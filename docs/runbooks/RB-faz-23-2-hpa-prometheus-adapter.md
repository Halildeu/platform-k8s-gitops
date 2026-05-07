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
cross-pod broadcast pattern eklendi. PG-only stateful kanonik
referansı: [ADR-0013 §"Stateful"](../adr/0013-notification-orchestration.md)
(Mongo/Redis/RabbitMQ YASAK) + PLAN.md D38/D39 notification authority
kararı. Her pod'un `InboxNotifyListener`'ı NOTIFY event'lerini post-commit
alır + lokal Spring event re-emit eder ⇒ hangi pod handle ederse etsin
tüm SSE client'lar update alır.
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

# Tüm pod'ların PR #89 image digest'inde olduğunu doğrula
# (Codex iter-1 absorb: HPA scale-out ile pod sayısı >1; tek pod kontrolü
# stale rollout maskelenebilir).
EXPECTED_DIGEST="sha256:b329d2e74fc7b75c1cbb4b47ee8e0f1a0253d670e4efd1dd652de54e48dba125"
kubectl --context k3d-test -n platform-test get pod \
  -l app.kubernetes.io/name=notification-orchestrator \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[0].imageID}{"\n"}{end}'
# Her satırın imageID'si EXPECTED_DIGEST içermeli; içermiyorsa rollout
# tamamlanmamış veya pinleme drift'i var.
```

Cross-pod smoke deterministik — DB-direct NOTIFY yaklaşımı (pod sayısı ≥2 olunca):
```bash
# Cross-pod kanıtı: bir pod'a (POD_A) SSE bağlan; NOTIFY publish'i
# **POD_A'nın kendi process'inden DEĞİL** — cluster dışındaki ephemeral
# psql client'tan gelir. POD_A'nın SSE client'ı bu NOTIFY'a karşılık
# event aldıysa, bu LISTEN/NOTIFY hattının çalıştığını ve JVM-local
# event publisher race'inin (PR-E.3 motivasyonu) kapandığını kanıtlar.
# POD_B aynı pattern'i ayrı bir tarafta confirm eder ama tek pod'a SSE
# bağlamak yeterli kanıt; smoke recipe POD_A'ya odaklı.
#
# Codex iter-1 absorb: deterministik recipe (eski log grep yetmez).
# Codex iter-2 absorb: container http port 8089 (8080 değil); psql
# notification-orchestrator imajında kurulu DEĞİL → ephemeral postgres
# client pod; tablo qualified (notify.notification_inbox).
# Codex iter-3 absorb: SSE endpoint authenticated → JWT; INSERT tek
# başına NOTIFY tetiklemez (DB trigger yok; publishViaPgNotify Java
# katmanında); SSE log post-mutation event sayısı BASELINE/FINAL delta.
# Codex iter-4 absorb: notification-orchestrator-config test overlay'de
# SECURITY_JWT_ISSUER_URI override'ı eklendi (PR #387 same-PR; backend
# default localhost:8081/realms/serban test cluster için invalid).
# Narrative drift düzeltildi: POD_B mutate yapısı kaldırıldı; recipe
# DB-direct NOTIFY smoke odaklı (cross-pod kanıtı için yeterli).

CTX="k3d-test"; NS="platform-test"
PODS=( $(kubectl --context $CTX -n $NS get pod -l app.kubernetes.io/name=notification-orchestrator -o jsonpath='{.items[*].metadata.name}') )
[ ${#PODS[@]} -lt 1 ] && { echo "Pod yok; deploy aktif değil"; exit 1; }
[ ${#PODS[@]} -lt 2 ] && echo "UYARI: pod sayısı <2 — cross-pod kanıtı zayıf; HPA scale-out tetikle veya manuel scale ile pod sayısını artır."
POD_A=${PODS[0]}

# 0) Test JWT al (Keycloak test realm; admin-cli client password grant).
#    SSE endpoint /api/v1/notify/** authenticated; port-forward gateway'i
#    bypass eder ama Spring Security hâlâ token bekler.
KC_URL="https://testai.acik.com/realms/platform-test/protocol/openid-connect/token"
JWT=$(curl -s -X POST "$KC_URL" \
  -d "client_id=admin-cli&grant_type=password&username=test-admin&password=$TEST_ADMIN_PASS" \
  | jq -r '.access_token')
[ -z "$JWT" ] || [ "$JWT" = "null" ] && { echo "FAIL: JWT alınamadı"; exit 1; }

# 1) Pod A'ya port-forward (container http port 8089).
kubectl --context $CTX -n $NS port-forward $POD_A 8089:8089 &
PF_PID=$!
sleep 2
# Önce Pod A'nın "inbox LISTEN started" log mesajını gör (cross-pod hat
# açıldı kanıtı):
kubectl --context $CTX -n $NS logs $POD_A | grep -E "inbox LISTEN started" | tail -1

# 2) SSE bağlan with JWT. Initial event hemen gelir; BASELINE event sayısı
#    log'lanır. Sonra BEFORE marker bırakılır ve mutation tetiklenir.
curl --no-buffer -N \
  -H "Authorization: Bearer $JWT" \
  -H 'Accept: text/event-stream' \
  "http://localhost:8089/api/v1/notify/inbox/me/stream?orgId=default&subscriberId=smoke-x" > /tmp/sse-A.log &
SSE_PID=$!
sleep 3
# BASELINE: initial event geldi mi? (genelde 1)
BASELINE=$(grep -cE 'event: ?unread-count' /tmp/sse-A.log)
echo "BASELINE event count: $BASELINE"
[ "$BASELINE" -lt 1 ] && { echo "FAIL: initial unread-count event yok"; kill $SSE_PID $PF_PID; exit 1; }

# 3) Cross-pod NOTIFY tetikle. publishViaPgNotify Java'da
#    SELECT pg_notify('inbox_updated', '{"orgId":...,"subscriberId":...}')
#    çalıştırır; DB trigger YOK. Smoke recipe iki yol:
#    (A) publishViaPgNotify iş mantığını ephemeral psql ile re-create:
#        BEGIN; INSERT ... ; SELECT pg_notify(...); COMMIT;
#        — listener post-commit NOTIFY alır → countUnreadBySubscriber → 1
#    (B) gateway-auth'lu yol: POST /api/v1/notify/submit (her pod'da
#        publish path'ini exercise eder ama JWT permission gerekir;
#        operatör isterse alternatif).
#    Aşağıda (A) kullanılıyor.
PGPASS=$(kubectl --context $CTX -n $NS get secret notification-orchestrator-secrets \
  -o jsonpath='{.data.SPRING_DATASOURCE_PASSWORD}' | base64 -d)
INTENT_ID="smoke-intent-$(date +%s)"
kubectl --context $CTX -n $NS run psql-smoke-$$ --rm -i --restart=Never \
  --image=postgres:15-alpine \
  --env=PGPASSWORD="$PGPASS" -- \
  psql "postgresql://notify@postgres:5432/notify_db" -c "
    BEGIN;
    INSERT INTO notify.notification_inbox
      (org_id,intent_id,subscriber_id,locale,topic_key,severity,state,created_at)
    VALUES
      ('default','$INTENT_ID','smoke-x','tr-TR','test.topic','info','UNREAD',now());
    SELECT pg_notify('inbox_updated', '{\"orgId\":\"default\",\"subscriberId\":\"smoke-x\"}');
    COMMIT;
  "

# 4) Beklenen: BASELINE'dan sonra 1+ event daha geldi (BASELINE+1 ≥ 2).
#    Listener post-commit NOTIFY aldı → recompute count → Spring event →
#    SSE emitter Pod A client'a push.
sleep 5
FINAL=$(grep -cE 'event: ?unread-count' /tmp/sse-A.log)
echo "FINAL event count: $FINAL"
if [ "$FINAL" -gt "$BASELINE" ]; then
  echo "PASS: cross-pod delivery doğrulandı ($BASELINE → $FINAL event)"
else
  echo "FAIL: post-mutation event yok ($BASELINE = $FINAL)"
fi

# Cleanup
kill $SSE_PID $PF_PID 2>/dev/null
```

Alternatif kontrol — log delivery zinciri (sadece pasif gözlem):
```bash
# Hangi pod NOTIFY emit etti, hangi pod SSE event send etti — pasif izleme.
# Smoke ile karıştırma: bu komut sadece tüm pod'ların log'unda NOTIFY
# çıkıp çıkmadığını + hangi pod'da SSE send olduğunu gösterir. NOTIFY
# fail durumunda root cause hızlı bulmak için kullanılır.
kubectl --context $CTX -n $NS logs --all-containers --tail=100 \
  -l app.kubernetes.io/name=notification-orchestrator \
  | grep -E "inbox NOTIFY|inbox SSE event send"
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

### PR-E.4 cross-pod smoke fail recovery (Codex iter-2 absorb, 2026-05-07)

Eğer post-revert (HPA min=1 max=3 base default) cross-pod smoke FAIL ise
(Pod A'ya bağlı SSE client Pod B'den tetiklenen NOTIFY için event
ALMIYOR), aşağıdaki sırayla geri çekil:

1. **Geçici HPA single-pod re-lock** (operatör unblock — repo truth ile
   senkron olmasa da pre-prod kabul edilebilir):
   ```bash
   kubectl --context k3d-test -n platform-test patch hpa notification-orchestrator \
     --type=json -p='[
       {"op":"replace","path":"/spec/minReplicas","value":1},
       {"op":"replace","path":"/spec/maxReplicas","value":1}
     ]'
   kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator
   ```

2. **Repo'ya yansıt**: PR #387 revert'inin reverse'ünü hemen yeni branch'a
   çıkar (`fix/notify-pr-e-4-rollback-hpa-relock`) → kustomize/overlays/
   test/kustomization.yaml'a HPA min=max=1 patch'ini geri ekle → açık ve
   merge et. Live patch sadece geçici; gitops desired-state ile drift
   bırakma.

3. **Digest rollback (opsiyonel)** — eğer fail kök sebebi PR #89 image
   bug'ı ise (örn. listener thread başlatma fail, NOTIFY publish 0 byte
   payload), AYRI PR ile digest'i bir önceki bilinen-iyi sha-b758571'e
   geri al. Bunu HPA re-lock PR'ı ile karıştırma — iki bağımsız değişim,
   ayrı audit trail.

4. **Backend yeni iter**: PR-E.4 image'ını fix et, yeni digest, yeni
   image promotion PR + HPA tekrar revert PR. Tam döngüyü kullanıcıya
   raporla.

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
