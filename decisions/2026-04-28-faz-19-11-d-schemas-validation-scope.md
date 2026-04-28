# Decision — Faz 19.11.D `validate_schemas` Scope (Out of platform-k8s-gitops)

**Status**: Accepted — 2026-04-28
**Driver**: Faz 19.11.D ci/ port (PR-A done in #205, PR-B done in #206/207/208)
**Codex thread**: `019dd322` (PR-C scope decision recommended) + `019dd333` (retrospective verdict A primary)
**Authority**: Codex consensus sufficient (docs only, no live state mutation)

## Context

`ci/validate_schemas.py` is a JSON-schema validation gate ported from the
owning repo (platform-ssot or similar). Faz 19.11.D goal: port the gate
to platform-k8s-gitops as a CI workflow.

Inspection of the script (lines 73-482) reveals it expects:

- `schemas/*.schema.json` and `schemas/*.schema.v1.json` (general)
- Conditional schemas keyed off the existence of:
  - `fixtures/envelopes` → `schemas/request-envelope.schema.json`
  - `roadmaps/` → `schemas/roadmap.schema.json`
  - `roadmaps/SSOT/changes` → `schemas/roadmap-change.schema.json`
  - `roadmaps/SSOT/changes/debt` → `schemas/chg-debt.schema.json`
  - `script_budget.v1.json` → `schemas/script-budget.schema.json` (warn-only)
  - `formats/` → `schemas/format-autopilot-chat.schema.json`
  - `packs/` → `schemas/pack-manifest.schema.v1.json`
  - `roadmaps/PROJECTS` → `schemas/project-manifest.schema.json`
  - `capabilities/` → `schemas/spec-capability.schema.json`
  - `docs/OPERATIONS/repo-layout.v1.json` → `schemas/repo-layout.schema.json`
  - `fixtures/reports` → `schemas/smoke-root-cause-report.schema.v1.json`

## Repo inventory (2026-04-28)

```
$ for d in schemas fixtures/envelopes roadmaps formats packs capabilities; do
    [ -d "$d" ] && echo "$d EXISTS" || echo "$d MISSING"
  done
schemas MISSING
fixtures/envelopes MISSING
roadmaps MISSING
formats MISSING
packs MISSING
capabilities MISSING

$ for f in docs/OPERATIONS/repo-layout.v1.json fixtures/reports script_budget.v1.json; do
    [ -e "$f" ] && echo "$f EXISTS" || echo "$f MISSING"
  done
docs/OPERATIONS/repo-layout.v1.json MISSING
fixtures/reports MISSING
script_budget.v1.json MISSING
```

**Zero trigger conditions match.** Top-level dirs in this repo: `argocd/`,
`bootstrap/`, `ci/`, `decisions/`, `docs/`, `helm-values/`, `host-compose/`,
`kustomize/`, `policies/`, `scripts/`, `sql/`, `src/`, `tests/`.

This repo's substance is:
- Kubernetes/GitOps manifests
- SQL migrations + ETL worker (Python)
- Vault policies (HCL)
- Operational runbooks + ADRs
- CI scripts (this porting effort)

None of the schema-validated artifact families (envelopes, roadmaps,
formats, packs, capabilities, smoke reports) live in this repo's authority
boundary.

## Options considered

### Option A — Port `schemas/` directory from owning repo (REJECTED)

Port all `schemas/*.schema.json` files. Workflow runs validate_schemas, which checks "no schemas found" → script's first check fails (raises SystemExit at line 73).

Problem: the schemas would be unused in this repo because none of the trigger artifact families exist. Adding schema files only to satisfy a check creates check theater + maintenance burden (schemas drift from owning repo).

### Option B — Subset port (only schemas matching this repo's needs) (REJECTED)

Identify which schemas could apply (e.g., script-budget, repo-layout) and port those only.

Problem: every conditional in validate_schemas.py is keyed off file/dir existence; subsetting creates a partial gate that prints WARN/INVALID for missing trigger conditions, not actual validation. Half-running gate is worse signal than no gate.

### Option C — Mark `validate_schemas.py` out-of-scope in this repo (CHOSEN)

Document explicitly that `ci/validate_schemas.py` runs only in the owning repo (platform-ssot or wherever schema authority lives). In this repo, the script is present (ported) but unused — neither imported nor invoked from any workflow.

Add a `ci/SCOPE.md` documenting which scripts run as gates here vs which are owning-repo-only.

### Option D — Build new gitops-specific schema set (REJECTED, premature)

Design schemas matching this repo's content (e.g., kustomization.yaml strict schema, ADR template schema, runbook frontmatter schema) and add corresponding validate_schemas-equivalent gate.

Problem: this is a NEW gate, not a port of the existing one. Codex `019dd322` PARTIAL warned against expanding scope mid-port. If gitops-specific schema validation has value, raise it as a new ADR proposal post-Faz 19.11.D.

### Option E — Modify validate_schemas.py to no-op gracefully on missing dirs (REJECTED)

Patch the script to return PASS when no schemas found AND no trigger dirs present.

Problem: divergent fork of the script from owning repo. Drift detection (PR #199 D35-style ladder pattern, applicable here too) breaks. Any owning-repo improvement to validate_schemas.py would need re-port + re-merge. Unmaintained.

## Decision

**Option C** — `validate_schemas.py` is out-of-scope for `platform-k8s-gitops`. The script remains in `ci/` (no functional change in this PR), but no CI workflow invokes it.

## Implementation

This PR adds:

1. `decisions/2026-04-28-faz-19-11-d-schemas-validation-scope.md` (this document) recording the decision.
2. `ci/SCOPE.md` (NEW) — single-page reference table mapping each `ci/` script to in-scope-here / owning-repo-only status.

This PR does NOT:
- Add a `gate-validate-schemas.yml` workflow.
- Port any `schemas/` files.
- Modify `ci/validate_schemas.py`.
- Affect runtime behavior of any service.

## Re-evaluation triggers

This decision should be revisited if:
- This repo gains a `schemas/` directory or any trigger artifact family (e.g., a new `roadmaps/` directory for project planning).
- A new ADR proposes gitops-specific schema validation (Option D becomes feasible).
- The owning repo deprecates `validate_schemas.py` and its content moves here.

## D35 ladder declaration

This decision (advances | affects | does NOT touch) the following D35 tier(s):

- [ ] D35-0/1/2/3 — not touched

Faz 19.11.D ci/ port — independent track from D35.

## References

- Codex thread `019dd322` (Faz 19.11.D plan-time PARTIAL — recommended scope decisions per script)
- Codex thread `019dd333` (Session 32 retrospective — verdict A primary, sequence: schemas/ scope first)
- ci/check_test_quality.py (similar precedent: also out-of-scope here per Codex's earlier comment about TS/TSX absence)
- PR #205 PR-A `src/shared/utils.py` shim
- PR #208 PR-B gate-enforcement-check.yml warning-tolerant
