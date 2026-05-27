# RB-perf-alerts-slack-reactivation-chain — perf-alertmanager Slack Workspace Activation Operator Runbook

> **Status**: READY (asset-preserved dormant; activation owner-gated post-trigger)
> **Trigger conditions**: ADR-0029 §D2 + Pattern mirror ADR-0027 §D3 (multi-tenant Slack workspace demand)
> **Reactivation type**: Atomic 6-step chain (ADR-0029 §D6 mandatory; Codex `019e6b24` REVISE→AGREE verdict)
> **Codex thread**: `019e6b24` (Hibrit D verdict + reactivation chain authorize)
> **Pattern emsali**: [RB-d43-teams-reactivation-chain.md](RB-d43-teams-reactivation-chain.md) (D43 Teams reactivation mirror — Hibrit C ↔ Hibrit D yapısal eşleştirme)
> **Risk**: ADR-0029 D5 multi-tenant pattern semantik (current state `dormant asset-preserved`; reactivation sonrası `🟢 Mitigated active` tenant-scoped)

---

## 1. Tetikleyici Conditions (ADR-0029 §D2 + D5 multi-tenant flexibility)

Reactivation chain yalnız aşağıdaki tetik koşullarından **en az biri** geldiğinde başlatılır:

1. **Başka tenant Slack workspace ile sisteme katılır** — perf-alertmanager kanal hedefi olarak Teams yerine Slack tercih (tenant org policy / kurulu workspace asset)
2. **acik tenant Microsoft Teams Power Automate workflow lifecycle break** — R29 active drift fail (license expire, DLP policy block, quota exhaustion); Slack fallback için kritik
3. **Compliance/audit requirement** — bir tenant compliance gereği perf alert audit trail Slack workspace'inde tutulmak zorunda
4. **Multi-tenant flexibility demand** — explicit owner kararı: hem Teams (acik) hem Slack (başka tenant) parallel destek
5. **Operator/security tactical decision** — incident visibility için Slack channel daha hızlı triage sağlar (ops decision per tenant)

**Trigger değil** (reactivation başlamaz):
- "Slack neden yok ki" tipi UX merak (asset-preserved dokümante ile yeterli)
- Marketing/visibility-only desire (operational dependency olmadan)
- Single-issue ad-hoc Slack post request (one-shot ops Slack direct post yeterli)

---

## 2. Pre-Activation Prerequisites

Reactivation başlamadan önce ADR-0029 D5 multi-tenant disiplin gereksinimleri kanıtlanır:

### 2.1 Slack workspace preflight

- [ ] **Slack workspace admin onayı**: Tenant Slack workspace admin'i webhook üretmeye yetkili (Apps → Manage permissions → Incoming Webhooks integration enabled)
- [ ] **Target channel hazır**: `#perf-alerts` (veya tenant-tercih kanal) workspace'te mevcut
- [ ] **Service-account vs personal**: Webhook üreten Slack user TERCİHEN service-account / bot-account (R29 lifecycle drift mitigation per-tenant); personal account = future drift risk
- [ ] **Webhook URL rotation policy**: Tenant Slack workspace webhook rotation cycle dokümante (R29 mitigation chain)

### 2.2 Cluster prereqs

- [ ] **Vault tenant-scoped path**: `kv/platform/perf-alertmanager.SLACK_WEBHOOK_URL` (single-tenant) veya `kv/platform/tenants/<tenant>/perf-alertmanager.SLACK_WEBHOOK_URL` (multi-tenant scoped)
- [ ] **ESO ClusterSecretStore reachable** — `monitoring` ns (mevcut)
- [ ] **Helm + kubectl k3d-prod context erişimi**: `helm upgrade` + `kubectl annotate externalsecret force-sync` rights
- [ ] **Vault root token + policy update right**: `eso-runtime` policy `kv/data/platform/perf-alertmanager` (veya tenant-scoped path) read capability

### 2.3 ADR-0029 D5 tenant-scoping decision

- [ ] **Scope kararı**: Single-tenant (acik = Slack global) mi yoksa multi-tenant (acik=Teams + başka tenant=Slack) mi? Receiver/route matcher matrix bu karara bağlı

---

## 3. Atomic 6-Step Reactivation Chain

> **HARD RULE — ATOMIC**: Parçalı aktivasyon YASAK (ADR-0029 §D2). Tüm 6 adım owner-approved window'da arka arkaya çalıştırılır; herhangi bir adımda fail → tüm önceki adımlar revert + audit log.

### Step 1: Slack Incoming Webhook URL üret (tenant workspace admin)

**1.1 Tenant Slack workspace admin → Apps → Manage → Custom Integrations → Incoming Webhooks**:
- Channel seç: `#perf-alerts` veya tenant-tercih kanal
- "Add to Slack" → Webhook URL kopyala
- Format: `https://hooks.slack.com/services/T<TEAM_ID>/B<BOT_ID>/<TOKEN>`

**1.2 Service-account audit log entry**: Slack admin audit log'da hangi service-account/bot ile üretildi kayıt edilir (R29 lifecycle drift trace için)

### Step 2: Vault seed (Slack webhook URL)

```bash
# Webhook URL'i gizli giriş
read -r -s SLACK_PERF_WEBHOOK
# yapıştır + Enter

# Shape sanity check
[[ "$SLACK_PERF_WEBHOOK" =~ ^https://hooks\.slack\.com/services/ ]] && echo "URL prefix OK" || echo "FAIL"

export VAULT_ROOT_TOKEN=$(ssh halil@staging-sw 'jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json')

# Single-tenant pattern (acik scope dahil):
ssh halil@staging-sw "docker exec -e VAULT_TOKEN='$VAULT_ROOT_TOKEN' -e WEBHOOK='$SLACK_PERF_WEBHOOK' platform-vault-prod \
  vault kv patch kv/platform/perf-alertmanager SLACK_WEBHOOK_URL=\"\$WEBHOOK\""

# Veya multi-tenant pattern (separate tenant path):
# vault kv put kv/platform/tenants/<tenant>/perf-alertmanager SLACK_WEBHOOK_URL=\"\$WEBHOOK\"
```

**Beklenen**: Vault `kv/platform/perf-alertmanager` (veya tenant-scoped) `SLACK_WEBHOOK_URL` key non-empty.

### Step 3: Vault policy update (ESO runtime AppRole read capability)

```bash
# Policy zaten kv/data/platform/perf-alertmanager için read capability içeriyor (ADR-0029 PR-2 helm/ESO setup'tan)
# Multi-tenant pattern için ek policy snippet:
ssh halil@staging-sw 'docker exec -i -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-prod \
  sh -c "cat > /tmp/eso-runtime-slack.hcl" <<EOF
path \"kv/data/platform/perf-alertmanager\" { capabilities = [\"read\"] }
# Multi-tenant alternatif:
# path \"kv/data/platform/tenants/+/perf-alertmanager\" { capabilities = [\"read\"] }
EOF
docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-prod \
  vault policy write eso-runtime /tmp/eso-runtime.hcl
docker exec platform-vault-prod rm /tmp/eso-runtime-slack.hcl'
```

### Step 4: ExternalSecret + K8s Secret render (`perf-alertmanager-slack-secrets`)

ExternalSecret manifest oluştur (kustomization'a dahil) — bu Step ile DORMANT snippet ACTIVE olur:

```bash
# Yeni ExternalSecret manifest oluştur: kustomize/overlays/prod/eso/alertmanager/externalsecret-perf-alertmanager-slack.yaml
# (ADR-0029 §D2 Slack dormant snippet template'inden activate)
# Kustomization'a ekle: kustomize/overlays/prod/eso/alertmanager/kustomization.yaml resources[]

git checkout -b ops/perf-alerts-slack-reactivate-tenant-<tenant>
# Manifest commit + git push + cross-AI peer review + merge

# Force-sync (1h beklemeden)
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring annotate externalsecret perf-alertmanager-slack-secrets \
  force-sync="$(date +%s)" --overwrite'

# Verify
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring get externalsecret perf-alertmanager-slack-secrets \
  -o jsonpath="{.status.conditions[0]}"'
```

**Beklenen**: `Ready=True (reason=SecretSynced)`; K8s Secret `perf-alertmanager-slack-secrets` `SLACK_WEBHOOK_URL` key 70-90 char.

### Step 5: Alertmanager helm values + receiver/route activate

Helm values dormant snippet'i activate olarak ekle (ADR-0029 PR-2 emsali; Hibrit D):

```yaml
# helm-values/kube-prometheus-stack/values-prod.yaml additions:
# (multi-tenant matcher pattern; Slack tenant-scoped route)

alertmanager.config.receivers:
  - name: perf-alerts-slack
    slack_configs:
      - api_url_file: /etc/alertmanager/secrets/perf-alertmanager-slack-secrets/SLACK_WEBHOOK_URL
        channel: '#perf-alerts'
        send_resolved: true
        # ... title/text templates per V2.1 runbook §4

alertmanager.config.route.routes:
  - matchers:
      - 'team = perf'
      - 'tenant_channel = slack'   # multi-tenant matcher
    receiver: perf-alerts-slack
    continue: true   # bridge trail için

alertmanager.config.alertmanagerSpec.secrets:
  - perf-alertmanager-slack-secrets   # mount path /etc/alertmanager/secrets/...
```

```bash
# Helm upgrade
ssh halil@staging-sw 'helm upgrade --reuse-values --set-file ... kube-prometheus-stack ...'

# Veya kustomize-only path:
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring apply -k kustomize/overlays/prod/eso/alertmanager'
```

### Step 6: Synthetic alert E2E (Slack delivery proof)

```bash
# Failures=1 patch (5dk sustain)
ssh halil@staging-sw 'kubectl --context k3d-prod -n platform-prod patch cm frontend-federation-smoke-status \
  --type=json -p="[{\"op\":\"replace\",\"path\":\"/metadata/annotations/frontend-federation-smoke.io~1failures\",\"value\":\"1\"}]"'

# 5-6 dk bekle (for: 5m clause + Alertmanager group_wait 30s)

# Alertmanager active alerts firing kanıtı
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring exec alertmanager-kube-prometheus-stack-alertmanager-0 \
  -- wget -qO- http://localhost:9093/api/v2/alerts' | jq '.[] | select(.labels.alertname=="PerfFederationSmokeFailing")'

# Tenant Slack workspace #perf-alerts kanalını manuel kontrol:
# Beklenen: "PerfFederationSmokeFailing" mesajı (FIRING, warning severity)

# Revert
ssh halil@staging-sw 'kubectl --context k3d-prod -n platform-prod patch cm frontend-federation-smoke-status \
  --type=json -p="[{\"op\":\"replace\",\"path\":\"/metadata/annotations/frontend-federation-smoke.io~1failures\",\"value\":\"0\"}]"'

# 5dk sonra Slack'te [RESOLVED] mesajı (send_resolved: true)
```

---

## 4. Acceptance Criteria

- [ ] **Step 1**: Slack workspace webhook URL üretildi (audit trail service-account/bot ile)
- [ ] **Step 2**: Vault `kv/platform/perf-alertmanager` (veya tenant-scoped) `SLACK_WEBHOOK_URL` non-empty seed
- [ ] **Step 3**: Vault `eso-runtime` policy ek kapsam re-apply
- [ ] **Step 4**: ExternalSecret `perf-alertmanager-slack-secrets` `Ready=True (SecretSynced)`; K8s Secret length 70-90 char
- [ ] **Step 5**: Alertmanager config `perf-alerts-slack` receiver + route active; pod mount `/etc/alertmanager/secrets/perf-alertmanager-slack-secrets/SLACK_WEBHOOK_URL`
- [ ] **Step 6**: Synthetic alert E2E — Slack FIRING + RESOLVED 2 mesaj alındı (~6 dk total)

**Closure verdict**: Reactivation success → tenant Slack workspace `#perf-alerts` operational. ADR-0029 D5 multi-tenant pattern bir tenant için active.

---

## 5. Post-Activation Mitigation Chain (R29 mirror-pattern adaptation)

Reactivation sonrası R29 7-step mitigation chain Slack-side ekvivalan (ADR-0027 R27 mirror):

1. **Service-account/team-owned account ownership** — personal account YASAK, audit log her webhook üretiminde
2. **Exported webhook URL backup** — operator vault notebook (R29 mitigation 2)
3. **Monthly synthetic Slack alert smoke** — `#perf-alerts` test mesajı + receipt verify; failure → R29 active drift
4. **Defense-in-depth**: Slack + GitHub Issue (`alarm-receiver-bridge`) + (acik tenant: Teams) — multi-channel coverage
5. **Webhook URL rotation policy** — tenant Slack admin policy review (every 6 ay)
6. **Webhook delivery failure monitoring** — Alertmanager log `Notify attempt failed receiver=perf-alerts-slack` grep alert
7. **URL rotation rehearsal** — yıllık simulated rotation (webhook revoke + new URL Vault seed + ESO refresh + smoke)

---

## 6. Rollback / Dormant Re-activation Revert

Reactivation fail veya tenant churn → Slack dormant'a geri çevir:

1. Helm values `perf-alerts-slack` receiver + route remove
2. ExternalSecret `perf-alertmanager-slack-secrets` manifest remove (kustomization'dan)
3. K8s Secret `perf-alertmanager-slack-secrets` delete (rolling restart Alertmanager)
4. Vault `kv/platform/perf-alertmanager.SLACK_WEBHOOK_URL` key empty veya `vault kv metadata delete <tenant-path>`
5. ADR-0029 R29 row update: tenant-scope dormant return

Reactivation sonraki tetik gelene kadar dormant kalır.

---

## 7. Audit + Cross-AI Peer Review

- **Plan-time (`019e6b24`)**: Hibrit D pattern AGREE; this runbook ADR-0029 §D6 PR-1 docs scope
- **Activation execute audit**: her tenant activation per-PR + cross-AI peer review chain (HARD RULE 2026-05-05/14)
- **R29 lifecycle drift monitoring**: monthly synthetic smoke evidence operator notebook
- **Pattern emsali**: RB-d43-teams-reactivation-chain.md — D43 Teams reactivation mirror

---

## 8. Quick Reference (TL;DR)

| Adım | Süre | Owner | Komut özet |
|---|---|---|---|
| 1. Slack webhook üret | 2 dk | tenant Slack admin | Apps → Incoming Webhooks → URL kopyala |
| 2. Vault seed | 1 dk | ops + Vault root | `vault kv patch kv/platform/perf-alertmanager SLACK_WEBHOOK_URL=...` |
| 3. Vault policy | 1 dk | ops + Vault root | policy write + tenant-scoped path varsa kapsam genişlet |
| 4. ExternalSecret + K8s Secret | 5 dk | ops (PR + force-sync) | manifest commit + cross-AI review + merge + annotate force-sync |
| 5. Helm + receiver/route | 5 dk | ops (helm upgrade) | values-prod.yaml receiver + route + alertmanagerSpec.secrets + apply |
| 6. Synthetic alert E2E | 10-12 dk | ops + agent verify | ConfigMap patch failures=1 → 5dk wait → alert firing → Slack receipt → revert |

**Total**: ~25-30 dk operator window (atomic; parçalı YASAK).

**Pre-activation**: Pre-Production Full Authority HARD RULE — agent execute + cross-AI peer review chain; owner Slack workspace setup tek dış adım.
