# MOBILE-PROJECT-LAYOUT

Bu doküman, `mobile/` klasörü altında geliştirilen mobil uygulamanın yapı,
klasör organizasyonu ve mimari prensiplerini tanımlar. Amaç: web ve backend
tarafında olduğu gibi mobil geliştirmede de tutarlı, temiz ve genişleyebilir bir
mimari sağlamaktır.

-------------------------------------------------------------------------------
1. ÜST DÜZEY DİZİN YAPISI
-------------------------------------------------------------------------------

mobile/
 ├── android/              yerel android proje dosyaları
 ├── ios/                  yerel iOS proje dosyaları
 ├── assets/               ikon, font, görsel, splash ekranları
 ├── app/                  navigation, global providers, root component
 ├── components/           ortak UI bileşenleri
 ├── features/             use-case odaklı modüller (login, profile, camera vb.)
 ├── screens/              route-level ekranlar
 ├── services/             API client, local storage, device services
 ├── store/                global app state (redux, zustand, context)
 ├── utils/                yardımcı fonksiyonlar
 ├── hooks/                tekrar kullanılabilir mobil hook'lar
 ├── i18n/                 çeviri dosyaları
 ├── types/                ortak type/interface modelleri
 ├── theme/                renk, spacing, typography ve design token eşleştirmeleri
 ├── mocks/                local dev test mockları
 ├── tests/                unit / integration testleri
 └── app.json, package.json, metro.config.js vb. config dosyaları

-------------------------------------------------------------------------------
2. MODÜLER MİMARİ PRENSİBİ
-------------------------------------------------------------------------------

Mobil proje şu modüllere bölünür:

- app/      → navigation yapısı, root providers, global lifecycle
- screens/  → route-level UI compose; business logic içermez
- features/ → UI + logic birleşik use-case modülleri (login, scan, offline-sync)
- components/ → küçük, tekrar kullanılabilir UI elementleri
- services/ → API çağrısı, cache, secure-storage, kamera, konum vb.
- store/     → global state
- theme/     → design tokens → RN/Flutter ada­ptasyonu

Yeni geliştirmeler daima features → screens → app hiyerarşisine uyar.

-------------------------------------------------------------------------------
3. EKRAN (SCREEN) YAPISI
-------------------------------------------------------------------------------

Bir ekran sadece:
- ilgili feature bileşenlerini compose eder,
- navigation parametrelerini okur,
- UI gösterir.

İş mantığı ekran içinde yazılmaz.

Örnek ekran yapısı:
screens/
  UserListScreen.tsx
  UserDetailScreen.tsx

-------------------------------------------------------------------------------
4. FEATURE YAPISI
-------------------------------------------------------------------------------

Her feature kendi:
- UI bileşenleri
- hook’ları (örn. useLogin)
- servis adaptörleri
- input validation schema’ları

ile birlikte paketlenir.

Örnek:
features/login/
  LoginForm.tsx
  useLogin.ts
  login.api.ts
  login.types.ts

Bu yapı mobil tarafta **bağımsız geliştirme** ve **yeniden kullanılabilirlik** sağlar.

-------------------------------------------------------------------------------
5. SERVICES YAPISI
-------------------------------------------------------------------------------

services/
  api/               → API çağrı katmanı
  storage/           → AsyncStorage / SecureStorage yönetimi
  device/            → Kamera, sensör, lokasyon adaptörleri
  notifications/     → Push notification yönetimi
  network/           → online/offline durum kontrolü

Prensip:
- UI bileşenleri doğrudan fetch veya cihaz API’si çağırmaz.
- Tüm device ve API erişimleri bu klasör altından yapılır.

-------------------------------------------------------------------------------
6. STATE YÖNETİMİ
-------------------------------------------------------------------------------

store/
  index.ts
  slices/
  actions/
  selectors/

Kurallar:
- Global state yalnızca gerçekten global olan bilgiler içindir (session, theme).
- Feature içi state → use-case özel hook’larda tutulur.
- Ekranlar sadece store → selector veya hook → data kullanır.

-------------------------------------------------------------------------------
7. TASARIM VE TEMA
-------------------------------------------------------------------------------

theme/
  colors.ts
  spacing.ts
  typography.ts
  shadows.ts
  tokens-map.ts

Kurallar:
- Hard-coded renk/spacing yasaktır.
- Tüm görsel değerler design tokens temelli oluşturulur.
- Dark mode / theme switching buradan yönetilir.

-------------------------------------------------------------------------------
8. TEST STANDARTLARI
-------------------------------------------------------------------------------

tests/
  unit/        → hook ve logic testleri
  integration/ → screen + feature etkileşim testleri
  mocks/       → device/api mockları

Kapsama:
- device service testleri
- offline sync mekanizması (varsa)
- kritik UI etkileşimleri (form validation, navigation)

-------------------------------------------------------------------------------
9. OFFLINE / SENKRONİZASYON STANDARTLARI
-------------------------------------------------------------------------------

Mobil uygulamalar için özel kurallar:

- offline-first yaklaşımı tercih edilir.
- local queue mekanizması varsa:
  - queue → retry → sync döngüsü feature içinde değil, services altında yönetilir.
- network durumu store + hook katmanında takip edilir.

-------------------------------------------------------------------------------
10. AGENT DAVRANIŞ REHBERİ
-------------------------------------------------------------------------------

[MOB] tipinde bir görevde agent:

1. AGENT-CODEX.core.md
2. AGENTS.md
3. MOBILE-PROJECT-LAYOUT.md (bu dosya)
4. STYLE-MOB-001.md
5. mobile/<path> yapısına göre uygun klasörü belirler
6. Output formatı:
   - Keşif Özeti
   - Mobil Tasarım
   - Uygulama Adımları (dosya yolu + yapılacak değişiklik)

-------------------------------------------------------------------------------
11. ÖZET
-------------------------------------------------------------------------------

Bu doküman:
- mobil MFE yapısını,
- ekran/feature ayrımını,
- state, API, theme, device access kurallarını,
- offline-first yaklaşımını

net biçimde tanımlar ve mobil için tek doğruluk kaynağıdır.