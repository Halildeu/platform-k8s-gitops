# Faz 21.1 — Endpoint Cleanup Execution Plan

> **Status**: Draft v1 — 2026-06-04 — Codex 019e8f95 plan-time AGREE
> **Authority**: this document for Faz 21.1 cleanup sub-slice sequencing, risk register, observation harness, drop gate.
> **Predecessor**: [Faz 21 Charter](./charter.md) + [ADR-0032 Faz 21 tenant model](../adr/0032-faz-21-tenant-model.md).

## Context

Faz 21.1 endpoint org_id canonicalize source-side work closed 2026-06-03:

| Phase | PRs MERGED | Codex thread |
|---|---|---|
| PR1 endpoint org_id ADD COLUMN + backfill + dual-read | (pre-session) | 019e8c95 |
| PR2 code-side dual-read COALESCE + canonical write + V30 CHECK | (pre-session) | (pre-session) |
| PR2b-ii canonical org_id write at service/mapper layer | (pre-session) | (pre-session) |
| PR2b-iii BE-024c repository COALESCE | (pre-session) | 019e8cd4 |
| PR2b-iv.a Compliance Evaluation | #396 | 019e8bf3 |
| PR2b-iv.b1-b4 EndpointDevice (4 PRs) | #397, #398, #400, #401 | (multiple) |
| PR2b-iv.c SoftwareInventoryStateHistory | #414 | 019e8d1d → 019e8dbb |
| PR2b-iv.d-A Outdated per-device | #416 | 019e8dc7 → 019e8dd6 |
| PR2b-iv.d-B Outdated JPQL pair | #417 | 019e8dc7 → 019e8dd6 |
| PR2b-iv.e-A InstallAudit admin visibility | #422 | 019e8dde |
| PR2b-iv.e-B InstallAudit compliance selector + AG-028 | #438 | 019e8dde |
| PR2b-iv.f AppControl | #420 | 019e8dec |
| PR2c V33 endpoint diff cache org_id canonicalize | #439 | 019e8e29 |
| PR2b-iv AppControl native insert canonical write | #440 | 019e8dec follow-up |

Source-side read migration arc (10 sub-slices: a, b1-b4, c, d-A, d-B, e-A, e-B, f) + cache canonicalize + AppControl write-side gap all closed. State at 2026-06-03 23:00 UTC:

- 9 endpoint tables carry both `tenant_id` (legacy, NOT NULL) and `org_id` (nullable, V29/V33 backfilled).
- 7 source tables: V29 trigger + V30 CHECK.
- 2 cache tables: V33 trigger + V33 CHECK.
- Code paths: canonical `org_id = tenant_id` write at INSERT; dual-read `effective-org filter` via P1 parenthesized OR.
- 10 PG IT regression guards covering effective-org + legacy NULL + cross-org + canonical write + V30 CHECK behavior.

## Cleanup work remaining

Per Codex 019e8e29 Q6 + 019e8f95 plan-time consult, cleanup is **NOT** "DROP COLUMN tenant_id" alone. It is a **5-phase sub-slice sequence**:

### Phase C0 — Gate PR (THIS PR, doc + harness + risk, no DB change)

This Cleanup Execution Plan document.
- Risk register entries: F21-R29 Active, F21-R30 Active, F21-R31 Active.
- Faz 21.1-specific observation harness: SQL evidence script (`scripts/faz-21/endpoint-org-cleanup-evidence.sh`) + (deferred) Prometheus recording rule + alert.
- Board issue claim template + acceptance checklist.
- **No DB change. No code change in endpoint-admin.**

### Phase C1 — Source Org-Key Foundation (parent-before-child) (one PR)

**CRITICAL ORDERING CORRECTION (Codex 019e8f95 iter-2):** the original
draft put Cache Org-Key Flip first, but cache FKs reference parent
tables via composite `(child_col, tenant_id) → parent (id, tenant_id)`.
A composite FK `(child_col, org_id) → parent (id, org_id)` **requires a
UNIQUE/PK constraint on `parent (id, org_id)`** which does not exist
yet. Therefore the **parent (source) org-key foundation MUST land
before** the cache FK flip. Dependency graph: **parent UNIQUE → source
FK/read → cache FK/read/write → observation → drop.**

Phase C1 establishes the source-side org-key foundation:

- **Non-null evidence gate (PRE-requisite):** V30 CHECK
  `(org_id IS NULL OR org_id = tenant_id)` does NOT prove `org_id IS NOT
  NULL` — `org_id IS NULL` still passes. Before any direct-read fallback
  removal, prove for all cleanup-scope source rows:
  - `org_id IS NOT NULL`
  - `tenant_id != org_id` count = 0
  - FK anti-join orphan count = 0 for proposed `(…, org_id)` joins
  Use DB `CHECK (org_id IS NOT NULL) NOT VALID` + `VALIDATE CONSTRAINT`
  pattern; final `SET NOT NULL` deferred to C4.
- V34 migration: `ADD CONSTRAINT ... UNIQUE (id, org_id)` on every
  source table that will be referenced by an org-key FK. Minimum for
  cache dependency: `endpoint_devices`,
  `endpoint_software_inventory_state_history`,
  `endpoint_outdated_software_snapshots`. (Other source tables that are
  not cache parents may defer their UNIQUE to C-source-FK if they have
  no org-key FK consumer.)
- Migrate source child FKs from `tenant_id` composite to `org_id`
  composite where parent UNIQUE now exists.
- Switch source repository/query paths from effective-org OR-fallback
  to direct `org_id` (only after validated non-null evidence).
- **No cache FK flip yet. No DROP tenant_id.**

### Phase C2 — Cache Org-Key Flip (one PR)

**Requires C1 parent `UNIQUE (id, org_id)` on the 3 cache parents.**
Cache UNIQUE + FK + UPSERT conflict target + repository + grid join all
migrated atomically (single deploy boundary). 2 tables (V27 lineage),
~4 service callsites:

- V35 migration: recreate cache FKs using `(device_id, org_id) →
  endpoint_devices (id, org_id)`, `(from_history_id, org_id)`,
  `(to_history_id, org_id)` (software) / snapshot equivalents (outdated)
  — now that parent `(id, org_id)` UNIQUE exists.
- `ADD CONSTRAINT ... UNIQUE (org_id, device_id)` on both cache tables.
- `DiffCacheService.upsertSoftwareDiffCache` + `upsertOutdatedDiffCache`
  UPSERT `ON CONFLICT (tenant_id, device_id)` → `ON CONFLICT (org_id,
  device_id)`.
- `EndpointSoftwareDiffCacheRepository.findByTenantIdAndDeviceId` →
  `findByOrgIdAndDeviceId` (rename).
- `EndpointOutdatedSoftwareDiffCacheRepository.findByTenantIdAndDeviceId`
  → `findByOrgIdAndDeviceId`.
- `DeviceGridQueryBuilder` cache JOIN `c.tenant_id = d.tenant_id` →
  `c.org_id = d.org_id`.
- PG IT: V35 regression guard (mirror V33 pattern + duplicate
  `(org_id, device_id)` preflight test + FK anti-join orphan fail-loud).
- **No DROP tenant_id.**

**Split decision**: Codex 019e8f95 acceptable C1 as 1 PR (matches
V29/V30 precedent). Alternative C1 split `devices+inventory+outdated` +
`install+compliance+appcontrol` if review surface too large.

### Phase C3 — 30-day reverify (operator-bound, evidence-only, no PR)

Endpoint-specific mismatch=0 invariant evidence on testai + prod-shaped staging:

- `endpoint_org_id_mismatch_rows{table=...}` = 0 for 30 days
- `endpoint_org_id_duplicate_org_device_rows{table=...}` = 0 for 30 days
- `endpoint_org_id_fk_mismatch_rows{table=...}` = 0 for 30 days
- Manual evidence (Codex 019e8f95 scope-narrowing): **no `tenant_id`
  callsite remains for cleanup-scope tables / diff-cache / device-grid
  source paths**. Do NOT target zero `tenant_id` across all of
  endpoint-admin-service — command/catalog/uninstall surfaces are
  out-of-scope tenant_id consumers and would inflate scope beyond the
  9 endpoint tables.
- Operator-bound prerequisites: R10 prod-shaped staging +
  Inv-explicit-column-list-guard audit (renamed from "Inv-4" to avoid
  charter concept drift — Inv-4 is the AI boundary invariant, NOT the
  `SELECT *` guard).

### Phase C4 — Final Drop Sweep (one PR, single Flyway migration)

V36 migration: precondition DO block (verify mismatch=0 + no duplicates + FK parents clean) + `org_id SET NOT NULL` on all 9 tables (deferred from C1) + drop `tenant_id` from 9 tables + drop V29 trigger + V30 CHECK + V33 trigger + V33 CHECK + old tenant_id indexes + V29 function `endpoint_org_id_compat_fill()` + old tenant_id UNIQUE/FK constraints.

- Migration version is the next free slot at C4 implementation time (V36 placeholder; reconcile against parallel AG-028 migration track which has claimed V31/V32 — check `ls db/migration` before authoring).
- Single Flyway migration covering all 9 tables (per-table split adds blast-radius rather than reduces).
- Precondition DO block: `RAISE EXCEPTION 'cleanup precondition failed'` on mismatch > 0 OR duplicate `(org_id, device_id)` > 0 OR FK orphans > 0 across the 9 tables.
- Entity field removal (`tenantId` getter/setter from 9 entity classes).
- **Adversarial review zorunlu** — Codex separate thread before this PR opens (live digest/pod proof, 30-day evidence, explicit column guard, no old tenant_id callsite, snapshot rehearsal, rollback wording).

## Risk register additions

Adding to charter §1.1 and ADR-0032 §3.x:

### F21-R29 — Cleanup window risk (Active)

**Description**: Rolling deploy where one pod has new code (org_id-only) and another has old code (tenant_id COALESCE) hits column-not-found error post-drop.

**Mitigation**:
- C1 + C2 do NOT drop `tenant_id`; only flip code/constraint authority to `org_id`.
- C4 final drop only after C3 30-day reverify + canonical proof that no in-flight rolling deploy has a tenant_id-only writer.
- Flyway forward-only; app-side rollback boundary is "revert deploy + V36 not applied". Once V36 lands, the rollback target must be V36+ digest.

### F21-R30 — Column-drop blast radius (Active)

**Description**: V36 single Flyway migration touches 9 tables atomically; a partial drop state is not a supported app state.

**Mitigation**:
- V36 includes precondition DO block: `RAISE EXCEPTION 'cleanup precondition failed'` on mismatch > 0 OR duplicate `(org_id, device_id)` > 0 OR FK orphans > 0 across the 9 tables.
- Snapshot rehearsal: V36 dry-run on prod-shaped staging snapshot before testai deploy.
- Rollback boundary: V36 cannot be reverted in-place; rollback target is V35-or-prior digest.

### F21-R31 — Parent-before-child org FK dependency (Active)

**Description** (Codex 019e8f95 iter-2 reframe): cache FKs reference
parent tables via composite `(child_col, tenant_id) → parent (id,
tenant_id)`. Migrating cache FKs to `(child_col, org_id)` REQUIRES
parent `(id, org_id)` UNIQUE to exist first. The original "cache first"
plan would fail at cache FK DDL creation. Beyond ordering, cache UNIQUE
+ UPSERT conflict target must also flip atomically (same C2 PR);
independent flips leave the cache in a non-functional state.

**Mitigation**:
- **Phase ordering is the primary mitigation**: C1 (source org-key
  foundation: parent UNIQUE + source FK + direct read) lands BEFORE
  C2 (cache org-key flip). C2 cannot start unless C1 evidence proves
  `UNIQUE (id, org_id)` exists on the 3 cache parents (devices,
  sw_inv_state_history, outdated_snapshots).
- C2 is the cache atomic boundary: V35 migration + DiffCacheService
  UPSERT update + repository method rename + grid JOIN update all in
  single PR.
- C2 migration must fail-loud if any cache row cannot anti-join to
  parent by `(id, org_id)`.
- Duplicate `(org_id, device_id)` preflight test: PG IT seeds duplicate
  canonical rows pre-V35 and asserts V35 either rejects (constraint
  violation) or de-dups via UPSERT (canonical winner).
- C4 cannot start unless no old tenant-FK / tenant-UPSERT / tenant-grid
  join remains in cleanup-scope.

### Link to global R10

R10 (multi-tenant migration data drift / cross-tenant leak) covers the Faz 21 broader scope. F21-R29/R30/R31 are sub-risks under R10 mitigation; cross-reference in `docs/notify/risk-register.md` once Faz 21 risk register entries land.

## Observation harness

### SQL evidence script (`scripts/faz-21/endpoint-org-cleanup-evidence.sh`, deferred to separate PR or M7-extension)

Read-only SQL queries against each of the 9 endpoint tables:

```sql
-- mismatch=0 invariant
SELECT COUNT(*) AS mismatch_rows
FROM <table>
WHERE tenant_id IS NOT NULL AND org_id IS NOT NULL AND tenant_id != org_id;

-- duplicate (org_id, device_id) for cache tables
SELECT COUNT(*) AS duplicate_rows
FROM (
    SELECT org_id, device_id, COUNT(*) AS rownum
    FROM <cache_table>
    WHERE org_id IS NOT NULL
    GROUP BY org_id, device_id
    HAVING COUNT(*) > 1
) duplicates;

-- FK orphan check for source tables with (device_id, tenant_id) FK
SELECT COUNT(*) AS fk_orphan_rows
FROM <source_table> s
LEFT JOIN endpoint_devices d ON d.id = s.device_id AND d.tenant_id = s.tenant_id
WHERE d.id IS NULL;
```

### (Deferred) Prometheus recording rules

If a Prometheus-DB exporter is added in a future operator harness:

```yaml
- record: endpoint_org_id_mismatch_rows
  expr: |
    sum by (table) (
      label_replace(
        pg_query{query=~"faz21-mismatch-..."},
        "table", "$1", "query", "faz21-mismatch-(.+)"
      )
    )

- alert: Faz21EndpointOrgIdMismatchPresent
  expr: max_over_time(endpoint_org_id_mismatch_rows[30d]) > 0
  for: 1h
  labels:
    severity: warning
    faz: 21.1
  annotations:
    description: "endpoint cleanup invariant violated: {{ $labels.table }} has mismatch rows"
```

C3 acceptance: `max_over_time(...[30d]) == 0` + coverage guard (recording rule must have produced data continuously for 30 days; gaps disqualify).

### Inv-4 (explicit column list guard)

Codex 019e8f95 noted: Inv-4 in this charter is AI boundary (not `SELECT *` guard). To avoid drift, the `SELECT *` audit is renamed:

- **Inv-4** = AI boundary invariant (charter §X.X)
- **Inv-explicit-column-list-guard** = audit no `SELECT *` patterns remain in endpoint-admin-service code paths before C4 final drop.

`scripts/faz-21/endpoint-explicit-column-list-audit.sh` (deferred to C0 follow-up or C2 prerequisite): `grep -rn 'SELECT \*' endpoint-admin-service/src/main` + manual review of dynamic SQL builders.

## Rollout pattern

Per Codex 019e8f95 Option A + C hybrid:

| Phase | DB state | Code state | App write | App read |
|---|---|---|---|---|
| Pre-C1 | `tenant_id NOT NULL`, `org_id` nullable | dual-read COALESCE | both columns | effective-org (P1) |
| Post-C1 (source foundation) | source: `UNIQUE (id, org_id)` + FK `(id, org_id)`; `org_id NOT NULL` VALIDATE | source: org-key direct | both columns | source org-key direct, cache effective-org |
| Post-C2 (cache flip) | cache: UNIQUE `(org_id, device_id)` + FK `(id, org_id)` | cache: org-key direct | both columns | all org-key direct |
| C3 evidence | (no DB change) | (no code change) | both columns | all org-key direct |
| Post-C4 | `org_id SET NOT NULL`; `tenant_id` dropped from 9 tables; trigger + CHECK + indexes cleaned | tenant_id removed from entities | org_id only | org_id only |

No outage window required. Rollback boundary moves with each phase: rollback target must always be ≥ same-phase digest.

## Board issue + claim

Board issue template (separate PR or attach to C0 commit):

```
Title: Faz 21.1 Cleanup Phase Cx — <description>
Labels: faz-21, cleanup, claim-required
Body:
- Scope: <specific tables / files>
- Prerequisites: <e.g., C0 merged, C1 prerequisites, C3 evidence>
- Acceptance:
  - [ ] PR opened with cross-AI Codex review
  - [ ] Verdict AGREE ready_for_merge:true
  - [ ] CI 13/13 GREEN
  - [ ] Charter §1.1 evidence updated
- Risk IDs: F21-R29 / F21-R30 / F21-R31 / R10 mitigation sub-risk
- Estimated effort: <hours>
```

Per HARD RULE board-protocol.md: claim-before-work. Trivial fix exception does NOT apply (cleanup work is multi-step + tenant-touching).

## Open items

- Board issue creation: not started (this PR is doc-only).
- SQL evidence script implementation: deferred to C0 follow-up or C1 prerequisite.
- Explicit column list audit script: deferred similarly.
- Final drop adversarial review (C4 separate Codex thread): not started.

## References

- Codex 019e8e29 PR2c iter-2 Q6 (initial cleanup sequencing seed)
- Codex 019e8f95 cleanup plan-time consult (this document derivation)
- [Faz 21 Charter §1.1](./charter.md)
- [ADR-0032 Faz 21 tenant model](../adr/0032-faz-21-tenant-model.md)
- [V29 add_org_id_compat_layer](../../platform-backend/endpoint-admin-service/src/main/resources/db/migration/V29__add_org_id_compat_layer.sql) (source-side pattern reference)
- [V30 org_id_check_constraint](../../platform-backend/endpoint-admin-service/src/main/resources/db/migration/V30__org_id_check_constraint.sql)
- [V33 endpoint_diff_cache_org_id_compat](../../platform-backend/endpoint-admin-service/src/main/resources/db/migration/V33__endpoint_diff_cache_org_id_compat.sql)
- M7 30-day stable observation harness (notify side; precedent for harness pattern, not endpoint scope)
