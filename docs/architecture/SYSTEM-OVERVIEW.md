# SYSTEM-OVERVIEW

## Amaç

Bu doküman, sistemin yüksek seviye mimarisini kısa ve kararlı bir özet halinde
sunmak için kullanılır.

Detaylı as-is analiz için:
- `docs/02-architecture/INDEX.md`

## Sistem Özeti

Sistem iki ana çalışma alanından oluşur:
- `backend/` → Spring Boot tabanlı mikroservis katmanı
- `web/` → React + Module Federation tabanlı mikro frontend katmanı

Ortak akış:
- Tarayıcı → `mfe-shell` ve remote MFE'ler
- Frontend → `api-gateway`
- Gateway → Eureka discovery
- Discovery → ilgili backend servisi
- Servisler → PostgreSQL, Keycloak, Vault

## Aktif Backend Bileşenleri

- `api-gateway`
- `discovery-server`
- `auth-service`
- `user-service`
- `permission-service`
- `variant-service`
- `core-data-service`
- `common-auth`

## Aktif Frontend Bileşenleri

- `mfe-shell`
- `mfe-users`
- `mfe-access`
- `mfe-audit`
- `mfe-reporting`
- `mfe-ethic`
- `mfe-suggestions`
- `packages/ui-kit`
- `packages/shared-http`

## Temel Mimari Kurallar

- Tarayıcı yalnız gateway ile konuşur.
- Servisler arası çağrı discovery/load-balancer üzerinden yapılır.
- Kullanıcı auth kaynağı Keycloak'tur.
- İç servis auth akışında `auth-service` service token minting rolü taşır.
- UI tarafında ortak HTTP katmanı `packages/shared-http`, ortak bileşen katmanı
  `packages/ui-kit` üzerinden ilerler.

## Kritik Gerçekler

- Kod tabanı gerçekte mikroservistir.
- `permission-service` **OpenFGA Hub** rolünü üstlenir (D-003/D-008 FINAL, 2026-04-14): TupleSyncService (rol→OpenFGA tuple senkronu), AuthzVersionService (cache invalidation), AuthorizationControllerV1 (`/authz/me`, `/authz/check`, `/authz/explain`), AccessControllerV1 (rol CRUD). Port 8090 aktif — kaldırılmamış, dönüştürülmüştür.
- `variant-service` hem variant hem tema alanını taşır.
- `core-data-service` modül olarak vardır; fakat mevcut compose akışına henüz
  bağlı değildir.

## Sonuç

Bu sistem, çalışan bir edge + service + MFE yapısına sahiptir.
Yeni geliştirme başlamadan önce referans alınacak gerçek mimari özet budur.
