# PR-V2.1-Ops-A — GitHub Issues Receiver Spike (Revisited) — **HISTORICAL / SUPERSEDED**

> ⚠️ **STATUS: HISTORICAL / SUPERSEDED (2026-05-19, PR #861 + #862 deprecation)** — Bu spike doc Alertmanager `webhook_configs` → GitHub `repository_dispatch` direct receiver pattern'ini öneriyordu. Implementation gerçekte payload schema uyumsuzluğu nedeniyle çalışmadı (Alertmanager Go template body wrap edemez; PR #648 closed RED). Direct receiver + token mount + perf route'lar PR #861 ile `values-prod.yaml`'dan kaldırıldı. #862 (P3 wrapper bridge) implementation **deprecated** (Codex `019e4445` REVISE — redundant; mevcut `alertmanager-bridge` pod `gh` CLI ile Issue lifecycle zaten yapıyor).
>
> **Canonical accepted path**: `alarm-receiver-bridge` Alertmanager receiver → `alertmanager-bridge` pod (script `kustomize/base/monitoring/alertmanager-bridge/alertmanager-bridge.py`) → `gh` CLI direct Issue create/comment/close. NOT `repository_dispatch`.
>
> Bu doc spike intent + alternative path keşfi olarak korunur (historical context). Live system için: `docs/operations/alertmanager-bridge-design.md` + `docs/runbooks/RB-prod-alertmanager-activation.md`.

> **Belge kodu**: `PR-V2.1-Ops-A-github-issues-receiver-spike-revisited`
> **Tarih**: 2026-05-14 (SUPERSEDED 2026-05-19)
> **Sahip**: Halil
> **Sprint**: V2.1 prod-readiness sub-wave (PMD v9.1 §3.4 doğal fallback path)
> **Tetik**: Vault DR blocker → Slack receiver Vault'a bağımlı (PR #642 owner waiver)
> **Codex thread**: `019e2a4f-d1d1-7892-92f5-70e565b0efdc` (Q1 verdict — PMD §3.4 doğal fallback önerisi; superseded by `019e4256` iter-2 + `019e4445`)
> **Önceki Codex spike**: `019e267a` Preferred B path: `alertmanager-github-receiver` image 3 yıl stale (reject)
> **Status**: Spike — SUPERSEDED (Codex strategic consensus REVISE iter chain Session 42)

---

## 1. Bağlam

Session 52 Vault DR diagnoz: test + prod Vault root recovery 4 farklı share kombinasyonu fail. Mevcut Vault state'i disk'teki share inventory ile authenticate edilmiyor. Slack receiver Vault'a (`kv/platform/perf-alertmanager.SLACK_WEBHOOK_URL`) bağımlı; Vault DR çözülene kadar synthetic alert E2E proof yok.

Codex `019e2a4f` stratejik consensus:
- V2.1 partial waiver (PR #642) **OK Faz G freeze öncesi**
- Faz G cutover sign-off için **receiver E2E proof şart** (Slack veya eşdeğer)
- Snapshot restore (Yol 1) **YASAK** (1 ay önce data loss riski)
- **Yol 2 (alternative receiver Vault'tan bağımsız)** = **PMD §3.4 GitHub Issues receiver doğal fallback**

Bu spike `alertmanager-github-receiver` image stale problem'i bypass eden **custom GitHub Actions workflow pattern**ı önerir.

---

## 2. Pattern: Alertmanager webhook → GHA repository_dispatch → GitHub Issue

### 2.1 Architectural overview

```
Prometheus alert evaluator (PR #620 LIVE)
  ↓
Alertmanager pod (helm receiver config)
  ↓
webhook_config: url: https://api.github.com/repos/Halildeu/platform-k8s-gitops/dispatches
  + auth: Authorization: Bearer <GITHUB_TOKEN_FROM_VAULT_OR_GHA_SECRET>
  + payload: {"event_type": "perf-alert", "client_payload": {...alert...}}
  ↓
GitHub Actions workflow .github/workflows/alert-receiver.yml
  on: repository_dispatch types: [perf-alert]
  ↓
job: gh issue create / update / close (alert lifecycle)
  ↓
Issue body: alert detail (alertname, severity, namespace, description, runbook_url)
Issue labels: alert/firing, alert/resolved
Dedupe: search existing open issue by alertname+namespace; comment instead of new
Resolved lifecycle: alert payload status="resolved" → issue close + comment
```

### 2.2 Vault dependency comparison

| Path | Vault Dependency | E2E Proof Path |
|---|---|---|
| Slack receiver (PR #627 current) | ✗ `kv/platform/perf-alertmanager.SLACK_WEBHOOK_URL` | Vault DR sonrası |
| GitHub Issues receiver (this spike) | ⚪ Optional (GHA secret alternative) | Immediate (GHA secret yeterli) |

**Key advantage**: GitHub Personal Access Token (PAT) **GHA secret**'a directly yazılabilir; Vault'tan bağımsız. V2.1 #4 closure tam mümkün.

---

## 3. Implementation Scope

### 3.1 Alertmanager helm config delta

```yaml
# helm-values/kube-prometheus-stack/values-prod.yaml
alertmanager:
  alertmanagerSpec:
    secrets:
      # YENİ: GitHub Issues receiver token (Vault path or GHA secret)
      - github-issues-receiver-token   # Vault path optional
      - perf-alertmanager-secrets       # mevcut Slack (Vault DR pending)
      - alertmanager-fallback-secrets   # mevcut D43

  config:
    receivers:
      - name: 'perf-alerts-github-issues'
        webhook_configs:
          - url: 'https://api.github.com/repos/Halildeu/platform-k8s-gitops/dispatches'
            http_config:
              authorization:
                type: Bearer
                credentials_file: /etc/alertmanager/secrets/github-issues-receiver-token/GITHUB_TOKEN
            send_resolved: true
            max_alerts: 50
            # Payload transformation handled by GHA workflow (repository_dispatch)
    
    route:
      routes:
        # Critical perf alarms → GitHub issue (Vault DR sonrası Slack ile dual delivery)
        - matchers:
            - team = "perf"
          receiver: 'perf-alerts-github-issues'
          group_by: ['alertname', 'namespace']
          group_wait: 30s
          group_interval: 5m
          repeat_interval: 6h
          continue: false
```

### 3.2 GitHub Actions workflow

```yaml
# .github/workflows/alert-receiver.yml
name: Alert Receiver — Perf Alerts to Issues

on:
  repository_dispatch:
    types: [perf-alert]

permissions:
  issues: write
  contents: read

jobs:
  process-alert:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Process Alertmanager webhook payload
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          PAYLOAD: ${{ toJSON(github.event.client_payload) }}
        run: |
          # Parse Alertmanager v4 webhook payload format
          STATUS=$(echo "$PAYLOAD" | jq -r '.status // .alerts[0].status')
          ALERTNAME=$(echo "$PAYLOAD" | jq -r '.commonLabels.alertname // .alerts[0].labels.alertname')
          SEVERITY=$(echo "$PAYLOAD" | jq -r '.commonLabels.severity // "unknown"')
          NAMESPACE=$(echo "$PAYLOAD" | jq -r '.commonLabels.namespace // "n/a"')
          DESC=$(echo "$PAYLOAD" | jq -r '.alerts[0].annotations.description // "(no description)"')
          
          # Dedupe: open issue lookup
          DEDUPE_KEY="alert/${ALERTNAME}/${NAMESPACE}"
          EXISTING=$(gh issue list --repo $GITHUB_REPOSITORY --label "$DEDUPE_KEY" --state open --json number --jq '.[0].number')
          
          if [[ -n "$EXISTING" && "$STATUS" == "firing" ]]; then
            # Update existing open issue
            gh issue comment $EXISTING --repo $GITHUB_REPOSITORY --body "🔥 Re-fired at $(date -u +%FT%TZ): $DESC"
          elif [[ -z "$EXISTING" && "$STATUS" == "firing" ]]; then
            # Create new issue
            gh issue create --repo $GITHUB_REPOSITORY \
              --title "[ALERT $SEVERITY] $ALERTNAME ($NAMESPACE)" \
              --body "Severity: $SEVERITY\nNamespace: $NAMESPACE\nDescription: $DESC\n\nRunbook: docs/runbooks/" \
              --label "$DEDUPE_KEY,alert,severity/$SEVERITY"
          elif [[ -n "$EXISTING" && "$STATUS" == "resolved" ]]; then
            # Close + comment
            gh issue comment $EXISTING --repo $GITHUB_REPOSITORY --body "✅ Resolved at $(date -u +%FT%TZ)"
            gh issue close $EXISTING --repo $GITHUB_REPOSITORY --reason "completed"
          fi
```

### 3.3 Secret management

**Option A — GitHub Actions Token (Vault'tan bağımsız, V2.1 closure unlock)**:
- Workflow `${{ secrets.GITHUB_TOKEN }}` GHA managed (auto-rotated, repo-scoped issue:write)
- Alertmanager webhook'a GitHub PAT gerek (repository_dispatch trigger için)
- PAT GitHub Settings → Developer Settings → Personal Access Tokens → repo + workflow scope
- PAT GHA secret olarak depo: `gh secret set ALERTMANAGER_GH_DISPATCH_TOKEN`
- Alertmanager Secret mount: `kubectl create secret generic github-issues-receiver-token --from-literal=GITHUB_TOKEN=<PAT>`
- **Vault dependency: SIFIR**

**Option B — Vault Path (Vault DR sonrası migration)**:
- `kv/platform/perf-alertmanager-github` Vault path + GITHUB_TOKEN field
- ESO ExternalSecret pattern (Slack receiver gibi)
- Vault DR çözülünce migration

### 3.4 Acceptance criteria

- [ ] Alertmanager helm config update (`perf-alerts-github-issues` receiver)
- [ ] GitHub Actions workflow (`.github/workflows/alert-receiver.yml`)
- [ ] PAT GHA secret seed (owner ~1dk)
- [ ] K8s Secret manual create (Vault'tan bağımsız) veya ESO sync (Vault sonra)
- [ ] Synthetic alert E2E: `failures=1` patch → Alertmanager webhook → GHA workflow trigger → Issue creation kanıt
- [ ] Resolved lifecycle: failures=0 → Issue close kanıt
- [ ] Dedupe verify: same alert re-fire → existing issue comment (no new)

---

## 4. Codex `019e2a4f` Consensus Bağlamı

Codex Q1 verdict: "PagerDuty/Opsgenie ancak mevcut hesap/routing hazırsa; **mevcut PMD §3.4 GitHub issue receiver doğal fallback ve daha az sürprizli seçenek**."

Codex Q2 verdict: "**V2.1 #4 için yol 2 (alternative receiver Vault'tan bağımsız)**; kalıcı mimari için yol 3 (V3 Thanos + Vault rebuild); snapshot restore break-glass dışında YASAK."

Bu spike o doğal fallback path'in **custom GHA pattern**'iyle execution'ını sunar.

### 4.1 Önceki Codex spike `019e267a` ile uyum

Codex `019e267a` (Ops-A spike): `alertmanager-github-receiver` (m-lab) image 3 yıl stale, prod-ready binary yok. **REJECT**.

Bu spike o `alertmanager-github-receiver` binary'sini KULLANMIYOR; **custom GHA workflow** ile GitHub API'ye direkt webhook. Image dependency yok.

---

## 5. V2.1 #4 Closure Etkisi

| Item | Etki |
|---|---|
| V2.1 #4 source-side LIVE | ✅ Already DONE (PR #620 + #623) |
| V2.1 #4 receiver coupling source-level | ✅ Already DONE (PR #627) |
| V2.1 #4 Slack receipt | 🟡 Deferred (Vault DR pending) |
| **V2.1 #4 GitHub Issues receipt** | 🆕 **This spike enables — V2.1 #4 tam closure mümkün** |

V2.1 closure: ~85% (waiver) → **~95% (impl PR sonrası)**.

---

## 6. Implementation PR Plan

1. **PR-V2.1-Ops-A-github-issues-impl** (this spike sonrası):
   - `.github/workflows/alert-receiver.yml` (~80 satır)
   - `helm-values/kube-prometheus-stack/values-prod.yaml` extension
   - Runbook (`docs/runbooks/V2.1-perf-alert-receiver-github-issues.md`)
   - Codex peer review thread (yeni)

2. **Owner action**: 
   - GitHub PAT create + GHA secret seed (`gh secret set ALERTMANAGER_GH_DISPATCH_TOKEN`)
   - K8s Secret manual create OR ESO migration (Vault DR sonrası)

3. **Synthetic alert E2E test**:
   - `kubectl patch cm frontend-federation-smoke-status` failures=1
   - 5dk sustain → PerfFederationSmokeFailing firing → Alertmanager webhook → GHA workflow → Issue
   - Revert failures=0 → Issue close
   - V2.1 #4 closure evidence PR

---

## 7. Audit Trail

- Codex thread `019e2a4f` Q1+Q2 verdict (PMD §3.4 doğal fallback + Yol 2 alternative receiver)
- Codex önceki spike `019e267a` reject (3-yr stale image) — **bu spike o image'i KULLANMIYOR**
- V2.1 Vault DR diagnoz (PR #642 owner waiver)
- Implementer AI: Claude (Anthropic)
- Reviewer AI: Codex (OpenAI)
- Cross-AI consensus: AGREE Yol 2 path + custom GHA workflow

---

## 8. Sıradaki Adımlar (Codex consensus chain)

1. **Bu spike merge** (PMD §3.4 path doğru tasarım)
2. **Impl PR aç** (workflow + helm config + runbook + Codex peer review)
3. **Owner GHA PAT seed** (1dk, Vault dependency yok)
4. **Synthetic alert E2E test** (V2.1 #4 closure evidence)
5. **PR #642 waiver expire** (V2.1 #4 partial → tam closure migration)
6. **Faz G prod cutover freeze gate** (Codex Q5 receiver E2E proof gereği karşılanır)
