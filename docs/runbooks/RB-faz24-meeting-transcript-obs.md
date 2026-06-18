# RB — Faz 24 meeting-service + transcript-service observability

> **Kapsam:** gitops#1660 (PR-obs-03) ile eklenen `meeting-service` + `transcript-service`
> ServiceMonitor + `meeting-transcript` PrometheusRule alarmlarının tetik → teşhis →
> aksiyon → rollback rehberi. Emsal: STT pipeline (RB redis-streams-staging-sw.md) +
> audit-archive-exporter (RB-faz24-audit-archive-exporter.md).

## 0. Bağlam

- İki servis k3d-test'te 1/1 canlı (foundation #410/#411) ama **bu PR'a kadar
  ServiceMonitor'ları yoktu → scrape edilmiyorlardı**. PR scrape'i açar + 8 alarm kurar.
- Scrape hedefi: `Service` `management` portu **8081** `/actuator/prometheus`
  (Spring Actuator; canlı 200 doğrulandı).
- Prod: D30 cutover'a kadar deploy edilmeyecek → SM boş kalır, alarmlar inert
  (absent()-free tasarım; audio-gateway/STT ile aynı davranış).

## 1. Alarmlar ve teşhis

| Alarm | Anlamı | İlk teşhis |
|---|---|---|
| `MeetingServiceDown` / `TranscriptServiceDown` (critical, 5m) | `up{job=...}==0` — scrape 5dk'dır başarısız | `kubectl -n platform-test get pod -l app.kubernetes.io/name=<svc>`; pod Running mi? `kubectl exec <pod> -- curl -s localhost:8081/actuator/health` 200 mü? |
| `MeetingService5xxRatio` / `TranscriptService5xxRatio` (warning, 10m) | 5xx oranı >%5 (≥20 istek/10dk floor) | `kubectl logs deploy/<svc> --since=15m | grep -E "ERROR|500"`; hangi `uri` 5xx? Prometheus: `topk(5, sum by (uri,status) (rate(http_server_requests_seconds_count{job="<svc>",status=~"5.."}[5m])))` |
| `MeetingServiceDBPoolSaturated` / `TranscriptServiceDBPoolSaturated` (warning, 10m) | `hikaricp_connections_pending>0` — thread'ler DB bağlantısı bekliyor (pool max=5) | Yavaş sorgu mu, leak mi? `hikaricp_connections_active` vs `_max`; PG tarafı `pg_stat_activity` uzun-süren sorgu |
| `MeetingServiceHeapPressure` / `TranscriptServiceHeapPressure` (warning, 15m) | Heap kullanımı >%90 (15dk) | `jvm_memory_used_bytes{area="heap"}` trend; GC: `rate(jvm_gc_pause_seconds_count[5m])`; leak şüphesi → heap dump |

## 2. Deploy + Doğrulama (D29)

### Topoloji (Codex 019edc25 — ÖNEMLİ)

- **base/monitoring** (ServiceMonitor değil; PrometheusRule) ArgoCD `platform-system`
  ile **her iki cluster'a** sync olur (test + prod-hub'da `get prometheusrule` ile
  `stt-pipeline`/`audit-retention-worker` görülür). Yani `meeting-transcript` rule'u
  hem test hem prod-hub Prometheus'unda **yüklenir**.
- **ServiceMonitor**'lar test overlay'inde → yalnız **test** cluster scrape eder
  (lokal `up` + tüm seriler test Prometheus'unda anında oluşur).
- **Alert routing GATED**: test cluster'da **Alertmanager KAPALI**
  (`values-test.yaml` alertmanager.enabled=false) → test rule'u evaluate eder ama
  route etmez. Prod-hub Alertmanager'ı var ama **şu an `cluster="test"` serisi YOK**
  (remote_write KIRIK — **issue #1459**). Bu yüzden bu PR şunu sağlar: test-lokal
  scrape (şimdi doğrulanır) + rule tanımı + allowlist hazırlığı. Uçtan-uca routing
  **#1459 onarılınca** aktif olur (sahte "8 alert canlı routing" iddiası YOK).

### 0. Test Prometheus remote_write allowlist'i uygula (HELM — manuel)

> `platform-system` ArgoCD app **yalnız `kustomize/base/monitoring` CR'lerini** yönetir;
> Helm release'lerini **YÖNETMEZ**. `values-test.yaml` writeRelabelConfigs değişikliği
> `helm upgrade` olmadan test Prometheus config'ine GİRMEZ → bu adım kaçarsa #1459
> onarılsa bile prod-hub yalnız `up` alır, 5xx/Hikari/heap = veri-yok sahte kapsama.

> **GÜVENLİK (Codex 019edc25 MF4):** `--kube-context k3d-test` ZORUNLU. Yanlış
> current-context `k3d-prod` ise `values-test.yaml` PROD release'ine uygulanır →
> prod Alertmanager/Grafana/topology için yüksek blast-radius hata.

```bash
# Mevcut -f zincirini koru (drill values aktifse onu da ekle):
#   helm get values kube-prometheus-stack -n monitoring --kube-context k3d-test
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --kube-context k3d-test \
  --version 85.0.3 \
  -n monitoring \
  -f helm-values/kube-prometheus-stack/values-test.yaml
#   (k3d-test release rev artar)
```

### 1. ServiceMonitor + Rule apply (ArgoCD sync veya manuel)

```bash
# ArgoCD platform-system + overlay sync; manuel selective:
kubectl --context k3d-test apply -k kustomize/overlays/test   # ServiceMonitor'lar
kubectl --context k3d-test apply -k kustomize/base/monitoring  # meeting-transcript rule
```

### 2. Doğrulama — TEST (şimdi yapılabilir)

```bash
PP=prometheus-kube-prometheus-stack-prometheus-0
# a) ServiceMonitor'lar var
kubectl --context k3d-test -n platform-test get servicemonitor meeting-service transcript-service
# b) test Prometheus hedefleri up (1-2 scrape, ~60s bekle)
kubectl --context k3d-test -n monitoring exec $PP -c prometheus -- \
  promtool query instant http://localhost:9090 'up{job=~"meeting-service|transcript-service"}'
#   beklenen: iki seri, value=1
# c) alert girdisi seriler test'te mevcut (5xx/hikari/heap)
kubectl --context k3d-test -n monitoring exec $PP -c prometheus -- \
  promtool query instant http://localhost:9090 \
  'count({job=~"meeting-service|transcript-service",__name__=~"http_server_requests_seconds_count|hikaricp_connections_pending|jvm_memory_used_bytes"})'
#   beklenen: >0
# d) rule yüklü + false-firing yok
kubectl --context k3d-test -n monitoring exec $PP -c prometheus -- \
  promtool query instant http://localhost:9090 \
  'ALERTS{alertname=~"Meeting.*|Transcript.*",alertstate="firing"}'
#   beklenen: boş (sağlıklı state)
```

### 3. Doğrulama — PROD-HUB (#1459 onarıldıktan SONRA)

```bash
# remote_write sağlıklıysa test serileri prod-hub'a allowlist üzerinden gelir:
PP=prometheus-kube-prometheus-stack-prometheus-0
kubectl --context k3d-prod -n monitoring exec $PP -c prometheus -- \
  promtool query instant http://localhost:9090 \
  'count({cluster="test",job=~"meeting-service|transcript-service",__name__=~"http_server_requests_seconds_count|hikaricp_connections_pending|jvm_memory_(used|max)_bytes"})'
#   beklenen (#1459 sonrası): >0. Boşsa: helm upgrade (§0) atlandı VEYA remote_write hâlâ kırık.
```

## 3. Rollback

PrometheusRule veya ServiceMonitor sorun çıkarırsa (örn. yanlış-pozitif alarm seli):

```bash
# Sadece scrape'i geri al (alarmlar da seri olmadan inert olur):
kubectl --context k3d-test -n platform-test delete servicemonitor meeting-service transcript-service
# Veya sadece rule'u kaldır:
kubectl --context k3d-test -n monitoring delete prometheusrule meeting-transcript
# Kalıcı: gitops revert PR (overlay'den ops/ + base/monitoring rule satırlarını çıkar).
```

Rollback **veri kaybı değildir** — yalnız görünürlük/alarmı geri alır; servisler etkilenmez.

## 4. Bilinen sınır / follow-up

- **p95 latency alarmı YOK**: bu servislerde `management.metrics.distribution.percentiles-histogram`
  kapalı → `http_server_requests_seconds_bucket` serisi yok. p95 için backend config
  follow-up gerek; o zamana kadar latency mean(`_sum`/`_count`) + `hikaricp_connections_acquire_seconds`.
- **Custom domain metrikleri YOK** (meeting_*/transcript_*): skeleton domain counter'ları
  ayrı backend PR'ı; landing sonrası bu rule'a iş-seviyesi alarm eklenebilir.
- **Dashboard**: bu PR alarm/scrape kapsar; Grafana dashboard (meeting+transcript SLO)
  fast-follow.

## Referans

- PR: gitops#1660 (PR-obs-03)
- Rule: `kustomize/base/monitoring/meeting-transcript-rule.yaml`
- SM: `kustomize/base/apps/{meeting,transcript}-service/ops/servicemonitor.yaml`
- Emsal: STT `kustomize/base/monitoring/stt-pipeline-rule.yaml` + `docs/runbooks/redis-streams-staging-sw.md`
- Plan: `docs/faz-24-meeting-intelligence-plan.md` §9 (Up/Functional acceptance gate)
