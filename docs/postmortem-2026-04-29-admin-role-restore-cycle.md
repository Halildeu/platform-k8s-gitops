# Postmortem — 2026-04-29 ADMIN Role Restore + permission-service NPE Cycle

> **Status:** Resolved; P2/P3 follow-up tracked | **Severity:** P2 (browser-only, prod-impact yok) | **Duration:** ~5h | **Codex thread:** 019dd818-dca7-76d0-8bba-6253a00623cd (iter-1 PARTIAL → ... → iter-9 AGREE C kalıcı çözüm)

## TL;DR

Kullanıcı `https://testai.acik.com/admin/access` sayfasında role drawer'da save kontrollerini "passive" / "değiştirme yetkim yok" görüyor. Backend chain doğruydu (admin@example.com → user_id=1, OpenFGA `user:1#admin@organization:default` resolves, `/v1/authz/me` `superAdmin=true` döner) — ama browser **JWT/session expire olmuştu**, frontend stale cache (`superAdmin:false`) ile çalışıyordu, `useZanzibarAccess` 'disabled' döndürüyordu.

Aynı çözüm cycle'ında ortaya çıkan ek bug: 2026-04-28 manuel SQL ile ADMIN role permission restore'u yaparken `permission_id NULL + permission_type+permission_key+grant_type` (Codex S1-S2 granule shortcut model) kullandım. Bu rows `PermissionDataInitializer` startup'taki `rp.getPermission().getCode()` dereference'ında NPE üretti — eski pod 6h53m uptime sürdüğü için sıkıntı çıkmamıştı; yeni image deploy initializer'ı tekrar koşturunca CrashLoopBackOff.

## Timeline (UTC)

- **2026-04-28 ~23:00**: Kullanıcı browser'da role drawer "—" ve save disabled tespiti. ADMIN role 31 permission silindiği için manuel SQL restore (12 MODULE granule eklendi).
- **2026-04-29 06:38**: Manuel SQL inserts tamamlandı (rows 82, 114-124).
- **2026-04-29 06:45**: Kullanıcı feedback "user tarafnda roller geldi ama pasif değiştirmer yetkim. mi yok"
- **2026-04-29 07:00**: Frontend sha-3a0c5f1 + backend diag log image (sha-d58fa61) build + deploy planlanmaya başladı.
- **2026-04-29 07:03**: backend rollout sha-d58fa61 → CrashLoopBackOff (NPE in PermissionDataInitializer).
- **2026-04-29 07:05**: PR #24 fix(null FK tolerance) → image sha-93a2ad6.
- **2026-04-29 07:08**: sha-93a2ad6 cluster Ready ✓
- **2026-04-29 07:14**: Browser user logout/login → `/v1/authz/me` 200 + diag log captured: `numericUserId=1, orgAdmin=true, superAdmin=true` ✓
- **2026-04-29 07:18**: Codex iter-1 PARTIAL review (5 concern + 4 ek bulgu).
- **2026-04-29 07:22**: PR #25 (diag log → DEBUG + email kaldır) merged.
- **2026-04-29 07:24**: gitops PR #262 (strategy patch) + PR #263 (digest pin) + DB cleanup (SISTEM_Y_NETIMI + REPORTING rows DELETE).
- **2026-04-29 07:30**: Codex iter-2 PARTIAL (4 action item: DEBUG env kontrolü, replicas drift, null FK envanter, postmortem guard).
- **2026-04-29 07:35**: Action 1+3 verified, action 2+4 bu PR'da.

## Root cause analizi

**Asıl semptom (kullanıcı feedback'i)**:
- Role drawer save button + checkbox'lar disabled
- "değiştirme yetkim yok" tooltip

**Tek değil çift kök neden:**

1. **Browser auth state stale/eskime** (asıl semptom): JWT/session cookie expire olmuştu. `/api/v1/authz/me` polling'de gateway 401 UNAUTHORIZED dönüyordu. Frontend silent catch yapıp eski `authz` cache'ini kullanmaya devam etti — eski cache'te `superAdmin:false` (önceki bir restorat öncesi state'ten kalma). `useZanzibarAccess('can_edit', 'module', 'ACCESS')` server check'e düştü, server `allowed:false reason:blocked` → access='disabled' → button disabled + tooltip.

2. **Frontend silent fallback UX bug** (yanal kök neden, P2 ürün borcu): 401 (authn unknown) ile `allowed:false reason:blocked` (authz deny) ayrı reason code üretmiyor → kullanıcı "oturum yenile" ile "yetkin yok"u ayırt edemiyor. Bu, asıl semptomun "başka şey" gibi görünmesine yol açtı.

**Yan kök neden** (cycle sırasında ortaya çıktı):
- 2026-04-28 manuel SQL restore'um Codex S1-S2 granule shortcut model (null FK + type+key+grant) kullandı; **PermissionDataInitializer**'ın legacy seed flow'u null FK'yi handle etmiyordu → startup NPE.

## Yapılan düzeltmeler

| PR | Repo | Ne | Sonuç |
|---|---|---|---|
| #260 | gitops | frontend sha-3a0c5f1 pin | merged |
| #23 | backend | /authz/me INFO diag log (PR #25 ile DEBUG'a çekildi) | merged |
| #24 | backend | PermissionDataInitializer null FK tolerance NPE fix | merged |
| #25 | backend | diag log INFO → DEBUG + email kaldır (Codex Q5) | merged |
| #261 | gitops | permission-service sha-93a2ad6 pin | merged |
| #262 | gitops | test overlay rollout strategy patch (maxSurge=0/maxUnavailable=1) | merged |
| #263 | gitops | permission-service sha-149f62e pin | merged |
| #264 | gitops | replicas=1 patch (live drift kapat) + bu postmortem | merged |
| DB cleanup | psql | role_permissions WHERE role_id=2 AND key IN (SISTEM_Y_NETIMI, REPORTING) DELETE 2 rows | done |

## Recurrence guard (manuel SQL restore tekrarını önle)

Bu incident'in tekrar etmemesi için:

### 1. ADMIN/role permission restore SQL pattern (canonical key validation)

Manuel restore yaparken **CANONICAL** modül key kullan. Asla label-derived mangled key kullanma:

```sql
-- DOĞRU canonical key set (PermissionCatalogService.MODULES):
-- USER_MANAGEMENT, ACCESS, AUDIT, REPORT, WAREHOUSE, PURCHASE, THEME

-- YANLIŞ (label-derived mangled):
INSERT INTO role_permissions (role_id, permission_type, permission_key, grant_type)
VALUES (2, 'MODULE', 'SISTEM_Y_NETIMI', 'MANAGE');  -- ✗ "Sistem Yönetimi" Türkçe label-derived

-- DOĞRU canonical:
-- (Yok — "SYSTEM_CONFIGURE" canonical değil; rolün gerçek modül ihtiyacı varsa
--  catalog'a ekleme kararı + canonical key tasarımı + Codex review gerekir)

-- DOĞRU duplicate-aware insert:
INSERT INTO role_permissions (role_id, permission_type, permission_key, grant_type)
SELECT 2, 'MODULE', 'USER_MANAGEMENT', 'MANAGE'
WHERE NOT EXISTS (
    SELECT 1 FROM role_permissions
    WHERE role_id=2 AND permission_type='MODULE' AND permission_key='USER_MANAGEMENT' AND grant_type='MANAGE'
);
```

### 2. Pre-insert validation query

```sql
-- Catalog'da olmayan key'leri detect et
WITH canonical AS (
    SELECT unnest(ARRAY['USER_MANAGEMENT','ACCESS','AUDIT','REPORT','WAREHOUSE','PURCHASE','THEME']) AS key
)
SELECT rp.permission_key, rp.role_id, COUNT(*)
FROM role_permissions rp
WHERE rp.permission_type = 'MODULE'
  AND rp.permission_key NOT IN (SELECT key FROM canonical)
GROUP BY rp.permission_key, rp.role_id;
```

### 3. Codex consensus zorunlu

Manuel restore SQL'i çalıştırmadan önce Codex thread aç + plan göster + AGREE bekle. ADMIN gibi yüksek-impact role'ler ve veri restorat'ları için bu zorunlu.

### 4. Initializer hardening (P2 follow-up — Codex iter-2 Q3)

`PermissionDataInitializer` artık `null Permission FK` skipliyor (PR #24). Ek hardening (Q3 referans):
- Null FK satırlarda `permission_type/permission_key/grant_type` validity check + WARN/ERROR log
- Tüm `getPermission().getCode()` dereference path'lerini scan + null guard

## Önemli observability

- `/v1/authz/me` diag log: DEBUG seviyesinde, default kapalı.
- Aktivasyon: `kubectl set env deploy/permission-service LOGGING_LEVEL_COM_EXAMPLE_PERMISSION=DEBUG`
- Deaktivasyon (incident bitince zorunlu): `kubectl set env deploy/permission-service LOGGING_LEVEL_COM_EXAMPLE_PERMISSION-`

## Open follow-up'lar (Codex iter-9 AGREE C kapsamı sonrası güncel — 12:09)

### ✅ Bu cycle'da kapatıldılar (P1)

| Madde | PR(lar) |
|---|---|
| Frontend silent fallback semantic (Codex Q2) | platform-web #76 (sessionExpired state), #77 (event dispatch + listener), #79 (shell toast/CTA + drawer reason) |
| Pre-existing ESLint cleanup | platform-web #75 (auth pkg), #78 (shell + 2 drawer) |
| Diag log PII guard (Q5) | platform-backend #25 |
| GitOps drift kapatma (replicas+strategy) | platform-k8s-gitops #262, #264 |
| Canonical module key drift (Q4) | DB DELETE 2 row + recurrence guard |
| Recovery via initialData (iter-6 blocker) | platform-web #76 commit deea2780 |

### 📋 Açık P2/P3 borçlar (Codex iter-9 8 maddelik roadmap)

| Öncelik | Madde | Owner |
|---|---|---|
| P2 | PermissionDataInitializer null FK hardening + dereference scan (Codex Q3) | backend-cycle |
| P2 | Canonical module key DB guard (Flyway/CHECK constraint veya restore script validator) | backend-cycle |
| P2 | `registerUnauthorizedHandler` API decision (event sistemi sonrası deprecate/contract) | frontend-cycle |
| P3 | `PermissionProvider.loading` state cleanup | frontend-cycle |
| P3 | `fetchAuthzVersion` 403 davranışı netleştirme | frontend-cycle |
| P3 | `CheckReason` backend integration (Codex: gerek yok) | — |
| P3 | Strategy patch pattern diğer scale-1 backend'lere generalize | gitops-cycle |
| P3 | Force-delete pattern runbook standardization | gitops-cycle |

## References

- Codex thread: 019dd818-dca7-76d0-8bba-6253a00623cd (iter-1..iter-9)
- backend PRs: #23 (diag log), #24 (NPE fix), #25 (DEBUG seviyesi)
- frontend PRs: #75 (auth cleanup), #76 (sessionExpired semantic), #77 (event dispatch + listener), #78 (shell+drawers cleanup), #79 (shell UX + drawer reason)
- gitops PRs: #260, #261, #262, #263, #264, #265, #266
- DB diff: role_permissions row 123 (SISTEM_Y_NETIMI) + row 124 (REPORTING) DELETE'd
- AuthzVersionService bumps: 21→22→23→24

## Codex iter timeline

| iter | Verdict | Konu |
|---|---|---|
| 1 | PARTIAL | 5 concern + 4 ek bulgu absorb |
| 2 | PARTIAL/REVISE | 4 action item (DEBUG kontrolü, replicas drift, null FK envanter, postmortem guard) |
| 3 | AGREE | gitops cycle bitti |
| 4 | PARTIAL/REVISE | A/B reddet → B-prime focused semantic plan |
| 5 | AGREE B | cleanup-first stratejisi |
| 6 | PARTIAL → AGREE | initialData recovery blocker fix |
| 7 | PARTIAL/REVISE-plan | PR-2 → PR-2a + PR-2b ayrım, 7 düzeltme |
| 8 | AGREE B (geçici) | PR-2b stash kararı (kullanıcı sonra "kalıcı çözüm" istedi) |
| 9 | AGREE C | cleanup + PR-2b complete + 8 madde P2/P3 roadmap |

---

## Cycle Phase 2 — Permanent role-definition save/update fix (iter-10..18, 2026-04-29 ~10:00–13:00 UTC)

### Tetikleyici (kullanıcı semptomu)

> "rol tanımlama kaydetme güncellme mevcut kaydı açtığında içeirğin doğrolmamaıs sorunu" — kaydedilen role drawer'a tekrar açıldığında yanlış içerik göründüğü kalıcı sorun.

Phase 1 (iter-1..9) auth/cache yüzeyini kapattı; Phase 2 ise **role permission persistence** layer'ını kalıcı çözmeye odaklandı. Kullanıcı **"uzun vadeli kalıcı çözüm hangisi"** ve **"test yazamısın doğru çalışı çalışmadığını kontorlo için"** soruları cycle'ı başlattı.

### 3 ayrı root cause — 3 ayrı entry point

| # | Layer | Root cause | Fix |
|---|---|---|---|
| **R1** | Read path | `permissions.module_name` Türkçe label drift'i (`Kullanıcı Yönetimi`, `Sistem Yönetimi`, `Audit`, `reporting`, vs.) ile `byModule` grouping mangled key üretiyordu — drawer'a stale label dönüyor | `ModuleNameCanonicalizer` 9 mapping (Plan A+) + V14 migration |
| **R2** | Write path | `AccessControllerV1.updateRoleGranules` JPQL `@Modifying DELETE` (`rolePermissionRepository.deleteByRoleId`) + ardından `rolePermissionRepository.save(rp)` + `roleRepository.save(role)` cascade=ALL pattern'i kullanıyordu. Bulk DELETE persistence context'i bypass ediyor; `save(role)` cascade-persist ile `role.rolePermissions` koleksiyonundaki **eski entity'leri** DB'ye yeniden insert ediyordu — kullanıcı VIEW yazmasına rağmen 4 row (1 yeni granule + 3 cascade-resurrected eski FK) kalıyor, drawer eski FK code'ları üzerinden MANAGE türetiyordu | Aggregate-native replace: `Role.clearRolePermissions()` + `Role.addRolePermission(rp)` (Plan B) — orphanRemoval=true + cascade=ALL tek persistence context içinde, bulk DML yok |
| **R3** | Boot path | `PermissionDataInitializer` granule-blind: row varlığına bakmadan `DEFAULT_ROLE_PERMISSIONS` üzerinden FK rows seed ediyordu. V14/V15 cleanup migration'ları doğru çalıştı ama aynı startup'ta initializer 47 mixed FK row'u tekrar insert etti → V15 success log'undan sonra mixed state geri geldi | `PermissionDataInitializer.usesGranuleModel()` granule-aware skip (Plan A iter-14) + V16 cleanup re-run + iter-16 `roles.permission_model` marker + iter-17 marker-OR-row-shape predicate parity |

### Yapılan düzeltmeler — 4 PR + 4 migration

| PR | Repo | iter | Konu | Sonuç |
|---|---|---|---|---|
| #26 | backend | 12 | Plan A+ — `ModuleNameCanonicalizer` 9 mapping + `AccessRoleService` byModule canonicalize + V14 migration | merged |
| #27 | backend | 12 | `ModuleNameCanonicalizerTest` 14 + `AccessRoleServiceTest` 4 yeni | merged |
| #28 | backend | 13 | Plan B — `Role.clearRolePermissions()` + `Role.addRolePermission()` aggregate-native helpers + `AccessControllerV1.updateRoleGranules` cascade-resurrect fix + V15 cleanup | merged |
| #29 | backend | 13 | `RoleAggregateHelpersTest` 3 + `AccessControllerV1UpdateRoleGranulesTest` 3 | merged |
| #30 | backend | 14 | Plan A iter-14 — `PermissionDataInitializer.usesGranuleModel()` skip + V16 cleanup re-run + `PermissionDataInitializerGranuleAwareTest` 5 | merged |
| #31 | backend | 16+17 | Plan C closure — V17 `roles.permission_model` enum marker + `AccessControllerV1.updateRoleGranules` flips marker + legacy endpoints 409 + `RolePermissionRepository.existsGranuleShapeByRoleId` drift guard + 13 yeni test | merged |

**Toplam migration zinciri**: V14 (label canonicalize) → V15 (mixed cleanup) → V16 (post-initializer cleanup re-run) → V17 (permission_model marker + GRANULE backfill).

**Toplam regresyon kapsamı**: 58/58 PASS (14 ModuleNameCanonicalizerTest + 20 AccessRoleServiceTest + 3 RoleAggregateHelpersTest + 3 AccessControllerV1UpdateRoleGranulesTest + 7 PermissionDataInitializerGranuleAwareTest + 7 AccessControllerV1LegacyWriteRejectionTest + 3 AccessControllerV1Test + 1 FlywayMigrationTest).

### Live evidence (PR #30 / sha-9610fbd post-deploy, 12:08)

- V16 auto-applied: `Successfully applied 1 migration to schema "public", now at version v16 (execution time 00:00.078s)`
- 11 granule role skip log: `Role X uses granule shortcut model — skipping legacy FK seed` (ROLE_MANAGE, ADMIN, WAREHOUSE_OPERATOR, FINANCE_MANAGER, SYSTEM_CONFIGURE, AUDIT_READ, USER_VIEWER, REPORT_VIEWER, USER_MANAGE, REPORT_MANAGER + ADMIN dup)
- DB query: 0 mixed FK rows across all 16 roles (V15+V16 success ✓)
- USER_MANAGE row count: 1 granule (`MODULE | USER_MANAGEMENT | VIEW | permission_id NULL`) — kullanıcı save'iyle birebir
- Legacy FK-only roles korundu: PURCHASE_MANAGER, FINANCE_VIEWER, PERMISSION_MANAGE, USER_MANAGER, VARIANT_SCOPE_CANARY, FULL_ACCESS_EXTRA (6 role)
- authzVersion bump: 35 → 36 (frontend cache invalidate)

### Detection gap (Phase 2'nin asıl maliyeti)

Phase 1 cycle'ında initializer NPE `PermissionDataInitializer` log'larıyla anında belli oldu. Phase 2'de ise mixed FK + granule state **silently** birikti — V15 migration logları success diyor, fakat kullanıcının drawer'ı hâlâ yanlış içerik gösteriyor. **Detection layer yoktu**:

- Mixed roles count metric yok
- Marker drift metric yok
- Initializer skip log'u DEBUG seviyesinde (varsayılan kapalı), yalnız ad-hoc enable edilince görülüyor
- Frontend authzVersion bump yapsa bile cache invalidate gerçek state'i değil eski API response'unu yansıtıyordu

**Bu açık iter-18 follow-up'larda kapatılacak** (aşağıdaki "Açık P2/P3 borçlar" tablosu).

### Codex iter timeline (Phase 2)

| iter | Verdict | Konu |
|---|---|---|
| 10 | AGREE | Plan A+ canonicalize + Plan B cascade-resurrect investigation green-light |
| 11 | PARTIAL | byModule grouping fix scope tightening |
| 12 | AGREE | Plan A+ + V14 ship plan |
| 13 | AGREE | Plan B aggregate-native ship plan + V15 |
| 14 | AGREE | Plan A iter-14 boot-path skip + V16 (after V15 mixed-state regression) |
| 15 | REVISE | "complete cycle" iddiasını sorguluyor: empty granule role + legacy endpoints 2 closure açığı |
| 16 | PARTIAL | Plan C — V17 permission_model marker + endpoint 409 guards (delivered in PR #31) |
| 17 | PARTIAL | CI break (LEGACY stub) + predicate parity (legacy rejection marker-only kalmış) |
| 18 | **AGREE** | Cycle CLOSED. PR #31 tüm closure açıklarını kapatıyor. 3 follow-up blocker olmadan kayda geçti |

### Phase 2 P1 closed (5 madde)

| Madde | PR/Migration |
|---|---|
| Read-path label drift kalıcı fix (canonicalize) | #26 + V14 |
| Write-path cascade-resurrect kalıcı fix (aggregate-native) | #28 + V15 |
| Boot-path granule-blind seed kalıcı fix (skip) | #30 + V16 |
| Empty granule role boot regression (marker) | #31 + V17 |
| Legacy endpoint mixed-state vector (409 + drift guard) | #31 |

### Phase 2 açık follow-up'lar (3 spawn task chip — non-blocker)

| Öncelik | Madde | Spawned |
|---|---|---|
| P2 | `cloneRole` granül kaynağı klonlarken `permissionModel`'i source'tan kopyala (drift metric noise + clone marker tutarlılığı) | ✓ chip 1 |
| P2 | `RolePermissionRepository.deleteByRoleId` için ArchUnit guard (production code'da tekrar kullanılmasın) | ✓ chip 2 |
| P1 (hazırlık) | `role_permissions_mixed_roles_count` + `marker_drift_count` + `empty_granule_count` metric + Prometheus alert | ✓ chip 3 |

### Recurrence guard — Phase 2 lessons

1. **Persistence boundary invariant**: bir role `role_permissions` tablosunda ya FK-only ya granule-only model'inde olmalı. Mixed state V15/V16/V17 tarafından sürekli temizlenir; future writer'lar bu invariant'ı korumalı.
2. **Marker source of truth**: `roles.permission_model` enum'u role-level mode için authoritative. Initializer ve write boundary aynı predicate (marker OR row-shape) kullanıyor; sapma test'lerle kilitli.
3. **JPQL bulk DML + cascade collection ilişkisi**: `@Modifying DELETE` + `save(aggregate)` pattern'i deterministically cascade-resurrect bug üretir. Aggregate-native helpers (`clear()` + `add()`) JPA orphanRemoval ile doğru DB I/O yapar.
4. **Codex adversarial review**: 18 iter sürdü çünkü her root-cause katmanı bağımsız ortaya çıktı (V15 success → kullanıcı drawer hâlâ yanlış → initializer dökümanı oku → empty replace edge case → ...). Plan-time ve post-impl review iki ayrı kapı; iter-15'in REVISE'i empty granule + legacy endpoints açığını yakalamasaydı cycle "closed" sanılıp tekrar açılacaktı.

### References (Phase 2)

- Codex Phase 2 thread: `019dd818-dca7-76d0-8bba-6253a00623cd` (Phase 1 base) → `019dd927-bf5f-7900-ba49-ff701a32c199` (Phase 2 retrospective iter-15..18)
- Backend PRs: #26 (canonicalizer), #27 (canonicalizer tests), #28 (aggregate-native), #29 (Plan B tests), #30 (initializer skip + V16), #31 (Plan C marker)
- Migrations: V14, V15, V16, V17
- AuthzVersionService bumps (Phase 2): 34 → 35 → 36
