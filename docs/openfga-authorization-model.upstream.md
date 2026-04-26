# OpenFGA Authorization Model — Migration Status

> **Status**: Faz 19.11 residual STEP 1+2 COMPLETE (2026-04-26).
> Model file migrated from upstream platform-ssot to this repo.
> Steps 3-5 still pending (dev-seed.sh reload + CI diff + upstream prune).

## Current location (this repo, authoritative for dev/local)

- Path: **`bootstrap/local-fixtures/openfga/model.fga`** (59 lines)
- Source: snapshotted from
  `Halildeu/platform-ssot:backend/openfga/model.fga` on 2026-04-26 via
  `gh api` read-only fetch.
- Referenced by `bootstrap/local-fixtures/openfga/tuples.json#model`
  → updated to local path in this PR.

## Faz 21.3 backend PR will modify this file

The model in this repo currently mirrors platform-ssot upstream:
- Has type `organization`, `company`, `project`, `warehouse`, `branch`
  + module/action/report.
- Has **auto-grant relations** (`admin from org`, `viewer: ... or member`)
  that contradict ADR-0008 explicit-scope contract.

Faz 21.3 backend repo PR (platform-backend, not k8s-gitops) will:
1. Remove auto-grant relations per ADR-0008.
2. Add `parent_warehouse` for hierarchy navigation (no transitive
   viewer grant).
3. Write the new model to OpenFGA store; capture new `model_id`.
4. Vault `kv/platform/openfga model_id` rotate per
   `docs/openfga-multi-org-rollout.md`.

## Naming reminder (PG ↔ OpenFGA)

PG `data_access.scope.scope_kind = 'depot'` (V19+V20 immutable migrations)
maps to OpenFGA object type `warehouse`. See ADR-0008 § Naming.

## Migration plan — remaining steps

- [x] Step 1: Copy `model.fga` to `bootstrap/local-fixtures/openfga/`.
- [x] Step 2: Update `tuples.json#model` to local path.
- [ ] Step 3: Update `scripts/dev-seed.sh` to read model from local path
      and write to OpenFGA store on local cluster boot. (Separate PR.)
- [ ] Step 4: CI gate — diff local model file against deployed model_id
      content rendered from OpenFGA store on the prod cluster. (Separate
      PR; needs read access to `kv/platform/openfga`.)
- [ ] Step 5: Once stable, delete the upstream copy in platform-ssot
      (post-hard-archive consideration).

## Why this placeholder is committed

- Codex 019dc8b4 iter-1 flagged the absent file as Faz 19.11 residual.
- ADR-0008 references the model; this stub gives next-agent context
  about why it's not yet here.
- Faz 21.3 rollout runbook (`docs/openfga-multi-org-rollout.md`) Step 2
  expects the model file to be writable to OpenFGA store; operator
  pulls from platform-ssot until migration completes.

## Cross-refs

- `docs/adr/0008-multi-org-explicit-scope-zanzibar.md`
- `docs/openfga-multi-org-rollout.md`
- `bootstrap/local-fixtures/openfga/tuples.json`
- `decisions/topics/zanzibar-openfga.v1.json`
- `PLAN.md` Faz 19.11
