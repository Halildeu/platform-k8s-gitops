# `ci/` — In-Scope / Owning-Repo-Only Reference

This table maps each `ci/` script to its scope in `platform-k8s-gitops`. Faz
19.11.D ported scripts from the owning repo (platform-ssot or similar);
not all of them are meaningful here. This file is the canonical reference.

When adding a new `ci/` workflow, update this table.

## Scripts

| Script | Scope here | CI workflow | Notes |
|---|---|---|---|
| `check_enforcement_rules.py` | ✅ in-scope | `gate-enforcement-check.yml` (live since PR #208) | 14 EP rules, warning-tolerant, errors-only fail. |
| `check_test_quality.py` | ❌ owning-repo-only | (none) | Scans TS/TSX; this repo has no frontend. Per Codex `019dd322`. |
| `check_module_delivery_lanes.py` | ⏸ deferred | (pending) | Requires `module-delivery-lanes.yml` workflow + `module_delivery_lanes.v1.json` config baseline-correct for this repo. |
| `check_script_budget.py` | ⏸ deferred | (pending) | Requires `script_budget.v1.json` config baseline correction (current config has dev-repo paths like `web/**`, `backend/**`). |
| `check_standards_lock.py` | ⏸ deferred | (pending) | Requires `standards.lock` revision (current expects 50+ files not present in this repo). |
| `validate_schemas.py` | ❌ owning-repo-only | (none) | Per `decisions/2026-04-28-faz-19-11-d-schemas-validation-scope.md` — zero trigger dirs in this repo. |
| `policy_dry_run.py` | ⏸ deferred | (pending) | Requires `managed-repo` variant decision (current run produces 20/20 invalid). |
| `run_module_delivery_lane.py` | (CLI runner) | (none) | Per-lane runner; consumed by `gate-module-delivery-*` workflows when ported. |
| `_summarize_enforcement_report.py` | ✅ in-scope (helper) | (called by `gate-enforcement-check.yml`) | Helper for summary step output formatting. |

## Status legend

- ✅ **in-scope**: actively running as a CI gate or used by a gate.
- ❌ **owning-repo-only**: ported to this repo for reference / consistency, but no workflow uses it; the meaningful execution context is the owning repo.
- ⏸ **deferred**: in-scope here in principle, but blocked on prereq drift (config baseline, missing workflow file, missing trigger artifact, etc.) — see specific notes.

## Drift policy

- When the owning repo updates a `ci/` script, port the change to this repo to maintain parity.
- When this repo gains a relevant trigger dir/file (e.g., `schemas/`, `roadmaps/`), revisit the corresponding script's scope (out-of-scope → potentially in-scope).
- New scripts added to this repo's `ci/` should declare scope here in the same PR.

## References

- Codex thread `019dd322` (Faz 19.11.D plan-time PARTIAL with per-script scope verdicts)
- Codex thread `019dd333` (Session 32 retrospective — verdict A primary)
- `decisions/2026-04-28-faz-19-11-d-schemas-validation-scope.md` (validate_schemas decision)
- PR #205 PR-A (src/shared/utils.py shim)
- PR #208 PR-B (gate-enforcement-check live)
