# TECH-DESIGN – Variant Service Overview

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `variant-service`, grid varyantları, kullanıcı tercihleri, tema yönetimi ve
  tema registry yüzeyini tek runtime modülde taşır.
- Sistem içinde hem kullanıcı deneyimi konfigürasyonu hem de görünüm/state
  varyantlarının ana kaynağıdır.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Servis: `variant-service`
- Temel sorumluluklar:
  - grid varyant CRUD ve preset yönetimi
  - kullanıcı bazlı varyant preference güncelleme
  - global ve kullanıcı temaları
  - çözümlenmiş kullanıcı teması (`resolved theme`) üretimi
  - tema registry listesini servis etme
  - permission-service üzerinden authz bağlamı çözme

-------------------------------------------------------------------------------
3. RUNTIME YAPI
-------------------------------------------------------------------------------

- Varyant API katmanı:
  - `VariantController` -> legacy `/api/variants/**`
  - `VariantControllerV1` -> `/api/v1/variants/**`
- Tema API katmanı:
  - `ThemeController` -> `/api/v1/themes/**`, `/api/v1/me/theme/**`
  - `ThemeRegistryController` -> `/api/v1/theme-registry`
- Uygulama katmanı:
  - `VariantService`
  - `VariantPresetService`
  - `ThemeService`
  - `VariantAuthorizationService`
- Dış bağımlılık:
  - `PermissionServiceAuthzClient` -> `permission-service /api/v1/authz/me`
- Teknik not:
  - Bu servis `WebClient.Builder` ile load-balanced çağrı yapan ilk baseline
    örneğidir.

-------------------------------------------------------------------------------
4. ANA API YÜZEYİ
-------------------------------------------------------------------------------

- Varyant v1 yüzeyi:
  - `GET /api/v1/variants?gridId=...`
  - `GET /api/v1/variants/presets?gridId=...`
  - `POST /api/v1/variants`
  - `PUT /api/v1/variants/{variantId}`
  - `PATCH /api/v1/variants/reorder`
  - `PATCH /api/v1/variants/{variantId}/preference`
  - `POST /api/v1/variants/{variantId}/clone`
  - `DELETE /api/v1/variants/{variantId}`
- Tema yüzeyi:
  - `GET /api/v1/themes`
  - `GET /api/v1/themes/{id}`
  - `PUT /api/v1/themes/global/{id}`
  - `PUT /api/v1/themes/global/{id}/meta`
  - `PUT /api/v1/themes/global/palette`
  - `PUT /api/v1/themes/global/default/{id}`
  - `POST /api/v1/themes`
  - `PUT /api/v1/themes/{id}`
  - `DELETE /api/v1/themes/{id}`
  - `POST /api/v1/themes/{id}/fork`
  - `GET /api/v1/me/theme/resolved`
  - `PATCH /api/v1/me/theme`
- Registry yüzeyi:
  - `GET /api/v1/theme-registry`

-------------------------------------------------------------------------------
5. GÜVENLİK VE SECRET MODELİ
-------------------------------------------------------------------------------

- `local/dev` profilinde:
  - istekler permit-all çalışır; token varsa parse edilir ve authz bağlamı
    çıkarılır.
- `!local && !dev` profilinde:
  - `/api/v1/**` JWT zorunludur.
  - audience doğrulaması `variant-service` üstünden yapılır.
- Yetki modeli:
  - varyant uçları `PermissionCodes.VARIANTS_READ/WRITE` ile korunur.
  - tema admin uçları `AuthorizationContext` içindeki role/permission bağlamıyla
    korunur.
- Secret / config kaynakları:
  - datasource varsayılan olarak Vault anahtarlarından okunur.
  - local/docker fallback olarak shared Postgres `users` DB kullanılabilir.
- Veri tabanı:
  - Flyway aktif
  - history tablosu: `variant_flyway_history`

-------------------------------------------------------------------------------
6. BAĞIMLILIKLAR VE İLETİŞİM
-------------------------------------------------------------------------------

- `permission-service`
  - `/api/v1/authz/me` üzerinden kullanıcı authz bağlamı çözülür.
- `api-gateway`
  - `/api/v1/variants/**`, `/api/v1/themes/**`, `/api/v1/me/theme/**` ve
    `/api/v1/theme-registry/**` route'larını dış dünyaya açar.
- `discovery-server`
  - service discovery bağımlılığı vardır.

-------------------------------------------------------------------------------
7. RİSKLER VE AÇIK NOKTALAR
-------------------------------------------------------------------------------

- Aynı runtime modülde hem varyant hem tema bounded context'i yaşadığı için
  servis sınırı geniştir.
- `local/dev` profilindeki permit-all davranışı, auth regresyonlarının yalnız
  integration/e2e aşamasında görünmesine neden olabilir.
- Shared `users` veritabanı kullanımı veri sınırlarını zayıflatır; ayrı schema
  veya DB ownership kararı backlog'tadır.

-------------------------------------------------------------------------------
8. UYGULAMA KURALLARI
-------------------------------------------------------------------------------

- Yeni iç servis çağrıları `WebClient` standardıyla eklenmelidir.
- Tema ve varyant yüzeyleri aynı serviste yaşasa da contract seviyesinde ayrı
  bounded context gibi ele alınmalıdır.
- UX ve tema kataloğu ile ilgili değişikliklerde `/api/v1/me/theme/resolved` ve
  `/api/v1/theme-registry` etkisi birlikte değerlendirilmelidir.

-------------------------------------------------------------------------------
9. ÖZET
-------------------------------------------------------------------------------

- `variant-service`, ürünün görünüm ve kişiselleştirme davranışını taşıyan ana
  runtime servisidir.
- Yeni UX, tema veya grid davranışı feature'leri bu servis sınırına göre
  planlanmalı; tema ile varyant akışları bilinçli olarak birlikte ele alınmalıdır.
