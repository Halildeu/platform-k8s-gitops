# INTERFACE-CONTRACT – Arayüz / Kontrat Şablonu

ID: IC-XXX-<kısa-konu>

Not: Aşağıdaki başlıklar ve sıralama **zorunludur**. HTTP API kontratları
oluşturulurken ayrıca `STYLE-API-001.md` kuralları da uygulanmalıdır. Özellikle:
- Request/Response DTO’ları **isim ve alan bazında** tanımlanmalıdır.
- Kullanılan status code’lar ve ortak `ErrorResponse` şeması açıkça yazılmalıdır.
- İlgili PB / PRD / STORY / ACCEPTANCE / TEST PLAN / API doküman linkleri
  “7. LİNKLER / SONRAKİ ADIMLAR” bölümünde yer almalıdır.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- İki sistem/servis arasındaki kontratı netleştirmek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Kim konuşuyor? (istemci/servis).
- Hangi domain / modül için geçerli?

-------------------------------------------------------------------------------
3. ENDPOINT / ARAYÜZ TANIMI
-------------------------------------------------------------------------------

- URL / topic / queue bilgisi.
- HTTP API ise:
  - Method + Path (örn. `GET /api/v1/...`).
  - Request DTO’ları:
    - DTO adı ve alan bazında tanım (tip, zorunluluk, açıklama).
  - Response DTO’ları:
    - DTO adı ve alan bazında tanım.
- Diğer protokoller için:
  - Mesaj şeması, header/body alanları.

-------------------------------------------------------------------------------
4. DAVRANIŞ VE HATA DURUMLARI
-------------------------------------------------------------------------------

- Başarılı akış:
  - Temel happy path senaryosu.
- Hata durumları:
  - Kullanılan status code’lar (200/201/400/401/403/404/409/500 vb.).
  - Error formatı (örn. ortak ErrorResponse şeması).
  - Tipik hata örnekleri ve mesajlar.

-------------------------------------------------------------------------------
5. GÜVENLİK VE VERSİYONLAMA
-------------------------------------------------------------------------------

- Auth:
  - JWT / service token / başka mekanizma?
- Authz:
  - Roller, scope’lar veya permission anahtarları.
- Header/bağlam:
  - Ortak header’lar (örn. `Authorization`, `X-Company-Id`).
- Rate limit ve throttling (varsa).
- Versiyonlama:
  - HTTP API’lerde `/api/v1/` vb. prefix.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Kontratın kısa özeti ve kullanım notları.

-------------------------------------------------------------------------------
7. LİNKLER / SONRAKİ ADIMLAR
-------------------------------------------------------------------------------

- İlgili PB / PRD / STORY / ACCEPTANCE / TEST PLAN / API dokümanları.
