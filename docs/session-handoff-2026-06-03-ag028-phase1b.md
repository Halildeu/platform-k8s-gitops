# Session Handoff — 2026-06-03 — AG-028 Phase 1b başlangıcı

> Format: D28 5-alan handoff + sıradaki agent P0 aksiyon listesi.

## 1. Bağlam

AG-028 Managed Uninstall multi-phase chain. Faz 22.5.6. Board #1239.

Bu oturum (Session ~46?) AG-028 Phase 0 + Phase 1a için 4 milestone tamamladı:

1. Board hygiene sweep (17 noStatus → 0; retrospektif gitops #1232 Done+close)
2. AG-028 plan-time consensus (Codex thread `019e8c10` + Phase 1 thread `019e8d81`, 6+2 iter)
3. **Phase 0** — Catalog uninstall flags + change-request flow (platform-backend PR #399, SOURCE-MERGED 2026-06-03)
4. **Phase 1a** — V32 uninstall surface schema + JPA mapping (platform-backend PR #404, SOURCE-MERGED 2026-06-03)

24 lokal PG IT PASS. 26 CI check PASS. 2 archive tag (cross-machine 1+ yıl recovery hazır).

## 2. İddia (MERGED PR'lar bu session)

| PR | Repo | Title | Merged |
|---|---|---|---|
| #399 | platform-backend | AG-028 Phase 0 catalog uninstall flags + change-request maker-checker | 2026-06-03 |
| #404 | platform-backend | AG-028 Phase 1a V32 uninstall surface schema + JPA mapping | 2026-06-03 |
| #1232 | platform-k8s-gitops | Retrospective session delta (Path C + #135 + 7-Zip + #1228) | 2026-06-02 |

Plus kapatılanlar: platform-backend #402 (scope leak, replaced by #404), gitops #305/#309/#1146 (Phase 0 hygiene close), #331/#44/#1154 (stale close).

Archive tag'leri:
- `archive/2026/06/feat-ag-028-phase-0-v3-claude-2026-06-03-pr399`
- `archive/2026/06/feat-ag-028-phase-1a-claude-2026-06-03-v2-pr404`

## 3. İspatlar

### Lokal evidence (12+12 test PASS)

```bash
# Phase 0 (V31 catalog flags)
./mvnw -pl endpoint-admin-service test \
  -Dtest='V31EndpointCatalogUninstallFlagsPostgresIntegrationTest,CatalogUninstallSettingsChangeRequestServiceTest,AdminCatalogUninstallSettingsControllerTest'
# 12/12 PASS (8 PG IT + 2 service + 2 MockMvc)

# Phase 1a (V32 uninstall surface)
./mvnw -pl endpoint-admin-service test \
  -Dtest='V32EndpointUninstallSurfacePostgresIntegrationTest'
# 12/12 PASS (state allowlist + partial unique + composite tenant FK + JSONB shape + append-only trigger + CommandType JPA round-trip)
```

### CI evidence (26 check PASS)

PR #399: 13/13 PASS — Maven full reactor, endpoint-admin slice, notification-orchestrator PG, permission-service PG, report-service MSSQL, auth-service WireMock, contract-gate, gitleaks, osv-scan, ADR-0011 DD-5, OpenFGA DSL, allowlist mirror, schema-service.

PR #404: 13/13 PASS — same matrix on rebased clean main.

### Cross-AI consensus (Codex MCP)

| Thread | Iterations | Final | Konu |
|---|---:|---|---|
| `019e8c10` (expired) | 6 (PARTIAL→REVISE→REVISE→PARTIAL→PARTIAL→AGREE) | AGREE | Phase 0 plan-time |
| `019e8d5b` | 2 (REVISE→AGREE) | AGREE | Phase 0 post-impl (durable audit, ResponseStatusException subclass, MockMvc 403) |
| `019e8c8a` (expired) | replay confirmed | AGREE | Phase 0 finalize |
| `019e8d81` | 2 (PARTIAL→AGREE) | AGREE | Phase 1 plan-time (idempotency replay order, JSONB shape CHECK, history index, DEDICATED_PATH_ONLY 422) |
| `019e8d95` | 2 (REVISE→AGREE) | AGREE | Phase 1a post-impl (scope leak, CommandType enum drift) |

## 4. İspatlamaz (pending)

- **Phase 1b LIVE** — service + REST + sanitizer + tests henüz başlatılmadı (branch hazır: `feat/ag-028-phase-1b-claude-2026-06-03` on main `370b2791`)
- **Phase 2** — Agent UNINSTALL_SOFTWARE + ProbeState detection schema extension
- **Phase 3** — Web (catalog admin "Yönetim Hakları" panel + per-device "Kaldır" button + audit panel + i18n TR+EN)
- **Phase 4** — Gitops digest pins (3 PR: backend + agent + web) + LIVE acceptance smoke (HALILKOOLUB735 7-Zip uninstall E2E)

## 5. Bilinen boşluk + Sıradaki agent için P0 aksiyon listesi

### P0 — Phase 1b implementation (bu session sonrası)

**Branch**: `feat/ag-028-phase-1b-claude-2026-06-03` (zaten oluşturuldu, main `370b2791`)

**Scope** (~15 dosya, ~1500 satır):

1. `EndpointUninstallService` — propose/approve flow:
   - `propose(...)`: feature flag → RBAC → idempotency replay FIRST (Codex iter-1 must-fix #1) → catalog gates (APPROVED + uninstall_supported + !uninstall_protected) → provenance MVP → partial unique race-handled insert → audit emit
   - `approve(...)`: PROPOSED state guard + maker-checker (caller != proposer) → custom exception with noRollbackFor → catalog state revalidation → capability guard (heartbeat freshness TTL 5min + UNINSTALL_SOFTWARE advertised, 422/424 retryable no-terminal) → dispatch UNINSTALL_SOFTWARE command (server-derived payload) → state APPROVED→QUEUED with commandId
   - `getHistory(...)` from `endpoint_uninstall_audit`

2. `EndpointUninstallMakerCheckerViolationException extends ResponseStatusException` (FORBIDDEN, mirror Phase 0)

3. `UninstallEvidencePayloadPolicy` sanitizer:
   - Parity with `InstallEvidencePayloadPolicy`
   - **raw stdoutTail/stderrTail EXCLUDED** (Codex Phase 1 plan iter-6 absorb)
   - DetectionReadout allowlist with `probeState`, `authority`, bounded `safeEvidence`
   - `probeState=null → verification=VERIFY_INCONCLUSIVE` (fail-closed)

4. `AdminEndpointUninstallController` 3 endpoint:
   - `POST /api/v1/admin/endpoint-devices/{deviceId}/uninstalls`
   - `POST /api/v1/admin/endpoint-devices/{deviceId}/uninstalls/{requestId}/approve`
   - `GET /api/v1/admin/endpoint-devices/{deviceId}/uninstalls/history`

5. 3 DTO: `AdminUninstallRequestCreate`, `AdminUninstallRequestApproval`, `AdminUninstallAuditResponse`

6. `EndpointAdminCommandService.validateCommandType` refactor:
   - `EnumSet DEDICATED_PATH_ONLY = of(INSTALL_SOFTWARE, UNINSTALL_SOFTWARE)` → 422
   - **Migrate INSTALL_SOFTWARE from existing 409 to 422** (Codex plan-time iter-2 explicit decision)
   - Update existing INSTALL_SOFTWARE 409 regression test → 422

7. Application properties: `endpoint.admin.uninstall.enabled` (default FALSE → 503) + `endpoint.admin.uninstall.heartbeat-freshness-ttl` (default PT5M)

8. Tests:
   - `EndpointUninstallServiceTest` (`@DataJpaTest` H2): happy approve dispatch, 422 NOT_UNINSTALL_SUPPORTED / PROTECTED / NO_PROVENANCE, 409 in-flight concurrent, 409 idempotency replay returns existing requestId, **403 maker-checker durable audit regression (BE-014A noRollbackFor pattern — like Phase 0)**, 422 CAPABILITY_NOT_ADVERTISED (retryable no-terminal), 424 stale heartbeat, feature flag off → 503, DEDICATED_PATH_ONLY 422 regression for INSTALL_SOFTWARE + UNINSTALL_SOFTWARE
   - `AdminEndpointUninstallControllerTest` (@WebMvcTest): wire-shape regression (200 / 201 / 403 / 409 / 422 / 424 / 503)
   - `UninstallEvidencePayloadPolicyTest`: allowlist drop, raw stdoutTail/stderrTail dropped, raw path/SID/token/JWT/cmdline dropped, bounded scalars retained, probeState→verification fail-closed mapping

### P0 chain (Phase 1b sonrası)

- Phase 1b SOURCE-MERGED + Codex post-impl AGREE
- **Phase 2** — Agent UNINSTALL_SOFTWARE adapter + ProbeState detection result extension (`platform-agent`)
- **Phase 3** — Web (`platform-web`)
- **Phase 4** — Gitops + LIVE (`platform-k8s-gitops`)
- Pre-LIVE prereq: 7-Zip catalog detection rule WINGET_PACKAGE → REGISTRY_UNINSTALL migration + noop INSTALL_SOFTWARE on HALILKOOLUB735 (provenance enabler)

### Plan reference (canonical)

- Plan v6 Phase 1: Codex thread `019e8d81-3d87-78f2-ba17-9a8981c5eb16` iter-2 AGREE
- Plan v6 Phase 0 (merged, for symmetry reference): thread `019e8c10` → `019e8c8a` → `019e8d5b`
- Implementation pattern: `EndpointAdminCommandService.createInstall` line 361 (1:1 mirror with uninstall additions)
- Repository symmetry: `EndpointInstallAuditService` write path
- BE-014A pattern: `CatalogUninstallSettingsMakerCheckerViolationException` (Phase 0, AG-028 already proven)

### Yeni Session Açılışı

```bash
cd /Users/halilkocoglu/Documents/platform-backend
git checkout feat/ag-028-phase-1b-claude-2026-06-03

cat /Users/halilkocoglu/Documents/platform-k8s-gitops/docs/session-handoff-2026-06-03-ag028-phase1b.md
```

Continuous Autonomous Mode + Plan Consensus Autonomy + Continuous Autonomous Mode aktif. Phase 1b plan-time AGREE alındığı için (Codex `019e8d81` iter-2) implementation direkt başlayabilir.
