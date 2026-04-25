# RB-vault – Vault Operasyon Runbook (Özet)

ID: RB-vault  
Service: vault-cluster  
Status: Draft  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Vault rekey, unseal, root token yönetimi ve kritik bakım işlemlerini
  tek bir operasyonel runbook altında toplamak.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Sorumlu ekipler: Platform Engineering (operasyon), Security Engineering (gözetim).
- Ortamlar: prod, stage, test (aynı runbook prensipleri ile).
- Ana sorumluluklar:
  - 3-of-5 shard modeliyle rekey / unseal süreçleri.
  - Root token’in yalnızca break-glass senaryosu için yönetilmesi.
  - Kasalama envanteri ve erişim prosedürlerinin güncel tutulması.
- SLA/SLO:
  - SLA: Vault erişilebilirliği için platform genel SLA’sına uyum (örn. ≥ 99.9%).  
  - SLO örnekleri:
    - Rekey operasyonu planlandığı anda başarıyla tamamlanmalı.  
    - Unseal işlemleri planlı bakım sırasında belirlenen süre içinde bitmeli.

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Başlatma:
  - Vault servislerini cluster üzerinde başlat, `vault status` ile sealed/unsealed
    durumunu kontrol et.
  - Gerekli shard sayısı ile unseal işlemini tamamla.
- Durdurma / bakım:
  - Planlı bakım öncesi backup ve gerekli notları al.
  - Servisleri kontrollü şekilde durdur veya node’ları maintenance’e al.
  - Bakım sonrası vault’un unsealed ve healthy olduğundan emin ol.
  - Smoke ve SLO kontrollerini çalıştır:
    - `python3 scripts/release_smoke_check.py user-service`
    - `python3 scripts/release_smoke_check.py permission-service`
    - Gerekirse `python3 scripts/check_slo_sla.py metrics.json`

-------------------------------------------------------------------------------
3.1 DEV VAULT (RAFT + VOLUME) – DEV-ONLY
-------------------------------------------------------------------------------

- Lokal geliştirmede `backend/docker-compose.yml` içindeki `vault` servisi kalıcı raft storage ile çalışır.
- İlk kurulum: `bash backend/scripts/vault/dev_init.sh`
  - Bu adım init çıktısını `backend/.vault-dev/` altına yazar (git’e girmez).
  - Ayrıca `vault-unseal-key` / `vault-root-token` helper dosyalarını üretir.
- Unseal:
  - Otomatik (önerilen): `backend/docker-compose.yml` içindeki `vault-unseal` sidecar servis’i
    Vault restart sonrası sealed durumu görür ve unseal eder.
  - Manuel (fallback): `bash backend/scripts/vault/dev_unseal.sh`
- KV v2 mount: `secret/` (enable: `bash backend/scripts/vault/dev_enable_kv.sh`)
- `vault server -dev` / inmem mod kullanılmaz; state `vault-data` volume’da tutulur.
- Init/unseal çıktıları repo’ya yazılmaz; `backend/.vault-dev/` altında tutulur (.gitignore).
- Dev vault restart sonrası:
  - `vault-unseal` çalışıyorsa otomatik unseal beklenir.
  - `vault-unseal` yoksa manuel unseal gerekir (`bash backend/scripts/vault/dev_unseal.sh`).
- SSOT seed: `bash backend/scripts/vault/seed-web-playwright-stage.sh` (Playwright staging config; opsiyonel `PW_REAL_USER_EMAIL` / `PW_REAL_USER_PASSWORD` dahil).
- GitHub-only seed: `Vault → GitHub Secrets Sync (Manual)` workflow’unda
  `mode=seed-web-playwright`; bu mod `playwright_base_url` input’unu ve mevcut
  GitHub repo secret’larındaki `KEYCLOAK_*` değerlerini
  `secret/<env>/web-playwright/{config,keycloak}` path’lerine yazar.
- Sonra `vault-secrets-sync` workflow’unu `dry_run=true` ile çalıştırıp FOUND/MISSING kontrol et.
- KV v2 “key kaybı” şüphesi (izleme):
  - Key list (value yok): `vault kv get -format=json secret/<env>/<path> | jq -r '.data.data | keys[]'`
  - Version history: `vault kv metadata get secret/<env>/<path>`
  - Geri alma: `vault kv rollback -version=<N> secret/<env>/<path>`
  - Not: “put” (tam yazım) secret’ı overwrite eder; tek bir alan güncellemek için `vault kv patch` tercih edilir.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Loglar:
  - Vault server log’ları (örn. `logs-vault-*` index’leri).
  - Rekey/unseal log dosyaları: `vault-rekey-log-YYYYMMDD.md`,
    `vault-unseal-log-YYYYMMDD.md`.
- Metrikler:
  - Vault availability, request latency, error rate.
  - Backup job’larının başarı durumu (örn. CronJob metrikleri).
- Dashboard’lar:
  - Vault ve secret management için monitoring panoları (Grafana vb.).

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – Rekey sırasında hata:
  - Given: Rekey kararı alınmış ve süreç başlatılmıştır.  
    When: Rekey komutları hata üretir veya gerekli shard sayısı sağlanamaz.  
    Then: İşlemi durdur, mevcut shard envanterini ve sahiplik bilgilerini
    doğrula; gerekli onaylarla birlikte süreci yeniden planla ve rekey logunu
    güncelle.

- [ ] Arıza senaryosu 2 – Unseal başarısız:
  - Given: Restart/upgrade sonrası Vault sealed durumdadır.  
    When: Yeterli shard ile unseal denemeleri başarısız olur veya tutarsızlık
    gözlenir.  
    Then: Kullanılan shard’ları ve komutları kontrol et, gerekirse farklı
    node’da dene; sorun devam ederse bu runbook’taki notlara göre incident aç
    ve Security/Platform ekibiyle birlikte ilerle.

- [ ] Arıza senaryosu 3 – Root token misuse / compromise şüphesi:
  - Given: Root token sadece break-glass senaryosu için kullanılmalıdır.  
    When: Yetkisiz kullanım şüphesi veya sızıntı işaretleri görülür.  
    Then: Root token’ı derhal revoke et, audit loglarını incele, ilgili
    governance/incident sürecini başlat ve gelecekteki kullanım için ek
    koruma önlemlerini planla.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Vault operasyonları (rekey, unseal, root token yönetimi, bakım) bu runbook
  altında standartlaştırılmıştır.
- Başarılı operasyon için güncel shard envanteri, düzenli bakım ve sağlam
  monitoring gereklidir.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- SLO/SLA: docs/04-operations/SLO-SLA.md
- Monitoring: docs/04-operations/MONITORING/…
