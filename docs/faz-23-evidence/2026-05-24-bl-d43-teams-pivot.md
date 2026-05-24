# BL-D43-TEAMS-PIVOT — D43 Outage Fallback Slack → Microsoft Teams Pivot (2026-05-24)

> **Status**: Source-side LIVE — gitops + ESO + docs closed
> **Trigger**: Kullanıcı kararı 2026-05-24 — "slack kullanmıyoruz teams kullanıyoruz"
> **Codex strategic verdict**: thread `019e5ba9` REVISE / `ready_for_impl: true` / `pr_count_estimate: 1 PR` / `agent_actionable_in_session: true`
> **Scope**: Sadece D43 outage fallback alarm routing (Alertmanager → external) — notification adapter (T4.1) Teams zaten LIVE (PR #272), Slack adapter (PR #271) dormant kalır

## 1. Bağlam

### Önceki State
- D43 outage fallback (Alertmanager → external channel notification-orchestrator down olduğunda) `slack_configs` kullanımıyla yapılandırılmıştı
- BL-008 2026-05-24 mock-receipt drill webhook-receiver POST `/slack-mock` + Mailpit SMTP dual-receipt ile R9 → 🟢 mitigated
- Real Slack workspace #853 + prod activation #854 ext-bound

### Kullanıcı Kararı
> "slack kullanmıyoruz. teams kullanıyoruz. onu için tamamladık mı"

Organizasyon Microsoft 365 / Teams kullanıyor; Slack adapter (PR #271) dormant. T4.1 user notification topic için Teams adapter zaten LIVE (PR #272 — TeamsWebhookAdapter + Adaptive Card sha-f40aa82). Ama D43 outage fallback Slack-varsayımındaydı — pivot gerekti.

## 2. Codex Strategic Consult (thread `019e5ba9`)

| Q | Karar |
|---|---|
| Q1 — Alertmanager Teams strateji | **Opsiyon A**: Alertmanager `webhook_configs.url_file` → Microsoft Teams Power Automate workflow incoming HTTP endpoint. Ham v4 webhook JSON; Power Automate flow parse + Adaptive Card post. (Reddedildi: msteams adapter ek workload + ikinci arıza yüzeyi; native template Adaptive Card legacy connector deprecated 2024-Q4) |
| Q2 — Vault path/key naming | Vault **path korunur** (`kv/platform/alertmanager-fallback`, `kv/platform/perf-alertmanager`); sadece secret **key rename** `SLACK_WEBHOOK_URL` → `TEAMS_WEBHOOK_URL`. K8s Secret adı aynı. Yeni path policy/ESO/runbook churn gereksiz |
| Q3 — Receiver naming + route | `perf-alerts-slack` → `perf-alerts-teams` (vendor-semantik düzeltme). `direct-fallback` adı **vendor-neutral korunur**. Teams+SMTP combine devam (`continue:true` `alarm-receiver-bridge` legs aynen) — 3-channel defense-in-depth |
| Q4 — Mock-receipt drill | Yeni Teams mock-receipt drill gerek (manifest sonrası agent test cluster'da). Receiver tipi `slack_configs` → `webhook_configs`, secret key path değişiyor, payload formatı farklı. BL-008 evidence historical kalır + Teams pivot supersedes wording |
| Q5 — Board issues #853+#854 | **Kapat, yeni Teams issue aç**. (a) Teams Power Automate workflow setup for Alertmanager fallback/perf receivers — operator-owned; (b) D43 Alertmanager Teams fallback prod activation + smoke — operator |
| Q6 — Backend Slack adapter | **Dormant kalsın**; bu PR scope DIŞI. T4.1.1 backend user-notification topic adapter yüzeyi farklı sistem. Cleanup ayrı platform-backend + GitOps çalışma yüzeyi |

### Risk Register Impact
- **R9 revize**: Slack dili → Teams Power Automate flow + Teams prod activation; status "🟢 Mitigated (mock-receipt, Teams-pivot reverify pending)"
- **R27 R-NEW**: Microsoft Teams Power Automate workflow lifecycle / owner / tenant policy drift breaks D43 outage Teams channel (Severity Medium; 5-step mitigation chain — service-account flow + exported backup + monthly synthetic smoke + defense-in-depth)

## 3. Repo Değişimi (Source-Side Closure)

### helm-values (Alertmanager config)
| Dosya | Değişim |
|---|---|
| `helm-values/kube-prometheus-stack/values-prod.yaml` | 3 receiver block: `perf-alerts-slack` → `perf-alerts-teams` (Slack name 2 route'ta), `direct-fallback` block `slack_configs` → `webhook_configs` (url_file: TEAMS_WEBHOOK_URL; Slack channel/title/text Adaptive Card template kaldırıldı — Alertmanager v4 webhook generic JSON, Power Automate flow parse) |
| `helm-values/kube-prometheus-stack/values-test-d43-drill.yaml` | `direct-fallback` block `slack_configs` → `webhook_configs`; comment + Codex thread reference |

### ESO ExternalSecret (Vault key rename)
| Dosya | Değişim |
|---|---|
| `kustomize/overlays/prod/eso/alertmanager/externalsecret-alertmanager-fallback.yaml` | `secretKey` ve `property`: `SLACK_WEBHOOK_URL` → `TEAMS_WEBHOOK_URL`; header comment Teams pivot note + operator init dokuman |
| `kustomize/overlays/test/eso/alertmanager/externalsecret-alertmanager-fallback.yaml` | Aynı pivot |
| `kustomize/overlays/prod/eso/alertmanager/externalsecret-perf-alertmanager.yaml` | Aynı pivot |
| `kustomize/overlays/test/eso/alertmanager/externalsecret-perf-alertmanager.yaml` | Aynı pivot |

### Docs
| Dosya | Değişim |
|---|---|
| `docs/notify/risk-register.md` | R9 mitigation row Teams pivot note + status "🟢 Mitigated (mock-receipt, Teams-pivot reverify pending)"; **R27 EKLENDİ** (Power Automate lifecycle drift); Risk Review History 2026-05-24 BL-D43-TEAMS-PIVOT entry |
| `docs/notify/feature-matrix.md` | Snapshot status update 2026-05-24 BL-D43-TEAMS-PIVOT entry; §15 O1+O2 "Teams-pivot reverify pending"; §2 B16 paralel |
| `docs/notify/sprint-plan.md` | T1.4 ana note + T1.4.8 row + Total Session 49 status + Last update — Teams pivot mention |
| `docs/notify/milestones.md` | T1.4 23.2.D row + R9 entry — Teams pivot mention + R27 ekle |

### Backward-Compat
- Eski `SLACK_WEBHOOK_URL` Vault path'te rollback window boyunca tutulabilir; ama yeni desired-state Teams. Operator Teams seed sonrası eski Slack key Vault'tan silinebilir (P2 cleanup, operator action)
- Slack adapter backend (T4.1.2 PR #271) dormant kalır — silinmez (Q6 absorb)

## 4. Build Sanity (PR-time)

```bash
kubectl kustomize kustomize/overlays/test 2>&1 | grep -E "(error|Error)" | head -5
kubectl kustomize kustomize/overlays/prod 2>&1 | grep -E "(error|Error)" | head -5
```

Build temiz — error yok. TEAMS_WEBHOOK_URL keylar yerinde, secretKey resolved.

## 5. Operator Action (Source-Side Closure SONRASI)

### Operator Step 1 — Microsoft Teams Power Automate Workflow Setup
1. Microsoft 365 Power Automate'a giriş (admin or service-account)
2. Flow: **"When an HTTP request is received"** trigger
3. Action: **"Post adaptive card in a chat or channel"** → target Teams channel
4. JSON schema parse (Alertmanager v4 webhook):
   ```json
   {
     "type": "object",
     "properties": {
       "alerts": {"type": "array"},
       "status": {"type": "string"},
       "groupLabels": {"type": "object"},
       "commonLabels": {"type": "object"},
       "commonAnnotations": {"type": "object"}
     }
   }
   ```
5. Adaptive Card body: alertname + severity + namespace + cluster + description + runbook_url
6. Save flow → copy **HTTP POST URL** (Power Automate workflow webhook)
7. Flow ownership: **service-account or team-owned** (R27 mitigation — bireysel owner YASAK)
8. Exported flow package (`.zip`) artifact backup → runbook ekle

### Operator Step 2 — Vault Seed
```bash
# Test cluster
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test \
  vault kv put kv/platform/alertmanager-fallback \
    TEAMS_WEBHOOK_URL=<Teams Power Automate workflow URL — test target channel> \
    SMTP_HOST=mailpit.platform-test.svc.cluster.local \
    SMTP_PORT=587 \
    SMTP_USER=alertmanager-fallback@local \
    SMTP_PASSWORD=<non-empty>

docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test \
  vault kv put kv/platform/perf-alertmanager \
    TEAMS_WEBHOOK_URL=<Teams Power Automate workflow URL — perf-alerts target channel>

# Prod cluster
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-prod \
  vault kv put kv/platform/alertmanager-fallback \
    TEAMS_WEBHOOK_URL=<Teams Power Automate workflow URL — D43 outage prod channel> \
    SMTP_HOST=<prod SMTP relay> \
    SMTP_PORT=587 \
    SMTP_USER=alertmanager-fallback@<prod-domain> \
    SMTP_PASSWORD=<fallback user password>

docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-prod \
  vault kv put kv/platform/perf-alertmanager \
    TEAMS_WEBHOOK_URL=<Teams Power Automate workflow URL — perf-alerts prod channel>
```

### Operator Step 3 — ESO Force-Sync
```bash
kubectl --context k3d-test -n monitoring annotate externalsecret alertmanager-fallback-secrets force-sync="$(date +%s)" --overwrite
kubectl --context k3d-test -n monitoring annotate externalsecret perf-alertmanager-secrets force-sync="$(date +%s)" --overwrite

kubectl --context k3d-prod -n monitoring annotate externalsecret alertmanager-fallback-secrets force-sync="$(date +%s)" --overwrite
kubectl --context k3d-prod -n monitoring annotate externalsecret perf-alertmanager-secrets force-sync="$(date +%s)" --overwrite
```

### Operator Step 4 — Helm Upgrade (Test + Prod)
```bash
# Test cluster (drill override)
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --kube-context k3d-test \
  -n monitoring \
  -f helm-values/kube-prometheus-stack/values-test.yaml \
  -f helm-values/kube-prometheus-stack/values-test-d43-drill.yaml

# Prod cluster
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --kube-context k3d-prod \
  -n monitoring \
  -f helm-values/kube-prometheus-stack/values-prod.yaml
```

### Operator Step 5 — Synthetic NotifyServiceDown Smoke (Test Cluster, scale=0 YASAK)
Alertmanager API synthetic alert POST (HARD RULE TEST Cluster Scale-to-Zero YASAK uyumlu — orchestrator scale=0 yapılmıyor):

```bash
# Test cluster Alertmanager API'ye synthetic alert POST
kubectl --context k3d-test -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093:9093 &
PF_PID=$!
sleep 3

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

kill $PF_PID

# Verify webhook-receiver POST 200 + Mailpit SMTP
kubectl --context k3d-test -n platform-test logs deploy/webhook-receiver --tail=20 | grep "/teams-mock\|POST /"
kubectl --context k3d-test -n platform-test port-forward svc/mailpit 8025:8025 &
# Browser: http://localhost:8025 — [D43 DRILL] NotifyServiceDown mail görmeli
```

### Operator Step 6 — Real Teams Channel Receipt (Prod)
- Prod Alertmanager API synthetic NotifyServiceDown
- Teams channel'da Adaptive Card geldi mi görsel kanıt (screenshot)
- SMTP receipt
- alarm-receiver-bridge GitHub Issue oluştu mu

## 6. Board Issues — Slack Issues Kapat + Teams Yeni Aç

### Eski (kapatılacak — superseded by Teams pivot)
- #853 — Slack workspace webhook setup for D43 outage drill
- #854 — D43 outage fallback prod activation (Slack)

### Yeni (açılacak — Codex Q5 Opsiyon b absorb)
1. **Teams Power Automate workflow setup for Alertmanager fallback/perf receivers**
   - Owner: ops (service-account or team-owned flow)
   - Acceptance: Flow live + URL captured + exported package backup runbook'ta + R27 mitigation chain (5-step) implemented
2. **D43 Alertmanager Teams fallback prod activation + smoke**
   - Owner: ops
   - Acceptance: Vault seed (TEAMS_WEBHOOK_URL test + prod) + ESO sync + helm upgrade + synthetic Alertmanager API POST + Teams Adaptive Card receipt + SMTP receipt + GitHub Issue receipt (3-channel defense-in-depth)

## 7. HARD RULE Compliance

- ✅ **Pre-Production Full Authority**: agent + Codex consensus, kullanıcıya plan onayı sorulmadı (Plan Consensus Autonomy)
- ✅ **No Closure Language**: "Source-side LIVE" — Teams reverify pending operator chain ile devam
- ✅ **Cross-AI Peer Review (provider-different)**: Codex iter-2 post-impl review (PR aç sonrası)
- ✅ **Admin Merge YASAK**: CI yeşil bekleyecek, normal squash
- ✅ **TEST Cluster Scale-to-Zero YASAK**: Synthetic Alertmanager API POST kullanılıyor (orchestrator scale=0 değil)
- ✅ **Kullanıcı login user dokunmadı**: ServiceAccount/operator credentials
- ✅ **Türkçe evidence + İngilizce kod-paylaşılan teknik artifact**
- ✅ **No Fake Work**: helm-values + ESO + docs concrete source-side change; build sanity geçti; operator chain runbook'ta net

## 8. Sıradaki Aksiyon (D43-TEAMS-5)

1. ✅ Source-side closure (this PR) — helm + ESO + docs
2. ⏳ PR aç + Codex iter-2 post-impl review (cross-AI peer review)
3. ⏳ AGREE → normal squash merge + ai-post-merge-cleanup
4. ⏳ Operator activation chain (Step 1-6 above)
5. ⏳ Teams reverify drill evidence doc (yeni evidence dosyası — operator chain sonrası)

**Source-side scope tam tamamlandı — kalan iş operator-bound (Teams Power Automate flow + Vault seed + helm upgrade + smoke).**
