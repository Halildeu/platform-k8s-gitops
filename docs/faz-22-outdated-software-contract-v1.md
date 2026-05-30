# Faz 22.5 — Outdated Software Payload Contract v1 (AG-036 → backend ingest → web view)

> **Status:** contract-fixture gate for the AG-036 consumer wave. The AG-036 outdated-software probe is **agent-side MERGED** (platform-agent PR #38, merged sha `a29eef49`; cross-AI: MiniMax probe + Claude cross-compile/REVISE fixes, Codex review thread `019e764b` AGREE). This document + [schema/endpoint-outdated-software-payload-v1.schema.json](../schema/endpoint-outdated-software-payload-v1.schema.json) freeze the wire shape so the backend ingest and web view can be implemented **in parallel** against a single canonical contract (Codex 019e7504 guardrail #2: data-contract = fixture, not prose).

## Context

AG-036 added a read-only outdated-software probe to the Windows agent: it enumerates upgradeable packages via `winget upgrade --include-returning-apps --source winget` and reports, per package, the installed → available version delta. The probe is opt-in (`CollectOptions.IncludeOutdatedSoftware`) and rides the existing `COLLECT_INVENTORY` result. The **agent side is done and merged**; the backend has no ingest/persist path and the web has no render surface yet. Without a frozen contract, backend and web would each guess the shape and drift. This contract pins it. It follows the same discipline as the AG-033 device-health contract ([docs/faz-22-device-health-contract-v1.md](./faz-22-device-health-contract-v1.md)).

## Wire path

The probe block is carried at:

```
COLLECT_INVENTORY result → details.inventory.outdatedSoftware
```

`outdatedSoftware` is a nullable object — **absent (null/omitted)** when the caller did not opt in (heartbeat / auto-enroll / lightweight inventory default). When present it MUST conform to the schema. Source of truth: `platform-agent internal/inventory/outdated_software.go` `OutdatedSoftwareResult` (`schemaVersion: 1`).

## Canonical schema

[schema/endpoint-outdated-software-payload-v1.schema.json](../schema/endpoint-outdated-software-payload-v1.schema.json) — JSON Schema Draft 2020-12, `additionalProperties: false` at every level, `schemaVersion` pinned `const: 1`, `maxUpgrade` pinned `const: 512`, `upgrade` `maxItems: 512`, `sourceUsed` enum `[winget, none]`, three golden `examples` (with-upgrades / no-upgrades-clean / non-Windows unsupported). The golden examples are the regression corpus: backend ingest tests and web render tests SHOULD load these verbatim.

## Redaction boundary (security invariant — do not widen)

| Field group | On the wire | NEVER on the wire |
|---|---|---|
| Package | `packageId` (winget id, no whitespace), `installedVersion`, `availableVersion` | display name, publisher, install location, license, download URL |
| Errors | `code` (enum), bounded `summary` (≤200, static phrasing) | raw errno, filesystem path, package display name |
| Caps | — (agent-side const `maxUpgrade=512`) | not payload-configurable |

The per-package key set is **exactly** `{packageId, installedVersion, availableVersion}` — machine-enforced both in this schema (`additionalProperties: false`) and at source (`TestOutdatedSoftwarePackage_JSONKeys` asserts the exact key set + forbidden-PII-fragment scan). Backend persistence and web render MUST NOT introduce any field outside this boundary. The two version strings are functionally required (an "outdated" signal is meaningless without the from/to versions) and are public, non-PII.

## Read-only boundary (agent invariant)

The probe is **read-only**: `winget upgrade --include-returning-apps --source winget` only enumerates; it NEVER runs `winget upgrade <id>` / `install` / `uninstall` / source mutation. Backend ingest is a persist/query path; it MUST NOT trigger any agent-side mutation from this payload.

## Forward-compat rule

- The schema is **strict v1** (`additionalProperties: false`) — machine-enforced for validation/CI.
- Backend ingest is **runtime-tolerant**: unknown top-level fields are ignored (and logged at debug), known v1 fields validated. This lets an older backend accept a newer agent without a hard 400.
- A genuinely new shape (new field consumers must read) → **bump `schemaVersion` to 2 + new schema `$id`** (`...-v2.schema.json`); never silently mutate v1.
- `upgrade` ALWAYS serializes as `[]` (never null) — consumers can iterate unconditionally.
- `probeComplete=false` is **fail-closed**: treat as "evidence incomplete", never render an incomplete probe as "fully up to date".
- **Known v1 limitation (tracked follow-up):** the agent parser caps at 512 before `upgradeTruncated` is evaluated, so a host with >512 pending upgrades is truncated with `upgradeTruncated=false`. Consumers should treat `upgradeCount == maxUpgrade (512)` as "possibly truncated". The durable agent-side fix (parser signals truncation) is a separate spawn-task follow-up.

## Expected DB projection (backend ingest target — non-binding suggestion)

Append-only snapshot, mirroring the BE-024 software-inventory + AG-033 device-health precedents:

```
endpoint_outdated_software_snapshots
  id, tenant_id, device_id            (composite FK to endpoint_devices)
  schema_version SMALLINT             (= 1)
  supported BOOLEAN, probe_complete BOOLEAN
  upgrade_count INT, upgrade_truncated BOOLEAN, max_upgrade INT
  source_used VARCHAR(8) CHECK (source_used IN ('winget','none'))
  probe_duration_ms INT
  collected_at TIMESTAMPTZ
  payload_hash_sha256 VARCHAR(64)     (deep-equality dedupe; lowercase hex; cast-as-string compare, never lower(bytea))
  redacted_payload JSONB              (full validated block, redaction-bounded)
  source_command_result_id           (idempotency; partial-unique + ON CONFLICT DO NOTHING per BE-024)
-- child: endpoint_outdated_software_packages (snapshot_id FK, package_id, installed_version, available_version)
```

Reuse the BE-024 atomicity pattern: native `INSERT ... ON CONFLICT (source_command_result_id) WHERE source_command_result_id IS NOT NULL DO NOTHING` against a partial-unique index (a duplicate command-result is a clean no-op; every other violation propagates and rolls back the whole ingest tx). Dedup via payload-hash deep-equality with `cast(:hash as string)` + direct VARCHAR `=`; **never** `lower(bytea)`.

## Web view binding (render target)

Device detail drawer → an outdated-software surface (panel/tab): per-package `packageId` + `installedVersion → availableVersion`, an upgradeable count badge, and a "possibly truncated" hint when `upgradeCount == 512`. `probeComplete=false` → "evidence incomplete" empty state. `supported=false` → "probe not supported on this device" state. Reuse the WEB-013 hardware-inventory + device-health view patterns + RTK Query 404→empty-state convention.

## Cross-repo binding & acceptance

- Backend outdated-software ingest PR + web outdated-software view PR MUST reference this contract commit hash in their PR body (`Contract: schema/endpoint-outdated-software-payload-v1.schema.json @ <commit>`).
- Acceptance: the three golden examples validate against the schema; backend ingest accepts each golden verbatim; web renders each golden (with-upgrades / clean / unsupported) without crash.
- D29: agent SOURCE-MERGED (#38); backend ingest + web view are the next-wave slices, each with its own Up/Functional/Secured gate.

## Scope note — AG-038 is NOT in this contract

This contract is outdated-software only (the merged, real AG-036 shape). AG-038 (agent self-health / connectivity diagnostics) is a **separate** probe and gets its **own** `schemaVersion`-pinned contract when its probe lands — designing a speculative shape now would violate "fixture from real code".
