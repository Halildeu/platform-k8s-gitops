# DEV-GUIDE – Yazılım Geliştirme Süreci (Compact Final)

> Transition Durumu: Bu dosya transition-active rehber katmanındadır;
> canonical OPO authority değildir. Canonical yönlendirme için
> `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`,
> `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md` ve
> `standards.lock` baz alınır.

Bu doküman yazılım geliştirme yaşam döngüsünü (SDLC) tek ve tutarlı bir akış
halinde tanımlar. Amaç, her iş tipinde (WEB, MOB, BE, DATA, AI, DOC) aynı
süreç mantığının uygulanmasını sağlamaktır.

Süreç 6 adımdan oluşur:
Discover → Shape → Design → Build → Validate → Operate.

-------------------------------------------------------------------------------
1. DISCOVER – Problemi Anla
-------------------------------------------------------------------------------

Amaç:
- Gerçek ihtiyacı netleştirmek, kapsamı belirlemek, başarı kriterini tanımlamak.

Girdiler:
- İş birimi talebi, kullanıcı ihtiyacı, hata kaydı, iyileştirme önerisi.

Çıktılar:
- PB (Problem Brief)
- Hedef metrikler (örn. hız, doğruluk, kullanım kolaylığı)
- Varsayımlar ve sınırlar

-------------------------------------------------------------------------------
2. SHAPE – Ürün Davranışını Tanımla
-------------------------------------------------------------------------------

Amaç:
- Sistemin dışarıdan nasıl davranacağını tarif etmek.

Girdiler:
- PB, UX girdileri, iş birimi gereksinimleri.

Çıktılar:
- PRD (ürün gereksinim dokümanı)
  - Kullanıcı akışları
  - Fonksiyonel davranış
  - Non-goals (kapsam dışı maddeler)
  - Acceptance kriterleri ile uyum

-------------------------------------------------------------------------------
3. DESIGN – Teknik Tasarımı Yap
-------------------------------------------------------------------------------

Amaç:
- Çözümün teknik olarak nasıl uygulanacağını belirlemek.

Girdiler:
- PRD, domain modeli, mevcut mimari dokümanlar.

Çıktılar:
- TECH-DESIGN
- DATA-MODEL (varsa tablo/şema değişiklikleri)
- ADR (kritik mimari kararlar)
- API/contract taslağı (BE/Web/Mobil)

Kurallar:
- Design seviyesinde fazla kod verilmez, sadece mimari kararlar netleşir.
- Tüm iş tipleri kendi layout/stil dokümanlarına göre düşünür.

-------------------------------------------------------------------------------
4. BUILD – Geliştirmeyi Yap
-------------------------------------------------------------------------------

Amaç:
- Tasarlanan çözümü kodlamak.

Girdiler:
- TECH-DESIGN
- Layout + Style dokümanları (WEB-PROJECT-LAYOUT, STYLE-BE-001 vb.)

Çıktılar:
- Kod değişiklikleri
- Birim testleri
- Gerekirse entegrasyon testleri

Agent davranışı:
- Her iş tipi kendi alan transition rehberindeki kurallara göre çözüm üretir.
- Çıktı formatı:
  - Keşif Özeti
  - Tasarım
  - Uygulama Adımları (dosya yolu + değişiklik listesi)

-------------------------------------------------------------------------------
5. VALIDATE – Test & Kabul
-------------------------------------------------------------------------------

Amaç:
- Yapılan işin PRD ile uyumlu olup olmadığını doğrulamak.

Girdiler:
- PRD, acceptance kriterleri, test planları.

Çıktılar:
- Acceptance sonuçları
- Test raporları
- Gerekirse revizyon önerileri

Kriterler:
- Acceptance Given/When/Then formatında olmalıdır.
- Testler (unit, integration, e2e) koşulmalıdır.

-------------------------------------------------------------------------------
6. OPERATE – Yayınla & İzle
-------------------------------------------------------------------------------

Amaç:
- Üretim ortamında kararlı ve izlenebilir çalışmayı sağlamak.

Girdiler:
- Runbook, monitoring planı, operasyonel gereksinimler.

Çıktılar:
- RUNBOOK
- MONITORING dokümanı
- RELEASE-NOTES
- SLO/SLA güncellemeleri

İçerik:
- Deployment adımları
- Versiyonlama
- Sağlık kontrolü (health checks)
- Alarm, uyarı ve log takip kuralları

-------------------------------------------------------------------------------
7. DOKÜMANLAR ARASI İLİŞKİ
-------------------------------------------------------------------------------

Discover → PB  
Shape → PRD  
Design → TECH-DESIGN + DATA-MODEL + ADR  
Build → Kod + testler  
Validate → Acceptance + test planları  
Operate → Runbook + Monitoring + Release Notes

Tüm bu adımlar DOCS-PROJECT-LAYOUT içinde tanımlanan dosya yapısına göre üretilir.

-------------------------------------------------------------------------------
8. AGENT DAVRANIŞI (GENEL)
-------------------------------------------------------------------------------

Her iş tipinde agent şu sırayı izler:

1. Çekirdek transition rehberi  
2. AGENTS.md  
3. İlgili iş tipine ait alan transition rehberi (web, mobile, backend, data, ai, docs)  
4. İlgili layout/stil dokümanları  
5. İlgili domain dokümanları (PRD, TECH-DESIGN, DATA-MODEL)

Agent’ın üreteceği format:
- Keşif Özeti
- Teknik / İş Tasarımı
- Uygulama Adımları

-------------------------------------------------------------------------------
9. ÖZET
-------------------------------------------------------------------------------

Bu doküman tüm iş tipleri için standart geliştirme sürecini tanımlar:
- Discover → Shape → Design → Build → Validate → Operate
- Doküman üretimi, kodlama ve agent çıktıları bu yapıya göre uyumlu hale gelir.

Geliştirme süreci için tek doğruluk kaynağıdır.
Geliştirme süreci için tek doğruluk kaynağıdır (SSOT).
