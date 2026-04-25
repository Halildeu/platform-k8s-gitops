# TECH-DESIGN – Permission Bulk-Assign API v2

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Permission service üzerinde, çok sayıda kullanıcı/role/group için aynı
  permission set’ini tek seferde atayabilen veya geri alabilen bulk-assign
  API v2 tasarımını tanımlamak.
- Mevcut permission registry v1, User REST/DTO v1 ve Auth REST/DTO v1 ile
  uyumlu, audit ve performans açısından güvenli bir çözüm üretmek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Servis: `permission-service`
- Etkilenen alanlar:
  - REST API katmanı (`/api/v1/permissions/bulk-assign`, `/bulk-revoke`)
  - Domain katmanı (permission registry v1 ile entegrasyon)
  - Audit logging ve monitoring
  - Ops/UI tarafına dönen özet DTO’lar

-------------------------------------------------------------------------------
3. MİMARİ / YAPI
-------------------------------------------------------------------------------

- Giriş:
  - FE Access UI veya ops script’leri, REST API üzerinden bulk isteği gönderir.
- Uygulama:
  - `BulkPermissionController`:
    - `POST /api/v1/permissions/bulk-assign`
    - `POST /api/v1/permissions/bulk-revoke`
  - `BulkPermissionService`:
    - Request’i doğrular, target ve permission listelerini çözer.
    - İşlem için tekil `bulkOperationId` üretir.
    - Her target için ilgili domain servislerine (registry, user-service vb.)
      çağrılar yapar.
  - `BulkPermissionProcessor`:
    - Her target için `success/failed` durumlarını toplar.
    - Sonuçları `BulkPermissionOperationResultDto` olarak döner.
- Çıkış:
  - API response, toplam kayıt ve hata özetini içerir.
  - Audit/log katmanı `bulkOperationId` üzerinden kayıtları saklar.

-------------------------------------------------------------------------------
4. ARAYÜZLER / CONTRACT’LAR
-------------------------------------------------------------------------------

- API path’leri:
  - `POST /api/v1/permissions/bulk-assign`
  - `POST /api/v1/permissions/bulk-revoke`
- Önemli DTO’lar (detay için `access-permission-bulk-assign.api.md`):
  - `BulkPermissionTargetDto`
  - `BulkPermissionOperationRequestDto`
  - `BulkPermissionOperationResultItemDto`
  - `BulkPermissionOperationResultDto`
- Hata kontratı:
  - `ErrorResponse` (STYLE-API-001) – kod, mesaj, detaylar, traceId.

-------------------------------------------------------------------------------
5. KARARLAR VE ALTERNATİFLER
-------------------------------------------------------------------------------

- Karar: İlk versiyonda REST senkron + küçük/orta batch’ler için 200/202
  davranışı; çok büyük batch senaryoları için ileride asenkron job modeli
  değerlendirilecek.
- Karar: `bulkOperationId` hem audit log’da hem de response DTO’sunda
  zorunlu alan; incident incelemelerinde ana korelasyon anahtarı.
- Alternatif: Tamamen messaging tabanlı (event-driven) bir yaklaşım
  değerlendirilmiş; ancak ilk fazda mevcut REST tabanlı mimariyi daha az
  değiştiren çözüm tercih edilmiştir.

-------------------------------------------------------------------------------
6. RİSKLER / VARSAYIMLAR
-------------------------------------------------------------------------------

- Riskler:
  - Çok büyük batch’lerde (binlerce kayıt) thread/connection kullanımı ve
    veri tabanı kilitlenmeleri.
  - Yanlış parametrelerle çalıştırılan bulk işlemlerin geniş kullanıcı
    gruplarını etkilemesi.
.- Varsayımlar:
  - Permission registry v1 modeli korunur; sadece yeni bulk entry point’leri
    eklenir.
  - Monitoring tarafında temel metrikler (işlem süresi, başarı/başarısız
    adetleri) mevcuttur veya bu Story kapsamında eklenecektir.

-------------------------------------------------------------------------------
7. UYGULAMA ADIMLARI
-------------------------------------------------------------------------------

- `permission-service` repository:
  - `BulkPermissionController` ve `BulkPermissionService` sınıflarını ekle/güncelle.
  - Gerekli DTO sınıflarını tanımla veya `access-permission-bulk-assign.api.md`
    ile hizalı hale getir.
  - Audit/log katmanında `bulkOperationId` ile kayıt tutacak alanları ekle.
  - Temel unit ve integration testlerini yaz.
- Dokümantasyon:
  - `docs/03-delivery/api/access-permission-bulk-assign.api.md` içeriğini
    güncel mimariyle uyumlu tut.
  - STORY-0042, AC-0042, TP-0101 ile teknik tasarım linklerini koru.

-------------------------------------------------------------------------------
8. ÖZET
-------------------------------------------------------------------------------

- Permission bulk-assign API v2, permission-service içine net bir controller +
  service katmanı ve sonuç DTO’ları ile entegre edilecektir.
- Çözüm, yüksek hacimli permission işlemlerini hem performans hem de audit
  açısından güvenli hale getirirken, mevcut registry v1 ve User/Auth REST/DTO
  v1 sözleşmeleriyle uyumlu kalacaktır.

