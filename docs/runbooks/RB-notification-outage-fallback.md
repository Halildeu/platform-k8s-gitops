# RB-notification-outage-fallback — Notification-orchestrator Outage Fallback

> **Status**: DRAFT (Faz 23.0 charter — 2026-05-05)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md) D43 + D46 #10
> **Sub-faz**: 23.2 (MVP-dar — outage fallback bypass implementation)
> **Codex thread**: `019df86f` Q4 PARTIAL absorb (kritik bulgu)

## Sorun

`notification-orchestrator` **kendi outage'ında alarm gönderemez**. Eğer drift alarm-receiver, break-glass audit, kritik ops alarmı için tek kanal `notification-orchestrator` ise:

- Orchestrator down → outage alarmı kendisinden gelir → alarm gönderilemez → **silent failure**
- Kullanıcı/operator outage'ı saatler sonra fark eder

## Çözüm — İki Katmanlı Bypass

### Katman 1: Alertmanager Direct Channel (orchestrator bypass)

`monitoring/alertmanager` config'inde **ayrı receiver**'lar:

```yaml
# kustomize/base/monitoring/alertmanager-config.yaml
receivers:
  - name: 'direct-fallback-slack'
    slack_configs:
      - api_url_file: '/etc/alertmanager-secrets/slack-fallback-webhook'
        channel: '#alerts'
        title: '[FALLBACK] {{ .GroupLabels.alertname }}'
        text: '{{ .CommonAnnotations.description }}'
  - name: 'direct-fallback-smtp'
    email_configs:
      - to: 'ops@example.com'
        from: 'alertmanager@example.com'
        smarthost: 'smtp.corporate.example.com:587'
        auth_username_file: '/etc/alertmanager-secrets/smtp-fallback-user'
        auth_password_file: '/etc/alertmanager-secrets/smtp-fallback-pass'

route:
  receiver: 'direct-fallback-slack'
  routes:
    - match:
        severity: critical
        bypass_orchestrator: 'true'
      receiver: 'direct-fallback-slack'
      continue: true
    - match:
        severity: critical
        bypass_orchestrator: 'true'
      receiver: 'direct-fallback-smtp'
```

### Katman 2: ESO Secret Sync (ayrı Vault path)

Fallback channel credential'ları `notification-orchestrator`'dan **bağımsız**:

```yaml
# kustomize/base/monitoring/eso-fallback.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: alertmanager-fallback-secrets
  namespace: monitoring
spec:
  secretStoreRef:
    name: vault-platform
    kind: ClusterSecretStore
  target:
    name: alertmanager-fallback-secrets
  data:
    - secretKey: slack-fallback-webhook
      remoteRef:
        key: kv/platform/monitoring/fallback
        property: slack_webhook_url
    - secretKey: smtp-fallback-user
      remoteRef:
        key: kv/platform/monitoring/fallback
        property: smtp_user
    - secretKey: smtp-fallback-pass
      remoteRef:
        key: kv/platform/monitoring/fallback
        property: smtp_password
```

**Vault path**: `kv/platform/monitoring/fallback` — `notification-orchestrator`'ın `kv/platform/notify/*` path'inden ayrı. Tek bir credential rotasyonu iki kanalı birden bozmaz.

### Katman 3: Prometheus Liveness Rule

```yaml
# kustomize/base/monitoring/prometheusrule-notify.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: notification-orchestrator-outage
  namespace: monitoring
spec:
  groups:
    - name: notification.outage
      interval: 30s
      rules:
        - alert: NotificationOrchestratorDown
          expr: up{job="notification-orchestrator"} == 0
          for: 5m
          labels:
            severity: critical
            bypass_orchestrator: 'true'
          annotations:
            summary: 'notification-orchestrator down — direct fallback active'
            description: '{{ $labels.instance }} 5+ dakikadır unreachable. Drift/break-glass alarmları Alertmanager direct kanalına yönlendiriliyor.'
            runbook: 'docs/runbooks/RB-notification-outage-fallback.md'
        
        - alert: NotificationOrchestratorDLQGrowing
          expr: notification_dlq_size > 10
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: 'DLQ size > 10 for 10m'
            description: '{{ $value }} delivery max retry exceeded. Manual replay gerekebilir.'
```

## Live Test (sub-faz 23.2 D29-NOTIFY-Up kabul kriteri)

```bash
# 1. Test cluster'da orchestrator'ı down al
kubectl --context k3d-test -n platform-test scale deploy/notification-orchestrator --replicas=0

# 2. 5 dakika bekle (Prometheus liveness rule for=5m)
sleep 360

# 3. Alertmanager'da fired alert'i doğrula
kubectl --context k3d-test -n monitoring port-forward svc/alertmanager 9093:9093 &
curl http://localhost:9093/api/v2/alerts | jq '.[] | select(.labels.alertname=="NotificationOrchestratorDown")'

# 4. Slack #alerts kanalında direct fallback mesajı geldi mi
# (manuel browser check — UI screenshot evidence)

# 5. SMTP fallback'i de test et (test mailbox)
# (corporate relay test mailbox check)

# 6. Cleanup
kubectl --context k3d-test -n platform-test scale deploy/notification-orchestrator --replicas=1
```

**Beklenen evidence**:
- `docs/faz-23-evidence/<date>-23-2-outage-fallback-canli.md`
- Alertmanager fired alert JSON
- Slack channel screenshot
- SMTP test mailbox screenshot
- Recovery: orchestrator scale=1 → fired alert resolved

## Drift Risk

Fallback path'i ayrı tutmak yeterli değil — **periyodik drift testi** gerek:

- Aylık (cron): `RB-notification-outage-fallback.md` Live Test prosedürü çalıştır
- Test cluster'da fallback denemesi → evidence dosyası
- Production'da DR drill (ADR-0011 AC-1 cadence ile uyumlu — ayrıca yıllık)

## Cross-Reference

- ADR-0013 D43 (Outage fallback bypass) + D46 #10 (Observability + outage fallback must-have)
- ADR-0010 §2.5 boundary matrix (Vault credential ayrı path)
- ADR-0011 §3 Audit cadence (drill cadence)
- Codex thread `019df86f` Q4 PARTIAL absorb
