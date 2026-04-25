# WEB-PROJECT-LAYOUT

Bu doküman, `web/` klasörünün gerçek proje mimarisini, alt klasörlerin
sorumluluklarını ve geliştirme sırasında izlenecek yapısal prensipleri tarif eder.
Amaç: Mikro frontend (MFE) tabanlı web projelerinde tutarlı, ölçeklenebilir ve
izlenebilir bir kod mimarisi sağlamaktır.

-------------------------------------------------------------------------------
1. ÜST DÜZEY DİZİN YAPISI
-------------------------------------------------------------------------------

web/
 ├── apps/                 # Her MFE burada yaşar
 ├── packages/             # Ortak modüller
 ├── design-tokens/        # Tema / token / design system kaynakları
 ├── cypress/              # E2E testler
 ├── stories/              # Storybook component hikayeleri
 ├── tests/                # Unit & integration testleri
 ├── docs/                 # Web'e özel dokümanlar (opsiyonel)
 ├── scripts/              # Build / generate / utility script'leri
 ├── security/             # Güvenlik analiz konfigürasyonu
 ├── security-reports/     # Güvenlik raporları (SAST, dependency analysis)
 ├── .storybook/           # Storybook config
 ├── storybook-static/     # Build edilmiş Storybook çıktısı
 ├── node_modules/
 ├── yapı & config dosyaları (package.json, tailwind.config.js, tsconfig.json vb.)
 └── .env.*.example        # Ortam değişkeni örnekleri

-------------------------------------------------------------------------------
2. MFE KLASÖR YAPISI (apps altında)
-------------------------------------------------------------------------------

Her mikro frontend, `apps/<mfe-name>/` altında yer alır.

Örnek:
apps/
 ├── mfe-shell/
 ├── mfe-access/
 ├── mfe-audit/
 ├── mfe-ethic/
 ├── mfe-reporting/
 ├── mfe-suggestions/
 └── mfe-users/

Genel dosyalar:
- package.json
- webpack.common.js / webpack.dev.js / webpack.prod.js
- tailwind.config.js
- postcss.config.js
- tsconfig.json
- public/
- dist/ (build çıktısı)
- mocks/        (mock API yanıtları, local dev stub’ları)
- manifest/     (module federation veya runtime config manifest’leri)

-------------------------------------------------------------------------------
3. YENİ NESİL MFE SRC YAPISI (ÖR: mfe-users)
-------------------------------------------------------------------------------

Yeni standart `src` yapısı (mfe-users gibi):

apps/<mfe>/src/
 ├── app/
 ├── entities/
 ├── features/
 ├── i18n/
 ├── manifest/
 ├── pages/
 ├── shared/
 ├── widgets/
 └── main.tsx veya index.tsx

Klasör rolleri:

- app/  
  Uygulamanın shell’i:
  - router
  - layout bileşenleri
  - global provider’lar
  - app-level bootstrap kodu

- entities/  
  Domain model katmanı:
  - tipler / interface’ler
  - entity bazlı küçük yardımcı fonksiyonlar
  - entity’ye göre ayrılmış data-access adapter’ları (gerekliyse)

- features/  
  Kullanıcıya görünen işlevler (use-case odaklı):
  - “login”, “user-profile”, “access-request” gibi feature klasörleri
  - her feature kendi UI + state + side-effect’ini içerir
  - features, entities katmanını kullanır; shared’den destek alır

- pages/  
  Route-level bileşenler:
  - routing parametrelerini alır
  - gerekli feature/ widget bileşenlerini compose eder
  - mümkün olduğunca ince kalır (iş mantığı feature’da)

- widgets/  
  Birden fazla page/feature tarafından kullanılabilen kompleks UI bileşenleri:
  - filtre paneli
  - tablo + grafik kombinasyonu
  - layout içinde reuse edilen bloklar

- shared/  
  MFE içinde ortak kullanılan:
  - küçük UI bileşenleri
  - helpers
  - form schema’ları
  - hook’lar
  (cross-MFE ortak kod yine packages/*’de olmalıdır, shared sadece o MFE içindir.)

- i18n/  
  Çeviri dosyaları, namespace’ler, i18n init/config.

- manifest/  
  Uygulamanın runtime configuration’ı:
  - module federation manifest
  - feature flag manifest
  - environment bazlı config map’leri

- main.tsx / index.tsx  
  Uygulamanın giriş noktası; genellikle app/ altındaki root component’i
  bootstrap eder.

Zorunlu iskelet doğrulaması (MFE standardı):
- `python3 scripts/check_web_mfe_layout.py`

-------------------------------------------------------------------------------
4. LEGACY MFE SRC YAPISI (GEÇİŞTEKİ PROJELER İÇİN)
-------------------------------------------------------------------------------

Bazı eski MFE’ler (ör. mfe-audit) aşağıdaki gibi daha klasik bir yapıyı
kullanabilir:

apps/<mfe>/src/
 ├── app/
 ├── components/
 ├── hooks/
 ├── services/
 ├── types/
 ├── utils/
 └── main.tsx / index.tsx

Bu yapı **legacy** olarak kabul edilir.
Yeni geliştirmeler mümkün olduğunca `entities/features/pages/widgets/shared`
modeline taşınmalıdır.

-------------------------------------------------------------------------------
5. packages/ YAPISI (ORTAK MODÜLLER)
-------------------------------------------------------------------------------

packages/
 ├── ui-kit/              # Kurumsal UI bileşenleri (buton, modal, grid wrapper...)
 ├── shared-http/         # API client, HTTP wrapper, interceptor katmanı
 ├── shared-utils/        # Çapraz MFE utility fonksiyonları
 ├── design-system/       # CSS vars, theme injector, helper fonksiyonlar
 └── diğer paketler...

Prensipler:
- packages/** altında **ortak** ve **genel** kod yaşar.
- apps/** içinde **uygulamaya özel** kod yaşar.
- MFE’ler birbirlerinden doğrudan kod import etmez; ortak kod packages üzerinden gelir.

-------------------------------------------------------------------------------
6. DESIGN TOKENS / TEMA SİSTEMİ
-------------------------------------------------------------------------------

design-tokens/
- Figma’dan alınan token dosyaları (ör. figma.tokens.json)
- token build script’leri
- CSS variables / Tailwind preset çıktıları

Kullanım prensipleri:
- UI bileşenleri hard-coded renk/spacing kullanmaz → sadece token referansı.
- Tailwind config doğrudan token dosyasından beslenir.

-------------------------------------------------------------------------------
7. AGENT KULLANIM REHBERİ
-------------------------------------------------------------------------------

[WEB] tipindeki bir görevde agent şu sırayla düşünmelidir:

1. AGENT-CODEX.core.md
2. AGENTS.md
3. WEB-PROJECT-LAYOUT.md (bu dosya)
4. STYLE-WEB-001.md (web FE stil kuralları)
5. İlgili MFE yapısı → apps/<mfe>/**
6. Ortak paketler → packages/**
7. Theme/token yapısı → design-tokens/**
8. PRD / UX dokümanları → docs/01-product/**

Cevap formatı:
- Keşif Özeti
- FE Tasarım
- Uygulama Adımları (dosya yolu + yapılacak değişiklik)

-------------------------------------------------------------------------------
8. ÖZET
-------------------------------------------------------------------------------

Bu layout:

- MFE tabanlı web geliştirmeyi,
- Yeni nesil entities/features/pages/widgets/shared mimarisini,
- Ortak paket mimarisini,
- Design system entegrasyonunu,
- Test altyapısını

tek bir tutarlı yapıda toplar ve tüm ekipler ile agent’lar için
**tek doğruluk kaynağıdır**.
