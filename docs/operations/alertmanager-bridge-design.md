# AlertManager → alarm_receiver Bridge Design

> Codex Sprint A retrospective follow-up: drift detection alarm pipeline'ı
> (alarm_receiver.sh + GitHub issue auto-dedup) zaten çalışıyor. Prometheus
> AlertManager bu pipeline'a bağlanmalı ki observability alarm'ları aynı
> issue tracker'a aksın (drift-detection alarm'ları gibi).

## Problem

Mevcut iki ayrı alarm pipeline:
- **Drift detection**: `check_env_drift.sh` → JSON → `alarm_receiver.sh` → GitHub issue
- **AlertManager**: PrometheusRule → AlertManager → ??? (default: silent receiver)

İkinci pipeline **alarm üretiyor ama hiçbir yere gitmiyor**. Operator AlertManager UI'a port-forward etmeli, hiçbir audit trail yok.

## Çözüm

AlertManager webhook → cluster-internal HTTP bridge → GitHub Issues API.

```
[PrometheusRule fires]
    ↓
[AlertManager group + route]
    ↓ webhook POST
[alertmanager-bridge:9093/alert]   ← bu PR'da yarattığım Python service
    ↓ severity → P1/P2/P3 mapping
    ↓ stable issue title
[gh CLI issue create / comment]
    ↓
[GitHub Issues — auto-deduplicated]
```

## Komponentler

### 1. AlertManager helm values config

`helm-values/kube-prometheus-stack/values-prod.yaml`:

```yaml
alertmanager:
  config:
    route:
      receiver: 'alarm-receiver-bridge'
      routes:
        - matchers: [severity = "critical"]
          group_wait: 0s
          repeat_interval: 1h
        - matchers: [severity =~ "warning|info"]
    receivers:
      - name: 'alarm-receiver-bridge'
        webhook_configs:
          - url: 'http://alertmanager-bridge.monitoring.svc.cluster.local:9093/alert'
            send_resolved: true
```

### 2. Bridge service (cluster-internal Python HTTP server)

**`scripts/alerting/alertmanager-bridge.py`**:
- `BaseHTTPRequestHandler` (stdlib, no external deps)
- POST `/alert` → AlertManager webhook payload parse
- Severity mapping: critical→P1, warning→P2, info→P3
- Stable title: `[alertmanager-{class}] {alertname}/{namespace}`
- Auto-dedup via existing issue search
- Persistent undelivered log: `/var/log/bridge/undelivered.jsonl`
- GET `/healthz` → liveness probe

### 3. K8s deployment

**`kustomize/base/monitoring/alertmanager-bridge/`**:
- `deployment.yaml` — single replica, alpine + python3 + github-cli
- `service.yaml` — ClusterIP :9093
- `configmap.yaml` — env config (GITHUB_REPO, BRIDGE_PORT)
- `servicemonitor.yaml` — Prometheus scrape (future bridge metrics)

ServiceAccount + GH token secret operator manual provision (see secret-stub pattern).

### 4. GH token provisioning (operator manual)

```bash
# GitHub fine-grained PAT with issues:write scope
kubectl --context k3d-prod -n monitoring create secret generic alertmanager-bridge-gh-token \
  --from-literal=token=ghp_...
```

Veya ESO ile Vault'tan inject (preferred, future iteration).

## Alarm class mapping

| AlertManager severity | Bridge class | Action |
|---|---|---|
| `critical` | P1 | Operator action <10min, immediate (group_wait 0s) |
| `warning` | P2 | Review <1 day, grouped (group_wait 10s) |
| `info` | P3 | Backlog grooming, grouped |

## Auto-deduplication

Drift detection alarm_receiver.sh ile aynı pattern:
- Title hash on `alertname + namespace + severity`
- Same alert refiring → comment to existing open issue
- Different alert → new issue
- Resolved alert → comment "resolved at..." (send_resolved: true)

## Inhibit rules

Critical alert kendi alertname'inin warning versiyonunu suppress eder:
```yaml
inhibit_rules:
  - source_matchers: [severity = "critical"]
    target_matchers: [severity = "warning"]
    equal: ['alertname', 'namespace']
```

Bu, "PodCrashLooping critical + warning" gibi cascade'leri tek alert'e indirir.

## Failure modes + mitigation

### gh CLI auth fail
- Bridge log: `gh issue create failed: stderr...`
- Persistent undelivered.jsonl: alarm payload + reason="gh_issue_create_failed"
- Operator: review log, fix GITHUB_TOKEN, manual replay

### GitHub API rate limit (5000/h per token)
- Auto-dedup pattern minimizes API calls (single search + 1 comment)
- High-cardinality alert storm → may exceed limit
- Mitigation: AlertManager group_interval increase + repeat_interval throttling

### Bridge pod down
- AlertManager webhook fails (connection refused)
- AlertManager retries (backoff)
- Eventually timeout — alert "delivered to receiver" but not actually
- Mitigation: HPA disabled (D21), ResourceQuota generous, liveness probe restart

### Webhook payload too large
- AlertManager `max_alerts: 50` config'te
- 50+ alert grouping varsa subset'e böl
- Bridge process_alert loop'u tek tek işler

### Cluster network partition
- Bridge unreachable → AlertManager local buffer
- Recovery sonrası flush
- Persistent log için bridge tarafında fallback yok (AlertManager-side handles)

## Observability of the bridge itself

Bridge'in kendisi izlenmeli:
- ServiceMonitor scrape `/metrics` (future Prometheus client)
- Healthz probe Kubernetes-side
- Undelivered log file size monitoring (operator alarm)

## Cutover strategy

1. **Apply manifest**: `kubectl apply -k kustomize/base/monitoring/`
2. **Provision GH token secret**: operator manual
3. **Update helm values**: redeploy kube-prometheus-stack
4. **Synthetic test**: amtool ile fake alert fire → bridge log → GitHub issue
5. **Real verification**: existing PrometheusRule trigger eden bir kontrolü çalıştır (örn. blackbox down)

## Bağlantılar

- Drift detection alarm_receiver.sh (PR #347 hardened)
- AlertManager helm values (this PR)
- Future: Slack/PagerDuty receiver eklenecek (operator decision)

## Bilinen TODO (post-merge follow-up)

- [ ] Dedicated container image (alpine + python + gh pre-installed) — startup time düşürür
- [ ] Bridge metrics (prometheus_client) — delivered_total, undelivered_total
- [ ] GitOps secret for GITHUB_TOKEN (ESO ExternalSecret)
- [ ] Resolved-comment template iyileştir (annotations dahil)
- [ ] Multi-severity routing (different repos? different labels?)
