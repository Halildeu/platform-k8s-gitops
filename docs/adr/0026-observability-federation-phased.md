# ADR-0026 — Observability Federation Phased Adoption (M7 T4.3.8 + R16)

> **Status**: ACCEPTED 2026-05-22 (Codex thread `019e4ee7` plan-time AGREE — Anthropic Claude implementer, OpenAI Codex reviewer; cross-AI provider-different per HARD RULE)
>
> **Sub-faz**: 23.8 (observability) — M7 T4.3.8 closure scope re-baseline
>
> **Risk**: R16 Cross-cluster Prometheus federation cardinality explosion (design-managed)
>
> **Supersedes**: implicit "production cross-cluster federation as M7 closure DoD" interpretation in earlier sprint-plan T4.3.8 wording

## 1. Bağlam

Faz 23.8 M7 T4.3 observability closure scope'unda T4.3.8 maddesi "cross-cluster Prometheus federation" olarak listelendi (R16 mitigation). Mevcut topoloji:

- **2 k3d cluster** (test + prod) tek staging-sw host'unda; kullanıcı sunucusu
- Prometheus + Loki + Tempo + Grafana + Alertmanager her cluster'da **bağımsız** (federation YOK)
- Tempo OTLP runtime path notification-orchestrator için LIVE (PR #934 sha-f40aa82 absorb)
- Per-tenant Grafana dashboard MERGED (PR #951 + B.1 org_id Counter Tag retrofit PR #289)

M8 multi-tenant ramp hedefi (Faz 24+ scope): dış müşteri tenant'lar onboarding; cluster sayısı 2 → 5-20 ramp. T4.3.8 "production cross-cluster federation" yorumu **M7 closure DoD**'una konursa M8 platform geçişi M7'ye absorbe olur → overengineering riski.

## 2. Karar

T4.3.8 ölçeği **iki faza ayrılır**:

### 2.1 M7 (Faz 23.8 closure) — bounded operator-only design + non-applied scaffold

| Eleman | Karar |
|---|---|
| Pattern | **Bounded Prometheus federation operator-only** — central Prometheus yalnız seçilmiş recording rule + düşük cardinality metrikleri `/federate` ile çeker |
| Boundary | Operator-only; tenant self-service değil |
| Scrape allowlist (match[]) | notify SLO/dispatch/org-boundary recording rules, `up`, alert state; raw container/kube series **hariç** |
| Mandatory labels | `cluster`, `environment`, `tenant_source`; `org_id` yalnız sorgu filtresi (güvenlik boundary'si **değil**) |
| Cardinality budget | Recording rule serisi ≤ 10K (whitelist'li); kill-switch + rollback dokümante |
| Production wiring | ArgoCD root'a bağlanmaz; scaffold `docs/scaffolds/` altında non-applied YAML olarak kalır |
| Acceptance | Plan-time ADR (bu doküman) + R16 budget/rollback + non-applied scaffold + Tempo/Loki policy notu |

### 2.2 Faz 24+ / M8 (multi-tenant ramp) — tenancy-enforced central observability

Trigger koşulları (biri yeterli):

- Cluster sayısı > 5
- Dış tenant self-service observability gerek
- Retention local Prometheus/Loki/Tempo limitlerini aşar
- M8 tenant onboarding planı somut

Karar matrisi (henüz seçim YOK — Faz 24 plan-time):

| Topoloji | Cost | Complexity | Scale | Tenant isolation | Prometheus continuity |
|---|---|---|---|---|---|
| **Prometheus federation** (bu ADR'ın M7 iter-1 seçimi) | en düşük | en düşük | 2-5 cluster + curated metrics | zayıf (operator-only) | tam |
| **Thanos** (sidecar/receiver + querier) | orta-yüksek | orta-yüksek | 5-20 cluster global query + HA dedupe | orta (extra gateway + Grafana discipline) | tam |
| **VictoriaMetrics cluster** | düşük runtime | farklı ops yüzeyi + MetricsQL | 5-20+ | account-style tenancy daha güçlü | platform pivot |
| **Grafana Mimir** | yüksek | yüksek + object-storage dep | büyük | en güçlü multi-tenant fit | remote_write native |

Default tercih (Codex 019e4ee7 verdict): **Thanos** (Prometheus continuity priority). Tenant strict requirement varsa **Mimir**.

## 3. Tempo + Loki Policy

### 3.1 Tempo (M7 LIVE durumda)

Mevcut runtime path: `application → in-cluster OTLP endpoint → Tempo`. **M7 closure'da değişmez**.

Faz 24+ scale pattern (ADR aday yapı):
- `application → in-cluster OpenTelemetry Collector / Grafana Alloy → central Tempo distributor`
- Collector cluster + tenant attribute inject + sampling + redaction
- App direct-to-central Tempo OTLP **YASAK** (central outage coupling + tenant label spoof riski)

### 3.2 Loki

| Faz | Pattern |
|---|---|
| **M7** | Logs **local** (her cluster kendi Loki) |
| **Operator view** | Grafana per-cluster Loki datasource; central metric/trace → local log link |
| **Faz 24+** | Central Loki sadece redacted + alert-correlated + audit/security; full pod-log centralization PII + retention + storage policy belirleyene kadar **DEFER** |

## 4. Multi-Tenancy Boundary (M8 hazırlık)

| Kural | Status M7 | Faz 24+/M8 |
|---|---|---|
| `org_id` metric label = security boundary? | **NO** — sadece observability semantics | NO; Grafana variable da NO |
| Tenant isolation katmanı | yok (operator-only) | Mimir/Loki/Tempo tenant header + gateway-enforced |
| Grafana org/team/folder | tek org | tenant-scoped datasource + folder model |
| Collector/remote_write gateway | yok | trusted cluster registration + tenant identity inject; user/app supplied `org_id` overwrite veya reject |
| Operator break-glass | tek datasource | ayrı, audited, tenant-facing değil |
| Metric relabel allowlist | scrape rule whitelist | merkezi ingest öncesi PII + cardinality drop |

## 5. Non-applied Scaffold (örnek)

Aşağıdaki scaffold **ArgoCD root'a bağlanmaz**, sadece referans pattern:

```yaml
# docs/scaffolds/prometheus-federation-additionalScrapeConfigs.example.yaml
# NON-APPLIED — reference pattern only. Do NOT wire into kustomize root.
- job_name: 'central-federate-test-cluster'
  honor_labels: false   # central labels (cluster, environment, tenant_source) win
  metrics_path: '/federate'
  params:
    match[]:
      # Recording rule allowlist (low cardinality, derived series only)
      - '{__name__=~"notify:dispatch:outcome:.+"}'
      - '{__name__=~"notify:intent:terminated:.+"}'
      - '{__name__=~"notify:abuse:blocked:.+"}'
      - '{__name__="up", job=~"notification-orchestrator.+"}'
      - '{__name__=~"ALERTS|ALERTS_FOR_STATE"}'
  static_configs:
    - targets: ['test-prometheus.platform-test.svc.cluster.local:9090']
      labels:
        cluster: 'k3d-test'
        environment: 'test'
        tenant_source: 'internal'
  relabel_configs:
    # Drop high-cardinality labels at central ingest
    - source_labels: [__name__]
      regex: '(container_|kube_pod_|node_).+'
      action: drop
  metric_relabel_configs:
    # Strip recipient_hash, message_id, email, mailbox, domain labels if present
    - regex: '(recipient_hash|message_id|email|mailbox|domain)'
      action: labeldrop
```

## 6. Cardinality Budget + Kill-switch + Rollback

### 6.1 Budget

| Series category | Budget M7 iter-1 |
|---|---|
| Recording rules (federated) | ≤ 5K |
| `up` + ALERTS | ≤ 1K |
| Total central federation series | **≤ 10K** |
| Grafana datasource series | Local Prometheus (yine cluster-local) — federation yalnız operator dashboard'lar için |

### 6.2 Kill-switch

```bash
# Central Prometheus additionalScrapeConfigs ConfigMap'ten federation job sil
kubectl -n monitoring patch prometheus central -p '{"spec":{"additionalScrapeConfigs":null}}'

# Veya scrape rule'ı disable et (selector ile):
kubectl -n monitoring annotate prometheus central observability.acik.com/federation=disabled --overwrite
```

### 6.3 Rollback (M7 iter-1 → no federation)

Scaffold non-applied olduğu için M7 iter-1 fail durumunda rollback **YOK** (nothing to roll back). Faz 24+ aktif deployment'a geçildiğinde Thanos/Mimir migration için ayrı rollback planı ADR aday.

## 7. Acceptance Criteria (M7 T4.3.8 closure)

- [ ] ADR-0026 MERGED (bu doküman)
- [ ] `docs/notify/risk-register.md` R16 row "design-managed" status'a güncellendi + budget/rollback kriterleri eklendi
- [ ] `docs/notify/sprint-plan.md` T4.3.8 wording "production federation" → "plan-time federation design + safe scaffold" güncellendi
- [ ] `docs/runbooks/RB-observability-federation-rollout.md` MERGED (operator runbook — topology, validation queries, cardinality budget, kill-switch, rollback, non-goals)
- [ ] Non-applied scaffold dosyası `docs/scaffolds/` altında (M7'de wire EDİLMEZ)
- [ ] M7 closure DoD'unda federation **blocker DEĞİL** (Codex 019e4ee7 verdict `blocker_for_m7_closure: false`)

## 8. Non-Goals (M7 scope dışı — Faz 24+/M8)

- Thanos / Mimir / VictoriaMetrics / Grafana Mimir production kurulumu
- Central Loki ingest (full pod-log)
- Tenant-facing observability dashboard (org_id security boundary)
- Cross-cluster trace continuity production wiring (Tempo central distributor)
- Multi-tenant datasource isolation (Mimir tenant header)

## 9. Çapraz-referans

- **Codex thread**: `019e4ee7` (2026-05-22 plan-time consultation; provider-different cross-AI Anthropic implementer ↔ OpenAI reviewer per HARD RULE Cross-AI Peer Review)
- **Risk**: R16 (`docs/notify/risk-register.md`)
- **Sprint plan**: T4.3.8 row (`docs/notify/sprint-plan.md`)
- **Operator runbook**: `RB-observability-federation-rollout.md` (bu PR'da)
- **Tempo runtime**: PR #934 (sha-f40aa82 absorb — notification-orchestrator OTLP LIVE)
- **Per-tenant dashboard**: PR #951 + B.1 PR #289 (org_id Counter Tag retrofit)

## 10. Tarih ve İmza

- 2026-05-22: ADR created by Anthropic Claude based on Codex `019e4ee7` cross-AI plan-time AGREE
- Reviewer: Codex thread `019e4ee7` (OpenAI provider — cross-AI provider-different per HARD RULE)
- Approver: Halil (kullanıcı — pre-production full authority HARD RULE)
