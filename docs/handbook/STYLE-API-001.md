# STYLE-API-001 – API Tasarım Stili (Compact)

Bu doküman, tüm backend servisleri için API tasarımında kullanılacak standart
kuralları tanımlar. Amaç: servislerin tutarlı, anlaşılır ve kolay entegre
edilebilir olmasıdır.

-------------------------------------------------------------------------------
1. GENEL TASARIM KURALLARI
-------------------------------------------------------------------------------

- API'lar REST prensiplerine uygun olmalıdır.
- URL'ler kaynak (resource) bazlı tasarlanır, fiil kullanılmaz.
  Örn: /api/v1/users (doğru), /api/v1/getUsers (yanlış)
- Versiyonlama zorunludur: /api/v1/
- Tüm endpoint'ler JSON formatında input/output kullanır.
- Response hiçbir zaman ham entity içermez → DTO döndürülür.

-------------------------------------------------------------------------------
2. URL YAPISI VE METHOD KULLANIMI
-------------------------------------------------------------------------------

- GET    → veri okumak
- POST   → yeni kaynak oluşturmak
- PUT    → tam güncelleme
- PATCH  → kısmi güncelleme
- DELETE → silme

Örnek URL seti:
- GET    /api/v1/users
- GET    /api/v1/users/{id}
- POST   /api/v1/users
- PUT    /api/v1/users/{id}
- DELETE /api/v1/users/{id}

Listeleme filtreleri query param ile verilir:
- /api/v1/users?role=admin&status=active

-------------------------------------------------------------------------------
3. REQUEST / RESPONSE STANDARTLARI
-------------------------------------------------------------------------------

Request:
- Girdi modelleri CreateXRequest ve UpdateXRequest DTO’ları olarak tanımlanır.
- Validation zorunludur → @Valid + javax.validation

Response:
- Ana model XResponse olarak tanımlanır.
- Liste dönüşlerinde:
  - items: []
  - totalCount: number
  - page / size (varsa)

Genel hataların hepsi ortak error formatıyla döner:
{
  code: "ERR_NOT_FOUND",
  message: "User not found",
  timestamp: "...",
  path: "/api/v1/users/123"
}

-------------------------------------------------------------------------------
4. STATUS CODE STANDARTLARI
-------------------------------------------------------------------------------

200 OK          → başarılı istek  
201 CREATED     → yeni kaynak oluşturuldu  
204 NO CONTENT  → içerik yok ama başarılı  
400 BAD REQUEST → validation hatası  
401 UNAUTHORIZED  
403 FORBIDDEN  
404 NOT FOUND  
409 CONFLICT  
500 INTERNAL SERVER ERROR  

-------------------------------------------------------------------------------
5. PAGING / SORTING / FILTERING
-------------------------------------------------------------------------------

Paging:
- ?page=0&size=20

Sorting:
- ?sort=name,asc
- Çoklu sort destekleniyorsa: ?sort=name,asc&sort=createdAt,desc

Filtering:
- Sadece açık isimli query param’lar kullanılmalı.
- “wildcard” parametrelerden kaçınılır.

-------------------------------------------------------------------------------
6. SECURITY & AUTHZ
-------------------------------------------------------------------------------

- Tüm endpoint’ler token doğrulamasından geçer.
- Yetki kontrolü:
  - Method-level → @PreAuthorize("hasAuthority('USER_VIEW')")
- Servisler arası çağrılarda internal token veya service-to-service auth katmanı
  kullanılmalıdır.
- Hassas alanlar maskelenmelidir.

-------------------------------------------------------------------------------
7. VERSİYONLAMA
-------------------------------------------------------------------------------

- URL seviyesinde: /api/v1/
- Breaking change olduğunda v2’ye geçilir.
- Aynı anda birden fazla versiyon aktif olabilir (migrasyon süresi boyunca).

-------------------------------------------------------------------------------
8. AGENT DAVRANIŞI
-------------------------------------------------------------------------------

[BE] veya [WEB] görevlerinde agent API tasarımı yapacaksa:

1. AGENT-CODEX.core.md  
2. AGENT-CODEX.backend.md  
3. STYLE-API-001.md (bu dosya)  
4. PRD → davranış kuralları  
5. TECH-DESIGN → bağlam bilgisi  
6. Gerekirse `docs/99-templates/INTERFACE-CONTRACT.template.md` → detaylı
   kontrat/DTO/status-code dokümantasyonu  

Sonra şu formatta cevap verir:
- Keşif Özeti  
- API Tasarımı (endpoint, method, DTO, status code, error formatı)  
- Uygulama Adımları (dosya yolu + yapılacak değişiklik)

-------------------------------------------------------------------------------
9. API DOKÜMAN YAPISI (.api.md)
-------------------------------------------------------------------------------

`docs/03-delivery/api/*.api.md` dosyaları yazılırken aşağıdaki bölümler ve
içerikler **zorunludur**:

1) Amaç  
   - API’nin neyi çözdüğünü 1–2 cümle ile açıklar.

2) Endpoint / Path listesi (v1)  
   - Her endpoint için Method + Path (`GET /api/v1/...`, `PATCH /api/v1/...`).  
   - Kısa davranış özeti (ne yaptığı).

3) DTO Özetleri  
   - Kullanılan request/response DTO’larının **adı ve alan bazında tanımı**.  
   - Alanlar için tip, zorunluluk ve kısa açıklama bilgisi bulunmalıdır.

4) Status Code ve Error Zarfı  
   - Endpoint’lerde kullanılan status code’lar (200/201/400/401/403/404/409/500 vb.)
     açıkça listelenmelidir.  
   - Hatalar için ortak `ErrorResponse` şeması kullanılmalı ve dokümanda örnek
     bir hata gövdesi gösterilmelidir.

5) Legacy / Versiyonlama Notu  
   - Varsa legacy path’ler “Legacy” veya benzeri ayrı bir bölümde işaretlenmelidir.  
   - Breaking change olduğunda yeni `/api/v2/...` path’leri ve geçiş süreci
     burada belirtilmelidir.

6) Bağlantılar  
   - İlgili PB / PRD / STORY / ACCEPTANCE / TEST PLAN / INTERFACE-CONTRACT /
     RUNBOOK dokümanları en altta “Bağlantılar” veya “LİNKLER” bölümünde
     listelenmelidir.

Bu yapı sayesinde `.api.md` dokümanları arasında tutarlı bir şablon hissi
sağlanır ve agent’lar için okunması gereken kritik alanlar değişmez.

-------------------------------------------------------------------------------
10. ÖZET
-------------------------------------------------------------------------------

Bu stil dokümanı tüm servislerde:
- tek tip URL yapısı,
- DTO kullanımı,
- error response standardı,
- versioning,
- security kuralları  
için otorite kaynağıdır.
