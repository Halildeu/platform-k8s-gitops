# ADR-0026 — Observability Federation Phased Adoption (M7 T4.3.8 + R16)

> **Status**: ACCEPTED 2026-05-22 (Codex thread `019e4ee7` plan-time AGREE — Anthropic Claude implementer, OpenAI Codex reviewer; cross-AI provider-different per HARD RULE)
>
> **Sub-faz**: 23.8 (observability) — M7 T4.3.8 closure scope re-baseline
>
> **Risk**: R16 Cross-cluster Prometheus federation cardinality explosion (design-managed)
>
> **Supersedes**: implicit "production cross-cluster federation as M7 closure DoD" interpretation in earlier sprint-plan T4.3.8 wording

## 1. Bağlam (ADR-0002 §3.8 ile reconciled — Codex 019e4ef4 P1 #1 absorb)

Faz 23.8 M7 T4.3 observability closure scope'unda T4.3.8 maddesi "cross-cluster Prometheus federation" olarak listelendi (R16 mitigation). **Mevcut topoloji ADR-0002 §3.8 authoritative** (bu ADR-0026 iter-1'de hatalı şekilde "her cluster bağımsız" ifadesi kullandı — Codex 019e4ef4 P1 #1 finding düzeltildi):

- **2 k3d cluster** (test + prod) tek staging-sw host'unda
- **Prod cluster** = kube-prometheus-stack **ana observability hub**; tek Grafana instance + Alertmanager + Loki/Tempo prod-only (initial scope)
- **Test cluster** = lightweight scrape agent (kube-state-metrics + node-exporter + ingress + ESO); **Grafana/Alertmanager/Loki DISABLED** (`helm-values/kube-prometheus-stack/values-test.yaml`); test Prometheus `remote_write` → prod (PR-NEXT-5 endpoint configuration pending per values-test.yaml comment)
- Grafana dashboard'lar `cluster=test|prod` label ile ayrım yapar (tek Grafana, multi-cluster view)
- Tempo OTLP runtime path notification-orchestrator için **prod cluster'da LIVE** (PR #934 sha-f40aa82 absorb); test cluster traces nice-to-have prod-only initial
- Per-tenant Grafana dashboard MERGED (PR #951 + B.1 org_id Counter Tag retrofit PR #289)

**M7 iter-1 implikasyonu** (Codex 019e4ef4 P1 #1 audit): 2-cluster topology'sinde **remote_write zaten centralized metric ingest sağlar** — yeni "federation" runtime gerekmez. R16 "cross-cluster federation cardinality" riski **remote_write series-cardinality** olarak yeniden okunur (test→prod remoteWrite ile prod hub'da biriken serialer için budget). Federation pattern yalnız **Faz 24+/M8 multi-cluster ramp** (>2 cluster, dış tenant) trigger sonrası anlam kazanır.

M8 multi-tenant ramp hedefi (Faz 24+ scope): dış müşteri tenant'lar onboarding; cluster sayısı 2 → 5-20 ramp. T4.3.8 "production cross-cluster federation" yorumu **M7 closure DoD**'una konursa M8 platform geçişi M7'ye absorbe olur → overengineering riski.

## 2. Karar

T4.3.8 ölçeği **iki faza ayrılır**:

### 2.1 M7 (Faz 23.8 closure) — design artifact + R16 acceptance criteria + non-applied future scaffold

> **Codex 019e4ef4 P2 #3 absorb**: cardinality budget consistency düzeltildi — recording rules ≤ 5K (önceki "≤ 10K" hatalı); total central federation hard cap ≤ 10K (recording 5K + up/ALERTS 1K + safety headroom 4K).

| Eleman | Karar |
|---|---|
| Mevcut state | ADR-0002 §3.8 remote_write topology (test→prod hub); **runtime federation gerekmez** M7 iter-1'de |
| M7 deliverable | **Design artifact** (bu ADR + RB-observability-federation-rollout + non-applied scaffold) + R16 acceptance criteria; runtime federation **YOK** |
| Pattern (Faz 24+ aday) | Bounded Prometheus federation operator-only — central Prometheus yalnız seçilmiş recording rule + düşük cardinality metrikleri `/federate` ile çeker |
| Boundary (Faz 24+ aday) | Operator-only; tenant self-service değil |
| Scrape allowlist (match[]) | notify SLO/dispatch/org-boundary recording rules, `up`, alert state; raw container/kube series **hariç** |
| Mandatory labels | `cluster`, `environment`, `tenant_source`; `org_id` yalnız sorgu filtresi (güvenlik boundary'si **değil**) |
| Cardinality budget (per §6.1) | Recording rules ≤ 5K + `up`/ALERTS ≤ 1K + safety headroom ≤ 4K = total hard cap **≤ 10K**; warning threshold 8K (alert) |
| Production wiring | ArgoCD root'a bağlanmaz; scaffold `docs/scaffolds/` altında **non-applied YAML** olarak kalır; runtime apply Faz 24+/M8 trigger sonrası |
| Acceptance (M7 closure) | Plan-time ADR (bu doküman) + R16 budget/rollback + non-applied scaffold + ADR-0002 §3.8 reconciliation + Tempo/Loki policy + M8 operator acceptance bullets (§3.3 + §4 future column) |

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

### 3.1 Tempo (M7 LIVE durumda — prod cluster)

Mevcut runtime path: `application → in-cluster OTLP endpoint → prod cluster Tempo`. ADR-0002 §3.8 prod-only initial scope (test cluster traces nice-to-have, deferred). **M7 closure'da değişmez**.

Faz 24+ scale pattern (ADR aday yapı):
- `application → in-cluster OpenTelemetry Collector / Grafana Alloy → central Tempo distributor`
- Collector cluster + tenant attribute inject + sampling + redaction
- App direct-to-central Tempo OTLP **YASAK** (central outage coupling + tenant label spoof riski)

### 3.3 M8 Operator Acceptance Criteria (Codex 019e4ef4 P2 #5 absorb)

Faz 24+/M8 trigger sonrası federation runtime aktivasyonu için operator gate'leri:

- [ ] Central OTLP egress: application pod'ları central Tempo endpoint'e doğrudan erişemez (NetworkPolicy egress block + DNS allowlist)
- [ ] Collector/Alloy ingestion: trusted cluster registration + tenant identity attribute inject (`tenant_id` collector-side enforce; app-side label override **YASAK**)
- [ ] App-supplied `org_id` label: collector + remote_write gateway tarafından `overwrite_with_trusted` veya `reject_on_mismatch` policy ile validate edilir
- [ ] Tenant datasource isolation: Grafana org/team/folder per-tenant + datasource credential boundary (Mimir tenant header veya equivalent)
- [ ] Break-glass datasource: operator-only, audited (Grafana audit log + datasource access trail), tenant-facing dashboard'da kullanılmaz
- [ ] Redaction policy: PII labels (`recipient_hash`, `message_id`, `email`, `mailbox`, `domain`, `user_id`, `session_id`) `metric_relabel_configs labeldrop` enforce edilir; collector-side string redaction integration test PASS
- [ ] Sampling: head/tail sampling cost-bounded; tenant per-second budget belirli; ihlal alarm

### 3.2 Loki

| Faz | Pattern |
|---|---|
| **M7** | Logs **local** (her cluster kendi Loki) |
| **Operator view** | Grafana per-cluster Loki datasource; central metric/trace → local log link |
| **Faz 24+** | Central Loki sadece redacted + alert-correlated + audit/security; full pod-log centralization PII + retention + storage policy belirleyene kadar **DEFER** |

## 4. Multi-Tenancy Boundary (M8 hazırlık + operator acceptance criteria)

> **Codex 019e4ef4 P2 #6 absorb**: aşağıdaki table M7 design guardrail iken Faz 24+/M8 trigger sonrası operator acceptance criteria'ya dönüştürülebilir aksiyon listesi olarak okunur (§3.3 ile birlikte).

| Kural | Status M7 | Faz 24+/M8 acceptance |
|---|---|---|
| `org_id` metric label = security boundary? | **NO** — sadece observability semantics | NO; Grafana variable da NO; **acceptance gate**: org_id label spoofing attempt scenario integration test PASS |
| Tenant isolation katmanı | yok (operator-only) | Mimir/Loki/Tempo tenant header + gateway-enforced; **acceptance gate**: cross-tenant query reject HTTP 403 + audit row |
| Grafana org/team/folder | tek org | tenant-scoped datasource + folder model; **acceptance gate**: tenant A user cannot read tenant B folder per RBAC |
| Collector/remote_write gateway | yok | trusted cluster registration + tenant identity inject; user/app supplied `org_id` overwrite veya reject; **acceptance gate**: app pod manipulation scenario test (POD spec'te `org_id` label inject) collector tarafından override edilir |
| Operator break-glass | tek datasource | ayrı, audited, tenant-facing değil; **acceptance gate**: break-glass access audit log row + alerting |
| Metric relabel allowlist | scrape rule whitelist | merkezi ingest öncesi PII + cardinality drop; **acceptance gate**: synthetic PII label injection scenario `metric_relabel_configs` drop'u verify eder |
| Redaction/sampling | yok | collector-side redaction; head/tail sampling cost-bounded; **acceptance gate**: per-tenant sample budget exceed → backpressure + alert |

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

### 6.2 Kill-switch (Codex 019e4ef4 P1 #2 absorb — kube-prometheus-stack source-accurate)

> **Authoritative kill-switch**: **helm-values rollback** (declarative; GitOps audit trail içinde). Imperative `kubectl patch` Prometheus CR pattern kube-prometheus-stack için **reliable değil** (Helm chart Prometheus CR overwrites declarative state on next reconcile).

**Authoritative (Faz 24+ aktivasyon sonrası)**:

```bash
# 1. helm-values/kube-prometheus-stack/values-prod.yaml içinde
#    prometheus.prometheusSpec.additionalScrapeConfigs entry'sini sil
#    (veya additionalScrapeConfigsSecret reference'ı kaldır)
# 2. PR aç + merge
# 3. helm upgrade kube-prometheus-stack (manual sync per ADR-0002 §3.7 prod auto-sync MANUAL)
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring -f helm-values/kube-prometheus-stack/values-prod.yaml
# 4. Prometheus operator detect new spec, reconcile additionalScrapeConfigs (no manual reload needed)
# 5. Verify:
kubectl -n monitoring get prometheus kube-prometheus-stack-prometheus -o jsonpath='{.spec.additionalScrapeConfigs}'
# Beklenen: empty / not present
```

**Imperative emergency fallback** (use ONLY during outage with operator awareness; Helm reconcile drift olabilir):

```bash
# Prometheus CR'ın actual name (kube-prometheus-stack default release name)
# Doğrula:
kubectl -n monitoring get prometheus -o name
# Beklenen: prometheus.monitoring.coreos.com/kube-prometheus-stack-prometheus (veya release-name'a göre)

# additionalScrapeConfigsSecret reference geçici kaldır:
kubectl -n monitoring patch prometheus kube-prometheus-stack-prometheus \
  --type=json -p='[{"op":"remove","path":"/spec/additionalScrapeConfigs"}]'

# UYARI: bir sonraki ArgoCD/helm sync bu değişikliği overwrite eder.
# Acil durumda kullanılır; kalıcı kill-switch yukarıdaki helm-values yolu.
```

**Reload behavior**: Prometheus Operator additionalScrapeConfigs değişimini otomatik detect eder + Prometheus pod'a `/-/reload` HTTP signal gönderir (~30s within). Manual restart **gerekmez**.

**Verification queries** (kill-switch sonrası):

```promql
# Federation series count (kill-switch sonrası 0 olmalı)
sum(scrape_samples_scraped{job=~"central-federate-.*"})

# additionalScrapeConfigs job'ları aktif mı?
up{job=~"central-federate-.*"}
```

### 6.3 Rollback (M7 iter-1 → no federation)

Scaffold non-applied olduğu için M7 iter-1 fail durumunda rollback **YOK** (nothing to roll back). Faz 24+ aktif deployment'a geçildiğinde Thanos/Mimir migration için ayrı rollback planı ADR aday.

## 7. Acceptance Criteria (M7 T4.3.8 closure)

- [ ] ADR-0026 MERGED (bu doküman)
- [ ] ADR-0002 §3.8 reconciliation: bu ADR'da current topology authoritative ADR-0002 referansıyla doğrulandı (Codex 019e4ef4 P1 #1 absorb)
- [ ] `docs/notify/risk-register.md` R16 row "design-managed" status'a güncellendi + budget/rollback kriterleri eklendi
- [ ] `docs/notify/sprint-plan.md` T4.3.8 wording "production federation" → "plan-time federation design + safe scaffold" güncellendi; **design artifact only** scope açık (runtime federation Faz 24+/M8 — Codex 019e4ef4 P2 #5 absorb)
- [ ] `docs/runbooks/RB-observability-federation-rollout.md` MERGED (operator runbook — topology, validation queries, cardinality budget, kill-switch helm-values authoritative, rollback, non-goals)
- [ ] Non-applied scaffold dosyası `docs/scaffolds/` altında (M7'de wire EDİLMEZ) — `docs/scaffolds/` kustomize tree DIŞINDA (Codex 019e4ef4 P3 #8 invariant)
- [ ] M7 closure DoD'unda federation **blocker DEĞİL** (Codex 019e4ee7 verdict `blocker_for_m7_closure: false`)
- [ ] Cardinality budget §6.1 consistent: recording rules ≤ 5K + up/ALERTS ≤ 1K + headroom ≤ 4K = total hard cap **≤ 10K** (Codex 019e4ef4 P2 #3 absorb — eski §2.1 "≤ 10K recording rules" wording düzeltildi)
- [ ] Kill-switch §6.2 **helm-values rollback authoritative**; imperative emergency fallback documented (Codex 019e4ef4 P1 #2 absorb)
- [ ] M8 operator acceptance bullets §3.3 + §4 future column eklendi (Codex 019e4ef4 P2 #5 + #6 absorb)

## 8. Non-Goals (M7 scope dışı — Faz 24+/M8)

- Thanos / Mimir / VictoriaMetrics / Grafana Mimir production kurulumu
- Central Loki ingest (full pod-log)
- Tenant-facing observability dashboard (org_id security boundary)
- Cross-cluster trace continuity production wiring (Tempo central distributor)
- Multi-tenant datasource isolation (Mimir tenant header)

## 9. Çapraz-referans

- **Codex threads**: `019e4ee7` (2026-05-22 plan-time consultation) + `019e4ef4` (2026-05-22 post-impl iter-2 review absorb); provider-different cross-AI Anthropic implementer ↔ OpenAI reviewer per HARD RULE Cross-AI Peer Review
- **ADR-0002 §3.8** (current observability topology — authoritative)
- **Risk**: R16 (`docs/notify/risk-register.md`)
- **Sprint plan**: T4.3.8 row (`docs/notify/sprint-plan.md`)
- **Operator runbook**: `RB-observability-federation-rollout.md` (bu PR'da)
- **Tempo runtime**: PR #934 (sha-f40aa82 absorb — notification-orchestrator OTLP LIVE prod cluster)
- **Per-tenant dashboard**: PR #951 + B.1 PR #289 (org_id Counter Tag retrofit)
- **values-test.yaml** (test cluster lightweight scrape + remote_write to prod)

## 10. Tarih ve İmza

- 2026-05-22 iter-1: ADR created by Anthropic Claude based on Codex `019e4ee7` cross-AI plan-time AGREE
- 2026-05-22 iter-2 absorb: Codex `019e4ef4` post-impl REVISE (P1=2, P2=4, P3=2) absorb — topology reconciliation (ADR-0002 §3.8), kill-switch source-accuracy (helm-values authoritative), cardinality budget consistency, M8 operator acceptance criteria
- Reviewer: Codex threads `019e4ee7` (plan-time) + `019e4ef4` (post-impl) — OpenAI provider, cross-AI provider-different per HARD RULE
- Approver: Halil (kullanıcı — pre-production full authority HARD RULE)
