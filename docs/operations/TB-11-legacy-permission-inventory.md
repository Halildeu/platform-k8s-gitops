# TB-11: Legacy References TO Permission-Service — Inventory (FROZEN)

Date: 2026-04-11
Status: FROZEN (Dalga 4 ön koşulu — bu envanterdeki itemler temizlenecek)
Ref: CNS-20260411-003 Q4, zanzibar-master-plan.md rev 6

> **Kapsam netliği:** Bu envanter, **permission-service'e bağlı eski client'ları** (auth-service
> `PermissionServiceClient`, `PermissionCodes` tüketicileri, legacy `/api/permissions` route) listeler.
> Permission-service'in kendisi **KALDIRILMAZ** — OpenFGA Hub (D-003/D-008 FINAL, C-005 HARD CONSTRAINT).
> Temizlenecek olan, servislerin permission-service'e yaptığı **HTTP check çağrıları**
> (D-008/C-008 ile OpenFGA SDK'ya taşınır), permission-service'in kendisi değildir.

## 1. PermissionServiceClient (2 servis, 9 referans — Codex F3 sonrası güncel)

| Servis | Dosya | Satır | Tür |
|--------|-------|-------|-----|
| auth-service | permission/PermissionServiceClient.java:30 | Class tanımı (HTTP → /authz/me migrated) | KAYNAK |
| auth-service | service/AuthService.java:22,41,52 | Import + field + constructor | TÜKETİCİ |
| auth-service | service/AuthServiceTest.java:7,51 | Test mock | TEST |
| auth-service | service/AuthServiceSessionAuditTest.java:39,58 | Test mock | TEST |
| ~~user-service~~ | ~~permission/PermissionServiceClient.java~~ | **SİLİNDİ (CNS-20260414-003 F3: dead code, 0 consumer)** | — |
| report-service | authz/PermissionServiceClient.java:24 | Class tanımı (aktif WebClient, 3 controller tüketiyor) | KAYNAK |

**Eylem:**
- PR6-prereq (post-canary, CNS-20260414-003 Q1): auth-service scope — `AuthService.java:83` çağrısı `Set.of()` kompat ile kısa devre + class stub (breaking drop yerine). Detay: JWT claim + downstream consumer temizliği PR6b'ye, report-service cleanup PR6c'ye ayrıldı.
- ~~user-service~~: Codex F3'te doğrulandı — class tamamen dead code (Spring @Component register ediliyor ama hiçbir yerden inject edilmiyor, test yok). **SİLİNDİ — ayrı PR gerekmedi.**

## 2. PermissionCodes (1 kaynak, 37 tüketici referans)

| Servis | Dosya | Referans Sayısı | Tür |
|--------|-------|-----------------|-----|
| common-auth | PermissionCodes.java:17 | Class tanımı (27 constant) | KAYNAK |
| core-data-service | CompanyController.java | 4 referans | TÜKETİCİ |
| core-data-service | CompanyControllerSecurityTest.java | 8 referans | TEST |
| variant-service | VariantController.java | 7 referans | TÜKETİCİ |
| variant-service | VariantControllerV1.java | 8 referans | TÜKETİCİ |
| variant-service | ThemeController.java | 2 referans | TÜKETİCİ |
| variant-service | VariantAuthorizationServiceImpl.java | 4 referans | TÜKETİCİ |
| variant-service | VariantService.java | 2 referans | TÜKETİCİ |
| variant-service | VariantSecurityIntegrationTest.java | 4 referans | TEST |
| common-auth | AuthorizationContextBuilderTest.java | 1 referans | TEST |

**Eylem:** PR6 — deprecated cleanup (class silinecek, tüketiciler OpenFGA check'e migrate)

## 3. Eski /api/permissions Endpoint (3 referans)

| Dosya | Satır | Tür |
|-------|-------|-----|
| PermissionController.java:17 | @RequestMapping("/api/permissions") | KAYNAK (deprecated) |
| application.properties:39 | Gateway route /api/permissions/** | ROUTING |
| PermissionServiceClient.java:43 | /api/permissions/assignments çağrısı | TÜKETİCİ |

**Eylem:** PR6-prereq + PR6

## 4. useAuthorization (Frontend Legacy, 6 dosya)

| App | Dosya | Tür |
|-----|-------|-----|
| @mfe/auth | compat.ts:46 | Compat wrapper (KAYNAK) |
| @mfe/auth | index.ts:24 | Export | 
| mfe-users | use-authorization.model.ts:16 | Local tanım | 
| mfe-users | UserActions.ui.tsx:6,18 | TÜKETİCİ |
| mfe-users | UserDetailDrawer.ui.tsx:6,58 | TÜKETİCİ |
| mfe-shell | use-authorization.model.ts:4 | Local tanım |
| mfe-shell | use-authorization.model.test.tsx:6,23,33 | TEST |

**Eylem:** PR7 — mfe-users useAuthorization → usePermissions

## 5. Deprecated Controller'lar (2)

| Dosya | Annotation |
|-------|-----------|
| AccessController.java:18 | @Deprecated(since = "v1 endpoints added; use /api/v1/roles") |
| PermissionController.java:18 | @Deprecated(since = "v1 endpoints added; use /api/v1/permissions") |

**Eylem:** PR6 — silinecek (v1 endpoint'ler aktif)

## 6. Deprecated Enum Değerleri (2)

| Dosya | Değer |
|-------|-------|
| PermissionType.java:13 | @Deprecated PAGE |
| PermissionType.java:15 | @Deprecated FIELD |

**Eylem:** PR6

## 7. ConstantAuthzVersionProvider (1)

| Dosya | Not |
|-------|-----|
| scope/ConstantAuthzVersionProvider.java:8 | Hiç kullanılmıyor (0 tüketici) |

**Eylem:** PR6 — silinecek

## ÖZET

Durum 2026-04-14 (Codex F3 uygulamasından sonra):

| Kategori | Kaynak | Tüketici | Test | Toplam |
|----------|--------|----------|------|--------|
| PermissionServiceClient | 2 | 3 | 4 | 9 |
| PermissionCodes | 1 | 27 | 13 | 41 |
| /api/permissions | 1 | 1 | 0 | 2 |
| useAuthorization | 3 | 2 | 2 | 7 |
| Deprecated controllers | 2 | 0 | 0 | 2 |
| Deprecated enums | 2 | 0 | 0 | 2 |
| ConstantAuthzVersionProvider | 1 | 0 | 0 | 1 |
| **TOPLAM** | **12** | **33** | **19** | **64** |

Not: PR6-prereq (auth-service) uygulandıktan sonra beklenen sayım: Kaynak 1, Tüketici 2, Test 2, Toplam 5. Codex F2 projeksiyonu: `65→57` frozen tablo baz alınmıştı; güncel baz (user-service silindikten sonra) için hedef `64→57` olarak kalıyor.

## PR MAPPING

Güncel (CNS-20260414-003 sonrası, FAZ B revize zinciri):

| PR | Temizlenecek Kategoriler | Dosya Sayısı | Durum |
|----|-------------------------|-------------|-------|
| PR5 | (bağımsız — propagateRoleChange) | 0 legacy | Done |
| — | user-service PermissionServiceClient (dead code F3) | 1 | **Done (this PR)** |
| PR6a | auth-service PermissionServiceClient — `Set.of()` kompat | ~6 dosya | Post-canary |
| PR6b | JWT `permissions` claim + downstream consumer (user/variant) | ~4 dosya | Post-canary |
| PR6c | report-service PermissionServiceClient → OpenFgaAuthzService | ~4 dosya | Post-canary |
| PR7 | useAuthorization (mfe-users) | ~5 dosya | Bağımsız |
| PR6 | PermissionCodes + deprecated controllers + enums + ConstantAuthzVersionProvider | ~20 dosya | PR6a-c sonrası |
| PR8 | (bağımsız — Grafana) | 0 legacy | Bağımsız |

**Refs:**
- CNS-20260414-003: scope bölme gerekçesi (Q4, F3)
- Codex verdict: FAZ B post-canary (Q1) — canary 48h monitor penceresinde auth-service refactor sinyali kirletmez
