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

## 4. ESO Migration Path (Opsiyonel, V3 Scope)

Vault DR çözüldüğünde Secret manual create yerine ESO ExternalSecret pattern:

```yaml
# kustomize/overlays/{test,prod}/eso/alertmanager-bridge-gh-token-externalsecret.yaml
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

Vault path: `kv/platform/alertmanager-bridge-gh.GITHUB_TOKEN`. V3 PERF-ARCH-V3 §3.5 cross-cluster federation + Vault DR scope.

---

## 5. Acceptance Criteria

- [ ] PAT created (GitHub Settings)
- [ ] K8s Secret seeded (test + prod)
- [ ] Pod rolling restart (env load)
- [ ] `GH_TOKEN` length > 30 verified
- [ ] Bridge logs ERROR yok ("gh issue create failed: ... gh auth login" mesajları durur)
- [ ] Synthetic alert E2E test PASS (issue create + close evidence)
- [ ] V2.1 #4 closure evidence PR (synthetic E2E sonrası)

---

## 6. Bridge Runtime Status (Session 53 P0 #1 close)

| Component | Status | Detay |
|---|---|---|
| **Pod** | ✅ Running | `alertmanager-bridge-8df75445c-*` test + prod (replaced 10d CrashLoop pod) |
| **Script** | ✅ Loaded | `scripts/alerting/alertmanager-bridge.py` → `kustomize/.../alertmanager-bridge.py` configMapGenerator hashSuffix `69hfmbhkfb` |
| **HTTP server** | ✅ :9093 listening | `alertmanager-bridge starting on :9093 (repo=Halildeu/platform-k8s-gitops)` |
| **Alert parsing** | ✅ Working | Alertmanager v4 webhook payload parsed (status/labels/annotations) |
| **Dedupe key** | ✅ Extended | PMD DoD §2.4(d): alertname+namespace+configmap/route+cluster |
| **Resolved lifecycle** | ✅ comment+close | `gh issue close` helper + undelivered log on failure |
| **gh CLI auth** | ❌ MISSING | Secret `alertmanager-bridge-gh-token` NotFound — owner PAT seed |
| **Issue create** | ❌ ERROR | gh auth fail; alerts → undelivered.jsonl (emptyDir, pod restart kaybolur) |

**Owner action**: §2.1-2.4 (~5dk) → Bridge runtime 100% LIVE + Issue lifecycle aktive → V2.1 #4 closure evidence PR mümkün.

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
