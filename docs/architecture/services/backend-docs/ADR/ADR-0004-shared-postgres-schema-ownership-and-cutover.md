# ADR-0004 - Shared Postgres Schema Ownership and Cutover

ID: ADR-0004
Status: Accepted
Tarih: 2026-03-05
Sahip: Halil K.

## Context

Mevcut development/runtime topolojisi tek PostgreSQL veritabanı (`users`)
üstünde birden fazla backend servisi çalıştırıyor. Şu anda tüm tablolar
`public` schema altında bulunuyor.

Bu yapı kısa vadede hız sağlıyor; ancak üç teknik sorun üretiyor:

1. tablo ownership belirsizleşiyor
2. migration sınırları servis sınırlarıyla hizalanmıyor
3. cross-service SQL bağımlılığı gizleniyor

Canlı inceleme sonucu özellikle `user-service` migration zincirinin
`permission-service` tablosu olan `roles` ve `user_role_assignments` alanına
dokunduğu görüldü.

## Decision

Yeni baseline:

- Development ortamında tek PostgreSQL instance kullanılabilir.
- Aynı veritabanı içinde her backend servis kendi schema ownership alanına sahip
  olmalıdır.
- Varsayılan hedef schema eşleşmesi:
  - `auth-service` -> `auth_service`
  - `user-service` -> `user_service`
  - `permission-service` -> `permission_service`
  - `variant-service` -> `variant_service`
  - `core-data-service` -> `core_data_service`
- Servis config katmanı schema-aware olmak zorundadır.
- Cross-service SQL ve cross-service migration ownership ihlali kabul edilmez.

## Consequences

Olumlu:

- fiziksel veri sahipliği netleşir
- Flyway zincirleri daha güvenli hale gelir
- ayrı database/instance mimarisine geçiş kolaylaşır

Olumsuz / Maliyet:

- mevcut `public` tablolardan hedef schemalara kontrollü taşıma gerekir
- `user-service` içindeki tarihsel cross-service seed mantığı için re-baseline
  veya migration rechain gerekir
- upgrade ve fresh bootstrap için ayrı smoke kanıtı gerekir

## Rollout Rule

Bu ADR iki aşamada uygulanır:

1. Kontrat aşaması
   - schema contract SQL
   - config/env schema anahtarları
   - mimari plan

2. Cutover aşaması
   - cross-service DB coupling kaldırılır
   - tablolar hedef schemalara taşınır
   - servis env değerleri hedef schema isimlerine alınır
   - runtime smoke ve rollback kanıtı üretilir

## Geçiş Notu

- Tarihsel olarak uygulanmış `user-service` Flyway migration dosyaları (`V6`, `V8`)
  permission ownership alanına dokunmaktadır.
- Bunlar checksum kırmamak için yerinde değiştirilmemiştir.
- Aktif runtime bootstrap ownership'i `permission-service` içindeki default admin
  assignment initializer ile düzeltilmiştir.
- Tam temizlik bir sonraki adımda `legacy-flyway-cutover-plan` içindeki
  re-baseline + offline upgrade cutover akışı ile yapılır.

## Linkler

- Runtime backlog: `docs/02-architecture/runtime/runtime-alignment-backlog.md`
- Isolation plan: `docs/02-architecture/runtime/database-isolation-plan.md`
- Legacy cutover plan: `docs/02-architecture/runtime/legacy-flyway-cutover-plan.md`
- Backend stil kuralı: `docs/00-handbook/STYLE-BE-001.md`
