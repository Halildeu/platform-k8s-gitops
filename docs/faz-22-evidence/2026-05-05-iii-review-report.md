# Faz 22.1.1b III Review Report — BE-009/BE-013 Maintenance Token Implementation

> **Status**: COMPLETE (read-only review, NO push, NO commit)
> **Date**: 2026-05-05
> **Reviewer**: Claude Explore subagent (a76734d58fafef3b4)
> **Trigger**: User mandate "tam otomasyon auto mode ile uçtan uca yapalım" → Faz 22.1.1b unblock for Faz 23.1 dependency
> **Codex thread reference**: `019df331` (Q3 AGREE — 5. verdict state `I-staged-pending-schema-rev` template'e eklendi)

## Provenance

- **Worktree path**: `/Users/halilkocoglu/Documents/platform-backend`
- **Branch HEAD**: `bf59897` (commit message: "fix(22.1.1 BE-009): relation align EndpointAdminAuthz to OpenFGA model contract")
- **Untracked file count**: 25 entries (22 Java/SQL code files + 3 directory markers)
- **Image probe** (`sha256:89be36653bf6...`): zipfile class scan **0 matches** for `AdminMaintenance|EndpointAdminAuthz|RequireModule|MaintenanceToken` — implementation **fully staged in untracked worktree**, image was built before files added

## File Tag Classification (22 dosya)

| Sprint | Files | Count |
|---|---|---|
| **BE-009** (OpenFGA authz) | EndpointAdminRequireModuleInterceptor + EndpointAdminWebMvcConfig + OpenFgaAuthzConfig + AdminEndpointAuthorizationSecurityTest + EndpointAdminAuthorizationAnnotationTest | 5 |
| **BE-013** (maintenance token) | AdminMaintenanceTokenController + AgentMaintenanceTokenController + 5 DTO + MaintenanceTokenExpiredException + EndpointMaintenanceToken + 2 enum + Repository + Service + V3 SQL + 3 test | 17 |
| **Total** | | 22 |

## Per-File Decision Matrix

**Decision**: All 22 files marked **`commit-ready`** in isolation.

| File category | Verdict |
|---|---|
| Authz interceptor + config (5 files) | `commit-ready` — JWT extract + check + fail-closed + profile-gated DI correct |
| Controllers (2 files) | `commit-ready` — `@RequireModule` annotations match spec, route paths consistent |
| DTOs (5 files) | `commit-ready` — validation constraints + JPA entity alignment |
| Domain (entity + 2 enum + repository + service) | `commit-ready` — UUID PK, optimistic lock, transactional, audit trace, fail-closed pessimistic lock on consume, token hash never logged |
| Flyway V3 migration | `commit-ready` — schema complete, indexes + CHECK constraints + FK |
| Tests (5 files) | `commit-ready` — happy path + denied + drift detection + DB persistence + state machine + audit |

## Route / Annotation / Relation Contract

| Route | Annotation | Live OpenFGA Alignment |
|---|---|---|
| `POST /api/v1/admin/endpoint-devices/{id}/maintenance-tokens` | `@RequireModule(MODULE, MANAGER)` | **Schema mismatch** — code: `endpoint_admin_module`/`manager`, live: `endpoint_admin`/`can_manage` |
| `GET .../maintenance-tokens` | `@RequireModule(MODULE, VIEWER)` | **Schema mismatch** — `viewer` vs `can_view` |
| `GET /api/v1/admin/maintenance-tokens/{tokenId}` | `@RequireModule(MODULE, VIEWER)` | **Schema mismatch** |
| `DELETE /api/v1/admin/maintenance-tokens/{tokenId}` | `@RequireModule(MODULE, MANAGER)` | **Schema mismatch** |
| `POST /api/v1/agent/maintenance-tokens/consume` | None (DeviceCredential auth) | **Correct** (not OpenFGA-gated) |

## DB Migration

V3 Flyway `endpoint_admin_maintenance_tokens.sql` **complete and correct**: UUID PK, tenant_id+device_id+status index, expires_at index, token_hash unique, FK with cascade delete, CHECK constraints on action/status enums.

## Audit / Fail-Closed / Test Coverage

Tüm 5 zorunlu boyut **PASS**:
- ✅ Audit trace: MAINTENANCE_TOKEN_CREATED/CONSUMED/REVOKED/EXPIRED events with subject + tenant + device + before/after status
- ✅ Fail-closed: `@Transactional(noRollbackFor=...)`, pessimistic lock, JWT-missing → 401, OpenFGA-deny → 403
- ✅ Test coverage: allow + deny + unauth + fail-closed (mocked authzService) + DB integration (TestEntityManager)

## Artifact Parity

Image `sha256:89be36653bf6...` zipfile scan: **0 matches** for any of 22 file class names. Implementation untracked, image stale.

## Final Verdict

### `I-staged-pending-schema-rev`

**Justification**:
- Code quality: production-ready in isolation
- DB schema: complete (V3 migration)
- Authz contract: correctly applied annotations
- **Blocking**: OpenFGA schema mismatch — code uses uppercase `ENDPOINT_ADMIN_MODULE` + `manager`/`viewer`, live model uses lowercase `endpoint_admin` + `can_manage`/`can_view`/`can_edit`/`blocked`
- All `@RequireModule` routes will receive HTTP 403 at runtime until schema aligned
- Tests pass because authzService is mocked with hardcoded relation names

**Risk Level**: HIGH — Code ready to commit but deployment will fail with 403 errors.

## Recommendation (1-2 saat fix-forward)

### Adım 1 — Constants update (immediate, sub-branch'e ek commit)

`endpoint-admin-service/src/main/java/com/example/endpointadmin/security/EndpointAdminAuthz.java`:

```java
public final class EndpointAdminAuthz {
  public static final String MODULE = "endpoint_admin";  // was "endpoint_admin_module"
  public static final String MANAGER = "can_manage";       // was "manager"
  public static final String VIEWER = "can_view";          // was "viewer"
  // can_edit + blocked relations gerekirse eklenir
}
```

### Adım 2 — Test update

Mocked relation names in:
- `AdminEndpointAuthorizationSecurityTest.java`
- `EndpointAdminAuthorizationAnnotationTest.java` (reflection-based contract test)

### Adım 3 — Commit + image rebuild + cluster deploy

- Sub-branch'e commit (or new branch + PR to sub-branch)
- platform-backend CI image build → GHCR push
- gitops repo image digest pin update PR (boundary class: `state-mutation (test cluster)` first, then `state-mutation (production)`)
- D29-EA-Functional live smoke (allow/deny/unauth/fail-closed)

### Adım 4 — Faz 22.1.1b → 22.1.1b-live evidence

Once D29-EA-Functional PASS, `docs/faz-22-evidence/<date>-22-1-1b-live-canli.md` ile evidence yazılır; 22.1.1b status `🟢 done` işaretlenir.

### Adım 5 — Faz 23.1 unblock

Faz 22.1.1b → 22.1.1b-live PASS = **Faz 23.1 (notification-orchestrator Kernel) implementation başlangıç onayı**.

## Boundary

**Auto mode'da yapılamaz** (cross-repo write):
- Sub-branch'e constants update commit (`platform-backend` repo write)
- Image build trigger (`platform-backend` CI)
- Sub-branch PR açma (`platform-backend` repo)

Bunlar **`boundary-cross + user-approval-required`** (ADR-0011 §2.3). Kullanıcı explicit confirm gerek.

**Auto mode'da yapılabilir** (gitops repo içi):
- Bu rapor (`docs/faz-22-evidence/2026-05-05-iii-review-report.md`)
- ADR-0011 BG-NOTIFY-1 gate update (Faz 23.0 follow-up)
- Faz 22 sub-faz tracker güncelle (sonraki Faz 22 entry)

## Cross-Reference

- Faz 22 ADR: `docs/adr/0012-EA-endpoint-admin-governance-charter.md`
- Faz 22.1.1 manifest: `docs/RB-22-1-1-be-009-openfga-live.md`
- Faz 23.1 dependency: `docs/runbooks/RB-faz-23-charter.md` §23.1 "Bağımlılık" 🔴 Faz 22.1.1b III review verdict
- 5. verdict state introduced: Codex thread `019df331` Q3 AGREE
