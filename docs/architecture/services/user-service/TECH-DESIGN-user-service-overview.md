# TECH-DESIGN – User Service Overview (Özet)

Amaç: User Service için API ve davranışlarını yeni docs/ mimarisi altında
özetlemek ve kanonik dokümanları (`users.api.md`, Story/Acceptance/Test Plan)
ile hizalamak.

-------------------------------------------------------------------------------
1. KAPSAM
-------------------------------------------------------------------------------

- Servis: `user-service`
- Konu:
  - `/api/users` endpoint’leri (listeleme, kayıt/güncelleme, export).
  - Kimlik doğrulama ve başlık kullanımı.
  - İzleme ve metrikler.

-------------------------------------------------------------------------------
2. API GENEL BİLGİLER
-------------------------------------------------------------------------------

- Base URL: `/api/users`
- Auth: `Authorization: Bearer <JWT>` zorunlu.
- Bağlamsal başlıklar:
  - `X-Company-Id`, `X-Project-Id`, `X-Warehouse-Id` (opsiyonel, önerilen).

-------------------------------------------------------------------------------
3. ANA ENDPOINTLER (ÖZET)
-------------------------------------------------------------------------------

- Listeleme (SSRM uyumlu):
  - GET `/api/users/all`
  - Parametreler: `page`, `pageSize`, `search`, `status`, `role`, `sort`, `advancedFilter`.
- CSV Export:
  - GET `/api/users/export.csv`
  - Başlık: `Accept: text/csv`
  - Parametreler: listeleme ile aynı, rate-limit & audit guard servisinde.
- Kayıt / Güncelleme:
  - POST `/api/users/register`
  - PUT `/api/users/{id}` (kısmi güncelleme; `name`, `role`, `enabled`, `sessionTimeoutMinutes` vb.)

Detaylı request/response örnekleri ve hata yönetimi için:
- docs/03-delivery/api/users.api.md  
- İlgili STORY/ACCEPTANCE/TEST-PLAN zinciri referans alınmalıdır.

-------------------------------------------------------------------------------
4. HATA YÖNETİMİ
-------------------------------------------------------------------------------

- 401/403: yetkisiz/izin yok.
- 400: geçersiz `advancedFilter` veya `sort`.
- 500: beklenmeyen hata (requestId log’da).

-------------------------------------------------------------------------------
5. METRİKLER VE İZLEME
-------------------------------------------------------------------------------

- `users_search_requests_total{mode,has_search,has_advanced_filter,has_sort,result}`
- `users_search_duration` (histogram).
- Export:
  - `users_export_rate_limit_total`
  - `users_export_audit_total`
  - `users_export_duration`

-------------------------------------------------------------------------------
6. NOT
-------------------------------------------------------------------------------

Bu doküman yalnızca `docs/` altındaki yeni sözleşmelerin üst seviye teknik
özetidir; legacy user-service dokümanları yalnız arşiv olarak tutulur ve tek
kaynak olarak kullanılmaz.
