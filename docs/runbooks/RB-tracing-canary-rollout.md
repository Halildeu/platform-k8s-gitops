# RB — Tracing Canary Rollout (R11)

> **Risk register**: #767 R11 — Tempo OTLP collector deploy tracing path'i bozabilir
> **Codex thread**: `019e4448-e90a-7472-9e8c-d287c0fa7970` (M7a R11 PR1 verdict REVISE → Alt-B safety-baseline)
> **Status**: ACTIVE — R11 PR1 (this PR) lands the monitoring + smoke script + this runbook; R11 PR2 lands the first single-service canary apply (notification-orchestrator).

## Tetik

Bir platform servisi için `MANAGEMENT_TRACING_ENABLED=false → true` flip etmeden önce bu runbook çalışır. Default state: 9 backend servisinin **HEPSINDE** tracing OFF; Tempo OTLP collector zaten çalışıyor (test 9d, prod 33d), ama tracing path canlı yük altında doğrulanmadı. R11 risk: bir servis tracing'i açtığında (a) Tempo refused-span artışı, (b) servisin export latency'si ana request path'ini geciktirir, (c) span volume Tempo storage'ı patlatır.

## Preflight — canary apply ÖNCESI

5 dakikalık preflight, runbook tetikleyici servisin uygulanmasından önce çalışır:

1. **Tempo pod health**
   ```bash
   bash scripts/ops/check-tempo-canary.sh test
   # exit 0 = Tempo /ready + 4317/4318 reachable + (opsiyonel) span ingest probe
   ```
2. **Tempo alert silence check**
   ```bash
   # TempoDown + TempoOTLPIngestErrors alert'leri OFF olmalı
   kubectl --context k3d-test -n monitoring exec sts/prometheus-kube-prometheus-stack-prometheus -c prometheus -- \
     wget -qO- 'http://localhost:9090/api/v1/alerts' | \
     jq -r '.data.alerts[] | select(.labels.risk=="R11") | "\(.state) \(.labels.alertname)"'
   # boş çıktı (no firing R11 alerts) gerekli
   ```
3. **Baseline cardinality snapshot** (R16 PR1 hazırlığı)
   ```bash
   kubectl --context k3d-test -n monitoring exec sts/prometheus-kube-prometheus-stack-prometheus -c prometheus -- \
     wget -qO- 'http://localhost:9090/api/v1/query?query=cardinality:series:total' | jq '.data.result[0].value[1]'
   # Sayıyı not al → canary apply sonrası diff alır
   ```

Preflight'ta herhangi bir kapı kırmızıysa **canary apply başlatma**. Önce ilgili sorunu kapat (Tempo restart, RuleSelector match, vb.).

## Canary apply — tek servis (R11 PR2 scope, bu runbook bunu yönlendirir)

Adımlar:

1. **Hedef servisi seç**: PR2 ilk hedef `notification-orchestrator` (OTLP HTTP 4318 client zaten yorumlu hazır, netpol egress allow var).
2. **Patch overlay**:
   ```bash
   # kustomize/overlays/test/notification-orchestrator-tracing-canary.yaml
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: notification-orchestrator-config
   data:
     MANAGEMENT_TRACING_ENABLED: "true"
     MANAGEMENT_TRACING_SAMPLING_PROBABILITY: "0.1"  # %10 sampling — Codex önerisi: tam zenith değil
     MANAGEMENT_OTLP_TRACING_ENDPOINT: "http://tempo.monitoring.svc.cluster.local:4318/v1/traces"
   ```
3. **Apply**:
   ```bash
   kubectl --context k3d-test -n platform-test apply -f kustomize/overlays/test/notification-orchestrator-tracing-canary.yaml
   kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
   kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator --timeout=180s
   ```
4. **5-10 dakika smoke**:
   ```bash
   # a. Pod up + envFrom pickup verified
   kubectl --context k3d-test -n platform-test exec deploy/notification-orchestrator -- env | grep MANAGEMENT_TRACING_ENABLED
   # expected: MANAGEMENT_TRACING_ENABLED=true
   
   # b. Span ingest (smoke script PR1)
   bash scripts/ops/check-tempo-canary.sh test
   
   # c. Alert state — TempoOTLPIngestErrors firing OLMAMALI
   kubectl --context k3d-test -n monitoring exec sts/prometheus-kube-prometheus-stack-prometheus -c prometheus -- \
     wget -qO- 'http://localhost:9090/api/v1/alerts' | \
     jq -r '.data.alerts[] | select(.labels.risk=="R11" and .state!="inactive") | .labels.alertname'
   # boş olmalı
   
   # d. Service own metrics (p99 latency, error rate) regression check
   #    İlgili Grafana dashboard panel'ine bak; baseline'a göre %20+ regression varsa rollback
   ```

## Acceptance — canary GREEN demek için

| Kapı | Geçer | Geçmez |
|---|---|---|
| Tempo `/ready` | 200 | 5xx veya timeout → rollback |
| `tempo_receiver_refused_spans_total` 10m delta | 0 | > 0 → rollback |
| Canary servis pod state | `Running` + envFrom doğru | `CrashLoopBackOff` veya envFrom mismatch → rollback |
| Canary servis p99 latency 10m | baseline ±%20 | %20+ regression → rollback |
| Cardinality delta (R16 PR1) | < %5 artış | > %5 artış → rollback (PR3 sample_limit'e kadar) |

Tüm 5 kapı yeşilse 30 dakika daha gözlemle; hâlâ yeşilse PR2 acceptance complete kabul. Aksi takdirde aşağıdaki rollback.

## Rollback — canary RED durumunda

1. **Hızlı flip-back** (5 dakika):
   ```bash
   # Patch'i kaldır
   kubectl --context k3d-test -n platform-test delete configmap notification-orchestrator-config-canary 2>/dev/null || true
   # Base config'i tekrar uygula
   kubectl --context k3d-test -n platform-test apply -k kustomize/overlays/test/
   kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
   kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator --timeout=180s
   ```
2. **Verify rollback**:
   ```bash
   kubectl --context k3d-test -n platform-test exec deploy/notification-orchestrator -- env | grep MANAGEMENT_TRACING_ENABLED
   # expected: MANAGEMENT_TRACING_ENABLED=false (base ConfigMap kazanır)
   ```
3. **Tempo cleanup** (opsiyonel):
   - Tempo storage rotation 24-48h olduğu için canary trace'leri otomatik düşer; aktif silme gerekmez.
4. **Incident review**:
   - Hangi smoke kapısı kırıldı?
   - Span volume, refused count, latency delta sayılarını kayıt al.
   - Sebep canary servise özgü mü, yoksa Tempo path'ine mi? Sebepe göre R11 PR3'ün scope'unu daralt.

## Bağlı PR'lar

- **R11 PR1 (bu PR)**: 2 alert (TempoDown + TempoOTLPIngestErrors) + bu runbook + smoke script `scripts/ops/check-tempo-canary.sh`. Code change yok; observability + ops dokümantasyonu.
- **R11 PR2** (sonraki): notification-orchestrator single-service canary apply (test cluster only). Acceptance: 5 kapı GREEN + 30dk soak.
- **R11 PR3** (sonraki): servis-by-servis incremental rollout (api-gateway, then permission-service, then …). Her servis için preflight + canary + acceptance + soak. Cluster-wide flag flip YASAK — Codex 019e4448 Q6.

## Alert tablosu

| Alert | Eşik | Severity | Sebep |
|---|---|---|---|
| `TempoDown` | `up{job=~"tempo|tempo-.+"} == 0 for 10m` | warning | Tempo pod / scrape sorunu — canary açma |
| `TempoOTLPIngestErrors` | `increase(tempo_receiver_refused_spans_total[10m]) > 0 for 5m` | warning | OTLP receiver span reddediyor; canary path bozuldu |

Pre-existing PrometheusRule path: `kustomize/base/monitoring/tempo-health-rule.yaml`. Label `release: kube-prometheus-stack` (kube-prometheus-stack ruleSelector matchLabels gerekiyor).

## Cross-AI audit kayıt

- Plan-time: Codex thread `019e4448-e90a-7472-9e8c-d287c0fa7970` REVISE → Alt-B AGREE
- Implementer Claude / Reviewer Codex — HARD RULE provider-level uyumlu
