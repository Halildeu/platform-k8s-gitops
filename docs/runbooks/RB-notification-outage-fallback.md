# RB-notification-outage-fallback — D43 Outage Fallback Bypass Runbook

> **Status**: ACTIVE (Faz 23.2.D T1.4 PR-1+PR-2+PR-3 MERGED 2026-05-09; PR-1.5 prod staged config PR #855 Session 42 — Codex `019e4234`; **BL-008 mock-receipt drill 2026-05-24 — Codex `019e5aaf` REVISE absorb**; **BL-D43-TEAMS-PIVOT 2026-05-24 — Codex `019e5ba9` REVISE/iter-2 absorb**)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md) D43 + D46 #10
> **Sub-faz**: 23.2 (MVP-dar — outage fallback bypass T1.4)
> **Codex thread**: `019df86f` Q4 PARTIAL absorb (initial); `019e0dea` iter-1+2+3+4 (T1.4 PR-1/2/3 cross-AI peer review); `019e4234` Session 42 (prod activation scope split + truth alignment); `019e5aaf` BL-008 mock-receipt drill REVISE absorb; **`019e5ba9` BL-D43-TEAMS-PIVOT REVISE/iter-2 absorb (Slack → Microsoft Teams Power Automate workflow webhook)**
> **Risk**: R9 — **current state 🟢 mock-receipt mitigated, Teams-pivot reverify pending** (BL-008 test cluster dual-receipt drill 2026-05-24; **BL-D43-TEAMS-PIVOT 2026-05-24** kullanıcı kararı "slack kullanmıyoruz teams kullanıyoruz" — receiver tipi `slack_configs` → `webhook_configs`, secret key `SLACK_WEBHOOK_URL` → `TEAMS_WEBHOOK_URL`, payload v4 generic JSON Power Automate parse). **Residual operator-external**: real Microsoft Teams Power Automate workflow setup + prod activation (yeni board issues; eski Slack #853/#854 kapatıldı). **R27 NEW**: Power Automate workflow lifecycle/owner/tenant policy drift risk. Production-ready claim DEĞİL.

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

### 2.1 Katman 1: Alertmanager Direct Receiver (T1.4 PR-1 + BL-008 2026-05-24 revize + BL-D43-TEAMS-PIVOT 2026-05-24 Codex `019e5ba9`)

`monitoring/alertmanager` config'inde **native receiver** `direct-fallback`:
- **Teams** (BL-D43-TEAMS-PIVOT 2026-05-24): `webhook_configs` + `url_file: /etc/alertmanager/secrets/alertmanager-fallback-secrets/TEAMS_WEBHOOK_URL` + `send_resolved: true` + `max_alerts: 50`. Alertmanager generic v4 webhook JSON payload — Microsoft Teams Power Automate workflow (incoming HTTP trigger) parse eder ve target Teams channel'a Adaptive Card post eder.
- **SMTP**: `email_configs` (test cluster Mailpit no-auth: `require_tls: false`, auth fields YOK; prod cluster ayrı schema — bkz §6.5.8)
- Single receiver (Teams + email birlikte) — Codex iter-2 #3 absorb; receiver adı `direct-fallback` vendor-neutral korunur (BL-D43-TEAMS-PIVOT Q3 absorb).

**Eski Slack pattern (DEPRECATED 2026-05-24)**:
- `slack_configs` + `api_url_file: SLACK_WEBHOOK_URL` — kullanıcı kararı "slack kullanmıyoruz teams kullanıyoruz" sonrası terkedildi. Vault key rename `SLACK_WEBHOOK_URL` → `TEAMS_WEBHOOK_URL`; eski Slack key Vault'ta rollback window boyunca tutulabilir, sonra operator silebilir (P2 cleanup).

`route` matchers (Codex `019e5aaf` REVISE absorb 2026-05-24 — BL-008 mock-receipt drill route narrowing):
- Root route: `receiver: "null"` (drill window'da diğer alerts drop; gereksiz POST/mail noise yok)
- D43 outage fallback dar regex route: `alertname =~ "NotifyServiceDown|NotifyServiceAbsent"` → `direct-fallback` (group_wait: 0s; repeat_interval: 30m; continue: false)
- `"null"` receiver baseline + `direct-fallback` receiver

Implementation: `helm-values/kube-prometheus-stack/values-test-d43-drill.yaml` (drill window override).

**Mock-vs-real boundary**: Test cluster `SLACK_WEBHOOK_URL` Codex `019e5aaf` REVISE absorb sonrası **in-cluster webhook-receiver mock URL** `http://webhook-receiver.platform-test.svc.cluster.local:8080/slack-mock` (sentinel revert YOK; webhook-receiver nginx POST logger LIVE 15d + permanent NetworkPolicy commit). Bu mock URL Alertmanager Slack receiver HTTP POST receipt evidence sağlar — **payload semantic Slack contract validation YOK** (nginx response body Slack format değil; "unrecoverable error" Alertmanager log'unda expected/known for mock drill). Real Slack workspace `#alerts-d43-drill` channel receipt board [#853](https://github.com/Halildeu/platform-k8s-gitops/issues/853) operator-external action.

### 2.2 Katman 2: ESO Vault Fallback Secret (T1.4 PR-1)

Vault path **ayrı** (`notification-orchestrator`'ın path'inden bağımsız → tek credential rotation iki kanalı bozmaz):

- **Vault path**: `kv/platform/alertmanager-fallback` (5 keys: **`TEAMS_WEBHOOK_URL`** (BL-D43-TEAMS-PIVOT 2026-05-24 rename), `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`)
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
# 2026-05-24 BL-D43-TEAMS-PIVOT (Codex 019e5ba9): SLACK_WEBHOOK_URL → TEAMS_WEBHOOK_URL.
# Mock URL port webhook-receiver Service port 8080 (kustomize/overlays/test/lab-deps/webhook-receiver.yaml line 136).
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test \
  vault kv put kv/platform/alertmanager-fallback \
    TEAMS_WEBHOOK_URL=http://webhook-receiver.platform-test.svc.cluster.local:8080/teams-mock \
    SMTP_HOST=mailpit.platform-test.svc.cluster.local \
    SMTP_PORT=587 \
    SMTP_USER=alertmanager-fallback@local \
    SMTP_PASSWORD=drill-only-mailpit-no-auth
```

**Test cluster TEAMS_WEBHOOK_URL canonical: in-cluster mock receiver**
(Codex thread `019e5ba9` BL-D43-TEAMS-PIVOT iter-2 absorb 2026-05-24).

Mock receiver: `webhook-receiver.platform-test.svc.cluster.local:8080/teams-mock`
(nginx POST logger; permanent NetworkPolicy
`kustomize/overlays/test/lab-deps/webhook-receiver-netpol-from-monitoring.yaml`
ile commit; Service port 8080 — webhook-receiver.yaml). Alertmanager
webhook receiver POST sırasında **HTTP 200 receipt** (nginx access log:
method/uri/length/status capture) sağlar — payload semantic Teams
Adaptive Card contract validation YOK; mock drill için HTTP-layer eşdeğer.
Eski `:9000/teams-mock` ve `SLACK_WEBHOOK_URL` referansları
**DEPRECATED** (Codex `019e5ba9` iter-2 P1 fix — yanlış port + Slack-first).

**Test mock vs real boundary**:

| Scope | Test cluster (this section) | Real Teams Power Automate workflow (yeni board) | Prod cluster (yeni board) |
|---|---|---|---|
| URL | `webhook-receiver.platform-test:8080/teams-mock` (Codex 019e5ba9 iter-2 port fix; eski 9000 yanlış) | Microsoft Teams Power Automate workflow HTTP POST endpoint (operator service-account/team-owned flow + exported package backup) | Operator Power Automate workflow target prod Teams channel |
| Validation | HTTP POST receipt (nginx 200 log) — payload semantic Teams Adaptive Card contract validation YOK (mock-only HTTP layer) | Teams Adaptive Card görsel + Power Automate flow run-history status=Success + flow run ID kayıt (R27 mitigation 6) | Teams Adaptive Card görsel + flow run-history audit log + SMTP receipt + GitHub Issue (3-channel defense-in-depth) |
| Acceptance | BL-008 mock-receipt drill 10/10 (`docs/faz-23-evidence/2026-05-24-bl008-r9-d43-drill.md` historical; Slack-pre-pivot kayıt; BL-D43-TEAMS-PIVOT 2026-05-24 sonrası Teams reverify drill yapılacak) | Operator action (Power Automate workflow setup + Vault seed) | Operator action (Vault prod seed + helm upgrade + triple receipt smoke + R27 mitigation 7 rotation rehearsal) |
| Status | 🟢 Mitigated (mock-receipt) 2026-05-24 — Teams reverify pending | 🟡 Pending yeni board issue (eski #853 kapatıldı 2026-05-24 BL-D43-TEAMS-PIVOT) | 🟡 Pending yeni board issue (eski #854 kapatıldı 2026-05-24 BL-D43-TEAMS-PIVOT) |

Test cluster drill execution: bu §3.2 test sub-section pre-conditions + §5 prosedür
(synthetic Alertmanager API POST 5.2.A önerilen / scale=0 5.2.B legacy
istisna → dual receipt → recovery) — `2026-05-24` mock-receipt drill log
referans. Geçici sentinel state 2026-05-10 drill window'unda mevcut idi; o
drill SMTP-only kanıt ile mitigated kabul edildi (`risk-register.md` R9 +
M3 T1.4) — Codex `019e4234` audit'i bu kabul sınıfını partial mitigation
olarak yeniden etiketledi; **BL-008 2026-05-24 mock-receipt drill** o partial state'i
test cluster dual-receipt evidence ile kapatır. **BL-D43-TEAMS-PIVOT 2026-05-24
(Codex `019e5ba9`)** sonrası Teams reverify drill (mock URL `:8080/teams-mock`)
ayrı operator slot — `webhook_configs` receiver pattern + payload v4 generic JSON
HTTP-layer eşdeğer.

#### Prod cluster (D43 outage fallback aktivasyon — Codex `019e4234` Yol-3)

> Bu adım PR-1 staged/gated values-prod.yaml merge edildikten **sonra** ve
> `helm upgrade` ile cluster apply edilmeden **önce** yapılır.

Owner artifact (Microsoft Teams admin + ops — BL-D43-TEAMS-PIVOT 2026-05-24 Codex `019e5ba9`):

- **`TEAMS_WEBHOOK_URL`**: Microsoft Teams Power Automate workflow HTTP POST endpoint. Operator Power Automate'ta service-account veya team-owned flow oluşturur:
  - **Trigger**: "When an HTTP request is received" (anonymous HTTP endpoint)
  - **Action**: "Post adaptive card in a chat or channel" → prod D43 outage target Teams channel
  - **Payload schema** (Alertmanager v4 webhook): `{alerts[], status, groupLabels, commonLabels, commonAnnotations}` — Power Automate flow JSON parse + Adaptive Card transform
  - **Flow ownership**: **service-account veya team-owned** (R27 mitigation — bireysel owner YASAK)
  - **Backup**: Exported flow package (`.zip`) artifact (R27 mitigation 2)
- `SMTP_HOST`: prod SMTP relay endpoint (default `smtp.office365.com`,
  vendor değişimi config-only — `notification-orchestrator` ile aynı vendor
  patternı)
- `SMTP_PORT`: `587` (STARTTLS standard)
- `SMTP_USER`: prod ops service mail (örn. `alertmanager-fallback@acik.com`
  — owner Microsoft 365 admin tarafında oluşturur; 2FA bypass için
  App Password)
- `SMTP_PASSWORD`: ilgili App Password (operator Vault'a yazar; transcript'e
  yazılmaz — HARD RULE no-token-log)

**Eski Slack pattern (DEPRECATED 2026-05-24)**: `SLACK_WEBHOOK_URL` Vault key kullanıcı kararı sonrası terkedildi; eski key Vault'ta rollback window'da tutulabilir, sonra operator silebilir (P2 cleanup).

Seed (operator) — Codex iter-2 R27 absorb: hidden prompt + stdin pipe:

```bash
ssh halil@staging-sw '
ROOT_TOKEN="$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)"

# Step 1: Non-secret SMTP host/port/user — inline kv patch
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-prod \
  vault kv put kv/platform/alertmanager-fallback \
    SMTP_HOST=smtp.office365.com \
    SMTP_PORT=587 \
    SMTP_USER=alertmanager-fallback@acik.com

# Step 2: Teams Power Automate workflow URL — stdin pipe (no plaintext shell)
read -r -s -p "Teams Power Automate workflow HTTP POST URL (prod D43 outage flow): " TEAMS_URL && echo
printf "%s" "$TEAMS_URL" | docker exec -i \
  -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-prod \
  vault kv patch kv/platform/alertmanager-fallback TEAMS_WEBHOOK_URL=-
unset TEAMS_URL

# Step 3: SMTP App Password — stdin pipe
read -r -s -p "SMTP App Password (alertmanager-fallback@acik.com): " SMTP_PWD && echo
printf "%s" "$SMTP_PWD" | docker exec -i \
  -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-prod \
  vault kv patch kv/platform/alertmanager-fallback SMTP_PASSWORD=-
unset SMTP_PWD

unset ROOT_TOKEN
'
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
# Beklenen: 5 keys, hepsi non-empty
```

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

### Step 4: Alertmanager native Teams+SMTP receiver routing match (BL-D43-TEAMS-PIVOT 2026-05-24)

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

### Step 5: Drill → fire NotifyServiceDown/NotifyServiceAbsent → fallback

> **BL-D43-TEAMS-PIVOT 2026-05-24 (Codex `019e5ba9` iter-2 P1 #3 absorb)**:
> HARD RULE TEST Cluster Scale-to-Zero YASAK (2026-05-10 — paralel multi-Claude session safety). Önerilen trigger pattern **Synthetic Alertmanager API POST** (5.2.A); `scale=0` legacy debug istisnası (5.2.B) sadece controlled drill window + owner-approved.

#### 5.1 PrometheusRule prereq

T1.4 PR-4 (this runbook) ile eklenen `NotifyServiceAbsent` test-only rule. Synthetic Alertmanager API POST için: rule mevcudiyeti gerekli DEĞİL (Alertmanager API alert'i direkt kabul eder). Scale=0 alternatifi için PR LIVE doğrulama:

```bash
curl -s http://127.0.0.1:9090/api/v1/rules | \
  jq '.data.groups[].rules[] | select(.name=="NotifyServiceAbsent")'
# Expected: rule mevcut (test-only, namespace=platform-test selector)
```

#### 5.2.A Trigger outage — **Synthetic Alertmanager API POST** (önerilen, HARD RULE uyumlu)

```bash
# Alertmanager port-forward
kubectl --context k3d-test -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093:9093 &
PF_PID=$!
sleep 3

# Synthetic NotifyServiceDown alert POST (Alertmanager dispatch chain'i hareket eder)
curl -sS -X POST http://localhost:9093/api/v2/alerts \
  -H 'Content-Type: application/json' \
  -d '[{
    "labels": {
      "alertname": "NotifyServiceDown",
      "severity": "critical",
      "namespace": "platform-test",
      "outage_fallback": "true",
      "bypass_orchestrator": "true"
    },
    "annotations": {
      "description": "Synthetic Teams pivot reverify drill — BL-D43-TEAMS-PIVOT"
    },
    "startsAt": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "endsAt": "'$(date -u -v+10M +%Y-%m-%dT%H:%M:%SZ)'"
  }]'

# Verify alert active
curl -s http://localhost:9093/api/v2/alerts | \
  jq '.[] | select(.labels.alertname | test("^(NotifyServiceDown|NotifyServiceAbsent)$")) | {alertname: .labels.alertname, status: .status.state, labels: .labels}'
# Expected: alert active, labels include bypass_orchestrator=true, outage_fallback=true

# (Alertmanager Step 6'da webhook-receiver POST + Step 7 SMTP receipt)

# Cleanup port-forward (drill receipt verify sonrası)
# kill $PF_PID
```

#### 5.2.B Trigger outage — Scale=0 (legacy istisna, sadece controlled drill window + owner-approved)

```bash
# Pre-drill snapshot (orchestrator UP)
kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=notification-orchestrator

# Trigger outage (HARD RULE TEST Cluster Scale-to-Zero YASAK — sadece drill istisna)
kubectl --context k3d-test -n platform-test scale deploy/notification-orchestrator --replicas=0

# Wait for=2m (NotifyServiceDown VEYA NotifyServiceAbsent alert fire)
sleep 130

# Verify alert fired (her iki rule yakalar; jq test() regex match)
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

### Step 6: Teams receipt evidence (mock-or-real per scope) — BL-D43-TEAMS-PIVOT 2026-05-24

**Test cluster mock-receipt drill — Codex `019e5ba9` Teams pivot**:

```bash
# webhook-receiver mock POST log capture (nginx access log)
kubectl --context k3d-test -n platform-test logs deploy/webhook-receiver --since=5m | grep teams-mock
# Expected: POST /teams-mock length=<bytes> status=200 timestamp matches T+3m FIRING window
```

Test mock evidence dili: **"Alertmanager webhook receiver mock POST receipt + Alertmanager route correlation"** (NOT "Teams Adaptive Card receipt"). Payload semantic validation YOK; webhook-receiver nginx 200 dönüyor; mock URL Teams flow değil — Adaptive Card transform YOK. Mock-only davranış: Alertmanager dispatch chain hareket etti + receiver tipi (webhook_configs) doğru çalıştı.

> Eski `/slack-mock` log grep pattern + payload contract DEPRECATED (2026-05-24 BL-D43-TEAMS-PIVOT). Historical evidence: `docs/faz-23-evidence/2026-05-24-bl008-r9-d43-drill.md` (Slack-pre-pivot historical kayıt).

**Real Microsoft Teams Power Automate workflow (yeni board issue — operator action)**:

Manuel: Operator Power Automate flow target Teams channel → drill window'da Adaptive Card görüldü mü? Card body: alertname=NotifyServiceDown + severity=critical + outage_fallback=true + bypass_orchestrator=true. Power Automate flow run-history'de status=Success + flow run ID kayıt zorunlu (R27 mitigation 6). Gerçek Teams Power Automate workflow URL Vault `kv/platform/alertmanager-fallback.TEAMS_WEBHOOK_URL`'a yazılır + ESO sync + drill.

**Prod cluster (yeni board issue — owner-gated)**:

§6.5 prosedürü follow; Power Automate flow target prod Teams channel manuel kontrol + flow run-history audit log.

### Step 7: Mailpit SMTP receipt evidence

```bash
# Mailpit UI port-forward
kubectl --context k3d-test -n platform-test port-forward svc/mailpit 8025:8025
# Browser: http://localhost:8025 → '[D43 DRILL] NotifyServiceDown' email
```

### Step 8: Recovery → audit best-effort post-recovery

> **BL-D43-TEAMS-PIVOT 2026-05-24 (Codex `019e5ba9` iter-2 P1 #3)**: Recovery pattern trigger seçimine bağlı.

**Recovery 5.2.A (synthetic API POST)**:

```bash
# Alert endsAt expire'a kadar bekle VEYA explicit silence
curl -sS -X POST http://localhost:9093/api/v2/silences \
  -H 'Content-Type: application/json' \
  -d '{"matchers": [{"name": "alertname", "value": "NotifyServiceDown", "isRegex": false}], "startsAt": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'", "endsAt": "'$(date -u -v+5M +%Y-%m-%dT%H:%M:%SZ)'", "createdBy": "d43-drill", "comment": "BL-D43-TEAMS-PIVOT reverify drill cleanup"}'

# Verify alert resolved
curl -s http://127.0.0.1:9093/api/v2/alerts | \
  jq '.[] | select(.labels.alertname=="NotifyServiceDown") | .status.state'
# Expected: empty (no active alerts) — silenced veya expired
```

**Recovery 5.2.B (scale=0 → scale=1)** — sadece eski drill alternatifi kullanılmışsa:

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
- Trigger seçimi (5.2.A synthetic API POST veya 5.2.B scale=0)
- Step 5-8 outputs (curl, kubectl, **mock POST log OR Teams Adaptive Card screenshot + flow run ID/status**, Mailpit screenshot)
- Recovery snapshot (silence ID veya scale=1 rollout)
- 10-criteria checklist (her step ✅) — scope-aware: mock-receipt OR real-Teams OR prod-activation
- Scope qualifier: "mock-receipt drill" / "real Teams Power Automate drill" / "prod activation triple-receipt"

Referans canlı evidence örnekleri:
- 2026-05-24 BL-008 mock-receipt drill: `docs/faz-23-evidence/2026-05-24-bl008-r9-d43-drill.md`
- 2026-05-10 SMTP-only drill: `docs/faz-23-evidence/2026-05-10-r9-d43-drill-mitigated.md`

### Step 10: R9 risk register status update

`docs/notify/risk-register.md`:
- Per-scope status:
  - **Test cluster mock-receipt drill**: 🟡 partial → 🟢 Mitigated (mock-receipt) — DUAL receipt evidence (Mailpit SMTP + webhook-receiver POST 200)
  - **Real Microsoft Teams Power Automate workflow**: pending yeni board issue ops slot (eski #853 kapatıldı 2026-05-24)
  - **Prod activation**: pending yeni board issue owner-gated (eski #854 kapatıldı 2026-05-24)
- Last review tarihi güncellenir
- Dil disiplini (Codex `019e5aaf` + `019e5ba9` REVISE absorb): "mitigated by mock-receipt drill — real Teams Power Automate workflow + prod activation ayrı operator-external". "Mitigated by first controlled drill" overclaim YASAK (mock-only kapsamla sınırlı).

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

> Codex thread `019e4234` Session 42 verdict — `ready_for_prod_activation=false`
> until owner artifacts arrive; cluster activation must follow `helm upgrade`
> sequenced with Vault seed completion.

### 6.5.1 Pre-activation gates

- PR-1 staged config MERGED + **BL-D43-TEAMS-PIVOT PR #1053** (Teams pivot 2026-05-24 Codex `019e5ba9`): `values-prod.yaml` `direct-fallback` receiver +
  `NotifyServiceDown|NotifyServiceAbsent` route + `secrets[]` mount listed
  (already present from PR #457 + Teams pivot #1053).
- Vault prod path seeded (§3.2 prod sub-section): 5 keys non-empty;
  `ExternalSecret/alertmanager-fallback-secrets` `Ready=True`;
  `Secret/alertmanager-fallback-secrets` 5 keys non-empty (TEAMS_WEBHOOK_URL + 4 SMTP).
- `cross-ai-audit` chain for PR-1 and any follow-up activation PR.
- **Teams Power Automate workflow live**: service-account/team-owned flow created + exported package backup + tenant DLP/license/quota preflight (R27 mitigation 1-2-5).
- **SMTP schema fix** (Codex `019e5ba9` iter-2 P1 #4): `values-prod.yaml` `email_configs` `auth_username_file`/`auth_password_file` Operator v0.90.1 schema gap fix yapıldı (inline `auth_username` + `auth_password` Vault template injection VEYA Operator upgrade). Aksi halde prod helm upgrade ReconciliationFailed.
- Yeni board issue `In Progress` → `Blocked by owner action` (Teams Power Automate workflow setup + ops Vault TEAMS_WEBHOOK_URL seed) →
  `In Progress` → `Needs Verify` (acceptance: Teams Adaptive Card + flow run-history + SMTP + GitHub Issue) → `Done`. Eski #854 kapatıldı 2026-05-24.

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
# Beklenen: receiver block + webhook_configs url_file: /etc/alertmanager/secrets/alertmanager-fallback-secrets/TEAMS_WEBHOOK_URL + SMTP smarthost smtp.office365.com:587 (BL-D43-TEAMS-PIVOT 2026-05-24)

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
# Beklenen: 5 file (TEAMS_WEBHOOK_URL + SMTP_HOST + SMTP_PORT + SMTP_USER + SMTP_PASSWORD) — BL-D43-TEAMS-PIVOT 2026-05-24
```

### 6.5.5 Synthetic NotifyServiceDown smoke (controlled prod outage window) — BL-D43-TEAMS-PIVOT 2026-05-24

> Bu adım gerçek prod outage simulasyonu — Pre-Production Full Authority +
> kullanıcı açık beyanı altında. **BL-D43-TEAMS-PIVOT 2026-05-24 (Codex
> `019e5ba9` iter-2 P1 #3)**: Önerilen trigger pattern **synthetic
> Alertmanager API POST** (HARD RULE PROD Scale-to-Zero controlled drill
> only + owner-approved). Sıra: port-forward aç (6.5.5-6.5.7 boyunca
> açık tutulur, sonra cleanup) → synthetic API POST → alert dispatch →
> direct-fallback + bridge triple delivery → silence/expire → curl
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

# Trigger outage — Synthetic Alertmanager API POST (önerilen, HARD RULE uyumlu)
curl -sS -X POST http://localhost:9093/api/v2/alerts \
  -H 'Content-Type: application/json' \
  -d '[{
    "labels": {
      "alertname": "NotifyServiceDown",
      "severity": "critical",
      "namespace": "platform-prod",
      "outage_fallback": "true",
      "bypass_orchestrator": "true"
    },
    "annotations": {
      "description": "Prod D43 activation smoke — BL-D43-TEAMS-PIVOT controlled smoke"
    },
    "startsAt": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "endsAt": "'$(date -u -v+10M +%Y-%m-%dT%H:%M:%SZ)'"
  }]'

sleep 10   # Alert dispatch + Power Automate flow trigger

# Verify alert + routing — receivers MULTI (continue:true) — direct-fallback
# + alarm-receiver-bridge birlikte; sıra Alertmanager iç state'e bağlı, bu
# yüzden `[receivers[].name]` array olarak kontrol et.
curl -s http://127.0.0.1:9093/api/v2/alerts | \
  jq '.[] | select(.labels.alertname | test("^(NotifyServiceDown|NotifyServiceAbsent)$")) | {alertname: .labels.alertname, status: .status.state, receivers: [.receivers[].name]}'
# Beklenen: at least 1 active alert; receivers array contains BOTH
# "direct-fallback" AND "alarm-receiver-bridge" (continue:true 3-channel
# defense-in-depth: Teams Adaptive Card + SMTP + GitHub Issue).
```

### 6.5.6 Acceptance — TRIPLE receipt (continue:true)

- **Teams "D43 Outage" channel (Power Automate workflow target)**: Adaptive Card geldi mi (alertname=NotifyServiceDown + severity=critical + outage_fallback=true + bypass_orchestrator=true) + flow run-history status=Success + run ID kayıt (R27 mitigation 6)? Eski `[D43 PROD]
  NotifyServiceDown — critical` mesajı + alert labels (Cluster=prod,
  outage_fallback=true, bypass_orchestrator=true).
- **SMTP receipt**: ops mail group (`notify-ops@acik.com`) inbox'ında
  `[D43 PROD] NotifyServiceDown` subject'li email.
- **GitHub Issue (alarm-receiver-bridge P1 evidence)**: Halildeu/platform-k8s-gitops repo'sunda yeni issue (alertmanager-bridge dedupe: alertname+namespace tek issue açar; recovery'de comment + close).

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
pre/during/post snapshot + Teams Adaptive Card screenshot + Power Automate flow run-history JSON export + SMTP screenshot + GitHub
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
- **Test cluster'da**: drill window aç + synthetic Alertmanager API POST (5.2.A önerilen) veya scale=0 (5.2.B legacy istisna) + verify + recovery
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
