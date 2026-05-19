# RB-prod-alertmanager-activation — Prod Alertmanager release activation packet

> **Status**: READY (staged config + activation prereq packet — 2026-05-19, Session 42)
> **Tracker**: [#857](https://github.com/Halildeu/platform-k8s-gitops/issues/857) — P0 prod Alertmanager release drift
> **Codex thread**: `019e4256` (Session 42 audit + scope verdict)
> **Sibling issues**: [#853](https://github.com/Halildeu/platform-k8s-gitops/issues/853) test sentinel; [#854](https://github.com/Halildeu/platform-k8s-gitops/issues/854) D43 prod activation
> **Risk**: HIGH (3-channel monitoring delivery gap), `ready_for_helm_upgrade=false` until §2 artifacts complete

---

## 1. Bağlam

Prod `kube-prometheus-stack` Helm release (revision 2, last upgrade 2026-05-14) **`values-prod.yaml`'da tanımlı V2.1 Ops-A + GitHub Issues + D43 receiver desired-state'inin hiçbirini taşımıyor**. Live Alertmanager config sadece `alarm-receiver-bridge` (single webhook) + 2 severity route. Bu durum:

- V2.1 Ops-A perf alarmlarının Slack DUAL delivery'sini blokluyor (sadece bridge → GitHub Issues yolundan akıyor)
- D43 outage fallback'in prod'da hiç aktif olmamasına yol açıyor (NotifyServiceDown firing → alarm-receiver-bridge fallback eksik)
- PR #855 staged config'in cluster'a yansımasını engelliyor

**Bu doc**: prod Alertmanager activation öncesi **owner artifact checklist** + **agent activation commands** + **acceptance smoke matrix** + **rollback procedure**. `helm upgrade` çağrılmadan önce §2'deki tüm artifact'ler eksiksiz olmalıdır.

---

## 2. Owner artifact checklist

### 2.1 Slack admin artifact'leri (3 incoming webhook URL)

> **HARD RULE**: webhook URL'leri PR body'sine veya issue comment'ine plaintext yazılmaz. Operator Vault'a doğrudan seed eder; agent sadece file path veya redacted hash referansı kullanır.

| # | Channel | Workspace | Webhook URL field | Kullanım | Status |
|---|---|---|---|---|---|
| 1 | `#perf-alerts` | acik prod workspace | `kv/platform/perf-alertmanager.SLACK_WEBHOOK_URL` | V2.1 Ops-A perf-alerts-slack receiver | ⏳ owner |
| 2 | `#alerts-d43-drill` (veya `#prod-outage-alerts`) | acik prod workspace | `kv/platform/alertmanager-fallback.SLACK_WEBHOOK_URL` | D43 direct-fallback receiver (NotifyServiceDown bypass) | ⏳ owner |
| 3 | (sibling) `#alerts-d43-drill` for **test** | acik test workspace (veya aynı workspace) | `kv/platform/alertmanager-fallback.SLACK_WEBHOOK_URL` test Vault | Test drill — board #853 (real webhook replaces sentinel `drill-slack-mock.local`) | ⏳ owner |

**Operator step**:
1. Slack workspace admin → Apps → Incoming Webhooks → Add (per channel, 1 URL each)
2. URL'leri güvenli operator notebook'a kaydet (Vault seed komutu sırasında stdin pipe)

### 2.2 GitHub PAT (`github-issues-receiver-token` Secret)

> **HARD RULE**: PAT plaintext PR/issue body'sine yazılmaz; operator kubectl create secret komutunda stdin pipe kullanır.

| Field | Detay |
|---|---|
| Scope | `repo`, `workflow` |
| Target | `monitoring/github-issues-receiver-token` Secret (Helm `secrets[]` mount listed) |
| Mount path | `/etc/alertmanager/secrets/github-issues-receiver-token/GITHUB_TOKEN` |
| Lifetime | 90+ gün; rotation reminder GitHub Apps yerine fine-grained PAT pattern'i tercih edilir |
| Creator | Owner (Halildeu account → Settings → Developer settings → Personal access tokens) |

**Operator step**:
```bash
ssh halil@staging-sw
printf %s "<GITHUB_PAT>" | kubectl --context k3d-prod -n monitoring create secret generic github-issues-receiver-token \
  --from-file=GITHUB_TOKEN=/dev/stdin \
  --dry-run=client -o yaml | kubectl --context k3d-prod -n monitoring apply -f -
```

### 2.3 Prod SMTP relay credentials (D43 fallback)

| Field | Detay |
|---|---|
| `SMTP_USER` | `alertmanager-fallback@acik.com` (Microsoft 365 admin tarafında oluşturulur) |
| `SMTP_PASSWORD` | App Password (2FA bypass for SMTP AUTH) |
| Hardcoded in values-prod.yaml | `smarthost: 'smtp.office365.com:587'` (vendor change PR ile, Vault patch ile değil — runbook §6.5.8) |
| Vault path | `kv/platform/alertmanager-fallback.{SMTP_USER, SMTP_PASSWORD}` |

**Operator step**: Microsoft 365 admin → users → manage MFA → App Passwords → create.

---

## 3. Vault prod seed komutları (post §2 artifact)

> Tüm komutlar `ssh halil@staging-sw` üzerinde + `printf %s "..." | docker exec -i ... -from-file=...=/dev/stdin` pattern'i ile (plaintext bash history'ye girmez).

### 3.1 perf-alertmanager (1 key)

```bash
ssh halil@staging-sw '
printf %s "<#perf-alerts WEBHOOK URL>" | \
  docker exec -i -e VAULT_TOKEN="$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)" \
    platform-vault-prod vault kv put kv/platform/perf-alertmanager SLACK_WEBHOOK_URL=-
'
```

Verify (no plaintext output):
```bash
ssh halil@staging-sw '
docker exec -e VAULT_TOKEN="$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)" \
  platform-vault-prod vault kv get -mount=kv -field=SLACK_WEBHOOK_URL platform/perf-alertmanager | wc -c
# Expected: ~50-70 chars (Slack webhook URL standard length)
'
```

### 3.2 alertmanager-fallback (5 keys)

```bash
ssh halil@staging-sw '
ROOT_TOKEN="$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)"
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-prod \
  vault kv put kv/platform/alertmanager-fallback \
    SLACK_WEBHOOK_URL="<#alerts-d43-drill WEBHOOK URL>" \
    SMTP_HOST=smtp.office365.com \
    SMTP_PORT=587 \
    SMTP_USER=alertmanager-fallback@acik.com \
    SMTP_PASSWORD="<APP PASSWORD>"
'
```

Note: bash history risk — operator komut historyden bu komutu temizler veya `set +o history` + `set -o history` pattern'i kullanır.

### 3.3 ESO force-sync + verify

```bash
ssh halil@staging-sw '
for ES in perf-alertmanager-secrets alertmanager-fallback-secrets; do
  kubectl --context k3d-prod -n monitoring annotate externalsecret "$ES" \
    force-sync="$(date +%s)" --overwrite
done

sleep 30

for ES in perf-alertmanager-secrets alertmanager-fallback-secrets; do
  echo "## $ES"
  kubectl --context k3d-prod -n monitoring get externalsecret "$ES" \
    -o jsonpath="{.status.conditions[0].type}={.status.conditions[0].status} reason={.status.conditions[0].reason}{\"\\n\"}"
  kubectl --context k3d-prod -n monitoring get secret "$ES" \
    -o json | jq ".data | to_entries | map({key, value_len: (.value | @base64d | length)})"
done
'
```

Beklenen:
- `perf-alertmanager-secrets`: 1 key non-empty (44+ byte)
- `alertmanager-fallback-secrets`: 5 keys non-empty
- Both: `Ready=True reason=SecretSynced`

---

## 4. Helm upgrade plan

> **HARD RULE**: dry-run + rollback snapshot + Codex review consensus → owner-approved upgrade window → real apply → smoke.

### 4.1 Pre-upgrade snapshot (rollback artifact)

```bash
ssh halil@staging-sw '
helm get values kube-prometheus-stack -n monitoring --kube-context k3d-prod > /tmp/values-pre-857.yaml
helm get manifest kube-prometheus-stack -n monitoring --kube-context k3d-prod > /tmp/manifest-pre-857.yaml
kubectl --context k3d-prod -n monitoring exec alertmanager-kube-prometheus-stack-alertmanager-0 -c alertmanager -- \
  amtool config show > /tmp/amtool-pre-857.txt
helm history kube-prometheus-stack -n monitoring --kube-context k3d-prod > /tmp/history-pre-857.txt
'
```

### 4.2 Dry-run diff

```bash
ssh halil@staging-sw '
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f helm-values/kube-prometheus-stack/values-prod.yaml \
  --kube-context k3d-prod \
  --dry-run --debug > /tmp/dry-run-857.yaml 2>&1
'
```

Owner + agent dry-run diff'i okur; özellikle bekleyen değişimler:
- `Alertmanager` CR `secrets:` field — `[]` → `[perf-alertmanager-secrets, github-issues-receiver-token, alertmanager-fallback-secrets]`
- `Alertmanager` CR `config` field (or generated Secret) — 4 receiver + 7 route
- `Secret/alertmanager-kube-prometheus-stack-alertmanager-generated` — content değişir (new config)
- (Beklenmedik değişim varsa abort)

Plus repo'da `gate-argocd-respect-ignore-diff` static analysis hala PASS (helm-values'da argocd App manifest değişimi yok — gate path filter'ı argocd/applications/'a focus).

### 4.3 Codex review consensus

PR-1 (#855) zaten Codex `019e4234` ile AGREE; mevcut helm upgrade activation step PR olmadan koşulur. Yine de:

- Codex'a dry-run output'unu gönder + verdict iste (`019e4256` thread continue)
- AGREE → owner-approved window + real apply
- REVISE → values-prod.yaml fix iter → new PR + new dry-run

### 4.4 Real upgrade (owner-approved window)

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

`--atomic`: upgrade fail ederse otomatik rollback (revision N+1 rollback to N).
`--timeout 5m`: pod restart + readiness window.

---

## 5. Acceptance smoke matrix

> **HARD RULE**: HTTP smoke + amtool config göstermek tek başına yetmez; **gerçek delivery receipt** (Slack channel mesajı + SMTP inbox + GitHub Issue) zorunlu.

### 5.1 Config + mount verify

```bash
ssh halil@staging-sw '
# Pod restart sonrası yeni pod adını al
POD=$(kubectl --context k3d-prod -n monitoring get pod -l app.kubernetes.io/name=alertmanager -o jsonpath="{.items[0].metadata.name}")
echo "Pod: $POD"

# Config show
kubectl --context k3d-prod -n monitoring exec "$POD" -c alertmanager -- amtool config show | grep -E "^- name:|name: direct-fallback|name: perf-alerts"
# Beklenen: 4 receiver: alarm-receiver-bridge, perf-alerts-slack, perf-alerts-github-issues, direct-fallback

# Routes
kubectl --context k3d-prod -n monitoring exec "$POD" -c alertmanager -- amtool config routes show | head -30

# Mount verify (5+1+1 = 7 files toplam)
kubectl --context k3d-prod -n monitoring exec "$POD" -c alertmanager -- ls -la \
  /etc/alertmanager/secrets/alertmanager-fallback-secrets/ \
  /etc/alertmanager/secrets/perf-alertmanager-secrets/ \
  /etc/alertmanager/secrets/github-issues-receiver-token/
'
```

### 5.2 Synthetic perf alert smoke (V2.1 Ops-A)

```bash
ssh halil@staging-sw '
# Trigger synthetic perf=critical alert (Alertmanager API directly)
kubectl --context k3d-prod -n monitoring port-forward svc/alertmanager-kube-prometheus-stack-alertmanager 9093:9093 &
PF=$!
trap "kill $PF 2>/dev/null || true" EXIT
sleep 3

curl -sX POST http://127.0.0.1:9093/api/v2/alerts -d "$(cat <<JSON
[{
  "labels": {
    "alertname": "PerfCanarySmoke857",
    "team": "perf",
    "severity": "critical",
    "namespace": "monitoring"
  },
  "annotations": {
    "description": "Synthetic perf alert smoke for #857 acceptance"
  }
}]
JSON
)"

# Wait routing + delivery
sleep 10

# Verify
curl -s http://127.0.0.1:9093/api/v2/alerts | jq ".[] | select(.labels.alertname==\"PerfCanarySmoke857\") | {receivers: [.receivers[].name]}"
# Beklenen: receivers contains both perf-alerts-slack AND perf-alerts-github-issues (DUAL delivery, continue:true)
'
```

**Owner verify (channels):**
- Slack `#perf-alerts`: `[V2.1 Perf Alert] PerfCanarySmoke857` mesajı görüldü mü?
- GitHub Issues repo `Halildeu/platform-k8s-gitops`: yeni issue açıldı mı (alertmanager-bridge'in dispatch'inden)?

### 5.3 Synthetic D43 outage smoke (controlled, owner-approved window)

Bu adım runbook'a havale: `docs/runbooks/RB-notification-outage-fallback.md` §6.5.5–6.5.7 sıra (notification-orchestrator scale=0 → 130s → triple receipt → recovery).

### 5.4 Recovery + resolved verify

```bash
# (Perf smoke için manuel resolve gerek yok — Alertmanager sonrasında otomatik resolve)
# D43 smoke için runbook §6.5.7 sıra
```

---

## 6. Rollback procedure

Eğer §5.1 amtool config 4 receiver göstermezse, pod CrashLoopBackOff'a girerse, veya synthetic alert delivery fail ederse:

```bash
ssh halil@staging-sw '
# Helm rollback to revision before upgrade
PRE_REV=$(helm history kube-prometheus-stack -n monitoring --kube-context k3d-prod -o json | jq -r ".[] | select(.status==\"superseded\")" | jq -s ".[-1].revision")
helm rollback kube-prometheus-stack "$PRE_REV" -n monitoring --kube-context k3d-prod

# Verify rollback
helm history kube-prometheus-stack -n monitoring --kube-context k3d-prod | head -5
kubectl --context k3d-prod -n monitoring rollout status statefulset/alertmanager-kube-prometheus-stack-alertmanager --timeout=180s

# amtool config 3-receiver minimal (revert to pre-857 state) verify
kubectl --context k3d-prod -n monitoring exec alertmanager-kube-prometheus-stack-alertmanager-0 -c alertmanager -- amtool config show | grep -A 3 receivers
'
```

Plus audit doc: `docs/faz-23-evidence/2026-XX-XX-857-helm-upgrade-rollback.md`.

---

## 7. References

- **Codex threads**: `019e4256` (Session 42 audit + scope), `019e4234` (PR #855 D43 staged config), `019e41d7`+`019e4216` (managedFields bug class + regression guard), `019e267a` (V2.1 Ops-A perf-alerts-slack), `019e2a4f` (GitHub Issues receiver, PR #645)
- **PRs**: #850 + #851 + #852 + #855 (D43 source-ready chain + governance)
- **Board issues**: #857 (this tracker), #853 (test sentinel), #854 (D43 owner-gated activation)
- **Source**: `helm-values/kube-prometheus-stack/values-prod.yaml`
- **Sibling runbook**: `docs/runbooks/RB-notification-outage-fallback.md` (D43 sub-section §6.5)

---

## 8. Last Update

**2026-05-19 (Session 42 — Codex `019e4256` activation packet)** — Owner artifact checklist + Vault seed commands + helm upgrade dry-run/diff + acceptance smoke matrix + rollback procedure. `ready_for_helm_upgrade=false` until §2 artifacts arrive.
