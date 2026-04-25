# TECH-DESIGN – Core Data Service Overview

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `core-data-service`, şirket temel verisini yöneten çekirdek master-data
  servisidir.
- Mevcut runtime'ta ilk bounded context olarak `company` alanını taşır.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Servis: `core-data-service`
- Temel sorumluluklar:
  - şirket listeleme ve arama
  - şirket detay görüntüleme
  - şirket oluşturma ve güncelleme
  - permission kodları ile company read/write erişim sınırı

-------------------------------------------------------------------------------
3. RUNTIME YAPI
-------------------------------------------------------------------------------

- Giriş katmanı:
  - `CompanyController` -> `/api/v1/companies`
- Uygulama katmanı:
  - `CompanyService`
- Veri katmanı:
  - `CompanyRepository`
  - `Company` entity
- Teknik özellik:
  - filtreleme `Specification` tabanlıdır
  - listeleme `PagedResultDto` ile döner

-------------------------------------------------------------------------------
4. ANA API YÜZEYİ
-------------------------------------------------------------------------------

- `GET /api/v1/companies`
  - filtreler: `companyCode`, `companyName`, `status`
  - paging: `page`, `size`
  - sorting: `sort=field,direction`
- `GET /api/v1/companies/{id}`
- `POST /api/v1/companies`
- `PUT /api/v1/companies/{id}`

-------------------------------------------------------------------------------
5. GÜVENLİK VE SECRET MODELİ
-------------------------------------------------------------------------------

- `/actuator/health` dışında tüm istekler JWT gerektirir.
- Method security aktif ve şu permission kodlarını kullanır:
  - `COMPANY_READ`
  - `COMPANY_WRITE`
- JWT doğrulaması:
  - issuer kontrolü aktif
  - audience listesi env veya `spring.application.name` üstünden çözülür
- Secret / config kaynakları:
  - local varsayılan config `jdbc:postgresql://localhost:5432/coredata`
  - docker/runtime override ile shared `users` DB senaryosu desteklenir
- Veri tabanı:
  - Flyway aktif
  - `baseline-on-migrate=true`
  - `baseline-version=0`
  - history tablosu: `core_data_flyway_history`

-------------------------------------------------------------------------------
6. BAĞIMLILIKLAR VE İLETİŞİM
-------------------------------------------------------------------------------

- `api-gateway`
  - `/api/v1/companies/**` route'u ile dış dünyaya açılır.
- `discovery-server`
  - service discovery bağımlılığı vardır.
- Bu servis şu an doğrudan başka domain servislerini çağırmaz; bounded context'i
  içeride tutar.

-------------------------------------------------------------------------------
7. RİSKLER VE AÇIK NOKTALAR
-------------------------------------------------------------------------------

- Docker runtime'ta shared `users` veritabanına bağlanabilmesi geçici hizalama
  çözümüdür; uzun vadede data isolation gerektirir.
- Mevcut bounded context yalnız company yüzeyiyle sınırlıdır; yeni master data
  modülleri eklenirken ayrı aggregate sınırları açıkça tanımlanmalıdır.
- Şu anda delete/deactivate gibi yaşam döngüsü uçları yoktur; yeni ihtiyaçlarda
  veri yönetişimi kuralı ayrıca kararlaştırılmalıdır.

-------------------------------------------------------------------------------
8. UYGULAMA KURALLARI
-------------------------------------------------------------------------------

- Yeni master-data alanı eklenirse önce bounded context ve ownership kararı
  dokümana işlenmelidir.
- Shared DB senaryosunda yeni tablo ekleyen migration'lar servis bazlı history
  tablosu ile ilerlemelidir.
- Permission kodu genişletmeleri controller ve gateway contract etkisiyle birlikte
  ele alınmalıdır.

-------------------------------------------------------------------------------
9. ÖZET
-------------------------------------------------------------------------------

- `core-data-service`, master-data alanını bağımsız servis olarak ayırma yönünde
  atılmış ilk somut adımdır.
- Bundan sonraki veri merkezli feature'lerde servis sınırı korunmalı ve shared DB
  kullanımının geçici bir uyum katmanı olduğu unutulmamalıdır.
