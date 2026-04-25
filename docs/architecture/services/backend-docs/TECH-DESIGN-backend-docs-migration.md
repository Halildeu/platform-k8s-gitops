# TECH-DESIGN – Backend Docs → Yeni docs/ Hiyerarşisine Taşıma

Amaç: Eski `backend/docs` ağacındaki dokümanların nasıl `docs/**`
hiyerarşisine taşındığını yüksek seviyede açıklamak ve bugün için canonical
authority’nin yalnız `docs/**` ile `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`
olduğunu netleştirmektir.

-------------------------------------------------------------------------------
1. ENVANTER (YÜKSEK SEVİYE)
-------------------------------------------------------------------------------

Kaynak envanter (özet, bugün yalnız tarihçe amaçlıdır):

- Eski backend dokümantasyonu archive-reference katmanına alınmıştır.  
- Aktif ve canonical içerik; layout, stil, story, acceptance, ADR, runbook ve
  API sözleşmeleri artık yalnız `docs/**` altında yer alır.

-------------------------------------------------------------------------------
2. HEDEF KONUMLAR (YENİ docs/ HİYERARŞİSİ)
-------------------------------------------------------------------------------

Referans:
- `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`
- `docs/03-delivery/STORIES/STORY-0001-backend-docs-refactor.md`
- `backend/docs/README.md`

Mapping prensipleri:

- Genel kurallar / stil / layout:
  - Hedef: transition rehber katmanı ve `docs/**`
  - Aksiyon: Var olan içerik büyük ölçüde taşındı; eski eşdeğerler yalnız
    archive-reference olarak tutulur.

- Sistem ve servis mimarisi (system overview, services, security):
  - Hedef: `docs/02-architecture/**`
  - Örnek:
    - 01-system/*.md → SYSTEM-OVERVIEW / SYSTEM-ARCHITECTURE altına özetlenir.
    - 03-services/*.md → services/<servis>/TECH-DESIGN-*.md / DATA-MODEL-*.md olarak yeniden yazılır.
    - 04-security/** → security ile ilgili TECH-DESIGN/ADR veya RUNBOOK/OPERATIONS dokümanlarına referans olur.

- Security / identity / vault rehberleri:
  - Hedef:  
    - Teknik mimari kısmı → `docs/02-architecture/**` (TECH-DESIGN + ADR)  
    - Operasyonel kısmı → `docs/04-operations/RUNBOOKS/**` ve MONITORING

- Delivery / CI / test stratejisi:
  - Hedef: `docs/03-delivery/**`
  - Örnek:
    - ci/** → TEST-PLAN veya operasyona yakınsa RUNBOOK notlarına referans.
    - testing/test-strategy.md → `docs/03-delivery/TEST-PLANS/TP-XXXX-*.md` içine taşınacak özet.

- Governance (story/spec/acceptance/feature-requests):
  - Hedef:  
    - Story’ler → `docs/03-delivery/STORIES/STORY-XXXX-*.md`  
    - Acceptance → `docs/03-delivery/ACCEPTANCE/AC-XXXX-*.md`  
    - Specs → `docs/02-architecture/**` (SPEC veya TECH-DESIGN olarak)  
    - PROJECT_FLOW → `docs/03-delivery/PROJECT-FLOW.md` ile birleştirilmiş görünüm.

- Runbook’lar:
  - Hedef: `docs/04-operations/RUNBOOKS/RB-<servis>.md`
  - Eski çok sayıda runbook, servis bazlı tekil RB dosyalarına konsolide edilecek.

- Agents:
  - Hedef: transition-active rehber katmanı; canonical authority ise
    `OPO-AUTHORITY-MAP` ve managed standards setidir.

-------------------------------------------------------------------------------
3. ADIMLAR (YÜKSEK SEVİYE PLAN)
-------------------------------------------------------------------------------

1) Envanterin detaylandırılması
   - backend/docs altındaki md dosyaları için kategori bazlı liste oluştur (handbook, story, acceptance, spec, runbook, guide, template, agent).

2) Mapping tablosu
   - Her önemli doc için şu alanlarla tablo hazırlanır:
     - Kaynak path
     - Tür (handbook/story/acceptance/spec/runbook/guide/template/agent/legacy)
     - Hedef path (docs/..)
     - Aksiyon (özetle, aynen taşı, legacy’ye al, birleştir, iptal)

-------------------------------------------------------------------------------
4. TARİHİ MAPPING ÖZETİ
-------------------------------------------------------------------------------

Bu dokümanın önceki sürümlerinde detaylı legacy-path tabloları tutuluyordu.
Bugün için o detaylar normatif değildir; önemli olan aşağıdaki current kurallar:

- Template üretimi yalnız `docs/99-templates/**` üzerinden yapılır.
- Runbook canonical yüzeyi yalnız `docs/04-operations/RUNBOOKS/**` altındadır.
- Guide canonical yüzeyi yalnız `docs/03-delivery/guides/**` altındadır.
- Governance canonical yüzeyi yalnız `STORY / AC / TP / PROJECT-FLOW` zinciridir.
- Archive-reference alanı yalnız tarihçe ve migration izi için tutulur.

3) Taşıma fazı
   - Yeni dokümanları `docs/` altında oluştur:
     - STORY-XXXX, AC-XXXX, TP-XXXX, ADR-XXXX, RUNBOOK, TECH-DESIGN, DATA-MODEL.
   - Eski backend/docs dosyalarını:
     - ya `backend/docs/legacy/**` altına taşı,
     - ya tamamen `docs/` altındaki yeni dokümana referans veren kısa bir “migrated” notuna indir.

4) Temizlik ve doğrulama
   - İlgili ID ve dosya adı kurallarına göre doğrulama yapılır.
   - PROJECT-FLOW ve current authority map ile uyum doğrulanır.
   - backend/docs kökünde README güncellenerek “aktif dokümantasyon docs/ altında” notu eklenir.

-------------------------------------------------------------------------------
8. NOTLAR
-------------------------------------------------------------------------------

- Bu dosya, gerçek taşıma öncesi tasarım rehberi niteliğindedir; her doküman için
  detaylı mapping ayrı bir tablo veya ek dokümanla takip edilebilir.
- Taşıma sırasında acceptance kriterleri:  
  - STORY-0001-backend-docs-refactor  
  - AC-0001-backend-docs-refactor  
  - ADR-0001-backend-docs-reorg
