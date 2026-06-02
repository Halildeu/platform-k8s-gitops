# Sprint Plan — Faz 22.7 Compliance Gap Mart Layer

> Codex plan-time thread: `019e881c-e077-7c92-bfdd-339710b58a1c` (Recommendation D AGREE)
> Plan-time date: 2026-06-02
> Sprint scope: 4-5 PR cross-service (endpoint-admin backend + platform-web frontend + docs)
> Board issue: platform-backend [#376](https://github.com/Halildeu/platform-backend/issues/376)

---

## Codex consensus

**Recommendation D AGREE**: Faz 22.7 compliance gap mart layer is the highest-leverage next sprint after Faz 22.5 D-chain SPRINT KAPALI. Converts existing LIVE visibility data (AG-037..AG-041 + AG-035 + BE-024..BE-028) into operator decision layer via cross-filterable aggregate queries.

### Why D wins over A/B/C/E/F

- **A (Sprint C P2 visibility extension)**: Higher-sensitivity surfaces (process tree, network conn, scheduled-job, USB enum) — Codex consensus retained gate: full implementation requires HALILKOOLUB735 acceptance window + privacy/redaction review. Threat model + contract can be parallel-prepared (A-lite path).
- **B (PR-D2.5a digest endpoint consumer)**: Digest LIVE but no consumer. Adding 6th D-chain module requires PR-E ratchet update — governance churn on closed 5/5 state. Better surfaced as sub-capability within D mart layer if needed.
- **C (Compliance authoring UI)**: Real admin workflow gap but tracked as low priority (platform-web #735). Local benefit; mart layer first surfaces "what to author" before improving authoring ergonomics.
- **E (Faz 23 RAID risk items)**: M8 trigger-gated on M7 30-day stability. Cross-cutting durability vs direct product value — D delivers operator decision value within current Faz 22.x momentum.
- **F (Defer/wait operator)**: Continuous Autonomous Mode incompatible with idle session. Board hygiene is sprint sub-step (D0 + D5), not the sprint itself.

---

## 7-PR sub-chain (D0..D6)

### D0 — Board claim + sprint contract

**Scope**: Open tracked issue + sprint plan + claim governance state.

**Status**: ✅ DONE
- Board issue: [platform-backend #376](https://github.com/Halildeu/platform-backend/issues/376)
- Sprint plan: this doc (PR-D0)

**Acceptance**: Issue Agent State current, blocker list explicit, PRs use "Tracked by" for runtime issue.

---

### D1 — Gap mart contract

**Scope**: Define the unified read-model contract pulled from existing LIVE snapshot tables.

**Source tables** (already LIVE):
- `endpoint_hotfix_posture_snapshots` (AG-037 / V22)
- `endpoint_diagnostics_snapshots` (AG-038 / V23)
- `endpoint_critical_services_snapshots` (AG-039 / V24)
- `endpoint_startup_exposure_snapshots` (AG-040 / V25)
- `endpoint_application_control_snapshots` (AG-041 / V26)
- `endpoint_hardware_snapshots` (AG-035 / BE-022 / V14)
- `endpoint_software_inventory_snapshots` (BE-020I)
- `endpoint_compliance_evaluations` (BE-023)
- `endpoint_devices` (cihaz metadata)

**Field allowlist** (per snapshot):

| Source | Surfaceable fields | Forbidden |
|---|---|---|
| hotfix posture | `pendingUpdateCount`, `pendingSecurityUpdateCount`, `pendingFeatureUpdateCount`, `latestInstalledKb`, `latestInstalledOn` | KB list raw, full update title |
| diagnostics | `serviceState`, `lastHeartbeatAge`, `wingetStatus`, `wingetEgressStatus` | Process IDs, full command lines |
| critical services | `criticalServicesUp`, `criticalServicesDown[]` (service name only), `criticalServicesUnknown[]` | Process IDs, command-line args |
| startup exposure | `rdpEnabled`, `windowsFirewallEventLogEnabled`, `startupAppCount`, `startupAppLocations[]` (anchor enum) | Full paths, command-line args |
| application control | `wdacPolicyEnforcementMode`, `wdacPolicyState`, `appLockerEnabled`, `appLockerRuleCount`, `mvpDriverBlocklistVersion` | Policy XML, certificate fingerprints |
| hardware | `osName`, `osVersion`, `architecture`, `totalMemoryGiB`, `cores`, `diskFreeGiB` | Serial numbers, MAC addresses |
| software inventory | `softwareCount`, `prohibitedSoftwareCount`, `outdatedSoftwareCount`, `wingetReadiness` | Package list raw |
| compliance evaluations | `complianceState`, `requiredItemsTotal`, `requiredItemsSatisfied`, `forbiddenItemsTotal`, `forbiddenItemsPresent` | Item-level details |

**Freshness semantics**:
- Per-snapshot `collectedAt` timestamp REQUIRED in mart query response
- `freshness_window` default 7 days; older snapshots labeled `stale=true` but still surfaceable
- Cross-snapshot correlation: default mart query joins on `device_id` AND `collectedAt BETWEEN ? AND ?` window
- "strong gap" = all referenced snapshots within freshness window
- "weak gap" = at least one stale snapshot — labeled as `gap_strength=weak` + `stale_components=[...]`

**No-raw-secret policy**: All string fields pass through `SUMMARY_VALUE_DENYLIST_RE` (URL/Bearer/IP/token/host pattern from AG-038-be). All paths pass through `NAME_FULLPATH_DENYLIST_RE` (drive letter / UNC / exe extension / control char). Mart layer never surfaces details that the source policy already redacted.

**Acceptance**: contract doc PR (this), schema canonical + fixture set + test infrastructure outline; no source code change in D1.

---

### D2 — Backend aggregate query API

**Scope**: Endpoint-admin cross-filterable compliance gap REST endpoint.

**Endpoint**: `GET /api/v1/admin/endpoint-devices/compliance-gap`

**Required query params**: none (default surface = all devices, paginated)

**Optional filters**:
- `gapType[]` (multi): `rdp_enabled`, `pending_security_updates`, `winget_unreachable`, `critical_service_down`, `appLocker_disabled`, `wdac_audit_only`, `local_admin_present`, `outdated_software`, `prohibited_software`, ... (full enum in code)
- `gapStrength`: `strong` (default) | `weak` | `any`
- `freshnessWindow`: ISO-8601 duration (default `PT7D`)
- `device[]`: filter to specific device IDs
- `sort`: `lastSeen,desc` (default) | `gapCount,desc` | `device,asc`
- `page` (default 1) + `pageSize` (default 50, max 200)

**Response shape**:
```json
{
  "items": [
    {
      "deviceId": "<uuid>",
      "deviceName": "HALILKOOLUB735",
      "lastSeen": "2026-06-02T08:15:00Z",
      "gapCount": 4,
      "gapStrength": "strong",
      "gaps": [
        {
          "type": "rdp_enabled",
          "label": "Uzak Masaüstü Etkin",
          "sourceSnapshotCollectedAt": "2026-06-02T08:15:00Z",
          "stale": false,
          "details": { "rdpEnabled": true }
        },
        ...
      ],
      "staleComponents": []
    }
  ],
  "total": 23,
  "page": 1,
  "pageSize": 50,
  "filterEcho": { ... },
  "computedAt": "2026-06-02T11:45:00Z"
}
```

**Implementation**:
- `EndpointComplianceGapService` orchestrating queries against per-snapshot repositories
- Native SQL with explicit JOINs on `device_id` + freshness window
- Per-gap-type predicate (e.g. `rdp_enabled` = `WHERE startup_exposure.rdp_enabled = TRUE AND collectedAt > NOW() - INTERVAL '7 days'`)
- Bounded query: pagination max 200, max 50 gap-types per request, max 366d freshness window
- @RequireModule(ENDPOINT_ADMIN, can_view) RBAC

**Tests**:
- Service unit tests (validation + dispatch)
- Per-gap-type predicate fixture tests
- Pagination + sort tests
- Stale snapshot labeling tests
- Cross-snapshot freshness window tests
- Testcontainers PG integration test (different DB session timezone validation)

**Acceptance**: 200 OK with seeded fixture → exact aggregate JSON shape match per fixture row.

**Branches**: `feat/faz-22-7-d2-compliance-gap-api`

---

### D3 — Frontend gap explorer

**Scope**: Platform-web unified gap list with drill-down.

**UI**:
- New route `/admin/compliance-gaps` (or extend Endpoint Admin tab)
- Filter bar: gap type multi-select + freshness window picker + device search
- AG-Grid: deviceName, lastSeen, gapCount badge (red >5, yellow 1-5, green 0), gap chips
- Row click → device drawer (drilldown to per-snapshot tab)
- Stale badge per row when `staleComponents` non-empty
- Empty state when no gaps match
- Loading state during query
- 403 forbidden state (gracefully degrade)

**Browser smoke**:
- Real testai cluster query → 200 + grid render + filter exercise
- Click row → drawer navigation
- Console clean

**Tests**:
- React Testing Library: filter bar + grid render + drilldown
- vitest mock for backend response
- E2E browser smoke (post-deploy)

**Branches**: `feat/faz-22-7-d3-compliance-gap-explorer`

---

### D4 — ReportDefinition bridge (OPTIONAL)

**Scope**: If reporting integration wanted, add `audit-compliance-gap.json` ReportDefinition pointing to D2 endpoint.

**Critical constraint**: D-chain 5/5 PR-E ratchet (test-only) currently locks `(service, path, responseShape)` tuples. Adding `audit-compliance-gap` would push to 6/6 — requires explicit ratchet update sprint.

**Decision criteria**:
- If reporting view is essential → separate B-style sprint (PR-D2.6) with ratchet update
- If frontend D3 is sufficient → skip D4 entirely; mart layer accessible via Endpoint Admin

**Default**: SKIP D4 unless explicit reporting integration request lands.

---

### D5 — Live acceptance

**Scope**: HALILKOOLUB735 cluster snapshot fixtures with ≥3 birleşik query exercises.

**Test scenarios**:
1. `rdpEnabled + pending_security_updates` — known correlation
2. `appLocker_disabled + local_admin_present` — security risk pattern
3. `winget_unreachable + outdated_software` — supply chain visibility gap

**Acceptance evidence** (HARD RULE Tarayıcıdan Sonuç Doğrulanmadan):
- Cluster API 200 + JSON shape match
- Browser grid render + filter exercise
- Drill-down navigation works
- Pod imageID = overlay digest (D29 invariant)
- current-state.md LIVE delta written

**Operator-bound parts**: if HALILKOOLUB735 has insufficient seeded data, may need ≥1 additional device snapshot (operator action). Synthetic fixtures only for test, NOT live claim.

---

### D6 — A-gate revisit

**Scope**: After D5 LIVE, analyze which visibility gaps the mart layer EXPOSES vs MISSING. If specific telemetry would close decision-quality gaps:
- Reorder Sprint C P2 priorities (process / network / sched / USB enum)
- Or: reschedule to focus on detection signal richness instead of raw collection

**Acceptance**: New A-gate plan iter via Codex consensus (`019e840b` follow-up thread).

---

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Fleet compliance yanılgısı (sample → fleet) | Her sonuçta sample scope, latestSeen, freshness window, 'observed devices only' semantiği |
| Cross-snapshot zaman drift'i | Freshness threshold + per-snapshot collectedAt + stale labeling |
| Hassas veri genişlemesi | Yalnız allowlisted scalar/enum/sanitized fields; A P2 ayrıca privacy review |
| Query/perf büyümesi | Pagination, bounded filters, selective indexes; server-side filter |
| Governance drift (PR-E ratchet) | D-chain 5/5 state dokunulmaz; aggregate route ayrı isimlendir |
| Overclaim | Scope read-only gap visibility; auto-remediation iddiası YOK |

## Parallel safe paths

| Path | Description | Can run parallel with |
|---|---|---|
| A-lite | Sprint C P2 threat model + schema/redaction contract | D2-D6 (different scope) |
| B-lite | PR-D2.5a digest endpoint consumer design + ratchet impact analysis | D1-D6 (different scope) |
| C-thin | platform-web #735 detector authoring UI spike | D3 (different surface) |
| E-targeted | R22 GHCR outage runbook veya R14 bundle size gate refresh | D1-D5 |
| F-as-hygiene | Board hygiene + current-state truth closure | D0/D5 sprint sub-steps |

## Next session — first action

```bash
# Already done in PR-D0:
# - Board issue: platform-backend #376
# - Sprint plan: this doc

# D2 (backend aggregate query API):
cd /Users/halilkocoglu/Documents/platform-backend
git checkout -b feat/faz-22-7-d2-compliance-gap-api origin/main

# 1. Read this plan: docs/sprint-plan-faz-22-7-compliance-gap-mart.md
# 2. Codex thread: 019e881c-e077-7c92-bfdd-339710b58a1c (plan-time AGREE)
# 3. Implement D2:
#    - EndpointComplianceGapService (orchestration)
#    - Per-snapshot repository methods (gap-type predicates)
#    - Native SQL with explicit JOINs + freshness window
#    - @RequireModule(ENDPOINT_ADMIN, can_view) controller endpoint
#    - Unit + integration (Testcontainers PG) tests
# 4. Cross-AI Codex post-impl review (provider isolation)
```

---

## References

- Codex plan-time thread: `019e881c-e077-7c92-bfdd-339710b58a1c`
- Board issue: [platform-backend #376](https://github.com/Halildeu/platform-backend/issues/376)
- D-chain SPRINT KAPALI truth: `docs/state/current-state.md` head delta + gitops PR #1206
- ADR-0012-EA: Endpoint Admin Governance Charter
- ADR-0015: Report execution adapter (D-chain governance)
- PR-E ratchet (D-chain test-only lock): platform-backend PR #371
- HARD RULE Plan Consensus Autonomy: Codex AGREE → direct impl
- HARD RULE No Fake Work: synthetic fixtures only in tests, NOT in live claim
- HARD RULE Continuous Autonomous Mode: sıradaki session devam eder
- HARD RULE Tarayıcıdan Sonuç Doğrulanmadan: D5 browser smoke zorunlu
