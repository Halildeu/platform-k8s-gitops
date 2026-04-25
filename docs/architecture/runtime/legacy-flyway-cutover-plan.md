# Legacy Flyway Cutover Plan

Bu doküman, mevcut `public` schema üstünde çalışan çok servisli PostgreSQL
kurulumunu hedef servis schema'larına taşırken tarihsel Flyway borcunu nasıl
yöneteceğimizi tanımlar.

Referans JSON artefact:
- `legacy-flyway-cutover-plan.v1.json`

## 1. Neden Ayrı Bir Plan Var?

`database-isolation-plan` hedef mimariyi tanımlar; fakat tek başına yeterli
olmaz. Çünkü mevcut canlı ortamda tarihsel olarak uygulanmış iki `user-service`
migration dosyası (`V6`, `V8`) `permission-service` ownership alanına SQL
seviyesinde dokunmaktadır.

Bu dosyalar geçmişte çalıştığı için yerinde değiştirilemez. Bu yüzden gerçek
cutover iki hatta bölünür:

1. fresh bootstrap için yeni schema-owned baseline zinciri
2. mevcut canlı ortam için offline upgrade + schema move cutover

## 2. Önerilen Strateji

Önerilen yol:
- mevcut uygulanmış V6/V8 migration dosyalarını değiştirme
- aktif runtime ownership'i `permission-service` bootstrap ile koru
- boş ortamlarda kullanılacak yeni baseline zincirlerini ayrıca üret
- mevcut ortamı ise tek seferlik offline schema move ile yükselt

Neden:
- Flyway checksum kırılmaz
- upgrade ve fresh bootstrap ayrı risk profillerine sahip olur
- servis ownership'i veri katmanında gerçekten görünür hale gelir

## 3. Değişmez Kurallar

- Geçmişte uygulanmış versioned Flyway migration dosyaları immutable kabul edilir.
- Cutover business servisler durmuşken yapılır; PostgreSQL açık kalır.
- `permission-service` default admin assignment bootstrap'ı ilk post-cutover
  start'ta açık kalır.
- Cutover öncesi ve sonrası object inventory + Flyway history kanıtı üretilir.
- Rollback, tarihi migration dosyalarını yeniden yazarak değil, schema geri taşıma
  ve config rollback ile yapılır.

## 4. Fazlar

### 4.1 Phase-0 Preflight Freeze

Amaç:
- geri dönüş için somut kanıt toplamak
- cutover penceresini deterministik hale getirmek

Çıktılar:
- tablo ve sequence inventory
- `user_flyway_history` ve `permission_flyway_history` snapshot'ı
- health / Eureka / gateway lock snapshot'ı

### 4.2 Phase-1 Fresh Bootstrap Re-baseline

Amaç:
- boş ortamlar için artık `public` schema bağımlı eski bootstrap zincirini
  canonical olmaktan çıkarmak

Bu fazda:
- `user-service` yalnız kendi tablolarını kuran yeni baseline zinciri alır
- `permission-service` kendi ownership tablolarını kuran yeni baseline zinciri alır
- varsayılan admin role assignment davranışı `permission-service` bootstrap'ta kalır

Bu faz gerçek canlı upgrade'den ayrıdır; amacı gelecekte temiz ortam kurulumunu
legacy migration borcundan kurtarmaktır.

Bu turda hazırlanan artefact'lar:
- `backend/*/src/main/resources/db/migration_schema_owned/`
- `backend/scripts/ops/validate-schema-owned-baselines.sh`
- `.autopilot-tmp/baseline-validation/*.log`

### 4.3 Phase-2 Offline Upgrade Cutover

Amaç:
- mevcut `public` tablo setini hedef service schema'larına taşımak

Önerilen taşıma sırası:
1. `auth-service`
2. `variant-service`
3. `core-data-service`
4. `permission-service`
5. `user-service`

Not:
- `permission-service` ve `user-service` aynı maintenance window içinde birlikte
  ele alınır.
- `user_role_assignments` ile `users` arasındaki ilişki nedeniyle bu iki servis
  ayrı iş gibi değil, koordineli tek iş gibi düşünülmelidir.
- Owned sequence'ler rehearsal sırasında tabloyla birlikte taşındığı için
  explicit `ALTER SEQUENCE` adımları no-op notice üretebilir; bu beklenen
  davranıştır.

Bu turda hazırlanan artefact'lar:
- `backend/devops/postgres/02-offline-service-schema-cutover.sql`
- `backend/devops/postgres/03-offline-service-schema-cutover-rollback.sql`
- `backend/scripts/ops/rehearse-service-schema-cutover.sh`
- `.autopilot-tmp/cutover-rehearsal/*`

### 4.4 Phase-3 Config Flip ve Runtime Verify

Bu fazda:
- `<SERVICE>_DB_SCHEMA` değerleri hedef schema isimlerine alınır
- servisler kontrollü sırayla açılır
- health, registry, gateway ve admin assignment doğrulanır
- Flyway validate her servis için yeniden koşulur

Bu faz izole rehearsal ortamında başarıyla geçti.

Rehearsal özeti:
- ortam: `schema_rehearsal`
- compose: `backend/devops/rehearsal/docker-compose.app-level-schema.yml`
- runner: `backend/scripts/ops/run-app-level-schema-rehearsal.sh`
- health: `discovery`, `permission-service`, `user-service`, `auth-service`,
  `variant-service`, `core-data-service`, `api-gateway` -> `UP`
- Eureka: `AUTH-SERVICE`, `USER-SERVICE`, `PERMISSION-SERVICE`,
  `VARIANT-SERVICE`, `CORE-DATA-SERVICE`, `API-GATEWAY`
- gateway smoke: `GET /api/v1/companies` -> `401 Unauthorized`
- admin assignment: `admin@example.com` ve `admin1@example.com` -> `ADMIN`
- schema inventory: 27 tablo hedef service schema'ları altında

Rehearsal sırasında kapanan iki gerçek blokaj:
- `permission-service` audit entity alanları `TEXT` DDL ile hizalandı
- `auth-service` rehearsal profili `local,docker` olacak şekilde düzeltildi

Artefact kanıtları:
- `.autopilot-tmp/app-level-schema-rehearsal/compose-ps.json`
- `.autopilot-tmp/app-level-schema-rehearsal/eureka-apps.xml`
- `.autopilot-tmp/app-level-schema-rehearsal/gateway-companies-headers.txt`
- `.autopilot-tmp/app-level-schema-rehearsal/gateway-companies-body.txt`
- `.autopilot-tmp/app-level-schema-rehearsal/schema-inventory.txt`
- `.autopilot-tmp/app-level-schema-rehearsal/admin-role-assignments.txt`
- `.autopilot-tmp/app-level-schema-rehearsal/flyway-history-counts.txt`

### 4.5 Phase-4 Live Maintenance Window Cutover

Bu faz canlı ortamda tamamlandı.

Uygulanan akış:
- canlı stack için pre-cutover lock snapshot alındı
- business servisler durduruldu, PostgreSQL açık bırakıldı
- `02-offline-service-schema-cutover.sql` canlı `users` veritabanına uygulandı
- canlı `<SERVICE>_DB_SCHEMA` değerleri hedef schema isimlerine çekildi
- servisler `permission -> user -> auth -> variant -> core-data -> api-gateway`
  sırasıyla yeniden açıldı
- post-cutover health, Eureka, gateway `401`, admin assignment ve Flyway history
  kanıtı toplandı

Canlı cutover özeti:
- gateway `GET /api/v1/companies` -> `401 Unauthorized`
- `AUTH-SERVICE`, `USER-SERVICE`, `PERMISSION-SERVICE`, `VARIANT-SERVICE`,
  `CORE-DATA-SERVICE`, `API-GATEWAY` Eureka'da aktif
- 27 runtime tablo hedef service schema'ları altında
- admin assignment kanıtı aktif
- live rollback tetiklenmedi

Artefact kanıtları:
- `backend/.autopilot-tmp/live-schema-cutover/pre/*`
- `backend/.autopilot-tmp/live-schema-cutover/post/*`

## 5. Servis Bazlı Ownership Haritası

- `auth-service` -> `email_verification_tokens`, `password_reset_tokens`, `auth_flyway_history`
- `user-service` -> `users`, `user_audit_events`, `user_notification_preferences`, `user_flyway_history`
- `permission-service` -> `permissions`, `roles`, `role_permissions`, `user_role_assignments`, `scopes`, `user_permission_scope`, `permission_audit_events`, `authz_audit_log`, `permission_flyway_history`
- `variant-service` -> `themes`, `theme_registry`, `theme_registry_css_vars`, `theme_overrides`, `user_theme_selections`, `user_grid_variants`, `user_grid_variant_preferences`, `variant_visibility`, `variant_flyway_history`
- `core-data-service` -> `companies`, `core_data_flyway_history`

## 6. Geçişte Başarı Kriterleri

- tüm aktif backend servisler `healthy`
- Eureka'da tüm kritik servisler kayıtlı
- gateway `/api/v1/companies` isteği `401 Unauthorized`
- admin kullanıcıların `ADMIN` assignment'ı aktif
- taşınan tablo ve sequence'ler hedef schema altında görünüyor
- Flyway validate her servis için temiz

## 7. Rollback Mantığı

Rollback şu durumda tetiklenir:
- schema flip sonrası kritik servis health başarısızsa
- Flyway validate başarısızsa
- gateway smoke `5xx` verirse veya registry eksikse

Rollback adımları:
1. business servisleri durdur
2. schema env değerlerini tekrar `public` moduna al
3. reverse `SET SCHEMA` ile objeleri geri taşı
4. health / gateway / registry smoke'u tekrar çalıştır
5. hata kanıtını sakla; tarihsel migration dosyalarını değiştirme

## 8. Bu Fazdan Sonra Ne Yapılacak?

Bir sonraki teknik adım canlı cutover değil, post-cutover bakım işidir:
- fresh environment kurulumlarında `migration_schema_owned` zincirlerini
  canonical bootstrap olarak kullanmak
- `user-service` içindeki tarihsel V6/V8 coupling'i legacy migration debt olarak
  izlemeye devam etmek
- orta vadede ayrı database veya instance kararını backlog bazında ele almak
