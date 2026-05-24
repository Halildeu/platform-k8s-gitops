# RB-d43-teams-reactivation-chain — D43 Teams Power Automate Activation Operator Runbook

> **Status**: READY (asset-preserved dormant; activation owner-gated post-trigger)
> **Trigger conditions**: ADR-0027 §D3 (5 koşuldan en az biri)
> **Reactivation type**: Atomic 6-step chain (Codex `019e5bdb` AGREE verdict 2026-05-25; ADR-0027 §D5 mandatory)
> **Codex thread**: `019e5bdb` (hibrit C verdict + reactivation chain authorize)
> **Audit reference**: PR #1053 closed diff (Codex thread `019e5ba9` iter-1..iter-5 review chain — implementation template)
> **Risk**: R27 (Teams Power Automate workflow lifecycle drift) — current state `⏳ DEFER asset-preserved`; reactivation sonrası `🟢 Mitigated active` (7-step mitigation operational evidence)

---

## 1. Tetikleyici Conditions (ADR-0027 §D3)

Reactivation chain yalnız aşağıdaki tetik koşullarından **en az biri** geldiğinde başlatılır:

1. **SMTP outage / Office 365 mail delivery tenant break** — `alertmanager-fallback@acik.com` SMTP relay başarısız (App Password deprecation tenant impact veya policy change) ve D43 outage anında dual-receipt için Teams alternative gerekli
2. **Outbound port 587 ISP/firewall block recurrence** — staging-sw veya prod cluster outbound 587 SMTP block; alternative external channel zorunlu
3. **Operator/security tactical decision** — incident visibility için Teams dashboard/Adaptive Card daha hızlı triage sağlar (ops decision)
4. **Compliance/audit requirement** — chat-channel notification audit trail için Teams formal channel zorunlu
5. **Tenant Power Automate DLP/license/quota approval** — preflight gate'leri tamamlanmış + service-account/team-owned flow lifecycle hazır (R27 mitigation prerequisites met)

**Trigger değil** (reactivation başlamaz):
- "Teams kullanıyoruz, neden D43'te yok" tipi user UX merak (audit trail clarify ile yeterli; reactivation gerekmez)
- Marketing/visibility-only desire (compliance gereksinim olmadan)
- Single-issue ad-hoc Adaptive Card request (one-shot ops Teams direct post yeterli)

---

## 2. Pre-Activation Prerequisites (R27 mitigation chain)

Reactivation başlamadan önce R27 7-step mitigation chain compliance kanıtlanır:

### 2.1 Power Platform tenant preflight (Codex `019e5ba9` iter-2 P1 absorb)

- [ ] **Power Platform DLP policy review**: Tenant Power Platform admin center → Data Policies → Connector availability (HTTP request connector + Microsoft Teams connector allowed)
- [ ] **License check**: Service-account veya team-owned account Power Automate Premium veya Per User license active (HTTP request trigger Premium connector)
- [ ] **Request quota**: Tenant daily/monthly Power Automate API call quota >= projected D43 outage frequency × Alertmanager group_interval (default ~10 calls/month conservative estimate)
- [ ] **Service-account/team-ownership**: Bireysel owner YASAK (R27 mitigation 1); flow service-account veya security group-owned hesap üzerinde

### 2.2 Workflow ownership + backup pattern (R27 mitigation 2)

- [ ] **Exported flow package backup plan**: Flow setup sonrası `.zip` export + runbook ekle (re-import için audit)
- [ ] **Service-account credential management**: Kayıt audit log dosyasında (HARD RULE no-token-log; secret management via Vault veya operator notebook)
- [ ] **Flow run-history monitoring plan** (R27 mitigation 6): Monthly synthetic smoke + flow run ID + status JSON export

### 2.3 Cluster prereqs

- [ ] **SMTP schema fix** (mevcut blocker — `values-prod.yaml` `email_configs` `auth_username_file`/`auth_password_file` Operator v0.90.1 schema gap fix): Bu chain başlamadan ÖNCE çözülmüş olmalı (ya inline `auth_username` + `auth_password` Vault template injection ya Operator upgrade)
- [ ] **Vault prod root token erişimi**: Operator `bootstrap/vault-init-prod.json` (HARD RULE no-token-log + stdin pipe pattern)
- [ ] **Helm + kubectl k3d-prod context erişimi**: `helm upgrade` + `kubectl annotate externalsecret force-sync` rights

---

## 3. Atomic 6-Step Reactivation Chain

> **HARD RULE — ATOMIC**: Parçalı aktivasyon YASAK (ADR-0027 §D5). Tüm 6 adım owner-approved window'da arka arkaya çalıştırılır; herhangi bir adımda fail → tüm önceki adımlar revert + audit log.

### Step 1: Power Automate flow setup (R27 mitigation 1+2)

**1.1 Service-account veya team-owned account ile Power Automate'a giriş**
- URL: `https://make.powerautomate.com/`
- Hesap: service-account (örn. `notify-platform-bot@<tenant>`) veya security group-owned

**1.2 Yeni flow oluştur — Cloud flow + "Manual trigger" → "When an HTTP request is received"**

Trigger config:
- Method: `POST` (default)
- Request body JSON Schema (Alertmanager v4 webhook):

```json
{
  "type": "object",
  "properties": {
    "alerts": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "labels": {"type": "object"},
          "annotations": {"type": "object"},
          "startsAt": {"type": "string"},
          "endsAt": {"type": "string"},
          "status": {"type": "string"}
        }
      }
    },
    "status": {"type": "string"},
    "groupLabels": {"type": "object"},
    "commonLabels": {"type": "object"},
    "commonAnnotations": {"type": "object"}
  }
}
```

**1.3 Action ekle — "Post adaptive card in a chat or channel"**

- Post as: **Flow bot** (service-account/group context)
- Post in: **Channel**
- Team: `<team>`
- Channel: "D43 Outage" veya `#prod-outage-alerts`
- Adaptive Card payload (Power Automate flow expression ile alerts[0]/groupLabels alanlarından doldurulur):

```json
{
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "type": "AdaptiveCard",
  "version": "1.4",
  "body": [
    {
      "type": "TextBlock",
      "text": "[D43 PROD] @{triggerBody()['groupLabels']['alertname']} — @{triggerBody()['commonLabels']['severity']}",
      "weight": "Bolder",
      "size": "Large",
      "color": "Attention"
    },
    {
      "type": "FactSet",
      "facts": [
        {"title": "Alert", "value": "@{triggerBody()['groupLabels']['alertname']}"},
        {"title": "Severity", "value": "@{triggerBody()['commonLabels']['severity']}"},
        {"title": "Namespace", "value": "@{triggerBody()['commonLabels']['namespace']}"},
        {"title": "Outage fallback", "value": "@{triggerBody()['commonLabels']['outage_fallback']}"},
        {"title": "Bypass orchestrator", "value": "@{triggerBody()['commonLabels']['bypass_orchestrator']}"},
        {"title": "Description", "value": "@{triggerBody()['commonAnnotations']['description']}"}
      ]
    }
  ]
}
```

**1.4 Save + flow URL'i kopyala**
- Flow detail view → "When a HTTP request is received" → **HTTP POST URL** field
- URL pattern: `https://prod-XX.westeurope.logic.azure.com:443/workflows/<workflow-id>/triggers/manual/paths/invoke?api-version=...&sig=<signature>`

**1.5 Exported flow package backup (R27 mitigation 2)**
- Flow detail view → ... → Export → .zip
- Backup location: operator notebook + runbook secondary copy

**1.6 Flow run-history monitoring setup (R27 mitigation 6)**
- Monthly calendar reminder: Flow detail view → Run history → Export JSON → audit log
- Failed run count >0 ise alarm

> **Scope note**: Bu runbook **D43 outage fallback** (alertmanager-fallback path) için. V2.1 Perf Alerts (`perf-alertmanager` path) Teams migration **ayrı PR/ADR** gerek (Hibrit C scope dışı; mevcut active config `perf-alerts-slack` korunur — separate future Perf Alerts Teams migration PR/ADR required, Codex `019e5bdb` iter-2 P2 absorb).

### Step 2: Vault seed (HARD RULE no-token-log + stdin pipe)

```bash
ssh halil@staging-sw '
ROOT_TOKEN="$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)"

# alertmanager-fallback (D43 outage flow URL) — SMTP 4-key canonical korunur
read -r -s -p "D43 outage Teams Power Automate workflow URL: " TEAMS_URL && echo
printf "%s" "$TEAMS_URL" | docker exec -i \
  -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-prod \
  vault kv patch kv/platform/alertmanager-fallback TEAMS_WEBHOOK_URL=-
unset TEAMS_URL

unset ROOT_TOKEN
'

# Test cluster (drill için) — D43 only
ssh halil@staging-sw '
ROOT_TOKEN="$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-test.json)"

# Test mock URL (webhook-receiver mock pattern)
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test \
  vault kv patch kv/platform/alertmanager-fallback \
    TEAMS_WEBHOOK_URL=http://webhook-receiver.platform-test.svc.cluster.local:8080/teams-mock

unset ROOT_TOKEN
'
```

**Verify (length-only, no plaintext)**:
```bash
ssh halil@staging-sw '
docker exec -e VAULT_TOKEN="$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)" \
  platform-vault-prod vault kv get -mount=kv -format=json platform/alertmanager-fallback \
  | jq ".data.data | to_entries | map({key, value_len: (.value | length)})"
# Beklenen post-reactivation: 5 keys (TEAMS_WEBHOOK_URL ~100-300 byte + 4 SMTP keys); current dormant 4 keys (SMTP-only ADR-0027 §D1)
'
```

### Step 3: ESO `TEAMS_WEBHOOK_URL` secretKey add (template snippet)

**Edit**: `kustomize/overlays/prod/eso/alertmanager/externalsecret-alertmanager-fallback.yaml`

Mevcut (dormant state, ADR-0027 §D1 canonical):
```yaml
  data:
    - secretKey: SMTP_HOST
      remoteRef:
        key: kv/platform/alertmanager-fallback
        property: SMTP_HOST
    - secretKey: SMTP_PORT
    ...
```

Reactivation ekle (PR #1053 closed diff template snippet — Codex `019e5ba9` iter-1 AGREE):
```yaml
  data:
    # 2026-05-XX Teams reactivation (ADR-0027 §D5 atomic; Codex 019e5bdb authorize)
    - secretKey: TEAMS_WEBHOOK_URL
      remoteRef:
        key: kv/platform/alertmanager-fallback
        property: TEAMS_WEBHOOK_URL
    # SMTP path canonical (ADR-0027 §D1; D43 v1 closure)
    - secretKey: SMTP_HOST
    ...
```

Aynı pattern test cluster `externalsecret-alertmanager-fallback.yaml` (D43 scope only). `externalsecret-perf-alertmanager.yaml` **bu PR scope dışı** (V2.1 Perf Alerts ayrı migration; Codex `019e5bdb` iter-2 P2 absorb).

**ESO force-sync + verify** (D43-only scope; perf-alertmanager-secrets ayrı migration):
```bash
kubectl --context k3d-prod -n monitoring annotate externalsecret alertmanager-fallback-secrets \
  force-sync="$(date +%s)" --overwrite

sleep 30

kubectl --context k3d-prod -n monitoring get externalsecret alertmanager-fallback-secrets \
  -o jsonpath="{.status.conditions[0].type}={.status.conditions[0].status}"
# Beklenen: Ready=True
```

### Step 4: Helm `values-prod.yaml` `direct-fallback` receiver `webhook_configs` add (template snippet)

**Edit**: `helm-values/kube-prometheus-stack/values-prod.yaml`

Mevcut (dormant state, ADR-0027 §D1 canonical):
```yaml
      - name: direct-fallback
        email_configs:
          - to: notify-ops@acik.com
            ...
```

Reactivation ekle (PR #1053 closed diff template snippet — Codex `019e5ba9` iter-2 Q1 Option A absorb):
```yaml
      - name: direct-fallback
        webhook_configs:
          - url_file: /etc/alertmanager/secrets/alertmanager-fallback-secrets/TEAMS_WEBHOOK_URL
            send_resolved: true
            max_alerts: 50
            # Alertmanager v4 generic JSON; Power Automate flow parse + Adaptive Card transform
        email_configs:
          - to: notify-ops@acik.com
            ...
```

Aynı pattern `values-test-d43-drill.yaml` test cluster için.

> **V2.1 Perf Alerts (`perf-alerts-slack` / `perf-alerts-teams`) scope DIŞI** (Codex `019e5bdb` iter-2 P2 absorb): D43 outage fallback `direct-fallback` receiver Teams reactivation bu runbook scope'unda. Perf alerts kendi migration runbook + ADR'a tabidir (separate future PR/ADR). Mevcut active config `perf-alerts-slack` ADR-0027 §D1 D43 canonical kapsamında değil — etkilenmez.

**Helm upgrade**:
```bash
ssh halil@staging-sw '
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f helm-values/kube-prometheus-stack/values-prod.yaml \
  --kube-context k3d-prod \
  --atomic \
  --timeout 5m
'
```

**Verify**:
```bash
kubectl --context k3d-prod -n monitoring rollout status \
  statefulset/alertmanager-kube-prometheus-stack-alertmanager --timeout=180s

# amtool config verify
POD=$(kubectl --context k3d-prod -n monitoring get pod -l app.kubernetes.io/name=alertmanager -o jsonpath="{.items[0].metadata.name}")
kubectl --context k3d-prod -n monitoring exec "$POD" -c alertmanager -- \
  amtool config show | grep -A 5 direct-fallback
# Beklenen: webhook_configs url_file: TEAMS_WEBHOOK_URL + email_configs (dual leg)

# Secret mount verify
kubectl --context k3d-prod -n monitoring exec "$POD" -c alertmanager -- \
  ls -la /etc/alertmanager/secrets/alertmanager-fallback-secrets/
# Beklenen: 5 file (TEAMS_WEBHOOK_URL + 4 SMTP)
```

### Step 5: Synthetic Alertmanager API POST smoke + triple receipt verify

> **HARD RULE TEST + PROD Cluster Scale-to-Zero YASAK**: Synthetic API POST kullanılır; `scale=0` legacy alternatifi YASAK (ADR-0027 §D5 + R27 mitigation pattern).

```bash
# Port-forward
kubectl --context k3d-prod -n monitoring port-forward \
  svc/alertmanager-kube-prometheus-stack-alertmanager 9093:9093 &
PF_PID=$!
trap 'kill $PF_PID 2>/dev/null || true' EXIT
sleep 3

# Synthetic NotifyServiceDown alert
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
      "description": "D43 Teams reactivation smoke — ADR-0027 §D5 Step 5"
    },
    "startsAt": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "endsAt": "'$(date -u -d '+10 minutes' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v+10M +%Y-%m-%dT%H:%M:%SZ)'"
  }]'

sleep 10  # Alertmanager dispatch + Power Automate flow trigger

# Triple receipt verify:
# 1. Teams Adaptive Card receipt (manuel görsel + flow run-history)
echo "Manuel: Teams 'D43 Outage' channel → Adaptive Card alındı mı?"
echo "Manuel: Power Automate flow run-history → status=Success, run ID kaydet"

# 2. SMTP receipt (Mailpit veya Office 365 inbox)
echo "Manuel: notify-ops@acik.com inbox → '[D43 PROD] NotifyServiceDown' email"

# 3. GitHub Issue receipt (alarm-receiver-bridge)
gh issue list --repo Halildeu/platform-k8s-gitops --search "NotifyServiceDown" --limit 1

# Recovery: synthetic alert silence/expire (NOT scale-up)
curl -sS -X POST http://localhost:9093/api/v2/silences \
  -H 'Content-Type: application/json' \
  -d '{"matchers": [{"name": "alertname", "value": "NotifyServiceDown", "isRegex": false}], "startsAt": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'", "endsAt": "'$(date -u -d '+5 minutes' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v+5M +%Y-%m-%dT%H:%M:%SZ)'", "createdBy": "d43-teams-reactivation-smoke", "comment": "ADR-0027 §D5 Step 5 cleanup"}'

kill $PF_PID
```

### Step 6: Audit + risk register status update

- [ ] Evidence doc: `docs/faz-23-evidence/2026-XX-XX-d43-teams-reactivation-evidence.md` — pre/during/post snapshot + Teams Adaptive Card screenshot + Power Automate flow run-history JSON + SMTP screenshot + GitHub Issue link + ADR-0027 §D5 6-step chain compliance
- [ ] Risk register R27: `⏳ DEFER asset-preserved` → `🟢 Mitigated active` (7-step mitigation chain operational evidence)
- [ ] Risk register R9: `🟢 Mitigated (SMTP-only D43 v1; Slack DEFER)` → `🟢 Mitigated (SMTP + Teams dual; Teams reactivated)` (R9 mitigation row extend)
- [ ] ADR-0027 Status: `Accepted` → `Accepted + Activated` (Implementation State line update)
- [ ] PR açıldığında commit message: `feat(d43): Teams reactivation activated — ADR-0027 §D5 6-step chain; Codex 019e5bdb authorize`

---

## 4. Rollback (Step herhangi bir aşamada fail)

> **HARD RULE — ATOMIC**: Tüm önceki adımlar revert + audit log.

### Step 1 fail (Power Automate flow setup)
- Flow silinmemişse: flow detail view → ... → Delete
- Exported package backup audit log'a kaydedilmez (yarım kayıt)
- Reactivation chain abort + ADR-0027 §D3 trigger condition reassess

### Step 2 fail (Vault seed)

> **HARD RULE — SMTP CANONICAL KORUMA**: Vault `kv/platform/alertmanager-fallback` path'i SMTP 4-key D43 v1 canonical (ADR-0027 §D1). Full path delete YASAK — SMTP keys silinirse D43 fallback komple çöker.

- **Önerilen rollback** (SMTP-safe): `vault kv patch kv/platform/alertmanager-fallback -mount=kv TEAMS_WEBHOOK_URL=""` (sadece TEAMS_WEBHOOK_URL alanını boşaltır; SMTP_HOST/PORT/USER/PASSWORD 4 key intact)
- **Doğrulama**: `vault kv get -mount=kv -format=json platform/alertmanager-fallback | jq '.data.data | keys'` — SMTP 4 key hâlâ mevcut
- **Break-glass YASAK** (operational truth korumak için): `vault kv metadata delete kv/platform/alertmanager-fallback` (full path delete) **YALNIZ** path compromise durumunda (token leak vb.) **VE** aynı adımda SMTP 4-key reseed ile (RB-prod-alertmanager-activation.md §3.2 SMTP-only re-init pattern); aksi halde D43 SMTP canonical bozulur
- Step 3+ skip; reactivation abort

### Step 3 fail (ESO sync)
- ExternalSecret manifest revert (kustomize remove TEAMS_WEBHOOK_URL secretKey)
- `kubectl apply -k` redeploy
- ESO force-sync sonrası `Ready=True` doğrula
- Step 4+ skip; reactivation abort

### Step 4 fail (Helm upgrade)
- `helm rollback kube-prometheus-stack <pre-rev>` (PR-1 Helm activation runbook §4.4 pattern)
- amtool config verify rollback success (dormant state)
- Step 5+ skip; reactivation abort

### Step 5 fail (Smoke triple receipt)
- Synthetic alert silence/expire (curl POST /api/v2/silences)
- Step 4'teki helm rollback uygula (Teams dormant'a geri dön)
- Audit log: hangi receipt leg fail etti (Teams Adaptive Card? Flow run-history? SMTP? GitHub Issue?)
- Reactivation iter retry (Step 1'den başla) veya abort + ADR-0027 §D3 trigger condition reassess

---

## 5. R27 Mitigation Chain Operational Evidence (post-Step 6)

R27 7-step mitigation chain compliance (Codex `019e5ba9` iter-4 absorb):

| # | Mitigation | Status check |
|---|---|---|
| 1 | Service-account/team-owned flow | Step 1 pre-flight: hesap ownership |
| 2 | Exported flow package backup | Step 1.5 + 1.6 .zip artifact |
| 3 | Monthly synthetic Teams smoke | Step 6 calendar reminder + monthly run-history audit |
| 4 | Defense-in-depth (Teams + SMTP + GitHub Issue) | Step 5 triple receipt |
| 5 | Tenant DLP/license/quota preflight | Step 2.1 + 2.2 + 2.3 prereqs |
| 6 | Flow run-history failed-run monitoring | Step 1.7 + Step 6 audit log |
| 7 | URL rotation rehearsal | Step 2 stdin pipe pattern + ESO 1h refresh-interval auto-pickup |

---

## 6. References

- **ADR-0027** (D43 Teams Power Automate Defer): D1-D6 decisions
- **Codex thread `019e5bdb`** (hibrit C strategic AGREE 2026-05-25)
- **Codex thread `019e5b9c`** (SMTP-only D43 v1 canonical — antecedent canonical)
- **Codex thread `019e5ba9`** (Teams Power Automate pivot — antecedent audit-only superseded; PR #1053 closed diff template reference)
- **PR #1053 closed diff**: helm-values + ESO + runbook snippet templates (audit reference)
- **RB-notification-outage-fallback.md**: D43 outage fallback runbook (SMTP canonical path)
- **RB-prod-alertmanager-activation.md**: prod helm upgrade + acceptance smoke matrix
- **Risk register R9** (SMTP-only D43 v1) + **R27** (Teams Power Automate dormant)
- **HARD RULE Pre-Production Full Authority** (CLAUDE.md global, 2026-04-29)
- **HARD RULE TEST + PROD Cluster Scale-to-Zero YASAK** (2026-05-10)
