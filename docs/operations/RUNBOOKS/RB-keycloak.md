# RB-keycloak – Keycloak Yönetim Runbook (Özet)

ID: RB-keycloak  
Service: keycloak  
Status: Draft  
Owner: @team/security

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Keycloak realm yönetimi, admin işlemleri ve yedekleme/geri yükleme
  adımlarını operasyonel düzeyde özetlemek; JWT sertleştirme ve rollback
  süreçlerini dokümante etmek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Servis: Keycloak cluster (auth provider).
- Ortamlar: prod, stage, test.
- Sorumlu ekipler: Security ve Platform Engineering.
- Ana sorumluluklar:
  - Realm ve client konfigurasyonu.
  - Kullanıcı, rol ve permission yönetimi.
  - Backup/restore ve DR drill’leri.
  - JWT sertleştirme rollout/rollback adımları.

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Servis başlatma/durdurma:
  - Kubernetes veya ilgili platform üzerinden `keycloak` deployment’ını
    scale/deploy et.
  - Başlatma sonrası admin console ve temel health endpoint’lerini kontrol et.
- Planlı bakım:
  - Önce yedekleme adımlarını tamamla (backup stratejisine bak).
  - Bakım/deploy işlemlerini uygula; ardından smoke test ve monitoring
    kontrollerini çalıştır:
    - `python3 scripts/release_smoke_check.py auth-service`
    - Gerekirse `python3 scripts/check_slo_sla.py metrics.json`

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Log index’leri:
  - `logs-keycloak-*` veya platformdaki ilgili log index’leri.
- Dashboard’lar:
  - Keycloak ve auth metriklerini gösteren panolar (örn. login başarısı,
    hata oranı, response time).
- Temel metrikler:
  - Login success/fail oranları.
  - Token endpoint latency ve hata oranı.
  - Backup/restore job’larının başarı durumu.

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – Backup başarısız:
  - Given: Günlük otomatik backup job’ı veya manuel backup çalışmaktadır.  
    When: Backup job hata verir veya doğrulama (checksum, restore dry-run) başarısız olur.  
    Then: Hata loglarını incele, depolama (S3/Vault) erişimini kontrol et, backup
    job konfigürasyonunu güncelle ve backup’ı yeniden çalıştır; başarısız denemeleri
    “Security DR Drills” dökümantasyonuna kaydet.

- [ ] Arıza senaryosu 2 – Restore sonrası tutarsızlık:
  - Given: Bir incident sonrası realm restore işlemi yapılmıştır.  
    When: Kullanıcı/rol/client ekranlarında beklenmeyen eksik/kaymış konfigurasyon görülür.  
    Then: Restore kaynağını (backup versiyonu) ve import adımlarını doğrula,
    gerekiyorsa son bilinen sağlıklı backup’a dön; uygulama ve gateway tarafında
    smoke test çalıştırarak sistemi doğrula.

- [ ] Arıza senaryosu 3 – JWT sertleştirme rollback:
  - Given: STORY-0002 kapsamında yapılan JWT sertleştirme rollout’u sonrası
    beklenmeyen client sorunları vardır.  
    When: Prod/test ortamlarında ciddi hata oranı veya erişim kaybı gözlenir.  
    Then: İlgili release’i CI/CD üzerinden son stabil versiyona geri al, gerekli ise
    kısa süreli geçici whitelist uygula; tüm karar ve adımları AC-0002 ve governance
    dokümanlarına kaydet.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Keycloak çalışması için backup/restore, realm konfigurasyonu ve JWT
  sertleştirme adımlarını bu runbook özetler.
- Düzenli DR drill’leri ve güncel backup stratejisi olmadan production
  değişiklikleri uygulanmamalıdır.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- TECH-DESIGN: docs/02-architecture/services/auth-service/TECH-DESIGN-*.md (varsa)
- STORY: docs/03-delivery/STORIES/STORY-0002-backend-keycloak-jwt-hardening.md
- ACCEPTANCE: docs/03-delivery/ACCEPTANCE/AC-0002-backend-keycloak-jwt-hardening.md
- TEST-PLAN: docs/03-delivery/TEST-PLANS/TP-0002-backend-keycloak-jwt-hardening.md
- SLO/SLA: docs/04-operations/SLO-SLA.md
