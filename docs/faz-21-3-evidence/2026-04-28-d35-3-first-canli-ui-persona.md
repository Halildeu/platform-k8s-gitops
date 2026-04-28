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

### Step 4 — Granular action retry (post-seed) — pending operator browser

- [ ] Logout / incognito + re-login `d35-admin@example.com`
- [ ] "Yeni Rol" tıkla
- [ ] Beklenen: rol oluşturma form/modal açılır (toast YOK)

## Operator-pending follow-up

Bu evidence module render layer için PASS. Granular action layer için Step 4'ün operator browser sonucu beklenecek; PASS gelirse evidence "FULL PASS" olarak amend edilir, hâlâ fail gelirse fine-grained permission name mapping daha derin araştırılır.

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
| **D35-3 (Product path UI persona)** | **PASS (module render) + pending granular action verify** | **bu dosya** |

D35 ladder **kapanmaya bir adım uzak** — Step 4 operator verify post-seed.

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
