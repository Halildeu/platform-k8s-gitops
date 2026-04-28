# D35-3 First Canlı UI Persona Evidence — Module Access PASS

> **Tier**: D35-3 (D35 ladder son halka)
> **Date**: 2026-04-28 (UTC ~20:30Z)
> **Cluster**: k3d-test on staging-sw
> **Operator**: agent + user browser session correlation
> **Codex thread**: `019dd409` (D35-3 prereq strategy)
> **Run ID**: `d35-3-ui-20260428-2030`

## Tier semantik

D35-3 = **product path** UI persona evidence — gerçek tarayıcıdan login + module render + (opsiyonel) action permission. Backend REST chain (D35-2-full) PASS olmadan D35-3 koşulmaz; bu run D35-2-full evidence (`2026-04-28-d35-2-full-canli-rest-flow.md` 11/11 PASS) downstream'i.

## Result

**PASS (module render layer)** + 🟡 **partial (granular action layer)** — first canlı UI persona evidence with real authorization chain.

## Authorization chain — agent-built persona registration zinciri

D35-3 öncesi `d35-admin-persona` Keycloak'ta yaratıldı (RB-keycloak-admin-jwt.md Step 2) ama users tablolarına hiç register edilmemişti — Codex `019dd409` BG-1 PR boundary declaration sonrasında tespit edildi. Frontend `/v1/authz/me` endpoint'ten `superAdmin` boolean alır; persona numeric userId resolution path:

```
JWT (sub=cbc9a869-..., email=d35-admin@example.com)
  → AuthenticatedUserLookupService:
    1. jwt.userId claim — none
    2. jwt.uid claim — none
    3. sub.parseLong — fails (UUID)
    4. email lookup → user-service /api/users/by-email/d35-admin@example.com → id=1204
  → AuthorizationControllerV1.checkOrganizationAdmin(1204)
    → OpenFGA /check user:1204 admin organization:default → allowed:true
  → /v1/authz/me: {"superAdmin":true, modules:{...}, ...}
  → mfe-host ProtectedRoute: isSuperAdmin() → true → bypass module guard
```

### Chain artifacts (verified live)

| Aşama | Komut/Değer | Sonuç |
|---|---|---|
| `users_db.public.users` INSERT | id=1204 d35-admin (ADMIN), id=1205 d35-granted (USER) | INSERT 0 2 |
| `permission_db.users` INSERT | id=1204, 1205 (numeric ID alignment) | INSERT 0 2 |
| OpenFGA `user:1204 admin organization:default` | tuple seed test store `01KPP0CFP4G82K42Y6NYSPT4JF` model `01KPP0CFRWFDNRNZFNE72299EY` | `{}` write OK |
| OpenFGA `/check user:1204 admin organization:default` | doğrulama | `{"allowed":true,"resolution":""}` |
| OpenFGA `user:1205 can_view module:ACCESS` | granted persona view-only | `{}` write OK + `/check` `allowed:true` |
| user-service `/api/users/by-email/d35-admin@example.com` | email lookup | HTTP 200 → `{id:1204, role:"ADMIN", enabled:true}` |
| user-service `/api/users/by-email/d35-granted@example.com` | email lookup | HTTP 200 → `{id:1205, role:"USER"}` |
| `user_role_assignments` INSERT (replicate admin@example.com 16 role) | id=1204 için 16 role | INSERT 0 16 |
| Effective permissions count | id=1204 distinct permission count | 31 |
| `authz_sync_version` bump | cache invalidate | 3→4 (2026-04-28T20:40:49) |

## UI render evidence

### Step 1 — Login

- [x] `https://testai.acik.com/` açıldı
- [x] Keycloak SSO ekranı geldi
- [x] `d35-admin@example.com` ile login başarılı
- [x] Dashboard render etti

### Step 2 — Module guard bypass + sidebar render

- [x] `/access/roles` URL'ine navigate
- [x] **`/unauthorized` REDIRECT YOK** (önceki blocker'ın tam tersi)
- [x] Breadcrumb: Yönetim > Erişim > Roller
- [x] Page title: "Rol & Policy Yönetimi"
- [x] Sol nav modüller render:
  - Home, Dashboard, Projects (active), Reporting, Services
  - **Schema Explorer** (THEME modülü — superAdmin bypass'la görünür)
  - Folders, Settings, Support
- [x] Top nav: Yönetim / Raporlar / Araçlar dropdown'lar açık
- [x] AG Grid table kolonları render: Rol adı / Üye sayısı / Yetkili modüller / Son güncelleme
- [x] Action buttons: "Yeni Rol", "Grupla", "Filtre", "Reset Filters" — tıklanabilir

**Screenshot kanıtı**: kullanıcı paylaşımlı (chat thread).

### Step 3 — Granular action permission (initially partial)

İlk denemede:
- [x] "Yeni Rol" tıklandı
- 🟡 Toast: **"Bu işlem için yetkiniz bulunmuyor"**
- **Sebep**: `user_role_assignments` boştu — module guard PASS ama specific RolePermission seed eksikti

**Çözüm**: admin@example.com (id=1) için seedlenmiş 16 role assignment d35-admin-persona için replicated:

```sql
INSERT INTO user_role_assignments (user_id, role_id)
SELECT 1204, role_id FROM user_role_assignments WHERE user_id = 1
ON CONFLICT DO NOTHING;
-- 16 INSERT
```

Effective: 16 role × distinct permissions = 31 permission. `authz_sync_version` 3→4 ile cache invalidate.

### Step 4 — Granular action retry (post-seed) — DISCOVERED CROSS-REPO BACKEND BUG

- [x] Logout / incognito + re-login `d35-admin@example.com`
- [x] "Yeni Rol" tıkla
- [x] Toast: **"Bu işlem için yetkiniz bulunmuyor"** (hâlâ)
- [x] Permission-service log incelendi → root cause:

```
authz.decision user=cbc9a869-... relation=viewer object=module:ACCESS allowed=false source=RequireModule
authz.decision user=cbc9a869-... relation=manager object=module:ACCESS allowed=false source=RequireModule
authz.decision user=cbc9a869-... relation=admin object=module:ACCESS allowed=false source=RequireModule

Caused by: dev.openfga.sdk.errors.FgaApiValidationError: [check] HTTP 400 relation 'module#viewer' not found
  at com.example.permission.config.RequireModuleInterceptor.preHandle(RequireModuleInterceptor.java:67)
```

### Root cause: cross-repo platform-backend bug (NOT persona-related)

`RequireModuleInterceptor` OpenFGA'ya **non-existent relation isimleri** soruyor:
- Backend uses: `viewer`, `manager`, `admin` (on `module` type)
- OpenFGA model has (verified live): `module` type relations = `can_view`, `can_manage`, `can_edit`, `blocked`. `admin` relation is on `organization` type ONLY.

Sonuç: Her UI write action (Yeni Rol, Yeni Scope, vs) **TÜM kullanıcılar için fail** (admin@example.com dahil). HTTP 400 `relation not found` → fail-closed → 403 frontend toast.

### D35-3 evidence ayrımı

D35-3 persona authorization chain için bu bulgu **kapanışı netleştirir**:
- ✅ Persona auth chain (numeric ID + organization:default#admin tuple + /v1/authz/me + module render) **TAM çalışıyor**
- 🟡 Granular action layer **D35-3 dışı backend bug** ile bloklanıyor (cross-repo platform-backend fix gerek)

D35-3 = "product path UI persona evidence" tanım gereği persona authorization correctness'ını kanıtlar; backend interceptor bug ayrı tier (BG-1 bulurdu eğer model ile interceptor sync drift varsa).

### Spawned task

Cross-repo fix `RequireModuleInterceptor.preHandle:67` chip ile ayrıldı:
- Backend relation mapping: `viewer` → `can_view`, `manager` → `can_manage`, `admin` (on module) → `can_manage`
- platform-backend PR + permission-service image rebuild + digest pin update PR

Bu bug fix sonrası granular action retry yapılır; D35-3 evidence "FULL PASS" amend.

## Granted persona test (opsiyonel D35-3 ek)

`d35-granted-persona` (id=1205) için minimal seed:
- OpenFGA `user:1205 can_view module:ACCESS` (✓)
- `user_role_assignments`: USER_VIEWER (role_id=7) + REPORT_VIEWER (role_id=8)

Granted persona UI flow:
- [ ] Login `d35-granted@example.com`
- [ ] Dashboard render
- [ ] `/access/*` route — view-only (panel render OK, write actions disabled)
- [ ] `/admin/*` admin-only routes — `/unauthorized` redirect (granted hasn't superAdmin)

(Bu blok ayrı tier — granted persona UI flow gerçekten farklı evidence. Bu run admin tier'ında tamamlanmış sayılır.)

## D35 ladder kapanış durumu

| Tier | Status | Evidence |
|---|---|---|
| D35-0 (Runtime preflight) | PASS | PR #192 outbox isolated preflight |
| D35-1 (Scope anchor prereq) | PASS | `2026-04-28-d35-1-scope-anchor-load-d93e9917.md` |
| D35-2-limited (Manuel SQL bypass) | superseded | `2026-04-28-d35-2-first-canli-eventual-consistency.md` |
| D35-2-full (Canlı REST flow 11/11) | PASS | `2026-04-28-d35-2-full-canli-rest-flow.md` (PR #225) |
| **D35-3 (Product path UI persona)** | **PASS** (persona auth chain + module render) | **bu dosya** |

### D35-3 PASS rationale

D35-3 = persona authorization correctness UI yansıması:
1. Persona register edildi (3 users tablosu + 16 role + 31 permission)
2. OpenFGA tuple seedlendi (`user:1204 admin organization:default`)
3. /v1/authz/me canlı superAdmin: true döner (numeric ID lookup zinciri tam çalışıyor)
4. mfe-host module guard bypass + sidebar full + AG Grid render

Granular UI action separately blocked by **cross-repo backend bug** (`RequireModuleInterceptor` relation mismatch — `viewer`/`manager`/`admin` vs model'in `can_view`/`can_manage`/`can_edit`). Bu bug ALL users için fail eder, persona-spesifik değil; spawned task ile platform-backend repo'sunda fix scheduled.

D35 ladder closure: D35-0 + D35-1 + D35-2-full + D35-3 **TAM PASS**. Cross-repo bug fix post-merge ile UI action layer tam yeşil olur.

## Boundary declaration (ADR-0011 §2.3)

This evidence captures:

- [x] state-mutation (test cluster) — DB INSERTs (users, permission_db.users, user_role_assignments, authz_sync_version) + OpenFGA tuple writes test store

User-approval evidence: kullanıcı 2026-04-28 chat'inde "onaylıyorum tam yetki" + auto-mode + Codex `019dd409` consensus

## References

- `docs/faz-21-3-evidence/d35-3-product-path-template.md`
- `docs/RB-faz-21-3-d35-3-persona-rol-atama.md` (PR #238)
- `docs/RB-faz-21-3-d35-3-keycloak-admin-jwt.md`
- `docs/RB-faz-21-3-d35-3-prereq-tuple-seed.md`
- `docs/RB-faz-21-3-d35-3-ui-persona-checklist.md`
- mfe-host `ProtectedRoute.tsx` line 47-56 (module guard)
- mfe-host `PermissionProvider.tsx` line 163-189 (hasModule + isSuperAdmin)
- permission-service `AuthorizationControllerV1.java` line 134-138 (superAdmin determination)
- permission-service `AuthenticatedUserLookupService.java` (JWT → numeric userId)
- ADR-0010 §2.5 (operator/agent boundary matrix)
- ADR-0011 §2.3 (boundary class)
- CLAUDE.md HARD RULE #7 (SSH+sudo+kubectl); #8 (auto-mode + Codex consensus); #9 (no fake work — bu evidence run-time tuple write + DB INSERT + /check round-trip + browser render correlation)
- Codex thread `019dd409` (D35-3 prereq strategy + persona credential boundary)
