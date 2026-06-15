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

**Live state change** (Codex `019e42c4` REVISE absorb):
- **Prod cluster (k3d-prod)**: no workload mutation. ArgoCD `argocd-secret`/
  secret store gains a new cluster credential entry; that's the only delta.
- **Test cluster (k3d-test)**: RBAC mutation — `argocd cluster add` creates
  `argocd-manager` ServiceAccount + cluster-admin ClusterRoleBinding in
  `kube-system` and mints a long-lived token for it.
- **Test cluster overlay sync**: after registration, the `platform-test`
  Application's `automated.selfHeal: true` (and apply path) **will sync
  `kustomize/overlays/test` into `platform-test` namespace**. `prune: false`
  prevents deletion of out-of-band resources but does NOT prevent apply or
  selfHeal of new/changed manifests. Verify overlays/test is the intended
  current state before running this runbook.

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

### Step 2B — CLI-less internal bridge + cluster Secret path

Use this path when the staging host does not have the `argocd` CLI or when
`argocd cluster add` cannot choose an ArgoCD-reachable test API address.

Observed drift on 2026-06-15 (#1577):

- staging host has `kubectl`/Docker and both kubeconfig contexts, but no
  `argocd` CLI;
- `k3d-test` API is exposed on host loopback `https://127.0.0.1:7443`;
- prod ArgoCD pods cannot reach host-loopback or the separate
  `platform-test-net` Docker bridge directly;
- public exposure of the test API is not acceptable.

The bounded alternative is an internal-only `socat` bridge container connected
to both Docker bridges, with **no published host ports**:

```text
k3d-prod ArgoCD pod
  -> platform-prod-net bridge IP of platform-argocd-test-api-bridge:6443
  -> socat TCP proxy
  -> k3d-test-serverlb:6443 on platform-test-net
```

The ArgoCD cluster Secret uses:

- `server=https://<bridge-prod-net-ip>:6443`
- `tlsClientConfig.serverName=k3d-test-serverlb`
- `caData` from the `k3d-test` service-account token Secret
- bearer token from the `kube-system/argocd-manager-token` Secret

Scripted path:

```bash
# Preview, no mutation:
bash bootstrap/register-test-cluster-argocd-secret.sh

# Apply live mutation:
APPLY=1 bash bootstrap/register-test-cluster-argocd-secret.sh
```

Rollback:

```bash
# Remove ArgoCD cluster secret + internal Docker bridge.
APPLY=1 ROLLBACK=1 bash bootstrap/register-test-cluster-argocd-secret.sh

# Also remove test-cluster RBAC/token if the registration should be fully
# dismantled:
APPLY=1 ROLLBACK=1 ROLLBACK_TEST_RBAC=1 \
  bash bootstrap/register-test-cluster-argocd-secret.sh
```

Security boundary:

- The script does not print bearer token material.
- The bridge has no host-published port and is reachable only from Docker
  networks already present on the staging host.
- This is still a live state change: Docker bridge container in host state,
  `kube-system` SA/CRB/Secret in `k3d-test`, and cluster Secret in prod ArgoCD.

## Step 3 — Verify cluster credential

```bash
ssh halil@staging-sw 'argocd cluster list 2>&1' | grep test-cluster
```

Expected: row containing `test-cluster` + the k3d-test API server URL +
`Successful` connection state.

For the CLI-less path, verify the cluster Secret exists:

```bash
ssh halil@staging-sw '
  kubectl --context k3d-prod -n argocd get secret cluster-test-cluster \
    -o jsonpath="{.data.name}{\"\n\"}{.data.server}{\"\n\"}"
'
```

Then verify the `platform-test` Application condition no longer reports
`unable to find destination server: there are no clusters with this name:
test-cluster`.

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

> Codex `019e42c4` REVISE absorb — root.yaml `automated.selfHeal: true` child
> Application spec'i otomatik düzeltir; spec patch ile sync disable kalıcı
> DEĞİL.

**Durable rollback — Git revert** (tercih edilen):
1. Open a revert PR for the Guardrail PR-2 commit (re-adds `platform-test.yaml`
   to `root.yaml` `exclude`, restores `prune: true`).
2. Merge revert → prod root reconciles → `platform-test` Application removed
   from cluster.
3. Optionally `argocd cluster rm test-cluster` to also remove the credential.

**Emergency stop (durable until next root reconcile)** — credential remove:
```bash
ssh halil@staging-sw 'argocd cluster rm test-cluster --yes'
```
Test cluster's `argocd-manager` SA + CRB removed; `platform-test` Application
goes `Unknown` (no target). The cluster's existing workloads continue running
unchanged (in-cluster k3d-test state independent of ArgoCD registration);
ArgoCD only stops new syncs, doesn't undo prior ones. Note: if root is left
in current PR-2 state, root will re-keep the `platform-test` Application CR
in `argocd` namespace; only its target is broken.

**Spec patches do NOT durably stop sync** — e.g.,
`kubectl patch application platform-test ... '{"spec":{"syncPolicy":{"automated":null}}}'`
gets reverted by root's `selfHeal: true` on next reconcile cycle. Use Git
revert or `argocd cluster rm` instead.

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
