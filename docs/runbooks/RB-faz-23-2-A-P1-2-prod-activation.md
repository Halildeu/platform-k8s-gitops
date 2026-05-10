# RB Faz 23.2.A P1.2 — M3 Next Gate Prod Activation Runbook

> **Trigger**: PR #501 merged. ArgoCD `platform-prod` + `platform-eso-prod` apps OutOfSync.
> **Estimated**: ~30dk operator
> **Risk**: medium (validator activation 9-guard fail-closed; rollback simple revert + sync)

## Context

P1.2 M3 next gate split sequence:

**PR-A (this PR #501)** completes prod desired-state for ProductionConfigValidator
activation. 4 prerequisites + test digest promotion (5 changes):

1. Test overlay digest sha-204042d → sha-c4a03fc (PR #147 build)
2. Prod ESO ExternalSecret 5→15 keys
3. Prod Vault seed (Pre-Production Full Authority done 2026-05-10 18:22Z)
4. Prod ConfigMap `NOTIFY_UNSUBSCRIBE_BASE_URL` + SMTP TLS env + dispatch=false
5. Prod profile flip `SPRING_PROFILES_ACTIVE=k8s,prod` (7-guard activation
   on OLD binary sha-204042d)

**PR-B (follow-up after D29 ledger)**: prod backend digest bump
sha-204042d → sha-c4a03fc (after auto-promotion bot creates ledger entry
from test smoke). PR-B activates 9 full guards (7 old + unsubscribe
signing-secret + base-url URI parser allowlist).

Repo topology: `platform-prod` (workload) and `platform-eso-prod` (ESO) are
**separate ArgoCD apps**. Apply ordering matters — wrong sequence triggers
pod CrashLoop.

PR-A guard activation matrix (sha-204042d binary):
| Guard | Active? |
|---|---|
| SMTP TLS enforce | ✅ |
| SMTP TLS check-server-identity | ✅ |
| redaction pepper | ✅ |
| webhook signing-secret | ✅ |
| authz enabled | ✅ |
| authz internal-api-key | ✅ |
| preferences enabled | ✅ |
| unsubscribe signing-secret | ❌ (added PR #144 / sha-c4a03fc) |
| unsubscribe base-url URI allowlist | ❌ (added PR #147 / sha-c4a03fc) |

PR-B post-promotion adds last 2 guards. Profile flip with old 7-guard binary
safe because NOTIFY_DISPATCH_ENABLED=false silences email path.

## Apply sequence (zorunlu sıra)

```bash
# Step 1 — sync ESO first (Secret extension to 15 keys)
kubectl --context k3d-prod -n argocd patch app platform-eso-prod \
  --type merge -p '{"operation":{"sync":{}}}'

# Wait for ArgoCD sync (Codex iter-2 fix: ArgoCD Application sync.status is
# a JSON status field, not a Kubernetes condition. `kubectl wait
# --for=condition=Synced=true` produces a false-negative timeout.)
until [[ "$(kubectl --context k3d-prod -n argocd get app platform-eso-prod \
  -o jsonpath='{.status.sync.status}/{.status.health.status}' 2>/dev/null)" == "Synced/Healthy" ]]; do
  echo "... waiting platform-eso-prod sync"; sleep 5
done

# Step 2 — force ESO refresh (Secret render new 10 keys)
kubectl --context k3d-prod -n platform-prod \
  annotate externalsecret notification-orchestrator-secrets \
  force-sync=$(date +%s) --overwrite

sleep 10

# Step 3 — verify Secret 15 keys
kubectl --context k3d-prod -n platform-prod \
  get secret notification-orchestrator-secrets \
  -o jsonpath='{.data}' | python3 -c "
import json, sys, base64
d = json.load(sys.stdin)
print(f'Keys ({len(d)}):', sorted(d.keys()))
"

# Expected: 15 keys including NOTIFY_UNSUBSCRIBE_SIGNING_SECRET,
# NOTIFY_ADAPTERS_TEAMS_WEBHOOK_URL, NOTIFY_ADAPTERS_PUSH_FCM_SERVICE_ACCOUNT_KEY, etc.
# If still 5 keys → STOP. Investigate ESO sync state before proceeding.

# Step 4 — sync workload (apply Deployment patch + ConfigMap update)
kubectl --context k3d-prod -n argocd patch app platform-prod \
  --type merge -p '{"operation":{"sync":{}}}'

# Wait for ArgoCD sync (jsonpath status field, not condition)
until [[ "$(kubectl --context k3d-prod -n argocd get app platform-prod \
  -o jsonpath='{.status.sync.status}/{.status.health.status}' 2>/dev/null)" == "Synced/Healthy" ]]; do
  echo "... waiting platform-prod sync"; sleep 5
done

# Step 5 — wait for rolling restart
kubectl --context k3d-prod -n platform-prod rollout status \
  deploy/notification-orchestrator --timeout=180s

# Step 6 — verify pod imageID + profile + validator PASS
POD=$(kubectl --context k3d-prod -n platform-prod \
  get pod -l app.kubernetes.io/name=notification-orchestrator \
  -o jsonpath='{.items[0].metadata.name}')

kubectl --context k3d-prod -n platform-prod \
  get pod $POD -o jsonpath='{.status.containerStatuses[0].imageID}'
# PR-A expected: ...platform-backend-notification-orchestrator@sha256:ef0f487f...
#   (sha-204042d, PR #126 era — old binary, 7 working guards)
# PR-B expected: ...platform-backend-notification-orchestrator@sha256:70491543...
#   (sha-c4a03fc, PR #147 — new binary, 9 working guards including
#   unsubscribe signing-secret + base-url URI allowlist)

kubectl --context k3d-prod -n platform-prod exec $POD -- \
  env | grep '^SPRING_PROFILES_ACTIVE='
# Expected: SPRING_PROFILES_ACTIVE=k8s,prod

kubectl --context k3d-prod -n platform-prod logs $POD | \
  grep -E "ProductionConfigValidator|all production guards"
# Expected: "ProductionConfigValidator: all production guards PASSED"
# Validator log message is identical for PR-A and PR-B (no count); pair the
# PASS log with imageID check above to determine which guard set is active:
#   imageID sha256:ef0f487f... → 7 working guards (PR-A old binary)
#   imageID sha256:70491543... → 9 working guards (PR-B new binary)

# Step 7 — health endpoint smoke (Codex iter-2 fix: management port 8081,
# not service port 8089/8080. Actuator /health binds to management port.)
kubectl --context k3d-prod -n platform-prod \
  port-forward svc/notification-orchestrator 9999:8081 &
PF_PID=$!
sleep 3
curl -sf http://localhost:9999/actuator/health | jq -c
kill $PF_PID
# Expected: {"status":"UP",...}

# Step 8 — browser verify (HARD RULE — deploy sonrası tarayıcı verifikasyonu)
# Navigate to https://ai.acik.com/ → check console errors + network 5xx
```

## Verification gates (MUST PASS)

PR-A apply gates:
- [ ] ESO Secret 15-key (Step 3)
- [ ] Pod imageID == `sha256:ef0f487f...` (Step 6 — old prod binary stays)
- [ ] `SPRING_PROFILES_ACTIVE=k8s,prod` (Step 6)
- [ ] Validator log "all production guards PASSED" — 7 guards (Step 6)
- [ ] Health endpoint UP (Step 7)
- [ ] Browser console + network smoke (Step 8)

PR-B apply gates (after auto-promotion ledger):
- [ ] Pod imageID == `sha256:70491543...` (sha-c4a03fc, PR #147 binary)
- [ ] Validator log 9 guards PASSED (full set including base-url URI allowlist)

## Rollback (fail-closed startup case)

Eğer Step 5'de pod CrashLoopBackOff veya Step 6'da validator log
"Production config validation FAILED" görünürse:

```bash
# Quick rollback — revert profile flip only (other prerequisites can stay)
git revert <P1.2-merge-commit-sha> -m 1
git push origin main

# Or local hot patch (faster):
kubectl --context k3d-prod -n platform-prod \
  set env deploy/notification-orchestrator SPRING_PROFILES_ACTIVE=k8s

# Wait for rollback rollout
kubectl --context k3d-prod -n platform-prod rollout status \
  deploy/notification-orchestrator --timeout=120s

# Now diagnose validator failure:
kubectl --context k3d-prod -n platform-prod logs $POD | grep -A20 \
  "Production config validation FAILED"

# Common causes:
#   - Vault key empty (e.g. unsubscribe_signing_secret seed not propagated)
#   - ConfigMap env binding case mismatch (Spring relaxed binding)
#   - Backend image mismatch (PR #147 not on prod)
```

ESO Secret 15-key extension does NOT need rollback — additive change, old
binary tolerates extra envs. Only profile flip is the activation gate.

## Why dispatch disabled

`NOTIFY_DISPATCH_ENABLED=false` set on prod ConfigMap (Codex iter-1 P1
absorb). Pre-prod context — base configmap `NOTIFY_ADAPTERS_SMTP_HOST=
OVERLAY_MUST_OVERRIDE` placeholder + `FROM=noreply@testai.acik.com` test
default. Email dispatch path inactive until R1 contract activation
(NetGSM ETA 2026-05-30) flips dispatch + sets real SMTP gateway in prod
overlay. Unsubscribe link generation (UnsubscribeUrlBuilder) runtime path
still works (URL composer); only outbound email is silent.

## References

- Codex thread `019e1307` (iter-3 RED → P1.2 absorb + iter-1 PR #501)
- HARD RULE — Pre-Production Full Authority (Vault seed)
- HARD RULE — Browser console verify (deploy sonrası tarayıcı)
- Charter sub-faz 23.2.A T1.1.8 P1.2 M3 next gate
