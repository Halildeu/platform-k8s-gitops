# PR-V2.1-Ops-B — Status Writer Monotonic Alert PrometheusRule Spike

> **Belge kodu**: `PR-V2.1-Ops-B-spike`
> **Tarih**: 2026-05-14
> **Sprint**: PERF-INIT-V2.1 prod-readiness sub-wave
> **PMD parent**: [PERF-INIT-V2-prod-readiness-v9.1.md](./PERF-INIT-V2-prod-readiness-v9.1.md) §2.7
> **Ops-A dependency**: [PR-V2.1-Ops-A-receiver-selection-spike.md](./PR-V2.1-Ops-A-receiver-selection-spike.md) — receiver attach Ops-A merge sonrası

---

## §1. Amaç

Status CM `frontend-federation-smoke-status` monotonic alert: `failures>0` / `result=FAIL` / `lastFire` stale → **auto-issue** (auto-PR YASAK — Codex tur-2 NARROW absorb). Receiver-attach Ops-A merge sonrası (Slack veya GitHub bridge).

PMD v9.1 §2.7 V2.1-Ops-B DoD:
> PrometheusRule: `failures>0` / `result=FAIL` / `lastFire` stale → **auto-issue**; throttle 6h; issue dedupe/close lifecycle

---

## §2. Pattern Selection (3 option)

Live verify (2026-05-14):
```bash
$ kubectl --context k3d-prod -n monitoring get pod -l app.kubernetes.io/name=prometheus-pushgateway
No resources found in monitoring namespace.
$ kubectl --context k3d-prod -n monitoring get pod -l app.kubernetes.io/name=kube-state-metrics -o jsonpath='{.items[0].spec.containers[0].args}'
["--port=8080","--resources=...,configmaps,..."]
```

| Option | Pattern | Avantaj | Dezavantaj |
|---|---|---|---|
| **A** | **Pushgateway**: CronJob script `failures>0` durumunda direct push → Pushgateway scrape | Standard pattern, multi-source aggregation | **Pushgateway install gerek** (mevcut değil); maintenance + resource overhead + ESO secret + RBAC + cleanup lifecycle |
| **B** | **Custom exporter sidecar**: Go binary ConfigMap watcher → `/metrics` endpoint → ServiceMonitor scrape | Real-time + reactive | Custom code (Codex tur-2 NARROW YASAK); maintenance + image build + provenance |
| **C** | **Annotation-based scrape via kube-state-metrics**: CronJob status writer `.metadata.annotations` da yazsın → `kube_configmap_annotations` otomatik scrape | **No controller install** + no custom binary + D27 upstream-first | Annotation cardinality limit (string sadece, numeric değil); PromQL transformation gerek |

**Tercih**: **Option C** (annotation-based). Sebep:
- Mevcut kube-state-metrics LIVE her iki cluster'da
- `kube_configmap_annotations` metric otomatik available
- Status writer script minimal extension (annotation patch eklemek 5 satır bash)
- D27 upstream-first uyumlu (no external dependency)
- HARD RULE No Fake Work uyumlu (gerçek değer eklenmiş, no facade)

---

## §3. Implementation Contract (Option C)

### §3.1 Status Writer Script Extension

CronJob smoke script (mevcut `kustomize/overlays/{test,prod}/cronjob-federation-smoke.yaml` writer block) PATCH operasyonu genişletilir.

**Annotation key naming**: `frontend-federation-smoke.io/<field>` (Kubernetes annotation FQDN prefix convention; collision-safe).

**Codex `019e26c5` R4 absorb**: CronJob image `curlimages/curl` jq **dependency YOK**. Mevcut shell plain string JSON pattern (PR #568 heredoc → plain interpolation fix) korunur:

```bash
# Tek PATCH ile birleşik (merge patch type) — plain string, no jq
PATCH_PAYLOAD="{\"metadata\":{\"annotations\":{\"frontend-federation-smoke.io/last-fire\":\"$TIMESTAMP\",\"frontend-federation-smoke.io/result\":\"$RESULT\",\"frontend-federation-smoke.io/failures\":\"$FAIL\"}},\"data\":{\"lastFire\":\"$TIMESTAMP\",\"result\":\"$RESULT\",\"failures\":\"$FAIL\"}}"
curl -sS ... -X PATCH --data "$PATCH_PAYLOAD" \
  "$API/api/v1/namespaces/$NS/configmaps/$CM_NAME"
```

### §3.2 PrometheusRule Manifest (Codex `019e26c5` R1+R5 absorb)

`kustomize/base/monitoring/prometheusrule-frontend-federation-smoke.yaml` pattern. **Codex R5 absorb**: kube-prometheus-stack discovery için `release: kube-prometheus-stack` label gerekli (mevcut `rollout-replicaset-crash-rule.yaml` aynı pattern).

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: frontend-federation-smoke-alerts
  namespace: monitoring  # Prometheus discovery namespace
  labels:
    app.kubernetes.io/name: frontend-federation-smoke
    app.kubernetes.io/part-of: platform
    release: kube-prometheus-stack  # Codex R5: discovery contract
    team: perf
spec:
  groups:
    - name: frontend-federation-smoke
      interval: 5m
      rules:
        # 1. failures monotonic — Codex tur-1 PromQL fix: regex numeric pattern (!="0" yerine)
        - alert: PerfFederationSmokeFailing
          expr: |
            kube_configmap_annotations{
              namespace=~"platform-(test|prod)",
              configmap="frontend-federation-smoke-status",
              annotation_frontend_federation_smoke_io_failures=~"[1-9][0-9]*"
            } == 1
          for: 5m
          labels: { severity: warning, team: perf, alert_class: federation-smoke }

        # 2. result=FAIL
        - alert: PerfFederationSmokeResultFail
          expr: |
            kube_configmap_annotations{
              namespace=~"platform-(test|prod)",
              configmap="frontend-federation-smoke-status",
              annotation_frontend_federation_smoke_io_result="FAIL"
            } == 1
          for: 5m
          labels: { severity: critical, team: perf, alert_class: federation-smoke }

        # 3. Codex R1 absorb: stale detect via changes(resourceVersion) + creation guard
        # `kube_configmap_metadata_resource_version` timestamp DEĞİL; changes() rate detector
        - alert: PerfFederationSmokeStale
          expr: |
            (
              max by (cluster, namespace, configmap) (
                changes(kube_configmap_metadata_resource_version{
                  namespace=~"platform-(test|prod)",
                  configmap="frontend-federation-smoke-status"
                }[12h])
              ) == 0
            )
            and on (cluster, namespace, configmap)
            (
              time() - max by (cluster, namespace, configmap) (
                kube_configmap_created{
                  namespace=~"platform-(test|prod)",
                  configmap="frontend-federation-smoke-status"
                }
              ) > 43200
            )
          for: 5m
          labels: { severity: warning, team: perf, alert_class: federation-smoke }

        # 4. Codex R6 absorb: separate absent alert (don't bury in stale)
        - alert: PerfFederationSmokeStatusAbsent
          expr: |
            absent(kube_configmap_annotations{
              namespace=~"platform-(test|prod)",
              configmap="frontend-federation-smoke-status"
            })
          for: 5m
          labels: { severity: critical, team: perf, alert_class: federation-smoke }
```

**Codex R2 absorb — kube-state-metrics annotation allowlist** (helm values delta zorunlu):

```yaml
# helm-values/kube-prometheus-stack/values-{test,prod}.yaml
kube-state-metrics:
  extraArgs:
    - --metric-annotations-allowlist=configmaps=[frontend-federation-smoke.io/last-fire,frontend-federation-smoke.io/result,frontend-federation-smoke.io/failures]
```

**Codex R3 absorb — ArgoCD ignoreDifferences** (data + 3 annotation key):

```yaml
# argocd/applications/platform-{test,prod}.yaml
ignoreDifferences:
  - kind: ConfigMap
    name: frontend-federation-smoke-status
    jsonPointers:
      - /data
      - /metadata/annotations/frontend-federation-smoke.io~1last-fire
      - /metadata/annotations/frontend-federation-smoke.io~1result
      - /metadata/annotations/frontend-federation-smoke.io~1failures
```

### §3.3 AlertManager Route Coupling (Codex R6 absorb)

Ops-A merge sonrası AlertManager `config.route.routes` perf-alerts receiver. **Codex R6**: perf route, prod values broad severity route'larından **ÖNCE** gelmeli (priority routing); yoksa critical perf alarmı genel `alarm-receiver-bridge`'e düşer.

```yaml
- matchers:
    - team = "perf"
    - alert_class = "federation-smoke"
  receiver: 'perf-alerts'  # Ops-A receiver (slack_configs api_url_file)
  group_by: ['cluster', 'namespace', 'alertname', 'alert_class']  # Codex R6
  group_wait: 1m
  group_interval: 5m
  repeat_interval: 6h  # PMD §2.7 throttle
```

### §3.4 Auto-Issue Receiver (post Ops-A) — Codex R6 absorb

`perf-alerts` receiver path:
- **Slack** (Ops-A A2 isolation): `slack_configs` `send_resolved: true` → mesaj **resolved notification** ama **auto-close DEĞİL** (Slack mesaj kalır)
- **GitHub bridge** (Ops-A fallback): `alertmanager-github-receiver` issue dedupe key + resolved → **auto-close action**

**Codex R6 önemli**: Slack-only seçilirse PMD §2.7 "auto-issue dedupe/close lifecycle" şartı **eksik kalır**; bu durumda V2.1 closure #4 **dependency veya owner waiver** olarak explicit yazılmalı. GitHub bridge seçilmesi auto-close lifecycle için gerek.

---

## §4. Dependency Chain (Codex R2+R3+R7 absorb)

| Step | Item | Status | Bağımlılık |
|---|---|:---:|---|
| 0 | **Codex R7 pre-impl gate**: test cluster `uninitialised` triage (CronJob deploy + RBAC + ESO + Argo app diff verify) | ⏳ | Pre-implementation blocker |
| 1 | Status writer annotation extension (CronJob script genişletme; jq YOK) | ⏳ | Implementation PR |
| 2 | PrometheusRule manifest + `release: kube-prometheus-stack` label | ⏳ | Implementation PR |
| 3 | kube-state-metrics annotation allowlist helm values delta (test+prod) | ⏳ | Implementation PR (Codex R2) |
| 4 | ArgoCD ignoreDifferences extension (3 annotation key) | ⏳ | Implementation PR (Codex R3) |
| 5 | AlertManager route + receiver attach | ⏳ | **Ops-A merge sonrası** |
| 6 | Synthetic always-firing PrometheusRule `perf-alerts-test` (route/receiver/Slack 200 OK zincir test) | ⏳ | Adım 5 sonrası |
| 7 | Kontrollü `failures=1` ConfigMap patch (Ops-B PromQL test) — eski CM snapshot + auto-issue noise/dedupe yönetim | ⏳ | Adım 6 sonrası |

**Bu PR scope**: **Spike decision record only** — pattern selection (Option C annotation-based) + implementation contract reference + Codex 7 revision absorb. Implementation **ayrı PR** (Adım 1-4 birleşik + Adım 5-7 Ops-A merge sonrası ayrı PR).

---

## §5. V2.1 Closure Coupling

PMD v9.1 §2.9:

| # | Madde | Ops-B katkı |
|---|---|---|
| 4 | Alert receiver synthetic proof | **Conditional on Ops-A** — Ops-B PrometheusRule LIVE ama receiver attach Ops-A; sentetik test Ops-A unblock sonrası |
| 6 | Status writer 24-72h clean | Ops-B alert FAIL durumunda detect; ABM-1 soak observer'a paralel kanal |
| 7 | Branch protection + cross-AI audit live | Bu PR cross-AI peer review chain ile uyumlu |

---

## §6. Risk Register Updates

| Risk | Kategori | Mitigation |
|---|---|---|
| Annotation cardinality limit | Methodology | 3 annotation key sabit, value range küçük (failures 0/1, result PASS/FAIL, lastFire UTC ISO) — Prometheus storage impact düşük |
| kube-state-metrics scrape lag | Operational | 30-60s scrape interval; alert `for: 5m` lag-tolerant |
| Receiver attach delay (Ops-A blocked) | Schedule | PrometheusRule LIVE ama alarm Slack/issue'ya düşmez; ABM-1 soak observer paralel monitoring (V2.1 #6) |
| False positive `lastFire stale` (maintenance) | Operational | Maintenance log ile annotate; alert `for: 5m` + 12h threshold |

---

## §7. Resolved Decisions + Carried Questions (Codex tur-2 cleanup)

### §7.1 Resolved (Codex 2-tur AGREE)

| # | Resolution |
|---|---|
| Annotation FQDN prefix | `frontend-federation-smoke.io/<field>` (collision-safe, Kubernetes convention) |
| PrometheusRule namespace | `monitoring` namespace + `release: kube-prometheus-stack` label (discovery contract) |
| Synthetic alert test pattern | **Önce** always-firing `PrometheusRule perf-alerts-test` (route/receiver/Slack 200 OK test); **sonra** controlled `failures=1` patch (Ops-B PromQL test) |
| Test cluster `uninitialised` triage | §4 Step 0 pre-impl gate (implementation PR öncesi zorunlu) |

### §7.2 Carried (Implementation PR scope)

| # | Question |
|---|---|
| 1 | helm-chart `extraArgs` vs `metricAnnotationsAllowList` field idiomatic? (chart sürümüne göre `helm template` verify implementation PR'da) |
| 2 | `PerfFederationSmokeStatusAbsent` per-cluster/per-namespace join pattern (global absent FAIL — test eksik / prod var → fire etmez); `kube_namespace_status_phase unless on(cluster, namespace) kube_configmap_annotations` benzeri expected-namespace join gerek |
| 3 | Step 0 triage outcome: CronJob/RBAC/deploy bug çıkarsa ayrı small fix PR mı yoksa Ops-B core PR description'a evidence eklemek mi |

---

## §8. Onay

| Rol | Ad | Tarih | İmza |
|---|---|---|---|
| Owner | Halil | 2026-05-14 | ☐ |
| AI Consensus | Claude (spike) + Codex pending review | 2026-05-14 | ⏳ |

---

## §9. Cross-AI

```yaml
Implementer AI:   Claude (Anthropic)
Reviewer AI:      Codex (OpenAI)
Codex thread:     N/A
Verdict:          AGREE
Verdict reason:   Spike decision record — annotation-based pattern selection (Option C) Pushgateway/exporter overhead'i önler; D27 upstream-first uyumlu
Same-provider exception: N/A
Cross-AI exempt reason: Docs-only spike decision record; Codex peer review tur-1 pending (cross-AI HARD RULE post-spike)
```

🤖 Generated by Claude (Anthropic). Cross-AI Codex peer review pending.
