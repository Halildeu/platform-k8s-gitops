# Faz 22.5 — Outdated Software Payload Contract v1 (AG-036 → backend ingest → web view)

> **Status:** contract-fixture gate for the AG-036 consumer wave. The AG-036 outdated-software probe is **agent-side MERGED** (platform-agent PR #38, merged sha `a29eef49`; cross-AI: MiniMax probe + Claude cross-compile/REVISE fixes, Codex review thread `019e764b` AGREE). The truncation/`upgradeCount` semantics were finalized by **platform-agent PR #40** (merged sha `e64c131`) and the wire-semantics decision recorded here (see §"Decision record — `upgradeCount` semantics", Codex thread `019e77df`). This document + [schema/endpoint-outdated-software-payload-v1.schema.json](../schema/endpoint-outdated-software-payload-v1.schema.json) freeze the wire shape; the backend ingest and web view are **already built** against it (see §"Cross-repo binding & acceptance").

## Context

AG-036 added a read-only outdated-software probe to the Windows agent: it enumerates upgradeable packages via `winget upgrade --include-returning-apps --source winget` and reports, per package, the installed → available version delta. The probe is opt-in (`CollectOptions.IncludeOutdatedSoftware`) and rides the existing `COLLECT_INVENTORY` result. The **agent side is done and merged** (probe PR #38 + truncation-semantics PR #40). The **backend ingest and web view are also built** against this contract — backend: `OutdatedSoftwarePayloadPolicy` (pre-persist sanitize/validate), `EndpointOutdatedSoftwareSnapshot` + V20 migration, `AdminEndpointOutdatedSoftwareController` (`/latest` + `/history`); web: `mfe-endpoint-admin` `OutdatedSoftwareView` + `endpoint-outdated-software/types.ts` + inventory-export columns. This contract is the canonical wire shape all three repos pin. It follows the same discipline as the AG-033 device-health contract ([docs/faz-22-device-health-contract-v1.md](./faz-22-device-health-contract-v1.md)).

## Wire path

The probe block is carried at:

```
COLLECT_INVENTORY result → details.inventory.outdatedSoftware
```

`outdatedSoftware` is a nullable object — **absent (null/omitted)** when the caller did not opt in (heartbeat / auto-enroll / lightweight inventory default). When present it MUST conform to the schema. Source of truth: `platform-agent internal/inventory/outdated_software.go` `OutdatedSoftwareResult` (`schemaVersion: 1`); the parser cap + truncation flag live in `internal/inventory/outdated_software_parse.go` `parseUpgradeOutput` (finalized in PR #40 / `e64c131`).

## Canonical schema

[schema/endpoint-outdated-software-payload-v1.schema.json](../schema/endpoint-outdated-software-payload-v1.schema.json) — JSON Schema Draft 2020-12, `additionalProperties: false` at every level, `schemaVersion` pinned `const: 1`, `upgradeCount` bounded `minimum: 0` + `maximum: 512` (machine-enforced cap, in lockstep with the agent const, the backend policy `[0,512]`, and the DB `CHECK (upgrade_count <= max_upgrade)`), `maxUpgrade` pinned `const: 512`, `upgrade` `maxItems: 512`, `sourceUsed` enum `[winget, none]`, three inline golden `examples` (with-upgrades / no-upgrades-clean / non-Windows unsupported). A fourth, **truncated** golden (exactly 512 packages + `upgradeTruncated: true`) lives as a separate fixture — [tests/contracts/fixtures/outdated-software/valid-truncated-v1.json](../tests/contracts/fixtures/outdated-software/valid-truncated-v1.json) — kept out of the inline `examples` only to avoid bloating the schema file. The golden examples + fixtures are the regression corpus: backend ingest tests and web render tests SHOULD load these verbatim. The contract is self-validated in this repo by [tests/contracts/test_outdated_software_payload_contract_v1.py](../tests/contracts/test_outdated_software_payload_contract_v1.py) (gate: [.github/workflows/gate-outdated-software-contract.yml](../.github/workflows/gate-outdated-software-contract.yml)).

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
- **Truncation is authoritative via `upgradeTruncated`** (finalized by platform-agent PR #40 / `e64c131`; the earlier "parser caps before the flag is evaluated → `upgradeTruncated=false`" limitation is **fixed**). `upgradeCount` is the returned/capped count and the true pending total is intentionally not on the wire when truncated — see §"Decision record — `upgradeCount` semantics" for the full decision and the rejected alternatives.

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

Device detail drawer → an outdated-software surface (panel/tab): per-package `packageId` + `installedVersion → availableVersion`, an upgradeable count badge, and a "list truncated" hint driven by the authoritative `upgradeTruncated` flag (post-#40). `probeComplete=false` → "evidence incomplete" empty state. `supported=false` → "probe not supported on this device" state. Reuse the WEB-013 hardware-inventory + device-health view patterns + RTK Query 404→empty-state convention.

> **Current consumer drift (tracked, NOT this contract's final state):** the shipped backend (`possiblyTruncated = upgradeCount == maxUpgrade`, derived in `EndpointOutdatedSoftwareService` + the two response DTOs) and web (`isPossiblyTruncated` in `OutdatedSoftwareView`; `outdatedPossiblyTruncated` `upgradeCount >= maxUpgrade` in `deviceInventoryColumns`) were built against the PRE-#40 contract and still key the truncation hint off the `==/>= maxUpgrade` heuristic, ignoring the now-authoritative `upgradeTruncated`. This heuristic false-positives at exactly-512. Aligning the consumers to prefer `upgradeTruncated` (heuristic kept only as a conservative legacy fallback for pre-#40 historical rows) is a separate cross-AI-reviewed follow-up per repo — see the follow-up board issue linked in §"Decision record".

## Cross-repo binding & acceptance

- Backend outdated-software ingest PR + web outdated-software view PR MUST reference this contract commit hash in their PR body (`Contract: schema/endpoint-outdated-software-payload-v1.schema.json @ <commit>`).
- Acceptance: the three golden examples validate against the schema; backend ingest accepts each golden verbatim; web renders each golden (with-upgrades / clean / unsupported) without crash.
- D29: agent SOURCE-MERGED (#38 probe + #40 truncation semantics); backend ingest + web view are SOURCE-BUILT (code merged) and each still owns its own Up/Functional/Secured LIVE acceptance gate.

## Decision record — `upgradeCount` semantics (AG-036 PR #40 contract debt)

Codex flagged during the platform-agent PR #40 review that the wire meaning of `upgradeCount` under truncation was unresolved (deliberately deferred to keep that fix tight). Board issue [#1147](https://github.com/Halildeu/platform-k8s-gitops/issues/1147); cross-AI decision thread Codex `019e77df` (VERDICT: REVISE → option (a), revisions absorbed).

**Question.** When a host has more than `maxUpgrade` (512) pending upgrades, the agent caps the returned `upgrade` list at 512 and sets `upgradeTruncated=true`; `finalizeOutdatedSoftware` sets `upgradeCount = len(upgrade) = 512`. Does the wire contract intend `upgradeCount` to mean the **returned/capped count** or the **true total pending upgrades**?

**Decision: option (a) — `upgradeCount` is the returned/capped count; `upgradeTruncated` is the authoritative "list incomplete" signal.** The capped count is bounded `[0, maxUpgrade]` and machine-enforced (`maximum: 512`). The true pending total is intentionally **not** carried on the wire when truncated; consumers that need "is the list complete?" read `upgradeTruncated` (authoritative post-#40). No agent code change is required — the merged post-#40 agent already implements this exactly.

**Why not (b) — add a distinct `totalUpgradeCount` (true total, may exceed 512)?** Deferred. There is **no consumer** for a true total today (the truncation flag already conveys "incomplete"; nothing ranks hosts by exact overflow magnitude). Adding it would mean an agent parser change + new struct field + a schema field that, per this repo's own forward-compat rule ("a new field consumers must read → bump `schemaVersion` to 2 + new `$id`; never silently mutate v1"), warrants a **v2** bump — plus a backend policy change, a **new DB column** (V21), DTO/service/repository changes, and web type/view/export changes. Designing that shape now for a hypothetical future risk-ranking consumer is exactly the "speculative shape" the AG-038 scope note below forbids. If/when a real consumer needs the true total, add `totalUpgradeCount` then, with its consumer, as a clean v2.

**Why not (c) — overload `upgradeCount` to carry the true total (parser counts past the cap)?** Rejected — it would **break the shipped consumers**. The backend ingest policy fail-closed rejects `upgradeCount > 512` (`OutdatedSoftwarePayloadPolicy` enforces `[0,512]`) and the DB `CHECK (upgrade_count <= max_upgrade)` rejects it at persist time, so a true-total >512 in `upgradeCount` would fail the entire `COLLECT_INVENTORY` ingest for precisely the most-unpatched hosts — strictly worse than the under-report.

**Consumer-alignment follow-up.** The shipped backend + web still derive the truncation hint from the legacy `upgradeCount ==/>= maxUpgrade` heuristic (false-positive at exactly-512) instead of the now-authoritative `upgradeTruncated`. Aligning them (heuristic kept only as a conservative legacy fallback for pre-#40 historical rows) is tracked as [#1148](https://github.com/Halildeu/platform-k8s-gitops/issues/1148) — a separate per-repo, cross-AI-reviewed slice; per Codex `019e77df` it is **not** a hard blocker for this contract-only change.

## Scope note — AG-038 is NOT in this contract

This contract is outdated-software only (the merged, real AG-036 shape). AG-038 (agent self-health / connectivity diagnostics) is a **separate** probe and gets its **own** `schemaVersion`-pinned contract when its probe lands — designing a speculative shape now would violate "fixture from real code".
