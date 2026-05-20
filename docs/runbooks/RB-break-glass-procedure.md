# RB-break-glass-procedure — Audited Cluster-Admin Operations

> Codex Sprint C pre-cutover RBAC: "D30 öncesi: break-glass SA + helper script
> + audit log + reconciliation PR template. Bu, cutover sırasında 'dirty
> break-glass' olursa kayıtsız kalmasını engeller."
>
> Bu runbook: ops-break-glass ServiceAccount aracılığıyla audited
> cluster-admin operasyonu nasıl yapılır + reconciliation PR contract.

## Niye var?

D30 atomic cutover + 72h rollback window'unda istenmedik durumlar:
- ArgoCD sync 10min+ gecikiyor; P1 alarm acilen response gerek
- CRD/ResourceQuota sorunu ArgoCD sync'i bloke ediyor
- Compose stateful tier'da (PG/Vault/KC) müdahale gerek; gitops PR doğru path değil

Bu durumlarda operator cluster-admin yetkisi kullanmak zorunda. Risk:
- Yetkili müdahale **kayıtsız** kalırsa drift gizleniyor
- Şikayetçi olmadığı sürece kimsenin haberi olmuyor

`ops-break-glass` ServiceAccount + audit pipeline bu boşluğu kapatır.

## Topology

```
[Operator (halil)]
    │
    │  bash scripts/operations/break-glass-token.sh "<reason>"
    ↓
[scripts/operations/break-glass-token.sh]
    │
    ├── kubectl create token ops-break-glass --duration=1h  → TTL token
    ├── /var/log/break-glass-audit.log append              → host audit trail
    ├── gh issue create --label "ops-audit,break-glass"    → governance trail
    └── Output minimal kubeconfig with token + reminder
    ↓
[Operator: KUBECONFIG=/tmp/kubeconfig-break-glass-$$ kubectl ...]
    │
    │  Cluster ops with cluster-admin
    ↓
[k8s API audit log] (kube-apiserver --audit-policy)
    │
    └── kubectl operation logged with SA identity = ops-break-glass
    ↓
[Within 30min: reconciliation PR]
    │
    │  Template: .github/PULL_REQUEST_TEMPLATE/break-glass-reconciliation.md
    │  Tag the audit issue
    ↓
[Reconciliation PR merged → drift cleared]
    │
    │  Audit issue closed
```

## Pre-cutover bootstrap (one-time)

Apply break-glass SA manifest to both clusters:

```bash
# test cluster
kubectl --context k3d-test apply -k kustomize/base/rbac/

# prod cluster
kubectl --context k3d-prod apply -k kustomize/base/rbac/

# Verify
kubectl --context k3d-prod -n kube-system get sa ops-break-glass
kubectl --context k3d-prod get clusterrolebinding ops-break-glass-cluster-admin
```

After bootstrap, the SA exists but is dormant — no token issued, no permissions effective.

## Operator usage

### Step 1 — Issue token

```bash
# Provide a clear, audit-friendly reason (≥15 chars)
bash scripts/operations/break-glass-token.sh "schema-service ImagePullBackOff fix during D30 cutover"
```

Output:
- Token issuance confirmation
- Audit log entry
- GitHub issue created
- KUBECONFIG path printed

### Step 2 — Use the token

```bash
export KUBECONFIG=/tmp/kubeconfig-break-glass-XXXX

# Verify identity
kubectl auth whoami
# → system:serviceaccount:kube-system:ops-break-glass

# Perform required ops
kubectl --context k3d-prod -n platform-prod set image deploy/schema-service \
  schema-service=ghcr.io/halildeu/platform-backend-schema-service@sha256:...
```

### Step 3 — Cleanup

```bash
unset KUBECONFIG
rm -f /tmp/kubeconfig-break-glass-XXXX
```

Token expires automatically at 1h TTL. No further action needed if not used.

### Step 4 — Reconciliation PR (within 30min)

```bash
# Branch from main
git checkout -b fix/reconcile-break-glass-<short-desc>

# Update gitops YAML to match cluster live state
vim kustomize/base/apps/schema-service/deployment.yaml  # update image digest

# Verify drift cleared
bash scripts/drift-detection/check_env_drift.sh prod

# Commit + push + PR
git commit -am "fix: reconcile break-glass schema-service digest update (#<audit-issue>)"
gh pr create --template .github/PULL_REQUEST_TEMPLATE/break-glass-reconciliation.md
```

Tag the audit issue in PR body. Operator review checklist must be ticked.

## What CAN you do under break-glass

- **Modify deployments** (kubectl set image, scale, restart)
- **Apply ConfigMap changes** (selective; D17 koruma kuralı sürdürün)
- **Delete stuck resources** (terminating pods, broken jobs)
- **kubectl exec for debugging** (read-only inspection ok)
- **kubectl logs / port-forward** (read-only inspection)

## What you should AVOID even with break-glass

- **kubectl edit on running prod resources** without parallel gitops PR
- **Anything that impacts a different namespace** without explicit reason
- **Persistent infra changes** (CRDs, RBAC, ingress) — these need gitops PR even in emergency
- **Destructive operations** (delete pvc, drop database, delete namespace) — separate runbooks for each scenario

If a destructive op is needed: STOP, raise stakes, get explicit user (operator) confirmation in the audit issue thread BEFORE proceeding.

## Token lifecycle

- **Issued**: 1h TTL, projected token (k8s 1.24+ API)
- **Active use**: visible in cluster audit log per kubectl call
- **Expires**: 1h after issue OR when service account secret rotated
- **Revoked**: kubectl delete the token's projected serviceaccount secret if compromised
  ```bash
  kubectl -n kube-system patch sa ops-break-glass --type='json' \
    -p='[{"op":"remove","path":"/secrets"}]'
  # Then re-issue with new --duration value as needed
  ```

## Audit log location + rotation

`/var/log/break-glass-audit.log`:
- Append-only (`>>`)
- One line per token issue
- Format: `<ts> | break-glass-issued | sa=<sa> | ns=<ns> | duration=<d> | requested-by=<user@host> | context=<ctx> | reason=<text>`
- Rotation: handled by host logrotate (operator's responsibility)
- Review: weekly grep for entries without matching reconciliation PR

## Failure modes

### Token issuance fails

**Cause**: SA not bootstrapped, kubectl context missing, k8s 1.24+ API not available

**Resolution**:
```bash
# Check SA exists
kubectl get sa ops-break-glass -n kube-system

# If missing, bootstrap:
kubectl apply -k kustomize/base/rbac/
```

### gh CLI unavailable for audit issue

**Cause**: gh not authenticated or repo permissions changed

**Resolution**:
- Token is still issued + audit log written
- Operator MUST manually open audit issue in GitHub UI
- Reconciliation PR refers to the manual issue

### /var/log not writable

**Cause**: First-run on staging-sw without sudo configured

**Resolution**:
- Script falls back to /tmp/break-glass-audit.log
- Operator manually appends to /var/log post-incident OR
- Runs as `sudo -E bash break-glass-token.sh "<reason>"`

## Compliance hooks (TODO future)

- Weekly job: scan audit log entries that lack matching reconciliation PR (>24h old) → P1 alarm
- Per-quarter audit review: list all break-glass uses + reconciliation PR refs
- ArgoCD app dashboard: surface break-glass-detected drift events

## Related artifacts

- `kustomize/base/rbac/break-glass-sa.yaml` — SA + ClusterRoleBinding
- `scripts/operations/break-glass-token.sh` — token issuance helper
- `.github/PULL_REQUEST_TEMPLATE/break-glass-reconciliation.md` — PR template
- `docs/operations/rbac-break-glass-design.md` — full architecture
- `scripts/drift-detection/check_env_drift.sh` — drift verification post-reconciliation
- `docs/runbooks/RB-argocd-hub-recovery.md` — ArgoCD recovery (often paired)
