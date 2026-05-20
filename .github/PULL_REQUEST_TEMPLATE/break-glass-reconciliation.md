## Break-glass reconciliation

> **Required**: This PR reconciles state changes made via break-glass token within the last 30min.

## Audit reference

- **Audit issue**: #<break-glass-issue-number>
- **Operator**: @<github-username>
- **Cluster context**: `k3d-test` | `k3d-prod`
- **Time of break-glass token issue**: `<YYYY-MM-DDTHH:MM:SSZ>`
- **Reason** (verbatim from token issue): `<reason>`

## State changes made

Describe each cluster state change made under the break-glass token:

1. <command-1 + outcome>
2. <command-2 + outcome>
3. ...

## Reconciliation in this PR

This PR brings the gitops desired-state YAML in sync with the cluster live-state changes:

- [ ] `kustomize/base/<resource>.yaml` updated to match live state
- [ ] `kustomize/overlays/<env>/<resource-patch>.yaml` updated if env-specific
- [ ] No drift remains: `bash scripts/drift-detection/check_env_drift.sh <env>` → exit 0
- [ ] If digest change: corresponding `release-candidates/<repo>/<sha>.json` ledger entry generated

## Why break-glass was needed

Explain why ArgoCD sync OR a regular gitops PR couldn't address the issue:

- [ ] ArgoCD hub was down (point to RB-argocd-hub-recovery.md scenario)
- [ ] Operator response time < ArgoCD sync cadence (e.g. P1 alarm requiring <10min response)
- [ ] CRD/ResourceQuota issue blocking ArgoCD sync (chicken-and-egg)
- [ ] Other: <explain>

## Operator review checklist

- [ ] All cluster mutations are now reflected in gitops YAML (no hidden drift)
- [ ] Drift detection runs clean (test + prod)
- [ ] D29 smoke runs green post-reconciliation
- [ ] Audit issue (#) updated with reconciliation PR link
- [ ] GitHub issue closed when this PR merges

## Boundary declaration (ADR-0011 §2.3)

- [ ] credential-read
- [ ] credential-write
- [x] state-mutation (test cluster) — if test cluster touched
- [x] state-mutation (production) — if prod cluster touched
- [ ] boundary-cross
- [ ] user-communication
- [ ] none of the above

User-approval evidence: break-glass audit issue #<num> + this reconciliation PR.

## Time budget compliance

- Break-glass token issued at: `<HH:MM:SS>`
- This PR opened at: `<HH:MM:SS>`
- Time delta: `<X>min`

If > 30min: explain why (e.g. additional verification needed before reconciliation).

---

🤖 Template: .github/PULL_REQUEST_TEMPLATE/break-glass-reconciliation.md (Codex Sprint C)
