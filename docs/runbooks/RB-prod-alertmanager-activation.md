# RB-prod-alertmanager-activation — Prod Alertmanager release activation packet

> **Status**: BLOCKED — pending sibling PR `values-prod.yaml` clean-up (`perf-alerts-github-issues` direct receiver + token mount removal, until payload wrapper bridge is added)
> **Tracker**: [#857](https://github.com/Halildeu/platform-k8s-gitops/issues/857) — P0 prod Alertmanager release drift
> **Codex thread**: `019e4256` (Session 42 audit + scope verdict — post-impl REVISE iter-2 P0 absorb)
> **Sibling issues**: [#853](https://github.com/Halildeu/platform-k8s-gitops/issues/853) test sentinel; [#854](https://github.com/Halildeu/platform-k8s-gitops/issues/854) D43 prod activation
> **Risk**: HIGH (3-channel monitoring delivery gap; direct receiver wrapper-bug active until sibling PR merge)
> **`ready_for_helm_upgrade=false`** until:
> 1. Sibling PR removes `perf-alerts-github-issues` direct receiver + `github-issues-receiver-token` mount from `values-prod.yaml` (Codex `019e4256` REVISE iter-2 absorb)
> 2. §2 owner artifacts complete (Slack webhooks + SMTP credentials; GitHub PAT becomes OPTIONAL / future-only)
> 3. Codex dry-run review consensus (separate iter on dry-run output)

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

### 2.2 GitHub PAT (`github-issues-receiver-token` Secret) — **OPTIONAL / future-only**

> **#857 activation için GEREKLİ DEĞİL** (Codex `019e4256` REVISE iter-2 P0 absorb). Sibling PR `values-prod.yaml`'dan `perf-alerts-github-issues` direct receiver + bu Secret'in `secrets[]` mount'unu wrapper bridge gelene kadar kaldıracak. PAT artifact'i ancak wrapper PR'ı sonrası (future work) gerekli.
>
> **HARD RULE**: PAT plaintext PR/issue body'sine yazılmaz; operator `read -r -s` hidden prompt + stdin pipe + `unset` ile çalışır. Bash history + process argv güvenliği yazma anında, sonradan-temizleme ile değil.

| Field | Detay |
|---|---|
| Scope | `repo`, `workflow` |
| Target | `monitoring/github-issues-receiver-token` Secret (Helm `secrets[]` mount listed) |
| Mount path | `/etc/alertmanager/secrets/github-issues-receiver-token/GITHUB_TOKEN` |
| Lifetime | 90+ gün; rotation reminder GitHub Apps yerine fine-grained PAT pattern'i tercih edilir |
| Creator | Owner (Halildeu account → Settings → Developer settings → Personal access tokens) |

**Important — direct receiver KNOWN-BLOCKED**: `perf-alerts-github-issues` Alertmanager receiver (defined in `values-prod.yaml`) sends the raw Alertmanager v4 webhook payload to GitHub `repository_dispatch` API, which requires a `{"event_type":"...","client_payload":{...}}` wrapper that Alertmanager `webhook_configs` does NOT produce. Reference: prior PR #648 was closed RED for exactly this reason (see `docs/session-52-handoff-final-honest-close.md:111`). Therefore:
- This Secret + mount is staged for future activation when a payload wrapper bridge (sidecar/proxy) is added.
- Until then, prod perf alert GitHub Issue trail flows through `alarm-receiver-bridge` → `alertmanager-bridge` pod (which DOES wrap into `client_payload`).
- `#857` acceptance smoke uses `alarm-receiver-bridge` evidence path for GitHub Issue receipt, NOT direct `perf-alerts-github-issues` receiver.

**Operator step**:
```bash
ssh halil@staging-sw '
read -r -s -p "GitHub PAT (repo+workflow scope): " GH_PAT && echo
printf "%s" "$GH_PAT" | kubectl --context k3d-prod -n monitoring create secret generic github-issues-receiver-token \
  --from-file=GITHUB_TOKEN=/dev/stdin \
  --dry-run=client -o yaml | kubectl --context k3d-prod -n monitoring apply -f -
unset GH_PAT
'
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

> **HARD RULE**: webhook URL hidden prompt + stdin pipe + `unset` ile yazılır; literal komut satırında değil (bash history/process argv safety).

```bash
ssh halil@staging-sw '
read -r -s -p "#perf-alerts incoming webhook URL: " WEBHOOK && echo
printf "%s" "$WEBHOOK" | docker exec -i \
  -e VAULT_TOKEN="$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)" \
  platform-vault-prod \
  vault kv put kv/platform/perf-alertmanager SLACK_WEBHOOK_URL=-
unset WEBHOOK
'
```

Verify (no plaintext output, length-only):
```bash
ssh halil@staging-sw '
docker exec -e VAULT_TOKEN="$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)" \
  platform-vault-prod vault kv get -mount=kv -field=SLACK_WEBHOOK_URL platform/perf-alertmanager | wc -c
# Expected: ~50-70 chars (Slack webhook URL standard length)
'
```

### 3.2 alertmanager-fallback (5 keys — secrets via stdin, non-secrets inline)

> Secrets (Slack URL + SMTP password) hidden prompt + stdin pipe ile; non-secrets (HOST/PORT/USER) inline `vault kv patch`. Bu pattern bash history'ye sadece non-sensitive field'ları sızdırır.

```bash
ssh halil@staging-sw '
ROOT_TOKEN="$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)"

# Step 1: Non-secret SMTP host/port/user — inline kv patch (initial put creates the path)
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-prod \
  vault kv put kv/platform/alertmanager-fallback \
    SMTP_HOST=smtp.office365.com \
    SMTP_PORT=587 \
    SMTP_USER=alertmanager-fallback@acik.com

# Step 2: Slack webhook — stdin pipe
read -r -s -p "#alerts-d43-drill incoming webhook URL: " SLACK_URL && echo
printf "%s" "$SLACK_URL" | docker exec -i \
  -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-prod \
  vault kv patch kv/platform/alertmanager-fallback SLACK_WEBHOOK_URL=-
unset SLACK_URL

# Step 3: SMTP App Password — stdin pipe
read -r -s -p "SMTP App Password (alertmanager-fallback@acik.com): " SMTP_PWD && echo
printf "%s" "$SMTP_PWD" | docker exec -i \
  -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-prod \
  vault kv patch kv/platform/alertmanager-fallback SMTP_PASSWORD=-
unset SMTP_PWD

unset ROOT_TOKEN
'
```

Verify (length-only, no plaintext):
```bash
ssh halil@staging-sw '
docker exec -e VAULT_TOKEN="$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)" \
  platform-vault-prod vault kv get -mount=kv -format=json platform/alertmanager-fallback \
  | jq ".data.data | to_entries | map({key, value_len: (.value | length)})"
# Expected: 5 keys; SLACK_WEBHOOK_URL ~50-70 byte; SMTP_PASSWORD ~16-32 byte; others fixed
'
```

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

# Capture PRE_REV as a stable rollback target (current deployed revision).
# Codex 019e4256 P2 absorb: do NOT recompute PRE_REV at rollback time —
# `--atomic` may have already taken history through a rollback cycle, and
# status==superseded scan can pick the wrong revision.
helm history kube-prometheus-stack -n monitoring --kube-context k3d-prod -o json \
  | jq -r "map(select(.status==\"deployed\"))[-1].revision" \
  > /tmp/pre-rev-857.txt
echo "PRE_REV=$(cat /tmp/pre-rev-857.txt)"
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

> Sibling PR (post-#860 merge) `perf-alerts-github-issues` direct receiver + `github-issues-receiver-token` mount'u removes; bu acceptance ona göre **3 aktif receiver + 2 Secret mount**.

```bash
ssh halil@staging-sw '
# Pod restart sonrası yeni pod adını al
POD=$(kubectl --context k3d-prod -n monitoring get pod -l app.kubernetes.io/name=alertmanager -o jsonpath="{.items[0].metadata.name}")
echo "Pod: $POD"

# Config show — 3 active receivers expected
kubectl --context k3d-prod -n monitoring exec "$POD" -c alertmanager -- amtool config show | grep -E "^- name:|name: direct-fallback|name: perf-alerts-slack|name: alarm-receiver-bridge"
# Beklenen: 3 aktif receiver:
#   - alarm-receiver-bridge
#   - perf-alerts-slack
#   - direct-fallback
# (perf-alerts-github-issues direct receiver: sibling PR ile KALDIRILDI — wrapper PR sonrası geri eklenir)

# Routes
kubectl --context k3d-prod -n monitoring exec "$POD" -c alertmanager -- amtool config routes show | head -30

# Mount verify (5+1 = 6 files toplam; github-issues-receiver-token sibling PR ile KALDIRILDI)
kubectl --context k3d-prod -n monitoring exec "$POD" -c alertmanager -- ls -la \
  /etc/alertmanager/secrets/alertmanager-fallback-secrets/ \
  /etc/alertmanager/secrets/perf-alertmanager-secrets/
# Note: /etc/alertmanager/secrets/github-issues-receiver-token/ klasörü YOK (sibling PR ile mount removed)
'
```

### 5.2 Synthetic perf alert smoke — Alertmanager direct API routing test

> **Proves**: Alertmanager config route matching + receiver dispatch (perf-alerts-slack via api_url_file delivery; alarm-receiver-bridge webhook delivery to alertmanager-bridge pod which wraps into GitHub repository_dispatch).
>
> **Does NOT prove**: PrometheusRule fires with `team=perf` labels, real metric path, `for:` clause window. Real production smoke requires either an existing PrometheusRule with `team=perf` OR a controlled rule that fires on a real metric expression (separate acceptance gate).
>
> **Does NOT prove**: `perf-alerts-github-issues` **direct** receiver delivery — this receiver is KNOWN-BLOCKED (see §2.2; Alertmanager `webhook_configs` does NOT wrap payload into GitHub `repository_dispatch` schema). GitHub Issue trail is verified via `alarm-receiver-bridge` route (which dispatches to alertmanager-bridge pod that DOES wrap).

```bash
ssh halil@staging-sw '
# Trigger synthetic perf=critical alert (Alertmanager API directly)
kubectl --context k3d-prod -n monitoring port-forward svc/alertmanager-kube-prometheus-stack-alertmanager 9093:9093 &
PF=$!
trap "kill $PF 2>/dev/null || true" EXIT
sleep 3

curl --fail-with-body -sX POST http://127.0.0.1:9093/api/v2/alerts \
  -H "Content-Type: application/json" \
  -d "$(cat <<JSON
[{
  \"labels\": {
    \"alertname\": \"PerfCanarySmoke857\",
    \"team\": \"perf\",
    \"severity\": \"critical\",
    \"namespace\": \"monitoring\"
  },
  \"annotations\": {
    \"description\": \"Synthetic perf alert smoke for #857 acceptance\"
  }
}]
JSON
)"

# Wait routing + delivery
sleep 10

# Verify — both perf-alerts-slack AND alarm-receiver-bridge should be in receivers
# (perf-alerts-github-issues direct receiver may or may not appear; if present, it
# will not actually deliver — KNOWN-BLOCKED per §2.2.)
curl -s http://127.0.0.1:9093/api/v2/alerts | \
  jq ".[] | select(.labels.alertname==\"PerfCanarySmoke857\") | {receivers: [.receivers[].name]}"
# Expected: receivers contains perf-alerts-slack AND alarm-receiver-bridge (continue:true triple
# delivery path; GitHub Issue receipt flows via alarm-receiver-bridge → alertmanager-bridge pod).
'
```

**Owner verify (channels — only Slack + bridge-driven GitHub Issue):**
- Slack `#perf-alerts`: `[V2.1 Perf Alert] PerfCanarySmoke857` mesajı görüldü mü?
- GitHub Issues repo `Halildeu/platform-k8s-gitops`: yeni issue açıldı mı (**alertmanager-bridge dispatch'inden** — `perf-alerts-github-issues` direct receiver sibling PR ile values-prod.yaml'dan kaldırıldı; payload wrapper bridge gelene kadar future PR konusu)?

**Acceptance**: Slack receipt + bridge-driven GitHub Issue = pass. Direct `perf-alerts-github-issues` receiver delivery is **scope-out of #857 acceptance** AND **scope-out of values-prod.yaml** (sibling PR cleanup) until a payload wrapper bridge is added (separate future PR).

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
# Use PRE_REV captured at §4.1 (stable rollback target — NOT recomputed at
# rollback time, see Codex 019e4256 P2 absorb).
if [ ! -s /tmp/pre-rev-857.txt ]; then
  echo "ERROR: /tmp/pre-rev-857.txt missing — pre-upgrade snapshot did not run, abort manual rollback" >&2
  exit 1
fi
PRE_REV=$(cat /tmp/pre-rev-857.txt)
echo "Rolling back to revision $PRE_REV"

helm rollback kube-prometheus-stack "$PRE_REV" -n monitoring --kube-context k3d-prod

# Verify rollback
helm history kube-prometheus-stack -n monitoring --kube-context k3d-prod | head -5
kubectl --context k3d-prod -n monitoring rollout status statefulset/alertmanager-kube-prometheus-stack-alertmanager --timeout=180s

# amtool config 3-receiver minimal (revert to pre-857 state) verify
kubectl --context k3d-prod -n monitoring exec alertmanager-kube-prometheus-stack-alertmanager-0 -c alertmanager -- \
  amtool config show | grep -A 3 receivers
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

**2026-05-19 (Session 42 PR #860 — Codex `019e4256` REVISE iter-2 P0 absorb)** — Single new finding: known-blocked `perf-alerts-github-issues` direct receiver still live in `values-prod.yaml` would activate on helm upgrade (404/422 fail log spam every perf alert). Absorb (Codex tercih A):
- Runbook front-matter Status: READY → **BLOCKED** until sibling PR cleanup.
- §2.2 GitHub PAT: **OPTIONAL / future-only** (not required for #857 activation; wrapper PR's prereq).
- §5.1 Config verify: 3 aktif receiver (alarm-receiver-bridge + perf-alerts-slack + direct-fallback); 6 mount file (5 fallback + 1 perf); github-issues-receiver-token mount klasörü YOK (sibling PR removed).
- §5.2 Synthetic alert acceptance: Slack + bridge-driven GitHub Issue; direct receiver scope-out at both runbook and values-prod.yaml level.
- Sibling PR scope: `values-prod.yaml` `perf-alerts-github-issues` route (both critical + non-critical) + receiver definition + `github-issues-receiver-token` mount removal. Wrapper PR sonra geri ekler.

**2026-05-19 (Session 42 PR #860 — Codex `019e4256` REVISE absorb)** — 4-finding absorb:
- **P0**: `perf-alerts-github-issues` direct receiver KNOWN-BLOCKED (Alertmanager v4 payload not wrapped into GitHub `repository_dispatch` schema; PR #648 RED reference). §2.2 + §5.2 spelled out; #857 acceptance via bridge GitHub Issue path, not direct receiver.
- **P1**: §2.2 + §3.1 + §3.2 Vault/Secret commands rewritten to `read -r -s` hidden prompt + stdin pipe + `unset` pattern. Bash history + process argv safety at write time; non-secrets (SMTP_HOST/PORT/USER) remain inline (intentional).
- **P1**: §5.2 acceptance scope spelled out — Proves: Alertmanager route + receiver dispatch (Slack + bridge); Does NOT prove: PrometheusRule fires, real metric path, `perf-alerts-github-issues` direct receiver delivery. `--fail-with-body` + `Content-Type: application/json` added.
- **P2**: §4.1 captures `PRE_REV` (status==deployed at snapshot time) to `/tmp/pre-rev-857.txt`; §6 reads stable rollback target from file, no recomputation at rollback time.

**2026-05-19 (Session 42 — Codex `019e4256` activation packet)** — Owner artifact checklist + Vault seed commands + helm upgrade dry-run/diff + acceptance smoke matrix + rollback procedure. `ready_for_helm_upgrade=false` until §2 artifacts arrive.
