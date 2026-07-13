# Runbook — backend testai desired-state promotion

> Canonical flow: immutable full digest map → reviewable test-overlay PR →
> normal review/CI/merge → ArgoCD auto-sync waves → read-only runtime evidence.
>
> Authority: ADR-0023. Main `k3d-test` workloads are changed only through
> `kustomize/overlays/test`; direct `kubectl set image`, `kubectl patch`,
> `kubectl edit` and workflow-owned resource sync are prohibited.

## Scope

`platform-backend` publishes immutable images and dispatches one complete
13-service digest map. `deploy-backend-testai.yml` validates that contract on a
GitHub-hosted runner and opens or updates
`auto-test-overlay/backend-testai`. It has no cluster credentials and performs
no runtime mutation.

After normal PR merge, ArgoCD's existing `main` auto-sync applies the desired
state. Test-only `argocd.argoproj.io/sync-wave` annotations provide quota-aware
dependency ordering. `verify-testai-backend-rollout.yml` only observes exact
revision convergence and runs acceptance checks.

Targeted single-service source builds are build-only. They do not dispatch an
incomplete promotion map.

## Service and wave contract

| Wave | Digest key | Deployment |
|---:|---|---|
| 10 | `auth-service` | `auth-service` |
| 11 | `permission-service` | `permission-service` |
| 12 | `user-service` | `user-service` |
| 13 | `variant-service` | `variant-service` |
| 14 | `core-data-service` | `core-data-service` |
| 15 | `report-service` | `report-service` |
| 16 | `schema-service` | `schema-service` |
| 17 | `endpoint-admin-service` | `endpoint-admin-service` |
| 18 | `audio-gateway-service` | `audio-gateway` |
| 19 | `meeting-service` | `meeting-service` |
| 20 | `transcript-service` | `transcript-service` |
| 21 | `audit-event-consumer-service` | `audit-event-consumer-service` |
| 22 | `api-gateway` | `api-gateway` |

Unannotated infrastructure remains at ArgoCD's default wave `0`. ArgoCD waits
for the current wave to become healthy before proceeding. `api-gateway` is last
so the public entry point changes only after its dependencies.

The test overlay also carries `maxSurge=0/maxUnavailable=1` for these
single-replica, quota-sensitive Deployments. That permits a bounded test-only
availability gap without needing an extra surge pod. Production rollout
strategy is not changed by this contract.

## Trigger contract

- Automatic: `repository_dispatch`, event type `backend-testai-deploy`.
- Manual recovery: `workflow_dispatch` with `sha`, matching `short_sha`, and
  the complete 13-service digest JSON.
- Every digest must match `sha256:<64 lowercase hex>`.
- Missing, extra, duplicate, malformed or partial service maps fail before PR
  mutation.
- Missing `AUTOMATION_APP_ID` or `AUTOMATION_APP_PRIVATE_KEY` fails before PR
  mutation; there is no legacy direct-deploy fallback.

Manual dispatch example:

```bash
gh workflow run deploy-backend-testai.yml \
  -R Halildeu/platform-k8s-gitops \
  -f sha='<40-lowercase-hex>' \
  -f short_sha='<first-7-hex>' \
  -f digests='<complete-13-service-json-map>'
```

Do not place credentials or tokens in the digest payload. GitHub App secrets
remain repository Actions secrets.

## Merge and reconciliation

1. Automation opens or updates `auto-test-overlay/backend-testai` from current
   `origin/main`.
2. Review confirms only allowlisted test-overlay digest fields changed. If
   endpoint-admin changes, its two owner-gated bridge mirror digests must move
   in lockstep.
3. Required CI passes; merge uses the normal protected-branch path.
4. ArgoCD auto-sync observes the merged `main` revision and processes waves
   `10..22`.
5. The self-hosted verifier waits until Application `platform-test` reports
   exact merge revision + `Synced` + `Healthy` in at least two consecutive
   polls, with no in-flight mismatched operation.
6. Runtime acceptance checks all 13 imageID digests, public edge, readiness,
   per-service stability and optional authenticated smoke.

The verifier checks `origin/main` before accepting convergence and again before
and after runtime evidence. If a newer relevant merge supersedes the requested
revision, the current run fails closed and the newer queued run owns evidence.

The verifier bootstraps exact ArgoCD CLI `v2.13.1` through an OS/architecture
allowlist and pinned official SHA-256. A global runner installation is not
trusted. CLI use is read-only (`app get --hard-refresh -o json`); the workflow
does not call `argocd app sync`.

## Acceptance evidence

| Gate | Requirement | Failure behavior |
|---|---|---|
| Desired-state lineage | PR merged at immutable git revision | blocking |
| ArgoCD convergence | exact revision, `Synced`, `Healthy` | blocking |
| D30 runtime | every live pod `imageID` equals expected digest | blocking |
| Public edge | `/api/users/all` returns `200`, `401` or `403`; never `5xx/0xx` | blocking |
| Readiness | all 13 services return `200` from actuator readiness | blocking |
| Stability | catalog-driven stability window passes per service | blocking |
| JWT functional smoke | authenticated request returns `200` when dedicated smoke credentials exist | conditional; absence is recorded as skipped |

`Up`, `Functional` and Zanzibar-ready evidence remain separate under D29. A
successful image promotion alone does not claim every product behavior.

## Failure triage

### Promotion workflow fails before PR

Inspect payload validation and GitHub App credential presence. Do not bypass by
running direct cluster mutation. Correct the source dispatch or App setup and
re-run the promotion.

### ArgoCD exact revision times out

Inspect the Application operation and resource health:

```bash
argocd --core --kube-context k3d-prod app get platform-test --hard-refresh
kubectl --context k3d-prod -n argocd get application platform-test -o yaml
```

If a wave resource is unhealthy, repair desired state through a new PR. Do not
force a different SHA with `argocd app sync --revision`; the Application tracks
`main` and auto-sync is authoritative.

### Runtime digest or readiness fails

Compare the merged overlay digest, Application observed revision, Deployment
image and non-terminating pod imageID. Read-only inspection is allowed. Any
correction to a workload spec or image pin goes through a new desired-state PR.

### Public edge fails

Check ingress, host routing and `api-gateway` health separately. Internal
cluster reachability is supporting evidence only; it does not replace the
authoritative public entry check.

## Rollback

Revert the immutable digest promotion commit through the normal PR path.
ArgoCD auto-sync applies the previous digest set using the same waves, and the
same exact-convergence/runtime verifier produces rollback evidence.

Never rollback with direct `kubectl set image`, direct Deployment patch/edit,
or a workflow-owned resource sync. Break-glass requires the four ADR-0023
conditions and same-incident Git reconciliation.

## References

- `docs/adr/0023-promotion-pipeline-test-overlay-authoritative.md`
- `docs/operations/RUNBOOKS/RB-automation-overlay-sync.md`
- `.github/workflows/deploy-backend-testai.yml`
- `.github/workflows/verify-testai-backend-rollout.yml`
- `scripts/automation/backend-testai-digest-contract.py`
- `scripts/deploy/reconcile-testai-backend-sequential.sh`
- `scripts/deploy/verify-testai-backend-runtime.sh`
- issue `#2384`
