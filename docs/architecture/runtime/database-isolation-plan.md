# Database Isolation Plan

Bu doküman, mevcut tek `users` veritabanı üstünde çalışan servislerin veri
ownership sınırını nasıl ayıracağımızı tanımlar.

Referans JSON artefact:
- `database-isolation-plan.v1.json`
- `legacy-flyway-cutover-plan.v1.json`

## 1. Bugünkü Durum

- Çalışan runtime tek PostgreSQL veritabanı kullanıyor: `users`
- Aktif backend servis tabloları hedef servis schema'larına taşınmış durumda
- Her servis kendi Flyway history tablosunu ayırmış durumda
- Veri ownership fiziksel schema düzeyinde servis bazlı ayrışmış durumda

## 2. Hedef Model

Tek DB içinde servis bazlı schema ownership:

- `auth-service` -> `auth_service`
- `user-service` -> `user_service`
- `permission-service` -> `permission_service`
- `variant-service` -> `variant_service`
- `core-data-service` -> `core_data_service`

Bu hedefin amacı:
- tablo sahipliğini fiziksel olarak görünür kılmak
- migration çakışmalarını azaltmak
- servis sınırını DB katmanında da enforce etmek
- ayrı database/instance mimarisine geçiş için temiz taban hazırlamak

## 3. Kritik Blokaj

Bugün `user-service` migration zinciri ownership ihlali yapıyor:

- `V6__seed_admin_user.sql`
- `V8__seed_theme_admin_users.sql`

Bu iki migration:
- `roles` tablosunu okuyor
- `user_role_assignments` tablosuna yazıyor

Bu tablolar `permission-service` ownership alanı içindedir. Bu yüzden schema
cutover'dan önce cross-service seed coupling kaldırılmalıdır.

Not:
- Bu migration dosyaları geçmişte çalıştığı için yerinde değiştirilmedi.
- Aktif runtime bootstrap ownership'i `permission-service` tarafına taşındı.
- Tam çözüm için ayrı bir Flyway re-baseline veya migration rechain işi gerekir.

## 4. Bu Turda Uygulanan Kontrat

- PostgreSQL için idempotent schema contract SQL eklendi
- fresh bootstrap için postgres init mount eklendi
- servis config'leri schema-aware hale getirildi
- varsayılan admin role assignment bootstrap'ı `permission-service` tarafına alındı
- canlı cutover ile varsayılan schema değerleri hedef service schema'larına alındı
- izole `schema_rehearsal` ortamında app-level schema rehearsal başarıyla geçti
- canlı `users` veritabanında live maintenance window cutover başarıyla tamamlandı

Sebep:
- mevcut canlı runtime bozulmasın
- ama bir sonraki kontrollü cutover için kod/config yüzeyi hazır olsun
- canlı cutover öncesi gerçek davranış health/Eureka/gateway/admin assignment
  seviyesinde kanıtlanmış olsun

## 5. Sonraki Teknik Adım

Canlı maintenance window execution tamamlandığı için sıradaki iş post-cutover
stabilizasyon ve temiz bootstrap standardını kalıcılaştırmaktır.

1. boş ortam bootstrap'larında `migration_schema_owned` zincirlerini canonical kullan
2. live evidence paketini release/notarization girişleri için referans tut
3. `user-service` içindeki tarihsel V6/V8 coupling'i runtime blocker değil legacy debt olarak izle
