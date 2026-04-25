# TECH-DESIGN – Discovery Server Overview

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `discovery-server`, mikroservislerin runtime'ta birbirini bulduğu merkezi
  Eureka registry servisidir.
- İş alanı logic'i taşımaz; altyapı topolojisinin omurgasıdır.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Servis: `discovery-server`
- Temel sorumluluklar:
  - servis kayıtlarını kabul etmek
  - registry bilgisini sağlamak
  - gateway ve diğer servisler için discovery kaynağı olmak

-------------------------------------------------------------------------------
3. RUNTIME YAPI
-------------------------------------------------------------------------------

- Tek uygulama sınıfı:
  - `DiscoveryServerApplication`
- Spring Cloud Netflix Eureka Server olarak ayağa kalkar.
- Varsayılan port: `8761`

-------------------------------------------------------------------------------
4. RUNTIME CONTRACT
-------------------------------------------------------------------------------

- Son kullanıcı business endpoint'i yoktur.
- Operasyonel yüzey:
  - Eureka dashboard / registry API
  - `/actuator/health`
- Konfigürasyon:
  - `register-with-eureka=false`
  - `fetch-registry=false`
  - yani kendi kendini client gibi kullanmaz

-------------------------------------------------------------------------------
5. BAĞIMLILIKLAR VE ETKİ
-------------------------------------------------------------------------------

- Tüm runtime servisleri discovery kaydını bu servise yapar:
  - `auth-service`
  - `user-service`
  - `permission-service`
  - `variant-service`
  - `core-data-service`
  - `api-gateway`
- Gateway route zinciri dolaylı olarak bu servise bağımlıdır.

-------------------------------------------------------------------------------
6. RİSKLER VE AÇIK NOKTALAR
-------------------------------------------------------------------------------

- Local stack'te tek registry noktası olduğu için kritik bağımlılıktır.
- Discovery yoksa gateway route çözümü ve servisler arası LB çağrıları kırılır.
- Şu an tek node çalıştığı için yüksek erişilebilirlik hedefi yoktur.

-------------------------------------------------------------------------------
7. UYGULAMA KURALLARI
-------------------------------------------------------------------------------

- Yeni servis compose veya runtime'a eklenirse discovery kaydı ve health bilgisi
  ayrıca doğrulanmalıdır.
- Discovery konfigürasyonu business feature ile birlikte değiştirilmez; ayrı
  altyapı değişikliği olarak ele alınır.

-------------------------------------------------------------------------------
8. ÖZET
-------------------------------------------------------------------------------

- `discovery-server`, business servis değil ama tüm mikroservis topolojisinin
  çalışma ön koşuludur.
- Bu nedenle canlı doğrulama zincirinde health ve registry kanıtı her zaman
  ayrı tutulmalıdır.
