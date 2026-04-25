# DOCS-PROJECT-LAYOUT

> Transition Durumu: Bu dosya transition-active rehber katmanındadır.
> Canonical OPO authority için
> `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`,
> `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md` ve
> `standards.lock` kullanılır.

Bu doküman, `docs/` klasörü içindeki tüm dokümanların nasıl yapılandırılacağını
ve hangi kategoride hangi tür içeriklerin bulunacağını tanımlar. Amaç: İnsanlar
ve AI agent’ların tüm proje dokümantasyonunu kolayca bulabileceği, okunabilir ve
tutarlı bir mimari sunmaktır.

-------------------------------------------------------------------------------
1. ÜST DÜZEY DİZİN YAPISI
-------------------------------------------------------------------------------

docs/
 ├── 00-handbook/        → Genel kurallar, layout, stil, rehberler
 ├── 01-product/         → Ürün & iş analizi dokümanları (PB, PRD, UX)
 ├── 02-architecture/    → Teknik tasarım & mimari dokümanlar
 ├── 03-delivery/        → Story, acceptance, test planları, workflow
 ├── 04-operations/      → Runbook, monitoring, release, SLO/SLA
 ├── 05-ml-ai/           → Data-card, model-card, evaluation dokümanları
 └── 99-templates/       → Tüm doküman türlerinin şablonları

-------------------------------------------------------------------------------
2. 00-HANDBOOK (GENEL REHBERLER)
-------------------------------------------------------------------------------

00-handbook/
  NAMING.md                    → İsimlendirme kuralları
  NUMARALANDIRMA-STANDARDI.md  → Doküman ID ve dosya adı formatları
  WEB-PROJECT-LAYOUT.md        → Web kod yapısı
  MOBILE-PROJECT-LAYOUT.md     → Mobil kod yapısı
  BACKEND-PROJECT-LAYOUT.md    → Backend mikroservis yapısı
  DATA-PROJECT-LAYOUT.md       → Data/ETL yapısı
  AI-PROJECT-LAYOUT.md         → AI/ML pipeline yapısı
  STYLE-WEB-001.md             → Web kod stili
  STYLE-MOB-001.md             → Mobil kod stili
  STYLE-BE-001.md              → Backend kod stili
  STYLE-DATA-001.md            → SQL/ETL kod stili
  STYLE-AI-001.md              → AI kod stili
  STYLE-API-001.md             → API tasarım stili
  STYLE-DOCS-001.md            → Doküman yazım stili
  DATA-GOV-001.md              → Veri gizlilik & etik kurallar
  DOC-HIERARCHY.md             → Tüm dokümanların indeks/hiyerarşisi
  DEV-GUIDE.md                 → Yazılım geliştirme süreci (Discover→Operate)

00-handbook klasörü, proje dokümanlarının “anayasa”sı niteliğindedir.

-------------------------------------------------------------------------------
3. 01-PRODUCT (İŞ & ÜRÜN DOKÜMANLARI)
-------------------------------------------------------------------------------

01-product/
  PROBLEM-BRIEFS/              → 1 sayfalık problem özetleri
  PRD/                         → Ürün/feature gereksinim dokümanları
  UX/                          → Kullanıcı akışları, ekran taslakları

Bu klasör, “ne istiyoruz?” sorusunu yanıtlar.

ID ve isimlendirme (özet):
- Problem Brief: `PB-0001-<kısa-konu>.md`
- PRD: `PRD-0001-<feature>.md`

-------------------------------------------------------------------------------
4. 02-ARCHITECTURE (TEKNİK TASARIM)
-------------------------------------------------------------------------------

02-architecture/
  SYSTEM-OVERVIEW.md           → Genel mimari üst bakış
  DOMAIN-MAP.md                → Bounded context / domain haritası
  services/<servis>/
    TECH-DESIGN-*.md           → Servis teknik tasarım dokümanları
    DATA-MODEL-*.md            → Tablo/şema modelleri
    ADR/ADR-*.md               → Mimari kararların kaydı
  clients/
    WEB-ARCH.md
    MOBILE-ARCH.md
    AI-ARCH.md

Bu klasör “nasıl yapıyoruz?” sorusunu yanıtlar.

ID ve isimlendirme (özet):
- TECH-DESIGN: `TECH-DESIGN-<servis>-<konu>.md` (ID almaz)
- DATA-MODEL: `DATA-MODEL-<servis>-<model>.md` (ID almaz)
- ADR: `ADR-0001-<karar>.md` (servis bazlı sayaç)

-------------------------------------------------------------------------------
5. 03-DELIVERY (GERÇEKLEŞTİRME)
-------------------------------------------------------------------------------

03-delivery/
  STORIES/                     → İş birimi istekleri (story level)
  ACCEPTANCE/                  → Given/When/Then koşulları
  TEST-PLANS/                  → Test stratejisi
  PROJECT-FLOW.md              → Story durumu & roadmap

Bu klasör, geliştirme işlerinin üretim sürecini yönetir.

ID ve isimlendirme (özet):
- Story: `STORY-0001-<konu>.md`
- Acceptance: `AC-0001-<konu>.md` (ilgili Story ile hizalı)
- Test Plan: `TP-0001-<konu>.md` (ilgili Story ile hizalı)

-------------------------------------------------------------------------------
6. 04-OPERATIONS (OPERASYON & YAŞAMA ALANI)
-------------------------------------------------------------------------------

04-operations/
  RUNBOOKS/                    → Servis çalışma kılavuzları
  MONITORING/                  → Metrikler & alarmlar
  RELEASE-NOTES/               → Versiyon/sürüm notları
  SLO-SLA.md                   → Hizmet kalitesi hedefleri

Bu klasör, “sistem üretimde nasıl çalışıyor?” sorusunu yanıtlar.

ID ve isimlendirme (özet):
- Runbook: `RB-<servis>.md` (servis başına tek runbook; içerikte ID alanı RB-<servis>)

-------------------------------------------------------------------------------
7. 05-ML-AI (MODEL & VERİ DOKÜMANLARI)
-------------------------------------------------------------------------------

05-ml-ai/
  DATA-CARDS/                  → Veri seti açıklamaları
  MODEL-CARDS/                 → Model açıklamaları, risk ve metrikler
  EVALUATION-REPORTS/          → Versiyon karşılaştırma raporları

Bu klasör AI/ML’in izlenebilirliğini sağlar.

ID ve isimlendirme (özet; projeye göre genişletilebilir):
- Data-Card: `DATA-0001-<dataset>.md`
- Model-Card: `MODEL-0001-<model>.md`

-------------------------------------------------------------------------------
8. 99-TEMPLATES (ŞABLONLAR)
-------------------------------------------------------------------------------

99-templates/
  PROBLEM-BRIEF.template.md
  PRD.template.md
  TECH-DESIGN.template.md
  STORY.template.md
  ACCEPTANCE.template.md
  TEST-PLAN.template.md
  RUNBOOK.template.md
  DATA-CARD.template.md
  MODEL-CARD.template.md

Bu klasör, tüm doküman üretiminde standart format sağlar.

-------------------------------------------------------------------------------
9. AGENT DAVRANIŞ REHBERİ
-------------------------------------------------------------------------------

[DOC] iş tipinde agent:

1. STYLE-DOCS-001.md  
2. Bu dosya (DOCS-PROJECT-LAYOUT.md)  
3. İlgili template (99-templates/**)  
4. İlgili domain dokümanları  
okur ve aşağıdaki formatı takip eder:

- Örneklerden Öğrenilenler  
- Doküman Taslağı  
- Uygulama Adımları (dosya yolu + oluşturulacak/güncellenecek dosya)

-------------------------------------------------------------------------------
10. ÖZET
-------------------------------------------------------------------------------

Bu layout dokümanı, tüm dokümantasyon alanları için:
- hiyerarşiyi,
- içerik alanlarını,
- klasör amacını,
- agent’ın hangi dosyaya bakacağını

compact ve tutarlı şekilde sunar.

Projedeki tüm dokümanlar için **tek mimari referanstır**.

Doküman ID ve dosya adı kuralları için:
- NUMARALANDIRMA-STANDARDI.md  
bu layout’un tamamlayıcı referansıdır.
