# Runbook — Alertmanager Bridge GitHub Token Seed (Session 53 P0 #1 Owner Step)

> **Belge kodu**: `RB-alertmanager-bridge-gh-token-seed`
> **Tarih**: 2026-05-15
> **Sahip**: Halil
> **Sprint**: Session 53 P0 #1 bridge restore (Codex `019e2a4f` A-prime)
> **Tetik**: PR #650 MERGED + cluster apply LIVE; bridge pod Running ama gh CLI auth eksik (Secret `alertmanager-bridge-gh-token` NotFound)

---

## 1. Bağlam

PR #650 alertmanager-bridge runtime restore başarılı:
- ✅ Test cluster pod LIVE (`alertmanager-bridge-8df75445c-6l5cc` Running 31s)
- ✅ Prod cluster pod LIVE (`alertmanager-bridge-8df75445c-xrcp7` Running 31s)
- ✅ Script LIVE: `alertmanager-bridge starting on :9093 (repo=Halildeu/platform-k8s-gitops)`
- ✅ Alert processing aktif (alerts received, parsed, dedupe + lifecycle çalışıyor)

**Tek eksik**: `Secret alertmanager-bridge-gh-token` NotFound her iki cluster'da → `GH_TOKEN=` boş → `gh issue create` fail:
```
[ERROR] gh issue create failed: To get started with GitHub CLI, please run:  gh auth login
```

Bridge 10 gün CrashLoop sırasında Alertmanager queue'da biriken alarmlar şu an resolved olarak akıyor (`KubeJobFailed`, `KubeDeploymentRolloutStuck`, `KubePodCrashLooping`, `NodeClockNotSynchronising`); undelivered.jsonl emptyDir'da birikiyor.

---

## 2. Owner Action — PAT Create + Secret Seed (5dk)

### 2.1 GitHub PAT Create

GitHub Settings → Developer Settings → Personal Access Tokens (classic):
- **Scope**: `repo` (issue create/comment/close için)
- **Expiration**: 90 day (rotation plan)
- **Note**: "alertmanager-bridge issue dispatcher"
- Copy PAT (`ghp_xxx...`)

**Alternatif (önerilen)**: Fine-grained PAT
- Repository access: `Halildeu/platform-k8s-gitops`
- Permissions: `Issues: Read and write` (sadece bu)
- Plus `Contents: Read` (workflow için, gerekli değil ama best practice)

### 2.2 K8s Secret Create

```bash
ssh halil@staging-sw

# Test cluster
kubectl --context k3d-test -n monitoring create secret generic alertmanager-bridge-gh-token \
  --from-literal=token="<PAT_FROM_2.1>" \
  --dry-run=client -o yaml | kubectl --context k3d-test -n monitoring apply -f -

# Prod cluster
kubectl --context k3d-prod -n monitoring create secret generic alertmanager-bridge-gh-token \
  --from-literal=token="<PAT_FROM_2.1>" \
  --dry-run=client -o yaml | kubectl --context k3d-prod -n monitoring apply -f -

# Verify
kubectl --context k3d-prod -n monitoring get secret alertmanager-bridge-gh-token -o jsonpath='{.metadata.name}'
echo
```

### 2.3 Pod Rolling Restart

```bash
# Deployment.yaml env GITHUB_TOKEN secretKeyRef optional: true; secret oluşunca
# pod restart gerekli (env load on start).
kubectl --context k3d-test -n monitoring rollout restart deploy/alertmanager-bridge
kubectl --context k3d-prod -n monitoring rollout restart deploy/alertmanager-bridge

# Verify GH_TOKEN env mevcut
kubectl --context k3d-prod -n monitoring exec deploy/alertmanager-bridge -- sh -c 'echo length=${#GITHUB_TOKEN}'
# Beklenen: length=40+ (PAT classic ~40 char veya fine-grained ~93 char)
```

### 2.4 Verify Bridge GitHub Auth

```bash
# Bridge bir alert aldığında gh issue create başarılı olmalı
kubectl --context k3d-prod -n monitoring logs deploy/alertmanager-bridge --tail=20 | grep -E "opened|commented|closed|ERROR"

# Beklenen (gh auth OK):
# [INFO] opened: [alertmanager-P1] PerfFederationSmokeFailing/...
# YOK ya da:
# [INFO] commented #<num>
```

---

## 3. Synthetic Alert E2E Test (V2.1 #4 Closure Evidence)

PAT seed sonrası:

```bash
# Trigger firing (prod cluster local)
ssh halil@staging-sw 'kubectl --context k3d-prod -n platform-prod patch cm frontend-federation-smoke-status \
  --type=json -p="[{\"op\":\"replace\",\"path\":\"/metadata/annotations/frontend-federation-smoke.io~1failures\",\"value\":\"1\"}]"'

# 5-6 dk bekle (PromQL for: 5m clause)
# Beklenen alert chain:
#   - PerfFederationSmokeFailing pending → firing
#   - Alertmanager group_wait 30s → webhook to bridge
#   - Bridge gh issue create → new issue in Halildeu/platform-k8s-gitops

# Verify issue created
gh issue list --repo Halildeu/platform-k8s-gitops \
  --search '"PerfFederationSmokeFailing" in:title' \
  --state open --json number,title,createdAt | jq .
# Beklenen: 1 issue

# Revert
ssh halil@staging-sw 'kubectl --context k3d-prod -n platform-prod patch cm frontend-federation-smoke-status \
  --type=json -p="[{\"op\":\"replace\",\"path\":\"/metadata/annotations/frontend-federation-smoke.io~1failures\",\"value\":\"0\"}]"'

# 5-6 dk bekle (resolved propagation)
# Verify issue closed
gh issue list --repo Halildeu/platform-k8s-gitops \
  --search '"PerfFederationSmokeFailing" in:title' \
  --state closed --json number,title,closedAt | jq .
# Beklenen: 1 issue closed + comment "✅ Resolved at..."
```

---

## 4. ESO Migration — SOURCE DESIRED-STATE PR READY / OPERATOR ACTION PENDING (BL-008-bridge)

> **Status (2026-05-28 — Codex `019e6e03` REVISE iter-2 truth-sync)**:
> Source-side desired-state added via PR #1110 (Codex `019e6de3` plan-time AGREE B
> path). Runtime restore pending: operator fine-grained PAT generation + agent
> Vault stdin-pipe seed + kubectl delete existing manual K8s secret + apply
> ExternalSecret + ESO Ready=True + bridge env GITHUB_TOKEN length verify + D43
> synthetic acceptance. Vault is operational and ClusterSecretStore
> `vault-platform-gitops` Ready=True 34d; the "Vault DR pending" gate is no longer
> blocking ESO migration. Live `DELIVERED` truth-sync deferred to post-acceptance
> follow-up PR (R9 update + handoff doc evidence batch).

Manifest source PR READY: [externalsecret-alertmanager-bridge-gh-token.yaml](../../kustomize/overlays/prod/eso/alertmanager/externalsecret-alertmanager-bridge-gh-token.yaml)

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: alertmanager-bridge-gh-token
  namespace: monitoring
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: vault-platform-gitops
  target:
    name: alertmanager-bridge-gh-token
    creationPolicy: Owner
  data:
    - secretKey: token
      remoteRef:
        key: kv/platform/alertmanager-bridge-gh
        property: GITHUB_TOKEN
```

Vault path: `kv/platform/alertmanager-bridge-gh.GITHUB_TOKEN`. Convention parallel
with `kv/platform/perf-alertmanager.TEAMS_WEBHOOK_URL` (per-receiver path; uppercase
env-style property names; separate from `alertmanager-fallback` which is multi-key
SMTP credentials).

### 4.1 New Operator Action (post-2026-05-28 — replaces §2.1-2.4 manual K8s secret pattern)

> **HARD RULE — no token leak**: PAT chat'e, log dosyasına, env'e, history'e
> **YAZILMAZ**. Terminalde sadece `read -rs` (silent, no echo) ile alınır.
> Tüm zincir tek-shot stdin-pipe; `BRIDGE_PAT` shell var hot-path; `unset`
> ile temizlenir. SSH komutu single-quote içinde quote-escape edilir; remote
> tarafta `vault kv put ... = -` ile stdin'den okunur (CLI history'ye bile
> düşmez). Codex `019e6fb5` AGREE Yol C-prime — bu disiplin verify gate
> Layer 2 (scripts/verify-vault-paths.sh live) ile machine-enforced.

```bash
# 1. GitHub Settings → Developer Settings → Personal Access Tokens (fine-grained):
#    - Repository: Halildeu/platform-k8s-gitops
#    - Permissions: Issues: Read and write (only — scope minimal per Codex AGREE)
#    - Expiration: 90 days
#    - Note: "alertmanager-bridge prod D43 paging (BL-008-bridge)"
#    - Copy token (ekrana 1 kez gösterilir; clipboard 30sn timeout tercih edilir)

# 2. Vault seed (D43 stdin-pipe pattern; HARD RULE — no token leak):
#    Read terminal silent mode; prefix verify via `=~`; stdin-pipe SSH;
#    remote vault kv put consumes stdin via `=-`; unset cleanup zorunlu.
read -r -s BRIDGE_PAT
echo  # newline after silent read
if [[ ! "$BRIDGE_PAT" =~ ^(ghp_|github_pat_) ]]; then
  echo "ERR: PAT prefix unexpected (got: ${BRIDGE_PAT:0:8}...); abort" >&2
  unset BRIDGE_PAT
  return 1 2>/dev/null || exit 1
fi
printf '%s' "$BRIDGE_PAT" | ssh halil@staging-sw '
  set -euo pipefail
  VAULT_ROOT_TOKEN=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)
  docker exec -i -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-prod \
    vault kv put kv/platform/alertmanager-bridge-gh GITHUB_TOKEN=-
  unset VAULT_ROOT_TOKEN
'
unset BRIDGE_PAT

# 3. Delete existing manual K8s secret so ESO can create owned (creationPolicy: Owner
#    refuses to take over non-ESO-owned existing secret to avoid accidental overwrite):
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring delete secret alertmanager-bridge-gh-token'

# 4. Apply ExternalSecret + force-sync:
ssh halil@staging-sw 'kubectl --context k3d-prod apply -k /path/to/repo/kustomize/overlays/prod/eso/alertmanager/'
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring annotate externalsecret alertmanager-bridge-gh-token force-sync=$(date +%s) --overwrite'

# 5. Wait Ready=True (within ~30s typical):
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring wait externalsecret/alertmanager-bridge-gh-token --for=condition=Ready --timeout=120s'

# 6. Verify ESO ownerRef on K8s Secret (Codex `019e6e03` absorb — drift fail-safe):
#    Expect: ownerReferences[0].kind=ExternalSecret, name=alertmanager-bridge-gh-token
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring get secret alertmanager-bridge-gh-token -o jsonpath="{.metadata.ownerReferences[0].kind}/{.metadata.ownerReferences[0].name}"; echo'

# 7. Verify K8s secret token length > 40:
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring get secret alertmanager-bridge-gh-token -o json | jq -r ".data.token" | base64 -d | wc -c'

# 8. Rollout restart bridge — Secret env rotation needs explicit restart (Codex
#    `019e6e03` absorb): configMapGenerator hashSuffix auto-restarts on script
#    edit, BUT Secret value change doesn't trigger Deployment rollout (env var
#    is start-time load). PAT rotation always requires explicit restart.
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring rollout restart deploy/alertmanager-bridge'
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring rollout status deploy/alertmanager-bridge --timeout=120s'

# 9. Pod env verify (length > 40):
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring exec deploy/alertmanager-bridge -- sh -c "echo length=\${#GITHUB_TOKEN}"'

# 10. R29 CronJob first-fire manual trigger (Codex `019e6e03` absorb — acceptance
#     gate; merge gate değil, ama live acceptance gate). Manual job from cron
#     spec; HTTP 200 + Alertmanager receivers + Teams Adaptive Card + bridge
#     synthetic_skipped_total metric increment + GH Issue NOT created.
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring create job --from=cronjob/r29-teams-smoke r29-smoke-manual-$(date +%s)'
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring logs -l app.kubernetes.io/name=r29-teams-smoke --tail=20'
# Verify bridge synthetic_skipped_total counter
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring exec deploy/alertmanager-bridge -- wget -qO- http://localhost:9093/metrics | grep alertmanager_bridge_synthetic_skipped_total'
```

### 4.2 90-Day PAT Rotation (cron-driven; Codex `019e6de3` A path long-term)

PAT expiration: 90 days (operator-set). Rotation procedure:

1. **T-7d alert** (R29-mitigation analog): PrometheusRule on Vault TTL would be ideal but
   Vault doesn't expose KV TTL natively. Operator calendar reminder OR GitHub Issue auto-create
   bridge metric `alertmanager_bridge_undelivered_by_reason_total{reason="gh_auth_failed"}` spike.
2. Operator generates new PAT (steps §4.1 step 1).
3. Re-run §4.1 step 2 (Vault `vault kv put` overwrites — atomic).
4. ESO syncs within 1h (or force annotation).
5. Bridge restart picks up new env (configMapGenerator hash change OR manual restart).
6. Synthetic alert acceptance verify (§5).

### 4.3 GitHub App Migration (90 günde — Codex `019e6de3` A path)

PAT → GitHub App eliminates 90-day rotation:
- Org-level installation (no individual user expiry)
- Installation token auto-refresh per request
- Vault property rename: `GITHUB_APP_PRIVATE_KEY` + `GITHUB_APP_INSTALLATION_ID`
- Bridge script update: `gh` CLI auth via JWT exchange (`gh auth login --with-token` → install token)
- Migration window: 60-90 days from BL-008-bridge merge

Separate sprint scope. ESO ExternalSecret is the migration target's data plane —
only the property names + bridge script auth flow change.

---

## 5. Acceptance Criteria

> **Truth-sync (2026-05-28 — Codex `019e6e03` REVISE iter-2 absorb)**: ESO
> migration acceptance criteria. Eski §2.1-2.4 manual K8s seed pattern historical
> (audit-only); operator path artık §4.1 ESO-driven.

### 5.1 Source-side (this PR, BL-008-bridge — PR #1110)
- [x] ExternalSecret manifest `externalsecret-alertmanager-bridge-gh-token.yaml` PR'da hazır
- [x] kustomization.yaml entry eklendi
- [x] Bridge `synthetic_skipped_total` metric + `is_synthetic=true` filter
- [x] R29 weekly synthetic Teams smoke CronJob manifest hazır (Mon 09:00 Istanbul; Codex `019e6e03` REVISE iter-2 absorb)
- [x] `kubectl kustomize` render OK (build sanity)
- [x] Python AST parse OK
- [x] PR open + Codex cross-AI peer review absorbed

### 5.2 Runtime acceptance (post-merge + agent automation per §4.1)
- [ ] Operator fine-grained PAT created (Issues:Read+Write only, 90d expire)
- [ ] Vault path `kv/platform/alertmanager-bridge-gh.GITHUB_TOKEN` seeded via stdin-pipe (no-token-log)
- [ ] Existing manual K8s Secret `alertmanager-bridge-gh-token` deleted (ESO creationPolicy=Owner pre-req)
- [ ] `kubectl apply -k kustomize/overlays/prod/eso/alertmanager/` applied
- [ ] ESO ExternalSecret `Ready=True` within 120s
- [ ] K8s Secret `ownerReferences[0]` = `ExternalSecret/alertmanager-bridge-gh-token` (ESO-owned)
- [ ] K8s Secret `data.token` decoded length > 40 (fine-grained ~93 char)
- [ ] Bridge pod rollout restart success
- [ ] Pod env `GITHUB_TOKEN` length > 40 verified
- [ ] Bridge log no `gh auth login` errors
- [ ] **Verify gate Layer 2 machine-enforced** (Codex `019e6fb5` AGREE Yol C-prime): `scripts/verify-vault-paths.sh live --context k3d-prod --namespace monitoring --externalsecret alertmanager-bridge-gh-token --min-token-len 40` exit 0
- [ ] Bridge `/metrics` exposes `alertmanager_bridge_github_token_configured 1` (startup auth-drift sentinel ON)
- [ ] PrometheusRule `alertmanager-bridge-gh-auth` 3 alerts NOT firing 10m sustained (Layer 3 runtime surveillance clear)

### 5.3 R29 CronJob first-fire (acceptance gate — not merge gate per Codex `019e6e03` absorb)
- [ ] Manual job trigger: `kubectl create job --from=cronjob/r29-teams-smoke r29-smoke-manual-<ts>`
- [ ] Job HTTP 200 (Alertmanager v2 API accepted synthetic alert)
- [ ] Alertmanager alert state: `receivers: [perf-alerts-teams, alarm-receiver-bridge]`
- [ ] Power Automate run history: 1 new run within ~7s (operator UI verify)
- [ ] Teams #perf-alerts channel: Adaptive Card receipt (operator visual verify)
- [ ] Bridge metric `alertmanager_bridge_synthetic_skipped_total` increment (synthetic filter triggered)
- [ ] No new GitHub Issue created (filter prevents spam)

### 5.4 D43 synthetic acceptance (real alert path verify)
- [ ] Synthetic `NotifyServiceAbsent` fire (per §3 procedure)
- [ ] Bridge log: `[INFO] opened: [alertmanager-P1] NotifyServiceAbsent/...`
- [ ] GH Issue auto-created with correct title format
- [ ] Resolve cycle → bridge comments + closes issue
- [ ] Bridge metric `alertmanager_bridge_undelivered_by_reason_total{reason="gh_issue_create_failed"}` = 0 (no auth fail)

### 5.5 Post-acceptance follow-up
- [ ] R9 risk register update (🟢 Mitigated SMTP-only → 🟢 Mitigated full defense-in-depth SMTP + bridge GH Issue) — note: BL-008-bridge follow-up PR (this PR — Codex `019e6fb5` Yol C-prime) source-side LIVE; runtime restore brings R9 to full mitigation
- [ ] R29 mitigation #3 status update (⏳ TODO → ✅ DELIVERED + first-fire evidence ts) — note: R29 madde (4) defense-in-depth `bridge route GitHub Issue blocked by GH_TOKEN` cleared after RB §5.2-5.4 chain
- [ ] V2.1 Exit #4 closure evidence doc update (mitigation #3 ACTIVE + bridge tertiary leg ACTIVE)
- [ ] Truth-sync PR §4 / §5 source-vs-runtime: PR READY → DELIVERED LIVE
- [ ] GitHub App migration follow-up issue/PR (Codex `019e6fb5` follow-up scope) — 90d PAT rotation eliminate: App ID + private key Vault seed + bridge script JWT exchange + PAT decom

---

## 6. Bridge Runtime Status (truth-sync 2026-05-28 — Codex `019e6e03` REVISE iter-2)

| Component | Status | Detay |
|---|---|---|
| **Pod** | ✅ Running (13d) | `alertmanager-bridge-7b6cc47fd5-lt5w9` prod cluster restart=0 |
| **Script** | ✅ Loaded | `kustomize/base/monitoring/alertmanager-bridge/alertmanager-bridge.py` configMapGenerator hashSuffix LIVE; PR #1110 ekler `is_synthetic` filter + `synthetic_skipped_total` metric |
| **HTTP server** | ✅ :9093 listening | `alertmanager-bridge starting on :9093 (repo=Halildeu/platform-k8s-gitops)` |
| **Alert parsing** | ✅ Working | Alertmanager v4 webhook payload parsed |
| **Dedupe key** | ✅ Extended | PMD DoD §2.4(d): alertname+namespace+configmap/route+cluster |
| **Resolved lifecycle** | ✅ comment+close | `gh issue close` helper + undelivered log on failure |
| **gh CLI auth** | ⚠️ source-restored / runtime pending | Source: ExternalSecret manifest PR #1110 READY; runtime: operator PAT + agent Vault seed + ESO Ready pending (§4.1) |
| **Issue create** | ⚠️ source-restored / runtime pending | Source: synthetic filter PR #1110 READY; runtime restoration after §4.1 chain |
| **Synthetic filter** | ✅ source PR-ready | `is_synthetic=true` label → skip GH Issue + `synthetic_skipped_total` metric increment |

**Restore action chain**: §4.1 §5.2-5.4 → Bridge runtime 100% LIVE + D43 tertiary leg restored + R29 surveillance ACTIVE.

**Historical (audit-only, superseded by §4)**: §2.1-2.4 manual K8s secret create pattern. ESO migration §4.1 replaces it. Existing manual K8s secret (13d age, token length=0) must be deleted before ESO apply.

---

## 7. Codex `019e2a4f` AGREE Bağlamı

Codex iter-3 AGREE post-iter-2 absorb:
> "Synthetic E2E'ye geçmeden önce `monitoring/alertmanager-bridge-gh-token` secret'ın ilgili cluster'da var olduğunu... doğrulayın."

Bu runbook owner action sıralı execution plan'ı. Bridge runtime restore tamamlandı; gh auth seed sonrası V2.1 #4 closure evidence path açık.

---

## 8. Audit Trail

- PR #650 sha `b0c029f0` MERGED 2026-05-15T07:10:48Z (bridge restore)
- Codex thread `019e2a4f` iter-3 AGREE (4 dosya scope temiz + AGREE squash)
- Session 52 honest handoff PR #649 (bridge dead tespit)
- PMD v9.1 §2.4(d) dedupe key contract
- PMD §3.4 GitHub Issues receiver doğal fallback path
