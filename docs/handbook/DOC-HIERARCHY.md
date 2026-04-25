# DOC-HIERARCHY – Doküman Hiyerarşisi ve Rol Özeti

> Transition Durumu: Bu dosya transition-active rehber katmanındadır.
> Canonical OPO authority için
> `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`,
> `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md` ve
> `standards.lock` kullanılır.

Bu dosya, repodaki tüm önemli `.md` doküman türlerinin **ne işe yaradığını**
ve **hangi durumda hangisine bakılması gerektiğini** özetler.

---

## 1. Agent Dokümanları (Kök Düzey)

- `AGENTS.md`
  - Tüm agent’lar için iş tipi → doküman okuma rotasını tarif eder.

- Çekirdek transition rehberi
  - Çekirdek davranış: cevap formatı, riskli komut kuralları, öncelik sırası.

- Backend transition rehberi
  - [BE] işleri için ek kurallar; backend layout + style entegrasyonu.

- Web transition rehberi
  - [WEB] işleri için ek kurallar; web FE layout + style entegrasyonu.

- Mobil transition rehberi
  - [MOB] işleri için ek kurallar; mobil FE layout + style entegrasyonu.

- AI/ML transition rehberi
  - [AI] işleri için ek kurallar; AI layout + stil + veri etik entegrasyonu.

- Data transition rehberi
  - [DATA] işleri için ek kurallar; data-pipeline ve SQL stil entegrasyonu.

- Doküman transition rehberi
  - [DOC] işleri için ek kurallar; doküman yazım stili ve şablon kullanımı.

---

## 2. Handbook – Genel Rehber Dokümanlar

- `NAMING.md`
  - Tüm domain için isimlendirme standartları.

- `BACKEND-PROJECT-LAYOUT.md`
  - Backend klasör/paket/servis yapısı.

- `WEB-PROJECT-LAYOUT.md`
  - Web frontend klasör / MFE / UI Kit yapısı.

- `MOBILE-PROJECT-LAYOUT.md`
  - Mobil frontend klasör / yapı.

- `AI-PROJECT-LAYOUT.md`
  - AI/ML klasör, pipeline ve model yerleşimi.

- `DATA-PROJECT-LAYOUT.md`
  - ETL, DWH, rapor ve data pipeline klasör yapısı.

- `DOCS-PROJECT-LAYOUT.md`
  - `docs/` altındaki 00–99 klasör yapısı ve hangi klasörde ne tür doküman tutulacağı.

- `DOCS-PRODUCTION-AGENTS.md`
  - Direct-Gen doküman üretim akışı (BM → BENCH → TRACE → Delivery Pack) ve agent rol dağılımı.

- `STYLE-BE-001.md`
  - Backend kod stili, best practice’ler.

- `STYLE-WEB-001.md`
  - Web frontend kod stili.

- `STYLE-MOB-001.md`
  - Mobil frontend kod stili.

- `STYLE-API-001.md`
  - API tasarım standartları (URL, versiyonlama, PagedResult, ErrorResponse).

- `STYLE-AI-001.md`
  - AI/ML kod, deney, model versiyonlama ve inference stil rehberi.

- `STYLE-DATA-001.md`
  - SQL, view, ETL ve pipeline stil kuralları.

- `STYLE-DOCS-001.md`
  - Doküman yazım stili (başlık yapısı, numaralandırma, referanslama).

- `DATA-GOV-001.md`
  - Veri gizliliği, KVKK, etik, bias ve data governance prensipleri.

- `DEV-GUIDE.md`
  - Genel yazılım süreci: Discover → Shape → Design → Build → Validate → Operate.

---

## 3. Ürün Dokümanları (`docs/01-product/`)

- `PROBLEM-BRIEFS/PB-*.md`
  - İş problemini ve hedefi 1 sayfada özetler.

- `PRD/PRD-*.md`
  - Ürün/feature davranışını, kullanıcı senaryolarını, kabul alanını tanımlar.

- `UX/UX-*.md`
  - Ekran akışları, wireframe ve kritik UX notları.

---

## 4. Mimari Dokümanlar (`docs/02-architecture/`)

- `SYSTEM-OVERVIEW.md`
  - Tüm sistemin yüksek seviye mimarisi.

- `DOMAIN-MAP.md`
  - Bounded context / domain haritası.

- `services/<servis>/TECH-DESIGN-*.md`
  - İlgili servisin teknik tasarım detayları.

- `services/<servis>/DATA-MODEL-*.md`
  - Önemli tablolar, şemalar, ilişkiler.

- `services/<servis>/ADR/ADR-*.md`
  - O servise dair mimari karar kayıtları.

- `clients/WEB-ARCH.md`, `clients/MOBILE-ARCH.md`, `clients/AI-ARCH.md`
  - Web, mobil, AI client mimarileri.

---

## 5. Teslimat ve Süreç Dokümanları (`docs/03-delivery/`)

- `STORIES/STORY-*.md`
  - Feature/story bazında “ne istiyoruz” cevabı.

- `ACCEPTANCE/AC-*.md`
  - Given/When/Then formatında kabul kriterleri.

- `TEST-PLANS/TP-*.md`
  - Test stratejisi ve kapsamı.

- `PROJECT-FLOW.md`
  - Story’lerin ve işlerin durumu / roadmap özeti.

---

## 6. Operasyon Dokümanları (`docs/04-operations/`)

- `RUNBOOKS/RB-*.md`
  - Servis/uygulama için çalışma kılavuzu.

- `MONITORING/MON-*.md`
  - Metrikler ve alarmlar.

- `RELEASE-NOTES/REL-*.md`
  - Sürüm bazında değişiklik özeti.

- `SLO-SLA.md`
  - Servis seviye hedef ve anlaşmaları.

---

## 7. AI/ML Dokümanları (`docs/05-ml-ai/`)

- `DATA-CARDS/*.md`
  - Veri seti tanımları, kaynaklar, kalite notları.

- `MODEL-CARDS/*.md`
  - Model tanımı, metrikler, kullanım alanı, kısıtlar.

- `EVALUATION-REPORTS/*.md`
  - Model değerlendirme raporları.

---

## 8. Şablonlar (`docs/99-templates/`)

- `PROBLEM-BRIEF.template.md`
- `PRD.template.md`
- `TECH-DESIGN.template.md`
- `INTERFACE-CONTRACT.template.md`
- `STORY.template.md`
- `ACCEPTANCE.template.md`
- `TEST-PLAN.template.md`
- `RUNBOOK.template.md`
- `DATA-CARD.template.md`
- `MODEL-CARD.template.md`

Bu dosyalar, yeni doküman oluştururken **tek tip format** kullanmak için rehberdir.
