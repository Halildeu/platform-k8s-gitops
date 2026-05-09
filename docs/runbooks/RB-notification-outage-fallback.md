# RB-notification-outage-fallback — D43 Outage Fallback Bypass Runbook

> **Status**: ACTIVE (Faz 23.2.D T1.4 PR-1+PR-2+PR-3 MERGED 2026-05-09)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md) D43 + D46 #10
> **Sub-faz**: 23.2 (MVP-dar — outage fallback bypass T1.4)
> **Codex thread**: `019df86f` Q4 PARTIAL absorb (initial); `019e0dea` iter-1+2+3+4 (T1.4 PR-1/2/3 cross-AI peer review)
> **Risk**: R9 (D43 outage fallback drill) — risk register'a göre PENDING; bu drill execute olduğunda 🔴 → 🟢 mitigated

---

## 1. Sorun & Tetik

`notification-orchestrator` **kendi outage'ında alarm gönderemez**. Eğer drift alarm-receiver, break-glass audit, kritik ops alarmı için tek kanal `notification-orchestrator` ise:

- Orchestrator down → outage alarmı kendisinden gelir → alarm gönderilemez → **silent failure**
- Operator outage'ı saatler sonra fark eder

**Tetikleyici** (drill veya gerçek incident için):
- `up{job="notification-orchestrator",namespace=~"platform-(test|prod)"} == 0` 2+ dakika (mevcut `NotifyServiceDown` PrometheusRule alert)
- Pod 0/1 Ready 5+ dakika
- Manual `kubectl scale deploy/notification-orchestrator --replicas=0` (drill)

---

## 2. Mimari — Üç Katmanlı Bypass

### 2.1 Katman 1: Alertmanager Direct Receiver (T1.4 PR-1)

`monitoring/alertmanager` config'inde **native receiver** `direct-fallback`:
- Slack: `slack_configs` + `api_url_file: /etc/alertmanager/secrets/alertmanager-fallback-secrets/SLACK_WEBHOOK_URL`
- SMTP: `email_configs` + `auth_username_file` + `auth_password_file` (aynı secret mount)
- Single receiver (slack + email birlikte) — Codex iter-2 #3 absorb

`route` matchers:
- `alertname = "NotifyServiceDown"` → `direct-fallback` (group_wait: 0s; repeat_interval: 30m)

Implementation: `helm-values/kube-prometheus-stack/values-test-d43-drill.yaml` (drill window override).

### 2.2 Katman 2: ESO Vault Fallback Secret (T1.4 PR-1)

Vault path **ayrı** (`notification-orchestrator`'ın path'inden bağımsız → tek credential rotation iki kanalı bozmaz):

- **Vault path**: `kv/platform/alertmanager-fallback` (5 keys: `SLACK_WEBHOOK_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`)
- **ESO ExternalSecret**: `monitoring/alertmanager-fallback-secrets` (test+prod overlays)
- **Vault policy**: `eso-runtime` extend (PR #457 commit `bootstrap/vault-policies/common/eso-runtime.hcl`)

Mount path (Alertmanager pod): `/etc/alertmanager/secrets/alertmanager-fallback-secrets/<key>`

### 2.3 Katman 3: PrometheusRule Liveness + Stable Labels (T1.4 PR-1)

`NotifyServiceDown` alert'in stable labels (Codex iter-3 #4 absorb):
- `severity: critical` + `service: notification-orchestrator` + `page: "true"`
- **`bypass_orchestrator: "true"`** (Alertmanager routing match)
- **`outage_fallback: "true"`** (fingerprint stability + drill kanıt)

Plus mailpit ingress NetworkPolicy (`kustomize/overlays/test/lab-deps/mailpit-netpol-from-monitoring.yaml`): monitoring ns → 587 SMTP allow (drill SMTP receipt için).

### 2.4 Katman 4: Script-Side Fallback Hooks (T1.4 PR-2 + PR-3)

#### PR-2: alarm-receiver Alertmanager direct fallback (`scripts/drift-detection/alarm_receiver.sh`)

Delivery chain (cascade order):
1. GitHub Issues (default — orchestrator-route audit trail)
2. `DRIFT_ALARM_WEBHOOK` generic webhook (GH 4xx/5xx/timeout sonrası)
3. **Alertmanager direct (P1 + `ALARM_FALLBACK_ALERTMANAGER=1`)**
4. Persistent undelivered log

Mode (`ALARM_FALLBACK_ALERTMANAGER_MODE`):
- `parallel` (default — D43 amacı): P1 + toggle → her zaman gönder (orchestrator-bypass receipt kanıtı korunur)
- `last_resort`: P1 + toggle + `delivery_status=undelivered` (cascade)

#### PR-3: break-glass dual-channel (`scripts/operations/break-glass-token.sh`)

Trigger:
- `orchestrator_reachable()` healthcheck:
  - 2xx → up (fallback gerekmez)
  - 5xx/timeout/000 → down (fallback fire)
  - 4xx → auth/config error (NOT outage; operator override hint)
- `gh_failed=1` (gh issue create fail VEYA gh CLI unavailable) → fallback fire

Dual-channel:
- Primary: GitHub Issues + local audit log
- Fallback: Alertmanager direct webhook (`alertname=BreakGlassUsed`, `severity=critical`)

**HARD RULE — TOKEN PAYLOAD'A YAZILMAZ** (no-token-log).

---

## 3. Pre-Drill Prereqs

### 3.1 Vault AppRole drift resolve (operator action)

Bu drill için ESO ClusterSecretStore Ready=True olmalı. Mevcut incident: "invalid role or secret ID" 2-day drift.

> **Detay runbook**: `docs/runbooks/RB-eso-vault-approle-rotate.md` — Vault AppRole rotation prosedürü, doğrulama, audit log + GitHub issue trail. Bu drill başlamadan önce o runbook adımları tamamlanmalı.

```bash
# Vault root token ile (operator)
ssh halil@staging-sw

# Mevcut role-id confirm
docker exec platform-vault-test vault read auth/approle/role/eso-runtime/role-id

# Yeni secret-id rotate
docker exec platform-vault-test vault write -force auth/approle/role/eso-runtime/secret-id

# K8s Secret update (yeni secret-id)
NEW_SECRET_ID=$(...)  # Vault output'tan
kubectl --context k3d-test -n external-secrets create secret generic vault-approle-secret \
  --from-literal=secret-id=$NEW_SECRET_ID \
  --dry-run=client -o yaml | kubectl --context k3d-test apply -f -

# ESO controller restart
kubectl --context k3d-test -n external-secrets rollout restart deploy/external-secrets

# Verify
kubectl --context k3d-test get clustersecretstore vault-platform-gitops \
  -o jsonpath='{.status.conditions[0].status}'  # Expected: True
```

### 3.2 Vault `alertmanager-fallback` path init (operator one-shot)

```bash
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test \
  vault kv put kv/platform/alertmanager-fallback \
    SLACK_WEBHOOK_URL=<test webhook URL — drill kanalı> \
    SMTP_HOST=mailpit.platform-test.svc.cluster.local \
    SMTP_PORT=587 \
    SMTP_USER=alertmanager-fallback@local \
    SMTP_PASSWORD=<irrelevant for Mailpit; populate non-empty>
```

Plus prod cluster için ayrı path init (operator gerçek prod credentials ile).

### 3.3 ESO sync verify

```bash
kubectl --context k3d-test -n monitoring get externalsecret alertmanager-fallback-secrets \
  -o jsonpath='{.status.conditions[0].status}'  # Expected: True

kubectl --context k3d-test -n monitoring get secret alertmanager-fallback-secrets \
  -o jsonpath='{.data}' | jq 'keys'  # Expected: 5 keys
```

### 3.4 alarm-receiver + break-glass script LIVE (PR-2 + PR-3)

```bash
# alarm-receiver toggle off default; drill için on
export ALARM_FALLBACK_ALERTMANAGER=1
export ALARM_FALLBACK_ALERTMANAGER_MODE=parallel
export ALERTMANAGER_FALLBACK_URL=http://127.0.0.1:9093/api/v2/alerts  # port-forward

# break-glass toggle off default; drill için on
# Same env vars + NOTIFY_ORCH_HEALTH_URL override (port-forward)
```

---

## 4. Execution Plane (Codex iter-3 #2 absorb)

Script'ler iki yerden çalışabilir:

### Opsiyon A: In-cluster runner (önerilir)

K8s Job/Pod monitoring ns'inde script çalıştırır; cluster.local DNS native çözüm.

### Opsiyon B: Host (staging-sw) + port-forward (drill default)

```bash
# Terminal 1: notification-orchestrator port-forward
kubectl --context k3d-test -n platform-test port-forward svc/notification-orchestrator 8089:8089

# Terminal 2: Alertmanager port-forward (drill window'da Alertmanager enable)
kubectl --context k3d-test -n monitoring port-forward svc/alertmanager 9093:9093

# Terminal 3: drill execution
export NOTIFY_ORCH_HEALTH_URL=http://127.0.0.1:8089/actuator/health
export ALERTMANAGER_FALLBACK_URL=http://127.0.0.1:9093/api/v2/alerts
export ALARM_FALLBACK_ALERTMANAGER=1

# Run drill...
```

---

## 5. Drill Prosedürü (10-criteria closure — Codex iter-2 absorb)

### Step 1: Render/lint pass (✅ PR #457 + #462 + #463 MERGED)

```bash
kubectl kustomize kustomize/overlays/test/eso/ | grep alertmanager-fallback-secrets
helm template kube-prometheus-stack -n monitoring \
  -f helm-values/kube-prometheus-stack/values-test.yaml \
  -f helm-values/kube-prometheus-stack/values-test-d43-drill.yaml | grep direct-fallback
bash -n scripts/drift-detection/alarm_receiver.sh
bash -n scripts/operations/break-glass-token.sh
```

### Step 2: Vault/ESO SecretSynced=True (gate Vault AppRole drift resolve)

`kubectl get externalsecret alertmanager-fallback-secrets -n monitoring -o jsonpath='{.status.conditions[0].status}'` → `True`

### Step 3: PrometheusRule LIVE

```bash
kubectl --context k3d-test -n monitoring exec -it deploy/prometheus-operator-prometheus -- \
  promtool query instant 'http://localhost:9090' 'ALERTS{alertname="NotifyServiceDown"}'
# Initial state: empty (no firing)
```

### Step 4: Alertmanager native Slack+SMTP receiver routing match

#### 4.0 Service/pod discovery (Codex iter-1 P2 #3 absorb)

```bash
# Discover canonical service + pod adlandırması (kube-prometheus-stack release'e göre)
kubectl --context k3d-test -n monitoring get svc | grep -E 'prometheus|alertmanager'
kubectl --context k3d-test -n monitoring get pods | grep -E 'prometheus|alertmanager'

# Beklenen: kube-prometheus-stack-prometheus, kube-prometheus-stack-alertmanager
# Bu çıktıdan canonical isim çıkar; aşağıdaki komutları o isimle güncelle.
```

#### 4.1 Drill window aç + receiver verify

```bash
# Drill window aç
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f helm-values/kube-prometheus-stack/values-test.yaml \
  -f helm-values/kube-prometheus-stack/values-test-d43-drill.yaml

# Wait Alertmanager up (statefulset adı discovery sonrası)
kubectl --context k3d-test -n monitoring rollout status statefulset/<alertmanager-statefulset-name-from-discovery>

# Verify direct-fallback receiver (pod adı discovery sonrası)
kubectl --context k3d-test -n monitoring exec <alertmanager-pod-from-discovery> -- \
  amtool config show | grep -A 5 direct-fallback
```

### Step 5: Drill scale=0 → fire NotifyServiceDown/NotifyServiceAbsent → fallback

#### 5.1 PrometheusRule prereq

T1.4 PR-4 (this runbook) ile eklenen `NotifyServiceAbsent` test-only rule. Scale-to-zero target disappearance coverage. PR LIVE doğrulama:

```bash
curl -s http://127.0.0.1:9090/api/v1/rules | \
  jq '.data.groups[].rules[] | select(.name=="NotifyServiceAbsent")'
# Expected: rule mevcut (test-only, namespace=platform-test selector)
```

#### 5.2 Trigger outage + native fallback evidence

```bash
# Pre-drill snapshot (orchestrator UP)
kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=notification-orchestrator

# Trigger outage
kubectl --context k3d-test -n platform-test scale deploy/notification-orchestrator --replicas=0

# Wait for=2m (NotifyServiceDown VEYA NotifyServiceAbsent alert fire)
sleep 130

# Verify alert fired (her iki rule yakalar; jq test() regex match — Codex iter-3 P1 #2 fix)
curl -s http://127.0.0.1:9093/api/v2/alerts | \
  jq '.[] | select(.labels.alertname | test("^(NotifyServiceDown|NotifyServiceAbsent)$")) | {alertname: .labels.alertname, status: .status.state, labels: .labels}'
# Expected: en az 1 alert active
#   labels include bypass_orchestrator=true, outage_fallback=true
```

#### Drill side-effect uyarısı (Codex iter-3 P2 #3 absorb)

> **Önemli**: Step 5.3 ve Step 5.4 gerçek audit side-effect üretir:
> - alarm-receiver: GitHub auth varsa drill için gerçek GitHub issue/comment
>   açabilir (drill etiketiyle ayırt edilir)
> - break-glass: gerçek TTL token üretir + GitHub issue + audit log entry
>   (drill mutation yapılmasa bile token issuance event'i kayda girer)
>
> **Drill cleanup**:
> - Token kullanılmaz; geçici kubeconfig silinir (`rm -f /tmp/kubeconfig-break-glass-*`)
> - Drill GitHub issue'ları ya evidence olarak bırakılır ya da drill sonrası kapatılır
> - Local audit log entry drill etiketiyle (REASON içinde "D43 drill" prefix) ayırt edilir

#### 5.3 alarm-receiver fallback hook execute (PR-2 source kanıtı)

```bash
# Test fixture report (drift detection sample)
cat > /tmp/drift-report-test-drill.json <<'JSON'
{
  "environment": "test",
  "timestamp": "2026-05-09T19:30:00Z",
  "exit_code": 1,
  "findings": [
    {
      "class": "P1",
      "kind": "drift_d43_drill",
      "message": "D43 drill — sample drift finding for alarm-receiver fallback evidence",
      "details": "Drill execution; not real drift"
    }
  ]
}
JSON

# Toggle ON, host port-forward URL override
export ALARM_FALLBACK_ALERTMANAGER=1
export ALARM_FALLBACK_ALERTMANAGER_MODE=parallel
export ALERTMANAGER_FALLBACK_URL=http://127.0.0.1:9093/api/v2/alerts
export DRIFT_ALARM_WEBHOOK=""  # generic webhook off; sadece Alertmanager fallback

bash scripts/drift-detection/alarm_receiver.sh /tmp/drift-report-test-drill.json

# Verify Alertmanager direct fallback alert
curl -s http://127.0.0.1:9093/api/v2/alerts | \
  jq '.[] | select(.labels.alertname=="DriftDetectionFallback") | {severity: .labels.severity, drift_class: .labels.drift_class, dedupe_key: .labels.dedupe_key}'
# Expected: severity=critical, drift_class=P1, dedupe_key=<sha256 12 char prefix>
```

#### 5.4 break-glass dual-channel execute (PR-3 source kanıtı)

```bash
# orchestrator down, drill window'da
export ALARM_FALLBACK_ALERTMANAGER=1
export NOTIFY_ORCH_HEALTH_URL=http://127.0.0.1:8089/actuator/health
export ALERTMANAGER_FALLBACK_URL=http://127.0.0.1:9093/api/v2/alerts

# Test reason (no real mutation)
bash scripts/operations/break-glass-token.sh "D43 drill — no mutation; fallback evidence only — non-destructive"

# Expected output:
# - Token issued (kubeconfig path; TOKEN VALUE STDOUT'TA YOK)
# - GitHub issue opened (governance trail)
# - orchestrator unreachable (port-forward 8089 deki orchestrator scale=0 ise)
# - Alertmanager direct fallback delivered

# Verify Alertmanager BreakGlassUsed
curl -s http://127.0.0.1:9093/api/v2/alerts | \
  jq '.[] | select(.labels.alertname=="BreakGlassUsed") | {severity: .labels.severity, ns: .labels.ns, sa: .labels.sa, dedupe_key: .labels.dedupe_key}'
# Expected: severity=critical, ns=kube-system, sa=ops-break-glass

# Cleanup geçici kubeconfig (no-token-log HARD RULE — dosya delete)
rm -f /tmp/kubeconfig-break-glass-*
```

### Step 6: Slack direct receipt (drill webhook test channel)

Manuel: Slack #alerts-d43-drill kanalı → drill window'da `[D43 DRILL] NotifyServiceDown — critical` mesajı görüldü mü?

### Step 7: Mailpit SMTP receipt evidence

```bash
# Mailpit UI port-forward
kubectl --context k3d-test -n platform-test port-forward svc/mailpit 8025:8025
# Browser: http://localhost:8025 → '[D43 DRILL] NotifyServiceDown' email
```

### Step 8: Recovery scale=1 → audit best-effort post-recovery

```bash
kubectl --context k3d-test -n platform-test scale deploy/notification-orchestrator --replicas=1
kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator

# Wait Prometheus up{} == 1 (alert resolved)
sleep 60

# Verify alert resolved
curl -s http://127.0.0.1:9093/api/v2/alerts | \
  jq '.[] | select(.labels.alertname=="NotifyServiceDown") | .status.state'
# Expected: empty (no active alerts)

# Operator manual: post-recovery, write OUTAGE_FALLBACK_USED audit event
# (notification-orchestrator audit publish — best-effort idempotent; gelecek backend PR'a kalır)
```

### Step 9: Evidence doc

`docs/faz-23-evidence/2026-XX-XX-23-2-d-d43-drill.md` içerik:
- Pre-drill snapshot (pod state, ESO sync, PrometheusRule list)
- Drill execution timeline (UTC timestamps)
- Step 5-8 outputs (curl, kubectl, Slack screenshot, Mailpit screenshot)
- Recovery snapshot
- 10-criteria checklist (her step ✅)

### Step 10: R9 risk register status mitigated

`docs/notify/risk-register.md`:
- R9 Pending → Mitigated (drill executed once + evidence collected)
- Last review tarihi güncellenir
- Note: "mitigated by first controlled drill" — Codex iter-4 dil disiplini

---

## 6. Drill Window Kapat (post-evidence)

```bash
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f helm-values/kube-prometheus-stack/values-test.yaml
# Override'sız → Alertmanager kapalı (test cluster baseline)
```

---

## 7. Drift Risk + Periyodik Drill Cadence

D43 fallback path'i ayrı tutmak yeterli değil — periyodik drift testi gerek:

- **Aylık (cron)**: `RB-notification-outage-fallback.md` Step 4-8 prosedürü çalıştır
- **Test cluster'da**: drill window aç + scale=0 + verify + recovery
- **Production'da DR drill**: ADR-0011 AC-1 cadence ile uyumlu — yıllık (controlled prod drill)
- **Periyodik drill follow-up**: ayrı PR (T1.4 PR-5 — Q3 2026)

---

## 8. Rollback (drill fail durumu)

Eğer drill sırasında prod side-effect (test cluster'da DR yok ama emin olmak için):

```bash
# Force scale up notification-orchestrator
kubectl --context k3d-test -n platform-test scale deploy/notification-orchestrator --replicas=1

# Force Alertmanager disable (drill window kapat)
helm upgrade kube-prometheus-stack ... -f values-test.yaml  # override'sız

# Audit log: OUTAGE_FALLBACK_DRILL_FAILED event manual write
```

---

## 9. Cross-Reference

- ADR-0013 D43 (Outage fallback bypass) + D46 #10 (Observability + outage fallback must-have)
- ADR-0010 §2.5 boundary matrix (Vault credential ayrı path)
- ADR-0011 §3 Audit cadence (drill cadence)
- Codex thread `019df86f` Q4 PARTIAL absorb (initial)
- Codex thread `019e0dea` iter-1+2+3+4 (T1.4 PR-1/2/3 cross-AI peer review chain)

## 10. Implementation Inventory

| Component | Source | PR |
|---|---|---|
| Vault path declaration | `bootstrap/vault-policies/common/eso-runtime.hcl` | #457 (T1.4 PR-1) |
| ESO ExternalSecret (test+prod) | `kustomize/overlays/{test,prod}/eso/alertmanager/` | #457 |
| Alertmanager native receiver | `helm-values/kube-prometheus-stack/values-test-d43-drill.yaml` | #457 |
| Mailpit netpol (monitoring → 587) | `kustomize/overlays/test/lab-deps/mailpit-netpol-from-monitoring.yaml` | #457 |
| NotifyServiceDown stable labels | `kustomize/base/apps/notification-orchestrator/prometheusrule.yaml` | #457 (iter-3) |
| alarm-receiver fallback hook | `scripts/drift-detection/alarm_receiver.sh` | #462 (T1.4 PR-2) |
| break-glass dual-channel | `scripts/operations/break-glass-token.sh` | #463 (T1.4 PR-3) |
| Runbook (this document) | `docs/runbooks/RB-notification-outage-fallback.md` | T1.4 PR-4 |

---

## 11. Last Update

**2026-05-09 (T1.4 PR-4 runbook rewrite)** — Faz 23.2.D T1.4 PR-1+PR-2+PR-3 MERGED implementation'a uyumlu yeniden yazıldı. Eski draft (kv/platform/monitoring/fallback path) deprecate; canonical kv/platform/alertmanager-fallback. 10-criteria closure prosedürü inline. Drill execution Vault AppRole drift resolve sonrası operator action.
