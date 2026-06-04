# Faz 21.1 Cleanup C4 — A1 FK-Graph Manifest (authoring gate)

> **Status**: A1 deliverable. This is the **decision artifact** that gates C4 authoring
> (supersedes the "9-table drop scope" the [cleanup-execution-plan.md](./cleanup-execution-plan.md)
> v2 banner / F21-R32 flagged as un-writable). Cross-AI: Claude discovery + Codex `019e93a1`
> REVISE→refinement (plan thread `019e926f` phased-A AGREE).
>
> **Live discovery source**: testai `platform-pg-test` `endpoint_admin` DB, `endpoint_admin_service`
> schema — `pg_constraint` (35 tenant-composite FKs) + `information_schema.columns` (org_id/tenant_id
> per table), read-only, 2026-06-04 (immediately after C1.5/V36 + C2b/V37 LIVE).

## 0. Top-level decision

**Full org expansion is SELECTED** (phased-A). `tenant_id` is to be dropped component-wise from
the device-rooted tree + the 2 hubs (`endpoint_commands`, `endpoint_software_catalog_items`).
**Single-column FK simplification is RED** (rejected) unless a per-table proof exists that the table
is detail-only, carries no tenant/org-addressable query/index/audit surface, and is reachable
parent-join-only. "Leave it tenant-only" = **co-resident compatibility debt** and is NOT phased-A
complete (Codex `019e93a1`).

## 1. Per-table org_state (45 tenant-bearing tables in scope)

| org_state | tables |
|---|---|
| **ORG-DONE** (9) | `endpoint_devices`, `endpoint_install_audit`, `endpoint_compliance_evaluations`, `endpoint_app_control_snapshots`, `endpoint_outdated_software_snapshots`, `endpoint_outdated_software_packages`, `endpoint_software_inventory_state_history`, `endpoint_software_diff_cache`, `endpoint_outdated_software_diff_cache` |
| **EXPANSION-REQUIRED** (36) | all tenant-only tables below |

The 36 expansion-required tables, grouped by **family** (A2 slice unit):

| Family | Tables (root → detail) | Notes |
|---|---|---|
| device_health | `endpoint_device_health_snapshots` → `endpoint_device_health_disks` | **A2 pilot (slice-1)** |
| diagnostics | `endpoint_diagnostics_snapshots` → `endpoint_diagnostics_probe_errors` | |
| hardware_inventory | `endpoint_hardware_inventory_snapshots` → `…_disks`, `…_network_interfaces` | 2 detail |
| hotfix_posture | `endpoint_hotfix_posture_snapshots` → `…_installed`, `…_pending` (→ `…_pending_kbs`), `…_pending_categories` | deepest tree |
| services | `endpoint_services_snapshots` → `…_entries`, `…_probe_errors` | |
| startup_exposure | `endpoint_startup_exposure_snapshots` → `…_apps`, `…_probe_errors` | |
| app_control (detail only) | `endpoint_app_control_probe_errors` | **NOT orphan** — detail child of ORG-DONE `endpoint_app_control_snapshots`; needs parent `UNIQUE(id, org_id)` (A3) before flip |
| software_inventory | `endpoint_software_inventory_items`, `endpoint_software_inventory_snapshots` | device-child |
| compliance read-model | `endpoint_device_compliance_states` | carries `latest_evaluation_id` single FK → `compliance_evaluations` (ORG-DONE); flip that FK too |
| standalone operational | `endpoint_enrollments`, `endpoint_heartbeats`, `endpoint_machine_certs`, `endpoint_maintenance_tokens`, `endpoint_prohibited_software_rules`, `endpoint_audit_events` | "stay-tenant?" → **NO** if tenant-scoped query/index/audit surface exists (default: expand; co-resident debt rejected) |
| **HUB commands** | `endpoint_commands` → `endpoint_command_results`, `endpoint_command_approvals` | expand parent first |
| **HUB catalog** | `endpoint_software_catalog_items` → `endpoint_software_compliance_policy_items`, `catalog_uninstall_settings_change_requests` | expand parent first |
| uninstall | `endpoint_uninstall_requests` → `endpoint_uninstall_audit` | depends on device + commands + catalog all org-ready |

## 2. FK graph (35 tenant-composite FKs, 3 hub roots)

```
HUB endpoint_devices (12 inbound):
  app_control_snapshots* · device_health_snapshots · diagnostics_snapshots ·
  hardware_inventory_snapshots · hotfix_posture_snapshots · install_audit* ·
  outdated_software_snapshots* · services_snapshots · software_inventory_state_history* ·
  startup_exposure_snapshots · uninstall_audit · uninstall_requests
HUB endpoint_commands (3 inbound):  install_audit* · uninstall_audit · uninstall_requests
HUB endpoint_software_catalog_items (5 inbound):
  catalog_uninstall_settings_change_requests · install_audit* ·
  software_compliance_policy_items · uninstall_audit · uninstall_requests
Snapshot→detail subtrees:
  app_control_snapshots*→probe_errors · device_health_snapshots→disks ·
  diagnostics_snapshots→probe_errors · hardware_inventory_snapshots→{disks,network_interfaces} ·
  hotfix_posture_snapshots→{installed,pending(→pending_kbs),pending_categories} ·
  outdated_software_snapshots*→packages* · services_snapshots→{entries,probe_errors} ·
  startup_exposure_snapshots→{apps,probe_errors} · uninstall_requests→uninstall_audit
  (* = parent already ORG-DONE; its inbound FK still tenant-composite until BOTH ends org)
```

Per-FK target (A4): `(child_col, tenant_id) → parent(id, tenant_id)` ⇒ `(child_col, org_id) → parent(id, org_id) <ON DELETE ...>` (preserve the existing delete rule + **DEFERRABLE** where set — see §4). Add-NOT VALID + VALIDATE + drop-old atomic swap (the V37 pattern).

## 3. Slicing + ordering (Codex `019e93a1`)

**Model**: family-vertical for leaves, staged-parent-first for hubs. Do NOT do a global "all 36 A2-expand, then all A4-flip" — long-lived dual-column drift + trigger surface + review debt.

1. **A1** — this manifest + FK-graph lock. ✅
2. **A2 slice-1 (pilot)** — `device_health` family (root + disks), full vertical: A2 expand + A3 parent `UNIQUE(id, org_id)` + A4 FK flip (detail→root, root→devices) + A5 query canonicalize, in one migration boundary (root org + detail tenant-FK is a bad intermediate).
3. Remaining leaf snapshot families: diagnostics, hardware_inventory, hotfix_posture, services, startup_exposure (same vertical pattern; hotfix/hardware are larger).
4. `app_control_probe_errors` (parent ORG-DONE → needs parent `UNIQUE(id, org_id)` A3 here).
5. Device-child / standalone: software_inventory, device_compliance_states, enrollments, heartbeats, machine_certs, maintenance_tokens, prohibited_software_rules, audit_events.
6. **HUB expansion** — `endpoint_commands` (+children) and `endpoint_software_catalog_items` (+policy/settings): A2+A3 as their own PRs; downstream FK flips separate PRs (many consumers → clearer rollback boundary).
7. ORG-DONE dependents' FK flip — esp. `install_audit → commands/catalog` (blocked until commands/catalog org-ready).
8. uninstall family (requests + audit) — needs device + commands + catalog all org.
9. **A6 final** — component-wise `tenant_id` drop; **devices/commands/catalog hub drop LAST** (after all inbound FKs org-flipped).

## 4. Structural risks (must stay explicit through C4)

- **`compliance_evaluations` device FK is single-column** (`→ endpoint_devices(id)`), not composite. It does NOT physically block the `devices.tenant_id` drop, but it does NOT DB-enforce tenant/org equality. **Decision needed in its slice**: if DB-enforced org isolation is the goal, flip to `(device_id, org_id) → endpoint_devices(id, org_id)`. Flagged `single-column FK semantic audit`.
- **`endpoint_commands` idempotency unique** is `(tenant_id, idempotency_key)`. Org expansion must atomically move the unique/index/query authority to `(org_id, idempotency_key)` — **single arbiter** (V35 cache concurrency lesson: never two redundant uniques + one `ON CONFLICT` arbiter).
- **`endpoint_software_catalog_items`** carries `(tenant_id, catalog_item_id)` business unique + policy/settings/install/uninstall consumers. Catalog A2+A3 MUST land before any consumer FK flip.
- **`endpoint_uninstall_requests.command_id` FK is DEFERRABLE** — preserve deferrability in the flip (else same-tx insert/update chains break).
- **`endpoint_devices` hub business uniques** `(tenant_id, hostname)` + `(tenant_id, machine_fingerprint)` are identity, not just FK targets. Before A6 drop: author org equivalents + a duplicate preflight (`(org_id, hostname)` collisions = 0).
- **`device_compliance_states`** is a tenant-keyed latest-pointer with `latest_evaluation_id` FK to ORG-DONE `compliance_evaluations`; treat as compliance read-model, flip that FK to org-composite in its slice.
- **Detail tables are never standalone** — every snapshot detail's PR boundary MUST be `root + details` together (root org + detail tenant-FK is a forbidden intermediate).

## 5. A6 final-drop blockers (per hub)

| Hub | tenant_id drop unblocked when |
|---|---|
| `endpoint_devices` | all 12 inbound FKs org-composite + business uniques org-equivalent + duplicate preflight clean |
| `endpoint_commands` | all 3 inbound FKs org + idempotency unique moved to `(org_id, idempotency_key)` |
| `endpoint_software_catalog_items` | all 5 inbound FKs org + `(tenant_id, catalog_item_id)` unique org-equivalent |

## 6. A2 slice-1 pilot acceptance (device_health)

- root `endpoint_device_health_snapshots`: `org_id` add + backfill `org_id=tenant_id` + BEFORE INSERT/UPDATE trigger + `CHECK (org_id IS NULL OR org_id=tenant_id)` + index + (after backfill) the non-null + `UNIQUE(id, org_id)` path mirroring V29/V30/V34/V36.
- detail `endpoint_device_health_disks`: `org_id` add (phased-A; not tenant retention) + `(snapshot_id, org_id) → snapshots(id, org_id)` FK.
- root `(device_id, org_id) → endpoint_devices(id, org_id)` FK flip (devices parent UNIQUE(id,org_id)=V34 + org_id NOT NULL=V36 already LIVE).
- add-NOT VALID + VALIDATE + drop-old atomic swap; ON DELETE rule + deferrability preserved.
- A5 repository/query: direct org (or explicitly-bounded transitional COALESCE).
- PG IT: cross-org FK reject 23503, legacy trigger/backfill, detail wrong-org attach reject, delete cascade preserved.

## References
- [cleanup-execution-plan.md](./cleanup-execution-plan.md) (C4 REOPENED banner + F21-R32)
- platform-backend V29/V30/V34/V36 (source org pattern), V33/V35/V37 (cache org pattern) — the migration templates A2-A4 mirror.
- Codex threads `019e926f` (phased-A AGREE), `019e93a1` (A1/A2 slicing REVISE→refinement).
