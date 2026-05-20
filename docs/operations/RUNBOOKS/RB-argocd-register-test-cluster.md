# Runbook — Register k3d-test as ArgoCD External Cluster

> **Owner**: ADR-0023 Guardrail PR-2 (promotion-pipeline hardening).
> **Codex consensus**: thread `019e40e4` Option A (un-exclude `platform-test.yaml`
> only, keep `platform-eso-test.yaml` excluded — in-cluster destination).
> **Trigger**: Guardrail PR-2 merged; prod ArgoCD root reconciles and creates
> `platform-test` Application; Application enters `Unknown`/`Error` state
> because target cluster `test-cluster` not registered. This runbook executes
> the live registration step.

## Purpose

Register the `k3d-test` cluster as a non-default ArgoCD destination on the
**prod** ArgoCD instance, so the `platform-test` Application can sync
`kustomize/overlays/test` → `k3d-test` `platform-test` namespace via GitOps
(ADR-0023 D2 — test overlay GitOps-authoritative).

**Live state change**: ArgoCD's `argocd-secret`/secret store gains a new
cluster credential entry. No workload mutation in either cluster. Reversible
via `argocd cluster rm`.

## Pre-conditions

- Guardrail PR-2 (`feat/guardrail-pr2-platform-test-argocd-app`) MERGED.
- Prod ArgoCD app-of-apps reconciled (root Application Synced).
- Operator has:
  - `argocd` CLI ≥ v2.13 installed locally or on staging-sw.
  - `kubectl` access to both `k3d-prod` (ArgoCD host) and `k3d-test` (target).
  - `argocd` CLI logged in to prod ArgoCD with `clusters,create` RBAC.

## Step 0 — Verify current state

```bash
# Confirm root has reconciled and created platform-test Application
ssh halil@staging-sw 'kubectl --context k3d-prod -n argocd get application platform-test \
  -o jsonpath="status.sync={.status.sync.status} status.health={.status.health.status}\n"'
```

Expected before this runbook: `status.sync=Unknown` or `OutOfSync` +
`status.health=Missing` (target cluster not yet registered).

```bash
# Confirm test-cluster not yet registered
ssh halil@staging-sw 'argocd cluster list 2>&1 | grep -E "test-cluster|^SERVER"'
```

Expected: only `https://kubernetes.default.svc (in-cluster)` listed; no
`test-cluster` row. If `test-cluster` already present → skip to Step 4
(verification).

## Step 1 — Prepare k3d-test kubeconfig context on the operator host

```bash
# On staging-sw (which already has both contexts)
ssh halil@staging-sw 'kubectl config get-contexts | grep k3d-test'
```

Expected: `k3d-test` context present + reachable. If missing, regenerate:
`k3d kubeconfig get k3d-test --output ~/.kube/k3d-test.yaml`.

## Step 2 — Register k3d-test as ArgoCD destination

> **Destination name MUST be `test-cluster`** (matches
> `argocd/applications/platform-test.yaml` `spec.destination.name`).

```bash
ssh halil@staging-sw '
  argocd cluster add k3d-test \
    --name test-cluster \
    --upsert \
    --yes
'
```

What this does:
- Creates a `ServiceAccount` + `ClusterRoleBinding` in the target k3d-test
  cluster (in `kube-system`) with `argocd-manager` SA + cluster-admin role.
- Generates a long-lived token for that SA.
- Writes the cluster credential as a Secret in the prod ArgoCD namespace
  (`argocd`), labeled `argocd.argoproj.io/secret-type=cluster`.

**Fail signal**: `unable to fetch cluster info` → check k3d-test reachable +
operator kubeconfig context valid. **Continue threshold**: command exits 0;
secret created.

## Step 3 — Verify cluster credential

```bash
ssh halil@staging-sw 'argocd cluster list 2>&1' | grep test-cluster
```

Expected: row containing `test-cluster` + the k3d-test API server URL +
`Successful` connection state.

## Step 4 — Verify `platform-test` Application transitions to Synced/Healthy

```bash
ssh halil@staging-sw 'kubectl --context k3d-prod -n argocd get application platform-test \
  -o jsonpath="status.sync={.status.sync.status} status.health={.status.health.status}\n"'
```

Expected within ~60-120s of registration: `status.sync=Synced` +
`status.health=Healthy`. If still `OutOfSync` after 2 min, force a sync:

```bash
ssh halil@staging-sw 'argocd app sync platform-test --timeout 300'
```

## Step 5 — Confirm test cluster reflects overlays/test

```bash
ssh halil@staging-sw '
  kubectl --context k3d-test -n platform-test get deploy \
    -o jsonpath="{range .items[*]}{.metadata.name}{\"\t\"}{.status.replicas}/{.status.readyReplicas}{\"\n\"}{end}"
'
```

Expected: 9+ Deployments (api-gateway, auth-service, core-data-service,
notification-orchestrator, permission-service, report-service, schema-service,
variant-service, frontend-testai) all `1/1`.

`platform-test` Application is now the authoritative sync path for the test
cluster (per ADR-0023 D2). Ad-hoc `kubectl set image` on main workloads is
forbidden going forward (HARD RULE — AGENTS.md §3).

## Rollback

If the `platform-test` Application causes unintended sync behaviour:

```bash
# Option A — disable auto-sync without removing cluster:
ssh halil@staging-sw '
  kubectl --context k3d-prod -n argocd patch application platform-test \
    --type=merge -p "{\"spec\":{\"syncPolicy\":{\"automated\":null}}}"
'

# Option B — remove cluster credential entirely:
ssh halil@staging-sw 'argocd cluster rm test-cluster --yes'
```

Option B leaves the `platform-test` Application in place but `Unknown` (no
target). The cluster's existing workloads continue running unchanged
(in-cluster k3d-test state is independent of ArgoCD registration).

## Post-step — Follow-up issues

- After `platform-test` runs stable for ≥7 days with no out-of-band drift, a
  follow-up PR can flip `prune: false` → `prune: true` in
  `argocd/applications/platform-test.yaml` (Codex Option A's safe-first-
  activation default).
- Restricted test-runner RBAC (originally scoped into Guardrail PR-2) moved
  to a separate PR — track separately.

## References

- ADR-0023 — Promotion Pipeline: Test Overlay GitOps-Authoritative
- Codex thread `019e40e4` — Guardrail PR-2 Option A design consensus
- `argocd/applications/root.yaml` — exclude pattern (post-PR-2)
- `argocd/applications/platform-test.yaml` — Application spec
- `AGENTS.md` §3 HARD RULE — test overlay GitOps-authoritative
