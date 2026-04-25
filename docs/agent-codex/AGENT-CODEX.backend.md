# Backend Görevleri (Compact)

> Transition Durumu: Bu dosya transition-active rehber katmanındadır.
> Canonical kaynaklar:
> `standards.lock`,
> `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md`,
> `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`.

Bu dosya, [BE] (Backend) tipindeki görevlerde agent’ın nasıl davranacağını tanımlar.
Amaç: Tüm Spring Boot mikroservis geliştirmelerinde tutarlı, öngörülebilir ve
izlenebilir bir çalışma modeli oluşturmaktır.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Mikroservis yapısında backend geliştirmeyi standartlaştırmak.
- controller → service → repository → model → dto zincirini korumak.
- Güvenlik, logging, transaction, exception ve test yaklaşımını ortak hale getirmek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

[BE] tipi aşağıdaki görevleri kapsar:

- Yeni REST endpoint ekleme / mevcut endpoint’i genişletme
- Mevcut business logic’i geliştirme veya refaktör
- Yeni mikroservis ekleme (user-service, variant-service vb.)
- Repository / query / transaction tasarımı
- Exception ve security davranışlarının düzenlenmesi

Saf SQL/rapor/ETL işleri ağırlıklı ise ek olarak data transition rehberi
dikkate alınmalıdır.

-------------------------------------------------------------------------------
3. ZORUNLU OKUMA
-------------------------------------------------------------------------------

[BE] işi alındığında agent aşağıdaki dokümanları dikkate almalıdır:

1. ÇEKİRDEK DAVRANIŞ
   - Çekirdek transition rehberi
   - AGENTS.md

2. BACKEND LAYOUT
   - BACKEND-PROJECT-LAYOUT.md

3. BACKEND STİL
   - STYLE-BE-001.md

4. ÜRÜN VE MİMARİ DOKÜMANLAR (VARSA)
   - docs/01-product/PRD/PRD-*.md
   - docs/02-architecture/services/<servis-adı>/TECH-DESIGN-*.md
   - docs/02-architecture/services/<servis-adı>/DATA-MODEL-*.md
   - docs/02-architecture/services/<servis-adı>/ADR/ADR-*.md

Bu dokümanlar yüklenmeden agent endpoint/servis tasarımı önermemelidir.

5. KOD KALİTESİ, TEST, GÜVENLİK VE MİMARİ TUTARLILIK
   - Lint / Build:
     - Backend kodu değiştiren her [BE] işinde:
       - `./scripts/run_lint_backend.sh` (Maven compile / basic check)
       - Gerekirse tüm repo için: `python3 scripts/run_lint_all.py`
   - Testler:
     - Tüm backend testleri:
       - `./scripts/run_tests_backend.sh`
     - Belirli bir modül için:
       - `./scripts/run_tests_backend.sh user-service` (örnek)
     - Backend + Web unit testleri birlikte:
       - `python3 scripts/run_tests_all.py`
   - Security / Vulnerability:
     - Basit statik security kontrolü:
       - `./scripts/check_security_backend.sh`
     - Backend + Web security kontrolleri birlikte:
       - `python3 scripts/check_security_all.py`
   - Mimarî tutarlılık:
     - TECH-DESIGN servis dizinleri ile backend modüllerinin temel varlık
       kontrolü:
       - `python3 scripts/check_arch_vs_code.py`
     - Mikroservis iç iskelet kontrolü (BACKEND-PROJECT-LAYOUT standardı):
       - `python3 scripts/check_backend_service_layout.py`
   - Bu script’ler CI pipeline’ında veya lokal geliştirmede “Validate” aşamasının
     otomatik parçası olarak düşünülmelidir.

-------------------------------------------------------------------------------
4. ÇALIŞMA MODELİ
-------------------------------------------------------------------------------

Agent [BE] görevinde şu adımları izler:

1. Keşif
   - Hangi mikroservis etkilenecek? (ör: user-service, permission-service)
   - Hangi domain? (User, Permission, Variant vb.)
   - PRD / TECH-DESIGN / DATA-MODEL dokümanlarında ilgili bilgi var mı?
   - BACKEND-PROJECT-LAYOUT’a göre ilgili paketler:
     config, controller, dto, model, repository, service, security, exceptions.

2. Tasarım
   - Endpoint tasarımı:
     - URL (örn: /api/v1/users)
     - HTTP method (GET, POST, PUT, DELETE)
     - Request/response DTO’ları
     - Status kodları
   - Katman tasarımı:
     - Controller → hangi service metodunu çağıracak?
     - Service → hangi repository’ler, hangi business rule’lar?
     - Repository → hangi JPA metodu veya custom query?
   - Transaction:
     - @Transactional anotasyonunun nerede ve nasıl kullanılacağı
   - Security:
     - Hangi roller/scope’lar, @PreAuthorize kullanımı
   - Exception:
     - Hangi domain hataları hangi exception’lar ile temsil edilecek?
     - GlobalExceptionHandler ile nasıl map edilecek?

3. Uygulama Adımları
   - Her adım sadece “dosya yolu + yapılacak değişiklik” formatında yazılır.
   - Örnekler:
     - backend/user-service/src/main/java/.../UserController.java → yeni GET /api/v1/users ekle.
     - backend/user-service/src/main/java/.../UserService.java → findUsers(filter) metodu ekle.
     - backend/user-service/src/main/java/.../UserRepository.java → uygun JPA query metodu ekle.
     - backend/user-service/src/main/java/.../UserMapper.java → entity ↔ dto dönüşümlerini ekle.

-------------------------------------------------------------------------------
5. CEVAP FORMATİ
-------------------------------------------------------------------------------

[BE] tipindeki her cevap şu üç başlığı içermelidir:

- Keşif Özeti
  - Okunan dokümanlar
  - Hangi servis ve domain etkilendiği
  - Temel varsayımlar ve kısıtlar

- Tasarım
  - Endpoint imzaları (path, method, DTO’lar)
  - Service metotları ve sorumlulukları
  - Repository kullanımı / query yaklaşımı
  - Transaction, security, exception stratejisi

- Uygulama Adımları
  - Her satır: ilgili dosya yolu + yapılacak değişiklik
  - Detaylı kod gövdesi yerine, görev listesi verilmelidir.

-------------------------------------------------------------------------------
6. MİKROSERVİS SINIR KURALI
-------------------------------------------------------------------------------

- Bir mikroservis başka bir servisin model, service veya repository sınıfını
  doğrudan import edemez.
- Servisler arası iletişim sadece:
  - REST (HTTP client),
  - event/queue,
  - ortak paket (packages/common-*)  
  üzerinden yapılmalıdır.
- Ortak domain veya util kodu packages/ veya common-* modüllerinde tutulur.

-------------------------------------------------------------------------------
7. TEST VE KALİTE BEKLENTİLERİ
-------------------------------------------------------------------------------

- Service katmanı için unit test yazılması beklenir.
- Kritik endpoint’ler için integration test (SpringBootTest + MockMvc/WebTestClient).
- Önemli mapper / converter sınıfları için kısa testler.
- Mümkünse Testcontainers ile izole DB testleri.

Agent tasarım yaparken:
- Hangi noktaların test edileceğini Tasarım bölümünde işaretlemelidir.

-------------------------------------------------------------------------------
8. NOTLAR
-------------------------------------------------------------------------------

- DTO / Model ayrımı sıkı tutulmalıdır; controller katmanı model ile konuşmaz.
- @Transactional sadece service katmanında kullanılmalı, controller veya repository’de kullanılmamalıdır.
- Logging, telemetry ve error response formatı STYLE-BE-001 ve ilgili logging
politikalarına uygun olmalıdır.

-------------------------------------------------------------------------------
9. ÖZET
-------------------------------------------------------------------------------

Bu dosya, backend görevlerinde agent’ın:
- Hangi dokümanları okuyacağını,
- Nasıl keşif ve tasarım yapacağını,
- Nasıl dosya bazlı görev listesi üreteceğini

net şekilde tanımlar ve backend geliştirme için referans davranış seti olarak
kullanılır.
