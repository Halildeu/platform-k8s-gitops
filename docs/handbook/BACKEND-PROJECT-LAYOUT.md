# BACKEND-PROJECT-LAYOUT

Bu doküman, `backend/` klasörünün mimarisini, alt klasörlerin sorumluluklarını ve
Spring Boot tabanlı mikroservis yapısının nasıl organize edildiğini tarif eder.
Amaç: Backend tarafında tüm servislerin aynı yapısal prensiplere göre
geliştirilmesini ve agent’ların bu yapıyı doğru okumasını sağlamak.

Dokümanlarla ilgili genel kurallar ve numaralandırma için:
- docs/00-handbook/DOCS-PROJECT-LAYOUT.md  
- NUMARALANDIRMA-STANDARDI.md  
dokümanları referans alınmalıdır.

-------------------------------------------------------------------------------
1. ÜST DÜZEY DİZİN YAPISI
-------------------------------------------------------------------------------

backend/
 ├── .mvn/                    Maven wrapper
 ├── .vscode/                 IDE ayarları
 ├── api-gateway/             API Gateway servisi
 ├── auth-service/            Kimlik doğrulama servisi
 ├── common-auth/             Ortak auth bileşenleri (token/claims vs.)
 ├── core-data-service/       Ortak veri/metadata servisi
 ├── discovery-server/        Service registry (Eureka vs.)
 ├── file-service/            Dosya yönetimi servisi
 ├── mail-service/            E-posta servisi
 ├── notification-service/    Bildirim servisi
 ├── permission-service/      Yetki/izin yönetimi servisi
 ├── theme-service/           Tema/ayarla ilgili backend servisi
 ├── user-service/            Kullanıcı yönetimi servisi (örnek)
 ├── variant-service/         Variant/feature flag servisi
 ├── infra/                   Altyapı (Docker compose, k8s manifest vb.)
 ├── manifest/                Sistem manifestleri / config profilleri
 ├── packages/                Ortak Java kütüphaneleri (shared libs)
 ├── policy-templates/        Politika şablonları (örn. authz, security)
 ├── scripts/                 Build / deploy / maintenance script’leri
 ├── stories/                 Backend’e özel doc veya örnekler
 ├── telemetry/               Observability / tracing / metrics setup
 ├── logs/                    Log dosyaları (lokal geliştirme)
 ├── docs/                    Backend’e özel teknik dokümanlar
 ├── tests/                   Servisler arası entegrasyon / sistem testleri
 ├── test-results/            Test çıktı klasörleri
 ├── target/                  Root build çıktıları (varsa)
 └── pom.xml                  Çok modüllü Maven projesi root POM’u

Not: Servis listesi zamanla genişleyebilir; yukarıdaki isimler örnek ve mevcut
duruma referans olacaktır.

-------------------------------------------------------------------------------
2. HER SERVİSİN İÇ YAPISI (ÖRNEK: user-service)
-------------------------------------------------------------------------------

Her mikroservis, örneğin `user-service`, aşağıdaki yapıyı izler:

user-service/
 ├── .vscode/ (opsiyonel)
 ├── src/
 │    ├── main/
 │    │    ├── java/com/example/user/
 │    │    │    ├── authz/          → Yetkilendirme ile ilgili sınıflar
 │    │    │    ├── config/         → Konfigürasyon (Beans, @Configuration vs.)
 │    │    │    ├── controller/     → REST controller’lar
 │    │    │    ├── dto/            → Data Transfer Object’ler
 │    │    │    ├── model/          → Domain modelleri / entity’ler
 │    │    │    ├── permission/     → İzin modelleri ve mantığı
 │    │    │    ├── repository/     → Spring Data repository’leri
 │    │    │    ├── security/       → Security konfigürasyonu / filtreler
 │    │    │    ├── service/        → İş mantığı (service katmanı)
 │    │    │    ├── serviceauth/    → Servisler arası auth yardımcıları (varsa)
 │    │    │    └── UserApplication.java → Spring Boot main class
 │    │    └── resources/
 │    │         ├── application.yml / properties  → Konfigürasyon
 │    │         └── diğer resource’lar
 │    └── test/
 │         └── java/...             → Unit / integration testleri
 ├── Dockerfile                     → Servis Docker imajı
 ├── pom.xml                        → Servise ait POM
 └── target/                        → Build çıktıları (compile/test paketleri)

Genel prensipler:
- `controller` sadece HTTP/REST seviyesini yönetir, iş mantığı `service` katmanındadır.
- `dto` ile `model` açıkça ayrılır; mapping için ayrı mapper katmanı veya tool kullanılır.
- `repository` sadece veri erişiminden sorumludur.
- `config` ve `security` cross-cutting konuları kapsar.

-------------------------------------------------------------------------------
3. ORTAK MODÜLLER VE ALTYAPI
-------------------------------------------------------------------------------

common-auth/
- JWT, token işleme, ortak security helper’ları.
- Birden fazla serviste tekrar eden auth kodunu merkezi hale getirmek için
kullanılır.

packages/
- Ortak domain veya util kütüphaneleri (örneğin common-dto, common-utils).
- Servisler bu paketleri Maven dependency olarak kullanır.

infra/
- Docker Compose, Kubernetes manifest’leri, lokal/CI altyapı dosyaları.

manifest/
- Profil bazlı konfigurasyon manifest’leri, environment mapping’leri.

policy-templates/
- Yetkilendirme / güvenlik / politika tanımlarına dair şablon YAML/JSON’lar.

telemetry/
- OpenTelemetry / Prometheus / Grafana gibi observability araçları için
konfigürasyon.

scripts/
- Build, test, CI, veri migrate etme, lokal ortam hazırlama gibi scriptler.

-------------------------------------------------------------------------------
4. TEST VE QUALITY KATMANI
-------------------------------------------------------------------------------

tests/
- Servisler arası entegrasyon testleri, end-to-end backend senaryoları.
- Örneğin API Gateway + birkaç mikroservisin birlikte test edildiği akışlar.

test-results/
- Test çıktı klasörleri (raporlar, coverage vs.).

stories/
- Backend’e özgü örnek senaryolar, fixture’lar veya doküman destek dosyaları.

logs/
- Lokal geliştirme sırasında üretilen log’lar (genelde .gitignore edilir).

-------------------------------------------------------------------------------
5. KOD YERLEŞİM KURALLARI
-------------------------------------------------------------------------------

- Yeni bir mikroservis eklerken:
  - backend/ altında `<isim>-service` veya benzer anlamlı bir klasör açılır.
  - İç yapısı user-service’teki standardı takip eder (src/main/java/.../config,
    controller, service, repository, model, dto, security, test).
  - Zorunlu iskelet doğrulaması için:
    - `python3 scripts/check_backend_service_layout.py`

- Ortak kod:
  - Birden fazla servisin kullandığı util / dto / auth mantığı packages/ veya
    common-* modüllerinde tutulur.
  - Servisler birbirlerinin `src` içeriğini import etmez; sadece dependency
    olarak diğer modülleri ekler.

- Config:
  - Ortak konfigürasyonlar gerekirse infra/ veya manifest/ altına alınır;
    servis içinde sadece ilgili servise özgü config kalır.
  - Shared Postgres kullanılan lokal compose senaryosunda her servis kendi
    Flyway history tablosunu kullanır.
  - Shared Postgres üzerinde hedef model servis bazlı schema ownership'tir.
  - Her servis config'inde `<SERVICE>_DB_SCHEMA` env anahtarı tanımlanır.
  - Fresh bootstrap re-baseline gerekiyorsa servis altında ayrıca
    `src/main/resources/db/migration_schema_owned/` klasörü tutulur.
  - Bu zincir varsayılan olmaz; yalnız `*_FLYWAY_LOCATIONS` override ile aktif edilir.
  - Sonradan eklenen servis boş olmayan ortak şemaya ilk kez bağlanıyorsa
    `baseline-on-migrate=true` ve uygun baseline versiyonu ile ayağa kalkmalıdır.
  - Başka servise ait tabloya migration ile dokunulmaz; böyle bir ihtiyaç varsa
    ilgili servis kendi migration zincirinde sahip olduğu tabloyu günceller.
  - Versioned Flyway dosyaları geçmişte uygulanmışsa doğrudan içerik değiştirilmez;
    gerekli düzeltme yeni migration, bootstrap veya re-baseline planı ile yapılır.

- Servisler arası HTTP istemcisi:
  - Yeni baseline `WebClient`’tır.
  - `RestTemplate` yalnız mevcut legacy kodda geçici olarak tutulur.
  - Yeni servis veya yeni iç servis çağrısı eklenirken `RestTemplate` tercih edilmez.

-------------------------------------------------------------------------------
6. AGENT KULLANIM REHBERİ
-------------------------------------------------------------------------------

[BE] tipindeki bir görevde agent şu sırayı izlemelidir:

1. AGENT-CODEX.core.md
2. AGENTS.md
3. BACKEND-PROJECT-LAYOUT.md (bu dosya)
4. STYLE-BE-001.md (backend kod stili)
5. İlgili servis klasörü:
   - backend/<servis-adı>/
   - src/main/java/... içindeki katmanlar (controller, service, repository, model, dto, security)
6. Gerekirse:
   - docs/02-architecture/services/<servis-adı>/TECH-DESIGN-*.md
   - DATA-MODEL-*.md
   - ADR-*.md

Cevap formatı:
- Keşif Özeti
- Tasarım (endpoint/servis imzaları, katmanlar, transaction & security notları)
- Uygulama Adımları (dosya yolu + yapılacak değişiklikler)

-------------------------------------------------------------------------------
7. ÖZET
-------------------------------------------------------------------------------

Bu layout:

- Mikroservislerin nerede ve nasıl konumlandığını,
- Her servisin iç katmanlarının sorumluluklarını,
- Ortak modüllerin ve altyapının nasıl organize edildiğini

tek bir yerde tanımlar ve backend ekibi ile agent’lar için
**tek doğruluk kaynağı** olarak kullanılmalıdır.
