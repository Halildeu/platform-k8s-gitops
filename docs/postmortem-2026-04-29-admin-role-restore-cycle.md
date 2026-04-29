# Postmortem — 2026-04-29 ADMIN Role Restore + permission-service NPE Cycle

> **Status:** Resolved | **Severity:** P2 (browser-only, prod-impact yok) | **Duration:** ~2h | **Codex thread:** 019dd818-dca7-76d0-8bba-6253a00623cd

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
| **THIS PR** | gitops | replicas=1 patch (live drift kapat) + bu postmortem | open |
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

## Open follow-up'lar

| Öncelik | Konu | Owner |
|---|---|---|
| P2 | Frontend silent fallback fix: 401 → "oturum yenile" UX (Codex Q2 + ek concern #4) | TBD frontend-cycle |
| P2 | PermissionDataInitializer null FK hardening + dereference scan (Codex Q3) | TBD backend-cycle |
| P3 | docs/state/current-state.md update (PR #260+#261+#262+#263+THIS) | TBD doc-cycle |
| P3 | Aynı strategy patch pattern diğer scale-1 backend'lere generalize edilebilir mi (Codex iter-1 ek concern #1 follow-up) | TBD |

## References

- Codex thread: 019dd818-dca7-76d0-8bba-6253a00623cd
- backend PRs: #23, #24, #25
- gitops PRs: #260, #261, #262, #263
- DB diff: role_permissions row 123 (SISTEM_Y_NETIMI) + row 124 (REPORTING) DELETE'd
- AuthzVersionService bumps: 21→22 (cache invalidate trigger), 22→23, 23→24
