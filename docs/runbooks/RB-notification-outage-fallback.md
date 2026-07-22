# RB-notification-outage-fallback — D43 Outage Fallback Bypass Runbook

> **Status**: ACTIVE (Faz 23.2.D T1.4 PR-1+PR-2+PR-3 MERGED 2026-05-09; PR-1.5 prod staged config PR #855 Session 42 — Codex `019e4234`; **BL-008 mock-receipt drill 2026-05-24 — Codex `019e5aaf` REVISE absorb**)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md) D43 + D46 #10
> **Sub-faz**: 23.2 (MVP-dar — outage fallback bypass T1.4)
> **Codex thread**: `019df86f` Q4 PARTIAL absorb (initial); `019e0dea` iter-1+2+3+4 (T1.4 PR-1/2/3 cross-AI peer review); `019e4234` Session 42 (prod activation scope split + truth alignment); **`019e5aaf` BL-008 mock-receipt drill REVISE absorb**
> **Risk**: R9 — **current state 🟢 SMTP-only D43 v1 accepted** per user decision 2026-05-24 (Codex strategic thread `019e5b9c` REVISE absorb). D43 v1 acceptance = Alertmanager direct-fallback SMTP receiver. Historical drill evidence retained as drill audit only (no longer v1 gate): first controlled drill 2026-05-10 Mailpit SMTP receipt + BL-008 mock-receipt drill 2026-05-24 (webhook-receiver + Mailpit dual). **Slack adoption DEFER future trigger**. **Residual operator-external**: prod activation board [#854](https://github.com/Halildeu/platform-k8s-gitops/issues/854) rescope (SMTP-only direct fallback smoke + Operator v0.90.1 `auth_*_file` schema fix). Original board [#853](https://github.com/Halildeu/platform-k8s-gitops/issues/853) + [#1012](https://github.com/Halildeu/platform-k8s-gitops/issues/1012) (Slack-dependent) → DEFER. Production-ready claim DEĞİL. Evidence: `docs/faz-23-evidence/2026-05-24-d43-slack-defer-smtp-only-acceptance.md`.

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

### 2.1 Katman 1: Alertmanager Direct Receiver (T1.4 PR-1 + BL-008 2026-05-24 revize)

`monitoring/alertmanager` config'inde **native receiver** `direct-fallback` (SMTP-only per user decision 2026-05-24 Slack DEFER; Codex `019e5b9c` REVISE absorb):
- SMTP: `email_configs` (test cluster Mailpit no-auth: `require_tls: false`, auth fields YOK; prod cluster ayrı schema — bkz §6.5.8)
- Slack leg removed from active config (historical: previously `slack_configs` + `api_url_file: /etc/alertmanager/secrets/alertmanager-fallback-secrets/SLACK_WEBHOOK_URL`); future reactivation atomic with operator workspace adoption + Vault seed + drill rerun in same PR

`route` matchers (Codex `019e5aaf` REVISE absorb 2026-05-24 — BL-008 mock-receipt drill route narrowing):
- Root route: `receiver: "null"` (drill window'da diğer alerts drop; gereksiz POST/mail noise yok)
- D43 outage fallback dar regex route: `alertname =~ "NotifyServiceDown|NotifyServiceAbsent"` → `direct-fallback` (group_wait: 0s; repeat_interval: 30m; continue: false)
- `"null"` receiver baseline + `direct-fallback` receiver

Implementation: `helm-values/kube-prometheus-stack/values-test-d43-drill.yaml` (drill window override).

**Historical mock-vs-real boundary** (pre-2026-05-24 Slack DEFER — audit-only): Test cluster `SLACK_WEBHOOK_URL` previously routed to in-cluster webhook-receiver mock URL (`http://webhook-receiver.platform-test.svc.cluster.local:8080/slack-mock`) per BL-008 drill 2026-05-24. Per user decision 2026-05-24 ("slack kullanmıyoruz. sonrasınd agelirse yapılacak") Slack section removed from active config — boundary historical only. Future reactivation atomic with helm-values + ExternalSecret data re-add + drill rerun.

### 2.2 Katman 2: ESO Vault Fallback Secret (T1.4 PR-1)

Vault path **ayrı** (`notification-orchestrator`'ın path'inden bağımsız → tek credential rotation iki kanalı bozmaz):

- **Vault path**: `kv/platform/alertmanager-fallback` (4 keys: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` — SMTP-only per user decision 2026-05-24 Slack DEFER; historical 5th key `SLACK_WEBHOOK_URL` removed from ExternalSecret request; Vault key may persist as inactive operator hygiene residue)
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

#### Test cluster (D43 drill prereq)

```bash
# SMTP-only per user decision 2026-05-24 Slack DEFER (Codex 019e5b9c REVISE absorb).
# SLACK_WEBHOOK_URL parameter removed; ExternalSecret no longer requests it.
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test \
  vault kv put kv/platform/alertmanager-fallback \
    SMTP_HOST=mailpit.platform-test.svc.cluster.local \
    SMTP_PORT=587 \
    SMTP_USER=alertmanager-fallback@local \
    SMTP_PASSWORD=drill-only-mailpit-no-auth
```

**Historical** (pre-2026-05-24 Slack DEFER, audit-only): Test cluster `SLACK_WEBHOOK_URL` canonical was in-cluster mock receiver `http://webhook-receiver.platform-test.svc.cluster.local:8080/slack-mock` (Codex thread `019e5aaf` REVISE absorb 2026-05-24 BL-008 mock-receipt drill). Removed per user decision 2026-05-24.

Mock receiver: `webhook-receiver.platform-test.svc.cluster.local:8080/slack-mock`
(nginx POST logger; permanent NetworkPolicy
`kustomize/overlays/test/lab-deps/webhook-receiver-netpol-from-monitoring.yaml`
ile commit). Alertmanager Slack receiver POST sırasında **HTTP 200 receipt**
(nginx access log: method/uri/length/status capture) sağlar — payload
semantic Slack contract validation YOK; "unrecoverable error" Alertmanager
log'unda expected for mock drill. Eski `http://drill-slack-mock.local/webhook`
sentinel **DEPRECATED** (NXDOMAIN; drill 2026-05-10 Slack leg sessiz kayıp).

**Test mock vs real boundary**:

| Scope | Test cluster (this section) | Real Slack workspace (#853) | Prod cluster (#854) |
|---|---|---|---|
| URL | `webhook-receiver.platform-test:8080/slack-mock` | Real `#alerts-d43-drill` Slack incoming webhook URL | Owner-provided `#prod-outage-alerts` webhook |
| Validation | HTTP POST receipt (nginx 200 log) | Slack channel message manuel görme | Slack channel message manuel görme |
| Acceptance | BL-008 mock-receipt drill 10/10 (`docs/faz-23-evidence/2026-05-24-bl008-r9-d43-drill.md`) | Operator action (Slack workspace admin) | Operator action (Vault prod seed + helm upgrade + dual-receipt smoke) |
| Status | 🟢 Mitigated (mock-receipt) 2026-05-24 | 🟡 Pending board [#853](https://github.com/Halildeu/platform-k8s-gitops/issues/853) | 🟡 Pending board [#854](https://github.com/Halildeu/platform-k8s-gitops/issues/854) |

Test cluster drill execution: bu §3.2 test sub-section pre-conditions + §5 prosedür
(scale=0 → dual receipt → recovery) — `2026-05-24` mock-receipt drill log
referans. Geçici sentinel state 2026-05-10 drill window'unda mevcut idi; o
drill SMTP-only kanıt ile mitigated kabul edildi (`risk-register.md` R9 +
M3 T1.4) — Codex `019e4234` audit'i bu kabul sınıfını partial mitigation
olarak yeniden etiketledi; **BL-008 2026-05-24 mock-receipt drill** o partial state'i
test cluster dual-receipt evidence ile kapatır.

#### Prod cluster (D43 outage fallback aktivasyon — Codex `019e4234` Yol-3)

> Bu adım PR-1 staged/gated values-prod.yaml merge edildikten **sonra** ve
> `helm upgrade` ile cluster apply edilmeden **önce** yapılır.

Owner artifact (ops only — SMTP-only per user decision 2026-05-24 Slack DEFER):

- `SMTP_HOST`: prod SMTP relay endpoint (default `smtp.office365.com`,
  vendor değişimi config-only — `notification-orchestrator` ile aynı vendor
  patternı)
- `SMTP_PORT`: `587` (STARTTLS standard)
- `SMTP_USER`: prod ops service mail (örn. `alertmanager-fallback@acik.com`
  — owner Microsoft 365 admin tarafında oluşturur; 2FA bypass için
  App Password)
- `SMTP_PASSWORD`: ilgili App Password (operator Vault'a yazar; transcript'e
  yazılmaz — HARD RULE no-token-log)

**Historical** (pre-2026-05-24 Slack DEFER, audit-only): Slack admin owner artifact previously required `SLACK_WEBHOOK_URL` (gerçek prod `#alerts-d43-drill` workspace incoming webhook). Removed per user decision 2026-05-24.

Seed (operator):

```bash
ssh halil@staging-sw
docker exec -e VAULT_TOKEN=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json) \
  platform-vault-prod \
  vault kv put kv/platform/alertmanager-fallback \
    SMTP_HOST=smtp.office365.com \
    SMTP_PORT=587 \
    SMTP_USER=alertmanager-fallback@acik.com \
    SMTP_PASSWORD=<...>
```

Verify ESO sync (1h refresh-interval veya manual force-sync):

```bash
kubectl --context k3d-prod -n monitoring annotate \
  externalsecret alertmanager-fallback-secrets \
  force-sync=$(date +%s) --overwrite
kubectl --context k3d-prod -n monitoring get externalsecret alertmanager-fallback-secrets \
  -o jsonpath='{.status.conditions[0].status}'
# Beklenen: True
kubectl --context k3d-prod -n monitoring get secret alertmanager-fallback-secrets \
  -o json | jq '.data | to_entries | map({key, value_len: (.value | @base64d | length)})'
# Beklenen (current SMTP-only canonical state — ADR-0027 §D1 2026-05-25): 4 key (SMTP_HOST + SMTP_PORT + SMTP_USER + SMTP_PASSWORD), hepsi non-empty. TEAMS_WEBHOOK_URL **not seeded** (asset-preserved dormant; Teams reactivation 5. key olarak RB-d43-teams-reactivation-chain.md §3 atomic chain ile gelir).
```

### 3.3 ESO sync verify

```bash
kubectl --context k3d-test -n monitoring get externalsecret alertmanager-fallback-secrets \
  -o jsonpath='{.status.conditions[0].status}'  # Expected: True

kubectl --context k3d-test -n monitoring get secret alertmanager-fallback-secrets \
  -o jsonpath='{.data}' | jq 'keys'  # Expected (current SMTP-only canonical — ADR-0027 §D1 2026-05-25): 4 keys (SMTP_HOST + SMTP_PORT + SMTP_USER + SMTP_PASSWORD); Teams reactivation 5. key TEAMS_WEBHOOK_URL ile gelir (RB-d43-teams-reactivation-chain.md §3)
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

### Step 4: Alertmanager native SMTP receiver routing match (SMTP-only per user decision 2026-05-24 Slack DEFER)

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

### Step 6: SMTP receipt evidence — DEFERRED (Slack DEFER per user decision 2026-05-24)

**Historical (pre-2026-05-24 user decision Slack DEFER)**:

Bu adım eski dual-receipt acceptance (SMTP + Slack) içindi. User decision 2026-05-24 ("slack kullanmıyoruz. sonrasınd agelirse yapılacak") sonrası D43 v1 acceptance SMTP-only.

**SMTP receipt validation**: Bkz §6.5.6 acceptance — DUAL receipt (SMTP + bridge). Slack receipt validation v1 acceptance gate DEĞİL.

**Historical drill evidence** (audit-only, NOT v1 gate):
- 2026-05-10 first controlled drill SMTP receipt Mailpit `[FIRING:1] NotifyServiceAbsent` 00:22:33Z
- BL-008 mock-receipt drill 2026-05-24 webhook-receiver mock POST + Mailpit SMTP receipt (dual-receipt drill audit; superseded by SMTP-only v1 acceptance per user decision 2026-05-24)

**Future Slack reactivation** (operator workspace adoption gelirse):
- Re-add `slack_configs` block to `direct-fallback` receiver atomic with this step's Slack receipt validation
- See §2.1 active config + ADR-0013 + `docs/faz-23-evidence/2026-05-24-d43-slack-defer-smtp-only-acceptance.md`
- Cascade: #853 + #1012 DEFER (Slack-dependent); reactivation requires new issue tracker

**Prod cluster (board [#854](https://github.com/Halildeu/platform-k8s-gitops/issues/854) — owner-gated; SMTP-only per user decision 2026-05-24 Slack DEFER)**:

§6.5 prosedürü follow (DEFERRED guard — see §6.5 header + [#1054](https://github.com/Halildeu/platform-k8s-gitops/issues/1054) canonical surface continuation tracker). Slack channel manual check requirement removed; current v1 acceptance = §6.5.6 DUAL receipt (SMTP + GitHub Issue bridge).

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

`docs/faz-23-evidence/2026-XX-XX-<scope>-d43-drill.md` içerik:
- Pre-drill snapshot (pod state, ESO sync, PrometheusRule list)
- Drill execution timeline (UTC timestamps)
- Step 5-8 outputs (curl, kubectl, Mailpit screenshot — SMTP-only per user decision 2026-05-24 Slack DEFER; historical Slack mock POST log/screenshot audit-only)
- Recovery snapshot
- 10-criteria checklist (her step ✅) — scope-aware: SMTP-only D43 v1 acceptance gate or prod-activation
- Scope qualifier: "SMTP-only D43 v1 drill" / "prod activation DUAL receipt (SMTP + GitHub Issue bridge)" — historical "Slack workspace drill" / "triple-receipt" wording superseded per user decision 2026-05-24

Referans canlı evidence örnekleri:
- 2026-05-24 BL-008 mock-receipt drill: `docs/faz-23-evidence/2026-05-24-bl008-r9-d43-drill.md`
- 2026-05-10 SMTP-only drill: `docs/faz-23-evidence/2026-05-10-r9-d43-drill-mitigated.md`

### Step 10: R9 risk register status update

`docs/notify/risk-register.md`:
- Current status (post-2026-05-24 user decision Slack DEFER; Codex `019e5b9c` REVISE absorb):
  - **R9**: 🟢 Mitigated (SMTP-only D43 v1; Slack DEFER per user decision 2026-05-24)
  - **Active mitigation**: Alertmanager direct-fallback SMTP receiver (notification-orchestrator-independent credentials)
  - **Historical drill evidence** (audit-only, no longer v1 acceptance gate): 2026-05-10 first controlled drill SMTP receipt + BL-008 mock-receipt dual drill 2026-05-24
  - **Prod activation**: board #854 SMTP-only rescope operator-bound
  - **Slack-dependent boards**: #853 + #1012 DEFER (not-planned for v1)
- Last review tarihi güncellenir
- Dil disiplini: "SMTP-only D43 v1 accepted; Slack DEFER". "Real Slack workspace receipt" / "triple-receipt" / "mock dual-receipt v1 acceptance" wording YASAK (historical drill audit-only). Future Slack reactivation atomic with active config re-add + drill rerun + R9 update.

---

## 6. Drill Window Kapat (post-evidence — test cluster)

```bash
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f helm-values/kube-prometheus-stack/values-test.yaml
# Override'sız → Alertmanager kapalı (test cluster baseline)
```

---

## 6.5 Prod D43 Activation (owner-gated, post PR-1 staged config)

> **⚠️ DEFERRED / DO NOT EXECUTE AS WRITTEN** (2026-05-24 Slack DEFER absorb pending continuation PR):
> §6.5.3-§6.5.7 sub-sections below contain pre-2026-05-24 Slack/triple-receipt wording with known stale expectations (Slack receiver verify, 5-key secret mount expectations, triple delivery acceptance, Slack screenshot evidence requirements). These pre-decision instructions are **NOT** the current v1 acceptance procedure.
>
> **Current v1 acceptance** (per user decision 2026-05-24 Slack DEFER + Codex `019e5b9c` REVISE absorb): Alertmanager direct-fallback SMTP receiver only. Acceptance = §6.5.6 DUAL receipt (SMTP + GitHub Issue bridge). 4 Vault keys (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD). No Slack receiver verify, no Slack screenshot evidence, no triple-receipt acceptance.
>
> **Operator action**: Board [#854](https://github.com/Halildeu/platform-k8s-gitops/issues/854) (SMTP-only prod activation rescope) MUST be the activation authority. The §6.5.3-§6.5.7 sub-sections below will be rewritten in a follow-up canonical-surface PR before operator activation. Until then, do not execute §6.5.x commands or accept the stale §6.5.6 TRIPLE receipt wording as current acceptance.
>
> Follow-up tracker: [#1054](https://github.com/Halildeu/platform-k8s-gitops/issues/1054) "Faz 23 D43 SMTP-only canonical surface continuation" covers RB §6.5.x rewrite + PLAN.md row 38 D43/D46 satırları + ADR-0013 amendment block + feature-matrix.md / RB-faz-23-charter.md supersession notes.

> Codex thread `019e4234` Session 42 verdict (HISTORICAL — superseded 2026-05-24 per user decision Slack DEFER; Codex `019e5b9c` REVISE absorb): `ready_for_prod_activation=false` until owner artifacts arrive; cluster activation must follow `helm upgrade` sequenced with Vault seed completion.

### 6.5.1 Pre-activation gates

- PR-1 staged config MERGED: `values-prod.yaml` `direct-fallback` receiver +
  `NotifyServiceDown|NotifyServiceAbsent` route + `secrets[]` mount listed
  (already present from PR #457; Slack section subsequently removed in
  Lane B PR roadmap-faz23-d43-slack-defer-helm-cleanup per user decision
  2026-05-24).
- Vault prod path seeded (§3.2 prod sub-section): 4 keys non-empty
  (SMTP-only per user decision 2026-05-24; `SLACK_WEBHOOK_URL` key removed
  from active ExternalSecret): `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
  `SMTP_PASSWORD`. `ExternalSecret/alertmanager-fallback-secrets`
  `Ready=True`; `Secret/alertmanager-fallback-secrets` 4 keys non-empty.
- `cross-ai-audit` chain for PR-1 and any follow-up activation PR.
- Board issue [#854](https://github.com/Halildeu/platform-k8s-gitops/issues/854)
  `In Progress` → `Blocked by owner action` (ops Vault seed + Operator
  v0.90.1 `auth_*_file` schema fix) → `In Progress` → `Needs Verify`
  (SMTP-only acceptance) → `Done`. Slack admin requirement REMOVED
  per user decision 2026-05-24 Slack DEFER.

### 6.5.2 Apply prod helm-values (operator action — kubectl context k3d-prod)

```bash
ssh halil@staging-sw
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f helm-values/kube-prometheus-stack/values-prod.yaml \
  --kube-context k3d-prod
# Alertmanager StatefulSet pod restart: Secret mount + new config reload
kubectl --context k3d-prod -n monitoring rollout status \
  statefulset/alertmanager-kube-prometheus-stack-alertmanager --timeout=180s
```

### 6.5.3 Config verify (amtool)

```bash
kubectl --context k3d-prod -n monitoring exec \
  alertmanager-kube-prometheus-stack-alertmanager-0 -c alertmanager -- \
  amtool config show | grep -A 30 direct-fallback
# Beklenen: receiver block + Slack `#alerts-d43-drill` + SMTP smarthost smtp.office365.com:587

kubectl --context k3d-prod -n monitoring exec \
  alertmanager-kube-prometheus-stack-alertmanager-0 -c alertmanager -- \
  amtool config routes show | grep -A 5 'alertname.*NotifyServiceDown'
# Beklenen: NotifyServiceDown|NotifyServiceAbsent → direct-fallback route
```

### 6.5.4 Secret mount verify (pod içinden)

```bash
kubectl --context k3d-prod -n monitoring exec \
  alertmanager-kube-prometheus-stack-alertmanager-0 -c alertmanager -- \
  ls -la /etc/alertmanager/secrets/alertmanager-fallback-secrets/
# Beklenen (current SMTP-only canonical — ADR-0027 §D1 2026-05-25): 4 file (SMTP_HOST + SMTP_PORT + SMTP_USER + SMTP_PASSWORD); Teams reactivation 5. file TEAMS_WEBHOOK_URL ile gelir (RB-d43-teams-reactivation-chain.md §3)
```

### 6.5.5 Synthetic NotifyServiceDown smoke (controlled prod outage window)

> Bu adım gerçek prod outage simulasyonu — Pre-Production Full Authority +
> kullanıcı açık beyanı altında. Sıra: port-forward aç (6.5.5-6.5.7 boyunca
> açık tutulur, sonra cleanup) → scale=0 → 130s bekle → alert fire →
> direct-fallback + bridge triple delivery → scale=1 → recovery → curl
> resolve verify → port-forward cleanup.

```bash
# Pre-smoke snapshot
kubectl --context k3d-prod -n platform-prod get pod \
  -l app.kubernetes.io/name=notification-orchestrator

# Open port-forward — kept open through §6.5.7 (cleanup at end of §6.5.7).
kubectl --context k3d-prod -n monitoring port-forward \
  svc/alertmanager-kube-prometheus-stack-alertmanager 9093:9093 &
PF_PID=$!
trap 'kill $PF_PID 2>/dev/null || true' EXIT
sleep 3

# Trigger outage (controlled — sadece smoke window)
kubectl --context k3d-prod -n platform-prod scale \
  deploy/notification-orchestrator --replicas=0

sleep 130   # NotifyServiceDown/Absent firing window

# Verify alert + routing — receivers MULTI (continue:true) — direct-fallback
# + alarm-receiver-bridge birlikte; sıra Alertmanager iç state'e bağlı, bu
# yüzden `[receivers[].name]` array olarak kontrol et.
curl -s http://127.0.0.1:9093/api/v2/alerts | \
  jq '.[] | select(.labels.alertname | test("^(NotifyServiceDown|NotifyServiceAbsent)$")) | {alertname: .labels.alertname, status: .status.state, receivers: [.receivers[].name]}'
# Beklenen: at least 1 active alert; receivers array contains BOTH
# "direct-fallback" AND "alarm-receiver-bridge" (continue:true 3-channel
# defense-in-depth: Slack + SMTP + GitHub Issue).
```

### 6.5.6 Acceptance — DUAL receipt (continue:true; SMTP-only per user decision 2026-05-24 Slack DEFER)

- **Source target**: shared mailbox `ai@acik.com` yalnız desired-state alıcısıdır;
  production apply ayrı ve açık insan onayı gerektirir. Apply + aşağıdaki
  receipt zinciri görülmeden bu adres canlı/functional sayılmaz.
- **Firing SMTP receipt**: aynı inbox'ta `[D43 PROD] NotifyServiceDown`
  subject'li email + alert labels (Cluster=prod, outage_fallback=true,
  bypass_orchestrator=true).
- **No-NDR evidence**: synthetic firing gönderiminden sonra `ai@acik.com`
  mailbox'ında hedef alıcıya ait Exchange NDR/bounce oluşmaz.
- **Recovery SMTP receipt**: orchestrator tekrar Ready olduktan ve alarm
  resolved olduktan sonra `send_resolved: true` bildirimi aynı inbox'a ulaşır.
- **GitHub Issue (alarm-receiver-bridge P1 evidence)**: Halildeu/platform-k8s-gitops repo'sunda yeni issue (alertmanager-bridge dedupe: alertname+namespace tek issue açar; recovery'de comment + close).

**#2796 apply/rollback sınırı:** PR merge yalnız source truth'u değiştirir ve
production mutation değildir. Prod Helm/GitOps apply için insan onayı gerekir.
Firing receipt, no-NDR, recovery receipt veya bridge kanıtlarından biri düşerse
delivery functional sayılmaz; doğrudan cluster edit yapılmaz. Operatör ya
doğrulanmış alternatif alıcıyı yeni reviewed PR ile seçer ya da bu recipient
commit'ini reviewed revert PR + insan onaylı prod re-sync ile geri alır. Bilinen
geçersiz eski alıcıya dönüş SMTP açığını gidermediğinden P0 issue açık kalır;
mevcut `alarm-receiver-bridge` sibling route'u korunur.

**Historical** (pre-2026-05-24 Slack DEFER): TRIPLE receipt included Slack `#alerts-d43-drill` channel message. Removed per user decision 2026-05-24 ("slack kullanmıyoruz. sonrasınd agelirse yapılacak"). DUAL receipt (SMTP + GitHub Issue bridge) is current v1 acceptance gate. Future Slack reactivation atomic with §2.1 active config re-add + Vault seed + drill rerun in same PR; cascade re-add to TRIPLE receipt acceptance dili.

### 6.5.7 Recovery + audit

```bash
# (port-forward §6.5.5'ten beri açık)
kubectl --context k3d-prod -n platform-prod scale \
  deploy/notification-orchestrator --replicas=1
kubectl --context k3d-prod -n platform-prod rollout status \
  deploy/notification-orchestrator --timeout=180s

sleep 60   # Alertmanager resolve cycle

curl -s http://127.0.0.1:9093/api/v2/alerts | \
  jq '.[] | select(.labels.alertname | test("^(NotifyServiceDown|NotifyServiceAbsent)$")) | .status.state'
# Beklenen: empty (resolved)

# Cleanup port-forward (trap zaten EXIT'te çağırır; explicit kill için)
kill $PF_PID 2>/dev/null || true
trap - EXIT
```

Audit doc: `docs/faz-23-evidence/2026-XX-XX-d43-prod-activation.md` —
pre/during/post snapshot + Slack screenshot + SMTP screenshot + GitHub
Issue link + 6.5.6 triple receipt evidence.

### 6.5.8 SMTP endpoint config — Vault değil, helm-values authoritative + Operator schema gap

> Codex `019e4234` post-impl P3 absorb: Alertmanager `email_configs` Go
> config'inde `smarthost` field'ı **string olarak doğrudan** beklenir;
> Alertmanager **`smarthost_file` desteklemez**. Bu yüzden prod `smarthost:
> 'smtp.office365.com:587'` `values-prod.yaml`'da hardcoded (canonical
> truth). Vault'taki `SMTP_HOST` + `SMTP_PORT` ESO ExternalSecret schema
> tutarlılığı için seed edilir (test cluster + prod cluster aynı key set'i
> — manifest portability), ama Alertmanager runtime'ı bu iki key'i
> okumaz.
>
> **Operator schema gap (Codex `019e5aaf` post-impl absorb — BL-008
> 2026-05-24 finding)**: Prometheus Operator v0.90.1 stricter schema
> `email_configs.auth_username_file` ve `email_configs.auth_password_file`
> field'larını reddediyor (`"field not found in type config.plain"`).
> Bu yüzden:
> - **Test cluster** (BL-008 mock drill): Mailpit no-auth (`require_tls:
>   false`); email_configs `auth_*_file` YOK; in-cluster mock receiver
>   karşılığında auth gerekmedi.
> - **Prod cluster** (board #854 blocker): `values-prod.yaml` hâlâ
>   `auth_username_file`/`auth_password_file` taşıyor — Operator
>   reconcile FAIL eder. Prod activation öncesi fix gerekir:
>   - **Opsiyon 1 (önerilir)**: inline `auth_username` + `auth_password`
>     (Vault'tan ESO ile pod env'e enjekte, Helm value template ile
>     embed). Field-mount değil, value-as-string.
>   - **Opsiyon 2**: Prometheus Operator upgrade (newer version
>     `_file` field desteği — release notes check gerek).
>
> **Vendor değişimi**: SMTP relay endpoint değişimi (örn. Office 365 →
> SendGrid → AWS SES) `values-prod.yaml` PR + `helm upgrade` ile yapılır,
> Vault seed patch'i ile değil. Vault'ta SMTP_HOST/PORT update edilse
> Alertmanager davranışı **etkilenmez**. Vendor flip için her zaman PR
> aç + cross-AI Codex review + acceptance smoke.

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
| Alertmanager native receiver (test drill) | `helm-values/kube-prometheus-stack/values-test-d43-drill.yaml` | #457 |
| Alertmanager native receiver (prod staged config) | `helm-values/kube-prometheus-stack/values-prod.yaml` (direct-fallback receiver + NotifyServiceDown\|NotifyServiceAbsent route) | #855 (PR-1 staged/gated; Codex thread `019e4234` Session 42 verdict) |
| Mailpit netpol (monitoring → 587) | `kustomize/overlays/test/lab-deps/mailpit-netpol-from-monitoring.yaml` | #457 |
| NotifyServiceDown stable labels | `kustomize/base/apps/notification-orchestrator/prometheusrule.yaml` | #457 (iter-3) |
| alarm-receiver fallback hook | `scripts/drift-detection/alarm_receiver.sh` | #462 (T1.4 PR-2) |
| break-glass dual-channel | `scripts/operations/break-glass-token.sh` | #463 (T1.4 PR-3) |
| Runbook (this document) | `docs/runbooks/RB-notification-outage-fallback.md` | T1.4 PR-4 |

---

## 11. Last Update

**2026-05-24 (BL-008 mock-receipt drill — Codex thread `019e5aaf`)** — Test cluster controlled simulate dual-receipt drill executed:
- Vault test SLACK_WEBHOOK_URL `drill-slack-mock.local` (NXDOMAIN sentinel) → `http://webhook-receiver.platform-test.svc.cluster.local:8080/slack-mock` (in-cluster nginx POST logger LIVE 15d). Sentinel revert YOK; webhook-receiver canonical test mock kalır.
- NetworkPolicy permanent: `kustomize/overlays/test/lab-deps/webhook-receiver-netpol-from-monitoring.yaml` (mailpit netpol pattern; monitoring → 8080 ingress allow).
- Drill values v3.1: root route receiver `"null"` + regex route `alertname =~ "NotifyServiceDown|NotifyServiceAbsent"` → `direct-fallback` (Codex REVISE absorb #3 route narrowing). email_configs `auth_*_file` removed (Operator v0.90.1 stricter schema; Mailpit no-auth).
- Drill execution 16:14:25-16:26:35Z (T+0 outage → T+3m dual receipt → T+8m recovery → T+12m baseline restore). Evidence: webhook-receiver POST 200 length=983 16:17:33Z + Mailpit `[D43 DRILL] NotifyServiceAbsent` 16:17:33.868Z.
- R9 risk-register update: 🟡 Partial → 🟢 Mitigated (mock-receipt). Real Slack workspace (#853) + prod activation (#854) ayrı.
- Evidence: `docs/faz-23-evidence/2026-05-24-bl008-r9-d43-drill.md`.

**2026-05-19 (PR #855 — Session 42, Codex thread `019e4234`)** — Prod D43 activation staged/gated config + truth alignment:
- §3.2 sub-divided test vs prod sub-sections; sentinel webhook prohibition added (Slack leg `drill-slack-mock.local` NXDOMAIN audit — board #853).
- §6.5 added — prod activation procedure (helm upgrade + amtool config verify + Secret mount verify + synthetic NotifyServiceDown smoke + **triple receipt** (Slack + SMTP + bridge GitHub Issue) + recovery), owner-gated until Vault prod seed.
- §10 inventory split test drill vs prod staged-config rows.
- Cross-doc truth alignment: PLAN.md D43 🔴→🟡 partial; D46 #10 partial detail; milestones.md M3 T1.4 partial drill; risk-register R9 🟢 Mitigated→🟡 Partial (eski "mitigated by first controlled drill" overclaim — Slack leg sentinel-only kanıtsız).

**2026-05-09 (T1.4 PR-4 runbook rewrite)** — Faz 23.2.D T1.4 PR-1+PR-2+PR-3 MERGED implementation'a uyumlu yeniden yazıldı. Eski draft (kv/platform/monitoring/fallback path) deprecate; canonical kv/platform/alertmanager-fallback. 10-criteria closure prosedürü inline. Drill execution Vault AppRole drift resolve sonrası operator action.
