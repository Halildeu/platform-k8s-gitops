# TECH-DESIGN – Auth Service Overview

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `auth-service`, kullanıcı oturumu, kayıt, email doğrulama, parola sıfırlama
  ve servisler arası kısa ömürlü token üretimi için merkezi kimlik servisidir.
- Runtime'ta hem son kullanıcı akışlarını (`/api/auth`, `/api/v1/auth`) hem de
  iç servis akışlarını (`/oauth2/token`, `/oauth2/jwks`) taşır.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Servis: `auth-service`
- Temel sorumluluklar:
  - kullanıcı login ve register akışları
  - email verification / password reset token yaşam döngüsü
  - `user-service` ile kullanıcı kaydı ve aktivasyon senkronizasyonu
  - `permission-service` üzerinden permission çözümü
  - servisler arası JWT mint (`client_credentials` benzeri akış)

-------------------------------------------------------------------------------
3. RUNTIME YAPI
-------------------------------------------------------------------------------

- Giriş katmanı:
  - `AuthController` ile legacy `/api/auth/**`
  - `AuthControllerV1` ile `/api/v1/auth/**`
  - `ServiceTokenController` ile `/oauth2/token`
  - `ServiceJwksController` ile `/oauth2/jwks`
- Uygulama katmanı:
  - `AuthService`
  - `EmailVerificationService`
  - `PasswordResetService`
  - `ServiceTokenProvider`
- Dış bağımlılıklar:
  - `UserServiceClient` -> `user-service`
  - `PermissionServiceClient` -> `permission-service`
- Teknik not:
  - iç servis çağrıları `WebClient` ile yürür.
  - `user-service` ve `permission-service` hatlarında ortak timeout policy vardır.

-------------------------------------------------------------------------------
4. ANA API YÜZEYİ
-------------------------------------------------------------------------------

- Legacy auth path'leri:
  - `POST /api/auth/login`
  - `POST /api/auth/register`
  - `GET /api/auth/verify-email`
  - `POST /api/auth/forgot-password`
  - `POST /api/auth/reset-password`
- v1 auth path'leri:
  - `POST /api/v1/auth/sessions`
  - `POST /api/v1/auth/registrations`
  - `POST /api/v1/auth/password-resets`
  - `POST /api/v1/auth/password-resets/{token}`
  - `POST /api/v1/auth/email-verifications/{token}`
- İç servis path'leri:
  - `POST /oauth2/token`
  - `GET /oauth2/jwks`

-------------------------------------------------------------------------------
5. GÜVENLİK VE SECRET MODELİ
-------------------------------------------------------------------------------

- `local/dev` profilinde:
  - `/api/auth/**`, `/oauth2/**`, health endpoint'leri anonim açıktır.
  - geri kalan istekler `JwtAuthFilter` arkasındadır.
- `!local && !dev` profilinde:
  - `/api/v1/**` JWT zorunludur.
  - resource server doğrulaması aktif olur.
- Secret / config kaynakları:
  - datasource varsayılan olarak Vault anahtarlarından okunur.
  - servis JWT private/public key bilgisi Vault veya env override ile gelir.
  - mint endpoint client secret allowlist'i config üzerinden yönetilir.
- Veri tabanı:
  - Flyway aktif
  - history tablosu: `auth_flyway_history`

-------------------------------------------------------------------------------
6. BAĞIMLILIKLAR VE İLETİŞİM
-------------------------------------------------------------------------------

- `user-service`
  - public register
  - internal by-email / activate / password / last-login uçları
- `permission-service`
  - assignment tabanlı permission çözümü
- `discovery-server`
  - runtime registry bağımlılığı
- `api-gateway`
  - dış istemcilerin standart giriş noktasıdır; ancak auth-service doğrudan da
    test edilebilir.

-------------------------------------------------------------------------------
7. RİSKLER VE AÇIK NOKTALAR
-------------------------------------------------------------------------------

- Legacy `/api/auth/**` ve v1 `/api/v1/auth/**` path'leri birlikte yaşadığı için
  deprecation planı olmadan yüzey büyür.
- `local/dev` ile non-local security davranışı farklıdır; smoke testlerinde bu
  ayrım açıkça dikkate alınmalıdır.

-------------------------------------------------------------------------------
8. UYGULAMA KURALLARI
-------------------------------------------------------------------------------

- Yeni service-to-service HTTP entegrasyonu eklenirse `WebClient` standardı
  kullanılmalıdır.
- Mevcut v1 path'ler değiştirilirken eşleşen legacy path etkisi kontrol edilmelidir.
- Servis token mint politikası (`audience`, `permissions`, rate limit) doküman ve
  kod birlikte güncellenmeden genişletilmemelidir.

-------------------------------------------------------------------------------
9. ÖZET
-------------------------------------------------------------------------------

- `auth-service`, kullanıcı kimliği ile iç servis kimliğini aynı runtime modülde
  birleştiren kritik boundary servisidir.
- Yeni feature'lerde bu servis hem public auth akışları hem de internal token mint
  contract'ı açısından birlikte değerlendirilmelidir.
