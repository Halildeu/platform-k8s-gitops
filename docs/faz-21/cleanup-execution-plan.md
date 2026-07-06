# Faz 21.1 — Endpoint Cleanup Execution Plan

> **Status**: v2 — 2026-06-04 — Codex 019e8f95 plan-time AGREE (C0) + Codex 019e919e PARTIAL (C1 bounded + FK-web reframe)
> **Authority**: this document for Faz 21.1 cleanup sub-slice sequencing, risk register, observation harness, drop gate.
> **Predecessor**: [Faz 21 Charter](./charter.md) + [ADR-0032 Faz 21 tenant model](../adr/0032-faz-21-tenant-model.md).
>
> **v2 change (2026-06-04 live FK-web discovery)**: C1 implementation gathered live test-cluster schema evidence the C0 plan lacked. The discovery **invalidates the C4 "drop tenant_id from 9 tables" scope** and **reduces C1 to a bounded foundation**. See [§ FK-web discovery](#fk-web-discovery-2026-06-04--reframes-c4) below. C1 landed as platform-backend **PR #443 / V34** (Codex 019e919e AGREE post-impl).

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

## FK-web discovery (2026-06-04) — reframes C4

During C1 implementation, live test-cluster (testai) read-only schema introspection surfaced facts the C0 plan did not have:

1. **Only the 9 org-bearing tables in the ENTIRE `endpoint_admin_service` schema have an `org_id` column.** Every other endpoint table (the device-rooted snapshot tree) is `tenant_id`-only.
2. **`endpoint_devices` has PRIMARY KEY (id)** (id alone unique) + `UNIQUE (id, tenant_id)` + `UNIQUE (tenant_id, hostname)` + `UNIQUE (tenant_id, machine_fingerprint)`. The other 2 cache parents: PK (id) + `UNIQUE (id, tenant_id)`.
3. **`endpoint_devices` is referenced by 14 inbound composite FKs** `(child_col, tenant_id) → endpoint_devices(id, tenant_id)`. ~10 of those children have **no `org_id`**: `endpoint_device_health_snapshots`, `endpoint_diagnostics_snapshots`, `endpoint_hardware_inventory_snapshots`, `endpoint_hotfix_posture_snapshots`, `endpoint_services_snapshots`, `endpoint_startup_exposure_snapshots`, `endpoint_app_control_probe_errors`, etc.
4. **Even inside the 9-table scope, `endpoint_install_audit` FKs to non-org parents**: `(command_id, tenant_id) → endpoint_commands(id, tenant_id)` and `(catalog_item_id, tenant_id) → endpoint_software_catalog_items(id, tenant_id)`. `endpoint_commands` + `endpoint_software_catalog_items` have no `org_id`.

**Consequence — C4 "DROP tenant_id from 9 tables" is infeasible as scoped.** To drop `endpoint_devices.tenant_id` you must drop `UNIQUE (id, tenant_id)` (+ the 2 other tenant_id-based uniques), which requires migrating/dropping all 14 inbound FKs — but ~10 inbound children have no `org_id` and so cannot take a `(child, org_id)` composite FK. The real dependency closure of "drop tenant_id from `endpoint_devices`" is the **entire device-rooted FK tree (~20+ tables, ~30 FK constraints, 3 tenant_id-based unique constraints)**, NOT 9 tables.

**Codex 019e919e on the resolution** (REVISE on the naive fix): blind single-column FK simplification `(child, tenant_id) → parent(id, tenant_id)` ⇒ `(child) → parent(id)` is **not durable** — the composite FK today machine-enforces `child.tenant_id == parent.tenant_id` (a real invariant with deliberate tests, e.g. `EndpointHardwareInventoryPostgresIntegrationTest` cross-tenant rejection). Reducing it to "app-layer org_id" is self-attestation, not machine enforcement. Durable preference order:

1. **Hybrid invariant model**: pure detail child (no own tenant/org discriminator, accessed only via parent join) → single-column FK is acceptable *only if* the child's `tenant_id` non-use is machine-proven; tenant/org-addressable child (own discriminator / unique / audit surface) → scope-expand `org_id` + `(child, org_id) → parent(id, org_id)` composite FK.
2. **Full `org_id` scope expansion** of the device-rooted tree (cleanest, most machine-enforced, larger surface).
3. **Keep `tenant_id` co-resident on hub tables** = honest long-tail compatibility debt; described as "org_id canonical reads/writes live, tenant_id retained for referential compatibility", NOT "cleanup complete".
4. Blind single-column simplification without an added invariant = **RED**.

→ The final FK-web / C4 drop strategy is **REOPENED** (tracked as **F21-R32** below). A dedicated Codex strategy thread must pick (1)/(2)/(3) before C4 is authored. **C1 (V34) commits to none of it.**

## Cleanup work remaining

Per Codex 019e8e29 Q6 + 019e8f95 plan-time consult, cleanup is **NOT** "DROP COLUMN tenant_id" alone. It is a **5-phase sub-slice sequence**. **v2 (2026-06-04)**: C1 reduced to a bounded foundation per Codex 019e919e PARTIAL; C4 scope reopened per the FK-web discovery above.

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

**v2 REDUCED SCOPE — B-only (Codex 019e919e AGREE — LANDED as PR #443 / V34):**
C1 was reduced to a **single purely-additive** change that unblocks C2 and
commits **nothing** about the (now-reopened) FK-web/C4 strategy. C1 = ONLY:

- **FK-target enabler** — `ADD CONSTRAINT UNIQUE (id, org_id)` on the 3
  cache parents (`endpoint_devices`,
  `endpoint_software_inventory_state_history`,
  `endpoint_outdated_software_snapshots`). Additive; coexists with PK(id) +
  UNIQUE(id,tenant_id) + all existing FKs. Enables C2's composite cache FK
  `(child, org_id) → parent(id, org_id)`.

**WHY NOT a non-null CHECK in C1 (CI-driven correction, 2026-06-04):** the
first V34 draft also added `CHECK (org_id IS NOT NULL) VALIDATE` as an
"evidence gate". CI proved that is a **schema contract flip, not an additive
gate** — it makes the legacy `org_id`-NULL row unconstructable and breaks
the entire PR2b-iv `*EffectiveOrgPostgresIntegrationTest` suite (~13 classes
disable the V29 trigger, insert `org_id = NULL`, and assert the effective-org
OR-fallback read still returns the row). The non-null CHECK and the
OR-fallback read removal are **two faces of one invariant flip** and ship
together in a future coupled PR (see below). The testai non-null evidence
(`org_id NULL = 0`, `mismatch = 0` on all 9) is preserved as a **precondition
proof**, NOT a deployed invariant. V34 leaves `org_id` nullable + the
OR-fallback intact. PG IT: 4/4 (`V34OrgIdSourceFoundationPostgresIntegrationTest`,
incl. a guard that a trigger-disabled `org_id = NULL` insert still **succeeds**
— machine-proof V34 did not flip the invariant).

**DEFERRED — the future coupled invariant-flip PR** (one atomic PR, prod-shaped
evidence gated): preflight `org_id NULL = 0` + `tenant_id<>org_id = 0` on 9
tables → `CHECK (org_id IS NOT NULL) NOT VALID + VALIDATE` → repository
effective-org OR-fallback removal → direct `org_id` → legacy-NULL fixtures
retired/replaced with "NULL rejected" tests → rollback/read-contract note.
Also still deferred: source child FK migration to org composite; `tenant_id`
drop / unique swap (C4).

The v1 description below is retained for sequencing context; items (c)/(d)
are deferred per the reduction above.

Phase C1 (v1 description) establishes the source-side org-key foundation:

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

### Phase C2 — Cache Org-Key Flip — SPLIT into C2a + C2b (Codex 019e919e)

> **⚠️ v2 (2026-06-04): C2 was split during implementation.** Two live
> findings forced it:
> 1. The cache FK flip `(child, org_id) → parent(id, org_id)` **depends on
>    the parent source tables having `org_id NOT NULL`**, which C1 (B-only)
>    deliberately deferred. Flipping the 6 cache FKs now would silently
>    re-trigger the parent invariant flip — the FK form of the C1 non-null
>    coupling. → FK flip deferred to **C2b**.
> 2. The v1 plan said "keep both uniques + flip ON CONFLICT". A
>    **deterministic concurrency test failure** proved that breaks: two
>    redundant uniques on the same logical key + a single ON CONFLICT
>    arbiter ⇒ a racing speculative insert trips the non-arbiter unique
>    (unhandled). → C2a does an **atomic unique swap** (drop old, add new).
> Also: the v1 join `c.org_id = d.org_id` is **wrong** for legacy-NULL
> devices (d.org_id NULL via the device OR-fallback) → the correct
> transitional join is `c.org_id = COALESCE(d.org_id, d.tenant_id)`.

#### Phase C2a — cache org-key IDENTITY (LANDED: platform-backend PR #446 / V35)

Cache identity (UNIQUE + UPSERT + read) flips to org-keyed; FKs stay tenant-keyed.

- V35: preflight DO (org_id NULL=0, tenant<>org=0, dup(org,device)=0) →
  cache `CHECK (org_id IS NOT NULL)` NOT VALID + VALIDATE (swdc, osdc) →
  **atomic swap**: `ADD UNIQUE (org_id, device_id)` then `DROP UNIQUE
  (tenant_id, device_id)` (single ON CONFLICT arbiter; add-before-drop).
- `DiffCacheService` UPSERT `ON CONFLICT (tenant_id,device_id)` →
  `(org_id, device_id)` (both).
- cache repos `findByTenantIdAndDeviceId` → `findByOrgIdAndDeviceId`.
- `DeviceGridQueryBuilder` cache JOIN → `c.org_id = COALESCE(d.org_id,
  d.tenant_id) AND c.device_id = d.id` (legacy-NULL devices still attach;
  cross-org isolation preserved).
- PG IT: V35 (CHECK validated, new UNIQUE present, **old UNIQUE absent**,
  6 tenant FKs present, dup(org,device) rejected, trigger-disabled NULL
  rejected) + Concurrency 2/2 + 100 tests green across 10 cache/grid classes.
- **Rollback boundary ≥ V35** (no old-writer-pod overlap — old code's
  ON CONFLICT(tenant_id,device_id) has no matching unique post-swap; F21-R29).
- Keeps tenant_id + the 6 tenant-composite cache FKs.

#### Phase C2b — cache FK org-composite flip (deferred — with the source non-null family)

Recreate the 6 cache FKs as `(child, org_id) → parent(id, org_id)` + drop
old tenant FKs. **Gated on the source parent `org_id NOT NULL` invariant**
(the C1.5 invariant-flip family, #444). Until then the cache FKs stay
`(child, tenant_id) → parent(id, tenant_id)`.

---

**v1 description (superseded — retained for context; the FK recreate +
`c.org_id = d.org_id` join below are NOT what shipped):**

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

> **⚠️ v2 REOPENED (2026-06-04 FK-web discovery):** the scope below ("drop
> tenant_id from 9 tables") is **infeasible as written** — the dependency
> closure of dropping `endpoint_devices.tenant_id` is the whole device-rooted
> FK tree, not 9 tables (see [§ FK-web discovery](#fk-web-discovery-2026-06-04--reframes-c4)
> + **F21-R32**). C4 MUST NOT be authored until a dedicated Codex strategy
> thread selects the FK-web resolution (hybrid-invariant / full-org-expansion /
> co-resident-debt). The text below is the v1 intent, preserved for context;
> the table list and migration body will be reshaped by that decision.

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

### F21-R32 — FK-web closure scope (Active, 2026-06-04)

**Description**: The C0 plan's C4 "drop tenant_id from the 9 org-bearing tables" assumed a bounded FK set. Live testai introspection shows `endpoint_devices` is an FK hub with 14 inbound composite `(child, tenant_id) → (id, tenant_id)` FKs, ~10 from children that have **no `org_id`** (device-rooted snapshot tree), plus in-scope `endpoint_install_audit` FKs to non-org parents (`endpoint_commands`, `endpoint_software_catalog_items`). Dropping `endpoint_devices.tenant_id` therefore requires resolving the whole device-rooted FK tree, not 9 tables. Blind single-column FK simplification would silently drop the machine-enforced `child.tenant_id == parent.tenant_id` invariant (Codex 019e919e REVISE).

**Mitigation**:
- C1 (V34) is bounded to additive non-null evidence + 3 parent `UNIQUE (id, org_id)`; it commits to none of the FK-web strategy.
- C4 is gated (banner above): a dedicated Codex strategy thread MUST select one of {hybrid-invariant model; full `org_id` scope expansion of the device-rooted tree; keep `tenant_id` co-resident as honest compatibility debt} before C4 is authored.
- Any chosen path that retains a tenant↔org match guarantee at the DB layer must keep it **machine-enforced** (composite FK or constraint trigger), not app-layer-only.
- Inventory artifacts to attach to the C4 strategy thread: `pg_constraint` inbound-FK dump for `endpoint_devices`; `pg_attribute` org_id-bearing table list; explicit evidence that `endpoint_commands`/`endpoint_software_catalog_items` lack `org_id`.

### Link to global R10

R10 (multi-tenant migration data drift / cross-tenant leak) covers the Faz 21 broader scope. F21-R29/R30/R31/R32 are sub-risks under R10 mitigation; cross-reference in `docs/notify/risk-register.md` once Faz 21 risk register entries land.

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
