# STYLE-BE-001 – Backend Kodlama Stili (Compact Version)

Bu doküman, backend microservice kodlarının tutarlı, okunabilir ve sürdürülebilir
şekilde yazılması için gerekli minimum kuralları tanımlar. Tüm Spring Boot servisleri
(user-service, variant-service, permission-service vb.) bu standartlara uymalıdır.

-------------------------------------------------------------------------------
1. PAKET / MODÜL YAPISI
-------------------------------------------------------------------------------

Her servis aşağıdaki paket yapısını izler:

src/main/java/com/example/<service>/
  config/         → Bean tanımları, app config
  controller/     → REST API uçları
  dto/            → Request/response modelleri
  model/          → Domain modelleri / entity'ler
  repository/     → Veri erişimi (JPA veya custom repo)
  service/        → Business logic
  security/       → Security config, filter, token validator
  exceptions/     → Global veya domain spesifik exception'lar
  mapper/         → DTO <-> Model dönüşüm katmanı (zorunlu değil ama önerilir)
  util/           → Küçük yardımcı sınıflar (minimum tutulur)

Test klasörü:
src/test/java/com/example/<service>/

-------------------------------------------------------------------------------
2. CONTROLLER STANDARTLARI
-------------------------------------------------------------------------------

- Controller sadece HTTP katmanıdır; business logic **service** katmanındadır.
- İsimlendirme: <Entity>Controller (ör: UserController)
- Mapping:
  - GET /api/v1/users
  - POST /api/v1/users
  - GET /api/v1/users/{id}
- Controller DTO ile konuşur; model ile doğrudan asla dönülmez.
- Validation:
  - @Valid + javax validation annotation'ları zorunludur.
- Hata yönetimi:
  - GlobalExceptionHandler kullanılmalı.
  - ResponseEntity hiçbir yerde “ham” yazılmamalı → helper kullanılabilir.

-------------------------------------------------------------------------------
3. SERVICE KATMANI
-------------------------------------------------------------------------------

- İş kuralları service katmanında olur.
- Service interface + implementation kullanımı opsiyoneldir ama büyüyen
servislerde önerilir.
- Transaction:
  - @Transactional sadece service katmanında kullanılmalıdır.
- İsimlendirme: <Entity>Service (UserService, VariantService)
- Service metotları minimal olmalı; tek sorumluluk prensibi gözetilir.

-------------------------------------------------------------------------------
4. REPOSITORY KATMANI
-------------------------------------------------------------------------------

- Spring Data JPA tercih edilir.
- İsimlendirme: <Entity>Repository
- Custom query gerekiyorsa:
  - @Query veya QueryDSL kullanılabilir.
- Dış dünyaya model döner; DTO ile işiniz yoktur.

-------------------------------------------------------------------------------
5. DTO KULLANIM STANDARTLARI
-------------------------------------------------------------------------------

- Controller giriş/çıkışları DTO’dur.
- Ayrım:
  - CreateUserRequest, UpdateUserRequest
  - UserResponse
- DTO → Model dönüşümü mapper katmanı üzerinden yapılır.
- Model ile DTO’nun karışması yasaktır.

-------------------------------------------------------------------------------
6. MODEL / ENTITY STANDARTLARI
-------------------------------------------------------------------------------

- Model domain’i temsil eder; persistence annotation’ları içerir.
- equals/hashCode → only id bazlı veya Lombok @EqualsAndHashCode(onlyExplicitlyIncluded = true)
- Entity üzerinde iş mantığı minimum tutulur (DDD aggregate root ihtiyacı yoksa).

-------------------------------------------------------------------------------
7. SECURITY STANDARTLARI
-------------------------------------------------------------------------------

- Security config her serviste net ayrılmalıdır:
  - SecurityConfig.java
  - TokenValidator / JwtAuthFilter
  - Path bazlı izin tanımları
- Role/scope kontrolü:
  - Method-level → @PreAuthorize("hasAuthority('X')")
  - API Gateway üzerinden scope propagate edilir.

-------------------------------------------------------------------------------
8. MAPPER KULLANIMI (ÖNERİLEN)
-------------------------------------------------------------------------------

- MapStruct veya manuel mapper.
- Controller/service hiçbir zaman doğrudan new DTO veya new Model yapmamalıdır.
- Örnek:
  UserMapper.toResponse(entity)

-------------------------------------------------------------------------------
9. EXCEPTION YÖNETİMİ
-------------------------------------------------------------------------------

- GlobalExceptionHandler zorunludur.
- Domain spesifik exception örnekleri:
  - UserNotFoundException
  - PermissionDeniedException
- Exception → error response mapping sabit olmalıdır:
  code, message, timestamp, path.

-------------------------------------------------------------------------------
10. LOGGING & TELEMETRY
-------------------------------------------------------------------------------

- Her servis Logback ile yapılandırılır.
- Service method entry/exit log yazılmaz → sadece kritik olaylar loglanır.
- TraceID/SpanID zorunlu; tüm log formatı distributed tracing ile uyumlu olur.
- Metrics:
  - request_count
  - request_duration
  - error_count
- Health check:
  - /actuator/health zorunlu.

-------------------------------------------------------------------------------
11. CONFIG YÖNETİMİ
-------------------------------------------------------------------------------

- application.yml sadece servise özel config içerir.
- Ortak config (auth, jwt, redis vs.) → common-auth veya shared packages’da tutulur.
- Profile kullanımı:
  - application-local.yml
  - application-dev.yml
  - application-prod.yml
- Shared database kullanılan development/compose senaryosunda:
  - Her servis kendi Flyway history tablosunu tanımlar.
  - Her servis için hedef schema ownership önceden tanımlanır:
    `auth_service`, `user_service`, `permission_service`, `variant_service`,
    `core_data_service`.
  - Runtime cutover yapılana kadar varsayılan schema `public` kalabilir; ancak
    config katmanında servis bazlı schema env anahtarı tanımlı olmak zorundadır.
  - Sonradan eklenen servis için boş olmayan ortak şemada ilk boot gerekiyorsa
    `baseline-on-migrate=true` kullanılır.
  - Başlangıç migration'ının gerçekten çalışması gerekiyorsa baseline versiyonu
    migration zinciriyle uyumlu ayarlanır.
  - Schema cutover öncesinde cross-service SQL bağımlılığı kalmamalıdır.

-------------------------------------------------------------------------------
12. TEST STANDARTLARI
-------------------------------------------------------------------------------

- Unit test zorunludur (service katmanı).
- Integration test:
  - @SpringBootTest
  - gerçek DB yerine Testcontainers önerilir.
- Controller testleri:
  - MockMvc veya WebTestClient
- Mapper testleri kısa ama zorunludur.

-------------------------------------------------------------------------------
13. MİKROSERVİS SINIRLARI
-------------------------------------------------------------------------------

Yasaklar:
- Bir servis, başka servisin model veya service sınıfını import edemez.
- Servisler arası iletişim sadece:
  - REST
  - event
  - shared package interface’leri  
üzerinden yapılır.

Servisler arası HTTP istemcisi standardı:
- Yeni veya dokunulan service-to-service HTTP kodunda `WebClient` kullanılmalıdır.
- Yeni `RestTemplate` kullanımı eklenmez.
- Mevcut `RestTemplate` kullanan kodlar legacy kabul edilir ve kademeli migrate edilir.
- Discovery/load-balanced çağrılarda istemci standardı servis bazında bölünmez.

Veri ownership standardı:
- Her tablo tek bir backend servisine aittir.
- Başka bir servisin tablosuna SQL ile yazmak veya migration içinde dokunmak
  yasaktır.
- Cross-service veri ihtiyacı HTTP/API veya event ile çözülür.
- Uygulanmış versioned Flyway migration dosyaları yerinde değiştirilmez.
- Tarihsel migration ownership ihlali varsa çözüm:
  - yeni ownership tarafında bootstrap/fix mekanizması kurmak
  - ardından kontrollü re-baseline veya migration rechain planı çıkarmaktır.
- Fresh bootstrap için temiz zincir gerekiyorsa aktif `db/migration` yanında
  ayrı `db/migration_schema_owned` hattı açılır; aktif runtime ancak açıkça
  `*_FLYWAY_LOCATIONS` override edildiğinde bu hatta geçer.

-------------------------------------------------------------------------------
14. AGENT DAVRANIŞ REHBERİ
-------------------------------------------------------------------------------

[BE] tipindeki bir görevde agent şu sırayı izler:
1. AGENT-CODEX.core.md
2. AGENTS.md
3. BACKEND-PROJECT-LAYOUT.md
4. STYLE-BE-001.md (bu dosya)
5. Hangi servis etkileniyorsa onun src/main/java/... yapısına bakar
6. Gerekirse TEKNOLOJI TASARIM (TECH-DESIGN) dokümanlarını okur

Agent’ın üreteceği çıktı formatı:
- Keşif Özeti
- Tasarım (endpoint, service metodu, transaction, security)
- Uygulama Adımları (dosya yolu + yapılacak değişiklik)

-------------------------------------------------------------------------------
15. ÖZET
-------------------------------------------------------------------------------

Bu doküman Spring Boot tabanlı mikroservisler için zorunlu backend stil
kurallarını içerir:
- controller → service → repository ayrımı
- DTO / model ayrımı
- token/security standardı
- logging / telemetry standardı
- test ve exception yönetimi

Agent’lar ve insanlar için backend geliştirme rehberidir.

-------------------------------------------------------------------------------
16. STORY ID REFERANSI (DOKÜMAN ↔ KOD İZLENEBİLİRLİĞİ)
-------------------------------------------------------------------------------

- Bir STORY dokümanı (örn. `STORY-0002-backend-keycloak-jwt-hardening.md`)
  backend tarafında uygulanıyorsa:
  - En az bir **test** veya **kod** dosyasında ilgili STORY ID açıkça
    referans verilmelidir.
- Önerilen kullanım şekilleri:
  - JUnit display name:
    - `@DisplayName("STORY-0002 – Backend Keycloak JWT Hardening")`
  - Test veya kod yorum satırı:
    - `// STORY-0002-backend-keycloak-jwt-hardening`
  - Commit mesajında STORY ID kullanımı teşvik edilir, ancak bu stil kuralı
    özellikle kod/test dosyası içinde görünür ID referansını zorunlu kılar.
- Bu sayede:
  - `docs/03-delivery/PROJECT-FLOW.md` içindeki STORY satırları ile
    backend kodu arasındaki ilişki, otomatik script’ler tarafından
    (örn. `check_arch_vs_code.py` ve ileride eklenecek STORY↔kod kontrolleri)
    daha kolay izlenebilir hale gelir.
