# INDEX

## Amaç

Bu doküman, `/Users/halilkocoglu/Documents/dev` reposunun şu an gerçekten nasıl
çalıştığını kod ve konfigürasyon üzerinden özetler.

Amaç:
- Geliştirmeye başlamadan önce mevcut sistemi doğru anlamak.
- Gerçek çalışan mimari ile dokümanlanan hedef mimari arasındaki farkları görmek.
- Bundan sonraki servis ve modül tasarımlarını aynı çizgide üretmek için bir
  başlangıç zemini oluşturmak.

## Kapsam

İnceleme aşağıdaki alanları kapsar:
- `backend/` çok modüllü Spring Boot mikroservis yapısı
- `web/` React + Module Federation mikro frontend yapısı
- gateway, discovery, auth, database ve secret/config akışı
- mevcut dokümanlar ile kod arasındaki mimari drift alanları

## Kanıt Kaynakları

Bu analiz aşağıdaki ana kaynaklara dayanır:
- `backend/pom.xml`
- `backend/docker-compose.yml`
- `backend/*/src/main/resources/application*.properties`
- `backend/core-data-service/src/main/resources/application.yml`
- `backend/*/src/main/java/**/controller/*.java`
- `web/package.json`
- `web/apps/*/webpack.dev.js`
- `web/apps/mfe-shell/src/app/auth/auth-config.ts`
- `web/packages/shared-http/src/index.ts`
- `web/docs/01-architecture/01-shell/01-frontend-architecture.md`
- `scripts/check_arch_vs_code.py`
- `scripts/check_backend_service_layout.py`

Operasyonel görünürlük artefact'ları:
- `docs/02-architecture/runtime/service-communication-matrix.md`
- `docs/02-architecture/runtime/secret-source-matrix.md`
- `docs/02-architecture/runtime/runtime-dependency-matrix.md`
- `docs/02-architecture/services/service-doc-status.v1.json`

## Üst Seviye Mimari Özeti

Repo şu an iki ana çalışma alanı içerir:

1. `backend/`
- Java 21 + Spring Boot 3.2 tabanlı çok modüllü mikroservis yapısı.
- Servis keşfi için Eureka kullanılır.
- Edge katmanında Spring Cloud Gateway bulunur.
- Kalıcılık için PostgreSQL ve Flyway kullanılır.
- Secret tasarımında hedef Vault'tur; fakat local/docker profillerinde env fallback
  yoğun biçimde kullanılır.

2. `web/`
- React 18 + TypeScript + Webpack 5 + Module Federation tabanlı mikro frontend
  yapısı.
- `mfe-shell` host uygulamadır.
- Domain bazlı remote MFE'ler shell içine bağlanır.
- Ortak HTTP istemcisi `packages/shared-http`, ortak UI katmanı `packages/ui-kit`
  üzerinden paylaşılır.

## Gerçek Runtime Topolojisi

İstemci akışı:
- Tarayıcı → `mfe-shell` ve remote MFE'ler
- Frontend → `/api` üzerinden `api-gateway`
- Gateway → Eureka discovery
- Discovery → ilgili backend servisi
- Servisler → PostgreSQL, Keycloak, Vault ve diğer servisler

Operasyonel bileşenler:
- `discovery-server` → servis keşfi
- `api-gateway` → tek giriş noktası
- `postgres-db` → ortak veritabanı konteyneri
- `keycloak` → kullanıcı OIDC/JWT kaynağı
- `vault` + `vault-unseal` → secret hedef kaynağı
- `observability-prometheus` + `observability-grafana` → gözlemlenebilirlik

## Backend Servis Envanteri

`backend/pom.xml` içindeki aktif modüller:
- `common-auth`
- `discovery-server`
- `api-gateway`
- `auth-service`
- `permission-service`
- `user-service`
- `variant-service`
- `core-data-service`

### Servis Haritası

| Servis | Varsayılan Port | Ana Sorumluluk | Giriş Path'leri | Önemli Bağımlılıklar |
| --- | --- | --- | --- | --- |
| `api-gateway` | 8080 | Tek giriş noktası, route ve JWT doğrulama | `/api/**`, `/api/v1/**` | Eureka, auth/user/permission/variant/core-data |
| `discovery-server` | 8761 | Eureka registry | registry | tüm backend servisleri |
| `auth-service` | 8088 | login/register, password reset, service token minting, service JWKS | `/api/auth/**`, `/api/v1/auth/**`, `/oauth2/token`, `/oauth2/jwks` | user-service, permission-service, Postgres, Keycloak/Vault |
| `user-service` | 8089 | kullanıcı yönetimi, aktivasyon, profil ve bazı internal provisioning akışları | `/api/users/**`, `/api/v1/users/**`, `/api/v1/notification-preferences/**` | permission-service, auth-service, Postgres |
| `permission-service` | 8090 | **OpenFGA Hub** (D-003/D-008): roller, izinler, authz scope, audit event + TupleSyncService + AuthzVersionService + AuthorizationControllerV1 | `/api/access/**`, `/api/permissions/**`, `/api/audit/**`, `/api/v1/roles/**`, `/api/v1/permissions/**`, `/api/v1/authz/**` (me, check, batch-check, explain, version, catalog) | Postgres, **OpenFGA**, Keycloak/Vault |
| `variant-service` | 8091 | grid variant, kullanıcı tercihleri, tema ve theme registry | `/api/variants/**`, `/api/v1/variants/**`, `/api/v1/themes/**`, `/api/v1/me/theme/**`, `/api/v1/theme-registry/**` | permission-service, Postgres |
| `core-data-service` | random (`server.port=0`) | şirket ana verisi | `/api/v1/companies/**` | Postgres, Eureka |
| `common-auth` | library | ortak auth, permission sabitleri, JWT yardımcıları | yok | tüm servisler |

### Backend İçin Kritik Notlar

- Repo gerçekte mikroservistir; `backend/README.md` başlığı hâlâ "Monolit" der.
- `core-data-service` kodda vardır ve gateway route'u tanımlıdır; fakat mevcut
  `docker-compose.yml` içinde servis olarak ayağa kaldırılmamaktadır.
- `permission-service` **OpenFGA Hub** rolünü üstlenir (D-003/D-008 FINAL, 2026-04-14):
  rol/izin/audit yönetimi + OpenFGA tuple senkronizasyonu + kullanıcı-facing authz API.
  Port 8090 aktif. Kaldırılamaz (C-005 HARD CONSTRAINT). Diğer servisler check işlemleri
  için bu servise HTTP çağrısı yapmaz; `OpenFgaAuthzService` (common-auth) üzerinden
  doğrudan OpenFGA'ya erişir (C-008).
- `variant-service` hem grid variant hem de tema/theme-registry alanlarını taşır;
  bu da kişiselleştirme alanında coupling yaratır.

## Servisler Arası İletişim Modeli

### Kullanıcı İstek Akışı

1. Frontend istekleri `api-gateway`'e gider.
2. Gateway, route tanımına göre isteği `lb://<service>` ile hedef servise yollar.
3. Gateway ve servisler kullanıcı JWT'sini Keycloak JWKS/issuer bilgileri ile
   doğrular.

### İç Servis Akışı

Şu an iki ayrı istemci tarzı birlikte kullanılmaktadır:
- `RestTemplate`
- `WebClient`

Görülen örnekler:
- `auth-service` → `user-service`, `permission-service` çağrıları `RestTemplate`
- `user-service` → `permission-service` ve auth context çağrıları `RestTemplate`
- `variant-service` → `permission-service` çağrısı `WebClient`

Sonuç:
- Servisler arası iletişim discovery + load balancer mantığında doğrudur.
- Fakat istemci standardı tekilleşmemiştir.
- Gelecek servislerde tek bir istemci standardı seçilmelidir.

### İç Kimlik Doğrulama

Kullanıcı JWT akışı:
- Kaynak: Keycloak realm
- Tüketenler: gateway ve resource server servisleri

Servis JWT akışı:
- Kaynak: `auth-service`
- Endpoint'ler: `/oauth2/token` ve `/oauth2/jwks`
- Tüketenler: özellikle `user-service` gibi iç servisler

Sonuç:
- Kullanıcı auth ile servis auth arasında ikili bir model vardır.
- Bu model çalışıyor; ama dokümanda ve operasyonel kurallarda daha açık
  sabitlenmelidir.

## Database ve Kalıcılık Yapısı

Ortak eğilim:
- PostgreSQL kullanılıyor.
- Flyway aktif.
- Çoğu servis kendi tablo alanını aynı PostgreSQL instance'ında tutuyor.

Belirgin alan sahiplikleri:
- `user-service`
  - kullanıcı, aktivasyon, bazı tercih alanları
- `permission-service`
  - rol, izin, authz scope, audit event
- `variant-service`
  - grid variants, visibility, theme, theme registry seed verileri
- `core-data-service`
  - company master data

Önemli gözlem:
- Veritabanı tarafında servis bazlı tablo ayrımı var; bu iyi.
- Fakat aynı PostgreSQL instance paylaşılıyor.
- Kısa vadede kabul edilebilir; uzun vadede servis sınırları netleştiğinde
  sahiplik ve migration yönetimi daha görünür hale getirilmelidir.

## Secret ve Config Kaynağı

### Hedef Model

Kod ve dokümanlarda hedef secret kaynağı:
- Vault KV
- servis bazlı `vault.db.<service>.*`
- servis JWT için `vault.jwt.auth-service.*`

### Gerçek Çalışan Model

Local/docker profillerinde:
- `spring.cloud.vault.enabled=false`
- `.env` ve docker-compose environment değişkenleri yaygın biçimde kullanılıyor

Frontend tarafında:
- `.env.local.example` çok sınırlı örnek verir.
- Auth/gateway ayarları esas olarak runtime env üzerinden okunur.
- `shared-http` varsayılan olarak same-origin `/api` kullanır.
- `mfe-shell` auth config varsayılan olarak Keycloak `serban` realm + `frontend`
  client ile çalışır.

Sonuç:
- Secret modelinin kanonik hedefi Vault.
- Gerçek dev çalışma düzeni env/.env fallback ağırlıklıdır.
- Bu fark açıkça yönetilmezse ortamlar arasında drift üretir.

## Frontend Mimari Özeti

### Uygulama Yapısı

`web/package.json` altındaki aktif workspace'ler:
- `apps/mfe-shell`
- `apps/mfe-suggestions`
- `apps/mfe-ethic`
- `apps/mfe-users`
- `apps/mfe-access`
- `apps/mfe-audit`
- `apps/mfe-reporting`
- `packages/shared-http`
- `packages/ui-kit`
- `packages/shared-types`
- `packages/i18n-dicts`

### Frontend Rol Dağılımı

| Bileşen | Rol |
| --- | --- |
| `mfe-shell` | host uygulama, auth lifecycle, route/layout, shared shell services |
| `mfe-users` | kullanıcı yönetimi |
| `mfe-access` | rol ve yetki yönetimi |
| `mfe-audit` | audit görünümü |
| `mfe-reporting` | raporlama ve variant tüketimi |
| `mfe-ethic` | etik/uyum alanı |
| `mfe-suggestions` | öneri/demo alanı |
| `packages/ui-kit` | ortak UI bileşenleri |
| `packages/shared-http` | ortak axios/interceptor katmanı |

### Frontend İletişim Modeli

- `mfe-shell` dev server `3000` portunda ayağa kalkar.
- Shell, remote MFE'leri `3001`, `3002`, `3004`, `3005`, `3006`, `3007`
  portlarından federasyon ile yükler.
- Dev ortamında shell `/api` path'ini `http://localhost:8080` gateway'ine proxy eder.
- Ortak HTTP katmanı `shared-http` içinde çözülür.
- Varsayılan base URL `'/api'` olarak tanımlıdır; tam gateway URL yalnız env ile
  override edilir.

### Frontend Auth Modeli

- Varsayılan mod `keycloak`
- Varsayılan Keycloak URL: `http://localhost:8081`
- Varsayılan realm: `serban`
- Varsayılan client: `frontend`
- `permitAll` modu env ile açılabilir

Sonuç:
- Auth lifecycle shell merkezlidir.
- Remote MFE'lerin kendi auth başlatma davranışı olmamalıdır.
- Bu yön doğru kurulmuştur.

## Doküman ve Kod Arasındaki Drift Alanları

### 1. Üst Mimari Dokümanları Boştu

- `docs/02-architecture/SYSTEM-OVERVIEW.md` ve `DOMAIN-MAP.md` placeholder
  durumundaydı.
- Gerçek mimari bilgi kod ve config içine dağılmıştı.

### 2. Backend README Başlığı Yanlış

- Başlık monolit der.
- Kod ve build yapısı mikroservistir.

### 3. Gateway ve Auth Dokümanları Kısmen Geri Kalıyor

- Bazı notlar `auth-service` JWKS varsayılanını referans verir.
- Gerçek varsayılan kullanıcı JWT doğrulaması Keycloak `serban` realm üzerindedir.

### 4. Frontend Mimari Dokümanı Kısmen Stale

- `web/docs/01-architecture/01-shell/01-frontend-architecture.md` değerli bir
  kaynak ama bazı eski sapma notları güncel kodla tam örtüşmez.
- Örnek: router singleton riski artık webpack shared listesinde kapatılmış
  görünüyor.
- Örnek: gateway base URL dokümanda bazı yerlerde tam URL iken gerçek kodda `/api`.

### 5. Planlanan Servisler ile Gerçek Servisler Ayrışıyor

`scripts/check_arch_vs_code.py` mevcut dokümanlarda backend karşılığı olmayan
servis başlıklarını gösterir:
- `approval-system`
- `ethics-case-management`
- `fleet-operations`
- `ops`
- `theme-system`

Bu alanlar şu an fikir/gelecek tasarım düzeyinde; gerçek çalışan servis
değildir.

### 6. Legacy ve v1 API Birlikte Yaşıyor

- Kodda hem legacy path'ler hem `/api/v1/**` path'leri vardır.
- Bu geçiş dönemi yönetilmezse frontend/backend arasında fark yaratır.

### 7. İstemci Standardı Tek Değil

- Bazı servisler `RestTemplate`, bazıları `WebClient` kullanır.
- Yeni servisler için standart seçilmeden büyümek teknik borç üretir.

## Domain Haritası

### Aktif Domainler

| Domain | Sorumlu Bileşenler | Not |
| --- | --- | --- |
| Kimlik ve Oturum | `auth-service`, Keycloak, `common-auth` | kullanıcı auth + servis token minting birlikte |
| Yetki ve Denetim | `permission-service` | roles, permissions, authz scope, audit event tek serviste |
| Kullanıcı Yönetimi | `user-service` | kullanıcı CRUD, aktivasyon, internal provisioning |
| Kişiselleştirme ve Tema | `variant-service` | grid variant + theme + theme registry birlikte |
| Referans Veri | `core-data-service` | company master data |
| Edge ve Registry | `api-gateway`, `discovery-server` | giriş ve yönlendirme katmanı |
| Web Sunum Katmanı | `mfe-shell` + remote MFE'ler + `ui-kit` + `shared-http` | MFE tabanlı istemci |

### Planlı Ama Henüz Ayrışmamış Alanlar

| Hedef Alan | Şu anki Durum |
| --- | --- |
| `theme-system` | tema alanı fiilen `variant-service` içinde |
| `ethics-case-management` | frontend/doküman tarafında izleri var, çalışan backend servis değil |
| `approval-system` | doküman seviyesi, çalışan backend modülü yok |
| `fleet-operations` | doküman seviyesi, çalışan backend modülü yok |

## Bundan Sonraki Servis Mimarisine Zemin

Bu repo üzerinde yeni iş geliştirirken aşağıdaki baseline korunmalıdır:

### 1. Önce Gerçek Domain Sınırı, Sonra Kod

Yeni servis açmadan önce şu sorular cevaplanmalıdır:
- Bu iş mevcut domainlerden hangisine aittir?
- Var olan serviste kalması coupling'i artırır mı?
- Ayrı servis açılacaksa gerçekten ayrı sahiplik, veri ve yayın döngüsü var mı?

### 2. Aktif Servis Seti Kanonik Kabul Edilmelidir

Şu an için kanonik backend servis seti:
- `auth-service`
- `user-service`
- `permission-service`
- `variant-service`
- `core-data-service`
- `api-gateway`
- `discovery-server`

Yeni servis kararı, bu aktif sete göre gerekçelendirilmelidir.

### 3. Frontend Domainleri Aynı Sınırı Takip Etmelidir

Frontend modüller şu backend sınırlarına yaslanmalıdır:
- kullanıcı → `mfe-users` ↔ `user-service`
- yetki/audit → `mfe-access`/`mfe-audit` ↔ `permission-service`
- kişiselleştirme/tema/variant → `mfe-reporting` ve ilgili UI modülleri ↔ `variant-service`
- referans veri → ilgili MFE ↔ `core-data-service`

### 4. İletişim Kuralları Sabitlenmelidir

- Tarayıcı yalnız gateway ile konuşur.
- Servisler arası çağrı discovery üzerinden yapılır.
- İç çağrılarda tek istemci standardı seçilir.
- Kullanıcı auth ve servis auth modeli ayrı ama açık dokümante edilir.

### 5. Secret Politikası Netleştirilmelidir

- Kanonik kaynak Vault olmalıdır.
- `.env` yalnız local bootstrap kolaylığı olarak tanımlanmalıdır.
- Hangi secret'ın hangi kaynaktan okunacağı servis bazlı tabloya bağlanmalıdır.

### 6. Doküman Sırası Koddan Önce Gelmelidir

Yeni işlerde şu sıra izlenmelidir:
1. Problem/PRD
2. as-is etkilenen domain kontrolü
3. TECH-DESIGN
4. gerekiyorsa yeni servis kararı
5. API ve data model
6. kod

## Açık Riskler

- `core-data-service` compose zincirine bağlı değil; route var, çalışma yolu eksik.
- `permission-service` domain olarak çok genişliyor.
- `variant-service` içinde theme + variant coupling var.
- Secret yönetimi ortamlar arasında farklı davranıyor.
- Legacy API path'leri temizlenmeden yeni iş eklemek ek drift üretir.
- Planlı servislerin bir kısmı yalnız doküman seviyesinde kaldığı için ekip
  algısı ile gerçek runtime mimarisi ayrışabilir.

## Sonuç

Bu repo geliştirilmeye uygun bir temel içeriyor; fakat önce çalışan gerçek
mimariyi kanonik hale getirmek gerekir.

En doğru yaklaşım:
- önce mevcut çalışan servis sınırlarını sabitlemek,
- sonra drift alanlarını temizlemek,
- ardından yeni domainleri aynı çizgide açmaktır.

Bu dokümandan sonraki zorunlu okuma:
- `docs/02-architecture/runtime/service-communication-matrix.md`
- `docs/02-architecture/runtime/secret-source-matrix.md`
- `docs/02-architecture/runtime/runtime-dependency-matrix.md`
