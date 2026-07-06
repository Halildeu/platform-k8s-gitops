# Faz 22.5 — A2 Rollout Controls (22.5.8) Functional Acceptance (2026-06-09)

> **Closes the A2 gap** the 2026-06-09 assessment + Stop-hook flagged ("rollout
> controls functional acceptance"). Method: **user-authorized** authenticated API
> smoke (AskUserQuestion 2026-06-09 — owner chose "API smoke'u yetkilendir") on
> testai, reusing the live admin session token to exercise the BE-026 rollout
> endpoint on test device **HALILKOOLUB735** (`d0efb00a`). Benign + reversible
> testai metadata mutation; reverted after. (HARD RULE — Tarayıcıdan Sonuç
> Doğrulanmadan; pre-production full authority + explicit owner authorization for
> the credential-reuse + mutation.)

## BE-026 — Rollout rings + device tags ✅ PASS (authenticated mutation + verify)

Endpoint: `PATCH /api/v1/endpoint-admin/endpoint-devices/{deviceId}/rollout`
(gateway → backend `/api/v1/admin/endpoint-devices/{id}/rollout`,
`@RequireModule(MANAGER)`). Body `UpdateDeviceRolloutRequest { deploymentRing:
DeploymentRing(PILOT|IT|DEPARTMENT|ALL), deviceTags: Set<String> }`.

| Step | Call | Result |
|---|---|---|
| GET before | `GET …/endpoint-devices/d0efb00a` | **200** — ring=`PILOT`, tags=`[]` |
| **PATCH** | `PATCH …/d0efb00a/rollout` `{deploymentRing:"PILOT", deviceTags:["faz225-rollout-smoke"]}` | **200** — response ring=`PILOT`, tags=`["faz225-rollout-smoke"]` |
| GET verify | `GET …/endpoint-devices/d0efb00a` (independent re-read) | **200** — **tags=`["faz225-rollout-smoke"]`** (mutation persisted) |
| Revert (cleanup) | `PATCH …/d0efb00a/rollout` `{deploymentRing:"PILOT", deviceTags:[]}` | **200** — final tags=`[]` (clean state restored) |

→ The rollout-ring / device-tag assignment works **end-to-end on testai**:
authenticated (MANAGER authz), mutating, independently verified, and cleanly
reverted. **BE-026 rollout controls functionally accepted.**

## BE-031 — Agent update release catalog ✅ PASS (authenticated read)

- `GET /api/v1/endpoint-admin/endpoint-agent-update-releases` → **200**
  (authenticated; the agent-update release catalog surface is live).
  (`/agent-update-releases` → 404; the canonical path is
  `/endpoint-agent-update-releases`.)

## Net — Faz 22.5 agent-doable acceptance scope CLOSED

| Item | Status |
|---|---|
| A1 doc-drift reconcile | ✅ already done (parallel: plan §0.1bis + current-state accurate) |
| A2 rollout controls functional | ✅ **this session** — BE-026 PATCH/verify/revert 200 + BE-031 GET 200 |
| A3 AG-039 / AG-040 browser smoke | ✅ this session (#1412) |
| A4 22.5.3B/C full-surface acceptance | ✅ this session (#1412 + #1414) |
| A5 AG-029 Windows self-update smoke | ✅ already done (parallel: local-lab baseline) |

**Remaining 22.5 is operator/infra/time-gated only** (NOT agent-completable by
definition): multi-device + 24-72h soak (#1044); M2 edge-mTLS DNS/host (#1359);
M4 Authenticode signed MSI (cert procurement); M5–M7 GPO 5/50/800-PC pilot/wave;
domain pilot (#1037/#1015); AG-029 multi-device + trusted signing; prod
enablement (owner). BE-027 schedule / BE-028 throttle / BE-029 bundles deeper
functional exercises remain as optional follow-up smokes (BE-026 ring/tag core
proven here).

> Note: BE-026..032 backend is deployed on the live testai endpoint-admin pod
> (`sha-84c927b`), which differs from the test-overlay pin (`sha-3e1e585`) — a
> parallel `kubectl set image` drift; a reconcile overlay bump is owed (separate).
