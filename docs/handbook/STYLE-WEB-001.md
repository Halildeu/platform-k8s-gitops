# STYLE-WEB-001 – Web Frontend Kodlama Stili (Compact Version)

Amaç: Web MFE kodlarının tutarlı, okunabilir ve genişleyebilir şekilde yazılmasını sağlamak. Bu belge agent'ların davranış belirlemesi için gerekli minimum kuralları içerir.

-------------------------------------------------------------------------------
1. DOSYA & PROJE YAPISI
-------------------------------------------------------------------------------
Kod yeri:
- MFE özel kod: apps/<mfe>/src/**
- Ortak kod: packages/**
- Tema & design system: design-tokens/**
- Test: tests/, stories/, cypress/

Modern MFE src yapısı:
apps/<mfe>/src/
  app/          → routing, layout, provider’lar
  entities/     → domain modelleri ve entity-level logic
  features/     → use-case odaklı UI + logic (örn: user-profile, login)
  pages/        → route-level UI compose
  widgets/      → tekrar kullanılabilir büyük UI blokları
  shared/       → yerel ortak kod (küçük UI, helpers, hook)
  i18n/         → çeviri dosyaları
  manifest/     → runtime config, federation manifest
  main.tsx      → giriş noktası

Legacy klasörler (yeni geliştirmede kullanılmaz):
components/, hooks/, services/, utils/

-------------------------------------------------------------------------------
2. COMPONENT STANDARTLARI
-------------------------------------------------------------------------------
- Component’ler stateless olmalıdır; side-effect içermez.
- Logic UI’dan ayrılır; data fetch, state yönetimi feature veya hook içindedir.
- İsimlendirme: PascalCase (UserCard.tsx)
- Dosya yapısı:
  ComponentName/
    ComponentName.tsx
    ComponentName.types.ts
    index.ts
- JSX okunabilir olmalıdır; uzun bloklar küçük bileşenlere ayrılır.

-------------------------------------------------------------------------------
3. STATE YÖNETİMİ
-------------------------------------------------------------------------------
- UI state: component içi (useState)
- Domain state: feature içindeki özel hook’lar (örn: useUserList)
- App-level global state: app/store (tema, session vb.)
- Komponent sadece data + handler alır; business logic içermez.
- Rule of thumb (i18n + memo invalidation):
  - Ne zaman: Locale switch sonrası UI güncellenmiyorsa (stale UI) ve memo/cache kullanımı varsa.
  - Neden: `useMemo`/`useCallback` sadece dependency referansı değişince invalid olur.
  - Nasıl: i18n hook’larında `t/formatNumber/formatDate` callback’lerini `locale` dependency’sine bağla; UI tarafında `useMemo([t])` kullan.
  - Örnek: `const t = useCallback(..., [manager, locale])`
  - Örnek: `const labels = useMemo(() => ..., [t])`

-------------------------------------------------------------------------------
4. API KULLANIM STANDARTLARI
-------------------------------------------------------------------------------
- API çağrıları sadece packages/shared-http üzerinden yapılır.
- API isimlendirme:
  userApi.getList()
  userApi.getById(id)
  userApi.create(payload)
- Response UI’ya verilmeden önce UI modeline dönüştürülür.
- Error handling ortak error handler ile yapılır.

-------------------------------------------------------------------------------
5. DESIGN TOKENS & TAILWIND
-------------------------------------------------------------------------------
- Hard-coded renk, spacing, font, radius yasaktır.
- Tüm görsel değerler design-tokens/ üzerinden gelir.
- Tailwind config token kaynaklarına bağlıdır.
- Component içinde mümkün olduğunca token sınıfları kullanılır.

-------------------------------------------------------------------------------
6. IMPORT SIRASI
-------------------------------------------------------------------------------
1. React / framework
2. 3rd party libs
3. packages/**
4. entities → features → shared
5. local dosyalar

-------------------------------------------------------------------------------
7. TEST STANDARTLARI
-------------------------------------------------------------------------------
- Unit: tests/**
- Component: stories ve testing-library
- E2E: cypress/
- Hook ve feature logic testleri zorunludur.
- Kritik UI bileşenleri test edilir (filter panel, grid wrapper vb.)

-------------------------------------------------------------------------------
8. MFE SINIRI KURALI
-------------------------------------------------------------------------------
- apps/<mfe> içindeki kod sadece kendi MFE’si tarafından kullanılabilir.
- Bir MFE diğer MFE’den import yapmaz.
- Ortak kod packages/ üzerinden paylaşılır.

-------------------------------------------------------------------------------
9. AGENT DAVRANIŞ NOTU
-------------------------------------------------------------------------------
[WEB] tipindeki bir görevde agent şu sırayı izlemelidir:
1. AGENT-CODEX.core.md
2. AGENTS.md
3. WEB-PROJECT-LAYOUT.md
4. STYLE-WEB-001.md (bu dosya)
5. apps/<mfe>/src/** yapısını dikkate alır
6. packages/** içindeki paylaşılan modülleri kullanır
7. Çıktı formatı:
   - Keşif Özeti
   - FE Tasarım
   - Uygulama Adımları (dosya yolu + yapılacak değişiklik)

-------------------------------------------------------------------------------
10. ÖZET
-------------------------------------------------------------------------------
Bu belge, web MFE geliştirme için minimum ama keskin kuralları tanımlar:
- doğru klasör
- doğru component yapısı
- doğru state modeli
- doğru API kullanımı
- doğru design token kullanımı
- doğru test yaklaşımı

-------------------------------------------------------------------------------
11. STORY ID REFERANSI (DOKÜMAN ↔ KOD İZLENEBİLİRLİĞİ)
-------------------------------------------------------------------------------

- Bir STORY dokümanı (örn. `STORY-0009-fe-spa-login-standardization.md`)
  frontend tarafında uygulanıyorsa:
  - En az bir **test** veya **kod** dosyasında ilgili STORY ID açıkça
    referans verilmelidir.
- Önerilen kullanım şekilleri:
  - Jest/Testing Library test adı veya describe:
    - `describe("STORY-0009 – FE SPA Login Standardization", () => { ... })`
  - Kod yorum satırı:
    - `// STORY-0009-fe-spa-login-standardization`
  - Commit mesajında STORY ID kullanımı teşvik edilir, ancak bu stil kuralı
    özellikle kod/test dosyası içinde görünür ID referansını zorunlu kılar.
- Bu sayede:
  - `docs/03-delivery/PROJECT-FLOW.md` içindeki STORY satırları ile
    web kodu arasındaki ilişki, otomatik script’ler ve kalite kontrolleri
    tarafından daha kolay izlenebilir hale gelir.
