# RB-feature-flags – Feature Flag Yönetimi Runbook (Özet)

ID: RB-feature-flags  
Service: feature-flags  
Status: Draft  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Unleash ve benzeri feature flag sistemlerinde flag yaşam döngüsünü
  (introduce → rollout → retire) operasyonel olarak yönetmek; riskli
  değişiklikleri kontrollü ve izlenebilir şekilde devreye almak.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Servis: Feature flag platformu (örn. Unleash cluster).
- Ortamlar: prod, stage, test.
- Sorumlu ekipler: Platform ve ilgili domain ekipleri.
- Konu:
  - Flag açma/kapama süreçleri.
  - Riskli değişiklikler için guardrail’lerin uygulanması.
  - Flag emeklilik (retire) ve temizlik (cleanup).
- İlgili SLO/SLA’lar: flag değerlendirme latency, config fetch hata oranı,
  rollout başarısı (detay için SLO-SLA ve monitoring dokümanlarına bakınız).

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Servis start/restart:
  - Deployment aracı (örn. ArgoCD/Helm) üzerinden `feature-flags` uygulamasını
    deploy et veya yeniden başlat.
  - Health check ve dashboard’lardan temel metrikleri kontrol et.
- Flag açma/kapama:
  - İlgili ortam için UI veya API üzerinden flag durumunu değiştir.
  - Kritik flag’ler için change approval sürecini uygula.
- Bakım / maintenance:
  - Yeni flag’leri önce `inactive` veya düşük rollout yüzdesi ile aç,
    telemetry ile gözlemle; sorun görülürse hızla geri al.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Log index’leri:
  - `logs-feature-flags-*` veya ilgili uygulama log index’leri.
- Dashboard’lar:
  - Feature flag kullanım ve error rate panoları (örn. *Feature Flags Overview*).
- Temel metrikler:
  - Flag evaluation latency.
  - Config fetch ve provider hata oranları.
  - Rollout sırasında error/spike gözlemleri.

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – Yanlış flag konfigurasyonu:
  - Given: Yeni bir flag rollout sonrası beklenmeyen hata veya performans
    sorunu vardır.  
    When: İlgili feature flag için hatalı config veya yanlış hedef segment
    olduğu tespit edilirse.  
    Then: Flag’i derhal önceki güvenli değere çek veya kapat, etkilenen servis
    log ve metriklerini incele; gerekirse rollback kararı ve kök sebep analizi
    dokümante edilir.

- [ ] Arıza senaryosu 2 – Flag servisi erişilemez:
  - Given: Uygulamalar feature flag servisine bağlanamıyor veya timeout
    hataları görülüyor.  
    When: Health check ve log’larda feature flag servisine erişim hataları
    tespit edilirse.  
    Then: Servis pod/instance durumunu kontrol et, gerekli restart/deploy
    işlemlerini uygula; uygulamaların default flag davranışı ile güvenli
    şekilde devam ettiğini doğrula.

- Gerekirse ek senaryolar aynı formatta eklenir (örneğin stale flag temizliği,
  audit eksiklikleri vb.).

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Feature flag yönetimi; introduce → rollout → retire döngüsünün güvenli ve
  izlenebilir şekilde yürütülmesi için bu runbook’u kullanır.
- Kritik flag değişiklikleri her zaman monitoring, rollback planı ve gerekli
  onay mekanizmaları ile birlikte ele alınmalıdır.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- TECH-DESIGN: docs/02-architecture/services/<servis>/TECH-DESIGN-feature-flags.md (varsa)
- SLO/SLA: docs/04-operations/SLO-SLA.md
- Monitoring: docs/04-operations/MONITORING/…
