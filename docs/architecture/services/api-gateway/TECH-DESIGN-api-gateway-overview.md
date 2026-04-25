# TECH-DESIGN – API Gateway Overview

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `api-gateway`, dış istemciler için merkezi ingress katmanıdır.
- Route yönlendirme, JWT boundary, export guard, outage fallback ve temel CORS
  davranışı bu serviste toplanır.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Servis: `api-gateway`
- Temel sorumluluklar:
  - service discovery tabanlı route yönlendirme
  - JWT doğrulama ve audience/issuer filtresi
  - export uçları için rate-limit + PII policy header ekleme
  - Vault/bağlantı kesintilerinde kontrollü 503 fallback döndürme
  - actuator / metrics / prometheus yüzeyi sağlama

-------------------------------------------------------------------------------
3. RUNTIME YAPI
-------------------------------------------------------------------------------

- Ana bileşenler:
  - `SecurityConfig` / `SecurityConfigLocal`
  - `ExportGuardFilter`
  - `VaultFailfastFallbackHandler`
  - `ManifestCorsConfig`
- Discovery / routing:
  - `lb://auth-service`
  - `lb://user-service`
  - `lb://variant-service`
  - `lb://permission-service`
  - `lb://core-data-service`
- Gözlemlenebilirlik:
  - actuator
  - metrics
  - prometheus export

-------------------------------------------------------------------------------
4. ANA ROUTE YÜZEYİ
-------------------------------------------------------------------------------

- Auth:
  - `/api/auth/**`
  - `/api/v1/auth/**`
- User:
  - `/api/users/**`
  - `/api/v1/users/**`
- Variant / Theme:
  - `/api/variants/**`
  - `/api/v1/variants/**`
  - `/api/v1/themes/**`
  - `/api/v1/me/theme/**`
  - `/api/v1/theme-registry/**`
- Permission:
  - `/api/permissions/**`
  - `/api/access/**`
  - `/api/audit/**`
  - `/api/v1/roles/**`
  - `/api/v1/permissions/**`
- Core data:
  - `/api/v1/companies/**`

-------------------------------------------------------------------------------
5. GÜVENLİK VE HATA DAVRANIŞI
-------------------------------------------------------------------------------

- `local/dev` profilinde gateway permit-all çalışır.
  - Bu profilde auth enforcement çoğunlukla downstream servislerde görünür.
- `!local && !dev` profilinde:
  - `/api/v1/**` JWT zorunludur.
  - multi-issuer / multi-JWK decode desteği vardır.
  - audience doğrulaması env/config üzerinden çözülür.
- Export guard:
  - `/api/users/export.csv`
  - `/api/audit/events/export`
  - in-memory token bucket ile rate-limit uygular
  - downstream request'e `X-PII-Policy: mask` ekler
- Outage fallback:
  - discovery/vault/route erişim hatalarında kontrollü `503` JSON response döner
  - `X-Serban-Outage-Code: VAULT_UNAVAILABLE` header'ı eklenir

-------------------------------------------------------------------------------
6. CORS, METRİK VE BAĞIMLILIKLAR
-------------------------------------------------------------------------------

- Global CORS:
  - `http://localhost:3000`
  - `http://localhost:3004`
  - docker varyantında `127.0.0.1:3000` de açıktır
- Manifest CORS:
  - `/manifest/**` için ayrı `CorsWebFilter` tanımı vardır
- Bağımlılıklar:
  - `discovery-server`
  - `auth-service`
  - `user-service`
  - `permission-service`
  - `variant-service`
  - `core-data-service`

-------------------------------------------------------------------------------
7. RİSKLER VE AÇIK NOKTALAR
-------------------------------------------------------------------------------

- `local/dev` profilindeki permit-all davranışı gateway security regresyonlarını
  prod benzeri profile bırakır; bu yüzden integration/e2e zorunludur.
- Route yüzeyi büyüdükçe path çakışmaları ve legacy/v1 çiftleri için contract
  yönetimi zorlaşır.
- Export guard şu an memory tabanlıdır; yüksek trafik ortamında merkezi rate
  limiter gerekecektir.

-------------------------------------------------------------------------------
8. UYGULAMA KURALLARI
-------------------------------------------------------------------------------

- Yeni servis route'u eklenirse hem route listesi hem security/audience etkisi
  birlikte değerlendirilmelidir.
- Gateway'de auth gevşetmesi yalnız profile özel yapılmalı; kalıcı permit-all
  route eklenmemelidir.
- Export benzeri hassas uçlar için guard/filter seviyesi kontrol eklenmeden route
  açılmamalıdır.

-------------------------------------------------------------------------------
9. ÖZET
-------------------------------------------------------------------------------

- `api-gateway`, servis topolojisinin dışarı açılan tek düzenli giriş kapısıdır.
- Yeni servis veya feature dış erişime açılacaksa ilk contract kontrolü bu servis
  üstünden düşünülmelidir.
