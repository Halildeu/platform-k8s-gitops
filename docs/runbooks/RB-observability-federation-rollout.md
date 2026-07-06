# RB-observability-federation-rollout — M7 T4.3.8 Federation Operator Runbook

> **Status**: source-ready 2026-05-22 iter-2 (Codex 019e4ee7 plan-time AGREE + 019e4ef4 post-impl REVISE absorb — Anthropic/OpenAI cross-AI provider-different)
>
> **Scope**: M7 iter-1 **design artifact only** (runtime federation YOK — ADR-0002 §3.8 remote_write topology zaten centralized); Faz 24+/M8 Thanos-or-Mimir scale path DOCUMENTED (NOT this runbook'un runtime scope'u)
>
> **Topology authority**: ADR-0002 §3.8 (prod = observability hub; test = lightweight scrape + remote_write to prod)
>
> **ADR referansı**: [ADR-0026 Observability Federation Phased Adoption](../adr/0026-observability-federation-phased.md)
>
> **Risk**: R16 (`docs/notify/risk-register.md`)

## 1. Bağlam + Non-Goals

### 1.1 Bu runbook NE içerir

- Bounded Prometheus federation pattern (`/federate` allowlist) operator-only deploy yöntemi
- Cardinality budget (≤ 10K central series) verification
- Validation query örnekleri (recording rule scrape doğrulama)
- Kill-switch + rollback adımları
- Multi-tenancy hard limits (tenant self-service değil)

### 1.2 Bu runbook NE içermez (Faz 24+ scope)

- Thanos / Mimir / VictoriaMetrics production kurulumu
- Central Loki ingest
- Cross-cluster Tempo distributor
- Tenant-facing observability (Grafana org/folder per-tenant + datasource isolation)
- Mass logs federation

## 2. Önkoşullar (Preflight)

### 2.1 Cluster topology doğrula

```bash
# 2 cluster mı (test + prod)?
ssh halil@staging-sw 'kubectl --context k3d-test config current-context ; kubectl --context k3d-prod config current-context'
```

Beklenen: `k3d-test` + `k3d-prod` döner. M7 iter-1 sadece bu 2 cluster için bounded federation.

### 2.2 Recording rule allowlist hazır

`/api/v1/rules` ile mevcut recording rule listesi alın:

```bash
ssh halil@staging-sw 'kubectl --context k3d-test -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090 &
sleep 2
curl -s http://localhost:9090/api/v1/rules | jq -r ".data.groups[].rules[] | select(.type==\"recording\") | .name"
kill %1'
```

Beklenen: `notify:dispatch:outcome:*`, `notify:intent:terminated:*`, `notify:abuse:blocked:*` gibi düşük cardinality serialer.

### 2.3 Central Prometheus instance gerek mi?

> **Codex 019e4ef4 P1 #1 absorb**: M7 iter-1'de **runtime federation gerek YOK** — ADR-0002 §3.8 mevcut remote_write topology zaten test→prod centralized metric ingest sağlar. Bu §2.3 ve §3 aşağısı **Faz 24+/M8 trigger sonrası referans** (M7 iter-1'de YAPILMAZ).

**Mevcut M7 topology** (ADR-0002 §3.8 authoritative):
- Prod cluster kube-prometheus-stack = ana observability hub (tek Grafana + Alertmanager + Loki/Tempo)
- Test cluster kube-prometheus-stack lightweight = remote_write → prod (`prometheus-prod-remote-write-receiver.platform-prod.svc.cluster.local:9090/api/v1/write` placeholder — values-test.yaml PR-NEXT-5 endpoint configuration pending)
- Cross-cluster query: Grafana dashboard `cluster=test|prod` label filtering ile yapılır (federation **gerekmez**)

**Faz 24+/M8 trigger sonrası federation pattern seçenekleri** (M7 iter-1'de aktif EDİLMEZ):

**Seçenek A (Faz 24+ aday)**: Mevcut prod cluster Prometheus'u central role'de pekiştir; ek tenant cluster'lardan `/federate` ile curated metric scrape. ADR-0026 §2.2 Prometheus federation pattern.

**Seçenek B (Faz 24+ aday)**: Thanos sidecar/receiver veya Grafana Mimir cluster provision. ADR-0026 §2.2 karar matrisi.

M7 closure içinde **hiçbir seçenek apply edilmez** — sadece design artifact (bu runbook + ADR + non-applied scaffold).

## 3. Bounded Federation Setup (Seçenek A — M7 iter-1)

> ⚠️ **NON-APPLIED scaffold**: aşağıdaki YAML şu an `docs/scaffolds/prometheus-federation-additionalScrapeConfigs.example.yaml` altında non-applied referans. Production'a wire ETMEYIN; sadece operator gözden geçirme + cardinality budget verify için.

### 3.1 Scaffold review

`docs/scaffolds/prometheus-federation-additionalScrapeConfigs.example.yaml` aç ve:

1. **Allowlist alanları** — match[] selector'larında high-cardinality (container_*, kube_pod_*, node_*, recipient_hash, message_id) **olmadığını** doğrula
2. **Mandatory labels** — cluster, environment, tenant_source ekli mi
3. **honor_labels=false** — central labels app-side label'ları override eder

### 3.2 Cardinality budget verify (Faz 24+ apply ÖNCESİ — M7 iter-1'de bilgi amaçlı)

> **Codex 019e4ef4 P2 #4 absorb**: pre-count sorgusu scaffold'un exact match[] selector'larıyla eşleşmeli — scaffold'da 6 selector var (notify:dispatch:outcome:.+, notify:intent:terminated:.+, notify:abuse:blocked:.+, notify:kvkk:erasure:.+, up notification-orchestrator, ALERTS|ALERTS_FOR_STATE), bu sorgu da o setleri ayrı ayrı sayar.

Match[] selector'larıyla mevcut Prometheus üzerinde dry-run sorgu (scaffold ile %100 hizalı):

```bash
# Federated olacak serileri pre-count (scaffold match[] selectors exactly)
SELECTORS=(
  '{__name__=~"notify:dispatch:outcome:.+"}'
  '{__name__=~"notify:intent:terminated:.+"}'
  '{__name__=~"notify:abuse:blocked:.+"}'
  '{__name__=~"notify:kvkk:erasure:.+"}'
  '{__name__="up", job=~"notification-orchestrator.+"}'
  '{__name__=~"ALERTS|ALERTS_FOR_STATE"}'
)
QUERY_PARAMS=""
for sel in "${SELECTORS[@]}"; do
  ENC=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$sel'''))")
  QUERY_PARAMS+="&match[]=$ENC"
done
# Pre-relabel scraped sample count (per source cluster)
curl -s "http://localhost:9090/federate?$(echo "$QUERY_PARAMS" | sed 's/^&//')" \
  | grep -v '^#' | wc -l
```

**Beklenen budgets** (ADR-0026 §6.1 ile %100 hizalı):
- Recording rules (notify:.+) ≤ **5K** satır (per source cluster)
- `up{job=~"notification-orchestrator.+"}` + `ALERTS`/`ALERTS_FOR_STATE` ≤ **1K** satır
- Safety headroom ≤ **4K** (cluster growth + new recording rules)
- **Total hard cap ≤ 10K** central series; warning threshold 8K (alert)

Aşıyorsa allowlist'i daralt (scaffold match[] selector'ları daha spesifik hale getir).

Post-ingest central series count (Faz 24+ apply sonrası):

```promql
# Central federation series toplamı
sum(scrape_samples_scraped{job=~"central-federate-.*"})
```

### 3.3 Apply (Faz 24+/M8 trigger sonrası — M7 iter-1'de YAPILMAZ)

> ❌ **M7 iter-1 scope'unda apply ETMEYIN**. ADR-0026 acceptance criteria: scaffold non-applied + ADR + R16 update + sprint-plan update merge'i yeterli. Apply Faz 24+/M8 trigger sonrası ayrı runbook iter-2 ile yapılır.

Faz 24+ trigger durumunda apply pattern (kube-prometheus-stack source-accurate — Codex 019e4ef4 P1 #2 absorb):

**Authoritative pattern**: helm-values üzerinden `additionalScrapeConfigsSecret` reference (declarative; GitOps audit).

```bash
# 1. Scaffold YAML'i kube-prometheus-stack Secret reference pattern'iyle ekle:
#    helm-values/kube-prometheus-stack/values-prod.yaml içinde
#    prometheus.prometheusSpec.additionalScrapeConfigsSecret reference ekle
#    (kube-prometheus-stack chart Secret-based additionalScrapeConfigs pattern)

# 2. Secret manifest oluştur (örnek):
cat <<'EOF' > /tmp/additional-scrape-config.yaml
apiVersion: v1
kind: Secret
metadata:
  name: prometheus-additional-scrape-config
  namespace: monitoring
type: Opaque
stringData:
  federation.yaml: |
    # Insert content from docs/scaffolds/prometheus-federation-additionalScrapeConfigs.example.yaml
EOF
kubectl --context k3d-prod -n monitoring apply -f /tmp/additional-scrape-config.yaml

# 3. helm-values'i güncelle (PR aç + merge):
# helm-values/kube-prometheus-stack/values-prod.yaml içine:
#   prometheus:
#     prometheusSpec:
#       additionalScrapeConfigs:
#         name: prometheus-additional-scrape-config
#         key: federation.yaml

# 4. helm upgrade (manual sync per ADR-0002 §3.7):
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring -f helm-values/kube-prometheus-stack/values-prod.yaml

# 5. Prometheus operator otomatik reconcile + Prometheus pod'a /-/reload signal
# 6. Verify:
kubectl --context k3d-prod -n monitoring get prometheus kube-prometheus-stack-prometheus \
  -o jsonpath='{.spec.additionalScrapeConfigs}'
# Beklenen: {"name":"prometheus-additional-scrape-config","key":"federation.yaml"}
```

**NOT**: Imperative `kubectl create configmap` veya `kubectl patch prometheus` pattern'leri **reliable değil** — Helm chart Prometheus CR'ı bir sonraki reconcile'da overwrite eder. Authoritative pattern helm-values declarative state.

## 4. Validation Queries

### 4.1 Recording rule scrape doğrulama

```promql
# Cluster label'ı geliyor mu?
notify:dispatch:outcome:5m{cluster="k3d-test"}

# Series sayısı budget içinde mi?
count({cluster=~"k3d-(test|prod)"})

# High-cardinality label varsa drop oldu mu?
{__name__=~"notify:.+"} unless on(__name__) container_*
```

### 4.2 Alert state federation

```promql
# Federated ALERTS — cluster + alertname
ALERTS{cluster=~"k3d-(test|prod)", alertstate="firing"}
```

## 5. Kill-Switch + Rollback (Codex 019e4ef4 P1 #2 absorb)

### 5.1 Authoritative kill-switch (helm-values rollback — declarative)

> **Helm-values rollback = authoritative kill-switch** (GitOps audit trail; reconcile-safe). Imperative `kubectl patch` Prometheus CR pattern kube-prometheus-stack için reliable değil — Helm chart Prometheus CR'ı bir sonraki reconcile'da overwrite eder.

```bash
# 1. helm-values/kube-prometheus-stack/values-prod.yaml içinden
#    prometheus.prometheusSpec.additionalScrapeConfigs entry'sini sil
# 2. PR aç + merge
# 3. helm upgrade (manual sync per ADR-0002 §3.7 prod auto-sync MANUAL):
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring -f helm-values/kube-prometheus-stack/values-prod.yaml
# 4. Prometheus operator detect + reconcile + reload Prometheus pod (~30s)
# 5. Verify:
kubectl --context k3d-prod -n monitoring get prometheus kube-prometheus-stack-prometheus \
  -o jsonpath='{.spec.additionalScrapeConfigs}'
# Beklenen: empty / not present
```

### 5.2 Imperative emergency fallback (outage-only; Helm reconcile drift olabilir)

```bash
# Prometheus CR actual name doğrula:
kubectl --context k3d-prod -n monitoring get prometheus -o name
# Beklenen: prometheus.monitoring.coreos.com/kube-prometheus-stack-prometheus

# additionalScrapeConfigs reference geçici kaldır:
kubectl --context k3d-prod -n monitoring patch prometheus kube-prometheus-stack-prometheus \
  --type=json -p='[{"op":"remove","path":"/spec/additionalScrapeConfigs"}]'

# UYARI: bir sonraki ArgoCD/helm sync bu değişikliği overwrite eder.
# Acil durumda kullanılır; kalıcı kill-switch §5.1 helm-values yolu.
```

### 5.3 Verification queries (kill-switch sonrası)

```promql
# Federation series count (0 olmalı kill-switch sonrası)
sum(scrape_samples_scraped{job=~"central-federate-.*"})

# additionalScrapeConfigs job'ları up mı?
up{job=~"central-federate-.*"}
```

### 5.4 Rollback (M7 iter-1 fail durumunda)

Non-applied scaffold senaryosunda rollback YOK — uygulanmamış değişim için geri dönüş gerekmez. ADR-0026 revert PR yeterli.

Faz 24+ aktif deployment fail'inde: helm-values rollback (§5.1) + dashboard rollback + tenant query downgrade ayrı runbook iter-2'te belirtilir (Faz 24+ scope).

## 6. Cardinality Budget Tracking

| Metric | M7 iter-1 budget | Mevcut | Status |
|---|---|---|---|
| `notify:.+` recording rules | ≤ 5K | tbd (run §2.2) | — |
| `up` + `ALERTS` | ≤ 1K | tbd | — |
| Central federation total | ≤ 10K | 0 (non-applied) | OK |

Per-cluster federation aktive edilirse budget güncellenir. Faz 24+ Thanos/Mimir geçişinde budget yeniden değerlendirilir (object-storage retention coupling).

## 7. Multi-Tenancy Hard Limits (M8 hazırlık)

| Kural | Bu runbook M7 |
|---|---|
| Federation = tenant self-service değil | ✅ operator-only |
| `org_id` label = security boundary değil | ✅ — sadece observability semantics |
| Grafana variable = security boundary değil | ✅ — variable filter, RBAC değil |
| Tenant onboarding bu runbook ile YAPMAYIN | ✅ — Faz 24+ scope |

## 8. Çapraz-referans

- ADR-0026 §1-9 (decision base)
- R16 risk register row (design-managed status, budget criteria)
- T4.3.8 sprint-plan row (plan-time design + safe scaffold)
- Codex thread `019e4ee7` (cross-AI plan-time verdict)
- Tempo runtime LIVE (PR #934 sha-f40aa82)
- Per-tenant Grafana dashboard (PR #951 + B.1 PR #289 org_id retrofit)
- `docs/scaffolds/prometheus-federation-additionalScrapeConfigs.example.yaml` (non-applied scaffold)

## 9. Faz 24+/M8 Trigger Conditions (normalized — Codex 019e4ef4 P3 #7 absorb)

Aşağıdakilerden biri gerçekleşirse Thanos/Mimir karar ADR aday açılır (ADR-0026 §2.2):

- Cluster sayısı > 5
- Dış tenant self-service observability gerek
- Retention local Prometheus/Loki/Tempo limit aşımı: **metric > 30 gün** + **log > 7 gün** + **trace > 7 gün**
- M8 tenant onboarding plan'ı operator tarafından somut hale gelir

> **Note (Codex 019e4ef4 P3 #7)**: retention trigger metric-only değildir; log + trace yükü de operator için karar tetikleyici. ADR-0026 §2.2 + scaffold yaml comment block aynı retention wording'i kullanır.

Trigger yokken bu runbook yeterli. M7 closure non-gated (ADR-0026 §2.1 acceptance criteria).
