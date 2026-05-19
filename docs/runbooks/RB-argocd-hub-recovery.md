# RB-argocd-hub-recovery — ArgoCD Hub Recovery Runbook

> Codex 2026-05-04 thread `019df310` Sprint A:
> "ArgoCD hub option: A pre-cutover, B post-cutover follow-up. Şimdi A:
> ArgoCD health probe, sync-age alarm, repo credential backup, 'hub down
> iken manual sync/recover' runbook, app status export, alarm receiver
> entegrasyonu."
>
> ADR-0002 single-host-dual-cluster aktif kararı: tek ArgoCD hub k3d-prod
> içinde. Bu runbook hub down olduğunda recovery + rollback prosedürünü
> tanımlar. Pre-cutover scope: monitoring + recovery only. Dedicated hub
> cluster (Option B) post-cutover follow-up.

## Sorun

Mevcut ArgoCD topolojisi (ADR-0002):
- Tek ArgoCD hub `k3d-prod` cluster içinde
- Hub k3d-prod'u in-cluster olarak yönetir (`server: https://kubernetes.default.svc`)
- Hub k3d-test'i cluster secret üzerinden (`name: test-cluster`) yönetir

**Single point of failure**:
- ArgoCD hub down (k3d-prod cluster issue, ArgoCD Deployment crash, network) → 
  test ve prod cluster'a gitops sync DURUR
- Operatör manuel intervene etmek zorunda kalır
- Drift detection alarm'ları gelir ama otomatik recovery yok

Pre-cutover'da bu kabul edilebilir risk (Codex AGREE), çünkü:
- Operator (halil) staging-sw'de sürekli, manual recovery hızlı
- D30 cutover öncesi infrastructure değişikliği yeni failure mode yaratır
- Post-cutover dedicated hub cluster mantıklı (Option B follow-up)

Bu runbook kabul edilebilir riski operasyonel olarak yönetilebilir hale getirir.

## Health probe (proactive monitoring)

### Manual check (operator)

```bash
# ArgoCD server reachable?
kubectl --context k3d-prod -n argocd get pods -l app.kubernetes.io/name=argocd-server
# Expected: Running 1/1

# ArgoCD applications health
kubectl --context k3d-prod -n argocd get application
# Expected: SYNC_STATUS=Synced, HEALTH_STATUS=Healthy for all

# Recent sync activity
kubectl --context k3d-prod -n argocd get application platform-prod \
  -o jsonpath='{.status.operationState.startedAt}'
# Expected: within last 1h for active deploy windows

# Repo connection health
kubectl --context k3d-prod -n argocd exec -it deployment/argocd-server -- \
  argocd repo list
# Expected: github.com/Halildeu/platform-k8s-gitops Connection=Successful
```

### Automated (systemd integration — TODO)

Future enhancement: systemd timer that runs the above checks every 5min and
emits alarm via alarm_receiver.sh if any failure.

```bash
# scripts/argocd-monitoring/check_hub_health.sh (TODO Sprint follow-up)
# - Check argocd-server pod Running
# - Check applications all Synced+Healthy
# - Check last successful sync within 24h
# - Check repo connection alive
# - Emit alarm if any failure → alarm_receiver.sh format
```

## Failure modes

### Mode 1: ArgoCD pod CrashLoopBackOff

**Symptom**:
- `kubectl get pods -n argocd` shows CrashLoopBackOff
- `kubectl logs <pod>` reveals error (DB conn, repo creds, OOM)

**Diagnosis**:
```bash
kubectl --context k3d-prod -n argocd describe pod <argocd-server-pod>
kubectl --context k3d-prod -n argocd logs <argocd-server-pod> --previous
```

Common causes:
- Redis connection failed (argocd-redis pod also CrashLoopBackOff)
- Repo credentials expired (rare; rotate if needed)
- Resource quota tight (memory limit hit)

**Recovery**:
```bash
# Quick restart
kubectl --context k3d-prod -n argocd rollout restart deploy/argocd-server

# If memory issue, scale Redis dependency too
kubectl --context k3d-prod -n argocd rollout restart deploy/argocd-repo-server
kubectl --context k3d-prod -n argocd rollout restart deploy/argocd-redis

# Watch
kubectl --context k3d-prod -n argocd get pods -w
```

### Mode 2: Application stuck "Progressing"

**Symptom**:
- `kubectl get application platform-prod` shows SYNC=OutOfSync, HEALTH=Progressing for >10min
- Some pod ImagePullBackOff or Pending

**Diagnosis**:
```bash
kubectl --context k3d-prod -n argocd get application platform-prod \
  -o jsonpath='{.status.conditions}' | jq

# Cluster-side: which pod is stuck?
kubectl --context k3d-prod -n platform-prod get pods | grep -v Running
kubectl --context k3d-prod -n platform-prod describe pod <stuck-pod>
```

Common causes:
- Image not in GHCR (digest GC'd) → drift detection should catch this; runtime detector P1 alarm
- ResourceQuota exceeded (strict rollout maxSurge=1 needs headroom)
- ConfigMap missing (envFrom reference broken)

**Recovery**:

For digest-GC'd:
```bash
# Find a known-good digest (drift detector report or release-candidates ledger)
LATEST_OK=$(jq -r '.image.digest' release-candidates/platform-backend/<sha-with-test-verified>.json)

# Update overlay yaml + commit + push (proper gitops path)
# OR break-glass:
kubectl --context k3d-prod -n platform-prod set image deploy/<service> \
  <container>=ghcr.io/halildeu/platform-backend-<service>@$LATEST_OK
```

For quota exceeded:
```bash
# Scale 2→1→2 cycle to release surge slot
kubectl --context k3d-prod -n platform-prod scale deploy/<service> --replicas=1
sleep 30
kubectl --context k3d-prod -n platform-prod scale deploy/<service> --replicas=2
```

### Mode 3: ArgoCD repo connection lost

**Symptom**:
- ArgoCD UI shows red repo connection
- New PR merges don't trigger sync
- `argocd repo list` shows Failed

**Diagnosis**:
```bash
kubectl --context k3d-prod -n argocd exec -it deploy/argocd-server -- \
  argocd repo get https://github.com/Halildeu/platform-k8s-gitops.git

# Check repo credentials secret
kubectl --context k3d-prod -n argocd get secret argocd-repo-platform-k8s-gitops -o yaml
```

Common causes:
- GitHub PAT expired (typically 1y; check expiry)
- Token revoked / scope changed
- Network issue (rare)

**Recovery**:

```bash
# Re-add repo with current PAT (or fine-grained token)
NEW_PAT="ghp_..." # from secure operator vault

kubectl --context k3d-prod -n argocd exec -it deploy/argocd-server -- \
  argocd repo add https://github.com/Halildeu/platform-k8s-gitops.git \
  --username Halildeu \
  --password $NEW_PAT

# Verify connection
kubectl --context k3d-prod -n argocd exec -it deploy/argocd-server -- \
  argocd repo list
```

### Mode 4: ArgoCD hub completely down (k3d-prod cluster issue)

**Symptom**:
- `kubectl --context k3d-prod` returns connection refused
- k3d-prod cluster itself unhealthy (control-plane down, etc.)

**Diagnosis**:
```bash
# Check k3d cluster state
k3d cluster list
docker ps | grep k3d-prod

# Check k3s container logs
docker logs k3d-prod-server-0 --tail=100
```

**Recovery (escalation)**:

If k3d-prod cluster is genuinely down, the failure scope is bigger than
ArgoCD — see `docs/D32-bootstrap-runbook.md` for full prod cluster recovery.
ArgoCD will come back online with the cluster.

If only the cluster's ArgoCD namespace is broken:

```bash
# Reinstall ArgoCD (idempotent; preserves Application CRs)
kubectl --context k3d-prod -n argocd apply -k argocd/install/

# Wait for argocd-server to come up
kubectl --context k3d-prod -n argocd rollout status deploy/argocd-server --timeout=300s

# Re-add repo if needed (Mode 3 procedure)
```

**Operations during hub-down**:

While ArgoCD hub is down, gitops sync stops. Operator may need to:
1. Stop merging PRs to main (avoid sync gap)
2. Manually apply critical fixes via `kubectl apply -f` (ROLLBACK to gitops PR after recovery)
3. Document break-glass actions in audit log + open reconciliation PR within 24h

### Mode 5: repo-server cannot resolve argocd-redis (ComparisonError)

**Symptom**:
- Application sync status stuck `Unknown` (health may still read `Healthy`)
- Application condition `ComparisonError: Failed to load target state: failed
  to generate manifest ... rpc error: ... dial tcp: lookup argocd-redis ...
  server misbehaving`
- `deploy-prod-gitops.yml` fails at `argocd app wait` (900s timeout) even
  though `argocd app sync` itself reported `Phase: Succeeded`

**Diagnosis**:
```bash
# repo-server pod resolv.conf — healthy pods point at CoreDNS (10.43.0.10)
RS=$(kubectl --context k3d-prod -n argocd get pod \
  -l app.kubernetes.io/name=argocd-repo-server -o jsonpath='{.items[0].metadata.name}')
kubectl --context k3d-prod -n argocd exec "$RS" -c repo-server -- cat /etc/resolv.conf
# BAD: `nameserver 172.x.0.1`, `ndots:0`, no `search` line → node resolv.conf
# GOOD: `nameserver 10.43.0.10`, `search ... svc.cluster.local`, `ndots:5`

# Root cause: hostNetwork + dnsPolicy mismatch
kubectl --context k3d-prod -n argocd get deploy argocd-repo-server \
  -o jsonpath='hostNetwork={.spec.template.spec.hostNetwork} dnsPolicy={.spec.template.spec.dnsPolicy}{"\n"}'
# BAD: hostNetwork=true + dnsPolicy=ClusterFirst — invalid combo: a
#      hostNetwork pod needs dnsPolicy ClusterFirstWithHostNet for cluster
#      DNS, else it inherits the node resolv.conf and cannot resolve the
#      argocd-redis Service.
```

**Recovery**:
```bash
# repo-server needs no host networking — remove the drift.
kubectl --context k3d-prod -n argocd get deploy argocd-repo-server -o yaml \
  > ~/argocd-backups/argocd-repo-server-$(date -u +%Y%m%dT%H%M%SZ).yaml
kubectl --context k3d-prod -n argocd patch deploy argocd-repo-server \
  --type=merge -p '{"spec":{"template":{"spec":{"hostNetwork":false}}}}'
kubectl --context k3d-prod -n argocd rollout status deploy/argocd-repo-server --timeout=150s

# New pod gets cluster DNS — confirm, then refresh the app
kubectl --context k3d-prod -n argocd annotate application platform-prod \
  argocd.argoproj.io/refresh=hard --overwrite
# Expected: sync status leaves Unknown → Synced, ComparisonError clears
```

The canonical source-of-truth `helm-values/argocd/values.yaml` pins
`repoServer.hostNetwork: false`; a future `helm upgrade` re-asserts it. If
hostNetwork is ever genuinely required, switch `dnsPolicy` to
`ClusterFirstWithHostNet` instead — never leave `ClusterFirst` + hostNetwork.

## Repo credential backup

ArgoCD repo credentials live in:
- `kubectl --context k3d-prod -n argocd get secret argocd-repo-platform-k8s-gitops`

This secret is NOT in gitops (it would be a chicken-and-egg cycle). Backup procedure:

### Manual backup (T-X cutover)

```bash
# Export secret to encrypted file
kubectl --context k3d-prod -n argocd get secret argocd-repo-platform-k8s-gitops \
  -o yaml | gpg --encrypt --recipient halil@... > /var/backups/argocd-repo-secret.gpg

# Or simpler: store the PAT in operator's password manager
```

### Automated backup (Sprint follow-up TODO)

Consider:
- Vault KV store: `kv/argocd/repo-credentials`
- ESO ExternalSecret to seed secret on cluster recovery (chicken-and-egg: ESO needs Vault, Vault is host compose, available even if k3d-prod down)

This pattern aligns with HARD RULE #6 (warm rollback): cluster can be re-bootstrapped with credentials available.

## Sync-age alarm (TODO Sprint follow-up)

Add to drift detection family of scripts:

```bash
# scripts/drift-detection/check_argocd_sync_age.sh (TODO)
# For each Application:
#   - Read .status.operationState.finishedAt
#   - If now() - finishedAt > 24h: P2 alarm (stale gitops sync)
#   - If > 7d: P1 alarm (gitops sync broken silently)
```

Reuse existing alarm_receiver.sh for delivery.

## Disaster recovery procedure

If a full disaster (k3d-prod cluster lost, ArgoCD config gone):

1. **Bootstrap k3d-prod cluster from scratch** (D32 runbook)
2. **Reinstall ArgoCD** (`argocd/install/` kustomize manifest applied via kubectl)
3. **Re-add repo credential** (from operator backup OR Vault)
4. **Apply root.yaml** (`kubectl apply -f argocd/applications/root.yaml`)
5. **Wait for app-of-apps sync** (creates platform-prod, platform-eso-prod, etc.)
6. **Verify sync success** (all applications Synced+Healthy)
7. **Run D29 smoke** (`bash scripts/smoke/d29-smoke-runner.sh prod`)

Total time: ~30-60min if all backups available.

## Post-cutover roadmap (Option B)

After D30 cutover succeeds + 72h rollback window expires, consider:

- Dedicated `k3d-argocd` hub cluster (third k3d on staging-sw, separate from data plane)
- Migrate all Application + AppProject CRs to new hub
- Original k3d-prod becomes pure data-plane (no ArgoCD)
- Hub cluster has no business workload → smaller blast radius for ArgoCD upgrades

This is non-trivial migration (cluster secret update, ApplicationSet rewrite,
ESO ClusterSecretStore split). Schedule for post-D30 stability window.

ADR amendment: ADR-0002 to reference this option as planned future state.

## Related artifacts

- `docs/adr/0002-single-host-dual-cluster.md` — current architecture
- `docs/D32-bootstrap-runbook.md` — full prod cluster bootstrap
- `argocd/applications/root.yaml` — app-of-apps root
- `argocd/applicationsets/platform-overlays.yaml` — multi-cluster pattern (DRAFT)
- `scripts/drift-detection/alarm_receiver.sh` — alarm delivery (extension point for sync-age)
