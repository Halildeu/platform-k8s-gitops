# RB-mfe-access – MFE Access Runbook (Özet)

ID: RB-mfe-access  
Service: mfe-access  
Status: Draft  
Owner: @team/platform-fe

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `mfe-access` modülünün üretim ortamındaki çalışmasını, kritik metrikleri,
  incident adımlarını ve fallback/rollback seçeneklerini özetlemek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Amaç: Manifest tabanlı rol & policy yönetim arayüzü; erişim matrisini
  `permission-service` üzerinden günceller, audit ID üretir ve shell
  notification center’a iletir.
- Ortamlar:
  - Prod URL: `https://shell.example.com/access/*`  
  - Stage URL: `https://shell-stage.example.com/access/*`
- Sorumlu ekip: Platform FE + Access domain temsilcisi.
- Dashboards:
  - Grafana: *Access Module Overview*
  - Log index: `logs-fe-access-*`

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Başlatma / deploy:
  - CI/CD veya ArgoCD üzerinden `mfe-access` uygulamasını deploy et.
  - Deploy sonrası shell manifest ve route’ların güncel olduğundan emin ol.
- Durdurma / rollback:
  - Gerekirse ArgoCD üzerinden `mfe-access` application’ını son stabil revision’a çek.
  - Kritik incident durumunda manifest-platform panelinden ilgili manifest’i
    geçici olarak devre dışı bırak; status sayfasından duyuru paylaş.
 - Release sonrası:
   - `python3 scripts/release_smoke_check.py mfe-access` ile temel smoke test
     çalıştır.
   - Gerekirse `python3 scripts/check_slo_sla.py metrics.json` ile SLO/SLA
     hedeflerini kontrol et.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Metrikler:
  - `fe.access.ttfa_p95` < 8s  
  - `fe.access.grid_fetch_latency_p95` < 2.5s  
  - `fe.access.client_error_rate` < %2
- Log aramaları:
  - `service.name:fe-access AND level:error`
  - `message:"auditId" AND level:warn`
- Alert kanalları:
  - Grafana contact point: *MFE-Squad*
  - OpsGenie policy: *Access-UI*

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – Manifest fetch 404/403:
  - Given: Kullanıcılar access ekranına ulaşamıyor veya manifest yüklenemiyor.  
    When: Manifest fetch istekleri 404/403 ile sonuçlanır.  
    Then: `npm run security:sri:check` ile SRI doğrulaması yap, manifest SRI
    değerlerini güncelle ve `mfe-shell` deploy et; problem çözülene kadar
    kullanıcıya uygun hata/duyuru göster.

- [ ] Arıza senaryosu 2 – Grid fetch timeout:
  - Given: Access grid’inde veri yüklenmiyor, istekler timeout oluyor.  
    When: `permission-service` veya ilgili backend servislerinde latency spike
    gözlenir.  
    Then: Backend oncall ekibini bilgilendir, ilgili PromQL metriklerini incele;
    gerektiğinde FE tarafında `access_grid_lazy_load` ve `access_grid_readonly`
    flag’leri ile sadece okunur moda geç, kullanıcıya durum bilgisini göster.

- [ ] Arıza senaryosu 3 – Mutation failure spike:
  - Given: Permission değişikliği istekleri beklenenden fazla başarısız oluyor.  
    When: `fe.access.client_error_rate` veya mutation hata oranı limitin
    üzerindedir.  
    Then: `access_mutation_write` flag’ini kapat, UI’yı read-only moda al ve
    kullanıcıyı banner ile bilgilendir; backend ve audit loglarını inceleyip
    kök sebebi tespit et.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- `mfe-access` için temel operasyon adımları, metrikler ve incident senaryoları
  bu runbook’ta özetlenir.
- Kritik durumlarda hızlı rollback ve read-only fallback stratejileri her zaman
  hazır tutulmalıdır.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- SLO/SLA: docs/04-operations/SLO-SLA.md
- Monitoring: docs/04-operations/MONITORING/…
