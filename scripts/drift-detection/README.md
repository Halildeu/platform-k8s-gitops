# Drift Detection — Codex P0 Truth-Hierarchy Enforcer

> Codex AGREE Session 37 (2026-05-04, thread 019df2bf-d910-7920-b888-cb21a4f71059) —
> "Live cluster is EVIDENCE, not source-of-truth. SSOT = origin/main GitOps yaml.
> When live ≠ git → drift incident, NOT successful deploy."

## What this catches

- **P1 (operator action required)**:
  - Git overlay digest ≠ Pod imageID
  - GHCR manifest unknown (digest garbage-collected)
  - ArgoCD platform-{env} not Synced/Healthy
  - ConfigMap KEYCLOAK_ISSUER_URI missing on a JWT-validating service
- **P2 (warning)**:
  - Live service has no gitops entry (e.g. endpoint-admin-service test'te canlı, prod yaml'da yok)
  - Service in yaml but no live pods
  - ResourceQuota headroom < one surge pod (rollout fail riski)
- **P3** (future): stale current-state docs, smoke creds missing

## Run manually

```bash
# On staging-sw or any host with kubectl context k3d-prod / k3d-test
cd /home/halil/platform/platform-k8s-gitops
bash scripts/drift-detection/check_env_drift.sh prod    # P1 cadence
bash scripts/drift-detection/check_env_drift.sh test    # P2 cadence
```

Exit codes:
- `0` — clean (all aligned)
- `1` — P1 drift (operator action required)
- `2` — P2 drift (lag / headroom warning)
- `3` — exec error (kubectl/git/docker unreachable)

Output: `/tmp/drift-report-<env>-<ts>.json` with structured findings + console summary.

## Schedule on staging-sw (systemd)

```bash
# Install (idempotent)
sudo cp scripts/drift-detection/systemd/drift-prod.{service,timer} /etc/systemd/system/
sudo cp scripts/drift-detection/systemd/drift-test.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now drift-prod.timer drift-test.timer

# Verify
systemctl status drift-prod.timer
journalctl -u drift-prod.service -n 30
tail -f /var/log/platform-drift-prod.log
```

Cadence:
- **prod**: every 5 minutes (after 120s boot delay)
- **test**: every 15 minutes (after 180s boot delay)

## Integration with PR-time gate (P0 follow-up)

A GitHub Actions workflow `.github/workflows/gate-drift-pr-time.yml` (next PR)
will run this same script in PR-time render mode (yaml-only checks, no
kubectl) so promotion PRs that introduce digest drift fail before merge.
The runtime/scheduled mode (this directory) catches drift introduced by
out-of-band manual interventions on the cluster.

## Alarm receivers (P1 follow-up)

Codex framework prescribes:
- **P1**: prod git/live digest mismatch >10min, GHCR manifest unknown,
  ESO SecretSyncedError, OpenFGA admin tuple missing, authz synthetic 3 fail
- **P2**: test git/live drift >30min, prod promotion lag >7d, endpoint-admin
  service catalog mismatch, quota headroom < one surge pod
- **P3**: stale current-state docs, optional smoke credentials missing,
  runner label persistence belirsizliği

MVP outputs JSON to `/tmp/`; alarm receiver (email + GitHub issue audit)
will be added in a follow-up PR. Slack/PagerDuty deferred to P2 per Codex.

## Truth hierarchy enforcement

Per `docs/context-priority-rules.md`:
1. Live evidence (this script's findings)
2. `docs/state/current-state.md`
3. ADR
4. PLAN

When this script reports drift, **the LIVE state is correct evidence** —
but **the gitops yaml IS the desired source-of-truth**. A drift finding
should trigger one of:
- A reconciliation PR that updates yaml to match live (legitimate state)
- A revert/rollout that brings live back to yaml (cluster broke contract)

Never accept "live is fine, ignore yaml" silently. That's how D30 immutable
artifact discipline rotted in the past (per session 37 audit).
