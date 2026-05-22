# RB-observability-federation-rollout — M7 T4.3.8 Federation Operator Runbook

> **Status**: source-ready 2026-05-22 (Codex 019e4ee7 AGREE — Anthropic/OpenAI cross-AI provider-different)
>
> **Scope**: M7 iter-1 bounded operator-only Prometheus federation; Faz 24+/M8 Thanos-or-Mimir scale path DOCUMENTED (NOT this runbook'un scope'u)
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

M7 iter-1 için **operator-only** federation. İki seçenek:

**Seçenek A (önerilen M7 iter-1)**: Mevcut test cluster Prometheus'u central role'de kullan; production cluster prod-only kalır. Cross-cluster query yalnız test cluster Grafana dashboard üzerinden operator tarafından çekilir.

**Seçenek B (Faz 24+ aday)**: Ayrı 3. cluster (central) provision. M7 scope'unda **YAPMA** — bu Thanos/Mimir kararıyla beraber alınması gereken karar.

## 3. Bounded Federation Setup (Seçenek A — M7 iter-1)

> ⚠️ **NON-APPLIED scaffold**: aşağıdaki YAML şu an `docs/scaffolds/prometheus-federation-additionalScrapeConfigs.example.yaml` altında non-applied referans. Production'a wire ETMEYIN; sadece operator gözden geçirme + cardinality budget verify için.

### 3.1 Scaffold review

`docs/scaffolds/prometheus-federation-additionalScrapeConfigs.example.yaml` aç ve:

1. **Allowlist alanları** — match[] selector'larında high-cardinality (container_*, kube_pod_*, node_*, recipient_hash, message_id) **olmadığını** doğrula
2. **Mandatory labels** — cluster, environment, tenant_source ekli mi
3. **honor_labels=false** — central labels app-side label'ları override eder

### 3.2 Cardinality budget verify (apply ÖNCESİ)

Match[] selector'larıyla mevcut Prometheus üzerinde dry-run sorgu:

```bash
# Federated olacak serileri pre-count
curl -s "http://localhost:9090/federate?match[]={__name__=~\"notify:.+\"}&match[]={__name__=~\"ALERTS\"}" \
  | grep -v '^#' | wc -l
```

Beklenen: ≤ 5000 satır (M7 budget). Aşıyorsa allowlist'i daralt.

### 3.3 Apply (operator karar — M7 iter-1'de YAPILMAZ)

> ❌ **M7 iter-1 scope'unda apply ETMEYIN**. ADR-0026 acceptance criteria: scaffold non-applied + ADR + R16 update + sprint-plan update merge'i yeterli. Apply Faz 24+/M8 trigger sonrası ayrı runbook.

Faz 24+ trigger durumunda apply pattern (referans):

```bash
# additionalScrapeConfigs ConfigMap'ini güncelle
kubectl --context k3d-test -n monitoring create configmap prometheus-additional-scrape-config \
  --from-file=federation.yaml=docs/scaffolds/prometheus-federation-additionalScrapeConfigs.example.yaml \
  --dry-run=client -o yaml | kubectl apply -f -

# Prometheus CR'a referans ekle (helm-values veya direct patch)
# kube-prometheus-stack Helm Prometheus.additionalScrapeConfigsSecret pattern
```

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

## 5. Kill-Switch + Rollback

### 5.1 Acil kill-switch (federation devre dışı)

```bash
# additionalScrapeConfigs'ten federation job'unu boş bırak
kubectl --context k3d-test -n monitoring patch configmap prometheus-additional-scrape-config \
  --type=json -p='[{"op":"replace","path":"/data/federation.yaml","value":"# disabled"}]'

# Prometheus reload (Prometheus operator otomatik reload eder, manuel tetik gerek değil)
```

### 5.2 Rollback (M7 iter-1 fail durumunda)

Non-applied scaffold senaryosunda rollback YOK — uygulanmamış değişim için geri dönüş gerekmez. ADR-0026 revert PR yeterli.

Faz 24+ aktif deployment fail'inde: scrape config rollback + dashboard rollback + tenant query downgrade ayrı runbook'ta belirtilir (Faz 24+ scope).

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

## 9. Faz 24+/M8 Trigger Conditions

Aşağıdakilerden biri gerçekleşirse Thanos/Mimir karar ADR aday açılır (ADR-0026 §2.2):

- Cluster sayısı > 5
- Dış tenant self-service observability gerek
- Retention local Prometheus/Loki/Tempo limit aşımı (>30 gün metric, >7 gün log)
- M8 tenant onboarding plan'ı operator tarafından somut hale gelir

Trigger yokken bu runbook yeterli. M7 closure non-gated.
