# Faz 22.5 — Device Health Payload Contract v1 (AG-033 → backend ingest → web view)

> **Status:** contract-fixture gate for the second wave. AG-033 device-health probe is **agent-side MERGED** (platform-agent PR #36, cross-AI: Claude impl + Codex review, thread 019e7500). This document + [schema/endpoint-device-health-payload-v1.schema.json](../schema/endpoint-device-health-payload-v1.schema.json) freeze the wire shape so the backend ingest and web view can be implemented **in parallel** against a single canonical contract (Codex 019e7504 guardrail #2: data-contract = fixture, not prose).

## Context

AG-033 added a read-only device-health probe to the Windows agent (disk free %, memory utilization %, uptime/last-boot, warning booleans) via direct Win32 syscalls. The probe is opt-in (`CollectOptions.IncludeDeviceHealth`) and rides the existing `COLLECT_INVENTORY` result. The **agent side is done and merged**; the backend has no ingest/persist path and the web has no render surface yet. Without a frozen contract, backend and web would each guess the shape and drift. This contract pins it.

## Wire path

The probe block is carried at:

```
COLLECT_INVENTORY result → details.inventory.deviceHealth
```

`deviceHealth` is a nullable object — **absent (null/omitted)** when the caller did not opt in (heartbeat / auto-enroll lightweight default, AG-025H). When present it MUST conform to the schema. Source of truth: `platform-agent internal/inventory/device_health.go` `DeviceHealthResult` (`schemaVersion: 1`).

## Canonical schema

[schema/endpoint-device-health-payload-v1.schema.json](../schema/endpoint-device-health-payload-v1.schema.json) — JSON Schema Draft 2020-12, `additionalProperties: false` at every level, `schemaVersion` pinned `const: 1`, three golden `examples` (healthy / low-disk+high-pressure+long-uptime / non-Windows unsupported). The golden examples are the regression corpus: backend ingest tests and web render tests SHOULD load these verbatim.

## Redaction boundary (security invariant — do not widen)

| Field group | On the wire | NEVER on the wire |
|---|---|---|
| Disk | `driveLetter` (`^[A-Z]:$`), byte totals, derived percent, warning | volume label, serial, filesystem, mount path, GUID |
| Memory | byte totals, used %, commit summary | per-process accounting |
| Uptime | `lastBootEpochSec` (unix seconds), seconds/days, warning | local-time string, timezone, locale |
| Errors | `code` (enum), bounded `summary` (≤200, static phrasing) | raw errno, filesystem path |
| Thresholds | — (agent-side const) | LowDisk/HighPressure/LongUptime are NOT payload-configurable |

Backend persistence and web render MUST NOT introduce any field outside this boundary.

## Forward-compat rule

- The schema is **strict v1** (`additionalProperties: false`) — machine-enforced for validation/CI.
- Backend ingest is **runtime-tolerant**: unknown top-level fields are ignored (and logged at debug), known v1 fields validated. This lets an older backend accept a newer agent without a hard 400.
- A genuinely new shape (new field that consumers must read) → **bump `schemaVersion` to 2 + new schema `$id`** (`...-v2.schema.json`); never silently mutate v1.
- `fixedDisks` ALWAYS serializes as `[]` (never null) — consumers can iterate unconditionally.
- `probeComplete=false` is **fail-closed**: treat as "evidence incomplete", never render the zero-values as a healthy device.

## Expected DB projection (backend ingest target — non-binding suggestion)

Append-only snapshot, mirroring the hardware-inventory precedent (BE-022 `endpoint_hardware_inventory_snapshots`):

```
endpoint_device_health_snapshots
  id, tenant_id, device_id            (composite FK to endpoint_devices)
  schema_version SMALLINT             (= 1)
  supported BOOLEAN, probe_complete BOOLEAN
  any_low_disk BOOLEAN
  fixed_disk_count INT, fixed_disks_truncated BOOLEAN, max_fixed_disks INT
  memory_used_percent SMALLINT, memory_high_pressure BOOLEAN
  uptime_days INT, uptime_seconds BIGINT, last_boot_epoch_sec BIGINT, long_uptime_warning BOOLEAN
  source_used VARCHAR(8) CHECK (source_used IN ('win32','none'))
  probe_duration_ms INT
  collected_at TIMESTAMPTZ
  payload_hash_sha256 VARCHAR(64)     (deep-equality dedupe; lowercase hex; cast-as-string compare, never lower(bytea))
  redacted_payload JSONB              (full validated block, redaction-bounded)
  source_command_result_id           (idempotency probe, hardware-inventory precedent)
-- child: endpoint_device_health_disks (snapshot_id FK, drive_letter, total_bytes, free_bytes, free_percent, low_disk_warning)
```

Dedupe pattern: reuse the BE-022Q approach (payload-hash deep-equality via `cast(:hash as string)` + direct `=` on the VARCHAR; **never** `lower(bytea)`).

## Web view binding (render target)

Device detail drawer → a health surface (new tab or a panel inside the existing Donanım/Detay tab): disk free % per drive + low-disk badge, memory used % + pressure badge, uptime + long-uptime badge. `probeComplete=false` → "evidence incomplete" empty state. `supported=false` → "probe not supported on this device" state. Reuse the WEB-013 hardware-inventory view pattern + RTK Query 404→empty-state convention.

## Cross-repo binding & acceptance

- Backend device-health ingest PR + web device-health view PR MUST reference this contract commit hash in their PR body (`Contract: schema/endpoint-device-health-payload-v1.schema.json @ <commit>`).
- Acceptance: the three golden examples validate against the schema; backend ingest accepts each golden verbatim; web renders each golden (healthy / warning / unsupported) without crash.
- D29: agent SOURCE-MERGED (#36); backend ingest + web view are the next-wave slices, each with its own Up/Functional/Secured gate.

## Scope note — AG-036 / AG-038 are NOT in this contract

This contract is device-health only (the merged, real shape). AG-036 (outdated software) and AG-038 (agent self-health/connectivity diagnostics) are **not yet implemented** (no agent code) and get their **own** `schemaVersion`-pinned contracts when their probes land — designing speculative shapes now would violate "fixture from real code". Track A's next agent work (AG-036/AG-038) ships first, then its contract, then its backend/web consumers.
