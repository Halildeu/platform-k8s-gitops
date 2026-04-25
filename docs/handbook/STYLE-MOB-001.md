# STYLE-MOB-001 – Mobil Kodlama Stili (Compact Version)

Bu doküman, `mobile/` klasörü altındaki mobil uygulama için kodlama, yapı ve
stil kurallarını tanımlar. Amaç: mobil tarafta tutarlı, okunabilir ve
offline-first yaklaşımı destekleyen bir mimari sağlamaktır.

-------------------------------------------------------------------------------
1. GENEL PRENSİPLER
-------------------------------------------------------------------------------

- UI → mümkün olduğunca “saf” (presentational) komponentler.
- İş mantığı → feature, hook veya service katmanında.
- Dosya ve klasör yapısı MOBILE-PROJECT-LAYOUT ile tutarlı olmalıdır.
- Hard-coded renk/spacing yasaktır; tema/tokens üzerinden çalışılır.
- Offline-first yaklaşımı tercih edilir.

-------------------------------------------------------------------------------
2. DOSYA & İSİMLENDİRME KURALLARI
-------------------------------------------------------------------------------

- Ekranlar (screens) → PascalCase + Screen sonu:
  UserListScreen.tsx, LoginScreen.tsx
- Feature hook’ları → camelCase + use prefix:
  useLogin(), useOfflineQueue()
- Service fonksiyonları → domain + eylem:
  userApi.fetchUsers(), cameraService.takePhoto()
- Dosya isimleri:
  login.api.ts, login.types.ts, login.hooks.ts gibi anlamlı, domain bazlı.

-------------------------------------------------------------------------------
3. SCREEN (EKRAN) STANDARTLARI
-------------------------------------------------------------------------------

- screens/ sadece:
  - navigation parametrelerini okur,
  - ilgili feature bileşenlerini compose eder,
  - UI’yı gösterir.
- İş mantığı ekran içinde yazılmaz.
- Ekran state’i minimum düzeyde tutulur (örn. local UI state).

-------------------------------------------------------------------------------
4. FEATURE MODÜLÜ STANDARTLARI
-------------------------------------------------------------------------------

features/<feature>/
  UI bileşenleri + hook + api + types birlikte yer alır.

Örn: features/login/
  LoginForm.tsx        → UI bileşeni
  useLogin.ts          → login akışının state + side-effect mantığı
  login.api.ts         → API çağrıları
  login.types.ts       → request/response modelleri

Prensip:
- Feature kendi kendine yeten bir modül gibi tasarlanır.
- Ekranlar feature’den sadece “hazır fonksiyonellik” alır.

-------------------------------------------------------------------------------
5. COMPONENT STANDARTLARI (components/)
-------------------------------------------------------------------------------

- Küçük, tekrar kullanılabilir UI blokları burada yaşar.
- Stateless ve side-effect’siz olmalıdır.
- Component yalnızca props → UI dönüştürür.
- Styling:
  - Mümkünse tema/tokens üzerinden, inline magic değerler olmadan.

-------------------------------------------------------------------------------
6. STATE YÖNETİMİ
-------------------------------------------------------------------------------

- Uygulama genel state’i → store/ içinde:
  store/
    index.ts
    slices/
    actions/
    selectors/
- Gerçekten global olan bilgiler (session, theme, network status) burada tutulur.
- Feature içi state → feature hook’larında (örn. useLogin()).
- Ekranlar:
  - store selector’ları veya feature hook’larını kullanır,
  - kendi içinde sadece küçük UI state (modal açık mı vb.) tutar.

-------------------------------------------------------------------------------
7. SERVICES & DEVICE ACCESS
-------------------------------------------------------------------------------

services/
  api/           → HTTP client, backend entegrasyonu
  storage/       → AsyncStorage / SecureStorage erişimi
  device/        → Kamera, sensör, lokasyon gibi native özellikler
  notifications/ → Push bildirim yönetimi
  network/       → Online/offline durum takibi

Kurallar:
- Ekran veya component içinde fetch, storage veya device API çağrısı yapılmaz.
- Tüm IO işlemleri services/ katmanı üzerinden yürür.
- services fonksiyonları mümkün olduğunca saf ve test edilebilir olmalıdır.

-------------------------------------------------------------------------------
8. THEME & TASARIM SİSTEMİ
-------------------------------------------------------------------------------

theme/
  colors.ts, spacing.ts, typography.ts, shadows.ts, tokens-map.ts

Kurallar:
- Renk, spacing, font büyüklüğü, radius gibi değerler theme’den veya design
  tokens mapping’inden alınır.
- Hard-coded literal değerlerden kaçınılır.
- Dark mode / theme switching buradan yönetilir.

-------------------------------------------------------------------------------
9. TEST STANDARTLARI
-------------------------------------------------------------------------------

tests/
  unit/        → hook, service ve pure logic testleri
  integration/ → screen + feature etkileşimi
  mocks/       → device API, network, storage mock’ları

Öncelik:
- Device service’leri (kamera, lokasyon, storage) test edilmeli.
- Offline sync mekanizması (queue → retry → sync) test edilmeli.
- Kritik form / navigation akışları test edilmeli.

-------------------------------------------------------------------------------
10. OFFLINE-FIRST VE SENKRONİZASYON
-------------------------------------------------------------------------------

- Veri girişi mümkünse offline modda da yapılabilmelidir.
- local queue mekanizması:
  - Kuyruk yönetimi services katmanında yapılır, ekran/feature içine gömülmez.
  - Retry stratejileri merkezi olarak tanımlanır.
- Network durumu:
  - store + özel hook (örn. useNetworkStatus) ile takip edilir.
  - UI, network state’e göre davranış değiştirir (örn. offline banner).

-------------------------------------------------------------------------------
11. AGENT DAVRANIŞ REHBERİ
-------------------------------------------------------------------------------

[MOB] tipinde bir görevde agent:

1. AGENT-CODEX.core.md ve AGENTS.md’yi dikkate alır.
2. MOBILE-PROJECT-LAYOUT.md ile hangi klasöre dokunacağını belirler.
3. Bu dosya (STYLE-MOB-001.md) üzerinden:
   - ekran/feature ayrımına,
   - services katmanına,
   - state & theme kurallarına uyar.
4. Cevap formatı:
   - Keşif Özeti
   - Mobil Tasarım
   - Uygulama Adımları (dosya yolu + yapılacak değişiklik)

-------------------------------------------------------------------------------
12. ÖZET
-------------------------------------------------------------------------------

Bu stil dokümanı:
- mobil klasör yapısını,
- ekran/feature/service/store ayrımını,
- offline-first yaklaşımını,
- test ve tema kullanımını

minimal ama net kurallarla tarif eder ve mobil geliştirme için tek referans noktasıdır.