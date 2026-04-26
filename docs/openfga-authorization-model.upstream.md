# OpenFGA Authorization Model — Migration Status

> **Status**: Faz 19.11 residual STEP 1+2+3+4 COMPLETE (2026-04-26).
> Model migrated, dev-seed.sh writes it to local OpenFGA store, and a
> CI drift gate compares against upstream platform-backend on every
> change. Step 5 (upstream prune) remains as low-priority cleanup.

## Current location (this repo)

- Path: **`bootstrap/local-fixtures/openfga/model.fga`** (61 lines)
- Source: snapshotted from
  `Halildeu/platform-backend:backend/openfga/model.fga` on 2026-04-26 via
  read-only fetch (post Faz 21.3 explicit-scope semantic update — backend
  PR #11). The local copy is the authoritative dev/local model.
- Helper: **`bootstrap/local-fixtures/openfga/render_model_json.py`** —
  custom DSL→JSON renderer (skips `#` comments + `or` / `but not`
  precedence). Used by `dev-seed.sh` to render before POST to OpenFGA.
- `bootstrap/local-fixtures/openfga/tuples.json#model` path points to
  this local file. With Step 3 in place `dev-seed.sh` writes the model
  to OpenFGA store **before** writing tuples (model_id captured + passed
  explicitly to `/write`).

## Faz 21.3 backend PR — DONE

The local model mirrors **post-Faz-21.3** upstream
(`Halildeu/platform-backend:backend/openfga/model.fga` PR #11 merged
2026-04-26):
- Auto-grant relations REMOVED per ADR-0008 (`admin from org`,
  `viewer: ... or member`, etc.).
- `parent_warehouse: [warehouse]` ADDED for hierarchy navigation; no
  transitive viewer grant (ADR-0008 alt C reddedildi).
- Types unchanged otherwise: `user`, `organization`, `company`,
  `project`, `warehouse`, `branch`, `module`, `action`, `report`.
- Vault `kv/platform/openfga model_id` rotate is a staging/prod cluster
  rollout step (`docs/openfga-multi-org-rollout.md` Step 3) — NOT
  exercised by `dev-seed.sh` (k3d-dev local store; ephemeral model_id
  per cluster boot).

## Naming reminder (PG ↔ OpenFGA)

PG `data_access.scope.scope_kind = 'depot'` (V19+V20 immutable migrations)
maps to OpenFGA object type `warehouse`. See ADR-0008 § Naming.

## Migration plan — remaining steps

- [x] Step 1: Copy `model.fga` to `bootstrap/local-fixtures/openfga/`.
- [x] Step 2: Update `tuples.json#model` to local path.
- [x] Step 3: Update `scripts/dev-seed.sh` to read model from local path
      and write to OpenFGA store on local cluster boot. **DONE
      2026-04-26.** Order: discover/create store → render `model.fga`
      via `render_model_json.py` → POST `/stores/{id}/authorization-models`
      → capture model_id → POST `/stores/{id}/write` with
      `authorization_model_id` explicit. Verified end-to-end against
      `openfga/openfga:latest` Docker container: 8/8 fixture smoke
      checks pass (5 allow + 3 deny — D29 Zanzibar-ready third level).
- [x] Step 4: CI drift gate. **DONE 2026-04-26.** Implemented as
      `.github/workflows/openfga-model-drift.yml`: on every PR or push
      that touches `model.fga` or `render_model_json.py`, plus weekly
      Mondays 03:00 UTC, the workflow fetches
      `Halildeu/platform-backend:main:backend/openfga/model.fga`,
      renders both files to JSON via `render_model_json.py`, and
      semantic-compares the dicts. Drift fails the workflow with a
      structured diff (LOCAL ONLY / UPSTREAM ONLY / shared-drifted
      types). NOTE: this Step 4 variant catches **upstream-source**
      drift (catches divergence early, before rotation). The original
      Step 4 description (diff against deployed `model_id` on prod
      cluster via Vault `kv/platform/openfga`) remains a future
      strengthening once Vault read in CI is wired (separate PR).
- [ ] Step 5: Once stable and the deployed-model drift gate above is
      added, delete the upstream copy in platform-backend (post Faz
      21.3 backend PR #11 propagation). Low priority — keeping a
      single source-of-truth in platform-backend with a periodic
      drift-checker here is acceptable steady-state.

## Why this doc is committed

- Codex 019dc8b4 iter-1 flagged the absent file as Faz 19.11 residual.
- ADR-0008 references the model; this doc tracks migration state across
  the 5-step plan.
- Faz 21.3 rollout runbook (`docs/openfga-multi-org-rollout.md`) Step 2
  expects the model file to be writable to OpenFGA store on staging/
  prod; that path is parallel to the k3d-dev path now exercised by
  `dev-seed.sh` (Step 3 done).

## Cross-refs

- `docs/adr/0008-multi-org-explicit-scope-zanzibar.md`
- `docs/openfga-multi-org-rollout.md`
- `bootstrap/local-fixtures/openfga/tuples.json`
- `decisions/topics/zanzibar-openfga.v1.json`
- `PLAN.md` Faz 19.11
