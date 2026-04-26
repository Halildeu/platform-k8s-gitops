# OpenFGA Authorization Model — Upstream Reference

> **Status**: Faz 19.11 residual (placeholder).
> The actual `.fga` source-of-truth file lives in **platform-ssot** until
> Faz 19.10 hard archive completes. This file documents the location and
> the migration plan.

## Current authoritative location

- Repo: `platform-ssot` (`Halildeu/platform-ssot`, currently active —
  hard archive deferred until Faz 19.11 4-dalga complete).
- Path: `docs/platform-ssot/openfga-authorization-model.fga`
- Referenced by `bootstrap/local-fixtures/openfga/tuples.json#model`.

## Why not in this repo (yet)

Per Faz 19 split-repo authority transfer:
- platform-k8s-gitops owns: deployment manifests (StatefulSet,
  ConfigMap, ESO, migrate-job), runbooks, ADRs, dev fixtures.
- platform-ssot owns: source-of-truth model files until OpenFGA model
  ownership is explicitly migrated.

Faz 19.11 (residual asset migration before hard archive) is in
progress; the model `.fga` file is part of the residual set that
hasn't been migrated yet because it's actively being modified for
Faz 21.3 (multi-org + depot types per ADR-0008).

## Migration plan

When Faz 21.3 backend repo PR merges (organization + depot types
added):

1. Copy the final `openfga-authorization-model.fga` into
   `bootstrap/local-fixtures/openfga/model.fga` in this repo.
2. Update `tuples.json#model` from
   `docs/platform-ssot/openfga-authorization-model.fga` →
   `bootstrap/local-fixtures/openfga/model.fga`.
3. Update `dev-seed.sh` to load model from local path.
4. Add a CI check that diffs the local copy against the deployed
   `model_id` content (rendered from OpenFGA store).
5. Once stable, delete the upstream copy in platform-ssot
   (post-hard-archive consideration).

This file removes once steps 1-4 land.

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
