# DOMAIN-MAP

## Amaç

Bu doküman, aktif bounded context'leri ve bunların hangi servis ve istemci
bileşenleri ile temsil edildiğini gösterir.

Detaylı inceleme için:
- `docs/02-architecture/INDEX.md`

## Aktif Domainler

### 1. Kimlik ve Oturum

Sorumlu bileşenler:
- `auth-service`
- Keycloak
- `common-auth`

Sorumluluk:
- kullanıcı oturumu
- registration ve password reset
- service token minting ve service JWKS

### 2. Yetki ve Denetim

Sorumlu bileşenler:
- `permission-service`
- `mfe-access`
- `mfe-audit`

Sorumluluk:
- roles (CRUD)
- permissions (catalog, CRUD)
- authz scope (company/project/warehouse/branch assignment)
- audit event
- **OpenFGA Hub** (D-003/D-008 FINAL, 2026-04-14):
  - TupleSyncService: role → OpenFGA tuple sync (deny-wins resolution)
  - AuthzVersionService: cache invalidation version management
  - TupleSyncOutboxPoller: durable retry (SELECT FOR UPDATE SKIP LOCKED)
  - AuthorizationControllerV1: `/authz/me`, `/authz/check`, `/authz/batch-check`,
    `/authz/explain`, `/authz/version`, `/authz/catalog`, `/authz/modules`

Not:
- Bu domain şu an geniş bir kapsama sahiptir ve ileride bölünme adayıdır.
- **Permission-service kaldırılamaz** (C-005 HARD CONSTRAINT) — OpenFGA sistemi bozulur.
- Diğer servisler **check işlemleri için permission-service'e HTTP çağrısı yapmaz**;
  `OpenFgaAuthzService` (common-auth) üzerinden doğrudan OpenFGA'ya erişir (C-008).

### 3. Kullanıcı Yönetimi

Sorumlu bileşenler:
- `user-service`
- `mfe-users`

Sorumluluk:
- kullanıcı CRUD
- aktivasyon
- internal provisioning
- bazı profil/tercih alanları

### 4. Kişiselleştirme ve Tema

Sorumlu bileşenler:
- `variant-service`
- `mfe-reporting`
- `packages/ui-kit`

Sorumluluk:
- grid variant
- görünüm tercihleri
- tema
- theme registry

Not:
- Theme alanı şu an ayrı servis değil, `variant-service` içine gömülü durumdadır.

### 5. Referans Veri

Sorumlu bileşenler:
- `core-data-service`

Sorumluluk:
- company master data

### 6. Edge ve Platform Yönlendirme

Sorumlu bileşenler:
- `api-gateway`
- `discovery-server`

Sorumluluk:
- giriş noktası
- route yönlendirme
- servis keşfi

### 7. Sunum Katmanı

Sorumlu bileşenler:
- `mfe-shell`
- remote MFE'ler
- `packages/shared-http`
- `packages/ui-kit`

Sorumluluk:
- route
- auth lifecycle
- ortak UI
- ortak HTTP istemcisi

## Planlı Ama Henüz Runtime'da Ayrışmamış Alanlar

- `approval-system`
- `ethics-case-management`
- `theme-system`
- `fleet-operations`
- `ops`

Bu alanlar doküman veya ürün niyeti seviyesinde görünür; fakat çalışan backend
servisi olarak sabitlenmiş değildir.

## Domain İlişki Özeti

- Kimlik ve Oturum → tüm backend servislerinin auth temelidir.
- Yetki ve Denetim → kullanıcı ve tema dahil birçok alan tarafından tüketilir.
- Kullanıcı Yönetimi → auth ve permission alanı ile sıkı bağlıdır.
- Kişiselleştirme ve Tema → reporting ve UI davranışı ile doğrudan ilişkilidir.
- Referans Veri → diğer domainler için ortak ana veri kaynağı olmaya adaydır.

## Sonuç

Yeni geliştirme, önce bu domain haritası üzerinde konumlandırılmalı; daha sonra
servis, API ve UI modülü kararı verilmelidir.
